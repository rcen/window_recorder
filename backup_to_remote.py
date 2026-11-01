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
import os
import argparse
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from sqlalchemy import create_engine, text
from config import get_database_uri, TIMEZONE
import pytz

DB_FILE = 'data/activity.sqlite'


def ensure_remote_tables(remote_engine) -> None:
    """Ensures all necessary tables and indexes exist on the remote PostgreSQL database."""
    with remote_engine.connect() as connection:
        # 1. activity table
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS activity (
                id BIGINT PRIMARY KEY,
                timestamp DOUBLE PRECISION NOT NULL,
                category VARCHAR(255) NOT NULL,
                duration INTEGER NOT NULL,
                window_title TEXT NOT NULL,
                synced BOOLEAN DEFAULT TRUE,
                source VARCHAR(255),
                window_url TEXT,
                window_url_short TEXT,
                local_date DATE
            )
        """))
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_activity_local_date ON activity(local_date)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity(timestamp)"))

        # 2. habit_completions table
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS habit_completions (
                id SERIAL PRIMARY KEY,
                habit VARCHAR(255) NOT NULL,
                local_date VARCHAR(50) NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at DOUBLE PRECISION,
                UNIQUE(habit, local_date)
            );
        """))

        # 3. habit_completion_events table
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS habit_completion_events (
                id SERIAL PRIMARY KEY,
                habit VARCHAR(255) NOT NULL,
                local_date VARCHAR(50) NOT NULL,
                completed BOOLEAN NOT NULL,
                happened_at DOUBLE PRECISION NOT NULL
            );
        """))

        # 4. must_done_items table
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS must_done_items (
                id SERIAL PRIMARY KEY,
                task_id VARCHAR(255) NOT NULL,
                week_id VARCHAR(255) NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT FALSE,
                completed_at DOUBLE PRECISION,
                UNIQUE(task_id, week_id)
            );
        """))

        # 5. warning_flags table
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS warning_flags (
                id SERIAL PRIMARY KEY,
                event_id VARCHAR(255) UNIQUE,
                timestamp DOUBLE PRECISION NOT NULL,
                elapsed_seconds DOUBLE PRECISION NOT NULL,
                result VARCHAR(255) NOT NULL,
                message TEXT,
                title TEXT
            );
        """))
        connection.commit()


def _format_date(val: Any, timestamp: float) -> Optional[str]:
    """Helper to ensure local_date is formatted as YYYY-MM-DD for PostgreSQL DATE column."""
    if val and str(val).strip():
        return str(val).strip()[:10]
    try:
        from database import calculate_adjusted_local_date
        return calculate_adjusted_local_date(timestamp)
    except Exception:
        tz = pytz.timezone(TIMEZONE)
        return datetime.fromtimestamp(timestamp, tz).strftime('%Y-%m-%d')

def sync_activities_to_remote(remote_engine, dry_run: bool = False, verbose: bool = True,
                              batch_size: int = 1000, limit: Optional[int] = None) -> int:
    """
    Syncs unsynced activities (synced = 0) from SQLite to Neon PostgreSQL in batches.
    Updates synced = 1 in SQLite upon successful commit.
    """
    if not os.path.exists(DB_FILE):
        if verbose:
            print(f"[WARN] Local database file {DB_FILE} not found.")
        return 0

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    query = """
        SELECT id, timestamp, category, duration, window_title, source, 
               window_url, window_url_short, local_date
        FROM activity
        WHERE synced = 0
        ORDER BY timestamp ASC
    """
    if limit and limit > 0:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    unsynced_rows = cursor.fetchall()

    total_to_sync = len(unsynced_rows)
    if verbose:
        print(f"[INFO] Found {total_to_sync} unsynced local activities.")

    if total_to_sync == 0:
        conn.close()
        if verbose:
            print("[OK] All local activities are already synced.")
        return 0

    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Would sync {total_to_sync} activities. Showing first 5:")
            for i, act in enumerate(unsynced_rows[:5], 1):
                dt = datetime.fromtimestamp(act[1], pytz.timezone(TIMEZONE))
                print(f"  {i}. {dt.strftime('%Y-%m-%d %H:%M:%S')} - {act[2]} - {str(act[4])[:50]}")
            if total_to_sync > 5:
                print(f"  ... and {total_to_sync - 5} more")
        conn.close()
        return total_to_sync

    insert_stmt = text("""
        INSERT INTO activity 
        (id, timestamp, category, duration, window_title, source, 
         window_url, window_url_short, local_date, synced)
        VALUES 
        (:id, :timestamp, :category, :duration, :window_title, :source,
         :window_url, :window_url_short, :local_date, TRUE)
        ON CONFLICT (id) DO UPDATE SET 
            category = EXCLUDED.category,
            duration = EXCLUDED.duration,
            window_title = EXCLUDED.window_title,
            synced = TRUE
    """)

    synced_count = 0
    try:
        with remote_engine.connect() as connection:
            for i in range(0, total_to_sync, batch_size):
                batch = unsynced_rows[i:i + batch_size]
                batch_dicts = []
                batch_ids = []

                for row in batch:
                    act_id, ts, cat, dur, title, src, url, url_short, ldate = row
                    clean_date = _format_date(ldate, ts)

                    batch_dicts.append({
                        'id': act_id,
                        'timestamp': ts,
                        'category': cat or 'unknown',
                        'duration': dur,
                        'window_title': title or '',
                        'source': src or 'unknown',
                        'window_url': url,
                        'window_url_short': url_short,
                        'local_date': clean_date
                    })
                    batch_ids.append((act_id,))

                # 1. Insert into Remote Postgres
                connection.execute(insert_stmt, batch_dicts)
                connection.commit()

                # 2. Mark as synced in local SQLite
                cursor.executemany("UPDATE activity SET synced = 1 WHERE id = ?", batch_ids)
                conn.commit()

                synced_count += len(batch)
                if verbose and (synced_count % 5000 == 0 or synced_count == total_to_sync):
                    print(f"[INFO] Synced {synced_count}/{total_to_sync} activities...")

        if verbose:
            print(f"[OK] Successfully synced {synced_count} activities to remote database!")
    except Exception as e:
        if verbose:
            print(f"[ERROR] Error during activity sync: {e}")
        logging.error(f"Error during activity sync: {e}")
        raise
    finally:
        conn.close()

    return synced_count

def sync_habits_to_remote(remote_engine, dry_run: bool = False, verbose: bool = True) -> None:
    """Sync habit completions and events to remote database."""
    if not os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Habit completions
    cursor.execute("""
        SELECT habit, local_date, completed, updated_at
        FROM habit_completions
        ORDER BY local_date
    """)
    local_habits = cursor.fetchall()

    if local_habits:
        if verbose:
            print(f"[INFO] Found {len(local_habits)} habit completion records.")
        if not dry_run:
            habit_stmt = text("""
                INSERT INTO habit_completions 
                (habit, local_date, completed, updated_at)
                VALUES 
                (:habit, :local_date, :completed, :updated_at)
                ON CONFLICT (habit, local_date) 
                DO UPDATE SET 
                    completed = EXCLUDED.completed, 
                    updated_at = EXCLUDED.updated_at
            """)
            habit_dicts = [{
                'habit': h[0],
                'local_date': str(h[1]),
                'completed': bool(h[2]),
                'updated_at': h[3]
            } for h in local_habits]

            with remote_engine.connect() as connection:
                connection.execute(habit_stmt, habit_dicts)
                connection.commit()
            if verbose:
                print(f"[OK] Successfully synced {len(local_habits)} habit completion records.")

    # 2. Habit completion events
    try:
        cursor.execute("""
            SELECT id, habit, local_date, completed, happened_at
            FROM habit_completion_events
            ORDER BY happened_at
        """)
        events = cursor.fetchall()
        if events and not dry_run:
            event_stmt = text("""
                INSERT INTO habit_completion_events 
                (id, habit, local_date, completed, happened_at)
                VALUES 
                (:id, :habit, :local_date, :completed, :happened_at)
                ON CONFLICT (id) DO NOTHING
            """)
            event_dicts = [{
                'id': ev[0],
                'habit': ev[1],
                'local_date': str(ev[2]),
                'completed': bool(ev[3]),
                'happened_at': ev[4]
            } for ev in events]

            with remote_engine.connect() as connection:
                connection.execute(event_stmt, event_dicts)
                connection.commit()
            if verbose:
                print(f"[OK] Successfully synced {len(events)} habit completion events.")
    except sqlite3.OperationalError:
        pass

    conn.close()


def sync_must_done_to_remote(remote_engine, dry_run: bool = False, verbose: bool = True) -> None:
    """Sync must-done items to remote database."""
    if not os.path.exists(DB_FILE):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT task_id, week_id, completed, completed_at
            FROM must_done_items
            ORDER BY week_id
        """)
        local_must_done = cursor.fetchall()
    except sqlite3.OperationalError:
        local_must_done = []
    finally:
        conn.close()

    if not local_must_done:
        return

    if verbose:
        print(f"[INFO] Found {len(local_must_done)} must-done item records.")

    if dry_run:
        return

    must_done_stmt = text("""
        INSERT INTO must_done_items 
        (task_id, week_id, completed, completed_at)
        VALUES 
        (:task_id, :week_id, :completed, :completed_at)
        ON CONFLICT (task_id, week_id) 
        DO UPDATE SET 
            completed = EXCLUDED.completed, 
            completed_at = EXCLUDED.completed_at
    """)
    must_done_dicts = [{
        'task_id': item[0],
        'week_id': item[1],
        'completed': bool(item[2]),
        'completed_at': item[3]
    } for item in local_must_done]

    with remote_engine.connect() as connection:
        connection.execute(must_done_stmt, must_done_dicts)
        connection.commit()

    if verbose:
        print(f"[OK] Successfully synced {len(local_must_done)} must-done records.")


def run_full_sync(dry_run: bool = False, verbose: bool = True, batch_size: int = 1000,
                  limit: Optional[int] = None) -> bool:
    """
    Programmatic entrypoint to run a complete synchronization to the remote PostgreSQL database.
    Returns True on success, False on failure.
    """
    remote_uri = get_database_uri()
    if not remote_uri:
        if verbose:
            print("[WARN] No remote database configured (DATABASE_URI is empty).")
        return False

    try:
        remote_engine = create_engine(remote_uri, pool_pre_ping=True)
        ensure_remote_tables(remote_engine)
        sync_activities_to_remote(remote_engine, dry_run=dry_run, verbose=verbose,
                                  batch_size=batch_size, limit=limit)
        sync_habits_to_remote(remote_engine, dry_run=dry_run, verbose=verbose)
        sync_must_done_to_remote(remote_engine, dry_run=dry_run, verbose=verbose)
        return True
    except Exception as e:
        if verbose:
            print(f"[ERROR] Sync failed: {e}")
        logging.error(f"Sync failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Sync local SQLite database to remote PostgreSQL (Neon)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be synced without modifying any data')
    parser.add_argument('--batch-size', type=int, default=1000,
                        help='Batch size for remote inserts (default: 1000)')
    parser.add_argument('--limit', type=int, default=None,
                        help='Maximum number of activity records to sync in this run')
    args = parser.parse_args()

    print("=" * 60)
    print("Window Recorder: Local to Remote Database Sync Tool")
    print("=" * 60)

    remote_uri = get_database_uri()
    if not remote_uri:
        print("[ERROR] No remote database configured! Set DATABASE_URI in .env")
        sys.exit(1)

    print(f"Remote database: {remote_uri.split('@')[1] if '@' in remote_uri else 'configured'}")

    if args.dry_run:
        print("\n[DRY-RUN MODE] No remote or local changes will be made.\n")

    print("\nConnecting to remote database...")
    try:
        remote_engine = create_engine(remote_uri, pool_pre_ping=True)
        with remote_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[OK] Connected successfully!")
    except Exception as e:
        print(f"[ERROR] Failed to connect to remote database: {e}")
        sys.exit(1)

    try:
        ensure_remote_tables(remote_engine)
        sync_activities_to_remote(remote_engine, dry_run=args.dry_run, verbose=True,
                                  batch_size=args.batch_size, limit=args.limit)
        sync_habits_to_remote(remote_engine, dry_run=args.dry_run, verbose=True)
        sync_must_done_to_remote(remote_engine, dry_run=args.dry_run, verbose=True)

        if not args.dry_run:
            print("\n" + "=" * 60)
            print("[SUCCESS] Backup and sync completed successfully!")
            print("=" * 60)
    except KeyboardInterrupt:
        print("\n[WARN] Sync cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Sync failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
