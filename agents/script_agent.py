#!/usr/bin/env python3
"""
Ajeebology Shorts - Script Generation Agent
Generates engaging Hinglish scripts using Groq LLaMA
"""

import json
import re
from typing import Dict, List
from dataclasses import dataclass
import requests
from logger import logger_script
from config import config


@dataclass
class ScriptSegment:
    """Individual segment of a video script."""
    text: str
    segment_type: str  # hook, fact1, fact2, fact3, outro
    emphasis_words: List[str] = None
    broll_prompt: str = ""
    
    def __post_init__(self):
        if self.emphasis_words is None:
            self.emphasis_words = []


@dataclass
class VideoScript:
    """Complete video script with metadata."""
    title: str
    category: str
    seo_title: str
    description: str
    tags: List[str]
    hashtags: List[str]
    segments: List[ScriptSegment]
    total_duration_estimate: float = 0.0


class ScriptAgent:
    """Generates professional Hinglish scripts for YouTube Shorts."""
    
    SYSTEM_PROMPT = """You are a professional YouTube Shorts scriptwriter for 'Ajeebology Shorts'.
Your scripts are in HINGLISH (Roman Hindi + English mix), engaging, fast-paced, optimized for viral growth.

RULES:
1. Write in Hinglish (Roman script Hindi mixed with English words)
2. Target 55-60 seconds when spoken naturally at normal pace
3. HOOK must be attention-grabbing in first 2 seconds
4. Each FACT should be mind-blowing and concise
5. OUTRO must have strong CTA (subscribe, comment, share)
6. Mark EMPHASIS words with [WORD] brackets
7. Keep sentences short and punchy for retention
8. Use conversational tone like talking to a friend

RETURN ONLY valid JSON:
{
    "title": "Hinglish title",
    "category": "psychology|space|weird_facts",
    "seo_title": "English SEO title",
    "description": "English description",
    "tags": ["tag1"],
    "hashtags": ["#tag1"],
    "segments": [
        {"type": "hook", "text": "Text with [emphasis]", "broll_prompt": "image search query"}
    ]
}"""
    
    FALLBACK_SCRIPTS = {
        "psychology": {
            "title": "Brain Ke Secrets",
            "category": "psychology",
            "seo_title": "Mind-Blowing Psychology Facts You Need To Know",
            "description": "Amazing psychology facts in Hinglish. Subscribe for daily mind-blowing content!",
            "tags": ["psychology", "facts", "hinglish", "brain", "mind"],
            "hashtags": ["#psychology", "#facts", "#hinglish", "#viral", "#shorts"],
            "segments": [
                {"type": "hook", "text": "Kya aap jaante hain aapka brain har [13 milliseconds] mein ek image process kar sakta hai?", "broll_prompt": "human brain neural pathways"},
                {"type": "fact1", "text": "Psychology ke ek experiment mein researchers ne dekha ki [false memories] create karna kitna aasan hai.", "broll_prompt": "psychology experiment memory"},
                {"type": "fact2", "text": "Agar aap forcefully [smile] karte hain, toh aapka brain automatically [happy hormones] release kar deta hai.", "broll_prompt": "person smiling happy"},
                {"type": "fact3", "text": "Aur ek study ke mutabik, aapke decisions ka [90 percent] aapke subconscious mind control karta hai.", "broll_prompt": "subconscious mind brain thinking"},
                {"type": "outro", "text": "Agar ye facts pasand aaye toh [subscribe] karo aur comments mein batao aapko kaunsa fact sabse zyada shocking laga!", "broll_prompt": "youtube subscribe button"}
            ]
        },
        "space": {
            "title": "Space Ke Mysteries",
            "category": "space",
            "seo_title": "Amazing Space Facts That Will Blow Your Mind",
            "description": "Mind-blowing space facts in Hinglish. Learn about the universe!",
            "tags": ["space", "astronomy", "facts", "universe", "shorts"],
            "hashtags": ["#space", "#astronomy", "#facts", "#universe", "#viral"],
            "segments": [
                {"type": "hook", "text": "Venus par ek din [243 Earth days] ka hota hai, lekin iska saal sirf [225 days] ka hai!", "broll_prompt": "venus planet space"},
                {"type": "fact1", "text": "Neutron stars itni tezi se spin karti hain ki ek second mein [600 baar] ghoom jaati hain.", "broll_prompt": "neutron star spinning space"},
                {"type": "fact2", "text": "Earth par [Milky Way] ke stars se zyada trees hain. Sochiye!", "broll_prompt": "milky way galaxy stars"},
                {"type": "fact3", "text": "Space mein ek [giant cloud] hai jo [alcohol] se bana hai, jiski value [1000 trillion dollars] hai.", "broll_prompt": "space nebula clouds"},
                {"type": "outro", "text": "Aur bhi amazing space facts ke liye [follow] karo Ajeebology Shorts ko aaj hi!", "broll_prompt": "space astronaut earth"}
            ]
        },
        "weird_facts": {
            "title": "Duniya Ke Ajeeb Raaz",
            "category": "weird_facts",
            "seo_title": "Unbelievable Weird Facts You Never Knew",
            "description": "Crazy weird facts that sound fake but are 100% true!",
            "tags": ["weird", "facts", "amazing", "strange", "viral"],
            "hashtags": ["#weird", "#facts", "#amazing", "#strange", "#viral"],
            "segments": [
                {"type": "hook", "text": "Honey kabhi [spoil] nahi hota! Archaeologists ne [3000 saal] purana honey khaya tha!", "broll_prompt": "honey jar ancient"},
                {"type": "fact1", "text": "Wombat ka poop [cube-shaped] hota hai. Nature ka sabse weird phenomenon!", "broll_prompt": "wombat animal australia"},
                {"type": "fact2", "text": "Banana technically ek [berry] hai, lekin strawberry nahi! Sochiye na!", "broll_prompt": "banana fruit close up"},
                {"type": "fact3", "text": "Octopus ke paas [teen dil] hain aur unka blood [blue] hota hai!", "broll_prompt": "octopus underwater ocean"},
                {"type": "outro", "text": "Aise hi [mind-blowing] facts ke liye channel ko [subscribe] karo!", "broll_prompt": "shocked surprised face"}
            ]
        }
    }
    
    def __init__(self):
        self.api_key = config.GROQ_API_KEY
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        logger_script.info("ScriptAgent initialized")
    
    def generate_script(self, research_data: Dict) -> VideoScript:
        """Generate complete video script from research data."""
        logger_script.info(f"Generating script for: {research_data.get('title', 'Unknown')}")
        
        user_prompt = f"""Create a viral YouTube Shorts script based on this research:
Category: {research_data.get('category', 'weird_facts')}
Title: {research_data.get('title', 'Unknown')}
Content: {research_data.get('content', '')}

Make it engaging, mind-blowing, and perfect for Hinglish-speaking audience aged 13-35."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.8,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"}
        }
        
        try:
            logger_script.debug("Calling Groq API...")
            resp = requests.post(
                self.base_url, json=payload, headers=headers, 
                timeout=config.REQUEST_TIMEOUT + 30
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            script_data = json.loads(content)
            
            logger_script.info(f"Script generated successfully")
            return self._parse_script(script_data)
        
        except Exception as e:
            logger_script.warning(f"Script generation failed: {e}. Using fallback.")
            return self._fallback_script(research_data)
    
    def _parse_script(self, data: Dict) -> VideoScript:
        """Parse JSON into VideoScript object."""
        segments = []
        for seg_data in data.get("segments", []):
            text = seg_data.get("text", "")
            emphasis = re.findall(r'\[(.*?)\]', text)
            clean_text = re.sub(r'\[(.*?)\]', r'\1', text)
            
            segments.append(ScriptSegment(
                text=clean_text,
                segment_type=seg_data.get("type", "fact"),
                emphasis_words=emphasis,
                broll_prompt=seg_data.get("broll_prompt", "")
            ))
        
        return VideoScript(
            title=data.get("title", "Amazing Facts"),
            category=data.get("category", "weird_facts"),
            seo_title=data.get("seo_title", "Mind Blowing Facts"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            hashtags=data.get("hashtags", []),
            segments=segments
        )
    
    def _fallback_script(self, research: Dict) -> VideoScript:
        """Return fallback script when API fails."""
        category = research.get("category", "weird_facts")
        fallback = self.FALLBACK_SCRIPTS.get(category, self.FALLBACK_SCRIPTS["weird_facts"])
        
        segments = []
        for seg_data in fallback["segments"]:
            text = seg_data["text"]
            emphasis = re.findall(r'\[(.*?)\]', text)
            clean_text = re.sub(r'\[(.*?)\]', r'\1', text)
            segments.append(ScriptSegment(
                text=clean_text,
                segment_type=seg_data["type"],
                emphasis_words=emphasis,
                broll_prompt=seg_data.get("broll_prompt", "")
            ))
        
        return VideoScript(
            title=fallback["title"],
            category=fallback["category"],
            seo_title=fallback["seo_title"],
            description=fallback["description"],
            tags=fallback["tags"],
            hashtags=fallback["hashtags"],
            segments=segments
        )
