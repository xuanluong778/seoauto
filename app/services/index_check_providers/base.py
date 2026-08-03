from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

INDEX_STATUS_INDEX = "INDEX"
INDEX_STATUS_NO_INDEX = "NO_INDEX"
INDEX_STATUS_UNKNOWN = "UNKNOWN"
INDEX_STATUS_ERROR = "ERROR"
INDEX_STATUS_CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
INDEX_STATUS_PENDING_RETRY = "PENDING_RETRY"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class IndexCheckProviderResult:
    url: str
    query: str
    index_status: str
    matched_url: str = ""
    title: str = ""
    reason: str = ""
    http_status: int | None = None
    indexability_status: str = ""
    checked_at: str = ""
    retry_count: int = 0
    evidence: str = ""
    target_url_normalized: str = ""
    candidate_urls: list[str] | None = None
    match_type: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "query": self.query,
            "index_status": self.index_status,
            "matched_url": self.matched_url or None,
            "title": self.title or None,
            "reason": self.reason,
            "http_status": self.http_status,
            "indexability_status": self.indexability_status,
            "checked_at": self.checked_at or utc_now_iso(),
            "retry_count": int(self.retry_count or 0),
            "evidence": (self.evidence or "")[:500] or None,
            "target_url_normalized": self.target_url_normalized or None,
            "candidate_urls": list(self.candidate_urls or [])[:20] or None,
            "match_type": self.match_type or "none",
        }


class BaseIndexCheckProvider(ABC):
    @abstractmethod
    def check_url(self, url: str, *, retry_count: int = 0) -> dict[str, Any]:
        raise NotImplementedError
