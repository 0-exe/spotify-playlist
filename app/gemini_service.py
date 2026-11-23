"""Gemini AI service: search strategy generation + batch track vibe scoring."""
import json
import logging
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a music expert and playlist curator.
Return ONLY valid JSON, no markdown, no explanation."""

SEARCH_STRATEGY_PROMPT = """Given this playlist mood/vibe description: "{prompt}"

Generate a JSON object with these fields:
{{
  "search_queries": ["query1", "query2", ...],
  "playlist_queries": ["query1", "query2", ...],
  "genres": ["genre1", "genre2", ...],
  "decade_tags": ["2010s", "2000s", ...],
  "mood_description": "brief mood summary",
  "energy_level": "low|medium|high",
  "search_track_queries": ["artist:name genre:pop year:2010-2020", ...]
}}

Be creative and specific. For "White Girl Music 2010s Throwback": Taylor Swift 2012, Katy Perry, indie pop 2012.
For "Dark Driving Techno": dark techno berlin, industrial techno driving."""

BATCH_SCORE_PROMPT = """You are a music curator. Given the mood/vibe "{mood}" rate each track on a scale 0-10
for how well it matches this mood (10 = perfect fit, 0 = completely wrong vibe).

Consider: genre, era, energy, typical listener profile, artist style.
Return ONLY a JSON array of objects with "id" and "score" (float 0-10), one per track, same order:

Tracks to rate:
{tracks_json}

Example output: [{{"id":"track123","score":8.5}},{{"id":"track456","score":3.0}}]"""


async def get_search_strategy(prompt: str) -> dict[str, Any]:
    """Use Gemini to generate a search strategy for the given mood/vibe prompt."""
    settings = get_settings()

    if not settings.gemini_api_key:
        logger.warning("Gemini API key not set, using fallback search strategy")
        return _fallback_strategy(prompt)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        full_prompt = SEARCH_STRATEGY_PROMPT.format(prompt=prompt)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.7,
                max_output_tokens=1024,
            ),
        )

        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        logger.info(f"Gemini search strategy generated for: {prompt!r}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        return _fallback_strategy(prompt)
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return _fallback_strategy(prompt)


async def batch_score_tracks(
    tracks: list[dict[str, Any]],
    mood: str,
    batch_size: int = 25,
) -> dict[str, float]:
    """
    Score a list of tracks (0–10) for how well they match the given mood/vibe.
    Uses Gemini in batches of `batch_size` tracks.

    Returns: dict mapping track_id -> vibe_score (float 0.0–10.0).
    Falls back to 5.0 for all tracks if Gemini is unavailable.
    """
    settings = get_settings()
    scores: dict[str, float] = {}

    if not settings.gemini_api_key:
        logger.warning("Gemini API key not set — using neutral score 5.0 for all tracks")
        return {t["id"]: 5.0 for t in tracks}

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)

        # Process in batches
        for i in range(0, len(tracks), batch_size):
            batch = tracks[i : i + batch_size]
            tracks_data = [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "artist": t["artist_name"],
                    "album": t.get("album_name", ""),
                    "popularity": t.get("popularity", 0),
                    "release_year": t.get("release_year", ""),
                }
                for t in batch
            ]
            tracks_json = json.dumps(tracks_data, ensure_ascii=False)
            prompt = BATCH_SCORE_PROMPT.format(mood=mood, tracks_json=tracks_json)

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.3,
                        max_output_tokens=2048,
                    ),
                )
                text = response.text.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
                text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE)
                results = json.loads(text)
                for item in results:
                    tid = item.get("id", "")
                    score = float(item.get("score", 5.0))
                    scores[tid] = max(0.0, min(10.0, score))
                logger.info(f"Scored batch {i // batch_size + 1}: {len(batch)} tracks for mood '{mood}'")
            except Exception as e:
                logger.error(f"Batch scoring failed for batch {i // batch_size + 1}: {e}")
                for t in batch:
                    scores.setdefault(t["id"], 5.0)

    except Exception as e:
        logger.error(f"Gemini batch scoring init error: {e}")
        return {t["id"]: 5.0 for t in tracks}

    # Fill any missing
    for t in tracks:
        scores.setdefault(t["id"], 5.0)

    return scores


def _fallback_strategy(prompt: str) -> dict[str, Any]:
    """Fallback search strategy when Gemini is unavailable."""
    return {
        "search_queries": [prompt, f"{prompt} hits", f"best {prompt}"],
        "playlist_queries": [prompt, f"{prompt} playlist"],
        "genres": [],
        "decade_tags": [],
        "mood_description": prompt,
        "energy_level": "medium",
        "search_track_queries": [prompt],
    }


def parse_gemini_response(text: str) -> dict[str, Any]:
    """Parse a Gemini JSON response, stripping markdown if needed."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE)
    return json.loads(text)
