"""Platform-aware publishing categories (label, cache, unsupported)."""

from __future__ import annotations

from pathlib import Path

from app.services import publishing_categories as cats


def test_platform_category_label_is_not_hardcoded_wordpress():
    assert cats.platform_category_label("wordpress") == "Danh mục WordPress"
    assert cats.platform_category_label("haravan") == "Danh mục Haravan"
    assert cats.platform_category_label("webcake") == "Danh mục Webcake"
    assert cats.platform_category_label("shopify") == "Danh mục Shopify"
    assert cats.platform_category_label("ghost") == "Danh mục Ghost"
    assert cats.platform_category_label("") == "Danh mục nền tảng"


def test_unknown_platform_is_unsupported_without_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONTENT_AI_CACHE_DIR", str(tmp_path))
    out = cats.load_site_categories(
        user_id=7,
        site={"id": "s1", "platform": "ghost", "url": "https://blog.example"},
        refresh=True,
    )
    assert out["ok"] is True
    assert out["unsupported"] is True
    assert out["items"] == []
    assert "error" not in out
    assert out["label"] == "Danh mục Ghost"


def test_sanitize_skips_empty_and_keeps_numeric_ids():
    items = cats.sanitize_category_items(
        [
            {"id": "12", "name": "Tin tức"},
            {"id": 0, "name": "bad"},
            {"id": "x1", "name": "Custom"},
            {"id": 3, "name": ""},
            {"id": 12, "name": "Dup skipped"},
            None,
        ]
    )
    assert items[0] == {"id": 12, "name": "Tin tức", "parent": 0}
    assert items[1] == {"id": "x1", "name": "Custom", "parent": 0}
    assert len(items) == 2


def test_cache_roundtrip_per_site_and_platform(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONTENT_AI_CACHE_DIR", str(tmp_path))
    cats.write_cached_site_categories(
        user_id=9,
        platform="haravan",
        site_id="abc",
        url="https://shop.myharavan.com",
        items=[{"id": 44, "name": "Blog chính", "parent": 0}],
        selected_id="44",
        message="Đã tải 1 danh mục.",
    )
    hit = cats.read_cached_site_categories(
        user_id=9,
        platform="haravan",
        site_id="abc",
        url="https://other.example",
    )
    assert hit and hit["items"][0]["name"] == "Blog chính"
    assert hit["selected_id"] == "44"
    other_pf = cats.read_cached_site_categories(
        user_id=9,
        platform="wordpress",
        site_id="abc",
        url="https://shop.myharavan.com",
    )
    assert other_pf is None
    other_user = cats.read_cached_site_categories(
        user_id=10,
        platform="haravan",
        site_id="abc",
    )
    assert other_user is None


def test_load_uses_cache_and_does_not_call_network(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONTENT_AI_CACHE_DIR", str(tmp_path))
    cats.write_cached_site_categories(
        user_id=3,
        platform="webcake",
        site_id="w1",
        url="https://mysite.webcake.io",
        items=[{"id": 8, "name": "Khuyến mãi"}],
        selected_id="8",
    )

    def boom(**kwargs):
        raise AssertionError("must not hit live API")

    monkeypatch.setattr(cats, "fetch_webcake_blog_categories", boom)
    out = cats.load_site_categories(
        user_id=3,
        site={
            "id": "w1",
            "platform": "webcake",
            "url": "https://mysite.webcake.io",
            "app_password": "secret-should-not-fetch",
        },
        refresh=False,
    )
    assert out["ok"] is True
    assert out["from_cache"] is True
    assert out["items"][0]["name"] == "Khuyến mãi"
    assert out["selected_id"] == "8"
    assert out["label"] == "Danh mục Webcake"


def test_selected_id_update_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONTENT_AI_CACHE_DIR", str(tmp_path))
    site = {
        "id": "h1",
        "platform": "haravan",
        "url": "https://a.myharavan.com",
        "app_password": "tok",
    }
    cats.write_cached_site_categories(
        user_id=1,
        platform="haravan",
        site_id="h1",
        url=site["url"],
        items=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        selected_id="1",
    )
    out = cats.save_selected_category(user_id=1, site=site, selected_id="2")
    assert out["selected_id"] == "2"
    assert [x["id"] for x in out["items"]] == [1, 2]
    again = cats.save_selected_category(user_id=1, site=site, selected_id="2")
    assert again["selected_id"] == "2"
    assert again["items"] == out["items"]


def test_wordpress_legacy_cache_is_imported(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CONTENT_AI_CACHE_DIR", str(tmp_path))
    from app.services import wp_categories as wp_cats

    wp_cats.write_cached_wordpress_categories(
        user_id=4,
        site_id="wp1",
        url="https://wp.example",
        items=[{"id": 9, "name": "SEO"}],
        message="legacy",
    )
    monkeypatch.setattr(
        cats,
        "load_wordpress_categories",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("no live wp")),
    )
    out = cats.load_site_categories(
        user_id=4,
        site={"id": "wp1", "platform": "wordpress", "url": "https://wp.example", "username": "u", "app_password": "p"},
        refresh=False,
    )
    assert out["ok"] is True
    assert out["items"][0]["name"] == "SEO"
    assert out["label"] == "Danh mục WordPress"
