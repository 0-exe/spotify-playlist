"""Spotify client singleton and helpers.

Cache path is stored in data/.spotify_cache so the Docker volume mount
at /app/data persists both the SQLite DB and the OAuth token.
"""
import os
import logging
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from app.config import get_settings

logger = logging.getLogger(__name__)


def _cache_path() -> str:
    settings = get_settings()
    path = settings.spotify_cache_path
    # Ensure parent directory exists (data/ folder)
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    return path


def get_spotify_oauth() -> SpotifyOAuth:
    """Create a SpotifyOAuth manager."""
    settings = get_settings()
    return SpotifyOAuth(
        client_id=settings.spotipy_client_id,
        client_secret=settings.spotipy_client_secret,
        redirect_uri=settings.spotipy_redirect_uri,
        scope=settings.spotify_scopes,
        cache_path=_cache_path(),
        open_browser=False,
    )


def get_spotify_client() -> spotipy.Spotify | None:
    """Return an authenticated Spotify client or None."""
    settings = get_settings()
    if not settings.spotipy_client_id or not settings.spotipy_client_secret:
        return None

    try:
        auth_manager = get_spotify_oauth()
        token_info = auth_manager.get_cached_token()

        if not token_info:
            return None

        if auth_manager.is_token_expired(token_info):
            token_info = auth_manager.refresh_access_token(token_info["refresh_token"])

        return spotipy.Spotify(auth_manager=auth_manager)
    except Exception as e:
        logger.error(f"Failed to create Spotify client: {e}")
        return None


def inject_token_from_url(callback_url: str) -> bool:
    """
    Headless Docker fallback: parse a full callback URL and exchange the code
    for a token, caching it for future requests.

    Useful when Docker runs on Proxmox-LAN-IP but the browser redirects to
    127.0.0.1 — user copies the full redirect URL and pastes it here.
    """
    try:
        auth_manager = get_spotify_oauth()
        code = auth_manager.parse_response_code(callback_url)
        token_info = auth_manager.get_access_token(code, as_dict=True, check_cache=False)
        return bool(token_info)
    except Exception as e:
        logger.error(f"Failed to inject token from URL: {e}")
        return False


def clear_spotify_cache():
    """Remove the Spotify token cache."""
    path = _cache_path()
    if os.path.exists(path):
        os.remove(path)
        logger.info("Spotify cache cleared.")
