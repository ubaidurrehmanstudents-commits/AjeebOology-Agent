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

WIDTH, HEIGHT  = 1080, 1920
SLIDE_DURATION = 4
OUTPUT_VIDEO   = "output_video.mp4"
THUMBNAIL_FILE = "thumbnail.png"
FRAMES_DIR     = Path("frames")
AUDIO_DIR      = Path("audio_clips")

TOPICS = [
    "psychology facts Hindi English mix",
    "space universe secrets facts Hinglish",
    "weird world amazing facts Hinglish",
    "human brain facts shocking Hinglish",
    "animal facts amazing Hindi English",
]

FALLBACK_FACTS = [
    {
        "title": "Psychology Ka Kamaal!",
        "fact": "Jab aap kisi cheez ke baare mein bahut zyada sochte hain toh aapka brain usse reality maan leta hai. Isliye positive sochna scientifically proven hai!",
        "hook": "Yeh sun ke aap hairan ho jayenge...",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Psychology"
    },
    {
        "title": "Space Ka Raaz!",
        "fact": "Universe mein itne stars hain ki agar aap ek second mein ek star count karein toh 3000 saal lagenge! Aur hum sochte hain hum akele hain...",
        "hook": "Space ka yeh secret aapki soch badal dega!",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Space"
    },
    {
        "title": "Neend Ka Jaadu!",
        "fact": "Aapka brain neend mein bhi active rehta hai. REM sleep mein aapka brain jagte waqt se bhi zyada kaam karta hai. Isliye sapne itane real lagte hain!",
        "hook": "Neend ke baare mein yeh baat aapko hairan kar degi!",
        "wrapup": "Aisa hi content ke liye subscribe karein!",
        "category": "Psychology"
    },
]

PALETTES = [
    {"bg": (10, 10, 40),  "accent": (100, 200, 255), "text": (255, 255, 255), "glow": (50, 100, 200)},
    {"bg": (20, 5, 35),   "accent": (200, 100, 255), "text": (255, 255, 255), "glow": (150, 50, 200)},
    {"bg": (5, 30, 20),   "accent": (100, 255, 150), "text": (255, 255, 255), "glow": (50, 200, 100)},
    {"bg": (40, 10, 5),   "accent": (255, 150, 50),  "text": (255, 255, 255), "glow": (200, 100, 30)},
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
        log.info("Tavily returned content")
        if len(raw) > 50:
            return raw
        return None
    except Exception as e:
        log.warning("Tavily failed: " + str(e))
        return None


def generate_fact_with_groq(raw_context):
    client = Groq(api_key=GROQ_API_KEY)

    if raw_context:
        system = "You are a viral YouTube Shorts script writer for Ajeebology Shorts channel. Niche: Psychology Facts, Space Secrets, Weird World Facts. Language: Hinglish. Return ONLY valid JSON, no extra text."
        user = "Given this info: " + str(raw_context[:800]) + "\n\nReturn ONLY this JSON:\n{\"title\": \"emoji + catchy title\", \"hook\": \"attention grabbing line\", \"fact\": \"main fact 3-5 sentences Hinglish\", \"wrapup\": \"subscribe encouragement\", \"category\": \"Psychology/Space/Science\"}"
    else:
        system = "You are a viral YouTube Shorts script writer for Ajeebology Shorts. Language: Hinglish. Return ONLY valid JSON, no extra text."
        user = "Create a mind-blowing fact. Return ONLY this JSON:\n{\"title\": \"emoji + catchy title\", \"hook\": \"attention grabbing line\", \"fact\": \"main fact 3-5 sentences Hinglish\", \"wrapup\": \"subscribe encouragement\", \"category\": \"Psychology/Space/Science\"}"

    log.info("Calling Groq to generate fact...")
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            temperature=0.85,
            max_tokens=600,
        )
        content = response.choices[0].message.content.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        fact_data = json.loads(content)
        log.info("Groq generated fact successfully")
        return fact_data
    except Exception as e:
        log.warning("Groq failed: " + str(e))
        return random.choice(FALLBACK_FACTS)


def get_todays_fact():
    raw = fetch_fact_tavily()
    try:
        fact = generate_fact_with_groq(raw)
        required = {"title", "hook", "fact", "category"}
        if not required.issubset(fact.keys()):
            raise ValueError("Missing keys")
        return fact
    except Exception as e:
        log.warning("Using fallback: " + str(e))
        return random.choice(FALLBACK_FACTS)


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
        log.info("Generating TTS clip " + str(i+1))
        try:
            tts = gTTS(text=text, lang="hi", slow=False)
            tts.save(str(path))
            clips.append(path)
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
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()


def draw_stars(draw, count=120):
    for _ in range(count):
        x = random.randint(0, WIDTH)
        y = random.randint(0, HEIGHT)
        r = random.randint(1, 3)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=(255, 255, 255))


def draw_gradient_bg(img, palette):
    draw = ImageDraw.Draw(img)
    bg = palette["bg"]
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(bg[0] * (1 - ratio * 0.3))
        g = int(bg[1] * (1 - ratio * 0.3))
        b = int(bg[2] * (1 - ratio * 0.3))
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    draw_stars(draw)


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ""
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    for word in words:
        test = (current + " " + word).strip()
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


def draw_text_shadow(draw, pos, text, font, color):
    x, y = pos
    draw.text((x+3, y+3), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=color)


def create_slide(slide_index, total_slides, title, body_text, palette):
    img = Image.new("RGB", (WIDTH, HEIGHT), color=palette["bg"])
    draw_gradient_bg(img, palette)
    draw = ImageDraw.Draw(img)
    accent = palette["accent"]
    text_color = palette["text"]
    pad = 60

    font_sm = load_font(36)
    font_title = load_font(66)
    font_body = load_font(50)
    font_cta = load_font(42)

    draw.text((pad, 60), "Ajeebology Shorts", font=font_sm, fill=accent)
    draw.line([(pad, 120), (WIDTH-pad, 120)], fill=accent, width=2)

    title_lines = wrap_text(title, font_title, WIDTH - pad*2)
    title_y = 280
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        lw = bbox[2] - bbox[0]
        draw_text_shadow(draw, ((WIDTH-lw)//2, title_y), line, font_title, text_color)
        title_y += bbox[3] - bbox[1] + 10

    div_y = title_y + 20
    draw.line([(pad*2, div_y), (WIDTH-pad*2, div_y)], fill=accent, width=3)

    body_lines = wrap_text(body_text, font_body, WIDTH - pad*2)
    body_y = div_y + 40
    for line in body_lines:
        bbox = draw.textbbox((0, 0), line, font=font_body)
        lw = bbox[2] - bbox[0]
        draw_text_shadow(draw, ((WIDTH-lw)//2, body_y), line, font_body, text_color)
        body_y += bbox[3] - bbox[1] + 12

    cta_y = HEIGHT - 250
    draw.line([(pad, cta_y-20), (WIDTH-pad, cta_y-20)], fill=accent, width=2)
    for line in ["Subscribe Karen!", "Daily 5:00 PM PKT pe naya Short!"]:
        bbox = draw.textbbox((0, 0), line, font=font_cta)
        lw = bbox[2] - bbox[0]
        draw.text(((WIDTH-lw)//2, cta_y), line, font=font_cta, fill=accent)
        cta_y += 55

    return img


def create_all_slides(fact):
    FRAMES_DIR.mkdir(exist_ok=True)
    palette = random.choice(PALETTES)
    slides_data = [
        {"title": fact["title"], "body": fact.get("hook", "Yeh jaankar aap hairan ho jayenge!")},
        {"title": "Ajeeb Fact", "body": fact["fact"]},
        {"title": "Aur Jaano!", "body": fact.get("wrapup", "Subscribe zarur karein!")},
    ]
    slide_paths = []
    thumbnail = None
    for i, slide in enumerate(slides_data):
        log.info("Creating slide " + str(i+1))
        img = create_slide(i, len(slides_data), slide["title"], slide["body"], palette)
        path = FRAMES_DIR / ("slide_" + str(i).zfill(3) + ".png")
        img.save(str(path), "PNG")
        slide_paths.append(path)
        if i == 0:
            thumbnail = img
    return slide_paths, thumbnail


def build_video(slide_paths, audio_clips):
    log.info("Assembling video with FFmpeg...")
    durations = [get_audio_duration(a) for a in audio_clips]

    inputs = []
    for slide, dur in zip(slide_paths, durations):
        inputs += ["-loop", "1", "-t", str(dur), "-i", str(slide)]

    audio_inputs = []
    for a in audio_clips:
        audio_inputs += ["-i", str(a)]

    n = len(slide_paths)
    filter_parts = []
    for i in range(n):
        filter_parts.append(
            "[" + str(i) + ":v]scale=" + str(WIDTH) + ":" + str(HEIGHT) +
            ":force_original_aspect_ratio=decrease,pad=" + str(WIDTH) + ":" +
            str(HEIGHT) + ":(ow-iw)/2:(oh-ih)/2,setsar=1[v" + str(i) + "];"
        )

    video_concat = "".join(["[v" + str(i) + "]" for i in range(n)])
    audio_offset = n
    audio_concat = "".join(["[" + str(audio_offset+i) + ":a]" for i in range(len(audio_clips))])

    filter_parts.append(video_concat + "concat=n=" + str(n) + ":v=1:a=0[vout];")
    filter_parts.append(audio_concat + "concat=n=" + str(len(audio_clips)) + ":v=0:a=1[aout]")
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
        log.error("FFmpeg failed: " + result.stderr[-1000:])
        return False
    log.info("Video created successfully")
    return True


def build_artifact_url():
    if GITHUB_REPO and GITHUB_RUN_ID:
        return "https://github.com/" + GITHUB_REPO + "/actions/runs/" + GITHUB_RUN_ID
    return "https://github.com"


def send_telegram_message(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }, timeout=30)
    return resp.ok


def send_telegram_video(video_path, caption):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendVideo"
    try:
        with open(video_path, "rb") as vf:
            resp = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"video": vf},
                timeout=120,
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
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=60,
            )
        return resp.ok
    except Exception as e:
        log.warning("Telegram photo failed: " + str(e))
        return False


def notify_telegram(fact, video_ok):
    artifact_url = build_artifact_url()
    date_str = datetime.now().strftime("%d %b %Y")

    if video_ok:
        caption = (
            "Ajeebology Shorts - Daily Short\n"
            + date_str + "\n\n"
            + fact["title"] + "\n\n"
            + "Download: " + artifact_url
        )
        size_mb = 0
        if Path(OUTPUT_VIDEO).exists():
            size_mb = Path(OUTPUT_VIDEO).stat().st_size / (1024 * 1024)

        if size_mb < 48:
            sent = send_telegram_video(OUTPUT_VIDEO, caption)
        else:
            sent = False

        if not sent:
            send_telegram_photo(THUMBNAIL_FILE, caption)

        send_telegram_message(
            "Video Ready!\n\nTitle: " + fact["title"] +
            "\nDate: " + date_str +
            "\n\nDownload:\n" + artifact_url
        )
    else:
        send_telegram_message(
            "Video Generation FAILED\n"
            + date_str + "\n\nCheck logs:\n" + artifact_url
        )


def main():
    log.info("AJEEBOLOGY SHORTS AGENT STARTED")

    log.info("STEP 1: Fetching fact...")
    fact = get_todays_fact()
    log.info("Fact: " + fact["title"])

    log.info("STEP 2: Generating voiceover...")
    audio_clips = generate_voiceover(fact)

    log.info("STEP 3: Creating slides...")
    slide_paths, thumbnail = create_all_slides(fact)

    if thumbnail:
        thumbnail.save(THUMBNAIL_FILE, "PNG")
        log.info("Thumbnail saved")

    log.info("STEP 4: Building video...")
    video_ok = build_video(slide_paths, audio_clips)

    log.info("STEP 5: Sending Telegram notification...")
    notify_telegram(fact, video_ok)

    if video_ok:
        log.info("PIPELINE COMPLETE - Video ready!")
    else:
        log.error("PIPELINE FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
