#!/bin/bash
# Starts the agent-server in secondself's GUI session.
# Run in its own terminal so you can see the logs.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1] Killing old agent-server..."
sudo pkill -9 -f "agent-server/server.py" 2>/dev/null || true
sleep 2

echo "[2] Copying latest code to secondself..."
sudo cp "$REPO_DIR/agent-server/server.py" /Users/secondself/second-self/agent-server/server.py
sudo chown secondself:staff /Users/secondself/second-self/agent-server/server.py

echo "[3] Starting agent-server in secondself's session..."
echo "    (logs will appear below)"
echo ""
sudo launchctl asuser 506 /opt/homebrew/bin/python3 /Users/secondself/second-self/agent-server/server.py
