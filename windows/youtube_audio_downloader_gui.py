#!/usr/bin/env python3
import os
import sys

# Make shared app importable both from source and from PyInstaller bundle
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # In a PyInstaller bundle, all files are extracted to sys._MEIPASS
    sys.path.insert(0, sys._MEIPASS)
    # Also add exe dir as fallback
    sys.path.insert(0, os.path.dirname(sys.executable))
    app_dir = sys._MEIPASS
else:
    # Running from source: shared app is one folder up
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(base_dir, '..'))
    app_dir = base_dir

from youtube_audio_downloader_app import run_app

if __name__ == "__main__":
    run_app(app_dir=app_dir)