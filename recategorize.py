import sqlite3
import time
from datetime import datetime, timedelta
from analytics import Analytics
import argparse
import sys

DB_FILE = 'data/activity.sqlite'

def list_activities_by_category(category):
    """
    Lists activities of a given category for today only, from recent to old.
    """
    print(f"Listing today's activities for category: '{category}'")
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Calculate timestamp for start of today (midnight)
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_timestamp = today.timestamp()
            
            # Check if window_url column exists
            cursor.execute("PRAGMA table_info(activity)")
            columns = [row[1] for row in cursor.fetchall()]
            has_window_url = 'window_url' in columns
            
            if has_window_url:
                cursor.execute(
                    "SELECT window_title, category, timestamp, window_url FROM activity WHERE category = ? AND timestamp >= ? ORDER BY timestamp DESC",
                    (category, today_timestamp)
                )
            else:
                cursor.execute(
                    "SELECT window_title, category, timestamp, NULL FROM activity WHERE category = ? AND timestamp >= ? ORDER BY timestamp DESC",
                    (category, today_timestamp)
                )
            activities = cursor.fetchall()

            if not activities:
                print(f"No activities found for category '{category}' today.")
                return

            print(f"Found {len(activities)} activities today:")
            for row in activities:
                title, cat, ts = row[0], row[1], row[2]
                url = row[3] if len(row) > 3 and row[3] else None
                
                dt_object = datetime.fromtimestamp(ts)
                line = f"  - {dt_object.strftime('%Y-%m-%d %H:%M:%S')}: [{cat}] {title}"
                if url:
                    line += f"\n    URL: {url}"
                # Encode to stdout's encoding, replacing characters that can't be handled
                print(line.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding))

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


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
            cursor.execute("PRAGMA table_info(activity)")
            columns = [row[1] for row in cursor.fetchall()]
            has_window_url = 'window_url' in columns

            if has_window_url:
                cursor.execute(
                    "SELECT id, window_title, window_url, category FROM activity WHERE timestamp >= ?",
                    (seven_days_ago,)
                )
            else:
                cursor.execute(
                    "SELECT id, window_title, NULL as window_url, category FROM activity WHERE timestamp >= ?",
                    (seven_days_ago,)
                )
            activities = cursor.fetchall()
            
            if not activities:
                print("No activities found in the last 7 days to recategorize.")
                return

            print(f"Found {len(activities)} activities to check from the past week.")
            
            update_count = 0
            updates = []

            for activity in activities:
                if has_window_url:
                    activity_id, window_title, window_url, old_category = activity
                else:
                    activity_id, window_title, window_url, old_category = activity
                # Get the new category based on current rules
                new_category = analytic.get_cat(window_title, window_url)
                
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
    parser = argparse.ArgumentParser(description="Recategorize activities or list them by category.")
    parser.add_argument('--category', type=str, help='Category of activities to list.')
    args = parser.parse_args()

    if args.category:
        list_activities_by_category(args.category)
    else:
        recategorize_past_week()
