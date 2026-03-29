#!/bin/bash
# Build Second Self as a macOS .pkg installer
# Usage: ./build-pkg.sh
#   Produces: build/SecondSelf.pkg

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$REPO_DIR/build"
PKG_ROOT="$BUILD_DIR/pkg-root"
SCRIPTS_DIR="$BUILD_DIR/pkg-scripts"
APP_NAME="Second Self"
PKG_ID="com.secondself.app"
VERSION="0.1.0"

echo "==> Building SecondSelf (release)..."
cd "$REPO_DIR/SecondSelf"
swift build -c release 2>&1 | tail -3

BINARY=$(swift build -c release --show-bin-path)/SecondSelf
if [ ! -f "$BINARY" ]; then
    echo "❌ Build failed"
    exit 1
fi
cd "$REPO_DIR"

echo "==> Assembling .app bundle..."
rm -rf "$PKG_ROOT" "$SCRIPTS_DIR" "$BUILD_DIR/SecondSelf.pkg"
mkdir -p "$PKG_ROOT/Applications/$APP_NAME.app/Contents/MacOS"
mkdir -p "$PKG_ROOT/Applications/$APP_NAME.app/Contents/Resources"

# Binary
cp "$BINARY" "$PKG_ROOT/Applications/$APP_NAME.app/Contents/MacOS/SecondSelf"

# Info.plist + PkgInfo
cp SecondSelf/Info.plist "$PKG_ROOT/Applications/$APP_NAME.app/Contents/Info.plist"
echo -n "APPL????" > "$PKG_ROOT/Applications/$APP_NAME.app/Contents/PkgInfo"

# Bundle resources (xcassets)
BUNDLE_RESOURCE=$(find SecondSelf/.build/release -name 'SecondSelf_SecondSelf.bundle' 2>/dev/null | head -1)
if [ -n "$BUNDLE_RESOURCE" ] && [ -d "$BUNDLE_RESOURCE" ]; then
    cp -R "$BUNDLE_RESOURCE" "$PKG_ROOT/Applications/$APP_NAME.app/Contents/Resources/"
fi

echo "==> Bundling repo files..."
REPO_DEST="$PKG_ROOT/usr/local/share/second-self"
mkdir -p "$REPO_DEST"

# Copy the files the app needs at runtime
for dir in orchestrator agent-server src setup cookie_sync; do
    if [ -d "$REPO_DIR/$dir" ]; then
        rsync -a --exclude='__pycache__' --exclude='*.pyc' \
            "$REPO_DIR/$dir/" "$REPO_DEST/$dir/"
    fi
done

# Copy config files (bundle real .env so demo works out of the box)
[ -f "$REPO_DIR/.env" ] && cp "$REPO_DIR/.env" "$REPO_DEST/.env"
[ -f "$REPO_DIR/.env.example" ] && cp "$REPO_DIR/.env.example" "$REPO_DEST/.env.example"
[ -f "$REPO_DIR/requirements.txt" ] && cp "$REPO_DIR/requirements.txt" "$REPO_DEST/"

# Copy setup scripts
chmod +x "$REPO_DEST/setup/"*.sh 2>/dev/null || true

echo "==> Creating postinstall script..."
mkdir -p "$SCRIPTS_DIR"
cat > "$SCRIPTS_DIR/postinstall" << 'POSTINSTALL'
#!/bin/bash
# Second Self — Post-install setup
# Runs as root after .pkg installs files.

INSTALL_DIR="/usr/local/share/second-self"
REAL_USER=$(stat -f '%Su' /dev/console)
REAL_HOME=$(dscl . -read /Users/"$REAL_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
SECOND_USER="secondself"

echo "[SecondSelf] Post-install starting for user: $REAL_USER"

# Symlink repo to ~/second-self for easy access
if [ -n "$REAL_HOME" ] && [ ! -e "$REAL_HOME/second-self" ]; then
    ln -s "$INSTALL_DIR" "$REAL_HOME/second-self"
    chown -h "$REAL_USER:staff" "$REAL_HOME/second-self"
    echo "[SecondSelf] Symlinked ~/second-self -> $INSTALL_DIR"
fi

# .env is bundled with real keys for demo — no setup needed
echo "[SecondSelf] API keys bundled for demo ✓"

# Clear Gatekeeper on the app
xattr -cr "/Applications/Second Self.app" 2>/dev/null || true

# Create secondself user if needed
if ! id "$SECOND_USER" &>/dev/null; then
    echo "[SecondSelf] Creating secondself user..."
    sysadminctl -addUser "$SECOND_USER" -password "secondself" -admin 2>/dev/null || {
        echo "[SecondSelf] Could not create user automatically."
        echo "[SecondSelf] Run: sudo sysadminctl -addUser secondself -password -"
    }
fi

# If secondself user exists, set up their environment
if id "$SECOND_USER" &>/dev/null; then
    SECOND_HOME="/Users/$SECOND_USER"
    SECOND_UID=$(id -u "$SECOND_USER")

    # Copy repo to secondself's home
    mkdir -p "$SECOND_HOME/second-self"
    rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' \
        "$INSTALL_DIR/" "$SECOND_HOME/second-self/" 2>/dev/null || true

    # Copy .env if it exists
    [ -f "$INSTALL_DIR/.env" ] && cp "$INSTALL_DIR/.env" "$SECOND_HOME/second-self/.env" 2>/dev/null || true
    chown -R "$SECOND_USER:staff" "$SECOND_HOME/second-self"

    # Install LaunchAgents
    LAUNCH_DIR="$SECOND_HOME/Library/LaunchAgents"
    mkdir -p "$LAUNCH_DIR"
    for plist in ai.secondself.agent.plist ai.secondself.chrome.plist; do
        if [ -f "$INSTALL_DIR/setup/$plist" ]; then
            cp "$INSTALL_DIR/setup/$plist" "$LAUNCH_DIR/"
        fi
    done
    chown -R "$SECOND_USER:staff" "$LAUNCH_DIR"

    # Try to start services (may fail if no GUI session yet)
    launchctl bootout "gui/$SECOND_UID/ai.secondself.agent" 2>/dev/null || true
    launchctl bootout "gui/$SECOND_UID/ai.secondself.chrome" 2>/dev/null || true
    sleep 1
    launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.chrome.plist" 2>/dev/null || true
    sleep 2
    launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.agent.plist" 2>/dev/null || true

    echo "[SecondSelf] Services started for secondself"
fi

echo ""
echo "========================================="
echo "  Second Self installed!"
echo ""
echo "  NEXT STEPS:"
echo "  1. Launch the app:  open '/Applications/Second Self.app'"
echo ""
echo "  If this is your first install, you also need to:"
echo "  3. Switch to 'secondself' user (menu bar > user icon)"
echo "  4. Grant Screen Recording to python3 in System Settings"
echo "  5. Switch back to your account"
echo "========================================="

exit 0
POSTINSTALL
chmod +x "$SCRIPTS_DIR/postinstall"

echo "==> Building .pkg..."
pkgbuild \
    --root "$PKG_ROOT" \
    --scripts "$SCRIPTS_DIR" \
    --identifier "$PKG_ID" \
    --version "$VERSION" \
    --install-location "/" \
    "$BUILD_DIR/SecondSelf.pkg"

echo ""
PKG_SIZE=$(du -sh "$BUILD_DIR/SecondSelf.pkg" | cut -f1)
echo "✅ Built: $BUILD_DIR/SecondSelf.pkg ($PKG_SIZE)"
echo ""
echo "To install locally:  open build/SecondSelf.pkg"
echo "To distribute:       upload SecondSelf.pkg to GitHub Release"
