import sqlite3
import os
import pandas as pd
import requests
import datetime
import time
import pytz
from sqlalchemy import create_engine, text
from config import TIMEZONE, API_KEY, DAY_BOUNDARY_HOUR, get_database_uri

# --- Configuration ---
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'

# --- Remote Database Connection ---
REMOTE_DB_URI = get_database_uri()
remote_engine = None
if REMOTE_DB_URI:
    try:
        remote_engine = create_engine(REMOTE_DB_URI)
        print("Successfully connected to the remote database.")
        print("WARNING: Remote sync is DISABLED. Database connection is active but not used for data storage.")
    except Exception as e:
        print(f"Could not connect to the remote database: {e}")
        remote_engine = None

# --- Local Database Functions ---

def calculate_adjusted_local_date(timestamp):
    """
    Calculate the local date for activity tracking, adjusting for the configured day boundary.
    If the activity occurs before the day boundary hour (e.g., 3 AM), it's considered
    part of the previous day.
    """
    tz = pytz.timezone(TIMEZONE)
    utc_dt = pytz.utc.localize(datetime.datetime.utcfromtimestamp(timestamp))
    local_dt = utc_dt.astimezone(tz)
    
    # If the hour is before the day boundary, consider it part of the previous day
    if local_dt.hour < DAY_BOUNDARY_HOUR:
        adjusted_dt = local_dt - datetime.timedelta(days=1)
        return adjusted_dt.strftime('%Y-%m-%d')
    else:
        return local_dt.strftime('%Y-%m-%d')

def initialize_database():
    # Initialize local SQLite database
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                category TEXT NOT NULL,
                duration INTEGER NOT NULL,
                window_title TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                source TEXT,
                window_url TEXT,
                window_url_short TEXT,
                local_date TEXT
            )
        ''')
        # Add other local tables if needed
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS warning_flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE,
                timestamp REAL NOT NULL,
                elapsed_seconds REAL NOT NULL,
                result TEXT NOT NULL,
                message TEXT,
                title TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS habit_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit TEXT NOT NULL,
                local_date TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 1,
                updated_at REAL,
                UNIQUE(habit, local_date)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS habit_completion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit TEXT NOT NULL,
                local_date TEXT NOT NULL,
                completed INTEGER NOT NULL,
                happened_at REAL NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS must_done_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                week_id TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at REAL,
                UNIQUE(task_id, week_id)
            )
        ''')

        # Ad-hoc "Must be Done" items (user-created). These are stored in buckets so
        # they can be weekly, monthly, or persistent.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS must_be_done_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_type TEXT NOT NULL,
                bucket_id TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at REAL NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at REAL,
                UNIQUE(bucket_type, bucket_id, description)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streak_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        ''')

        # Migrate existing streak_notes to ensure required columns exist
        try:
            cursor.execute("PRAGMA table_info(streak_notes)")
            cols = {row[1] for row in cursor.fetchall()}
            if 'timestamp' not in cols:
                # Add missing timestamp column and backfill with current time
                cursor.execute("ALTER TABLE streak_notes ADD COLUMN timestamp REAL")
                cursor.execute("UPDATE streak_notes SET timestamp = ? WHERE timestamp IS NULL", (time.time(),))
        except Exception as e:
            print(f"WARNING: could not migrate streak_notes schema: {e}")

def _streak_notes_schema(cursor) -> list[tuple]:
    """Return PRAGMA table_info rows for streak_notes."""
    cursor.execute("PRAGMA table_info(streak_notes)")
    return cursor.fetchall()

def _streak_notes_columns(cursor) -> set[str]:
    return {row[1] for row in _streak_notes_schema(cursor)}

def add_streak_note(note: str, ts: float | None = None) -> int:
    """Insert a note tied to the productivity streak timeline.
    Handles legacy schemas (created_at) and new schema (timestamp).
    Returns the inserted note id.
    """
    if not note or not note.strip():
        return 0
    ts = ts if ts is not None else time.time()
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        schema = _streak_notes_schema(cursor)
        # schema rows: (cid, name, type, notnull, dflt_value, pk)
        insert_cols = []
        insert_vals = []
        for (_cid, name, _type, notnull, dflt, pk) in schema:
            if pk == 1:
                continue  # skip primary key
            if name == 'note':
                insert_cols.append('note')
                insert_vals.append(note.strip())
            elif name in ('timestamp', 'created_at', 'streak_start'):
                # Use ts for any time-related required columns
                insert_cols.append(name)
                insert_vals.append(ts)
            else:
                # For other NOT NULL columns without default, put safe value
                if notnull == 1 and dflt is None:
                    # Try boolean/integer default 0
                    insert_cols.append(name)
                    insert_vals.append(0)
                # else skip optional columns

        if not insert_cols:
            # No known columns; attempt minimal
            cursor.execute("INSERT INTO streak_notes DEFAULT VALUES")
        else:
            placeholders = ', '.join(['?'] * len(insert_cols))
            sql = f"INSERT INTO streak_notes ({', '.join(insert_cols)}) VALUES ({placeholders})"
            cursor.execute(sql, insert_vals)
        conn.commit()
        return cursor.lastrowid


def get_must_be_done_items(
    bucket_type: str,
    bucket_id: str,
    include_completed: bool = True,
) -> list[dict]:
    """Return ad-hoc Must-be-done items for a given bucket."""
    bucket_type = (bucket_type or '').strip().lower()
    bucket_id = (bucket_id or '').strip()
    if not bucket_type or not bucket_id:
        return []

    query = (
        "SELECT id, description, completed, completed_at, created_at "
        "FROM must_be_done_items WHERE bucket_type = ? AND bucket_id = ?"
    )
    params: tuple = (bucket_type, bucket_id)
    if not include_completed:
        query += " AND completed = 0"

    query += " ORDER BY completed ASC, created_at ASC, id ASC"

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception:
        return []

    return [
        {
            'id': int(row[0]),
            'description': row[1],
            'completed': bool(row[2]),
            'completed_at': row[3],
            'created_at': row[4],
            'bucket_type': bucket_type,
            'bucket_id': bucket_id,
        }
        for row in rows
    ]


def get_must_be_done_items_multi(
    bucket_type: str,
    bucket_ids: list[str],
    include_completed: bool = True,
) -> list[dict]:
    """Return ad-hoc Must-be-done items for a bucket_type across many bucket_ids."""
    bucket_type = (bucket_type or '').strip().lower()
    bucket_ids = [str(b).strip() for b in (bucket_ids or []) if str(b).strip()]
    if not bucket_type or not bucket_ids:
        return []

    placeholders = ','.join(['?'] * len(bucket_ids))
    query = (
        "SELECT id, bucket_id, description, completed, completed_at, created_at "
        "FROM must_be_done_items WHERE bucket_type = ? AND bucket_id IN ("
        + placeholders
        + ")"
    )
    params: list = [bucket_type] + bucket_ids
    if not include_completed:
        query += " AND completed = 0"
    query += " ORDER BY completed ASC, created_at ASC, id ASC"

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
    except Exception:
        return []

    return [
        {
            'id': int(row[0]),
            'bucket_type': bucket_type,
            'bucket_id': row[1],
            'description': row[2],
            'completed': bool(row[3]),
            'completed_at': row[4],
            'created_at': row[5],
        }
        for row in rows
    ]


def add_must_be_done_item(bucket_type: str, bucket_id: str, description: str) -> dict | None:
    """Create an ad-hoc Must-be-done item and return its record."""
    bucket_type = (bucket_type or '').strip().lower()
    bucket_id = (bucket_id or '').strip()
    description = (description or '').strip()
    if not bucket_type or not bucket_id or not description:
        return None

    now_ts = time.time()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO must_be_done_items
                    (bucket_type, bucket_id, description, created_at, completed, completed_at)
                VALUES
                    (?, ?, ?, ?, 0, NULL)
                """,
                (bucket_type, bucket_id, description, now_ts),
            )
            conn.commit()

            # Fetch the existing/inserted row (unique on bucket+desc).
            cur.execute(
                """
                SELECT id, description, completed, completed_at, created_at
                FROM must_be_done_items
                WHERE bucket_type = ? AND bucket_id = ? AND description = ?
                """,
                (bucket_type, bucket_id, description),
            )
            row = cur.fetchone()
    except Exception:
        return None

    if not row:
        return None
    return {
        'id': int(row[0]),
        'description': row[1],
        'completed': bool(row[2]),
        'completed_at': row[3],
        'created_at': row[4],
        'bucket_type': bucket_type,
        'bucket_id': bucket_id,
    }


def set_must_be_done_item_completed(item_id: int, completed: bool) -> bool:
    """Update completion for a given ad-hoc item."""
    try:
        item_id_int = int(item_id)
    except Exception:
        return False

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            if completed:
                cur.execute(
                    "UPDATE must_be_done_items SET completed = 1, completed_at = ? WHERE id = ?",
                    (time.time(), item_id_int),
                )
            else:
                cur.execute(
                    "UPDATE must_be_done_items SET completed = 0, completed_at = NULL WHERE id = ?",
                    (item_id_int,),
                )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def delete_must_be_done_item(item_id: int) -> bool:
    """Delete an ad-hoc Must-be-done item."""
    try:
        item_id_int = int(item_id)
    except Exception:
        return False

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM must_be_done_items WHERE id = ?", (item_id_int,))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def save_streak_note(note: str) -> bool:
    """Compatibility helper to save a note and return success boolean."""
    try:
        return add_streak_note(note) > 0
    except Exception:
        return False

def get_today_streak_notes(limit: int = 3) -> list[tuple[int, str, float]]:
    """Fetch up to `limit` notes for today (respecting DAY_BOUNDARY_HOUR).
    Returns list of tuples (id, note, timestamp) sorted newest-first.
    """
    tz = pytz.timezone(TIMEZONE)
    now_local = datetime.datetime.now(tz)
    # If before boundary, consider notes since yesterday boundary
    boundary_hour = DAY_BOUNDARY_HOUR
    if now_local.hour < boundary_hour:
        start_day = (now_local - datetime.timedelta(days=1)).date()
    else:
        start_day = now_local.date()
    start_dt = tz.localize(datetime.datetime.combine(start_day, datetime.time(hour=boundary_hour)))
    start_ts = start_dt.timestamp()
    end_ts = (start_dt + datetime.timedelta(days=1)).timestamp()

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cols = _streak_notes_columns(cursor)
        time_col = 'timestamp' if 'timestamp' in cols else ('created_at' if 'created_at' in cols else None)
        if not time_col:
            return []
        cursor.execute(
            f"SELECT id, note, {time_col} as ts FROM streak_notes WHERE {time_col} >= ? AND {time_col} < ? ORDER BY {time_col} DESC LIMIT ?",
            (start_ts, end_ts, limit),
        )
        rows = cursor.fetchall()
        # Normalize to (id, note, timestamp)
        return [(r[0], r[1], r[2]) for r in rows]

def get_recent_streak_notes(limit: int = 5) -> list[tuple[str, float]]:
    """Fetch most recent notes regardless of date, returns (note, timestamp)."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cols = _streak_notes_columns(cursor)
        time_col = 'timestamp' if 'timestamp' in cols else ('created_at' if 'created_at' in cols else None)
        if not time_col:
            return []
        cursor.execute(
            f"SELECT note, {time_col} as ts FROM streak_notes ORDER BY {time_col} DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [(r[0], r[1]) for r in rows]


def parse_note_tags(note: str) -> tuple[list[str], str]:
    """Parse hashtags from a note.
    
    Returns (tags, clean_note) where:
    - tags: list of tags found (without # prefix), e.g. ['done', 'todo', 'blocked']
    - clean_note: the note text with tags removed
    
    Example:
        parse_note_tags("Fixed the bug #done #coding")
        -> (['done', 'coding'], "Fixed the bug")
    """
    import re
    tags = re.findall(r'#(\w+)', note)
    clean_note = re.sub(r'\s*#\w+', '', note).strip()
    return tags, clean_note


def get_today_notes_with_tags(limit: int = 10) -> list[dict]:
    """Fetch today's notes parsed with their tags.
    
    Returns list of dicts with keys:
    - 'note': original note text
    - 'clean_note': note without tags
    - 'tags': list of tags found
    - 'timestamp': unix timestamp
    - 'time_str': formatted time string (HH:MM)
    """
    notes = get_today_streak_notes(limit)
    tz = pytz.timezone(TIMEZONE)
    
    result = []
    for note_id, note, ts in notes:
        tags, clean_note = parse_note_tags(note)
        dt = datetime.datetime.fromtimestamp(ts, tz)
        result.append({
            'id': note_id,
            'note': note,
            'clean_note': clean_note,
            'tags': tags,
            'timestamp': ts,
            'time_str': dt.strftime('%H:%M'),
        })
    return result


def get_notes_summary_for_coaching() -> dict:
    """Get a summary of today's notes organized by tags for AI coaching.
    
    Returns dict with:
    - 'all_notes': list of all note dicts
    - 'done_items': notes tagged #done
    - 'todo_items': notes tagged #todo
    - 'blocked_items': notes tagged #blocked
    - 'focus_items': notes tagged #focus
    - 'tags_count': dict of tag -> count
    """
    notes = get_today_notes_with_tags(limit=20)
    
    summary = {
        'all_notes': notes,
        'done_items': [],
        'todo_items': [],
        'blocked_items': [],
        'focus_items': [],
        'tags_count': {},
    }
    
    for note in notes:
        for tag in note['tags']:
            tag_lower = tag.lower()
            summary['tags_count'][tag_lower] = summary['tags_count'].get(tag_lower, 0) + 1
            
            if tag_lower == 'done':
                summary['done_items'].append(note)
            elif tag_lower in ('todo', 'task'):
                summary['todo_items'].append(note)
            elif tag_lower in ('blocked', 'stuck'):
                summary['blocked_items'].append(note)
            elif tag_lower in ('focus', 'priority'):
                summary['focus_items'].append(note)
    
    return summary



    # Initialize remote PostgreSQL database
    if remote_engine:
        try:
            with remote_engine.connect() as connection:
                # Create activity table
                connection.execute(text('''
                    CREATE TABLE IF NOT EXISTS activity (
                        id SERIAL PRIMARY KEY,
                        timestamp DOUBLE PRECISION NOT NULL,
                        category VARCHAR(255) NOT NULL,
                        duration INTEGER NOT NULL,
                        window_title TEXT NOT NULL,
                        synced BOOLEAN DEFAULT FALSE,
                        source VARCHAR(255),
                        window_url TEXT,
                        window_url_short TEXT,
                        local_date DATE
                    )
                '''))
                # Create warning_flags table
                connection.execute(text('''
                    CREATE TABLE IF NOT EXISTS warning_flags (
                        id SERIAL PRIMARY KEY,
                        event_id VARCHAR(255) UNIQUE,
                        timestamp DOUBLE PRECISION NOT NULL,
                        elapsed_seconds DOUBLE PRECISION NOT NULL,
                        result VARCHAR(255) NOT NULL,
                        message TEXT,
                        title TEXT
                    )
                '''))
                # Create habit_completions table
                connection.execute(text('''
                    CREATE TABLE IF NOT EXISTS habit_completions (
                        id SERIAL PRIMARY KEY,
                        habit VARCHAR(255) NOT NULL,
                        local_date DATE NOT NULL,
                        completed BOOLEAN NOT NULL DEFAULT TRUE,
                        updated_at DOUBLE PRECISION,
                        UNIQUE(habit, local_date)
                    )
                '''))
                # Create habit_completion_events table
                connection.execute(text('''
                    CREATE TABLE IF NOT EXISTS habit_completion_events (
                        id SERIAL PRIMARY KEY,
                        habit VARCHAR(255) NOT NULL,
                        local_date DATE NOT NULL,
                        completed BOOLEAN NOT NULL,
                        happened_at DOUBLE PRECISION NOT NULL
                    )
                '''))
                connection.commit()
                print("Remote database initialized successfully.")
                print("WARNING: Remote database tables created but sync is DISABLED. All data saves to local SQLite only.")
        except Exception as e:
            print(f"Error initializing remote database: {e}")

def _insert_local_activity(timestamp, category, duration, window_title, source='unknown', synced=False, window_url=None, window_url_short=None):
    """Inserts a single activity record into the local database, including the local_date."""
    local_date_str = calculate_adjusted_local_date(timestamp)

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # We need to handle the case where the migration hasn't been run yet
        cursor.execute("PRAGMA table_info(activity)")
        columns = [column[1] for column in cursor.fetchall()]
        has_local_date = 'local_date' in columns
        has_window_url = 'window_url' in columns
        has_window_url_short = 'window_url_short' in columns

        column_names = ['timestamp', 'category', 'duration', 'window_title']
        values = [timestamp, category, duration, window_title]

        if has_window_url:
            column_names.append('window_url')
            values.append(window_url)

        if has_window_url_short:
            column_names.append('window_url_short')
            values.append(window_url_short)

        column_names.append('synced')
        values.append(1 if synced else 0)

        if has_local_date:
            column_names.append('local_date')
            values.append(local_date_str)

        column_names.append('source')
        values.append(source)

        placeholders = ', '.join('?' for _ in column_names)
        cursor.execute(f"""
            INSERT INTO activity ({', '.join(column_names)})
            VALUES ({placeholders})
        """, values)

# --- API Communication Functions ---

def wait_for_server(max_retries=5, delay=10):
    """
    Waits for the remote server to be available by making a simple request.
    Retries a few times before giving up.
    """
    # Remote functionality is disabled.
    print("Remote sync is disabled. Assuming server is unavailable.")
    return False

def get_headers():
    """Returns the authorization headers for API requests."""
    # Remote functionality is disabled.
    return {}

def insert_activity(timestamp, category, duration, window_title, source, window_url=None, window_url_short=None):
    """
    Inserts an activity record, splitting it if it spans the day boundary.
    
    If an activity started before DAY_BOUNDARY_HOUR and ended after it,
    we split it into two records - one for each logical day.
    """
    tz = pytz.timezone(TIMEZONE)
    
    # Calculate start and end times
    end_time = datetime.datetime.fromtimestamp(timestamp, tz)
    start_time = end_time - datetime.timedelta(seconds=duration)
    
    # Calculate the day boundary time for the end time's date
    # Day boundary is at DAY_BOUNDARY_HOUR on the calendar date
    boundary_date = end_time.date()
    if end_time.hour < DAY_BOUNDARY_HOUR:
        # If we're before boundary hour, the boundary we care about is today's
        boundary_datetime = tz.localize(datetime.datetime.combine(boundary_date, datetime.time(DAY_BOUNDARY_HOUR)))
    else:
        # If we're after boundary hour, check if activity started before today's boundary
        boundary_datetime = tz.localize(datetime.datetime.combine(boundary_date, datetime.time(DAY_BOUNDARY_HOUR)))
    
    # Check if activity spans the boundary
    if start_time < boundary_datetime <= end_time:
        # Split the activity at the boundary
        # Part 1: from start_time to boundary (belongs to previous logical day)
        duration_before = (boundary_datetime - start_time).total_seconds()
        timestamp_before = boundary_datetime.timestamp()  # End timestamp for part 1
        
        # Part 2: from boundary to end_time (belongs to current logical day)
        duration_after = (end_time - boundary_datetime).total_seconds()
        timestamp_after = timestamp  # Original end timestamp
        
        # Insert both parts (only if they have meaningful duration)
        if duration_before >= 1:  # At least 1 second
            _insert_local_activity(timestamp_before, category, int(duration_before), 
                                   window_title, source, synced=False, 
                                   window_url=window_url, window_url_short=window_url_short)
        if duration_after >= 1:  # At least 1 second
            _insert_local_activity(timestamp_after, category, int(duration_after), 
                                   window_title, source, synced=False, 
                                   window_url=window_url, window_url_short=window_url_short)
    else:
        # No split needed - insert as normal
        _insert_local_activity(timestamp, category, duration, window_title, source, 
                               synced=False, window_url=window_url, window_url_short=window_url_short)
    
    return True

def fetch_available_days():
    """
    Fetches a list of unique days directly from the local_date column.
    """
    try:
        # This is the fallback path, so we always read from the local DB
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT local_date FROM activity ORDER BY local_date DESC")
            days = [row[0] for row in cursor.fetchall() if row[0] is not None]
            return days
    except Exception as e:
        print(f"Error fetching available days from local DB: {e}")
        return []

def get_activity_count():
    """
    Returns the total number of activities in the database.
    Used to detect if new activities have been added.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM activity")
            count = cursor.fetchone()[0]
            return count
    except Exception as e:
        print(f"Error getting activity count: {e}")
        return 0


def get_latest_activity_timestamp() -> float | None:
    """Return the newest activity.timestamp in the local DB, or None if empty."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(timestamp) FROM activity")
            value = cursor.fetchone()[0]
            return float(value) if value is not None else None
    except Exception as e:
        print(f"Error getting latest activity timestamp: {e}")
        return None

def fetch_summary_for_day(date_str):
    """
    Fetches a summary for a specific day directly from the local_date column.
    """
    try:
        # This is the fallback path, so we always read from the local DB
        with sqlite3.connect(DB_FILE) as conn:
            query = "SELECT category, SUM(duration) as total_duration FROM activity WHERE local_date = ? GROUP BY category"
            df = pd.read_sql_query(query, conn, params=(date_str,))
            u_cats = df['category'].tolist()
            u_dur = df['total_duration'].tolist()
            return u_cats, u_dur
    except Exception as e:
        print(f"Error fetching summary for day {date_str} from local DB: {e}")
        return [], []

def _fetch_local_data_grouped_by_day():
    # This function is no longer needed, but we'll keep it for now to avoid breaking other parts of the code.
    # It will not be called by the main analytics flow anymore.
    pass

def fetch_log_for_day(date_str):
    """
    Fetches the detailed activity log for a specific day from the local_date column.
    Returns a pandas DataFrame.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Determine available columns dynamically
            cursor.execute("PRAGMA table_info(activity)")
            columns = [column[1] for column in cursor.fetchall()]

            select_columns = ['timestamp', 'category', 'duration', 'window_title']
            if 'window_url' in columns:
                select_columns.append('window_url')
            if 'window_url_short' in columns:
                select_columns.append('window_url_short')
            if 'source' in columns:
                select_columns.append('source')

            query = f"SELECT {', '.join(select_columns)} FROM activity WHERE local_date = ? ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn, params=(date_str,))
            return df
    except Exception as e:
        print(f"Error fetching detailed log for day {date_str} from local DB: {e}")
        return pd.DataFrame()

def sync_local_data():
    """
    Synchronizes unsynced local data with the remote server.
    """
    # Remote functionality is disabled.
    print("Remote sync is disabled. Skipping sync.")
    return

def _get_unsynced_local_data():
    """
    Retrieves all records from the local database that have not been synced.
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, category, duration, window_title, source FROM activity WHERE synced = 0")
        return cursor.fetchall()

def _mark_as_synced(record_ids):
    """
    Marks a list of records as synced in the local database.
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.executemany("UPDATE activity SET synced = 1 WHERE id = ?", [(id,) for id in record_ids])

def sync_remote_to_local():
    """
    Fetches all records from the remote server and inserts any missing records
    into the local database. This allows for a unified view of data from all clients.
    """
    print("turn this off for now. the timestamp is a mess between remote and local")
    return
    
    print("Starting sync from remote server to local database...")
    
    # 1. Fetch all data from the remote server
    try:
        response = requests.get(f"{API_BASE_URL}/logs?limit=30000", headers=get_headers(), timeout=60)
        response.raise_for_status()
        remote_data = response.json()
        if not remote_data:
            print("No data on remote server. Sync complete.")
            return
        print(f"Fetched {len(remote_data)} records from remote server.")
    except requests.RequestException as e:
        print(f"Network Error: Could not fetch data from remote server. {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred while fetching remote data: {e}")
        return

    # 2. Get existing local records to avoid duplicates
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, window_title, source FROM activity")
            # Create a set of tuples for quick lookup. Round timestamp to avoid float precision issues.
            local_records = {(round(ts, 2), title, src) for ts, title, src in cursor.fetchall()}
    except Exception as e:
        print(f"Error reading from local database: {e}")
        return

    # 3. Find new records by comparing with the local set
    new_records_to_insert = []
    for record in remote_data:
        # Convert remote timestamp string to float for comparison
        utc_dt = datetime.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
        timestamp_float = utc_dt.timestamp()

        # Check for existence based on a tuple of rounded timestamp, title, and source
        source = record.get('source') # This will be None if not present
        
        if (round(timestamp_float, 2), record['window_title'], source) not in local_records:
            new_records_to_insert.append(record)

    if not new_records_to_insert:
        print("Local database is already up-to-date.")
        return

    print(f"Found {len(new_records_to_insert)} new records to insert locally.")
    
    # 4. Batch insert new records
    batch = []
    for record in new_records_to_insert:
        # Always treat remote timestamp as UTC
        utc_dt = datetime.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
        timestamp_float = utc_dt.timestamp()
        category = record['category']
        duration = record['duration']
        window_title = record['window_title']
        source = record.get('source') # Keep as None if not present
        
        # Calculate adjusted local date using day boundary
        local_date_str = calculate_adjusted_local_date(timestamp_float)
        
        batch.append((timestamp_float, category, duration, window_title, 1, local_date_str, source))

    if batch:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # This assumes the local_date column exists, which it should by now.
            cursor.executemany(
                'INSERT INTO activity (timestamp, category, duration, window_title, synced, local_date, source) VALUES (?, ?, ?, ?, ?, ?, ?)',
                batch
            )
        print(f"Batch inserted {len(batch)} new records.")
    print("Successfully synced remote data to local database.")

def delete_remote_activities_by_title(window_title):
    """
    Sends a request to the remote API to delete all records with a specific window_title.
    """
    # Remote functionality is disabled.
    print("Remote sync is disabled. Cannot delete remote data.")
    return False

def delete_remote_activities_by_ids(ids):
    """
    Sends a request to the remote API to delete a list of records by their IDs.
    """
    # Remote functionality is disabled.
    print("Remote sync is disabled. Cannot delete remote data.")
    return False

def fetch_recent_activities(limit=20, offset=0):
    """Fetches recent activities from the local database with a limit and offset."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(activity)")
            columns = [column[1] for column in cursor.fetchall()]

            select_columns = ['id', 'timestamp', 'window_title', 'duration', 'category']
            if 'window_url_short' in columns:
                select_columns.append('window_url_short')
            if 'window_url' in columns:
                select_columns.append('window_url')
            if 'source' in columns:
                select_columns.append('source')

            query = f"""
                SELECT {', '.join(select_columns)}
                FROM activity
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, (limit, offset))
            return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching recent activities: {e}")
        return []


def record_warning_flag(event_id, timestamp, elapsed_seconds, result, message=None, title=None):
    """Persists the outcome of a warning dialog interaction."""
    if not event_id or not result:
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                    INSERT INTO warning_flags (event_id, timestamp, elapsed_seconds, result, message, title)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        timestamp=excluded.timestamp,
                        elapsed_seconds=excluded.elapsed_seconds,
                        result=excluded.result,
                        message=excluded.message,
                        title=excluded.title
                """,
                (event_id, timestamp, elapsed_seconds, result, message, title)
            )
            conn.commit()
    except Exception as exc:
        print(f"Error recording warning flag result: {exc}")


def get_warning_flag_counts():
    """Returns aggregate counts of winning and losing warning flags."""
    counts = {'win': 0, 'lose': 0}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT result, COUNT(*) FROM warning_flags GROUP BY result")
            for result, total in cursor.fetchall():
                if result in counts:
                    counts[result] = total
    except Exception as exc:
        print(f"Error fetching warning flag counts: {exc}")

    return counts


def record_habit_completion(habit, local_date, completed=True):
    """Creates or updates a habit completion record for the given local date."""
    if not habit or not local_date:
        return None

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            now_ts = time.time()
            completed_flag = 1 if completed else 0
            cursor.execute(
                """
                    INSERT INTO habit_completions (habit, local_date, completed, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(habit, local_date) DO UPDATE SET
                        completed=excluded.completed,
                        updated_at=excluded.updated_at
                """,
                (habit, local_date, completed_flag, now_ts)
            )
            cursor.execute(
                """
                    INSERT INTO habit_completion_events (habit, local_date, completed, happened_at)
                    VALUES (?, ?, ?, ?)
                """,
                (habit, local_date, completed_flag, now_ts)
            )
            conn.commit()
            return {'habit': habit, 'local_date': local_date, 'completed': bool(completed_flag), 'updated_at': now_ts}
    except Exception as exc:
        print(f"Error recording habit completion: {exc}")
    return None


def get_habit_completions(habits=None, start_date=None, end_date=None):
    """Returns a mapping of habit -> {local_date: {completed: bool, updated_at: float | None}}."""
    results = {}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            query = "SELECT habit, local_date, completed, updated_at FROM habit_completions WHERE 1=1"
            params = []

            if habits:
                placeholders = ','.join('?' for _ in habits)
                query += f" AND habit IN ({placeholders})"
                params.extend(habits)

            if start_date:
                query += " AND local_date >= ?"
                params.append(start_date)

            if end_date:
                query += " AND local_date <= ?"
                params.append(end_date)

            query += " ORDER BY local_date ASC"

            cursor.execute(query, params)
            for habit, local_date, completed, updated_at in cursor.fetchall():
                habit_map = results.setdefault(habit, {})
                habit_map[local_date] = {
                    'completed': bool(completed),
                    'updated_at': updated_at
                }
    except Exception as exc:
        print(f"Error fetching habit completions: {exc}")

    # Ensure requested habits exist in map even if empty
    if habits:
        for habit in habits:
            results.setdefault(habit, {})

    return results


def delete_activity(activity_id):
    """Deletes a single activity from the local database by its ID."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM activity WHERE id = ?", (activity_id,))
            conn.commit()
            # Check if the row was actually deleted
            return cursor.rowcount > 0
    except Exception as e:
        print(f"Error deleting activity with ID {activity_id}: {e}")
        return False


def get_must_done_status_for_week(week_id: str) -> dict:
    """
    Get the completion status of all Must Done items for a given week.
    Returns a dict of task_id -> completed (bool).
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT task_id, completed FROM must_done_items WHERE week_id = ?",
                (week_id,)
            )
            rows = cursor.fetchall()
            return {task_id: bool(completed) for task_id, completed in rows}
    except Exception as e:
        print(f"Error retrieving must done status: {e}")
        return {}


def get_must_done_summary_for_coaching() -> list[dict]:
    """Get Must Done tasks with their completion status for AI coaching context.

    Reads task definitions from config.dat [MUST_DONE] section and checks
    completion against the current week_id in the database.

    Returns list of dicts with keys:
        task_id, description, day, deadline_time, completed (bool)
    """
    import configparser

    config = configparser.ConfigParser()
    config.read("config.dat", encoding='utf-8')

    if not config.has_section("MUST_DONE"):
        return []

    # Parse task definitions
    tasks: list[dict] = []
    for task_id in config.options("MUST_DONE"):
        task_def = config.get("MUST_DONE", task_id)
        parts = [p.strip() for p in task_def.split(",", 2)]
        if len(parts) == 3:
            tasks.append({
                "task_id": task_id,
                "day": parts[0],
                "deadline_time": parts[1],
                "description": parts[2],
            })

    if not tasks:
        return []

    # Determine current week_id (Monday date of current week)
    tz = pytz.timezone(TIMEZONE)
    now = datetime.datetime.now(tz)
    # ISO weekday: Monday=1 ... Sunday=7
    monday = (now - datetime.timedelta(days=now.weekday())).date()
    week_id = monday.strftime("%Y-%m-%d")

    status_map = get_must_done_status_for_week(week_id)

    for task in tasks:
        task["completed"] = status_map.get(task["task_id"], False)

    return tasks



