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
import datetime
import database

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

def reanalyze_all():
    database.clear_cache()
    if not os.path.isdir('data'):
        os.mkdir('data')
    
    analytic = Analytics()
    log_list, _ = analytic.get_log_list()

    for logfile in log_list:
        print('Processing analysis for:', logfile)
        # The following functions now read from the database
        analytic.print_review(logfile)
        analytic.print_timeline(logfile)
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
        self.analysis_cache = {}
        database.initialize_database()

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
adobe acrobat reader: documents
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
        if not os.path.isdir('figs/timeline'):
            os.mkdir('figs/timeline')
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


    def print_timeline(self, logfile=''):
        if "mod.log" in logfile:
            return

        from config import TIMEZONE
        import pytz
        
        date_str = logfile.replace('.csv', '')
        path = f'figs/timeline/{date_str}.png'

        # --- Intelligent Chart Generation ---
        tz = pytz.timezone(TIMEZONE)
        today_date = datetime.datetime.now(tz).date()
        try:
            chart_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return # Invalid date format in logfile name

        # If the chart is for a past day and it already exists, skip redrawing.
        if chart_date < today_date and os.path.exists(path):
            return
        # --- End of Optimization ---

        df = database.fetch_log_for_day(date_str)
        if df.empty:
            return

        # Convert timestamps to datetime objects, adjusted for timezone
        df['end_time'] = pd.to_datetime(df['timestamp'], unit='s').dt.tz_localize('UTC').dt.tz_convert(tz)
        df['start_time'] = df.apply(lambda row: row['end_time'] - datetime.timedelta(seconds=row['duration']), axis=1)

        # Get unique categories and assign them a y-level
        u_cats = self.get_unique_categories()
        cat_y_map = {cat: i for i, cat in enumerate(u_cats)}
        
        # Get colors
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')

        fig, ax = plt.subplots(figsize=(12, 8))

        for index, row in df.iterrows():
            y = cat_y_map.get(row['category'])
            if y is None:
                continue
            start = row['start_time']
            end = row['end_time']
            color = color_map.get(row['category'], default_color)
            
            ax.barh(y, (end - start), left=start, height=0.6, color=color, edgecolor='black')

        # Formatting the plot
        ax.set_yticks(range(len(u_cats)))
        ax.set_yticklabels(u_cats)
        ax.invert_yaxis()

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        plt.xticks(rotation=45)

        plt.title(f'Activity Timeline for {date_str}')
        plt.xlabel('Time of Day')
        plt.ylabel('Category')
        plt.tight_layout()
        plt.grid(axis='x', linestyle='--', alpha=0.6)

        plt.savefig(path)
        plt.close()
        print(f'Timeline chart saved as {path}')


    def analyze(self, logfile=''):
        """
        Fetches a pre-computed summary for a given day.
        The heavy lifting is done by the API server.
        """
        if "mod.log" in logfile:
            return None, None, None, None
        if logfile in self.analysis_cache:
            return self.analysis_cache[logfile]

        if logfile == '':
            from config import TIMEZONE
            import pytz
            tz = pytz.timezone(TIMEZONE)
            today = datetime.datetime.now(tz)
            date_str = today.strftime('%Y-%m-%d')
        else:
            date_str = logfile.replace('.csv', '')

        # Fetch the pre-aggregated summary instead of the full dataset
        u_cats, u_dur = database.fetch_summary_for_day(date_str)

        if not u_cats:
            return [], [], None, None

        date = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        
        # The dataframe `df` is no longer available as we don't fetch the full log.
        # We pass None for it. Other functions will need to handle this.
        self.analysis_cache[logfile] = (u_cats, u_dur, date, None)
        return u_cats, u_dur, date, None



    def print_pi_chart(self, logfile=''):
        # --- Intelligent Chart Generation ---
        from config import TIMEZONE
        import pytz
        tz = pytz.timezone(TIMEZONE)
        today_date = datetime.datetime.now(tz).date()

        if logfile:
            date_str = logfile.replace('.csv', '')
            chart_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date_str = today_date.strftime('%Y-%m-%d')
            chart_date = today_date
        
        path = f'figs/pie/{date_str}.png'

        # If the chart is for a past day and it already exists, skip redrawing.
        if chart_date < today_date and os.path.exists(path):
            return
        # --- End of Optimization ---

        # check the filename does not contain "mod.log" to avoid crash
        if "mod.log" in logfile:
            return

        u_cats, u_dur, date, _ = self.analyze(logfile) # df is no longer available
        
        # Exit if there's no data to plot
        if not date or not any(d > 0 for d in u_dur):
            return

        total_dur = np.sum(u_dur)
        today = date
        filename = '{0:d}-{1:02d}-{2:02d}.png'.format(today.year, today.month, today.day)

        # Filter out categories with zero duration to ensure colors, labels, and data align
        pie_labels = []
        pie_dur = []
        pie_colors = []
        
        # Get all unique categories defined in the config to create a stable color mapping
        all_u_cats = self.get_unique_categories()
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC')

        # Create a duration map from the fetched summary data
        dur_map = dict(zip(u_cats, u_dur))

        for cat in all_u_cats:
            dur = dur_map.get(cat, 0)
            if dur > 0:
                pie_dur.append(dur)
                hr, mn, sec = Sec2hms(dur)
                pie_labels.append(f"{cat}-{hr:02}:{mn:02}:{sec:02}")
                pie_colors.append(color_map.get(cat, default_color))

        # Proceed with plotting
        weekday_name = today.strftime('%a')
        total_hr, total_min, total_sec = Sec2hms(total_dur)
        
        plt.figure(num=None, figsize=(8, 6), dpi=80, facecolor='w', edgecolor='k')
        plt.title(f'{weekday_name}, {today.month:02}.{today.day:02}.{today.year:04} - {total_hr:02}:{total_min:02}:{total_sec:02} h')

        plt.pie(pie_dur, labels=pie_labels, autopct='%1.1f%%', colors=pie_colors)
        plt.axis('equal')
        plt.tight_layout()
        # The path is already determined at the top of the function
        plt.savefig(path)
        plt.close()

        print('Pie chart saved as {}'.format(path))


    def get_colors(self, logfile):
        colors = []
        u_cats, _, _, _ = self.analyze(logfile)
        if not u_cats:
            return []
        
        color_map = dict(self.color_list)
        # Use idle color as a fallback, otherwise a generic gray
        default_color = color_map.get('idle', '#CCCCCC')
        
        for u_cat in u_cats:
            colors.append(color_map.get(u_cat, default_color))
            
        return colors

    def print_review(self, logfile=''):

        # check the filename does not contain "mod.log" to avoid crash
        if "mod.log" in logfile:
            return

        u_cats, u_dur, date, _ = self.analyze(logfile) # df is no longer available
        if not u_cats or date is None:
            return
        print('')
        print('')
        total_dur = np.sum(u_dur) # Calculate total from summary
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

        # "not categorized" is now implicitly handled since the summary only returns categorized data.
        # The total duration is the sum of all categorized durations.
        print('-------------------------------------')
        print('{0: 6}:{1:02}:{2:02} h not categorized'.format(0, 0, 0))


    def get_log_list(self):
        """
        Gets the list of days that have data from the new, efficient API endpoint.
        Returns a list of date strings ('YYYY-MM-DD.csv') and a list of datetime objects.
        """
        days = database.fetch_available_days()
        log_list = [f"{day}.csv" for day in days]
        date_list = [datetime.datetime.strptime(day, '%Y-%m-%d') for day in days]
        
        # The API already returns them sorted, but we can ensure it here too.
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
            return 'idle' #this is a "pre-defined" cat in script.py
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
        # check the filename does not contain "mod.log" to avoid crash
        if "mod.log" in logfile:
            return

        week_days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        
        log_list, date_list = self.get_log_list()
        all_u_cats = self.get_unique_categories()
        
        # Create a stable color map for all categories
        color_map = dict(self.color_list)
        default_color = color_map.get('idle', '#CCCCCC') # Use idle color or gray as fallback

        with open('html/head.txt', 'r', encoding='utf-8') as file:
            head = file.readlines()
        with open('html/tail.txt', 'r', encoding='utf-8') as file:
            tail = file.read()

        with open('html/index.html', 'w', encoding='utf-8') as file:
            file.writelines(head)

            # --- TABLE ---
            table_html = '<table style="width:100%">'
            
            # --- TABLE HEADER ---
            header_row = '<tr><td></td>'
            for cat in all_u_cats:
                color = color_map.get(cat, default_color)
                header_row += f'<td style="background-color:{color}"><b>{cat}</b></td>\n'
            header_row += '<td><b>Total Time</b></td></tr>\n'
            table_html += header_row

            # --- TABLE DATA ROWS ---
            for log in reversed(log_list):
                # Generate a pie chart for each day (it will be skipped if it's old)
                self.print_pi_chart(log)
                
                u_cats_log, u_dur_log, date, df = self.analyze(log)
                if not date: continue
                
                dur_map = dict(zip(u_cats_log, u_dur_log))
                date = datetime.datetime.strptime(log[0:10], '%Y-%m-%d')
                
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

            # --- TABLE FOOTER ---
            table_html += header_row
            table_html += '</table>\n'
            file.write(table_html)

            # --- IMAGES ---
            file.write('<div class="gallery">')
            img_list = sorted(os.listdir('figs/pie'))
            for img in reversed(img_list):
                img_row = '<div style="display: flex; justify-content: space-around;">'
                img_row += '<img src="../figs/pie/{}"  width="450" height="450" >'.format(img)
                img_row += '</div></br>'
                file.write(img_row)
            file.write('</div>')
            file.writelines(tail)
        print('html updated')


if __name__ == '__main__':
    main()
