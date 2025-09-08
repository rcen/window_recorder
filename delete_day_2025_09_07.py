import sqlite3

DB_FILE = 'data/activity.sqlite'
DATE = '2025-09-07'

def delete_day(date_str):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM activity WHERE local_date = ?", (date_str,))
        conn.commit()
        print(f"Deleted all records for {date_str} from the database.")

if __name__ == '__main__':
    delete_day(DATE)
