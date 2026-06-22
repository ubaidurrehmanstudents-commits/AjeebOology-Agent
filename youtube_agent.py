import os
import json
import random
import time
import requests
import asyncio
import edge_tts
import subprocess
import re
from PIL import Image, ImageDraw, ImageFont
from pydub import AudioSegment
from pydub.silence import split_on_silence
from dataclasses import dataclass, field
from typing import List, Dict, Any

class Config:
    VERSION = "1.0"
    OUTPUT_DIR = "output"
    TEMP_DIR = "temp"
    VIDEO_PATH = os.path.join(OUTPUT_DIR, "video.mp4")
    THUMB_PATH = os.path.join(OUTPUT_DIR, "thumbnail.jpg")
    META_PATH = os.path.join(OUTPUT_DIR, "metadata.json")
    VOICE_PATH = os.path.join(TEMP_DIR, "voice_clean.mp3")
    AUDIO_PATH = os.path.join(TEMP_DIR, "final_audio.mp3")
    ASS_PATH = os.path.join(TEMP_DIR, "subtitles.ass")
    BG_VIDEO_PATH = os.path.join(TEMP_DIR, "bg_video.mp4")
    FX_VIDEO_PATH = os.path.join(TEMP_DIR, "fx_video.mp4")
    PARTICLE_PATH = os.path.join(TEMP_DIR, "particles.png")
    
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 30
    DURATION = 58
    
    GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
    GROQ_MODEL = "llama-3.3-70b-versatile"
    TAVILY_URL = "https://api.tavily.com/search"
    TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"
    
    VOICE = "hi-IN-MadhurNeural"
    VOICE_RATE = "+15%"
    FONT_NAME = "Arial"
    CHANNEL_NAME = "AJEEBOLOGY SHORTS"
    CATEGORIES = ["Psychology Facts", "Space Secrets", "Weird Facts"]
def ensure_dirs():
    if not os.path.exists(Config.OUTPUT_DIR):
        os.makedirs(Config.OUTPUT_DIR)
    if not os.path.exists(Config.TEMP_DIR):
        os.makedirs(Config.TEMP_DIR)

def format_time_ass(seconds):
    ms = int((seconds - int(seconds)) * 100)
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h}:{m:02d}:{s:02d}.{ms:02d}"

def escape_ass_text(text):
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    return text

def clean_text(text):
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

@dataclass
class Segment:
    seg_type: str
    text: str
    words: List[str] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0
    image_path: str = ""
    sfx: str = ""
    is_shocking: bool = False

@dataclass
class VideoData:
    title: str
    description: str
    tags: List[str]
    segments: List[Segment]
class ScriptAgent:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def generate_script(self, context, category):
        prompt = f"Context: {context}\n"
        prompt += "Create a viral YouTube Shorts script in Hinglish (Roman Hindi + English).\n"
        prompt += "Niche: " + category + ".\n"
        prompt += "Format as JSON with keys: title, description, tags, segments (array of 5 objects).\n"
        prompt += "Segments must be: hook, fact1, fact2, fact3, outro.\n"
        prompt += "Mark emphasis words with [brackets].\n"
        prompt += "Keep total speaking time under 55 seconds.\n"
        prompt += "Outro must loop back to the hook concept.\n"
        prompt += "Output ONLY valid JSON, no markdown."

        payload = {
            "model": Config.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post(Config.GROQ_URL, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            print(f"Script generation failed: {e}")
            return None
        class VoiceAgent:
    def __init__(self):
        self.voice = Config.VOICE
        self.rate = Config.VOICE_RATE
        self.timings = []

    def generate_audio(self, segments):
        full_text = " ".join([s.text for s in segments])
        tts_text = full_text.replace("[", "").replace("]", "")
        asyncio.run(self._fetch_audio(tts_text))
        return self._trim_silence()

    async def _fetch_audio(self, text):
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        with open(Config.VOICE_PATH, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start_ms = chunk["offset"] / 10000.0
                    duration_ms = chunk["duration"] / 10000.0
                    self.timings.append({
                        "start": start_ms,
                        "end": start_ms + duration_ms,
                        "text": chunk["text"]
                    })

    def _trim_silence(self):
        audio = AudioSegment.from_mp3(Config.VOICE_PATH)
        new_audio = AudioSegment.silent(duration=50)
        new_timings = []
        
        for t in self.timings:
            word_audio = audio[int(t["start"]):int(t["end"])]
            new_audio += word_audio
            new_audio += AudioSegment.silent(duration=30)
            new_start = (len(new_audio) - len(word_audio) - 30) / 1000.0
            new_end = (len(new_audio) - 30) / 1000.0
            new_timings.append({
                "start": new_start,
                "end": new_end,
                "text": t["text"]
            })
            
        new_audio.export(Config.VOICE_PATH, format="mp3")
        return new_timings, len(new_audio) / 1000.0
            def mix_audio(self, segments, duration, music_path, sfx_paths):
        voice = AudioSegment.from_mp3(Config.VOICE_PATH)
        
        try:
            music = AudioSegment.from_mp3(music_path)
            if len(music) < duration * 1000:
                music = music * (int(duration * 1000 / len(music)) + 1)
            music = music[:int(duration * 1000)]
            music = music - 18
        except:
            music = AudioSegment.silent(duration=int(duration * 1000))
            
        room_tone = AudioSegment.silent(duration=int(duration * 1000))
        mixed = voice.overlay(music).overlay(room_tone)
        
        for seg in segments:
            if seg.sfx and seg.sfx in sfx_paths:
                try:
                    sfx = AudioSegment.from_mp3(sfx_paths[seg.sfx])
                    sfx = sfx - 8
                    mixed = mixed.overlay(sfx, position=int(seg.start * 1000))
                except:
                    pass
                    
        mixed = mixed[:int(duration * 1000)]
        mixed.export(Config.AUDIO_PATH, format="mp3")
        return Config.AUDIO_PATH

class AssetAgent:
    def __init__(self):
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def fetch_broll(self, prompt, idx):
        enhanced = "cinematic lighting, highly detailed, 8k resolution, vertical aspect ratio, " + prompt
        url = "https://image.pollinations.ai/prompt/" + requests.utils.quote(enhanced) + "?width=1080&height=1920"
        path = os.path.join(Config.TEMP_DIR, f"broll_{idx}.jpg")
        try:
            r = requests.get(url, headers=self.headers, timeout=60)
            with open(path, "wb") as f:
                f.write(r.content)
            return path
        except:
            return self._create_fallback_img(prompt, idx)

    def _create_fallback_img(self, text, idx):
        img = Image.new('RGB', (1080, 1920), color=(20, 20, 30))
        d = ImageDraw.Draw(img)
        d.text((540, 960), text[:50], fill=(255, 255, 255), anchor="mm")
        path = os.path.join(Config.TEMP_DIR, f"broll_{idx}.jpg")
        img.save(path)
        return path

    def download_audio(self, url, path):
        try:
            r = requests.get(url, headers=self.headers, timeout=30)
            with open(path, "wb") as f:
                f.write(r.content)
            return path
        except:
            return self._generate_silence(path)

    def _generate_silence(self, path):
        silence = AudioSegment.silent(duration=10000)
        silence.export(path, format="mp3")
        return path

class VideoEngine:
    def __init__(self, video_data, timings, audio_path):
        self.data = video_data
        self.timings = timings
        self.audio_path = audio_path
        self.duration = 0
        for s in video_data.segments:
            self.duration += (s.end - s.start)
        if self.duration <= 0:
            self.duration = Config.DURATION

    def render(self):
        self._build_bg_video()
        self._generate_particles()
        self._render_subtitles()
        
        cmd = [
            "ffmpeg", "-y",
            "-i", Config.BG_VIDEO_PATH,
            "-i", Config.PARTICLE_PATH,
            "-i", Config.AUDIO_PATH,
            "-vf", self._build_filtergraph(),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            "-t", str(self.duration),
            Config.VIDEO_PATH
        ]
        subprocess.run(cmd, check=True)
        return Config.VIDEO_PATH
            def _build_bg_video(self):
        inputs = []
        for seg in self.data.segments:
            if seg.image_path and os.path.exists(seg.image_path):
                inputs.extend(["-i", seg.image_path])
                
        if not inputs:
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=" + str(self.duration), "-c:v", "libx264", Config.BG_VIDEO_PATH]
            subprocess.run(cmd, check=True)
            return
            
        filter_parts = []
        num_segs = len(self.data.segments)
        seg_dur = self.duration / num_segs
        
        for i in range(num_segs):
            f = f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
            f += f",zoompan=z='min(zoom+0.0015,1.15)':d={int(seg_dur*30)}:s=1080x1920:fps=30[v{i}]"
            filter_parts.append(f)
            
        concat_str = "".join([f"[v{i}]" for i in range(num_segs)])
        concat_str += f"concat=n={num_segs}:v=1:a=0[outv]"
        filter_parts.append(concat_str)
        
        cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filter_parts), "-map", "[outv]", "-c:v", "libx264", "-preset", "ultrafast", "-t", str(self.duration), Config.BG_VIDEO_PATH]
        subprocess.run(cmd, check=True)

    def _generate_particles(self):
        img = Image.new("RGBA", (Config.WIDTH, Config.HEIGHT), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for _ in range(50):
            x = random.randint(0, Config.WIDTH)
            y = random.randint(0, Config.HEIGHT)
            r = random.randint(2, 6)
            alpha = random.randint(50, 200)
            d.ellipse((x, y, x+r, y+r), fill=(255, 255, 255, alpha))
        img.save(Config.PARTICLE_PATH)

    def _render_subtitles(self):
        with open(Config.ASS_PATH, "w", encoding="utf-8") as f:
            f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n")
            f.write("[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
            f.write("Style: Default,Arial Black,70,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,2,2,40,40,80,1\n")
            f.write("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
            
            word_idx = 0
            for seg in self.data.segments:
                orig_text = seg.text.replace("[", "").replace("]", "")
                orig_words = orig_text.split()
                
                for ow in orig_words:
                    if word_idx >= len(self.timings):
                        break
                    t = self.timings[word_idx]
                    word_idx += 1
                    
                    start = format_time_ass(t["start"])
                    end = format_time_ass(t["end"])
                    text = escape_ass_text(t["text"])
                    
                    if f"[{ow}]" in seg.text:
                        text = "{\\c1&H00FFFF&\\fscx120\\fscy120}" + text + "{\\r}"
                    else:
                        text = "{\\move(540,1000,540,960,0,100)\\fad(50,50)}" + text
                        
                    f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

    def _build_filtergraph(self):
        filters = []
        filters.append("[0:v][1:v]overlay=0:0[bg]")
        filters.append(f"[bg]subtitles={Config.ASS_PATH}[sub]")
        filters.append(f"[sub]drawbox=x=0:y=1880:w='t/{self.duration}*1080':h=20:color=cyan@0.8[pg]")
        filters.append("[pg]drawtext=text='AJEEBOLOGY SHORTS':x=(w-text_w)/2:y=50:fontcolor=white:fontsize=40:box=1:boxcolor=red@0.5:boxborderw=10[wm]")
        filters.append("[wm]zoompan=z='min(zoom+0.0005,1.05)':d=1:s=1080x1920:fps=30[outv]")
        return ";".join(filters)
    class ThumbnailGenerator:
    @staticmethod
    def generate(title, thumb_path):
        img = Image.new('RGB', (1280, 720), color=(10, 10, 20))
        d = ImageDraw.Draw(img)
        for i in range(720):
            r = int(10 + (i / 720) * 40)
            g = int(10 + (i / 720) * 20)
            b = int(20 + (i / 720) * 80)
            d.line([(0, i), (1280, i)], fill=(r, g, b))
        try:
            font = ImageFont.truetype("arial.ttf", 80)
        except:
            font = ImageFont.load_default()
        d.text((640, 360), title[:40], fill=(255, 255, 0), font=font, anchor="mm", align="center")
        img.save(thumb_path)

class TelegramAgent:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_video(self, video_path, thumb_path, metadata):
        if not os.path.exists(video_path):
            return
        with open(video_path, 'rb') as v, open(thumb_path, 'rb') as t:
            files = {'video': v, 'thumbnail': t}
            data = {
                'chat_id': self.chat_id,
                'caption': self._format_caption(metadata),
                'parse_mode': 'HTML'
            }
            r = requests.post(f"{self.base_url}/sendVideo", files=files, data=data, timeout=120)
        if r.status_code != 200:
            self.send_text(f"Failed to send video. Size might be >50MB.\nStatus: {r.text}")

    def send_text(self, text):
        requests.post(f"{self.base_url}/sendMessage", data={'chat_id': self.chat_id, 'text': text, 'parse_mode': 'HTML'})

    def _format_caption(self, metadata):
        text = f"🎬 <b>{metadata['title']}</b>\n\n"
        text += f"📝 {metadata['description']}\n\n"
        text += " ".join([f"#{t}" for t in metadata['tags']])
        return text[:1024]

class Pipeline:
    def __init__(self):
        ensure_dirs()
        self.researcher = ResearchAgent(os.getenv("TAVILY_API_KEY", ""))
        self.scripter = ScriptAgent(os.getenv("GROQ_API_KEY", ""))
        self.voice = VoiceAgent()
        self.assets = AssetAgent()
        self.telegram = TelegramAgent(os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""))

    def run(self):
        category = random.choice(Config.CATEGORIES)
        print(f"Starting pipeline for: {category}")
        
        context = self.researcher.search(category + " interesting facts")
        script_data = self.scripter.generate_script(context, category)
        
        if not script_data:
            script_data = self.scripter.get_fallback_script(category)
            
        segments = []
        for s in script_data["segments"]:
            segments.append(Segment(seg_type=s["seg_type"], text=s["text"]))
            
        print("Generating Voice...")
        timings, duration = self.voice.generate_audio(segments)
        
        word_idx = 0
        for seg in segments:
            orig_words = seg.text.replace("[", "").replace("]", "").split()
            seg_len = len(orig_words)
            if word_idx < len(timings):
                seg.start = timings[word_idx]["start"]
                if word_idx + seg_len - 1 < len(timings):
                    seg.end = timings[word_idx + seg_len - 1]["end"]
                else:
                    seg.end = timings[-1]["end"]
            word_idx += seg_len
            
            if seg.seg_type in ["fact1", "fact2", "fact3"]:
                seg.sfx = "pop"
            elif seg.seg_type == "hook":
                seg.sfx = "riser"
            else:
                seg.sfx = "whoosh"

        total_dur = segments[-1].end + 2.0
        
        print("Fetching Assets...")
        for i, seg in enumerate(segments):
            prompt = seg.text.replace("[", "").replace("]", "")
            seg.image_path = self.assets.fetch_broll(prompt, i)
            
        sfx_url = "https://www.soundjay.com/buttons/sounds/button-3.mp3"
        sfx_paths = {
            "pop": self.assets.download_audio(sfx_url, os.path.join(Config.TEMP_DIR, "pop.mp3")),
            "riser": self.assets.download_audio(sfx_url, os.path.join(Config.TEMP_DIR, "riser.mp3")),
            "whoosh": self.assets.download_audio(sfx_url, os.path.join(Config.TEMP_DIR, "whoosh.mp3"))
        }
        music_path = self.assets.download_audio(sfx_url, os.path.join(Config.TEMP_DIR, "music.mp3"))

        print("Mixing Audio...")
        audio_path = self.voice.mix_audio(segments, total_dur, music_path, sfx_paths)
        
        print("Rendering Video...")
        video_data = VideoData(
            title=script_data["title"],
            description=script_data["description"],
            tags=script_data["tags"],
            segments=segments
        )
        engine = VideoEngine(video_data, timings, audio_path)
        engine.duration = total_dur
        video_path = engine.render()
        
        print("Generating Thumbnail...")
        ThumbnailGenerator.generate(video_data.title, Config.THUMB_PATH)
        
        print("Saving Metadata...")
        with open(Config.META_PATH, "w") as f:
            json.dump({
                "title": video_data.title,
                "description": video_data.description,
                "tags": video_data.tags
            }, f, indent=4)
            
        print("Sending to Telegram...")
        self.telegram.send_video(video_path, Config.THUMB_PATH, {
            "title": video_data.title,
            "description": video_data.description,
            "tags": video_data.tags
        })
        print("Done!")

if __name__ == "__main__":
    try:
        pipeline = Pipeline()
        pipeline.run()
    except Exception as e:
        print(f"Pipeline crashed: {e}")
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if token and chat_id:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={'chat_id': chat_id, 'text': f"❌ Agent Crashed: {e}"})
