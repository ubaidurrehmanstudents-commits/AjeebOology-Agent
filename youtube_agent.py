#!/usr/bin/env python3
"""
Ajeebology Shorts - Fully Automated YouTube Shorts Pipeline
Single-file implementation for GitHub Actions Free Tier.
All functionality is contained in this one file.
"""

import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

try:
    import groq
except ImportError:
    groq = None
try:
    import tavily
except ImportError:
    tavily = None
try:
    import edge_tts
except ImportError:
    edge_tts = None


# =============================================================================
# CONSTANTS
# =============================================================================

CATEGORIES = ["psychology", "space", "weird"]
CATEGORY_EMOJIS = {"psychology": "🧠", "space": "🚀", "weird": "👽"}

OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")
SEGMENTS_DIR = TEMP_DIR / "segments"
FONTS_DIR = TEMP_DIR / "fonts"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
TARGET_DURATION_MIN = 55
TARGET_DURATION_MAX = 65

GROQ_MODEL = "mixtral-8x7b-32768"
TTS_VOICE = "hi-IN-SwaraNeural"
TTS_VOICE_FALLBACK = "en-IN-NeerjaNeural"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%H:%M:%S"

DEFAULT_CATEGORY_PROMPTS = {
    "psychology": "Interesting psychology facts about human behavior and mind",
    "space": "Amazing space facts and discoveries",
    "weird": "Weird and unbelievable facts from around the world"
}

FONT_STYLES = {
    "noto_devanagari": {
        "url": "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
        "name": "NotoSansDevanagari-VariableFont_wdth,wght.ttf",
        "family": "Noto Sans Devanagari"
    },
    "noto": {
        "url": "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf",
        "name": "NotoSans-VariableFont_wdth,wght.ttf",
        "family": "Noto Sans"
    }
}


# =============================================================================
# LOGGING
# =============================================================================

def setup_logging():
    log_level = logging.DEBUG if os.environ.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger(__name__)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def retry(max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0,
          exceptions: tuple = (Exception,)):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        wait = delay * (backoff ** (attempt - 1))
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Attempt {attempt}/{max_attempts} failed: {e}. "
                                       f"Retrying in {wait:.1f}s...")
                        time.sleep(wait)
                    else:
                        logger = logging.getLogger(__name__)
                        logger.error(f"All {max_attempts} attempts failed: {e}")
            raise last_exc
        return wrapper
    return decorator


def validate_environment() -> bool:
    logger = logging.getLogger(__name__)
    required_secrets = [
        "GROQ_API_KEY",
        "TAVILY_API_KEY",
        "PEXELS_API_KEY",
        "UNSPLASH_ACCESS_KEY",
        "TELEGRAM_TOKEN",
        "TELEGRAM_CHAT_ID"
    ]
    all_ok = True
    for secret in required_secrets:
        if not os.environ.get(secret):
            logger.error(f"Missing required secret: {secret}")
            all_ok = False
    if not all_ok:
        logger.error("Environment validation failed. Set all required secrets.")
        return False
    logger.info("All required secrets are present")
    return True


def setup_directories():
    for d in [OUTPUT_DIR, TEMP_DIR, SEGMENTS_DIR, FONTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    logging.getLogger(__name__).info("Directories created")


def cleanup_directories(keep_output: bool = True):
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
    logging.getLogger(__name__).info("Temp directories cleaned")


def time_ms_to_ass(t_ms: float) -> str:
    hours = int(t_ms // 3600000)
    minutes = int((t_ms % 3600000) // 60000)
    seconds = int((t_ms % 60000) // 1000)
    centiseconds = int((t_ms % 1000) // 10)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def seconds_to_ass(t_sec: float) -> str:
    return time_ms_to_ass(t_sec * 1000)


def run_ffmpeg(cmd: List[str], timeout: int = 300,
               description: str = "ffmpeg") -> subprocess.CompletedProcess:
    logger = logging.getLogger(__name__)
    logger.debug(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            logger.error(f"{description} failed (code {result.returncode})")
            logger.error(f"STDERR: {result.stderr[:2000]}")
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result
    except subprocess.TimeoutExpired:
        logger.error(f"{description} timed out after {timeout}s")
        raise


def get_default_font_path() -> Optional[str]:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-VariableFont_wdth,wght.ttf",
        str(FONTS_DIR / "NotoSansDevanagari-VariableFont_wdth,wght.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        str(FONTS_DIR / "NotoSans-VariableFont_wdth,wght.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    font_dir = os.path.expanduser("~/.fonts")
    if os.path.exists(font_dir):
        for fname in os.listdir(font_dir):
            if fname.endswith((".ttf", ".otf")):
                fpath = os.path.join(font_dir, fname)
                try:
                    from PIL import ImageFont
                    ImageFont.truetype(fpath, 36)
                    return fpath
                except Exception:
                    continue
    return None


def install_font() -> Optional[str]:
    logger = logging.getLogger(__name__)
    existing = get_default_font_path()
    if existing and "Devanagari" in existing:
        logger.info(f"Font already available: {existing}")
        return existing

    font_info = FONT_STYLES["noto_devanagari"]
    font_path = FONTS_DIR / font_info["name"]
    if font_path.exists():
        logger.info(f"Font already downloaded: {font_path}")
        target_dir = os.path.expanduser("~/.fonts")
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(str(font_path), os.path.join(target_dir, font_info["name"]))
        try:
            subprocess.run(["fc-cache", "-f"], capture_output=True, timeout=30)
        except Exception:
            pass
        return str(font_path)

    try:
        logger.info(f"Downloading font: {font_info['url']}")
        resp = requests.get(font_info["url"], timeout=60)
        resp.raise_for_status()
        FONTS_DIR.mkdir(parents=True, exist_ok=True)
        font_path.write_bytes(resp.content)
        logger.info(f"Font saved to {font_path}")

        target_dir = os.path.expanduser("~/.fonts")
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(str(font_path), os.path.join(target_dir, font_info["name"]))
        try:
            subprocess.run(["fc-cache", "-f"], capture_output=True, timeout=30)
        except Exception:
            pass
        return str(font_path)
    except Exception as e:
        logger.warning(f"Font download failed: {e}")
        fallback = get_default_font_path()
        if fallback:
            return fallback
        return None


def write_json_metadata(metadata: dict):
    path = OUTPUT_DIR / "metadata.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def github_summary(text: str):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


# =============================================================================
# TOPIC SELECTION & RESEARCH
# =============================================================================

def select_category() -> str:
    override = os.environ.get("CATEGORY_OVERRIDE", "auto")
    if override and override.lower() in CATEGORIES:
        return override.lower()
    return random.choice(CATEGORIES)


def select_topic(category: str) -> str:
    override = os.environ.get("TOPIC_OVERRIDE", "")
    if override:
        return override
    prompts = {
        "psychology": [
            "fascinating psychology facts about human behavior",
            "mind tricks your brain plays on you",
            "psychological facts about love and attraction",
            "dark psychology facts that explain human nature",
            "cognitive biases that control your decisions"
        ],
        "space": [
            "mind blowing space facts",
            "strangest things in the universe",
            "facts about black holes and neutron stars",
            "amazing discoveries in our solar system",
            "weirdest planets ever discovered"
        ],
        "weird": [
            "strangest laws still on the books",
            "weirdest historical facts nobody knows",
            "bizarre medical conditions that exist",
            "strangest animal facts in the world",
            "most unusual traditions around the world"
        ]
    }
    return random.choice(prompts.get(category, prompts["psychology"]))


@retry(max_attempts=3, delay=2.0, exceptions=(Exception,))
def research_topic(topic: str) -> Dict[str, Any]:
    logger = logging.getLogger(__name__)
    logger.info(f"Researching: {topic}")

    try:
        tavily_client = tavily.Client(api_key=os.environ["TAVILY_API_KEY"])
        response = tavily_client.search(
            query=topic,
            search_depth="advanced",
            max_results=5,
            include_answer=True
        )
        logger.info(f"Tavily research complete: {len(response.get('results', []))} sources")
        return response
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        logger.info("Falling back to basic search format")
        return {
            "answer": f"Research results for: {topic}",
            "results": [
                {"title": topic, "url": "", "content": f"Information about {topic}"}
            ]
        }


# =============================================================================
# SCRIPT GENERATION
# =============================================================================

@retry(max_attempts=3, delay=3.0, exceptions=(Exception,))
def generate_script(category: str, topic: str,
                    research: Dict[str, Any]) -> List[Dict[str, Any]]:
    logger = logging.getLogger(__name__)

    groq_client = groq.Client(api_key=os.environ["GROQ_API_KEY"])

    research_text = ""
    if research.get("answer"):
        research_text += f"Summary: {research['answer']}\n"
    for i, r in enumerate(research.get("results", [])[:3]):
        content = r.get("content", "")[:500]
        research_text += f"Source {i+1}: {content}\n"

    prompt = f"""You are a professional YouTube Shorts scriptwriter for the channel "Ajeebology Shorts".

Your task is to create a 55-65 second video script in HINGLISH (Hindi + English mix).

CATEGORY: {category}
TOPIC: {topic}

RESEARCH DATA:
{research_text}

REQUIREMENTS:
- Duration: 55-65 seconds when spoken
- Language: Hinglish (natural mix of Hindi and English, spoken style)
- Tone: Engaging, slightly dramatic, mysterious yet educational
- Format: 5-7 quick facts/segments
- Each segment must be visually distinct

OUTPUT FORMAT (JSON ONLY, no other text):
{{
  "title": "Catchy title in Hinglish (max 60 chars)",
  "description": "SEO description in Hinglish (2-3 lines)",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3"],
  "segments": [
    {{
      "text": "Spoken text in Hinglish for this segment",
      "keywords": ["keyword1", "keyword2"],
      "visual_style": "zoom_in or pan or static or reveal"
    }}
  ]
}}

IMPORTANT:
- Each segment should be 8-15 seconds when spoken
- Segments should flow naturally from one to the next
- Keywords should be search terms for Pexels/Unsplash footage
- Make every second count - no filler content
- First segment should be a strong hook
- Last segment should be a call to action (follow for more)

Return ONLY valid JSON. No markdown, no explanation."""

    logger.info("Generating script via Groq...")
    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": "You are a YouTube Shorts scriptwriter. Output only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=4000
    )

    raw = completion.choices[0].message.content.strip()
    logger.debug(f"Groq response length: {len(raw)} chars")

    json_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if json_match:
        raw = json_match.group()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        logger.debug(f"Raw response: {raw[:1000]}")
        raise ValueError(f"Script generation returned invalid JSON: {e}")

    if not data.get("segments") or len(data["segments"]) < 3:
        logger.warning("Too few segments, adjusting...")
        segments = data.get("segments", [])
        while len(segments) < 5:
            segments.append({
                "text": f"Amazing fact about {topic} that will surprise you!",
                "keywords": [topic, category, "facts"],
                "visual_style": "zoom_in"
            })
        data["segments"] = segments

    logger.info(f"Script generated: {data.get('title', 'Untitled')} "
                f"with {len(data['segments'])} segments")
    return data


# =============================================================================
# TTS - TEXT TO SPEECH
# =============================================================================

def parse_srt_word_timestamps(srt_content: str) -> List[Dict[str, Any]]:
    entries = []
    block_pattern = re.compile(
        r'(\d+)\s*\n(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*\n(.+?)(?=\n\s*\n|\n\d+\s*\n|\Z)',
        re.DOTALL
    )
    for match in block_pattern.finditer(srt_content + "\n\n"):
        idx = int(match.group(1))
        start_str = match.group(2).replace(",", ".")
        end_str = match.group(3).replace(",", ".")
        word = match.group(4).strip().replace("\n", " ")

        start_parts = start_str.split(":")
        end_parts = end_str.split(":")
        start_ms = (int(start_parts[0]) * 3600 + int(start_parts[1]) * 60
                    + float(start_parts[2])) * 1000
        end_ms = (int(end_parts[0]) * 3600 + int(end_parts[1]) * 60
                  + float(end_parts[2])) * 1000

        entries.append({
            "index": idx,
            "word": word,
            "start_ms": start_ms,
            "end_ms": end_ms
        })
    return entries


async def _generate_tts_async(text: str, audio_path: str,
                              voice: str) -> List[Dict[str, Any]]:
    logger = logging.getLogger(__name__)
    logger.info(f"Generating TTS with voice: {voice}")

    communicate = edge_tts.Communicate(text, voice)
    submaker = edge_tts.SubMaker()

    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "Word":
                submaker.feed(chunk)

    srt_content = submaker.generate_srt()
    words = parse_srt_word_timestamps(srt_content)
    logger.info(f"TTS generated: {len(words)} words")
    return words


def generate_voiceover(text: str, audio_path: str) -> List[Dict[str, Any]]:
    logger = logging.getLogger(__name__)
    words = []

    try:
        if edge_tts is None:
            raise ImportError("edge_tts not installed")
        words = asyncio.run(
            _generate_tts_async(text, audio_path, TTS_VOICE)
        )
        if not words:
            raise ValueError("No word timestamps generated")
    except Exception as e:
        logger.warning(f"Primary TTS failed: {e}. Trying fallback voice...")
        try:
            words = asyncio.run(
                _generate_tts_async(text, audio_path, TTS_VOICE_FALLBACK)
            )
        except Exception as e2:
            logger.error(f"Fallback TTS also failed: {e2}")
            raise

    if not words:
        logger.warning("No word timestamps from TTS. Generating synthetic timing.")
        word_count = len(text.split())
        total_duration = max(word_count * 0.3, 55.0)
        words = []
        for i, w in enumerate(text.split()):
            start_ms = (i / word_count) * total_duration * 1000
            end_ms = ((i + 1) / word_count) * total_duration * 1000
            words.append({
                "index": i + 1,
                "word": w,
                "start_ms": start_ms,
                "end_ms": end_ms
            })

        audio_duration_sec = total_duration
    else:
        audio_duration_sec = (words[-1]["end_ms"] - words[0]["start_ms"]) / 1000

    audio_duration_sec = max(audio_duration_sec, 1.0)

    metadata = {
        "audio_duration_sec": audio_duration_sec,
        "word_count": len(words),
        "voice": TTS_VOICE,
        "path": audio_path
    }

    meta_path = os.path.join(os.path.dirname(audio_path), "audio_meta.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f)

    logger.info(f"Voiceover complete: {audio_duration_sec:.1f}s, {len(words)} words")
    return words


# =============================================================================
# CAPTION GENERATION (ASS FORMAT WITH KARAOKE)
# =============================================================================

def build_ass_captions(words: List[Dict[str, Any]],
                       full_text: str,
                       font_path: str,
                       output_path: str,
                       video_width: int = VIDEO_WIDTH,
                       video_height: int = VIDEO_HEIGHT):
    logger = logging.getLogger(__name__)
    logger.info(f"Generating ASS subtitles: {len(words)} words")

    if not words:
        logger.warning("No words for caption generation")
        Path(output_path).write_text(generate_empty_ass(video_width, video_height))
        return output_path

    font_name = "Noto Sans Devanagari"
    try:
        if font_path:
            from PIL import ImageFont
            test_font = ImageFont.truetype(font_path, 36)
            font_name = test_font.getname()[0] if hasattr(test_font, 'getname') else "Noto Sans Devanagari"
    except Exception:
        pass

    sentences = segment_words_into_sentences(words, full_text)
    logger.info(f"Grouped into {len(sentences)} caption sentences")

    ass_lines = []
    ass_lines.append("[Script Info]")
    ass_lines.append("ScriptType: v4.00+")
    ass_lines.append(f"PlayResX: {video_width}")
    ass_lines.append(f"PlayResY: {video_height}")
    ass_lines.append("WrapStyle: 0")
    ass_lines.append("ScaledBorderAndShadow: yes")
    ass_lines.append("")

    ass_lines.append("[V4+ Styles]")
    ass_lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                     "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                     "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                     "Alignment, MarginL, MarginR, MarginV, Encoding")

    style_line = (
        f"Style: Highlight,{font_name},48,&H88FFFFFF,&H00FFD700,"
        f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,10,10,120,1"
    )
    ass_lines.append(style_line)

    style_line2 = (
        f"Style: Dimmed,{font_name},44,&H66FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,120,1"
    )
    ass_lines.append(style_line2)

    ass_lines.append("")

    ass_lines.append("[Events]")
    ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")
    ass_lines.append("")

    for sentence in sentences:
        sent_words = sentence["words"]
        sent_start = sent_words[0]["start_ms"] / 1000
        sent_end = sent_words[-1]["end_ms"] / 1000
        duration = sent_end - sent_start
        if duration < 0.5:
            sent_end = sent_start + 0.5

        sent_text_words = [w["word"] for w in sent_words]
        full_sentence = " ".join(sent_text_words)
        dimmed_alpha = "{\\alpha&H88}"
        ass_lines.append(
            f"Dialogue: 0,{seconds_to_ass(sent_start)},{seconds_to_ass(sent_end)},"
            f"Dimmed,,0,0,0,,{dimmed_alpha}{full_sentence}"
        )

        karaoke_parts = []
        for w in sent_words:
            w_duration_cs = max(int((w["end_ms"] - w["start_ms"]) / 10), 5)
            escaped_word = w["word"].replace("{", "\\{").replace("}", "\\}")
            karaoke_parts.append(f"{{\\k{w_duration_cs}}}{escaped_word} ")

        karaoke_text = "".join(karaoke_parts).strip()
        ass_lines.append(
            f"Dialogue: 1,{seconds_to_ass(sent_start)},{seconds_to_ass(sent_end)},"
            f"Highlight,,0,0,0,,{karaoke_text}"
        )

    ass_content = "\n".join(ass_lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    logger.info(f"ASS subtitles saved: {output_path} ({len(sentences)} sentences)")
    return output_path


def segment_words_into_sentences(words: List[Dict[str, Any]],
                                 full_text: str) -> List[Dict[str, Any]]:
    if not words:
        return []

    sentence_delimiters = {".", "!", "?", ":", ";"}
    sentences = []
    current_words = []
    word_texts = [w["word"] for w in words]

    for i, w in enumerate(words):
        current_words.append(w)
        word_text = w["word"]

        is_end = False
        if word_text and word_text[-1] in sentence_delimiters:
            is_end = True
        if i == len(words) - 1:
            is_end = True
        if i > 0 and word_text == " " and current_words:
            pass

        if is_end:
            sentences.append({"words": current_words})
            current_words = []

    if current_words:
        sentences.append({"words": current_words})

    if not sentences:
        sentences = [{"words": words}]

    min_words = 3
    merged = []
    for s in sentences:
        if merged and (len(merged[-1]["words"]) < min_words
                       or len(s["words"]) < min_words):
            merged[-1]["words"].extend(s["words"])
        else:
            merged.append(s)

    return merged


def generate_empty_ass(width: int = VIDEO_WIDTH,
                       height: int = VIDEO_HEIGHT) -> str:
    return (
        f"[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        f"\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, "
        f"PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        f"Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, "
        f"Angle, BorderStyle, Outline, Shadow, Alignment, "
        f"MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,36,&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1\n"
        f"\n[Events]\nFormat: Layer, Start, End, Style, Name, "
        f"MarginL, MarginR, MarginV, Effect, Text\n"
    )


# =============================================================================
# MEDIA FETCHING
# =============================================================================

@retry(max_attempts=2, delay=1.0, exceptions=(requests.RequestException,))
def fetch_pexels_video(keyword: str) -> Optional[str]:
    logger = logging.getLogger(__name__)
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        logger.warning("No Pexels API key")
        return None

    url = "https://api.pexels.com/videos/search"
    headers = {"Authorization": api_key}
    params = {
        "query": keyword,
        "per_page": 5,
        "orientation": "portrait",
        "size": "large"
    }

    logger.info(f"Searching Pexels: '{keyword}'")
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    videos = data.get("videos", [])
    if not videos:
        logger.warning(f"No Pexels videos for '{keyword}'")
        return None

    for video in videos:
        video_files = video.get("video_files", [])
        hd_candidates = [vf for vf in video_files
                         if vf.get("quality") in ("hd", "sd")
                         and vf.get("width", 0) >= 480
                         and vf.get("height", 0) >= 720
                         and vf.get("link")]
        if hd_candidates:
            hd_candidates.sort(key=lambda x: x.get("width", 0), reverse=True)
            best = hd_candidates[0]
            link = best.get("link")
            if link:
                dest = TEMP_DIR / f"pexels_{keyword[:20].replace(' ', '_')}_{video['id']}.mp4"
                logger.info(f"Downloading Pexels video: {link[:80]}...")
                try:
                    vresp = requests.get(link, stream=True, timeout=60)
                    vresp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in vresp.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    if dest.stat().st_size > 10000:
                        logger.info(f"Pexels video saved: {dest} ({dest.stat().st_size} bytes)")
                        return str(dest)
                    else:
                        logger.warning(f"Downloaded file too small: {dest}")
                        dest.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Download failed: {e}")
                    dest.unlink(missing_ok=True)
                    continue

    logger.warning(f"No suitable Pexels video found for '{keyword}'")
    return None


@retry(max_attempts=2, delay=1.0, exceptions=(requests.RequestException,))
def fetch_unsplash_image(keyword: str) -> Optional[str]:
    logger = logging.getLogger(__name__)
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        logger.warning("No Unsplash access key")
        return None

    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {access_key}"}
    params = {
        "query": keyword,
        "per_page": 5,
        "orientation": "portrait"
    }

    logger.info(f"Searching Unsplash: '{keyword}'")
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    if not results:
        logger.warning(f"No Unsplash images for '{keyword}'")
        return None

    for result in results[:3]:
        urls = result.get("urls", {})
        img_url = urls.get("regular") or urls.get("full")
        if not img_url:
            continue

        dest = TEMP_DIR / f"unsplash_{keyword[:20].replace(' ', '_')}_{result['id']}.jpg"
        logger.info(f"Downloading Unsplash image: {img_url[:80]}...")
        try:
            iresp = requests.get(img_url, stream=True, timeout=60)
            iresp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in iresp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if dest.stat().st_size > 5000:
                logger.info(f"Unsplash image saved: {dest} ({dest.stat().st_size} bytes)")
                return str(dest)
            else:
                dest.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Download failed: {e}")
            dest.unlink(missing_ok=True)
            continue

    return None


def fetch_media_for_keywords(keywords: List[str]) -> Dict[str, Any]:
    logger = logging.getLogger(__name__)

    all_keywords = keywords + ["background footage", "stock video"]
    fetched_keywords = set()

    for kw in all_keywords:
        if kw in fetched_keywords:
            continue
        fetched_keywords.add(kw)

        video_path = fetch_pexels_video(kw)
        if video_path:
            return {"type": "video", "path": video_path, "keyword": kw}

        logger.info(f"No Pexels video, trying Unsplash for '{kw}'")
        img_path = fetch_unsplash_image(kw)
        if img_path:
            return {"type": "image", "path": img_path, "keyword": kw}

    logger.warning("No media found for any keyword, using fallback")
    fallback = generate_fallback_background(VIDEO_WIDTH, VIDEO_HEIGHT)
    return {"type": "generated", "path": fallback, "keyword": "fallback"}


def generate_fallback_background(width: int, height: int) -> str:
    logger = logging.getLogger(__name__)
    path = TEMP_DIR / "fallback_bg.png"
    try:
        img = Image.new("RGB", (width, height), (20, 20, 40))
        draw = ImageDraw.Draw(img)
        for i in range(0, width, 50):
            draw.line([(i, 0), (i, height)], fill=(30, 30, 50), width=1)
        for i in range(0, height, 50):
            draw.line([(0, i), (width, i)], fill=(30, 30, 50), width=1)
        img.save(str(path))
        logger.info(f"Fallback background generated: {path}")
        return str(path)
    except Exception as e:
        logger.error(f"Fallback generation failed: {e}")
        return ""


# =============================================================================
# VIDEO COMPOSITION
# =============================================================================

def render_segment_video(media_info: Dict[str, Any],
                         duration: float,
                         output_path: str,
                         segment_index: int,
                         visual_style: str = "zoom_in") -> bool:
    logger = logging.getLogger(__name__)
    media_path = media_info.get("path", "")
    media_type = media_info.get("type", "generated")

    if not media_path or not os.path.exists(media_path):
        logger.error(f"Media path not found: {media_path}")
        return False

    duration = max(duration, 1.5)

    if media_type == "video":
        cmd = [
            "ffmpeg", "-y",
            "-i", media_path,
            "-vf",
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=1,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            "-an",
            output_path
        ]
        try:
            run_ffmpeg(cmd, timeout=180,
                       description=f"Segment {segment_index} video render")
            return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
        except Exception as e:
            logger.warning(f"Segment {segment_index} video render failed: {e}")

    frames = int(duration * FPS)
    zoom_params = {
        "zoom_in": "if(lte(on,1),1.2,zoom+0.008)",
        "zoom_out": "if(lte(on,1),1.8,zoom-0.008)",
        "pan": "1.0",
        "static": "1.0",
        "reveal": "if(lte(on,1),1.4,zoom+0.006)"
    }
    zoom_expr = zoom_params.get(visual_style, zoom_params["zoom_in"])

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", media_path,
        "-vf",
        f"zoompan=z='{zoom_expr}':d={frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-an",
        output_path
    ]
    try:
        run_ffmpeg(cmd, timeout=180,
                   description=f"Segment {segment_index} zoompan render")
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        logger.error(f"Segment {segment_index} all renders failed: {e}")
        return False


def create_concat_file(segment_paths: List[str]) -> str:
    concat_path = SEGMENTS_DIR / "concat.txt"
    with open(concat_path, "w") as f:
        for sp in segment_paths:
            abs_path = os.path.abspath(sp).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")
    return str(concat_path)


def compose_video(script_data: Dict[str, Any],
                  word_timestamps: List[Dict[str, Any]],
                  audio_path: str,
                  ass_path: str,
                  font_path: str,
                  output_path: str = str(OUTPUT_DIR / "video.mp4")) -> Optional[str]:
    logger = logging.getLogger(__name__)
    segments = script_data.get("segments", [])

    if not segments:
        logger.error("No segments to render")
        return None

    total_words_timing = word_timestamps
    word_index = 0
    segment_times = []

    for i, seg in enumerate(segments):
        seg_text = seg.get("text", "")
        seg_word_count = len(seg_text.split())
        seg_words = []
        for _ in range(seg_word_count):
            if word_index < len(total_words_timing):
                seg_words.append(total_words_timing[word_index])
                word_index += 1

        if seg_words:
            start_t = seg_words[0]["start_ms"] / 1000
            end_t = seg_words[-1]["end_ms"] / 1000
            duration = max(end_t - start_t, 2.0)
        else:
            duration = 8.0

        segment_times.append({
            "index": i,
            "text": seg_text,
            "keywords": seg.get("keywords", []),
            "visual_style": seg.get("visual_style", "zoom_in"),
            "duration": duration,
            "start_time": start_t if seg_words else 0,
            "end_time": end_t if seg_words else duration
        })

    total_duration = sum(s["duration"] for s in segment_times)
    logger.info(f"Total estimated duration: {total_duration:.1f}s ({len(segments)} segments)")

    if total_duration < TARGET_DURATION_MIN:
        scale_factor = TARGET_DURATION_MIN / total_duration
        for s in segment_times:
            s["duration"] *= scale_factor
        logger.info(f"Scaled durations up by {scale_factor:.2f}x for minimum target")
    elif total_duration > TARGET_DURATION_MAX:
        scale_factor = TARGET_DURATION_MAX / total_duration
        for s in segment_times:
            s["duration"] *= scale_factor
        logger.info(f"Scaled durations down by {scale_factor:.2f}x for maximum target")

    logger.info("Fetching media for each segment...")
    for i, seg_info in enumerate(segment_times):
        logger.info(f"  Segment {i+1}/{len(segment_times)}: fetching media...")
        keywords = seg_info["keywords"]
        if not keywords:
            words_in_seg = seg_info["text"].split()
            keywords = [w for w in words_in_seg if len(w) > 3][:3]
            if not keywords:
                keywords = ["stock footage", "background"]
        media = fetch_media_for_keywords(keywords)
        seg_info["media"] = media

    logger.info("Rendering segments...")
    segment_files = []
    for i, seg_info in enumerate(segment_times):
        out_path = str(SEGMENTS_DIR / f"seg_{i:04d}.mp4")
        success = render_segment_video(
            seg_info["media"],
            seg_info["duration"],
            out_path,
            i,
            seg_info["visual_style"]
        )
        if success:
            segment_files.append(out_path)
            logger.info(f"  Segment {i+1}: OK ({seg_info['duration']:.1f}s)")
        else:
            logger.error(f"  Segment {i+1}: FAILED")
            if segment_files:
                logger.info("  Using previous segment as fallback")
                segment_files.append(segment_files[-1])
            else:
                logger.error("No segments rendered, cannot continue")
                return None

    if len(segment_files) < 1:
        logger.error("No segment files produced")
        return None

    if len(segment_files) == 1:
        logger.info("Only one segment, using it directly")
        concat_video = str(SEGMENTS_DIR / "concat.mp4")
        shutil.copy2(segment_files[0], concat_video)
    else:
        logger.info(f"Concatenating {len(segment_files)} segments...")
        concat_file = create_concat_file(segment_files)
        concat_video = str(SEGMENTS_DIR / "concat.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            concat_video
        ]
        try:
            run_ffmpeg(cmd, timeout=120, description="Concatenation")
        except Exception as e:
            logger.error(f"Concat failed: {e}")
            if os.path.exists(concat_video):
                os.unlink(concat_video)
            if segment_files:
                logger.info("Using single segment as fallback")
                shutil.copy2(segment_files[0], concat_video)
            else:
                return None

    if not os.path.exists(concat_video):
        logger.error("Concatenated video not found")
        return None

    logger.info("Adding subtitles and audio...")
    audio_exists = os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000
    ass_exists = os.path.exists(ass_path) and os.path.getsize(ass_path) > 100

    ffmpeg_cmd = ["ffmpeg", "-y"]
    ffmpeg_cmd.extend(["-i", concat_video])
    if audio_exists:
        ffmpeg_cmd.extend(["-i", audio_path])

    filter_parts = []
    if ass_exists:
        filter_parts.append(f"ass='{ass_path}'")

    if filter_parts:
        ffmpeg_cmd.extend(["-vf", ",".join(filter_parts)])

    out_opts = [
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart"
    ]

    if audio_exists:
        out_opts.extend(["-c:a", "aac", "-b:a", "128k", "-map", "0:v:0", "-map", "1:a:0", "-shortest"])
    else:
        out_opts.extend(["-an"])

    ffmpeg_cmd.extend(out_opts)
    ffmpeg_cmd.append(output_path)

    try:
        run_ffmpeg(ffmpeg_cmd, timeout=300, description="Final video assembly")
        if os.path.exists(output_path) and os.path.getsize(output_path) > 50000:
            duration_cmd = [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "csv=p=0", output_path
            ]
            try:
                result = subprocess.run(duration_cmd, capture_output=True,
                                        text=True, timeout=30)
                video_duration = float(result.stdout.strip())
                logger.info(f"Final video: {output_path} "
                            f"({os.path.getsize(output_path)} bytes, "
                            f"{video_duration:.1f}s)")
            except Exception as e:
                logger.warning(f"Could not probe video: {e}")
            return output_path
        else:
            logger.error("Output video too small or missing")
            return None
    except Exception as e:
        logger.error(f"Final assembly failed: {e}")
        return None


# =============================================================================
# THUMBNAIL GENERATION
# =============================================================================

def generate_thumbnail(script_data: Dict[str, Any],
                       category: str,
                       font_path: Optional[str] = None,
                       output_path: str = str(OUTPUT_DIR / "thumbnail.jpg")):
    logger = logging.getLogger(__name__)
    logger.info("Generating thumbnail")

    title = script_data.get("title", "Amazing Facts!")
    emoji = CATEGORY_EMOJIS.get(category, "🔥")

    width, height = 1080, 1920

    try:
        img = Image.new("RGB", (width, height), (10, 10, 30))
        draw = ImageDraw.Draw(img)

        for i in range(0, width, 80):
            shade = 15 + (i % 160) // 8
            draw.line([(i, 0), (i, height)], fill=(shade, shade, shade + 10), width=2)

        try:
            from PIL import ImageFilter
            overlay = Image.new("RGB", (width, height // 2), (40, 20, 80))
            overlay = overlay.filter(ImageFilter.GaussianBlur(50))
            img.paste(overlay, (0, height // 3), overlay)
        except Exception:
            draw.rectangle([(0, height // 3), (width, height * 2 // 3)],
                           fill=(30, 15, 60, 128))

        try:
            font_title = None
            font_emoji = None
            font_sub = None

            if font_path and os.path.exists(font_path):
                font_title = ImageFont.truetype(font_path, 72)
                font_emoji = ImageFont.truetype(font_path, 120)
                font_sub = ImageFont.truetype(font_path, 48)

            if not font_title:
                default_font = get_default_font_path()
                if default_font:
                    font_title = ImageFont.truetype(default_font, 72)
                    font_emoji = ImageFont.truetype(default_font, 120)
                    font_sub = ImageFont.truetype(default_font, 48)

            if not font_title:
                font_title = ImageFont.load_default()
                font_emoji = font_title
                font_sub = font_title

            _, _, w_emoji, _ = draw.textbbox((0, 0), emoji, font=font_emoji)
            draw.text(((width - w_emoji) // 2, height // 4), emoji,
                      fill=(255, 215, 0), font=font_emoji)

            lines = []
            title_words = title.split()
            current_line = ""
            for word in title_words:
                test_line = current_line + " " + word if current_line else word
                _, _, tw, _ = draw.textbbox((0, 0), test_line, font=font_title)
                if tw < width - 80:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)

            y_offset = height // 2 - len(lines) * 45
            for line in lines:
                _, _, lw, _ = draw.textbbox((0, 0), line, font=font_title)
                draw.text(((width - lw) // 2, y_offset), line,
                          fill=(255, 255, 255), font=font_title)
                y_offset += 90

            sub_text = "Ajeebology Shorts"
            _, _, sw, _ = draw.textbbox((0, 0), sub_text, font=font_sub)
            draw.text(((width - sw) // 2, height - 200), sub_text,
                      fill=(200, 200, 200), font=font_sub)

            img.save(output_path, "JPEG", quality=85)
            logger.info(f"Thumbnail saved: {output_path}")
            return output_path

        except Exception as e:
            logger.warning(f"Font rendering failed: {e}")
            draw.text((width // 2 - 100, height // 2 - 50),
                      title[:30], fill=(255, 255, 255))
            img.save(output_path, "JPEG", quality=85)
            return output_path

    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        return None


# =============================================================================
# METADATA PREPARATION
# =============================================================================

def prepare_metadata(script_data: Dict[str, Any],
                     category: str,
                     video_duration: float = 0,
                     video_path: str = "",
                     word_count: int = 0) -> Dict[str, Any]:
    title = script_data.get("title", "Amazing Facts You Need To Know")
    description = script_data.get("description", "")
    tags = script_data.get("tags", [category, "facts", "amazing"])
    hashtags = script_data.get("hashtags", [f"#{category}", "#facts", "#shorts"])

    if len(title) > 100:
        title = title[:97] + "..."

    default_desc = (
        f"{CATEGORY_EMOJIS.get(category, '')} {title}\n\n"
        f"Amazing {category} facts that will blow your mind! "
        f"Follow for more amazing content daily.\n\n"
        f"---\n"
        f"#Ajeebology #Shorts #{category.capitalize()}Facts"
    )
    if not description:
        description = default_desc

    all_tags = list(set(tags + [category, "shorts", "youtubeshorts", "facts"]))
    all_hashtags = list(set(hashtags + [f"#{category}", "#shorts", "#facts"]))

    video_size = 0
    if video_path and os.path.exists(video_path):
        video_size = os.path.getsize(video_path)

    metadata = {
        "title": title,
        "description": description,
        "tags": all_tags[:15],
        "hashtags": all_hashtags[:8],
        "category": category,
        "video_duration_sec": round(video_duration, 1),
        "video_size_bytes": video_size,
        "word_count": word_count,
        "generated_at": datetime.utcnow().isoformat(),
        "language": "hinglish",
        "channel": "Ajeebology Shorts"
    }

    return metadata


# =============================================================================
# TELEGRAM DELIVERY
# =============================================================================

@retry(max_attempts=3, delay=2.0, exceptions=(requests.RequestException,))
def send_telegram_video(video_path: str, caption: str) -> bool:
    logger = logging.getLogger(__name__)
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendVideo"
    logger.info("Sending video to Telegram...")

    with open(video_path, "rb") as f:
        files = {"video": f}
        data = {
            "chat_id": chat_id,
            "caption": caption[:1024],
            "parse_mode": "HTML",
            "supports_streaming": True
        }
        resp = requests.post(url, files=files, data=data, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            logger.info("Video sent to Telegram successfully")
            return True
        else:
            logger.error(f"Telegram API error: {result}")
            return False


@retry(max_attempts=3, delay=2.0, exceptions=(requests.RequestException,))
def send_telegram_photo(photo_path: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendPhoto"
    with open(photo_path, "rb") as f:
        resp = requests.post(url, files={"photo": f},
                             data={"chat_id": chat_id}, timeout=60)
    return resp.json().get("ok", False)


def send_telegram_message(text: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }, timeout=30)
    return resp.json().get("ok", False)


def send_telegram(script_data: Dict[str, Any],
                  metadata: Dict[str, Any],
                  category: str,
                  pipeline_time: float):
    logger = logging.getLogger(__name__)

    if os.environ.get("DRY_RUN", "").lower() in ("true", "1", "yes"):
        logger.info("DRY RUN: Skipping Telegram delivery")
        return True

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    video_path = str(OUTPUT_DIR / "video.mp4")
    thumbnail_path = str(OUTPUT_DIR / "thumbnail.jpg")

    if not os.path.exists(video_path):
        logger.error(f"Video not found: {video_path}")
        return False

    title = metadata.get("title", "Ajeebology Short")
    hashtags_str = " ".join(metadata.get("hashtags", []))
    video_dur = metadata.get("video_duration_sec", 0)

    caption = (
        f"<b>{title}</b>\n\n"
        f"Category: {category.capitalize()}\n"
        f"Duration: {video_dur:.0f}s\n\n"
        f"{hashtags_str}"
    )

    video_sent = False
    try:
        video_sent = send_telegram_video(video_path, caption)
    except Exception as e:
        logger.warning(f"Video send failed: {e}")

    thumb_sent = False
    if os.path.exists(thumbnail_path) and video_sent:
        try:
            thumb_sent = send_telegram_photo(thumbnail_path, chat_id)
        except Exception as e:
            logger.warning(f"Thumbnail send failed: {e}")

    run_url = (
        f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
        f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/"
        f"{os.environ.get('GITHUB_RUN_ID', '')}"
    )

    info_lines = [
        f"<b>📊 Pipeline Report</b>",
        f"",
        f"Title: {title}",
        f"Category: {category.capitalize()}",
        f"Duration: {video_dur:.1f}s",
        f"Pipeline time: {pipeline_time:.1f}s",
        f"Video sent: {'✅' if video_sent else '❌'}",
        f"Thumbnail: {'✅' if thumb_sent else '❌'}",
        f"",
        f"Tags: {', '.join(metadata.get('tags', [])[:8])}",
        f"Hashtags: {hashtags_str}",
        f"",
        f"<a href='{run_url}'>GitHub Actions Run</a>"
    ]
    info_text = "\n".join(info_lines)

    try:
        send_telegram_message(info_text, chat_id)
    except Exception as e:
        logger.warning(f"Info message send failed: {e}")

    return video_sent


# =============================================================================
# MAIN
# =============================================================================

def main():
    start_time = time.time()
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("AJEEBOLOGY SHORTS PIPELINE")
    logger.info("=" * 60)

    audio_path = str(TEMP_DIR / "voiceover.mp3")
    ass_path = str(TEMP_DIR / "captions.ass")
    font_path = None
    script_data = None
    word_timestamps = []
    video_path = None

    try:
        if not validate_environment():
            sys.exit(1)

        setup_directories()

        category = select_category()
        topic = select_topic(category)
        logger.info(f"Selected: {category.upper()} → {topic}")

        research = research_topic(topic)

        script_data = generate_script(category, topic, research)
        logger.info(f"Title: {script_data.get('title', 'N/A')}")
        logger.info(f"Segments: {len(script_data.get('segments', []))}")

        full_text = " ".join([s["text"] for s in script_data.get("segments", [])])
        if not full_text.strip():
            full_text = f"Amazing {category} facts! " + topic

        logger.info("Generating voiceover...")
        word_timestamps = generate_voiceover(full_text, audio_path)
        logger.info(f"Voiceover: {len(word_timestamps)} words")

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
            logger.error("Voiceover file missing or too small")
            audio_valid = False
        else:
            audio_valid = True

        logger.info("Setting up font...")
        font_path = install_font()
        if font_path:
            logger.info(f"Using font: {font_path}")
        else:
            logger.warning("No suitable font found, captions may not render correctly")

        logger.info("Generating captions...")
        if word_timestamps:
            build_ass_captions(
                word_timestamps, full_text, font_path or "", ass_path
            )
        else:
            logger.error("No word timestamps for caption generation")

        logger.info("Composing video...")
        video_path = compose_video(
            script_data, word_timestamps,
            audio_path, ass_path, font_path or ""
        )

        if video_path and os.path.exists(video_path):
            video_size = os.path.getsize(video_path)
            dur_cmd = [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "csv=p=0", video_path
            ]
            try:
                dur_result = subprocess.run(dur_cmd, capture_output=True,
                                            text=True, timeout=30)
                video_duration = float(dur_result.stdout.strip())
            except Exception:
                video_duration = 0.0

            logger.info(f"✅ Video generated: {video_path} "
                        f"({video_size} bytes, {video_duration:.1f}s)")
        else:
            video_duration = 0.0
            logger.error("❌ Video generation failed")
            video_path = str(OUTPUT_DIR / "video.mp4") if os.path.exists(str(OUTPUT_DIR / "video.mp4")) else None

        logger.info("Generating thumbnail...")
        thumbnail_path = generate_thumbnail(
            script_data or {"title": f"{topic}"},
            category, font_path
        )

        logger.info("Preparing metadata...")
        metadata = prepare_metadata(
            script_data or {"title": topic, "description": "", "tags": [], "hashtags": []},
            category, video_duration,
            video_path or "", len(word_timestamps)
        )

        write_json_metadata(metadata)

        pipeline_time = time.time() - start_time
        metadata["pipeline_time_sec"] = round(pipeline_time, 1)

        if video_path and os.path.exists(video_path):
            send_telegram(script_data or {}, metadata, category, pipeline_time)

        github_summary(
            f"## Ajeebology Short - {metadata['title']}\n"
            f"- Category: {category} | Duration: {video_duration:.1f}s\n"
            f"- Pipeline: {pipeline_time:.1f}s | Words: {len(word_timestamps)}\n"
            f"- Video: {'✅' if video_path else '❌'} | "
            f"Audio: {'✅' if audio_valid else '❌'} | "
            f"Caption words: {len(word_timestamps)}"
        )

        logger.info("=" * 60)
        logger.info(f"PIPELINE COMPLETE ({pipeline_time:.1f}s)")
        logger.info("=" * 60)

    except SystemExit:
        raise
    except Exception as e:
        logger.critical(f"Pipeline crashed: {e}")
        logger.critical(traceback.format_exc())

        error_msg = (
            f"❌ Ajeebology Pipeline CRASHED\n"
            f"Error: {str(e)[:200]}\n"
            f"Check GitHub Actions for details."
        )
        try:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
            if chat_id and not os.environ.get("DRY_RUN"):
                send_telegram_message(error_msg, chat_id)
        except Exception:
            pass

        github_summary(f"## Pipeline FAILED\n- Error: {str(e)[:200]}")
        sys.exit(1)

    finally:
        cleanup_directories(keep_output=True)


if __name__ == "__main__":
    main()
