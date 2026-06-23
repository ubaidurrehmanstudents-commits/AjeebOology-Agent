#!/usr/bin/env python3
"""
Ajeebology Shorts - Main Pipeline Orchestrator
Coordinates all agents to produce complete videos
"""

import os
import sys
from datetime import datetime

from logger import logger_pipeline
from config import config
from utils import format_duration, format_file_size, get_system_info, cleanup_directory

from agents.research_agent import ResearchAgent
from agents.script_agent import ScriptAgent
from agents.voice_agent import VoiceAgent
from agents.asset_agent import AssetAgent
from engine.video_engine import VideoEngine
from delivery.telegram_agent import TelegramAgent


class AjeebologyPipeline:
    """Main pipeline orchestrator for video generation."""
    
    def __init__(self):
        logger_pipeline.info("="*80)
        logger_pipeline.info("AJEEBOLOGY SHORTS - AUTOMATION PIPELINE INITIALIZED")
        logger_pipeline.info("="*80)
        
        # Initialize all agents
        self.researcher = ResearchAgent()
        self.script_writer = ScriptAgent()
        self.voice_gen = VoiceAgent()
        self.asset_fetcher = AssetAgent()
        self.video_engine = VideoEngine()
        self.telegram = TelegramAgent()
        
        logger_pipeline.info("All agents initialized successfully")
    
    def run(self) -> bool:
        """Execute full pipeline from research to delivery."""
        start_time = datetime.now()
        logger_pipeline.info(f"Pipeline started at {start_time}")
        
        try:
            # Step 1: Setup
            logger_pipeline.info("\n[1/8] Setting up directories...")
            config.create_directories()
            logger_pipeline.info("Directories created successfully")
            
            # Step 2: Validate configuration
            logger_pipeline.info("\n[2/8] Validating configuration...")
            is_valid, msg = config.validate()
            if not is_valid:
                logger_pipeline.error(f"Configuration invalid: {msg}")
                return False
            logger_pipeline.info(f"Configuration valid: {msg}")
            
            # Log system info
            sys_info = get_system_info()
            logger_pipeline.info(f"System info: {sys_info}")
            
            # Step 3: Research
            logger_pipeline.info("\n[3/8] Researching fresh facts...")
            research_data = self.researcher.fetch_fact()
            logger_pipeline.info(f"Category: {research_data.get('category')}")
            logger_pipeline.info(f"Topic: {research_data.get('title')}")
            
            # Step 4: Generate Script
            logger_pipeline.info("\n[4/8] Generating Hinglish script...")
            script = self.script_writer.generate_script(research_data)
            logger_pipeline.info(f"Script title: {script.title}")
            logger_pipeline.info(f"Segments: {len(script.segments)}")
            for i, seg in enumerate(script.segments):
                logger_pipeline.debug(f"  [{seg.segment_type}] {seg.text[:60]}...")
            
            # Step 5: Generate Voice
            logger_pipeline.info("\n[5/8] Generating voiceover...")
            audio_segments = self.voice_gen.generate_voice(script)
            total_voice_duration = sum(seg.duration for seg in audio_segments)
            logger_pipeline.info(f"Total voice duration: {format_duration(total_voice_duration)}")
            
            # Step 6: Fetch Assets
            logger_pipeline.info("\n[6/8] Fetching B-roll and music...")
            broll_paths = []
            for i, seg in enumerate(script.segments):
                if seg.broll_prompt:
                    path = self.asset_fetcher.fetch_broll(seg.broll_prompt, i)
                    broll_paths.append(path)
                    if path:
                        logger_pipeline.info(f"  ✓ B-roll {i}: {seg.broll_prompt[:40]}...")
                    else:
                        logger_pipeline.warning(f"  ✗ B-roll {i}: Failed")
                else:
                    broll_paths.append(None)
            
            bg_music = self.asset_fetcher.fetch_background_music()
            if bg_music:
                logger_pipeline.info("  ✓ Background music downloaded")
            else:
                logger_pipeline.warning("  ✗ Background music failed")
            
            # Step 7: Mix Audio
            logger_pipeline.info("\n[7/8] Mixing audio...")
            final_audio = self.voice_gen.mix_audio(audio_segments, bg_music)
            logger_pipeline.info(f"Final audio: {final_audio}")
            final_duration = self.voice_gen._estimate_duration(" ".join([s.segment.text for s in audio_segments]))
            logger_pipeline.info(f"Estimated duration: {format_duration(final_duration)}s")
            
            # Step 8: Render Video
            logger_pipeline.info("\n[8/8] Rendering professional video...")
            logger_pipeline.info("This may take 5-10 minutes on GitHub Actions...")
            video_path = self.video_engine.render_video(
                script, audio_segments, broll_paths, final_audio
            )
            logger_pipeline.info(f"Video rendered: {video_path}")
            
            file_size = os.path.getsize(video_path)
            logger_pipeline.info(f"File size: {format_file_size(file_size)}")
            
            # Step 9: Deliver
            logger_pipeline.info("\n[9/9] Sending to Telegram...")
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            artifact_url = ""
            if run_id and repo:
                artifact_url = f"https://github.com/{repo}/actions/runs/{run_id}"
            
            success = self.telegram.send_video(video_path, script, artifact_url)
            if success:
                logger_pipeline.info("Telegram delivery successful!")
            else:
                logger_pipeline.warning("Telegram delivery failed or file too large")
            
            # Step 10: Cleanup
            logger_pipeline.info("\n[10/10] Cleaning up temporary files...")
            cleanup_directory(str(config.FRAMES_DIR))
            cleanup_directory(str(config.AUDIO_DIR))
            logger_pipeline.info("Temporary files cleaned up")
            
            # Summary
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger_pipeline.info("\n" + "="*80)
            logger_pipeline.info("PIPELINE COMPLETED SUCCESSFULLY! ✅")
            logger_pipeline.info("="*80)
            logger_pipeline.info(f"Total pipeline duration: {format_duration(duration)}")
            logger_pipeline.info(f"Video file: {video_path}")
            logger_pipeline.info(f"File size: {format_file_size(file_size)}")
            logger_pipeline.info(f"Video duration: {format_duration(final_duration)}")
            logger_pipeline.info(f"End time: {end_time}")
            
            return True
        
        except Exception as e:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger_pipeline.error("\n" + "="*80)
            logger_pipeline.error("PIPELINE FAILED! ❌")
            logger_pipeline.error("="*80)
            logger_pipeline.error(f"Error: {e}", exc_info=True)
            logger_pipeline.error(f"Pipeline duration before failure: {format_duration(duration)}")
            
            return False


if __name__ == "__main__":
    pipeline = AjeebologyPipeline()
    success = pipeline.run()
    sys.exit(0 if success else 1)
