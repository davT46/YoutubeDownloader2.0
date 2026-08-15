#!/usr/bin/env python3
import os
import sys
import customtkinter as ctk
import subprocess
import threading
from tkinter import messagebox, filedialog
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import json
import queue
import shutil

def find_resource(relative_path):
    # PyInstaller bundle: resources are in a temporary folder
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        # development: relative to the script
        base_path = os.path.dirname(os.path.abspath(__file__))

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

FFMPEG_PATH = find_ffmpeg()
ensure_executable(find_resource(os.path.join('resources', binary_name('ffprobe'))))

class MyLogger:
    def __init__(self, app):
        self.app = app
    def debug(self, msg):
        if not msg.startswith('[debug]'):
            self.log(msg)
    def warning(self, msg):
        self.log(f"WARNING: {msg}")
    def error(self, msg):
        self.log(f"ERROR: {msg}")
    def log(self, msg):
        self.app.log(msg)

def download_media(url, is_playlist, logger, yt_dlp_path, save_dir, browser, cookie_file, debug_mode):
    try:
        logger.log(f"\nAnalyzing: {url}")
        output_template = (
            os.path.join(save_dir, '%(playlist)s', '%(title)s.%(ext)s')
            if is_playlist
            else os.path.join(save_dir, 'Single Songs', '%(title)s.%(ext)s')
        )

        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

        command = [
            yt_dlp_path,
            '--rm-cache-dir',
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
            '--user-agent', user_agent,
            '--ffmpeg-location', FFMPEG_PATH,
            '--encoding', 'utf-8',
        ]
        if debug_mode:
            command.append('--verbose')
        else:
            command.append('--quiet')

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
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            error_message = stderr.strip() or stdout.strip()
            if error_message:
                logger.log(f"yt-dlp output for {url}: {error_message}")
            return False

        return True

    except Exception as e:
        logger.log(f"Unexpected error for {url}: {e}")
        return False

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Audio Downloader")
        self.geometry("800x650")
        ctk.set_appearance_mode("Dark")
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
        self.mode_selector = ctk.CTkComboBox(self.controls_frame, values=["Playlist", "Single Songs"], command=self.update_ui_for_mode, state="readonly")
        self.mode_selector.set("Playlist")
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
        self.theme_switch.select()
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
        self.download_path = os.path.join(os.path.expanduser('~'), 'Desktop', 'downloaded_music')
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
        self.browse_cookie_button = ctk.CTkButton(self.cookie_frame, text="Browse...", command=self.select_cookie_file)
        self.browse_cookie_button.grid(row=0, column=2, padx=(10,5), pady=5, sticky="e")
        self.cookie_file_path = None

        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.bottom_frame.grid(row=4, column=0, padx=10, pady=(5, 10), sticky="ew")
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        self.status_bar = ctk.CTkLabel(self.bottom_frame, text="Ready", anchor="w", height=28)
        self.status_bar.grid(row=0, column=0, columnspan=2, padx=(5,10), pady=5, sticky="ew")
        self.debug_mode_check = ctk.CTkCheckBox(self.bottom_frame, text="Debug Mode")
        self.debug_mode_check.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.download_button = ctk.CTkButton(self.bottom_frame, text="START DOWNLOAD", command=self.start_download, height=40, font=("", 14, "bold"))
        self.download_button.grid(row=1, column=1, padx=5, pady=5, sticky="e")

        self.update_ui_for_mode("Playlist")

        # queues must exist before the update thread starts
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.yt_dlp_path = None
        self.check_for_updates()
        self.process_log_queue()

    def select_download_directory(self):
        path = filedialog.askdirectory(
            title="Select download folder",
            initialdir=self.download_path
        )
        if path:
            self.download_path = path
            self.path_label.configure(text=self.download_path)

    def select_cookie_file(self):
        path = filedialog.askopenfilename(
            title="Select the cookie file",
            filetypes=[("All files", "*.*"), ("SQLite files", "*.sqlite"), ("Text files", "*.txt")]
        )
        if path:
            self.cookie_file_path = path
            self.cookie_path_label.configure(text=path)

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

        # if the bundle ships a copy of yt-dlp, extract it as the base version
        bundled = find_resource(os.path.join('resources', binary_name('yt-dlp')))
        if os.path.exists(bundled):
            shutil.copyfile(bundled, self.yt_dlp_path)
            if sys.platform != "win32":
                os.chmod(self.yt_dlp_path, 0o755)
            self.log("yt-dlp ready (bundled copy).")
            self.set_status("Ready")
        else:
            self.log("Checking for the latest yt-dlp version...")
            self.set_status("Checking for yt-dlp updates...")

        try:
            # latest version available on GitHub
            request = urllib.request.Request(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                headers={"User-Agent": "YouTubeAudioDownloader/2.0"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read())

            asset = next((a for a in data["assets"] if a['name'] == binary_name('yt-dlp')), None)
            if not asset:
                self.log(f"Could not find '{binary_name('yt-dlp')}' in the latest release.")
                self.set_status("Update error: asset not found.")
                return

            latest_version = data["tag_name"]

            # if the local copy is already the latest, skip the download
            if self._local_yt_dlp_version() == latest_version:
                self.log(f"yt-dlp is already up to date (version {latest_version}).")
                self.set_status("Ready")
                return

            asset_url = asset["browser_download_url"]
            self.log(f"Found version {latest_version}. Downloading from {asset_url}...")

            request = urllib.request.Request(asset_url, headers={"User-Agent": "YouTubeAudioDownloader/2.0"})
            with urllib.request.urlopen(request, timeout=60) as response, open(self.yt_dlp_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)

            if sys.platform != "win32":
                os.chmod(self.yt_dlp_path, 0o755)

            self.log(f"yt-dlp updated successfully to version {latest_version}.")
            self.set_status("Ready")

        except Exception as e:
            if isinstance(e, urllib.error.URLError) and "getaddrinfo failed" in str(e):
                self.log("Could not connect to update servers. Check your internet connection.")
            else:
                self.log(f"Error while updating yt-dlp: {e}")
            self.log("If a previous version exists, it will be used.")
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
        if self.focus_get() == self.url_text:
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
        urls = [line.strip() for line in current_text.splitlines() if line.strip()]
        if not urls:
            messagebox.showwarning("No valid URLs", "The entered text does not contain valid YouTube URLs.")
            return
        self.save_urls_to_file(urls)
        is_playlist = self.mode_selector.get() == "Playlist"
        browser = self.browser_selector.get()
        cookie_file = self.cookie_file_path
        debug_mode = self.debug_mode_check.get()

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
        self.set_controls_state("disabled")
        self.set_status("Downloading...")

        # in development mode the update thread may not have set yt_dlp_path yet
        yt_dlp_path = self.yt_dlp_path or binary_name('yt-dlp')

        result_queue = queue.Queue()
        thread = threading.Thread(
            target=self.run_download_logic,
            args=(urls, is_playlist, yt_dlp_path, save_dir, browser, cookie_file, debug_mode, result_queue),
            daemon=True
        )
        thread.start()
        self.after(100, self.check_thread, thread, result_queue)

    def run_download_logic(self, urls, is_playlist, yt_dlp_path, save_dir, browser, cookie_file, debug_mode, result_queue):
        logger = MyLogger(self)
        total_success = 0
        try:
            with ThreadPoolExecutor(max_workers=12) as executor:
                future_to_url = {
                    executor.submit(download_media, url, is_playlist, logger, yt_dlp_path, save_dir, browser, cookie_file, debug_mode): url
                    for url in urls
                }
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        success = future.result()
                        if success:
                            logger.log(f"Download completed successfully for: {url}")
                            total_success += 1
                        else:
                            logger.log(f"Download failed for: {url}")
                    except Exception as exc:
                        logger.log(f"Error downloading {url}: {exc}")
            result_queue.put((total_success, len(urls)))
        except Exception as exc:
            logger.log(f"Critical error in thread: {exc}")
            result_queue.put((0, len(urls)))

    def check_thread(self, thread, result_queue):
        if thread.is_alive() and result_queue.empty():
            self.after(100, self.check_thread, thread, result_queue)
            return
        try:
            total_success, total_urls = result_queue.get_nowait()
            self.log(f"\n--- OPERATION COMPLETED ---\n   URLs processed: {total_urls}\n   Downloads started successfully: {total_success}\n---------------------------------")
            self.set_status(f"Completed: {total_success}/{total_urls} downloads started.")
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

if __name__ == "__main__":
    app = App()
    app.mainloop()
