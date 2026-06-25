#!/usr/bin/env python3
import os
import re
import json
import math
import time
import base64
import random
import shutil
import string
import tempfile
import traceback
import textwrap
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps


APP_NAME = "Ajeebology Shorts"
ROOT = Path.cwd()
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = OUTPUT_DIR / "cache"
ASSETS_DIR = OUTPUT_DIR / "assets"
LOG_FILE = OUTPUT_DIR / "run.log"
STATE_FILE = OUTPUT_DIR / "state.json"

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
DEFAULT_STYLE = "Hinglish, punchy, high-retention, cinematic, short-form"
VIDEO_W = 1080
VIDEO_H = 1920
FPS = 30
TARGET_DURATION_MIN = 55
TARGET_DURATION_MAX = 65
MAX_RETRIES = 4
HTTP_TIMEOUT = 20
SAFE_MARGIN = 0.92
TEMPO = 1.0

PREFERRED_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]

SESSION = requests.Session()


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""


@dataclass
class ScriptPlan:
    topic: str
    hook: str
    title: str
    description: str
    tags: List[str]
    hashtags: List[str]
    category: str
    sections: List[str]
    sources: List[ResearchSource]


@dataclass
class ScenePlan:
    index: int
    text: str
    duration: float
    visual_type: str
    asset_query: str
    emphasis: str


@dataclass
class RunResult:
    topic: str
    title: str
    duration: float
    video_path: str
    thumbnail_path: str
    metadata_path: str
    sources: List[ResearchSource]
    runtime_stats: Dict[str, Any]


def ensure_dirs() -> None:
    for p in [OUTPUT_DIR, CACHE_DIR, ASSETS_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    ensure_dirs()
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "
")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_slug(text: str, limit: int = 80) -> str:
    text = re.sub(r"[^a-zA-Z0-9s-_.]+", "", text).strip().lower()
    text = re.sub(r"s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:limit].strip("-") or "short"


def clamp(v: float, a: float, b: float) -> float:
    return max(a, min(b, v))


def now_ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def jitter(a: float, b: float) -> float:
    return random.uniform(a, b)


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def run_cmd(cmd: List[str], timeout: Optional[int] = None, check: bool = True) -> subprocess.CompletedProcess:
    log("RUN " + " ".join(cmd))
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=check,
    )


def ffmpeg_exists() -> bool:
    return which("ffmpeg") is not None


def ffprobe_exists() -> bool:
    return which("ffprobe") is not None


def http_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    data: Optional[Any] = None,
    timeout: int = HTTP_TIMEOUT,
    retries: int = MAX_RETRIES,
) -> requests.Response:
    last_err = None
    for attempt in range(retries):
        try:
            resp = SESSION.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                data=data,
                timeout=timeout,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"Retryable HTTP {resp.status_code}: {resp.text[:300]}", response=resp)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            sleep_s = (1.5 ** attempt) + random.uniform(0, 0.6)
            log(f"HTTP retry {attempt + 1}/{retries}: {e}")
            time.sleep(sleep_s)
    raise RuntimeError(f"HTTP request failed after retries: {last_err}")


def groq_chat(messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 1200) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY missing")
    payload = {
        "model": DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = http_request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json_data=payload,
        timeout=60,
    )
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        raise RuntimeError(f"Unexpected Groq response: {data}")


def tavily_search(query: str, max_results: int = 5) -> List[ResearchSource]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_domains": [],
        "exclude_domains": [],
    }
    resp = http_request(
        "POST",
        "https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        json_data=payload,
        timeout=45,
    )
    data = resp.json()
    out = []
    for item in data.get("results", [])[:max_results]:
        out.append(
            ResearchSource(
                title=item.get("title", "").strip(),
                url=item.get("url", "").strip(),
                snippet=item.get("content", "").strip()[:300],
                provider="tavily",
            )
        )
    return out


def pexels_search(query: str, per_page: int = 5) -> List[Dict[str, Any]]:
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        return []
    resp = http_request(
        "GET",
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=45,
    )
    return resp.json().get("videos", [])


def unsplash_search(query: str, per_page: int = 5) -> List[Dict[str, Any]]:
    access_key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    if not access_key:
        return []
    resp = http_request(
        "GET",
        "https://api.unsplash.com/search/photos",
        headers={"Authorization": f"Client-ID {access_key}"},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=45,
    )
    return resp.json().get("results", [])


def telegram_send_document(path: Path, caption: str = "", filename: Optional[str] = None) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram secrets missing"}
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with path.open("rb") as f:
        files = {"document": (filename or path.name, f)}
        data = {"chat_id": chat_id, "caption": caption[:1000]}
        resp = SESSION.post(url, data=data, files=files, timeout=90)
    try:
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {"ok": False, "error": resp.text[:500]}


def telegram_send_photo(path: Path, caption: str = "") -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram secrets missing"}
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    with path.open("rb") as f:
        files = {"photo": (path.name, f)}
        data = {"chat_id": chat_id, "caption": caption[:1024]}
        resp = SESSION.post(url, data=data, files=files, timeout=90)
    try:
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {"ok": False, "error": resp.text[:500]}


def pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for fp in PREFERRED_FONTS:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_multiline_center(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.ImageFont, fill: Tuple[int, int, int], stroke_fill: Tuple[int, int, int] = (0, 0, 0), stroke_width: int = 6, max_width: int = 900, line_spacing: int = 8) -> int:
    lines = []
    for para in text.split("
"):
        lines.extend(wrap_text(draw, para, font, max_width))
    total_h = 0
    heights = []
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        h = bb[3] - bb[1]
        heights.append(h)
        total_h += h
    total_h += line_spacing * max(0, len(lines) - 1)
    cy = y - total_h // 2
    for line, h in zip(lines, heights):
        bb = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        w = bb[2] - bb[0]
        x = (VIDEO_W - w) // 2
        draw.text((x, cy), line, font=font, fill=fill, stroke_fill=stroke_fill, stroke_width=stroke_width)
        cy += h + line_spacing
    return total_h


def duration_to_frames(seconds: float) -> int:
    return max(1, int(round(seconds * FPS)))


def clean_text(s: str) -> str:
    s = re.sub(r"s+", " ", s).strip()
    return s.replace("```", "").strip()


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])s+", clean_text(text))
    return [p.strip() for p in parts if p.strip()]


def estimate_words_per_second(text: str, duration: float) -> float:
    words = max(1, len(text.split()))
    return words / max(1.0, duration)


def ensure_ffmpeg_or_fail() -> None:
    if not ffmpeg_exists() or not ffprobe_exists():
        raise RuntimeError("ffmpeg/ffprobe not available in runner")


def load_state() -> Dict[str, Any]:
    return read_json(STATE_FILE, {})


def save_state(state: Dict[str, Any]) -> None:
    write_json(STATE_FILE, state)


def serialize_sources(sources: List[ResearchSource]) -> List[Dict[str, str]]:
    return [asdict(s) for s in sources]


def pick_topic(state: Dict[str, Any]) -> str:
    topics = [
        "Why your brain ignores obvious things",
        "The weirdest space fact people still get wrong",
        "A bizarre world fact that feels fake but is real",
    ]
    used = set(state.get("used_topics", []))
    for t in topics:
        if t not in used:
            used.add(t)
            state["used_topics"] = list(used)[-30:]
            save_state(state)
            return t
    choice = random.choice(topics)
    return choice


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default

def extract_json_block(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?s*", "", text)
        text = re.sub(r"s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"{.*}", text, re.S)
        if m:
            return json.loads(m.group(0))
        m = re.search(r"[.*]", text, re.S)
        if m:
            return json.loads(m.group(0))
    raise ValueError("Could not parse JSON")


def choose_category(topic: str) -> str:
    t = topic.lower()
    if any(k in t for k in ["brain", "mind", "psychology", "memory", "behavior"]):
        return "22"
    if any(k in t for k in ["space", "planet", "universe", "star", "moon", "mars"]):
        return "28"
    return "24"


def build_research_query(topic: str) -> str:
    return f"{topic} facts explained briefly with reliable sources"


def assemble_research(topic: str) -> List[ResearchSource]:
    sources: List[ResearchSource] = []
    try:
        sources.extend(tavily_search(build_research_query(topic), max_results=5))
    except Exception as e:
        log(f"Tavily search failed: {e}")
    if not sources:
        try:
            alt_queries = [
                topic,
                f"{topic} scientific facts",
                f"{topic} explanation",
            ]
            for q in alt_queries:
                try:
                    results = tavily_search(q, max_results=3)
                    sources.extend(results)
                    if sources:
                        break
                except Exception:
                    continue
        except Exception:
            pass
    dedup = []
    seen = set()
    for s in sources:
        key = (s.url or s.title).strip().lower()
        if key and key not in seen:
            seen.add(key)
            dedup.append(s)
    return dedup[:6]


def default_script_plan(topic: str, sources: List[ResearchSource]) -> ScriptPlan:
    title = f"{topic} | 3 Shocking Facts"
    hook = "Ruko... ye fact literally mind-blowing hai."
    description = (
        f"{topic} in Hinglish, fast-paced Shorts format. "
        f"Sources: " + ", ".join(s.title for s in sources[:3]) if sources else f"{topic} in Hinglish, fast-paced Shorts format."
    )
    tags = ["facts", "shorts", "hinglish", "psychology", "space", "weird facts", "ajeeobology"]
    hashtags = ["#shorts", "#facts", "#hinglish", "#viral", "#ajeeobology"]
    sections = [
        "Hook: Ye fact aapke dimaag ko confuse kar dega.",
        "Fact 1: Short, sharp, surprising statement.",
        "Fact 2: Another twist with simple explanation.",
        "Fact 3: Final punch with retention twist.",
        "Closer: Ab aap ye dekh ke normal feel nahi karoge.",
    ]
    return ScriptPlan(
        topic=topic,
        hook=hook,
        title=title,
        description=description,
        tags=tags,
        hashtags=hashtags,
        category=choose_category(topic),
        sections=sections,
        sources=sources,
    )


def generate_script_plan(topic: str) -> ScriptPlan:
    sources = assemble_research(topic)
    source_lines = "
".join(
        f"- {s.title} | {s.url} | {s.snippet}" for s in sources[:6]
    ) or "- No research sources found."
    prompt = f"""
You are writing a YouTube Shorts script for a channel named Ajeebology Shorts.

Rules:
- Language: Hinglish.
- Target duration: 55-65 seconds.
- Tone: punchy, energetic, retention-first, cinematic, no fluff.
- Topic: {topic}
- Must be accurate, concise, and entertaining.
- Structure: hook, 3-5 fast facts, strong outro.
- Avoid generic lines.
- Avoid fake certainty.
- Output STRICT JSON only with keys:
  title, hook, description, tags, hashtags, category, sections
- sections must be an array of 5 to 7 short scene-ready lines.
- title under 70 chars.
- description under 300 chars.
- tags array of 8 to 15 strings.
- hashtags array of 4 to 8 strings.
- category must be a YouTube category id as a string, preferably 22, 28, 24, or 27 based on fit.
- Use these sources only as reference:
{source_lines}
""".strip()
    try:
        raw = groq_chat(
            [
                {"role": "system", "content": "Return only valid JSON. No markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1200,
        )
        data = extract_json_block(raw)
        sections = [clean_text(x) for x in data.get("sections", []) if clean_text(str(x))]
        if not sections:
            raise ValueError("No sections")
        return ScriptPlan(
            topic=topic,
            hook=clean_text(data.get("hook", sections if sections else "")),
            title=clean_text(data.get("title", f"{topic} | Facts")),
            description=clean_text(data.get("description", ""))[:300],
            tags=[clean_text(t) for t in data.get("tags", []) if clean_text(str(t))][:15],
            hashtags=[clean_text(h) for h in data.get("hashtags", []) if clean_text(str(h))][:8],
            category=str(data.get("category", choose_category(topic))),
            sections=sections[:7],
            sources=sources,
        )
    except Exception as e:
        log(f"Script generation failed, using fallback: {e}")
        return default_script_plan(topic, sources)


def make_scene_plan(plan: ScriptPlan) -> List[ScenePlan]:
    base_lines = []
    for s in plan.sections:
        base_lines.append(clean_text(s))
    if plan.hook and (not base_lines or plan.hook not in base_lines):
        base_lines = [clean_text(plan.hook)] + base_lines
    while len(base_lines) < 6:
        base_lines.append("Ye part retention ke liye intentionally fast hai.")
    scene_types = ["footage", "footage", "graphic", "zoom", "footage", "motion"]
    queries = [
        "abstract background dark",
        "person thinking close up",
        "space stars nebula",
        "surprised reaction",
        "microscope macro",
        "cinematic motion blur",
    ]
    out: List[ScenePlan] = []
    total = len(base_lines)
    durations = distribute_durations(total, TARGET_DURATION_MIN + 2)
    for i, text in enumerate(base_lines[:7]):
        out.append(
            ScenePlan(
                index=i,
                text=text,
                duration=durations[i],
                visual_type=scene_types[i % len(scene_types)],
                asset_query=queries[i % len(queries)],
                emphasis=random.choice(["highlight", "zoom", "shake", "underline", "pulse"]),
            )
        )
    return out


def distribute_durations(n: int, target_seconds: float) -> List[float]:
    if n <= 0:
        return []
    mins, maxs = 6.5, 11.0
    raw = [random.uniform(mins, maxs) for _ in range(n)]
    total = sum(raw)
    scale = target_seconds / total if total > 0 else 1.0
    vals = [clamp(v * scale, 5.5, 12.0) for v in raw]
    diff = target_seconds - sum(vals)
    vals[-1] = clamp(vals[-1] + diff, 5.5, 14.0)
    return vals


def build_prompt_for_narration(plan: ScriptPlan, scenes: List[ScenePlan]) -> str:
    joined = "
".join(f"{i+1}. {s.text}" for i, s in enumerate(scenes))
    return f"""
Create a natural Hinglish voiceover for a YouTube Short.

Requirements:
- 55 to 65 seconds total.
- Clear, fast, retention-driven.
- Simple words, high energy.
- Keep sentence length short.
- Do not mention source names.
- No bullet points in final narration.
- Return STRICT JSON only:
  {{
    "narration": "...",
    "subtitle_chunks": [
      {{"text":"...", "seconds":2.5}},
      ...
    ]
  }}

Scene beats:
{joined}
""".strip()


def generate_narration_and_captions(plan: ScriptPlan, scenes: List[ScenePlan]) -> Tuple[str, List[Dict[str, Any]]]:
    prompt = build_prompt_for_narration(plan, scenes)
    try:
        raw = groq_chat(
            [
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.75,
            max_tokens=1200,
        )
        data = extract_json_block(raw)
        narration = clean_text(data.get("narration", ""))
        chunks = data.get("subtitle_chunks", [])
        if not narration or not isinstance(chunks, list):
            raise ValueError("Invalid narration response")
        fixed = []
        for ch in chunks:
            txt = clean_text(str(ch.get("text", "")))
            sec = safe_float(ch.get("seconds", 2.5), 2.5)
            if txt:
                fixed.append({"text": txt, "seconds": clamp(sec, 0.8, 5.0)})
        if not fixed:
            raise ValueError("No subtitle chunks")
        return narration, fixed
    except Exception as e:
        log(f"Narration generation failed, using fallback: {e}")
        narration = "Aaj ka fact sach mein ajeeb hai. Pehle socho, phir suno. Dimaag thoda twist hoga, kyunki ye normal nahi hai. Fact one fast hai. Fact two aur bhi crazy hai. Aur end mein jo turn aayega, woh aapko yaad rahega."
        chunks = [
            {"text": "Aaj ka fact sach mein ajeeb hai.", "seconds": 3.0},
            {"text": "Pehle socho, phir suno.", "seconds": 2.4},
            {"text": "Dimaag thoda twist hoga.", "seconds": 2.7},
            {"text": "Fact one fast hai.", "seconds": 2.2},
            {"text": "Fact two aur bhi crazy hai.", "seconds": 2.8},
            {"text": "End mein twist yaad rahega.", "seconds": 3.2},
        ]
        return narration, chunks

def make_background(size: Tuple[int, int], idx: int, total: int, variant: str) -> Image.Image:
    w, h = size
    base_colors = [
        (9, 14, 28),
        (28, 10, 42),
        (10, 34, 46),
        (40, 20, 10),
        (12, 20, 60),
    ]
    c1 = base_colors[idx % len(base_colors)]
    c2 = base_colors[(idx + 2) % len(base_colors)]
    img = Image.new("RGB", size, c1)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        for x in range(w):
            jitter_c = (x * 13 + y * 7 + idx * 29) % 24
            px[x, y] = (
                clamp(r + jitter_c, 0, 255),
                clamp(g + jitter_c // 2, 0, 255),
                clamp(b + jitter_c // 3, 0, 255),
            )
    if variant == "motion":
        overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        for i in range(12):
            x0 = int((i / 12) * w) - 120
            d.ellipse((x0, -40, x0 + 260, 220), fill=(255, 255, 255, 12))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    return img


def add_vignette(img: Image.Image) -> Image.Image:
    w, h = img.size
    overlay = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(overlay)
    for i in range(60):
        alpha = int(255 * (i / 60) ** 2 * 0.85)
        d.ellipse((-i * 8, -i * 8, w + i * 8, h + i * 8), outline=alpha, width=12)
    overlay = overlay.filter(ImageFilter.GaussianBlur(35))
    rgb = img.convert("RGB")
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(dark, rgb, overlay)


def create_scene_frame(scene: ScenePlan, idx: int, total: int, narration_text: str) -> Image.Image:
    bg = make_background((VIDEO_W, VIDEO_H), idx, total, scene.visual_type)
    bg = bg.filter(ImageFilter.GaussianBlur(0.2))
    if scene.visual_type == "footage":
        bg = ImageOps.autocontrast(bg)
    elif scene.visual_type == "graphic":
        bg = bg.transpose(Image.FLIP_LEFT_RIGHT)
    elif scene.visual_type == "zoom":
        bg = bg.resize((int(VIDEO_W * 1.06), int(VIDEO_H * 1.06)), Image.Resampling.LANCZOS)
        crop_x = (bg.width - VIDEO_W) // 2
        crop_y = (bg.height - VIDEO_H) // 2
        bg = bg.crop((crop_x, crop_y, crop_x + VIDEO_W, crop_y + VIDEO_H))
    bg = add_vignette(bg)
    frame = bg.convert("RGBA")
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    title_font = pick_font(58, bold=True)
    body_font = pick_font(46)
    tiny_font = pick_font(28)
    accent = [(255, 201, 77), (109, 240, 255), (255, 115, 160)][idx % 3]

    top_bar_h = 180
    d.rounded_rectangle((40, 42, VIDEO_W - 40, 160), radius=38, fill=(0, 0, 0, 130))
    d.rounded_rectangle((48, 50, VIDEO_W - 48, 152), radius=34, outline=accent, width=4)
    d.text((78, 78), f"{APP_NAME}", font=title_font, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((78, 132), f"Beat {idx + 1}/{total}", font=tiny_font, fill=accent)

    box_y0 = 1400
    d.rounded_rectangle((48, box_y0, VIDEO_W - 48, 1750), radius=44, fill=(0, 0, 0, 160))
    d.rounded_rectangle((62, box_y0 + 14, VIDEO_W - 62, 1736), radius=34, outline=(255, 255, 255, 50), width=2)

    inner_y = box_y0 + 52
    draw_multiline_center(
        d,
        scene.text,
        inner_y + 86,
        body_font,
        fill=(255, 255, 255),
        stroke_fill=(0, 0, 0),
        stroke_width=5,
        max_width=900,
        line_spacing=12,
    )

    prog_w = int((VIDEO_W - 120) * ((idx + 1) / max(1, total)))
    d.rounded_rectangle((60, 1770, VIDEO_W - 60, 1800), radius=14, fill=(255, 255, 255, 38))
    d.rounded_rectangle((60, 1770, 60 + prog_w, 1800), radius=14, fill=accent + (255,))

    if idx % 2 == 0:
        d.line((90, 250, VIDEO_W - 90, 250), fill=accent + (255,), width=6)
        d.polygon([(870, 260), (930, 260), (900, 300)], fill=accent + (255,))
    else:
        d.ellipse((890, 220, 990, 320), outline=accent + (255,), width=6)

    if scene.emphasis == "highlight":
        d.rounded_rectangle((120, 980, 960, 1100), radius=26, outline=accent + (255,), width=6)
    elif scene.emphasis == "shake":
        d.line((120, 1120, 960, 1080), fill=accent + (255,), width=5)
    elif scene.emphasis == "underline":
        d.line((140, 1230, 900, 1230), fill=accent + (255,), width=10)

    subtitle_font = pick_font(32)
    sub = clean_text(narration_text)[:140]
    d.rounded_rectangle((88, 1220, 992, 1335), radius=26, fill=(0, 0, 0, 100))
    draw_multiline_center(
        d,
        sub,
        1278,
        subtitle_font,
        fill=accent,
        stroke_fill=(0, 0, 0),
        stroke_width=4,
        max_width=800,
        line_spacing=5,
    )

    frame = Image.alpha_composite(frame, overlay)
    return frame.convert("RGB")


def save_frames(scene_plans: List[ScenePlan], narration: str) -> List[Path]:
    frames = []
    for i, scene in enumerate(scene_plans):
        img = create_scene_frame(scene, i, len(scene_plans), narration)
        path = ASSETS_DIR / f"frame_{i:02d}.jpg"
        img.save(path, quality=94, optimize=True)
        frames.append(path)
    return frames


def create_thumbnail(plan: ScriptPlan, narration: str) -> Path:
    img = make_background((VIDEO_W, VIDEO_H), 0, 1, "zoom")
    img = img.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, 0, VIDEO_W, 420), fill=(0, 0, 0, 110))
    d.rounded_rectangle((70, 1240, 1010, 1750), radius=42, fill=(0, 0, 0, 165))
    font_big = pick_font(76, bold=True)
    font_mid = pick_font(52)
    accent = (109, 240, 255)
    title = plan.title[:48]
    draw_multiline_center(d, title, 240, font_big, fill=(255, 255, 255), stroke_fill=(0, 0, 0), stroke_width=7, max_width=920, line_spacing=8)
    draw_multiline_center(d, "WATCH TILL END", 1510, font_mid, fill=accent, stroke_fill=(0, 0, 0), stroke_width=6, max_width=850, line_spacing=8)
    d.rounded_rectangle((120, 460, 520, 610), radius=30, fill=(255, 201, 77, 255))
    d.text((158, 495), "AJEEBOLOGY", font=pick_font(44, bold=True), fill=(10, 14, 28))
    thumb = Image.alpha_composite(img, overlay).convert("RGB")
    path = OUTPUT_DIR / f"thumbnail_{safe_slug(plan.title)}.jpg"
    thumb.save(path, quality=95, optimize=True)
    return path


def frames_to_concat_file(frame_paths: List[Path], scene_plans: List[ScenePlan]) -> Path:
    concat = OUTPUT_DIR / "frames_concat.txt"
    lines = []
    for p, sc in zip(frame_paths, scene_plans):
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"duration {max(0.5, sc.duration):.3f}")
    if frame_paths:
        lines.append(f"file '{frame_paths[-1].as_posix()}'")
    concat.write_text("
".join(lines), encoding="utf-8")
    return concat


def render_video(frame_paths: List[Path], scene_plans: List[ScenePlan], narration_audio: Optional[Path], audio_duration: float, out_name: str) -> Path:
    concat_path = frames_to_concat_file(frame_paths, scene_plans)
    video_path = OUTPUT_DIR / out_name
    temp_video = OUTPUT_DIR / "temp_video.mp4"
    cmd1 = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_path),
        "-r", str(FPS),
        "-vsync", "vfr",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        str(temp_video),
    ]
    run_cmd(cmd1, timeout=1800)
    if narration_audio and narration_audio.exists():
        cmd2 = [
            "ffmpeg", "-y",
            "-i", str(temp_video),
            "-i", str(narration_audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(video_path),
        ]
    else:
        cmd2 = [
            "ffmpeg", "-y",
            "-i", str(temp_video),
            "-c:v", "copy",
            "-movflags", "+faststart",
            str(video_path),
        ]
    run_cmd(cmd2, timeout=1800)
    if temp_video.exists():
        temp_video.unlink(missing_ok=True)
    return video_path


def synthesize_audio_with_ffmpeg(text: str, out_path: Path) -> Optional[Path]:
    if not which("espeak") and not which("espeak-ng"):
        return None
    exe = which("espeak-ng") or which("espeak")
    txt = text.replace('"', "'")
    run_cmd([exe, "-w", str(out_path), txt], timeout=120, check=True)
    return out_path if out_path.exists() else None


def build_metadata(plan: ScriptPlan, sources: List[ResearchSource], video_path: Path, thumbnail_path: Path, runtime_stats: Dict[str, Any]) -> Path:
    meta = {
        "title": plan.title,
        "description": plan.description,
        "tags": plan.tags,
        "hashtags": plan.hashtags,
        "category": plan.category,
        "video_path": str(video_path),
        "thumbnail_path": str(thumbnail_path),
        "sources": serialize_sources(sources),
        "runtime_stats": runtime_stats,
    }
    path = OUTPUT_DIR / f"metadata_{safe_slug(plan.title)}.json"
    write_json(path, meta)
    return path


def pack_telegram_caption(plan: ScriptPlan, runtime_stats: Dict[str, Any], metadata_path: Path) -> str:
    src_lines = []
    for s in plan.sources[:5]:
        if s.url:
            src_lines.append(f"• {s.title} - {s.url}")
        else:
            src_lines.append(f"• {s.title}")
    sources_txt = "
".join(src_lines) if src_lines else "• No sources captured"
    caption = (
        f"Title: {plan.title}
"
        f"Description: {plan.description}
"
        f"Tags: {', '.join(plan.tags[:10])}
"
        f"Hashtags: {' '.join(plan.hashtags[:8])}
"
        f"Category: {plan.category}
"
        f"Runtime: {runtime_stats.get('video_seconds', 'n/a')}s
"
        f"Artifact: {metadata_path.name}
"
        f"Research Sources:
{sources_txt}"
    )
    return caption[:1000]


def run_pipeline() -> RunResult:
    ensure_dirs()
    ensure_ffmpeg_or_fail()
    state = load_state()
    topic = pick_topic(state)
    log(f"Selected topic: {topic}")
    plan = generate_script_plan(topic)
    scenes = make_scene_plan(plan)
    narration, subtitle_chunks = generate_narration_and_captions(plan, scenes)
    combined_narration = narration + " " + " ".join(ch["text"] for ch in subtitle_chunks)
    audio_path = OUTPUT_DIR / f"narration_{safe_slug(plan.title)}.wav"
    audio_file = synthesize_audio_with_ffmpeg(combined_narration, audio_path)
    frame_paths = save_frames(scenes, combined_narration)
    video_seconds = sum(s.duration for s in scenes)
    if audio_file and audio_file.exists():
        try:
            probe = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_file)], timeout=120)
            audio_duration = float(probe.stdout.strip() or "0")
        except Exception:
            audio_duration = video_seconds
    else:
        audio_duration = video_seconds
    video_name = f"{safe_slug(plan.title)}_{now_ts()}.mp4"
    video_path = render_video(frame_paths, scenes, audio_file, audio_duration, video_name)
    thumbnail_path = create_thumbnail(plan, narration)
    runtime_stats = {
        "topic": topic,
        "scene_count": len(scenes),
        "video_seconds": round(video_seconds, 2),
        "audio_seconds": round(audio_duration, 2),
        "frames": len(frame_paths),
        "files": {
            "video": str(video_path),
            "thumbnail": str(thumbnail_path),
        },
    }
    metadata_path = build_metadata(plan, plan.sources, video_path, thumbnail_path, runtime_stats)
    telegram_caption = pack_telegram_caption(plan, runtime_stats, metadata_path)
    telegram_send_photo(thumbnail_path, caption=telegram_caption)
    telegram_send_document(video_path, caption=telegram_caption, filename=video_path.name)
    telegram_send_document(metadata_path, caption="Research sources and runtime stats")
    result = RunResult(
        topic=topic,
        title=plan.title,
        duration=video_seconds,
        video_path=str(video_path),
        thumbnail_path=str(thumbnail_path),
        metadata_path=str(metadata_path),
        sources=plan.sources,
        runtime_stats=runtime_stats,
    )
    write_json(OUTPUT_DIR / "last_result.json", asdict(result))
    return result


def main() -> int:
    try:
        result = run_pipeline()
        log(f"Done: {result.title} -> {result.video_path}")
        return 0
    except Exception as e:
        err_path = OUTPUT_DIR / "error.txt"
        err_path.write_text(traceback.format_exc(), encoding="utf-8")
        log(f"FAILED: {e}")
        try:
            token = os.getenv("TELEGRAM_TOKEN", "").strip()
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
            if token and chat_id and err_path.exists():
                telegram_send_document(err_path, caption="Ajeebology Shorts pipeline failed. See error log.")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
