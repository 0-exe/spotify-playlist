"""Core playlist generation, merge logic, scoring and artist weighting."""
import logging
import time
from typing import Any

import spotipy

logger = logging.getLogger(__name__)

SOFTBAN_MAX_SONGS = 2
DEFAULT_ARTIST_CAP = 3


# ─────────────────────────────────────────────
# Scoring helpers
# ─────────────────────────────────────────────

def compute_final_score(popularity: int, artist_weight: float) -> float:
    """Score = popularity * artist_weight. Range 0–200."""
    return popularity * artist_weight


def compute_merge_score(
    popularity: int,
    artist_weight: float,
    vibe_score: float,
    *,
    popularity_weight: float = 0.4,
    vibe_weight: float = 0.4,
    artist_weight_factor: float = 0.2,
) -> float:
    """
    Combined score for multi-playlist merge mode.

    Score = popularity_norm * pw + vibe_norm * vw + artist_weight_norm * aw
    All components normalised to 0–100.
    """
    pop_norm = popularity  # 0–100
    vibe_norm = vibe_score * 10  # 0–10 → 0–100
    aw_norm = min(artist_weight, 2.0) * 50  # 0–2 → 0–100

    return pop_norm * popularity_weight + vibe_norm * vibe_weight + aw_norm * artist_weight_factor


# ─────────────────────────────────────────────
# Artist cap / scoring pipeline
# ─────────────────────────────────────────────

def apply_artist_cap(
    tracks: list[dict[str, Any]],
    artist_weights: dict[str, float],
    sort_mode: str = "popularity",
    playlist_limit: int = 40,
) -> list[dict[str, Any]]:
    """
    Deduplicate, annotate with weights/scores, sort, apply per-artist caps.
    """
    seen_ids: set[str] = set()
    unique_tracks = []
    for t in tracks:
        if t["id"] not in seen_ids:
            seen_ids.add(t["id"])
            unique_tracks.append(t)

    for track in unique_tracks:
        aid = track["artist_id"]
        weight = artist_weights.get(aid, 1.0)
        track["artist_weight"] = weight
        track["final_score"] = compute_final_score(track["popularity"], weight)

    eligible = [t for t in unique_tracks if t["artist_weight"] > 0]

    if sort_mode == "hidden_gems":
        eligible.sort(key=lambda t: (-(t["final_score"] if t["popularity"] < 55 else 0), t["popularity"]))
    else:
        eligible.sort(key=lambda t: -t["final_score"])

    artist_song_count: dict[str, int] = {}
    result = []

    for track in eligible:
        aid = track["artist_id"]
        weight = track["artist_weight"]
        count = artist_song_count.get(aid, 0)

        if weight < 0.5:
            cap = SOFTBAN_MAX_SONGS
            if track["popularity"] < 70 and count >= 1:
                continue
        elif sort_mode == "balanced":
            cap = DEFAULT_ARTIST_CAP
        else:
            cap = playlist_limit

        if count >= cap:
            continue

        result.append(track)
        artist_song_count[aid] = count + 1

        if len(result) >= playlist_limit:
            break

    return result


def apply_merge_pipeline(
    tracks: list[dict[str, Any]],
    artist_weights: dict[str, float],
    vibe_scores: dict[str, float],
    min_popularity: int = 0,
    min_vibe_score: float = 0.0,
    playlist_limit: int = 40,
    sort_mode: str = "popularity",
) -> list[dict[str, Any]]:
    """
    Full merge pipeline:
    1. Deduplicate
    2. Hard-ban filter (weight == 0)
    3. Popularity hard filter
    4. Annotate with vibe score + merge_score
    5. Vibe score hard filter
    6. Sort by merge_score
    7. Artist cap
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for t in tracks:
        if t["id"] not in seen:
            seen.add(t["id"])
            unique.append(t)

    result = []
    for t in unique:
        aid = t["artist_id"]
        weight = artist_weights.get(aid, 1.0)
        if weight <= 0:
            continue
        if t["popularity"] < min_popularity:
            continue

        vibe = vibe_scores.get(t["id"], 5.0)
        if vibe < min_vibe_score:
            continue

        t["artist_weight"] = weight
        t["vibe_score"] = vibe
        t["final_score"] = compute_merge_score(t["popularity"], weight, vibe)
        result.append(t)

    result.sort(key=lambda t: -t["final_score"])

    # Artist cap
    artist_count: dict[str, int] = {}
    capped: list[dict[str, Any]] = []
    for t in result:
        aid = t["artist_id"]
        weight = t["artist_weight"]
        count = artist_count.get(aid, 0)

        if weight < 0.5:
            cap = SOFTBAN_MAX_SONGS
            if t["popularity"] < 70 and count >= 1:
                continue
        elif sort_mode == "balanced":
            cap = DEFAULT_ARTIST_CAP
        else:
            cap = playlist_limit

        if count >= cap:
            continue

        capped.append(t)
        artist_count[aid] = count + 1
        if len(capped) >= playlist_limit:
            break

    return capped


# ─────────────────────────────────────────────
# Library helpers
# ─────────────────────────────────────────────

def extract_track_dict(item: Any) -> dict[str, Any] | None:
    """Normalise a raw Spotify track object into our standard dict."""
    if not item:
        return None
    artists = item.get("artists", [{}])
    primary = artists[0] if artists else {}
    album = item.get("album", {})
    images = album.get("images", [{}])
    release_date = album.get("release_date", "")
    release_year = release_date[:4] if release_date else ""
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "artist_id": primary.get("id", ""),
        "artist_name": primary.get("name", "Unknown"),
        "all_artists": [a.get("name", "") for a in artists],
        "popularity": item.get("popularity", 0),
        "album_name": album.get("name", ""),
        "album_image": images[0].get("url", "") if images else "",
        "preview_url": item.get("preview_url") or "",
        "spotify_url": item.get("external_urls", {}).get("spotify", ""),
        "uri": item.get("uri", ""),
        "duration_ms": item.get("duration_ms", 0),
        "release_year": release_year,
    }


def fetch_playlist_tracks(
    sp: spotipy.Spotify,
    playlist_id: str,
    max_tracks: int = 500,
) -> list[dict[str, Any]]:
    """Fetch all tracks from a Spotify playlist (paginated)."""
    tracks = []
    offset = 0
    fields = "items(track(id,name,artists,album,popularity,preview_url,external_urls,uri,duration_ms)),next"

    while len(tracks) < max_tracks:
        try:
            result = sp.playlist_tracks(
                playlist_id,
                fields=fields,
                limit=100,
                offset=offset,
            )
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                time.sleep(int(getattr(e, "headers", {}).get("Retry-After", 2)))
                continue
            raise

        items = result.get("items", [])
        for item in items:
            track = item.get("track") if item else None
            if not track or not track.get("id"):
                continue
            td = extract_track_dict(track)
            if td:
                tracks.append(td)

        if not result.get("next") or len(items) == 0:
            break
        offset += len(items)

    return tracks


def fetch_liked_songs(
    sp: spotipy.Spotify,
    max_tracks: int = 500,
) -> list[dict[str, Any]]:
    """Fetch user's liked songs (saved tracks), paginated."""
    tracks = []
    offset = 0

    while len(tracks) < max_tracks:
        try:
            result = sp.current_user_saved_tracks(limit=50, offset=offset)
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                time.sleep(int(getattr(e, "headers", {}).get("Retry-After", 2)))
                continue
            raise

        items = result.get("items", [])
        for item in items:
            track = item.get("track") if item else None
            if not track or not track.get("id"):
                continue
            td = extract_track_dict(track)
            if td:
                tracks.append(td)

        if not result.get("next") or len(items) == 0:
            break
        offset += len(items)

    return tracks


def fetch_user_playlists(sp: spotipy.Spotify) -> list[dict[str, Any]]:
    """Fetch all playlists owned or followed by the current user."""
    playlists = []
    offset = 0

    while True:
        result = sp.current_user_playlists(limit=50, offset=offset)
        items = result.get("items", [])
        for pl in items:
            if not pl:
                continue
            images = pl.get("images", [{}]) or [{}]
            playlists.append({
                "id": pl.get("id", ""),
                "name": pl.get("name", ""),
                "description": pl.get("description", ""),
                "track_count": pl.get("tracks", {}).get("total", 0),
                "owner": pl.get("owner", {}).get("display_name", ""),
                "image": images[0].get("url", "") if images else "",
                "public": pl.get("public", False),
                "collaborative": pl.get("collaborative", False),
                "spotify_url": pl.get("external_urls", {}).get("spotify", ""),
            })
        if not result.get("next") or len(items) == 0:
            break
        offset += len(items)

    return playlists


# ─────────────────────────────────────────────
# Playlist inspector helpers
# ─────────────────────────────────────────────

def filter_tracks(
    tracks: list[dict[str, Any]],
    *,
    query: str = "",
    min_popularity: int = 0,
    max_popularity: int = 100,
    year_from: int = 0,
    year_to: int = 9999,
    artist_ids: list[str] | None = None,
    artist_weights: dict[str, float] | None = None,
    weight_filter: str = "",  # "banned"|"soft_banned"|"boosted"|"normal"|""
) -> list[dict[str, Any]]:
    """Filter a list of tracks by various criteria."""
    result = []
    q = query.lower()
    aw = artist_weights or {}

    for t in tracks:
        if min_popularity > 0 and t.get("popularity", 0) < min_popularity:
            continue
        if t.get("popularity", 0) > max_popularity:
            continue

        yr = int(t.get("release_year", "0") or "0")
        if yr and (yr < year_from or yr > year_to):
            continue

        if artist_ids and t.get("artist_id") not in artist_ids:
            continue

        if q:
            searchable = f"{t.get('name','')} {t.get('artist_name','')} {t.get('album_name','')}".lower()
            if q not in searchable:
                continue

        if weight_filter:
            w = aw.get(t.get("artist_id", ""), 1.0)
            if weight_filter == "banned" and w != 0.0:
                continue
            elif weight_filter == "soft_banned" and not (0 < w < 0.5):
                continue
            elif weight_filter == "boosted" and w <= 1.0:
                continue
            elif weight_filter == "normal" and w != 1.0:
                continue

        result.append(t)

    return result


def find_duplicates(tracks: list[dict[str, Any]]) -> list[str]:
    """Return list of duplicate track IDs (all occurrences after the first)."""
    seen: set[str] = set()
    dupes: list[str] = []
    for t in tracks:
        tid = t["id"]
        if tid in seen:
            dupes.append(tid)
        else:
            seen.add(tid)
    return dupes


def sort_tracks(
    tracks: list[dict[str, Any]],
    sort_by: str,
    artist_weights: dict[str, float] | None = None,
    vibe_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Sort tracks by various criteria."""
    aw = artist_weights or {}
    vs = vibe_scores or {}

    if sort_by == "popularity":
        return sorted(tracks, key=lambda t: -t.get("popularity", 0))
    elif sort_by == "release_date":
        return sorted(tracks, key=lambda t: -(int(t.get("release_year") or 0)))
    elif sort_by == "artist_weight":
        return sorted(tracks, key=lambda t: -aw.get(t.get("artist_id", ""), 1.0))
    elif sort_by == "vibe_score":
        return sorted(tracks, key=lambda t: -vs.get(t.get("id", ""), 5.0))
    elif sort_by == "name":
        return sorted(tracks, key=lambda t: t.get("name", "").lower())
    elif sort_by == "artist":
        return sorted(tracks, key=lambda t: t.get("artist_name", "").lower())
    return tracks


def reorder_playlist_on_spotify(
    sp: spotipy.Spotify,
    playlist_id: str,
    ordered_track_uris: list[str],
) -> bool:
    """Replace a playlist's track order with the given URI list."""
    try:
        # Spotify limits replace to 100 tracks; use replace + add for more
        sp.playlist_replace_items(playlist_id, ordered_track_uris[:100])
        if len(ordered_track_uris) > 100:
            for i in range(100, len(ordered_track_uris), 100):
                sp.playlist_add_items(playlist_id, ordered_track_uris[i : i + 100])
        return True
    except Exception as e:
        logger.error(f"Failed to reorder playlist {playlist_id}: {e}")
        return False


def remove_tracks_from_playlist(
    sp: spotipy.Spotify,
    playlist_id: str,
    track_uris: list[str],
) -> bool:
    """Remove specific tracks from a Spotify playlist."""
    try:
        # Batch in groups of 100
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i : i + 100]
            sp.playlist_remove_all_occurrences_of_items(playlist_id, batch)
        return True
    except Exception as e:
        logger.error(f"Failed to remove tracks from playlist {playlist_id}: {e}")
        return False


# ─────────────────────────────────────────────
# Original search helpers (unchanged)
# ─────────────────────────────────────────────

def search_spotify_tracks(
    sp: spotipy.Spotify,
    search_strategy: dict[str, Any],
    max_per_query: int = 20,
) -> list[dict[str, Any]]:
    """Search Spotify for tracks using the AI-generated search strategy."""
    all_tracks = []
    seen_ids: set[str] = set()

    def _add(items: list) -> None:
        for item in items or []:
            if not item or item.get("id") in seen_ids:
                continue
            seen_ids.add(item["id"])
            td = extract_track_dict(item)
            if td:
                all_tracks.append(td)

    queries = search_strategy.get("search_queries", [])
    advanced_queries = search_strategy.get("search_track_queries", [])

    for query in queries + advanced_queries:
        try:
            results = sp.search(q=query, type="track", limit=max_per_query)
            _add(results.get("tracks", {}).get("items", []))
            time.sleep(0.1)
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                time.sleep(int(getattr(e, "headers", {}).get("Retry-After", 2)))
            else:
                logger.error(f"Spotify search error for '{query}': {e}")

    for query in search_strategy.get("playlist_queries", [])[:3]:
        try:
            results = sp.search(q=query, type="playlist", limit=5)
            for pl in (results.get("playlists", {}).get("items", []) or [])[:3]:
                if not pl:
                    continue
                try:
                    pl_tracks = sp.playlist_tracks(
                        pl["id"],
                        fields="items(track(id,name,artists,album,popularity,preview_url,external_urls,uri,duration_ms))",
                        limit=30,
                    )
                    _add([i["track"] for i in pl_tracks.get("items", []) if i and i.get("track")])
                    time.sleep(0.1)
                except Exception as ex:
                    logger.warning(f"Failed to get tracks from playlist {pl.get('id')}: {ex}")
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                time.sleep(int(getattr(e, "headers", {}).get("Retry-After", 2)))
            else:
                logger.error(f"Spotify playlist search error for '{query}': {e}")

    return all_tracks


def create_spotify_playlist(
    sp: spotipy.Spotify,
    tracks: list[dict[str, Any]],
    playlist_name: str,
    description: str = "",
) -> dict[str, Any]:
    """Create or update a Spotify playlist with the given tracks."""
    user_id = sp.current_user()["id"]
    existing_playlist = None
    offset = 0

    while True:
        playlists = sp.current_user_playlists(limit=50, offset=offset)
        for pl in playlists.get("items", []):
            if pl and pl.get("name") == playlist_name:
                existing_playlist = pl
                break
        if existing_playlist or not playlists.get("next"):
            break
        offset += 50

    if existing_playlist:
        pl_id = existing_playlist["id"]
        sp.playlist_change_details(pl_id, description=description)
        sp.playlist_replace_items(pl_id, [t["uri"] for t in tracks[:100]])
        if len(tracks) > 100:
            for i in range(100, len(tracks), 100):
                sp.playlist_add_items(pl_id, [t["uri"] for t in tracks[i : i + 100]])
        logger.info(f"Updated existing playlist: {playlist_name}")
    else:
        pl = sp.user_playlist_create(
            user=user_id,
            name=playlist_name,
            public=True,
            description=description,
        )
        pl_id = pl["id"]
        sp.playlist_add_items(pl_id, [t["uri"] for t in tracks[:100]])
        if len(tracks) > 100:
            for i in range(100, len(tracks), 100):
                sp.playlist_add_items(pl_id, [t["uri"] for t in tracks[i : i + 100]])
        logger.info(f"Created new playlist: {playlist_name}")

    result = sp.playlist(pl_id)
    return {
        "id": pl_id,
        "name": result.get("name"),
        "url": result.get("external_urls", {}).get("spotify", ""),
        "uri": result.get("uri", ""),
        "tracks_added": len(tracks),
    }


def start_playback(
    sp: spotipy.Spotify,
    playlist_uri: str,
    device_name: str | None = None,
) -> bool:
    """Start playback of a playlist on a device."""
    try:
        device_id = None
        if device_name:
            devices = sp.devices()
            for dev in devices.get("devices", []):
                if dev.get("name", "").lower() == device_name.lower():
                    device_id = dev["id"]
                    break
            if not device_id:
                logger.warning(f"Device '{device_name}' not found, using active device.")

        sp.start_playback(device_id=device_id, context_uri=playlist_uri)
        return True
    except Exception as e:
        logger.error(f"Failed to start playback: {e}")
        return False
