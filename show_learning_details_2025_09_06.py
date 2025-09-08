import sqlite3
import pandas as pd

DB_FILE = 'data/activity.sqlite'
DATE = '2025-09-06'
CATEGORY = 'learning'

def main():
    with sqlite3.connect(DB_FILE) as conn:
        query = '''
            SELECT timestamp, duration, window_title
            FROM activity
            WHERE local_date = ? AND category = ?
            ORDER BY timestamp ASC
        '''
        df = pd.read_sql_query(query, conn, params=(DATE, CATEGORY))
        if df.empty:
            print(f'No entries found for {CATEGORY} on {DATE}.')
            return
        df['start_time'] = pd.to_datetime(df['timestamp'], unit='s')
        df['duration_min'] = (df['duration'] / 60).round(2)
        print(df[['start_time', 'duration_min', 'window_title']].to_string(index=False))
        print(f'\nTotal duration: {df["duration"].sum()/3600:.2f} hours')

if __name__ == '__main__':
    main()
