"""Check what databases exist and their contents"""
import sqlite3
import os

print("=" * 60)
print("DATABASE INVENTORY")
print("=" * 60)

# Check activity.db (old location)
if os.path.exists('activity.db'):
    print("\n1. activity.db (ROOT DIRECTORY)")
    print(f"   Size: {os.path.getsize('activity.db'):,} bytes")
    print(f"   Last modified: {os.path.getmtime('activity.db')}")
    conn = sqlite3.connect('activity.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"   Tables: {[t[0] for t in tables]}")
    
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
        count = cursor.fetchone()[0]
        print(f"     - {table[0]}: {count} rows")
    conn.close()
else:
    print("\n1. activity.db (ROOT DIRECTORY) - NOT FOUND")

# Check data/activity.sqlite (new location)
if os.path.exists('data/activity.sqlite'):
    print("\n2. data/activity.sqlite (DATA DIRECTORY)")
    print(f"   Size: {os.path.getsize('data/activity.sqlite'):,} bytes")
    print(f"   Last modified: {os.path.getmtime('data/activity.sqlite')}")
    conn = sqlite3.connect('data/activity.sqlite')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"   Tables: {[t[0] for t in tables]}")
    
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
        count = cursor.fetchone()[0]
        print(f"     - {table[0]}: {count} rows")
    conn.close()
else:
    print("\n2. data/activity.sqlite (DATA DIRECTORY) - NOT FOUND")

print("\n" + "=" * 60)
print("CONCLUSION")
print("=" * 60)

if os.path.exists('activity.db') and os.path.exists('data/activity.sqlite'):
    print("\n⚠️  TWO DATABASES FOUND!")
    print("\nYou have habit data split across two locations:")
    print("  - activity.db (root) - older location")
    print("  - data/activity.sqlite (data/) - newer location")
    print("\nRecommendation: Consolidate into ONE database")
elif os.path.exists('data/activity.sqlite'):
    print("\n✓ ONE DATABASE: data/activity.sqlite")
    print("All data (activities + habits) is in one place!")
elif os.path.exists('activity.db'):
    print("\n✓ ONE DATABASE: activity.db")
    print("Consider moving to data/activity.sqlite for consistency")
else:
    print("\n⚠️  NO DATABASES FOUND!")
