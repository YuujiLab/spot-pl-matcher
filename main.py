import argparse
import json
import logging
from pathlib import Path
import re

from spotapi import Config, Login, PublicPlaylist


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

def get_deep(data, path, default=None):
    """Helper to navigate nested dictionaries safely."""
    if data is None:
        return default
    for key in path:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and isinstance(key, int):
            if 0 <= key < len(data):
                data = data[key]
            else:
                return default
        else:
            return default
    return data if data is not None else default


def extract_playlist_id(url):
    match = re.search(r"playlist/([a-zA-Z0-9]{22})", url)
    if match:
        return match.group(1)
    raise ValueError("Invalid Spotify playlist URL.")


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "playlist"


def build_output_path(playlist_name):
    return f"{slugify(playlist_name)}.json"


def build_raw_path(playlist_name):
    return f"RAW_{slugify(playlist_name)}.json"


def get_highest_resolution_url(sources):
    if not sources:
        return None
    best_source = max(sources, key=lambda source: source.get('width', 0) or 0)
    return best_source.get('url')


def get_earliest_timestamp(timestamps):
    values = [timestamp for timestamp in timestamps if timestamp]
    if not values:
        return None
    return min(values)


def has_playlist_content(playlist_info):
    return bool(get_deep(playlist_info, ['data', 'playlistV2', 'content', 'items']))


def load_authenticated_client(cookie_path="cookies.json"):
    cookie_file = Path(cookie_path)
    if not cookie_file.exists():
        return None

    with cookie_file.open("r", encoding="utf-8") as file_handle:
        cookie_list = json.load(file_handle)

    cookie_dict = {cookie['name']: cookie['value'] for cookie in cookie_list}
    cfg = Config(logger=SpotApiLogger)
    session = Login.from_cookies(
        {
            "identifier": "spotify_playlist_scraper",
            "cookies": cookie_dict,
            "password": "",
        },
        cfg,
    )
    return session.client


def fetch_playlist_handler(playlist_id):
    public_handler = PublicPlaylist(playlist_id)
    public_info = public_handler.get_playlist_info(limit=25)

    if has_playlist_content(public_info):
        return public_handler, public_info

    auth_client = load_authenticated_client()
    if auth_client is not None:
        authenticated_handler = PublicPlaylist(playlist_id, client=auth_client)
        authenticated_info = authenticated_handler.get_playlist_info(limit=25)
        if has_playlist_content(authenticated_info):
            print("[DEBUG] Public response was incomplete; using cookies.json for authenticated access.")
            return authenticated_handler, authenticated_info

        message = get_deep(authenticated_info, ['data', 'playlistV2', 'message'])
        raise RuntimeError(message or "Authenticated playlist response did not include track content.")

    message = get_deep(public_info, ['data', 'playlistV2', 'message'])
    raise RuntimeError(
        message
        or "Playlist response did not include track content. Add cookies.json if this playlist is private or gated."
    )

def extract_track_details(entry):
    """Extract comprehensive track details from a raw playlist item entry."""
    track_data = {}
    
    # Get itemV2 (detailed track info) and itemV3 (metadata/publishing info)
    item_v2 = entry.get('itemV2', {})
    item_v3 = entry.get('itemV3', {})
    
    v2_data = item_v2.get('data', {})
    v3_data = item_v3.get('data', {})
    
    # Skip if no valid track data
    if not v2_data and not v3_data:
        return None

    uri = v2_data.get('uri', '')
    is_local_track = uri.startswith('spotify:local:')
    track_data['is_local_track'] = is_local_track
    track_data['track_source'] = 'local' if is_local_track else 'spotify'
    
    # ===== Basic Track Info (from itemV2) =====
    track_data['title'] = v2_data.get('name', 'Unknown')
    track_data['uri'] = uri
    track_data['spotify_id'] = uri.split(':')[-1] if uri else None
    track_data['track_number'] = v2_data.get('trackNumber')
    track_data['disc_number'] = v2_data.get('discNumber')
    track_data['playcount'] = v2_data.get('playcount')
    
    # ===== Duration =====
    track_data['duration_ms'] = get_deep(v2_data, ['trackDuration', 'totalMilliseconds'])
    if track_data['duration_ms']:
        track_data['duration_sec'] = track_data['duration_ms'] // 1000
    
    # ===== Artists =====
    artists = get_deep(v2_data, ['artists', 'items'], [])
    track_data['artists'] = []
    for artist in artists:
        artist_name = get_deep(artist, ['profile', 'name'])
        artist_uri = artist.get('uri')
        if artist_name:
            track_data['artists'].append({
                'name': artist_name,
                'uri': artist_uri,
                'spotify_id': artist_uri.split(':')[-1] if artist_uri else None
            })

    if is_local_track:
        local_artist = v2_data.get('artistName')
        local_album = v2_data.get('albumName')
        local_duration = get_deep(v2_data, ['localTrackDuration', 'totalMilliseconds'])

        track_data['local_track_artist_name'] = local_artist
        track_data['local_track_album_name'] = local_album
        track_data['local_track_duration_ms'] = local_duration

        if local_artist:
            track_data['artists'] = [{'name': local_artist, 'uri': None, 'spotify_id': None}]
        if local_album:
            track_data['album_name'] = local_album
        if local_duration and not track_data.get('duration_ms'):
            track_data['duration_ms'] = local_duration
            track_data['duration_sec'] = local_duration // 1000
    
    # ===== Album/Release Info (from itemV2) =====
    album_v2 = get_deep(v2_data, ['albumOfTrack'], {})
    track_data['album_name'] = album_v2.get('name')
    track_data['album_uri'] = album_v2.get('uri')
    track_data['album_spotify_id'] = track_data['album_uri'].split(':')[-1] if track_data['album_uri'] else None
    
    # Album artists
    album_artists = get_deep(album_v2, ['artists', 'items'], [])
    track_data['album_artists'] = []
    for artist in album_artists:
        artist_name = get_deep(artist, ['profile', 'name'])
        artist_uri = artist.get('uri')
        if artist_name:
            track_data['album_artists'].append({
                'name': artist_name,
                'uri': artist_uri
            })
    
    # Album thumbnail (highest resolution)
    cover_sources = get_deep(album_v2, ['coverArt', 'sources'], [])
    if cover_sources:
        # Sort by width to get highest resolution
        cover_sources_sorted = sorted(cover_sources, key=lambda x: x.get('width', 0), reverse=True)
        track_data['album_thumbnail_url'] = cover_sources_sorted[0].get('url')
        track_data['album_thumbnails'] = [
            {'width': s.get('width'), 'height': s.get('height'), 'url': s.get('url')} 
            for s in cover_sources
        ]
    
    # ===== Release Date & Publishing Metadata (from itemV3) =====
    identity_trait = get_deep(v3_data, ['identityTrait'], {})
    content_hierarchy_parent = get_deep(identity_trait, ['contentHierarchyParent'], {})
    publishing_metadata = get_deep(content_hierarchy_parent, ['publishingMetadataTrait'], {})
    
    # Release date from the album
    first_published = get_deep(publishing_metadata, ['firstPublishedAt'], {})
    track_data['release_date'] = first_published.get('isoString')
    track_data['release_date_precision'] = first_published.get('precision')  # DAY, MONTH, YEAR
    
    # ===== Playability =====
    playability = get_deep(v2_data, ['playability'], {})
    track_data['is_playable'] = playability.get('playable', False)
    track_data['playability_reason'] = playability.get('reason')
    
    # ===== Explicit/Content Rating =====
    content_rating = get_deep(v2_data, ['contentRating'], {})
    track_data['content_rating'] = content_rating.get('label')
    
    # ===== Media Type =====
    track_data['media_type'] = v2_data.get('mediaType')  # AUDIO, VIDEO, etc.
    
    # ===== Audio Formats Available (from itemV3) =====
    formats = get_deep(v3_data, ['consumptionExperienceTrait', 'formats'], [])
    if formats:
        track_data['available_formats'] = formats
    
    # ===== Track Added Info (from entry root) =====
    added_at = entry.get('addedAt', {})
    track_data['added_to_playlist'] = added_at.get('isoString')
    
    added_by = get_deep(entry, ['addedBy', 'data'])
    if added_by:
        track_data['added_by'] = {
            'name': added_by.get('name'),
            'uri': added_by.get('uri'),
            'username': added_by.get('username'),
            'avatar_url': get_highest_resolution_url(get_deep(added_by, ['avatar', 'sources'], []))
        }
    
    # ===== Contributors (from itemV3) =====
    contributors = get_deep(identity_trait, ['contributors', 'items'], [])
    if contributors:
        track_data['contributors'] = [
            {'name': c.get('name'), 'uri': c.get('uri')} 
            for c in contributors
        ]
    
    return track_data


def extract_playlist_details(playlist_info):
    playlist_v2 = get_deep(playlist_info, ['data', 'playlistV2'], {})

    playlist_data = {
        "playlist_info": {
            "name": playlist_v2.get('name', 'Unknown Playlist'),
            "description": playlist_v2.get('description', ''),
            "uri": playlist_v2.get('uri', ''),
            "spotify_id": playlist_v2.get('uri', '').split(':')[-1] if playlist_v2.get('uri') else None,
            "followers": playlist_v2.get('followers', 0),
            "is_public": playlist_v2.get('public'),
            "is_collaborative": playlist_v2.get('collaborative'),
            "base_permission": playlist_v2.get('basePermission'),
            "following": playlist_v2.get('following'),
            "total_tracks": get_deep(playlist_v2, ['content', 'pagingInfo', 'totalCount'], 0),
            "revision_id": playlist_v2.get('revisionId'),
        },
        "playlist_owner": {},
        "playlist_cover_image_url": None,
        "playlist_images": [],
        "playlist_sharing": {},
        "playlist_members": [],
        "user_capabilities": {},
        "created_at": None,
        "tracks": []
    }

    owner_v2 = get_deep(playlist_v2, ['ownerV2', 'data'], {})
    if owner_v2:
        playlist_data['playlist_owner'] = {
            'name': owner_v2.get('name'),
            'username': owner_v2.get('username'),
            'uri': owner_v2.get('uri'),
            'spotify_id': owner_v2.get('uri', '').split(':')[-1] if owner_v2.get('uri') else None,
            'avatar_url': get_deep(owner_v2, ['avatar', 'sources', 0, 'url']),
        }

    image_sources = get_deep(playlist_v2, ['images', 'items', 0, 'sources'], [])
    if image_sources:
        for source in image_sources:
            playlist_data['playlist_images'].append({
                'width': source.get('width'),
                'height': source.get('height'),
                'url': source.get('url')
            })
        playlist_cover_url = get_highest_resolution_url(image_sources)
        playlist_data['playlist_cover_image_url'] = playlist_cover_url
        playlist_data['playlist_info']['image_url'] = playlist_cover_url

    sharing_info = get_deep(playlist_v2, ['sharingInfo'], {})
    if sharing_info:
        playlist_data['playlist_sharing'] = {
            'share_id': sharing_info.get('shareId'),
            'share_url': sharing_info.get('shareUrl'),
        }

    members = get_deep(playlist_v2, ['members', 'items'], [])
    for member in members:
        member_data = get_deep(member, ['user', 'data'], {})
        if member_data:
            playlist_data['playlist_members'].append({
                'name': member_data.get('name'),
                'username': member_data.get('username'),
                'uri': member_data.get('uri'),
                'is_owner': member.get('isOwner', False),
                'permission_level': member.get('permissionLevel'),
                'avatar_url': get_deep(member_data, ['avatar', 'sources', 0, 'url']),
            })

    capabilities = get_deep(playlist_v2, ['currentUserCapabilities'], {})
    if capabilities:
        playlist_data['user_capabilities'] = {
            'can_view': capabilities.get('canView', False),
            'can_edit_items': capabilities.get('canEditItems', False),
            'can_administrate_permissions': capabilities.get('canAdministratePermissions', False),
            'can_mix_playlist': capabilities.get('canMixPlaylist', False),
            'can_abuse_report': capabilities.get('canAbuseReport', False),
        }

    return playlist_data


def iterate_playlist_chunks(playlist_handler):
    upper_limit = 343
    first_page = playlist_handler.get_playlist_info(limit=upper_limit)
    first_content = get_deep(first_page, ['data', 'playlistV2', 'content'])

    if not first_content:
        message = get_deep(first_page, ['data', 'playlistV2', 'message'])
        raise RuntimeError(message or "Playlist response did not contain track content.")

    yield first_content

    total_count = first_content.get('totalCount', 0)
    if total_count <= upper_limit:
        return

    offset = upper_limit
    while offset < total_count:
        page = playlist_handler.get_playlist_info(limit=upper_limit, offset=offset)
        content = get_deep(page, ['data', 'playlistV2', 'content'])
        if not content:
            break
        yield content
        offset += upper_limit


def save_json_file(path, payload):
    with open(path, "w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=4, ensure_ascii=False)


def delete_file_if_exists(path):
    file_path = Path(path)
    if file_path.exists():
        file_path.unlink()

def main():
    parser = argparse.ArgumentParser(description="Extract Spotify playlist metadata from a Spotify playlist link.")
    parser.add_argument("playlist_url", help="Spotify playlist link")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON file path. Defaults to a slugified playlist name.",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep the raw playlist dump as RAW_<playlist_name>.json instead of deleting it after export.",
    )
    args = parser.parse_args()

    playlist_id = extract_playlist_id(args.playlist_url)
    try:
        playlist_handler, playlist_info = fetch_playlist_handler(playlist_id)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return

    playlist_data = extract_playlist_details(playlist_info)
    raw_output_path = build_raw_path(playlist_data['playlist_info']['name'])

    raw_dump = {
        "raw_playlist_metadata": playlist_info,
        "raw_track_chunks": [],
    }
    
    print(f"[DEBUG] Processing playlist: {playlist_data['playlist_info']['name']}")
    print(f"[DEBUG] Playlist link id: {playlist_id}")
    print(f"[DEBUG] Owner: {playlist_data['playlist_owner'].get('name')}")
    print(f"[DEBUG] Members: {len(playlist_data['playlist_members'])}")
    print(f"[DEBUG] API total tracks reported: {playlist_data['playlist_info']['total_tracks']}")
    
    processed_count = 0
    skipped_count = 0
    
    for chunk_idx, chunk in enumerate(iterate_playlist_chunks(playlist_handler)):
        items = chunk.get('items', [])
        print(f"[DEBUG] Processing chunk {chunk_idx + 1} with {len(items)} items")
        raw_dump['raw_track_chunks'].append(chunk)

        for entry in items:
            track = extract_track_details(entry)
            if track:
                playlist_data['tracks'].append(track)
                processed_count += 1
            else:
                skipped_count += 1

    playlist_data['playlist_info']['created_at'] = get_earliest_timestamp(
        [track.get('added_to_playlist') for track in playlist_data['tracks']]
    )
    
    print(f"[DEBUG] Processed {processed_count} tracks, skipped {skipped_count}")

    playlist_data['playlist_info']['total_tracks'] = processed_count
    
    output_path = args.output or build_output_path(playlist_data['playlist_info']['name'])

    # Save raw snapshot first, then the parsed export
    save_json_file(raw_output_path, raw_dump)
    save_json_file(output_path, playlist_data)
    
    print(f"[SUCCESS] Saved complete playlist data to {output_path}")
    print(f"[SUCCESS] Saved raw playlist dump to {raw_output_path}")

    if not args.keep_raw:
        delete_file_if_exists(raw_output_path)
        print(f"[DEBUG] Removed temporary raw dump: {raw_output_path}")
    
    # Print sample
    if playlist_data['tracks']:
        print("\n[SAMPLE] First track:")
        sample = playlist_data['tracks'][0]
        print(f"  Title: {sample['title']}")
        print(f"  Artist(s): {', '.join([a['name'] for a in sample.get('artists', [])])}")
        print(f"  Album: {sample.get('album_name')}")
        print(f"  Release Date: {sample.get('release_date')}")
        print(f"  Duration: {sample.get('duration_sec')}s")
        print(f"  Spotify ID: {sample.get('spotify_id')}")
        print(f"  Added by: {sample.get('added_by', {}).get('name')}")
        print(f"  Added: {sample.get('added_to_playlist')}")

if __name__ == "__main__":
    main()