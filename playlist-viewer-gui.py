import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import threading
import sys
import requests
from io import BytesIO
from PIL import Image, ImageTk

class SpotifyPlaylistViewer(tk.Tk):
    def __init__(self, initial_json_path=None):
        super().__init__()

        self.title("Spotify Playlist JSON Viewer")
        self.geometry("1000x650")
        self.minsize(800, 500)

        # To prevent Python's garbage collector from deleting the images
        self.current_playlist_image = None
        self.current_track_image = None
        # type: dict | None
        self.loaded_data = None

        self.setup_ui()
        if initial_json_path:
            self.after(0, lambda: self.load_json_path(initial_json_path))

    def setup_ui(self):
        # Top Frame for Controls
        top_frame = tk.Frame(self, pady=10, padx=10)
        top_frame.pack(fill=tk.X)

        load_btn = ttk.Button(top_frame, text="Load Playlist JSON", command=self.load_json)
        load_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(top_frame, textvariable=self.status_var, foreground="gray")
        status_label.pack(side=tk.RIGHT)

        # Paned Window to separate Track List (Left) and Details (Right)
        paned_window = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- LEFT PANEL: Track List ---
        left_frame = ttk.Frame(paned_window)
        paned_window.add(left_frame, weight=2)

        # Treeview (Table)
        columns = ("#", "Title", "Artist", "Album", "Duration")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="headings")
        
        self.tree.heading("#", text="#", anchor=tk.W)
        self.tree.heading("Title", text="Title", anchor=tk.W)
        self.tree.heading("Artist", text="Artist", anchor=tk.W)
        self.tree.heading("Album", text="Album", anchor=tk.W)
        self.tree.heading("Duration", text="Time", anchor=tk.W)

        self.tree.column("#", width=40, stretch=False)
        self.tree.column("Title", width=220)
        self.tree.column("Artist", width=150)
        self.tree.column("Album", width=150)
        self.tree.column("Duration", width=60, stretch=False)

        scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self.on_track_select)

        # --- RIGHT PANEL: Details ---
        right_frame = ttk.Frame(paned_window)
        paned_window.add(right_frame, weight=1)

        # Playlist Info Section
        playlist_group = ttk.LabelFrame(right_frame, text="Playlist Info", padding=10)
        playlist_group.pack(fill=tk.X, pady=(0, 10))

        self.lbl_playlist_cover = ttk.Label(playlist_group, text="[No Cover]")
        self.lbl_playlist_cover.pack(pady=5)
        
        self.lbl_playlist_title = ttk.Label(playlist_group, text="Playlist Name", font=("Arial", 12, "bold"), wraplength=250, justify="center")
        self.lbl_playlist_title.pack()
        
        self.lbl_playlist_meta = ttk.Label(playlist_group, text="Owner • 0 Tracks")
        self.lbl_playlist_meta.pack()

        # Track Info Section
        track_group = ttk.LabelFrame(right_frame, text="Selected Track", padding=10)
        track_group.pack(fill=tk.BOTH, expand=True)

        self.lbl_track_cover = ttk.Label(track_group, text="[Select a track]")
        self.lbl_track_cover.pack(pady=5)
        
        self.lbl_track_title = ttk.Label(track_group, text="-", font=("Arial", 11, "bold"), wraplength=250, justify="center")
        self.lbl_track_title.pack(pady=(5, 0))

        self.lbl_track_artist = ttk.Label(track_group, text="-", wraplength=250, justify="center")
        self.lbl_track_artist.pack()

        self.lbl_track_album = ttk.Label(track_group, text="-", foreground="gray", wraplength=250, justify="center")
        self.lbl_track_album.pack(pady=(5, 0))

    def load_json(self):
        filepath = filedialog.askopenfilename(
            title="Select Playlist JSON",
            filetypes=[("JSON Files", "*.json")]
        )
        if not filepath:
            return

        self.load_json_path(filepath)

    def load_json_path(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                self.loaded_data = json.load(f)

            # Basic validation: expect a JSON object with expected keys
            if not isinstance(self.loaded_data, dict):
                messagebox.showerror("Error", "Loaded JSON is not an object/dictionary.")
                self.loaded_data = None
                return

            self.populate_ui()
            self.status_var.set(f"Loaded: {filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load JSON:\n{e}")

    def populate_ui(self):
        # Ensure loaded_data is available for static type checkers
        if self.loaded_data is None:
            return
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 1. Update Playlist Info
        p_info = self.loaded_data.get("playlist_info", {})
        p_owner = self.loaded_data.get("playlist_owner", {})
        
        title = p_info.get("name", "Unknown Playlist")
        owner = p_owner.get("name", "Unknown Owner")
        total = p_info.get("total_tracks", 0)

        self.lbl_playlist_title.config(text=title)
        self.lbl_playlist_meta.config(text=f"{owner} • {total} Tracks")

        # Load Playlist Cover asynchronously (max size 200x200)
        cover_url = p_info.get("image_url") or self.loaded_data.get("playlist_cover_image_url")
        if cover_url:
            self.lbl_playlist_cover.config(image="", text="Loading image...")
            self.fetch_image_async(cover_url, self.lbl_playlist_cover, max_size=(200, 200), is_playlist=True)

        # 2. Populate Tracks Table
        tracks = self.loaded_data.get("tracks", [])
        for idx, track in enumerate(tracks, start=1):
            t_title = track.get("title", "Unknown")
            
            # Add an indicator for local files based on the new JSON structure
            if track.get("is_local_track"):
                t_title = f"📁 {t_title}"
            
            artists = track.get("artists", [])
            t_artist = ", ".join([a.get("name", "Unknown") for a in artists])
            
            t_album = track.get("album_name", "Unknown")
            
            # Format duration
            sec = track.get("duration_sec", 0)
            t_dur = f"{sec // 60}:{sec % 60:02d}" if sec else "0:00"

            # Insert into tree, store original track index in tags to retrieve full data later
            self.tree.insert("", tk.END, values=(idx, t_title, t_artist, t_album, t_dur), tags=(str(idx-1),))

    def on_track_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        
        # Get index from the hidden tag we assigned
        item = self.tree.item(selected[0])
        track_idx = int(item["tags"][0])
        # loaded_data was validated when loading; guard for the type checker
        if self.loaded_data is None:
            return
        track = self.loaded_data["tracks"][track_idx]

        # Update Track Details Text
        t_title = track.get("title", "Unknown")
        if track.get("is_local_track"):
            t_title += " (Local File)"
            
        self.lbl_track_title.config(text=t_title)
        
        artists = ", ".join([a.get("name", "Unknown") for a in track.get("artists", [])])
        self.lbl_track_artist.config(text=artists)
        
        self.lbl_track_album.config(text=track.get("album_name", "Unknown Album"))

        # Update Track Cover
        self.lbl_track_cover.config(image="", text="Loading image...")
        thumb_url = track.get("album_thumbnail_url")
        if thumb_url:
            self.fetch_image_async(thumb_url, self.lbl_track_cover, max_size=(250, 250), is_playlist=False)
        else:
            self.lbl_track_cover.config(text="[No Image Available]")

    def fetch_image_async(self, url, label_widget, max_size=(200, 200), is_playlist=False):
        """Fetches an image in a background thread to keep the UI responsive."""
        def download():
            try:
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                image_data = response.content
                
                # Open image using Pillow
                img = Image.open(BytesIO(image_data))
                
                # Use thumbnail() instead of resize() to preserve aspect ratio.
                # Use a compatibility fallback for Pillow's Resampling enum.
                try:
                    resample = Image.Resampling.LANCZOS
                except AttributeError:
                    # Pillow < 9.1 doesn't have Image.Resampling; try legacy names via getattr
                    resample = getattr(Image, "LANCZOS", None)
                    if resample is None:
                        resample = getattr(Image, "BICUBIC", None)

                # If no resample constant found, call thumbnail without resample (safe fallback)
                if resample is None:
                    img.thumbnail(max_size)
                else:
                    img.thumbnail(max_size, resample)
                
                # Update GUI safely in the main thread
                self.after(0, self.update_image_label, img, label_widget, is_playlist)
            except Exception as e:
                print(f"Failed to load image from {url}: {e}")
                self.after(0, lambda: label_widget.config(text="[Image Load Failed]"))

        threading.Thread(target=download, daemon=True).start()

    def update_image_label(self, pil_image, label_widget, is_playlist):
        # Convert to Tkinter PhotoImage
        tk_image = ImageTk.PhotoImage(pil_image)
        
        # Keep a reference to prevent garbage collection from deleting the image out of memory
        if is_playlist:
            self.current_playlist_image = tk_image
        else:
            self.current_track_image = tk_image
            
        label_widget.config(image=tk_image, text="")

if __name__ == "__main__":
    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = SpotifyPlaylistViewer(initial_json_path=initial_path)
    app.mainloop()