#!/bin/bash
# Launches the MJPEG test viewer. Run AFTER start-agent-server.sh in another terminal.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Checking agent-server..."
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null || echo "unreachable")
if echo "$HEALTH" | grep -q '"status"'; then
    echo "Agent-server is running. Launching viewer..."
else
    echo "Agent-server not running! Start it first: bash start-agent-server.sh"
    exit 1
fi

cd "$REPO_DIR/test-mjpeg-viewer"
swift run
