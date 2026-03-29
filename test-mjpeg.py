#!/usr/bin/env python3
"""Standalone MJPEG stream tester. Tests the agent-server /stream endpoint."""

import urllib.request
import sys
import time

PORTS = [8421, 8422, 8423]

def test_stream():
    for port in PORTS:
        url = f"http://localhost:{port}/stream"
        print(f"\n--- Testing {url} ---")
        try:
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=5)
            print(f"  Status: {resp.status}")
            print(f"  Content-Type: {resp.headers.get('Content-Type')}")

            # Read first 10KB to see if frames arrive
            data = resp.read(10240)
            print(f"  Received: {len(data)} bytes")

            # Check for JPEG markers
            jpeg_start = data.find(b'\xff\xd8')
            jpeg_end = data.find(b'\xff\xd9')
            print(f"  JPEG start (FFD8) at byte: {jpeg_start}")
            print(f"  JPEG end (FFD9) at byte: {jpeg_end}")

            if jpeg_start >= 0 and jpeg_end > jpeg_start:
                frame = data[jpeg_start:jpeg_end+2]
                with open("/tmp/mjpeg-test-frame.jpg", "wb") as f:
                    f.write(frame)
                print(f"  Frame saved: /tmp/mjpeg-test-frame.jpg ({len(frame)} bytes)")
                print(f"  STREAM WORKS on port {port}")
            else:
                print(f"  No complete JPEG frame in first 10KB")
                # Show what we got
                print(f"  First 200 bytes: {data[:200]}")

            resp.close()
            return port

        except urllib.error.URLError as e:
            print(f"  Connection failed: {e}")
        except Exception as e:
            print(f"  Error: {e}")

    print("\n  NO WORKING STREAM FOUND on any port")
    return None

if __name__ == "__main__":
    working_port = test_stream()
    if working_port:
        print(f"\n  Open in browser to verify: http://localhost:{working_port}/view")
