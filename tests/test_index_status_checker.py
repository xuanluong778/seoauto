"""Tests for index_status_checker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.index_status_checker import (
    INDEX_STATUS_INDEXED,
    INDEX_STATUS_NOT_FOUND,
    INDEX_STATUS_UNKNOWN,
    _interpret_gsc_indexed,
    _url_matches_gsc_property,
    check_url_index_status,
    check_url_response_details,
    format_http_status_label,
    format_indexability_label,
)


def test_url_matches_gsc_domain_property():
    assert _url_matches_gsc_property("https://example.com/page", "sc-domain:example.com")
    assert not _url_matches_gsc_property("https://other.com/", "sc-domain:example.com")


def test_url_matches_gsc_url_prefix_property():
    assert _url_matches_gsc_property("https://www.example.com/a", "https://www.example.com/")
    assert not _url_matches_gsc_property("https://other.com/", "https://www.example.com/")


def test_interpret_gsc_indexed_pass():
    assert _interpret_gsc_indexed({"index_verdict": "PASS", "coverage_state": "Submitted and indexed"}) is True


def test_interpret_gsc_not_indexed_fail():
    assert _interpret_gsc_indexed({"index_verdict": "FAIL", "coverage_state": "URL is not on Google"}) is False


@patch("app.services.index_status_checker._technical_check")
@patch("app.services.index_status_checker._check_serp_indexed")
@patch("app.services.index_status_checker.GscClient.for_user", return_value=None)
def test_check_serp_indexed(mock_gsc, mock_serp, mock_tech):
    mock_serp.return_value = (True, "dataforseo")
    row = check_url_index_status(MagicMock(), url="https://example.com/page", user_id=1)
    assert row["index_status"] == INDEX_STATUS_INDEXED
    assert row["source"] == "serp"
    assert "sinbyte" not in row["message"].lower()
    mock_tech.assert_not_called()


@patch("app.services.index_status_checker._technical_check")
@patch("app.services.index_status_checker._check_serp_indexed")
@patch("app.services.index_status_checker.GscClient.for_user", return_value=None)
def test_check_not_found_with_technical_reason(mock_gsc, mock_serp, mock_tech):
    mock_serp.return_value = (False, "cse")
    mock_tech.return_value = {
        "indexability": "blocked",
        "main_issue": "Meta noindex",
        "checks": {"meta_noindex": "fail"},
        "suggestion": "",
    }
    row = check_url_index_status(MagicMock(), url="https://example.com/hidden", user_id=1)
    assert row["index_status"] == INDEX_STATUS_NOT_FOUND
    assert "noindex" in row["message"].lower()


@patch("app.services.index_status_checker._technical_check")
@patch("app.services.index_status_checker._check_serp_indexed", return_value=(None, "disabled"))
@patch("app.services.index_status_checker.GscClient.for_user", return_value=None)
def test_check_unknown_on_technical_error(mock_gsc, mock_serp, mock_tech):
    mock_tech.return_value = {"indexability": "error", "main_issue": "HTTP error", "suggestion": ""}
    row = check_url_index_status(MagicMock(), url="https://example.com/down", user_id=1)
    assert row["index_status"] == INDEX_STATUS_UNKNOWN


def test_format_http_status_redirect():
    label = format_http_status_label({
        "status_code": 301,
        "redirected": True,
        "indexability": "indexable",
    })
    assert "301" in label
    assert "redirect" in label


def test_format_indexability_noindex():
    assert format_indexability_label({"checks": {"meta_noindex": "fail"}}) == "Noindex"


@patch("app.services.index_status_checker._technical_check")
def test_check_url_response_details(mock_tech):
    mock_tech.return_value = {
        "status_code": 200,
        "indexability": "indexable",
        "page_title": "Demo Title",
        "checks": {},
        "redirected": False,
        "suggestion": "",
        "main_issue": "",
    }
    row = check_url_response_details("https://example.com/page")
    assert row["http_status"] == "200"
    assert row["indexability"] == "Có thể index"
    assert row["page_title"] == "Demo Title"
