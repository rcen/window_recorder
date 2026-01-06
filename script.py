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

KNOWN ISSUE: Microsoft Teams tracking
    Teams runs as a PWA/Electron app inside Microsoft Edge (msedge.exe), not as a standalone
    process. This causes window title detection to be unreliable - titles may be slow to update
    or return empty strings. The current workaround uses:
    - Retry logic (3 attempts with 50ms delays)
    - Process name detection (msedge.exe with Teams in title)
    - Title normalization to extract Teams context
    If Teams tracking remains problematic, consider using UI Automation API or accessibility
    APIs instead of GetWindowText().
"""
import os
import sys
import time
import datetime
import pyautogui
import configparser
import numpy as np
import csv
import logging
from analytics import Analytics
from broser_start import generate_inspirational_html
from productivity_agent import ProductivityAgent, GoalStatus
from categories import is_wasted
import platform
import uuid
from typing import Any, Dict, Optional

# --- Setup Logging ---
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    filename=log_file_path,
    filemode='w' # Overwrite log file on each run
)
logging.getLogger('matplotlib').setLevel(logging.INFO)
# --- End Logging Setup ---

import psutil
from multiprocessing import Process, Queue
import tkinter as tk
import database
from config import FOCUS_SLOTS
import socket
from urllib.parse import urlparse
from threading import Thread
import queue

if platform.system() == "Windows":
    import win32gui
    import msvcrt
    import win32process
    import pythoncom
    from pywinauto import Application, Desktop
    from pywinauto.findwindows import ElementNotFoundError
else:
    import Xlib
    from Xlib import display
    from pynput import keyboard

last_time_key_pressed = time.time()
last_time_mouse_moved = time.time()
last_mouse_coords = [0, 0]
start_of_event = time.time()
last_window = 'start tracking'
last_window_url = None
last_event = ''
idle_time = 180 # 3 minutes.
html_update_time = time.time() + 30
inspirational_html_update_time = time.time() + 600 # 10 minutes
ram_check_time = time.time() + 10
wasted_time_start = None
last_warning_minute = 0
previous_category_state = None  # Track if previous state was 'wasting' or 'productive'
activity_page_reminder_time = time.time() + 1800  # 30 minutes = 1800 seconds
productivity_check_time = time.time() + 300  # Check productivity goals every 5 minutes
productivity_agent = None  # Will be initialized in main()

CHROMIUM_BROWSER_PROCESSES = {
    'chrome.exe',
    'msedge.exe',
    'brave.exe',
    'vivaldi.exe',
    'opera.exe',
    'opera_gx.exe',
    'chromium.exe',
    'arc.exe'
}


def format_url(url):
    short = shorten_url(url)
    if short:
        return f" | URL: {short}"
    return ''

last_notification_time = 0
notification_cooldown = 60  # seconds
alert_queue = None
alert_process = None
alert_result_queue = None
WARNING_RESPONSE_THRESHOLD = 60

def alert_process_func(message_queue: Any, result_queue: Any) -> None:
    current_alert: Dict[str, Any] = {
        'id': None,
        'message': '',
        'title': 'Warning',
        'start_time': None,
        'created_at': None,
        'active': False,
        'buttons': [],
    }

    def reset_display() -> None:
        current_alert.update({
            'id': None,
            'message': '',
            'title': 'Warning',
            'start_time': None,
            'created_at': None,
            'active': False,
            'buttons': [],
        })
        message_var.set('')
        timer_var.set('')
        # Remove old buttons
        for widget in button_frame.winfo_children():
            widget.destroy()
        root.withdraw()

    def finalize_alert(result: Optional[str] = None) -> None:
        if not current_alert['active']:
            return

        elapsed: float = time.time() - current_alert['start_time'] if current_alert['start_time'] else 0.0
        outcome: str = result or ('win' if elapsed <= WARNING_RESPONSE_THRESHOLD else 'lose')
        payload: Dict[str, Any] = {
            'id': current_alert['id'],
            'result': outcome,
            'elapsed_seconds': elapsed,
            'timestamp': time.time(),
            'started_at': current_alert['start_time'],
            'created_at': current_alert['created_at'],
            'message': current_alert['message'],
            'title': current_alert['title'],
        }
        try:
            result_queue.put(payload)
        except Exception:
            logging.exception('Failed to push alert result payload')

        reset_display()

    def activate_alert(payload: Dict[str, Any]) -> None:
        if current_alert['active']:
            finalize_alert(result='lose')

        current_alert['id'] = payload.get('id')
        current_alert['message'] = payload.get('message', '')
        current_alert['title'] = payload.get('title', 'Warning')
        current_alert['start_time'] = time.time()
        current_alert['created_at'] = payload.get('created_at', current_alert['start_time'])
        current_alert['active'] = True
        current_alert['buttons'] = payload.get('buttons', [])

        message_var.set(current_alert['message'])
        root.title(current_alert['title'])
        
        # Clear existing buttons
        for widget in button_frame.winfo_children():
            widget.destroy()

        # Add custom buttons if any
        if current_alert['buttons']:
            for btn_text in current_alert['buttons']:
                btn = tk.Button(button_frame, text=btn_text, 
                         command=lambda t=btn_text: finalize_alert(result=t))
                btn.pack(side=tk.LEFT, padx=5)
                if btn_text == 'Close Page':
                    btn.focus_set()
        
        # Always add OK button
        tk.Button(button_frame, text='OK', command=on_ok).pack(side=tk.LEFT, padx=5)

        root.deiconify()
        root.attributes('-topmost', True)
        root.after(250, lambda: root.attributes('-topmost', False))

    def on_ok() -> None:
        finalize_alert()

    def poll_events() -> None:
        try:
            while True:
                payload = message_queue.get_nowait()
                if not isinstance(payload, dict):
                    continue
                activate_alert(payload)
        except queue.Empty:
            pass

        if current_alert['active'] and current_alert['start_time']:
            elapsed_seconds = max(time.time() - current_alert['start_time'], 0.0)
            
            # Auto-close after 5 minutes to allow system sleep if user is away
            if elapsed_seconds > 300:
                finalize_alert(result='timeout')
            else:
                minutes, seconds = divmod(int(elapsed_seconds), 60)
                timer_var.set(f"Time elapsed: {minutes:02d}:{seconds:02d}")
        else:
            timer_var.set('')

        root.after(250, poll_events)

    root = tk.Tk()
    root.title('Warning')
    message_var = tk.StringVar(value='')
    timer_var = tk.StringVar(value='')

    label = tk.Label(root, textvariable=message_var, padx=20, pady=10, wraplength=420, justify='left')
    label.pack()

    timer_label = tk.Label(root, textvariable=timer_var, padx=20, pady=5, fg='red')
    timer_label.pack()

    button_frame = tk.Frame(root)
    button_frame.pack(pady=10)

    root.protocol('WM_DELETE_WINDOW', on_ok)
    root.withdraw()
    root.after(100, poll_events)
    root.mainloop()

def show_non_blocking_alert(message, title, buttons=None):
    global last_notification_time
    global alert_queue
    if time.time() - last_notification_time < notification_cooldown:
        return
    last_notification_time = time.time()
    if platform.system() == "Linux":
        os.system(f'notify-send "{title}" "{message}"')
    else:
        if alert_queue:
            event_payload = {
                'id': str(uuid.uuid4()),
                'message': message,
                'title': title,
                'created_at': time.time(),
                'buttons': buttons or []
            }
            alert_queue.put(event_payload)


def process_alert_results() -> None:
    global alert_result_queue
    if not alert_result_queue:
        return

    try:
        while True:
            payload = alert_result_queue.get_nowait()
            if not isinstance(payload, dict):
                continue

            event_id = payload.get('id')
            result = payload.get('result')
            elapsed_seconds = float(payload.get('elapsed_seconds', 0.0))
            timestamp = float(payload.get('timestamp', time.time()))
            message = payload.get('message')
            title = payload.get('title')

            if not event_id or not result:
                continue

            if result == 'Close Page':
                logging.info("User chose to close the wasted page.")
                try:
                    # Attempt to close the current window (assumed to be the wasted one)
                    # We might need to ensure the correct window is focused first, 
                    # but typically the user is interacting with the dialog which is on top.
                    # However, to send Ctrl+W to the browser, we need the browser to be focused.
                    
                    # 1. Get the foreground window (which might be our dialog or something else)
                    # 2. If it's our dialog, we need to find the browser window.
                    #    But wait, the dialog closes immediately after clicking.
                    #    So the previous window (the browser) should regain focus automatically 
                    #    in many cases, OR we need to force it.
                    
                    # A simple approach: Wait a split second for dialog to close and focus to return
                    time.sleep(0.5)
                    
                    # Send Ctrl+W
                    pyautogui.hotkey('ctrl', 'w')
                    logging.info("Sent Ctrl+W to close page")
                    
                except Exception as e:
                    logging.error(f"Failed to close page: {e}")

            try:
                database.record_warning_flag(
                    event_id=event_id,
                    timestamp=timestamp,
                    elapsed_seconds=elapsed_seconds,
                    result=result,
                    message=message,
                    title=title,
                )
                logging.info(
                    "Recorded warning response: %s in %.1fs", result, elapsed_seconds
                )
            except Exception:
                logging.exception("Failed to persist warning flag result")
    except queue.Empty:
        return

def check_ram():
    global ram_check_time
    if time.time() > ram_check_time:
        free_ram_gb = psutil.virtual_memory().free / (1024.0 * 1024 * 1024)
        # print(f"Debug: Free RAM: {free_ram_gb:.2f} GB")
        if free_ram_gb < 0.6:
            show_non_blocking_alert(f"Warning: Free RAM is less than 1GB ({free_ram_gb:.2f}GB)", "Low RAM Warning")
        ram_check_time = time.time() + 10

def get_current_focus_slot():
    """
    Checks if the current time is within any of the defined focus slots.
    Returns the start and end time of the current slot if active, otherwise None.
    """
    now = datetime.datetime.now().time()
    for start_str, end_str in FOCUS_SLOTS:
        start_time = datetime.datetime.strptime(start_str, '%H:%M').time()
        end_time = datetime.datetime.strptime(end_str, '%H:%M').time()
        if start_time <= now <= end_time:
            return start_str, end_str
    return None


def is_browser_window(window_title):
    """Check if the current window is a web browser."""
    browser_keywords = ['chrome', 'firefox', 'edge', 'brave', 'opera', 'safari', 'vivaldi', 'chromium']
    window_lower = window_title.lower()
    return any(keyword in window_lower for keyword in browser_keywords)


def is_activity_page_already_open():
    """Check if the activity page (index.html) is already open in any browser window."""
    if platform.system() != "Windows":
        return False
    
    try:
        activity_indicators = ['127.0.0.1:8042', '8042', 'window_recorder', 'track your time']
        open_windows = []
        
        def enum_windows_callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if window_title:
                    results.append(window_title.lower())
        
        win32gui.EnumWindows(enum_windows_callback, open_windows)
        
        # Check if any window title contains activity page indicators
        for window_title in open_windows:
            # Check for the HTTP localhost URL or file path
            if any(indicator.lower() in window_title for indicator in activity_indicators):
                return True
        
        return False
    except Exception as e:
        logging.debug(f"Error checking for open activity page: {e}")
        return False


def open_activity_page_in_background():
    """Open the activity page in the default browser without bringing it to foreground."""
    import webbrowser
    
    # Check if activity page is already open
    if is_activity_page_already_open():
        print("Activity page already open, skipping...")
        return
    
    # Open via HTTP server instead of file:// to allow fetch() requests
    activity_page_url = 'http://127.0.0.1:8042/'
    
    try:
        # Open in background - just create a new tab, don't focus it
        webbrowser.open(activity_page_url, new=2, autoraise=False)
        print("Opened activity page in background")
    except Exception as e:
        print(f"Failed to open activity page: {e}")


def main():
    global last_window
    global last_window_url
    global last_event
    global start_of_event
    global html_update_time
    global inspirational_html_update_time
    global wasted_time_warning_issued
    global wasted_time_start
    global last_warning_minute
    global alert_queue
    global alert_process
    global alert_result_queue
    global previous_category_state
    global activity_page_reminder_time
    global productivity_check_time
    global productivity_agent

    hostname = socket.gethostname()
    database.initialize_database()

    # Initialize Productivity Agent with warning callback
    def productivity_warning_callback(title: str, message: str, level: str):
        """Callback to display productivity warnings."""
        show_non_blocking_alert(message, title)
        print(f"[ProductivityAgent] {level.upper()}: {message}")
    
    productivity_agent = ProductivityAgent(callback_warn=productivity_warning_callback)
    print("[ProductivityAgent] Initialized with goals:")
    for cat, goal in productivity_agent.goals.items():
        type_str = "maximize" if goal.is_positive else "minimize"
        print(f"  • {cat}: {goal.daily_target_minutes} min/day ({type_str})")

    # Sync with the remote server at startup to get the latest data
    # database.sync_remote_to_local()

    hidden_tk_root = None
    if platform.system() == "Windows":
        try:
            # Create a hidden root Tk window in the main thread.
            # This helps prevent tkinter-related garbage collection errors that can be
            # triggered by other libraries in worker threads.
            hidden_tk_root = tk.Tk()
            hidden_tk_root.withdraw()
        except (tk.TclError, ImportError):
            # Fail gracefully if tkinter is not available or fails to initialize
            hidden_tk_root = None

        alert_queue = Queue()
        alert_result_queue = Queue()
        alert_process = Process(target=alert_process_func, args=(alert_queue, alert_result_queue))
        alert_process.daemon = True
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
    last_sync_time = time.time()
    while True:
        current_loop_time = time.time()
        time_jump = current_loop_time - last_loop_time
        last_loop_time = current_loop_time

        # A jump of more than 5s is considered a sleep/off event.
        if time_jump > 5.0:
            # System sleep/off detected. End the event that was active before the jump.
            # Calculate duration as time from event start to just BEFORE sleep (not after!)
            time_before_sleep = current_loop_time - time_jump
            duration_before_jump = time_before_sleep - start_of_event
            if last_event and duration_before_jump > 0:
                category = 'idle' if last_event == 'idle' else analytic.get_cat(last_window, last_window_url)

                bRecord = False
                if duration_before_jump < 18 and category == 'idle':
                    bRecord = True
                if duration_before_jump > 2 and category != 'idle':
                    bRecord = True
                if bRecord:
                    save_data([time_before_sleep, category, int(duration_before_jump), last_window], hostname, last_window_url)
                    try:
                        mins = int(np.floor(duration_before_jump/60))
                        secs = int(np.floor(duration_before_jump - mins*60))
                        local_t = time.localtime(start_of_event)
                        print("{0:02}:{1:02} -{2: 3}:{3:02} min\t".format(local_t.tm_hour, local_t.tm_min, mins, secs),
                              "{} \t".format(category),
                              "(pre-sleep) ({})".format(last_event[:120]),
                              format_url(last_window_url))
                    except UnicodeError:
                        print("{0: 5.0f} s\t".format(duration_before_jump), "UNICODE ERROR")

            # Reset the state for the post-sleep/wake event.
            # Crucially, we set the start time to NOW, ignoring the sleep duration.
            start_of_event = current_loop_time
            last_event = 'idle' # Assume idle on wake, will be re-evaluated.
            last_window_url = None
            last_window = 'Computer Wake'
            last_loop_time = current_loop_time # Reset last_loop_time as well
            continue # Skip the rest of this loop iteration.

        # --- New: Cap any single event duration to 30 min (1800s) ---
        max_event_duration = 1800  # 30 minutes
        if last_event and (time.time() - start_of_event) > max_event_duration:
            # End the current event and start a new one (idle or current window)
            duration = max_event_duration
            category = 'idle' if last_event == 'idle' else analytic.get_cat(last_window, last_window_url)
            save_data([start_of_event + max_event_duration, category, int(duration), last_window], hostname, last_window_url)
            try:
                mins = int(np.floor(duration/60))
                secs = int(np.floor(duration - mins*60))
                local_t = time.localtime(start_of_event)
                print("{0:02}:{1:02} -{2: 3}:{3:02} min\t".format(local_t.tm_hour, local_t.tm_min, mins, secs),
                      "{} \t".format(category),
                      "(auto-split) ({})".format(last_event[:120]),
                      format_url(last_window_url))
            except UnicodeError:
                print("{0: 5.0f} s\t".format(duration), "UNICODE ERROR")
            # Start a new event from now
            start_of_event = time.time()
            last_event = 'idle'
            last_window = 'auto-split (idle)'
            last_window_url = None


        mouse_idle = is_mouse_idle()
        keyboard_idle = is_keyboard_idle(0.01)
        current_window, current_url = get_window_name()
        idle = mouse_idle and keyboard_idle

        # --- New: Treat 'start page' as idle if focused > 5 min ---
        start_page_idle_threshold = 300  # 5 minutes
        if current_window.strip().lower() == 'start page' and (time.time() - start_of_event) > start_page_idle_threshold:
            idle = True
            current_window = 'start page (idle)'
            current_url = None

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
                    category = analytic.get_cat(last_window, last_window_url)

                bRecord = False
                if duration < 18 and category == 'idle':
                    bRecord = True
                if duration > 2 and category != 'idle':
                    bRecord = True
                if bRecord == True:
                    save_data([time.time(), category, int(duration), last_window], hostname, last_window_url)

            # A new event has just started. Update state and print it for immediate feedback.
            last_window = current_window
            last_window_url = None if idle else current_url
            start_of_event = time.time()
            last_event = current_event
            try:
                new_category = 'idle' if idle else analytic.get_cat(current_event, current_url)
                local_t = time.localtime(start_of_event)
                print("{0:02}:{1:02} - Starting:\t".format(local_t.tm_hour, local_t.tm_min),
                      "{} \t".format(new_category),
                      "({})".format(current_event[:120]),
                      format_url(current_url))
            except Exception:
                # Fail silently if printing the new event causes an issue
                pass

        if time.time() > html_update_time:
            # This updates the main analysis report (index.html)
            analytic.create_html()
            
            # Dynamic HTML update interval based on current activity
            # Fast updates (15s) when wasting time for immediate feedback
            # Medium updates (30s) when productive to see streak increment
            # Quick update (15s) when switching between productive/wasted for instant feedback
            current_category = 'idle' if idle else analytic.get_cat(current_window, current_url)
            is_currently_wasting = is_wasted(current_category)
            
            # Determine current state
            current_state = 'wasting' if is_currently_wasting else 'productive'
            
            # Check if category switched
            category_switched = (previous_category_state is not None and 
                                previous_category_state != current_state)
            
            # Set interval: 15s if switched or wasting, 30s if productive (no switch)
            if category_switched:
                html_update_interval = 15  # Quick update on state change
            else:
                html_update_interval = 15 if is_currently_wasting else 30
            
            # Update the previous state for next iteration
            previous_category_state = current_state
            
            html_update_time = time.time() + html_update_interval

        if time.time() > inspirational_html_update_time:
            # This updates the inspirational image page
            image_folder = analytic.config.get('SETTINGS', 'image_folder', fallback='figs/pictures')
            md_folder = analytic.config.get('SETTINGS', 'md_folder', fallback='C:/Users/YourUser/Documents/Notes')
            result = generate_inspirational_html(image_folder, md_folder)
            inspirational_html_update_time = time.time() + 600 # Reset for another 10 minutes

        # Activity page reminder every 30 minutes
        if time.time() > activity_page_reminder_time:
            current_category = 'idle' if idle else analytic.get_cat(current_window, current_url)
            is_currently_wasting = is_wasted(current_category)
            
            # Rule 1: If not on web browser, open activity page in background
            if not is_browser_window(current_window):
                print("30-min reminder: Opening activity page in background...")
                open_activity_page_in_background()
            
            # Rule 2: If on browser and wasting time, show dialog
            elif is_browser_window(current_window) and is_currently_wasting:
                print("30-min reminder: You're wasting time on browser, check your activity page!")
                show_non_blocking_alert(
                    "You've been wasting time! Please check your productivity dashboard.",
                    "Activity Page Reminder"
                )
            
            # Rule 3: If productive, no interruption (just silently reset timer)
            # No action needed for productive work
            
            # Reset for next 30 minutes
            activity_page_reminder_time = time.time() + 1800

        current_category = 'idle' if idle else analytic.get_cat(current_window, current_url)
        if is_wasted(current_category):
            if wasted_time_start is None:
                wasted_time_start = time.time()
                # last_warning_minute is reset when the activity is no longer "wasted"

            wasted_time = time.time() - wasted_time_start
            current_wasted_minutes = int(wasted_time / 60)
            print(f"wasted time is {wasted_time:.2f} seconds", end='\r')

            focus_slot = get_current_focus_slot()
            
            # Set the warning threshold in minutes
            warning_threshold_minutes = 1 if focus_slot else 6

            # Check if a new warning should be issued
            if current_wasted_minutes >= warning_threshold_minutes and current_wasted_minutes > last_warning_minute:
                buttons = []
                if focus_slot:
                    start, end = focus_slot
                    message = f"Focus time is {start} till {end}. You have wasted {current_wasted_minutes} minute(s)."
                    buttons = ['Close Page']
                else:
                    message = f"You have been on a 'wasted' task for {current_wasted_minutes} minute(s)."
                
                show_non_blocking_alert(message, "Wasted Time Warning", buttons=buttons)
                last_warning_minute = current_wasted_minutes # Update the last warning time
        else:
            if wasted_time_start is not None:
                print(" " * 50, end='\r')
            wasted_time_start = None
            last_warning_minute = 0 # Reset when activity is no longer wasted

        check_ram()
        process_alert_results()
        
        # --- Productivity Goal Monitoring ---
        if time.time() > productivity_check_time and productivity_agent:
            try:
                # Pass current activity so we don't interrupt productive work
                warnings = productivity_agent.check_and_warn(current_category)
                if warnings:
                    print(f"[ProductivityAgent] {len(warnings)} goal(s) need attention")
            except Exception as e:
                logging.error(f"[ProductivityAgent] Error checking goals: {e}")
            productivity_check_time = time.time() + 300  # Check every 5 minutes
        
        if time.time() - last_sync_time > 300: # 5 minutes
            print("Running periodic sync...")
            # database.sync_local_data()
            last_sync_time = time.time()

        if hidden_tk_root:
            try:
                hidden_tk_root.update()
            except tk.TclError:
                # The window might have been destroyed, ignore.
                pass

        time.sleep(0.3)  # Reduced from 0.5s for more responsive tracking

def save_data(data, source, window_url=None):
    """Saves a single data record to the database."""
    # data format is [timestamp, category, duration, window_title]
    window_url_short = shorten_url(window_url)
    database.insert_activity(data[0], data[1], data[2], data[3], source, window_url, window_url_short)



def is_mouse_idle():
    global last_time_mouse_moved
    global last_mouse_coords
    global idle_time

    # Removed sleep to avoid adding latency to window detection
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

def shorten_url(url, max_length=80):
    """Shortens a URL for display without losing the host information."""
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
        return url if url and len(url) <= max_length else (f"{url[:max_length-3]}..." if url else None)

import platform
import psutil
from multiprocessing import Process, Queue
import tkinter as tk
import database
from config import FOCUS_SLOTS
import socket
from urllib.parse import urlparse

if platform.system() == "Windows":
    import win32gui
    import msvcrt
    import win32process
else:
    import Xlib
    from Xlib import display
    from pynput import keyboard

def _extract_chromium_url(hwnd):
    """Attempts to retrieve the URL from a Chromium-based browser window."""
    try:
        pythoncom.CoInitialize()
    except pythoncom.com_error:
        pass

    url_value = None
    try:
        app = Desktop(backend="uia").window(handle=hwnd)
        candidate_queries = [
            {"control_type": "Edit", "auto_id": "view_1022"},
            {"control_type": "Edit", "auto_id": "addressEditBox"},
            {"control_type": "Edit", "auto_id": "urlEditBox"},
            {"control_type": "Edit", "title_re": ".*address.*"},
            {"control_type": "Edit", "found_index": 0},
        ]

        def _extract_from_control(ctrl):
            value = None
            try:
                value = ctrl.get_value()
            except Exception:
                pass
            if not value:
                try:
                    value = ctrl.iface_value.CurrentValue
                except Exception:
                    pass
            if not value:
                try:
                    value = ctrl.window_text()
                except Exception:
                    pass
            return value

        for query in candidate_queries:
            try:
                ctrl = app.child_window(**query).wrapper_object()
                value = _extract_from_control(ctrl)
                if value:
                    cleaned = value.strip()
                    if cleaned and (cleaned.startswith("http") or "//" in cleaned or "." in cleaned):
                        url_value = cleaned.lower()
                        logging.debug("Extracted URL via query %s: %s", query, url_value)
                        break
            except (ElementNotFoundError, AttributeError):
                continue

        if not url_value:
            try:
                for ctrl in app.descendants(control_type="Edit"):
                    value = _extract_from_control(ctrl)
                    if value:
                        cleaned = value.strip()
                        if cleaned and (cleaned.startswith("http") or "//" in cleaned or "." in cleaned):
                            url_value = cleaned.lower()
                            logging.debug("Extracted URL via fallback scan: %s", url_value)
                            break
            except Exception as e:
                logging.debug("Fallback URL extraction failed: %s", e)
    except Exception as exc:
        logging.debug("URL extraction failed: %s", exc)
        url_value = None
    finally:
        try:
            pythoncom.CoUninitialize()
        except pythoncom.com_error:
            pass

    return url_value


def get_window_name():
    global last_window, last_window_url

    if platform.system() == "Windows":
        try:
            parent = win32gui.GetForegroundWindow()
            if not parent:
                return "desktop", None

            # Try to get window text with retry for slow-responding apps like Teams
            window_name = None
            for attempt in range(3):
                try:
                    window_name = win32gui.GetWindowText(parent)
                    if window_name:  # Successfully got a non-empty name
                        break
                    if attempt < 2:  # Don't sleep on last attempt
                        time.sleep(0.05)  # Short sleep before retry
                except:
                    if attempt < 2:
                        time.sleep(0.05)
                    continue
            
            # If we still don't have a window name, use last known window
            if not window_name:
                logging.debug(f"Failed to get window name after retries, using last window: {last_window}")
                return last_window, last_window_url

            if window_name == "not a fan":
                return last_window, last_window_url

            normalized_title = window_name.replace(',', '').lower()
            url_value = None

            try:
                _, pid = win32process.GetWindowThreadProcessId(parent)
                process_name = psutil.Process(pid).name().lower()
                
                # Special handling for Teams (which runs as Edge/Chrome)
                # Teams windows often have slow/empty title responses
                if 'microsoft teams' in normalized_title or 'teams.microsoft.com' in normalized_title:
                    logging.debug(f"Teams detected via title - Window: '{window_name}', Process: {process_name}")
                    # Force Teams title to be consistent
                    if process_name == 'msedge.exe' or process_name == 'chrome.exe':
                        # Extract the specific Teams context if available
                        if '|' in window_name:
                            # "Microsoft Teams - Chat | Meeting Name | Microsoft Teams"
                            parts = [p.strip() for p in window_name.split('|')]
                            normalized_title = f"microsoft teams - {parts[1] if len(parts) > 1 else 'active'}".lower()
                        else:
                            normalized_title = "microsoft teams"
                
                if process_name in CHROMIUM_BROWSER_PROCESSES:
                    url_value = _extract_chromium_url(parent)
            except (psutil.Error, ProcessLookupError, PermissionError) as e:
                logging.debug(f"Error getting process info: {e}")
                pass

            return normalized_title, url_value

        except (win32gui.error, psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logging.debug(f"Error in get_window_name: {e}")
            # Return last known window instead of desktop to avoid losing tracking
            if last_window and last_window != 'start tracking':
                return last_window, last_window_url
            return "desktop", None
    else:
        try:
            if "DISPLAY" not in os.environ or not os.environ["DISPLAY"]:
                return "desktop", None
            d = display.Display()
            root = d.screen().root
            window_id = root.get_full_property(d.intern_atom('_NET_ACTIVE_WINDOW'), Xlib.X.AnyPropertyType).value[0]
            window = d.create_resource_object('window', window_id)
            window_name_prop = window.get_full_property(d.intern_atom('_NET_WM_NAME'), Xlib.X.AnyPropertyType)
            
            if window_name_prop and window_name_prop.value:
                return window_name_prop.value.decode('utf-8', 'ignore').lower(), None
            else:
                window_name_prop = window.get_full_property(d.intern_atom('WM_NAME'), Xlib.X.AnyPropertyType)
                if window_name_prop and window_name_prop.value:
                    return window_name_prop.value.decode('utf-8', 'ignore').lower(), None
                else:
                    return "desktop", None
        except (Xlib.error.XError, IndexError):
            return "desktop", None
        except Exception:
            return "desktop", None




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
