#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional YouTube Shorts Automation Agent
Fully automated pipeline: Research -> Script -> Voice -> Video -> Telegram
Language: Hinglish (Roman Hindi + English), Male voice
Output: Vertical 1080x1920, 24 FPS, <= 60s (YouTube Shorts limit)
KARAOKE CAPTIONS: Word-by-word animated highlighting via ASS subtitles
             (real per-word timing from edge-tts WordBoundary events)
"""

import os
import sys
import json
import re
import math
import random
import textwrap
import asyncio
import tempfile
import subprocess
import shutil
import time
import hashlib
import base64
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote_plus, urlparse
from io import BytesIO

import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
import numpy as np


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24
    TARGET_DURATION = 55
    MAX_DURATION = 60

    VOICE_MODEL = "hi-IN-MadhurNeural"
    VOICE_FALLBACK = "hi-IN-ArjunNeural"
    AUDIO_SAMPLE_RATE = 44100

    FONT_SIZE_TITLE = 72
    FONT_SIZE_BODY = 56
    FONT_SIZE_SMALL = 40

    COLOR_BG_DARK = (10, 5, 25)
    COLOR_BG_MID = (30, 15, 60)
    COLOR_ACCENT = (0, 255, 255)
    COLOR_ACCENT_2 = (255, 0, 128)
    COLOR_TEXT = (255, 255, 255)
    COLOR_TEXT_DIM = (200, 200, 220)
    COLOR_HIGHLIGHT = (255, 255, 0)

    BASE_DIR = Path("/tmp/ajeebology")
    FRAMES_DIR = BASE_DIR / "frames"
    AUDIO_DIR = BASE_DIR / "audio"
    ASSETS_DIR = BASE_DIR / "assets"
    OUTPUT_DIR = BASE_DIR / "output"

    BROLL_ENABLED = True
    UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
    POLLINATIONS_ENABLED = True

    KARAOKE_WORDS_PER_LINE = 3
    KARAOKE_FONT_SIZE = 64

    HISTORY_FILE = BASE_DIR / "history.json"
    MAX_HISTORY_DAYS = 30

    CATEGORY_OVERRIDE = os.environ.get("CATEGORY_OVERRIDE", "")


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class WordTiming:
    text: str
    start: float
    end: float


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
    word_timings: List[WordTiming] = field(default_factory=list)


# =============================================================================
# HISTORY (deduplication)
# =============================================================================

def load_history() -> List[Dict]:
    try:
        if Config.HISTORY_FILE.exists():
            with open(Config.HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def save_history_entry(entry: Dict):
    history = load_history()
    history.append(entry)
    cutoff = time.time() - (Config.MAX_HISTORY_DAYS * 86400)
    history = [h for h in history if h.get("ts", 0) >= cutoff]
    history = history[-200:]
    Config.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(Config.HISTORY_FILE, "w") as f:
        json.dump(history, f)


def was_title_used(title: str) -> bool:
    history = load_history()
    norm = re.sub(r"\W+", "", title.lower())
    return any(re.sub(r"\W+", "", h.get("title", "").lower()) == norm for h in history)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def setup_directories():
    """Create all necessary directories."""
    for d in [Config.FRAMES_DIR, Config.AUDIO_DIR, Config.ASSETS_DIR, Config.OUTPUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def run_command(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """Run shell command with timeout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"


def get_audio_duration(path: str) -> float:
    """Get audio duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    rc, out, _ = run_command(cmd)
    if rc == 0 and out.strip():
        try:
            return float(out.strip())
        except ValueError:
            pass
    return 0.0


def download_file(url: str, dest: str, timeout: int = 30) -> bool:
    """Download file with retry logic."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)
    return False


def safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)[:50]


def trim_audio_to_max(audio_path: str, max_seconds: float) -> str:
    """Trim audio to max duration. Returns path to trimmed file."""
    duration = get_audio_duration(audio_path)
    if duration <= max_seconds:
        return audio_path
    out_path = audio_path.replace(".mp3", "_trim.mp3")
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-t", str(max_seconds),
        "-acodec", "libmp3lame", "-q:a", "2",
        out_path
    ]
    run_command(cmd)
    return out_path if os.path.exists(out_path) else audio_path


# =============================================================================
# 1. KARAOKE CAPTION ENGINE (ASS-based, real per-word timing)
# =============================================================================

class CaptionEngine:
    """Generates karaoke-style ASS subtitles using REAL word timings from edge-tts."""

    ASS_HEADER = """[Script Info]
Title: Ajeebology Karaoke Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans Bold,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,900,1
Style: Highlight,DejaVu Sans Bold,68,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,105,105,0,0,1,5,2,2,60,60,860,1
Style: Glow,DejaVu Sans Bold,68,&H000080FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,110,110,0,0,1,5,4,2,60,60,820,1
Style: Outline,DejaVu Sans Bold,64,&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,6,2,60,60,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def __init__(self):
        self.ass_lines: List[str] = []

    def _time_to_ass(self, seconds: float) -> str:
        if seconds < 0:
            seconds = 0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    def _escape_ass_text(self, text: str) -> str:
        text = text.replace("\\", "\\\\")
        text = text.replace("{", "(")
        text = text.replace("}", ")")
        return text

    def _group_words(self, word_timings: List[WordTiming], max_words: int = 3):
        """Group consecutive words into display lines for Shorts readability."""
        if not word_timings:
            return []
        lines = []
        current = []
        current_start = word_timings[0].start
        for i, wt in enumerate(word_timings):
            current.append(wt)
            is_last = (i == len(word_timings) - 1)
            should_break = len(current) >= max_words or is_last
            if should_break and current:
                line_end = wt.end
                lines.append((current[:], current_start, line_end))
                current = []
                if not is_last:
                    current_start = word_timings[i + 1].start
        return lines

    def _generate_karaoke_line(
        self,
        words: List[WordTiming],
        line_start: float,
        line_end: float,
        emphasis_words: List[str],
    ) -> str:
        """Generate a single ASS Dialogue line with {\k} karaoke tags using REAL durations."""
        if not words or line_end <= line_start:
            return ""

        line_dur_cs = max(int((line_end - line_start) * 100), 1)
        parts = []
        acc_cs = 0
        for i, wt in enumerate(words):
            word_dur_cs = int((wt.end - wt.start) * 100)
            if i == len(words) - 1:
                word_dur_cs = max(line_dur_cs - acc_cs, 1)
            acc_cs += word_dur_cs

            clean = self._escape_ass_text(wt.text)
            parts.append(r"{\k%d}%s" % (word_dur_cs, clean))

        text = " ".join(parts)
        start_ass = self._time_to_ass(line_start)
        end_ass = self._time_to_ass(line_end)
        return f"Dialogue: 0,{start_ass},{end_ass},Glow,,0,0,0,,{text}"

    def build_ass_file(self, audio_segments: List[AudioSegment]) -> str:
        """Build the complete ASS subtitle file from audio segments with word timings."""
        lines = [self.ASS_HEADER.strip()]
        for seg in audio_segments:
            if not seg.word_timings:
                continue
            grouped = self._group_words(seg.word_timings, max_words=Config.KARAOKE_WORDS_PER_LINE)
            for word_list, line_start, line_end in grouped:
                ass_line = self._generate_karaoke_line(
                    word_list, line_start, line_end, seg.segment.emphasis_words
                )
                if ass_line:
                    lines.append(ass_line)

        ass_path = str(Config.AUDIO_DIR / "karaoke_captions.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return ass_path

# =============================================================================
# 2. RESEARCH MODULE (Tavily)
# =============================================================================

class ResearchAgent:
    """Fetches fresh facts using Tavily Search API."""

    CATEGORIES = ["psychology", "space", "weird_facts"]

    QUERIES = {
        "psychology": [
            "mind blowing psychology facts human behavior 2026",
            "psychology tricks brain facts hindi",
            "interesting psychological phenomena daily life",
        ],
        "space": [
            "amazing space facts universe secrets 2026",
            "space discoveries recent mind blowing",
            "astronomy facts that will blow your mind",
        ],
        "weird_facts": [
            "unbelievable facts about world strange but true",
            "weird facts that sound fake but are true",
            "amazing facts about earth animals humans",
        ],
    }

    FALLBACK_FACTS = {
        "psychology": {
            "title": "Psychology Facts That Will Blow Your Mind",
            "content": "Your brain processes images in 13 milliseconds. The placebo effect works even when patients know they're taking a placebo. Decisions are 90% subconscious. Smiling tricks your brain into feeling happier.",
            "category": "psychology",
        },
        "space": {
            "title": "Space Secrets You Never Knew",
            "content": "A day on Venus is longer than its year. Neutron stars spin 600 times per second. There are more trees on Earth than stars in the Milky Way. A space cloud is made of alcohol worth trillions.",
            "category": "space",
        },
        "weird_facts": {
            "title": "Weird Facts That Sound Fake",
            "content": "Honey never spoils. Wombat poop is cube-shaped. Bananas are berries, strawberries aren't. Octopuses have three hearts and blue blood.",
            "category": "weird_facts",
        },
    }

    def __init__(self):
        self.api_key = Config.TAVILY_API_KEY
        self.base_url = "https://api.tavily.com/search"

    def fetch_fact(self, category: Optional[str] = None) -> Dict:
        """Fetch a fresh fact topic. Avoids recently-used titles."""
        if not category:
            category = Config.CATEGORY_OVERRIDE or random.choice(self.CATEGORIES)

        recent_titles = [h.get("title", "") for h in load_history()[-15:]]
        queries = self.QUERIES.get(category, self.QUERIES["weird_facts"])

        for query in queries:
            fact = self._try_query(category, query)
            if fact and not any(recent.lower() in fact.get("title", "").lower() for recent in recent_titles):
                return fact

        # Last resort: pick a random fallback that wasn't used recently
        cat = category if category in self.FALLBACK_FACTS else random.choice(self.CATEGORIES)
        return dict(self.FALLBACK_FACTS[cat])

    def _try_query(self, category: str, query: str) -> Optional[Dict]:
        try:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced",
                "include_answer": True,
                "max_results": 5,
            }
            resp = requests.post(self.base_url, json=payload, timeout=30)
            data = resp.json()
            results = data.get("results", [])
            if results:
                best = max(results, key=lambda x: len(x.get("content", "")))
                return {
                    "category": category,
                    "title": best.get("title", ""),
                    "content": best.get("content", ""),
                    "url": best.get("url", ""),
                    "query": query,
                    "ai_answer": data.get("answer", ""),
                }
        except Exception as e:
            print(f"Research error: {e}")
        return None


# =============================================================================
# 3. SCRIPT GENERATION (Groq/LLaMA)
# =============================================================================

class ScriptAgent:
    """Generates structured Hinglish scripts using Groq LLaMA."""

    SYSTEM_PROMPT = """You are a professional YouTube Shorts scriptwriter for "Ajeebology Shorts".
Your scripts are in HINGLISH (Roman Hindi + English mix), engaging, fast-paced, and optimized for retention.

RULES:
1. Write in Hinglish (Roman script Hindi mixed with English words)
2. Target 50-55 seconds when spoken naturally (NEVER exceed 60s)
3. HOOK must grab attention in first 2 seconds (use curiosity gap or shocking claim)
4. Each FACT must be mind-blowing and concise (max 12 words)
5. Every 8-10 seconds introduce an OPEN LOOP ("but here's the crazy part...", "wait till you hear this")
6. OUTRO must have a strong CTA (subscribe, comment, share)
7. Mark EMPHASIS words with [WORD] brackets (max 2 per segment)
8. Keep sentences short and punchy (one idea per line in script)
9. Conversational tone like talking to a friend
10. NEVER repeat a topic from previous videos

OUTPUT FORMAT: Return ONLY valid JSON with this structure:
{
    "title": "Hinglish title under 60 chars",
    "category": "psychology|space|weird_facts",
    "seo_title": "English SEO title with primary keyword",
    "description": "English description 100-150 words with keywords",
    "tags": ["tag1", "tag2", ...15 tags],
    "hashtags": ["#tag1", "#tag2", ...10 hashtags],
    "segments": [
        {"type": "hook", "text": "Hinglish with [emphasis] words", "broll_prompt": "english search prompt"},
        {"type": "fact1", "text": "...", "broll_prompt": "..."},
        {"type": "fact2", "text": "...", "broll_prompt": "..."},
        {"type": "fact3", "text": "...", "broll_prompt": "..."},
        {"type": "outro", "text": "...", "broll_prompt": "..."}
    ]}"""

    HOOK_STYLES = [
        "Start with a direct question that creates curiosity gap",
        "Start with an impossible-sounding claim, then prove it",
        "Start with 'What if I told you...' pattern",
        "Start with a shocking statistic in round numbers",
        "Start with a controversial take that challenges common belief",
    ]

    def __init__(self):
        self.api_key = Config.GROQ_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.3-70b-versatile"

    def generate_script(self, research_data: Dict) -> VideoScript:
        """Generate complete video script from research."""
        hook_style = random.choice(self.HOOK_STYLES)

        user_prompt = f"""Create a viral YouTube Shorts script.

Category: {research_data['category']}
Topic: {research_data['title']}
Research: {research_data['content']}

HOOK STYLE TO USE: {hook_style}

Audience: Hinglish speakers aged 16-30. Keep segments SHORT for fast pacing.
CRITICAL: Total spoken duration MUST be 50-55 seconds. Count words: ~140-160 total words."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.85,
            "max_tokens": 1800,
            "response_format": {"type": "json_object"},
        }

        try:
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=60)
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            script_data = json.loads(content)

            # Retry if title was recently used
            for _ in range(2):
                if not was_title_used(script_data.get("title", "")):
                    break
                resp = requests.post(self.base_url, json=payload, headers=headers, timeout=60)
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                script_data = json.loads(content)

            return self._parse_script(script_data)
        except Exception as e:
            print(f"Script generation error: {e}")
            return self._fallback_script(research_data)

    def _parse_script(self, data: Dict) -> VideoScript:
        """Parse JSON into VideoScript object."""
        segments = []
        for seg_data in data.get("segments", []):
            text = seg_data.get("text", "")
            emphasis = re.findall(r"\[(.*?)\]", text)
            clean_text = re.sub(r"\[(.*?)\]", r"\1", text)

            segments.append(
                ScriptSegment(
                    text=clean_text,
                    segment_type=seg_data.get("type", "fact"),
                    emphasis_words=emphasis,
                    broll_prompt=seg_data.get("broll_prompt", ""),
                )
            )

        return VideoScript(
            title=data.get("title", "Amazing Facts"),
            category=data.get("category", "weird_facts"),
            seo_title=data.get("seo_title", "Mind Blowing Facts You Need To Know"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            hashtags=data.get("hashtags", []),
            segments=segments,
        )

    def _fallback_script(self, research: Dict) -> VideoScript:
        """Generate fallback script if API fails."""
        category = research.get("category", "weird_facts")
        templates = {
            "psychology": [
                ScriptSegment("Kya aap jaante hain aapka brain har [13 milliseconds] mein ek image process kar sakta hai?", "hook", ["13 milliseconds"], "human brain neural pathways"),
                ScriptSegment("Psychology ke ek experiment mein researchers ne dekha ki [false memories] create karna kitna aasan hai.", "fact1", ["false memories"], "psychology experiment memory"),
                ScriptSegment("Agar aap forcefully [smile] karte hain, toh aapka brain automatically [happy hormones] release kar deta hai.", "fact2", ["smile"], "person smiling happiness"),
                ScriptSegment("Aur ek study ke mutabik, aapke decisions ka [90%] subconscious mind control karta hai.", "fact3", ["90%"], "subconscious mind brain"),
                ScriptSegment("Agar ye facts pasand aaye toh [subscribe] karo aur comments mein batao aapko kaunsa fact sabse zyada shocking laga!", "outro", ["subscribe"], "youtube subscribe button"),
            ],
            "space": [
                ScriptSegment("Venus par ek din [243 Earth days] ka hota hai, lekin saal sirf [225 days] ka!", "hook", ["243 Earth days"], "venus planet space"),
                ScriptSegment("Neutron stars itni tezi se spin karti hain ki ek second mein [600 baar] ghoom jaati hain.", "fact1", ["600 baar"], "neutron star spinning"),
                ScriptSegment("Aur Earth par trees [Milky Way] ke stars se zyada hain!", "fact2", ["Milky Way"], "milky way galaxy stars"),
                ScriptSegment("Space mein ek [giant cloud] hai jo alcohol se bana hai, jiski value [1000 trillion dollars] hai.", "fact3", ["giant cloud"], "space nebula cloud"),
                ScriptSegment("Aur bhi amazing space facts ke liye [follow] karo Ajeebology Shorts ko!", "outro", ["follow"], "space astronaut earth"),
            ],
            "weird_facts": [
                ScriptSegment("Honey kabhi [spoil] nahi hota, archaeologists ne [3000 saal] purana honey khaya tha!", "hook", ["spoil", "3000 saal"], "honey jar ancient"),
                ScriptSegment("Wombat ka poop [cube-shaped] hota hai, nature ka sabse weird phenomenon!", "fact1", ["cube-shaped"], "wombat animal australia"),
                ScriptSegment("Banana technically ek [berry] hai, lekin strawberry nahi!", "fact2", ["berry"], "banana fruit close up"),
                ScriptSegment("Octopus ke paas [teen dil] hain aur unka blood [blue] hota hai!", "fact3", ["teen dil"], "octopus underwater ocean"),
                ScriptSegment("Aise hi [mind-blowing] facts ke liye channel ko subscribe karo!", "outro", ["mind-blowing"], "shocked surprised face"),
            ],
        }
        segs = templates.get(category, templates["weird_facts"])
        return VideoScript(
            title=research.get("title", "Amazing Facts"),
            category=category,
            seo_title=f"Mind Blowing {category.title()} Facts You Need To Know 2026",
            description=f"Amazing {category} facts in Hinglish. Subscribe for daily mind-blowing content!",
            tags=[category, "facts", "hinglish", "shorts", "viral"],
            hashtags=[f"#{category}", "#facts", "#shorts", "#viral", "#hinglish"],
            segments=segs,
    )


# =============================================================================
# 4. VOICE GENERATION (edge-tts async, with WordBoundary extraction)
# =============================================================================

class VoiceAgent:
    """Generates male Hindi voiceover using edge-tts. Captures per-word timings."""

    def __init__(self):
        self.voice_primary = Config.VOICE_MODEL
        self.voice_fallback = Config.VOICE_FALLBACK

    async def _tts_with_timings(self, text: str, voice: str, out_path: str) -> List[WordTiming]:
        """Async edge-tts call that captures WordBoundary events for karaoke timing."""
        word_timings: List[WordTiming] = []
        communicate = edge_tts.Communicate(text, voice, rate="+8%")
        with open(out_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # offset is in 100-ns units (ticks)
                    start = chunk["offset"] / 10_000_000.0
                    duration = chunk["duration"] / 10_000_000.0
                    word_text = chunk["text"].strip()
                    if word_text:
                        word_timings.append(WordTiming(
                            text=word_text,
                            start=start,
                            end=start + duration,
                        ))
        return word_timings

    async def _generate_segment(self, segment: ScriptSegment, idx: int, voice: str) -> AudioSegment:
        """Generate one segment's audio + word timings."""
        tts_text = self._clean_for_tts(segment.text)
        output_path = str(Config.AUDIO_DIR / f"segment_{idx:02d}.mp3")
        try:
            word_timings = await self._tts_with_timings(tts_text, voice, output_path)
        except Exception as e:
            print(f"edge-tts error: {e}")
            word_timings = []

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            duration = self._estimate_duration(segment.text)
            self._create_silent_audio(output_path, duration)
            word_timings = self._estimate_word_timings(segment.text, duration)

        duration = get_audio_duration(output_path)
        return AudioSegment(
            segment=segment,
            audio_path=output_path,
            duration=duration,
            start_time=0.0,
            end_time=duration,
            word_timings=word_timings,
        )

    def generate_voice(self, script: VideoScript) -> List[AudioSegment]:
        """Generate voice for all segments in parallel (async). Falls back to alt voice on failure."""
        async def _run_all():
            tasks = [
                self._generate_segment(seg, i, self.voice_primary)
                for i, seg in enumerate(script.segments)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # fallback for any that failed
            for i, res in enumerate(results):
                if isinstance(res, Exception) or res is None:
                    print(f"Segment {i} failed with primary voice, retrying with fallback")
                    try:
                        results[i] = await self._generate_segment(
                            script.segments[i], i, self.voice_fallback
                        )
                    except Exception as e:
                        print(f"Fallback also failed for segment {i}: {e}")
                        results[i] = self._synthetic_segment(script.segments[i], i)
            return results

        segments = asyncio.run(_run_all())

        # adjust start/end times and add small pause after hook
        current = 0.0
        for seg in segments:
            if seg is None:
                continue
            seg.start_time = current
            seg.end_time = current + seg.duration
            current = seg.end_time
            if seg.segment.segment_type == "hook":
                current += 0.25  # small dramatic pause

        script.total_duration_estimate = current

        # enforce Shorts duration cap
        if current > Config.MAX_DURATION:
            print(f"Voice total {current:.1f}s exceeds {Config.MAX_DURATION}s cap, trimming last segment")
            last = segments[-1]
            allowed = Config.MAX_DURATION - last.start_time
            if allowed > 1.5:
                last.audio_path = trim_audio_to_max(last.audio_path, allowed)
                last.duration = get_audio_duration(last.audio_path)
                last.end_time = last.start_time + last.duration
                # rescale word timings to new duration
                if last.word_timings and last.duration > 0:
                    orig = last.word_timings[-1].end
                    ratio = last.duration / orig if orig > 0 else 1.0
                    last.word_timings = [
                        WordTiming(wt.text, wt.start * ratio, wt.end * ratio)
                        for wt in last.word_timings
                    ]

        return [s for s in segments if s is not None]

    def _clean_for_tts(self, text: str) -> str:
        text = re.sub(r"[!]{2,}", "!", text)
        text = re.sub(r"[?]{2,}", "?", text)
        return text.strip()

    def _estimate_duration(self, text: str) -> float:
        return max(2.0, len(text) / 4.5)

    def _estimate_word_timings(self, text: str, duration: float) -> List[WordTiming]:
        words = text.split()
        if not words:
            return []
        per_word = duration / len(words)
        return [WordTiming(w, i * per_word, (i + 1) * per_word) for i, w in enumerate(words)]

    def _create_silent_audio(self, path: str, duration: float):
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration), "-acodec", "libmp3lame", "-q:a", "4", path,
        ]
        run_command(cmd)

    def _synthetic_segment(self, segment: ScriptSegment, idx: int) -> AudioSegment:
        duration = self._estimate_duration(segment.text)
        path = str(Config.AUDIO_DIR / f"segment_{idx:02d}.mp3")
        self._create_silent_audio(path, duration)
        return AudioSegment(
            segment=segment,
            audio_path=path,
            duration=duration,
            start_time=0.0,
            end_time=duration,
            word_timings=self._estimate_word_timings(segment.text, duration),
        )

    def mix_audio(self, audio_segments: List[AudioSegment], bg_music_path: Optional[str] = None) -> str:
        """Concatenate voice segments then duck-mix with background music."""
        concat_list = Config.AUDIO_DIR / "concat_list.txt"
        with open(concat_list, "w") as f:
            for seg in audio_segments:
                f.write(f"file '{seg.audio_path}'\n")

        voice_path = str(Config.AUDIO_DIR / "voice_only.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-acodec", "libmp3lame", "-q:a", "2",
            voice_path,
        ]
        run_command(cmd, timeout=120)

        if not bg_music_path or not os.path.exists(bg_music_path):
            return voice_path

        final_path = str(Config.AUDIO_DIR / "final_audio.mp3")
        # sidechaincompress ducks the bg music while voice plays (proper mixing)
        cmd = [
            "ffmpeg", "-y",
            "-i", voice_path,
            "-stream_loop", "-1", "-i", bg_music_path,
            "-filter_complex",
            "[1:a]volume=0.20,sidechaincompress=threshold=0.05:ratio=8:attack=5:release=400[bg];"
            "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]",
            "-map", "[aout]",
            "-acodec", "libmp3lame", "-q:a", "2",
            final_path,
        ]
        rc, _, err = run_command(cmd, timeout=120)
        if rc == 0 and os.path.exists(final_path):
            return final_path
        print(f"audio mix fallback: {err}")
        return voice_path


# =============================================================================
# 5. B-ROLL & ASSETS
# =============================================================================

class AssetAgent:
    """Downloads B-roll images, video clips, and music. Tries multiple sources with fallbacks."""

    MUSIC_URLS = [
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3",
        "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3",
    ]

    def __init__(self):
        self.assets: List[str] = []

    def fetch_broll(self, prompt: str, index: int) -> Optional[str]:
        """Fetch B-roll image. Try Unsplash → Pollinations → Pexels → procedural fallback."""
        safe_prompt = safe_filename(prompt)[:30]
        dest_path = str(Config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.jpg")

        if Config.UNSPLASH_ACCESS_KEY:
            if self._try_unsplash(prompt, dest_path):
                return dest_path

        if Config.POLLINATIONS_ENABLED:
            if self._try_pollinations(prompt, dest_path):
                return dest_path

        if Config.PEXELS_API_KEY:
            if self._try_pexels(prompt, dest_path):
                return dest_path

        # procedural fallback — gradient with text overlay
        return self._procedural_broll(dest_path, prompt, index)

    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        try:
            url = f"https://api.unsplash.com/search/photos?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": f"Client-ID {Config.UNSPLASH_ACCESS_KEY}"}
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            results = data.get("results", [])
            if results:
                return download_file(results[0]["urls"]["regular"], dest)
        except Exception as e:
            print(f"Unsplash error: {e}")
        return False

    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        try:
            enhanced = f"professional stock photo, {prompt}, high quality, detailed, cinematic lighting"
            encoded = quote_plus(enhanced)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&seed={random.randint(1, 10000)}&nologo=true"
            return download_file(url, dest, timeout=45)
        except Exception as e:
            print(f"Pollinations error: {e}")
        return False

    def _try_pexels(self, prompt: str, dest: str) -> bool:
        try:
            url = f"https://api.pexels.com/v1/search?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": Config.PEXELS_API_KEY}
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            photos = data.get("photos", [])
            if photos:
                return download_file(photos[0]["src"]["portrait"], dest)
        except Exception as e:
            print(f"Pexels error: {e}")
        return False

    def _procedural_broll(self, dest: str, prompt: str, index: int) -> str:
        """Last-resort B-roll: gradient with category-themed overlay."""
        try:
            img = Image.new("RGB", (Config.WIDTH, Config.HEIGHT), Config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(img)
            for y in range(Config.HEIGHT):
                ratio = y / Config.HEIGHT
                r = int(10 + ratio * 30 + math.sin(index * 0.7) * 20)
                g = int(5 + ratio * 20 + math.sin(index * 1.1) * 15)
                b = int(25 + ratio * 60 + math.sin(index * 0.5) * 25)
                draw.line([(0, y), (Config.WIDTH, y)], fill=(r, g, b))
            img.save(dest, "JPEG", quality=85)
            return dest
        except Exception as e:
            print(f"Procedural b-roll failed: {e}")
            return dest

    def fetch_background_music(self) -> Optional[str]:
        """Try multiple Pixabay music URLs."""
        dest = str(Config.ASSETS_DIR / "bg_music.mp3")
        for url in self.MUSIC_URLS:
            if download_file(url, dest):
                return dest
        return None

    def fetch_sfx(self, sfx_type: str) -> Optional[str]:
        """Download a sound effect (placeholder for future expansion)."""
        return None

# =============================================================================
# 6. VIDEO RENDERING ENGINE (PIL + ffmpeg + burned ASS karaoke)
# =============================================================================

class VideoEngine:
    """Professional video rendering. Uses PIL for visuals, FFmpeg for final encode."""

    def __init__(self):
        self.width = Config.WIDTH
        self.height = Config.HEIGHT
        self.fps = Config.FPS

        self.font_title = self._load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", Config.FONT_SIZE_TITLE)
        self.font_body = self._load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", Config.FONT_SIZE_BODY)
        self.font_small = self._load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", Config.FONT_SIZE_SMALL)

        self.particles = self._init_particles(60)

        # Cache pan direction per segment so Ken Burns doesn't jitter
        self._segment_pan: Dict[int, Tuple[int, int]] = {}

        self.caption_engine = CaptionEngine()

    def _load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            for alt in [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            ]:
                try:
                    return ImageFont.truetype(alt, size)
                except Exception:
                    continue
            return ImageFont.load_default()

    def _init_particles(self, count: int) -> List[Dict]:
        return [
            {
                "x": random.randint(0, self.width),
                "y": random.randint(0, self.height),
                "size": random.randint(1, 4),
                "speed": random.uniform(0.2, 1.5),
                "opacity": random.randint(50, 200),
                "phase": random.uniform(0, math.pi * 2),
            }
            for _ in range(count)
        ]

    def _draw_gradient_background(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        progress = frame_idx / max(total_frames, 1)
        hue_shift = progress * 0.3
        for y in range(self.height):
            ratio = y / self.height
            r = int(10 + ratio * 20 + math.sin(hue_shift + ratio * 3) * 10)
            g = int(5 + ratio * 15 + math.sin(hue_shift + ratio * 2) * 8)
            b = int(25 + ratio * 40 + math.sin(hue_shift + ratio * 4) * 15)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))

    def _draw_particles(self, draw: ImageDraw, frame_idx: int):
        for p in self.particles:
            p["y"] -= p["speed"]
            p["x"] += math.sin(frame_idx * 0.02 + p["phase"]) * 0.5
            if p["y"] < -10:
                p["y"] = self.height + 10
                p["x"] = random.randint(0, self.width)
            twinkle = abs(math.sin(frame_idx * 0.05 + p["phase"]))
            if int(p["opacity"] * twinkle) > 30:
                draw.ellipse(
                    [p["x"] - p["size"], p["y"] - p["size"], p["x"] + p["size"], p["y"] + p["size"]],
                    fill=(200, 220, 255),
                )

    def _draw_progress_bar(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        progress = frame_idx / max(total_frames, 1)
        bar_height = 8
        bar_y = self.height - bar_height - 20
        bar_width = self.width - 80
        bar_x = 40
        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            radius=4, fill=(40, 40, 60),
        )
        fill_width = int(bar_width * progress)
        if fill_width > 0:
            draw.rounded_rectangle(
                [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height],
                radius=4, fill=Config.COLOR_ACCENT,
            )

    def _draw_channel_badge(self, draw: ImageDraw, frame_idx: int):
        pulse = abs(math.sin(frame_idx * 0.08))
        dot_size = int(6 + pulse * 4)
        badge_w = 200
        badge_h = 44
        badge_x = self.width // 2 - badge_w // 2
        badge_y = 30
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=22, fill=(20, 20, 40), outline=Config.COLOR_ACCENT, width=1,
        )
        dot_color = (255, 50, 50) if pulse > 0.5 else (255, 100, 100)
        draw.ellipse(
            [badge_x + 15, badge_y + badge_h // 2 - dot_size // 2,
             badge_x + 15 + dot_size, badge_y + badge_h // 2 + dot_size // 2],
            fill=dot_color,
        )
        draw.text(
            (badge_x + 30, badge_y + badge_h // 2),
            "AJEEBOLOGY SHORTS", font=self.font_small,
            fill=Config.COLOR_TEXT, anchor="lm",
        )

    def _draw_subscribe_cta(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        progress = frame_idx / max(total_frames, 1)
        if progress < 0.85:
            return
        slide_progress = (progress - 0.85) / 0.15
        ease = slide_progress * slide_progress * (3 - 2 * slide_progress)
        cta_y = int(self.height + 100 - ease * 180)
        cta_w = 400
        cta_h = 80
        cta_x = self.width // 2 - cta_w // 2
        for glow in range(15, 0, -3):
            draw.rounded_rectangle(
                [cta_x - glow, cta_y - glow, cta_x + cta_w + glow, cta_y + cta_h + glow],
                radius=25, outline=Config.COLOR_ACCENT_2, width=2,
            )
        draw.rounded_rectangle(
            [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
            radius=20, fill=Config.COLOR_ACCENT_2, outline=(255, 255, 255), width=2,
        )
        bounce = abs(math.sin(frame_idx * 0.15)) * 3
        draw.text(
            (self.width // 2, cta_y + cta_h // 2 + bounce),
            "SUBSCRIBE KARO!", font=self.font_body, fill=(255, 255, 255), anchor="mm",
        )

    def _apply_ken_burns(self, img: Image.Image, frame_idx: int, segment_frames: int,
                         zoom_start: float, zoom_end: float, pan_x: float, pan_y: float) -> Image.Image:
        """Smooth Ken Burns with FIXED pan direction (no per-frame jitter)."""
        progress = frame_idx / max(segment_frames, 1)
        t = progress
        ease = t * t * (3 - 2 * t)
        zoom = zoom_start + (zoom_end - zoom_start) * ease

        new_w = int(self.width / zoom)
        new_h = int(self.height / zoom)

        offset_x = int(pan_x * ease * (self.width - new_w))
        offset_y = int(pan_y * ease * (self.height - new_h))

        left = max(0, (self.width - new_w) // 2 + offset_x)
        top = max(0, (self.height - new_h) // 2 + offset_y)
        right = min(img.width, left + new_w)
        bottom = min(img.height, top + new_h)

        if right - left < 10 or bottom - top < 10:
            return img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        return img.crop((left, top, right, bottom)).resize((self.width, self.height), Image.Resampling.LANCZOS)

    def _draw_broll_overlay(self, base_img: Image.Image, broll_path: str,
                            frame_idx: int, segment_frames: int, segment_idx: int,
                            overlay_mode: str = "full") -> Image.Image:
        """Overlay B-roll with effects. Pan direction picked ONCE per segment (cached)."""
        try:
            broll = Image.open(broll_path).convert("RGB")
        except Exception:
            return base_img

        # FIXED pan per segment (not random per frame)
        if segment_idx not in self._segment_pan:
            self._segment_pan[segment_idx] = (
                random.choice([-1, 1]) * 0.10,
                random.choice([-1, 1]) * 0.05,
            )
        pan_x, pan_y = self._segment_pan[segment_idx]

        broll = self._apply_ken_burns(broll, frame_idx, segment_frames,
                                       zoom_start=1.0, zoom_end=1.12,
                                       pan_x=pan_x, pan_y=pan_y)

        if overlay_mode == "full":
            overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            overlay.paste(broll.resize((self.width, self.height)))
            overlay = ImageEnhance.Brightness(overlay).enhance(0.4)
            base_img = Image.alpha_composite(base_img.convert("RGBA"), overlay)
            return base_img.convert("RGB")
        elif overlay_mode == "split":
            broll_resized = broll.resize((self.width, self.height // 2))
            base_img.paste(broll_resized, (0, 0))
            for y in range(self.height // 2 - 100, self.height // 2):
                for x in range(self.width):
                    base_img.putpixel((x, y), (10, 5, 25))
            return base_img
        return base_img

    def render_video(self, script: VideoScript, audio_segments: List[AudioSegment],
                     broll_paths: List[Optional[str]], final_audio_path: str) -> str:
        """Two-pass render: PIL generates frames, FFmpeg encodes + burns karaoke ASS."""
        total_duration = get_audio_duration(final_audio_path)
        total_duration = min(total_duration, Config.MAX_DURATION)
        total_frames = int(total_duration * self.fps)

        print(f"Rendering {total_frames} frames @ {self.fps} FPS, duration: {total_duration:.2f}s")

        # Build karaoke ASS file using REAL word timings
        ass_path = self.caption_engine.build_ass_file(audio_segments)
        print(f"Karaoke ASS: {ass_path}")

        # Pre-load b-roll images
        broll_images = {}
        for i, path in enumerate(broll_paths):
            if path and os.path.exists(path):
                try:
                    broll_images[i] = Image.open(path).convert("RGB")
                except Exception:
                    pass

        # Generate frames to disk
        for frame_idx in range(total_frames):
            current_time = frame_idx / self.fps

            active_seg_idx = -1
            active_seg = None
            for i, seg in enumerate(audio_segments):
                if seg.start_time <= current_time < seg.end_time:
                    active_seg_idx = i
                    active_seg = seg
                    break

            frame = Image.new("RGB", (self.width, self.height), Config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(frame)
            self._draw_gradient_background(draw, frame_idx, total_frames)
            self._draw_particles(draw, frame_idx)

            if active_seg_idx >= 0 and active_seg_idx in broll_images:
                seg_frames = int((active_seg.end_time - active_seg.start_time) * self.fps)
                rel_frame = max(0, frame_idx - int(active_seg.start_time * self.fps))
                stype = active_seg.segment.segment_type
                if stype == "hook":
                    mode = "full"
                elif stype in ("fact1", "fact2", "fact3"):
                    mode = "split" if random.random() > 0.5 else "full"
                else:
                    mode = "full"

                frame = self._draw_broll_overlay(
                    frame, broll_paths[active_seg_idx], rel_frame,
                    seg_frames, active_seg_idx, mode,
                )
                draw = ImageDraw.Draw(frame)

            # zoom punch on emphasis beats
            if active_seg and active_seg.segment.emphasis_words:
                seg_dur = active_seg.end_time - active_seg.start_time
                beat_times = [
                    active_seg.start_time + 0.5,
                    active_seg.start_time + seg_dur * 0.5,
                ]
                for bt in beat_times:
                    if abs(current_time - bt) < 0.15:
                        beat = 1 - abs(current_time - bt) / 0.15
                        zoom = 1 + 0.08 * beat
                        new_size = (int(self.width * zoom), int(self.height * zoom))
                        frame = frame.resize(new_size, Image.Resampling.LANCZOS)
                        left = (new_size[0] - self.width) // 2
                        top = (new_size[1] - self.height) // 2
                        frame = frame.crop((left, top, left + self.width, top + self.height))
                        draw = ImageDraw.Draw(frame)

            self._draw_channel_badge(draw, frame_idx)
            self._draw_progress_bar(draw, frame_idx, total_frames)
            self._draw_subscribe_cta(draw, frame_idx, total_frames)

            frame_path = Config.FRAMES_DIR / f"frame_{frame_idx:06d}.png"
            frame.save(frame_path, "PNG")
            if frame_idx % 100 == 0:
                print(f"Frame {frame_idx}/{total_frames}")

        output_path = str(Config.OUTPUT_DIR / "output_video.mp4")
        temp_video = str(Config.OUTPUT_DIR / "temp_video_no_subs.mp4")

        # Pass 1: encode frames + audio (no subs)
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(self.fps),
            "-i", str(Config.FRAMES_DIR / "frame_%06d.png"),
            "-i", final_audio_path,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-t", str(total_duration),
            "-movflags", "+faststart",
            temp_video,
        ]
        rc, _, err = run_command(cmd, timeout=900)
        if rc != 0:
            print(f"FFmpeg pass1 error, retrying ultrafast: {err}")
            cmd[cmd.index("-preset") + 1] = "ultrafast"
            cmd[cmd.index("-crf") + 1] = "28"
            cmd[cmd.index("-b:a") + 1] = "128k"
            run_command(cmd, timeout=900)

        # Pass 2: burn karaoke ASS subtitles
        print("Burning karaoke captions...")
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_video,
            "-vf", f"subtitles={ass_path}:fontsdir=/usr/share/fonts/truetype",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "23", "-preset", "fast",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        rc, _, err = run_command(cmd, timeout=300)
        if rc != 0:
            print(f"Subtitle burn failed, retrying without fontsdir: {err}")
            cmd[cmd.index("-vf") + 1] = f"subtitles={ass_path}"
            rc2, _, err2 = run_command(cmd, timeout=300)
            if rc2 != 0:
                print(f"Fallback failed: {err2}, copying video without subs")
                shutil.copy(temp_video, output_path)

        # cleanup
        if os.path.exists(temp_video):
            os.remove(temp_video)
        for f in Config.FRAMES_DIR.glob("*.png"):
            f.unlink()

        print(f"Final video: {output_path}")
        return output_path

# =============================================================================
# 7. TELEGRAM DELIVERY
# =============================================================================

class TelegramAgent:
    """Sends video and metadata via Telegram Bot. Reports success AND failure."""

    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_video(self, video_path: str, script: VideoScript, artifact_url: str = "") -> bool:
        if not self.token or not self.chat_id:
            print("Telegram credentials not configured")
            return False

        caption = self._build_caption(script, artifact_url)
        file_size = os.path.getsize(video_path)
        max_size = 48 * 1024 * 1024

        try:
            if file_size <= max_size:
                with open(video_path, "rb") as f:
                    files = {"video": f}
                    data = {
                        "chat_id": self.chat_id,
                        "caption": caption[:1024],
                        "parse_mode": "HTML",
                    }
                    resp = requests.post(
                        f"{self.base_url}/sendVideo", data=data, files=files, timeout=180
                    )
                    result = resp.json()
                    if result.get("ok"):
                        return True
                    print(f"Telegram error: {result}")
            else:
                self._send_text(caption)
                thumb = self._generate_thumbnail(script)
                if thumb:
                    with open(thumb, "rb") as f:
                        files = {"photo": f}
                        data = {
                            "chat_id": self.chat_id,
                            "caption": f"<b>{script.seo_title}</b>\n\nVideo too large. Download from artifacts.",
                            "parse_mode": "HTML",
                        }
                        requests.post(f"{self.base_url}/sendPhoto", data=data, files=files, timeout=60)
        except Exception as e:
            print(f"Telegram send error: {e}")
        return False

    def send_success(self, script: VideoScript, artifact_url: str):
        """Quick success notification."""
        msg = f"<b>✅ Ajeebology Video Ready</b>\n\n<b>{script.seo_title}</b>\nCategory: {script.category}\n\n<a href='{artifact_url}'>Download Artifact</a>"
        self._send_text(msg)

    def _build_caption(self, script: VideoScript, artifact_url: str) -> str:
        tags_str = ", ".join(script.tags[:15])
        hashtags_str = " ".join(script.hashtags[:10])
        return (
            f"<b>🎬 {script.seo_title}</b>\n\n"
            f"<b>📋 Title:</b> {script.title}\n"
            f"<b>📁 Category:</b> {script.category}\n\n"
            f"<b>📝 Description:</b>\n{script.description}\n\n"
            f"<b>🏷 Tags:</b>\n{tags_str}\n\n"
            f"<b>#️⃣ Hashtags:</b>\n{hashtags_str}\n\n"
            f"<b>📥 Download:</b> {artifact_url if artifact_url else 'GitHub Actions artifacts'}\n\n"
            f"#AjeebologyShorts #YouTubeShorts #DailyFacts"
        )

    def _send_text(self, text: str):
        try:
            data = {
                "chat_id": self.chat_id,
                "text": text[:4096],
                "parse_mode": "HTML",
            }
            requests.post(f"{self.base_url}/sendMessage", data=data, timeout=30)
        except Exception as e:
            print(f"Text send error: {e}")

    def _generate_thumbnail(self, script: VideoScript) -> Optional[str]:
        try:
            img = Image.new("RGB", (1280, 720), Config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(img)
            for y in range(720):
                ratio = y / 720
                draw.line(
                    [(0, y), (1280, y)],
                    fill=(int(10 + ratio * 30), int(5 + ratio * 20), int(25 + ratio * 50)),
                )
            font = self._load_font_thumbnail(80)
            words = script.title.split()
            lines, current = [], []
            for word in words:
                test = " ".join(current + [word])
                bbox = font.getbbox(test)
                if bbox and bbox[2] > 1200 and current:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            if current:
                lines.append(" ".join(current))

            y = 360 - len(lines) * 50
            for line in lines:
                for offset in range(8, 0, -2):
                    draw.text((640 + offset, y), line, font=font, fill=(0, 200, 200), anchor="mm")
                    draw.text((640 - offset, y), line, font=font, fill=(0, 200, 200), anchor="mm")
                draw.text((640, y), line, font=font, fill=(255, 255, 255), anchor="mm")
                y += 100

            font_small = self._load_font_thumbnail(40)
            draw.text((640, 650), "@AjeebologyShorts", font=font_small,
                      fill=Config.COLOR_ACCENT, anchor="mm")
            path = str(Config.OUTPUT_DIR / "thumbnail.jpg")
            img.save(path, "JPEG", quality=90)
            return path
        except Exception as e:
            print(f"Thumbnail error: {e}")
            return None

    def _load_font_thumbnail(self, size: int):
        for p in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()


# =============================================================================
# 8. MAIN PIPELINE
# =============================================================================

class AjeebologyPipeline:
    """Orchestrates the full automation: Research → Script → Voice → Render → Deliver."""

    def __init__(self):
        self.researcher = ResearchAgent()
        self.script_writer = ScriptAgent()
        self.voice_gen = VoiceAgent()
        self.asset_fetcher = AssetAgent()
        self.video_engine = VideoEngine()
        self.telegram = TelegramAgent()

    def run(self) -> bool:
        print("=" * 60)
        print("AJEEBOLOGY SHORTS - AUTOMATION PIPELINE")
        print("=" * 60)

        try:
            setup_directories()

            print("\n[1/7] Researching fresh facts...")
            research_data = self.researcher.fetch_fact()
            print(f"  Category: {research_data['category']}")
            print(f"  Topic:    {research_data['title']}")

            print("\n[2/7] Generating Hinglish script...")
            script = self.script_writer.generate_script(research_data)
            print(f"  Title:    {script.title}")
            print(f"  Segments: {len(script.segments)}")

            print("\n[3/7] Generating voiceover (async parallel)...")
            audio_segments = self.voice_gen.generate_voice(script)
            print(f"  Voice duration: {script.total_duration_estimate:.2f}s")

            print("\n[4/7] Fetching B-roll and music...")
            broll_paths = []
            for i, seg in enumerate(script.segments):
                if seg.broll_prompt:
                    path = self.asset_fetcher.fetch_broll(seg.broll_prompt, i)
                    broll_paths.append(path)
                    print(f"  {'✓' if path else '✗'} B-roll {i}: {seg.broll_prompt[:40]}")
                else:
                    broll_paths.append(None)

            bg_music = self.asset_fetcher.fetch_background_music()
            print(f"  {'✓' if bg_music else '✗'} Background music")

            print("\n[5/7] Mixing audio (voice + ducked music)...")
            final_audio = self.voice_gen.mix_audio(audio_segments, bg_music)
            print(f"  Final audio: {final_audio}")

            print("\n[6/7] Rendering video with karaoke captions...")
            video_path = self.video_engine.render_video(script, audio_segments, broll_paths, final_audio)
            file_size = os.path.getsize(video_path) / (1024 * 1024)
            print(f"  Video: {video_path} ({file_size:.2f} MB)")

            print("\n[7/7] Sending to Telegram...")
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            artifact_url = f"https://github.com/{repo}/actions/runs/{run_id}" if run_id and repo else ""

            sent = self.telegram.send_video(video_path, script, artifact_url)
            if not sent:
                self.telegram.send_success(script, artifact_url)

            # save to history for dedup
            save_history_entry({
                "ts": time.time(),
                "title": script.title,
                "category": script.category,
                "seo_title": script.seo_title,
            })

            print("\n" + "=" * 60)
            print("✅ PIPELINE COMPLETED SUCCESSFULLY")
            print("=" * 60)
            return True

        except Exception as e:
            print(f"\n❌ PIPELINE FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    pipeline = AjeebologyPipeline()
    success = pipeline.run()
    sys.exit(0 if success else 1)
