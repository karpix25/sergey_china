import os

class SubtitleService:
    @staticmethod
    def format_timestamp(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def alignments_to_srt(self, alignment: dict, words_per_chunk: int = 1) -> str:
        """
        Converts character alignments to SRT.
        Groups characters into words, then words into chunks.
        """
        characters = alignment.get("characters", [])
        starts = alignment.get("character_start_times_seconds", [])
        ends = alignment.get("character_end_times_seconds", [])
        
        words = []
        current_word = {"text": "", "start": 0.0, "end": 0.0}
        in_word = False
        
        for i, char in enumerate(characters):
            # Very simple word boundary detection (whitespace)
            if char.isspace():
                if in_word:
                    words.append(current_word)
                    current_word = {"text": "", "start": 0.0, "end": 0.0}
                    in_word = False
            else:
                if not in_word:
                    current_word["start"] = starts[i]
                    in_word = True
                current_word["text"] += char
                current_word["end"] = ends[i]
        
        if in_word:
            words.append(current_word)
            
        # Prepare words with continuous timing (end = next start)
        continuous_words = []
        for i in range(len(words)):
            w = words[i].copy()
            if i < len(words) - 1:
                # Set end of current to start of next to avoid "blinking"
                w["end"] = words[i+1]["start"]
            continuous_words.append(w)

        # Group words into subtitle chunks
        srt_lines = []
        for i in range(0, len(continuous_words), words_per_chunk):
            chunk = continuous_words[i:i + words_per_chunk]
            if not chunk: continue
            
            chunk_index = (i // words_per_chunk) + 1
            chunk_text = " ".join([w["text"] for w in chunk])
            start_time = self.format_timestamp(chunk[0]["start"])
            end_time = self.format_timestamp(chunk[-1]["end"])
            
            srt_lines.append(f"{chunk_index}")
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(f"{chunk_text}")
            srt_lines.append("")
            
        return "\n".join(srt_lines)

    def adjust_srt_speed(self, srt_content: str, speed_factor: float) -> str:
        """Scales all timestamps in SRT content by 1/speed_factor (speeding up = shorter times)."""
        if speed_factor == 1.0 or not srt_content:
            return srt_content
        
        import re
        def scale_time(ts_match):
            h, m, s, ms = map(int, re.split('[:|,]', ts_match.group(0)))
            total_seconds = h * 3600 + m * 60 + s + ms / 1000.0
            new_seconds = total_seconds / speed_factor
            return self.format_timestamp(new_seconds)

        # Pattern matches e.g., 00:00:01,234
        timestamp_pattern = r'\d{2}:\d{2}:\d{2},\d{3}'
        return re.sub(timestamp_pattern, scale_time, srt_content)

    def save_srt(self, srt_content: str, output_path: str):
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)

subtitle_service = SubtitleService()
