import sqlite3
import datetime

DB_FILE = 'data/activity.sqlite'
# 57:23:43 = 206,623 seconds
LONG_IDLE_THRESHOLD = 200000  # seconds, just below 57:23:43

# Delete all idle events with duration >= threshold

def delete_long_idle():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM activity WHERE category = 'idle' AND duration >= ?", (LONG_IDLE_THRESHOLD,))
        conn.commit()
        print(f"Deleted all 'idle' records with duration >= {LONG_IDLE_THRESHOLD} seconds.")

if __name__ == '__main__':
    delete_long_idle()
