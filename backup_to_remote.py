"""
Manual backup script to sync local SQLite database to remote PostgreSQL (Neon).

This script copies all local data to the remote database as a backup.
Run this manually when you want to backup your data to the cloud.

Usage:
    python backup_to_remote.py
    python backup_to_remote.py --dry-run  # Show what would be synced without actually doing it
"""

import sqlite3
import sys
import argparse
from datetime import datetime
from sqlalchemy import create_engine, text
from config import get_database_uri, TIMEZONE
import pytz

def get_local_activities():
    """Fetch all activities from local SQLite database."""
    conn = sqlite3.connect('data/activity.sqlite')
    cursor = conn.cursor()
    
    # Get all activities
    cursor.execute("""
        SELECT id, timestamp, category, duration, window_title, source, 
               window_url, window_url_short, local_date
        FROM activity
        ORDER BY timestamp
    """)
    
    activities = cursor.fetchall()
    conn.close()
    return activities

def get_remote_activity_ids(remote_engine):
    """Fetch all activity IDs that already exist in remote database."""
    try:
        with remote_engine.connect() as connection:
            result = connection.execute(text("SELECT id FROM activity"))
            return set(row[0] for row in result)
    except Exception as e:
        print(f"Error fetching remote IDs: {e}")
        return set()

def sync_activities_to_remote(remote_engine, dry_run=False):
    """Sync local activities to remote database."""
    print("Fetching local activities...")
    local_activities = get_local_activities()
    print(f"Found {len(local_activities)} local activities")
    
    print("\nFetching remote activity IDs...")
    remote_ids = get_remote_activity_ids(remote_engine)
    print(f"Found {len(remote_ids)} activities already in remote database")
    
    # Find activities that need to be synced
    to_sync = [act for act in local_activities if act[0] not in remote_ids]
    print(f"\n{len(to_sync)} new activities need to be synced")
    
    if not to_sync:
        print("✅ All local data is already backed up to remote database!")
        return
    
    if dry_run:
        print("\n🔍 DRY RUN - Would sync the following:")
        for i, act in enumerate(to_sync[:10], 1):  # Show first 10
            timestamp, category, duration, window_title = act[1], act[2], act[3], act[4]
            dt = datetime.fromtimestamp(timestamp, pytz.timezone(TIMEZONE))
            print(f"  {i}. {dt.strftime('%Y-%m-%d %H:%M')} - {category} - {window_title[:50]}...")
        if len(to_sync) > 10:
            print(f"  ... and {len(to_sync) - 10} more")
        print("\n⚠️  Run without --dry-run to actually sync")
        return
    
    # Sync activities in batches
    print("\n📤 Syncing activities to remote database...")
    batch_size = 100
    synced_count = 0
    
    try:
        with remote_engine.connect() as connection:
            for i in range(0, len(to_sync), batch_size):
                batch = to_sync[i:i + batch_size]
                
                for act in batch:
                    id_, timestamp, category, duration, window_title, source, \
                        window_url, window_url_short, local_date = act
                    
                    connection.execute(text("""
                        INSERT INTO activity 
                        (id, timestamp, category, duration, window_title, source, 
                         window_url, window_url_short, local_date, synced)
                        VALUES 
                        (:id, :timestamp, :category, :duration, :window_title, :source,
                         :window_url, :window_url_short, :local_date, TRUE)
                        ON CONFLICT (id) DO NOTHING
                    """), {
                        'id': id_,
                        'timestamp': timestamp,
                        'category': category,
                        'duration': duration,
                        'window_title': window_title,
                        'source': source,
                        'window_url': window_url,
                        'window_url_short': window_url_short,
                        'local_date': local_date
                    })
                
                connection.commit()
                synced_count += len(batch)
                print(f"  Synced {synced_count}/{len(to_sync)} activities...")
        
        print(f"\n✅ Successfully synced {synced_count} activities to remote database!")
        
    except Exception as e:
        print(f"\n❌ Error during sync: {e}")
        raise

def sync_habits_to_remote(remote_engine, dry_run=False):
    """Sync habit completions to remote database."""
    conn = sqlite3.connect('data/activity.sqlite')
    cursor = conn.cursor()
    
    # Get all habit completions
    cursor.execute("""
        SELECT habit, local_date, completed, updated_at
        FROM habit_completions
        ORDER BY local_date
    """)
    
    local_habits = cursor.fetchall()
    conn.close()
    
    if not local_habits:
        print("\nNo habit data to sync")
        return
    
    print(f"\nFound {len(local_habits)} habit completion records")
    
    if dry_run:
        print("🔍 DRY RUN - Would sync habit data")
        return
    
    print("📤 Syncing habit completions to remote database...")
    
    try:
        with remote_engine.connect() as connection:
            for habit, local_date, completed, updated_at in local_habits:
                connection.execute(text("""
                    INSERT INTO habit_completions 
                    (habit, local_date, completed, updated_at)
                    VALUES 
                    (:habit, :local_date, :completed, :updated_at)
                    ON CONFLICT (habit, local_date) 
                    DO UPDATE SET completed = :completed, updated_at = :updated_at
                """), {
                    'habit': habit,
                    'local_date': local_date,
                    'completed': bool(completed),
                    'updated_at': updated_at
                })
            
            connection.commit()
        
        print(f"✅ Successfully synced {len(local_habits)} habit records!")
        
    except Exception as e:
        print(f"❌ Error syncing habits: {e}")
        raise

def sync_must_done_to_remote(remote_engine, dry_run=False):
    """Sync must-done items to remote database."""
    conn = sqlite3.connect('data/activity.sqlite')
    cursor = conn.cursor()
    
    # Get all must-done items
    cursor.execute("""
        SELECT task_id, week_id, completed, completed_at
        FROM must_done_items
        ORDER BY week_id
    """)
    
    local_must_done = cursor.fetchall()
    conn.close()
    
    if not local_must_done:
        print("\nNo must-done data to sync")
        return
    
    print(f"\nFound {len(local_must_done)} must-done item records")
    
    if dry_run:
        print("🔍 DRY RUN - Would sync must-done data")
        return
    
    print("📤 Syncing must-done items to remote database...")
    
    try:
        with remote_engine.connect() as connection:
            # Create table if it doesn't exist
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS must_done_items (
                    id SERIAL PRIMARY KEY,
                    task_id VARCHAR(255) NOT NULL,
                    week_id VARCHAR(255) NOT NULL,
                    completed BOOLEAN NOT NULL DEFAULT FALSE,
                    completed_at DOUBLE PRECISION,
                    UNIQUE(task_id, week_id)
                )
            """))
            
            for task_id, week_id, completed, completed_at in local_must_done:
                connection.execute(text("""
                    INSERT INTO must_done_items 
                    (task_id, week_id, completed, completed_at)
                    VALUES 
                    (:task_id, :week_id, :completed, :completed_at)
                    ON CONFLICT (task_id, week_id) 
                    DO UPDATE SET completed = :completed, completed_at = :completed_at
                """), {
                    'task_id': task_id,
                    'week_id': week_id,
                    'completed': bool(completed),
                    'completed_at': completed_at
                })
            
            connection.commit()
        
        print(f"✅ Successfully synced {len(local_must_done)} must-done records!")
        
    except Exception as e:
        print(f"❌ Error syncing must-done items: {e}")
        raise

def main():
    parser = argparse.ArgumentParser(description='Backup local database to remote PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be synced without actually doing it')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Local to Remote Database Backup Tool")
    print("=" * 60)
    
    # Get remote database URI
    remote_uri = get_database_uri()
    if not remote_uri:
        print("❌ No remote database configured!")
        print("Please set DATABASE_URI in .env file")
        sys.exit(1)
    
    print(f"\nRemote database: {remote_uri.split('@')[1] if '@' in remote_uri else 'configured'}")
    
    if args.dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made\n")
    
    # Connect to remote database
    print("\nConnecting to remote database...")
    try:
        remote_engine = create_engine(remote_uri)
        with remote_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("✅ Connected successfully!")
    except Exception as e:
        print(f"❌ Failed to connect to remote database: {e}")
        sys.exit(1)
    
    # Sync activities
    try:
        sync_activities_to_remote(remote_engine, args.dry_run)
        sync_habits_to_remote(remote_engine, args.dry_run)
        sync_must_done_to_remote(remote_engine, args.dry_run)
        
        if not args.dry_run:
            print("\n" + "=" * 60)
            print("🎉 Backup completed successfully!")
            print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Backup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Backup failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
