import sqlite3

DB_FILE = 'data/activity.sqlite'
DATE = '2025-09-06'
WINDOW_TITLE = 'start'
CATEGORY = 'learning'

def fix_start_as_idle():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Update all 'start' as 'learning' to 'idle' for the given date
        cursor.execute("UPDATE activity SET category = 'idle' WHERE local_date = ? AND window_title = ? AND category = ?", (DATE, WINDOW_TITLE, CATEGORY))
        conn.commit()
        print(f"Updated all 'start' as 'learning' to 'idle' for {DATE}.")

if __name__ == '__main__':
    fix_start_as_idle()
