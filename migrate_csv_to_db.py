import os
import pandas as pd
import database
import sqlite3

def migrate_csv_to_db():
    """
    Migrates historical data from CSV files in the 'data/' directory
    to the SQLite database.
    """
    data_dir = 'data'
    db_file = database.DB_FILE

    # 1. Initialize the database to ensure the table exists
    database.initialize_database()
    print(f"Database '{db_file}' is ready.")

    # 2. Find all CSV files in the data directory
    try:
        log_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]
        if not log_files:
            print("No CSV log files found to migrate.")
            return
    except FileNotFoundError:
        print(f"Error: The '{data_dir}' directory was not found.")
        return

    print(f"Found {len(log_files)} CSV files to migrate.")

    # 3. Connect to the database
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # 4. Iterate over each CSV file and insert its data
    total_rows_migrated = 0
    for log_file in log_files:
        file_path = os.path.join(data_dir, log_file)
        try:
            # Read CSV, accepting up to 5 columns and using the first 4
            df = pd.read_csv(file_path, header=None, names=['timestamp', 'category', 'duration', 'window_title', 'extra_time'], usecols=[0, 1, 2, 3], encoding='ISO-8859-1', sep=',')

            # Drop rows with missing essential data
            df.dropna(subset=['timestamp', 'category', 'duration', 'window_title'], inplace=True)

            # Ensure data types are correct
            df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
            df['duration'] = pd.to_numeric(df['duration'], errors='coerce')
            df.dropna(subset=['timestamp', 'duration'], inplace=True)
            df['duration'] = df['duration'].astype(int)


            # Use a transaction for efficient insertion
            for index, row in df.iterrows():
                cursor.execute('''
                    INSERT INTO activity (timestamp, category, duration, window_title)
                    VALUES (?, ?, ?, ?)
                ''', (row['timestamp'], row['category'], row['duration'], str(row['window_title'])))

            conn.commit()
            print(f"Successfully migrated {len(df)} rows from {log_file}.")
            total_rows_migrated += len(df)

        except Exception as e:
            print(f"Error processing file {log_file}: {e}")
            conn.rollback() # Rollback transaction on error

    # 5. Close the connection
    conn.close()
    print(f"\nMigration complete. A total of {total_rows_migrated} records were added to the database.")
    print("You can now safely back up or remove the old .csv files if you wish.")

if __name__ == '__main__':
    migrate_csv_to_db()
