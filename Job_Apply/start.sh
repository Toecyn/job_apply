#!/bin/bash
cd /Users/olusobayo/job-apply
source venv/bin/activate

# Kill anything on port 5001
lsof -ti:5001 | xargs kill -9 2>/dev/null
sleep 1

# Start scheduler in background
python3 scheduler.py &
SCHEDULER_PID=$!
echo "Scheduler started (PID: $SCHEDULER_PID)"

# Start dashboard
echo "Dashboard starting at http://127.0.0.1:5001"
python3 app.py
