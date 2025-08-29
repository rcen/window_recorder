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
import pytz
import plotly.express as px
import database
from config import TIMEZONE

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

def resolve_conflicts(df):
    """
    Resolves overlapping activities from different sources based on category priority.

    Args:
        df (pd.DataFrame): DataFrame containing a day's activities with 'timestamp', 
                           'duration', 'category', and 'source' columns.

    Returns:
        pd.DataFrame: A new DataFrame with conflicts resolved.
    """
    if df.empty or 'source' not in df.columns or df['source'].nunique() <= 1:
        return df

    # Define category priorities (lower number is higher priority)
    priority = {
        'programming': 1,
        'documents': 1,
        'mail': 2,
        'not categorized': 3,
        'wasted time': 4,
        'idle': 5
    }
    df['priority'] = df['category'].map(priority).fillna(99)

    df = df.sort_values(by=['start_time', 'priority']).reset_index(drop=True)

    # When converting to dict, datetime objects are preserved.
    resolved = df.to_dict('records')

    if not resolved:
        return pd.DataFrame()

    final_timeline = []
    # Sort by start time, then by priority
    resolved_sorted = sorted(resolved, key=lambda x: (x['start_time'], x['priority']))
    
    current_event = resolved_sorted[0]

    for i in range(1, len(resolved_sorted)):
        next_event = resolved_sorted[i]

        # Check for overlap
        if next_event['start_time'] < current_event['end_time']:
            # Overlap detected, decide which event wins based on priority
            if next_event['priority'] < current_event['priority']:
                # Next event is higher priority. Truncate the current one.
                if next_event['start_time'] > current_event['start_time']:
                    current_event['end_time'] = next_event['start_time']
                    final_timeline.append(current_event)
                current_event = next_event
            else:
                # Current event is higher or equal priority. Ignore the overlapping part of the next event.
                pass # The next event is effectively skipped or will be handled in the next iteration
        else:
            # No overlap, add the current event to the timeline
            final_timeline.append(current_event)
            current_event = next_event
    
    final_timeline.append(current_event) # Add the last event

    if not final_timeline:
        return pd.DataFrame()

    # Convert back to a DataFrame and recalculate duration
    result_df = pd.DataFrame(final_timeline)
    result_df['duration'] = (result_df['end_time'] - result_df['start_time']).dt.total_seconds()
    result_df = result_df[result_df['duration'] > 1] # Remove tiny fragments

    # Clean up columns, but keep the essential time columns
    result_df = result_df.drop(columns=['priority'])
    
    return result_df

def reanalyze_all():
    if not os.path.isdir('data'):
        os.mkdir('data')
    
    analytic = Analytics()
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
        database.initialize_database()

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
        config.read(path_config)
        
        # Add settings section if it doesn't exist
        if not config.has_section('SETTINGS'):
            config.add_section('SETTINGS')
            config.set('SETTINGS', 'image_folder', 'figs/pictures')
            config.set('SETTINGS', 'md_folder', 'C:/Users/YourUser/Documents/Notes')
            with open(path_config, 'w') as configfile:
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
                with open(self.cache_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_analysis_cache(self):
        try:
            with open(self.cache_path, 'w') as f:
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
            return # Invalid date format in logfile name

        # If the chart is for a past day and it already exists, skip redrawing.
        if chart_date < today_date and os.path.exists(path):
            return
        # --- End of Optimization ---

        df = self._get_and_prepare_day_df(date_str)
        if df.empty:
            return

        # Resolve conflicts on the timezone-aware data
        df = resolve_conflicts(df)

        # Get colors
        color_map = dict(self.color_list)
        
        fig = px.timeline(
            df,
            x_start="start_time",
            x_end="end_time",
            y="category",
            color="category",
            hover_name="window_title",
            color_discrete_map=color_map,
            title=f'Activity Timeline for {date_str}'
        )

        fig.update_yaxes(categoryorder='total ascending')
        fig.update_layout(
            xaxis_title="Time of Day",
            yaxis_title="Category",
            showlegend=False
        )

        fig.write_html(path, full_html=False, include_plotlyjs='cdn')
        print(f'Interactive timeline chart saved as {path}')


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

        total_dur = np.sum(u_dur)
        today = date
        filename = '{0:d}-{1:02d}-{2:02d}.png'.format(today.year, today.month, today.day)

        pie_labels = []
        pie_dur = []
        pie_colors = []
        
        all_u_cats = self.get_unique_categories()
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')

        dur_map = dict(zip(u_cats, u_dur))

        for cat in all_u_cats:
            dur = dur_map.get(cat, 0)
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

        print('Pie chart saved as {}'.format(path))


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


    def get_cat(self, window):
        ret = 'not categorized'
        if len(window) <=1:
            return 'idle'
        for string, category in self.string_cats:
            try:
                match = re.search(string, window)
                if bool(match):
                    return category
            except TypeError:
                pass
            ret = category
        return ret

    def create_html(self, logfile=''):
        if "mod.log" in logfile:
            return

        week_days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        
        log_list, date_list = self.get_log_list()
        
        # Read display_limit from config, with a fallback
        try:
            display_limit = self.config.getint('SETTINGS', 'display_limit', fallback=20)
        except (configparser.NoSectionError, configparser.NoOptionError):
            display_limit = 20
        
        # Limit the number of logs to be displayed
        if len(log_list) > display_limit:
            log_list = log_list[:display_limit]
            
        all_u_cats = self.get_unique_categories()
        
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')

        with open('html/head.txt', 'r', encoding='utf-8') as file:
            head = file.readlines()
        with open('html/tail.txt', 'r', encoding='utf-8') as file:
            tail = file.read()

        with open('html/index.html', 'w', encoding='utf-8') as file:
            file.writelines(head)

            table_html = '<table style="width:100%">'
            
            header_row = '<tr><td></td>'
            for cat in all_u_cats:
                color = color_map.get(cat, default_color)
                header_row += f'<td style="background-color:{color}"><b>{cat}</b></td>\n'
            header_row += '<td><b>Total Time</b></td></tr>\n'
            table_html += header_row

            for log in reversed(log_list):
                self.print_pi_chart(log)
                self.create_interactive_timeline(log)
                
                u_cats_log, u_dur_log, date, df = self.analyze(log)
                if not date: continue
                
                dur_map = dict(zip(u_cats_log, u_dur_log))
                
                row = '<tr>'
                row += '<td><b>{0:02}.{1:02}.{2:04},{3}</b></td>'.format(date.month, date.day, date.year, week_days[date.weekday()])
                
                total_time = 0
                for cat in all_u_cats:
                    dur = dur_map.get(cat, 0)
                    total_time += dur
                    dur_hr, dur_min, dur_sec = Sec2hms(dur)
                    color = color_map.get(cat, default_color)
                    row += f'<td style="background-color:{color}">'
                    row += '{0:02}:{1:02}:{2:02}'.format(dur_hr, dur_min, dur_sec)
                    row += '</td>'
                
                tot_hr, tot_min, tot_sec = Sec2hms(total_time)
                row += '<td>{0:02}:{1:02}:{2:02}</td>'.format(tot_hr, tot_min, tot_sec)
                row += '</tr>'

                table_html += row

            table_html += header_row
            table_html += '</table>\n'
            file.write(table_html)

            file.write('<div class="gallery" style="width: 100%;">')
            img_list = sorted(os.listdir('figs/pie'))
            timeline_html_list = sorted(os.listdir('html/timelines'))

            # Create a dictionary for timeline images for quick lookup
            timeline_map = {html.split('.')[0]: html for html in timeline_html_list}

            for img in reversed(img_list):
                date_str = img.split('.')[0]
                timeline_html = timeline_map.get(date_str)

                img_row = '<div style="display: flex; justify-content: center; align-items: center; margin-bottom: 20px; width: 100%;">'
                img_row += f'<img src="../figs/pie/{img}" style="width: 48%; max-width: 500px;" >'
                if timeline_html:
                    img_row += f'<iframe src="timelines/{timeline_html}" style="width: 48%; height: 500px; border: none;"></iframe>'
                img_row += '</div></br>'
                file.write(img_row)
            file.write('</div>')

            file.writelines(tail)
        
        self._save_analysis_cache()
        print('html updated')


if __name__ == '__main__':
    main()