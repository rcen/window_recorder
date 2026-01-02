# -*- coding: utf-8 -*-
"""
Productivity Monitoring Agent (Enhanced)
Implements the Agentic Productivity Dashboard spec with behavioral coaching.

Features:
- Waste Ratio monitoring (< 15% target)
- 1:5 Vibe-to-Job Ratio tracking
- Focus Streak monitoring with record-breaking alerts
- Morning Shield (8-11 AM protection)
- Timesheet Guardrail (Fri/Sat Must Done enforcement)
- Friction Hack (MVD suggestions on wasted spikes)
- Version Control Check (Git commit reminders)
- AI Coaching via Gemini Pro (personalized advice)

@author: Enhanced by GitHub Copilot
"""
import os
import time
import datetime
import threading
import json
import subprocess
import random
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import pytz

import database
from config import TIMEZONE, DAY_BOUNDARY_HOUR
from categories import (
    PRODUCTIVE_CATS, WASTED_CATS, JOB_CATS, VIBE_CATS,
    CATEGORY_ALIASES, is_productive, is_wasted, is_job_related, aggregate_stats
)

# Try to import Gemini coach
try:
    from gemini_coach import GeminiCoach
    GEMINI_COACH_AVAILABLE = True
except ImportError:
    GEMINI_COACH_AVAILABLE = False

# --- Configuration ---
GOALS_CONFIG_FILE = 'data/productivity_goals.json'
AGENT_STATE_FILE = 'data/agent_state.json'

# --- Thresholds (Weekday) ---
WASTE_RATIO_TARGET = 0.15  # 15% max wasted time
VIBE_TO_JOB_RATIO = 5  # 5:1 ratio (50 min vibe = 10 min job)
MORNING_SHIELD_START = 8  # 8 AM
MORNING_SHIELD_END = 11  # 11 AM
MORNING_PRODUCTIVE_MIN = 10  # Must have 10 min productive before wasting
GIT_COMMIT_REMINDER_MIN = 60  # Remind after 60 min without commit

# --- Weekend/Holiday Relaxed Mode ---
WEEKEND_WASTE_RATIO_TARGET = 0.40  # 40% allowed on weekends
WEEKEND_VIBE_TO_JOB_RATIO = 0  # No job balance required on weekends
WEEKEND_MORNING_SHIELD_ENABLED = False  # Sleep in on weekends
WEEKEND_GIT_COMMIT_ENABLED = False  # No coding pressure on weekends

# Holiday dates (add your holidays here in MM-DD format)
HOLIDAYS = {
    "01-01",  # New Year's Day
    "07-04",  # Independence Day
    "12-25",  # Christmas
    "12-26",  # Day after Christmas
    "11-28",  # Thanksgiving (approximate)
    "11-29",  # Day after Thanksgiving
}


class GoalStatus(Enum):
    """Status of goal progress."""
    ON_TRACK = "on_track"
    WARNING = "warning"
    CRITICAL = "critical"
    ACHIEVED = "achieved"
    FAILED = "failed"


class AlertType(Enum):
    """Types of alerts the agent can trigger."""
    WASTE_RATIO = "waste_ratio"
    JOB_BALANCE = "job_balance"
    STREAK_RECORD = "streak_record"
    MORNING_SHIELD = "morning_shield"
    TIMESHEET_GUARDRAIL = "timesheet_guardrail"
    FRICTION_HACK = "friction_hack"
    GIT_COMMIT = "git_commit"
    GOAL_WARNING = "goal_warning"


@dataclass
class ProductivityGoal:
    """Represents a single productivity goal."""
    category: str
    daily_target_minutes: int
    warning_threshold: float = 0.7
    critical_threshold: float = 0.5
    is_positive: bool = True
    enabled: bool = True
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProductivityGoal':
        return cls(**data)


@dataclass
class GoalProgress:
    """Tracks progress toward a goal."""
    goal: ProductivityGoal
    current_minutes: float = 0.0
    expected_minutes: float = 0.0
    status: GoalStatus = GoalStatus.ON_TRACK
    message: str = ""
    last_updated: float = field(default_factory=time.time)
    
    @property
    def progress_percentage(self) -> float:
        if self.goal.daily_target_minutes <= 0:
            return 100.0
        return (self.current_minutes / self.goal.daily_target_minutes) * 100
    
    @property
    def expected_percentage(self) -> float:
        if self.goal.daily_target_minutes <= 0:
            return 100.0
        return (self.expected_minutes / self.goal.daily_target_minutes) * 100


@dataclass
class AgentState:
    """Persistent state for the productivity agent."""
    longest_streak_today: int = 0
    longest_streak_ever: int = 52  # Current record from spec
    morning_productive_minutes: float = 0.0
    morning_wasted_triggered: bool = False
    last_git_check: float = 0.0
    last_git_commit_time: float = 0.0
    coding_since_last_commit: float = 0.0
    waste_spike_count: int = 0
    last_mvd_suggestion: float = 0.0
    job_minutes_today: float = 0.0
    vibe_minutes_today: float = 0.0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AgentState':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ProductivityAgent:
    """
    Enhanced Agent that monitors productivity with behavioral coaching.
    Implements the full Agentic Productivity Dashboard spec.
    """
    
    # MVD (Minimum Viable Day) suggestions for friction hack
    MVD_SUGGESTIONS = [
        "🏋️ Do 10 pushups right now!",
        "🧠 Solve 1 LeetCode easy problem",
        "📖 Read 1 page of documentation",
        "🚶 Take a 2-minute walk",
        "💧 Drink a glass of water and stretch",
        "✍️ Write down 3 things you're grateful for",
        "🎯 Set 1 small goal for the next 25 minutes",
        "📝 Write 1 sentence about what you're working on",
    ]
    
    def __init__(self, callback_warn: Optional[callable] = None):
        """Initialize the productivity agent."""
        self.goals: Dict[str, ProductivityGoal] = {}
        self.progress: Dict[str, GoalProgress] = {}
        self.callback_warn = callback_warn
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._last_warning_times: Dict[str, float] = {}
        self._warning_cooldown = 300  # 5 minutes
        self.state = AgentState()
        
        # Initialize AI coach (optional)
        self.coach = None
        if GEMINI_COACH_AVAILABLE:
            try:
                self.coach = GeminiCoach()
                if self.coach.enabled:
                    print("[ProductivityAgent] AI Coach (Gemini) enabled")
            except Exception as e:
                print(f"[ProductivityAgent] AI Coach init failed: {e}")
        
        self._load_goals()
        self._load_state()
        
    # ==================== STATE MANAGEMENT ====================
    
    def _load_state(self) -> None:
        """Load agent state from file."""
        if os.path.exists(AGENT_STATE_FILE):
            try:
                with open(AGENT_STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.state = AgentState.from_dict(data)
            except (json.JSONDecodeError, IOError):
                self.state = AgentState()
        
        # Reset daily counters if new day
        self._check_day_reset()
    
    def _save_state(self) -> None:
        """Save agent state to file."""
        os.makedirs(os.path.dirname(AGENT_STATE_FILE), exist_ok=True)
        try:
            with open(AGENT_STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except IOError as e:
            print(f"[ProductivityAgent] Error saving state: {e}")
    
    def _check_day_reset(self) -> None:
        """Reset daily counters if it's a new day."""
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        # Reset at day boundary
        if now.hour == DAY_BOUNDARY_HOUR and now.minute < 5:
            self.state.longest_streak_today = 0
            self.state.morning_productive_minutes = 0.0
            self.state.morning_wasted_triggered = False
            self.state.waste_spike_count = 0
            self.state.job_minutes_today = 0.0
            self.state.vibe_minutes_today = 0.0
            self._save_state()
    
    def is_rest_day(self) -> Tuple[bool, str]:
        """
        Check if today is a weekend or holiday (rest day with relaxed rules).
        Returns (is_rest_day, reason).
        """
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        # Check if weekend (Saturday=5, Sunday=6)
        if now.weekday() == 5:
            return True, "Saturday"
        if now.weekday() == 6:
            return True, "Sunday"
        
        # Check if holiday
        date_key = now.strftime("%m-%d")
        if date_key in HOLIDAYS:
            return True, f"Holiday ({date_key})"
        
        return False, "Weekday"
    
    def get_effective_thresholds(self) -> Dict[str, Any]:
        """
        Get the effective thresholds based on whether it's a rest day.
        """
        is_rest, reason = self.is_rest_day()
        
        if is_rest:
            return {
                'waste_ratio_target': WEEKEND_WASTE_RATIO_TARGET,
                'vibe_to_job_ratio': WEEKEND_VIBE_TO_JOB_RATIO,
                'morning_shield_enabled': WEEKEND_MORNING_SHIELD_ENABLED,
                'git_commit_enabled': WEEKEND_GIT_COMMIT_ENABLED,
                'is_rest_day': True,
                'rest_reason': reason
            }
        else:
            return {
                'waste_ratio_target': WASTE_RATIO_TARGET,
                'vibe_to_job_ratio': VIBE_TO_JOB_RATIO,
                'morning_shield_enabled': True,
                'git_commit_enabled': True,
                'is_rest_day': False,
                'rest_reason': reason
            }
    
    # ==================== GOAL MANAGEMENT ====================
    
    def _get_default_goals(self) -> List[ProductivityGoal]:
        """Get default productivity goals aligned with spec."""
        return [
            ProductivityGoal(
                category="work",
                daily_target_minutes=240,  # 4 hours
                warning_threshold=0.7,
                critical_threshold=0.5,
                is_positive=True
            ),
            ProductivityGoal(
                category="learning",
                daily_target_minutes=60,  # 1 hour
                warning_threshold=0.6,
                critical_threshold=0.4,
                is_positive=True
            ),
            ProductivityGoal(
                category="wasted time",
                daily_target_minutes=60,  # Max 1 hour (aligned with 15% of ~6.5h work)
                warning_threshold=0.7,
                critical_threshold=0.9,
                is_positive=False
            ),
            ProductivityGoal(
                category="job_search",
                daily_target_minutes=30,  # 30 min job activities
                warning_threshold=0.5,
                critical_threshold=0.3,
                is_positive=True
            ),
        ]
    
    def _load_goals(self) -> None:
        """Load goals from config file or create defaults."""
        if os.path.exists(GOALS_CONFIG_FILE):
            try:
                with open(GOALS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.goals = {
                        g['category']: ProductivityGoal.from_dict(g) 
                        for g in data.get('goals', [])
                    }
                    print(f"[ProductivityAgent] Loaded {len(self.goals)} goals from config")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[ProductivityAgent] Error loading goals: {e}")
                self._create_default_goals()
        else:
            self._create_default_goals()
    
    def _create_default_goals(self) -> None:
        """Create and save default goals."""
        default_goals = self._get_default_goals()
        self.goals = {g.category: g for g in default_goals}
        self.save_goals()
        print(f"[ProductivityAgent] Created {len(self.goals)} default goals")
    
    def save_goals(self) -> None:
        """Save goals to config file."""
        os.makedirs(os.path.dirname(GOALS_CONFIG_FILE), exist_ok=True)
        data = {
            'goals': [g.to_dict() for g in self.goals.values()],
            'last_updated': time.time()
        }
        try:
            with open(GOALS_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"[ProductivityAgent] Error saving goals: {e}")
    
    def add_goal(self, goal: ProductivityGoal) -> None:
        """Add or update a productivity goal."""
        self.goals[goal.category] = goal
        self.save_goals()
    
    def remove_goal(self, category: str) -> bool:
        """Remove a goal by category."""
        if category in self.goals:
            del self.goals[category]
            self.save_goals()
            return True
        return False
    
    # ==================== DATA RETRIEVAL ====================
    
    def get_current_day_stats(self) -> Dict[str, float]:
        """Get current day's activity statistics by category (in minutes)."""
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        if now.hour < DAY_BOUNDARY_HOUR:
            adjusted_date = (now - datetime.timedelta(days=1)).date()
        else:
            adjusted_date = now.date()
        
        date_str = adjusted_date.strftime('%Y-%m-%d')
        df = database.fetch_log_for_day(date_str)
        
        if df is None or df.empty:
            return {}
        
        stats = {}
        for _, row in df.iterrows():
            category = row.get('category', 'unknown').lower()
            duration_sec = row.get('duration', 0)
            duration_min = duration_sec / 60.0
            stats[category] = stats.get(category, 0) + duration_min
        
        return stats
    
    def get_morning_stats(self) -> Dict[str, float]:
        """Get activity stats for morning shield period (8-11 AM)."""
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        if now.hour < DAY_BOUNDARY_HOUR:
            adjusted_date = (now - datetime.timedelta(days=1)).date()
        else:
            adjusted_date = now.date()
        
        date_str = adjusted_date.strftime('%Y-%m-%d')
        df = database.fetch_log_for_day(date_str)
        
        if df is None or df.empty:
            return {}
        
        stats = {}
        for _, row in df.iterrows():
            timestamp = row.get('timestamp', 0)
            dt = datetime.datetime.fromtimestamp(timestamp, tz)
            
            # Only count activities between 8-11 AM
            if MORNING_SHIELD_START <= dt.hour < MORNING_SHIELD_END:
                category = row.get('category', 'unknown').lower()
                duration_sec = row.get('duration', 0)
                duration_min = duration_sec / 60.0
                stats[category] = stats.get(category, 0) + duration_min
        
        return stats
    
    def get_total_active_minutes(self, stats: Dict[str, float]) -> float:
        """Get total active (non-idle) minutes."""
        return sum(v for k, v in stats.items() if k.lower() != 'idle')
    
    # ==================== BEHAVIORAL CHECKS ====================
    
    def check_waste_ratio(self, stats: Dict[str, float]) -> Optional[Tuple[str, str]]:
        """
        Check Waste Ratio - Target varies by day type.
        Returns (title, message) if alert needed.
        """
        total_active = self.get_total_active_minutes(stats)
        if total_active < 30:  # Not enough data
            return None
        
        thresholds = self.get_effective_thresholds()
        target = thresholds['waste_ratio_target']
        
        wasted_minutes = sum(stats.get(cat, 0) for cat in WASTED_CATS)
        waste_ratio = wasted_minutes / total_active if total_active > 0 else 0
        
        if waste_ratio > target:
            self.state.waste_spike_count += 1
            pct = waste_ratio * 100
            target_pct = target * 100
            day_note = f" (Relaxed: {thresholds['rest_reason']})" if thresholds['is_rest_day'] else ""
            return (
                "🚨 Waste Ratio Alert",
                f"Your waste ratio is {pct:.1f}% (target: <{target_pct:.0f}%){day_note}. "
                f"You've spent {wasted_minutes:.0f} min on distractions. Time for a RESET!"
            )
        return None
    
    def check_vibe_to_job_ratio(self, stats: Dict[str, float]) -> Optional[Tuple[str, str]]:
        """
        Check 1:5 Vibe-to-Job Ratio.
        For every 50 min coding/learning, need 10 min job activities.
        Disabled on weekends/holidays.
        """
        thresholds = self.get_effective_thresholds()
        
        # Skip job balance check on rest days
        if thresholds['vibe_to_job_ratio'] == 0:
            return None
        
        vibe_minutes = sum(stats.get(cat, 0) for cat in VIBE_CATS)
        # Use is_job_related for substring matching (handles "job search ... linkedin" etc)
        job_minutes = sum(dur for cat, dur in stats.items() if is_job_related(cat))
        
        self.state.vibe_minutes_today = vibe_minutes
        self.state.job_minutes_today = job_minutes
        
        ratio = thresholds['vibe_to_job_ratio']
        required_job_minutes = vibe_minutes / ratio
        
        if vibe_minutes >= 50 and job_minutes < required_job_minutes:
            deficit = required_job_minutes - job_minutes
            return (
                "⚖️ Job Balance Needed",
                f"You've done {vibe_minutes:.0f} min of coding/learning. "
                f"Time to spend {deficit:.0f} min on job_search or work tasks!"
            )
        return None
    
    def check_focus_streak(self) -> Optional[Tuple[str, str]]:
        """
        Check Focus Streaks - Notify when 5 min from breaking record.
        """
        try:
            # Import here to avoid circular dependency
            from analytics import Analytics
            analytics = Analytics()
            
            tz = pytz.timezone(TIMEZONE)
            today = datetime.datetime.now(tz).strftime('%Y-%m-%d')
            
            current_streak, _, _ = analytics._calculate_longest_streak_for_day(today)
            
            if current_streak > self.state.longest_streak_today:
                self.state.longest_streak_today = current_streak
                self._save_state()
            
            # Check if approaching record
            record = self.state.longest_streak_ever
            if current_streak >= record - 5 and current_streak < record:
                return (
                    "🔥 Record Breaking Alert!",
                    f"You're {record - current_streak} minutes away from breaking "
                    f"your focus streak record of {record} minutes! Keep going!"
                )
            elif current_streak > record:
                self.state.longest_streak_ever = current_streak
                self._save_state()
                return (
                    "🏆 NEW RECORD!",
                    f"Amazing! You just broke your focus streak record! "
                    f"New record: {current_streak} minutes!"
                )
        except Exception as e:
            print(f"[ProductivityAgent] Error checking streak: {e}")
        
        return None
    
    def check_morning_shield(self) -> Optional[Tuple[str, str]]:
        """
        Morning Shield: Flag wasted time before 10 min of productive work (8-11 AM).
        Disabled on weekends/holidays - you deserve to sleep in!
        """
        thresholds = self.get_effective_thresholds()
        
        # Skip morning shield on rest days
        if not thresholds['morning_shield_enabled']:
            return None
        
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        # Only active between 8-11 AM
        if not (MORNING_SHIELD_START <= now.hour < MORNING_SHIELD_END):
            return None
        
        morning_stats = self.get_morning_stats()
        
        # Calculate productive morning minutes
        productive_minutes = sum(
            morning_stats.get(cat, 0) 
            for cat in PRODUCTIVE_CATS
        )
        wasted_minutes = sum(
            morning_stats.get(cat, 0) 
            for cat in WASTED_CATS
        )
        
        self.state.morning_productive_minutes = productive_minutes
        
        # Check if wasting before productive threshold
        if productive_minutes < MORNING_PRODUCTIVE_MIN and wasted_minutes > 0:
            if not self.state.morning_wasted_triggered:
                self.state.morning_wasted_triggered = True
                self._save_state()
                return (
                    "🛡️ Morning Shield Activated",
                    f"It's only {now.strftime('%H:%M')} and you haven't hit {MORNING_PRODUCTIVE_MIN} min "
                    f"of productive work yet ({productive_minutes:.0f} min so far). "
                    f"Start with coding or docs before distractions!"
                )
        
        return None
    
    def check_timesheet_guardrail(self) -> Optional[Tuple[str, str]]:
        """
        Timesheet Guardrail: On Fri/Sat, prioritize Must Done before Gaming/Learning.
        """
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        # 4 = Friday, 5 = Saturday
        if now.weekday() not in (4, 5):
            return None
        
        # Check if Must Done items are completed
        try:
            week_id = self._get_week_id()
            must_done_status = database.get_must_done_status_for_week(week_id)
            
            incomplete_tasks = [
                task for task, completed in must_done_status.items() 
                if not completed
            ]
            
            if incomplete_tasks:
                stats = self.get_current_day_stats()
                gaming_time = stats.get('gaming', 0)
                learning_time = stats.get('learning', 0)
                
                if gaming_time > 10 or learning_time > 30:
                    day_name = "Friday" if now.weekday() == 4 else "Saturday"
                    return (
                        "📋 Timesheet Guardrail",
                        f"It's {day_name}! Complete your Must Done tasks first:\n"
                        f"• {', '.join(incomplete_tasks[:3])}\n"
                        f"Then you can enjoy gaming/learning guilt-free!"
                    )
        except Exception as e:
            print(f"[ProductivityAgent] Error checking timesheet: {e}")
        
        return None
    
    def check_friction_hack(self) -> Optional[Tuple[str, str]]:
        """
        Friction Hack: Suggest MVD task on wasted spikes.
        """
        if self.state.waste_spike_count >= 2:
            # Cooldown: only suggest every 30 minutes
            if time.time() - self.state.last_mvd_suggestion < 1800:
                return None
            
            self.state.last_mvd_suggestion = time.time()
            self.state.waste_spike_count = 0
            self._save_state()
            
            suggestion = random.choice(self.MVD_SUGGESTIONS)
            return (
                "💪 Friction Hack - MVD Time!",
                f"Detected a wasted time spike. Try this Minimum Viable Day task:\n\n"
                f"{suggestion}\n\n"
                f"Small wins build momentum!"
            )
        return None
    
    def check_git_commit(self, current_activity: str = "") -> Optional[Tuple[str, str]]:
        """
        Version Control Check: Remind after 60+ min coding without git commit.
        Disabled on weekends/holidays - no pressure to code!
        """
        thresholds = self.get_effective_thresholds()
        
        # Skip git check on rest days
        if not thresholds['git_commit_enabled']:
            return None
        
        if current_activity.lower() not in ('work', 'coding', 'programming'):
            self.state.coding_since_last_commit = 0
            return None
        
        # Check for recent git commits
        try:
            result = subprocess.run(
                ['git', 'log', '--oneline', '-1', '--format=%ct'],
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                timeout=5
            )
            if result.returncode == 0:
                last_commit_time = float(result.stdout.strip())
                if last_commit_time > self.state.last_git_commit_time:
                    self.state.last_git_commit_time = last_commit_time
                    self.state.coding_since_last_commit = 0
                    self._save_state()
                    return None
        except Exception:
            pass  # Git not available or error
        
        # Track coding time since last commit
        stats = self.get_current_day_stats()
        coding_minutes = sum(stats.get(cat, 0) for cat in ('coding', 'programming'))
        
        if coding_minutes > self.state.coding_since_last_commit:
            self.state.coding_since_last_commit = coding_minutes
        
        if self.state.coding_since_last_commit >= GIT_COMMIT_REMINDER_MIN:
            self.state.coding_since_last_commit = 0  # Reset after warning
            self._save_state()
            return (
                "📦 Git Commit Reminder",
                f"You've been coding for {coding_minutes:.0f} minutes without a commit. "
                f"Remember: documentation generation requires version control! "
                f"Consider committing your progress."
            )
        
        return None
    
    def _get_week_id(self) -> str:
        """Get the current week ID for Must Done tracking."""
        tz = pytz.timezone(TIMEZONE)
        today = datetime.datetime.now(tz).date()
        week_start = today - datetime.timedelta(days=today.weekday())
        return week_start.strftime('%Y-%m-%d')
    
    # ==================== GOAL EVALUATION ====================
    
    def get_expected_progress(self, goal: ProductivityGoal) -> float:
        """Calculate expected progress based on time of day."""
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        
        work_start_hour = max(DAY_BOUNDARY_HOUR, 8)
        work_end_hour = 23
        
        current_hour = now.hour + now.minute / 60.0
        
        if now.hour < DAY_BOUNDARY_HOUR:
            current_hour += 24
            
        if current_hour < work_start_hour:
            work_hours_elapsed = 0
        elif current_hour > work_end_hour:
            work_hours_elapsed = work_end_hour - work_start_hour
        else:
            work_hours_elapsed = current_hour - work_start_hour
        
        total_work_hours = work_end_hour - work_start_hour
        day_progress = work_hours_elapsed / total_work_hours if total_work_hours > 0 else 1.0
        
        return goal.daily_target_minutes * day_progress
    
    def evaluate_goal(self, goal: ProductivityGoal, current_minutes: float) -> GoalProgress:
        """Evaluate progress toward a single goal."""
        expected_minutes = self.get_expected_progress(goal)
        
        # Adjust targets on rest days (weekends/holidays)
        is_rest_day, rest_reason = self.is_rest_day()
        
        # On rest days: halve positive goals, double negative goals (more lenient)
        if is_rest_day:
            if goal.is_positive:
                effective_target = goal.daily_target_minutes * 0.5  # Half the requirement
                expected_minutes = expected_minutes * 0.5
            else:
                effective_target = goal.daily_target_minutes * 2.0  # Double the limit (more lenient)
        else:
            effective_target = goal.daily_target_minutes
        
        progress = GoalProgress(
            goal=goal,
            current_minutes=current_minutes,
            expected_minutes=expected_minutes,
            last_updated=time.time()
        )
        
        if goal.is_positive:
            if current_minutes >= effective_target:
                progress.status = GoalStatus.ACHIEVED
                progress.message = f"🎉 Goal achieved! {current_minutes:.0f}/{effective_target:.0f} min"
            elif expected_minutes > 0:
                ratio = current_minutes / expected_minutes
                if ratio >= goal.warning_threshold:
                    progress.status = GoalStatus.ON_TRACK
                    progress.message = f"✅ On track: {current_minutes:.0f}/{effective_target:.0f} min"
                elif ratio >= goal.critical_threshold:
                    progress.status = GoalStatus.WARNING
                    behind = expected_minutes - current_minutes
                    progress.message = f"⚠️ Behind: {current_minutes:.0f}/{effective_target:.0f} min ({behind:.0f} min behind)"
                else:
                    progress.status = GoalStatus.CRITICAL
                    behind = expected_minutes - current_minutes
                    progress.message = f"🚨 Critical! {current_minutes:.0f}/{effective_target:.0f} min ({behind:.0f} min behind)"
            else:
                progress.status = GoalStatus.ON_TRACK
                progress.message = f"Day started: {current_minutes:.0f}/{effective_target:.0f} min"
        else:
            if current_minutes >= effective_target:
                progress.status = GoalStatus.FAILED
                progress.message = f"🚨 Limit exceeded! {current_minutes:.0f}/{effective_target:.0f} min"
            elif current_minutes / effective_target >= goal.critical_threshold:
                progress.status = GoalStatus.CRITICAL
                remaining = effective_target - current_minutes
                progress.message = f"🚨 Near limit! {remaining:.0f} min remaining"
            elif current_minutes / effective_target >= goal.warning_threshold:
                progress.status = GoalStatus.WARNING
                remaining = effective_target - current_minutes
                progress.message = f"⚠️ Approaching limit: {remaining:.0f} min remaining"
            else:
                progress.status = GoalStatus.ON_TRACK
                remaining = effective_target - current_minutes
                progress.message = f"✅ Under limit: {current_minutes:.0f}/{effective_target:.0f} min"
        
        return progress
    
    def evaluate_all_goals(self) -> Dict[str, GoalProgress]:
        """Evaluate progress toward all goals."""
        stats = self.get_current_day_stats()
        
        for category, goal in self.goals.items():
            if not goal.enabled:
                continue
            
            # Sum up all aliased categories using centralized function
            current_minutes = aggregate_stats(stats, category)
            
            self.progress[category] = self.evaluate_goal(goal, current_minutes)
        
        return self.progress
    
    # ==================== MAIN CHECK LOOP ====================
    
    def check_all_rules(self, current_activity: str = "") -> List[Tuple[str, str, str]]:
        """
        Check all behavioral rules and return alerts.
        Returns list of (title, message, alert_type).
        """
        alerts = []
        stats = self.get_current_day_stats()
        
        # 1. Waste Ratio
        result = self.check_waste_ratio(stats)
        if result:
            alerts.append((*result, AlertType.WASTE_RATIO.value))
        
        # 2. Vibe-to-Job Ratio
        result = self.check_vibe_to_job_ratio(stats)
        if result:
            alerts.append((*result, AlertType.JOB_BALANCE.value))
        
        # 3. Focus Streak
        result = self.check_focus_streak()
        if result:
            alerts.append((*result, AlertType.STREAK_RECORD.value))
        
        # 4. Morning Shield
        result = self.check_morning_shield()
        if result:
            alerts.append((*result, AlertType.MORNING_SHIELD.value))
        
        # 5. Timesheet Guardrail
        result = self.check_timesheet_guardrail()
        if result:
            alerts.append((*result, AlertType.TIMESHEET_GUARDRAIL.value))
        
        # 6. Friction Hack
        result = self.check_friction_hack()
        if result:
            alerts.append((*result, AlertType.FRICTION_HACK.value))
        
        # 7. Git Commit Check
        result = self.check_git_commit(current_activity)
        if result:
            alerts.append((*result, AlertType.GIT_COMMIT.value))
        
        return alerts
    
    def check_and_warn(self, current_activity: str = "") -> List[GoalProgress]:
        """Check all goals and rules, trigger warnings as needed."""
        self.evaluate_all_goals()
        warnings_triggered = []
        
        # Check behavioral rules
        alerts = self.check_all_rules(current_activity)
        for title, message, alert_type in alerts:
            if self._should_warn(alert_type):
                self._last_warning_times[alert_type] = time.time()
                if self.callback_warn:
                    self.callback_warn(title, message, "warning")
        
        # Check goal progress
        for category, progress in self.progress.items():
            if progress.status in (GoalStatus.WARNING, GoalStatus.CRITICAL, GoalStatus.FAILED):
                if self._should_warn(f"goal_{category}"):
                    self._last_warning_times[f"goal_{category}"] = time.time()
                    warnings_triggered.append(progress)
                    
                    if self.callback_warn:
                        level = "critical" if progress.status in (GoalStatus.CRITICAL, GoalStatus.FAILED) else "warning"
                        title = f"Productivity Alert: {category.title()}"
                        self.callback_warn(title, progress.message, level)
        
        return warnings_triggered
    
    def _should_warn(self, key: str) -> bool:
        """Check if enough time has passed since last warning for this key."""
        last_warn = self._last_warning_times.get(key, 0)
        return time.time() - last_warn >= self._warning_cooldown
    
    # ==================== OUTPUT METHODS ====================
    
    def get_summary(self) -> str:
        """Get a comprehensive text summary."""
        self.evaluate_all_goals()
        stats = self.get_current_day_stats()
        thresholds = self.get_effective_thresholds()
        
        # Header with rest day indicator
        is_rest = thresholds['is_rest_day']
        rest_badge = f" 🌴 {thresholds['rest_reason']} - Relaxed Mode" if is_rest else ""
        
        lines = [
            f"📊 Productivity Dashboard{rest_badge}",
            "=" * 50,
            "",
            "🎯 DAILY GOALS"
        ]
        
        for category, progress in sorted(self.progress.items()):
            pct = progress.progress_percentage
            bar_len = 20
            filled = int(bar_len * min(pct / 100, 1.0))
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"  {category.title()}: [{bar}] {pct:.1f}%")
            lines.append(f"    {progress.message}")
        
        # Behavioral metrics
        lines.extend([
            "",
            "📈 BEHAVIORAL METRICS",
            "-" * 30
        ])
        
        # Rest day notice
        if is_rest:
            lines.append(f"  🌴 REST DAY: {thresholds['rest_reason']} - Relaxed thresholds active!")
        
        # Waste Ratio
        total_active = self.get_total_active_minutes(stats)
        wasted = sum(stats.get(cat, 0) for cat in WASTED_CATS)
        waste_ratio = (wasted / total_active * 100) if total_active > 0 else 0
        target = thresholds['waste_ratio_target'] * 100
        status = "✅" if waste_ratio < target else "⚠️"
        lines.append(f"  {status} Waste Ratio: {waste_ratio:.1f}% (target: <{target:.0f}%)")
        
        # Job Balance (skip display on rest days)
        if not is_rest:
            vibe = sum(stats.get(cat, 0) for cat in VIBE_CATS)
            job = sum(dur for cat, dur in stats.items() if is_job_related(cat))
            required = vibe / VIBE_TO_JOB_RATIO
            status = "✅" if job >= required else "⚠️"
            lines.append(f"  {status} Job Balance: {job:.0f}/{required:.0f} min needed")
        else:
            lines.append("  😴 Job Balance: Not required on rest days")
        
        # Streak
        lines.append(f"  🔥 Today's Best Streak: {self.state.longest_streak_today} min")
        lines.append(f"  🏆 All-Time Record: {self.state.longest_streak_ever} min")
        
        # Morning Shield
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        if not is_rest and MORNING_SHIELD_START <= now.hour < MORNING_SHIELD_END:
            status = "✅" if self.state.morning_productive_minutes >= 10 else "🛡️"
            lines.append(f"  {status} Morning Shield: {self.state.morning_productive_minutes:.0f}/10 min productive")
        elif is_rest:
            lines.append("  😴 Morning Shield: Disabled - sleep in!")
        
        # AI Coach advice
        if self.coach and self.coach.enabled:
            lines.extend([
                "",
                "🤖 AI COACH",
                "-" * 30
            ])
            goals_dict = {cat: g.daily_target_minutes for cat, g in self.goals.items()}
            advice = self.coach.get_coaching(
                stats=stats,
                goals=goals_dict,
                is_rest_day=is_rest,
                rest_reason=thresholds['rest_reason'],
                waste_ratio=waste_ratio,
                focus_streak=self.state.longest_streak_today,
                best_streak=self.state.longest_streak_today,
            )
            # Wrap advice text
            lines.append(f"  {advice}")
        
        return "\n".join(lines)
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data formatted for dashboard display."""
        self.evaluate_all_goals()
        stats = self.get_current_day_stats()
        thresholds = self.get_effective_thresholds()
        
        total_active = self.get_total_active_minutes(stats)
        wasted = sum(stats.get(cat, 0) for cat in WASTED_CATS)
        vibe = sum(stats.get(cat, 0) for cat in VIBE_CATS)
        job = sum(dur for cat, dur in stats.items() if is_job_related(cat))
        
        # Calculate job required with rest day awareness
        job_ratio = thresholds['vibe_to_job_ratio']
        job_required = vibe / job_ratio if job_ratio > 0 else 0
        
        waste_ratio = (wasted / total_active * 100) if total_active > 0 else 0
        
        data = {
            'timestamp': time.time(),
            'goals': [],
            'metrics': {
                'waste_ratio': waste_ratio,
                'waste_ratio_target': thresholds['waste_ratio_target'] * 100,
                'vibe_minutes': vibe,
                'job_minutes': job,
                'job_required': job_required,
                'streak_today': self.state.longest_streak_today,
                'streak_record': self.state.longest_streak_ever,
                'morning_productive': self.state.morning_productive_minutes,
                'is_rest_day': thresholds['is_rest_day'],
                'rest_reason': thresholds['rest_reason'],
                'morning_shield_enabled': thresholds['morning_shield_enabled'],
                'git_commit_enabled': thresholds['git_commit_enabled'],
            }
        }
        
        # Add AI coach advice
        if self.coach and self.coach.enabled:
            goals_dict = {cat: g.daily_target_minutes for cat, g in self.goals.items()}
            advice = self.coach.get_coaching(
                stats=stats,
                goals=goals_dict,
                is_rest_day=thresholds['is_rest_day'],
                rest_reason=thresholds['rest_reason'],
                waste_ratio=waste_ratio,
                focus_streak=self.state.longest_streak_today,
                best_streak=self.state.longest_streak_today,
            )
            data['ai_coach_advice'] = advice
        
        for category, progress in self.progress.items():
            goal_data = {
                'category': category,
                'current_minutes': round(progress.current_minutes, 1),
                'target_minutes': progress.goal.daily_target_minutes,
                'expected_minutes': round(progress.expected_minutes, 1),
                'progress_percentage': round(progress.progress_percentage, 1),
                'status': progress.status.value,
                'message': progress.message,
                'is_positive': progress.goal.is_positive
            }
            data['goals'].append(goal_data)
        
        return data
    
    # ==================== MONITORING ====================
    
    def start_monitoring(self, interval_seconds: int = 60) -> None:
        """Start background monitoring thread."""
        if self._running:
            return
        
        self._running = True
        
        def monitor_loop():
            while self._running:
                try:
                    self.check_and_warn()
                except Exception as e:
                    print(f"[ProductivityAgent] Error in monitor loop: {e}")
                time.sleep(interval_seconds)
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        print(f"[ProductivityAgent] Started monitoring (interval: {interval_seconds}s)")
    
    def stop_monitoring(self) -> None:
        """Stop background monitoring thread."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None
        print("[ProductivityAgent] Stopped monitoring")


# --- CLI ---

def create_cli():
    """Create CLI for managing the productivity agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Productivity Agent CLI")
    parser.add_argument('command', choices=['status', 'list', 'add', 'remove', 'set-target', 'check'],
                       help="Command to run")
    parser.add_argument('--category', '-c', help="Category name")
    parser.add_argument('--target', '-t', type=int, help="Target minutes per day")
    parser.add_argument('--positive', action='store_true', default=True, help="Maximize goal")
    parser.add_argument('--negative', action='store_true', help="Minimize goal")
    
    args = parser.parse_args()
    agent = ProductivityAgent()
    
    if args.command == 'status':
        print(agent.get_summary())
        
    elif args.command == 'check':
        print("Running all behavioral checks...\n")
        alerts = agent.check_all_rules()
        if alerts:
            for title, message, alert_type in alerts:
                print(f"[{alert_type}] {title}")
                print(f"  {message}\n")
        else:
            print("✅ All behavioral rules passing!")
        
    elif args.command == 'list':
        print("\n📋 Configured Goals:")
        print("-" * 50)
        for cat, goal in agent.goals.items():
            type_str = "maximize" if goal.is_positive else "minimize"
            status = "enabled" if goal.enabled else "disabled"
            print(f"  • {cat}: {goal.daily_target_minutes} min/day ({type_str}) [{status}]")
            
    elif args.command == 'add' and args.category and args.target:
        is_positive = not args.negative
        goal = ProductivityGoal(
            category=args.category.lower(),
            daily_target_minutes=args.target,
            is_positive=is_positive
        )
        agent.add_goal(goal)
        print(f"✅ Added goal: {args.category} - {args.target} min/day")
        
    elif args.command == 'remove' and args.category:
        if agent.remove_goal(args.category.lower()):
            print(f"✅ Removed goal: {args.category}")
        else:
            print(f"❌ Goal not found: {args.category}")
            
    elif args.command == 'set-target' and args.category and args.target:
        if args.category.lower() in agent.goals:
            agent.goals[args.category.lower()].daily_target_minutes = args.target
            agent.save_goals()
            print(f"✅ Updated target for {args.category}: {args.target} min/day")
        else:
            print(f"❌ Goal not found: {args.category}")
    else:
        parser.print_help()


if __name__ == '__main__':
    create_cli()
