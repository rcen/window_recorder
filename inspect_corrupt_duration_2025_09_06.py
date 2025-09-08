import sqlite3
import pandas as pd

DB_FILE = 'data/activity.sqlite'
DATE = '2025-09-06'
# A day has 86400 seconds. Any duration longer than this is impossible for a single entry.
IMPOSSIBLE_DURATION = 86400 

def find_corrupt_entries():
    with sqlite3.connect(DB_FILE) as conn:
        query = """
            SELECT id, timestamp, category, duration, window_title
            FROM activity
            WHERE local_date = ? AND duration > ?
        """
        df = pd.read_sql_query(query, conn, params=(DATE, IMPOSSIBLE_DURATION))
        
        if df.empty:
            print(f"No single entries with impossible durations found for {DATE}.")
            # Let's check the total duration to see if it matches the user's report
            total_dur_query = "SELECT SUM(duration) FROM activity WHERE local_date = ?"
            total_duration_series = pd.read_sql_query(total_dur_query, conn, params=(DATE,))
            total_duration = total_duration_series.iloc[0,0] if not total_duration_series.empty else 0
            if total_duration is None:
                total_duration = 0
            print(f"Total recorded duration for {DATE} from database is {total_duration/3600:.2f} hours.")
            print("The issue might be an accumulation of many smaller entries or a caching issue in analytics.")

        else:
            print(f"Found the following corrupt entries for {DATE}:")
            print(df.to_string())

if __name__ == '__main__':
    find_corrupt_entries()
