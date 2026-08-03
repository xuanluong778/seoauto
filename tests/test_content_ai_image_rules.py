"""Tests for Content AI image insertion rules."""

from __future__ import annotations

from app.services.content_ai_image_rules import (
    image_credit_slots,
    inline_image_count_for_word_count,
    parse_image_source_choice,
    resolve_image_orientation,
)


def test_inline_image_count_tiers():
    assert inline_image_count_for_word_count(900) == 1
    assert inline_image_count_for_word_count(1000) == 2
    assert inline_image_count_for_word_count(1499) == 2
    assert inline_image_count_for_word_count(1500) == 3
    assert inline_image_count_for_word_count(1999) == 3
    assert inline_image_count_for_word_count(2000) == 4


def test_parse_image_source_choice():
    assert parse_image_source_choice("lấy ảnh từ google") == "google"
    assert parse_image_source_choice("tạo ảnh bằng ai") == "ai"
    assert parse_image_source_choice("không chèn ảnh") == "none"


def test_resolve_orientation_portrait():
    assert resolve_image_orientation(keyword="áo cưới hồng") == "portrait"


def test_resolve_orientation_landscape():
    assert resolve_image_orientation(keyword="sửa máy tính tại nhà") == "landscape"


def test_image_credit_slots():
    assert image_credit_slots(1500) == 4
