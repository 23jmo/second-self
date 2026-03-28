#!/bin/bash
# Quick test script for the Agent Server
# Opens Google and searches for "Johnathan Mo"

AGENT_URL="http://localhost:8421"

echo "=== Agent Server Test ==="
echo ""

# Health check
echo "1. Health check..."
curl -s "$AGENT_URL/health" | python3 -m json.tool
echo ""

# Screen size
echo "2. Screen size..."
curl -s -X POST "$AGENT_URL/tool/screen_size" \
    -H "Content-Type: application/json" \
    -d '{}' | python3 -m json.tool
echo ""

# Open Chrome to Google
echo "3. Opening Google in Chrome..."
curl -s -X POST "$AGENT_URL/tool/navigate" \
    -H "Content-Type: application/json" \
    -d '{"url":"https://google.com"}' | python3 -m json.tool
sleep 2
echo ""

# Click the search box (center of screen, roughly where Google search is)
echo "4. Clicking search box..."
curl -s -X POST "$AGENT_URL/tool/click" \
    -H "Content-Type: application/json" \
    -d '{"x":756, "y":500}' | python3 -m json.tool
sleep 1
echo ""

# Type the search query
echo "5. Typing search query..."
curl -s -X POST "$AGENT_URL/tool/type" \
    -H "Content-Type: application/json" \
    -d '{"text":"Johnathan Mo"}' | python3 -m json.tool
sleep 1
echo ""

# Press Enter to search
echo "6. Pressing Enter..."
curl -s -X POST "$AGENT_URL/tool/hotkey" \
    -H "Content-Type: application/json" \
    -d '{"keys":["return"]}' | python3 -m json.tool
echo ""

echo "=== Test Complete ==="
echo "Check TigerVNC — you should see Google search results for 'Johnathan Mo'"
