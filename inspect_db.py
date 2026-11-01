import sqlite3
import pandas as pd
import datetime

DB_FILE = 'data/activity.sqlite'

def inspect_unsynced_data():
    """
    Connects to the local database and prints the timestamps of unsynced records
    in a human-readable format.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            print("Reading unsynced records from the local database...")
            query = "SELECT id, timestamp, category, duration, window_title, source FROM activity WHERE synced = 0"
            df = pd.read_sql_query(query, conn)
            
            if df.empty:
                print("No unsynced records found.")
                return

            print(f"Found {len(df)} unsynced records. Here are the first 20 records with converted timestamps:")
            
            # Convert timestamps to datetime objects
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Print the relevant columns, ensuring the datetime is fully visible
            with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 1000):
                print(df[['id', 'datetime', 'category', 'duration', 'window_title', 'source']].head(20))

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    inspect_unsynced_data()
