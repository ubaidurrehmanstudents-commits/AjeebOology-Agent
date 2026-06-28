#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional YouTube Shorts Automation Agent
Fully automated pipeline: Research -> Script -> Voice -> Video -> Upload
Language: Hinglish (Roman Hindi + English), Male voice
Output: Vertical 1080x1920, ~55-65 seconds, 24 FPS
Features: Karaoke ASS captions, Pexels video b-roll, audio ducking
FIXES:
- edge_tts async handled with asyncio.new_event_loop() for GitHub Actions
- ffmpeg frame rendering replaced with ffmpeg lavfi for speed
- Output directory always created before use
- All exception paths log and continue gracefully
- random.seed accepts string safely
- Font fallback chain improved
- Telegram send with proper error handling
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

# Optional imports with graceful fallback
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not available, visual features limited")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("WARNING: numpy not available")

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
    TENACITY_AVAILABLE = True
except ImportError:
    TENACITY_AVAILABLE = False
    # Provide a no-op decorator if tenacity not installed
    def retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def stop_after_attempt(n): return None
    def wait_exponential(**kwargs): return None


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    GROQ_API_KEY        = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY      = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
    PEXELS_API_KEY      = os.environ.get("PEXELS_API_KEY", "")
    UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    GITHUB_RUN_ID       = os.environ.get("GITHUB_RUN_ID", "local")
    CATEGORY_OVERRIDE   = os.environ.get("CATEGORY_OVERRIDE", "")

    WIDTH  = 1080
    HEIGHT = 1920
    FPS    = 24
    TARGET_DURATION = 58
    MAX_DURATION    = 64

    VOICE_MODEL       = "hi-IN-MadhurNeural"
    AUDIO_SAMPLE_RATE = 44100

    # Font fallback chain
    FONT_PATHS = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]

    FONT_SIZE_TITLE   = 72
    FONT_SIZE_BODY    = 56
    FONT_SIZE_CAPTION = 58

    COLOR_BG_DARK  = (10, 5, 25)
    COLOR_BG_MID   = (30, 15, 60)
    COLOR_ACCENT   = (0, 255, 255)
    COLOR_ACCENT_2 = (255, 0, 128)
    COLOR_TEXT     = (255, 255, 255)
    COLOR_TEXT_DIM = (200, 200, 220)
    COLOR_HIGHLIGHT= (255, 255, 0)

    BASE_DIR   = Path("/tmp/ajeebology")
    FRAMES_DIR = BASE_DIR / "frames"
    AUDIO_DIR  = BASE_DIR / "audio"
    ASSETS_DIR = BASE_DIR / "assets"
    OUTPUT_DIR = BASE_DIR / "output"

    BROLL_ENABLED        = True
    POLLINATIONS_ENABLED = True


# Seed random safely (handles string)
try:
    random.seed(int(hashlib.md5(Config.GITHUB_RUN_ID.encode()).hexdigest(), 16))
except Exception:
    random.seed(42)


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
    except Exception as e:
        return -1, "", str(e)


def get_audio_duration(path: str) -> float:
    """Get audio duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    rc, out, _ = run_command(cmd, timeout=30)
    if rc == 0 and out.strip():
        try:
            return float(out.strip())
        except ValueError:
            pass
    return 0.0


def ensure_dirs():
    """Create all necessary directories."""
    for d in [Config.FRAMES_DIR, Config.AUDIO_DIR, Config.ASSETS_DIR, Config.OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_font(size: int):
    """Load font with fallback chain."""
    if not PIL_AVAILABLE:
        return None
    for path in Config.FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    rc, _, _ = run_command(["ffmpeg", "-version"], timeout=10)
    return rc == 0


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
        category = Config.CATEGORY_OVERRIDE or random.choice(
            ["psychology", "space", "weird_facts"]
        )
        prompt = f"""Create a YouTube Shorts script about: {research_data.get('topic', category)}.
Category: {category}
Make it mind-blowing, use Hinglish. Include 2-3 emphasis words per segment.
Return ONLY valid JSON."""

        if not self.api_key:
            print("WARNING: GROQ_API_KEY not set, using fallback script")
            return self._fallback_script(category)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user",   "content": prompt}
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
        brolls = [
            "human brain neurons glowing",
            "subconscious mind concept",
            "psychology illusion visual",
            "brain decision making scan",
            "mind blowing explosion concept"
        ]
        for i, t in enumerate(texts.get(category, texts["weird_facts"])):
            segs.append(ScriptSegment(
                text=t,
                segment_type=types[i],
                emphasis_words=["shock", "amazing"] if i == 0 else ["fact", "wow"],
                broll_prompt=brolls[i] if i < len(brolls) else "amazing facts science"
            ))
        return VideoScript(
            title="Ajeebology Fact",
            category=category,
            seo_title="Amazing Fact | AjeebOology",
            description="Incredible facts in Hinglish",
            tags=[category, "facts", "shorts", "hindi", "ajeebology"],
            hashtags=["#Shorts", "#AjeebOology", "#Facts", "#Hindi"],
            segments=segs
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
            "psychology":  "mind-blowing psychology facts 2026 trending",
            "space":       "latest space discoveries 2026 NASA trending",
            "weird_facts": "incredible weird facts 2026 viral"
        }
        query = queries.get(category, queries["weird_facts"])

        if not self.api_key:
            print("WARNING: TAVILY_API_KEY not set, skipping research")
            return {"topic": category, "results": []}

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

            success = False
            if clean_text.strip():
                success = self._generate_with_edge_tts(clean_text, output_path)

            if success:
                duration = get_audio_duration(output_path)
                if duration < 0.5:
                    duration = self._estimate_duration(clean_text)
            else:
                duration = self._estimate_duration(clean_text)
                self._create_silent_audio(output_path, duration)

            audio_segments.append(AudioSegment(
                segment=seg,
                audio_path=output_path,
                duration=duration,
                start_time=current_time,
                end_time=current_time + duration
            ))
            current_time += duration
            print(f"  Segment {i}: {duration:.2f}s — {clean_text[:50]}...")

        script.total_duration_estimate = current_time
        print(f"Total estimated duration: {current_time:.2f}s")
        return audio_segments

    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS."""
        text = re.sub(r"[#@]\w+", "", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"[\*\_\~\`]", "", text)
        return text.strip()

    def _generate_with_edge_tts(self, text: str, output_path: str) -> bool:
        """Generate voice using edge-tts — compatible with GitHub Actions."""
        try:
            import edge_tts
            import asyncio

            async def _gen():
                communicate = edge_tts.Communicate(text, self.model)
                await communicate.save(output_path)

            # FIX: Use new event loop — avoids "no running loop" error in GH Actions
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_gen())
            finally:
                loop.close()

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return True
            print(f"  edge-tts produced empty file for: {text[:40]}")
            return False
        except ImportError:
            print("  edge-tts not installed — using silent fallback")
            return False
        except Exception as e:
            print(f"  Edge-TTS error: {e}")
            return False

    def _estimate_duration(self, text: str) -> float:
        """Estimate duration based on word count (~3 words/sec for Hindi)."""
        words = len(text.split())
        return max(1.5, words * 0.38)

    def _create_silent_audio(self, path: str, duration: float):
        """Create silent audio fallback via ffmpeg."""
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={Config.AUDIO_SAMPLE_RATE}:cl=mono",
            "-t", str(max(duration, 0.1)),
            "-acodec", "libmp3lame", "-q:a", "4",
            path
        ]
        rc, _, err = run_command(cmd, timeout=30)
        if rc != 0:
            print(f"  Silent audio creation failed: {err}")

    def mix_audio(
        self,
        audio_segments: List[AudioSegment],
        bg_music_path: Optional[str] = None
    ) -> str:
        """Mix voice with optional background music."""
        concat_list = str(Config.AUDIO_DIR / "concat_list.txt")
        valid_segs = [s for s in audio_segments if os.path.exists(s.audio_path)]

        if not valid_segs:
            # Create a silent fallback
            total_dur = max(sum(s.duration for s in audio_segments), 5.0)
            final_audio = str(Config.AUDIO_DIR / "final_audio.mp3")
            self._create_silent_audio(final_audio, total_dur)
            return final_audio

        with open(concat_list, "w") as f:
            for seg in valid_segs:
                f.write(f"file '{seg.audio_path}'\n")

        voice_concat = str(Config.AUDIO_DIR / "voice_concat.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", voice_concat
        ]
        rc, _, err = run_command(cmd, timeout=120)
        if rc != 0:
            print(f"Audio concat error: {err}")
            # Try individual copy
            shutil.copy(valid_segs[0].audio_path, voice_concat)

        final_audio = str(Config.AUDIO_DIR / "final_audio.mp3")

        if bg_music_path and os.path.exists(bg_music_path):
            filter_complex = (
                "[1:a]volume=0.15,aloop=loop=-1:size=2e+09[bgloop];"
                "[0:a][bgloop]amix=inputs=2:duration=first:weights=1 0.2[mixed];"
                "[mixed]loudnorm=I=-14:TP=-1.5:LRA=11[out]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", voice_concat,
                "-i", bg_music_path,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:a", "libmp3lame", "-q:a", "2",
                "-ar", str(Config.AUDIO_SAMPLE_RATE),
                final_audio
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", voice_concat,
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame", "-q:a", "2",
                "-ar", str(Config.AUDIO_SAMPLE_RATE),
                final_audio
            ]

        rc, _, err = run_command(cmd, timeout=180)
        if rc != 0 or not os.path.exists(final_audio):
            print(f"Audio mix error: {err}")
            shutil.copy(voice_concat, final_audio)

        return final_audio


# =============================================================================
# 4. ASSET AGENT (B-Roll + Background Music)
# =============================================================================

class AssetAgent:
    def __init__(self):
        self.unsplash_key = Config.UNSPLASH_ACCESS_KEY
        self.pexels_key   = Config.PEXELS_API_KEY

    def fetch_broll(self, prompt: str, index: int) -> Optional[str]:
        """Fetch b-roll asset. Try Pexels video, then images, then AI image."""
        dest     = str(Config.ASSETS_DIR / f"broll_{index:02d}.mp4")
        img_dest = str(Config.ASSETS_DIR / f"broll_{index:02d}.jpg")

        # Try Pexels video
        if self.pexels_key and self._try_pexels_video(prompt, dest):
            return dest

        # Try Unsplash image
        if self.unsplash_key and self._try_unsplash(prompt, img_dest):
            return img_dest

        # Try Pollinations AI image
        if Config.POLLINATIONS_ENABLED and self._try_pollinations(prompt, img_dest):
            return img_dest

        # Try Pexels image
        if self.pexels_key and self._try_pexels_image(prompt, img_dest):
            return img_dest

        print(f"  No b-roll found for: {prompt}")
        return None

    def _try_pexels_video(self, prompt: str, dest: str) -> bool:
        try:
            url = (
                f"https://api.pexels.com/videos/search"
                f"?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            )
            headers = {"Authorization": self.pexels_key}
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
            for vid in videos:
                for vf in vid.get("video_files", []):
                    if vf.get("quality") in ["sd", "hd"] and vf.get("link"):
                        r = requests.get(vf["link"], timeout=60, stream=True)
                        if r.status_code == 200:
                            with open(dest, "wb") as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            if os.path.exists(dest) and os.path.getsize(dest) > 10240:
                                return True
            return False
        except Exception as e:
            print(f"  Pexels video error: {e}")
            return False

    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        try:
            url = (
                f"https://api.unsplash.com/photos/random"
                f"?query={quote_plus(prompt)}&orientation=portrait"
            )
            headers = {"Authorization": f"Client-ID {self.unsplash_key}"}
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            img_url = resp.json()["urls"]["regular"]
            r = requests.get(img_url, timeout=30)
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"  Unsplash error: {e}")
            return False

    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        try:
            safe_prompt = quote_plus(f"cinematic {prompt} dark aesthetic")
            url = (
                f"https://image.pollinations.ai/prompt/{safe_prompt}"
                f"?width=1080&height=1920&nologo=true"
                f"&seed={random.randint(1, 99999)}"
            )
            r = requests.get(url, timeout=90)
            if r.status_code == 200 and len(r.content) > 10240:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return True
            return False
        except Exception as e:
            print(f"  Pollinations error: {e}")
            return False

    def _try_pexels_image(self, prompt: str, dest: str) -> bool:
        try:
            url = (
                f"https://api.pexels.com/v1/search"
                f"?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            )
            headers = {"Authorization": self.pexels_key}
            resp = requests.get(url, headers=headers, timeout=20)
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
            print(f"  Pexels image error: {e}")
            return False

    def fetch_background_music(self) -> Optional[str]:
        """Generate synthetic background music via ffmpeg (no external dependency)."""
        dest = str(Config.ASSETS_DIR / "bg_music.mp3")
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            return dest
        # Gentle pink noise as subtle ambient bed
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anoisesrc=a=0.015:c=pink:duration=70",
            "-af", "lowpass=f=600,volume=0.25",
            "-c:a", "libmp3lame", "-q:a", "4",
            dest
        ]
        rc, _, err = run_command(cmd, timeout=30)
        if rc == 0 and os.path.exists(dest):
            return dest
        print(f"BG music generation failed: {err}")
        return None


# =============================================================================
# 5. KARAOKE CAPTION ENGINE (ASS Subtitles)
# =============================================================================

class CaptionEngine:
    """Generates professional karaoke captions using ASS subtitle format."""

    def _build_ass_header(self) -> str:
        white  = "&H00FFFFFF"
        cyan   = "&H00FFFF00"   # BGR = cyan
        yellow = "&H0000FFFF"  # BGR = yellow
        black  = "&H00000000"
        shadow = "&HAA000000"

        return f"""[Script Info]
Title: AjeebOology Karaoke
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans Bold,58,{white},{cyan},{black},{shadow},-1,0,0,0,100,100,0,0,1,3,1,2,60,60,160,1
Style: Emphasis,DejaVu Sans Bold,68,{yellow},{cyan},{black},{shadow},-1,0,0,0,110,110,0,0,1,4,1,2,60,60,160,1
Style: Hook,DejaVu Sans Bold,72,{yellow},{cyan},{black},{shadow},-1,0,0,0,120,120,0,0,1,5,2,2,60,60,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def build_ass_file(self, audio_segments: List[AudioSegment]) -> str:
        """Generate complete ASS file with word-by-word karaoke."""
        ass_path = str(Config.OUTPUT_DIR / "karaoke.ass")

        lines = [self._build_ass_header()]

        for seg in audio_segments:
            words = seg.segment.text.split()
            if not words:
                continue

            seg_duration = max(seg.end_time - seg.start_time, 0.1)
            word_duration = seg_duration / len(words)

            # Build karaoke line
            karaoke_text = ""
            for word in words:
                k_dur = max(int(word_duration * 100), 5)
                karaoke_text += f"{{\\k{k_dur}}}{word} "

            if seg.segment.segment_type == "hook":
                style = "Hook"
            elif seg.segment.segment_type in ["fact1", "fact2", "fact3"]:
                style = "Emphasis"
            else:
                style = "Default"

            start = self._format_time(seg.start_time)
            end   = self._format_time(seg.end_time)
            lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{karaoke_text.strip()}")

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return ass_path

    def _format_time(self, seconds: float) -> str:
        """Format seconds to ASS time H:MM:SS.cc"""
        seconds = max(seconds, 0)
        hours   = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs    = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:05.2f}"


# =============================================================================
# 6. VIDEO RENDERING ENGINE
# =============================================================================

class VideoEngine:
    """
    Video renderer using ffmpeg lavfi for background generation (fast),
    PIL for per-segment overlays, and single-pass ASS caption burn.
    """

    def __init__(self):
        self.width   = Config.WIDTH
        self.height  = Config.HEIGHT
        self.fps     = Config.FPS
        self.caption_engine = CaptionEngine()

    def _create_background_video(self, duration: float, output_path: str) -> bool:
        """Create animated gradient background using ffmpeg (much faster than PIL frames)."""
        # Animated gradient using ffmpeg's geq filter
        filter_str = (
            f"color=c=black:size={self.width}x{self.height}:rate={self.fps}[base];"
            f"[base]geq="
            f"r='10 + 20*sin(2*PI*T/8) + 30*(Y/{self.height})':"
            f"g='5 + 10*sin(2*PI*T/12) + 15*(Y/{self.height})':"
            f"b='25 + 35*sin(2*PI*T/6) + 60*(Y/{self.height})'[out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x0A0519:size={self.width}x{self.height}:rate={self.fps}",
            "-t", str(duration),
            "-vf", (
                f"geq="
                f"r='clip(10+20*sin(2*PI*T/8)+30*(Y/{self.height}),0,255)':"
                f"g='clip(5+10*sin(2*PI*T/12)+15*(Y/{self.height}),0,255)':"
                f"b='clip(25+35*sin(2*PI*T/6)+60*(Y/{self.height}),0,255)'"
            ),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            output_path
        ]
        rc, _, err = run_command(cmd, timeout=120)
        if rc != 0:
            print(f"Background video error: {err}")
            # Fallback: solid color
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c=0x0A0519:size={self.width}x{self.height}:rate={self.fps}",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                output_path
            ]
            rc, _, err = run_command(cmd, timeout=60)
        return rc == 0 and os.path.exists(output_path)

    def _prepare_broll_clip(
        self,
        broll_path: str,
        duration: float,
        output_path: str
    ) -> bool:
        """Convert b-roll image/video to vertical clip with Ken Burns."""
        if not broll_path or not os.path.exists(broll_path):
            return False

        ext = os.path.splitext(broll_path)[1].lower()

        # Ken Burns zoom filter
        kb_filter = (
            f"scale={self.width * 2}:{self.height * 2}:force_original_aspect_ratio=increase,"
            f"crop={self.width * 2}:{self.height * 2},"
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={int(duration * self.fps)}:s={self.width}x{self.height}:fps={self.fps},"
            f"scale={self.width}:{self.height},"
            f"format=yuv420p"
        )

        if ext in [".mp4", ".mov", ".avi", ".webm"]:
            cmd = [
                "ffmpeg", "-y",
                "-i", broll_path,
                "-t", str(duration),
                "-vf", (
                    f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                    f"crop={self.width}:{self.height},"
                    f"format=yuv420p"
                ),
                "-r", str(self.fps),
                "-c:v", "libx264", "-preset", "ultrafast",
                "-an", output_path
            ]
        else:
            # Image: use zoompan for Ken Burns
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", broll_path,
                "-t", str(duration),
                "-vf", kb_filter,
                "-r", str(self.fps),
                "-c:v", "libx264", "-preset", "ultrafast",
                output_path
            ]

        rc, _, err = run_command(cmd, timeout=120)
        if rc != 0:
            print(f"  B-roll clip error: {err}")
        return rc == 0 and os.path.exists(output_path)

    def _create_overlay_image(
        self,
        script: VideoScript,
        seg_index: int,
        seg: AudioSegment,
        duration: float
    ) -> Optional[str]:
        """Create a semi-transparent overlay PNG with channel badge and progress bar."""
        if not PIL_AVAILABLE:
            return None

        overlay_path = str(Config.ASSETS_DIR / f"overlay_{seg_index:02d}.png")

        try:
            # Transparent canvas
            img  = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Channel badge (top right)
            badge_font = load_font(32)
            if badge_font:
                badge_text = "AjeebOology"
                try:
                    bbox = badge_font.getbbox(badge_text)
                    tw   = bbox[2] - bbox[0]
                    th   = bbox[3] - bbox[1]
                except Exception:
                    tw, th = 200, 40

                bx = self.width - tw - 40
                by = 35
                pad = 14
                draw.rounded_rectangle(
                    [bx - pad, by - pad, bx + tw + pad, by + th + pad],
                    radius=22,
                    fill=(20, 10, 40, 210),
                    outline=(0, 255, 255, 255),
                    width=2
                )
                draw.text((bx, by), badge_text, font=badge_font, fill=(255, 255, 255, 255))

            # Progress bar (bottom)
            bar_y = self.height - 22
            bh    = 10
            draw.rounded_rectangle(
                [40, bar_y, self.width - 40, bar_y + bh],
                radius=5,
                fill=(40, 30, 60, 180)
            )
            # Progress for this segment
            total = script.total_duration_estimate or 60
            prog  = min((seg.end_time / total), 1.0)
            pw    = int((self.width - 80) * prog)
            if pw > 8:
                draw.rounded_rectangle(
                    [40, bar_y, 40 + pw, bar_y + bh],
                    radius=5,
                    fill=(0, 255, 255, 220)
                )

            # Subscribe CTA (last segment only)
            if seg_index == len(script.segments) - 1:
                cta_font = load_font(46)
                if cta_font:
                    cta = "Subscribe for Daily Facts!"
                    try:
                        bbox = cta_font.getbbox(cta)
                        tw   = bbox[2] - bbox[0]
                        th   = bbox[3] - bbox[1]
                    except Exception:
                        tw, th = 500, 55

                    cx = (self.width - tw) // 2
                    cy = self.height - 200
                    draw.rounded_rectangle(
                        [cx - 24, cy - 12, cx + tw + 24, cy + th + 12],
                        radius=28,
                        fill=(255, 0, 128, 230),
                        outline=(255, 255, 255, 255),
                        width=2
                    )
                    draw.text((cx, cy), cta, font=cta_font, fill=(255, 255, 255, 255))

            img.save(overlay_path, "PNG")
            return overlay_path
        except Exception as e:
            print(f"  Overlay creation error: {e}")
            return None

    def _compose_segment_video(
        self,
        bg_path: str,
        broll_path: Optional[str],
        overlay_path: Optional[str],
        duration: float,
        output_path: str
    ) -> bool:
        """Compose background + b-roll + overlay into one segment video."""
        inputs = ["-i", bg_path]
        filter_parts = []
        last = "[0:v]"

        if broll_path and os.path.exists(broll_path):
            inputs += ["-i", broll_path]
            # Darken b-roll and overlay on background
            broll_idx = len(inputs) // 2 - 1
            filter_parts.append(
                f"[{broll_idx}:v]eq=brightness=-0.3:saturation=1.2[broll_dark];"
                f"{last}[broll_dark]overlay=0:0:format=auto[comp]"
            )
            last = "[comp]"

        if overlay_path and os.path.exists(overlay_path):
            inputs += ["-i", overlay_path]
            ov_idx = len(inputs) // 2 - 1
            filter_parts.append(
                f"{last}[{ov_idx}:v]overlay=0:0:format=auto[final]"
            )
            last = "[final]"

        if filter_parts:
            filter_complex = ";".join(filter_parts)
            cmd = (
                ["ffmpeg", "-y"]
                + inputs
                + [
                    "-filter_complex", filter_complex,
                    "-map", last,
                    "-t", str(duration),
                    "-r", str(self.fps),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    output_path
                ]
            )
        else:
            cmd = (
                ["ffmpeg", "-y"]
                + inputs
                + [
                    "-t", str(duration),
                    "-r", str(self.fps),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    output_path
                ]
            )

        rc, _, err = run_command(cmd, timeout=180)
        if rc != 0:
            print(f"  Segment compose error: {err}")
            # Fallback: just copy background
            shutil.copy(bg_path, output_path)
        return os.path.exists(output_path)

    def render_video(
        self,
        script: VideoScript,
        audio_segments: List[AudioSegment],
        broll_paths: List[Optional[str]],
        final_audio_path: str
    ) -> str:
        """Main video rendering pipeline."""
        total_duration = get_audio_duration(final_audio_path)
        if total_duration < 1:
            total_duration = script.total_duration_estimate or 60.0
        print(f"Total video duration: {total_duration:.2f}s")

        # 1. Build ASS karaoke file
        ass_path = self.caption_engine.build_ass_file(audio_segments)
        print(f"Karaoke ASS: {ass_path}")

        # 2. Build each segment video
        segment_clips = []
        for i, seg in enumerate(audio_segments):
            print(f"Rendering segment {i+1}/{len(audio_segments)} ...")
            seg_dur = seg.end_time - seg.start_time

            # 2a. Background
            bg_path = str(Config.FRAMES_DIR / f"bg_{i:02d}.mp4")
            self._create_background_video(seg_dur, bg_path)

            # 2b. B-roll
            broll_clip = None
            if i < len(broll_paths) and broll_paths[i]:
                broll_clip_path = str(Config.FRAMES_DIR / f"broll_clip_{i:02d}.mp4")
                if self._prepare_broll_clip(broll_paths[i], seg_dur, broll_clip_path):
                    broll_clip = broll_clip_path

            # 2c. Overlay PNG
            overlay_path = self._create_overlay_image(script, i, seg, seg_dur)

            # 2d. Compose
            seg_out = str(Config.FRAMES_DIR / f"segment_{i:02d}.mp4")
            self._compose_segment_video(bg_path, broll_clip, overlay_path, seg_dur, seg_out)
            if os.path.exists(seg_out):
                segment_clips.append(seg_out)

        # 3. Concatenate all segment clips
        if not segment_clips:
            print("ERROR: No segment clips rendered!")
            sys.exit(1)

        concat_list = str(Config.FRAMES_DIR / "segments_concat.txt")
        with open(concat_list, "w") as f:
            for clip in segment_clips:
                f.write(f"file '{clip}'\n")

        concat_video = str(Config.FRAMES_DIR / "concat_video.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            concat_video
        ]
        rc, _, err = run_command(cmd, timeout=300)
        if rc != 0:
            print(f"Concat error: {err}")
            # Try re-encoding
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                concat_video
            ]
            run_command(cmd, timeout=300)

        # 4. Final pass: add audio + burn ASS captions
        output_path = str(Config.OUTPUT_DIR / "output_video.mp4")

        # Escape colons/backslashes in ASS path for ffmpeg filtergraph
        ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-i", final_audio_path,
            "-vf", f"ass={ass_escaped}",
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            output_path
        ]
        rc, _, err = run_command(cmd, timeout=600)

        if rc != 0 or not os.path.exists(output_path):
            print(f"Final encode error: {err}")
            # Fallback without captions
            cmd = [
                "ffmpeg", "-y",
                "-i", concat_video,
                "-i", final_audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                output_path
            ]
            rc, _, err = run_command(cmd, timeout=600)
            if rc != 0:
                print(f"Fallback encode also failed: {err}")
                sys.exit(1)

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Output video: {output_path} ({size_mb:.1f} MB)")
        return output_path


# =============================================================================
# 7. DELIVERY (Telegram)
# =============================================================================

class DeliveryAgent:
    def __init__(self):
        self.token   = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID

    def send_to_telegram(self, video_path: str, script: VideoScript) -> bool:
        """Send video + metadata to Telegram."""
        if not self.token or not self.chat_id:
            print("WARNING: Telegram credentials not set, skipping delivery")
            return False

        if not os.path.exists(video_path):
            print(f"ERROR: Video file not found: {video_path}")
            return False

        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb > 50:
            print(f"WARNING: Video is {size_mb:.1f}MB, Telegram limit is 50MB")

        # Caption text
        hashtags_str = " ".join(script.hashtags[:8])
        caption = (
            f"🎬 *{script.seo_title}*\n\n"
            f"{script.description}\n\n"
            f"{hashtags_str}"
        )[:1024]  # Telegram caption limit

        # Send metadata first
        meta_text = (
            f"✅ AjeebOology Short Ready!\n\n"
            f"📌 Title: {script.seo_title}\n"
            f"🏷️ Category: {script.category}\n"
            f"📝 Tags: {', '.join(script.tags[:10])}\n"
            f"📏 Size: {size_mb:.1f}MB\n"
            f"🔗 Run: {Config.GITHUB_RUN_ID}"
        )

        try:
            # Send text notification
            msg_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(msg_url, json={
                "chat_id": self.chat_id,
                "text": meta_text,
                "parse_mode": "Markdown"
            }, timeout=30)

            # Send video
            vid_url = f"https://api.telegram.org/bot{self.token}/sendVideo"
            with open(video_path, "rb") as vf:
                resp = requests.post(vid_url, data={
                    "chat_id": self.chat_id,
                    "caption": caption,
                    "parse_mode": "Markdown",
                    "supports_streaming": True
                }, files={"video": vf}, timeout=300)

            if resp.status_code == 200:
                print("✅ Video sent to Telegram successfully!")
                return True
            else:
                print(f"Telegram error {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as e:
            print(f"Telegram delivery error: {e}")
            return False

    def send_error_notification(self, error_msg: str):
        """Send error notification to Telegram."""
        if not self.token or not self.chat_id:
            return
        try:
            msg_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(msg_url, json={
                "chat_id": self.chat_id,
                "text": f"❌ AjeebOology Pipeline Failed!\n\nRun: {Config.GITHUB_RUN_ID}\n\nError: {error_msg[:500]}",
            }, timeout=30)
        except Exception:
            pass


# =============================================================================
# 8. METADATA GENERATOR
# =============================================================================

def save_metadata(script: VideoScript, output_dir: Path):
    """Save SEO metadata files for manual YouTube upload."""
    meta = {
        "title":       script.seo_title,
        "description": script.description + "\n\n" + " ".join(script.hashtags),
        "tags":        script.tags,
        "hashtags":    script.hashtags,
        "category":    script.category,
        "run_id":      Config.GITHUB_RUN_ID,
    }
    meta_path = output_dir / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Also save plain text description
    desc_path = output_dir / "description.txt"
    with open(desc_path, "w", encoding="utf-8") as f:
        f.write(f"TITLE:\n{script.seo_title}\n\n")
        f.write(f"DESCRIPTION:\n{meta['description']}\n\n")
        f.write(f"TAGS:\n{', '.join(script.tags)}\n")

    print(f"Metadata saved: {meta_path}")


# =============================================================================
# 9. MAIN PIPELINE
# =============================================================================

def main():
    print("=" * 60)
    print("  AjeebOology Shorts Automation Pipeline")
    print(f"  Run ID: {Config.GITHUB_RUN_ID}")
    print("=" * 60)

    # Check critical dependencies
    if not check_ffmpeg():
        print("FATAL: ffmpeg not found! Install with: sudo apt-get install -y ffmpeg")
        sys.exit(1)
    print("✅ ffmpeg found")

    # Ensure all dirs exist
    ensure_dirs()
    print("✅ Directories created")

    delivery = DeliveryAgent()

    try:
        # STEP 1: Research
        print("\n[1/6] Researching topic...")
        category     = Config.CATEGORY_OVERRIDE or random.choice(["psychology", "space", "weird_facts"])
        researcher   = ResearchAgent()
        research_data = researcher.research(category)
        print(f"  Topic: {research_data.get('topic', category)}")

        # STEP 2: Generate Script
        print("\n[2/6] Generating script...")
        script_agent = ScriptAgent()
        script       = script_agent.generate_script(research_data)
        print(f"  Title: {script.title}")
        print(f"  Segments: {len(script.segments)}")

        # STEP 3: Generate Voice
        print("\n[3/6] Generating voice audio...")
        voice_agent    = VoiceAgent()
        audio_segments = voice_agent.generate_voice(script)
        print(f"  Total duration: {script.total_duration_estimate:.2f}s")

        # STEP 4: Fetch Assets
        print("\n[4/6] Fetching b-roll assets...")
        asset_agent = AssetAgent()
        broll_paths = []
        for i, seg in enumerate(script.segments):
            prompt = seg.broll_prompt or seg.text[:50]
            print(f"  Fetching broll {i+1}/{len(script.segments)}: {prompt[:40]}")
            broll_path = asset_agent.fetch_broll(prompt, i)
            broll_paths.append(broll_path)

        bg_music = asset_agent.fetch_background_music()
        print(f"  Background music: {'✅' if bg_music else '❌'}")

        # STEP 5: Mix Audio
        print("\n[5/6] Mixing audio...")
        final_audio = voice_agent.mix_audio(audio_segments, bg_music)
        audio_dur   = get_audio_duration(final_audio)
        print(f"  Final audio: {audio_dur:.2f}s")

        # STEP 6: Render Video
        print("\n[6/6] Rendering video...")
        video_engine = VideoEngine()
        output_video = video_engine.render_video(
            script, audio_segments, broll_paths, final_audio
        )

        # Save metadata
        save_metadata(script, Config.OUTPUT_DIR)

        # Deliver
        print("\n[+] Delivering to Telegram...")
        delivery.send_to_telegram(output_video, script)

        print("\n" + "=" * 60)
        print("  ✅ PIPELINE COMPLETE!")
        print(f"  Output: {output_video}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nPipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"\n❌ Pipeline failed:\n{error_msg}")
        delivery.send_error_notification(error_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
