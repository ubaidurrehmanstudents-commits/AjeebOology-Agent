#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ajeebology Shorts - Production Pipeline v1.0
Single file implementation. Only youtube_agent.py + youtube_agent.yml allowed.
"""

import os
import sys
import json
import time
import random
import logging
import subprocess
import tempfile
import shutil
import textwrap
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote_plus

try:
    from groq import Groq
    from tavily import TavilyClient
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import requests
except ImportError as e:
    print(f"CRITICAL: Missing dependency {e}")
    print("Run: pip install groq tavily-python pillow requests")
    sys.exit(1)

@dataclass
class Config:
    target_width: int = 1080
    target_height: int = 1920
    target_fps: int = 30
    target_duration: int = int(os.getenv("TARGET_DURATION", "60"))
    temp_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="ajeebology_")))
    output_dir: Path = Path("output")
    logs_dir: Path = Path("logs")
    scene_change_interval: float = 2.5
    zoom_speed: float = 0.0008
    caption_font_size: int = 90
    caption_max_chars: int = 32
    words_per_caption: int = 3
    groq_model: str = "llama-3.3-70b-versatile"
    groq_max_tokens: int = 1800
    max_retries: int = 3
    retry_delay: float = 2.0
    request_timeout: int = 30

class Logger:
    def __init__(self, logs_dir: Path):
        logs_dir.mkdir(exist_ok=True)
        log_file = logs_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.logger = logging.getLogger("Ajeebology")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)
        self.start_time = time.time()
        self.logs: List[str] = []
        self.info(f"Logging initialized: {log_file}")

    def info(self, msg: str):
        self.logger.info(msg)
        self.logs.append(f" {msg}")

    def error(self, msg: str):
        self.logger.error(msg)
        self.logs.append(f"[ERROR] {msg}")

    def warning(self, msg: str):
        self.logger.warning(msg)
        self.logs.append(f"[WARNING] {msg}")

    def get_runtime_stats(self) -> Dict:
        return {
            "total_runtime_seconds": round(time.time() - self.start_time, 2),
            "timestamp": datetime.now().isoformat(),
            "recent_logs": self.logs[-15:]
        }

logger = Logger(Path("logs"))
config = Config()

def validate_secrets() -> Dict[str, str]:
    required = [
        "GROQ_API_KEY", "TAVILY_API_KEY", "PEXELS_API_KEY",
        "UNSPLASH_ACCESS_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"
    ]
    secrets = {}
    missing = []
    for key in required:
        val = os.getenv(key)
        if not val or val.strip() == "":
            missing.append(key)
        else:
            secrets[key] = val.strip()
    if missing:
        logger.error(f"Missing required secrets: {', '.join(missing)}")
        sys.exit(1)
    logger.info("All secrets validated successfully")
    return secrets

def validate_ffmpeg() -> None:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        if "ffmpeg" not in result.stdout.lower():
            raise RuntimeError("FFmpeg not found")
        version = result.stdout.split('\n')[0]
        logger.info(f"FFmpeg validated: {version}")
    except Exception as e:
        logger.error(f"FFmpeg validation failed: {e}")
        sys.exit(1)

def run_command(cmd: List[str], timeout: int = 120) -> Tuple[bool, str, str]:
    for attempt in range(config.max_retries):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                return True, result.stdout, result.stderr
            logger.warning(f"Attempt {attempt+1}/{config.max_retries} failed: {result.stderr[:200]}")
            time.sleep(config.retry_delay * (attempt + 1))
        except subprocess.TimeoutExpired:
            logger.warning(f"Attempt {attempt+1} timeout after {timeout}s")
            time.sleep(config.retry_delay * (attempt + 1))
        except Exception as e:
            logger.error(f"Command error: {e}")
            time.sleep(config.retry_delay * (attempt + 1))
    return False, "", "All retry attempts failed"

class Researcher:
    def __init__(self, api_key: str):
        self.client = TavilyClient(api_key=api_key)

    def research_topic(self, topic: str) -> Dict:
        logger.info(f"Researching: {topic}")
        try:
            response = self.client.search(
                query=f"{topic} fact psychology space weird world",
                search_depth="advanced",
                max_results=5,
                include_answer=True,
                include_raw_content=False
            )
            facts = []
            sources = []
            if response.get("answer"):
                facts.append(response["answer"])
            for result in response.get("results", []):
                content = result.get("content", "")
                if content and len(content) > 30:
                    facts.append(content)
                sources.append({
                    "title": result.get("title", "Unknown Source"),
                    "url": result.get("url", ""),
                    "score": result.get("score", 0)
                })
            logger.info(f"Research complete: {len(facts)} facts, {len(sources)} sources")
            return {"facts": facts[:4], "sources": sources[:5]}
        except Exception as e:
            logger.error(f"Research failed: {e}. Using fallback.")
            return {
                "facts": ["Your brain makes 35,000 decisions daily and 90% are subconscious!"],
                "sources": [{"title": "Fallback Data", "url": "internal", "score": 1.0}]
            }

class ScriptGenerator:
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)

    def generate_script(self, facts: List[str], topic: str, duration: int) -> Dict:
        logger.info("Generating Hinglish script with Groq")
        facts_text = "\n".join(facts)
        target_words = int(duration * 1.6)
        prompt = f"""You are a YouTube Shorts script writer for 'Ajeebology Shorts'.
Channel: Psychology Facts, Space Facts, Weird World Facts
Language: Hinglish - conversational Hindi + English mix, Gen-Z tone
Target Duration: {duration} seconds
Target Words: {target_words}
Facts to use: {facts_text}
Topic: {topic}
RETENTION RULES:
1. Hook in first 1.5 seconds: shocking question or statement
2. Change visual/idea every 2-3 seconds
3. Pattern interrupts: "Wait...", "Lekin twist ye hai", "Number 3 sunke dimaag hil jayega"
4. End with curiosity loop + CTA
OUTPUT JSON ONLY:
{{"title": "5-7 words, clickbait but honest","description": "2 lines + hashtags at end","tags": ["psychology", "facts", "shorts"],"hashtags": "#Psychology #Facts #Shorts #Ajeebology","category": "Education","segments": [{{"text": "Hook line", "duration": 2.5, "visual": "zoom_in_shock"}}]}}"""
        for attempt in range(config.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=config.groq_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                    max_tokens=config.groq_max_tokens,
                    response_format={"type": "json_object"}
                )
                content = response.choices[0].message.content
                data = json.loads(content)
                total_duration = sum(s["duration"] for s in data.get("segments", []))
                if abs(total_duration - duration) > 5:
                    scale = duration / total_duration if total_duration > 0 else 1.0
                    for seg in data["segments"]:
                        seg["duration"] = round(seg["duration"] * scale, 2)
                logger.info(f"Script generated: {data['title']}")
                return data
            except Exception as e:
                logger.error(f"Groq API error attempt {attempt+1}: {e}")
                time.sleep(config.retry_delay * (attempt + 1))
        logger.warning("Using fallback script")
        return {
            "title": "Weird Psychology Fact",
            "description": "Ye fact sunke tumhara dimaag hil jayega! #psychology #facts",
            "tags": ["psychology", "facts", "shorts", "mind"],
            "hashtags": "#Psychology #Facts #Shorts #Ajeebology",
            "category": "Education",
            "segments": [
                {"text": "Kya tumhe pata hai tumhara dimaag roz 60,000 thoughts banata hai?", "duration": 3.0, "visual": "zoom_in_shock"},
                {"text": "Aur sabse crazy baat ye hai ki 95% thoughts kal wale hi hote hain!", "duration": 3.5, "visual": "cut_new_footage"},
                {"text": "Isi liye change karna itna mushkil lagta hai", "duration": 2.5, "visual": "pan_left"},
                {"text": "Lekin science kehti hai 21 din ki practice se brain rewire ho jata hai", "duration": 3.5, "visual": "fast_zoom"},
                {"text": "Comment karo tum konsa naya habit start karna chahte ho!", "duration": 2.5, "visual": "bounce_out"}
            ]
        }

class MediaFetcher:
    def __init__(self, pexels_key: str, unsplash_key: str):
        self.pexels_key = pexels_key
        self.unsplash_key = unsplash_key

    def fetch_pexels_videos(self, query: str, count: int = 6) -> List:
        logger.info(f"Fetching Pexels videos for: {query}")
        videos = []
        try:
            url = f"https://api.pexels.com/videos/search?query={quote_plus(query)}&per_page={count}&orientation=portrait"
            req = Request(url, headers={"Authorization": self.pexels_key})
            with urlopen(req, timeout=config.request_timeout) as response:
                data = json.loads(response.read().decode())
            for i, video in enumerate(data.get("videos", [])):
                try:
                    video_files = video.get("video_files", [])
                    hd_file = next((vf for vf in video_files if vf["quality"] == "hd"), video_files[0])
                    download_url = hd_file["link"]
                    path = config.temp_dir / f"pexels_{i}.mp4"
                    with urlopen(download_url, timeout=60) as vid_resp:
                        path.write_bytes(vid_resp.read())
                    videos.append(path)
                    logger.info(f"Downloaded video {i+1}/{count}")
                except Exception as e:
                    logger.warning(f"Video download failed: {e}")
                    continue
        except Exception as e:
            logger.error(f"Pexels API error: {e}")
        return videos

    def fetch_unsplash_images(self, query: str, count: int = 5) -> List:
        logger.info(f"Fetching Unsplash images for: {query}")
        images = []
        try:
            url = f"https://api.unsplash.com/search/photos?query={quote_plus(query)}&per_page={count}&orientation=portrait"
            req = Request(url, headers={"Authorization": f"Client-ID {self.unsplash_key}"})
            with urlopen(req, timeout=config.request_timeout) as response:
                data = json.loads(response.read().decode())
            for i, photo in enumerate(data.get("results", [])):
                try:
                    download_url = photo["urls"]["regular"]
                    path = config.temp_dir / f"unsplash_{i}.jpg"
                    with urlopen(download_url, timeout=30) as img_resp:
                        path.write_bytes(img_resp.read())
                    images.append(path)
                    logger.info(f"Downloaded image {i+1}/{count}")
                except Exception as e:
                    logger.warning(f"Image download failed: {e}")
                    continue
        except Exception as e:
            logger.error(f"Unsplash API error: {e}")
        return images
    class VideoProcessor:
    def __init__(self):
        pass

    def create_zoom_clip(self, input_path: Path, output_path: Path, duration: float) -> bool:
        is_video = input_path.suffix.lower() == ".mp4"
        if is_video:
            filter_str = f"scale={config.target_width}:{config.target_height}:force_original_aspect_ratio=decrease,crop={config.target_width}:{config.target_height},zoompan=z='1+{config.zoom_speed}*in':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={config.target_width}x{config.target_height}:fps={config.target_fps}"
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-t", str(duration), "-vf", filter_str, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-an", str(output_path)]
        else:
            filter_str = f"scale={config.target_width}:{config.target_height}:force_original_aspect_ratio=decrease,crop={config.target_width}:{config.target_height},zoompan=z='1+{config.zoom_speed}*in':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration * config.target_fps)}:s={config.target_width}x{config.target_height}:fps={config.target_fps}"
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(input_path), "-t", str(duration), "-vf", filter_str, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-an", str(output_path)]
        success, _, _ = run_command(cmd, timeout=180)
        return success

    def _render_caption(self, text: str) -> Image:
        img = Image.new("RGBA", (config.target_width, config.target_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", config.caption_font_size)
        except:
            font = ImageFont.load_default()
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= config.caption_max_chars * 22:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
        y_offset = config.target_height - 500
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (config.target_width - text_width) // 2
            for dx in [-3, -2, -1, 0, 1, 2, 3]:
                for dy in [-3, -2, -1, 0, 1, 2, 3]:
                    if dx!= 0 or dy!= 0:
                        draw.text((x + dx, y_offset + dy), line, font=font, fill=(0, 0, 0, 220))
            draw.text((x, y_offset), line, font=font, fill=(255, 255, 255, 255))
            y_offset += config.caption_font_size + 25
        return img

    def add_captions(self, video_path: Path, segments: List, output_path: Path) -> bool:
        temp_dir = Path(tempfile.mkdtemp(dir=config.temp_dir))
        caption_clips = []
        current_time = 0.0
        try:
            for i, seg in enumerate(segments):
                text = seg["text"]
                duration = seg["duration"]
                caption_img = self._render_caption(text)
                caption_path = temp_dir / f"caption_{i}.png"
                caption_img.save(caption_path)
                segment_path = temp_dir / f"segment_{i}.mp4"
                cmd = ["ffmpeg", "-y", "-i", str(video_path), "-ss", str(current_time), "-t", str(duration), "-i", str(caption_path), "-filter_complex", "[0:v]fade=in:0:15,fade=out:st=duration-0.3:d=0.3[base];[1:v]fade=in:0:10,fade=out:st=duration-0.2:d=0.2[cap];[base][cap]overlay=(W-w)/2:H-h-250:enable=between(t\\,0\\,duration)[out]", "-map", "[out]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-an", str(segment_path)]
                success, _, _ = run_command(cmd, timeout=60)
                if success:
                    caption_clips.append(segment_path)
                current_time += duration
            concat_file = temp_dir / "concat.txt"
            with open(concat_file, "w", encoding="utf-8") as f:
                for clip in caption_clips:
                    f.write(f"file '{clip}'\n")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output_path)]
            success, _, _ = run_command(cmd, timeout=120)
            return success
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def create_thumbnail(self, title: str, output_path: Path) -> None:
        img = Image.new("RGB", (config.target_width, config.target_height), (20, 20, 40))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 120)
        except:
            font = ImageFont.load_default()
        text = title[:25]
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        x = (config.target_width - text_width) // 2
        y = config.target_height // 2
        draw.text((x + 8, y + 8), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=(255, 215, 0))
        img.save(output_path, quality=95)
        logger.info(f"Thumbnail created: {output_path}")

class TelegramSender:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send_video(self, video_path: Path, thumbnail_path: Path, metadata: Dict, stats: Dict) -> bool:
        logger.info("Sending to Telegram")
        sources_text = "\n".join([f"• {s['title'][:50]}" for s in metadata.get("sources", [])[:3]])
        caption = f"""🎬 **{metadata['title']}**
📝 {metadata['description']}
🏷️ Tags: {', '.join(metadata['tags'])}
#️⃣ {metadata['hashtags']}
📂 Category: {metadata['category']}
🔗 Research Sources:
{sources_text}
⚡ Runtime: {stats['total_runtime_seconds']}s
📦 GitHub Run: #{os.getenv('GITHUB_RUN_NUMBER', 'local')}
🕐 {stats['timestamp']}"""
        try:
            with open(video_path, "rb") as video_file, open(thumbnail_path, "rb") as thumb_file:
                files = {"video": video_file, "thumbnail": thumb_file}
                data = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "Markdown", "supports_streaming": True}
                response = requests.post(f"https://api.telegram.org/bot{self.token}/sendVideo", data=data, files=files, timeout=300)
                if response.status_code == 200:
                    logger.info("Telegram delivery successful")
                    return True
                else:
                    logger.error(f"Telegram error: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Telegram delivery failed: {e}")
            return False

def main():
    logger.info("=" * 60)
    logger.info("Ajeebology Shorts Pipeline Started")
    logger.info("=" * 60)
    secrets = validate_secrets()
    validate_ffmpeg()
    config.output_dir.mkdir(exist_ok=True)
    topic = os.getenv("TOPIC", "Psychology fact about human behavior")
    duration = config.target_duration
    try:
        researcher = Researcher(secrets["TAVILY_API_KEY"])
        research_data = researcher.research_topic(topic)
        script_gen = ScriptGenerator(secrets["GROQ_API_KEY"])
        script_data = script_gen.generate_script(research_data["facts"], topic, duration)
        media_fetcher = MediaFetcher(secrets["PEXELS_API_KEY"], secrets["UNSPLASH_ACCESS_KEY"])
        keywords = " ".join(topic.split()[:3])
        videos = media_fetcher.fetch_pexels_videos(keywords, 8)
        images = media_fetcher.fetch_unsplash_images(keywords, 6)
        all_media = videos + images
        if not all_media:
            logger.error("No media downloaded. Exiting.")
            sys.exit(1)
        processor = VideoProcessor()
        clip_duration = config.scene_change_interval
        num_clips = int(duration / clip_duration) + 1
        processed_clips = []
        for i in range(num_clips):
            media = all_media[i % len(all_media)]
            clip_path = config.temp_dir / f"clip_{i}.mp4"
            if processor.create_zoom_clip(media, clip_path, clip_duration):
                processed_clips.append(clip_path)
            else:
                logger.warning(f"Clip {i} creation failed, skipping")
        if not processed_clips:
            logger.error("No clips created successfully")
            sys.exit(1)
        concat_file = config.temp_dir / "concat_raw.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for clip in processed_clips:
                f.write(f"file '{clip}'\n")
        raw_video = config.temp_dir / "raw_video.mp4"
        success, _, _ = run_command(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(raw_video)], timeout=180)
        if not success:
            logger.error("Raw video concat failed")
            sys.exit(1)
        final_video = config.output_dir / f"ajeebology_{int(time.time())}.mp4"
        if not processor.add_captions(raw_video, script_data["segments"], final_video):
            logger.error("Caption addition failed")
            sys.exit(1)
        thumbnail_path = config.output_dir / "thumbnail.jpg"
        processor.create_thumbnail(script_data["title"], thumbnail_path)
        stats = logger.get_runtime_stats()
        script_data["sources"] = research_data["sources"]
        telegram = TelegramSender(secrets["TELEGRAM_TOKEN"], secrets["TELEGRAM_CHAT_ID"])
        telegram.send_video(final_video, thumbnail_path, script_data, stats)
        logger.info("=" * 60)
        logger.info(f"PIPELINE COMPLETE!")
        logger.info(f"Video: {final_video}")
        logger.info(f"Thumbnail: {thumbnail_path}")
        logger.info(f"Runtime: {stats['total_runtime_seconds']}s")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Fatal pipeline error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        if config.temp_dir.exists():
            shutil.rmtree(config.temp_dir, ignore_errors=True)
            logger.info("Temp files cleaned up")

if __name__ == "__main__":
    main()
