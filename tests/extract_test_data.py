"""
Extract 7 days of activity data from the local database to create a test fixture
for regression testing.

By default, all window titles, URLs, and device hostnames are anonymized so
personal browsing or work history is never written into `tests/fixtures/`.
Pass `--raw` ONLY for strictly local debugging (never commit raw fixtures).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime
from typing import Any

DB_FILE = "data/activity.sqlite"
OUTPUT_DIR = "tests/fixtures"

ANONYMIZED_DEFAULTS: dict[str, tuple[str, str | None, str | None]] = {
    "work": ("main.py - demo_project - Visual Studio Code", None, None),
    "coding": ("app.py - demo_project - Visual Studio Code", None, None),
    "learning": ("Python Documentation - Google Chrome", "https://docs.python.org/3/", "docs.python.org"),
    "vibe": ("agent.py - side_project - Visual Studio Code", None, None),
    "job_search": ("Software Engineer Jobs - LinkedIn - Google Chrome", "https://www.linkedin.com/jobs/", "linkedin.com"),
    "mail": ("Inbox - Webmail - Google Chrome", "https://mail.example.com/", "mail.example.com"),
    "wasted": ("Hacker News - Google Chrome", "https://news.ycombinator.com/", "news.ycombinator.com"),
    "gaming": ("Indie Strategy Game", None, None),
    "family": ("Family Planner - LibreOffice Calc", None, None),
    "idle": ("Idle", None, None),
}


def _anonymize_record(category: str, index: int) -> tuple[str, str | None, str | None]:
    """Return synthetic (window_title, window_url, window_url_short) for a category."""
    cat_key = (category or "").lower()
    if cat_key in ANONYMIZED_DEFAULTS:
        return ANONYMIZED_DEFAULTS[cat_key]
    return (f"Synthetic {category} Window #{index % 5 + 1}", None, None)


def get_last_7_days_data(anonymize: bool = True) -> dict[str, Any] | None:
    """Extract activity data from the last 7 days, anonymizing PII by default."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT DISTINCT local_date
        FROM activity
        WHERE local_date IS NOT NULL
        ORDER BY local_date DESC
        LIMIT 7
        """
    )
    dates = [row["local_date"] for row in cursor.fetchall()]

    if not dates:
        print("No data found in database!")
        conn.close()
        return None

    mode_label = "ANONYMIZED" if anonymize else "RAW (DO NOT COMMIT)"
    print(f"Extracting data ({mode_label}) for dates: {dates}")

    placeholders = ",".join(["?" for _ in dates])
    cursor.execute(
        f"""
        SELECT id, timestamp, category, duration, window_title,
               source, window_url, window_url_short, local_date
        FROM activity
        WHERE local_date IN ({placeholders})
        ORDER BY timestamp
        """,
        dates,
    )

    activities: list[dict[str, Any]] = []
    for idx, row in enumerate(cursor.fetchall(), start=1):
        category = row["category"]
        if anonymize:
            title, url, url_short = _anonymize_record(category, idx)
            source = "DEMO-PC"
            rec_id = idx
        else:
            title = row["window_title"]
            url = row["window_url"]
            url_short = row["window_url_short"]
            source = row["source"]
            rec_id = row["id"]

        activities.append(
            {
                "id": rec_id,
                "timestamp": row["timestamp"],
                "category": category,
                "duration": row["duration"],
                "window_title": title,
                "source": source,
                "window_url": url,
                "window_url_short": url_short,
                "local_date": row["local_date"],
            }
        )

    print(f"Extracted {len(activities)} activity records")

    daily_stats: dict[str, dict[str, Any]] = {}
    for activity in activities:
        date = activity["local_date"]
        cat = activity["category"]
        dur = activity["duration"]

        if date not in daily_stats:
            daily_stats[date] = {"categories": {}, "total_duration": 0}

        daily_stats[date]["categories"][cat] = (
            daily_stats[date]["categories"].get(cat, 0) + dur
        )
        daily_stats[date]["total_duration"] += dur

    fixture_data: dict[str, Any] = {
        "extracted_at": datetime.now().isoformat(),
        "anonymized": anonymize,
        "date_range": {"start": min(dates), "end": max(dates)},
        "record_count": len(activities),
        "activities": activities,
        "daily_summary": daily_stats,
    }

    fixture_path = os.path.join(OUTPUT_DIR, "activity_7days.json")
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(fixture_data, f, indent=2, ensure_ascii=False)

    print(f"Saved fixture to {fixture_path}")

    print("\n" + "=" * 60)
    print("DAILY SUMMARY")
    print("=" * 60)
    for date in sorted(daily_stats.keys()):
        stats = daily_stats[date]
        total_mins = stats["total_duration"] / 60
        print(f"\n{date} (Total: {total_mins:.0f} min)")
        for cat, dur in sorted(stats["categories"].items(), key=lambda x: -x[1]):
            print(f"  {cat}: {dur / 60:.1f} min")

    conn.close()
    return fixture_data


def main() -> None:
    """Parse CLI arguments and run extraction."""
    parser = argparse.ArgumentParser(
        description="Extract 7-day activity fixture (anonymized by default)."
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Export raw unredacted titles/URLs (WARNING: contains PII, never commit!).",
    )
    args = parser.parse_args()
    get_last_7_days_data(anonymize=not args.raw)


if __name__ == "__main__":
    main()
