"""Google Places API — cấu hình API key (backend only)."""

from __future__ import annotations

import os

from app.core.settings import _ENV_LOCAL, refresh_env_local
from dotenv import dotenv_values

PLACES_API_BASE = "https://places.googleapis.com/v1"
GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def get_places_api_key() -> str:
    """Ưu tiên GOOGLE_PLACES_API_KEY, fallback GOOGLE_MAPS_API_KEY / GOOGLE_API_KEY."""
    refresh_env_local()
    file_vals = dotenv_values(_ENV_LOCAL) if _ENV_LOCAL.is_file() else {}

    def pick(*keys: str) -> str:
        for key in keys:
            if file_vals:
                raw = file_vals.get(key)
                if raw is not None and str(raw).strip():
                    return str(raw).strip().strip('"').strip("'")
            val = (os.getenv(key) or "").strip().strip('"').strip("'")
            if val:
                return val
        return ""

    return pick("GOOGLE_PLACES_API_KEY", "GOOGLE_MAPS_API_KEY", "GOOGLE_API_KEY")


def places_api_configured() -> bool:
    return bool(get_places_api_key())
