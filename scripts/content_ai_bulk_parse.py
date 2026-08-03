"""Parse bulk Content AI input lines: keyword | title | description | outline."""

from __future__ import annotations

import re
from typing import Any


def _normalize_word_count(value: Any, *, default: int = 1000) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 200:
        return default
    return min(8000, n)


def normalize_bulk_outline(text: str) -> str:
    """Turn «H2: A; H2: B» or plain lines into markdown outline."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        return ""
    if re.search(r"^#{1,3}\s", s, flags=re.MULTILINE):
        return str(text or "").strip()
    chunks = re.split(r"[;\n]+", str(text or ""))
    lines: list[str] = []
    for chunk in chunks:
        p = chunk.strip()
        if not p:
            continue
        m = re.match(r"^H([1-3])\s*:\s*(.+)$", p, flags=re.IGNORECASE)
        if m:
            level = max(1, min(3, int(m.group(1))))
            title = m.group(2).strip()
            lines.append(f"{'#' * level} {title}")
        else:
            lines.append(f"## {p}")
    return "\n".join(lines)


def parse_bulk_input_line(line: str) -> dict[str, str] | None:
    raw = str(line or "").strip()
    if not raw:
        return None
    if raw.startswith('"') and raw.endswith('"') and len(raw) > 1:
        raw = raw[1:-1].strip()

    custom_title = ""
    custom_description = ""
    custom_outline = ""

    if "|" in raw:
        parts = [p.strip() for p in raw.split("|")]
        keyword = parts[0] if parts else ""
        if len(parts) > 1:
            custom_title = parts[1]
        if len(parts) > 2:
            custom_description = parts[2]
        if len(parts) > 3:
            custom_outline = " | ".join(parts[3:]).strip()
    elif "," in raw and not re.search(r"\bH[1-3]\s*:", raw, flags=re.IGNORECASE):
        keyword = raw.split(",", 1)[0].strip()
    else:
        keyword = raw

    keyword = re.sub(r"\s+", " ", keyword).strip()
    if not keyword:
        return None

    outline_norm = normalize_bulk_outline(custom_outline) if custom_outline else ""

    return {
        "keyword": keyword,
        "custom_title": custom_title.strip(),
        "custom_description": custom_description.strip(),
        "custom_outline": outline_norm,
    }


def parse_bulk_input_text(raw: str) -> list[dict[str, str]]:
    lines = str(raw or "").replace("\r", "\n").split("\n")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        row = parse_bulk_input_line(line)
        if not row:
            continue
        lk = row["keyword"].lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append(row)
    return out


def bulk_item_has_customs(item: dict[str, Any]) -> bool:
    return bool(
        str(item.get("custom_title") or "").strip()
        or str(item.get("custom_description") or "").strip()
        or str(item.get("custom_outline") or "").strip()
    )


def _coerce_secondary_keywords(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return [x.strip() for x in re.split(r"[,;\n\r]+", val) if x.strip()]
    return []


def _coerce_wp_category_id(val: Any) -> int:
    try:
        n = int(val or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def normalize_bulk_job_items(
    *,
    keywords: list[str] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge legacy keyword list + structured items; dedupe by keyword."""
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(row: dict[str, Any]) -> None:
        kw = str(row.get("keyword") or "").strip()
        if not kw:
            return
        lk = kw.lower()
        if lk in seen:
            return
        seen.add(lk)
        try:
            sv = int(row.get("search_volume") or 0)
        except (TypeError, ValueError):
            sv = 0
        merged.append(
            {
                "keyword": kw,
                "custom_title": str(row.get("custom_title") or "").strip(),
                "custom_description": str(row.get("custom_description") or "").strip(),
                "custom_outline": str(row.get("custom_outline") or "").strip(),
                "search_volume": max(0, sv),
                "content_type": str(row.get("content_type") or "").strip(),
                "competitor_url": str(row.get("competitor_url") or "").strip(),
                "target_word_count": _normalize_word_count(row.get("target_word_count")),
                "secondary_keywords": _coerce_secondary_keywords(row.get("secondary_keywords")),
                "wp_category_id": _coerce_wp_category_id(row.get("wp_category_id")),
            }
        )

    if items:
        for it in items:
            if not isinstance(it, dict):
                continue
            kw = str(it.get("keyword") or it.get("primary_keyword") or "").strip()
            if not kw:
                continue
            outline_raw = str(it.get("custom_outline") or "").strip()
            try:
                sv = int(it.get("search_volume") or 0)
            except (TypeError, ValueError):
                sv = 0
            _add(
                {
                    "keyword": kw,
                    "custom_title": str(it.get("custom_title") or "").strip(),
                    "custom_description": str(it.get("custom_description") or "").strip(),
                    "custom_outline": normalize_bulk_outline(outline_raw) if outline_raw else "",
                    "search_volume": max(0, sv),
                    "content_type": str(it.get("content_type") or "").strip(),
                    "competitor_url": str(it.get("competitor_url") or "").strip(),
                    "target_word_count": _normalize_word_count(it.get("target_word_count")),
                    "secondary_keywords": _coerce_secondary_keywords(it.get("secondary_keywords")),
                    "wp_category_id": _coerce_wp_category_id(it.get("wp_category_id")),
                }
            )

    for k in keywords or []:
        ks = str(k or "").strip()
        if not ks:
            continue
        if "|" in ks:
            row = parse_bulk_input_line(ks)
            if row:
                _add(row)
        else:
            _add(
                {
                    "keyword": ks,
                    "custom_title": "",
                    "custom_description": "",
                    "custom_outline": "",
                    "search_volume": 0,
                    "content_type": "",
                    "competitor_url": "",
                    "target_word_count": 1000,
                    "secondary_keywords": [],
                    "wp_category_id": 0,
                }
            )

    return merged
