import sqlite3

DB_FILE = 'data/activity.sqlite'
TITLE_TO_DELETE = 'start'

def delete_start_events():
    """
    Deletes all records from the activity table where the window_title is 'start'.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # First, count how many records will be deleted
            cursor.execute("SELECT COUNT(*) FROM activity WHERE window_title = ?", (TITLE_TO_DELETE,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"No records found with window_title '{TITLE_TO_DELETE}'. Nothing to delete.")
                return

            print(f"Found {count} records with window_title '{TITLE_TO_DELETE}'. Deleting them now...")
            
            # Execute the delete operation
            cursor.execute("DELETE FROM activity WHERE window_title = ?", (TITLE_TO_DELETE,))
            conn.commit()
            
            # Get the number of rows affected
            rows_deleted = cursor.rowcount
            print(f"Successfully deleted {rows_deleted} records from the local database.")

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    delete_start_events()
