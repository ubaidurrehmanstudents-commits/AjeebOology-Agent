#!/usr/bin/env python3
"""
Ajeebologyshorts - Professional YouTube Shorts Generator
Features:
- Karaoke-style animated captions (word-by-word)
- Ken Burns zoom/pan effects
- Royalty-free background music
- Fast energetic pacing + cinematic look
- Professional editing style of top creators
"""

import os
import random
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import groq
import edge_tts
import requests
from moviepy.editor import (
    VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip,
    concatenate_videoclips, ColorClip, CompositeAudioClip, vfx
)
from moviepy.video.fx.all import resize, crop, fadein, fadeout
from moviepy.audio.fx.all import audio_normalize

# ==================== CONFIG ====================
CHANNEL_NAME = "Ajeebologyshorts"
OUTPUT_DIR = Path("output/videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR = Path("output/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

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

VOICE = "en-US-AvaNeural"
SPEED = "+6%"
VIDEO_DURATION = 50
RESOLUTION = (1080, 1920)
FPS = 30
CAPTION_FONT = "DejaVu-Sans-Bold"
BRAND_COLOR = "#FFD700"
BG_COLOR = (12, 12, 28)

load_dotenv()

# ==================== GROQ PROFESSIONAL SCRIPT ====================
def generate_professional_script(topic: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    client = groq.Groq(api_key=api_key)

    prompt = f"""You are a top-tier YouTube Shorts scriptwriter for Ajeebologyshorts.
Create an extremely engaging 48-52 second script with:
- Powerful 2-second hook
- 5-6 rapid-fire mind-blowing facts
- High curiosity & retention
- Simple language + strong ending with CTA

Topic: {topic}

Output ONLY the clean script text."""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=380,
        temperature=0.78,
    )
    script = response.choices[0].message.content.strip()
    return script[:700]

# ==================== VOICEOVER ====================
async def generate_voiceover(text: str, path: str):
    communicate = edge_tts.Communicate(text, VOICE, rate=SPEED)
    await communicate.save(path)

def create_voiceover(text: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(AUDIO_DIR / f"voice_{ts}.mp3")
    asyncio.run(generate_voiceover(text, path))
    return path

# ==================== STOCK FOOTAGE ====================
def download_stock_footage(topic: str, max_clips=5) -> list:
    pexels_key = os.getenv("PEXELS_API_KEY")
    if not pexels_key:
        return []
    headers = {"Authorization": pexels_key}
    search_terms = ["brain", "space", "mind", "stars", "psychology", "thinking", "mystery", "universe"]

    urls = []
    for term in random.sample(search_terms, 5):
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={"query": term, "per_page": 4, "orientation": "portrait"},
                timeout=15
            )
            if r.status_code == 200:
                for v in r.json().get("videos", []):
                    if v.get("video_files"):
                        urls.append(v["video_files"][0]["link"])
        except:
            pass
    return list(dict.fromkeys(urls))[:max_clips]

# ==================== KEN BURNS EFFECT ====================
def apply_ken_burns(clip, duration):
    def zoom_effect(get_frame, t):
        frame = get_frame(t)
        zoom = 1.0 + (0.18 * (t / duration))
        h, w = frame.shape[:2]
        new_w, new_h = int(w * zoom), int(h * zoom)
        x = int((new_w - w) * (t / duration) * 0.5)
        y = int((new_h - h) * (t / duration) * 0.3)
        return frame[y:y+h, x:x+w]
    return clip.fl(zoom_effect).set_duration(duration)

# ==================== BACKGROUND MUSIC ====================
def get_free_music_url():
    return random.choice([
        "https://cdn.pixabay.com/audio/2022/05/27/audio_1808b9a0b2.mp3",
        "https://cdn.pixabay.com/audio/2022/03/15/audio_8f8b9a0b2.mp3"
    ])

def download_music(url: str) -> str:
    path = str(AUDIO_DIR / "bg_music.mp3")
    try:
        r = requests.get(url, timeout=20)
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except:
        return None

# ==================== KARAOKE CAPTIONS ====================
def create_karaoke_captions(script: str, total_duration: float):
    words = script.split()
    clips = []
    words_per_second = len(words) / total_duration
    current_time = 0
    chunk_size = 3

    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        chunk_duration = (chunk_size / words_per_second) * 0.95

        # Main caption
        txt = TextClip(
            chunk, fontsize=52, color="white", font=CAPTION_FONT,
            stroke_color="black", stroke_width=3,
            size=(RESOLUTION[0] - 80, None), method="caption"
        ).set_position(("center", 0.76)).set_duration(chunk_duration).set_start(current_time)

        # Karaoke highlight
        highlight = TextClip(
            chunk, fontsize=52, color="#FFD700", font=CAPTION_FONT,
            stroke_color="#000000", stroke_width=2,
            size=(RESOLUTION[0] - 80, None), method="caption"
        ).set_position(("center", 0.76)).set_duration(0.6).set_start(current_time + 0.3).set_opacity(0.9)

        clips.extend([txt, highlight])
        current_time += chunk_duration

    return clips

# ==================== PROFESSIONAL VIDEO COMPOSER ====================
def create_professional_short(script: str, voice_path: str, topic: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(OUTPUT_DIR / f"ajeebologyshorts_pro_{ts}.mp4")

    print("🎬 Building PROFESSIONAL short...")

    # === VISUALS + KEN BURNS ===
    footage_urls = download_stock_footage(topic)
    video_segments = []

    for i, url in enumerate(footage_urls):
        try:
            clip = VideoFileClip(url)
            clip = clip.resize(height=RESOLUTION[1])
            clip = clip.crop(x_center=clip.w/2, width=RESOLUTION[0])
            clip = apply_ken_burns(clip, clip.duration)
            if i > 0: clip = fadein(clip, 0.4)
            if i < len(footage_urls) - 1: clip = fadeout(clip, 0.4)
            video_segments.append(clip)
        except:
            continue

    if not video_segments:
        video_segments = [ColorClip(size=RESOLUTION, color=BG_COLOR, duration=VIDEO_DURATION)]

    main_video = concatenate_videoclips(video_segments, method="compose")
    if main_video.duration > VIDEO_DURATION:
        main_video = main_video.subclip(0, VIDEO_DURATION)
    elif main_video.duration < VIDEO_DURATION:
        main_video = main_video.loop(duration=VIDEO_DURATION)

    # === AUDIO (Voice + Music) ===
    voice_audio = audio_normalize(AudioFileClip(voice_path))

    music_path = download_music(get_free_music_url())
    if music_path and os.path.exists(music_path):
        bg_music = AudioFileClip(music_path).volumex(0.18)
        if bg_music.duration < VIDEO_DURATION:
            bg_music = bg_music.loop(duration=VIDEO_DURATION)
        else:
            bg_music = bg_music.subclip(0, VIDEO_DURATION)
        final_audio = CompositeAudioClip([bg_music, voice_audio.set_start(0)])
    else:
        final_audio = voice_audio

    main_video = main_video.set_audio(final_audio)

    # === KARAOKE CAPTIONS + BRANDING ===
    caption_clips = create_karaoke_captions(script, VIDEO_DURATION)

    brand = TextClip(
        "🧠 AJEEBOLOGYSHORTS", fontsize=36, color=BRAND_COLOR,
        font=CAPTION_FONT, stroke_color="black", stroke_width=2
    ).set_position(("center", 0.065)).set_duration(VIDEO_DURATION)

    cta = TextClip(
        "Comment your thoughts 👇", fontsize=28, color="white",
        font=CAPTION_FONT, stroke_color="black", stroke_width=1.5
    ).set_position(("center", 0.92)).set_duration(VIDEO_DURATION * 0.6).set_start(VIDEO_DURATION * 0.4)

    final = CompositeVideoClip([main_video] + caption_clips + [brand, cta])

    # High-quality render
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate="8000k",
        preset="fast",
        threads=4,
        logger=None
    )

    print(f"✅ PRO SHORT CREATED: {output_path}")
    return output_path

# ==================== MAIN ====================
def main():
    print("=" * 60)
    print("🚀 AJEEBOLOGYSHORTS - PROFESSIONAL AI SHORTS")
    print("=" * 60)

    topic = random.choice(TOPICS)
    print(f"📌 Topic: {topic}")

    script = generate_professional_script(topic)
    voice_path = create_voiceover(script)
    video_path = create_professional_short(script, voice_path, topic)

    with open(OUTPUT_DIR / "latest.txt", "w") as f:
        f.write(f"Topic: {topic}\nScript: {script}\nFile: {video_path}\n")

    print("\n🎉 PROFESSIONAL SHORT READY!")
    print("=" * 60)

if __name__ == "__main__":
    main()
