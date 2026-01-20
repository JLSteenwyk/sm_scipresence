#!/bin/bash
# Scheduled runner for bioRxiv to Bluesky poster
# Adds random delay to avoid appearing automated

cd /home/jlsteenwyk/Desktop/bluesky_science

# Random delay between 0-20 minutes (0-1200 seconds)
DELAY=$((RANDOM % 1200))
echo "$(date): Waiting ${DELAY} seconds before posting..."
sleep $DELAY

# Activate virtual environment and run
source venv/bin/activate
python main.py

echo "$(date): Completed"
