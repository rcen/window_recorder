#!/bin/bash
# Start the habit tracking and dashboard server
cd "$(dirname "$0")"
echo "Starting habit tracking server..."
./winrecord_env/bin/python habit_server.py &
sleep 2
echo "Habit server started on http://127.0.0.1:8042/"
echo ""
echo "Open http://127.0.0.1:8042/ in your browser to view the interactive dashboard!"
