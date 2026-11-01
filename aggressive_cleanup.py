import database
import sqlite3
import pandas as pd
import requests
import os
import datetime
import pytz
from config import TIMEZONE, API_KEY

# --- Configuration ---
MAX_DAILY_SECONDS = 86400  # 24 hours
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'
CACHE_FILE = 'data/analysis_cache.json'

def find_and_delete_remote_corrupt_days():
    """
    Fetches all data from the remote server, identifies days with >24 hours of activity,
    and deletes all records from those corrupt days.
    """
    print("--- Starting Aggressive Remote Cleanup ---")
    
    # 1. Fetch all data
    print("Fetching all records from remote server...")
    try:
        headers = database.get_headers()
        response = requests.get(f"{API_BASE_URL}/logs?limit=30000", headers=headers, timeout=60)
        response.raise_for_status()
        remote_data = response.json()
        if not remote_data:
            print("No remote data found. Skipping.")
            return
        print(f"Fetched {len(remote_data)} records.")
    except requests.RequestException as e:
        print(f"ERROR: Could not fetch data from remote server. {e}")
        return

    # 2. Process data to find corrupt days
    df = pd.DataFrame(remote_data)
    tz = pytz.timezone(TIMEZONE)
    
    # Convert timestamp string to datetime object, then to local time to get the correct date
    df['timestamp_dt'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC')
    df['local_date'] = df['timestamp_dt'].dt.tz_convert(tz).dt.strftime('%Y-%m-%d')
    
    daily_totals = df.groupby('local_date')['duration'].sum()
    corrupt_dates = daily_totals[daily_totals > MAX_DAILY_SECONDS].index.tolist()

    if not corrupt_dates:
        print("No corrupt days found on the remote server.")
        return

    print(f"Found {len(corrupt_dates)} remote days with >24 hours of activity: {corrupt_dates}")

    # 3. Get IDs of all records from the corrupt days
    ids_to_delete = df[df['local_date'].isin(corrupt_dates)]['id'].tolist()
    
    if not ids_to_delete:
        print("Could not find record IDs for corrupt dates. Aborting remote delete.")
        return
        
    print(f"Preparing to delete {len(ids_to_delete)} remote records from corrupt days...")

    # 4. Delete the records
    success = database.delete_remote_activities_by_ids(ids_to_delete)
    if not success:
        print("ERROR: Failed to delete corrupt records from remote server.")
    else:
        print("Successfully sent request to delete corrupt remote records.")


def find_and_delete_local_corrupt_days():
    """
    Finds and deletes all data from days with >24 hours of activity in the local database.
    """
    print("\n--- Starting Aggressive Local Cleanup ---")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            df = pd.read_sql_query("SELECT local_date, duration FROM activity WHERE local_date IS NOT NULL", conn)
            if df.empty:
                print("No local data to analyze.")
                return

            daily_totals = df.groupby('local_date')['duration'].sum()
            corrupt_dates = daily_totals[daily_totals > MAX_DAILY_SECONDS].index.tolist()

            if not corrupt_dates:
                print("No corrupt days found in the local database.")
                return

            print(f"Found {len(corrupt_dates)} local days with >24 hours of activity: {corrupt_dates}")
            
            cursor = conn.cursor()
            # Using parameter substitution for security
            placeholders = ','.join('?' for date in corrupt_dates)
            sql = f"DELETE FROM activity WHERE local_date IN ({placeholders})"
            
            cursor.execute(sql, corrupt_dates)
            conn.commit()
            
            print(f"Successfully deleted {cursor.rowcount} local records from corrupt days.")

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
        find_and_delete_remote_corrupt_days()
        find_and_delete_local_corrupt_days()
        clear_cache()
        print("\nAggressive cleanup complete. Run analytics to see the final state.")
