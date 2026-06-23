#!/usr/bin/env python3
"""
Ajeebology Shorts - Research Agent
Fetches fresh facts using Tavily Search API
"""

import random
from typing import Dict, Optional
import requests
from logger import logger_research
from config import config
from utils import RetryConfig, run_command


class ResearchAgent:
    """Fetches fresh, engaging facts for video scripts."""
    
    CATEGORIES = ["psychology", "space", "weird_facts"]
    
    QUERIES = {
        "psychology": [
            "mind blowing psychology facts human behavior 2026",
            "psychology tricks brain facts hindi urdu",
            "interesting psychological phenomena daily life",
            "cognitive biases that affect human behavior",
            "neuroscience discoveries mind brain"
        ],
        "space": [
            "amazing space facts universe secrets 2026",
            "space discoveries recent mind blowing",
            "astronomy facts that will blow your mind",
            "cosmic mysteries unexplained phenomena",
            "facts about black holes neutron stars"
        ],
        "weird_facts": [
            "unbelievable facts about world strange but true",
            "weird facts that sound fake but are true",
            "amazing facts about earth animals humans",
            "strange natural phenomena explained",
            "bizarre animal behaviors and abilities"
        ]
    }
    
    FALLBACK_DATA = {
        "psychology": {
            "title": "Psychology Facts That Will Blow Your Mind",
            "content": "Your brain can process images in just 13 milliseconds. The human mind is capable of creating false memories that feel completely real. Smiling can actually make you feel happier due to facial feedback hypothesis.",
            "category": "psychology",
            "url": "https://example.com"
        },
        "space": {
            "title": "Space Secrets You Never Knew",
            "content": "A day on Venus is longer than its year. Neutron stars can spin 600 times per second. There are more trees on Earth than stars in the Milky Way galaxy.",
            "category": "space",
            "url": "https://example.com"
        },
        "weird_facts": {
            "title": "Weird Facts That Sound Fake",
            "content": "Honey never spoils. Wombat poop is cube-shaped. Bananas are berries but strawberries are not. Octopuses have three hearts and blue blood.",
            "category": "weird_facts",
            "url": "https://example.com"
        }
    }
    
    def __init__(self):
        self.api_key = config.TAVILY_API_KEY
        self.base_url = "https://api.tavily.com/search"
        logger_research.info("ResearchAgent initialized")
    
    def fetch_fact(self, category: Optional[str] = None) -> Dict:
        """Fetch fresh fact from Tavily API with fallback support."""
        if not category:
            category = random.choice(self.CATEGORIES)
        
        logger_research.info(f"Fetching fact for category: {category}")
        
        query = random.choice(self.QUERIES.get(category, self.QUERIES["weird_facts"]))
        logger_research.debug(f"Query: {query}")
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "max_results": 5
        }
        
        try:
            resp = requests.post(
                self.base_url, json=payload, headers=headers, 
                timeout=config.REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            
            results = data.get("results", [])
            if results:
                best = max(results, key=lambda x: len(x.get("content", "")))
                fact_data = {
                    "category": category,
                    "title": best.get("title", "Interesting Fact"),
                    "content": best.get("content", ""),
                    "url": best.get("url", ""),
                    "query": query
                }
                logger_research.info(f"Successfully fetched fact: {fact_data['title'][:50]}...")
                return fact_data
        
        except requests.exceptions.RequestException as e:
            logger_research.warning(f"API request failed: {e}")
        except Exception as e:
            logger_research.error(f"Unexpected error: {e}", exc_info=True)
        
        # Return fallback data
        logger_research.info(f"Using fallback data for category: {category}")
        return self.FALLBACK_DATA.get(category, self.FALLBACK_DATA["weird_facts"])
