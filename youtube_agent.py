#!/usr/bin/env python3
"""
Ajeebologyshorts - Professional Monetizable YouTube Shorts Generator
Single File Version - Human-like voice + Full Telegram Metadata
"""

import os
import random
import asyncio
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import groq
import edge_tts
import requests
from moviepy.editor import (
    VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip,
    concatenate_videoclips, ColorClip, CompositeAudioClip
)
from moviepy.video.fx.all import fadein, fadeout
from moviepy.audio.fx.all import audio_normalize

# ==================== CONFIG ====================
BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "videos"
AUDIO_DIR = BASE_DIR / "output" / "audio"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

CHANNEL_NAME = "Ajeebologyshorts"

TOPICS = [
    "Why do we forget our dreams?",
    "The psychology trick that makes people instantly like you",
    "What NASA doesn't want you to know about space",
    "Mind-blowing fact about human memory",
    "The weird reason you feel déjà vu",
    "How your brain tricks you every single day",
    "Why time feels faster as you get older",
    "The dark psychology behind social media",
    "Secret NASA experiment that changed everything",
    "The surprising truth about first impressions"
]

# Human-like Indian Voice (Best for monetization)
VOICE = "en-IN-NeerjaNeural"
SPEED = "+4%"                    # Slightly slower = more natural

VIDEO_DURATION = 50
RESOLUTION = (1080, 1920)
FPS = 30
CAPTION_FONT = "DejaVu-Sans-Bold"
BRAND_COLOR = "#FFD700"
BG_COLOR = (12, 12, 28)

load_dotenv()

# ==================== 1. GENERATE SCRIPT + METADATA ====================
def generate_script_and_metadata(topic: str):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        script = f"Here are 5 mind-blowing facts about {topic}. The first one will shock you..."
        return script, f"You Won't Believe These Facts About {topic}", script, "#Shorts #Psychology", ["psychology", "facts"]

    client = groq.Groq(api_key=api_key)

    prompt = f"""You are a professional YouTube Shorts scriptwriter for Ajeebologyshorts.

Create:
1. A highly engaging 48-52 second script (strong hook + 5-6 facts + CTA)
2. A curiosity-driven title (under 60 characters)
3. A YouTube description (2-3 lines)
4. 4-5 relevant hashtags
5. 8-10 tags

Topic: {topic}

Return ONLY in this exact JSON format:
{{
  "script": "...",
  "title": "...",
  "description": "...",
  "hashtags": "...",
  "tags": ["tag1", "tag2"]
}}"""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.75,
        )
        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        return data["script"], data["title"], data["description"], data["hashtags"], data["tags"]
    except:
        script = f"Here are 5 shocking facts about {topic}. Number one will blow your mind..."
        return script, f"You Won't Believe These Facts About {topic}", script, "#Shorts #Psychology", ["psychology", "facts"]

# ==================== 2. HUMAN-LIKE VOICEOVER ====================
async def generate_voiceover(text: str, path: str):
    communicate = edge_tts.Communicate(text, VOICE, rate=SPEED)
    await communicate.save(path)

def create_voiceover(text: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(AUDIO_DIR / f"voice_{ts}.mp3")
    asyncio.run(generate_voiceover(text, path))
    return path

# ==================== 3. STOCK FOOTAGE ====================
def get_stock_footage(max_clips=5):
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    headers = {"Authorization": key}
    keywords = ["brain", "space", "mind", "stars", "psychology", "thinking", "mystery"]
    urls = []
    for kw in random.sample(keywords, 5):
        try:
            r = requests.get("https://api.pexels.com/videos/search", headers=headers,
                             params={"query": kw, "per_page": 3, "orientation": "portrait"}, timeout=12)
            if r.status_code == 200:
                for v in r.json().get("videos", []):
                    if v.get("video_files"):
                        urls.append(v["video_files"][0]["link"])
        except:
            continue
    return list(dict.fromkeys(urls))[:max_clips]

# ==================== 4. KEN BURNS EFFECT ====================
def apply_ken_burns(clip, duration):
    def zoom(get_frame, t):
        frame = get_frame(t)
        z = 1.0 + (0.18 * (t / duration))
        h, w = frame.shape[:2]
        nw, nh = int(w * z), int(h * z)
        x = int((nw - w) * (t / duration) * 0.5)
        y = int((nh - h) * (t / duration) * 0.3)
        return frame[y:y+h, x:x+w]
    return clip.fl(zoom).set_duration(duration)

# ==================== 5. BACKGROUND MUSIC ====================
def get_music():
    return random.choice([
        "https://cdn.pixabay.com/audio/2022/05/27/audio_1808b9a0b2.mp3",
        "https://cdn.pixabay.com/audio/2022/03/15/audio_8f8b9a0b2.mp3"
    ])

def download_music(url):
    path = str(AUDIO_DIR / "bg_music.mp3")
    try:
        r = requests.get(url, timeout=15)
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except:
        return None

# ==================== 6. KARAOKE CAPTIONS ====================
def create_karaoke_captions(script, duration):
    words = script.split()
    if not words:
        return []
    clips = []
    wps = len(words) / duration
    time = 0
    for i in range(0, len(words), 3):
        chunk = " ".join(words[i:i+3])
        dur = (3 / wps) * 0.95
        txt = TextClip(chunk, fontsize=52, color="white", font=CAPTION_FONT,
                       stroke_color="black", stroke_width=3,
                       size=(RESOLUTION[0]-80, None), method="caption"
                       ).set_position(("center", 0.76)).set_duration(dur).set_start(time)
        hl = TextClip(chunk, fontsize=52, color="#FFD700", font=CAPTION_FONT,
                      stroke_color="#000000", stroke_width=2,
                      size=(RESOLUTION[0]-80, None), method="caption"
                      ).set_position(("center", 0.76)).set_duration(0.6).set_start(time+0.3).set_opacity(0.9)
        clips.extend([txt, hl])
        time += dur
    return clips

# ==================== 7. CREATE PROFESSIONAL VIDEO ====================
def create_video(script, voice_path, topic, title):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(OUTPUT_DIR / f"ajeebologyshorts_pro_{ts}.mp4")

    print("🎬 Creating professional short...")

    # Visuals
    urls = get_stock_footage()
    segs = []
    for i, url in enumerate(urls):
        try:
            c = VideoFileClip(url).resize(height=RESOLUTION[1]).crop(x_center=0.5, width=RESOLUTION[0])
            c = apply_ken_burns(c, c.duration)
            if i > 0: c = fadein(c, 0.4)
            if i < len(urls)-1: c = fadeout(c, 0.4)
            segs.append(c)
        except:
            continue
    if not segs:
        segs = [ColorClip(size=RESOLUTION, color=BG_COLOR, duration=VIDEO_DURATION)]

    video = concatenate_videoclips(segs, method="compose")
    if video.duration > VIDEO_DURATION:
        video = video.subclip(0, VIDEO_DURATION)
    elif video.duration < VIDEO_DURATION:
        video = video.loop(duration=VIDEO_DURATION)

    # Audio
    voice = audio_normalize(AudioFileClip(voice_path))
    music_path = download_music(get_music())
    if music_path and os.path.exists(music_path):
        bg = AudioFileClip(music_path).volumex(0.18)
        if bg.duration < VIDEO_DURATION:
            bg = bg.loop(duration=VIDEO_DURATION)
        else:
            bg = bg.subclip(0, VIDEO_DURATION)
        final_audio = CompositeAudioClip([bg, voice])
    else:
        final_audio = voice
    video = video.set_audio(final_audio)

    # Captions + Branding
    caps = create_karaoke_captions(script, VIDEO_DURATION)
    brand = TextClip("🧠 AJEEBOLOGYSHORTS", fontsize=36, color=BRAND_COLOR,
                     font=CAPTION_FONT, stroke_color="black", stroke_width=2
                     ).set_position(("center", 0.065)).set_duration(VIDEO_DURATION)
    cta = TextClip("Comment your thoughts 👇", fontsize=28, color="white",
                   font=CAPTION_FONT, stroke_color="black", stroke_width=1.5
                   ).set_position(("center", 0.92)).set_duration(VIDEO_DURATION*0.6).set_start(VIDEO_DURATION*0.4)

    final = CompositeVideoClip([video] + caps + [brand, cta])
    final.write_videofile(output_path, fps=FPS, codec="libx264", audio_codec="aac",
                          bitrate="8500k", preset="fast", threads=4, logger=None)
    return output_path

# ==================== 8. SEND RICH TELEGRAM MESSAGE ====================
def send_telegram(title, description, hashtags, tags, video_path, run_id):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    artifact_link = f"https://github.com/ubaidurrehmn/AjeebOology-Agent/actions/runs/{run_id}/artifacts"

    message = f"""🎬 <b>New Professional Short Ready!</b>

<b>📌 Title:</b> {title}

<b>📝 Description:</b>
{description}

<b>🔖 Hashtags:</b> {hashtags}

<b>🏷️ Tags:</b> {', '.join(tags)}

<b>📥 Download Video:</b> {artifact_link}

✅ Ready to upload to YouTube
"""

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=15)
    print("✅ Rich Telegram notification sent")

# ==================== MAIN ====================
def main():
    print("=" * 65)
    print("🚀 AJEEBOLOGYSHORTS - PROFESSIONAL MONETIZABLE GENERATOR")
    print("=" * 65)

    topic = random.choice(TOPICS)
    print(f"📌 Topic: {topic}")

    script, title, desc, hashtags, tags = generate_script_and_metadata(topic)
    print(f"📝 Title: {title}")

    voice_path = create_voiceover(script)
    print("🎙️ Human-like voice created")

    video_path = create_video(script, voice_path, topic, title)

    # Save metadata
    with open(OUTPUT_DIR / "latest.txt", "w") as f:
        f.write(f"Title: {title}\nScript: {script}\nFile: {video_path}\n")

    # Get GitHub Run ID
    run_id = os.getenv("GITHUB_RUN_ID", "unknown")

    # Send Telegram with full metadata
    send_telegram(title, desc, hashtags, tags, video_path, run_id)

    print("\n🎉 PROFESSIONAL SHORT + METADATA SENT TO TELEGRAM!")
    print("=" * 65)

if __name__ == "__main__":
    main()
