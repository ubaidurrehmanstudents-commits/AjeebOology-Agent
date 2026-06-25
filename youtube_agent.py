#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AJEEBOLOGY SHORTS — Automated YouTube Shorts Production Pipeline
Single-file implementation. No external modules.
"""

import os
import sys
import json
import time
import random
import argparse
import tempfile
import subprocess
import textwrap
import re
import math
import hashlib
import warnings
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from urllib.parse import urlencode, urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np

warnings.filterwarnings("ignore")

# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

TARGET_DURATION = 60
MIN_DURATION = 55
MAX_DURATION = 65
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
VIDEO_BITRATE = "4M"
AUDIO_SAMPLE_RATE = 24000

TOPICS = {
    "psychology": [
        "cognitive biases", "body language secrets", "dream interpretation",
        "stress response", "memory tricks", "social proof", "confirmation bias",
        "Dunning-Kruger effect", "imposter syndrome", "love languages",
        "micro-expressions", "placebo effect", "bystander effect",
        "Stockholm syndrome", "Pygmalion effect", "spotlight effect",
        "Zeigarnik effect", "mere exposure effect", "anchoring bias",
        "sunk cost fallacy", "paradox of choice", "fundamental attribution error"
    ],
    "space": [
        "black holes", "dark matter", "neutron stars", "exoplanets",
        "supernovae", "galaxy collisions", "cosmic microwave background",
        "gravitational waves", "time dilation", "wormholes", "multiverse theory",
        "Oumuamua", "Titan lakes", "Europa ocean", "Venus clouds",
        "Mars dust storms", "Jupiter Great Red Spot", "Saturn hexagon",
        "pulsar precision", "quasar brightness", "rogue planets",
        "space vacuum effects", "cosmic rays", "asteroid mining"
    ],
    "weird_world": [
        "underwater rivers", "bioluminescent beaches", "sailing stones",
        "blood falls Antarctica", "door to hell Turkmenistan", "underwater crop circles",
        "spotted lake Canada", "pink lake Senegal", "hidden beach Mexico",
        "catacombs Paris", "island of dolls", "Christ of the Abyss",
        "underwater waterfall illusion", "frozen methane bubbles",
        "rainbow mountains", "giant crystal cave", "Devil's kettle",
        "boiling river Amazon", "stone forest Madagascar", "wave rock Australia",
        "moeraki boulders", "fairy circles Namibia", "skeleton coast"
    ]
}

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_AUDIO_URL = "https://api.groq.com/openai/v1/audio/speech"
TAVILY_API_URL = "https://api.tavily.com/search"
PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}"

MAX_RETRIES = 3
RETRY_DELAY = 2

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# ═════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class CaptionWord:
    word: str
    start: float
    end: float

@dataclass
class ResearchSource:
    title: str
    url: str

@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: List[str]
    hashtags: List[str]
    category: str
    duration: float
    file_size_mb: float
    video_filename: str
    thumbnail_filename: str
    sources: List[Dict[str, str]]
    timestamp: str
    script_text: str
    topic: str

# ═════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def retry_request(func, max_retries: int = MAX_RETRIES, delay: int = RETRY_DELAY):
    def wrapper(*args, **kwargs):
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                wait = delay * (2 ** attempt)
                log(f"Retry {attempt + 1}/{max_retries}: {e}. Waiting {wait}s...", "WARN")
                time.sleep(wait)
        return None
    return wrapper

def get_font_path(bold: bool = True) -> str:
    candidates = FONT_PATHS if bold else [f.replace("Bold", "") for f in FONT_PATHS]
    for path in candidates:
        if os.path.exists(path):
            return path
    for root, dirs, files in os.walk("/usr/share/fonts"):
        for f in files:
            if f.endswith((".ttf", ".ttc", ".otf")):
                if bold and "bold" in f.lower():
                    return os.path.join(root, f)
                elif not bold:
                    return os.path.join(root, f)
    raise RuntimeError("No suitable font found")

def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')[:50]

def run_ffmpeg(cmd: List[str], description: str = "FFmpeg") -> None:
    full_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + cmd
    log(f"Running: {' '.join(full_cmd[:15])}...", "DEBUG")
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"FFmpeg stderr: {result.stderr[:500]}", "ERROR")
        raise RuntimeError(f"{description} failed: {result.stderr[:200]}")
    log(f"{description} OK")

def get_duration(path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0

def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

# ═════════════════════════════════════════════════════════════════════════════
# API CLIENTS
# ═════════════════════════════════════════════════════════════════════════════

class GroqClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    @retry_request
    def chat(self, messages: List[Dict], model: str = "llama-3.3-70b-versatile",
             temperature: float = 0.7, max_tokens: int = 2048, json_mode: bool = False) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = requests.post(GROQ_API_URL, headers=self.headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @retry_request
    def generate_speech(self, text: str, output_path: str, voice: str = "Arista-PlayAI") -> str:
        payload = {
            "model": "playai-tts",
            "voice": voice,
            "input": text,
            "response_format": "mp3"
        }
        resp = requests.post(GROQ_AUDIO_URL, headers=self.headers, json=payload, timeout=120)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)
        log(f"TTS saved: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

class TavilyClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    @retry_request
    def search(self, query: str, max_results: int = 5) -> List[ResearchSource]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False
        }
        resp = requests.post(TAVILY_API_URL, json=payload, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        sources = []
        for r in results:
            sources.append(ResearchSource(
                title=r.get("title", "Unknown")[:100],
                url=r.get("url", "")
            ))
        log(f"Tavily: {len(sources)} sources for '{query[:40]}...'")
        return sources

class PexelsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Authorization": api_key}

    @retry_request
    def search_videos(self, query: str, per_page: int = 10, orientation: str = "portrait") -> List[Dict]:
        params = {"query": query, "per_page": per_page, "orientation": orientation}
        resp = requests.get(PEXELS_VIDEO_URL, headers=self.headers, params=params, timeout=30)
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
        log(f"Pexels: {len(videos)} videos for '{query[:40]}...'")
        return videos

    def download_video(self, video_url: str, output_path: str) -> str:
        resp = requests.get(video_url, timeout=60, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        log(f"Downloaded video: {output_path}")
        return output_path

class UnsplashClient:
    def __init__(self, access_key: str):
        self.access_key = access_key
        self.headers = {"Authorization": f"Client-ID {access_key}"}

    @retry_request
    def search_photos(self, query: str, per_page: int = 10, orientation: str = "portrait") -> List[Dict]:
        params = {"query": query, "per_page": per_page, "orientation": orientation}
        resp = requests.get(UNSPLASH_SEARCH_URL, headers=self.headers, params=params, timeout=30)
        resp.raise_for_status()
        photos = resp.json().get("results", [])
        log(f"Unsplash: {len(photos)} photos for '{query[:40]}...'")
        return photos

    def download_photo(self, photo: Dict, output_path: str) -> str:
        download_url = photo.get("links", {}).get("download_location", "")
        if download_url:
            try:
                requests.get(download_url, headers=self.headers, timeout=10)
            except Exception:
                pass
        img_url = photo.get("urls", {}).get("regular", photo.get("urls", {}).get("small", ""))
        if not img_url:
            raise RuntimeError("No image URL found")
        resp = requests.get(img_url, timeout=60, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        log(f"Downloaded photo: {output_path}")
        return output_path


# ═════════════════════════════════════════════════════════════════════════════
# CONTENT GENERATION
# ═════════════════════════════════════════════════════════════════════════════

class ContentGenerator:
    def __init__(self, groq: GroqClient, tavily: TavilyClient):
        self.groq = groq
        self.tavily = tavily

    def select_topic(self, category: str) -> Tuple[str, str]:
        if category == "random":
            category = random.choice(list(TOPICS.keys()))
        topic = random.choice(TOPICS[category])
        log(f"Topic: {topic} (category: {category})")
        return category, topic

    def generate_script(self, topic: str, category: str) -> Tuple[str, List[CaptionWord], float]:
        system_prompt = """You are an expert YouTube Shorts scriptwriter for "Ajeebology Shorts".
Scripts are in Hinglish (Roman Urdu/Hindi mixed with English).
Rules:
- Hook in first 3 seconds
- Each sentence under 12 words
- Conversational: "Aapko pata hai...", "Imagine karo...", "Shocking hai na?"
- 1-2 rhetorical questions
- End with CTA: "Comment karo", "Share karo", "Follow for more"
- Total script readable in 50-58 seconds at natural pace
- Output ONLY the script text, no explanations, no quotes around it"""

        user_prompt = f"Write a 50-58 second Hinglish script about: {topic}\nCategory: {category}\nTarget: Pakistani/Indian youth aged 18-30.\nMake it addictive, fact-packed, retention-optimized."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        script = self.groq.chat(messages, temperature=0.8, max_tokens=800)
        script = script.strip().strip('"').strip("'")
        script = re.sub(r'\n+', ' ', script)
        script = re.sub(r'\s+', ' ', script).strip()

        words = script.split()
        wpm = 150
        spw = 60.0 / wpm
        word_timings = []
        current_time = 0.0

        for word in words:
            duration = spw * random.uniform(0.8, 1.2)
            word_timings.append(CaptionWord(
                word=word,
                start=current_time,
                end=current_time + duration
            ))
            current_time += duration

        estimated = current_time
        log(f"Script: {len(words)} words, ~{estimated:.1f}s")
        return script, word_timings, estimated

    def research_topic(self, topic: str) -> List[ResearchSource]:
        query = f"{topic} facts psychology science research"
        try:
            return self.tavily.search(query, max_results=5)
        except Exception as e:
            log(f"Research failed: {e}", "WARN")
            return [ResearchSource(title=f"Wikipedia: {topic}", url=f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}")]
    def generate_tts(self, script: str, output_dir: str) -> str:
        audio_path = os.path.join(output_dir, "voiceover.mp3")
        
        # Try Groq TTS first
        try:
            self.groq.generate_speech(script, audio_path, voice="Arabella")
            duration = get_duration(audio_path)
            log(f"TTS duration: {duration:.1f}s")
            if duration >= MIN_DURATION:
                return audio_path
            log("Groq TTS too short, trying fallback", "WARN")
        except Exception as e:
            log(f"Groq TTS failed: {e}, using fallback", "WARN")
        
        # Fallback: gTTS (Google TTS, free, no API key)
        try:
            from gtts import gTTS
            tts = gTTS(text=script, lang='en', slow=False)
            tts.save(audio_path)
            duration = get_duration(audio_path)
            log(f"gTTS duration: {duration:.1f}s")
            if duration < MIN_DURATION or duration > MAX_DURATION:
                log(f"WARNING: Audio {duration:.1f}s outside range", "WARN")
            return audio_path
        except Exception as e:
            log(f"gTTS also failed: {e}", "ERROR")
            raise
            
            
            
            

    def generate_title(self, topic: str, script: str) -> str:
        system_prompt = """You are a YouTube Shorts title expert.
Create a SHORT, click-worthy title in Hinglish or English.
Rules:
- Max 60 characters
- Use numbers, power words, or curiosity gaps
- No clickbait that disappoints
- Examples: "Ye Fact Aapko Hila Dege!", "99% Log Ye Nahi Jante", "Brain Ka Ye Secret..."
Output ONLY the title, nothing else."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Topic: {topic}\nScript: {script[:200]}..."}
        ]

        title = self.groq.chat(messages, temperature=0.9, max_tokens=100)
        title = title.strip().strip('"').strip("'")[:60]
        log(f"Title: {title}")
        return title

    def generate_description(self, title: str, topic: str) -> str:
        return f"""{title}

Ajeebology Shorts par aapko milti hain psychology, space, aur weird world ki most amazing facts — short, crisp, aur addictive format mein! 🧠🚀🌍

Har video mein ek nayi curiosity, ek naya perspective. Agar aapko knowledge pasand hai aur aap chhote format mein bada impact chahte hain, toh ye channel aapke liye hai!

🔔 Har roz naye facts ke liye follow karein!
💬 Apna favorite fact comments mein batayein!

#Ajeebology #Shorts #Facts #Knowledge"""

    def generate_tags(self, topic: str, category: str) -> List[str]:
        base = [
            "shorts", "youtube shorts", "facts", "amazing facts",
            "knowledge", "education", "hinglish", "pakistan", "india",
            "viral shorts", "trending", "did you know"
        ]
        cat_tags = {
            "psychology": ["psychology facts", "mind tricks", "brain facts", "human behavior", "mental health"],
            "space": ["space facts", "universe", "nasa", "astronomy", "cosmos", "galaxy"],
            "weird_world": ["weird facts", "strange places", "mystery", "unexplained", "bizarre"]
        }
        topic_tags = [topic, topic + " facts", topic.replace(" ", "")]
        return list(set(base + cat_tags.get(category, []) + topic_tags))[:15]

    def generate_hashtags(self, topic: str, category: str) -> List[str]:
        tags = ["#Ajeebology", "#Shorts", "#Facts", "#Knowledge", "#Viral"]
        if category == "psychology":
            tags += ["#Psychology", "#MindTricks", "#BrainFacts", "#HumanBehavior"]
        elif category == "space":
            tags += ["#Space", "#Universe", "#NASA", "#Cosmos", "#Astronomy"]
        else:
            tags += ["#WeirdWorld", "#Strange", "#Mystery", "#Bizarre", "#Unexplained"]
        tags.append(f"#{topic.replace(' ', '').replace('-', '')}")
        return tags[:8]

# ═════════════════════════════════════════════════════════════════════════════
# ASSET MANAGER
# ═════════════════════════════════════════════════════════════════════════════

class AssetManager:
    def __init__(self, pexels: PexelsClient, unsplash: UnsplashClient, cache_dir: str):
        self.pexels = pexels
        self.unsplash = unsplash
        self.cache_dir = ensure_dir(cache_dir)

    def _cache_path(self, prefix: str, identifier: str, ext: str) -> str:
        h = hashlib.md5(identifier.encode()).hexdigest()[:12]
        return os.path.join(self.cache_dir, f"{prefix}_{h}.{ext}")

    def download_video_clips(self, topic: str, count: int = 5, min_duration: float = 3.0) -> List[str]:
        queries = [
            topic,
            f"{topic} close up",
            f"{topic} cinematic",
            f"{topic} abstract",
            f"{topic} slow motion"
        ]

        downloaded = []
        used_urls = set()

        for query in queries[:count]:
            if len(downloaded) >= count:
                break
            try:
                videos = self.pexels.search_videos(query, per_page=5)
                for video in videos:
                    if len(downloaded) >= count:
                        break

                    video_files = video.get("video_files", [])
                    best_file = None

                    for vf in video_files:
                        if vf.get("width", 0) == VIDEO_WIDTH and vf.get("height", 0) == VIDEO_HEIGHT:
                            best_file = vf
                            break

                    if not best_file:
                        for vf in video_files:
                            w, h = vf.get("width", 0), vf.get("height", 0)
                            if h > w and h >= 1080:
                                best_file = vf
                                break

                    if not best_file:
                        best_file = video_files[0] if video_files else None

                    if not best_file:
                        continue

                    url = best_file.get("link", "")
                    if url in used_urls:
                        continue

                    vid_duration = video.get("duration", 0)
                    if vid_duration < min_duration:
                        continue

                    cache_path = self._cache_path("vid", url, "mp4")

                    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10000:
                        log(f"Using cached: {cache_path}")
                        downloaded.append(cache_path)
                        used_urls.add(url)
                        continue

                    try:
                        self.pexels.download_video(url, cache_path)
                        dur = get_duration(cache_path)
                        if dur > 0:
                            downloaded.append(cache_path)
                            used_urls.add(url)
                            log(f"Downloaded clip {len(downloaded)}/{count}: {dur:.1f}s")
                    except Exception as e:
                        log(f"Clip download failed: {e}", "WARN")
                        continue
            except Exception as e:
                log(f"Search failed for '{query}': {e}", "WARN")
                continue

        log(f"Total clips: {len(downloaded)}")
        return downloaded

    def download_thumbnail_image(self, topic: str, category: str) -> str:
        queries = [
            f"{topic} dramatic",
            f"{topic} cinematic dark",
            f"{topic} professional"
        ]

        for query in queries:
            try:
                photos = self.unsplash.search_photos(query, per_page=5)
                for photo in photos:
                    cache_path = self._cache_path("thumb", photo.get("id", query), "jpg")
                    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 10000:
                        log(f"Using cached thumb: {cache_path}")
                        return cache_path
                    try:
                        self.unsplash.download_photo(photo, cache_path)
                        if os.path.getsize(cache_path) > 10000:
                            log(f"Downloaded thumb: {cache_path}")
                            return cache_path
                    except Exception as e:
                        log(f"Photo download failed: {e}", "WARN")
                        continue
            except Exception as e:
                log(f"Unsplash search failed: {e}", "WARN")
                continue

        fallback = os.path.join(self.cache_dir, "fallback_thumb.jpg")
        img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), color=(20, 20, 40))
        img.save(fallback, quality=95)
        log(f"Using fallback thumb: {fallback}")
        return fallback


# ═════════════════════════════════════════════════════════════════════════════
# VIDEO PROCESSOR
# ═════════════════════════════════════════════════════════════════════════════

class VideoProcessor:
    def __init__(self, output_dir: str):
        self.output_dir = ensure_dir(output_dir)
        self.temp_dir = ensure_dir(os.path.join(output_dir, "temp"))

    def _temp(self, name: str) -> str:
        return os.path.join(self.temp_dir, name)

    def prepare_clip(self, input_path: str, target_duration: float, effect: str = "ken_burns") -> str:
        output_path = self._temp(f"clip_{os.path.basename(input_path)}")

        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json", input_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)

        try:
            probe_data = json.loads(probe_result.stdout)
            stream = probe_data.get("streams", [{}])[0]
            src_w = int(stream.get("width", 1920))
            src_h = int(stream.get("height", 1080))
            src_dur = float(stream.get("duration", 10))
        except (json.JSONDecodeError, ValueError, KeyError):
            src_w, src_h, src_dur = 1920, 1080, 10

        target_aspect = VIDEO_WIDTH / VIDEO_HEIGHT
        filters = []

        if src_w / src_h > target_aspect:
            new_w = int(src_h * target_aspect)
            filters.append(f"crop={new_w}:{src_h}:(iw-{new_w})/2:0")
            filters.append(f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}")
        else:
            new_h = int(src_w / target_aspect)
            filters.append(f"crop={src_w}:{new_h}:0:(ih-{new_h})/2")
            filters.append(f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}")

        total_frames = int(target_duration * VIDEO_FPS)

        if effect == "ken_burns":
            filters.append(
                f"zoompan=z='min(zoom+0.0015,1.5)':d={total_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
            )
        elif effect == "zoom_in":
            filters.append(
                f"zoompan=z='min(zoom+0.003,1.4)':d={total_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
            )
        elif effect == "zoom_out":
            filters.append(
                f"zoompan=z='max(1.3-zoom*0.003,1.0)':d={total_frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
            )
        elif effect == "pan_left":
            filters.append(
                f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:'(iw-{VIDEO_WIDTH})-((iw-{VIDEO_WIDTH})*t/{target_duration})':0"
            )
        elif effect == "pan_right":
            filters.append(
                f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:'((iw-{VIDEO_WIDTH})*t/{target_duration})':0"
            )

        filters.append("eq=contrast=1.1:saturation=1.15:brightness=0.02")
        filter_str = ",".join(filters)
        trim_dur = min(target_duration, src_dur * 0.9)

        cmd = [
            "-i", input_path,
            "-t", str(trim_dur),
            "-vf", filter_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            "-r", str(VIDEO_FPS),
            output_path
        ]

        run_ffmpeg(cmd, f"Prepare clip ({effect})")
        return output_path

    def prepare_all_clips(self, clip_paths: List[str], segment_duration: float) -> List[str]:
        effects = ["ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right", "none"]
        prepared = []
        for i, path in enumerate(clip_paths):
            effect = effects[i % len(effects)]
            try:
                prepared_path = self.prepare_clip(path, segment_duration, effect)
                prepared.append(prepared_path)
            except Exception as e:
                log(f"Failed clip {i}: {e}", "WARN")
        return prepared

# ═════════════════════════════════════════════════════════════════════════════
# CAPTION ENGINE
# ═════════════════════════════════════════════════════════════════════════════

class CaptionEngine:
    def __init__(self):
        self.font_path = get_font_path(bold=True)
        self.font_path_regular = get_font_path(bold=False)

    def generate_caption_video(self, word_timings: List[CaptionWord],
                               total_duration: float, output_dir: str) -> str:
        ensure_dir(output_dir)
        total_frames = int(total_duration * VIDEO_FPS)

        font_size = 72
        max_width = VIDEO_WIDTH - 120
        line_height = 90

        # Group words into phrases
        phrase_groups = []
        current_group = []
        current_width = 0

        for wt in word_timings:
            word = wt.word
            word_width = len(word) * font_size * 0.6
            if current_width + word_width > max_width and current_group:
                phrase_groups.append(current_group)
                current_group = [wt]
                current_width = word_width
            else:
                current_group.append(wt)
                current_width += word_width + font_size * 0.3

        if current_group:
            phrase_groups.append(current_group)

        log(f"Caption phrases: {len(phrase_groups)}")

        frame_paths = []

        try:
            font = ImageFont.truetype(self.font_path, font_size)
            font_highlight = ImageFont.truetype(self.font_path, font_size + 4)
        except Exception:
            font = ImageFont.load_default()
            font_highlight = font

        for frame_num in range(total_frames):
            current_time = frame_num / VIDEO_FPS

            active_phrase_idx = 0
            for i, group in enumerate(phrase_groups):
                if group and group[0].start <= current_time:
                    active_phrase_idx = i

            if active_phrase_idx >= len(phrase_groups):
                active_phrase_idx = max(0, len(phrase_groups) - 1)

            active_group = phrase_groups[active_phrase_idx] if phrase_groups else []

            img = Image.new('RGBA', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            if active_group:
                lines = []
                current_line = []
                current_line_width = 0

                for wt in active_group:
                    word = wt.word
                    word_w = len(word) * font_size * 0.55
                    if current_line_width + word_w > max_width and current_line:
                        lines.append(current_line)
                        current_line = [(word, wt)]
                        current_line_width = word_w
                    else:
                        current_line.append((word, wt))
                        current_line_width += word_w + font_size * 0.25

                if current_line:
                    lines.append(current_line)

                lines = lines[:2]
                total_text_height = len(lines) * line_height
                start_y = VIDEO_HEIGHT - 280 - total_text_height // 2

                for line_idx, line in enumerate(lines):
                    line_width = sum(len(w) * font_size * 0.55 for w, _ in line)
                    line_width += (len(line) - 1) * font_size * 0.25
                    start_x = (VIDEO_WIDTH - line_width) // 2
                    x = start_x
                    y = start_y + line_idx * line_height

                    for word, wt in line:
                        is_active = wt.start <= current_time <= wt.end + 0.15

                        # Shadow
                        for dx in range(-2, 3):
                            for dy in range(-2, 3):
                                draw.text((x + dx, y + dy), word,
                                         font=font_highlight if is_active else font,
                                         fill=(0, 0, 0, 180))

                        if is_active:
                            draw.text((x, y), word, font=font_highlight,
                                     fill=(255, 220, 50, 255))
                            draw.text((x - 1, y - 1), word, font=font_highlight,
                                     fill=(255, 240, 100, 100))
                        else:
                            draw.text((x, y), word, font=font,
                                     fill=(255, 255, 255, 255))

                        x += len(word) * font_size * 0.55 + font_size * 0.25

            frame_path = os.path.join(output_dir, f"cap_{frame_num:06d}.png")
            img.save(frame_path)
            frame_paths.append(frame_path)

            if frame_num % (VIDEO_FPS * 5) == 0:
                log(f"Caption frame {frame_num}/{total_frames}")

        # Compile frames to video
        caption_video = os.path.join(output_dir, "captions.mp4")
        cmd = [
            "-framerate", str(VIDEO_FPS),
            "-i", os.path.join(output_dir, "cap_%06d.png"),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-r", str(VIDEO_FPS),
            caption_video
        ]
        run_ffmpeg(cmd, "Compile captions")

        # Cleanup frames
        for fp in frame_paths:
            try:
                os.remove(fp)
            except Exception:
                pass

        log(f"Caption video: {caption_video}")
        return caption_video


# ═════════════════════════════════════════════════════════════════════════════
# VIDEO ASSEMBLER
# ═════════════════════════════════════════════════════════════════════════════

class VideoAssembler:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.temp_dir = ensure_dir(os.path.join(output_dir, "temp"))

    def _temp(self, name: str) -> str:
        return os.path.join(self.temp_dir, name)

    def concatenate_clips(self, clip_paths: List[str], target_duration: float) -> str:
        if not clip_paths:
            raise RuntimeError("No clips to concatenate")

        if len(clip_paths) == 1:
            output = self._temp("concatenated.mp4")
            cmd = [
                "-i", clip_paths[0],
                "-t", str(target_duration),
                "-c", "copy",
                output
            ]
            run_ffmpeg(cmd, "Copy single clip")
            return output

        normalized = []
        for i, path in enumerate(clip_paths):
            norm_path = self._temp(f"norm_{i}.mp4")
            cmd = [
                "-i", path,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",
                "-r", str(VIDEO_FPS),
                norm_path
            ]
            run_ffmpeg(cmd, f"Normalize clip {i}")
            normalized.append(norm_path)

        concat_file = self._temp("concat_list.txt")
        with open(concat_file, "w") as f:
            for path in normalized:
                f.write(f"file '{os.path.abspath(path)}'\n")

        output = self._temp("concatenated.mp4")
        cmd = [
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output
        ]
        run_ffmpeg(cmd, "Concatenate clips")

        final_output = self._temp("trimmed.mp4")
        cmd = [
            "-i", output,
            "-t", str(target_duration),
            "-c", "copy",
            final_output
        ]
        run_ffmpeg(cmd, "Trim to target")
        return final_output

    def add_audio(self, video_path: str, audio_path: str, output_path: str) -> str:
        video_dur = get_duration(video_path)
        audio_dur = get_duration(audio_path)

        if abs(video_dur - audio_dur) > 1.0:
            log(f"Duration mismatch: v={video_dur:.1f}s a={audio_dur:.1f}s", "WARN")

        cmd = [
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-shortest",
            output_path
        ]
        run_ffmpeg(cmd, "Add audio")
        return output_path

    def overlay_captions(self, video_path: str, caption_video_path: str, output_path: str) -> str:
        cmd = [
            "-i", video_path,
            "-i", caption_video_path,
            "-filter_complex",
            "[0:v][1:v]overlay=0:0[outv]",
            "-map", "[outv]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-c:a", "copy",
            output_path
        ]
        run_ffmpeg(cmd, "Overlay captions")
        return output_path

    def add_background_music(self, video_path: str, output_path: str) -> str:
        ambient_path = self._temp("ambient.mp3")
        duration = get_duration(video_path)

        cmd = [
            "-f", "lavfi",
            "-i", f"anoisesrc=a=0.015:c=pink:d={duration}",
            "-af", f"lowpass=f=800,afade=t=in:ss=0:d=2,afade=t=out:st={max(0, duration - 3)}:d=3",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            ambient_path
        ]

        try:
            run_ffmpeg(cmd, "Generate ambient")
        except RuntimeError:
            log("Ambient failed, skipping music", "WARN")
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        cmd = [
            "-i", video_path,
            "-i", ambient_path,
            "-filter_complex",
            "[1:a]volume=0.08[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]
        run_ffmpeg(cmd, "Mix ambient")
        return output_path

    def add_intro_outro(self, video_path: str, title: str, output_path: str) -> str:
        duration = get_duration(video_path)
        intro_duration = 1.5

        # Intro
        intro_img = self._temp("intro.png")
        img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), (10, 10, 25))
        draw = ImageDraw.Draw(img)

        try:
            big_font = ImageFont.truetype(get_font_path(bold=True), 120)
            small_font = ImageFont.truetype(get_font_path(bold=False), 48)
        except Exception:
            big_font = ImageFont.load_default()
            small_font = big_font

        text = "AJEEBOLOGY"
        bbox = draw.textbbox((0, 0), text, font=big_font)
        text_w = bbox[2] - bbox[0]
        draw.text(((VIDEO_WIDTH - text_w) // 2, VIDEO_HEIGHT // 2 - 80), text,
                 font=big_font, fill=(255, 220, 50))

        sub = "Shorts • Facts • Knowledge"
        bbox2 = draw.textbbox((0, 0), sub, font=small_font)
        sub_w = bbox2[2] - bbox2[0]
        draw.text(((VIDEO_WIDTH - sub_w) // 2, VIDEO_HEIGHT // 2 + 60), sub,
                 font=small_font, fill=(200, 200, 200))

        img.save(intro_img, quality=95)

        intro_video = self._temp("intro.mp4")
        cmd = [
            "-loop", "1",
            "-i", intro_img,
            "-t", str(intro_duration),
            "-vf", "fade=t=out:st=1.0:d=0.5",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-r", str(VIDEO_FPS),
            intro_video
        ]
        run_ffmpeg(cmd, "Generate intro")

        # Outro
        outro_duration = 2.0
        outro_img = self._temp("outro.png")
        img2 = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), (10, 10, 25))
        draw2 = ImageDraw.Draw(img2)

        text2 = "Like • Share • Subscribe"
        bbox3 = draw2.textbbox((0, 0), text2, font=big_font)
        text2_w = bbox3[2] - bbox3[0]
        draw2.text(((VIDEO_WIDTH - text2_w) // 2, VIDEO_HEIGHT // 2 - 40), text2,
                  font=big_font, fill=(255, 100, 100))

        sub2 = "For More Amazing Facts!"
        bbox4 = draw2.textbbox((0, 0), sub2, font=small_font)
        sub2_w = bbox4[2] - bbox4[0]
        draw2.text(((VIDEO_WIDTH - sub2_w) // 2, VIDEO_HEIGHT // 2 + 100), sub2,
                  font=small_font, fill=(200, 200, 200))

        img2.save(outro_img, quality=95)

        outro_video = self._temp("outro.mp4")
        cmd = [
            "-loop", "1",
            "-i", outro_img,
            "-t", str(outro_duration),
            "-vf", "fade=t=in:st=0:d=0.5",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-r", str(VIDEO_FPS),
            outro_video
        ]
        run_ffmpeg(cmd, "Generate outro")

        # Final concat
        concat_file = self._temp("final_concat.txt")
        with open(concat_file, "w") as f:
            f.write(f"file '{os.path.abspath(intro_video)}'\n")
            f.write(f"file '{os.path.abspath(video_path)}'\n")
            f.write(f"file '{os.path.abspath(outro_video)}'\n")

        cmd = [
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output_path
        ]
        run_ffmpeg(cmd, "Final assembly")
        return output_path


# ═════════════════════════════════════════════════════════════════════════════
# THUMBNAIL GENERATOR
# ═════════════════════════════════════════════════════════════════════════════

class ThumbnailGenerator:
    def __init__(self):
        self.font_path = get_font_path(bold=True)

    def generate(self, base_image_path: str, title: str, topic: str, output_path: str) -> str:
        img = Image.open(base_image_path).convert('RGB')
        img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)

        # Dark gradient overlays
        overlay = Image.new('RGBA', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        for y in range(400):
            alpha = int(180 * (1 - y / 400))
            draw_overlay.line([(0, y), (VIDEO_WIDTH, y)], fill=(0, 0, 0, alpha))

        for y in range(VIDEO_HEIGHT - 400, VIDEO_HEIGHT):
            alpha = int(200 * ((y - (VIDEO_HEIGHT - 400)) / 400))
            draw_overlay.line([(0, y), (VIDEO_WIDTH, y)], fill=(0, 0, 0, alpha))

        img_rgba = img.convert('RGBA')
        img_rgba = Image.alpha_composite(img_rgba, overlay)
        img = img_rgba.convert('RGB')
        draw = ImageDraw.Draw(img)

        try:
            font_title = ImageFont.truetype(self.font_path, 100)
            font_sub = ImageFont.truetype(self.font_path, 48)
        except Exception:
            font_title = ImageFont.load_default()
            font_sub = font_title

        # Wrap title
        max_text_width = VIDEO_WIDTH - 120
        words = title.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font_title)
            if bbox[2] - bbox[0] > max_text_width and current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                current_line.append(word)
        if current_line:
            lines.append(' '.join(current_line))

        lines = lines[:3]
        line_height = 120
        total_text_height = len(lines) * line_height
        start_y = (VIDEO_HEIGHT - total_text_height) // 2 - 100

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font_title)
            text_w = bbox[2] - bbox[0]
            x = (VIDEO_WIDTH - text_w) // 2
            y = start_y + i * line_height

            # Shadow
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    if abs(dx) + abs(dy) <= 3:
                        draw.text((x + dx, y + dy), line, font=font_title,
                                 fill=(0, 0, 0, 180))

            draw.text((x, y), line, font=font_title, fill=(255, 255, 255))

            if i == 0:
                underline_y = y + line_height - 20
                draw.rectangle([(x, underline_y), (x + text_w, underline_y + 8)],
                              fill=(255, 220, 50))

        # Topic badge
        badge_text = f"  {topic.upper()}  "
        bbox_badge = draw.textbbox((0, 0), badge_text, font=font_sub)
        badge_w = bbox_badge[2] - bbox_badge[0] + 40
        badge_h = bbox_badge[3] - bbox_badge[1] + 20
        badge_x = (VIDEO_WIDTH - badge_w) // 2
        badge_y = 80

        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
            radius=15, fill=(255, 220, 50)
        )
        draw.text((badge_x + 20, badge_y + 8), badge_text, font=font_sub,
                 fill=(0, 0, 0))

        # Shorts indicator
        draw.text((60, VIDEO_HEIGHT - 120), "SHORTS", font=font_sub,
                 fill=(255, 0, 0))

        # Vignette
        vignette = Image.new('RGBA', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        for i in range(100):
            alpha = int(30 * (i / 100))
            v_draw.rectangle([(i, i), (VIDEO_WIDTH - i, VIDEO_HEIGHT - i)],
                           outline=(0, 0, 0, alpha))
        img = Image.alpha_composite(img.convert('RGBA'), vignette).convert('RGB')

        img.save(output_path, quality=95, optimize=True)
        log(f"Thumbnail: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

# ═════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═════════════════════════════════════════════════════════════════════════════

class AjeebologyPipeline:
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = ensure_dir(output_dir)
        self.temp_dir = ensure_dir(os.path.join(output_dir, "temp"))

        self.groq = GroqClient(os.environ.get("GROQ_API_KEY", ""))
        self.tavily = TavilyClient(os.environ.get("TAVILY_API_KEY", ""))
        self.pexels = PexelsClient(os.environ.get("PEXELS_API_KEY", ""))
        self.unsplash = UnsplashClient(os.environ.get("UNSPLASH_ACCESS_KEY", ""))

        self.content = ContentGenerator(self.groq, self.tavily)
        self.assets = AssetManager(self.pexels, self.unsplash,
                                   os.path.join(output_dir, "cache"))
        self.video_proc = VideoProcessor(output_dir)
        self.assembler = VideoAssembler(output_dir)
        self.captions = CaptionEngine()
        self.thumbnail = ThumbnailGenerator()

        self.metadata = None

    def run(self, topic_category: str = "random", force: bool = False) -> VideoMetadata:
        start_time = time.time()
        log("=" * 60)
        log("PIPELINE STARTED")
        log("=" * 60)

        video_out = os.path.join(self.output_dir, "video.mp4")
        thumb_out = os.path.join(self.output_dir, "thumbnail.jpg")
        meta_out = os.path.join(self.output_dir, "metadata.json")

        if not force and os.path.exists(video_out) and os.path.exists(thumb_out):
            log("Existing output found. Use --force to regenerate.")
            with open(meta_out, 'r') as f:
                return VideoMetadata(**json.load(f))

        try:
            # Step 1: Topic
            category, topic = self.content.select_topic(topic_category)

            # Step 2: Research
            log("Researching...")
            sources = self.content.research_topic(topic)

            # Step 3: Script
            log("Generating script...")
            script, word_timings, est_duration = self.content.generate_script(topic, category)
            target_duration = min(max(est_duration, MIN_DURATION), MAX_DURATION)

            # Step 4: TTS
            log("Generating TTS...")
            audio_path = self.content.generate_tts(script, self.output_dir)
            actual_audio_dur = get_duration(audio_path)
            if MIN_DURATION <= actual_audio_dur <= MAX_DURATION:
                target_duration = actual_audio_dur

            # Step 5: Metadata
            log("Generating metadata...")
            title = self.content.generate_title(topic, script)
            description = self.content.generate_description(title, topic)
            tags = self.content.generate_tags(topic, category)
            hashtags = self.content.generate_hashtags(topic, category)

            # Step 6: Assets
            log("Downloading assets...")
            num_clips = max(3, int(target_duration / 2.5))
            clip_paths = self.assets.download_video_clips(topic, count=num_clips)
            if len(clip_paths) < 2:
                while len(clip_paths) < 3:
                    clip_paths.append(random.choice(clip_paths))
            thumb_image_path = self.assets.download_thumbnail_image(topic, category)

            # Step 7: Process clips
            log("Processing clips...")
            segment_duration = target_duration / len(clip_paths)
            prepared_clips = self.video_proc.prepare_all_clips(clip_paths, segment_duration)

            # Step 8: Assemble
            log("Assembling video...")
            concatenated = self.assembler.concatenate_clips(prepared_clips, target_duration)

            with_audio = self._temp("with_audio.mp4")
            self.assembler.add_audio(concatenated, audio_path, with_audio)

            # Step 9: Captions
            log("Generating captions...")
            caption_frames_dir = ensure_dir(os.path.join(self.temp_dir, "caption_frames"))
            caption_video = self.captions.generate_caption_video(
                word_timings, target_duration, caption_frames_dir
            )

            with_captions = self._temp("with_captions.mp4")
            self.assembler.overlay_captions(with_audio, caption_video, with_captions)

            # Step 10: Background music
            with_music = self._temp("with_music.mp4")
            self.assembler.add_background_music(with_captions, with_music)

            # Step 11: Intro/Outro
            final_video = self.assembler.add_intro_outro(with_music, title, video_out)

            # Step 12: Thumbnail
            self.thumbnail.generate(thumb_image_path, title, topic, thumb_out)

            # Step 13: Metadata
            file_size_mb = round(os.path.getsize(video_out) / (1024 * 1024), 2)

            self.metadata = VideoMetadata(
                title=title,
                description=description,
                tags=tags,
                hashtags=hashtags,
                category=category,
                duration=round(get_duration(video_out), 1),
                file_size_mb=file_size_mb,
                video_filename="video.mp4",
                thumbnail_filename="thumbnail.jpg",
                sources=[{"title": s.title, "url": s.url} for s in sources],
                timestamp=datetime.now(timezone.utc).isoformat(),
                script_text=script,
                topic=topic
            )

            with open(meta_out, 'w', encoding='utf-8') as f:
                json.dump(asdict(self.metadata), f, indent=2, ensure_ascii=False)

            info_path = os.path.join(self.output_dir, "video_info.txt")
            with open(info_path, 'w', encoding='utf-8') as f:
                f.write(f"Title: {title}\n\n")
                f.write(f"Description:\n{description}\n\n")
                f.write(f"Tags: {', '.join(tags)}\n\n")
                f.write(f"Hashtags: {' '.join(hashtags)}\n\n")
                f.write(f"Duration: {self.metadata.duration}s\n")
                f.write(f"File Size: {file_size_mb} MB\n")
                f.write(f"Category: {category}\n")
                f.write(f"Topic: {topic}\n\n")
                f.write(f"Sources:\n")
                for s in sources:
                    f.write(f"  - {s.title}: {s.url}\n")

            # Cleanup
            self._cleanup()

            elapsed = time.time() - start_time
            log("=" * 60)
            log(f"DONE in {elapsed:.1f}s")
            log(f"Video: {video_out} ({file_size_mb} MB)")
            log(f"Thumbnail: {thumb_out}")
            log("=" * 60)

            return self.metadata

        except Exception as e:
            log(f"PIPELINE FAILED: {str(e)}", "ERROR")
            import traceback
            log(traceback.format_exc(), "ERROR")
            raise

    def _temp(self, name: str) -> str:
        return os.path.join(self.temp_dir, name)

    def _cleanup(self) -> None:
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                os.makedirs(self.temp_dir)
            log("Cleanup done")
        except Exception as e:
            log(f"Cleanup warning: {e}", "WARN")


# ═════════════════════════════════════════════════════════════════════════════
# TELEGRAM DELIVERY
# ═════════════════════════════════════════════════════════════════════════════

class TelegramDelivery:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = TELEGRAM_BASE_URL.format(token=token)

    def send_video(self, video_path: str, caption: str) -> Dict:
        url = f"{self.base_url}/sendVideo"
        with open(video_path, 'rb') as f:
            r = requests.post(url, data={
                'chat_id': self.chat_id,
                'caption': caption[:1024],
                'parse_mode': 'HTML',
                'supports_streaming': 'true'
            }, files={'video': f}, timeout=120)
            r.raise_for_status()
            return r.json()

    def send_document(self, doc_path: str, caption: str = "") -> Dict:
        url = f"{self.base_url}/sendDocument"
        with open(doc_path, 'rb') as f:
            r = requests.post(url, data={
                'chat_id': self.chat_id,
                'caption': caption[:1024],
                'parse_mode': 'HTML'
            }, files={'document': f}, timeout=60)
            r.raise_for_status()
            return r.json()

    def send_report(self, metadata: VideoMetadata, output_dir: str) -> None:
        log("Sending to Telegram...")
        sources_text = '\n'.join([
            '• ' + s['title'] + ': ' + s['url']
            for s in metadata.sources[:3]
        ])

        caption = '📹 <b>' + metadata.title + '</b>\n\n📝 <b>Description:</b>\n' + metadata.description[:300] + '...\n\n🏷 <b>Tags:</b> ' + ', '.join(metadata.tags[:5]) + '\n#️⃣ <b>Hashtags:</b> ' + ' '.join(metadata.hashtags) + '\n📂 <b>Category:</b> ' + metadata.category + '\n⏱ <b>Duration:</b> ' + str(metadata.duration) + 's\n📊 <b>Size:</b> ' + str(metadata.file_size_mb) + ' MB\n\n🔬 <b>Sources:</b>\n' + sources_text + '\n\n🕐 <b>Generated:</b> ' + metadata.timestamp[:19]

        video_path = os.path.join(output_dir, metadata.video_filename)
        self.send_video(video_path, caption)

        thumb_path = os.path.join(output_dir, metadata.thumbnail_filename)
        self.send_document(thumb_path, '🖼 Thumbnail')

        meta_path = os.path.join(output_dir, "metadata.json")
        self.send_document(meta_path, '📋 Metadata JSON')

        info_path = os.path.join(output_dir, "video_info.txt")
        if os.path.exists(info_path):
            self.send_document(info_path, '📝 Video Info')

        log("Telegram delivery complete")

# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(description="Ajeebology Shorts Production")
    parser.add_argument("--topic", "-t", choices=["psychology", "space", "weird_world", "random"],
                      default="random", help="Video topic category")
    parser.add_argument("--output-dir", "-o", default="./output", help="Output directory")
    parser.add_argument("--force", "-f", action="store_true", default=False,
                        help="Force regeneration")
    parser.add_argument("--skip-telegram", action="store_true", default=False,
                        help="Skip Telegram delivery")
    return parser.parse_args()

def main():
    args = parse_args()

    required = ["GROQ_API_KEY", "TAVILY_API_KEY", "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log(f"Missing env vars: {', '.join(missing)}", "ERROR")
        sys.exit(1)

    pipeline = AjeebologyPipeline(output_dir=args.output_dir)

    try:
        metadata = pipeline.run(topic_category=args.topic, force=args.force)

        if not args.skip_telegram:
            token = os.environ.get("TELEGRAM_TOKEN")
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if token and chat_id:
                try:
                    delivery = TelegramDelivery(token, chat_id)
                    delivery.send_report(metadata, args.output_dir)
                except Exception as e:
                    log(f"Telegram failed: {e}", "WARN")
            else:
                log("Telegram credentials missing, skipping", "WARN")

        log("All done!")
        sys.exit(0)

    except Exception as e:
        log(f"Fatal: {e}", "ERROR")
        sys.exit(1)

if __name__ == "__main__":
    main()
        
