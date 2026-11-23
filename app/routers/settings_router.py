"""Settings router for managing Gemini API keys and free model selection."""
import logging
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_app_setting, set_app_setting
from app.gemini_service import (
    get_effective_gemini_config,
    fetch_available_gemini_models,
    DEFAULT_FREE_MODELS,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class GeminiSettingsUpdate(BaseModel):
    api_key: str | None = Field(None, description="Google Gemini API Key")
    model: str | None = Field(None, description="Selected Gemini Model ID (e.g. gemini-2.5-flash)")


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "••••••••"
    return key[:4] + "••••••••" + key[-4:]


@router.get("/settings/gemini")
async def get_gemini_settings():
    """Return the current Gemini configuration and available models."""
    api_key, model_name = await get_effective_gemini_config()
    models = await fetch_available_gemini_models(api_key)

    return {
        "has_key": bool(api_key),
        "api_key_masked": _mask_key(api_key),
        "selected_model": model_name,
        "available_models": models,
    }


@router.post("/settings/gemini")
async def save_gemini_settings(payload: GeminiSettingsUpdate):
    """Save/update the Gemini API key and/or selected model."""
    if payload.api_key is not None:
        key_str = payload.api_key.strip()
        await set_app_setting("gemini_api_key", key_str)
        logger.info("Updated Gemini API key in settings")

    if payload.model is not None:
        model_str = payload.model.strip()
        if model_str:
            await set_app_setting("gemini_model", model_str)
            logger.info(f"Updated selected Gemini model to {model_str}")

    api_key, model_name = await get_effective_gemini_config()
    return {
        "success": True,
        "has_key": bool(api_key),
        "api_key_masked": _mask_key(api_key),
        "selected_model": model_name,
    }


@router.get("/settings/gemini/models")
async def list_gemini_models(api_key: str = ""):
    """Fetch live available models from Google API."""
    key = api_key.strip()
    if not key:
        key, _ = await get_effective_gemini_config()

    models = await fetch_available_gemini_models(key)
    return {"models": models, "count": len(models)}
