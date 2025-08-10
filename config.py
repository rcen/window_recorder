# config.py
import os
import configparser

def get_app_timezone():
    """
    Reads the timezone from the [SETTINGS] section of config.dat.
    Falls back to a default if not specified.
    """
    try:
        config = configparser.ConfigParser()
        # Assuming config.dat is in the same directory as this script
        config_path = os.path.join(os.path.dirname(__file__), 'config.dat')
        if os.path.exists(config_path):
            config.read(config_path)
            # Use 'timezone' key, fallback to 'America/New_York'
            return config.get('SETTINGS', 'timezone', fallback='America/New_York')
    except Exception:
        # In case of any error reading the file, return a safe default
        pass
    return 'America/New_York'

TIMEZONE = get_app_timezone()
