"""
Test Suite for Streak Notes Functionality
==========================================
Tests saving, retrieving, and parsing of productivity streak notes.

Run with: python -m pytest tests/test_streak_notes.py -v
"""
import os
import sys
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest import mock

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, db_path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    
    # Initialize the database schema
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS streak_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        ''')
        conn.commit()
    
    yield db_path
    
    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def mock_db_file(temp_db):
    """Patch database.DB_FILE to use the temporary database."""
    import database
    original_db_file = database.DB_FILE
    database.DB_FILE = temp_db
    yield temp_db
    database.DB_FILE = original_db_file


# =============================================================================
# TESTS: add_streak_note
# =============================================================================

class TestAddStreakNote:
    """Tests for the add_streak_note function."""
    
    def test_add_streak_note_returns_id(self, mock_db_file):
        """add_streak_note should return the inserted row id (> 0)."""
        import database
        
        note_id = database.add_streak_note("Test note #done")
        
        assert note_id is not None, "add_streak_note returned None"
        assert isinstance(note_id, int), f"Expected int, got {type(note_id)}"
        assert note_id > 0, f"Expected positive id, got {note_id}"
    
    def test_add_streak_note_persists_to_db(self, mock_db_file):
        """Note should be saved and retrievable from database."""
        import database
        
        test_note = "Fixed the login bug #done"
        note_id = database.add_streak_note(test_note)
        
        # Verify by reading directly from database
        with sqlite3.connect(mock_db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT note FROM streak_notes WHERE id = ?", (note_id,))
            row = cursor.fetchone()
        
        assert row is not None, "Note was not saved to database"
        assert row[0] == test_note, f"Expected '{test_note}', got '{row[0]}'"
    
    def test_add_streak_note_with_custom_timestamp(self, mock_db_file):
        """Note should use provided timestamp if given."""
        import database
        
        custom_ts = 1700000000.0  # A specific timestamp
        note_id = database.add_streak_note("Timestamped note", ts=custom_ts)
        
        with sqlite3.connect(mock_db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp FROM streak_notes WHERE id = ?", (note_id,))
            row = cursor.fetchone()
        
        assert row is not None, "Note was not saved"
        assert row[0] == custom_ts, f"Expected timestamp {custom_ts}, got {row[0]}"
    
    def test_add_streak_note_empty_returns_zero(self, mock_db_file):
        """Empty or whitespace-only notes should return 0 without saving."""
        import database
        
        assert database.add_streak_note("") == 0
        assert database.add_streak_note("   ") == 0
        assert database.add_streak_note(None) == 0
        
        # Verify nothing was saved
        with sqlite3.connect(mock_db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM streak_notes")
            count = cursor.fetchone()[0]
        
        assert count == 0, f"Expected 0 notes, got {count}"


# =============================================================================
# TESTS: save_streak_note (compatibility wrapper)
# =============================================================================

class TestSaveStreakNote:
    """Tests for the save_streak_note compatibility function."""
    
    def test_save_streak_note_returns_true_on_success(self, mock_db_file):
        """save_streak_note should return True when note is saved."""
        import database
        
        result = database.save_streak_note("Test note")
        
        assert result is True, f"Expected True, got {result}"
    
    def test_save_streak_note_returns_false_for_empty(self, mock_db_file):
        """save_streak_note should return False for empty notes."""
        import database
        
        result = database.save_streak_note("")
        
        assert result is False, f"Expected False for empty note, got {result}"


# =============================================================================
# TESTS: get_recent_streak_notes
# =============================================================================

class TestGetRecentStreakNotes:
    """Tests for retrieving recent streak notes."""
    
    def test_get_recent_notes_returns_list(self, mock_db_file):
        """get_recent_streak_notes should return a list."""
        import database
        
        result = database.get_recent_streak_notes(5)
        
        assert isinstance(result, list), f"Expected list, got {type(result)}"
    
    def test_get_recent_notes_ordered_newest_first(self, mock_db_file):
        """Notes should be returned in reverse chronological order."""
        import database
        
        # Add notes with different timestamps
        database.add_streak_note("First note", ts=1000.0)
        database.add_streak_note("Second note", ts=2000.0)
        database.add_streak_note("Third note", ts=3000.0)
        
        notes = database.get_recent_streak_notes(5)
        
        assert len(notes) == 3, f"Expected 3 notes, got {len(notes)}"
        # Notes should be newest first
        assert notes[0][0] == "Third note", f"Expected 'Third note' first, got '{notes[0][0]}'"
        assert notes[1][0] == "Second note"
        assert notes[2][0] == "First note"
    
    def test_get_recent_notes_respects_limit(self, mock_db_file):
        """Limit parameter should restrict number of returned notes."""
        import database
        
        for i in range(10):
            database.add_streak_note(f"Note {i}", ts=1000.0 + i)
        
        notes = database.get_recent_streak_notes(3)
        
        assert len(notes) == 3, f"Expected 3 notes, got {len(notes)}"


# =============================================================================
# TESTS: parse_note_tags
# =============================================================================

class TestParseNoteTags:
    """Tests for hashtag parsing in notes."""
    
    def test_parse_single_tag(self):
        """Should parse a single hashtag."""
        import database
        
        tags, clean = database.parse_note_tags("Fixed bug #done")
        
        assert tags == ['done'], f"Expected ['done'], got {tags}"
        assert clean == "Fixed bug", f"Expected 'Fixed bug', got '{clean}'"
    
    def test_parse_multiple_tags(self):
        """Should parse multiple hashtags."""
        import database
        
        tags, clean = database.parse_note_tags("Working on feature #todo #priority #coding")
        
        assert set(tags) == {'todo', 'priority', 'coding'}
        assert clean == "Working on feature"
    
    def test_parse_no_tags(self):
        """Should handle notes without tags."""
        import database
        
        tags, clean = database.parse_note_tags("Just a regular note")
        
        assert tags == [], f"Expected empty list, got {tags}"
        assert clean == "Just a regular note"
    
    def test_parse_tags_only(self):
        """Should handle note with only tags."""
        import database
        
        tags, clean = database.parse_note_tags("#done #shipped")
        
        assert set(tags) == {'done', 'shipped'}
        assert clean == ""


# =============================================================================
# TESTS: get_notes_summary_for_coaching
# =============================================================================

class TestGetNotesSummaryForCoaching:
    """Tests for the coaching summary function."""
    
    def test_summary_structure(self, mock_db_file):
        """Summary should have expected keys."""
        import database
        
        summary = database.get_notes_summary_for_coaching()
        
        assert 'all_notes' in summary
        assert 'done_items' in summary
        assert 'todo_items' in summary
        assert 'blocked_items' in summary
        assert 'focus_items' in summary
        assert 'tags_count' in summary
    
    def test_summary_categorizes_tags(self, mock_db_file):
        """Summary should categorize notes by their tags."""
        import database
        
        # Get current day boundary timestamp
        now = time.time()
        
        database.add_streak_note("Task completed #done", ts=now)
        database.add_streak_note("Need to fix #todo", ts=now - 100)
        database.add_streak_note("Stuck on auth #blocked", ts=now - 200)
        database.add_streak_note("Main goal #focus", ts=now - 300)
        
        summary = database.get_notes_summary_for_coaching()
        
        assert len(summary['done_items']) >= 1, "Should have done items"
        assert len(summary['todo_items']) >= 1, "Should have todo items"


# =============================================================================
# INTEGRATION TEST: Full save/retrieve cycle
# =============================================================================

class TestIntegration:
    """Integration tests for the complete workflow."""
    
    def test_full_save_retrieve_cycle(self, mock_db_file):
        """Complete workflow: save note, retrieve it, parse tags."""
        import database
        
        # Save a note
        original_note = "Implemented new feature #done #coding"
        note_id = database.add_streak_note(original_note)
        
        assert note_id > 0, "Failed to save note"
        
        # Retrieve recent notes
        notes = database.get_recent_streak_notes(5)
        
        assert len(notes) > 0, "No notes retrieved"
        retrieved_note = notes[0][0]
        assert retrieved_note == original_note
        
        # Parse tags
        tags, clean = database.parse_note_tags(retrieved_note)
        
        assert 'done' in tags
        assert 'coding' in tags
        assert clean == "Implemented new feature"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
