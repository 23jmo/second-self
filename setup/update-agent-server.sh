#!/bin/bash
# Updates the agent-server code in secondself's session and restarts it.
# Run from primary user terminal.
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECOND_HOME="/Users/secondself"
SECOND_USER="secondself"

echo "[update] Copying agent-server code to secondself..."
sudo cp "$REPO_DIR/agent-server/server.py" "$SECOND_HOME/second-self/agent-server/server.py"
sudo chown "$SECOND_USER:staff" "$SECOND_HOME/second-self/agent-server/server.py"

echo "[update] Restarting agent-server in secondself's session..."
SECOND_UID=$(id -u "$SECOND_USER")
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.agent" 2>/dev/null || true
sleep 1
sudo launchctl bootstrap "gui/$SECOND_UID" "$SECOND_HOME/Library/LaunchAgents/ai.secondself.agent.plist"

echo "[update] Waiting for agent-server to start..."
sleep 3

HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null || echo "unreachable")
if echo "$HEALTH" | grep -q '"status"'; then
    echo "[update] Agent-server is running on :8421"
else
    echo "[update] WARNING: Agent-server not responding. Check: cat $SECOND_HOME/second-self/agent-server/agent.err"
fi

echo "[update] Done. Run 'cd SecondSelf && swift build && swift run' to launch the app."
