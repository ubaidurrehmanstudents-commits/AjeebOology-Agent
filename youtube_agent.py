import os
import sys
import json
import time
import edge_tts
import requests
import math
import random
import string
import hashlib
import tempfile
import subprocess
import textwrap
import re
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from urllib.parse import quote

import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# =============================================================================
# PART 1/16 - CONFIGURATION
# =============================================================================

class Config:
    """All constants and configuration for the pipeline."""
    
    # Channel
    CHANNEL_NAME = "AJEEBOLOGY SHORTS"
    NICHE = "psychology"
    
    # Video
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    TARGET_DURATION = 58.0
    
    # Voice
    VOICE = "hi-IN-MadhurNeural"
    VOICE_SPEED = "+15%"
    MAX_SILENCE_MS = 50
    
    # Audio mixing
    BG_MUSIC_VOLUME = 0.12
    SFX_VOLUME = 0.35
    ROOM_TONE_VOLUME = 0.03
    
    # Caption style
    CAPTION_FONT = "Arial-Bold"
    CAPTION_SIZE = 70
    CAPTION_OUTLINE = 4
    CAPTION_COLOR = "&H00FFFFFF"
    CAPTION_OUTLINE_COLOR = "&H00000000"
    EMPHASIS_COLOR = "&H0000FFFF"
    
    # ASS animation
    SLIDE_UP_DURATION = 0.25
    BOUNCE_DURATION = 0.15
    
    # Visual effects
    ZOOM_PUNCH_SCALE = 1.08
    ZOOM_PUNCH_DURATION = 0.2
    SHAKE_PIXELS = 2
    SHAKE_DURATION = 0.3
    FLASH_DURATION = 0.1
    TRANSITION_DURATION = 0.3
    
    # Ken Burns
    KEN_BURNS_ZOOM_START = 1.0
    KEN_BURNS_ZOOM_END = 1.15
    KEN_BURNS_PAN_RANGE = 20
    
    # Graphics
    PROGRESS_BAR_HEIGHT = 12
    PROGRESS_BAR_COLOR = "0x00FFFF"
    WATERMARK_Y = 60
    CTA_DURATION = 8.0
    
    # Particles
    PARTICLE_COUNT = 50
    PARTICLE_SPEED = 30
    
    # API endpoints
    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    TAVILY_API_URL = "https://api.tavily.com/search"
    POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{}"
    PIXABAY_API_URL = "https://pixabay.com/api/"
    PIXABAY_AUDIO_URL = "https://pixabay.com/api/videos/"
    
    # SFX fallback URLs (Pixabay CDN direct links)
    SFX_WHOOSH = "https://cdn.pixabay.com/download/audio/2022/03/24/audio_07b2a04be3.mp3"
    SFX_POP = "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3"
    SFX_RISER = "https://cdn.pixabay.com/download/audio/2021/08/04/audio_0625c1531c.mp3"
    
    # Music fallback
    MUSIC_URL = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3"
    
    # Categories for rotation
    CATEGORIES = ["psychology", "space", "weird facts"]
    
    # Emphasis keywords for auto-detection
    EMPHASIS_WORDS = [
        "shocking", "amazing", "unbelievable", "crazy", "insane",
        "secret", "hidden", "truth", "never", "always", "every",
        "dangerous", "powerful", "mind", "brain", "psychology"
    ]
    
    # Output
    OUTPUT_DIR = "output"
    TEMP_DIR = "temp"
    
    @classmethod
    def ensure_dirs(cls):
        Path(cls.OUTPUT_DIR).mkdir(exist_ok=True)
        Path(cls.TEMP_DIR).mkdir(exist_ok=True)
# =============================================================================
# PART 2/16 - DATA CLASSES & UTILITY FUNCTIONS
# =============================================================================

@dataclass
class VideoSegment:
    """A single segment of the video script."""
    text: str
    segment_type: str
    duration: float = 0.0
    emphasis_words: List[str] = field(default_factory=list)
    is_shocking: bool = False
    broll_prompt: str = ""


@dataclass
class Script:
    """Complete video script structure."""
    hook: VideoSegment
    fact1: VideoSegment
    fact2: VideoSegment
    fact3: VideoSegment
    outro: VideoSegment
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)


@dataclass
class WordTiming:
    """Timing for a single word in captions."""
    word: str
    start: float
    end: float
    is_emphasis: bool = False


@dataclass
class AudioEvent:
    """An audio event (SFX) at a specific time."""
    timestamp: float
    sfx_type: str
    duration: float


def sanitize_filename(name: str) -> str:
    """Create a safe filename from any string."""
    valid = string.ascii_letters + string.digits + "_-"
    return "".join(c if c in valid else "_" for c in name)[:50]


def run_ffmpeg(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run an FFmpeg command safely."""
    full_cmd = ["ffmpeg", "-y"] + cmd
    return subprocess.run(full_cmd, capture_output=True, text=True, check=check)


def get_audio_duration(path: str) -> float:
    """Get duration of an audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def download_file(url: str, path: str, timeout: int = 30) -> bool:
    """Download a file with retry logic."""
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=timeout, stream=True)
            response.raise_for_status()
            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)
    return False


def load_json_safe(text: str) -> Optional[Dict]:
    """Safely extract and parse JSON from text."""
    try:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except Exception:
        return None


def escape_ass_text(text: str) -> str:
    """Escape text for ASS subtitle format."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    return text


def hex_to_ass_color(hex_color: str) -> str:
    """Convert hex color to ASS format (&HAABBGGRR)."""
    hex_color = hex_color.replace("#", "").replace("&H", "")
    if len(hex_color) == 6:
        r = hex_color[0:2]
        g = hex_color[2:4]
        b = hex_color[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00FFFFFF"


def generate_gradient_background(width: int, height: int) -> str:
    """Generate animated gradient background using FFmpeg."""
    return (
        f"gradients=s={width}x{height}:"
        f"x0=0:y0=0:x1={width}:y1={height}:"
        f"colors=2B1055+0000FF:steps=30:seed=42"
    )


def chunk_list(lst: List, size: int) -> List[List]:
    """Split list into chunks of given size."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def get_random_gradient_colors() -> Tuple[str, str]:
    """Get random dark gradient colors for background."""
    colors = [
        ("2B1055", "0000FF"),
        ("1a1a2e", "16213e"),
        ("0f0c29", "302b63"),
        ("200122", "6f0000"),
        ("1e3c72", "2a5298"),
    ]
    return random.choice(colors)
# =============================================================================
# PART 3/16 - RESEARCH AGENT (Tavily)
# =============================================================================

class ResearchAgent:
    """Fetches trending facts using Tavily search API."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.category = random.choice(Config.CATEGORIES)
    
    def search_facts(self, query_count: int = 3) -> List[Dict]:
        """Search for interesting facts in the chosen category."""
        queries = self._build_queries()
        all_results = []
        for query in queries[:query_count]:
            results = self._tavily_search(query)
            all_results.extend(results)
        return self._filter_best_facts(all_results)
    
    def _build_queries(self) -> List[str]:
        """Build search queries based on category."""
        templates = {
            "psychology": [
                "shocking psychology facts about human behavior 2026",
                "mind blowing brain facts that will surprise you",
                "hidden psychology tricks people don't know"
            ],
            "space": [
                "amazing space secrets NASA doesn't tell you 2026",
                "shocking facts about the universe and planets",
                "hidden space discoveries that blow your mind"
            ],
            "weird facts": [
                "unbelievable weird facts you never knew existed",
                "crazy hidden facts about everyday things",
                "shocking trivia facts that sound fake but true"
            ]
        }
        return templates.get(self.category, templates["psychology"])
    
    def _tavily_search(self, query: str) -> List[Dict]:
        """Call Tavily API to search for facts."""
        try:
            headers = {"Content-Type": "application/json"}
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": 5,
                "include_answer": True
            }
            response = requests.post(
                Config.TAVILY_API_URL,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            answer = data.get("answer", "")
            if answer:
                results.insert(0, {"content": answer, "title": "AI Summary"})
            return results
        except Exception as e:
            print(f"Tavily search error: {e}")
            return []
    
    def _filter_best_facts(self, results: List[Dict]) -> List[Dict]:
        """Filter and rank the best facts from search results."""
        facts = []
        for result in results:
            content = result.get("content", "")
            if len(content) > 50 and len(content) < 500:
                facts.append({
                    "text": content,
                    "title": result.get("title", "Unknown"),
                    "source": result.get("url", "")
                })
        random.shuffle(facts)
        return facts[:6]
    
    def get_category(self) -> str:
        """Return the selected category for this run."""
        return self.category
    # =============================================================================
# PART 4/16 - SCRIPT AGENT (Groq) - Main Methods
# =============================================================================

class ScriptAgent:
    """Generates viral Hinglish scripts using Groq API."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def generate_script(self, facts: List[Dict], category: str) -> Script:
        """Generate a complete viral script from research facts."""
        prompt = self._build_prompt(facts, category)
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a viral YouTube Shorts scriptwriter. "
                            "Write in Hinglish (Roman Hindi + English mix). "
                            "Make scripts addictive, fast-paced, and shocking. "
                            "Mark emphasis words with [brackets]. "
                            "Output ONLY valid JSON."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.9,
                "max_tokens": 1500
            }
            response = requests.post(
                Config.GROQ_API_URL,
                headers=headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            data = response.json()
            raw_text = data["choices"][0]["message"]["content"]
            parsed = load_json_safe(raw_text)
            if parsed:
                return self._json_to_script(parsed, category)
        except Exception as e:
            print(f"Groq API error: {e}")
        return self._fallback_script(category)
    
    def _build_prompt(self, facts: List[Dict], category: str) -> str:
        """Build the prompt for Groq."""
        fact_texts = "\n".join([
            f"{i+1}. {f['text'][:200]}"
            for i, f in enumerate(facts[:3])
        ])
        return textwrap.dedent(f"""
            Create a viral YouTube Shorts script about {category} facts.
            Use Hinglish (Roman Hindi + English mix).
            Target: 55-60 seconds when spoken naturally.
            
            Research facts:
            {fact_texts}
            
            Output this EXACT JSON structure:
            {{
                "title": "SEO optimized title",
                "description": "engaging description",
                "tags": ["tag1", "tag2", "tag3"],
                "hashtags": ["#hashtag1", "#hashtag2"],
                "hook": "Attention-grabbing first line. [Shocking] word marked.",
                "fact1": "First mind-blowing fact. [Amazing] detail here.",
                "fact2": "Second surprising fact. [Unbelievable] truth.",
                "fact3": "Third hidden secret. [Secret] revealed.",
                "outro": "Call to action + loop back to hook."
            }}
            
            Rules:
            - Hook must grab attention in 2 seconds
            - Each fact should be 1-2 sentences max
            - Mark 1-2 emphasis words per segment with [brackets]
            - Outro must flow back to hook for infinite loop
            - Include strong CTA (subscribe, comment, share)
        """)
        def _json_to_script(self, data: Dict, category: str) -> Script:
        """Convert parsed JSON into Script dataclass."""
        def make_segment(key: str, seg_type: str) -> VideoSegment:
            text = data.get(key, "")
            emphasis = re.findall(r'\[(.*?)\]', text)
            clean_text = re.sub(r'\[|\]', '', text)
            shocking = any(w in clean_text.lower() for w in [
                "shocking", "unbelievable", "crazy", "insane",
                "secret", "hidden", "dangerous", "never"
            ])
            return VideoSegment(
                text=clean_text,
                segment_type=seg_type,
                emphasis_words=emphasis,
                is_shocking=shocking,
                broll_prompt=self._broll_prompt(clean_text, category)
            )
        return Script(
            hook=make_segment("hook", "hook"),
            fact1=make_segment("fact1", "fact1"),
            fact2=make_segment("fact2", "fact2"),
            fact3=make_segment("fact3", "fact3"),
            outro=make_segment("outro", "outro"),
            title=data.get("title", "Amazing Facts You Won't Believe"),
            description=data.get("description", "Mind-blowing facts in Hinglish!"),
            tags=data.get("tags", ["facts", "hinglish", "shorts"]),
            hashtags=data.get("hashtags", ["#Shorts", "#Facts", "#Hinglish"])
        )
    
    def _broll_prompt(self, text: str, category: str) -> str:
        """Generate a B-roll image prompt from segment text."""
        keywords = {
            "psychology": "brain, mind, psychology, thinking, human behavior",
            "space": "galaxy, stars, planet, universe, astronaut",
            "weird facts": "mystery, question mark, discovery, hidden, secret"
        }
        base = keywords.get(category, "amazing discovery")
        return f"cinematic lighting, highly detailed, 8k resolution, vertical aspect ratio, {base}, {text[:80]}"
    
    def _fallback_script(self, category: str) -> Script:
        """Generate a fallback script if Groq fails."""
        templates = {
            "psychology": {
                "hook": "Kya aap jaante hain aapka brain [80%] fake memories store karta hai?",
                "fact1": "Psychology ke experts kehte hain [eye contact] 7 seconds se zyada uncomfortable lagta hai.",
                "fact2": "Aapka brain [sad songs] sunne se actually dopamine release karta hai.",
                "fact3": "[95%] log apne decisions ke baad regret feel karte hain, lekin phir bhi same mistake repeat karte hain.",
                "outro": "Agar ye facts [shocking] lage toh subscribe karo, aur comments mein batao kaunsa fact sabse zyada surprising tha!"
            },
            "space": {
                "hook": "NASA ne [ek aisa planet] discover kiya jahan ek saal sirf 8.5 hours ka hai!",
                "fact1": "Space mein [ek dead star] hai jo har second 716 times rotate karti hai.",
                "fact2": "Agar aap [Venus] pe khade honge toh sun east se nahi, [west] se ugta dikhega.",
                "fact3": "Universe ka [96%] matter aise hai jo hum dekh nahi sakte, scientists isse [dark matter] kehte hain.",
                "outro": "Space ke ye [hidden secrets] pasand aaye toh channel subscribe karo, aur share karo space lovers ke saath!"
            },
            "weird facts": {
                "hook": "Kya aapne kabhi socha ki [honey] kabhi expire nahi hota?",
                "fact1": "Octopus ke [three hearts] hote hain aur unka blood [blue] hota hai.",
                "fact2": "Banana technically [berry] hai, lekin strawberry [berry] nahi hai.",
                "fact3": "Agar aap [space] mein chillayenge toh koi aapki awaaz [sun nahi payega].",
                "outro": "Ye [weird facts] pasand aaye toh like karo, subscribe karo, aur comments mein apna favorite fact batayo!"
            }
        }
        data = templates.get(category, templates["psychology"])
        data["title"] = f"Amazing {category.title()} Facts That Will Blow Your Mind"
        data["description"] = f"Mind-blowing {category} facts in Hinglish that you never knew!"
        data["tags"] = [category, "facts", "hinglish", "shorts", "viral"]
        data["hashtags"] = ["#Shorts", "#Facts", "#Hinglish", "#Viral"]
        return self._json_to_script(data, category)
    # =============================================================================
# PART 6/16 - VOICE AGENT (edge-tts + silence trimming + word timings)
# =============================================================================

class VoiceAgent:
    """Generates natural AI voice with word-level timing data."""
    
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.temp_dir.mkdir(exist_ok=True)
    
    async def generate_voice(self, script: Script) -> Tuple[str, List[WordTiming], float]:
        """Generate voice audio and return path + word timings + total duration."""
        full_text = self._combine_text(script)
        clean_text = self._clean_for_tts(full_text)
        voice_path = str(self.temp_dir / "voice_raw.mp3")
        boundary_path = str(self.temp_dir / "voice_boundaries.json")
        await self._run_edge_tts(clean_text, voice_path, boundary_path)
        word_timings = self._parse_boundaries(boundary_path, clean_text)
        trimmed_path = self._trim_silence(voice_path)
        duration = get_audio_duration(trimmed_path)
        return trimmed_path, word_timings, duration
    
    def _combine_text(self, script: Script) -> str:
        """Combine all segments into one text with minimal pauses."""
        segments = [
            script.hook.text,
            script.fact1.text,
            script.fact2.text,
            script.fact3.text,
            script.outro.text
        ]
        return ". ".join(segments)
    
    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS (remove brackets, normalize)."""
        text = re.sub(r'\[|\]', '', text)
        text = text.replace("  ", " ").strip()
        return text
    
    async def _run_edge_tts(self, text: str, output: str, boundary_file: str):
        """Run edge-tts with word boundary output."""
        communicate = edge_tts.Communicate(
            text=text,
            voice=Config.VOICE,
            rate=Config.VOICE_SPEED
        )
        word_boundaries = []
        async for chunk in communicate.stream():
            if chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "text": chunk["text"],
                    "offset": chunk["offset"] / 10000000.0,
                    "duration": chunk["duration"] / 10000000.0
                })
        await communicate.save(output)
        with open(boundary_file, "w", encoding="utf-8") as f:
            json.dump(word_boundaries, f, indent=2)
    
    def _parse_boundaries(self, path: str, full_text: str) -> List[WordTiming]:
        """Parse edge-tts word boundaries into WordTiming objects."""
        if not Path(path).exists():
            return self._fallback_timings(full_text)
        with open(path, "r", encoding="utf-8") as f:
            boundaries = json.load(f)
        timings = []
        for b in boundaries:
            word = b.get("text", "").strip()
            if word:
                timings.append(WordTiming(
                    word=word,
                    start=b["offset"],
                    end=b["offset"] + b["duration"],
                    is_emphasis=word.lower() in [w.lower() for w in Config.EMPHASIS_WORDS]
                ))
        return timings
    
    def _fallback_timings(self, text: str) -> List[WordTiming]:
        """Create approximate timings if boundary file missing."""
        words = text.split()
        est_duration = len(words) * 0.35
        return [
            WordTiming(
                word=w,
                start=i * 0.35,
                end=(i + 1) * 0.35,
                is_emphasis=w.lower() in [ew.lower() for ew in Config.EMPHASIS_WORDS]
            )
            for i, w in enumerate(words)
        ]
    
    def _trim_silence(self, input_path: str) -> str:
        """Aggressively trim silence from voice audio."""
        output_path = str(self.temp_dir / "voice_trimmed.mp3")
        cmd = [
            "-i", input_path,
            "-af",
            (
                f"silenceremove=start_periods=1:start_duration=0.1:"
                f"start_threshold=-50dB:"
                f"detection=peak,"
                f"areverse,"
                f"silenceremove=start_periods=1:start_duration=0.1:"
                f"start_threshold=-50dB:"
                f"detection=peak,"
                f"areverse"
            ),
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "192k",
            output_path
        ]
        run_ffmpeg(cmd)
        return output_path
        def mix_audio(
        self,
        voice_path: str,
        music_path: str,
        sfx_events: List[AudioEvent],
        output_path: str
    ) -> str:
        """Mix voice, music, SFX, and room tone into final audio."""
        voice_dur = get_audio_duration(voice_path)
        total_dur = min(voice_dur + 2.0, Config.TARGET_DURATION)
        room_path = self._generate_room_tone(total_dur)
        inputs = [
            f"-i {voice_path}",
            f"-i {music_path}",
            f"-i {room_path}"
        ]
        filter_parts = [
            "[0:a]volume=1.0[vo]",
            "[1:a]volume={Config.BG_MUSIC_VOLUME},"
            f"afade=t=out:st={total_dur-2}:d=2[bg]",
            f"[2:a]volume={Config.ROOM_TONE_VOLUME}[rt]"
        ]
        mix_inputs = "[vo][bg][rt]"
        for i, event in enumerate(sfx_events):
            sfx_path = self._get_sfx_path(event.sfx_type)
            if Path(sfx_path).exists():
                inputs.append(f"-i {sfx_path}")
                delay_ms = int(event.timestamp * 1000)
                filter_parts.append(
                    f"[{3+i}:a]adelay={delay_ms}|{delay_ms},"
                    f"volume={Config.SFX_VOLUME},"
                    f"afade=t=out:st={event.timestamp+event.duration-0.2}:d=0.2[sfx{i}]"
                )
                mix_inputs += f"[sfx{i}]"
        filter_parts.append(
            f"{mix_inputs}amix=inputs={3+len(sfx_events)}:"
            f"duration=longest:normalize=0[aout]"
        )
        filter_complex = ";".join(filter_parts)
        cmd = inputs + [
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "192k",
            "-t", str(total_dur),
            output_path
        ]
        run_ffmpeg(cmd)
        return output_path
    
    def _generate_room_tone(self, duration: float) -> str:
        """Generate subtle room tone for natural feel."""
        path = str(self.temp_dir / "room_tone.mp3")
        cmd = [
            "-f", "lavfi",
            "-i", f"anoisesrc=a=0.02:d={duration}:c=pink",
            "-ar", "44100",
            "-ac", "2",
            path
        ]
        run_ffmpeg(cmd)
        return path
    
    def _get_sfx_path(self, sfx_type: str) -> str:
        """Get path to downloaded SFX file."""
        sfx_map = {
            "whoosh": str(self.temp_dir / "sfx_whoosh.mp3"),
            "pop": str(self.temp_dir / "sfx_pop.mp3"),
            "riser": str(self.temp_dir / "sfx_riser.mp3")
        }
        return sfx_map.get(sfx_type, sfx_map["whoosh"])
    # =============================================================================
# PART 8/16 - ASSET AGENT (B-roll + Music + SFX Download)
# =============================================================================

class AssetAgent:
    """Downloads all visual and audio assets needed for the video."""
    
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.temp_dir.mkdir(exist_ok=True)
    
    def download_broll(self, script: Script) -> List[str]:
        """Download B-roll images for each segment."""
        segments = [
            script.hook,
            script.fact1,
            script.fact2,
            script.fact3,
            script.outro
        ]
        paths = []
        for i, seg in enumerate(segments):
            prompt = quote(seg.broll_prompt)
            url = Config.POLLINATIONS_URL.format(prompt)
            url += f"?width={Config.WIDTH}&height={Config.HEIGHT}&seed={random.randint(1, 9999)}"
            path = str(self.temp_dir / f"broll_{i}.jpg")
            success = download_file(url, path, timeout=45)
            if not success or not Path(path).exists():
                path = self._create_placeholder_image(i)
            paths.append(path)
        return paths
    
    def _create_placeholder_image(self, index: int) -> str:
        """Create a gradient placeholder if download fails."""
        path = str(self.temp_dir / f"broll_{index}_fallback.jpg")
        c1, c2 = get_random_gradient_colors()
        cmd = [
            "-f", "lavfi",
            "-i", (
                f"gradients=s={Config.WIDTH}x{Config.HEIGHT}:"
                f"x0=0:y0=0:x1={Config.WIDTH}:y1={Config.HEIGHT}:"
                f"colors={c1}+{c2}:steps=30:seed={index}"
            ),
            "-frames:v", "1",
            path
        ]
        run_ffmpeg(cmd)
        return path
    
    def download_music(self) -> str:
        """Download background music from Pixabay."""
        path = str(self.temp_dir / "bg_music.mp3")
        success = download_file(Config.MUSIC_URL, path, timeout=30)
        if not success:
            return self._generate_synthetic_music()
        return path
    
    def _generate_synthetic_music(self) -> str:
        """Generate simple ambient music if download fails."""
        path = str(self.temp_dir / "bg_music_synth.mp3")
        cmd = [
            "-f", "lavfi",
            "-i", (
                f"aevalsrc=0.1*sin(2*PI*220*t)|"
                f"0.1*sin(2*PI*220*t+PI/4):d=65"
            ),
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "128k",
            path
        ]
        run_ffmpeg(cmd)
        return path
    
    def download_sfx(self) -> Dict[str, str]:
        """Download all sound effects."""
        sfx_urls = {
            "whoosh": Config.SFX_WHOOSH,
            "pop": Config.SFX_POP,
            "riser": Config.SFX_RISER
        }
        paths = {}
        for name, url in sfx_urls.items():
            path = str(self.temp_dir / f"sfx_{name}.mp3")
            success = download_file(url, path, timeout=20)
            if not success:
                path = self._generate_synthetic_sfx(name)
            paths[name] = path
        return paths
    
    def _generate_synthetic_sfx(self, sfx_type: str) -> str:
        """Generate synthetic SFX if download fails."""
        path = str(self.temp_dir / f"sfx_{sfx_type}_synth.mp3")
        if sfx_type == "whoosh":
            expr = "0.3*sin(2*PI*(200+800*t)*t)|0.3*sin(2*PI*(200+800*t)*t)"
            dur = 0.5
        elif sfx_type == "pop":
            expr = "0.5*sin(2*PI*800*t)*exp(-10*t)|0.5*sin(2*PI*800*t)*exp(-10*t)"
            dur = 0.2
        else:
            expr = "0.2*sin(2*PI*(100+400*t)*t)|0.2*sin(2*PI*(100+400*t)*t)"
            dur = 1.5
        cmd = [
            "-f", "lavfi",
            "-i", f"aevalsrc={expr}:d={dur}",
            "-ar", "44100",
            "-ac", "2",
            path
        ]
        run_ffmpeg(cmd)
        return path
# =============================================================================
# PART 9/16 - VIDEO ENGINE - Main Render Method
# =============================================================================

class VideoEngine:
    """Renders professional YouTube Shorts using FFmpeg filters."""
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if not Path(self.font_path).exists():
            alt = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            if Path(alt).exists():
                self.font_path = alt
    def render(self, script, word_timings, audio_path, broll_paths, output_path):
        total_duration = get_audio_duration(audio_path)
        segment_timings = self._calculate_segment_timings(script, word_timings, total_duration)
        ass_path = self._generate_ass_subtitles(word_timings, script, segment_timings)
        bg_path = self._create_background_video(total_duration)
        clip_paths = self._create_broll_clips(broll_paths, segment_timings)
        broll_path = self._concatenate_clips(clip_paths, segment_timings)
        composite_path = self._composite_video(bg_path, broll_path, ass_path, script, word_timings, segment_timings, total_duration)
        self._final_mix(composite_path, audio_path, output_path)
        return output_path
    def _calculate_segment_timings(self, script, word_timings, total_duration):
        segments = [script.hook, script.fact1, script.fact2, script.fact3, script.outro]
        word_counts = [len(s.text.split()) for s in segments]
        total_words = sum(word_counts) or 1
        timings, current = [], 0.0
        for i, seg in enumerate(segments):
            d = total_duration * word_counts[i] / total_words
            timings.append({"start": current, "end": current + d, "duration": d, "segment": seg})
            current += d
        if timings:
            timings[-1]["end"] = total_duration
            timings[-1]["duration"] = total_duration - timings[-1]["start"]
        return timings
    def _create_background_video(self, duration):
        output = str(self.temp_dir / "background.mp4")
        c1, c2 = get_random_gradient_colors()
        grad = f"gradients=s={Config.WIDTH}x{Config.HEIGHT}:x0=0:y0=0:x1={Config.WIDTH}:y1={Config.HEIGHT}:colors={c1}+{c2}:steps=30:seed=42"
        cmd = ["-f", "lavfi", "-i", grad, "-vf", "noise=alls=8:allf=t+u:allc=p,eq=brightness=0.02:contrast=1.1", "-t", str(duration), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-an", output]
        run_ffmpeg(cmd)
        return output
    def _create_broll_clips(self, broll_paths, segment_timings):
        clips = []
        for i, (path, timing) in enumerate(zip(broll_paths, segment_timings)):
            duration = timing["duration"]
            output = str(self.temp_dir / f"clip_{i}.mp4")
            frames = max(int(duration * Config.FPS), 1)
            px = random.choice([-1, 1]) * Config.KEN_BURNS_PAN_RANGE
            py = random.choice([-1, 1]) * Config.KEN_BURNS_PAN_RANGE
            ze = f"1+0.15*on/{frames}"
            xe = f"iw/2-(iw/zoom/2)+{px}*on/{frames}"
            ye = f"ih/2-(ih/zoom/2)+{py}*on/{frames}"
            vf = f"scale={Config.WIDTH}:{Config.HEIGHT}:force_original_aspect_ratio=increase,crop={Config.WIDTH}:{Config.HEIGHT},zoompan=z='{ze}':x='{xe}':y='{ye}':d={frames}:s={Config.WIDTH}x{Config.HEIGHT}"
            cmd = ["-loop", "1", "-i", path, "-vf", vf, "-t", str(duration), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-an", output]
            try:
                run_ffmpeg(cmd, check=True)
            except subprocess.CalledProcessError:
                vf = f"scale={Config.WIDTH}:{Config.HEIGHT}:force_original_aspect_ratio=decrease,pad={Config.WIDTH}:{Config.HEIGHT}:(ow-iw)/2:(oh-ih)/2"
                cmd = ["-loop", "1", "-i", path, "-vf", vf, "-t", str(duration), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-an", output]
                run_ffmpeg(cmd)
            clips.append(output)
        return clips
    def _concatenate_clips(self, clip_paths, segment_timings):
        if len(clip_paths) == 1:
            return clip_paths[0]
        output = str(self.temp_dir / "broll_concat.mp4")
        inputs = []
        for path in clip_paths:
            inputs.extend(["-i", path])
        filters, offsets, t = [], [], Config.TRANSITION_DURATION
        for i in range(len(clip_paths) - 1):
            offsets.append(max(sum(timing["duration"] for timing in segment_timings[:i+1]) - (i + 1) * t, 0.1))
        for i in range(len(clip_paths) - 1):
            label = f"[v{i+1}]"
            if i == 0:
                filters.append(f"[0:v][1:v]xfade=transition=fade:duration={t}:offset={offsets[i]}{label}")
            else:
                filters.append(f"[v{i}][{i+1}:v]xfade=transition=fade:duration={t}:offset={offsets[i]}{label}")
        cmd = inputs + ["-filter_complex", ";".join(filters), "-map", f"[v{len(clip_paths)-1}]", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-an", output]
        run_ffmpeg(cmd)
        return output
      def _generate_ass_subtitles(self, word_timings, script, segment_timings):
        ass_path = str(self.temp_dir / "subtitles.ass")
        emphasis_set = set()
        for seg in [script.hook, script.fact1, script.fact2, script.fact3, script.outro]:
            for ew in seg.emphasis_words:
                emphasis_set.add(ew.lower().strip())
        for wt in word_timings:
            clean = re.sub(r'[^\w]', '', wt.word).lower()
            if clean in emphasis_set:
                wt.is_emphasis = True
        header = self._ass_header()
        events = self._ass_events(word_timings)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + events)
        return ass_path
    def _ass_header(self):
        return (
            "[Script Info]\n"
            "Title: Dynamic Captions\n"
            "ScriptType: v4.00+\n"
            "PlayResX: 1080\n"
            "PlayResY: 1920\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "1,0,0,0,100,100,0,0,1,4,0,2,40,40,200,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
    def _ass_events(self, word_timings):
        lines = self._group_words_into_lines(word_timings)
        events = []
        base_y = 1680
        for idx, line_words in enumerate(lines):
            if not line_words:
                continue
            line_start = line_words[0].start
            line_end = line_words[-1].end + 0.6
            y = base_y - idx * 90
            x = Config.WIDTH // 2
            slide_ms = int(Config.SLIDE_UP_DURATION * 1000)
            move_tag = f"\\move({x},{y+50},{x},{y},0,{slide_ms})"
            text = self._build_line_text(line_words, line_start)
            start_t = self._to_ass_time(line_start)
            end_t = self._to_ass_time(line_end)
            events.append(
                f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,"
                f"{{{move_tag}\\alpha&HFF&}}{text}"
            )
        return "\n".join(events)
    def _group_words_into_lines(self, word_timings):
        lines, current, char_count = [], [], 0
        for wt in word_timings:
            wlen = len(wt.word)
            if char_count + wlen > 20 or len(current) >= 4:
                if current:
                    lines.append(current)
                current, char_count = [wt], wlen
            else:
                current.append(wt)
                char_count += wlen + 1
        if current:
            lines.append(current)
        return lines
    def _build_line_text(self, line_words, line_start):
        parts = []
        for wt in line_words:
            rel_s = int((wt.start - line_start) * 100)
            rel_e1 = rel_s + int(Config.BOUNCE_DURATION * 1000)
            rel_e2 = rel_s + int((Config.BOUNCE_DURATION + 0.1) * 1000)
            fade = f"\\t({rel_s},{rel_s+5},\\alpha&H00&)"
            word_text = escape_ass_text(wt.word)
            if wt.is_emphasis:
                bounce1 = f"\\t({rel_s},{rel_e1},\\fscx120\\fscy120)"
                bounce2 = f"\\t({rel_e1},{rel_e2},\\fscx100\\fscy100)"
                parts.append(
                    f"{{\\c&H0000FFFF&{fade}{bounce1}{bounce2}}}"
                    f"{word_text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}} "
                )
            else:
                parts.append(f"{{{fade}}}{word_text} ")
        return "".join(parts).strip()
    def _to_ass_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        cents = int(round((seconds % 1) * 100))
        if cents >= 100:
            cents = 99
        return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"
    def _calculate_line_y(self, line_words, all_lines):
        idx = 0
        for i, line in enumerate(all_lines):
            if line == line_words:
                idx = i
                break
        return 1680 - idx * 90
       def _composite_video(self, bg_path, broll_path, ass_path, script, word_timings, segment_timings, total_duration):
        output = str(self.temp_dir / "composite.mp4")
        zoom_f = self._build_zoom_filter(word_timings, segment_timings)
        shake_f = self._build_shake_filter(script, segment_timings)
        flash_f = self._build_flash_filter(script, segment_timings)
        vf = f"[0:v][1:v]overlay=0:0:format=auto"
        if zoom_f:
            vf += f",{zoom_f}"
        if shake_f:
            vf += f",{shake_f}"
        if flash_f:
            vf += f",{flash_f}"
        vf += f",ass={ass_path}[out]"
        cmd = [
            "-i", bg_path,
            "-i", broll_path,
            "-filter_complex", vf,
            "-map", "[out]",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-an",
            output
        ]
        run_ffmpeg(cmd)
        return output

    def _build_zoom_filter(self, word_timings, segment_timings):
        parts = []
        for wt in word_timings:
            if wt.is_emphasis:
                s = round(wt.start, 2)
                e = round(s + Config.ZOOM_PUNCH_DURATION, 2)
                parts.append(
                    f"scale='if(between(t\\,{s}\\,{e})\\,iw*1.08\\,iw)':"
                    f"'if(between(t\\,{s}\\,{e})\\,ih*1.08\\,ih)'"
                )
                parts.append(
                    f"crop='if(between(t\\,{s}\\,{e})\\,iw/1.08\\,iw)':"
                    f"'if(between(t\\,{s}\\,{e})\\,ih/1.08\\,ih)':"
                    f"(iw-iw/1.08)/2:(ih-ih/1.08)/2"
                )
        return ",".join(parts) if parts else ""

    def _build_shake_filter(self, script, segment_timings):
        parts = []
        for timing in segment_timings:
            if timing["segment"].is_shocking:
                s = round(timing["start"], 2)
                e = round(s + Config.SHAKE_DURATION, 2)
                parts.append(
                    f"crop=iw-4:ih-4:"
                    f"'if(between(t\\,{s}\\,{e})\\,random(1)*4\\,0)':"
                    f"'if(between(t\\,{s}\\,{e})\\,random(2)*4\\,0)'"
                )
        return ",".join(parts) if parts else ""

    def _build_flash_filter(self, script, segment_timings):
        parts = []
        for i, timing in enumerate(segment_timings):
            if timing["segment"].is_shocking and i > 0:
                s = round(timing["start"] - 0.5, 2)
                e = round(s + Config.FLASH_DURATION, 2)
                if s > 0:
                    parts.append(
                        f"eq=brightness=2:contrast=0.5:"
                        f"enable='between(t\\,{s}\\,{e})'"
                    )
        return ",".join(parts) if parts else ""

    def _final_mix(self, video_path, audio_path, output_path):
        cmd = [
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
        run_ffmpeg(cmd)
       def _generate_particles_video(self, duration):
        output = str(self.temp_dir / "particles.mp4")
        vf = ("noise=alls=30:allf=t+u:allc=p,format=gray,"
              "geq='if(gt(val,220),180,0)',scroll=v=-1")
        cmd = ["-f", "lavfi", "-i", f"color=black:{Config.WIDTH}x{Config.HEIGHT}",
               "-vf", vf, "-t", str(duration), "-pix_fmt", "yuv420p",
               "-c:v", "libx264", "-preset", "ultrafast", "-an", output]
        try:
            run_ffmpeg(cmd)
        except subprocess.CalledProcessError:
            cmd = ["-f", "lavfi", "-i", f"color=black:{Config.WIDTH}x{Config.HEIGHT}",
                   "-t", str(duration), "-pix_fmt", "yuv420p",
                   "-c:v", "libx264", "-preset", "ultrafast", "-an", output]
            run_ffmpeg(cmd)
        return output

    def _composite_video(self, bg_path, broll_path, ass_path, script, word_timings, segment_timings, total_duration):
        output = str(self.temp_dir / "composite.mp4")
        particles_path = self._generate_particles_video(total_duration)
        gfx = self._build_graphics_filter(script, segment_timings, total_duration)
        zoom_f = self._build_zoom_filter(word_timings, segment_timings)
        shake_f = self._build_shake_filter(script, segment_timings)
        flash_f = self._build_flash_filter(script, segment_timings)
        def build_cmd(use_particles):
            filters = ["[0:v][1:v]overlay=0:0:format=auto[base]"]
            last = "[base]"
            if use_particles:
                filters.append(f"{last}[2:v]blend=all_mode=screen:all_opacity=0.4[base2]")
                last = "[base2]"
            if gfx:
                filters.append(f"{last}{gfx}[base3]")
                last = "[base3]"
            if zoom_f:
                filters.append(f"{last}{zoom_f}[z]")
                last = "[z]"
            if shake_f:
                filters.append(f"{last}{shake_f}[s]")
                last = "[s]"
            if flash_f:
                filters.append(f"{last}{flash_f}[f]")
                last = "[f]"
            filters.append(f"{last}ass={ass_path}[out]")
            cmd = ["-i", bg_path, "-i", broll_path]
            if use_particles:
                cmd.extend(["-i", particles_path])
            cmd.extend(["-filter_complex", ";".join(filters), "-map", "[out]",
                       "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-an", output])
            return cmd
        try:
            run_ffmpeg(build_cmd(True))
        except subprocess.CalledProcessError:
            print("Retrying composite without particles...")
            run_ffmpeg(build_cmd(False))
        return output

    def _build_graphics_filter(self, script, segment_timings, total_duration):
        parts = []
        font_opt = f"fontfile={self.font_path}:" if Path(self.font_path).exists() else ""
        bar_w = f"min(t*{Config.WIDTH/total_duration},{Config.WIDTH})"
        parts.append(f"drawbox=x=0:y={Config.HEIGHT-Config.PROGRESS_BAR_HEIGHT}:w='{bar_w}':h={Config.PROGRESS_BAR_HEIGHT}:color={Config.PROGRESS_BAR_COLOR}@1:t=max")
        parts.append(f"drawtext={font_opt}text='{Config.CHANNEL_NAME}':x=(w-text_w)/2:y={Config.WATERMARK_Y}:fontsize=32:fontcolor=white:box=1:boxcolor=0x000000@0.6:boxborderw=4")
        parts.append(f"drawbox=x='w/2+140':y={Config.WATERMARK_Y+10}:w=10:h=10:color=red@'0.5+0.5*sin(2*PI*2*t)':t=max")
        parts.append(f"drawbox=x='(w-340)/2':y=180:w=340:h=60:color=0xFFD700@0.9:t=max:enable='lt(t,3)'")
        parts.append(f"drawtext={font_opt}text='DID YOU KNOW?':x=(w-text_w)/2:y=192:fontsize=30:fontcolor=black:enable='lt(t,3)'")
        for i, timing in enumerate(segment_timings[1:4], 1):
            s = round(timing["start"], 2)
            e = round(timing["end"], 2)
            parts.append(f"drawbox=x=50:y=50:w=60:h=60:color=0xFF4444@0.9:t=max:enable='between(t,{s},{e})'")
            parts.append(f"drawtext={font_opt}text='{i}':x=50+30-text_w/2:y=50+30-text_h/2:fontsize=32:fontcolor=white:enable='between(t,{s},{e})'")
        cta_s = round(max(total_duration - Config.CTA_DURATION, 0), 2)
        slide_y = f"if(between(t,{cta_s},{cta_s+0.5}),h-(h-150)*((t-{cta_s})/0.5),h-150)"
        parts.append(f"drawbox=x='(w-380)/2':y='{slide_y}':w=380:h=90:color=red@0.9:t=max:enable='gte(t,{cta_s})'")
        parts.append(f"drawtext={font_opt}text='SUBSCRIBE NOW':x=(w-text_w)/2:y='{slide_y}+22':fontsize=40:fontcolor=white:enable='gte(t,{cta_s})'")
        return ",".join(parts)
# =============================================================================
# PART 13/16 - TELEGRAM AGENT + THUMBNAIL GENERATION
# =============================================================================

class TelegramAgent:
    """Sends video, thumbnail, and metadata to Telegram."""
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    def send_video(self, video_path, thumb_path, metadata):
        try:
            with open(video_path, "rb") as v, open(thumb_path, "rb") as t:
                payload = {
                    "chat_id": self.chat_id,
                    "caption": self._build_caption(metadata),
                    "parse_mode": "HTML"
                }
                files = {
                    "video": v,
                    "thumbnail": t
                }
                response = requests.post(
                    f"{self.base_url}/sendVideo",
                    data=payload,
                    files=files,
                    timeout=120
                )
                response.raise_for_status()
                return True
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False
    def send_failure(self, error_msg):
        try:
            text = f"<b>❌ YouTube Agent Failed</b>\n\n{error_msg}\n\nCheck GitHub Actions logs."
            requests.post(
                f"{self.base_url}/sendMessage",
                data={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=30
            )
        except Exception as e:
            print(f"Telegram failure notify error: {e}")
    def _build_caption(self, metadata):
        lines = [
            f"<b>{metadata['title']}</b>",
            "",
            f"<b>Description:</b> {metadata['description']}",
            "",
            f"<b>Tags:</b> {', '.join(metadata.get('tags', []))}",
            "",
            f"<b>Hashtags:</b> {' '.join(metadata.get('hashtags', []))}",
            "",
            f"<b>Duration:</b> {metadata.get('duration', 0):.1f}s",
            "",
            "Download artifacts from GitHub Actions."
        ]
        return "\n".join(lines)


class ThumbnailAgent:
    """Generates professional YouTube thumbnail."""
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    def generate(self, script, output_path):
        try:
            img = Image.new("RGB", (1280, 720), "#1a1a2e")
            draw = ImageDraw.Draw(img)
            c1 = "#2B1055"
            c2 = "#0000FF"
            for y in range(720):
                ratio = y / 720
                r = int(int(c1[1:3], 16) * (1 - ratio) + int(c2[1:3], 16) * ratio)
                g = int(int(c1[3:5], 16) * (1 - ratio) + int(c2[3:5], 16) * ratio)
                b = int(int(c1[5:7], 16) * (1 - ratio) + int(c2[5:7], 16) * ratio)
                draw.line([(0, y), (1280, y)], fill=(r, g, b))
            try:
                font_large = ImageFont.truetype(self.font_path, 72)
                font_small = ImageFont.truetype(self.font_path, 36)
            except:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()
            title = script.title[:40] if len(script.title) > 40 else script.title
            words = title.split()
            y_pos = 200
            for word in words[:4]:
                bbox = draw.textbbox((0, 0), word, font=font_large)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                x = (1280 - w) // 2
                for dx in range(-3, 4):
                    for dy in range(-3, 4):
                        draw.text((x + dx, y_pos + dy), word, fill="black", font=font_large)
                draw.text((x, y_pos), word, fill="white", font=font_large)
                y_pos += h + 20
            hook_text = script.hook.text[:50] + "..." if len(script.hook.text) > 50 else script.hook.text
            bbox = draw.textbbox((0, 0), hook_text, font=font_small)
            w = bbox[2] - bbox[0]
            x = (1280 - w) // 2
            draw.text((x, 550), hook_text, fill="#FFD700", font=font_small)
            draw.text((540, 620), "AJEEBOLOGY SHORTS", fill="white", font=font_small)
            img.save(output_path, "JPEG", quality=95)
            return output_path
        except Exception as e:
            print(f"Thumbnail error: {e}")
            return self._fallback_thumbnail(output_path)
    def _fallback_thumbnail(self, output_path):
        try:
            cmd = [
                "-f", "lavfi", "-i",
                f"color=c=1a1a2e:s=1280x720",
                "-vf",
                "drawtext=text='AJEEBOLOGY SHORTS':fontsize=60:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
                "-frames:v", "1",
                output_path
            ]
            run_ffmpeg(cmd)
            return output_path
        except Exception as e:
            print(f"Fallback thumbnail error: {e}")
            Path(output_path).touch()
            return output_path


# =============================================================================
# PART 14/16 - MAIN PIPELINE ORCHESTRATOR
# =============================================================================

class Pipeline:
    """Orchestrates the entire video generation pipeline."""
    def __init__(self):
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.tavily_key = os.getenv("TAVILY_API_KEY", "")
        self.tg_token = os.getenv("TELEGRAM_TOKEN", "")
        self.tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        Config.ensure_dirs()
        self.research = ResearchAgent(self.tavily_key)
        self.script_agent = ScriptAgent(self.groq_key)
        self.voice = VoiceAgent()
        self.assets = AssetAgent()
        self.video = VideoEngine()
        self.telegram = TelegramAgent(self.tg_token, self.tg_chat)
        self.thumbnail = ThumbnailAgent()
    def run(self):
        print("=" * 50)
        print("YOUTUBE SHORTS AGENT - STARTING")
        print("=" * 50)
        try:
            print("\n[1/8] Researching facts...")
            facts = self.research.search_facts()
            category = self.research.get_category()
            print(f"   Category: {category}")
            print(f"   Facts found: {len(facts)}")
            print("\n[2/8] Generating script...")
            script = self.script_agent.generate_script(facts, category)
            print(f"   Title: {script.title}")
            print("\n[3/8] Generating voice...")
            voice_path, word_timings, voice_dur = asyncio.run(self.voice.generate_voice(script))
            print(f"   Voice duration: {voice_dur:.2f}s")
            print("\n[4/8] Downloading assets...")
            broll_paths = self.assets.download_broll(script)
            music_path = self.assets.download_music()
            sfx_paths = self.assets.download_sfx()
            print(f"   B-roll images: {len(broll_paths)}")
            print("\n[5/8] Building SFX events...")
            sfx_events = self._build_sfx_events(script, word_timings)
            print(f"   SFX events: {len(sfx_events)}")
            print("\n[6/8] Mixing audio...")
            mixed_audio = str(Path(Config.TEMP_DIR) / "mixed_audio.mp3")
            self.voice.mix_audio(voice_path, music_path, sfx_events, mixed_audio)
            print(f"   Mixed audio saved")
            print("\n[7/8] Rendering video...")
            video_path = str(Path(Config.OUTPUT_DIR) / "video.mp4")
            self.video.render(script, word_timings, mixed_audio, broll_paths, video_path)
            video_dur = get_audio_duration(video_path)
            print(f"   Video rendered: {video_dur:.2f}s")
            print("\n[8/8] Generating thumbnail & metadata...")
            thumb_path = str(Path(Config.OUTPUT_DIR) / "thumbnail.jpg")
            self.thumbnail.generate(script, thumb_path)
            metadata = {
                "title": script.title,
                "description": script.description,
                "tags": script.tags,
                "hashtags": script.hashtags,
                "category": category,
                "duration": video_dur,
                "hook": script.hook.text,
                "fact1": script.fact1.text,
                "fact2": script.fact2.text,
                "fact3": script.fact3.text,
                "outro": script.outro.text
            }
            meta_path = str(Path(Config.OUTPUT_DIR) / "metadata.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print("\n[DELIVERY] Sending to Telegram...")
            self.telegram.send_video(video_path, thumb_path, metadata)
            print("\n" + "=" * 50)
            print("PIPELINE COMPLETE!")
            print(f"Video: {video_path}")
            print(f"Thumbnail: {thumb_path}")
            print(f"Metadata: {meta_path}")
            print("=" * 50)
            return True
        except Exception as e:
            error_msg = str(e)
            print(f"\n❌ PIPELINE FAILED: {error_msg}")
            self.telegram.send_failure(error_msg)
            raise
    def _build_sfx_events(self, script, word_timings):
        events = []
        segments = [script.hook, script.fact1, script.fact2, script.fact3, script.outro]
        word_idx = 0
        for i, seg in enumerate(segments):
            if word_idx >= len(word_timings):
                break
            seg_start = word_timings[word_idx].start
            events.append(AudioEvent(
                timestamp=seg_start,
                sfx_type="whoosh",
                duration=0.5
            ))
            if seg.is_shocking and word_idx + 2 < len(word_timings):
                riser_time = word_timings[word_idx + 2].start - 1.0
                if riser_time > seg_start:
                    events.append(AudioEvent(
                        timestamp=riser_time,
                        sfx_type="riser",
                        duration=1.5
                    ))
            seg_words = len(seg.text.split())
            for j in range(word_idx, min(word_idx + seg_words, len(word_timings))):
                if word_timings[j].is_emphasis:
                    events.append(AudioEvent(
                        timestamp=word_timings[j].start,
                        sfx_type="pop",
                        duration=0.2
                    ))
            word_idx += seg_words
        return events


# =============================================================================
# PART 15/16 - ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pipeline = Pipeline()
    pipeline.run()
                
    
