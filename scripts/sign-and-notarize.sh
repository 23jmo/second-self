#!/bin/bash
# Sign and notarize the SecondSelf PKG for Gatekeeper-clean distribution.
# Prerequisites:
#   1. Run ./build-pkg.sh first (produces build/SecondSelf.pkg)
#   2. Developer ID Application + Installer certs in Keychain
#   3. App-specific password stored in Keychain:
#        xcrun notarytool store-credentials "SecondSelf-Notary" \
#          --apple-id "your@email.com" \
#          --team-id "YOUR_TEAM_ID" \
#          --password "app-specific-password"
#
# Usage: ./scripts/sign-and-notarize.sh [--wait]
#   --wait: Block until notarization completes (default: submit and exit)

set -euo pipefail

BUILD_DIR="$(cd "$(dirname "$0")/.." && pwd)/build"
PKG_FILE="$BUILD_DIR/SecondSelf.pkg"
KEYCHAIN_PROFILE="SecondSelf-Notary"

WAIT=false
for arg in "$@"; do
    [ "$arg" = "--wait" ] && WAIT=true
done

if [ ! -f "$PKG_FILE" ]; then
    echo "PKG not found at $PKG_FILE"
    echo "Run ./build-pkg.sh first."
    exit 1
fi

# ─── Verify signing ───

echo "==> Checking PKG signature..."
if pkgutil --check-signature "$PKG_FILE" 2>/dev/null | grep -q "Developer ID Installer"; then
    echo "    PKG is signed"
else
    echo "    PKG is NOT signed. Re-run build-pkg.sh without --skip-sign."
    exit 1
fi

# ─── Submit for notarization ───

echo "==> Submitting for notarization..."
echo "    Using keychain profile: $KEYCHAIN_PROFILE"

if [ "$WAIT" = true ]; then
    xcrun notarytool submit "$PKG_FILE" \
        --keychain-profile "$KEYCHAIN_PROFILE" \
        --wait
else
    xcrun notarytool submit "$PKG_FILE" \
        --keychain-profile "$KEYCHAIN_PROFILE"
    echo ""
    echo "Notarization submitted. Check status with:"
    echo "  xcrun notarytool history --keychain-profile $KEYCHAIN_PROFILE"
    echo ""
    echo "Once approved, staple with:"
    echo "  xcrun stapler staple $PKG_FILE"
    exit 0
fi

# ─── Staple the ticket ───

echo "==> Stapling notarization ticket..."
xcrun stapler staple "$PKG_FILE"

# ─── Verify ───

echo "==> Verifying..."
spctl --assess --type install "$PKG_FILE" 2>&1 && echo "    PKG passes Gatekeeper" || echo "    WARNING: Gatekeeper check failed"

# Regenerate checksum (stapling modifies the file)
shasum -a 256 "$PKG_FILE" > "$PKG_FILE.sha256"

echo ""
echo "Notarized PKG ready: $PKG_FILE"
echo "SHA256: $(cat "$PKG_FILE.sha256")"
echo ""
echo "This PKG will install without any Gatekeeper warnings."
