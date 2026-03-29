#!/bin/bash
# Test the MJPEG stream from secondself's agent-server
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1] Killing old agent-server..."
sudo pkill -9 -f "agent-server/server.py" 2>/dev/null || true
sleep 2

echo "[2] Copying latest code to secondself..."
sudo cp "$REPO_DIR/agent-server/server.py" /Users/secondself/second-self/agent-server/server.py
sudo chown secondself:staff /Users/secondself/second-self/agent-server/server.py

echo "[3] Starting agent-server in secondself's session..."
sudo launchctl asuser 506 /opt/homebrew/bin/python3 /Users/secondself/second-self/agent-server/server.py &
sleep 3

echo "[4] Checking health..."
curl -s --connect-timeout 3 http://localhost:8421/health | head -1
echo ""

echo "[5] Launching MJPEG test viewer..."
cd "$REPO_DIR/test-mjpeg-viewer"
swift run
