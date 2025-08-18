import sqlite3
import os
import pandas as pd
import requests
import datetime
import time
import pytz
from config import TIMEZONE, API_KEY

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
        if 'source' not in columns:
            cursor.execute('ALTER TABLE activity ADD COLUMN source TEXT')

def _insert_local_activity(timestamp, category, duration, window_title, source='unknown', synced=False):
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
                INSERT INTO activity (timestamp, category, duration, window_title, synced, local_date, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (timestamp, category, duration, window_title, 1 if synced else 0, local_date_str, source))
        else:
            # Fallback for before the migration is run
            cursor.execute('''
                INSERT INTO activity (timestamp, category, duration, window_title, synced, source)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (timestamp, category, duration, window_title, 1 if synced else 0, source))

# --- API Communication Functions ---

def wait_for_server(max_retries=5, delay=10):
    """
    Waits for the remote server to be available by making a simple request.
    Retries a few times before giving up.
    """
    if not API_KEY:
        print("API key not configured. Skipping server check.")
        return True

    print("Checking remote server availability...")
    headers = get_headers()
    for i in range(max_retries):
        try:
            # Using a small timeout and a lightweight query to check for server availability.
            requests.get(f"{API_BASE_URL}/logs?limit=1", headers=headers, timeout=5)
            print("Remote server is available.")
            return True
        except requests.RequestException:
            print(f"Could not connect to remote server. Attempt {i+1}/{max_retries}. Retrying in {delay}s...")
            time.sleep(delay)
    
    print("Could not connect to remote server after several retries.")
    return False

def get_headers():
    """Returns the authorization headers for API requests."""
    if not API_KEY:
        return {}
    return {"Authorization": f"Bearer {API_KEY}"}

def insert_activity(timestamp, category, duration, window_title, source):
    """
    Inserts an activity record. It first tries to send it to the remote API.
    If that fails, it saves the record locally.
    """
    if not API_KEY:
        print("API key not configured. Saving locally.")
        _insert_local_activity(timestamp, category, duration, window_title, source, synced=False)
        return False

    payload = {"timestamp": timestamp, "category": category, "duration": duration, "window_title": window_title, "source": source}
    headers = get_headers()
    
    try:
        response = requests.post(f"{API_BASE_URL}/log", json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            _insert_local_activity(timestamp, category, duration, window_title, source, synced=True)
            return True
        else:
            print(f"API Error: {response.status_code}. Saving locally.")
            _insert_local_activity(timestamp, category, duration, window_title, source, synced=False)
            return False
    except requests.RequestException:
        print("Network Error. Saving locally.")
        _insert_local_activity(timestamp, category, duration, window_title, source, synced=False)
        return False

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
            query = "SELECT timestamp, category, duration, window_title, source FROM activity WHERE local_date = ? ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn, params=(date_str,))
            return df
    except Exception as e:
        print(f"Error fetching detailed log for day {date_str} from local DB: {e}")
        return pd.DataFrame()

def sync_local_data():
    """
    Synchronizes unsynced local data with the remote server.
    """
    if not API_KEY:
        print("API key not configured. Skipping sync.")
        return

    unsynced_data = _get_unsynced_local_data()
    if not unsynced_data:
        print("No local data to sync.")
        return

    print(f"Found {len(unsynced_data)} unsynced records. Syncing...")
    
    headers = get_headers()
    successful_ids = []
    for record in unsynced_data:
        record_id, timestamp, category, duration, window_title, source = record[:6]
        payload = {"timestamp": timestamp, "category": category, "duration": duration, "window_title": window_title, "source": source}
        
        try:
            response = requests.post(f"{API_BASE_URL}/log", json=payload, headers=headers, timeout=5)
            if response.status_code == 200:
                successful_ids.append(record_id)
            else:
                print(f"API Error for record {record_id}: {response.status_code}. Will retry later.")
        except requests.RequestException as e:
            print(f"Network Error for record {record_id}: {e}. Will retry later.")
            # Stop trying to sync on network error to avoid repeated failures
            break
    
    if successful_ids:
        _mark_as_synced(successful_ids)
        print(f"Successfully synced {len(successful_ids)} records.")

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
    print("Starting sync from remote server to local database...")
    
    # 1. Fetch all data from the remote server
    try:
        response = requests.get(f"{API_BASE_URL}/logs?limit=20000", headers=get_headers(), timeout=30)
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

    # 2. Get existing local timestamps to avoid duplicates
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, window_title, source FROM activity")
            local_records = set(cursor.fetchall())
    except Exception as e:
        print(f"Error reading from local database: {e}")
        return

    # 3. Insert new records
    new_records_to_insert = []
    for record in remote_data:
        # Check for existence based on a tuple of timestamp, title, and source
        source = record.get('source', 'unknown') # Handle records from before source was added
        if (record['timestamp'], record['window_title'], source) not in local_records:
            new_records_to_insert.append(record)

    if not new_records_to_insert:
        print("Local database is already up-to-date.")
        return

    print(f"Found {len(new_records_to_insert)} new records to insert locally.")
    
    # 4. Use the existing local insert function
    for record in new_records_to_insert:
        # The remote data is considered "synced" by definition.
        # Convert ISO 8601 timestamp string from server to a Unix timestamp float
        utc_dt = datetime.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
        timestamp_float = utc_dt.timestamp()

        _insert_local_activity(
            timestamp_float,
            record['category'],
            record['duration'],
            record['window_title'],
            source=record.get('source', 'unknown'),
            synced=True 
        )
    
    print("Successfully synced remote data to local database.")
