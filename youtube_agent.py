import os
import requests
from groq import Groq
from gtts import gTTS
from PIL import Image, ImageDraw

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Groq(api_key=GROQ_API_KEY)

# CRITICAL PROMPT RULE: Must use ONLY English Alphabets (Roman Urdu/Hindi)
prompt = """
You are the scriptwriter for 'AjeebOology' YouTube Channel. 
Generate 1 psychological fact or mind-blowing strange reality.
CRITICAL RULE: Write EVERYTHING using English Alphabets ONLY (Roman Urdu/Hindi style, like 'Kya aapko pata hai...'). 
Do NOT use Devanagari/Hindi script (like हिंदी) and do NOT use Urdu script. Use only plain English letters.
The tone must be shocking and fast-paced. Keep it short for a 30-second YouTube Short.

Format the output exactly like this:
TITLE: [Your Title in Roman Urdu using English letters]
TAGS: [Your Tags Here]
SCRIPT: [Your 30-second Roman Urdu Script Here using English letters]
"""

chat_completion = client.chat.completions.create(
    messages=[{"role": "user", "content": prompt}],
    model="llama-3.3-70b-versatile",
)
response_text = chat_completion.choices[0].message.content

title = "AjeebOology Fact"
tags = "#shorts #facts"
script = response_text

for line in response_text.split('\n'):
    if line.startswith("TITLE:"): title = line.replace("TITLE:", "").strip()
    elif line.startswith("TAGS:"): tags = line.replace("TAGS:", "").strip()
    elif line.startswith("SCRIPT:"): script = line.replace("SCRIPT:", "").strip()

# Audio generation
tts = gTTS(text=script, lang='hi', slow=False)
audio_file = "voice.mp3"
tts.save(audio_file)

# Video Background Canvas (1080x1920)
img = Image.new('RGB', (1080, 1920), color=(15, 10, 25))
d = ImageDraw.Draw(img)
d.rectangle([(30, 30), (1050, 1890)], outline=(147, 51, 234), width=10)
d.text((540, 250), "AJEEBOOLOGY SHORTS", fill=(255, 255, 255), anchor="mm")
d.text((540, 960), "🧠\nVideo Content\nProcessing...", fill=(234, 179, 8), anchor="mm")
thumbnail_file = "thumbnail.png"
img.save(thumbnail_file)

# FFmpeg Compile
video_file = "output_video.mp4"
os.system(f"ffmpeg -loop 1 -i {thumbnail_file} -i {audio_file} -c:v libx264 -tune stillimage -c:a aac -b:a 192k -pix_fmt yuv420p -shortest {video_file}")

# Telegram Notification
tg_msg = f"🎬 *AjeebOology Alert!*\n\n📌 *Title:* {title}\n\n🔑 *Tags:* {tags}\n\n⚠️ Check GitHub Actions Artifacts to download your video!"
tg_url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/sendMessage"
requests.post(tg_url, data={"chat_id": TELEGRAM_CHAT_ID, "text": tg_msg, "parse_mode": "Markdown"})
