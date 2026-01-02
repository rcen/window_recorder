"""
Gemini AI Productivity Coach
============================
Uses Google Gemini Pro to provide personalized productivity coaching
for software developers.

Features:
- Contextual advice based on current productivity stats
- Time-aware recommendations (morning vs afternoon strategies)
- Rest day vs workday appropriate messaging
- Historical pattern recognition
- Encouraging, supportive tone

Setup:
1. Get API key from https://makersuite.google.com/app/apikey
2. Set environment variable: GEMINI_API_KEY=your_key
   Or add to config.dat under [GEMINI] section:
   api_key = your_key

Usage:
    from gemini_coach import GeminiCoach
    coach = GeminiCoach()
    advice = coach.get_coaching(productivity_stats)
"""

import os
import json
import time
import datetime
import configparser
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path

from categories import aggregate_stats

# Try to import the new google.genai package (replaces deprecated google.generativeai)
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[GeminiCoach] Warning: google-genai not installed. Run: pip install google-genai")


@dataclass
class CoachingContext:
    """Context for generating coaching advice."""
    current_stats: Dict[str, float]  # Category -> minutes
    goals: Dict[str, float]  # Category -> target minutes
    time_of_day: str  # "morning", "afternoon", "evening"
    day_type: str  # "workday", "weekend", "holiday"
    rest_reason: Optional[str] = None
    waste_ratio: float = 0.0
    focus_streak: float = 0.0
    best_streak: float = 0.0
    hours_remaining: float = 0.0
    historical_insights: Optional[Dict] = None


class GeminiCoach:
    """AI-powered productivity coach using Google Gemini."""
    
    SYSTEM_PROMPT = """You are an expert productivity coach for software developers. Your name is "Dev Coach".

Your personality:
- Professional and direct, never patronizing or overly cheerful
- Practical, evidence-based advice grounded in productivity research
- Understanding of developer challenges (context switching, debugging frustration, meeting fatigue)
- Acknowledges progress factually without excessive praise
- Uses developer-friendly analogies (commits, refactoring, debugging)

Your coaching style:
- Keep responses concise (2-3 sentences max)
- Be specific and data-driven based on the current metrics
- Focus on the next actionable step
- Avoid cheerleader phrases like "You got this!", "Amazing!", "Awesome!", "Great job!"
- Use a calm, focused tone like a senior engineer giving advice
- Use emojis very sparingly (max 1 per response, only if it adds clarity)

Key principles you follow:
1. Deep work blocks are precious - protect them
2. Regular breaks improve overall output
3. Learning compounds over time
4. Some waste time is healthy and necessary
5. Consistency beats intensity
6. Morning hours are golden for complex work
7. Energy management > time management
8. Idle time is normal - it represents time away from the computer, NOT lost productivity

IMPORTANT: Never criticize idle time. Users are not expected to be at their computer continuously.
Focus your coaching on the ACTIVE time distribution, not total time.

Remember: You're a professional coach, not a cheerleader. Be direct, helpful, and respect the developer's intelligence."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Gemini coach."""
        self.api_key = api_key or self._load_api_key()
        self.client = None
        self.enabled = False
        self.cache_file = Path("data/coach_cache.json")
        self._advice_cache_file = Path("data/coach_advice_cache.json")
        self._last_advice_time = 0
        self._cached_advice = None
        self._cached_context_hash = None
        self._advice_cooldown = 1800  # 30 minutes between API calls (was 5 min)
        
        # Model fallback chain - try each in order if quota exhausted
        self._model_fallbacks = [
            'gemma-3-27b-it',   # Primary: largest Gemma, best quality
            'gemma-3-12b-it',   # Fallback 1: good balance of speed/quality
            'gemma-3-4b-it',    # Fallback 2: smaller, faster
            'gemini-2.0-flash', # Fallback 3: try Gemini if Gemma exhausted
            'gemini-2.5-flash', # Fallback 4: latest Gemini flash
        ]
        self._model_name = self._model_fallbacks[0]
        
        if not GEMINI_AVAILABLE:
            print("[GeminiCoach] Gemini library not available")
            return
            
        if not self.api_key:
            print("[GeminiCoach] No API key found. Set GEMINI_API_KEY or add to config.dat")
            return
        
        try:
            self.client = genai.Client(api_key=self.api_key)
            self.enabled = True
            print(f"[GeminiCoach] Initialized successfully with {self._model_name}")
        except Exception as e:
            print(f"[GeminiCoach] Failed to initialize: {e}")
    
    def _load_api_key(self) -> Optional[str]:
        """Load API key from environment or config file."""
        # Try environment variable first
        api_key = os.environ.get('GEMINI_API_KEY')
        if api_key:
            return api_key
        
        # Try config.dat
        config_path = Path("config.dat")
        if config_path.exists():
            config = configparser.ConfigParser()
            config.read(config_path)
            if config.has_option('GEMINI', 'api_key'):
                return config.get('GEMINI', 'api_key')
        
        return None
    
    def _get_time_of_day(self) -> str:
        """Get current time period."""
        hour = datetime.datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"
    
    def _build_context_prompt(self, context: CoachingContext) -> str:
        """Build the context prompt for Gemini."""
        # Format current stats - exclude idle time (it's just time away from computer)
        # Categories to exclude from coaching analysis
        excluded_cats = {'idle', 'sperrbildschirm'}  # idle, lock screen
        
        stats_str = "\n".join([
            f"  - {cat}: {mins:.0f} min" 
            for cat, mins in context.current_stats.items() 
            if mins > 0 and cat.lower() not in excluded_cats
        ])
        
        goals_str = "\n".join([
            f"  - {cat}: {target:.0f} min target"
            for cat, target in context.goals.items()
        ])
        
        prompt = f"""Current Situation:
Time: {datetime.datetime.now().strftime('%H:%M')} ({context.time_of_day})
Day Type: {context.day_type}
{f'Rest Reason: {context.rest_reason}' if context.rest_reason else ''}

Today's Activity:
{stats_str if stats_str else '  (No activity recorded yet)'}

Goals:
{goals_str}

Metrics:
- Waste Ratio: {context.waste_ratio:.1f}%
- Current Focus Streak: {context.focus_streak:.0f} min
- Best Streak Today: {context.best_streak:.0f} min
- Hours Remaining in Workday: {context.hours_remaining:.1f}h

{self._get_situation_specific_context(context)}

Based on this context, provide brief, encouraging coaching advice (2-3 sentences max)."""
        
        return prompt
    
    def _get_situation_specific_context(self, context: CoachingContext) -> str:
        """Add situation-specific context based on patterns."""
        situations = []
        
        # Check various situations
        work_mins = aggregate_stats(context.current_stats, 'work')
        wasted_mins = context.current_stats.get('wasted', 0)
        learning_mins = context.current_stats.get('learning', 0)
        
        work_goal = context.goals.get('work', 240)
        
        # Morning with no work yet
        if context.time_of_day == "morning" and work_mins < 30:
            situations.append("Developer hasn't started deep work yet this morning.")
        
        # Good progress
        if work_mins >= work_goal * 0.7:
            situations.append("Developer is making excellent progress on coding goals!")
        
        # High waste ratio
        if context.waste_ratio > 30:
            situations.append("Waste ratio is getting high - may need a focus reset.")
        
        # Great focus streak
        if context.focus_streak > 30:
            situations.append(f"Currently on a great {context.focus_streak:.0f} min focus streak!")
        
        # Rest day context
        if context.day_type in ("weekend", "holiday"):
            situations.append("It's a rest day - balance is important, be gentle.")
        
        # Late in day, behind on goals
        if context.hours_remaining < 3 and coding_mins < coding_goal * 0.5:
            situations.append("Limited time remaining and behind on coding goals.")
        
        # Learning achievement
        if learning_mins > 30:
            situations.append(f"Great learning investment today: {learning_mins:.0f} min!")
        
        if situations:
            return "Observations:\n" + "\n".join(f"- {s}" for s in situations)
        return ""
    
    def get_coaching(
        self,
        stats: Dict[str, float],
        goals: Dict[str, float],
        is_rest_day: bool = False,
        rest_reason: str = "",
        waste_ratio: float = 0.0,
        focus_streak: float = 0.0,
        best_streak: float = 0.0,
    ) -> str:
        """Get AI coaching advice based on current productivity stats.
        
        Args:
            stats: Current activity statistics (category -> minutes)
            goals: Goal targets (category -> target minutes)
            is_rest_day: Whether it's a weekend/holiday
            rest_reason: Why it's a rest day
            waste_ratio: Current waste percentage
            focus_streak: Current focus streak in minutes
            best_streak: Best streak today in minutes
            
        Returns:
            Coaching advice string
        """
        if not self.enabled:
            return self._get_fallback_advice(stats, goals, is_rest_day)
        
        # Calculate hours remaining (assume 7 AM - 11 PM workday)
        now = datetime.datetime.now()
        work_end = 23  # 11 PM
        hours_remaining = max(0, work_end - now.hour - now.minute / 60)
        
        context = CoachingContext(
            current_stats=stats,
            goals=goals,
            time_of_day=self._get_time_of_day(),
            day_type="holiday" if "Holiday" in rest_reason else ("weekend" if is_rest_day else "workday"),
            rest_reason=rest_reason if is_rest_day else None,
            waste_ratio=waste_ratio,
            focus_streak=focus_streak,
            best_streak=best_streak,
            hours_remaining=hours_remaining,
        )
        
        # Check if we can use cached advice
        context_hash = self._get_context_hash(context)
        cached = self._load_cached_advice()
        
        if cached:
            cache_age = time.time() - cached.get('timestamp', 0)
            cached_hash = cached.get('context_hash', '')
            
            # Use cache if: less than 30 min old AND situation hasn't changed drastically
            if cache_age < self._advice_cooldown:
                # Check if situation changed significantly
                if self._is_similar_context(context_hash, cached_hash):
                    print(f"[GeminiCoach] Using cached advice ({cache_age/60:.0f} min old)")
                    return cached.get('advice', self._get_fallback_advice(stats, goals, is_rest_day))
                else:
                    print(f"[GeminiCoach] Context changed significantly, will refresh")
        
        # Call API for fresh advice - try models in fallback order
        prompt = self._build_context_prompt(context)
        full_prompt = f"{self.SYSTEM_PROMPT}\n\n---\n\n{prompt}"
        
        last_error = None
        for model in self._model_fallbacks:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        top_p=0.9,
                        max_output_tokens=200,
                    )
                )
                
                advice = response.text.strip()
                
                # Update current model if fallback succeeded
                if model != self._model_name:
                    print(f"[GeminiCoach] Switched to {model} (primary exhausted)")
                    self._model_name = model
                
                # Cache the advice
                self._save_cached_advice(advice, context_hash)
                self._cache_advice(context, advice)
                
                return advice
                
            except Exception as e:
                last_error = e
                err_str = str(e)
                if '429' in err_str or 'quota' in err_str.lower():
                    print(f"[GeminiCoach] {model} quota exhausted, trying next...")
                    continue
                else:
                    # Non-quota error, don't try other models
                    print(f"[GeminiCoach] API error with {model}: {e}")
                    break
        
        # All models failed
        print(f"[GeminiCoach] All models exhausted or failed: {last_error}")
        # Try to return stale cache if available
        if cached and cached.get('advice'):
            print("[GeminiCoach] Returning stale cached advice")
            return cached['advice']
        return self._get_fallback_advice(stats, goals, is_rest_day)
    
    def _get_context_hash(self, context: CoachingContext) -> str:
        """Create a hash representing the current context situation."""
        # Round values to reduce sensitivity to minor changes
        work = round((context.current_stats.get('work', 0) +
                     context.current_stats.get('coding', 0) + 
                     context.current_stats.get('programming', 0)) / 30) * 30  # Round to 30 min
        wasted = round(context.current_stats.get('wasted', 0) / 15) * 15  # Round to 15 min
        waste_ratio_bucket = "low" if context.waste_ratio < 15 else ("mid" if context.waste_ratio < 30 else "high")
        streak_bucket = "none" if context.focus_streak < 10 else ("short" if context.focus_streak < 30 else "long")
        
        return f"{context.day_type}:{context.time_of_day}:{work}:{wasted}:{waste_ratio_bucket}:{streak_bucket}"
    
    def _is_similar_context(self, current_hash: str, cached_hash: str) -> bool:
        """Check if two context hashes are similar enough to reuse advice."""
        if not cached_hash:
            return False
        
        current_parts = current_hash.split(':')
        cached_parts = cached_hash.split(':')
        
        if len(current_parts) != len(cached_parts):
            return False
        
        # Must match: day_type, time_of_day
        if current_parts[0] != cached_parts[0]:  # day_type
            return False
        if current_parts[1] != cached_parts[1]:  # time_of_day
            return False
        
        # Allow some variance in numeric values
        # coding can differ by 1 bucket (30 min)
        # wasted can differ by 1 bucket (15 min)
        try:
            coding_diff = abs(int(current_parts[2]) - int(cached_parts[2]))
            wasted_diff = abs(int(current_parts[3]) - int(cached_parts[3]))
            if coding_diff > 30 or wasted_diff > 30:
                return False
        except ValueError:
            return False
        
        return True
    
    def _load_cached_advice(self) -> Optional[Dict]:
        """Load cached advice from file."""
        try:
            if self._advice_cache_file.exists():
                with open(self._advice_cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return None
    
    def _save_cached_advice(self, advice: str, context_hash: str) -> None:
        """Save advice to cache file."""
        try:
            self._advice_cache_file.parent.mkdir(exist_ok=True)
            with open(self._advice_cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': time.time(),
                    'advice': advice,
                    'context_hash': context_hash,
                    'datetime': datetime.datetime.now().isoformat(),
                }, f, indent=2)
        except IOError as e:
            print(f"[GeminiCoach] Cache save error: {e}")
    
    def _get_fallback_advice(
        self, 
        stats: Dict[str, float], 
        goals: Dict[str, float],
        is_rest_day: bool
    ) -> str:
        """Fallback advice when Gemini is unavailable."""
        work = aggregate_stats(stats, 'work')
        wasted = stats.get('wasted', 0)
        work_goal = goals.get('work', 240)
        
        time_of_day = self._get_time_of_day()
        
        if is_rest_day:
            return "🌴 Rest days are for recharging. A little work is fine, but don't forget to enjoy yourself!"
        
        if time_of_day == "morning" and work < 30:
            return "🌅 Morning is golden time for deep work. Try starting with your most challenging task!"
        
        if work >= work_goal:
            return "🎉 Amazing! You've hit your work goal. Consider some learning time or a well-deserved break!"
        
        if wasted > 60:
            return "🔄 Time for a reset? Try the 2-minute rule: pick one small task and complete it."
        
        progress = work / work_goal if work_goal > 0 else 0
        if progress >= 0.7:
            return f"💪 Great progress at {progress*100:.0f}%! You're in the home stretch - keep the momentum!"
        
        return "🚀 Every line of code counts. What's the smallest useful thing you can build right now?"
    
    def _cache_advice(self, context: CoachingContext, advice: str) -> None:
        """Cache advice for analytics/improvement."""
        try:
            cache = []
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
            
            cache.append({
                'timestamp': datetime.datetime.now().isoformat(),
                'time_of_day': context.time_of_day,
                'day_type': context.day_type,
                'waste_ratio': context.waste_ratio,
                'focus_streak': context.focus_streak,
                'advice': advice,
            })
            
            # Keep last 100 entries
            cache = cache[-100:]
            
            self.cache_file.parent.mkdir(exist_ok=True)
            with open(self.cache_file, 'w') as f:
                json.dump(cache, f, indent=2)
                
        except Exception as e:
            print(f"[GeminiCoach] Cache error: {e}")
    
    def get_daily_summary(self, stats: Dict[str, float], goals: Dict[str, float]) -> str:
        """Get an end-of-day summary and reflection."""
        if not self.enabled:
            return self._get_fallback_summary(stats, goals)
        
        prompt = f"""Generate a brief end-of-day productivity summary for a software developer.

Today's Results:
{json.dumps(stats, indent=2)}

Goals Were:
{json.dumps(goals, indent=2)}

Provide:
1. One thing to celebrate (1 sentence)
2. One insight about today (1 sentence)  
3. One suggestion for tomorrow (1 sentence)

Keep it warm, encouraging, and specific to their actual numbers."""

        try:
            response = self.client.models.generate_content(
                model=self._model_name,
                contents=f"{self.SYSTEM_PROMPT}\n\n---\n\n{prompt}",
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=300,
                )
            )
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiCoach] Summary error: {e}")
            return self._get_fallback_summary(stats, goals)
    
    def _get_fallback_summary(self, stats: Dict[str, float], goals: Dict[str, float]) -> str:
        """Fallback daily summary."""
        work = aggregate_stats(stats, 'work')
        learning = stats.get('learning', 0)
        
        return f"""📊 Daily Summary:
🎯 Work: {work:.0f} min | Learning: {learning:.0f} min
💡 Tomorrow: Start with your hardest task while energy is fresh!"""
    
    def ask_question(self, question: str, stats: Dict[str, float]) -> str:
        """Ask the coach a free-form question about productivity."""
        if not self.enabled:
            return "💡 AI coach is offline. Check your Gemini API key configuration."
        
        prompt = f"""A software developer is asking you a question about productivity.

Their current stats today:
{json.dumps(stats, indent=2)}

Their question: {question}

Provide a helpful, concise answer (2-4 sentences). Be practical and developer-focused."""

        try:
            response = self.client.models.generate_content(
                model=self._model_name,
                contents=f"{self.SYSTEM_PROMPT}\n\n---\n\n{prompt}",
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    max_output_tokens=200,
                )
            )
            return response.text.strip()
        except Exception as e:
            return f"Sorry, I couldn't process that question: {e}"


# CLI for testing
if __name__ == "__main__":
    import sys
    
    coach = GeminiCoach()
    
    # Test stats
    test_stats = {
        'work': 45,
        'learning': 30,
        'wasted': 20,
        'docs': 10,
    }
    
    test_goals = {
        'work': 240,
        'learning': 60,
        'wasted time': 60,
        'documents': 30,
    }
    
    if len(sys.argv) > 1 and sys.argv[1] == "ask":
        question = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "How can I be more productive?"
        print(coach.ask_question(question, test_stats))
    elif len(sys.argv) > 1 and sys.argv[1] == "summary":
        print(coach.get_daily_summary(test_stats, test_goals))
    else:
        print("Testing coaching advice...\n")
        advice = coach.get_coaching(
            stats=test_stats,
            goals=test_goals,
            is_rest_day=False,
            waste_ratio=15.0,
            focus_streak=25,
            best_streak=45,
        )
        print(f"🤖 Dev Coach says:\n{advice}")
