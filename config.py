#!/usr/bin/env python3
"""
Ajeebology Shorts - Global Configuration Management
Handles all configuration, secrets, and environment variables
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Config:
    """Global configuration for Ajeebology pipeline."""
    
    # API KEYS (from GitHub Secrets)
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
    TAVILY_API_KEY: str = os.environ.get("TAVILY_API_KEY", "")
    TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
    UNSPLASH_ACCESS_KEY: str = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    
    # VIDEO SETTINGS
    WIDTH: int = 1080
    HEIGHT: int = 1920
    FPS: int = 24
    TARGET_DURATION: int = 58
    MAX_DURATION: int = 60
    VIDEO_BITRATE: str = "2500k"
    
    # AUDIO SETTINGS
    VOICE_MODEL: str = "hi-IN-MadhurNeural"
    VOICE_RATE: str = "+10%"
    AUDIO_SAMPLE_RATE: int = 44100
    AUDIO_BITRATE: str = "192k"
    
    # TEXT & FONT
    FONT_SIZE_TITLE: int = 72
    FONT_SIZE_BODY: int = 56
    FONT_SIZE_SMALL: int = 40
    
    # COLORS
    COLOR_BG_DARK: tuple = (10, 5, 25)
    COLOR_BG_MID: tuple = (30, 15, 60)
    COLOR_ACCENT: tuple = (0, 255, 255)
    COLOR_ACCENT_2: tuple = (255, 0, 128)
    COLOR_TEXT: tuple = (255, 255, 255)
    COLOR_HIGHLIGHT: tuple = (255, 255, 0)
    
    # PATHS
    BASE_DIR: Path = Path("/tmp/ajeebology")
    FRAMES_DIR: Path = BASE_DIR / "frames"
    AUDIO_DIR: Path = BASE_DIR / "audio"
    ASSETS_DIR: Path = BASE_DIR / "assets"
    OUTPUT_DIR: Path = BASE_DIR / "output"
    LOGS_DIR: Path = BASE_DIR / "logs"
    CACHE_DIR: Path = BASE_DIR / "cache"
    
    # B-ROLL & ASSETS
    BROLL_ENABLED: bool = True
    POLLINATIONS_ENABLED: bool = True
    PEXELS_ENABLED: bool = True
    UNSPLASH_ENABLED: bool = True
    MUSIC_VOLUME: float = 0.15
    
    # SCRIPT
    SCRIPT_CATEGORIES: List[str] = None
    ENABLE_EMPHASIS_HIGHLIGHTS: bool = True
    ENABLE_NUMBERED_BADGES: bool = True
    
    # DELIVERY
    TELEGRAM_ENABLED: bool = True
    TELEGRAM_MAX_FILE_SIZE: int = 48 * 1024 * 1024
    
    # LOGGING
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    
    # PIPELINE
    PARALLEL_DOWNLOADS: int = 3
    RETRY_ATTEMPTS: int = 3
    RETRY_DELAY: int = 2
    REQUEST_TIMEOUT: int = 30
    
    def __post_init__(self):
        if self.SCRIPT_CATEGORIES is None:
            self.SCRIPT_CATEGORIES = ["psychology", "space", "weird_facts"]
    
    def validate(self) -> tuple:
        if not self.GROQ_API_KEY:
            return False, "GROQ_API_KEY not configured"
        if not self.TAVILY_API_KEY:
            return False, "TAVILY_API_KEY not configured"
        if not self.TELEGRAM_TOKEN:
            return False, "TELEGRAM_TOKEN not configured"
        if not self.TELEGRAM_CHAT_ID:
            return False, "TELEGRAM_CHAT_ID not configured"
        return True, "Configuration valid"
    
    def create_directories(self):
        for directory in [self.FRAMES_DIR, self.AUDIO_DIR, self.ASSETS_DIR, self.OUTPUT_DIR, self.LOGS_DIR, self.CACHE_DIR]:
            directory.mkdir(parents=True, exist_ok=True)


config = Config()
