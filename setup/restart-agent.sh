#!/bin/bash
# Restart the Agent Server on secondself from your primary account.
# Usage: ./setup/restart-agent.sh

SECOND_USER="secondself"
SECOND_HOME="/Users/$SECOND_USER"

# Copy latest code
sudo cp ~/second-self/agent-server/server.py "$SECOND_HOME/second-self/agent-server/server.py"
sudo chown "$SECOND_USER:staff" "$SECOND_HOME/second-self/agent-server/server.py"

# Kill old process
sudo kill $(sudo lsof -ti :8421) 2>/dev/null
sleep 1

# Restart in secondself's GUI session via SSH
# Falls back to launchctl if SSH fails
ssh -o StrictHostKeyChecking=no "$SECOND_USER@localhost" \
    "cd ~/second-self/agent-server && nohup python3 server.py > agent.log 2>&1 &" 2>/dev/null || {
    echo "SSH failed. Switch to secondself and run:"
    echo "  cd ~/second-self/agent-server && nohup python3 server.py > agent.log 2>&1 &"
    exit 1
}

sleep 2
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null)
if echo "$HEALTH" | grep -q '"status"'; then
    echo "✅ Agent Server restarted — $HEALTH"
else
    echo "❌ Agent Server not responding. May need to start from secondself's Terminal."
fi
