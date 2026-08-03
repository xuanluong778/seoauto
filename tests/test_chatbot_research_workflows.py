from __future__ import annotations

from app.services.chatbot_research_report import (
    build_chatbot_research_report,
    normalize_keyword_rows,
)
from app.services.chatbot_tab_registry import (
    CHATBOT_TABS,
    INTENT_KEYWORD_RESEARCH,
    INTENT_KEYWORD_RESEARCH_CLUSTER,
    TAB_RESEARCH,
    estimate_workflow_credits,
    init_progress_for_intent,
    tab_for_intent,
    validate_prepare_params,
)


def test_research_tab_has_two_workflows() -> None:
    tab = next(t for t in CHATBOT_TABS if t["id"] == TAB_RESEARCH)
    assert len(tab["workflows"]) == 2
    ids = {w["id"] for w in tab["workflows"]}
    assert INTENT_KEYWORD_RESEARCH in ids
    assert INTENT_KEYWORD_RESEARCH_CLUSTER in ids


def test_validate_keyword_research_params_no_clustering() -> None:
    out = validate_prepare_params(
        INTENT_KEYWORD_RESEARCH,
        {"seed_keyword": "crm software", "max_keywords": 200, "country": "VN", "language": "vi"},
    )
    assert out["seed_keyword"] == "crm software"
    assert out["include_clustering"] is False
    assert out["max_keywords"] == 200


def test_validate_keyword_research_cluster_params() -> None:
    out = validate_prepare_params(INTENT_KEYWORD_RESEARCH_CLUSTER, {"seed_keyword": "seo"})
    assert out["include_clustering"] is True
    assert out["max_keywords"] == 100


def test_estimate_research_credits_split() -> None:
    only = estimate_workflow_credits(INTENT_KEYWORD_RESEARCH, {})
    both = estimate_workflow_credits(INTENT_KEYWORD_RESEARCH_CLUSTER, {})
    assert only["clustering"] == 0
    assert both["clustering"] > 0
    assert both["total"] > only["total"]


def test_progress_steps_for_cluster_workflow() -> None:
    steps = init_progress_for_intent(INTENT_KEYWORD_RESEARCH_CLUSTER)
    ids = [s["id"] for s in steps]
    assert ids == ["research", "clustering", "planning", "complete"]


def test_tab_for_intent_research_cluster() -> None:
    assert tab_for_intent(INTENT_KEYWORD_RESEARCH_CLUSTER) == TAB_RESEARCH


def test_normalize_keyword_rows_table() -> None:
    rows = normalize_keyword_rows(
        [
            {
                "keyword": "dịch vụ seo",
                "search_volume": {"avg_monthly": 1200},
                "intent": "commercial",
                "kd": 0.42,
                "competition": "medium",
                "trend": {"direction": "up"},
                "cpc_avg": 15000,
            }
        ]
    )
    assert rows[0]["keyword"] == "dịch vụ seo"
    assert rows[0]["volume"] == 1200
    assert rows[0]["difficulty"] == "42"


def test_build_research_report_clusters_mode() -> None:
    report = build_chatbot_research_report(
        mode="clusters",
        seed_keyword="crm",
        keywords=[{"keyword": "crm", "search_volume": {"avg_monthly": 100}}],
        clusters=[
            {
                "cluster_id": "c1",
                "cluster_name": "CRM",
                "primary_keyword": "crm",
                "variations": ["crm", "phần mềm crm"],
                "intent": "commercial",
                "total_volume": 500,
                "difficulty": 0.5,
                "content_plan": {
                    "recommended_title": "CRM guide",
                    "outline": "## H2",
                    "intent": "commercial",
                },
            }
        ],
    )
    assert report["mode"] == "clusters"
    assert len(report["clusters"]) == 1
    assert report["clusters"][0]["suggested_title"] == "CRM guide"
