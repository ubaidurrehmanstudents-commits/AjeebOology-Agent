#!/usr/bin/env python3
"""
Ajeebology Shorts - Fully Automated YouTube Shorts Pipeline
Single-file implementation for GitHub Actions Free Tier
"""

import os
import sys
import json
import time
import random
import logging
import hashlib
import asyncio
import textwrap
import requests
import traceback
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np
from gtts import gTTS
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from groq import Groq
import httpx

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

OUTPUT_DIR = Path("output")
ASSETS_DIR = Path("output/assets")
FOOTAGE_DIR = Path("output/footage")
AUDIO_DIR = Path("output/audio")
FRAMES_DIR = Path("output/frames")

for d in [OUTPUT_DIR, ASSETS_DIR, FOOTAGE_DIR, AUDIO_DIR, FRAMES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TOPIC_OVERRIDE = os.environ.get("TOPIC_OVERRIDE", "").strip()

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
TARGET_DURATION_MIN = 55
TARGET_DURATION_MAX = 65
SEGMENT_CHANGE_INTERVAL = 2.5
CAPTION_FONT_SIZE = 72
CAPTION_MAX_WORDS = 4

TOPIC_CATEGORIES = [
    "psychology facts",
    "space facts",
    "weird world facts",
    "human brain facts",
    "universe mysteries",
    "strange animal behavior",
    "bizarre historical events",
    "mind-blowing science facts"
]

HINGLISH_INTRO_TEMPLATES = [
    "Kya aap jaante hain? {fact_preview}",
    "Ye sunke aap shocked ho jaoge! {fact_preview}",
    "Science ne kuch aisa discover kiya hai jo {fact_preview}",
    "Duniya ka sabse ajeeb fact — {fact_preview}",
    "99% log nahi jaante — {fact_preview}"
]

# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("AjeebologyAgent")
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    file_handler = logging.FileHandler("output/pipeline.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger

log = setup_logging()

# ─────────────────────────────────────────────
# RUNTIME STATS TRACKER
# ─────────────────────────────────────────────

class RuntimeStats:
    def __init__(self):
        self.start_time = time.time()
        self.steps = {}
        self.errors = []
        self.warnings = []

    def mark(self, step: str):
        self.steps[step] = round(time.time() - self.start_time, 2)
        log.info(f"✅ Step completed: {step} at {self.steps[step]}s")

    def warn(self, msg: str):
        self.warnings.append(msg)
        log.warning(f"⚠️  {msg}")

    def error(self, msg: str):
        self.errors.append(msg)
        log.error(f"❌ {msg}")

    def summary(self) -> dict:
        total = round(time.time() - self.start_time, 2)
        return {
            "total_runtime_seconds": total,
            "steps": self.steps,
            "errors": self.errors,
            "warnings": self.warnings,
            "github_minutes_used": round(total / 60, 2)
        }

stats = RuntimeStats()

# ─────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────

def validate_environment():
    log.info("Validating environment variables...")
    required = {
        "GROQ_API_KEY": GROQ_API_KEY,
        "TAVILY_API_KEY": TAVILY_API_KEY,
        "PEXELS_API_KEY": PEXELS_API_KEY,
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(f"Missing secrets: {', '.join(missing)}")

    optional = {"UNSPLASH_ACCESS_KEY": UNSPLASH_ACCESS_KEY}
    for k, v in optional.items():
        if not v:
            stats.warn(f"Optional secret missing: {k}")

    log.info("Environment validation passed.")

# ─────────────────────────────────────────────
# TOPIC RESEARCH — TAVILY
# ─────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception)
)
def research_topic(topic: str) -> dict:
    log.info(f"Researching topic: {topic}")
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": f"{topic} amazing facts 2024",
        "search_depth": "advanced",
        "include_answer": True,
        "include_raw_content": False,
        "max_results": 5,
        "include_domains": [
            "wikipedia.org",
            "sciencedaily.com",
            "nationalgeographic.com",
            "space.com",
            "psychologytoday.com"
        ]
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()

    sources = []
    combined_content = data.get("answer", "")

    for result in data.get("results", []):
        sources.append(result.get("url", ""))
        combined_content += "\n" + result.get("content", "")

    log.info(f"Research complete. Sources found: {len(sources)}")
    return {
        "topic": topic,
        "raw_content": combined_content[:4000],
        "sources": sources[:5]
    }

# ─────────────────────────────────────────────
# SCRIPT GENERATION — GROQ
# ─────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=3, max=15),
    retry=retry_if_exception_type(Exception)
)
def generate_script(research_data: dict) -> dict:
    log.info("Generating Hinglish script via Groq...")
    client = Groq(api_key=GROQ_API_KEY)
    topic = research_data["topic"]
    content = research_data["raw_content"]

    system_prompt = """You are a viral YouTube Shorts scriptwriter for "Ajeebology Shorts" channel.
You write in Hinglish (mix of Hindi written in Roman script and English).
Your scripts must be:
- Shocking and curiosity-driven
- Max 60 seconds when read aloud (130-150 words)
- Use simple language a 13-year-old understands
- Include a strong hook in first 3 seconds
- End with a mind-blown statement

Return ONLY valid JSON with this exact structure:
{
  "title": "video title in Hinglish (max 60 chars)",
  "description": "YouTube description in Hinglish (150 words)",
  "script": "full spoken script in Hinglish",
  "hook": "first 1-2 sentences (the hook)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3"],
  "category": "Education",
  "search_keywords": ["keyword1", "keyword2", "keyword3"],
  "pexels_search_terms": ["term1", "term2", "term3", "term4"]
}"""

    user_prompt = f"""Topic: {topic}

Research Data:
{content}

Write a 55-65 second viral Hinglish YouTube Short script about this topic.
The pexels_search_terms should be English words for finding relevant B-roll footage.
Make the hook extremely shocking."""

    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.8,
        max_tokens=1500,
        response_format={"type": "json_object"}
    )

    raw = response.choices[0].message.content
    script_data = json.loads(raw)

    required_keys = ["title", "script", "hook", "tags", "pexels_search_terms"]
    for key in required_keys:
        if key not in script_data:
            raise ValueError(f"Missing key in script response: {key}")

    log.info(f"Script generated. Title: {script_data['title']}")
    log.info(f"Script word count: {len(script_data['script'].split())}")
    return script_data

# ─────────────────────────────────────────────
# TEXT TO SPEECH — gTTS
# ─────────────────────────────────────────────

def generate_tts(script: str) -> dict:
    log.info("Generating TTS audio via gTTS...")
    output_path = AUDIO_DIR / "voiceover.mp3"
    wav_path = AUDIO_DIR / "voiceover.wav"

    try:
        tts = gTTS(text=script, lang="hi", slow=False)
        tts.save(str(output_path))
        log.info(f"TTS saved to {output_path}")
    except Exception as e:
        log.warning(f"Hindi TTS failed: {e}. Trying English fallback...")
        tts = gTTS(text=script, lang="en", slow=False)
        tts.save(str(output_path))

    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(output_path)
    ], capture_output=True, text=True, timeout=30)

    duration = 60.0
    if result.returncode == 0:
        probe_data = json.loads(result.stdout)
        duration = float(probe_data["format"]["duration"])

    log.info(f"TTS duration: {duration:.2f}s")

    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(output_path),
        "-ar", "44100",
        "-ac", "2",
        "-q:a", "0",
        str(wav_path)
    ], capture_output=True, timeout=60)

    if duration < TARGET_DURATION_MIN:
        stats.warn(f"TTS duration {duration:.1f}s is below target minimum {TARGET_DURATION_MIN}s")
    elif duration > TARGET_DURATION_MAX:
        stats.warn(f"TTS duration {duration:.1f}s exceeds target maximum {TARGET_DURATION_MAX}s")

    words = script.split()
    words_per_second = len(words) / duration if duration > 0 else 2.5
    word_timings = []
    current_time = 0.0
    for word in words:
        word_duration = 1.0 / words_per_second
        word_timings.append({
            "word": word,
            "start": round(current_time, 3),
            "end": round(current_time + word_duration, 3)
        })
        current_time += word_duration

    log.info(f"Word timings generated for {len(word_timings)} words")

    return {
        "mp3_path": str(output_path),
        "wav_path": str(wav_path),
        "duration": duration,
        "word_timings": word_timings,
        "words_per_second": words_per_second
    }

# ─────────────────────────────────────────────
# PEXELS VIDEO DOWNLOAD
# ─────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception_type(Exception)
)
def search_pexels_videos(query: str, per_page: int = 5) -> list:
    log.info(f"Searching Pexels videos: '{query}'")
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "portrait",
        "size": "medium"
    }
    response = requests.get(
        "https://api.pexels.com/videos/search",
        headers=headers,
        params=params,
        timeout=20
    )
    response.raise_for_status()
    data = response.json()
    videos = data.get("videos", [])
    log.info(f"Found {len(videos)} videos for '{query}'")
    return videos

def get_best_video_file(video: dict) -> Optional[str]:
    files = video.get("video_files", [])
    portrait_files = [
        f for f in files
        if f.get("width", 0) < f.get("height", 0)
    ]
    if not portrait_files:
        portrait_files = files

    portrait_files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0))
    mid_quality = portrait_files[len(portrait_files)//2] if portrait_files else None
    return mid_quality.get("link") if mid_quality else None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception)
)
def download_video(url: str, filename: str) -> Optional[Path]:
    output_path = FOOTAGE_DIR / filename
    if output_path.exists() and output_path.stat().st_size > 10000:
        log.info(f"Video already exists: {filename}")
        return output_path

    log.info(f"Downloading video: {filename}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(output_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)

    size_mb = output_path.stat().st_size / (1024*1024)
    log.info(f"Downloaded {filename} ({size_mb:.1f} MB)")
    return output_path

def collect_footage(search_terms: list, total_duration: float) -> list:
    log.info(f"Collecting footage for {total_duration:.1f}s video...")
    footage_clips = []
    segments_needed = int(total_duration / SEGMENT_CHANGE_INTERVAL) + 3
    used_video_ids = set()

    for term in search_terms:
        if len(footage_clips) >= segments_needed:
            break
        try:
            videos = search_pexels_videos(term, per_page=5)
            for video in videos:
                if len(footage_clips) >= segments_needed:
                    break
                vid_id = video.get("id")
                if vid_id in used_video_ids:
                    continue
                video_url = get_best_video_file(video)
                if not video_url:
                    continue
                safe_term = term.replace(" ", "_")[:20]
                filename = f"{safe_term}_{vid_id}.mp4"
                path = download_video(video_url, filename)
                if path and path.exists():
                    clip_duration = get_video_duration(str(path))
                    if clip_duration and clip_duration > 1.0:
                        footage_clips.append({
                            "path": str(path),
                            "duration": clip_duration,
                            "term": term,
                            "id": vid_id
                        })
                        used_video_ids.add(vid_id)
                        log.info(f"Added clip: {filename} ({clip_duration:.1f}s)")
        except Exception as e:
            stats.warn(f"Footage collection failed for '{term}': {e}")
            continue

    if len(footage_clips) < 3:
        log.warning("Not enough footage collected. Adding fallback searches...")
        fallback_terms = ["technology", "nature", "space", "science", "abstract"]
        for term in fallback_terms:
            if len(footage_clips) >= 5:
                break
            try:
                videos = search_pexels_videos(term, per_page=3)
                for video in videos[:2]:
                    vid_id = video.get("id")
                    if vid_id in used_video_ids:
                        continue
                    video_url = get_best_video_file(video)
                    if not video_url:
                        continue
                    filename = f"fallback_{vid_id}.mp4"
                    path = download_video(video_url, filename)
                    if path and path.exists():
                        clip_duration = get_video_duration(str(path))
                        if clip_duration and clip_duration > 1.0:
                            footage_clips.append({
                                "path": str(path),
                                "duration": clip_duration,
                                "term": term,
                                "id": vid_id
                            })
                            used_video_ids.add(vid_id)
            except Exception as e:
                stats.warn(f"Fallback footage failed for '{term}': {e}")

    log.info(f"Total footage clips collected: {len(footage_clips)}")
    return footage_clips

def get_video_duration(path: str) -> Optional[float]:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", path
        ], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
    except Exception as e:
        log.warning(f"Could not get duration for {path}: {e}")
    return None

# ─────────────────────────────────────────────
# UNSPLASH THUMBNAIL BACKGROUND
# ─────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception_type(Exception)
)
def fetch_unsplash_image(query: str) -> Optional[Path]:
    if not UNSPLASH_ACCESS_KEY:
        log.warning("No Unsplash key. Skipping Unsplash fetch.")
        return None

    log.info(f"Fetching Unsplash image for: '{query}'")
    params = {
        "query": query,
        "orientation": "portrait",
        "per_page": 5,
        "client_id": UNSPLASH_ACCESS_KEY
    }
    response = requests.get(
        "https://api.unsplash.com/search/photos",
        params=params,
        timeout=20
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])

    if not results:
        log.warning(f"No Unsplash results for '{query}'")
        return None

    chosen = random.choice(results[:3])
    img_url = chosen["urls"]["regular"]

    img_response = requests.get(img_url, timeout=30)
    img_response.raise_for_status()

    img_path = ASSETS_DIR / "thumbnail_bg.jpg"
    with open(img_path, "wb") as f:
        f.write(img_response.content)

    log.info(f"Unsplash image saved: {img_path}")
    return img_path

# ─────────────────────────────────────────────
# THUMBNAIL GENERATION
# ─────────────────────────────────────────────

def generate_thumbnail(title: str, bg_image_path: Optional[Path]) -> Path:
    log.info("Generating thumbnail...")
    thumb_path = OUTPUT_DIR / "thumbnail.jpg"

    canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color=(10, 10, 30))

    if bg_image_path and bg_image_path.exists():
        try:
            bg = Image.open(bg_image_path).convert("RGB")
            bg = bg.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
            enhancer = ImageEnhance.Brightness(bg)
            bg = enhancer.enhance(0.4)
            blur = bg.filter(ImageFilter.GaussianBlur(radius=3))
            canvas.paste(blur, (0, 0))
        except Exception as e:
            log.warning(f"Could not apply thumbnail background: {e}")

    overlay = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 10, 160))
    canvas = canvas.convert("RGBA")
    canvas = Image.alpha_composite(canvas, overlay)
    canvas = canvas.convert("RGB")

    draw = ImageDraw.Draw(canvas)

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 90)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 60)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 45)
        font_channel = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 50)
    except Exception:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large
        font_channel = font_large

    channel_text = "AJEEBOLOGY"
    ch_bbox = draw.textbbox((0, 0), channel_text, font=font_channel)
    ch_w = ch_bbox[2] - ch_bbox[0]
    draw.rectangle([
        (VIDEO_WIDTH//2 - ch_w//2 - 20, 120),
        (VIDEO_WIDTH//2 + ch_w//2 + 20, 185)
    ], fill=(255, 50, 50))
    draw.text(
        (VIDEO_WIDTH//2 - ch_w//2, 125),
        channel_text,
        font=font_channel,
        fill=(255, 255, 255)
    )

    emoji_area = (VIDEO_WIDTH//2 - 80, 220, VIDEO_WIDTH//2 + 80, 400)
    draw.ellipse(emoji_area, fill=(255, 200, 0, 200))
    draw.text((VIDEO_WIDTH//2 - 55, 240), "🤯", font=font_large, fill=(255, 255, 255))

    words = title.split()
    lines = []
    current_line = []
    for word in words:
        current_line.append(word)
        test_line = " ".join(current_line)
        bbox = draw.textbbox((0, 0), test_line, font=font_medium)
        if bbox[2] - bbox[0] > VIDEO_WIDTH - 120:
            if len(current_line) > 1:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(test_line)
                current_line = []
    if current_line:
        lines.append(" ".join(current_line))

    y_start = 900
    line_height = 85
    for i, line in enumerate(lines[:4]):
        bbox = draw.textbbox((0, 0), line, font=font_medium)
        line_w = bbox[2] - bbox[0]
        x = VIDEO_WIDTH//2 - line_w//2
        y = y_start + i * line_height
        for dx, dy in [(-3,-3),(3,-3),(-3,3),(3,3),(0,-3),(0,3),(-3,0),(3,0)]:
            draw.text((x+dx, y+dy), line, font=font_medium, fill=(0, 0, 0))
        draw.text((x, y), line, font=font_medium, fill=(255, 255, 255))

    gradient_height = 400
    for i in range(gradient_height):
        alpha = int(200 * (i / gradient_height))
        draw.rectangle(
            [(0, VIDEO_HEIGHT - gradient_height + i),
             (VIDEO_WIDTH, VIDEO_HEIGHT - gradient_height + i + 1)],
            fill=(0, 0, 0, alpha)
        )

    shorts_text = "#Shorts"
    s_bbox = draw.textbbox((0, 0), shorts_text, font=font_small)
    s_w = s_bbox[2] - s_bbox[0]
    draw.text(
        (VIDEO_WIDTH//2 - s_w//2, VIDEO_HEIGHT - 120),
        shorts_text,
        font=font_small,
        fill=(255, 50, 50)
    )

    canvas.save(str(thumb_path), "JPEG", quality=95)
    log.info(f"Thumbnail saved: {thumb_path}")
    return thumb_path

# ─────────────────────────────────────────────
# CAPTION FRAME GENERATOR
# ─────────────────────────────────────────────

def group_words_into_captions(word_timings: list) -> list:
    captions = []
    i = 0
    while i < len(word_timings):
        group = word_timings[i:i + CAPTION_MAX_WORDS]
        if group:
            text = " ".join(w["word"] for w in group)
            captions.append({
                "text": text,
                "start": group[0]["start"],
                "end": group[-1]["end"]
            })
        i += CAPTION_MAX_WORDS
    return captions

def create_caption_image(
    text: str,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    highlight_color: tuple = (255, 220, 0),
    text_color: tuple = (255, 255, 255)
) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            CAPTION_FONT_SIZE
        )
    except Exception:
        font = ImageFont.load_default()

    max_width = width - 120
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    line_height = CAPTION_FONT_SIZE + 18
    total_h = len(lines) * line_height
    y_start = height - 380 - total_h

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2
        pad = 18
        draw.rounded_rectangle(
            [x - pad, y_start - pad//2,
             x + text_w + pad, y_start + line_height],
            radius=14,
            fill=(0, 0, 0, 190)
        )
        for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2)]:
            draw.text((x+dx, y_start+dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y_start), line, font=font, fill=text_color)
        y_start += line_height

    return img

# ─────────────────────────────────────────────
# FFMPEG VIDEO ASSEMBLY
# ─────────────────────────────────────────────

def get_clip_segment(clip_path: str, start: float, duration: float, output_path: str, index: int):
    zoom_types = ["in", "out", "none"]
    zoom = zoom_types[index % len(zoom_types)]

    if zoom == "in":
        vf = (
            f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"'(iw-{VIDEO_WIDTH})/2+((iw-{VIDEO_WIDTH})/2)*t/{duration}':"
            f"'(ih-{VIDEO_HEIGHT})/2+((ih-{VIDEO_HEIGHT})/2)*t/{duration}',"
            f"setsar=1"
        )
    elif zoom == "out":
        vf = (
            f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"'(iw-{VIDEO_WIDTH})/2+((iw-{VIDEO_WIDTH})/2)*(1-t/{duration})':"
            f"'(ih-{VIDEO_HEIGHT})/2+((ih-{VIDEO_HEIGHT})/2)*(1-t/{duration})',"
            f"setsar=1"
        )
    else:
        vf = (
            f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"'(iw-{VIDEO_WIDTH})/2':"
            f"'(ih-{VIDEO_HEIGHT})/2',"
            f"setsar=1"
        )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", clip_path,
        "-t", str(duration),
        "-vf", vf,
        "-r", str(VIDEO_FPS),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-an",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Clip extraction failed: {result.stderr.decode()[:300]}")

def build_segment_list(footage_clips: list, total_duration: float) -> list:
    log.info("Building segment list...")
    segments = []
    current_time = 0.0
    clip_index = 0
    seg_index = 0

    while current_time < total_duration:
        remaining = total_duration - current_time
        seg_duration = min(SEGMENT_CHANGE_INTERVAL, remaining)
        if seg_duration < 0.5:
            break

        clip = footage_clips[clip_index % len(footage_clips)]
        clip_dur = clip["duration"]
        max_start = max(0, clip_dur - seg_duration - 0.5)
        start_offset = random.uniform(0, max_start) if max_start > 0 else 0

        segments.append({
            "clip_path": clip["path"],
            "start_offset": start_offset,
            "duration": seg_duration,
            "timeline_start": current_time,
            "index": seg_index
        })

        current_time += seg_duration
        clip_index += 1
        seg_index += 1

    log.info(f"Built {len(segments)} segments covering {current_time:.2f}s")
    return segments

def extract_all_segments(segments: list) -> list:
    log.info(f"Extracting {len(segments)} video segments...")
    extracted = []
    for seg in segments:
        out_path = str(FOOTAGE_DIR / f"seg_{seg['index']:04d}.mp4")
        try:
            get_clip_segment(
                seg["clip_path"],
                seg["start_offset"],
                seg["duration"],
                out_path,
                seg["index"]
            )
            extracted.append(out_path)
        except Exception as e:
            stats.warn(f"Segment {seg['index']} extraction failed: {e}")
            if extracted:
                extracted.append(extracted[-1])
            continue

    log.info(f"Successfully extracted {len(extracted)} segments")
    return extracted

def concatenate_segments(segment_paths: list, output_path: str):
    log.info("Concatenating video segments...")
    list_file = FOOTAGE_DIR / "concat_list.txt"
    with open(list_file, "w") as f:
        for path in segment_paths:
            if Path(path).exists():
                f.write(f"file '{path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"Concatenation failed: {result.stderr.decode()[:300]}")
    log.info(f"Segments concatenated: {output_path}")

# ─────────────────────────────────────────────
# CAPTION OVERLAY VIA FFMPEG
# ─────────────────────────────────────────────

def render_captions_on_video(
    input_video: str,
    word_timings: list,
    output_path: str
):
    log.info("Rendering captions onto video...")
    captions = group_words_into_captions(word_timings)
    caption_images_dir = FRAMES_DIR / "captions"
    caption_images_dir.mkdir(exist_ok=True)

    caption_files = []
    for i, cap in enumerate(captions):
        img = create_caption_image(cap["text"])
        img_path = caption_images_dir / f"cap_{i:04d}.png"
        img.save(str(img_path), "PNG")
        caption_files.append({
            "path": str(img_path),
            "start": cap["start"],
            "end": cap["end"],
            "text": cap["text"]
        })

    if not caption_files:
        log.warning("No captions generated. Skipping caption overlay.")
        import shutil
        shutil.copy(input_video, output_path)
        return

    filter_parts = []
    overlay_parts = []
    prev_label = "[0:v]"

    for i, cap in enumerate(caption_files):
        cap_label_in = f"[cap{i}]"
        cap_label_out = f"[v{i}]"
        filter_parts.append(
            f"[{i+1}:v]format=rgba{cap_label_in}"
        )
        overlay_parts.append(
            f"{prev_label}{cap_label_in}overlay=0:0:"
            f"enable='between(t,{cap['start']},{cap['end']})'"
            f"{cap_label_out}"
        )
        prev_label = cap_label_out

    final_label = prev_label

    filter_complex = (
        ";".join(filter_parts) +
        ";" +
        ";".join(overlay_parts)
    )

    cmd = ["ffmpeg", "-y", "-i", input_video]
    for cap in caption_files:
        cmd += ["-i", cap["path"]]

    cmd += [
        "-filter_complex", filter_complex,
        "-map", final_label,
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        log.warning(f"Caption overlay failed: {result.stderr.decode()[:300]}")
        log.warning("Falling back to drawtext captions...")
        render_captions_drawtext(input_video, captions, output_path)
    else:
        log.info(f"Captions rendered: {output_path}")

def render_captions_drawtext(
    input_video: str,
    captions: list,
    output_path: str
):
    log.info("Using drawtext fallback for captions...")
    drawtext_filters = []

    for cap in captions:
        safe_text = cap["text"].replace("'", "\\'").replace(":", "\\:")
        safe_text = safe_text.replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")
        drawtext_filters.append(
            f"drawtext=text='{safe_text}'"
            f":fontsize={CAPTION_FONT_SIZE}"
            f":fontcolor=white"
            f":borderw=4"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y=h-380"
            f":enable='between(t,{cap['start']},{cap['end']})'"
        )

    vf = ",".join(drawtext_filters) if drawtext_filters else "null"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-c:a", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Drawtext captions failed: {result.stderr.decode()[:300]}")
    log.info(f"Drawtext captions applied: {output_path}")

# ─────────────────────────────────────────────
# SOUND DESIGN — BACKGROUND MUSIC
# ─────────────────────────────────────────────

def generate_background_music(duration: float) -> Optional[str]:
    log.info("Generating background music tone...")
    music_path = str(AUDIO_DIR / "background_music.wav")

    try:
        sample_rate = 44100
        t = np.linspace(0, duration, int(sample_rate * duration), False)

        freq1 = 174.6
        freq2 = 220.0
        freq3 = 261.6

        wave1 = 0.15 * np.sin(2 * np.pi * freq1 * t)
        wave2 = 0.10 * np.sin(2 * np.pi * freq2 * t)
        wave3 = 0.08 * np.sin(2 * np.pi * freq3 * t)

        fade_samples = int(sample_rate * 2.0)
        fade_in = np.linspace(0, 1, fade_samples)
        fade_out = np.linspace(1, 0, fade_samples)

        combined = wave1 + wave2 + wave3

        if len(combined) > fade_samples:
            combined[:fade_samples] *= fade_in
        if len(combined) > fade_samples:
            combined[-fade_samples:] *= fade_out

        combined = np.clip(combined, -1.0, 1.0)
        audio_int16 = (combined * 32767).astype(np.int16)

        import wave as wave_module
        with wave_module.open(music_path, 'w') as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            stereo = np.column_stack([audio_int16, audio_int16])
            wf.writeframes(stereo.tobytes())

        log.info(f"Background music generated: {music_path}")
        return music_path

    except Exception as e:
        stats.warn(f"Background music generation failed: {e}")
        return None

def mix_audio(
    voiceover_path: str,
    music_path: Optional[str],
    duration: float,
    output_path: str
):
    log.info("Mixing audio tracks...")

    if not music_path or not Path(music_path).exists():
        log.info("No background music. Using voiceover only.")
        cmd = [
            "ffmpeg", "-y",
            "-i", voiceover_path,
            "-t", str(duration),
            "-ar", "44100",
            "-ac", "2",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"Audio processing failed: {result.stderr.decode()[:200]}")
        return

    cmd = [
        "ffmpeg", "-y",
        "-i", voiceover_path,
        "-i", music_path,
        "-filter_complex",
        "[0:a]volume=1.0[voice];"
        "[1:a]volume=0.12[music];"
        "[voice][music]amix=inputs=2:duration=first:dropout_transition=2[out]",
        "-map", "[out]",
        "-t", str(duration),
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0:
        log.warning(f"Audio mix failed: {result.stderr.decode()[:200]}")
        log.warning("Falling back to voiceover only...")
        mix_audio(voiceover_path, None, duration, output_path)
    else:
        log.info(f"Audio mixed: {output_path}")

# ─────────────────────────────────────────────
# FINAL VIDEO ASSEMBLY
# ─────────────────────────────────────────────

def assemble_final_video(
    raw_video: str,
    audio_path: str,
    output_path: str,
    duration: float
):
    log.info("Assembling final video with audio...")
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_video,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", str(duration),
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Final assembly failed: {result.stderr.decode()[:300]}")
    size_mb = Path(output_path).stat().st_size / (1024*1024)
    log.info(f"Final video assembled: {output_path} ({size_mb:.1f} MB)")

def add_intro_card(
    main_video: str,
    hook_text: str,
    output_path: str
):
    log.info("Adding intro card overlay...")
    safe_hook = hook_text[:60].replace("'", "\\'").replace(":", "\\:")
    safe_hook = safe_hook.replace(",", "\\,")

    vf = (
        f"drawtext=text='{safe_hook}'"
        f":fontsize=58"
        f":fontcolor=yellow"
        f":borderw=4"
        f":bordercolor=black"
        f":x=(w-text_w)/2"
        f":y=200"
        f":enable='between(t,0,3)'"
        f",drawtext=text='AJEEBOLOGY'"
        f":fontsize=45"
        f":fontcolor=white"
        f":borderw=3"
        f":bordercolor=red"
        f":x=(w-text_w)/2"
        f":y=140"
        f":enable='between(t,0,3)'"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", main_video,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180)
    if result.returncode != 0:
        log.warning(f"Intro card failed: {result.stderr.decode()[:200]}")
        import shutil
        shutil.copy(main_video, output_path)
    else:
        log.info(f"Intro card added: {output_path}")

# ─────────────────────────────────────────────
# TELEGRAM DELIVERY
# ─────────────────────────────────────────────

def send_telegram_video(
    video_path: str,
    thumbnail_path: str,
    script_data: dict,
    research_data: dict,
    audio_data: dict,
    runtime_summary: dict
):
    log.info("Sending video to Telegram...")

    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    caption_text = f"""
🎬 *AJEEBOLOGY SHORTS — NEW VIDEO READY*

📌 *Title:*
{script_data.get('title', 'N/A')}

📝 *Description:*
{script_data.get('description', 'N/A')[:300]}...

🏷️ *Tags:*
{', '.join(script_data.get('tags', []))}

#️⃣ *Hashtags:*
{' '.join(script_data.get('hashtags', []))}

📂 *Category:* {script_data.get('category', 'Education')}

🔬 *Research Sources:*
{chr(10).join(research_data.get('sources', [])[:3])}

⏱️ *Runtime Stats:*
• Total Time: {runtime_summary.get('total_runtime_seconds', 0)}s
• GitHub Minutes Used: {runtime_summary.get('github_minutes_used', 0)}
• Video Duration: {audio_data.get('duration', 0):.1f}s
• Steps: {len(runtime_summary.get('steps', {}))}
• Warnings: {len(runtime_summary.get('warnings', []))}
• Errors: {len(runtime_summary.get('errors', []))}

✅ *Status: READY FOR UPLOAD*
"""

    thumb_sent = False
    if Path(thumbnail_path).exists():
        try:
            with open(thumbnail_path, "rb") as thumb_file:
                thumb_response = requests.post(
                    f"{base_url}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": "🖼️ Thumbnail Preview"},
                    files={"photo": thumb_file},
                    timeout=60
                )
            if thumb_response.status_code == 200:
                thumb_sent = True
                log.info("Thumbnail sent to Telegram")
            else:
                stats.warn(f"Thumbnail send failed: {thumb_response.text[:200]}")
        except Exception as e:
            stats.warn(f"Thumbnail Telegram error: {e}")

    video_sent = False
    if Path(video_path).exists():
        video_size_mb = Path(video_path).stat().st_size / (1024*1024)
        log.info(f"Sending video ({video_size_mb:.1f} MB) to Telegram...")

        if video_size_mb > 50:
            stats.warn(f"Video {video_size_mb:.1f}MB exceeds Telegram 50MB limit")
            compressed_path = str(OUTPUT_DIR / "final_video_compressed.mp4")
            compress_video_for_telegram(video_path, compressed_path)
            if Path(compressed_path).exists():
                video_path = compressed_path
                video_size_mb = Path(video_path).stat().st_size / (1024*1024)
                log.info(f"Compressed to {video_size_mb:.1f}MB")

        try:
            with open(video_path, "rb") as vid_file:
                vid_response = requests.post(
                    f"{base_url}/sendVideo",
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "caption": caption_text[:1024],
                        "parse_mode": "Markdown",
                        "supports_streaming": "true",
                        "width": VIDEO_WIDTH,
                        "height": VIDEO_HEIGHT
                    },
                    files={"video": vid_file},
                    timeout=300
                )
            if vid_response.status_code == 200:
                video_sent = True
                log.info("Video sent to Telegram successfully")
            else:
                stats.warn(f"Video send failed: {vid_response.text[:200]}")
        except Exception as e:
            stats.warn(f"Video Telegram error: {e}")

    try:
        full_message = f"""
📊 *FULL METADATA*

🎯 *Search Keywords:*
{', '.join(script_data.get('search_keywords', []))}

📜 *Full Script:*
{script_data.get('script', '')[:800]}...

⚠️ *Warnings:*
{chr(10).join(runtime_summary.get('warnings', ['None'])) or 'None'}

🔗 *Artifact:* GitHub Actions Run
        """
        requests.post(
            f"{base_url}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": full_message[:4096],
                "parse_mode": "Markdown"
            },
            timeout=30
        )
        log.info("Full metadata message sent to Telegram")
    except Exception as e:
        stats.warn(f"Metadata message failed: {e}")

    return video_sent

def compress_video_for_telegram(input_path: str, output_path: str):
    log.info("Compressing video for Telegram...")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "32",
        "-c:a", "aac",
        "-b:a", "96k",
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
        "-movflags", "+faststart",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=180)
    if result.returncode != 0:
        stats.warn(f"Compression failed: {result.stderr.decode()[:200]}")

# ─────────────────────────────────────────────
# METADATA SAVE
# ─────────────────────────────────────────────

def save_metadata(
    script_data: dict,
    research_data: dict,
    audio_data: dict,
    runtime_summary: dict
):
    log.info("Saving metadata JSON...")
    metadata = {
        "generated_at": datetime.utcnow().isoformat(),
        "channel": "Ajeebology Shorts",
        "title": script_data.get("title", ""),
        "description": script_data.get("description", ""),
        "script": script_data.get("script", ""),
        "hook": script_data.get("hook", ""),
        "tags": script_data.get("tags", []),
        "hashtags": script_data.get("hashtags", []),
        "category": script_data.get("category", "Education"),
        "search_keywords": script_data.get("search_keywords", []),
        "pexels_search_terms": script_data.get("pexels_search_terms", []),
        "research_sources": research_data.get("sources", []),
        "topic": research_data.get("topic", ""),
        "audio_duration_seconds": audio_data.get("duration", 0),
        "words_per_second": audio_data.get("words_per_second", 0),
        "runtime": runtime_summary
    }

    meta_path = OUTPUT_DIR / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    script_path = OUTPUT_DIR / "script.txt"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(f"TITLE: {metadata['title']}\n\n")
        f.write(f"HOOK: {metadata['hook']}\n\n")
        f.write(f"SCRIPT:\n{metadata['script']}\n\n")
        f.write(f"TAGS: {', '.join(metadata['tags'])}\n\n")
        f.write(f"HASHTAGS: {' '.join(metadata['hashtags'])}\n\n")
        f.write(f"DESCRIPTION:\n{metadata['description']}\n\n")
        f.write(f"SOURCES:\n")
        for src in metadata["research_sources"]:
            f.write(f"  - {src}\n")

    log.info(f"Metadata saved: {meta_path}")
    log.info(f"Script saved: {script_path}")
    return meta_path

# ─────────────────────────────────────────────
# MAIN PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────

def run_pipeline():
    log.info("=" * 60)
    log.info("AJEEBOLOGY SHORTS PIPELINE STARTING")
    log.info("=" * 60)

    validate_environment()
    stats.mark("environment_validation")

    if TOPIC_OVERRIDE:
        topic = TOPIC_OVERRIDE
        log.info(f"Using topic override: {topic}")
    else:
        topic = random.choice(TOPIC_CATEGORIES)
        log.info(f"Auto-selected topic: {topic}")

    research_data = research_topic(topic)
    stats.mark("topic_research")

    script_data = generate_script(research_data)
    stats.mark("script_generation")

    audio_data = generate_tts(script_data["script"])
    stats.mark("tts_generation")

    total_duration = audio_data["duration"]
    log.info(f"Target video duration: {total_duration:.2f}s")

    search_terms = script_data.get("pexels_search_terms", [topic])
    if not search_terms:
        search_terms = [topic, "science", "space"]

    footage_clips = collect_footage(search_terms, total_duration)
    stats.mark("footage_collection")

    if not footage_clips:
        raise RuntimeError("No footage collected. Cannot continue pipeline.")

    segments = build_segment_list(footage_clips, total_duration)
    extracted_paths = extract_all_segments(segments)
    stats.mark("segment_extraction")

    if not extracted_paths:
        raise RuntimeError("No segments extracted. Cannot continue.")

    raw_concat = str(FOOTAGE_DIR / "raw_concat.mp4")
    concatenate_segments(extracted_paths, raw_concat)
    stats.mark("segment_concatenation")

    music_path = generate_background_music(total_duration)
    stats.mark("music_generation")

    mixed_audio = str(AUDIO_DIR / "mixed_audio.aac")
    mix_audio(audio_data["mp3_path"], music_path, total_duration, mixed_audio)
    stats.mark("audio_mixing")

    assembled_video = str(OUTPUT_DIR / "assembled.mp4")
    assemble_final_video(raw_concat, mixed_audio, assembled_video, total_duration)
    stats.mark("video_assembly")

    captioned_video = str(OUTPUT_DIR / "captioned.mp4")
    render_captions_on_video(assembled_video, audio_data["word_timings"], captioned_video)
    stats.mark("caption_rendering")

    if not Path(captioned_video).exists():
        log.warning("Captioned video missing. Using assembled video.")
        captioned_video = assembled_video

    final_video = str(OUTPUT_DIR / "final_video.mp4")
    add_intro_card(captioned_video, script_data.get("hook", ""), final_video)
    stats.mark("intro_card")

    if not Path(final_video).exists():
        log.warning("Final video missing. Using captioned video.")
        import shutil
        shutil.copy(captioned_video, final_video)

    unsplash_bg = fetch_unsplash_image(topic)
    thumbnail_path = generate_thumbnail(script_data["title"], unsplash_bg)
    stats.mark("thumbnail_generation")

    runtime_summary = stats.summary()
    save_metadata(script_data, research_data, audio_data, runtime_summary)
    stats.mark("metadata_save")

    telegram_ok = send_telegram_video(
        final_video,
        str(thumbnail_path),
        script_data,
        research_data,
        audio_data,
        runtime_summary
    )
    stats.mark("telegram_delivery")

    log.info("=" * 60)
    log.info("PIPELINE COMPLETED SUCCESSFULLY")
    log.info(f"Total time: {runtime_summary['total_runtime_seconds']}s")
    log.info(f"GitHub minutes used: {runtime_summary['github_minutes_used']}")
    log.info(f"Telegram delivery: {'✅' if telegram_ok else '⚠️ partial'}")
    log.info("=" * 60)

    return True

# ─────────────────────────────────────────────
# GLOBAL ERROR HANDLER
# ─────────────────────────────────────────────

def send_telegram_error(error_msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
        runtime_so_far = round(time.time() - stats.start_time, 2)
        message = f"""
❌ *AJEEBOLOGY PIPELINE FAILED*

🕐 *Failed at:* {runtime_so_far}s

💥 *Error:*
{error_msg[:800]}

⚠️ *Warnings before failure:*
{chr(10).join(stats.warnings[-5:]) or 'None'}

📋 *Steps completed:*
{chr(10).join([f"✅ {k}: {v}s" for k, v in stats.steps.items()]) or 'None'}

🔧 *Action Required:*
Check GitHub Actions logs for full traceback.
        """
        requests.post(
            f"{base_url}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4096],
                "parse_mode": "Markdown"
            },
            timeout=20
        )
        log.info("Error notification sent to Telegram")
    except Exception as e:
        log.warning(f"Could not send error to Telegram: {e}")

def cleanup_temp_files():
    log.info("Cleaning up temporary files...")
    temp_patterns = [
        FOOTAGE_DIR / "seg_*.mp4",
        FRAMES_DIR / "captions" / "cap_*.png",
        FOOTAGE_DIR / "concat_list.txt",
        OUTPUT_DIR / "assembled.mp4",
        OUTPUT_DIR / "captioned.mp4",
    ]
    removed = 0
    for pattern in temp_patterns:
        parent = pattern.parent
        glob_pattern = pattern.name
        try:
            for f in parent.glob(glob_pattern):
                f.unlink()
                removed += 1
        except Exception as e:
            log.warning(f"Cleanup error for {pattern}: {e}")
    log.info(f"Cleaned up {removed} temporary files")

def verify_final_output() -> bool:
    log.info("Verifying final output files...")
    final_video = OUTPUT_DIR / "final_video.mp4"
    thumbnail = OUTPUT_DIR / "thumbnail.jpg"
    metadata = OUTPUT_DIR / "metadata.json"

    all_ok = True

    if not final_video.exists():
        stats.error("final_video.mp4 missing")
        all_ok = False
    else:
        size_mb = final_video.stat().st_size / (1024*1024)
        if size_mb < 0.5:
            stats.error(f"final_video.mp4 too small: {size_mb:.2f}MB")
            all_ok = False
        else:
            log.info(f"final_video.mp4 OK ({size_mb:.1f}MB)")

        result = subprocess.run([
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(final_video)
        ], capture_output=True, text=True, timeout=15)

        if result.returncode == 0:
            probe = json.loads(result.stdout)
            duration = float(probe["format"].get("duration", 0))
            streams = probe.get("streams", [])
            has_video = any(s["codec_type"] == "video" for s in streams)
            has_audio = any(s["codec_type"] == "audio" for s in streams)

            log.info(f"Video duration: {duration:.2f}s")
            log.info(f"Has video stream: {has_video}")
            log.info(f"Has audio stream: {has_audio}")

            if not has_video:
                stats.error("Output has no video stream")
                all_ok = False
            if not has_audio:
                stats.warn("Output has no audio stream")
            if duration < 10:
                stats.error(f"Output too short: {duration:.2f}s")
                all_ok = False
        else:
            stats.warn("Could not probe final video")

    if not thumbnail.exists():
        stats.warn("thumbnail.jpg missing")
    else:
        size_kb = thumbnail.stat().st_size / 1024
        log.info(f"thumbnail.jpg OK ({size_kb:.0f}KB)")

    if not metadata.exists():
        stats.warn("metadata.json missing")
    else:
        log.info("metadata.json OK")

    return all_ok

# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    exit_code = 0
    try:
        log.info("Python version: " + sys.version)
        log.info("Working directory: " + str(Path.cwd()))
        log.info("Output directory: " + str(OUTPUT_DIR.absolute()))

        success = run_pipeline()

        output_ok = verify_final_output()

        if not output_ok:
            log.error("Output verification failed.")
            send_telegram_error(
                "Pipeline ran but output verification failed.\n"
                "Check artifacts for partial output."
            )
            exit_code = 1
        else:
            log.info("All output verified successfully.")
            cleanup_temp_files()
            exit_code = 0

    except EnvironmentError as e:
        msg = f"Environment error: {str(e)}"
        log.critical(msg)
        send_telegram_error(msg)
        exit_code = 1

    except RuntimeError as e:
        msg = f"Pipeline runtime error: {str(e)}"
        log.critical(msg)
        log.critical(traceback.format_exc())
        send_telegram_error(msg + "\n\n" + traceback.format_exc()[:400])
        exit_code = 1

    except KeyboardInterrupt:
        msg = "Pipeline interrupted by user"
        log.warning(msg)
        exit_code = 1

    except Exception as e:
        msg = f"Unexpected error: {str(e)}"
        log.critical(msg)
        log.critical(traceback.format_exc())
        send_telegram_error(msg + "\n\n" + traceback.format_exc()[:400])
        exit_code = 1

    finally:
        final_stats = stats.summary()
        log.info("=" * 60)
        log.info(f"PIPELINE EXIT — Code: {exit_code}")
        log.info(f"Total runtime: {final_stats['total_runtime_seconds']}s")
        log.info(f"GitHub minutes: {final_stats['github_minutes_used']}")
        log.info(f"Errors: {len(final_stats['errors'])}")
        log.info(f"Warnings: {len(final_stats['warnings'])}")
        log.info("=" * 60)
        sys.exit(exit_code)
