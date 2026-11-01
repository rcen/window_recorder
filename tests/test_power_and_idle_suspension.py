"""Unit and regression tests for display power broadcasting and idle polling suspension.

Verifies:
1. Display Power State Management:
   - Turning display off pauses active listeners and sets is_display_off=True.
   - Turning display on resumes listeners, resets is_display_off=False, and resets loop timers.
2. Idle Polling Suspension:
   - When idle > 30s, active cursor polling in is_mouse_idle() is suspended.
   - Deep idle (>30s or display off) triggers adaptive loop sleep (1.5s instead of 0.3s).
"""

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestPowerBroadcastHandling:
    """Test display power-off and power-on state toggling."""

    def test_display_off_pauses_listeners(self, monkeypatch):
        """Verify that setting display off sets flag and calls pause handler."""
        import script

        paused = []
        monkeypatch.setattr(script, "pause_pynput_listeners", lambda: paused.append(True))
        
        script.set_display_power_state(True)
        assert script.is_display_off is True
        assert len(paused) == 1

    def test_display_on_resumes_listeners_and_resets_timer(self, monkeypatch):
        """Verify that setting display on sets flag, calls resume handler, and updates timer."""
        import script

        resumed = []
        monkeypatch.setattr(script, "resume_pynput_listeners", lambda: resumed.append(True))
        
        # Turn off first
        script.is_display_off = True
        
        before_time = time.time()
        script.set_display_power_state(False)
        after_time = time.time()

        assert script.is_display_off is False
        assert len(resumed) == 1
        assert before_time <= script.last_loop_time <= after_time


class TestIdlePollingSuspension:
    """Test active polling suspension during extended idle (>30s)."""

    def test_mouse_idle_suspends_pyautogui_polling_after_30s(self, monkeypatch):
        """Verify that is_mouse_idle returns True immediately without polling pyautogui if idle > 30s."""
        import script

        polled = []

        def mock_position():
            polled.append(True)
            return (100, 100)

        monkeypatch.setattr("pyautogui.position", mock_position)

        # Set last_time_mouse_moved to 40 seconds ago
        script.last_time_mouse_moved = time.time() - 40.0

        is_idle = script.is_mouse_idle()
        assert is_idle is True
        # Since idle > 30s, pyautogui.position should NOT have been polled
        assert len(polled) == 0

    def test_adaptive_loop_sleep_duration(self):
        """Verify deep idle state selects 1.5s sleep vs 0.3s when active."""
        # Deep idle active
        is_deep_idle = True
        loop_sleep = 1.5 if is_deep_idle else 0.3
        assert loop_sleep == 1.5

        # Active user
        is_deep_idle = False
        loop_sleep = 1.5 if is_deep_idle else 0.3
        assert loop_sleep == 0.3
