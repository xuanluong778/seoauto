"""Chatbot CSKH — per-user JSON store."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.services.user_data_paths import user_data_dir

MAX_BOTS = 20
MAX_SOURCES = 50
MAX_CHANNELS = 30
MAX_CONVERSATIONS = 500

CHANNEL_TYPES = frozenset({"website_widget", "facebook", "zalo", "telegram", "api"})
SOURCE_TYPES = frozenset({"faq", "url", "file", "manual"})
BOT_STATUSES = frozenset({"draft", "active", "paused"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path(user_id: int):
    return user_data_dir(user_id) / "chatbot_cskh.json"


def _default_payload() -> dict[str, Any]:
    return {
        "bots": [],
        "sources": [],
        "channels": [],
        "conversations": [],
        "settings": {
            "model": "gpt-4o-mini",
            "temperature": 0.4,
            "system_prompt": (
                "Trả lời ngắn gọn, lịch sự. Chỉ dùng dữ liệu đã cung cấp. "
                "Khuyến khích khách để lại SĐT khi hỏi giá hoặc cần tư vấn sâu."
            ),
            "greeting": "Xin chào! Tôi có thể hỗ trợ gì cho bạn?",
            "fallback_reply": (
                "Hiện tôi chưa có đủ thông tin chính xác về nội dung này. "
                "Anh/chị vui lòng để lại số điện thoại để nhân viên tư vấn chi tiết hơn."
            ),
        },
        "updated_at": _now(),
    }


def _read(user_id: int) -> dict[str, Any]:
    path = _store_path(user_id)
    if not path.exists():
        return _default_payload()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_payload()
    if not isinstance(raw, dict):
        return _default_payload()
    base = _default_payload()
    for key in base:
        if key in raw:
            base[key] = raw[key]
    return base


def _write(user_id: int, data: dict[str, Any]) -> None:
    data["updated_at"] = _now()
    path = _store_path(user_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def get_overview(user_id: int) -> dict[str, Any]:
    data = _read(user_id)
    bots = data.get("bots") or []
    active_bots = sum(1 for b in bots if str(b.get("status")) == "active")
    return {
        "bots_total": len(bots),
        "bots_active": active_bots,
        "sources_total": len(data.get("sources") or []),
        "channels_total": len(data.get("channels") or []),
        "conversations_total": len(data.get("conversations") or []),
        "conversations_today": sum(
            1
            for c in (data.get("conversations") or [])
            if str(c.get("created_at") or "").startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        ),
        "updated_at": data.get("updated_at"),
    }


def list_bots(user_id: int) -> list[dict[str, Any]]:
    items = list(_read(user_id).get("bots") or [])
    items.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return items


def create_bot(user_id: int, *, name: str, description: str = "") -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tên chatbot không được để trống.")
    data = _read(user_id)
    bots = list(data.get("bots") or [])
    if len(bots) >= MAX_BOTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Tối đa {MAX_BOTS} chatbot.")
    bot = {
        "id": _new_id("bot"),
        "name": name[:120],
        "description": str(description or "").strip()[:500],
        "status": "draft",
        "created_at": _now(),
        "updated_at": _now(),
    }
    bots.append(bot)
    data["bots"] = bots
    _write(user_id, data)
    return bot


def update_bot(user_id: int, bot_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = _read(user_id)
    bots = list(data.get("bots") or [])
    for i, bot in enumerate(bots):
        if str(bot.get("id")) != str(bot_id):
            continue
        if "name" in patch:
            name = str(patch.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tên chatbot không được để trống.")
            bot["name"] = name[:120]
        if "description" in patch:
            bot["description"] = str(patch.get("description") or "").strip()[:500]
        if "status" in patch:
            st = str(patch.get("status") or "").strip().lower()
            if st not in BOT_STATUSES:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Trạng thái không hợp lệ.")
            bot["status"] = st
        bot["updated_at"] = _now()
        bots[i] = bot
        data["bots"] = bots
        _write(user_id, data)
        return bot
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")


def delete_bot(user_id: int, bot_id: str) -> None:
    data = _read(user_id)
    bots = [b for b in (data.get("bots") or []) if str(b.get("id")) != str(bot_id)]
    if len(bots) == len(data.get("bots") or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy chatbot.")
    data["bots"] = bots
    _write(user_id, data)


def list_sources(user_id: int) -> list[dict[str, Any]]:
    return list(_read(user_id).get("sources") or [])


def create_source(user_id: int, *, title: str, source_type: str, content: str = "", url: str = "") -> dict[str, Any]:
    title = str(title or "").strip()
    st = str(source_type or "").strip().lower()
    if not title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tiêu đề nguồn không được để trống.")
    if st not in SOURCE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Loại nguồn không hợp lệ.")
    data = _read(user_id)
    sources = list(data.get("sources") or [])
    if len(sources) >= MAX_SOURCES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Tối đa {MAX_SOURCES} nguồn.")
    row = {
        "id": _new_id("src"),
        "title": title[:160],
        "type": st,
        "content": str(content or "").strip()[:20000],
        "url": str(url or "").strip()[:2000],
        "created_at": _now(),
    }
    sources.append(row)
    data["sources"] = sources
    _write(user_id, data)
    return row


def delete_source(user_id: int, source_id: str) -> None:
    data = _read(user_id)
    sources = [s for s in (data.get("sources") or []) if str(s.get("id")) != str(source_id)]
    if len(sources) == len(data.get("sources") or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nguồn.")
    data["sources"] = sources
    _write(user_id, data)


def list_channels(user_id: int) -> list[dict[str, Any]]:
    return list(_read(user_id).get("channels") or [])


def create_channel(user_id: int, *, name: str, channel_type: str, bot_id: str | None = None) -> dict[str, Any]:
    name = str(name or "").strip()
    ct = str(channel_type or "").strip().lower()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tên kênh không được để trống.")
    if ct not in CHANNEL_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Loại kênh không hợp lệ.")
    data = _read(user_id)
    channels = list(data.get("channels") or [])
    if len(channels) >= MAX_CHANNELS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Tối đa {MAX_CHANNELS} kênh.")
    row = {
        "id": _new_id("chn"),
        "name": name[:120],
        "type": ct,
        "bot_id": str(bot_id or "").strip() or None,
        "status": "pending",
        "created_at": _now(),
    }
    channels.append(row)
    data["channels"] = channels
    _write(user_id, data)
    return row


def delete_channel(user_id: int, channel_id: str) -> None:
    data = _read(user_id)
    channels = [c for c in (data.get("channels") or []) if str(c.get("id")) != str(channel_id)]
    if len(channels) == len(data.get("channels") or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy kênh.")
    data["channels"] = channels
    _write(user_id, data)


def list_conversations(user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    items = list(_read(user_id).get("conversations") or [])
    items.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return items[: max(1, min(limit, 200))]


def get_settings(user_id: int) -> dict[str, Any]:
    return dict(_read(user_id).get("settings") or _default_payload()["settings"])


def update_settings(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    data = _read(user_id)
    settings = dict(data.get("settings") or _default_payload()["settings"])
    for key in ("model", "system_prompt", "greeting", "fallback_reply"):
        if key in patch:
            settings[key] = str(patch.get(key) or "").strip()[:8000]
    if "temperature" in patch:
        try:
            t = float(patch.get("temperature"))
            settings["temperature"] = max(0.0, min(1.0, t))
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="temperature không hợp lệ.")
    data["settings"] = settings
    _write(user_id, data)
    return settings
