# YouTube Audio Downloader

Desktop application to convert YouTube videos to MP3, with playlist support,
parallel downloads and cookie management. Available for **Windows** and
**Linux**, each with its own self-contained folder and build files.

## Folder structure

- [`windows/`](windows/) — Windows version (single portable `.exe`,
  build instructions in `windows/README.md`)
- [`linux/`](linux/) — Linux version (single portable binary,
  build instructions in `linux/README.md`)
- `youtube_audio_downloader_app.py` — single shared application used by
  both platforms (each platform folder only keeps a small launcher, its
  build files and its own `resources/`)
- [`.github/workflows/build.yml`](.github/workflows/build.yml) — builds
  both platforms and attaches the binaries to GitHub Releases on every
  `v*` tag (and on push to `main`/manual run, artifacts only)

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
- Automatic yt-dlp updates: a copy is bundled in the binary and is updated
  from GitHub whenever a newer version is available
- Single portable file: Python, FFmpeg, FFprobe and yt-dlp are all bundled
- Choose the download folder

## Usage

1. Paste one or more YouTube URLs (one per line)
2. Choose **Playlist** or **Single Songs** mode
3. (Optional) Select a browser or a cookie file for protected content
4. Press **START DOWNLOAD**
5. MP3 files are saved to the folder you chose (default:
   `Desktop\downloaded_music` on Windows, `~/Desktop/downloaded_music` on Linux)

In **Playlist** mode you can mix playlists and single videos. Single videos
(those that don't belong to a playlist) are saved in a subfolder called
**NA**: this is the value yt-dlp uses when a field like the playlist name
is not available.

## Downloading the executable

The latest builds are available in the **Releases** section:
- Windows: `YouTubeDownloader2.0.exe`
- Linux: `YouTubeDownloader2.0`

Both are single portable files, no installation required.

## Building from source

Prerequisites: Python 3 (tested with 3.13).

1. Enter the folder for your platform (`windows/` or `linux/`)
2. Install the dependencies: `pip install -r requirements.txt`
3. Download FFmpeg, FFprobe and yt-dlp for your platform and place them in
   the `resources/` folder (see the platform README for exact names and links)
4. Build: `pyinstaller --clean YouTubeDownloader2.0.spec`
5. The executable is in `dist/`

## Tips

- **Parallel downloads**: in the app UI, use the **Parallel downloads**
  control to choose how many downloads run at the same time. Lower it on
  PCs with little RAM or CPU, raise it on more powerful PCs (e.g. 4 on
  modest PCs, 20+ on high-end ones). The value is saved with the other
  settings in `~\.yt-audio-downloader\settings.json`.
- If a download fails, enable **Debug Mode** to see the full yt-dlp output.
- For age-restricted content, use browser cookies or a cookie file.
- The app saves a backup of the URLs in `~\.yt-audio-downloader\saved_urls.txt`
  (Windows) or `~/.yt-audio-downloader/saved_urls.txt` (Linux) and keeps
  yt-dlp updated in the same folder.

## Notes

- The binary files (ffmpeg, ffprobe, yt-dlp) are not included in the repository
  because they are too large for GitHub: download them and put them in
  `resources` before building.
