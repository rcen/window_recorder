import sqlite3
import datetime
import pytz
from config import TIMEZONE

DB_FILE = 'data/activity.sqlite'

def fix_local_dates():
    tz = pytz.timezone(TIMEZONE)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp FROM activity")
        rows = cursor.fetchall()
        updates = []
        for row in rows:
            rec_id, ts = row
            utc_dt = datetime.datetime.utcfromtimestamp(ts).replace(tzinfo=pytz.utc)
            local_dt = utc_dt.astimezone(tz)
            local_date_str = local_dt.strftime('%Y-%m-%d')
            updates.append((local_date_str, rec_id))
        cursor.executemany("UPDATE activity SET local_date = ? WHERE id = ?", updates)
        conn.commit()
    print(f"Updated {len(updates)} records with correct local_date.")

if __name__ == '__main__':
    fix_local_dates()
