"""Seoauto floating chatbot — FAQ, Knowledge Base, page context, LLM."""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict, deque
from threading import Lock
from typing import Any

import requests

from app.services.ai_knowledge_docs import search_kb
from app.services.ai_knowledge_store import get_default_base, list_bases
from app.services.product_knowledge import (
    build_product_kb_context,
    is_pricing_query,
    resolve_pricing_reply,
)
from app.services.technical_knowledge import build_technical_kb_context
from app.services.llm_content_writer import (
    LlmConfig,
    _openai_chat_completion,
    load_llm_config_admin,
)

NO_DATA_MSG = (
    "Tôi chưa có dữ liệu chính xác về phần này, vui lòng liên hệ admin để được hỗ trợ."
)

_MAX_HISTORY = 40
_RATE_WINDOW_SEC = 60
_RATE_MAX_PER_WINDOW = 20

_history_lock = Lock()
_sessions: dict[str, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=_MAX_HISTORY))
_session_owners: dict[str, int | None] = {}
_rate_lock = Lock()
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

_FAQ: list[dict[str, str]] = [
    {
        "id": "pricing",
        "q": "Giá phần mềm bao nhiêu?",
        "a": (
            "Seoauto có **Basic, Pro, Agency, Unlimited** (6 tháng / 1 năm / 2 năm / Vĩnh viễn).\n"
            "Ví dụ **Pro 6 tháng: 2.490.000đ** (GSC, 100 bài AI/tháng).\n"
            "Xem **Upgrade plan** hoặc Cài đặt → **View pricing**."
        ),
    },
    {
        "id": "audit",
        "q": "Cách audit website?",
        "a": (
            "1. Đăng nhập tại trang chủ.\n"
            "2. Vào **Phân tích Technical** (/tool).\n"
            "3. Nhập URL → **Kiểm tra Technical**.\n"
            "4. Xem checklist, xuất CSV/Google Sheet.\n"
            "5. Theo dõi lịch sử trên **Dashboard** (/report)."
        ),
    },
    {
        "id": "seo_article",
        "q": "Cách tạo bài SEO?",
        "a": (
            "1. Mở **Content AI** (/content-ai).\n"
            "2. Nhập từ khóa chính, chọn website/Knowledge Base.\n"
            "3. Dùng gợi ý AI cho title, meta, outline, nội dung.\n"
            "4. Chỉnh sửa trong editor → xuất bản hoặc đăng WordPress."
        ),
    },
    {
        "id": "kb",
        "q": "Cách dùng Knowledge Base?",
        "a": (
            "1. **Cài đặt** → **AI Knowledge Base**.\n"
            "2. Tạo KB: tên thương hiệu, website, tone, sản phẩm/dịch vụ.\n"
            "3. Upload tài liệu (outline, FAQ, quy tắc nội dung).\n"
            "4. Gắn website mục tiêu trong Content AI để AI bám KB khi viết bài."
        ),
    },
    {
        "id": "api_error",
        "q": "API key bị lỗi thì làm sao?",
        "a": (
            "1. **Cài đặt** → **Khóa API** → **Kiểm tra** từng provider.\n"
            "2. Đảm bảo key còn hạn, đúng provider (OpenAI/Anthropic/OpenRouter).\n"
            "3. Không chia sẻ key; hệ thống không hiển thị key đầy đủ sau khi lưu.\n"
            "4. Nếu vẫn lỗi: tạo key mới trên dashboard nhà cung cấp và cập nhật lại."
        ),
    },
    {
        "id": "wordpress",
        "q": "Cách đăng bài lên WordPress?",
        "a": (
            "1. **Cài đặt** → **Xuất bản** → thêm site WordPress (URL + Application Password).\n"
            "2. Trong **Content AI**, hoàn thiện bài → chọn site → **Đăng bài**.\n"
            "3. Kiểm tra trạng thái đăng; lỗi thường do URL site, quyền user WP hoặc REST API."
        ),
    },
]

_PAGE_FOCUS: dict[str, str] = {
    "content_ai": (
        "Trang Content AI: ưu tiên hướng dẫn viết bài SEO, outline, meta, bulk content, "
        "thumbnail/hình ảnh, Knowledge Base, đăng WordPress."
    ),
    "technical": (
        "Trang Technical SEO: ưu tiên audit website, checklist technical, GSC, crawl, "
        "sitemap, robots, schema, tốc độ, HTTPS."
    ),
    "settings": (
        "Trang Cài đặt: ưu tiên khóa API, nhà cung cấp AI, Knowledge Base, "
        "bảng giá gói Seoauto (Upgrade plan / View pricing), trial, credit, tài khoản."
    ),
    "dashboard": "Trang Dashboard: ưu tiên đọc báo cáo audit, lọc checklist, xuất CSV.",
    "keywords": "Trang Từ khóa: ưu tiên nghiên cứu từ khóa, gom nhóm cluster.",
    "schema": "Trang Schema: ưu tiên JSON-LD, schema generator.",
    "default": (
        "Hỗ trợ chung Technical SEO + Content SEO trong Seoauto; "
        "có thể trả lời giá gói theo Knowledge Base Giá & Gói."
    ),
}


def sanitize_user_text(text: str, *, max_len: int = 4000) -> str:
    """Strip control chars / limit length (XSS handled when rendering in browser)."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = raw[:max_len]
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)


def detect_page_context(path: str) -> str:
    p = (path or "/").split("?")[0].rstrip("/") or "/"
    if p.startswith("/content-ai"):
        return "content_ai"
    if p.startswith("/tool") or p.startswith("/analyze"):
        return "technical"
    if p.startswith("/settings"):
        return "settings"
    if p.startswith("/report"):
        return "dashboard"
    if p.startswith("/keywords"):
        return "keywords"
    if p.startswith("/schema"):
        return "schema"
    return "default"


def _rate_key(*, user_id: int | None, client_ip: str) -> str:
    if user_id is not None:
        return f"u:{user_id}"
    return f"ip:{client_ip or 'anon'}"


def check_rate_limit(*, user_id: int | None, client_ip: str) -> bool:
    """Return True if allowed."""
    key = _rate_key(user_id=user_id, client_ip=client_ip)
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets[key]
        while bucket and bucket[0] < now - _RATE_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= _RATE_MAX_PER_WINDOW:
            return False
        bucket.append(now)
    return True


def get_or_create_session(session_id: str | None, *, user_id: int | None = None) -> str:
    sid = str(session_id or "").strip()
    if not sid or len(sid) > 64 or not re.match(r"^[a-zA-Z0-9_-]+$", sid):
        sid = uuid.uuid4().hex
    with _history_lock:
        if sid not in _session_owners:
            _session_owners[sid] = int(user_id) if user_id is not None else None
    return sid


def _session_owner(session_id: str) -> int | None:
    with _history_lock:
        return _session_owners.get(session_id)


def assert_session_access(session_id: str, user_id: int | None) -> None:
    """Chặn đọc lịch sử chat của user/session khác."""
    owner = _session_owner(session_id)
    if owner is None:
        return
    if user_id is None or int(owner) != int(user_id):
        raise PermissionError("Không có quyền xem lịch sử phiên chat này.")


def get_history(session_id: str, *, user_id: int | None = None) -> list[dict[str, str]]:
    assert_session_access(session_id, user_id)
    with _history_lock:
        return list(_sessions.get(session_id, []))


def append_history(session_id: str, role: str, content: str) -> None:
    with _history_lock:
        _sessions[session_id].append({"role": role, "content": content})


def match_faq(message: str) -> str | None:
    q = message.strip().lower()
    if not q:
        return None
    pricing_hit = resolve_pricing_reply(message)
    if pricing_hit:
        return pricing_hit
    for item in _FAQ:
        if q == item["q"].lower() or item["id"] in q:
            return item["a"]
    for item in _FAQ:
        keywords = item["q"].lower().split()
        if len(keywords) >= 2 and all(k in q for k in keywords[:3]):
            return item["a"]
    return None


def _kb_context_for_user(
    user_id: int | None, query: str, *, page_key: str = "default"
) -> str:
    parts: list[str] = []
    if page_key in ("technical", "dashboard", "default", "schema"):
        tech_blob = build_technical_kb_context(query, limit=6)
        if tech_blob:
            parts.append(tech_blob)
    if is_pricing_query(query) or page_key in ("settings", "default"):
        product_blob = build_product_kb_context(
            query, limit=6, force_summary=True
        )
        if product_blob:
            parts.append(product_blob)
    if user_id is None:
        return "\n\n".join(parts)
    bases = [b for b in list_bases(user_id=user_id) if b.get("enabled", True)]
    user_bases = [b for b in bases if str(b.get("scope") or "user") == "user"]
    if user_bases:
        default = get_default_base(user_id=user_id)
        kb = default if (default and str(default.get("scope") or "user") == "user") else user_bases[0]
        kb_id = str(kb.get("id") or "")
        if kb_id:
            hits = search_kb(kb_id, query, limit=6)
            if hits:
                lines = [f"Knowledge Base: {kb.get('name') or kb_id}"]
                for h in hits:
                    title = h.get("document_title") or "doc"
                    snip = str(h.get("snippet") or "")[:400]
                    lines.append(f"- [{title}] {snip}")
                parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _user_context_block(user: Any | None) -> str:
    if user is None:
        return "Người dùng: khách (chưa đăng nhập)."
    email = str(getattr(user, "email", "") or "")
    masked = email
    if "@" in email:
        local, dom = email.split("@", 1)
        masked = (local[:2] + "***@" + dom) if len(local) > 2 else "***@" + dom
    role = str(getattr(user, "role", "user") or "user")
    status = str(getattr(user, "status", "active") or "active")
    credits = getattr(user, "credit_balance", None)
    extra = f", credit={credits}" if credits is not None else ""
    return f"Người dùng đăng nhập: {masked}, role={role}, status={status}{extra}. Không tiết lộ dữ liệu user khác."


def _build_system_prompt(*, page_key: str, kb_blob: str, user_blob: str) -> str:
    focus = _PAGE_FOCUS.get(page_key, _PAGE_FOCUS["default"])
    faq_lines = "\n".join(f"- {x['q']}" for x in _FAQ)
    return f"""Bạn là trợ lý Seoauto — hỗ trợ Technical SEO và Content SEO.

QUY TẮC BẮT BUỘC:
- Trả lời tiếng Việt, ngắn gọn, thân thiện.
- Được phép nêu **giá gói Seoauto** theo KNOWLEDGE BASE «Giá & Gói» / bảng giá chính thức trong ngữ cảnh.
- KHÔNG bịa giá ngoài KB; không nêi số credit / trạng thái của user khác; API key/token không được hiển thị.
- Số credit của chính user đang chat (nếu có trong ngữ cảnh) có thể nhắc khi họ hỏi tài khoản.
- KHÔNG hiển thị hoặc đoán API key; nếu user hỏi key → hướng dẫn vào Cài đặt.
- Nếu KNOWLEDGE BASE có bảng giá / gói Seoauto → trả lời giá cụ thể, KHÔNG dùng câu «chưa có dữ liệu».
- Chỉ khi thật sự không có thông tin trong KB/FAQ → trả: «{NO_DATA_MSG}»
- Không khẳng định kết quả audit cụ thể nếu user chưa chạy quét trên /tool.

NGỮ CẢNH TRANG: {focus}

{user_blob}

FAQ hệ thống (có thể trích):
{faq_lines}

KNOWLEDGE BASE (nếu có, ưu tiên):
{kb_blob or "(không có đoạn KB khớp)"}
"""


def _scrub_secrets(text: str) -> str:
    out = str(text or "")
    out = re.sub(r"sk-[a-zA-Z0-9]{8,}", "[đã ẩn key]", out)
    out = re.sub(r"Bearer\s+[a-zA-Z0-9._-]{12,}", "Bearer [đã ẩn]", out, flags=re.I)
    return out


def _anthropic_chat(*, cfg: LlmConfig, system: str, turns: list[dict[str, str]], max_tokens: int = 800) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": cfg.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    messages: list[dict[str, str]] = []
    for t in turns:
        role = str(t.get("role") or "user").strip().lower()
        if role not in ("user", "assistant"):
            continue
        content = str(t.get("content") or "").strip()
        if content:
            messages.append({"role": role, "content": content})
    if not messages:
        messages = [{"role": "user", "content": "Xin chào"}]
    payload: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": max(256, min(2048, max_tokens)),
        "temperature": cfg.temperature,
        "system": system,
        "messages": messages,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=50)
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic HTTP {r.status_code}")
    data = r.json() if r.content else {}
    parts = [
        str(b.get("text") or "")
        for b in (data.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return "\n".join(parts).strip()


def process_message(
    *,
    message: str,
    history: list[dict[str, str]] | None = None,
    page_path: str = "/",
    user: Any | None = None,
    user_id: int | None = None,
    client_ip: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    safe_msg = sanitize_user_text(message)
    if not safe_msg:
        return {"reply": "Vui lòng nhập câu hỏi.", "session_id": get_or_create_session(session_id)}

    uid = user_id
    if uid is None and user is not None:
        uid = int(getattr(user, "id", 0) or 0) or None

    if not check_rate_limit(user_id=uid, client_ip=client_ip):
        return {
            "reply": "Bạn gửi tin quá nhanh. Vui lòng đợi một phút rồi thử lại.",
            "session_id": get_or_create_session(session_id),
        }

    sid = get_or_create_session(session_id, user_id=uid)
    page_key = detect_page_context(page_path)

    faq_hit = match_faq(safe_msg)
    pricing_reply = resolve_pricing_reply(safe_msg)
    kb_blob = _kb_context_for_user(uid, safe_msg, page_key=page_key)
    user_blob = _user_context_block(user)
    system = _build_system_prompt(page_key=page_key, kb_blob=kb_blob, user_blob=user_blob)

    hist = list(history or [])[-12:]
    for h in hist:
        if str(h.get("role")) in ("user", "assistant"):
            append_history(sid, str(h["role"]), str(h.get("content") or "")[:2000])

    append_history(sid, "user", safe_msg)

    if pricing_reply:
        reply = pricing_reply
    elif faq_hit and (not kb_blob or len(safe_msg) < 120):
        reply = faq_hit
    else:
        cfg = load_llm_config_admin()
        if not cfg:
            reply = pricing_reply or faq_hit or (
                "Xin chào! Tôi là trợ lý Seoauto.\n\n"
                + (faq_hit or "")
                + "\n\nChatbot dùng **khóa API admin** (OPENAI_API_KEY / ANTHROPIC_API_KEY trong env.local). "
                "Admin cần cấu hình env.local rồi khởi động lại server."
            ).strip()
        else:
            pricing_hint = (
                " (Câu hỏi về giá: dùng bảng giá trong KNOWLEDGE BASE, không trả NO_DATA.)"
                if is_pricing_query(safe_msg)
                else ""
            )
            ctx_user = (
                f"[Trang: {page_path}]\n"
                f"{safe_msg}\n\n"
                f"(Trả lời dựa FAQ/KB/ngữ cảnh.{pricing_hint})"
            )
            openai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
            for h in hist:
                role = str(h.get("role") or "").strip().lower()
                if role in ("user", "assistant"):
                    c = sanitize_user_text(str(h.get("content") or ""), max_len=2000)
                    if c:
                        openai_messages.append({"role": role, "content": c})
            openai_messages.append({"role": "user", "content": ctx_user})
            try:
                if cfg.provider == "openai":
                    reply = _openai_chat_completion(
                        cfg=cfg,
                        messages=openai_messages,
                        max_tokens=800,
                        timeout_sec=50,
                    )
                else:
                    turns = hist + [{"role": "user", "content": ctx_user}]
                    reply = _anthropic_chat(cfg=cfg, system=system, turns=turns)
            except Exception:
                reply = faq_hit or NO_DATA_MSG

    reply = _scrub_secrets(reply.strip() or NO_DATA_MSG)
    append_history(sid, "assistant", reply)
    return {"reply": reply, "session_id": sid, "page_context": page_key}


def list_quick_prompts() -> list[dict[str, str]]:
    items = [{"id": x["id"], "label": x["q"]} for x in _FAQ]
    pricing = [i for i in items if i.get("id") == "pricing"]
    rest = [i for i in items if i.get("id") != "pricing"]
    return pricing + rest
