"""Deploy-time: rank_tracking_projects/keywords/results tables."""

from __future__ import annotations

import logging

from app.db import Base, engine

_LOG = logging.getLogger(__name__)


def ensure_rank_tracking_pg() -> None:
    import app.models.rank_tracking  # noqa: F401
    import app.models.user  # noqa: F401

    from app.models.rank_tracking import (
        RankTrackingKeyword,
        RankTrackingProject,
        RankTrackingResult,
    )

    Base.metadata.create_all(
        bind=engine,
        tables=[
            RankTrackingProject.__table__,
            RankTrackingKeyword.__table__,
            RankTrackingResult.__table__,
        ],
    )
    _LOG.info("rank_tracking PG tables ensured")
