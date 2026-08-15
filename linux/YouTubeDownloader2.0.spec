# -*- mode: python ; coding: utf-8 -*-

import os

app_dir = os.path.dirname(os.path.abspath(SPEC))


def resource(name):
    return os.path.join(app_dir, 'resources', name)


a = Analysis(
    [os.path.join(app_dir, 'youtube_audio_downloader_gui.py')],
    pathex=[app_dir],
    binaries=[
        (resource('ffmpeg'), 'resources'),
        (resource('ffprobe'), 'resources'),
        (resource('yt-dlp'), 'resources'),
    ],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YouTubeDownloader2.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
