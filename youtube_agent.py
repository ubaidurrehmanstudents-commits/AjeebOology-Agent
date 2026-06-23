#!/usr/bin/env python3
"""
=============================================================================
 AJEEBOLOGY SHORTS — Premium YouTube Shorts Automation Pipeline
 Fully automated: Research → Script → Voiceover → Stock Video → Subtitles 
 → Music → Assembly → Telegram delivery
=============================================================================
"""

import os, sys, json, time, math, random, asyncio, shutil, subprocess, traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple
import requests
import edge_tts

# ─── CONFIGURATION ───
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY")
TAVILY_API_KEY   = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY   = os.environ.get("PEXELS_API_KEY")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

W, H, FPS = 1080, 1920, 30
BRAND_PURPLE, BRAND_CYAN, BRAND_GOLD = "#1a0a2e", "#00FFFF", "#FFD700"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

OUT = Path("/tmp/ajeebology_output")
OUT.mkdir(parents=True, exist_ok=True)
for p in ["output_video.mp4","voice_combined.mp3","final_audio.mp3",
          "intro.mp4","subtitles.ass","subscribe.mp4","thumb.jpg",
          "metadata.json","pipeline.log"]:
    globals()[f"{p.replace('.','_').upper()}"] = OUT/p

STOCK_DIR = OUT/"stock_clips"; STOCK_DIR.mkdir(exist_ok=True)
CLIPS_DIR = OUT/"processed"; CLIPS_DIR.mkdir(exist_ok=True)
FINAL_VIDEO = OUT/"output_video.mp4"
VOICE_AUDIO = OUT/"voice_combined.mp3"
FINAL_AUDIO = OUT/"final_audio.mp3"
INTRO       = OUT/"intro.mp4"
SUBS_FILE   = OUT/"subtitles.ass"
SUB_OVERLAY = OUT/"subscribe.mp4"
THUMB       = OUT/"thumb.jpg"
META_FILE   = OUT/"metadata.json"
LOG_FILE    = OUT/"pipeline.log"

# ─── UTILITIES ───
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)
    with open(LOG_FILE,"a",encoding="utf-8") as f: f.write(f"[{ts}] [{level}] {msg}\n")

def step(n,t,name):
    log(""); log("━"*57); log(f"  STEP {n}/{t}: {name}"); log("━"*57)

def ff(args, timeout=300):
    try:
        r = subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error"]+args,
                          check=True,capture_output=True,text=True,timeout=timeout)
        return True, r.stdout, r.stderr
    except subprocess.CalledProcessError as e:
        log(f"FFmpeg error (code {e.returncode}): {e.stderr[:500]}", "ERROR")
        return False, e.stdout, e.stderr
    except subprocess.TimeoutExpired:
        log(f"FFmpeg timeout ({timeout}s)", "ERROR")
        return False, "", "Timeout"

def duration(f):
    if not f.exists() or f.stat().st_size<100: return 0.0
    try:
        r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","default=noprint_wrappers=1:nokey=1",str(f)],
                          capture_output=True,text=True,timeout=15)
        return max(0.0, float(r.stdout.strip()))
    except: return 0.0

def resolution(f):
    try:
        r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                          "-show_entries","stream=width,height","-of","csv=s=x:p=0",str(f)],
                          capture_output=True,text=True,timeout=15)
        p = r.stdout.strip().split("x")
        if len(p)==2: return int(p[0]),int(p[1])
    except: pass
    return 0,0

def retry(func, n=3, d=2, b=2):
    for a in range(1,n+1):
        try: return func()
        except Exception as e:
            if a<n: log(f"Retry {a}/{n}: {e}", "WARN"); time.sleep(d); d*=b
            else: raise

def parse_json(text):
    if not text: return None
    if "```" in text:
        for p in text.split("```"):
            p=p.strip()
            if p.startswith("json"): p=p[4:].strip()
            if p.startswith("{"): text=p; break
    try: return json.loads(text.strip())
    except:
        s,e=text.find("{"),text.rfind("}")
        if s>=0 and e>s:
            try: return json.loads(text[s:e+1])
            except: return None
    return None

def fmt_ass(s):
    s=max(0,s); cs=int((s-int(s))*100)
    return f"{int(s//3600)}:{int((s%3600)//60):02d}:{int(s%60):02d}.{cs:02d}"

def size_mb(f): return f.stat().st_size/1048576 if f.exists() else 0.0

def send_tg(text, mode="Markdown"):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                     data={"chat_id":TELEGRAM_CHAT_ID,"text":text[:4000],
                           "parse_mode":mode,"disable_web_page_preview":True}, timeout=30)
    except: pass

def send_err(msg):
    send_tg(f"❌ *Pipeline Error:*\n`{msg[:300]}`\nCheck GitHub Actions logs.", "Markdown")

# ─── STEP 1: RESEARCH ───
def research():
    cats = [("psychology",["psychology fact about human behavior","mind blowing psychology fact"]),
            ("space",["amazing space fact","mind blowing space secret"]),
            ("weird",["weird fact about human body","strange but true fact"]),
            ("brain",["brain fact","neuroscience fact about memory"])]
    cat, qs = random.choice(cats)
    q = random.choice(qs)
    log(f"Category: {cat}")
    log(f"Query: {q}")

    def _s():
        r = requests.post("https://api.tavily.com/search",
                         json={"api_key":TAVILY_API_KEY,"query":q,
                               "search_depth":"basic","max_results":5,"include_answer":True},
                         timeout=30)
        if r.status_code!=200: raise RuntimeError(f"Tavily {r.status_code}")
        return r.json()

    try:
        data = retry(_s, n=2, d=3)
        ans = data.get("answer","")
        if ans and len(ans)>50: log(f"Result: {ans[:120]}..."); return ans
        results = data.get("results",[])
        if results:
            best = max(results, key=lambda r: len(r.get("content","")))
            c = best.get("content","")
            if len(c)>50: log(f"Using: {c[:120]}..."); return c
    except: log("Tavily failed", "WARN")

    fallback = {
        "psychology":"The human brain processes 70,000 thoughts per day. Most happen below conscious awareness.",
        "space":"A day on Venus is longer than a year on Venus. It takes 243 Earth days to rotate but 225 to orbit.",
        "weird":"Your stomach lining replaces itself every 3-4 days. Otherwise your own stomach acid would digest you!",
        "brain":"Your brain uses 20% of your body's energy despite being only 2% of your body weight."
    }
    return fallback.get(cat, fallback["psychology"])

# ─── STEP 2: SCRIPT ───
def generate_script(ctx):
    prompt = """You write Hinglish YouTube Shorts scripts for "Ajeebology Shorts".
Rules: Roman Hinglish only, 12-14 short phrases (3-12 words each),
first = hook, last = subscribe CTA. Include pexels_keyword.
Output ONLY valid JSON:
{
  "title": "Catchy title with emoji",
  "category": "psychology|space|weird|brain",
  "seo_title": "SEO title | Ajeebology Shorts",
  "description": "2-3 line Hinglish description",
  "tags": ["tag1","tag2","tag3","tag4","tag5"],
  "hashtags": "#tag1 #tag2",
  "pexels_keyword": "English keyword for video search",
  "phrases": ["Hook?","Next phrase...","...12-14 total","Subscribe CTA"]
}"""
    log("Generating script via Groq LLaMA...")
    def _g():
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},
            json={"model":"llama-3.3-70b-versatile",
                  "messages":[{"role":"system","content":prompt},
                             {"role":"user","content":f"Write Hinglish script based on: {ctx}"}],
                  "temperature":0.8,"max_tokens":2000}, timeout=90)
        if r.status_code!=200: raise RuntimeError(f"Groq {r.status_code}")
        s = parse_json(r.json()["choices"][0]["message"]["content"])
        if not s: raise ValueError("JSON parse failed")
        if len(s.get("phrases",[]))<8: raise ValueError(f"Only {len(s['phrases'])} phrases")
        return s
    try:
        s = retry(_g, n=2, d=5)
        log(f"✓ Script: {len(s['phrases'])} phrases")
        return s
    except:
        log("Groq failed, emergency script", "WARN")
        cat = random.choice(["psychology","space","weird","brain"])
        return {"title":"Amazing Fact You Didn't Know 🤯","category":cat,
                "seo_title":f"Amazing {cat.capitalize()} Fact | Ajeebology Shorts",
                "description":f"Ek aaisa {cat} fact jo aapne kabhi nahi suna hoga!",
                "tags":[f"{cat} facts","hinglish facts","amazing"],
                "hashtags":f"#{cat} #facts #hinglishfacts",
                "pexels_keyword":cat,
                "phrases":["Kya aap jaante hain?","Yeh fact aapko hairan kar dega!",
                          ctx.split(".")[0] if "." in ctx else ctx,"Haan, yeh bilkul sach hai!",
                          "Scientists ne yeh research mein paya hai.","Yeh aapki soch badal dega.",
                          "Isliye yaad rakhiye!","Kyunki knowledge hi power hoti hai.",
                          "Agar achha laga toh like karein!","Aur Ajeebology Shorts ko subscribe karein!"]}

def validate(s):
    for f in ["title","category","phrases","tags","hashtags"]:
        if f not in s:
            if f=="phrases": s[f]=["Amazing fact for you!"]
            elif f=="tags": s[f]=["facts","hinglish"]
            elif f=="hashtags": s[f]="#facts"
            else: s[f]=f"Amazing Fact {datetime.now().day}"
    ps = [p.strip() for p in s["phrases"] if len(p.strip().split())>=3 and len(p)<200]
    if not ps: ps = ["Kya aap jaante hain? Yeh fact amazing hai!"]
    s["phrases"] = ps[:14]
    return s

# ─── STEP 3: AUDIO ───
async def gen_audio(phrase, path):
    try:
        c = edge_tts.Communicate(text=phrase.strip(), voice="hi-IN-MadhurNeural",
                                 rate="-5%", pitch="-2Hz")
        await c.save(str(path))
    except Exception as e:
        log(f"edge-tts failed: {e}", "ERROR")
        ff(["-f","lavfi","-i","anullsrc=r=44100:cl=mono:d=2.0",str(path)])
    return duration(path)

async def gen_all_audio(phrases):
    files = []
    for i,p in enumerate(phrases):
        path = OUT/f"phrase_{i:03d}.mp3"
        log(f"  TTS [{i+1}/{len(phrases)}] {p[:55]}...")
        d = await gen_audio(p, path)
        files.append({"idx":i,"phrase":p,"path":str(path),"duration":d,"words":p.split()})
        if i<len(phrases)-1: await asyncio.sleep(0.3)
    total = sum(f["duration"] for f in files)
    log(f"Total audio: {total:.1f}s across {len(files)} phrases")
    return files

def concat_audio(files, out):
    if not files or all(f["duration"]<0.1 for f in files):
        log("No valid audio! Generating 30s silence.", "ERROR")
        ff(["-f","lavfi","-i","anullsrc=r=44100:cl=mono:d=30",str(out)])
        return duration(out)
    lst = OUT/"concat.txt"
    with open(lst,"w") as f:
        for af in files:
            if Path(af["path"]).exists() and Path(af["path"]).stat().st_size>100:
                f.write(f"file '{af['path']}'\n")
    raw = OUT/"raw.mp3"
    ok,_,_ = ff(["-f","concat","-safe","0","-i",str(lst),"-c","copy",str(raw)])
    if not ok or not raw.exists():
        ok,_,_ = ff(["-f","concat","-safe","0","-i",str(lst),"-c:a","libmp3lame","-q:a","2",str(raw)])
    if not ok or not raw.exists():
        ff(["-f","lavfi","-i","anullsrc=r=44100:cl=mono:d=30",str(out)])
        return duration(out)
    trim = OUT/"trimmed.mp3"
    ok,_,_ = ff(["-i",str(raw),"-af",
                "silenceremove=start_periods=1:start_duration=0.3:start_threshold=-45dB:detection=peak,"
                "silenceremove=stop_periods=1:stop_duration=0.3:stop_threshold=-45dB:detection=peak",
                str(trim)])
    shutil.move(str(trim if ok and trim.exists() else raw), str(out))
    return duration(out)

def word_timings(phrase, dur):
    words = phrase.strip().split()
    if not words or dur<=0: return []
    total = sum(len(w) for w in words) or 1
    timings, cur = [], 0.0
    for w in words:
        wd = max((len(w)/total)*dur, 0.15)
        timings.append({"word":w,"start":cur,"end":cur+wd,"cs":int(wd*100)})
        cur += wd
    return timings

# ─── STEP 4: MUSIC ───
def fetch_music(dur):
    if dur<5: return None
    out = OUT/"bg_music.mp3"
    for url in ["https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
                "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
                "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3"]:
        try:
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code!=200: continue
            tmp = OUT/"music_src.mp3"
            with open(tmp,"wb") as f:
                for c in r.iter_content(8192):
                    if c: f.write(c)
                    if tmp.stat().st_size>10*1048576: break
            if tmp.stat().st_size<10000: continue
            ok,_,_ = ff(["-i",str(tmp),"-t",str(dur+2),
                        "-af",f"volume=0.12,afade=t=in:ss=0:d=2,afade=t=out:st={max(0,dur-2)}:d=2",
                        str(out)])
            if ok and out.exists(): return out
        except: continue
    ok,_,_ = ff(["-f","lavfi","-i",f"anoisesrc=d={dur}:c=pink:a=0.015",
                "-f","lavfi","-i",f"sine=frequency=220:duration={dur}",
                "-filter_complex","[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.3[o]",
                "-map","[o]","-c:a","libmp3lame","-q:a","5",str(out)])
    return out if ok and out.exists() else None

def mix_audio(voice, music, out):
    ok,_,_ = ff(["-i",str(music),"-i",str(voice),
                "-filter_complex",
                "[0:a]volume=0.15[mu];[1:a]asplit[vo][si];"
                f"[mu][si]sidechaincompress=threshold=-18dB:ratio=5:attack=10:release=100[md];"
                "[md][vo]amix=inputs=2:duration=first[o]",
                "-map","[o]","-c:a","libmp3lame","-q:a","2",str(out)])
    if not ok:
        log("Sidechain failed, using simple volume mix", "WARN")
        ok,_,_ = ff(["-i",str(voice),"-i",str(music),
                    "-filter_complex","[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first[o]",
                    "-map","[o]","-c:a","libmp3lame","-q:a","2",str(out)])
    return ok

# ─── STEP 5: STOCK VIDEO ───
def search_pexels(kw):
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                        headers={"Authorization":PEXELS_API_KEY},
                        params={"query":kw,"orientation":"portrait","size":"medium","per_page":10},
                        timeout=30)
        if r.status_code!=200: return []
        videos = r.json().get("videos",[])
        parsed = []
        for v in videos:
            info = {"url":None,"quality":"unknown"}
            for f in v.get("video_files",[]):
                w,h = f.get("width",0),f.get("height",0)
                if w>=1080 and h>=1920: info["url"]=f["link"]; info["quality"]="1080p"; break
                elif w>=720 and h>=1280 and info["quality"]=="unknown":
                    info["url"]=f["link"]; info["quality"]="720p"
            if info["url"]: parsed.append(info)
        return parsed
    except: return []

def dl_video(info, path):
    try:
        r = requests.get(info["url"], stream=True, timeout=120)
        if r.status_code!=200: return False
        with open(path,"wb") as f:
            for c in r.iter_content(8192):
                if c: f.write(c)
                if path.stat().st_size>50*1048576: break
        return path.stat().st_size>100000
    except: return False

def dl_stock(kw, cat, maxc=2):
    clips = []
    for k in [kw, cat, "abstract background", "time lapse"]:
        if len(clips)>=maxc: break
        results = search_pexels(k)
        for v in results[:maxc]:
            if len(clips)>=maxc: break
            path = STOCK_DIR/f"stock_{len(clips):02d}.mp4"
            if dl_video(v, path): clips.append(path); log(f"  Clip {len(clips)}: {k}")
    return clips

# ─── STEP 6: SUBTITLES ───
def gen_ass(files, out, mv=400):
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,DejaVu Sans Bold,42,&H00FFFF00,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,1,2,50,50,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events, cur = [], 0.0
    for af in files:
        d = af["duration"]
        if d<=0: cur+=max(d,2.0); continue
        wt = word_timings(af["phrase"], d)
        kt = " ".join(f"{{\\k{max(1,w['cs'])}}}{w['word'].replace('{','\\\\{').replace('}','\\\\}')}" for w in wt)
        events.append(f"Dialogue: 0,{fmt_ass(cur)},{fmt_ass(cur+d)},Karaoke,,0,0,0,,{kt}")
        cur += d
    with open(out,"w",encoding="utf-8") as f: f.write(hdr+"\n".join(events)+"\n")
    log(f"ASS subtitles: {len(events)} karaoke events, {cur:.1f}s total")

def drawtext_fallback(files):
    flt, cur = [], 0.0
    for af in files:
        s,e = cur, cur+af["duration"]
        esc = af["phrase"].replace("'","'\\\\\\'").replace(":","\\:").replace("%","\\%").replace("{","\\{").replace("}","\\}")
        flt.append(f"drawtext=text='{esc}':fontsize=38:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=18:x=(w-text_w)/2:y=h-text_h-180:fontfile={FONT_BOLD}:enable='between(t,{s:.2f},{e:.2f})'")
        cur = e
    return ",".join(flt)

# ─── STEP 7: EFFECTS ───
def ken_burns(inp, out, dur, zs=1.0, ze=1.08):
    if dur<=0:
        if inp!=out: shutil.copy(str(inp),str(out))
        return True
    rate = (ze-zs)/(dur*FPS) if dur>0 else 0
    ok,_,_ = ff(["-stream_loop","-1","-i",str(inp),"-t",str(dur),
                "-vf",f"zoompan=z='min({zs}+{rate:.6f}*on,{ze})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(dur*FPS)}:s={W}x{H}:fps={FPS}",
                "-c:v","libx264","-preset","veryfast","-crf","21","-pix_fmt","yuv420p",str(out)])
    return ok

def make_intro(d=3.0):
    ok,_,_ = ff(["-f","lavfi","-i",f"color=c={BRAND_PURPLE}:s={W}x{H}:d={d}:r={FPS}",
                "-f","lavfi","-i",f"nullsrc=s={W}x{H}:d={d}:r={FPS}",
                "-filter_complex",
                f"[0:v][1:v]overlay[bg];"
                f"[bg]drawtext=text='Ajeebology Shorts':fontsize=64:fontcolor={BRAND_CYAN}:x=(w-text_w)/2:y=(h-text_h)/2-60:fontfile={FONT_BOLD}:shadowx=3:shadowy=3:shadowcolor=black@0.5[wt];"
                f"[wt]drawtext=text='Facts in Hinglish':fontsize=32:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2+30:fontfile={FONT_REG}[ws];"
                f"[ws]fade=t=in:st=0:d=0.5:alpha=1,fade=t=out:st={d-0.7}:d=0.7:alpha=1",
                "-c:v","libx264","-preset","veryfast","-crf","21","-pix_fmt","yuv420p",str(INTRO)])
    return ok

def make_subscribe(d=4.0):
    ok,_,_ = ff(["-f","lavfi","-i",f"color=c=0x0D0618:s={W}x{H}:d={d}:r={FPS}",
                "-vf",f"drawtext=text='Ajeebology Shorts':fontsize=52:fontcolor={BRAND_CYAN}:x=(w-text_w)/2:y=(h/2)-80:fontfile={FONT_BOLD},"
                       f"drawtext=text='📢 SUBSCRIBE KAREIN!':fontsize=44:fontcolor={BRAND_GOLD}:x=(w-text_w)/2:y=(h/2):fontfile={FONT_BOLD},"
                       f"drawtext=text='🔔 Bell icon dabayein':fontsize=28:fontcolor=white:x=(w-text_w)/2:y=(h/2)+80:fontfile={FONT_REG},"
                       f"fade=t=in:st=0:d=0.8:alpha=1,fade=t=out:st={d-0.5}:d=0.5:alpha=1",
                "-c:v","libx264","-preset","ultrafast","-crf","25","-pix_fmt","yuv420p",str(SUB_OVERLAY)])
    return ok

# ─── STEP 8: ASSEMBLY ───
def assemble(clips, intro, audio, sub_src, sub_ov, dur, out):
    log("═══ FINAL VIDEO ASSEMBLY ═══")
    dur = max(dur, 10)

    if not clips:
        log("No stock clips — generating animated fallback")
        fb = CLIPS_DIR/"fallback.mp4"
        ff(["-f","lavfi","-i",f"color=c={BRAND_PURPLE}:s={W}x{H}:d={dur}:r={FPS}",
           "-vf",f"drawbox=x=0:y=0:w=iw:h=ih:color=purple@0.1:t=fill,drawtext=text='Ajeebology Shorts':fontsize=40:fontcolor=white@0.2:x=(w-text_w)/2:y=(h-text_h)/2:fontfile={FONT_BOLD}",
           "-c:v","libx264","-preset","veryfast","-crf","23",str(fb)])
        clips = [fb]

    processed = []
    cd = dur/len(clips)
    for i,c in enumerate(clips):
        p = CLIPS_DIR/f"kb_{i:02d}.mp4"
        log(f"  Ken Burns clip {i+1}/{len(clips)}...")
        if not ken_burns(c,p,cd):
            log("  Ken Burns failed, using raw clip", "WARN")
            processed.append(c)
        else:
            processed.append(p)

    if len(processed)>1:
        merged = CLIPS_DIR/"merged.mp4"
        lst = CLIPS_DIR/"vlist.txt"
        with open(lst,"w") as f:
            for p in processed: f.write(f"file '{p}'\n")
        ok,_,_ = ff(["-f","concat","-safe","0","-i",str(lst),"-c","copy",str(merged)])
        if ok and merged.exists(): processed = [merged]
        else: processed = [processed[0]]

    if intro and intro.exists():
        wi = CLIPS_DIR/"with_intro.mp4"
        lst = CLIPS_DIR/"intro_list.txt"
        with open(lst,"w") as f: f.write(f"file '{intro}'\nfile '{processed[-1]}'\n")
        ff(["-f","concat","-safe","0","-i",str(lst),"-c","copy",str(wi)])
        processed = [wi]

    src = processed[-1]
    if not src or not src.exists(): return False, "No video source available"

    is_ass = str(sub_src).endswith(".ass")
    sf = f"subtitles={sub_src}" if is_ass else sub_src
    ss = max(0, dur-4)

    if sub_ov and sub_ov.exists():
        flt = f"[0:v]{sf}[sb];[sb]movie={sub_ov}:loop=0:setpts=PTS-STARTPTS[so];[sb][so]overlay=0:0:shortest=1:enable='between(t,{ss},{dur})'[ov]"
    else:
        flt = f"[0:v]{sf}[ov]"

    log("  Rendering final video with ffmpeg...")
    ok,_,stderr = ff(["-stream_loop","-1","-i",str(src),"-i",str(audio),
                     "-filter_complex",flt,"-map","[ov]","-map","1:a","-shortest",
                     "-c:v","libx264","-preset","veryfast","-crf","22",
                     "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p",
                     "-movflags","+faststart",str(out)], timeout=600)

    if ok and out.exists():
        log(f"✓ FINAL VIDEO: {duration(out):.1f}s, {size_mb(out):.1f}MB, {W}x{H}")
        return True, ""
    return False, stderr[:500] if stderr else "Unknown ffmpeg error"

def verify(f):
    if not f.exists(): return False, "File not found"
    if size_mb(f)<0.5: return False, f"Too small ({size_mb(f):.1f}MB)"
    d = duration(f)
    if d<10: return False, f"Too short ({d:.1f}s)"
    w,h = resolution(f)
    if w<100 or h<100: return False, f"Bad resolution ({w}x{h})"
    return True, f"{d:.1f}s, {size_mb(f):.1f}MB, {w}x{h}"

# ─── STEP 9: DELIVERY ───
def tg_send_video(path, cap):
    if size_mb(path)>48: return False
    try:
        with open(path,"rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo",
                            data={"chat_id":TELEGRAM_CHAT_ID,"caption":cap[:1024],
                                  "parse_mode":"Markdown","supports_streaming":True},
                            files={"video":f}, timeout=300)
        return r.status_code==200
    except: return False

def deliver(meta):
    if not FINAL_VIDEO.exists():
        send_err("Video file not found after assembly"); return
    cap = (f"🎬 **AJEEBOLOGY SHORTS — VIDEO READY**\n\n"
           f"**📺 {meta['title']}**\n"
           f"**📝 {meta.get('seo_title',meta['title'])}**\n\n"
           f"**📖** {meta.get('description','')}\n\n"
           f"**🏷** `{', '.join(meta['tags'][:10])}`\n"
           f"**🔖** {meta.get('hashtags','')}\n"
           f"**📂** {meta.get('category','facts')}  ⏱ {duration(FINAL_VIDEO):.0f}s  📦 {size_mb(FINAL_VIDEO):.1f}MB")
    if not tg_send_video(FINAL_VIDEO, cap):
        log("Video >48MB, sending thumbnail instead", "WARN")
        ff(["-i",str(FINAL_VIDEO),"-ss","5","-vframes","1",
           "-vf",f"scale={W}:{H}","-q:v","8",str(THUMB)])
        if THUMB.exists():
            with open(THUMB,"rb") as f:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                             data={"chat_id":TELEGRAM_CHAT_ID,"caption":cap[:1024],"parse_mode":"Markdown"},
                             files={"photo":f}, timeout=60)
        else: send_tg(cap)
    send_tg(f"✅ *Pipeline Complete* — {duration(FINAL_VIDEO):.0f}s video ready! Download artifact from GitHub.")

# ─── MAIN PIPELINE ───
async def run():
    t0, ts = time.time(), 9

    step(1,ts,"FACT RESEARCH")
    ctx = research()

    step(2,ts,"SCRIPT GENERATION")
    script = validate(generate_script(ctx))
    phrases = script["phrases"]
    kw = script.get("pexels_keyword", script.get("category","facts"))
    meta = {"title":script["title"],"category":script.get("category","facts"),
            "seo_title":script.get("seo_title",script["title"]),
            "description":script.get("description",""),
            "tags":script.get("tags",["facts","hinglish"]),
            "hashtags":script.get("hashtags","#facts")}

    step(3,ts,"AUDIO GENERATION")
    af = await gen_all_audio(phrases)
    if not af: send_err("No audio files generated"); return
    td = concat_audio(af, VOICE_AUDIO)
    meta["duration"] = td
    if td<10: log(f"Audio is short ({td:.0f}s), continuing anyway", "WARN")

    step(4,ts,"BACKGROUND MUSIC")
    music = fetch_music(td)
    if music and td>5:
        ok = mix_audio(VOICE_AUDIO, music, FINAL_AUDIO)
        if not ok: shutil.copy(VOICE_AUDIO, FINAL_AUDIO)
    else: shutil.copy(VOICE_AUDIO, FINAL_AUDIO)

    step(5,ts,"STOCK VIDEO DOWNLOAD")
    clips = dl_stock(kw, script.get("category","facts"), 2)

    step(6,ts,"INTRO & OVERLAYS")
    make_intro(3.0); make_subscribe(4.0)

    step(7,ts,"SUBTITLE GENERATION")
    gen_ass(af, SUBS_FILE, 400)
    sub = str(SUBS_FILE)
    with open(OUT/"test.ass","w") as f: f.write("[Script Info]\nScriptType: v4.00+\n")
    ok,_,_ = ff(["-f","lavfi","-i","color=c=black:s=8x8:d=0.2",
                "-vf",f"subtitles={OUT/'test.ass'}","-f","null","-"])
    if not ok:
        log("libass not available — using drawtext fallback", "WARN")
        sub = drawtext_fallback(af)
    else:
        log("libass available — using ASS karaoke subtitles")

    step(8,ts,"FINAL VIDEO ASSEMBLY")
    audio_src = FINAL_AUDIO if FINAL_AUDIO.exists() else VOICE_AUDIO
    sov = SUB_OVERLAY if SUB_OVERLAY.exists() else None
    ok, err = assemble(clips, INTRO if INTRO.exists() else None,
                       audio_src, sub, sov, td, FINAL_VIDEO)
    if not ok:
        log(f"❌ ASSEMBLY FAILED: {err}", "CRITICAL")
        send_err(f"Assembly error: {err}")
        return
    ok, info = verify(FINAL_VIDEO)
    if not ok:
        log(f"❌ VERIFICATION FAILED: {info}", "CRITICAL")
        send_err(f"Verification failed: {info}")
        return
    log(f"✓ Video verification passed: {info}")

    step(9,ts,"TELEGRAM DELIVERY")
    deliver(meta)

    # Summary
    log(""); log("═"*57); log("🏁  PIPELINE COMPLETE — SUCCESS"); log("═"*57)
    log(f"  ⏱ Time:         {time.time()-t0:.0f}s ({((time.time()-t0)/60):.1f} min)")
    log(f"  🎬 Video:       {duration(FINAL_VIDEO):.1f}s")
    log(f"  📦 Size:        {size_mb(FINAL_VIDEO):.1f} MB")
    log(f"  📐 Resolution:  {W}x{H} @ {FPS}fps")
    log(f"  💬 Phrases:     {len(phrases)}")
    log(f"  📂 Category:    {meta['category']}")
    log(f"  📺 Title:       {meta['title']}")
    log("═"*57)

    meta["pipeline_s"] = round(time.time()-t0)
    meta["video_s"] = round(duration(FINAL_VIDEO))
    meta["size_mb"] = round(size_mb(FINAL_VIDEO),1)
    with open(META_FILE,"w") as f: json.dump(meta,f,indent=2)

async def main():
    try:
        log(""); log("╔══════════════════════════════════════╗")
        log("║  🎬 AJEEBOLOGY SHORTS — PIPELINE      ║")
        log("╚══════════════════════════════════════════╝")
        log(f"Python {sys.version.split()[0]} | Output: {OUT}")
        missing = [k for k in ["GROQ_API_KEY","TAVILY_API_KEY","PEXELS_API_KEY",
                               "TELEGRAM_TOKEN","TELEGRAM_CHAT_ID"] if not os.environ.get(k)]
        if missing:
            log(f"❌ MISSING SECRETS: {missing}", "CRITICAL")
            sys.exit(1)
        log("✓ All API keys found")
        await run()
    except Exception as e:
        log(f"❌ CRASH: {e}\n{traceback.format_exc()}", "CRITICAL")
        try: send_err(str(e)[:200])
        except: pass
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
