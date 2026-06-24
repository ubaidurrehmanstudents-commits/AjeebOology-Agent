#!/usr/bin/env python3
"""
Ajeebology Shorts — Fully Automated YouTube Shorts Pipeline
Single-file implementation for GitHub Actions Free Tier.
All functionality in one file. No external modules.
"""

# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================

import os
import sys
import io
import re
import json
import time
import math
import random
import hashlib
import textwrap
import asyncio
import logging
import traceback
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from urllib.parse import quote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from groq import Groq, AsyncGroq
from tavily import TavilyClient

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
import numpy as np

import edge_tts
from edge_tts import SubMaker, Communications

import mutagen
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from mutagen.id3 import ID3, APIC

# =============================================================================
# SECTION 2: CONFIGURATION
# =============================================================================


class Config:
    """Central configuration — loads from environment variables."""

    # API Keys
    GROQ_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    PEXELS_API_KEY: str = ""
    UNSPLASH_ACCESS_KEY: str = ""
    TELEGRAM_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Runtime config
    TOPIC: str = "random"
    VIDEO_COUNT: int = 1
    RUN_ID: str = ""
    RUN_ATTEMPT: str = ""

    # Video parameters
    VIDEO_WIDTH: int = 1080
    VIDEO_HEIGHT: int = 1920
    FPS: int = 30
    TARGET_DURATION_MIN: float = 55.0
    TARGET_DURATION_MAX: float = 65.0
    SCENE_CHANGE_INTERVAL: float = 2.5  # Something changes every ~2.5s
    WORDS_PER_SECOND: float = 2.4  # Hinglish speaking pace
    MIN_SCENE_DURATION: float = 1.5
    MAX_SCENE_DURATION: float = 4.0

    # Paths
    OUTPUT_DIR: str = "output"
    TEMP_DIR: str = "temp_media"

    # Retry config
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 2.0

    # Groq
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MAX_TOKENS: int = 1024
    GROQ_TEMPERATURE: float = 0.7

    # Tavily
    TAVILY_MAX_RESULTS: int = 10
    TAVILY_SEARCH_DEPTH: str = "basic"

    # Pexels
    PEXELS_VIDEOS_PER_PAGE: int = 5
    PEXELS_MIN_DURATION: int = 5

    # Telegram
    TELEGRAM_API_BASE: str = "https://api.telegram.org"
    TELEGRAM_TIMEOUT: int = 120

    # Duration checks
    MAX_TOTAL_PROCESSING_TIME: int = 1800  # 30 min safety

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment variables."""
        cfg = cls()

        cfg.GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
        cfg.TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
        cfg.PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
        cfg.UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
        cfg.TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
        cfg.TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

        cfg.TOPIC = os.environ.get("TOPIC", "random")
        try:
            cfg.VIDEO_COUNT = int(os.environ.get("VIDEO_COUNT", "1"))
        except (ValueError, TypeError):
            cfg.VIDEO_COUNT = 1
        cfg.RUN_ID = os.environ.get("RUN_ID", str(int(time.time())))
        cfg.RUN_ATTEMPT = os.environ.get("RUN_ATTEMPT", "1")

        # Validate required API keys
        missing = []
        if not cfg.GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        if not cfg.TAVILY_API_KEY:
            missing.append("TAVILY_API_KEY")
        if not cfg.PEXELS_API_KEY:
            missing.append("PEXELS_API_KEY")
        if not cfg.UNSPLASH_ACCESS_KEY:
            missing.append("UNSPLASH_ACCESS_KEY")
        if not cfg.TELEGRAM_TOKEN:
            missing.append("TELEGRAM_TOKEN")
        if not cfg.TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")

        if missing:
            logger.warning(f"Missing secrets: {', '.join(missing)}")
            logger.warning("Some features will be disabled.")

        # Create directories
        os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
        os.makedirs(cfg.TEMP_DIR, exist_ok=True)

        return cfg

    @property
    def topic_list(self) -> List[str]:
        """Return list of topics based on config."""
        if self.TOPIC and self.TOPIC != "random":
            return [self.TOPIC]
        return ["random"]

    @property
    def is_telegram_configured(self) -> bool:
        return bool(self.TELEGRAM_TOKEN and self.TELEGRAM_CHAT_ID)

    @property
    def short_size(self) -> Tuple[int, int]:
        return (self.VIDEO_WIDTH, self.VIDEO_HEIGHT)


# =============================================================================
# SECTION 3: LOGGING
# =============================================================================

# Create logger
logger = logging.getLogger("Ajeebology")
logger.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Format
formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File handler
log_file = None


def setup_file_logging(output_dir: str):
    """Add file logging to the output directory."""
    global log_file
    try:
        log_path = os.path.join(output_dir, f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        log_file = log_path
        logger.info(f"Logging to file: {log_path}")
    except Exception as e:
        logger.warning(f"Could not set up file logging: {e}")


# =============================================================================
# SECTION 4: UTILITY FUNCTIONS
# =============================================================================


def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Sanitize string for use as filename."""
    # Remove or replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r'\s+', "_", name)
    name = re.sub(r'_+', "_", name)
    name = name.strip("._")
    # Truncate
    if len(name) > max_len:
        name = name[:max_len]
    # Ensure not empty
    if not name:
        name = f"video_{int(time.time())}"
    return name


def safe_request(
    method: str,
    url: str,
    max_retries: int = 3,
    backoff: float = 2.0,
    **kwargs
) -> requests.Response:
    """Make HTTP request with retry logic and timeout."""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    kwargs.setdefault("timeout", 30)

    try:
        response = session.request(method, url, **kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed after {max_retries} retries: {e}")
        raise
    finally:
        session.close()


def download_file(url: str, dest_path: str, max_retries: int = 3) -> bool:
    """Download a file with retry logic."""
    for attempt in range(max_retries):
        try:
            resp = safe_request("GET", url, stream=True, timeout=60)
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            if total_size > 0 and downloaded < total_size:
                logger.warning(f"Download incomplete: {downloaded}/{total_size} bytes")
                if attempt < max_retries - 1:
                    continue

            logger.info(f"Downloaded {downloaded / 1024:.1f}KB -> {os.path.basename(dest_path)}")
            return True

        except Exception as e:
            logger.warning(f"Download attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(backoff)
            else:
                logger.error(f"Download failed after {max_retries} attempts: {url}")
                return False

    return False


def run_ffmpeg(args: List[str], timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess:
    """Run FFmpeg command with logging."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    cmd_str = " ".join(str(a) if " " not in str(a) else f'"{a}"' for a in cmd)
    logger.debug(f"FFmpeg: {cmd_str[:200]}...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and check:
            stderr = result.stderr[-500:] if result.stderr else ""
            logger.error(f"FFmpeg failed (rc={result.returncode}): {stderr}")
            raise RuntimeError(f"FFmpeg command failed: {stderr}")
        return result
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg timed out after {timeout}s")
        raise
    except FileNotFoundError:
        logger.error("FFmpeg not found. Is it installed?")
        raise


def run_ffprobe(args: List[str]) -> Dict[str, Any]:
    """Run ffprobe and return parsed JSON output."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
        return {}
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return {}


def get_media_duration(file_path: str) -> float:
    """Get duration of media file in seconds."""
    data = run_ffprobe(["-show_entries", "format=duration", file_path])
    try:
        return float(data.get("format", {}).get("duration", 0))
    except (ValueError, TypeError):
        return 0.0


def get_media_info(file_path: str) -> Dict[str, Any]:
    """Get detailed media info."""
    data = run_ffprobe(["-show_streams", "-show_format", file_path])
    streams = data.get("streams", [])
    info = {"duration": 0, "width": 0, "height": 0, "codec": "", "fps": 0}

    for stream in streams:
        if stream.get("codec_type") == "video":
            info["width"] = int(stream.get("width", 0))
            info["height"] = int(stream.get("height", 0))
            info["codec"] = stream.get("codec_name", "")
            fps_str = stream.get("avg_frame_rate", "0/1")
            if "/" in fps_str:
                try:
                    n, d = fps_str.split("/")
                    info["fps"] = float(n) / float(d) if float(d) > 0 else 0
                except (ValueError, ZeroDivisionError):
                    info["fps"] = 0
            break

    fmt = data.get("format", {})
    try:
        info["duration"] = float(fmt.get("duration", 0))
    except (ValueError, TypeError):
        info["duration"] = 0

    return info


def format_duration(seconds: float) -> str:
    """Format seconds to HH:MM:SS.mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


def backoff(attempt: int, base: float = 2.0, max_delay: float = 30.0) -> float:
    """Exponential backoff with jitter."""
    delay = min(base * (2 ** attempt), max_delay)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter


def clean_temp_files(temp_dir: str):
    """Remove temporary media files."""
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)
            logger.info(f"Cleaned temp directory: {temp_dir}")
    except Exception as e:
        logger.warning(f"Failed to clean temp dir: {e}")


# =============================================================================
# SECTION 5: DATA MODELS
# =============================================================================


@dataclass
class WordTimestamp:
    """Single word with its timing information."""
    word: str
    start: float  # seconds
    end: float    # seconds
    duration: float = 0.0

    def __post_init__(self):
        self.duration = self.end - self.start


@dataclass
class ScriptSegment:
    """A segment of the script with visual cues."""
    text: str
    words: List[WordTimestamp] = field(default_factory=list)
    visual_keywords: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    media_path: Optional[str] = None
    media_type: str = "video"  # "video" or "image"
    is_hook: bool = False  # First segment is the hook

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class VideoMetadata:
    """Generated metadata for YouTube upload."""
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    category: str = "Education"
    language: str = "hi"
    thumbnail_path: str = ""
    video_path: str = ""
    duration: float = 0.0
    file_size: int = 0
    sources: List[str] = field(default_factory=list)
    topic: str = ""
    generated_at: str = ""


@dataclass
class PipelineResult:
    """Result of the full pipeline run."""
    success: bool = False
    video_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    metadata: Optional[VideoMetadata] = None
    error: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)
    telegram_sent: bool = False


# =============================================================================
# SECTION 6: RESEARCH AGENT (Tavily API)
# =============================================================================


class ResearchAgent:
    """Research facts using Tavily API."""

    def __init__(self, config: Config):
        self.config = config
        self.client = TavilyClient(api_key=config.TAVILY_API_KEY) if config.TAVILY_API_KEY else None

    def get_facts(self, topic: str, count: int = 8) -> List[Dict[str, Any]]:
        """
        Search for interesting facts on the topic.
        Returns list of dicts with 'fact', 'source', 'keywords'.
        """
        logger.info(f"🔍 Researching topic: {topic}")

        if not self.client:
            logger.warning("Tavily not configured. Using fallback facts.")
            return self._fallback_facts(topic)

        # Build search queries based on topic
        queries = self._build_queries(topic)
        all_facts = []
        seen_facts = set()

        for query in queries:
            try:
                logger.info(f"  Searching: {query}")
                response = self.client.search(
                    query=query,
                    search_depth=self.config.TAVILY_SEARCH_DEPTH,
                    max_results=self.config.TAVILY_MAX_RESULTS,
                    include_answer=True,
                )

                # Extract facts from search results
                facts = self._extract_facts(response, query, seen_facts)
                all_facts.extend(facts)

                if len(all_facts) >= count:
                    break

                # Polite delay between searches
                time.sleep(0.5)

            except Exception as e:
                logger.warning(f"Tavily search failed for '{query}': {e}")
                continue

        logger.info(f"  Collected {len(all_facts)} unique facts")

        if not all_facts:
            logger.warning("No facts from Tavily. Using fallback.")
            return self._fallback_facts(topic)

        return all_facts[:count]

    def _build_queries(self, topic: str) -> List[str]:
        """Build search queries for the topic."""
        if topic == "psychology":
            return [
                "psychology facts about human behavior",
                "interesting psychology facts mind blowing",
                "psychology facts about brain and mind",
                "amazing psychology facts you didn't know",
            ]
        elif topic == "space":
            return [
                "amazing space facts NASA latest discoveries",
                "interesting facts about universe and planets",
                "space discoveries 2024 2025",
                "mind blowing facts about solar system",
            ]
        elif topic == "weird_world":
            return [
                "weird facts about world interesting",
                "strange facts about countries and cultures",
                "unbelievable facts about nature and animals",
                "weird science facts that sound fake",
            ]
        else:  # random
            topics = ["psychology", "space", "nature", "science", "history", "human body"]
            chosen = random.choice(topics)
            return self._build_queries(chosen)

    def _extract_facts(
        self, response: Any, query: str, seen: set
    ) -> List[Dict[str, Any]]:
        """Extract unique facts from Tavily response."""
        facts = []

        # Check for answer
        if hasattr(response, 'answer') and response.answer:
            answer = response.answer
            if isinstance(answer, str) and answer not in seen:
                seen.add(answer)
                facts.append({
                    "fact": answer,
                    "source": "tavily_summary",
                    "keywords": self._extract_keywords(answer),
                })

        # Check results
        results = []
        if hasattr(response, 'results'):
            results = response.results
        elif isinstance(response, dict):
            results = response.get('results', [])

        for result in results:
            if isinstance(result, dict):
                content = result.get('content', '') or result.get('snippet', '')
                url = result.get('url', '')
            else:
                content = getattr(result, 'content', '') or getattr(result, 'snippet', '')
                url = getattr(result, 'url', '')

            if not content or content in seen:
                continue

            # Extract shorter factual snippets
            sentences = re.split(r'(?<=[.!?])\s+', content)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 20 or len(sentence) > 300:
                    continue
                if sentence in seen:
                    continue
                seen.add(sentence)

                facts.append({
                    "fact": sentence,
                    "source": url or "tavily",
                    "keywords": self._extract_keywords(sentence),
                })

                if len(facts) >= 3:
                    break

        return facts

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Remove common words and keep meaningful terms
        common = {"the", "a", "an", "is", "are", "was", "were", "has", "have",
                   "had", "do", "does", "did", "will", "would", "could", "should",
                   "may", "might", "can", "shall", "to", "of", "in", "for", "on",
                   "with", "at", "by", "from", "as", "into", "through", "during",
                   "before", "after", "above", "below", "between", "this", "that",
                   "these", "those", "it", "its", "they", "them", "their", "we",
                   "you", "your", "our", "and", "or", "but", "not", "so", "if",
                   "because", "about", "than", "also", "very", "just", "more",
                   "some", "any", "each", "every", "both", "all", "most", "other",
                   "many", "much", "such", "no", "nor", "only", "own", "same",
                   "too", "very", "well", "even", "still", "already", "yet"}

        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in common]
        # Return unique keywords, up to 5
        seen = set()
        unique = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return unique[:5]

    def _fallback_facts(self, topic: str) -> List[Dict[str, Any]]:
        """Fallback facts when API is unavailable."""
        fallback_pool = {
            "psychology": [
                {"fact": "Your brain processes 70,000 thoughts every single day on average.", "source": "fallback", "keywords": ["brain", "thoughts", "daily"]},
                {"fact": "People who stay up late tend to be more creative than early risers.", "source": "fallback", "keywords": ["creativity", "sleep", "personality"]},
                {"fact": "The mere-exposure effect means you tend to like things just because you're familiar with them.", "source": "fallback", "keywords": ["familiarity", "liking", "psychology"]},
                {"fact": "Your brain can't multitask. It actually switches between tasks rapidly.", "source": "fallback", "keywords": ["multitasking", "brain", "focus"]},
                {"fact": "People are more honest when they're tired because mental exhaustion reduces impulse control.", "source": "fallback", "keywords": ["honesty", "tired", "impulse"]},
            ],
            "space": [
                {"fact": "A teaspoon of neutron star would weigh about 6 billion tons on Earth.", "source": "fallback", "keywords": ["neutron star", "gravity", "space"]},
                {"fact": "There's a cloud of alcohol in space called Sagittarius B2 that contains enough to make 400 trillion trillion pints of beer.", "source": "fallback", "keywords": ["space cloud", "alcohol", "sagittarius"]},
                {"fact": "Venus rotates backwards compared to most other planets in our solar system.", "source": "fallback", "keywords": ["venus", "rotation", "solar system"]},
                {"fact": "The largest known diamond in the universe is a white dwarf star named Lucy.", "source": "fallback", "keywords": ["diamond", "star", "white dwarf"]},
                {"fact": "A day on Venus is longer than a year on Venus. It takes 243 Earth days to rotate once.", "source": "fallback", "keywords": ["venus", "day", "year"]},
            ],
            "weird_world": [
                {"fact": "There's a species of jellyfish called Turritopsis dohrnii that is biologically immortal.", "source": "fallback", "keywords": ["jellyfish", "immortal", "biology"]},
                {"fact": "In Japan, there's a vending machine that sells fresh eggs.", "source": "fallback", "keywords": ["japan", "vending machine", "eggs"]},
                {"fact": "Octopuses have three hearts, and two of them stop beating when they swim.", "source": "fallback", "keywords": ["octopus", "hearts", "swimming"]},
                {"fact": "Bananas are berries, but strawberries aren't. Botanically speaking.", "source": "fallback", "keywords": ["banana", "berry", "botany"]},
                {"fact": "There's a town in Norway where it's illegal to die because the ground is too frozen for burials.", "source": "fallback", "keywords": ["norway", "illegal", "death"]},
            ],
        }

        if topic in fallback_pool:
            return fallback_pool[topic][:8]

        # Random mix
        mixed = []
        for t in ["psychology", "space", "weird_world"]:
            mixed.extend(fallback_pool[t][:3])
        random.shuffle(mixed)
        return mixed[:8]


# =============================================================================
# SECTION 7: SCRIPT GENERATION (Groq API)
# =============================================================================


class ScriptAgent:
    """Generate Hinglish script using Groq API."""

    def __init__(self, config: Config):
        self.config = config
        self.client = Groq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None

    def generate_script(self, facts: List[Dict[str, Any]], topic: str) -> Dict[str, Any]:
        """
        Generate a Hinglish script for 55-65 second Shorts video.

        Returns dict with:
          - 'full_text': complete Hinglish narration
          - 'segments': list of {text, keywords, is_hook}
          - 'title': video title
          - 'hook': opening hook sentence
          - 'cta': call to action
        """
        logger.info(f"📝 Generating script for {topic}")

        if not self.client:
            logger.warning("Groq not configured. Using fallback script.")
            return self._fallback_script(facts, topic)

        # Prepare facts summary for prompt
        facts_text = "\n".join([
            f"- {f['fact']}" for f in facts[:6]
        ])

        prompts = [
            self._build_system_prompt(),
            self._build_user_prompt(topic, facts_text),
        ]

        for attempt in range(self.config.MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.config.GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": prompts[0]},
                        {"role": "user", "content": prompts[1]},
                    ],
                    max_tokens=self.config.GROQ_MAX_TOKENS,
                    temperature=self.config.GROQ_TEMPERATURE,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from Groq")

                result = json.loads(content)
                self._validate_script_result(result)
                logger.info(f"  Script generated: {len(result.get('full_text', ''))} chars")
                return result

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"Attempt {attempt + 1}: Script parsing failed: {e}")
                if attempt < self.config.MAX_RETRIES - 1:
                    time.sleep(backoff(attempt))
                else:
                    logger.error("Script generation failed. Using fallback.")
                    return self._fallback_script(facts, topic)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}: Groq API error: {e}")
                if attempt < self.config.MAX_RETRIES - 1:
                    time.sleep(backoff(attempt))
                else:
                    logger.error("Groq API failed. Using fallback.")
                    return self._fallback_script(facts, topic)

        return self._fallback_script(facts, topic)

    def _build_system_prompt(self) -> str:
        """Build system prompt for script generation."""
        return """You are a professional YouTube Shorts script writer for the channel 'Ajeebology Shorts'.
Your scripts are in HINGLISH (Hindi + English mix) — the primary language is Hindi written in Devanagari script, mixed with English words naturally.

RULES:
1. Script must be 55-65 seconds at normal speaking pace (approximately 130-170 words total)
2. Start with a STRONG HOOK in the first 3 seconds
3. Every 2-3 seconds there should be a visual change
4. Use simple Hinglish that any Indian audience can understand
5. Include 3-4 interesting facts per video
6. End with a call to action (like, share, subscribe in Hinglish)
7. Keep sentences short and punchy — max 8-10 words per sentence
8. Use numbers and specific details for credibility
9. Add emotional triggers — surprise, curiosity, shock value

Output JSON format exactly:
{
  "hook": "Opening hook sentence in Hinglish (1 line)",
  "full_text": "Complete script with all punctuation. One sentence per line.",
  "segments": [
    {"text": "sentence 1", "keywords": ["keyword1", "keyword2"], "is_hook": true},
    {"text": "sentence 2", "keywords": ["keyword1", "keyword2"], "is_hook": false}
  ],
  "title": "Click-worthy title in Hinglish (max 60 chars)",
  "cta": "Call to action in Hinglish"
}"""

    def _build_user_prompt(self, topic: str, facts_text: str) -> str:
        """Build user prompt with facts."""
        topic_display = topic.replace("_", " ").title()
        return f"""Write a YouTube Shorts script for topic: {topic_display}

Here are the facts to incorporate:

{facts_text}

Create an engaging Hinglish script that makes these facts feel surprising and interesting. 
Remember: hook in first 3 seconds, visual change every 2-3 seconds, total duration 55-65 seconds.
Use Hinglish naturally — Hindi script (Devanagari) mixed with English words when natural.

Output as JSON with the exact format specified."""

    def _validate_script_result(self, result: Dict[str, Any]):
        """Validate script result structure."""
        required = ["full_text", "segments", "title", "hook"]
        for key in required:
            if key not in result:
                raise KeyError(f"Missing key in script result: {key}")

        if not isinstance(result["segments"], list):
            raise ValueError("Segments must be a list")

        if len(result["segments"]) < 3:
            raise ValueError("Need at least 3 segments")

    def _fallback_script(self, facts: List[Dict[str, Any]], topic: str) -> Dict[str, Any]:
        """Generate fallback script when API is unavailable."""
        # Build simple script from facts
        fact_texts = [f["fact"] for f in facts[:4]]

        segments = []
        for i, fact in enumerate(fact_texts):
            segments.append({
                "text": fact,
                "keywords": facts[i].get("keywords", ["facts"]),
                "is_hook": i == 0,
            })

        full_text = "\n".join(fact_texts)
        hook = fact_texts[0] if fact_texts else "Amazing fact for you!"

        return {
            "hook": hook,
            "full_text": full_text,
            "segments": segments,
            "title": f"Ajeebology Shorts - {topic.replace('_', ' ').title()} Facts",
            "cta": "Agar aapko yeh fact pasand aaya toh like karein aur channel ko subscribe karein!",
        }
