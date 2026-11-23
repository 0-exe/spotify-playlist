"""Library endpoints: user playlists, liked songs, merge-playlists."""
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, ArtistWeight
from app.spotify_client import get_spotify_client
from app.gemini_service import batch_score_tracks
from app.playlist_generator import (
    fetch_user_playlists,
    fetch_playlist_tracks,
    fetch_liked_songs,
    apply_merge_pipeline,
    create_spotify_playlist,
    start_playback,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/library/playlists")
async def get_user_playlists():
    """Return all playlists owned/followed by the authenticated user."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")
    try:
        playlists = fetch_user_playlists(sp)
        return {"playlists": playlists, "total": len(playlists)}
    except Exception as e:
        logger.error(f"Failed to fetch playlists: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/library/playlists/{playlist_id}/tracks")
async def get_playlist_tracks(playlist_id: str, max_tracks: int = 500):
    """Return all tracks of a specific playlist."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")
    try:
        tracks = fetch_playlist_tracks(sp, playlist_id, max_tracks=max_tracks)
        return {"tracks": tracks, "total": len(tracks)}
    except Exception as e:
        logger.error(f"Failed to fetch playlist {playlist_id} tracks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/library/liked-songs")
async def get_liked_songs(max_tracks: int = 500):
    """Return user's liked/saved songs."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")
    try:
        tracks = fetch_liked_songs(sp, max_tracks=max_tracks)
        return {"tracks": tracks, "total": len(tracks)}
    except Exception as e:
        logger.error(f"Failed to fetch liked songs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Merge Playlists ──────────────────────────────────────────────────────────

class MergeRequest(BaseModel):
    """
    Request body for POST /api/merge-playlists.
    Usable directly from Home Assistant rest_command.
    """
    prompt: str = Field(..., description="Mood/vibe for Gemini scoring")
    playlist_ids: list[str] = Field(default=[], description="Spotify playlist IDs to merge")
    playlist_names: list[str] = Field(default=[], description="Playlist names (resolved to IDs)")
    include_liked_songs: bool = Field(False, description="Include liked songs as source")
    min_popularity: int = Field(0, ge=0, le=100, description="Minimum popularity hard filter")
    min_vibe_score: float = Field(0.0, ge=0.0, le=10.0, description="Minimum Gemini vibe score")
    limit: int = Field(40, ge=5, le=200)
    sort_mode: str = Field("popularity", description="popularity | balanced | hidden_gems")
    create_on_spotify: bool = Field(False)
    target_playlist_name: str = Field("", description="Target playlist name")
    device_name: str = Field("")
    start_playback_after: bool = Field(False)
    use_ai_scoring: bool = Field(True, description="Use Gemini to score tracks (slower but better)")


class MergeResponse(BaseModel):
    tracks: list[dict[str, Any]]
    playlist: dict[str, Any] | None = None
    total_candidates: int
    after_popularity_filter: int
    after_vibe_filter: int
    mood_description: str


@router.post("/merge-playlists", response_model=MergeResponse)
async def merge_playlists(
    request: MergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Two-stage AI-powered merge of multiple playlists:
    1. Hard filter by popularity + artist weights
    2. Gemini vibe scoring
    
    Can be called from Home Assistant as a rest_command.
    """
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    # 1. Resolve playlist names → IDs if needed
    ids_to_fetch: list[str] = list(request.playlist_ids)
    if request.playlist_names:
        all_playlists = fetch_user_playlists(sp)
        name_to_id = {pl["name"]: pl["id"] for pl in all_playlists}
        for name in request.playlist_names:
            pid = name_to_id.get(name)
            if pid and pid not in ids_to_fetch:
                ids_to_fetch.append(pid)
            elif not pid:
                logger.warning(f"Playlist name not found: {name!r}")

    # 2. Load all tracks from selected sources
    all_tracks: list[dict[str, Any]] = []
    for pid in ids_to_fetch:
        logger.info(f"Loading playlist {pid}...")
        tracks = fetch_playlist_tracks(sp, pid, max_tracks=500)
        all_tracks.extend(tracks)

    if request.include_liked_songs:
        logger.info("Loading liked songs...")
        liked = fetch_liked_songs(sp, max_tracks=500)
        all_tracks.extend(liked)

    total_candidates = len(all_tracks)
    logger.info(f"Total tracks collected: {total_candidates}")

    if total_candidates == 0:
        raise HTTPException(status_code=400, detail="No tracks found in selected sources")

    # 3. Load artist weights from DB
    result = await db.execute(select(ArtistWeight))
    artist_weights = {row.artist_id: row.weight for row in result.scalars().all()}

    # 4. Stage 1: Deduplicate + hard filters (popularity + artist weight)
    seen: set[str] = set()
    stage1: list[dict[str, Any]] = []
    for t in all_tracks:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        w = artist_weights.get(t["artist_id"], 1.0)
        if w <= 0:
            continue  # hard-banned
        if t["popularity"] < request.min_popularity:
            continue
        stage1.append(t)

    after_popularity_filter = len(stage1)
    logger.info(f"After hard filters: {after_popularity_filter} tracks")

    # 5. Stage 2: Gemini vibe scoring
    vibe_scores: dict[str, float] = {}
    if request.use_ai_scoring and stage1:
        logger.info(f"Scoring {after_popularity_filter} tracks with Gemini for mood: {request.prompt!r}")
        vibe_scores = await batch_score_tracks(stage1, request.prompt)
    else:
        vibe_scores = {t["id"]: 5.0 for t in stage1}

    # 6. Apply merge pipeline
    final_tracks = apply_merge_pipeline(
        stage1,
        artist_weights,
        vibe_scores,
        min_popularity=0,  # already filtered
        min_vibe_score=request.min_vibe_score,
        playlist_limit=request.limit,
        sort_mode=request.sort_mode,
    )

    after_vibe_filter = len(final_tracks)
    logger.info(f"Final merged playlist: {after_vibe_filter} tracks")

    # 7. Optionally create on Spotify
    playlist_info = None
    if request.create_on_spotify and final_tracks:
        name = request.target_playlist_name or f"🎵 Merge: {request.prompt[:35]}"
        desc = f"AI-merged playlist | Mood: {request.prompt} | {after_vibe_filter} tracks"
        playlist_info = create_spotify_playlist(sp, final_tracks, name, desc)

        if request.start_playback_after and playlist_info:
            start_playback(sp, playlist_info["uri"], request.device_name or None)

    return MergeResponse(
        tracks=final_tracks,
        playlist=playlist_info,
        total_candidates=total_candidates,
        after_popularity_filter=after_popularity_filter,
        after_vibe_filter=after_vibe_filter,
        mood_description=request.prompt,
    )
