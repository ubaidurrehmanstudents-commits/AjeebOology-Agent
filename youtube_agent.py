#!/usr/bin/env python3
"""
Ajeebology Shorts Automation Pipeline
Production-ready single-file execution.
Dependencies: edge-tts, requests, groq, tavily-python, Pillow
"""

import os
import sys
import json
import time
import random
import asyncio
import logging
import subprocess
import requests
import edge_tts  # FIX: Added missing import
from textwrap import wrap
from io import BytesIO
from groq import Groq
from tavily import TavilyClient
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# 1. LOGGING & CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AjeebologyAgent")

# Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_RUN_ID = os.getenv("GITHUB_RUN_ID", "local")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")

# Constants
RES_W, RES_H = 1080, 1920
FPS = 30
SAFE_AREA_TOP = 200
SAFE_AREA_BOTTOM = 1700

# Directories
WORKSPACE = "/tmp/ajeeb_workspace"
os.makedirs(WORKSPACE, exist_ok=True)

# ==========================================
# 2. RESEARCH & SCRIPT GENERATION
# ==========================================
def research_topic():
    logger.info("Starting Tavily research...")
    tavily = TavilyClient(api_key=TAVILY_API_KEY)
    topics = ["bizarre psychology facts", "unsolved space mysteries", "weird historical world facts"]
    query = random.choice(topics)
    
    try:
        result = tavily.search(query=query, max_results=3, include_answer=True)
        research_text = result.get("answer", "")
        sources = [r['url'] for r in result.get('results', [])[:2]]
        if not research_text and result.get('results'):
            research_text = result['results'][0]['content']
        logger.info("Research successful.")
        return research_text, sources
    except Exception as e:
        logger.error(f"Tavily research failed: {e}")
        return "Some random bizarre psychology fact about human behavior.", []

def generate_script(research_text):
    logger.info("Generating script via Groq...")
    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""
    You are an expert YouTube Shorts scriptwriter for the channel "Ajeebology Shorts".
    Content niche: Psychology Facts, Space Secrets, Weird World Facts.
    Language: Hinglish (Hindi+English mix, Roman script).
    
    Given the research: {research_text}
    
    Create a script for a 60-second Short. The script must be highly engaging, retention-optimized, and structured into exactly 5 segments (Hook, Fact 1, Fact 2, Fact 3, Outro/CTA).
    
    Return STRICT JSON with this exact format:
    {{
      "category": "Psychology" | "Space" | "Weird World",
      "title": "Catchy Hinglish title (under 60 chars)",
      "english_title": "SEO optimized English title",
      "description": "Detailed description with the script text included",
      "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
      "hashtags": ["#shorts", "#ajeebology", "#fact", "#psychology"],
      "segments": [
        {{
          "text": "Hinglish script for this segment (12-20 words)",
          "search_query": "English search query for stock footage related to this segment (1-3 words)"
        }},
        ... (5 segments total)
      ]
    }}
    """
    
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            # FIX: Updated to Groq's newest supported model
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.7
        )
        script = json.loads(response.choices[0].message.content)
        logger.info("Script generated successfully.")
        return script
    except Exception as e:
        logger.error(f"Groq script generation failed: {e}")
        # Fallback script
        return {
            "category": "Psychology",
            "title": "Aapka Dimag Kaise Kaam Karta Hai?",
            "english_title": "Psychology Facts You Didn't Know",
            "description": "Amazing psychology facts in Hinglish.",
            "tags": ["psychology", "facts", "hindu", "shorts"],
            "hashtags": ["#shorts", "#psychology"],
            "segments": [
                {"text": "Kya aap jaante hain apka dimag kaise kaam karta hai?", "search_query": "brain thinking"},
                {"text": "Ek insaan ka dimag din mein 70,000 soch soch sakta hai.", "search_query": "human brain neurons"},
                {"text": "Aur jab aap kisi ko miss karte hain, toh aapka dimag unhe dhoondhta hai.", "search_query": "missing someone sad"},
                {"text": "Rone se aapka stress level kam hota hai, ye ek scientific fact hai.", "search_query": "crying tears"},
                {"text": "Aisi ajeeb psychology facts ke liye channel ko subscribe karein!", "search_query": "subscribe button"}
            ]
        }

# ==========================================
# 3. AUDIO SYNTHESIS & WORD BOUNDARIES
# ==========================================
async def generate_audio_and_timestamps(segments):
    logger.info("Generating audio via edge-tts with WordBoundary extraction...")
    all_word_boundaries = []
    
    temp_files = []
    
    for i, seg in enumerate(segments):
        text = seg["text"]
        temp_path = os.path.join(WORKSPACE, f"seg_{i}.mp3")
        temp_files.append(temp_path)
        
        communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural")
        seg_boundaries = []
        
        with open(temp_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    # Convert 100ns ticks to milliseconds
                    start_ms = chunk["offset"] / 10000
                    duration_ms = chunk["duration"] / 10000
                    seg_boundaries.append({
                        "text": chunk["text"],
                        "start": start_ms,
                        "duration": duration_ms,
                        "seg_index": i
                    })
        
        all_word_boundaries.append(seg_boundaries)

    # Concatenate audio files and get offsets
    concat_list = os.path.join(WORKSPACE, "concat.txt")
    with open(concat_list, "w") as f:
        for t in temp_files:
            f.write(f"file '{t}'\n")
            
    final_audio_path = os.path.join(WORKSPACE, "final_voiceover.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", final_audio_path], check=True)
    
    # Probe each segment to get exact duration
    global_boundaries = []
    current_offset_ms = 0
    
    for i, seg_bounds in enumerate(all_word_boundaries):
        seg_path = temp_files[i]
        # ffprobe duration
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", seg_path], capture_output=True, text=True)
        seg_dur = float(probe.stdout.strip()) * 1000.0
        
        for wb in seg_bounds:
            global_boundaries.append({
                "text": wb["text"],
                "start": current_offset_ms + wb["start"],
                "duration": wb["duration"],
                "seg_index": i
            })
            
        current_offset_ms += seg_dur

    logger.info(f"Audio generated. Total duration: {current_offset_ms}ms. Total words: {len(global_boundaries)}")
    return final_audio_path, global_boundaries, current_offset_ms

# ==========================================
# 4. ASS SUBTITLE GENERATION (KARAOKE)
# ==========================================
def generate_ass_subtitle(word_boundaries, total_duration_ms):
    logger.info("Generating ASS subtitle file with karaoke timings...")
    ass_path = os.path.join(WORKSPACE, "captions.ass")
    
    # Group words into chunks of 3 or max 1.2s
    chunks = []
    current_chunk = []
    current_start = 0
    
    for wb in word_boundaries:
        if not current_chunk:
            current_start = wb["start"]
        current_chunk.append(wb)
        
        chunk_dur = (wb["start"] + wb["duration"]) - current_start
        if len(current_chunk) >= 3 or chunk_dur > 1200:
            chunks.append({
                "words": current_chunk,
                "start": current_start,
                "end": wb["start"] + wb["duration"]
            })
            current_chunk = []
            
    if current_chunk:
        chunks.append({
            "words": current_chunk,
            "start": current_start,
            "end": current_chunk[-1]["start"] + current_chunk[-1]["duration"]
        })

    def fmt_time(ms):
        s = ms / 1000.0
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,80,&H00FFFF,&HFFFFFF,&H000000,&H80000000,1,0,0,0,100,100,0,0,1,6,2,2,80,80,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        for chunk in chunks:
            start_t = fmt_time(chunk["start"])
            end_t = fmt_time(chunk["end"])
            
            # Build karaoke string: {\k20}Word {\k30}Word
            # \k duration is in 1/100ths of a second (centiseconds)
            text_parts = []
            for i, wb in enumerate(chunk["words"]):
                dur_cs = int(wb["duration"] / 10)
                if dur_cs < 1: dur_cs = 1
                # Add gap to next word if exists
                if i < len(chunk["words"]) - 1:
                    next_start = chunk["words"][i+1]["start"]
                    gap_cs = int((next_start - (wb["start"] + wb["duration"])) / 10)
                    if gap_cs > 0:
                        dur_cs += gap_cs
                text_parts.append(f"{{\\k{dur_cs}}}{wb['text']}")
                
            line_text = " ".join(text_parts)
            f.write(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{line_text}\n")
            
    logger.info("ASS file generated.")
    return ass_path

# ==========================================
# 5. ASSET FETCHING & PROCESSING
# ==========================================
def fetch_broll(query, index):
    logger.info(f"Fetching B-roll for: {query}")
    asset_path = os.path.join(WORKSPACE, f"asset_{index}.mp4")
    image_fallback = os.path.join(WORKSPACE, f"asset_{index}.jpg")
    
    # 1. Try Pexels Video
    if PEXELS_API_KEY:
        try:
            headers = {"Authorization": PEXELS_API_KEY}
            url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200 and r.json().get("videos"):
                videos = r.json()["videos"]
                vid = random.choice(videos)
                # Find 720p or higher HD file
                file_url = None
                for f in vid["video_files"]:
                    if f["quality"] == "hd" and f["width"] >= 720:
                        file_url = f["link"]
                        break
                if not file_url and vid["video_files"]:
                    file_url = vid["video_files"][0]["link"]
                    
                if file_url:
                    vid_resp = requests.get(file_url, timeout=30)
                    with open(asset_path, "wb") as f:
                        f.write(vid_resp.content)
                    logger.info(f"Downloaded Pexels video for segment {index}")
                    return asset_path, "video"
        except Exception as e:
            logger.warning(f"Pexels video failed: {e}")

    # 2. Try Unsplash Image
    if UNSPLASH_ACCESS_KEY:
        try:
            url = f"https://api.unsplash.com/search/photos?query={query}&orientation=portrait&client_id={UNSPLASH_ACCESS_KEY}"
            r = requests.get(url, timeout=10)
            if r.status_code == 200 and r.json().get("results"):
                img_url = r.json()["results"][0]["urls"]["regular"]
                img_resp = requests.get(img_url, timeout=15)
                with open(image_fallback, "wb") as f:
                    f.write(img_resp.content)
                logger.info(f"Downloaded Unsplash image for segment {index}")
                return image_fallback, "image"
        except Exception as e:
            logger.warning(f"Unsplash failed: {e}")

    # 3. Fallback to solid color background
    logger.warning(f"Using fallback gradient for segment {index}")
    img = Image.new("RGB", (RES_W, RES_H), color=(10, 10, 30))
    img.save(image_fallback, "JPEG")
    return image_fallback, "image"

def process_segment_video(asset_path, asset_type, duration, index):
    out_path = os.path.join(WORKSPACE, f"seg_vid_{index}.mp4")
    frames = int(duration * FPS)
    
    if asset_type == "video":
        vf = f"scale={RES_W}:{RES_H}:force_original_aspect_ratio=increase,crop={RES_W}:{RES_H},setsar=1,fps={FPS}"
        cmd = [
            "ffmpeg", "-y", "-i", asset_path, "-t", str(duration),
            "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_path
        ]
    else:
        # Image with zoompan
        # Calculate zoompan duration based on frames
        vf = (
            f"scale={RES_W*2}:{RES_H*2}:force_original_aspect_ratio=increase,"
            f"crop={RES_W*2}:{RES_H*2},"
            f"zoompan=z='min(zoom+0.0008,1.15)':d={frames}:s={RES_W}x{RES_H}:fps={FPS},setsar=1"
        )
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", asset_path, "-t", str(duration),
            "-vf", vf, "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out_path
        ]
        
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg segment processing failed: {e.stderr.decode()}")
        raise

# ==========================================
# 6. FINAL VIDEO ASSEMBLY
# ==========================================
def get_audio_duration(audio_path):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True
    )
    return float(probe.stdout.strip())

def concat_segments(seg_paths, audio_path, ass_path):
    logger.info("Concatenating segments and burning subtitles...")
    concat_list = os.path.join(WORKSPACE, "vid_concat.txt")
    with open(concat_list, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")
            
    video_only = os.path.join(WORKSPACE, "video_only.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", video_only], check=True)
    
    final_output = "output_video.mp4"
    # Ensure ass path is properly formatted for ffmpeg filter (escape colons)
    ass_filter = ass_path.replace("/", "\\/").replace(":", "\\:")
    
    vf = f"ass='{ass_filter}'"
    
    cmd = [
        "ffmpeg", "-y", "-i", video_only, "-i", audio_path,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "26",
        "-maxrate", "4M", "-bufsize", "8M",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", final_output
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"Final video created: {final_output}")
        return final_output
    except subprocess.CalledProcessError as e:
        logger.error(f"Final assembly failed: {e.stderr.decode()}")
        raise

# ==========================================
# 7. THUMBNAIL GENERATION
# ==========================================
def generate_thumbnail(title):
    logger.info("Generating thumbnail...")
    thumb_path = "thumbnail.jpg"
    # Extract a frame from 2 seconds into the video
    subprocess.run(["ffmpeg", "-y", "-i", "output_video.mp4", "-ss", "00:00:02", "-vframes", "1", "-q:v", "2", "temp_frame.jpg"], check=True)
    
    img = Image.open("temp_frame.jpg")
    draw = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", 70)
    except:
        font = ImageFont.load_default()
        
    # Wrap text
    lines = wrap(title, width=20)
    y = 1400
    
    # Draw text with background box
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (img.width - tw) / 2
        # Draw black box
        draw.rectangle([x-10, y-10, x+tw+10, y+th+10], fill=(0,0,0))
        draw.text((x, y), line, font=font, fill=(255, 255, 0))
        y += th + 20
        
    img.save(thumb_path, "JPEG", quality=85)
    logger.info("Thumbnail generated.")
    return thumb_path

# ==========================================
# 8. TELEGRAM DELIVERY
# ==========================================
def send_telegram(video_path, thumb_path, metadata):
    logger.info("Sending to Telegram...")
    token = TELEGRAM_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    
    file_size = os.path.getsize(video_path)
    max_size = 50 * 1024 * 1024  # 50MB limit
    
    with open(video_path, "rb") as v, open(thumb_path, "rb") as t:
        files = {"video": v}
        if file_size <= max_size:
            files["thumbnail"] = t
            
        data = {
            "chat_id": chat_id,
            "caption": metadata[:1024],
            "parse_mode": "HTML",
            "supports_streaming": True
        }
        
        try:
            r = requests.post(url, files=files, data=data, timeout=120)
            if r.status_code == 200:
                logger.info("Video sent successfully.")
            else:
                logger.error(f"Telegram failed: {r.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

# ==========================================
# 9. MAIN EXECUTION
# ==========================================
async def main():
    start_time = time.time()
    logger.info("=== Ajeebology Shorts Pipeline Started ===")
    
    # 1. Research
    research_text, sources = research_topic()
    
    # 2. Script
    script = generate_script(research_text)
    
    # 3. Audio & Timestamps
    audio_path, word_boundaries, total_dur_ms = await generate_audio_and_timestamps(script["segments"])
    total_dur_s = total_dur_ms / 1000.0
    
    # 4. Subtitles
    ass_path = generate_ass_subtitle(word_boundaries, total_dur_ms)
    
    # 5. Assets & Segment Processing
    seg_videos = []
    # Calculate proportional duration for each segment based on word count
    seg_durations = []
    total_words = sum(len([w for w in word_boundaries if w['seg_index'] == i]) for i in range(len(script['segments'])))
    
    # More accurate: use actual audio duration per segment
    seg_audio_durations = []
    for i in range(len(script['segments'])):
        seg_words = [w for w in word_boundaries if w['seg_index'] == i]
        if seg_words:
            start = seg_words[0]['start']
            end = seg_words[-1]['start'] + seg_words[-1]['duration']
            seg_durations.append((end - start) / 1000.0 + 0.3) # Add 0.3s padding
        else:
            seg_durations.append(2.0) # fallback
            
    # Normalize durations to match total audio length
    dur_sum = sum(seg_durations)
    seg_durations = [d * (total_dur_s / dur_sum) for d in seg_durations]
    
    for i, seg in enumerate(script["segments"]):
        asset_path, asset_type = fetch_broll(seg["search_query"], i)
        vid_path = process_segment_video(asset_path, asset_type, seg_durations[i], i)
        seg_videos.append(vid_path)
        
    # 6. Final Assembly
    final_video = concat_segments(seg_videos, audio_path, ass_path)
    
    # 7. Thumbnail
    thumb = generate_thumbnail(script["title"])
    
    # 8. Metadata
    artifact_url = f"https://github.com/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}"
    metadata = (
        f"🎬 <b>Title:</b> {script['title']}\n"
        f"🌍 <b>English Title:</b> {script['english_title']}\n"
        f"📂 <b>Category:</b> {script['category']}\n\n"
        f"📝 <b>Description:</b>\n{script['description']}\n\n"
        f"🏷️ <b>Tags:</b> {', '.join(script['tags'])}\n"
        f"#️⃣ <b>Hashtags:</b> {' '.join(script['hashtags'])}\n\n"
        f"🔗 <b>Sources:</b>\n" + "\n".join(sources) + f"\n\n"
        f"⏱️ <b>Runtime:</b> {total_dur_s:.2f}s\n"
        f"🔗 <b>Artifacts:</b> <a href='{artifact_url}'>Download Here</a>"
    )
    
    # Save metadata locally for artifact
    with open("metadata.txt", "w", encoding="utf-8") as f:
        f.write(metadata.replace("<b>", "").replace("</b>", "").replace("<a href='", "").replace("'>", " ").replace("</a>", ""))
        
    # 9. Deliver
    send_telegram(final_video, thumb, metadata)
    
    elapsed = time.time() - start_time
    logger.info(f"=== Pipeline Completed in {elapsed:.2f}s ===")

if __name__ == "__main__":
    asyncio.run(main())
        
        
        
 
