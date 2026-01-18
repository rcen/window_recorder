#!/usr/bin/env python
"""Test YouTube categorization rules."""
from analytics import Analytics

analytic = Analytics()

# Test cases: (window_title, expected_category)
test_cases = [
    ('Python Tutorial for Beginners - YouTube — Mozilla Firefox', 'learning'),
    ('3Blue1Brown - Linear Algebra Explained - YouTube — Chrome', 'learning'),
    ('freeCodeCamp Full Course - YouTube — Edge', 'learning'),
    ('Machine Learning Crash Course - YouTube — Firefox', 'learning'),
    ('Sunday Worship Service Live - YouTube — Chrome', 'church'),
    ('Bible Study John Chapter 3 - YouTube — Firefox', 'church'),
    ('Taylor Swift Travis Kelce Engagement - YouTube — Firefox', 'wasted'),
    ('Subscriptions - YouTube — Mozilla Firefox', 'wasted'),
    ('US Open Tennis Highlights - YouTube — Chrome', 'wasted'),
    ('www.youtube.com/shorts', 'wasted'),
    ('How to Code in Python - YouTube — Firefox', 'learning'),
    ('LeetCode Problem 1 Solution - YouTube — Chrome', 'learning'),
    ('Fireship 100 Seconds of Code - YouTube — Edge', 'learning'),
    ('NeetCode Dynamic Programming - YouTube — Firefox', 'learning'),
    ('Traversy Media React Crash Course - YouTube — Chrome', 'learning'),
    ('CS50 Harvard Lecture 1 - YouTube — Edge', 'learning'),
    ('Gospel Music Worship - YouTube — Firefox', 'church'),
    ('Sermon by Pastor John - YouTube — Chrome', 'church'),
    ('Cat Videos Compilation - YouTube — Firefox', 'wasted'),
    ('Data Science Full Course - YouTube — Chrome', 'learning'),
]

print('Testing YouTube categorization rules:')
print('=' * 70)
passed = 0
failed = 0

for window_title, expected in test_cases:
    result = analytic.get_cat(window_title)
    status = 'PASS' if result == expected else 'FAIL'
    if result == expected:
        passed += 1
    else:
        failed += 1
    short_title = window_title[:45] + '...' if len(window_title) > 45 else window_title
    print(f'[{status}] "{short_title}"')
    if result != expected:
        print(f'       Expected: {expected}, Got: {result}')

print('=' * 70)
print(f'Results: {passed} passed, {failed} failed')
