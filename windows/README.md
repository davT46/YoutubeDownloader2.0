# YouTube Audio Downloader

Desktop application to convert YouTube videos to MP3, with playlist support,
parallel downloads and cookie management.

## Features

- Convert YouTube videos to MP3 (192K, best available audio track)
- Download entire playlists or single tracks
- Paste multiple URLs at once, one per line
- Two modes: **Playlist** and **Single Songs**
- In **Playlist** mode you can mix playlists and single videos:
  - playlists are saved in subfolders named after the playlist
  - single videos are saved in a folder called **NA**
- Parallel downloads (12 threads by default)
- Cookie support: cookie file or cookies from your browser (Chrome, Firefox, Edge, Opera, Vivaldi, Brave)
- Dark/light theme
- Debug Mode to see the full yt-dlp output in case of errors
- Automatic yt-dlp updates: a copy is bundled in the exe and is
  updated from GitHub whenever a newer version is available
- Single portable .exe file: Python, FFmpeg, FFprobe and yt-dlp are all bundled
- Choose the download folder

## Usage

1. Paste one or more YouTube URLs (one per line)
2. Choose **Playlist** or **Single Songs** mode
3. (Optional) Select a browser or a cookie file for protected content
4. Press **START DOWNLOAD**
5. MP3 files are saved to the folder you chose (default: `Desktop\downloaded_music`)

In **Playlist** mode you can mix playlists and single videos. Single videos
(those that don't belong to a playlist) are saved in a subfolder called
**NA**: this is the value yt-dlp uses when a field like the playlist name
is not available.

## Downloading the executable

The latest build is available in the **Releases** section: it is a single
portable file (`YouTubeDownloader2.0.exe`), no installation required.

## Building from source

Prerequisites: Python 3 (tested with 3.13).

1. Clone the repository and install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Download and place these three files in the `resources` folder:

   ```
   resources/
   ├── ffmpeg.exe
   ├── ffprobe.exe
   └── yt-dlp.exe
   ```

   - **FFmpeg / FFprobe**: full Windows build from
     https://github.com/BtbN/FFmpeg-Builds (release tag `latest`, build `win64-gpl`,
     just extract `bin\ffmpeg.exe` and `bin\ffprobe.exe`)
   - **yt-dlp.exe**: from https://github.com/yt-dlp/yt-dlp/releases

3. Build the executable (everything is bundled in the file: Python, FFmpeg, FFprobe, yt-dlp):

   ```bash
   pyinstaller --clean YouTubeDownloader2.0.spec
   ```

4. The executable is at `dist\YouTubeDownloader2.0.exe`

### Running without building

To try the app directly from the source:

```bash
python youtube_audio_downloader_gui.py
```

In this case `yt-dlp` must be reachable from the PATH, and FFmpeg in the
`resources` folder next to the script.

## Tips

- **max_workers**: in `youtube_audio_downloader_gui.py`, inside the
  `run_download_logic` method, `ThreadPoolExecutor(max_workers=12)` is used.
  This number controls how many downloads run in parallel: **lower it on
  PCs with little RAM or CPU, raise it on more powerful PCs** (e.g. 4 on
  modest PCs, 20+ on high-end ones).
- If a download fails, enable **Debug Mode** to see the full yt-dlp output.
- For age-restricted content, use browser cookies or a cookie file.
- The app saves a backup of the URLs in `~\.yt-audio-downloader\saved_urls.txt`
  and keeps yt-dlp updated in the same folder.

## Notes

- The binary files (ffmpeg, ffprobe, yt-dlp) are not included in the repository
  because they are too large for GitHub: download them and put them in
  `resources` before building.
