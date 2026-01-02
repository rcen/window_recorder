# config.py
import os
import configparser
import datetime
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists.
# This is useful for local development. System-level environment variables
# will always take precedence over values in the .env file.
load_dotenv()

def get_config_parser():
    """Initializes and returns a ConfigParser object with the config file loaded."""
    config = configparser.ConfigParser()
    # Assuming config.dat is in the same directory as this script
    config_path = os.path.join(os.path.dirname(__file__), 'config.dat')
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            config.read_file(f)
    else:
        pass
    return config

def get_database_uri():
    """
    Reads the database URI from environment variables.
    It prioritizes a system-level 'DATABASE_URI' variable, falling back to the
    one defined in the .env file if it's not set in the system.
    """
    return os.environ.get("DATABASE_URI")

def get_app_timezone():
    """
    Reads the timezone from the [SETTINGS] section of config.dat.
    Falls back to a default if not specified.
    """
    try:
        config = get_config_parser()
        # Use 'timezone' key, fallback to 'America/New_York'
        return config.get('SETTINGS', 'timezone', fallback='America/New_York')
    except Exception:
        # In case of any error reading the file, return a safe default
        pass
    return 'America/New_York'

def get_api_key():
    """
    Reads the API key from environment variables.
    It prioritizes a system-level 'API_KEY' variable, falling back to the
    one defined in the .env file if it's not set in the system.
    """
    return os.environ.get("API_KEY")

def get_focus_slots():
    """
    Reads the focus time slots from the [FOCUS_SLOTS] section of config.dat.
    Returns a list of tuples, where each tuple contains the start and end time as strings.
    """
    slots = []
    try:
        config = get_config_parser()
        if config.has_section('FOCUS_SLOTS'):
            for key, value in config.items('FOCUS_SLOTS'):
                try:
                    start_time, end_time = value.split('-')
                    # Basic validation
                    datetime.datetime.strptime(start_time.strip(), '%H:%M')
                    datetime.datetime.strptime(end_time.strip(), '%H:%M')
                    slots.append((start_time.strip(), end_time.strip()))
                except ValueError:
                    print(f"Warning: Invalid time format for focus slot '{key}'. Please use HH:MM-HH:MM.")
    except Exception:
        pass
    return slots

def get_habits():
    """Reads habit definitions from [HABITS] section, returning list of (name, color)."""
    habits = []
    default_palette = [
        '#4caf50', '#ff6b6b', '#4d96ff', '#f6c344', '#9b59b6', '#00a8cc'
    ]
    try:
        config = get_config_parser()
        if config.has_section('HABITS'):
            for idx, (name, color) in enumerate(config.items('HABITS')):
                name = name.strip()
                color = (color or '').strip()
                if not color:
                    color = default_palette[idx % len(default_palette)]
                habits.append((name, color))
    except Exception:
        pass
    return habits


def get_vibe_repos():
    """
    Reads vibe coding repository names from [VIBE_REPOS] section.
    Returns a dict with 'repos' (list of repo names) and 'paths' (list of folder paths).
    
    NOTE: Primary vibe_coding detection now happens via [CATEGORIES] section in config.dat.
    This function is kept for potential query-time analysis or backup detection.
    """
    result = {
        'repos': [],
        'paths': []
    }
    try:
        config = get_config_parser()
        if config.has_section('VIBE_REPOS'):
            # Get repo names
            repos_str = config.get('VIBE_REPOS', 'repos', fallback='')
            if repos_str:
                result['repos'] = [r.strip().lower() for r in repos_str.split(',') if r.strip()]
            
            # Get paths
            paths_str = config.get('VIBE_REPOS', 'paths', fallback='')
            if paths_str:
                result['paths'] = [p.strip().lower() for p in paths_str.split(',') if p.strip()]
    except Exception as e:
        print(f"Warning: Error reading VIBE_REPOS config: {e}")
    return result


def is_vibe_coding(window_title: str) -> bool:
    """
    Detect if the current coding activity is "vibe coding" based on window title.
    
    Parses VS Code window titles like:
    - "filename.py - window_recorder - Visual Studio Code"
    - "window_recorder - Visual Studio Code"
    
    Returns True if the repo/folder matches a vibe repo, False otherwise.
    """
    vibe_config = get_vibe_repos()
    title_lower = window_title.lower()
    
    # Check if any vibe repo name appears in the window title
    for repo in vibe_config['repos']:
        if repo in title_lower:
            return True
    
    # Check if any vibe path appears in the window title
    for path in vibe_config['paths']:
        if path in title_lower:
            return True
    
    return False


def get_coding_type(window_title: str) -> str:
    """
    Determine the type of coding activity.
    Returns: 'vibe_coding', 'work_coding', or 'work' (if undetermined)
    """
    if is_vibe_coding(window_title):
        return 'vibe_coding'
    
    # If it looks like VS Code but not vibe, assume work
    vscode_indicators = ['visual studio code', 'vscode', '- code']
    title_lower = window_title.lower()
    for indicator in vscode_indicators:
        if indicator in title_lower:
            return 'work_coding'
    
    # Default to generic work
    return 'work'


def get_day_boundary_hour():
    """
    Reads the day boundary hour from the [SETTINGS] section of config.dat.
    Returns the hour (0-23) when a new day should start for activity tracking.
    Defaults to 3 AM if not specified.
    """
    try:
        config = get_config_parser()
        hour = config.getint('SETTINGS', 'day_boundary_hour', fallback=3)
        # Validate the hour is in valid range
        if 0 <= hour <= 23:
            return hour
        else:
            print(f"Warning: day_boundary_hour must be between 0-23. Using default of 3.")
            return 3
    except Exception:
        return 3

TIMEZONE = get_app_timezone()
# API_KEY = get_api_key()
API_KEY = None
FOCUS_SLOTS = get_focus_slots()
DAY_BOUNDARY_HOUR = get_day_boundary_hour()
HABITS = get_habits()
VIBE_REPOS = get_vibe_repos()
