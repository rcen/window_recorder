import database

def main():
    """
    This script orchestrates the synchronization between the local and remote databases.
    """
    # First, push any unsynced local data to the remote server.
    print("--- Step 1: Syncing local data to remote ---")
    database.sync_local_data()
    print("--- Finished local to remote sync ---")

    # Second, pull all remote data down to the local database to get a unified view.
    print("--- Step 2: Syncing remote data to local ---")
    database.sync_remote_to_local()
    print("--- Finished remote to local sync ---")

if __name__ == "__main__":
    main()
