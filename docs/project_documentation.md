---

## Project Documentation: The Window Recorder

### 1. Project Purpose & High-Level Overview

The **Window Recorder** is a personal analytics tool designed to track your computer usage. Its primary goal is to automatically log the title of the active window on your screen and categorize it, helping you understand how you spend your time.

It started as a simple local script but has evolved into a more robust **client-server application**. This means it has two main parts:

1.  **The Client:** A Python script that runs on your local computer(s) to record activity.
2.  **The Server:** A remote application that receives and stores the data from any client, allowing you to centralize logs from multiple machines.

### 2. System Architecture

The project follows a classic client-server architecture.



*   **Client (Your Computer):**
    *   Runs the main `script.py`.
    *   Its only job is to detect the active window, time how long it's active, and send this information to the server.
    *   It reads a `config.dat` file to get the server URL and the secret API key needed to authenticate.
    *   If it can't reach the server, it saves the data locally to a temporary file to be sent later.

*   **API Server (Hosted on Render.com):**
    *   A Python application built using the **FastAPI** framework.
    *   Its job is to listen for incoming data from clients.
    *   It exposes several **endpoints** (like URLs) that the client can talk to, such as `/log` to save new data and `/health` to check its status.
    *   It validates the client's API key to ensure the data is from a trusted source.
    *   It connects to a central database to store and retrieve activity logs.

*   **Database (PostgreSQL on Render.com):**
    *   The central, long-term storage for all your activity data.
    *   Using a database (instead of a simple file) allows for powerful querying, like "show me all my 'Work' activities for last Tuesday."
    *   The server uses a library called **SQLAlchemy** to talk to the database. SQLAlchemy acts as a translator, turning Python objects into database commands.

### 3. Key Files and Their Roles

Here are the most important files in the repository and what they do:

| File | Purpose |
| :--- | :--- |
| `script.py` | **The Client.** This is the script you run on your computer to track your activity. It's the heart of the data collection process. |
| `api_server.py` | **The Server.** This defines the entire remote API using the FastAPI framework. It handles incoming requests, validates them, and interacts with the database. |
| `database.py` | **Database Schema.** This file defines the structure of your data tables (e.g., the `activities` table) using SQLAlchemy's Object-Relational Mapping (ORM). The ORM is a convenience that lets you work with Python classes instead of writing raw SQL. |
| `config.py` | A helper script that reads settings from `config.dat`. This separates your configuration (like API keys and timezone) from your application code, which is a very important best practice. |
| `config.dat` | **(Not in Git)** A local configuration file where you store your secret API key, server URL, and other settings. It's listed in `.gitignore` so you never accidentally commit your secrets. |
| `run.sh` | A simple shell script to make it easier to run the client (`script.py`). |
| `run_server.sh` | A shell script used by the remote host (Render.com) to start the API server. |
| `analytics.py` | A utility script for performing data analysis and generating charts from the collected data. |
| `show_remote_db.py`| A simple script to fetch and display all records from the remote database. Useful for debugging. |

### 4. Data Flow: The Journey of a Single Log

To understand how it all works together, let's follow a single piece of data from creation to storage.

1.  **Detection (Client):**
    *   You are working in a window with the title "Project Report - Excel".
    *   `script.py`, running in the background, detects this is the active window. It records the start time.

2.  **Activity Switch (Client):**
    *   You switch to a web browser with the title "Google.com".
    *   `script.py` notices the window title has changed. It calculates the total duration you spent on "Project Report - Excel".

3.  **Data Packaging (Client):**
    *   The script bundles the information into a structured format (a Python dictionary, which becomes JSON):
        ```json
        {
          "timestamp": 1678886400.0,
          "category": "Work",
          "duration": 120, // seconds
          "window_title": "Project Report - Excel",
          "source": "Work-Laptop"
        }
        ```

4.  **Transmission (Client → Server):**
    *   The client sends this JSON data in an **HTTP POST request** to the server's `/log` endpoint: `https://window-recorder-api.onrender.com/log`.
    *   It includes the secret `API_KEY` in the request headers for authentication.

5.  **Receipt and Validation (Server):**
    *   `api_server.py` receives the request at the `create_activity` function.
    *   It first checks if the provided `API_KEY` is valid. If not, it rejects the request.

6.  **Storage (Server → Database):**
    *   The server uses SQLAlchemy to create a new `Activity` object from the JSON data.
    *   SQLAlchemy translates this object into an `INSERT` SQL command.
    *   The new record is saved as a new row in the `activities` table in the PostgreSQL database. The process is complete.

### 5. Algorithm Flow (The `script.py` Main Loop)

The core logic of the client is a continuous loop that looks like this:

1.  **Start Loop.**
2.  Get the title of the currently active window.
3.  **Is this a new window?**
    *   **YES:**
        *   The previous activity has just ended. Record its end time and calculate the duration.
        *   Send the completed activity log to the server (or save it locally if the server is down).
        *   A new activity has just begun. Store its title and start time.
    *   **NO (Same window as before):**
        *   Do nothing. The user is still on the same task.
4.  **Wait** for a few seconds.
5.  **Go back to Step 1.**

This simple but effective loop ensures that time is accurately logged and attributed to the correct window title.

### 6. How the Project Evolved

Based on the files in the repository, we can infer the project's history:

*   **Phase 1: Local CSV File.** The project likely started as a very simple script that logged all activity to a single `activities.csv` file. This is fast to build but becomes slow and difficult to query as the file grows. The existence of `migrate_csv_to_db.py` strongly suggests this was the starting point.

*   **Phase 2: Local Database.** To solve the problems of a giant CSV, the project was upgraded to use a local SQLite database (`activity.db`). This allows for much faster and more powerful data queries using SQL.

*   **Phase 3: Client-Server Architecture.** To enable logging from multiple computers and centralize the data, the project was split into the client (`script.py`) and the `api_server.py`. This is the most significant evolution, turning a local tool into a distributed application. The `source` column was likely added to the database during this phase to track which computer sent which log. The server was then deployed to a cloud provider (Render.com) to be accessible from anywhere.
