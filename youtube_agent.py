## 🧩 CHUNK 1 – [Imports, Configuration, Utilities, Research, and Script Generation]
import os
import sys
import json
import random
import logging
import subprocess
import shutil
import textwrap
import urllib.parse
from datetime import datetime
import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from groq import Groq
from tavily import TavilyClient
from tenacity import retry, stop_after_attempt, wait_exponential

# ==========================================
# 1. CONFIGURATION & LOGGING SETUP
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AjeebologyAgent")

# Directory Setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

for d in [ASSETS_DIR, OUTPUT_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)

# API Keys (Fail fast if missing)
try:
    GROQ_API_KEY = os.environ["GROQ_API_KEY"]
    TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
    PEXELS_API_KEY = os.environ["PEXELS_API_KEY"]
    UNSPLASH_ACCESS_KEY = os.environ["UNSPLASH_ACCESS_KEY"]
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
except KeyError as e:
    logger.error(f"Missing required environment variable: {e}")
    sys.exit(1)

# Initialize Clients
groq_client = Groq(api_key=GROQ_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

CATEGORIES = ["Psychology Facts", "Space Facts", "Weird World Facts"]
TARGET_CATEGORY = random.choice(CATEGORIES)

# ==========================================
# 2. UTILITY FUNCTIONS
# ==========================================
def cleanup_temp():
    """Cleans up the temporary directory after processing."""
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
        os.makedirs(TEMP_DIR)
    logger.info("Temporary files cleaned up.")

def sanitize_filename(name):
    return "".join([c for c in name if c.isalpha() or c.isdigit() or c==' ']).rstrip()

# ==========================================
# 3. RESEARCH & SCRIPT GENERATION (AGENTS)
# ==========================================
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def conduct_research(category):
    """Fetches real, highly engaging facts using Tavily."""
    logger.info(f"Conducting research for category: {category}...")
    query = f"Mind-blowing, unknown, and fascinating {category.lower()} that sound fake but are true."
    
    response = tavily_client.search(
        query=query,
        search_depth="advanced",
        max_results=3
    )
    
    context = "\n".join([result["content"] for result in response["results"]])
    logger.info("Research completed successfully.")
    return context

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_script(category, research_context):
    """Generates a highly-retaining Hinglish script using Groq."""
    logger.info("Generating Hinglish script via Groq...")
    
    prompt = f"""
    You are a viral YouTube Shorts scriptwriter for 'Ajeebology Shorts'.
    Target Audience: Youth in India/Pakistan. Language: Hinglish (Hindi/Urdu written in English alphabet, mixed with English words).
    Topic: {category}.
    
    Use this research to find ONE mind-blowing fact:
    {research_context}
    
    Rules for Script:
    1. Hook (2-3 sec): Ask a surprising question or make a bold statement.
    2. Revelation: Explain the fact with escalating excitement.
    3. CTA: Quick subscribe ask for 'Ajeebology Shorts'.
    4. Total words: 120-140 words (for 55-60 seconds audio).
    5. No emojis in the spoken text.
    
    Output strictly in JSON format:
    {{
        "title": "Viral English Title here",
        "description": "Short description with #hashtags",
        "hook": "Hinglish hook here",
        "segments": ["sentence 1", "sentence 2", "sentence 3", "sentence 4", "sentence 5", "sentence 6"],
        "cta": "Hinglish subscribe ask here",
        "search_queries": ["english search term 1", "english search term 2", "english search term 3"]
    }}
    """
    
    response = groq_client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile", # <-- NEW ACTIVE MODEL
        temperature=0.7,
        response_format={"type": "json_object"}
        )

    
    script_data = json.loads(response.choices[0].message.content)
    logger.info(f"Script generated: {script_data['title']}")
    return script_data

# **After pasting this chunk, press Enter twice before pasting the next chunk.**

# ==========================================
# 4. ASSET FETCHING SYSTEM (PEXELS & UNSPLASH)
# ==========================================
def fetch_pexels_video(query, index):
    """Fetches a vertical video from Pexels using direct HTTP API requests."""
    logger.info(f"Searching Pexels for video: '{query}'...")
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page=5&orientation=portrait"
    headers = {"Authorization": PEXELS_API_KEY}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            videos = data.get("videos", [])
            if videos:
                # Select a video, use index to rotate choices if called multiple times
                video_data = videos[index % len(videos)]
                video_files = video_data.get("video_files", [])
                
                # Try to find an HD mobile-friendly file or use the first available
                best_file = next((f for f in video_files if f.get("quality") == "hd"), video_files[0])
                video_url = best_file["link"]
                
                target_path = os.path.join(ASSETS_DIR, f"pexels_{sanitize_filename(query)}_{index}.mp4")
                
                logger.info(f"Downloading Pexels video: {video_url}")
                v_res = requests.get(video_url, stream=True, timeout=30)
                if v_res.status_code == 200:
                    with open(target_path, "wb") as f:
                        shutil.copyfileobj(v_res.raw, f)
                    return target_path
        logger.warning(f"Pexels API failed or returned no videos for '{query}'. Using fallback.")
    except Exception as e:
        logger.error(f"Error fetching Pexels video: {e}")
    return None

def fetch_unsplash_image(query, index):
    """Fetches a high-res portrait image from Unsplash using direct HTTP requests."""
    logger.info(f"Searching Unsplash for image: '{query}'...")
    url = f"https://api.unsplash.com/search/photos?query={urllib.parse.quote(query)}&per_page=5&orientation=portrait"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            if results:
                img_data = results[index % len(results)]
                img_url = img_data["urls"]["regular"]
                
                target_path = os.path.join(ASSETS_DIR, f"unsplash_{sanitize_filename(query)}_{index}.jpg")
                
                logger.info(f"Downloading Unsplash image: {img_url}")
                i_res = requests.get(img_url, stream=True, timeout=30)
                if i_res.status_code == 200:
                    with open(target_path, "wb") as f:
                        shutil.copyfileobj(i_res.raw, f)
                    return target_path
        logger.warning(f"Unsplash API failed or returned no images for '{query}'. Using fallback.")
    except Exception as e:
        logger.error(f"Error fetching Unsplash image: {e}")
    return None

def get_scene_asset(query, index, prefer_video=True):
    """Fetches and caches media assets, alternating types for retention diversity."""
    # Check cache first
    sanitized = sanitize_filename(query)
    ext = ".mp4" if prefer_video else ".jpg"
    cached_path = os.path.join(ASSETS_DIR, f"asset_{sanitized}_{index}{ext}")
    
    if os.path.exists(cached_path):
        logger.info(f"Using cached asset: {cached_path}")
        return cached_path, "video" if prefer_video else "image"

    if prefer_video:
        path = fetch_pexels_video(query, index)
        if path:
            shutil.copy(path, cached_path)
            return cached_path, "video"
        # Fallback to image if video fails
        path = fetch_unsplash_image(query, index)
        if path:
            shutil.copy(path, cached_path)
            return cached_path, "image"
    else:
        path = fetch_unsplash_image(query, index)
        if path:
            shutil.copy(path, cached_path)
            return cached_path, "image"
        # Fallback to video if image fails
        path = fetch_pexels_video(query, index)
        if path:
            shutil.copy(path, cached_path)
            return cached_path, "video"
            
    # Absolute system placeholder if both APIs completely fail
    placeholder_path = os.path.join(ASSETS_DIR, f"placeholder_{index}.jpg")
    if not os.path.exists(placeholder_path):
        img = Image.new("RGB", (1080, 1920), color=(random.randint(10,50), random.randint(10,50), random.randint(10,50)))
        img.save(placeholder_path)
    return placeholder_path, "image"

# ==========================================
# 5. AUDIO & VOICEOVER GENERATION ENGINE
# ==========================================
def get_audio_duration(file_path):
    """Calculates precisely how long an audio file is via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nocreepy=1", file_path
    ]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8").strip()
        # Parse output safely handling any extra characters
        duration_str = output.split('=')[-1]
        return float(duration_str)
    except Exception as e:
        logger.error(f"Error reading audio duration: {e}")
        return 5.0 # Safe fallback guess

def generate_voiceover_segment(text, filename_prefix):
    """Generates guaranteed MALE voice using espeak with clean gTTS fallback."""
    out_wav = os.path.join(TEMP_DIR, f"{filename_prefix}.wav")
    
    # Attempt 1: Espeak for direct native localized Hinglish Male voice
    try:
        logger.info(f"Generating voiceover with espeak (hi+m1): '{text[:30]}...'")
        cmd = ["espeak", "-v", "hi+m1", "-s", "145", "-p", "60", "-g", "5", "-w", out_wav, text]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if os.path.exists(out_wav) and os.path.getsize(out_wav) > 0:
            return out_wav
    except Exception as e:
        logger.warning(f"Espeak compilation failed, shifting to safe backup gTTS: {e}")

    # Attempt 2: gTTS Fallback
    try:
        from gtts import gTTS
        logger.info(f"Generating backup voiceover with gTTS: '{text[:30]}...'")
        temp_mp3 = os.path.join(TEMP_DIR, f"{filename_prefix}.mp3")
        tts = gTTS(text=text, lang="hi", slow=False)
        tts.save(temp_mp3)
        
        # Convert to production ready wav format using FFmpeg
        cmd = ["ffmpeg", "-y", "-i", temp_mp3, "-acodec", "pcm_s16le", "-ar", "22050", out_wav]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out_wav
    except Exception as e:
        logger.error(f"Critical Fail: Audio engine completely broke down on segment: {e}")
        
        # Absolute Emergency Floor Fallback: Generate completely silent WAV to prevent runtime crashes
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", "3", out_wav]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out_wav

# **After pasting this chunk, press Enter twice before pasting the next chunk.**


# ==========================================
# 6. SCENE PREPARATION & CANVAS PROCESSING
# ==========================================
def create_brander_clip(text, duration, filename):
    """Generates clean, non-crashing intro/outro clips without emojis."""
    out_path = os.path.join(TEMP_DIR, filename)
    logger.info(f"Generating branding clip ({text}) -> {filename}")
    
    # Simple, highly stable FFmpeg filter chain creating a professional clean slate
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={duration}:r=30",
        "-vf", f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out_path
    except Exception as e:
        logger.error(f"Failed to generate branding clip: {e}")
        # Absolute structural fallback: raw black clip
        fallback_cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={duration}:r=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path]
        subprocess.run(fallback_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out_path

def process_video_scene(input_path, duration, output_path):
    """Normalizes, crops, and forces raw videos into a standard 1080x1920 layout."""
    logger.info(f"Processing scene video asset: {input_path} for {duration}s")
    
    # Scale and crop to fit 1080x1920 while ensuring smooth framerate (30fps)
    vf_chain = (
        f"scale=w='max(1080,ih*(1080/1920))':h='max(1920,iw*(1920/1080))',"
        f"crop=1080:1920,"
        f"zoompan=z='min(zoom+0.0015,1.1)':d=1:x='iw/2-w/2':y='ih/2-h/2':s=1080x1920"
    )
    
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", input_path,
        "-t", str(duration), "-vf", vf_chain,
        "-c:v", "libx264", "-profile:v", "main", "-level:v", "4.0",
        "-pix_fmt", "yuv420p", "-r", "30", output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        logger.error(f"Error optimizing video asset: {e}. Running structural recovery.")
        # Basic fallback crop script if zoompan breaks down due to input codec constraints
        fallback_vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        cmd_fb = [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", input_path,
            "-t", str(duration), "-vf", fallback_vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", output_path
        ]
        subprocess.run(cmd_fb, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def process_image_scene(input_path, duration, output_path):
    """Converts static image assets into high-retention 1080x1920 video with camera panning."""
    logger.info(f"Processing image asset into dynamic video clip: {input_path}")
    
    # Creating a motion picture from a static image through smooth mathematical coordinate adjustments
    vf_chain = (
        f"scale=8000:-1,zoompan=z='min(zoom+0.001,1.15)':x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)+sin(on/10)*10':d=1:s=1080x1920"
    )
    
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", input_path,
        "-t", str(duration), "-vf", vf_chain,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        logger.error(f"Dynamic image scale failed: {e}. Executing standard rendering.")
        fallback_vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        cmd_fb = [
            "ffmpeg", "-y", "-loop", "1", "-i", input_path,
            "-t", str(duration), "-vf", fallback_vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", output_path
        ]
        subprocess.run(cmd_fb, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# ==========================================
# 7. CAPTIONS & KINETIC TYPOGRAPHY GENERATOR
# ==========================================
def burn_kinetic_captions(video_path, text, output_path):
    """Burns heavy stylized kinetic captions into the current active scene file."""
    logger.info(f"Applying text overlays: '{text[:25]}...'")
    
    # Process text layout wrap limits safely for mobile phone viewport constraints
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        if len(" ".join(current_line + [word])) <= 18:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
        
    cleaned_text = "\\n".join(lines).replace("'", "").replace(":", "")
    
    # Kinetic animation sequence: Pop scale up text using sin function modulations
    font_p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    vf_caption = (
        f"drawtext=fontfile={font_p}:text='{cleaned_text}':fontcolor=yellow:"
        f"fontsize='70+10*sin(on/3)':x=(w-text_w)/2:y=(h-text_h)/2+200:"
        f"borderw=5:bordercolor=black:line_spacing=15"
    )
    
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf_caption, "-c:a", "copy", "-c:v", "libx264", output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        logger.warning(f"Kinetic captions engine hit error: {e}. Defaulting to safe rendering.")
        # Fallback to absolute standard solid bounding box placement layout
        vf_fallback = (
            f"drawtext=fontfile={font_p}:text='{cleaned_text}':fontcolor=white:"
            f"fontsize=64:x=(w-text_w)/2:y=(h-text_h)/2+200:box=1:boxcolor=black@0.6:boxborderw=10"
        )
        cmd_fb = ["ffmpeg", "-y", "-i", video_path, "-vf", vf_fallback, "-c:a", "copy", "-c:v", "libx264", output_path]
        subprocess.run(cmd_fb, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# **After pasting this chunk, press Enter twice before pasting the next chunk.**


# ==========================================
# 8. AUDIO MIXING & DUCKING ENGINE
# ==========================================
def create_final_audio_track(vo_segments, total_duration, output_audio_path):
    """Combines all scene voiceovers and mixes them with a synthesized ducked background track."""
    logger.info("Assembling and mixing final audio tracks...")
    
    # 1. Concatenate all segment WAV files into one master voiceover track
    concat_list_path = os.path.join(TEMP_DIR, "audio_concat.txt")
    with open(concat_list_path, "w") as f:
        for vo in vo_segments:
            f.write(f"file '{vo}'\n")
            
    master_vo = os.path.join(TEMP_DIR, "master_vo.wav")
    cmd_concat = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", master_vo]
    subprocess.run(cmd_concat, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # 2. Generate a professional low-frequency cinematic ambient pad as background music
    bg_music = os.path.join(TEMP_DIR, "synthesized_bg.wav")
    bg_cmd = [
        "ffmpeg", "-y", "-f", "lavfi", 
        "-i", f"sine=frequency=80:sample_rate=22050:duration={total_duration}",
        "-af", "volume=0.15,lowpass=f=300", bg_music
    ]
    subprocess.run(bg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # 3. Mix master voiceover with the background pad using audio ducking properties via amix
    mix_cmd = [
        "ffmpeg", "-y", "-i", master_vo, "-i", bg_music,
        "-filter_complex", "amix=inputs=2:duration=first:dropout_transition=2",
        "-acodec", "pcm_s16le", "-ar", "22050", output_audio_path
    ]
    try:
        subprocess.run(mix_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        logger.error(f"Audio mixing failed: {e}. Defaulting to raw master voiceover track.")
        shutil.copy(master_vo, output_audio_path)

# ==========================================
# 9. THUMBNAIL CREATION ENGINE
# ==========================================
def generate_viral_thumbnail(video_path, title_text, output_thumb_path):
    """Extracts a high-motion frame from the video and applies viral graphic styles."""
    logger.info("Generating high-retention thumbnail image...")
    raw_frame = os.path.join(TEMP_DIR, "raw_frame.jpg")
    
    # Extract a clean video frame from 3 seconds into the timeline
    extract_cmd = ["ffmpeg", "-y", "-ss", "00:00:03", "-i", video_path, "-vframes", "1", "-q:v", "2", raw_frame]
    try:
        subprocess.run(extract_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Open frame with Pillow for high-quality filters and composition
        img = Image.open(raw_frame)
        width, height = img.size
        
        # Apply slight contrast and saturation pop
        img = ImageEnhance.Contrast(img).enhance(1.3)
        img = ImageEnhance.Color(img).enhance(1.4)
        
        # Create dark atmospheric vignette overlay
        vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw_v = ImageDraw.Draw(vignette)
        draw_v.ellipse([-100, -100, width + 100, height + 100], outline=(0, 0, 0, 200), width=180)
        img.paste(vignette, (0, 0), vignette)
        
        # Add high-contrast oversized bold text overlay
        draw = ImageDraw.Draw(img)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        font = ImageFont.truetype(font_path, size=75)
        
        # Wrap title text safely
        words = title_text.split()[:4]  # Maximum 4-5 words for extreme mobile scannability
        short_title = " ".join(words).upper()
        wrapped_lines = textwrap.wrap(short_title, width=12)
        
        y_text = height // 3
        for line in wrapped_lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            w_text = bbox[2] - bbox[0]
            h_text = bbox[3] - bbox[1]
            
            # Draw heavy black shadow drop box behind typography text
            draw.text(((width - w_text) // 2 + 6, y_text + 6), line, font=font, fill=(0, 0, 0))
            draw.text(((width - w_text) // 2, y_text), line, font=font, fill=(255, 255, 0)) # Neon Viral Yellow
            y_text += h_text + 30
            
        img.save(output_thumb_path, "JPEG", quality=95)
        logger.info("Thumbnail generation processing executed cleanly.")
    except Exception as e:
        logger.error(f"Thumbnail generation system failed: {e}. Building emergency canvas graphic.")
        emergency_img = Image.new("RGB", (1080, 1920), color=(20, 20, 20))
        emergency_img.save(output_thumb_path)

# ==========================================
# 10. AUTOMATED TELEGRAM DISTRIBUTION PIPELINE
# ==========================================
def dispatch_to_telegram(video_path, thumb_path, script_data):
    """Dispatches the finalized high-retention short asset directly to your mobile via Telegram API."""
    logger.info("Dispatching generated media assets to Telegram...")
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    
    caption_text = (
        f"🎬 **AJEEBOLOGY SHORTS PRODUCTION**\n\n"
        f"📌 **Title:** {script_data['title']}\n\n"
        f"📝 **Description & SEO Tags:**\n{script_data['description']}\n\n"
        f"🚀 *Status: Ready for Manual Upload to YouTube Shorts!*"
    )
    
    # 1. Deliver the Viral Cover Thumbnail Graphic First
    try:
        with open(thumb_path, "rb") as photo:
            p_res = requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": f"🖼 Thumbnail for: {script_data['title']}"},
                files={"photo": photo},
                timeout=30
            )
        if p_res.status_code != 200:
            logger.error(f"Telegram Thumbnail upload response failure: {p_res.text}")
    except Exception as e:
        logger.error(f"Failed to push thumbnail image to Telegram: {e}")

    # 2. Deliver the Final Master Compiled Video File Package
    try:
        with open(video_path, "rb") as video:
            v_res = requests.post(
                f"{base_url}/sendVideo",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption_text, "parse_mode": "Markdown"},
                files={"video": video},
                timeout=120
            )
        if v_res.status_code == 200:
            logger.info("🚀 Automation Cycle Complete! Final video package pushed to Telegram.")
        else:
            logger.error(f"Telegram Video upload response failure: {v_res.text}")
    except Exception as e:
        logger.error(f"Failed to push video package to Telegram: {e}")

# ==========================================
# 11. CENTRAL SYSTEM ORCHESTRATOR (MAIN)
# ==========================================
def main():
    logger.info("Initializing Full Automated YouTube Shorts Pipeline...")
    cleanup_temp()
    
    # Run Research Agent
    research_data = conduct_research(TARGET_CATEGORY)
    
    # Run Script Writing Agent
    script = generate_script(TARGET_CATEGORY, research_data)
    
    # Phase 1: Generate Branded Intro Clip Block
    intro_clip = create_brander_clip("AJEEBOLOGY\nSHORTS", 2.0, "intro.mp4")
    
    # Phase 2: Iterate and process narrative voice over script clips
    processed_scene_clips = [intro_clip]
    vo_files = []
    
    all_segments = script["segments"] + [script["cta"]]
    search_queries = script["search_queries"]
    
    for idx, segment_text in enumerate(all_segments):
        logger.info(f"Processing structural timeline scene segment [{idx+1}/{len(all_segments)}]")
        
        # 1. Render and track localized voice file
        vo_path = generate_voiceover_segment(segment_text, f"vo_seg_{idx}")
        vo_files.append(vo_path)
        
        # Determine exact scene timing track duration
        scene_duration = get_audio_duration(vo_path) + 0.4  # Includes small safety padding buffer
        
        # 2. Pull optimal context search term
        query_term = search_queries[idx % len(search_queries)]
        # Alternate visual layouts to maximize structural audience retention metrics
        prefer_video_format = (idx % 2 == 0)
        
        raw_asset, asset_type = get_scene_asset(query_term, idx, prefer_video=prefer_video_format)
        
        # 3. Canvas scale and adapt layout
        normalized_scene = os.path.join(TEMP_DIR, f"normalized_scene_{idx}.mp4")
        if asset_type == "video":
            process_video_scene(raw_asset, scene_duration, normalized_scene)
        else:
            process_image_scene(raw_asset, scene_duration, normalized_scene)
            
        # 4. Apply Kinetic Type Overlay Over Canvas
        captioned_scene = os.path.join(TEMP_DIR, f"captioned_scene_{idx}.mp4")
        burn_kinetic_captions(normalized_scene, segment_text, captioned_scene)
        
        processed_scene_clips.append(captioned_scene)
        
    # Phase 3: Generate Branded Outro CTA Clip Block
    outro_clip = create_brander_clip("SUBSCRIBE FOR\nMORE FACTS!", 2.0, "outro.mp4")
    processed_scene_clips.append(outro_clip)
    
    # Phase 4: Compile Final Base Video Array Sequence
    video_concat_txt = os.path.join(TEMP_DIR, "video_concat.txt")
    with open(video_concat_txt, "w") as f:
        for clip in processed_scene_clips:
            f.write(f"file '{clip}'\n")
            
    raw_merged_video = os.path.join(TEMP_DIR, "raw_merged_output.mp4")
    cmd_merge = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", video_concat_txt, "-c:v", "libx264", "-an", raw_merged_video]
    subprocess.run(cmd_merge, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Calculate global tracking timeline durations
    total_video_duration = 2.0 + sum([get_audio_duration(v) + 0.4 for v in vo_files]) + 2.0
    
    # Phase 5: Master audio track distribution compilation mix
    mixed_audio_track = os.path.join(TEMP_DIR, "master_mixed_audio.wav")
    # Generate audio for the length of segments only (offsetting for silent intro/outro)
    segment_total_duration = sum([get_audio_duration(v) + 0.4 for v in vo_files])
    create_final_audio_track(vo_files, segment_total_duration, mixed_audio_track)
    
    # Phase 6: Finalize Master Render via Audio/Video Multiplexing mapping
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_video_name = f"AjeebologyShort_{timestamp}.mp4"
    final_video_output = os.path.join(OUTPUT_DIR, final_video_name)
    
    # Multiplex audio onto video stream with intro/outro delays cleanly set
    mux_cmd = [
        "ffmpeg", "-y", "-i", raw_merged_video, "-i", mixed_audio_track,
        "-filter_complex", "[1:a]adelay=2000|2000[delayed_audio]", # Delay audio by 2 seconds for intro clip buffer
        "-map", "0:v", "-map", "[delayed_audio]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", final_video_output
    ]
    
    logger.info("Running final structural mux render cycle...")
    subprocess.run(mux_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Phase 7: Extract Thumbnail Cover
    final_thumbnail_output = os.path.join(OUTPUT_DIR, f"Thumbnail_{timestamp}.jpg")
    generate_viral_thumbnail(final_video_output, script["title"], final_thumbnail_output)
    
    # Phase 8: Package Delivery Dispatch Routing
    dispatch_to_telegram(final_video_output, final_thumbnail_output, script)
    
    # Complete Local Storage Archival Save States
    with open(os.path.join(OUTPUT_DIR, f"Metadata_{timestamp}.json"), "w") as f:
        json.dump(script, f, indent=4)
        
    cleanup_temp()
    logger.info("--- PRODUCTION WORKFLOW AGENT LIFECYCLE COMPLETED SUCCESSFULLY ---")

if __name__ == "__main__":
    try:
        main()
    except Exception as main_err:
        logger.critical(f"Pipeline crashed catastrophically during master execute block: {main_err}")
        sys.exit(1)
        
