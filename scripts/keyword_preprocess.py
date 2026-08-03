"""
Keyword preprocessing for clustering.

Goals:
- normalize case/spacing/punctuation
- remove stopwords (vi/en) for lexical signals
"""

from __future__ import annotations

import os
import re
import unicodedata

_WS = re.compile(r"\s+")
_NONWORD = re.compile(r"[^\w\sÀ-ỹ]", re.UNICODE)


def _strip_accents(s: str) -> str:
    # Keep accents by default; allow optional stripping via env (useful for Vietnamese).
    if os.getenv("KW_STRIP_ACCENTS", "0").lower() not in ("1", "true", "yes"):
        return s
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


_STOP_EN = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "to",
    "for",
    "of",
    "in",
    "on",
    "with",
    "near",
    "me",
    "best",
    "top",
    "review",
    "vs",
    "compare",
}

_STOP_VI = {
    "ở",
    "tai",
    "tại",
    "gan",
    "gần",
    "gia",
    "giá",
    "re",
    "rẻ",
    "uy",
    "tín",
    "uy tín",
    "chính hãng",
    "hcm",
    "tphcm",
    "tp",
    "hn",
    "ha noi",
    "hà nội",
    "quan",
    "quận",
    "huyen",
    "huyện",
    "phuong",
    "phường",
}

_SYN_VI = [
    # repair synonyms
    (re.compile(r"\bchua\b", re.I), "sua"),
    (re.compile(r"\bchữa\b", re.I), "sửa"),
    # price synonyms
    (re.compile(r"\bbang gia\b", re.I), "gia"),
    (re.compile(r"\bbảng giá\b", re.I), "giá"),
    (re.compile(r"\bbao gia\b", re.I), "gia"),
    (re.compile(r"\bbáo giá\b", re.I), "giá"),
    (re.compile(r"\bgia bao nhieu\b", re.I), "gia"),
    (re.compile(r"\bgiá bao nhiêu\b", re.I), "giá"),
    # buy/order synonyms
    (re.compile(r"\bdat hang\b", re.I), "mua"),
    (re.compile(r"\bđặt hàng\b", re.I), "mua"),
    (re.compile(r"\bdat mua\b", re.I), "mua"),
    (re.compile(r"\bđặt mua\b", re.I), "mua"),
]


def normalize_keyword(raw: str) -> str:
    s = (raw or "").strip().lower()
    s = _strip_accents(s)
    if os.getenv("KW_ENABLE_SYNONYMS", "1").lower() in ("1", "true", "yes"):
        for rx, rep in _SYN_VI:
            s = rx.sub(rep, s)
    # normalize common location shorthand (helps blocking + lexical overlap)
    s = re.sub(r"\bq(\d{1,2})\b", r"quan \1", s, flags=re.I)
    s = re.sub(r"\bquận\s+(\d{1,2})\b", r"quan \1", s, flags=re.I)
    s = _NONWORD.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def tokenize_keyword(norm: str) -> list[str]:
    parts = [p for p in (norm or "").split(" ") if p]
    return parts


def remove_stopwords(tokens: list[str]) -> list[str]:
    extra = (os.getenv("KW_STOPWORDS_EXTRA") or "").strip()
    extra_set = {w.strip().lower() for w in extra.split(",") if w.strip()} if extra else set()
    stop = _STOP_EN | _STOP_VI | extra_set
    out: list[str] = []
    for t in tokens or []:
        if t in stop:
            continue
        out.append(t)
    return out


def preprocess_keyword(raw: str) -> dict[str, object]:
    norm = normalize_keyword(raw)
    toks = tokenize_keyword(norm)
    toks2 = remove_stopwords(toks)
    return {"raw": raw, "norm": norm, "tokens": toks2}

