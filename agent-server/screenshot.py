#!/usr/bin/env python3
"""Standalone screenshot capture. Outputs JPEG to stdout."""
import sys
import io
import pyautogui
from PIL import Image

img = pyautogui.screenshot()
img = img.convert("RGB")
img = img.resize((img.width // 2, img.height // 2))
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=60)
sys.stdout.buffer.write(buf.getvalue())
