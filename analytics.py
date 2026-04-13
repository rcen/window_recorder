# -*- coding: utf-8 -*-
"""
Created on Tue Aug 14 08:36:12 2018

@author: Nicolaj Baramsky
"""
import os
import datetime
import pandas as pd
import configparser
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numbers
from pathlib import Path
import re
import shutil
import time
import bisect
import json
import textwrap
import pytz
import plotly.express as px
import database
from config import TIMEZONE, DAY_BOUNDARY_HOUR, HABITS
from categories import (
    PRODUCTIVE_CATS, WASTED_CATS, RATIO_DISPLAY_CATS, CATEGORY_PRIORITY,
    RECENT_ACTIVITY_PRODUCTIVE, RECENT_ACTIVITY_DISTRACTED,
    is_productive, is_wasted,
    should_display_in_activity_summary,
)
import sqlite3
import requests
import html
from urllib.parse import urlparse
import stock_prices
from productivity_agent import ProductivityAgent, GoalStatus, HOLIDAYS

def main():
    reanalyze_all()

def sec2str(dur):
    dur_hr = int(np.floor(dur/3600))
    dur_min = int(np.floor((dur-dur_hr*3600)/60))
    dur_sec = int(dur%60)
    return [dur_hr,dur_min,dur_sec]

def Sec2hms(seconds):
    hr = int(np.floor(seconds / 3600))
    min = int(np.floor((seconds-hr*3600) / 60))
    sec = int(seconds%60)
    return hr, min, sec

def shorten_url_display(url, max_length=80):
    """Produce a concise, human-friendly URL label for reports."""
    if not url:
        return None

    try:
        parsed = urlparse(url)
        if not parsed.netloc and parsed.path:
            parsed = urlparse(f"http://{url}")

        netloc = parsed.netloc or parsed.path
        if not netloc:
            return url if len(url) <= max_length else f"{url[:max_length-3]}..."

        path_parts = [part for part in parsed.path.split('/') if part]
        short_path = ''
        if path_parts:
            displayed_parts = path_parts[:2]
            short_path = '/' + '/'.join(displayed_parts)
            if len(path_parts) > 2:
                short_path += '/...'

        short_url = f"{netloc}{short_path}"

        if parsed.query:
            short_url += '?...'

        if len(short_url) > max_length:
            short_url = f"{short_url[:max_length-3]}..."

        return short_url
    except Exception:
        return url if len(url) <= max_length else f"{url[:max_length-3]}..."

def resolve_conflicts(df):
    """
    Resolves overlapping activities from different sources based on category priority.
    This new implementation is more robust and handles complex overlap scenarios.
    """
    if df.empty:
        return pd.DataFrame()

    # If no source column or only one source, no conflicts to resolve.
    if 'source' not in df.columns or df['source'].nunique() <= 1:
        return df.sort_values(by='start_time').reset_index(drop=True)

    df['priority'] = df['category'].map(CATEGORY_PRIORITY).fillna(99)

    # Sort events by start time, then by priority to process them in order.
    sorted_events = df.sort_values(by=['start_time', 'priority']).to_dict('records')

    if not sorted_events:
        return pd.DataFrame()

    # This list will hold the final, non-overlapping events.
    resolved_timeline = []
    
    for event in sorted_events:
        # Keep track of the parts of the current event that need to be added.
        # Initially, this is the whole event.
        events_to_add = [event]
        
        # This will hold the timeline after considering the current event.
        new_resolved_timeline = []
        
        # Iterate through the already resolved events to check for overlaps.
        for existing_event in resolved_timeline:
            
            # This will hold the parts of the new event that don't get overwritten.
            remaining_parts = []
            
            for part_to_add in events_to_add:
                # --- Overlap Check ---
                # (StartA < EndB) and (EndA > StartB)
                is_overlapping = (part_to_add['start_time'] < existing_event['end_time'] and 
                                  part_to_add['end_time'] > existing_event['start_time'])

                if not is_overlapping:
                    remaining_parts.append(part_to_add)
                    continue

                # --- Overlap exists, resolve based on priority ---
                
                # Split the new event part into up to three pieces:
                # 1. The part before the existing event.
                if part_to_add['start_time'] < existing_event['start_time']:
                    before_part = part_to_add.copy()
                    before_part['end_time'] = existing_event['start_time']
                    remaining_parts.append(before_part)

                # 2. The part after the existing event.
                if part_to_add['end_time'] > existing_event['end_time']:
                    after_part = part_to_add.copy()
                    after_part['start_time'] = existing_event['end_time']
                    remaining_parts.append(after_part)
            
            # The parts that survived the overlap check are carried over.
            events_to_add = remaining_parts
            
            # The existing event is kept as it has higher priority (it was processed earlier).
            new_resolved_timeline.append(existing_event)
        
        # Add the surviving parts of the new event and the existing resolved events.
        resolved_timeline = sorted(new_resolved_timeline + events_to_add, key=lambda x: x['start_time'])

    if not resolved_timeline:
        return pd.DataFrame()

    # --- Post-processing: Merge adjacent events of the same category ---
    
    # Filter out any tiny fragments that might have been created.
    cleaned_timeline = [e for e in resolved_timeline if (e['end_time'] - e['start_time']).total_seconds() > 1]
    
    if not cleaned_timeline:
        return pd.DataFrame()

    merged_timeline = [cleaned_timeline[0]]
    for current_event in cleaned_timeline[1:]:
        last_merged = merged_timeline[-1]
        
        # Check if categories match and events are contiguous (or very close).
        if (current_event['category'] == last_merged['category'] and
            abs((current_event['start_time'] - last_merged['end_time']).total_seconds()) < 2):
            # Merge by extending the end time of the last event.
            last_merged['end_time'] = current_event['end_time']
        else:
            merged_timeline.append(current_event)

    if not merged_timeline:
        return pd.DataFrame()

    # Convert back to a DataFrame, recalculate duration, and clean up.
    result_df = pd.DataFrame(merged_timeline)
    result_df['duration'] = (result_df['end_time'] - result_df['start_time']).dt.total_seconds()
    
    if 'priority' in result_df.columns:
        result_df = result_df.drop(columns=['priority'])
    
    return result_df.sort_values(by='start_time').reset_index(drop=True)

def reanalyze_all():
    if not os.path.isdir('data'):
        os.mkdir('data')
    
    analytic = Analytics()
    
    # Check for future data before processing
    analytic.check_for_future_data()
    
    log_list, _ = analytic.get_log_list()

    for logfile in log_list:
        print('Processing analysis for:', logfile)
        # The following functions now read from the database
        analytic.print_review(logfile)
        analytic.create_interactive_timeline(logfile)
        analytic.print_pi_chart(logfile)
    
    # Create the main HTML report
    analytic.create_html()


def _format_coach_html(text: str) -> str:
    """Convert plain-text coach output (with • bullets) into well-formatted HTML.

    Bullet lines are rendered as a proper <ul> so wrapped text stays
    indented under the bullet character, not flush-left.
    """
    lines = text.splitlines()
    parts: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        # Detect bullet lines: • or - at the start
        if stripped.startswith('•') or (stripped.startswith('- ') and not stripped.startswith('---')):
            if not in_list:
                parts.append('<ul style="margin:4px 0 4px 8px; padding-left:1.2em; list-style:disc;">')
                in_list = True
            # Remove the leading bullet/dash character
            item_text = stripped.lstrip('•-').strip()
            parts.append(f'<li style="margin-bottom:3px;">{html.escape(item_text)}</li>')
        else:
            if in_list:
                parts.append('</ul>')
                in_list = False
            if stripped:
                parts.append(f'<p style="margin:2px 0;">{html.escape(stripped)}</p>')

    if in_list:
        parts.append('</ul>')

    return '\n'.join(parts)


class Analytics():

    def __init__(self):
        self.path_data = 'data'
        self.config = self._load_config()
        self.string_cats = self.config.items('CATEGORIES')
        self._raw_color_list = self.config.items('COLORS')
        self.color_list, self._color_flags = self._parse_colors_with_flags(self._raw_color_list)
        self._activity_summary_hidden_cats = {
            cat
            for cat, flags in (self._color_flags or {}).items()
            if ('no_show_summary' in flags) or ('hide_summary' in flags) or ('hide_activity_summary' in flags)
        }
        self.proj_list = self.config.items('PROJECTS')
        self.cache_path = 'data/analysis_cache.json'
        self.analysis_cache = self._load_analysis_cache()
        self._context_switch_cache = {}
        self.last_activity_count = 0  # Track activity count to detect changes
        self.last_update_timestamp = 0  # Track when we last updated
        database.initialize_database()

    @staticmethod
    def _parse_colors_with_flags(color_items: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, set[str]]]:
        """Parse [COLORS] items.

        Supports values like:
          work: #4954EA
          no_cat: #387FF7, no_show_summary
        """
        parsed: list[tuple[str, str]] = []
        flags_by_cat: dict[str, set[str]] = {}
        for cat, raw in (color_items or []):
            raw_str = (raw or '').strip()
            parts = [p.strip() for p in raw_str.split(',') if p.strip()]
            color = parts[0] if parts else raw_str
            flags = {p.lower() for p in parts[1:]} if len(parts) > 1 else set()
            parsed.append((cat, color))
            flags_by_cat[str(cat).strip().lower()] = flags
        return parsed, flags_by_cat

    def _is_hidden_in_activity_summary(self, category: str) -> bool:
        cat = (category or '').strip().lower()
        if not cat:
            return False
        for hidden in (self._activity_summary_hidden_cats or set()):
            if cat == hidden or cat.startswith(hidden + ':') or cat.startswith(hidden + ' '):
                return True
        return False

    @staticmethod
    def _ensure_url_columns(df):
        if df is None or df.empty:
            return df

        df = df.copy()

        if 'window_url' not in df.columns:
            df['window_url'] = None

        if 'window_url_short' not in df.columns:
            df['window_url_short'] = df['window_url'].apply(shorten_url_display)
        else:
            mask = df['window_url_short'].isna() & df['window_url'].notna()
            if mask.any():
                df.loc[mask, 'window_url_short'] = df.loc[mask, 'window_url'].apply(shorten_url_display)

        df['url_display'] = df['window_url_short'].fillna(df['window_url']).fillna('')
        return df

    def _get_and_prepare_day_df(self, date_str):
        """
        Fetches the log for a given day and prepares it for analysis.
        - Converts UTC timestamps to localized, timezone-aware datetime objects.
        - Calculates start_time and end_time.
        """
        tz = pytz.timezone(TIMEZONE)
        df = database.fetch_log_for_day(date_str)
        if df.empty:
            return pd.DataFrame()

        # Filter out 'start' events, as they are not real activities
        if 'window_title' in df.columns:
            df = df[df['window_title'].str.strip().str.lower() != 'start'].copy()

        df = self._ensure_url_columns(df)

        # Correctly interpret the timestamp as UTC, then convert to local time
        # .floor('us') truncates nanosecond sub-precision that Plotly cannot serialize
        df['end_time'] = pd.to_datetime(df['timestamp'], unit='s').dt.floor('us').dt.tz_localize('UTC').dt.tz_convert(tz)
        df['start_time'] = df.apply(lambda row: row['end_time'] - datetime.timedelta(seconds=row['duration']), axis=1)
        return df

    def _calculate_context_switching(self, date_str: str, *, ignore_idle: bool = True) -> tuple[int, float, float]:
        """Return (switch_count, switches_per_hour, active_seconds) for a given logical day.

        Definition: a switch occurs when consecutive activity rows (sorted by time)
        have different categories. By default, idle rows are excluded.
        """
        df = self._get_and_prepare_day_df(date_str)
        if df is None or df.empty:
            return 0, 0.0, 0.0

        df = resolve_conflicts(df)

        if 'category' not in df.columns or 'duration' not in df.columns:
            return 0, 0.0, 0.0

        df = df.copy()
        df['category'] = df['category'].fillna('').astype(str)

        if ignore_idle:
            df = df[df['category'].str.strip().str.lower() != 'idle']

        if df.empty:
            return 0, 0.0, 0.0

        if 'start_time' in df.columns:
            df = df.sort_values('start_time')
        else:
            df = df.sort_values('timestamp')

        cats = df['category'].tolist()
        prev = None
        switches = 0
        for cat in cats:
            if prev is None:
                prev = cat
                continue
            if cat != prev:
                switches += 1
                prev = cat

        active_seconds = float(df['duration'].sum()) if not df['duration'].empty else 0.0
        switches_per_hour = (switches / (active_seconds / 3600.0)) if active_seconds > 0 else 0.0
        return switches, switches_per_hour, active_seconds

    def _get_recent_context_switches(
        self,
        date_str: str,
        *,
        max_switches: int = 5,
        ignore_idle: bool = True,
    ) -> list[dict]:
        """Return the most recent context switches for a day.

        Each entry is a dict with:
            from_cat, to_cat, time (datetime), is_focus_to_distraction
        Ordered newest-first. Returns at most *max_switches* entries.
        """
        df = self._get_and_prepare_day_df(date_str)
        if df is None or df.empty:
            return []

        df = resolve_conflicts(df)
        if df is None or df.empty:
            return []

        if 'category' not in df.columns or 'duration' not in df.columns:
            return []

        df = df.copy()
        df['category'] = df['category'].fillna('').astype(str)
        if ignore_idle:
            df = df[df['category'].str.strip().str.lower() != 'idle']
        if df.empty:
            return []

        sort_col = 'start_time' if 'start_time' in df.columns else 'timestamp'
        df = df.sort_values(sort_col)

        cats = df['category'].tolist()
        # Use end_time of the row we switch TO as the switch timestamp
        times = df['end_time'].tolist() if 'end_time' in df.columns else [None] * len(cats)

        switches: list[dict] = []
        prev = None
        for i, cat in enumerate(cats):
            if prev is None:
                prev = cat
                continue
            if cat != prev:
                from_productive = is_productive(prev)
                to_wasted = is_wasted(cat)
                switches.append({
                    'from_cat': prev,
                    'to_cat': cat,
                    'time': times[i],
                    'is_focus_to_distraction': from_productive and to_wasted,
                })
                prev = cat
            else:
                prev = cat

        # Return newest first, capped
        return list(reversed(switches[-max_switches:]))

    def _calculate_context_switching_window(
        self,
        date_str: str,
        window_end: "datetime.datetime",
        *,
        window_seconds: int = 3600,
        ignore_idle: bool = True,
    ) -> tuple[int, float | None, float]:
        """Return (switch_count, switches_per_active_hour, active_seconds) for a rolling time window.

        Implementation note: this is performance-sensitive; it uses a cached per-day
        time series (sorted by end_time) with prefix sums instead of re-resolving
        conflicts for every window.
        """
        series = self._get_context_switch_series(date_str, ignore_idle=ignore_idle)
        if series is None:
            return 0, None, 0.0

        end_ts = float(window_end.timestamp())
        switches, active_seconds = self._window_switch_stats_from_series(series, end_ts, window_seconds)
        per_active_hour = (switches / (active_seconds / 3600.0)) if active_seconds > 0 else None
        return switches, per_active_hour, active_seconds

    def _calculate_lowest_context_switching_rate(
        self,
        date_str: str,
        *,
        window_seconds: int = 3600,
        min_active_seconds: int = 600,
    ) -> float | None:
        """Return the lowest rolling-window switches-per-active-hour for a day.

        This uses a prefix-sum series with a 2-pointer window to avoid O(n^2) behavior.
        """
        series = self._get_context_switch_series(date_str, ignore_idle=True)
        if series is None:
            return None

        end_times = series['end_ts']
        prefix_dur = series['prefix_dur']
        prefix_sw = series['prefix_sw']
        n = len(end_times)
        if n == 0:
            return None

        lo = 0
        lowest = None
        for hi_idx in range(n):
            end_ts = end_times[hi_idx]
            cutoff = end_ts - float(window_seconds)
            while lo < n and end_times[lo] <= cutoff:
                lo += 1

            hi = hi_idx + 1
            active_seconds = float(prefix_dur[hi] - prefix_dur[lo])
            if active_seconds < float(min_active_seconds) or active_seconds <= 0:
                continue

            if hi - lo >= 2:
                switches = int(prefix_sw[hi] - prefix_sw[lo + 1])
            else:
                switches = 0

            # Ignore "warm-up" windows with zero switches. These are common early in the day
            # (or during long single-category stretches) and would otherwise dominate the
            # "Lowest" metric with 0/hr, which is usually not meaningful.
            if switches <= 0:
                continue

            rate = switches / (active_seconds / 3600.0)
            if lowest is None or rate < lowest:
                lowest = rate

        return lowest

    def _get_context_switch_series(self, date_str: str, *, ignore_idle: bool = True):
        key = (date_str, ignore_idle)
        if key in self._context_switch_cache:
            return self._context_switch_cache[key]

        df = self._get_and_prepare_day_df(date_str)
        if df is None or df.empty:
            self._context_switch_cache[key] = None
            return None

        df = resolve_conflicts(df)
        if df is None or df.empty:
            self._context_switch_cache[key] = None
            return None

        if 'end_time' not in df.columns or 'duration' not in df.columns or 'category' not in df.columns:
            self._context_switch_cache[key] = None
            return None

        df = df.copy()
        df['category'] = df['category'].fillna('').astype(str)
        if ignore_idle:
            df = df[df['category'].str.strip().str.lower() != 'idle']
        if df.empty:
            self._context_switch_cache[key] = None
            return None

        df = df.sort_values('end_time')
        end_ts = [float(dt.timestamp()) for dt in df['end_time'].tolist()]
        durations = [max(0.0, float(x)) for x in df['duration'].tolist()]
        cats = df['category'].tolist()

        switch_flags = [0]
        for i in range(1, len(cats)):
            switch_flags.append(1 if cats[i] != cats[i - 1] else 0)

        prefix_dur = [0.0]
        prefix_sw = [0]
        for d, s in zip(durations, switch_flags):
            prefix_dur.append(prefix_dur[-1] + d)
            prefix_sw.append(prefix_sw[-1] + int(s))

        series = {
            'end_ts': end_ts,
            'dur': durations,
            'switch': switch_flags,
            'prefix_dur': prefix_dur,
            'prefix_sw': prefix_sw,
        }
        self._context_switch_cache[key] = series
        return series

    @staticmethod
    def _window_switch_stats_from_series(series, window_end_ts: float, window_seconds: int) -> tuple[int, float]:
        end_ts = series['end_ts']
        prefix_dur = series['prefix_dur']
        prefix_sw = series['prefix_sw']

        hi = bisect.bisect_right(end_ts, window_end_ts)
        lo = bisect.bisect_right(end_ts, window_end_ts - float(window_seconds))
        if hi <= lo:
            return 0, 0.0

        active_seconds = float(prefix_dur[hi] - prefix_dur[lo])
        if hi - lo >= 2:
            switches = int(prefix_sw[hi] - prefix_sw[lo + 1])
        else:
            switches = 0
        return switches, active_seconds

    def _load_config(self):
        path_config = 'config.dat'
        if not os.path.isfile(path_config):
            with open(path_config, 'w', encoding='utf-8') as file:
                config_template="""
[SETTINGS]
image_folder = figs/pictures
md_folder = os.path.expanduser('~/Documents/Notes')

[CATEGORIES]
spyder: programming
stackoverflow: programming
stackexchange: programming
github: programming
eingabeaufforderung: programming
texstudio: documents
word: documents
adobe\u00a0acrobat\u00a0reader: documents
thunderbird: mail
whatsapp: wasted time
mozilla: wasted.time
chrome: wasted time
mingw64: programming
sperrbildschirm: idle

[COLORS]
programming: #4954EA
documents: #F68D15
mail: #72ACF1
wasted time: #F64438
idle: #837F7F

[PROJECTS]
test:
"""
                file.write(config_template)
        if not os.path.isdir('figs'):
            os.mkdir('figs')
        if not os.path.isdir('figs/pie'):
            os.mkdir('figs/pie')
        if not os.path.isdir('html/timelines'):
            os.makedirs('html/timelines')
        if not os.path.isdir('figs/pictures'):
            os.mkdir('figs/pictures')
        
        config = configparser.ConfigParser()
        config.read(path_config, encoding='utf-8')
        
        # Add settings section if it doesn't exist
        if not config.has_section('SETTINGS'):
            config.add_section('SETTINGS')
            config.set('SETTINGS', 'image_folder', 'figs/pictures')
            config.set('SETTINGS', 'md_folder', 'C:/Users/YourUser/Documents/Notes')
            with open(path_config, 'w', encoding='utf-8') as configfile:
                config.write(configfile)

        # custom logic to handle duplicates in CATEGORIES
        categories = []
        with open(path_config, 'r', encoding='utf-8') as f:
            in_categories_section = False
            for line in f:
                line = line.strip()
                if line == '[CATEGORIES]':
                    in_categories_section = True
                    continue
                elif line.startswith('['):
                    in_categories_section = False
                    continue
                
                # Skip comment lines and empty lines
                if not line or line.startswith('#'):
                    continue
                
                if in_categories_section and ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    if key not in [k for k, v in categories]:
                        categories.append((key, value.strip()))
        
        config['CATEGORIES'] = {}
        for key, value in categories:
            config['CATEGORIES'][key] = value
            
        return config

    def _load_analysis_cache(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_analysis_cache(self):
        try:
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.analysis_cache, f, indent=4)
        except IOError:
            print("Error: Could not save analysis cache.")

    def create_interactive_timeline(self, logfile=''):
        if "mod.log" in logfile:
            return

        tz = pytz.timezone(TIMEZONE)
        date_str = logfile.replace('.csv', '')
        path = f'html/timelines/{date_str}.html'

        # --- Intelligent Chart Generation ---
        today_date = datetime.datetime.now(tz).date()
        try:
            chart_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return  # Invalid date format in logfile name

        # If the chart is for a past day and it already exists, skip redrawing.
        if chart_date < today_date and os.path.exists(path):
            return
        # --- End of Optimization ---

        # --- Fetch data for the adjusted day using day boundary configuration ---
        current_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Get data for the target day and the next day to cover activities that span the boundary
        df1 = self._get_and_prepare_day_df(date_str)
        next_date_str = (current_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        df2 = self._get_and_prepare_day_df(next_date_str)
        
        df = pd.concat([df1, df2], ignore_index=True)
        if df.empty:
            return

        # --- Filter and clamp data to the adjusted day range using day boundary hour ---
        # Start of adjusted day: day_boundary_hour on the current date
        start_of_adjusted_day = pd.Timestamp.combine(
            current_date, 
            datetime.time(hour=DAY_BOUNDARY_HOUR)
        ).tz_localize(tz)
        
        # End of adjusted day: day_boundary_hour on the next date  
        end_of_adjusted_day = pd.Timestamp.combine(
            current_date + datetime.timedelta(days=1),
            datetime.time(hour=DAY_BOUNDARY_HOUR)
        ).tz_localize(tz)

        # Filter activities that overlap with the adjusted day
        df = df[(df['start_time'] < end_of_adjusted_day) & (df['end_time'] > start_of_adjusted_day)].copy()
        if df.empty:
            return

        # Clamp start and end times to the boundaries of the adjusted day
        df['start_time'] = df['start_time'].clip(lower=start_of_adjusted_day)
        df['end_time'] = df['end_time'].clip(upper=end_of_adjusted_day)

        # Resolve conflicts on the filtered and clamped data
        df = resolve_conflicts(df)
        if df.empty:
            return

        df = self._ensure_url_columns(df)
        if df.empty:
            return

        df['URL'] = df['url_display'].replace('', None).fillna('—')
        df['Duration (min)'] = (df['duration'] / 60).round(1)

        # --- Exclude 'idle' category from the timeline ---
        if 'category' in df.columns:
            df = df[df['category'].str.lower() != 'idle']
        
        if df.empty:
            return
        # --- End of exclusion ---

        # Get colors
        color_map = dict(self.color_list)

        fig = px.timeline(
            df,
            x_start="start_time",
            x_end="end_time",
            y="category",
            color="category",
            hover_name="window_title",
            hover_data={
                "URL": True,
                "Duration (min)": ':.1f'
            },
            color_discrete_map=color_map,
            title=f'Activity Timeline for {date_str}'
        )

        fig.update_yaxes(categoryorder='total ascending')

        # Set x-axis to autoscale
        fig.update_layout(
            xaxis_title="Time of Day",
            yaxis_title="Category",
            showlegend=False,
            xaxis=dict(
                tickformat="%H:%M"
            )
        )

        fig.write_html(path, full_html=False, include_plotlyjs='cdn')
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] Interactive timeline chart saved as {path}')


    def analyze(self, logfile=''):
        if "mod.log" in logfile:
            return None, None, None, None

        tz = pytz.timezone(TIMEZONE)
        today_str = datetime.datetime.now(tz).strftime('%Y-%m-%d')

        if logfile == '':
            date_str = today_str
            logfile = f"{date_str}.csv"
        else:
            date_str = logfile.replace('.csv', '')

        # For past days, use the cache if available
        if date_str != today_str and logfile in self.analysis_cache:
            cached_data = self.analysis_cache[logfile]
            # The date is stored as a string in JSON, convert it back
            date_obj = datetime.datetime.fromisoformat(cached_data[2]) if cached_data[2] else None
            return cached_data[0], cached_data[1], date_obj, None

        # For today or for uncached past days, fetch and prepare data consistently
        df = self._get_and_prepare_day_df(date_str)
        if df.empty:
            return [], [], None, None

        # Now, resolve conflicts on the correctly prepared DataFrame
        df = resolve_conflicts(df)

        # Perform the summary analysis on the resolved data
        summary = df.groupby('category')['duration'].sum().reset_index()
        u_cats = summary['category'].tolist()
        u_dur = summary['duration'].tolist()

        if not u_cats:
            return [], [], None, None

        date = datetime.datetime.strptime(date_str, '%Y-%m-%d')

        # Do not cache data for future dates
        if date.date() > datetime.datetime.now(tz).date():
            return u_cats, u_dur, date, None
        
        # Store in cache. Convert date to string for JSON serialization.
        self.analysis_cache[logfile] = (u_cats, u_dur, date.isoformat(), None)
        
        return u_cats, u_dur, date, None



    def print_pi_chart(self, logfile=''):
        # --- Intelligent Chart Generation ---
        tz = pytz.timezone(TIMEZONE)
        today_date = datetime.datetime.now(tz).date()

        if logfile:
            date_str = logfile.replace('.csv', '')
            try:
                chart_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return # Invalid date format
        else:
            date_str = today_date.strftime('%Y-%m-%d')
            chart_date = today_date
        
        path = f'figs/pie/{date_str}.png'

        # If the chart is for a past day and it already exists, skip redrawing.
        if chart_date < today_date and os.path.exists(path):
            return
        # --- End of Optimization ---

        if "mod.log" in logfile:
            return

        u_cats, u_dur, date, _ = self.analyze(logfile)
        
        if not date or not any(d > 0 for d in u_dur):
            return

        # Filter out 'idle' category
        non_idle_data = [(c, d) for c, d in zip(u_cats, u_dur) if c.lower() != 'idle']
        if not non_idle_data:
            return
        
        u_cats, u_dur = zip(*non_idle_data)

        total_dur = np.sum(u_dur)
        today = date
        filename = '{0:d}-{1:02d}-{2:02d}.png'.format(today.year, today.month, today.day)

        pie_labels = []
        pie_dur = []
        pie_colors = []
        
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')

        for cat, dur in zip(u_cats, u_dur):
            if dur > 0:
                pie_dur.append(dur)
                hr, mn, sec = Sec2hms(dur)
                pie_labels.append(f"{cat}-{hr:02}:{mn:02}:{sec:02}")
                pie_colors.append(color_map.get(cat, default_color))

        weekday_name = today.strftime('%a')
        total_hr, total_min, total_sec = Sec2hms(total_dur)
        
        plt.figure(num=None, figsize=(8, 6), dpi=80, facecolor='w', edgecolor='k')
        plt.title(f'{weekday_name}, {today.month:02}.{today.day:02}.{today.year:04} - {total_hr:02}:{total_min:02}:{total_sec:02} h')

        plt.pie(pie_dur, labels=pie_labels, autopct='%1.1f%%', colors=pie_colors)
        plt.axis('equal')
        plt.tight_layout()
        plt.savefig(path)
        plt.close()

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print('[{}] Pie chart saved as {}'.format(timestamp, path))


    def get_colors(self, logfile):
        colors = []
        u_cats, _, _, _ = self.analyze(logfile)
        if not u_cats:
            return []
        
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')
        
        for u_cat in u_cats:
            colors.append(color_map.get(u_cat, default_color))
            
        return colors

    def print_review(self, logfile=''):
        if "mod.log" in logfile:
            return

        u_cats, u_dur, date, _ = self.analyze(logfile)
        if not u_cats or date is None:
            return
        print('')
        print('')
        total_dur = np.sum(u_dur)
        if (isinstance(total_dur, numbers.Number) == False):
            return

        total_hr = np.floor(total_dur / 3600)
        total_min = np.floor((total_dur-total_hr*3600) / 60)
        total_sec = total_dur%60
        print('Review of {0:02}.{1:02}.{2:04}.{3}'.format(date.day, date.month, date.year, date.weekday()))
        print('-------------------------------------')
        print('{0: 6}:{1:02}:{2:02} h total'.format(int(total_hr), int(total_min), int(total_sec)))
        print('-------------------------------------')

        for idx in range(len(u_dur)):
            dur = u_dur[idx]
            cat = u_cats[idx]
            if dur > 0:
                dur_hr = int(np.floor(dur/3600))
                dur_min = int(np.floor((dur-dur_hr*3600)/60))
                dur_sec = int(dur%60)
                print('{0: 6}:{1:02}:{2:02} h  {3:} '.format(dur_hr, dur_min, dur_sec, cat))

        print('-------------------------------------')
        print('{0: 6}:{1:02}:{2:02} h not categorized'.format(0, 0, 0))


    def get_log_list(self):
        days = database.fetch_available_days()
        log_list = [f"{day}.csv" for day in days]
        date_list = [datetime.datetime.strptime(day, '%Y-%m-%d') for day in days]
        
        # Filter out future dates
        tz = pytz.timezone(TIMEZONE)
        today = datetime.datetime.now(tz).date()
        filtered_pairs = []
        for date, log in zip(date_list, log_list):
            if date.date() <= today:
                filtered_pairs.append((date, log))
            else:
                print(f"Warning: Skipping future date {date.date()} ({log}) to avoid processing future data and potential data loss.")
        
        if not filtered_pairs:
            return [], []
        
        date_list, log_list = zip(*filtered_pairs)
        sorted_pairs = sorted(zip(date_list, log_list), reverse=True)
        
        if not sorted_pairs:
            return [], []
            
        date_list, log_list = zip(*sorted_pairs)
        return list(log_list), list(date_list)


    def get_unique_categories(self, string_cats=''):
        if string_cats == '':
            string_cats = self.string_cats
        u_cats = []
        for string, cat in string_cats:
            if cat not in u_cats:
                u_cats.append(cat)
        return u_cats


    def get_cat(self, window, url=None):
        # Always treat 'desktop' as idle
        if window.strip().lower() == 'desktop':
            return 'idle'
        if len(window) <=1:
            return 'idle'
        normalized_targets = []
        if window:
            normalized_targets.append(window.lower())
        if url:
            normalized_targets.append(url.lower())

        for string, category in self.string_cats:
            if not string:
                continue
            string = string.strip()
            if not string:
                continue

            if string.lower().startswith('regex__'):
                pattern = string[7:].strip()
                for target in normalized_targets:
                    try:
                        if re.search(pattern, target.strip(), flags=re.IGNORECASE):
                            return category
                    except re.error:
                        continue
                continue

            needle = string.lower()
            for target in normalized_targets:
                if needle in target:
                    return category
        return 'not categorized'

    def create_html(self, logfile=''):
        if "mod.log" in logfile:
            return

        # Check if there are any new activities since last update
        current_activity_count = database.get_activity_count()
        time_since_last_update = time.time() - self.last_update_timestamp
        
        # Skip update if:
        # 1. No new activities AND
        # 2. We updated recently
        if (current_activity_count == self.last_activity_count and 
            time_since_last_update < 300):
            # print(f"[SKIP] No new activities, last update was {time_since_last_update:.0f}s ago")
            return
        
        # Update tracking variables
        self.last_activity_count = current_activity_count
        self.last_update_timestamp = time.time()

        week_days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        
        log_list, date_list = self.get_log_list()
        
        # Read display_limit from config, with a fallback
        try:
            display_limit = self.config.getint('SETTINGS', 'display_limit', fallback=20)
        except (configparser.NoSectionError, configparser.NoOptionError):
            display_limit = 14
        
        # Limit the number of logs to be displayed
        if len(log_list) > display_limit:
            log_list = log_list[:display_limit]
            date_list = date_list[:display_limit]
            
        all_u_cats = [
            cat
            for cat in self.get_unique_categories()
            if should_display_in_activity_summary(cat) and (not self._is_hidden_in_activity_summary(cat))
        ]
        
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')

        with open('html/head.txt', 'r', encoding='utf-8') as file:
            head = file.readlines()
        with open('html/tail.txt', 'r', encoding='utf-8') as file:
            tail = file.read()

        with open('html/index.html', 'w', encoding='utf-8') as file:
            file.writelines(head)
            
            # Determine current activity and set refresh rate accordingly
            current_category = self._get_current_activity_category(log_list, date_list)
            is_currently_wasting = current_category and is_wasted(current_category)
            
            # Refresh defaults (seconds). JS will only reload if there is new activity.
            refresh_interval = 30 if is_currently_wasting else 60
            latest_activity_ts = database.get_latest_activity_timestamp() or 0
            file.write(f'<meta name="refresh-interval" content="{refresh_interval}">\n')
            file.write(f'<meta name="activity-count" content="{current_activity_count}">\n')
            file.write(f'<meta name="activity-last-ts" content="{latest_activity_ts}">\n')

            # Add smart bookmarks section at the top
            bookmarks_html = self._generate_bookmarks_html()
            if bookmarks_html:
                file.write(bookmarks_html)

            # Add stock prices at the top
            stock_html = stock_prices.get_stock_html()
            if stock_html:
                file.write(stock_html)

            # Add Activity Summary section with expand/collapse
            file.write('<h2>Activity Summary <button id="toggle-summary-btn" style="margin-left:10px; padding:5px 15px; cursor:pointer; border-radius:5px; border:1px solid #4c6ef5; background:#4c6ef5; color:white;">Show All</button></h2>\n')
            table_html = '<table style="width:100%">'
            
            header_row = '<tr><td></td>'
            for cat in all_u_cats:
                color = color_map.get(cat, default_color)
                header_row += f'<td style="background-color:{color}"><b>{cat}</b></td>\n'
            header_row += '<td><b>Total Time</b></td>'
            header_row += '<td><b>Ctx Switches</b></td>'
            header_row += '<td><b>Switches/hr</b></td></tr>\n'
            table_html += header_row

            total_logs = len(log_list)
            for idx, log in enumerate(reversed(log_list)):
                self.print_pi_chart(log)
                self.create_interactive_timeline(log)
                
                u_cats_log, u_dur_log, date, df = self.analyze(log)
                if not date: continue
                
                dur_map = dict(zip(u_cats_log, u_dur_log))
                
                # Add class to hide older rows - show only the latest 3 days (at the bottom)
                row_class = '' if idx >= total_logs - 3 else ' class="summary-extra-row" style="display:none;"'
                row = f'<tr{row_class}>'
                row += '<td><b>{0:02}.{1:02}.{2:04},{3}</b></td>'.format(date.month, date.day, date.year, week_days[date.weekday()])
                
                # Categories to show ratio for - use centralized definition
                ratio_cats = RATIO_DISPLAY_CATS
                
                # Calculate total_time from ALL non-idle categories in the log (not just all_u_cats)
                total_time = 0
                for cat in dur_map.keys():
                    if cat.lower() != 'idle':
                        total_time += dur_map[cat]
                
                # Now render cells with ratios for specified categories
                for cat in all_u_cats:
                    dur = dur_map.get(cat, 0)
                    dur_hr, dur_min, dur_sec = Sec2hms(dur)
                    color = color_map.get(cat, default_color)
                    row += f'<td style="background-color:{color}">'
                    row += '{0:02}:{1:02}:{2:02}'.format(dur_hr, dur_min, dur_sec)
                    
                    # Add percentage for specified categories
                    if cat in ratio_cats and total_time > 0:
                        ratio = (dur / total_time) * 100
                        row += f'<br/><span style="font-size:0.85em;">({ratio:.1f}%)</span>'
                    
                    row += '</td>'
                
                tot_hr, tot_min, tot_sec = Sec2hms(total_time)
                row += '<td>{0:02}:{1:02}:{2:02}</td>'.format(tot_hr, tot_min, tot_sec)

                day_str = date.strftime('%Y-%m-%d')
                switch_count, switch_per_hour, _ = self._calculate_context_switching(day_str)
                row += f'<td>{switch_count:d}</td>'
                row += f'<td>{switch_per_hour:.1f}</td>'
                row += '</tr>'

                table_html += row

            table_html += header_row
            table_html += '</table>\n'
            file.write(table_html)

            # Add warning flags after activity summary
            flag_summary_html = self._build_warning_flag_summary()
            if flag_summary_html:
                file.write('<hr/>')
                file.write(flag_summary_html)

            habit_section_html, habit_script = self._build_habit_calendar_section()
            if habit_section_html:
                file.write(habit_section_html)
            if habit_script:
                file.write(habit_script)
            
            # Add auto-scroll: Must Done on Sat/Sun, Productivity Streak on other days
            file.write('''<script>
window.addEventListener("load", function() {
    var today = new Date().getDay(); // 0=Sunday, 6=Saturday
    var targetSection;
    if (today === 0 || today === 6) {
        // Saturday or Sunday - scroll to Must Done
        targetSection = document.getElementById("must-done-section");
    } else {
        // Weekday - scroll to Productivity Streak
        targetSection = document.getElementById("productivity-streak");
    }
    if (targetSection) {
        targetSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }
});
</script>
''')

            # Add Must Done section before Productive Streak
            must_done_html = self._build_must_done_section()
            if must_done_html:
                file.write(must_done_html)

            # Add productivity streak section or waste ratio section
            streak_minutes, streak_display = self._calculate_productivity_streak(log_list, date_list)
            current_category = self._get_current_activity_category(log_list, date_list)
            
            # Use centralized category definitions
            # Check if current activity is non-productive
            is_currently_wasting = current_category and is_wasted(current_category)
            
            # Always calculate waste ratio for display
            waste_percentage, waste_display, total_active_hours, wasted_hours, _ = self._calculate_waste_ratio(log_list, date_list)
            
            # Always show combined dashboard with streaks and waste ratio
            # Calculate longest streaks
            today_date_str = date_list[0].strftime('%Y-%m-%d') if date_list else None
            longest_today_min, longest_today_display, longest_today_time = (0, "0 min", "") if not today_date_str else self._calculate_longest_streak_for_day(today_date_str)
            longest_7days_min, longest_7days_display, longest_7days_date = self._calculate_longest_streak_recent_days(date_list, num_days=7)

            # Context switching metrics
            tz = pytz.timezone(TIMEZONE)
            now_local = datetime.datetime.now(tz)

            total_switches_today = 0
            switches_last_hour = 0
            switch_per_active_hour_last_hour = None
            if today_date_str:
                total_switches_today, _, _ = self._calculate_context_switching(today_date_str)
                switches_last_hour, switch_per_active_hour_last_hour, _ = self._calculate_context_switching_window(
                    today_date_str,
                    now_local,
                    window_seconds=3600,
                )

            lowest_switch_per_hour_today = self._calculate_lowest_context_switching_rate(today_date_str) if today_date_str else None

            recent_switches = self._get_recent_context_switches(today_date_str, max_switches=5) if today_date_str else []

            lowest_switch_per_hour_7d = None
            lowest_switch_per_hour_7d_date = None
            if date_list:
                seen_days = []
                for dt in date_list:
                    if dt is None:
                        continue

                    # Skip rest days for the 7-day comparison.
                    # Weekends and configured holidays behave differently and would distort this baseline.
                    try:
                        if dt.weekday() >= 5:
                            continue
                        if dt.strftime('%m-%d') in HOLIDAYS:
                            continue
                    except Exception:
                        # If dt isn't a date-like object for some reason, fall back to including it.
                        pass

                    day_str = dt.strftime('%Y-%m-%d')
                    if day_str in seen_days:
                        continue
                    seen_days.append(day_str)
                    if len(seen_days) > 7:
                        break

                    per_hr_low = self._calculate_lowest_context_switching_rate(day_str)
                    if per_hr_low is None:
                        continue
                    if lowest_switch_per_hour_7d is None or per_hr_low < lowest_switch_per_hour_7d:
                        lowest_switch_per_hour_7d = per_hr_low
                        lowest_switch_per_hour_7d_date = dt.strftime('%a, %b %d')
            
            # Get threshold from config
            streak_threshold = self.config.getint('SETTINGS', 'productivity_streak_threshold', fallback=25)
            
            # Determine border color based on current activity
            if is_currently_wasting:
                border_color = "#f44336"
                gradient = "linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%)"
            elif streak_minutes >= streak_threshold:
                border_color = "#4caf50"
                gradient = "linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%)"
            else:
                border_color = "#ff9800"
                gradient = "linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%)"
            
            # Determine message based on current state
            if is_currently_wasting:
                message = "⚠️ Get back to productive work! 💪"
            elif streak_minutes >= streak_threshold:
                message = "Keep going! You're doing great! 🚀"
            else:
                remaining = streak_threshold - int(streak_minutes)
                message = f"Go back to work, till {streak_threshold} minutes! ({remaining} min remaining)"
            
            file.write('<hr/>')
            file.write(f'<div id="productivity-streak" class="productivity-streak" style="margin:20px 0; padding:15px; border:2px solid {border_color}; border-radius:8px; background:{gradient};">')
            
            # Four columns: Productive Streak, Longest Today, Longest 7 Days, Waste Ratio
            file.write('<div style="display: flex; justify-content: space-around; align-items: flex-start; flex-wrap: wrap;">')
            
            # Productive Streak
            file.write('<div style="flex: 1; min-width: 200px; padding: 10px; text-align: center;">')
            file.write('<h3 style="margin:0 0 10px 0; color:#2e7d32;">🔥 Productive Streak</h3>')
            # Add a stable element id so other UI (e.g., Focus Timer popup) can stay consistent.
            file.write(f'<p id="productive-streak-value" style="font-size:2em; font-weight:bold; margin:5px 0; color:#1b5e20;">{streak_display}</p>')
            file.write(f'<p style="margin:5px 0; color:#33691e; font-size:0.95em;">{message}</p>')
            
            # Add note-taking section
            file.write('<div style="margin-top: 15px; padding-top: 10px; border-top: 1px solid rgba(0,0,0,0.1);">')
            file.write('<textarea id="streak-note" placeholder="What are you working on?" style="width: 90%; padding: 8px; border: 2px solid #ccc; border-radius: 4px; font-family: inherit; resize: vertical; min-height: 60px; transition: all 0.2s ease;"></textarea>')
            file.write('<div style="margin-top: 5px;"><button onclick="saveNote()" style="background: #4CAF50; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 0.9em;">Save Note</button>')
            file.write('<span id="note-status" style="margin-left: 10px; font-size: 0.9em; color: #666;"></span></div>')
            
            file.write('</div>')
            
            # JavaScript for saving notes
            file.write('''
<script>
function saveNote() {
    const noteArea = document.getElementById('streak-note');
    const statusSpan = document.getElementById('note-status');
    const saveBtn = document.querySelector('button[onclick="saveNote()"]');
    // Track unsaved changes
    window.__streakNoteUnsaved = window.__streakNoteUnsaved || false;
    const note = noteArea.value.trim();
    
    if (!note) {
        statusSpan.textContent = 'Please enter a note';
        statusSpan.style.color = '#d32f2f';
        return;
    }
    
    statusSpan.textContent = 'Saving...';
    statusSpan.style.color = '#666';
    
    fetch('http://127.0.0.1:8042/save_note', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({note: note})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            statusSpan.textContent = 'Saved!';
            statusSpan.style.color = '#4CAF50';

            // Capture text before clearing
            const savedText = note;
            noteArea.value = '';
            // Mark as saved and set button to blue
            window.__streakNoteUnsaved = false;
            window.__refreshEnabled = true; // Re-enable page refresh after saving
            if (saveBtn) {
                saveBtn.style.background = '#1976D2'; // Blue
                saveBtn.style.color = 'white';
            }
            // Reset textarea styling
            noteArea.style.borderColor = '#ccc';
            noteArea.style.boxShadow = 'none';

            // Rebuild Recent Notes from server response
            const recentContainer = document.getElementById('recent-notes');
            if (recentContainer && data.recent_notes) {
                // Clear existing notes
                recentContainer.innerHTML = '';
                
                // Ensure container is visible
                recentContainer.style.display = '';

                // Add notes from server (most recent first)
                data.recent_notes.forEach(note_item => {
                    const timestamp = note_item.timestamp;
                    const dt = new Date(timestamp * 1000); // Convert unix timestamp to ms
                    const timeStr = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    
                    const div = document.createElement('div');
                    div.style.margin = '4px 0';
                    div.style.color = '#555';
                    div.innerHTML = `<span style="color: #888;">${timeStr}</span> - ${note_item.text.replace(/</g,'&lt;').replace(/>/g,'&gt;')}`;
                    recentContainer.appendChild(div);
                });
            }

            // Also update Today's Notes if present
            const todayContainer = document.getElementById('todays-notes');
            if (todayContainer) {
                const li = document.createElement('div');
                li.style.margin = '4px 0';
                li.textContent = savedText;
                if (todayContainer.firstChild) {
                    todayContainer.insertBefore(li, todayContainer.firstChild);
                } else {
                    todayContainer.appendChild(li);
                }
            }
        } else {
            statusSpan.textContent = 'Error: ' + (data.error || 'Unknown');
            statusSpan.style.color = '#d32f2f';
        }
    })
    .catch(error => {
        console.error('Error:', error);
        statusSpan.textContent = 'Network Error';
        statusSpan.style.color = '#d32f2f';
    });
}
</script>
            ''')

            # Add autosave guards and button color changes
            file.write('''
<script>
// JavaScript-based page refresh (replaces meta http-equiv="refresh")
// This allows us to prevent refresh while user is typing notes
window.__refreshEnabled = true;
window.__refreshTimeoutId = null;
window.__refreshLocks = window.__refreshLocks || {};

window.__setRefreshLock = function(key, locked) {
    if (!key) return;
    if (locked) {
        window.__refreshLocks[key] = true;
    } else {
        delete window.__refreshLocks[key];
    }
};

window.__isRefreshAllowed = function() {
    if (!window.__refreshEnabled) return false;
    try {
        return Object.keys(window.__refreshLocks || {}).length === 0;
    } catch (e) {
        return window.__refreshEnabled;
    }
};

function scheduleRefresh() {
    if (window.__refreshTimeoutId) {
        clearTimeout(window.__refreshTimeoutId);
    }
    
    const metaInterval = document.querySelector('meta[name="refresh-interval"]');
    const metaMs = metaInterval ? parseInt(metaInterval.content) * 1000 : 60000;
    const refreshInterval = Math.max(metaMs, 30000); // never poll faster than 30s

    function getActivityStatusUrl() {
        try {
            if (window.location && window.location.protocol && window.location.protocol.indexOf('http') === 0) {
                return window.location.origin + '/activity/status';
            }
        } catch (e) {}
        return 'http://127.0.0.1:8042/activity/status';
    }

    function fetchWithTimeout(url, timeoutMs) {
        if (!('AbortController' in window)) {
            return fetch(url, { cache: 'no-store' });
        }
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeoutMs);
        return fetch(url, { cache: 'no-store', signal: controller.signal })
            .finally(() => clearTimeout(id));
    }

    function shouldReload() {
        const baseCountMeta = document.querySelector('meta[name="activity-count"]');
        const baseCount = baseCountMeta ? parseInt(baseCountMeta.content) : NaN;
        const baseTsMeta = document.querySelector('meta[name="activity-last-ts"]');
        const baseTs = baseTsMeta ? parseFloat(baseTsMeta.content) : NaN;

        return fetchWithTimeout(getActivityStatusUrl(), 2000)
            .then(resp => resp.ok ? resp.json() : Promise.reject(new Error('Status ' + resp.status)))
            .then(data => {
                if (!data || data.status !== 'ok') return false;
                const currentCount = parseInt(data.activity_count);
                const currentTs = parseFloat(data.latest_activity_ts);
                if (!isNaN(baseCount) && !isNaN(currentCount)) {
                    return currentCount > baseCount;
                }
                if (!isNaN(baseTs) && !isNaN(currentTs)) {
                    return currentTs > (baseTs + 0.0001);
                }
                return false;
            })
            .catch(() => false);
    }

    window.__refreshTimeoutId = setTimeout(() => {
        const allowed = (typeof window.__isRefreshAllowed === 'function')
            ? window.__isRefreshAllowed()
            : window.__refreshEnabled;
        if (!allowed) {
            scheduleRefresh();
            return;
        }

        shouldReload().then(needsReload => {
            if (needsReload) {
                sessionStorage.setItem('scrollPos', window.scrollY.toString());
                location.reload();
            } else {
                // No new data: don't reload, just keep polling.
                scheduleRefresh();
            }
        });
    }, refreshInterval);
}

// Restore scroll position after page loads
document.addEventListener('DOMContentLoaded', () => {
    const savedPos = sessionStorage.getItem('scrollPos');
    if (savedPos !== null) {
        window.scrollTo(0, parseInt(savedPos));
        sessionStorage.removeItem('scrollPos');
    }
    scheduleRefresh();
});

// Make Save button yellow when typing, and guard against losing unsaved text
(() => {
    const noteArea = document.getElementById('streak-note');
    const saveBtn = document.querySelector('button[onclick="saveNote()"]');
    const statusSpan = document.getElementById('note-status');
    if (!noteArea || !saveBtn) return;
    
    const setButtonYellow = () => {
        window.__streakNoteUnsaved = noteArea.value.trim().length > 0;
        
        // Disable refresh when there's unsaved text
        window.__refreshEnabled = !window.__streakNoteUnsaved;
        if (typeof window.__setRefreshLock === 'function') {
            window.__setRefreshLock('streak_note', window.__streakNoteUnsaved);
        }
        
        if (window.__streakNoteUnsaved) {
            saveBtn.style.background = '#FBC02D'; // Yellow
            saveBtn.style.color = '#000';
            // Highlight the textarea
            noteArea.style.borderColor = '#FBC02D';
            noteArea.style.boxShadow = '0 0 8px rgba(251, 192, 45, 0.5)';
            if (statusSpan && !statusSpan.textContent) {
                statusSpan.textContent = 'Draft not saved';
                statusSpan.style.color = '#8D6E63';
            }
        } else {
            // Reset styling when empty
            saveBtn.style.background = '#4CAF50';
            saveBtn.style.color = 'white';
            noteArea.style.borderColor = '#ccc';
            noteArea.style.boxShadow = 'none';
            if (statusSpan) {
                statusSpan.textContent = '';
            }
        }
    };

    noteArea.addEventListener('input', setButtonYellow);
    noteArea.addEventListener('change', setButtonYellow);
    
    // Add visual feedback on focus
    noteArea.addEventListener('focus', function() {
        if (noteArea.value.trim().length > 0) {
            noteArea.style.borderColor = '#FBC02D';
            noteArea.style.boxShadow = '0 0 8px rgba(251, 192, 45, 0.5)';
        } else {
            noteArea.style.borderColor = '#4CAF50';
            noteArea.style.boxShadow = '0 0 8px rgba(76, 175, 80, 0.3)';
        }
    });
    
    // Reset on blur if no unsaved text
    noteArea.addEventListener('blur', function() {
        if (noteArea.value.trim().length === 0) {
            noteArea.style.borderColor = '#ccc';
            noteArea.style.boxShadow = 'none';
        }
    });

    // Prevent page unload if there's unsaved text
    window.addEventListener('beforeunload', function(e) {
        const hasUnsaved = noteArea.value.trim().length > 0;
        if (hasUnsaved) {
            e.preventDefault();
            e.returnValue = '';
            return '';
        }
    });
})();
</script>
            ''')
            
            file.write('</div>')
            
            # Longest Today
            file.write('<div style="flex: 1; min-width: 200px; padding: 10px; text-align: center; border-left: 1px solid rgba(0,0,0,0.1);">')
            file.write('<h3 style="margin:0 0 10px 0; color:#2e7d32;">🏆 Longest (Today / 7 Days)</h3>')
            longest_7days_info = longest_7days_date if longest_7days_date else "Weekly record"
            file.write(
                f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#1b5e20; white-space:nowrap;">'
                f'{longest_today_display} / {longest_7days_display} '
                f'<span style="font-size:0.60em; font-weight:normal; white-space:nowrap;">({longest_7days_info})</span>'
                f'</p>'
            )
            
            # Get current time
            tz = pytz.timezone(TIMEZONE)
            current_time = datetime.datetime.now(tz).strftime('%I:%M %p')
            
            if longest_today_time:
                longest_today_info = f"Started at {longest_today_time} · Now {current_time}"
            else:
                longest_today_info = f"Best focus session · Now {current_time}"
            file.write(f'<p style="margin:5px 0; color:#33691e; font-size:0.95em;">{longest_today_info}</p>')
            
            # Display recent notes under Longest Today
            recent_notes = database.get_recent_streak_notes(5)
            if recent_notes:
                file.write('<div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(0,0,0,0.1); text-align:left;">')
                file.write('<h4 style="margin: 0 0 8px 0; font-size: 0.9em; color: #555;">Recent Notes:</h4>')
                file.write('<div id="recent-notes" style="font-size: 0.85em;">')
                tz = pytz.timezone(TIMEZONE)
                for note_text, timestamp in recent_notes:
                    dt = datetime.datetime.fromtimestamp(timestamp, tz)
                    time_str = dt.strftime('%I:%M %p')
                    file.write(f'<div style="margin: 4px 0; color: #555;"><span style="color: #888;">{time_str}</span> - {html.escape(note_text)}</div>')
                file.write('</div></div>')
            else:
                file.write('<div id="recent-notes" style="display:none;"></div>')
            file.write('</div>')

            # Context Switching (today)
            file.write('<div style="flex: 1; min-width: 200px; padding: 10px; text-align: center; border-left: 1px solid rgba(0,0,0,0.1);">')
            file.write('<h3 style="margin:0 0 10px 0; color:#455a64;">Context Switches</h3>')
            file.write(f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#263238;">{switches_last_hour:d}</p>')
            if switch_per_active_hour_last_hour is None:
                file.write('<p style="margin:5px 0; color:#455a64; font-size:0.95em;">No active time in last hour</p>')
            else:
                file.write(f'<p style="margin:5px 0; color:#455a64; font-size:0.95em;">{switch_per_active_hour_last_hour:.1f} per active hour (last 60 min)</p>')
            file.write(f'<p style="margin:4px 0 0 0; color:#607d8b; font-size:0.90em;">Today total: {total_switches_today:d} switches</p>')

            if lowest_switch_per_hour_today is not None or lowest_switch_per_hour_7d is not None:
                parts = []
                if lowest_switch_per_hour_today is not None:
                    parts.append(f'Lowest today: {lowest_switch_per_hour_today:.1f}/hr')
                if lowest_switch_per_hour_7d is not None:
                    date_label = f' ({lowest_switch_per_hour_7d_date})' if lowest_switch_per_hour_7d_date else ''
                    parts.append(f'Lowest 7 days: {lowest_switch_per_hour_7d:.1f}/hr{date_label}')
                joined = ' · '.join(parts)
                file.write(
                    f'<p style="margin:8px 0 0 0; font-size:0.98em;">'
                    f'<span style="display:inline-block; padding:4px 10px; border-radius:999px; '
                    f'background:rgba(69, 90, 100, 0.10); border:1px solid rgba(69, 90, 100, 0.22); '
                    f'color:#263238; font-weight:600; letter-spacing:0.1px;">{joined}</span>'
                    f'</p>'
                )

            # Recent switch transitions
            if recent_switches:
                file.write('<div style="margin-top:10px; text-align:left; font-size:0.88em; line-height:1.6;">')
                file.write('<div style="font-weight:600; color:#455a64; margin-bottom:4px;">Recent switches:</div>')
                for sw in recent_switches:
                    from_cat = html.escape(sw['from_cat'])
                    to_cat = html.escape(sw['to_cat'])
                    sw_time = sw.get('time')
                    time_str = sw_time.strftime('%I:%M %p') if sw_time else ''
                    if sw['is_focus_to_distraction']:
                        # Highlight focus → distraction in red
                        file.write(
                            f'<div style="color:#c62828; font-weight:600;">'
                            f'<span style="color:#888; font-weight:400;">{time_str}</span> '
                            f'⚠️ {from_cat} → {to_cat}'
                            f'</div>'
                        )
                    else:
                        file.write(
                            f'<div style="color:#455a64;">'
                            f'<span style="color:#888;">{time_str}</span> '
                            f'{from_cat} → {to_cat}'
                            f'</div>'
                        )
                file.write('</div>')

            file.write('</div>')
            
            # Waste Ratio
            file.write('<div style="flex: 1; min-width: 200px; padding: 10px; text-align: center; border-left: 1px solid rgba(0,0,0,0.1);">')
            file.write('<h3 style="margin:0 0 10px 0; color:#c62828;">📊 Waste Ratio</h3>')
            file.write(f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#d32f2f;">{waste_display}</p>')
            if total_active_hours > 0:
                file.write(f'<p style="margin:5px 0; color:#c62828; font-size:0.95em;">Wasted: {wasted_hours:.1f}h / {total_active_hours:.1f}h</p>')
                
                # Calculate needed focus hours to reach target waste ratio
                target_waste_ratio = self.config.getfloat('SETTINGS', 'target_waste_ratio', fallback=0.20)
                current_waste_ratio = waste_percentage / 100.0
                
                if current_waste_ratio > target_waste_ratio and wasted_hours > 0:
                    # Calculate: wasted_hours / (total_active_hours + X) = target_waste_ratio
                    # X = (wasted_hours / target_waste_ratio) - total_active_hours
                    needed_hours = (wasted_hours / target_waste_ratio) - total_active_hours
                    if needed_hours > 0:
                        target_display = f"{int(target_waste_ratio * 100)}%"
                        file.write(f'<p style="margin:10px 0 5px 0; color:#ff5722; font-size:0.95em; font-weight:bold;">💪 Need {needed_hours:.1f}h more focus to reach {target_display}</p>')
            else:
                file.write(f'<p style="margin:5px 0; color:#666; font-size:0.95em;">No active time yet</p>')
            file.write('<ul style="text-align:left; display:inline-block; margin:10px 0 0 0; padding-left:20px; font-size:1.1em; color:#d32f2f;">')
            file.write('<li>No shopping/gaming in the morning</li>')
            file.write('<li>No facebook too</li>')
            file.write('<li></li>')
            file.write('<li>PUT CELL PHONE AWAY</li>')
            file.write('</ul>')
            file.write('</div>')
            
            file.write('</div>')
            file.write('</div>')

            # Work focus timer popup (uses the same threshold as the productivity streak)
            work_focus_cats = {
                'work',
                'coding',
                'programming',
                'job_search',
                'current_job',
            }
            current_category_lower = (current_category or '').strip().lower()
            is_work_focus = bool(
                current_category_lower
                and (
                    current_category_lower in work_focus_cats
                    or current_category_lower.startswith('job_search')
                    or current_category_lower.startswith('current_job')
                )
            )

            # Streak minutes is a float; clamp to >= 0 for display/timer.
            try:
                streak_minutes_value = float(streak_minutes)
            except Exception:
                streak_minutes_value = 0.0
            if streak_minutes_value < 0:
                streak_minutes_value = 0.0

            file.write(
                f'\n<div id="work-timer-popup" '
                f'data-enabled="{1 if is_work_focus else 0}" '
                f'data-streak-min="{streak_minutes_value:.4f}" '
                f'data-threshold-min="{int(streak_threshold)}" '
                f'data-category="{html.escape(current_category_lower)}" '
                f'style="display:none; position:fixed; right:18px; bottom:18px; z-index:9999; '
                f'max-width:360px; width:calc(100vw - 36px); '
                f'background:rgba(255,255,255,0.96); backdrop-filter: blur(8px); '
                f'border:1px solid rgba(76,175,80,0.35); border-left:6px solid #4caf50; '
                f'border-radius:14px; box-shadow:0 10px 30px rgba(0,0,0,0.18); '
                f'padding:12px; font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial;">\n'
                f'  <div style="display:flex; align-items:center; justify-content:space-between; gap:10px;">\n'
                f'    <div style="font-weight:800; color:#1b5e20; font-size:1.02em;">Focus Timer</div>\n'
                f'    <button id="work-timer-close" type="button" '
                f'      style="cursor:pointer; border:0; background:transparent; color:#607d8b; '
                f'      font-size:1.25em; line-height:1; padding:2px 6px;" '
                f'      aria-label="Dismiss">×</button>\n'
                f'  </div>\n'
                f'  <div style="margin-top:6px; color:#37474f; font-size:0.92em;">Category: <span id="work-timer-cat" style="font-weight:700;"></span></div>\n'
                f'  <div style="margin-top:8px; font-size:1.18em; font-weight:800; color:#263238;">'
                f'    <span id="work-timer-elapsed"></span> / <span id="work-timer-target"></span>'
                f'  </div>\n'
                f'  <div style="margin-top:4px; color:#546e7a; font-size:0.92em;">Remaining: <span id="work-timer-remaining" style="font-weight:700;"></span></div>\n'
                f'  <div style="height:9px; background:rgba(76,175,80,0.12); border-radius:999px; overflow:hidden; margin-top:10px;">\n'
                f'    <div id="work-timer-bar" style="height:100%; width:0%; background:linear-gradient(90deg, #66bb6a, #2e7d32);"></div>\n'
                f'  </div>\n'
                f'  <div id="work-timer-done" style="display:none; margin-top:10px; color:#1b5e20; font-weight:800;">Threshold reached — keep going.</div>\n'
                f'</div>\n'
                f'<button id="work-timer-fab" type="button" '
                f'  style="display:none; position:fixed; right:18px; bottom:18px; z-index:9998; '
                f'  width:46px; height:46px; border-radius:999px; border:1px solid rgba(76,175,80,0.35); '
                f'  background:rgba(255,255,255,0.92); backdrop-filter: blur(8px); '
                f'  box-shadow:0 10px 24px rgba(0,0,0,0.18); cursor:pointer; '
                f'  color:#1b5e20; font-size:20px; font-weight:800;" '
                f'  aria-label="Show focus timer" title="Show focus timer">⏱</button>\n'
                f'<script>\n'
                f'(function() {{\n'
                f'  const popup = document.getElementById("work-timer-popup");\n'
                f'  const fab = document.getElementById("work-timer-fab");\n'
                f'  if (!popup) return;\n'
                f'  const enabled = popup.dataset.enabled === "1";\n'
                f'  const dismissed = sessionStorage.getItem("workTimerDismissed") === "1";\n'
                f'  const thresholdMin = parseInt(popup.dataset.thresholdMin || "25", 10);\n'
                f'  const thresholdSec = Math.max(0, thresholdMin) * 60;\n'
                f'  let streakSec = Math.max(0, Math.floor(parseFloat(popup.dataset.streakMin || "0") * 60));\n'
                f'  const category = (popup.dataset.category || "").trim();\n'
                f'\n'
                f'  // If you leave work-focus (e.g. switch to wasted/non-work), reset dismiss state so it can show again next time.\n'
                f'  if (!enabled) {{\n'
                f'    sessionStorage.removeItem("workTimerDismissed");\n'
                f'    popup.style.display = "none";\n'
                f'    if (fab) fab.style.display = "none";\n'
                f'    return;\n'
                f'  }}\n'
                f'\n'
                f'  const closeBtn = document.getElementById("work-timer-close");\n'
                f'  if (closeBtn) closeBtn.addEventListener("click", () => {{\n'
                f'    sessionStorage.setItem("workTimerDismissed", "1");\n'
                f'    popup.style.display = "none";\n'
                f'    if (fab && enabled && thresholdSec > 0 && streakSec < thresholdSec) fab.style.display = "block";\n'
                f'  }});\n'

                f'  function showPopup() {{\n'
                f'    sessionStorage.removeItem("workTimerDismissed");\n'
                f'    popup.style.display = "block";\n'
                f'    if (fab) fab.style.display = "none";\n'
                f'  }}\n'

                f'  // Allow manual re-open from console or a button.\n'
                f'  window.__showWorkTimerPopup = showPopup;\n'

                f'  if (fab) fab.addEventListener("click", () => {{\n'
                f'    showPopup();\n'
                f'    render();\n'
                f'  }});\n'
                f'\n'
                f'  const catEl = document.getElementById("work-timer-cat");\n'
                f'  const elapsedEl = document.getElementById("work-timer-elapsed");\n'
                f'  const targetEl = document.getElementById("work-timer-target");\n'
                f'  const remainingEl = document.getElementById("work-timer-remaining");\n'
                f'  const barEl = document.getElementById("work-timer-bar");\n'
                f'  const doneEl = document.getElementById("work-timer-done");\n'
                f'\n'
                f'  function fmtMmss(sec) {{\n'
                f'    sec = Math.max(0, sec|0);\n'
                f'    const m = Math.floor(sec / 60);\n'
                f'    const s = sec % 60;\n'
                f'    return m.toString() + ":" + s.toString().padStart(2, "0");\n'
                f'  }}\n'
                f'\n'
                f'  function render() {{\n'
                f'    if (catEl) catEl.textContent = category || "(unknown)";\n'
                f'    if (elapsedEl) elapsedEl.textContent = fmtMmss(streakSec);\n'
                f'    if (targetEl) targetEl.textContent = fmtMmss(thresholdSec);\n'
                f'    const remainingSec = Math.max(0, thresholdSec - streakSec);\n'
                f'    if (remainingEl) remainingEl.textContent = fmtMmss(remainingSec);\n'
                f'    const pct = thresholdSec > 0 ? Math.min(100, Math.floor((streakSec / thresholdSec) * 100)) : 0;\n'
                f'    if (barEl) barEl.style.width = pct.toString() + "%";\n'
                f'  }}\n'
                f'\n'
                f'  // Only show while you are in a work-focus category and still below the streak threshold.\n'
                f'  if (!enabled || dismissed || thresholdSec <= 0 || streakSec >= thresholdSec) {{\n'
                f'    popup.style.display = "none";\n'
                f'    if (fab) {{\n'
                f'      // If dismissed but eligible, show a small button to reopen.\n'
                f'      if (enabled && dismissed && thresholdSec > 0 && streakSec < thresholdSec) fab.style.display = "block";\n'
                f'      else fab.style.display = "none";\n'
                f'    }}\n'
                f'    return;\n'
                f'  }}\n'
                f'\n'
                f'  popup.style.display = "block";\n'
                f'  if (fab) fab.style.display = "none";\n'
                f'  render();\n'
                f'\n'
                f'  const timerId = window.setInterval(() => {{\n'
                f'    streakSec += 1;\n'
                f'    if (streakSec >= thresholdSec) {{\n'
                f'      render();\n'
                f'      if (doneEl) doneEl.style.display = "block";\n'
                f'      sessionStorage.removeItem("workTimerDismissed");\n'
                f'      window.clearInterval(timerId);\n'
                f'      window.setTimeout(() => {{ popup.style.display = "none"; }}, 4000);\n'
                f'      return;\n'
                f'    }}\n'
                f'    render();\n'
                f'  }}, 1000);\n'
                f'}})();\n'
                f'</script>\n'
            )

            recent_activity_minutes = self.config.getint('SETTINGS', 'recent_activity_minutes', fallback=10)
            recent_activity_html = self._build_recent_activity_section(log_list, date_list, minutes=recent_activity_minutes)
            if recent_activity_html:
                file.write('<hr/>')
                file.write(recent_activity_html)

            # Add Agent Coach Dashboard (after Recent Activity for easier reading)
            productivity_goals_html = self._build_productivity_goals_section()
            if productivity_goals_html:
                file.write(productivity_goals_html)

            # Add section header with expand/collapse button for charts
            file.write('<h2>Pie Charts and Activity Timelines <button id="toggle-charts-btn" style="margin-left:10px; padding:5px 15px; cursor:pointer; border-radius:5px; border:1px solid #4c6ef5; background:#4c6ef5; color:white;">Show All</button></h2>\n')
            file.write('<div class="gallery" id="charts-gallery" style="width: 100%;">\n')
            img_list = sorted(os.listdir('figs/pie'))
            timeline_html_list = sorted(os.listdir('html/timelines'))

            # Create a dictionary for timeline images for quick lookup
            timeline_map = {html.split('.')[0]: html for html in timeline_html_list}

            # Show only the most recent 7 days
            recent_img_list = list(reversed(img_list))[:7]

            for idx, img in enumerate(recent_img_list):
                date_str = img.split('.')[0]
                timeline_html = timeline_map.get(date_str)

                # Add class to hide older charts - show only the latest 3 days
                chart_class = '' if idx < 3 else ' class="chart-extra-row" style="display:none;"'
                img_row = f'<div{chart_class} style="display: flex; justify-content: center; align-items: center; margin-bottom: 20px; width: 100%;">'
                img_row += f'<img src="../figs/pie/{img}" style="width: 48%; max-width: 500px;" >'
                if timeline_html:
                    img_row += f'<iframe src="timelines/{timeline_html}" style="width: 48%; height: 500px; border: none;"></iframe>'
                img_row += '</div></br>'
                file.write(img_row)
            file.write('</div>')

            # Add JavaScript for expand/collapse functionality
            file.write('''
<script>
// Toggle Activity Summary table
var summaryBtn = document.getElementById('toggle-summary-btn');
var summaryExpanded = false;
if (summaryBtn) {
    summaryBtn.addEventListener('click', function() {
        var extraRows = document.querySelectorAll('.summary-extra-row');
        summaryExpanded = !summaryExpanded;
        for (var i = 0; i < extraRows.length; i++) {
            extraRows[i].style.display = summaryExpanded ? 'table-row' : 'none';
        }
        summaryBtn.textContent = summaryExpanded ? 'Show Less' : 'Show All';
    });
}

// Toggle Pie Charts and Timelines
var chartsBtn = document.getElementById('toggle-charts-btn');
var chartsExpanded = false;
if (chartsBtn) {
    chartsBtn.addEventListener('click', function() {
        var extraCharts = document.querySelectorAll('.chart-extra-row');
        chartsExpanded = !chartsExpanded;
        for (var i = 0; i < extraCharts.length; i++) {
            extraCharts[i].style.display = chartsExpanded ? 'flex' : 'none';
        }
        chartsBtn.textContent = chartsExpanded ? 'Show Less' : 'Show All';
    });
}
</script>
''')
            file.writelines(tail)
        
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] html updated')
        
        # Save analysis cache asynchronously to avoid blocking the main thread
        self._save_analysis_cache()

    def _build_habit_calendar_section(self):
        if not HABITS:
            return '', ''

        tz = pytz.timezone(TIMEZONE)
        today = datetime.datetime.now(tz).date()
        display_days = 14
        current_week_start = today - datetime.timedelta(days=today.weekday())
        display_start = current_week_start - datetime.timedelta(days=7)
        display_end = display_start + datetime.timedelta(days=display_days - 1)
        lookback_days = 60
        fetch_start = display_start - datetime.timedelta(days=lookback_days)

        habit_names = [name for name, _ in HABITS]
        raw_completions = database.get_habit_completions(
            habits=habit_names,
            start_date=fetch_start.isoformat(),
            end_date=display_end.isoformat()
        )

        normalized_flags: dict[str, dict[str, bool]] = {}
        updated_at_map: dict[str, dict[str, str | None]] = {}
        for habit_name in habit_names:
            habit_entries = raw_completions.get(habit_name, {})
            normalized_flags[habit_name] = {}
            updated_at_map[habit_name] = {}
            for iso_date, entry in habit_entries.items():
                if isinstance(entry, dict):
                    normalized_flags[habit_name][iso_date] = bool(entry.get('completed'))
                    updated_at_map[habit_name][iso_date] = entry.get('updated_at') or entry.get('updatedAt')
                else:
                    normalized_flags[habit_name][iso_date] = bool(entry)
                    updated_at_map[habit_name][iso_date] = None

        def _carryover_streak(habit_name: str) -> int:
            habit_map = normalized_flags.get(habit_name, {})
            streak = 0
            cursor = display_start - datetime.timedelta(days=1)
            while cursor >= fetch_start:
                if not habit_map.get(cursor.isoformat()):
                    break
                streak += 1
                cursor -= datetime.timedelta(days=1)
            return streak

        streak_base = {habit: _carryover_streak(habit) for habit in habit_names}

        streak_by_date: dict[str, dict[str, int]] = {}
        for habit in habit_names:
            streak = streak_base[habit]
            habit_map = normalized_flags.get(habit, {})
            date_map: dict[str, int] = {}
            for offset in range(display_days):
                day = display_start + datetime.timedelta(days=offset)
                iso_date = day.isoformat()
                if habit_map.get(iso_date):
                    streak += 1
                else:
                    streak = 0
                date_map[iso_date] = streak
            streak_by_date[habit] = date_map

        weekdays_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        server_url = 'http://127.0.0.1:8042/habits'
        if display_start.year == display_end.year:
            calendar_title = f"{display_start.strftime('%b %d')} – {display_end.strftime('%b %d %Y')}"
        else:
            calendar_title = f"{display_start.strftime('%b %d %Y')} – {display_end.strftime('%b %d %Y')}"

        legend_items = [
            '<span class="habit-legend-item">'
            f'<span class="habit-dot" style="background:{html.escape(color, quote=True)}"></span>'
            f'<span class="habit-text">{html.escape(name)}</span>'
            '</span>'
            for name, color in HABITS
        ]

        habits_json = html.escape(json.dumps(habit_names))
        streak_base_json = html.escape(json.dumps(streak_base))

        def _habits_with_completions() -> dict[str, dict[str, dict[str, str | bool | None]]]:
            enriched: dict[str, dict[str, dict[str, str | bool | None]]] = {}
            for habit in habit_names:
                enriched[habit] = {}
                for iso_date in normalized_flags.get(habit, {}):
                    enriched[habit][iso_date] = {
                        'completed': normalized_flags[habit][iso_date],
                        'updated_at': updated_at_map[habit].get(iso_date)
                    }
            return enriched

        completions_json = html.escape(json.dumps(_habits_with_completions()))

        html_parts = [
            '<section class="habit-calendar"'
            f' data-start="{display_start.isoformat()}"'
            f' data-display-start="{display_start.isoformat()}"'
            f' data-display-end="{display_end.isoformat()}"'
            f' data-fetch-start="{fetch_start.isoformat()}"'
            f' data-end="{display_end.isoformat()}"'
            f' data-server-url="{server_url}"'
            f' data-habits="{habits_json}"'
            f' data-streak-base="{streak_base_json}"'
            f' data-completions="{completions_json}">',
            '<div class="habit-calendar-header">'
            f'<h2>Daily Habits – {calendar_title}</h2>'
            '<div class="habit-calendar-actions">'
            '<button type="button" class="habit-refresh">Refresh</button>'
            '</div>'
            '</div>'
        ]

        if legend_items:
            html_parts.append('<div class="habit-legend">' + ''.join(legend_items) + '</div>')

        html_parts.append('<div class="habit-calendar-message" role="status"></div>')

        html_parts.append('<div class="habit-calendar-weekdays">')
        for label in weekdays_labels:
            html_parts.append(f'<div>{label}</div>')
        html_parts.append('</div>')

        html_parts.append('<div class="habit-calendar-grid">')
        for offset in range(display_days):
            day = display_start + datetime.timedelta(days=offset)
            iso_date = day.isoformat()
            classes = ['calendar-day']
            if day == today:
                classes.append('today')
            if day > today:
                classes.append('future')
            if day < today:
                classes.append('past')
            class_attr = ' '.join(classes)

            html_parts.append(f'<div class="{class_attr}" data-date="{iso_date}">')
            html_parts.append(f'<div class="date-label">{day.day}</div>')
            html_parts.append('<div class="habit-checkboxes">')

            for habit_name, color in HABITS:
                slug = re.sub(r'[^a-z0-9]+', '-', habit_name.lower()).strip('-') or 'habit'
                checkbox_id = f'habit-{slug}-{iso_date}'
                habit_map = normalized_flags.get(habit_name, {})
                is_completed = bool(habit_map.get(iso_date))
                checked_attr = ' checked' if is_completed else ''
                streak_value = streak_by_date.get(habit_name, {}).get(iso_date, 0)
                updated_value = updated_at_map.get(habit_name, {}).get(iso_date)
                updated_attr = f' data-updated-at="{html.escape(str(updated_value))}"' if updated_value else ''
                escaped_habit = html.escape(habit_name)
                html_parts.append(
                    f'<label class="habit-toggle" data-habit="{escaped_habit}" data-date="{iso_date}"'
                    f' data-streak="{streak_value}"{updated_attr} for="{checkbox_id}">'
                    f'<input id="{checkbox_id}" type="checkbox" data-habit="{escaped_habit}" data-date="{iso_date}"{checked_attr}>'
                    f'<span class="habit-dot" style="background:{html.escape(color, quote=True)}"></span>'
                    f'<span class="habit-text">{escaped_habit}</span>'
                    f'<span class="habit-streak">{streak_value}d</span>'
                    '<span class="habit-updated"></span>'
                    '</label>'
                )

            html_parts.append('</div>')
            html_parts.append('</div>')

        html_parts.append('</div>')
        html_parts.append('</section>')

        script = textwrap.dedent(
            """
            <style>
            .habit-calendar { margin: 0 0 24px 0; padding: 16px 20px; background: #f9f9fb; border: 1px solid #d3d7e0; border-radius: 12px; box-shadow: 0 1px 2px rgba(18,25,38,0.08); }
            .habit-calendar h2 { margin: 0; font-size: 1.25rem; }
            .habit-calendar-actions { display: flex; gap: 8px; }
            .habit-refresh { border: 1px solid #4c6ef5; background: #4c6ef5; color: #fff; padding: 6px 12px; border-radius: 6px; font-size: 0.9rem; cursor: pointer; }
            .habit-refresh:hover { background: #3b5bdb; border-color: #3b5bdb; }
            .habit-refresh:disabled { background: #a5b4fc; border-color: #a5b4fc; cursor: not-allowed; }
            .habit-calendar-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
            .habit-legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; font-size: 0.9rem; }
            .habit-legend-item { display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; background: rgba(76,110,245,0.08); border-radius: 999px; }
            .habit-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
            .habit-text { flex: 1 1 auto; }
            .habit-streak { margin-left: auto; padding: 2px 6px; background: rgba(54,79,199,0.12); color: #364fc7; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
            .habit-updated { display: none; margin-left: 8px; font-size: 0.72rem; color: #5c7cfa; white-space: nowrap; }
            .habit-updated.is-visible { display: inline-block; }
            .habit-calendar-message { min-height: 1em; margin: 8px 0 12px; font-size: 0.9rem; }
            .habit-calendar-message.success { color: #2f9e44; }
            .habit-calendar-message.error { color: #d6336c; }
            .habit-calendar-message.info { color: #364fc7; }
            .habit-calendar-weekdays { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; text-align: center; font-weight: 600; margin-bottom: 6px; }
            .habit-calendar-weekdays div { padding: 6px 0; background: rgba(18,25,38,0.06); border-radius: 6px; }
            .habit-calendar-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; grid-auto-rows: minmax(110px, auto); }
            .habit-calendar .calendar-day { padding: 10px; background: #fff; border: 1px solid rgba(18,25,38,0.1); border-radius: 10px; display: flex; flex-direction: column; }
            .habit-calendar .calendar-day.today { border-color: #4c6ef5; box-shadow: 0 0 0 2px rgba(76,110,245,0.25); }
            .habit-calendar .calendar-day.future { background: #f1f3f5; }
            .habit-calendar .calendar-day.past { opacity: 0.92; }
            .habit-calendar .date-label { font-weight: 600; margin-bottom: 6px; }
            .habit-checkboxes { display: flex; flex-direction: column; gap: 4px; margin-top: auto; }
            .habit-toggle { display: flex; align-items: center; gap: 6px; font-size: 0.85rem; cursor: pointer; }
            .habit-toggle input[type="checkbox"] { margin: 0; }
            @media (max-width: 860px) {
                .habit-calendar { padding: 12px 14px; }
                .habit-calendar-grid { gap: 4px; }
            }
            </style>
            <script>
            (function() {
                var HABIT_REFRESH_DELAY_MS = 250;

                function parseJSON(value, fallback) {
                    if (!value) {
                        return fallback || {};
                    }
                    try {
                        return JSON.parse(value);
                    } catch (error) {
                        console.warn('Failed to parse habit calendar data', error);
                        return fallback || {};
                    }
                }

                function toDate(iso) {
                    var parts = iso.split('-');
                    return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
                }

                function formatISO(date) {
                    var year = date.getFullYear();
                    var month = String(date.getMonth() + 1).padStart(2, '0');
                    var day = String(date.getDate()).padStart(2, '0');
                    return year + '-' + month + '-' + day;
                }

                function addDays(date, amount) {
                    var copy = new Date(date.getTime());
                    copy.setDate(copy.getDate() + amount);
                    return copy;
                }

                function buildDateRange(startISO, endISO) {
                    var dates = [];
                    if (!startISO || !endISO) {
                        return dates;
                    }
                    var cursor = toDate(startISO);
                    var limit = toDate(endISO);
                    while (cursor <= limit) {
                        dates.push(formatISO(cursor));
                        cursor = addDays(cursor, 1);
                    }
                    return dates;
                }

                function isEntryCompleted(entry) {
                    if (!entry) {
                        return false;
                    }
                    if (typeof entry === 'object') {
                        return Boolean(entry.completed);
                    }
                    return Boolean(entry);
                }

                function getEntryUpdatedAt(entry) {
                    if (!entry || typeof entry !== 'object') {
                        return null;
                    }
                    var raw = entry.updated_at;
                    if (typeof raw === 'undefined') {
                        raw = entry.updatedAt;
                    }
                    if (raw === null || typeof raw === 'undefined') {
                        return null;
                    }
                    if (typeof raw === 'number') {
                        return new Date(raw * 1000).toISOString();
                    }
                    if (typeof raw === 'string') {
                        return raw;
                    }
                    return null;
                }

                function toMillis(isoTimestamp) {
                    if (!isoTimestamp) {
                        return 0;
                    }
                    var dt = new Date(isoTimestamp);
                    var value = dt.getTime();
                    return isNaN(value) ? 0 : value;
                }

                function shouldApplyServerState(label, entryUpdatedISO) {
                    if (!label) {
                        console.log('[shouldApplyServerState] No label - APPLY');
                        return true;
                    }
                    if (label.dataset.pending === 'true') {
                        console.log('[shouldApplyServerState]', label.dataset.habit, label.dataset.date, '- SKIP (pending)');
                        return false;
                    }
                    var labelMs = toMillis(label.dataset.updatedAt || null);
                    var entryMs = toMillis(entryUpdatedISO);
                    
                    console.log('[shouldApplyServerState]', label.dataset.habit, label.dataset.date, '- labelMs:', labelMs, 'entryMs:', entryMs, 'entryUpdatedISO:', entryUpdatedISO);
                    
                    if (!entryUpdatedISO) {
                        // If server has no timestamp, only apply if label also has no timestamp
                        // AND the checkbox is currently unchecked. This prevents unchecking
                        // recently-saved checkboxes during sync.
                        if (labelMs === 0) {
                            var checkbox = label.querySelector('input[type="checkbox"]');
                            var isChecked = checkbox ? checkbox.checked : false;
                            console.log('[shouldApplyServerState]', label.dataset.habit, '- No server timestamp, no label timestamp, checkbox is', isChecked ? 'CHECKED' : 'UNCHECKED');
                            // Only apply server state (which would uncheck) if checkbox is already unchecked
                            var shouldApply = checkbox ? !checkbox.checked : true;
                            console.log('[shouldApplyServerState]', label.dataset.habit, '- Decision:', shouldApply ? 'APPLY' : 'SKIP');
                            return shouldApply;
                        }
                        console.log('[shouldApplyServerState]', label.dataset.habit, '- No server timestamp but label has timestamp - SKIP');
                        return false;
                    }
                    if (labelMs === 0) {
                        console.log('[shouldApplyServerState]', label.dataset.habit, '- No label timestamp but server has timestamp - APPLY');
                        return true;
                    }
                    var shouldApply = entryMs >= labelMs - 500;
                    console.log('[shouldApplyServerState]', label.dataset.habit, '- Timestamp comparison:', shouldApply ? 'APPLY' : 'SKIP');
                    return shouldApply;
                }

                function formatUpdatedLabel(isoTimestamp) {
                    if (!isoTimestamp) {
                        return '';
                    }
                    var date = new Date(isoTimestamp);
                    if (isNaN(date.getTime())) {
                        return '';
                    }
                    var now = new Date();
                    var sameDay = date.toDateString() === now.toDateString();
                    var options = sameDay
                        ? { hour: '2-digit', minute: '2-digit' }
                        : { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
                    return date.toLocaleString(undefined, options);
                }

                function setUpdatedText(label, isoTimestamp) {
                    if (!label) {
                        return;
                    }
                    if (isoTimestamp) {
                        label.dataset.updatedAt = isoTimestamp;
                    } else {
                        delete label.dataset.updatedAt;
                    }
                    var stamp = label.querySelector('.habit-updated');
                    if (!stamp) {
                        return;
                    }
                    var text = formatUpdatedLabel(isoTimestamp);
                    if (text) {
                        stamp.textContent = text;
                        stamp.classList.add('is-visible');
                    } else {
                        stamp.textContent = '';
                        stamp.classList.remove('is-visible');
                    }
                }

                function updateStreakLabel(label, value) {
                    label.dataset.streak = String(value);
                    var badge = label.querySelector('.habit-streak');
                    if (badge) {
                        badge.textContent = value + 'd';
                    }
                }

                function computeStreaksFromCompletions(options) {
                    var completions = options.completions || {};
                    var fetchStart = options.fetchStart;
                    var displayStart = options.displayStart;
                    var displayEnd = options.displayEnd;
                    var habits = options.habits || [];
                    var dates = buildDateRange(fetchStart || displayStart, displayEnd);
                    var streaks = {};
                    var carryover = {};

                    habits.forEach(function(habit) {
                        var habitMap = completions[habit] || {};
                        var streak = 0;
                        streaks[habit] = {};
                        dates.forEach(function(isoDate) {
                            if (isoDate === displayStart) {
                                carryover[habit] = streak;
                            }
                            if (isEntryCompleted(habitMap[isoDate])) {
                                streak += 1;
                            } else {
                                streak = 0;
                            }
                            if (isoDate >= displayStart) {
                                streaks[habit][isoDate] = streak;
                            }
                        });
                        if (typeof carryover[habit] === 'undefined') {
                            carryover[habit] = 0;
                        }
                    });

                    return { streaks: streaks, carryover: carryover };
                }

                function groupLabelsByHabit(labels) {
                    var grouped = {};
                    labels.forEach(function(label) {
                        var habit = label.dataset.habit;
                        if (!grouped[habit]) {
                            grouped[habit] = [];
                        }
                        grouped[habit].push(label);
                    });
                    Object.keys(grouped).forEach(function(habit) {
                        grouped[habit].sort(function(a, b) {
                            return a.dataset.date.localeCompare(b.dataset.date);
                        });
                    });
                    return grouped;
                }

                function initHabitCalendar() {
                    var container = document.querySelector('.habit-calendar');
                    if (!container) {
                        return;
                    }

                    var serverUrl = container.dataset.serverUrl || '';
                    var displayStart = container.dataset.displayStart || container.dataset.start || '';
                    var displayEnd = container.dataset.displayEnd || container.dataset.end || '';
                    var fetchStart = container.dataset.fetchStart || displayStart;
                    var messageEl = container.querySelector('.habit-calendar-message');
                    var refreshBtn = container.querySelector('.habit-refresh');
                    var checkboxes = Array.prototype.slice.call(
                        container.querySelectorAll('input[type="checkbox"][data-habit][data-date]')
                    );
                    var labels = Array.prototype.slice.call(
                        container.querySelectorAll('.habit-toggle[data-habit][data-date]')
                    );
                    var labelLookup = {};
                    labels.forEach(function(label) {
                        labelLookup[label.dataset.habit + '||' + label.dataset.date] = label;
                        setUpdatedText(label, label.dataset.updatedAt || null);
                    });

                    var habits = parseJSON(container.dataset.habits, []);
                    if (!Array.isArray(habits) || !habits.length) {
                        habits = labels.map(function(label) {
                            return label.dataset.habit;
                        }).filter(function(value, index, array) {
                            return array.indexOf(value) === index;
                        });
                    }

                    var groupedLabels = groupLabelsByHabit(labels);
                    var canSync = Boolean(serverUrl && fetchStart && displayEnd);

                    function showMessage(text, type) {
                        if (!messageEl) {
                            return;
                        }
                        messageEl.textContent = text || '';
                        messageEl.className = 'habit-calendar-message ' + (type || 'info');
                    }

                    function setRefreshEnabled(enabled) {
                        if (!refreshBtn) {
                            return;
                        }
                        refreshBtn.disabled = !enabled;
                    }

                    function applyStreakBundle(bundle) {
                        if (!bundle) {
                            return;
                        }
                        var streaks = bundle.streaks || {};
                        Object.keys(streaks).forEach(function(habit) {
                            var habitMap = streaks[habit] || {};
                            Object.keys(habitMap).forEach(function(date) {
                                var label = labelLookup[habit + '||' + date];
                                if (label && label.dataset.pending === 'true') {
                                    return;
                                }
                                if (label) {
                                    updateStreakLabel(label, habitMap[date] || 0);
                                }
                            });
                        });
                        if (bundle.carryover) {
                            container.dataset.streakBase = JSON.stringify(bundle.carryover);
                        }
                    }

                    function recomputeStreaksFromDom() {
                        var base = parseJSON(container.dataset.streakBase, {});
                        Object.keys(groupedLabels).forEach(function(habit) {
                            var streak = base[habit] || 0;
                            groupedLabels[habit].forEach(function(label) {
                                var checkbox = label.querySelector('input[type="checkbox"]');
                                if (checkbox && checkbox.checked) {
                                    streak += 1;
                                } else {
                                    streak = 0;
                                }
                                updateStreakLabel(label, streak);
                            });
                        });
                    }

                    function syncFromServer() {
                        if (!canSync) {
                            return;
                        }
                        setRefreshEnabled(false);
                        fetch(serverUrl + '?start=' + encodeURIComponent(fetchStart) + '&end=' + encodeURIComponent(displayEnd))
                            .then(function(response) {
                                if (!response.ok) {
                                    throw new Error('Request failed: ' + response.status);
                                }
                                return response.json();
                            })
                            .then(function(data) {
                                if (!data || !data.completions) {
                                    throw new Error('Missing completion data');
                                }
                                console.log('[Habit Sync] Received data from server:', data);
                                checkboxes.forEach(function(cb) {
                                    var habit = cb.dataset.habit;
                                    var date = cb.dataset.date;
                                    var habitMap = data.completions[habit] || {};
                                    var entry = habitMap[date];
                                    var label = labelLookup[habit + '||' + date];
                                    var entryUpdatedISO = getEntryUpdatedAt(entry);
                                    var currentChecked = cb.checked;
                                    
                                    if (!shouldApplyServerState(label, entryUpdatedISO)) {
                                        console.log('[Habit Sync] SKIPPING', habit, date, '- shouldApplyServerState returned false');
                                        return;
                                    }
                                    
                                    var serverCompleted = isEntryCompleted(entry);
                                    console.log('[Habit Sync]', habit, date, '- Current:', currentChecked, 'Server:', serverCompleted, 'Entry:', entry);
                                    
                                    cb.checked = serverCompleted;
                                    if (label) {
                                        setUpdatedText(label, entryUpdatedISO);
                                    }
                                });
                                var bundle = computeStreaksFromCompletions({
                                    completions: data.completions,
                                    fetchStart: fetchStart,
                                    displayStart: displayStart,
                                    displayEnd: displayEnd,
                                    habits: habits
                                });
                                applyStreakBundle(bundle);
                                showMessage('Habits synced.', 'success');
                                setRefreshEnabled(true);
                                recomputeStreaksFromDom();
                            })
                            .catch(function(error) {
                                console.error('Habit sync failed', error);
                                showMessage('Could not reach habit server; showing cached data.', 'error');
                                setRefreshEnabled(true);
                            });
                    }

                    checkboxes.forEach(function(cb) {
                        cb.addEventListener('change', function(event) {
                            var checkbox = event.target;
                            var key = checkbox.dataset.habit + '||' + checkbox.dataset.date;
                            var label = labelLookup[key];
                            var previousUpdated = label ? (label.dataset.updatedAt || null) : null;
                            var desiredState = checkbox.checked;

                            if (!serverUrl) {
                                showMessage('Habit server not configured.', 'error');
                                checkbox.checked = !checkbox.checked;
                                recomputeStreaksFromDom();
                                return;
                            }

                            if (label) {
                                label.dataset.pending = 'true';
                                label.dataset.pendingDesired = desiredState ? '1' : '0';
                            }

                            recomputeStreaksFromDom();

                            var payload = {
                                habit: checkbox.dataset.habit,
                                date: checkbox.dataset.date,
                                completed: checkbox.checked
                            };

                            fetch(serverUrl, {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json'
                                },
                                body: JSON.stringify(payload)
                            })
                                .then(function(response) {
                                    if (!response.ok) {
                                        throw new Error('Request failed: ' + response.status);
                                    }
                                    return response.json();
                                })
                                .then(function(body) {
                                    var updatedISO = body && body.updated_at ? body.updated_at : null;
                                    var completedFromServer = body && typeof body.completed === 'boolean' ? body.completed : desiredState;
                                    checkbox.checked = completedFromServer;
                                    if (label) {
                                        setUpdatedText(label, updatedISO || previousUpdated);
                                        delete label.dataset.pending;
                                        delete label.dataset.pendingDesired;
                                    }
                                    showMessage('Saved ' + payload.habit + ' for ' + payload.date + '.', 'success');
                                    recomputeStreaksFromDom();
                                    window.setTimeout(syncFromServer, HABIT_REFRESH_DELAY_MS);
                                })
                                .catch(function(error) {
                                    console.error('Habit update failed', error);
                                    checkbox.checked = !checkbox.checked;
                                    if (label) {
                                        setUpdatedText(label, previousUpdated);
                                        delete label.dataset.pending;
                                        delete label.dataset.pendingDesired;
                                    }
                                    recomputeStreaksFromDom();
                                    showMessage('Failed to save habit. Please try again.', 'error');
                                });
                        });
                    });

                    if (refreshBtn) {
                        refreshBtn.addEventListener('click', function() {
                            if (!canSync) {
                                showMessage('Habit server not configured.', 'error');
                                return;
                            }
                            syncFromServer();
                        });
                        setRefreshEnabled(canSync);
                    }

                    if (canSync) {
                        window.setTimeout(syncFromServer, HABIT_REFRESH_DELAY_MS);
                    } else if (messageEl) {
                        showMessage('Habits shown from last export.', 'info');
                    }

                    recomputeStreaksFromDom();
                }

                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', initHabitCalendar);
                } else {
                    initHabitCalendar();
                }
            })();
            </script>
            """
        ).strip() + '\n'

        return ''.join(html_parts), script

    def _calculate_productivity_streak(self, log_list, date_list):
        """
        Calculate how long the user has been productive by tracing back from the current activity
        until hitting a non-productive activity. Returns duration in minutes and formatted string.
        Resets at the start of the day (defined by DAY_BOUNDARY_HOUR).
        """
        if not log_list or not date_list:
            return 0, "0 min"

        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)

        # Calculate the start of the current day based on DAY_BOUNDARY_HOUR
        current_date = now.date()
        day_start_time = pd.Timestamp.combine(
            current_date,
            datetime.time(hour=DAY_BOUNDARY_HOUR)
        ).tz_localize(tz)
        
        # If current time is before the boundary hour, the day actually started yesterday
        if now < day_start_time:
            day_start_time = pd.Timestamp.combine(
                current_date - datetime.timedelta(days=1),
                datetime.time(hour=DAY_BOUNDARY_HOUR)
            ).tz_localize(tz)

        # Use centralized category definitions
        # Idle and mail are neutral - we skip them when looking for current activity

        # Get recent activities from the most recent day(s)
        all_activities = []
        for date in date_list[:3]:  # Look at last 3 days max
            date_str = date.strftime('%Y-%m-%d')
            df = self._get_and_prepare_day_df(date_str)
            if not df.empty:
                df = resolve_conflicts(df)
                if not df.empty:
                    all_activities.append(df)

        if not all_activities:
            return 0, "0 min"

        combined_df = pd.concat(all_activities, ignore_index=True)
        combined_df = combined_df.sort_values('end_time', ascending=False).reset_index(drop=True)

        # Find the current or most recent activity
        if combined_df.empty:
            return 0, "0 min"

        # Start from the most recent non-idle, non-mail activity
        current_idx = -1
        for idx in range(len(combined_df)):
            category = str(combined_df.iloc[idx].get('category', '')).lower()
            if category not in {"idle", "mail"}:
                current_idx = idx
                break
        
        if current_idx == -1:
            return 0, "0 min"

        current_activity = combined_df.iloc[current_idx]
        current_category = str(current_activity.get('category', '')).lower()

        # Check if current meaningful activity is productive
        if not is_productive(current_category):
            return 0, "0 min"

        # Backtrace through activities accumulating productive time
        total_productive_minutes = 0
        streak_start_time = None
        
        # Get max idle break threshold from config (default 30 minutes)
        max_idle_break_minutes = self.config.getint('SETTINGS', 'max_idle_break_minutes', fallback=30)

        for idx in range(current_idx, len(combined_df)):
            activity = combined_df.iloc[idx]
            category = str(activity.get('category', '')).lower()
            
            # Check if this activity started before the day boundary - if so, stop
            if 'start_time' in activity:
                activity_start = activity['start_time']
                if activity_start < day_start_time:
                    break
            
            # Check idle duration - long idles break the streak
            if category == "idle":
                idle_duration_minutes = activity.get('duration', 0) / 60.0
                if idle_duration_minutes > max_idle_break_minutes:
                    # Long idle breaks the streak
                    break
                else:
                    # Short idle - skip it, streak continues
                    continue
            
            # Skip mail - it doesn't break the streak
            if category == "mail":
                continue
            
            # If we hit a non-productive activity, stop
            if is_wasted(category):
                break
            
            # If productive, accumulate the duration
            if is_productive(category):
                duration_seconds = activity.get('duration', 0)
                total_productive_minutes += duration_seconds / 60.0
                
                # Track the earliest start time of the streak
                if 'start_time' in activity:
                    activity_start = activity['start_time']
                    if streak_start_time is None or activity_start < streak_start_time:
                        streak_start_time = activity_start
            else:
                # Any other category (not categorized, family, self, etc.) breaks the streak
                break

        # Format the output
        if total_productive_minutes < 1:
            return total_productive_minutes, "< 1 min"
        elif total_productive_minutes < 60:
            return total_productive_minutes, f"{int(total_productive_minutes)} min"
        else:
            hours = int(total_productive_minutes // 60)
            minutes = int(total_productive_minutes % 60)
            return total_productive_minutes, f"{hours}h {minutes}min"

    def _calculate_longest_streak_for_day(self, date_str):
        """
        Calculate the longest productivity streak for a specific day.
        Returns (duration in minutes, formatted string, start time string).
        """
        df = self._get_and_prepare_day_df(date_str)
        if df.empty:
            return 0, "0 min", ""
        
        df = resolve_conflicts(df)
        if df.empty:
            return 0, "0 min", ""
        
        # Sort by start time
        df = df.sort_values('start_time').reset_index(drop=True)
        
        # Use centralized category definitions
        
        # Get max idle break threshold from config (default 30 minutes)
        max_idle_break_minutes = self.config.getint('SETTINGS', 'max_idle_break_minutes', fallback=30)
        
        max_streak_minutes = 0
        current_streak_minutes = 0
        max_streak_start_time = None
        current_streak_start_time = None
        
        for idx, activity in df.iterrows():
            category = str(activity.get('category', '')).lower()
            
            # Check idle duration - long idles break the streak
            if category == "idle":
                idle_duration_minutes = activity.get('duration', 0) / 60.0
                if idle_duration_minutes > max_idle_break_minutes:
                    # Long idle breaks the streak
                    current_streak_minutes = 0
                    current_streak_start_time = None
                # Short idle - skip it, streak continues
                continue
            
            # Skip mail
            if category == "mail":
                continue
            
            # If productive, add to current streak
            if is_productive(category):
                # Track start time of current streak
                if current_streak_minutes == 0 and 'start_time' in activity:
                    current_streak_start_time = activity['start_time']
                
                duration_seconds = activity.get('duration', 0)
                current_streak_minutes += duration_seconds / 60.0
                
                # Update max if current is longer
                if current_streak_minutes > max_streak_minutes:
                    max_streak_minutes = current_streak_minutes
                    max_streak_start_time = current_streak_start_time
            
            # If non-productive, reset streak
            elif is_wasted(category):
                current_streak_minutes = 0
                current_streak_start_time = None
            
            # Any other category (not categorized, family, self, etc.) also resets the streak
            else:
                current_streak_minutes = 0
                current_streak_start_time = None
        
        # Format the time string
        time_str = ""
        if max_streak_start_time:
            time_str = max_streak_start_time.strftime('%H:%M')
        
        # Format the duration output
        if max_streak_minutes < 1:
            return max_streak_minutes, "< 1 min", time_str
        elif max_streak_minutes < 60:
            return max_streak_minutes, f"{int(max_streak_minutes)} min", time_str
        else:
            hours = int(max_streak_minutes // 60)
            minutes = int(max_streak_minutes % 60)
            return max_streak_minutes, f"{hours}h {minutes}min", time_str

    def _calculate_longest_streak_recent_days(self, date_list, num_days=7):
        """
        Calculate the longest productivity streak across recent days.
        Returns (duration in minutes, formatted string, date string).
        """
        max_streak_minutes = 0
        max_streak_date = None
        
        for date in date_list[:num_days]:
            date_str = date.strftime('%Y-%m-%d')
            streak_min, _, _ = self._calculate_longest_streak_for_day(date_str)
            if streak_min > max_streak_minutes:
                max_streak_minutes = streak_min
                max_streak_date = date
        
        # Format the date string
        date_str = ""
        if max_streak_date:
            date_str = max_streak_date.strftime('%a, %b %d')  # e.g., "Mon, Nov 04"
        
        # Format the duration output
        if max_streak_minutes < 1:
            return max_streak_minutes, "< 1 min", date_str
        elif max_streak_minutes < 60:
            return max_streak_minutes, f"{int(max_streak_minutes)} min", date_str
        else:
            hours = int(max_streak_minutes // 60)
            minutes = int(max_streak_minutes % 60)
            return max_streak_minutes, f"{hours}h {minutes}min", date_str

    def _calculate_waste_ratio(self, log_list, date_list):
        """
        Calculate the ratio of wasted time vs total active time for today (excluding idle).
        Returns (waste_percentage, waste_display, total_active_hours, wasted_hours, total_hours)
        """
        if not log_list or not date_list:
            return 0, "0%", 0, 0, 0

        # Use existing analyze method to get category totals
        today_date = date_list[0]
        logfile = f"{today_date.strftime('%Y-%m-%d')}.csv"
        u_cats, u_dur, date, _ = self.analyze(logfile)
        
        if not u_cats or not u_dur:
            return 0, "0%", 0, 0, 0

        # Define wasted categories
        wasted_cats = {"wasted", "wasted time", "gaming"}
        
        # Calculate totals using existing category analysis (durations are in seconds)
        total_seconds = 0
        total_active_seconds = 0
        wasted_seconds = 0
        
        for category, duration in zip(u_cats, u_dur):
            total_seconds += duration  # Include all time
            if category.lower() != 'idle':  # Exclude idle time for active calculation
                total_active_seconds += duration
                if category.lower() in wasted_cats:
                    wasted_seconds += duration
        
        if total_active_seconds == 0:
            return 0, "0%", 0, 0, 0
            
        waste_percentage = (wasted_seconds / total_active_seconds) * 100
        
        # Format display
        if waste_percentage < 0.1:
            percentage_display = "< 0.1%"
        else:
            percentage_display = f"{waste_percentage:.1f}%"
            
        total_hours = total_seconds / 3600
        total_active_hours = total_active_seconds / 3600
        wasted_hours = wasted_seconds / 3600
        
        return waste_percentage, percentage_display, total_active_hours, wasted_hours, total_hours

    def _get_current_activity_category(self, log_list, date_list):
        """
        Get the category of the current/most recent meaningful activity.
        Returns the category string or None if no meaningful activity found.
        """
        if not log_list or not date_list:
            return None

        tz = pytz.timezone(TIMEZONE)

        # Get recent activities from the most recent day(s)
        all_activities = []
        for date in date_list[:3]:  # Look at last 3 days max
            date_str = date.strftime('%Y-%m-%d')
            df = self._get_and_prepare_day_df(date_str)
            if not df.empty:
                df = resolve_conflicts(df)
                if not df.empty:
                    all_activities.append(df)

        if not all_activities:
            return None

        combined_df = pd.concat(all_activities, ignore_index=True)
        combined_df = combined_df.sort_values('end_time', ascending=False).reset_index(drop=True)

        # Find the current or most recent meaningful activity (not idle/mail)
        for idx in range(len(combined_df)):
            category = str(combined_df.iloc[idx].get('category', '')).lower()
            if category not in {"idle", "mail"}:
                return category
        
        return None

    def _generate_bookmarks_html(self) -> str:
        """Generate HTML section for recent smart bookmarks with inline add/edit."""
        try:
            bookmarks = database.get_bookmarks(limit=10, include_archived=False)
        except Exception as e:
            print(f"WARNING: could not load bookmarks: {e}")
            bookmarks = []

        tz = pytz.timezone(TIMEZONE)
        count = len(bookmarks)

        bm_html = '''
    <div id="bookmarks-section" style="background-color: #f0f4ff; border: 1px solid #b8c9e8; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
        <h3 style="margin-top: 0; color: #333; font-size: 18px; display: flex; align-items: center; justify-content: space-between;">
            <span>\U0001f516 Smart Bookmarks</span>
            <span>
                <button onclick="document.getElementById('bm-add-form').style.display=document.getElementById('bm-add-form').style.display==='none'?'block':'none'" style="background:#4c6ef5; color:white; border:none; padding:4px 14px; border-radius:5px; cursor:pointer; font-size:13px; margin-right:6px;">+ Add Bookmark</button>
                <a href="bookmarks.html" style="font-size: 12px; font-weight: normal; color: #4c6ef5; text-decoration: none;" title="Manage all bookmarks">View All \u2192</a>
            </span>
        </h3>

        <!-- Inline Add Bookmark Form (hidden by default) -->
        <div id="bm-add-form" style="display:none; background:#fff; border:1px solid #c5d0e0; border-radius:6px; padding:12px; margin-bottom:12px;">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:8px;">
                <div>
                    <label style="font-size:12px; color:#555; font-weight:600;">URL *</label>
                    <input type="text" id="bm-url" placeholder="https://example.com/article" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div>
                    <label style="font-size:12px; color:#555; font-weight:600;">Title</label>
                    <input type="text" id="bm-title" placeholder="Page title (auto-filled by bookmarklet)" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
            </div>
            <div style="margin-bottom:8px;">
                <label style="font-size:12px; color:#555; font-weight:600;">Summary</label>
                <input type="text" id="bm-summary" placeholder="Brief description of the page" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
            </div>
            <div style="display:grid; grid-template-columns:2fr 1fr; gap:8px; margin-bottom:8px;">
                <div>
                    <label style="font-size:12px; color:#555; font-weight:600;">Notes (why save this?)</label>
                    <input type="text" id="bm-notes" placeholder="Your personal notes on why to revisit" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div>
                    <label style="font-size:12px; color:#555; font-weight:600;">Tags (comma-separated)</label>
                    <input type="text" id="bm-tags" placeholder="ai, tutorial, reference" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
            </div>
            <div style="text-align:right;">
                <button onclick="document.getElementById('bm-add-form').style.display='none'" style="background:#e0e0e0; color:#333; border:none; padding:5px 14px; border-radius:4px; cursor:pointer; font-size:13px; margin-right:6px;">Cancel</button>
                <button onclick="addBookmarkFromForm()" style="background:#4c6ef5; color:white; border:none; padding:5px 14px; border-radius:4px; cursor:pointer; font-size:13px;">Save Bookmark</button>
            </div>
        </div>
'''

        if not bookmarks:
            bm_html += '''
        <div style="text-align:center; padding:20px; color:#888; font-size:14px;">
            No bookmarks yet. Click <b>+ Add Bookmark</b> above, or install the
            <a href="bookmarklet.html" target="_blank" style="color:#4c6ef5;">browser bookmarklet</a>
            to save pages while browsing.
        </div>
'''
        else:
            bm_html += '''
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="background: #dbe4f0; text-align: left;">
                    <th style="padding: 6px 8px; border: 1px solid #c5d0e0;">Title</th>
                    <th style="padding: 6px 8px; border: 1px solid #c5d0e0; max-width: 300px;">Summary</th>
                    <th style="padding: 6px 8px; border: 1px solid #c5d0e0;">Notes</th>
                    <th style="padding: 6px 8px; border: 1px solid #c5d0e0;">Tags</th>
                    <th style="padding: 6px 8px; border: 1px solid #c5d0e0;">Saved</th>
                    <th style="padding: 6px 8px; border: 1px solid #c5d0e0; width: 60px;">Actions</th>
                </tr>
            </thead>
            <tbody>
'''
            for bm in bookmarks:
                title_raw = bm.get('title') or bm.get('url', '')
                url = html.escape(bm.get('url', ''))
                summary_raw = bm.get('summary') or ''
                notes_raw = bm.get('notes') or ''
                tags_raw = bm.get('tags') or ''
                bm_id = bm.get('id', '')

                title = html.escape(title_raw)
                if len(title) > 60:
                    title = title[:57] + '...'
                summary = html.escape(summary_raw)
                if len(summary) > 120:
                    summary = summary[:117] + '...'
                notes_escaped = html.escape(notes_raw)

                ts = bm.get('timestamp')
                time_str = ''
                if ts:
                    try:
                        dt = datetime.datetime.fromtimestamp(float(ts), tz)
                        time_str = dt.strftime('%b %d %H:%M')
                    except Exception:
                        pass

                screenshot = bm.get('screenshot_path')
                thumb_html = ''
                if screenshot:
                    thumb_html = f'<img src="http://127.0.0.1:8042/bookmark_screenshots/{html.escape(screenshot)}" style="max-height:30px; max-width:50px; border-radius:3px; margin-right:6px; vertical-align:middle;" title="Screenshot">'

                tag_badges = ''
                if tags_raw:
                    for tag in tags_raw.split(','):
                        tag = tag.strip()
                        if tag:
                            tag_badges += f'<span style="background:#4c6ef5; color:white; padding:1px 6px; border-radius:10px; font-size:11px; margin-right:3px;">{html.escape(tag)}</span>'

                # Notes cell is editable: click to edit inline
                notes_json = html.escape(json.dumps(notes_raw))
                title_json = html.escape(json.dumps(title_raw))
                summary_json = html.escape(json.dumps(summary_raw))
                tags_json = html.escape(json.dumps(tags_raw))
                url_json = html.escape(json.dumps(bm.get('url', '')))
                bm_html += f'''                <tr style="border-bottom: 1px solid #dde3ee;" data-bookmark-id="{bm_id}">
                    <td style="padding: 6px 8px; border: 1px solid #e0e6f0;">{thumb_html}<a href="{url}" target="_blank" style="color: #2563eb; text-decoration: none;" title="{url}">{title}</a></td>
                    <td style="padding: 6px 8px; border: 1px solid #e0e6f0; max-width: 300px; color: #555;">{summary}</td>
                    <td style="padding: 6px 8px; border: 1px solid #e0e6f0; color: #666; font-style: italic; cursor:pointer;" onclick="editBookmarkNotes({bm_id}, this)" title="Click to edit notes" id="bm-notes-{bm_id}">{notes_escaped}</td>
                    <td style="padding: 6px 8px; border: 1px solid #e0e6f0;">{tag_badges}</td>
                    <td style="padding: 6px 8px; border: 1px solid #e0e6f0; white-space: nowrap; color: #888;">{time_str}</td>
                    <td style="padding: 6px 8px; border: 1px solid #e0e6f0; text-align: center; white-space: nowrap;">
                        <button onclick='openEditBookmark({bm_id}, {title_json}, {summary_json}, {notes_json}, {tags_json}, {url_json})' title="Edit all fields" style="background:none; border:none; cursor:pointer; font-size:13px; color:#4c6ef5;">\u270e</button>
                        <button onclick="archiveBookmark({bm_id})" title="Archive" style="background:none; border:none; cursor:pointer; font-size:13px; color:#999;">\u2716</button>
                    </td>
                </tr>
'''

            bm_html += '''            </tbody>
        </table>
'''

        bm_html += f'''
        <div style="margin-top: 10px; display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #888;">
            <span>
                <a href="bookmarklet.html" target="_blank" style="color:#4c6ef5; text-decoration:none;">
                    \U0001f4cc Install browser bookmarklet
                </a>
                &mdash; one click to save any page while browsing
            </span>
            <span>{count} bookmark{"s" if count != 1 else ""} &middot;
                <a href="bookmarks.html" style="color:#4c6ef5; text-decoration:none;">Manage all bookmarks</a>
            </span>
        </div>
    </div>

    <script>
    function addBookmarkFromForm() {{
        const url = document.getElementById('bm-url').value.trim();
        if (!url) {{ alert('URL is required'); return; }}
        const payload = {{
            url: url,
            title: document.getElementById('bm-title').value.trim() || null,
            summary: document.getElementById('bm-summary').value.trim() || null,
            notes: document.getElementById('bm-notes').value.trim() || null,
            tags: document.getElementById('bm-tags').value.trim() || null,
            timestamp: Date.now() / 1000
        }};
        fetch('http://127.0.0.1:8042/bookmarks/add', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(payload)
        }})
        .then(r => r.json())
        .then(data => {{
            if (data.status === 'success') {{
                alert('Bookmark saved!' + (data.bookmark && data.bookmark.title ? '\\nTitle: ' + data.bookmark.title : '') + (data.bookmark && data.bookmark.summary ? '\\nSummary: ' + data.bookmark.summary : ''));
                location.reload();
            }} else {{
                alert('Failed: ' + (data.error || 'Unknown error'));
            }}
        }})
        .catch(err => alert('Error: ' + err.message));
    }}

    function archiveBookmark(id) {{
        if (!confirm('Archive this bookmark?')) return;
        fetch('http://127.0.0.1:8042/bookmarks/update', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{id: id, archived: 1}})
        }}).then(r => r.json()).then(data => {{
            if (data.status === 'success') {{
                const row = document.querySelector('tr[data-bookmark-id="' + id + '"]');
                if (row) row.style.display = 'none';
            }}
        }}).catch(err => console.error('Archive failed:', err));
    }}

    function editBookmarkNotes(id, cell) {{
        const current = cell.innerText;
        const input = document.createElement('input');
        input.type = 'text';
        input.value = current;
        input.style.cssText = 'width:100%; padding:3px 6px; border:1px solid #4c6ef5; border-radius:3px; font-size:13px; box-sizing:border-box;';
        cell.innerHTML = '';
        cell.appendChild(input);
        input.focus();
        input.select();

        function save() {{
            const newNotes = input.value.trim();
            fetch('http://127.0.0.1:8042/bookmarks/update', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{id: id, notes: newNotes}})
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.status === 'success') {{
                    cell.innerText = newNotes;
                }} else {{
                    cell.innerText = current;
                    alert('Failed to update notes');
                }}
            }})
            .catch(() => {{ cell.innerText = current; }});
        }}

        input.addEventListener('blur', save);
        input.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter') {{ e.preventDefault(); input.blur(); }}
            if (e.key === 'Escape') {{ cell.innerText = current; }}
        }});
    }}

    /* --- Full Edit Modal --- */
    function openEditBookmark(id, title, summary, notes, tags, url) {{
        // Remove existing modal if any
        const old = document.getElementById('bm-edit-modal');
        if (old) old.remove();

        const modal = document.createElement('div');
        modal.id = 'bm-edit-modal';
        modal.style.cssText = 'position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.4); z-index:10000; display:flex; align-items:center; justify-content:center;';
        modal.innerHTML = `
            <div style="background:white; border-radius:10px; padding:20px; width:520px; max-width:95vw; box-shadow:0 8px 30px rgba(0,0,0,0.25); font-family:Verdana,sans-serif;">
                <h3 style="margin:0 0 14px 0; color:#2563eb; font-size:16px;">\\u270e Edit Bookmark #${{id}}</h3>
                <div style="margin-bottom:10px;">
                    <label style="font-size:12px; color:#555; font-weight:600; display:block; margin-bottom:3px;">URL</label>
                    <input id="bm-edit-url" type="text" value="${{url.replace(/"/g, '&quot;')}}" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div style="margin-bottom:10px;">
                    <label style="font-size:12px; color:#555; font-weight:600; display:block; margin-bottom:3px;">Title</label>
                    <input id="bm-edit-title" type="text" value="${{title.replace(/"/g, '&quot;')}}" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div style="margin-bottom:10px;">
                    <label style="font-size:12px; color:#555; font-weight:600; display:block; margin-bottom:3px;">Summary <span style="color:#999; font-weight:normal;">(AI-generated if left empty on creation)</span></label>
                    <input id="bm-edit-summary" type="text" value="${{summary.replace(/"/g, '&quot;')}}" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div style="margin-bottom:10px;">
                    <label style="font-size:12px; color:#555; font-weight:600; display:block; margin-bottom:3px;">Notes</label>
                    <input id="bm-edit-notes" type="text" value="${{notes.replace(/"/g, '&quot;')}}" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div style="margin-bottom:14px;">
                    <label style="font-size:12px; color:#555; font-weight:600; display:block; margin-bottom:3px;">Tags <span style="color:#999; font-weight:normal;">(comma-separated)</span></label>
                    <input id="bm-edit-tags" type="text" value="${{tags.replace(/"/g, '&quot;')}}" style="width:100%; padding:5px 8px; border:1px solid #ccc; border-radius:4px; font-size:13px; box-sizing:border-box;">
                </div>
                <div style="text-align:right;">
                    <button onclick="document.getElementById('bm-edit-modal').remove()" style="background:#e0e0e0; color:#333; border:none; padding:6px 16px; border-radius:4px; cursor:pointer; font-size:13px; margin-right:6px;">Cancel</button>
                    <button onclick="saveEditBookmark(${{id}})" style="background:#4c6ef5; color:white; border:none; padding:6px 16px; border-radius:4px; cursor:pointer; font-size:13px;">Save Changes</button>
                </div>
            </div>`;
        document.body.appendChild(modal);
        // Close on backdrop click
        modal.addEventListener('click', function(e) {{ if (e.target === modal) modal.remove(); }});
    }}

    function saveEditBookmark(id) {{
        const payload = {{
            id: id,
            url: document.getElementById('bm-edit-url').value.trim(),
            title: document.getElementById('bm-edit-title').value.trim(),
            summary: document.getElementById('bm-edit-summary').value.trim(),
            notes: document.getElementById('bm-edit-notes').value.trim(),
            tags: document.getElementById('bm-edit-tags').value.trim()
        }};
        fetch('http://127.0.0.1:8042/bookmarks/update', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(payload)
        }})
        .then(r => r.json())
        .then(data => {{
            if (data.status === 'success') {{
                document.getElementById('bm-edit-modal').remove();
                location.reload();
            }} else {{
                alert('Failed: ' + (data.error || 'Unknown'));
            }}
        }})
        .catch(err => alert('Error: ' + err.message));
    }}
    </script>
'''
        return bm_html

    def _build_recent_activity_section(self, log_list, date_list, minutes=12):
        if not log_list or not date_list:
            return ''

        # Find the most recent activities within the last N minutes
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)

        # Use the latest log file
        latest_date = date_list[0]
        date_str = latest_date.strftime('%Y-%m-%d')
        df = self._get_and_prepare_day_df(date_str)
        if df.empty:
            return ''

        df = resolve_conflicts(df)
        if df.empty:
            return ''

        df = self._ensure_url_columns(df)
        df['Duration (min)'] = (df['duration'] / 60).round(1)

        # Filter by end_time within the last N minutes
        if 'end_time' in df:
            cutoff = now - datetime.timedelta(minutes=minutes)
            df = df[df['end_time'] >= cutoff]
        df = df.sort_values('end_time', ascending=False)

        # Collapse repeated entries within the window by grouping on window metadata
        for col in ['category', 'window_title', 'window_url', 'url_display']:
            if col not in df.columns:
                df[col] = ''
            else:
                df[col] = df[col].fillna('')

        grouped = (
            df.groupby(['category', 'window_title', 'window_url', 'url_display'], dropna=False)
              .agg({
                  'start_time': 'max',
                  'end_time': 'max',
                  'Duration (min)': 'sum'
              })
              .reset_index()
        )

        df = grouped.sort_values('end_time', ascending=False)

        if df.empty:
            return ''

        # Use centralized category definitions
        productive_cats = RECENT_ACTIVITY_PRODUCTIVE
        distracted_cats = RECENT_ACTIVITY_DISTRACTED

        rows = []
        for _, row in df.iterrows():
            start_time = row['start_time'].strftime('%H:%M') if 'start_time' in row else ''
            category = html.escape(str(row.get('category', '') or ''))
            if not category:
                category = '—'

            window_title = html.escape(str(row.get('window_title', '') or ''))
            if not window_title:
                window_title = '—'

            full_url = row.get('window_url')
            display_url = row.get('url_display') or full_url or ''
            display_url_escaped = html.escape(str(display_url)) if display_url else ''

            if display_url_escaped:
                if isinstance(full_url, str) and full_url.startswith(('http://', 'https://')):
                    url_cell = f'<a href="{html.escape(full_url, quote=True)}" target="_blank" rel="noopener">{display_url_escaped}</a>'
                else:
                    url_cell = display_url_escaped
            else:
                url_cell = '—'

            duration_value = row.get('Duration (min)', 0)
            try:
                duration_str = f"{float(duration_value):.1f}"
            except (TypeError, ValueError):
                duration_str = '0.0'

            row_style = ""
            if category in productive_cats:
                row_style = 'style="background-color: #D9F7D9;"'
            elif category in distracted_cats:
                row_style = 'style="background-color: pink;"'

            rows.append(
                f'<tr {row_style}>'
                f'<td>{start_time}</td>'
                f'<td>{category}</td>'
                f'<td>{window_title}</td>'
                f'<td>{url_cell}</td>'
                f'<td style="text-align:right">{duration_str}</td>'
                '</tr>'
            )

        if not rows:
            return ''

        header = f'<h2 id="recent-activity">Recent Activity (last {minutes} min) – {latest_date.strftime("%B %d, %Y")}</h2>'

        table = [
            '<table class="recent-activity" style="width:100%; border-collapse:collapse;">',
            '<tr>'
            '<th style="text-align:left; padding:4px;">Start</th>'
            '<th style="text-align:left; padding:4px;">Category</th>'
            '<th style="text-align:left; padding:4px;">Window</th>'
            '<th style="text-align:left; padding:4px;">URL</th>'
            '<th style="text-align:right; padding:4px;">Duration (min)</th>'
            '</tr>'
        ]

        for row_html in rows:
            table.append(row_html)

        table.append('</table>')

        return header + '\n' + '\n'.join(table)

    def _get_week_id(self, dt=None):
        """Get week identifier (Monday date format) for a given datetime. Resets on Saturday at noon."""
        tz = pytz.timezone(TIMEZONE)
        if dt is None:
            dt = datetime.datetime.now(tz)
        
        # Ensure dt is timezone aware for consistency
        if dt.tzinfo is None:
            dt = tz.localize(dt)

        # Calculate Monday of this week (weekday is 0 for Monday)
        monday = (dt - datetime.timedelta(days=dt.weekday())).date()
        
        # If it's Saturday >= 12:00 or Sunday, shift to next Monday
        if (dt.weekday() == 5 and dt.hour >= 12) or dt.weekday() == 6:
            monday += datetime.timedelta(days=7)
            
        return monday.strftime('%Y-%m-%d')
    
    def _parse_must_done_config(self):
        """Parse MUST_DONE section from config.dat."""
        tasks = []
        if not self.config.has_section('MUST_DONE'):
            return tasks
        
        for task_id in self.config.options('MUST_DONE'):
            task_def = self.config.get('MUST_DONE', task_id)
            parts = [p.strip() for p in task_def.split(',', 2)]
            if len(parts) == 3:
                day_name, time_str, description = parts
                tasks.append({
                    'id': task_id,
                    'day': day_name,  # e.g., "Saturday"
                    'time': time_str,  # e.g., "23:59"
                    'description': description
                })
        return tasks
    
    def _get_must_done_deadline(self, task, week_start=None):
        """Calculate the deadline datetime for a task in the current week."""
        tz = pytz.timezone(TIMEZONE)
        if week_start is None:
            now = datetime.datetime.now(tz)
            # Use unified week_id logic
            week_id = self._get_week_id(now)
            target_monday = datetime.datetime.strptime(week_id, '%Y-%m-%d').date()
            # Sunday 00:00 before the target Monday
            week_start = tz.localize(datetime.datetime.combine(target_monday - datetime.timedelta(days=1), datetime.time(0, 0)))
        
        # Map day names to weekday numbers (Sunday=0)
        day_map = {
            'sunday': 0, 'monday': 1, 'tuesday': 2, 'wednesday': 3,
            'thursday': 4, 'friday': 5, 'saturday': 6
        }
        
        day_num = day_map.get(task['day'].lower())
        if day_num is None:
            return None
        
        # Calculate the target day
        target_day = week_start + datetime.timedelta(days=day_num)
        
        # Parse time
        try:
            hour, minute = map(int, task['time'].split(':'))
            deadline = target_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return deadline
        except:
            return None
    
    def _get_must_done_status(self, task_id, week_id):
        """Check if a task is completed for the given week."""
        try:
            conn = sqlite3.connect(database.DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT completed, completed_at FROM must_done_items WHERE task_id = ? AND week_id = ?",
                (task_id, week_id)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return {'completed': bool(row[0]), 'completed_at': row[1]}
            return {'completed': False, 'completed_at': None}
        except:
            return {'completed': False, 'completed_at': None}
    
    def _build_must_done_section(self):
        """Build the Must Done section HTML."""
        tasks = self._parse_must_done_config()
        if not tasks:
            return ''
        
        tz = pytz.timezone(TIMEZONE)
        now = datetime.datetime.now(tz)
        week_id = self._get_week_id(now)
        month_id = now.strftime('%Y-%m')
        today_id = now.strftime('%Y-%m-%d')
        
        # Calculate logical boundaries for display
        target_monday = datetime.datetime.strptime(week_id, '%Y-%m-%d').date()
        # display_week_start: Previous Saturday 12:00 (when this week's tasks appeared)
        display_week_start = datetime.datetime.combine(target_monday - datetime.timedelta(days=2), datetime.time(12, 0))
        display_week_start = tz.localize(display_week_start)
        # display_week_end: Following Saturday 11:59:59 (when they reset)
        display_week_end = datetime.datetime.combine(target_monday + datetime.timedelta(days=5), datetime.time(11, 59, 59))
        display_week_end = tz.localize(display_week_end)
        next_reset = display_week_end + datetime.timedelta(seconds=1)
        
        html_parts = [
            '<div id="must-done-section" class="must-done-section" style="margin:20px 0; padding:15px; border:2px solid #333; border-radius:8px; background:#fff;">',
            f'<h2 style="margin-top:0; color:#333;">📋 Must Done This Week</h2>',
            f'<div style="color:#666; font-size:0.9em; margin-bottom:10px;">Week of {target_monday.strftime("%b %d")} (Reset on {next_reset.strftime("%a %I:%M %p")}).</div>',
            '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:14px; align-items:start;">',
            '<div id="must-done-weekly" style="min-width:0;">',
            '<h3 style="margin:0 0 8px 0; color:#333;">This Week</h3>',
            '<div id="must-done-sync-status" style="color:#666; font-size:0.85em; margin:-6px 0 10px 0;">Last synced: —</div>',
            '<div id="must-done-weekly-items" style="display:flex; flex-direction:column; gap:10px;">'
        ]
        
        for task in tasks:
            deadline = self._get_must_done_deadline(task)
            status = self._get_must_done_status(task['id'], week_id)
            
            if deadline is None:
                continue
            
            # Calculate time until deadline
            time_until = deadline - now
            hours_until = time_until.total_seconds() / 3600
            
            # Determine status color and urgency
            if status['completed']:
                bg_color = '#d4edda'  # Green
                border_color = '#28a745'
                status_icon = '✅'
                completed_time = datetime.datetime.fromtimestamp(status['completed_at'], tz)
                # Calculate how long ago it was completed
                time_since = now - completed_time
                if time_since.days > 0:
                    time_ago = f"{time_since.days}d ago"
                elif time_since.seconds > 3600:
                    time_ago = f"{time_since.seconds // 3600}h ago"
                else:
                    time_ago = f"{time_since.seconds // 60}m ago"
                status_text = f"✓ Completed {completed_time.strftime('%a %I:%M %p')} ({time_ago})"
                font_size = '1em'
            elif hours_until < 0:
                bg_color = '#f8d7da'  # Red
                border_color = '#dc3545'
                status_icon = '🔴'
                status_text = f'OVERDUE by {abs(int(hours_until))}h'
                font_size = '1.2em'
            elif hours_until < 24:
                bg_color = '#fff3cd'  # Yellow
                border_color = '#ffc107'
                status_icon = '🟡'
                status_text = f'Due in {int(hours_until)}h'
                font_size = '1.1em'
            else:
                bg_color = '#e7f3ff'  # Blue
                border_color = '#0066cc'
                status_icon = '⏰'
                status_text = f'Due {deadline.strftime("%a %I:%M %p")}'
                font_size = '1em'
            
            # Build task HTML
            checked = 'checked' if status['completed'] else ''
            checkbox_html = f'<input type="checkbox" class="must-done-checkbox" data-task-id="{task["id"]}" data-week-id="{week_id}" {checked} style="width:20px; height:20px; margin-right:10px; cursor:pointer;">'
            
            html_parts.append(f'''
                <div class="must-done-item" style="display:flex; align-items:center; padding:12px; background:{bg_color}; border:2px solid {border_color}; border-radius:6px; font-size:{font_size};">
                    {checkbox_html}
                    <div style="flex:1;">
                        <div style="font-weight:bold; font-size:1.1em;">{status_icon} {task['description']}</div>
                        <div style="color:#666; font-size:0.9em; margin-top:4px;">{status_text}</div>
                    </div>
                </div>
            ''')

        # Close weekly list + weekly column
        html_parts.append('</div>')
        html_parts.append('</div>')

        # --- Ad-hoc "Must be Done" items (user-created) ---
        html_parts.append(f'''
            <div id="must-be-done" style="min-width:0;">
                <h3 style="margin:0 0 8px 0; color:#333;">🧾 Must be Done</h3>
                <div style="color:#666; font-size:0.9em; margin-bottom:10px;">Quick add ad-hoc tasks (today / weekly / monthly / persistent).</div>
                <div id="must-be-done-meta" data-week-id="{week_id}" data-month-id="{month_id}" data-today-id="{today_id}"></div>

                <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:10px;">
                    <input id="must-be-done-input" type="text" placeholder="Add a task (e.g., pay taxes, take a shower)" 
                        style="flex:1; min-width:220px; padding:10px 12px; border:1px solid #bbb; border-radius:8px; font-size:1em;">
                    <select id="must-be-done-bucket" style="padding:10px 12px; border:1px solid #bbb; border-radius:8px; font-size:1em;">
                        <option value="today" selected>Today</option>
                        <option value="week">This week</option>
                        <option value="month">This month</option>
                        <option value="persistent">Persistent</option>
                    </select>
                    <button id="must-be-done-add" type="button" 
                        style="padding:10px 14px; border:0; border-radius:8px; background:#333; color:#fff; font-weight:700; cursor:pointer;">
                        Add
                    </button>
                </div>

                <div id="must-be-done-status" style="color:#666; font-size:0.85em; margin:-4px 0 10px 0;">—</div>
                <div id="must-be-done-list" style="display:flex; flex-direction:column; gap:10px;"></div>
            </div>
        ''')

        # Close the two-column grid
        html_parts.append('</div>')
        
        # Add JavaScript for checkbox handling
        html_parts.append('''
<script>
document.addEventListener('DOMContentLoaded', function() {
    const checkboxes = document.querySelectorAll('.must-done-checkbox');
    const syncStatusEl = document.getElementById('must-done-sync-status');

    // --- Must be Done (ad-hoc) ---
    const mustBeDoneMeta = document.getElementById('must-be-done-meta');
    const mustBeDoneInput = document.getElementById('must-be-done-input');
    const mustBeDoneBucket = document.getElementById('must-be-done-bucket');
    const mustBeDoneAddBtn = document.getElementById('must-be-done-add');
    const mustBeDoneList = document.getElementById('must-be-done-list');
    const mustBeDoneStatus = document.getElementById('must-be-done-status');

    function setMustBeDoneStatus(text, tone) {
        if (!mustBeDoneStatus) return;
        mustBeDoneStatus.textContent = text;
        if (tone === 'error') {
            mustBeDoneStatus.style.color = '#b00020';
        } else if (tone === 'success') {
            mustBeDoneStatus.style.color = '#2e7d32';
        } else {
            mustBeDoneStatus.style.color = '#666';
        }
    }

    function bucketLabel(bucketType) {
        if (bucketType === 'today') return 'today';
        if (bucketType === 'month') return 'monthly';
        if (bucketType === 'persistent') return 'persistent';
        return 'weekly';
    }

    function renderMustBeDoneItems(items) {
        if (!mustBeDoneList) return;
        mustBeDoneList.innerHTML = '';
        if (!items || items.length === 0) {
            const empty = document.createElement('div');
            empty.textContent = 'No ad-hoc items yet.';
            empty.style.color = '#777';
            empty.style.fontSize = '0.95em';
            mustBeDoneList.appendChild(empty);
            return;
        }

        items.forEach(item => {
            const row = document.createElement('div');
            row.className = 'must-be-done-item';
            row.style.display = 'flex';
            row.style.alignItems = 'center';
            row.style.padding = '10px 12px';
            const isExpired = !!item.expired;
            row.style.background = item.completed ? '#f3f6f3' : (isExpired ? '#fde8e8' : '#ffffff');
            row.style.border = '1px solid rgba(0,0,0,0.12)';
            row.style.borderLeft = item.completed ? '6px solid #9e9e9e' : (isExpired ? '6px solid #d32f2f' : '6px solid #333');
            row.style.borderRadius = '8px';
            row.style.gap = '10px';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = !!item.completed;
            cb.style.width = '20px';
            cb.style.height = '20px';
            cb.style.cursor = 'pointer';
            cb.addEventListener('change', () => {
                const completed = cb.checked;
                row.style.opacity = '0.6';
                if (typeof window.__setRefreshLock === 'function') {
                    window.__setRefreshLock('must_be_done:' + item.id, true);
                }
                setMustBeDoneStatus('Saving…', 'info');
                fetch('http://127.0.0.1:8042/must_be_done/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: item.id, completed })
                })
                .then(resp => resp.ok ? resp.json() : Promise.reject(new Error('Status ' + resp.status)))
                .then(data => {
                    if (!data || data.status !== 'success') throw new Error('Save failed');
                    loadMustBeDone();
                })
                .catch(err => {
                    console.warn('Must be done update failed:', err);
                    cb.checked = !completed;
                    row.style.opacity = '1';
                    setMustBeDoneStatus('Save failed (server unreachable)', 'error');
                })
                .finally(() => {
                    if (typeof window.__setRefreshLock === 'function') {
                        window.__setRefreshLock('must_be_done:' + item.id, false);
                    }
                });
            });

            const textWrap = document.createElement('div');
            textWrap.style.flex = '1';
            const title = document.createElement('div');
            title.textContent = item.description || '(empty)';
            title.style.fontWeight = '800';
            title.style.color = '#222';
            title.style.textDecoration = item.completed ? 'line-through' : 'none';

            const meta = document.createElement('div');
            let metaText = bucketLabel(item.bucket_type) + (isExpired ? ' • expired' : '');
            if (item.completed && item.completed_at) {
                const completedDate = new Date(item.completed_at * 1000);
                const timeStr = completedDate.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                metaText += ' • ✓ ' + timeStr;
            }
            meta.textContent = metaText;
            meta.style.color = isExpired ? '#b00020' : '#666';
            meta.style.fontSize = '0.85em';
            meta.style.marginTop = '2px';

            textWrap.appendChild(title);
            textWrap.appendChild(meta);

            const del = document.createElement('button');
            del.type = 'button';
            del.textContent = 'Delete';
            del.style.cursor = 'pointer';
            del.style.border = '1px solid rgba(0,0,0,0.18)';
            del.style.background = '#fff';
            del.style.borderRadius = '8px';
            del.style.padding = '6px 10px';
            del.style.fontWeight = '700';
            del.style.color = '#333';
            del.addEventListener('click', () => {
                if (!confirm('Delete this item?')) return;
                row.style.opacity = '0.6';
                if (typeof window.__setRefreshLock === 'function') {
                    window.__setRefreshLock('must_be_done:' + item.id, true);
                }
                setMustBeDoneStatus('Deleting…', 'info');
                fetch('http://127.0.0.1:8042/must_be_done/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: item.id })
                })
                .then(resp => resp.ok ? resp.json() : Promise.reject(new Error('Status ' + resp.status)))
                .then(data => {
                    if (!data || data.status !== 'success') throw new Error('Delete failed');
                    loadMustBeDone();
                })
                .catch(err => {
                    console.warn('Must be done delete failed:', err);
                    row.style.opacity = '1';
                    setMustBeDoneStatus('Delete failed (server unreachable)', 'error');
                })
                .finally(() => {
                    if (typeof window.__setRefreshLock === 'function') {
                        window.__setRefreshLock('must_be_done:' + item.id, false);
                    }
                });
            });

            row.appendChild(cb);
            row.appendChild(textWrap);
            row.appendChild(del);
            mustBeDoneList.appendChild(row);
        });
    }

    function getMustBeDoneBucketId(bucketType, weekId, monthId, todayId) {
        if (bucketType === 'today') return todayId;
        if (bucketType === 'month') return monthId;
        if (bucketType === 'persistent') return 'all';
        return weekId;
    }

    function loadMustBeDone() {
        if (!mustBeDoneMeta) return;
        const weekId = mustBeDoneMeta.getAttribute('data-week-id');
        const monthId = mustBeDoneMeta.getAttribute('data-month-id');
        const todayId = mustBeDoneMeta.getAttribute('data-today-id');
        setMustBeDoneStatus('Syncing…', 'info');
        fetch('http://127.0.0.1:8042/must_be_done/list?week_id=' + encodeURIComponent(weekId || '') + '&month_id=' + encodeURIComponent(monthId || '') + '&today_id=' + encodeURIComponent(todayId || '') + '&include_persistent=1&include_completed=1&include_expired=1&weeks_back=12&months_back=6&days_back=7')
            .then(resp => resp.ok ? resp.json() : Promise.reject(new Error('Status ' + resp.status)))
            .then(data => {
                if (!data || data.status !== 'success') throw new Error('Bad payload');
                renderMustBeDoneItems(data.items || []);
                const now = new Date();
                const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                setMustBeDoneStatus('Last synced: ' + timeStr, 'success');
            })
            .catch(err => {
                console.warn('Must be done sync failed:', err);
                const msg = (err && err.message) ? String(err.message) : '';
                if (msg.startsWith('Status ')) {
                    setMustBeDoneStatus('Last synced: failed (' + msg + ' — restart habit_server)', 'error');
                } else {
                    setMustBeDoneStatus('Last synced: failed (server unreachable)', 'error');
                }
            });
    }

    if (mustBeDoneAddBtn) {
        mustBeDoneAddBtn.addEventListener('click', () => {
            if (!mustBeDoneMeta || !mustBeDoneInput || !mustBeDoneBucket) return;
            const weekId = mustBeDoneMeta.getAttribute('data-week-id');
            const monthId = mustBeDoneMeta.getAttribute('data-month-id');
            const todayId = mustBeDoneMeta.getAttribute('data-today-id');
            const description = (mustBeDoneInput.value || '').trim();
            const bucketType = (mustBeDoneBucket.value || 'today').trim();
            const bucketId = getMustBeDoneBucketId(bucketType, weekId, monthId, todayId);
            if (!description) return;

            if (typeof window.__setRefreshLock === 'function') {
                window.__setRefreshLock('must_be_done:add', true);
            }
            setMustBeDoneStatus('Adding…', 'info');
            fetch('http://127.0.0.1:8042/must_be_done/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bucket_type: bucketType, bucket_id: bucketId, description })
            })
            .then(resp => resp.ok ? resp.json() : Promise.reject(new Error('Status ' + resp.status)))
            .then(data => {
                if (!data || data.status !== 'success') throw new Error('Add failed');
                mustBeDoneInput.value = '';
                // Clear typing lock once the draft is submitted.
                if (typeof window.__setRefreshLock === 'function') {
                    window.__setRefreshLock('must_be_done_typing', false);
                }
                loadMustBeDone();
            })
            .catch(err => {
                console.warn('Must be done add failed:', err);
                setMustBeDoneStatus('Add failed (server unreachable)', 'error');
            })
            .finally(() => {
                if (typeof window.__setRefreshLock === 'function') {
                    window.__setRefreshLock('must_be_done:add', false);
                }
            });
        });
    }

    if (mustBeDoneInput) {
        const updateMustBeDoneTypingLock = () => {
            if (typeof window.__setRefreshLock !== 'function') return;
            const hasDraft = (mustBeDoneInput.value || '').trim().length > 0;
            const isFocused = (document.activeElement === mustBeDoneInput);
            // Lock refresh while focused OR while there's an unsaved draft.
            window.__setRefreshLock('must_be_done_typing', hasDraft || isFocused);
        };

        mustBeDoneInput.addEventListener('focus', updateMustBeDoneTypingLock);
        mustBeDoneInput.addEventListener('blur', updateMustBeDoneTypingLock);
        mustBeDoneInput.addEventListener('input', updateMustBeDoneTypingLock);

        mustBeDoneInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (mustBeDoneAddBtn) mustBeDoneAddBtn.click();
            }
        });

        // Initialize lock state on load.
        updateMustBeDoneTypingLock();
    }

    function setSyncStatus(text, tone) {
        if (!syncStatusEl) return;
        syncStatusEl.textContent = text;
        if (tone === 'error') {
            syncStatusEl.style.color = '#b00020';
        } else if (tone === 'success') {
            syncStatusEl.style.color = '#2e7d32';
        } else {
            syncStatusEl.style.color = '#666';
        }
    }

    // Keep Must Done state in sync with the habit server so periodic page reloads
    // don't revert to stale HTML-exported checkbox values.
    function syncMustDoneFromServer(weekId) {
        if (!weekId) return;
        setSyncStatus('Syncing…', 'info');
        fetch('http://127.0.0.1:8042/must_done/status?week_id=' + encodeURIComponent(weekId))
            .then(resp => resp.ok ? resp.json() : Promise.reject(new Error('Status ' + resp.status)))
            .then(data => {
                if (!data || data.status !== 'success' || !data.items) return;
                checkboxes.forEach(cb => {
                    if (cb.getAttribute('data-week-id') !== weekId) return;
                    const taskId = cb.getAttribute('data-task-id');
                    const item = data.items[String(taskId)];
                    if (!item) return;
                    cb.checked = !!item.completed;
                });
                const now = new Date();
                const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                setSyncStatus('Last synced: ' + timeStr, 'success');
            })
            .catch(err => {
                console.warn('Must Done sync failed:', err);
                setSyncStatus('Last synced: failed (server unreachable)', 'error');
            });
    }

    // On load, sync for the current week.
    if (checkboxes.length > 0) {
        const weekId = checkboxes[0].getAttribute('data-week-id');
        syncMustDoneFromServer(weekId);
    }

    // On load, sync ad-hoc items.
    loadMustBeDone();

    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function(e) {
            const taskId = this.getAttribute('data-task-id');
            const weekId = this.getAttribute('data-week-id');
            const completed = this.checked;
            
            console.log('Checkbox toggled:', taskId, 'completed:', completed);
            
            // Immediate visual feedback - add a "saving" indicator
            const item = this.closest('.must-done-item');
            const originalOpacity = item ? item.style.opacity : '1';
            if (item) {
                item.style.opacity = '0.6';
                item.style.border = '2px dashed #999';
            }

            // Prevent periodic auto-refresh from reloading stale HTML mid-save.
            if (typeof window.__setRefreshLock === 'function') {
                window.__setRefreshLock('must_done:' + taskId, true);
            }

            setSyncStatus('Saving…', 'info');
            
            // Send update to server immediately
            fetch('http://127.0.0.1:8042/must_done/update', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    task_id: taskId,
                    week_id: weekId,
                    completed: completed
                })
            })
            .then(response => {
                console.log('Server response:', response.status);
                return response.json();
            })
            .then(data => {
                console.log('Update saved:', data);
                if (data.status === 'success') {
                    // Success - restore opacity, keep checkbox state
                    if (item) {
                        item.style.opacity = '1';
                        item.style.border = '';
                    }
                    console.log('✓ Checkbox state saved to database');
                    // No page reload - state is already correct!

                    // Also re-sync from server to guarantee state matches persisted DB.
                    syncMustDoneFromServer(weekId);
                } else {
                    console.error('Server error:', data);
                    // Revert on error
                    this.checked = !completed;
                    if (item) {
                        item.style.opacity = '1';
                        item.style.border = '';
                    }
                    alert('Failed to save. Please try again.');
                    setSyncStatus('Last synced: failed to save', 'error');
                }
            })
            .catch(error => {
                console.error('Network error:', error);
                // Revert on error
                this.checked = !completed;
                if (item) {
                    item.style.opacity = '1';
                    item.style.border = '';
                }
                alert('Connection failed. Please check if the server is running.');
                setSyncStatus('Last synced: failed (server unreachable)', 'error');
            })
            .finally(() => {
                if (typeof window.__setRefreshLock === 'function') {
                    window.__setRefreshLock('must_done:' + taskId, false);
                }
            });
        });
    });
});
</script>
        ''')

        html_parts.append('</div>')
        return '\n'.join(html_parts)

    def _build_productivity_goals_section(self):
        """Build the Agent Coach dashboard section for the HTML report."""
        try:
            agent = ProductivityAgent()
            dashboard_data = agent.get_dashboard_data()
        except Exception as e:
            print(f"Error loading productivity agent data: {e}")
            return ""
        
        metrics = dashboard_data.get('metrics', {})
        is_rest_day = metrics.get('is_rest_day', False)
        rest_reason = metrics.get('rest_reason', '')
        
        html_parts = [
            '<div id="productivity-goals" class="productivity-goals-section" style="margin:20px 0; padding:15px; border:2px solid #3f51b5; border-radius:8px; background:linear-gradient(135deg, #e8eaf6 0%, #c5cae9 100%);">',
            '<h2 style="margin:0 0 12px 0; color:#283593;">📈 Agent Coach</h2>'
        ]
        
        # Rest day indicator
        if is_rest_day:
            html_parts.append(f'''
            <div style="background:#e8f5e9; padding:8px 12px; border-radius:6px; margin-bottom:12px; border-left:4px solid #4caf50;">
                🌴 <strong>Rest Day:</strong> {html.escape(rest_reason)} - Relaxed thresholds active!
            </div>
            ''')
        
        html_parts.append('<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px;">')
        
        # 1. Vibe-to-Job Ratio (skip on rest days)
        if not is_rest_day:
            vibe_min = metrics.get('vibe_minutes', 0)
            job_min = metrics.get('job_minutes', 0)
            job_required = metrics.get('job_required', 0)
            job_ok = job_min >= job_required
            job_color = '#4caf50' if job_ok else '#ff9800'
            job_emoji = '✅' if job_ok else '⚖️'
            html_parts.append(f'''
            <div style="padding:10px; background:white; border-radius:6px; border-left:4px solid {job_color};">
                <div style="font-weight:bold; color:#333;">{job_emoji} Job Balance</div>
                <div style="font-size:1.4em; color:{job_color}; margin:4px 0;">{job_min:.0f}/{job_required:.0f}m</div>
                <div style="font-size:0.85em; color:#666;">1:5 vibe-to-job ratio</div>
            </div>
            ''')
        else:
            html_parts.append('''
            <div style="padding:10px; background:white; border-radius:6px; border-left:4px solid #9e9e9e;">
                <div style="font-weight:bold; color:#333;">😴 Job Balance</div>
                <div style="font-size:1.1em; color:#9e9e9e; margin:4px 0;">Not required</div>
                <div style="font-size:0.85em; color:#666;">Rest day</div>
            </div>
            ''')
        
        # Morning Shield (only show during morning hours or on weekdays)
        morning_shield_enabled = metrics.get('morning_shield_enabled', True)
        morning_productive = metrics.get('morning_productive', 0)
        now = datetime.datetime.now()
        is_morning = 8 <= now.hour < 11
        
        if is_morning and morning_shield_enabled:
            shield_ok = morning_productive >= 10
            shield_color = '#4caf50' if shield_ok else '#ff9800'
            shield_emoji = '✅' if shield_ok else '🛡️'
            html_parts.append(f'''
            <div style="padding:10px; background:white; border-radius:6px; border-left:4px solid {shield_color};">
                <div style="font-weight:bold; color:#333;">{shield_emoji} Morning Shield</div>
                <div style="font-size:1.4em; color:{shield_color}; margin:4px 0;">{morning_productive:.0f}/10m</div>
                <div style="font-size:0.85em; color:#666;">Productive before wasting</div>
            </div>
            ''')
        elif not morning_shield_enabled:
            html_parts.append('''
            <div style="padding:10px; background:white; border-radius:6px; border-left:4px solid #9e9e9e;">
                <div style="font-weight:bold; color:#333;">😴 Morning Shield</div>
                <div style="font-size:1.1em; color:#9e9e9e; margin:4px 0;">Not required</div>
                <div style="font-size:0.85em; color:#666;">Rest day</div>
            </div>
            ''')
        
        html_parts.append('</div>')  # Close grid
        
        # AI Coach advice section
        ai_advice = dashboard_data.get('ai_coach_advice')
        if ai_advice:
            # Use the timestamp from when advice was generated, not current time
            advice_ts = dashboard_data.get('ai_coach_advice_timestamp')
            if advice_ts:
                coach_timestamp = datetime.datetime.fromtimestamp(advice_ts).strftime("%H:%M")
            else:
                coach_timestamp = datetime.datetime.now().strftime("%H:%M")
            html_parts.append(f'''
            <div id="ai-coach-container" style="margin-top:15px; padding:12px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius:8px; color:white;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <div style="font-weight:bold;">🤖 AI Coach Says <span style="font-weight:normal; font-size:0.85em; opacity:0.8;" id="coach-timestamp">({coach_timestamp})</span>:</div>
                    <button onclick="refreshAICoach()" id="refresh-coach-btn" style="background:rgba(255,255,255,0.2); border:1px solid rgba(255,255,255,0.4); color:white; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:0.85em;" title="Get fresh advice from AI">🔄 Refresh</button>
                </div>
                <div id="coach-advice" style="font-size:1.05em; line-height:1.6;">{_format_coach_html(ai_advice)}</div>
            </div>
            <script>
            async function refreshAICoach() {{
                const btn = document.getElementById('refresh-coach-btn');
                const adviceDiv = document.getElementById('coach-advice');
                const tsSpan = document.getElementById('coach-timestamp');
                btn.disabled = true;
                btn.textContent = '⏳ Loading...';
                try {{
                    // Use relative URL that works when html is served from habit_server
                    const resp = await fetch('/ai_coach/refresh', {{method: 'POST'}});
                    if (!resp.ok) {{
                        throw new Error(`HTTP ${{resp.status}}`);
                    }}
                    const data = await resp.json();
                    if (data.status === 'success') {{
                        adviceDiv.innerHTML = data.advice.replace(/\n/g, '<br>').replace(/•/g, '&bull;');
                        const ts = new Date(data.timestamp * 1000);
                        tsSpan.textContent = '(' + ts.toLocaleTimeString([], {{hour: '2-digit', minute:'2-digit'}}) + ')';
                    }} else {{
                        alert('Error: ' + (data.error || 'Unknown error'));
                    }}
                }} catch (e) {{
                    console.error('Refresh error:', e);
                    alert('Failed to refresh advice: ' + e.message);
                }} finally {{
                    btn.disabled = false;
                    btn.textContent = '🔄 Refresh';
                }}
            }}
            </script>
            ''')

        # Recent AI coach briefings/summaries (last few days)
        digest_path = Path("data/coach_briefings.json")
        if digest_path.exists():
            try:
                with open(digest_path, "r", encoding="utf-8") as f:
                    digest_entries = json.load(f)
            except Exception:
                digest_entries = []
        else:
            digest_entries = []

        if digest_entries:
            # Sort newest-first by date then timestamp
            digest_entries = sorted(
                digest_entries,
                key=lambda d: (d.get("date", ""), d.get("timestamp", "")),
                reverse=True
            )

            # Group by date preserving order
            grouped = {}
            ordered_dates = []
            for entry in digest_entries:
                date_key = entry.get("date")
                kind = entry.get("kind")
                if not date_key or not kind:
                    continue
                if date_key not in grouped:
                    grouped[date_key] = {}
                    ordered_dates.append(date_key)
                grouped[date_key][kind] = entry

            html_parts.append('<div style="margin-top:15px; padding:12px; background:white; border-radius:8px; border:1px solid #dfe3f3;">')
            html_parts.append('<div style="font-weight:bold; color:#283593; margin-bottom:6px;">📅 Recent AI Coach Briefings</div>')
            html_parts.append('<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:10px;">')

            max_cards = 4
            for idx, date_key in enumerate(ordered_dates):
                if idx >= max_cards:
                    break
                day_entries = grouped.get(date_key, {})
                morning_entry = day_entries.get("morning_briefing")
                summary_entry = day_entries.get("daily_summary")

                rest_badge = ""
                rest_flag = morning_entry.get("is_rest_day") if morning_entry else summary_entry.get("is_rest_day") if summary_entry else False
                rest_reason = morning_entry.get("rest_reason") if morning_entry else summary_entry.get("rest_reason") if summary_entry else ""
                if rest_flag:
                    rest_badge = f" <span style=\"font-size:0.85em; color:#4caf50;\">(Rest: {html.escape(rest_reason or 'Weekend')})</span>"

                morning_text = morning_entry.get("text") if morning_entry else "(No morning briefing recorded)"
                summary_text = summary_entry.get("text") if summary_entry else "(No end-of-day summary recorded)"

                html_parts.append(f'''
                <div style="padding:10px; background:#f8f9ff; border-radius:6px; border:1px solid #e0e3f7;">
                    <div style="font-weight:bold; color:#1f2a44; margin-bottom:6px;">{date_key}{rest_badge}</div>
                    <div style="font-size:0.92em; color:#111;">
                        <div style="font-weight:600; color:#555; margin-bottom:3px;">☀️ Today's Focus</div>
                        <div style="margin-bottom:8px; line-height:1.45;">{_format_coach_html(morning_text)}</div>
                        <div style="font-weight:600; color:#555; margin-bottom:3px;">🌙 Daily Summary</div>
                        <div style="line-height:1.45;">{_format_coach_html(summary_text)}</div>
                    </div>
                </div>
                ''')

            html_parts.append('</div>')  # grid
            html_parts.append('</div>')  # container
        
        # Add last updated timestamp
        html_parts.append(f'<div style="text-align:right; font-size:0.8em; color:#666; margin-top:10px;">Updated: {datetime.datetime.now().strftime("%H:%M:%S")}</div>')
        html_parts.append('</div>')  # Close main container
        
        return '\n'.join(html_parts)

    def _build_warning_flag_summary(self):
        # Hidden by request: this section isn't currently useful in the dashboard.
        # Keeping the function so it can be re-enabled later without deleting code.
        return ''
        try:
            counts = database.get_warning_flag_counts()
        except Exception:
            counts = {'win': 0, 'lose': 0}

        wins = counts.get('win') or 0
        losses = counts.get('lose') or 0
        total = wins + losses

        summary_parts = [
            '<div class="warning-flag-summary" style="margin:20px 0; padding:12px; border:1px solid #ccc; border-radius:6px; background:#fdf9e6;">',
            '<h2 style="margin-top:0;">Warning Response Flags</h2>',
            f'<p style="font-size:1.05em; margin-bottom:8px;"><strong>Winning flags:</strong> {wins} &nbsp;|&nbsp; <strong>Losing flags:</strong> {losses}</p>'
        ]

        if total == 0:
            summary_parts.append('<p style="margin:0; color:#555;">No warning responses recorded yet. Click warning dialogs within one minute to earn a win.</p>')
        else:
            win_pct = (wins / total) * 100 if total else 0
            loss_pct = (losses / total) * 100 if total else 0
            summary_parts.append(
                f'<p style="margin:0; color:#555;">Respond within one minute to earn a win. Current win rate: {win_pct:.0f}% &nbsp;|&nbsp; Loss rate: {loss_pct:.0f}%.</p>'
            )

        summary_parts.append('</div>')
        return ''.join(summary_parts)

    def check_for_future_data(self):
        """
        Checks local database, remote database (if accessible), and cache for any future-dated records.
        Prints warnings for any future data found.
        """
        tz = pytz.timezone(TIMEZONE)
        today = datetime.datetime.now(tz).date()
        
        print("Checking for future data in databases and cache...")
        
        # Check local database using database module
        try:
            days = database.fetch_available_days()
            future_dates = [day for day in days if datetime.datetime.strptime(day, '%Y-%m-%d').date() > today]
            if future_dates:
                print(f"Warning: Found future dates in local database: {future_dates}")
            else:
                print("Local database: No future dates found.")
        except Exception as e:
            print(f"Error checking local database: {e}")
        
        # Check remote database (if API key is set) using database module
        if database.API_KEY:
            try:
                # Use the sync function to fetch remote data
                database.sync_remote_to_local()  # This will fetch and insert new data
                # Then check again
                days_after = database.fetch_available_days()
                future_dates_after = [day for day in days_after if datetime.datetime.strptime(day, '%Y-%m-%d').date() > today]
                if future_dates_after:
                    print(f"Warning: Found future dates in remote database: {future_dates_after}")
                else:
                    print("Remote database: No future dates found.")
            except Exception as e:
                print(f"Error checking remote database: {e}")
        else:
            print("Remote database: API key not configured, skipping.")
        
        # Check cache
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                future_cache = []
                for key, value in cache.items():
                    if key.endswith('.csv'):
                        date_str = key.replace('.csv', '')
                        try:
                            cache_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                            if cache_date > today:
                                future_cache.append(date_str)
                        except ValueError:
                            pass
                if future_cache:
                    print(f"Warning: Found future dates in cache: {future_cache}")
                else:
                    print("Cache: No future dates found.")
            except Exception as e:
                print(f"Error checking cache: {e}")
        else:
            print("Cache: File not found.")
        
        print("Future data check complete.")


if __name__ == '__main__':
    main()