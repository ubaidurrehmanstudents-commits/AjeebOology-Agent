#!/usr/bin/env python3
"""
Ajeebology Shorts - Structured Logging Module
"""

import logging
import json
from pathlib import Path
from datetime import datetime
from config import config


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        log_path = config.LOGS_DIR / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)
        json_formatter = JSONFormatter()
        file_handler.setFormatter(json_formatter)
        logger.addHandler(file_handler)
    
    return logger


logger_research = setup_logger("ajeebology.research", "research.log")
logger_script = setup_logger("ajeebology.script", "script.log")
logger_voice = setup_logger("ajeebology.voice", "voice.log")
logger_assets = setup_logger("ajeebology.assets", "assets.log")
logger_video = setup_logger("ajeebology.video", "video.log")
logger_delivery = setup_logger("ajeebology.delivery", "delivery.log")
logger_pipeline = setup_logger("ajeebology.pipeline", "pipeline.log")
