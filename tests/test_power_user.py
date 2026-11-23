"""
Comprehensive tests for Power-User features:
- Multi-Playlist Merging & Deduplication
- Popularity Pre-Filter & Artist Weights (Hard-Ban, Soft-Ban, Boost)
- Batch Gemini Vibe Scoring (mocked)
- Internal Playlist Inspector: Filtering, Duplicates Detection, Reordering
- REST Endpoint POST /api/merge-playlists (FastAPI TestClient)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.playlist_generator import (
    compute_merge_score,
    apply_merge_pipeline,
    filter_tracks,
    find_duplicates,
    sort_tracks,
    extract_track_dict,
)
from app.gemini_service import batch_score_tracks
from main import app


def make_track(
    track_id: str,
    name: str,
    artist_id: str,
    artist_name: str,
    popularity: int,
    release_year: str = "2020",
    album_name: str = "Test Album",
) -> dict:
    return {
        "id": track_id,
        "name": name,
        "artist_id": artist_id,
        "artist_name": artist_name,
        "all_artists": [artist_name],
        "popularity": popularity,
        "album_name": album_name,
        "album_image": "",
        "preview_url": "",
        "spotify_url": f"https://open.spotify.com/track/{track_id}",
        "uri": f"spotify:track:{track_id}",
        "duration_ms": 180000,
        "release_year": release_year,
    }


SAMPLE_TRACKS = [
    make_track("t1", "Pop Banger 1", "art_1", "Famous Artist", 85, "2015"),
    make_track("t2", "Pop Banger 2", "art_1", "Famous Artist", 80, "2016"),
    make_track("t3", "Pop Banger 3", "art_1", "Famous Artist", 75, "2017"),
    make_track("t4", "Slow Ballad", "art_2", "Ballad Singer", 65, "2010"),
    make_track("t5", "Indie Gem", "art_3", "Indie Creator", 45, "2022"),
    make_track("t6", "Techno Beat", "art_4", "DJ Producer", 70, "2023"),
    make_track("t7", "Low Filler", "art_5", "Unknown Guy", 20, "2005"),
]


# ==============================================================================
# 1. Scoring & Merge Pipeline Tests
# ==============================================================================

class TestMergeScoring:
    def test_compute_merge_score_components(self):
        # 100 pop, 10 vibe, 2.0 artist weight -> max possible score = 40 + 40 + 20 = 100
        score = compute_merge_score(popularity=100, artist_weight=2.0, vibe_score=10.0)
        assert pytest.approx(score, 0.01) == 100.0

    def test_compute_merge_score_low_vibe(self):
        # High pop (90), zero vibe (0), normal artist weight (1.0)
        # Pop: 90 * 0.4 = 36. Vibe: 0. AW: 1.0*50 * 0.2 = 10. Total = 46
        score = compute_merge_score(popularity=90, artist_weight=1.0, vibe_score=0.0)
        assert pytest.approx(score, 0.01) == 46.0


class TestMergePipeline:
    def test_deduplication_in_merge(self):
        tracks_with_dupes = SAMPLE_TRACKS + [
            make_track("t1", "Pop Banger 1", "art_1", "Famous Artist", 85)
        ]
        result = apply_merge_pipeline(
            tracks_with_dupes,
            artist_weights={},
            vibe_scores={},
            min_popularity=0,
            playlist_limit=50,
        )
        ids = [t["id"] for t in result]
        assert len(ids) == len(set(ids)), "Duplikate wurden nicht gefiltert"

    def test_min_popularity_hard_filter(self):
        result = apply_merge_pipeline(
            SAMPLE_TRACKS,
            artist_weights={},
            vibe_scores={},
            min_popularity=60,
        )
        for t in result:
            assert t["popularity"] >= 60
        assert "t5" not in [t["id"] for t in result]  # 45 pop
        assert "t7" not in [t["id"] for t in result]  # 20 pop

    def test_hard_banned_artist_excluded(self):
        weights = {"art_1": 0.0}
        result = apply_merge_pipeline(
            SAMPLE_TRACKS,
            artist_weights=weights,
            vibe_scores={},
            min_popularity=0,
        )
        assert all(t["artist_id"] != "art_1" for t in result)

    def test_soft_banned_artist_capped(self):
        # art_1 has 3 tracks (85, 80, 75). With soft ban (0.3), max 2 can pass
        weights = {"art_1": 0.3}
        result = apply_merge_pipeline(
            SAMPLE_TRACKS,
            artist_weights=weights,
            vibe_scores={},
            min_popularity=0,
            playlist_limit=50,
        )
        art1_tracks = [t for t in result if t["artist_id"] == "art_1"]
        assert len(art1_tracks) <= 2

    def test_vibe_score_filtering(self):
        vibe_scores = {"t1": 9.5, "t4": 2.0, "t6": 8.0}
        result = apply_merge_pipeline(
            SAMPLE_TRACKS,
            artist_weights={},
            vibe_scores=vibe_scores,
            min_vibe_score=6.0,
        )
        result_ids = [t["id"] for t in result]
        assert "t1" in result_ids
        assert "t6" in result_ids
        assert "t4" not in result_ids  # vibe was 2.0 < 6.0


# ==============================================================================
# 2. Batch Gemini Scoring (Mocked)
# ==============================================================================

@pytest.mark.asyncio
async def test_batch_gemini_scoring_mocked():
    tracks = [
        make_track("t1", "Dancing Queen", "abba", "ABBA", 80),
        make_track("t2", "Heavy Metal Song", "metal", "Metal Band", 60),
    ]

    mock_response = MagicMock()
    mock_response.text = '[{"id":"t1","score":9.0},{"id":"t2","score":1.5}]'

    with patch("app.gemini_service.get_settings") as mock_settings:
        mock_settings.return_value.gemini_api_key = "fake_key"
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client

            scores = await batch_score_tracks(tracks, "Upbeat Disco Pop")

            assert scores["t1"] == 9.0
            assert scores["t2"] == 1.5


@pytest.mark.asyncio
async def test_batch_gemini_scoring_fallback():
    # If API key is empty, should return 5.0 neutral score
    with patch("app.gemini_service.get_settings") as mock_settings:
        mock_settings.return_value.gemini_api_key = ""
        scores = await batch_score_tracks(SAMPLE_TRACKS[:2], "Any mood")
        assert scores["t1"] == 5.0
        assert scores["t2"] == 5.0


# ==============================================================================
# 3. Playlist Inspector: Filtering, Duplicates & Sorting
# ==============================================================================

class TestPlaylistInspector:
    def test_filter_by_query(self):
        filtered = filter_tracks(SAMPLE_TRACKS, query="banger")
        assert len(filtered) == 3
        assert all("banger" in t["name"].lower() for t in filtered)

    def test_filter_by_year_range(self):
        filtered = filter_tracks(SAMPLE_TRACKS, year_from=2015, year_to=2020)
        assert len(filtered) == 3
        assert all(2015 <= int(t["release_year"]) <= 2020 for t in filtered)

    def test_filter_by_artist_weight_status(self):
        weights = {"art_1": 0.0, "art_2": 0.3, "art_3": 1.8, "art_4": 1.0}
        banned = filter_tracks(SAMPLE_TRACKS, artist_weights=weights, weight_filter="banned")
        assert all(t["artist_id"] == "art_1" for t in banned)

        soft = filter_tracks(SAMPLE_TRACKS, artist_weights=weights, weight_filter="soft_banned")
        assert all(t["artist_id"] == "art_2" for t in soft)

        boosted = filter_tracks(SAMPLE_TRACKS, artist_weights=weights, weight_filter="boosted")
        assert all(t["artist_id"] == "art_3" for t in boosted)

    def test_find_duplicates(self):
        tracks_with_dupes = [
            make_track("t1", "Track 1", "a1", "Art", 50),
            make_track("t2", "Track 2", "a1", "Art", 50),
            make_track("t1", "Track 1 Dupe", "a1", "Art", 50),
        ]
        dupes = find_duplicates(tracks_with_dupes)
        assert dupes == ["t1"]

    def test_sort_tracks_popularity(self):
        sorted_res = sort_tracks(SAMPLE_TRACKS, sort_by="popularity")
        pops = [t["popularity"] for t in sorted_res]
        assert pops == sorted(pops, reverse=True)

    def test_sort_tracks_release_date(self):
        sorted_res = sort_tracks(SAMPLE_TRACKS, sort_by="release_date")
        years = [int(t["release_year"]) for t in sorted_res]
        assert years == sorted(years, reverse=True)

    def test_sort_tracks_artist_weight(self):
        weights = {"art_3": 2.0, "art_1": 1.0, "art_4": 0.2}
        sorted_res = sort_tracks(SAMPLE_TRACKS, sort_by="artist_weight", artist_weights=weights)
        assert sorted_res[0]["artist_id"] == "art_3"  # weight 2.0


# ==============================================================================
# 4. API Endpoints Tests
# ==============================================================================

def test_api_merge_playlists_unauthenticated():
    client = TestClient(app)
    response = client.post(
        "/api/merge-playlists",
        json={"prompt": "Test Vibe", "playlist_ids": ["pl1", "pl2"]},
    )
    # Should return 401 when Spotify token is not configured
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_api_manual_token_invalid():
    client = TestClient(app)
    response = client.post(
        "/api/auth/manual-token",
        json={"callback_url": "http://localhost:8000/callback?invalid=param"},
    )
    assert response.status_code == 400


def test_api_inspect_filter_unauthenticated():
    client = TestClient(app)
    response = client.post(
        "/api/inspect/filter",
        json={"playlist_id": "pl123", "min_popularity": 50},
    )
    assert response.status_code == 401
