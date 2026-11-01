import database

TITLE_TO_DELETE = 'start'

def main():
    print("--- Deleting local 'start' events ---")
    # This part is redundant if you just ran it, but good for a standalone script
    try:
        import sqlite3
        DB_FILE = 'data/activity.sqlite'
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM activity WHERE window_title = ?", (TITLE_TO_DELETE,))
            print(f"Deleted {cursor.rowcount} local records.")
    except Exception as e:
        print(f"Could not delete local records: {e}")

    print("\n--- Deleting remote 'start' events ---")
    success = database.delete_remote_activities_by_title(TITLE_TO_DELETE)
    if success:
        print("\nRemote deletion request sent successfully.")
    else:
        print("\nFailed to send remote deletion request.")

    print("\n--- Clearing local cache ---")
    try:
        import os
        cache_file = 'data/analysis_cache.json'
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print("Local analysis cache cleared.")
        else:
            print("No local cache file to clear.")
    except Exception as e:
        print(f"Could not clear cache: {e}")


if __name__ == '__main__':
    main()
