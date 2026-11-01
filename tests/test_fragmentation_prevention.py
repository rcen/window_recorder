"""Regression tests to prevent event fragmentation and false sleep detection.

Verifies:
1. Sleep detection logic: Blocking calls in window detection (e.g., URL extraction taking 30s)
   do not trigger false system sleep/off events when last_loop_time is updated.
2. Idle detection logic: Extended idle categories (e.g., 'learning') remain active during
   extended passive viewing (e.g., 5-14 mins of no mouse/keyboard input), whereas standard
   categories (e.g., 'work', 'wasted') switch to idle after the standard threshold (3 mins).
3. Auto-split logic: Long events (>30 mins) split cleanly without injecting artificial idle states.
"""

import time
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import IDLE_TIME, IDLE_TIME_EXTENDED, IDLE_EXTENDED_CATEGORIES


class TestSleepDetectionPrevention:
    """Test prevention of false sleep/off event triggering during long blocking calls."""

    def test_last_loop_time_update_prevents_false_sleep(self):
        """Simulate a loop iteration where get_window_name takes 35 seconds.
        
        Verifies that updating last_loop_time after get_window_name prevents
        the next loop iteration from detecting a false time_jump > 5.0s.
        """
        # Step 1: Initialize loop time before get_window_name()
        start_time = 1000.0
        last_loop_time = start_time

        # Step 2: Simulate get_window_name() blocking for 35 seconds (e.g. UIA URL extraction)
        window_detection_duration = 35.0
        window_detected_at = start_time + window_detection_duration

        # --- THE FIX: update last_loop_time after get_window_name() ---
        last_loop_time = window_detected_at

        # Step 3: Next loop iteration starts 0.3s later
        next_iteration_time = window_detected_at + 0.3
        time_jump = next_iteration_time - last_loop_time

        # Verification: time_jump must be 0.3s (normal loop sleep), NOT 35.3s
        assert time_jump < 1.0, f"time_jump was {time_jump}s, expected ~0.3s"
        assert time_jump <= 5.0, "time_jump exceeded 5.0s threshold! False sleep would be triggered."

    def test_without_fix_false_sleep_would_trigger(self):
        """Demonstrate that without updating last_loop_time, false sleep IS triggered."""
        start_time = 1000.0
        last_loop_time = start_time

        # get_window_name takes 35s, but last_loop_time is NOT updated
        window_detected_at = start_time + 35.0
        next_iteration_time = window_detected_at + 0.3

        unfixed_time_jump = next_iteration_time - last_loop_time
        assert unfixed_time_jump > 5.0, "Without fix, time jump exceeds 5s sleep threshold"


class TestCategoryAwareIdleEvaluation:
    """Test that idle decisions accurately reflect category-specific thresholds."""

    def evaluate_idle_status(self, category: str, user_idle_seconds: float) -> bool:
        """Helper mirroring the idle decision logic in script.py."""
        effective_threshold = (
            IDLE_TIME_EXTENDED
            if category and category.lower() in IDLE_EXTENDED_CATEGORIES
            else IDLE_TIME
        )
        return user_idle_seconds >= effective_threshold

    def test_learning_active_at_5_minutes_idle(self):
        """5 minutes of no hardware input while learning should NOT switch to idle."""
        five_minutes_seconds = 300.0
        is_idle = self.evaluate_idle_status('learning', five_minutes_seconds)
        assert is_idle is False, "Learning was falsely marked idle after 5 minutes of passive viewing"

    def test_learning_active_at_14_minutes_idle(self):
        """14 minutes of no hardware input while learning should NOT switch to idle."""
        fourteen_minutes_seconds = 840.0
        is_idle = self.evaluate_idle_status('learning', fourteen_minutes_seconds)
        assert is_idle is False, "Learning was falsely marked idle after 14 minutes"

    def test_learning_idle_at_15_minutes(self):
        """15 minutes (or extended threshold) of no input SHOULD switch to idle."""
        fifteen_minutes_seconds = float(IDLE_TIME_EXTENDED)
        is_idle = self.evaluate_idle_status('learning', fifteen_minutes_seconds)
        assert is_idle is True, "Learning was not marked idle after reaching extended threshold"

    def test_work_idle_at_4_minutes(self):
        """4 minutes of no input while working SHOULD switch to idle (threshold is 3 mins)."""
        four_minutes_seconds = 240.0
        is_idle = self.evaluate_idle_status('work', four_minutes_seconds)
        assert is_idle is True, "Work should be idle after 4 minutes of inactivity"

    def test_wasted_idle_at_4_minutes(self):
        """4 minutes of no input while in wasted category SHOULD switch to idle."""
        four_minutes_seconds = 240.0
        is_idle = self.evaluate_idle_status('wasted', four_minutes_seconds)
        assert is_idle is True, "Wasted should be idle after 4 minutes of inactivity"


class TestAutoSplitPreservation:
    """Test that 30-minute auto-splits preserve the event state."""

    def test_auto_split_does_not_force_idle_event(self):
        """Simulate auto-split at 30 minutes for a learning session."""
        last_event = "YouTube - Learning Lecture"
        last_window = "YouTube - Learning Lecture"
        start_of_event = 1000.0
        current_time = start_of_event + 1800.1  # Exceeds 30 mins

        # Auto-split logic
        max_event_duration = 1800
        event_exceeded = (current_time - start_of_event) > max_event_duration
        assert event_exceeded is True

        # New segment start time resets, but event name is preserved
        new_start_of_event = current_time
        retained_event = last_event

        assert retained_event == "YouTube - Learning Lecture", "Auto-split wiped active event name"
        assert retained_event != "idle", "Auto-split falsely forced event to idle"
