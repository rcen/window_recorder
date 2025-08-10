
import sqlite3
import pandas as pd
import os

DB_FILE = 'data/activity.sqlite'

def show_database_content():
    """
    Connects to the SQLite database and prints the entire content
    of the 'activity' table.
    """
    if not os.path.exists(DB_FILE):
        print(f"Database file not found at: {DB_FILE}")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        print(f"Connected to database: {DB_FILE}")

        # Use pandas to read the whole table and print it
        df = pd.read_sql_query("SELECT * FROM activity", conn)

        if df.empty:
            print("The 'activity' table is empty.")
        else:
            print("--- Full Content of 'activity' Table ---")
            # Use to_string() to ensure the entire DataFrame is printed
            print(df.to_string())
            print("----------------------------------------")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()
            print("Database connection closed.")

if __name__ == "__main__":
    show_database_content()
