"""
Database Migration: Rename 'job search' to 'job_search'
========================================================
Also renames 'current job' to 'current_job' for consistency.

This migration updates the category column in the activity table.

Run with: python migrations/migrate_job_search_rename.py
"""
import sqlite3
import os
from datetime import datetime

DB_FILE = 'data/activity.sqlite'

# Category renames to apply
RENAMES = {
    'job search': 'job_search',
    'current job': 'current_job',
}


def backup_database():
    """Create a backup before migration."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f'data/activity_backup_{timestamp}.sqlite'
    
    if os.path.exists(DB_FILE):
        import shutil
        shutil.copy2(DB_FILE, backup_file)
        print(f"✓ Created backup: {backup_file}")
        return backup_file
    return None


def get_affected_records():
    """Count records that will be affected by the migration."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    counts = {}
    for old_cat in RENAMES.keys():
        # Exact match
        cursor.execute(
            "SELECT COUNT(*) FROM activity WHERE category = ?",
            (old_cat,)
        )
        exact = cursor.fetchone()[0]
        
        # Substring match (for malformed categories)
        cursor.execute(
            "SELECT COUNT(*) FROM activity WHERE category LIKE ? AND category != ?",
            (f'%{old_cat}%', old_cat)
        )
        partial = cursor.fetchone()[0]
        
        counts[old_cat] = {'exact': exact, 'partial': partial}
    
    conn.close()
    return counts


def migrate_categories(dry_run=True):
    """
    Migrate category names from 'job search' to 'job_search'.
    
    Args:
        dry_run: If True, only show what would be changed without making changes.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    total_updated = 0
    
    for old_cat, new_cat in RENAMES.items():
        # 1. Exact match updates
        if dry_run:
            cursor.execute(
                "SELECT COUNT(*) FROM activity WHERE category = ?",
                (old_cat,)
            )
            count = cursor.fetchone()[0]
            print(f"  Would update {count} records: '{old_cat}' -> '{new_cat}'")
        else:
            cursor.execute(
                "UPDATE activity SET category = ? WHERE category = ?",
                (new_cat, old_cat)
            )
            count = cursor.rowcount
            print(f"  ✓ Updated {count} records: '{old_cat}' -> '{new_cat}'")
        total_updated += count
        
        # 2. Substring replacements for malformed categories
        # e.g., "job search     linkedin: job search" -> "job_search"
        if dry_run:
            cursor.execute(
                "SELECT DISTINCT category FROM activity WHERE category LIKE ? AND category != ?",
                (f'%{old_cat}%', old_cat)
            )
            malformed = cursor.fetchall()
            for (cat,) in malformed:
                cursor.execute(
                    "SELECT COUNT(*) FROM activity WHERE category = ?",
                    (cat,)
                )
                mal_count = cursor.fetchone()[0]
                print(f"  Would update {mal_count} malformed records: '{cat[:50]}...' -> '{new_cat}'")
                total_updated += mal_count
        else:
            # Update malformed categories containing the old name
            cursor.execute(
                "SELECT DISTINCT category FROM activity WHERE category LIKE ? AND category != ?",
                (f'%{old_cat}%', old_cat)
            )
            malformed = cursor.fetchall()
            for (cat,) in malformed:
                cursor.execute(
                    "UPDATE activity SET category = ? WHERE category = ?",
                    (new_cat, cat)
                )
                mal_count = cursor.rowcount
                print(f"  ✓ Fixed {mal_count} malformed records: '{cat[:50]}...' -> '{new_cat}'")
                total_updated += mal_count
    
    if not dry_run:
        conn.commit()
        print(f"\n✓ Migration complete! Total records updated: {total_updated}")
    else:
        print(f"\n[DRY RUN] Would update {total_updated} total records")
    
    conn.close()
    return total_updated


def verify_migration():
    """Verify no old category names remain."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    issues = []
    for old_cat in RENAMES.keys():
        cursor.execute(
            "SELECT COUNT(*) FROM activity WHERE category LIKE ?",
            (f'%{old_cat}%',)
        )
        count = cursor.fetchone()[0]
        if count > 0:
            issues.append(f"Found {count} records still containing '{old_cat}'")
    
    conn.close()
    
    if issues:
        print("\n⚠️ Verification failed:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("\n✓ Verification passed! No old category names found.")
        return True


def show_current_job_categories():
    """Show all job-related categories in the database."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT category, COUNT(*) as count
        FROM activity
        WHERE category LIKE '%job%' 
           OR category LIKE '%linkedin%'
           OR category LIKE '%indeed%'
           OR category LIKE '%career%'
        GROUP BY category
        ORDER BY count DESC
    """)
    
    print("\nJob-related categories in database:")
    print("-" * 60)
    for cat, count in cursor.fetchall():
        display_cat = cat[:55] + '...' if len(cat) > 55 else cat
        print(f"  {count:5d} | {display_cat}")
    
    conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Migrate job search category names')
    parser.add_argument('--execute', action='store_true', 
                        help='Actually perform the migration (default is dry run)')
    parser.add_argument('--no-backup', action='store_true',
                        help='Skip creating a backup (not recommended)')
    parser.add_argument('--show', action='store_true',
                        help='Just show current job-related categories')
    args = parser.parse_args()
    
    if args.show:
        show_current_job_categories()
        exit(0)
    
    print("=" * 60)
    print("Database Migration: Rename 'job search' -> 'job_search'")
    print("=" * 60)
    
    if not os.path.exists(DB_FILE):
        print(f"Error: Database not found at {DB_FILE}")
        exit(1)
    
    # Show current state
    show_current_job_categories()
    
    # Show what will be affected
    print("\nRecords to migrate:")
    counts = get_affected_records()
    for cat, c in counts.items():
        print(f"  '{cat}': {c['exact']} exact + {c['partial']} partial matches")
    
    if args.execute:
        print("\n" + "=" * 60)
        print("EXECUTING MIGRATION")
        print("=" * 60)
        
        if not args.no_backup:
            backup_database()
        
        migrate_categories(dry_run=False)
        verify_migration()
        
        print("\nPost-migration state:")
        show_current_job_categories()
    else:
        print("\n" + "=" * 60)
        print("DRY RUN (use --execute to apply changes)")
        print("=" * 60)
        migrate_categories(dry_run=True)
        print("\nTo apply these changes, run:")
        print("  python migrations/migrate_job_search_rename.py --execute")
