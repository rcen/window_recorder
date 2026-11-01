import sqlite3

DB_FILE = 'data/activity.sqlite'

def add_local_date_column():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Check if the column already exists
        cursor.execute("PRAGMA table_info(activity)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'local_date' not in columns:
            cursor.execute("ALTER TABLE activity ADD COLUMN local_date TEXT")
            print("local_date column added.")
        else:
            print("local_date column already exists.")

if __name__ == "__main__":
    add_local_date_column()
