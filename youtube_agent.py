import os
import sys
import json
import random
import logging
import textwrap
import requests
import subprocess
from pathlib import Path
from datetime import datetime

# ── Third-party ──────────────────────────────────────────────
from groq import Groq
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ── Logging Setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("AjeebologyAgent")

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════
GROQ_API_KEY     = os.environ["GROQ_API_KEY"]
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY", "")
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GITHUB_RUN_ID    = os.environ.get("GITHUB_RUN_ID", "")
GITHUB_REPO      = os.environ.get("GITHUB_REPOSITORY", "")

# Video dimensions (YouTube Shorts = 9:16)
WIDTH, HEIGHT = 1080, 1920
SLIDE_DURATION = 4          # seconds each slide stays on screen
FONT_SIZE_TITLE = 68
FONT_SIZE_BODY  = 52
FONT_SIZE_SMALL = 38
OUTPUT_VIDEO    = "output_video.mp4"
THUMBNAIL_FILE  = "thumbnail.png"
FRAMES_DIR      = Path("frames")
AUDIO_DIR       = Path("audio_clips")

# ── Niche Topics ──────────────────────────────────────────────
TOPICS = [
    "psychology facts in Hindi English mix",
    "space universe secrets facts Hinglish",
    "weird world amazing facts Hinglish",
    "human brain facts shocking Hinglish",
    "science facts mind blowing Hindi",
    "ancient history mysterious facts Hinglish",
    "animal facts amazing shocking Hindi English",
    "quantum physics simple facts Hinglish",
]

# ── Fallback Hardcoded Facts ──────────────────────────────────
FALLBACK_FACTS = [
    {
        "title": "🧠 Psychology Ka Kamaal!",
        "fact": "Kya aap jaante hain? Jab aap kisi cheez ke baare mein bahut zyada sochte hain, toh aapka brain usse reality maan leta hai. Isliye positive sochna scientifically proven hai!",
        "hook": "Yeh sun ke aap hairan ho jayenge...",
        "category": "Psychology"
    },
    {
        "title": "🌌 Space Ka Raaz!",
        "fact": "Universe mein itare stars hain ki agar aap ek second mein ek star count karein, toh 3000 saal lagenge! Aur hum sochte hain hum akele hain...",
        "hook": "Space ka yeh secret aapki soch badal dega!",
        "category": "Space"
    },
    {
        "title": "😴 Neend Ka Jaadu!",
        "fact": "Aapka brain neend mein bhi active rehta hai. Actually, REM sleep mein aapka brain JAAG-te waqt se bhi zyada kaam karta hai. Isliye sapne itane real lagte hain!",
        "hook": "Neend ke baare mein yeh baat jaankar aap hairan ho jayenge!",
        "category": "Psychology"
    },
    {
        "title": "🔢 Numbers Ka Jaadu!",
        "fact": "Duniya mein jitni raat sand grains hain, unse zyada synaptic connections hain aapke ek brain mein! Aapka dimaag literally universe se bhi complex hai.",
        "hook": "Yeh fact sun ke aap apna dimaag pakad lenge!",
        "category": "Science"
    },
    {
        "title": "🐙 Animals Ka Ajeeb Raaz!",
        "fact": "Octopus ke 3 dil hote hain! Aur jab woh swim karta hai toh 2 dil band ho jaate hain. Isliye octopus ko swimming pasand nahi - woh crawling prefer karta hai!",
        "hook": "Yeh jaanwar itana ajeeb hai ki aap believe nahi karenge!",
        "category": "Animals"
    },
    {
        "title": "⏰ Time Ka Illusion!",
        "fact": "Aapka brain past ko record nahi karta - woh usse reconstruct karta hai har baar jab aap yaad karte hain. Matlab aapki memories actually fake ho sakti hain without you knowing!",
        "hook": "Aapki yaadein aapko dhoka de rahi hain!",
        "category": "Psychology"
    },
    {
        "title": "🌊 Samundar Ka Raaz!",
        "fact": "Abhi tak insaan ne sirf 5% samundar explore kiya hai. Baaki 95% mein kya hai - hum nahi jaante! Shayad aliens nahi, lekin zarur kuch ajeeb cheezein zarur hain.",
        "hook": "Samundar ki gehraai mein kya chupta hai?",
        "category": "Science"
    },
]

# ── Color Palettes ────────────────────────────────────────────
PALETTES = [
    {"bg": (10, 10, 40),    "accent": (100, 200, 255), "text": (255, 255, 255), "glow": (50, 100, 200)},
    {"bg": (20, 5, 35),     "accent": (200, 100, 255), "text": (255, 255, 255), "glow": (150, 50, 200)},
    {"bg": (5, 30, 20),     "accent": (100, 255, 150), "text": (255, 255, 255), "glow": (50, 200, 100)},
    {"bg": (40, 10, 5),     "accent": (255, 150, 50),  "text": (255, 255, 255), "glow": (200, 100, 30)},
    {"bg": (5, 20, 40),     "accent": (50, 200, 255),  "text": (255, 255, 255), "glow": (30, 150, 200)},
]

# ══════════════════════════════════════════════════════════════
#  STEP 1 — FETCH FACT (Tavily → Groq → Fallback)
# ══════════════════════════════════════════════════════════════
def fetch_fact_tavily():
    """Search for a fresh fact using Tavily."""
    if not TAVILY_API_KEY:
        return None
    try:
        topic = random.choice(TOPICS)
        log.info(f"Tavily search: '{topic}'")
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": topic, "max_results": 3,
                  "search_depth": "basic", "include_answer": True},
            timeout=20
        )
        data = resp.json()
        # Combine answer + top result snippets
        parts = []
        if data.get("answer"):
            parts.append(data["answer"])
        for r in data.get("results", [])[:2]:
            if r.get("content"):
                parts.append(r["content"][:400])
        raw = " | ".join(parts)
        log.info("Tavily returned content ✅")
        return raw if len(raw) > 50 else None
    except Exception as e:
        log.warning(f"Tavily failed: {e}")
        return None


def generate_fact_with_groq(raw_context) -> dict:
    """Use Groq (LLaMA) to generate a structured Hinglish fact."""
    client = Groq(api_key=GROQ_API_KEY)

    if raw_context:
        system = """You are a viral YouTube Shorts script writer for 'Ajeebology Shorts' channel.
Channel niche: Psychology Facts, Space Secrets, Weird World Facts.
Language: Hinglish (Hindi + English mix) - conversational and engaging.
You must return ONLY valid JSON, no extra text."""

        user = f"""Given this raw information:
{raw_context[:800]}

Create an engaging YouTube Shorts fact script. Return ONLY this JSON:
{{
  "title": "emoji + catchy Hinglish title (max 8 words)",
  "hook": "first line to grab attention in 1-2 sentences (Hinglish)",
  "fact": "main fact explained in 3-5 engaging Hinglish sentences, conversational tone",
  "wrapup": "closing line encouraging to follow/subscribe (Hinglish)",
  "category": "Psychology/Space/Science/Animals/History"
}}"""
    else:
        system = """You are a viral YouTube Shorts script writer for 'Ajeebology Shorts'.
Channel: Psychology Facts, Space Secrets, Weird World Facts.
Language: Hinglish (Hindi + English mix).
Return ONLY valid JSON, no extra text."""

        user = """Create an original mind-blowing fact script. Return ONLY this JSON:
{
  "title": "emoji + catchy Hinglish title (max 8 words)",
  "hook": "attention-grabbing first line 1-2 sentences (Hinglish)",
  "fact": "main fact 3-5 engaging Hinglish sentences, conversational tone",
  "wrapup": "closing subscribe/follow encouragement (Hinglish)",
  "category": "Psychology/Space/Science/Animals/History"
}"""

    log.info("Calling Groq LLaMA to generate fact script...")
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": system},
                      {"role": "user",   "content": user}],
            temperature=0.85,
            max_tokens=600,
        )
        content = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        content = content.replace("```json", "").replace("```", "").strip()
        fact_data = json.loads(content)
        log.info(f"Groq generated fact: {fact_data.get('title', 'N/A')} ✅")
        return fact_data
    except Exception as e:
        log.warning(f"Groq failed: {e} — using fallback fact")
        return random.choice(FALLBACK_FACTS)


def get_todays_fact() -> dict:
    """Main fact pipeline: Tavily → Groq → Hardcoded fallback."""
    raw = fetch_fact_tavily()
    try:
        fact = generate_fact_with_groq(raw)
        # Validate required keys
        required = {"title", "hook", "fact", "category"}
        if not required.issubset(fact.keys()):
            raise ValueError("Missing keys in Groq response")
        return fact
    except Exception as e:
        log.warning(f"Fact generation failed: {e} — using hardcoded fallback")
        return random.choice(FALLBACK_FACTS)


# ══════════════════════════════════════════════════════════════
#  STEP 2 — TEXT TO SPEECH
# ══════════════════════════════════════════════════════════════
def generate_voiceover(fact: dict) -> list[Path]:
    """Generate TTS audio clips for each slide."""
    AUDIO_DIR.mkdir(exist_ok=True)
    clips = []

    # Slide texts (intro, fact, outro)
    slide_texts = [
        f"Ajeebology Shorts par aapka swagat hai! {fact['hook']}",
        fact["fact"],
        fact.get("wrapup", "Aisa hi aur content dekhne ke liye Subscribe karein! Ajeebology Shorts ke saath rahen!"),
    ]

    for i, text in enumerate(slide_texts):
        path = AUDIO_DIR / f"clip_{i}.mp3"
        log.info(f"Generating TTS clip {i+1}/{len(slide_texts)}...")
        try:
            tts = gTTS(text=text, lang="hi", slow=False)
            tts.save(str(path))
            clips.append(path)
        except Exception as e:
            log.error(f"TTS failed for clip {i}: {e}")
            # Create silent placeholder using ffmpeg
            subprocess.run([
                "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                "-t", str(SLIDE_DURATION), "-q:a", "9", "-acodec", "libmp3lame",
                str(path), "-y"
            ], capture_output=True)
            clips.append(path)

    return clips


def get_audio_duration(path: Path) -> float:
    """Get duration of an audio file using ffprobe."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "json", str(path)
        ], capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return float(SLIDE_DURATION)


# ══════════════════════════════════════════════════════════════
#  STEP 3 — CREATE SLIDE IMAGES
# ══════════════════════════════════════════════════════════════
def load_font(size: int):
    """Load a font, falling back to default if not available."""
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", size)
        except Exception:
            return ImageFont.load_default()


def draw_stars(draw: ImageDraw, count: int = 120):
    """Draw random stars on background."""
    for _ in range(count):
        x = random.randint(0, WIDTH)
        y = random.randint(0, HEIGHT)
        r = random.randint(1, 3)
        alpha = random.randint(100, 255)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(255, 255, 255, alpha))


def draw_gradient_bg(img: Image.Image, palette: dict):
    """Draw a radial-ish gradient background."""
    draw = ImageDraw.Draw(img, "RGBA")
    bg = palette["bg"]
    glow = palette["glow"]
    # Top-to-bottom gradient by drawing horizontal bands
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(bg[0] + (glow[0] - bg[0]) * ratio * 0.4)
        g = int(bg[1] + (glow[1] - bg[1]) * ratio * 0.4)
        b = int(bg[2] + (glow[2] - bg[2]) * ratio * 0.4)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b, 255))
    # Center glow
    cx, cy = WIDTH // 2, HEIGHT // 2
    for radius in range(600, 0, -20):
        alpha = int(30 * (1 - radius / 600))
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*glow, alpha)
        )
    draw_stars(draw)


def wrap_text(text: str, font, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    for word in words:
        test = f"{current} {word}".strip()
        bbox = dummy_draw.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_with_shadow(draw, pos, text, font, color, shadow_color=(0,0,0), shadow_offset=3):
    """Draw text with drop shadow."""
    x, y = pos
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=color)


def create_slide(
    slide_index: int,
    total_slides: int,
    title: str,
    body_text: str,
    palette: dict,
    channel_name: str = "Ajeebology Shorts",
    is_thumbnail: bool = False
) -> Image.Image:
    """Create a single 1080×1920 slide image."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color=palette["bg"])
    draw_gradient_bg(img, palette)
    draw = ImageDraw.Draw(img)

    accent = palette["accent"]
    text_color = palette["text"]
    pad = 60

    # ── Channel watermark (top) ───────────────────────────────
    font_sm = load_font(FONT_SIZE_SMALL)
    draw.text((pad, 60), f"🎬 {channel_name}", font=font_sm, fill=accent)
    draw.line([(pad, 125), (WIDTH - pad, 125)], fill=accent, width=2)

    # ── Slide counter dots ────────────────────────────────────
    dot_y = 155
    dot_spacing = 28
    total_width = (total_slides - 1) * dot_spacing
    start_x = (WIDTH - total_width) // 2
    for i in range(total_slides):
        x = start_x + i * dot_spacing
        r = 10 if i == slide_index else 6
        color = accent if i == slide_index else (100, 100, 100)
        draw.ellipse([x-r, dot_y-r, x+r, dot_y+r], fill=color)

    # ── Category badge ────────────────────────────────────────
    font_badge = load_font(34)
    badge_text = f"  🧠 AJEEBOLOGY  "
    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = bbox[2] - bbox[0] + 20
    bx = (WIDTH - bw) // 2
    by = 200
    draw.rounded_rectangle([bx, by, bx+bw, by+50], radius=25, fill=accent)
    draw.text((bx + 10, by + 8), badge_text, font=font_badge, fill=palette["bg"])

    # ── Main title ────────────────────────────────────────────
    font_title = load_font(FONT_SIZE_TITLE)
    title_lines = wrap_text(title, font_title, WIDTH - pad * 2)
    title_y = 300
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        lw = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((WIDTH - lw) // 2, title_y), line, font_title, text_color)
        title_y += bbox[3] - bbox[1] + 12

    # ── Decorative divider ────────────────────────────────────
    div_y = title_y + 20
    draw.line([(pad * 2, div_y), (WIDTH - pad * 2, div_y)], fill=accent, width=3)
    div_y += 30

    # ── Body text ─────────────────────────────────────────────
    font_body = load_font(FONT_SIZE_BODY)
    body_lines = wrap_text(body_text, font_body, WIDTH - pad * 2)
    body_y = div_y + 10
    for line in body_lines:
        bbox = draw.textbbox((0, 0), line, font=font_body)
        lw = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((WIDTH - lw) // 2, body_y), line, font_body, text_color)
        body_y += bbox[3] - bbox[1] + 14

    # ── Subscribe CTA (bottom) ────────────────────────────────
    cta_y = HEIGHT - 260
    draw.line([(pad, cta_y - 20), (WIDTH - pad, cta_y - 20)], fill=accent, width=2)
    font_cta = load_font(42)
    cta_lines = ["🔔 Subscribe Karen!", "Daily 5:00 PM PKT pe naya Short!"]
    for line in cta_lines:
        bbox = draw.textbbox((0, 0), line, font=font_cta)
        lw = bbox[2] - bbox[0]
        draw.text(((WIDTH - lw) // 2, cta_y), line, font=font_cta, fill=accent)
        cta_y += 55

    # ── Bottom channel name ───────────────────────────────────
    font_footer = load_font(36)
    footer = "AjeebologyShorts"
    bbox = draw.textbbox((0, 0), footer, font=font_footer)
    fw = bbox[2] - bbox[0]
    draw.text(((WIDTH - fw) // 2, HEIGHT - 90), footer, font=font_footer,
              fill=(150, 150, 150))

    return img


def create_all_slides(fact: dict) -> tuple[list[Path], Image.Image]:
    """Create all slide images and return their paths + thumbnail."""
    FRAMES_DIR.mkdir(exist_ok=True)
    palette = random.choice(PALETTES)

    slides_data = [
        {
            "title": fact["title"],
            "body": fact.get("hook", "Yeh jaankar aap hairan ho jayenge!"),
        },
        {
            "title": f"🔍 {fact.get('category', 'Ajeeb Fact')}",
            "body": fact["fact"],
        },
        {
            "title": "✅ Aur Jaano!",
            "body": fact.get("wrapup", "Aisa hi amazing content ke liye channel subscribe zarur karein! 🔔"),
        },
    ]

    slide_paths = []
    thumbnail = None

    for i, slide in enumerate(slides_data):
        log.info(f"Creating slide {i+1}/{len(slides_data)}...")
        img = create_slide(
            slide_index=i,
            total_slides=len(slides_data),
            title=slide["title"],
            body_text=slide["body"],
            palette=palette,
        )
        path = FRAMES_DIR / f"slide_{i:03d}.png"
        img.save(str(path), "PNG")
        slide_paths.append(path)
        if i == 0:
            thumbnail = img  # First slide = thumbnail

    return slide_paths, thumbnail


# ══════════════════════════════════════════════════════════════
#  STEP 4 — ASSEMBLE VIDEO WITH FFMPEG
# ══════════════════════════════════════════════════════════════
def build_video(slide_paths: list[Path], audio_clips: list[Path]) -> bool:
    """Assemble slides + audio into a final MP4 using FFmpeg."""
    log.info("Assembling video with FFmpeg...")

    # Get durations for each audio clip
    durations = [get_audio_duration(a) for a in audio_clips]
    log.info(f"Audio durations: {[f'{d:.1f}s' for d in durations]}")

    # Build FFmpeg input args: each slide shown for its audio duration
    inputs = []
    for slide, dur in zip(slide_paths, durations):
        inputs += ["-loop", "1", "-t", str(dur), "-i", str(slide)]

    audio_inputs = []
for a in audio_clips:
    audio_inputs += ["-i", str(a)]

    n = len(slide_paths)

    # Filter complex: scale all slides, concat video, concat audio
    filter_parts = []
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}];"
        )

    video_concat = "".join(f"[v{i}]" for i in range(n))
    audio_offset = n
    audio_concat = "".join(f"[{audio_offset + i}:a]" for i in range(len(audio_clips)))

    filter_parts.append(f"{video_concat}concat=n={n}:v=1:a=0[vout];")
    filter_parts.append(f"{audio_concat}concat=n={len(audio_clips)}:v=0:a=1[aout]")

    filter_complex = "".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + audio_inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-shortest",
            "-movflags", "+faststart",
            OUTPUT_VIDEO
        ]
    )

    log.info("Running FFmpeg command...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        log.error(f"FFmpeg failed:\n{result.stderr[-2000:]}")
        return False

    size_mb = Path(OUTPUT_VIDEO).stat().st_size / (1024 * 1024)
    log.info(f"Video created: {OUTPUT_VIDEO} ({size_mb:.1f} MB) ✅")
    return True


# ══════════════════════════════════════════════════════════════
#  STEP 5 — SEND TO TELEGRAM
# ══════════════════════════════════════════════════════════════
def build_artifact_url() -> str:
    """Build GitHub Actions artifact URL."""
    if GITHUB_REPO and GITHUB_RUN_ID:
        return (
            f"https://github.com/{GITHUB_REPO}/actions/runs/{GITHUB_RUN_ID}"
        )
    return "https://github.com (Artifact URL unavailable)"


def send_telegram_message(text: str):
    """Send a text message to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=30)
    if not resp.ok:
        log.warning(f"Telegram message failed: {resp.text}")
    return resp.ok


def send_telegram_video(video_path: str, caption: str) -> bool:
    """Send video file to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    log.info("Sending video to Telegram...")
    try:
        with open(video_path, "rb") as vf:
            resp = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
                files={"video": vf},
                timeout=120,
            )
        if resp.ok:
            log.info("Video sent to Telegram ✅")
            return True
        else:
            log.warning(f"Telegram video failed: {resp.text}")
            return False
    except Exception as e:
        log.error(f"Telegram video exception: {e}")
        return False


def send_telegram_photo(photo_path: str, caption: str) -> bool:
    """Send thumbnail photo to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=60,
            )
        return resp.ok
    except Exception as e:
        log.warning(f"Telegram photo failed: {e}")
        return False


def notify_telegram(fact: dict, video_ok: bool):
    """Send notification + video/thumbnail to Telegram."""
    artifact_url = build_artifact_url()
    date_str = datetime.now().strftime("%d %b %Y")

    if video_ok:
        caption = (
            f"🎬 <b>Ajeebology Shorts</b> — Daily Short\n"
            f"📅 {date_str}\n\n"
            f"<b>{fact['title']}</b>\n\n"
            f"📂 <b>Download Video (GitHub Artifact):</b>\n"
            f"<a href='{artifact_url}'>👉 Click Here to Download</a>\n\n"
            f"#AjeebologyShorts #Facts #Psychology #Space"
        )
        # Try sending video directly
        size_mb = Path(OUTPUT_VIDEO).stat().st_size / (1024 * 1024) if Path(OUTPUT_VIDEO).exists() else 99
        if size_mb < 48:  # Telegram bot limit ~50MB
            sent = send_telegram_video(OUTPUT_VIDEO, caption)
        else:
            sent = False
            log.info("Video too large for Telegram direct send, sending thumbnail instead.")

        if not sent:
            # Fallback: send thumbnail + link
            send_telegram_photo(THUMBNAIL_FILE, caption)

        # Also send a text message with artifact link
        summary_msg = (
            f"✅ <b>Video Generated Successfully!</b>\n\n"
            f"🎬 <b>Title:</b> {fact['title']}\n"
            f"🧠 <b>Category:</b> {fact.get('category', 'Ajeeb')}\n"
            f"📅 <b>Date:</b> {date_str}\n\n"
            f"📥 <b>GitHub Artifact (Download Video):</b>\n"
            f"<a href='{artifact_url}'>🔗 {artifact_url}</a>\n\n"
            f"<i>Artifact available for 90 days after workflow run.</i>"
        )
        send_telegram_message(summary_msg)
    else:
        err_msg = (
            f"❌ <b>Video Generation FAILED</b>\n"
            f"📅 {date_str}\n\n"
            f"Topic: {fact.get('title', 'Unknown')}\n"
            f"Check GitHub Actions logs:\n"
            f"<a href='{artifact_url}'>🔗 View Run</a>"
        )
        send_telegram_message(err_msg)


# ══════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ══════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("  AJEEBOLOGY SHORTS AGENT STARTED")
    log.info("=" * 60)

    # 1. Get today's fact
    log.info("STEP 1: Fetching today's fact...")
    fact = get_todays_fact()
    log.info(f"Fact ready: {fact['title']}")

    # 2. Generate voiceover
    log.info("STEP 2: Generating voiceover...")
    audio_clips = generate_voiceover(fact)

    # 3. Create slides
    log.info("STEP 3: Creating slide images...")
    slide_paths, thumbnail = create_all_slides(fact)

    # 4. Save thumbnail
    if thumbnail:
        thumbnail.save(THUMBNAIL_FILE, "PNG")
        log.info(f"Thumbnail saved: {THUMBNAIL_FILE} ✅")

    # 5. Build video
    log.info("STEP 4: Building video...")
    video_ok = build_video(slide_paths, audio_clips)

    # 6. Notify Telegram
    log.info("STEP 5: Sending Telegram notification...")
    notify_telegram(fact, video_ok)

    # 7. Summary
    log.info("=" * 60)
    if video_ok:
        log.info("✅ PIPELINE COMPLETE — Video ready!")
    else:
        log.error("❌ PIPELINE FAILED — Check logs above.")
        sys.exit(1)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
