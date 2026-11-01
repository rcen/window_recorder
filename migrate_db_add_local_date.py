import sqlite3
import datetime
import pytz
import os
from config import TIMEZONE

DB_FILE = 'data/activity.sqlite'

def migrate_database_add_local_date():
    """
    Adds a 'local_date' column to the activity table and populates it
    by converting the UTC timestamp to the user's local date.
    """
    if not os.path.exists(DB_FILE):
        print(f"Database file not found at: {DB_FILE}")
        return

    try:
        tz = pytz.timezone(TIMEZONE)
    except pytz.UnknownTimeZoneError:
        print(f"Error: Unknown timezone '{TIMEZONE}' in config.dat.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Step 1: Add the 'local_date' column if it doesn't exist
    try:
        cursor.execute('ALTER TABLE activity ADD COLUMN local_date TEXT')
        print("Added 'local_date' column to the database.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("'local_date' column already exists.")
        else:
            raise

    # Step 2: Fetch all records that need migrating (where local_date is NULL)
    cursor.execute('SELECT id, timestamp FROM activity WHERE local_date IS NULL')
    records_to_migrate = cursor.fetchall()

    if not records_to_migrate:
        print("No records need to be migrated. Database is up-to-date.")
        conn.close()
        return

    print(f"Found {len(records_to_migrate)} records to migrate...")

    # Step 3: Iterate and update each record
    for record_id, timestamp in records_to_migrate:
        utc_dt = pytz.utc.localize(datetime.datetime.utcfromtimestamp(timestamp))
        local_dt = utc_dt.astimezone(tz)
        local_date_str = local_dt.strftime('%Y-%m-%d')
        
        cursor.execute('UPDATE activity SET local_date = ? WHERE id = ?', (local_date_str, record_id))

    conn.commit()
    conn.close()

    print(f"Successfully migrated {len(records_to_migrate)} records.")

if __name__ == '__main__':
    migrate_database_add_local_date()
