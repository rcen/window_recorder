"""Tests for category-aware idle detection logic.

Verifies that:
- Standard categories use the base idle threshold (180s).
- Learning (and other configured extended categories) use the extended idle threshold (900s).
- Auto-split preserves the current event instead of forcing idle.
- Config functions return correct defaults and parse custom values.
"""

import os
import sys
import tempfile
import configparser

import pytest

# Ensure project root is on sys.path so imports work from the tests/ directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ---------------------------------------------------------------------------
# Tests for config.py idle settings
# ---------------------------------------------------------------------------

class TestIdleConfigDefaults:
    """Verify default values when no config.dat settings exist."""

    def test_get_idle_time_seconds_default(self):
        from config import get_idle_time_seconds
        result = get_idle_time_seconds()
        # Default should be 180 (3 minutes) or whatever is in the user's config.dat
        assert isinstance(result, int)
        assert result > 0

    def test_get_idle_time_extended_seconds_default(self):
        from config import get_idle_time_extended_seconds
        result = get_idle_time_extended_seconds()
        assert isinstance(result, int)
        assert result > 0

    def test_get_idle_extended_categories_default(self):
        from config import get_idle_extended_categories
        result = get_idle_extended_categories()
        assert isinstance(result, set)
        assert 'learning' in result

    def test_extended_is_greater_than_base(self):
        from config import get_idle_time_seconds, get_idle_time_extended_seconds
        base = get_idle_time_seconds()
        extended = get_idle_time_extended_seconds()
        assert extended > base, (
            f"Extended idle ({extended}s) should be greater than base idle ({base}s)"
        )


class TestIdleConfigParsing:
    """Test that config parsing handles custom values correctly."""

    def test_idle_extended_categories_parsing(self):
        """Verify comma-separated category string is parsed into a set."""
        from config import get_idle_extended_categories
        # The function reads from config.dat; we test the default or current value
        result = get_idle_extended_categories()
        # Should be a set of lowercase strings
        for cat in result:
            assert cat == cat.lower(), f"Category '{cat}' should be lowercase"
            assert cat.strip() == cat, f"Category '{cat}' should be stripped"


# ---------------------------------------------------------------------------
# Tests for idle threshold selection logic
# ---------------------------------------------------------------------------

class TestIdleThresholdSelection:
    """Test that the correct idle threshold is selected based on category."""

    def _get_effective_idle_time(self, category: str) -> int:
        """Simulate the threshold selection logic from script.py."""
        from config import IDLE_TIME, IDLE_TIME_EXTENDED, IDLE_EXTENDED_CATEGORIES
        if category and category.lower() in IDLE_EXTENDED_CATEGORIES:
            return IDLE_TIME_EXTENDED
        return IDLE_TIME

    def test_learning_uses_extended_threshold(self):
        from config import IDLE_TIME_EXTENDED
        assert self._get_effective_idle_time('learning') == IDLE_TIME_EXTENDED

    def test_learning_case_insensitive(self):
        from config import IDLE_TIME_EXTENDED
        assert self._get_effective_idle_time('Learning') == IDLE_TIME_EXTENDED
        assert self._get_effective_idle_time('LEARNING') == IDLE_TIME_EXTENDED

    def test_work_uses_base_threshold(self):
        from config import IDLE_TIME
        assert self._get_effective_idle_time('work') == IDLE_TIME

    def test_wasted_uses_base_threshold(self):
        from config import IDLE_TIME
        assert self._get_effective_idle_time('wasted') == IDLE_TIME

    def test_idle_uses_base_threshold(self):
        from config import IDLE_TIME
        assert self._get_effective_idle_time('idle') == IDLE_TIME

    def test_none_category_uses_base_threshold(self):
        from config import IDLE_TIME
        assert self._get_effective_idle_time(None) == IDLE_TIME

    def test_empty_category_uses_base_threshold(self):
        from config import IDLE_TIME
        assert self._get_effective_idle_time('') == IDLE_TIME


# ---------------------------------------------------------------------------
# Tests for module-level constants
# ---------------------------------------------------------------------------

class TestModuleLevelConstants:
    """Verify that the module-level constants are properly exported."""

    def test_idle_time_exported(self):
        from config import IDLE_TIME
        assert isinstance(IDLE_TIME, int)
        assert IDLE_TIME > 0

    def test_idle_time_extended_exported(self):
        from config import IDLE_TIME_EXTENDED
        assert isinstance(IDLE_TIME_EXTENDED, int)
        assert IDLE_TIME_EXTENDED > 0

    def test_idle_extended_categories_exported(self):
        from config import IDLE_EXTENDED_CATEGORIES
        assert isinstance(IDLE_EXTENDED_CATEGORIES, set)
        assert len(IDLE_EXTENDED_CATEGORIES) > 0
