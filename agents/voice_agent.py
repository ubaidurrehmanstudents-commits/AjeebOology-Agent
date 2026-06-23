#!/usr/bin/env python3
"""
Ajeebology Shorts - Voice Generation Agent
Generates male Hindi voiceover using edge-tts
"""

import os
import re
from typing import List
from dataclasses import dataclass
from logger import logger_voice
from config import config
from utils import run_command, get_audio_duration


@dataclass
class AudioSegment:
    """Audio segment with timing information."""
    segment: object  # ScriptSegment
    audio_path: str
    duration: float
    start_time: float
    end_time: float


class VoiceAgent:
    """Generates professional Hindi male voiceover."""
    
    def __init__(self):
        self.voice = config.VOICE_MODEL
        logger_voice.info(f"VoiceAgent initialized with voice: {self.voice}")
    
    def generate_voice(self, script) -> List[AudioSegment]:
        """Generate voice for each script segment with timings."""
        logger_voice.info(f"Generating voice for {len(script.segments)} segments")
        audio_segments = []
        current_time = 0.0
        
        for i, segment in enumerate(script.segments):
            logger_voice.debug(f"Processing segment {i}: {segment.segment_type}")
            tts_text = self._clean_for_tts(segment.text)
            output_path = str(config.AUDIO_DIR / f"segment_{i:02d}.mp3")
            
            success = self._generate_with_edge_tts(tts_text, output_path)
            
            if not success:
                duration = self._estimate_duration(segment.text)
                self._create_silent_audio(output_path, duration)
                logger_voice.warning(f"Using estimated duration for segment {i}: {duration:.2f}s")
            
            duration = get_audio_duration(output_path)
            
            audio_segments.append(AudioSegment(
                segment=segment,
                audio_path=output_path,
                duration=duration,
                start_time=current_time,
                end_time=current_time + duration
            ))
            
            logger_voice.debug(f"Segment {i} duration: {duration:.2f}s")
            current_time += duration
            
            # Add pause after hook
            if segment.segment_type == "hook":
                current_time += 0.3
        
        script.total_duration_estimate = current_time
        logger_voice.info(f"Total voice duration: {current_time:.2f}s")
        return audio_segments
    
    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS processing."""
        text = re.sub(r'[!]{2,}', '!', text)
        text = re.sub(r'[?]{2,}', '?', text)
        return text.strip()
    
    def _generate_with_edge_tts(self, text: str, output_path: str) -> bool:
        """Generate audio using edge-tts CLI."""
        try:
            cmd = [
                "edge-tts",
                "--voice", self.voice,
                "--text", text,
                "--write-media", output_path,
                "--rate", config.VOICE_RATE
            ]
            rc, _, err = run_command(cmd, timeout=60)
            
            if rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger_voice.debug(f"Successfully generated audio: {output_path}")
                return True
            else:
                logger_voice.warning(f"edge-tts failed: {err}")
                return False
        
        except Exception as e:
            logger_voice.error(f"edge-tts error: {e}")
            return False
    
    def _estimate_duration(self, text: str) -> float:
        """Estimate audio duration from text length (Hindi speech rate)."""
        # Average: ~2 words per second in Hindi speech
        word_count = len(text.split())
        return max(2.0, word_count / 2.5)
    
    def _create_silent_audio(self, path: str, duration: float):
        """Create silent audio as fallback."""
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration), "-acodec", "libmp3lame", "-q:a", "4", path
        ]
        rc, _, err = run_command(cmd)
        if rc != 0:
            logger_voice.error(f"Failed to create silent audio: {err}")
    
    def mix_audio(self, audio_segments: List[AudioSegment], bg_music_path: str = None) -> str:
        """Mix all voice segments with background music."""
        logger_voice.info("Mixing audio segments...")
        
        concat_list = config.AUDIO_DIR / "concat_list.txt"
        with open(concat_list, "w") as f:
            for seg in audio_segments:
                f.write(f"file '{seg.audio_path}'\n")
        
        mixed_path = str(config.AUDIO_DIR / "mixed_voice.mp3")
        
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-acodec", "libmp3lame", "-q:a", "2",
            mixed_path
        ]
        
        rc, _, err = run_command(cmd)
        if rc != 0:
            logger_voice.error(f"Audio concat failed: {err}")
            return mixed_path
        
        logger_voice.info(f"Voice mixed: {mixed_path}")
        
        # Mix with background music if provided
        if bg_music_path and os.path.exists(bg_music_path):
            final_path = str(config.AUDIO_DIR / "final_audio.mp3")
            
            cmd = [
                "ffmpeg", "-y",
                "-i", mixed_path,
                "-i", bg_music_path,
                "-filter_complex",
                f"[1:a]volume={config.MUSIC_VOLUME}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "[aout]",
                "-acodec", "libmp3lame", "-q:a", "2",
                final_path
            ]
            
            rc, _, err = run_command(cmd)
            if rc == 0:
                logger_voice.info(f"Final audio with music: {final_path}")
                return final_path
            else:
                logger_voice.warning(f"Music mixing failed: {err}. Using voice only.")
        
        return mixed_path
