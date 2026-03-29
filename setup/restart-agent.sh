#!/bin/bash
# Restart the Agent Server on secondself from your primary account.
# Usage: ./setup/restart-agent.sh

SECOND_USER="secondself"
SECOND_HOME="/Users/$SECOND_USER"
LAUNCH_DIR="$SECOND_HOME/Library/LaunchAgents"

# Copy latest code
sudo cp ~/second-self/agent-server/server.py "$SECOND_HOME/second-self/agent-server/server.py"
sudo chown "$SECOND_USER:staff" "$SECOND_HOME/second-self/agent-server/server.py"

# Restart via launchctl (more reliable than SSH)
SECOND_UID=$(id -u "$SECOND_USER")
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.agent" 2>/dev/null || true
sleep 1
sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.agent.plist"

sleep 2
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null)
if echo "$HEALTH" | grep -q '"status"'; then
    echo "✅ Agent Server restarted — $HEALTH"
else
    echo "❌ Agent Server not responding. Check: cat $SECOND_HOME/second-self/agent-server/agent.err"
fi
