#!/bin/bash
set -e

# Check for virtual environment
if [ ! -d "winrecord_env" ]; then
    echo "Creating virtual environment..."
    python3 -m venv winrecord_env
fi

# Activate virtual environment
source winrecord_env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run analytics
python3 analytics.py

# Run the main script in a loop
while true; do
    python3 script.py
    echo "Script stopped. Restarting in 5 seconds..."
    sleep 5
done
