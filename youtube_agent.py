#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ajeebology Shorts
Single-file YouTube Shorts Automation System

Chunk 1:
- Imports
- Configuration
- Environment Validation
- Logging
- Cache System
- Utility Functions
- API Clients
- Topic Selection
- Research Engine

DO NOT RUN UNTIL ALL CHUNKS ARE COMBINED.
"""

import os
import re
import io
import json
import time
import math
import glob
import uuid
import shutil
import random
import hashlib
import logging
import pathlib
import tempfile
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests
import numpy as np

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageFilter,
)

from groq import Groq
from tavily import TavilyClient

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from pydub import (
    AudioSegment,
)

from gtts import gTTS

from telegram import Bot

# ============================================================
# CONFIGURATION
# ============================================================

ROOT = pathlib.Path(".")
OUTPUT_DIR = ROOT / "outputs"
CACHE_DIR = ROOT / "cache"
ASSET_CACHE_DIR = ROOT / "assets_cache"
LOG_DIR = ROOT / "logs"

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)
ASSET_CACHE_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

RUN_MODE = os.getenv("RUN_MODE", "render")
LANGUAGE = os.getenv("LANGUAGE", "hinglish")

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

TARGET_DURATION_MIN = 55
TARGET_DURATION_MAX = 65

CHANNEL_NAME = "Ajeebology Shorts"

VOICE_RATE = 145
VOICE_PITCH = 60
VOICE_GAP = 5

MAX_SCENES = 8
MIN_SCENES = 6

TOPICS = [
    "psychology fact",
    "space mystery",
    "human brain fact",
    "black hole mystery",
    "weird country fact",
    "strange science fact",
    "sleep psychology",
    "ancient mystery",
    "universe fact",
    "mind trick"
]

# ============================================================
# LOGGING
# ============================================================

LOG_FILE = LOG_DIR / "youtube_agent.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("Ajeebology")

# ============================================================
# ENVIRONMENT
# ============================================================

class Config:

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
    UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def validate_environment():

    required = [
        "GROQ_API_KEY",
        "TAVILY_API_KEY",
        "PEXELS_API_KEY",
        "UNSPLASH_ACCESS_KEY",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID"
    ]

    missing = []

    for key in required:
        if not os.getenv(key):
            missing.append(key)

    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}"
        )

    logger.info("Environment validation passed")


# ============================================================
# HELPERS
# ============================================================

def now_string():
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def random_topic():
    override = os.getenv("TOPIC_OVERRIDE")

    if override:
        return override

    return random.choice(TOPICS)


def clean_text(text: str) -> str:

    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    return text


def safe_filename(text: str) -> str:

    text = re.sub(r"[^a-zA-Z0-9_-]", "_", text)

    return text[:80]


def hash_string(text: str) -> str:

    return hashlib.md5(
        text.encode("utf-8")
    ).hexdigest()


def save_json(path, data):

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_json(path):

    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# CACHE MANAGER
# ============================================================

class CacheManager:

    def __init__(self):

        self.cache_dir = CACHE_DIR

    def path(self, key):

        return self.cache_dir / f"{key}.json"

    def get(self, key):

        file = self.path(key)

        if not file.exists():
            return None

        try:
            return load_json(file)

        except Exception:
            return None

    def set(self, key, value):

        file = self.path(key)

        save_json(file, value)


cache = CacheManager()

# ============================================================
# HTTP CLIENT
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "AjeebologyShortsBot/1.0"
    }
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2)
)
def http_get(url, **kwargs):

    r = SESSION.get(
        url,
        timeout=30,
        **kwargs
    )

    r.raise_for_status()

    return r


# ============================================================
# GROQ CLIENT
# ============================================================

class GroqClient:

    def __init__(self):

        self.client = Groq(
            api_key=Config.GROQ_API_KEY
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2)
    )
    def generate(self, prompt):

        completion = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.9,
            max_tokens=2000
        )

        return (
            completion
            .choices[0]
            .message
            .content
        )


# ============================================================
# TAVILY RESEARCH CLIENT
# ============================================================

class ResearchClient:

    def __init__(self):

        self.client = TavilyClient(
            api_key=Config.TAVILY_API_KEY
        )

    def search(self, query):

        cache_key = (
            "research_" +
            hash_string(query)
        )

        cached = cache.get(cache_key)

        if cached:
            logger.info(
                "Research cache hit"
            )
            return cached

        try:

            result = self.client.search(
                query=query,
                max_results=5
            )

            cache.set(
                cache_key,
                result
            )

            return result

        except Exception as e:

            logger.error(
                f"Tavily failed: {e}"
            )

            return {
                "results": []
            }


# ============================================================
# RESEARCH ENGINE
# ============================================================

class TopicResearcher:

    def __init__(self):

        self.research = ResearchClient()

    def build_research_query(
        self,
        topic
    ):

        return (
            f"{topic} surprising fact "
            f"science explanation"
        )

    def gather(self, topic):

        logger.info(
            f"Researching: {topic}"
        )

        query = self.build_research_query(
            topic
        )

        data = self.research.search(
            query
        )

        summaries = []

        for item in data.get(
            "results",
            []
        ):

            content = item.get(
                "content",
                ""
            )

            if content:
                summaries.append(content)

        return "\n\n".join(
            summaries
        )[:6000]


# ============================================================
# SCRIPT GENERATOR
# ============================================================

class ScriptGenerator:

    def __init__(self):

        self.groq = GroqClient()

    def build_prompt(
        self,
        topic,
        research
    ):

        return f"""
You are an elite YouTube Shorts writer.

Language:
{LANGUAGE}

Topic:
{topic}

Research:
{research}

Requirements:

1. Hook in first 2 seconds.
2. Curiosity gap.
3. Escalation.
4. Surprise reveal.
5. CTA.

Output JSON:

{{
 "title":"",
 "segments":[
   {{
     "text":"..."
   }}
 ],
 "cta":"..."
}}

6-8 segments.
55-65 second video.
Male narration.
"""


        return clean_text(prompt)

    def generate_script(
        self,
        topic,
        research
    ):

        prompt = self.build_prompt(
            topic,
            research
        )

        raw = self.groq.generate(
            prompt
        )

        try:

            start = raw.find("{")
            end = raw.rfind("}")

            payload = raw[start:end+1]

            data = json.loads(
                payload
            )

            return data

        except Exception as e:

            logger.error(
                f"Script parse failed: {e}"
            )

            return {
                "title": f"Amazing {topic}",
                "segments": [
                    {
                        "text":
                        "Kya aap jante hain ek ajeeb fact?"
                    },
                    {
                        "text":
                        "Yeh sach hai aur scientists bhi hairan hain."
                    },
                    {
                        "text":
                        "Iska reason aur bhi shocking hai."
                    },
                    {
                        "text":
                        "Aur isi wajah se duniya ise fascinating maanti hai."
                    },
                    {
                        "text":
                        "Agar aapko yeh fact pasand aaya to comment karo."
                    }
                ],
                "cta":
                "Like, share aur subscribe."
            }


# ============================================================
# METADATA GENERATOR
# ============================================================

class MetadataGenerator:

    def generate(
        self,
        topic,
        script
    ):

        title = script.get(
            "title",
            topic
        )

        segments = script.get(
            "segments",
            []
        )

        full_text = []

        for seg in segments:

            txt = seg.get(
                "text",
                ""
            )

            full_text.append(txt)

        description = "\n".join(
            full_text
        )

        description += (
            "\n\nLike • Share • Subscribe "
            "for more amazing facts."
        )

        tags = [
            "shorts",
            "facts",
            "psychology",
            "space",
            "science",
            "viral",
            "youtube shorts",
            "knowledge",
            "interesting facts",
            topic
        ]

        hashtags = [
            "#shorts",
            "#facts",
            "#science",
            "#viral",
            "#knowledge"
        ]

        return {
            "title": title,
            "description": description,
            "tags": tags,
            "hashtags": hashtags
        }


# ============================================================
# PEXELS CLIENT
# ============================================================

class PexelsClient:

    BASE_URL = (
        "https://api.pexels.com/videos/search"
    )

    def __init__(self):

        self.api_key = (
            Config.PEXELS_API_KEY
        )

    def search_videos(
        self,
        query,
        per_page=10
    ):

        cache_key = (
            "pexels_" +
            hash_string(query)
        )

        cached = cache.get(
            cache_key
        )

        if cached:
            return cached

        try:

            response = http_get(
                self.BASE_URL,
                headers={
                    "Authorization":
                    self.api_key
                },
                params={
                    "query": query,
                    "per_page": per_page
                }
            )

            data = response.json()

            cache.set(
                cache_key,
                data
            )

            return data

        except Exception as e:

            logger.error(
                f"Pexels error: {e}"
            )

            return {
                "videos": []
            }


# ============================================================
# UNSPLASH CLIENT
# ============================================================

class UnsplashClient:

    BASE_URL = (
        "https://api.unsplash.com/search/photos"
    )

    def __init__(self):

        self.api_key = (
            Config.UNSPLASH_ACCESS_KEY
        )

    def search_images(
        self,
        query,
        per_page=10
    ):

        cache_key = (
            "unsplash_" +
            hash_string(query)
        )

        cached = cache.get(
            cache_key
        )

        if cached:
            return cached

        try:

            response = http_get(
                self.BASE_URL,
                params={
                    "query": query,
                    "per_page": per_page,
                    "client_id":
                    self.api_key
                }
            )

            data = response.json()

            cache.set(
                cache_key,
                data
            )

            return data

        except Exception as e:

            logger.error(
                f"Unsplash error: {e}"
            )

            return {
                "results": []
            }


# ============================================================
# ASSET CACHE
# ============================================================

class AssetCache:

    def __init__(self):

        self.root = (
            ASSET_CACHE_DIR
        )

    def download(
        self,
        url
    ):

        ext = (
            url.split("?")[0]
            .split(".")[-1]
        )

        if len(ext) > 6:
            ext = "bin"

        filename = (
            hash_string(url)
            + "."
            + ext
        )

        path = (
            self.root /
            filename
        )

        if path.exists():

            return str(path)

        try:

            r = http_get(
                url,
                stream=True
            )

            with open(
                path,
                "wb"
            ) as f:

                for chunk in r.iter_content(
                    8192
                ):
                    f.write(chunk)

            return str(path)

        except Exception as e:

            logger.error(
                f"Download failed: {e}"
            )

            return None


asset_cache = AssetCache()

# ============================================================
# ASSET COLLECTOR
# ============================================================

class AssetCollector:

    def __init__(self):

        self.pexels = (
            PexelsClient()
        )

        self.unsplash = (
            UnsplashClient()
        )

    def collect(
        self,
        topic,
        scene_count
    ):

        assets = []

        video_data = (
            self.pexels
            .search_videos(topic)
        )

        image_data = (
            self.unsplash
            .search_images(topic)
        )

        videos = (
            video_data.get(
                "videos",
                []
            )
        )

        images = (
            image_data.get(
                "results",
                []
            )
        )

        v_index = 0
        i_index = 0

        for idx in range(
            scene_count
        ):

            use_video = (
                idx % 2 == 0
            )

            if (
                use_video and
                v_index < len(videos)
            ):

                files = (
                    videos[v_index]
                    .get(
                        "video_files",
                        []
                    )
                )

                v_index += 1

                if files:

                    best = sorted(
                        files,
                        key=lambda x:
                        x.get(
                            "width",
                            0
                        ),
                        reverse=True
                    )[0]

                    assets.append(
                        {
                            "type":
                            "video",
                            "url":
                            best["link"]
                        }
                    )

                    continue

            if (
                i_index <
                len(images)
            ):

                image = (
                    images[i_index]
                )

                i_index += 1

                assets.append(
                    {
                        "type":
                        "image",
                        "url":
                        image["urls"][
                            "regular"
                        ]
                    }
                )

        downloaded = []

        for item in assets:

            path = (
                asset_cache.download(
                    item["url"]
                )
            )

            if path:

                item["path"] = path

                downloaded.append(
                    item
                )

        return downloaded


# ============================================================
# SCENE PLANNER
# ============================================================

class ScenePlanner:

    def create(
        self,
        script
    ):

        segments = (
            script.get(
                "segments",
                []
            )
        )

        count = len(
            segments
        )

        duration = 60

        per_scene = (
            duration /
            max(count, 1)
        )

        scenes = []

        for i, seg in enumerate(
            segments
        ):

            scenes.append(
                {
                    "index": i,
                    "text":
                    seg.get(
                        "text",
                        ""
                    ),
                    "duration":
                    per_scene
                }
            )

        return scenes


# ============================================================
# AUDIO ENGINE
# ============================================================

class AudioEngine:

    def __init__(self):

        pass

    def voice_path(self):

        return str(
            OUTPUT_DIR /
            "voice.wav"
        )

    def generate_espeak(
        self,
        text
    ):

        output = (
            self.voice_path()
        )

        cmd = [
            "espeak",
            "-v",
            "hi+m1",
            "-s",
            str(VOICE_RATE),
            "-p",
            str(VOICE_PITCH),
            "-g",
            str(VOICE_GAP),
            "-w",
            output,
            text
        ]

        try:

            subprocess.run(
                cmd,
                check=True
            )

            return output

        except Exception as e:

            logger.error(
                f"espeak failed: {e}"
            )

            return None

    def generate_gtts(
        self,
        text
    ):

        mp3 = (
            OUTPUT_DIR /
            "voice.mp3"
        )

        tts = gTTS(
            text=text,
            lang="hi"
        )

        tts.save(
            str(mp3)
        )

        return str(mp3)



# ============================================================
# AUDIO PROCESSING
# ============================================================

class AudioProcessor:

    def get_duration(self, audio_file):

        try:

            audio = AudioSegment.from_file(
                audio_file
            )

            return (
                len(audio) / 1000.0
            )

        except Exception as e:

            logger.error(
                f"Duration error: {e}"
            )

            return 0

    def normalize(
        self,
        audio_file
    ):

        try:

            audio = AudioSegment.from_file(
                audio_file
            )

            target = -16

            change = (
                target -
                audio.dBFS
            )

            normalized = (
                audio.apply_gain(
                    change
                )
            )

            out = (
                OUTPUT_DIR /
                "voice_normalized.wav"
            )

            normalized.export(
                out,
                format="wav"
            )

            return str(out)

        except Exception as e:

            logger.error(
                f"Normalize error: {e}"
            )

            return audio_file

    def create_silence(
        self,
        seconds
    ):

        audio = (
            AudioSegment.silent(
                duration=int(
                    seconds * 1000
                )
            )
        )

        out = (
            OUTPUT_DIR /
            "silence.wav"
        )

        audio.export(
            out,
            format="wav"
        )

        return str(out)


audio_processor = AudioProcessor()

# ============================================================
# MUSIC ENGINE
# ============================================================

class MusicEngine:

    def create_background_music(self):

        silence = (
            AudioSegment.silent(
                duration=65000
            )
        )

        path = (
            OUTPUT_DIR /
            "background.wav"
        )

        silence.export(
            path,
            format="wav"
        )

        return str(path)

    def duck_music(
        self,
        music_file,
        voice_file
    ):

        try:

            music = AudioSegment.from_file(
                music_file
            )

            voice = AudioSegment.from_file(
                voice_file
            )

            music = music - 18

            mixed = (
                music.overlay(
                    voice
                )
            )

            output = (
                OUTPUT_DIR /
                "mixed_audio.wav"
            )

            mixed.export(
                output,
                format="wav"
            )

            return str(output)

        except Exception as e:

            logger.error(
                f"Duck failed: {e}"
            )

            return voice_file


music_engine = MusicEngine()

# ============================================================
# FFMPEG HELPERS
# ============================================================

class FFmpeg:

    @staticmethod
    def run(cmd):

        logger.info(
            " ".join(cmd)
        )

        subprocess.run(
            cmd,
            check=True
        )

    @staticmethod
    def probe_duration(path):

        try:

            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            return float(
                result.stdout.strip()
            )

        except Exception:

            return 5.0


# ============================================================
# INTRO BUILDER
# ============================================================

class IntroBuilder:

    def build(self):

        output = (
            OUTPUT_DIR /
            "intro.mp4"
        )

        filter_text = (
            f"drawtext="
            f"text='{CHANNEL_NAME}':"
            f"fontsize=80:"
            f"x=(w-text_w)/2:"
            f"y=(h-text_h)/2:"
            f"fontcolor=white"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:d=2",
            "-vf",
            filter_text,
            "-pix_fmt",
            "yuv420p",
            str(output)
        ]

        FFmpeg.run(cmd)

        return str(output)


# ============================================================
# OUTRO BUILDER
# ============================================================

class OutroBuilder:

    def build(self):

        output = (
            OUTPUT_DIR /
            "outro.mp4"
        )

        text = (
            "Subscribe For More Facts"
        )

        filter_text = (
            f"drawtext="
            f"text='{text}':"
            f"fontsize=70:"
            f"x=(w-text_w)/2:"
            f"y=(h-text_h)/2:"
            f"fontcolor=white"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:d=2",
            "-vf",
            filter_text,
            "-pix_fmt",
            "yuv420p",
            str(output)
        ]

        FFmpeg.run(cmd)

        return str(output)


# ============================================================
# SCENE RENDERER
# ============================================================

class SceneRenderer:

    def image_scene(
        self,
        image_path,
        duration,
        index
    ):

        output = (
            OUTPUT_DIR /
            f"scene_{index}.mp4"
        )

        vf = (
            "scale=1080:1920,"
            "zoompan="
            "z='min(zoom+0.0015,1.3)':"
            "d=125"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            image_path,
            "-t",
            str(duration),
            "-vf",
            vf,
            "-pix_fmt",
            "yuv420p",
            str(output)
        ]

        FFmpeg.run(cmd)

        return str(output)

    def video_scene(
        self,
        video_path,
        duration,
        index
    ):

        output = (
            OUTPUT_DIR /
            f"scene_{index}.mp4"
        )

        vf = (
            "scale=1080:1920,"
            "crop=1080:1920"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-t",
            str(duration),
            "-vf",
            vf,
            "-an",
            str(output)
        ]

        FFmpeg.run(cmd)

        return str(output)

    def render(
        self,
        asset,
        duration,
        index
    ):

        if (
            asset["type"]
            == "image"
        ):

            return self.image_scene(
                asset["path"],
                duration,
                index
            )

        return self.video_scene(
            asset["path"],
            duration,
            index
        )


scene_renderer = SceneRenderer()

# ============================================================
# CAPTION ENGINE
# ============================================================

class CaptionEngine:

    def create_srt(
        self,
        scenes
    ):

        srt = (
            OUTPUT_DIR /
            "captions.srt"
        )

        current = 0.0

        lines = []

        for idx, scene in enumerate(
            scenes,
            start=1
        ):

            start = current
            end = (
                current +
                scene["duration"]
            )

            current = end

            def fmt(sec):

                ms = int(
                    (sec % 1) * 1000
                )

                total = int(sec)

                h = total // 3600
                m = (
                    total % 3600
                ) // 60

                s = total % 60

                return (
                    f"{h:02}:{m:02}:{s:02},{ms:03}"
                )

            lines.append(
                str(idx)
            )

            lines.append(
                f"{fmt(start)} --> {fmt(end)}"
            )

            lines.append(
                scene["text"]
            )

            lines.append("")


        with open(
            srt,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                "\n".join(lines)
            )

        return str(srt)


caption_engine = CaptionEngine()

# ============================================================
# VIDEO ASSEMBLER
# ============================================================

class VideoAssembler:

    def create_concat_file(
        self,
        files
    ):

        concat = (
            OUTPUT_DIR /
            "concat.txt"
        )

        with open(
            concat,
            "w",
            encoding="utf-8"
        ) as f:

            for item in files:

                if os.path.exists(item):

                    f.write(
                        f"file '{os.path.abspath(item)}'\n"
                    )

        return str(concat)

    def concat(
        self,
        files
    ):

        concat_file = (
            self.create_concat_file(
                files
            )
        )

        output = (
            OUTPUT_DIR /
            "video_base.mp4"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file,
            "-c",
            "copy",
            str(output)
        ]

        try:

            FFmpeg.run(cmd)

        except Exception:

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_file,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                str(output)
            ]

            FFmpeg.run(cmd)

        return str(output)

    def burn_captions(
        self,
        video,
        srt_file
    ):

        output = (
            OUTPUT_DIR /
            "video_captioned.mp4"
        )

        vf = (
            f"subtitles={srt_file}"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-vf",
            vf,
            "-c:a",
            "copy",
            str(output)
        ]

        FFmpeg.run(cmd)

        return str(output)

    def add_audio(
        self,
        video,
        audio
    ):

        output = (
            OUTPUT_DIR /
            "final_video.mp4"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-i",
            audio,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output)
        ]

        FFmpeg.run(cmd)

        return str(output)


video_assembler = VideoAssembler()

# ============================================================
# THUMBNAIL ENGINE
# ============================================================

class ThumbnailGenerator:

    def create(
        self,
        video_path,
        title
    ):

        frame = (
            OUTPUT_DIR /
            "frame.jpg"
        )

        thumb = (
            OUTPUT_DIR /
            "thumbnail.jpg"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-ss",
            "00:00:03",
            "-vframes",
            "1",
            str(frame)
        ]

        FFmpeg.run(cmd)

        image = Image.open(
            frame
        )

        image = image.resize(
            (
                1080,
                1920
            )
        )

        overlay = Image.new(
            "RGBA",
            image.size,
            (0, 0, 0, 80)
        )

        image = Image.alpha_composite(
            image.convert("RGBA"),
            overlay
        )

        draw = ImageDraw.Draw(
            image
        )

        try:

            font = (
                ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    90
                )
            )

        except Exception:

            font = (
                ImageFont.load_default()
            )

        text = (
            title[:40]
        )

        draw.text(
            (
                50,
                1300
            ),
            text,
            fill="white",
            font=font
        )

        draw.text(
            (
                50,
                1600
            ),
            CHANNEL_NAME,
            fill="yellow",
            font=font
        )

        image = image.filter(
            ImageFilter.SHARPEN
        )

        image.convert(
            "RGB"
        ).save(
            thumb,
            quality=95
        )

        return str(thumb)


thumbnail_generator = (
    ThumbnailGenerator()
)

# ============================================================
# TELEGRAM DELIVERY
# ============================================================

class TelegramSender:

    def __init__(self):

        self.token = (
            Config.TELEGRAM_TOKEN
        )

        self.chat_id = (
            Config.TELEGRAM_CHAT_ID
        )

    def send_video(
        self,
        video,
        caption
    ):

        try:

            bot = Bot(
                token=self.token
            )

            with open(
                video,
                "rb"
            ) as fp:

                bot.send_video(
                    chat_id=self.chat_id,
                    video=fp,
                    caption=caption[:1000]
                )

            logger.info(
                "Telegram video sent"
            )

        except Exception as e:

            logger.error(
                f"Telegram video failed: {e}"
            )

    def send_photo(
        self,
        photo,
        caption=""
    ):

        try:

            bot = Bot(
                token=self.token
            )

            with open(
                photo,
                "rb"
            ) as fp:

                bot.send_photo(
                    chat_id=self.chat_id,
                    photo=fp,
                    caption=caption[:1000]
                )

        except Exception as e:

            logger.error(
                f"Telegram photo failed: {e}"
            )


telegram_sender = (
    TelegramSender()
)

# ============================================================
# PIPELINE
# ============================================================

class ShortsPipeline:

    def __init__(self):

        self.researcher = (
            TopicResearcher()
        )

        self.writer = (
            ScriptGenerator()
        )

        self.assets = (
            AssetCollector()
        )

        self.planner = (
            ScenePlanner()
        )

        self.audio = (
            AudioEngine()
        )

        self.meta = (
            MetadataGenerator()
        )

    def build_voice(
        self,
        scenes
    ):

        script_text = []

        for scene in scenes:

            script_text.append(
                scene["text"]
            )

        narration = (
            " ".join(
                script_text
            )
        )

        voice = (
            self.audio
            .generate_espeak(
                narration
            )
        )

        if not voice:

            voice = (
                self.audio
                .generate_gtts(
                    narration
                )
            )

        return voice

    def render(self):

        topic = random_topic()

        logger.info(
            f"Topic: {topic}"
        )

        research = (
            self.researcher
            .gather(topic)
        )

        script = (
            self.writer
            .generate_script(
                topic,
                research
            )
        )

        scenes = (
            self.planner
            .create(script)
        )

        assets = (
            self.assets
            .collect(
                topic,
                len(scenes)
            )
        )

        if not assets:

            raise RuntimeError(
                "No assets found"
            )

        voice = (
            self.build_voice(
                scenes
            )
        )

        voice = (
            audio_processor
            .normalize(
                voice
            )
        )

        music = (
            music_engine
            .create_background_music()
        )

        mixed_audio = (
            music_engine
            .duck_music(
                music,
                voice
            )
        )

        intro = (
            IntroBuilder()
            .build()
        )

        outro = (
            OutroBuilder()
            .build()
        )

        rendered = []

        rendered.append(
            intro
        )

        for i, scene in enumerate(
            scenes
        ):

            asset = (
                assets[
                    i % len(assets)
                ]
            )

            rendered.append(
                scene_renderer.render(
                    asset,
                    scene["duration"],
                    i
                )
            )

        rendered.append(
            outro
        )

        base_video = (
            video_assembler
            .concat(
                rendered
            )
        )

        srt = (
            caption_engine
            .create_srt(
                scenes
            )
        )

        captioned = (
            video_assembler
            .burn_captions(
                base_video,
                srt
            )
        )

        final_video = (
            video_assembler
            .add_audio(
                captioned,
                mixed_audio
            )
        )

        metadata = (
            self.meta.generate(
                topic,
                script
            )
        )

        thumb = (
            thumbnail_generator
            .create(
                final_video,
                metadata["title"]
            )
        )

        save_json(
            OUTPUT_DIR /
            "metadata.json",
            metadata
        )

        telegram_sender.send_video(
            final_video,
            metadata["title"]
        )

        telegram_sender.send_photo(
            thumb,
            metadata["title"]
        )

        logger.info(
            "Pipeline complete"
        )

        return {
            "video":
            final_video,
            "thumbnail":
            thumb,
            "metadata":
            metadata
        }


# ============================================================
# MAIN
# ============================================================

def main():

    validate_environment()

    logger.info(
        f"Mode: {RUN_MODE}"
    )

    if RUN_MODE == "validate":

        logger.info(
            "Validation successful"
        )

        return

    if RUN_MODE == "preview":

        topic = random_topic()

        researcher = (
            TopicResearcher()
        )

        writer = (
            ScriptGenerator()
        )

        research = (
            researcher.gather(
                topic
            )
        )

        script = (
            writer.generate_script(
                topic,
                research
            )
        )

        print(
            json.dumps(
                script,
                indent=2,
                ensure_ascii=False
            )
        )

        return

    pipeline = (
        ShortsPipeline()
    )

    pipeline.render()


if __name__ == "__main__":

    main()
