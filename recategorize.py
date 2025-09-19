import sqlite3
import time
from datetime import datetime, timedelta
from analytics import Analytics

DB_FILE = 'data/activity.sqlite'

def recategorize_past_week():
    """
    Recategorizes all activities from the past week based on the current
    rules in config.dat.
    """
    print("Starting recategorization of the last 7 days...")
    
    # Use the Analytics class to get the current categorization logic
    try:
        analytic = Analytics()
        print("Successfully loaded categorization rules from config.dat.")
    except Exception as e:
        print(f"Error: Could not load analytics configuration. {e}")
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            # Calculate the timestamp for 7 days ago
            seven_days_ago = time.time() - timedelta(days=7).total_seconds()

            # Get all activities from the last 7 days
            cursor.execute(
                "SELECT id, window_title, category FROM activity WHERE timestamp >= ?",
                (seven_days_ago,)
            )
            activities = cursor.fetchall()
            
            if not activities:
                print("No activities found in the last 7 days to recategorize.")
                return

            print(f"Found {len(activities)} activities to check from the past week.")
            
            update_count = 0
            updates = []

            for activity_id, window_title, old_category in activities:
                # Get the new category based on current rules
                new_category = analytic.get_cat(window_title)
                
                # If the category has changed, stage it for update
                if new_category != old_category:
                    updates.append((new_category, activity_id))
                    update_count += 1
            
            if not updates:
                print("All categories are already up-to-date.")
                return

            # Perform all database updates in one transaction
            print(f"Found {update_count} activities that need recategorization. Updating now...")
            cursor.executemany("UPDATE activity SET category = ? WHERE id = ?", updates)
            conn.commit()
            
            print(f"Successfully updated {cursor.rowcount} activities.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    recategorize_past_week()
