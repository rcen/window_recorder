import sqlite3
import os

DB_FILE = 'data/activity.sqlite'

def check_schema():
    print("Starting schema check...")
    if not os.path.exists(DB_FILE):
        print(f"Database file {DB_FILE} not found.")
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            print("Tables found:", [t[0] for t in tables])
            
            if ('streak_notes',) in tables:
                print("streak_notes table exists.")
                cursor.execute("PRAGMA table_info(streak_notes)")
                columns = cursor.fetchall()
                print("Columns:", columns)
            else:
                print("streak_notes table MISSING!")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_schema()
