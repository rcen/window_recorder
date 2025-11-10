#!/usr/bin/env python3
"""
Simple command-line script to manually add activities to the tracking database.
Useful for adding offline activities like walking, jogging, exercise, etc.
"""

import sqlite3
import time
from datetime import datetime, timedelta
import sys
import configparser
import re

DB_FILE = 'data/activity.sqlite'
CONFIG_FILE = 'config.dat'

def load_config():
    """Load configuration from config.dat"""
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    
    # Handle duplicate categories by manually parsing
    categories = []
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        in_categories_section = False
        for line in f:
            stripped = line.strip()
            if stripped.startswith('[CATEGORIES]'):
                in_categories_section = True
                continue
            elif stripped.startswith('[') and in_categories_section:
                break
            elif in_categories_section and ':' in line:
                key, value = line.split(':', 1)
                categories.append((key.strip(), value.strip()))
    
    return categories

def get_category(window_title, string_cats):
    """
    Infer category from window title using the same logic as analytics.py.
    Returns the inferred category or 'not categorized'.
    """
    if not window_title or len(window_title) <= 1:
        return 'idle'
    
    window_lower = window_title.lower()
    
    for string, category in string_cats:
        if not string:
            continue
        string = string.strip()
        if not string:
            continue
        
        # Handle regex patterns (prefix: regex__)
        if string.lower().startswith('regex__'):
            pattern = string[7:]  # Remove 'regex__' prefix
            try:
                if re.search(pattern, window_lower, re.IGNORECASE):
                    return category
            except re.error:
                continue
        else:
            # Simple substring match
            needle = string.lower()
            if needle in window_lower:
                return category
    
    return 'not categorized'

def add_manual_activity():
    """
    Prompt user for activity details and add to database.
    """
    print("\n=== Add Manual Activity ===\n")
    
    # Load config for category inference
    string_cats = load_config()
    
    # Get activity description
    description = input("Activity description (e.g., 'jogging', 'walk', 'exercise'): ").strip()
    if not description:
        print("Error: Description cannot be empty.")
        return
    
    # Infer category from description
    inferred_category = get_category(description, string_cats)
    
    print(f"\nInferred category: {inferred_category}")
    override = input("Press Enter to accept, or type a different category: ").strip().lower()
    
    if override:
        category = override
    else:
        category = inferred_category
    
    # Get duration
    try:
        duration_minutes = float(input("\nDuration in minutes: "))
        if duration_minutes <= 0:
            print("Error: Duration must be positive.")
            return
    except ValueError:
        print("Error: Invalid duration. Please enter a number.")
        return
    
    # Get timestamp (default to now, or specify time)
    time_input = input("\nTime in 24-hour format (HH:MM, e.g., 14:30, or press Enter for now): ").strip()
    
    if time_input:
        try:
            # Parse time as HH:MM
            time_parts = time_input.split(':')
            if len(time_parts) != 2:
                raise ValueError("Invalid time format")
            
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                raise ValueError("Invalid time values")
            
            # Create datetime for today with specified time
            now = datetime.now()
            activity_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If time is in the future, assume it's from yesterday
            if activity_time > now:
                activity_time = activity_time - timedelta(days=1)
            
            timestamp = activity_time.timestamp()
        except (ValueError, IndexError) as e:
            print(f"Error: Invalid time format. Use HH:MM (e.g., 14:30). {e}")
            return
    else:
        # Use current time
        timestamp = time.time()
        activity_time = datetime.fromtimestamp(timestamp)
    
    # Calculate duration in seconds
    duration_seconds = int(duration_minutes * 60)
    
    # Confirm before adding
    print("\n=== Confirm Activity ===")
    print(f"Description: {description}")
    print(f"Category: {category}")
    print(f"Duration: {duration_minutes} min ({duration_seconds} sec)")
    print(f"Time: {activity_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    confirm = input("\nAdd this activity? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return
    
    # Insert into database
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO activity (window_title, category, timestamp, duration) VALUES (?, ?, ?, ?)",
            (description, category, timestamp, duration_seconds)
        )
        
        conn.commit()
        conn.close()
        
        print(f"\n✓ Activity added successfully!")
        print(f"  ID: {cursor.lastrowid}")
        print(f"\nRun 'python analytics.py' to regenerate reports with this activity.")
        
    except sqlite3.Error as e:
        print(f"\n✗ Database error: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")

def list_recent_activities(limit=10):
    """
    Display recent activities for reference.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT window_title, category, timestamp, duration FROM activity "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        
        activities = cursor.fetchall()
        conn.close()
        
        if not activities:
            print("No activities found.")
            return
        
        print(f"\n=== Last {len(activities)} Activities ===\n")
        for title, cat, ts, dur in activities:
            dt = datetime.fromtimestamp(ts)
            dur_min = dur / 60
            print(f"  {dt.strftime('%Y-%m-%d %H:%M')} | {dur_min:5.1f} min | [{cat:12s}] {title[:50]}")
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--list':
        list_recent_activities(20)
    else:
        add_manual_activity()
