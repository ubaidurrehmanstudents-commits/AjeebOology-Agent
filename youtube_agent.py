#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional YouTube Shorts Automation Agent
Fully automated pipeline: Research -> Script -> Voice -> Whisper Sync -> Video -> Telegram
Language: Hinglish (Roman Hindi + English), Male voice
Output: Vertical 1080x1920, ~55-65 seconds, 24 FPS
Engine: FFmpeg filter_complex (Zero frame-by-frame rendering to save GitHub minutes)
"""

import os
import sys
import json
import re
import math
import random
import subprocess
import time
import shutil
import hashlib
import traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote_plus

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
import numpy as np

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Central configuration for the Ajeebology pipeline."""
    
    # API Keys from Environment
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
    PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
    UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    # GitHub Context
    GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")
    GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "local")
    
    # Video Specifications
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24
    TARGET_DURATION = 60.0
    MAX_DURATION = 65.0
    
    # Voice & Audio
    VOICE_MODEL = "hi-IN-MadhurNeural"
    AUDIO_SAMPLE_RATE = 44100
    
    # Typography & Fonts (Downloaded by YAML)
    FONTS_DIR = Path(os.environ.get("FONTS_DIR", "/tmp/ajeebology/fonts"))
    FONT_TITLE = str(FONTS_DIR / "BebasNeue-Regular.ttf")
    FONT_BODY = str(FONTS_DIR / "Montserrat-Bold.ttf")
    FONT_FALLBACK = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    
    # Colors (RGB)
    COLOR_BG_DARK = (10, 5, 25)
    COLOR_BG_MID = (30, 15, 60)
    COLOR_ACCENT = (0, 255, 255)      # Cyan
    COLOR_ACCENT_2 = (255, 0, 128)    # Magenta
    COLOR_TEXT = (255, 255, 255)
    COLOR_HIGHLIGHT = (255, 255, 0)   # Yellow
    
    # Directories
    BASE_DIR = Path("/tmp/ajeebology")
    FRAMES_DIR = BASE_DIR / "frames"      # Used sparingly for pre-rendered assets
    AUDIO_DIR = BASE_DIR / "audio"
    ASSETS_DIR = BASE_DIR / "assets"
    OUTPUT_DIR = BASE_DIR / "output"
    TMP_DIR = BASE_DIR / "tmp"
    
    # Pipeline Settings
    WHISPER_MODEL_SIZE = "tiny" # tiny is fast on CPU, base is more accurate. tiny is recommended for GH Actions.
    BROLL_ENABLED = True
    POLLINATIONS_ENABLED = True

# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ScriptSegment:
    text: str
    segment_type: str  # hook, fact1, fact2, fact3, outro
    emphasis_words: List[str] = field(default_factory=list)
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
    total_duration_estimate: float = 0.0

@dataclass
class AudioSegment:
    segment: ScriptSegment
    audio_path: str
    duration: float
    start_time: float
    end_time: float

@dataclass
class CaptionWord:
    text: str
    start_time: float
    end_time: float
    confidence: float = 1.0

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def setup_directories():
    """Create all necessary working directories."""
    dirs = [
        Config.BASE_DIR, Config.FRAMES_DIR, Config.AUDIO_DIR, 
        Config.ASSETS_DIR, Config.OUTPUT_DIR, Config.TMP_DIR
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

def run_command(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """Run shell command with timeout, return (returncode, stdout, stderr)."""
    try:
        # Flatten any lists in cmd for complex ffmpeg commands
        flat_cmd = []
        for item in cmd:
            if isinstance(item, list):
                flat_cmd.extend(item)
            else:
                flat_cmd.append(str(item))
                
        result = subprocess.run(
            flat_cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        print(f"Command timed out after {timeout}s: {' '.join(flat_cmd[:5])}...")
        return -1, "", "Command timed out"
    except Exception as e:
        print(f"Command execution error: {e}")
        return -1, "", str(e)

def get_media_duration(path: str) -> float:
    """Get audio/video duration using ffprobe."""
    if not os.path.exists(path):
        return 0.0
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    rc, out, _ = run_command(cmd, timeout=30)
    if rc == 0 and out.strip():
        try:
            return float(out.strip())
        except ValueError:
            return 0.0
    return 0.0

def download_file(url: str, dest: str, timeout: int = 30, retries: int = 3) -> bool:
    """Download file with retry logic and proper chunking."""
    for attempt in range(retries):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 \
                               (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, timeout=timeout, stream=True, headers=headers)
            resp.raise_for_status()
            
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except requests.exceptions.RequestException as e:
            print(f"Download attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    
    if os.path.exists(dest):
        os.remove(dest)
    return False

def safe_filename(text: str, max_len: int = 40) -> str:
    """Create safe, short filename from text."""
    text = re.sub(r'[^a-zA-Z0-9_-]', '_', text).strip('_')
    return text[:max_len]

def escape_ffmpeg_text(text: str) -> str:
    """Escape text for FFmpeg drawtext filter."""
    if not text:
        return ""
    # Escape backslashes, colons, single quotes, and percent signs
    text = text.replace('\\', '\\\\')
    text = text.replace(':', '\\:')
    text = text.replace("'", "\u2019") # Use right single quote to avoid escaping mess
    text = text.replace('%', '\\%')
    return text

def format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS.mmm string for logging."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02}:{mins:02}:{secs:02}.{ms:03}"

def cleanup_path(path: str | Path):
    """Safely delete a file or directory if it exists."""
    p = Path(path)
    try:
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
    except Exception as e:
        print(f"Cleanup warning for {p}: {e}")

# =============================================================================
# 1. RESEARCH MODULE (Tavily)
# =============================================================================

class ResearchAgent:
    """Fetches fresh facts using Tavily Search API."""
    
    CATEGORIES = ["psychology", "space", "weird_facts"]
    
    QUERIES = {
        "psychology": [
            "mind blowing psychology facts human behavior 2024 2025",
            "psychology tricks brain facts hindi urdu",
            "interesting psychological phenomena daily life"
        ],
        "space": [
            "amazing space facts universe secrets 2024 2025",
            "space discoveries recent mind blowing james webb",
            "astronomy facts that will blow your mind"
        ],
        "weird_facts": [
            "unbelievable facts about world strange but true",
            "weird facts that sound fake but are true",
            "amazing facts about earth animals humans"
        ]
    }
    
    def __init__(self):
        self.api_key = Config.TAVILY_API_KEY
        self.base_url = "https://api.tavily.com/search"
    
    def fetch_fact(self, category: Optional[str] = None) -> Dict:
        """Fetch a fresh fact topic from Tavily."""
        if not category:
            # Allow workflow_dispatch to override category
            override = os.environ.get("CATEGORY_OVERRIDE", "").strip()
            if override in self.CATEGORIES:
                category = override
            else:
                category = random.choice(self.CATEGORIES)
        
        query = random.choice(self.QUERIES[category])
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "max_results": 5
        }
        
        print(f"[ResearchAgent] Fetching research for category: {category}...")
        
        try:
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            results = data.get("results", [])
            if results:
                # Find the result with the most content
                best = max(results, key=lambda x: len(x.get("content", "")))
                return {
                    "category": category,
                    "title": best.get("title", ""),
                    "content": best.get("content", ""),
                    "url": best.get("url", ""),
                    "query": query
                }
        except Exception as e:
            print(f"[ResearchAgent] Error: {e}")
        
        print("[ResearchAgent] Using fallback fact.")
        return self._fallback(category)
    
    def _fallback(self, category: Optional[str]) -> Dict:
        """Provide hardcoded fallback facts if API fails."""
        fallbacks = {
            "psychology": {
                "title": "Psychology Facts That Will Blow Your Mind",
                "content": "Your brain can process images in just 13 milliseconds. The human mind is capable of creating false memories that feel completely real. Smiling can actually make you feel happier due to facial feedback effect.",
                "category": "psychology"
            },
            "space": {
                "title": "Space Secrets You Never Knew",
                "content": "A day on Venus is longer than its year. Neutron stars can spin 600 times per second. There are more trees on Earth than stars in the Milky Way galaxy.",
                "category": "space"
            },
            "weird_facts": {
                "title": "Weird Facts That Sound Fake",
                "content": "Honey never spoils. Wombat poop is cube-shaped. Bananas are berries but strawberries are not. Octopuses have three hearts and blue blood.",
                "category": "weird_facts"
            }
        }
        cat = category or random.choice(self.CATEGORIES)
        return fallbacks[cat]

# =============================================================================
# 2. SCRIPT GENERATION (Groq/LLaMA)
# =============================================================================

class ScriptAgent:
    """Generates structured Hinglish scripts using Groq LLaMA for maximum retention."""
    
    SYSTEM_PROMPT = """You are an elite YouTube Shorts scriptwriter and retention expert for "Ajeebology Shorts".
Your scripts are in HINGLISH (Roman Hindi + English mix), engaging, fast-paced, and optimized to go viral.

RETENTION RULES:
1. Write in natural Hinglish (Roman script Hindi mixed with English words).
2. Target 55-60 seconds when spoken at a fast, energetic pace (approx. 130-150 words).
3. HOOK must be attention-grabbing in the first 3 seconds. Ask a provocative question or state a mind-blowing fact.
4. Each FACT must be concise, mind-blowing, and easy to understand.
5. OUTRO must have a strong CTA (subscribe, comment, share) in under 5 seconds.
6. Mark EMPHASIS words (keywords, numbers, shocking phrases) with [WORD] brackets. These will be highlighted on screen.
7. Keep sentences short and punchy. No long explanations.
8. Provide a specific English B-roll prompt for each segment (e.g., "human brain glowing neural pathways", "galaxy spinning in space").

OUTPUT FORMAT: Return ONLY valid JSON with this exact structure:
{
    "title": "Catchy Hinglish title for video",
    "category": "psychology|space|weird_facts",
    "seo_title": "English SEO optimized title for YouTube",
    "description": "English description with keywords for algorithm",
    "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
    "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"],
    "segments": [
        {
            "type": "hook",
            "text": "Hinglish text with [emphasis] words",
            "broll_prompt": "English image search prompt for B-roll"
        },
        {
            "type": "fact1",
            "text": "...",
            "broll_prompt": "..."
        },
        {
            "type": "fact2",
            "text": "...",
            "broll_prompt": "..."
        },
        {
            "type": "fact3",
            "text": "...",
            "broll_prompt": "..."
        },
        {
            "type": "outro",
            "text": "...",
            "broll_prompt": "..."
        }
    ]
}"""

    def __init__(self):
        self.api_key = Config.GROQ_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        if not self.api_key:
            print("[ScriptAgent] WARNING: GROQ_API_KEY is missing. Will use fallback script.")

    def generate_script(self, research_data: Dict) -> VideoScript:
        """Generate complete video script from research data."""
        if not self.api_key:
            return self._fallback_script(research_data)
            
        user_prompt = f"""Create a viral YouTube Shorts script based on this research:
Category: {research_data['category']}
Title: {research_data['title']}
Content: {research_data['content']}

Make it engaging, mind-blowing, and perfect for a Hinglish-speaking audience aged 16-30. 
Remember to strictly follow the JSON format and include exactly 5 segments (hook, fact1, fact2, fact3, outro)."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.8,
            "max_tokens": 1500,
            "response_format": {"type": "json_object"}
        }
        
        print("[ScriptAgent] Requesting script from Groq LLaMA...")
        
        try:
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=45)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            script_data = json.loads(content)
            
            return self._parse_script(script_data)
        except Exception as e:
            print(f"[ScriptAgent] Error generating script: {e}")
            return self._fallback_script(research_data)
    
    def _parse_script(self, data: Dict) -> VideoScript:
        """Parse JSON response into VideoScript object."""
        segments = []
        for seg_data in data.get("segments", []):
            text = seg_data.get("text", "")
            # Extract emphasis words marked with [ ]
            emphasis = re.findall(r'\[(.*?)\]', text)
            # Remove brackets from clean text for TTS
            clean_text = re.sub(r'\[(.*?)\]', r'\1', text)
            
            segments.append(ScriptSegment(
                text=clean_text.strip(),
                segment_type=seg_data.get("type", "fact"),
                emphasis_words=[e.strip() for e in emphasis],
                broll_prompt=seg_data.get("broll_prompt", "")
            ))
        
        # Ensure we have at least some segments
        if not segments:
            return self._fallback_script({"category": data.get("category", "weird_facts")})
        
        return VideoScript(
            title=data.get("title", "Amazing Facts"),
            category=data.get("category", "weird_facts"),
            seo_title=data.get("seo_title", "Mind Blowing Facts You Need To Know"),
            description=data.get("description", "Subscribe for more amazing facts!"),
            tags=data.get("tags", ["facts", "shorts", "viral"]),
            hashtags=data.get("hashtags", ["#facts", "#shorts", "#viral"]),
            segments=segments
        )
    
    def _fallback_script(self, research: Dict) -> VideoScript:
        """Generate a hardcoded fallback script if API fails."""
        print("[ScriptAgent] Using fallback script.")
        category = research.get("category", "weird_facts")
        
        templates = {
            "psychology": [
                ScriptSegment("Kya aap jaante hain aapka brain har [13 milliseconds] mein ek image process kar sakta hai?", "hook", ["13 milliseconds"], "human brain glowing neural pathways"),
                ScriptSegment("Psychology ke ek experiment mein researchers ne dekha ki [false memories] create karna kitna aasan hai.", "fact1", ["false memories"], "person thinking confused memory"),
                ScriptSegment("Agar aap forcefully [smile] karte hain, toh aapka brain automatically [happy hormones] release kar deta hai.", "fact2", ["smile", "happy hormones"], "person smiling happiness light"),
                ScriptSegment("Aur ek study ke mutabik, aapke decisions ka [90%] aapke subconscious mind control karta hai.", "fact3", ["90%", "subconscious mind"], "subconscious mind brain dark"),
                ScriptSegment("Agar ye facts pasand aaye toh [subscribe] karo aur comments mein batao aapko kaunsa fact sabse zyada shocking laga!", "outro", ["subscribe"], "youtube subscribe button 3d")
            ],
            "space": [
                ScriptSegment("Venus par ek din [243 Earth days] ka hota hai, lekin saal sirf [225 days] ka!", "hook", ["243 Earth days", "225 days"], "venus planet rotating space"),
                ScriptSegment("Neutron stars itni tezi se spin karti hain ki ek second mein [600 baar] ghoom jaati hain.", "fact1", ["600 baar"], "neutron star spinning glowing"),
                ScriptSegment("Aur Earth par trees [Milky Way] ke stars se zyada hain!", "fact2", ["Milky Way"], "milky way galaxy stars night"),
                ScriptSegment("Space mein ek [giant cloud] hai jo alcohol se bana hai, jiski value [1000 trillion dollars] hai.", "fact3", ["giant cloud", "1000 trillion dollars"], "space nebula cloud colorful"),
                ScriptSegment("Aur bhi amazing space facts ke liye [follow] karo Ajeebology Shorts ko!", "outro", ["follow"], "astronaut floating earth")
            ],
            "weird_facts": [
                ScriptSegment("Honey kabhi [spoil] nahi hota, archaeologists ne [3000 saal] purana honey khaya tha!", "hook", ["spoil", "3000 saal"], "ancient honey jar gold"),
                ScriptSegment("Wombat ka poop [cube-shaped] hota hai, nature ka sabse weird phenomenon!", "fact1", ["cube-shaped"], "wombat animal australia grass"),
                ScriptSegment("Banana technically ek [berry] hai, lekin strawberry nahi!", "fact2", ["berry"], "banana bunch close up"),
                ScriptSegment("Octopus ke paas [teen dil] hain aur unka blood [blue] hota hai!", "fact3", ["teen dil", "blue"], "octopus underwater blue"),
                ScriptSegment("Aise hi [mind-blowing] facts ke liye channel ko subscribe karo!", "outro", ["mind-blowing"], "shocked surprised face meme")
            ]
        }
        
        segs = templates.get(category, templates["weird_facts"])
        
        return VideoScript(
            title=f"Amazing {category.title()} Facts",
            category=category,
            seo_title=f"Mind Blowing {category.title()} Facts You Need To Know",
            description=f"Amazing {category} facts in Hinglish. Subscribe for daily mind-blowing content!",
            tags=[category, "facts", "hinglish", "shorts", "viral"],
            hashtags=[f"#{category}", "#facts", "#shorts", "#viral", "#hinglish"],
            segments=segs
        )

# =============================================================================
# 3. VOICE GENERATION (edge-tts)
# =============================================================================

class VoiceAgent:
    """Generates male Hindi voiceover using edge-tts with precise duration tracking."""
    
    def __init__(self):
        self.voice = Config.VOICE_MODEL
    
    def generate_voice(self, script: VideoScript) -> List[AudioSegment]:
        """Generate voice for each segment and return with timings."""
        print("[VoiceAgent] Generating voiceover segments...")
        audio_segments = []
        current_time = 0.0
        
        for i, segment in enumerate(script.segments):
            tts_text = self._clean_for_tts(segment.text)
            output_path = str(Config.AUDIO_DIR / f"segment_{i:02d}.mp3")
            
            success = self._generate_with_edge_tts(tts_text, output_path)
            
            if not success:
                # Fallback to silent audio if TTS fails completely
                duration = max(2.0, len(tts_text) / 4.5)
                self._create_silent_audio(output_path, duration)
            
            duration = get_media_duration(output_path)
            if duration == 0.0:
                duration = max(2.0, len(tts_text) / 4.5)
                self._create_silent_audio(output_path, duration)
                duration = get_media_duration(output_path)
            
            audio_segments.append(AudioSegment(
                segment=segment,
                audio_path=output_path,
                duration=duration,
                start_time=current_time,
                end_time=current_time + duration
            ))
            
            # Add a tiny pause between segments for rhythm (except after hook)
            pause = 0.2 if segment.segment_type == "hook" else 0.15
            current_time += duration + pause
            
            print(f"  -> Segment {i} ({segment.segment_type}): {duration:.2f}s")
        
        # Adjust end_times to exclude the final pause
        if audio_segments:
            audio_segments[-1].end_time = audio_segments[-1].start_time + audio_segments[-1].duration
            script.total_duration_estimate = audio_segments[-1].end_time
            
        print(f"[VoiceAgent] Total voice duration: {script.total_duration_estimate:.2f}s")
        return audio_segments
    
    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS processing."""
        text = re.sub(r'[!]{2,}', '!', text)
        text = re.sub(r'[?]{2,}', '?', text)
        text = text.replace('[', '').replace(']', '') # Remove any leftover brackets
        return text.strip()
    
    def _generate_with_edge_tts(self, text: str, output_path: str) -> bool:
        """Generate audio using edge-tts CLI."""
        try:
            cmd = [
                "edge-tts",
                "--voice", self.voice,
                "--text", text,
                "--write-media", output_path,
                "--rate", "+15%"  # Slightly faster for Shorts retention
            ]
            rc, _, err = run_command(cmd, timeout=60)
            if rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True
            print(f"[VoiceAgent] edge-tts failed. Error: {err}")
        except Exception as e:
            print(f"[VoiceAgent] edge-tts exception: {e}")
        return False
    
    def _create_silent_audio(self, path: str, duration: float):
        """Create silent audio as fallback."""
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration), "-acodec", "libmp3lame", "-q:a", "4", path
        ]
        run_command(cmd, timeout=30)

    def mix_audio(self, audio_segments: List[AudioSegment], bg_music_path: Optional[str] = None) -> str:
        """Mix all segments + background music into final audio track."""
        print("[VoiceAgent] Mixing audio segments...")
        
        # 1. Concatenate voice segments with tiny pauses for rhythm
        concat_list = Config.AUDIO_DIR / "concat_list.txt"
        silence_path = Config.AUDIO_DIR / "silence_short.mp3"
        self._create_silent_audio(str(silence_path), 0.15)
        
        with open(concat_list, "w") as f:
            for i, seg in enumerate(audio_segments):
                f.write(f"file '{seg.audio_path}'\n")
                if i < len(audio_segments) - 1:
                    pause = 0.2 if seg.segment.segment_type == "hook" else 0.15
                    if pause > 0:
                        f.write(f"file '{silence_path}'\n")
        
        mixed_voice_path = str(Config.AUDIO_DIR / "mixed_voice.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-acodec", "libmp3lame", "-q:a", "2",
            mixed_voice_path
        ]
        run_command(cmd, timeout=120)
        
        # 2. Mix with background music if available
        if bg_music_path and os.path.exists(bg_music_path):
            print("[VoiceAgent] Mixing with background music...")
            final_path = str(Config.AUDIO_DIR / "final_audio.mp3")
            
            voice_duration = get_media_duration(mixed_voice_path)
            
            # Background music: volume 0.12, loop until voice ends, fade out at the end
            bg_filter = f"[1:a]aloop=loop=-1:size=2e9,volume=0.12,afade=t=out:st={max(0, voice_duration-1.5)}:d=1.5[bg]"
            voice_filter = "[0:a]volume=1.0[voice]"
            mix_filter = "[voice][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            
            cmd = [
                "ffmpeg", "-y",
                "-i", mixed_voice_path,
                "-i", bg_music_path,
                "-filter_complex", f"{bg_filter};{voice_filter};{mix_filter}",
                "-map", "[aout]",
                "-acodec", "libmp3lame", "-q:a", "2",
                "-t", str(voice_duration), # Ensure music doesn't overextend
                final_path
            ]
            rc, _, err = run_command(cmd, timeout=120)
            if rc == 0:
                return final_path
            print(f"[VoiceAgent] Music mix failed, using voice only. Error: {err}")
        
        return mixed_voice_path

# =============================================================================
# 4. B-ROLL, MOTION GRAPHICS & ASSETS
# =============================================================================

class AssetAgent:
    """Downloads video B-roll, motion backgrounds, music, and SFX."""
    
    def __init__(self):
        self.pexels_headers = {"Authorization": Config.PEXELS_API_KEY} if Config.PEXELS_API_KEY else {}
        self.unsplash_headers = {"Authorization": f"Client-ID {Config.UNSPLASH_ACCESS_KEY}"} if Config.UNSPLASH_ACCESS_KEY else {}
        
    def fetch_broll(self, prompt: str, index: int) -> Tuple[Optional[str], bool]:
        """
        Fetch B-roll for a segment.
        Returns: (path, is_video)
        Prioritizes Pexels Videos -> Unsplash Images -> Pollinations AI.
        """
        safe_prompt = safe_filename(prompt)[:30]
        
        # 1. Try Pexels Video (Best for motion graphics feel)
        if Config.PEXELS_API_KEY:
            video_path = str(Config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.mp4")
            if self._try_pexels_video(prompt, video_path):
                return video_path, True
        
        # 2. Try Unsplash Image
        if Config.UNSPLASH_ACCESS_KEY:
            img_path = str(Config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.jpg")
            if self._try_unsplash(prompt, img_path):
                return img_path, False
        
        # 3. Try Pollinations AI Image
        if Config.POLLINATIONS_ENABLED:
            img_path = str(Config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.jpg")
            if self._try_pollinations(prompt, img_path):
                return img_path, False
                
        return None, False

    def fetch_motion_background(self) -> Optional[str]:
        """Fetch a looping motion background video for text overlays."""
        if not Config.PEXELS_API_KEY:
            return None
            
        print("[AssetAgent] Fetching motion background...")
        prompts = ["abstract dark particles", "technology background loop", "galaxy space stars moving", "dark smoke flowing"]
        prompt = random.choice(prompts)
        
        dest = str(Config.ASSETS_DIR / "motion_bg.mp4")
        if self._try_pexels_video(prompt, dest, max_duration=10):
            return dest
        return None

    def _try_pexels_video(self, prompt: str, dest: str, max_duration: int = 15) -> bool:
        """Search and download a vertical video from Pexels."""
        try:
            url = f"https://api.pexels.com/videos/search?query={quote_plus(prompt)}&per_page=15&orientation=portrait"
            resp = requests.get(url, headers=self.pexels_headers, timeout=15)
            if resp.status_code != 200:
                return False
                
            data = resp.json()
            videos = data.get("videos", [])
            
            # Filter for suitable videos (vertical/short duration/HD)
            valid_videos = []
            for v in videos:
                if v.get("duration", 99) <= max_duration:
                    # Find the HD portrait file
                    for vf in v.get("video_files", []):
                        w, h = vf.get("width", 0), vf.get("height", 0)
                        # Look for 1080x1920 or 720x1280
                        if h > w and w >= 720:
                            valid_videos.append(vf["link"])
                            break
            
            if valid_videos:
                # Pick a random one from the top results to keep content fresh
                video_url = random.choice(valid_videos)
                return download_file(video_url, dest, timeout=45)
                
        except Exception as e:
            print(f"[AssetAgent] Pexels video error: {e}")
        return False

    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        """Search Unsplash for high-quality portrait images."""
        try:
            url = f"https://api.unsplash.com/search/photos?query={quote_plus(prompt)}&per_page=10&orientation=portrait"
            resp = requests.get(url, headers=self.unsplash_headers, timeout=15)
            if resp.status_code != 200:
                return False
                
            data = resp.json()
            results = data.get("results", [])
            if results:
                # Pick a random top result
                img_data = random.choice(results[:5])
                img_url = img_data["urls"]["regular"] # Usually 1080p
                return download_file(img_url, dest, timeout=30)
        except Exception as e:
            print(f"[AssetAgent] Unsplash error: {e}")
        return False

    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        """Generate an AI image using Pollinations.ai as a fallback."""
        try:
            enhanced = f"professional cinematic still, {prompt}, dark moody lighting, high contrast, 8k"
            encoded = quote_plus(enhanced)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&seed={random.randint(1, 10000)}&nologo=true"
            return download_file(url, dest, timeout=60)
        except Exception as e:
            print(f"[AssetAgent] Pollinations error: {e}")
        return False

    def fetch_background_music(self) -> Optional[str]:
        """Download royalty-free background music from Pixabay."""
        # Using specific high-energy, low-melody background tracks suitable for Shorts
        music_urls = [
            "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3", # Tech/Trap beat
            "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3", # Cinematic pulse
            "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3", # Upbeat electronic
            "https://cdn.pixabay.com/download/audio/2024/02/18/audio_06c7536080.mp3"  # Dark synthwave
        ]
        
        dest = str(Config.ASSETS_DIR / "bg_music.mp3")
        random.shuffle(music_urls)
        for url in music_urls:
            if download_file(url, dest, timeout=45):
                return dest
        return None

    def fetch_sfx(self, sfx_type: str) -> Optional[str]:
        """Download specific sound effects for retention editing."""
        # Map SFX types to Pixabay CDN URLs
        sfx_library = {
            "whoosh": "https://cdn.pixabay.com/download/audio/2022/03/10/audio_8e9a3f1d3e.mp3",
            "impact": "https://cdn.pixabay.com/download/audio/2022/03/15/audio_9b7f3e1d2a.mp3",
            "pop": "https://cdn.pixabay.com/download/audio/2022/03/24/audio_c8c8a73467.mp3",
            "ding": "https://cdn.pixabay.com/download/audio/2022/04/27/audio_1808fbf07a.mp3"
        }
        
        url = sfx_library.get(sfx_type)
        if url:
            dest = str(Config.ASSETS_DIR / f"sfx_{sfx_type}.mp3")
            if download_file(url, dest, timeout=20):
                return dest
        return None

# =============================================================================
# 5. WHISPER CAPTION SYNC (Word-Level Karaoke)
# =============================================================================

class CaptionSyncAgent:
    """Uses faster-whisper to generate precise word-level timestamps for karaoke captions."""
    
    def __init__(self):
        from faster_whisper import WhisperModel
        print("[CaptionSyncAgent] Loading faster-whisper model (tiny)...")
        # Use CPU with int8 precision for speed on GitHub Actions
        self.model = WhisperModel(Config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        
    def transcribe(self, audio_path: str) -> List[CaptionWord]:
        """Transcribe audio and return word-level timings."""
        print(f"[CaptionSyncAgent] Transcribing {audio_path}...")
        try:
            segments, info = self.model.transcribe(
                audio_path, 
                beam_size=1, 
                word_timestamps=True,
                vad_filter=True # Filters out silence to speed up processing
            )
            
            words = []
            for segment in segments:
                for word in segment.words:
                    clean_word = word.word.strip()
                    if clean_word:
                        words.append(CaptionWord(
                            text=clean_word,
                            start_time=word.start,
                            end_time=word.end,
                            confidence=word.probability
                        ))
                            
            print(f"[CaptionSyncAgent] Transcribed {len(words)} words.")
            return words
            
        except Exception as e:
            print(f"[CaptionSyncAgent] Transcription failed: {e}")
            return []

    def align_to_script(self, script_words: List[str], whisper_words: List[CaptionWord]) -> List[CaptionWord]:
        """
        Aligns Whisper's output back to our original script words.
        This corrects any minor mispronunciations or hallucinations by Whisper,
        ensuring the text on screen perfectly matches the script.
        """
        if not whisper_words:
            return []

        aligned = []
        w_idx = 0
        tolerance = 0.6 # How similar words must be to match

        for s_word in script_words:
            matched = False
            # Look ahead in whisper words to find a match
            for i in range(w_idx, min(w_idx + 3, len(whisper_words))):
                w_word = whisper_words[i]
                # Simple similarity check (lowercase, alphanumeric only)
                s_clean = re.sub(r'[^a-z0-9]', '', s_word.lower())
                w_clean = re.sub(r'[^a-z0-9]', '', w_word.text.lower())
                
                if s_clean and w_clean and (s_clean in w_clean or w_clean in s_clean):
                    aligned.append(CaptionWord(
                        text=s_word, # Keep original script word for display
                        start_time=w_word.start_time,
                        end_time=w_word.end_time,
                        confidence=w_word.confidence
                    ))
                    w_idx = i + 1
                    matched = True
                    break
            
            if not matched:
                # If no match, interpolate timing based on neighbors
                start_t = aligned[-1].end_time if aligned else 0.0
                end_t = whisper_words[w_idx].start_time if w_idx < len(whisper_words) else start_t + 0.2
                aligned.append(CaptionWord(
                    text=s_word,
                    start_time=start_t,
                    end_time=max(start_t + 0.1, end_t),
                    confidence=0.5
                ))
                
        return aligned

# =============================================================================
# 6. PROFESSIONAL VIDEO RENDERING ENGINE (Part 1: Asset Prep)
# =============================================================================

class VideoEngine:
    """
    Hybrid Rendering Engine:
    - PIL for pre-rendering high-quality transparent text/assets.
    - FFmpeg filter_complex for motion graphics, Ken Burns, and final composition.
    """
    
    def __init__(self):
        self.width = Config.WIDTH
        self.height = Config.HEIGHT
        self.fps = Config.FPS
        
        self.font_title = self._load_font(Config.FONT_TITLE, 90)
        self.font_body = self._load_font(Config.FONT_BODY, 60)
        self.font_small = self._load_font(Config.FONT_BODY, 40)
        
    def _load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """Load font with robust fallback."""
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            alternatives = [
                Config.FONT_FALLBACK,
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            ]
            for alt in alternatives:
                try:
                    return ImageFont.truetype(alt, size)
                except:
                    continue
            return ImageFont.load_default()

    def _wrap_text(self, text: str, font, max_width: int) -> List[str]:
        """Wrap text to fit within max_width."""
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

    def _draw_rounded_card(self, draw: ImageDraw, bbox: List[int], radius: int, 
                           fill: Tuple, outline: Optional[Tuple] = None, outline_width: int = 2):
        """Draw rounded rectangle card."""
        draw.rounded_rectangle(bbox, radius=radius, fill=fill)
        if outline:
            draw.rounded_rectangle(bbox, radius=radius, outline=outline, width=outline_width)

    def pre_render_text_chunks(self, aligned_words: List[CaptionWord]) -> List[Dict]:
        """
        Groups word-level timings into 3-4 word chunks.
        Pre-renders each chunk as a transparent PNG for FFmpeg overlay.
        Returns list of dicts: {path, start, end}
        """
        print("[VideoEngine] Pre-rendering text chunks for karaoke captions...")
        chunks = []
        
        # Group words into chunks of 3-4 words for better readability
        current_chunk_words = []
        chunk_idx = 0
        
        for i, word in enumerate(aligned_words):
            current_chunk_words.append(word)
            
            # Create chunk every 3 words, or if there's a long pause, or at the end
            is_last_word = (i == len(aligned_words) - 1)
            long_pause = (i < len(aligned_words) - 1 and 
                          aligned_words[i+1].start_time - word.end_time > 0.3)
            
            if len(current_chunk_words) >= 3 or is_last_word or long_pause:
                chunk_text = " ".join([w.text for w in current_chunk_words])
                start_t = current_chunk_words[0].start_time
                end_t = current_chunk_words[-1].end_time
                
                # Render PNG
                img_path = str(Config.FRAMES_DIR / f"text_{chunk_idx:04d}.png")
                self._render_text_png(chunk_text, img_path, current_chunk_words)
                
                chunks.append({
                    "path": img_path,
                    "start": start_t,
                    "end": max(end_t, start_t + 0.4) # Ensure minimum visibility
                })
                
                current_chunk_words = []
                chunk_idx += 1
                
        print(f"[VideoEngine] Rendered {len(chunks)} text chunks.")
        return chunks

    def _render_text_png(self, text: str, output_path: str, words: List[CaptionWord]):
        """Render a single text chunk as a high-quality transparent PNG."""
        # Create a large transparent canvas
        img = Image.new("RGBA", (self.width, 400), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        font = self.font_body
        max_width = self.width - 160
        
        lines = self._wrap_text(text, font, max_width)
        line_height = font.size + 20
        total_height = len(lines) * line_height
        
        # Draw text with glow/shadow for professional pop
        y = 0
        for line in lines:
            bbox = font.getbbox(line)
            text_w = bbox[2] - bbox[0]
            x = (self.width - text_w) // 2
            
            # Draw shadow/glow
            for offset in range(4, 0, -1):
                shadow_color = (0, 0, 0, 80 + (4-offset)*20)
                draw.text((x+offset, y+offset), line, font=font, fill=shadow_color)
                draw.text((x-offset, y+offset), line, font=font, fill=shadow_color)
                draw.text((x+offset, y-offset), line, font=font, fill=shadow_color)
                draw.text((x-offset, y-offset), line, font=font, fill=shadow_color)
            
            # Draw main text
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
            y += line_height
            
        # Crop to content
        img = img.crop((0, 0, self.width, y))
        img.save(output_path, "PNG")

    def pre_render_brand_assets(self):
        """Pre-render static UI overlays (Progress bar base, Channel Badge)."""
        # Channel Badge
        badge = Image.new("RGBA", (220, 50), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)
        self._draw_rounded_card(draw, [0, 0, 220, 50], radius=25, fill=(20, 20, 40, 200), outline=Config.COLOR_ACCENT, outline_width=2)
        draw.ellipse([15, 17, 27, 29], fill=(255, 50, 50))
        draw.text((35, 25), "AJEEBOLOGY", font=self.font_small, fill=(255, 255, 255, 255), anchor="lm")
        badge.save(str(Config.FRAMES_DIR / "badge.png"), "PNG")
        
        # CTA Background
        cta = Image.new("RGBA", (450, 90), (0, 0, 0, 0))
        draw = ImageDraw.Draw(cta)
        self._draw_rounded_card(draw, [0, 0, 450, 90], radius=20, fill=Config.COLOR_ACCENT_2, outline=(255, 255, 255, 255), outline_width=3)
        cta.save(str(Config.FRAMES_DIR / "cta_bg.png"), "PNG")

    def inject_sfx(self, audio_path: str, sfx_paths: Dict[str, str], audio_segments: List[AudioSegment]) -> str:
        """Inject sound effects at emphasis points to boost retention."""
        print("[VideoEngine] Injecting SFX into audio track...")
        inputs = ["-i", audio_path]
        filter_complex = "[0:a]volume=1.0[base];"
        amix_inputs = ["[base]"]
        
        sfx_idx = 1
        for seg in audio_segments:
            if seg.segment.emphasis_words:
                # Play 'pop' or 'whoosh' slightly before the segment starts
                sfx_file = sfx_paths.get("whoosh") if seg.segment.segment_type == "hook" else sfx_paths.get("pop")
                if sfx_file:
                    start_t = max(0, seg.start_time - 0.1)
                    delay_ms = int(start_t * 1000)
                    
                    inputs.extend(["-i", sfx_file])
                    # Add delay to the SFX track
                    filter_complex += f"[{sfx_idx}:a]adelay={delay_ms}|{delay_ms},volume=0.6[s{sfx_idx}];"
                    amix_inputs.append(f"[s{sfx_idx}]")
                    sfx_idx += 1
                    
        if sfx_idx == 1:
            return audio_path # No SFX added
            
        filter_complex += f"{''.join(amix_inputs)}amix=inputs={sfx_idx}:duration=first:dropout_transition=0[aout]"
        
        output_path = str(Config.AUDIO_DIR / "final_with_sfx.mp3")
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-acodec", "libmp3lame", "-q:a", "2",
            output_path
        ]
        
        rc, _, err = run_command(cmd, timeout=120)
        if rc == 0:
            return output_path
        print(f"[VideoEngine] SFX injection failed: {err}")
        return audio_path

    # =============================================================================
    # 6. PROFESSIONAL VIDEO RENDERING ENGINE (Part 2: Final Composition)
    # =============================================================================
    
    def render_video(self, script: VideoScript, audio_segments: List[AudioSegment],
                     broll_assets: List[Tuple[Optional[str], bool]], motion_bg_path: Optional[str],
                     text_chunks: List[Dict], final_audio_path: str) -> str:
        """Main video rendering using FFmpeg filter_complex."""
        print("[VideoEngine] Building FFmpeg filter_complex...")
        
        total_duration = get_media_duration(final_audio_path)
        if total_duration == 0:
            total_duration = script.total_duration_estimate + 2.0
            
        inputs = []
        filter_complex = ""
        input_idx = 0
        
        # 0. Main Audio Track
        inputs.extend(["-i", final_audio_path])
        audio_idx = input_idx
        input_idx += 1
        
        # 1. Motion Background (Looping video)
        has_motion_bg = False
        if motion_bg_path:
            inputs.extend(["-stream_loop", "-1", "-i", motion_bg_path, "-t", str(total_duration)])
            motion_bg_idx = input_idx
            input_idx += 1
            has_motion_bg = True
            # Darken and scale the motion background
            filter_complex += f"[{motion_bg_idx}:v]scale={self.width}:{self.height},setpts=PTS-STARTPTS,colorchannelmixer=rr=0.3:gg=0.3:bb=0.3[bg];"
        else:
            # Fallback: Solid color background
            filter_complex += f"color=c=0x0A0519:s={self.width}x{self.height}:d={total_duration}[bg];"

        # 2. B-Roll Assets
        broll_labels = []
        for i, (path, is_video) in enumerate(broll_assets):
            seg = audio_segments[i]
            seg_duration = seg.end_time - seg.start_time
            
            if not path or seg_duration <= 0:
                broll_labels.append(None)
                continue
                
            if is_video:
                inputs.extend(["-i", path])
                v_idx = input_idx
                input_idx += 1
                # Trim, scale, and apply Ken Burns (zoompan) to video
                # zoompan works on images, so we extract frames from video. For simplicity, use scale + crop for video motion.
                filter_complex += (
                    f"[{v_idx}:v]trim=duration={seg_duration:.2f},setpts=PTS-STARTPTS,"
                    f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                    f"crop={self.width}:{self.height},"
                    f"setsar=1,format=yuva420p,"
                    f"fade=t=in:st=0:d=0.3:alpha=1,fade=t=out:st={max(0,seg_duration-0.3):.2f}:d=0.3:alpha=1"
                    f"[b{i}]"
                )
            else:
                # Image B-Roll with dynamic zoompan
                inputs.extend(["-loop", "1", "-i", path])
                v_idx = input_idx
                input_idx += 1
                # zoompan requires frame count. d=duration*fps
                frames = int(seg_duration * self.fps)
                filter_complex += (
                    f"[{v_idx}:v]scale={self.width*2}:{self.height*2}:force_original_aspect_ratio=increase,"
                    f"crop={self.width*2}:{self.height*2},"
                    f"zoompan=z='min(zoom+0.0015,1.15)':d={frames}:s={self.width}x{self.height}:fps={self.fps},"
                    f"setsar=1,format=yuva420p,"
                    f"fade=t=in:st=0:d=0.3:alpha=1,fade=t=out:st={max(0,seg_duration-0.3):.2f}:d=0.3:alpha=1"
                    f"[b{i}]"
                )
            broll_labels.append(f"b{i}")

        # 3. Overlay B-Roll onto Background
        prev_label = "bg"
        for i, b_label in enumerate(broll_labels):
            if not b_label:
                continue
            seg = audio_segments[i]
            # Apply slide-in transition for facts
            if seg.segment.segment_type in ["fact1", "fact2", "fact3"]:
                # Slide from right
                filter_complex += f"[{prev_label}][{b_label}]overlay=x='if(lt(t,{seg.start_time}),W+100,min(0,-(t-{seg.start_time})*1000))':y=0:eof_action=pass:enable='between(t,{seg.start_time},{seg.end_time})'[v{i}];"
            else:
                # Simple fade overlay
                filter_complex += f"[{prev_label}][{b_label}]overlay=0:0:eof_action=pass:enable='between(t,{seg.start_time},{seg.end_time})'[v{i}];"
            prev_label = f"v{i}"
            
        # 4. Pre-rendered Assets (Badge, CTA)
        inputs.extend(["-i", str(Config.FRAMES_DIR / "badge.png")])
        badge_idx = input_idx
        input_idx += 1
        filter_complex += f"[{prev_label}][{badge_idx}:v]overlay=40:40:format=auto[v_badge];"
        prev_label = "v_badge"
        
        inputs.extend(["-i", str(Config.FRAMES_DIR / "cta_bg.png")])
        cta_idx = input_idx
        input_idx += 1
        # CTA slides up at 85% of video
        cta_start = total_duration * 0.85
        cta_x = "(W-w)/2"
        cta_y = "if(lt(t,{cta_start}),H+100,min(H-h-100,H+100-(t-{cta_start})*800))"
        filter_complex += f"[{prev_label}][{cta_idx}:v]overlay={cta_x}:{cta_y}:format=auto:enable='gte(t,{cta_start})'[v_cta];"
        prev_label = "v_cta"

        # 5. Text Chunks (Karaoke Captions)
        for chunk in text_chunks:
            inputs.extend(["-i", chunk["path"]])
            t_idx = input_idx
            input_idx += 1
            
            # Calculate position (bottom third, slightly raised)
            y_pos = self.height - 400
            
            # Pop-in animation (scale from 0.8 to 1.0)
            # To avoid complex scale math in overlay, we just use a quick fade in/out
            filter_complex += f"[{prev_label}][{t_idx}:v]overlay=(W-w)/2:{y_pos}:format=auto:enable='between(t,{chunk['start']:.2f},{chunk['end']:.2f})'[v_t{t_idx}];"
            prev_label = f"v_t{t_idx}"

        # 6. Drawtext for Progress Bar (Directly on final video)
        # Drawtext is safe here because we use simple system font and no special chars
        font_path = Config.FONT_FALLBACK
        progress_color = "0x00FFFF"
        bg_color = "0x28283C"
        bar_y = self.height - 30
        bar_w = self.width - 80
        bar_x = 40
        
        # Progress bar background
        filter_complex += f"drawbox=x={bar_x}:y={bar_y}:w={bar_w}:h=8:color={bg_color}:t=fill[{prev_label}_pb1];"
        # Progress bar fill (width based on time)
        filter_complex += f"drawbox=x={bar_x}:y={bar_y}:w='{bar_w}*t/{total_duration}':h=8:color={progress_color}:t=fill[{prev_label}_pb2];"
        
        # Final CTA Text
        filter_complex += f"drawtext=fontfile='{font_path}':text='SUBSCRIBE KARO':fontcolor=white:fontsize=50:x=(w-text_w)/2:y=H-145:enable='gte(t,{cta_start})'[v_out];"

        # 7. Map Audio and Video
        filter_complex += f"[{audio_idx}:a]anull[a_out]"
        
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v_out]",
            "-map", "[a_out]",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "fast",
            "-r", str(self.fps),
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-shortest",
            "-movflags", "+faststart",
            str(Config.OUTPUT_DIR / "output_video.mp4")
        ]
        
        print("[VideoEngine] Executing FFmpeg render. This will take a few minutes...")
        rc, out, err = run_command(cmd, timeout=600)
        
        if rc != 0:
            print(f"[VideoEngine] FFmpeg failed (Code {rc}). Error:\n{err[-2000:]}")
            # Fallback: Simple concat without complex filters if something breaks
            return self._fallback_render(broll_assets, final_audio_path, total_duration)
            
        print("[VideoEngine] Render successful!")
        return str(Config.OUTPUT_DIR / "output_video.mp4")

    def _fallback_render(self, broll_assets: List[Tuple[Optional[str], bool]], audio_path: str, duration: float) -> str:
        """Absolute fallback if complex filtergraph fails."""
        print("[VideoEngine] Attempting fallback render...")
        output_path = str(Config.OUTPUT_DIR / "output_video.mp4")
        
        # Just use the first available B-roll as a static background
        bg_path = None
        for path, is_vid in broll_assets:
            if path:
                bg_path = path
                break
                
        if not bg_path:
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x0A0519:s={self.width}x{self.height}:d={duration}", "-i", audio_path, "-shortest", "-c:v", "libx264", "-c:a", "aac", output_path]
        else:
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", bg_path, "-i", audio_path, "-t", str(duration), "-vf", f"scale={self.width}:{self.height}", "-shortest", "-c:v", "libx264", "-c:a", "aac", output_path]
            
        rc, _, err = run_command(cmd, timeout=300)
        if rc == 0:
            return output_path
        raise RuntimeError(f"Fallback render failed: {err}")

# =============================================================================
# 7. TELEGRAM DELIVERY
# =============================================================================

class TelegramAgent:
    """Sends video and metadata via Telegram Bot."""
    
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
    def send_video(self, video_path: str, script: VideoScript, artifact_url: str, runtime_stats: str):
        """Send video with full metadata."""
        if not self.token or not self.chat_id:
            print("[TelegramAgent] Credentials missing. Skipping delivery.")
            return False
            
        print("[TelegramAgent] Preparing delivery...")
        caption = self._build_caption(script, artifact_url, runtime_stats)
        thumbnail_path = self._generate_thumbnail(script)
        
        file_size = os.path.getsize(video_path)
        max_size = 48 * 1024 * 1024 # Telegram bot limit
        
        try:
            if file_size <= max_size:
                print(f"[TelegramAgent] Uploading video ({file_size/1024/1024:.2f} MB)...")
                with open(video_path, "rb") as f:
                    files = {"video": f}
                    data = {
                        "chat_id": self.chat_id,
                        "caption": caption[:1024],
                        "parse_mode": "HTML",
                        "thumbnail": open(thumbnail_path, "rb") if thumbnail_path else None
                    }
                    resp = requests.post(f"{self.base_url}/sendVideo", data=data, files=files, timeout=300)
                    result = resp.json()
                    if result.get("ok"):
                        print("[TelegramAgent] Video sent successfully!")
                        return True
                    else:
                        print(f"[TelegramAgent] Send error: {result.get('description')}")
            else:
                print(f"[TelegramAgent] Video too large ({file_size/1024/1024:.2f}MB). Sending metadata only.")
                self._send_text(f"⚠️ Video too large for Telegram direct upload.\n\n{caption}")
                if thumbnail_path:
                    with open(thumbnail_path, "rb") as f:
                        files = {"photo": f}
                        data = {"chat_id": self.chat_id, "caption": "Thumbnail for large video", "parse_mode": "HTML"}
                        requests.post(f"{self.base_url}/sendPhoto", data=data, files=files, timeout=60)
        except Exception as e:
            print(f"[TelegramAgent] Delivery exception: {e}")
            
        return False
        
    def _build_caption(self, script: VideoScript, artifact_url: str, runtime_stats: str) -> str:
        """Build comprehensive caption."""
        tags_str = ", ".join(script.tags[:15])
        hashtags_str = " ".join(script.hashtags[:10])
        
        return f"""<b>🎬 {script.seo_title}</b>

<b>📋 Title:</b> {script.title}
<b>📁 Category:</b> {script.category}

<b>📝 Description:</b>
{script.description}

<b>🏷 Tags:</b>
{tags_str}

<b>#️⃣ Hashtags:</b>
{hashtags_str}

<b>⏱ Runtime Stats:</b>
{runtime_stats}

<b>📥 Artifact Link:</b> 
{artifact_url}

#AjeebologyShorts #YouTubeShorts"""

    def _send_text(self, text: str):
        """Send text message."""
        try:
            data = {"chat_id": self.chat_id, "text": text[:4096], "parse_mode": "HTML"}
            requests.post(f"{self.base_url}/sendMessage", data=data, timeout=30)
        except Exception as e:
            print(f"[TelegramAgent] Text send error: {e}")

    def _generate_thumbnail(self, script: VideoScript) -> Optional[str]:
        """Generate high-quality YouTube thumbnail (1280x720)."""
        try:
            img = Image.new("RGB", (1280, 720), Config.COLOR_BG_DARK)
            draw = ImageDraw.Draw(img)
            
            # Gradient background
            for y in range(720):
                ratio = y / 720
                r = int(10 + ratio * 30)
                g = int(5 + ratio * 20)
                b = int(25 + ratio * 50)
                draw.line([(0, y), (1280, y)], fill=(r, g, b))
                
            font_title = self._load_font(Config.FONT_TITLE, 110)
            font_body = self._load_font(Config.FONT_BODY, 50)
            
            # Wrap title
            words = script.title.split()
            lines = []
            current = []
            for word in words:
                test = " ".join(current + [word])
                bbox = font_title.getbbox(test)
                if bbox and bbox[2] > 1200:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            if current:
                lines.append(" ".join(current))
                
            # Draw title with glow
            y = 360 - len(lines) * 60
            for line in lines:
                for offset in range(8, 0, -2):
                    draw.text((640+offset, y), line, font=font_title, fill=(0, 200, 200), anchor="mm")
                    draw.text((640-offset, y), line, font=font_title, fill=(0, 200, 200), anchor="mm")
                draw.text((640, y), line, font=font_title, fill=(255, 255, 255), anchor="mm")
                y += 120
                
            draw.text((640, 650), "@AjeebologyShorts", font=font_body, fill=Config.COLOR_ACCENT, anchor="mm")
            
            path = str(Config.OUTPUT_DIR / "thumbnail.jpg")
            img.save(path, "JPEG", quality=90)
            return path
        except Exception as e:
            print(f"[TelegramAgent] Thumbnail error: {e}")
            return None
            
    def _load_font(self, path: str, size: int):
        try:
            return ImageFont.truetype(path, size)
        except:
            return ImageFont.truetype(Config.FONT_FALLBACK, size)


# =============================================================================
# 8. MAIN PIPELINE ORCHESTRATOR
# =============================================================================

class AjeebologyPipeline:
    """Main pipeline that orchestrates the entire automation."""
    
    def __init__(self):
        self.researcher = ResearchAgent()
        self.script_writer = ScriptAgent()
        self.voice_gen = VoiceAgent()
        self.asset_fetcher = AssetAgent()
        self.video_engine = VideoEngine()
        self.telegram = TelegramAgent()
        
    def run(self):
        """Execute full pipeline."""
        start_time = time.time()
        print("=" * 60)
        print("🚀 AJEEBOLOGY SHORTS - AUTOMATION PIPELINE STARTED")
        print("=" * 60)
        
        try:
            # 1. Setup
            print("\n[STEP 1/8] Setting up directories...")
            setup_directories()
            self.video_engine.pre_render_brand_assets()
            
            # 2. Research
            print("\n[STEP 2/8] Researching fresh facts...")
            research_data = self.researcher.fetch_fact()
            print(f"Category: {research_data['category']}")
            print(f"Topic: {research_data['title']}")
            
            # 3. Script
            print("\n[STEP 3/8] Generating Hinglish script...")
            script = self.script_writer.generate_script(research_data)
            print(f"Title: {script.title}")
            print(f"Segments: {len(script.segments)}")
            
            # 4. Voice
            print("\n[STEP 4/8] Generating voiceover...")
            audio_segments = self.voice_gen.generate_voice(script)
            print(f"Total voice duration: {script.total_duration_estimate:.2f}s")
            
            # 5. Assets
            print("\n[STEP 5/8] Fetching B-roll, motion backgrounds, and music...")
            broll_assets = []
            for i, seg in enumerate(script.segments):
                if seg.broll_prompt:
                    path, is_vid = self.asset_fetcher.fetch_broll(seg.broll_prompt, i)
                    broll_assets.append((path, is_vid))
                    print(f"  -> Seg {i}: {'Video' if is_vid else 'Image'} {'✓' if path else '✗'}")
                else:
                    broll_assets.append((None, False))
                    
            motion_bg = self.asset_fetcher.fetch_motion_background()
            print(f"  -> Motion BG: {'✓' if motion_bg else '✗'}")
            
            bg_music = self.asset_fetcher.fetch_background_music()
            print(f"  -> BG Music: {'✓' if bg_music else '✗'}")
            
            sfx_paths = {
                "whoosh": self.asset_fetcher.fetch_sfx("whoosh"),
                "pop": self.asset_fetcher.fetch_sfx("pop")
            }
            
            # 6. Audio Mixing & SFX
            print("\n[STEP 6/8] Mixing audio and injecting SFX...")
            mixed_audio = self.voice_gen.mix_audio(audio_segments, bg_music)
            final_audio = self.video_engine.inject_sfx(mixed_audio, sfx_paths, audio_segments)
            
            # 6.5 Whisper Caption Sync
            print("\n[STEP 6.5/8] Syncing word-level captions (Whisper)...")
            from faster_whisper import WhisperModel
            whisper_model = WhisperModel(Config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
            whisper_words = []
            
            # We need to transcribe the mixed audio to get global timings
            segments, _ = whisper_model.transcribe(final_audio, beam_size=1, word_timestamps=True, vad_filter=True)
            for seg in segments:
                for word in seg.words:
                    whisper_words.append(CaptionWord(
                        text=word.word.strip(),
                        start_time=word.start,
                        end_time=word.end
                    ))
            
            # Align to original script words
            all_script_words = []
            for seg in script.segments:
                all_script_words.extend(seg.text.split())
                
            caption_agent = CaptionSyncAgent.__new__(CaptionSyncAgent) # Init without reloading model
            aligned_words = caption_agent.align_to_script(all_script_words, whisper_words)
            text_chunks = self.video_engine.pre_render_text_chunks(aligned_words)
            
            # 7. Render Video
            print("\n[STEP 7/8] Rendering professional video (FFmpeg)...")
            video_path = self.video_engine.render_video(
                script, audio_segments, broll_assets, motion_bg, text_chunks, final_audio
            )
            file_size = os.path.getsize(video_path) / (1024 * 1024)
            print(f"Video rendered: {video_path} ({file_size:.2f} MB)")
            
            # 8. Deliver
            print("\n[STEP 8/8] Sending to Telegram...")
            runtime_secs = time.time() - start_time
            runtime_stats = f"Total Time: {int(runtime_secs//60)}m {int(runtime_secs%60)}s\nFile Size: {file_size:.2f} MB"
            
            run_id = Config.GITHUB_RUN_ID
            repo = Config.GITHUB_REPOSITORY
            artifact_url = f"https://github.com/{repo}/actions/runs/{run_id}" if run_id != "local" else "Local Run"
            
            self.telegram.send_video(video_path, script, artifact_url, runtime_stats)
            
            print("\n" + "=" * 60)
            print("✅ PIPELINE COMPLETED SUCCESSFULLY!")
            print(f"⏱ Total Runtime: {int(runtime_secs//60)}m {int(runtime_secs%60)}s")
            print("=" * 60)
            
            return True
            
        except Exception as e:
            print(f"\n❌ PIPELINE FAILED: {e}")
            traceback.print_exc()
            return False
        finally:
            # Aggressive cleanup to protect GitHub runner disk space
            print("\n[CLEANUP] Removing temporary frames and audio...")
            cleanup_path(Config.FRAMES_DIR)
            cleanup_path(Config.AUDIO_DIR)
            cleanup_path(Config.TMP_DIR)

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pipeline = AjeebologyPipeline()
    success = pipeline.run()
    sys.exit(0 if success else 1)
