import sqlite3
import os
import pandas as pd
import requests
import datetime
import time
import pytz
from config import TIMEZONE

# --- Configuration ---
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'

# --- Local Database Functions ---

def initialize_database():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                category TEXT NOT NULL,
                duration INTEGER NOT NULL,
                window_title TEXT NOT NULL
            )
        ''')
        cursor.execute("PRAGMA table_info(activity)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'synced' not in columns:
            cursor.execute('ALTER TABLE activity ADD COLUMN synced INTEGER DEFAULT 0')

def _insert_local_activity(timestamp, category, duration, window_title, synced=False):
    """Inserts a single activity record into the local database, including the local_date."""
    tz = pytz.timezone(TIMEZONE)
    utc_dt = pytz.utc.localize(datetime.datetime.utcfromtimestamp(timestamp))
    local_dt = utc_dt.astimezone(tz)
    local_date_str = local_dt.strftime('%Y-%m-%d')

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # We need to handle the case where the migration hasn't been run yet
        cursor.execute("PRAGMA table_info(activity)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'local_date' in columns:
            cursor.execute('''
                INSERT INTO activity (timestamp, category, duration, window_title, synced, local_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (timestamp, category, duration, window_title, 1 if synced else 0, local_date_str))
        else:
            # Fallback for before the migration is run
            cursor.execute('''
                INSERT INTO activity (timestamp, category, duration, window_title, synced)
                VALUES (?, ?, ?, ?, ?)
            ''', (timestamp, category, duration, window_title, 1 if synced else 0))

# --- API Communication Functions ---

def insert_activity(timestamp, category, duration, window_title):
    payload = {"timestamp": timestamp, "category": category, "duration": duration, "window_title": window_title}
    try:
        response = requests.post(f"{API_BASE_URL}/log", json=payload, timeout=5)
        if response.status_code == 200:
            _insert_local_activity(timestamp, category, duration, window_title, synced=True)
            return True
        else:
            print(f"API Error: {response.status_code}. Saving locally.")
            _insert_local_activity(timestamp, category, duration, window_title, synced=False)
            return False
    except requests.RequestException:
        print("Network Error. Saving locally.")
        _insert_local_activity(timestamp, category, duration, window_title, synced=False)
        return False

def fetch_available_days():
    """
    Fetches a list of unique days directly from the local_date column.
    """
    print("--> Getting available days from the CORRECT local_date column.")
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

def fetch_summary_for_day(date_str):
    """
    Fetches a summary for a specific day directly from the local_date column.
    """
    print(f"--> Getting summary for {date_str} from the CORRECT local_date column.")
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