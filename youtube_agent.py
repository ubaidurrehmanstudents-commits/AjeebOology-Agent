import os
import sys
import json
import random
import logging
import requests
import subprocess
from pathlib import Path
from datetime import datetime

from groq import Groq
from gtts import gTTS
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
SLIDE_DURATION = 5
OUTPUT_VIDEO   = "output_video.mp4"
THUMBNAIL_FILE = "thumbnail.png"
FRAMES_DIR     = Path("frames")
AUDIO_DIR      = Path("audio_clips")
MUSIC_FILE     = "bg_music.mp3"

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
        "title": "🧠 Psychology Ka Kamaal!",
        "fact": "Jab aap kisi cheez ke baare mein bahut zyada sochte hain toh aapka brain usse reality maan leta hai. Isliye positive sochna scientifically proven hai!",
        "hook": "Yeh sun ke aap hairan ho jayenge...",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Psychology"
    },
    {
        "title": "🌌 Space Ka Raaz!",
        "fact": "Universe mein itne stars hain ki agar aap ek second mein ek star count karein toh 3000 saal lagenge!",
        "hook": "Space ka yeh secret aapki soch badal dega!",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Space"
    },
    {
        "title": "😴 Neend Ka Jaadu!",
        "fact": "Aapka brain neend mein bhi active rehta hai. REM sleep mein aapka brain jagte waqt se bhi zyada kaam karta hai!",
        "hook": "Neend ke baare mein yeh baat aapko hairan kar degi!",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Psychology"
    },
]

PALETTES = [
    {"bg": (8, 8, 35),   "accent": (0, 200, 255),  "text": (255, 255, 255), "star": (180, 220, 255)},
    {"bg": (18, 4, 32),  "accent": (180, 80, 255),  "text": (255, 255, 255), "star": (220, 180, 255)},
    {"bg": (4, 28, 18),  "accent": (0, 255, 140),   "text": (255, 255, 255), "star": (180, 255, 220)},
    {"bg": (35, 8, 4),   "accent": (255, 140, 0),   "text": (255, 255, 255), "star": (255, 220, 180)},
    {"bg": (4, 18, 35),  "accent": (0, 160, 255),   "text": (255, 255, 255), "star": (180, 200, 255)},
]


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
    if raw_context:
        system = "You are a viral YouTube Shorts script writer for Ajeebology Shorts. Niche: Psychology, Space, Weird Facts. Language: Hinglish. Return ONLY valid JSON."
        user = (
            "Given this info: " + str(raw_context[:800]) +
            "\n\nReturn ONLY this JSON:\n"
            "{\n"
            "  \"title\": \"emoji + catchy Hinglish title max 8 words\",\n"
            "  \"hook\": \"1-2 sentence attention grabber Hinglish\",\n"
            "  \"fact\": \"main fact 4-5 sentences Hinglish conversational\",\n"
            "  \"wrapup\": \"subscribe encouragement Hinglish\",\n"
            "  \"category\": \"Psychology or Space or Science or Animals or History\",\n"
            "  \"english_title\": \"SEO optimized English title for YouTube\",\n"
            "  \"description\": \"150 word English YouTube description with keywords\",\n"
            "  \"tags\": \"tag1,tag2,tag3,tag4,tag5,tag6,tag7,tag8,tag9,tag10\"\n"
            "}"
        )
    else:
        system = "You are a viral YouTube Shorts script writer for Ajeebology Shorts. Language: Hinglish. Return ONLY valid JSON."
        user = (
            "Create an original mind-blowing fact. Return ONLY this JSON:\n"
            "{\n"
            "  \"title\": \"emoji + catchy Hinglish title max 8 words\",\n"
            "  \"hook\": \"1-2 sentence attention grabber Hinglish\",\n"
            "  \"fact\": \"main fact 4-5 sentences Hinglish conversational\",\n"
            "  \"wrapup\": \"subscribe encouragement Hinglish\",\n"
            "  \"category\": \"Psychology or Space or Science or Animals or History\",\n"
            "  \"english_title\": \"SEO optimized English title for YouTube\",\n"
            "  \"description\": \"150 word English YouTube description with keywords\",\n"
            "  \"tags\": \"tag1,tag2,tag3,tag4,tag5,tag6,tag7,tag8,tag9,tag10\"\n"
            "}"
        )
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            temperature=0.85,
            max_tokens=800,
        )
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        fact_data = json.loads(content)
        log.info("Groq generated fact: " + fact_data.get("title", ""))
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


def download_free_music():
    try:
        log.info("Downloading free background music from Pixabay...")
        music_urls = [
            "https://cdn.pixabay.com/download/audio/2022/03/15/audio_8cb4bae0c2.mp3",
            "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0fd6a3ab2.mp3",
            "https://cdn.pixabay.com/download/audio/2021/11/25/audio_5b3e7a6b5f.mp3",
        ]
        url = random.choice(music_urls)
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            with open(MUSIC_FILE, "wb") as f:
                f.write(resp.content)
            log.info("Music downloaded successfully")
            return True
        return False
    except Exception as e:
        log.warning("Music download failed: " + str(e))
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
        try:
            tts = gTTS(text=text, lang="hi", slow=False)
            tts.save(str(path))
        except Exception as e:
            log.error("TTS failed: " + str(e))
            subprocess.run([
                "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                "-t", str(SLIDE_DURATION), "-q:a", "9", "-acodec", "libmp3lame",
                str(path), "-y"
            ], capture_output=True)
        clips.append(path)
    return clips


def get_audio_duration(path):
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "json", str(path)
        ], capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return float(SLIDE_DURATION)


def load_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_background(img, palette, slide_index):
    draw = ImageDraw.Draw(img)
    bg = palette["bg"]

    # Gradient
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = min(255, int(bg[0] + 20 * ratio))
        g = min(255, int(bg[1] + 20 * ratio))
        b = min(255, int(bg[2] + 30 * ratio))
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # Stars
    random.seed(slide_index * 42)
    for _ in range(150):
        x = random.randint(0, WIDTH)
        y = random.randint(0, HEIGHT)
        r = random.randint(1, 3)
        bright = random.randint(150, 255)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(bright, bright, bright))

    # Glowing circles decoration
    accent = palette["accent"]
    for radius, alpha_div in [(200, 8), (150, 6), (100, 4)]:
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        cx, cy = WIDTH // 2, HEIGHT // 3
        a = accent[0] // alpha_div
        b2 = accent[1] // alpha_div
        c2 = accent[2] // alpha_div
        ov_draw.ellipse(
            [cx-radius, cy-radius, cx+radius, cy+radius],
            fill=(a, b2, c2, 40)
        )
        img.paste(Image.new("RGB", (WIDTH, HEIGHT), (0,0,0)), mask=overlay.split()[3])

    # Grid lines (subtle)
    for x in range(0, WIDTH, 80):
        draw.line([(x, 0), (x, HEIGHT)], fill=(255, 255, 255, 8), width=1)
    for y2 in range(0, HEIGHT, 80):
        draw.line([(0, y2), (WIDTH, y2)], fill=(255, 255, 255, 8), width=1)

    random.seed()


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = (current + " " + word).strip()
        bbox = dummy.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text_glow(draw, pos, text, font, color, accent):
    x, y = pos
    # Glow effect
    for offset in [(3,3), (-3,3), (3,-3), (-3,-3), (0,4), (4,0), (-4,0), (0,-4)]:
        draw.text((x+offset[0], y+offset[1]), text, font=font,
                  fill=(accent[0]//3, accent[1]//3, accent[2]//3))
    # Shadow
    draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0))
    # Main text
    draw.text((x, y), text, font=font, fill=color)


def create_slide(slide_index, total_slides, title, body_text, palette, emoji_top="✨"):
    img = Image.new("RGB", (WIDTH, HEIGHT), color=palette["bg"])
    draw_background(img, palette, slide_index)
    draw = ImageDraw.Draw(img)

    accent = palette["accent"]
    text_color = palette["text"]
    pad = 45

    font_channel = load_font(28)
    font_emoji   = load_font(55)
    font_title   = load_font(52)
    font_body    = load_font(38)
    font_cta     = load_font(32)
    font_dot     = load_font(22)

    # Top bar
    draw.rectangle([0, 0, WIDTH, 90], fill=(0, 0, 0))
    draw.text((pad, 28), "AJEEBOLOGY SHORTS", font=font_channel, fill=accent)
    draw.line([(0, 90), (WIDTH, 90)], fill=accent, width=2)

    # Progress dots
    dot_y = 115
    spacing = 24
    total_w = (total_slides - 1) * spacing
    start_x = (WIDTH - total_w) // 2
    for i in range(total_slides):
        x = start_x + i * spacing
        if i == slide_index:
            draw.ellipse([x-8, dot_y-8, x+8, dot_y+8], fill=accent)
        else:
            draw.ellipse([x-5, dot_y-5, x+5, dot_y+5], fill=(80, 80, 80))

    # Big emoji
    emoji_bbox = draw.textbbox((0, 0), emoji_top, font=font_emoji)
    ew = emoji_bbox[2] - emoji_bbox[0]
    draw.text(((WIDTH - ew) // 2, 145), emoji_top, font=font_emoji, fill=text_color)

    # Accent line top
    draw.line([(pad, 225), (WIDTH-pad, 225)], fill=accent, width=3)

    # Title
    title_lines = wrap_text(title, font_title, WIDTH - pad*2)
    ty = 245
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        lw = bbox[2] - bbox[0]
        draw_text_glow(draw, ((WIDTH-lw)//2, ty), line, font_title, text_color, accent)
        ty += bbox[3] - bbox[1] + 8

    # Divider
    draw.line([(pad*2, ty+15), (WIDTH-pad*2, ty+15)], fill=accent, width=2)

    # Body text box
    box_top = ty + 30
    body_lines = wrap_text(body_text, font_body, WIDTH - pad*2 - 20)
    body_height = len(body_lines) * 55 + 30
    draw.rounded_rectangle(
        [pad-10, box_top, WIDTH-pad+10, box_top+body_height],
        radius=18,
        fill=(0, 0, 0)
    )

    by = box_top + 15
    for line in body_lines:
        bbox = draw.textbbox((0, 0), line, font=font_body)
        lw = bbox[2] - bbox[0]
        draw.text(((WIDTH-lw)//2, by), line, font=font_body, fill=text_color)
        by += bbox[3] - bbox[1] + 12

    # CTA box at bottom
    cta_box_top = HEIGHT - 220
    draw.rectangle([0, cta_box_top, WIDTH, HEIGHT], fill=(0, 0, 0))
    draw.line([(0, cta_box_top), (WIDTH, cta_box_top)], fill=accent, width=3)

    cta_lines = [
        "🔔 Subscribe Now!",
        "Daily Facts at 5:00 PM PKT",
        "@AjeebologyShorts",
    ]
    cy = cta_box_top + 18
    for line in cta_lines:
        bbox = draw.textbbox((0, 0), line, font=font_cta)
        lw = bbox[2] - bbox[0]
        draw.text(((WIDTH-lw)//2, cy), line, font=font_cta, fill=accent)
        cy += 52

    return img


def create_all_slides(fact):
    FRAMES_DIR.mkdir(exist_ok=True)
    palette = random.choice(PALETTES)

    cat = fact.get("category", "Facts")
    cat_emojis = {
        "Psychology": "🧠",
        "Space": "🌌",
        "Science": "⚗️",
        "Animals": "🐾",
        "History": "📜",
    }
    emoji = cat_emojis.get(cat, "✨")

    slides_data = [
        {
            "title": fact["title"],
            "body": fact.get("hook", "Yeh jaankar aap hairan ho jayenge!"),
            "emoji": emoji
        },
        {
            "title": cat + " Fact",
            "body": fact["fact"],
            "emoji": "🔍"
        },
        {
            "title": "Mind = Blown!",
            "body": fact.get("wrapup", "Subscribe karein for daily amazing facts!"),
            "emoji": "💥"
        },
    ]

    slide_paths = []
    thumbnail = None

    for i, slide in enumerate(slides_data):
        log.info("Creating slide " + str(i+1))
        img = create_slide(i, len(slides_data), slide["title"], slide["body"],
                           palette, slide["emoji"])
        path = FRAMES_DIR / ("slide_" + str(i).zfill(3) + ".png")
        img.save(str(path), "PNG")
        slide_paths.append(path)
        if i == 0:
            thumbnail = img

    return slide_paths, thumbnail


def build_video(slide_paths, audio_clips):
    log.info("Building video...")
    durations = [get_audio_duration(a) for a in audio_clips]
    has_music = Path(MUSIC_FILE).exists()

    inputs = []
    for slide, dur in zip(slide_paths, durations):
        inputs += ["-loop", "1", "-t", str(dur), "-i", str(slide)]

    audio_inputs = []
    for a in audio_clips:
        audio_inputs += ["-i", str(a)]

    if has_music:
        audio_inputs += ["-i", MUSIC_FILE]

    n = len(slide_paths)
    na = len(audio_clips)

    filter_parts = []
    for i in range(n):
        filter_parts.append(
            "[" + str(i) + ":v]scale=" + str(WIDTH) + ":" + str(HEIGHT) +
            ":force_original_aspect_ratio=decrease,"
            "pad=" + str(WIDTH) + ":" + str(HEIGHT) +
            ":(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v" + str(i) + "];"
        )

    video_concat = "".join(["[v" + str(i) + "]" for i in range(n)])
    audio_concat = "".join(["[" + str(n+i) + ":a]" for i in range(na)])

    filter_parts.append(video_concat + "concat=n=" + str(n) + ":v=1:a=0[vout];")

    if has_music:
        music_index = n + na
        total_dur = sum(durations)
        filter_parts.append(
            audio_concat + "concat=n=" + str(na) + ":v=0:a=1[voice];"
            "[" + str(music_index) + ":a]aloop=loop=-1:size=2e+09,asetpts=N/SR/TB,"
            "volume=0.15[music];"
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    else:
        filter_parts.append(
            audio_concat + "concat=n=" + str(na) + ":v=0:a=1[aout]"
        )

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

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("FFmpeg error: " + result.stderr[-1500:])
        return False
    log.info("Video created successfully")
    return True


def build_artifact_url():
    if GITHUB_REPO and GITHUB_RUN_ID:
        return "https://github.com/" + GITHUB_REPO + "/actions/runs/" + GITHUB_RUN_ID
    return "https://github.com"


def generate_youtube_metadata(fact):
    category = fact.get("category", "Facts")
    english_title = fact.get("english_title", fact["title"] + " | Ajeebology Shorts")
    date_str = datetime.now().strftime("%d %b %Y")

    description = fact.get("description", "")
    if not description:
        description = (
            "Welcome to Ajeebology Shorts! Today we explore an amazing "
            + category + " fact that will blow your mind. "
            "We bring you daily psychology facts, space secrets, and weird world facts "
            "in short engaging videos. Subscribe for daily content at 5:00 PM PKT!\n\n"
            "For Business: ubaidurehman983@gmail.com"
        )

    description += (
        "\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📺 AJEEBOLOGY SHORTS\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔔 Subscribe for daily facts at 5:00 PM PKT!\n"
        "📧 Business: ubaidurehman983@gmail.com\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📅 Published: " + date_str
    )

    raw_tags = fact.get("tags", "")
    if raw_tags:
        tag_list = [t.strip() for t in raw_tags.split(",")]
    else:
        tag_list = [
            "AjeebologyShorts", "facts", "psychology", "space", "sciencefacts",
            "mindblowingtfacts", "didyouknow", "amazingfacts", "shorts",
            "youtubeshorts", "hindifacts", "urdu", "viral", "trending",
            "knowledge", "education", "brainpower", category.lower(),
        ]

    hashtags = " ".join(["#" + t.replace(" ", "").replace("#", "") for t in tag_list[:15]])

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


def send_telegram_video(video_path, caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendVideo"
    try:
        with open(video_path, "rb") as vf:
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


def send_telegram_photo(photo_path, caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
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
    artifact_url = build_artifact_url()
    date_str = datetime.now().strftime("%d %b %Y %H:%M UTC")
    english_title, description, tag_list, hashtags = generate_youtube_metadata(fact)

    if video_ok:
        # Send video/thumbnail first
        video_caption = (
            "🎬 <b>" + english_title + "</b>\n\n"
            + fact["hook"] + "\n\n"
            + hashtags
        )

        size_mb = 0
        if Path(OUTPUT_VIDEO).exists():
            size_mb = Path(OUTPUT_VIDEO).stat().st_size / (1024 * 1024)

        if size_mb < 48:
            send_telegram_video(OUTPUT_VIDEO, video_caption)
        elif Path(THUMBNAIL_FILE).exists():
            send_telegram_photo(THUMBNAIL_FILE, video_caption)

        # Send full metadata message
        tags_str = ", ".join(tag_list[:20])

        metadata_msg = (
            "✅ <b>VIDEO READY — " + date_str + "</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "🎬 <b>YOUTUBE TITLE:</b>\n"
            + english_title + "\n\n"

            "📝 <b>DESCRIPTION:</b>\n"
            + description[:800] + "\n\n"

            "🏷️ <b>TAGS:</b>\n"
            + tags_str + "\n\n"

            "#️⃣ <b>HASHTAGS:</b>\n"
            + hashtags + "\n\n"

            "📥 <b>DOWNLOAD VIDEO:</b>\n"
            "<a href='" + artifact_url + "'>👉 Click Here — GitHub Artifact</a>\n\n"

            "⏰ <b>Upload at:</b> 5:00 PM PKT sharp\n"
            "📧 <b>Business:</b> ubaidurehman983@gmail.com\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram_message(metadata_msg)

    else:
        send_telegram_message(
            "❌ <b>VIDEO FAILED — " + date_str + "</b>\n\n"
            "Check logs:\n<a href='" + artifact_url + "'>GitHub Actions</a>"
        )


def main():
    log.info("AJEEBOLOGY SHORTS AGENT STARTED")

    log.info("STEP 1: Fetching fact...")
    fact = get_todays_fact()
    log.info("Fact: " + fact["title"])

    log.info("STEP 2: Downloading background music...")
    download_free_music()

    log.info("STEP 3: Generating voiceover...")
    audio_clips = generate_voiceover(fact)

    log.info("STEP 4: Creating slides...")
    slide_paths, thumbnail = create_all_slides(fact)

    if thumbnail:
        thumbnail.save(THUMBNAIL_FILE, "PNG")

    log.info("STEP 5: Building video...")
    video_ok = build_video(slide_paths, audio_clips)

    log.info("STEP 6: Sending Telegram notification...")
    notify_telegram(fact, video_ok)

    if video_ok:
        log.info("PIPELINE COMPLETE!")
    else:
        log.error("PIPELINE FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
