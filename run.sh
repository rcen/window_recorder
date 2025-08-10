#!/bin/bash
set -e

# Function to clean up background processes on exit
cleanup() {
    echo "Stopping background processes..."
    # Kill the process group of the script, which includes all child processes
    if [ -n "$tracker_pid" ]; then
        kill $tracker_pid 2>/dev/null
    fi
    exit 0
}

# Trap script exit signals and call the cleanup function
trap cleanup SIGINT SIGTERM

# Activate virtual environment
source winrecord_env/bin/activate

# Install dependencies if needed
if [[ " $@ " =~ " --new " ]]; then
    pip install -r requirements.txt
fi

# Start the activity tracker in the background
echo "Starting window recorder in the background..."
(
  while true; do
    python3 script.py
    echo "Tracker script stopped. Restarting in 5 seconds..."
    sleep 5
  done
) &
tracker_pid=$!

echo "Tracker started with PID: $tracker_pid"
echo "Starting automatic report generator in the foreground..."

# Start the report generator in the foreground
./update_report.sh
