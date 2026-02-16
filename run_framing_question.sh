#!/bin/bash
# Scheduled runner for afternoon framing question post
# Adds random delay to avoid appearing automated

cd /home/jlsteenwyk/Desktop/sm_scipresence

# Load environment variables
set -a
source .env
set +a

# Random delay between 0-45 minutes (0-2700 seconds) for 11:45 AM - 12:30 PM window
DELAY=$((RANDOM % 2700))
echo "$(date): Waiting ${DELAY} seconds before posting framing question..."
sleep $DELAY

# Activate virtual environment and run
source venv/bin/activate
python framing_question.py

echo "$(date): Completed"
