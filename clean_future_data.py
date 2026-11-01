import sqlite3
import json
import os
import datetime
import pytz
from config import TIMEZONE

DB_FILE = 'data/activity.sqlite'
CACHE_PATH = 'data/analysis_cache.json'
FUTURE_DATE = '2025-09-07'

def clean_future_data():
    tz = pytz.timezone(TIMEZONE)
    today = datetime.datetime.now(tz).date()
    
    print("Cleaning future data from local database, cache...")
    
    # Clean local database
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM activity WHERE local_date = ?", (FUTURE_DATE,))
            conn.commit()
        print(f"Deleted future data from local database: {FUTURE_DATE}")
    except Exception as e:
        print(f"Error cleaning local database: {e}")
    
    # Clean cache
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                cache = json.load(f)
            key_to_remove = f"{FUTURE_DATE}.csv"
            if key_to_remove in cache:
                del cache[key_to_remove]
                with open(CACHE_PATH, 'w') as f:
                    json.dump(cache, f, indent=4)
                print(f"Deleted future data from cache: {key_to_remove}")
            else:
                print("No future data found in cache.")
        except Exception as e:
            print(f"Error cleaning cache: {e}")
    else:
        print("Cache file not found.")
    
    # For remote database, advise user
    print("For remote database, please delete future data manually via the web interface or API.")
    
    print("Future data cleanup complete.")

if __name__ == '__main__':
    clean_future_data()
