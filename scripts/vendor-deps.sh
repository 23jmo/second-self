#!/bin/bash
# Pre-install all pip dependencies into the standalone Python's site-packages.
# Run this AFTER fetch-python.sh and BEFORE build-pkg.sh.
# This runs at BUILD TIME so the PKG ships with all deps included.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$REPO_DIR/build"
PYTHON_DIR="$BUILD_DIR/python-standalone"
PYTHON="$PYTHON_DIR/bin/python3"

if [ ! -x "$PYTHON" ]; then
    echo "Standalone Python not found. Run fetch-python.sh first."
    exit 1
fi

echo "==> Using Python: $("$PYTHON" --version)"
echo ""

# Ensure pip is available and up to date
"$PYTHON" -m ensurepip --upgrade 2>/dev/null || true
"$PYTHON" -m pip install --upgrade pip --quiet

# Install all requirement files into the standalone Python's site-packages
REQUIREMENTS=(
    "$REPO_DIR/requirements.txt"
    "$REPO_DIR/orchestrator/requirements.txt"
    "$REPO_DIR/agent-server/requirements.txt"
)

for req in "${REQUIREMENTS[@]}"; do
    if [ -f "$req" ]; then
        echo "==> Installing from $(basename "$(dirname "$req")")/$(basename "$req")..."
        "$PYTHON" -m pip install --quiet -r "$req" 2>&1 | grep -v "already satisfied" || true
    else
        echo "    Skipping $req (not found)"
    fi
done

# Verify critical packages
echo ""
echo "==> Verifying critical packages..."
CRITICAL_PACKAGES=(anthropic fastapi uvicorn pyautogui)
ALL_OK=true
for pkg in "${CRITICAL_PACKAGES[@]}"; do
    if "$PYTHON" -c "import $pkg" 2>/dev/null; then
        VERSION=$("$PYTHON" -c "import $pkg; print(getattr($pkg, '__version__', 'ok'))" 2>/dev/null || echo "ok")
        echo "    $pkg ($VERSION)"
    else
        echo "    $pkg MISSING"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = true ]; then
    echo ""
    echo "All dependencies vendored successfully."
else
    echo ""
    echo "Some dependencies failed to install. Check errors above."
    exit 1
fi

# Print size
SITE_SIZE=$(du -sh "$PYTHON_DIR/lib" 2>/dev/null | cut -f1)
echo "Vendored Python size: $SITE_SIZE"
