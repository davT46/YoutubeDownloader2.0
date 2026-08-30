#!/usr/bin/env python3
import os
import sys

# the shared application lives one folder up; make it importable both when
# running from source and when frozen into a bundle by PyInstaller
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from youtube_audio_downloader_app import run_app

if __name__ == "__main__":
    run_app(app_dir=os.path.dirname(os.path.abspath(__file__)))