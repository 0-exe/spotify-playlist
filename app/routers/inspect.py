"""Playlist Inspector: filter, reorder, bulk-edit existing playlists."""
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
    fetch_playlist_tracks,
    filter_tracks,
    find_duplicates,
    sort_tracks,
    reorder_playlist_on_spotify,
    remove_tracks_from_playlist,
    create_spotify_playlist,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class InspectFilterRequest(BaseModel):
    playlist_id: str
    query: str = ""
    min_popularity: int = Field(0, ge=0, le=100)
    max_popularity: int = Field(100, ge=0, le=100)
    year_from: int = Field(0, ge=0)
    year_to: int = Field(9999, ge=0)
    weight_filter: str = Field("", description="banned|soft_banned|boosted|normal|''")
    sort_by: str = Field("popularity", description="popularity|release_date|artist_weight|vibe_score|name|artist")
    mood_for_vibe: str = Field("", description="If set, Gemini scores tracks for this mood")
    limit: int = Field(200, ge=1, le=1000)


class BulkRemoveRequest(BaseModel):
    playlist_id: str
    track_uris: list[str]


class ReorderRequest(BaseModel):
    playlist_id: str
    track_uris: list[str]
    sort_by: str = Field("popularity", description="popularity|release_date|artist_weight|vibe_score|name|artist")
    mood_for_vibe: str = ""


class SaveAsNewRequest(BaseModel):
    source_playlist_id: str
    track_ids: list[str]
    new_playlist_name: str
    description: str = ""


class DeduplicateRequest(BaseModel):
    playlist_id: str
    apply: bool = Field(False, description="If True, actually removes duplicates from Spotify")


@router.post("/inspect/filter")
async def inspect_filter(
    request: InspectFilterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Load a playlist and apply live filters + optional Gemini vibe scoring."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    # Fetch artist weights
    result = await db.execute(select(ArtistWeight))
    artist_weights = {row.artist_id: row.weight for row in result.scalars().all()}

    # Fetch tracks
    tracks = fetch_playlist_tracks(sp, request.playlist_id, max_tracks=1000)

    # Apply filters
    filtered = filter_tracks(
        tracks,
        query=request.query,
        min_popularity=request.min_popularity,
        max_popularity=request.max_popularity,
        year_from=request.year_from or 0,
        year_to=request.year_to or 9999,
        artist_weights=artist_weights,
        weight_filter=request.weight_filter,
    )

    # Annotate weights
    for t in filtered:
        t["artist_weight"] = artist_weights.get(t["artist_id"], 1.0)

    # Optional vibe scoring
    vibe_scores: dict[str, float] = {}
    if request.mood_for_vibe and filtered:
        vibe_scores = await batch_score_tracks(filtered[:100], request.mood_for_vibe)
        for t in filtered:
            t["vibe_score"] = vibe_scores.get(t["id"], 5.0)

    # Sort
    sorted_tracks = sort_tracks(
        filtered,
        sort_by=request.sort_by,
        artist_weights=artist_weights,
        vibe_scores=vibe_scores,
    )

    return {
        "tracks": sorted_tracks[: request.limit],
        "total": len(sorted_tracks),
        "filters_applied": {
            "query": request.query,
            "min_popularity": request.min_popularity,
            "max_popularity": request.max_popularity,
            "year_from": request.year_from,
            "year_to": request.year_to,
            "weight_filter": request.weight_filter,
            "sort_by": request.sort_by,
        },
    }


@router.post("/inspect/duplicates")
async def inspect_duplicates(request: DeduplicateRequest):
    """Find (and optionally remove) duplicate tracks in a playlist."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    tracks = fetch_playlist_tracks(sp, request.playlist_id, max_tracks=1000)
    dupe_ids = find_duplicates(tracks)
    dupe_uris = [t["uri"] for t in tracks if t["id"] in dupe_ids]

    removed = False
    if request.apply and dupe_uris:
        removed = remove_tracks_from_playlist(sp, request.playlist_id, dupe_uris)

    return {
        "duplicate_count": len(dupe_ids),
        "duplicate_ids": dupe_ids,
        "removed": removed,
    }


@router.post("/inspect/bulk-remove")
async def bulk_remove(request: BulkRemoveRequest):
    """Remove a list of tracks from a playlist."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    success = remove_tracks_from_playlist(sp, request.playlist_id, request.track_uris)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to remove tracks")

    return {"removed": len(request.track_uris), "playlist_id": request.playlist_id}


@router.post("/inspect/reorder")
async def reorder_playlist(
    request: ReorderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Sort a playlist by the given criteria and save the new order to Spotify."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    result = await db.execute(select(ArtistWeight))
    artist_weights = {row.artist_id: row.weight for row in result.scalars().all()}

    tracks = fetch_playlist_tracks(sp, request.playlist_id, max_tracks=1000)

    vibe_scores: dict[str, float] = {}
    if request.mood_for_vibe and tracks:
        vibe_scores = await batch_score_tracks(tracks[:100], request.mood_for_vibe)

    sorted_tracks = sort_tracks(
        tracks,
        sort_by=request.sort_by,
        artist_weights=artist_weights,
        vibe_scores=vibe_scores,
    )

    uris = [t["uri"] for t in sorted_tracks]
    success = reorder_playlist_on_spotify(sp, request.playlist_id, uris)

    return {
        "success": success,
        "reordered_count": len(sorted_tracks),
        "sort_by": request.sort_by,
    }


@router.post("/inspect/save-as-new")
async def save_as_new_playlist(request: SaveAsNewRequest):
    """Save a filtered subset of tracks as a brand-new playlist."""
    sp = get_spotify_client()
    if not sp:
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")

    # Fetch source tracks and filter to requested IDs
    all_tracks = fetch_playlist_tracks(sp, request.source_playlist_id, max_tracks=1000)
    id_set = set(request.track_ids)
    selected = [t for t in all_tracks if t["id"] in id_set]

    if not selected:
        raise HTTPException(status_code=400, detail="No matching tracks found")

    info = create_spotify_playlist(sp, selected, request.new_playlist_name, request.description)
    return info
