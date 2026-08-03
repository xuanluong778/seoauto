"""
Content AI duplicate / same-search-intent detection.

Uses keyword embeddings (cached via semantic_embedding) plus structural signals
(location, content purpose, service core) — no LLM calls on each keystroke.

Hot path: exact normalized keyword first (no embedding). Embeddings only for
remaining same-intent candidates after purpose/location prefilter.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

import numpy as np

from app.services.content_draft_builder import content_ai_extract_geo_tail
from app.services.content_ai_project_store import _projects_for_user, _read_projects_scoped
from app.services.semantic_embedding import embed_keywords

_LOG = logging.getLogger(__name__)

# Per-user corpus cache (projects + schedule [+ optional IL]). Avoids reloading
# on every debounced keystroke. Short TTL keeps new saves visible quickly.
_CORPUS_LOCK = threading.Lock()
_CORPUS_CACHE: dict[str, tuple[float, tuple[Any, ...]]] = {}
_CORPUS_TTL_SEC = 45.0
_CORPUS_CACHE_MAX = 256

MatchType = Literal["exact", "same_intent"]

MSG_EXACT = "Bài viết này đã tồn tại"
MSG_SAME_INTENT = "Đã có bài viết cùng mục đích tìm kiếm"
# Max matching articles returned per keyword (UI cards).
MAX_DUP_MATCHES = 3

# Cosine thresholds for L2-normalized embeddings (dot product).
_INTENT_SIM_THRESHOLD = 0.78
_INTENT_SIM_THRESHOLD_STRONG_STRUCTURE = 0.68
_CORE_SIM_THRESHOLD = 0.82

_FILLER_WORDS = frozenset(
    {
        # EN
        "home",
        "trusted",
        "best",
        "professional",
        "affordable",
        "cheap",
        "local",
        "quality",
        "reliable",
        "quick",
        "fast",
        "top",
        "near",
        "me",
        "the",
        "a",
        "an",
        "for",
        "and",
        "or",
        "in",
        "at",
        "of",
        "to",
        "with",
        "your",
        "our",
        # VI (folded)
        "uy",
        "tin",
        "chuyen",
        "nghiep",
        "nhanh",
        "chong",
        "gia",
        "re",
        "tot",
        "nhat",
        "tai",
        "nha",
        "tan",
        "noi",
        "gan",
        "day",
        "dich",
        "vu",
        "va",
        "cho",
        "cac",
        "mot",
        "nhung",
        "la",
        "co",
        "khong",
        "duoc",
        "tu",
        "tin",
        "cay",
    }
)

_GENERIC_SERVICE_TOKENS = frozenset(
    {
        "sua",
        "repair",
        "service",
        "services",
        "dich",
        "vu",
        "cai",
        "dat",
        "home",
        "tai",
        "nha",
        "uy",
        "tin",
        "chuyen",
        "nghiep",
        "nhanh",
        "online",
        "may",
    }
)

_GEO_STOP_TOKENS = frozenset(
    {
        "quan",
        "district",
        "huyen",
        "phuong",
        "tp",
        "thanh",
        "pho",
        "tai",
        "at",
        "o",
    }
)

_PURPOSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "pricing",
        re.compile(
            r"\b("
            r"gia|bang\s*gia|bao\s*gia|chi\s*phi|price|pricing|cost|costs|"
            r"bao\s*nhieu|how\s*much|phi\s*dich\s*vu"
            r")\b",
            re.I,
        ),
    ),
    (
        "faq",
        re.compile(
            r"\b("
            r"faq|cau\s*hoi\s*thuong\s*gap|frequently\s*asked|q\s*&\s*a|hoi\s*dap"
            r")\b",
            re.I,
        ),
    ),
    (
        "guide",
        re.compile(
            r"\b("
            r"huong\s*dan|cach\s+|howto|how\s*to|guide|tutorial|tips|"
            r"meo\s+|tu\s*sua|diy|"
            r"loi|loi\s+|khac\s*phuc|troubleshoot|bsod|man\s*hinh\s*xanh|blue\s*screen|"
            r"sua\s*loi|fix\s+|fixing"
            r")\b",
            re.I,
        ),
    ),
    (
        "comparison",
        re.compile(
            r"\b("
            r"so\s*sanh|compare|comparison|vs\.?|versus|review|danh\s*gia|top\s+\d+"
            r")\b",
            re.I,
        ),
    ),
]

_PURPOSE_STRIP = re.compile(
    r"\b("
    r"gia|bang\s*gia|bao\s*gia|chi\s*phi|price|pricing|cost|costs|"
    r"faq|cau\s*hoi\s*thuong\s*gap|huong\s*dan|cach|howto|how\s*to|guide|tutorial|"
    r"so\s*sanh|compare|comparison|vs|versus|review|danh\s*gia"
    r")\b",
    re.I,
)

_GEO_STRIP = re.compile(
    r"(?:"
    r"\b(?:quan|huyen|district|tp\.?|thanh\s*pho|phuong)\s+[\w\-]+"
    r"|"
    r"\b(?:district|quan|q\.?)\s*\d{1,2}\b"
    r"|"
    r"\bquan-\d{1,2}\b"
    r")",
    re.I,
)

# Paths that are never content pages (taxonomy / system).
_NON_CONTENT_PATH_RE = re.compile(
    r"(?:^|/)(?:category|tag|author|page)(?:/|$)",
    re.I,
)

# Unrelated device/service topics — exclude from computer troubleshooting matches.
_UNRELATED_DEVICE_RE = re.compile(
    r"may-in|may-lanh|dien-thoai|may-anh|may-giat|tu-lanh|dieu-hoa",
    re.I,
)

# Service-intent duplicate scan: skip blog/news listing paths (not for info/guide intent).
_SERVICE_BLOG_EXCLUDE_RE = re.compile(
    r"(?:^|/)(?:blog|tin-tuc|tin-cong-nghe)(?:/|$)",
    re.I,
)

# Legacy alias — service-path checks only.
_EXCLUDED_PATH_RE = re.compile(
    r"(?:^|/)(?:blog|tin-tuc|tin-cong-nghe|category|tag|author|page)(?:/|$)|"
    r"may-in|may-lanh|dien-thoai|may-anh|may-giat|tu-lanh|dieu-hoa",
    re.I,
)

_SERVICE_GROUP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sua_may_tinh", re.compile(r"may[\s\-_]?tinh|sua[\s\-_]?may[\s\-_]?tinh", re.I)),
    ("sua_may_in", re.compile(r"may[\s\-_]?in\b|sua[\s\-_]?may[\s\-_]?in\b", re.I)),
    ("sua_may_lanh", re.compile(r"may[\s\-_]?lanh|sua[\s\-_]?may[\s\-_]?lanh", re.I)),
    ("sua_dien_thoai", re.compile(r"dien[\s\-_]?thoai|sua[\s\-_]?dien[\s\-_]?thoai", re.I)),
]

# Device / object entity (hard filter before embedding).
_ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("may_tinh", re.compile(r"may[\s\-_]?tinh|computer|pc\b|laptop", re.I)),
    ("may_in", re.compile(r"may[\s\-_]?in\b|printer", re.I)),
    ("may_lanh", re.compile(r"may[\s\-_]?lanh|dieu[\s\-_]?hoa|air[\s\-_]?cond", re.I)),
    ("dien_thoai", re.compile(r"dien[\s\-_]?thoai|phone|smartphone", re.I)),
]

# Core troubleshooting problems — mutually exclusive hard filters.
# Order matters: more specific patterns first.
_PRIMARY_PROBLEM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "khong_len_nguon",
        re.compile(
            r"khong[\s\-_]?len[\s\-_]?nguon|no[\s\-_]?power|wont[\s\-_]?(?:turn|power)[\s\-_]?on|"
            r"khong[\s\-_]?mo[\s\-_]?nguon|khong[\s\-_]?khoi[\s\-_]?dong",
            re.I,
        ),
    ),
    (
        "khong_len_man_hinh",
        re.compile(
            r"khong[\s\-_]?len[\s\-_]?man[\s\-_]?hinh|no[\s\-_]?display|black[\s\-_]?screen|"
            r"man[\s\-_]?hinh[\s\-_]?den|khong[\s\-_]?co[\s\-_]?hinh",
            re.I,
        ),
    ),
    (
        "man_hinh_xanh",
        re.compile(
            r"man[\s\-_]?hinh[\s\-_]?xanh|blue[\s\-_]?screen|bsod|man[\s\-_]?hinh[\s\-_]?xanh[\s\-_]?chet",
            re.I,
        ),
    ),
    (
        "tat_dot_ngot",
        re.compile(
            r"tat[\s\-_]?dot[\s\-_]?ngot|shutdown[\s\-_]?suddenly|sudden[\s\-_]?shutdown|"
            r"restart[\s\-_]?dot[\s\-_]?ngot|tu[\s\-_]?tat|crash[\s\-_]?dot[\s\-_]?ngot",
            re.I,
        ),
    ),
    (
        "khong_wifi",
        re.compile(
            r"khong[\s\-_]?co[\s\-_]?wifi|mat[\s\-_]?wifi|no[\s\-_]?wifi|wifi[\s\-_]?khong|"
            r"khong[\s\-_]?ket[\s\-_]?noi[\s\-_]?wifi|mat[\s\-_]?mang[\s\-_]?wifi",
            re.I,
        ),
    ),
    (
        "cham_lag",
        re.compile(r"may[\s\-_]?tinh[\s\-_]?cham|laptop[\s\-_]?cham|\blag\b|treo[\s\-_]?may", re.I),
    ),
    (
        "qua_nhiet",
        re.compile(r"qua[\s\-_]?nhiet|overheat|nong[\s\-_]?may", re.I),
    ),
]


@dataclass(frozen=True)
class KeywordIntent:
    intent_kind: str  # service | informational | other
    service_group: str
    topic_group: str
    entity: str  # may_tinh | may_in | …
    primary_problem: str  # khong_len_nguon | tat_dot_ngot | …
    location: str
    purpose: str
    slug_candidates: tuple[str, ...]


# Tokens that must stay in informational slug candidates even if listed as filler.
_PROBLEM_SLUG_KEEP = frozenset(
    {
        "khong",
        "len",
        "nguon",
        "mat",
        "wifi",
        "tat",
        "dot",
        "ngot",
        "man",
        "hinh",
        "xanh",
        "loi",
        "co",
        "den",
    }
)


def keyword_to_slug_candidate(keyword: str) -> str:
    """Fold keyword to WP-style slug (loi-may-tinh-khong-len-nguon)."""
    folded = _fold(keyword)
    tokens = []
    for t in re.split(r"[^a-z0-9]+", folded):
        if not t or len(t) < 2:
            continue
        if t in _FILLER_WORDS and t not in _PROBLEM_SLUG_KEEP:
            continue
        tokens.append(t)
    return "-".join(tokens)


def classify_intent_kind(keyword: str) -> str:
    """service = hire/repair local pages; informational = blog/guide/troubleshooting."""
    folded = _fold(keyword)
    if not folded:
        return "other"
    purpose = classify_content_purpose(keyword)
    if purpose in ("guide", "faq", "comparison", "pricing"):
        return "informational"
    if re.search(
        r"\b(loi|loi\s|khac\s*phuc|troubleshoot|bsod|man\s*hinh\s*xanh|blue\s*screen|"
        r"huong\s*dan|cach\s+|fix\s+|sua\s*loi)\b",
        folded,
    ):
        return "informational"
    if re.search(r"\b(sua|repair|dich\s*vu)\b", folded):
        return "service"
    if purpose == "service":
        return "service"
    if extract_location_key(keyword) and detect_service_group(keyword):
        return "service"
    return "other"


def detect_entity(text: str) -> str:
    """Device/object entity for hard filtering (may_tinh, may_in, …)."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    blob = f"{_fold(raw)} {_slug_norm(raw)} {raw.lower().replace('-', ' ')}"
    for name, pat in _ENTITY_PATTERNS:
        if pat.search(blob):
            return name
    return ""


def extract_primary_problem(text: str) -> str:
    """Core troubleshooting problem key — mutually exclusive hard filter."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    blob = f"{_fold(raw)} {_slug_norm(raw)} {raw.lower().replace('-', ' ').replace('_', ' ')}"
    for name, pat in _PRIMARY_PROBLEM_PATTERNS:
        if pat.search(blob):
            return name
    return ""


def detect_topic_group(text: str) -> str:
    """Topic cluster for informational / troubleshooting keywords."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    entity = detect_entity(raw)
    problem = extract_primary_problem(raw)
    if entity and problem:
        return f"{entity}__{problem}"
    if problem:
        return problem
    if entity:
        # Generic device troubleshoot without a known primary problem.
        if re.search(r"\bloi\b", _fold(raw)):
            return f"{entity}__loi"
        return entity
    ents = sorted(_keyword_entity_tokens(raw))
    if len(ents) >= 2:
        return "_".join(ents)[:48]
    return ents[0] if ents else ""


def _purposes_compatible_info(purpose_a: str, purpose_b: str) -> bool:
    info = {"guide", "faq", "other", "comparison", "pricing"}
    if purpose_a in info and purpose_b in info:
        return True
    return purpose_a == purpose_b


def _entities_compatible(entity_a: str, entity_b: str) -> bool:
    a = str(entity_a or "").strip()
    b = str(entity_b or "").strip()
    if not a or not b:
        # Missing entity on either side → do not hard-block (exact/slug still wins).
        return True
    return a == b


def _primary_problems_compatible(prob_a: str, prob_b: str) -> bool:
    """Different known primary problems are never same-intent."""
    a = str(prob_a or "").strip()
    b = str(prob_b or "").strip()
    if a and b:
        return a == b
    # One side has a known problem and the other does not → not same core issue.
    if a or b:
        return False
    return True


def _topic_tokens_from_text(text: str) -> set[str]:
    return _keyword_entity_tokens(text) | {
        tok for tok in _fold(text).split() if len(tok) > 2 and tok not in _FILLER_WORDS
    }


def _ref_topic_tokens(ref: ExistingArticleRef) -> set[str]:
    blob = " ".join(x for x in (ref.slug, _url_path_slug(ref.url), ref.title, ref.keyword) if x)
    return _topic_tokens_from_text(blob)


def _ref_entity(ref: ExistingArticleRef) -> str:
    for src in (ref.slug, _url_path_slug(ref.url), ref.title, ref.keyword):
        ent = detect_entity(src)
        if ent:
            return ent
    return ""


def _ref_primary_problem(ref: ExistingArticleRef) -> str:
    for src in (ref.slug, _url_path_slug(ref.url), ref.title, ref.keyword):
        prob = extract_primary_problem(src)
        if prob:
            return prob
    return ""


def _hard_filter_info_candidate(kw_intent: KeywordIntent, ref: ExistingArticleRef) -> bool:
    """Require same entity + same primaryProblem before same-intent / embedding."""
    if kw_intent.intent_kind != "informational":
        return True
    # Soft matches need at least entity or primaryProblem on the query.
    if not kw_intent.entity and not kw_intent.primary_problem:
        return False
    if not _entities_compatible(kw_intent.entity, _ref_entity(ref)):
        return False
    if not _primary_problems_compatible(kw_intent.primary_problem, _ref_primary_problem(ref)):
        return False
    return True


def _is_unrelated_device_blob(blob: str, *, kw_blob: str = "") -> bool:
    low = str(blob or "").lower()
    if not _UNRELATED_DEVICE_RE.search(low):
        return False
    kw = str(kw_blob or "").lower()
    if re.search(r"may-tinh|may tinh|may_tinh", kw):
        return not re.search(r"may-tinh|may tinh|may_tinh", low)
    return True


def detect_service_group(text: str) -> str:
    return _service_group_from_text(text)


def parse_keyword_intent(keyword: str) -> KeywordIntent:
    kw = re.sub(r"\s+", " ", str(keyword or "").strip())
    kind = classify_intent_kind(kw)
    purpose = classify_content_purpose(kw)
    loc = ref_location_key_from_text(kw)
    group = detect_service_group(kw) if kind == "service" else ""
    entity = detect_entity(kw)
    primary_problem = extract_primary_problem(kw) if kind == "informational" else ""
    topic = detect_topic_group(kw) if kind == "informational" else ""
    slugs = tuple(build_slug_candidates(kw, service_group=group, location=loc, intent_kind=kind))
    return KeywordIntent(
        intent_kind=kind,
        service_group=group,
        topic_group=topic,
        entity=entity,
        primary_problem=primary_problem,
        location=loc,
        purpose=purpose,
        slug_candidates=slugs,
    )


def _service_group_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    blob = f"{raw} {_slug_norm(raw)}"
    for name, pat in _SERVICE_GROUP_PATTERNS:
        if pat.search(blob):
            return name
    core = extract_service_core(raw)
    ents = sorted(_service_entity_tokens(core))
    # Ignore single-token noise from short titles like "Bài A".
    if len(ents) >= 2 or (len(ents) == 1 and len(core.split()) >= 2):
        return "_".join(ents)[:48]
    return ""


def ref_location_key_from_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    m_slug = re.search(r"quan-(\d{1,2})\b", low)
    if m_slug:
        return f"district {int(m_slug.group(1))}"
    m_q = re.search(r"\bq-(\d{1,2})\b", low)
    if m_q:
        return f"district {int(m_q.group(1))}"
    folded = _fold(raw)
    m_d = re.search(r"\bd[\s\-]?(\d{1,2})\b", folded)
    if m_d:
        return f"district {int(m_d.group(1))}"
    return extract_location_key(raw)


def ref_location_key(ref: ExistingArticleRef) -> str:
    for src in (ref.slug, _url_path_slug(ref.url), ref.keyword, ref.title):
        loc = ref_location_key_from_text(src)
        if loc:
            return loc
    return ""


def ref_service_group_key(ref: ExistingArticleRef) -> str:
    for src in (ref.slug, _url_path_slug(ref.url), ref.keyword, ref.title):
        grp = _service_group_from_text(src)
        if grp:
            return grp
    return ""


def build_slug_candidates(
    keyword: str,
    *,
    service_group: str = "",
    location: str = "",
    intent_kind: str = "",
) -> list[str]:
    kind = intent_kind or classify_intent_kind(keyword)
    if kind == "informational":
        slug = keyword_to_slug_candidate(keyword)
        return [slug] if slug else []

    grp = service_group or detect_service_group(keyword)
    loc = location or ref_location_key_from_text(keyword)
    m = re.search(r"(\d{1,2})", loc or "")
    if not m:
        # Service keywords without district still get a direct slug fallback.
        direct = keyword_to_slug_candidate(keyword)
        return [direct] if direct else []
    n = int(m.group(1))
    bases: list[str] = []
    if grp == "sua_may_tinh":
        bases = ["sua-may-tinh"]
    elif grp == "sua_may_in":
        bases = ["sua-may-in"]
    elif grp == "sua_may_lanh":
        bases = ["sua-may-lanh"]
    elif grp == "sua_dien_thoai":
        bases = ["sua-dien-thoai"]
    else:
        core = extract_service_core(keyword)
        if core:
            bases = ["-".join(core.split())]
    out: list[str] = []
    for base in bases:
        out.extend(
            [
                f"{base}-quan-{n}",
                f"{base}-tai-nha-quan-{n}",
                f"{base}-q-{n}",
            ]
        )
    direct = keyword_to_slug_candidate(keyword)
    if direct:
        out.insert(0, direct)
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def all_slug_candidates_for_keyword(keyword: str) -> list[str]:
    """All slug lookup candidates including direct keyword slug."""
    intent = parse_keyword_intent(keyword)
    out: list[str] = []
    seen: set[str] = set()
    direct = keyword_to_slug_candidate(keyword)
    if direct and direct not in seen:
        seen.add(direct)
        out.append(direct)
    for slug in intent.slug_candidates:
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _path_matches_intent(path: str, intent: KeywordIntent) -> bool:
    p = str(path or "").lower()
    folded = _fold(path)
    blob = f"{p} {folded} {folded.replace(' ', '-')}"
    if not blob.strip():
        return False
    if _NON_CONTENT_PATH_RE.search(blob):
        return False
    if _is_unrelated_device_blob(blob):
        return False

    if intent.intent_kind == "informational":
        if intent.entity == "may_tinh" or (intent.entity and intent.entity.startswith("may_")):
            ent_pat = intent.entity.replace("_", r"[\s\-_]?")
            if intent.entity == "may_tinh":
                if not re.search(r"may-tinh|may tinh|may_tinh|computer|pc|laptop", blob):
                    return False
            elif ent_pat and not re.search(ent_pat, blob):
                return False
            if re.search(r"may-in|may-lanh|dien-thoai", blob) and not re.search(
                r"may-tinh|may tinh", blob
            ):
                return False
        if intent.primary_problem:
            # Path must contain the same primary problem slug fragment when known.
            frag = intent.primary_problem.replace("_", "-")
            frag_space = intent.primary_problem.replace("_", " ")
            if frag not in blob and frag_space not in folded and frag.replace("-", "") not in blob.replace("-", ""):
                # Allow parent path only if slug candidate matches (handled elsewhere);
                # for sitemap scoring we require problem signal when present.
                prob_from_path = extract_primary_problem(blob)
                if prob_from_path and prob_from_path != intent.primary_problem:
                    return False
                if not intent.slug_candidates or not any(s in p for s in intent.slug_candidates):
                    # Keep broad sitemap candidates only when no conflicting problem.
                    if prob_from_path and prob_from_path != intent.primary_problem:
                        return False
        return True

    if _SERVICE_BLOG_EXCLUDE_RE.search(blob):
        return False
    if _UNRELATED_DEVICE_RE.search(blob):
        return False
    if intent.service_group == "sua_may_tinh":
        if not re.search(r"may-tinh|sua-may-tinh|may tinh|sua may tinh", blob):
            return False
        if re.search(r"may-in|may-lanh|dien-thoai|may in\b|may lanh", blob):
            return False
    elif intent.service_group == "sua_may_in":
        if not re.search(r"may-in|sua-may-in|may in\b|sua may in\b", blob):
            return False
    elif intent.service_group == "sua_may_lanh":
        if not re.search(r"may-lanh|sua-may-lanh|may lanh|sua may lanh", blob):
            return False
    elif intent.service_group:
        frag = intent.service_group.replace("_", "-")
        if frag and frag not in blob and frag.replace("-", " ") not in folded:
            return False
    if intent.location:
        m = re.search(r"(\d{1,2})", intent.location)
        if m:
            num = m.group(1)
            if not re.search(rf"(?:quan-{num}|quan{num}|q-{num}|quan {num})(?:/|$|-|\b)", blob):
                return False
    return True


def _ref_slug_matches_keyword(kw: str, ref: ExistingArticleRef) -> bool:
    kw_slug = keyword_to_slug_candidate(kw)
    ref_slug = str(ref.slug or _url_path_slug(ref.url) or "").strip().lower()
    if kw_slug and ref_slug and kw_slug == ref_slug:
        return True
    if ref_slug and _slug_norm(ref_slug) == _slug_norm(kw):
        return True
    return False


def _ref_structural_info_match(kw: str, ref: ExistingArticleRef, intent: KeywordIntent | None = None) -> bool:
    """Same entity + same primary problem + compatible purpose — no embedding."""
    sig = intent or parse_keyword_intent(kw)
    ref_purpose = classify_content_purpose(ref.title or ref.keyword or ref.slug or kw)
    if not _purposes_compatible_info(sig.purpose, ref_purpose):
        return False
    # Slug/title exact is handled in exact pass; here require hard filters.
    if not _hard_filter_info_candidate(sig, ref):
        return False
    if _ref_slug_matches_keyword(kw, ref):
        return True
    # Same known primary problem + entity → same_intent (paraphrase titles).
    if sig.entity and sig.primary_problem:
        if _ref_entity(ref) == sig.entity and _ref_primary_problem(ref) == sig.primary_problem:
            return True
        return False
    # No known primary problem: require strong token overlap on problem words (strict).
    kw_tokens = _topic_tokens_from_text(kw)
    ref_tokens = _ref_topic_tokens(ref)
    if not kw_tokens or not ref_tokens:
        return False
    overlap = len(kw_tokens & ref_tokens) / max(1, len(kw_tokens))
    return overlap >= 0.75 and _token_jaccard(_fold(kw), _fold(ref.title or ref.keyword or ref.slug)) >= 0.66


def _ref_structural_intent_match(kw: str, ref: ExistingArticleRef, intent: KeywordIntent | None = None) -> bool:
    """Same service group + same district + hire/service purpose — no embedding."""
    sig = intent or parse_keyword_intent(kw)
    if sig.intent_kind == "informational":
        return _ref_structural_info_match(kw, ref, sig)
    if not sig.service_group:
        return False
    ref_group = ref_service_group_key(ref)
    if not ref_group or ref_group != sig.service_group:
        return False
    ref_loc = ref_location_key(ref)
    if not locations_compatible(sig.location, ref_loc):
        return False
    ref_purpose = classify_content_purpose(ref.title or ref.keyword or ref.slug)
    if sig.purpose != ref_purpose:
        return False
    # Slug / URL path is the strongest signal for published WP pages.
    slug_path = str(ref.slug or _url_path_slug(ref.url) or "").strip()
    path_blob = " ".join(
        x for x in (ref.slug, _url_path_slug(ref.url), _fold(ref.title), _fold(ref.keyword)) if x
    )
    substantive_path = bool(
        slug_path
        and (
            _service_group_from_text(slug_path)
            or ref_location_key_from_text(slug_path)
            or len(slug_path) > 12
        )
    )
    if substantive_path and path_blob and not _path_matches_intent(path_blob, sig):
        return False
    return True


def _filter_corpus_for_keywords(
    corpus: list[ExistingArticleRef],
    keywords: list[str],
) -> list[ExistingArticleRef]:
    cleaned = [re.sub(r"\s+", " ", str(k or "").strip()) for k in keywords if str(k or "").strip()]
    if not cleaned:
        return corpus
    out: list[ExistingArticleRef] = []
    for ref in corpus:
        if any(_corpus_relevant_for_keyword(k, ref) for k in cleaned):
            out.append(ref)
    return out


def _corpus_relevant_for_keyword(kw: str, ref: ExistingArticleRef) -> bool:
    """Scope corpus rows by intent kind before matching."""
    sig = parse_keyword_intent(kw)
    blob = " ".join(
        x for x in (ref.slug, _url_path_slug(ref.url), ref.keyword, ref.title) if x
    )
    if not blob:
        return False

    # Slug/title exact hits always stay in corpus.
    if _ref_slug_matches_keyword(kw, ref) or _ref_exact_match(kw, ref):
        return True

    if sig.intent_kind == "informational":
        if _NON_CONTENT_PATH_RE.search(blob.lower()):
            return False
        if _is_unrelated_device_blob(blob.lower(), kw_blob=_fold(kw)):
            return False
        # Hard filter: entity + primaryProblem before any loose token overlap.
        if not _hard_filter_info_candidate(sig, ref):
            return False
        return True

    if not sig.service_group:
        return True
    if _SERVICE_BLOG_EXCLUDE_RE.search(blob.lower()):
        return False
    if _UNRELATED_DEVICE_RE.search(blob.lower()):
        return False
    ref_group = ref_service_group_key(ref)
    if ref_group and ref_group != sig.service_group:
        return False
    if sig.location and ref_location_key(ref):
        if not locations_compatible(sig.location, ref_location_key(ref)):
            return False
    return True


@dataclass(frozen=True)
class ExistingArticleRef:
    keyword: str
    title: str = ""
    url: str = ""
    slug: str = ""
    source: str = "content_ai"  # content_ai | published
    project_id: str = ""
    target_website: str = ""
    wp_post_id: int = 0


@dataclass(frozen=True)
class DuplicateMatch:
    match_type: MatchType
    message: str
    existing: ExistingArticleRef
    score: float = 1.0


def normalize_keyword(pk: str) -> str:
    s = re.sub(r"\s+", " ", str(pk or "").strip())
    s = re.split(r"\s*[|]\s*", s, maxsplit=1)[0].strip()
    return s.lower()


def _slug_norm(slug: str) -> str:
    return _fold(str(slug or "").replace("-", " ").replace("_", " "))


def _url_path_slug(url: str) -> str:
    path = str(urlparse(str(url or "").strip()).path or "").strip("/")
    if not path:
        return ""
    return path.split("/")[-1]


def _ref_exact_match(kw: str, ref: ExistingArticleRef) -> bool:
    """Exact duplicate: keyword, title, slug, or URL path slug (normalized)."""
    nk = normalize_keyword(kw)
    if not nk:
        return False
    if normalize_keyword(ref.keyword) == nk:
        return True
    if ref.title and normalize_keyword(ref.title) == nk:
        return True
    if ref.slug and _slug_norm(ref.slug) == _slug_norm(kw):
        return True
    path_slug = _url_path_slug(ref.url)
    if path_slug and _slug_norm(path_slug) == _slug_norm(kw):
        return True
    # Diacritics-insensitive equality for Vietnamese titles/keywords.
    if ref.title and _fold(ref.title) == _fold(kw):
        return True
    if ref.keyword and _fold(ref.keyword) == _fold(kw):
        return True
    return False


def _merge_corpus_refs(
    base: list[ExistingArticleRef],
    extra: list[ExistingArticleRef],
) -> list[ExistingArticleRef]:
    seen = {_ref_dedupe_key(r) for r in base}
    out = list(base)
    for ref in extra:
        key = _ref_dedupe_key(ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _fold(s: str) -> str:
    t = (s or "").replace("Đ", "D").replace("đ", "d")
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", t).strip().lower()


def classify_content_purpose(keyword: str) -> str:
    """pricing | faq | guide | comparison | service | other"""
    folded = _fold(keyword)
    if not folded:
        return "other"
    for name, pat in _PURPOSE_PATTERNS:
        if pat.search(folded):
            return name
    # Local / service-ish keywords default to service purpose.
    if content_ai_extract_geo_tail(keyword) or any(
        x in folded for x in ("sua", "repair", "service", "dich vu", "cai win", "cai dat")
    ):
        return "service"
    return "other"


def extract_location_key(keyword: str) -> str:
    raw = str(keyword or "").strip()
    low = raw.lower()
    m_slug = re.search(r"quan-(\d{1,2})\b", low)
    if m_slug:
        return f"district {int(m_slug.group(1))}"
    raw_folded = _fold(keyword)
    # Prefer explicit district / quận markers in EN or VI.
    m = re.search(r"(?:quan|district|q\.?)\s*(\d{1,2})\b", raw_folded)
    if m:
        return f"district {int(m.group(1))}"
    m2 = re.search(r"(?:huyen)\s+([a-z0-9]+(?:\s+[a-z0-9]+)?)", raw_folded)
    if m2:
        return f"huyen {m2.group(1).strip()}"
    geo = content_ai_extract_geo_tail(keyword) or ""
    folded = _fold(geo)
    if not folded:
        # "in District 9" / "at Thuận An" style tails
        m3 = re.search(r"\b(?:in|at|tai|o)\s+([a-z0-9]+(?:\s+[a-z0-9]+)?)\s*$", raw_folded)
        if m3:
            place = m3.group(1).strip()
            if place and place not in _FILLER_WORDS:
                return place
        return ""
    m4 = re.search(r"(?:quan|district|q\.?)\s*(\d{1,2})\b", folded)
    if m4:
        return f"district {int(m4.group(1))}"
    return folded


def extract_service_core(keyword: str) -> str:
    """Keyword with geo, purpose markers, and filler adjectives removed."""
    folded = _fold(keyword)
    if not folded:
        return ""
    folded = _PURPOSE_STRIP.sub(" ", folded)
    folded = _GEO_STRIP.sub(" ", folded)
    # Strip trailing/leading bare location leftovers (numbers after district removed).
    folded = re.sub(r"\b\d{1,2}\b", " ", folded)
    tokens = [t for t in re.split(r"[^a-z0-9]+", folded) if t and t not in _FILLER_WORDS and len(t) > 1]
    return " ".join(tokens)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.size == 0 or b.size == 0:
        return 0.0
    if a.shape != b.shape:
        return 0.0
    return float(np.dot(a, b))


def _token_jaccard(a: str, b: str) -> float:
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _service_entity_tokens(core: str) -> set[str]:
    return {
        tok for tok in core.split()
        if tok and tok not in _GENERIC_SERVICE_TOKENS and len(tok) > 1
    }


def _keyword_entity_tokens(keyword: str) -> set[str]:
    tokens = [t for t in re.split(r"[^a-z0-9]+", _fold(keyword)) if t]
    out = {
        tok for tok in tokens
        if len(tok) > 1
        and tok not in _FILLER_WORDS
        and tok not in _GENERIC_SERVICE_TOKENS
        and tok not in _GEO_STOP_TOKENS
        and not tok.isdigit()
    }
    for i, tok in enumerate(tokens[:-1]):
        nxt = tokens[i + 1]
        if tok == "may" and nxt and nxt not in _GEO_STOP_TOKENS and not nxt.isdigit():
            out.add(f"may_{nxt}")
    return out


def locations_compatible(loc_a: str, loc_b: str) -> bool:
    """Different explicit locations → incompatible. Missing on either side → ok only if both empty."""
    a = (loc_a or "").strip()
    b = (loc_b or "").strip()
    if a and b:
        return a == b
    # One local + one generic: treat as different purpose/scope (avoid false positive).
    if a or b:
        return False
    return True


def _collect_content_ai_articles(
    *,
    user_id: int,
    exclude_project_id: str | None = None,
) -> list[ExistingArticleRef]:
    out: list[ExistingArticleRef] = []
    excl = str(exclude_project_id or "").strip()
    for p in _projects_for_user(_read_projects_scoped(user_id), user_id):
        pid = str(p.get("id") or "").strip()
        if excl and pid == excl:
            continue
        kw = str(p.get("primary_keyword") or "").strip()
        if not kw:
            continue
        title = str(p.get("title") or p.get("custom_title") or "").strip() or kw
        url = str(p.get("wp_post_url") or "").strip()
        source = "published" if url else "content_ai"
        out.append(
            ExistingArticleRef(
                keyword=kw,
                title=title,
                url=url,
                source=source,
                project_id=pid,
                target_website=str(p.get("target_website") or "").strip(),
            )
        )
    return out


def _collect_publish_schedule_articles(
    *,
    user_id: int,
    db: Any | None,
    exclude_project_id: str | None = None,
) -> list[ExistingArticleRef]:
    if db is None:
        return []
    try:
        from app.models.content_ai_publish_schedule import ContentAIPublishSchedule
        from sqlalchemy import select

        # Minimal columns only — avoid loading content_html on every keystroke.
        q = (
            select(
                ContentAIPublishSchedule.project_id,
                ContentAIPublishSchedule.keyword,
                ContentAIPublishSchedule.title,
                ContentAIPublishSchedule.wp_post_url,
            )
            .where(ContentAIPublishSchedule.user_id == int(user_id))
            .where(ContentAIPublishSchedule.status.in_(("published", "scheduled", "publishing", "draft")))
            .order_by(ContentAIPublishSchedule.id.desc())
            .limit(500)
        )
        rows = db.execute(q).all()
    except Exception as exc:
        _LOG.debug("publish schedule corpus skipped: %s", exc)
        return []

    excl = str(exclude_project_id or "").strip()
    out: list[ExistingArticleRef] = []
    seen_kw: set[str] = set()
    for r in rows:
        pid = str(getattr(r, "project_id", None) or (r[0] if len(r) > 0 else "") or "").strip()
        if excl and pid == excl:
            continue
        kw = str(getattr(r, "keyword", None) or (r[1] if len(r) > 1 else "") or "").strip()
        if not kw:
            continue
        nk = normalize_keyword(kw)
        if nk in seen_kw:
            continue
        seen_kw.add(nk)
        title = str(getattr(r, "title", None) or (r[2] if len(r) > 2 else "") or "").strip() or kw
        url = str(getattr(r, "wp_post_url", None) or (r[3] if len(r) > 3 else "") or "").strip()
        out.append(
            ExistingArticleRef(
                keyword=kw,
                title=title,
                url=url,
                source="published" if url else "content_ai",
                project_id=pid,
            )
        )
    return out


def _owned_site_bases(user_id: int, *, target_website: str = "", role: str = "user") -> list[str]:
    from app.services.publishing_sites_store import list_sites
    from app.services.site_ownership import user_owns_wp_site
    from app.services.wp_connect import normalize_wp_base_url

    sites: list[str] = []
    tw = str(target_website or "").strip()
    if tw:
        try:
            base = normalize_wp_base_url(tw)
        except Exception:
            base = tw.rstrip("/")
        if user_owns_wp_site(user_id, base, role=role):
            sites.append(base)
        return sites

    seen: set[str] = set()
    try:
        for s in list_sites(user_id=user_id):
            u = str(s.get("url") or s.get("website_url") or "").strip()
            if not u:
                continue
            try:
                base = normalize_wp_base_url(u)
            except Exception:
                base = u.rstrip("/")
            if base and base not in seen and user_owns_wp_site(user_id, base, role=role):
                seen.add(base)
                sites.append(base)
    except Exception as exc:
        _LOG.debug("owned sites list failed: %s", exc)
    return sites


def _resolve_wp_site_id(user_id: int, target_website: str, *, role: str = "user") -> str | None:
    """Map owned target website URL to Content Auto Update site id."""
    tw = str(target_website or "").strip()
    if not tw:
        return None
    from app.services.site_ownership import user_owns_wp_site
    from app.services.wp_connect import normalize_wp_base_url
    from app.services.wp_site_connector import _site_url_key, list_sites as wp_list_sites

    if not user_owns_wp_site(user_id, tw, role=role):
        return None
    try:
        url_key = _site_url_key(normalize_wp_base_url(tw))
    except Exception:
        url_key = tw.rstrip("/").lower()
    for s in wp_list_sites(user_id):
        if _site_url_key(str(s.get("url") or "")) == url_key:
            sid = str(s.get("id") or "").strip()
            if sid:
                return sid
    return None


def _resolve_publishing_wp_credentials(
    user_id: int,
    target_website: str,
    *,
    role: str = "user",
) -> dict[str, str] | None:
    """Publishing-store WordPress credentials for an owned target website."""
    tw = str(target_website or "").strip()
    if not tw:
        return None
    from app.services.publishing_sites_store import get_site as pub_get_site, list_sites as pub_list_sites
    from app.services.site_ownership import user_owns_wp_site
    from app.services.wp_connect import normalize_wp_base_url
    from app.services.wp_site_connector import _site_url_key

    if not user_owns_wp_site(user_id, tw, role=role):
        return None
    try:
        url_key = _site_url_key(normalize_wp_base_url(tw))
        site_base = normalize_wp_base_url(tw)
    except Exception:
        url_key = tw.rstrip("/").lower()
        site_base = tw.rstrip("/")
    for row in pub_list_sites(user_id=user_id, platform="wordpress"):
        u = str(row.get("url") or "").strip()
        if not u:
            continue
        try:
            row_key = _site_url_key(normalize_wp_base_url(u))
        except Exception:
            row_key = u.rstrip("/").lower()
        if row_key != url_key:
            continue
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        full = pub_get_site(sid, user_id=user_id, reveal_password=True)
        if not full:
            continue
        username = str(full.get("username") or "").strip()
        pwd = str(full.get("app_password") or "").strip()
        if username and pwd:
            return {
                "url": site_base,
                "username": username,
                "app_password": pwd.replace(" ", ""),
            }
    return None


def _wp_auth_headers(username: str, app_password: str) -> dict[str, str]:
    import base64

    cred = f"{str(username or '').strip()}:{str(app_password or '').strip()}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(cred).decode("ascii"),
        "Accept": "application/json",
    }


def _fetch_wp_posts_direct(
    *,
    site_base: str,
    username: str,
    app_password: str,
    search: str = "",
    slug: str = "",
    max_posts: int = 120,
) -> list[dict[str, Any]]:
    """Fetch published posts via WordPress REST using site credentials."""
    from app.services.wp_connect import parse_wp_response_json, wp_get_json

    headers = _wp_auth_headers(username, app_password)
    auth = (username, app_password)
    params: dict[str, Any] = {
        "context": "view",
        "status": "publish",
        "_fields": "id,link,slug,status,title",
        "per_page": min(20, max_posts),
        "page": 1,
    }
    slug_hint = re.sub(r"[^a-z0-9\-]+", "", str(slug or "").strip().lower())
    resources = ["posts", "pages"] if slug_hint else ["posts"]

    def _rows_from_resource(resource: str) -> list[dict[str, Any]]:
        req_params = dict(params)
        if slug_hint:
            req_params["slug"] = slug_hint
        else:
            q = re.sub(r"\s+", " ", str(search or "").strip())
            if q:
                req_params["search"] = q[:200]
        try:
            resp, _base = wp_get_json(
                f"/wp-json/wp/v2/{resource}",
                url=site_base,
                headers=headers,
                auth=auth,
                params=req_params,
                timeout=45,
            )
        except Exception as exc:
            _LOG.debug(
                "wp direct %s failed base=%s slug=%r search=%r: %s",
                resource,
                site_base,
                slug_hint,
                search[:40],
                exc,
            )
            return []
        if resp.status_code >= 400:
            return []
        try:
            rows = parse_wp_response_json(resp)
        except Exception as exc:
            _LOG.debug("wp direct %s invalid json base=%s: %s", resource, site_base, exc)
            return []
        if not isinstance(rows, list):
            return []
        parsed: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title_obj = row.get("title") if isinstance(row.get("title"), dict) else {}
            title = str(title_obj.get("rendered") or title_obj.get("raw") or "").strip()
            title = re.sub(r"<[^>]+>", "", title)
            parsed.append(
                {
                    "id": int(row.get("id") or 0),
                    "title": title,
                    "link": str(row.get("link") or "").strip(),
                    "slug": str(row.get("slug") or "").strip(),
                }
            )
            if len(parsed) >= max_posts:
                break
        return parsed

    out: list[dict[str, Any]] = []
    for resource in resources:
        for row in _rows_from_resource(resource):
            out.append(row)
            if len(out) >= max_posts:
                return out
    return out


def _wp_fetch_rows(
    *,
    site_id: str | None,
    user_id: int,
    site_base: str,
    pub_creds: dict[str, str] | None,
    search: str = "",
    slug: str = "",
    max_posts: int = 20,
) -> list[dict[str, Any]]:
    from app.services.wp_site_connector import list_site_posts

    if slug:
        if site_id:
            try:
                result = list_site_posts(
                    site_id=site_id,
                    user_id=user_id,
                    search=slug,
                    per_page=min(20, max_posts),
                    max_total=max_posts,
                    status="publish",
                )
                return [p for p in (result.get("posts") or []) if isinstance(p, dict)]
            except Exception as exc:
                _LOG.debug("wp slug fetch via connector failed slug=%s: %s", slug, exc)
        if pub_creds:
            return _fetch_wp_posts_direct(
                site_base=pub_creds["url"],
                username=pub_creds["username"],
                app_password=pub_creds["app_password"],
                slug=slug,
                max_posts=max_posts,
            )
        return []
    if site_id:
        try:
            result = list_site_posts(
                site_id=site_id,
                user_id=user_id,
                search=search,
                fetch_all=False,
                per_page=min(20, max_posts),
                max_total=max_posts,
                status="publish",
            )
            return [p for p in (result.get("posts") or []) if isinstance(p, dict)]
        except Exception as exc:
            _LOG.debug("wp search via connector failed q=%r: %s", search[:40], exc)
            return []
    if pub_creds:
        return _fetch_wp_posts_direct(
            site_base=pub_creds["url"],
            username=pub_creds["username"],
            app_password=pub_creds["app_password"],
            search=search,
            max_posts=max_posts,
        )
    return []


def _wp_post_to_ref(post: dict[str, Any], *, site_base: str) -> ExistingArticleRef | None:
    title = str(post.get("title") or "").strip()
    url = str(post.get("link") or "").strip()
    slug = str(post.get("slug") or "").strip()
    post_id = int(post.get("id") or post.get("post_id") or 0)
    if not title and not url:
        return None
    kw = title or _slug_norm(slug)
    if not kw:
        return None
    return ExistingArticleRef(
        keyword=kw,
        title=title or kw,
        url=url,
        slug=slug or _url_path_slug(url),
        source="published",
        target_website=site_base,
        wp_post_id=post_id,
    )


def _lookup_wp_post_by_slug(
    *,
    user_id: int,
    target_website: str,
    slug: str,
    role: str = "user",
) -> tuple[int, str]:
    """Resolve WordPress post/page id + public URL from slug via REST API."""
    slug_hint = re.sub(r"[^a-z0-9\-]+", "", str(slug or "").strip().lower())
    if not slug_hint:
        return 0, ""
    tw = str(target_website or "").strip()
    if not tw:
        return 0, ""
    from app.services.site_ownership import user_owns_wp_site

    if not user_owns_wp_site(user_id, tw, role=role):
        return 0, ""

    site_id = _resolve_wp_site_id(user_id, tw, role=role)
    from app.services.wp_connect import normalize_wp_base_url

    try:
        site_base = normalize_wp_base_url(tw)
    except Exception:
        site_base = tw.rstrip("/")
    pub_creds = None if site_id else _resolve_publishing_wp_credentials(user_id, tw, role=role)
    if not site_id and not pub_creds:
        return 0, ""

    rows = _wp_fetch_rows(
        site_id=site_id,
        user_id=user_id,
        site_base=site_base,
        pub_creds=pub_creds,
        slug=slug_hint,
        max_posts=5,
    )
    if not rows and pub_creds:
        rows = _fetch_wp_posts_direct(
            site_base=pub_creds["url"],
            username=pub_creds["username"],
            app_password=pub_creds["app_password"],
            slug=slug_hint,
            max_posts=5,
        )
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_slug = re.sub(r"[^a-z0-9\-]+", "", str(row.get("slug") or "").strip().lower())
        post_id = int(row.get("id") or 0)
        if post_id <= 0:
            continue
        if row_slug and row_slug != slug_hint:
            continue
        return post_id, str(row.get("link") or "").strip()
    return 0, ""


def _resolve_wp_edit_links(
    *,
    user_id: int,
    role: str,
    target_website: str,
    ref: ExistingArticleRef,
) -> dict[str, Any]:
    """Build postId/publicUrl/editUrl when the user owns the target WordPress site."""
    tw = str(target_website or ref.target_website or "").strip()
    empty = {"postId": 0, "publicUrl": "", "editUrl": "", "can_edit": False}
    if not tw:
        return empty
    from app.services.site_ownership import user_owns_wp_site
    from app.services.wp_connect import normalize_wp_base_url

    if not user_owns_wp_site(user_id, tw, role=role):
        return empty
    try:
        site_base = normalize_wp_base_url(tw)
    except Exception:
        site_base = tw.rstrip("/")

    public_url = str(ref.url or "").strip()
    post_id = int(ref.wp_post_id or 0)
    if post_id <= 0:
        slug = str(ref.slug or _url_path_slug(ref.url) or "").strip()
        if slug:
            post_id, looked_up_url = _lookup_wp_post_by_slug(
                user_id=user_id,
                target_website=tw,
                slug=slug,
                role=role,
            )
            if looked_up_url:
                public_url = looked_up_url
    if post_id <= 0:
        return empty

    edit_url = f"{site_base.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
    return {
        "postId": post_id,
        "publicUrl": public_url,
        "editUrl": edit_url,
        "can_edit": True,
    }


def _collect_wp_rest_site_articles(
    *,
    user_id: int,
    target_website: str = "",
    search_keywords: list[str] | None = None,
    role: str = "user",
    max_posts: int = 40,
) -> list[ExistingArticleRef]:
    """Live WordPress REST posts — slug + service-group scoped (not whole site)."""
    tw = str(target_website or "").strip()
    if not tw:
        return []
    site_id = _resolve_wp_site_id(user_id, tw, role=role)
    from app.services.wp_connect import normalize_wp_base_url

    try:
        site_base = normalize_wp_base_url(tw)
    except Exception:
        site_base = tw.rstrip("/")

    pub_creds = None if site_id else _resolve_publishing_wp_credentials(user_id, tw, role=role)
    if not site_id and not pub_creds:
        return []

    out: list[ExistingArticleRef] = []
    seen: set[str] = set()
    keywords = [re.sub(r"\s+", " ", str(k or "").strip()) for k in (search_keywords or []) if str(k or "").strip()]

    def _ingest_rows(rows: list[dict[str, Any]], *, kw_for_filter: str) -> None:
        nonlocal out, seen
        kw_slug = keyword_to_slug_candidate(kw_for_filter)
        for post in rows:
            if not isinstance(post, dict):
                continue
            ref = _wp_post_to_ref(post, site_base=site_base)
            if not ref:
                continue
            ref_slug = str(ref.slug or _url_path_slug(ref.url) or "").strip().lower()
            slug_hit = bool(kw_slug and ref_slug and kw_slug == ref_slug)
            if not slug_hit and not _corpus_relevant_for_keyword(kw_for_filter, ref):
                continue
            key = _ref_dedupe_key(ref)
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)

    for kw in keywords[:8]:
        intent = parse_keyword_intent(kw)
        # 1) Slug lookup — direct keyword slug + intent candidates.
        for slug in all_slug_candidates_for_keyword(kw):
            rows = _wp_fetch_rows(
                site_id=site_id,
                user_id=user_id,
                site_base=site_base,
                pub_creds=pub_creds,
                slug=slug,
                max_posts=3,
            )
            _ingest_rows(rows, kw_for_filter=kw)
            if len(out) >= max_posts:
                return out

        if intent.intent_kind == "informational":
            # 2) REST search by full topic phrase (blog / guide posts).
            search_q = _fold(kw)[:200]
            if search_q:
                rows = _wp_fetch_rows(
                    site_id=site_id,
                    user_id=user_id,
                    site_base=site_base,
                    pub_creds=pub_creds,
                    search=search_q,
                    max_posts=20,
                )
                _ingest_rows(rows, kw_for_filter=kw)
                if len(out) >= max_posts:
                    return out
            continue

        # 2) Narrow REST search by service + district tokens (service pages).
        core = extract_service_core(kw)
        loc = ref_location_key_from_text(kw)
        loc_num = re.search(r"(\d{1,2})", loc or "")
        search_bits = [core]
        if loc_num:
            search_bits.append(f"quan {loc_num.group(1)}")
        narrow = " ".join(x for x in search_bits if x).strip()
        if narrow:
            rows = _wp_fetch_rows(
                site_id=site_id,
                user_id=user_id,
                site_base=site_base,
                pub_creds=pub_creds,
                search=narrow,
                max_posts=15,
            )
            _ingest_rows(rows, kw_for_filter=kw)
            if len(out) >= max_posts:
                return out
    return out


def _collect_sitemap_site_articles(
    *,
    user_id: int,
    target_website: str = "",
    search_keywords: list[str] | None = None,
    role: str = "user",
    max_urls: int = 40,
) -> list[ExistingArticleRef]:
    """Sitemap URLs scoped to service group + district (not whole site)."""
    tw = str(target_website or "").strip()
    if not tw:
        return []
    from app.services.site_ownership import user_owns_wp_site
    from app.services.url_safety import assert_public_http_url
    from app.services.wp_connect import normalize_wp_base_url

    if not user_owns_wp_site(user_id, tw, role=role):
        return []
    try:
        base = normalize_wp_base_url(tw)
        assert_public_http_url(base)
    except Exception as exc:
        _LOG.debug("sitemap corpus url blocked: %s", exc)
        return []

    keywords = [re.sub(r"\s+", " ", str(k or "").strip()) for k in (search_keywords or []) if str(k or "").strip()]
    if not keywords:
        return []

    try:
        sm_url = f"{base.rstrip('/')}/sitemap.xml"
        resp = requests.get(sm_url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (compatible; ContentAI/1.0)"})
        if resp.status_code != 200 or not resp.text:
            return []
        root = ET.fromstring(resp.text)
    except Exception as exc:
        _LOG.debug("sitemap corpus fetch failed %s: %s", tw, exc)
        return []

    out: list[ExistingArticleRef] = []
    seen: set[str] = set()
    locs: list[str] = []
    for el in root.iter():
        if str(el.tag or "").endswith("loc") and el.text:
            locs.append(el.text.strip())

    for kw in keywords[:8]:
        intent = parse_keyword_intent(kw)
        kw_slug = keyword_to_slug_candidate(kw)
        scored: list[tuple[int, str]] = []
        for u in locs:
            try:
                host = urlparse(u).netloc.lower()
                if host and host not in (urlparse(base).netloc or "").lower():
                    continue
            except Exception:
                continue
            path = urlparse(u).path or ""
            if not _path_matches_intent(path, intent):
                continue
            score = 2
            if kw_slug and kw_slug in path.lower():
                score += 10
            for slug in intent.slug_candidates:
                if slug in path.lower():
                    score += 5
            if intent.intent_kind == "informational" and intent.topic_group:
                if intent.topic_group.replace("_", "-") in path.lower():
                    score += 3
            scored.append((score, u))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _score, url in scored[:max_urls]:
            slug = _url_path_slug(url)
            title_guess = _slug_norm(slug) if slug else url
            ref = ExistingArticleRef(
                keyword=title_guess,
                title=title_guess,
                url=url,
                slug=slug,
                source="published",
                target_website=base,
            )
            if not _corpus_relevant_for_keyword(kw, ref):
                continue
            key = _ref_dedupe_key(ref)
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
    return out


def _collect_live_site_articles(
    *,
    user_id: int,
    target_website: str = "",
    search_keywords: list[str] | None = None,
    role: str = "user",
) -> list[ExistingArticleRef]:
    """WordPress REST + sitemap articles for duplicate checks."""
    rest = _collect_wp_rest_site_articles(
        user_id=user_id,
        target_website=target_website,
        search_keywords=search_keywords,
        role=role,
    )
    sitemap = _collect_sitemap_site_articles(
        user_id=user_id,
        target_website=target_website,
        search_keywords=search_keywords,
        role=role,
    )
    return _merge_corpus_refs(rest, sitemap)


def _collect_connected_site_articles(
    *,
    user_id: int,
    db: Any | None,
    target_website: str = "",
    role: str = "user",
) -> list[ExistingArticleRef]:
    """Published WP posts from IL corpus on sites the user owns."""
    if db is None:
        return []
    try:
        from app.services.internal_linking.models import InternalLinkArticle
    except Exception as exc:
        _LOG.debug("IL corpus imports failed: %s", exc)
        return []

    sites = _owned_site_bases(user_id, target_website=target_website, role=role)
    if not sites:
        return []

    out: list[ExistingArticleRef] = []
    seen_urls: set[str] = set()
    try:
        from sqlalchemy import select

        for site in sites[:20]:
            rows = db.execute(
                select(InternalLinkArticle.title, InternalLinkArticle.url)
                .where(
                    InternalLinkArticle.wp_site == site,
                    InternalLinkArticle.is_published.is_(True),
                )
                .order_by(InternalLinkArticle.id.desc())
                .limit(300)
            ).all()
            for art in rows:
                title = str(getattr(art, "title", None) or (art[0] if len(art) > 0 else "") or "").strip()
                url = str(getattr(art, "url", None) or (art[1] if len(art) > 1 else "") or "").strip()
                if not title or not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                # Use title as keyword proxy for published posts without Content AI keyword.
                out.append(
                    ExistingArticleRef(
                        keyword=title,
                        title=title,
                        url=url,
                        source="published",
                        target_website=site,
                    )
                )
    except Exception as exc:
        _LOG.debug("IL article corpus skipped: %s", exc)
        return []
    return out


def _corpus_cache_key(
    *,
    user_id: int,
    exclude_project_id: str | None,
    target_website: str,
    role: str,
    include_connected_sites: bool,
) -> str:
    return "|".join(
        (
            str(int(user_id)),
            str(role or "user"),
            str(exclude_project_id or "").strip(),
            str(target_website or "").strip().lower(),
            "1" if include_connected_sites else "0",
        )
    )


def invalidate_duplicate_corpus_cache(user_id: int | None = None) -> None:
    """Drop cached corpora (optional; TTL also expires entries)."""
    with _CORPUS_LOCK:
        if user_id is None:
            _CORPUS_CACHE.clear()
            return
        prefix = f"{int(user_id)}|"
        for k in [k for k in _CORPUS_CACHE if k.startswith(prefix)]:
            _CORPUS_CACHE.pop(k, None)


def _store_corpus_cache(key: str, items: list[ExistingArticleRef]) -> list[ExistingArticleRef]:
    frozen = tuple(items)
    now = time.monotonic()
    with _CORPUS_LOCK:
        if len(_CORPUS_CACHE) >= _CORPUS_CACHE_MAX and key not in _CORPUS_CACHE:
            # Drop oldest by expiry timestamp.
            oldest = min(_CORPUS_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _CORPUS_CACHE.pop(oldest, None)
        _CORPUS_CACHE[key] = (now + _CORPUS_TTL_SEC, frozen)
    return list(frozen)


def _load_corpus_cache(key: str) -> list[ExistingArticleRef] | None:
    now = time.monotonic()
    with _CORPUS_LOCK:
        hit = _CORPUS_CACHE.get(key)
        if not hit:
            return None
        expires, frozen = hit
        if expires < now:
            _CORPUS_CACHE.pop(key, None)
            return None
        return list(frozen)


def collect_existing_articles(
    *,
    user_id: int,
    db: Any | None = None,
    target_website: str = "",
    exclude_project_id: str | None = None,
    role: str = "user",
    include_connected_sites: bool = True,
    use_cache: bool = True,
) -> list[ExistingArticleRef]:
    """Corpus for duplicate checks — scoped to the current user only."""
    cache_key = _corpus_cache_key(
        user_id=user_id,
        exclude_project_id=exclude_project_id,
        target_website=target_website,
        role=role,
        include_connected_sites=include_connected_sites,
    )
    if use_cache:
        cached = _load_corpus_cache(cache_key)
        if cached is not None:
            return cached

    items = _collect_content_ai_articles(user_id=user_id, exclude_project_id=exclude_project_id)
    seen = {normalize_keyword(x.keyword) for x in items}

    for ref in _collect_publish_schedule_articles(
        user_id=user_id, db=db, exclude_project_id=exclude_project_id
    ):
        nk = normalize_keyword(ref.keyword)
        if nk and nk not in seen:
            seen.add(nk)
            items.append(ref)

    if include_connected_sites:
        for ref in _collect_connected_site_articles(
            user_id=user_id, db=db, target_website=target_website, role=role
        ):
            nk = normalize_keyword(ref.keyword)
            # Prefer exact keyword entries; still include published titles for intent matching.
            key = nk or _fold(ref.title)
            if key and key not in seen:
                seen.add(key)
                items.append(ref)

    if use_cache:
        return _store_corpus_cache(cache_key, items)
    return items


def _ref_dedupe_key(ref: ExistingArticleRef) -> str:
    pid = str(ref.project_id or "").strip()
    if pid:
        return f"pid:{pid}"
    url = str(ref.url or "").strip().lower().rstrip("/")
    if url:
        return f"url:{url}"
    return f"kw:{normalize_keyword(ref.keyword)}"


def find_duplicates_for_keyword(
    keyword: str,
    existing: list[ExistingArticleRef],
    *,
    embeddings: dict[str, np.ndarray] | None = None,
    exact_only: bool = False,
    limit: int = MAX_DUP_MATCHES,
) -> list[DuplicateMatch]:
    """Return up to ``limit`` duplicate matches (exact first, then same-intent by score)."""
    kw = re.sub(r"\s+", " ", str(keyword or "").strip())
    if not kw or not existing:
        return []
    nk = normalize_keyword(kw)
    if not nk:
        return []
    cap = max(1, min(int(limit or MAX_DUP_MATCHES), MAX_DUP_MATCHES))

    out: list[DuplicateMatch] = []
    seen: set[str] = set()

    # 1) Exact primary keyword / title / slug matches (no embedding).
    # When any exact hit exists, return ONLY exact cards (per product requirement).
    for ref in existing:
        if not _ref_exact_match(kw, ref):
            continue
        key = _ref_dedupe_key(ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            DuplicateMatch(
                match_type="exact",
                message=MSG_EXACT,
                existing=ref,
                score=1.0,
            )
        )
        if len(out) >= cap:
            return out
    if out:
        return out
    if exact_only:
        return out

    intent = parse_keyword_intent(kw)

    # 2) Structural same-intent — hard-filtered by entity + primaryProblem for info intent.
    for ref in existing:
        if not _corpus_relevant_for_keyword(kw, ref):
            continue
        key = _ref_dedupe_key(ref)
        if key in seen:
            continue
        if _ref_structural_intent_match(kw, ref, intent):
            seen.add(key)
            out.append(
                DuplicateMatch(
                    match_type="same_intent",
                    message=MSG_SAME_INTENT,
                    existing=ref,
                    score=0.92,
                )
            )
            if len(out) >= cap:
                return out

    purpose = classify_content_purpose(kw)
    loc = extract_location_key(kw)
    core = extract_service_core(kw)
    if not core:
        return out

    emb_map = embeddings or {}
    q_vec = emb_map.get(kw)
    core_vec = emb_map.get(core) if core else None

    intent_hits: list[DuplicateMatch] = []

    for ref in existing:
        key = _ref_dedupe_key(ref)
        if key in seen:
            continue
        if not _corpus_relevant_for_keyword(kw, ref):
            continue
        # Hard filter informational candidates before any embedding similarity.
        if intent.intent_kind == "informational" and not _hard_filter_info_candidate(intent, ref):
            continue
        other_kw = re.sub(r"\s+", " ", str(ref.keyword or ref.title or ref.slug or "").strip())
        if not other_kw:
            continue
        other_purpose = classify_content_purpose(other_kw)
        if intent.intent_kind == "informational":
            if not _purposes_compatible_info(purpose, other_purpose):
                continue
        elif purpose != other_purpose:
            continue
        other_loc = extract_location_key(other_kw) or ref_location_key(ref)
        if intent.intent_kind == "informational":
            if loc and other_loc and loc != other_loc:
                continue
        elif not locations_compatible(loc, other_loc):
            continue
        other_core = extract_service_core(other_kw) or extract_service_core(ref.title or ref.slug)
        if not other_core:
            continue

        entity_a = _keyword_entity_tokens(kw) or _service_entity_tokens(core)
        entity_b = _keyword_entity_tokens(other_kw) or _service_entity_tokens(other_core)
        if entity_a and entity_b and not (entity_a & entity_b):
            continue

        core_jac = _token_jaccard(core, other_core)
        # Require overlapping service cores — prevents "computer repair" vs "phone repair".
        if core_jac < 0.34:
            # Allow high embedding similarity on cores to catch paraphrases with low token overlap.
            o_core_vec = emb_map.get(other_core)
            core_sim = _cosine(core_vec, o_core_vec) if core_vec is not None and o_core_vec is not None else 0.0
            if core_sim < _CORE_SIM_THRESHOLD:
                continue
        else:
            o_core_vec = emb_map.get(other_core)
            core_sim = (
                _cosine(core_vec, o_core_vec) if core_vec is not None and o_core_vec is not None else core_jac
            )

        o_vec = emb_map.get(other_kw)
        kw_sim = _cosine(q_vec, o_vec) if q_vec is not None and o_vec is not None else 0.0

        strong_structure = core_jac >= 0.5 and loc and loc == other_loc and purpose == other_purpose
        threshold = _INTENT_SIM_THRESHOLD_STRONG_STRUCTURE if strong_structure else _INTENT_SIM_THRESHOLD

        # Structural-only path: same purpose + same location + strong core overlap.
        structural_hit = bool(strong_structure and core_jac >= 0.66)
        if intent.intent_kind == "informational":
            # Informational: never accept embedding-only without hard filter (already applied).
            # Still require meaningful similarity or structural problem match.
            if not structural_hit and kw_sim < threshold:
                continue
        elif not structural_hit and kw_sim < threshold:
            continue

        score = max(kw_sim, core_sim, core_jac)
        if structural_hit and score < 0.66:
            score = 0.66
        intent_hits.append(
            DuplicateMatch(
                match_type="same_intent",
                message=MSG_SAME_INTENT,
                existing=ref,
                score=score,
            )
        )

    intent_hits.sort(key=lambda m: float(m.score), reverse=True)
    for match in intent_hits:
        key = _ref_dedupe_key(match.existing)
        if key in seen:
            continue
        seen.add(key)
        out.append(match)
        if len(out) >= cap:
            break
    return out


def find_duplicate_for_keyword(
    keyword: str,
    existing: list[ExistingArticleRef],
    *,
    embeddings: dict[str, np.ndarray] | None = None,
    exact_only: bool = False,
) -> DuplicateMatch | None:
    """Return best duplicate match for one keyword against an in-memory corpus."""
    matches = find_duplicates_for_keyword(
        keyword,
        existing,
        embeddings=embeddings,
        exact_only=exact_only,
        limit=1,
    )
    return matches[0] if matches else None

def _intent_candidate_refs(
    keyword: str,
    existing: list[ExistingArticleRef],
) -> list[ExistingArticleRef]:
    """Prefilter corpus rows that could share search intent (before embedding)."""
    intent = parse_keyword_intent(keyword)
    if intent.intent_kind != "informational" and not intent.service_group:
        return []
    out: list[ExistingArticleRef] = []
    for ref in existing:
        if not _corpus_relevant_for_keyword(keyword, ref):
            continue
        if intent.intent_kind == "informational" and not _hard_filter_info_candidate(intent, ref):
            continue
        if _ref_structural_intent_match(keyword, ref, intent):
            out.append(ref)
            continue
        other_kw = re.sub(r"\s+", " ", str(ref.keyword or ref.title or ref.slug or "").strip())
        if not other_kw:
            continue
        if intent.intent_kind == "informational":
            if not _purposes_compatible_info(
                intent.purpose, classify_content_purpose(other_kw)
            ):
                continue
            out.append(ref)
            continue
        if classify_content_purpose(other_kw) != intent.purpose:
            continue
        if not locations_compatible(intent.location, ref_location_key(ref)):
            continue
        if not extract_service_core(other_kw) and not ref_service_group_key(ref):
            continue
        if ref_service_group_key(ref) and ref_service_group_key(ref) != intent.service_group:
            continue
        out.append(ref)
    return out


def _existing_to_dict(ref: ExistingArticleRef, *, wp_links: dict[str, Any] | None = None) -> dict[str, Any]:
    pid = str(ref.project_id or "").strip()
    links = wp_links or {}
    public_url = str(links.get("publicUrl") or ref.url or "").strip()
    out = {
        "title": ref.title,
        "url": public_url or ref.url,
        "primary_keyword": ref.keyword,
        "source": ref.source,
        "project_id": pid,
        # Content AI project id — frontend navigates with this (not title).
        "article_id": pid,
        "target_website": ref.target_website,
    }
    if links.get("can_edit"):
        out["postId"] = int(links.get("postId") or 0)
        out["publicUrl"] = public_url
        out["editUrl"] = str(links.get("editUrl") or "").strip()
    return out


def _match_to_card(match: DuplicateMatch, *, wp_links: dict[str, Any] | None = None) -> dict[str, Any]:
    links = wp_links or {}
    existing = _existing_to_dict(match.existing, wp_links=links)
    card = {
        "article_id": existing["article_id"],
        "title": existing["title"],
        "url": existing["url"],
        "match_type": match.match_type,
        "message": match.message,
        "primary_keyword": existing["primary_keyword"],
        "project_id": existing["project_id"],
        "source": existing["source"],
        "target_website": existing.get("target_website", ""),
        "score": round(float(match.score), 4),
    }
    if links.get("can_edit"):
        card["postId"] = int(links.get("postId") or 0)
        card["publicUrl"] = str(links.get("publicUrl") or card["url"] or "").strip()
        card["editUrl"] = str(links.get("editUrl") or "").strip()
        card["url"] = card["publicUrl"] or card["url"]
    return card


def _empty_dup_result(keyword: str = "") -> dict[str, Any]:
    return {
        "keyword": keyword,
        "is_duplicate": False,
        "match_type": None,
        "message": "",
        "existing": None,
        "matches": [],
    }


def _match_dup_result(
    kw: str,
    match: DuplicateMatch | list[DuplicateMatch],
    *,
    wp_link_resolver: Any | None = None,
) -> dict[str, Any]:
    matches = match if isinstance(match, list) else [match]
    matches = [m for m in matches if isinstance(m, DuplicateMatch)][:MAX_DUP_MATCHES]
    if not matches:
        return _empty_dup_result(kw)
    best = matches[0]

    def _links_for(ref: ExistingArticleRef) -> dict[str, Any]:
        if not wp_link_resolver:
            return {}
        try:
            return wp_link_resolver(ref) or {}
        except Exception as exc:
            _LOG.debug("wp edit link resolve failed: %s", exc)
            return {}

    best_links = _links_for(best.existing)
    return {
        "keyword": kw,
        "is_duplicate": True,
        "match_type": best.match_type,
        "message": best.message,
        "existing": _existing_to_dict(best.existing, wp_links=best_links),
        "matches": [_match_to_card(m, wp_links=_links_for(m.existing)) for m in matches],
        "score": round(float(best.score), 4),
    }


def build_duplicate_check_meta(
    *,
    user_id: int,
    target_website: str = "",
    role: str = "user",
    live_site_count: int = 0,
) -> dict[str, Any]:
    tw = str(target_website or "").strip()
    if not tw:
        return {
            "target_website": "",
            "site_owned": False,
            "site_connected": False,
            "wp_articles_scanned": int(live_site_count or 0),
            "message": "Chưa nhập Target website — chỉ kiểm tra bài trong hệ thống Content AI.",
        }
    from app.services.site_ownership import user_owns_wp_site

    owned = bool(user_owns_wp_site(user_id, tw, role=role))
    site_id = _resolve_wp_site_id(user_id, tw, role=role) if owned else None
    pub = _resolve_publishing_wp_credentials(user_id, tw, role=role) if owned and not site_id else None
    connected = bool(site_id or pub)
    msg = ""
    if not owned:
        msg = "Target website chưa thuộc tài khoản — chỉ kiểm tra bài trong hệ thống Content AI."
    elif not connected:
        msg = "Website chưa kết nối WordPress — chỉ kiểm tra bài đã lưu trong hệ thống."
    elif live_site_count <= 0:
        msg = "Đã kết nối website nhưng chưa lấy được bài từ WordPress/sitemap — thử bấm kiểm tra lại."
    return {
        "target_website": tw,
        "site_owned": owned,
        "site_connected": connected,
        "wp_articles_scanned": int(live_site_count or 0),
        "message": msg,
    }


def check_keywords_for_duplicates(
    keywords: list[str],
    *,
    user_id: int,
    db: Any | None = None,
    target_website: str = "",
    exclude_project_id: str | None = None,
    role: str = "user",
    include_connected_sites: bool = True,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """
    Check one or more keywords. Returns a result dict per input keyword (stable order).

    Fast path: exact normalized match on light corpus (Content AI + schedule) — no embedding.
    Same-intent: structural match first; embed only remaining prefiltered candidates.
    Connected-site titles load only when exact misses and intent still unresolved.
    """
    cleaned = [re.sub(r"\s+", " ", str(k or "").strip()) for k in keywords]
    if not any(cleaned):
        return [_empty_dup_result(k) for k in cleaned]

    tw = str(target_website or "").strip()

    def _wp_links(ref: ExistingArticleRef) -> dict[str, Any]:
        site = tw or str(ref.target_website or "").strip()
        if not site:
            return {}
        return _resolve_wp_edit_links(
            user_id=user_id,
            role=role,
            target_website=site,
            ref=ref,
        )

    wp_match_kwargs = {"wp_link_resolver": _wp_links}

    live_site: list[ExistingArticleRef] = []
    if include_connected_sites and str(target_website or "").strip():
        search_kws = list(dict.fromkeys(k for k in cleaned if k))
        live_site = _collect_live_site_articles(
            user_id=user_id,
            target_website=target_website,
            search_keywords=search_kws,
            role=role,
        )

    # Light corpus first (no IL) — enough for exact match on Content AI keywords.
    light = collect_existing_articles(
        user_id=user_id,
        db=db,
        target_website=target_website,
        exclude_project_id=exclude_project_id,
        role=role,
        include_connected_sites=False,
        use_cache=use_cache,
    )
    if live_site:
        light = _merge_corpus_refs(light, live_site)
    light = _filter_corpus_for_keywords(light, cleaned)

    results: list[dict[str, Any] | None] = [None] * len(cleaned)
    pending: list[int] = []

    for i, kw in enumerate(cleaned):
        if not kw:
            results[i] = _empty_dup_result("")
            continue
        matches = find_duplicates_for_keyword(kw, light, exact_only=True)
        if matches:
            # Exact hit: show only exact article(s) — do not mix with same_intent.
            results[i] = _match_dup_result(kw, matches, **wp_match_kwargs)
        else:
            pending.append(i)

    if not pending:
        return [r if r is not None else _empty_dup_result() for r in results]

    # Structural same-intent on light corpus (no IL / no embedding yet).
    need_more: list[int] = []
    for i in pending:
        kw = cleaned[i]
        matches = find_duplicates_for_keyword(kw, light, embeddings={})
        if matches:
            results[i] = _match_dup_result(kw, matches, **wp_match_kwargs)
        else:
            need_more.append(i)
    pending = need_more

    if not pending:
        return [r if r is not None else _empty_dup_result() for r in results]

    # Expand with connected-site titles only when light corpus still unresolved.
    existing = light
    if include_connected_sites:
        existing = collect_existing_articles(
            user_id=user_id,
            db=db,
            target_website=target_website,
            exclude_project_id=exclude_project_id,
            role=role,
            include_connected_sites=True,
            use_cache=True,
        )
        still: list[int] = []
        for i in pending:
            kw = cleaned[i]
            matches = find_duplicates_for_keyword(kw, existing, exact_only=True)
            if matches:
                # Exact hit only — do not pad with same_intent cards.
                results[i] = _match_dup_result(kw, matches, **wp_match_kwargs)
                continue
            matches = find_duplicates_for_keyword(kw, existing, embeddings={})
            if matches:
                results[i] = _match_dup_result(kw, matches, **wp_match_kwargs)
            else:
                still.append(i)
        pending = still

    if not pending:
        return [r if r is not None else _empty_dup_result() for r in results]

    # Embed only query keywords + prefiltered candidate keywords/cores.
    to_embed: list[str] = []
    candidate_by_idx: dict[int, list[ExistingArticleRef]] = {}
    need_embed = pending
    for i in need_embed:
        kw = cleaned[i]
        cands = _intent_candidate_refs(kw, existing)
        candidate_by_idx[i] = cands
        if not cands:
            results[i] = _empty_dup_result(kw)
            continue
        to_embed.append(kw)
        core = extract_service_core(kw)
        if core:
            to_embed.append(core)
        for ref in cands:
            if ref.keyword:
                to_embed.append(ref.keyword)
                oc = extract_service_core(ref.keyword)
                if oc:
                    to_embed.append(oc)

    emb: dict[str, np.ndarray] = {}
    if to_embed:
        try:
            emb = embed_keywords(to_embed, use_cache=True)
        except Exception as exc:
            _LOG.warning("embed_keywords failed for duplicate check: %s", exc)
            emb = {}

    for i in need_embed:
        if results[i] is not None:
            continue
        kw = cleaned[i]
        cands = candidate_by_idx.get(i) or []
        if not cands:
            results[i] = _empty_dup_result(kw)
            continue
        matches = find_duplicates_for_keyword(kw, cands, embeddings=emb)
        results[i] = _match_dup_result(kw, matches, **wp_match_kwargs) if matches else _empty_dup_result(kw)

    return [r if r is not None else _empty_dup_result() for r in results]


def filter_keywords_rejecting_duplicates(
    keywords: list[str],
    *,
    user_id: int,
    db: Any | None = None,
    target_website: str = "",
    role: str = "user",
) -> tuple[list[str], list[dict[str, Any]]]:
    """Keep only non-duplicate keywords; return (kept, rejected_results)."""
    results = check_keywords_for_duplicates(
        keywords,
        user_id=user_id,
        db=db,
        target_website=target_website,
        role=role,
    )
    kept: list[str] = []
    rejected: list[dict[str, Any]] = []
    for r in results:
        if r.get("is_duplicate"):
            rejected.append(r)
        elif r.get("keyword"):
            kept.append(str(r["keyword"]))
    return kept, rejected


def assert_keyword_not_duplicate(
    keyword: str,
    *,
    user_id: int,
    db: Any | None = None,
    target_website: str = "",
    exclude_project_id: str | None = None,
    role: str = "user",
) -> None:
    """Raise HTTPException 409 when keyword is an exact or same-intent duplicate."""
    from fastapi import HTTPException

    rows = check_keywords_for_duplicates(
        [keyword],
        user_id=user_id,
        db=db,
        target_website=target_website,
        exclude_project_id=exclude_project_id,
        role=role,
        include_connected_sites=True,
    )
    if not rows:
        return
    r = rows[0]
    if not r.get("is_duplicate"):
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "content_ai_duplicate",
            "match_type": r.get("match_type"),
            "message": r.get("message") or MSG_EXACT,
            "existing": r.get("existing"),
            "matches": r.get("matches") or [],
            "keyword": r.get("keyword"),
        },
    )
