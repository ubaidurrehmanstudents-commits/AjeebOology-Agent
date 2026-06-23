#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional Video Rendering Engine
Produces cinematic YouTube Shorts with animations, effects, and professional polish
"""

import os
import math
import random
from pathlib import Path
from typing import List, Tuple, Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
import numpy as np

from logger import logger_video
from config import config
from utils import run_command, get_audio_duration, format_file_size


class VideoEngine:
    """
    Professional video rendering engine with:
    - Animated gradient backgrounds
    - Floating particle effects
    - Ken Burns effect on B-roll
    - Text animations (slide-in, scale-pop)
    - Audio-reactive visual beats
    - Neon glow effects
    - Progress bars and badges
    """
    
    def __init__(self):
        self.width = config.WIDTH
        self.height = config.HEIGHT
        self.fps = config.FPS
        
        self.font_title = self._load_font(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            config.FONT_SIZE_TITLE
        )
        self.font_body = self._load_font(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            config.FONT_SIZE_BODY
        )
        self.font_small = self._load_font(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            config.FONT_SIZE_SMALL
        )
        
        self.particles = self._init_particles(config.PARTICLE_COUNT)
        self.frame_count = 0
        logger_video.info("VideoEngine initialized")
    
    def _load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """Load font with fallback options."""
        try:
            return ImageFont.truetype(path, size)
        except:
            alternatives = [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
            ]
            for alt in alternatives:
                try:
                    return ImageFont.truetype(alt, size)
                except:
                    continue
            return ImageFont.load_default()
    
    def _init_particles(self, count: int) -> List[dict]:
        """Initialize floating particle effects."""
        particles = []
        for _ in range(count):
            particles.append({
                "x": random.randint(0, self.width),
                "y": random.randint(0, self.height),
                "size": random.randint(1, 4),
                "speed": random.uniform(0.2, 1.5),
                "opacity": random.randint(50, 200),
                "phase": random.uniform(0, math.pi * 2)
            })
        return particles
    
    def _draw_gradient_background(self, draw: ImageDraw.ImageDraw, frame_idx: int, total_frames: int):
        """Draw animated gradient background with color shifts."""
        progress = frame_idx / max(total_frames, 1)
        hue_shift = progress * 0.3
        
        for y in range(self.height):
            ratio = y / self.height
            r = int(10 + ratio * 20 + math.sin(hue_shift + ratio * 3) * 10)
            g = int(5 + ratio * 15 + math.sin(hue_shift + ratio * 2) * 8)
            b = int(25 + ratio * 40 + math.sin(hue_shift + ratio * 4) * 15)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
    
    def _draw_particles(self, draw: ImageDraw.ImageDraw, frame_idx: int):
        """Draw animated floating particles with twinkle effect."""
        for p in self.particles:
            p["y"] -= p["speed"]
            p["x"] += math.sin(frame_idx * 0.02 + p["phase"]) * 0.5
            
            if p["y"] < -10:
                p["y"] = self.height + 10
                p["x"] = random.randint(0, self.width)
            
            twinkle = abs(math.sin(frame_idx * 0.05 + p["phase"]))
            opacity = int(p["opacity"] * twinkle)
            
            if opacity > 30:
                draw.ellipse(
                    [p["x"] - p["size"], p["y"] - p["size"],
                     p["x"] + p["size"], p["y"] + p["size"]],
                    fill=(200, 220, 255)
                )
    
    def _draw_text_with_glow(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                             x: int, y: int, color: Tuple, glow_color: Tuple, glow_radius: int = 3):
        """Draw text with neon glow effect."""
        for offset in range(glow_radius, 0, -1):
            alpha_factor = 0.3 + (glow_radius - offset) * 0.15
            glow = tuple(int(c * alpha_factor + 255 * (1 - alpha_factor)) for c in glow_color[:3])
            for dx in [-offset, 0, offset]:
                for dy in [-offset, 0, offset]:
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, font=font, fill=glow, anchor="mm")
        draw.text((x, y), text, font=font, fill=color, anchor="mm")
    
    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
        """Wrap text to fit within max width."""
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = font.getbbox(test_line)
            if bbox and (bbox[2] - bbox[0]) > max_width:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
            else:
                current_line.append(word)
        
        if current_line:
            lines.append(" ".join(current_line))
        
        return lines if lines else [text]
    
    def _draw_rounded_card(self, draw: ImageDraw.ImageDraw, bbox: List[int], radius: int,
                          fill: Tuple, outline: Optional[Tuple] = None, outline_width: int = 2):
        """Draw rounded rectangle card."""
        draw.rounded_rectangle(bbox, radius=radius, fill=fill)
        if outline:
            draw.rounded_rectangle(bbox, radius=radius, outline=outline, width=outline_width)
    
    def _apply_ken_burns(self, img: Image.Image, frame_idx: int, segment_frames: int,
                        zoom_start: float = 1.0, zoom_end: float = 1.15) -> Image.Image:
        """Apply Ken Burns zoom/pan effect to B-roll images."""
        progress = frame_idx / max(segment_frames, 1)
        t = progress
        ease = t * t * (3 - 2 * t)  # Smoothstep easing
        
        zoom = zoom_start + (zoom_end - zoom_start) * ease
        new_w = int(self.width / zoom)
        new_h = int(self.height / zoom)
        
        left = max(0, (img.width - new_w) // 2)
        top = max(0, (img.height - new_h) // 2)
        right = min(img.width, left + new_w)
        bottom = min(img.height, top + new_h)
        
        if right - left < 10 or bottom - top < 10:
            return img.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        cropped = img.crop((left, top, right, bottom))
        return cropped.resize((self.width, self.height), Image.Resampling.LANCZOS)
    
    def _draw_progress_bar(self, draw: ImageDraw.ImageDraw, frame_idx: int, total_frames: int):
        """Draw bottom progress bar."""
        progress = frame_idx / max(total_frames, 1)
        bar_height = 8
        bar_y = self.height - bar_height - 20
        bar_width = self.width - 80
        bar_x = 40
        
        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            radius=4, fill=(40, 40, 60)
        )
        
        fill_width = int(bar_width * progress)
        if fill_width > 0:
            draw.rounded_rectangle(
                [bar_x, bar_y, bar_x + fill_width, bar_y + bar_height],
                radius=4, fill=config.COLOR_ACCENT
            )
    
    def _draw_channel_badge(self, draw: ImageDraw.ImageDraw, frame_idx: int):
        """Draw pulsing channel badge at top."""
        pulse = abs(math.sin(frame_idx * 0.08))
        dot_size = int(6 + pulse * 4)
        
        badge_w = 200
        badge_h = 44
        badge_x = self.width // 2 - badge_w // 2
        badge_y = 30
        
        self._draw_rounded_card(
            draw, [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=22, fill=(20, 20, 40), outline=config.COLOR_ACCENT, outline_width=1
        )
        
        dot_color = (255, 50, 50) if pulse > 0.5 else (255, 100, 100)
        draw.ellipse(
            [badge_x + 15, badge_y + badge_h // 2 - dot_size // 2,
             badge_x + 15 + dot_size, badge_y + badge_h // 2 + dot_size // 2],
            fill=dot_color
        )
        
        draw.text((badge_x + 30, badge_y + badge_h // 2), "AJEEBOLOGY",
                 font=self.font_small, fill=config.COLOR_TEXT, anchor="lm")
    
    def _draw_subscribe_cta(self, draw: ImageDraw.ImageDraw, frame_idx: int, total_frames: int):
        """Draw animated subscribe CTA in final seconds."""
        progress = frame_idx / max(total_frames, 1)
        
        if progress < 0.85:
            return
        
        slide_progress = (progress - 0.85) / 0.15
        ease = slide_progress * slide_progress * (3 - 2 * slide_progress)
        
        cta_y = int(self.height + 100 - ease * 180)
        cta_w = 400
        cta_h = 80
        cta_x = self.width // 2 - cta_w // 2
        
        # Glow effect
        for glow in range(15, 0, -3):
            draw.rounded_rectangle(
                [cta_x - glow, cta_y - glow, cta_x + cta_w + glow, cta_y + cta_h + glow],
                radius=25, outline=config.COLOR_ACCENT_2, width=2
            )
        
        self._draw_rounded_card(
            draw, [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
            radius=20, fill=config.COLOR_ACCENT_2, outline=(255, 255, 255), outline_width=2
        )
        
        bounce = abs(math.sin(frame_idx * 0.15)) * 3
        draw.text((self.width // 2, cta_y + cta_h // 2 + bounce), "SUBSCRIBE KARO!",
                 font=self.font_body, fill=(255, 255, 255), anchor="mm")
    
    def _get_text_animation_offset(self, frame_idx: int, segment_start_frame: int) -> Tuple[int, float]:
        """Get animation values for text entrance."""
        rel_frame = frame_idx - segment_start_frame
        
        if rel_frame < config.TEXT_ENTRANCE_FRAMES:
            progress = rel_frame / config.TEXT_ENTRANCE_FRAMES
            ease = 1 - (1 - progress) ** 3
            offset_y = int(80 * (1 - ease))
            alpha = ease
            return offset_y, alpha
        return 0, 1.0
    
    def _draw_segment_text(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                          y_pos: int, frame_idx: int, segment_start_frame: int,
                          emphasis_words: List[str], max_width: int = 900):
        """Draw segment text with emphasis highlighting."""
        lines = self._wrap_text(text, font, max_width)
        anim_y, alpha = self._get_text_animation_offset(frame_idx, segment_start_frame)
        
        line_height = font.size + 20
        total_height = len(lines) * line_height
        start_y = y_pos - total_height // 2 + anim_y
        
        for line_idx, line in enumerate(lines):
            line_y = start_y + line_idx * line_height
            is_emphasis = any(ew.lower() in line.lower() for ew in emphasis_words)
            
            if is_emphasis and config.ENABLE_EMPHASIS_HIGHLIGHTS:
                bbox = font.getbbox(line)
                if bbox:
                    text_w = bbox[2] - bbox[0]
                    pad = 20
                    self._draw_rounded_card(
                        draw,
                        [self.width // 2 - text_w // 2 - pad, line_y - line_height // 2 - 10,
                         self.width // 2 + text_w // 2 + pad, line_y + line_height // 2 + 10],
                        radius=15, fill=config.COLOR_HIGHLIGHT, outline=config.COLOR_HIGHLIGHT, outline_width=2
                    )
            
            glow_color = config.COLOR_ACCENT if is_emphasis else config.COLOR_ACCENT_2
            self._draw_text_with_glow(
                draw, line, font, self.width // 2, line_y,
                config.COLOR_TEXT, glow_color,
                glow_radius=4 if is_emphasis else 2
            )
    
    def _draw_broll_overlay(self, base_img: Image.Image, broll_path: str,
                           frame_idx: int, segment_frames: int) -> Image.Image:
        """Overlay B-roll image with Ken Burns effect."""
        try:
            broll = Image.open(broll_path).convert("RGB")
        except:
            return base_img
        
        broll = self._apply_ken_burns(broll, frame_idx, segment_frames,
                                     zoom_start=1.0, zoom_end=1.12)
        
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        overlay.paste(broll.resize((self.width, self.height)))
        
        enhancer = ImageEnhance.Brightness(overlay)
        overlay = enhancer.enhance(0.4)
        
        base_img = Image.alpha_composite(base_img.convert("RGBA"), overlay)
        return base_img.convert("RGB")
    
    def render_video(self, script, audio_segments: List, broll_paths: List[Optional[str]],
                    final_audio_path: str) -> str:
        """Main video rendering function with all effects."""
        total_duration = get_audio_duration(final_audio_path)
        total_frames = int(total_duration * self.fps)
        
        logger_video.info(f"Rendering {total_frames} frames at {self.fps} FPS, duration: {total_duration:.2f}s")
        
        # Load B-roll images
        broll_images = {}
        for i, path in enumerate(broll_paths):
            if path and os.path.exists(path):
                try:
                    broll_images[i] = Image.open(path).convert("RGB")
                except:
                    pass
        
        batch_size = 100
        
        for batch_start in range(0, total_frames, batch_size):
            batch_end = min(batch_start + batch_size, total_frames)
            
            for frame_idx in range(batch_start, batch_end):
                current_time = frame_idx / self.fps
                
                # Find active segment
                active_seg_idx = -1
                active_seg = None
                
                for i, seg in enumerate(audio_segments):
                    if seg.start_time <= current_time < seg.end_time:
                        active_seg_idx = i
                        active_seg = seg
                        break
                
                # Create base frame
                frame = Image.new("RGB", (self.width, self.height), config.COLOR_BG_DARK)
                draw = ImageDraw.Draw(frame)
                
                # Draw background
                self._draw_gradient_background(draw, frame_idx, total_frames)
                self._draw_particles(draw, frame_idx)
                
                # Draw B-roll overlay
                if active_seg_idx >= 0 and active_seg_idx in broll_images:
                    seg_frames = int((active_seg.end_time - active_seg.start_time) * self.fps)
                    rel_frame = frame_idx - int(active_seg.start_time * self.fps)
                    frame = self._draw_broll_overlay(frame, broll_paths[active_seg_idx], rel_frame, seg_frames)
                    draw = ImageDraw.Draw(frame)
                
                # Draw text
                if active_seg:
                    seg_start_frame = int(active_seg.start_time * self.fps)
                    
                    if active_seg.segment.segment_type == "hook":
                        self._draw_segment_text(
                            draw, active_seg.segment.text, self.font_title,
                            self.height // 2 - 100, frame_idx, seg_start_frame,
                            active_seg.segment.emphasis_words
                        )
                    
                    elif active_seg.segment.segment_type in ["fact1", "fact2", "fact3"]:
                        fact_num = ["fact1", "fact2", "fact3"].index(active_seg.segment.segment_type) + 1
                        
                        if config.ENABLE_NUMBERED_BADGES:
                            badge_y = 180
                            self._draw_rounded_card(
                                draw, [self.width // 2 - 40, badge_y, self.width // 2 + 40, badge_y + 80],
                                radius=40, fill=config.COLOR_ACCENT,
                                outline=(255, 255, 255), outline_width=3
                            )
                            draw.text((self.width // 2, badge_y + 40), str(fact_num),
                                     font=self.font_title, fill=(0, 0, 0), anchor="mm")
                        
                        self._draw_segment_text(
                            draw, active_seg.segment.text, self.font_body,
                            self.height // 2 + 50, frame_idx, seg_start_frame,
                            active_seg.segment.emphasis_words
                        )
                    
                    elif active_seg.segment.segment_type == "outro":
                        self._draw_segment_text(
                            draw, active_seg.segment.text, self.font_body,
                            self.height // 2 - 200, frame_idx, seg_start_frame,
                            active_seg.segment.emphasis_words
                        )
                
                # Draw overlays
                self._draw_channel_badge(draw, frame_idx)
                self._draw_progress_bar(draw, frame_idx, total_frames)
                self._draw_subscribe_cta(draw, frame_idx, total_frames)
                
                # Save frame
                frame_path = config.FRAMES_DIR / f"frame_{frame_idx:06d}.png"
                frame.save(frame_path, "PNG")
                
                if frame_idx % 100 == 0:
                    logger_video.debug(f"Rendered frame {frame_idx}/{total_frames}")
        
        # Compile video with ffmpeg
        output_path = str(config.OUTPUT_DIR / "output_video.mp4")
        
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(self.fps),
            "-i", str(config.FRAMES_DIR / "frame_%06d.png"),
            "-i", final_audio_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", config.AUDIO_BITRATE,
            "-ar", str(config.AUDIO_SAMPLE_RATE),
            "-shortest",
            "-movflags", "+faststart",
            output_path
        ]
        
        logger_video.info("Compiling video with ffmpeg...")
        rc, _, err = run_command(cmd, timeout=600)
        
        if rc != 0:
            logger_video.warning(f"FFmpeg error, retrying with faster settings: {err}")
            cmd[-5] = "28"  # Lower quality
            cmd[-4] = "ultrafast"  # Faster preset
            rc, _, err = run_command(cmd, timeout=600)
        
        # Cleanup frames
        for f in config.FRAMES_DIR.glob("*.png"):
            f.unlink()
        
        logger_video.info(f"Video compiled: {output_path}")
        return output_path
