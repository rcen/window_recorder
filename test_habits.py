"""
Quick test to verify habit tracking is working correctly.
Run this script to test the entire habit tracking flow.
"""
import database
import requests
import json

print("=" * 60)
print("HABIT TRACKING SYSTEM TEST")
print("=" * 60)

# Initialize database
print("\n1. Initializing database...")
database.initialize_database()
print("   ✓ Database initialized")

# Test habits from config
print("\n2. Loading habits from config...")
from config import HABITS
if not HABITS:
    print("   ✗ ERROR: No habits found in config.dat [HABITS] section")
    exit(1)
print(f"   ✓ Found {len(HABITS)} habits:")
for name, color in HABITS:
    print(f"     - {name} ({color})")

# Test server connectivity
print("\n3. Testing habit server connectivity...")
server_url = "http://127.0.0.1:8042/habits"
try:
    response = requests.get(f"{server_url}?start=2025-10-14&end=2025-10-14", timeout=2)
    if response.status_code == 200:
        print(f"   ✓ Server responding at {server_url}")
        data = response.json()
        print(f"   ✓ Server returned {len(data.get('completions', {}))} habit records")
    else:
        print(f"   ✗ Server returned status {response.status_code}")
        exit(1)
except requests.exceptions.ConnectionError:
    print(f"   ✗ ERROR: Cannot connect to {server_url}")
    print("\n   The habit server is NOT running!")
    print("\n   Please start it with:")
    print("     start_habit_server.bat")
    print("   OR")
    print("     C:\\projects\\window_recorder\\winrecord_env\\Scripts\\python.exe habit_server.py")
    exit(1)
except Exception as e:
    print(f"   ✗ ERROR: {e}")
    exit(1)

# Test habit completion POST
print("\n4. Testing habit completion recording...")
test_habit = HABITS[0][0]  # Use first configured habit
test_date = "2025-10-14"
payload = {
    "habit": test_habit,
    "date": test_date,
    "completed": True
}

try:
    response = requests.post(
        server_url,
        json=payload,
        timeout=2
    )
    if response.status_code == 200:
        result = response.json()
        print(f"   ✓ Successfully recorded: {test_habit}")
        print(f"   ✓ Date: {result.get('date')}")
        print(f"   ✓ Completed: {result.get('completed')}")
        if result.get('updated_at'):
            print(f"   ✓ Updated at: {result.get('updated_at')}")
    else:
        print(f"   ✗ Server returned status {response.status_code}")
        exit(1)
except Exception as e:
    print(f"   ✗ ERROR: {e}")
    exit(1)

# Verify database persistence
print("\n5. Verifying database persistence...")
completions = database.get_habit_completions(
    habits=[test_habit],
    start_date=test_date,
    end_date=test_date
)
if test_habit in completions and test_date in completions[test_habit]:
    record = completions[test_habit][test_date]
    if record.get('completed'):
        print(f"   ✓ Habit '{test_habit}' is marked complete for {test_date}")
        if record.get('updated_at'):
            print(f"   ✓ Timestamp: {record.get('updated_at')}")
    else:
        print(f"   ✗ Habit '{test_habit}' is NOT marked complete")
        exit(1)
else:
    print(f"   ✗ ERROR: Habit '{test_habit}' not found in database")
    exit(1)

# Test GET endpoint with actual data
print("\n6. Testing habit retrieval...")
try:
    response = requests.get(f"{server_url}?start={test_date}&end={test_date}", timeout=2)
    if response.status_code == 200:
        data = response.json()
        completions_data = data.get('completions', {})
        if test_habit in completions_data and test_date in completions_data[test_habit]:
            entry = completions_data[test_habit][test_date]
            if isinstance(entry, dict) and entry.get('completed'):
                print(f"   ✓ Successfully retrieved habit completion")
                print(f"   ✓ Completed: {entry.get('completed')}")
                print(f"   ✓ Updated at: {entry.get('updated_at')}")
            else:
                print(f"   ✗ Habit data format incorrect: {entry}")
                exit(1)
        else:
            print(f"   ✗ Habit '{test_habit}' not in server response")
            exit(1)
    else:
        print(f"   ✗ Server returned status {response.status_code}")
        exit(1)
except Exception as e:
    print(f"   ✗ ERROR: {e}")
    exit(1)

print("\n" + "=" * 60)
print("✓ ALL TESTS PASSED!")
print("=" * 60)
print("\nYour habit tracking system is working correctly!")
print("\nNext steps:")
print("1. Run: python analytics.py")
print("2. Open: html/index.html in your browser")
print("3. Click the habit checkboxes - they should persist!")
print("4. Watch the streak counters increment!")
print("\nThe checkboxes will work because the server is running.")
print("=" * 60)
