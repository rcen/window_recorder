import sqlite3

DB_FILE = 'data/activity.sqlite'
DATE_TO_DELETE = '2025-09-06'

def delete_day_data():
    """
    Deletes all records for a specific date from the activity table.
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # First, count how many records will be deleted
            cursor.execute("SELECT COUNT(*) FROM activity WHERE local_date = ?", (DATE_TO_DELETE,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"No records found for date '{DATE_TO_DELETE}'. Nothing to delete.")
                return

            print(f"Found {count} records for date '{DATE_TO_DELETE}'. Deleting them now...")
            
            # Execute the delete operation
            cursor.execute("DELETE FROM activity WHERE local_date = ?", (DATE_TO_DELETE,))
            conn.commit()
            
            # Get the number of rows affected
            rows_deleted = cursor.rowcount
            print(f"Successfully deleted {rows_deleted} records for {DATE_TO_DELETE} from the local database.")

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    delete_day_data()
