# ══════════════════════════════════════════════════════
# PART 1 OF 2 — AUDIO PIPELINE
# (Script generation, pause-trimming, speed-up, SFX, ducking)
# This is a standalone-testable module. Part 2 will add the
# visual/video pipeline and the main() that ties both together.
# ══════════════════════════════════════════════════════

import os
import sys
import json
import random
import logging
import requests
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime

from groq import Groq

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("AjeebologyAgent")

GROQ_API_KEY     = os.environ["GROQ_API_KEY"]
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "")
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GITHUB_RUN_ID    = os.environ.get("GITHUB_RUN_ID", "")
GITHUB_REPO      = os.environ.get("GITHUB_REPOSITORY", "")

AUDIO_DIR        = Path("audio_clips")
AUDIO_CLEAN_DIR  = Path("audio_clean")
SFX_DIR          = Path("sfx")
MUSIC_FILE       = "bg_music.mp3"
WHOOSH_FILE      = SFX_DIR / "whoosh.mp3"
DING_FILE        = SFX_DIR / "ding.mp3"

TOPICS = [
    "psychology facts mind blowing",
    "space universe secrets amazing",
    "weird world facts shocking",
    "human brain facts incredible",
    "animal facts surprising",
    "science facts unbelievable",
    "ancient history mysterious facts",
]

FALLBACK_SCRIPTS = [
    {
        "title": "Dimaag Ka Kamaal",
        "category": "Psychology",
        "english_title": "5 Mind Blowing Psychology Facts That Will Shock You",
        "description": "Amazing psychology facts about how your brain really works. Subscribe for daily facts!",
        "tags": "psychology,facts,brain,mindblowing,shorts,viral,hindi,knowledge,science,amazing",
        "segments": [
            {"text": "Ruko zara! Aaj main aapko 5 aise psychology facts batane wala hoon jo aapka dimaag hila denge."},
            {"text": "Number one. Jab aap kisi cheez ke baare mein bahut zyada sochte hain, toh aapka brain usse reality maan leta hai."},
            {"text": "Number two. Aapki memories actually fake ho sakti hain. Brain har baar yaad karte waqt unhe reconstruct karta hai, record nahi karta."},
            {"text": "Number three. REM sleep mein aapka brain jagte waqt se bhi zyada active hota hai. Isliye sapne itne real lagte hain."},
            {"text": "Itna sab jaan kar bhi agar aap hairan nahi hue, toh comment mein batana! Subscribe karna mat bhoolna, daily aise hi facts ke liye."}
        ]
    },
    {
        "title": "Space Ke Raaz",
        "category": "Space",
        "english_title": "5 Space Secrets That Will Blow Your Mind",
        "description": "Incredible space facts about our universe that nobody tells you. Subscribe for daily facts!",
        "tags": "space,universe,facts,stars,mindblowing,shorts,viral,science,amazing,knowledge",
        "segments": [
            {"text": "Ruko zara! Space ke baare mein yeh 5 facts sun kar aap apni soch badal denge."},
            {"text": "Number one. Universe mein itne stars hain ki agar aap ek second mein ek star count karein, toh 3000 saal lagenge."},
            {"text": "Number two. Agar aap light ki speed se chalein, toh hamari galaxy paar karne mein 100,000 saal lagenge."},
            {"text": "Number three. Black hole ke andar time aur space ka koi matlab nahi rehta, physics ke rules wahan toot jaate hain."},
            {"text": "Yeh sab sun kar aap kya soch rahe hain, comment mein zaroor batana! Subscribe karein, daily aise hi cosmic facts ke liye."}
        ]
    },
]


# ══════════════════════════════════════════════════════
# STEP 1: FETCH FACT CONTEXT (Tavily)
# ══════════════════════════════════════════════════════
def fetch_fact_tavily():
    if not TAVILY_API_KEY:
        return None
    try:
        topic = random.choice(TOPICS)
        log.info("Tavily search: " + topic)
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": topic,
                "max_results": 3,
                "search_depth": "basic",
                "include_answer": True
            },
            timeout=20
        )
        data = resp.json()
        parts = []
        if data.get("answer"):
            parts.append(data["answer"])
        for r in data.get("results", [])[:2]:
            if r.get("content"):
                parts.append(r["content"][:400])
        raw = " | ".join(parts)
        if len(raw) > 50:
            return raw
        return None
    except Exception as e:
        log.warning("Tavily failed: " + str(e))
        return None


# ══════════════════════════════════════════════════════
# STEP 2: GENERATE FULL 5-SEGMENT SCRIPT (Groq)
# ══════════════════════════════════════════════════════
def generate_script_with_groq(raw_context):
    """
    Generates a longer-form ~60 second script structured as:
    hook -> fact1 -> fact2 -> fact3 -> outro/CTA
    Each segment is its own short voiceover line + slide.
    This naturally produces 55-65 seconds of speech at normal pace.
    """
    client = Groq(api_key=GROQ_API_KEY)

    schema = (
        "{\n"
        "  \"title\": \"short catchy Hinglish title max 5 words NO emoji\",\n"
        "  \"category\": \"Psychology or Space or Science or Animals or History\",\n"
        "  \"english_title\": \"SEO YouTube title English max 60 chars\",\n"
        "  \"description\": \"120 word English YouTube description\",\n"
        "  \"tags\": \"tag1,tag2,tag3,tag4,tag5,tag6,tag7,tag8,tag9,tag10\",\n"
        "  \"segments\": [\n"
        "    {\"text\": \"strong hook line in Hinglish, 1-2 sentences, grabs attention immediately\"},\n"
        "    {\"text\": \"fact 1 in Hinglish, 2 sentences, conversational\"},\n"
        "    {\"text\": \"fact 2 in Hinglish, 2 sentences, conversational\"},\n"
        "    {\"text\": \"fact 3 in Hinglish, 2 sentences, conversational\"},\n"
        "    {\"text\": \"outro with subscribe call to action in Hinglish, 1-2 sentences\"}\n"
        "  ]\n"
        "}"
    )

    if raw_context:
        system = (
            "You are a viral YouTube Shorts script writer for Ajeebology Shorts "
            "(Psychology, Space, Weird Facts channel). Write in Hinglish "
            "(Hindi+English mix, Roman script). The full script across all 5 "
            "segments should take about 55-65 seconds to speak aloud at normal "
            "pace - so each segment should be substantial, not just one short "
            "phrase. Return ONLY valid JSON, no markdown, no extra text."
        )
        user = "Source info: " + str(raw_context[:800]) + "\n\nReturn ONLY this JSON:\n" + schema
    else:
        system = (
            "You are a viral YouTube Shorts script writer for Ajeebology Shorts "
            "(Psychology, Space, Weird Facts channel). Write in Hinglish "
            "(Hindi+English mix, Roman script). The full script across all 5 "
            "segments should take about 55-65 seconds to speak aloud at normal "
            "pace - so each segment should be substantial, not just one short "
            "phrase. Return ONLY valid JSON, no markdown, no extra text."
        )
        user = "Create an original mind-blowing multi-fact script. Return ONLY this JSON:\n" + schema

    try:
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            temperature=0.85,
            max_tokens=1200,
        )
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        script_data = json.loads(content)

        if "segments" not in script_data or len(script_data["segments"]) < 3:
            raise ValueError("Script too short or missing segments")

        log.info("Script generated: " + script_data.get("title", "") +
                  " (" + str(len(script_data["segments"])) + " segments)")
        return script_data
    except Exception as e:
        log.warning("Groq script generation failed: " + str(e))
        return random.choice(FALLBACK_SCRIPTS)


def get_todays_script():
    raw = fetch_fact_tavily()
    try:
        script = generate_script_with_groq(raw)
        return script
    except Exception as e:
        log.warning("Using fallback script: " + str(e))
        return random.choice(FALLBACK_SCRIPTS)


# ══════════════════════════════════════════════════════
# STEP 3: MALE VOICE TTS PER SEGMENT
# ══════════════════════════════════════════════════════
async def generate_tts_async(text, path):
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural")
        await communicate.save(str(path))
        return True
    except Exception as e:
        log.warning("edge-tts failed: " + str(e))
        return False


def generate_raw_voiceover(script):
    """Generates one raw (unedited) TTS clip per segment."""
    AUDIO_DIR.mkdir(exist_ok=True)
    clips = []
    for i, seg in enumerate(script["segments"]):
        path = AUDIO_DIR / ("raw_" + str(i) + ".mp3")
        log.info("Generating raw TTS for segment " + str(i + 1) + "/" + str(len(script["segments"])))
        success = asyncio.run(generate_tts_async(seg["text"], path))
        if not success or not path.exists():
            try:
                from gtts import gTTS
                tts = gTTS(text=seg["text"], lang="hi", slow=False, tld="co.uk")
                tts.save(str(path))
            except Exception as e:
                log.error("All TTS failed for segment " + str(i) + ": " + str(e))
                subprocess.run([
                    "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", "3", "-q:a", "9", "-acodec", "libmp3lame",
                    str(path), "-y"
                ], capture_output=True)
        clips.append(path)
    return clips


# ══════════════════════════════════════════════════════
# STEP 4: AUDIO CLEANUP — TRIM PAUSES + SPEED UP
# ══════════════════════════════════════════════════════
def clean_audio_clip(raw_path, clean_path, speed=1.06):
    """
    Removes long silences from AI-generated voice (a known gTTS/edge-tts
    problem) using ffmpeg's silenceremove filter, then applies a slight
    atempo speedup (default 1.06x) to tighten pacing without pitch shift.

    silenceremove logic:
    - start_periods=1: trim leading silence once
    - start_duration=0.15: silence shorter than this is kept (avoids
      cutting natural micro-pauses between words)
    - start_threshold=-35dB: anything quieter than this counts as silence
    - The same params applied with stop_periods=-1 trims ALL internal
      silences longer than the threshold duration, not just leading/trailing
    """
    filter_chain = (
        "silenceremove="
        "start_periods=1:start_duration=0.15:start_threshold=-35dB:"
        "stop_periods=-1:stop_duration=0.35:stop_threshold=-35dB,"
        "atempo=" + str(speed)
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(raw_path),
        "-af", filter_chain,
        "-ar", "44100", "-ac", "1",
        str(clean_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not Path(clean_path).exists():
        log.warning("Audio cleanup failed for " + str(raw_path) + ", using raw copy")
        subprocess.run(["cp", str(raw_path), str(clean_path)], capture_output=True)
        return False
    return True


def clean_all_clips(raw_clips):
    AUDIO_CLEAN_DIR.mkdir(exist_ok=True)
    cleaned = []
    for i, raw_path in enumerate(raw_clips):
        clean_path = AUDIO_CLEAN_DIR / ("clean_" + str(i) + ".mp3")
        log.info("Cleaning audio segment " + str(i + 1) + "/" + str(len(raw_clips)))
        clean_audio_clip(raw_path, clean_path)
        cleaned.append(clean_path)
    return cleaned


def get_audio_duration(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "json", str(path)
        ], capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 5.0


# ══════════════════════════════════════════════════════
# STEP 5: SOUND EFFECTS (transition whoosh + word ding)
# ══════════════════════════════════════════════════════
def download_sfx():
    """
    Downloads two short free SFX from Pixabay's open CDN:
    a whoosh for slide transitions, a soft ding for emphasis beats.
    If downloads fail, SFX are simply skipped later (non-fatal).
    """
    SFX_DIR.mkdir(exist_ok=True)
    sfx_targets = {
        WHOOSH_FILE: [
            "https://cdn.pixabay.com/download/audio/2022/03/10/audio_270a8d3030.mp3",
            "https://cdn.pixabay.com/download/audio/2021/08/04/audio_12b0c7443c.mp3",
        ],
        DING_FILE: [
            "https://cdn.pixabay.com/download/audio/2021/08/04/audio_0625c1539c.mp3",
            "https://cdn.pixabay.com/download/audio/2022/03/24/audio_e0a0c0f76b.mp3",
        ],
    }
    for target_path, urls in sfx_targets.items():
        if target_path.exists():
            continue
        for url in urls:
            try:
                r = requests.get(url, timeout=20)
                if r.status_code == 200 and len(r.content) > 3000:
                    with open(target_path, "wb") as f:
                        f.write(r.content)
                    log.info("SFX downloaded: " + str(target_path))
                    break
            except Exception as e:
                log.warning("SFX download failed (" + str(target_path) + "): " + str(e))
                continue


# ══════════════════════════════════════════════════════
# STEP 6: BACKGROUND MUSIC
# ══════════════════════════════════════════════════════
def download_free_music():
    urls = [
        "https://cdn.pixabay.com/download/audio/2023/06/19/audio_0babde2a4c.mp3",
        "https://cdn.pixabay.com/download/audio/2022/10/25/audio_913fb96e1f.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb4bae0c2.mp3",
    ]
    for url in urls:
        try:
            log.info("Downloading background music...")
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(MUSIC_FILE, "wb") as f:
                    f.write(r.content)
                log.info("Music downloaded OK")
                return True
        except Exception as e:
            log.warning("Music URL failed: " + str(e))
            continue
    log.warning("All music downloads failed - video will proceed without music")
    return False


# ══════════════════════════════════════════════════════
# STEP 7: CONCAT CLEANED CLIPS WITH SFX TRANSITIONS
# ══════════════════════════════════════════════════════
def build_voice_track_with_sfx(cleaned_clips):
    """
    Concatenates all cleaned voice segments into one track, inserting
    a short whoosh sound at each segment boundary (if SFX available).
    Returns path to the combined voice track and list of each segment's
    actual duration (needed later for video timing in Part 2).
    """
    has_whoosh = WHOOSH_FILE.exists()
    segment_durations = [get_audio_duration(c) for c in cleaned_clips]

    list_file = "voice_concat_list.txt"
    with open(list_file, "w") as f:
        for i, clip in enumerate(cleaned_clips):
            f.write("file '" + str(clip.resolve()) + "'\n")
            if has_whoosh and i < len(cleaned_clips) - 1:
                f.write("file '" + str(WHOOSH_FILE.resolve()) + "'\n")

    combined_voice = "voice_combined.mp3"
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", combined_voice
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("SFX-interleaved concat failed, falling back to plain concat")
        with open(list_file, "w") as f:
            for clip in cleaned_clips:
                f.write("file '" + str(clip.resolve()) + "'\n")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", combined_voice
        ], capture_output=True)

    return combined_voice, segment_durations


# ══════════════════════════════════════════════════════
# STEP 8: MIX VOICE + DUCKED MUSIC
# ══════════════════════════════════════════════════════
def mix_voice_and_music(voice_track, output_path="final_audio.mp3"):
    """
    Mixes the voice track with background music using sidechaincompress
    so the music automatically ducks (lowers volume) whenever the voice
    is speaking, and rises back up in gaps - this is the actual technique
    professional editors use instead of a flat low music volume.
    """
    has_music = Path(MUSIC_FILE).exists()
    if not has_music:
        log.info("No music available, using voice track only")
        subprocess.run(["cp", voice_track, output_path], capture_output=True)
        return output_path

    filter_complex = (
        "[1:a]aloop=loop=-1:size=2e+09,volume=0.35[music_loud];"
        "[0:a]asplit=2[voice_main][voice_sc];"
        "[music_loud][voice_sc]sidechaincompress="
        "threshold=0.05:ratio=8:attack=5:release=300[music_ducked];"
        "[voice_main][music_ducked]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", voice_track,
        "-i", MUSIC_FILE,
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-ar", "44100", "-ac", "2",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("Sidechain ducking failed, falling back to flat low-volume music mix")
        fallback_filter = (
            "[1:a]aloop=loop=-1:size=2e+09,volume=0.12[music];"
            "[0:a][music]amix=inputs=2:duration=first[aout]"
        )
        subprocess.run([
            "ffmpeg", "-y", "-i", voice_track, "-i", MUSIC_FILE,
            "-filter_complex", fallback_filter,
            "-map", "[aout]", "-ar", "44100", "-ac", "2",
            output_path
        ], capture_output=True)
    return output_path


# ══════════════════════════════════════════════════════
# STANDALONE TEST ENTRY POINT FOR PART 1
# (Part 2 will replace this with the full main() that also
# builds video frames and calls Telegram notification)
# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# PART 2 OF 2 — VISUAL PIPELINE + FINAL ASSEMBLY
#
# PLACEMENT: Paste this directly below Part 1 in the same file,
# REPLACING Part 1's test_audio_pipeline() function and its
# `if __name__ == "__main__":` block at the bottom. This part
# adds its own complete main() that uses everything from Part 1.
# ══════════════════════════════════════════════════════

import math
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT  = 720, 1280
FPS            = 20
OUTPUT_VIDEO   = "output_video.mp4"
THUMBNAIL_FILE = "thumbnail.png"
FRAMES_DIR     = Path("frames")
FONT_PATH      = "NotoSans.ttf"
FONT_BOLD_PATH = "NotoSans-Bold.ttf"
CROSSFADE_SECS = 0.3

BRAND = {
    "bg_dark":   (8, 4, 20),
    "bg_mid":    (22, 10, 48),
    "purple1":   (120, 60, 220),
    "purple2":   (160, 80, 255),
    "cyan":      (0, 255, 255),
    "yellow":    (255, 215, 0),
    "white":     (255, 255, 255),
    "glow_p":    (100, 40, 180),
    "glow_c":    (40, 150, 200),
    "red":       (255, 40, 40),
}


# ══════════════════════════════════════════════════════
# FONTS
# ══════════════════════════════════════════════════════
def download_fonts():
    fonts = {
        FONT_PATH: "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
        FONT_BOLD_PATH: "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Bold.ttf",
    }
    for fname, url in fonts.items():
        if not Path(fname).exists():
            try:
                log.info("Downloading font: " + fname)
                r = requests.get(url, timeout=30)
                with open(fname, "wb") as f:
                    f.write(r.content)
            except Exception as e:
                log.warning("Font download failed: " + str(e))


def load_font(size, bold=False):
    path = FONT_BOLD_PATH if bold else FONT_PATH
    fallbacks = [
        path,
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in fallbacks:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ══════════════════════════════════════════════════════
# WORD TIMELINE (karaoke approximation, weighted by length)
# ══════════════════════════════════════════════════════
def build_word_timeline(text, total_duration):
    words = text.split()
    if not words:
        return []
    weights = [max(len(w), 2) for w in words]
    total_weight = sum(weights)
    timeline = []
    t_cursor = 0.0
    for w, wt in zip(words, weights):
        dur = (wt / total_weight) * total_duration
        timeline.append({"word": w, "start": t_cursor, "end": t_cursor + dur})
        t_cursor += dur
    return timeline


def current_word_index(timeline, current_time):
    for i, item in enumerate(timeline):
        if item["start"] <= current_time < item["end"]:
            return i
    if timeline and current_time >= timeline[-1]["end"]:
        return len(timeline) - 1
    return -1


# ══════════════════════════════════════════════════════
# BACKGROUND DRAWING
# ══════════════════════════════════════════════════════
def draw_gradient(img):
    draw = ImageDraw.Draw(img)
    bg1, bg2 = BRAND["bg_dark"], BRAND["bg_mid"]
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(bg1[0] + (bg2[0]-bg1[0]) * t)
        g = int(bg1[1] + (bg2[1]-bg1[1]) * t)
        b = int(bg1[2] + (bg2[2]-bg1[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def draw_stars_animated(draw, frame, count=130):
    random.seed(42)
    for _ in range(count):
        x = random.randint(0, WIDTH)
        y = random.randint(0, HEIGHT)
        base_r = random.randint(1, 3)
        phase = random.random() * 6.28
        twinkle = abs(math.sin(frame * 0.08 + phase))
        brightness = int(90 + 165 * twinkle)
        r = max(1, int(base_r * (0.5 + twinkle * 0.5)))
        draw.ellipse([x-r, y-r, x+r, y+r],
                     fill=(brightness, int(brightness*0.85), 255))
    random.seed()


def draw_grid_matrix(draw, frame, alpha_base=18):
    spacing = 70
    offset = frame % spacing
    shimmer = max(6, min(40, int(alpha_base + 10 * math.sin(frame * 0.05))))
    base = BRAND["purple1"]
    faint = tuple(int(c * (shimmer / 255.0) + 8) for c in base)
    for x in range(-spacing, WIDTH + spacing, spacing):
        draw.line([(x+offset, 0), (x+offset, HEIGHT)], fill=faint, width=1)
    for y in range(0, HEIGHT, spacing):
        draw.line([(0, y), (WIDTH, y)], fill=faint, width=1)


def draw_particles(draw, frame, count=22):
    random.seed(frame // 3)
    for i in range(count):
        angle = (frame * 2 + i * 30) % 360
        rad = math.radians(angle)
        dist = 80 + (i % 5) * 40
        cx = WIDTH // 2 + int(dist * math.cos(rad))
        cy = HEIGHT // 4 + int(dist * math.sin(rad) * 0.5)
        size = random.randint(2, 5)
        colors = [BRAND["purple2"], BRAND["cyan"], BRAND["white"]]
        draw.ellipse([cx-size, cy-size, cx+size, cy+size], fill=colors[i % 3])
    random.seed()


def apply_ken_burns(img, progress, zoom_start=1.0, zoom_end=1.08, pan_px=20):
    """
    Applies a slow zoom + slight pan across the duration of a slide
    (progress 0.0 -> 1.0). This is THE single biggest 'looks professionally
    edited' signal for static-content video - real editors almost never
    leave a frame perfectly still.
    """
    zoom = zoom_start + (zoom_end - zoom_start) * progress
    new_w = int(WIDTH * zoom)
    new_h = int(HEIGHT * zoom)
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    pan_x = int(pan_px * progress)
    pan_y = int(pan_px * 0.5 * progress)

    left = (new_w - WIDTH) // 2 + pan_x
    top = (new_h - HEIGHT) // 2 + pan_y
    left = max(0, min(left, new_w - WIDTH))
    top = max(0, min(top, new_h - HEIGHT))

    cropped = resized.crop((left, top, left + WIDTH, top + HEIGHT))
    return cropped


# ══════════════════════════════════════════════════════
# TEXT DRAWING
# ══════════════════════════════════════════════════════
def get_text_size(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * 20, 30


def draw_outlined_text(draw, pos, text, font, fill_color, outline_color=(0, 0, 0), stroke=3):
    x, y = pos
    for dx in range(-stroke, stroke + 1):
        for dy in range(-stroke, stroke + 1):
            if dx*dx + dy*dy <= stroke*stroke:
                draw.text((x+dx, y+dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)


def draw_glowing_text(draw, pos, text, font, color, glow_color, glow_range=3):
    x, y = pos
    for dx in range(-glow_range, glow_range + 1):
        for dy in range(-glow_range, glow_range + 1):
            if dx != 0 or dy != 0:
                draw.text((x+dx, y+dy), text, font=font, fill=glow_color)
    draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=color)


def wrap_text(text, font, max_width):
    words = text.split()
    lines, current = [], ""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = (current + " " + word).strip()
        try:
            bbox = dummy.textbbox((0, 0), test, font=font)
            width = bbox[2] - bbox[0]
        except Exception:
            width = len(test) * 20
        if width <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_words_with_index(words, font, max_width, draw):
    lines, current_line, current_width = [], [], 0
    space_w, _ = get_text_size(draw, " ", font)
    for idx, word in enumerate(words):
        ww, _ = get_text_size(draw, word, font)
        added = ww if not current_line else ww + space_w
        if current_width + added <= max_width or not current_line:
            current_line.append((word, idx))
            current_width += added
        else:
            lines.append(current_line)
            current_line = [(word, idx)]
            current_width = ww
    if current_line:
        lines.append(current_line)
    return lines


def draw_karaoke_paragraph(draw, top_y, words, max_width, font,
                            active_index, highlight_color,
                            white_color=(255, 255, 255), line_height=50,
                            center_x=WIDTH // 2, stroke=3):
    lines = wrap_words_with_index(words, font, max_width, draw)
    space_w, _ = get_text_size(draw, " ", font)
    y = top_y
    for line in lines:
        line_text = " ".join([w for w, _ in line])
        lw, _ = get_text_size(draw, line_text, font)
        x = center_x - lw // 2
        for word, idx in line:
            ww, _ = get_text_size(draw, word, font)
            if idx == active_index:
                draw_glowing_text(draw, (x, y), word, font,
                                  highlight_color, highlight_color, glow_range=2)
            else:
                draw_outlined_text(draw, (x, y), word, font,
                                   white_color, (0, 0, 0), stroke=stroke)
            x += ww + space_w
        y += line_height
    return y - top_y


# ══════════════════════════════════════════════════════
# FRAME RENDERING
# ══════════════════════════════════════════════════════
def create_base_frame(frame_num, slide_index, total_slides,
                       title, body_text, category,
                       word_timeline, current_time, slide_progress,
                       show_cta):
    """Renders one complete frame (background + UI + karaoke text + CTA)."""
    base = Image.new("RGB", (int(WIDTH*1.1), int(HEIGHT*1.1)), color=BRAND["bg_dark"])
    draw_gradient(base)
    bdraw = ImageDraw.Draw(base)
    draw_grid_matrix(bdraw, frame_num)
    draw_stars_animated(bdraw, frame_num)
    draw_particles(bdraw, frame_num)

    img = apply_ken_burns(base, slide_progress)
    draw = ImageDraw.Draw(img)

    pad = 40

    pulse = 0.7 + 0.3 * math.sin(frame_num * 0.15)
    cx, cy = WIDTH // 2, HEIGHT // 4
    for radius, color in [(170, BRAND["glow_p"]), (110, BRAND["glow_c"])]:
        r = int(radius * pulse)
        for thickness in range(4, 0, -1):
            alpha_val = int(15 * thickness * pulse)
            ocol = (min(255, color[0]+alpha_val), min(255, color[1]+alpha_val), min(255, color[2]+alpha_val))
            draw.ellipse([cx-r-thickness*3, cy-r-thickness*3, cx+r+thickness*3, cy+r+thickness*3],
                         outline=ocol, width=1)

    # Header
    draw.rectangle([0, 0, WIDTH, 85], fill=(4, 2, 12))
    draw.line([(0, 85), (WIDTH, 85)], fill=BRAND["cyan"], width=2)
    font_top = load_font(24, bold=True)
    draw.text((pad, 28), "AJEEBOLOGY STUDIO", font=font_top, fill=BRAND["cyan"])

    rec_blink = abs(math.sin(frame_num * 0.3))
    rec_alpha = 0.4 + 0.6 * rec_blink
    rec_color = tuple(int(c * rec_alpha) for c in BRAND["red"])
    draw.ellipse([WIDTH-95, 30, WIDTH-75, 50], fill=rec_color)
    draw.text((WIDTH-65, 30), "LIVE", font=load_font(20, bold=True), fill=BRAND["white"])

    # Slide dots
    dot_y = 110
    spacing = 28
    total_w = (total_slides - 1) * spacing
    start_x = (WIDTH - total_w) // 2
    for i in range(total_slides):
        x = start_x + i * spacing
        if i == slide_index:
            pr = int(10 + 3 * math.sin(frame_num * 0.2))
            draw.ellipse([x-pr, dot_y-pr, x+pr, dot_y+pr], fill=BRAND["cyan"])
            draw.ellipse([x-6, dot_y-6, x+6, dot_y+6], fill=BRAND["white"])
        else:
            draw.ellipse([x-5, dot_y-5, x+5, dot_y+5], fill=(60, 40, 100))

    # Category badge
    font_badge = load_font(22, bold=True)
    cat_icons = {"Psychology": "BRAIN", "Space": "SPACE", "Science": "SCIENCE",
                "Animals": "NATURE", "History": "HISTORY"}
    badge_text = "[ " + cat_icons.get(category, "FACTS") + " ]"
    bw, bh = get_text_size(draw, badge_text, font_badge)
    bx, by = (WIDTH - bw)//2, 138
    draw.rounded_rectangle([bx-15, by-8, bx+bw+15, by+bh+8], radius=15, fill=BRAND["purple1"])
    draw.text((bx, by), badge_text, font=font_badge, fill=BRAND["cyan"])

    # Title
    font_title = load_font(46, bold=True)
    title_lines = wrap_text(title, font_title, WIDTH - pad*2)
    title_y = 195
    title_alpha = min(1.0, slide_progress * 6)
    for line in title_lines:
        lw, lh = get_text_size(draw, line, font_title)
        tx = (WIDTH - lw)//2
        glow_c = tuple(int(c*title_alpha) for c in BRAND["purple2"])
        text_c = tuple(int(c*title_alpha) for c in BRAND["white"])
        draw_glowing_text(draw, (tx, title_y), line, font_title, text_c, glow_c)
        title_y += lh + 8

    div_y = title_y + 16
    line_progress = min(1.0, slide_progress * 4)
    line_end = int(pad + (WIDTH - pad*2) * line_progress)
    if line_end > pad:
        draw.line([(pad, div_y), (line_end, div_y)], fill=BRAND["cyan"], width=3)

    # Karaoke body card
    font_body = load_font(34, bold=True)
    words = body_text.split()
    box_top = div_y + 24
    box_inner_pad = 22
    max_text_width = WIDTH - pad*2 - box_inner_pad*2
    dry_lines = wrap_words_with_index(words, font_body, max_text_width, draw)
    line_height = 48
    body_height = len(dry_lines) * line_height + 20

    glow_col = (min(255, BRAND["purple1"][0]+20), min(255, BRAND["purple1"][1]+10), min(255, BRAND["purple1"][2]+30))
    draw.rounded_rectangle([pad-5, box_top-5, WIDTH-pad+5, box_top+body_height+5], radius=18, outline=glow_col, width=2)
    draw.rounded_rectangle([pad, box_top, WIDTH-pad, box_top+body_height], radius=20, fill=(6, 3, 16))
    border_pulse = int(160 + 80 * math.sin(frame_num * 0.15))
    draw.rounded_rectangle([pad, box_top, WIDTH-pad, box_top+body_height], radius=20,
                           outline=(0, border_pulse, 255), width=3)

    active_idx = current_word_index(word_timeline, current_time)
    highlight = BRAND["yellow"] if (slide_index % 2 == 0) else BRAND["cyan"]
    draw_karaoke_paragraph(draw, box_top + box_inner_pad, words, max_text_width,
                           font_body, active_idx, highlight, BRAND["white"], line_height)

    # Delayed CTA — only fades in during final slide's last portion
    if show_cta > 0:
        cta_top = HEIGHT - 210
        cta_alpha = show_cta
        overlay_bg = tuple(int(c*cta_alpha) for c in (4, 2, 12))
        draw.rectangle([0, cta_top, WIDTH, HEIGHT-14], fill=overlay_bg)
        if cta_alpha > 0.3:
            draw.line([(0, cta_top), (WIDTH, cta_top)], fill=BRAND["purple2"], width=3)
            font_cta = load_font(28, bold=True)
            font_sub = load_font(24)
            cta_pulse = int(200 + 55 * abs(math.sin(frame_num * 0.25)))
            cta_color = tuple(int(c*cta_alpha) for c in (cta_pulse, 80, 255))
            items = [("SUBSCRIBE NOW!", font_cta, cta_color),
                    ("Daily Facts at 5:00 PM PKT", font_sub, tuple(int(c*cta_alpha) for c in BRAND["white"])),
                    ("@AjeebologyShorts", font_sub, tuple(int(c*cta_alpha) for c in BRAND["cyan"]))]
            cy2 = cta_top + 16
            for text_item, font_item, color_item in items:
                lw, lh = get_text_size(draw, text_item, font_item)
                draw.text(((WIDTH-lw)//2, cy2), text_item, font=font_item, fill=color_item)
                cy2 += lh + 14

    return img


def draw_bottom_progress_bar(img, overall_progress):
    draw = ImageDraw.Draw(img)
    bar_h = 6
    bar_y = HEIGHT - bar_h
    draw.rectangle([0, bar_y, WIDTH, HEIGHT], fill=(20, 10, 35))
    filled_w = int(WIDTH * overall_progress)
    draw.rectangle([0, bar_y, filled_w, HEIGHT], fill=BRAND["cyan"])
    if filled_w > 0:
        draw.ellipse([filled_w-5, bar_y-3, filled_w+5, bar_y+bar_h+3], fill=BRAND["yellow"])
    return img


# ══════════════════════════════════════════════════════
# SLIDE FRAME GENERATION (with crossfade overlap)
# ══════════════════════════════════════════════════════
def create_slide_frames(slide_index, total_slides, title, body_text,
                         category, duration_secs, total_video_duration,
                         elapsed_before):
    total_frames = max(1, int(duration_secs * FPS))
    word_timeline = build_word_timeline(body_text, duration_secs)
    is_last_slide = (slide_index == total_slides - 1)
    paths = []

    for f in range(total_frames):
        current_time = f / FPS
        slide_progress = f / max(total_frames - 1, 1)
        overall_progress = (elapsed_before + current_time) / total_video_duration

        show_cta = 0.0
        if is_last_slide:
            cta_window = min(3.0, duration_secs * 0.4)
            time_remaining = duration_secs - current_time
            if time_remaining <= cta_window:
                show_cta = min(1.0, (cta_window - time_remaining) / 0.6)

        img = create_base_frame(f, slide_index, total_slides, title, body_text,
                                category, word_timeline, current_time,
                                slide_progress, show_cta)
        img = draw_bottom_progress_bar(img, overall_progress)

        path = FRAMES_DIR / ("s" + str(slide_index) + "_f" + str(f).zfill(4) + ".png")
        img.save(str(path), "PNG")
        paths.append(path)

    return paths


def create_all_slides(script, segment_durations):
    FRAMES_DIR.mkdir(exist_ok=True)
    category = script.get("category", "Facts")
    segments = script["segments"]
    total_video_duration = sum(segment_durations)

    slide_titles = []
    n = len(segments)
    for i in range(n):
        if i == 0:
            slide_titles.append(script["title"])
        elif i == n - 1:
            slide_titles.append("Mind Blown!")
        else:
            slide_titles.append(category + " Fact " + str(i))

    all_frame_paths = []
    thumbnail = None
    elapsed = 0.0

    for i, (seg, dur) in enumerate(zip(segments, segment_durations)):
        log.info("Rendering slide " + str(i+1) + "/" + str(n) +
                 " (" + str(round(dur, 1)) + "s)")
        frame_paths = create_slide_frames(
            i, n, slide_titles[i], seg["text"], category,
            dur, total_video_duration, elapsed
        )
        all_frame_paths.append(frame_paths)
        if i == 0 and frame_paths:
            thumbnail = Image.open(str(frame_paths[len(frame_paths)//2]))
        elapsed += dur

    return all_frame_paths, thumbnail


# ══════════════════════════════════════════════════════
# CROSSFADE BLENDING BETWEEN SLIDE BOUNDARIES
# ══════════════════════════════════════════════════════
def apply_crossfades(slide_frame_groups):
    """
    Blends the last N frames of each slide with the first N frames of
    the next slide using alpha compositing, replacing the hard-cut
    boundary frames with smooth crossfade frames. Modifies files in
    place and returns the final flat ordered list of all frame paths.
    """
    crossfade_frames = max(1, int(CROSSFADE_SECS * FPS))

    for i in range(len(slide_frame_groups) - 1):
        current_group = slide_frame_groups[i]
        next_group = slide_frame_groups[i + 1]

        n = min(crossfade_frames, len(current_group), len(next_group))
        if n < 1:
            continue

        for k in range(n):
            alpha = (k + 1) / (n + 1)
            out_idx = len(current_group) - n + k
            in_idx = k

            try:
                img_out = Image.open(str(current_group[out_idx])).convert("RGB")
                img_in = Image.open(str(next_group[in_idx])).convert("RGB")
                blended = Image.blend(img_out, img_in, alpha)
                blended.save(str(current_group[out_idx]), "PNG")
            except Exception as e:
                log.warning("Crossfade blend failed at slide boundary " + str(i) + ": " + str(e))

    flat_list = []
    for group in slide_frame_groups:
        flat_list.extend(group)
    return flat_list


# ══════════════════════════════════════════════════════
# FINAL VIDEO ASSEMBLY
# ══════════════════════════════════════════════════════
def build_video(all_frames, final_audio_path):
    log.info("Assembling final video...")

    frame_list_file = "frame_list.txt"
    with open(frame_list_file, "w") as f:
        for frame in all_frames:
            f.write("file '" + str(Path(frame).resolve()) + "'\n")
            f.write("duration " + str(1.0/FPS) + "\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", frame_list_file,
        "-i", str(final_audio_path),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-r", str(FPS),
        "-shortest",
        "-movflags", "+faststart",
        OUTPUT_VIDEO
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("FFmpeg final assembly error: " + result.stderr[-2000:])
        return False
    log.info("Video built successfully!")
    return True


# ══════════════════════════════════════════════════════
# TELEGRAM NOTIFICATION (unchanged from earlier versions)
# ══════════════════════════════════════════════════════
def generate_youtube_metadata(script):
    english_title = script.get("english_title", script["title"] + " | Ajeebology Shorts")
    date_str = datetime.now().strftime("%d %b %Y")
    description = script.get("description", "Amazing facts daily on Ajeebology Shorts!")
    description += (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "AJEEBOLOGY SHORTS\nDaily Facts at 5:00 PM PKT\n"
        "Business: ubaidurehman983@gmail.com\nPublished: " + date_str +
        "\n━━━━━━━━━━━━━━━━━━━━━━"
    )
    raw_tags = script.get("tags", "")
    tag_list = [t.strip() for t in raw_tags.split(",")] if raw_tags else [
        "AjeebologyShorts", "facts", "psychology", "space", "mindblowing",
        "didyouknow", "shorts", "viral", "hindi", "knowledge", "science", "amazing"
    ]
    hashtags = " ".join(["#" + t.replace(" ", "").replace("#", "") for t in tag_list[:15]])
    return english_title, description, tag_list, hashtags


def send_telegram_message(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                            "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30)
        return resp.ok
    except Exception as e:
        log.error("Telegram message failed: " + str(e))
        return False


def send_telegram_video(caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendVideo"
    try:
        with open(OUTPUT_VIDEO, "rb") as vf:
            resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024],
                            "parse_mode": "HTML", "supports_streaming": True},
                            files={"video": vf}, timeout=180)
        return resp.ok
    except Exception as e:
        log.error("Telegram video failed: " + str(e))
        return False


def send_telegram_photo(caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto"
    try:
        with open(THUMBNAIL_FILE, "rb") as f:
            resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024],
                            "parse_mode": "HTML"}, files={"photo": f}, timeout=60)
        return resp.ok
    except Exception as e:
        log.warning("Telegram photo failed: " + str(e))
        return False


def notify_telegram(script, video_ok):
    artifact_url = ("https://github.com/" + GITHUB_REPO + "/actions/runs/" + GITHUB_RUN_ID
                    if GITHUB_REPO and GITHUB_RUN_ID else "https://github.com")
    date_str = datetime.now().strftime("%d %b %Y %H:%M UTC")
    english_title, description, tag_list, hashtags = generate_youtube_metadata(script)

    if video_ok:
        video_caption = "🎬 <b>" + english_title + "</b>\n\n" + hashtags
        size_mb = Path(OUTPUT_VIDEO).stat().st_size / (1024*1024) if Path(OUTPUT_VIDEO).exists() else 0
        if size_mb < 48:
            send_telegram_video(video_caption)
        elif Path(THUMBNAIL_FILE).exists():
            send_telegram_photo(video_caption)

        tags_str = ", ".join(tag_list[:20])
        metadata_msg = (
            "✅ <b>VIDEO READY — " + date_str + "</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎬 <b>YOUTUBE TITLE:</b>\n" + english_title + "\n\n"
            "📝 <b>DESCRIPTION:</b>\n" + description[:700] + "\n\n"
            "🏷️ <b>TAGS:</b>\n" + tags_str + "\n\n"
            "#️⃣ <b>HASHTAGS:</b>\n" + hashtags + "\n\n"
            "📥 <b>DOWNLOAD:</b>\n<a href='" + artifact_url + "'>Click Here - GitHub Artifact</a>\n\n"
            "⏰ Upload at 5:00 PM PKT\n📧 ubaidurehman983@gmail.com\n━━━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_message(metadata_msg)
    else:
        send_telegram_message("❌ <b>VIDEO FAILED — " + date_str + "</b>\n\nLogs: <a href='" +
                              artifact_url + "'>GitHub Actions</a>")


# ══════════════════════════════════════════════════════
# MAIN — TIES PART 1 (AUDIO) + PART 2 (VIDEO) TOGETHER
# ══════════════════════════════════════════════════════
def main():
    log.info("AJEEBOLOGY SHORTS AGENT STARTED (full production pipeline)")

    log.info("STEP 1: Downloading fonts...")
    download_fonts()

    log.info("STEP 2: Generating 5-segment script...")
    script = get_todays_script()
    log.info("Title: " + script["title"] + " | Segments: " + str(len(script["segments"])))

    log.info("STEP 3: Generating raw TTS per segment...")
    raw_clips = generate_raw_voiceover(script)

    log.info("STEP 4: Cleaning audio (trim pauses + speed up)...")
    cleaned_clips = clean_all_clips(raw_clips)
    segment_durations = [get_audio_duration(c) for c in cleaned_clips]
    log.info("Segment durations: " + str([round(d, 1) for d in segment_durations]))
    log.info("Total speech duration: " + str(round(sum(segment_durations), 1)) + "s")

    log.info("STEP 5: Downloading SFX...")
    download_sfx()

    log.info("STEP 6: Downloading background music...")
    download_free_music()

    log.info("STEP 7: Building voice track with SFX transitions...")
    voice_track, sfx_segment_durations = build_voice_track_with_sfx(cleaned_clips)

    log.info("STEP 8: Mixing voice + ducked music...")
    final_audio = mix_voice_and_music(voice_track)
    final_audio_duration = get_audio_duration(final_audio)
    log.info("FINAL AUDIO DURATION: " + str(round(final_audio_duration, 1)) + "s")

    log.info("STEP 9: Rendering animated Ken Burns + karaoke frames...")
    slide_frame_groups, thumbnail = create_all_slides(script, segment_durations)

    if thumbnail:
        thumbnail.save(THUMBNAIL_FILE, "PNG")
        log.info("Thumbnail saved")

    log.info("STEP 10: Applying crossfade transitions...")
    all_frames = apply_crossfades(slide_frame_groups)
    log.info("Total frames: " + str(len(all_frames)))

    log.info("STEP 11: Building final video...")
    video_ok = build_video(all_frames, final_audio)

    log.info("STEP 12: Sending Telegram notification...")
    notify_telegram(script, video_ok)

    if video_ok:
        log.info("PIPELINE COMPLETE!")
    else:
        log.error("PIPELINE FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
