# Database Architecture

## Overview

**Window Recorder uses a SINGLE unified SQLite database** that contains all your data:
- ✅ Activity tracking (window titles, categories, durations)
- ✅ Habit tracking (completions, streaks, timestamps)
- ✅ Projects tracking
- ✅ Warning flags
- ✅ All metadata and audit trails

## Database Location

**File:** `data/activity.sqlite`
**Size:** ~42 MB (as of October 2025)
**Last Updated:** Real-time (updated by script.py and habit_server.py)

## Database Schema

### Core Tables

#### 1. `activity` (Window Tracking Data)
- **53,092+ records** of window activity
- Columns:
  - `id`: Primary key
  - `timestamp`: Unix timestamp (UTC)
  - `category`: Activity category (coding, learning, entertainment, etc.)
  - `duration`: Duration in seconds
  - `window_title`: Full window title text
  - `window_url`: URL if browser window
  - `window_url_short`: Shortened URL
  - `local_date`: Adjusted date based on day boundary (3 AM)
  - `synced`: Sync status flag
  - `source`: Device identifier

#### 2. `habit_completions` (Habit Current State)
- **Current completion status** for each habit/date
- Columns:
  - `id`: Primary key
  - `habit`: Habit name (e.g., "read bible", "exercises")
  - `local_date`: Date in YYYY-MM-DD format
  - `completed`: Boolean (0 or 1)
  - `updated_at`: Unix timestamp of last update
- **Unique constraint:** (habit, local_date)

#### 3. `habit_completion_events` (Habit Audit Trail)
- **Event log** of all habit check/uncheck actions
- Columns:
  - `id`: Primary key
  - `habit`: Habit name
  - `local_date`: Date in YYYY-MM-DD format
  - `completed`: Boolean state after event
  - `happened_at`: Unix timestamp when event occurred

#### 4. `projects` (Project Tracking)
- Project metadata for time tracking

#### 5. `warning_flags` (System Alerts)
- **368 records** of system warnings and events

## Data Flow

### Activity Tracking Flow
```
script.py (monitors windows)
    ↓
database.py (_insert_local_activity)
    ↓
data/activity.sqlite (activity table)
    ↓
analytics.py (reads and analyzes)
    ↓
html/index.html (displays charts)
```

### Habit Tracking Flow
```
html/index.html (user clicks checkbox)
    ↓
JavaScript fetch POST → http://127.0.0.1:8042/habits
    ↓
habit_server.py (handles request)
    ↓
database.py (record_habit_completion)
    ↓
data/activity.sqlite (habit_completions + habit_completion_events)
    ↓
analytics.py (reads completions, calculates streaks)
    ↓
html/index.html (displays updated calendar)
```

## Cloud Sync Ready

Your database is **ready for cloud synchronization**:
- ✅ **Single file**: `data/activity.sqlite` contains everything
- ✅ **Portable**: Standard SQLite format
- ✅ **Sync-aware**: `synced` column tracks cloud status
- ✅ **Source tracking**: `source` column identifies device

### Existing Sync Infrastructure

The codebase already has sync support:
- `sync_databases.py`: Bidirectional sync between local and remote
- `database.py` functions:
  - `get_unsynced_activities()`: Find local changes
  - `mark_activities_as_synced()`: Update sync status
  - `sync_from_remote()`: Pull remote data
- `api_server.py`: REST API for remote access
- Environment variables:
  - `WINDOW_RECORDER_API_URL`: Remote server URL
  - `DATABASE_URL`: Database connection string

### Cloud Sync Options

**Option 1: Simple File Sync**
- Use Dropbox/Google Drive/OneDrive
- Move `data/activity.sqlite` to synced folder
- Update `DB_FILE` path in `database.py`
- ⚠️ Warning: May have conflicts with concurrent writes

**Option 2: Use Existing API Server**
- Already implemented in `api_server.py`
- Deploy to cloud (Render, Railway, etc.)
- Run `sync_databases.py` periodically
- ✅ Handles conflicts properly

**Option 3: Hybrid Approach**
- Keep local database as-is
- Periodic backup to cloud storage
- Use API for multi-device sync

## Database Maintenance

### Backup
```bash
# Create timestamped backup
cp data/activity.sqlite "data/activity_backup_$(date +%Y%m%d).sqlite"
```

### Check Database Size
```bash
ls -lh data/activity.sqlite
```

### Verify Integrity
```bash
sqlite3 data/activity.sqlite "PRAGMA integrity_check;"
```

### Compact Database
```bash
sqlite3 data/activity.sqlite "VACUUM;"
```

## Migration History

### Timeline
1. **Early 2025**: CSV-based storage (`activity.csv`)
2. **Mid 2025**: Migrated to `activity.db` (root directory)
3. **September 2025**: Reorganized to `data/activity.sqlite`
4. **October 2025**: Added habit tracking tables

### Old Files (Deprecated)
- ❌ `activity.db` → Renamed to `activity.db.old` (backup)
- ❌ `activity.csv` → Historical only

## Configuration

All references now point to the unified database:

| File | Variable/Constant | Value |
|------|------------------|-------|
| `database.py` | `DB_FILE` | `'data/activity.sqlite'` |
| `api_server.py` | `DATABASE_URL` | `'sqlite:///./data/activity.sqlite'` |
| `show_db.py` | `DB_FILE` | `'data/activity.sqlite'` |

## Statistics (as of October 14, 2025)

- **Total activity records**: 53,092
- **Habit completions**: 2
- **Habit events logged**: 3
- **Warning flags**: 368
- **Projects tracked**: 6
- **Database size**: 41.8 MB
- **Date range**: Multiple months of data

## Summary

✅ **ONE database** contains everything  
✅ **Ready for cloud sync** (single file, sync infrastructure exists)  
✅ **Well-structured** (proper tables, indexes, constraints)  
✅ **Actively maintained** (regular updates, integrity checks)  
✅ **Documented** (clear schema, data flow understood)

Your data is organized, consolidated, and ready to be synced to the cloud whenever you're ready! 🚀
