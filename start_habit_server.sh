#!/bin/bash
# Start the habit tracking server
echo "Starting habit tracking server..."
./winrecord_env/Scripts/python.exe habit_server.py &
sleep 2
echo "Habit server started on http://127.0.0.1:8042/habits"
echo ""
echo "You can now open html/index.html and your habit checkboxes will work!"
