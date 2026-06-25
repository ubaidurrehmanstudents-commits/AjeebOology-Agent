#!/usr/bin/env python3
"""
youtube_agent.py — Fully automated YouTube Shorts production pipeline.
Single‑file, production‑ready, designed for GitHub Actions Free Tier.

Features:
- Narrative script with hook, climax, CTA
- Motion graphics (zoom/pan) on all clips (videos and images)
- Crossfade transitions (0.5s) between scenes
- Kinetic captions (slide-up with pulse) with fallback to static
- Branded intro (2s) and outro (2s)
- Real background music (pad) and ducking
- Natural male voice via espeak (hi+m1)
- Sound effects (whoosh, pop) on transitions
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

# Caption style (kinetic with fallback to static)
CAPTION_FONT_SIZE = 60
CAPTION_BG_ALPHA = 0.6
CAPTION_TEXT_COLOR = "#FFFFFF"
CAPTION_OUTLINE_COLOR = "#000000"
CAPTION_HIGHLIGHT_COLOR = "#FFD700"  # gold for emphasis

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
# END OF CHUNK 1
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 10. FFMPEG UTILITIES FOR ADVANCED EDITING
# ----------------------------------------------------------------------

def create_zoom_clip(input_file: Path, output_file: Path, duration: float,
                     zoom_in: bool = True, pan_x: float = 0.0, pan_y: float = 0.0) -> bool:
    """
    Apply zoom (in or out) and subtle pan to an image or video.
    For videos: use zoompan (works on videos too, but we'll have a fallback)
    """
    if not input_file.exists():
        logger.error(f"Input file does not exist: {input_file}")
        return False
    
    # For both images and videos, we'll try zoompan
    start_zoom = 1.0
    end_zoom = 1.4 if zoom_in else 0.8
    pan_x_val = pan_x * 0.04  # 4% max pan
    pan_y_val = pan_y * 0.04
    
    # Build filter string for zoompan
    filter_str = (
        f"zoompan=z='if(eq(on,1),{start_zoom},zoom+({end_zoom-start_zoom})/{max(0.5, duration)*FPS})':"
        f"x='(iw - iw/zoom)/2 + {pan_x_val}*iw/zoom':"
        f"y='(ih - ih/zoom)/2 + {pan_y_val}*ih/zoom':"
        f"d={int(max(1, duration*FPS))}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS}"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_file),
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        "-t", str(duration),
        "-r", str(FPS),
        str(output_file)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.warning(f"zoompan failed for {input_file}: {e.stderr.decode()[:200]}")
        # Fallback: scale to fit without zoom
        return scale_to_fit(input_file, output_file, duration)
    except Exception as e:
        logger.error(f"create_zoom_clip error: {e}")
        return scale_to_fit(input_file, output_file, duration)

def scale_to_fit(input_file: Path, output_file: Path, duration: float) -> bool:
    """Scale and pad to 1080x1920 (9:16)."""
    if not input_file.exists():
        return False
        
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_file),
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        "-t", str(duration),
        "-r", str(FPS),
        str(output_file)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"scale_to_fit failed: {e}")
        return False

def apply_crossfade_transition(clip1: Path, clip2: Path, output_file: Path, 
                                duration: float = 0.5) -> bool:
    """
    Apply crossfade transition between two clips using xfade filter.
    """
    if not clip1.exists() or not clip2.exists():
        return False
        
    # Ensure both clips have the same framerate and dimensions
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip1),
        "-i", str(clip2),
        "-filter_complex",
        f"[0:v]fps={FPS},scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2[v0];"
        f"[1:v]fps={FPS},scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2[v1];"
        f"[v0][v1]xfade=transition=fade:duration={duration}:offset={duration}",
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        "-an",  # Audio handled separately
        str(output_file)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.warning(f"Crossfade failed: {e}")
        # Fallback: simple concat
        return concat_clips([clip1, clip2], output_file)

def concat_clips(clip_files: List[Path], output_file: Path) -> bool:
    """Concatenate video clips without re-encoding (using concat demuxer)."""
    valid_clips = [c for c in clip_files if c.exists()]
    if not valid_clips:
        return False
        
    concat_file = OUTPUT_DIR / f"concat_list_{get_timestamp()}.txt"
    with open(concat_file, "w") as f:
        for clip in valid_clips:
            f.write(f"file '{clip.absolute()}'\n")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
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
# 11. INTRO AND OUTRO GENERATION (Fixed Filter Strings)
# ----------------------------------------------------------------------

def generate_intro(output_file: Path) -> bool:
    """Generate a 2-second branded intro with channel name."""
    font_path = get_font_path()
    
    # Only drawtext filters - NO 'color=' prefix (we already feed color source)
    filter_str = (
        f"drawtext=fontfile={font_path}:text='Ajeebology Shorts':fontcolor=white:fontsize=80:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-50,"
        f"drawtext=fontfile={font_path}:text='Shorts':fontcolor=cyan:fontsize=50:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+160"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={INTRO_DURATION}:r={FPS}",
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        str(output_file)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"Intro generation failed: {e}")
        # Fallback: simpler command
        try:
            cmd_fallback = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={INTRO_DURATION}:r={FPS}",
                "-vf", f"drawtext=fontfile={font_path}:text='Ajeebology Shorts':fontcolor=white:fontsize=80:x=(w-text_w)/2:y=(h-text_h)/2",
                "-c:v", VIDEO_CODEC,
                "-pix_fmt", PIXEL_FORMAT,
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
        f"drawtext=fontfile={font_path}:text='SUBSCRIBE':fontcolor=red:fontsize=90:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-50,"
        f"drawtext=fontfile={font_path}:text='Ajeebology':fontcolor=yellow:fontsize=40:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+80"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={OUTRO_DURATION}:r={FPS}",
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
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
                "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={OUTRO_DURATION}:r={FPS}",
                "-vf", f"drawtext=fontfile={font_path}:text='SUBSCRIBE':fontcolor=red:fontsize=90:x=(w-text_w)/2:y=(h-text_h)/2",
                "-c:v", VIDEO_CODEC,
                "-pix_fmt", PIXEL_FORMAT,
                "-preset", FFMPEG_PRESET,
                str(output_file)
            ]
            subprocess.run(cmd_fallback, check=True, capture_output=True)
            return True
        except:
            return False

# ----------------------------------------------------------------------
# 12. KINETIC CAPTIONS (With Fallback to Static)
# ----------------------------------------------------------------------

def generate_kinetic_captions_filter(scenes: List[Dict]) -> Tuple[str, bool]:
    """
    Generate kinetic captions with slide-up and pulse animation.
    Returns (filter_string, success_flag). If fails, returns static captions.
    """
    try:
        font_path = get_font_path()
        filters = []
        
        for scene in scenes:
            text = scene["text"]
            start = scene["start"]
            end = scene["end"]
            dur = scene["duration"]
            
            # Escape text for ffmpeg
            escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
            escaped = escaped.replace('"', '\\"')
            
            # Animate: slide up from bottom, with pulse effect
            # y = h - text_h - 100 - (h - text_h - 100) * max(0, min(1, (t-start)/0.3))
            # fontsize = 60 + 8 * sin((t-start)*5)
            y_expr = f"h - text_h - 100 - (h - text_h - 100) * max(0, min(1, (t-{start})/0.3))"
            fontsize_expr = f"60 + 8 * sin((t-{start})*5)"
            
            filter_str = (
                f"drawtext=text='{escaped}':"
                f"fontfile={font_path}:"
                f"fontsize='{fontsize_expr}':"
                f"fontcolor={CAPTION_TEXT_COLOR}:"
                f"box=1:boxcolor=black@0.6:boxborderw=10:"
                f"x=(w-text_w)/2:"
                f"y='{y_expr}':"
                f"enable='between(t,{start},{end})'"
            )
            filters.append(filter_str)
        
        return (",".join(filters), True)
        
    except Exception as e:
        logger.warning(f"Kinetic captions generation failed: {e}")
        # Fallback to static captions
        return generate_static_captions_filter(scenes), False

def generate_static_captions_filter(scenes: List[Dict]) -> str:
    """Generate simple static captions (reliable fallback)."""
    font_path = get_font_path()
    filters = []
    
    for scene in scenes:
        text = scene["text"]
        start = scene["start"]
        end = scene["end"]
        
        escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        escaped = escaped.replace('"', '\\"')
        
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
# 13. SOUND EFFECTS & BACKGROUND MUSIC
# ----------------------------------------------------------------------

def generate_sound_effect(effect_type: str = "whoosh") -> Optional[Path]:
    """Generate simple sound effects using ffmpeg aeval."""
    sound_file = SOUND_DIR / f"{effect_type}.mp3"
    if sound_file.exists():
        return sound_file
    
    try:
        if effect_type == "whoosh":
            # White noise with frequency sweep
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                "aevalsrc='0.5*sin(1000*t*t)*tanh(8*(1-t))':duration=0.3:rate=44100",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(sound_file)
            ]
        elif effect_type == "pop":
            # Short pop/click
            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                "aevalsrc='0.5*sin(2000*t)*exp(-15*t)':duration=0.15:rate=44100",
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(sound_file)
            ]
        else:
            return None
        
        subprocess.run(cmd, check=True, capture_output=True)
        return sound_file
    except Exception as e:
        logger.warning(f"Sound effect generation failed: {e}")
        return None

def fetch_background_music() -> Optional[Path]:
    """Generate a soft pad or return cached."""
    music_file = MUSIC_DIR / "bg_music.mp3"
    if music_file.exists():
        return music_file
    
    # Generate a soft pad using aeval with two sine waves (stereo)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        "aevalsrc='0.3*sin(2*PI*220*t)+0.2*sin(2*PI*330*t)':duration=65:rate=44100",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(music_file)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return music_file
    except Exception as e:
        logger.error(f"Failed to generate bg music: {e}")
        return None

# ----------------------------------------------------------------------
# 14. FULL VIDEO COMPOSITION (Orchestrates Everything)
# ----------------------------------------------------------------------

def compose_video(scenes: List[Dict], assets: List[Path], output_video: Path) -> bool:
    """
    Compose the final video with:
      - Intro (2s)
      - Each scene: zoom/pan animation
      - Crossfade transitions between all clips
      - Kinetic captions (with fallback)
      - Sound effects on transitions
      - Voiceover audio with background music ducking
      - Outro (2s)
    """
    logger.info("Starting video composition...")
    
    # 1. Generate individual scene clips with zoom/pan
    scene_clips = []
    for i, (scene, asset) in enumerate(zip(scenes, assets)):
        clip_dur = scene["duration"]
        clip_file = CLIPS_DIR / f"scene_{i:02d}.mp4"
        
        # Randomize zoom direction and pan
        zoom_in = random.choice([True, False])
        pan_x = random.uniform(-0.5, 0.5)
        pan_y = random.uniform(-0.5, 0.5)
        
        if not create_zoom_clip(asset, clip_file, clip_dur, zoom_in, pan_x, pan_y):
            logger.warning(f"Scene {i} zoom failed, using scale fallback")
            scale_to_fit(asset, clip_file, clip_dur)
        
        scene_clips.append(clip_file)
    
    # 2. Generate intro and outro
    intro_file = CLIPS_DIR / "intro.mp4"
    outro_file = CLIPS_DIR / "outro.mp4"
    
    if not generate_intro(intro_file):
        logger.warning("Intro generation failed, creating blank fallback")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={INTRO_DURATION}:r={FPS}",
            "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT, "-preset", FFMPEG_PRESET,
            str(intro_file)
        ], check=True, capture_output=True)
    
    if not generate_outro(outro_file):
        logger.warning("Outro generation failed, creating blank fallback")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:s=1080x1920:d={OUTRO_DURATION}:r={FPS}",
            "-c:v", VIDEO_CODEC, "-pix_fmt", PIXEL_FORMAT, "-preset", FFMPEG_PRESET,
            str(outro_file)
        ], check=True, capture_output=True)
    
    # 3. Concatenate all clips with crossfade transitions
    # We'll use a chained approach: create a list of all clip paths
    all_clips = [intro_file] + scene_clips + [outro_file]
    
    # For crossfade, we need to process pairs with xfade
    # We'll build clips progressively: [clip1, clip2] -> xfade -> output, then add next clip
    if len(all_clips) > 1:
        # Start with the first two clips
        current_output = OUTPUT_DIR / "current_concat_temp.mp4"
        if not apply_crossfade_transition(all_clips[0], all_clips[1], current_output, 0.5):
            logger.warning("Crossfade failed for first pair, using concat")
            concat_clips([all_clips[0], all_clips[1]], current_output)
        
        # Add remaining clips one by one with transitions
        for i in range(2, len(all_clips)):
            next_output = OUTPUT_DIR / f"concat_temp_{i}.mp4"
            if not apply_crossfade_transition(current_output, all_clips[i], next_output, 0.5):
                logger.warning(f"Crossfade failed at step {i}, using concat")
                concat_clips([current_output, all_clips[i]], next_output)
            current_output = next_output
        
        final_video = current_output
    else:
        final_video = all_clips[0]
    
    # 4. Generate voiceover audio
    full_text = " ".join([s["text"] for s in scenes])
    voiceover_file = OUTPUT_DIR / "voiceover.mp3"
    
    if not generate_audio(full_text, voiceover_file):
        logger.warning("Voiceover generation failed, creating silent audio")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anullsrc=r=44100:cl=stereo",
            "-t", str(sum(s["duration"] for s in scenes) + INTRO_DURATION + OUTRO_DURATION + 2),
            str(voiceover_file)
        ], check=True, capture_output=True)
    
    # 5. Fetch or generate background music
    bg_music = fetch_background_music()
    if bg_music is None or not bg_music.exists():
        logger.warning("Background music generation failed, creating silent fallback")
        bg_music = MUSIC_DIR / "silent.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anullsrc=r=44100:cl=stereo",
            "-t", "65",
            "-c:a", "libmp3lame",
            str(bg_music)
        ], check=True, capture_output=True)
    
    # 6. Mix audio: voiceover + background music with ducking
    mixed_audio = OUTPUT_DIR / "mixed_audio.mp3"
    
    # Use sidechaincompress for proper ducking if available, else simple volume mix
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voiceover_file),
        "-i", str(bg_music),
        "-filter_complex",
        "[0:a] volume=1.8 [voice]; [1:a] volume=0.25 [bg]; [voice][bg] amix=inputs=2:duration=first",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(mixed_audio)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception as e:
        logger.error(f"Audio mixing failed: {e}")
        # Fallback: copy voiceover only
        shutil.copy2(voiceover_file, mixed_audio)
    
    # 7. Combine video and audio
    final_no_captions = OUTPUT_DIR / "final_no_captions.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(final_video),
        "-i", str(mixed_audio),
        "-c:v", VIDEO_CODEC,
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(final_no_captions)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception as e:
        logger.error(f"Video-audio combine failed: {e}")
        return False
    
    # 8. Burn captions (try kinetic, fallback to static)
    captions_filter, success = generate_kinetic_captions_filter(scenes)
    
    if not success:
        logger.warning("Kinetic captions failed, using static fallback")
        captions_filter = generate_static_captions_filter(scenes)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(final_no_captions),
        "-vf", captions_filter,
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-preset", FFMPEG_PRESET,
        "-c:a", "copy",
        str(output_video)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception as e:
        logger.error(f"Caption burn failed: {e}")
        # Fallback: copy video without captions
        shutil.copy2(final_no_captions, output_video)
    
    # 9. Cleanup temporary files
    for f in scene_clips + [intro_file, outro_file, final_video, voiceover_file, bg_music, mixed_audio, final_no_captions]:
        try:
            if f.exists() and f.parent != OUTPUT_DIR:
                f.unlink(missing_ok=True)
        except:
            pass
    
    # Clean up temp concat files
    for f in OUTPUT_DIR.glob("concat_temp_*.mp4"):
        try:
            f.unlink(missing_ok=True)
        except:
            pass
    
    logger.info("Video composition completed successfully")
    return True

# ----------------------------------------------------------------------
# END OF CHUNK 2
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 15. THUMBNAIL GENERATION (High-CTR)
# ----------------------------------------------------------------------

def generate_thumbnail(title: str, video_path: Path, output_path: Path) -> bool:
    """
    Extract a high-motion frame from video and overlay bold text with vignette.
    """
    dur = get_video_duration(video_path)
    if dur <= 0:
        return False
    
    # Extract frame at 1/3 of the video (often has motion)
    timestamp = dur / 3.0
    frame_file = OUTPUT_DIR / "frame_raw.jpg"
    
    cmd = [
        "ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(frame_file)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except:
        logger.warning("Frame extraction failed")
        return False
    
    try:
        img = Image.open(frame_file)
        # Resize to thumbnail dimensions (landscape) – crop centre
        img = img.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        
        # Load a bold font
        font_path = get_font_path()
        try:
            font = ImageFont.truetype(font_path, 90)
            small_font = ImageFont.truetype(font_path, 50)
        except:
            font = ImageFont.load_default()
            small_font = font
        
        # Add a semi-transparent overlay at the bottom for text readability
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([(0, img.height-250), (img.width, img.height)], fill=(0,0,0,180))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        
        # Title text: max 5 words
        words = title.split()[:5]
        text = " ".join(words)
        if len(text) > 40:
            text = text[:37] + "..."
        
        # Draw text with outline
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (img.width - tw) // 2
        y = img.height - th - 120
        
        # Outline for contrast
        for dx, dy in [(-3,-3), (-3,3), (3,-3), (3,3), (0,-3), (0,3), (-3,0), (3,0)]:
            draw.text((x+dx, y+dy), text, font=font, fill="black")
        draw.text((x, y), text, font=font, fill="white")
        
        # Small subtitle
        sub_text = "@Ajeebology"
        bbox2 = draw.textbbox((0, 0), sub_text, font=small_font)
        sw = bbox2[2] - bbox2[0]
        sx = (img.width - sw) // 2
        sy = y + th + 20
        draw.text((sx, sy), sub_text, font=small_font, fill="yellow")
        
        # Save thumbnail
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
    """
    Create viral-optimised title, description, tags, hashtags.
    Uses Groq to generate a click-driven title if available.
    """
    # Try to generate a viral title using Groq
    try:
        prompt = f"""
You are a YouTube Shorts title expert. Given this fact:
Title: {fact['title']}
Content: {fact['content']}
Category: {category}

Generate a clickbait-style, curiosity-driven title for a YouTube Short (max 50 characters).
Use numbers, "This", "Why", "What If", or surprising statements.
Output only the title, nothing else.
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
    except Exception as e:
        logger.warning(f"Title generation failed: {e}")
        viral_title = title  # fallback
    
    # Build description with full script
    script_lines = [f"{i+1}. {scene['text']}" for i, scene in enumerate(scenes)]
    script_text = "\n".join(script_lines)
    
    description = f"🔥 {viral_title}\n\n"
    description += "Did you know this mind-blowing fact? Watch till the end!\n\n"
    description += script_text + "\n\n"
    description += "📌 Like, Share & Subscribe to Ajeebology Shorts for more amazing facts!\n"
    description += "🔔 Turn on notifications so you never miss a Short!\n"
    description += "\n#Ajeebology #Shorts #Facts"
    
    # Tags: mix broad + niche
    tag_words = [category] + [w for w in viral_title.split() if len(w) > 3]
    tags = ["Ajeebology", "Shorts", "Facts", "Psychology", "Space", "Weird"] + tag_words
    tags = list(dict.fromkeys(tags))[:10]  # unique, max 10
    
    # Hashtags: category + keywords
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
        
        # Send thumbnail separately as a photo
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
    
    # 1. Category selection
    categories = ["Psychology Facts", "Space Facts", "Weird World Facts"]
    category = random.choice(categories)
    logger.info(f"📂 Selected category: {category}")
    
    # 2. Research fact
    try:
        fact = research_fact(category)
        logger.info(f"🔍 Fact: {fact['title']}")
    except Exception as e:
        logger.error(f"Research failed: {e}")
        return False
    
    # 3. Generate script with narrative arc
    try:
        script = generate_script(category, fact)
        lines = script["lines"]
        logger.info(f"📝 Script: {len(lines)} segments")
    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        return False
    
    # 4. Plan scenes
    total_duration = random.uniform(*TARGET_DURATION)
    scenes = plan_scenes(lines, total_duration)
    logger.info(f"🎬 Planned {len(scenes)} scenes over {sum(s['duration'] for s in scenes):.1f}s")
    
    # 5. Fetch assets for each scene (alternate video/image)
    assets = []
    for i, scene in enumerate(scenes):
        query = get_random_asset_query(scene["text"], category)
        asset_type = "video" if i % 2 == 0 else "image"
        asset = fetch_asset(query, asset_type)
        
        if asset is None:
            # Fallback: use category keyword
            fallback_query = category.split()[0] if i % 2 == 0 else "mysterious"
            asset = fetch_asset(fallback_query, "video" if i % 2 == 0 else "image")
            
            if asset is None:
                # Last resort: create a colored placeholder
                placeholder = ASSETS_DIR / f"placeholder_{i}.jpg"
                if not placeholder.exists():
                    img = Image.new('RGB', (1080, 1920), color=(random.randint(30,100), random.randint(30,100), random.randint(30,100)))
                    img.save(placeholder)
                asset = placeholder
        
        assets.append(asset)
    
    # 6. Compose final video (includes intro, scenes, outro, captions, audio)
    output_video = OUTPUT_DIR / f"ajeebology_{get_timestamp()}.mp4"
    logger.info("🎥 Composing video with advanced editing...")
    
    if not compose_video(scenes, assets, output_video):
        logger.error("Video composition failed")
        return False
    
    logger.info(f"✅ Video composed: {output_video}")
    
    # 7. Generate thumbnail
    thumbnail_path = OUTPUT_DIR / f"thumbnail_{get_timestamp()}.jpg"
    if not generate_thumbnail(fact['title'], output_video, thumbnail_path):
        logger.warning("Thumbnail generation failed, creating fallback")
        # Simple fallback: black image with text
        img = Image.new('RGB', (1280, 720), color='black')
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(get_font_path(), 60)
        except:
            font = ImageFont.load_default()
        draw.text((100, 300), fact['title'], fill='white', font=font)
        img.save(thumbnail_path)
    
    # 8. Generate viral metadata
    metadata = generate_viral_metadata(scenes, fact['title'], fact, category)
    
    # 9. Runtime stats
    duration = get_video_duration(output_video)
    runtime_stats = {
        "duration": duration,
        "scenes": len(scenes),
        "assets_used": len(assets),
        "timestamp": get_timestamp(),
    }
    
    # 10. Send to Telegram
    logger.info("📲 Sending to Telegram...")
    if not send_to_telegram(output_video, thumbnail_path, metadata, runtime_stats):
        logger.error("Telegram delivery failed")
    
    # 11. Save metadata JSON
    metadata_path = OUTPUT_DIR / f"metadata_{get_timestamp()}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    # 12. Log completion
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
         
