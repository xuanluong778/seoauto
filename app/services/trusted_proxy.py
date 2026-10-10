"""Trusted reverse-proxy client IP resolution (Nginx / Cloudflare)."""

from __future__ import annotations

import os


def trusted_proxy_xff_enabled() -> bool:
    return os.getenv("TRUSTED_PROXY_XFF", "1").strip().lower() in ("1", "true", "yes", "on")


def trusted_proxy_peers() -> frozenset[str]:
    raw = (os.getenv("TRUSTED_PROXY_IPS") or "127.0.0.1,::1").strip()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def direct_peer_ip(request) -> str:
    if request.client:
        return str(request.client.host or "unknown").strip()
    return "unknown"


def is_trusted_proxy_peer(peer_ip: str) -> bool:
    return peer_ip in trusted_proxy_peers()


def resolve_client_ip(request) -> str:
    """Resolve client IP for rate limiting and audit.

    When TRUSTED_PROXY_XFF=1 (default):
    - Only trust X-Real-IP / X-Forwarded-For when the direct peer is a trusted proxy.
    - Prefer X-Real-IP (nginx: $remote_addr, not client-spoofable).
    - For X-Forwarded-For chains, use the rightmost hop (real client after nginx append).

    Direct Internet connections to Uvicorn cannot spoof XFF to bypass rate limits.
    """
    direct = direct_peer_ip(request)[:64]

    if not trusted_proxy_xff_enabled():
        fwd = (request.headers.get("x-forwarded-for") or "").strip()
        if fwd:
            return fwd.split(",")[0].strip()[:64]
        return direct

    if not is_trusted_proxy_peer(direct):
        return direct

    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip[:64]

    fwd = (request.headers.get("x-forwarded-for") or "").strip()
    if fwd:
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]

    return direct
