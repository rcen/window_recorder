# config.py
import os
import configparser

def get_config_parser():
    """Initializes and returns a ConfigParser object with the config file loaded."""
    config = configparser.ConfigParser()
    # Assuming config.dat is in the same directory as this script
    config_path = os.path.join(os.path.dirname(__file__), 'config.dat')
    if os.path.exists(config_path):
        config.read(config_path)
    return config

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
    Reads the API key from the [API] section of config.dat.
    """
    try:
        config = get_config_parser()
        return config.get('API', 'key', fallback=None)
    except Exception:
        return None

TIMEZONE = get_app_timezone()
API_KEY = get_api_key()
