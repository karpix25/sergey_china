from elevenlabs.client import ElevenLabs
import os
import uuid

class AudioService:
    def __init__(self):
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        if self.api_key:
            self.client = ElevenLabs(api_key=self.api_key)
        else:
            self.client = None

    def _save_audio(self, audio_generator) -> str:
        file_id = str(uuid.uuid4())
        os.makedirs("outputs", exist_ok=True)
        file_path = f"outputs/{file_id}.mp3"
        with open(file_path, 'wb') as f:
            for chunk in audio_generator:
                if chunk:
                    f.write(chunk)
        return file_path

    def generate_speech(self, text: str, voice_id: str = None) -> str:
        # Allow voice_id override via env variable; fallback to default "Тикток ВИДЕО"
        if voice_id is None:
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "qjDkMfBq6uC3Z1hJqiuu")
        if not self.client:
            # Fake/Mock for testing
            mock_path = "outputs/mock_audio.mp3"
            if not os.path.exists(mock_path):
                os.makedirs("outputs", exist_ok=True)
                with open(mock_path, 'w') as f: f.write("mock")
            return mock_path
            
        audio_generator = self.client.text_to_speech.convert(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2"
        )
        return self._save_audio(audio_generator)

    def generate_speech_with_timestamps(self, text: str, voice_id: str = None) -> tuple[str, dict]:
        """Generates speech and returns file path plus timestamp alignments."""
        if voice_id is None:
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "qjDkMfBq6uC3Z1hJqiuu")
        
        if not self.client:
            return "outputs/mock_audio.mp3", {"characters": list(text), "character_start_times_seconds": [0.1*i for i in range(len(text))], "character_end_times_seconds": [0.1*(i+1) for i in range(len(text))]}

        if not hasattr(self.client.text_to_speech, 'convert_with_timestamps'):
            import elevenlabs
            logger.error("ElevenLabs client (%s) missing convert_with_timestamps. Using fallback.", getattr(elevenlabs, '__version__', 'unknown'))
            return "outputs/mock_audio.mp3", {"characters": list(text), "character_start_times_seconds": [0.1*i for i in range(len(text))], "character_end_times_seconds": [0.1*(i+1) for i in range(len(text))]}

        import base64
        response = self.client.text_to_speech.convert_with_timestamps(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2"
        )
        
        # ElevenLabs v2.37.0 returns a generator of tuples: (key, value)
        # Chunk 0: ('audio_base_64', '<base64 string>')
        # Chunk 1: ('alignment', CharacterAlignmentResponseModel)
        # Chunk 2: ('normalized_alignment', CharacterAlignmentResponseModel)
        audio_bytes = b""
        alignment = None
        for chunk in response:
            if isinstance(chunk, tuple) and len(chunk) == 2:
                key, value = chunk
                if key in ("audio_base_64", "audio_base64") and value:
                    audio_bytes = base64.b64decode(value)
                elif key == "alignment" and value:
                    if hasattr(value, '__dict__'):
                        alignment = {k: v for k, v in value.__dict__.items() if not k.startswith('_')}
                    elif isinstance(value, dict):
                        alignment = value
        
        file_id = str(uuid.uuid4())
        os.makedirs("outputs", exist_ok=True)
        file_path = f"outputs/{file_id}.mp3"
        with open(file_path, 'wb') as f:
            f.write(audio_bytes)
        
        if alignment is None:
            alignment = {"characters": list(text), "character_start_times_seconds": [0.1*i for i in range(len(text))], "character_end_times_seconds": [0.1*(i+1) for i in range(len(text))]}
            
        return file_path, alignment

    def get_duration(self, file_path: str) -> float:
        try:
            import ffmpeg
            probe = ffmpeg.probe(file_path)
            return float(probe['format']['duration'])
        except Exception as e:
            print(f"Error probing audio duration: {e}")
            return 0.0

audio_service = AudioService()
