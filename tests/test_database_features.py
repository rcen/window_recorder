"""
Unit and regression tests for core database features:
- Day-boundary activity splitting (splitting across 3 AM)
- Habit tracking CRUD & completion events
- Must-Done items management
- Warning flags logging and counting
- Bookmarks management
"""
import os
import sys
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
import pytest
import pytz

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import database
from config import TIMEZONE, DAY_BOUNDARY_HOUR


@pytest.fixture
def temp_db():
    """Creates a fresh, isolated temporary SQLite database for testing database.py functions."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test_activity.sqlite")

    old_db = database.DB_FILE
    database.DB_FILE = db_path

    database.initialize_database()

    yield db_path

    database.DB_FILE = old_db


class TestDayBoundarySplitting:
    """Tests that activities spanning the 3 AM day boundary are correctly split into two records."""

    def test_activity_within_same_day_not_split(self, temp_db):
        """Activity ending before or after boundary without crossing is inserted as a single record."""
        tz = pytz.timezone(TIMEZONE)
        # 14:00 (2 PM) - 30 minutes duration
        dt = tz.localize(datetime(2026, 9, 13, 14, 0, 0))
        ts = dt.timestamp()

        database.insert_activity(
            timestamp=ts,
            category="coding",
            duration=1800,
            window_title="VS Code - project",
            source="test_pc"
        )

        with sqlite3.connect(temp_db) as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT timestamp, category, duration, local_date FROM activity").fetchall()

        assert len(rows) == 1
        assert rows[0][1] == "coding"
        assert rows[0][2] == 1800
        assert rows[0][3] == "2026-09-13"

    def test_activity_crossing_day_boundary_is_split(self, temp_db):
        """
        Activity starting at 02:45 AM and ending at 03:15 AM (30 min duration)
        spans the 3:00 AM boundary and must be split into:
        Part 1: 02:45 AM - 03:00 AM (duration 900s, belongs to previous day: 2026-09-12)
        Part 2: 03:00 AM - 03:15 AM (duration 900s, belongs to current day: 2026-09-13)
        """
        tz = pytz.timezone(TIMEZONE)
        # End time: 03:15 AM on Sept 13
        end_dt = tz.localize(datetime(2026, 9, 13, DAY_BOUNDARY_HOUR, 15, 0))
        end_ts = end_dt.timestamp()
        duration = 1800  # 30 mins -> started at 02:45 AM

        database.insert_activity(
            timestamp=end_ts,
            category="learning",
            duration=duration,
            window_title="Reading research paper",
            source="test_pc"
        )

        with sqlite3.connect(temp_db) as conn:
            cur = conn.cursor()
            rows = cur.execute("SELECT timestamp, category, duration, local_date FROM activity ORDER BY timestamp ASC").fetchall()

        assert len(rows) == 2, f"Expected 2 split records, got {len(rows)}"

        # Part 1: before boundary (belongs to previous date)
        assert rows[0][1] == "learning"
        assert rows[0][2] == 900
        assert rows[0][3] == "2026-09-12"

        # Part 2: after boundary (belongs to new date)
        assert rows[1][1] == "learning"
        assert rows[1][2] == 900
        assert rows[1][3] == "2026-09-13"


class TestHabitTracking:
    """Tests habit completions and event logging in database.py."""

    def test_record_and_get_habit_completion(self, temp_db):
        """Records habit completion, updates state, and verifies event audit log."""
        # 1. Complete habit
        database.record_habit_completion("exercise", "2026-09-13", completed=True)

        completions = database.get_habit_completions(habits=["exercise"], start_date="2026-09-13", end_date="2026-09-13")
        assert "exercise" in completions
        assert "2026-09-13" in completions["exercise"]
        assert completions["exercise"]["2026-09-13"]["completed"] is True

        # 2. Toggle to incomplete
        database.record_habit_completion("exercise", "2026-09-13", completed=False)
        updated = database.get_habit_completions(habits=["exercise"], start_date="2026-09-13", end_date="2026-09-13")
        assert updated["exercise"]["2026-09-13"]["completed"] is False

        # 3. Verify event audit trail recorded both events
        with sqlite3.connect(temp_db) as conn:
            cur = conn.cursor()
            events = cur.execute("SELECT completed FROM habit_completion_events WHERE habit = 'exercise' ORDER BY happened_at ASC").fetchall()
        assert len(events) == 2
        assert events[0][0] == 1
        assert events[1][0] == 0


class TestMustDoneItems:
    """Tests must-done tasks management."""

    def test_must_done_lifecycle(self, temp_db):
        """Tests adding, completing, and deleting must-done items."""
        # 1. Add item
        item = database.add_must_be_done_item("week", "2026-W37", "Complete weekly report")
        assert item is not None
        item_id = item["id"]

        # 2. Query items
        items = database.get_must_be_done_items("week", "2026-W37")
        assert len(items) == 1
        assert items[0]["description"] == "Complete weekly report"
        assert items[0]["completed"] is False

        # 3. Mark completed
        ok = database.set_must_be_done_item_completed(item_id, True)
        assert ok is True
        items_after = database.get_must_be_done_items("week", "2026-W37")
        assert items_after[0]["completed"] is True

        # 4. Delete item
        del_ok = database.delete_must_be_done_item(item_id)
        assert del_ok is True
        assert len(database.get_must_be_done_items("week", "2026-W37")) == 0


class TestWarningFlags:
    """Tests system alert logging and frequency querying."""

    def test_warning_flags_recording(self, temp_db):
        """Tests recording warning flags and querying counts."""
        database.record_warning_flag("evt-001", 1789340000.0, 15.0, "win", "Closed wasted site", "YouTube")
        # Duplicate event_id should update/ignore without throwing
        database.record_warning_flag("evt-001", 1789340000.0, 15.0, "win", "Closed wasted site", "YouTube")
        database.record_warning_flag("evt-002", 1789340010.0, 30.0, "lose", "Ignored warning", "YouTube")

        counts = database.get_warning_flag_counts()
        assert counts.get("win", 0) == 1
        assert counts.get("lose", 0) == 1


class TestBookmarksCRUD:
    """Tests bookmark creation, retrieval, update, and deletion."""

    def test_bookmarks_crud_flow(self, temp_db):
        """Tests full lifecycle of bookmarks."""
        # 1. Add bookmark
        bm = database.add_bookmark(url="https://docs.python.org", title="Python Docs", tags="programming")
        assert bm is not None
        bm_id = bm["id"]

        # 2. Get bookmark
        fetched = database.get_bookmark_by_id(bm_id)
        assert fetched is not None
        assert fetched["url"] == "https://docs.python.org"
        assert fetched["title"] == "Python Docs"

        # 3. Update bookmark
        database.update_bookmark(bm_id, title="Official Python Documentation")
        updated_bm = database.get_bookmark_by_id(bm_id)
        assert updated_bm["title"] == "Official Python Documentation"

        # 4. Delete bookmark
        database.delete_bookmark(bm_id)
        assert database.get_bookmark_by_id(bm_id) is None
