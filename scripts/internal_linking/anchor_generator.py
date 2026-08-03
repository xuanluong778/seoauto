from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.services.llm_content_writer import load_llm_config

log = logging.getLogger(__name__)


_BAD_GENERIC = {
    "xem thêm",
    "xem chi tiết",
    "tại đây",
    "click here",
    "bấm vào đây",
    "xem ngay",
    "đọc thêm",
}


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _tokenize(s: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9à-ỹÀ-Ỹ]{2,}", str(s or ""))


def _looks_spammy(anchor: str, *, primary_keyword: str = "") -> bool:
    a = _clean_ws(anchor).lower()
    if not a or len(a) < 4:
        return True
    if a in _BAD_GENERIC:
        return True
    if len(a) > 90:
        return True
    # Avoid exact match keyword anchors too frequently
    pk = _clean_ws(primary_keyword).lower()
    if pk and a == pk:
        return True
    # Too many repeated words
    toks = [t.lower() for t in _tokenize(a)]
    if toks:
        uniq = set(toks)
        if len(uniq) <= max(1, len(toks) // 3):
            return True
    return False


@dataclass(frozen=True)
class AnchorCandidate:
    text: str
    reason: str = ""


def generate_anchor_variations(
    *,
    context_sentence: str,
    target_title: str,
    primary_keyword: str = "",
    max_candidates: int = 6,
) -> list[AnchorCandidate]:
    """
    Generate natural anchor text variations with AI when available.
    Falls back to deterministic heuristics if LLM isn't configured.
    """
    ctx = _clean_ws(context_sentence)
    title = _clean_ws(target_title)
    pk = _clean_ws(primary_keyword)
    n = max(2, min(int(max_candidates), 10))

    # Heuristic fallback first (fast, deterministic)
    fallback: list[str] = []
    if title:
        # Prefer 2-6 word phrases from title
        words = _tokenize(title)
        for win in (6, 5, 4, 3, 2):
            for i in range(0, max(0, len(words) - win + 1)):
                cand = " ".join(words[i : i + win]).strip()
                if len(cand) < 8:
                    continue
                if cand not in fallback:
                    fallback.append(cand)
                if len(fallback) >= n:
                    break
            if len(fallback) >= n:
                break
    if pk and pk not in fallback:
        fallback.append(pk)
    fallback = [x for x in fallback if not _looks_spammy(x, primary_keyword=pk)]
    if len(fallback) >= n:
        return [AnchorCandidate(text=x, reason="heuristic") for x in fallback[:n]]

    cfg = None
    try:
        cfg = load_llm_config()
    except Exception:
        cfg = None

    if not cfg:
        return [AnchorCandidate(text=x, reason="heuristic") for x in fallback[:n]]

    # Use the existing LLM writer stack via HTTP; keep prompt small and strict.
    # We intentionally avoid embedding the whole article to reduce cost and hallucinations.
    try:
        import requests

        api_key = cfg.api_key
        provider = cfg.provider
        model = cfg.model
        temp = float(cfg.temperature)
        prompt = (
            "Bạn là chuyên gia SEO nội dung. Nhiệm vụ: tạo anchor text tự nhiên để đặt internal link.\n"
            "QUY TẮC BẮT BUỘC:\n"
            "- Trả về đúng 1 JSON array các string (không markdown, không giải thích).\n"
            "- 4–8 anchor, mỗi anchor 2–7 từ, tiếng Việt tự nhiên.\n"
            "- Không dùng anchor chung chung: 'tại đây', 'xem thêm', 'click here'.\n"
            "- Tránh exact-match spam: không lặp nguyên văn từ khóa chính nếu không cần.\n"
            "- Anchor phải khớp ngữ nghĩa với bài đích và ăn nhập câu ngữ cảnh.\n"
            "\n"
            f"NGỮ CẢNH (1 câu): {ctx}\n"
            f"TIÊU ĐỀ BÀI ĐÍCH: {title}\n"
            f"TỪ KHÓA CHÍNH: {pk}\n"
            "\nOUTPUT (JSON array):"
        )

        if provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload: dict[str, Any] = {
                "model": model,
                "temperature": temp,
                "messages": [
                    {"role": "system", "content": "Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
            }
            r = requests.post(url, headers=headers, json=payload, timeout=35)
            if r.status_code >= 400:
                raise RuntimeError(f"OpenAI HTTP {r.status_code}: {(r.text or '')[:250]}")
            data = r.json() if r.content else {}
            msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
            content = msg.get("content") or ""
        else:
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {
                "model": model,
                "max_tokens": 600,
                "temperature": temp,
                "system": "Return only valid JSON.",
                "messages": [{"role": "user", "content": prompt}],
            }
            r = requests.post(url, headers=headers, json=payload, timeout=35)
            if r.status_code >= 400:
                raise RuntimeError(f"Anthropic HTTP {r.status_code}: {(r.text or '')[:250]}")
            data = r.json() if r.content else {}
            blocks = data.get("content") or []
            parts = []
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(str(b.get("text") or ""))
            content = "\n".join(parts)

        raw = str(content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
        import json

        arr = json.loads(raw)
        if not isinstance(arr, list):
            raise ValueError("LLM did not return list")
        out: list[AnchorCandidate] = []
        seen: set[str] = set()
        for it in arr:
            a = _clean_ws(str(it or ""))
            if not a:
                continue
            key = a.lower()
            if key in seen:
                continue
            seen.add(key)
            if _looks_spammy(a, primary_keyword=pk):
                continue
            out.append(AnchorCandidate(text=a, reason="llm"))
            if len(out) >= n:
                break
        if out:
            return out
    except Exception as exc:
        log.warning("Anchor LLM generation failed; fallback used. err=%s", str(exc)[:200])

    # Merge remaining fallback
    merged: list[AnchorCandidate] = []
    for x in fallback:
        if len(merged) >= n:
            break
        merged.append(AnchorCandidate(text=x, reason="heuristic"))
    return merged[:n]

