# -*- coding: utf-8 -*-
"""
One-time backfill script: generate AI coach daily summaries for the previous 4 days
and store them in data/coach_briefings.json so they show up in the dashboard.

Usage:
    python backfill_coach_briefings.py

Notes:
- Uses the existing GeminiCoach fallback summary if the API key is missing.
- Skips days with no activity data.
- Stores only daily summaries (not morning briefings) for the selected days.
"""
import datetime
import json
from pathlib import Path

import pandas as pd

import database
from config import TIMEZONE
from gemini_coach import GeminiCoach
from productivity_agent import ProductivityAgent


def _aggregate_minutes(df: pd.DataFrame) -> dict:
    """Aggregate a day's durations into minutes by category."""
    if df is None or df.empty:
        return {}
    return (df.groupby('category')['duration'].sum() / 60.0).to_dict()


def _is_rest_day(date_obj: datetime.date) -> tuple[bool, str]:
    """Determine rest day flags for a given date (weekend)."""
    if date_obj.weekday() == 5:
        return True, "Saturday"
    if date_obj.weekday() == 6:
        return True, "Sunday"
    return False, ""


def generate_backfill(days: int = 4) -> None:
    agent = ProductivityAgent()
    coach = agent.coach
    if not coach:
        print("AI Coach not available; nothing to backfill.")
        return

    goals_dict = {cat: g.daily_target_minutes for cat, g in agent.goals.items()}

    tz = datetime.timezone.utc
    today_local = datetime.datetime.now(datetime.timezone.utc).astimezone().date()

    for offset in range(1, days + 1):
        target_date = today_local - datetime.timedelta(days=offset)
        date_str = target_date.strftime('%Y-%m-%d')

        df = database.fetch_log_for_day(date_str)
        stats = _aggregate_minutes(df)
        if not stats:
            print(f"[skip] No activity for {date_str}")
            continue

        is_rest, rest_reason = _is_rest_day(target_date)

        summary_text = coach.get_daily_summary(stats=stats, goals=goals_dict)
        if not summary_text:
            print(f"[warn] No summary generated for {date_str}")
            continue

        coach._save_digest(
            date_str=date_str,
            kind="daily_summary",
            text=summary_text,
            is_rest_day=is_rest,
            rest_reason=rest_reason,
            source="ai",
        )

        print(f"[ok] Saved summary for {date_str} ({'rest' if is_rest else 'workday'})")


if __name__ == "__main__":
    generate_backfill(days=4)
