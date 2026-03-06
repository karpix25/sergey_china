import ffmpeg
import os
import random
import uuid
from typing import Optional

class VideoProcessor:
    def __init__(self):
        self.output_dir = "outputs"
        os.makedirs(self.output_dir, exist_ok=True)
        self.cta_dir = "storage/cta_plates"
        os.makedirs(self.cta_dir, exist_ok=True)

    DEFAULT_SUBTITLE_STYLE = {
        'FontName': 'Arial',
        'FontSize': '14',  # Reduced from 18
        'PrimaryColour': '&H00FFFFFF', # White
        'OutlineColour': '&H00000000', # Black
        'BorderStyle': '1',
        'Outline': '1',
        'Shadow': '0',
        'Alignment': '2', # Bottom Center
        'MarginV': '25',
        'MarginL': '40',  # Force left margin so text wraps
        'MarginR': '40'   # Force right margin
    }

    # Preset definitions: ASS style + words_per_chunk
    SUBTITLE_PRESETS = {
        'classic': {
            'words_per_chunk': 5,
            'style': {
                'FontSize': '14', 'PrimaryColour': '&H00FFFFFF',
                'OutlineColour': '&H00000000', 'Outline': '1',
                'BorderStyle': '1', 'Shadow': '0',
                'Alignment': '2', 'MarginV': '30',
                'MarginL': '40', 'MarginR': '40',
            }
        },
        'word': {
            'words_per_chunk': 1,
            'style': {
                'FontSize': '20', 'PrimaryColour': '&H00FFFFFF',  # Reduced from 28
                'OutlineColour': '&H00000000', 'Outline': '2',
                'BorderStyle': '1', 'Shadow': '0',
                'Alignment': '2', 'MarginV': '60',
                'MarginL': '20', 'MarginR': '20',
            }
        },
        'karaoke': {
            'words_per_chunk': 2,
            'style': {
                'FontSize': '18', 'PrimaryColour': '&H0000FFFF',  # Yellow (Reduced from 24)
                'OutlineColour': '&H00000000', 'Outline': '2',
                'BorderStyle': '1', 'Shadow': '1',
                'Alignment': '2', 'MarginV': '40',
                'MarginL': '30', 'MarginR': '30',
            }
        },
        'mrbeast': {
            'words_per_chunk': 2,
            'style': {
                'FontName': 'Impact', 'FontSize': '24',  # Reduced from 32
                'PrimaryColour': '&H0000FFFF',  # Yellow
                'OutlineColour': '&H000000FF',  # Red
                'Outline': '3', 'BorderStyle': '1', 'Shadow': '2',
                'Alignment': '2', 'MarginV': '50',
                'MarginL': '20', 'MarginR': '20',
            }
        },
        'hormozi': {
            'words_per_chunk': 1,
            'style': {
                'FontSize': '20', 'PrimaryColour': '&H00FFFFFF',  # Reduced from 26
                'OutlineColour': '&H00000000',
                'BorderStyle': '3',  # Opaque box background
                'Outline': '0', 'Shadow': '0',
                'Alignment': '2', 'MarginV': '50',
                'MarginL': '20', 'MarginR': '20',
            }
        },
    }

    @staticmethod
    def _hex_to_ass_color(hex_color: str) -> str:
        """Convert CSS hex color (#RRGGBB) to ASS color (&H00BBGGRR)."""
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
            return f"&H00{b.upper()}{g.upper()}{r.upper()}"
        return '&H00FFFFFF'  # fallback white

    def _convert_frontend_subtitle_style(self, frontend_style: Optional[dict]) -> Optional[dict]:
        """Convert frontend subtitle_style keys to ASS format for FFmpeg.
        If a preset is specified, start from that preset's style, then apply manual overrides."""
        if not frontend_style:
            return None

        ass_style = {}

        # Apply preset base if specified
        preset_name = frontend_style.get('preset', 'classic')
        preset = self.SUBTITLE_PRESETS.get(preset_name)
        if preset:
            ass_style.update(preset['style'])

        # Manual overrides (from custom sliders if user has them)
        if 'font_size' in frontend_style:
            ass_style['FontSize'] = str(frontend_style['font_size'])
        if 'primary_color' in frontend_style:
            ass_style['PrimaryColour'] = self._hex_to_ass_color(frontend_style['primary_color'])
        
        # Handle explicitly disabled outline
        if 'has_outline' in frontend_style and frontend_style['has_outline'] is False:
            if 'Outline' in ass_style:
                ass_style['Outline'] = '0'
            if 'Shadow' in ass_style:
                ass_style['Shadow'] = '0'
        else:
            if 'outline_color' in frontend_style:
                ass_style['OutlineColour'] = self._hex_to_ass_color(frontend_style['outline_color'])
            
        if 'vertical_position' in frontend_style:
            ass_style['MarginV'] = str(frontend_style['vertical_position'])
        return ass_style if ass_style else None

    @classmethod
    def get_words_per_chunk(cls, subtitle_style: Optional[dict]) -> int:
        """Extract words_per_chunk from subtitle_style preset."""
        if not subtitle_style:
            return 5
        preset_name = subtitle_style.get('preset', 'classic')
        preset = cls.SUBTITLE_PRESETS.get(preset_name)
        return preset['words_per_chunk'] if preset else 5

    def _build_style_string(self, custom_style: Optional[dict] = None) -> str:
        style = self.DEFAULT_SUBTITLE_STYLE.copy()
        if custom_style:
            style.update(custom_style)
        return ",".join([f"{k}={v}" for k, v in style.items()])

    def _apply_overlay(self, video_stream, overlay_path: str, main_w: int, main_h: int, overlay_settings: Optional[dict] = None):
        """Apply overlay to video stream with optional position/scale settings."""
        overlay_input = ffmpeg.input(overlay_path)

        # Scale: default 100% of main_w, or user-specified percentage
        scale_pct = 100
        if overlay_settings and 'scale' in overlay_settings:
            scale_pct = max(10, min(200, int(overlay_settings['scale'])))

        # Simple scale filter using absolute width computed in python
        # e.g., if main_w=1080 and scale_pct=60, width=648
        target_w = int(main_w * scale_pct / 100)
        overlay_scaled = overlay_input.filter('scale', target_w, -1)

        # Y position: 0% = bottom, 100% = top (clamped to 0-80 on frontend)
        y_pct = 0
        if overlay_settings and 'y_position' in overlay_settings:
            y_pct = max(0, min(100, int(overlay_settings['y_position'])))

        if scale_pct == 100:
            x_expr = '0'
        else:
            # overlay filter provides 'w' and 'h' as overlay width/height
            # and 'W' and 'H' as main video width/height
            x_expr = '(W-w)/2'

        if y_pct == 0:
            y_expr = 'H-h'
        else:
            # Convert percentage to pixel offset from bottom
            y_expr = f'H-h-H*{y_pct}/100'

        return ffmpeg.overlay(video_stream, overlay_scaled, x=x_expr, y=y_expr)

    def merge_audio_and_overlay(self, video_path: str, audio_path: str, overlay_path: Optional[str] = None, target_duration: Optional[float] = None, subtitles_path: Optional[str] = None, subtitle_style: Optional[dict] = None, overlay_settings: Optional[dict] = None) -> str:
        output_filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(self.output_dir, output_filename)
        
        # Get video dimensions for overlay scaling
        probe = ffmpeg.probe(video_path)
        video_stream_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        # Handle cases where width/height might be encoded differently or rotated
        main_w = int(video_stream_info.get('width', 1080))
        main_h = int(video_stream_info.get('height', 1920))
        
        video_input = ffmpeg.input(video_path)
        original_audio = video_input.audio.filter('volume', 0.4) # Original at 40%
        voiceover_input = ffmpeg.input(audio_path)
        voiceover_audio = voiceover_input.audio.filter('volume', 1.0) # Voiceover at 100%
        
        if target_duration:
            probe = ffmpeg.probe(audio_path)
            current_duration = float(probe['format']['duration'])
            speed_factor = current_duration / target_duration
            if speed_factor != 1.0:
                # Limit atempo to valid range [0.5, 2.0] just in case
                safe_speed = max(0.5, min(2.0, speed_factor))
                voiceover_audio = voiceover_audio.filter('atempo', safe_speed)
        
        # Mix original audio with voiceover
        mixed_audio = ffmpeg.filter([original_audio, voiceover_audio], 'amix', inputs=2, duration='first')

        video_stream = video_input.video
        
        # Apply subtitles if provided — convert frontend keys to ASS format
        if subtitles_path:
            # Handle speed adjustment for subtitles if audio is being sped up
            final_srt_path = subtitles_path
            if target_duration:
                try:
                    from services.subtitles import subtitle_service
                    with open(subtitles_path, 'r', encoding='utf-8') as f:
                        srt_content = f.read()
                    
                    probe_audio = ffmpeg.probe(audio_path)
                    current_audio_dur = float(probe_audio['format']['duration'])
                    speed_factor = current_audio_dur / target_duration
                    
                    if speed_factor != 1.0:
                        adjusted_srt = subtitle_service.adjust_srt_speed(srt_content, speed_factor)
                        adjusted_path = subtitles_path.replace(".srt", "_adjusted.srt")
                        subtitle_service.save_srt(adjusted_srt, adjusted_path)
                        final_srt_path = adjusted_path
                        logger.info("  - Subtitles adjusted for speed factor %.2f", speed_factor)
                except Exception as e:
                    logger.warning("Failed to adjust SRT speed: %s", e)

            abs_subs_path = os.path.abspath(final_srt_path)
            ass_style = self._convert_frontend_subtitle_style(subtitle_style)
            style_str = self._build_style_string(ass_style)
            video_stream = video_stream.filter('subtitles', abs_subs_path, force_style=style_str)

        if overlay_path:
            video_stream = self._apply_overlay(video_stream, overlay_path, main_w, main_h, overlay_settings)

        stream = ffmpeg.output(
            video_stream,
            mixed_audio,
            output_path,
            vcodec='libx264',
            acodec='aac',
            crf=23,
            preset='fast'
        )
            
        ffmpeg.run(stream, overwrite_output=True)

        # Cleanup internal temporary assets
        if subtitles_path and target_duration and final_srt_path != subtitles_path:
            try:
                if os.path.exists(final_srt_path):
                    os.remove(final_srt_path)
            except Exception:
                pass

        return output_path

    def extract_thumbnail(self, video_path: str, output_path: str) -> bool:
        """Extract first frame from video as thumbnail."""
        try:
            (
                ffmpeg
                .input(video_path, ss=1) # Seek to 1s for a better frame than absolute 0
                .output(output_path, vframes=1)
                .run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
            )
            return True
        except Exception as e:
            print(f"Error extracting thumbnail: {e}")
            return False

    def overlay_only(self, video_path: str, overlay_path: str, overlay_settings: Optional[dict] = None) -> str:
        """Наложить CTA-плашку на видео без изменения аудио."""
        output_filename = f"{uuid.uuid4()}.mp4"
        output_path = os.path.join(self.output_dir, output_filename)

        probe = ffmpeg.probe(video_path)
        video_stream_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        main_w = int(video_stream_info.get('width', 1080))
        main_h = int(video_stream_info.get('height', 1920))

        video_input = ffmpeg.input(video_path)
        video_stream = self._apply_overlay(video_input.video, overlay_path, main_w, main_h, overlay_settings)

        stream = ffmpeg.output(
            video_stream,
            video_input.audio,
            output_path,
            vcodec='libx264',
            acodec='aac',
            crf=23,
            preset='fast',
        )
        ffmpeg.run(stream, overwrite_output=True)
        return output_path

    def get_random_cta(self) -> Optional[str]:
        """Get a random CTA overlay file path, downloading from GCS if needed."""
        from database import SessionLocal
        import models
        from services.storage import storage_service
        
        db = SessionLocal()
        try:
            overlays = db.query(models.Overlay).filter(models.Overlay.is_active == True).all()
            if not overlays:
                return None
            
            overlay = random.choice(overlays)
            local_path = overlay.file_path or os.path.join(self.cta_dir, overlay.name)
            
            # If file exists locally, use it
            if os.path.exists(local_path):
                return local_path
            
            # File missing locally — try downloading from GCS
            if overlay.gcs_path and storage_service.bucket:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                try:
                    blob_name = overlay.gcs_path.replace(f"gs://{storage_service.bucket_name}/", "")
                    storage_service.download_to_filename(blob_name, local_path)
                    print(f"  CTA downloaded from GCS: {blob_name} → {local_path}")
                    return local_path
                except Exception as e:
                    print(f"  CTA download from GCS failed: {e}")
                    return None
            
            return None
        finally:
            db.close()

video_processor = VideoProcessor()
