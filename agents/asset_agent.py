#!/usr/bin/env python3
"""
Ajeebology Shorts - Asset Agent
Downloads B-roll images and background music from multiple sources
"""

import random
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import requests
from logger import logger_assets
from config import config
from utils import download_file, safe_filename, RetryConfig


class AssetAgent:
    """Manages B-roll image and music asset fetching from multiple sources."""
    
    # Free stock photo APIs
    PEXELS_API_KEY = "563492ad6f91700001000001f8b9d0e1a6f94f8a8e7e8e7e8e7e8e7"
    
    MUSIC_URLS = [
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_c8c8a73467.mp3",
        "https://cdn.pixabay.com/download/audio/2022/01/18/audio_d0a13f69d2.mp3",
        "https://cdn.pixabay.com/download/audio/2023/06/20/audio_abc123def.mp3",
        "https://cdn.pixabay.com/download/audio/2023/08/15/audio_xyz789.mp3"
    ]
    
    def __init__(self):
        self.assets = []
        logger_assets.info("AssetAgent initialized")
    
    def fetch_broll(self, prompt: str, index: int) -> Optional[str]:
        """Fetch B-roll image for a segment from multiple sources."""
        safe_prompt = safe_filename(prompt)[:30]
        dest_path = str(config.ASSETS_DIR / f"broll_{index:02d}_{safe_prompt}.jpg")
        
        logger_assets.info(f"Fetching B-roll for: {prompt}")
        
        # Try sources in order
        sources = [
            ("unsplash", self._try_unsplash),
            ("pollinations", self._try_pollinations),
            ("pexels", self._try_pexels)
        ]
        
        for source_name, source_func in sources:
            if source_name == "unsplash" and not config.UNSPLASH_ENABLED:
                continue
            if source_name == "pollinations" and not config.POLLINATIONS_ENABLED:
                continue
            if source_name == "pexels" and not config.PEXELS_ENABLED:
                continue
            
            logger_assets.debug(f"Trying {source_name}...")
            if source_func(prompt, dest_path):
                logger_assets.info(f"Successfully fetched from {source_name}: {dest_path}")
                return dest_path
        
        logger_assets.warning(f"Failed to fetch B-roll for: {prompt}")
        return None
    
    def _try_unsplash(self, prompt: str, dest: str) -> bool:
        """Search Unsplash for images."""
        try:
            url = f"https://api.unsplash.com/search/photos?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": f"Client-ID {config.UNSPLASH_ACCESS_KEY}"}
            resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            
            data = resp.json()
            results = data.get("results", [])
            if results:
                img_url = results[0]["urls"]["regular"]
                return download_file(img_url, dest, timeout=45)
        
        except Exception as e:
            logger_assets.debug(f"Unsplash error: {e}")
        
        return False
    
    def _try_pollinations(self, prompt: str, dest: str) -> bool:
        """Generate image using Pollinations.ai (free, no auth needed)."""
        try:
            enhanced = f"professional stock photo, {prompt}, high quality, detailed, cinematic lighting, 4k"
            encoded = quote_plus(enhanced)
            seed = random.randint(1, 100000)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&seed={seed}&nologo=true"
            logger_assets.debug(f"Pollinations URL: {url}")
            return download_file(url, dest, timeout=45)
        
        except Exception as e:
            logger_assets.debug(f"Pollinations error: {e}")
        
        return False
    
    def _try_pexels(self, prompt: str, dest: str) -> bool:
        """Search Pexels for free images."""
        try:
            url = f"https://api.pexels.com/v1/search?query={quote_plus(prompt)}&per_page=5&orientation=portrait"
            headers = {"Authorization": self.PEXELS_API_KEY}
            resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            
            data = resp.json()
            photos = data.get("photos", [])
            if photos:
                img_url = photos[0]["src"]["portrait"]
                return download_file(img_url, dest, timeout=45)
        
        except Exception as e:
            logger_assets.debug(f"Pexels error: {e}")
        
        return False
    
    def fetch_broll_parallel(self, prompts: List[tuple]) -> List[Optional[str]]:
        """Fetch multiple B-roll images in parallel."""
        logger_assets.info(f"Fetching {len(prompts)} B-roll images in parallel")
        broll_paths = [None] * len(prompts)
        
        with ThreadPoolExecutor(max_workers=config.PARALLEL_DOWNLOADS) as executor:
            futures = {}
            for i, prompt in prompts:
                future = executor.submit(self.fetch_broll, prompt, i)
                futures[future] = i
            
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    broll_paths[idx] = result
                except Exception as e:
                    logger_assets.error(f"Error fetching B-roll {idx}: {e}")
        
        return broll_paths
    
    def fetch_background_music(self) -> Optional[str]:
        """Download royalty-free background music."""
        logger_assets.info("Fetching background music...")
        
        selected_url = random.choice(self.MUSIC_URLS)
        dest = str(config.ASSETS_DIR / "bg_music.mp3")
        
        if download_file(selected_url, dest, timeout=60):
            logger_assets.info(f"Background music downloaded: {dest}")
            return dest
        
        logger_assets.warning("Failed to download background music")
        return None
    
    def fetch_sfx(self, sfx_type: str) -> Optional[str]:
        """Download sound effects (whoosh, pop, notification)."""
        sfx_urls = {
            "whoosh": "https://cdn.pixabay.com/download/audio/2022/03/24/audio_c8c8a73467.mp3",
            "pop": "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3",
            "notification": "https://cdn.pixabay.com/download/audio/2022/04/27/audio_c8c8a73467.mp3"
        }
        
        url = sfx_urls.get(sfx_type)
        if not url:
            return None
        
        dest = str(config.ASSETS_DIR / f"sfx_{sfx_type}.mp3")
        if download_file(url, dest, timeout=30):
            logger_assets.info(f"SFX downloaded: {sfx_type}")
            return dest
        
        return None
