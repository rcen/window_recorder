# Window Recorder - AI Coding Agent Instructions

## Project Overview

Personal productivity tracker that monitors active windows, categorizes time, and provides AI coaching. Client-server architecture: local Python scripts capture activity → SQLite database → HTML dashboard with habit tracking.

## Architecture

```
script.py (Window Capture) → database.py → data/activity.sqlite
                                              ↓
                              analytics.py → html/index.html
                                              ↑
habit_server.py (HTTP:8042) ← JavaScript fetch (habit checkboxes)
```

**Key data flow concept**: All times stored as UTC timestamps, converted using `DAY_BOUNDARY_HOUR` (3 AM default) to determine "logical day". Activity at 2 AM belongs to the previous day.

## Critical Files

| File | Purpose |
|------|---------|
| `script.py` | Main window capture loop - runs continuously in background |
| `database.py` | SQLite operations, schema definitions, all DB functions |
| `analytics.py` | Report generation, HTML output, chart creation (~2800 lines) |
| `categories.py` | **Single source of truth** for category definitions |
| `config.py` | Config loader from `config.dat` and `.env` |
| `productivity_agent.py` | Behavioral coaching rules (waste ratio, streaks, morning shield) |
| `habit_server.py` | Local HTTP server on port 8042 for habit checkbox persistence |
| `gemini_coach.py` | AI coaching via Google Gemini API |

## Essential Patterns

### Category System
Always import from `categories.py`, never hardcode:
```python
from categories import PRODUCTIVE_CATS, WASTED_CATS, is_productive, is_wasted
```

Categories have priority for conflict resolution (lower = higher priority):
- `work/coding/job_search`: 1
- `learning/mail/church`: 2  
- `family`: 3
- `not categorized`: 4
- `wasted/gaming`: 5
- `idle`: 10

### Date Boundary Logic
Activities are assigned to "logical days" using `calculate_adjusted_local_date()`:
```python
# Activity at 2:30 AM on Jan 5 → belongs to Jan 4
if local_dt.hour < DAY_BOUNDARY_HOUR:  # DAY_BOUNDARY_HOUR = 3
    adjusted_dt = local_dt - datetime.timedelta(days=1)
```

### Database Access
Use `database.py` functions, not raw SQL:
```python
import database
database.insert_local_activity(timestamp, category, duration, window_title)
database.get_activities_for_date(date_str)  # Returns DataFrame
```

Database file: `data/activity.sqlite` with tables: `activity`, `habit_completions`, `habit_completion_events`, `warning_flags`, `streak_notes`

## Development Commands

```bash
# Run window recorder (foreground)
python script.py

# Run habit server (required for habit checkboxes)
python habit_server.py  # or start_habit_server.bat

# Run tests
run_tests.bat  # or: python -m pytest tests/test_regression.py -v

# Generate analytics report
python analytics.py
```

## Configuration

### Required: `.env` file (not in git)
```
DATABASE_URI=postgresql://...  # Optional remote sync
SERVER_API_KEY=your_key
GEMINI_API_KEY=your_key  # For AI coaching
```

### Required: `config.dat` 
```ini
[SETTINGS]
timezone = America/New_York

[HABITS]
exercise = #4ade80
read = #60a5fa

[FOCUS_SLOTS]
slot1 = 09:00-12:00
```

## Testing Conventions

- Fixture data in `tests/fixtures/activity_7days.json`
- Use `pytest` with `-v` flag
- Test categories are in `test_regression.py`
- Create temporary test DB for database operation tests

## Productivity Agent Rules

Weekend/holiday detection affects thresholds:
- **Weekday**: 15% waste ratio max, 1:5 vibe-to-job ratio, morning shield active
- **Weekend**: 40% waste ratio allowed, no job balance required
- **Saturday**: 25% of normal goals (SATURDAY_GOAL_MULTIPLIER)
- **Sunday**: 50% of normal goals (SUNDAY_GOAL_MULTIPLIER)

### Anti-Procrastination Coaching (Critical Feature)
The AI coach in `gemini_coach.py` emphasizes breaking the procrastination → late sleep → miserable morning cycle:
- **After 8 PM**: Triggers evening urgency alerts with minutes-until-midnight countdown
- **After 10 PM**: Late night warnings emphasizing sleep debt
- **Procrastination detection**: Flags high waste ratio + low productive time in evening
- **Focus on completion**: Encourages ONE completable task over perfectionism
- **Sleep-productivity link**: Always connects current behavior to next-day outcomes

### Morning Briefing (New Day Feature)
At day boundary (default 3 AM), the system generates a morning briefing via `get_new_day_briefing()`:
- **Yesterday summary**: Goals achieved vs missed, waste ratio
- **Pattern recognition**: Identifies if late-night work or high waste occurred
- **Today's focus**: One specific actionable improvement based on yesterday's data
- **Rest day awareness**: Adjusts expectations for weekends/holidays

## Common Gotchas

1. **Teams tracking**: Unreliable window titles due to Edge PWA. See `script.py` header comment.
2. **Idle detection**: Uses `pyautogui` for mouse movement, `msvcrt`/`pynput` for keyboard. Default idle timeout: 180 seconds.
3. **Timezone handling**: Always use `pytz.timezone(TIMEZONE)` from config, never hardcode.
4. **HTML generation**: `analytics.py` writes to `html/index.html` using `html/head.txt` and `html/tail.txt` templates.
5. **Multi-source conflicts**: When multiple devices report overlapping activity, `resolve_conflicts()` in `analytics.py` uses category priority.
