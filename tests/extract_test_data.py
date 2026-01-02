"""
Extract 7 days of activity data from the production database
to create a test fixture for regression testing.
"""
import sqlite3
import json
import os
from datetime import datetime, timedelta

DB_FILE = 'data/activity.sqlite'
OUTPUT_DIR = 'tests/fixtures'


def get_last_7_days_data():
    """Extract activity data from the last 7 days."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get the date range (last 7 days based on local_date)
    cursor.execute("""
        SELECT DISTINCT local_date 
        FROM activity 
        WHERE local_date IS NOT NULL 
        ORDER BY local_date DESC 
        LIMIT 7
    """)
    dates = [row['local_date'] for row in cursor.fetchall()]
    
    if not dates:
        print("No data found in database!")
        return
    
    print(f"Extracting data for dates: {dates}")
    
    # Extract activities for these dates
    placeholders = ','.join(['?' for _ in dates])
    cursor.execute(f"""
        SELECT id, timestamp, category, duration, window_title, 
               source, window_url, window_url_short, local_date
        FROM activity 
        WHERE local_date IN ({placeholders})
        ORDER BY timestamp
    """, dates)
    
    activities = []
    for row in cursor.fetchall():
        activities.append({
            'id': row['id'],
            'timestamp': row['timestamp'],
            'category': row['category'],
            'duration': row['duration'],
            'window_title': row['window_title'],
            'source': row['source'],
            'window_url': row['window_url'],
            'window_url_short': row['window_url_short'],
            'local_date': row['local_date']
        })
    
    print(f"Extracted {len(activities)} activity records")
    
    # Calculate summary statistics per day
    daily_stats = {}
    for activity in activities:
        date = activity['local_date']
        cat = activity['category']
        dur = activity['duration']
        
        if date not in daily_stats:
            daily_stats[date] = {'categories': {}, 'total_duration': 0}
        
        daily_stats[date]['categories'][cat] = daily_stats[date]['categories'].get(cat, 0) + dur
        daily_stats[date]['total_duration'] += dur
    
    # Save activities to fixture file
    fixture_data = {
        'extracted_at': datetime.now().isoformat(),
        'date_range': {'start': min(dates), 'end': max(dates)},
        'record_count': len(activities),
        'activities': activities,
        'daily_summary': daily_stats
    }
    
    fixture_path = os.path.join(OUTPUT_DIR, 'activity_7days.json')
    with open(fixture_path, 'w', encoding='utf-8') as f:
        json.dump(fixture_data, f, indent=2, ensure_ascii=False)
    
    print(f"Saved fixture to {fixture_path}")
    
    # Print summary
    print("\n" + "="*60)
    print("DAILY SUMMARY")
    print("="*60)
    for date in sorted(daily_stats.keys()):
        stats = daily_stats[date]
        total_mins = stats['total_duration'] / 60
        print(f"\n{date} (Total: {total_mins:.0f} min)")
        for cat, dur in sorted(stats['categories'].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {dur/60:.1f} min")
    
    conn.close()
    return fixture_data


if __name__ == '__main__':
    get_last_7_days_data()
