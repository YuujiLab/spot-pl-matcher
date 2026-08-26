import json
import os
import threading
import difflib
import re
import unicodedata
import base64
from typing import Any
from pathlib import Path
from io import BytesIO
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import requests
    from PIL import Image, ImageTk
except Exception:
    requests = None
    Image = None
    ImageTk = None

try:
    from mutagen._file import File as MutagenFile
except Exception:
    MutagenFile = None


SUPPORTED_EXT = {'.mp3', '.m4a', '.flac', '.wav', '.ogg', '.aac'}


def slugify(text: str):
    return "".join(c if c.isalnum() else "_" for c in text or "").strip("_") or "playlist"


def normalize_text(text: str):
    text = unicodedata.normalize('NFKD', (text or '')).encode('ascii', 'ignore').decode('ascii')
    text = text.lower()
    text = re.sub(r'\b(feat|ft|featuring|official|audio|video|lyrics|remastered)\b', ' ', text)
    text = re.sub(r'[_\-\(\)\[\]\{\}\.,]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def text_tokens(text: str):
    return [t for t in normalize_text(text).split() if t]


def token_overlap(a: str, b: str):
    ta = set(text_tokens(a))
    tb = set(text_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def text_similarity(a: str, b: str):
    na = normalize_text(a)
    nb = normalize_text(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


VERSION_KEYWORDS = {
    'remix', 'mix', 'edit', 'radio', 'extended', 'club', 'vip', 'live',
    'acoustic', 'instrumental', 'karaoke', 'version', 'dub'
}


def has_version_keyword(text: str):
    tokens = set(text_tokens(text))
    return any(k in tokens for k in VERSION_KEYWORDS)


def parse_local_audio_file(file_path: str, include_cover: bool = False):
    rec = {
        'path': str(file_path),
        'filename': os.path.basename(file_path),
        'dir': os.path.basename(os.path.dirname(file_path)),
        'title': None,
        'artist': None,
        'album': None,
        'duration': None,
        'cover_bytes': None,
    }

    if not MutagenFile:
        return rec

    try:
        m = MutagenFile(str(file_path))
        if m is None:
            return rec

        tags = m.tags or {}

        def get_tag(*keys):
            for k in keys:
                try:
                    v = tags.get(k)
                except Exception:
                    v = None
                if v is None:
                    continue
                if isinstance(v, (list, tuple)) and v:
                    v = v[0]
                try:
                    return str(v)
                except Exception:
                    continue
            return None

        rec['title'] = get_tag('TIT2', 'title', '\xa9nam')
        rec['artist'] = get_tag('TPE1', 'artist', '\xa9ART')
        rec['album'] = get_tag('TALB', 'album', '\xa9alb')

        if hasattr(m.info, 'length'):
            try:
                rec['duration'] = int(getattr(m.info, 'length', 0))
            except Exception:
                rec['duration'] = None

        if include_cover:
            cover = None

            # MP3/ID3 APIC frames
            try:
                if hasattr(tags, 'values'):
                    for v in tags.values():
                        if hasattr(v, 'data') and isinstance(getattr(v, 'data', None), (bytes, bytearray)):
                            cls_name = v.__class__.__name__.lower()
                            if 'apic' in cls_name:
                                cover = bytes(v.data)
                                break
            except Exception:
                pass

            # FLAC pictures
            if cover is None:
                try:
                    pictures = getattr(m, 'pictures', None)
                    if pictures:
                        cover = bytes(pictures[0].data)
                except Exception:
                    pass

            # MP4 covr
            if cover is None:
                try:
                    covr = tags.get('covr') if hasattr(tags, 'get') else None
                    if isinstance(covr, (list, tuple)) and covr:
                        cover = bytes(covr[0])
                except Exception:
                    pass

            # OGG/Vorbis metadata_block_picture
            if cover is None:
                try:
                    mbp = None
                    if hasattr(tags, 'get'):
                        mbp = tags.get('metadata_block_picture') or tags.get('METADATA_BLOCK_PICTURE')
                    if isinstance(mbp, (list, tuple)) and mbp:
                        mbp = mbp[0]
                    if isinstance(mbp, str):
                        cover = base64.b64decode(mbp)
                except Exception:
                    pass

            rec['cover_bytes'] = cover

    except Exception:
        pass

    return rec


def build_music_index(music_dir: str):
    """Walk music_dir and return list of file records with metadata."""
    records = []
    for root, _, files in os.walk(music_dir):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() not in SUPPORTED_EXT:
                continue
            rec = parse_local_audio_file(str(p), include_cover=False)
            records.append(rec)
    return records


def best_candidates_for_track(track, index_records, max_results=10):
    """Return top local file candidates with title-first smart scoring.
    Filename/title match is prioritized; artist/album/duration are secondary.
    """
    album = (track.get('album_name') or '')
    artist = ', '.join([a.get('name', '') for a in track.get('artists', [])])
    title = track.get('title') or ''
    duration = track.get('duration_sec')

    title_norm = normalize_text(title)
    artist_norm = normalize_text(artist)
    album_norm = normalize_text(album)
    spotify_has_version = has_version_keyword(title)

    def score(rec):
        try:
            rec_filename = rec.get('filename') or ''
            rec_filename_stem = Path(rec_filename).stem
            rec_title = str(rec.get('title') or '')
            rec_artist = str(rec.get('artist') or '')
            rec_album = str(rec.get('album') or rec.get('dir') or '')
            rec_title_for_version = f"{rec_filename_stem} {rec_title}"

            filename_norm = normalize_text(rec_filename_stem)
            rec_title_norm = normalize_text(rec_title)

            title_vs_filename = text_similarity(title_norm, filename_norm)
            title_vs_tag = text_similarity(title_norm, rec_title_norm)
            title_overlap = max(
                token_overlap(title_norm, filename_norm),
                token_overlap(title_norm, rec_title_norm),
            )
            title_score = max(title_vs_filename, title_vs_tag)

            artist_score = text_similarity(artist_norm, rec_artist)
            artist_overlap = token_overlap(artist_norm, rec_artist)

            album_score = text_similarity(album_norm, rec_album)

            duration_score = 0.0
            duration_penalty = 0.0
            rec_duration = rec.get('duration')
            duration_cap = 1.0
            if isinstance(duration, (int, float)) and isinstance(rec_duration, (int, float)):
                diff = abs(float(duration) - float(rec_duration))
                if diff <= 2:
                    duration_score = 1.0
                elif diff <= 5:
                    duration_score = 0.7
                elif diff <= 12:
                    duration_score = 0.4
                elif diff <= 20:
                    duration_score = 0.1

                # Big runtime differences strongly indicate a different version/song.
                if diff > 30:
                    duration_penalty = 0.12
                    duration_cap = min(duration_cap, 0.88)
                if diff > 60:
                    duration_penalty = 0.22
                    duration_cap = min(duration_cap, 0.72)
                if diff > 120:
                    duration_penalty = 0.35
                    duration_cap = min(duration_cap, 0.55)

            # Strong boost for exact/contained title in filename.
            boost = 0.0
            if title_norm and filename_norm:
                if title_norm == filename_norm:
                    boost += 0.35
                elif title_norm in filename_norm or filename_norm in title_norm:
                    boost += 0.22

            # If only one side looks like a remix/edit/live version, reduce confidence.
            rec_has_version = has_version_keyword(rec_title_for_version)
            version_penalty = 0.0
            version_cap = 1.0
            if spotify_has_version != rec_has_version:
                version_penalty = 0.12
                version_cap = 0.82

            # Album mismatch matters more when title appears very close.
            album_cap = 1.0
            if album_norm and rec_album:
                if title_score >= 0.9 and album_score < 0.3:
                    album_cap = 0.86
                if title_score >= 0.95 and album_score < 0.2:
                    album_cap = 0.78

            s = (
                (0.52 * title_score)
                + (0.20 * title_overlap)
                + (0.13 * artist_score)
                + (0.07 * artist_overlap)
                + (0.05 * album_score)
                + (0.03 * duration_score)
                + boost
            )

            s -= duration_penalty
            s -= version_penalty
            s = min(s, duration_cap, version_cap, album_cap)
        except Exception:
            s = 0.0

        return min(1.0, max(0.0, s))

    scored = [(score(r), r) for r in index_records]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(round(s, 3), r) for s, r in scored[:max_results] if s >= 0.12]


class PlaylistMatcherUI(tk.Tk):
    # Navigation helpers
    def prev_track(self) -> None:
        """Go to previous track and refresh UI."""
        if not getattr(self, 'playlist', None):
            return
        if self.current_idx <= 0:
            messagebox.showinfo('Navigation', 'Already at the first track')
            return
        self.current_idx -= 1
        self.selected_candidate_idx = None
        try:
            self.cand_list.selection_clear(0, 'end')
        except Exception:
            pass
        self.show_current()

    def next_track(self) -> None:
        """Advance to next track and refresh UI."""
        if not getattr(self, 'playlist', None):
            return
        tracks = (self.playlist or {}).get('tracks', [])
        if self.current_idx >= len(tracks) - 1:
            messagebox.showinfo('Complete', 'Reached end of playlist')
            return
        self.current_idx += 1
        self.selected_candidate_idx = None
        try:
            self.cand_list.selection_clear(0, 'end')
        except Exception:
            pass
        self.show_current()

    def __init__(self):
        super().__init__()
        self.title('Spotify Playlist Matcher')
        self.geometry('1200x800')
        self.minsize(900, 600)

        # State
        self.playlist: dict[str, Any] | None = None
        self.index: list[dict[str, Any]] = []
        self.results: list[dict[str, Any] | None] = []
        self.current_candidates: list[tuple[float, dict[str, Any]]] = []
        self.current_idx = 0
        self.selected_candidate_idx = None

        # Configure style
        style = ttk.Style()
        style.configure('Header.TLabel', font=('Segoe UI', 14, 'bold'))
        style.configure('Section.TLabel', font=('Segoe UI', 11, 'bold'))
        style.configure('Info.TLabel', font=('Segoe UI', 10))
        style.configure('Progress.TLabel', font=('Segoe UI', 9))

        # === HEADER ===
        header = ttk.Frame(self)
        header.pack(side='top', fill='x', padx=12, pady=10)

        title = ttk.Label(header, text='🎵 Spotify Playlist Matcher', style='Header.TLabel')
        title.pack(anchor='w')
        ttk.Label(header, text='Match your Spotify playlist tracks with local music files',
                 style='Info.TLabel', foreground='gray').pack(anchor='w')

        # === SETUP PANEL ===
        setup_frame = ttk.LabelFrame(self, text='1. Setup', padding=10)
        setup_frame.pack(side='top', fill='x', padx=12, pady=5)

        setup_btns = ttk.Frame(setup_frame)
        setup_btns.pack(fill='x')

        ttk.Button(setup_btns, text='📂 Load Playlist JSON', 
                  command=self.load_playlist, width=20).pack(side='left', padx=5)
        ttk.Button(setup_btns, text='🎼 Choose Music Directory', 
                  command=self.choose_music_dir, width=25).pack(side='left', padx=5)

        # Option: fetch remote images (useful to disable for offline use)
        self.fetch_images_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(setup_frame, text='Fetch remote images (for offline disable)',
                variable=self.fetch_images_var).pack(anchor='e')
        self.setup_status = ttk.Label(setup_frame, text='⏳ Waiting for playlist and music directory...',
                                      foreground='#FF8C00', style='Info.TLabel')
        self.setup_status.pack(anchor='w', pady=8)

        # === MAIN CONTENT ===
        main = ttk.Frame(self)
        main.pack(fill='both', expand=True, padx=12, pady=5)

        # Left: Spotify track info
        left_frame = ttk.LabelFrame(main, text='📻 Spotify Track', padding=10)
        left_frame.pack(side='left', fill='both', expand=False, padx=(0, 8))

        self.progress_label = ttk.Label(left_frame, text='Track 0/0',
                                        style='Progress.TLabel', foreground='#0066FF')
        self.progress_label.pack(anchor='w', pady=(0, 8))

        self.json_image_label = ttk.Label(left_frame, relief='solid', borderwidth=1)
        self.json_image_label.pack(pady=8)

        self.json_info = tk.Text(left_frame, height=14, width=35, wrap='word',
                                font=('Consolas', 9))
        self.json_info.pack(fill='both', expand=True)

        # Right: Matching candidates and actions
        right_frame = ttk.LabelFrame(main, text='🔍 Candidate Matches', padding=10)
        right_frame.pack(side='right', fill='both', expand=True)

        ttk.Label(right_frame, text='Select a match or use buttons below:',
                 style='Info.TLabel').pack(anchor='w', pady=(0, 8))

        # Candidates listbox with scrollbar
        list_frame = ttk.Frame(right_frame)
        list_frame.pack(fill='both', expand=True, pady=(0, 8))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')

        self.cand_list = tk.Listbox(list_frame, height=16, font=('Consolas', 9),
                                   yscrollcommand=scrollbar.set, selectmode='single')
        self.cand_list.pack(side='left', fill='both', expand=True)
        self.cand_list.bind('<<ListboxSelect>>', self.on_candidate_select)
        # allow double-click to accept selected candidate
        self.cand_list.bind('<Double-Button-1>', self.on_candidate_double_click)
        scrollbar.config(command=self.cand_list.yview)

        # Action buttons
        button_frame = ttk.Frame(right_frame)
        button_frame.pack(fill='x')

        ttk.Button(button_frame, text='✓ Accept Match (Enter)',
                  command=self.accept_candidate, width=20).pack(side='left', padx=2, pady=2)
        ttk.Button(button_frame, text='📁 Manual Choose',
                  command=self.manual_choose, width=20).pack(side='left', padx=2, pady=2)
        ttk.Button(button_frame, text='⊘ Skip Track (S)',
                  command=self.skip_track, width=15).pack(side='left', padx=2, pady=2)

        # === LOCAL PREVIEW (right side) ===
        preview_frame = ttk.LabelFrame(right_frame, text='🎧 Local Track Preview', padding=8)
        preview_frame.pack(fill='x', pady=(8, 0))

        self.local_image_label = ttk.Label(preview_frame, relief='solid', borderwidth=1, text='[No cover]')
        self.local_image_label.pack(side='left', padx=(0, 8), pady=4)

        self.local_info = tk.Text(preview_frame, height=8, width=70, wrap='word',
                     font=('Consolas', 9))
        self.local_info.pack(side='left', fill='both', expand=True)

        # === BOTTOM NAVIGATION ===
        bottom = ttk.Frame(self)
        bottom.pack(side='bottom', fill='x', padx=12, pady=10)

        nav_btns = ttk.Frame(bottom)
        nav_btns.pack(side='right')

        ttk.Button(nav_btns, text='⬅ Previous',
                  command=self.prev_track).pack(side='left', padx=4)
        ttk.Button(nav_btns, text='Next ➜ (Space)',
                  command=self.next_track).pack(side='left', padx=4)
        ttk.Button(nav_btns, text='💾 Save & Exit',
                  command=self.save_and_exit).pack(side='left', padx=4)

        # Bind keyboard shortcuts
        self.bind('<Return>', lambda e: self.accept_candidate())
        self.bind('<space>', lambda e: self.next_track())
        self.bind('<s>', lambda e: self.skip_track())
        self.bind('<S>', lambda e: self.skip_track())

    @staticmethod
    def _format_duration(sec):
        if not isinstance(sec, (int, float)):
            return 'N/A'
        sec_int = int(sec)
        return f"{sec_int // 60}:{sec_int % 60:02d}"

    def _update_local_preview(self, rec=None, score=None):
        # Render immediate lightweight preview (filename/path/title-from-filename)
        self.local_info.config(state='normal')
        self.local_info.delete('1.0', 'end')
        if not rec:
            self.local_image_label.config(image='', text='[No cover]')
            self.local_info.insert('1.0', '[Select a candidate to preview local metadata and cover]')
            self.local_info.config(state='disabled')
            return

        basic = {
            'path': rec.get('path') or '',
            'filename': rec.get('filename') or os.path.basename(rec.get('path', '')),
            'dir': rec.get('dir') or os.path.basename(os.path.dirname(rec.get('path', ''))),
            'title': rec.get('title'),
            'artist': rec.get('artist'),
            'album': rec.get('album'),
            'duration': rec.get('duration'),
            'cover_bytes': rec.get('cover_bytes'),
        }

        info = (
            f"File: {os.path.basename(basic.get('path',''))}\n"
            f"Path: {basic.get('path','N/A')}\n"
            f"Title: {basic.get('title') or Path(basic.get('filename','')).stem}\n"
            f"Artist: {basic.get('artist') or 'N/A'}\n"
            f"Album: {basic.get('album') or basic.get('dir') or 'N/A'}\n"
            f"Duration: {self._format_duration(basic.get('duration'))}"
        )
        if isinstance(score, (int, float)):
            info += f"\nMatch Score: {score:.1%}"

        self.local_info.insert('1.0', info)
        self.local_info.config(state='disabled')

        # set placeholder image immediately
        if basic.get('cover_bytes'):
            try:
                if Image and ImageTk:
                    im = Image.open(BytesIO(basic['cover_bytes']))
                    im.thumbnail((140, 140))
                    self.local_photo = ImageTk.PhotoImage(im)
                    self.local_image_label.config(image=self.local_photo, text='')
            except Exception:
                self.local_image_label.config(image='', text='[No cover]')
        else:
            self.local_image_label.config(image='', text='[No cover]')

        # Launch background job to reparse file for full metadata + cover (non-blocking)
        self._preview_job += 1
        job_id = self._preview_job

        def worker():
            parsed = parse_local_audio_file(basic.get('path', ''), include_cover=True)
            def on_done():
                if job_id != self._preview_job:
                    return
                merged = dict(basic)
                for k in ('title', 'artist', 'album', 'duration', 'cover_bytes'):
                    if parsed.get(k) not in (None, ''):
                        merged[k] = parsed.get(k)
                # re-render UI with richer info
                info2 = (
                    f"File: {os.path.basename(merged.get('path', ''))}\n"
                    f"Path: {merged.get('path', 'N/A')}\n"
                    f"Title: {merged.get('title') or Path(merged.get('filename', '')).stem}\n"
                    f"Artist: {merged.get('artist') or 'N/A'}\n"
                    f"Album: {merged.get('album') or merged.get('dir') or 'N/A'}\n"
                    f"Duration: {self._format_duration(merged.get('duration'))}"
                )
                if isinstance(score, (int, float)):
                    info2 += f"\nMatch Score: {score:.1%}"
                self.local_info.config(state='normal')
                self.local_info.delete('1.0', 'end')
                self.local_info.insert('1.0', info2)
                self.local_info.config(state='disabled')
                if Image and ImageTk and merged.get('cover_bytes'):
                    try:
                        im = Image.open(BytesIO(merged['cover_bytes']))
                        im.thumbnail((140, 140))
                        self.local_photo = ImageTk.PhotoImage(im)
                        self.local_image_label.config(image=self.local_photo, text='')
                        return
                    except Exception:
                        pass
                self.local_image_label.config(image='', text='[No cover]')

            self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def load_playlist(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON', '*.json'), ('All Files', '*.*')],
            title='Select your Spotify playlist JSON file'
        )
        if not path:
            return
        # If user has an in-progress playlist, ask whether to save before loading new one
        if self.playlist is not None and any(r is not None for r in self.results):
            res = messagebox.askyesnocancel('In-progress playlist',
                'You have an in-progress matched playlist. Save before loading another?\nYes=Save and continue, No=Discard and load, Cancel=Keep current')
            if res is None:
                return
            if res is True:
                # save current results (non-destructive)
                try:
                    self._save_results()
                except Exception as e:
                    messagebox.showerror('Error', f'Failed to save current results:\n{e}')
                    return
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if 'tracks' not in data:
                messagebox.showerror('Error', 'Invalid playlist file: no "tracks" key found')
                return
            playlist_data: dict[str, Any] = data
            self.playlist = playlist_data
            self.playlist_path = path
            self.results = [None] * len(playlist_data.get('tracks', []))
            self.current_idx = 0
            self.selected_candidate_idx = None
            self._preview_job = 0
            self._spotify_img_job = 0
            self.json_photo = None
            self.local_photo = None
            self.setup_status.config(
                text=f'✓ Playlist loaded: {os.path.basename(path)} ({len(playlist_data["tracks"])} tracks)',
                foreground='green'
            )
            self.show_current()
        except Exception as e:
            messagebox.showerror('Error', f'Failed to load playlist:\n{str(e)}')


    def choose_music_dir(self):
        d = filedialog.askdirectory(title='Select your music directory')
        if not d:
            return
        self.setup_status.config(text='⏳ Indexing music directory... (this may take a while)', foreground='#FF8C00')
        self.update()
        
        def worker():
            try:
                idx = build_music_index(d)
                def on_done():
                    self.index = idx
                    self.setup_status.config(
                        text=f'✓ Music indexed: {len(self.index)} files found',
                        foreground='green'
                    )
                    self.show_current()
                self.after(0, on_done)
            except Exception as e:
                def on_error():
                    messagebox.showerror('Error', f'Failed to index music directory:\n{str(e)}')
                    self.setup_status.config(text='❌ Indexing failed', foreground='red')
                self.after(0, on_error)
        
        threading.Thread(target=worker, daemon=True).start()

    def show_current(self):
        if not self.playlist:
            messagebox.showwarning('Setup', 'Please load a playlist first')
            return
        
        tracks = self.playlist.get('tracks', [])
        if self.current_idx >= len(tracks):
            messagebox.showinfo('Complete', 'Reached end of playlist')
            return
        
        t = tracks[self.current_idx]
        
        # Update progress
        matched_count = sum(1 for r in self.results[:self.current_idx] if r is not None)
        skipped_count = sum(1 for r in self.results[:self.current_idx] if r is None)
        self.progress_label.config(
            text=f'Track {self.current_idx + 1}/{len(tracks)} | Matched: {matched_count} | Skipped: {skipped_count}'
        )

        # Show Spotify track info
        self.json_info.config(state='normal')
        self.json_info.delete('1.0', 'end')
        
        artist_names = ', '.join([a.get('name', '') for a in t.get('artists', [])])
        duration_min = (t.get('duration_sec', 0) or 0) // 60
        duration_sec = (t.get('duration_sec', 0) or 0) % 60
        
        current_result = self.results[self.current_idx] if self.results else None
        current_match_path = current_result['path'] if isinstance(current_result, dict) else 'Not matched yet'

        info_text = f"""Title:
{t.get('title', 'N/A')}

Artists:
{artist_names or 'N/A'}

Album:
{t.get('album_name', 'N/A')}

Duration: {duration_min}:{duration_sec:02d}

Added: {t.get('added_to_playlist', 'N/A')[:10]}

Current Match:
{current_match_path}"""
        
        self.json_info.insert('1.0', info_text)
        self.json_info.config(state='disabled')

        # Show album image
        img_url = (t.get('album_thumbnail_url') or 
                  (t.get('album_thumbnails', [{}])[0].get('url') if t.get('album_thumbnails') else None))
        # Fetch Spotify image in background to avoid UI hangs; respect offline toggle
        self.json_image_label.config(image='', text='[No image]')
        if self.fetch_images_var.get() and (requests is not None) and (Image is not None) and (ImageTk is not None) and img_url:
            # start a background job and only set latest job's result
            self._spotify_img_job += 1
            job = self._spotify_img_job
            # capture safe callables to satisfy static checkers
            requests_get = getattr(requests, 'get', None)
            Image_open = getattr(Image, 'open', None)
            PhotoImage_cls = getattr(ImageTk, 'PhotoImage', None)

            def worker_img():
                if not requests_get:
                    def on_err():
                        if job != self._spotify_img_job:
                            return
                        self.json_image_label.config(image='', text='[No image]')
                    self.after(0, on_err)
                    return
                try:
                    r = requests_get(img_url, stream=True, timeout=6)
                    r.raise_for_status()
                    data = r.content
                    def on_done():
                        if job != self._spotify_img_job:
                            return
                        try:
                            if not Image_open or not PhotoImage_cls:
                                self.json_image_label.config(image='', text='[No image]')
                                return
                            im = Image_open(BytesIO(data))
                            im.thumbnail((240,240))
                            self.json_photo = PhotoImage_cls(im)
                            self.json_image_label.config(image=self.json_photo)
                        except Exception:
                            self.json_image_label.config(image='', text='[No image]')
                    self.after(0, on_done)
                except Exception:
                    def on_err():
                        if job != self._spotify_img_job:
                            return
                        self.json_image_label.config(image='', text='[No image]')
                    self.after(0, on_err)
            threading.Thread(target=worker_img, daemon=True).start()

        # Show candidates
        self.cand_list.delete(0, 'end')
        self.current_candidates = []
        
        if not self.index:
            self.cand_list.insert('end', '[Music directory not indexed]')
        else:
            cands = best_candidates_for_track(t, self.index, max_results=15)
            self.current_candidates = cands
            for score, rec in cands:
                filename = os.path.basename(rec['path'])
                artist = rec.get('artist') or ''
                album = rec.get('album') or rec.get('dir') or ''
                display = f"{score:.3f} ⭐ {filename}\n       {artist} — {album}"
                self.cand_list.insert('end', display)
            # auto-select top candidate and preview it
            if cands:
                try:
                    self.cand_list.selection_set(0)
                    self.cand_list.activate(0)
                    self.selected_candidate_idx = 0
                    top_score, top_rec = cands[0]
                    self._update_local_preview(top_rec, score=top_score)
                except Exception:
                    pass
        
        # Clear selection info if no match yet
        selected_result = self.results[self.current_idx]
        if isinstance(selected_result, dict):
            selected_path = selected_result.get('path')
            idx_rec = next((r for r in self.index if r.get('path') == selected_path), {'path': selected_path})
            self._update_local_preview(idx_rec, score=selected_result.get('score'))
        else:
            self._update_local_preview(None)

    def on_candidate_select(self, event):
        """Show selected candidate details"""
        sel = self.cand_list.curselection()
        if not sel:
            return
        self.selected_candidate_idx = sel[0]
        score, rec = self.current_candidates[self.selected_candidate_idx]

        self._update_local_preview(rec, score=score)

    def on_candidate_double_click(self, event):
        """Accept selected candidate on double-click."""
        # ensure selection is processed before accepting
        self.after(10, self.accept_candidate)

    def accept_candidate(self):
        if not self.playlist:
            messagebox.showwarning('Setup', 'Please load a playlist first')
            return
        
        sel = self.cand_list.curselection()
        if not sel:
            messagebox.showwarning('Select Match', 'Please select a candidate from the list first')
            return
        
        idx = sel[0]
        score, rec = self.current_candidates[idx]
        self.results[self.current_idx] = {'path': rec['path'], 'score': score}
        # clear local preview now that we've accepted this candidate
        try:
            self._update_local_preview(None)
        except Exception:
            pass

        self.next_track()

    def skip_track(self):
        """Skip current track without matching"""
        self.results[self.current_idx] = None
        self.next_track()

    def manual_choose(self):
        """Let user manually select a file"""
        if not self.playlist:
            messagebox.showwarning('Setup', 'Please load a playlist first')
            return
        
        p = filedialog.askopenfilename(
            filetypes=[('Audio Files', '*.mp3 *.m4a *.flac *.wav *.ogg *.aac'),
                      ('MP3', '*.mp3'), ('M4A', '*.m4a'), ('FLAC', '*.flac'),
                      ('All Files', '*.*')],
            title='Manually select a music file for this track'
        )
        if p:
            self.results[self.current_idx] = {'path': p, 'score': 1.0}
            self._update_local_preview({'path': p, 'filename': os.path.basename(p), 'dir': os.path.basename(os.path.dirname(p))}, score=1.0)
            self.next_track()

    def save_and_exit(self):
        if not self.playlist:
            messagebox.showwarning('No Data', 'No playlist loaded to save')
            return
        
        # Calculate statistics
        matched = sum(1 for r in self.results if r is not None)
        skipped = len(self.results) - matched
        
        # Show summary
        summary = f"""Summary before saving:

Total tracks: {len(self.results)}
✓ Matched: {matched} ({100*matched//len(self.results)}%)
⊘ Skipped: {skipped} ({100*skipped//len(self.results)}%)

The results will be saved as:
{Path(self.playlist_path).stem}_matched.json

Continue?"""
        
        if not messagebox.askyesno('Save Results', summary):
            return

        try:
            self._save_results()
            messagebox.showinfo('Success', '✓ Results saved')
            self.destroy()
        except Exception as e:
            messagebox.showerror('Error', f'Failed to save results:\n{str(e)}')

    def _save_results(self, out_path: str | None = None):
        """Save current results to disk without exiting."""
        if not self.playlist:
            raise RuntimeError('No playlist loaded')
        out = dict(self.playlist)
        out['matched_paths'] = self.results
        matched = sum(1 for r in self.results if r is not None)
        skipped = len(self.results) - matched
        out['match_summary'] = {'total': len(self.results), 'matched': matched, 'skipped': skipped}

        base = Path(self.playlist_path)
        if out_path is None:
            out_path = str(base.parent / f"{base.stem}_matched.json")

        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)


def main():
    app = PlaylistMatcherUI()
    app.mainloop()


if __name__ == '__main__':
    main()
