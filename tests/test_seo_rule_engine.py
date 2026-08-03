from app.services.seo_rule_engine import (
    compute_decision_score,
    dedupe_and_prioritize_issues,
    run_seo_decision_layer,
)


def test_run_decision_indexability_blocked() -> None:
    parsed = {"status": 200, "title": "T", "meta_description": "d", "h1_count": 1, "word_count": 400, "h2": ["a"]}
    cr = {
        "indexability": {"indexable": False, "indexability_reason": "noindex", "indexability_confidence": 0.95},
        "seo_signals": {"indexable": False, "js_dependency": False, "render_difference": False},
        "canonical_resolution": {"canonical_url": None, "final_effective_url": "https://ex.com/", "canonical_mismatch": False},
        "raw_vs_rendered": {"identical": True, "missing_elements_in_raw": []},
        "js_seo_risk_level": "low",
        "js_seo_risk_score": 0.0,
        "cloaking_risk": False,
    }
    out = run_seo_decision_layer("https://ex.com/", parsed, "article", cr)
    ids = {i["rule_id"] for i in out["issues"]}
    assert "indexability_blocked" in ids
    assert out["summary"]["score"] < 100
    assert "resolved_signals" in out
    assert "final_indexability" in out["resolved_signals"]


def test_indexability_blocked_low_on_policy_noindex() -> None:
    parsed = {
        "status": 200,
        "title": "Privacy",
        "meta_description": "d",
        "h1_count": 1,
        "word_count": 400,
        "h2": ["a"],
        "robots_meta": "noindex, nofollow",
    }
    cr = {
        "indexability": {"indexable": False, "indexability_reason": "noindex", "indexability_confidence": 0.95},
        "seo_signals": {"js_dependency": False, "render_difference": False},
        "canonical_resolution": {
            "canonical_url": None,
            "final_effective_url": "https://ex.com/chinh-sach-bao-mat",
            "canonical_mismatch": False,
        },
        "raw_vs_rendered": {"identical": True, "missing_elements_in_raw": []},
        "js_seo_risk_level": "low",
        "js_seo_risk_score": 0.0,
        "cloaking_risk": False,
        "response_headers": {},
        "raw_response_headers": {},
    }
    out = run_seo_decision_layer("https://ex.com/chinh-sach-bao-mat-thong-tin", parsed, "unknown", cr)
    issue = next((i for i in out["issues"] if i["rule_id"] == "meta_robots_noindex"), None)
    assert issue is not None
    assert issue["severity"] == "low"


def test_missing_h1_suppressed_when_js_dependency() -> None:
    parsed = {"status": 200, "title": "T", "meta_description": "d", "h1_count": 0, "word_count": 400, "h2": ["a"]}
    cr = {
        "indexability": {"indexable": True, "indexability_reason": "", "indexability_confidence": 0.9},
        "seo_signals": {"js_dependency": True, "render_difference": True},
        "canonical_resolution": {"canonical_url": None, "final_effective_url": "https://ex.com/p", "canonical_mismatch": False},
        "raw_vs_rendered": {"identical": False, "missing_elements_in_raw": ["H1"]},
        "raw_html": "<html><head></head><body><div>shell</div></body></html>",
        "js_seo_risk_level": "medium",
        "js_seo_risk_score": 0.6,
        "cloaking_risk": False,
    }
    out = run_seo_decision_layer("https://ex.com/p", parsed, "article", cr)
    ids = {i["rule_id"] for i in out["issues"]}
    assert "missing_h1" not in ids


def test_soft_404_heuristic_detected() -> None:
    parsed = {
        "status": 200,
        "title": "Page not available",
        "meta_description": "",
        "h1_count": 0,
        "word_count": 40,
        "h2": [],
        "visible_text": "Not found. The page is not available.",
    }
    cr = {
        "indexability": {"indexable": True, "indexability_reason": "", "indexability_confidence": 0.9},
        "seo_signals": {"js_dependency": False, "render_difference": False},
        "canonical_resolution": {"canonical_url": None, "final_effective_url": "https://ex.com/missing", "canonical_mismatch": False},
        "raw_vs_rendered": {"identical": True, "missing_elements_in_raw": []},
        "raw_html": "<html><body>Not found</body></html>",
        "js_seo_risk_level": "low",
        "js_seo_risk_score": 0.0,
        "cloaking_risk": False,
    }
    out = run_seo_decision_layer("https://ex.com/missing", parsed, "unknown", cr)
    issue = next((i for i in out["issues"] if i["rule_id"] == "soft_404_heuristic"), None)
    assert issue is not None
    assert issue["severity"] == "high"


def test_scoring_weights_legacy() -> None:
    issues = [
        {"rule_id": "a", "severity": "high", "confidence": 1.0},
        {"rule_id": "b", "severity": "medium", "confidence": 1.0},
        {"rule_id": "c", "severity": "low", "confidence": 1.0},
    ]
    assert compute_decision_score(issues) == 100 - 15 - 8 - 3


def test_dedupe_same_rule_id_keeps_stronger() -> None:
    a = {"rule_id": "x", "severity": "low", "confidence": 0.5, "issue": "1"}
    b = {"rule_id": "x", "severity": "high", "confidence": 0.5, "issue": "2"}
    r = dedupe_and_prioritize_issues([a, b])
    assert len(r) == 1
    assert r[0]["severity"] == "high"
