import requests
import json
import time

def test_save_note():
    url = 'http://127.0.0.1:8042/streak/note'
    payload = {
        'note': 'Test note from debug script',
        'streak_start': time.time()
    }
    
    try:
        print(f"Sending POST request to {url}...")
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code == 200:
            print("Success!")
        else:
            print("Failed!")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_save_note()
