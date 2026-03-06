import os

class SubtitleService:
    @staticmethod
    def format_timestamp(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

    def alignments_to_srt(self, alignment: dict, words_per_chunk: int = 5) -> str:
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
            
        # Group words into subtitle chunks
        srt_lines = []
        for i in range(0, len(words), words_per_chunk):
            chunk = words[i:i + words_per_chunk]
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

    def save_srt(self, srt_content: str, output_path: str):
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)

subtitle_service = SubtitleService()
