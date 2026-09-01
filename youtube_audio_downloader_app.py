#!/usr/bin/env python3
import os
import sys
import time
import customtkinter as ctk
import subprocess
import threading
from tkinter import messagebox, filedialog
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.error
import urllib.parse
import json
import queue
import shutil
import hashlib

APP_VERSION = "2.0.2"
NO_OUTPUT_TIMEOUT = 15 * 60  # seconds without any new output before a download is considered stuck
MAX_LOG_LINES = 2000  # maximum lines kept in the status log before the oldest ones are trimmed

# Optional SHA256 of the current bundled yt-dlp release, so the updater can
# refuse a binary that does not match it. Leave empty to skip this check and
# rely on the file-magic verification in _update_yt_dlp.
YT_DLP_EXPECTED_SHA256 = ""

# the folder containing the platform-specific resources/ directory; set by
# the per-platform launcher when running from source
_APP_DIR = None

FFMPEG_PATH = None


def set_app_dir(app_dir):
    global _APP_DIR
    _APP_DIR = app_dir


def find_resource(relative_path):
    # PyInstaller bundle: resources are in a temporary folder
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        # development: resources live next to the launcher script
        base_path = _APP_DIR

    return os.path.join(base_path, relative_path)


def binary_name(name):
    # 'ffmpeg' -> 'ffmpeg.exe' on Windows, 'ffmpeg' on Linux/macOS
    return name + '.exe' if sys.platform == 'win32' else name


def ensure_executable(path):
    # onefile bundles may not preserve the exec bit on extracted files
    if os.path.exists(path) and sys.platform != "win32":
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def find_ffmpeg():
    bundled = find_resource(os.path.join('resources', binary_name('ffmpeg')))
    if os.path.exists(bundled):
        ensure_executable(bundled)
        return bundled
    return shutil.which('ffmpeg') or binary_name('ffmpeg')


def _is_youtube_url(url):
    # accept only genuine YouTube hostnames, not arbitrary strings containing them
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except (ValueError, AttributeError):
        return False
    host = (parsed.hostname or '').lower()
    hosts = ('youtube.com', 'www.youtube.com', 'm.youtube.com',
             'youtube-nocookie.com', 'www.youtube-nocookie.com',
             'youtu.be', 'music.youtube.com', 'www.music.youtube.com')
    if host not in hosts:
        return False
    return parsed.scheme in ('http', 'https')


def terminate_process(process):
    # kill yt-dlp and (on Windows) its child processes such as ffmpeg
    if process.poll() is not None:
        return
    try:
        if sys.platform == 'win32':
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(process.pid)],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            process.terminate()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def download_media(url, is_playlist, log, yt_dlp_path, save_dir, browser, cookie_file, debug_mode, cancel_event, active_processes):
    process = None
    try:
        if cancel_event.is_set():
            log(f"Skipped (cancelled): {url}")
            return 'skipped'

        log(f"\nAnalyzing: {url}")
        output_template = (
            os.path.join(save_dir, '%(playlist)s', '%(title)s.%(ext)s')
            if is_playlist
            else os.path.join(save_dir, 'Single Songs', '%(title)s.%(ext)s')
        )

        command = [
            yt_dlp_path,
            '--format', 'bestaudio/best',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '192K',
            '--output', output_template,
            '--no-warnings',
            '--ignore-errors',
            '--socket-timeout', '60',
            '--retries', '15',
            '--fragment-retries', '15',
            '--extractor-retries', '10',
            '--throttled-rate', '100K',
            '--ffmpeg-location', FFMPEG_PATH,
            '--encoding', 'utf-8',
        ]
        if debug_mode:
            command.append('--verbose')
        else:
            # --progress/--newline keep output flowing so the stall watchdog works
            command.extend(['--quiet', '--progress', '--newline'])

        if cookie_file:
            command.extend(['--cookies', cookie_file])
        elif browser and browser.lower() != "none":
            command.extend(['--cookies-from-browser', browser.lower()])

        if not is_playlist:
            command.append('--no-playlist')

        command.append(url)

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        process = subprocess.Popen(command, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        with active_processes['lock']:
            active_processes['procs'].add(process)

        output_lines = []
        last_activity = [time.time()]

        def reader(pipe):
            for line in iter(pipe.readline, ''):
                output_lines.append(line)
                last_activity[0] = time.time()
            pipe.close()

        readers = [
            threading.Thread(target=reader, args=(process.stdout,), daemon=True),
            threading.Thread(target=reader, args=(process.stderr,), daemon=True),
        ]
        for reader_thread in readers:
            reader_thread.start()

        cancelled = False
        stalled = False
        while process.poll() is None:
            if cancel_event.is_set():
                cancelled = True
                terminate_process(process)
                break
            if time.time() - last_activity[0] > NO_OUTPUT_TIMEOUT:
                stalled = True
                terminate_process(process)
                break
            time.sleep(0.25)

        for reader_thread in readers:
            reader_thread.join(timeout=5)
        output = ''.join(output_lines)

        if cancelled:
            log(f"Download cancelled for: {url}")
            return 'cancelled'

        if stalled:
            log(f"Download stalled for {url}: no output for {NO_OUTPUT_TIMEOUT // 60} minutes, it was terminated.")
            return 'failed'

        if process.returncode != 0:
            error_message = output.strip()
            if error_message:
                log(f"yt-dlp reported an error for {url}:\n{error_message}")
            else:
                log(f"yt-dlp exited with code {process.returncode} for: {url}")
            return 'failed'

        # --ignore-errors lets yt-dlp exit 0 even when some items fail;
        # surface those failures instead of silently counting a success
        error_lines = [line.rstrip() for line in output_lines if 'ERROR:' in line]
        if error_lines:
            log(f"{len(error_lines)} yt-dlp error(s) while downloading {url}:")
            for line in error_lines[:20]:
                log(f"  {line}")
            return 'failed'

        return 'success'

    except Exception as e:
        log(f"Unexpected error for {url}: {e}")
        return 'failed'
    finally:
        if process is not None:
            with active_processes['lock']:
                active_processes['procs'].discard(process)


class Spinbox(ctk.CTkFrame):
    def __init__(self, master, from_=1, to=32, initial=12):
        super().__init__(master)
        self.from_ = from_
        self.to = to
        self.value = max(from_, min(to, int(initial)))
        self.minus_button = ctk.CTkButton(self, text="−", width=28, command=self.decrement)
        self.minus_button.grid(row=0, column=0, padx=(0, 2))
        self.entry = ctk.CTkEntry(self, width=66, justify="center")
        self.entry.grid(row=0, column=1, padx=(0, 2))
        self.plus_button = ctk.CTkButton(self, text="+", width=28, command=self.increment)
        self.plus_button.grid(row=0, column=2, padx=0)
        self.entry.insert(0, str(self.value))
        self.entry.bind("<FocusOut>", self._normalize)
        self.entry.bind("<Return>", self._normalize)

    def get(self):
        self._normalize()
        return self.value

    def _normalize(self, event=None):
        try:
            raw = self.entry.get().strip()
            parsed = self.from_ if raw == "" else int(raw)
        except ValueError:
            parsed = self.from_
        self.value = max(self.from_, min(self.to, parsed))
        self.entry.delete(0, "end")
        self.entry.insert(0, str(self.value))

    def increment(self):
        self._normalize()
        self.value = min(self.to, self.value + 1)
        self.entry.delete(0, "end")
        self.entry.insert(0, str(self.value))

    def decrement(self):
        self._normalize()
        self.value = max(self.from_, self.value - 1)
        self.entry.delete(0, "end")
        self.entry.insert(0, str(self.value))

    def set_state(self, state):
        for widget in (self.minus_button, self.plus_button):
            widget.configure(state=state)
        self.entry.configure(state=state)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"YouTube Audio Downloader v{APP_VERSION}")
        self.geometry("800x650")
        self.settings = self._load_settings()
        theme = self.settings.get('theme', 'Dark')
        mode = self.settings.get('mode', 'Playlist')
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.placeholder_playlist = "https://www.youtube.com/playlist?list=..."
        self.placeholder_single = "https://www.youtube.com/watch?v=..."
        self.placeholder_color = "gray50"
        self.text_color = ctk.ThemeManager.theme["CTkTextbox"]["text_color"]
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        self.controls_frame.grid_columnconfigure(2, weight=1)

        self.mode_label = ctk.CTkLabel(self.controls_frame, text="Mode")
        self.mode_label.grid(row=0, column=0, padx=(5,0), pady=(5,0), sticky="w")
        self.mode_selector = ctk.CTkComboBox(self.controls_frame, values=["Playlist", "Single Songs"], command=self.on_mode_change, state="readonly")
        self.mode_selector.set(mode)
        self.mode_selector.grid(row=1, column=0, padx=(5,10), pady=5, sticky="ew")

        self.browser_label = ctk.CTkLabel(self.controls_frame, text="Browser (for cookies)")
        self.browser_label.grid(row=0, column=1, padx=(5,0), pady=(5,0), sticky="w")
        self.browser_selector = ctk.CTkComboBox(self.controls_frame, values=["None", "Chrome", "Firefox", "Edge", "Opera", "Vivaldi", "Brave"], state="readonly")
        self.browser_selector.set("None")
        self.browser_selector.grid(row=1, column=1, padx=(5,10), pady=5, sticky="ew")

        self.url_label = ctk.CTkLabel(self.controls_frame, text="URLs to download (one per line)")
        self.url_label.grid(row=0, column=2, padx=5, pady=(5,0), sticky="w")
        self.url_text = ctk.CTkTextbox(self.controls_frame, height=120)
        self.url_text.grid(row=1, column=2, padx=5, pady=5, sticky="nsew")
        self.url_text.bind("<FocusIn>", self.on_entry_focus_in)
        self.url_text.bind("<FocusOut>", self.on_entry_focus_out)
        self.theme_switch = ctk.CTkSwitch(self.controls_frame, text="Dark Mode", command=self.toggle_theme)
        if theme.lower() == 'dark':
            self.theme_switch.select()
        else:
            self.theme_switch.deselect()
        self.theme_switch.grid(row=0, column=3, rowspan=2, padx=10, pady=5, sticky="e")
        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.status_widget = ctk.CTkTextbox(self.log_frame, state='disabled', corner_radius=0)
        self.status_widget.pack(expand=True, fill="both")

        self.path_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.path_frame.grid(row=2, column=0, padx=10, pady=(5,10), sticky="ew")
        self.path_frame.grid_columnconfigure(1, weight=1)
        path_label_title = ctk.CTkLabel(self.path_frame, text="Save to:")
        path_label_title.grid(row=0, column=0, padx=(5,10), pady=5, sticky="w")
        self.download_path = self.settings.get('download_path', os.path.join(os.path.expanduser('~'), 'Desktop', 'downloaded_music'))
        self.path_label = ctk.CTkLabel(self.path_frame, text=self.download_path, anchor="w", fg_color=ctk.ThemeManager.theme["CTkEntry"]["fg_color"], corner_radius=6, height=28)
        self.path_label.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_button = ctk.CTkButton(self.path_frame, text="Browse...", command=self.select_download_directory)
        self.browse_button.grid(row=0, column=2, padx=(10,5), pady=5, sticky="e")

        self.cookie_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.cookie_frame.grid(row=3, column=0, padx=10, pady=(5,10), sticky="ew")
        self.cookie_frame.grid_columnconfigure(1, weight=1)
        cookie_label_title = ctk.CTkLabel(self.cookie_frame, text="Cookie file (optional):")
        cookie_label_title.grid(row=0, column=0, padx=(5,10), pady=5, sticky="w")
        self.cookie_path_label = ctk.CTkLabel(self.cookie_frame, text="No file selected", anchor="w", fg_color=ctk.ThemeManager.theme["CTkEntry"]["fg_color"], corner_radius=6, height=28)
        self.cookie_path_label.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.clear_cookie_button = ctk.CTkButton(self.cookie_frame, text="Clear", width=60, command=self.clear_cookie_file, state="disabled")
        self.clear_cookie_button.grid(row=0, column=2, padx=(10,0), pady=5, sticky="e")
        self.browse_cookie_button = ctk.CTkButton(self.cookie_frame, text="Browse...", command=self.select_cookie_file)
        self.browse_cookie_button.grid(row=0, column=3, padx=(0,5), pady=5, sticky="e")
        self.cookie_file_path = None

        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_frame.grid(row=4, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        self.status_bar = ctk.CTkLabel(self.bottom_frame, text="Ready", anchor="w", height=28)
        self.status_bar.grid(row=0, column=0, columnspan=3, padx=(5,10), pady=5, sticky="ew")
        self.debug_mode_check = ctk.CTkCheckBox(self.bottom_frame, text="Debug Mode")
        self.debug_mode_check.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.cancel_button = ctk.CTkButton(self.bottom_frame, text="CANCEL", width=100, fg_color="#a91b1b", hover_color="#7c1414", command=self.cancel_download, state="disabled")
        self.cancel_button.grid(row=1, column=1, padx=5, pady=5, sticky="e")
        self.download_button = ctk.CTkButton(self.bottom_frame, text="START DOWNLOAD", command=self.start_download, height=40, font=("", 14, "bold"))
        self.download_button.grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.parallel_label = ctk.CTkLabel(self.bottom_frame, text="Parallel downloads")
        self.parallel_label.grid(row=2, column=0, padx=(5,5), pady=(0,5), sticky="w")
        self.max_workers_spin = Spinbox(self.bottom_frame, initial=int(self.settings.get('max_workers', 12)))
        self.max_workers_spin.grid(row=2, column=1, padx=(0,5), pady=(0,5), sticky="w")

        self.update_ui_for_mode(mode)

        # queues must exist before the update thread starts
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.active_processes = {'lock': threading.Lock(), 'procs': set()}
        self.yt_dlp_path = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.check_for_updates()
        self.process_log_queue()

    def on_mode_change(self, mode):
        self.update_ui_for_mode(mode)
        self.save_settings()

    def _load_settings(self):
        try:
            settings_path = os.path.join(os.path.expanduser('~'), '.yt-audio-downloader', 'settings.json')
            with open(settings_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(self):
        try:
            settings_dir = os.path.join(os.path.expanduser('~'), '.yt-audio-downloader')
            os.makedirs(settings_dir, exist_ok=True)
            settings_path = os.path.join(settings_dir, 'settings.json')
            theme = "Dark" if self.theme_switch.get() == 1 else "Light"
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'theme': theme,
                    'mode': self.mode_selector.get(),
                    'download_path': self.download_path,
                    'max_workers': self.max_workers_spin.get(),
                }, f, indent=2)
        except Exception as e:
            self.log(f"Error saving settings: {e}")

    def select_download_directory(self):
        path = filedialog.askdirectory(
            title="Select download folder",
            initialdir=self.download_path
        )
        if path:
            self.download_path = path
            self.path_label.configure(text=self.download_path)
            self.save_settings()

    def select_cookie_file(self):
        path = filedialog.askopenfilename(
            title="Select the cookie file",
            filetypes=[("All files", "*.*"), ("SQLite files", "*.sqlite"), ("Text files", "*.txt")]
        )
        if path:
            self.cookie_file_path = path
            self.cookie_path_label.configure(text=path)
            # a cookie file takes precedence over the browser cookies
            self.browser_selector.configure(state="disabled")
            self.clear_cookie_button.configure(state="normal")

    def clear_cookie_file(self):
        self.cookie_file_path = None
        self.cookie_path_label.configure(text="No file selected")
        self.clear_cookie_button.configure(state="disabled")
        self.browser_selector.configure(state="readonly")

    def _update_yt_dlp(self):
        # in a bundle use the bundled copy (then update it if possible);
        # in development use the one in the PATH
        if not getattr(sys, 'frozen', False):
            self.log("Development mode: yt-dlp update is not managed.")
            self.yt_dlp_path = binary_name('yt-dlp')
            self.set_status("Ready (Development Mode)")
            return

        home_dir = os.path.expanduser("~")
        yt_dlp_dir = os.path.join(home_dir, ".yt-audio-downloader")
        os.makedirs(yt_dlp_dir, exist_ok=True)
        self.yt_dlp_path = os.path.join(yt_dlp_dir, binary_name('yt-dlp'))
        tmp_path = self.yt_dlp_path + '.tmp'

        # seed the local copy from the bundled one only if there is nothing yet;
        # never overwrite a newer copy downloaded on a previous run
        bundled = find_resource(os.path.join('resources', binary_name('yt-dlp')))
        if not os.path.exists(self.yt_dlp_path) and os.path.exists(bundled):
            try:
                shutil.copyfile(bundled, self.yt_dlp_path)
                ensure_executable(self.yt_dlp_path)
                self.log("Extracted the bundled yt-dlp copy as base version.")
            except OSError as e:
                self.log(f"Could not extract the bundled yt-dlp copy: {e}")

        try:
            # latest version available on GitHub
            request = urllib.request.Request(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                headers={"User-Agent": f"YouTubeAudioDownloader/{APP_VERSION}"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read())

            asset = next((a for a in data["assets"] if a['name'] == binary_name('yt-dlp')), None)
            if not asset:
                self.log(f"Could not find '{binary_name('yt-dlp')}' in the latest release.")
                self.set_status("Update error: asset not found.")
                return

            latest_version = data["tag_name"]

            # if the local copy is already the latest, skip the download;
            # also keep the existing copy if its version cannot be read,
            # instead of re-downloading it on every startup
            if os.path.exists(self.yt_dlp_path):
                local_version = self._local_yt_dlp_version()
                if local_version == latest_version:
                    self.log(f"yt-dlp is already up to date (version {latest_version}).")
                    self.set_status("Ready")
                    return
                if not local_version:
                    self.log("Could not read the local yt-dlp version, keeping the existing copy.")
                    self.set_status("Ready")
                    return

            asset_url = asset["browser_download_url"]
            self.log(f"Found version {latest_version}. Downloading from {asset_url}...")

            # download to a temp file first, then verify integrity before replacing
            request = urllib.request.Request(asset_url, headers={"User-Agent": f"YouTubeAudioDownloader/{APP_VERSION}"})
            sha256 = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=60) as response, open(tmp_path, 'wb') as out_file:
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    sha256.update(chunk)

            # verify the downloaded binary is a valid executable before shipping it
            expected_header = b'MZ' if sys.platform == 'win32' else b'\x7fELF'
            try:
                with open(tmp_path, 'rb') as f:
                    magic = f.read(len(expected_header))
            except OSError as e:
                magic = b''
                self.log(f"Could not read the downloaded yt-dlp for verification: {e}")
            actual_sha = sha256.hexdigest()
            if magic != expected_header:
                self.log("Downloaded yt-dlp failed integrity check (bad file magic). Discarding update.")
                self.set_status("Update failed: integrity check failed.")
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return
            # enforce a known-good checksum when one is embedded at build time
            if YT_DLP_EXPECTED_SHA256 and actual_sha != YT_DLP_EXPECTED_SHA256:
                self.log("Downloaded yt-dlp failed checksum verification. Discarding update.")
                self.set_status("Update failed: checksum mismatch.")
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return
            if actual_sha == asset.get("digest"):
                self.log(f"Verified checksum {actual_sha}.")
            else:
                self.log(f"Downloaded yt-dlp (sha={actual_sha}) - no known checksum to compare against.")

            os.replace(tmp_path, self.yt_dlp_path)
            ensure_executable(self.yt_dlp_path)

            self.log(f"yt-dlp updated successfully to version {latest_version}.")
            self.set_status("Ready")

        except Exception as e:
            if isinstance(e, urllib.error.URLError) and "getaddrinfo failed" in str(e):
                self.log("Could not connect to update servers. Check your internet connection.")
            else:
                self.log(f"Error while updating yt-dlp: {e}")
            self.log("If a previous version exists, it will be used.")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            if not os.path.exists(self.yt_dlp_path):
                self.set_status("Update error. Check your connection.")
                self.yt_dlp_path = None
            else:
                self.set_status("Ready (offline)")

    def check_for_updates(self):
        update_thread = threading.Thread(target=self._update_yt_dlp, daemon=True)
        update_thread.start()

    def _local_yt_dlp_version(self):
        try:
            result = subprocess.run([self.yt_dlp_path, "--version"], capture_output=True, text=True, timeout=20)
            return result.stdout.strip()
        except Exception:
            return ""

    def toggle_theme(self):
        mode = "dark" if self.theme_switch.get() == 1 else "light"
        ctk.set_appearance_mode(mode)
        self.save_settings()

    def is_placeholder_text(self, text):
        return text == self.placeholder_playlist or text == self.placeholder_single

    def on_entry_focus_in(self, event):
        current_text = self.url_text.get("1.0", "end-1c").strip()
        if self.is_placeholder_text(current_text):
            self.url_text.delete("1.0", "end")
            self.url_text.configure(text_color=self.text_color)

    def on_entry_focus_out(self, event):
        if not self.url_text.get("1.0", "end-1c").strip():
            self.put_placeholder(self.mode_selector.get())

    def put_placeholder(self, mode):
        self.url_text.configure(text_color=self.placeholder_color)
        self.url_text.delete("1.0", "end")
        placeholder = self.placeholder_playlist if mode == "Playlist" else self.placeholder_single
        self.url_text.insert("1.0", placeholder)

    def update_ui_for_mode(self, mode):
        focused_widget = self.focus_get()
        internal_textbox = getattr(self.url_text, '_textbox', None)
        if focused_widget is not None and (focused_widget is self.url_text or focused_widget is internal_textbox):
            return
        current_text = self.url_text.get("1.0", "end-1c").strip()
        if not current_text or self.is_placeholder_text(current_text):
            self.put_placeholder(mode)

    def set_status(self, message):
        # through a queue so it is safe to call from background threads
        self.status_queue.put(message)

    def process_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.status_widget.configure(state='normal')
                self.status_widget.insert("end", message + "\n")
                self.status_widget.configure(state='disabled')
                self.status_widget.see("end")
        except queue.Empty:
            pass
        try:
            while True:
                message = self.status_queue.get_nowait()
                self.status_bar.configure(text=message)
        except queue.Empty:
            pass
        line_count = int(self.status_widget.index("end-1c").split('.')[0])
        if line_count > MAX_LOG_LINES:
            self.status_widget.configure(state='normal')
            self.status_widget.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")
            self.status_widget.configure(state='disabled')
        self.after(100, self.process_log_queue)

    def log(self, message):
        self.log_queue.put(message)

    def save_urls_to_file(self, urls):
        try:
            target_dir = os.path.join(os.path.expanduser('~'), '.yt-audio-downloader')
            os.makedirs(target_dir, exist_ok=True)
            target_file = os.path.join(target_dir, 'saved_urls.txt')
            with open(target_file, 'w', encoding='utf-8') as f:
                for url in urls:
                    f.write(url + "\n")
            self.log(f"URLs saved to file {target_file}")
        except Exception as e:
            self.log(f"Error saving to file: {e}")

    def cancel_download(self):
        if messagebox.askyesno("Cancel download", "Stop all running and pending downloads?"):
            self.cancel_event.set()
            self.set_status("Cancelling...")

    def _terminate_all_processes(self):
        with self.active_processes['lock']:
            procs = list(self.active_processes['procs'])
        for process in procs:
            terminate_process(process)

    def on_close(self):
        with self.active_processes['lock']:
            running = bool(self.active_processes['procs'])
        if running:
            proceed = messagebox.askyesno("Exit", "Downloads are still running. Exit and terminate them?")
            if not proceed:
                return
            self.cancel_event.set()
            self._terminate_all_processes()
        self.save_settings()
        self.destroy()

    def start_download(self):
        if getattr(sys, 'frozen', False) and (not self.yt_dlp_path or not os.path.exists(self.yt_dlp_path)):
            messagebox.showerror("Error: yt-dlp not found",
                                 f"The '{binary_name('yt-dlp')}' executable was not found.\n\n"
                                 "Check your internet connection and restart the app "
                                 "to allow it to download automatically.")
            self.set_controls_state("normal")
            self.set_status(f"Failed: {binary_name('yt-dlp')} not found.")
            return

        current_text = self.url_text.get("1.0", "end-1c").strip()
        if not current_text or self.is_placeholder_text(current_text):
            messagebox.showwarning("No URL", "Enter at least one valid YouTube URL.")
            return
        raw_urls = [line.strip() for line in current_text.splitlines() if line.strip()]
        urls = list(dict.fromkeys(raw_urls))
        duplicates = len(raw_urls) - len(urls)
        if duplicates:
            self.log(f"Removed {duplicates} duplicate URL(s).")
        filtered_urls = [url for url in urls if _is_youtube_url(url)]
        invalid = len(urls) - len(filtered_urls)
        if invalid:
            self.log(f"Removed {invalid} line(s) that are not YouTube URLs.")
        urls = filtered_urls
        if not urls:
            messagebox.showwarning("No valid URLs", "The entered text does not contain valid YouTube URLs.")
            return
        self.save_urls_to_file(urls)
        is_playlist = self.mode_selector.get() == "Playlist"
        browser = self.browser_selector.get()
        cookie_file = self.cookie_file_path
        debug_mode = self.debug_mode_check.get()
        max_workers = self.max_workers_spin.get()

        save_dir = self.download_path
        os.makedirs(save_dir, exist_ok=True)

        if not is_playlist:
            os.makedirs(os.path.join(save_dir, "Single Songs"), exist_ok=True)

        self.log(f"\n--- Starting download in mode: {'Playlist' if is_playlist else 'Single Songs'} ---")
        if cookie_file:
            self.log(f"Using cookie file: {cookie_file}")
        elif browser != "None":
            self.log(f"Using cookies from browser: {browser}")
        self.log(f"Files will be saved to: {save_dir}")
        self.log(f"Parallel downloads: {max_workers}")
        self.cancel_event.clear()
        self.set_controls_state("disabled")
        self.cancel_button.configure(state="normal")
        self.set_status("Downloading...")

        # in development mode the update thread may not have set yt_dlp_path yet
        yt_dlp_path = self.yt_dlp_path or binary_name('yt-dlp')

        result_queue = queue.Queue()
        thread = threading.Thread(
            target=self.run_download_logic,
            args=(urls, is_playlist, yt_dlp_path, save_dir, browser, cookie_file, debug_mode, max_workers, result_queue),
            daemon=True
        )
        thread.start()
        self.after(100, self.check_thread, thread, result_queue)

    def run_download_logic(self, urls, is_playlist, yt_dlp_path, save_dir, browser, cookie_file, debug_mode, max_workers, result_queue):
        log = self.log
        total_success = 0
        processed = 0
        skipped = 0
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_url = {
                    executor.submit(download_media, url, is_playlist, log, yt_dlp_path, save_dir, browser, cookie_file, debug_mode, self.cancel_event, self.active_processes): url
                    for url in urls
                }
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        result = future.result()
                        if result == 'success':
                            log(f"Download completed successfully for: {url}")
                            total_success += 1
                            processed += 1
                        elif result == 'skipped':
                            # already logged inside download_media
                            skipped += 1
                        elif result == 'cancelled':
                            # already logged inside download_media
                            processed += 1
                        elif result == 'failed':
                            log(f"Download failed for: {url}")
                            processed += 1
                        else:
                            log(f"Unexpected result for {url}: {result}")
                            processed += 1
                    except Exception as exc:
                        log(f"Error downloading {url}: {exc}")
                        processed += 1
            result_queue.put((total_success, processed, skipped, len(urls)))
        except Exception as exc:
            log(f"Critical error in thread: {exc}")
            result_queue.put((0, 0, 0, len(urls)))

    def check_thread(self, thread, result_queue):
        if thread.is_alive() and result_queue.empty():
            self.after(100, self.check_thread, thread, result_queue)
            return
        try:
            total_success, processed, skipped, total_urls = result_queue.get_nowait()
            if self.cancel_event.is_set():
                self.log(f"\n--- OPERATION CANCELLED ---\n   Downloads completed successfully: {total_success}\n   Downloads started: {processed}\n   Skipped before starting: {skipped}\n---------------------------------")
                self.set_status(f"Cancelled: {total_success}/{total_urls} downloads completed.")
                messagebox.showwarning("Cancelled", "The download was cancelled. Check the status window for details.")
            else:
                self.log(f"\n--- OPERATION COMPLETED ---\n   URLs processed: {processed}\n   Downloads completed successfully: {total_success}\n---------------------------------")
                self.set_status(f"Completed: {total_success}/{total_urls} downloads.")
                messagebox.showinfo("Done!", "Download completed. Check the status window for details.")
        except queue.Empty:
            self.log("Critical error in thread: the download finished without a result.")
            self.set_status("Critical error.")
            messagebox.showerror("Critical Error", "An error occurred during the download.")
        finally:
            self.set_controls_state("normal")

    def set_controls_state(self, state):
        for widget in [self.download_button, self.mode_selector, self.browser_selector, self.url_text, self.theme_switch, self.browse_button, self.browse_cookie_button]:
            widget.configure(state=state)
        self.max_workers_spin.set_state(state)
        if state == "normal":
            # restore the proper non-editable combobox states and the
            # cookie/browser mutual exclusion
            self.mode_selector.configure(state="readonly")
            self.browser_selector.configure(state="disabled" if self.cookie_file_path else "readonly")
            self.clear_cookie_button.configure(state="normal" if self.cookie_file_path else "disabled")
            self.cancel_button.configure(state="disabled")


def run_app(app_dir):
    global FFMPEG_PATH
    set_app_dir(app_dir)
    FFMPEG_PATH = find_ffmpeg()
    ensure_executable(find_resource(os.path.join('resources', binary_name('ffprobe'))))
    app = App()
    app.mainloop()


if __name__ == "__main__":
    run_app(app_dir=os.path.dirname(os.path.abspath(__file__)))