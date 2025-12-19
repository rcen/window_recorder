import sqlite3
import time

conn = sqlite3.connect('data/activity.sqlite')
cursor = conn.cursor()

# Check all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', [r[0] for r in cursor.fetchall()])

# Check habit_completions schema
print('\nhabit_completions schema:')
cursor.execute('PRAGMA table_info(habit_completions)')
for row in cursor.fetchall():
    print(row)

# Check streak_notes schema
print('\nstreak_notes schema:')
cursor.execute('PRAGMA table_info(streak_notes)')
for row in cursor.fetchall():
    print(row)

# Try a simple habit insert
print('\nTesting habit insert...')
try:
    cursor.execute('''
        INSERT INTO habit_completions (habit, local_date, completed, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(habit, local_date) DO UPDATE SET
            completed=excluded.completed,
            updated_at=excluded.updated_at
    ''', ('test_habit', '2025-12-03', 1, time.time()))
    conn.commit()
    print('Habit insert: SUCCESS')
    
    # Clean up test
    cursor.execute('DELETE FROM habit_completions WHERE habit=?', ('test_habit',))
    conn.commit()
except Exception as e:
    print(f'Habit insert FAILED: {e}')

# Try habit_completion_events insert
print('\nTesting habit_completion_events insert...')
try:
    cursor.execute('''
        INSERT INTO habit_completion_events (habit, local_date, completed, happened_at)
        VALUES (?, ?, ?, ?)
    ''', ('test_habit', '2025-12-03', 1, time.time()))
    conn.commit()
    print('habit_completion_events insert: SUCCESS')
    
    # Clean up test
    cursor.execute('DELETE FROM habit_completion_events WHERE habit=?', ('test_habit',))
    conn.commit()
except Exception as e:
    print(f'habit_completion_events insert FAILED: {e}')

conn.close()
print('\nDatabase check complete.')
