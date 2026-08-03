"""Tests for Content AI image optimizer."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.content_ai_image_optimizer import MAX_OUTPUT_BYTES, optimize_image_bytes


def _make_test_jpeg(w: int, h: int, color=(120, 80, 40)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_optimize_no_upscale():
    data = _make_test_jpeg(400, 300)
    out, fmt, w, h, ow, oh = optimize_image_bytes(data, stem="test", orientation="any")
    assert fmt in ("JPEG", "WEBP")
    assert w <= ow
    assert h <= oh
    assert len(out) <= MAX_OUTPUT_BYTES


def test_optimize_resize_smaller_than_original():
    data = _make_test_jpeg(1600, 1200)
    out, fmt, w, h, ow, oh = optimize_image_bytes(data, stem="big", orientation="landscape")
    assert ow == 1600 and oh == 1200
    if (w, h) != (ow, oh):
        assert w <= ow - 2
        assert h <= oh - 2
    assert len(out) <= MAX_OUTPUT_BYTES


def test_optimize_rejects_invalid():
    with pytest.raises(ValueError):
        optimize_image_bytes(b"not-an-image", stem="x")
