#!/usr/bin/env python3
"""
Ajeebology Shorts - Telegram Delivery Agent
Sends videos and metadata to Telegram
"""

import os
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from logger import logger_delivery
from config import config
from utils import format_file_size


class TelegramAgent:
    """Delivers videos and metadata via Telegram Bot."""
    
    def __init__(self):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        logger_delivery.info("TelegramAgent initialized")
    
    def send_video(self, video_path: str, script, artifact_url: str = "") -> bool:
        """Send video with full metadata to Telegram."""
        if not self.token or not self.chat_id:
            logger_delivery.warning("Telegram credentials not configured")
            return False
        
        logger_delivery.info(f"Preparing to send video: {video_path}")
        
        caption = self._build_caption(script, artifact_url)
        file_size = os.path.getsize(video_path)
        max_size = config.TELEGRAM_MAX_FILE_SIZE
        
        try:
            if file_size <= max_size:
                logger_delivery.info(f"Sending video ({format_file_size(file_size)})...")
                with open(video_path, "rb") as f:
                    files = {"video": f}
                    data = {
                        "chat_id": self.chat_id,
                        "caption": caption[:1024],
                        "parse_mode": "HTML"
                    }
                    resp = requests.post(
                        f"{self.base_url}/sendVideo",
                        data=data, files=files, timeout=120
                    )
                    result = resp.json()
                    if result.get("ok"):
                        logger_delivery.info("Video sent successfully!")
                        return True
                    else:
                        logger_delivery.error(f"Telegram error: {result}")
            else:
                logger_delivery.warning(f"Video too large ({format_file_size(file_size)}), sending metadata only")
                self._send_text(caption)
                
                # Send thumbnail
                thumbnail_path = self._generate_thumbnail(script)
                if thumbnail_path:
                    with open(thumbnail_path, "rb") as f:
                        files = {"photo": f}
                        data = {
                            "chat_id": self.chat_id,
                            "caption": f"<b>{script.seo_title}</b>\n\nVideo too large. Download from GitHub Actions artifacts.",
                            "parse_mode": "HTML"
                        }
                        requests.post(
                            f"{self.base_url}/sendPhoto",
                            data=data, files=files, timeout=60
                        )
        
        except Exception as e:
            logger_delivery.error(f"Telegram send error: {e}", exc_info=True)
            return False
        
        return False
    
    def _build_caption(self, script, artifact_url: str) -> str:
        """Build comprehensive Telegram caption with metadata."""
        tags_str = ", ".join(script.tags[:15])
        hashtags_str = " ".join(script.hashtags[:10])
        
        caption = f"""<b>🎬 {script.seo_title}</b>

<b>📋 Title:</b> {script.title}
<b>📁 Category:</b> {script.category}

<b>📝 Description:</b>
{script.description}

<b>🏷 Tags:</b>
{tags_str}

<b>#️⃣ Hashtags:</b>
{hashtags_str}

<b>⬆️ Upload Time:</b> 5:00 PM PKT Daily

<b>📥 Download:</b> {artifact_url if artifact_url else 'Check GitHub Actions artifacts'}

#AjeebologyShorts #YouTubeShorts #DailyFacts"""
        
        return caption
    
    def _send_text(self, text: str) -> bool:
        """Send text message to Telegram."""
        try:
            data = {
                "chat_id": self.chat_id,
                "text": text[:4096],
                "parse_mode": "HTML"
            }
            resp = requests.post(f"{self.base_url}/sendMessage", data=data, timeout=30)
            if resp.json().get("ok"):
                logger_delivery.info("Text message sent successfully")
                return True
        except Exception as e:
            logger_delivery.error(f"Text send error: {e}")
        return False
    
    def _generate_thumbnail(self, script) -> Optional[str]:
        """Generate thumbnail image for video."""
        try:
            img = Image.new("RGB", (1280, 720), config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(img)
            
            # Gradient background
            for y in range(720):
                ratio = y / 720
                r = int(10 + ratio * 30)
                g = int(5 + ratio * 20)
                b = int(25 + ratio * 50)
                draw.line([(0, y), (1280, y)], fill=(r, g, b))
            
            # Title text
            font = self._load_font_thumbnail(80)
            words = script.title.split()
            lines = []
            current = []
            
            for word in words:
                test = " ".join(current + [word])
                bbox = font.getbbox(test)
                if bbox and bbox[2] > 1200:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            
            if current:
                lines.append(" ".join(current))
            
            y = 360 - len(lines) * 50
            for line in lines:
                # Draw with glow
                for offset in range(8, 0, -2):
                    draw.text((640 + offset, y), line, font=font, fill=(0, 200, 200), anchor="mm")
                    draw.text((640 - offset, y), line, font=font, fill=(0, 200, 200), anchor="mm")
                draw.text((640, y), line, font=font, fill=(255, 255, 255), anchor="mm")
                y += 100
            
            # Channel name
            font_small = self._load_font_thumbnail(40)
            draw.text((640, 650), "@AjeebologyShorts", font=font_small, fill=config.COLOR_ACCENT, anchor="mm")
            
            path = str(config.OUTPUT_DIR / "thumbnail.jpg")
            img.save(path, "JPEG", quality=90)
            logger_delivery.info(f"Thumbnail generated: {path}")
            return path
        
        except Exception as e:
            logger_delivery.error(f"Thumbnail generation error: {e}")
            return None
    
    def _load_font_thumbnail(self, size: int) -> ImageFont.FreeTypeFont:
        """Load font for thumbnail generation."""
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        ]
        for p in paths:
            try:
                return ImageFont.truetype(p, size)
            except:
                continue
        return ImageFont.load_default()
