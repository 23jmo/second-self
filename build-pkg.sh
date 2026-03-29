#!/bin/bash
# Build Second Self as a signed macOS .pkg installer with embedded Python.
# Usage: ./build-pkg.sh [--skip-python] [--skip-sign]
#
# Prerequisites:
#   - Run scripts/fetch-python.sh && scripts/vendor-deps.sh first
#   - For signing: Developer ID certs in Keychain (see scripts/sign-and-notarize.sh)
#
# Produces: build/SecondSelf.pkg (or build/SecondSelf-unsigned.pkg)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$REPO_DIR/build"
PKG_ROOT="$BUILD_DIR/pkg-root"
SCRIPTS_DIR="$BUILD_DIR/pkg-scripts"
APP_NAME="Second Self"
BUNDLE_ID="com.secondself.app"
VERSION="0.1.0"

SKIP_PYTHON=false
SKIP_SIGN=false
for arg in "$@"; do
    case "$arg" in
        --skip-python) SKIP_PYTHON=true ;;
        --skip-sign)   SKIP_SIGN=true ;;
    esac
done

# ─── Step 1: Ensure standalone Python is ready ───

PYTHON_DIR="$BUILD_DIR/python-standalone"
if [ "$SKIP_PYTHON" = false ]; then
    if [ ! -x "$PYTHON_DIR/bin/python3" ]; then
        echo "==> Fetching standalone Python..."
        bash "$REPO_DIR/scripts/fetch-python.sh"
        echo ""
        echo "==> Vendoring dependencies..."
        bash "$REPO_DIR/scripts/vendor-deps.sh"
        echo ""
    else
        echo "==> Standalone Python already prepared"
    fi
fi

# ─── Step 2: Build Swift binary (release) ───

echo "==> Building SecondSelf (release)..."
cd "$REPO_DIR/SecondSelf"
swift build -c release 2>&1 | tail -3

BINARY=$(swift build -c release --show-bin-path)/SecondSelf
if [ ! -f "$BINARY" ]; then
    echo "Build failed — binary not found"
    exit 1
fi
cd "$REPO_DIR"

# ─── Step 3: Assemble the .app bundle ───

echo "==> Assembling $APP_NAME.app..."
rm -rf "$PKG_ROOT" "$SCRIPTS_DIR"
APP_DIR="$PKG_ROOT/Applications/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

# Binary
cp "$BINARY" "$CONTENTS/MacOS/SecondSelf"

# Info.plist + PkgInfo
cp SecondSelf/Info.plist "$CONTENTS/Info.plist"
echo -n "APPL????" > "$CONTENTS/PkgInfo"

# Entitlements (for reference — used by codesign, not bundled)
# cp SecondSelf/SecondSelf.entitlements "$CONTENTS/"

# Bundle resources (xcassets → compiled asset catalog)
BUNDLE_RESOURCE=$(find SecondSelf/.build/release -name 'SecondSelf_SecondSelf.bundle' 2>/dev/null | head -1)
if [ -n "$BUNDLE_RESOURCE" ] && [ -d "$BUNDLE_RESOURCE" ]; then
    cp -R "$BUNDLE_RESOURCE" "$CONTENTS/Resources/"
fi

# ─── Step 4: Code-sign the .app ───

if [ "$SKIP_SIGN" = false ]; then
    # Find Developer ID Application certificate
    SIGN_IDENTITY=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | sed 's/.*"\(.*\)"/\1/')
    if [ -n "$SIGN_IDENTITY" ]; then
        echo "==> Signing app with: $SIGN_IDENTITY"
        codesign --force --options runtime --deep \
            --entitlements "$REPO_DIR/SecondSelf/SecondSelf.entitlements" \
            --sign "$SIGN_IDENTITY" \
            "$APP_DIR"
    else
        echo "==> No Developer ID Application certificate found, skipping app signing"
        SKIP_SIGN=true
    fi
fi

# ─── Step 5: Bundle runtime files into /usr/local/share/second-self ───

echo "==> Bundling runtime files..."
SHARE_DIR="$PKG_ROOT/usr/local/share/second-self"
mkdir -p "$SHARE_DIR"

# Python runtime (standalone + vendored packages)
if [ -d "$PYTHON_DIR" ]; then
    echo "    Copying embedded Python..."
    mkdir -p "$SHARE_DIR/python"
    rsync -a "$PYTHON_DIR/" "$SHARE_DIR/python/"

    # Sign all Python binaries for notarization
    if [ "$SKIP_SIGN" = false ] && [ -n "$SIGN_IDENTITY" ]; then
        echo "==> Signing embedded Python binaries..."
        # Sign all .so and .dylib files (native extensions)
        find "$SHARE_DIR/python" \( -name '*.so' -o -name '*.dylib' \) -type f | while read -r lib; do
            codesign --force --options runtime --timestamp \
                --sign "$SIGN_IDENTITY" "$lib" 2>/dev/null || true
        done
        # Sign the Python binary itself
        PYTHON_BIN="$SHARE_DIR/python/bin/python3.11"
        if [ -f "$PYTHON_BIN" ]; then
            codesign --force --options runtime --timestamp \
                --entitlements "$REPO_DIR/SecondSelf/SecondSelf.entitlements" \
                --sign "$SIGN_IDENTITY" "$PYTHON_BIN"
        fi
        echo "    Python binaries signed"
    fi
else
    echo "    WARNING: No standalone Python found — PKG will require system Python"
fi

# Application source code
for dir in orchestrator agent-server src setup cookie_sync; do
    if [ -d "$REPO_DIR/$dir" ]; then
        rsync -a --exclude='__pycache__' --exclude='*.pyc' \
            "$REPO_DIR/$dir/" "$SHARE_DIR/$dir/"
    fi
done

# Config files (bundle real .env for demo — API keys included)
[ -f "$REPO_DIR/.env" ] && cp "$REPO_DIR/.env" "$SHARE_DIR/.env"
[ -f "$REPO_DIR/.env.example" ] && cp "$REPO_DIR/.env.example" "$SHARE_DIR/.env.example"
[ -f "$REPO_DIR/requirements.txt" ] && cp "$REPO_DIR/requirements.txt" "$SHARE_DIR/"

# Make setup scripts executable
chmod +x "$SHARE_DIR/setup/"*.sh 2>/dev/null || true

# ─── Step 6: Create the postinstall script ───

echo "==> Creating postinstall script..."
mkdir -p "$SCRIPTS_DIR"
cat > "$SCRIPTS_DIR/postinstall" << 'POSTINSTALL'
#!/bin/bash
# Second Self — Post-install provisioning
# Runs as root after .pkg installs files.
# Handles EVERYTHING so the user never touches Terminal.

set -e

INSTALL_DIR="/usr/local/share/second-self"
PYTHON="$INSTALL_DIR/python/bin/python3"
REAL_USER=$(stat -f '%Su' /dev/console)
REAL_HOME=$(dscl . -read /Users/"$REAL_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
SECOND_USER="secondself"
LOG="/tmp/secondself-install.log"

log() { echo "[SecondSelf] $1" | tee -a "$LOG"; }

log "Post-install starting for user: $REAL_USER"

# ── 1. Symlink ~/second-self for easy access ──
if [ -n "$REAL_HOME" ] && [ ! -e "$REAL_HOME/second-self" ]; then
    ln -s "$INSTALL_DIR" "$REAL_HOME/second-self"
    chown -h "$REAL_USER:staff" "$REAL_HOME/second-self"
    log "Symlinked ~/second-self -> $INSTALL_DIR"
fi

# ── 2. Clear Gatekeeper on the app ──
xattr -cr "/Applications/Second Self.app" 2>/dev/null || true
log "Gatekeeper quarantine cleared"

# ── 3. Create secondself user (silent, no prompts) ──
if ! id "$SECOND_USER" &>/dev/null; then
    log "Creating secondself user..."
    sysadminctl -addUser "$SECOND_USER" -password "secondself" -admin 2>/dev/null || {
        log "Could not create user automatically. Manual step needed."
    }
fi

# ── 4. Set up secondself's environment ──
if id "$SECOND_USER" &>/dev/null; then
    SECOND_HOME="/Users/$SECOND_USER"
    SECOND_UID=$(id -u "$SECOND_USER")

    # Copy code + config to secondself's home
    mkdir -p "$SECOND_HOME/second-self"
    rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        "$INSTALL_DIR/" "$SECOND_HOME/second-self/" 2>/dev/null || true
    chown -R "$SECOND_USER:staff" "$SECOND_HOME/second-self"
    log "Code synced to $SECOND_HOME/second-self"

    # ── 5. Install LaunchAgents ──
    LAUNCH_DIR="$SECOND_HOME/Library/LaunchAgents"
    mkdir -p "$LAUNCH_DIR"
    for plist in ai.secondself.agent.plist ai.secondself.chrome.plist; do
        if [ -f "$INSTALL_DIR/setup/$plist" ]; then
            cp "$INSTALL_DIR/setup/$plist" "$LAUNCH_DIR/"
        fi
    done
    chown -R "$SECOND_USER:staff" "$LAUNCH_DIR"
    log "LaunchAgents installed"

    # ── 6. Install Chromium for browser-use (if not already present) ──
    if [ -x "$PYTHON" ]; then
        if ! [ -d "$SECOND_HOME/.browser-use" ] && ! [ -d "/Applications/Google Chrome.app" ]; then
            log "Installing Chromium via browser-use..."
            sudo -H -u "$SECOND_USER" "$PYTHON" -m browser_use install 2>>"$LOG" || {
                # Fallback: try the CLI
                BROWSER_USE_BIN="$INSTALL_DIR/python/bin/browser-use"
                if [ -x "$BROWSER_USE_BIN" ]; then
                    sudo -H -u "$SECOND_USER" "$BROWSER_USE_BIN" install 2>>"$LOG" || true
                fi
            }
        fi
    fi

    # ── 7. Try to bootstrap LaunchAgents ──
    # This may fail if secondself has never logged in (no GUI session yet)
    launchctl bootout "gui/$SECOND_UID/ai.secondself.agent" 2>/dev/null || true
    launchctl bootout "gui/$SECOND_UID/ai.secondself.chrome" 2>/dev/null || true
    sleep 1
    launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.chrome.plist" 2>/dev/null || true
    sleep 2
    launchctl bootstrap "gui/$SECOND_UID" "$LAUNCH_DIR/ai.secondself.agent.plist" 2>/dev/null || true
    log "LaunchAgents bootstrapped (may need GUI session)"

    # ── 8. Write first-run marker ──
    touch "$INSTALL_DIR/.installed"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$INSTALL_DIR/.installed"
    log "Install marker written"
fi

log "Post-install complete"
log ""
log "Launch 'Second Self' from Applications to get started."
log "Install log: $LOG"

exit 0
POSTINSTALL
chmod +x "$SCRIPTS_DIR/postinstall"

# ─── Step 7: Build the .pkg ───

echo "==> Building .pkg..."

# Use pkgbuild to create the component package
pkgbuild \
    --root "$PKG_ROOT" \
    --scripts "$SCRIPTS_DIR" \
    --identifier "$BUNDLE_ID" \
    --version "$VERSION" \
    --install-location "/" \
    "$BUILD_DIR/SecondSelf-component.pkg"

# Wrap with productbuild for signing support
if [ "$SKIP_SIGN" = false ]; then
    INSTALLER_IDENTITY=$(security find-identity -v -p basic | grep "Developer ID Installer" | head -1 | sed 's/.*"\(.*\)"/\1/' || true)
    if [ -n "$INSTALLER_IDENTITY" ]; then
        echo "==> Signing PKG with: $INSTALLER_IDENTITY"
        productbuild \
            --package "$BUILD_DIR/SecondSelf-component.pkg" \
            "$BUILD_DIR/SecondSelf-unsigned.pkg"
        productsign \
            --sign "$INSTALLER_IDENTITY" \
            "$BUILD_DIR/SecondSelf-unsigned.pkg" \
            "$BUILD_DIR/SecondSelf.pkg"
        rm -f "$BUILD_DIR/SecondSelf-unsigned.pkg" "$BUILD_DIR/SecondSelf-component.pkg"
        PKG_FILE="$BUILD_DIR/SecondSelf.pkg"
    else
        echo "==> No Developer ID Installer certificate found, shipping unsigned"
        mv "$BUILD_DIR/SecondSelf-component.pkg" "$BUILD_DIR/SecondSelf.pkg"
        PKG_FILE="$BUILD_DIR/SecondSelf.pkg"
    fi
else
    mv "$BUILD_DIR/SecondSelf-component.pkg" "$BUILD_DIR/SecondSelf.pkg"
    PKG_FILE="$BUILD_DIR/SecondSelf.pkg"
fi

# ─── Step 8: Generate checksum ───

shasum -a 256 "$PKG_FILE" > "$PKG_FILE.sha256"

echo ""
PKG_SIZE=$(du -sh "$PKG_FILE" | cut -f1)
echo "Built: $PKG_FILE ($PKG_SIZE)"
echo "SHA256: $(cat "$PKG_FILE.sha256")"
echo ""
echo "To install locally:  open '$PKG_FILE'"
echo "To notarize:         bash scripts/sign-and-notarize.sh"
echo "To distribute:       upload to GitHub Release"
