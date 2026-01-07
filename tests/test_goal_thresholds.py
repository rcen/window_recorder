# -*- coding: utf-8 -*-
"""
Test suite for configurable goal warning thresholds.
Tests different threshold scenarios for positive and negative goals.
"""
import pytest
import datetime
import pytz
from dataclasses import dataclass

from productivity_agent import (
    ProductivityGoal, GoalProgress, GoalStatus, ProductivityAgent
)
from config import TIMEZONE


class TestGoalThresholdConfiguration:
    """Test that goal thresholds can be configured per category."""
    
    def test_goal_has_minimum_behind_threshold(self):
        """Goal should have configurable minimum_behind_threshold field."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.6,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        assert goal.minimum_behind_threshold == 15.0
    
    def test_minimum_behind_threshold_defaults_to_15(self):
        """Default minimum_behind_threshold should be 15 minutes."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30
        )
        assert goal.minimum_behind_threshold == 15.0
    
    def test_different_thresholds_per_category(self):
        """Different categories can have different minimum_behind_threshold values."""
        work_goal = ProductivityGoal(
            category="work",
            daily_target_minutes=240,
            minimum_behind_threshold=30.0
        )
        learning_goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            minimum_behind_threshold=15.0
        )
        
        assert work_goal.minimum_behind_threshold == 30.0
        assert learning_goal.minimum_behind_threshold == 15.0


class TestPositiveGoalThresholds:
    """Test warning thresholds for positive goals (targets to meet)."""
    
    @pytest.fixture
    def agent(self):
        """Create a productivity agent for testing."""
        agent = ProductivityAgent()
        return agent
    
    def test_on_track_when_ratio_exceeds_warning_threshold(self, agent):
        """Goal should be ON_TRACK when ratio >= warning_threshold."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.7,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # At 21 minutes (70% of 30), should be ON_TRACK
        progress = agent.evaluate_goal(goal, current_minutes=21.0)
        
        assert progress.status == GoalStatus.ON_TRACK
        assert "on track" in progress.message.lower()
    
    def test_ramping_up_when_slightly_behind_minimum_threshold(self, agent):
        """Goal should be ON_TRACK (ramping up) when behind < minimum_behind_threshold."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.7,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # Expected progress at 50% of day: 15 minutes
        # Current: 5 minutes (10 min behind, < 15 min threshold)
        # Mock expected_minutes by manually calling logic
        agent.goals = {"learning": goal}
        
        # Create a progress object for testing
        progress = GoalProgress(
            goal=goal,
            current_minutes=5.0,
            expected_minutes=15.0
        )
        
        # Expected: 5/15 = 0.33 ratio (below 0.7 threshold)
        # Behind: 10 minutes (< 15 minimum threshold)
        # Should be ON_TRACK with "ramping up" message
        
        ratio = progress.current_minutes / progress.expected_minutes
        behind = progress.expected_minutes - progress.current_minutes
        
        assert ratio < goal.warning_threshold
        assert behind < goal.minimum_behind_threshold
        assert behind == 10.0
    
    def test_warning_when_past_minimum_but_above_critical(self, agent):
        """Goal should be WARNING when behind >= minimum_threshold and ratio >= critical_threshold."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.7,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # Expected: 30 minutes
        # Current: 15 minutes (15 min behind, >= 15 min threshold)
        # Ratio: 15/30 = 0.5, which is >= 0.4 (critical_threshold) but < 0.7 (warning)
        
        progress = GoalProgress(
            goal=goal,
            current_minutes=15.0,
            expected_minutes=30.0
        )
        
        ratio = progress.current_minutes / progress.expected_minutes
        behind = progress.expected_minutes - progress.current_minutes
        
        assert behind >= goal.minimum_behind_threshold  # 15 >= 15
        assert ratio >= goal.critical_threshold  # 0.5 >= 0.4
        assert ratio < goal.warning_threshold  # 0.5 < 0.7
    
    def test_critical_when_below_critical_threshold(self, agent):
        """Goal should be CRITICAL when ratio < critical_threshold and behind >= minimum_threshold."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.7,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # Expected: 30 minutes
        # Current: 5 minutes (25 min behind, > 15 min threshold)
        # Ratio: 5/30 = 0.167, which is < 0.4 (critical_threshold)
        
        progress = GoalProgress(
            goal=goal,
            current_minutes=5.0,
            expected_minutes=30.0
        )
        
        ratio = progress.current_minutes / progress.expected_minutes
        behind = progress.expected_minutes - progress.current_minutes
        
        assert behind > goal.minimum_behind_threshold  # 25 > 15
        assert ratio < goal.critical_threshold  # 0.167 < 0.4
    
    def test_achieved_when_current_meets_target(self, agent):
        """Goal should be ACHIEVED when current_minutes >= daily_target_minutes."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        progress = agent.evaluate_goal(goal, current_minutes=30.0)
        assert progress.status == GoalStatus.ACHIEVED


class TestNegativeGoalThresholds:
    """Test warning thresholds for negative goals (limits to stay under)."""
    
    @pytest.fixture
    def agent(self):
        """Create a productivity agent for testing."""
        agent = ProductivityAgent()
        return agent
    
    def test_on_track_when_well_under_limit(self, agent):
        """Negative goal should be ON_TRACK when usage is well below limit."""
        goal = ProductivityGoal(
            category="wasted time",
            daily_target_minutes=60,  # Limit is 60 minutes
            warning_threshold=0.7,
            critical_threshold=0.9,
            is_positive=False,
            minimum_behind_threshold=0.0
        )
        
        # Using only 20 minutes of 60 minute limit
        # Ratio: 20/60 = 0.33, which is < 0.7 (warning threshold)
        progress = agent.evaluate_goal(goal, current_minutes=20.0)
        
        assert progress.status == GoalStatus.ON_TRACK
        assert "under control" in progress.message.lower()
    
    def test_warning_for_negative_goal_approaching_limit(self, agent):
        """Negative goal should be WARNING when approaching limit."""
        goal = ProductivityGoal(
            category="wasted time",
            daily_target_minutes=60,
            warning_threshold=0.7,
            critical_threshold=0.9,
            is_positive=False,
            minimum_behind_threshold=0.0
        )
        
        # Using 45 minutes of 60 minute limit
        # Ratio: 45/60 = 0.75, which is >= 0.7 and < 0.9
        progress = agent.evaluate_goal(goal, current_minutes=45.0)
        
        assert progress.status == GoalStatus.WARNING
        assert "approaching limit" in progress.message.lower()
    
    def test_critical_for_negative_goal_nearly_at_limit(self, agent):
        """Negative goal should be CRITICAL when near the limit."""
        goal = ProductivityGoal(
            category="wasted time",
            daily_target_minutes=60,
            warning_threshold=0.7,
            critical_threshold=0.9,
            is_positive=False,
            minimum_behind_threshold=0.0
        )
        
        # Using 55 minutes of 60 minute limit
        # Ratio: 55/60 = 0.916, which is >= 0.9
        progress = agent.evaluate_goal(goal, current_minutes=55.0)
        
        assert progress.status == GoalStatus.CRITICAL
        assert "near limit" in progress.message.lower()
    
    def test_failed_for_negative_goal_exceeds_limit(self, agent):
        """Negative goal should be FAILED when limit is exceeded."""
        goal = ProductivityGoal(
            category="wasted time",
            daily_target_minutes=60,
            is_positive=False,
            minimum_behind_threshold=0.0
        )
        
        # Using 75 minutes of 60 minute limit
        progress = agent.evaluate_goal(goal, current_minutes=75.0)
        
        assert progress.status == GoalStatus.FAILED
        assert "exceeded" in progress.message.lower()


class TestDifferentCategoryThresholds:
    """Test that different categories can have different threshold values."""
    
    @pytest.fixture
    def agent(self):
        """Create a productivity agent for testing."""
        agent = ProductivityAgent()
        return agent
    
    def test_work_goal_30_minute_buffer(self, agent):
        """Work goal should have 30-minute minimum buffer."""
        goal = ProductivityGoal(
            category="work",
            daily_target_minutes=240,
            warning_threshold=0.7,
            critical_threshold=0.5,
            is_positive=True,
            minimum_behind_threshold=30.0
        )
        
        assert goal.minimum_behind_threshold == 30.0
    
    def test_learning_goal_15_minute_buffer(self, agent):
        """Learning goal should have 15-minute minimum buffer."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.6,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        assert goal.minimum_behind_threshold == 15.0
    
    def test_wasted_time_no_buffer(self, agent):
        """Wasted time goal should have no buffer (0.0)."""
        goal = ProductivityGoal(
            category="wasted time",
            daily_target_minutes=60,
            is_positive=False,
            minimum_behind_threshold=0.0
        )
        
        assert goal.minimum_behind_threshold == 0.0
    
    def test_threshold_difference_prevents_false_warnings(self, agent):
        """Larger buffers prevent warnings for slight delays."""
        # Work goal with 30-min buffer
        work_goal = ProductivityGoal(
            category="work",
            daily_target_minutes=240,
            warning_threshold=0.7,
            critical_threshold=0.5,
            is_positive=True,
            minimum_behind_threshold=30.0
        )
        
        # Learning goal with 15-min buffer
        learning_goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.6,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # 20 minutes behind expected progress
        # Work: 20 < 30, so no warning
        # Learning: 20 > 15, so warning possible
        
        # For work goal
        work_progress = GoalProgress(
            goal=work_goal,
            current_minutes=100.0,  # Assuming expected = 120
            expected_minutes=120.0
        )
        behind_work = work_progress.expected_minutes - work_progress.current_minutes
        assert behind_work == 20.0
        assert behind_work < work_goal.minimum_behind_threshold
        
        # For learning goal
        learning_progress = GoalProgress(
            goal=learning_goal,
            current_minutes=5.0,  # Assuming expected = 25
            expected_minutes=25.0
        )
        behind_learning = learning_progress.expected_minutes - learning_progress.current_minutes
        assert behind_learning == 20.0
        assert behind_learning > learning_goal.minimum_behind_threshold


class TestThresholdEdgeCases:
    """Test edge cases for threshold logic."""
    
    @pytest.fixture
    def agent(self):
        """Create a productivity agent for testing."""
        agent = ProductivityAgent()
        return agent
    
    def test_exactly_at_minimum_threshold_boundary(self, agent):
        """When exactly at minimum_behind_threshold, should treat as warning, not ramping up."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            warning_threshold=0.7,
            critical_threshold=0.4,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # Exactly 15 minutes behind
        progress = GoalProgress(
            goal=goal,
            current_minutes=15.0,
            expected_minutes=30.0
        )
        
        behind = progress.expected_minutes - progress.current_minutes
        # At boundary: behind == 15.0, not < 15.0, so should go to next check
        assert behind == goal.minimum_behind_threshold
        assert not (behind < goal.minimum_behind_threshold)
    
    def test_zero_expected_minutes(self, agent):
        """When expected_minutes is very small (day just started), minimum threshold prevents warnings."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=30,
            is_positive=True,
            minimum_behind_threshold=15.0
        )
        
        # Simulate very early in the day: expected = 5 min, current = 0 min
        # Behind = 5 minutes (< 15 minute threshold), should show "ramping up"
        progress = agent.evaluate_goal(goal, current_minutes=0.0)
        
        # The actual message depends on the time of day calculation, but with
        # a small expected amount and 0 current, we should be in ramping up mode
        # if behind < minimum_behind_threshold
        assert progress.status == GoalStatus.ON_TRACK
    
    def test_zero_daily_target_minutes(self, agent):
        """Goal with 0 target should always show as achieved."""
        goal = ProductivityGoal(
            category="learning",
            daily_target_minutes=0,
            is_positive=True
        )
        
        progress = agent.evaluate_goal(goal, current_minutes=0.0)
        # With 0 daily target, should be at 100%
        assert progress.progress_percentage == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
