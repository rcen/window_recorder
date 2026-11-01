import sqlite3

DB_FILE = 'data/activity.sqlite'

def delete_unsynced_data():
    """
    Connects to the local database and deletes all records that have not been synced.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # First, count the unsynced records to see how many will be deleted
            cursor.execute("SELECT COUNT(*) FROM activity WHERE synced = 0")
            count = cursor.fetchone()[0]
            
            if count == 0:
                print("No unsynced records to delete.")
                return

            print(f"Found {count} unsynced records. Deleting them now...")
            
            # Delete the unsynced records
            cursor.execute("DELETE FROM activity WHERE synced = 0")
            conn.commit()
            
            print(f"Successfully deleted {count} unsynced records.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    delete_unsynced_data()
