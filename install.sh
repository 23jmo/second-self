#!/bin/bash
# Second Self — Build, install, and set up everything.
# Usage: ./install.sh
#   First time: provisions secondself user + installs app
#   Updates:    rebuilds app + syncs agent-server code + restarts services

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Second Self"
APP_DIR="/Applications/$APP_NAME.app"
SECOND_USER="secondself"
SECOND_HOME="/Users/$SECOND_USER"

echo "========================================="
echo "  Second Self — Install"
echo "========================================="
echo ""

# ─── Step 1: First-time provisioning (if needed) ───
if id "$SECOND_USER" &>/dev/null; then
    echo "[1/5] secondself user exists ✓"
else
    echo "[1/5] First-time setup — running provisioning..."
    echo "  This creates the secondself user and installs dependencies."
    echo ""
    bash "$REPO_DIR/setup/provision.sh"
    echo ""
fi

# ─── Step 2: Sync latest code to secondself ───
echo "[2/5] Syncing code to secondself..."
if [ -d "$SECOND_HOME/second-self" ]; then
    sudo rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='.env' --exclude='.build' --exclude='build' \
        "$REPO_DIR/" "$SECOND_HOME/second-self/"
else
    sudo cp -R "$REPO_DIR" "$SECOND_HOME/second-self"
fi
sudo chown -R "$SECOND_USER:staff" "$SECOND_HOME/second-self"

# Copy .env if it exists (agent-server needs API keys)
if [ -f "$REPO_DIR/.env" ]; then
    sudo cp "$REPO_DIR/.env" "$SECOND_HOME/second-self/.env"
    sudo chown "$SECOND_USER:staff" "$SECOND_HOME/second-self/.env"
fi
echo "  Done ✓"
echo ""

# ─── Step 3: Restart agent-server ───
echo "[3/5] Restarting agent-server..."
SECOND_UID=$(id -u "$SECOND_USER")
LAUNCH_DIR="$SECOND_HOME/Library/LaunchAgents"

# Ensure LaunchAgents are installed
sudo mkdir -p "$LAUNCH_DIR"
sudo cp "$REPO_DIR/setup/ai.secondself.agent.plist" "$LAUNCH_DIR/"
sudo cp "$REPO_DIR/setup/ai.secondself.chrome.plist" "$LAUNCH_DIR/"
if [ -d "/Applications/Vine Server.app" ]; then
    sudo cp "$REPO_DIR/setup/ai.secondself.vine.plist" "$LAUNCH_DIR/" 2>/dev/null || true
fi
sudo chown -R "$SECOND_USER:staff" "$LAUNCH_DIR"

# Restart services
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.agent" 2>/dev/null || true
sudo launchctl bootout "gui/$SECOND_UID/ai.secondself.chrome" 2>/dev/null || true
sleep 1
sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.chrome.plist" 2>/dev/null || true
sleep 2
sudo launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.agent.plist" 2>/dev/null || true
sleep 2

# Verify agent-server
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q '"status"'; then
    echo "  Agent-server running ✓"
else
    echo "  ⚠️  Agent-server not responding (may need Screen Recording permission)"
fi
echo ""

# ─── Step 4: Build the app ───
echo "[4/5] Building $APP_NAME.app..."
cd "$REPO_DIR/SecondSelf"
swift build -c release 2>&1 | tail -3

BINARY=$(swift build -c release --show-bin-path)/SecondSelf
if [ ! -f "$BINARY" ]; then
    echo "❌ Build failed"
    exit 1
fi
cd "$REPO_DIR"

# Assemble .app bundle
STAGING="$REPO_DIR/build/$APP_NAME.app"
rm -rf "$STAGING"
mkdir -p "$STAGING/Contents/MacOS" "$STAGING/Contents/Resources"

cp "$BINARY" "$STAGING/Contents/MacOS/SecondSelf"
cp SecondSelf/Info.plist "$STAGING/Contents/Info.plist"
echo -n "APPL????" > "$STAGING/Contents/PkgInfo"

# Bundle resources (xcassets processed by swift build)
BUNDLE_RESOURCE=$(find SecondSelf/.build/release -name 'SecondSelf_SecondSelf.bundle' 2>/dev/null | head -1)
if [ -n "$BUNDLE_RESOURCE" ] && [ -d "$BUNDLE_RESOURCE" ]; then
    cp -R "$BUNDLE_RESOURCE" "$STAGING/Contents/Resources/SecondSelf_SecondSelf.bundle"
fi

echo "  Built ✓ ($(du -sh "$STAGING" | cut -f1))"
echo ""

# ─── Step 5: Install to /Applications ───
echo "[5/5] Installing to /Applications..."

# Kill running instance
pkill -f "SecondSelf" 2>/dev/null || true
sleep 1

# Install
rm -rf "$APP_DIR"
cp -R "$STAGING" "$APP_DIR"
xattr -cr "$APP_DIR"

echo "  Installed ✓"
echo ""

echo "========================================="
echo "  Second Self installed!"
echo ""
echo "  Launch:  open '/Applications/Second Self.app'"
echo ""
echo "  What happens on launch:"
echo "    - Kills any stale orchestrators"
echo "    - Clears agent browser session"
echo "    - Starts auth server + orchestrator"
echo "    - Notch UI appears"
echo ""
echo "  Hotkey:  Cmd+Shift+T (toggle panel)"
echo "  Escape:  collapse panel"
echo "========================================="
