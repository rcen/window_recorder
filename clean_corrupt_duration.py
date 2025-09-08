import database
import requests
import sqlite3
import os

# Configuration
IMPOSSIBLE_DURATION = 7200  # 2 hours in seconds
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'
CACHE_FILE = 'data/analysis_cache.json'

def clean_remote_db():
    """
    Fetches all records from the remote server, identifies corrupt ones,
    and deletes them using their IDs.
    """
    print("--- Cleaning remote database ---")
    
    # 1. Fetch all data from the remote server
    print("Fetching all records from remote server...")
    try:
        headers = database.get_headers()
        response = requests.get(f"{API_BASE_URL}/logs?limit=30000", headers=headers, timeout=60)
        response.raise_for_status()
        remote_data = response.json()
        print(f"Fetched {len(remote_data)} records.")
    except requests.RequestException as e:
        print(f"ERROR: Could not fetch data from remote server. {e}")
        return

    # 2. Identify corrupt records by their duration
    remote_ids_to_delete = []
    for record in remote_data:
        if record.get('duration', 0) > IMPOSSIBLE_DURATION:
            remote_ids_to_delete.append(record['id'])
    
    if not remote_ids_to_delete:
        print("No corrupt records found on the remote server.")
        return

    print(f"Found {len(remote_ids_to_delete)} remote records with duration > {IMPOSSIBLE_DURATION / 3600} hours.")
    
    # 3. Delete the corrupt records from the remote server
    success = database.delete_remote_activities_by_ids(remote_ids_to_delete)
    if not success:
        print("ERROR: Failed to delete corrupt records from remote server.")
    else:
        print("Successfully sent request to delete remote records.")


def clean_local_db():
    """
    Finds and deletes records with impossibly long durations from the local database.
    """
    print("\n--- Cleaning local database ---")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # First, count how many records will be deleted
            cursor.execute("SELECT COUNT(*) FROM activity WHERE duration > ?", (IMPOSSIBLE_DURATION,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"No local records with duration > {IMPOSSIBLE_DURATION / 3600} hours found. Nothing to delete.")
                return

            print(f"Found {count} local records with impossibly long durations. Deleting them now...")
            
            # Execute the delete operation
            cursor.execute("DELETE FROM activity WHERE duration > ?", (IMPOSSIBLE_DURATION,))
            conn.commit()
            
            print(f"Successfully deleted {cursor.rowcount} records from the local database.")

    except sqlite3.Error as e:
        print(f"An error occurred during local cleanup: {e}")

def clear_cache():
    """Clears the analysis cache file."""
    print("\n--- Clearing local cache ---")
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
            print("Local analysis cache cleared.")
        else:
            print("No local cache file to clear.")
    except Exception as e:
        print(f"Could not clear cache: {e}")


if __name__ == '__main__':
    # IMPORTANT: Assumes the remote server has been restarted with the latest api_server.py
    if not database.wait_for_server(max_retries=3, delay=5):
        print("\nAborting cleanup: Remote server is not available.")
    else:
        clean_remote_db()
        clean_local_db()
        clear_cache()
        print("\nCleanup complete. Please run analytics again to see the corrected data.")
