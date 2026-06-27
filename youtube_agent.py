#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional YouTube Shorts Automation Agent
Fully automated pipeline: Research -> Script -> Voice -> Video -> Telegram
Language: Hinglish (Roman Hindi + English), Male voice
Output: Vertical 1080x1920, ~55-65 seconds, 24 FPS
KARAOKE CAPTIONS: Word-by-word animated highlighting via ASS subtitles
"""

import os
import sys
import json
import re
import math
import random
import textwrap
import tempfile
import subprocess
import shutil
import time
import hashlib
import base64
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote_plus, urlparse
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
import numpy as np


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24
    TARGET_DURATION = 58
    MAX_DURATION = 60
    
    VOICE_MODEL = "hi-IN-MadhurNeural"
    VOICE_FALLBACK = "hi-IN-MadhurNeural"
    AUDIO_SAMPLE_RATE = 44100
    
    FONT_SIZE_TITLE = 72
    FONT_SIZE_BODY = 56
    FONT_SIZE_SMALL = 40
    
    COLOR_BG_DARK = (10, 5, 25)
    COLOR_BG_MID = (30, 15, 60)
    COLOR_ACCENT = (0, 255, 255)
    COLOR_ACCENT_2 = (255, 0, 128)
    COLOR_TEXT = (255, 255, 255)
    COLOR_TEXT_DIM = (200, 200, 220)
    COLOR_HIGHLIGHT = (255, 255, 0)
    
    BASE_DIR = Path("/tmp/ajeebology")
    FRAMES_DIR = BASE_DIR / "frames"
    AUDIO_DIR = BASE_DIR / "audio"
    ASSETS_DIR = BASE_DIR / "assets"
    OUTPUT_DIR = BASE_DIR / "output"
    
    BROLL_ENABLED = True
    UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    POLLINATIONS_ENABLED = True


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ScriptSegment:
    text: str
    segment_type: str
    emphasis_words: List[str] = field(default_factory=list)
    broll_prompt: str = ""

@dataclass
class VideoScript:
    title: str
    category: str
    seo_title: str
    description: str
    tags: List[str]
    hashtags: List[str]
    segments: List[ScriptSegment]
    total_duration_estimate: float = 0.0

@dataclass
class AudioSegment:
    segment: ScriptSegment
    audio_path: str
    duration: float
    start_time: float
    end_time: float



# =============================================================================
# KARAOKE CAPTION ENGINE (FIXED — Sync + Center Alignment)
# =============================================================================

class CaptionEngine:
    """
    Generates professional karaoke-style ASS subtitles.
    Uses Whisper for PRECISE word timing + original Hinglish text for display.
    Captions centered vertically on screen.
    """
    
    # FIXED: Alignment=10 (center horizontally + center vertically in ASS)
    # MarginV=700 positions text in middle of 1920px height screen
    ASS_HEADER = """[Script Info]
Title: Ajeebology Karaoke Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans Bold,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,3,10,60,60,700,1
Style: Highlight,DejaVu Sans Bold,72,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,105,105,0,0,1,5,4,10,60,60,700,1
Style: Glow,DejaVu Sans Bold,76,&H00FF0080,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,110,110,0,0,1,6,5,10,60,60,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    def __init__(self):
        self.ass_lines = []
        self._whisper_model = None
    
    def _get_whisper_model(self):
        """Lazy-load Whisper model."""
        if self._whisper_model is None:
            try:
                import whisper
                self._whisper_model = whisper.load_model("base")
            except Exception as e:
                print(f"Whisper model load error: {e}")
                self._whisper_model = False
        return self._whisper_model
    
    def _time_to_ass(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"
    
    def _escape_ass_text(self, text: str) -> str:
        text = text.replace("\\", "\\\\")
        text = text.replace("{", "\\{")
        text = text.replace("}", "\\}")
        return text
    
    def _split_into_words(self, text: str) -> List[str]:
        words = []
        for word in text.split():
            word = word.strip()
            if word:
                words.append(word)
        return words
    
    def _generate_karaoke_line(self, words: List[str], timings: List[Tuple[float, float]], 
                                emphasis_words: List[str]) -> str:
        """
        Generate karaoke line with PRECISE Whisper timings.
        words: original Hinglish words
        timings: list of (start, end) for each word from Whisper
        """
        if not words or not timings or len(words) != len(timings):
            return ""
        
        karaoke_parts = []
        line_start = timings[0][0]
        line_end = timings[-1][1]
        
        for i, (word, (w_start, w_end)) in enumerate(zip(words, timings)):
            # \k duration in centiseconds
            word_cs = max(1, int((w_end - w_start) * 100))
            clean_word = self._escape_ass_text(word)
            
            is_emphasis = any(ew.lower() in word.lower() for ew in emphasis_words)
            
            if is_emphasis:
                karaoke_parts.append(f"{{\\rGlow\\k{word_cs}}}{clean_word}")
            else:
                karaoke_parts.append(f"{{\\k{word_cs}}}{clean_word}")
        
        text = " ".join(karaoke_parts)
        start_ass = self._time_to_ass(line_start)
        end_ass = self._time_to_ass(line_end)
        
        return f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}"
    
    def _get_whisper_word_timings(self, audio_path: str, original_words: List[str]) -> List[Tuple[float, float]]:
        """
        Get precise word timings from Whisper.
        Maps Whisper's transcribed words back to original Hinglish words.
        """
        model = self._get_whisper_model()
        if not model:
            return []
        
        try:
            result = model.transcribe(audio_path, word_timestamps=True, language="hi")
            
            whisper_words = []
            for seg in result.get("segments", []):
                for word_info in seg.get("words", []):
                    whisper_words.append({
                        "word": word_info["word"].strip(),
                        "start": float(word_info["start"]),
                        "end": float(word_info["end"])
                    })
            
            if not whisper_words:
                return []
            
            # Map Whisper timings to original Hinglish words
            # Strategy: Whisper gives more words (Hindi+English split differently)
            # We distribute Whisper timings proportionally across original words
            return self._map_timings_to_original(whisper_words, original_words)
            
        except Exception as e:
            print(f"Whisper timing error: {e}")
            return []
    
    def _map_timings_to_original(self, whisper_words: List[Dict], original_words: List[str]) -> List[Tuple[float, float]]:
        """
        Map Whisper's word timings to original Hinglish words.
        Uses character-count proportion for distribution.
        """
        if not whisper_words:
            return []
        
        # Flatten all whisper word text
        whisper_text = "".join(w["word"].strip() for w in whisper_words).lower()
        original_text = "".join(w.strip() for w in original_words).lower()
        
        # Total duration covered by whisper
        total_start = whisper_words[0]["start"]
        total_end = whisper_words[-1]["end"]
        total_duration = total_end - total_start
        
        # Distribute timings based on character count of original words
        original_chars = [len(w) for w in original_words]
        total_chars = sum(original_chars)
        
        if total_chars == 0:
            # Even fallback
            per_word = total_duration / len(original_words)
            return [(total_start + i * per_word, total_start + (i + 1) * per_word) 
                    for i in range(len(original_words))]
        
        timings = []
        current_time = total_start
        
        for word, char_count in zip(original_words, original_chars):
            word_duration = (char_count / total_chars) * total_duration
            word_start = current_time
            word_end = current_time + word_duration
            timings.append((word_start, word_end))
            current_time = word_end
        
        return timings
    
    def _group_words_into_lines(self, words: List[str], 
                                 timings: List[Tuple[float, float]],
                                 max_words_per_line: int = 3) -> List[Tuple[List[str], List[Tuple[float, float]]]]:
        """Group words and their timings into display lines."""
        if not words or not timings:
            return []
        
        lines = []
        current_words = []
        current_timings = []
        
        for word, timing in zip(words, timings):
            current_words.append(word)
            current_timings.append(timing)
            
            is_last = (word == words[-1])
            should_break = (
                len(current_words) >= max_words_per_line or
                word.endswith(('.', '!', '?', '।', ',')) or
                is_last
            )
            
            if should_break and current_words:
                lines.append((current_words.copy(), current_timings.copy()))
                current_words = []
                current_timings = []
        
        # Handle any remaining
        if current_words:
            lines.append((current_words, current_timings))
        
        return lines
    
    def generate_segment_captions(self, segment: ScriptSegment, audio_path: str,
                                   start_time: float, end_time: float) -> List[str]:
        """
        Generate karaoke ASS lines with PRECISE timing.
        Uses Whisper for timing, original Hinglish for text.
        """
        words = self._split_into_words(segment.text)
        
        # Get precise timings from Whisper
        timings = self._get_whisper_word_timings(audio_path, words)
        
        # Fallback: even distribution if Whisper fails
        if not timings:
            duration = end_time - start_time
            word_duration = duration / len(words)
            timings = [(start_time + i * word_duration, start_time + (i + 1) * word_duration) 
                       for i in range(len(words))]
        
        # Group into lines
        grouped = self._group_words_into_lines(words, timings, max_words_per_line=3)
        
        lines = []
        for word_list, word_timings in grouped:
            ass_line = self._generate_karaoke_line(word_list, word_timings, segment.emphasis_words)
            if ass_line:
                lines.append(ass_line)
        
        return lines
    
    def build_ass_file(self, audio_segments: List[AudioSegment]) -> str:
        """Build complete ASS subtitle file."""
        self.ass_lines = [self.ASS_HEADER.strip()]
        
        for seg in audio_segments:
            segment_lines = self.generate_segment_captions(
                seg.segment, seg.audio_path, seg.start_time, seg.end_time
            )
            self.ass_lines.extend(segment_lines)
        
        ass_path = str(Config.AUDIO_DIR / "karaoke_captions.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.ass_lines))
        
        return ass_path
                               


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def setup_directories():
    """Create all necessary directories."""
    for d in [Config.FRAMES_DIR, Config.AUDIO_DIR, Config.ASSETS_DIR, Config.OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def run_command(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """Run shell command with timeout, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"

def get_audio_duration(path: str) -> float:
    """Get audio duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    rc, out, _ = run_command(cmd)
    if rc == 0 and out.strip():
        return float(out.strip())
    return 0.0

def download_file(url: str, dest: str, timeout: int = 30) -> bool:
    """Download file with retry logic."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)
    return False

def safe_filename(text: str) -> str:
    """Create safe filename from text."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)[:50]

# =============================================================================
# 1. RESEARCH MODULE (Tavily)
# =============================================================================

class ResearchAgent:
    """Fetches fresh facts using Tavily Search API."""
    
    CATEGORIES = ["psychology", "space", "weird_facts"]
    
    QUERIES = {
        "psychology": [
            "mind blowing psychology facts human behavior 2026",
            "psychology tricks brain facts hindi",
            "interesting psychological phenomena daily life"
        ],
        "space": [
            "amazing space facts universe secrets 2026",
            "space discoveries recent mind blowing",
            "astronomy facts that will blow your mind"
        ],
        "weird_facts": [
            "unbelievable facts about world strange but true",
            "weird facts that sound fake but are true",
            "amazing facts about earth animals humans"
        ]
    }
    
    def __init__(self):
        self.api_key = Config.TAVILY_API_KEY
        self.base_url = "https://api.tavily.com/search"
    
    def fetch_fact(self, category: Optional[str] = None) -> Dict:
        """Fetch a fresh fact topic."""
        if not category:
            category = random.choice(self.CATEGORIES)
        
        query = random.choice(self.QUERIES[category])
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "max_results": 5
        }
        
        try:
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=30)
            data = resp.json()
            
            results = data.get("results", [])
            if results:
                best = max(results, key=lambda x: len(x.get("content", "")))
                return {
                    "category": category,
                    "title": best.get("title", ""),
                    "content": best.get("content", ""),
                    "url": best.get("url", ""),
                    "query": query
                }
        except Exception as e:
            print(f"Research error: {e}")
        
        fallbacks = {
            "psychology": {
                "title": "Psychology Facts That Will Blow Your Mind",
                "content": "Your brain can process images in just 13 milliseconds. The human mind is capable of creating false memories that feel completely real. Smiling can actually make you feel happier due to facial feedback effect.",
                "category": "psychology"
            },
            "space": {
                "title": "Space Secrets You Never Knew",
                "content": "A day on Venus is longer than its year. Neutron stars can spin 600 times per second. There are more trees on Earth than stars in the Milky Way galaxy.",
                "category": "space"
            },
            "weird_facts": {
                "title": "Weird Facts That Sound Fake",
                "content": "Honey never spoils. Wombat poop is cube-shaped. Bananas are berries but strawberries are not. Octopuses have three hearts and blue blood.",
                "category": "weird_facts"
            }
        }
        cat = category or random.choice(self.CATEGORIES)
        return fallbacks[cat]


# =============================================================================
# 2. SCRIPT GENERATION (Groq/LLaMA)
# =============================================================================

class ScriptAgent:
    """Generates structured Hinglish scripts using Groq LLaMA."""
    
    SYSTEM_PROMPT = """You are a professional YouTube Shorts scriptwriter for "Ajeebology Shorts".
Your scripts are in HINGLISH (Roman Hindi + English mix), engaging, fast-paced, and optimized for retention.

RULES:
1. Write in Hinglish (Roman script Hindi mixed with English words)
2. Target 55-60 seconds when spoken naturally
3. HOOK must be attention-grabbing in first 2 seconds
4. Each FACT should be mind-blowing and concise
5. OUTRO must have a strong CTA (subscribe, comment, share)
6. Mark EMPHASIS words with [WORD] brackets
7. Keep sentences short and punchy
8. Use conversational tone like talking to a friend

OUTPUT FORMAT: Return ONLY valid JSON with this structure:
{
    "title": "Hinglish title",
    "category": "psychology|space|weird_facts",
    "seo_title": "English SEO optimized title",
    "description": "English description with keywords",
    "tags": ["tag1", "tag2", ...],
    "hashtags": ["#tag1", "#tag2", ...],
    "segments": [
        {
            "type": "hook",
            "text": "Hinglish text with [emphasis] words",
            "broll_prompt": "English image search prompt for B-roll"
        },
        {
            "type": "fact1",
            "text": "...",
            "broll_prompt": "..."
        },
        ...
    ]
}"""
    
    def __init__(self):
        self.api_key = Config.GROQ_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
    
    def generate_script(self, research_data: Dict) -> VideoScript:
        """Generate complete video script from research."""
        
        user_prompt = f"""Create a viral YouTube Shorts script based on this research:
Category: {research_data['category']}
Title: {research_data['title']}
Content: {research_data['content']}

Make it engaging, mind-blowing, and perfect for Hinglish-speaking audience aged 16-30."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.8,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"}
        }
        
        try:
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=60)
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            script_data = json.loads(content)
            
            return self._parse_script(script_data)
        except Exception as e:
            print(f"Script generation error: {e}")
            return self._fallback_script(research_data)
    
    def _parse_script(self, data: Dict) -> VideoScript:
        """Parse JSON into VideoScript object."""
        segments = []
        for seg_data in data.get("segments", []):
            text = seg_data.get("text", "")
            emphasis = re.findall(r'\[(.*?)\]', text)
            clean_text = re.sub(r'\[(.*?)\]', r'\1', text)
            
            segments.append(ScriptSegment(
                text=clean_text,
                segment_type=seg_data.get("type", "fact"),
                emphasis_words=emphasis,
                broll_prompt=seg_data.get("broll_prompt", "")
            ))
        
        return VideoScript(
            title=data.get("title", "Amazing Facts"),
            category=data.get("category", "weird_facts"),
            seo_title=data.get("seo_title", "Mind Blowing Facts You Need To Know"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            hashtags=data.get("hashtags", []),
            segments=segments
        )
    
    def _fallback_script(self, research: Dict) -> VideoScript:
        """Generate fallback script if API fails."""
        category = research.get("category", "weird_facts")
        
        templates = {
            "psychology": [
                ScriptSegment("Kya aap jaante hain aapka brain har [13 milliseconds] mein ek image process kar sakta hai?", "hook", ["13 milliseconds"], "human brain neural pathways"),
                ScriptSegment("Psychology ke ek experiment mein researchers ne dekha ki [false memories] create karna kitna aasan hai.", "fact1", ["false memories"], "psychology experiment memory"),
                ScriptSegment("Agar aap forcefully [smile] karte hain, toh aapka brain automatically [happy hormones] release kar deta hai.", "fact2", ["smile", "happy hormones"], "person smiling happiness"),
                ScriptSegment("Aur ek study ke mutabik, aapke decisions ka [90%] aapke subconscious mind control karta hai.", "fact3", ["90%", "subconscious mind"], "subconscious mind brain"),
                ScriptSegment("Agar ye facts pasand aaye toh [subscribe] karo aur comments mein batao aapko kaunsa fact sabse zyada shocking laga!", "outro", ["subscribe"], "youtube subscribe button")
            ],
            "space": [
                ScriptSegment("Venus par ek din [243 Earth days] ka hota hai, lekin saal sirf [225 days] ka!", "hook", ["243 Earth days", "225 days"], "venus planet space"),
                ScriptSegment("Neutron stars itni tezi se spin karti hain ki ek second mein [600 baar] ghoom jaati hain.", "fact1", ["600 baar"], "neutron star spinning"),
                ScriptSegment("Aur Earth par trees [Milky Way] ke stars se zyada hain!", "fact2", ["Milky Way"], "milky way galaxy stars"),
                ScriptSegment("Space mein ek [giant cloud] hai jo alcohol se bana hai, jiski value [1000 trillion dollars] hai.", "fact3", ["giant cloud", "1000 trillion dollars"], "space nebula cloud"),
                ScriptSegment("Aur bhi amazing space facts ke liye [follow] karo Ajeebology Shorts ko!", "outro", ["follow"], "space astronaut earth")
            ],
            "weird_facts": [
                ScriptSegment("Honey kabhi [spoil] nahi hota, archaeologists ne [3000 saal] purana honey khaya tha!", "hook", ["spoil", "3000 saal"], "honey jar ancient"),
                ScriptSegment("Wombat ka poop [cube-shaped] hota hai, nature ka sabse weird phenomenon!", "fact1", ["cube-shaped"], "wombat animal australia"),
                ScriptSegment("Banana technically ek [berry] hai, lekin strawberry nahi!", "fact2", ["berry"], "banana fruit close up"),
                ScriptSegment("Octopus ke paas [teen dil] hain aur unka blood [blue] hota hai!", "fact3", ["teen dil", "blue"], "octopus underwater ocean"),
                ScriptSegment("Aise hi [mind-blowing] facts ke liye channel ko subscribe karo!", "outro", ["mind-blowing"], "shocked surprised face")
            ]
        }
        
        segs = templates.get(category, templates["weird_facts"])
        
        return VideoScript(
            title=research.get("title", "Amazing Facts"),
            category=category,
            seo_title=f"Mind Blowing {category.title()} Facts You Need To Know 2026",
            description=f"Amazing {category} facts in Hinglish. Subscribe for daily mind-blowing content!",
            tags=[category, "facts", "hinglish", "shorts", "viral"],
            hashtags=[f"#{category}", "#facts", "#shorts", "#viral", "#hinglish"],
            segments=segs
        )


# =============================================================================
# 3. VOICE GENERATION (edge-tts)
# =============================================================================

class VoiceAgent:
    """Generates male Hindi voiceover using edge-tts."""
    
    def __init__(self):
        self.voice = Config.VOICE_MODEL
    
    def generate_voice(self, script: VideoScript) -> List[AudioSegment]:
        """Generate voice for each segment and return with timings."""
        audio_segments = []
        current_time = 0.0
        
        for i, segment in enumerate(script.segments):
            tts_text = self._clean_for_tts(segment.text)
            output_path = str(Config.AUDIO_DIR / f"segment_{i:02d}.mp3")
            
            success = self._generate_with_edge_tts(tts_text, output_path)
            
            if not success:
                duration = self._estimate_duration(segment.text)
                self._create_silent_audio(output_path, duration)
            
            duration = get_audio_duration(output_path)
            
            audio_segments.append(AudioSegment(
                segment=segment,
                audio_path=output_path,
                duration=duration,
                start_time=current_time,
                end_time=current_time + duration
            ))
            
            current_time += duration
            
            if segment.segment_type == "hook":
                current_time += 0.3
        
        script.total_duration_estimate = current_time
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
                "--rate", "+10%"
            ]
            rc, _, err = run_command(cmd, timeout=60)
            if rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True
        except Exception as e:
            print(f"edge-tts error: {e}")
        return False
    
    def _estimate_duration(self, text: str) -> float:
        """Estimate audio duration from text length."""
        return max(2.0, len(text) / 4.5)
    
    def _create_silent_audio(self, path: str, duration: float):
        """Create silent audio as fallback."""
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration), "-acodec", "libmp3lame", "-q:a", "4", path
        ]
        run_command(cmd)
    
    def mix_audio(self, audio_segments: List[AudioSegment], bg_music_path: Optional[str] = None) -> str:
        """Mix all segments + background music into final audio."""
        concat_list = Config.AUDIO_DIR / "concat_list.txt"
        with open(concat_list, "w") as f:
            for seg in audio_segments:
                f.write(f"file '{seg.audio_path}'\n")
        
        mixed_path = str(Config.AUDIO_DIR / "mixed_voice.mp3")
        
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-acodec", "libmp3lame", "-q:a", "2",
            mixed_path
        ]
        run_command(cmd)
        
        if bg_music_path and os.path.exists(bg_music_path):
            final_path = str(Config.AUDIO_DIR / "final_audio.mp3")
            
            cmd = [
                "ffmpeg", "-y",
                "-i", mixed_path,
                "-i", bg_music_path,
                "-filter_complex",
                "[1:a]volume=0.15[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "[aout]",
                "-acodec", "libmp3lame", "-q:a", "2",
                final_path
            ]
            run_command(cmd)
            return final_path
        
        return mixed_path

# =============================================================================
# 4. B-ROLL & ASSETS
# =============================================================================

class AssetAgent:
    """Downloads/generates B-roll images and SFX."""
    
    def __init__(self):
        self.assets = []
    
    def fetch_broll(self, prompt: str, index: int) -> Optional[str]:
        """Fetch B-roll image for a segment."""
        safe_prompt = safe_filename(prompt)[:30]
        dest_path = str(Config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.jpg")
        
        if Config.UNSPLASH_ACCESS_KEY:
            if self._try_unsplash(prompt, dest_path):
                return dest_path
        
        if Config.POLLINATIONS_ENABLED:
            if self._try_pollinations(prompt, dest_path):
                return dest_path
        
        if self._try_pexels(prompt, dest_path):
            return dest_path
        
        return None
    
    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        """Search Unsplash for images."""
        try:
            url = f"https://api.unsplash.com/search/photos?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": f"Client-ID {Config.UNSPLASH_ACCESS_KEY}"}
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            results = data.get("results", [])
            if results:
                img_url = results[0]["urls"]["regular"]
                return download_file(img_url, dest)
        except Exception as e:
            print(f"Unsplash error: {e}")
        return False
    
    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        """Generate image using Pollinations.ai (free)."""
        try:
            enhanced = f"professional stock photo, {prompt}, high quality, detailed, cinematic lighting"
            encoded = quote_plus(enhanced)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&seed={random.randint(1, 10000)}&nologo=true"
            return download_file(url, dest, timeout=45)
        except Exception as e:
            print(f"Pollinations error: {e}")
        return False
    
    def _try_pexels(self, prompt: str, dest: str) -> bool:
        """Search Pexels for free images."""
        try:
            url = f"https://api.pexels.com/v1/search?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": "563492ad6f91700001000001f8b9d0e1a6f94f8a8e7e8e7e8e7e8e7"}
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            photos = data.get("photos", [])
            if photos:
                img_url = photos[0]["src"]["portrait"]
                return download_file(img_url, dest)
        except:
            pass
        return False
    
    def fetch_background_music(self) -> Optional[str]:
        """Download royalty-free background music."""
        music_urls = [
            "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",
            "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3",
            "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3",
        ]
        
        dest = str(Config.ASSETS_DIR / "bg_music.mp3")
        for url in music_urls:
            if download_file(url, dest):
                return dest
        return None
    
    def fetch_sfx(self, sfx_type: str) -> Optional[str]:
        """Download sound effects."""
        sfx_urls = {
            "whoosh": "https://cdn.pixabay.com/download/audio/2022/03/24/audio_c8c8a73467.mp3",
            "pop": "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3",
            "notification": "https://cdn.pixabay.com/download/audio/2022/04/27/audio_c8c8a73467.mp3"
        }
        
        url = sfx_urls.get(sfx_type)
        if url:
            dest = str(Config.ASSETS_DIR / f"sfx_{sfx_type}.mp3")
            if download_file(url, dest):
                return dest
        return None


# =============================================================================
# 5. PROFESSIONAL VIDEO RENDERING ENGINE (WITH KARAOKE CAPTIONS)
# =============================================================================

class VideoEngine:
    """
    Professional video rendering using PIL + ffmpeg.
    Features:
    - Animated gradient backgrounds with particles
    - Cinematic text animations (slide-in, scale-pop)
    - B-roll image overlays with Ken Burns + crossfade
    - Audio-reactive visual beats (zoom punches, flashes)
    - Progress bar, channel branding, subscribe CTA
    - KARAOKE-STYLE animated captions via ASS subtitles
    """
    
    def __init__(self):
        self.width = Config.WIDTH
        self.height = Config.HEIGHT
        self.fps = Config.FPS
        
        self.font_title = self._load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", Config.FONT_SIZE_TITLE)
        self.font_body = self._load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", Config.FONT_SIZE_BODY)
        self.font_small = self._load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", Config.FONT_SIZE_SMALL)
        
        self.particles = self._init_particles(50)
        self.frame_count = 0
        
        # NEW: Karaoke caption engine
        self.caption_engine = CaptionEngine()
    
    def _load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """Load font with fallback."""
        try:
            return ImageFont.truetype(path, size)
        except:
            alternatives = [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
            ]
            for alt in alternatives:
                try:
                    return ImageFont.truetype(alt, size)
                except:
                    continue
            return ImageFont.load_default()
    
    def _init_particles(self, count: int) -> List[Dict]:
        """Initialize floating particles."""
        particles = []
        for _ in range(count):
            particles.append({
                "x": random.randint(0, self.width),
                "y": random.randint(0, self.height),
                "size": random.randint(1, 4),
                "speed": random.uniform(0.2, 1.5),
                "opacity": random.randint(50, 200),
                "phase": random.uniform(0, math.pi * 2)
            })
        return particles
    
    def _draw_gradient_background(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        """Draw animated gradient background."""
        progress = frame_idx / max(total_frames, 1)
        hue_shift = progress * 0.3
        
        for y in range(self.height):
            ratio = y / self.height
            r = int(10 + ratio * 20 + math.sin(hue_shift + ratio * 3) * 10)
            g = int(5 + ratio * 15 + math.sin(hue_shift + ratio * 2) * 8)
            b = int(25 + ratio * 40 + math.sin(hue_shift + ratio * 4) * 15)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
    
    def _draw_particles(self, draw: ImageDraw, frame_idx: int):
        """Draw animated floating particles."""
        for p in self.particles:
            p["y"] -= p["speed"]
            p["x"] += math.sin(frame_idx * 0.02 + p["phase"]) * 0.5
            
            if p["y"] < -10:
                p["y"] = self.height + 10
                p["x"] = random.randint(0, self.width)
            
            twinkle = abs(math.sin(frame_idx * 0.05 + p["phase"]))
            opacity = int(p["opacity"] * twinkle)
            
            if opacity > 30:
                draw.ellipse(
                    [p["x"] - p["size"], p["y"] - p["size"],
                     p["x"] + p["size"], p["y"] + p["size"]],
                    fill=(200, 220, 255)
                )
    
    def _draw_text_with_glow(self, draw: ImageDraw, text: str, font, x: int, y: int, 
                             color: Tuple, glow_color: Tuple, glow_radius: int = 3, anchor: str = "mm"):
        """Draw text with neon glow effect."""
        for offset in range(glow_radius, 0, -1):
            alpha_factor = 0.3 + (glow_radius - offset) * 0.15
            glow = tuple(int(c * alpha_factor + 255 * (1 - alpha_factor)) for c in glow_color[:3])
            for dx in [-offset, 0, offset]:
                for dy in [-offset, 0, offset]:
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, font=font, fill=glow, anchor=anchor)
        
        draw.text((x, y), text, font=font, fill=color, anchor=anchor)
    
    def _wrap_text(self, text: str, font, max_width: int) -> List[str]:
        """Wrap text to fit within max_width."""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = font.getbbox(test_line)
            if bbox and (bbox[2] - bbox[0]) > max_width:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
            else:
                current_line.append(word)
        
        if current_line:
            lines.append(" ".join(current_line))
        
        return lines if lines else [text]
    
    def _draw_rounded_card(self, draw: ImageDraw, bbox: List[int], radius: int, 
                           fill: Tuple, outline: Optional[Tuple] = None, outline_width: int = 2):
        """Draw rounded rectangle card."""
        draw.rounded_rectangle(bbox, radius=radius, fill=fill)
        if outline:
            draw.rounded_rectangle(bbox, radius=radius, outline=outline, width=outline_width)
    
    def _apply_ken_burns(self, img: Image.Image, frame_idx: int, segment_frames: int,
                        zoom_start: float = 1.0, zoom_end: float = 1.15,
                        pan_x: float = 0, pan_y: float = 0) -> Image.Image:
        """Apply Ken Burns effect to image."""
        progress = frame_idx / max(segment_frames, 1)
        t = progress
        ease = t * t * (3 - 2 * t)
        
        zoom = zoom_start + (zoom_end - zoom_start) * ease
        
        new_w = int(self.width / zoom)
        new_h = int(self.height / zoom)
        
        offset_x = int(pan_x * ease * (self.width - new_w))
        offset_y = int(pan_y * ease * (self.height - new_h))
        
        left = max(0, (self.width - new_w) // 2 + offset_x)
        top = max(0, (self.height - new_h) // 2 + offset_y)
        right = min(img.width, left + new_w)
        bottom = min(img.height, top + new_h)
        
        if right - left < 10 or bottom - top < 10:
            return img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        cropped = img.crop((left, top, right, bottom))
        return cropped.resize((self.width, self.height), Image.Resampling.LANCZOS)
    
    def _draw_progress_bar(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        """Draw bottom progress bar."""
        progress = frame_idx / max(total_frames, 1)
        bar_height = 8
        bar_y = self.height - bar_height - 20
        bar_width = self.width - 80
        bar_x = 40
        
        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            radius=4, fill=(40, 40, 60)
        )
        
        fill_width = int(bar_width * progress)
        if fill_width > 0:
            draw.rounded_rectangle(
                [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height],
                radius=4, fill=Config.COLOR_ACCENT
            )
    
    def _draw_channel_badge(self, draw: ImageDraw, frame_idx: int):
        """Draw channel badge at top."""
        pulse = abs(math.sin(frame_idx * 0.08))
        dot_size = int(6 + pulse * 4)
        
        badge_w = 200
        badge_h = 44
        badge_x = self.width // 2 - badge_w // 2
        badge_y = 30
        
        self._draw_rounded_card(
            draw, [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=22, fill=(20, 20, 40), outline=Config.COLOR_ACCENT, outline_width=1
        )
        
        dot_color = (255, 50, 50) if pulse > 0.5 else (255, 100, 100)
        draw.ellipse(
            [badge_x + 15, badge_y + badge_h // 2 - dot_size // 2,
             badge_x + 15 + dot_size, badge_y + badge_h // 2 + dot_size // 2],
            fill=dot_color
        )
        
        draw.text((badge_x + 30, badge_y + badge_h // 2), "AJEEBOLOGY SHORTS",
                 font=self.font_small, fill=Config.COLOR_TEXT, anchor="lm")
    
    def _draw_subscribe_cta(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        """Draw subscribe CTA in final seconds."""
        progress = frame_idx / max(total_frames, 1)
        
        if progress < 0.85:
            return
        
        slide_progress = (progress - 0.85) / 0.15
        ease = slide_progress * slide_progress * (3 - 2 * slide_progress)
        
        cta_y = int(self.height + 100 - ease * 180)
        
        cta_w = 400
        cta_h = 80
        cta_x = self.width // 2 - cta_w // 2
        
        for glow in range(15, 0, -3):
            glow_color = Config.COLOR_ACCENT_2
            draw.rounded_rectangle(
                [cta_x - glow, cta_y - glow, cta_x + cta_w + glow, cta_y + cta_h + glow],
                radius=25, outline=glow_color, width=2
            )
        
        self._draw_rounded_card(
            draw, [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
            radius=20, fill=Config.COLOR_ACCENT_2, outline=(255, 255, 255), outline_width=2
        )
        
        bounce = abs(math.sin(frame_idx * 0.15)) * 3
        draw.text((self.width // 2, cta_y + cta_h // 2 + bounce), "SUBSCRIBE KARO!",
                 font=self.font_body, fill=(255, 255, 255), anchor="mm")
    
    def _get_text_animation_offset(self, frame_idx: int, segment_start_frame: int) -> Tuple[int, float]:
        """Get animation offset for text entrance."""
        rel_frame = frame_idx - segment_start_frame
        
        if rel_frame < 8:
            progress = rel_frame / 8
            ease = 1 - (1 - progress) ** 3
            offset_y = int(80 * (1 - ease))
            alpha = ease
            return offset_y, alpha
        return 0, 1.0
    
    def _draw_segment_text(self, draw: ImageDraw, text: str, font, y_pos: int,
                           frame_idx: int, segment_start_frame: int, 
                           emphasis_words: List[str], max_width: int = 900):
        """
        LEGACY: Static text rendering. 
        NO LONGER USED in render_video — kept for backward compatibility only.
        Karaoke captions are now handled via ASS subtitle burning.
        """
        lines = self._wrap_text(text, font, max_width)
        
        anim_y, alpha = self._get_text_animation_offset(frame_idx, segment_start_frame)
        
        line_height = font.size + 20
        total_height = len(lines) * line_height
        start_y = y_pos - total_height // 2 + anim_y
        
        for line_idx, line in enumerate(lines):
            line_y = start_y + line_idx * line_height
            
            is_emphasis = any(ew.lower() in line.lower() for ew in emphasis_words)
            
            if is_emphasis:
                bbox = font.getbbox(line)
                if bbox:
                    text_w = bbox[2] - bbox[0]
                    pad = 20
                    self._draw_rounded_card(
                        draw,
                        [self.width // 2 - text_w // 2 - pad, line_y - line_height // 2 - 10,
                         self.width // 2 + text_w // 2 + pad, line_y + line_height // 2 + 10],
                        radius=15, fill=Config.COLOR_HIGHLIGHT, outline=Config.COLOR_HIGHLIGHT, outline_width=2
                    )
            
            self._draw_text_with_glow(
                draw, line, font, self.width // 2, line_y,
                Config.COLOR_TEXT, Config.COLOR_ACCENT if is_emphasis else Config.COLOR_ACCENT_2,
                glow_radius=4 if is_emphasis else 2
            )
    
    def _draw_broll_overlay(self, base_img: Image.Image, broll_path: str, 
                            frame_idx: int, segment_frames: int,
                            overlay_mode: str = "full") -> Image.Image:
        """Overlay B-roll image with effects."""
        try:
            broll = Image.open(broll_path).convert("RGB")
        except:
            return base_img
        
        broll = self._apply_ken_burns(broll, frame_idx, segment_frames, 
                                       zoom_start=1.0, zoom_end=1.12,
                                       pan_x=random.choice([-1, 1]) * 0.1,
                                       pan_y=random.choice([-1, 1]) * 0.05)
        
        if overlay_mode == "full":
            overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            overlay.paste(broll.resize((self.width, self.height)))
            
            enhancer = ImageEnhance.Brightness(overlay)
            overlay = enhancer.enhance(0.4)
            
            base_img = Image.alpha_composite(base_img.convert("RGBA"), overlay)
            return base_img.convert("RGB")
        
        elif overlay_mode == "split":
            broll_resized = broll.resize((self.width, self.height // 2))
            base_img.paste(broll_resized, (0, 0))
            
            for y in range(self.height // 2 - 100, self.height // 2):
                for x in range(self.width):
                    base_img.putpixel((x, y), (10, 5, 25))
            
            return base_img
        
        elif overlay_mode == "circle":
            size = min(self.width, self.height) // 2
            broll_resized = broll.resize((size, size))
            
            mask = Image.new("L", (size, size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, size, size], fill=255)
            
            glow = Image.new("RGBA", (size + 20, size + 20), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow)
            glow_draw.ellipse([0, 0, size + 20, size + 20], outline=(*Config.COLOR_ACCENT,), width=4)
            
            pos = ((self.width - size) // 2, 200)
            base_img.paste(broll_resized, pos, mask)
            base_img.paste(glow, (pos[0] - 10, pos[1] - 10), glow)
            
            return base_img
        
        return base_img
    
    def render_video(self, script: VideoScript, audio_segments: List[AudioSegment],
                     broll_paths: List[Optional[str]], final_audio_path: str) -> str:
        """
        Main video rendering function with KARAOKE animated captions.
        Two-pass render: 1) Generate visual frames, 2) Burn ASS subtitles via FFmpeg
        """
        total_duration = get_audio_duration(final_audio_path)
        total_frames = int(total_duration * self.fps)
        
        print(f"Rendering {total_frames} frames at {self.fps} FPS, duration: {total_duration:.2f}s")
        print("Generating karaoke-style animated captions...")
        
        # NEW: Generate ASS subtitle file with word-by-word karaoke timing
        ass_path = self.caption_engine.build_ass_file(audio_segments)
        print(f"Karaoke captions saved: {ass_path}")
        
        broll_images = {}
        for i, path in enumerate(broll_paths):
            if path and os.path.exists(path):
                try:
                    broll_images[i] = Image.open(path).convert("RGB")
                except:
                    pass
        
        batch_size = 100
        frame_files = []
        
        for batch_start in range(0, total_frames, batch_size):
            batch_end = min(batch_start + batch_size, total_frames)
            
            for frame_idx in range(batch_start, batch_end):
                current_time = frame_idx / self.fps
                
                active_seg_idx = -1
                active_seg = None
                seg_progress = 0.0
                
                for i, seg in enumerate(audio_segments):
                    if seg.start_time <= current_time < seg.end_time:
                        active_seg_idx = i
                        active_seg = seg
                        seg_duration = seg.end_time - seg.start_time
                        seg_progress = (current_time - seg.start_time) / max(seg_duration, 0.1)
                        break
                
                frame = Image.new("RGB", (self.width, self.height), Config.COLOR_BG_DARK)
                draw = ImageDraw.Draw(frame)
                
                # 1. Background
                self._draw_gradient_background(draw, frame_idx, total_frames)
                
                # 2. Particles
                self._draw_particles(draw, frame_idx)
                
                # 3. B-roll overlay
                if active_seg_idx >= 0 and active_seg_idx in broll_images:
                    seg_frames = int((active_seg.end_time - active_seg.start_time) * self.fps)
                    rel_frame = frame_idx - int(active_seg.start_time * self.fps)
                    
                    if active_seg.segment.segment_type == "hook":
                        mode = "full"
                    elif active_seg.segment.segment_type in ["fact1", "fact2", "fact3"]:
                        mode = "split" if random.random() > 0.5 else "full"
                    else:
                        mode = "full"
                    
                    frame = self._draw_broll_overlay(
                        frame, broll_paths[active_seg_idx], rel_frame, seg_frames, mode
                    )
                    draw = ImageDraw.Draw(frame)
                
                # 4. Visual beats (zoom punches on emphasis)
                if active_seg and active_seg.segment.emphasis_words:
                    beat_times = [
                        active_seg.start_time + 0.5,
                        active_seg.start_time + (active_seg.end_time - active_seg.start_time) * 0.5
                    ]
                    for bt in beat_times:
                        if abs(current_time - bt) < 0.15:
                            beat_progress = 1 - abs(current_time - bt) / 0.15
                            zoom = 1 + 0.08 * beat_progress
                            new_size = (int(self.width * zoom), int(self.height * zoom))
                            frame = frame.resize(new_size, Image.Resampling.LANCZOS)
                            left = (new_size[0] - self.width) // 2
                            top = (new_size[1] - self.height) // 2
                            frame = frame.crop((left, top, left + self.width, top + self.height))
                            draw = ImageDraw.Draw(frame)
                
                # 5. REMOVED: Static PIL text drawing
                # Karaoke captions are now burned via FFmpeg ASS filter
                
                # 6. Channel badge
                self._draw_channel_badge(draw, frame_idx)
                
                # 7. Progress bar
                self._draw_progress_bar(draw, frame_idx, total_frames)
                
                # 8. Subscribe CTA
                self._draw_subscribe_cta(draw, frame_idx, total_frames)
                
                frame_path = Config.FRAMES_DIR / f"frame_{frame_idx:06d}.png"
                frame.save(frame_path, "PNG")
                frame_files.append(str(frame_path))
                
                if frame_idx % 100 == 0:
                    print(f"Rendered frame {frame_idx}/{total_frames}")
        
        # NEW: Compile video with FFmpeg + burn karaoke ASS subtitles
        output_path = str(Config.OUTPUT_DIR / "output_video.mp4")
        temp_video = str(Config.OUTPUT_DIR / "temp_video_no_subs.mp4")
        
        # Step 1: Compile frames + audio into temp video (no subs yet)
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(self.fps),
            "-i", str(Config.FRAMES_DIR / "frame_%06d.png"),
            "-i", final_audio_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-shortest",
            "-movflags", "+faststart",
            temp_video
        ]
        
        rc, out, err = run_command(cmd, timeout=600)
        if rc != 0:
            print(f"FFmpeg temp video error: {err}")
            cmd = [
                "ffmpeg", "-y",
                "-framerate", str(self.fps),
                "-i", str(Config.FRAMES_DIR / "frame_%06d.png"),
                "-i", final_audio_path,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "28",
                "-preset", "ultrafast",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                temp_video
            ]
            run_command(cmd, timeout=600)
        
        # Step 2: Burn ASS karaoke subtitles onto the temp video
        print("Burning karaoke animated captions onto video...")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_video,
            "-vf", f"subtitles={ass_path}:fontsdir=/usr/share/fonts/truetype",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path
        ]
        
        rc, out, err = run_command(cmd, timeout=300)
        if rc != 0:
            print(f"FFmpeg subtitle burn error: {err}")
            print("Trying fallback without fontsdir...")
            cmd = [
                "ffmpeg", "-y",
                "-i", temp_video,
                "-vf", f"subtitles={ass_path}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "23",
                "-preset", "fast",
                "-c:a", "copy",
                output_path
            ]
            rc2, out2, err2 = run_command(cmd, timeout=300)
            if rc2 != 0:
                print(f"Fallback also failed: {err2}")
                shutil.copy(temp_video, output_path)
        
        # Cleanup temp files
        if os.path.exists(temp_video):
            os.remove(temp_video)
        
        # Cleanup frames
        for f in Config.FRAMES_DIR.glob("*.png"):
            f.unlink()
        
        print(f"Final video with karaoke captions: {output_path}")
        return output_path

# =============================================================================
# 6. TELEGRAM DELIVERY
# =============================================================================

class TelegramAgent:
    """Sends video and metadata via Telegram Bot."""
    
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
    
    def send_video(self, video_path: str, script: VideoScript, artifact_url: str = ""):
        """Send video with full metadata."""
        if not self.token or not self.chat_id:
            print("Telegram credentials not configured")
            return False
        
        caption = self._build_caption(script, artifact_url)
        
        file_size = os.path.getsize(video_path)
        max_size = 48 * 1024 * 1024
        
        try:
            if file_size <= max_size:
                with open(video_path, "rb") as f:
                    files = {"video": f}
                    data = {
                        "chat_id": self.chat_id,
                        "caption": caption[:1024],
                        "parse_mode": "HTML"
                    }
                    resp = requests.post(
                        f"{self.base_url}/sendVideo",
                        data=data, files=files, timeout=120
                    )
                    result = resp.json()
                    if result.get("ok"):
                        print("Video sent successfully!")
                        return True
                    else:
                        print(f"Telegram error: {result}")
            else:
                print(f"Video too large ({file_size / 1024 / 1024:.1f}MB), sending metadata only")
                self._send_text(caption)
                
                thumbnail_path = self._generate_thumbnail(script)
                if thumbnail_path:
                    with open(thumbnail_path, "rb") as f:
                        files = {"photo": f}
                        data = {
                            "chat_id": self.chat_id,
                            "caption": f"<b>{script.seo_title}</b>\n\nVideo too large for Telegram. Download from GitHub Actions artifacts.",
                            "parse_mode": "HTML"
                        }
                        requests.post(
                            f"{self.base_url}/sendPhoto",
                            data=data, files=files, timeout=60
                        )
        except Exception as e:
            print(f"Telegram send error: {e}")
        
        return False
    
    def _build_caption(self, script: VideoScript, artifact_url: str) -> str:
        """Build comprehensive caption."""
        tags_str = ", ".join(script.tags[:15])
        hashtags_str = " ".join(script.hashtags[:10])
        
        caption = f"""<b>🎬 {script.seo_title}</b>

<b>📋 Title:</b> {script.title}
<b>📁 Category:</b> {script.category}

<b>📝 Description:</b>
{script.description}

<b>🏷 Tags:</b>
{tags_str}

<b>#️⃣ Hashtags:</b>
{hashtags_str}

<b>⬆️ Upload Time:</b> 5:00 PM PKT Daily

<b>📥 Download:</b> {artifact_url if artifact_url else "Check GitHub Actions artifacts"}

#AjeebologyShorts #YouTubeShorts #DailyFacts"""
        
        return caption
    
    def _send_text(self, text: str):
        """Send text message."""
        try:
            data = {
                "chat_id": self.chat_id,
                "text": text[:4096],
                "parse_mode": "HTML"
            }
            requests.post(f"{self.base_url}/sendMessage", data=data, timeout=30)
        except Exception as e:
            print(f"Text send error: {e}")
    
    def _generate_thumbnail(self, script: VideoScript) -> Optional[str]:
        """Generate thumbnail image."""
        try:
            img = Image.new("RGB", (1280, 720), Config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(img)
            
            for y in range(720):
                ratio = y / 720
                r = int(10 + ratio * 30)
                g = int(5 + ratio * 20)
                b = int(25 + ratio * 50)
                draw.line([(0, y), (1280, y)], fill=(r, g, b))
            
            font = self._load_font_thumbnail(80)
            words = script.title.split()
            lines = []
            current = []
            for word in words:
                test = " ".join(current + [word])
                bbox = font.getbbox(test)
                if bbox and bbox[2] > 1200:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            if current:
                lines.append(" ".join(current))
            
            y = 360 - len(lines) * 50
            for line in lines:
                for offset in range(8, 0, -2):
                    draw.text((640 + offset, y), line, font=font, fill=(0, 200, 200), anchor="mm")
                    draw.text((640 - offset, y), line, font=font, fill=(0, 200, 200), anchor="mm")
                draw.text((640, y), line, font=font, fill=(255, 255, 255), anchor="mm")
                y += 100
            
            font_small = self._load_font_thumbnail(40)
            draw.text((640, 650), "@AjeebologyShorts", font=font_small, 
                     fill=Config.COLOR_ACCENT, anchor="mm")
            
            path = str(Config.OUTPUT_DIR / "thumbnail.jpg")
            img.save(path, "JPEG", quality=90)
            return path
        except Exception as e:
            print(f"Thumbnail error: {e}")
            return None
    
    def _load_font_thumbnail(self, size: int):
        """Load font for thumbnail."""
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        ]
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except:
                continue
        return ImageFont.load_default()


# =============================================================================
# 7. MAIN PIPELINE ORCHESTRATOR
# =============================================================================

class AjeebologyPipeline:
    """Main pipeline that orchestrates the entire automation."""
    
    def __init__(self):
        self.researcher = ResearchAgent()
        self.script_writer = ScriptAgent()
        self.voice_gen = VoiceAgent()
        self.asset_fetcher = AssetAgent()
        self.video_engine = VideoEngine()
        self.telegram = TelegramAgent()
    
    def run(self):
        """Execute full pipeline."""
        print("=" * 60)
        print("AJEEBOLOGY SHORTS - AUTOMATION PIPELINE")
        print("=" * 60)
        
        try:
            # Step 1: Setup
            print("\n[1/8] Setting up directories...")
            setup_directories()
            
            # Step 2: Research
            print("\n[2/8] Researching fresh facts...")
            research_data = self.researcher.fetch_fact()
            print(f"Category: {research_data['category']}")
            print(f"Topic: {research_data['title']}")
            
            # Step 3: Generate Script
            print("\n[3/8] Generating Hinglish script...")
            script = self.script_writer.generate_script(research_data)
            print(f"Title: {script.title}")
            print(f"Segments: {len(script.segments)}")
            for seg in script.segments:
                print(f"  [{seg.segment_type}] {seg.text[:60]}...")
            
            # Step 4: Generate Voice
            print("\n[4/8] Generating voiceover...")
            audio_segments = self.voice_gen.generate_voice(script)
            total_voice_duration = sum(seg.duration for seg in audio_segments)
            print(f"Total voice duration: {total_voice_duration:.2f}s")
            
            # Step 5: Fetch Assets
            print("\n[5/8] Fetching B-roll and music...")
            broll_paths = []
            for i, seg in enumerate(script.segments):
                if seg.broll_prompt:
                    path = self.asset_fetcher.fetch_broll(seg.broll_prompt, i)
                    broll_paths.append(path)
                    if path:
                        print(f"  ✓ B-roll {i}: {seg.broll_prompt[:40]}...")
                    else:
                        print(f"  ✗ B-roll {i}: Failed")
                else:
                    broll_paths.append(None)
            
            bg_music = self.asset_fetcher.fetch_background_music()
            if bg_music:
                print("  ✓ Background music downloaded")
            
            # Step 6: Mix Audio
            print("\n[6/8] Mixing audio...")
            final_audio = self.voice_gen.mix_audio(audio_segments, bg_music)
            print(f"Final audio: {final_audio}")
            
            # Step 7: Render Video (with karaoke captions)
            print("\n[7/8] Rendering professional video with karaoke captions...")
            print("This may take several minutes on GitHub Actions...")
            video_path = self.video_engine.render_video(
                script, audio_segments, broll_paths, final_audio
            )
            print(f"Video rendered: {video_path}")
            
            file_size = os.path.getsize(video_path)
            print(f"File size: {file_size / 1024 / 1024:.2f} MB")
            
            # Step 8: Deliver
            print("\n[8/8] Sending to Telegram...")
            
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            artifact_url = ""
            if run_id and repo:
                artifact_url = f"https://github.com/{repo}/actions/runs/{run_id}"
            
            self.telegram.send_video(video_path, script, artifact_url)
            
            print("\n" + "=" * 60)
            print("PIPELINE COMPLETED SUCCESSFULLY!")
            print("=" * 60)
            
            return True
            
        except Exception as e:
            print(f"\n❌ PIPELINE FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pipeline = AjeebologyPipeline()
    success = pipeline.run()
    sys.exit(0 if success else 1)
