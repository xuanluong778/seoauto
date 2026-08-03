"""Phân tích lệnh workflow từ tin nhắn chatbot (không thay thế luồng FAQ/RAG/LLM)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import quote

from app.services.content_ai_image_rules import (
    image_source_label,
    inline_image_count_for_word_count,
    normalize_image_source,
    parse_image_source_choice,
)

INTENT_KEYWORD_CLUSTER_TO_ARTICLE = "keyword_cluster_to_article"

_PENDING_LOCK = Lock()
_pending_workflows: dict[str, dict[str, Any]] = {}

_WRITE_MARKERS = (
    r"viết bài",
    r"viết bài viết",
    r"tạo bài",
    r"tạo bài viết",
    r"bài viết",
    r"viết content",
    r"viết nội dung",
    r"write article",
    r"write content",
    r"create article",
    r"generate article",
)

_CLUSTER_MARKERS = (
    r"gom nhóm",
    r"gom cluster",
    r"gộp nhóm",
    r"cluster",
    r"nghiên cứu từ khóa",
    r"research từ khóa",
    r"research keyword",
    r"keyword research",
    r"cụm từ khóa",
    r"cụm keyword",
    r"từ khóa",
    r"keyword",
)

_COMBO_PATTERNS = (
    re.compile(
        r"(?:gom\s+nhóm|gộp\s+nhóm|cluster|nghiên cứu|research).{0,80}?(?:viết|tạo).{0,40}?(?:bài|content|nội dung|article)",
        re.I,
    ),
    re.compile(
        r"(?:viết|tạo).{0,40}?(?:bài|content|nội dung|article).{0,80}?(?:gom\s+nhóm|cluster|từ khóa|keyword|cụm)",
        re.I,
    ),
    re.compile(r"tạo\s+bài\s+viết\s+từ\s+cụm\s+(?:từ\s+khóa|keyword)", re.I),
    re.compile(r"keyword\s+cluster.{0,60}?(?:write|create|generate)\s+(?:article|content)", re.I),
)

# Kết thúc cụm từ khóa: metadata (số từ, và/rồi viết…) hoặc hết câu.
_KW_END = r"(?=(?:\s*,|\s+\d{3,5}\s*từ|\s+(?:và|rồi)\s+(?:viết|gom|tạo|research|nghiên)|$))"

_KEYWORD_PATTERNS = (
    re.compile(
        r"(?:với|cho|theo|about)\s+(?:từ\s+khóa|keyword|chủ\s+đề|topic)\s+(.+?)"
        + _KW_END,
        re.I,
    ),
    re.compile(
        r"(?:viết|tạo)\s+(?:cho\s+(?:tôi|mình|em)\s+)?(?:một\s+)?(?:bài\s+viết|bài|content|nội dung)\s+"
        r"(?:với|cho|theo|about)\s+(?:từ\s+khóa|keyword)\s+(.+?)"
        + _KW_END,
        re.I,
    ),
    re.compile(
        r"(?:từ\s+khóa|keyword|chủ\s+đề|chủ\s+de|topic)\s*[:\-]?\s*[\"“]?(.+?)[\"”]?"
        + _KW_END,
        re.I,
    ),
    re.compile(
        r"(?:research|nghiên\s+cứu)\s+(?:từ\s+khóa|keyword)\s+(.+?)"
        + _KW_END,
        re.I,
    ),
    re.compile(
        r"(?:gom\s+nhóm|gộp\s+nhóm|cluster)\s+(?:từ\s+khóa|keyword)\s+(.+?)"
        + _KW_END,
        re.I,
    ),
    re.compile(r"[\"“]([^\"”]{2,120})[\"”]"),
    re.compile(r"'([^']{2,120})'"),
    re.compile(r"cụm\s+(?:từ\s+khóa|keyword)\s+(.+)$", re.I),
)

_WORD_COUNT_RE = re.compile(
    r"(?:số\s+từ|word\s*count|khoảng|about|~)?\s*(\d{3,5})\s*(?:từ|words?)\b",
    re.I,
)
_WORD_COUNT_K_RE = re.compile(r"\b(\d(?:\.\d)?)\s*k\s*từ\b", re.I)

_LANGUAGE_MAP = {
    "tiếng việt": "vi",
    "tieng viet": "vi",
    "vietnamese": "vi",
    "tiếng anh": "en",
    "tieng anh": "en",
    "english": "en",
    "bằng tiếng việt": "vi",
    "bằng tiếng anh": "en",
    "in vietnamese": "vi",
    "in english": "en",
}

_TONE_MAP = {
    "chuyên nghiệp": "professional",
    "professional": "professional",
    "formal": "formal",
    "trang trọng": "formal",
    "thân thiện": "friendly",
    "friendly": "friendly",
    "casual": "casual",
    "gần gũi": "friendly",
    "thuyết phục": "persuasive",
    "persuasive": "persuasive",
}

_COUNTRY_MAP = {
    "việt nam": "VN",
    "viet nam": "VN",
    "vietnam": "VN",
    "united states": "US",
    "mỹ": "US",
    "usa": "US",
    "singapore": "SG",
    "thái lan": "TH",
    "thai lan": "TH",
}

_INTERNAL_LINK_RE = re.compile(
    r"internal\s*link|link\s*nội\s*bộ|liên\s*kết\s*nội\s*bộ|internal\s*linking",
    re.I,
)
_IMAGE_RE = re.compile(
    r"hình\s*ảnh|chèn\s*ảnh|chèn\s*hình|ảnh\s*minh\s*họa|minh\s*họa|\bimages?\b",
    re.I,
)

_WORD_COUNT_PRESETS = (1000, 1500, 2000)

_ARTICLE_TYPE_MAP = {
    "blog": "blog",
    "bài blog": "blog",
    "landing page": "landing_page",
    "landing": "landing_page",
    "pillar": "pillar",
    "bài pillar": "pillar",
    "hướng dẫn": "guide",
    "guide": "guide",
    "review": "review",
    "đánh giá": "review",
    "so sánh": "comparison",
    "comparison": "comparison",
    "listicle": "listicle",
    "dạng list": "listicle",
}


@dataclass
class WorkflowParseResult:
    intent: str | None = None
    primary_keyword: str | None = None
    word_count: int | None = None
    language: str | None = None
    tone: str | None = None
    country: str | None = None
    article_type: str | None = None
    confidence: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    awaiting_keyword: bool = False
    awaiting_word_count: bool = False
    awaiting_image_source: bool = False
    include_internal_links: bool = False
    include_images: bool = False
    image_source: str | None = None
    target_website: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_workflow(self) -> bool:
        return bool(self.intent)

    @property
    def needs_keyword(self) -> bool:
        return self.is_workflow and not (self.primary_keyword or "").strip()

    @property
    def needs_word_count(self) -> bool:
        return (
            self.is_workflow
            and bool((self.primary_keyword or "").strip())
            and not self.word_count
        )

    @property
    def needs_image_source(self) -> bool:
        return (
            self.is_workflow
            and bool((self.primary_keyword or "").strip())
            and bool(self.word_count)
            and self.image_source is None
        )

    @property
    def workflow_ready(self) -> bool:
        return (
            self.is_workflow
            and bool((self.primary_keyword or "").strip())
            and bool(self.word_count)
            and self.image_source is not None
        )

    def sync_image_flags(self) -> None:
        if self.image_source is None:
            self.include_images = False
            return
        src = normalize_image_source(self.image_source, include_images=self.include_images)
        self.image_source = src
        self.include_images = src in ("google", "ai")


def _norm(text: str) -> str:
    raw = unicodedata.normalize("NFC", str(text or "")).strip()
    raw = re.sub(r"\s+", " ", raw)
    return raw


def _fold(text: str) -> str:
    t = _norm(text).lower()
    t = t.replace("đ", "d")
    return unicodedata.normalize("NFC", t)


def _clean_keyword(raw: str) -> str:
    kw = _norm(raw)
    kw = re.sub(r"^(?:từ khóa|keyword|chủ đề|topic)\s*[:\-]?\s*", "", kw, flags=re.I)
    kw = re.sub(r"\s+(?:cho tôi|giúp tôi|hộ tôi|nhé|nha|ạ|giúp|please)\.?$", "", kw, flags=re.I)
    kw = kw.strip(" \"“”'.,;:!?")
    if len(kw) < 2:
        return ""
    if kw.lower() in {"này", "này", "đó", "do", "kia", "nay", "this", "that"}:
        return ""
    return kw[:200]


def _is_plausible_keyword(kw: str) -> bool:
    cleaned = _clean_keyword(kw)
    if not cleaned:
        return False
    folded = _fold(cleaned)
    if re.match(r"^(?:va|roi|và|rồi)\s+", folded):
        return False
    if re.match(
        r"^(?:viết|viet|tạo|tao|gom|gộp|cluster|research|nghiên)\b",
        folded,
    ):
        return False
    if folded in {
        "va",
        "và",
        "roi",
        "rồi",
        "viết bài",
        "viet bai",
        "viết bài seo",
        "viet bai seo",
        "tạo bài",
        "tao bai",
    }:
        return False
    return True


def _has_marker(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _is_workflow_command(text: str) -> bool:
    if any(p.search(text) for p in _COMBO_PATTERNS):
        return True
    has_write = _has_marker(text, _WRITE_MARKERS)
    has_cluster = _has_marker(text, _CLUSTER_MARKERS)
    if has_write and has_cluster:
        return True
    if re.search(r"tạo\s+bài\s+viết\s+từ\s+cụm", text, re.I):
        return True
    return False


def _extract_keyword(text: str) -> str:
    for pat in _KEYWORD_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        kw = _clean_keyword(m.group(1))
        if kw and _is_plausible_keyword(kw):
            return kw

    m = re.search(
        r"(?:gom\s+nhóm|gộp\s+nhóm|cluster)\s+(?:từ\s+khóa|keyword)?\s*(.+?)"
        r"(?=\s+(?:và|rồi)\s+(?:viết|tạo))",
        text,
        re.I,
    )
    if m:
        kw = _clean_keyword(m.group(1))
        if kw and _is_plausible_keyword(kw):
            return kw
    return ""


def _extract_word_count(text: str) -> int | None:
    m = _WORD_COUNT_RE.search(text)
    if m:
        try:
            n = int(m.group(1))
            return n if 200 <= n <= 20000 else None
        except ValueError:
            pass
    m = _WORD_COUNT_K_RE.search(text)
    if m:
        try:
            return int(float(m.group(1)) * 1000)
        except ValueError:
            pass
    return None


def _extract_mapped(text: str, mapping: dict[str, str]) -> str | None:
    folded = _fold(text)
    for key, val in sorted(mapping.items(), key=lambda x: -len(x[0])):
        if key in folded:
            return val
    return None


def _extract_country(text: str) -> str | None:
    folded = _fold(text)
    m = re.search(r"thị trường\s+([a-zA-ZÀ-ỹ\s]{2,40})", text, re.I)
    if m:
        region = _fold(m.group(1))
        for key, val in _COUNTRY_MAP.items():
            if key.strip() in region or region in key:
                return val
    return _extract_mapped(text, _COUNTRY_MAP)


def _extract_article_type(text: str) -> str | None:
    return _extract_mapped(text, _ARTICLE_TYPE_MAP)


def _confidence(text: str, keyword: str) -> float:
    score = 0.55
    if _is_workflow_command(text):
        score += 0.2
    if keyword:
        score += 0.2
    if _extract_word_count(text):
        score += 0.03
    if _extract_mapped(text, _LANGUAGE_MAP):
        score += 0.02
    return min(0.98, score)


def _last_assistant_awaiting_keyword(history: list[dict[str, str]] | None) -> bool:
    if not history:
        return False
    for turn in reversed(history[-6:]):
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        content = str(turn.get("content") or "")
        if _is_assistant_awaiting_word_count(content):
            continue
        folded = content.lower()
        if "từ khóa chính" in folded and "workflow" in folded:
            return True
    return False


def _is_assistant_awaiting_image_source(content: str) -> bool:
    folded = str(content or "").lower()
    if "workflow" not in folded and "keyword_cluster_to_article" not in folded:
        return False
    return "nguồn ảnh" in folded or "nguon anh" in folded


def _last_assistant_awaiting_image_source(history: list[dict[str, str]] | None) -> bool:
    if not history:
        return False
    for turn in reversed(history[-6:]):
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        if _is_assistant_awaiting_image_source(str(turn.get("content") or "")):
            return True
    return False


def _extract_primary_keyword_from_image_source_prompt(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    pat = re.compile(
        r"từ\s*khóa\s*chính\s*[:\*]*\s*\*?\*?\s*([^\n\*]+?)(?:\s*\*|$|\n)",
        re.I,
    )
    for turn in reversed(history[-8:]):
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        content = str(turn.get("content") or "")
        if not _is_assistant_awaiting_image_source(content):
            continue
        m = pat.search(content)
        if not m:
            continue
        kw = _clean_keyword(m.group(1))
        if kw:
            return kw
    return ""


def _extract_word_count_from_image_source_prompt(history: list[dict[str, str]] | None) -> int | None:
    if not history:
        return None
    pat = re.compile(r"số\s*từ\s*[:\*]*\s*\*?\*?\s*(\d{3,5})", re.I)
    for turn in reversed(history[-8:]):
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        content = str(turn.get("content") or "")
        if not _is_assistant_awaiting_image_source(content):
            continue
        m = pat.search(content)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _is_assistant_awaiting_word_count(content: str) -> bool:
    folded = str(content or "").lower()
    if "workflow" not in folded and "keyword_cluster_to_article" not in folded:
        return False
    return "bao nhiêu từ" in folded or "số từ" in folded


def _last_assistant_awaiting_word_count(history: list[dict[str, str]] | None) -> bool:
    if not history:
        return False
    for turn in reversed(history[-6:]):
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        if _is_assistant_awaiting_word_count(str(turn.get("content") or "")):
            return True
    return False


def _extract_primary_keyword_from_history(history: list[dict[str, str]] | None) -> str:
    """Khôi phục từ khóa từ tin nhắn bot hỏi số từ (khi pending in-memory bị mất)."""
    if not history:
        return ""
    pat = re.compile(
        r"từ\s*khóa\s*chính\s*[:\*]*\s*\*?\*?\s*([^\n\*]+?)(?:\s*\*|$|\n)",
        re.I,
    )
    for turn in reversed(history[-8:]):
        if str(turn.get("role") or "").lower() != "assistant":
            continue
        content = str(turn.get("content") or "")
        if not _is_assistant_awaiting_word_count(content):
            continue
        m = pat.search(content)
        if not m:
            continue
        kw = _clean_keyword(m.group(1))
        if kw:
            return kw
    return ""


def _extract_feature_flags(text: str) -> tuple[bool, bool]:
    return bool(_INTERNAL_LINK_RE.search(text)), bool(_IMAGE_RE.search(text))


def _extract_target_website(text: str) -> str:
    m = re.search(
        r"(?:website|trang|site|domain)\s*[:\-]?\s*(https?://[^\s,]+|[a-z0-9][a-z0-9.-]+\.[a-z]{2,})",
        text,
        re.I,
    )
    if not m:
        return ""
    return str(m.group(1) or "").strip()[:200]


def _parse_word_count_choice(text: str) -> int | None:
    wc = _extract_word_count(text)
    if wc:
        return wc
    raw = _norm(text).lower()
    if raw in {"1000", "1500", "2000"}:
        return int(raw)
    m = re.match(r"^(\d{3,5})\s*$", raw)
    if m:
        try:
            n = int(m.group(1))
            return n if 200 <= n <= 20000 else None
        except ValueError:
            pass
    return None


def _save_pending(session_id: str, payload: dict[str, Any]) -> None:
    if not session_id:
        return
    with _PENDING_LOCK:
        _pending_workflows[session_id] = payload


def _pop_pending(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _PENDING_LOCK:
        return _pending_workflows.pop(session_id, None)


def _get_pending(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _PENDING_LOCK:
        data = _pending_workflows.get(session_id)
        return dict(data) if data else None


def clear_pending_workflow(session_id: str) -> None:
    if not session_id:
        return
    with _PENDING_LOCK:
        _pending_workflows.pop(session_id, None)


def parse_chatbot_command(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    session_id: str | None = None,
) -> WorkflowParseResult:
    """Nhận diện lệnh workflow. Trả intent=None nếu là hội thoại thường."""
    text = _norm(message)
    if not text:
        return WorkflowParseResult()

    pending = _get_pending(session_id or "")
    awaiting_img = _last_assistant_awaiting_image_source(history) or bool(
        pending and pending.get("awaiting_image_source")
    )
    awaiting_wc = _last_assistant_awaiting_word_count(history) or bool(
        pending and pending.get("awaiting_word_count")
    )
    awaiting_kw = _last_assistant_awaiting_keyword(history) or bool(
        pending and pending.get("awaiting_keyword")
    )

    if awaiting_img and not _is_workflow_command(text):
        src = parse_image_source_choice(text)
        if src is not None:
            base = pending or {}
            pk = str(
                base.get("primary_keyword")
                or _extract_primary_keyword_from_image_source_prompt(history)
                or _extract_primary_keyword_from_history(history)
                or ""
            ).strip()
            wc = base.get("word_count") or _extract_word_count_from_image_source_prompt(history)
            if not pk or not wc:
                clear_pending_workflow(session_id or "")
                return WorkflowParseResult()
            clear_pending_workflow(session_id or "")
            result = WorkflowParseResult(
                intent=INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
                primary_keyword=pk,
                word_count=int(wc),
                language=base.get("language"),
                tone=base.get("tone"),
                country=base.get("country"),
                article_type=base.get("article_type"),
                include_internal_links=bool(base.get("include_internal_links")),
                image_source=src,
                target_website=str(base.get("target_website") or ""),
                confidence=0.9,
                missing_fields=[],
            )
            result.sync_image_flags()
            return result

    if awaiting_wc and not _is_workflow_command(text):
        wc = _parse_word_count_choice(text)
        if wc:
            base = pending or {}
            pk = str(
                base.get("primary_keyword")
                or _extract_primary_keyword_from_history(history)
                or ""
            ).strip()
            if not pk:
                clear_pending_workflow(session_id or "")
                return WorkflowParseResult()
            result = WorkflowParseResult(
                intent=INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
                primary_keyword=pk,
                word_count=wc,
                language=base.get("language"),
                tone=base.get("tone"),
                country=base.get("country"),
                article_type=base.get("article_type"),
                include_internal_links=bool(base.get("include_internal_links")),
                include_images=bool(base.get("include_images")),
                target_website=str(base.get("target_website") or ""),
                confidence=0.88,
                missing_fields=["image_source"],
                awaiting_image_source=True,
            )
            _save_pending(
                session_id or "",
                {
                    **base,
                    "awaiting_keyword": False,
                    "awaiting_word_count": False,
                    "awaiting_image_source": True,
                    "primary_keyword": pk,
                    "word_count": wc,
                    "include_internal_links": result.include_internal_links,
                    "include_images": result.include_images,
                    "target_website": result.target_website,
                },
            )
            return result

    if awaiting_kw and not _is_workflow_command(text):
        kw = _clean_keyword(text)
        if kw:
            base = pending or {
                "intent": INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
                "word_count": None,
                "language": None,
                "tone": None,
                "country": None,
                "article_type": None,
                "include_internal_links": False,
                "include_images": False,
                "target_website": "",
            }
            il, im = _extract_feature_flags(text)
            result = WorkflowParseResult(
                intent=INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
                primary_keyword=kw,
                word_count=base.get("word_count"),
                language=base.get("language"),
                tone=base.get("tone"),
                country=base.get("country"),
                article_type=base.get("article_type"),
                include_internal_links=bool(base.get("include_internal_links")) or il,
                include_images=bool(base.get("include_images")) or im,
                target_website=str(base.get("target_website") or _extract_target_website(text) or ""),
                confidence=0.85,
            )
            if result.needs_word_count:
                result.awaiting_word_count = True
                result.missing_fields = ["word_count"]
                _save_pending(
                    session_id or "",
                    {
                        **base,
                        "awaiting_keyword": False,
                        "awaiting_word_count": True,
                        "awaiting_image_source": False,
                        "primary_keyword": kw,
                        "include_internal_links": result.include_internal_links,
                        "include_images": result.include_images,
                        "target_website": result.target_website,
                    },
                )
            elif result.needs_image_source:
                result.awaiting_image_source = True
                result.missing_fields = ["image_source"]
                _save_pending(
                    session_id or "",
                    {
                        **base,
                        "awaiting_keyword": False,
                        "awaiting_word_count": False,
                        "awaiting_image_source": True,
                        "primary_keyword": kw,
                        "word_count": result.word_count,
                        "include_internal_links": result.include_internal_links,
                        "include_images": result.include_images,
                        "target_website": result.target_website,
                    },
                )
            else:
                clear_pending_workflow(session_id or "")
            result.sync_image_flags()
            return result

    if not _is_workflow_command(text):
        clear_pending_workflow(session_id or "")
        return WorkflowParseResult()

    keyword = _extract_keyword(text)
    il, im = _extract_feature_flags(text)
    src_choice = parse_image_source_choice(text)
    result = WorkflowParseResult(
        intent=INTENT_KEYWORD_CLUSTER_TO_ARTICLE,
        primary_keyword=keyword or None,
        word_count=_extract_word_count(text),
        language=_extract_mapped(text, _LANGUAGE_MAP),
        tone=_extract_mapped(text, _TONE_MAP),
        country=_extract_country(text),
        article_type=_extract_article_type(text),
        include_internal_links=il,
        include_images=im,
        image_source=src_choice,
        target_website=_extract_target_website(text),
        confidence=_confidence(text, keyword),
    )

    if result.needs_keyword:
        result.awaiting_keyword = True
        result.missing_fields = ["primary_keyword"]
        _save_pending(
            session_id or "",
            {
                "intent": result.intent,
                "awaiting_keyword": True,
                "awaiting_word_count": False,
                "word_count": result.word_count,
                "language": result.language,
                "tone": result.tone,
                "country": result.country,
                "article_type": result.article_type,
                "include_internal_links": result.include_internal_links,
                "include_images": result.include_images,
                "target_website": result.target_website,
            },
        )
    elif result.needs_word_count:
        result.awaiting_word_count = True
        result.missing_fields = ["word_count"]
        _save_pending(
            session_id or "",
            {
                "intent": result.intent,
                "awaiting_keyword": False,
                "awaiting_word_count": True,
                "awaiting_image_source": False,
                "primary_keyword": result.primary_keyword,
                "language": result.language,
                "tone": result.tone,
                "country": result.country,
                "article_type": result.article_type,
                "include_internal_links": result.include_internal_links,
                "include_images": result.include_images,
                "target_website": result.target_website,
            },
        )
    elif result.needs_image_source:
        result.awaiting_image_source = True
        result.missing_fields = ["image_source"]
        _save_pending(
            session_id or "",
            {
                "intent": result.intent,
                "awaiting_keyword": False,
                "awaiting_word_count": False,
                "awaiting_image_source": True,
                "primary_keyword": result.primary_keyword,
                "word_count": result.word_count,
                "language": result.language,
                "tone": result.tone,
                "country": result.country,
                "article_type": result.article_type,
                "include_internal_links": result.include_internal_links,
                "include_images": result.include_images,
                "target_website": result.target_website,
            },
        )
    else:
        clear_pending_workflow(session_id or "")

    result.sync_image_flags()
    return result


def build_workflow_reply(result: WorkflowParseResult) -> str:
    """Tạo phản hồi chatbot cho workflow (plain text — JS hiện tại không đổi)."""
    if not result.is_workflow:
        return ""

    if result.needs_image_source or result.awaiting_image_source:
        img_n = inline_image_count_for_word_count(result.word_count)
        lines = [
            "Mình nhận diện workflow **Research → Gom nhóm → Viết bài SEO**.",
            "",
            f"- **Từ khóa chính:** {result.primary_keyword}",
            f"- **Số từ:** {result.word_count}",
            f"- **Số ảnh dự kiến chèn:** {img_n} ảnh (sau các mục H2 phù hợp)",
            "",
            "Bạn muốn **nguồn ảnh** nào?",
            "- **Không chèn ảnh**",
            "- **Lấy ảnh từ Google** (tìm theo từ khóa + ngữ cảnh H2)",
            "- **Tạo ảnh bằng AI** (prompt theo từng section)",
        ]
        if result.include_internal_links:
            lines.extend(["", "Đã ghi nhận yêu cầu: internal link."])
        lines.extend(["", "_(workflow: keyword_cluster_to_article)_"])
        return "\n".join(lines)

    if result.needs_word_count:
        lines = [
            "Mình nhận diện workflow **Research → Gom nhóm → Viết bài SEO**.",
            "",
            f"- **Từ khóa chính:** {result.primary_keyword}",
            "",
            "Bạn muốn bài dài **bao nhiêu từ**?",
            "Chọn nhanh: **1000** / **1500** / **2000** từ, hoặc nhập số tùy chỉnh (vd: `1800`).",
        ]
        if result.include_internal_links or result.include_images:
            lines.append("")
            extras = []
            if result.include_internal_links:
                extras.append("internal link")
            if result.include_images:
                extras.append("hình ảnh")
            lines.append(f"Đã ghi nhận yêu cầu: {', '.join(extras)}.")
        lines.append("")
        lines.append("_(workflow: keyword_cluster_to_article)_")
        return "\n".join(lines)

    if result.needs_keyword:
        lines = [
            "Mình nhận diện bạn muốn **Research → Gom nhóm → Viết bài SEO** (workflow).",
            "",
            "Vui lòng cho biết **từ khóa chính** bạn muốn research và viết bài.",
            "Ví dụ: `đào tạo SEO`, `bất động sản Hà Nội`, `phần mềm CRM`.",
        ]
        if result.word_count or result.language or result.tone or result.country or result.article_type:
            lines.append("")
            lines.append("Thông tin đã ghi nhận:")
            if result.word_count:
                lines.append(f"- Số từ: **{result.word_count}**")
            if result.language:
                lines.append(f"- Ngôn ngữ: **{result.language}**")
            if result.tone:
                lines.append(f"- Tone: **{result.tone}**")
            if result.country:
                lines.append(f"- Thị trường: **{result.country}**")
            if result.article_type:
                lines.append(f"- Loại bài: **{result.article_type}**")
        lines.append("")
        lines.append("_(workflow: keyword_cluster_to_article)_")
        return "\n".join(lines)

    lines = [
        "Đã nhận lệnh workflow **gom nhóm từ khóa → viết bài SEO**.",
        "",
        f"- **Từ khóa chính:** {result.primary_keyword}",
    ]
    if result.word_count:
        lines.append(f"- **Số từ:** {result.word_count}")
    if result.language:
        lines.append(f"- **Ngôn ngữ:** {result.language}")
    if result.tone:
        lines.append(f"- **Tone:** {result.tone}")
    if result.country:
        lines.append(f"- **Thị trường:** {result.country}")
    if result.article_type:
        lines.append(f"- **Loại bài:** {result.article_type}")

    kw_q = quote(result.primary_keyword or "")
    lines.extend(
        [
            "",
            "**Bước tiếp theo:**",
            "1. Mở **Keyword Clustering**: [/keywords/tools/clustering](/keywords/tools/clustering)",
            f"2. Gom nhóm từ khóa quanh «{result.primary_keyword}».",
            "3. Mở **Content AI**: [/content-ai](/content-ai) để viết bài từ cụm đã gom.",
            "",
            f"Gợi ý nhanh: [/keywords/tools/clustering?seed={kw_q}](/keywords/tools/clustering?seed={kw_q})",
            "",
            "_(workflow: keyword_cluster_to_article)_",
        ]
    )
    return "\n".join(lines)
