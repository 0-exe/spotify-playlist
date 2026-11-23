"""Auth router — supports dynamic multi-domain callbacks (IP, DuckDNS, Local Domain) + headless OAuth."""
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
import spotipy

from app.config import get_settings
from app.spotify_client import get_spotify_oauth, get_spotify_client, clear_spotify_cache, inject_token_from_url

logger = logging.getLogger(__name__)
router = APIRouter()


def detect_redirect_uri(request: Request) -> str:
    """
    Dynamically detect the caller's redirect URI (supports Nginx Proxy Manager,
    direct IP, DuckDNS, and custom local domains).
    """
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        return f"{proto}://{host}/callback"
    return get_settings().spotipy_redirect_uri


@router.get("/login")
async def login(request: Request):
    """Redirect user to Spotify authorization page using dynamic callback URL."""
    settings = get_settings()
    if not settings.spotipy_client_id or not settings.spotipy_client_secret:
        raise HTTPException(
            status_code=503,
            detail="Spotify credentials not configured. Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET in .env",
        )
    redirect_uri = detect_redirect_uri(request)
    auth_manager = get_spotify_oauth(redirect_uri=redirect_uri)
    auth_url = auth_manager.get_authorize_url()
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def callback(request: Request, code: str = None, error: str = None):
    """Handle Spotify OAuth callback."""
    if error:
        return RedirectResponse(url=f"/?error={error}")
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received")

    redirect_uri = detect_redirect_uri(request)
    auth_manager = get_spotify_oauth(redirect_uri=redirect_uri)
    token_info = auth_manager.get_access_token(code)
    if not token_info:
        raise HTTPException(status_code=400, detail="Failed to get access token")

    return RedirectResponse(url="/")


@router.get("/logout")
async def logout():
    """Clear Spotify cache and log out."""
    clear_spotify_cache()
    return RedirectResponse(url="/")


@router.get("/api/auth/status")
async def auth_status():
    """Check if user is authenticated with Spotify."""
    try:
        sp = get_spotify_client()
        if sp:
            user = sp.current_user()
            return {
                "authenticated": True,
                "user": {
                    "id": user.get("id"),
                    "display_name": user.get("display_name"),
                    "email": user.get("email"),
                    "image": user.get("images", [{}])[0].get("url") if user.get("images") else None,
                },
            }
    except Exception as e:
        logger.debug(f"Auth check failed: {e}")

    return {"authenticated": False, "user": None}


class ManualTokenRequest(BaseModel):
    callback_url: str


@router.post("/api/auth/manual-token")
async def manual_token(request: ManualTokenRequest):
    """
    Headless Docker fallback: accepts a full Spotify callback URL
    and exchanges the code for a token.
    """
    success = inject_token_from_url(request.callback_url)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to exchange token. Check the URL and try again.")
    return {"success": True, "message": "Token saved successfully. You are now authenticated."}
