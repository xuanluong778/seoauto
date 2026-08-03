"""
Tri thức Technical SEO dùng chung (global) — Sơ đồ tri thức cho mọi website.

Nguồn: Knowledge Base ``digiseo-technical-global-001`` + file ``data/checklist-technical-seo-so-do-tri-thuc.txt``.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.ai_knowledge_docs import search_kb
from app.services.ai_knowledge_store import get_base, list_bases

GLOBAL_TECHNICAL_KB_ID = (
    os.getenv("TECHNICAL_GLOBAL_KB_ID") or "digiseo-technical-global-001"
).strip()

_CHECKLIST_PATH = (
    Path(os.getenv("TECHNICAL_CHECKLIST_PATH") or "data/checklist-technical-seo-so-do-tri-thuc.txt")
)


def get_global_technical_kb_id() -> str:
    return GLOBAL_TECHNICAL_KB_ID


def resolve_global_technical_kb(*, user_id: int | None = None) -> dict[str, Any] | None:
    """KB global readable by any logged-in user."""
    kid = GLOBAL_TECHNICAL_KB_ID
    if user_id is not None:
        row = get_base(kid, user_id=user_id)
        if row:
            return row
    for raw in _read_bases_raw():
        if str(raw.get("id")) == kid and str(raw.get("scope") or "") == "global":
            return raw
    return None


def _read_bases_raw() -> list[dict[str, Any]]:
    from app.services.ai_knowledge_store import _read_all

    return _read_all()


def _checklist_path() -> Path | None:
    if _CHECKLIST_PATH.is_file():
        return _CHECKLIST_PATH
    root = Path(__file__).resolve().parents[2] / "checklist-technical-seo-so-do-tri-thuc.txt"
    return root if root.is_file() else None


def _checklist_mtime() -> float:
    p = _checklist_path()
    if not p:
        return 0.0
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


@lru_cache(maxsize=4)
def _issue_guidance_from_file(_mtime: float) -> dict[str, dict[str, str]]:
    path = _checklist_path()
    if not path:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_issue_blocks(text)


def _append_field(block: dict[str, str], key: str, line: str) -> None:
    prev = (block.get(key) or "").strip()
    block[key] = f"{prev}\n{line}".strip() if prev else line.strip()


def _parse_issue_blocks(text: str) -> dict[str, dict[str, str]]:
    """Parse ``- issue_code:`` blocks from checklist file."""
    out: dict[str, dict[str, str]] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^-\s*issue_code:\s*(\S+)\s*$", lines[i], re.I)
        if not m:
            i += 1
            continue
        code = m.group(1).strip().lower()
        block: dict[str, str] = {"issue_code": code}
        active_key = ""
        i += 1
        while i < len(lines):
            if re.match(r"^-\s*issue_code:\s*", lines[i], re.I):
                break
            if re.match(r"^\d+\.\d+\.\s+", lines[i]) or re.match(r"^=+$", lines[i].strip()):
                break
            fm = re.match(r"^-\s*([a-z_]+):\s*(.*)$", lines[i], re.I)
            if fm:
                active_key = fm.group(1).strip().lower()
                val = fm.group(2).strip()
                if val:
                    block[active_key] = val
                else:
                    block.setdefault(active_key, "")
                i += 1
                continue
            stripped = lines[i].strip()
            if active_key and stripped and not lines[i].startswith("- "):
                _append_field(block, active_key, lines[i].rstrip())
                i += 1
                continue
            if not stripped:
                i += 1
                continue
            break
        if code:
            out[code] = block
    return out


def lookup_issue_guidance(issue_type: str) -> dict[str, str] | None:
    code = str(issue_type or "").strip().lower()
    if not code:
        return None
    return _issue_guidance_from_file(_checklist_mtime()).get(code)


def enrich_issue_from_technical_knowledge(issue: dict[str, Any]) -> dict[str, Any]:
    """Gắn remediation / giải thích từ sơ đồ tri thức global nếu có."""
    out = dict(issue)
    t = str(out.get("type") or "").strip().lower()
    if not t:
        return out
    guide = lookup_issue_guidance(t)
    if not guide:
        return out

    parts: list[str] = []
    desc = (guide.get("description") or "").strip()
    why = (guide.get("why_it_matters") or "").strip()
    fix = (guide.get("how_to_fix") or "").strip()
    check = (guide.get("how_to_check") or "").strip()
    owner = (guide.get("owner_role") or "").strip()
    sev = (guide.get("severity") or "").strip()

    if desc:
        parts.append(desc)
    if why:
        parts.append(f"Vì sao quan trọng: {why}")
    if fix:
        parts.append(f"Cách xử lý:\n{fix}")
    if check:
        parts.append(f"Kiểm tra lại: {check}")
    if owner:
        parts.append(f"Người xử lý: {owner}")

    kb_text = "\n\n".join(parts).strip()
    if not kb_text:
        return out

    existing = (out.get("remediation") or "").strip()
    if not existing or existing in (
        "Xem hướng dẫn trong checklist Technical SEO global.",
    ):
        out["remediation"] = kb_text
    elif kb_text not in existing:
        out["remediation"] = f"{existing}\n\n---\nTri thức Technical (global):\n{kb_text}"

    if sev and not out.get("severity"):
        out["severity"] = sev
    if guide.get("priority_score") and not out.get("priority_score"):
        try:
            out["priority_score"] = int(guide["priority_score"])
        except (TypeError, ValueError):
            pass

    out["suggested_fix"] = (out.get("remediation") or out.get("suggested_fix") or "").strip()
    out["knowledge_source"] = "technical_global"
    return out


def search_technical_knowledge(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    kid = GLOBAL_TECHNICAL_KB_ID
    if not kid:
        return []
    return search_kb(kid, query, limit=limit)


def build_technical_kb_context(query: str, *, limit: int = 6) -> str:
    hits = search_technical_knowledge(query, limit=limit)
    if not hits:
        return ""
    lines = ["Seoauto — Sơ đồ tri thức (dùng chung mọi website):"]
    for h in hits:
        title = h.get("document_title") or "doc"
        snip = str(h.get("snippet") or "")[:500]
        lines.append(f"- [{title}] {snip}")
    return "\n".join(lines)


def list_global_technical_bases_for_user(user_id: int) -> list[dict[str, Any]]:
    return [b for b in list_bases(user_id=user_id) if str(b.get("scope") or "") == "global" and b.get("enabled", True)]
