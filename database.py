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
    Inserts an activity record. It first tries to send it to the remote API.
    If that fails, it saves the record locally.
    """
    # Remote functionality is disabled, always save locally.
    _insert_local_activity(timestamp, category, duration, window_title, source, synced=False, window_url=window_url, window_url_short=window_url_short)
    return True # Assuming local save is successful.

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
