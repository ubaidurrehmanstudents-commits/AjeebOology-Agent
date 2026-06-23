#!/usr/bin/env python3
"""
=============================================================================
 AJEEBOLOGY SHORTS — Premium YouTube Shorts Automation Pipeline
=============================================================================
 Generates professional Hinglish fact videos with:
   • Real stock video backgrounds (Pexels API — free tier)
   • Per-phrase AI voiceover (edge-tts) with word-level karaoke subtitle sync
   • ASS karaoke subtitles (MrBeast-style word-by-word highlighting)
   • Ken Burns subtle zoom on stock footage
   • Branded intro card (3s, purple/cyan channel colors)
   • Background music with sidechain compression ducking
   • Animated progress bar
   • Subscribe call-to-action overlay
   • Crossfade transitions between multiple video clips
   • Full SEO metadata + Telegram delivery

 All APIs are FREE-tier. Runs on GitHub Actions ubuntu-latest.
=============================================================================
"""

import os
import sys
import json
import time
import math
import random
import asyncio
import shutil
import textwrap
import subprocess
import tempfile
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import requests

# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1: CONFIGURATION & CONSTANTS                                 ║
# ╚═════════════════════════════════════════════════════════════════════════╝

# ── API Keys (from GitHub Actions secrets / environment) ──
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY     = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY     = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# ── Video Dimensions ──
VIDEO_WIDTH        = 1080
VIDEO_HEIGHT       = 1920
VIDEO_FPS          = 30

# ── Timing Targets ──
TARGET_DURATION    = 60       # target video length in seconds
MIN_DURATION       = 45       # minimum acceptable duration
MAX_DURATION       = 75       # maximum acceptable duration
PHRASE_MIN_WORDS   = 3        # minimum words per phrase
PHRASE_MAX_WORDS   = 12       # maximum words per phrase
TARGET_PHRASE_COUNT = 12      # target number of phrases

# ── Brand Colors (Ajeebology: Purple + Cyan) ──
BRAND_PURPLE_HEX   = "#1a0a2e"
BRAND_PURPLE_RGB   = "26,10,46"
BRAND_CYAN_HEX     = "#00FFFF"
BRAND_CYAN_RGB     = "0,255,255"
BRAND_GOLD_HEX     = "#FFD700"
BRAND_WHITE_HEX    = "#FFFFFF"
BRAND_DARK_HEX     = "#0D0618"

# ── Paths ──
OUTPUT_DIR         = Path("/tmp/ajeebology_output")
FINAL_VIDEO        = OUTPUT_DIR / "output_video.mp4"
VOICE_AUDIO        = OUTPUT_DIR / "voice_combined.mp3"
MUSIC_DUCKED       = OUTPUT_DIR / "music_ducked.mp3"
FINAL_AUDIO        = OUTPUT_DIR / "final_audio.mp3"
STOCK_VIDEO_DIR    = OUTPUT_DIR / "stock_clips"
INTRO_VIDEO        = OUTPUT_DIR / "intro.mp4"
SUBTITLES_FILE     = OUTPUT_DIR / "subtitles.ass"
SUBSCRIBE_OVERLAY  = OUTPUT_DIR / "subscribe_overlay.png"
PROGRESS_BAR_FILE  = OUTPUT_DIR / "progress_bar.png"
THUMBNAIL_FILE     = OUTPUT_DIR / "thumbnail.jpg"
METADATA_FILE      = OUTPUT_DIR / "metadata.json"

# ── Font ──
FONT_BOLD          = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR       = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# ── Logging ──
LOG_FILE           = OUTPUT_DIR / "pipeline.log"


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2: UTILITY FUNCTIONS                                         ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def log(message: str, level: str = "INFO"):
    """Log a timestamped message to stdout and log file."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {message}"
    print(formatted, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def log_step(step_num: int, total_steps: int, name: str):
    """Log the beginning of a pipeline step."""
    log("")
    log("━" * 55)
    log(f"  STEP {step_num}/{total_steps}: {name}")
    log("━" * 55)


def run_ffmpeg(args: list, timeout: int = 300,
               capture: bool = True) -> Tuple[bool, str, str]:
    """Run an ffmpeg command safely. Returns (success, stdout, stderr)."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return True, result.stdout or "", result.stderr or ""
    except subprocess.CalledProcessError as e:
        err = e.stderr or ""
        log(f"FFmpeg failed (code {e.returncode}): {err[:300]}", "ERROR")
        return False, e.stdout or "", err
    except subprocess.TimeoutExpired:
        log(f"FFmpeg timed out after {timeout}s", "ERROR")
        return False, "", "Timeout"
    except FileNotFoundError:
        log("FFmpeg not found! Is it installed?", "CRITICAL")
        return False, "", "FFmpeg not found"


def get_media_duration(file_path: Path) -> float:
    """Get media duration in seconds using ffprobe."""
    if not file_path.exists() or file_path.stat().st_size < 100:
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1",
             str(file_path)],
            capture_output=True, text=True, timeout=15
        )
        return max(0.0, float(result.stdout.strip()))
    except (ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return 0.0


def get_video_resolution(file_path: Path) -> Tuple[int, int]:
    """Get video resolution using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0",
             str(file_path)],
            capture_output=True, text=True, timeout=15
        )
        parts = result.stdout.strip().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 0, 0


def retry(func, max_retries: int = 3, delay: float = 2.0,
          backoff: float = 2.0, exceptions=(Exception,)):
    """Retry a function with exponential backoff."""
    last_exception = None
    current_delay = delay
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                log(f"Retry {attempt}/{max_retries} after error: {e}. "
                    f"Waiting {current_delay:.0f}s...", "WARN")
                time.sleep(current_delay)
                current_delay *= backoff
            else:
                log(f"All {max_retries} attempts failed: {e}", "ERROR")
    raise last_exception


def safe_json_parse(text: str) -> Optional[dict]:
    """Safely parse JSON from LLM output, handling markdown fences."""
    if not text:
        return None
    # Remove markdown code fences
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                return None
        return None


def ensure_dir(path: Path):
    """Ensure a directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def format_time(seconds: float) -> str:
    """Format seconds to H:MM:SS.cs (ASS time format)."""
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def format_time_srt(seconds: float) -> str:
    """Format seconds to HH:MM:SS,mmm (SRT time format)."""
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def get_file_size_mb(file_path: Path) -> float:
    """Get file size in MB."""
    if file_path.exists():
        return file_path.stat().st_size / (1024 * 1024)
    return 0.0


def clean_temp_files(keep: list = None):
    """Clean temporary files, keeping specified ones."""
    if keep is None:
        keep = [FINAL_VIDEO, METADATA_FILE]
    for f in OUTPUT_DIR.glob("*"):
        if f not in keep:
            try:
                if f.is_file():
                    f.unlink()
            except Exception:
                pass


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3: STEP 1 — RESEARCH (Tavily API)                            ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def research_fact() -> str:
    """Research an interesting fact using Tavily search API with fallbacks."""
    categories = [
        ("psychology", [
            "psychology fact about human behavior",
            "mind blowing psychology fact",
            "brain fact that changes everything",
            "psychological truth about human mind"
        ]),
        ("space", [
            "amazing space fact NASA discovered",
            "mind blowing space secret",
            "unbelievable universe fact",
            "space discovery that shocked scientists"
        ]),
        ("weird", [
            "weird fact about human body",
            "strange but true fact",
            "interesting science fact",
            "fact that sounds fake but is true"
        ]),
        ("brain", [
            "brain fact psychology research",
            "how human brain works fact",
            "neuroscience fact about memory"
        ])
    ]

    # Pick a random category and query
    category_name, queries = random.choice(categories)
    query = random.choice(queries)
    log(f"Research category: {category_name}")
    log(f"Search query: '{query}'")

    # Try Tavily with retry
    def _search():
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
                "include_raw_content": False,
            },
            timeout=30
        )
        if response.status_code != 200:
            raise RuntimeError(f"Tavily error {response.status_code}: "
                               f"{response.text[:200]}")
        return response.json()

    try:
        data = retry(_search, max_retries=2, delay=3.0)
    except Exception as e:
        log(f"Tavily search failed after retries: {e}", "WARN")
        # Fallback: use a curated fact database
        return get_fallback_fact(category_name)

    # Extract the most useful content
    answer = data.get("answer", "")
    if answer and len(answer) > 50:
        log(f"Research result: {answer[:120]}...")
        return answer

    results = data.get("results", [])
    if results:
        best = max(results, key=lambda r: len(r.get("content", "")))
        content = best.get("content", "")
        if len(content) > 50:
            log(f"Using result: {content[:120]}...")
            return content

    # Last resort: fallback fact
    log("No good result from Tavily, using fallback fact", "WARN")
    return get_fallback_fact(category_name)


def get_fallback_fact(category: str) -> str:
    """Return a curated fact when API search fails."""
    fallback_facts = {
        "psychology": [
            "The human brain processes 70,000 thoughts per day on average. "
            "Most of these thoughts are automatic and happen below our conscious awareness. "
            "This is why your brain can drive a car on autopilot while your mind wanders.",
            "People are more likely to remember information when it's presented in a story "
            "rather than as plain facts. This is called the 'narrative bias' and it's why "
            "storytelling is so powerful in marketing and education.",
            "The 'spotlight effect' makes us believe people notice us more than they actually do. "
            "In reality, most people are too focused on themselves to pay close attention to you."
        ],
        "space": [
            "A day on Venus is longer than a year on Venus. "
            "Venus takes 243 Earth days to rotate once on its axis, "
            "but only 225 Earth days to orbit the Sun.",
            "There's a giant cloud of alcohol in space called Sagittarius B2. "
            "It contains enough ethanol to fill 400 trillion pints of beer.",
            "Neutron stars are so dense that a single teaspoon of their material "
            "would weigh about 10 million tons on Earth."
        ],
        "weird": [
            "Your stomach lining replaces itself every 3-4 days. "
            "If it didn't, your stomach acid would digest your own stomach!",
            "Humans shed about 600,000 particles of skin every hour. "
            "That's about 1.5 pounds of dead skin per year.",
            "Your bones are constantly being broken down and rebuilt. "
            "Every 7-10 years, you get a completely new skeleton."
        ],
        "brain": [
            "Your brain uses 20% of your body's energy despite being "
            "only 2% of your body weight. It's the most energy-hungry organ.",
            "When you learn something new, your brain physically changes shape. "
            "New connections form between neurons, literally rewiring itself.",
            "The brain can't actually multitask. It just switches between tasks "
            "extremely quickly, losing efficiency with each switch."
        ]
    }
    facts = fallback_facts.get(category, fallback_facts["psychology"])
    return random.choice(facts)


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4: STEP 2 — SCRIPT GENERATION (Groq LLaMA)                  ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def generate_script(fact_context: str) -> dict:
    """Generate a structured Hinglish script using Groq LLaMA 3."""
    system_prompt = """You are a top YouTube Shorts script writer for "Ajeebology Shorts" — 
a Hinglish (Hindi+English, Roman script) channel covering psychology, space, and weird world facts.

Your scripts go VIRAL because they are:
1. HOOK-strong: First 3 seconds grab attention immediately
2. VALUE-packed: Every sentence teaches something surprising
3. PACED perfectly: Short, punchy sentences that are easy to follow
4. RETENTION-optimized: Each phrase makes the viewer want the next one

ABSOLUTE RULES:
- Write ALL text in Roman Hinglish (NOT Devanagari script)
  Example: "Kya aap jaante hain ki insaan ka dimaag..."
- Each phrase must be 3-12 words (short, punchy, complete sentence)
- Generate EXACTLY 12-14 phrases
- First phrase = POWERFUL HOOK (question or shocking statement)
- Last 2 phrases = Value summary + Subscribe CTA ("Ajeebology Shorts ko subscribe karein!")
- Include a relevant Pexels video search keyword
- Output ONLY valid JSON, no markdown, no explanation

JSON STRUCTURE (exact):
{
  "title": "Catchy title with emoji (max 60 chars)",
  "category": "psychology|space|weird|brain|science",
  "seo_title": "SEO title for YouTube | Ajeebology Shorts",
  "description": "2-3 line Hinglish description of the video content",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "hashtags": "#hashtag1 #hashtag2 #hashtag3",
  "pexels_keyword": "English keyword for Pexels stock video search",
  "phrases": [
    "First hook phrase? 3-12 words",
    "Second phrase continuing the thought...",
    "... (12-14 total)",
    "Second-to-last: value summary",
    "Last phrase: subscribe CTA in Hinglish"
  ]
}"""

    log("Generating script via Groq LLaMA 3 70B...")

    def _generate():
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama3-70b-8192",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content":
                        f"Write a Hinglish fact video script (12-14 phrases) "
                        f"based on this research:\n\n{fact_context}"}
                ],
                "temperature": 0.8,
                "max_tokens": 2000,
            },
            timeout=90
        )
        if response.status_code != 200:
            raise RuntimeError(f"Groq error {response.status_code}: "
                               f"{response.text[:300]}")
        content = response.json()["choices"][0]["message"]["content"]
        script = safe_json_parse(content)
        if not script:
            raise ValueError("Failed to parse JSON from Groq response")
        phrases = script.get("phrases", [])
        if len(phrases) < 8:
            raise ValueError(f"Only {len(phrases)} phrases, need ≥ 8")
        return script

    try:
        script = retry(_generate, max_retries=2, delay=5.0)
        phrases = script["phrases"]
        log(f"Script generated: {len(phrases)} phrases")
        for i, phrase in enumerate(phrases):
            log(f"  [{i+1}] {phrase[:70]}")
        return script
    except Exception as e:
        log(f"Script generation failed: {e}", "ERROR")
        # Emergency fallback script
        log("Generating emergency fallback script...", "WARN")
        return generate_emergency_script(fact_context)


def generate_emergency_script(fact_context: str) -> dict:
    """Generate a simple script when Groq fails completely."""
    category = random.choice(["psychology", "space", "weird", "brain"])
    fact_snippet = fact_context[:300]

    phrases = [
        "Kya aap jaante hain?",
        "Yeh fact aapko hairan kar dega!",
        fact_snippet.split(".")[0] if "." in fact_snippet else fact_snippet,
        "Haan, yeh bilkul sach hai!",
        "Scientists ne yeh research mein paya hai.",
        "Aapko yah fact jaanna bahut zaroori hai.",
        "Yeh aapki soch badal dega.",
        "Isliye aapko yeh baat yaad rakhni chahiye.",
        "Kyunki knowledge hi power hoti hai.",
        "Agar yeh fact aapko achha laga, toh like karein!",
        "Aur Ajeebology Shorts ko subscribe karein.",
        "Kyuki aise amazing facts aapko kahi nahi milenge!"
    ]

    return {
        "title": "Amazing Fact You Didn't Know 🤯",
        "category": category,
        "seo_title": f"Amazing {category.capitalize()} Fact | Ajeebology Shorts",
        "description": f"Ek aaisa {category} fact jo aapne kabhi nahi suna hoga! "
                       f"Watch till end for surprise. Ajeebology Shorts - "
                       f"Psychology, Space aur Weird Facts ka best channel!",
        "tags": [f"{category} facts", "hinglish facts", "amazing facts",
                 "mind blowing", "ajeebology"],
        "hashtags": f"#{category} #facts #hinglishfacts #amazing #ajeebology",
        "pexels_keyword": category,
        "phrases": phrases
    }


def validate_script(script: dict) -> dict:
    """Validate and repair script fields."""
    required = ["title", "category", "phrases", "tags", "hashtags"]
    for field in required:
        if field not in script:
            log(f"Missing field '{field}' in script", "WARN")
            if field == "phrases":
                script["phrases"] = ["Default phrase for Ajeebology Shorts!"]
            elif field == "tags":
                script["tags"] = ["facts", "hinglish"]
            elif field == "hashtags":
                script["hashtags"] = "#facts"
            else:
                script[field] = f"Amazing Facts {datetime.now().day}"

    # Ensure phrases are valid
    phrases = []
    for p in script["phrases"]:
        p = p.strip()
        if len(p.split()) >= PHRASE_MIN_WORDS and len(p) < 200:
            phrases.append(p)
    if not phrases:
        phrases = ["Kya aap jaante hain? Yeh fact amazing hai!"]
    script["phrases"] = phrases[:14]  # cap at 14

    return script


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5: STEP 3 — AUDIO GENERATION (edge-tts per phrase)          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

async def generate_single_audio(phrase: str, output_path: Path,
                                 voice: str = "hi-IN-MadhurNeural",
                                 rate: str = "-5%",
                                 pitch: str = "-2Hz") -> float:
    """Generate TTS audio for a single phrase. Returns duration in seconds."""
    try:
        communicate = edge_tts.Communicate(
            text=phrase.strip(),
            voice=voice,
            rate=rate,
            pitch=pitch
        )
        await communicate.save(str(output_path))
    except Exception as e:
        log(f"edge-tts failed for '{phrase[:40]}...': {e}", "ERROR")
        # Create a minimal silent file as fallback
        run_ffmpeg([
            "-f", "lavfi", "-i",
            f"anullsrc=r=44100:cl=mono:d=2.0",
            str(output_path)
        ])

    duration = get_media_duration(output_path)
    if duration < 0.2:
        log(f"Very short audio ({duration:.2f}s) for: {phrase[:40]}", "WARN")
    return duration


async def generate_all_audio(phrases: list) -> List[Dict]:
    """Generate audio for all phrases sequentially (edge-tts is rate-limited)."""
    audio_files = []
    total = len(phrases)
    log(f"Generating audio for {total} phrases with edge-tts...")

    for i, phrase in enumerate(phrases):
        audio_path = OUTPUT_DIR / f"phrase_{i:03d}.mp3"
        log(f"  TTS [{i+1}/{total}] ~{phrase[:55]}...")
        duration = await generate_single_audio(phrase, audio_path)

        audio_files.append({
            "index": i,
            "phrase": phrase,
            "path": str(audio_path),
            "duration": duration,
            "words": phrase.split(),
            "word_count": len(phrase.split()),
        })

        # Brief pause to avoid rate limiting
        if i < total - 1:
            await asyncio.sleep(0.3)

    total_duration = sum(af["duration"] for af in audio_files)
    log(f"Total raw audio: {total_duration:.1f}s across {total} phrases")
    return audio_files


def concatenate_and_trim_audio(audio_files: List[Dict],
                                output_path: Path) -> float:
    """Concatenate all phrase audio files with crossfade, trim silence."""
    log("Concatenating and processing audio...")

    # Create concat file
    concat_list = OUTPUT_DIR / "concat.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for af in audio_files:
            f.write(f"file '{af['path']}'\n")

    # Concatenate
    raw_combined = OUTPUT_DIR / "voice_raw.mp3"
    success, _, _ = run_ffmpeg([
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(raw_combined)
    ])

    if not success:
        log("Direct concat failed, re-encoding...", "WARN")
        success, _, _ = run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(raw_combined)
        ])

    if not success or not raw_combined.exists():
        log("Audio concatenation failed!", "ERROR")
        return 0.0

    # Trim leading/trailing silence
    trimmed = OUTPUT_DIR / "voice_trimmed.mp3"
    success, _, _ = run_ffmpeg([
        "-i", str(raw_combined),
        "-af",
        "silenceremove=start_periods=1:start_duration=0.3:"
        "start_threshold=-45dB:detection=peak,"
        "silenceremove=stop_periods=1:stop_duration=0.3:"
        "stop_threshold=-45dB:detection=peak",
        str(trimmed)
    ])

    if success and trimmed.exists():
        shutil.move(str(trimmed), str(output_path))
    else:
        shutil.move(str(raw_combined), str(output_path))

    duration = get_media_duration(output_path)
    log(f"Voice audio ready: {duration:.1f}s")
    return duration


def calculate_word_timings(phrase: str, phrase_duration: float
                           ) -> List[Dict]:
    """Calculate per-word timings within a phrase using char-length weighting.
    
    This gives reasonable word-level timing without needing Whisper.
    Longer words naturally take more time to speak.
    Returns list of {word, start, end, duration_cs} where cs = centiseconds.
    """
    words = phrase.strip().split()
    if not words:
        return []

    total_chars = sum(len(w) for w in words)
    if total_chars == 0:
        total_chars = 1

    timings = []
    current_time = 0.0

    for word in words:
        # Each word gets time proportional to its character length
        word_duration = (len(word) / total_chars) * phrase_duration
        # But ensure minimum duration for very short words
        word_duration = max(word_duration, 0.15)

        timings.append({
            "word": word,
            "start": current_time,
            "end": current_time + word_duration,
            "duration_cs": int(word_duration * 100)  # centiseconds for ASS
        })
        current_time += word_duration

    return timings


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 6: STEP 4 — BACKGROUND MUSIC                                 ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def fetch_background_music(target_duration: float) -> Optional[Path]:
    """Fetch royalty-free background music. Multiple fallback sources."""
    output_path = OUTPUT_DIR / "bg_music.mp3"
    log(f"Fetching background music ({target_duration:.0f}s target)...")

    # Source 1: SoundHelix (always available, no API key)
    soundhelix_tracks = [
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-16.mp3",
    ]

    for url in soundhelix_tracks:
        try:
            track_name = url.split("/")[-1]
            log(f"  Trying SoundHelix: {track_name}")

            resp = requests.get(url, stream=True, timeout=30)
            if resp.status_code != 200:
                continue

            temp_path = OUTPUT_DIR / "music_source.mp3"
            with open(temp_path, "wb") as f:
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > 10 * 1024 * 1024:  # 10MB cap
                        break

            if temp_path.stat().st_size < 10000:
                log(f"  {track_name}: file too small", "WARN")
                continue

            # Trim to exact duration and apply fade in/out
            success, _, _ = run_ffmpeg([
                "-i", str(temp_path),
                "-t", str(target_duration + 2),
                "-af",
                "volume=0.12,"
                "afade=t=in:ss=0:d=2,"
                "afade=t=out:st=" + str(target_duration - 2) + ":d=2",
                str(output_path)
            ])

            if success and output_path.exists():
                log(f"  ✓ Background music ready ({get_file_size_mb(output_path):.1f} MB)")
                return output_path

        except Exception as e:
            log(f"  Music source failed: {e}", "WARN")
            continue

    # Source 2: Generate ambient/chill background with ffmpeg
    log("  Generating ambient background music (pink noise + tone)...")
    success, _, _ = run_ffmpeg([
        "-f", "lavfi",
        "-i", f"anoisesrc=d={target_duration}:c=pink:a=0.015",
        "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={target_duration}",
        "-filter_complex",
        "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.3[out]",
        "-map", "[out]", "-c:a", "libmp3lame", "-q:a", "5",
        str(output_path)
    ])

    if success:
        log("  ✓ Ambient background generated")
        return output_path

    log("  No background music available", "WARN")
    return None


def apply_sidechain_ducking(voice_path: Path, music_path: Path,
                             output_path: Path, threshold: float = -18,
                             ratio: float = 5, attack: float = 10,
                             release: float = 100) -> bool:
    """Apply sidechain compression to duck music under voice."""
    log("Applying sidechain compression (music ducks under voice)...")

    success, _, _ = run_ffmpeg([
        "-i", str(music_path),
        "-i", str(voice_path),
        "-filter_complex",
        f"[0:a]volume=0.15[music];"
        f"[1:a]asplit[voice][voice_side];"
        f"[music][voice_side]sidechaincompress="
        f"threshold={threshold}dB:ratio={ratio}:"
        f"attack={attack}ms:release={release}ms[music_ducked];"
        f"[music_ducked][voice]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(output_path)
    ], timeout=120)

    if success:
        log(f"  ✓ Sidechain ducking complete")
    else:
        log("  Sidechain compression failed, using simple volume mix", "WARN")
        # Fallback: simple volume mix
        success, _, _ = run_ffmpeg([
            "-i", str(voice_path),
            "-i", str(music_path),
            "-filter_complex",
            "[1:a]volume=0.10[music_low];"
            "[0:a][music_low]amix=inputs=2:duration=first[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(output_path)
        ])

    return success


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 7: STEP 5 — STOCK VIDEO (Pexels API)                        ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def search_pexels_videos(keyword: str, per_page: int = 15) -> List[Dict]:
    """Search Pexels for vertical videos. Returns list of video info dicts."""
    log(f"Searching Pexels for: '{keyword}'")

    try:
        response = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query": keyword,
                "orientation": "portrait",
                "size": "medium",
                "per_page": per_page,
            },
            timeout=30
        )

        if response.status_code != 200:
            log(f"Pexels error {response.status_code}: {response.text[:200]}", "WARN")
            return []

        data = response.json()
        videos = data.get("videos", [])
        log(f"  Found {len(videos)} videos")

        # Parse into usable format
        parsed = []
        for video in videos:
            video_info = {
                "id": video.get("id"),
                "duration": video.get("duration", 0),
                "width": 0,
                "height": 0,
                "url": None,
                "quality": "unknown",
                "photographer": video.get("user", {}).get("name", "Unknown"),
            }

            # Find best file for 9:16 portrait
            for file in video.get("video_files", []):
                w = file.get("width", 0)
                h = file.get("height", 0)
                # Prefer 1080x1920 or closest
                if w >= 1080 and h >= 1920:
                    video_info["width"] = w
                    video_info["height"] = h
                    video_info["url"] = file["link"]
                    video_info["quality"] = "1080p"
                    break
                elif w >= 720 and h >= 1280 and video_info["quality"] == "unknown":
                    video_info["width"] = w
                    video_info["height"] = h
                    video_info["url"] = file["link"]
                    video_info["quality"] = "720p"

            if video_info["url"]:
                parsed.append(video_info)

        log(f"  {len(parsed)} usable vertical videos")
        return parsed

    except requests.exceptions.RequestException as e:
        log(f"Pexels API error: {e}", "ERROR")
        return []


def download_pexels_video(video_info: Dict, output_path: Path) -> bool:
    """Download a single Pexels video file."""
    url = video_info["url"]
    photographer = video_info.get("photographer", "Unknown")

    log(f"  Downloading ({video_info['quality']}): {url.split('?')[0][:60]}...")

    try:
        response = requests.get(url, stream=True, timeout=120)
        if response.status_code != 200:
            log(f"    Download failed: HTTP {response.status_code}", "WARN")
            return False

        with open(output_path, "wb") as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > 50 * 1024 * 1024:  # 50MB cap
                        log(f"    Large file, stopping at 50MB", "WARN")
                        break

        size_mb = get_file_size_mb(output_path)
        log(f"    Downloaded: {size_mb:.1f} MB (by {photographer})")

        if size_mb < 0.1:
            log(f"    File too small, discarding", "WARN")
            output_path.unlink(missing_ok=True)
            return False

        return True

    except Exception as e:
        log(f"    Download error: {e}", "ERROR")
        return False


def download_stock_videos(keyword: str, category: str,
                           target_duration: float,
                           max_clips: int = 3) -> List[Path]:
    """Download multiple stock video clips for variety."""
    ensure_dir(STOCK_VIDEO_DIR)

    # Try primary keyword first
    keywords_to_try = [keyword, category, "abstract background",
                       "time lapse nature", "space", "sci fi"]
    videos = []

    for kw in keywords_to_try:
        if len(videos) >= max_clips:
            break
        results = search_pexels_videos(kw)
        if results:
            # Take top results we don't already have
            for video_info in results[:max_clips]:
                if len(videos) >= max_clips:
                    break
                clip_path = STOCK_VIDEO_DIR / f"stock_{len(videos):02d}.mp4"
                if download_pexels_video(video_info, clip_path):
                    videos.append(clip_path)
                    log(f"  ✓ Clip {len(videos)}: {kw}")

    if not videos:
        log("No stock videos downloaded from Pexels", "WARN")

    return videos


def get_video_duration_safe(file_path: Path) -> float:
    """Get video duration, with a cap for very long files."""
    duration = get_media_duration(file_path)
    if duration > 120:
        log(f"  Video too long ({duration:.0f}s), will loop segments", "WARN")
    return duration


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 8: STEP 6 — SUBTITLE GENERATION (ASS with karaoke)          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def generate_ass_subtitles(audio_files: List[Dict],
                            output_path: Path,
                            margin_v: int = 400) -> str:
    """Generate ASS subtitle file with word-by-word karaoke highlighting.
    
    Uses \k tags for karaoke effect:
    - Unspoken words appear in SecondaryColour (white)
    - Spoken/current word fills with PrimaryColour (cyan)
    - Semi-transparent background box behind text (BorderStyle=3)
    """
    log("Generating ASS subtitles with karaoke word highlighting...")

    ass_header = f"""[Script Info]
; ASS subtitle file for Ajeebology Shorts
; Generated by automated pipeline
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,DejaVu Sans Bold,42,&H00FFFF00,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,1,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    current_time = 0.0

    for af in audio_files:
        phrase = af["phrase"]
        phrase_duration = af["duration"]
        words = phrase.strip().split()

        if phrase_duration <= 0 or len(words) == 0:
            current_time += max(phrase_duration, 2.0)
            continue

        # Calculate word timings
        word_timings = calculate_word_timings(phrase, phrase_duration)

        # Build karaoke line with \k tags
        # Format: {\kCS}word where CS = centiseconds
        karaoke_text = ""
        for wt in word_timings:
            cs = max(1, wt["duration_cs"])
            escaped_word = wt["word"].replace("{", "\\{").replace("}", "\\}")
            karaoke_text += f"{{\\k{cs}}}{escaped_word} "

        karaoke_text = karaoke_text.strip()

        start_time = current_time
        end_time = current_time + phrase_duration

        # Format timestamps for ASS (H:MM:SS.cs)
        start_ass = format_time(start_time)
        end_ass = format_time(end_time)

        event = (
            f"Dialogue: 0,{start_ass},{end_ass},"
            f"Karaoke,,0,0,0,,{karaoke_text}"
        )
        events.append(event)

        current_time = end_time

    total_duration = current_time
    ass_content = ass_header + "\n".join(events) + "\n"

    # Write file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    log(f"  ASS file written: {len(events)} subtitle events")
    log(f"  Total subtitle duration: {total_duration:.1f}s")

    return ass_content


def build_drawtext_fallback(audio_files: List[Dict],
                             total_duration: float) -> str:
    """Build ffmpeg drawtext filter chain as fallback (no libass needed).
    
    Each phrase gets a drawtext filter with enable='between(t,start,end)'.
    This is less fancy than ASS karaoke but still professional-looking.
    """
    log("Building drawtext subtitle filters (ASS fallback)...")
    filters = []
    current_time = 0.0

    for i, af in enumerate(audio_files):
        start_time = current_time
        end_time = current_time + af["duration"]
        phrase = af["phrase"]

        # Escape special chars for drawtext
        escaped = (phrase
                   .replace("'", "'\\\\\\''")
                   .replace(":", "\\:")
                   .replace("%", "\\%")
                   .replace("{", "\\{")
                   .replace("}", "\\}")
                   .replace("\\", "\\\\"))

        text_filter = (
            f"drawtext="
            f"text='{escaped}'"
            f":fontsize=38"
            f":fontcolor=white"
            f":box=1"
            f":boxcolor=black@0.6"
            f":boxborderw=18"
            f":x=(w-text_w)/2"
            f":y=h-text_h-180"
            f":fontfile={FONT_BOLD}"
            f":enable='between(t,{start_time:.2f},{end_time:.2f})'"
        )
        filters.append(text_filter)
        current_time = end_time

    filter_string = ",".join(filters)
    log(f"  Drawtext chain: {len(audio_files)} filters")
    return filter_string


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 9: STEP 7 — VIDEO EFFECTS                                    ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def apply_ken_burns(input_path: Path, output_path: Path,
                     target_duration: float,
                     zoom_start: float = 1.0,
                     zoom_end: float = 1.08) -> bool:
    """Apply subtle Ken Burns zoom effect using ffmpeg zoompan."""
    log(f"  Applying Ken Burns zoom ({zoom_start}→{zoom_end})...")

    # zoompan: z='min(zoom+0.001, 1.5)' gradually zooms in
    zoom_rate = (zoom_end - zoom_start) / (target_duration * VIDEO_FPS)
    zoom_expr = f"min({zoom_start}+{zoom_rate:.6f}*on,{zoom_end})"

    success, _, _ = run_ffmpeg([
        "-stream_loop", "-1",
        "-i", str(input_path),
        "-t", str(target_duration),
        "-vf",
        f"zoompan=z='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={int(target_duration * VIDEO_FPS)}:"
        f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
        f"fps={VIDEO_FPS}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ], timeout=180)

    return success


def apply_color_grading(input_path: Path, output_path: Path) -> bool:
    """Apply subtle color grading for brand consistency (purple/cyan tint)."""
    log("  Applying color grading (brand purple/cyan)...")

    # Use colorbalance and curves for cinematic look
    success, _, _ = run_ffmpeg([
        "-i", str(input_path),
        "-vf",
        "colorbalance=rs=-0.05:gs=-0.02:bs=0.08,"
        "curves=vintage='0/0 0.2/0.15 0.8/0.85 1/1'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ], timeout=120)

    return success


def create_intro_card(duration: float = 3.0,
                       text_line1: str = "Ajeebology Shorts",
                       text_line2: str = "Amazing Facts in Hinglish") -> bool:
    """Create a branded intro card using ffmpeg (no PIL needed).
    
    3-second intro with:
    - Purple gradient background
    - Channel name in cyan
    - Tagline in white
    - Smooth fade in/out
    """
    log(f"Creating intro card ({duration}s)...")

    # Generate gradient background with text
    success, _, _ = run_ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={BRAND_PURPLE_HEX}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
              f"d={duration}:r={VIDEO_FPS}",
        # Add subtle radial gradient overlay
        "-f", "lavfi",
        "-i", f"nullsrc=s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={VIDEO_FPS}",
        "-filter_complex",
        f"[0:v][1:v]overlay[bg];"
        f"[bg]drawtext=text='{text_line1}':"
        f"fontsize=64:fontcolor={BRAND_CYAN_HEX}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-60:"
        f"fontfile={FONT_BOLD}:"
        f"shadowx=3:shadowy=3:shadowcolor=black@0.5[withtitle];"
        f"[withtitle]drawtext=text='{text_line2}':"
        f"fontsize=32:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+30:"
        f"fontfile={FONT_REGULAR}[withsubtitle];"
        f"[withsubtitle]fade=t=in:st=0:d=0.5:alpha=1,"
        f"fade=t=out:st={duration-0.7}:d=0.7:alpha=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(INTRO_VIDEO)
    ], timeout=60)

    if success:
        log(f"  ✓ Intro card created")
    else:
        log(f"  Intro card failed", "WARN")

    return success


def create_subscribe_overlay(duration: float = 4.0) -> bool:
    """Create a subscribe animation overlay using ffmpeg drawscreen.
    
    Shows at the end of the video with a pulsing subscribe button.
    """
    log(f"Creating subscribe overlay ({duration}s)...")

    # Generate animated subscribe overlay
    success, _, _ = run_ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c=black@0:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
              f"d={duration}:r={VIDEO_FPS}",
        "-vf",
        f"drawtext=text='Ajeebology Shorts':"
        f"fontsize=52:fontcolor={BRAND_CYAN_HEX}:"
        f"x=(w-text_w)/2:y=(h/2)-80:"
        f"fontfile={FONT_BOLD}:"
        f"enable='between(t,0,{duration})',"
        f"drawtext=text='📢 SUBSCRIBE KAREIN!':"
        f"fontsize=44:fontcolor={BRAND_GOLD_HEX}:"
        f"x=(w-text_w)/2:y=(h/2):"
        f"fontfile={FONT_BOLD}:"
        f"enable='between(t,0,{duration})',"
        f"drawtext=text='🔔 Bell icon dabayein':"
        f"fontsize=28:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h/2)+80:"
        f"fontfile={FONT_REGULAR}:"
        f"enable='between(t,0,{duration})',"
        f"fade=t=in:st=0:d=0.8:alpha=1,"
        f"fade=t=out:st={duration-0.5}:d=0.5:alpha=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25",
        "-pix_fmt", "yuv420p",
        str(SUBSCRIBE_OVERLAY)
    ], timeout=60)

    return success


def create_progress_bar_animation(total_duration: float,
                                   bar_color: str = BRAND_CYAN_HEX) -> str:
    """Return ffmpeg overlay filter for an animated bottom progress bar.
    
    The bar starts at x=-w (offscreen left) and slides to x=0 (full width)
    over the duration of the video.
    """
    # Create a small colored bar image
    bar_path = OUTPUT_DIR / "progress_bar.png"
    bar_height = 4
    bar_width = VIDEO_WIDTH

    # Generate bar with ffmpeg
    run_ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={bar_color}:s={bar_width}x{bar_height}:d=1",
        "-vframes", "1",
        str(bar_path)
    ])

    # Return overlay filter string
    # x starts at -w (hidden) and goes to 0 (full width)
    # y is at the very bottom of the video
    overlay_filter = (
        f"movie={bar_path}:loop=0:setpts=PTS-STARTPTS[bar];"
        f"[in][bar]overlay="
        f"x='-W+(W/{total_duration})*t':"
        f"y=H-h-10:shortest=1"
    )

    return overlay_filter


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 10: STEP 8 — FINAL VIDEO ASSEMBLY                            ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def assemble_final_video(
    stock_clips: List[Path],
    intro_video: Optional[Path],
    audio_path: Path,
    subtitle_source: str,  # ASS file path OR drawtext filter string
    subscribe_overlay: Optional[Path],
    total_duration: float,
    output_path: Path
) -> bool:
    """Assemble all components into the final video.
    
    Pipeline:
    1. If multiple stock clips → crossfade between them
    2. If intro exists → prepend it
    3. Apply Ken Burns zoom to stock footage
    4. Overlay subtitles (ASS or drawtext)
    5. Overlay progress bar
    6. Overlay subscribe CTA (last 4 seconds)
    7. Mix with audio
    """
    log("═══ FINAL VIDEO ASSEMBLY ═══")

    # ── Step A: Process stock clips with Ken Burns ──
    processed_clips = []
    clips_dir = OUTPUT_DIR / "processed_clips"
    ensure_dir(clips_dir)

    if not stock_clips:
        log("No stock clips available, generating fallback...", "WARN")
        fallback = clips_dir / "fallback.mp4"
        run_ffmpeg([
            "-f", "lavfi",
            "-i", f"color=c={BRAND_PURPLE_HEX}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
                  f"d={total_duration}:r={VIDEO_FPS}",
            "-vf",
            f"drawbox=x=0:y=0:w=iw:h=ih:"
            f"color=purple@0.1:t=fill,"
            f"drawtext=text='Ajeebology Shorts':"
            f"fontsize=40:fontcolor=white@0.2:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:fontfile={FONT_BOLD}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(fallback)
        ])
        processed_clips.append(fallback)
    else:
        # Calculate duration per clip
        clip_duration = total_duration / len(stock_clips)
        for i, clip in enumerate(stock_clips):
            processed = clips_dir / f"kenburns_{i:02d}.mp4"
            log(f"  Processing clip {i+1}/{len(stock_clips)}...")
            if apply_ken_burns(clip, processed, clip_duration):
                processed_clips.append(processed)
            else:
                # Use raw clip if Ken Burns fails
                log(f"  Ken Burns failed for clip {i+1}, using raw", "WARN")
                processed_clips.append(clip)

    # ── Step B: Concatenate clips with crossfade ──
    if len(processed_clips) > 1:
        log("  Crossfading clips...")
        concat_base = clips_dir / "concatenated.mp4"
        # Build xfade chain
        filter_parts = []
        for i in range(len(processed_clips)):
            filter_parts.append(f"[{i}:v]")

        xfade_parts = []
        offset = 0
        for i in range(len(processed_clips) - 1):
            clip_dur = get_media_duration(processed_clips[i])
            xfade_parts.append(
                f"[{i}:v][{i+1}:v]xfade="
                f"transition=fade:duration=0.5:offset={offset + clip_dur - 0.5}"
            )
            offset += clip_dur

        if xfade_parts:
            xfade_filter = ";".join(xfade_parts)
            input_files = []
            for clip in processed_clips:
                input_files.extend(["-i", str(clip)])

            success, _, _ = run_ffmpeg(
                input_files + [
                    "-filter_complex", xfade_filter + "[outv]",
                    "-map", "[outv]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-pix_fmt", "yuv420p",
                    str(concat_base)
                ], timeout=180
            )

            if success:
                processed_clips = [concat_base]
            else:
                log("  Crossfade failed, using simple concat", "WARN")
    else:
        log("  Single clip (or none) — no crossfade needed")

    # ── Step C: Prepend intro if available ──
    if intro_video and intro_video.exists():
        log("  Prepending intro card...")
        final_base = clips_dir / "with_intro.mp4"
        # Concatenate intro + main video
        concat_file = clips_dir / "concat_videos.txt"
        with open(concat_file, "w") as f:
            f.write(f"file '{intro_video}'\n")
            f.write(f"file '{processed_clips[-1]}'\n")

        run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(final_base)
        ])
        processed_clips = [final_base]

    # ── Step D: Final composition ──
    # Input: processed video + audio
    # Filters: subtitles + progress bar + subscribe overlay + output
    log("  Composing final video with overlays...")

    video_source = processed_clips[-1] if processed_clips else None
    if not video_source or not video_source.exists():
        log("No video source available!", "CRITICAL")
        return False

    # Determine if we have ASS file or drawtext string
    is_ass = subtitle_source.endswith(".ass")

    # Build filter complex
    if is_ass:
        # ASS subtitles via subtitles filter
        subtitle_filter = f"subtitles={subtitle_source}"
    else:
        # drawtext filter string
        subtitle_filter = subtitle_source

    # Add subscribe overlay for last few seconds
    subscribe_duration = 4.0
    subscribe_start = max(0, total_duration - subscribe_duration)
    if subscribe_overlay and subscribe_overlay.exists():
        subscribe_filter = (
            f"[subbed]"
            f"movie={subscribe_overlay}:loop=0:setpts=PTS-STARTPTS[sub];"
            f"[subbed][sub]overlay=0:0:shortest=1:"
            f"enable='between(t,{subscribe_start},{total_duration})'[outv]"
        )
        full_filter = f"[0:v]{subtitle_filter}[subbed];{subscribe_filter}"
    else:
        full_filter = f"[0:v]{subtitle_filter}[outv]"

    # Assemble!
    success, _, _ = run_ffmpeg([
        "-stream_loop", "-1",
        "-i", str(video_source),
        "-i", str(audio_path),
        "-filter_complex", full_filter,
        "-map", "[outv]",
        "-map", "1:a",
        "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path)
    ], timeout=600)

    if success:
        final_size = get_file_size_mb(output_path)
        final_dur = get_media_duration(output_path)
        log(f"  ✓ FINAL VIDEO: {final_dur:.1f}s, {final_size:.1f} MB")
        return True

    log("  Final assembly failed!", "ERROR")
    return False


def generate_thumbnail(video_path: Path, output_path: Path) -> bool:
    """Generate a thumbnail from the video at mid-point."""
    duration = get_media_duration(video_path)
    mid_point = duration / 2

    success, _, _ = run_ffmpeg([
        "-i", str(video_path),
        "-ss", str(mid_point),
        "-vframes", "1",
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
        "-q:v", "8",
        str(output_path)
    ])
    return success


def verify_video(file_path: Path) -> bool:
    """Verify the final video is valid and playable."""
    if not file_path.exists():
        log("Video file does not exist!", "ERROR")
        return False

    size_mb = get_file_size_mb(file_path)
    if size_mb < 0.5:
        log(f"Video too small: {size_mb:.1f} MB", "ERROR")
        return False

    duration = get_media_duration(file_path)
    if duration < 10:
        log(f"Video too short: {duration:.1f}s", "ERROR")
        return False

    width, height = get_video_resolution(file_path)
    if width < 100 or height < 100:
        log(f"Invalid resolution: {width}x{height}", "ERROR")
        return False

    log(f"✓ Verification passed: {duration:.1f}s, {size_mb:.1f}MB, "
        f"{width}x{height}")
    return True


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 11: STEP 9 — TELEGRAM DELIVERY                               ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def send_telegram_message(text: str, parse_mode: str = "Markdown"):
    """Send a text message to Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text[:4000],
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=30
        )
    except Exception as e:
        log(f"Telegram message send failed: {e}", "WARN")


def send_telegram_video(video_path: Path, caption: str) -> bool:
    """Send the video file to Telegram."""
    file_size_mb = get_file_size_mb(video_path)

    if file_size_mb > 48:
        log(f"Video too large for Telegram ({file_size_mb:.1f}MB > 48MB)",
            "WARN")
        return False

    log(f"Sending video to Telegram ({file_size_mb:.1f} MB)...")

    try:
        with open(video_path, "rb") as f:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],
                    "parse_mode": "Markdown",
                    "supports_streaming": True,
                    "width": VIDEO_WIDTH,
                    "height": VIDEO_HEIGHT,
                },
                files={"video": f},
                timeout=300
            )

        if response.status_code == 200:
            log("✓ Video sent to Telegram successfully!")
            return True
        else:
            log(f"Telegram error: {response.status_code} — "
                f"{response.text[:200]}", "ERROR")
            return False

    except Exception as e:
        log(f"Telegram send failed: {e}", "ERROR")
        return False


def format_telegram_message(metadata: dict, duration: float,
                             file_size_mb: float) -> str:
    """Format the full metadata message for Telegram."""
    date_str = datetime.now().strftime("%d %b %Y")

    message = (
        f"🎬 **AJEEBOLOGY SHORTS — VIDEO READY**\n\n"
        f"**📺 Title:**\n{metadata['title']}\n\n"
        f"**📝 SEO Title:**\n{metadata.get('seo_title', metadata['title'])}\n\n"
        f"**📖 Description:**\n{metadata.get('description', '')}\n\n"
        f"**🏷 Tags:**\n`{', '.join(metadata['tags'][:10])}`\n\n"
        f"**🔖 Hashtags:**\n{metadata.get('hashtags', '')}\n\n"
        f"**📂 Category:** {metadata.get('category', 'facts')}\n"
        f"**⏱ Duration:** {duration:.0f}s\n"
        f"**📦 Size:** {file_size_mb:.1f} MB\n"
        f"**📅 Date:** {date_str}\n\n"
        f"📥 **Download:** Check GitHub Actions artifacts (retention: 3 days)\n"
        f"📤 *Upload this video to YouTube Shorts manually*"
    )

    return message


def deliver_to_telegram(metadata: dict, total_duration: float):
    """Complete Telegram delivery with progress updates."""
    log("═══ TELEGRAM DELIVERY ═══")

    # Check video
    if not FINAL_VIDEO.exists():
        log("Final video not found!", "ERROR")
        send_telegram_message(
            "❌ *Pipeline Failed:* Final video was not generated.\n"
            "Check GitHub Actions logs for details."
        )
        return

    file_size_mb = get_file_size_mb(FINAL_VIDEO)
    actual_duration = get_media_duration(FINAL_VIDEO)

    # Format caption
    caption = format_telegram_message(metadata, actual_duration, file_size_mb)

    # Try sending video
    sent = send_telegram_video(FINAL_VIDEO, caption)

    if not sent:
        # Generate and send thumbnail instead
        log("Sending thumbnail with metadata instead...")
        if generate_thumbnail(FINAL_VIDEO, THUMBNAIL_FILE):
            try:
                with open(THUMBNAIL_FILE, "rb") as f:
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                        data={
                            "chat_id": TELEGRAM_CHAT_ID,
                            "caption": caption[:1024],
                            "parse_mode": "Markdown",
                        },
                        files={"photo": f},
                        timeout=60
                    )
                log("✓ Thumbnail sent")
            except Exception as e:
                log(f"Thumbnail send failed: {e}", "ERROR")
                # Last resort: just text
                send_telegram_message(caption, parse_mode="Markdown")
        else:
            send_telegram_message(caption, parse_mode="Markdown")

    # Send a brief success message
    send_telegram_message(
        f"✅ *Pipeline Complete* — {actual_duration:.0f}s video ready!\n"
        f"📁 Artifact: `output_video.mp4` in GitHub Actions",
        parse_mode="Markdown"
    )


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 12: MAIN PIPELINE ORCHESTRATOR                               ║
# ╚═════════════════════════════════════════════════════════════════════════╝

async def run_pipeline():
    """Execute the complete video generation pipeline."""
    pipeline_start = time.time()
    total_steps = 9

    # ──────────────────────────────────────────
    # STEP 1: RESEARCH
    # ──────────────────────────────────────────
    log_step(1, total_steps, "RESEARCH")
    fact_context = research_fact()
    log(f"Research context: {len(fact_context)} chars")

    # ──────────────────────────────────────────
    # STEP 2: SCRIPT GENERATION
    # ──────────────────────────────────────────
    log_step(2, total_steps, "SCRIPT GENERATION")
    script = generate_script(fact_context)
    script = validate_script(script)
    phrases = script["phrases"]
    pexels_keyword = script.get("pexels_keyword", script.get("category", "facts"))
    log(f"Script: {len(phrases)} phrases, keyword: '{pexels_keyword}'")

    # Save metadata for later
    metadata = {
        "title": script["title"],
        "category": script.get("category", "facts"),
        "seo_title": script.get("seo_title", script["title"]),
        "description": script.get("description", ""),
        "tags": script.get("tags", ["facts", "hinglish"]),
        "hashtags": script.get("hashtags", "#facts"),
    }

    # ──────────────────────────────────────────
    # STEP 3: AUDIO GENERATION
    # ──────────────────────────────────────────
    log_step(3, total_steps, "AUDIO GENERATION")
    audio_files = await generate_all_audio(phrases)

    if not audio_files:
        log("No audio generated!", "CRITICAL")
        return

    total_voice_duration = concatenate_and_trim_audio(audio_files, VOICE_AUDIO)
    metadata["duration"] = total_voice_duration

    if total_voice_duration < MIN_DURATION:
        log(f"Voice audio short ({total_voice_duration:.0f}s), "
            f"consider regenerating script", "WARN")

    # ──────────────────────────────────────────
    # STEP 4: BACKGROUND MUSIC
    # ──────────────────────────────────────────
    log_step(4, total_steps, "BACKGROUND MUSIC")
    music_path = fetch_background_music(total_voice_duration)

    if music_path:
        # Mix voice + music with ducking
        log("Mixing voice + background music...")
        success = apply_sidechain_ducking(
            VOICE_AUDIO, music_path, FINAL_AUDIO
        )
        if not success:
            log("Audio mixing failed, using voice only", "WARN")
            shutil.copy(VOICE_AUDIO, FINAL_AUDIO)
    else:
        log("No background music, using voice only")
        shutil.copy(VOICE_AUDIO, FINAL_AUDIO)

    # ──────────────────────────────────────────
    # STEP 5: STOCK VIDEO
    # ──────────────────────────────────────────
    log_step(5, total_steps, "STOCK VIDEO DOWNLOAD")
    stock_clips = download_stock_videos(
        pexels_keyword,
        script.get("category", "facts"),
        total_voice_duration,
        max_clips=2
    )
    log(f"Stock clips downloaded: {len(stock_clips)}")

    # ──────────────────────────────────────────
    # STEP 6: INTRO CARD
    # ──────────────────────────────────────────
    log_step(6, total_steps, "INTRO & OVERLAYS")
    create_intro_card(
        duration=3.0,
        text_line1="Ajeebology Shorts",
        text_line2=script.get("category", "Facts").capitalize() + " Facts"
    )
    create_subscribe_overlay(duration=4.0)

    # ──────────────────────────────────────────
    # STEP 7: SUBTITLES
    # ──────────────────────────────────────────
    log_step(7, total_steps, "SUBTITLES")
    # Generate ASS subtitles with karaoke
    generate_ass_subtitles(audio_files, SUBTITLES_FILE, margin_v=400)
    subtitle_source = str(SUBTITLES_FILE)

    # Check if ASS will work (test ffmpeg with libass)
    ass_test = OUTPUT_DIR / "ass_test.txt"
    with open(ass_test, "w") as f:
        f.write("[Script Info]\nScriptType: v4.00+\n")
    has_libass = False
    success, _, _ = run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=black:s=1x1:d=0.1",
        "-vf", f"subtitles={ass_test}",
        "-f", "null", "-"
    ])
    if success:
        has_libass = True
        log("  ✓ libass available — using ASS karaoke subtitles")
    else:
        log("  libass NOT available — falling back to drawtext subtitles", "WARN")
        subtitle_source = build_drawtext_fallback(
            audio_files, total_voice_duration
        )

    # ──────────────────────────────────────────
    # STEP 8: FINAL ASSEMBLY
    # ──────────────────────────────────────────
    log_step(8, total_steps, "FINAL VIDEO ASSEMBLY")

    # Determine the audio to use
    audio_to_use = FINAL_AUDIO if FINAL_AUDIO.exists() else VOICE_AUDIO

    # Check if we have a subscribe overlay
    sub_overlay = SUBSCRIBE_OVERLAY if SUBSCRIBE_OVERLAY.exists() else None

    success = assemble_final_video(
        stock_clips=stock_clips,
        intro_video=INTRO_VIDEO if INTRO_VIDEO.exists() else None,
        audio_path=audio_to_use,
        subtitle_source=subtitle_source,
        subscribe_overlay=sub_overlay,
        total_duration=total_voice_duration,
        output_path=FINAL_VIDEO
    )

    if not success:
        log("FINAL ASSEMBLY FAILED!", "CRITICAL")
        send_telegram_message(
            "❌ *Pipeline Failed:* Video assembly error.\n"
            "Check GitHub Actions logs."
        )
        return

    # Verify output
    if not verify_video(FINAL_VIDEO):
        log("Video verification failed!", "CRITICAL")
        return

    # ──────────────────────────────────────────
    # STEP 9: DELIVERY
    # ──────────────────────────────────────────
    log_step(9, total_steps, "TELEGRAM DELIVERY")
    deliver_to_telegram(metadata, total_voice_duration)

    # ──────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────
    elapsed = time.time() - pipeline_start
    log("")
    log("═" * 55)
    log("🏁 PIPELINE COMPLETE")
    log("═" * 55)
    log(f"  Duration:      {elapsed:.0f}s ({elapsed/60:.1f} min)")
    log(f"  Video length:  {get_media_duration(FINAL_VIDEO):.1f}s")
    log(f"  File size:     {get_file_size_mb(FINAL_VIDEO):.1f} MB")
    log(f"  Resolution:    {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
    log(f"  Phrases:       {len(phrases)}")
    log(f"  Category:      {metadata['category']}")
    log(f"  Title:         {metadata['title']}")
    log("═" * 55)

    # Save metadata JSON
    metadata["pipeline_duration_s"] = round(elapsed)
    metadata["video_duration_s"] = round(get_media_duration(FINAL_VIDEO))
    metadata["file_size_mb"] = round(get_file_size_mb(FINAL_VIDEO), 1)
    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)

    # Cleanup temporary files (keep final video + metadata)
    clean_temp_files(keep=[FINAL_VIDEO, METADATA_FILE, LOG_FILE])
    log("Cleanup complete")


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ENTRY POINT                                                          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

async def main():
    """Main entry point with top-level error handling."""
    try:
        # Set up output directory
        ensure_dir(OUTPUT_DIR)

        # Log startup info
        log("")
        log("╔══════════════════════════════════════════════════════════╗")
        log("║     🎬 AJEEBOLOGY SHORTS — PREMIUM VIDEO PIPELINE      ║")
        log("╚══════════════════════════════════════════════════════════╝")
        log(f"Python:        {sys.version.split()[0]}")
        log(f"Output dir:    {OUTPUT_DIR}")
        log(f"Target:        {VIDEO_WIDTH}x{VIDEO_HEIGHT} @ {VIDEO_FPS}fps")
        log(f"Duration:      ~{TARGET_DURATION}s")
        log(f"Date:          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log("")

        # Validate API keys
        missing_keys = []
        for key_name in ["GROQ_API_KEY", "TAVILY_API_KEY", "PEXELS_API_KEY",
                          "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]:
            if not os.environ.get(key_name):
                missing_keys.append(key_name)
        if missing_keys:
            log(f"MISSING API KEYS: {', '.join(missing_keys)}", "CRITICAL")
            log("Set these in GitHub Actions secrets and rerun.", "CRITICAL")
            sys.exit(1)

        log("✓ All API keys found")

        # Run pipeline
        await run_pipeline()

    except Exception as e:
        log(f"❌ UNHANDLED PIPELINE ERROR: {e}", "CRITICAL")
        log(traceback.format_exc(), "CRITICAL")

        try:
            send_telegram_message(
                f"❌ *Pipeline Crashed:*\n`{str(e)[:200]}`\n\n"
                f"Check GitHub Actions logs for full traceback.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
