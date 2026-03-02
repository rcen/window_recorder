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
    notes_summary: Optional[Dict] = None  # Today's notes with tags for coaching
    must_done_tasks: Optional[List[Dict]] = None  # Weekly must-done tasks with status


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
- Format EVERY response as 2-3 short bullet points (use • character)
- Each bullet: one clear thought, max 12 words
- Be specific and data-driven based on the current metrics
- Focus on the next actionable step
- Avoid cheerleader phrases like "You got this!", "Amazing!", "Awesome!", "Great job!"
- Use a calm, focused tone like a senior engineer giving advice
- Use emojis very sparingly (max 1 per bullet, only if it adds clarity)

Key principles you follow:
1. Deep work blocks are precious - protect them
2. Regular breaks improve overall output
3. Learning compounds over time
4. Some waste time is healthy and necessary
5. Consistency beats intensity
6. Morning hours are golden for complex work
7. Energy management > time management
8. Idle time is normal - it represents time away from the computer, NOT lost productivity
9. A written daily plan in the morning is THE single highest-leverage habit for productivity.
   Without a plan, the day drifts into reactive mode and procrastination wins.
   Encourage the user to spend 5-10 minutes each morning writing a concrete plan:
   pick 1-3 focus tasks, assign time blocks, and define a "done" criteria for each.

CRITICAL ANTI-PROCRASTINATION RULES:
The user struggles with procrastination that leads to late nights and miserable mornings. Your #1 job is breaking this cycle:

1. **Before midnight deadline**: The day ENDS at midnight. If it's evening (after 8 PM) and goals aren't met, create URGENCY:
   - Calculate exactly how much time remains until midnight
   - Suggest ONE specific task they can complete in the remaining time
   - Remind them: "Finishing now = better sleep = better tomorrow"

2. **Evening procrastination detection**: If after 8 PM with high waste ratio or no productive work:
   - Call it out directly: "You're procrastinating. The cost is tomorrow morning's energy."
   - Suggest the smallest possible start: "Just open the file. 5 minutes."
   
3. **Sleep-productivity connection**: Always link current behavior to next-day outcomes:
   - Late work = late sleep = groggy morning = harder to focus = more procrastination
   - Early completion = on-time sleep = fresh morning = easier focus = momentum

4. **Minimum viable progress**: When time is short, help them achieve SOMETHING:
   - "You have 90 minutes until midnight. One completed task > zero tasks."
   - "Even 20 minutes of real work beats 3 hours of anxious avoidance."

IMPORTANT: Never criticize idle time. Users are not expected to be at their computer continuously.
Focus your coaching on the ACTIVE time distribution, not total time.

Remember: You're a professional coach, not a cheerleader. Be direct, helpful, and respect the developer's intelligence. Your goal is to help them sleep on time with a sense of accomplishment."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Gemini coach."""
        self.api_key = api_key or self._load_api_key()
        self.client = None
        self.enabled = False
        self.cache_file = Path("data/coach_cache.json")
        self._advice_cache_file = Path("data/coach_advice_cache.json")
        self._digest_file = Path("data/coach_briefings.json")
        self._last_advice_time = 0
        self._cached_advice = None
        self._cached_context_hash = None
        self._advice_cooldown = 1800  # 30 minutes between API calls (default)
        self._morning_advice_cooldown = 900  # 15 minutes in the morning (before 11 AM)
        
        # Model fallback chain - try each in order if quota exhausted
        self._model_fallbacks = [
            'gemini-2.5-pro',   # Primary: best quality, free tier available
            'gemini-2.5-flash', # Fallback 1: fast, good quality
            'gemini-2.0-flash', # Fallback 2: stable Gemini flash
            'gemma-3-27b-it',   # Fallback 3: free, largest Gemma
            'gemma-3-12b-it',   # Fallback 4: free, good balance
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
            config.read(config_path, encoding='utf-8')
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
        
        # Build progress vs goal summary with actual/target numbers
        now = datetime.datetime.now()
        current_hour = now.hour
        # Workday is 7 AM – 11 PM (16 h). Pro-rate positive goals so
        # morning progress isn't measured against the full-day target.
        day_start = 7   # 7 AM
        day_end   = 23  # 11 PM
        day_length = day_end - day_start  # 16 h
        elapsed_hours = max(0, min(now.hour + now.minute / 60 - day_start, day_length))
        day_fraction = elapsed_hours / day_length if day_length else 1.0

        progress_lines = []
        for cat, target in context.goals.items():
            actual = context.current_stats.get(cat, 0)
            pct = (actual / target * 100) if target > 0 else 0
            if cat.lower() in ('wasted', 'wasted time'):
                status = "✅ under" if actual <= target else f"⚠️ OVER ({actual:.0f}/{target:.0f} min)"
            elif cat.lower() == 'learning' and current_hour < 14:
                # Learning is an afternoon/evening activity — don't flag as behind in the morning
                if pct >= 100:
                    status = "✅ done"
                else:
                    status = f"scheduled for later ({actual:.0f}/{target:.0f} min) — afternoon/evening task"
            else:
                # Compare against pro-rated expected progress, not full-day target
                expected = target * day_fraction
                if pct >= 100:
                    status = "✅ done"
                elif actual >= expected * 0.7:
                    status = f"on track ({actual:.0f} min, expected ~{expected:.0f} by now, goal {target:.0f})"
                else:
                    status = f"behind pace ({actual:.0f} min, expected ~{expected:.0f} by now, goal {target:.0f})"
            progress_lines.append(f"  - {cat}: {status}")
        progress_str = "\n".join(progress_lines)
        
        # Format notes with tags
        notes_section = self._format_notes_for_prompt(context.notes_summary)
        must_done_section = self._format_must_done_for_prompt(context.must_done_tasks)
        
        prompt = f"""Current Situation:
Time: {datetime.datetime.now().strftime('%H:%M')} ({context.time_of_day})
Day Type: {context.day_type}
{f'Rest Reason: {context.rest_reason}' if context.rest_reason else ''}

Today's Activity:
{stats_str if stats_str else '  (No activity recorded yet)'}

Goals:
{goals_str}

Progress vs Goals:
{progress_str}

Metrics:
- Waste Ratio: {context.waste_ratio:.1f}%
- Current Focus Streak: {context.focus_streak:.0f} min
- Best Streak Today: {context.best_streak:.0f} min
- Hours Remaining in Workday: {context.hours_remaining:.1f}h

{notes_section}

{must_done_section}

{self._get_situation_specific_context(context)}

Based on this context, provide 2-3 bullet points (use • character). Each bullet: one short, actionable thought (max 15 words).
RULES:
- When mentioning progress, ALWAYS include the actual numbers (e.g., "45/240 min" not just "behind").
- If there are incomplete Must Done tasks or user #todo/#focus notes, reference them specifically.
- LEARNING is an afternoon/evening activity. Before 12:30 PM, do NOT flag learning as behind or suggest learning tasks. Focus on work goals in the morning instead.
- For WORK goals, compare against the pro-rated expected progress (shown in the Progress section), NOT the full-day target. Saying "29/240 behind" at 11 AM is misleading — there are many hours left. Use the expected-by-now number instead and keep the tone encouraging if the developer is roughly on pace."""
        
        return prompt
    
    def _format_notes_for_prompt(self, notes_summary: Optional[Dict]) -> str:
        """Format user's notes with tags for the coaching prompt."""
        if not notes_summary:
            return ""
        
        sections = []
        
        # Show completed items (#done)
        done_items = notes_summary.get('done_items', [])
        if done_items:
            done_list = "\n".join([f"  ✓ {n['clean_note']} ({n['time_str']})" for n in done_items[:5]])
            sections.append(f"Completed Today (#done):\n{done_list}")
        
        # Show todo items (#todo)
        todo_items = notes_summary.get('todo_items', [])
        if todo_items:
            todo_list = "\n".join([f"  • {n['clean_note']}" for n in todo_items[:5]])
            sections.append(f"Todo Items (#todo):\n{todo_list}")
        
        # Show blocked items (#blocked, #stuck)
        blocked_items = notes_summary.get('blocked_items', [])
        if blocked_items:
            blocked_list = "\n".join([f"  ⚠ {n['clean_note']}" for n in blocked_items[:3]])
            sections.append(f"Blocked/Stuck (#blocked):\n{blocked_list}")
        
        # Show focus items (#focus, #priority)
        focus_items = notes_summary.get('focus_items', [])
        if focus_items:
            focus_list = "\n".join([f"  🎯 {n['clean_note']}" for n in focus_items[:3]])
            sections.append(f"Priority Focus (#focus):\n{focus_list}")
        
        # Show recent untagged notes
        all_notes = notes_summary.get('all_notes', [])
        untagged = [n for n in all_notes if not n['tags']][:3]
        if untagged:
            untagged_list = "\n".join([f"  - {n['note']} ({n['time_str']})" for n in untagged])
            sections.append(f"Recent Notes:\n{untagged_list}")
        
        if sections:
            return "User's Notes Today:\n" + "\n\n".join(sections)
        return ""
    
    def _format_must_done_for_prompt(self, must_done_tasks: Optional[List[Dict]]) -> str:
        """Format must-done tasks for the coaching prompt."""
        if not must_done_tasks:
            return ""
        
        lines = []
        pending = []
        completed = []
        for task in must_done_tasks:
            desc = task.get('description', task.get('task_id', '?'))
            day = task.get('day', '')
            if task.get('completed'):
                completed.append(f"  ✅ {desc} (due {day})")
            else:
                pending.append(f"  ⬜ {desc} (due {day})")
        
        if pending:
            lines.append("Must Done This Week (INCOMPLETE):")
            lines.extend(pending)
        if completed:
            lines.append("Must Done This Week (done):")
            lines.extend(completed)
        
        if lines:
            return "\n".join(lines)
        return ""
    
    def _get_situation_specific_context(self, context: CoachingContext) -> str:
        """Add situation-specific context based on patterns."""
        situations = []
        
        # Check various situations
        work_mins = aggregate_stats(context.current_stats, 'work')
        wasted_mins = context.current_stats.get('wasted', 0)
        learning_mins = context.current_stats.get('learning', 0)
        
        work_goal = context.goals.get('work', 240)
        
        # Get current hour for time-based urgency
        current_hour = datetime.datetime.now().hour
        minutes_until_midnight = (24 - current_hour) * 60 - datetime.datetime.now().minute
        
        # CRITICAL: Evening/Night procrastination detection (after 8 PM)
        if current_hour >= 20:  # 8 PM or later
            situations.append(f"⚠️ EVENING ALERT: Only {minutes_until_midnight} minutes until midnight!")
            
            productive_mins = work_mins + learning_mins
            if productive_mins < 30:
                situations.append("PROCRASTINATION DETECTED: Almost no productive work today. The cost is tomorrow's energy.")
                situations.append("Suggest: Pick ONE small task. Even 20 minutes beats anxious avoidance.")
            elif work_mins < work_goal * 0.5:
                situations.append(f"Behind on goals with limited time. Focus on ONE completable task before bed.")
            
            if context.waste_ratio > 25:
                situations.append("High waste ratio in evening - classic procrastination pattern. Breaking this = better sleep tonight.")
        
        # Late night warning (after 10 PM)
        if current_hour >= 22:
            situations.append("🌙 LATE NIGHT: Every minute past midnight costs double tomorrow. Wrap up or commit to sleep.")
        
        # Morning with no work yet
        if context.time_of_day == "morning" and work_mins < 30:
            situations.append("Developer hasn't started deep work yet this morning.")
            if work_mins < 5 and wasted_mins < 10:
                situations.append("DAILY PLAN CHECK: If the user hasn't made a plan yet, strongly encourage spending 5 min writing down today's top 1-3 tasks with time blocks. A plan in the morning is the #1 predictor of a productive day.")
        
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
        
        # Late in day, behind on goals (but not yet evening)
        if context.hours_remaining < 3 and work_mins < work_goal * 0.5 and current_hour < 20:
            situations.append("Limited time remaining and behind on work goals.")
        
        # Learning scheduling awareness
        if current_hour < 14:
            # Morning/early afternoon — learning is not expected yet
            if learning_mins > 15:
                situations.append(f"Bonus: already started learning early ({learning_mins:.0f} min)!")
            # Don't flag learning as behind before 2 PM
        elif learning_mins > 30:
            situations.append(f"Great learning investment today: {learning_mins:.0f} min!")
        elif learning_mins < context.goals.get('learning', 30) * 0.5 and current_hour >= 17:
            situations.append(f"Learning goal needs attention: {learning_mins:.0f}/{context.goals.get('learning', 30):.0f} min — evening is a good time.")
        
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
        
        # Fetch today's notes with tags for context
        notes_summary = None
        must_done_tasks = None
        try:
            import database
            notes_summary = database.get_notes_summary_for_coaching()
            must_done_tasks = database.get_must_done_summary_for_coaching()
        except Exception as e:
            print(f"[GeminiCoach] Could not fetch notes/must-done: {e}")
        
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
            notes_summary=notes_summary,
            must_done_tasks=must_done_tasks,
        )
        
        # Check if we can use cached advice
        context_hash = self._get_context_hash(context)
        cached = self._load_cached_advice()
        
        if cached:
            cache_age = time.time() - cached.get('timestamp', 0)
            cached_hash = cached.get('context_hash', '')
            
            # Use shorter cooldown in the morning (before 11 AM) for more frequent coaching
            current_hour = datetime.datetime.now().hour
            cooldown = self._morning_advice_cooldown if current_hour < 11 else self._advice_cooldown
            
            # Use cache if: less than cooldown AND situation hasn't changed drastically
            if cache_age < cooldown:
                # Check if situation changed significantly
                if self._is_similar_context(context_hash, cached_hash):
                    print(f"[GeminiCoach] Using cached advice ({cache_age/60:.0f} min old)")
                    self._last_advice_time = cached.get('timestamp', time.time())
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
                        # Gemini 2.5 uses "thinking" tokens that count against output limit
                        # Need ~1500 for thinking + ~300 for actual response
                        max_output_tokens=2048,
                    )
                )
                
                # Debug: check if response was truncated
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = getattr(candidate, 'finish_reason', None)
                    if finish_reason and str(finish_reason) not in ('STOP', 'FinishReason.STOP', '1'):
                        print(f"[GeminiCoach] WARNING: Response truncated, finish_reason={finish_reason}")
                
                advice = response.text.strip()
                
                # Sanity check: if advice seems truncated (ends mid-sentence), log warning
                if advice and not advice[-1] in '.!?…"\'':
                    print(f"[GeminiCoach] WARNING: Advice may be truncated: '{advice[-50:]}...'")
                
                # Update current model if fallback succeeded
                if model != self._model_name:
                    print(f"[GeminiCoach] Switched to {model} (primary exhausted)")
                    self._model_name = model
                
                # Cache the advice
                self._save_cached_advice(advice, context_hash)
                self._cache_advice(context, advice)
                
                # Store the generation timestamp
                self._last_advice_time = time.time()
                
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
            self._last_advice_time = cached.get('timestamp', time.time())
            return cached['advice']
        return self._get_fallback_advice(stats, goals, is_rest_day)
    
    def get_coaching_with_timestamp(
        self,
        stats: Dict[str, float],
        goals: Dict[str, float],
        is_rest_day: bool = False,
        rest_reason: str = "",
        waste_ratio: float = 0.0,
        focus_streak: float = 0.0,
        best_streak: float = 0.0,
    ) -> tuple:
        """Get AI coaching advice with generation timestamp.
        
        Returns:
            Tuple of (advice_string, timestamp_unix)
        """
        advice = self.get_coaching(
            stats=stats,
            goals=goals,
            is_rest_day=is_rest_day,
            rest_reason=rest_reason,
            waste_ratio=waste_ratio,
            focus_streak=focus_streak,
            best_streak=best_streak,
        )
        return advice, self._last_advice_time
    
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
            return "• 🌴 Rest day — recharge is the priority\n• A little work is fine, enjoy yourself"
        
        if time_of_day == "morning" and work < 30:
            return "• 📋 First: spend 5 min writing today's plan (1-3 tasks + time blocks)\n• 🌅 Then start your hardest task — morning focus is golden"
        
        if work >= work_goal:
            return "• ✅ Work goal hit\n• Consider learning time or a break"
        
        if wasted > 60:
            return "• 🔄 High waste — time for a reset\n• Pick one small task, finish it now"
        
        progress = work / work_goal if work_goal > 0 else 0
        if progress >= 0.7:
            return f"• 💪 Work at {work:.0f}/{work_goal:.0f} min ({progress*100:.0f}%)\n• Home stretch — keep momentum"
        
        return f"• ⚠️ Work behind: {work:.0f}/{work_goal:.0f} min ({progress*100:.0f}%)\n• Pick one task, start now"
    
    def get_new_day_briefing(
        self,
        yesterday_stats: Dict[str, float],
        yesterday_goals: Dict[str, float],
        today_goals: Dict[str, float],
        is_rest_day: bool = False,
        rest_reason: str = "",
    ) -> str:
        """Generate a new day briefing summarizing yesterday and setting intentions for today.
        
        Args:
            yesterday_stats: Yesterday's activity statistics (category -> minutes)
            yesterday_goals: Yesterday's goals (category -> target minutes)
            today_goals: Today's goals (category -> target minutes)
            is_rest_day: Whether today is a weekend/holiday
            rest_reason: Why it's a rest day
            
        Returns:
            Morning briefing string with yesterday's summary and today's focus
        """
        if not self.enabled:
            return self._get_fallback_briefing(yesterday_stats, yesterday_goals, is_rest_day)
        
        # Calculate yesterday's performance
        excluded_cats = {'idle', 'sperrbildschirm'}
        
        # Build yesterday summary
        achievements = []
        missed = []
        
        for cat, target in yesterday_goals.items():
            actual = yesterday_stats.get(cat, 0)
            if cat.lower() in ('wasted', 'wasted time'):
                # For negative goals, under is good
                if actual <= target:
                    achievements.append(f"{cat}: {actual:.0f}/{target:.0f} min ✅")
                else:
                    missed.append(f"{cat}: {actual:.0f}/{target:.0f} min (over by {actual-target:.0f} min)")
            else:
                # For positive goals, meeting target is good
                if actual >= target:
                    achievements.append(f"{cat}: {actual:.0f}/{target:.0f} min ✅")
                else:
                    pct = (actual / target * 100) if target > 0 else 0
                    missed.append(f"{cat}: {actual:.0f}/{target:.0f} min ({pct:.0f}%)")
        
        # Calculate waste ratio
        total_active = sum(v for k, v in yesterday_stats.items() if k.lower() not in excluded_cats)
        wasted = yesterday_stats.get('wasted', 0) + yesterday_stats.get('wasted time', 0)
        waste_ratio = (wasted / total_active * 100) if total_active > 0 else 0
        
        yesterday_summary = []
        if achievements:
            yesterday_summary.append("Goals achieved: " + ", ".join(achievements))
        if missed:
            yesterday_summary.append("Missed: " + ", ".join(missed))
        yesterday_summary.append(f"Waste ratio: {waste_ratio:.0f}%")
        
        # Day type context
        day_type = "holiday" if "Holiday" in rest_reason else ("weekend" if is_rest_day else "workday")
        
        prompt = f"""NEW DAY BRIEFING REQUEST

Yesterday's Performance (for context only — do NOT dwell on it):
{chr(10).join('  - ' + s for s in yesterday_summary)}

Today's Goals:
{chr(10).join(f'  - {cat}: {target:.0f} min' for cat, target in today_goals.items())}

Day Type: {day_type}
{f'Rest Reason: {rest_reason}' if is_rest_day else ''}

Generate a SHORT, actionable morning plan for today. Format as bullet points (use • character).
Rules:
1. Start with ONE brief line about yesterday (max 10 words, e.g., "Yesterday: solid work day" or "Yesterday: too much waste time").
2. Then present a CONCRETE DAILY PLAN with 3-5 time-blocked focus areas for TODAY based on the goals and yesterday's gaps.
3. Each bullet should be a specific, time-boxed action with a clear "done" state (e.g., "• 9:00-10:30 — Deep coding on [priority task]. Done = PR submitted.").
4. Include at least one bullet reminding the user to write down their top 1-3 tasks for the day if they haven't already. Planning is NOT optional — it's the #1 predictor of a productive day.
5. If it's a rest day, keep it to 2-3 gentle bullets but still suggest a light plan.
6. Do NOT give generic motivational advice. Every bullet must be a clear action or time-boxed focus block.
7. No "tomorrow" references — this is about TODAY only.
8. End with a short reminder: "A day without a plan drifts. 5 min of planning saves hours of wasted time."

Remember the user's challenge: procrastination leads to late nights.
If yesterday had high waste ratio, include a bullet about starting with the hardest task first.
The CORE message: making a plan in the morning is the single most effective thing the user can do to have a good day."""
        
        # Try to get AI response
        for model in self._model_fallbacks:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=f"{self.SYSTEM_PROMPT}\n\n---\n\n{prompt}",
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=300,
                    )
                )
                advice = response.text.strip()
                if advice:
                    print(f"[GeminiCoach] New day briefing generated with {model}")
                    return advice
            except Exception as e:
                print(f"[GeminiCoach] {model} failed for briefing: {e}")
                continue
        
        return self._get_fallback_briefing(yesterday_stats, yesterday_goals, is_rest_day)
    
    def _get_fallback_briefing(
        self,
        yesterday_stats: Dict[str, float],
        yesterday_goals: Dict[str, float],
        is_rest_day: bool
    ) -> str:
        """Fallback briefing when Gemini is unavailable."""
        work = aggregate_stats(yesterday_stats, 'work')
        wasted = yesterday_stats.get('wasted', 0) + yesterday_stats.get('wasted time', 0)
        work_goal = yesterday_goals.get('work', 240)
        learning_goal = yesterday_goals.get('learning', 60)
        
        if work >= work_goal:
            yesterday_line = "Yesterday: hit work goal ✅"
        elif work >= work_goal * 0.7:
            yesterday_line = f"Yesterday: decent ({work:.0f}/{work_goal:.0f} min)"
        else:
            yesterday_line = f"Yesterday: missed work goal ({work:.0f}/{work_goal:.0f} min)"
        
        lines = [f"{yesterday_line}\n"]
        
        if is_rest_day:
            lines.append("• Rest day — recharge is the priority")
            lines.append("• Jot down 1-2 light goals so the day has shape")
            lines.append("• Enjoy your time off")
        else:
            lines.append("• First 5 min: write today's plan — pick 1-3 tasks, assign time blocks")
            lines.append(f"• Then 25 min deep coding before checking anything else")
            lines.append(f"• Target {work_goal:.0f} min work, {learning_goal:.0f} min learning")
            if wasted > 90:
                lines.append("• Block distractions early — yesterday's waste was high")
            else:
                lines.append("• Keep waste time under control")
            lines.append("• A day without a plan drifts. Plan now, thank yourself tonight.")
        
        return "\n".join(lines)
    
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

    def _save_digest(
        self,
        *,
        date_str: str,
        kind: str,
        text: str,
        is_rest_day: bool = False,
        rest_reason: str = "",
        source: str = "ai",
    ) -> None:
        """Persist morning briefings or daily summaries for later display."""
        try:
            digest = []
            if self._digest_file.exists():
                with open(self._digest_file, "r", encoding="utf-8") as f:
                    digest = json.load(f)

            # Replace any existing entry for the same date/kind
            digest = [d for d in digest if not (d.get("date") == date_str and d.get("kind") == kind)]

            digest.append({
                "date": date_str,
                "kind": kind,
                "text": text,
                "is_rest_day": is_rest_day,
                "rest_reason": rest_reason,
                "source": source,
                "timestamp": datetime.datetime.now().isoformat(),
            })

            # Keep the most recent 14 entries (roughly two weeks)
            digest = sorted(
                digest,
                key=lambda d: (d.get("date", ""), d.get("timestamp", ""))
            )[-14:]

            self._digest_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._digest_file, "w", encoding="utf-8") as f:
                json.dump(digest, f, indent=2)
        except Exception as e:
            print(f"[GeminiCoach] Digest cache error: {e}")
    
    def get_daily_summary(self, stats: Dict[str, float], goals: Dict[str, float]) -> str:
        """Get an end-of-day summary and reflection."""
        if not self.enabled:
            return self._get_fallback_summary(stats, goals)
        
        prompt = f"""Generate a brief end-of-day productivity summary for a software developer.

UNITS: All durations below are in MINUTES (not hours).

Today's Results (minutes):
{json.dumps(stats, indent=2)}

Today's Goals (minutes):
{json.dumps(goals, indent=2)}

Your response MUST start with a per-category scoreboard using EXACTLY this format
(one bullet per goal, always show actual/target and percentage):

• Work: <actual> / <target> min (<pct>%) [exceeded ✅ | on track | short ⚠️]
• Learning: <actual> / <target> min (<pct>%) [exceeded ✅ | on track | short ⚠️]
• Wasted: <actual> / <target> min (<pct>%) [under ✅ | over ⚠️]

After the scoreboard, add ONE sentence — either something to celebrate
or an honest observation about today's patterns.

Rules:
- Use the EXACT category names from the goals dict (work, learning, wasted time).
- Never invent combined labels like "focused work" — keep categories separate.
- Do NOT mention tomorrow or give suggestions for the next day.
- Keep it factual, warm, and specific to their actual numbers.
- Do not re-interpret units as hours."""

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
        wasted = aggregate_stats(stats, 'wasted time')
        work_goal = goals.get('work', 240)
        learning_goal = goals.get('learning', 30)
        wasted_goal = goals.get('wasted time', 60)

        def _tag(actual, target, positive=True):
            pct = (actual / target * 100) if target else 0
            if positive:
                return f"exceeded ✅" if actual >= target else (f"on track" if pct >= 70 else f"short ⚠️")
            else:
                return f"under ✅" if actual <= target else f"over ⚠️"

        lines = [
            f"• Work: {work:.0f} / {work_goal:.0f} min ({work/work_goal*100:.0f}%) — {_tag(work, work_goal)}",
            f"• Learning: {learning:.0f} / {learning_goal:.0f} min ({learning/learning_goal*100:.0f}%) — {_tag(learning, learning_goal)}",
            f"• Wasted: {wasted:.0f} / {wasted_goal:.0f} min ({wasted/wasted_goal*100:.0f}%) — {_tag(wasted, wasted_goal, positive=False)}",
        ]

        if work >= work_goal:
            note = "Hit the work target — solid day."
        elif work >= work_goal * 0.7:
            note = f"Decent effort at {work/work_goal*100:.0f}% of work goal."
        else:
            note = f"Fell short on work ({work:.0f}/{work_goal:.0f} min)."

        return "\n".join(lines) + f"\n{note}"
    
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
        'work': 55,
        'learning': 30,
        'wasted': 20,
    }
    
    test_goals = {
        'work': 240,
        'learning': 60,
        'wasted time': 60,
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
