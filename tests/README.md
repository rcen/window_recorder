# Regression Testing Guide

## Overview

This project includes a regression test suite to catch breaking changes before they're committed.

## Quick Start

```bash
# Run all regression tests
run_tests.bat

# Or using pytest directly
python -m pytest tests/test_regression.py -v
```

## Test Structure

```
tests/
├── __init__.py
├── extract_test_data.py     # Script to extract fresh fixture data
├── fixtures/
│   └── activity_7days.json  # 7 days of activity data (baseline)
└── test_regression.py       # Main regression test suite
```

## Test Categories

### 1. Category Classification Tests
- Verifies `is_productive()`, `is_wasted()`, `is_neutral()`, `is_job_related()` functions
- Ensures categories are mutually exclusive (nothing is both productive AND wasted)

### 2. Aggregate Stats Tests
- Tests the `aggregate_stats()` function for combining related categories
- Verifies work, learning, and other category aggregations

### 3. Fixture Data Integrity Tests
- Validates the baseline fixture data exists and is consistent
- Spot-checks specific daily totals against known values

### 4. Productivity Metrics Tests
- Calculates productive/wasted time from fixture data
- Tests waste ratio calculations

### 5. Database Operations Tests
- Tests queries by date, category aggregation, and date ranges
- Uses a temporary test database created from fixture data

### 6. Category Aliases Tests
- Verifies CATEGORY_ALIASES mapping is correct

## Baseline Metrics

The tests verify against these known baseline values:
- Date range: 2025-12-27 to 2026-01-02 (7 days)
- Total records: 4351 activities
- Spot-check values for specific days/categories

## Updating the Baseline

If you make intentional changes to the data model or add new features:

1. Run the extraction script to get fresh data:
   ```bash
   python tests/extract_test_data.py
   ```

2. Update `BASELINE_METRICS` in `test_regression.py` with new expected values

3. Run tests to verify:
   ```bash
   python -m pytest tests/test_regression.py -v
   ```

## Pre-Commit Workflow

Before committing any changes:

1. Run regression tests: `run_tests.bat`
2. If tests fail, investigate and fix before committing
3. If tests fail due to intentional changes, update the baseline

## Adding New Tests

When adding new features, add corresponding tests:

```python
class TestNewFeature:
    """Test new feature functionality."""
    
    def test_new_function(self):
        """Test the new function works correctly."""
        result = new_function(input_data)
        assert result == expected_output
```
