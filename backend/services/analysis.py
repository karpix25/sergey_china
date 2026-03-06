from google import genai
from google.genai.types import Part, GenerateContentConfig
from google.oauth2 import service_account
import os
import json
import re
import logging
from services.rate_limiter import gemini_rate_limiter, retry_with_backoff

logger = logging.getLogger(__name__)

class AnalysisService:
    def __init__(self):
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        location   = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        api_key    = os.getenv("GOOGLE_API_KEY")
        credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

        self.vertex_client = None
        self.studio_client = None
        self.vertex_model_id = "gemini-2.5-flash"
        self.studio_model_id = "models/gemini-2.5-flash"

        # 1. Try to set up Vertex AI
        if project_id:
            try:
                if credentials_json:
                    creds_info = json.loads(credentials_json)
                    credentials = service_account.Credentials.from_service_account_info(
                        creds_info,
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                    self.vertex_client = genai.Client(
                        vertexai=True, project=project_id, location=location, credentials=credentials
                    )
                else:
                    self.vertex_client = genai.Client(vertexai=True, project=project_id, location=location)
                print(f"Vertex AI client initialized (project={project_id})")
            except Exception as e:
                print(f"Vertex AI init error: {e}")

        # 2. Try to set up AI Studio
        if api_key:
            try:
                self.studio_client = genai.Client(api_key=api_key)
                print("AI Studio client initialized")
            except Exception as e:
                print(f"AI Studio init error: {e}")

        # Use vertex by default if available
        self.client = self.vertex_client or self.studio_client
        self.model_id = self.vertex_model_id if self.vertex_client else self.studio_model_id
        self.use_vertex = self.vertex_client is not None


    async def analyze_video(self, video_uri: str, additional_instructions: str = "") -> dict:
        print(f"DEBUG: AnalysisService.analyze_video started for {video_uri}")
        if not self.client:
            print("DEBUG: No GenAI client configured. Returning mock response.")
            return {
                "is_product": True,
                "detected_duration": 13.0,
                "script": "Этот девайс изменит твою жизнь. Стильный гаджет для ежедневного использования."
            }

        prompt = """
Ты — экспертный ИИ-редактор видеоконтента. Твоя задача: проанализировать видео и определить, является ли оно "чистой" демонстрацией физического товара.

1. КРЫТИЧЕСКОЕ ПРАВИЛО (is_product):
- Установи "is_product": false, если в ЛЮБОЙ части видео (даже на 1 секунду) появляется:
    * Интерфейс TikTok (кнопки, профиль пользователя, список подписчиков).
    * Скриншот или запись экрана телефона с магазином или ссылками.
    * Призывы "link in bio", "click the link", "order here" в виде элементов интерфейса.
    * Видео, которое начинается с показа профиля автора (как на скриншоте).
- Установи "is_product": true, ТОЛЬКО если:
    * Весь ролик целиком (от начала до конца) посвящен демонстрации реального физического предмета.
    * Нет никаких интерфейсных вставок, скриншотов профилей или магазинов.

2. ПАРАМЕТРЫ:
- "detected_duration": Длительность видео в секундах.
- "script": Текст озвучки на русском языке. 
    * ПРАВИЛО: Сразу начинай говорить о товаре и его пользе.
    * СКОРОСТЬ: Рассчитывай текст исходя из 18 символов (БЕЗ пробелов) на 1 секунду видео.
    * ЗАПРЕЩЕНО: Использовать фразы "В этом видео", "Этот ролик показывает", "Посмотрите на...", "На экране мы видим". Не ломай "четвертую стену". Ты должен рассказывать о товаре так, будто ты его используешь или советуешь другу прямо сейчас.
    * СТИЛЬ: Эмоционально, вовлекающе, без упоминания брендов.
- "product_summary": Очень короткое, "продающее" описание товара (1-2 предложения), которое подчеркивает его главную пользу или уникальность. Это НЕ сценарий озвучки, а именно текст для описания поста.

ВЫДАЙ ОТВЕТ СТРОГО В ФОРМАТЕ JSON:
{
  "is_product": false,
  "detected_duration": 15.0,
  "script": "текст озвучки",
  "product_summary": "цепляющее описание товара для поста"
}
"""
        full_prompt = prompt + (f"\nДОПОЛНИТЕЛЬНОЕ ТРЕБОВАНИЕ: {additional_instructions}" if additional_instructions else "")
        
        try:
            return await retry_with_backoff(
                self._execute_analysis,
                video_uri, full_prompt,
                max_retries=5,
                rate_limiter=gemini_rate_limiter,
            )
        except Exception as e:
            # FALLBACK LOGIC: If Vertex AI fails with Permission Denied (403), switch to AI Studio
            error_msg = str(e)
            if "403" in error_msg and self.vertex_client and self.studio_client and self.use_vertex:
                logger.warning("Vertex AI Permission Error. Falling back to AI Studio...")
                self.use_vertex = False
                self.client = self.studio_client
                self.model_id = self.studio_model_id
                return await retry_with_backoff(
                    self._execute_analysis,
                    video_uri, full_prompt,
                    max_retries=5,
                    rate_limiter=gemini_rate_limiter,
                )
            else:
                raise e

    async def _execute_analysis(self, video_uri: str, prompt: str) -> dict:
        import time
        video_part = None
        gemini_upload_path = None
        is_temp_file = False

        try:
            # 1. Prepare video part
            if video_uri.startswith("local://"):
                gemini_upload_path = video_uri.replace("local://", "")
            elif video_uri.startswith("gs://"):
                if self.use_vertex:
                    print(f"DEBUG: Vertex AI — using GCS URI directly: {video_uri}")
                    video_part = Part.from_uri(file_uri=video_uri, mime_type="video/mp4")
                else:
                    # AI Studio or fallback — download first
                    from services.storage import storage_service
                    import tempfile
                    blob_name = video_uri.replace(f"gs://{storage_service.bucket_name}/", "")
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
                    tmp_path = tmp.name
                    tmp.close()
                    print(f"DEBUG: AI Studio — downloading {video_uri} to {tmp_path}...")
                    storage_service.bucket.blob(blob_name).download_to_filename(tmp_path)
                    gemini_upload_path = tmp_path
                    is_temp_file = True
            else:
                video_part = Part.from_uri(file_uri=video_uri, mime_type="video/mp4")

            # 2. Handle upload if needed
            if gemini_upload_path:
                print(f"DEBUG: Uploading to Gemini File API: {gemini_upload_path}")
                file_obj = self.client.files.upload(file=gemini_upload_path)
                while file_obj.state.name == "PROCESSING":
                    time.sleep(2)
                    file_obj = self.client.files.get(name=file_obj.name)
                if file_obj.state.name == "FAILED":
                    raise Exception(f"Gemini File API failed: {file_obj.error}")
                video_part = Part.from_uri(file_uri=file_obj.uri, mime_type=file_obj.mime_type)

                # Cleanup temp file
                if is_temp_file and os.path.exists(gemini_upload_path):
                    os.remove(gemini_upload_path)

            # 3. Generate content
            print(f"DEBUG: Calling Gemini via {'Vertex' if self.use_vertex else 'Studio'}...")
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[video_part, prompt],
                config=GenerateContentConfig(response_mime_type="application/json")
            )

            
            raw_text = response.text
            print(f"DEBUG: Gemini raw response: {raw_text[:200]}...")
            
            # Extract JSON block
            json_text = raw_text
            if "```json" in raw_text:
                json_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                json_text = raw_text.split("```")[1].split("```")[0].strip()
            
            # Find the first { and last }
            start = json_text.find('{')
            end = json_text.rfind('}')
            if start != -1 and end != -1:
                json_text = json_text[start:end+1]
                
            data = json.loads(json_text)
        
            # CLEAN KEYS (remove quotes, newlines, spaces)
            clean_data = {}
            if isinstance(data, dict):
                for k, v in data.items():
                    # Remove quotes, newlines, and extra whitespace from key
                    clean_key = str(k).strip().strip('"').strip("'").strip()
                    # Handle potential nested or complex keys
                    clean_key = clean_key.split('\n')[-1].strip()
                    clean_data[clean_key] = v
                
            # Ensure required keys exist and have correct types
            final_result = {
                "is_product": bool(clean_data.get("is_product", False)),
                "detected_duration": float(clean_data.get("detected_duration", 0)),
                "script": str(clean_data.get("script", "")),
                "product_summary": str(clean_data.get("product_summary", ""))
            }
            print(f"DEBUG: Analysis successful: {final_result}")
            return final_result
            
        except Exception as e:
            # Propagate the exception so that the outer analyze_video can handle fallback
            print(f"DEBUG: Internal analysis failed: {e}")
            raise e

    async def rewrite_script(self, current_script: str, video_duration: float, audio_duration: float) -> str:
        """
        Rewrite an existing script to match video duration — TEXT ONLY request.
        Used on retry when audio is too short or too long.
        """
        if not self.client:
            return current_script

        is_too_long = audio_duration > video_duration
        # User specified: 180 chars (no spaces) = 10 sec -> 18 chars/sec (no spaces)
        target_chars_no_spaces = int(video_duration * 18)
        
        problem_desc = f"озвучка получилась длиннее видео ({audio_duration:.1f}s > {video_duration:.1f}s)" if is_too_long else \
                       f"озвучка получилась короче видео ({audio_duration:.1f}s < {video_duration:.1f}s)"
        
        instruction = "СОКРАТИ сценарий, убери лишние слова, сохранив основной смысл и эмоции." if is_too_long else \
                      "СДЕЛАЙ сценарий подробнее и длиннее, добавь описание преимуществ."

        prompt = f"""У нас есть сценарий озвучки для товара:
\"\"\"
{current_script}
\"\"\"

Проблема: {problem_desc}.
Задача: {instruction} 
Цель: попасть в тайминг {video_duration:.1f} сек.

Требования:
- Около {target_chars_no_spaces} символов (БЕЗ УЧЕТА ПРОБЕЛОВ)
- Только русский язык
- Без названий брендов и "четвертой стены" (не говори "в этом видео")
- Верни ТОЛЬКО текст сценария, без кавычек и пояснений"""

        try:
            async def _call_rewrite():
                return self.client.models.generate_content(
                    model=self.model_id,
                    contents=[prompt]
                )
            response = await retry_with_backoff(
                _call_rewrite,
                max_retries=3,
                rate_limiter=gemini_rate_limiter,
            )
            new_script = response.text.strip().strip('"').strip("'")
            print(f"DEBUG: Rewritten script ({len(new_script)} chars): {new_script[:80]}...")
            return new_script
        except Exception as e:
            logger.warning("rewrite_script failed: %s. Returning original.", e)
            return current_script

    async def generate_adapted_description(self, script: str, base_description: str, product_info: str = "") -> str:
        """
        Create a hybrid description based on the video analysis result and a base template.
        Uses product_info if provided, otherwise falls back to the voiceover script.
        """
        if not self.client or not base_description:
            return base_description

        context = product_info if product_info else script

        prompt = f"""У нас есть информация о товаре (это то, о чем видео):
\"\"\"
{context}
\"\"\"

Также у нас есть базовый текст/шаблон от пользователя (призыв к действию, ссылки):
\"\"\"
{base_description}
\"\"\"

Задача: напиши описание для TikTok/Reels, которое органично объединяет суть товара и текст пользователя.

Требования:
1. Текст должен быть ГИБРИДНЫМ: сначала 1-2 цепляющих предложения о самом товаре (на основе контекста выше), а затем — текст пользователя.
2. Обязательно сохрани все ссылки, хештеги и призывы из базового текста.
3. Текст должен выглядеть как естественный пост от одного лица.
4. Добавь 2-3 релевантных эмодзи.
5. Только русский язык.
6. Верни ТОЛЬКО готовый текст описания, без кавычек и пояснений."""

        try:
            async def _call_adapt():
                return self.client.models.generate_content(
                    model=self.model_id,
                    contents=[prompt]
                )
            response = await retry_with_backoff(
                _call_adapt,
                max_retries=3,
                rate_limiter=gemini_rate_limiter,
            )
            adapted_desc = response.text.strip().strip('"').strip("'")
            print(f"DEBUG: Adapted description: {adapted_desc[:50]}...")
            return adapted_desc
        except Exception as e:
            logger.warning("generate_adapted_description failed: %s. Returning base.", e)
            return base_description

analysis_service = AnalysisService()
