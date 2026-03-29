#!/bin/bash
# Smoke test for the Second Self streaming pipeline.
# Tests agent-server, orchestrator, MJPEG stream, and optional VNC.
# Usage: ./setup/smoke-test.sh

PASS=0
FAIL=0
SKIP=0

check() {
    local label="$1"
    local result="$2"
    if [ "$result" = "pass" ]; then
        echo "  ✅ $label"
        PASS=$((PASS + 1))
    elif [ "$result" = "skip" ]; then
        echo "  ⏭  $label"
        SKIP=$((SKIP + 1))
    else
        echo "  ❌ $label"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Second Self Smoke Test ==="
echo ""

# 1. Agent Server health
echo "1. Agent Server (:8421)"
HEALTH=$(curl -s --connect-timeout 3 http://localhost:8421/health 2>/dev/null)
if echo "$HEALTH" | grep -q '"status"'; then
    check "Responding" "pass"
    if echo "$HEALTH" | grep -q '"stream_active": true'; then
        check "Stream active" "pass"
    else
        check "Stream active (capture may not be running)" "fail"
    fi
else
    check "Not responding" "fail"
    check "Stream active" "skip"
fi
echo ""

# 2. Orchestrator health (only when SwiftUI app is running)
echo "2. Orchestrator (:8420)"
ORCH_HEALTH=$(curl -s --connect-timeout 3 http://localhost:8420/health 2>/dev/null)
if echo "$ORCH_HEALTH" | grep -q '"status"'; then
    check "Responding" "pass"
else
    check "Not responding (start SecondSelf app or run orchestrator manually)" "fail"
fi
echo ""

# 3. MJPEG stream produces frames
echo "3. MJPEG Stream"
STREAM_FILE="/tmp/mjpeg-smoke-test.bin"
rm -f "$STREAM_FILE"
curl -s --max-time 3 http://localhost:8421/stream > "$STREAM_FILE" 2>/dev/null
if [ -s "$STREAM_FILE" ]; then
    check "Stream produces data" "pass"
    # Check for JPEG SOI marker (0xFF 0xD8)
    if xxd -l 512 "$STREAM_FILE" | grep -q "ffd8"; then
        check "Contains JPEG frames" "pass"
    else
        check "No JPEG markers found" "fail"
    fi
else
    check "Stream produced no data" "fail"
fi
rm -f "$STREAM_FILE"
echo ""

# 4. VNC (optional)
echo "4. VNC / Vine Server (:5901, optional)"
if netstat -an 2>/dev/null | grep -q "\.5901.*LISTEN"; then
    check "Vine Server listening" "pass"
    BANNER=$(echo | nc -w 2 localhost 5901 2>&1 | head -1)
    if echo "$BANNER" | grep -q "RFB"; then
        check "VNC protocol responding ($BANNER)" "pass"
    else
        check "VNC not responding to protocol" "fail"
    fi
else
    check "Vine Server not running (optional)" "skip"
fi
echo ""

# 5. Chrome CDP (optional)
echo "5. Chrome CDP (:9222)"
CDP_CHECK=$(curl -s --connect-timeout 2 http://localhost:9222/json/version 2>/dev/null)
if echo "$CDP_CHECK" | grep -q "Browser"; then
    check "Chrome DevTools responding" "pass"
else
    check "Chrome not running or CDP not exposed" "skip"
fi
echo ""

# Summary
echo "========================================="
echo "  Results: $PASS passed, $FAIL failed, $SKIP skipped"
if [ "$FAIL" -eq 0 ]; then
    echo "  Pipeline is healthy."
else
    echo "  ⚠️  $FAIL check(s) failed. See above for details."
fi
echo "========================================="
exit "$FAIL"
