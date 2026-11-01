import database
import time

def check_server():
    """
    Checks if the remote API server is available.
    """
    print("Attempting to connect to the remote server...")
    
    # The wait_for_server function already has built-in retries and logging.
    # We can call it with a shorter retry cycle for a quick check.
    is_available = database.wait_for_server(max_retries=3, delay=5)
    
    if is_available:
        print("\n[SUCCESS] The remote server is up and responding.")
    else:
        print("\n[FAILURE] The remote server is not available. Please ensure it has been restarted with the latest code.")

if __name__ == '__main__':
    check_server()
