#!/bin/bash
# Scheduled runner for Sunday weekly roundup
# Adds random delay to avoid appearing automated

cd /home/jlsteenwyk/Desktop/bluesky_science

# Load environment variables
set -a
source .env
set +a

# Random delay between 0-30 minutes (0-1800 seconds)
DELAY=$((RANDOM % 1800))
echo "$(date): Waiting ${DELAY} seconds before posting weekly roundup..."
sleep $DELAY

# Activate virtual environment and run
source venv/bin/activate
python weekly_roundup.py

echo "$(date): Completed weekly roundup"
