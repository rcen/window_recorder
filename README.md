# Window Recorder — Local-First Activity Tracker, Focus Guardrails & AI Productivity Dashboard

Window Recorder is a local-first Python productivity suite that automatically tracks active window titles and browser URLs, categorizes how your time is spent, enforces real-time focus guardrails, and renders an interactive web dashboard with habit streaks, daily checklists, smart bookmarks, and optional Google Gemini AI coaching.

All tracking data stays on your machine by default in a local SQLite database (`data/activity.sqlite`), with optional incremental background sync to PostgreSQL (such as Neon serverless Postgres) for multi-device analytics and cloud backup.

---

## Key Features

- **Automatic Window & Browser URL Capture (`script.py`)**
  - Continuously monitors the active window in the background and extracts active URLs/domains from Chromium-based browsers (Chrome, Edge, Brave) via Windows UI Automation.
  - Smart mouse/keyboard idle detection (default 180s timeout), Windows sleep/wake/shutdown power-event handling, and logical day-boundary rollover (`3:00 AM` default, so late-night sessions count toward the previous day).
- **Real-Time Focus Guardrails**
  - Detects distraction spikes, waste-ratio threshold breaches, and scheduled `[FOCUS_SLOTS]` violations.
  - Displays Windows alerts / toast notifications with a one-click **"Close Wasted Page"** action to immediately close distracting browser tabs.
- **Interactive Local Web Dashboard (`analytics.py` + `habit_server.py`)**
  - Auto-refreshes every 60 seconds at `http://127.0.0.1:8042/` with interactive Plotly charts, multi-day activity summary tables (with weekend highlighting), focus-streak timelines, and behavioral KPIs (`productivity_agent.py`).
  - **2-Week Habit Calendar**: Color-coded habit checkboxes with streak counters persisted to SQLite.
  - **Must-Done Tasks & Daily Todo Bucket**: Track non-negotiable daily priorities alongside a persistent backlog.
  - **Focus Streak Notes**: Log quick notes during deep-work sessions using hashtags (`#done`, `#todo`, `#blocked`, `#focus`).
  - **Visual Category Rule Manager (`/categorize`)**: Inspect top uncategorized window titles/URLs, assign substring or regex rules directly to `config.dat`, and trigger retroactive database recategorization from the browser.
  - **Smart Bookmarks & Bookmarklet (`/bookmarks`, `/bookmarklet`)**: Save links with one click from any browser and view engagement statistics and tags.
- **Optional AI Productivity Coach (`gemini_coach.py`)**
  - Powered by Google Gemini (`GEMINI_API_KEY`) to deliver context-aware anti-procrastination nudges, evening wind-down reminders, and morning briefings tailored to your goals, streaks, and `#tag` notes.
- **Optional Stock Watch Widget (`stock_prices.py`)**
  - Compact dashboard ticker strip powered by Yahoo Finance (`yfinance`).
- **Optional Cloud Backup & Multi-Device Sync (`backup_to_remote.py`)**
  - Non-blocking incremental sync from local SQLite to remote PostgreSQL (`DATABASE_URI`), with priority-based multi-device conflict resolution.

---

## Architecture & Data Flow

```text
script.py (Window + Browser URL Capture, Idle/Sleep Monitor, Focus Alerts)
    │
    ▼
database.py ──► data/activity.sqlite (Local SQLite: activities, habits, todos, notes, bookmarks)
    │                   │
    │                   ├──► backup_to_remote.py (Optional background/CLI sync ──► Neon PostgreSQL)
    ▼                   ▼
analytics.py (Plotly Charts, KPI Engine, Gemini Coach, Stock Widget)
    │
    ▼
html/index.html ◄──► habit_server.py (http://127.0.0.1:8042 REST API & UI Routes)
```

### Core Modules

| File | Role |
| :--- | :--- |
| `script.py` | Background capture loop for active window titles, browser URLs, idle/power states, and focus alerts |
| `database.py` | Local SQLite schema, queries, logical day-boundary math (`DAY_BOUNDARY_HOUR = 3`), and sync triggers |
| `analytics.py` | Aggregates logs, resolves multi-device overlaps, and generates `html/index.html` + Plotly charts |
| `habit_server.py` | Local HTTP server (`127.0.0.1:8042`) serving the dashboard, `/categorize`, `/bookmarks`, and persistence APIs |
| `categories.py` | Single source of truth for productive/wasted/neutral category groups, aliases, and conflict priority |
| `config.py` | Configuration loader for `config.dat` (auto-bootstrapped from `config.dat.example`) and `.env` |
| `productivity_agent.py` | Rule-based coaching KPIs (Waste Ratio, 1:5 Vibe-to-Job balance, Focus Streaks, Morning Shield, Weekend rules) |
| `gemini_coach.py` | Optional Google Gemini AI coaching & morning briefing generator |
| `backup_to_remote.py` | Direct SQLAlchemy incremental sync from local SQLite to remote PostgreSQL |
| `broser_start.py` | Optional quick-launch desktop/tray helper to open the local dashboard |
| `recategorize.py` | CLI tool to retroactively re-apply updated `config.dat` category rules to recent activity logs |
| `timesheet.py` | CLI tool to start, stop, adjust, and summarize named project work sessions |

---

## Quick Start

### Prerequisites
- **Python 3.10+**
- **Windows 10 / 11** recommended (full Win32 window capture, Chromium URL extraction, and toast notifications). Basic X11 window capture on Linux is also supported via `python-xlib` and `pynput`.

### Option 1: One-Command Launch (Windows)

On your first run after cloning, pass `--new` to create the virtual environment (`winrecord_env`), install core dependencies, and automatically copy `config.dat.example` to `config.dat`:

```bat
run.bat --new
```

On subsequent runs, start the recorder and local dashboard server with:

```bat
run.bat
```

*(Tip: Use `run.bat --debug` to keep console output visible while troubleshooting.)*

Then open **`http://127.0.0.1:8042/`** in your browser.

### Option 2: Manual Setup (Windows & Linux)

1. **Create and activate the `winrecord_env` virtual environment:**

   ```powershell
   # Windows (PowerShell)
   python -m venv winrecord_env
   .\winrecord_env\Scripts\pip.exe install -r requirements.txt
   ```

   ```bash
   # Linux / macOS
   python3 -m venv winrecord_env
   ./winrecord_env/bin/pip install -r requirements.txt
   ```

2. **(Optional) Install extra packages for optional integrations:**

   ```powershell
   # Google Gemini AI Coach (gemini_coach.py)
   .\winrecord_env\Scripts\pip.exe install google-genai

   # Stock Watch dashboard widget (stock_prices.py)
   .\winrecord_env\Scripts\pip.exe install yfinance

   # Remote PostgreSQL / Neon cloud backup (backup_to_remote.py)
   .\winrecord_env\Scripts\pip.exe install psycopg2-binary

   # Quick-launcher icon support (broser_start.py)
   .\winrecord_env\Scripts\pip.exe install Pillow
   ```

3. **Bootstrap your personal config (automatic on first run):**
   - If `config.dat` does not exist, `config.py`, `analytics.py`, `run.bat`, and `run.sh` automatically copy `config.dat.example` → `config.dat`.
   - `config.dat`, `.env`, `data/`, and generated `html/index.html` are gitignored so your personal categories, habits, API keys, and activity history are never committed to Git.

4. **Run the services:**

   ```powershell
   # 1. Start the local dashboard & persistence server (port 8042)
   .\winrecord_env\Scripts\python.exe habit_server.py
   # (or run start_habit_server.bat / ./start_habit_server.sh)

   # 2. Start the background window & URL recorder
   .\winrecord_env\Scripts\python.exe script.py

   # 3. Generate/refresh the HTML report manually at any time
   .\winrecord_env\Scripts\python.exe analytics.py
   ```

---

## Configuration Guide

### 1. Personal Rules & Preferences (`config.dat`)

Edit `config.dat` (or use `http://127.0.0.1:8042/categorize`) to tailor tracking to your workflow:

```ini
[SETTINGS]
timezone = America/New_York
idle_Selection = True
enable_ai_coach = False
ai_coach_interval = 30

[CATEGORIES]
# Rules are evaluated top-to-bottom against both window title and browser URL.
# Put specific keywords above broad app names (like chrome or edge).
visual studio code = work
github.com = work
stackoverflow.com = learning
docs.python.org = learning
linkedin.com/jobs = job_search
youtube.com = wasted
reddit.com = wasted

# Prefix a key with regex__ to match using regular expressions:
regex__^pull request.*github = work

[COLORS]
work = #4caf50
learning = #2196f3
job_search = #00bcd4
wasted = #f44336
idle = #9e9e9e
# Hide specific categories from summary charts:
no_show_summary = idle

[FOCUS_SLOTS]
morning_deep_work = 09:00-11:30
afternoon_sprint = 14:00-16:00
days = mon,tue,wed,thu,fri

[HABITS]
30m deep work = #4d96ff
exercise = #4caf50
daily plan = #f6c344

[MUST_DONE]
review pull requests
daily standup notes

[VIBE_REPOS]
# Optional local Git repo paths checked for commit reminders during long coding streaks
# window_recorder = C:\projects\window_recorder

[STOCKS]
enabled = False
symbols = SPY, QQQ, AAPL, MSFT
refresh_minutes = 15
```

High-level category groupings (`PRODUCTIVE_CATS`, `WASTED_CATS`, `NEUTRAL_CATS`) and multi-device conflict resolution priorities live in `categories.py`.

### 2. Secrets & Cloud Connections (`.env` — Optional)

Create a `.env` file in the repository root only if you want AI coaching or remote PostgreSQL sync:

```ini
# Optional: Google Gemini API key for AI productivity coaching & morning briefings
GEMINI_API_KEY="your_gemini_api_key"

# Optional: PostgreSQL connection URI (e.g., Neon) for background cloud backup
DATABASE_URI="postgresql://user:password@ep-example.us-east-2.aws.neon.tech/neondb?sslmode=require"

# Optional: Only used by the legacy FastAPI ingestion server (api_server.py)
SERVER_API_KEY="your_secret_api_key"
```

---

## Dashboard & Web Tools (`http://127.0.0.1:8042`)

Make sure `habit_server.py` is running (started automatically by `run.bat` or `start_habit_server.bat`) so interactive widgets can persist changes to SQLite:

| URL | Description |
| :--- | :--- |
| `http://127.0.0.1:8042/` | **Main Dashboard** — Interactive Plotly charts, daily/weekly summary tables, habit calendar, must-done checklist, streak notes, and AI coach panel |
| `http://127.0.0.1:8042/categorize` | **Category Rule Manager** — Browse top uncategorized apps/URLs, add new `config.dat` rules, and retroactively recategorize past logs |
| `http://127.0.0.1:8042/bookmarks` | **Smart Bookmarks** — Searchable saved links with visit durations and custom tags |
| `http://127.0.0.1:8042/bookmarklet` | **Bookmarklet Installer** — Drag-and-drop browser bookmarklet for one-click link saving |

### Preview

*(Early dashboard layout and summary chart snapshots — current builds render interactive Plotly timelines, habit calendars, and coaching cards dynamically at `http://127.0.0.1:8042/`.)*

![Dashboard Preview](images/html_preview.PNG)

![Summary Pie Chart Example](images/example_pie_chart.png)

---

## Cloud Backup & Multi-Device Sync (Optional)

When `DATABASE_URI` is configured in `.env` (and `psycopg2-binary` is installed), Window Recorder incrementally syncs unsynced local SQLite records, habit completions, and must-done tasks to your PostgreSQL database in a non-blocking background worker.

You can also run or test synchronization manually from the CLI:

```powershell
# Preview pending records without writing to the remote database
.\winrecord_env\Scripts\python.exe backup_to_remote.py --dry-run

# Run a full incremental sync in batches of 1000 records
.\winrecord_env\Scripts\python.exe backup_to_remote.py --batch-size 1000
```

*(Note: `api_server.py` and `requirements_server.txt` provide an optional/legacy FastAPI REST server if you prefer HTTP-based log ingestion over direct SQLAlchemy PostgreSQL sync.)*

---

## CLI Utilities & Testing

### Retroactive Recategorization (`recategorize.py`)
After updating `[CATEGORIES]` in `config.dat`, re-classify the past week's logged activities or inspect today's entries for a category:

```powershell
# Re-apply current config.dat rules to the past 7 days of SQLite logs
.\winrecord_env\Scripts\python.exe recategorize.py

# List today's logged window titles & URLs for a specific category
.\winrecord_env\Scripts\python.exe recategorize.py --category "not categorized"
```

### Project Timesheet CLI (`timesheet.py`)
Track explicit named project sessions alongside automatic window categorization:

```powershell
.\winrecord_env\Scripts\python.exe timesheet.py start api-refactor "Auth middleware cleanup"
.\winrecord_env\Scripts\python.exe timesheet.py status
.\winrecord_env\Scripts\python.exe timesheet.py stop
.\winrecord_env\Scripts\python.exe timesheet.py list
```

### Regression Test Suite (`pytest`)
Tests run against a 100% synthetic 7-day fixture (`tests/fixtures/activity_7days.json`). If you ever generate local fixtures from your own database with `tests/extract_test_data.py`, window titles, URLs, and hostnames are anonymized by default.

```powershell
run_tests.bat
# or directly:
.\winrecord_env\Scripts\python.exe -m pytest tests/ -v --tb=short
```

---

## Companion Documentation

- [Database Architecture & Sync Details](docs/DATABASE_ARCHITECTURE.md)
- [Database Maintenance & Cleanup](docs/DATABASE_CLEANUP.md)
- [Habit Server Troubleshooting](HABIT_TROUBLESHOOTING.md)
- [Stock Watch Widget Setup](STOCK_INTEGRATION.md)
- [Microsoft Teams PWA Tracking Notes](TEAMS_TRACKING_NOTES.md)

---

## Roadmap

- [x] Project timesheet CLI (`timesheet.py`) & category rule manager UI (`/categorize`)
- [x] Incremental background cloud sync to Neon PostgreSQL (`backup_to_remote.py`)
- [x] Distraction warning dialog with one-click "Close Wasted Page" action
- [x] Weekend-aware activity summary highlighting & rest-day coaching thresholds
- [ ] AI-assisted category validation & automatic rule suggestions from uncategorized titles
- [ ] Long-term productivity, habit-correlation, and wellbeing pattern insights
- [ ] Migrate AI coach briefing history from local JSON cache into synced database tables
