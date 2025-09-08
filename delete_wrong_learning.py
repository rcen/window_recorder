import sqlite3

DB_FILE = 'data/activity.sqlite'
DATES = ['2025-08-20', '2025-08-21']
WINDOW_TITLE = 'desktop'
CATEGORY = 'learning'

def delete_wrong_learning():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        for date_str in DATES:
            cursor.execute("DELETE FROM activity WHERE local_date = ? AND window_title = ? AND category = ?", (date_str, WINDOW_TITLE, CATEGORY))
        conn.commit()
        print(f"Deleted all 'desktop' as 'learning' records for {DATES} from the database.")

if __name__ == '__main__':
    delete_wrong_learning()
