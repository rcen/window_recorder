import sqlite3

DB_FILE = 'data/activity.sqlite'
FUTURE_DATE = '2025-09-07'

def delete_future():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM activity WHERE local_date = ?", (FUTURE_DATE,))
        conn.commit()
        print(f"Deleted all records for {FUTURE_DATE} from the database.")

if __name__ == '__main__':
    delete_future()
