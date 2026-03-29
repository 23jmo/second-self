#!/bin/bash
# Setup script for Second Self
# Run this from your PRIMARY user session.
# Some steps require manual GUI interaction (noted with [MANUAL]).

set -e

SECOND_USER="secondself"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "========================================="
echo "  Second Self — Phase 1 Setup"
echo "========================================="
echo ""
echo "Repo directory: $REPO_DIR"
echo ""

# Step 1: Create the second user
echo "--- Step 1: Create second user ---"
if id "$SECOND_USER" &>/dev/null; then
    echo "User '$SECOND_USER' already exists. Skipping."
else
    echo "Creating user '$SECOND_USER'..."
    echo "(You'll be prompted for sudo password, then the new user's password)"
    sudo sysadminctl -addUser "$SECOND_USER" -password -
    echo "User created."
fi
echo ""

# Step 2: Enable Fast User Switching
echo "--- Step 2: Enable Fast User Switching ---"
echo "[MANUAL] Go to: System Settings → Control Center → Fast User Switching"
echo "         Set 'Show in Menu Bar' to ON"
echo ""
read -p "Press Enter when done..."
echo ""

# Step 3: Initial login to secondself
echo "--- Step 3: Log into secondself session ---"
echo "[MANUAL] Click the user icon in the menu bar → switch to '$SECOND_USER'"
echo "         This creates the GUI session and WindowServer process."
echo ""
echo "         While in the secondself session, do these things:"
echo ""
echo "         a) System Settings → General → Sharing → Screen Sharing → ON"
echo "         b) System Settings → Privacy & Security → Accessibility → grant Terminal"
echo "         c) System Settings → Privacy & Security → Screen Recording → grant Terminal"
echo ""
echo "         Then switch back to your primary account."
echo ""
read -p "Press Enter when done with all steps above..."
echo ""

# Step 4: Verify WindowServer
echo "--- Step 4: Verify WindowServer ---"
WS_COUNT=$(ps aux | grep -i "[W]indowServer" | wc -l | tr -d ' ')
echo "WindowServer processes found: $WS_COUNT"
if [ "$WS_COUNT" -ge 2 ]; then
    echo "✅ Both sessions have active WindowServer processes."
else
    echo "⚠️  Only $WS_COUNT WindowServer process found."
    echo "    The background session might be suspended."
    echo "    Try: Install BetterDisplay or plug in a dummy HDMI adapter."
fi
echo ""

# Step 5: Test VNC connection via SSH tunnel
echo "--- Step 5: Test VNC connection ---"
echo "NOTE: vnc://localhost connects to YOUR session (gives 'cannot control own screen')."
echo "      We use an SSH tunnel to reach the secondself background session instead."
echo ""
echo "Starting SSH tunnel (port 5901 → 5900)..."
ssh -NL 5901:localhost:5900 localhost &
SSH_PID=$!
sleep 1
echo "Opening VNC viewer via tunnel..."
echo "(Log in as '$SECOND_USER' when prompted)"
open vnc://localhost:5901 &
echo ""
echo "VERIFY: You should see the secondself desktop (not your desktop)."
echo "VERIFY: Mouse movements are smooth."
echo "VERIFY: Connection stays alive."
echo ""
read -p "Does VNC work? (y/n): " VNC_WORKS
if [ "$VNC_WORKS" != "y" ]; then
    kill $SSH_PID 2>/dev/null
    echo ""
    echo "⚠️  VNC via SSH tunnel didn't work. Trying alternatives:"
    echo ""
    echo "    Option A: Install Vine Server (free VNC server)"
    echo "      brew install --cask vine-server"
    echo "      (configure in secondself session on port 5901)"
    echo ""
    echo "    Option B: Use the MJPEG stream (built into Agent Server)"
    echo "      Once Agent Server is running, open:"
    echo "      http://localhost:8421/view"
    echo ""
    echo "    Option C: Install BetterDisplay (if screen is black/not rendering)"
    echo "      brew install --cask betterdisplay"
    echo ""
    read -p "Continue setup anyway? (y/n): " CONTINUE
    if [ "$CONTINUE" != "y" ]; then
        exit 1
    fi
fi
echo ""

# Step 6: Copy repo to secondself's home
echo "--- Step 6: Copy repo to secondself ---"
SECOND_HOME="/Users/$SECOND_USER"
if [ -d "$SECOND_HOME/second-self" ]; then
    echo "Repo already exists at $SECOND_HOME/second-self. Updating..."
    sudo rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        "$REPO_DIR/" "$SECOND_HOME/second-self/"
else
    echo "Copying repo to $SECOND_HOME/second-self..."
    sudo cp -R "$REPO_DIR" "$SECOND_HOME/second-self"
fi
sudo chown -R "$SECOND_USER:staff" "$SECOND_HOME/second-self"
echo "Done."
echo ""

# Step 7: Install Python dependencies in secondself
echo "--- Step 7: Install Python dependencies ---"
SECOND_UID=$(id -u "$SECOND_USER")
sudo launchctl asuser "$SECOND_UID" /usr/bin/python3 -m pip install --user \
    -r "$SECOND_HOME/second-self/agent-server/requirements.txt" 2>&1 || {
    echo "⚠️  pip install via launchctl failed."
    echo "    You may need to install dependencies manually in the secondself session."
    echo "    Switch to secondself and run:"
    echo "    cd ~/second-self/agent-server && python3 -m pip install -r requirements.txt"
}
echo ""

# Step 8: Install LaunchAgent
echo "--- Step 8: Install Agent Server LaunchAgent ---"
LAUNCH_AGENTS_DIR="$SECOND_HOME/Library/LaunchAgents"
sudo mkdir -p "$LAUNCH_AGENTS_DIR"
sudo cp "$REPO_DIR/setup/ai.secondself.agent.plist" "$LAUNCH_AGENTS_DIR/"
sudo chown "$SECOND_USER:staff" "$LAUNCH_AGENTS_DIR/ai.secondself.agent.plist"

echo "Loading LaunchAgent..."
sudo launchctl bootstrap "gui/$SECOND_UID" \
    "$LAUNCH_AGENTS_DIR/ai.secondself.agent.plist" 2>&1 || {
    echo "⚠️  LaunchAgent load failed. You may need to:"
    echo "    1. Switch to secondself session"
    echo "    2. Run: launchctl load ~/Library/LaunchAgents/ai.secondself.agent.plist"
}
echo ""

# Step 9: Verify Agent Server
echo "--- Step 9: Verify Agent Server ---"
sleep 2
echo "Checking Agent Server health..."
HEALTH=$(curl -s http://localhost:8421/health 2>/dev/null || echo '{"error":"unreachable"}')
echo "Response: $HEALTH"
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    echo "✅ Agent Server is running!"
else
    echo "⚠️  Agent Server not responding."
    echo "    Check logs: cat $SECOND_HOME/second-self/agent-server/agent.log"
    echo "    Check errors: cat $SECOND_HOME/second-self/agent-server/agent.err"
fi
echo ""

# Step 10: Test remote control
echo "--- Step 10: Test remote control ---"
echo "Sending test command to open Safari..."
RESULT=$(curl -s -X POST http://localhost:8421/tool/open_app \
    -H "Content-Type: application/json" \
    -d '{"name":"Safari"}' 2>/dev/null || echo '{"error":"failed"}')
echo "Response: $RESULT"
echo ""
echo "VERIFY in VNC: Did Safari open in the secondself session?"
read -p "(y/n): " SAFARI_WORKS
echo ""

if [ "$SAFARI_WORKS" = "y" ]; then
    echo "========================================="
    echo "  ✅ Phase 1 COMPLETE"
    echo "========================================="
    echo ""
    echo "  VNC:          working"
    echo "  Agent Server: running on :8421"
    echo "  Remote ctrl:  verified"
    echo ""
    echo "  Next: Start the orchestrator (or launch SecondSelf app)"
    echo "  export ANTHROPIC_API_KEY=your_key"
    echo "  export TAVILY_API_KEY=your_key"
    echo "  python3 orchestrator/server.py"
    echo ""
else
    echo "⚠️  Remote control not working."
    echo "    Check TCC permissions in secondself session."
    echo "    Accessibility and Screen Recording must be granted to Terminal."
fi
