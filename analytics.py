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
def main():
    reanalyze_all()

def sec2str(dur):
    dur_hr = int(np.floor(dur/3600))
    dur_min = int(np.floor((dur-dur_hr*3600)/60))
    dur_sec = int(dur%60)
    return [dur_hr,dur_min,dur_sec]



def reanalyze_all():
    logfiles = os.listdir('data')
    for logfile in logfiles:
        print('logfile', logfile)
        #logfile = '' #'2018-9-5.csv'        
        analytic = Analytics()
        analytic.redo_cat(logfile)
        analytic.print_review(logfile)
        analytic.print_timeline(logfile)
        analytic.print_pi_chart(logfile)
        analytic.create_html(logfile)


class Analytics():

    def __init__(self):
        self.path_data = 'data'
        config = configparser.ConfigParser()
        path_config = 'config.dat'
        if not os.path.isfile(path_config):
            with open(path_config, 'w') as file:
                config_template="""[CATEGORIES]
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
mozilla: wasted time
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
        config.read('config.dat')
        self.string_cats = config.items('CATEGORIES')
        self.color_list = config.items('COLORS')
        self.proj_list = config.items('PROJECTS')


    def print_timeline(self, logfile=''):
        if logfile == '':
            today = datetime.datetime.now()
            filename = '{0:d}-{1:02d}-{2:02d}.csv'.format(today.year, today.month, today.day)
            path = self.path_data + '/' + filename

        else:
            filename = logfile
            today = datetime.datetime.strptime(logfile[:-4], '%Y-%m-%d')
        path = self.path_data + '/' + filename
        if not os.path.isfile(path):
                raise FileNotFoundError ('Logfile not found. Start script.py first do generate data')

        df = pd.read_csv(path, encoding = "ISO-8859-1", names=['time', 'category', 'duration', 'title'])
        u_cats = self.get_unique_categories(self.string_cats) # unique category name

        colors = self.get_colors(logfile)
        plt.title('')
        start_time = ''
        for idx, u_cat in enumerate(u_cats):
            temp = df.loc[df.category == u_cat]
            time = temp.time.values
            duration = temp.duration.values

            for entry in range(len(time)):
                start_time = datetime.datetime.fromtimestamp(float(time[0])).date()
                start = datetime.datetime.fromtimestamp(float(time[entry]) - float(duration[entry]))
                end = datetime.datetime.fromtimestamp(float(time[entry]))
                #print(u_cat, start, end, '\t', duration[entry])
                plt.plot([start , end], [idx, idx] , '-.', linewidth=7, color=colors[idx])
        
        if(start_time != ''):
            plt.yticks(range(len(u_cat)+1), u_cats.append('test'))
            plt.grid()
            plt.title(start_time)
            start_time = datetime.datetime.combine(start_time, datetime.time(7,00))
            time_delta = datetime.time(20)
            end_time = datetime.datetime.combine(start_time, time_delta)

            plt.xlim([start_time, end_time])
            plt.gcf().autofmt_xdate()
            myFmt = mdates.DateFormatter('%H:%M')
            plt.gca().xaxis.set_major_formatter(myFmt)
            plt.tight_layout()

            filename = '{0:d}-{1:02d}-{2:02d}.png'.format(today.year, today.month, today.day)
            #fig_path = str(today.year) + '-' + str(today.month) + '-' + str(today.day) + '.png'

            path = 'figs/timeline/' + filename
            plt.savefig(path)

            plt.close()
            print('Timeline saved as {}'.format(path))






    def analyze(self, logfile=''):
        if logfile == '':
            today = datetime.datetime.now()
            filename = '{0:d}-{1:02d}-{2:02d}.csv'.format(today.year, today.month, today.day)
            path = self.path_data + '/' + filename

        else:
            filename = logfile
        path = self.path_data + '/' + filename
        if not os.path.isfile(path):
                raise FileNotFoundError ('Logfile not found. Start script.py first do generate data')
        date = datetime.datetime.strptime(filename[:-4], '%Y-%m-%d')

        df = pd.read_csv(path, encoding = "ISO-8859-1", names=['time', 'category', 'duration', 'title'])
        u_cats = self.get_unique_categories(self.string_cats) # unique category name
        u_dur = [] # duratio of unice category
        for u_cat in u_cats:
            temp = df.loc[df.category == u_cat]
            dur = np.sum(temp.duration)
            u_dur.append(dur)
        return u_cats, u_dur, date, df


    def print_pi_chart(self, logfile=''):
        if logfile == '':
            today = datetime.datetime.today()
        else:
            today = datetime.datetime.strptime(logfile[:-4], '%Y-%m-%d')

        filename = '{0:d}-{1:02d}-{2:02d}.png'.format(today.year, today.month, today.day)
        u_cats, u_dur, date, df = self.analyze(logfile)
        total_dur = np.sum(u_dur)
        total_hr = int(np.floor(total_dur / 3600))
        total_min = int(np.floor((total_dur-total_hr*3600) / 60))
        total_sec = int(total_dur%60)
        if (total_dur > 0):
            plt.figure(num=None, figsize=(8, 6), dpi=80, facecolor='w', edgecolor='k')
            plt.title('{0:02}.{1:02}.{2:04} - {3:02}:{4:02}:{5:02} h'\
                    .format(today.month, today.day, today.year,
                            total_hr, total_min, total_sec))
            plt.pie(u_dur, labels=u_cats, autopct='%1.1f%%', colors = self.get_colors(logfile))
            plt.axis('equal')
            plt.tight_layout()
            path = 'figs/pie/'+filename
            plt.savefig(path)
            #plt.show()
            plt.close()
            
            print('Pie chart saved as {}'.format(path))


    def get_colors(self, logfile):
        colors = []
        u_cats, _, _, _ = self.analyze(logfile)
        for u_cat in u_cats:
            for col_cat, col in self.color_list:
                if u_cat == col_cat:
                    colors.append(col)
        return colors

    def redo_cat(self, logfile=''):
        path = self.path_data + '/' + logfile
        if not os.path.isfile(path):
                raise FileNotFoundError ('Logfile not found. Start script.py first do generate data')
        outlog = ""
        mylog = ""
        try:
            mylog = open(path, "r")
            outlog = open(self.path_data + '/' +"mod.log", "w")
            for line in mylog:
                words = line.split(',')
                if (len(words) >3):
                    words[1] = self.get_cat(words[3])

                line = ",".join(words)
                outlog.write(line)

            mylog.close()  
            outlog.close()
        except (RuntimeError, TypeError, NameError):
            return
        if os.path.isfile(outlog.name) and os.path.isfile(mylog.name):
            shutil.copyfile(outlog.name,mylog.name) 
            shutil.remove(outlog.name)       

    def print_review(self, logfile=''):
        u_cats, u_dur, date, df = self.analyze(logfile)
        print('')
        print('')
        total_dur = np.sum(df.duration)
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

        sum_cat_time = total_dur - np.sum(u_dur)
        sum_dur_hr = int(np.floor(sum_cat_time/3600))
        sum_dur_min = int(np.floor((sum_cat_time - sum_dur_hr*3500)/60))
        sum_dur_sec = sum_cat_time%60
        print('-------------------------------------')
        print('{0: 6}:{1:02}:{2:02} h not categorized'.format(sum_dur_hr, sum_dur_min, sum_dur_sec))


    def get_log_list(self):
        log_list = os.listdir(self.path_data)
        date_list = []
        for log in log_list:
            date_list.insert(0,datetime.datetime.strptime(log[:-4], '%Y-%m-%d'))
        return log_list, date_list


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
        week_days=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        _, u_dur, date, df = self.analyze(logfile)
        log_list, date_list = self.get_log_list()
        u_cats = self.get_unique_categories()
        with open('html/head.txt', 'r') as file:
            head = file.readlines()
        with open('html/tail.txt', 'r') as file:
            tail = file.read()

        with open('html/index.html', 'w') as file:

            # TABLE
            file.writelines(head)
            row = '<table>\n'
            row += '<tr>\n<td></td>'
            for cat in u_cats:
                row += '<td><b>{}</b></td>\n'.format(cat)
            row += '<td><b>Total Time</b></td></tr>'

            self.print_pi_chart()
            self.print_timeline()
            for log in reversed(log_list):
                row += '<tr>\n\t<td>'
                u_cat, u_dur, date, df = self.analyze(log)
                date = datetime.datetime.strptime(log[:-4], '%Y-%m-%d')
                row += '<b>{0:02}.{1:02}.{2:04},{3}</b>'.format(date.month, date.day, date.year,week_days[date.weekday()])
                row += '</td>'
                total_time =0
                for dur in u_dur:
                    total_time = total_time + dur                    
                    dur_hr = int(np.floor(dur/3600))
                    dur_min = int(np.floor((dur-dur_hr*3600)/60))
                    dur_sec = int(dur%60)
                    row += '<td>'
                    row += '{0: 6}:{1:02}:{2:02}'.format(dur_hr, dur_min, dur_sec)
                    row += '</td>\n'
                tot_time = sec2str(total_time)
                row += '<td>{0: 6}:{1:02}:{2:02}</td>'.format(tot_time[0],tot_time[1],tot_time[2])
                row += '</tr>\n'
            file.write(row)
            file.write('</table>\n')

            # images
            file.write('<div class="gallery">\n')
            img_list = os.listdir('figs/pie')
            for img in reversed(img_list):
                img_row = '<img src="../figs/pie/{}" width=500></br>\n'.format(img)
                file.write(img_row)
            file.write('</div>\n')
            file.writelines(tail)
        print('html updated')


if __name__ == '__main__':
    main()
