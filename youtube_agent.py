import os
import requests
from groq import Groq
from gtts import gTTS
from PIL import Image, ImageDraw

# 1. API Environment Variables Check
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Groq(api_key=GROQ_API_KEY)
print("🚀 AjeebOology Engine Script Started...")

# 2. Generate Viral Script using Groq (Strict Roman Urdu Prompt)
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
print("📝 AI Script Generated!")

# Parse script details
title = "AjeebOology Fact"
tags = "#shorts #facts"
script = response_text

for line in response_text.split('\n'):
    if line.startswith("TITLE:"):
        title = line.replace("TITLE:", "").strip()
    elif line.startswith("TAGS:"):
        tags = line.replace("TAGS:", "").strip()
    elif line.startswith("SCRIPT:"):
        script = line.replace("SCRIPT:", "").strip()

# 3. Generate Audio via gTTS
tts = gTTS(text=script, lang='hi', slow=False)
audio_file = "voice.mp3"
tts.save(audio_file)
print("🔊 Voice Over Generated!")

# 4. Generate HD Canvas for Shorts (1080x1920)
img = Image.new('RGB', (1080, 1920), color=(15, 10, 25))
d = ImageDraw.Draw(img)

# Simple sleek border
d.rectangle([(30, 30), (1050, 1890)], outline=(147, 51, 234), width=10)

# Visual Placeholder Text
d.text((540, 250), "AJEEBOOLOGY SHORTS", fill=(255, 255, 255), anchor="mm")
d.text((540, 960), "🧠\nVideo Content\nProcessing...", fill=(234, 179, 8), anchor="mm")

thumbnail_file = "thumbnail.png"
img.save(thumbnail_file)
print("🖼️ Visual Frame Created!")

# 5. Compile into Video using FFmpeg
video_file = "output_video.mp4"
os.system(f"ffmpeg -loop 1 -i {thumbnail_file} -i {audio_file} -c:v libx264 -tune stillimage -c:a aac -b:a 192k -pix_fmt yuv420p -shortest {video_file}")
print("🎬 Final Video Rendered!")

# 6. Send Alert Notification to your Telegram Bot (Auto-Fix URL Error)
tg_msg = f"🎬 *AjeebOology Alert!*\n\n📌 *Title:* {title}\n\n🔑 *Tags:* {tags}\n\n⚠️ Check GitHub Actions Artifacts to download your video!"

clean_token = TELEGRAM_TOKEN.strip()
if "bot" in clean_token:
    # Agar token mein galti se pura URL format save ho gaya ho, toh yeh use theek kar dega
    clean_token = clean_token.split("bot")[-1].split("/")[0]

tg_url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
payload = {"chat_id": TELEGRAM_CHAT_ID.strip(), "text": tg_msg, "parse_mode": "Markdown"}

requests.post(tg_url, data=payload)
print("📲 Status Sent to Telegram!")
