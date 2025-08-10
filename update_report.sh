#!/bin/bash
set -e

# Activate virtual environment
source winrecord_env/bin/activate

# Loop indefinitely to regenerate the report
while true; do
    echo "[$(date +'%T')] Regenerating report..."

    # Clear old images to ensure a fresh report
    rm -f figs/pie/*.png
    rm -f figs/timeline/*.png

    # Run the analytics script, redirecting output to a log file for debugging
    python3 analytics.py > reporter.log 2>&1

    echo "[$(date +'%T')] Report update complete. Waiting 120 seconds..."
    sleep 120
done
