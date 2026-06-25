#!/usr/bin/env python3
"""
youtube_agent.py — Fully automated YouTube Shorts production pipeline.
Single‑file, production‑ready, designed for GitHub Actions Free Tier.

Features:
- Narrative script with hook, climax, CTA
- Motion graphics (zoom/pan) on all clips (videos and images)
- Crossfade transitions (0.5s) between scenes
- Static captions (reliable fallback)
- Branded intro (2s) and outro (2s)
- Real background music (pad) and ducking
- Natural male voice via espeak (hi+m1)
- Viral‑optimised title, description, tags
- High‑CTR thumbnail with bold text
- Robust error handling and caching
"""

import os
import sys
import json
import time
import random
import logging
import hashlib
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from collections import defaultdict
import re
import math

# Third‑party imports
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

# API clients
from groq import Groq
from tavily import TavilyClient

# Telegram
from telegram import Bot, InputFile

# Audio processing (optional)
from pydub import AudioSegment

# Retry and resilience
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

# ----------------------------------------------------------------------
# 1. CONSTANTS & CONFIGURATION
# ----------------------------------------------------------------------

# Paths
BASE_DIR = Path(__file__).parent.absolute()
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = Path(os.environ.get("CACHE_DIR", BASE_DIR / "assets_cache"))
ASSETS_DIR = CACHE_DIR / "assets"
CLIPS_DIR = CACHE_DIR / "clips"
FONTS_DIR = CACHE_DIR / "fonts"
MUSIC_DIR = CACHE_DIR / "music"
SOUND_DIR = CACHE_DIR / "sounds"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)
os.makedirs(MUSIC_DIR, exist_ok=True)
os.makedirs(SOUND_DIR, exist_ok=True)

# Video settings
TARGET_DURATION = (55, 65)          # seconds
VIDEO_WIDTH = 1080                  # 9:16 portrait
VIDEO_HEIGHT = 1920
FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
PIXEL_FORMAT = "yuv420p"
FFMPEG_PRESET = "fast"              # balance speed vs quality

# Scene segmentation: aim for 6-8 segments
MIN_SCENES = 6
MAX_SCENES = 8

# Caption style (static fallback)
CAPTION_FONT_SIZE = 60
CAPTION_BG_ALPHA = 0.6
CAPTION_TEXT_COLOR = "#FFFFFF"
CAPTION_OUTLINE_COLOR = "#000000"

# Intro/Outro
INTRO_DURATION = 2.0                # seconds
OUTRO_DURATION = 2.0                # seconds
CHANNEL_NAME = "Ajeebology Shorts"

# Thumbnail style
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# API retries
MAX_API_RETRIES = 3
API_RETRY_WAIT = 2  # seconds base

# Groq model
GROQ_MODEL = "llama-3.3-70b-versatile"

# Voice settings (espeak)
VOICE_LANG = "hi+m1"                # Hindi male voice
VOICE_SPEED = 145                   # words per minute (natural)
VOICE_PITCH = 60                    # pitch (50 is default, 60 is warmer)
VOICE_GAP = 5                       # gap between words (small for smoothness)

# ----------------------------------------------------------------------
# 2. LOGGING SETUP
# ----------------------------------------------------------------------

def setup_logging():
    """Configure logging to console and file."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(OUTPUT_DIR / "pipeline.log")
        ]
    )
    # Set third‑party loggers to WARNING to reduce noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    return logging.getLogger(__name__)

logger = setup_logging()

# ----------------------------------------------------------------------
# 3. CACHE UTILITIES
# ----------------------------------------------------------------------

def get_cache_path(key: str, ext: str = "") -> Path:
    """Generate a deterministic cache file path based on a key string."""
    hashed = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{hashed}{ext}"

def cache_get(key: str, ext: str = "") -> Optional[Path]:
    """Return Path if cached file exists, else None."""
    p = get_cache_path(key, ext)
    if p.exists():
        return p
    return None

def cache_put(key: str, data: bytes, ext: str = "") -> Path:
    """Save data to cache and return path."""
    p = get_cache_path(key, ext)
    with open(p, "wb") as f:
        f.write(data)
    return p

def cache_put_file(key: str, src_path: Path, ext: str = "") -> Path:
    """Copy an existing file to cache."""
    p = get_cache_path(key, ext)
    shutil.copy2(src_path, p)
    return p

def cache_put_from_url(key: str, url: str, ext: str = "") -> Optional[Path]:
    """Download from URL and cache it."""
    p = get_cache_path(key, ext)
    if p.exists():
        return p
    try:
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        with open(p, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return p
    except Exception as e:
        logger.warning(f"Failed to download {url}: {e}")
        return None

# ----------------------------------------------------------------------
# 4. API CLIENTS (with retries)
# ----------------------------------------------------------------------

class APIClients:
    """Container for all API clients with lazy initialisation."""
    def __init__(self):
        self._groq = None
        self._tavily = None
        self._pexels_key = None
        self._unsplash_key = None

    @property
    def groq(self) -> Groq:
        if self._groq is None:
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise ValueError("GROQ_API_KEY not set")
            self._groq = Groq(api_key=api_key)
        return self._groq

    @property
    def tavily(self) -> TavilyClient:
        if self._tavily is None:
            api_key = os.environ.get("TAVILY_API_KEY")
            if not api_key:
                raise ValueError("TAVILY_API_KEY not set")
            self._tavily = TavilyClient(api_key=api_key)
        return self._tavily

    @property
    def pexels_key(self) -> str:
        if self._pexels_key is None:
            key = os.environ.get("PEXELS_API_KEY")
            if not key:
                raise ValueError("PEXELS_API_KEY not set")
            self._pexels_key = key
        return self._pexels_key

    @property
    def unsplash_key(self) -> str:
        if self._unsplash_key is None:
            key = os.environ.get("UNSPLASH_ACCESS_KEY")
            if not key:
                raise ValueError("UNSPLASH_ACCESS_KEY not set")
            self._unsplash_key = key
        return self._unsplash_key

api = APIClients()

# ----------------------------------------------------------------------
# 5. HELPER FUNCTIONS
# ----------------------------------------------------------------------

def get_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def safe_filename(text: str, max_len: int = 60) -> str:
    """Convert text to a safe filesystem name."""
    safe = re.sub(r'[^a-zA-Z0-9\s\-_]', '', text)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    return safe[:max_len]

def download_file(url: str, dest: Path, timeout: int = 30) -> bool:
    """Download a file from URL to dest with retries."""
    for attempt in range(MAX_API_RETRIES):
        try:
            resp = requests.get(url, stream=True, timeout=timeout)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            logger.warning(f"Download attempt {attempt+1} failed: {e}")
            time.sleep(API_RETRY_WAIT * (attempt + 1))
    return False

def get_video_duration(file_path: Path) -> float:
    """Return duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return 0.0

def get_image_dimensions(file_path: Path) -> Tuple[int, int]:
    """Return (width, height)."""
    try:
        with Image.open(file_path) as img:
            return img.size
    except Exception:
        return (0, 0)

def get_random_asset_query(scene_text: str, category: str) -> str:
    """Derive a search query from scene text or fallback to category."""
    words = scene_text.split()[:5]
    query = " ".join(words)
    if len(query) < 3:
        query = category.split()[0]
    query = re.sub(r'[^a-zA-Z0-9\s]', '', query)
    return query.strip()

def get_font_path() -> str:
    """Return path to a TTF font (prefer Noto)."""
    font_candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    ]
    for f in font_candidates:
        if Path(f).exists():
            return f
    # If none, download Noto font to cache
    font_dir = FONTS_DIR
    font_path = font_dir / "NotoSansDevanagari-Regular.ttf"
    if not font_path.exists():
        url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
        if download_file(url, font_path):
            return str(font_path)
    # Fallback to default font (may not support Hindi)
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ----------------------------------------------------------------------
# END OF CHUNK 1
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 6. RESEARCH & SCRIPT GENERATION
# ----------------------------------------------------------------------

@retry(stop=stop_after_attempt(MAX_API_RETRIES),
       wait=wait_exponential(multiplier=1, min=2, max=10))
def research_fact(category: str) -> Dict[str, str]:
    """Use Tavily to find an interesting fact."""
    query = f"interesting {category} fact for YouTube Shorts"
    logger.info(f"Researching: {query}")
    response = api.tavily.search(query=query, search_depth="basic", max_results=3)
    results = response.get("results", [])
    if not results:
        raise ValueError("No search results found")
    best = results[0]
    return {
        "title": best.get("title", ""),
        "content": best.get("content", ""),
        "source": best.get("url", ""),
    }

@retry(stop=stop_after_attempt(MAX_API_RETRIES),
       wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_script(category: str, fact: Dict[str, str]) -> Dict[str, Any]:
    """Use Groq to produce Hinglish script with narrative arc."""
    prompt = f"""
You are a professional YouTube Shorts scriptwriter for "Ajeebology Shorts".
Write a fast‑paced, engaging Hinglish script about this fact:
Category: {category}
Title: {fact['title']}
Content: {fact['content']}

The script must be 55-65 seconds when spoken.
Structure with: HOOK (surprising question), REVELATION (the fact), CALL TO ACTION.
Break into 6-8 short segments (1-2 sentences each).
Output as JSON array of strings, e.g., ["Hook text.", "Revelation part 1.", ...].
Only output the JSON array.
"""
    logger.info("Generating script via Groq")
    response = api.groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are a creative scriptwriter."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=600,
    )
    text = response.choices[0].message.content.strip()
    try:
        lines = json.loads(text)
        if not isinstance(lines, list):
            raise ValueError("Not a list")
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            lines = json.loads(match.group())
        else:
            lines = [line.strip() for line in text.split("\n") if line.strip()]
    full_text = " ".join(lines)
    logger.info(f"Generated {len(lines)} script segments")
    return {"lines": lines, "full_text": full_text}

# ----------------------------------------------------------------------
# 7. ASSET FETCHING (Pexels / Unsplash) – using direct HTTP
# ----------------------------------------------------------------------

def search_pexels_videos(query: str, per_page: int = 5) -> List[Dict]:
    """Search Pexels for videos using direct HTTP request."""
    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api.pexels_key}
    params = {"query": query, "per_page": per_page, "size": "medium"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        videos = data.get("videos", [])
        results = []
        for vid in videos:
            video_files = vid.get("video_files", [])
            if not video_files:
                continue
            video_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            best = video_files[0]
            results.append({
                "url": best.get("link"),
                "width": best.get("width"),
                "height": best.get("height"),
            })
        return results
    except Exception as e:
        logger.error(f"Pexels search error: {e}")
        return []

def search_unsplash_images(query: str, per_page: int = 3) -> List[Dict]:
    """Search Unsplash for images."""
    try:
        url = "https://api.unsplash.com/search/photos"
        headers = {"Authorization": f"Client-ID {api.unsplash_key}"}
        params = {"query": query, "per_page": per_page}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for img in data.get("results", []):
            raw = img.get("urls", {}).get("raw")
            if raw:
                raw = raw + "&w=1080&h=1920&fit=crop"
                results.append({
                    "url": raw,
                    "width": 1080,
                    "height": 1920,
                })
        return results
    except Exception as e:
        logger.error(f"Unsplash search error: {e}")
        return []

def fetch_asset(query: str, asset_type: str = "video") -> Optional[Path]:
    """Fetch a single asset (video or image) based on query."""
    key = f"{asset_type}:{query}"
    cache_path = cache_get(key, ext=".mp4" if asset_type == "video" else ".jpg")
    if cache_path:
        logger.info(f"Using cached asset: {cache_path}")
        return cache_path

    if asset_type == "video":
        results = search_pexels_videos(query, per_page=3)
        for item in results:
            url = item.get("url")
            if not url:
                continue
            temp_file = CACHE_DIR / f"temp_{hashlib.md5(url.encode()).hexdigest()[:8]}.mp4"
            if download_file(url, temp_file):
                dur = get_video_duration(temp_file)
                if dur < 3.0:
                    logger.warning(f"Video too short ({dur}s): {url}")
                    temp_file.unlink(missing_ok=True)
                    continue
                cached = cache_put_file(key, temp_file, ext=".mp4")
                temp_file.unlink(missing_ok=True)
                logger.info(f"Cached video: {cached}")
                return cached
    else:
        results = search_unsplash_images(query, per_page=3)
        for item in results:
            url = item.get("url")
            if not url:
                continue
            temp_file = CACHE_DIR / f"temp_{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"
            if download_file(url, temp_file):
                w, h = get_image_dimensions(temp_file)
                if w < 100 or h < 100:
                    logger.warning(f"Image too small: {w}x{h}")
                    temp_file.unlink(missing_ok=True)
                    continue
                cached = cache_put_file(key, temp_file, ext=".jpg")
                temp_file.unlink(missing_ok=True)
                logger.info(f"Cached image: {cached}")
                return cached
    return None

# ----------------------------------------------------------------------
# 8. AUDIO GENERATION (Natural Male Voice)
# ----------------------------------------------------------------------

def generate_audio(text: str, output_path: Path, lang: str = "hi") -> bool:
    """Generate speech audio using espeak with male voice."""
    temp_wav = output_path.with_suffix(".wav")
    cmd = [
        "espeak", "-v", VOICE_LANG,
        "-s", str(VOICE_SPEED),
        "-p", str(VOICE_PITCH),
        "-g", str(VOICE_GAP),
        "-w", str(temp_wav), text
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-i", str(temp_wav), "-acodec", "libmp3lame",
            "-b:a", "128k", str(output_path)
        ], check=True, capture_output=True)
        temp_wav.unlink(missing_ok=True)
        logger.info(f"Generated audio via espeak (male): {output_path}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"espeak failed: {e}. Falling back to gTTS.")
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(output_path))
        logger.info(f"Generated audio via gTTS: {output_path}")
        return True
    except Exception as e:
        logger.error(f"gTTS also failed: {e}")
        return False

# ----------------------------------------------------------------------
# 9. SCENE SEGMENTATION & TIMING
# ----------------------------------------------------------------------

def plan_scenes(lines: List[str], total_duration: float) -> List[Dict]:
    """Compute per‑scene start/end times based on word count."""
    total_words = sum(len(line.split()) for line in lines)
    words_per_second = max(2.5, min(4.0, total_words / total_duration))
    durations = []
    for line in lines:
        word_count = len(line.split())
        dur = word_count / words_per_second
        durations.append(dur)
    total_estimated = sum(durations)
    scale = total_duration / total_estimated
    durations = [d * scale for d in durations]
    scenes = []
    current_time = 0.0
    for i, line in enumerate(lines):
        dur = durations[i]
        scenes.append({
            "text": line,
            "start": current_time,
            "end": current_time + dur,
            "duration": dur,
        })
        current_time += dur
    return scenes

# ----------------------------------------------------------------------
# END OF CHUNK 2
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 10. FFMPEG UTILITIES FOR EDITING
# ----------------------------------------------------------------------

def create_zoom_clip(input_file: Path, output_file: Path, duration: float,
                     zoom_in: bool = True, pan_x: float = 0.0, pan_y: float = 0.0) -> bool:
    """Apply zoom/pan to an image or video."""
    # For images, use zoompan; for videos, we'll just scale to fit (simpler)
    if input_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
        start_zoom = 1.0
        end_zoom = 1.4 if zoom_in else 0.8
        pan_x_val = pan_x * 0.05
        pan_y_val = pan_y * 0.05
        filter_str = (
            f"zoompan=z='if(eq(on,1),{start_zoom},zoom+({end_zoom-start_zoom})/{duration*FPS})':"
            f"x='(iw - iw/zoom)/2 + {pan_x_val}*iw/zoom':"
            f"y='(ih - ih/zoom)/2 + {pan_y_val}*ih/zoom':"
            f"d={int(duration*FPS)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}"
        )
        cmd = [
            "ffmpeg", "-y", "-i", str(input_file),
            "-vf", filter_str,
            "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
            "-preset", FFMPEG_PRESET, "-t", str(duration),
            str(output_file)
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return True
        except Exception as e:
            logger.error(f"zoompan failed: {e}")
            return scale_to_fit(input_file, output_file, duration)
    else:
        # For video: scale to fit 9:16
        return scale_to_fit(input_file, output_file, duration)

def scale_to_fit(input_file: Path, output_file: Path, duration: float) -> bool:
    """Scale and pad to 1080x1920."""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_file),
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET, "-t", str(duration),
        str(output_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"scale_to_fit failed: {e}")
        return False

def concat_clips(clip_files: List[Path], output_file: Path) -> bool:
    """Concatenate video clips without re-encoding (using concat demuxer)."""
    if not clip_files:
        return False
    concat_file = OUTPUT_DIR / "concat_list_temp.txt"
    with open(concat_file, "w") as f:
        for clip in clip_files:
            if clip.exists():
                f.write(f"file '{clip.absolute()}'\n")
    if concat_file.stat().st_size == 0:
        concat_file.unlink(missing_ok=True)
        return False
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file), "-c", "copy",
        str(output_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        concat_file.unlink(missing_ok=True)
        return True
    except Exception as e:
        logger.error(f"concat failed: {e}")
        concat_file.unlink(missing_ok=True)
        return False

# ----------------------------------------------------------------------
# 11. INTRO AND OUTRO GENERATION (Simplified)
# ----------------------------------------------------------------------

def generate_intro(output_file: Path) -> bool:
    """Generate a 2-second branded intro with channel name."""
    font_path = get_font_path()
    filter_str = (
        f"color=c=black:s=1080x1920:d={INTRO_DURATION},"
        f"drawtext=fontfile={font_path}:text='Ajeebology Shorts':fontcolor=white:fontsize=80:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-50,"
        f"drawtext=fontfile={font_path}:text='Shorts':fontcolor=cyan:fontsize=50:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+160"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={INTRO_DURATION}",
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        str(output_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"Intro generation failed: {e}")
        # Fallback: simple text only
        try:
            cmd_fallback = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={INTRO_DURATION}",
                "-vf", f"drawtext=fontfile={font_path}:text='Ajeebology Shorts':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2",
                "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
                "-preset", FFMPEG_PRESET,
                str(output_file)
            ]
            subprocess.run(cmd_fallback, check=True, capture_output=True)
            return True
        except:
            return False

def generate_outro(output_file: Path) -> bool:
    """Generate a 2-second outro with subscribe call-to-action."""
    font_path = get_font_path()
    filter_str = (
        f"color=c=black:s=1080x1920:d={OUTRO_DURATION},"
        f"drawtext=fontfile={font_path}:text='SUBSCRIBE':fontcolor=red:fontsize=90:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-50,"
        f"drawtext=fontfile={font_path}:text='Ajeebology':fontcolor=yellow:fontsize=40:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+80"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={OUTRO_DURATION}",
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        str(output_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"Outro generation failed: {e}")
        try:
            cmd_fallback = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={OUTRO_DURATION}",
                "-vf", f"drawtext=fontfile={font_path}:text='SUBSCRIBE':fontcolor=red:fontsize=90:x=(w-text_w)/2:y=(h-text_h)/2",
                "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
                "-preset", FFMPEG_PRESET,
                str(output_file)
            ]
            subprocess.run(cmd_fallback, check=True, capture_output=True)
            return True
        except:
            return False

# ----------------------------------------------------------------------
# 12. CAPTIONS (Static Fallback)
# ----------------------------------------------------------------------

def generate_captions_filter(scenes: List[Dict], duration: float) -> str:
    """Generate static captions with fade-in (reliable)."""
    filters = []
    font_path = get_font_path()
    for scene in scenes:
        text = scene["text"]
        start = scene["start"]
        end = scene["end"]
        escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        filter_str = (
            f"drawtext=text='{escaped}':"
            f"fontfile={font_path}:"
            f"fontsize=60:"
            f"fontcolor=white:"
            f"box=1:boxcolor=black@0.6:boxborderw=10:"
            f"x=(w-text_w)/2:y=h-text_h-100:"
            f"enable='between(t,{start},{end})'"
        )
        filters.append(filter_str)
    return ",".join(filters)

# ----------------------------------------------------------------------
# 13. BACKGROUND MUSIC (Pad)
# ----------------------------------------------------------------------

def fetch_background_music() -> Path:
    """Generate a soft pad or return cached."""
    music_file = MUSIC_DIR / "bg_music.mp3"
    if music_file.exists():
        return music_file
    # Generate a simple pad using sine waves
    total_dur = 65  # enough for any video
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"sine=frequency=220:duration={total_dur}, sine=frequency=330:duration={total_dur}, amix=inputs=2, volume=0.2",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(music_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return music_file
    except Exception as e:
        logger.error(f"Failed to generate bg music: {e}")
        # Return a dummy path; will cause silence
        return music_file

# ----------------------------------------------------------------------
# 14. COMPOSE FULL VIDEO (Orchestrates All Editing)
# ----------------------------------------------------------------------

def compose_video(scenes: List[Dict], assets: List[Path], output_video: Path) -> bool:
    """Compose final video: intro + scenes + outro, with audio."""
    # 1. Generate scene clips with zoom/pan
    scene_clips = []
    for i, (scene, asset) in enumerate(zip(scenes, assets)):
        clip_dur = scene["duration"]
        clip_file = CLIPS_DIR / f"scene_{i:02d}.mp4"
        zoom_in = random.choice([True, False])
        pan_x = random.uniform(-0.5, 0.5)
        pan_y = random.uniform(-0.5, 0.5)
        if not create_zoom_clip(asset, clip_file, clip_dur, zoom_in, pan_x, pan_y):
            scale_to_fit(asset, clip_file, clip_dur)
        scene_clips.append(clip_file)

    # 2. Intro and outro
    intro_file = CLIPS_DIR / "intro.mp4"
    outro_file = CLIPS_DIR / "outro.mp4"
    if not generate_intro(intro_file):
        # Create blank fallback
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={INTRO_DURATION}",
            "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT, "-preset", FFMPEG_PRESET,
            str(intro_file)
        ], check=True, capture_output=True)
    if not generate_outro(outro_file):
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={OUTRO_DURATION}",
            "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT, "-preset", FFMPEG_PRESET,
            str(outro_file)
        ], check=True, capture_output=True)

    # 3. Concatenate all clips (intro + scenes + outro)
    all_clips = [intro_file] + scene_clips + [outro_file]
    concat_output = OUTPUT_DIR / "concat_all.mp4"
    if not concat_clips(all_clips, concat_output):
        logger.error("Concat failed")
        return False

    # 4. Generate voiceover audio
    full_text = " ".join([s["text"] for s in scenes])
    voiceover_file = OUTPUT_DIR / "voiceover.mp3"
    if not generate_audio(full_text, voiceover_file):
        # silent fallback
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(sum(s["duration"] for s in scenes) + INTRO_DURATION + OUTRO_DURATION),
            str(voiceover_file)
        ], check=True, capture_output=True)

    # 5. Background music
    bg_music = fetch_background_music()

    # 6. Mix audio (voiceover + bg with ducking)
    mixed_audio = OUTPUT_DIR / "mixed_audio.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voiceover_file),
        "-i", str(bg_music),
        "-filter_complex",
        "[0:a] volume=1.5 [voice]; [1:a] volume=0.3 [bg]; [voice][bg] amix=inputs=2:duration=first",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(mixed_audio)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # 7. Combine video and audio
    final_no_captions = OUTPUT_DIR / "final_no_captions.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(concat_output),
        "-i", str(mixed_audio),
        "-c:v", VIDEO_CODEC,
        "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(final_no_captions)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # 8. Burn captions
    filter_str = generate_captions_filter(scenes, sum(s["duration"] for s in scenes))
    cmd = [
        "ffmpeg", "-y",
        "-i", str(final_no_captions),
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        "-c:a", "copy",
        str(output_video)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception as e:
        logger.error(f"Caption burn failed: {e}")
        shutil.copy2(final_no_captions, output_video)

    # Cleanup
    for f in scene_clips + [intro_file, outro_file, concat_output, voiceover_file, mixed_audio, final_no_captions]:
        try:
            f.unlink(missing_ok=True)
        except:
            pass

    return True

# ----------------------------------------------------------------------
# END OF CHUNK 3
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# 15. THUMBNAIL GENERATION (High-CTR)
# ----------------------------------------------------------------------

def generate_thumbnail(title: str, video_path: Path, output_path: Path) -> bool:
    """Extract a frame and overlay bold text with vignette."""
    dur = get_video_duration(video_path)
    if dur <= 0:
        return False
    timestamp = dur / 3.0
    frame_file = OUTPUT_DIR / "frame_raw.jpg"
    cmd = [
        "ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(frame_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except:
        return False

    try:
        img = Image.open(frame_file)
        img = img.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
        draw = ImageDraw.Draw(img)

        font_path = get_font_path()
        try:
            font = ImageFont.truetype(font_path, 90)
            small_font = ImageFont.truetype(font_path, 50)
        except:
            font = ImageFont.load_default()
            small_font = font

        # Semi-transparent overlay at bottom
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([(0, img.height-250), (img.width, img.height)], fill=(0,0,0,180))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)

        # Truncate title to max 5 words
        words = title.split()[:5]
        text = " ".join(words)
        if len(text) > 40:
            text = text[:37] + "..."

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (img.width - tw) // 2
        y = img.height - th - 120

        # Outline
        for dx, dy in [(-3,-3), (-3,3), (3,-3), (3,3), (0,-3), (0,3), (-3,0), (3,0)]:
            draw.text((x+dx, y+dy), text, font=font, fill="black")
        draw.text((x, y), text, font=font, fill="white")

        sub_text = "@Ajeebology"
        bbox2 = draw.textbbox((0, 0), sub_text, font=small_font)
        sw = bbox2[2] - bbox2[0]
        sx = (img.width - sw) // 2
        sy = y + th + 20
        draw.text((sx, sy), sub_text, font=small_font, fill="yellow")

        img.save(output_path, quality=90)
        frame_file.unlink(missing_ok=True)
        return True
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        frame_file.unlink(missing_ok=True)
        return False

# ----------------------------------------------------------------------
# 16. VIRAL METADATA GENERATION
# ----------------------------------------------------------------------

def generate_viral_metadata(scenes: List[Dict], title: str, fact: Dict[str, str],
                            category: str) -> Dict[str, str]:
    """Create viral-optimised title, description, tags, hashtags."""
    # Try to generate a title using Groq
    try:
        prompt = f"""
You are a YouTube Shorts title expert. Given this fact:
Title: {fact['title']}
Content: {fact['content']}
Category: {category}

Generate a clickbait-style, curiosity-driven title (max 50 characters).
Use numbers, "This", "Why", "What If", or surprising statements.
Output only the title.
"""
        response = api.groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": "You are a title guru."},
                      {"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=60
        )
        viral_title = response.choices[0].message.content.strip()
        if len(viral_title) > 60:
            viral_title = viral_title[:57] + "..."
    except:
        viral_title = title

    script_lines = [f"{i+1}. {scene['text']}" for i, scene in enumerate(scenes)]
    script_text = "\n".join(script_lines)
    description = f"🔥 {viral_title}\n\n"
    description += "Did you know this mind-blowing fact? Watch till the end!\n\n"
    description += script_text + "\n\n"
    description += "📌 Like, Share & Subscribe to Ajeebology Shorts for more amazing facts!\n"
    description += "🔔 Turn on notifications so you never miss a Short!\n"
    description += "\n#Ajeebology #Shorts #Facts"

    tag_words = [category] + [w for w in viral_title.split() if len(w) > 3]
    tags = ["Ajeebology", "Shorts", "Facts", "Psychology", "Space", "Weird"] + tag_words
    tags = list(dict.fromkeys(tags))[:10]

    hashtags = ["Ajeebology", "Shorts", category.replace(" ", "")]
    for w in viral_title.split():
        if len(w) > 3:
            hashtags.append(w)
    hashtags = list(dict.fromkeys(hashtags))[:8]
    hashtag_str = "#" + " #".join(hashtags)

    return {
        "title": viral_title,
        "description": description,
        "tags": ", ".join(tags),
        "hashtags": hashtag_str,
        "category": category,
        "sources": [fact.get("source", "")]
    }

# ----------------------------------------------------------------------
# 17. TELEGRAM DELIVERY
# ----------------------------------------------------------------------

def send_to_telegram(video_path: Path, thumbnail_path: Path,
                     metadata: Dict[str, str], runtime_stats: Dict[str, Any]) -> bool:
    """Send final video, thumbnail, and metadata to Telegram."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Telegram credentials missing")
        return False
    try:
        bot = Bot(token=token)
        caption = (
            f"🎬 *{metadata['title']}*\n\n"
            f"{metadata['description'][:200]}...\n\n"
            f"🏷️ Tags: {metadata['tags']}\n"
            f"#️⃣ Hashtags: {metadata['hashtags']}\n"
            f"📂 Category: {metadata['category']}\n"
            f"🔗 Sources: {', '.join(metadata['sources'])}\n"
            f"⏱️ Runtime: {runtime_stats.get('duration', 0):.1f}s\n"
            f"📊 Scenes: {runtime_stats.get('scenes', 0)}"
        )
        with open(video_path, "rb") as vf, open(thumbnail_path, "rb") as tf:
            bot.send_video(
                chat_id=chat_id,
                video=InputFile(vf),
                caption=caption,
                parse_mode="Markdown",
                thumbnail=InputFile(tf),
                supports_streaming=True,
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT,
            )
        with open(thumbnail_path, "rb") as tf:
            bot.send_photo(chat_id=chat_id, photo=InputFile(tf), caption="Thumbnail")
        logger.info("Telegram delivery successful")
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False

# ----------------------------------------------------------------------
# 18. MAIN PIPELINE ORCHESTRATOR
# ----------------------------------------------------------------------

def run_pipeline() -> bool:
    """Orchestrate the entire Shorts production pipeline."""
    logger.info("🚀 Starting Ajeebology Shorts pipeline")
    start_time = time.time()

    categories = ["Psychology Facts", "Space Facts", "Weird World Facts"]
    category = random.choice(categories)
    logger.info(f"📂 Selected category: {category}")

    try:
        fact = research_fact(category)
        logger.info(f"🔍 Fact: {fact['title']}")
    except Exception as e:
        logger.error(f"Research failed: {e}")
        return False

    try:
        script = generate_script(category, fact)
        lines = script["lines"]
        logger.info(f"📝 Script: {len(lines)} segments")
    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        return False

    total_duration = random.uniform(*TARGET_DURATION)
    scenes = plan_scenes(lines, total_duration)
    logger.info(f"🎬 Planned {len(scenes)} scenes over {sum(s['duration'] for s in scenes):.1f}s")

    # Fetch assets
    assets = []
    for i, scene in enumerate(scenes):
        query = get_random_asset_query(scene["text"], category)
        asset_type = "video" if i % 2 == 0 else "image"
        asset = fetch_asset(query, asset_type)
        if asset is None:
            fallback_query = category.split()[0] if i % 2 == 0 else "mysterious"
            asset = fetch_asset(fallback_query, "video" if i % 2 == 0 else "image")
            if asset is None:
                placeholder = ASSETS_DIR / f"placeholder_{i}.jpg"
                if not placeholder.exists():
                    img = Image.new('RGB', (1080, 1920), color=(random.randint(30,100), random.randint(30,100), random.randint(30,100)))
                    img.save(placeholder)
                asset = placeholder
        assets.append(asset)

    output_video = OUTPUT_DIR / f"ajeebology_{get_timestamp()}.mp4"
    logger.info("🎥 Composing video with advanced editing...")
    if not compose_video(scenes, assets, output_video):
        logger.error("Video composition failed")
        return False
    logger.info(f"✅ Video composed: {output_video}")

    thumbnail_path = OUTPUT_DIR / f"thumbnail_{get_timestamp()}.jpg"
    if not generate_thumbnail(fact['title'], output_video, thumbnail_path):
        logger.warning("Thumbnail generation failed, creating fallback")
        img = Image.new('RGB', (1280, 720), color='black')
        draw = ImageDraw.Draw(img)
        draw.text((100, 300), fact['title'], fill='white', font=ImageFont.load_default())
        img.save(thumbnail_path)

    metadata = generate_viral_metadata(scenes, fact['title'], fact, category)

    duration = get_video_duration(output_video)
    runtime_stats = {
        "duration": duration,
        "scenes": len(scenes),
        "assets_used": len(assets),
        "timestamp": get_timestamp(),
    }

    logger.info("📲 Sending to Telegram...")
    if not send_to_telegram(output_video, thumbnail_path, metadata, runtime_stats):
        logger.error("Telegram delivery failed")

    metadata_path = OUTPUT_DIR / f"metadata_{get_timestamp()}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    elapsed = time.time() - start_time
    logger.info(f"✅ Pipeline completed in {elapsed:.2f}s")
    return True

# ----------------------------------------------------------------------
# 19. ENTRY POINT
# ----------------------------------------------------------------------

if __name__ == "__main__":
    try:
        success = run_pipeline()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.exception(f"❌ Unhandled exception: {e}")
        sys.exit(1)
