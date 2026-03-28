#!/bin/bash
echo "=== VNC Debug ==="
echo ""
echo "1. Port 5901 listening:"
netstat -an | grep 5901
echo ""
echo "2. TCP connectivity:"
nc -zv localhost 5901 2>&1
echo ""
echo "3. Firewall state:"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
echo ""
echo "4. WindowServer processes:"
ps aux | grep -c "[W]indowServer"
echo ""
echo "5. Vine Server process:"
ps aux | grep -i "[v]ine"
echo ""
echo "6. Screen Sharing service:"
sudo launchctl list | grep -i screen
echo ""
echo "7. VNC banner test:"
echo | nc -w 2 localhost 5901 2>&1 | head -1
