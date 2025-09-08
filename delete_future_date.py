import database
import requests
import sqlite3
import os
import datetime
import pytz
from config import TIMEZONE

# --- Configuration ---
FUTURE_DATE = '2025-09-07'
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'
CACHE_FILE = 'data/analysis_cache.json'

def clean_future_date_remote():
    """
    Finds and deletes records for a specific future date from the remote database.
    """
    print("--- Cleaning future date from remote database ---")
    
    # 1. Fetch all data from the remote server
    print("Fetching all records from remote server...")
    try:
        headers = database.get_headers()
        response = requests.get(f"{API_BASE_URL}/logs?limit=30000", headers=headers, timeout=60)
        response.raise_for_status()
        remote_data = response.json()
        print(f"Fetched {len(remote_data)} records.")
    except requests.RequestException as e:
        print(f"ERROR: Could not fetch data from remote server. {e}")
        return

    # 2. Identify future-dated records by converting their UTC timestamp to local date
    remote_ids_to_delete = []
    tz = pytz.timezone(TIMEZONE)
    for record in remote_data:
        utc_dt = datetime.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
        local_dt = utc_dt.astimezone(tz)
        local_date_str = local_dt.strftime('%Y-%m-%d')
        if local_date_str == FUTURE_DATE:
            remote_ids_to_delete.append(record['id'])
    
    if not remote_ids_to_delete:
        print(f"No records for future date {FUTURE_DATE} found on the remote server.")
        return

    print(f"Found {len(remote_ids_to_delete)} remote records for {FUTURE_DATE}. Deleting them now...")
    
    # 3. Delete the records from the remote server
    success = database.delete_remote_activities_by_ids(remote_ids_to_delete)
    if not success:
        print("ERROR: Failed to delete future-dated records from remote server.")
    else:
        print("Successfully sent request to delete future-dated remote records.")


def clean_future_date_local():
    """
    Deletes records for a specific future date from the local database.
    """
    print("\n--- Cleaning future date from local database ---")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM activity WHERE local_date = ?", (FUTURE_DATE,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"No local records for {FUTURE_DATE} found. Nothing to delete.")
                return

            print(f"Found {count} local records for {FUTURE_DATE}. Deleting them now...")
            cursor.execute("DELETE FROM activity WHERE local_date = ?", (FUTURE_DATE,))
            conn.commit()
            print(f"Successfully deleted {cursor.rowcount} records from the local database.")

    except sqlite3.Error as e:
        print(f"An error occurred during local cleanup: {e}")

def clear_cache():
    """Clears the analysis cache file."""
    print("\n--- Clearing local cache ---")
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            print("Local analysis cache cleared.")
    except Exception as e:
        print(f"Could not clear cache: {e}")


if __name__ == '__main__':
    if not database.wait_for_server(max_retries=3, delay=5):
        print("\nAborting cleanup: Remote server is not available.")
    else:
        clean_future_date_remote()
        clean_future_date_local()
        clear_cache()
        print("\nFuture date cleanup complete.")
