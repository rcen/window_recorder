
import sqlite3
import os
import pandas as pd
import requests
import datetime
import time

# --- Configuration ---
# This will be replaced with your actual Render API URL during deployment
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "http://127.0.0.1:8000")
DB_FILE = 'data/activity.sqlite'

# --- Global Cache ---
# Cache to hold the data fetched from the server to avoid repeated API calls.
# The key is the date of the fetch, the value is the grouped data.
data_cache = {
    "timestamp": None,
    "data": None
}
CACHE_DURATION_SECONDS = 300 # 5 minutes

# --- Local Database Functions ---

def initialize_database():
    """Initializes the local database and creates the activity table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            category TEXT NOT NULL,
            duration INTEGER NOT NULL,
            window_title TEXT NOT NULL,
            synced INTEGER DEFAULT 0
        )
    ''')
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
            print("Activity logged to server.")
            return True
        else:
            print(f"API Error: {response.status_code}. Saving locally.")
            _insert_local_activity(timestamp, category, duration, window_title, synced=False)
            return False
    except requests.RequestException:
        print(f"Network Error. Saving locally.")
        _insert_local_activity(timestamp, category, duration, window_title, synced=False)
        return False

def fetch_all_data_grouped_by_day():
    """
    Fetches all activity data from the API server with caching.
    If the server is unavailable, falls back to the local database.
    """
    global data_cache
    # Check cache first
    if data_cache["timestamp"] and (time.time() - data_cache["timestamp"] < CACHE_DURATION_SECONDS):
        print("Returning cached data.")
        return data_cache["data"]

    print("Attempting to fetch data from server...")
    try:
        # High limit to fetch all data. In a larger application, pagination would be needed.
        response = requests.get(f"{API_BASE_URL}/logs?limit=20000", timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"Successfully fetched {len(data)} records from server.")

        if not data:
            return {}

        df = pd.DataFrame(data)
        df['time'] = pd.to_datetime(df['timestamp']).apply(lambda x: x.timestamp())
        df['day'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d')
        df.rename(columns={'window_title': 'title'}, inplace=True)
        df.drop(['timestamp', 'id'], axis=1, inplace=True)

        grouped = df.groupby('day')
        result = {name: group.drop('day', axis=1) for name, group in grouped}
        
        # Update cache
        data_cache["timestamp"] = time.time()
        data_cache["data"] = result
        
        return result

    except requests.RequestException as e:
        print(f"Could not connect to server: {e}. Falling back to local data.")
        return _fetch_local_data_grouped_by_day()

def fetch_data_for_day(date_str):
    """
    Fetches activity data for a specific day.
    It uses the main data fetching function and filters for the requested day.
    """
    all_data = fetch_all_data_grouped_by_day()
    return all_data.get(date_str, pd.DataFrame())


def _fetch_local_data_grouped_by_day():
    """
    Fetches all activity data from the local SQLite database.
    """
    if not os.path.exists(DB_FILE):
        return {}
        
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT strftime('%Y-%m-%d', timestamp, 'unixepoch', 'localtime') as day,
               timestamp as time,
               category,
               duration,
               window_title as title
        FROM activity
        ORDER BY day
    """
    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if df.empty:
        return {}

    grouped = df.groupby('day')
    return {name: group.drop('day', axis=1) for name, group in grouped}

# TODO: Implement a sync function to send unsynced local data to the server.
