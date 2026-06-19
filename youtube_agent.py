import os
import sys
import json
import random
import logging
import requests
import subprocess
import asyncio
import math
from pathlib import Path
from datetime import datetime

from groq import Groq
from PIL import Image, ImageDraw, ImageFont

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

WIDTH, HEIGHT  = 720, 1280
FPS            = 24
OUTPUT_VIDEO   = "output_video.mp4"
THUMBNAIL_FILE = "thumbnail.png"
FRAMES_DIR     = Path("frames")
AUDIO_DIR      = Path("audio_clips")
MUSIC_FILE     = "bg_music.mp3"
FONT_PATH      = "NotoSans.ttf"
FONT_BOLD_PATH = "NotoSans-Bold.ttf"

# Brand colors matching Ajeebology logo
BRAND = {
    "bg_dark":   (10, 5, 25),
    "bg_mid":    (20, 10, 45),
    "purple1":   (120, 60, 220),
    "purple2":   (160, 80, 255),
    "cyan":      (80, 200, 255),
    "white":     (255, 255, 255),
    "star":      (200, 180, 255),
    "glow_p":    (100, 40, 180),
    "glow_c":    (40, 150, 200),
}

TOPICS = [
    "psychology facts mind blowing",
    "space universe secrets amazing",
    "weird world facts shocking",
    "human brain facts incredible",
    "animal facts surprising",
    "science facts unbelievable",
    "ancient history mysterious facts",
]

FALLBACK_FACTS = [
    {
        "title": "Dimaag Ka Kamaal",
        "fact": "Jab aap kisi cheez ke baare mein bahut zyada sochte hain toh aapka brain usse reality maan leta hai. Isliye positive sochna scientifically proven hai!",
        "hook": "Yeh sun ke aap hairan ho jayenge...",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Psychology",
        "english_title": "Mind Blowing Psychology Fact That Will Shock You",
        "description": "Amazing psychology fact about how your brain works. Subscribe for daily facts!",
        "tags": "psychology,facts,brain,mindblowing,shorts,viral,hindi,knowledge,science,amazing"
    },
    {
        "title": "Space Ka Raaz",
        "fact": "Universe mein itne stars hain ki agar aap ek second mein ek star count karein toh 3000 saal lagenge! Aur hum sochte hain hum akele hain...",
        "hook": "Space ka yeh secret aapki soch badal dega!",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Space",
        "english_title": "Space Secret That Will Blow Your Mind",
        "description": "Incredible space fact about our universe. Subscribe for daily facts!",
        "tags": "space,universe,facts,stars,mindblowing,shorts,viral,science,amazing,knowledge"
    },
]


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
                log.info("Font downloaded: " + fname)
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
# FACT GENERATION
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


def generate_fact_with_groq(raw_context):
    client = Groq(api_key=GROQ_API_KEY)
    base_json = (
        "{\n"
        "  \"title\": \"short catchy Hinglish title max 5 words NO emoji\",\n"
        "  \"hook\": \"1 sentence attention grabber Hinglish\",\n"
        "  \"fact\": \"main fact 3-4 sentences Hinglish\",\n"
        "  \"wrapup\": \"subscribe encouragement 1 sentence\",\n"
        "  \"category\": \"Psychology or Space or Science or Animals or History\",\n"
        "  \"english_title\": \"SEO YouTube title English max 60 chars\",\n"
        "  \"description\": \"120 word English YouTube description\",\n"
        "  \"tags\": \"tag1,tag2,tag3,tag4,tag5,tag6,tag7,tag8,tag9,tag10\"\n"
        "}"
    )
    if raw_context:
        system = "YouTube Shorts script writer for Ajeebology Shorts. Hinglish language. Return ONLY valid JSON no markdown."
        user = "Info: " + str(raw_context[:600]) + "\n\nReturn ONLY this JSON:\n" + base_json
    else:
        system = "YouTube Shorts script writer for Ajeebology Shorts. Hinglish language. Return ONLY valid JSON no markdown."
        user = "Create mind-blowing fact. Return ONLY this JSON:\n" + base_json

    try:
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            temperature=0.85,
            max_tokens=700,
        )
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        fact_data = json.loads(content)
        log.info("Fact generated: " + fact_data.get("title", ""))
        return fact_data
    except Exception as e:
        log.warning("Groq failed: " + str(e))
        return random.choice(FALLBACK_FACTS)


def get_todays_fact():
    raw = fetch_fact_tavily()
    try:
        fact = generate_fact_with_groq(raw)
        if "title" not in fact or "fact" not in fact:
            raise ValueError("Missing keys")
        return fact
    except Exception as e:
        log.warning("Using fallback: " + str(e))
        return random.choice(FALLBACK_FACTS)


# ══════════════════════════════════════════════════════
# MALE VOICE TTS
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


def generate_voiceover(fact):
    AUDIO_DIR.mkdir(exist_ok=True)
    clips = []
    slide_texts = [
        "Ajeebology Shorts par aapka swagat hai! " + fact["hook"],
        fact["fact"],
        fact.get("wrapup", "Subscribe karein aur daily naye facts paayein!"),
    ]
    for i, text in enumerate(slide_texts):
        path = AUDIO_DIR / ("clip_" + str(i) + ".mp3")
        log.info("Generating TTS clip " + str(i + 1))
        success = asyncio.run(generate_tts_async(text, path))
        if not success or not path.exists():
            try:
                from gtts import gTTS
                tts = gTTS(text=text, lang="hi", slow=False, tld="co.uk")
                tts.save(str(path))
            except Exception as e:
                log.error("All TTS failed: " + str(e))
                subprocess.run([
                    "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", "5", "-q:a", "9", "-acodec", "libmp3lame",
                    str(path), "-y"
                ], capture_output=True)
        clips.append(path)
    return clips


# ══════════════════════════════════════════════════════
# BACKGROUND MUSIC
# ══════════════════════════════════════════════════════
def download_free_music():
    urls = [
        "https://cdn.pixabay.com/download/audio/2023/06/19/audio_0babde2a4c.mp3",
        "https://cdn.pixabay.com/download/audio/2022/10/25/audio_913fb96e1f.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb4bae0c2.mp3",
    ]
    for url in urls:
        try:
            log.info("Downloading music...")
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(MUSIC_FILE, "wb") as f:
                    f.write(r.content)
                log.info("Music downloaded OK")
                return True
        except Exception as e:
            log.warning("Music URL failed: " + str(e))
            continue
    log.warning("All music downloads failed")
    return False


# ══════════════════════════════════════════════════════
# DRAWING HELPERS
# ══════════════════════════════════════════════════════
def draw_gradient(img):
    draw = ImageDraw.Draw(img)
    bg1 = BRAND["bg_dark"]
    bg2 = BRAND["bg_mid"]
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(bg1[0] + (bg2[0] - bg1[0]) * t)
        g = int(bg1[1] + (bg2[1] - bg1[1]) * t)
        b = int(bg1[2] + (bg2[2] - bg1[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))


def draw_stars_animated(draw, frame, count=120):
    random.seed(42)
    for _ in range(count):
        x = random.randint(0, WIDTH)
        y = random.randint(0, HEIGHT)
        base_r = random.randint(1, 3)
        # Twinkle effect
        twinkle = abs(math.sin(frame * 0.1 + random.random() * 6))
        brightness = int(100 + 155 * twinkle)
        r = max(1, int(base_r * (0.5 + twinkle * 0.5)))
        draw.ellipse([x-r, y-r, x+r, y+r],
                     fill=(brightness, int(brightness*0.8), 255))
    random.seed()


def draw_glowing_circle(draw, cx, cy, radius, color, alpha_max=60):
    for i in range(5):
        r = radius + i * 15
        a = max(0, alpha_max - i * 12)
        for _ in range(3):
            draw.ellipse(
                [cx-r, cy-r, cx+r, cy+r],
                outline=(*color, a),
                width=2
            )


def draw_particles(draw, frame, count=25):
    random.seed(frame // 3)
    for i in range(count):
        angle = (frame * 2 + i * 30) % 360
        rad = math.radians(angle)
        dist = 80 + (i % 5) * 40
        cx = WIDTH // 2 + int(dist * math.cos(rad))
        cy = HEIGHT // 3 + int(dist * math.sin(rad) * 0.5)
        size = random.randint(2, 5)
        colors = [BRAND["purple2"], BRAND["cyan"], BRAND["white"]]
        color = colors[i % 3]
        draw.ellipse([cx-size, cy-size, cx+size, cy+size], fill=color)
    random.seed()


def draw_circuit_lines(draw, alpha=30):
    positions = [
        [(0, 200), (150, 200), (150, 350), (300, 350)],
        [(WIDTH, 400), (WIDTH-120, 400), (WIDTH-120, 550), (WIDTH-250, 550)],
        [(0, 900), (100, 900), (100, 800), (200, 800)],
        [(WIDTH, 1000), (WIDTH-150, 1000), (WIDTH-150, 1100), (WIDTH-80, 1100)],
    ]
    color = BRAND["purple1"]
    for path in positions:
        for j in range(len(path) - 1):
            draw.line([path[j], path[j+1]], fill=color, width=1)
            end = path[j+1]
            draw.ellipse([end[0]-4, end[1]-4, end[0]+4, end[1]+4], fill=BRAND["cyan"])


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""
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
def draw_glowing_text(draw, pos, text, font, color, glow_color, glow_range=1): # Changed glow_range to 1 for crisp outline
    x, y = pos
    # Soft text stroke/shadow
    for dx in range(-glow_range, glow_range + 1):
        for dy in range(-glow_range, glow_range + 1):
            if dx != 0 or dy != 0:
                draw.text((x+dx, y+dy), text, font=font, fill=glow_color)
    draw.text((x, y), text, font=font, fill=color)



# ══════════════════════════════════════════════════════
# ANIMATED FRAME CREATION
# ══════════════════════════════════════════════════════

def get_text_width(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return len(text) * 20, 30


def create_animated_frame(
    frame_num,
    total_frames,
    slide_index,
    total_slides,
    title,
    body_text,
    category,
    progress_text=""
):
    img = Image.new("RGB", (WIDTH, HEIGHT), color=BRAND["bg_dark"])
    draw_gradient(img)
    draw = ImageDraw.Draw(img)

    t = frame_num / max(total_frames - 1, 1)
    pad = 40

    # Circuit lines
    draw_circuit_lines(draw)

    # Animated stars
    draw_stars_animated(draw, frame_num)

    # Glowing orbs (pulsing)
    pulse = 0.7 + 0.3 * math.sin(frame_num * 0.15)
    cx, cy = WIDTH // 2, HEIGHT // 3

    for radius, color in [(180, BRAND["glow_p"]), (120, BRAND["glow_c"])]:
        r = int(radius * pulse)
        for thickness in range(4, 0, -1):
            alpha_val = int(15 * thickness * pulse)
            overlay_color = (
                min(255, color[0] + alpha_val),
                min(255, color[1] + alpha_val),
                min(255, color[2] + alpha_val),
            )
            draw.ellipse(
                [cx-r-thickness*3, cy-r-thickness*3,
                 cx+r+thickness*3, cy+r+thickness*3],
                outline=overlay_color, width=1
            )

    # Particles
    draw_particles(draw, frame_num)

    # TOP BAR
    draw.rectangle([0, 0, WIDTH, 85], fill=(5, 2, 15))
    draw.line([(0, 85), (WIDTH, 85)], fill=BRAND["cyan"], width=2)

    font_top = load_font(26, bold=True)
    draw.text((pad, 25), "AJEEBOLOGY SHORTS", font=font_top, fill=BRAND["cyan"])

    # Live dot animation
    dot_alpha = int(255 * abs(math.sin(frame_num * 0.2)))
    dot_color = (dot_alpha, 255 - dot_alpha // 2, 100)
    draw.ellipse([WIDTH-60, 32, WIDTH-40, 52], fill=dot_color)
    font_live = load_font(20)
    draw.text((WIDTH-35, 32), "LIVE", font=font_live, fill=BRAND["white"])

    # Progress dots
    dot_y = 110
    spacing = 28
    total_w = (total_slides - 1) * spacing
    start_x = (WIDTH - total_w) // 2
    for i in range(total_slides):
        x = start_x + i * spacing
        if i == slide_index:
            pulse_r = int(10 + 3 * math.sin(frame_num * 0.2))
            draw.ellipse([x-pulse_r, dot_y-pulse_r, x+pulse_r, dot_y+pulse_r],
                         fill=BRAND["cyan"])
            draw.ellipse([x-6, dot_y-6, x+6, dot_y+6], fill=BRAND["white"])
        else:
            draw.ellipse([x-5, dot_y-5, x+5, dot_y+5], fill=(60, 40, 100))

    # Category badge
    font_badge = load_font(24, bold=True)
    cat_icons = {
        "Psychology": "BRAIN",
        "Space": "SPACE",
        "Science": "SCIENCE",
        "Animals": "NATURE",
        "History": "HISTORY",
    }
    badge_text = "[ " + cat_icons.get(category, "FACTS") + " ]"
    bw, bh = get_text_width(draw, badge_text, font_badge)
    bx = (WIDTH - bw) // 2
    by = 140
    draw.rounded_rectangle([bx-15, by-8, bx+bw+15, by+bh+8],
                            radius=15, fill=BRAND["purple1"])
    draw.text((bx, by), badge_text, font=font_badge, fill=BRAND["cyan"])

    # TITLE with slide-in animation
    font_title = load_font(54, bold=True)
    title_lines = wrap_text(title, font_title, WIDTH - pad*2)
    title_y = 210

    slide_offset = max(0, int(50 * (1 - t * 3))) if t < 0.33 else 0
    title_alpha = min(1.0, t * 4)

    for line in title_lines:
        lw, lh = get_text_width(draw, line, font_title)
        tx = (WIDTH - lw) // 2
        ty = title_y + slide_offset
        glow_color = (
            int(BRAND["purple2"][0] * title_alpha),
            int(BRAND["purple2"][1] * title_alpha),
            int(BRAND["purple2"][2] * title_alpha),
        )
        text_color = (
            int(BRAND["white"][0] * title_alpha),
            int(BRAND["white"][1] * title_alpha),
            int(BRAND["white"][2] * title_alpha),
        )
        draw_glowing_text(draw, (tx, ty), line, font_title, text_color, glow_color)
        title_y += lh + 8

    # Animated divider line
    div_y = title_y + 20
    line_progress = min(1.0, t * 2)
    line_end = int(pad + (WIDTH - pad*2) * line_progress)
    if line_end > pad:
        draw.line([(pad, div_y), (line_end, div_y)],
                  fill=BRAND["cyan"], width=3)
        draw.ellipse([line_end-5, div_y-5, line_end+5, div_y+5],
                     fill=BRAND["cyan"])

    # BODY TEXT BOX with fade-in
    font_body = load_font(36)
    body_lines = wrap_text(body_text, font_body, WIDTH - pad*2 - 30)
    body_height = len(body_lines) * 52 + 40
    box_top = div_y + 30

    body_alpha = max(0, min(1.0, (t - 0.2) * 3))

    # Glowing border box
    box_color = (
        int(BRAND["purple1"][0] * body_alpha * 0.5),
        int(BRAND["purple1"][1] * body_alpha * 0.5),
        int(BRAND["purple1"][2] * body_alpha * 0.5),
    )
    draw.rounded_rectangle(
        [pad-5, box_top-5, WIDTH-pad+5, box_top+body_height+5],
        radius=20, fill=box_color
    )
    draw.rounded_rectangle(
        [pad, box_top, WIDTH-pad, box_top+body_height],
        radius=18, fill=(8, 4, 20)
    )
    # Cyan border with pulse
    border_pulse = int(180 + 75 * math.sin(frame_num * 0.15))
    draw.rounded_rectangle(
        [pad, box_top, WIDTH-pad, box_top+body_height],
        radius=18, outline=(0, border_pulse, 255), width=2
    )

    by2 = box_top + 20
    for line in body_lines:
        lw, lh = get_text_width(draw, line, font_body)
        tx = (WIDTH - lw) // 2
        text_col = (
            int(BRAND["white"][0] * body_alpha),
            int(BRAND["white"][1] * body_alpha),
            int(BRAND["white"][2] * body_alpha),
        )
        draw.text((tx, by2), line, font=font_body, fill=text_col)
        by2 += lh + 12

    # Progress bar at bottom of text box
    if t > 0.3:
        bar_y = box_top + body_height + 10
        bar_progress = (t - 0.3) / 0.7
        bar_w = int((WIDTH - pad*2) * bar_progress)
        draw.rectangle([pad, bar_y, pad+bar_w, bar_y+4],
                       fill=BRAND["purple2"])
        draw.rectangle([pad+bar_w-3, bar_y-2, pad+bar_w+3, bar_y+6],
                       fill=BRAND["cyan"])

    # CTA SECTION
    cta_top = HEIGHT - 230
    draw.rectangle([0, cta_top, WIDTH, HEIGHT], fill=(5, 2, 15))
    draw.line([(0, cta_top), (WIDTH, cta_top)],
              fill=BRAND["purple2"], width=3)

    font_cta = load_font(30, bold=True)
    font_sub = load_font(26)

    cta_pulse = int(200 + 55 * abs(math.sin(frame_num * 0.25)))
    cta_color = (cta_pulse, 80, 255)

    cta_items = [
        ("SUBSCRIBE NOW!", font_cta, cta_color),
        ("Daily Facts at 5:00 PM PKT", font_sub, BRAND["white"]),
        ("@AjeebologyShorts", font_sub, BRAND["cyan"]),
    ]
    cy2 = cta_top + 20
    for text_item, font_item, color_item in cta_items:
        lw, lh = get_text_width(draw, text_item, font_item)
        draw.text(((WIDTH-lw)//2, cy2), text_item,
                  font=font_item, fill=color_item)
        cy2 += lh + 18

    return img


# ══════════════════════════════════════════════════════
# SLIDE GENERATION
# ══════════════════════════════════════════════════════
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


def create_slide_frames(
    slide_index, total_slides,
    title, body_text, category,
    duration_secs
):
    total_frames = int(duration_secs * FPS)
    paths = []
    log.info("Creating " + str(total_frames) + " frames for slide " + str(slide_index+1))
    for f in range(total_frames):
        img = create_animated_frame(
            f, total_frames,
            slide_index, total_slides,
            title, body_text, category
        )
        path = FRAMES_DIR / ("s" + str(slide_index) + "_f" + str(f).zfill(4) + ".png")
        img.save(str(path), "PNG")
        paths.append(path)
    return paths


def create_all_slides(fact, audio_clips):
    FRAMES_DIR.mkdir(exist_ok=True)
    category = fact.get("category", "Facts")

    slides_data = [
        {
            "title": fact["title"],
            "body": fact.get("hook", "Yeh jaankar aap hairan ho jayenge!"),
        },
        {
            "title": category + " Fact",
            "body": fact["fact"],
        },
        {
            "title": "Mind Blown!",
            "body": fact.get("wrapup", "Subscribe karein for daily amazing facts!"),
        },
    ]

    all_frame_paths = []
    thumbnail = None

    for i, (slide, audio) in enumerate(zip(slides_data, audio_clips)):
        dur = get_audio_duration(audio)
        frame_paths = create_slide_frames(
            i, len(slides_data),
            slide["title"], slide["body"],
            category, dur
        )
        all_frame_paths.extend(frame_paths)
        if i == 0 and frame_paths:
            thumbnail = Image.open(str(frame_paths[len(frame_paths)//2]))

    return all_frame_paths, thumbnail


# ══════════════════════════════════════════════════════
# VIDEO BUILD
# ══════════════════════════════════════════════════════
def build_video(audio_clips):
    log.info("Building video with FFmpeg...")
    has_music = Path(MUSIC_FILE).exists()

    # Concat all audio clips first
    concat_audio = "concat_audio.mp3"
    audio_list_file = "audio_list.txt"
    with open(audio_list_file, "w") as f:
        for clip in audio_clips:
            f.write("file '" + str(clip.resolve()) + "'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", audio_list_file,
        "-c", "copy", concat_audio
    ], capture_output=True)

    # All frames in order
    frame_pattern = str(FRAMES_DIR / "s%d_f%04d.png")

    # Build using frame sequence
    # Get all frames sorted
    all_frames = sorted(FRAMES_DIR.glob("*.png"))
    frame_list_file = "frame_list.txt"
    with open(frame_list_file, "w") as f:
        for frame in all_frames:
            f.write("file '" + str(frame.resolve()) + "'\n")
            f.write("duration " + str(1.0/FPS) + "\n")

    if has_music:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", frame_list_file,
            "-i", concat_audio,
            "-i", MUSIC_FILE,
            "-filter_complex",
            "[1:a]volume=1.0[voice];[2:a]volume=0.12,aloop=loop=-1:size=2e+09[music];[voice][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
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
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", frame_list_file,
            "-i", concat_audio,
            "-map", "0:v",
            "-map", "1:a",
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
        log.error("FFmpeg error: " + result.stderr[-2000:])
        return False
    log.info("Video built successfully!")
    return True


# ══════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════
def generate_youtube_metadata(fact):
    english_title = fact.get(
        "english_title",
        fact["title"] + " | Ajeebology Shorts"
    )
    date_str = datetime.now().strftime("%d %b %Y")
    description = fact.get("description", "Amazing facts daily on Ajeebology Shorts!")
    description += (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "AJEEBOLOGY SHORTS\n"
        "Daily Facts at 5:00 PM PKT\n"
        "Business: ubaidurehman983@gmail.com\n"
        "Published: " + date_str +
        "\n━━━━━━━━━━━━━━━━━━━━━━"
    )
    raw_tags = fact.get("tags", "")
    if raw_tags:
        tag_list = [t.strip() for t in raw_tags.split(",")]
    else:
        tag_list = [
            "AjeebologyShorts", "facts", "psychology", "space",
            "mindblowing", "didyouknow", "shorts", "viral",
            "hindi", "knowledge", "science", "amazing",
        ]
    hashtags = " ".join(["#" + t.replace(" ", "").replace("#", "")
                         for t in tag_list[:15]])
    return english_title, description, tag_list, hashtags


def send_telegram_message(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=30)
        return resp.ok
    except Exception as e:
        log.error("Telegram message failed: " + str(e))
        return False


def send_telegram_video(caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendVideo"
    try:
        with open(OUTPUT_VIDEO, "rb") as vf:
            resp = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                    "supports_streaming": True,
                },
                files={"video": vf},
                timeout=180,
            )
        return resp.ok
    except Exception as e:
        log.error("Telegram video failed: " + str(e))
        return False


def send_telegram_photo(caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto"
    try:
        with open(THUMBNAIL_FILE, "rb") as f:
            resp = requests.post(
                url,
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                },
                files={"photo": f},
                timeout=60,
            )
        return resp.ok
    except Exception as e:
        log.warning("Telegram photo failed: " + str(e))
        return False


def notify_telegram(fact, video_ok):
    artifact_url = (
        "https://github.com/" + GITHUB_REPO +
        "/actions/runs/" + GITHUB_RUN_ID
        if GITHUB_REPO and GITHUB_RUN_ID
        else "https://github.com"
    )
    date_str = datetime.now().strftime("%d %b %Y %H:%M UTC")
    english_title, description, tag_list, hashtags = generate_youtube_metadata(fact)

    if video_ok:
        video_caption = (
            "🎬 <b>" + english_title + "</b>\n\n"
            + fact.get("hook", "") + "\n\n"
            + hashtags
        )

        size_mb = 0
        if Path(OUTPUT_VIDEO).exists():
            size_mb = Path(OUTPUT_VIDEO).stat().st_size / (1024*1024)

        if size_mb < 48:
            send_telegram_video(video_caption)
        elif Path(THUMBNAIL_FILE).exists():
            send_telegram_photo(video_caption)

        tags_str = ", ".join(tag_list[:20])

        metadata_msg = (
            "✅ <b>VIDEO READY — " + date_str + "</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎬 <b>YOUTUBE TITLE:</b>\n" + english_title + "\n\n"
            "📝 <b>DESCRIPTION:</b>\n" + description[:700] + "\n\n"
            "🏷️ <b>TAGS:</b>\n" + tags_str + "\n\n"
            "#️⃣ <b>HASHTAGS:</b>\n" + hashtags + "\n\n"
            "📥 <b>DOWNLOAD:</b>\n"
            "<a href='" + artifact_url + "'>Click Here - GitHub Artifact</a>\n\n"
            "⏰ Upload at 5:00 PM PKT\n"
            "📧 ubaidurehman983@gmail.com\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_message(metadata_msg)
    else:
        send_telegram_message(
            "❌ <b>VIDEO FAILED — " + date_str + "</b>\n\n"
            "Logs: <a href='" + artifact_url + "'>GitHub Actions</a>"
        )


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    log.info("AJEEBOLOGY SHORTS AGENT STARTED")

    log.info("STEP 1: Downloading fonts...")
    download_fonts()

    log.info("STEP 2: Fetching fact...")
    fact = get_todays_fact()
    log.info("Fact: " + fact["title"])

    log.info("STEP 3: Downloading music...")
    download_free_music()

    log.info("STEP 4: Generating male voiceover...")
    audio_clips = generate_voiceover(fact)

    log.info("STEP 5: Creating animated frames...")
    all_frames, thumbnail = create_all_slides(fact, audio_clips)

    if thumbnail:
        thumbnail.save(THUMBNAIL_FILE, "PNG")
        log.info("Thumbnail saved")

    log.info("STEP 6: Building video...")
    video_ok = build_video(audio_clips)

    log.info("STEP 7: Sending Telegram notification...")
    notify_telegram(fact, video_ok)

    if video_ok:
        log.info("PIPELINE COMPLETE!")
    else:
        log.error("PIPELINE FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
