import requests
import os
from config import API_KEY

# --- Configuration ---
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")

def get_headers():
    """Returns the authorization headers for API requests."""
    if not API_KEY:
        raise ValueError("API_KEY is not configured. Cannot proceed.")
    return {"Authorization": f"Bearer {API_KEY}"}

def clear_remote_database():
    """
    Sends a DELETE request to the /clear-data endpoint to wipe the remote database.
    """
    headers = get_headers()
    url = f"{API_BASE_URL}/clear-data"
    
    print(f"Sending DELETE request to {url} to clear all remote data...")
    
    try:
        response = requests.delete(url, headers=headers, timeout=30)
        
        if response.status_code == 204:
            print("Successfully cleared the remote database.")
        else:
            print(f"Error: Received status code {response.status_code}")
            try:
                print("Response content:", response.json())
            except requests.exceptions.JSONDecodeError:
                print("Response content:", response.text)
                
    except requests.RequestException as e:
        print(f"A network error occurred: {e}")

if __name__ == "__main__":
    clear_remote_database()