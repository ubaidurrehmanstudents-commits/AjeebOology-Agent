#!/usr/bin/env python3
"""
Ajeebology Shorts — Fully Automated YouTube Shorts Generator
Single-file production pipeline. No modules. No helpers. Everything here.

Author: Ajeebology
Architecture: GitHub Actions Free Tier
Constraints: 2 files only (youtube_agent.py + youtube_agent.yml)
"""

# ═══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import time
import math
import random
import hashlib
import tempfile
import subprocess
import textwrap
import re
import shutil
import logging
import traceback
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field, asdict

# Third-party (installed via pip in workflow)
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# Optional imports with graceful fallback
try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

try:
    import edge_tts
    import asyncio
except ImportError:
    edge_tts = None
    asyncio = None

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Channel settings
CHANNEL_NAME = "Ajeebology Shorts"
CONTENT_TOPICS = ["psychology", "space", "weird_world"]
TARGET_DURATION_SECONDS = 60  # 55-65s range
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # 9:16 vertical
VIDEO_FPS = 30
VIDEO_BITRATE = "4M"

# Paths
BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
ASSETS_DIR = BASE_DIR / "assets_cache"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# Logging setup
LOG_FILE = OUTPUT_DIR / "generation.log"
ERROR_LOG = OUTPUT_DIR / "error.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ajeebology")

# Runtime tracking
RUNTIME_STATS = {
    "start_time": time.time(),
    "api_calls": 0,
    "assets_downloaded": 0,
    "total_seconds": 0,
    "steps": {},
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FactSource:
    url: str
    title: str
    snippet: str = ""


@dataclass
class ScriptSegment:
    text: str
    start_time: float
    end_time: float
    visual_keyword: str = ""
    emotion: str = "neutral"


@dataclass
class VideoAsset:
    path: Path
    asset_type: str  # "video" or "image"
    duration: float
    source_url: str = ""
    keywords: List[str] = field(default_factory=list)


@dataclass
class VideoMetadata:
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    category: str = "Education"
    sources: List[str] = field(default_factory=list)
    runtime_stats: Dict[str, Any] = field(default_factory=dict)
    script: str = ""
    thumbnail_text: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS (ALL INLINE — NO MODULES)
# ═══════════════════════════════════════════════════════════════════════════════

def log_step(step_name: str):
    """Decorator to track step timing."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.info(f"▶ START: {step_name}")
            t0 = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - t0
                RUNTIME_STATS["steps"][step_name] = round(elapsed, 2)
                logger.info(f"✓ DONE: {step_name} ({elapsed:.1f}s)")
                return result
            except Exception as e:
                elapsed = time.time() - t0
                logger.error(f"✗ FAILED: {step_name} ({elapsed:.1f}s): {e}")
                raise
        return wrapper
    return decorator


def safe_api_call(func, *args, retries=3, delay=2, **kwargs):
    """Generic retry wrapper for API calls."""
    for attempt in range(1, retries + 1):
        try:
            RUNTIME_STATS["api_calls"] += 1
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"API call attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(delay * attempt)
            else:
                raise
    return None


def download_file(url: str, dest: Path, timeout=30) -> bool:
    """Download a file with retry logic."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            with open(dest, "wb") as f:
                f.write(response.read())
        return True
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return False


def run_ffmpeg(cmd: List[str], timeout=300) -> Tuple[bool, str]:
    """Execute FFmpeg command with error capture."""
    full_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + cmd
    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False, result.stderr
        return True, ""
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timeout")
        return False, "timeout"
    except Exception as e:
        logger.error(f"FFmpeg execution error: {e}")
        return False, str(e)


def get_video_duration(path: Path) -> float:
    """Get video duration using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def sanitize_filename(text: str) -> str:
    """Create safe filename from text."""
    safe = re.sub(r'[^\w\s-]', '', text).strip()
    safe = re.sub(r'[-\s]+', '_', safe)
    return safe[:50]


def hinglish_clean(text: str) -> str:
    """Clean and normalize Hinglish text."""
    # Remove excessive punctuation
    text = re.sub(r'[!]{2,}', '!', text)
    text = re.sub(r'[?]{2,}', '?', text)
    # Normalize spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: RESEARCH & FACT SOURCING (Tavily + Groq)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Research & Fact Sourcing")
def research_facts(topic: str) -> Tuple[str, List[FactSource]]:
    """
    Research facts using Tavily API and Groq for curation.
    Returns: (curated_fact_text, sources)
    """
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    groq_key = os.environ.get("GROQ_API_KEY", "")

    if not tavily_key:
        logger.warning("No TAVILY_API_KEY — using fallback facts")
        return _fallback_facts(topic), []

    # Tavily search
    try:
        client = TavilyClient(api_key=tavily_key)
        query_map = {
            "psychology": "mind-blowing psychology facts human behavior 2024",
            "space": "amazing space facts universe discoveries 2024",
            "weird_world": "weird unbelievable world facts strange phenomena",
        }
        search_query = query_map.get(topic, f"interesting {topic} facts")

        response = safe_api_call(
            client.search,
            search_query,
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

        sources = []
        context_text = ""

        if response and "results" in response:
            for result in response["results"]:
                source = FactSource(
                    url=result.get("url", ""),
                    title=result.get("title", ""),
                    snippet=result.get("content", "")[:500],
                )
                sources.append(source)
                context_text += f"\nSource: {source.title}\n{source.snippet}\n"

        # Use Groq to curate the best fact
        if groq_key and context_text:
            curated = _curate_fact_with_groq(groq_key, topic, context_text)
            return curated, sources

        # Fallback: use first snippet
        if sources:
            return sources[0].snippet, sources

    except Exception as e:
        logger.error(f"Tavily research failed: {e}")

    return _fallback_facts(topic), []


def _curate_fact_with_groq(api_key: str, topic: str, context: str) -> str:
    """Use Groq to select and rewrite the most interesting fact."""
    try:
        client = Groq(api_key=api_key)
        prompt = f"""You are a content curator for "Ajeebology Shorts", a YouTube channel about amazing facts.
Topic: {topic}
Language: Hinglish (mix of Hindi and English, written in Roman script)

From the following research, select the SINGLE most mind-blowing, shareable fact.
Rewrite it in engaging Hinglish (60-80 words max). Make it conversational and hook the viewer immediately.
Use short punchy sentences. Add dramatic pauses with "..." 

Research:
{context}

Output ONLY the rewritten fact. No explanations, no formatting, no quotes around it."""

        response = safe_api_call(
            client.chat.completions.create,
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )

        if response and response.choices:
            return hinglish_clean(response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Groq curation failed: {e}")

    return context[:300] if context else _fallback_facts(topic)


def _fallback_facts(topic: str) -> str:
    """Fallback facts when APIs fail."""
    facts = {
        "psychology": (
            "Tumhara brain actually tumhari aankhon se 50% zyada information process karta hai "
            "jo tum dekhte ho... lekin tum sirf 0.003% hi notice karte ho! "
            "Matlab har second millions of details miss ho rahi hain... "
            "Aur tumhe lagta hai tum aware ho?"
        ),
        "space": (
            "Ek black hole itna powerful hai ke agar tum uske paas jao toh "
            "tumhari body spaghetti ki tarah stretch ho jayegi... scientists isse "
            "'spaghettification' kehte hain. Space mein death bhi weird hoti hai!"
        ),
        "weird_world": (
            "Japan mein ek island hai jahan sirf cats rehti hain... "
            "humans 100 se bhi kam hain! Yeh place literally 'Cat Heaven' hai. "
            "Duniya mein aisi 50+ cat islands hain... insaan extinct ho jaye toh "
            "cats definitely rule karengi!"
        ),
    }
    return facts.get(topic, facts["psychology"])


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: SCRIPT GENERATION (Groq — Hinglish)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Script Generation")
def generate_script(topic: str, fact: str) -> Tuple[str, List[ScriptSegment], str]:
    """
    Generate complete Hinglish script with timing segments.
    Returns: (full_script, segments, hook)
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return _fallback_script(topic)

    # Speaking rate: ~130 words per minute for Hinglish
    # Target: 55-65 seconds = ~120-140 words
    target_words = 130

    prompt = f"""You are the lead scriptwriter for "Ajeebology Shorts" — a viral YouTube Shorts channel.
Your scripts get millions of views because they are addictive.

TOPIC: {topic}
CORE FACT: {fact}

RULES:
1. Language: Hinglish (Roman script, casual conversational)
2. Total words: {target_words} (strict — must fit in 55-65 seconds)
3. Structure:
   - HOOK (0-3s): Shocking statement or question. Start with "Kya tumhe pata hai..." or "Imagine karo..."
   - BODY (3-50s): Build curiosity with 3-4 rapid facts. Use "Lekin..." for twists.
   - CTA (50-60s): "Follow for more ajeeb facts!" or similar
4. Every sentence must be SHORT (5-10 words max). One idea per sentence.
5. Use conversational fillers: "Matlab", "Basically", "Samajh rahe ho?", "Crazy hai na?"
6. Add [PAUSE] markers where the speaker should breathe
7. Add [EMPHASIS] before words to stress
8. Add [VISUAL: keyword] to suggest what footage to show

OUTPUT FORMAT:
Return ONLY the script text. No explanations. No markdown. Just the spoken words with markers."""

    try:
        client = Groq(api_key=groq_key)
        response = safe_api_call(
            client.chat.completions.create,
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=500,
        )

        if response and response.choices:
            script = hinglish_clean(response.choices[0].message.content)
            segments, hook = _parse_script_to_segments(script)
            return script, segments, hook

    except Exception as e:
        logger.error(f"Script generation failed: {e}")

    return _fallback_script(topic)


def _parse_script_to_segments(script: str) -> Tuple[List[ScriptSegment], str]:
    """Parse script into timed segments with visual keywords."""
    # Remove markers for clean text but keep for analysis
    clean_script = re.sub(r'\[PAUSE\]|\[EMPHASIS\]|\[VISUAL:[^\]]+\]', '', script)
    clean_script = re.sub(r'\s+', ' ', clean_script).strip()

    # Extract hook (first sentence)
    sentences = re.split(r'[.!?।]+', clean_script)
    hook = sentences[0].strip() if sentences else "Kya tumhe pata hai?"

    # Estimate timing: ~2.3 chars per second for Hinglish at natural pace
    words = clean_script.split()
    total_chars = len(clean_script)
    speaking_rate = 2.3  # chars per second

    segments = []
    current_time = 0.0

    # Split into chunks of ~15-20 words for visual changes every 2-3s
    chunk_size = 4  # words per segment (forces rapid cuts)
    word_chunks = [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]

    for chunk in word_chunks:
        text = " ".join(chunk)
        duration = max(len(text) / speaking_rate, 2.0)  # Min 2s per segment
        duration = min(duration, 3.5)  # Max 3.5s for retention

        # Extract visual keyword from chunk
        visual_keyword = _extract_visual_keyword(text)

        segment = ScriptSegment(
            text=text,
            start_time=current_time,
            end_time=current_time + duration,
            visual_keyword=visual_keyword,
            emotion=_detect_emotion(text),
        )
        segments.append(segment)
        current_time += duration

    # Adjust last segment to hit target duration
    if segments:
        total_estimated = segments[-1].end_time
        if total_estimated > 65:
            # Compress by reducing segment durations
            scale = 60 / total_estimated
            for seg in segments:
                seg.end_time = seg.start_time + (seg.end_time - seg.start_time) * scale
        elif total_estimated < 55:
            # Extend slightly
            scale = 58 / total_estimated
            for seg in segments:
                seg.end_time = seg.start_time + (seg.end_time - seg.start_time) * scale

    return segments, hook


def _extract_visual_keyword(text: str) -> str:
    """Extract the most visual noun from text for asset search."""
    # Common visual keywords by topic
    visual_map = {
        "brain": "brain neuroscience", "mind": "brain thinking", "eye": "eyes vision",
        "space": "space galaxy", "black hole": "black hole space", "star": "stars night",
        "planet": "planet space", "cat": "cats animals", "island": "island ocean",
        "ocean": "ocean waves", "money": "money cash", "food": "food delicious",
        "dream": "dream sleep", "sleep": "sleep night", "memory": "memory brain",
        "heart": "heart heartbeat", "time": "time clock", "water": "water splash",
    }

    text_lower = text.lower()
    for key, val in visual_map.items():
        if key in text_lower:
            return val

    # Fallback: extract longest noun-like word
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text_lower)
    return words[0] if words else "abstract"


def _detect_emotion(text: str) -> str:
    """Detect emotional tone for visual treatment."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["shock", "crazy", "wtf", "omg", "unbelievable", "mind"]):
        return "shock"
    if any(w in text_lower for w in ["happy", "love", "amazing", "awesome", "beautiful"]):
        return "happy"
    if any(w in text_lower for w in ["scary", "fear", "death", "danger", "warning"]):
        return "dark"
    if any(w in text_lower for w in ["sad", "cry", "miss", "lost", "alone"]):
        return "sad"
    return "neutral"


def _fallback_script(topic: str) -> Tuple[str, List[ScriptSegment], str]:
    """Fallback script when Groq fails."""
    scripts = {
        "psychology": (
            "Kya tumhe pata hai? Tumhara brain har second 11 million bits process karta hai. "
            "Par tum consciously sirf 40 bits notice karte ho. Matlab 99.999% information "
            "tumhari aankhon ke saamme se guzar jaati hai. Tumhara brain auto-pilot pe chalta hai. "
            "Aur tum sochte ho tum control mein ho? Follow for more mind-blowing facts!"
        ),
        "space": (
            "Imagine karo... Agar tum space mein bina suit ke nikle. Pehle 15 seconds mein "
            "tum conscious rehte. Phir tumhari body inflate hone lagti. 90 seconds mein "
            "tum dead. Lekin agar tumhe rescue kar liya jaye toh tum survive kar sakte ho! "
            "Space mein death bhi ajeeb hai. Follow for more space facts!"
        ),
        "weird_world": (
            "Duniya mein ek aisa gaaon hai jahan log sirf left hand se kaam karte hain. "
            "Right hand use karna banned hai! Yeh India mein hai. 400 saal purani tradition. "
            "Aur tum sochte ho tumhara gaaon weird hai? Follow for more ajeeb facts!"
        ),
    }

    script = scripts.get(topic, scripts["psychology"])
    segments, hook = _parse_script_to_segments(script)
    return script, segments, hook


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: AUDIO GENERATION (Edge-TTS — Free, High Quality)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Audio Generation")
def generate_audio(script: str, segments: List[ScriptSegment]) -> Tuple[Path, List[ScriptSegment]]:
    """
    Generate narration audio using Edge-TTS (free Microsoft voices).
    Returns: (audio_path, updated_segments_with_exact_timing)
    """
    if edge_tts is None:
        logger.error("edge_tts not installed — cannot generate audio")
        raise RuntimeError("edge_tts is required but not installed")

    audio_path = TEMP_DIR / "narration.mp3"

    # Clean script for TTS (remove markers)
    clean_script = re.sub(r'\[PAUSE\]|\[EMPHASIS\]|\[VISUAL:[^\]]+\]', '...', script)
    clean_script = re.sub(r'\.{2,}', '...', clean_script)
    clean_script = re.sub(r'\s+', ' ', clean_script).strip()

    # Select voice based on emotion
    # Hindi voices available in Edge-TTS
    voices = [
        "hi-IN-MadhurNeural",      # Male, warm
        "hi-IN-SwaraNeural",       # Female, expressive
        "hi-IN-KunalNeural",       # Male, energetic
    ]
    voice = random.choice(voices)

    async def _generate():
        communicate = edge_tts.Communicate(clean_script, voice)
        await communicate.save(str(audio_path))

    try:
        asyncio.run(_generate())
    except Exception as e:
        logger.error(f"Edge-TTS generation failed: {e}")
        raise

    # Get exact audio duration
    duration = get_video_duration(audio_path)
    if duration == 0:
        # Fallback estimation
        duration = len(clean_script.split()) / 2.2  # ~2.2 words/sec for Hindi

    # Adjust segment timings to match actual audio duration
    if segments:
        total_estimated = segments[-1].end_time if segments else 60
        if total_estimated > 0:
            scale = duration / total_estimated
            for seg in segments:
                seg.start_time *= scale
                seg.end_time *= scale

    logger.info(f"Audio generated: {audio_path} ({duration:.1f}s)")
    return audio_path, segments


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: VISUAL ASSET ACQUISITION (Pexels + Unsplash)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Asset Acquisition")
def acquire_assets(segments: List[ScriptSegment], topic: str) -> List[VideoAsset]:
    """
    Download video clips and images from Pexels/Unsplash.
    Returns list of VideoAsset mapped to segments.
    """
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")

    assets = []
    used_keywords = set()

    # Topic-based base keywords
    topic_keywords = {
        "psychology": ["brain", "thinking", "mind", "neuron", "meditation", "eye closeup"],
        "space": ["galaxy", "nebula", "planet", "astronaut", "stars", "rocket launch"],
        "weird_world": ["strange place", "unusual", "mystery", "abandoned", "optical illusion"],
    }

    base_keywords = topic_keywords.get(topic, ["amazing", "beautiful", "interesting"])

    for i, segment in enumerate(segments):
        # Try visual keyword first, then fallback
        keywords_to_try = [segment.visual_keyword] if segment.visual_keyword else []
        keywords_to_try.extend(base_keywords)
        keywords_to_try.append(random.choice(["4k", "hd", "cinematic", "slow motion"]))

        asset = None
        for keyword in keywords_to_try:
            if keyword in used_keywords:
                continue

            # Try Pexels video first
            if pexels_key:
                asset = _fetch_pexels_video(keyword, pexels_key, i)
                if asset:
                    used_keywords.add(keyword)
                    break

            # Fallback to Unsplash image
            if unsplash_key and not asset:
                asset = _fetch_unsplash_image(keyword, unsplash_key, i)
                if asset:
                    used_keywords.add(keyword)
                    break

        # Ultimate fallback: generate colored background
        if not asset:
            asset = _generate_fallback_visual(i, segment.emotion)

        assets.append(asset)

    RUNTIME_STATS["assets_downloaded"] = len([a for a in assets if a.source_url])
    return assets


def _fetch_pexels_video(keyword: str, api_key: str, index: int) -> Optional[VideoAsset]:
    """Fetch video from Pexels API."""
    try:
        url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(keyword)}&per_page=5&orientation=portrait"
        headers = {"Authorization": api_key}

        response = requests.get(url, headers=headers, timeout=15)
        RUNTIME_STATS["api_calls"] += 1

        if response.status_code != 200:
            return None

        data = response.json()
        videos = data.get("videos", [])

        if not videos:
            return None

        # Pick random video from results
        video = random.choice(videos)
        video_files = video.get("video_files", [])

        # Find best quality vertical video
        best_file = None
        for vf in video_files:
            if vf.get("width", 0) < vf.get("height", 0):  # Portrait
                if not best_file or vf.get("height", 0) > best_file.get("height", 0):
                    best_file = vf

        if not best_file:
            best_file = video_files[0] if video_files else None

        if not best_file:
            return None

        # Download
        dest = ASSETS_DIR / f"pexels_{index}_{sanitize_filename(keyword)}.mp4"
        if download_file(best_file["link"], dest):
            duration = get_video_duration(dest)
            return VideoAsset(
                path=dest,
                asset_type="video",
                duration=duration or 5.0,
                source_url=best_file["link"],
                keywords=[keyword],
            )

    except Exception as e:
        logger.warning(f"Pexels fetch failed for '{keyword}': {e}")

    return None


def _fetch_unsplash_image(keyword: str, api_key: str, index: int) -> Optional[VideoAsset]:
    """Fetch image from Unsplash API and convert to video-like asset."""
    try:
        url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(keyword)}&per_page=5&orientation=portrait"
        headers = {"Authorization": f"Client-ID {api_key}"}

        response = requests.get(url, headers=headers, timeout=15)
        RUNTIME_STATS["api_calls"] += 1

        if response.status_code != 200:
            return None

        data = response.json()
        results = data.get("results", [])

        if not results:
            return None

        photo = random.choice(results)
        img_url = photo["urls"]["regular"]

        # Download
        dest = ASSETS_DIR / f"unsplash_{index}_{sanitize_filename(keyword)}.jpg"
        if download_file(img_url, dest):
            return VideoAsset(
                path=dest,
                asset_type="image",
                duration=5.0,  # Will be animated
                source_url=img_url,
                keywords=[keyword],
            )

    except Exception as e:
        logger.warning(f"Unsplash fetch failed for '{keyword}': {e}")

    return None


def _generate_fallback_visual(index: int, emotion: str) -> VideoAsset:
    """Generate a procedural colored background as ultimate fallback."""
    colors = {
        "shock": [(255, 50, 50), (50, 0, 0)],
        "happy": [(255, 200, 50), (255, 150, 0)],
        "dark": [(30, 30, 50), (10, 10, 20)],
        "sad": [(50, 100, 150), (30, 60, 100)],
        "neutral": [(50, 50, 80), (30, 30, 50)],
    }

    c1, c2 = colors.get(emotion, colors["neutral"])

    # Create gradient image
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), c1)
    draw = ImageDraw.Draw(img)

    # Draw gradient bars
    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    # Add subtle noise texture
    arr = np.array(img)
    noise = np.random.randint(-10, 10, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # Add subtle geometric pattern
    draw = ImageDraw.Draw(img)
    for i in range(0, VIDEO_WIDTH, 100):
        draw.line([(i, 0), (i, VIDEO_HEIGHT)], fill=(255, 255, 255, 30), width=1)
    for i in range(0, VIDEO_HEIGHT, 100):
        draw.line([(0, i), (VIDEO_WIDTH, i)], fill=(255, 255, 255, 30), width=1)

    dest = ASSETS_DIR / f"fallback_{index}_{emotion}.jpg"
    img.save(dest, quality=95)

    return VideoAsset(
        path=dest,
        asset_type="image",
        duration=5.0,
        source_url="",
        keywords=[emotion],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5: CAPTION GENERATION (ASS Subtitles with Karaoke-style highlighting)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Caption Generation")
def generate_captions(segments: List[ScriptSegment], audio_path: Path) -> Path:
    """
    Generate Advanced SubStation Alpha (.ass) subtitle file with:
    - Word-level karaoke highlighting
    - Bold current word
    - Color transitions
    - Proper positioning for 9:16
    """
    ass_path = TEMP_DIR / "captions.ass"

    # ASS header for 1080x1920 vertical video
    ass_header = """[Script Info]
Title: Ajeebology Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,4,0,2,20,20,400,1
Style: Highlight,Arial,72,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,20,20,400,1
Style: Hook,Arial,80,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,110,110,0,0,1,5,2,2,20,20,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for seg in segments:
        start = _seconds_to_ass_time(seg.start_time)
        end = _seconds_to_ass_time(seg.end_time)

        # Style based on position
        style = "Hook" if seg.start_time < 3 else "Default"

        # Clean text (remove markers for display)
        display_text = re.sub(r'\[PAUSE\]|\[EMPHASIS\]|\[VISUAL:[^\]]+\]', '', seg.text)
        display_text = display_text.strip()

        if not display_text:
            continue

        # Word-level karaoke effect
        words = display_text.split()
        if len(words) > 1 and seg.end_time > seg.start_time:
            word_duration = (seg.end_time - seg.start_time) / len(words)
            karaoke_text = ""

            for w_idx, word in enumerate(words):
                w_start = seg.start_time + w_idx * word_duration
                w_end = w_start + word_duration
                k_start = _seconds_to_ass_time(w_start)
                k_end = _seconds_to_ass_time(w_end)

                # Karaoke timing in centiseconds
                cs = int(word_duration * 100)

                # Highlight current word, dim others
                karaoke_text += f"{{\\k{cs}}}{word} "

            events.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{karaoke_text.strip()}")
        else:
            events.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{display_text}")

    # Write ASS file
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        f.write("\n".join(events))

    return ass_path


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6: VIDEO ASSEMBLY (FFmpeg — Professional Editing)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Video Assembly")
def assemble_video(
    segments: List[ScriptSegment],
    assets: List[VideoAsset],
    audio_path: Path,
    ass_path: Path,
    hook: str,
) -> Path:
    """
    Assemble final video with:
    - Rapid cuts (every 2-3s)
    - Ken Burns on images
    - Zoom pulses
    - Transitions
    - ASS captions burned in
    - Background ambient
    - Audio normalization
    """
    output_path = OUTPUT_DIR / f"ajeebology_short_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

    # Build FFmpeg filter complex
    filter_parts = []
    inputs = []

    # Input 0: audio
    inputs.extend(["-i", str(audio_path)])

    # Process each segment with its asset
    for i, (seg, asset) in enumerate(zip(segments, assets)):
        if not asset.path.exists():
            logger.warning(f"Asset missing for segment {i}, using fallback")
            asset = _generate_fallback_visual(i, seg.emotion)

        # Add asset as input
        inputs.extend(["-i", str(asset.path)])

        stream_idx = i + 1  # +1 because audio is input 0

        # Build video filter for this segment
        duration = seg.end_time - seg.start_time
        start_time = seg.start_time

        if asset.asset_type == "video":
            # Video clip: trim, scale, add subtle zoom
            filter_parts.append(
                f"[{stream_idx}:v]trim=start=0:duration={duration},"
                f"setpts=PTS-STARTPTS,"
                f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
                f"setsar=1:1,"
                f"zoompan=z='min(zoom+0.001,1.1)':d={int(duration*VIDEO_FPS)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT},"
                f"fade=t=out:st={duration-0.5}:d=0.5,"
                f"format=yuv420p[v{i}];"
            )
        else:
            # Image: Ken Burns effect (slow zoom + pan)
            zoom_start = 1.0
            zoom_end = 1.15
            pan_x = random.choice(["0", "(iw-ow)/2", "(iw-ow)"])
            pan_y = random.choice(["0", "(ih-oh)/2", "(ih-oh)"])

            filter_parts.append(
                f"[{stream_idx}:v]loop=loop={int(duration*VIDEO_FPS)}:size=1:start=0,"
                f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
                f"zoompan=z='if(lte(on,1),{zoom_start},min(pzoom+0.0015,{zoom_end}))':"
                f"x='if(lte(on,1),{pan_x},x+0.5)':"
                f"y='if(lte(on,1),{pan_y},y+0.3)':"
                f"d={int(duration*VIDEO_FPS)}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT},"
                f"fade=t=out:st={duration-0.5}:d=0.5,"
                f"format=yuv420p[v{i}];"
            )

    # Concatenate all video segments
    concat_inputs = "".join([f"[v{i}]" for i in range(len(segments))])
    filter_parts.append(
        f"{concat_inputs}concat=n={len(segments)}:v=1:a=0[outv];"
    )

    # Audio processing: normalize, add subtle compression
    filter_parts.append(
        f"[0:a]anormalize,"
        f"acompressor=threshold=-20dB:ratio=3:attack=5:release=100,"
        f"afade=t=in:st=0:d=0.5,"
        f"afade=t=out:st={segments[-1].end_time-1}:d=1[outa];"
    )

    # Add color grading (subtle saturation boost for retention)
    filter_parts.append(
        f"[outv]eq=brightness=0.02:contrast=1.1:saturation=1.15[graded];"
    )

    # Add subtle vignette
    filter_parts.append(
        f"[graded]vignette=PI/4[finalv];"
    )

    # Build full command
    filter_complex = "".join(filter_parts)
    # Remove trailing semicolon from last filter
    filter_complex = filter_complex.rstrip(";")

    cmd = inputs + [
        "-filter_complex", filter_complex,
        "-map", "[finalv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "medium",  # Balance quality/speed
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(VIDEO_FPS),
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]

    success, error = run_ffmpeg(cmd, timeout=600)
    if not success:
        raise RuntimeError(f"Video assembly failed: {error}")

    # Burn in captions separately (more reliable than complex filter)
    captioned_path = _burn_captions(output_path, ass_path)

    logger.info(f"Video assembled: {captioned_path}")
    return captioned_path


def _burn_captions(video_path: Path, ass_path: Path) -> Path:
    """Burn ASS captions into video."""
    output_path = OUTPUT_DIR / video_path.name.replace(".mp4", "_final.mp4")

    cmd = [
        "-i", str(video_path),
        "-vf", f"ass={str(ass_path)}",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-movflags", "+faststart",
        str(output_path),
    ]

    success, error = run_ffmpeg(cmd, timeout=300)
    if success:
        # Replace original with captioned version
        video_path.unlink(missing_ok=True)
        output_path.rename(video_path)
        return video_path
    else:
        logger.warning(f"Caption burn failed, using uncaptioned: {error}")
        return video_path


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 7: THUMBNAIL GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Thumbnail Generation")
def generate_thumbnail(hook: str, topic: str) -> Path:
    """
    Generate high-CTR thumbnail for YouTube Shorts.
    Features: Bold text, high contrast, emotional color, slight blur background.
    """
    thumb_path = OUTPUT_DIR / f"thumbnail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

    # Background: gradient based on topic
    bg_colors = {
        "psychology": [(74, 0, 224), (142, 45, 226)],
        "space": [(15, 32, 39), (32, 58, 67)],
        "weird_world": [(255, 81, 47), (221, 36, 118)],
    }
    c1, c2 = bg_colors.get(topic, [(0, 0, 0), (50, 50, 50)])

    # Create gradient background
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), c1)
    draw = ImageDraw.Draw(img)

    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    # Add subtle pattern overlay
    for i in range(0, VIDEO_WIDTH, 80):
        draw.line([(i, 0), (i, VIDEO_HEIGHT)], fill=(255, 255, 255, 20), width=2)

    # Try to load fonts
    try:
        # Try system fonts
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        font_large = None
        font_small = None

        for fp in font_paths:
            if Path(fp).exists():
                font_large = ImageFont.truetype(fp, 90)
                font_small = ImageFont.truetype(fp, 50)
                break

        if font_large is None:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Prepare text
    clean_hook = re.sub(r'[^\w\s]', '', hook).strip()
    words = clean_hook.split()

    # Split into 2-3 lines for readability
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        if len(" ".join(current_line)) > 18:
            lines.append(" ".join(current_line))
            current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    # Limit to 3 lines
    lines = lines[:3]

    # Draw text with outline for readability
    text_y = VIDEO_HEIGHT // 2 - (len(lines) * 100) // 2

    for line in lines:
        # Calculate text width for centering
        bbox = draw.textbbox((0, 0), line, font=font_large)
        text_width = bbox[2] - bbox[0]
        text_x = (VIDEO_WIDTH - text_width) // 2

        # Draw outline (black)
        outline_range = 4
        for dx in range(-outline_range, outline_range + 1):
            for dy in range(-outline_range, outline_range + 1):
                if dx*dx + dy*dy <= outline_range*outline_range:
                    draw.text((text_x + dx, text_y + dy), line, font=font_large, fill=(0, 0, 0))

        # Draw main text (white with slight yellow)
        draw.text((text_x, text_y), line, font=font_large, fill=(255, 255, 220))

        text_y += 110

    # Add "Ajeebology" branding at bottom
    brand_text = "AJEEBOLOGY SHORTS"
    bbox = draw.textbbox((0, 0), brand_text, font=font_small)
    brand_width = bbox[2] - bbox[0]
    brand_x = (VIDEO_WIDTH - brand_width) // 2

    # Brand outline
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            draw.text((brand_x + dx, VIDEO_HEIGHT - 150 + dy), brand_text, font=font_small, fill=(0, 0, 0))

    draw.text((brand_x, VIDEO_HEIGHT - 150), brand_text, font=font_small, fill=(255, 200, 50))

    # Add subtle glow effect
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

    # Save
    img.save(thumb_path, quality=95, optimize=True)

    logger.info(f"Thumbnail generated: {thumb_path}")
    return thumb_path


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 8: METADATA GENERATION (Groq)
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Metadata Generation")
def generate_metadata(script: str, hook: str, topic: str, sources: List[FactSource]) -> VideoMetadata:
    """
    Generate YouTube metadata: title, description, tags, hashtags.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    meta = VideoMetadata()

    # Title
    meta.title = _generate_title(groq_key, hook, topic)

    # Description
    meta.description = _generate_description(groq_key, script, topic)

    # Tags
    base_tags = ["shorts", "facts", "viral", "trending", "didyouknow"]
    topic_tags = {
        "psychology": ["psychology", "mind", "brain", "humanbehavior", "mentalhealth"],
        "space": ["space", "universe", "nasa", "galaxy", "astronomy"],
        "weird_world": ["weird", "strange", "unbelievable", "world", "mystery"],
    }
    meta.tags = base_tags + topic_tags.get(topic, [])

    # Hashtags
    meta.hashtags = [f"#{t}" for t in ["Shorts", "Facts", "Viral", topic.capitalize(), "Ajeebology"]]

    # Category
    meta.category = "Education"

    # Sources
    meta.sources = [f"{s.title} — {s.url}" for s in sources if s.url]

    # Thumbnail text
    meta.thumbnail_text = hook[:50]

    # Script
    meta.script = script

    return meta


def _generate_title(api_key: str, hook: str, topic: str) -> str:
    """Generate click-worthy title."""
    if not api_key:
        return f"Kya Tumhe Pata Hai? | {topic.title()} Facts | Ajeebology Shorts"

    prompt = f"""Create a viral YouTube Shorts title in Hinglish (max 60 chars).
Hook: {hook}
Topic: {topic}

Rules:
- Start with number or shocking word
- Use curiosity gap
- Add emoji
- Max 60 characters
- Language: Hinglish

Output ONLY the title. No quotes."""

    try:
        client = Groq(api_key=api_key)
        response = safe_api_call(
            client.chat.completions.create,
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=50,
        )
        if response and response.choices:
            title = response.choices[0].message.content.strip().strip('"').strip("'")
            return title[:100]
    except Exception as e:
        logger.error(f"Title generation failed: {e}")

    return f"😱 Kya Tumhe Yeh Pata Tha? | {topic.title()} Facts"


def _generate_description(api_key: str, script: str, topic: str) -> str:
    """Generate SEO-friendly description."""
    if not api_key:
        return (
            f"🎬 Ajeebology Shorts — Daily amazing facts in Hinglish!\n\n"
            f"Today's topic: {topic}\n\n"
            f"🔔 Subscribe for more mind-blowing facts!\n"
            f"👇 Comment your favorite fact below!"
        )

    prompt = f"""Write a YouTube Shorts description (max 300 chars) in Hinglish.
Topic: {topic}
Script preview: {script[:200]}

Include: Hook, CTA to subscribe, comment prompt.
Output ONLY the description."""

    try:
        client = Groq(api_key=api_key)
        response = safe_api_call(
            client.chat.completions.create,
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150,
        )
        if response and response.choices:
            return response.choices[0].message.content.strip()[:500]
    except Exception as e:
        logger.error(f"Description generation failed: {e}")

    return f"🎬 Ajeebology Shorts — {topic} facts that will blow your mind! 🔥"


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 9: TELEGRAM DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

@log_step("Telegram Delivery")
def send_to_telegram(
    video_path: Path,
    thumb_path: Path,
    metadata: VideoMetadata,
) -> bool:
    """
    Send complete package to Telegram with all metadata.
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials missing — skipping delivery")
        return False

    # Save metadata JSON
    meta_path = OUTPUT_DIR / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

    # Build caption
    sources_text = "\n".join([f"• {s}" for s in metadata.sources]) or "N/A"

    caption = f"""🎬 <b>{metadata.title}</b>

📝 <b>Description:</b>
{metadata.description}

🏷 <b>Tags:</b> {", ".join(metadata.tags)}

#️⃣ <b>Hashtags:</b> {" ".join(metadata.hashtags)}

📂 <b>Category:</b> {metadata.category}

📚 <b>Sources:</b>
{sources_text}

📊 <b>Runtime Stats:</b>
• Total time: {RUNTIME_STATS['total_seconds']:.1f}s
• API calls: {RUNTIME_STATS['api_calls']}
• Assets downloaded: {RUNTIME_STATS['assets_downloaded']}
• Steps: {json.dumps(RUNTIME_STATS['steps'], indent=2)}
"""

    # Send video
    try:
        video_url = f"https://api.telegram.org/bot{token}/sendVideo"
        with open(video_path, "rb") as vf:
            files = {"video": vf}
            data = {
                "chat_id": chat_id,
                "caption": caption[:1024],  # Telegram caption limit
                "parse_mode": "HTML",
                "supports_streaming": "true",
            }
            response = requests.post(video_url, data=data, files=files, timeout=120)
            RUNTIME_STATS["api_calls"] += 1

        if response.status_code != 200:
            logger.error(f"Telegram video send failed: {response.text}")
            return False

        # Send thumbnail as photo
        thumb_url = f"https://api.telegram.org/bot{token}/sendPhoto"
        with open(thumb_path, "rb") as tf:
            files = {"photo": tf}
            data = {
                "chat_id": chat_id,
                "caption": f"🖼 Thumbnail for: {metadata.title}",
                "parse_mode": "HTML",
            }
            response = requests.post(thumb_url, data=data, files=files, timeout=60)
            RUNTIME_STATS["api_calls"] += 1

        # Send metadata as document
        doc_url = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(meta_path, "rb") as df:
            files = {"document": df}
            data = {
                "chat_id": chat_id,
                "caption": "📄 Full metadata JSON",
                "parse_mode": "HTML",
            }
            response = requests.post(doc_url, data=data, files=files, timeout=60)
            RUNTIME_STATS["api_calls"] += 1

        logger.info("Telegram delivery complete")
        return True

    except Exception as e:
        logger.error(f"Telegram delivery failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

def select_topic() -> str:
    """Select topic based on schedule or random."""
    override = os.environ.get("TOPIC_OVERRIDE", "").strip().lower()
    if override in CONTENT_TOPICS:
        return override

    custom = os.environ.get("CUSTOM_PROMPT", "").strip()
    if custom:
        # Detect topic from custom prompt
        if any(w in custom.lower() for w in ["psychology", "mind", "brain"]):
            return "psychology"
        if any(w in custom.lower() for w in ["space", "planet", "star", "galaxy"]):
            return "space"
        return "weird_world"

    # Daily rotation
    day_of_week = datetime.now(timezone.utc).weekday()
    rotation = ["psychology", "space", "weird_world", "psychology", "space", "weird_world", "psychology"]
    return rotation[day_of_week]


def save_error_log():
    """Save error details for Telegram notification."""
    with open(ERROR_LOG, "w") as f:
        f.write(traceback.format_exc())


def main():
    """Main pipeline execution."""
    global RUNTIME_STATS

    try:
        logger.info("=" * 60)
        logger.info("  AJEEEBOLOGY SHORTS — AUTOMATED PIPELINE")
        logger.info("=" * 60)

        # Step 1: Select topic
        topic = select_topic()
        logger.info(f"Selected topic: {topic}")

        # Step 2: Research
        fact, sources = research_facts(topic)

        # Step 3: Generate script
        script, segments, hook = generate_script(topic, fact)

        # Step 4: Generate audio
        audio_path, segments = generate_audio(script, segments)

        # Step 5: Acquire visual assets
        assets = acquire_assets(segments, topic)

        # Step 6: Generate captions
        ass_path = generate_captions(segments, audio_path)

        # Step 7: Assemble video
        video_path = assemble_video(segments, assets, audio_path, ass_path, hook)

        # Step 8: Generate thumbnail
        thumb_path = generate_thumbnail(hook, topic)

        # Step 9: Generate metadata
        metadata = generate_metadata(script, hook, topic, sources)

        # Step 10: Finalize stats
        RUNTIME_STATS["total_seconds"] = round(time.time() - RUNTIME_STATS["start_time"], 2)

        # Step 11: Save metadata
        meta_path = OUTPUT_DIR / "metadata.json"
        metadata.runtime_stats = RUNTIME_STATS
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

        # Step 12: Telegram delivery
        send_to_telegram(video_path, thumb_path, metadata)

        # Step 13: Cleanup temp files
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR, ignore_errors=True)

        logger.info("=" * 60)
        logger.info("  PIPELINE COMPLETE ✅")
        logger.info(f"  Video: {video_path}")
        logger.info(f"  Thumbnail: {thumb_path}")
        logger.info(f"  Total time: {RUNTIME_STATS['total_seconds']:.1f}s")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"PIPELINE FAILED: {e}")
        save_error_log()

        # Attempt to notify Telegram of failure
        try:
            token = os.environ.get("TELEGRAM_TOKEN", "")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
            if token and chat_id:
                error_text = f"❌ <b>Pipeline Failed</b>\n\nError: {str(e)[:500]}\n\nCheck GitHub Actions logs."
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={"chat_id": chat_id, "text": error_text, "parse_mode": "HTML"},
                    timeout=30,
                )
        except Exception:
            pass

        return 1


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.exit(main())
