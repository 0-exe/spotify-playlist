"""Gemini AI service: search strategy generation + batch track vibe scoring + dynamic model fetching."""
import json
import logging
import re
from typing import Any
import httpx

from app.config import get_settings
from app.database import get_app_setting, set_app_setting

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

# Standard list of free-tier supported Gemini models on Google AI Studio
DEFAULT_FREE_MODELS = [
    {
        "id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "description": "Empfohlen: Neuestes, schnelles Modell mit exzellenter Kuratierung und hoher Genauigkeit (Free-Tier Kontingent)",
        "is_free_tier": True,
        "recommended": True,
    },
    {
        "id": "gemini-2.5-flash-lite",
        "display_name": "Gemini 2.5 Flash-Lite",
        "description": "Extrem schnell, minimale Latenz und sparsamste Token-Nutzung (Free Tier)",
        "is_free_tier": True,
        "recommended": False,
    },
    {
        "id": "gemini-2.0-flash",
        "display_name": "Gemini 2.0 Flash",
        "description": "Solides, schnelles Allrounder-Modell der 2. Generation (Free Tier)",
        "is_free_tier": True,
        "recommended": False,
    },
    {
        "id": "gemini-1.5-flash",
        "display_name": "Gemini 1.5 Flash",
        "description": "Bewährtes Flash-Modell der 1.5 Serie mit hoher Geschwindigkeit (Free Tier)",
        "is_free_tier": True,
        "recommended": False,
    },
    {
        "id": "gemini-1.5-flash-8b",
        "display_name": "Gemini 1.5 Flash-8B",
        "description": "Kompaktes 8B-Modell für besonders schnellen Durchsatz (Free Tier)",
        "is_free_tier": True,
        "recommended": False,
    },
]


async def get_effective_gemini_config() -> tuple[str, str]:
    """
    Returns (api_key, model_name).
    Checks SQLite DB app_settings first, then falls back to .env settings.
    """
    settings = get_settings()
    db_key = await get_app_setting("gemini_api_key", "")
    api_key = db_key.strip() if db_key.strip() else settings.gemini_api_key

    db_model = await get_app_setting("gemini_model", "")
    model = db_model.strip() if db_model.strip() else "gemini-2.5-flash"

    return api_key, model


async def fetch_available_gemini_models(api_key: str | None = None) -> list[dict[str, Any]]:
    """
    Query Google Generative Language API directly to discover all available models,
    filtering for content generation models and flagging Free-Tier eligible models.
    """
    if not api_key:
        api_key, _ = await get_effective_gemini_config()

    if not api_key:
        return DEFAULT_FREE_MODELS

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Google models endpoint returned status {resp.status_code}: {resp.text[:200]}")
                return DEFAULT_FREE_MODELS

            data = resp.json()
            raw_models = data.get("models", [])

            parsed_models: list[dict[str, Any]] = []
            for m in raw_models:
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" not in methods:
                    continue

                full_name = m.get("name", "")
                model_id = full_name.replace("models/", "")
                
                # Exclude embedding, aqa, or image-only models
                if "embedding" in model_id.lower() or "aqa" in model_id.lower():
                    continue

                display_name = m.get("displayName", model_id)
                description = m.get("description", "")

                # Free-tier identification on Google AI Studio:
                # "flash" and "flash-lite" models enjoy the standard free-tier quota (15 RPM / 1M TPM)
                is_free = any(k in model_id.lower() for k in ["flash", "flash-lite", "flash-8b", "2.5-flash", "2.0-flash"])
                is_rec = model_id == "gemini-2.5-flash"

                parsed_models.append({
                    "id": model_id,
                    "display_name": display_name,
                    "description": description,
                    "is_free_tier": is_free,
                    "recommended": is_rec,
                })

            # Sort: Recommended first, then free-tier models, then others
            parsed_models.sort(key=lambda x: (not x["recommended"], not x["is_free_tier"], x["id"]))
            return parsed_models if parsed_models else DEFAULT_FREE_MODELS

    except Exception as e:
        logger.error(f"Failed to fetch models from Google: {e}")
        return DEFAULT_FREE_MODELS


async def get_search_strategy(prompt: str) -> dict[str, Any]:
    """Use Gemini to generate a search strategy for the given mood/vibe prompt."""
    api_key, model_name = await get_effective_gemini_config()

    if not api_key:
        logger.warning("Gemini API key not set, using fallback search strategy")
        return _fallback_strategy(prompt)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        full_prompt = SEARCH_STRATEGY_PROMPT.format(prompt=prompt)

        response = client.models.generate_content(
            model=model_name,
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
        logger.info(f"Gemini search strategy generated with model '{model_name}' for: {prompt!r}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        return _fallback_strategy(prompt)
    except Exception as e:
        logger.error(f"Gemini API error with model '{model_name}': {e}")
        return _fallback_strategy(prompt)


async def batch_score_tracks(
    tracks: list[dict[str, Any]],
    mood: str,
    batch_size: int = 25,
) -> dict[str, float]:
    """
    Score a list of tracks (0–10) for how well they match the given mood/vibe.
    Uses selected Gemini model in batches of `batch_size` tracks.
    """
    api_key, model_name = await get_effective_gemini_config()
    scores: dict[str, float] = {}

    if not api_key:
        logger.warning("Gemini API key not set — using neutral score 5.0 for all tracks")
        return {t["id"]: 5.0 for t in tracks}

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

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
                    model=model_name,
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
                logger.info(f"Scored batch with {model_name}: {len(batch)} tracks for mood '{mood}'")
            except Exception as e:
                logger.error(f"Batch scoring failed with {model_name}: {e}")
                for t in batch:
                    scores.setdefault(t["id"], 5.0)

    except Exception as e:
        logger.error(f"Gemini batch scoring init error: {e}")
        return {t["id"]: 5.0 for t in tracks}

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
