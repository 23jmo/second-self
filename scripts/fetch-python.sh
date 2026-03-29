#!/bin/bash
# Download a standalone Python 3.11 build for embedding in the PKG.
# Source: https://github.com/indygreg/python-build-standalone
# Output: build/python-standalone/ (ready for vendoring)

set -euo pipefail

PYTHON_VERSION="3.11.11"
RELEASE_TAG="20250317"
ARCH=$(uname -m)  # arm64 or x86_64

BUILD_DIR="$(cd "$(dirname "$0")/.." && pwd)/build"
PYTHON_DIR="$BUILD_DIR/python-standalone"

if [ -d "$PYTHON_DIR/bin/python3" ] 2>/dev/null && [ -x "$PYTHON_DIR/bin/python3" ]; then
    EXISTING_VER=$("$PYTHON_DIR/bin/python3" --version 2>/dev/null || echo "")
    if echo "$EXISTING_VER" | grep -q "$PYTHON_VERSION"; then
        echo "Python $PYTHON_VERSION already fetched at $PYTHON_DIR"
        exit 0
    fi
fi

# Map arch to python-build-standalone naming
case "$ARCH" in
    arm64)  TRIPLE="aarch64-apple-darwin" ;;
    x86_64) TRIPLE="x86_64-apple-darwin"  ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

FILENAME="cpython-${PYTHON_VERSION}+${RELEASE_TAG}-${TRIPLE}-install_only_stripped.tar.gz"
URL="https://github.com/indygreg/python-build-standalone/releases/download/${RELEASE_TAG}/${FILENAME}"

echo "==> Downloading Python $PYTHON_VERSION for $ARCH..."
echo "    URL: $URL"

mkdir -p "$BUILD_DIR"
TARBALL="$BUILD_DIR/$FILENAME"

if [ ! -f "$TARBALL" ]; then
    curl -L --progress-bar -o "$TARBALL" "$URL"
else
    echo "    Using cached tarball"
fi

echo "==> Extracting to $PYTHON_DIR..."
rm -rf "$PYTHON_DIR"
mkdir -p "$PYTHON_DIR"
tar xzf "$TARBALL" -C "$BUILD_DIR"

# python-build-standalone extracts to build/python/
# Move it to our expected location
if [ -d "$BUILD_DIR/python" ] && [ "$BUILD_DIR/python" != "$PYTHON_DIR" ]; then
    rm -rf "$PYTHON_DIR"
    mv "$BUILD_DIR/python" "$PYTHON_DIR"
fi

# Verify
"$PYTHON_DIR/bin/python3" --version
echo ""
echo "Python standalone ready at: $PYTHON_DIR"
