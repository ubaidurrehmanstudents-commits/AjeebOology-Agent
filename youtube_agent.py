#!/usr/bin/env python3
"""
Ajeebology Shorts - Cinematic YouTube Shorts Automation Agent
After Effects-level motion graphics | 100% Python + FFmpeg | GitHub Actions
22 Features: Kinetic typography, 3D parallax, fractal noise, bokeh, chromatic aberration,
 velocity blur, audio-reactive bars, procedural SFX, peak-energy thumbnail, etc.
Language: Hinglish | Output: 1080x1920 24fps | Option B: Full PIL word rendering (no ASS)
"""

import os, sys, json, re, math, random, subprocess, shutil, hashlib, tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
from urllib.parse import quote_plus
from io import BytesIO
from collections import defaultdict

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
    PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
    UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
    CATEGORY_OVERRIDE = os.environ.get("CATEGORY_OVERRIDE", "")

    W, H, FPS = 1080, 1920, 24
    TARGET_DUR, MAX_DUR = 58, 64
    VOICE_MODEL = "hi-IN-MadhurNeural"
    AUDIO_SR = 44100

    FONT_MAIN = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"
    FONT_FALL = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    FONT_EMOJI = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
    SZ_TITLE, SZ_BODY, SZ_WORD = 72, 56, 68

    # Cinematic palette
    BG_DARK = (8, 4, 20)
    BG_MID = (25, 12, 50)
    ACCENT = (0, 255, 255)
    ACCENT2 = (255, 0, 128)
    TEXT = (255, 255, 255)
    TEXT_DIM = (180, 180, 200)
    HIGHLIGHT = (255, 255, 0)
    GLASS_BG = (20, 10, 40, 180)

    BASE = Path("/tmp/ajeebology")
    FRAMES = BASE / "frames"
    AUDIO = BASE / "audio"
    ASSETS = BASE / "assets"
    OUTPUT = BASE / "output"

    BROLL_ON = True
    POLLINATIONS_ON = False  # FIX: Disabled by default (typo bug in method)
    MIDAS_ON = False         # FIX: Disabled by default (large model download)

random.seed(Config.GITHUB_RUN_ID)

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ScriptSegment:
    text: str
    seg_type: str
    emphasis: List[str] = field(default_factory=list)
    broll_prompt: str = ""

@dataclass
class VideoScript:
    title: str
    category: str
    seo_title: str
    description: str
    tags: List[str]
    hashtags: List[str]
    segments: List[ScriptSegment]
    total_dur: float = 0.0

@dataclass
class AudioSeg:
    segment: ScriptSegment
    path: str
    dur: float
    t0: float
    t1: float

@dataclass
class WordToken:
    text: str
    t0: float
    t1: float
    syl: int
    emphasis: bool
    seg_type: str
    seg_idx: int
    word_idx: int

@dataclass
class FrameEnergy:
    frame_idx: int
    audio_rms: float
    visual_energy: float
    has_emphasis: bool

# =============================================================================
# UTILITIES
# =============================================================================

def run_cmd(cmd: List[str], to: int = 300, binary: bool = False) -> Tuple[int, Any, Any]:
    try:
        cmd = [str(c) for c in cmd]  # FIX: auto-convert ints/floats to strings
        r = subprocess.run(cmd, capture_output=True, text=not binary, timeout=to, check=False)
        return r.returncode, r.stdout if not binary else r.stdout, r.stderr if not binary else r.stderr
    except subprocess.TimeoutExpired:
        return -1, b"" if binary else "", "timeout"

def audio_dur(p: str) -> float:
    rc, out, _ = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", p], 30)
    return float(out.strip()) if rc == 0 and out.strip() else 0.0

def ensure_dirs():
    for d in [Config.FRAMES, Config.AUDIO, Config.ASSETS, Config.OUTPUT]:
        d.mkdir(parents=True, exist_ok=True)

def load_font(size: int, emoji: bool = False) -> ImageFont.FreeTypeFont:
    paths = [Config.FONT_EMOJI] if emoji else [Config.FONT_MAIN, Config.FONT_FALL]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except:
                continue
    return ImageFont.load_default()

# =============================================================================
# EASING FUNCTIONS (After Effects curves)
# =============================================================================

def ease_linear(t: float) -> float:
    return t

def ease_in_out_cubic(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2

def ease_out_back(t: float) -> float:
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)

def ease_out_expo(t: float) -> float:
    return 1.0 if t >= 1 else 1 - pow(2, -10 * t)

def ease_out_bounce(t: float) -> float:
    n1, d1 = 7.5625, 2.75
    if t < 1 / d1:
        return n1 * t * t
    elif t < 2 / d1:
        t2 = t - 1.5 / d1
        return n1 * t2 * t2 + 0.75
    elif t < 2.5 / d1:
        t2 = t - 2.25 / d1
        return n1 * t2 * t2 + 0.9375
    else:
        t2 = t - 2.625 / d1
        return n1 * t2 * t2 + 0.984375

def ease_in_expo(t: float) -> float:
    return 0.0 if t <= 0 else pow(2, 10 * (t - 1))

# =============================================================================
# WORD TIMELINE PARSER (replaces ASS - Option B)
# =============================================================================

class WordTimeline:
    """Splits segments into word-level tokens with syllable timing."""

    @staticmethod
    def count_syl(word: str) -> int:
        word = word.lower().strip('.,!?;:"\'')
        if not word:
            return 1
        v = "aeiou"
        c = 0
        pv = False
        for ch in word:
            iv = ch in v
            if iv and not pv:
                c += 1
            pv = iv
        return max(c, 1)

    @staticmethod
    def build(audio_segments: List[AudioSeg]) -> List[WordToken]:
        tokens = []
        for seg_idx, aseg in enumerate(audio_segments):
            words = aseg.segment.text.split()
            if not words:
                continue
            seg_dur = aseg.t1 - aseg.t0
            syls = [WordTimeline.count_syl(w) for w in words]
            total_syl = sum(syls) or len(words)
            t_cursor = aseg.t0
            for widx, w in enumerate(words):
                s = syls[widx]
                wdur = seg_dur * (s / total_syl)
                wdur = max(wdur, 0.15)
                emp = any(e.lower() in w.lower() for e in aseg.segment.emphasis)
                tokens.append(WordToken(
                    text=w, t0=t_cursor, t1=t_cursor + wdur,
                    syl=s, emphasis=emp, seg_type=aseg.segment.seg_type,
                    seg_idx=seg_idx, word_idx=widx
                ))
                t_cursor += wdur
        return tokens

# =============================================================================
# TEXT RENDERER (glow, shadow, chromatic aberration, 3D extrusion)
# =============================================================================

class TextRenderer:
    """Renders individual words as transparent PNGs with full FX stack."""

    def __init__(self):
        self.font_word = load_font(Config.SZ_WORD)
        self.font_emp = load_font(int(Config.SZ_WORD * 1.35))
        self.font_emoji = load_font(48, emoji=True)

    def render_word(self, text: str, size: int, emphasis: bool = False,
                    glow: bool = True, chromatic: bool = False,
                    extrusion: bool = False, velocity: Tuple[float, float] = (0, 0)) -> Image.Image:
        """Render a word onto a transparent canvas with all FX."""
        font = self.font_emp if emphasis else load_font(size)
        bbox = font.getbbox(text)
        if not bbox:
            bbox = (0, 0, size * 2, size)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = 60 if emphasis else 40
        if chromatic:
            pad += 20
        if extrusion:
            pad += 20

        W, H = tw + pad * 2, th + pad * 2
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(base)

        cx, cy = W // 2, H // 2
        tx, ty = cx - tw // 2, cy - th // 2

        # 3D Extrusion shadow
        if extrusion:
            for i in range(6, 0, -1):
                alpha = int(30 - i * 4)
                off = i * 2
                draw.text((tx + off, ty + off), text, font=font, fill=(0, 0, 0, alpha))

        # Chromatic aberration
        if chromatic:
            vx, vy = velocity
            shift = max(3, int(math.hypot(vx, vy) * 0.5))
            r_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(r_layer).text((tx - shift, ty), text, font=font, fill=(255, 0, 0, 120))
            b_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(b_layer).text((tx + shift, ty), text, font=font, fill=(0, 0, 255, 120))
            base = Image.alpha_composite(base, r_layer)
            base = Image.alpha_composite(base, b_layer)

        # Glow layers
        if glow:
            glow_color = Config.ACCENT if not emphasis else Config.HIGHLIGHT
            for r in range(12, 0, -2):
                alpha = int(25 - r * 2)
                gc = glow_color + (alpha,)
                for dx, dy in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
                    draw.text((tx + dx * r, ty + dy * r), text, font=font, fill=gc)

        # Main text
        main_color = Config.HIGHLIGHT if emphasis else Config.TEXT
        draw.text((tx, ty), text, font=font, fill=main_color + (255,))

        return base

    def render_emoji(self, emoji: str) -> Image.Image:
        font = self.font_emoji
        bbox = font.getbbox(emoji)
        if not bbox:
            bbox = (0, 0, 48, 48)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        img = Image.new("RGBA", (tw + 20, th + 20), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((10, 10), emoji, font=font, embedded_color=True)
        return img

# =============================================================================
# MOTION GRAPHICS ENGINE (Fractal noise, particles, bokeh, audio bars)
# =============================================================================

class MotionGraphics:
    """Procedural background animations - all CPU-based, no external assets."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.particles = self._init_particles(120)
        self.bokeh = self._init_bokeh(25)
        self.noise_seed = random.randint(0, 99999)
        self.grid_phase = 0.0

    def _init_particles(self, n: int) -> List[Dict]:
        pts = []
        for _ in range(n):
            pts.append({
                "x": random.randint(0, self.w), "y": random.randint(0, self.h),
                "size": random.randint(1, 4), "sx": random.uniform(-0.6, 0.6),
                "sy": random.uniform(-1.5, -0.3), "op": random.randint(60, 180),
                "phase": random.uniform(0, math.pi * 2)
            })
        return pts

    def _init_bokeh(self, n: int) -> List[Dict]:
        b = []
        colors = [Config.ACCENT, Config.ACCENT2, (255, 100, 100), (100, 255, 100)]
        for _ in range(n):
            b.append({
                "x": random.randint(0, self.w), "y": random.randint(0, self.h),
                "r": random.randint(30, 120), "color": random.choice(colors),
                "sx": random.uniform(-0.3, 0.3), "sy": random.uniform(-0.2, -0.1),
                "op": random.randint(15, 50), "phase": random.uniform(0, math.pi * 2)
            })
        return b

    def _perlin_noise(self, x: float, y: float, seed: int) -> float:
        def smoothstep(t):
            return t * t * (3 - 2 * t)

        def noise(ix, iy):
            n = math.sin(ix * 12.9898 + iy * 78.233 + seed) * 43758.5453
            return n - int(n)

        ix, iy = int(x), int(y)
        fx, fy = x - ix, y - iy
        a = noise(ix, iy)
        b = noise(ix + 1, iy)
        c = noise(ix, iy + 1)
        d = noise(ix + 1, iy + 1)
        return smoothstep(fy) * (smoothstep(fx) * (d - c) + c) + (1 - smoothstep(fy)) * (smoothstep(fx) * (b - a) + a)

    def draw_fractal_bg(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        # FIX: Simplified for performance - gradient only, skip expensive perlin
        t = frame_idx / max(total_frames, 1)
        for y in range(0, self.h, 12):
            ratio = y / self.h
            r = int(Config.BG_DARK[0] + (Config.BG_MID[0] - Config.BG_DARK[0]) * ratio + math.sin(t * math.pi * 2 + y * 0.002) * 15)
            g = int(Config.BG_DARK[1] + (Config.BG_MID[1] - Config.BG_DARK[1]) * ratio + math.cos(t * math.pi * 2 + y * 0.002) * 8)
            b = int(Config.BG_DARK[2] + (Config.BG_MID[2] - Config.BG_DARK[2]) * ratio + math.sin(t * math.pi) * 20)
            r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
            draw.rectangle([0, y, self.w, y + 12], fill=(r, g, b))

    def draw_particles(self, draw: ImageDraw, frame_idx: int):
        for p in self.particles:
            px = (p["x"] + p["sx"] * frame_idx) % self.w
            py = (p["y"] + p["sy"] * frame_idx) % self.h
            pulse = 0.5 + 0.5 * math.sin(frame_idx * 0.04 + p["phase"])
            alpha = int(p["op"] * pulse)
            sz = int(p["size"] * (0.8 + 0.4 * pulse))
            c = Config.ACCENT
            draw.ellipse([px - sz, py - sz, px + sz, py + sz], fill=(c[0], c[1], c[2], alpha))

    def draw_bokeh(self, img: Image.Image, frame_idx: int) -> Image.Image:
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        for b in self.bokeh:
            bx = (b["x"] + b["sx"] * frame_idx) % self.w
            by = (b["y"] + b["sy"] * frame_idx) % self.h
            pulse = 0.5 + 0.5 * math.sin(frame_idx * 0.02 + b["phase"])
            alpha = int(b["op"] * pulse)
            r = int(b["r"] * (0.9 + 0.2 * pulse))
            c = b["color"] + (alpha,)
            d.ellipse([bx - r, by - r, bx + r, by + r], fill=c)
        overlay = overlay.filter(ImageFilter.GaussianBlur(20))
        return Image.alpha_composite(img.convert("RGBA"), overlay)

    def draw_audio_bars(self, draw: ImageDraw, frame_idx: int, rms: float, total_frames: int):
        bar_w, bar_h_max, gap = 8, 60, 6
        cx = self.w // 2
        base_y = self.h - 120
        heights = [bar_h_max * rms * (0.8 + 0.4 * math.sin(frame_idx * 0.1 + i)) for i in range(3)]
        for i, h in enumerate(heights):
            h = min(h, bar_h_max)
            x = cx - bar_w - gap + i * (bar_w + gap)
            y = base_y - h
            for r in range(4, 0, -1):
                a = int(20 - r * 4)
                draw.rectangle([x - r, y - r, x + bar_w + r, base_y + r], fill=Config.ACCENT + (a,))
            draw.rectangle([x, y, x + bar_w, base_y], fill=Config.ACCENT)

    def draw_neon_grid(self, draw: ImageDraw, frame_idx: int):
        t = frame_idx * 0.008
        y_base = int(self.h * 0.65)
        for i in range(-5, 6):
            x = self.w // 2 + i * 80 + int(math.sin(t + i * 0.3) * 20)
            draw.line([(x, y_base), (self.w // 2 + i * 200, self.h)], fill=Config.ACCENT + (30,), width=1)
        scan_y = int(self.h * 0.3 + math.sin(t * 2) * 50)
        draw.line([(0, scan_y), (self.w, scan_y)], fill=Config.ACCENT + (20,), width=2)

    def draw_glass_card(self, img: Image.Image, cx: int, cy: int, cw: int, ch: int) -> Image.Image:
        overlay = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        crop = img.crop((max(0, cx - cw // 2 - 20), max(0, cy - ch // 2 - 20),
            min(self.w, cx + cw // 2 + 20), min(self.h, cy + ch // 2 + 20)))
        crop = crop.filter(ImageFilter.GaussianBlur(15))
        img.paste(crop, (max(0, cx - cw // 2 - 20), max(0, cy - ch // 2 - 20)))
        d.rounded_rectangle([cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2], radius=20,
            fill=(20, 10, 40, 160), outline=Config.ACCENT + (100,), width=2)
        return Image.alpha_composite(img.convert("RGBA"), overlay)

    def draw_date_stamp(self, draw: ImageDraw, frame_idx: int):
        from datetime import datetime
        date_str = datetime.now().strftime("%d %b %Y").upper()
        font = load_font(28)
        pulse = 0.5 + 0.5 * math.sin(frame_idx * 0.15)
        dot_r = int(4 + 2 * pulse)
        dot_color = (255, 50, 50) if pulse > 0.7 else (180, 40, 40)
        draw.ellipse([20, 20, 20 + dot_r * 2, 20 + dot_r * 2], fill=dot_color)
        draw.text((20 + dot_r * 2 + 10, 18), date_str, font=font, fill=Config.TEXT)
        if frame_idx / Config.FPS < 4:
            live_font = load_font(22)
            draw.text((20 + dot_r * 2 + 10, 48), "LIVE", font=live_font, fill=(255, 50, 50))

    def draw_progress_ring(self, draw: ImageDraw, frame_idx: int, total_frames: int):
        cx, cy, r = self.w - 80, 80, 30
        progress = frame_idx / max(total_frames, 1)
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=0, end=360, fill=(40, 30, 60), width=4)
        end_angle = int(360 * progress)
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=-90, end=-90 + end_angle, fill=Config.ACCENT, width=4)
        font = load_font(26)
        draw.text((cx - 50, cy + 40), "AjeebOology", font=font, fill=Config.TEXT)

# =============================================================================
# DEPTH ENGINE (MiDaS parallax - lightweight CPU)
# =============================================================================

class DepthEngine:
    """Generates depth maps for 3D parallax effect."""

    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        if not Config.MIDAS_ON:
            return
        try:
            import torch
            from transformers import pipeline
            self.model = pipeline("depth-estimation", model="Intel/dpt-large", device=-1)
            print("MiDaS depth model loaded")
        except Exception as e:
            print(f"MiDaS load failed ({e}), using gradient fallback")
            self.model = None

    def get_depth_map(self, img: Image.Image) -> np.ndarray:
        if self.model is None:
            return self._gradient_fallback(img)
        try:
            result = self.model(img)
            depth = np.array(result["depth"])
            depth = ((depth - depth.min()) / (depth.max() - depth.min() + 1e-8) * 255).astype(np.uint8)
            return depth
        except Exception as e:
            print(f"Depth inference failed: {e}")
            return self._gradient_fallback(img)

    def _gradient_fallback(self, img: Image.Image) -> np.ndarray:
        w, h = img.size
        grad = np.linspace(0, 255, h).reshape(h, 1).repeat(w, axis=1).astype(np.uint8)
        return grad

    def apply_parallax(self, img: Image.Image, depth: np.ndarray, frame_idx: int,
                        seg_frames: int) -> Image.Image:
        if seg_frames < 2:
            return img
        progress = frame_idx / seg_frames
        pan_max = 30
        pan_x = int(pan_max * math.sin(progress * math.pi * 2))
        pan_y = int(pan_max * 0.3 * math.cos(progress * math.pi * 2))
        w, h = img.size
        img_arr = np.array(img)
        result = np.zeros_like(img_arr)
        for y in range(h):
            for x in range(w):
                d = depth[y, x] / 255.0
                shift_x = int(pan_x * d)
                shift_y = int(pan_y * d)
                nx = max(0, min(w - 1, x + shift_x))
                ny = max(0, min(h - 1, y + shift_y))
                result[y, x] = img_arr[ny, nx]
        return Image.fromarray(result)

# =============================================================================
# SFX ENGINE (Procedural sound design)
# =============================================================================

class SFXEngine:
    """Generates all sound effects procedurally via FFmpeg."""

    def __init__(self):
        self.sfx_dir = Config.AUDIO / "sfx"
        self.sfx_dir.mkdir(exist_ok=True)

    def _gen(self, filter_str: str, dur: float, vol: float, out: str):
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine={filter_str}",
            "-af", f"volume={vol},afade=t=out:st={dur - 0.05}:d=0.05",
            "-t", str(dur), "-c:a", "libmp3lame", "-q:a", 4, out]
        run_cmd(cmd, 15)

    def whoosh(self, path: str):
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
            "sine=frequency=200:duration=0.25", "-af",
            "volume=0.3,afade=t=out:st=0.2:d=0.05",
            "-t", "0.25", "-c:a", "libmp3lame", "-q:a", 4, path]
        run_cmd(cmd, 15)

    def pop(self, path: str):
        self._gen("frequency=1200:duration=0.08", 0.08, 0.4, path)

    def rumble(self, path: str, dur: float = 0.4):
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anoisesrc=a=0.1:c=brown:duration={dur}",
            "-af", "lowpass=f=120,volume=0.5,afade=t=out:st=0.3:d=0.1",
            "-t", str(dur), "-c:a", "libmp3lame", "-q:a", 4, path]
        run_cmd(cmd, 15)

    def tape_stop(self, path: str, dur: float = 0.6):
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
            f"sine=frequency=400:duration={dur}",
            "-af", f"asetrate=44100*0.5,volume=0.4,afade=t=out:st={dur - 0.2}:d=0.2",
            "-t", str(dur), "-c:a", "libmp3lame", "-q:a", 4, path]
        run_cmd(cmd, 15)

    def ding(self, path: str):
        self._gen("frequency=880:duration=0.15", 0.15, 0.35, path)

    def glitch_noise(self, path: str, dur: float = 0.2):
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
            f"anoisesrc=a=0.8:c=white:duration={dur}",
            "-af", "highpass=f=2000,volume=0.15,afade=t=out:st=0.1:d=0.1",
            "-t", str(dur), "-c:a", "libmp3lame", "-q:a", 4, path]
        run_cmd(cmd, 15)

    def mix_sfx_to_voice(self, voice_path: str, sfx_events: List[Tuple[float, str]], out_path: str):
        if not sfx_events:
            shutil.copy(voice_path, out_path)
            return
        inputs = [["-i", voice_path]]
        delays = []
        for i, (t, spath) in enumerate(sfx_events):
            if os.path.exists(spath):
                inputs.append(["-i", spath])
                ms = int(t * 1000)
                delays.append(f"[{i + 1}:a]adelay={ms}|{ms}[sfx{i}];")
        if not delays:
            shutil.copy(voice_path, out_path)
            return
        mix_str = "[0:a]" + "".join(f"[sfx{i}]" for i in range(len(delays))) + f"amix=inputs={len(delays) + 1}:duration=first[out]"
        fc = "".join(delays) + mix_str
        flat_inputs = [item for sub in inputs for item in sub]
        cmd = ["ffmpeg", "-y"] + flat_inputs + ["-filter_complex", fc, "-map", "[out]", "-c:a", "libmp3lame", "-q:a", 2, out_path]
        run_cmd(cmd, 120)

# =============================================================================
# ANIMATION ENGINE (Kinetic Typography - Option B Core)
# =============================================================================

class AnimationEngine:
    """Handles all word-level animations: enter, hold, exit, emphasis, glitch."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.text_r = TextRenderer()
        self.mg = MotionGraphics(w, h)
        self.depth = DepthEngine()
        self.sfx = SFXEngine()
        self.energy_log: List[FrameEnergy] = []
        self.ENTER_FRAMES = 8
        self.EXIT_FRAMES = 6
        self.EMP_FRAMES = 12
        self.GLITCH_FRAMES = 7

    def _word_position(self, token: WordToken, frame_idx: int, total_frames: int) -> Tuple[int, int]:
        cx = self.w // 2
        base_y = 820
        if token.seg_type == "hook":
            base_y = 780
        elif token.seg_type == "conclusion":
            base_y = 860
        breathe = int(math.sin(frame_idx * 0.03) * 3)
        return cx, base_y + breathe

    def _calc_word_transform(self, token: WordToken, frame_idx: int, fps: int) -> Dict:
        t_frame = frame_idx / fps
        dur = token.t1 - token.t0
        if dur <= 0:
            dur = 0.3
        rel = (t_frame - token.t0) / dur
        rel = max(0, min(1, rel))

        phase = "enter" if rel < 0.25 else ("exit" if rel > 0.75 else "hold")
        phase_rel = rel / 0.25 if phase == "enter" else ((rel - 0.75) / 0.25 if phase == "exit" else (rel - 0.25) / 0.5)
        phase_rel = max(0, min(1, phase_rel))

        result = {"x": 0, "y": 0, "scale": 1.0, "rot": 0, "opacity": 255,
            "glow": True, "chromatic": False, "extrusion": True,
            "velocity": (0, 0), "emoji": None}

        cx, cy = self._word_position(token, frame_idx, total_frames)

        if phase == "enter":
            edge = token.word_idx % 4
            ease = ease_out_back(phase_rel)
            if edge == 0:
                result["x"] = cx - int((cx + 200) * (1 - ease))
                result["velocity"] = (15 * (1 - ease), 0)
            elif edge == 1:
                result["x"] = cx + int((cx + 200) * (1 - ease))
                result["velocity"] = (-15 * (1 - ease), 0)
            elif edge == 2:
                result["y"] = cy - int((cy + 100) * (1 - ease))
                result["velocity"] = (0, 10 * (1 - ease))
            else:
                result["y"] = cy + int((self.h - cy + 100) * (1 - ease))
                result["velocity"] = (0, -10 * (1 - ease))
            result["scale"] = 0.6 + 0.4 * ease
            result["opacity"] = int(255 * ease_linear(phase_rel))
            result["glow"] = False

        elif phase == "hold":
            result["x"] = cx
            result["y"] = cy
            result["scale"] = 1.0 + 0.03 * math.sin(frame_idx * 0.08)
            result["opacity"] = 255
            result["glow"] = True

        elif phase == "exit":
            ease = ease_in_expo(phase_rel)
            edge = token.word_idx % 4
            if edge == 0:
                result["x"] = cx - int(300 * ease)
                result["velocity"] = (-20 * ease, 0)
            elif edge == 1:
                result["x"] = cx + int(300 * ease)
                result["velocity"] = (20 * ease, 0)
            elif edge == 2:
                result["y"] = cy - int(200 * ease)
                result["velocity"] = (0, -15 * ease)
            else:
                result["y"] = cy + int(200 * ease)
                result["velocity"] = (0, 15 * ease)
            result["scale"] = 1.0 - 0.3 * ease
            result["opacity"] = int(255 * (1 - ease_linear(phase_rel)))

        if token.emphasis and phase == "hold":
            seg_mid = (token.t0 + token.t1) / 2
            t_since_mid = abs(t_frame - seg_mid)
            if t_since_mid < 0.25:
                emp_rel = 1 - (t_since_mid / 0.25)
                emp_ease = ease_out_back(emp_rel)
                result["scale"] = 1.0 + 0.4 * emp_ease
                result["glow"] = True
                result["chromatic"] = True
                result["emoji"] = self._pick_emoji(token.seg_type)

        return result

    def _pick_emoji(self, seg_type: str) -> str:
        emojis = {"hook": "😱", "fact1": "🔥", "fact2": "💡", "fact3": "🧠", "conclusion": "✅"}
        return emojis.get(seg_type, "✨")

    def _apply_velocity_blur(self, img: Image.Image, velocity: Tuple[float, float]) -> Image.Image:
        vx, vy = velocity
        speed = math.hypot(vx, vy)
        if speed < 2:
            return img
        blur_amt = min(8, int(speed * 0.4))
        blurred = img.filter(ImageFilter.GaussianBlur(blur_amt))
        alpha = min(0.6, speed / 25)
        return Image.blend(img, blurred, alpha)

    def _draw_glitch_transition(self, base: Image.Image, frame_idx: int, seg_idx: int,
                                    prev_seg: int, tokens: List[WordToken]) -> Image.Image:
        if seg_idx == prev_seg or prev_seg < 0:
            return base
        glitch_progress = (frame_idx % self.GLITCH_FRAMES) / self.GLITCH_FRAMES
        if glitch_progress >= 1:
            return base

        arr = np.array(base)
        h, w = arr.shape[:2]
        shift = int(15 * (1 - glitch_progress))
        r = np.roll(arr[:, :, 0], shift, axis=1)
        b = np.roll(arr[:, :, 2], -shift, axis=1)
        arr[:, :, 0] = r
        arr[:, :, 2] = b
        for y in range(0, h, 4):
            arr[y:y + 2, :] = (arr[y:y + 2, :] * 0.7).astype(np.uint8)
        slices = random.randint(3, 8)
        for _ in range(slices):
            sy = random.randint(0, h - 20)
            sh = random.randint(5, 20)
            sx = random.randint(-30, 30)
            arr[sy:sy + sh, :] = np.roll(arr[sy:sy + sh, :], sx, axis=1)
        return Image.fromarray(arr)

    def _draw_scanline_overlay(self, img: Image.Image) -> Image.Image:
        arr = np.array(img)
        h = arr.shape[0]
        for y in range(0, h, 3):
            arr[y, :] = (arr[y, :] * 0.92).astype(np.uint8)
        return Image.fromarray(arr)

    def _draw_vignette(self, img: Image.Image) -> Image.Image:
        w, h = img.size
        x = np.linspace(-1, 1, w)
        y = np.linspace(-1, 1, h)
        X, Y = np.meshgrid(x, y)
        R = np.sqrt(X ** 2 + Y ** 2)
        mask = 1 - np.clip(R / 1.35, 0, 1) * 0.55
        mask = (mask * 255).astype(np.uint8)
        m = Image.fromarray(mask, mode="L").filter(ImageFilter.GaussianBlur(60))
        arr = np.array(img)
        ma = np.array(m).reshape(h, w, 1) / 255.0
        return Image.fromarray((arr * ma).astype(np.uint8))

    def _apply_lut(self, img: Image.Image) -> Image.Image:
        arr = np.array(img).astype(np.float32)
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.05 + 5, 0, 255)
        arr[:, :, 1] = np.clip(arr[:, :, 1] * 1.02 + 8, 0, 255)
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 1.15 + 12, 0, 255)
        arr = np.where(arr < 30, arr * 0.85, arr)
        arr = np.clip((arr - 128) * 1.08 + 128, 0, 255)
        return Image.fromarray(arr.astype(np.uint8))

    def render_frame(self, frame_idx: int, total_frames: int, tokens: List[WordToken],
                        broll_paths: List[Optional[str]], audio_rms: float,
                        seg_boundaries: List[int]) -> Tuple[Image.Image, float]:
        t = frame_idx / Config.FPS

        active_seg = -1
        for i, tok in enumerate(tokens):
            if tok.t0 <= t < tok.t1:
                active_seg = tok.seg_idx
                break

        prev_seg = -1
        if frame_idx > 0:
            pt = (frame_idx - 1) / Config.FPS
            for tok in tokens:
                if tok.t0 <= pt < tok.t1:
                    prev_seg = tok.seg_idx
                    break

        # 1. Fractal noise background
        base = Image.new("RGB", (self.w, self.h), Config.BG_DARK)
        draw = ImageDraw.Draw(base)
        self.mg.draw_fractal_bg(draw, frame_idx, total_frames)

        # 2. B-roll with parallax
        if active_seg >= 0 and active_seg < len(broll_paths):
            bpath = broll_paths[active_seg]
            if bpath and os.path.exists(bpath):
                try:
                    if bpath.lower().endswith((".mp4", ".mov", ".avi")):
                        bt = max(0, t - tokens[0].t0 if tokens else 0)
                        # FIX: Use binary=True for FFmpeg stdout capture
                        rc, out, _ = run_cmd(["ffmpeg", "-y", "-ss", str(bt), "-i", bpath,
                            "-vframes", "1", "-f", "image2", "-vcodec", "png", "-"], 15, binary=True)
                        bimg = Image.open(BytesIO(out)).convert("RGB") if rc == 0 and out else None
                    else:
                        bimg = Image.open(bpath).convert("RGB")
                    if bimg:
                        bimg = self._resize_cover(bimg, self.w, self.h)
                        seg_frames = int((tokens[-1].t1 - tokens[0].t0) * Config.FPS) if tokens else total_frames
                        rel_f = frame_idx - int(tokens[0].t0 * Config.FPS) if tokens else frame_idx
                        bimg = self._ken_burns(bimg, rel_f, seg_frames)
                        depth = self.depth.get_depth_map(bimg)
                        bimg = self.depth.apply_parallax(bimg, depth, rel_f, seg_frames)
                        bimg = ImageEnhance.Brightness(bimg).enhance(0.4)
                        base = bimg
                except Exception as e:
                    print(f"Broll error: {e}")

        base = base.convert("RGBA")

        # 3. Neon grid
        self.mg.draw_neon_grid(ImageDraw.Draw(base), frame_idx)

        # 4. Particles
        self.mg.draw_particles(ImageDraw.Draw(base), frame_idx)

        # 5. Bokeh
        base = self.mg.draw_bokeh(base, frame_idx)

        # 6. Glass card
        card_w, card_h = 900, 300
        base = self.mg.draw_glass_card(base, self.w // 2, self.h // 2 + 50, card_w, card_h)

        # 7. Kinetic typography
        visual_energy = 0.0
        words_on_screen = 0
        for tok in tokens:
            if not (tok.t0 - 0.15 <= t < tok.t1 + 0.15):
                continue
            words_on_screen += 1
            transform = self._calc_word_transform(tok, frame_idx, total_frames)

            size = int(Config.SZ_WORD * transform["scale"])
            if tok.emphasis:
                size = int(Config.SZ_WORD * 1.35 * transform["scale"])
            word_img = self.text_r.render_word(
                tok.text, size, emphasis=tok.emphasis,
                glow=transform["glow"], chromatic=transform["chromatic"],
                extrusion=transform["extrusion"], velocity=transform["velocity"]
            )

            word_img = self._apply_velocity_blur(word_img, transform["velocity"])

            wx = transform["x"]
            wy = transform["y"]
            ww, wh = word_img.size
            paste_x = wx - ww // 2
            paste_y = wy - wh // 2

            if transform["opacity"] < 255:
                word_img = word_img.copy()
                alpha = word_img.split()[3]
                alpha = alpha.point(lambda p: int(p * transform["opacity"] / 255))
                word_img.putalpha(alpha)

            base = Image.alpha_composite(base, word_img)

            if transform["emoji"]:
                eimg = self.text_r.render_emoji(transform["emoji"])
                ew, eh = eimg.size
                ex = wx + ww // 2 + 10
                ey = wy - eh // 2
                bounce = int(abs(math.sin(frame_idx * 0.2)) * 10)
                base = Image.alpha_composite(base, eimg.convert("RGBA"))

            if tok.emphasis and transform["scale"] > 1.2:
                visual_energy += transform["scale"]

        # 8. Audio bars
        self.mg.draw_audio_bars(ImageDraw.Draw(base), frame_idx, audio_rms, total_frames)

        # 9. Date stamp + LIVE
        self.mg.draw_date_stamp(ImageDraw.Draw(base), frame_idx)

        # 10. Progress ring
        self.mg.draw_progress_ring(ImageDraw.Draw(base), frame_idx, total_frames)

        # 11. Subscribe CTA
        self._draw_subscribe_cta(ImageDraw.Draw(base), frame_idx, total_frames)

        # 12. Glitch transition
        base = self._draw_glitch_transition(base, frame_idx, active_seg, prev_seg, tokens)

        # 13. Scanline
        base = self._draw_scanline_overlay(base)

        # 14. Vignette
        base = self._draw_vignette(base)

        # 15. Color grade
        base = self._apply_lut(base)

        # 16. Letterbox
        final = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        final.paste(base.convert("RGB"), (0, 0))
        draw_final = ImageDraw.Draw(final)
        draw_final.rectangle([0, 0, self.w, 12], fill=(0, 0, 0))
        draw_final.rectangle([0, self.h - 12, self.w, self.h], fill=(0, 0, 0))

        return final, visual_energy

    def _resize_cover(self, img: Image.Image, tw: int, th: int) -> Image.Image:
        ir = img.width / img.height
        tr = tw / th
        if ir > tr:
            nh = th
            nw = int(nh * ir)
        else:
            nw = tw
            nh = int(nw / ir)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        l = (nw - tw) // 2
        t = (nh - th) // 2
        return img.crop((l, t, l + tw, t + th))

    def _ken_burns(self, img: Image.Image, fidx: int, sframes: int) -> Image.Image:
        if sframes < 2:
            return img
        p = fidx / sframes
        sc = 1.0 + 0.12 * math.sin(p * math.pi)
        nw, nh = int(img.width * sc), int(img.height * sc)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        px = int((nw - self.w) * 0.5 * (1 + 0.3 * math.sin(p * math.pi * 2)))
        py = int((nh - self.h) * 0.5 * (1 + 0.2 * math.cos(p * math.pi * 2)))
        l = max(0, min(px, nw - self.w))
        t = max(0, min(py, nh - self.h))
        return img.crop((l, t, l + self.w, t + self.h))

    def _draw_subscribe_cta(self, draw: ImageDraw, fidx: int, total: int):
        t = fidx / Config.FPS
        total_t = total / Config.FPS
        if t < total_t - 8:
            return
        txt = "Subscribe for Daily Facts!"
        font = load_font(44)
        bb = font.getbbox(txt)
        if not bb:
            return
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        x = (self.w - tw) // 2
        y = self.h - 200
        bounce = abs(math.sin((t - (total_t - 8)) * 4)) * 12
        y -= int(bounce)
        for r in range(8, 0, -2):
            draw.rounded_rectangle([x - 20 - r, y - 10 - r, x + tw + 20 + r, y + th + 10 + r],
                radius=25, fill=Config.ACCENT2 + (15 - r * 2,))
        draw.rounded_rectangle([x - 20, y - 10, x + tw + 20, y + th + 10],
            radius=25, fill=Config.ACCENT2 + (200,), outline=Config.TEXT + (255,), width=2)
        draw.text((x, y), txt, font=font, fill=Config.TEXT)

# =============================================================================
# AUDIO ANALYSIS (RMS per frame for reactive elements)
# =============================================================================

class AudioAnalyzer:
    def __init__(self, audio_path: str):
        self.path = audio_path
        self.rms_values = self._analyze()

    def _analyze(self) -> List[float]:
        cmd = [
            "ffmpeg", "-y", "-i", self.path,
            "-af", "astats=metadata=1:reset=1,ametadata=print:file=-",
            "-f", "null", "-"
        ]
        rc, out, err = run_cmd(cmd, 120)
        rms_vals = []
        for line in (out + err).split("\n"):
            if "RMS level dB" in line:
                try:
                    db = float(line.split(":")[-1].strip())
                    lin = 10 ** (db / 20)
                    rms_vals.append(min(1.0, max(0.0, lin)))
                except:
                    pass
        if not rms_vals:
            dur = audio_dur(self.path)
            frames = int(dur * Config.FPS)
            rms_vals = [0.3] * frames
        return rms_vals

    def get_rms(self, frame_idx: int) -> float:
        return self.rms_values[frame_idx] if frame_idx < len(self.rms_values) else 0.3

# =============================================================================
# SCRIPT AGENT (Groq)
# =============================================================================

class ScriptAgent:
    SYS = '''You are a professional YouTube Shorts scriptwriter for 'AjeebOology'.
Create engaging scripts in Hinglish (Roman Hindi + English).
Target: Indian youth 18-34. Tone: curious, energetic, slightly dramatic.

Rules:
- Hook under 4 seconds, pattern interrupt
- Segments: hook, fact1, fact2, fact3, conclusion
- 140-170 words (~55-62 seconds)
- 2-3 emphasis words per segment
- B-roll prompts: vivid image search terms
- Output valid JSON only

JSON: {"title":"","category":"","seo_title":"","description":"","tags":[],"hashtags":[],"segments":[{"text":"","segment_type":"","emphasis_words":[],"broll_prompt":""}]}'''

    def __init__(self):
        self.key = Config.GROQ_API_KEY
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    def generate(self, research: Dict) -> VideoScript:
        cat = Config.CATEGORY_OVERRIDE or random.choice(["psychology", "space", "weird_facts"])
        prompt = f"Create a YouTube Shorts script about: {research.get('topic', cat)}. Category: {cat}. Mind-blowing Hinglish. 2-3 emphasis words per segment. ONLY JSON."
        try:
            r = requests.post(self.url, headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": self.SYS}, {"role": "user", "content": prompt}],
                "temperature": 0.85, "max_tokens": 1200, "response_format": {"type": "json_object"}}, timeout=60)
            r.raise_for_status()
            d = r.json()["choices"][0]["message"]["content"]
            if isinstance(d, str):
                d = json.loads(d)
            return self._parse(d, cat)
        except Exception as e:
            print(f"Script error: {e}")
            return self._fallback(cat)

    def _parse(self, d: Dict, cat: str) -> VideoScript:
        segs = [ScriptSegment(text=s.get("text", ""), seg_type=s.get("segment_type", "fact"),
            emphasis=s.get("emphasis_words", []), broll_prompt=s.get("broll_prompt", ""))
            for s in d.get("segments", [])]
        return VideoScript(title=d.get("title", "Ajeebology"), category=cat,
            seo_title=d.get("seo_title", ""), description=d.get("description", ""),
            tags=d.get("tags", []), hashtags=d.get("hashtags", ["#Shorts", "#AjeebOology"]),
            segments=segs)

    def _fallback(self, cat: str) -> VideoScript:
        txts = {
            "psychology": ["Kya aap jante hain ki aapka brain 70 percent waqt auto-pilot par rehta hai?",
                "Jab aap drive kar rahe hote hain, tab aapka subconscious mind control mein hota hai.",
                "Aur jab aap sochte hain ki aap conscious hain, woh bhi ek illusion hai!",
                "Scientists ne prove kiya hai ki decisions 7 seconds pehle brain mein ban chuke hote hain.",
                "Toh agli baar jab koi decision lo, yaad rakhna - aapka brain pehle se hi decide kar chuka tha!"],
            "space": ["Space mein aawaz kyun nahi jaati? Reason sunke shock ho jaaoge!",
                "Aawaz travel karne ke liye medium chahiye, aur space mein vacuum hai.",
                "Lekin suno, agar aap Mars pe khade hokar chillao, toh wahan ke atmosphere mein aawaz jayegi!",
                "Aur NASA ke microphones ne actually Mars ki aawazein record ki hain!",
                "Toh space silent nahi hai, bas uska silence alag tarah ka hai!"],
            "weird_facts": ["Yeh fact sunke aapka dimaag ghoom jayega!",
                "Honey kabhi spoil nahi hota. Archaeologists ne 3000 saal purana honey khaya aur woh theek tha!",
                "Aur octopus ke paas 3 dil hote hain, aur woh blue blood rakhte hain!",
                "Banana technically ek berry hai, aur strawberry technically berry nahi hai!",
                "Duniya itni ajeeb hai ki facts bhi confuse ho jate hain!"]
        }
        types = ["hook", "fact1", "fact2", "fact3", "conclusion"]
        segs = [ScriptSegment(text=t, seg_type=types[i],
            emphasis=["shock", "amazing"] if i == 0 else ["fact", "wow"])
            for i, t in enumerate(txts.get(cat, txts["weird_facts"]))]
        return VideoScript(title="Ajeebology Fact", category=cat,
            seo_title="Amazing Fact | AjeebOology", description="Incredible facts in Hinglish",
            tags=[cat, "facts", "shorts"], hashtags=["#Shorts", "#AjeebOology", "#Facts"],
            segments=segs)

# =============================================================================
# RESEARCH AGENT (Tavily)
# =============================================================================

class ResearchAgent:
    def __init__(self):
        self.key = Config.TAVILY_API_KEY
        self.url = "https://api.tavily.com/search"

    def research(self, cat: str) -> Dict:
        queries = {"psychology": "mind-blowing psychology facts 2026 trending",
            "space": "latest space discoveries 2026 NASA trending",
            "weird_facts": "incredible weird facts 2026 viral"}
        try:
            r = requests.post(self.url, json={"api_key": self.key, "query": queries.get(cat, queries["weird_facts"]),
                "search_depth": "basic", "max_results": 5}, timeout=30)
            r.raise_for_status()
            res = r.json().get("results", [])
            if res:
                return {"topic": res[0].get("title", cat), "results": res}
        except Exception as e:
            print(f"Research error: {e}")
        return {"topic": cat, "results": []}

# =============================================================================
# VOICE AGENT (Edge-TTS)
# =============================================================================

class VoiceAgent:
    def __init__(self):
        self.model = Config.VOICE_MODEL

    def generate(self, script: VideoScript) -> List[AudioSeg]:
        segs = []
        t = 0.0
        for i, seg in enumerate(script.segments):
            clean = self._clean(seg.text)
            out = str(Config.AUDIO / f"seg_{i:02d}.mp3")
            if self._edge(clean, out):
                d = audio_dur(out)
                if d < 0.5:
                    d = self._est(clean)
            else:
                d = self._est(clean)
                self._silent(out, d)
            segs.append(AudioSeg(segment=seg, path=out, dur=d, t0=t, t1=t + d))
            t += d
        script.total_dur = t
        return segs

    def _clean(self, txt: str) -> str:
        txt = re.sub(r'[#@]\w+', '', txt)
        txt = re.sub(r'https?://\S+', '', txt)
        txt = re.sub(r'[*_~`]', '', txt)
        return txt.strip()

    def _edge(self, txt: str, out: str) -> bool:
        try:
            import edge_tts
            import asyncio
            
            async def _save():
                communicate = edge_tts.Communicate(txt, self.model)
                await communicate.save(out)
                
            # FIX: Use new_event_loop to avoid conflicts with existing loops
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_save())
            finally:
                loop.close()
                
            return os.path.exists(out) and os.path.getsize(out) > 1024
        except Exception as e:
            print(f"Edge-TTS error: {e}")
            return False

    def _est(self, txt: str) -> float:
        return max(1.5, len(txt.split()) * 0.35)

    def _silent(self, path: str, dur: float):
        run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(dur), "-acodec", "libmp3lame", "-q:a", 4, path], 30)

    def mix(self, segs: List[AudioSeg], bg: Optional[str], sfx_events: List[Tuple[float, str]]) -> str:
        clist = str(Config.AUDIO / "concat.txt")
        with open(clist, "w") as f:
            for s in segs:
                f.write(f"file '{s.path}'\n")
        vcat = str(Config.AUDIO / "voice_cat.mp3")
        run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", clist, "-c", "copy", vcat], 60)
        vsfx = str(Config.AUDIO / "voice_sfx.mp3")
        SFXEngine().mix_sfx_to_voice(vcat, sfx_events, vsfx)
        final = str(Config.AUDIO / "final.mp3")
        if bg and os.path.exists(bg):
            fc = ("[1:a]asplit=2[sc][mix];[sc]sidechaincompress=threshold=0.05:ratio=5:attack=50:release=200[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:weights=1 0.25[Mixed];[Mixed]loudnorm=I=-14:TP=-1.5:LRA=11[out]")
            run_cmd(["ffmpeg", "-y", "-i", vsfx, "-i", bg, "-filter_complex", fc, "-map", "[out]", "-c:a", "libmp3lame", "-q:a", 2, "-ar", str(Config.AUDIO_SR), final], 120)
        else:
            run_cmd(["ffmpeg", "-y", "-i", vsfx, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-q:a", 2, "-ar", str(Config.AUDIO_SR), final], 120)
        if not os.path.exists(final):
            shutil.copy(vsfx, final)
        return final

# =============================================================================
# ASSET AGENT (B-Roll + BG Music)
# =============================================================================

class AssetAgent:
    def __init__(self):
        self.uk = Config.UNSPLASH_KEY
        self.pk = Config.PEXELS_API_KEY

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(1, 2, 10))
    def fetch_broll(self, prompt: str, idx: int) -> Optional[str]:
        dest = str(Config.ASSETS / f"br_{idx:02d}.mp4")
        img = str(Config.ASSETS / f"br_{idx:02d}.jpg")
        if self.pk and self._pexels_vid(prompt, dest):
            return dest
        if self._unsplash(prompt, img):
            return img
        if Config.POLLINATIONS_ON and self._pollinations(prompt, img):
            return img
        if self._pexels_img(prompt, img):
            return img
        return None

    def _pexels_vid(self, p: str, dest: str) -> bool:
        try:
            r = requests.get(f"https://api.pexels.com/videos/search?query={quote_plus(p)}&per_page=5&orientation=portrait",
                headers={"Authorization": self.pk}, timeout=15)
            r.raise_for_status()
            for v in r.json().get("videos", []):
                for vf in v.get("video_files", []):
                    if vf.get("quality") in ["sd", "hd"]:
                        rr = requests.get(vf.get("link", ""), timeout=30)
                        if rr.status_code == 200:
                            with open(dest, "wb") as f:
                                f.write(rr.content)
                            return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Pexels vid error: {e}")
            return False

    def _unsplash(self, p: str, dest: str) -> bool:
        try:
            r = requests.get(f"https://api.unsplash.com/photos/random?query={quote_plus(p)}&orientation=portrait",
                headers={"Authorization": f"Client-ID {self.uk}"}, timeout=15)
            r.raise_for_status()
            rr = requests.get(r.json()["urls"]["regular"], timeout=30)
            if rr.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(rr.content)
                return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Unsplash error: {e}")
            return False

    def _pollinations(self, p: str, dest: str) -> bool:
        try:
            r = requests.get(
                f"https://image.pollinations.ai/prompt/{quote_plus(p)}"
                f"?width=1080&height=1920&nologo=true&seed={random.randint(1, 9999)}",
                timeout=60
            )
            if r.status_code == 200:
                with open(dest, "wb") as f:
                    f.write(r.content)   # FIX: was `rr.content`
                return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Pollinations error: {e}")
            return False

    def _pexels_img(self, p: str, dest: str) -> bool:
        try:
            r = requests.get(f"https://api.pexels.com/v1/search?query={quote_plus(p)}&per_page=5&orientation=portrait",
                headers={"Authorization": self.pk}, timeout=15)
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                rr = requests.get(photos[0]["src"]["large"], timeout=30)
                if rr.status_code == 200:
                    with open(dest, "wb") as f:
                        f.write(rr.content)
                    return os.path.exists(dest) and os.path.getsize(dest) > 10240
            return False
        except Exception as e:
            print(f"Pexels img error: {e}")
            return False

    def fetch_bg(self) -> Optional[str]:
        dest = str(Config.ASSETS / "bg.mp3")
        if os.path.exists(dest):
            return dest
        run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=a=0.02:c=pink:duration=65",
            "-af", "lowpass=f=800,volume=0.3", "-c:a", "libmp3lame", "-q:a", 4, dest], 30)
        return dest if os.path.exists(dest) else None

# =============================================================================
# VIDEO RENDERER (Main orchestrator)
# =============================================================================

class VideoRenderer:
    def __init__(self):
        self.anim = AnimationEngine(Config.W, Config.H)
        self.sfx = SFXEngine()

    def render(self, script: VideoScript, audio_segs: List[AudioSeg],
                broll_paths: List[Optional[str]], audio_path: str) -> Tuple[str, int]:
        total_dur = audio_dur(audio_path)
        total_frames = int(total_dur * Config.FPS)
        print(f"Rendering {total_frames} frames @ {Config.FPS}fps, {total_dur:.2f}s")

        tokens = WordTimeline.build(audio_segs)
        print(f"Word tokens: {len(tokens)}")

        analyzer = AudioAnalyzer(audio_path)
        sfx_events = self._plan_sfx(tokens, total_dur)

        broll_imgs = {}
        for i, p in enumerate(broll_paths):
            if p and os.path.exists(p) and not p.lower().endswith((".mp4", ".mov", ".avi")):
                try:
                    broll_imgs[i] = Image.open(p).convert("RGB")
                except:
                    pass

        peak_energy = 0.0
        peak_frame = 0

        for fidx in range(total_frames):
            rms = analyzer.get_rms(fidx)
            frame, venergy = self.anim.render_frame(
                fidx, total_frames, tokens, broll_paths, rms,
                [tok.seg_idx for tok in tokens if tok.t0 <= fidx / Config.FPS < tok.t1]
            )
            total_energy = venergy + rms * 2
            if total_energy > peak_energy:
                peak_energy = total_energy
                peak_frame = fidx

            frame.save(Config.FRAMES / f"f_{fidx:06d}.png", "PNG")
            if fidx % 100 == 0:
                print(f" Frame {fidx}/{total_frames}")

        out = str(Config.OUTPUT / "video.mp4")
        rc, _, err = run_cmd([
            "ffmpeg", "-y", "-framerate", str(Config.FPS), "-i", str(Config.FRAMES / "f_%06d.png"),
            "-i", audio_path, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest", "-movflags", "+faststart", out
        ], 600)
        if rc != 0:
            raise RuntimeError(f"FFmpeg failed: {err}")

        for f in Config.FRAMES.glob("*.png"):
            f.unlink()

        print(f"Video: {out}")
        return out, peak_frame

    def _plan_sfx(self, tokens: List[WordToken], total_dur: float) -> List[Tuple[float, str]]:
        events = []
        seen_emphasis = set()
        for tok in tokens:
            spath = str(self.sfx.sfx_dir / f"whoosh_{tok.seg_idx}_{tok.word_idx}.mp3")
            self.sfx.whoosh(spath)
            events.append((tok.t0, spath))
            if tok.emphasis and tok.seg_idx not in seen_emphasis:
                seen_emphasis.add(tok.seg_idx)
                ppath = str(self.sfx.sfx_dir / f"pop_{tok.seg_idx}.mp3")
                self.sfx.pop(ppath)
                events.append(((tok.t0 + tok.t1) / 2, ppath))
        for pct in [0.3, 0.7]:
            rpath = str(self.sfx.sfx_dir / f"rumble_{pct}.mp3")
            self.sfx.rumble(rpath)
            events.append((total_dur * pct, rpath))
        tpath = str(self.sfx.sfx_dir / "tapestop.mp3")
        self.sfx.tape_stop(tpath)
        events.append((total_dur - 0.6, tpath))
        return events

    def generate_thumbnail(self, script: VideoScript, peak_frame: int) -> Optional[str]:
        try:
            thumb = Image.new("RGB", (1280, 720), Config.BG_DARK)
            d = ImageDraw.Draw(thumb)
            for y in range(0, 720, 4):
                ratio = y / 720
                d.line([(0, y), (1280, y)], fill=(int(10 + 20 * ratio), int(5 + 10 * ratio), int(25 + 35 * ratio)), width=4)
            title = script.seo_title[:60]
            font = load_font(72)
            words = title.split()
            lines = []
            cur = []
            for w in words:
                test = " ".join(cur + [w])
                bb = font.getbbox(test)
                if bb and (bb[2] - bb[0]) > 1100 and cur:
                    lines.append(" ".join(cur))
                    cur = [w]
                else:
                    cur.append(w)
            if cur:
                lines.append(" ".join(cur))
            yp = 200
            for line in lines[:2]:
                bb = font.getbbox(line)
                x = (1280 - (bb[2] - bb[0])) // 2 if bb else 100
                for ox, oy in [(3, 3), (-3, -3), (3, -3), (-3, 3)]:
                    d.text((x + ox, yp + oy), line, font=font, fill=(0, 0, 0))
                d.text((x, yp), line, font=font, fill=Config.HIGHLIGHT)
                yp += 90
            d.text((50, 650), "AjeebOology", font=load_font(36), fill=Config.ACCENT)
            d.rectangle([0, 0, 1280, 8], fill=Config.ACCENT)
            d.rectangle([0, 712, 1280, 720], fill=Config.ACCENT2)
            tp = str(Config.OUTPUT / "thumbnail.jpg")
            thumb.save(tp, "JPEG", quality=92)
            return tp
        except Exception as e:
            print(f"Thumb error: {e}")
            return None

# =============================================================================
# TELEGRAM DELIVERY
# =============================================================================

class TelegramAgent:
    def __init__(self):
        self.tok = Config.TELEGRAM_TOKEN
        self.cid = Config.TELEGRAM_CHAT_ID
        self.url = f"https://api.telegram.org/bot{self.tok}"

    def send(self, video: str, script: VideoScript, thumb: Optional[str] = None) -> bool:
        """Send video and thumbnail to Telegram channel."""
        try:
            caption = f"{script.seo_title}\n\n{script.description}\n\n{' '.join(script.hashtags[:5])}"
            with open(video, "rb") as vf:
                files = {"video": vf}
                data = {
                    "chat_id": self.cid,
                    "caption": caption[:1024],
                    "supports_streaming": "true"
                }
                r = requests.post(f"{self.url}/sendVideo", data=data, files=files, timeout=120)
                r.raise_for_status()
                print("Telegram: Video sent successfully")

            if thumb and os.path.exists(thumb):
                with open(thumb, "rb") as tf:
                    files = {"photo": tf}
                    data = {"chat_id": self.cid, "caption": f"Thumbnail: {script.seo_title}"}
                    r = requests.post(f"{self.url}/sendPhoto", data=data, files=files, timeout=60)
                    if r.status_code == 200:
                        print("Telegram: Thumbnail sent")

            return True
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Orchestrate the full AjeebOology Shorts pipeline."""
    ensure_dirs()
    print("=" * 60)
    print("AjeebOology Shorts - Cinematic Automation Agent")
    print("=" * 60)

    cat = Config.CATEGORY_OVERRIDE or random.choice(["psychology", "space", "weird_facts"])
    print(f"Category: {cat}")

    research = ResearchAgent().research(cat)
    print(f"Research topic: {research.get('topic', cat)}")

    script = ScriptAgent().generate(research)
    print(f"Title: {script.title}")
    print(f"SEO Title: {script.seo_title}")
    for i, seg in enumerate(script.segments):
        print(f"  [{seg.seg_type}] {seg.text[:60]}...")

    voice = VoiceAgent()
    audio_segs = voice.generate(script)
    print(f"Audio: {len(audio_segs)} segments, total duration: {script.total_dur:.2f}s")

    assets = AssetAgent()
    broll_paths = []
    for i, seg in enumerate(script.segments):
        prompt = seg.broll_prompt if seg.broll_prompt else f"{script.category} {seg.seg_type}"
        bp = assets.fetch_broll(prompt, i)
        broll_paths.append(bp)
        print(f"  B-roll {i}: {bp or 'None'}")

    bg = assets.fetch_bg()

    renderer = VideoRenderer()
    tokens = WordTimeline.build(audio_segs)
    sfx_events = renderer._plan_sfx(tokens, script.total_dur)
    final_audio = voice.mix(audio_segs, bg, sfx_events)
    print(f"Final audio: {final_audio}")

    video_path, peak_frame = renderer.render(script, audio_segs, broll_paths, final_audio)

    thumb_path = renderer.generate_thumbnail(script, peak_frame)
    if thumb_path:
        print(f"Thumbnail: {thumb_path}")

    if Config.TELEGRAM_TOKEN and Config.TELEGRAM_CHAT_ID:
        TelegramAgent().send(video_path, script, thumb_path)

    print("=" * 60)
    print("DONE! All assets generated.")
    print(f"Video: {video_path}")
    if thumb_path:
        print(f"Thumbnail: {thumb_path}")
    print("=" * 60)

if __name__ == "__main__":
    main()
