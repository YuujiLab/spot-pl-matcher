import json
import logging
import os
import queue
import threading
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import main as converter


class SpotApiLogger:
    @staticmethod
    def info(s: str, **extra):
        logging.getLogger("spotify_playlist_scraper").info(s, extra=extra or None)

    @staticmethod
    def attempt(s: str, **extra):
        logging.getLogger("spotify_playlist_scraper").info(s, extra=extra or None)

    @staticmethod
    def error(s: str, **extra):
        logging.getLogger("spotify_playlist_scraper").error(s, extra=extra or None)

    @staticmethod
    def fatal(s: str, **extra):
        logging.getLogger("spotify_playlist_scraper").critical(s, extra=extra or None)


class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue[str]):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


class PlaylistConverterGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Spotify Playlist Converter")
        self.geometry("920x680")
        self.minsize(820, 580)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.current_output_path: Path | None = None
        self.current_raw_path: Path | None = None
        self.viewer_path = Path(__file__).with_name("gui-viewer.py")

        self._configure_style()
        self._configure_logging()
        self._build_ui()
        self.after(100, self._drain_log_queue)

    def _configure_style(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("App.TFrame", background="#111827")
        style.configure("Header.TFrame", background="#0f172a")
        style.configure("Card.TFrame", background="#111827")
        style.configure("App.TLabel", background="#111827", foreground="#e5e7eb")
        style.configure("Header.TLabel", background="#0f172a", foreground="#f8fafc")
        style.configure("Muted.TLabel", background="#111827", foreground="#9ca3af")
        style.configure("Accent.TButton", padding=(14, 8))
        style.configure("TButton", padding=(12, 8))
        style.configure("TLabelframe", background="#111827", foreground="#e5e7eb")
        style.configure("TLabelframe.Label", background="#111827", foreground="#e5e7eb")
        style.configure(
            "TEntry",
            fieldbackground="#1f2937",
            foreground="#f9fafb",
            insertcolor="#f9fafb",
        )
        style.configure("TCheckbutton", background="#111827", foreground="#e5e7eb")
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#1f2937",
            background="#22c55e",
            bordercolor="#1f2937",
            lightcolor="#22c55e",
            darkcolor="#22c55e",
        )

        self.configure(background="#111827")

    def _configure_logging(self):
        self.logger = logging.getLogger("spotify_playlist_scraper")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        self.logger.addHandler(handler)

    def _build_ui(self):
        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 18))
        header.pack(fill=tk.X)

        ttk.Label(
            header,
            text="Spotify Playlist Converter",
            style="Header.TLabel",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Paste a playlist URL, choose export settings, and convert in the background.",
            style="Header.TLabel",
            font=("Segoe UI", 10),
        ).pack(anchor=tk.W, pady=(4, 0))

        body = ttk.Frame(self, style="App.TFrame", padding=20)
        body.pack(fill=tk.BOTH, expand=True)

        form = ttk.LabelFrame(body, text="Conversion Settings", padding=16)
        form.pack(fill=tk.X)

        self.url_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.cookie_var = tk.StringVar(value="cookies.json")
        self.keep_raw_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        ttk.Label(form, text="Playlist URL", style="App.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        self.url_entry = ttk.Entry(form, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        ttk.Label(form, text="Output Directory", style="App.TLabel").grid(row=2, column=0, sticky=tk.W, pady=(0, 6))
        output_row = ttk.Frame(form, style="Card.TFrame")
        output_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_dir_var)
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(output_row, text="Browse", command=self._choose_output_dir).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(form, text="Cookies JSON", style="App.TLabel").grid(row=4, column=0, sticky=tk.W, pady=(0, 6))
        cookie_row = ttk.Frame(form, style="Card.TFrame")
        cookie_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.cookie_entry = ttk.Entry(cookie_row, textvariable=self.cookie_var)
        self.cookie_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(cookie_row, text="Browse", command=self._choose_cookie_file).pack(side=tk.LEFT, padx=(10, 0))

        options_row = ttk.Frame(form, style="Card.TFrame")
        options_row.grid(row=6, column=0, columnspan=2, sticky="ew")
        ttk.Checkbutton(options_row, text="Keep raw dump", variable=self.keep_raw_var).pack(side=tk.LEFT)

        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=0)

        controls = ttk.Frame(body, style="App.TFrame", padding=(0, 16, 0, 8))
        controls.pack(fill=tk.X)

        self.convert_button = ttk.Button(controls, text="Convert Playlist", style="Accent.TButton", command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT)
        ttk.Button(controls, text="Clear Log", command=self._clear_log).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="Open Output Folder", command=self._open_output_folder).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="Open in Viewer", command=self._open_in_viewer).pack(side=tk.LEFT, padx=(10, 0))

        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=220)
        self.progress.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(16, 0))

        status_row = ttk.Frame(body, style="App.TFrame")
        status_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(status_row, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.LEFT)

        log_box = ttk.LabelFrame(body, text="Activity Log", padding=10)
        log_box.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(
            log_box,
            height=18,
            wrap=tk.WORD,
            bg="#0b1220",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief=tk.FLAT,
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state=tk.DISABLED)

    def _choose_output_dir(self):
        directory = filedialog.askdirectory(
            title="Choose output directory",
        )
        if directory:
            self.output_dir_var.set(directory)

    def _choose_cookie_file(self):
        filename = filedialog.askopenfilename(
            title="Choose cookies JSON file",
            filetypes=[("JSON Files", "*.json")],
        )
        if filename:
            self.cookie_var.set(filename)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _append_log(self, message: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _queue_log(self, message: str):
        self.log_queue.put(message)

    def _drain_log_queue(self):
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(message)
        self.after(100, self._drain_log_queue)

    def _set_busy(self, busy: bool):
        self.convert_button.configure(state=tk.DISABLED if busy else tk.NORMAL)
        if busy:
            self.progress.start(12)
            self.status_var.set("Converting...")
        else:
            self.progress.stop()
            self.status_var.set("Ready")

    def _open_output_folder(self):
        target_path = self.current_output_path or (
            Path(self.output_dir_var.get()) if self.output_dir_var.get() else None
        )
        if target_path is None:
            messagebox.showinfo("Open Output Folder", "No output file has been generated yet.")
            return

        folder = target_path.parent if target_path.is_file() else target_path
        if not folder.exists():
            messagebox.showinfo("Open Output Folder", f"Folder does not exist:\n{folder}")
            return

        try:
            import os

            os.startfile(folder)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Open Output Folder", f"Could not open folder:\n{exc}")

    def _open_in_viewer(self):
        if not self.current_output_path or not self.current_output_path.exists():
            messagebox.showinfo("Open in Viewer", "Convert a playlist first so there is a JSON file to open.")
            return

        if not self.viewer_path.exists():
            messagebox.showerror("Open in Viewer", f"Could not find gui-viewer.py next to this file:\n{self.viewer_path}")
            return

        try:
            subprocess.Popen([sys.executable, str(self.viewer_path), str(self.current_output_path)], cwd=str(self.viewer_path.parent))
        except Exception as exc:
            messagebox.showerror("Open in Viewer", f"Could not launch viewer:\n{exc}")

    def _fetch_playlist_handler(self, playlist_id: str, cookie_path: str):
        public_handler = converter.PublicPlaylist(playlist_id)
        public_info = public_handler.get_playlist_info(limit=25)

        if converter.has_playlist_content(public_info):
            return public_handler, public_info

        auth_client = self._load_authenticated_client(cookie_path)
        if auth_client is not None:
            authenticated_handler = converter.PublicPlaylist(playlist_id, client=auth_client)
            authenticated_info = authenticated_handler.get_playlist_info(limit=25)
            if converter.has_playlist_content(authenticated_info):
                self._queue_log("INFO: Public response was incomplete; using cookies for authenticated access.")
                return authenticated_handler, authenticated_info

            message = converter.get_deep(authenticated_info, ["data", "playlistV2", "message"])
            raise RuntimeError(message or "Authenticated playlist response did not include track content.")

        message = converter.get_deep(public_info, ["data", "playlistV2", "message"])
        raise RuntimeError(
            message
            or "Playlist response did not include track content. Add cookies.json if this playlist is private or gated."
        )

    def _load_authenticated_client(self, cookie_path: str):
        cookie_file = Path(cookie_path)
        if not cookie_file.exists():
            return None

        try:
            with cookie_file.open("r", encoding="utf-8") as file_handle:
                cookie_list = json.load(file_handle)
        except Exception as exc:
            raise RuntimeError(f"Failed to read cookies file: {exc}") from exc

        cookie_dict = {cookie["name"]: cookie["value"] for cookie in cookie_list}
        cfg = converter.Config(logger=SpotApiLogger)
        session = converter.Login.from_cookies(
            {
                "identifier": "spotify_playlist_scraper",
                "cookies": cookie_dict,
                "password": "",
            },
            cfg,
        )
        return session.client

    def start_conversion(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Convert Playlist", "A conversion is already running.")
            return

        playlist_url = self.url_var.get().strip()
        if not playlist_url:
            messagebox.showerror("Convert Playlist", "Paste a Spotify playlist URL first.")
            return

        try:
            playlist_id = converter.extract_playlist_id(playlist_url)
        except Exception as exc:
            messagebox.showerror("Convert Playlist", str(exc))
            return

        keep_raw = self.keep_raw_var.get()
        cookie_path = self.cookie_var.get().strip() or "cookies.json"

        output_dir_text = self.output_dir_var.get().strip()
        output_dir = Path(output_dir_text) if output_dir_text else Path.cwd()
        if output_dir.exists() and output_dir.is_file():
            messagebox.showerror("Convert Playlist", "Choose a directory for the output location, not a file.")
            return

        self._set_busy(True)
        self._queue_log(f"INFO: Starting conversion for playlist {playlist_id}")

        self.worker_thread = threading.Thread(
            target=self._convert_playlist_worker,
            args=(playlist_id, output_dir_text, cookie_path, keep_raw),
            daemon=True,
        )
        self.worker_thread.start()

    def _convert_playlist_worker(self, playlist_id: str, output_dir_text: str, cookie_path: str, keep_raw: bool):
        try:
            handler, playlist_info = self._fetch_playlist_handler(playlist_id, cookie_path)
            playlist_data = converter.extract_playlist_details(playlist_info)
            output_dir = Path(output_dir_text) if output_dir_text else Path.cwd()
            output_dir.mkdir(parents=True, exist_ok=True)
            raw_output_path = output_dir / converter.build_raw_path(playlist_data["playlist_info"]["name"])
            output_path = output_dir / converter.build_output_path(playlist_data["playlist_info"]["name"])

            raw_dump = {
                "raw_playlist_metadata": playlist_info,
                "raw_track_chunks": [],
            }

            self._queue_log(f"INFO: Playlist name: {playlist_data['playlist_info']['name']}")
            self._queue_log(f"INFO: Output directory: {output_dir}")
            self._queue_log(f"INFO: API total tracks reported: {playlist_data['playlist_info']['total_tracks']}")

            processed_count = 0
            skipped_count = 0

            for chunk_index, chunk in enumerate(converter.iterate_playlist_chunks(handler), start=1):
                items = chunk.get("items", [])
                self._queue_log(f"INFO: Processing chunk {chunk_index} with {len(items)} items")
                raw_dump["raw_track_chunks"].append(chunk)

                for entry in items:
                    track = converter.extract_track_details(entry)
                    if track:
                        playlist_data["tracks"].append(track)
                        processed_count += 1
                    else:
                        skipped_count += 1

            playlist_data["playlist_info"]["created_at"] = converter.get_earliest_timestamp(
                [track.get("added_to_playlist") for track in playlist_data["tracks"]]
            )
            playlist_data["playlist_info"]["total_tracks"] = processed_count

            converter.save_json_file(raw_output_path, raw_dump)
            converter.save_json_file(output_path, playlist_data)

            self.current_output_path = output_path
            self.current_raw_path = raw_output_path

            if not keep_raw:
                converter.delete_file_if_exists(raw_output_path)
                raw_message = f"INFO: Removed temporary raw dump: {raw_output_path}"
            else:
                raw_message = f"INFO: Kept raw dump: {raw_output_path}"

            summary_lines = [
                f"SUCCESS: Saved complete playlist data to {output_path}",
                f"SUCCESS: Saved raw playlist dump to {raw_output_path}",
                raw_message,
                f"INFO: Processed {processed_count} tracks, skipped {skipped_count}",
            ]

            self.after(0, self._finish_success, output_path, summary_lines)
        except Exception as exc:
            self.after(0, self._finish_failure, exc)

    def _finish_success(self, output_path: Path, summary_lines: list[str]):
        for line in summary_lines:
            self._append_log(line)
        self.status_var.set(f"Done: {output_path}")
        self._set_busy(False)
        messagebox.showinfo("Convert Playlist", f"Export complete:\n{output_path}")

    def _finish_failure(self, exc: Exception):
        self._append_log(f"ERROR: {exc}")
        self.status_var.set("Conversion failed")
        self._set_busy(False)
        messagebox.showerror("Convert Playlist", str(exc))


def main():
    app = PlaylistConverterGUI()
    app.mainloop()


if __name__ == "__main__":
    main()