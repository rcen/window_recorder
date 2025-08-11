# -*- coding: utf-8 -*-
"""
Created on Mon Aug 13 08:29:50 2018

@author: Nicolaj Baramsky
install win32 gui from:
    https://stackoverflow.com/questions/20113456/installing-win32gui-python-module#20128310
    https://www.lfd.uci.edu/~gohlke/pythonlibs/#pywin32

    Step 1: Download the pywin32....whl
    Step 2: pip install pywin32....whl
    Step 3: C:/python32/python.exe Scripts/pywin32_postinstall.py -install
    Step 4: python
"""
import os
import sys
import time
import datetime
import pyautogui
import configparser
import numpy as np
import csv
from analytics import Analytics
from broser_start import generate_inspirational_html
import platform
import psutil
from multiprocessing import Process, Queue
import tkinter as tk
import database

if platform.system() == "Windows":
    import win32gui
    import msvcrt
else:
    import Xlib
    from Xlib import display
    from pynput import keyboard

last_time_key_pressed = time.time()
last_time_mouse_moved = time.time()
last_mouse_coords = [0, 0]
start_of_event = time.time()
last_window = 'start tracking'
last_event = ''
idle_time = 3*60 # 3 minutes.
html_update_time = time.time() + 30
ram_check_time = time.time() + 10
wasted_time_start = None
wasted_time_warning_issued = False

last_notification_time = 0
notification_cooldown = 60  # seconds
alert_queue = None
alert_process = None

def alert_process_func(queue):
    def update_text():
        try:
            message, title = queue.get_nowait()
            label.config(text=message)
            root.title(title)
            root.deiconify()  # Show the window
        except Exception:
            pass
        root.after(100, update_text)

    def on_closing():
        root.withdraw()  # Hide the window instead of closing it

    root = tk.Tk()
    root.title("Warning")
    label = tk.Label(root, text="", padx=20, pady=20)
    label.pack()
    ok_button = tk.Button(root, text="OK", command=on_closing)
    ok_button.pack(pady=5)
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.withdraw()  # Hide the window initially
    root.after(100, update_text)
    root.mainloop()

def show_non_blocking_alert(message, title):
    global last_notification_time
    if time.time() - last_notification_time < notification_cooldown:
        return
    last_notification_time = time.time()
    if platform.system() == "Linux":
        os.system(f'notify-send "{title}" "{message}"')
    else:
        if alert_queue:
            alert_queue.put((message, title))

def check_ram():
    global ram_check_time
    if time.time() > ram_check_time:
        free_ram_gb = psutil.virtual_memory().free / (1024.0 * 1024 * 1024)
        # print(f"Debug: Free RAM: {free_ram_gb:.2f} GB")
        if free_ram_gb < 0.6:
            show_non_blocking_alert(f"Warning: Free RAM is less than 1GB ({free_ram_gb:.2f}GB)", "Low RAM Warning")
        ram_check_time = time.time() + 10


def main():
    global start_of_event
    global last_window
    global last_event
    global html_update_time
    global wasted_time_warning_issued
    global wasted_time_start
    global alert_queue
    global alert_process

    database.initialize_database()

    if platform.system() == "Windows":
        alert_queue = Queue()
        alert_process = Process(target=alert_process_func, args=(alert_queue,))
        alert_process.start()

    np.seterr(all='ignore')

    analytic = Analytics()
    html_counter = 0;
    print("""
---------------------------------------
TRACK YOUR TIME - DON'T WASTE IT!
---------------------------------------

  TIME           CATEGORY""")

    if platform.system() != "Windows":
        listener = keyboard.Listener(on_press=on_press)
        listener.start()

    last_loop_time = time.time()
    while True:
        current_loop_time = time.time()
        time_jump = current_loop_time - last_loop_time
        last_loop_time = current_loop_time

        # A jump of more than 5s is considered a sleep event, as the loop should run every ~0.5s
        if time_jump > 5.0:
            # System sleep detected. End the previous event.
            duration_before_sleep = last_loop_time - start_of_event
            if last_event:  # Log the event that was active before sleep
                category = 'idle' if last_event == 'idle' else analytic.get_cat(last_window)

                bRecord = False
                if duration_before_sleep < 18 and category == 'idle':
                    bRecord = True
                if duration_before_sleep > 2 and category != 'idle':
                    bRecord = True
                if bRecord:
                    save_data([last_loop_time, category, int(duration_before_sleep), last_window])
                    try:
                        mins = int(np.floor(duration_before_sleep/60))
                        secs = int(np.floor(duration_before_sleep - mins*60))
                        local_t = time.localtime(start_of_event)
                        print("{0:02}:{1:02} -{2: 3}:{3:02} min\t".format(local_t.tm_hour, local_t.tm_min, mins, secs),
                              "{} \t".format(category),
                              "(pre-sleep) ({})".format(last_event[:120]))
                    except UnicodeDecodeError:
                        print("{0: 5.0f} s\t".format(duration_before_sleep), "UNICODE DECODE ERROR")

            # The time spent sleeping is effectively idle time. We reset the state to idle.
            start_of_event = last_loop_time
            last_event = 'idle'
            last_window = 'Computer Sleep'

        mouse_idle = is_mouse_idle()
        keyboard_idle = is_keyboard_idle(0.01)

        current_window = get_window_name()
        idle = mouse_idle and keyboard_idle

        if idle:
            current_event = 'idle'
        else:
            current_event = current_window


        if current_event != last_event:
            # An event has just ended. Log it.
            duration = time.time() - start_of_event
            if last_event:  # Don't log the very first "event" on startup
                if last_event == 'idle':
                    category = 'idle'
                else:
                    category = analytic.get_cat(last_window)

                bRecord = False
                if duration < 18 and category == 'idle':
                    bRecord = True
                if duration > 2 and category != 'idle':
                    bRecord = True
                if bRecord == True:
                    save_data([time.time(), category, int(duration), last_window])
                    try:
                        if sys.version_info.major > 2:
                            mins = int(np.floor(duration/60))
                            secs = int(np.floor(duration - mins*60))
                            local_t = time.localtime(start_of_event)
                            print("{0:02}:{1:02} -{2: 3}:{3:02} min\t".format(local_t.tm_hour, local_t.tm_min, mins, secs),
                                  "{} \t".format(category),
                                  "({})".format(last_event[:120]))
                    except UnicodeDecodeError:
                        print("{0: 5.0f} s\t".format(duration), "UNICODE DECODE ERROR")

            # A new event has just started. Update state and print it for immediate feedback.
            last_window = current_window
            start_of_event = time.time()
            last_event = current_event
            try:
                new_category = 'idle' if idle else analytic.get_cat(current_event)
                local_t = time.localtime(start_of_event)
                print("{0:02}:{1:02} - Starting:\t".format(local_t.tm_hour, local_t.tm_min),
                      "{} \t".format(new_category),
                      "({})".format(current_event[:120]))
            except Exception:
                # Fail silently if printing the new event causes an issue
                pass

        if time.time() > html_update_time:
            # Clear the cache to force re-reading data from the database
            analytic.analysis_cache.clear()
            analytic.create_html()
            image_folder = analytic.config.get('SETTINGS', 'image_folder', fallback='figs/pictures')
            md_folder = analytic.config.get('SETTINGS', 'md_folder', fallback='C:/Users/YourUser/Documents/Notes')
            result = generate_inspirational_html(image_folder, md_folder)
            html_update_time = time.time() + 30

        current_category = 'idle' if idle else analytic.get_cat(current_window)
        if "wasted" in current_category.lower():
            if wasted_time_start is None:
                wasted_time_start = time.time()
                wasted_time_warning_issued = False

            wasted_time = time.time() - wasted_time_start
            print(f"wasted time is {wasted_time:.2f} seconds", end='\r')

            if wasted_time > 6 * 60 and not wasted_time_warning_issued:
                show_non_blocking_alert(f"You have been looking at a 'wasted' window for {wasted_time/60.0:.0f} minutes.", "Wasted Time Warning")
                wasted_time_warning_issued = True
        else:
            if wasted_time_start is not None:
                print(" " * 50, end='\r')
            wasted_time_start = None
            wasted_time_warning_issued = False

        check_ram()
        time.sleep(0.5)

def save_data(data):
    """Saves a single data record to the database."""
    # data format is [timestamp, category, duration, window_title]
    database.insert_activity(data[0], data[1], data[2], data[3])



def is_mouse_idle():
    global last_time_mouse_moved
    global last_mouse_coords
    global idle_time

    time.sleep(0.1)
    try:
        x, y = pyautogui.position()
        mouse_coords = [x,y]
    except:
        pass

    if mouse_coords != last_mouse_coords:
        last_mouse_coords = [x, y]
        last_time_mouse_moved = time.time()

    if time.time() > last_time_mouse_moved + idle_time:
        return True
    return False
def get_window_name():
    if platform.system() == "Windows":
        try:
            parent = win32gui.GetForegroundWindow()
            window_name = win32gui.GetWindowText(parent).lower()
            window_name = window_name.replace(',', '')
            window_name = window_name.lower().encode("latin_1", "ignore")
            window_name = window_name.lower().decode("latin_1", "ignore")

            return window_name
        except win32gui.error as E:
            print(E)
    else:
        try:
            # Check if DISPLAY is set and X server is available
            if "DISPLAY" not in os.environ or not os.environ["DISPLAY"]:
                return "desktop"
            d = display.Display()
            root = d.screen().root
            window_id = root.get_full_property(d.intern_atom('_NET_ACTIVE_WINDOW'), Xlib.X.AnyPropertyType).value[0]
            window = d.create_resource_object('window', window_id)
            window_name = window.get_full_property(d.intern_atom('_NET_WM_NAME'), Xlib.X.AnyPropertyType).value
            if window_name:
                return window_name.decode('utf-8', 'ignore').lower()
            else:
                # Fallback for windows that don't have _NET_WM_NAME
                window_name = window.get_full_property(d.intern_atom('WM_NAME'), Xlib.X.AnyPropertyType).value
                if window_name:
                    return window_name.decode('utf-8', 'ignore').lower()
                else:
                    return "desktop"
        except (Xlib.error.XError, IndexError):
            return "desktop"
        except Exception:
            return "desktop"


def on_press(key):
    global last_time_key_pressed
    last_time_key_pressed = time.time()

def is_keyboard_idle(sleep_duration):
    global last_time_key_pressed
    global idle_time

    if platform.system() == "Windows":
        time.sleep(sleep_duration)
        key_pressed = msvcrt.kbhit()

        if key_pressed:
            #keys = msvcrt.getch() # reads the keys and resets kbhit()
            last_time_key_pressed = time.time()

    if time.time() > last_time_key_pressed + idle_time:
        return True
    return False


if __name__ == '__main__':
    try:
        main()
    finally:
        if alert_process:
            alert_process.terminate()
            alert_process.join()
