
import sqlite3
import pandas as pd
import os
from config import TIMEZONE

DB_FILE = 'activity.db' # Updated to match the new database name

def show_database_content():
    """
    Connects to the SQLite database, converts timestamps to the local timezone,
    and prints the entire content of the 'activities' table.
    """
    if not os.path.exists(DB_FILE):
        print(f"Database file not found at: {DB_FILE}")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        print(f"Connected to database: {DB_FILE}")

        # Use pandas to read the whole table
        # The table name is 'activities', not 'activity'
        df = pd.read_sql_query("SELECT * FROM activities", conn)

        if df.empty:
            print("The 'activities' table is empty.")
        else:
            # Convert timestamp from UTC to the configured local timezone
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
            
            print("\n--- Full Content of 'activities' Table (in local timezone) ---")
            # Use to_string() to ensure the entire DataFrame is printed
            print(df.to_string())
            print("-------------------------------------------------------------")

    except (sqlite3.Error, pd.io.sql.DatabaseError) as e:
        print(f"Database error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    show_database_content()
