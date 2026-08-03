from __future__ import annotations

from unittest.mock import Mock, patch

import requests

from app.services.index_check_providers.google_site_search_provider import GoogleSiteSearchProvider
from app.services.index_check_providers.url_match import (
    normalize_index_url,
    urls_equivalent,
    urls_exact_index_match,
)


def _response(
    *,
    status_code: int = 200,
    text: str = "",
    url: str = "https://www.google.com/search?q=test",
):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.url = url
    return resp


def test_urls_equivalent_trailing_slash():
    a = "https://able2know.org/user/phucsangminhgas/"
    b = "https://able2know.org/user/phucsangminhgas"
    assert urls_equivalent(a, b)


def test_urls_equivalent_www_and_scheme():
    a = "http://www.files.fm/phucsangminhgas/info"
    b = "https://files.fm/phucsangminhgas/info/"
    assert urls_equivalent(a, b)


def test_urls_equivalent_encoded_path():
    a = "https://example.com/tiếng-việt"
    b = "https://example.com/ti%E1%BA%BFng-vi%E1%BB%87t"
    assert urls_equivalent(a, b)


def test_urls_not_equivalent_same_domain_different_path():
    target = "https://unsplash.com/@phucsangminhgas"
    candidate = "https://unsplash.com/@otheruser"
    assert not urls_equivalent(target, candidate)


def test_urls_not_equivalent_domain_only():
    target = "https://v.gd/XnBA5g"
    candidate = "https://v.gd/other"
    assert not urls_equivalent(target, candidate)


def test_urls_not_equivalent_leaked_query_echo():
    target = "https://unsplash.com/@phucsangminhgas"
    leaked = "https://unsplash.com/@phucsangminhgas&safe=off&sca_esv=abc"
    matched, match_type = urls_exact_index_match(target, leaked)
    assert matched is False
    assert match_type == "none"


def test_normalize_preserves_triple_slash_path():
    raw = "https://www.tm-town.com///translators/phucsangminhgas"
    assert "///translators/phucsangminhgas" in normalize_index_url(raw)


def test_shortlink_does_not_match_redirect_target():
    short = "https://v.gd/XnBA5g"
    redirect = "https://example.com/landing-page"
    assert not urls_equivalent(short, redirect)


def test_provider_index_match_exact_organic():
    session = Mock()
    session.get.return_value = _response(
        text=(
            '<html><body><div class="yuRUbf">'
            '<a href="https://example.com/page" data-ved="1"><h3>Example</h3></a>'
            "</div></body></html>"
        )
    )
    provider = GoogleSiteSearchProvider(session=session)

    row = provider.check_url("https://example.com/page")
    assert row["index_status"] == "INDEX"
    assert row["matched_url"] == "https://example.com/page"
    assert row["match_type"] == "exact"
    assert row.get("candidate_urls")


def test_provider_no_index_when_only_domain_related_result():
    session = Mock()
    session.get.return_value = _response(
        text=(
            '<html><body><div class="g">'
            '<a href="https://unsplash.com/" data-ved="1"><h3>phucsangminhgas photos</h3></a>'
            '<cite>unsplash.com</cite></div></body></html>'
        )
    )
    provider = GoogleSiteSearchProvider(session=session)
    row = provider.check_url("https://unsplash.com/@phucsangminhgas")
    assert row["index_status"] == "NO_INDEX"
    assert row["match_type"] == "none"


def test_provider_no_index_when_username_only_in_title():
    session = Mock()
    session.get.return_value = _response(
        text=(
            '<html><body><div class="yuRUbf">'
            '<a href="https://unsplash.com/explore" data-ved="1">'
            "<h3>phucsangminhgas on Unsplash</h3></a></div></body></html>"
        )
    )
    provider = GoogleSiteSearchProvider(session=session)
    row = provider.check_url("https://unsplash.com/@phucsangminhgas")
    assert row["index_status"] == "NO_INDEX"


def test_provider_no_index_false_positive_urls_without_organic():
    session = Mock()
    leaked_html = (
        "<html><body><script>enablejs</script>"
        "https://unsplash.com/@phucsangminhgas&safe=off&sca_esv=abc"
        "</body></html>"
    )
    session.get.return_value = _response(text=leaked_html)
    provider = GoogleSiteSearchProvider(session=session)

    for url in [
        "https://www.tm-town.com///translators/phucsangminhgas",
        "https://unsplash.com/@phucsangminhgas",
        "https://v.gd/XnBA5g",
    ]:
        row = provider.check_url(url, query_url=url)
        assert row["index_status"] != "INDEX", url


def test_provider_no_index_only_when_explicit():
    session = Mock()
    session.get.return_value = _response(
        text="<html><body>Your search did not match any documents</body></html>"
    )
    provider = GoogleSiteSearchProvider(session=session)

    row = provider.check_url("https://example.com/missing")
    assert row["index_status"] == "NO_INDEX"


def test_provider_parse_failure_unknown_not_no_index():
    session = Mock()
    session.get.return_value = _response(
        text="<html><body>" + ("x" * 4000) + '<div class="g"></div></body></html>'
    )
    provider = GoogleSiteSearchProvider(session=session)

    row = provider.check_url("https://example.com/page")
    assert row["index_status"] == "UNKNOWN"
    assert row["index_status"] != "NO_INDEX"


def test_provider_captcha_not_noindex():
    session = Mock()
    session.get.return_value = _response(status_code=429, text="unusual traffic detected")
    provider = GoogleSiteSearchProvider(session=session)

    row = provider.check_url("https://example.com/page")
    assert row["index_status"] == "CAPTCHA_REQUIRED"


def test_provider_timeout_pending_retry():
    session = Mock()
    session.get.side_effect = requests.Timeout()
    provider = GoogleSiteSearchProvider(session=session)

    row = provider.check_url("https://example.com/page")
    assert row["index_status"] == "PENDING_RETRY"


@patch("app.services.dataforseo_client.google_serp_live_advanced")
@patch("app.services.dataforseo_client.get_basic_auth")
@patch("app.services.dataforseo_client.is_dataforseo_enabled")
def test_provider_dataforseo_empty_result_is_no_index(mock_enabled, mock_auth, mock_live):
    mock_enabled.return_value = True
    mock_auth.return_value = ("u", "p")
    mock_live.return_value = {
        "keyword": "site:https://unsplash.com/@phucsangminhgas",
        "items": [],
        "mock": True,
        "fallback_mock": True,
        "error": "empty_result",
    }
    provider = GoogleSiteSearchProvider(session=Mock())
    row = provider.check_url("https://unsplash.com/@phucsangminhgas")
    assert row["index_status"] == "NO_INDEX"
    assert row["match_type"] == "none"


@patch("app.services.serp_fetcher.fetch_serp_for_keyword")
def test_provider_uses_serp_when_enabled(mock_fetch):
    mock_fetch.return_value = {
        "source": "google_cse",
        "serp_urls": ["https://files.fm/phucsangminhgas/info"],
        "titles": ["Files.fm profile"],
    }
    with patch.dict("os.environ", {"SERP_FETCH_ENABLED": "1"}, clear=False):
        provider = GoogleSiteSearchProvider(session=Mock())
        row = provider.check_url("https://files.fm/phucsangminhgas/info")
    assert row["index_status"] == "INDEX"
    assert row["match_type"] == "exact"
    mock_fetch.assert_called_once()


@patch("app.services.serp_fetcher.fetch_serp_for_keyword")
def test_provider_serp_no_index_when_candidates_do_not_match(mock_fetch):
    mock_fetch.return_value = {
        "source": "google_cse",
        "serp_urls": ["https://unsplash.com/explore", "https://unsplash.com/"],
        "titles": ["Explore", "Home"],
    }
    with patch.dict("os.environ", {"SERP_FETCH_ENABLED": "1"}, clear=False):
        provider = GoogleSiteSearchProvider(session=Mock())
        row = provider.check_url("https://unsplash.com/@phucsangminhgas")
    assert row["index_status"] == "NO_INDEX"
    assert row["match_type"] == "none"
    assert len(row.get("candidate_urls") or []) == 2
