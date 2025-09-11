# delete_activity.py
import database
import datetime

def display_activities(offset=0, limit=20):
    """Displays a paginated list of recent activities."""
    print("\n--- Most Recent Activities ---")
    
    recent_activities = database.fetch_recent_activities(limit=limit, offset=offset)
    
    if not recent_activities:
        print("No more activities found.")
        return False

    for activity in recent_activities:
        activity_id, timestamp, title, duration, category = activity
        dt_object = datetime.datetime.fromtimestamp(timestamp)
        time_str = dt_object.strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"  ID: {activity_id:<5} | {time_str} | {category:<15} | {duration:<5}s | {title[:80]}")

    print("------------------------------")
    return True

def main():
    """
    Continuously lists recent activities and prompts the user to delete one by ID
    or view the next page.
    """
    offset = 0
    limit = 20
    
    while True:
        if not display_activities(offset=offset, limit=limit):
            break
            
        prompt = (
            "Enter an ID to delete, "
            "'n' for next page, "
            "or 'q' to quit: "
        )
        user_input = input(prompt).strip().lower()
        
        if user_input == 'q':
            print("Exiting.")
            break
        elif user_input == 'n':
            offset += limit
            continue
        elif user_input.isdigit():
            activity_id = int(user_input)
            confirm = input(f"Are you sure you want to delete activity with ID {activity_id}? (y/n): ").lower()
            
            if confirm == 'y':
                if database.delete_activity(activity_id):
                    print(f"Successfully deleted activity with ID {activity_id}.")
                    # After deletion, we should refresh the current page
                else:
                    print(f"Could not find or delete activity with ID {activity_id}.")
            else:
                print("Deletion cancelled.")
        else:
            print("Invalid input.")

if __name__ == '__main__':
    main()