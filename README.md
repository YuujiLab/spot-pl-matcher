# Spot Playlist Converter & Local Matcher

A lightweight desktop toolkit to export Spotify playlist metadata to structured JSON and match tracks against your local offline music library.

> **Disclaimer:** This project is an independent open-source utility and is not affiliated with, maintained by, or endorsed by Spotify. It is intended solely for personal metadata organization and local file management. It does not download, stream, or rip DRM-protected audio files.

## Features

- **Playlist Metadata Exporter:** Export public and private Spotify playlists to standardized JSON files containing track details, artists, albums, timestamps, and cover art URLs.
- **Local Audio Matcher:** Intelligently match exported playlist tracks to your local audio library using fuzzy string matching, filename stem analysis, and tag duration scoring.
- **Built-in Desktop GUIs:** Simple Tkinter-based interfaces for running exports, reviewing matches, and viewing playlist JSON files with thumbnail previews.
- **Multi-Format Local Support:** Reads metadata and embedded art across `.mp3`, `.m4a`, `.flac`, `.wav`, `.ogg`, and `.aac` filesf.

## Requirements

- Python 3.10+
- `tkinter` (included with standard Python installations on Windows/macOS; Linux users may need `sudo apt install python3-tk`)

## Installation

1. **Clone the repository:**
```
git clone https://github.com/YuujiLab/spot-pl-matcher.git
cd spot-playlist-matcher
```

2. **Create and activate a virtual environment (Optional):**
```
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

3. **Install dependencies:**
```
pip install -r requirements-gui.txt
```

*(Required packages: `spotapi`, `Pillow`, `requests`, `mutagen`)*

## Usage

### 1. Playlist Converter GUI (Recommended)

Launch the graphical interface to export playlist data:

```bash
python main-gui.py
```

* Paste your Spotify playlist URL.


* (Optional) Select an output directory and custom cookie file.


* Click **Convert Playlist**.

### 2. Local Audio Matcher GUI

Match an exported playlist JSON file against your offline music files:

```
python playlist-matcher-gui.py
```

* Click **Load Playlist JSON** and select your exported `.json` file.

* Click **Choose Music Directory** to index your local songs.

* Cycle through suggested track candidates:
* `Enter` to accept a match.

* `Space` / `Next` to advance.

* `S` to skip.

* **Manual Choose** to pick a file manually from disk.

* Click **Save & Exit** to export a `<playlist>_matched.json` mapping file.

### 3. Command-Line Exporter

Export directly from your terminal:

```
python main.py "[https://open.spotify.com/playlist/YOUR_PLAYLIST_ID](https://open.spotify.com/playlist/YOUR_PLAYLIST_ID)"
```

Flags:

* `--output <path>`: Specify custom JSON output path.

* `--keep-raw`: Retain the unparsed raw API response dump (`RAW_<name>.json`).

### 4. JSON Viewer

Inspect any exported playlist JSON file independently:

```
python playlist-viewer-gui.py path/to/playlist.json
```

## Handling Private or Gated Playlists

Public playlists can usually be exported without logging in. If a playlist is private, user-gated, or fails to return track data, you can provide an optional `cookies.json` file in the root folder:

1. Use a browser extension (such as *Cookie-Editor*) to export your cookies from `open.spotify.com` as JSON.
2. Save the output as `cookies.json` inside the project root directory.

> **Security Warning:** Never commit, publish, or share your `cookies.json` file with anyone. It contains active session credentials for your Spotify account.

## Output Structure

The tool outputs a clean JSON schema including:

* `playlist_info`: Name, description, follower count, total tracks, and cover image URLs.

* `playlist_owner`: Owner display name and profile identifiers.

* `tracks`: Array of tracks containing titles, artist lists, album names, durations, release dates, and playlist addition timestamps.

## License

Distributed under the GPLv3 License. See `LICENSE` for details.