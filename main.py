"""
Spotify AI Playlist Generator - Main Application
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routers import auth, playlist, artists, devices, library, inspect, settings_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    settings = get_settings()
    logger.info("Starting Spotify AI Playlist Generator...")
    
    # Validate required environment variables
    missing = []
    if not settings.spotipy_client_id:
        missing.append("SPOTIPY_CLIENT_ID")
    if not settings.spotipy_client_secret:
        missing.append("SPOTIPY_CLIENT_SECRET")
    if not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    
    if missing:
        logger.warning(f"Missing environment variables: {', '.join(missing)}")
        logger.warning("App will start but some features will be unavailable.")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized.")
    
    yield
    
    logger.info("Shutting down...")


app = FastAPI(
    title="Spotify AI Playlist Generator & Power-User Suite",
    description="Generate, mix, and inspect Spotify playlists using Gemini AI and Spotipy",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Include routers
app.include_router(auth.router, tags=["auth"])
app.include_router(playlist.router, prefix="/api", tags=["playlist"])
app.include_router(library.router, prefix="/api", tags=["library"])
app.include_router(inspect.router, prefix="/api", tags=["inspect"])
app.include_router(artists.router, prefix="/api", tags=["artists"])
app.include_router(devices.router, prefix="/api", tags=["devices"])
app.include_router(settings_router.router, prefix="/api", tags=["settings"])


@app.get("/")
async def index(request: Request):
    """Serve the main UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "ok",
        "spotify_configured": bool(settings.spotipy_client_id and settings.spotipy_client_secret),
        "gemini_configured": bool(settings.gemini_api_key),
    }
