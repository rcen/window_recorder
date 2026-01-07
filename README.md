# Monitor the time you spend
1. run 'script.py' in background
2. run 'analytics.py' to see where you waisted your time
3. have fun

## requirements
requires the following packages
* pyautogui
* msvcrt
* numpy
* pandas
* configparser
* win32 gui (see below)


### install win32 gui from:
Details from [satackoverflow](https://stackoverflow.com/questions/20113456/installing-win32gui-python-module#20128310)
1. Download the pywin32....whl from [pythonlibs](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pywin32)
2. pip install pywin32....whl
3. C:\python32\python.exe Scripts\pywin32_postinstall.py -install

more details under [Module win32gui](http://timgolden.me.uk/pywin32-docs/win32gui.html)

## Local Configuration (.env file)
For local development, a `.env` file is required to manage environment variables. This file should be placed in the root of the project directory. It is used to store sensitive information like database connection strings and API keys, and it is ignored by version control (see `.gitignore`).

Create a file named `.env` in the project root and add the following variables:

```
# .env

# Example connection URI for a remote PostgreSQL database (e.g., from Neon)
DATABASE_URI="postgresql://user:password@host:port/dbname"

# Secret key for securing the local API server
SERVER_API_KEY="your_secret_api_key"
```

This ensures that your local application can connect to the remote database and that the API server is properly configured without hardcoding credentials into the source code.


## categories
the program will log the window title that you have in focus every time you change the focussed window.
in the 'categories.dat' file you can name a string as key (left of the ':') and correspond it to a categorie  (right of the ':'). The file will be read from top to bottom. So if you use 'stackoverflow' and correspond that with the categoriey 'programming' than this will be prioritized against the string 'chrome', which might also appear on a visited website.

from 'categories.dat'
```
[CATEGORIES]
spyder: programming
stackoverflow: programming
github: programming
eingabeaufforderung: programming
texstudio: latex
whatsapp: wasted time
mozilla: wasted time (mozilla)
chrome: wasted time (chrome)
mingw64: programming
```

## example results
run 'analytics.py' to get a summary table and a pie chart of your data.
Only the data for today will be shown

```
Review of 15.8.2018
-------------------------------------
     7:50:39 h total
-------------------------------------
     4:53:10 h  programming
     0:57:42 h  documents
     0:14:49 h  mail
     1:09:24 h  wasted time
-------------------------------------
     0:35:34 h not categorized
```

![pie chart example](/images/example_pie_chart.png)

## Website shows results of all data in "data"
open html/index.html and see the beauty of your recorded data
every 60 seconds, the script will automaticall refresh the source code for the html page
![html preview](/images/html_preview.PNG)

## Habit Tracking Calendar
The HTML report includes an interactive 2-week habit calendar with streak counters.

**Important:** To use the habit calendar checkboxes, you must start the habit server first:

### Windows:
```bash
start_habit_server.bat
```

Or manually:
```bash
winrecord_env\Scripts\python.exe habit_server.py
```

### Linux/Mac:
```bash
./start_habit_server.sh
```

Or manually:
```bash
./winrecord_env/Scripts/python.exe habit_server.py
```

The server runs on `http://127.0.0.1:8042/habits` and must be running for checkboxes to persist.

**Configure your habits** in `config.py`:
```python
HABITS = [
    ("Exercise", "#4ade80"),
    ("Read", "#60a5fa"),
    ("Meditate", "#a78bfa"),
]
```

# todo
- adding "projects" as a separate measure next to categories
- read the parent process and not only the window title
- move AI coach briefings/summaries from JSON to database tables for multi-device access
- migrate existing coach_briefings.json into the new DB tables and update analytics to read from DB
- optionally expose digest data via API for multi-computer usage; keep only minimal local caches
