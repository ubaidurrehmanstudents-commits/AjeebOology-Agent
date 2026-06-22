#!/usr/bin/env python3
"""
Ajeebology Shorts - Professional YouTube Shorts Automation
Version: 2.0 (Production Ready)
"""

import os
import sys
import json
import re
import math
import random
import tempfile
import subprocess
import shutil
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote_plus
import asyncio

import requests
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import edge_tts
from pydub import AudioSegment
from pydub.silence import detect_nonsilent


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Centralized configuration for the pipeline."""
    
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24
    TARGET_DURATION = 58
    MAX_DURATION = 60
    
    VOICE_MODEL = "hi-IN-MadhurNeural"
    AUDIO_SAMPLE_RATE = 44100  
    VOICE_RATE = "+15%"
    
    FONT_SIZE_TITLE = 72
    FONT_SIZE_BODY = 56
    FONT_SIZE_SMALL = 40
    FONT_SIZE_CAPTION = 64
    
    COLOR_BG_PRIMARY = (10, 5, 25)
    COLOR_BG_SECONDARY = (30, 15, 60)
    COLOR_ACCENT = (0, 255, 255)
    COLOR_ACCENT_2 = (255, 0, 128)
    COLOR_TEXT = (255, 255, 255)
    COLOR_HIGHLIGHT = (255, 255, 0)
    
    BASE_DIR = Path("/tmp/ajeebology")
    FRAMES_DIR = BASE_DIR / "frames"
    AUDIO_DIR = BASE_DIR / "audio"
    ASSETS_DIR = BASE_DIR / "assets"
    OUTPUT_DIR = BASE_DIR / "output"
    SUBTITLES_DIR = BASE_DIR / "subtitles"
    
    POLLINATIONS_ENABLED = True
    UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    
    SILENCE_THRESHOLD = -40
    MIN_GAP_DURATION = 0.05
    BG_MUSIC_VOLUME = 0.12


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ScriptSegment:
    text: str
    segment_type: str
    emphasis_words: List[str] = field(default_factory=list)
    broll_prompt: str = ""
    duration_estimate: float = 0.0


@dataclass
class VideoScript:
    title: str
    category: str
    seo_title: str
    description: str
    tags: List[str]
    hashtags: List[str]    segments: List[ScriptSegment]
    total_duration_estimate: float = 0.0


@dataclass
class AudioSegment:
    segment: ScriptSegment
    audio_path: str
    duration: float
    start_time: float
    end_time: float
    word_boundaries: List[Dict] = field(default_factory=list)
# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def setup_directories():
    """Create all necessary directories."""
    for d in [Config.FRAMES_DIR, Config.AUDIO_DIR, Config.ASSETS_DIR, 
              Config.OUTPUT_DIR, Config.SUBTITLES_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    print("Directories initialized")


def run_command(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """Run shell command with timeout."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"


def get_audio_duration(path: str) -> float:
    """Get precise audio duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    rc, out, _ = run_command(cmd)
    if rc == 0 and out.strip():
        return float(out.strip())
    return 0.0


def download_file(url: str, dest: str, timeout: int = 30) -> bool:
    """Download file with retry logic."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200:
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)
    return False


def safe_filename(text: str) -> str:
    """Create safe filename from text."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)[:50]


def estimate_speech_duration(text: str) -> float:
    """Estimate speech duration in seconds."""
    clean_text = re.sub(r'[^\w\s]', '', text)
    return max(2.0, len(clean_text) / 5.2)
# =============================================================================
# 1. RESEARCH MODULE (Tavily API)
# =============================================================================

class ResearchAgent:
    """Fetches fresh, trending facts using Tavily Search API."""
    
    CATEGORIES = ["psychology", "space", "weird_facts"]
    
    QUERIES = {
        "psychology": [
            "mind blowing psychology facts human behavior 2026",
            "psychology tricks brain facts that will change your life",
            "interesting psychological phenomena daily life examples"
        ],
        "space": [
            "amazing space facts universe secrets 2026",
            "recent space discoveries mind blowing",
            "astronomy facts that will blow your mind"
        ],
        "weird_facts": [
            "unbelievable facts about world strange but true 2026",
            "weird facts that sound fake but are scientifically proven",
            "amazing facts about earth animals humans nature"
        ]
    }
    
    def __init__(self):
        self.api_key = Config.TAVILY_API_KEY
        self.base_url = "https://api.tavily.com/search"
    
    def fetch_fact(self, category: Optional[str] = None) -> Dict:
        """Fetch a fresh fact topic from the internet."""
        
        if os.environ.get("CATEGORY_OVERRIDE"):
            category = os.environ.get("CATEGORY_OVERRIDE")
        
        if not category or category not in self.CATEGORIES:
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
        
        try:
            print(f"Searching: {query}")
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=30)
            data = resp.json()
            
            results = data.get("results", [])
            if results:
                best = max(results, key=lambda x: len(x.get("content", "")))
                
                fact_data = {
                    "category": category,
                    "title": best.get("title", ""),
                    "content": best.get("content", ""),
                    "url": best.get("url", ""),
                    "query": query
                }
                print(f"Found: {fact_data['title'][:60]}...")
                return fact_data
                
        except Exception as e:
            print(f"Research API error: {e}")
        
        # Fallback facts
        fallbacks = {
            "psychology": {
                "title": "Psychology Facts That Will Blow Your Mind",
                "content": "Your brain can process images in just 13 milliseconds. The human mind is capable of creating false memories that feel completely real. Smiling can actually make you feel happier due to the facial feedback effect.",
                "category": "psychology"
            },
            "space": {
                "title": "Space Secrets You Never Knew",
                "content": "A day on Venus is longer than its year. Neutron stars can spin 600 times per second. There are more trees on Earth than stars in the Milky Way galaxy.",
                "category": "space"
            },
            "weird_facts": {
                "title": "Weird Facts That Sound Fake",
                "content": "Honey never spoils - archaeologists found 3000-year-old honey that was still edible. Wombat poop is cube-shaped. Bananas are berries but strawberries are not.",
                "category": "weird_facts"
            }
        }
        
        cat = category or random.choice(self.CATEGORIES)
        print(f"Using fallback fact for {cat}")
        return fallbacks[cat]
        # =============================================================================
# 2. SCRIPT GENERATION (Groq/LLaMA)
# =============================================================================

class ScriptAgent:
    """Generates viral Hinglish scripts optimized for retention."""

    SYSTEM_PROMPT = """You are a professional YouTube Shorts scriptwriter for "Ajeebology Shorts".
YOUR TASK: Create engaging, viral scripts in HINGLISH (Roman Hindi + English mix).
CRITICAL RULES:
1. LANGUAGE: Write in Hinglish - conversational Roman Hindi mixed with English words.
2. DURATION: Target 55-60 seconds when spoken.
3. HOOK: First 2 seconds MUST grab attention.
4. EMPHASIS: Mark important words with [brackets] like this: [shocking], [90%].
5. TONE: Conversational, energetic.
6. LOOP: Make the outro flow naturally back into the hook.

OUTPUT FORMAT: Return ONLY valid JSON with this exact structure:
{
    "title": "Catchy Hinglish title",
    "category": "psychology|space|weird_facts",
    "seo_title": "English SEO optimized title",
    "description": "English description with keywords",
    "tags": ["tag1", "tag2"],
    "hashtags": ["#tag1", "#tag2"],
    "segments": [
        {"type": "hook", "text": "Hinglish text with [emphasis]", "broll_prompt": "English description"},
        {"type": "fact1", "text": "...", "broll_prompt": "..."},
        {"type": "fact2", "text": "...", "broll_prompt": "..."},
        {"type": "fact3", "text": "...", "broll_prompt": "..."},
        {"type": "outro", "text": "...", "broll_prompt": "..."}
    ]
}"""

    def __init__(self):
        self.api_key = Config.GROQ_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def generate_script(self, research_data: Dict) -> VideoScript:
        """Generate complete video script from research data."""
        user_prompt = f"Create a viral YouTube Shorts script based on this research:\nCATEGORY: {research_data['category']}\nTOPIC: {research_data['title']}\nCONTENT: {research_data['content']}"

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
            "max_tokens": 2000,
            "response_format": {"type": "json_object"}
        }

        try:
            print("Generating script with Groq LLaMA...")
            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=60)
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            script_data = json.loads(content)
            script = self._parse_script(script_data)
            print(f"Script generated: {script.title}")
            return script
        except Exception as e:
            print(f"Script generation error: {e}")
            return self._fallback_script(research_data)

    def _parse_script(self, data: Dict) -> VideoScript:
        """Parse JSON response into VideoScript object."""
        segments = []
        for seg_data in data.get("segments", []):
            text = seg_data.get("text", "")
            emphasis = re.findall(r'\[(.*?)\]', text)
            clean_text = re.sub(r'\[(.*?)\]', r'\1', text)
            segments.append(ScriptSegment(
                text=clean_text,
                segment_type=seg_data.get("type", "fact"),
                emphasis_words=emphasis,
                broll_prompt=seg_data.get("broll_prompt", ""),
                duration_estimate=estimate_speech_duration(clean_text)
            ))
        total_duration = sum(seg.duration_estimate for seg in segments)
        return VideoScript(
            title=data.get("title", "Amazing Facts"),
            category=data.get("category", "weird_facts"),
            seo_title=data.get("seo_title", "Mind Blowing Facts"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            hashtags=data.get("hashtags", []),
            segments=segments,
            total_duration_estimate=total_duration
        )
        def _fallback_script(self, research: Dict) -> VideoScript:
        """Generate high-quality fallback script if API fails."""
        category = research.get("category", "weird_facts")

        templates = {
            "psychology": {
                "title": "Psychology Facts Jo Aapka Dimag Ghuma Denge",
                "seo_title": "Psychology Facts That Will Blow Your Mind 2026",
                "description": "Amazing psychology facts about human behavior.",
                "tags": ["psychology", "facts", "brain", "mind"],
                "hashtags": ["#psychology", "#facts", "#brain", "#shorts"],
                "segments": [
                    ScriptSegment("Kya aap jaante hain aapka brain har [13 milliseconds] mein ek image process kar sakta hai?", "hook", ["13 milliseconds"], "human brain", 4.0),
                    ScriptSegment("Psychology ke ek experiment mein researchers ne dekha ki [false memories] create karna kitna aasan hai.", "fact1", ["false memories"], "psychology experiment", 12.0),
                    ScriptSegment("Agar aap forcefully [smile] karte hain, toh aapka brain automatically [happy hormones] release kar deta hai.", "fact2", ["smile", "happy hormones"], "person smiling", 12.0),
                    ScriptSegment("Aur ek study ke mutabik, aapke decisions ka [90%] aapka subconscious mind control karta hai.", "fact3", ["90%", "subconscious mind"], "subconscious mind", 12.0),
                    ScriptSegment("Agar ye facts pasand aaye toh [subscribe] karo aur comments mein batao!", "outro", ["subscribe"], "youtube subscribe", 8.0)
                ]
            },
            "space": {
                "title": "Space Ke Raaz Jo Koi Nahi Jaanta",
                "seo_title": "Space Secrets You Never Knew 2026",
                "description": "Mind-blowing space facts about universe.",
                "tags": ["space", "universe", "astronomy", "facts"],
                "hashtags": ["#space", "#universe", "#facts", "#shorts"],
                "segments": [
                    ScriptSegment("Venus par ek din [243 Earth days] ka hota hai, lekin saal sirf [225 days] ka!", "hook", ["243 Earth days", "225 days"], "venus planet", 10.0),
                    ScriptSegment("Neutron stars itni tezi se spin karti hain ki ek second mein [600 baar] ghoom jaati hain.", "fact1", ["600 baar"], "neutron star", 12.0),
                    ScriptSegment("Aur Earth par trees [Milky Way] ke stars se zyada hain!", "fact2", ["Milky Way"], "milky way galaxy", 12.0),
                    ScriptSegment("Space mein ek [giant cloud] hai jo alcohol se bana hai, jiski value [1000 trillion dollars] hai.", "fact3", ["giant cloud", "1000 trillion dollars"], "space nebula", 12.0),
                    ScriptSegment("Aur bhi amazing space facts ke liye [follow] karo Ajeebology Shorts ko!", "outro", ["follow"], "space astronaut", 6.0)
                ]
            },
            "weird_facts": {
                "title": "Weird Facts Jo Sach Lagte Hi Nahi",
                "seo_title": "Weird Facts That Sound Fake But Are True 2026",
                "description": "Unbelievable weird facts about nature.",
                "tags": ["weird facts", "strange facts", "amazing facts"],
                "hashtags": ["#weirdfacts", "#amazing", "#nature", "#shorts"],
                "segments": [
                    ScriptSegment("Honey kabhi [spoil] nahi hota! Archaeologists ne [3000 saal] purana honey khaya tha!", "hook", ["spoil", "3000 saal"], "ancient honey", 9.0),
                    ScriptSegment("Wombat ka poop [cube-shaped] hota hai - nature ka sabse weird phenomenon!", "fact1", ["cube-shaped"], "wombat animal", 12.0),
                    ScriptSegment("Banana technically ek [berry] hai, lekin strawberry nahi!", "fact2", ["berry"], "banana fruit", 12.0),
                    ScriptSegment("Octopus ke paas [teen dil] hain aur unka blood [blue] hota hai!", "fact3", ["teen dil", "blue"], "octopus underwater", 12.0),
                    ScriptSegment("Aise hi [mind-blowing] facts ke liye channel ko subscribe karo!", "outro", ["mind-blowing"], "shocked reaction", 6.0)
                ]
            }
        }

        template = templates.get(category, templates["weird_facts"])
        segments = template["segments"]
        total_duration = sum(seg.duration_estimate for seg in segments)

        return VideoScript(
            title=template["title"],
            category=category,
            seo_title=template["seo_title"],
            description=template["description"],
            tags=template["tags"],
            hashtags=template["hashtags"],
            segments=segments,
            total_duration_estimate=total_duration
        )
        # =============================================================================
# 3. VOICE GENERATION (edge-tts with Word Boundaries & Silence Trimming)
# =============================================================================

class VoiceAgent:
    """Generates natural, pause-free voiceover using edge-tts Python API."""

    def __init__(self):
        self.voice = Config.VOICE_MODEL
        self.rate = Config.VOICE_RATE

    def generate_voice(self, script: VideoScript) -> List[AudioSegment]:
        """Generate voice for each segment and capture exact word timings."""
        audio_segments = []
        current_time = 0.0

        print("Generating voiceover with edge-tts...")

        for i, segment in enumerate(script.segments):
            tts_text = self._clean_for_tts(segment.text)
            output_path = str(Config.AUDIO_DIR / f"segment_{i:02d}.mp3")

            # Generate audio and get word boundaries
            word_boundaries = asyncio.run(self._generate_with_edge_tts(tts_text, output_path))

            if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
                print(f"TTS failed for segment {i}, creating silent fallback.")
                duration = estimate_speech_duration(tts_text)
                self._create_silent_audio(output_path, duration)
                word_boundaries = []

            # Trim trailing silence to make it punchy and natural
            self._trim_silence(output_path)

            duration = get_audio_duration(output_path)

            audio_segments.append(AudioSegment(
                segment=segment,
                audio_path=output_path,
                duration=duration,
                start_time=current_time,
                end_time=current_time + duration,
                word_boundaries=word_boundaries
            ))

            # Add a tiny, natural 50ms gap between segments
            current_time += duration + Config.MIN_GAP_DURATION

        script.total_duration_estimate = current_time
        print(f"Voiceover generated. Total duration: {current_time:.2f}s")        return audio_segments

    async def _generate_with_edge_tts(self, text: str, output_path: str) -> List[Dict]:
        """Generate audio using edge-tts API and capture word boundaries."""
        word_boundaries = []
        try:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            with open(output_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        word_boundaries.append({
                            "text": chunk["text"],
                            "offset": chunk["offset"] / 10000,
                            "duration": chunk["duration"] / 10000,
                            "start_ms": (chunk["offset"] / 10000)
                        })
        except Exception as e:
            print(f"edge-tts API error: {e}")
        return word_boundaries

    def _trim_silence(self, audio_path: str):
        """Aggressively trim silence from the end of the audio file."""
        try:
            audio = AudioSegment.from_mp3(audio_path)
            nonsilent = detect_nonsilent(audio, min_silence_len=50, silence_thresh=-40)
            if nonsilent:
                start = max(0, nonsilent[0][0] - 20)
                end = min(len(audio), nonsilent[-1][1] + 50)
                trimmed = audio[start:end]
                trimmed.export(audio_path, format="mp3", bitrate="192k")
        except Exception as e:
            print(f"Silence trimming error: {e}")

    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS processing."""
        text = re.sub(r'[!]{2,}', '!', text)
        text = re.sub(r'[?]{2,}', '?', text)
        return text.strip()

    def _create_silent_audio(self, path: str, duration: float):
        """Create silent audio as fallback."""
        silence = AudioSegment.silent(duration=int(duration * 1000))
        silence.export(path, format="mp3")

    def mix_audio(self, audio_segments: List[AudioSegment], bg_music_path: Optional[str]) -> str:
        """Mix all voice segments and background music into final audio."""
        print("Mixing audio tracks...")
        # 1. Concatenate all voice segments with tiny gaps
        combined_voice = AudioSegment.silent(duration=0)
        for seg in audio_segments:
            voice_clip = AudioSegment.from_mp3(seg.audio_path)
            combined_voice += voice_clip
            combined_voice += AudioSegment.silent(duration=int(Config.MIN_GAP_DURATION * 1000))

        voice_path = str(Config.AUDIO_DIR / "combined_voice.mp3")
        combined_voice.export(voice_path, format="mp3", bitrate="192k")

        # 2. Mix with background music using FFmpeg
        final_path = str(Config.AUDIO_DIR / "final_audio.mp3")

        if bg_music_path and os.path.exists(bg_music_path):
            cmd = [
                "ffmpeg", "-y",
                "-i", voice_path,
                "-stream_loop", "-1", "-i", bg_music_path,
                "-filter_complex",
                f"[1:a]volume={Config.BG_MUSIC_VOLUME}[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "[aout]",
                "-acodec", "libmp3lame", "-b:a", "192k",
                final_path
            ]
            rc, _, err = run_command(cmd, timeout=120)
            if rc != 0:
                print(f"Audio ducking failed, falling back to simple mix: {err}")
                combined_voice += AudioSegment.from_mp3(bg_music_path).apply_gain(-15)
                combined_voice.export(final_path, format="mp3", bitrate="192k")
        else:
            shutil.copy(voice_path, final_path)

        print(f"Final audio mixed: {final_path}")
        return final_path
        # =============================================================================
# 4. B-ROLL & ASSETS FETCHING
# =============================================================================

class AssetAgent:
    """Downloads high-quality B-roll images and background music."""
    
    def __init__(self):
        self.assets = []
    
    def fetch_broll(self, prompt: str, index: int) -> Optional[str]:
        """Fetch B-roll image for a segment."""
        safe_prompt = safe_filename(prompt)[:30]
        dest_path = str(Config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.jpg")
        
        # Try Unsplash first (high quality, requires API key)
        if Config.UNSPLASH_ACCESS_KEY and self._try_unsplash(prompt, dest_path):
            return dest_path
        
        # Fallback to Pollinations AI (Free, no API key)
        if Config.POLLINATIONS_ENABLED and self._try_pollinations(prompt, dest_path):
            return dest_path
            
        return None
    
    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        """Search Unsplash for images."""
        try:
            url = f"https://api.unsplash.com/search/photos?query={quote_plus(prompt)}&per_page=3&orientation=portrait"
            headers = {"Authorization": f"Client-ID {Config.UNSPLASH_ACCESS_KEY}"}
            resp = requests.get(url, headers=headers, timeout=15)
            data = resp.json()
            results = data.get("results", [])
            if results:
                img_url = results[0]["urls"]["regular"]
                return download_file(img_url, dest)
        except Exception as e:
            print(f"Unsplash error: {e}")
        return False
    
    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        """Generate image using Pollinations.ai (free, AI-generated)."""
        try:
            enhanced = f"cinematic lighting, highly detailed, 8k resolution, vertical aspect ratio, {prompt}"
            encoded = quote_plus(enhanced)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&seed={random.randint(1, 100000)}&nologo=true"
            
            print(f"  Generating AI B-roll: {prompt[:40]}...")
            success = download_file(url, dest, timeout=60)
            if success and os.path.getsize(dest) > 5000:
                return True
        except Exception as e:
            print(f"Pollinations error: {e}")
        return False
    
    def fetch_background_music(self) -> Optional[str]:
        """Download royalty-free background music."""
        music_urls = [
            "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=lofi-study-112191.mp3",
            "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3?filename=chill-lofi-music-2-110791.mp3"
        ]
        
        dest = str(Config.ASSETS_DIR / "bg_music.mp3")
        print("Downloading background music...")
        for url in music_urls:
            if download_file(url, dest, timeout=30):
                return dest
                
        print("Music download failed. Creating silent fallback.")
        silence = AudioSegment.silent(duration=60000)
        silence.export(dest, format="mp3")
        return dest
        # =============================================================================
# 5. PROFESSIONAL VIDEO RENDERING ENGINE (FFmpeg + ASS Subtitles)
# =============================================================================

class VideoEngine:
    """Renders video fast using FFmpeg filters and dynamic karaoke captions."""
    
    def __init__(self):
        self.width = Config.WIDTH
        self.height = Config.HEIGHT
        self.fps = Config.FPS
        
    def render_video(self, script: VideoScript, audio_segments: List[AudioSegment],
                     broll_paths: List[Optional[str]], final_audio_path: str) -> str:
        """Main video rendering function using FFmpeg."""
        total_duration = get_audio_duration(final_audio_path)
        print(f"Starting FFmpeg render ({total_duration:.2f}s)...")
        
        # 1. Generate Dynamic ASS Subtitles
        ass_path = self._generate_ass_subtitles(audio_segments, total_duration)
        
        # 2. Prepare B-roll images
        processed_brolls = self._prepare_brolls(broll_paths, len(audio_segments), total_duration)
        
        output_path = str(Config.OUTPUT_DIR / "output_video.mp4")
        
        # Create a dark gradient background video
        bg_video_path = str(Config.ASSETS_DIR / "bg_video.mp4")
        bg_cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", 
            f"color=c=0x0A0519:s={self.width}x{self.height}:d={total_duration}:r={self.fps}",
            bg_video_path
        ]
        run_command(bg_cmd, timeout=60)
        
        # Build the main FFmpeg command
        cmd = ["ffmpeg", "-y", "-i", bg_video_path]
        
        # Add B-roll images as inputs
        for i, broll in enumerate(processed_brolls):
            if broll and os.path.exists(broll):
                cmd.extend(["-loop", "1", "-t", str(audio_segments[i].duration + 0.5), "-i", broll])
        
        # Add audio
        cmd.extend(["-i", final_audio_path])
        
        # Add subtitles filter
        # Note: We escape colons and single quotes for FFmpeg filter syntax
        safe_ass_path = ass_path.replace(":", r"\:").replace("'", r"\'")
        cmd.extend(["-vf", f"ass={safe_ass_path}"])        
        # Output settings
        cmd.extend([
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            output_path
        ])
        
        print("Rendering video with FFmpeg...")
        rc, out, err = run_command(cmd, timeout=300)
        
        if rc != 0:
            print(f"Complex render failed, falling back to simple render: {err[:200]}")
            cmd_fallback = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=0x0A0519:s={self.width}x{self.height}:d={total_duration}:r={self.fps}",
                "-i", final_audio_path,
                "-vf", f"ass={safe_ass_path}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-shortest", output_path
            ]
            run_command(cmd_fallback, timeout=300)
            
        print(f"Video rendered successfully: {output_path}")
        return output_path

    def _generate_ass_subtitles(self, audio_segments: List[AudioSegment], total_duration: float) -> str:
        """Generate an ASS subtitle file for dynamic, word-by-word highlighting."""
        ass_path = str(Config.SUBTITLES_DIR / "captions.ass")
        
        ass_content = """[Script Info]
Title: Ajeebology Shorts Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,70,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,30,30,250,1
Style: Hook,Arial Black,85,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,30,30,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        current_time_ms = 0.0
                for seg in audio_segments:
            style = "Hook" if seg.segment.segment_type == "hook" else "Default"
            seg_duration_ms = seg.duration * 1000
            
            if seg.word_boundaries and len(seg.word_boundaries) > 1:
                # Word-by-word karaoke effect using \k tags
                dialogue_text = ""
                for i, wb in enumerate(seg.word_boundaries):
                    word = wb["text"]
                    duration_cs = int(wb["duration"] / 10) 
                    if duration_cs < 5: 
                        duration_cs = 5 
                    
                    dialogue_text += f"{{\\k{duration_cs}}}{word} "
                
                start_time = self._ms_to_ass_time(current_time_ms)
                end_time = self._ms_to_ass_time(current_time_ms + seg_duration_ms)
                
                ass_content += f"Dialogue: 0,{start_time},{end_time},{style},,0,0,0,,{dialogue_text.strip()}\n"
            else:
                start_time = self._ms_to_ass_time(current_time_ms)
                end_time = self._ms_to_ass_time(current_time_ms + seg_duration_ms)
                clean_text = seg.segment.text.replace("\n", "\\N")
                ass_content += f"Dialogue: 0,{start_time},{end_time},{style},,0,0,0,,{clean_text}\n"
                
            current_time_ms += seg_duration_ms + (Config.MIN_GAP_DURATION * 1000)
            
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
            
        print(f"Dynamic ASS subtitles generated: {ass_path}")
        return ass_path

    def _ms_to_ass_time(self, ms: float) -> str:
        """Convert milliseconds to ASS time format (H:MM:SS.CC)."""
        h = int(ms // 3600000)
        m = int((ms % 3600000) // 60000)
        s = int((ms % 60000) // 1000)
        cs = int((ms % 1000) // 10)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    def _prepare_brolls(self, broll_paths: List[Optional[str]], num_segments: int, total_duration: float) -> List[Optional[str]]:
        """Ensure all B-roll images are exactly 1080x1920."""
        processed = []
        for i, path in enumerate(broll_paths):
            if path and os.path.exists(path):
                try:
                    img = Image.open(path).convert("RGB")
                    img_ratio = img.width / img.height
                    target_ratio = self.width / self.height
                    
                    if img_ratio > target_ratio:
                        new_width = int(img.height * target_ratio)
                        left = (img.width - new_width) // 2
                        img = img.crop((left, 0, left + new_width, img.height))
                    else:
                        new_height = int(img.width / target_ratio)
                        top = (img.height - new_height) // 2
                        img = img.crop((0, top, img.width, top + new_height))
                        
                    img = img.resize((self.width, self.height), Image.Resampling.LANCZOS)
                    
                    out_path = str(Config.ASSETS_DIR / f"broll_processed_{i}.jpg")
                    img.save(out_path, "JPEG", quality=90)
                    processed.append(out_path)
                except Exception as e:
                    print(f"B-roll processing failed for {i}: {e}")
                    processed.append(None)
            else:
                processed.append(None)
        return processed
# =============================================================================
# 6. TELEGRAM DELIVERY & THUMBNAIL
# =============================================================================

class TelegramAgent:
    """Sends the final video, thumbnail, and metadata to Telegram."""
    
    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
    
    def send_video(self, video_path: str, script: VideoScript, artifact_url: str = ""):
        """Send video with full metadata to Telegram."""
        if not self.token or not self.chat_id:
            print("Telegram credentials not configured. Skipping delivery.")
            return False
        
        print("Sending video to Telegram...")
        caption = self._build_caption(script, artifact_url)
        thumbnail_path = self._generate_thumbnail(script)
        
        file_size = os.path.getsize(video_path)
        max_size = 48 * 1024 * 1024 
        
        try:
            if file_size <= max_size:
                with open(video_path, "rb") as f:
                    files = {"video": f}
                    if thumbnail_path and os.path.exists(thumbnail_path):
                        with open(thumbnail_path, "rb") as tf:
                            files["thumbnail"] = tf
                            data = {
                                "chat_id": self.chat_id,
                                "caption": caption[:1024],
                                "parse_mode": "HTML",
                                "supports_streaming": "1"
                            }
                            resp = requests.post(f"{self.base_url}/sendVideo", data=data, files=files, timeout=180)
                    else:
                        data = {
                            "chat_id": self.chat_id,
                            "caption": caption[:1024],
                            "parse_mode": "HTML",
                            "supports_streaming": "1"
                        }
                        resp = requests.post(f"{self.base_url}/sendVideo", data=data, files=files, timeout=180)
                        
                    result = resp.json()
                    if result.get("ok"):                        print("Video sent successfully to Telegram!")
                        return True
                    else:
                        print(f"Telegram API error: {result}")
            else:
                print(f"Video too large ({file_size / 1024 / 1024:.1f}MB). Sending metadata only.")
                self._send_text(f"<b>Video too large for Telegram.</b>\n\n{caption}")
                
        except Exception as e:
            print(f"Telegram send error: {e}")
            
        return False
    
    def _build_caption(self, script: VideoScript, artifact_url: str) -> str:
        """Build a comprehensive, SEO-friendly caption."""
        tags_str = ", ".join(script.tags[:10])
        hashtags_str = " ".join(script.hashtags[:5])
        
        caption = f"""<b>{script.seo_title}</b>

<b>Title:</b> {script.title}
<b>Category:</b> {script.category}

<b>Description:</b>
{script.description}

<b>Tags:</b> {tags_str}
<b>Hashtags:</b> {hashtags_str}

<b>Upload Time:</b> 5:00 PM PKT Daily
<b>Download:</b> <a href='{artifact_url}'>Click Here</a>

#AjeebologyShorts #YouTubeShorts #DailyFacts"""
        return caption
    
    def _send_text(self, text: str):
        """Send a simple text message."""
        try:
            data = {"chat_id": self.chat_id, "text": text[:4096], "parse_mode": "HTML"}
            requests.post(f"{self.base_url}/sendMessage", data=data, timeout=30)
        except Exception as e:
            print(f"Text send error: {e}")
    
    def _generate_thumbnail(self, script: VideoScript) -> Optional[str]:
        """Generate a professional YouTube thumbnail (1280x720)."""
        try:
            img = Image.new("RGB", (1280, 720), Config.COLOR_BG_PRIMARY)
            draw = ImageDraw.Draw(img)
            
            for y in range(720):                ratio = y / 720
                r = int(10 + ratio * 30)
                g = int(5 + ratio * 20)
                b = int(25 + ratio * 50)
                draw.line([(0, y), (1280, y)], fill=(r, g, b))
                
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            ]
            font = ImageFont.load_default()
            for p in font_paths:
                try:
                    font = ImageFont.truetype(p, 70)
                    break
                except:
                    continue
                    
            words = script.seo_title.split()
            lines = []
            current = []
            for word in words:
                test = " ".join(current + [word])
                bbox = font.getbbox(test)
                if bbox and bbox[2] > 1100:
                    lines.append(" ".join(current))
                    current = [word]
                else:
                    current.append(word)
            if current:
                lines.append(" ".join(current))
                
            y = 360 - len(lines) * 45
            for line in lines:
                draw.text((642, y+2), line, font=font, fill=(0, 0, 0), anchor="mm")
                draw.text((640, y), line, font=font, fill=Config.COLOR_TEXT, anchor="mm")
                y += 90
                
            font_small = ImageFont.load_default()
            for p in font_paths:
                try:
                    font_small = ImageFont.truetype(p, 35)
                    break
                except:
                    continue
            draw.text((640, 650), "@AjeebologyShorts", font=font_small, fill=Config.COLOR_ACCENT, anchor="mm")
            
            path = str(Config.OUTPUT_DIR / "thumbnail.jpg")
            img.save(path, "JPEG", quality=95)
            return path        except Exception as e:
            print(f"Thumbnail generation error: {e}")
            return None
        # =============================================================================
# 7. MAIN PIPELINE ORCHESTRATOR
# =============================================================================

class AjeebologyPipeline:
    """Main pipeline that orchestrates the entire automation process."""

    def __init__(self):
        self.researcher = ResearchAgent()
        self.script_writer = ScriptAgent()
        self.voice_gen = VoiceAgent()
        self.asset_fetcher = AssetAgent()
        self.video_engine = VideoEngine()
        self.telegram = TelegramAgent()

    def run(self):
        """Execute the full automation pipeline."""
        print("=" * 60)
        print("AJEEBOLOGY SHORTS - PROFESSIONAL AUTOMATION PIPELINE")
        print("=" * 60)

        try:
            # Step 1: Setup
            print("\n[1/7] Setting up directories...")
            setup_directories()

            # Step 2: Research
            print("\n[2/7] Researching fresh, viral facts...")
            research_data = self.researcher.fetch_fact()

            # Step 3: Generate Script
            print("\n[3/7] Generating Hinglish script with Groq...")
            script = self.script_writer.generate_script(research_data)

            # Step 4: Generate Voice (Pause-Free)
            print("\n[4/7] Generating natural, pause-free voiceover...")
            audio_segments = self.voice_gen.generate_voice(script)

            # Step 5: Fetch Assets
            print("\n[5/7] Fetching B-roll images and background music...")
            broll_paths = []
            for i, seg in enumerate(script.segments):
                if seg.broll_prompt:
                    path = self.asset_fetcher.fetch_broll(seg.broll_prompt, i)
                    broll_paths.append(path)
                else:
                    broll_paths.append(None)

            bg_music = self.asset_fetcher.fetch_background_music()

            # Step 6: Mix Audio & Render Video
            print("\n[6/7] Mixing audio and rendering video...")
            final_audio = self.voice_gen.mix_audio(audio_segments, bg_music)

            video_path = self.video_engine.render_video(
                script, audio_segments, broll_paths, final_audio
            )

            file_size = os.path.getsize(video_path)
            print(f"Video rendered! Size: {file_size / 1024 / 1024:.2f} MB")

            # Step 7: Deliver to Telegram
            print("\n[7/7] Delivering to Telegram...")
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            artifact_url = ""
            if run_id and repo:
                artifact_url = f"https://github.com/{repo}/actions/runs/{run_id}"

            self.telegram.send_video(video_path, script, artifact_url)

            # Save metadata for debugging
            metadata = {
                "title": script.title,
                "seo_title": script.seo_title,
                "category": script.category,
                "duration": script.total_duration_estimate,
                "tags": script.tags,
                "hashtags": script.hashtags
            }
            with open(Config.OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)

            print("\n" + "=" * 60)
            print("PIPELINE COMPLETED SUCCESSFULLY!")
            print("=" * 60)

            return True

        except Exception as e:
            print(f"\nPIPELINE FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Cleanup temporary files to save GitHub Actions disk space
            print("\nCleaning up temporary files...")
            for d in [Config.FRAMES_DIR, Config.AUDIO_DIR, Config.SUBTITLES_DIR]:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
        # =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pipeline = AjeebologyPipeline()
    success = pipeline.run()
    sys.exit(0 if success else 1)
