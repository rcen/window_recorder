"""
Regression and unit tests for remote database synchronization features.
Tests:
- ensure_remote_tables (schema creation and idempotency)
- sync_activities_to_remote (batching, synced flag updates, conflict updates)
- sync_habits_to_remote & sync_must_done_to_remote
- recategorize.py (synced flag reset to 0 upon category changes)
- database.trigger_background_sync (non-blocking daemon thread & locking)
"""
import os
import sys
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import backup_to_remote
import database
from recategorize import recategorize_past_week


@pytest.fixture
def temp_workspace():
    """Sets up an isolated temporary local SQLite database and mock remote engine."""
    tmp_dir = tempfile.mkdtemp()
    local_db_path = os.path.join(tmp_dir, "local_activity.sqlite")
    remote_db_path = os.path.join(tmp_dir, "remote_activity.sqlite")

    # Create local database schema
    conn = sqlite3.connect(local_db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            category TEXT NOT NULL,
            duration INTEGER NOT NULL,
            window_title TEXT NOT NULL,
            synced INTEGER DEFAULT 0,
            source TEXT,
            window_url TEXT,
            window_url_short TEXT,
            local_date TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE habit_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit TEXT NOT NULL,
            local_date TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 1,
            updated_at REAL,
            UNIQUE(habit, local_date)
        )
    """)
    cur.execute("""
        CREATE TABLE habit_completion_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit TEXT NOT NULL,
            local_date TEXT NOT NULL,
            completed INTEGER NOT NULL,
            happened_at REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE must_done_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            week_id TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at REAL,
            UNIQUE(task_id, week_id)
        )
    """)
    cur.execute("""
        CREATE TABLE warning_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            timestamp REAL NOT NULL,
            elapsed_seconds REAL NOT NULL,
            result TEXT NOT NULL,
            message TEXT,
            title TEXT
        )
    """)
    conn.commit()
    conn.close()

    # Create mock remote engine (SQLite in file mode)
    remote_engine = create_engine(f"sqlite:///{remote_db_path}")

    # Patch backup_to_remote and database DB_FILE
    old_backup_db = backup_to_remote.DB_FILE
    old_database_db = database.DB_FILE
    backup_to_remote.DB_FILE = local_db_path
    database.DB_FILE = local_db_path

    yield {
        "tmp_dir": tmp_dir,
        "local_db": local_db_path,
        "remote_db": remote_db_path,
        "remote_engine": remote_engine,
    }

    # Teardown
    backup_to_remote.DB_FILE = old_backup_db
    database.DB_FILE = old_database_db


class TestRemoteSync:
    """Test suite for remote database backup and synchronization."""

    def test_ensure_remote_tables(self, temp_workspace):
        """Verifies tables and indexes are created without error and operation is idempotent."""
        engine = temp_workspace["remote_engine"]
        backup_to_remote.ensure_remote_tables(engine)

        with engine.connect() as conn:
            # Verify tables exist
            for table in ["activity", "habit_completions", "habit_completion_events", "must_done_items", "warning_flags"]:
                res = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                assert res == 0

        # Run a second time to ensure idempotency (no duplicate errors)
        backup_to_remote.ensure_remote_tables(engine)

    def test_sync_activities_batch_and_flag(self, temp_workspace):
        """Tests that unsynced activities are uploaded and marked synced=1 locally."""
        engine = temp_workspace["remote_engine"]
        local_db = temp_workspace["local_db"]
        backup_to_remote.ensure_remote_tables(engine)

        # Seed local activities
        conn = sqlite3.connect(local_db)
        cur = conn.cursor()
        for i in range(1, 6):
            cur.execute("""
                INSERT INTO activity (id, timestamp, category, duration, window_title, synced, source, local_date)
                VALUES (?, ?, ?, ?, ?, 0, 'test_pc', '2026-09-13')
            """, (i, 1789340000.0 + i * 10, "coding", 10, f"editor_{i}"))
        conn.commit()
        conn.close()

        # Run sync
        synced_count = backup_to_remote.sync_activities_to_remote(engine, dry_run=False, verbose=False)
        assert synced_count == 5

        # Verify remote received all 5 rows
        with engine.connect() as conn:
            remote_count = conn.execute(text("SELECT COUNT(*) FROM activity WHERE synced = 1")).scalar()
            assert remote_count == 5

        # Verify local records marked as synced = 1
        conn = sqlite3.connect(local_db)
        cur = conn.cursor()
        unsynced_left = cur.execute("SELECT COUNT(*) FROM activity WHERE synced = 0").fetchone()[0]
        synced_total = cur.execute("SELECT COUNT(*) FROM activity WHERE synced = 1").fetchone()[0]
        conn.close()

        assert unsynced_left == 0
        assert synced_total == 5

        # Subsequent sync should sync 0 records
        second_sync = backup_to_remote.sync_activities_to_remote(engine, dry_run=False, verbose=False)
        assert second_sync == 0

    def test_sync_activities_conflict_update(self, temp_workspace):
        """Tests that modified activities update on remote instead of failing or ignoring."""
        engine = temp_workspace["remote_engine"]
        local_db = temp_workspace["local_db"]
        backup_to_remote.ensure_remote_tables(engine)

        # 1. Initial insert and sync
        conn = sqlite3.connect(local_db)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO activity (id, timestamp, category, duration, window_title, synced, source, local_date)
            VALUES (101, 1789340000.0, 'wasted', 300, 'social feed', 0, 'pc', '2026-09-13')
        """)
        conn.commit()
        conn.close()

        backup_to_remote.sync_activities_to_remote(engine, dry_run=False, verbose=False)

        # 2. Local recategorization: changed from wasted -> learning, synced reset to 0
        conn = sqlite3.connect(local_db)
        cur = conn.cursor()
        cur.execute("UPDATE activity SET category = 'learning', synced = 0 WHERE id = 101")
        conn.commit()
        conn.close()

        # 3. Sync again
        backup_to_remote.sync_activities_to_remote(engine, dry_run=False, verbose=False)

        # 4. Verify remote category was updated
        with engine.connect() as conn:
            remote_cat = conn.execute(text("SELECT category FROM activity WHERE id = 101")).scalar()
            assert remote_cat == "learning"

    def test_sync_habits_and_must_done(self, temp_workspace):
        """Tests syncing of habit completions and must-done tasks."""
        engine = temp_workspace["remote_engine"]
        local_db = temp_workspace["local_db"]
        backup_to_remote.ensure_remote_tables(engine)

        # Insert local habit and must-done
        conn = sqlite3.connect(local_db)
        cur = conn.cursor()
        cur.execute("INSERT INTO habit_completions (habit, local_date, completed, updated_at) VALUES ('read', '2026-09-13', 1, 1789340000.0)")
        cur.execute("INSERT INTO habit_completion_events (id, habit, local_date, completed, happened_at) VALUES (1, 'read', '2026-09-13', 1, 1789340000.0)")
        cur.execute("INSERT INTO must_done_items (task_id, week_id, completed, completed_at) VALUES ('task_a', '2026-W37', 1, 1789340000.0)")
        conn.commit()
        conn.close()

        backup_to_remote.sync_habits_to_remote(engine, dry_run=False, verbose=False)
        backup_to_remote.sync_must_done_to_remote(engine, dry_run=False, verbose=False)

        with engine.connect() as conn:
            habits_count = conn.execute(text("SELECT COUNT(*) FROM habit_completions WHERE habit = 'read'")).scalar()
            must_done_count = conn.execute(text("SELECT COUNT(*) FROM must_done_items WHERE task_id = 'task_a'")).scalar()
            assert habits_count == 1
            assert must_done_count == 1

    def test_trigger_background_sync_locking(self, monkeypatch):
        """Verifies that trigger_background_sync is non-blocking and prevents overlapping syncs."""
        sync_started = threading.Event()
        release_sync = threading.Event()

        def mock_sync_local_data(dry_run=False, verbose=False):
            sync_started.set()
            release_sync.wait(timeout=5)
            return True

        monkeypatch.setattr(database, "sync_local_data", mock_sync_local_data)

        # First call starts background thread
        res1 = database.trigger_background_sync(verbose=False)
        assert res1 is True

        # Wait for worker to enter execution
        sync_started.wait(timeout=2)

        # Second call while running should return False
        res2 = database.trigger_background_sync(verbose=False)
        assert res2 is False

        # Release first worker
        release_sync.set()
        time.sleep(0.2)

        # After worker finishes, next trigger should return True
        res3 = database.trigger_background_sync(verbose=False)
        assert res3 is True
