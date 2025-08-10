import sqlite3
import os
import pandas as pd
import requests
import datetime
import time

# --- Configuration ---
# This is your actual Render API URL.
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'

# --- Global Cache ---
data_cache = {
    "timestamp": None,
    "data": None
}
CACHE_DURATION_SECONDS = 300 # 5 minutes

def clear_cache():
    """Clears the global data cache."""
    global data_cache
    # print("Clearing data cache.") # Can be noisy, commenting out
    data_cache["timestamp"] = None
    data_cache["data"] = None

# --- Local Database Functions ---

def initialize_database():
    """
    Initializes the local database. Creates the table if it doesn't exist,
    and adds the 'synced' column if it's missing from an existing table.
    """
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create table if it doesn't exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            category TEXT NOT NULL,
            duration INTEGER NOT NULL,
            window_title TEXT NOT NULL
        )
    ''')

    # Check if 'synced' column exists
    cursor.execute("PRAGMA table_info(activity)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'synced' not in columns:
        print("Adding 'synced' column to local database.")
        cursor.execute('ALTER TABLE activity ADD COLUMN synced INTEGER DEFAULT 0')

    conn.commit()
    conn.close()

def _insert_local_activity(timestamp, category, duration, window_title, synced=False):
    """Inserts a single activity record into the local database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO activity (timestamp, category, duration, window_title, synced)
        VALUES (?, ?, ?, ?, ?)
    ''', (timestamp, category, duration, window_title, 1 if synced else 0))
    conn.commit()
    conn.close()

# --- API Communication Functions ---

def insert_activity(timestamp, category, duration, window_title):
    """
    Tries to send an activity to the API server.
    If it fails, saves the record to the local database.
    """
    api_url = f"{API_BASE_URL}/log"
    payload = {
        "timestamp": timestamp,
        "category": category,
        "duration": duration,
        "window_title": window_title
    }
    try:
        response = requests.post(api_url, json=payload, timeout=5)
        if response.status_code == 200:
            _insert_local_activity(timestamp, category, duration, window_title, synced=True)
            # print("Activity logged to server.") # This can be noisy, commenting out.
            return True
        else:
            print(f"API Error: {response.status_code}. Saving locally.")
            _insert_local_activity(timestamp, category, duration, window_title, synced=False)
            return False
    except requests.RequestException:
        print(f"Network Error. Saving locally.")
        _insert_local_activity(timestamp, category, duration, window_title, synced=False)
        return False

def fetch_available_days():
    """
    Fetches a list of days with available data from the API server.
    Falls back to local database if the server is unavailable.
    """
    print("Attempting to fetch available days from server...")
    try:
        response = requests.get(f"{API_BASE_URL}/days", timeout=15)
        response.raise_for_status()
        days = response.json()
        print(f"Successfully fetched {len(days)} days from server.")
        return days
    except requests.RequestException as e:
        print(f"Could not connect to server for days list: {e}. Falling back to local data.")
        local_data = _fetch_local_data_grouped_by_day()
        return sorted(list(local_data.keys()), reverse=True)

def fetch_summary_for_day(date_str):
    """
    Fetches a pre-aggregated summary for a specific day from the API server.
    Falls back to local database if the server is unavailable.
    """
    print(f"Attempting to fetch summary for {date_str} from server...")
    try:
        response = requests.get(f"{API_BASE_URL}/summary/{date_str}", timeout=15)
        response.raise_for_status()
        summary_data = response.json()
        # Convert to the format expected by the analytics script
        # It expects a list of categories and a corresponding list of durations
        u_cats = [item['category'] for item in summary_data]
        u_dur = [item['total_duration'] for item in summary_data]
        return u_cats, u_dur
    except requests.RequestException as e:
        print(f"Could not connect to server for summary: {e}. Falling back to local data.")
        all_local_data = _fetch_local_data_grouped_by_day()
        day_data = all_local_data.get(date_str)
        if day_data is None or day_data.empty:
            return [], []
        
        # Manually calculate summary from local data
        summary = day_data.groupby('category')['duration'].sum().reset_index()
        u_cats = summary['category'].tolist()
        u_dur = summary['duration'].tolist()
        return u_cats, u_dur

def _fetch_local_data_grouped_by_day():
    """
    Fetches all activity data from the local SQLite database and groups by day
    according to the configured TIMEZONE.
    """
    if not os.path.exists(DB_FILE):
        return {}
        
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT timestamp, category, duration, window_title as title FROM activity"
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if df.empty:
        return {}

    # Convert UNIX timestamp to timezone-aware datetime objects
    from config import TIMEZONE
    import pytz
    tz = pytz.timezone(TIMEZONE)
    df['time'] = df['timestamp'].apply(lambda ts: datetime.datetime.fromtimestamp(ts, tz))
    # Determine the day based on the localized time
    df['day'] = df['time'].dt.strftime('%Y-%m-%d')

    grouped = df.groupby('day')
    return {name: group.drop(['day', 'time'], axis=1) for name, group in grouped}