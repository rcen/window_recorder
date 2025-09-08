import sqlite3
import pandas as pd

DB_FILE = 'data/activity.sqlite'
DATE = '2025-09-06'
OUTPUT_FILE = 'debug_day_2025_09_06.txt'

def dump_day_details():
    with sqlite3.connect(DB_FILE) as conn:
        query = "SELECT * FROM activity WHERE local_date = ?"
        df = pd.read_sql_query(query, conn, params=(DATE,))
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"Detailed activity log for {DATE}\n\n")
            f.write(df.to_string())
    
    print(f"Activity log for {DATE} has been saved to {OUTPUT_FILE}")
    print(f"\nSummary of durations (in hours) by category for {DATE}:")
    # Show total hours per category to quickly find the offender
    category_summary = df.groupby('category')['duration'].sum() / 3600
    print(category_summary.to_string())

    print(f"\nSummary of durations (in hours) by source for {DATE}:")
    source_summary = df.groupby('source')['duration'].sum() / 3600
    print(source_summary.to_string())


if __name__ == '__main__':
    dump_day_details()
