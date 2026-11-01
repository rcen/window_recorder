#!/bin/bash
#
# This script clears the cache and generated files for the window_recorder project.

echo "Clearing cached images..."
# Use find to gracefully handle cases where the directory is empty
find figs/pie -type f -name "*.png" -delete
find figs/timeline -type f -name "*.png" -delete

echo "Clearing generated HTML report..."
rm -f html/index.html

echo "Clearing Python bytecode cache..."
find . -type d -name "__pycache__" -exec rm -rf {} +

# Clear the analysis cache in analytics.py if needed (optional, as it's in-memory)
# No, the cache in analytics.py is in-memory, so it's cleared on each run.

echo "Cache cleared successfully."
