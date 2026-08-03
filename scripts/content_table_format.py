"""
Chuẩn hóa bảng trong HTML bài viết: chuyển khối cột (| hoặc tab) thành <table>, thêm class zebra.
"""

from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

TABLE_CLASS = "digiseo-table"
WRAP_CLASS = "digiseo-table-wrap"
_MULTI_SPACE = re.compile(r"\s{2,}")


def _split_row_text(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if "|" in t:
        parts = [p.strip() for p in re.split(r"\s*\|\s*", t.strip("| ").strip()) if p.strip()]
        if len(parts) >= 2:
            return parts[:8]
    parts = [p.strip() for p in _MULTI_SPACE.split(t) if p.strip()]
    return parts[:8] if len(parts) >= 2 else []


def _rows_are_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    n = len(rows[0])
    if n < 2 or n > 8:
        return False
    return all(len(r) == n for r in rows[1:])


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.match(r"^:?-{2,}:?$", (c or "").strip()) for c in cells)


def _build_table_element(rows: list[list[str]], soup: BeautifulSoup) -> Tag:
    if _is_separator_row(rows[1]) if len(rows) > 1 else False:
        header = rows[0]
        body_rows = rows[2:]
    else:
        header = rows[0]
        body_rows = rows[1:]

    wrap = soup.new_tag("div", attrs={"class": WRAP_CLASS})
    table = soup.new_tag("table", attrs={"class": TABLE_CLASS})
    thead = soup.new_tag("thead")
    trh = soup.new_tag("tr")
    for cell in header:
        th = soup.new_tag("th")
        th.string = cell
        trh.append(th)
    thead.append(trh)
    table.append(thead)
    tbody = soup.new_tag("tbody")
    for row in body_rows:
        tr = soup.new_tag("tr")
        for cell in row:
            td = soup.new_tag("td")
            td.string = cell
            tr.append(td)
        tbody.append(tr)
    table.append(tbody)
    wrap.append(table)
    return wrap


def _enhance_existing_tables(soup: BeautifulSoup) -> None:
    for table in soup.find_all("table"):
        cls = table.get("class") or []
        if isinstance(cls, str):
            cls = cls.split()
        if "no-digiseo-table" in cls:
            continue
        if TABLE_CLASS not in cls:
            table["class"] = cls + [TABLE_CLASS]
        parent = table.parent
        if parent and getattr(parent, "name", None) == "div":
            pcls = parent.get("class") or []
            if isinstance(pcls, str):
                pcls = pcls.split()
            if WRAP_CLASS in pcls:
                continue
        wrap = soup.new_tag("div", attrs={"class": WRAP_CLASS})
        table.insert_before(wrap)
        wrap.append(table.extract())


def _convert_p_block_to_table(nodes: list[Tag], soup: BeautifulSoup) -> Tag | None:
    rows: list[list[str]] = []
    for node in nodes:
        row = _split_row_text(node.get_text(" ", strip=True))
        if not row:
            return None
        rows.append(row)
    if not _rows_are_table(rows):
        return None
    return _build_table_element(rows, soup)


def _convert_plain_text_block(text: str, soup: BeautifulSoup) -> Tag | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    rows = [_split_row_text(ln) for ln in lines]
    if not all(rows) or not _rows_are_table(rows):
        return None
    return _build_table_element(rows, soup)


def enhance_tables_in_html(content_html: str) -> str:
    """Thêm bảng HTML + class zebra cho mọi khối dạng cột trong bài."""
    raw = str(content_html or "").strip()
    if not raw:
        return raw
    try:
        soup = BeautifulSoup(raw[:800_000], "html.parser")
    except Exception:
        return raw

    # Khối <p> liên tiếp giống bảng 2+ cột
    for p in list(soup.find_all("p")):
        if p.find_parent("table"):
            continue
        block: list[Tag] = [p]
        sib = p.next_sibling
        while sib is not None:
            if isinstance(sib, NavigableString) and not str(sib).strip():
                sib = sib.next_sibling
                continue
            if not isinstance(sib, Tag) or sib.name != "p":
                break
            if sib.find_parent("table"):
                break
            row = _split_row_text(sib.get_text(" ", strip=True))
            if not row:
                break
            block.append(sib)
            sib = sib.next_sibling
        if len(block) < 2:
            continue
        table_el = _convert_p_block_to_table(block, soup)
        if not table_el:
            continue
        block[0].insert_before(table_el)
        for node in block:
            node.decompose()

    # Đoạn text thuần (không bọc thẻ) giữa các block
    for el in list(soup.find_all(["div", "section", "article", "body"])):
        if el.name == "body" and not soup.body:
            continue
        children = list(el.children)
        i = 0
        while i < len(children):
            ch = children[i]
            if not isinstance(ch, NavigableString):
                i += 1
                continue
            txt = str(ch).strip()
            if not txt or "\n" not in txt:
                i += 1
                continue
            table_el = _convert_plain_text_block(txt, soup)
            if table_el:
                ch.replace_with(table_el)
            i += 1

    _enhance_existing_tables(soup)
    out = str(soup).strip()
    return out or raw
