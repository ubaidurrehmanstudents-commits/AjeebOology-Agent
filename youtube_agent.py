#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional YouTube Shorts Automation Agent
Fully automated pipeline: Research -> Script -> Voice -> Video -> Upload
Language: Hinglish (Roman Hindi + English), Male voice
Output: Vertical 1080x1920, ~55-65 seconds, 24 FPS
Features: Karaoke ASS captions, Pexels video b-roll, audio ducking, YouTube upload
"""

import os
import sys
import json
import re
import math
import random
import tempfile
import subprocess
import shutil
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from urllib.parse import quote_plus, urlparse
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
    YOUTUBE_CLIENT_SECRETS = os.environ.get("YOUTUBE_CLIENT_SECRETS", "")
    PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
    UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
    CATEGORY_OVERRIDE = os.environ.get("CATEGORY_OVERRIDE", "")
    
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24
    TARGET_DURATION = 58
    MAX_DURATION = 64
    
    VOICE_MODEL = "hi-IN-MadhurNeural"
    AUDIO_SAMPLE_RATE = 44100
    
    FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"
    FONT_PATH_FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    FONT_SIZE_TITLE = 72
    FONT_SIZE_BODY = 56
    FONT_SIZE_CAPTION = 58
    
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
    POLLINATIONS_ENABLED = True

# Seed random for deterministic builds
random.seed(Config.GITHUB_RUN_ID)

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
# UTILITIES
# =============================================================================

def run_command(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """Run shell command with timeout."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
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
    rc, out, _ = run_command(cmd, timeout=30)
    if rc == 0 and out.strip():
        return float(out.strip())
    return 0.0

def ensure_dirs():
    """Create all necessary directories."""
    for d in [Config.FRAMES_DIR, Config.AUDIO_DIR, Config.ASSETS_DIR, Config.OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load font with fallback."""
    for path in [Config.FONT_PATH, Config.FONT_PATH_FALLBACK]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

# =============================================================================
# 1. SCRIPT GENERATION (Groq/LLaMA)
# =============================================================================

class ScriptAgent:
    SYSTEM_PROMPT = """You are a professional YouTube Shorts scriptwriter for the channel 'AjeebOology'.
Create engaging, fact-packed scripts in Hinglish (Roman Hindi + English mix).
Target audience: Indian youth aged 18-34.
Tone: Curious, energetic, slightly dramatic, educational but entertaining.

Rules:
- Hook must be under 4 seconds, create a "pattern interrupt"
- Each script has: hook, fact1, fact2, fact3, conclusion
- Total spoken words: 140-170 (roughly 55-62 seconds)
- Emphasis words: 2-3 per segment (for visual punch)
- B-roll prompts: vivid, specific image/video search terms
- Output valid JSON only

JSON Format:
{
  "title": "Short catchy title",
  "category": "psychology|space|weird_facts",
  "seo_title": "SEO optimized title under 100 chars",
  "description": "2-3 lines with keywords",
  "tags": ["tag1", "tag2", ...],
  "hashtags": ["#Shorts", "#AjeebOology", ...],
  "segments": [
    {
      "text": "Spoken text here",
      "segment_type": "hook|fact1|fact2|fact3|conclusion",
      "emphasis_words": ["word1", "word2"],
      "broll_prompt": "search keywords for visuals"
    }
  ]
}"""

    def __init__(self):
        self.api_key = Config.GROQ_API_KEY
        self.url = "https://api.groq.com/openai/v1/chat/completions"
    
    def generate_script(self, research_data: Dict) -> VideoScript:
        """Generate script via Groq API."""
        category = Config.CATEGORY_OVERRIDE or random.choice(["psychology", "space", "weird_facts"])
        prompt = f"""Create a YouTube Shorts script about: {research_data.get('topic', category)}.
Category: {category}
Make it mind-blowing, use Hinglish. Include 2-3 emphasis words per segment.
Return ONLY valid JSON."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.85,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"}
        }
        try:
            resp = requests.post(self.url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()["choices"][0]["message"]["content"]
            if isinstance(data, str):
                data = json.loads(data)
            return self._parse_script(data, category)
        except Exception as e:
            print(f"Script generation error: {e}")
            return self._fallback_script(category)
    
    def _parse_script(self, data: Dict, category: str) -> VideoScript:
        segments = []
        for seg in data.get("segments", []):
            segments.append(ScriptSegment(
                text=seg.get("text", ""),
                segment_type=seg.get("segment_type", "fact"),
                emphasis_words=seg.get("emphasis_words", []),
                broll_prompt=seg.get("broll_prompt", "")
            ))
        return VideoScript(
            title=data.get("title", "Ajeebology Short"),
            category=category,
            seo_title=data.get("seo_title", "Ajeebology Short"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            hashtags=data.get("hashtags", ["#Shorts", "#AjeebOology"]),
            segments=segments
        )


    def _fallback_script(self, category: str) -> VideoScript:
        texts = {
            "psychology": [
                "Kya aap jante hain ki aapka brain 70 percent waqt auto-pilot par rehta hai?",
                "Jab aap drive kar rahe hote hain, tab aapka subconscious mind control mein hota hai.",
                "Aur jab aap sochte hain ki aap conscious hain, woh bhi ek illusion hai!",
                "Scientists ne prove kiya hai ki decisions 7 seconds pehle brain mein ban chuke hote hain.",
                "Toh agli baar jab koi decision lo, yaad rakhna - aapka brain pehle se hi decide kar chuka tha!"
            ],
            "space": [
                "Space mein aawaz kyun nahi jaati? Reason sunke shock ho jaaoge!",
                "Aawaz travel karne ke liye medium chahiye, aur space mein vacuum hai.",
                "Lekin suno, agar aap Mars pe khade hokar chillao, toh wahan ke atmosphere mein aawaz jayegi!",
                "Aur NASA ke microphones ne actually Mars ki aawazein record ki hain!",
                "Toh space silent nahi hai, bas uska silence alag tarah ka hai!"
            ],
            "weird_facts": [
                "Yeh fact sunke aapka dimaag ghoom jayega!",
                "Honey kabhi spoil nahi hota. Archaeologists ne 3000 saal purana honey khaya aur woh theek tha!",
                "Aur octopus ke paas 3 dil hote hain, aur woh blue blood rakhte hain!",
                "Banana technically ek berry hai, aur strawberry technically berry nahi hai!",
                "Duniya itni ajeeb hai ki facts bhi confuse ho jate hain!"
            ]
        }
        segs = []
        types = ["hook", "fact1", "fact2", "fact3", "conclusion"]
        for i, t in enumerate(texts.get(category, texts["weird_facts"])):
            segs.append(ScriptSegment(
                text=t, segment_type=types[i],
                emphasis_words=["shock", "amazing"] if i == 0 else ["fact", "wow"]
            ))
        return VideoScript(
            title="Ajeebology Fact", category=category, seo_title="Amazing Fact | AjeebOology",
            description="Incredible facts in Hinglish", tags=[category, "facts", "shorts"],
            hashtags=["#Shorts", "#AjeebOology", "#Facts"], segments=segs
        )

# =============================================================================
# 2. RESEARCH AGENT (Tavily)
# =============================================================================

class ResearchAgent:
    def __init__(self):
        self.api_key = Config.TAVILY_API_KEY
        self.url = "https://api.tavily.com/search"
    
    def research(self, category: str) -> Dict:
        """Fetch trending topics and facts."""
        queries = {
            "psychology": "mind-blowing psychology facts 2026 trending",
            "space": "latest space discoveries 2026 NASA trending",
            "weird_facts": "incredible weird facts 2026 viral"
        }
        query = queries.get(category, queries["weird_facts"])
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 5
        }
        try:
            resp = requests.post(self.url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                return {"topic": results[0].get("title", category), "results": results}
        except Exception as e:
            print(f"Research error: {e}")
        return {"topic": category, "results": []}

# =============================================================================
# 3. VOICE GENERATION (Edge-TTS)
# =============================================================================

class VoiceAgent:
    def __init__(self):
        self.model = Config.VOICE_MODEL
    
    def generate_voice(self, script: VideoScript) -> List[AudioSegment]:
        """Generate TTS for each segment and build timeline."""
        audio_segments = []
        current_time = 0.0
        
        for i, seg in enumerate(script.segments):
            clean_text = self._clean_for_tts(seg.text)
            output_path = str(Config.AUDIO_DIR / f"seg_{i:02d}.mp3")
            
            if self._generate_with_edge_tts(clean_text, output_path):
                duration = get_audio_duration(output_path)
                if duration < 0.5:
                    duration = self._estimate_duration(clean_text)
            else:
                duration = self._estimate_duration(clean_text)
                self._create_silent_audio(output_path, duration)
            
            audio_segments.append(AudioSegment(
                segment=seg, audio_path=output_path,
                duration=duration, start_time=current_time,
                end_time=current_time + duration
            ))
            current_time += duration
        
        script.total_duration_estimate = current_time
        return audio_segments
    
    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS."""
        text = re.sub(r"[#@]\w+", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[\*\_\~\`]", "", text)
        return text.strip()
    
    def _generate_with_edge_tts(self, text: str, output_path: str) -> bool:
        """Generate voice using edge-tts."""
        try:
            import edge_tts
            import asyncio
            async def _gen():
                communicate = edge_tts.Communicate(text, self.model)
                await communicate.save(output_path)
            asyncio.run(_gen())
            return os.path.exists(output_path) and os.path.getsize(output_path) > 1024
        except Exception as e:
            print(f"Edge-TTS error: {e}")
            return False
    
    def _estimate_duration(self, text: str) -> float:
        """Estimate duration based on word count."""
        words = len(text.split())
        return max(1.5, words * 0.35)
    
    def _create_silent_audio(self, path: str, duration: float):
        """Create silent audio fallback."""
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration), "-acodec", "libmp3lame", "-q:a", "4", path
        ]
        run_command(cmd, timeout=30)
    
    def mix_audio(self, audio_segments: List[AudioSegment],
                  bg_music_path: Optional[str] = None) -> str:
        """Mix voice with background music using sidechain compression."""
        # Concatenate all voice segments
        concat_list = str(Config.AUDIO_DIR / "concat_list.txt")
        with open(concat_list, "w") as f:
            for seg in audio_segments:
                f.write(f"file '{seg.audio_path}'\n")
        
        voice_concat = str(Config.AUDIO_DIR / "voice_concat.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", voice_concat
        ]
        run_command(cmd, timeout=60)
        
        final_audio = str(Config.AUDIO_DIR / "final_audio.mp3")
        
        if bg_music_path and os.path.exists(bg_music_path):
            filter_complex = (
                "[1:a]asplit=2[sc][mix];"
                "[sc]sidechaincompress=threshold=0.05:ratio=5:attack=50:release=200[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:weights=1 0.25[Mixed];"
                "[Mixed]loudnorm=I=-14:TP=-1.5:LRA=11[out]"
            )
            cmd = [
                "ffmpeg", "-y", "-i", voice_concat, "-i", bg_music_path,
                "-filter_complex", filter_complex,
                "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "2",
                "-ar", str(Config.AUDIO_SAMPLE_RATE), final_audio
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", voice_concat,
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame", "-q:a", "2",
                "-ar", str(Config.AUDIO_SAMPLE_RATE), final_audio
            ]
        
        rc, _, err = run_command(cmd, timeout=120)
        if rc != 0 or not os.path.exists(final_audio):
            print(f"Audio mix error: {err}")
            shutil.copy(voice_concat, final_audio)
        
        return final_audio

# =============================================================================
# 4. ASSET AGENT (B-Roll + Background Music + SFX)
# =============================================================================

class AssetAgent:
    def __init__(self):
        self.unsplash_key = Config.UNSPLASH_ACCESS_KEY
        self.pexels_key = Config.PEXELS_API_KEY
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_broll(self, prompt: str, index: int) -> Optional[str]:
        """Fetch b-roll asset. Try Pexels video first, then images."""
        dest = str(Config.ASSETS_DIR / f"broll_{index:02d}.mp4")
        img_dest = str(Config.ASSETS_DIR / f"broll_{index:02d}.jpg")
        
        if self.pexels_key and self._try_pexels_video(prompt, dest):
            return dest
        if self._try_unsplash(prompt, img_dest):
            return img_dest
        if Config.POLLINATIONS_ENABLED and self._try_pollinations(prompt, img_dest):
            return img_dest
        if self._try_pexels_image(prompt, img_dest):
            return img_dest
        return None
    
    def _try_pexels_video(self, prompt: str, dest: str) -> bool:
        """Fetch vertical video from Pexels."""
        try:
            url = f"https://api.pexels.com/videos/search?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": self.pexels_key}
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            for vid in videos:
                files = vid.get("video_files", [])
                for vf in files:
                    if vf.get("quality") in ["sd", "hd"]:
                        vurl = vf.get("link", "")
                        if vurl:
                            r = requests.get(vurl, timeout=30)
                            if r.status_code == 200:
                                with open(dest, "wb") as f:
                                    f.write(r.content)
                                return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Pexels video error: {e}")
            return False
    
    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        """Fetch image from Unsplash."""
        try:
            url = f"https://api.unsplash.com/photos/random?query={quote_plus(prompt)}&orientation=portrait"
            headers = {"Authorization": f"Client-ID {self.unsplash_key}"}
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            img_url = resp.json()["urls"]["regular"]
            r = requests.get(img_url, timeout=30)
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Unsplash error: {e}")
            return False
    
    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        """Fetch AI image from Pollinations."""
        try:
            url = f"https://image.pollinations.ai/prompt/{quote_plus(prompt)}?width=1080&height=1920&nologo=true&seed={random.randint(1,9999)}"
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Pollinations error: {e}")
            return False
    
    def _try_pexels_image(self, prompt: str, dest: str) -> bool:
        """Fetch image from Pexels."""
        try:
            url = f"https://api.pexels.com/v1/search?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": self.pexels_key}
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
            if photos:
                img_url = photos[0]["src"]["large"]
                r = requests.get(img_url, timeout=30)
                if r.status_code == 200:
                    with open(dest, "wb") as f:
                        f.write(r.content)
                    return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Pexels image error: {e}")
            return False
    
    def fetch_background_music(self) -> Optional[str]:
        """Fetch royalty-free background music."""
        dest = str(Config.ASSETS_DIR / "bg_music.mp3")
        if os.path.exists(dest):
            return dest
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anoisesrc=a=0.02:c=pink:duration=65",
            "-af", "lowpass=f=800, volume=0.3",
            "-c:a", "libmp3lame", "-q:a", "4", dest
        ]
        rc, _, _ = run_command(cmd, timeout=30)
        if rc == 0 and os.path.exists(dest):
            return dest
        return None
    
    def fetch_sfx(self, sfx_type: str, output_path: str) -> bool:
        """Generate simple SFX using ffmpeg."""
        generators = {
            "pop": "sine=frequency=1000:duration=0.15",
            "whoosh": "sine=frequency=200:duration=0.3",
            "ding": "sine=frequency=800:duration=0.2"
        }
        gen = generators.get(sfx_type, generators["pop"])
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", gen,
            "-af", "volume=0.4", "-c:a", "libmp3lame", "-q:a", "4", output_path
        ]
        rc, _, _ = run_command(cmd, timeout=15)
        return rc == 0 and os.path.exists(output_path)



# =============================================================================
# 5. KARAOKE CAPTION ENGINE (ASS Subtitles)
# =============================================================================

class CaptionEngine:
    """
    Generates professional karaoke captions using ASS subtitle format.
    Word-by-word highlighting with smooth color transitions.
    """
    
    def __init__(self):
        self.ass_header = self._build_ass_header()
    
    def _build_ass_header(self) -> str:
        """Build ASS file header with styles."""
        white = "&H00FFFFFF"
        cyan = "&H00FFFF00"      # BGR cyan
        yellow = "&H0000FFFF"    # BGR yellow
        black = "&H00000000"
        
        return f"""[Script Info]
Title: AjeebOology Karaoke
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans Devanagari Bold,58,{white},{cyan},{black},{black},-1,0,0,0,100,100,0,0,1,3,0,2,40,40,140,1
Style: Emphasis,Noto Sans Devanagari Bold,64,{yellow},{cyan},{black},{black},-1,0,0,0,110,110,0,0,1,4,0,2,40,40,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    def build_ass_file(self, audio_segments: List[AudioSegment]) -> str:
        """Generate complete ASS file with word-by-word karaoke."""
        ass_path = str(Config.OUTPUT_DIR / "karaoke.ass")
        lines = [self.ass_header]
        
        for seg in audio_segments:
            words = seg.segment.text.split()
            if not words:
                continue
            
            seg_duration = seg.end_time - seg.start_time
            word_duration = seg_duration / max(len(words), 1)
            
            # Build karaoke line with \k tags (centiseconds)
            karaoke_text = ""
            for word in words:
                k_duration = int(word_duration * 100)
                karaoke_text += f"{{\\k{k_duration}}}{word} "
            
            style = "Emphasis" if seg.segment.segment_type == "hook" else "Default"
            start = self._format_time(seg.start_time)
            end = self._format_time(seg.end_time)
            
            lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{karaoke_text.strip()}")
        
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return ass_path
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds to ASS time (H:MM:SS.cc)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"

# =============================================================================
# 6. VIDEO RENDERING ENGINE
# =============================================================================

class VideoEngine:
    """
    Professional video renderer with animated backgrounds, b-roll overlays,
    and karaoke captions burned via FFmpeg ASS filter (single-pass).
    """
    
    def __init__(self):
        self.width = Config.WIDTH
        self.height = Config.HEIGHT
        self.fps = Config.FPS
        self.font_title = load_font(Config.FONT_SIZE_TITLE)
        self.font_body = load_font(Config.FONT_SIZE_BODY)
        self.font_caption = load_font(Config.FONT_SIZE_CAPTION)
        self.particles = self._init_particles(80)
        self.caption_engine = CaptionEngine()
    
    def _init_particles(self, count: int) -> List[Dict]:
        """Initialize floating particles."""
        particles = []
        for _ in range(count):
            particles.append({
                "x": random.randint(0, self.width),
                "y": random.randint(0, self.height),
                "size": random.randint(2, 6),
                "speed_x": random.uniform(-0.8, 0.8),
                "speed_y": random.uniform(-0.5, -2.0),
                "opacity": random.randint(80, 200),
                "phase": random.uniform(0, math.pi * 2)
            })
        return particles
    
    def _draw_gradient_background(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        """Draw animated gradient background."""
        progress = frame_idx / max(total_frames, 1)
        for y in range(0, self.height, 4):
            ratio = y / self.height
            drift = math.sin(progress * math.pi * 2 + ratio * 3) * 0.15
            
            r = int(Config.COLOR_BG_DARK[0] + (Config.COLOR_BG_MID[0] - Config.COLOR_BG_DARK[0]) * ratio + drift * 40)
            g = int(Config.COLOR_BG_DARK[1] + (Config.COLOR_BG_MID[1] - Config.COLOR_BG_DARK[1]) * ratio + drift * 20)
            b = int(Config.COLOR_BG_DARK[2] + (Config.COLOR_BG_MID[2] - Config.COLOR_BG_DARK[2]) * ratio + drift * 60)
            
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            draw.line([(0, y), (self.width, y)], fill=(r, g, b), width=4)
    
    def _draw_particles(self, draw: ImageDraw, frame_idx: int):
        """Draw animated particles."""
        for p in self.particles:
            px = (p["x"] + p["speed_x"] * frame_idx) % self.width
            py = (p["y"] + p["speed_y"] * frame_idx) % self.height
            pulse = 0.5 + 0.5 * math.sin(frame_idx * 0.05 + p["phase"])
            alpha = int(p["opacity"] * pulse)
            size = int(p["size"] * (0.8 + 0.4 * pulse))
            color = (Config.COLOR_ACCENT[0], Config.COLOR_ACCENT[1], Config.COLOR_ACCENT[2])
            draw.ellipse([px - size, py - size, px + size, py + size], fill=color)
    
    def _draw_text_with_glow(self, draw: ImageDraw, text: str, font, x: int, y: int,
                              color: Tuple[int, int, int], glow_radius: int = 3):
        """Draw text with subtle glow outline."""
        for r in range(glow_radius, 0, -1):
            alpha = int(40 + (glow_radius - r) * 30)
            glow_color = (color[0], color[1], color[2])
            draw.text((x, y), text, font=font, fill=glow_color)
        draw.text((x, y), text, font=font, fill=color)
    
    def _wrap_text(self, text: str, font, max_width: int) -> List[str]:
        """Wrap text to fit max width."""
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            test = " ".join(current_line + [word])
            bbox = font.getbbox(test)
            if bbox and (bbox[2] - bbox[0]) > max_width and current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                current_line.append(word)
        if current_line:
            lines.append(" ".join(current_line))
        return lines if lines else [text]
    
    def _draw_rounded_card(self, draw: ImageDraw, bbox: List[int], radius: int,
                            fill: Tuple[int, int, int], outline: Optional[Tuple[int, int, int]] = None):
        """Draw rounded rectangle card."""
        draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=2)
    
    def _apply_ken_burns(self, img: Image.Image, frame_idx: int, segment_frames: int,
                          mode: str = "full") -> Image.Image:
        """Apply Ken Burns effect to b-roll."""
        if segment_frames < 2:
            return img
        progress = frame_idx / segment_frames
        
        if mode == "zoom_in":
            scale = 1.0 + 0.15 * progress
        elif mode == "zoom_out":
            scale = 1.15 - 0.15 * progress
        else:
            scale = 1.0 + 0.08 * math.sin(progress * math.pi)
        
        new_w = int(img.width * scale)
        new_h = int(img.height * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        pan_x = int((new_w - self.width) * 0.5 * (1 + 0.3 * math.sin(progress * math.pi * 2)))
        pan_y = int((new_h - self.height) * 0.5 * (1 + 0.2 * math.cos(progress * math.pi * 2)))
        
        left = max(0, min(pan_x, new_w - self.width))
        top = max(0, min(pan_y, new_h - self.height))
        return img.crop((left, top, left + self.width, top + self.height))
    
    def _draw_progress_bar(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        """Draw sleek progress bar at bottom."""
        bar_y = self.height - 20
        bar_height = 8
        progress = frame_idx / max(total_frames, 1)
        
        draw.rounded_rectangle(
            [40, bar_y, self.width - 40, bar_y + bar_height],
            radius=4, fill=(40, 30, 60)
        )
        progress_width = int((self.width - 80) * progress)
        if progress_width > 0:
            draw.rounded_rectangle(
                [40, bar_y, 40 + progress_width, bar_y + bar_height],
                radius=4, fill=Config.COLOR_ACCENT
            )
    
    def _draw_channel_badge(self, draw: ImageDraw, frame_idx: int):
        """Draw channel badge in top corner."""
        badge_text = "AjeebOology"
        font = load_font(32)
        bbox = font.getbbox(badge_text)
        if not bbox:
            return
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        x = self.width - text_w - 30
        y = 30
        
        padding = 12
        self._draw_rounded_card(
            draw,
            [x - padding, y - padding, x + text_w + padding, y + text_h + padding],
            radius=20, fill=(20, 10, 40), outline=Config.COLOR_ACCENT
        )
        draw.text((x, y), badge_text, font=font, fill=Config.COLOR_TEXT)
    
    def _draw_subscribe_cta(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        """Draw subscribe CTA in last 8 seconds."""
        current_time = frame_idx / self.fps
        total_time = total_frames / self.fps
        if current_time < total_time - 8:
            return
        
        cta_text = "Subscribe for Daily Facts!"
        font = load_font(44)
        bbox = font.getbbox(cta_text)
        if not bbox:
            return
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        x = (self.width - text_w) // 2
        y = self.height - 180
        
        bounce = abs(math.sin((current_time - (total_time - 8)) * 4)) * 10
        y -= int(bounce)
        
        self._draw_rounded_card(
            draw,
            [x - 20, y - 10, x + text_w + 20, y + text_h + 10],
            radius=25, fill=Config.COLOR_ACCENT_2, outline=Config.COLOR_TEXT
        )
        draw.text((x, y), cta_text, font=font, fill=Config.COLOR_TEXT)
    
    def _draw_broll_overlay(self, base_img: Image.Image, broll_path: str,
                             frame_idx: int, segment_frames: int, mode: str) -> Image.Image:
        """Overlay b-roll with Ken Burns and darkening."""
        if not broll_path or not os.path.exists(broll_path):
            return base_img
        
        try:
            ext = os.path.splitext(broll_path)[1].lower()
            if ext in [".mp4", ".mov", ".avi"]:
                seg_time = frame_idx / self.fps
                cmd = [
                    "ffmpeg", "-y", "-ss", str(seg_time), "-i", broll_path,
                    "-vframes", "1", "-f", "image2", "-vcodec", "png", "-"
                ]
                rc, out, _ = run_command(cmd, timeout=15)
                if rc == 0 and out:
                    broll = Image.open(BytesIO(out)).convert("RGB")
                else:
                    return base_img
            else:
                broll = Image.open(broll_path).convert("RGB")
            
            broll = self._resize_to_cover(broll, self.width, self.height)
            broll = self._apply_ken_burns(broll, frame_idx, segment_frames)
            
            enhancer = ImageEnhance.Brightness(broll)
            broll = enhancer.enhance(0.45)
            broll = self._apply_vignette(broll)
            
            if mode == "split":
                mask = Image.new("L", (self.width, self.height), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rectangle([0, 0, self.width, self.height // 2], fill=255)
                mask_blur = mask.filter(ImageFilter.GaussianBlur(30))
                base_img = Image.composite(broll, base_img, mask_blur)
            else:
                base_img = broll
            
            return base_img
        except Exception as e:
            print(f"B-roll overlay error: {e}")
            return base_img
    
    def _resize_to_cover(self, img: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """Resize image to cover target dimensions."""
        img_ratio = img.width / img.height
        target_ratio = target_w / target_h
        
        if img_ratio > target_ratio:
            new_h = target_h
            new_w = int(new_h * img_ratio)
        else:
            new_w = target_w
            new_h = int(new_w / img_ratio)
        
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        return img.crop((left, top, left + target_w, top + target_h))
    
    def _apply_vignette(self, img: Image.Image) -> Image.Image:
        """Apply subtle vignette effect."""
        w, h = img.size
        x = np.linspace(-1, 1, w)
        y = np.linspace(-1, 1, h)
        X, Y = np.meshgrid(x, y)
        R = np.sqrt(X**2 + Y**2)
        mask = 1 - np.clip(R / 1.4, 0, 1) * 0.4
        mask = (mask * 255).astype(np.uint8)
        mask_img = Image.fromarray(mask, mode="L")
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(50))
        
        img_array = np.array(img)
        mask_array = np.array(mask_img).reshape(h, w, 1) / 255.0
        vignette = (img_array * mask_array).astype(np.uint8)
        return Image.fromarray(vignette)


    def render_video(self, script: VideoScript, audio_segments: List[AudioSegment],
                     broll_paths: List[Optional[str]], final_audio_path: str) -> str:
        """
        Main video rendering with single-pass FFmpeg + ASS karaoke burn.
        """
        total_duration = get_audio_duration(final_audio_path)
        total_frames = int(total_duration * self.fps)
        
        print(f"Rendering {total_frames} frames at {self.fps} FPS, duration: {total_duration:.2f}s")
        
        # Generate ASS karaoke file
        ass_path = self.caption_engine.build_ass_file(audio_segments)
        print(f"Karaoke ASS saved: {ass_path}")
        
        # Pre-load b-roll images
        broll_images = {}
        for i, path in enumerate(broll_paths):
            if path and os.path.exists(path):
                try:
                    if path.lower().endswith((".mp4", ".mov", ".avi")):
                        broll_images[i] = None
                    else:
                        broll_images[i] = Image.open(path).convert("RGB")
                except Exception as e:
                    print(f"Failed to load broll {i}: {e}")
        
        # Render frames in batches
        batch_size = 120
        for batch_start in range(0, total_frames, batch_size):
            batch_end = min(batch_start + batch_size, total_frames)
            
            for frame_idx in range(batch_start, batch_end):
                current_time = frame_idx / self.fps
                
                # Find active segment
                active_seg_idx = -1
                active_seg = None
                seg_progress = 0.0
                for i, seg in enumerate(audio_segments):
                    if seg.start_time <= current_time < seg.end_time:
                        active_seg_idx = i
                        active_seg = seg
                        seg_dur = seg.end_time - seg.start_time
                        seg_progress = (current_time - seg.start_time) / max(seg_dur, 0.1)
                        break
                
                # Create frame
                frame = Image.new("RGB", (self.width, self.height), Config.COLOR_BG_DARK)
                draw = ImageDraw.Draw(frame)
                
                # 1. Animated gradient background
                self._draw_gradient_background(draw, frame_idx, total_frames)
                
                # 2. Floating particles
                self._draw_particles(draw, frame_idx)
                
                # 3. B-roll overlay
                if active_seg_idx >= 0 and active_seg_idx in broll_images:
                    seg_frames = int((active_seg.end_time - active_seg.start_time) * self.fps)
                    rel_frame = frame_idx - int(active_seg.start_time * self.fps)
                    mode = "full" if active_seg.segment.segment_type == "hook" else \
                           ("split" if random.random() > 0.6 else "full")
                    frame = self._draw_broll_overlay(
                        frame, broll_paths[active_seg_idx], rel_frame, seg_frames, mode
                    )
                    draw = ImageDraw.Draw(frame)
                
                # 4. Audio-reactive zoom on emphasis beats
                if active_seg and active_seg.segment.emphasis_words:
                    beat_times = [
                        active_seg.start_time + seg_progress * (active_seg.end_time - active_seg.start_time) * 0.3,
                        active_seg.start_time + seg_progress * (active_seg.end_time - active_seg.start_time) * 0.7
                    ]
                    for bt in beat_times:
                        if abs(current_time - bt) < 0.12:
                            beat_p = 1 - abs(current_time - bt) / 0.12
                            zoom = 1 + 0.06 * beat_p
                            new_sz = (int(self.width * zoom), int(self.height * zoom))
                            frame = frame.resize(new_sz, Image.Resampling.LANCZOS)
                            l = (new_sz[0] - self.width) // 2
                            t = (new_sz[1] - self.height) // 2
                            frame = frame.crop((l, t, l + self.width, t + self.height))
                            draw = ImageDraw.Draw(frame)
                
                # 5. Channel badge
                self._draw_channel_badge(draw, frame_idx)
                
                # 6. Progress bar
                self._draw_progress_bar(draw, frame_idx, total_frames)
                
                # 7. Subscribe CTA
                self._draw_subscribe_cta(draw, frame_idx, total_frames)
                
                # Save frame
                frame_path = Config.FRAMES_DIR / f"frame_{frame_idx:06d}.png"
                frame.save(frame_path, "PNG")
                
                if frame_idx % 150 == 0:
                    print(f"Rendered frame {frame_idx}/{total_frames}")
        
        # SINGLE-PASS FFmpeg: frames + audio + ASS subtitles
        output_path = str(Config.OUTPUT_DIR / "output_video.mp4")
        
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(self.fps),
            "-i", str(Config.FRAMES_DIR / "frame_%06d.png"),
            "-i", final_audio_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-shortest",
            "-movflags", "+faststart",
            output_path
        ]
        
        print("Compiling video with karaoke captions (single-pass)...")
        rc, out, err = run_command(cmd, timeout=600)
        if rc != 0:
            print(f"FFmpeg error: {err}")
            # Fallback: without ASS
            cmd2 = [
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
                "-shortest",
                "-movflags", "+faststart",
                output_path
            ]
            run_command(cmd2, timeout=600)
        
        # Cleanup frames
        for f in Config.FRAMES_DIR.glob("*.png"):
            f.unlink()
        
        print(f"Final video: {output_path}")
        return output_path
    
    def generate_thumbnail(self, script: VideoScript) -> Optional[str]:
        """Generate high-CTR thumbnail."""
        try:
            thumb = Image.new("RGB", (1280, 720), Config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(thumb)
            
            # Gradient background
            for y in range(0, 720, 4):
                ratio = y / 720
                r = int(10 + 20 * ratio)
                g = int(5 + 10 * ratio)
                b = int(25 + 35 * ratio)
                draw.line([(0, y), (1280, y)], fill=(r, g, b), width=4)
            
            # Title text (large, high contrast)
            title = script.seo_title[:60]
            font = load_font(72)
            lines = self._wrap_text(title, font, 1100)
            y_pos = 200
            for line in lines[:2]:
                bbox = font.getbbox(line)
                if bbox:
                    x = (1280 - (bbox[2] - bbox[0])) // 2
                    for offset in [(3, 3), (-3, -3), (3, -3), (-3, 3)]:
                        draw.text((x + offset[0], y_pos + offset[1]), line, font=font, fill=(0, 0, 0))
                    draw.text((x, y_pos), line, font=font, fill=Config.COLOR_HIGHLIGHT)
                    y_pos += 90
            
            # Channel watermark
            font_sm = load_font(36)
            draw.text((50, 650), "AjeebOology", font=font_sm, fill=Config.COLOR_ACCENT)
            
            # Accent bars
            draw.rectangle([0, 0, 1280, 8], fill=Config.COLOR_ACCENT)
            draw.rectangle([0, 712, 1280, 720], fill=Config.COLOR_ACCENT_2)
            
            thumb_path = str(Config.OUTPUT_DIR / "thumbnail.jpg")
            thumb.save(thumb_path, "JPEG", quality=92)
            return thumb_path
        except Exception as e:
            print(f"Thumbnail error: {e}")
            return None

# =============================================================================
# 7. TELEGRAM DELIVERY
# =============================================================================

class TelegramAgent:
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
    
    def send_video(self, video_path: str, script: VideoScript, thumb_path: Optional[str] = None):
        """Send video to Telegram with metadata."""
        if not self.token or not self.chat_id:
            print("Telegram credentials not configured")
            return
        
        caption = self._build_caption(script)
        
        try:
            with open(video_path, "rb") as vf:
                files = {"video": vf}
                data = {
                    "chat_id": self.chat_id,
                    "caption": caption[:1024],
                    "parse_mode": "HTML"
                }
                if thumb_path and os.path.exists(thumb_path):
                    with open(thumb_path, "rb") as tf:
                        files["thumbnail"] = tf
                        resp = requests.post(
                            f"{self.base_url}/sendVideo",
                            data=data, files=files, timeout=120
                        )
                else:
                    resp = requests.post(
                        f"{self.base_url}/sendVideo",
                        data=data, files=files, timeout=120
                    )
                if resp.status_code == 200:
                    print("Video sent to Telegram successfully")
                else:
                    print(f"Telegram error: {resp.text}")
        except Exception as e:
            print(f"Telegram send error: {e}")
    
    def _build_caption(self, script: VideoScript) -> str:
        """Build Telegram caption."""
        lines = [
            f"<b>{script.seo_title}</b>",
            "",
            f"Category: {script.category}",
            f"Tags: {', '.join(script.tags[:5])}",
            "",
            "Hashtags:",
            " ".join(script.hashtags[:8])
        ]
        return "\n".join(lines)


# =============================================================================
# 8. YOUTUBE UPLOAD AGENT
# =============================================================================

class YouTubeAgent:
    def __init__(self):
        self.client_secrets = Config.YOUTUBE_CLIENT_SECRETS
    
    def upload_video(self, video_path: str, script: VideoScript,
                     thumb_path: Optional[str] = None) -> Optional[str]:
        """Upload video to YouTube via Data API v3."""
        if not self.client_secrets:
            print("YouTube client secrets not configured, skipping upload")
            return None
        
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            import pickle
            
            creds = None
            token_path = str(Config.BASE_DIR / "youtube_token.pickle")
            if os.path.exists(token_path):
                with open(token_path, "rb") as token:
                    creds = pickle.load(token)
            
            if not creds or not creds.valid:
                print("YouTube credentials not available or expired.")
                print("Please run OAuth flow locally and upload token.pickle to secrets.")
                return None
            
            youtube = build("youtube", "v3", credentials=creds)
            
            body = {
                "snippet": {
                    "title": script.seo_title[:100],
                    "description": self._build_description(script),
                    "tags": script.tags[:15],
                    "categoryId": "24",
                    "defaultLanguage": "hi",
                    "defaultAudioLanguage": "hi"
                },
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": False
                }
            }
            
            media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            
            print("Uploading to YouTube...")
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"Upload progress: {int(status.progress() * 100)}%")
            
            video_id = response.get("id")
            print(f"YouTube upload complete: https://youtu.be/{video_id}")
            
            if thumb_path and video_id:
                try:
                    youtube.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")
                    ).execute()
                    print("Thumbnail uploaded")
                except Exception as e:
                    print(f"Thumbnail upload error: {e}")
            
            return video_id
            
        except ImportError:
            print("google-api-python-client not installed, skipping YouTube upload")
            return None
        except Exception as e:
            print(f"YouTube upload error: {e}")
            return None
    
    def _build_description(self, script: VideoScript) -> str:
        """Build YouTube description."""
        lines = [
            script.description,
            "",
            "Follow AjeebOology for daily mind-blowing facts!",
            "",
            "Hashtags:",
            " ".join(script.hashtags),
            "",
            "Tags:",
            ", ".join(script.tags)
        ]
        return "\n".join(lines)

# =============================================================================
# 9. MAIN PIPELINE
# =============================================================================

class AjeebologyPipeline:
    def __init__(self):
        ensure_dirs()
        self.script_agent = ScriptAgent()
        self.research_agent = ResearchAgent()
        self.voice_agent = VoiceAgent()
        self.asset_agent = AssetAgent()
        self.video_engine = VideoEngine()
        self.telegram_agent = TelegramAgent()
        self.youtube_agent = YouTubeAgent()
    
    def run(self):
        """Execute full pipeline."""
        print("=" * 60)
        print("AJEEBOLOGY SHORTS PIPELINE STARTED")
        print("=" * 60)
        
        try:
            # Step 1: Research
            print("\n[1/7] Researching trending topics...")
            category = Config.CATEGORY_OVERRIDE or random.choice(["psychology", "space", "weird_facts"])
            research = self.research_agent.research(category)
            print(f"Research topic: {research.get('topic', category)}")
            
            # Step 2: Generate Script
            print("\n[2/7] Generating script...")
            script = self.script_agent.generate_script(research)
            print(f"Title: {script.seo_title}")
            print(f"Segments: {len(script.segments)}")
            
            # Step 3: Generate Voice
            print("\n[3/7] Generating voice...")
            audio_segments = self.voice_agent.generate_voice(script)
            total_voice = sum(s.duration for s in audio_segments)
            print(f"Total voice duration: {total_voice:.2f}s")
            
            # Step 4: Fetch Assets
            print("\n[4/7] Fetching b-roll assets...")
            broll_paths = []
            for i, seg in enumerate(script.segments):
                if seg.broll_prompt and Config.BROLL_ENABLED:
                    path = self.asset_agent.fetch_broll(seg.broll_prompt, i)
                    broll_paths.append(path)
                    print(f"  Segment {i} ({seg.segment_type}): {'OK' if path else 'FAIL'}")
                else:
                    broll_paths.append(None)
            
            print("Fetching background music...")
            bg_music = self.asset_agent.fetch_background_music()
            
            # Step 5: Mix Audio
            print("\n[5/7] Mixing audio with ducking...")
            final_audio = self.voice_agent.mix_audio(audio_segments, bg_music)
            final_duration = get_audio_duration(final_audio)
            print(f"Final audio duration: {final_duration:.2f}s")
            
            # Step 6: Render Video
            print("\n[6/7] Rendering video with karaoke captions...")
            video_path = self.video_engine.render_video(
                script, audio_segments, broll_paths, final_audio
            )
            
            print("Generating thumbnail...")
            thumb_path = self.video_engine.generate_thumbnail(script)
            
            # Step 7: Deliver
            print("\n[7/7] Delivering...")
            self.telegram_agent.send_video(video_path, script, thumb_path)
            
            # YouTube upload (optional)
            youtube_id = self.youtube_agent.upload_video(video_path, script, thumb_path)
            
            print("\n" + "=" * 60)
            print("PIPELINE COMPLETE")
            print(f"Video: {video_path}")
            if youtube_id:
                print(f"YouTube: https://youtu.be/{youtube_id}")
            print("=" * 60)
            
        except Exception as e:
            print(f"\nPIPELINE FAILED: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pipeline = AjeebologyPipeline()
    pipeline.run()
          
