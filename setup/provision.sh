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
# Use /opt/homebrew/bin/python3 to match the LaunchAgent Python path.
# Packages installed under /usr/bin/python3 are invisible to Homebrew Python.
PYTHON="/usr/local/share/second-self/python/bin/python3"
if [ ! -x "$PYTHON" ]; then
    PYTHON="/opt/homebrew/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
    PYTHON="/usr/local/bin/python3"
fi
if [ ! -x "$PYTHON" ]; then
    PYTHON="/usr/bin/python3"
    echo "  ⚠️  No bundled or Homebrew Python found, falling back to system Python."
fi
echo "  Using: $PYTHON"

# Install agent-server deps (pyautogui, Pillow, Quartz, browser-use CLI)
echo "  Installing agent-server deps..."
sudo -H -u "$SECOND_USER" "$PYTHON" -m pip install --user --break-system-packages \
    -r "$REPO_DIR/agent-server/requirements.txt" 2>&1 | tail -5 || {
    echo "  ⚠️  agent-server deps install failed."
}

# Install orchestrator deps (anthropic, fastapi, uvicorn, etc.)
echo "  Installing orchestrator deps..."
sudo -H -u "$SECOND_USER" "$PYTHON" -m pip install --user --break-system-packages \
    -r "$REPO_DIR/orchestrator/requirements.txt" 2>&1 | tail -5 || {
    echo "  ⚠️  orchestrator deps install failed."
}
echo ""

# ─── Step 4: Install Chromium for browser-use ───
echo "[4/10] Installing Chromium for browser-use..."
sudo -H -u "$SECOND_USER" bash -c 'cd /tmp && browser-use install' 2>&1 | tail -5 || {
    echo "  ⚠️  Chromium install failed. Try: sudo -H -u $SECOND_USER bash -c 'cd /tmp && browser-use install'"
}
echo ""

# ─── Step 5: Clear quarantine on Vine Server (optional) ───
echo "[5/10] Checking Vine Server..."
if [ -d "/Applications/Vine Server.app" ]; then
    sudo xattr -cr "/Applications/Vine Server.app"
    echo "  Vine Server found, quarantine cleared."
    VINE_AVAILABLE=true
else
    echo "  Vine Server not installed (optional, MJPEG streaming works without it)."
    echo "  To install later: brew install --cask vine-server"
    VINE_AVAILABLE=false
fi
echo ""

# ─── Step 6: Install LaunchAgents ───
echo "[6/10] Installing LaunchAgents..."
LAUNCH_DIR="$SECOND_HOME/Library/LaunchAgents"
sudo mkdir -p "$LAUNCH_DIR"
sudo cp "$REPO_DIR/setup/ai.secondself.agent.plist" "$LAUNCH_DIR/"
sudo cp "$REPO_DIR/setup/ai.secondself.chrome.plist" "$LAUNCH_DIR/"
echo "  Installed: ai.secondself.agent (Agent Server on :8421)"
echo "  Installed: ai.secondself.chrome (Chrome with CDP on :9222)"
if [ "$VINE_AVAILABLE" = true ]; then
    sudo cp "$REPO_DIR/setup/ai.secondself.vine.plist" "$LAUNCH_DIR/"
    echo "  Installed: ai.secondself.vine (Vine VNC on :5901)"
fi
# Note: orchestrator is NOT a LaunchAgent — the SwiftUI app launches it as a subprocess.
sudo chown -R "$SECOND_USER:staff" "$LAUNCH_DIR"
echo ""

# ─── Step 7: Enable Fast User Switching + initial login ───
echo "[7/10] Checking if secondself has a GUI session..."
SECOND_UID=$(id -u "$SECOND_USER")
WS_COUNT=$(ps aux | grep -c "[W]indowServer")

if [ "$WS_COUNT" -lt 2 ]; then
    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  MANUAL STEPS REQUIRED (first time only):           ║"
    echo "  ║                                                      ║"
    echo "  ║  1. Click user icon in menu bar                      ║"
    echo "  ║  2. Switch to 'secondself'                           ║"
    echo "  ║  3. Log in with the password you just set            ║"
    echo "  ║  4. Grant Accessibility to Terminal if prompted       ║"
    echo "  ║  5. Grant Screen Recording (see below)               ║"
    echo "  ║  6. Switch back to your account                      ║"
    echo "  ║                                                      ║"
    echo "  ║  This creates the GUI session. Only needed once.     ║"
    echo "  ╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "  Screen Recording permission is needed for VNC + screenshots."
    echo "  While logged in as secondself:"
    echo "    System Settings > Privacy & Security > Screen Recording"
    echo "    Enable: python3, Vine Server, Terminal"
    echo ""
    read -p "  Press Enter after switching back to continue..."
    echo ""
else
    echo "  GUI session already active."
fi

# Verify Screen Recording permission by testing a screenshot
echo "  Checking Screen Recording permission..."
SCREENSHOT_TEST=$(sudo -u "$SECOND_USER" /opt/homebrew/bin/python3 -c "
import Quartz
ref = Quartz.CGWindowListCreateImage(Quartz.CGRectInfinite, Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID, Quartz.kCGWindowImageDefault)
print('OK' if ref else 'DENIED')
" 2>/dev/null || echo "ERROR")

if echo "$SCREENSHOT_TEST" | grep -q "OK"; then
    echo "    ✅ Screen Recording granted"
else
    echo "    ⚠️  Screen Recording NOT granted for python3"
    echo ""
    echo "    To fix: switch to secondself and run:"
    echo "      open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'"
    echo "    Then enable python3 and Vine Server."
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
if [ "$VINE_AVAILABLE" = true ]; then
    sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.vine.plist" 2>/dev/null || {
        echo "  ⚠️  Vine Server LaunchAgent failed. May need to start manually."
    }
fi
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

# Check Vine Server (optional)
echo "  VNC (Vine Server on :5901):"
if [ "$VINE_AVAILABLE" = true ]; then
    if netstat -an | grep -q "\.5901.*LISTEN"; then
        echo "    ✅ Listening"
    else
        echo "    ⚠️  Not listening (Vine installed but not running)"
        echo "    Check: cat $SECOND_HOME/second-self/vine.err"
    fi
else
    echo "    ⏭  Skipped (Vine Server not installed, MJPEG streaming works without it)"
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

# Check browser-use
echo ""
echo "  browser-use CLI:"
BU_CHECK=$(sudo -H -u "$SECOND_USER" bash -c 'cd /tmp && browser-use doctor' 2>/dev/null || echo "not found")
if echo "$BU_CHECK" | grep -qi "ok\|ready\|chromium\|[0-9]"; then
    echo "    ✅ Installed"
else
    echo "    ❌ Not found or not working"
    echo "    Try: sudo -H -u $SECOND_USER pip install 'browser-use[cli]'"
fi

# Check VNC connectivity (optional)
echo ""
echo "  VNC protocol test:"
if [ "$VINE_AVAILABLE" = true ]; then
    BANNER=$(echo | nc -w 2 localhost 5901 2>&1 | head -1)
    if echo "$BANNER" | grep -q "RFB"; then
        echo "    ✅ VNC responding ($BANNER)"
    else
        echo "    ⚠️  No VNC response"
    fi
else
    echo "    ⏭  Skipped (Vine Server not installed)"
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
echo "  To start the orchestrator (or launch the SecondSelf app, which starts it automatically):"
echo "    cd ~/second-self"
echo "    source .env && export ANTHROPIC_API_KEY TAVILY_API_KEY"
echo "    python3 orchestrator/server.py"
echo ""
echo "  To test the agent:"
echo "    curl -s http://localhost:8421/health"
echo "    bash setup/test-agent.sh"
echo ""
echo "  browser-use: installed for browser automation via CDP"
echo "========================================="
