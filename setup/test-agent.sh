#!/bin/bash
# Quick test script for the Agent Server
# Tests both browser (browser-use via CDP) and desktop (PyAutoGUI) endpoints

AGENT_URL="http://localhost:8421"

echo "=== Agent Server Test ==="
echo ""

# Health check (includes browser-use status)
echo "1. Health check..."
HEALTH=$(curl -s "$AGENT_URL/health")
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "  ❌ Agent Server not responding at $AGENT_URL"
echo ""

# Screen size (desktop tool)
echo "2. Screen size (desktop)..."
curl -s -X POST "$AGENT_URL/tool/screen_size" \
    -H "Content-Type: application/json" \
    -d '{}' | python3 -m json.tool
echo ""

# Browser: Navigate to Google
echo "3. Browser: goto google.com..."
curl -s -X POST "$AGENT_URL/browser/goto" \
    -H "Content-Type: application/json" \
    -d '{"url":"https://google.com"}' | python3 -m json.tool
sleep 2
echo ""

# Browser: Get element refs
echo "4. Browser: snapshot (get element refs)..."
SNAPSHOT=$(curl -s -X POST "$AGENT_URL/browser/snapshot" \
    -H "Content-Type: application/json" \
    -d '{}')
echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null || echo "$SNAPSHOT" | head -20
echo ""

# Browser: Get page text
echo "5. Browser: text (get page content)..."
curl -s -X POST "$AGENT_URL/browser/text" \
    -H "Content-Type: application/json" \
    -d '{}' | python3 -m json.tool 2>/dev/null | head -20
echo ""

# Desktop: Open an app
echo "6. Desktop: open Notes..."
curl -s -X POST "$AGENT_URL/tool/open_app" \
    -H "Content-Type: application/json" \
    -d '{"name":"Notes"}' | python3 -m json.tool
echo ""

echo "=== Test Complete ==="
echo ""
echo "Check TigerVNC:"
echo "  - Chrome should show Google (from browser test)"
echo "  - Notes should be open (from desktop test)"
echo ""
echo "If browser tests failed, verify:"
echo "  1. browser-use is installed: pip show browser-use"
echo "  2. Chrome is running with CDP: curl -s http://localhost:9222/json/version"
echo "  3. Chrome LaunchAgent is loaded: launchctl list | grep secondself.chrome"
