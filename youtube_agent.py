import os
import sys
import json
import time
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

import edge_tts
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    CHANNEL_NAME = "AJEEBOLOGY SHORTS"
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    TARGET_DURATION = 58.0
    VOICE = "hi-IN-MadhurNeural"
    VOICE_SPEED = "+15%"
    BG_MUSIC_VOLUME = 0.12
    SFX_VOLUME = 0.25
    ROOM_TONE_VOLUME = 0.03
    CAPTION_SIZE = 70
    CAPTION_OUTLINE = 4
    SLIDE_UP_MS = 250
    BOUNCE_MS = 150
    ZOOM_SCALE = 1.08
    ZOOM_DURATION = 0.2
    SHAKE_PX = 2
    SHAKE_DURATION = 0.3
    FLASH_DURATION = 0.1
    TRANSITION_DURATION = 0.3
    KEN_BURNS_ZOOM_END = 1.15
    KEN_BURNS_PAN = 20
    PROGRESS_BAR_H = 12
    PROGRESS_BAR_COLOR = "cyan"
    WATERMARK_Y = 60
    CTA_DURATION = 8.0
    PARTICLE_COUNT = 50
    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    TAVILY_URL = "https://api.tavily.com/search"
    POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{}"
    SFX_WHOOSH = ""
    SFX_POP = ""
    SFX_RISER = ""
    MUSIC_URL = ""
    CATEGORIES = ["psychology", "space", "weird facts"]
    EMPHASIS_WORDS = [
        "shocking", "amazing", "unbelievable", "crazy", "insane",
        "secret", "hidden", "truth", "never", "always", "every",
        "dangerous", "powerful", "mind", "brain", "psychology"
    ]
    OUTPUT_DIR = "output"
    TEMP_DIR = "temp"

    @classmethod
    def ensure_dirs(cls):
        Path(cls.OUTPUT_DIR).mkdir(exist_ok=True)
        Path(cls.TEMP_DIR).mkdir(exist_ok=True)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class VideoSegment:
    text: str
    segment_type: str
    duration: float = 0.0
    emphasis_words: List[str] = field(default_factory=list)
    is_shocking: bool = False
    broll_prompt: str = ""


@dataclass
class Script:
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
    word: str
    start: float
    end: float
    is_emphasis: bool = False


@dataclass
class AudioEvent:
    timestamp: float
    sfx_type: str
    duration: float


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def sanitize_filename(name: str) -> str:
    valid = string.ascii_letters + string.digits + "_-"
    return "".join(c if c in valid else "_" for c in name)[:50]


def run_ffmpeg(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    full_cmd = ["ffmpeg", "-y"] + cmd
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"FFmpeg FAILED: {' '.join(full_cmd)}")
        print(f"FFmpeg stderr: {result.stderr}")
        raise subprocess.CalledProcessError(
            result.returncode, full_cmd, output=result.stdout, stderr=result.stderr
        )
    return result


def get_audio_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 0.0


def download_file(url: str, path: str, timeout: int = 30) -> bool:
    if not url:
        return False
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=timeout, stream=True)
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"Download attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)
    return False


def load_json_safe(text: str) -> Optional[Dict]:
    try:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except:
        return None


def escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def get_gradient_colors() -> Tuple[str, str]:
    colors = [
        ("2B1055", "0000FF"),
        ("1a1a2e", "16213e"),
        ("0f0c29", "302b63"),
        ("200122", "6f0000"),
        ("1e3c72", "2a5298")
    ]
    return random.choice(colors)


def build_geq_gradient(width: int, height: int, c1: str, c2: str) -> str:
    r1 = int(c1[0:2], 16)
    g1 = int(c1[2:4], 16)
    b1 = int(c1[4:6], 16)
    r2 = int(c2[0:2], 16)
    g2 = int(c2[2:4], 16)
    b2 = int(c2[4:6], 16)
    return (
        f"geq=r='({r1}+({r2}-{r1})*Y/{height})':"
        f"g='({g1}+({g2}-{g1})*Y/{height})':"
        f"b='({b1}+({b2}-{b1})*Y/{height})'"
    )


# =============================================================================
# RESEARCH AGENT
# =============================================================================

class ResearchAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.category = random.choice(Config.CATEGORIES)

    def search_facts(self, query_count: int = 3) -> List[Dict]:
        queries = self._build_queries()
        all_results = []
        for query in queries[:query_count]:
            results = self._tavily_search(query)
            all_results.extend(results)
        return self._filter_best_facts(all_results)

    def _build_queries(self) -> List[str]:
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
        try:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": 5,
                "include_answer": True
            }
            r = requests.post(Config.TAVILY_URL, json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            answer = data.get("answer", "")
            if answer:
                results.insert(0, {"content": answer, "title": "AI Summary"})
            return results
        except Exception as e:
            print(f"Tavily error: {e}")
            return []

    def _filter_best_facts(self, results: List[Dict]) -> List[Dict]:
        facts = []
        for r in results:
            content = r.get("content", "")
            if 50 < len(content) < 500:
                facts.append({
                    "text": content,
                    "title": r.get("title", ""),
                    "source": r.get("url", "")
                })
        random.shuffle(facts)
        return facts[:6]

    def get_category(self) -> str:
        return self.category


# =============================================================================
# SCRIPT AGENT
# =============================================================================

class ScriptAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def generate_script(self, facts: List[Dict], category: str) -> Script:
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
            r = requests.post(Config.GROQ_URL, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            data = r.json()
            raw = data["choices"][0]["message"]["content"]
            parsed = load_json_safe(raw)
            if parsed:
                return self._json_to_script(parsed, category)
        except Exception as e:
            print(f"Groq error: {e}")
        return self._fallback_script(category)

    def _build_prompt(self, facts: List[Dict], category: str) -> str:
        fact_texts = "\n".join([
            f"{i + 1}. {f['text'][:200]}"
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
        def make_segment(key: str, seg_type: str) -> VideoSegment:
            text = data.get(key, "")
            emphasis = re.findall(r'\[(.*?)\]', text)
            clean = re.sub(r'\[|\]', '', text)
            shocking = any(w in clean.lower() for w in [
                "shocking", "unbelievable", "crazy", "insane",
                "secret", "hidden", "dangerous", "never"
            ])
            return VideoSegment(
                text=clean,
                segment_type=seg_type,
                emphasis_words=emphasis,
                is_shocking=shocking,
                broll_prompt=self._broll_prompt(clean, category)
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
        keywords = {
            "psychology": "brain, mind, psychology, thinking, human behavior",
            "space": "galaxy, stars, planet, universe, astronaut",
            "weird facts": "mystery, question mark, discovery, hidden, secret"
        }
        base = keywords.get(category, "amazing discovery")
        return f"cinematic lighting, highly detailed, 8k resolution, vertical aspect ratio, {base}, {text[:80]}"

    def _fallback_script(self, category: str) -> Script:
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
# VOICE AGENT
# =============================================================================

class VoiceAgent:
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.temp_dir.mkdir(exist_ok=True)

    async def generate_voice(self, script: Script) -> Tuple[str, List[WordTiming], float]:
        full_text = self._combine_text(script)
        clean_text = self._clean_for_tts(full_text)
        voice_path = str(self.temp_dir / "voice_raw.mp3")
        boundary_path = str(self.temp_dir / "voice_boundaries.json")
        await self._run_edge_tts(clean_text, voice_path, boundary_path)
        word_timings = self._parse_boundaries(boundary_path, clean_text)
        duration = get_audio_duration(voice_path)
        return voice_path, word_timings, duration

    def _combine_text(self, script: Script) -> str:
        segments = [
            script.hook.text,
            script.fact1.text,
            script.fact2.text,
            script.fact3.text,
            script.outro.text
        ]
        return ". ".join(segments)

    def _clean_for_tts(self, text: str) -> str:
        text = re.sub(r'\[|\]', '', text)
        return text.replace("  ", " ").strip()

    async def _run_edge_tts(self, text: str, output: str, boundary_file: str):
        communicate = edge_tts.Communicate(
            text=text, voice=Config.VOICE, rate=Config.VOICE_SPEED
        )
        word_boundaries = []
        async for chunk in communicate.stream():
            if chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "text": chunk["text"],
                    "offset": chunk["offset"] / 10000000.0,
                    "duration": chunk["duration"] / 10000000.0
                })
        communicate2 = edge_tts.Communicate(
            text=text, voice=Config.VOICE, rate=Config.VOICE_SPEED
        )
        await communicate2.save(output)
        with open(boundary_file, "w", encoding="utf-8") as f:
            json.dump(word_boundaries, f, indent=2)

    def _parse_boundaries(self, path: str, full_text: str) -> List[WordTiming]:
        if not Path(path).exists():
            return self._fallback_timings(full_text)
        with open(path, "r", encoding="utf-8") as f:
            boundaries = json.load(f)
        timings = []
        for b in boundaries:
            word = b.get("text", "").strip()
            if word:
                clean_word = re.sub(r'[^\w]', '', word).lower()
                is_emp = clean_word in [w.lower() for w in Config.EMPHASIS_WORDS]
                timings.append(WordTiming(
                    word=word,
                    start=b["offset"],
                    end=b["offset"] + b["duration"],
                    is_emphasis=is_emp
                ))
        return timings

    def _fallback_timings(self, text: str) -> List[WordTiming]:
        words = text.split()
        return [
            WordTiming(
                word=w,
                start=i * 0.35,
                end=(i + 1) * 0.35,
                is_emphasis=w.lower() in [ew.lower() for ew in Config.EMPHASIS_WORDS]
            )
            for i, w in enumerate(words)
        ]

    def mix_audio(
        self,
        voice_path: str,
        music_path: str,
        sfx_events: List[AudioEvent],
        output_path: str
    ) -> str:
        voice_dur = get_audio_duration(voice_path)
        total_dur = min(voice_dur + 1.0, Config.TARGET_DURATION)

        room_path = str(self.temp_dir / "room_tone.mp3")
        run_ffmpeg([
            "-f", "lavfi", "-i", f"anoisesrc=a=0.02:d={total_dur}:c=pink",
            "-ar", "44100", "-ac", "2", room_path
        ])

        inputs = ["-i", voice_path, "-i", music_path, "-i", room_path]
        filter_parts = [
            "[0:a]volume=1.0[vo]",
            f"[1:a]volume={Config.BG_MUSIC_VOLUME},afade=t=out:st={total_dur - 2}:d=2[bg]",
            f"[2:a]volume={Config.ROOM_TONE_VOLUME}[rt]"
        ]
        mix_inputs = "[vo][bg][rt]"
        base_idx = 3

        valid_sfx = []
        for event in sfx_events:
            sfx_path = self._get_sfx_path(event.sfx_type)
            if Path(sfx_path).exists():
                valid_sfx.append((event, sfx_path))

        for i, (event, sfx_path) in enumerate(valid_sfx):
            idx = base_idx + i
            inputs.extend(["-i", sfx_path])
            delay_ms = int(event.timestamp * 1000)
            fade_start = event.timestamp + max(event.duration - 0.2, 0.1)
            filter_parts.append(
                f"[{idx}:a]adelay={delay_ms}|{delay_ms},"
                f"volume={Config.SFX_VOLUME},"
                f"afade=t=out:st={fade_start}:d=0.2"
                f"[sfx{i}]"
            )
            mix_inputs += f"[sfx{i}]"

        num_inputs = 3 + len(valid_sfx)
        filter_parts.append(
            f"{mix_inputs}amix=inputs={num_inputs}:duration=first:normalize=1[aout]"
        )

        cmd = inputs + [
            "-filter_complex", ";".join(filter_parts),
            "-map", "[aout]",
            "-ar", "44100",
            "-ac", "2",
            "-b:a", "192k",
            "-t", str(total_dur),
            output_path
        ]
        run_ffmpeg(cmd)
        return output_path

    def _get_sfx_path(self, sfx_type: str) -> str:
        return str(self.temp_dir / f"sfx_{sfx_type}.mp3")


# =============================================================================
# ASSET AGENT
# =============================================================================

class AssetAgent:
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.temp_dir.mkdir(exist_ok=True)

    def download_broll(self, script: Script) -> List[str]:
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
            url += f"?width={Config.WIDTH}&height={Config.HEIGHT}&seed={random.randint(1, 9999)}&nologo=true"
            path = str(self.temp_dir / f"broll_{i}.jpg")
            success = download_file(url, path, timeout=45)
            if not success:
                path = self._create_placeholder(i)
            paths.append(path)
        return paths

    def _create_placeholder(self, index: int) -> str:
        path = str(self.temp_dir / f"broll_{index}_fallback.jpg")
        c1, c2 = get_gradient_colors()
        geq = build_geq_gradient(Config.WIDTH, Config.HEIGHT, c1, c2)
        run_ffmpeg([
            "-f", "lavfi", "-i",
            f"color=c=black:s={Config.WIDTH}x{Config.HEIGHT}",
            "-vf", geq,
            "-frames:v", "1", path
        ])
        return path

    def download_music(self) -> str:
        path = str(self.temp_dir / "bg_music.mp3")
        if download_file(Config.MUSIC_URL, path, timeout=30):
            return path
        return self._synthetic_music()

    def _synthetic_music(self) -> str:
        path = str(self.temp_dir / "bg_music_synth.mp3")
        run_ffmpeg([
            "-f", "lavfi", "-i",
            "aevalsrc=0.08*sin(2*PI*220*t)|0.08*sin(2*PI*220*t+PI/4):d=65",
            "-ar", "44100", "-ac", "2", "-b:a", "128k", path
        ])
        return path

    def download_sfx(self) -> Dict[str, str]:
        sfx_urls = {
            "whoosh": Config.SFX_WHOOSH,
            "pop": Config.SFX_POP,
            "riser": Config.SFX_RISER
        }
        paths = {}
        for name, url in sfx_urls.items():
            path = str(self.temp_dir / f"sfx_{name}.mp3")
            if not download_file(url, path, timeout=20):
                path = self._synthetic_sfx(name)
            paths[name] = path
        return paths

    def _synthetic_sfx(self, sfx_type: str) -> str:
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
        run_ffmpeg([
            "-f", "lavfi", "-i", f"aevalsrc={expr}:d={dur}",
            "-ar", "44100", "-ac", "2", path
        ])
        return path


# =============================================================================
# VIDEO ENGINE
# =============================================================================

class VideoEngine:
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.font_path = self._find_font()

    def _find_font(self):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return ""

    def render(self, script, word_timings, audio_path, broll_paths, output_path):
        total_duration = get_audio_duration(audio_path)
        segment_timings = self._calc_segment_timings(script, word_timings, total_duration)

        bg_path = self._create_background(total_duration)
        clip_paths = self._create_broll_clips(broll_paths, segment_timings)
        broll_path = self._concat_clips(clip_paths, segment_timings)
        ass_path = self._generate_ass(word_timings, script, segment_timings)

        zoom_expr = self._build_zoom_expr(word_timings)
        shake_expr = self._build_shake_expr(script, segment_timings)
        flash_expr = self._build_flash_expr(script, segment_timings)

        composite_path = self._composite_video(
            bg_path, broll_path, ass_path,
            zoom_expr, shake_expr, flash_expr,
            script, segment_timings, total_duration
        )

        self._final_mix(composite_path, audio_path, output_path)
        return output_path

    def _calc_segment_timings(self, script, word_timings, total_duration):
        segments = [
            script.hook,
            script.fact1,
            script.fact2,
            script.fact3,
            script.outro
        ]
        word_counts = [len(s.text.split()) for s in segments]
        total_words = sum(word_counts) or 1
        timings = []
        current = 0.0
        for i, seg in enumerate(segments):
            d = total_duration * word_counts[i] / total_words
            timings.append({
                "start": current,
                "end": min(current + d, total_duration),
                "duration": min(d, total_duration - current),
                "segment": seg
            })
            current += d
        if timings:
            timings[-1]["end"] = total_duration
            timings[-1]["duration"] = total_duration - timings[-1]["start"]
        return timings

    def _create_background(self, duration):
        output = str(self.temp_dir / "background.mp4")
        c1, c2 = get_gradient_colors()
        geq = build_geq_gradient(Config.WIDTH, Config.HEIGHT, c1, c2)
        run_ffmpeg([
            "-f", "lavfi", "-i",
            f"color=c=black:s={Config.WIDTH}x{Config.HEIGHT}:d={duration}",
            "-vf", geq,
            "-t", str(duration), "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-threads", "0", "-an", output
        ])
        return output

    def _create_broll_clips(self, broll_paths, segment_timings):
        clips = []
        for i, (path, timing) in enumerate(zip(broll_paths, segment_timings)):
            duration = timing["duration"]
            output = str(self.temp_dir / f"clip_{i}.mp4")
            frames = max(int(duration * Config.FPS), 1)
            pan_x = random.choice([-1, 1]) * Config.KEN_BURNS_PAN
            pan_y = random.choice([-1, 1]) * Config.KEN_BURNS_PAN
            zoom_expr = f"1+0.15*on/{frames}"
            x_expr = f"iw/2-(iw/zoom/2)+{pan_x}*on/{frames}"
            y_expr = f"ih/2-(ih/zoom/2)+{pan_y}*on/{frames}"
            vf = (
                f"scale={Config.WIDTH}:{Config.HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={Config.WIDTH}:{Config.HEIGHT},"
                f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
                f"d={frames}:s={Config.WIDTH}x{Config.HEIGHT}:fps={Config.FPS}"
            )
            try:
                run_ffmpeg([
                    "-loop", "1", "-i", path, "-vf", vf,
                    "-t", str(duration), "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-threads", "0", "-an", output
                ])
            except subprocess.CalledProcessError:
                vf2 = (
                    f"scale={Config.WIDTH}:{Config.HEIGHT}:force_original_aspect_ratio=decrease,"
                    f"pad={Config.WIDTH}:{Config.HEIGHT}:(ow-iw)/2:(oh-ih)/2"
                )
                run_ffmpeg([
                    "-loop", "1", "-i", path, "-vf", vf2,
                    "-t", str(duration), "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-threads", "0", "-an", output
                ])
            clips.append(output)
        return clips

    def _concat_clips(self, clip_paths, segment_timings):
        if len(clip_paths) == 1:
            return clip_paths[0]
        output = str(self.temp_dir / "broll_concat.mp4")
        inputs = []
        for path in clip_paths:
            inputs.extend(["-i", path])

        filters = []
        offsets = []
        t = Config.TRANSITION_DURATION
        cumulative = 0.0
        for i in range(len(clip_paths)):
            cumulative += segment_timings[i]["duration"]
            if i < len(clip_paths) - 1:
                offsets.append(max(cumulative - (i + 1) * t, 0.1))

        for i in range(len(clip_paths) - 1):
            out_label = f"[v{i + 1}]"
            if i == 0:
                filters.append(
                    f"[0:v][1:v]xfade=transition=fade:duration={t}:offset={offsets[i]}{out_label}"
                )
            else:
                filters.append(
                    f"[v{i}][{i + 1}:v]xfade=transition=fade:duration={t}:offset={offsets[i]}{out_label}"
                )

        final_label = f"v{len(clip_paths) - 1}"
        cmd = inputs + [
            "-filter_complex", ";".join(filters),
            "-map", f"[{final_label}]",
            "-pix_fmt", "yuv420p", "-c:v", "libx264",
            "-preset", "ultrafast", "-threads", "0", "-an", output
        ]
        run_ffmpeg(cmd)
        return output

    def _generate_ass(self, word_timings, script, segment_timings):
        ass_path = str(self.temp_dir / "subtitles.ass")
        emphasis_set = set()
        for seg in [script.hook, script.fact1, script.fact2, script.fact3, script.outro]:
            for ew in seg.emphasis_words:
                emphasis_set.add(re.sub(r'[^\w]', '', ew).lower())

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
            "Style: Default,Arial Black,70,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "1,0,0,0,100,100,0,0,1,4,0,2,40,40,180,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

    def _ass_events(self, word_timings):
        lines = self._group_words(word_timings)
        events = []
        base_y = 1700
        for idx, line_words in enumerate(lines):
            if not line_words:
                continue
            line_start = line_words[0].start
            line_end = line_words[-1].end + 0.5
            y = base_y - idx * 85
            x = Config.WIDTH // 2

            slide_ms = Config.SLIDE_UP_MS
            move_tag = f"\\move({x},{y + 40},{x},{y},0,{slide_ms})"

            text_parts = []
            for wt in line_words:
                rel_s = int((wt.start - line_start) * 1000)
                rel_e1 = rel_s + Config.BOUNCE_MS
                rel_e2 = rel_s + Config.BOUNCE_MS + 100

                word_text = escape_ass(wt.word)

                if wt.is_emphasis:
                    part = (
                        f"{{\\c&H0000FFFF&\\alpha&HFF&"
                        f"\\t({rel_s},{rel_s + 50},\\alpha&H00&)"
                        f"\\t({rel_s + 50},{rel_e1},\\fscx120\\fscy120)"
                        f"\\t({rel_e1},{rel_e2},\\fscx100\\fscy100)}}"
                        f"{word_text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}} "
                    )
                else:
                    part = (
                        f"{{\\alpha&HFF&\\t({rel_s},{rel_s + 50},\\alpha&H00&)}}"
                        f"{word_text} "
                    )
                text_parts.append(part)

            full_text = "".join(text_parts).strip()
            start_t = to_ass_time(line_start)
            end_t = to_ass_time(line_end)

            events.append(
                f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,"
                f"{{{move_tag}}}{full_text}"
            )
        return "\n".join(events)

    def _group_words(self, word_timings):
        lines, current, char_count = [], [], 0
        for wt in word_timings:
            wlen = len(wt.word)
            if char_count + wlen > 22 or len(current) >= 4:
                if current:
                    lines.append(current)
                current, char_count = [wt], wlen
            else:
                current.append(wt)
                char_count += wlen + 1
        if current:
            lines.append(current)
        return lines

    def _build_zoom_expr(self, word_timings):
        terms = []
        for wt in word_timings:
            if wt.is_emphasis:
                s = round(wt.start, 2)
                e = round(s + Config.ZOOM_DURATION, 2)
                terms.append(f"between(t,{s},{e})")
        if not terms:
            return ""
        return f"1+0.08*({' + '.join(terms)})"

    def _build_shake_expr(self, script, segment_timings):
        terms = []
        for timing in segment_timings:
            if timing["segment"].is_shocking:
                s = round(timing["start"], 2)
                e = round(s + Config.SHAKE_DURATION, 2)
                terms.append(f"between(t,{s},{e})")
        if not terms:
            return ""
        sum_expr = " + ".join(terms)
        x_expr = f"(random(1)-0.5)*4*({sum_expr})"
        y_expr = f"(random(2)-0.5)*4*({sum_expr})"
        return f"{x_expr}:{y_expr}"

    def _build_flash_expr(self, script, segment_timings):
        terms = []
        for i, timing in enumerate(segment_timings):
            if timing["segment"].is_shocking and i > 0:
                s = round(timing["start"] - 0.3, 2)
                e = round(s + Config.FLASH_DURATION, 2)
                if s > 0:
                    terms.append(f"between(t,{s},{e})")
        if not terms:
            return ""
        sum_expr = " + ".join(terms)
        brightness = f"1+1*({sum_expr})"
        contrast = f"1-0.5*({sum_expr})"
        return f"{brightness}:{contrast}"

    def _composite_video(
        self,
        bg_path,
        broll_path,
        ass_path,
        zoom_expr,
        shake_expr,
        flash_expr,
        script,
        segment_timings,
        total_duration
    ):
        output = str(self.temp_dir / "composite.mp4")
        filters = ["[0:v][1:v]overlay=0:0:format=auto[base]"]
        last = "[base]"

        if zoom_expr:
            filters.append(
                f"{last}scale='iw*{zoom_expr}':'ih*{zoom_expr}',"
                f"crop='iw/({zoom_expr})':'ih/({zoom_expr})':"
                f"'(iw-iw/({zoom_expr}))/2':'(ih-ih/({zoom_expr}))/2'[zoomed]"
            )
            last = "[zoomed]"

        if shake_expr:
            x_expr, y_expr = shake_expr.split(":")
            filters.append(
                f"{last}crop='iw-4':'ih-4':'{x_expr}':'{y_expr}'[shaken]"
            )
            last = "[shaken]"

        if flash_expr:
            b_expr, c_expr = flash_expr.split(":")
            filters.append(
                f"{last}eq=brightness='{b_expr}':contrast='{c_expr}'[flashed]"
            )
            last = "[flashed]"

        filters.append(f"{last}ass={ass_path}[subbed]")
        last = "[subbed]"

        gfx = self._build_graphics_filter(script, segment_timings, total_duration)
        if gfx:
            filters.append(f"{last}{gfx}[gfx]")
            last = "[gfx]"

        cmd = [
            "-i", bg_path,
            "-i", broll_path,
            "-filter_complex", ";".join(filters),
            "-map", last,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "25",
            "-threads", "0",
            "-an",
            output
        ]
        run_ffmpeg(cmd)
        return output

    def _build_graphics_filter(self, script, segment_timings, total_duration):
        parts = []
        font_opt = f"fontfile={self.font_path}:" if self.font_path else ""

        bar_w = f"min(t*{Config.WIDTH / total_duration},{Config.WIDTH})"
        parts.append(
            f"drawbox=x=0:y={Config.HEIGHT - Config.PROGRESS_BAR_H}:"
            f"w='{bar_w}':h={Config.PROGRESS_BAR_H}:"
            f"color={Config.PROGRESS_BAR_COLOR}:t=max"
        )

        parts.append(
            f"drawtext={font_opt}text='{Config.CHANNEL_NAME}':"
            f"x=(w-text_w)/2:y={Config.WATERMARK_Y}:"
            f"fontsize=32:fontcolor=white:"
            f"box=1:boxcolor=0x000000@0.6:boxborderw=4"
        )

        parts.append(
            f"drawbox=x='w/2+140':y={Config.WATERMARK_Y + 10}:"
            f"w=12:h=12:color=red:t=max"
        )

        parts.append(
            f"drawbox=x='(w-340)/2':y=180:w=340:h=60:"
            f"color=0xFFD700:t=max:enable='lt(t,3)'"
        )
        parts.append(
            f"drawtext={font_opt}text='DID YOU KNOW?':"
            f"x=(w-text_w)/2:y=192:"
            f"fontsize=30:fontcolor=black:enable='lt(t,3)'"
        )

        for i, timing in enumerate(segment_timings[1:4], 1):
            s = round(timing["start"], 2)
            e = round(timing["end"], 2)
            parts.append(
                f"drawbox=x=50:y=50:w=60:h=60:"
                f"color=0xFF4444:t=max:enable='between(t,{s},{e})'"
            )
            parts.append(
                f"drawtext={font_opt}text='{i}':"
                f"x=50+30-text_w/2:y=50+30-text_h/2:"
                f"fontsize=32:fontcolor=white:"
                f"enable='between(t,{s},{e})'"
            )

        cta_s = round(max(total_duration - Config.CTA_DURATION, 0), 2)
        cta_e = round(cta_s + 0.5, 2)
        box_y = (
            f"if(between(t,{cta_s},{cta_e}),"
            f"h+20-(h+20-(h-200))*(t-{cta_s})/0.5,h-200)"
        )
        parts.append(
            f"drawbox=x='(w-400)/2':y='{box_y}':"
            f"w=400:h=80:color=red:t=max:"
            f"enable='gte(t,{cta_s})'"
        )
        text_y = (
            f"if(between(t,{cta_s},{cta_e}),"
            f"h+20-(h+20-(h-175))*(t-{cta_s})/0.5,h-175)"
        )
        parts.append(
            f"drawtext={font_opt}text='SUBSCRIBE NOW':"
            f"x=(w-text_w)/2:y='{text_y}':"
            f"fontsize=36:fontcolor=white:"
            f"enable='gte(t,{cta_s})'"
        )

        return ",".join(parts)

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


# =============================================================================
# TELEGRAM AGENT
# =============================================================================

class TelegramAgent:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_video(self, video_path: str, thumb_path: str, metadata: Dict) -> bool:
        try:
            size_mb = Path(video_path).stat().st_size / (1024 * 1024)
            if size_mb > 48:
                return self._send_link(metadata, size_mb)

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
                r = requests.post(
                    f"{self.base_url}/sendVideo",
                    data=payload,
                    files=files,
                    timeout=120
                )
                r.raise_for_status()
                return True
        except Exception as e:
            print(f"Telegram send error: {e}")
            return self._send_link(metadata, 0)

    def _send_link(self, metadata: Dict, size_mb: float):
        try:
            text = self._build_caption(metadata)
            if size_mb > 0:
                text += (
                    f"\n\n<i>Video too large ({size_mb:.1f}MB). "
                    f"Download from GitHub Actions artifacts.</i>"
                )
            r = requests.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=30
            )
            return r.status_code == 200
        except Exception as e:
            print(f"Telegram link send error: {e}")
            return False

    def send_failure(self, error_msg: str):
        try:
            text = (
                f"<b>❌ YouTube Agent Failed</b>\n\n"
                f"{error_msg}\n\n"
                f"Check GitHub Actions logs."
            )
            requests.post(
                f"{self.base_url}/sendMessage",
                data={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=30
            )
        except Exception as e:
            print(f"Telegram failure notify error: {e}")

    def _build_caption(self, metadata: Dict) -> str:
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


# =============================================================================
# THUMBNAIL AGENT
# =============================================================================

class ThumbnailAgent:
    def __init__(self):
        self.temp_dir = Path(Config.TEMP_DIR)
        self.font_path = self._find_font()

    def _find_font(self):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return ""

    def generate(self, script: Script, output_path: str) -> str:
        try:
            img = Image.new("RGB", (1280, 720), "#1a1a2e")
            draw = ImageDraw.Draw(img)

            c1, c2 = get_gradient_colors()
            for y in range(720):
                ratio = y / 720
                r = int(int(c1[0:2], 16) * (1 - ratio) + int(c2[0:2], 16) * ratio)
                g = int(int(c1[2:4], 16) * (1 - ratio) + int(c2[2:4], 16) * ratio)
                b = int(int(c1[4:6], 16) * (1 - ratio) + int(c2[4:6], 16) * ratio)
                draw.line([(0, y), (1280, y)], fill=(r, g, b))

            try:
                font_large = ImageFont.truetype(self.font_path, 68)
                font_small = ImageFont.truetype(self.font_path, 32)
            except:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()

            title = script.title[:45] if len(script.title) > 45 else script.title
            words = title.split()
            y_pos = 180
            for word in words[:5]:
                bbox = draw.textbbox((0, 0), word, font=font_large)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                x = (1280 - w) // 2
                for dx in range(-3, 4):
                    for dy in range(-3, 4):
                        draw.text((x + dx, y_pos + dy), word, fill="black", font=font_large)
                draw.text((x, y_pos), word, fill="white", font=font_large)
                y_pos += h + 15

            hook = script.hook.text[:60] + "..." if len(script.hook.text) > 60 else script.hook.text
            bbox = draw.textbbox((0, 0), hook, font=font_small)
            w = bbox[2] - bbox[0]
            x = (1280 - w) // 2
            draw.text((x, 540), hook, fill="#FFD700", font=font_small)

            draw.text((440, 620), "AJEEBOLOGY SHORTS", fill="white", font=font_small)

            img.save(output_path, "JPEG", quality=95)
            return output_path
        except Exception as e:
            print(f"Thumbnail error: {e}")
            return self._fallback_thumbnail(output_path)

    def _fallback_thumbnail(self, output_path: str) -> str:
        try:
            run_ffmpeg([
                "-f", "lavfi", "-i", "color=c=1a1a2e:s=1280x720",
                "-vf",
                "drawtext=text='AJEEBOLOGY SHORTS':fontsize=60:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
                "-frames:v", "1", output_path
            ])
            return output_path
        except Exception as e:
            print(f"Fallback thumbnail error: {e}")
            Path(output_path).touch()
            return output_path


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

class Pipeline:
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
            voice_path, word_timings, voice_dur = asyncio.run(
                self.voice.generate_voice(script)
            )
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
            print("   Mixed audio saved")

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
            print(f"\nPIPELINE FAILED: {error_msg}")
            self.telegram.send_failure(error_msg)
            raise

    def _build_sfx_events(self, script, word_timings):
        events = []
        segments = [
            script.hook,
            script.fact1,
            script.fact2,
            script.fact3,
            script.outro
        ]
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
                riser_time = max(
                    word_timings[word_idx + 2].start - 1.0,
                    seg_start + 0.5
                )
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
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    pipeline = Pipeline()
    pipeline.run()
