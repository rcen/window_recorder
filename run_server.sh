#!/bin/bash

# Activate virtual environment if it exists
if [ -f "winrecord_env/bin/activate" ]; then
    source winrecord_env/bin/activate
fi

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start the Uvicorn server
echo "Starting server..."
uvicorn api_server:app --host 0.0.0.0 --port ${PORT:-8000}
