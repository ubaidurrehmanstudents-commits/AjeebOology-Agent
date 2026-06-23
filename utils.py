#!/usr/bin/env python3
"""
Ajeebology Shorts - Utility Functions
"""

import os
import re
import subprocess
import hashlib
import time
from pathlib import Path
from typing import Tuple, List
from urllib.parse import quote_plus

import requests
from logger import logger_pipeline
from config import config


class RetryConfig:
    def __init__(self, max_attempts: int = 3, initial_delay: int = 2, backoff: float = 2.0):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.backoff = backoff


def run_command(cmd: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger_pipeline.error(f"Command timed out after {timeout}s: {' '.join(cmd)}")
        return -1, "", "Command timed out"
    except Exception as e:
        logger_pipeline.error(f"Command execution failed: {e}")
        return -1, "", str(e)


def get_audio_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path
    ]
    rc, out, _ = run_command(cmd)
    if rc == 0 and out.strip():
        try:
            return float(out.strip())
        except ValueError:
            return 0.0
    return 0.0


def download_file(url: str, dest: str, timeout: int = 30, retry_config: RetryConfig = None) -> bool:
    if retry_config is None:
        retry_config = RetryConfig()
    
    delay = retry_config.initial_delay
    for attempt in range(retry_config.max_attempts):
        try:
            logger_pipeline.debug(f"Downloading {url} (attempt {attempt + 1})")
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                logger_pipeline.info(f"Downloaded to {dest}")
                return True
        except requests.exceptions.RequestException as e:
            logger_pipeline.warning(f"Download attempt {attempt + 1} failed: {e}")
        if attempt < retry_config.max_attempts - 1:
            time.sleep(delay)
            delay *= retry_config.backoff
    return False


def safe_filename(text: str, max_length: int = 50) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', text)[:max_length]
    return safe


def get_file_hash(path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_file_size(bytes_size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"


def cleanup_directory(path: str, pattern: str = "*", keep_count: int = 0):
    try:
        p = Path(path)
        files = sorted(p.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
        for file in files[keep_count:]:
            file.unlink()
            logger_pipeline.debug(f"Deleted {file}")
    except Exception as e:
        logger_pipeline.warning(f"Cleanup failed for {path}: {e}")


def get_ffmpeg_version() -> str:
    rc, out, _ = run_command(["ffmpeg", "-version"])
    if rc == 0:
        return out.split('\n')[0] if out else "Unknown"
    return "Not installed"
