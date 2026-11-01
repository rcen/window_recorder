import database
import sqlite3
import pandas as pd
import requests
import os
import datetime
import pytz
import json
from config import TIMEZONE, API_KEY

# --- Configuration ---
MAX_DAILY_SECONDS = 86400  # 24 hours
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'
CACHE_FILE = 'data/analysis_cache.json'
tz = pytz.timezone(TIMEZONE)
TODAY = datetime.datetime.now(tz).strftime('%Y-%m-%d')

def check_remote_db():
    """
    Analyzes the remote database for data integrity issues like impossible daily totals or future dates.
    """
    print("--- 1. Checking Remote Database ---")
    if not database.wait_for_server(max_retries=1, delay=2):
        print("[FAILURE] Remote server is not available.")
        return

    try:
        headers = database.get_headers()
        response = requests.get(f"{API_BASE_URL}/logs?limit=30000", headers=headers, timeout=60)
        response.raise_for_status()
        remote_data = response.json()
        if not remote_data:
            print("[SUCCESS] Remote database is empty and clean.")
            return
        
        df = pd.DataFrame(remote_data)
        df['timestamp_dt'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC')
        df['local_date'] = df['timestamp_dt'].dt.tz_convert(tz).dt.strftime('%Y-%m-%d')
        
        # Check for impossible daily totals
        daily_totals = df.groupby('local_date')['duration'].sum()
        corrupt_days = daily_totals[daily_totals > MAX_DAILY_SECONDS].index.tolist()
        if corrupt_days:
            print(f"[FAILURE] Found remote days with >24 hours of activity: {corrupt_days}")
        else:
            print("[SUCCESS] No remote days have impossible total durations.")

        # Check for future dates
        future_dates = df[df['local_date'] > TODAY]['local_date'].unique().tolist()
        if future_dates:
            print(f"[FAILURE] Found future-dated entries on remote server: {future_dates}")
        else:
            print("[SUCCESS] No future-dated entries found on remote server.")

    except Exception as e:
        print(f"[FAILURE] An error occurred while checking the remote database: {e}")


def check_local_db():
    """
    Analyzes the local database for data integrity issues.
    """
    print("\n--- 2. Checking Local Database ---")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            df = pd.read_sql_query("SELECT local_date, duration FROM activity WHERE local_date IS NOT NULL", conn)
            if df.empty:
                print("[SUCCESS] Local database is empty and clean.")
                return

            # Check for impossible daily totals
            daily_totals = df.groupby('local_date')['duration'].sum()
            corrupt_days = daily_totals[daily_totals > MAX_DAILY_SECONDS].index.tolist()
            if corrupt_days:
                print(f"[FAILURE] Found local days with >24 hours of activity: {corrupt_days}")
            else:
                print("[SUCCESS] No local days have impossible total durations.")

            # Check for future dates
            future_dates = df[df['local_date'] > TODAY]['local_date'].unique().tolist()
            if future_dates:
                print(f"[FAILURE] Found future-dated entries in local database: {future_dates}")
            else:
                print("[SUCCESS] No future-dated entries found in local database.")

    except Exception as e:
        print(f"[FAILURE] An error occurred while checking the local database: {e}")


def check_cache():
    """
    Checks the local analysis cache for future-dated entries.
    """
    print("\n--- 3. Checking Local Cache ---")
    if not os.path.exists(CACHE_FILE):
        print("[SUCCESS] No cache file exists.")
        return
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        future_dates = [key for key in cache_data.keys() if key.replace('.csv', '') > TODAY]
        if future_dates:
            print(f"[FAILURE] Found future-dated entries in cache: {future_dates}")
        else:
            print("[SUCCESS] No future-dated entries found in cache.")

    except Exception as e:
        print(f"[FAILURE] An error occurred while checking the cache: {e}")


if __name__ == '__main__':
    print(f"Running health check on {TODAY}...")
    check_remote_db()
    check_local_db()
    check_cache()
    print("\nHealth check complete.")
