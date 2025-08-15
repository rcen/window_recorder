#!/bin/bash

# Activate virtual environment
source winrecord_env/bin/activate

# Function to be called on exit
cleanup() {
    echo -e "\nCaught Ctrl-C. Stopping the Python script..."
    if [ -n "$python_pid" ]; then
        kill $python_pid
    fi
    exit 0
}

# Set the trap
trap cleanup SIGINT SIGTERM

echo "Synchronizing databases..."
python3 sync_databases.py

echo "Starting the window recorder script..."
echo "Press Ctrl-C to stop."

# Run the python script in the background
python3 script.py &
python_pid=$!

# Wait for the python script to exit
wait $python_pid

