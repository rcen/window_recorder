import sqlite3
import time
import argparse
import os
from datetime import datetime

DB_FILE = 'data/activity.sqlite'

def initialize_database():
    """Creates the projects table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_name TEXT NOT NULL,
                description TEXT,
                start_time REAL NOT NULL,
                end_time REAL
            )
        ''')
        conn.commit()

def start_project(short_name, description):
    """Starts a new project session."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # First, stop any currently active project
        current_time = time.time()
        cursor.execute("UPDATE projects SET end_time = ? WHERE end_time IS NULL", (current_time,))
        
        # Start the new project
        cursor.execute(
            "INSERT INTO projects (short_name, description, start_time) VALUES (?, ?, ?)",
            (short_name, description, current_time)
        )
        conn.commit()
        print(f"Started project '{short_name}': {description}")

def stop_project():
    """Stops the currently active project session."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Find the active project
        cursor.execute("SELECT id, short_name FROM projects WHERE end_time IS NULL")
        active_project = cursor.fetchone()
        
        if active_project:
            project_id, short_name = active_project
            current_time = time.time()
            cursor.execute("UPDATE projects SET end_time = ? WHERE id = ?", (current_time, project_id))
            conn.commit()
            print(f"Stopped project '{short_name}'.")
        else:
            print("No active project to stop.")

def show_status():
    """Shows the currently active project."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT short_name, description, start_time FROM projects WHERE end_time IS NULL")
        active_project = cursor.fetchone()
        
        if active_project:
            short_name, description, start_time = active_project
            start_str = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
            
            current_time = time.time()
            duration = current_time - start_time
            mins, secs = divmod(duration, 60)
            hours, mins = divmod(mins, 60)
            duration_str = f"{int(hours):02d}h {int(mins):02d}m {int(secs):02d}s"

            print(f"Currently active project: '{short_name}'")
            print(f"  Description: {description}")
            print(f"  Started at: {start_str}")
            print(f"  Duration: {duration_str}")
        else:
            print("No project is currently active.")

def list_projects():
    """Lists all project sessions."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, short_name, description, start_time, end_time FROM projects ORDER BY start_time DESC")
        projects = cursor.fetchall()
        
        if projects:
            print(f"{'ID':<4} {'Project':<15} {'Start Time':<20} {'End Time':<20} {'Duration':<12} {'Description':<40}")
            print("-" * 111)
            for proj in projects:
                proj_id, short_name, description, start_time, end_time = proj
                start_str = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
                if end_time:
                    end_str = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
                    duration = end_time - start_time
                    mins, secs = divmod(duration, 60)
                    hours, mins = divmod(mins, 60)
                    duration_str = f"{int(hours):02d}h {int(mins):02d}m {int(secs):02d}s"
                else:
                    end_str = "(active)"
                    duration_str = ""
                
                print(f"{proj_id:<4} {short_name:<15} {start_str:<20} {end_str:<20} {duration_str:<12} {description:<40}")
        else:
            print("No projects found.")

def view_project(short_name):
    """Shows the total time and activity summary for a specific project."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get all sessions for the project
        cursor.execute("SELECT start_time, end_time, description FROM projects WHERE short_name = ? ORDER BY start_time ASC", (short_name,))
        sessions = cursor.fetchall()
        
        if not sessions:
            print(f"Project '{short_name}' not found.")
            return

        total_duration = 0
        
        print(f"Project: {short_name}")
        print("\nSessions:")
        print("-" * 80)
        print(f"{'Start Time':<20} {'End Time':<20} {'Duration':<12} {'Description':<40}")
        print("-" * 80)

        for start_time, end_time, description in sessions:
            start_str = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
            if end_time:
                end_str = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
                duration = end_time - start_time
                total_duration += duration
                mins, secs = divmod(duration, 60)
                hours, mins = divmod(mins, 60)
                duration_str = f"{int(hours):02d}h {int(mins):02d}m {int(secs):02d}s"
            else:
                end_str = "(active)"
                duration_str = ""

            print(f"{start_str:<20} {end_str:<20} {duration_str:<12} {description:<40}")
        
        print("-" * 80)
        total_mins, total_secs = divmod(total_duration, 60)
        total_hours, total_mins = divmod(total_mins, 60)
        print(f"Total time for project '{short_name}': {int(total_hours):02d}h {int(total_mins):02d}m {int(total_secs):02d}s")

        print("\nActivity Summary:")
        print("-" * 80)
        
        # Get all activities within the project's sessions
        activities = []
        for start_time, end_time, _ in sessions:
            if end_time:
                cursor.execute(
                    "SELECT category, SUM(duration) FROM activity WHERE timestamp >= ? AND timestamp < ? GROUP BY category",
                    (start_time, end_time)
                )
                activities.extend(cursor.fetchall())
        
        if activities:
            # Sum up durations for each category across all sessions
            category_totals = {}
            for category, duration in activities:
                category_totals[category] = category_totals.get(category, 0) + duration
            
            for category, duration in category_totals.items():
                mins, secs = divmod(duration, 60)
                hours, mins = divmod(mins, 60)
                duration_str = f"{int(hours):02d}h {int(mins):02d}m {int(secs):02d}s"
                print(f"  {category:<20}: {duration_str}")
        else:
            print("No activity recorded for this project yet.")

def adjust_project(project_id, new_name, new_desc, new_start_str, new_end_str, new_endtime_str):
    """Adjusts the properties of a specific project session."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if new_name:
            updates.append("short_name = ?")
            params.append(new_name)
        
        if new_desc:
            updates.append("description = ?")
            params.append(new_desc)

        if new_start_str:
            try:
                new_start_dt = datetime.strptime(new_start_str, '%Y-%m-%d %H:%M:%S')
                updates.append("start_time = ?")
                params.append(new_start_dt.timestamp())
            except ValueError:
                print("Invalid start time format. Please use YYYY-MM-DD HH:MM:SS.")
                return

        if new_end_str:
            try:
                new_end_dt = datetime.strptime(new_end_str, '%Y-%m-%d %H:%M:%S')
                updates.append("end_time = ?")
                params.append(new_end_dt.timestamp())
            except ValueError:
                print("Invalid end time format. Please use YYYY-MM-DD HH:MM:SS.")
                return
        elif new_endtime_str:
            try:
                cursor.execute("SELECT start_time FROM projects WHERE id = ?", (project_id,))
                result = cursor.fetchone()
                if not result:
                    print(f"Project ID {project_id} not found.")
                    return
                
                original_start_time = result[0]
                original_date = datetime.fromtimestamp(original_start_time).date()
                new_time = datetime.strptime(new_endtime_str, '%H:%M:%S').time()
                new_end_dt = datetime.combine(original_date, new_time)
                
                updates.append("end_time = ?")
                params.append(new_end_dt.timestamp())
            except ValueError:
                print("Invalid end time format. Please use HH:MM:SS.")
                return

        if not updates:
            print("No adjustments provided. Use --name, --desc, --start, --end, or --endtime.")
            return

        params.append(project_id)
        
        try:
            cursor.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", tuple(params))
            conn.commit()
            if cursor.rowcount > 0:
                print(f"Successfully adjusted project ID {project_id}.")
            else:
                print(f"Project ID {project_id} not found.")
        except sqlite3.Error as e:
            print(f"Database error: {e}")

def main():
    """Main function to handle command-line arguments."""
    initialize_database()
    
    parser = argparse.ArgumentParser(description="A command-line timesheet tool for tracking projects.")
    subparsers = parser.add_subparsers(dest='command', required=True, help='Available commands')

    # 'start' command
    start_parser = subparsers.add_parser('start', help='Start a new project session.')
    start_parser.add_argument('short_name', type=str, help='A short, easy-to-type name for the project.')
    start_parser.add_argument('description', type=str, nargs='?', default='', help='An optional description of the work session.')

    # 'stop' command
    stop_parser = subparsers.add_parser('stop', help='Stop the currently active project session.')

    # 'status' command
    status_parser = subparsers.add_parser('status', help='Show the currently active project.')

    # 'list' command
    list_parser = subparsers.add_parser('list', help='List all project sessions.')

    # 'view' command
    view_parser = subparsers.add_parser('view', help='View details for a specific project.')
    view_parser.add_argument('short_name', type=str, help='The short name of the project to view.')

    # 'adjust' command
    adjust_parser = subparsers.add_parser('adjust', help='Adjust the properties of a specific project session.')
    adjust_parser.add_argument('project_id', type=int, help='The ID of the project session to adjust.')
    adjust_parser.add_argument('--name', type=str, help='The new short name for the project.')
    adjust_parser.add_argument('--desc', type=str, help='The new description for the session.')
    adjust_parser.add_argument('--start', type=str, help='The new start time in "YYYY-MM-DD HH:MM:SS" format.')
    adjust_parser.add_argument('--end', type=str, help='The new end time in "YYYY-MM-DD HH:MM:SS" format.')
    adjust_parser.add_argument('--endtime', type=str, help='The new end time in "HH:MM:SS" format, keeping the original date.')

    args = parser.parse_args()

    if args.command == 'start':
        start_project(args.short_name, args.description)
    elif args.command == 'stop':
        stop_project()
    elif args.command == 'status':
        show_status()
    elif args.command == 'list':
        list_projects()
    elif args.command == 'view':
        view_project(args.short_name)
    elif args.command == 'adjust':
        adjust_project(args.project_id, args.name, args.desc, args.start, args.end, args.endtime)


if __name__ == '__main__':
    main()
