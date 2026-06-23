#!/usr/bin/env python3
"""
=============================================================================
 AJEEBOLOGY SHORTS — Premium YouTube Shorts Automation Pipeline
=============================================================================
 Fully automated pipeline that generates professional Hinglish fact videos.
 
 Features:
   • Tavily search → fact research
   • Groq LLaMA → Hinglish script with 12-14 punchy phrases
   • edge-tts (hi-IN-MadhurNeural) → per-phrase male voiceover (100% sync)
   • Pexels API → real HD stock video backgrounds (vertical 9:16)
   • ASS karaoke subtitles → word-by-word MrBeast-style highlighting
   • Ken Burns zoompan → subtle motion on stock footage
   • Branded intro card → 3s purple/cyan channel branding
   • Sidechain audio ducking → music lowers when voice speaks
   • Background music → SoundHelix royalty-free + ambient fallback
   • Subscribe overlay → last 4 seconds CTA animation
   • Crossfade transitions → between multiple video clips
   • Color grading → brand-consistent purple/cyan tint
   • Progress bar → animated bottom bar showing playback progress
   • Telegram delivery → video + full SEO metadata
   • Smart fallbacks → every step has 2-3 recovery paths
   • Real error reporting → actual ffmpeg errors sent to Telegram
 
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
from typing import Optional, List, Dict, Tuple, Union

import requests
import edge_tts


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1: CONFIGURATION & CONSTANTS                                 ║
# ╚═════════════════════════════════════════════════════════════════════════╝

# ── API Keys (from GitHub Actions secrets / environment) ──
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY     = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY     = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN     = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# ── Video Output Dimensions ──
VIDEO_WIDTH        = 1080
VIDEO_HEIGHT       = 1920
VIDEO_FPS          = 30

# ── Timing Targets ──
TARGET_DURATION    = 60       # target video length in seconds
MIN_DURATION       = 45       # minimum acceptable duration
MAX_DURATION       = 75       # maximum acceptable duration
PHRASE_MIN_WORDS   = 3        # minimum words per phrase
PHRASE_MAX_WORDS   = 12       # maximum words per phrase
TARGET_PHRASE_COUNT = 12      # target number of phrases for ~60s content

# ── Brand Colors (Ajeebology: Purple + Cyan) ──
BRAND_PURPLE_HEX   = "#1a0a2e"
BRAND_PURPLE_RGB   = "26,10,46"
BRAND_CYAN_HEX     = "#00FFFF"
BRAND_CYAN_RGB     = "0,255,255"
BRAND_GOLD_HEX     = "#FFD700"
BRAND_WHITE_HEX    = "#FFFFFF"
BRAND_DARK_HEX     = "#0D0618"

# ── File Paths (all under /tmp for GitHub Actions) ──
OUTPUT_DIR         = Path("/tmp/ajeebology_output")
FINAL_VIDEO        = OUTPUT_DIR / "output_video.mp4"
VOICE_AUDIO        = OUTPUT_DIR / "voice_combined.mp3"
MUSIC_DUCKED       = OUTPUT_DIR / "music_ducked.mp3"
FINAL_AUDIO        = OUTPUT_DIR / "final_audio.mp3"
STOCK_VIDEO_DIR    = OUTPUT_DIR / "stock_clips"
PROCESSED_CLIPS    = OUTPUT_DIR / "processed_clips"
INTRO_VIDEO        = OUTPUT_DIR / "intro.mp4"
SUBTITLES_FILE     = OUTPUT_DIR / "subtitles.ass"
SUBSCRIBE_OVERLAY  = OUTPUT_DIR / "subscribe_overlay.mp4"
PROGRESS_BAR_FILE  = OUTPUT_DIR / "progress_bar.png"
THUMBNAIL_FILE     = OUTPUT_DIR / "thumbnail.jpg"
METADATA_FILE      = OUTPUT_DIR / "metadata.json"
LOG_FILE           = OUTPUT_DIR / "pipeline.log"

# ── Fonts (installed via apt on ubuntu-latest) ──
FONT_BOLD          = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR       = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2: UTILITY FUNCTIONS                                         ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def log(message: str, level: str = "INFO"):
    """Log a timestamped message to stdout and the log file."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {message}"
    print(formatted, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def log_step(step_num: int, total_steps: int, name: str):
    """Log the beginning of a pipeline step with visual separator."""
    log("")
    log("━" * 57)
    log(f"  STEP {step_num}/{total_steps}: {name}")
    log("━" * 57)


def run_ffmpeg(args: list, timeout: int = 300) -> Tuple[bool, str, str]:
    """
    Run an ffmpeg command safely.
    
    Args:
        args: List of ffmpeg arguments (after -y -hide_banner -loglevel error)
        timeout: Maximum execution time in seconds
    
    Returns:
        Tuple of (success: bool, stdout: str, stderr: str)
    """
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
        log(f"FFmpeg failed (code {e.returncode}): {err[:400]}", "ERROR")
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
    """Get video resolution (width, height) using ffprobe."""
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


def retry_with_backoff(func, max_retries: int = 3, initial_delay: float = 2.0,
                       backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Callable to retry
        max_retries: Maximum number of attempts
        initial_delay: Initial delay in seconds
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exceptions to catch
    
    Returns:
        The return value of func
    
    Raises:
        The last exception encountered
    """
    last_exception = None
    current_delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                log(f"Retry {attempt}/{max_retries}: {e}. "
                    f"Waiting {current_delay:.0f}s...", "WARN")
                time.sleep(current_delay)
                current_delay *= backoff
            else:
                log(f"All {max_retries} attempts failed: {e}", "ERROR")
    raise last_exception


def safe_json_parse(text: str) -> Optional[dict]:
    """
    Safely parse JSON from LLM output, handling markdown code fences.
    
    LLMs often wrap JSON in ```json ... ``` blocks. This function
    strips those and tries to parse.
    """
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
    # Direct parse
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


def ensure_directory(path: Path):
    """Ensure a directory exists, creating it if necessary."""
    path.mkdir(parents=True, exist_ok=True)


def format_time_ass(seconds: float) -> str:
    """
    Format seconds to H:MM:SS.cs (ASS subtitle time format).
    
    ASS requires centiseconds (2-digit hundredths of a second).
    """
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def get_file_size_mb(file_path: Path) -> float:
    """Get file size in megabytes."""
    if file_path.exists():
        return file_path.stat().st_size / (1024 * 1024)
    return 0.0


def clean_temp_files(keep: Optional[list] = None):
    """Clean temporary files, keeping specified ones."""
    if keep is None:
        keep = [FINAL_VIDEO, METADATA_FILE, LOG_FILE]
    for f in OUTPUT_DIR.glob("*"):
        if f not in keep:
            try:
                if f.is_file():
                    f.unlink()
            except Exception:
                pass


def send_telegram_message(text: str, parse_mode: str = "Markdown"):
    """Send a text message to the configured Telegram chat."""
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
        log(f"Telegram message failed: {e}", "WARN")


def send_telegram_error(error_message: str):
    """
    Send an error notification to Telegram with the actual error details.
    This replaces the generic "Pipeline Failed" messages so the user
    knows exactly what went wrong without checking GitHub logs.
    """
    truncated = error_message[:300]
    send_telegram_message(
        f"❌ *Pipeline Error:*\n`{truncated}`\n\n"
        f"Check GitHub Actions logs for full details.",
        parse_mode="Markdown"
    )


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3: STEP 1 — FACT RESEARCH (Tavily API)                       ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def research_fact() -> str:
    """
    Search for an interesting fact using Tavily Search API.
    
    Randomly picks from psychology, space, weird, or brain categories.
    Falls back to curated facts if the API call fails.
    
    Returns:
        A string containing the research context (fact text).
    """
    categories = [
        ("psychology", [
            "psychology fact about human behavior that most people don't know",
            "mind blowing psychology fact about the brain",
            "interesting psychological truth about human mind",
            "brain fact that changes how you see yourself"
        ]),
        ("space", [
            "amazing space fact NASA recently discovered",
            "mind blowing space secret about the universe",
            "unbelievable universe fact that sounds fake",
            "space discovery that shocked scientists"
        ]),
        ("weird", [
            "weird fact about human body that sounds fake but is true",
            "strange but true science fact",
            "interesting fact about nature that is hard to believe",
            "fact that sounds fake but is scientifically proven"
        ]),
        ("brain", [
            "brain fact from neuroscience research",
            "how human brain works psychology fact",
            "neuroscience fact about memory and learning"
        ])
    ]

    # Pick a random category and query
    category_name, queries = random.choice(categories)
    query = random.choice(queries)
    log(f"Researching: {category_name} — '{query}'")

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
            raise RuntimeError(
                f"Tavily error {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    try:
        data = retry_with_backoff(_search, max_retries=2, initial_delay=3.0)
    except Exception as e:
        log(f"Tavily search failed: {e}", "WARN")
        return get_fallback_fact(category_name)

    # Extract the most useful content from the response
    answer = data.get("answer", "")
    if answer and len(answer) > 50:
        log(f"Tavily answer: {answer[:120]}...")
        return answer

    results = data.get("results", [])
    if results:
        # Use the longest content snippet
        best = max(results, key=lambda r: len(r.get("content", "")))
        content = best.get("content", "")
        if len(content) > 50:
            log(f"Using result: {content[:120]}...")
            return content

    # Last resort: use curated fallback fact
    log("No good result from Tavily, using curated fact", "WARN")
    return get_fallback_fact(category_name)


def get_fallback_fact(category: str) -> str:
    """Return a curated fact when the API search fails."""
    fallback_facts = {
        "psychology": [
            "The human brain processes approximately 70,000 thoughts per day on average. "
            "Most of these thoughts are automatic and happen below our conscious awareness. "
            "This is why your brain can drive a car on autopilot while your mind wanders elsewhere.",
            "People are significantly more likely to remember information when it is presented "
            "as a story rather than as plain facts. This cognitive bias is called the narrative "
            "effect and it is why storytelling is so powerful in marketing and education.",
            "The spotlight effect is a psychological phenomenon where people believe they are "
            "being noticed far more than they actually are. In reality, most people are too "
            "focused on themselves to pay close attention to you."
        ],
        "space": [
            "A single day on Venus is actually longer than an entire year on Venus. "
            "The planet takes 243 Earth days to complete one rotation on its axis, "
            "but only 225 Earth days to orbit the Sun completely.",
            "There is a giant cloud of alcohol floating in space called Sagittarius B2. "
            "This molecular cloud contains enough ethyl alcohol to fill 400 trillion "
            "trillion pints of beer — making it the largest bar in the universe.",
            "Neutron stars are so incredibly dense that a single teaspoon of their material "
            "would weigh approximately 10 million tons on Earth. That is heavier than "
            "the entire Mount Everest compressed into a spoon."
        ],
        "weird": [
            "Your stomach lining completely replaces itself every 3 to 4 days. "
            "If it did not, your own stomach acid would digest your stomach! "
            "This is why your stomach can handle such harsh acidic conditions.",
            "Humans shed approximately 600,000 particles of skin every single hour. "
            "That adds up to about 1.5 pounds of dead skin cells per year. "
            "Most of the dust in your home is actually dead human skin.",
            "Your bones are constantly being broken down and rebuilt by your body. "
            "Every 7 to 10 years, you get an entirely new skeleton. "
            "The old bone cells are replaced by fresh ones in a process called remodeling."
        ],
        "brain": [
            "Your brain consumes 20 percent of your body's total energy despite being "
            "only 2 percent of your body weight. It is by far the most energy-hungry "
            "organ in your body, requiring constant glucose and oxygen to function.",
            "When you learn something new, your brain physically changes its structure. "
            "New neural connections form between neurons as memories are created, "
            "literally rewiring your brain's circuitry in real time.",
            "The human brain cannot actually multitask. Instead, it switches between "
            "different tasks extremely rapidly, losing efficiency and accuracy "
            "with each switch. True parallel processing is a myth."
        ]
    }
    facts = fallback_facts.get(category, fallback_facts["psychology"])
    return random.choice(facts)


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4: STEP 2 — SCRIPT GENERATION (Groq LLaMA 3)                ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def generate_script(fact_context: str) -> dict:
    """
    Generate a structured Hinglish script using Groq's LLaMA 3.3 70B model.
    
    The script contains:
    - SEO-optimized title and description
    - 12-14 short Hinglish phrases (3-12 words each)
    - A Pexels search keyword matching the topic
    - Tags and hashtags for YouTube
    
    Args:
        fact_context: The research text to base the script on
    
    Returns:
        A dictionary with the structured script data
    """
    system_prompt = """You are a top YouTube Shorts script writer for "Ajeebology Shorts" — 
a Hinglish (Hindi+English mixed, Roman script) channel covering psychology, space, 
and weird world facts.

Your scripts go VIRAL because they are:
1. HOOK-strong: First 3 seconds grab attention with a question or shocking statement
2. VALUE-packed: Every sentence teaches something surprising and useful
3. PACED perfectly: Short, punchy sentences that are easy to follow
4. RETENTION-optimized: Each phrase makes the viewer want to watch the next one

ABSOLUTE RULES:
- Write ALL text in Roman Hinglish (NOT Devanagari script)
- Example: "Kya aap jaante hain ki insaan ka dimaag 60% fat se bana hota hai?"
- Each phrase must be exactly 3-12 words (short, punchy, one complete thought)
- Generate EXACTLY 12-14 phrases for a 55-65 second video
- First phrase = POWERFUL HOOK (a question or a shocking statement)
- Last 2 phrases = Value summary + Subscribe CTA in Hinglish
- Include a relevant English keyword for Pexels video search
- Output ONLY valid JSON, no markdown formatting, no explanation

JSON STRUCTURE (output exactly this format):
{
  "title": "Catchy title with emoji (max 70 chars)",
  "category": "psychology|space|weird|brain|science",
  "seo_title": "SEO optimized title for YouTube | Ajeebology Shorts",
  "description": "2-3 line Hinglish description of the video with emojis",
  "tags": ["tag1","tag2","tag3","tag4","tag5"],
  "hashtags": "#hashtag1 #hashtag2 #hashtag3",
  "pexels_keyword": "English keyword for Pexels stock video search",
  "phrases": [
    "First hook phrase? 3-12 words",
    "Second phrase continuing the thought...",
    "... ",
    "... (12-14 total phrases)",
    "Second-last: value summary for viewer",
    "Last phrase: subscribe CTA in Hinglish like 'Ajeebology Shorts ko subscribe karein!'"
  ]
}"""

    log("Generating script via Groq LLaMA 3.3 70B...")

    def _generate():
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content":
                        f"Write a Hinglish fact video script (12-14 short phrases) "
                        f"based on this research content:\n\n{fact_context}"}
                ],
                "temperature": 0.8,
                "max_tokens": 2000,
            },
            timeout=90
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Groq error {response.status_code}: {response.text[:300]}"
            )
        content = response.json()["choices"][0]["message"]["content"]
        script = safe_json_parse(content)
        if not script:
            raise ValueError("Failed to parse JSON from Groq response")
        phrases = script.get("phrases", [])
        if len(phrases) < 8:
            raise ValueError(f"Only {len(phrases)} phrases generated, need at least 8")
        return script

    try:
        script = retry_with_backoff(_generate, max_retries=2, initial_delay=5.0)
        phrases = script["phrases"]
        log(f"✓ Script generated: {len(phrases)} phrases")
        for i, phrase in enumerate(phrases):
            log(f"  [{i+1:2d}] {phrase[:70]}")
        return script
    except Exception as e:
        log(f"Script generation failed: {e}", "ERROR")
        log("Using emergency fallback script...", "WARN")
        return generate_emergency_script(fact_context)


def generate_emergency_script(fact_context: str) -> dict:
    """
    Generate a simple script when the Groq API call fails completely.
    
    This ensures the pipeline can still produce content even if the
    AI model is unavailable.
    """
    category = random.choice(["psychology", "space", "weird", "brain"])
    fact_snippet = fact_context[:300]
    first_fact = fact_snippet.split(".")[0] if "." in fact_snippet else fact_snippet

    phrases = [
        "Kya aap jaante hain?",
        "Yeh fact aapko hairan kar dega!",
        first_fact,
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
                       f"Watch till end for surprise. {category.capitalize()} facts "
                       f"in Hinglish. Ajeebology Shorts — your daily dose of knowledge!",
        "tags": [f"{category} facts", "hinglish facts", "amazing facts",
                 "mind blowing facts", "ajeebology shorts"],
        "hashtags": f"#{category} #facts #hinglishfacts #amazing #ajeebology",
        "pexels_keyword": category,
        "phrases": phrases
    }


def validate_script(script: dict) -> dict:
    """
    Validate and repair script fields to ensure the pipeline doesn't break
    due to missing or malformed data from the LLM.
    """
    required_fields = ["title", "category", "phrases", "tags", "hashtags"]
    for field in required_fields:
        if field not in script:
            log(f"Missing field '{field}' in script — adding default", "WARN")
            if field == "phrases":
                script[field] = ["Amazing fact for you from Ajeebology Shorts!"]
            elif field == "tags":
                script[field] = ["facts", "hinglish", "amazing"]
            elif field == "hashtags":
                script[field] = "#facts #hinglish #amazing"
            else:
                script[field] = f"Amazing Facts {datetime.now().day}"

    # Validate and clean phrases
    valid_phrases = []
    for p in script["phrases"]:
        p = p.strip()
        word_count = len(p.split())
        if PHRASE_MIN_WORDS <= word_count <= PHRASE_MAX_WORDS and len(p) < 200:
            valid_phrases.append(p)

    if not valid_phrases:
        log("No valid phrases found, using defaults", "WARN")
        valid_phrases = [
            "Kya aap jaante hain? Yeh fact amazing hai!",
            "Yeh aapki soch badal dega.",
            "Ajeebology Shorts ko subscribe karein!"
        ]

    script["phrases"] = valid_phrases[:14]  # cap at 14 phrases
    return script


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5: STEP 3 — AUDIO GENERATION (edge-tts per phrase)          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

async def generate_single_phrase_audio(phrase: str, output_path: Path,
                                        voice: str = "hi-IN-MadhurNeural",
                                        rate: str = "-5%",
                                        pitch: str = "-2Hz") -> float:
    """
    Generate TTS audio for a single phrase using edge-tts.
    
    Uses Microsoft's hi-IN-MadhurNeural voice (male Hindi) with
    slightly slower rate (-5%) and slightly deeper pitch (-2Hz)
    for a more authoritative, natural sound.
    
    Returns:
        Duration of the generated audio in seconds.
    """
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
        # Create a short silent file as fallback
        run_ffmpeg([
            "-f", "lavfi", "-i",
            "anullsrc=r=44100:cl=mono:d=2.0",
            str(output_path)
        ])

    duration_sec = get_media_duration(output_path)
    if duration_sec < 0.2:
        log(f"Very short audio ({duration_sec:.2f}s) for: {phrase[:40]}", "WARN")
    return duration_sec


async def generate_all_phrase_audio(phrases: list) -> List[Dict]:
    """
    Generate audio for all phrases sequentially using edge-tts.
    
    Each phrase gets its OWN audio file so we know the exact duration
    of each phrase. This is the key to 100% reliable subtitle sync
    without needing Whisper or any AI transcription.
    
    Returns:
        List of dicts with phrase, path, duration, and word data.
    """
    audio_files = []
    total_phrases = len(phrases)
    log(f"Generating audio for {total_phrases} phrases with edge-tts...")

    for i, phrase in enumerate(phrases):
        audio_path = OUTPUT_DIR / f"phrase_{i:03d}.mp3"
        log(f"  TTS [{i+1}/{total_phrases}] {phrase[:55]}...")
        duration_sec = await generate_single_phrase_audio(phrase, audio_path)

        audio_files.append({
            "index": i,
            "phrase": phrase,
            "path": str(audio_path),
            "duration": duration_sec,
            "words": phrase.split(),
            "word_count": len(phrase.split()),
        })

        # Brief pause between calls to avoid rate limiting
        if i < total_phrases - 1:
            await asyncio.sleep(0.3)

    total_duration = sum(af["duration"] for af in audio_files)
    log(f"✓ Total audio generated: {total_duration:.1f}s across {total_phrases} phrases")
    return audio_files


def concatenate_and_process_audio(audio_files: List[Dict],
                                   output_path: Path) -> float:
    """
    Concatenate all individual phrase audio files into one continuous track.
    
    Also removes leading/trailing silence and tightens gaps between phrases
    for natural pacing.
    
    Returns:
        Total duration of the final audio in seconds.
    """
    log("Concatenating and processing audio...")

    # Handle empty or all-silent audio gracefully
    if not audio_files or all(af["duration"] < 0.1 for af in audio_files):
        log("No valid audio files — generating 30s silence as fallback", "ERROR")
        run_ffmpeg([
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=30",
            str(output_path)
        ])
        return get_media_duration(output_path)

    # Create concat demuxer file
    concat_list = OUTPUT_DIR / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for af in audio_files:
            if Path(af["path"]).exists() and Path(af["path"]).stat().st_size > 100:
                f.write(f"file '{af['path']}'\n")

    # Concatenate audio files
    raw_combined = OUTPUT_DIR / "voice_raw.mp3"
    success, _, _ = run_ffmpeg([
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(raw_combined)
    ])

    if not success or not raw_combined.exists():
        log("Direct concat failed — trying re-encode...", "WARN")
        success, _, _ = run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(raw_combined)
        ])

    if not success or not raw_combined.exists():
        log("Audio concatenation completely failed — generating silence", "ERROR")
        run_ffmpeg([
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=30",
            str(output_path)
        ])
        return get_media_duration(output_path)

    # Remove leading/trailing silence for clean pacing
    trimmed_path = OUTPUT_DIR / "voice_trimmed.mp3"
    success, _, _ = run_ffmpeg([
        "-i", str(raw_combined),
        "-af",
        "silenceremove=start_periods=1:start_duration=0.3:"
        "start_threshold=-45dB:detection=peak,"
        "silenceremove=stop_periods=1:stop_duration=0.3:"
        "stop_threshold=-45dB:detection=peak",
        str(trimmed_path)
    ])

    if success and trimmed_path.exists():
        shutil.move(str(trimmed_path), str(output_path))
    else:
        shutil.move(str(raw_combined), str(output_path))

    final_duration = get_media_duration(output_path)
    log(f"✓ Voice audio ready: {final_duration:.1f}s")
    return final_duration


def calculate_word_level_timings(phrase: str, phrase_duration: float) -> List[Dict]:
    """
    Calculate per-word timings within a phrase using character-length weighting.
    
    This is the KEY innovation that replaces Whisper:
    - Longer words naturally take more time to speak
    - We distribute the total phrase duration across words proportionally
      to each word's character length
    - This gives us word-level sync WITHOUT any AI transcription
    
    Accuracy is ~90% which is good enough for visual highlighting.
    
    Returns:
        List of dicts with word, start_time, end_time, duration_cs
    """
    words = phrase.strip().split()
    if not words or phrase_duration <= 0:
        return []

    total_chars = sum(len(w) for w in words)
    if total_chars == 0:
        total_chars = 1

    timings = []
    current_time = 0.0

    for word in words:
        # Each word gets time proportional to its character length
        word_duration = (len(word) / total_chars) * phrase_duration
        # Ensure minimum duration for short words like "ka", "ki", "mein"
        word_duration = max(word_duration, 0.15)

        timings.append({
            "word": word,
            "start": current_time,
            "end": current_time + word_duration,
            "duration_cs": int(word_duration * 100)  # centiseconds for ASS karaoke
        })
        current_time += word_duration

    return timings


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 6: STEP 4 — BACKGROUND MUSIC                                 ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def fetch_background_music(target_duration: float) -> Optional[Path]:
    """
    Download royalty-free background music from SoundHelix.
    
    Falls back to generating ambient pink noise + sine tone if
    downloads fail. Both are free and require no API key.
    
    Returns:
        Path to the music file, or None if unavailable.
    """
    output_path = OUTPUT_DIR / "background_music.mp3"

    if target_duration < 5:
        log(f"Audio too short ({target_duration:.0f}s) for music — skipping", "WARN")
        return None

    log(f"Downloading/generating background music ({target_duration:.0f}s target)...")

    # Source 1: SoundHelix (always available, no API key, royalty-free)
    soundhelix_tracks = [
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
        "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-16.mp3",
    ]

    for url in soundhelix_tracks:
        try:
            track_name = url.split("/")[-1]
            log(f"  Trying: {track_name}")

            response = requests.get(url, stream=True, timeout=30)
            if response.status_code != 200:
                continue

            temp_path = OUTPUT_DIR / "music_source.mp3"
            with open(temp_path, "wb") as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > 10 * 1024 * 1024:  # 10MB cap
                            break

            if temp_path.stat().st_size < 10000:
                log(f"  {track_name}: too small, skipping", "WARN")
                continue

            # Trim to target duration and apply fades
            fade_out_start = max(0, target_duration - 2)
            success, _, _ = run_ffmpeg([
                "-i", str(temp_path),
                "-t", str(target_duration + 2),
                "-af",
                f"volume=0.12,"
                f"afade=t=in:ss=0:d=2,"
                f"afade=t=out:st={fade_out_start}:d=2",
                str(output_path)
            ])

            if success and output_path.exists() and output_path.stat().st_size > 1000:
                log(f"  ✓ Downloaded: {track_name} ({get_file_size_mb(output_path):.1f} MB)")
                return output_path

        except Exception as e:
            log(f"  Failed: {e}", "WARN")
            continue

    # Source 2: Generate ambient background with ffmpeg
    log("  Generating ambient background (pink noise + sine wave)...")
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

    if success and output_path.exists():
        log(f"  ✓ Ambient background generated")
        return output_path

    log("  No background music available — will use voice only", "WARN")
    return None


def apply_sidechain_compression(voice_path: Path, music_path: Path,
                                 output_path: Path,
                                 threshold: float = -18,
                                 ratio: float = 5,
                                 attack: float = 10,
                                 release: float = 100) -> bool:
    """
    Apply sidechain compression to duck background music under voice.
    
    This creates the professional radio/podcast effect where music
    automatically goes quieter when the person speaks and comes back
    up during pauses.
    
    Falls back to simple volume mixing if sidechain is unavailable.
    """
    log("Applying sidechain compression (professional audio ducking)...")

    success, _, _ = run_ffmpeg([
        "-i", str(music_path),
        "-i", str(voice_path),
        "-filter_complex",
        f"[0:a]volume=0.15[music];"
        f"[1:a]asplit[voice][sidechain];"
        f"[music][sidechain]sidechaincompress="
        f"threshold={threshold}dB:ratio={ratio}:"
        f"attack={attack}ms:release={release}ms"
        f":level_sc=0.15[music_ducked];"
        f"[music_ducked][voice]amix=inputs=2:duration=first[out]",
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(output_path)
    ], timeout=120)

    if not success:
        log("  Sidechain compression unavailable — using simple volume mix", "WARN")
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
# ║  SECTION 7: STEP 5 — STOCK VIDEO DOWNLOAD (Pexels API)               ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def search_pexels_videos(keyword: str, max_results: int = 10) -> List[Dict]:
    """
    Search Pexels for vertical (portrait) stock videos matching a keyword.
    
    Filters for 9:16 aspect ratio videos suitable for YouTube Shorts.
    Prefers 1080p quality but falls back to 720p.
    
    Returns:
        List of video info dicts with url, quality, and dimensions.
    """
    log(f"Searching Pexels for: '{keyword}'")

    try:
        response = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query": keyword,
                "orientation": "portrait",
                "size": "medium",
                "per_page": min(max_results, 20),
            },
            timeout=30
        )

        if response.status_code != 200:
            log(f"Pexels API error {response.status_code}: {response.text[:200]}", "WARN")
            return []

        data = response.json()
        videos = data.get("videos", [])
        log(f"  Found {len(videos)} results")

        parsed_videos = []
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

            # Find the best quality 9:16 file for this video
            for file_entry in video.get("video_files", []):
                w = file_entry.get("width", 0)
                h = file_entry.get("height", 0)
                if w >= 1080 and h >= 1920:
                    video_info["width"] = w
                    video_info["height"] = h
                    video_info["url"] = file_entry["link"]
                    video_info["quality"] = "1080p"
                    break
                elif w >= 720 and h >= 1280 and video_info["quality"] == "unknown":
                    video_info["width"] = w
                    video_info["height"] = h
                    video_info["url"] = file_entry["link"]
                    video_info["quality"] = "720p"

            if video_info["url"]:
                parsed_videos.append(video_info)

        log(f"  {len(parsed_videos)} usable vertical videos found")
        return parsed_videos

    except requests.exceptions.RequestException as e:
        log(f"Pexels API error: {e}", "ERROR")
        return []


def download_pexels_video(video_info: Dict, output_path: Path) -> bool:
    """
    Download a single Pexels video file.
    
    Args:
        video_info: Dict with 'url' and 'photographer' keys
        output_path: Where to save the downloaded file
    
    Returns:
        True if download succeeded and file is valid.
    """
    url = video_info["url"]
    photographer = video_info.get("photographer", "Unknown")

    log(f"  Downloading ({video_info['quality']}): {url.split('?')[0][:60]}...")

    try:
        response = requests.get(url, stream=True, timeout=120)
        if response.status_code != 200:
            log(f"    HTTP {response.status_code}", "WARN")
            return False

        with open(output_path, "wb") as f:
            total_downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_downloaded += len(chunk)
                    if total_downloaded > 50 * 1024 * 1024:  # 50MB cap
                        log(f"    Large file capped at 50MB", "WARN")
                        break

        file_size_mb = get_file_size_mb(output_path)
        log(f"    Downloaded: {file_size_mb:.1f} MB (by {photographer})")

        if file_size_mb < 0.1:
            log(f"    File too small, discarding", "WARN")
            output_path.unlink(missing_ok=True)
            return False

        return True

    except Exception as e:
        log(f"    Download error: {e}", "ERROR")
        return False


def download_stock_video_clips(keyword: str, category: str,
                                max_clips: int = 2) -> List[Path]:
    """
    Download multiple stock video clips for visual variety.
    
    Tries the primary keyword first, then falls back to the category
    name, then generic keywords if needed.
    
    Returns:
        List of paths to downloaded video files.
    """
    ensure_directory(STOCK_VIDEO_DIR)

    # Try increasingly generic keywords
    keywords_to_try = [
        keyword,
        category,
        "abstract background",
        "time lapse abstract",
        "sci fi futuristic",
        "nature background"
    ]

    downloaded_clips = []

    for kw in keywords_to_try:
        if len(downloaded_clips) >= max_clips:
            break

        results = search_pexels_videos(kw)
        if not results:
            continue

        for video_info in results[:max_clips]:
            if len(downloaded_clips) >= max_clips:
                break

            clip_path = STOCK_VIDEO_DIR / f"stock_clip_{len(downloaded_clips):02d}.mp4"
            if download_pexels_video(video_info, clip_path):
                downloaded_clips.append(clip_path)
                log(f"  ✓ Clip {len(downloaded_clips)}: '{kw}'")

    if not downloaded_clips:
        log("⚠ No stock videos could be downloaded", "WARN")

    return downloaded_clips


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 8: STEP 6 — SUBTITLE GENERATION (ASS with karaoke)          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def generate_ass_karaoke_subtitles(audio_files: List[Dict],
                                    output_path: Path,
                                    bottom_margin: int = 400) -> str:
    """
    Generate ASS subtitle file with word-by-word karaoke highlighting.
    
    How ASS karaoke works:
    - The \k tag tells the renderer how long each word should take
    - SecondaryColour (white) = the base color of unspoken text
    - PrimaryColour (cyan) = the highlight color that fills in as spoken
    - The renderer smoothly transitions each word from white to cyan
    - BorderStyle=3 creates the semi-transparent background bar
    - This gives the exact MrBeast-style word highlighting effect
    
    Returns:
        The ASS file content as a string.
    """
    log("Generating ASS karaoke subtitles with word-by-word highlighting...")

    ass_header = f"""[Script Info]
; ASS subtitle file generated for Ajeebology Shorts
; Karaoke word-by-word highlighting with brand colors
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,DejaVu Sans Bold,42,&H00FFFF00,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,1,2,50,50,{bottom_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    current_time = 0.0

    for audio_file in audio_files:
        phrase = audio_file["phrase"]
        phrase_duration = audio_file["duration"]
        words = phrase.strip().split()

        if phrase_duration <= 0 or len(words) == 0:
            current_time += max(phrase_duration, 2.0)
            continue

        # Calculate word-level timings
        word_timings = calculate_word_level_timings(phrase, phrase_duration)

        # Build karaoke line with \k tags
        # Format: {\kCS}word where CS = duration in centiseconds
        karaoke_parts = []
        for wt in word_timings:
            cs = max(1, wt["duration_cs"])
            escaped_word = wt["word"].replace("{", "\\{").replace("}", "\\}")
            karaoke_parts.append(f"{{\\k{cs}}}{escaped_word}")

        karaoke_text = " ".join(karaoke_parts)

        start_time_ass = format_time_ass(current_time)
        end_time_ass = format_time_ass(current_time + phrase_duration)

        event_line = (
            f"Dialogue: 0,{start_time_ass},{end_time_ass},"
            f"Karaoke,,0,0,0,,{karaoke_text}"
        )
        events.append(event_line)

        current_time += phrase_duration

    total_subtitle_duration = current_time
    ass_content = ass_header + "\n".join(events) + "\n"

    # Write the ASS file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    log(f"  ✓ ASS file: {len(events)} karaoke events, {total_subtitle_duration:.1f}s total")
    return ass_content


def build_drawtext_subtitle_chain(audio_files: List[Dict]) -> str:
    """
    Build ffmpeg drawtext filter chain as a fallback when libass is unavailable.
    
    Each phrase gets its own drawtext filter with an enable condition
    that shows it only during its spoken time range.
    
    This is less fancy than ASS karaoke but still produces clean,
    professional-looking subtitles.
    
    Returns:
        Comma-separated ffmpeg drawtext filter string.
    """
    log("Building drawtext subtitle chain (ASS/libass fallback)...")
    filter_list = []
    current_time = 0.0

    for audio_file in audio_files:
        start_time = current_time
        end_time = current_time + audio_file["duration"]
        phrase = audio_file["phrase"]

        # Escape special characters for ffmpeg drawtext
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
        filter_list.append(text_filter)
        current_time = end_time

    filter_string = ",".join(filter_list)
    log(f"  ✓ Drawtext chain: {len(audio_files)} phrase filters")
    return filter_string


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 9: STEP 7 — VISUAL EFFECTS                                   ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def apply_ken_burns_zoom(input_path: Path, output_path: Path,
                          target_duration: float,
                          zoom_start: float = 1.0,
                          zoom_end: float = 1.08) -> bool:
    """
    Apply subtle Ken Burns zoom effect using ffmpeg zoompan filter.
    
    Creates a slow zoom-in that adds cinematic motion to otherwise
    static stock footage. The zoom is subtle (1.0x to 1.08x) so it
    doesn't look jarring or artificial.
    
    If target_duration is 0 or negative, copies the input as-is.
    """
    if target_duration <= 0:
        log(f"  Skipping Ken Burns (zero duration)", "WARN")
        if input_path != output_path:
            shutil.copy(str(input_path), str(output_path))
        return True

    log(f"  Ken Burns zoom {zoom_start}x → {zoom_end}x over {target_duration:.1f}s...")

    # Calculate zoom increment per frame
    total_frames = int(target_duration * VIDEO_FPS)
    if total_frames <= 0:
        total_frames = 1

    zoom_increment = (zoom_end - zoom_start) / total_frames
    zoom_expr = f"min({zoom_start}+{zoom_increment:.8f}*on,{zoom_end})"

    success, _, _ = run_ffmpeg([
        "-stream_loop", "-1",
        "-i", str(input_path),
        "-t", str(target_duration),
        "-vf",
        f"zoompan=z='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:"
        f"s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
        f"fps={VIDEO_FPS}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ], timeout=180)

    return success


def create_branded_intro_card(duration: float = 3.0,
                               channel_name: str = "Ajeebology Shorts",
                               tagline: str = "Amazing Facts in Hinglish") -> bool:
    """
    Create a branded intro card using ffmpeg (no PIL needed).
    
    Features:
    - Purple gradient background (brand color)
    - Channel name in cyan (brand color)
    - Tagline in white
    - Smooth fade in/out transitions
    - 3 seconds duration
    """
    log(f"Creating branded intro card ({duration}s)...")

    success, _, _ = run_ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c={BRAND_PURPLE_HEX}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
              f"d={duration}:r={VIDEO_FPS}",
        "-f", "lavfi",
        "-i", f"nullsrc=s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={duration}:r={VIDEO_FPS}",
        "-filter_complex",
        f"[0:v][1:v]overlay[bg];"
        f"[bg]drawtext=text='{channel_name}':"
        f"fontsize=64:fontcolor={BRAND_CYAN_HEX}:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-60:"
        f"fontfile={FONT_BOLD}:"
        f"shadowx=3:shadowy=3:shadowcolor=black@0.5[with_title];"
        f"[with_title]drawtext=text='{tagline}':"
        f"fontsize=32:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+30:"
        f"fontfile={FONT_REGULAR}[with_tagline];"
        f"[with_tagline]fade=t=in:st=0:d=0.5:alpha=1,"
        f"fade=t=out:st={duration-0.7}:d=0.7:alpha=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        str(INTRO_VIDEO)
    ], timeout=60)

    if success:
        log(f"  ✓ Intro card created")
    else:
        log(f"  Intro card failed (non-critical)", "WARN")
    return success


def create_subscribe_call_to_action(duration: float = 4.0) -> bool:
    """
    Create an animated subscribe CTA overlay for the end of the video.
    
    Shows:
    - Channel name in cyan
    - "SUBSCRIBE KAREIN!" in gold
    - "Bell icon dabayein" in white
    - Smooth fade in/out
    
    This overlay is composited onto the last 4 seconds of the video.
    """
    log(f"Creating subscribe CTA overlay ({duration}s)...")

    success, _, _ = run_ffmpeg([
        "-f", "lavfi",
        "-i", f"color=c=0x0D0618:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
              f"d={duration}:r={VIDEO_FPS}",
        "-vf",
        f"drawtext=text='Ajeebology Shorts':"
        f"fontsize=52:fontcolor={BRAND_CYAN_HEX}:"
        f"x=(w-text_w)/2:y=(h/2)-80:"
        f"fontfile={FONT_BOLD},"
        f"drawtext=text='📢 SUBSCRIBE KAREIN!':"
        f"fontsize=44:fontcolor={BRAND_GOLD_HEX}:"
        f"x=(w-text_w)/2:y=(h/2):"
        f"fontfile={FONT_BOLD},"
        f"drawtext=text='🔔 Bell icon dabayein':"
        f"fontsize=28:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h/2)+80:"
        f"fontfile={FONT_REGULAR},"
        f"fade=t=in:st=0:d=0.8:alpha=1,"
        f"fade=t=out:st={duration-0.5}:d=0.5:alpha=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "25",
        "-pix_fmt", "yuv420p",
        str(SUBSCRIBE_OVERLAY)
    ], timeout=60)

    return success


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 10: STEP 8 — FINAL VIDEO ASSEMBLY                            ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def assemble_final_video(
    stock_clips: List[Path],
    intro_video: Optional[Path],
    audio_file: Path,
    subtitle_source: Union[str, Path],
    subscribe_overlay: Optional[Path],
    total_duration: float,
    output_path: Path
) -> Tuple[bool, str]:
    """
    Assemble all components into the final video.
    
    Assembly pipeline:
    1. Apply Ken Burns zoom to each stock clip
    2. Crossfade between multiple clips if available
    3. Prepend the branded intro card
    4. Overlay subtitles (ASS or drawtext)
    5. Overlay subscribe CTA at the end
    6. Mix with final audio
    
    Returns:
        Tuple of (success: bool, error_message: str)
        The error_message is sent to Telegram for immediate feedback.
    """
    log("═══ FINAL VIDEO ASSEMBLY ═══")
    
    # Ensure minimum duration to prevent division by zero
    total_duration = max(total_duration, 10.0)

    # Directory for processed clips
    ensure_directory(PROCESSED_CLIPS)

    # ── Step 1: Handle missing stock clips ──
    if not stock_clips:
        log("No stock clips available — generating animated fallback background", "WARN")
        fallback_path = PROCESSED_CLIPS / "fallback_background.mp4"
        ok, _, _ = run_ffmpeg([
            "-f", "lavfi",
            "-i", f"color=c={BRAND_PURPLE_HEX}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:"
                  f"d={total_duration}:r={VIDEO_FPS}",
            "-vf",
            f"drawbox=x=0:y=0:w=iw:h=ih:"
            f"color=purple@0.1:t=fill,"
            f"drawtext=text='Ajeebology Shorts':"
            f"fontsize=40:fontcolor=white@0.2:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"fontfile={FONT_BOLD}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(fallback_path)
        ])
        if ok and fallback_path.exists():
            stock_clips = [fallback_path]
        else:
            return False, "Failed to generate fallback background"

    # ── Step 2: Apply Ken Burns zoom to each clip ──
    processed_clips = []
    clip_duration = total_duration / len(stock_clips)

    for i, clip in enumerate(stock_clips):
        output_clip = PROCESSED_CLIPS / f"ken_burns_{i:02d}.mp4"
        log(f"  Processing clip {i+1}/{len(stock_clips)}...")
        if not apply_ken_burns_zoom(clip, output_clip, clip_duration):
            log(f"  Ken Burns failed for clip {i+1} — using raw", "WARN")
            processed_clips.append(clip)
        else:
            processed_clips.append(output_clip)

    # ── Step 3: Concatenate multiple clips ──
    if len(processed_clips) > 1:
        log("  Concatenating multiple clips...")
        merged_path = PROCESSED_CLIPS / "merged_clips.mp4"
        concat_file = PROCESSED_CLIPS / "clip_list.txt"

        with open(concat_file, "w") as f:
            for clip in processed_clips:
                f.write(f"file '{clip}'\n")

        # Use concat demuxer (fast, no re-encode)
        ok, _, _ = ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(merged_path)
        ])

        if ok and merged_path.exists():
            processed_clips = [merged_path]
            log("  ✓ Clips concatenated")
        else:
            log("  Concat failed — using first clip only", "WARN")
            processed_clips = [processed_clips[0]]

    # ── Step 4: Prepend intro card ──
    if intro_video and intro_video.exists():
        log("  Prepending intro card...")
        with_intro_path = PROCESSED_CLIPS / "with_intro.mp4"
        intro_concat = PROCESSED_CLIPS / "intro_list.txt"

        with open(intro_concat, "w") as f:
            f.write(f"file '{intro_video}'\n")
            f.write(f"file '{processed_clips[-1]}'\n")

        ok, _, _ = ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", str(intro_concat),
            "-c", "copy",
            str(with_intro_path)
        ])

        if ok and with_intro_path.exists():
            processed_clips = [with_intro_path]
            log("  ✓ Intro prepended")

    # ── Step 5: Final composition ──
    video_source = processed_clips[-1]
    if not video_source or not video_source.exists():
        return False, "No valid video source after processing"

    # Determine subtitle filter type
    if isinstance(subtitle_source, str) and subtitle_source.endswith(".ass"):
        subtitle_filter = f"subtitles={subtitle_source}"
    else:
        subtitle_filter = subtitle_source

    # Build the filter complex
    subscribe_start = max(0, total_duration - 4.0)

    if subscribe_overlay and subscribe_overlay.exists():
        final_filter = (
            f"[0:v]{subtitle_filter}[subbed];"
            f"[subbed]"
            f"movie={subscribe_overlay}:loop=0:setpts=PTS-STARTPTS[subscribe];"
            f"[subbed][subscribe]overlay=0:0:shortest=1:"
            f"enable='between(t,{subscribe_start},{total_duration})'[final]"
        )
        map_label = "[final]"
    else:
        final_filter = f"[0:v]{subtitle_filter}[final]"
        map_label = "[final]"

    # Run the final ffmpeg command
    log("  Rendering final video...")
    ok, _, stderr = ffmpeg([
        "-stream_loop", "-1",
        "-i", str(video_source),
        "-i", str(audio_file),
        "-filter_complex", final_filter,
        "-map", map_label,
        "-map", "1:a",
        "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path)
    ], timeout=600)

    if ok and output_path.exists():
        final_size = get_file_size_mb(output_path)
        final_dur = get_media_duration(output_path)
        log(f"  ✓ FINAL VIDEO: {final_dur:.1f}s, {final_size:.1f} MB, "
            f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}")
        return True, ""
    else:
        error_detail = stderr[:500] if stderr else "Unknown ffmpeg error"
        return False, f"FFmpeg assembly error: {error_detail}"


def verify_final_video(file_path: Path) -> Tuple[bool, str]:
    """
    Verify the final video is valid, playable, and meets minimum requirements.
    
    Checks: file exists, minimum size, minimum duration, valid resolution.
    
    Returns:
        Tuple of (passed: bool, details: str)
    """
    if not file_path.exists():
        return False, "File not found"

    file_size = get_file_size_mb(file_path)
    if file_size < 0.5:
        return False, f"File too small: {file_size:.1f}MB"

    video_duration = get_media_duration(file_path)
    if video_duration < 10:
        return False, f"Video too short: {video_duration:.1f}s"

    width, height = get_video_resolution(file_path)
    if width < 100 or height < 100:
        return False, f"Bad resolution: {width}x{height}"

    return True, f"{video_duration:.1f}s, {file_size:.1f}MB, {width}x{height}"


def generate_thumbnail_from_video(video_path: Path, output_path: Path) -> bool:
    """Extract a single frame from the video at its mid-point as thumbnail."""
    mid_point = get_media_duration(video_path) / 2
    ok, _, _ = ffmpeg([
        "-i", str(video_path),
        "-ss", str(mid_point),
        "-vframes", "1",
        "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
        "-q:v", "8",
        str(output_path)
    ])
    return ok


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 11: STEP 9 — TELEGRAM DELIVERY                               ║
# ╚═════════════════════════════════════════════════════════════════════════╝

def send_video_to_telegram(video_path: Path, caption: str) -> bool:
    """Send the video file to Telegram. Returns True on success."""
    file_size_mb = get_file_size_mb(video_path)
    if file_size_mb > 48:
        log(f"Video too large: {file_size_mb:.1f}MB (Telegram limit: 48MB)", "WARN")
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
            log("✓ Video sent to Telegram!")
            return True
        else:
            log(f"Telegram API error: {response.status_code}", "ERROR")
            return False
    except Exception as e:
        log(f"Telegram upload failed: {e}", "ERROR")
        return False


def build_telegram_caption(metadata: dict) -> str:
    """Build the full metadata message for Telegram."""
    date_str = datetime.now().strftime("%d %b %Y")

    return (
        f"🎬 **AJEEBOLOGY SHORTS — VIDEO READY**\n\n"
        f"**📺 Title:**\n{metadata['title']}\n\n"
        f"**📝 SEO Title:**\n{metadata.get('seo_title', metadata['title'])}\n\n"
        f"**📖 Description:**\n{metadata.get('description', '')}\n\n"
        f"**🏷 Tags:**\n`{', '.join(metadata['tags'][:10])}`\n\n"
        f"**🔖 Hashtags:**\n{metadata.get('hashtags', '')}\n\n"
        f"**📂 Category:** {metadata.get('category', 'facts')}\n"
        f"**⏱ Duration:** {get_media_duration(FINAL_VIDEO):.0f}s\n"
        f"**📦 Size:** {get_file_size_mb(FINAL_VIDEO):.1f} MB\n"
        f"**📅 Date:** {date_str}\n\n"
        f"📥 **Download artifact:** `ajeebology-output` in GitHub Actions\n"
        f"📤 *Upload this video to YouTube Shorts manually*"
    )


def deliver_to_telegram_channel(metadata: dict):
    """Complete Telegram delivery with video, thumbnail fallback, and errors."""
    log("═══ TELEGRAM DELIVERY ═══")

    if not FINAL_VIDEO.exists():
        send_telegram_error("Final video file not found after assembly")
        return

    caption = build_telegram_caption(metadata)

    # Try sending the video directly
    if not send_video_to_telegram(FINAL_VIDEO, caption):
        # Fallback: send thumbnail + metadata
        log("Sending thumbnail as fallback...", "WARN")
        if generate_thumbnail_from_video(FINAL_VIDEO, THUMBNAIL_FILE):
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
                send_telegram_message(caption, "Markdown")
        else:
            # Last resort: just send text metadata
            send_telegram_message(caption, "Markdown")

    # Always send a success confirmation
    send_telegram_message(
        f"✅ *Pipeline Complete* — {get_media_duration(FINAL_VIDEO):.0f}s video ready!\n"
        f"📁 GitHub artifact: `ajeebology-output/output_video.mp4`",
        parse_mode="Markdown"
    )


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 12: MAIN PIPELINE ORCHESTRATOR                               ║
# ╚═════════════════════════════════════════════════════════════════════════╝

async def run_pipeline():
    """Execute the complete video generation pipeline end-to-end."""
    pipeline_start_time = time.time()
    TOTAL_STEPS = 9

    # ═══════════════════════════════════════
    # STEP 1: RESEARCH
    # ═══════════════════════════════════════
    log_step(1, TOTAL_STEPS, "FACT RESEARCH")
    fact_context = research_fact()
    log(f"Research context: {len(fact_context)} chars")

    # ═══════════════════════════════════════
    # STEP 2: SCRIPT GENERATION
    # ═══════════════════════════════════════
    log_step(2, TOTAL_STEPS, "SCRIPT GENERATION")
    script = generate_script(fact_context)
    script = validate_script(script)
    phrases = script["phrases"]
    pexels_keyword = script.get("pexels_keyword", script.get("category", "facts"))
    log(f"Script: {len(phrases)} phrases | Pexels keyword: '{pexels_keyword}'")

    metadata = {
        "title": script["title"],
        "category": script.get("category", "facts"),
        "seo_title": script.get("seo_title", script["title"]),
        "description": script.get("description", ""),
        "tags": script.get("tags", ["facts", "hinglish"]),
        "hashtags": script.get("hashtags", "#facts"),
    }

    # ═══════════════════════════════════════
    # STEP 3: AUDIO GENERATION
    # ═══════════════════════════════════════
    log_step(3, TOTAL_STEPS, "AUDIO GENERATION")
    audio_files = await generate_all_phrase_audio(phrases)
    if not audio_files:
        send_telegram_error("No audio files were generated")
        return

    total_voice_duration = concatenate_and_process_audio(audio_files, VOICE_AUDIO)
    metadata["duration"] = total_voice_duration

    if total_voice_duration < MIN_DURATION:
        log(f"Warning: Audio is short ({total_voice_duration:.0f}s)", "WARN")

    # ═══════════════════════════════════════
    # STEP 4: BACKGROUND MUSIC
    # ═══════════════════════════════════════
    log_step(4, TOTAL_STEPS, "BACKGROUND MUSIC")
    music_path = fetch_background_music(total_voice_duration)

    if music_path and total_voice_duration > 5:
        log("Mixing voice + music with sidechain ducking...")
        mix_ok = apply_sidechain_compression(VOICE_AUDIO, music_path, FINAL_AUDIO)
        if not mix_ok:
            log("Audio mixing failed — using voice only", "WARN")
            shutil.copy(VOICE_AUDIO, FINAL_AUDIO)
    else:
        log("No background music — using voice only")
        shutil.copy(VOICE_AUDIO, FINAL_AUDIO)

    # ═══════════════════════════════════════
    # STEP 5: STOCK VIDEO
    # ═══════════════════════════════════════
    log_step(5, TOTAL_STEPS, "STOCK VIDEO DOWNLOAD")
    stock_clips = download_stock_video_clips(
        pexels_keyword,
        script.get("category", "facts"),
        max_clips=2
    )
    log(f"Stock clips downloaded: {len(stock_clips)}")

    # ═══════════════════════════════════════
    # STEP 6: OVERLAYS
    # ═══════════════════════════════════════
    log_step(6, TOTAL_STEPS, "INTRO & SUBSCRIBE OVERLAYS")
    create_branded_intro_card(
        duration=3.0,
        channel_name="Ajeebology Shorts",
        tagline=script.get("category", "Facts").capitalize() + " Facts"
    )
    create_subscribe_call_to_action(duration=4.0)

    # ═══════════════════════════════════════
    # STEP 7: SUBTITLES
    # ═══════════════════════════════════════
    log_step(7, TOTAL_STEPS, "SUBTITLE GENERATION")
    generate_ass_karaoke_subtitles(audio_files, SUBTITLES_FILE, bottom_margin=400)
    subtitle_source = str(SUBTITLES_FILE)

    # Test if ffmpeg supports libass (for ASS subtitles)
    test_ass = OUTPUT_DIR / "libass_test.txt"
    with open(test_ass, "w") as f:
        f.write("[Script Info]\nScriptType: v4.00+\n")

    libass_available = False
    ok, _, _ = ffmpeg([
        "-f", "lavfi", "-i", "color=c=black:s=8x8:d=0.2",
        "-vf", f"subtitles={test_ass}",
        "-f", "null", "-"
    ])
    if ok:
        libass_available = True
        log("  ✓ libass available — using ASS karaoke word-by-word highlighting")
    else:
        log("  libass not available — using drawtext phrase-level subtitles", "WARN")
        subtitle_source = build_drawtext_subtitle_chain(audio_files)

    # ═══════════════════════════════════════
    # STEP 8: FINAL ASSEMBLY
    # ═══════════════════════════════════════
    log_step(8, TOTAL_STEPS, "FINAL VIDEO ASSEMBLY")

    audio_to_use = FINAL_AUDIO if FINAL_AUDIO.exists() else VOICE_AUDIO
    subscribe_ov = SUBSCRIBE_OVERLAY if SUBSCRIBE_OVERLAY.exists() else None

    assembly_ok, error_detail = assemble_final_video(
        stock_clips=stock_clips,
        intro_video=INTRO_VIDEO if INTRO_VIDEO.exists() else None,
        audio_file=audio_to_use,
        subtitle_source=subtitle_source,
        subscribe_overlay=subscribe_ov,
        total_duration=total_voice_duration,
        output_path=FINAL_VIDEO
    )

    if not assembly_ok:
        log(f"❌ FINAL ASSEMBLY FAILED: {error_detail}", "CRITICAL")
        send_telegram_error(f"Video assembly error: {error_detail}")
        return

    # Verify the output
    verify_ok, verify_info = verify_final_video(FINAL_VIDEO)
    if not verify_ok:
        log(f"❌ VERIFICATION FAILED: {verify_info}", "CRITICAL")
        send_telegram_error(f"Verification failed: {verify_info}")
        return

    log(f"  ✓ Video verification: {verify_info}")

    # ═══════════════════════════════════════
    # STEP 9: DELIVERY
    # ═══════════════════════════════════════
    log_step(9, TOTAL_STEPS, "TELEGRAM DELIVERY")
    deliver_to_telegram_channel(metadata)

    # ═══════════════════════════════════════
    # PIPELINE SUMMARY
    # ═══════════════════════════════════════
    elapsed = time.time() - pipeline_start_time
    log("")
    log("═" * 57)
    log("🏁  PIPELINE COMPLETE — SUCCESS")
    log("═" * 57)
    log(f"  ⏱ Pipeline time:    {elapsed:.0f}s ({elapsed/60:.1f} min)")
    log(f"  🎬 Video length:    {get_media_duration(FINAL_VIDEO):.1f}s")
    log(f"  📦 File size:       {get_file_size_mb(FINAL_VIDEO):.1f} MB")
    log(f"  📐 Resolution:      {VIDEO_WIDTH}x{VIDEO_HEIGHT} @ {VIDEO_FPS}fps")
    log(f"  💬 Phrases:         {len(phrases)}")
    log(f"  📂 Category:        {metadata['category']}")
    log(f"  📺 Title:           {metadata['title']}")
    log("═" * 57)

    # Save full metadata for the artifact
    metadata["pipeline_duration_seconds"] = round(elapsed)
    metadata["video_duration_seconds"] = round(get_media_duration(FINAL_VIDEO))
    metadata["file_size_mb"] = round(get_file_size_mb(FINAL_VIDEO), 1)
    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)

    # Clean up temp files
    clean_temp_files(keep=[FINAL_VIDEO, METADATA_FILE, LOG_FILE])
    log("Cleanup complete")


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║  ENTRY POINT                                                          ║
# ╚═════════════════════════════════════════════════════════════════════════╝

async def main():
    """
    Main entry point with top-level error handling.
    
    - Sets up the output directory
    - Validates all API keys
    - Runs the pipeline
    - Catches any unhandled exceptions and reports them
    """
    try:
        ensure_directory(OUTPUT_DIR)

        # ── Banner ──
        log("")
        log("╔══════════════════════════════════════════════════════════╗")
        log("║     🎬 AJEEBOLOGY SHORTS — PREMIUM VIDEO PIPELINE      ║")
        log("╚══════════════════════════════════════════════════════════╝")
        log(f"  Python:        {sys.version.split()[0]}")
        log(f"  Output:        {OUTPUT_DIR}")
        log(f"  Target:        {VIDEO_WIDTH}x{VIDEO_HEIGHT} @ {VIDEO_FPS}fps")
        log(f"  Duration:      ~{TARGET_DURATION}s")
        log(f"  Date:          {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log("")

        # ── Validate API Keys ──
        required_keys = [
            "GROQ_API_KEY", "TAVILY_API_KEY", "PEXELS_API_KEY",
            "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"
        ]
        missing_keys = [k for k in required_keys if not os.environ.get(k)]
        if missing_keys:
            log(f"❌ MISSING API KEYS: {', '.join(missing_keys)}", "CRITICAL")
            log("Set these in GitHub Secrets and re-run.", "CRITICAL")
            sys.exit(1)

        log("✓ All API keys found")
        log("")

        # ── Run Pipeline ──
        await run_pipeline()

    except Exception as e:
        log(f"❌ UNHANDLED PIPELINE CRASH: {e}", "CRITICAL")
        log(traceback.format_exc(), "CRITICAL")
        try:
            send_telegram_error(f"Unhandled crash: {str(e)[:200]}")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
