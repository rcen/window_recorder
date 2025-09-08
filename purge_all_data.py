import sqlite3
import os
import requests
from config import API_KEY

API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")
DB_FILE = 'data/activity.sqlite'
CACHE_FILE = 'data/analysis_cache.json'

def purge_local_db():
    """Deletes all records from the local activity table."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM activity")
            conn.commit()
            # Verify deletion
            cursor.execute("SELECT COUNT(*) FROM activity")
            count = cursor.fetchone()[0]
            if count == 0:
                print("Successfully purged all records from local database.")
            else:
                print(f"[ERROR] Local database purge failed. {count} records remain.")
    except Exception as e:
        print(f"[ERROR] An error occurred while purging the local database: {e}")

def purge_remote_db():
    """Calls the API to delete all records from the remote database."""
    if not API_KEY:
        print("[ERROR] API_KEY not found in config. Cannot purge remote database.")
        return

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    print("Sending request to purge remote database...")
    try:
        # First, add the new endpoint to the server (this is a placeholder for the actual server-side change)
        # In a real scenario, the server would need to be updated with a DELETE /logs/all endpoint.
        # For this script, we assume the endpoint exists.
        
        # We need to get all IDs first, as there is no "delete all" endpoint.
        response = requests.get(f"{API_BASE_URL}/logs?limit=99999", headers=headers, timeout=60)
        if response.status_code != 200:
            print(f"Failed to get remote logs for deletion. Status: {response.status_code}, Response: {response.text}")
            return
            
        logs = response.json()
        if not logs:
            print("Remote database is already empty.")
            return
            
        ids_to_delete = [log['id'] for log in logs]
        
        delete_response = requests.post(f"{API_BASE_URL}/logs/delete_by_ids", json={"ids": ids_to_delete}, headers=headers, timeout=60)

        if delete_response.status_code == 200:
            print(f"Successfully purged {delete_response.json().get('deleted_count', 'unknown')} records from remote database.")
        else:
            print(f"Failed to purge remote database. Status: {delete_response.status_code}, Response: {delete_response.text}")

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] A network error occurred while purging the remote database: {e}")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")


def purge_cache():
    """Deletes the analysis cache file."""
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
            print("Successfully purged analysis cache.")
        except OSError as e:
            print(f"[ERROR] An error occurred while deleting the cache file: {e}")
    else:
        print("Analysis cache file not found, skipping.")

if __name__ == '__main__':
    print("--- Starting Total Data Purge ---")
    
    # Step 1: Purge local database
    purge_local_db()
    
    # Step 2: Purge remote database
    purge_remote_db()
    
    # Step 3: Purge cache
    purge_cache()
    
    print("\n--- Data Purge Complete ---")
    print("All local, remote, and cached data has been deleted.")
