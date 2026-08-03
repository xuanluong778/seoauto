"""
Trained ranking model hook (``RANKING_MODEL_PATH``) + surrogate used by attribution.

Production models should expose ``predict_proba`` and ideally ``feature_names_in_``.
"""

from __future__ import annotations

from app.services.model_interface import (
    AdditiveLogitSurrogateModel,
    build_default_surrogate,
    load_ranking_model_from_path,
    predict_proba_for_vector,
)

__all__ = [
    "AdditiveLogitSurrogateModel",
    "build_default_surrogate",
    "load_ranking_model_from_path",
    "predict_proba_for_vector",
]
