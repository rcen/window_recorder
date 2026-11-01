
import requests
import pandas as pd
import os

# Fetch the API URL from the same environment variable as the main app
API_BASE_URL = os.environ.get("WINDOW_RECORDER_API_URL", "https://window-recorder-api.onrender.com")

def show_remote_database_content():
    """
    Connects to the remote API, fetches all activity logs,
    and prints them in a readable format.
    """
    api_url = f"{API_BASE_URL}/logs?limit=20000" # Fetch a large number of records
    print(f"Attempting to fetch all data from: {api_url}")

    try:
        # Increased timeout to handle potential "cold starts" on the server
        response = requests.get(api_url, timeout=30)
        
        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()
        
        data = response.json()

        if not data:
            print("The remote database contains no records.")
            return

        print(f"Successfully fetched {len(data)} records from the server.")
        
        df = pd.DataFrame(data)
        
        # Ensure all columns are displayed
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        
        print("\n--- Full Content of Remote Database ---")
        print(df)
        print("---------------------------------------")

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while trying to connect to the server: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    show_remote_database_content()
