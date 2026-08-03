"""
Entity hierarchy: category → subcategory / brand → product → attributes.

Integrates with ``topic_entity_resolver`` canonical surfaces (not raw keyword spam).
"""

from __future__ import annotations

import re
from typing import Any

from app.services.topic_entity_resolver import normalize_entity_phrase, resolve_entity_groups

_ATTR_PAT = re.compile(r"\b(for|with|without|vs|under|over)\s+([a-z0-9\s]{3,60})", re.I)
_BRANDS = frozenset(
    """
    nike adidas puma reebok asics new balance brooks saucony hoka on running
    apple samsung google microsoft amazon dell hp lenovo sony lg
    """.split()
)


def classify_entity_type(phrase: str) -> str:
    """Heuristic entity class for hierarchy edges."""
    p = (phrase or "").strip().lower()
    toks = set(re.findall(r"[a-z0-9]{3,}", p))
    if _ATTR_PAT.search(p) or any(p.startswith(x + " ") for x in ("for ", "with ", "without ")):
        return "attribute"
    if toks & _BRANDS:
        if len(toks) >= 3:
            return "product"
        return "brand"
    if len(p.split()) <= 2 and len(p) < 22:
        return "category"
    if len(toks) >= 4:
        return "product"
    return "category"


def build_entity_hierarchy(
    *,
    topic_label: str,
    raw_entity_phrases: list[str],
    cluster_keywords: list[str],
) -> dict[str, Any]:
    """
    Returns nested map keyed by canonical category-like root, with ``type``, ``children``, ``attributes``.

    Uses ``resolve_entity_groups`` then assigns parent/child by type + substring containment
    (conservative — avoids over-asserting taxonomy).
    """
    groups = resolve_entity_groups(raw_entity_phrases, cluster_keywords=cluster_keywords, use_embeddings=False)
    root_label = normalize_entity_phrase(topic_label) or (topic_label or "topic").strip().lower()
    if len(root_label) < 2:
        root_label = "topic"

    hierarchy: dict[str, Any] = {}
    root_entry: dict[str, Any] = {
        "type": "category",
        "children": [],
        "attributes": [],
    }
    hierarchy[root_label] = root_entry

    seen_child: set[str] = set()
    for g in groups[:40]:
        canon = str(g.get("canonical_entity") or "").strip().lower()
        if not canon or canon == root_label:
            continue
        et = classify_entity_type(canon)
        if et == "attribute":
            attr = canon
            if attr not in root_entry["attributes"]:
                root_entry["attributes"].append(attr)
        elif et in ("brand", "product"):
            if root_label in canon or any(k in canon for k in root_label.split() if len(k) > 3):
                if canon not in seen_child:
                    seen_child.add(canon)
                    root_entry["children"].append(canon)
                    hierarchy[canon] = {
                        "type": et,
                        "children": [],
                        "attributes": [],
                    }
        else:
            if canon not in seen_child and len(canon) < 36:
                seen_child.add(canon)
                root_entry["children"].append(canon)
                hierarchy[canon] = {"type": "subcategory", "children": [], "attributes": []}

    return {
        "hierarchy": hierarchy,
        "root": root_label,
        "entity_groups": groups[:32],
        "explain": "Resolver → type heuristic → parent/child when phrase overlaps cluster root.",
    }
