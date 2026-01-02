"""
Regression Test Suite for Window Recorder
==========================================
Tests core functionality against known baseline data to ensure
code changes don't break existing behavior.

Run with: python -m pytest tests/test_regression.py -v
Or:       python tests/test_regression.py
"""
import json
import os
import sys
import sqlite3
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

# Import modules to test
from categories import (
    PRODUCTIVE_CATS, WASTED_CATS, NEUTRAL_CATS, JOB_CATS, VIBE_CATS,
    is_productive, is_wasted, is_job_related, is_neutral,
    aggregate_stats, get_priority, CATEGORY_ALIASES
)

FIXTURE_DIR = Path(__file__).parent / 'fixtures'
FIXTURE_FILE = FIXTURE_DIR / 'activity_7days.json'


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(scope='module')
def fixture_data():
    """Load the 7-day activity fixture data."""
    with open(FIXTURE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def daily_stats(fixture_data):
    """Get daily statistics from fixture."""
    return fixture_data['daily_summary']


@pytest.fixture(scope='module')
def all_categories(fixture_data):
    """Get all unique categories from fixture data."""
    cats = set()
    for activity in fixture_data['activities']:
        cats.add(activity['category'])
    return cats


@pytest.fixture(scope='module')
def test_db(fixture_data):
    """Create a temporary test database with fixture data."""
    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test_activity.sqlite')
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create table
    cursor.execute('''
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
    ''')
    
    # Insert fixture data
    for act in fixture_data['activities']:
        cursor.execute('''
            INSERT INTO activity (timestamp, category, duration, window_title, 
                                  source, window_url, window_url_short, local_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            act['timestamp'], act['category'], act['duration'], act['window_title'],
            act.get('source'), act.get('window_url'), act.get('window_url_short'), act['local_date']
        ))
    
    conn.commit()
    conn.close()
    
    yield db_path
    
    # Cleanup
    shutil.rmtree(temp_dir)


# =============================================================================
# BASELINE METRICS (calculated from fixture data)
# =============================================================================

# These are the expected metrics calculated from the 7-day fixture
# If tests fail, either the baseline needs updating or there's a regression

BASELINE_METRICS = {
    'date_range': {
        'start': '2025-12-27',
        'end': '2026-01-02'
    },
    'total_records': 4351,
    'days_count': 7,
    
    # Expected category classifications
    'productive_categories': {'work', 'learning', 'vibe_coding', 'mail', 'church', 'docs', 'think', 'job search                                                            linkedin'},
    'wasted_categories': {'wasted', 'gaming'},
    'neutral_categories': {'idle', 'family'},
    
    # Expected daily totals (in seconds) for spot-checking
    'daily_totals': {
        '2025-12-27': {'work': 2652, 'wasted': 6042},
        '2025-12-31': {'work': 8976, 'learning': 1476},
        '2026-01-01': {'learning': 6876, 'vibe_coding': 5064},
    }
}


# =============================================================================
# CATEGORY CLASSIFICATION TESTS
# =============================================================================

class TestCategoryClassification:
    """Test that category classification functions work correctly."""
    
    def test_productive_categories_defined(self):
        """Ensure productive categories are defined."""
        assert len(PRODUCTIVE_CATS) > 0
        assert 'work' in PRODUCTIVE_CATS
        assert 'learning' in PRODUCTIVE_CATS
    
    def test_wasted_categories_defined(self):
        """Ensure wasted categories are defined."""
        assert len(WASTED_CATS) > 0
        assert 'wasted' in WASTED_CATS
        assert 'gaming' in WASTED_CATS
    
    def test_is_productive_function(self):
        """Test is_productive() returns correct values."""
        assert is_productive('work') == True
        assert is_productive('Work') == True  # case insensitive
        assert is_productive('WORK') == True
        assert is_productive('learning') == True
        assert is_productive('vibe_coding') == True
        assert is_productive('idle') == False
        assert is_productive('wasted') == False
        assert is_productive('gaming') == False
    
    def test_is_wasted_function(self):
        """Test is_wasted() returns correct values."""
        assert is_wasted('wasted') == True
        assert is_wasted('Wasted') == True  # case insensitive
        assert is_wasted('gaming') == True
        assert is_wasted('youtube') == True
        assert is_wasted('work') == False
        assert is_wasted('idle') == False
    
    def test_is_neutral_function(self):
        """Test is_neutral() for non-productive, non-wasted categories."""
        assert is_neutral('idle') == True
        assert is_neutral('family') == True
        assert is_neutral('work') == False
        assert is_neutral('wasted') == False
    
    def test_is_job_related_function(self):
        """Test job search category detection."""
        assert is_job_related('job search') == True
        assert is_job_related('job') == True
        assert is_job_related('career') == True
        assert is_job_related('interview') == True
        assert is_job_related('work') == False
    
    def test_category_mutual_exclusivity(self):
        """Ensure no category is both productive and wasted."""
        overlap = PRODUCTIVE_CATS & WASTED_CATS
        assert len(overlap) == 0, f"Categories in both productive and wasted: {overlap}"


# =============================================================================
# AGGREGATE STATS TESTS
# =============================================================================

class TestAggregateStats:
    """Test the aggregate_stats function for combining related categories."""
    
    def test_aggregate_work_categories(self):
        """Test that work-related categories are aggregated correctly."""
        stats = {
            'work': 100,
            'coding': 50,
            'programming': 30,
            'vibe_coding': 20  # Note: vibe_coding is NOT in work aliases
        }
        total = aggregate_stats(stats, 'work')
        assert total == 180  # 100 + 50 + 30 (vibe_coding not included)
    
    def test_aggregate_with_missing_categories(self):
        """Test aggregation when some categories are missing."""
        stats = {'work': 100}
        total = aggregate_stats(stats, 'work')
        assert total == 100
    
    def test_aggregate_empty_stats(self):
        """Test aggregation with empty stats."""
        stats = {}
        total = aggregate_stats(stats, 'work')
        assert total == 0
    
    def test_aggregate_learning(self):
        """Test learning category aggregation."""
        stats = {'learning': 60, 'docs': 30}
        # Learning should include learning and docs
        total = aggregate_stats(stats, 'learning')
        assert total >= 60  # At minimum the learning value


# =============================================================================
# FIXTURE DATA VALIDATION TESTS
# =============================================================================

class TestFixtureDataIntegrity:
    """Validate the fixture data matches expected baseline."""
    
    def test_fixture_file_exists(self):
        """Ensure fixture file exists."""
        assert FIXTURE_FILE.exists(), f"Fixture file not found: {FIXTURE_FILE}"
    
    def test_fixture_record_count(self, fixture_data):
        """Verify record count matches baseline."""
        assert fixture_data['record_count'] == BASELINE_METRICS['total_records']
    
    def test_fixture_date_range(self, fixture_data):
        """Verify date range matches baseline."""
        assert fixture_data['date_range']['start'] == BASELINE_METRICS['date_range']['start']
        assert fixture_data['date_range']['end'] == BASELINE_METRICS['date_range']['end']
    
    def test_fixture_has_all_days(self, daily_stats):
        """Verify all 7 days are present."""
        assert len(daily_stats) == BASELINE_METRICS['days_count']
    
    def test_daily_totals_spot_check(self, daily_stats):
        """Spot check specific daily totals against baseline."""
        for date, expected in BASELINE_METRICS['daily_totals'].items():
            assert date in daily_stats, f"Missing date: {date}"
            for cat, expected_dur in expected.items():
                actual = daily_stats[date]['categories'].get(cat, 0)
                # Allow 1% tolerance for rounding
                assert abs(actual - expected_dur) < expected_dur * 0.01, \
                    f"Mismatch for {date}/{cat}: expected {expected_dur}, got {actual}"


# =============================================================================
# PRODUCTIVITY METRICS TESTS
# =============================================================================

class TestProductivityMetrics:
    """Test productivity calculation logic."""
    
    def test_calculate_productive_time(self, daily_stats, all_categories):
        """Calculate total productive time across all days."""
        total_productive = 0
        for date, stats in daily_stats.items():
            for cat, dur in stats['categories'].items():
                if is_productive(cat):
                    total_productive += dur
        
        # Should have some productive time
        assert total_productive > 0
        # Convert to minutes for readability
        productive_mins = total_productive / 60
        print(f"\nTotal productive time: {productive_mins:.0f} minutes")
    
    def test_calculate_wasted_time(self, daily_stats):
        """Calculate total wasted time across all days."""
        total_wasted = 0
        for date, stats in daily_stats.items():
            for cat, dur in stats['categories'].items():
                if is_wasted(cat):
                    total_wasted += dur
        
        wasted_mins = total_wasted / 60
        print(f"\nTotal wasted time: {wasted_mins:.0f} minutes")
        assert total_wasted >= 0
    
    def test_waste_ratio_calculation(self, daily_stats):
        """Test waste ratio calculation for each day."""
        for date, stats in daily_stats.items():
            productive = sum(dur for cat, dur in stats['categories'].items() if is_productive(cat))
            wasted = sum(dur for cat, dur in stats['categories'].items() if is_wasted(cat))
            
            if productive + wasted > 0:
                waste_ratio = (wasted / (productive + wasted)) * 100
                # Waste ratio should be between 0 and 100
                assert 0 <= waste_ratio <= 100
                print(f"{date}: waste_ratio = {waste_ratio:.1f}%")


# =============================================================================
# DATABASE OPERATIONS TESTS
# =============================================================================

class TestDatabaseOperations:
    """Test database query operations."""
    
    def test_query_by_date(self, test_db):
        """Test querying activities by date."""
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM activity WHERE local_date = '2025-12-31'")
        count = cursor.fetchone()[0]
        
        assert count > 0
        conn.close()
    
    def test_aggregate_by_category(self, test_db):
        """Test aggregating duration by category."""
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT category, SUM(duration) as total
            FROM activity
            WHERE local_date = '2025-12-31'
            GROUP BY category
            ORDER BY total DESC
        """)
        
        results = cursor.fetchall()
        assert len(results) > 0
        
        # First result should have the most time
        top_category, top_duration = results[0]
        assert top_duration > 0
        
        conn.close()
    
    def test_query_date_range(self, test_db):
        """Test querying activities in a date range."""
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM activity 
            WHERE local_date BETWEEN '2025-12-28' AND '2025-12-30'
        """)
        count = cursor.fetchone()[0]
        
        assert count > 0
        conn.close()


# =============================================================================
# CATEGORY ALIASES TESTS
# =============================================================================

class TestCategoryAliases:
    """Test category alias mappings."""
    
    def test_aliases_defined(self):
        """Ensure category aliases are defined."""
        assert len(CATEGORY_ALIASES) > 0
    
    def test_work_aliases(self):
        """Test work-related aliases."""
        # CATEGORY_ALIASES maps category -> list of aliases
        assert 'work' in CATEGORY_ALIASES
        work_aliases = CATEGORY_ALIASES['work']
        assert isinstance(work_aliases, list)
        assert 'work' in work_aliases
        assert 'coding' in work_aliases
        assert 'programming' in work_aliases


# =============================================================================
# MAIN
# =============================================================================

def run_tests():
    """Run all tests and return exit code."""
    import subprocess
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', __file__, '-v', '--tb=short'],
        cwd=PROJECT_ROOT
    )
    return result.returncode


if __name__ == '__main__':
    # Check if pytest is available
    try:
        import pytest
        exit_code = pytest.main([__file__, '-v', '--tb=short'])
        sys.exit(exit_code)
    except ImportError:
        print("pytest not installed. Running basic tests...")
        # Basic smoke tests without pytest
        print("\n=== Running Basic Tests ===\n")
        
        # Test category functions
        assert is_productive('work'), "is_productive('work') should be True"
        assert is_wasted('gaming'), "is_wasted('gaming') should be True"
        assert not is_productive('idle'), "is_productive('idle') should be False"
        print("✓ Category functions work correctly")
        
        # Test aggregate_stats
        stats = {'work': 100, 'coding': 50}
        total = aggregate_stats(stats, 'work')
        assert total >= 100, "aggregate_stats should sum work-related categories"
        print("✓ aggregate_stats works correctly")
        
        # Test fixture loading
        with open(FIXTURE_FILE) as f:
            data = json.load(f)
        assert data['record_count'] == BASELINE_METRICS['total_records']
        print("✓ Fixture data loads correctly")
        
        print("\n=== All Basic Tests Passed ===")
