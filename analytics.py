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
import json
import textwrap
import pytz
import plotly.express as px
import database
from config import TIMEZONE, DAY_BOUNDARY_HOUR, HABITS
import sqlite3
import requests
import html
from urllib.parse import urlparse
import stock_prices

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

    priority = {
        'programming': 1, 'documents': 1, 'mail': 2,
        'not categorized': 3, 'wasted time': 4, 'idle': 5
    }
    df['priority'] = df['category'].map(priority).fillna(99)

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



class Analytics():

    def __init__(self):
        self.path_data = 'data'
        self.config = self._load_config()
        self.string_cats = self.config.items('CATEGORIES')
        self.color_list = self.config.items('COLORS')
        self.proj_list = self.config.items('PROJECTS')
        self.cache_path = 'data/analysis_cache.json'
        self.analysis_cache = self._load_analysis_cache()
        self.last_activity_count = 0  # Track activity count to detect changes
        self.last_update_timestamp = 0  # Track when we last updated
        database.initialize_database()

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
        df['end_time'] = pd.to_datetime(df['timestamp'], unit='s').dt.tz_localize('UTC').dt.tz_convert(tz)
        df['start_time'] = df.apply(lambda row: row['end_time'] - datetime.timedelta(seconds=row['duration']), axis=1)
        return df

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
        # 2. We updated recently (within last 60 seconds)
        if (current_activity_count == self.last_activity_count and 
            time_since_last_update < 60):
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
            
        all_u_cats = self.get_unique_categories()
        
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
            non_productive_cats = {"wasted", "wasted time", "gaming"}
            is_currently_wasting = current_category and current_category in non_productive_cats
            
            # Fast refresh (15s) when wasting for immediate feedback, medium refresh (30s) when productive
            refresh_interval = 15 if is_currently_wasting else 30
            file.write(f'<meta http-equiv="refresh" content="{refresh_interval}">\n')

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
            header_row += '<td><b>Total Time</b></td></tr>\n'
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
                
                # Categories to show ratio for
                ratio_cats = {'family', 'gaming', 'coding', 'wasted', 'learning', 'church', 'mail'}
                
                total_time = 0
                for cat in all_u_cats:
                    dur = dur_map.get(cat, 0)
                    if cat.lower() != 'idle':
                        total_time += dur
                
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
            
            # Define productive and non-productive categories
            productive_cats = {"coding", "programming", "learning", "church", "documents", "docs", "think"}
            non_productive_cats = {"wasted", "wasted time", "gaming"}
            
            # Check if current activity is non-productive
            is_currently_wasting = current_category and current_category in non_productive_cats
            
            # Always calculate waste ratio for display
            waste_percentage, waste_display, total_active_hours, wasted_hours, _ = self._calculate_waste_ratio(log_list, date_list)
            
            # Always show combined dashboard with streaks and waste ratio
            # Calculate longest streaks
            today_date_str = date_list[0].strftime('%Y-%m-%d') if date_list else None
            longest_today_min, longest_today_display, longest_today_time = (0, "0 min", "") if not today_date_str else self._calculate_longest_streak_for_day(today_date_str)
            longest_7days_min, longest_7days_display, longest_7days_date = self._calculate_longest_streak_recent_days(date_list, num_days=7)
            
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
            file.write(f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#1b5e20;">{streak_display}</p>')
            file.write(f'<p style="margin:5px 0; color:#33691e; font-size:0.95em;">{message}</p>')
            
            # Add note-taking section
            file.write('<div style="margin-top: 15px; padding-top: 10px; border-top: 1px solid rgba(0,0,0,0.1);">')
            file.write('<textarea id="streak-note" placeholder="What are you working on?" style="width: 90%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; font-family: inherit; resize: vertical; min-height: 60px;"></textarea>')
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
            if (saveBtn) {
                saveBtn.style.background = '#1976D2'; // Blue
                saveBtn.style.color = 'white';
            }

            // Append the new note to Recent Notes without refreshing
            const recentContainer = document.getElementById('recent-notes');
            if (recentContainer) {
                // Ensure container is visible
                recentContainer.style.display = '';

                // Build note element with current local time
                const now = new Date();
                const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                const div = document.createElement('div');
                div.style.margin = '4px 0';
                div.style.color = '#555';
                div.innerHTML = `<span style="color: #888;">${timeStr}</span> - ${savedText.replace(/</g,'&lt;').replace(/>/g,'&gt;')}`;

                // Prepend for most-recent-first
                if (recentContainer.firstChild) {
                    recentContainer.insertBefore(div, recentContainer.firstChild);
                } else {
                    recentContainer.appendChild(div);
                }
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
// Make Save button yellow when typing, and guard against losing unsaved text
(() => {
    const noteArea = document.getElementById('streak-note');
    const saveBtn = document.querySelector('button[onclick="saveNote()"]');
    const statusSpan = document.getElementById('note-status');
    if (!noteArea || !saveBtn) return;

    const setButtonYellow = () => {
        window.__streakNoteUnsaved = noteArea.value.trim().length > 0;
        if (window.__streakNoteUnsaved) {
            saveBtn.style.background = '#FBC02D'; // Yellow
            saveBtn.style.color = '#000';
            if (statusSpan && !statusSpan.textContent) {
                statusSpan.textContent = 'Draft not saved';
                statusSpan.style.color = '#8D6E63';
            }
        }
    };

    noteArea.addEventListener('input', setButtonYellow);
    noteArea.addEventListener('change', setButtonYellow);

    window.addEventListener('beforeunload', function(e) {
        const hasUnsaved = window.__streakNoteUnsaved && noteArea.value.trim().length > 0;
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
            file.write('<h3 style="margin:0 0 10px 0; color:#2e7d32;">🏆 Longest Today</h3>')
            file.write(f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#1b5e20;">{longest_today_display}</p>')
            longest_today_info = f"Started at {longest_today_time}" if longest_today_time else "Best focus session"
            file.write(f'<p style="margin:5px 0; color:#33691e; font-size:0.95em;">{longest_today_info}</p>')
            
            # Display recent notes under Longest Today
            recent_notes = database.get_recent_streak_notes(5)
            if recent_notes:
                file.write('<div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(0,0,0,0.1); text-align:left;">')
                file.write('<h4 style="margin: 0 0 8px 0; font-size: 0.9em; color: #555;">Recent Notes:</h4>')
                file.write('<div id="recent-notes" style="font-size: 0.85em;">')
                import pytz
                tz = pytz.timezone(TIMEZONE)
                for note_text, timestamp in recent_notes:
                    dt = datetime.datetime.fromtimestamp(timestamp, tz)
                    time_str = dt.strftime('%I:%M %p')
                    file.write(f'<div style="margin: 4px 0; color: #555;"><span style="color: #888;">{time_str}</span> - {html.escape(note_text)}</div>')
                file.write('</div></div>')
            else:
                file.write('<div id="recent-notes" style="display:none;"></div>')
            file.write('</div>')
            
            # Longest 7 Days
            file.write('<div style="flex: 1; min-width: 200px; padding: 10px; text-align: center; border-left: 1px solid rgba(0,0,0,0.1);">')
            file.write('<h3 style="margin:0 0 10px 0; color:#2e7d32;">⭐ Longest in 7 Days</h3>')
            file.write(f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#1b5e20;">{longest_7days_display}</p>')
            longest_7days_info = longest_7days_date if longest_7days_date else "Weekly record"
            file.write(f'<p style="margin:5px 0; color:#33691e; font-size:0.95em;">{longest_7days_info}</p>')
            file.write('</div>')
            
            # Waste Ratio
            file.write('<div style="flex: 1; min-width: 200px; padding: 10px; text-align: center; border-left: 1px solid rgba(0,0,0,0.1);">')
            file.write('<h3 style="margin:0 0 10px 0; color:#c62828;">📊 Waste Ratio</h3>')
            file.write(f'<p style="font-size:2em; font-weight:bold; margin:5px 0; color:#d32f2f;">{waste_display}</p>')
            if total_active_hours > 0:
                file.write(f'<p style="margin:5px 0; color:#c62828; font-size:0.95em;">Wasted: {wasted_hours:.1f}h / {total_active_hours:.1f}h</p>')
            else:
                file.write(f'<p style="margin:5px 0; color:#666; font-size:0.95em;">No active time yet</p>')
            file.write('</div>')
            
            file.write('</div>')
            file.write('</div>')

            recent_activity_minutes = self.config.getint('SETTINGS', 'recent_activity_minutes', fallback=10)
            recent_activity_html = self._build_recent_activity_section(log_list, date_list, minutes=recent_activity_minutes)
            if recent_activity_html:
                file.write('<hr/>')
                file.write(recent_activity_html)

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
        
        self._save_analysis_cache()
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] html updated')

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

        import pytz
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

        # Define productive and non-productive categories
        productive_cats = {"coding", "programming", "learning", "church", "documents", "docs", "think", "not categorized"}
        non_productive_cats = {"wasted", "wasted time", "gaming"}
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
        if current_category not in productive_cats:
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
            if category in non_productive_cats:
                break
            
            # If productive, accumulate the duration
            if category in productive_cats:
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
        
        productive_cats = {"coding", "programming", "learning", "church", "documents", "docs", "think", "not categorized"}
        non_productive_cats = {"wasted", "wasted time", "gaming"}
        
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
            if category in productive_cats:
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
            elif category in non_productive_cats:
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

        import pytz
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

    def _build_recent_activity_section(self, log_list, date_list, minutes=12):
        if not log_list or not date_list:
            return ''

        # Find the most recent activities within the last N minutes
        import pytz
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

        productive_cats = ["coding", "programming", "learning", "church", "documents", "mail"]
        distracted_cats = ["wasted", "wasted time", "gaming", "no_cat", "not categorized"]

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
        """Get week identifier (year-week format) for a given datetime."""
        if dt is None:
            dt = datetime.datetime.now(pytz.timezone(TIMEZONE))
        return dt.strftime('%Y-W%U')  # e.g., "2025-W45"
    
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
        if week_start is None:
            tz = pytz.timezone(TIMEZONE)
            now = datetime.datetime.now(tz)
            # Find the start of the current week (Sunday)
            week_start = now - datetime.timedelta(days=now.weekday() + 1)
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
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
        
        # Calculate week start and end for display
        week_start = now - datetime.timedelta(days=now.weekday() + 1)
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + datetime.timedelta(days=6, hours=23, minutes=59, seconds=59)
        next_week_start = week_start + datetime.timedelta(days=7)
        
        html_parts = [
            '<div id="must-done-section" class="must-done-section" style="margin:20px 0; padding:15px; border:2px solid #333; border-radius:8px; background:#fff;">',
            f'<h2 style="margin-top:0; color:#333;">📋 Must Done This Week</h2>',
            f'<div style="color:#666; font-size:0.9em; margin-bottom:10px;">Week {week_id} ({week_start.strftime("%b %d")} - {week_end.strftime("%b %d")}). Tasks reset on {next_week_start.strftime("%a, %b %d at 12:00 AM")}.</div>',
            '<div style="display:flex; flex-direction:column; gap:10px;">'
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
        
        html_parts.append('</div>')
        
        # Add JavaScript for checkbox handling
        html_parts.append('''
<script>
document.addEventListener('DOMContentLoaded', function() {
    const checkboxes = document.querySelectorAll('.must-done-checkbox');
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
                } else {
                    console.error('Server error:', data);
                    // Revert on error
                    this.checked = !completed;
                    if (item) {
                        item.style.opacity = '1';
                        item.style.border = '';
                    }
                    alert('Failed to save. Please try again.');
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
            });
        });
    });
});
</script>
        ''')
        
        html_parts.append('</div>')
        return '\n'.join(html_parts)

    def _build_warning_flag_summary(self):
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