#!/bin/bash
# Second Self — One-shot provisioning script
# Run from your PRIMARY admin account. No switching required.
# Usage: ./setup/provision.sh

set -e

SECOND_USER="secondself"
SECOND_HOME="/Users/$SECOND_USER"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "========================================="
echo "  Second Self — Provisioning"
echo "  Run from: $(whoami) (primary admin)"
echo "========================================="
echo ""

# ─── Step 1: Create user if needed ───
echo "[1/10] Checking user account..."
if id "$SECOND_USER" &>/dev/null; then
    echo "  User '$SECOND_USER' already exists."
else
    echo "  Creating user '$SECOND_USER'..."
    sudo sysadminctl -addUser "$SECOND_USER" -password -
fi

# Make sure they're admin (needed for installs)
sudo dscl . -append /Groups/admin GroupMembership "$SECOND_USER" 2>/dev/null || true
echo "  Admin privileges granted."
echo ""

# ─── Step 2: Copy repo ───
echo "[2/10] Copying repo to $SECOND_HOME..."
if [ -d "$SECOND_HOME/second-self" ]; then
    sudo rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
        "$REPO_DIR/" "$SECOND_HOME/second-self/"
else
    sudo cp -R "$REPO_DIR" "$SECOND_HOME/second-self"
fi
sudo chown -R "$SECOND_USER:staff" "$SECOND_HOME/second-self"
echo "  Done."
echo ""

# ─── Step 3: Install Python dependencies ───
echo "[3/10] Installing Python dependencies..."
sudo -u "$SECOND_USER" /usr/bin/python3 -m pip install --user --break-system-packages \
    pyautogui Pillow 2>&1 | tail -3 || {
    echo "  ⚠️  pip install failed. May need manual install in secondself session."
}
echo ""

# ─── Step 4: Install agent-browser ───
echo "[4/10] Installing browser-use CLI..."
sudo -H -u "$SECOND_USER" /usr/bin/python3 -m pip install --user --break-system-packages \
    "browser-use[cli]" 2>&1 | tail -3 || {
    echo "  ⚠️  browser-use install failed."
}

echo "  Installing Chromium for browser-use..."
sudo -H -u "$SECOND_USER" bash -c 'cd /tmp && browser-use install' 2>&1 | tail -5 || {
    echo "  ⚠️  Chromium install failed. Try: sudo -H -u $SECOND_USER bash -c 'cd /tmp && browser-use install'"
}
echo ""

# ─── Step 5: Clear quarantine on Vine Server ───
echo "[5/10] Clearing quarantine on Vine Server..."
if [ -d "/Applications/Vine Server.app" ]; then
    sudo xattr -cr "/Applications/Vine Server.app"
    echo "  Done."
else
    echo "  ⚠️  Vine Server not found. Install it first:"
    echo "     brew install --cask vine-server"
    echo "     Then re-run this script."
    exit 1
fi
echo ""

# ─── Step 6: Install LaunchAgents ───
echo "[6/10] Installing LaunchAgents..."
LAUNCH_DIR="$SECOND_HOME/Library/LaunchAgents"
sudo mkdir -p "$LAUNCH_DIR"
sudo cp "$REPO_DIR/setup/ai.secondself.agent.plist" "$LAUNCH_DIR/"
sudo cp "$REPO_DIR/setup/ai.secondself.vine.plist" "$LAUNCH_DIR/"
sudo cp "$REPO_DIR/setup/ai.secondself.chrome.plist" "$LAUNCH_DIR/"
sudo chown -R "$SECOND_USER:staff" "$LAUNCH_DIR"
echo "  Installed: ai.secondself.agent (Agent Server on :8421)"
echo "  Installed: ai.secondself.vine (Vine VNC on :5901)"
echo "  Installed: ai.secondself.chrome (Chrome with CDP on :9222)"
echo ""

# ─── Step 7: Enable Fast User Switching + initial login ───
echo "[7/10] Checking if secondself has a GUI session..."
SECOND_UID=$(id -u "$SECOND_USER")
WS_COUNT=$(ps aux | grep -c "[W]indowServer")

if [ "$WS_COUNT" -lt 2 ]; then
    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  ONE MANUAL STEP REQUIRED (first time only):        ║"
    echo "  ║                                                      ║"
    echo "  ║  1. Click user icon in menu bar                      ║"
    echo "  ║  2. Switch to 'secondself'                           ║"
    echo "  ║  3. Log in with the password you just set            ║"
    echo "  ║  4. Grant Accessibility to Terminal if prompted       ║"
    echo "  ║  5. Switch back to your account                      ║"
    echo "  ║                                                      ║"
    echo "  ║  This creates the GUI session. Only needed once.     ║"
    echo "  ╚══════════════════════════════════════════════════════╝"
    echo ""
    read -p "  Press Enter after switching back to continue..."
    echo ""
fi

# ─── Step 8: Start services ───
echo "[8/10] Starting services in secondself's session..."
SECOND_UID=$(id -u "$SECOND_USER")

# Stop any existing instances
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.agent" 2>/dev/null || true
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.vine" 2>/dev/null || true
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.chrome" 2>/dev/null || true
sudo -u "$SECOND_USER" pkill -f "Google Chrome" 2>/dev/null || true
sleep 1

# Start fresh
sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.vine.plist" 2>/dev/null || {
    echo "  ⚠️  Vine Server LaunchAgent failed. May need to start manually."
}
sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.chrome.plist" 2>/dev/null || {
    echo "  ⚠️  Chrome LaunchAgent failed. May need to start manually."
}
sleep 2
sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.agent.plist" 2>/dev/null || {
    echo "  ⚠️  Agent Server LaunchAgent failed. May need to start manually."
}
echo "  Waiting for services to start..."
sleep 3
echo ""

# ─── Step 9: Verify everything ───
echo "[9/10] Verifying..."
echo ""

# Check Vine Server
echo "  VNC (Vine Server on :5901):"
if netstat -an | grep -q "\.5901.*LISTEN"; then
    echo "    ✅ Listening"
else
    echo "    ❌ Not listening"
    echo "    Check: cat $SECOND_HOME/second-self/vine.err"
fi

# Check Agent Server
echo ""
echo "  Agent Server on :8421:"
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null || echo "unreachable")
if echo "$HEALTH" | grep -q '"status"'; then
    echo "    ✅ Running — $HEALTH"
else
    echo "    ❌ Not responding"
    echo "    Check: cat $SECOND_HOME/second-self/agent-server/agent.err"
fi

# Check agent-browser
echo ""
echo "  agent-browser:"
AB_VERSION=$(sudo -u "$SECOND_USER" agent-browser --version 2>/dev/null || echo "not found")
if echo "$AB_VERSION" | grep -qi "agent-browser\|version\|[0-9]"; then
    echo "    ✅ Installed — $AB_VERSION"
else
    echo "    ❌ Not found or not working"
    echo "    Try: sudo -H -u $SECOND_USER npm install -g agent-browser"
fi

# Check VNC connectivity
echo ""
echo "  VNC protocol test:"
BANNER=$(echo | nc -w 2 localhost 5901 2>&1 | head -1)
if echo "$BANNER" | grep -q "RFB"; then
    echo "    ✅ VNC responding ($BANNER)"
else
    echo "    ❌ No VNC response"
fi

# Check WindowServer
echo ""
echo "  WindowServer sessions:"
WS_COUNT=$(ps aux | grep -c "[W]indowServer")
echo "    $WS_COUNT process(es) — $([ "$WS_COUNT" -ge 2 ] && echo '✅ both sessions active' || echo '⚠️  secondself may not have a GUI session')"

echo ""
echo "========================================="
echo "  Provisioning complete!"
echo ""
echo "  To view secondself's desktop:"
echo "    open -a TigerVNC --args localhost:5901"
echo ""
echo "  To start the orchestrator:"
echo "    cd ~/second-self"
echo "    source .env && export DEDALUS_API_KEY DEDALUS_API_URL DEDALUS_MODEL TAVILY_API_KEY"
echo "    python3 orchestrator/server.py"
echo ""
echo "  To test the agent:"
echo "    curl -s http://localhost:8421/health"
echo "    bash setup/test-agent.sh"
echo ""
echo "  agent-browser: installed for browser automation"
echo "========================================="
