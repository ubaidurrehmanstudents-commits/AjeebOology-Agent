name: 🤖 Ajeebologyshorts Pro - Daily AI Shorts

on:
  schedule:
    - cron: '0 11 * * *'   # 4:00 PM PKT daily
  workflow_dispatch:

jobs:
  generate-pro-short:
    runs-on: ubuntu-latest
    timeout-minutes: 40

    steps:
      - name: 📥 Checkout
        uses: actions/checkout@v4

      - name: 🐍 Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: 🔧 Install Dependencies
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y ffmpeg
          pip install -q moviepy edge-tts requests python-dotenv groq Pillow

      - name: 🔐 Load Secrets
        run: |
          cat > .env << 'EOF'
          GROQ_API_KEY=${{ secrets.GROQ_API_KEY }}
          TELEGRAM_TOKEN=${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID=${{ secrets.TELEGRAM_CHAT_ID }}
          PEXELS_API_KEY=${{ secrets.PEXELS_API_KEY || '' }}
          EOF

      - name: 🚀 Generate Professional Short + Metadata
        run: python scripts/generate_short_pro.py

      - name: 📤 Upload Video
        uses: actions/upload-artifact@v4
        with:
          name: ajeebologyshorts-pro
          path: output/videos/*.mp4
          retention-days: 30

      - name: 🧹 Cleanup
        if: always()
        run: rm -f .env
