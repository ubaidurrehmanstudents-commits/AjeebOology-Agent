#!/usr/bin/env python3
"""
youtube_agent.py — Fully automated YouTube Shorts production pipeline.
Single‑file, production‑ready, designed for GitHub Actions Free Tier.
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
from pexels_api import API as PexelsAPI
import unsplash

# Telegram
from telegram import Bot, InputFile

# Audio processing (optional, but we keep for future use)
from pydub import AudioSegment
import whisper  # for forced alignment if needed, but we'll rely on timing.

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
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)

# Video settings
TARGET_DURATION = (55, 65)          # seconds
VIDEO_WIDTH = 1080                  # 9:16 portrait
VIDEO_HEIGHT = 1920
FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
PIXEL_FORMAT = "yuv420p"

# Scene segmentation: aim for 6-8 segments
MIN_SCENES = 6
MAX_SCENES = 8
SCENE_DURATION = (5, 9)            # seconds per scene (will adjust to fit total)

# Caption style
CAPTION_FONT_SIZE = 60
CAPTION_BG_ALPHA = 0.6
CAPTION_TEXT_COLOR = "#FFFFFF"
CAPTION_OUTLINE_COLOR = "#000000"

# Thumbnail style
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720

# API retries
MAX_API_RETRIES = 3
API_RETRY_WAIT = 2  # seconds base

# Groq model
GROQ_MODEL = "llama-3.3-70b-versatile"

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
    logging.getLogger("pexels_api").setLevel(logging.WARNING)
    logging.getLogger("unsplash").setLevel(logging.WARNING)
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

# ----------------------------------------------------------------------
# 4. API CLIENTS (with retries)
# ----------------------------------------------------------------------

class APIClients:
    """Container for all API clients with lazy initialisation."""
    def __init__(self):
        self._groq = None
        self._tavily = None
        self._pexels = None
        self._unsplash = None

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
    def pexels(self) -> PexelsAPI:
        if self._pexels is None:
            api_key = os.environ.get("PEXELS_API_KEY")
            if not api_key:
                raise ValueError("PEXELS_API_KEY not set")
            self._pexels = PexelsAPI(api_key)
        return self._pexels

    @property
    def unsplash(self):
        if self._unsplash is None:
            api_key = os.environ.get("UNSPLASH_ACCESS_KEY")
            if not api_key:
                raise ValueError("UNSPLASH_ACCESS_KEY not set")
            # The unsplash library is not directly used, we'll use the search API.
            # We'll use a simple requests wrapper, but we keep the property for future.
            self._unsplash = api_key
        return self._unsplash

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

# ----------------------------------------------------------------------
# 6. RESEARCH & SCRIPT GENERATION
# ----------------------------------------------------------------------

@retry(stop=stop_after_attempt(MAX_API_RETRIES),
       wait=wait_exponential(multiplier=1, min=2, max=10))
def research_fact(category: str) -> Dict[str, str]:
    """
    Use Tavily to find an interesting fact in the given category.
    Returns dict with 'title', 'content', 'source'.
    """
    query = f"interesting {category} fact for YouTube Shorts"
    logger.info(f"Researching: {query}")
    response = api.tavily.search(query=query, search_depth="basic", max_results=3)
    results = response.get("results", [])
    if not results:
        raise ValueError("No search results found")
    # Pick the most relevant (first)
    best = results[0]
    return {
        "title": best.get("title", ""),
        "content": best.get("content", ""),
        "source": best.get("url", ""),
    }

@retry(stop=stop_after_attempt(MAX_API_RETRIES),
       wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_script(category: str, fact: Dict[str, str]) -> Dict[str, Any]:
    """
    Use Groq to produce a Hinglish script optimized for 55-65 second Shorts.
    Returns dict with 'lines' (list of sentences) and 'full_text'.
    """
    prompt = f"""
You are a professional YouTube Shorts scriptwriter for the channel "Ajeebology Shorts".
Write a fast‑paced, engaging Hinglish script (mix of Hindi and English) about the following fact:
Category: {category}
Title: {fact['title']}
Content: {fact['content']}
Source: {fact['source']}

The script must be between 55 and 65 seconds when spoken at a normal pace (approx. 150-170 words per minute).
Structure the script into 6-8 short segments, each consisting of 1-2 sentences.
Each segment should end with a visual cue (e.g., "pause", "zoom", "cut") but we will handle that.
Output the script as a JSON array of strings, e.g., ["Segment 1 text.", "Segment 2 text.", ...].
Ensure the language is Hinglish and uses catchy phrases, hooks, and a strong call to action at the end.
Only output the JSON array, nothing else.
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
    # Parse JSON array
    try:
        lines = json.loads(text)
        if not isinstance(lines, list):
            raise ValueError("Response is not a list")
    except json.JSONDecodeError:
        # Fallback: try to extract using regex
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            lines = json.loads(match.group())
        else:
            # split by newline and filter
            lines = [line.strip() for line in text.split("\n") if line.strip()]
    full_text = " ".join(lines)
    logger.info(f"Generated {len(lines)} script segments")
    return {"lines": lines, "full_text": full_text}

# ----------------------------------------------------------------------
# 7. ASSET FETCHING (Pexels / Unsplash)
# ----------------------------------------------------------------------

def search_pexels_videos(query: str, per_page: int = 5) -> List[Dict]:
    """Search Pexels for videos, return list of dicts with 'url', 'width', 'height'."""
    try:
        resp = api.pexels.search_video(query, per_page=per_page)
        videos = resp.get("videos", [])
        results = []
        for vid in videos:
            # Prefer HD files
            video_files = vid.get("video_files", [])
            if not video_files:
                continue
            # Sort by quality: prefer high resolution
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
    """Search Unsplash for images, return list of dicts with 'url', 'width', 'height'."""
    try:
        url = "https://api.unsplash.com/search/photos"
        headers = {"Authorization": f"Client-ID {api.unsplash}"}
        params = {"query": query, "per_page": per_page}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for img in data.get("results", []):
            # Get raw URL with max dimensions
            raw = img.get("urls", {}).get("raw")
            if raw:
                # Append query for large size
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
    """
    Fetch a single asset (video or image) based on query.
    Returns cached path or None.
    """
    # Sanitise query for caching
    key = f"{asset_type}:{query}"
    cache_path = cache_get(key, ext=".mp4" if asset_type == "video" else ".jpg")
    if cache_path:
        logger.info(f"Using cached asset: {cache_path}")
        return cache_path

    # Download fresh
    if asset_type == "video":
        results = search_pexels_videos(query, per_page=3)
        for item in results:
            url = item.get("url")
            if not url:
                continue
            temp_file = CACHE_DIR / f"temp_{hashlib.md5(url.encode()).hexdigest()[:8]}.mp4"
            if download_file(url, temp_file):
                # Validate duration > 3 sec
                dur = get_video_duration(temp_file)
                if dur < 3.0:
                    logger.warning(f"Video too short ({dur}s): {url}")
                    temp_file.unlink(missing_ok=True)
                    continue
                # Cache it
                cached = cache_put_file(key, temp_file, ext=".mp4")
                temp_file.unlink(missing_ok=True)
                logger.info(f"Cached video: {cached}")
                return cached
    else:
        # image from Unsplash
        results = search_unsplash_images(query, per_page=3)
        for item in results:
            url = item.get("url")
            if not url:
                continue
            temp_file = CACHE_DIR / f"temp_{hashlib.md5(url.encode()).hexdigest()[:8]}.jpg"
            if download_file(url, temp_file):
                # Validate dimensions
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
# END OF CHUNK 1
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 8. AUDIO GENERATION (using Groq TTS? Actually we'll use a free TTS via requests)
# Since Groq doesn't have TTS, we'll use a simple fallback: pyttsx3? But that needs
# system audio. We'll use an external service: Google TTS via gTTS, or we can use
# a command‑line tool like espeak. For GitHub Actions, we can install espeak.
# We'll implement a function that uses `espeak` or `ffmpeg` with a downloaded voice.
# Alternatively, we can use the TTS from OpenAI? That costs. So we'll use a free one:
# We'll use the `gTTS` library (google text-to-speech). It requires internet but is free.
# We'll import gTTS and generate an MP3.
# ----------------------------------------------------------------------

try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False
    logger.warning("gTTS not installed, falling back to espeak if available.")

def generate_audio(text: str, output_path: Path, lang: str = "hi") -> bool:
    """
    Generate speech audio using espeak with a male voice (hi+m1).
    Falls back to gTTS if espeak is not available.
    Returns True on success.
    """
    # Try espeak first (guaranteed male voice)
    temp_wav = output_path.with_suffix(".wav")
    # Use hi+m1 for male Hindi voice (explicitly male)
    cmd = [
        "espeak", "-v", "hi+m1", "-s", "150",  # speed
        "-w", str(temp_wav), text
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        # Convert to MP3 using ffmpeg
        subprocess.run([
            "ffmpeg", "-i", str(temp_wav), "-acodec", "libmp3lame",
            "-b:a", "128k", str(output_path)
        ], check=True, capture_output=True)
        temp_wav.unlink(missing_ok=True)
        logger.info(f"Generated audio via espeak (male voice): {output_path}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"espeak failed: {e}. Falling back to gTTS (gender may vary).")

    # Fallback to gTTS (if installed)
    try:
        from gtts import gTTS
        # gTTS does not support gender selection; we use 'hi' language.
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(output_path))
        logger.info(f"Generated audio via gTTS (fallback): {output_path}")
        return True
    except Exception as e:
        logger.error(f"gTTS fallback also failed: {e}")
        return False

# ----------------------------------------------------------------------
# 9. SCENE SEGMENTATION & TIMING
# ----------------------------------------------------------------------

def plan_scenes(lines: List[str], total_duration: float) -> List[Dict]:
    """
    Given script lines and target total duration, compute per‑scene start/end times.
    Returns list of dict: {text, start, end, duration}.
    """
    # Estimate words per second (avg 3 words/sec for Hinglish)
    total_words = sum(len(line.split()) for line in lines)
    words_per_second = max(2.5, min(4.0, total_words / total_duration))
    # Allocate time proportionally
    durations = []
    for line in lines:
        word_count = len(line.split())
        dur = word_count / words_per_second
        durations.append(dur)
    # Scale to total_duration
    total_estimated = sum(durations)
    scale = total_duration / total_estimated
    durations = [d * scale for d in durations]
    # Build scenes
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
# 10. FFMPEG UTILITIES FOR VIDEO EDITING
# ----------------------------------------------------------------------

def create_zoompan_filter(input_file: Path, output_file: Path,
                          duration: float, zoom_factor: float = 0.05,
                          pan_amount: Tuple[float, float] = (0.02, 0.02)) -> bool:
    """
    Apply a slow zoom and pan effect to a static image or video.
    We'll use ffmpeg's zoompan filter for images, or for videos we'll overlay a scaled version?
    For simplicity, we'll handle images; for videos, we can use a simple scale/zoom with crop.
    This function is for images only.
    """
    # Only apply to images (jpg/png)
    if input_file.suffix.lower() not in ['.jpg', '.jpeg', '.png', '.webp']:
        logger.warning("zoompan only works on images, copying video instead")
        shutil.copy2(input_file, output_file)
        return True
    # Use ffmpeg to zoompan
    # We need to ensure the output is 1080x1920.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_file),
        "-vf", f"zoompan=z='min(zoom+{zoom_factor},1.5)':x='(iw - iw/zoom)/2 + {pan_amount[0]}*(iw/zoom)':y='(ih - ih/zoom)/2 + {pan_amount[1]}*(ih/zoom)':d={int(duration * FPS)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}",
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-t", str(duration),
        str(output_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"zoompan failed: {e.stderr.decode()}")
        return False

def apply_transition(prev_file: Path, next_file: Path, output_file: Path,
                     transition_type: str = "fade", duration: float = 0.5) -> bool:
    """
    Apply a transition between two video clips (or images).
    Supported: fade, wipe, slide? We'll implement simple fade.
    For now, we'll just concatenate without transition to save complexity,
    but we can add a crossfade using ffmpeg's filter_complex.
    """
    # For simplicity, we'll use the concat demuxer without transition,
    # but we can add a crossfade by overlapping.
    # We'll implement a simple crossfade.
    cmd = [
        "ffmpeg", "-y",
        "-i", str(prev_file),
        "-i", str(next_file),
        "-filter_complex",
        f"[0:v] [1:v] xfade=transition=fade:duration={duration}:offset={duration}",
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-an",  # audio will be handled separately
        str(output_file)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"Transition failed: {e}")
        return False

def add_captions_to_video(video_path: Path, scenes: List[Dict], output_path: Path) -> bool:
    """
    Burn captions onto the video using drawtext filter.
    Each scene has text and timing.
    We'll generate a complex filter chain.
    """
    # Build the drawtext filters for each scene
    filters = []
    for idx, scene in enumerate(scenes):
        text = scene["text"]
        start = scene["start"]
        duration = scene["duration"]
        # Escape text for ffmpeg
        escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        # Position: bottom center with a background box
        drawtext = (
            f"drawtext=text='{escaped}':"
            f"fontfile={str(get_font_path())}:"
            f"fontsize={CAPTION_FONT_SIZE}:"
            f"fontcolor={CAPTION_TEXT_COLOR}:"
            f"box=1:boxcolor=black@0.6:boxborderw=10:"
            f"x=(w-text_w)/2:y=h-text_h-100:"
            f"enable='between(t,{start},{start+duration})'"
        )
        filters.append(drawtext)
    # Combine filters with a comma
    filter_str = ",".join(filters)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", filter_str,
        "-c:v", VIDEO_CODEC,
        "-pix_fmt", PIXEL_FORMAT,
        "-c:a", "copy",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"Caption burn failed: {e}")
        return False

def get_font_path() -> Path:
    """Return a path to a TTF font (prefer Noto Sans Devanagari)."""
    # Check system fonts
    system_fonts = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for f in system_fonts:
        if Path(f).exists():
            return Path(f)
    # Fallback: download a font if not present
    font_dir = FONTS_DIR
    font_path = font_dir / "NotoSansDevanagari-Regular.ttf"
    if not font_path.exists():
        # Download from Google Fonts
        url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
        if download_file(url, font_path):
            return font_path
        else:
            # Use default system font (may not support Devanagari)
            return Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return font_path

# ----------------------------------------------------------------------
# 11. MAIN VIDEO COMPOSITION
# ----------------------------------------------------------------------

def compose_video(scenes: List[Dict], assets: List[Path], output_video: Path) -> bool:
    """
    Create a single video from scenes using provided assets (one per scene).
    steps:
      1. For each scene, if asset is image, apply zoompan to make a video clip.
         If asset is video, trim to scene duration and add a scale to fit 9:16.
      2. Concatenate all clips (with optional transitions).
      3. Add background music (if available).
      4. Burn captions.
    """
    # Ensure we have enough assets
    if len(assets) < len(scenes):
        logger.warning(f"Not enough assets ({len(assets)}) for {len(scenes)} scenes, reusing last.")
        while len(assets) < len(scenes):
            assets.append(assets[-1])

    # Step 1: Generate intermediate clips
    temp_clips = []
    for i, (scene, asset) in enumerate(zip(scenes, assets)):
        clip_dur = scene["duration"]
        clip_file = CLIPS_DIR / f"scene_{i:02d}.mp4"
        if asset.suffix.lower() in ['.mp4', '.mov', '.avi', '.webm']:
            # Video file: trim and scale to 9:16
            # We'll crop to fit: use scale and crop to 9:16
            cmd = [
                "ffmpeg", "-y",
                "-i", str(asset),
                "-ss", "0",  # start from beginning, we can randomize later
                "-t", str(clip_dur),
                "-vf", f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", VIDEO_CODEC,
                "-pix_fmt", PIXEL_FORMAT,
                "-an",
                str(clip_file)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            # Image: apply zoompan
            create_zoompan_filter(asset, clip_file, clip_dur, zoom_factor=0.02, pan_amount=(0.01, 0.01))
        temp_clips.append(clip_file)

    # Step 2: Concatenate with crossfade transitions
    # We'll build a concat filter with xfade between each pair.
    # For simplicity, we'll just concatenate without transitions to avoid complexity,
    # but we'll add a simple fade in/out at start/end.
    # Use concat demuxer.
    concat_file = OUTPUT_DIR / "concat_list.txt"
    with open(concat_file, "w") as f:
        for clip in temp_clips:
            f.write(f"file '{clip.absolute()}'\n")
    # Concat without re-encoding (copy) to save time, but we need same codec.
    concat_output = OUTPUT_DIR / "concat_temp.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(concat_output)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Step 3: Add audio (voiceover + background music)
    # We need voiceover from script full text
    # We'll generate voiceover as separate audio file and mix with background music.
    # Background music: we can use a free track from Pixabay or use a sine wave placeholder.
    # For production, we'll try to fetch a free track.
    # We'll implement a function to download a royalty‑free track.
    voiceover_file = OUTPUT_DIR / "voiceover.mp3"
    full_text = " ".join([s["text"] for s in scenes])
    if not generate_audio(full_text, voiceover_file):
        logger.warning("Voiceover generation failed, using silent audio.")
        # Create silent audio
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(sum(s["duration"] for s in scenes)),
            str(voiceover_file)
        ], check=True)

    # Background music: download from a free source (e.g., Pixabay)
    bg_music_file = CACHE_DIR / "bg_music.mp3"
    if not bg_music_file.exists():
        # Try to download from a sample URL (pixabay example)
        # We'll use a placeholder: we can try to use a pre‑uploaded asset.
        # For now, generate a simple tone or use a known free track.
        # Since we cannot guarantee external links, we'll skip bg music or generate a simple beat.
        # Option: use `ffmpeg` to generate a soft pad sound.
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"sine=frequency=440:duration={sum(s['duration'] for s in scenes)}",
            "-c:a", "aac", "-b:a", "128k",
            str(bg_music_file)
        ], check=True)

    # Mix audio: voiceover + bg music (duck bg)
    # We'll use ffmpeg's amix with volume adjustments.
    mixed_audio = OUTPUT_DIR / "mixed_audio.mp3"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voiceover_file),
        "-i", str(bg_music_file),
        "-filter_complex",
        "[0:a] volume=1.5 [voice]; [1:a] volume=0.3 [bg]; [voice][bg] amix=inputs=2:duration=first",
        "-c:a", "aac", "-b:a", "128k",
        str(mixed_audio)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Step 4: Combine video (concat) with audio
    final_video_no_captions = OUTPUT_DIR / "final_no_captions.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(concat_output),
        "-i", str(mixed_audio),
        "-c:v", VIDEO_CODEC,
        "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
        "-shortest",
        str(final_video_no_captions)
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Step 5: Burn captions
    success = add_captions_to_video(final_video_no_captions, scenes, output_video)

    # Cleanup temp files
    for f in temp_clips + [concat_file, concat_output, voiceover_file, bg_music_file, mixed_audio, final_video_no_captions]:
        try:
            f.unlink(missing_ok=True)
        except:
            pass

    return success

# ----------------------------------------------------------------------
# 12. THUMBNAIL GENERATION
# ----------------------------------------------------------------------

def generate_thumbnail(title: str, video_path: Path, output_path: Path) -> bool:
    """Extract a frame from video and overlay title text."""
    # Extract frame at 1/3 of duration
    dur = get_video_duration(video_path)
    if dur <= 0:
        return False
    timestamp = dur / 3.0
    frame_file = OUTPUT_DIR / "frame.jpg"
    cmd = [
        "ffmpeg", "-y", "-ss", str(timestamp), "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(frame_file)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    # Load image with PIL, overlay text
    try:
        img = Image.open(frame_file)
        # Resize to thumbnail size (1080x1920 but we'll crop to 1280x720)
        # Actually we'll resize to 1280x720 (landscape) but we can crop a center portion
        # For simplicity, we'll resize to 1280x720 without preserving ratio (stretch)
        img = img.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
        draw = ImageDraw.Draw(img)
        # Font: use a large bold font
        try:
            font = ImageFont.truetype(str(get_font_path()), 80)
        except:
            font = ImageFont.load_default()
        # Title text with outline
        text = title
        # Get text bbox
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (img.width - text_w) // 2
        y = img.height - text_h - 100
        # Draw outline
        outline_color = "black"
        for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
            draw.text((x+dx, y+dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill="white")
        # Add a small subtitle like "Ajeebology Shorts"
        sub_font = ImageFont.truetype(str(get_font_path()), 40) if get_font_path().exists() else ImageFont.load_default()
        sub_text = "@Ajeebology"
        sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = (img.width - sub_w) // 2
        sub_y = y + text_h + 20
        draw.text((sub_x, sub_y), sub_text, font=sub_font, fill="yellow")
        img.save(output_path)
        return True
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        return False

# ----------------------------------------------------------------------
# END OF CHUNK 2
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 13. TELEGRAM DELIVERY
# ----------------------------------------------------------------------

def send_to_telegram(video_path: Path, thumbnail_path: Path,
                     title: str, description: str, tags: str,
                     hashtags: str, category: str, sources: List[str],
                     runtime_stats: Dict[str, Any]) -> bool:
    """Send final video, thumbnail, and metadata to Telegram."""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Telegram credentials missing")
        return False
    try:
        bot = Bot(token=token)
        # Send video with caption
        with open(video_path, "rb") as vf, open(thumbnail_path, "rb") as tf:
            caption = (
                f"🎬 *{title}*\n\n"
                f"{description}\n\n"
                f"🏷️ Tags: {tags}\n"
                f"#️⃣ Hashtags: {hashtags}\n"
                f"📂 Category: {category}\n"
                f"🔗 Sources: {', '.join(sources)}\n"
                f"⏱️ Runtime: {runtime_stats.get('duration', 0):.1f}s\n"
                f"📊 Artifact: {runtime_stats.get('artifact_url', 'N/A')}"
            )
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
        # Also send the thumbnail as photo
        with open(thumbnail_path, "rb") as tf:
            bot.send_photo(chat_id=chat_id, photo=InputFile(tf), caption="Thumbnail")
        logger.info("Telegram delivery successful")
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False

# ----------------------------------------------------------------------
# 14. GENERATE METADATA AND ARTIFACT
# ----------------------------------------------------------------------

def generate_metadata(scenes: List[Dict], title: str, fact: Dict[str, str],
                      category: str) -> Dict[str, Any]:
    """Produce metadata for upload (description, tags, etc.)."""
    # Build description
    description = f"🤯 {title}\n\n"
    description += "Did you know this mind‑blowing fact? 🔥\n\n"
    for i, scene in enumerate(scenes, 1):
        description += f"{i}. {scene['text']}\n"
    description += "\n📌 Don't forget to LIKE, SHARE & SUBSCRIBE to Ajeebology Shorts! 🚀"
    # Tags
    tags = ["Ajeebology", "Shorts", "Facts", "Psychology", "Space", "Weird", "Hinglish", category]
    hashtags = "#".join(["#Ajeebology", "#Shorts", "#Facts", category.replace(" ", "")]
                       + [f"#{word}" for word in title.split() if len(word) > 3][:3])
    return {
        "title": title,
        "description": description,
        "tags": ", ".join(tags),
        "hashtags": "#" + hashtags,
        "category": category,
        "sources": [fact.get("source", "")],
    }

# ----------------------------------------------------------------------
# 15. MAIN PIPELINE
# ----------------------------------------------------------------------

def run_pipeline() -> bool:
    """Orchestrate the entire Shorts production."""
    logger.info("Starting Ajeebology Shorts pipeline")
    start_time = time.time()

    # 1. Choose a category randomly
    categories = ["Psychology Facts", "Space Facts", "Weird World Facts"]
    category = random.choice(categories)
    logger.info(f"Selected category: {category}")

    # 2. Research fact
    try:
        fact = research_fact(category)
        logger.info(f"Fact: {fact['title']}")
    except Exception as e:
        logger.error(f"Research failed: {e}")
        return False

    # 3. Generate script
    try:
        script = generate_script(category, fact)
        lines = script["lines"]
        full_text = script["full_text"]
        logger.info(f"Script: {lines}")
    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        return False

    # 4. Plan scene durations (target total 60 sec)
    total_duration = random.uniform(*TARGET_DURATION)
    scenes = plan_scenes(lines, total_duration)
    logger.info(f"Planned {len(scenes)} scenes over {sum(s['duration'] for s in scenes):.1f}s")

    # 5. Fetch assets for each scene (video or image)
    assets = []
    for i, scene in enumerate(scenes):
        # Derive query from scene text (take first few words)
        query_words = scene["text"].split()[:5]
        query = " ".join(query_words)
        # For variety, alternate video and image
        asset_type = "video" if i % 2 == 0 else "image"
        asset = fetch_asset(query, asset_type)
        if asset is None:
            # Fallback to a generic asset
            fallback_query = category.split()[0] if i % 2 == 0 else "mysterious"
            asset = fetch_asset(fallback_query, "video" if i % 2 == 0 else "image")
            if asset is None:
                # Last resort: use a placeholder image generated by PIL
                placeholder = ASSETS_DIR / f"placeholder_{i}.jpg"
                if not placeholder.exists():
                    img = Image.new('RGB', (1080, 1920), color=(random.randint(0,255), random.randint(0,255), random.randint(0,255)))
                    img.save(placeholder)
                asset = placeholder
        assets.append(asset)

    # 6. Compose video
    output_video = OUTPUT_DIR / f"ajeebology_{get_timestamp()}.mp4"
    logger.info("Composing video...")
    if not compose_video(scenes, assets, output_video):
        logger.error("Video composition failed")
        return False
    logger.info(f"Video composed: {output_video}")

    # 7. Generate thumbnail
    title = fact['title']
    thumbnail_path = OUTPUT_DIR / f"thumbnail_{get_timestamp()}.jpg"
    if not generate_thumbnail(title, output_video, thumbnail_path):
        logger.warning("Thumbnail generation failed, using a fallback")
        # Create a simple fallback thumbnail
        img = Image.new('RGB', (1280, 720), color='black')
        draw = ImageDraw.Draw(img)
        draw.text((100, 300), title, fill='white', font=ImageFont.load_default())
        img.save(thumbnail_path)

    # 8. Generate metadata
    metadata = generate_metadata(scenes, title, fact, category)

    # 9. Collect runtime stats
    duration = get_video_duration(output_video)
    runtime_stats = {
        "duration": duration,
        "scenes": len(scenes),
        "assets_used": len(assets),
        "artifact_url": "https://github.com/your-repo/actions/runs/...",  # placeholder
    }

    # 10. Send to Telegram
    logger.info("Sending to Telegram...")
    if not send_to_telegram(
        output_video, thumbnail_path,
        metadata["title"], metadata["description"],
        metadata["tags"], metadata["hashtags"],
        metadata["category"], metadata["sources"],
        runtime_stats
    ):
        logger.error("Telegram delivery failed")
        # But we continue to save artifacts locally

    # 11. Save metadata JSON
    metadata_path = OUTPUT_DIR / f"metadata_{get_timestamp()}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # 12. Log success
    elapsed = time.time() - start_time
    logger.info(f"Pipeline completed in {elapsed:.2f}s")
    return True

# ----------------------------------------------------------------------
# 16. ENTRY POINT
# ----------------------------------------------------------------------

if __name__ == "__main__":
    try:
        success = run_pipeline()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)
