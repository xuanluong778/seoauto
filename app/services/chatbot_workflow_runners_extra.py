"""Chatbot workflow runners — SEO Score, Technical, Keyword Research."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.services.chatbot_tab_registry import (
    INTENT_CONTENT_SEO_SCORE,
    INTENT_KEYWORD_RESEARCH,
    INTENT_KEYWORD_RESEARCH_CLUSTER,
    INTENT_TECHNICAL_DEEP_AUDIT,
    INTENT_TECHNICAL_QUICK_AUDIT,
    INTENT_TECHNICAL_SINGLE_URL,
    INTENT_URL_SEO_SCOREBOARD,
)

_LOG = logging.getLogger(__name__)
StepStatus = str


@dataclass
class SimpleWorkflowStep:
    id: str
    label: str
    status: StepStatus = "pending"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimpleWorkflowResult:
    intent: str
    status: str = "pending"
    steps: list[SimpleWorkflowStep] = field(default_factory=list)
    stats: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    actions: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "stats": self.stats,
            "result": self.result,
            "actions": self.actions,
            "error": self.error,
        }


def _init_steps(defs: tuple[tuple[str, str], ...]) -> list[SimpleWorkflowStep]:
    return [SimpleWorkflowStep(id=sid, label=label) for sid, label in defs]


def _set_step(steps: list[SimpleWorkflowStep], step_id: str, *, status: StepStatus, message: str = "") -> None:
    for s in steps:
        if s.id == step_id:
            s.status = status
            if message:
                s.message = message
            return


def _fail(result: SimpleWorkflowResult, steps: list[SimpleWorkflowStep], step_id: str, msg: str) -> SimpleWorkflowResult:
    _set_step(steps, step_id, status="failed", message=msg)
    result.status = "failed"
    result.error = msg
    result.steps = steps
    return result


def _enrich_clusters_with_plans(
    clusters: list[dict[str, Any]],
    keywords: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from app.services.cluster_content_map import build_content_plan

    kw_by_lower = {str(r.get("keyword") or "").strip().lower(): r for r in keywords if str(r.get("keyword") or "").strip()}
    enriched: list[dict[str, Any]] = []
    for i, c in enumerate(clusters):
        cluster = dict(c)
        primary = str(cluster.get("primary_keyword") or cluster.get("main_keyword") or "").strip()
        variations = [str(v).strip() for v in (cluster.get("variations") or cluster.get("supporting_keywords") or []) if str(v).strip()]
        if primary and primary.lower() not in {v.lower() for v in variations}:
            variations = [primary, *variations]
        if not primary and variations:
            primary = variations[0]
        keyword_items: list[dict[str, Any]] = []
        for kw in variations:
            row = dict(kw_by_lower.get(kw.lower(), {"keyword": kw}))
            row["keyword"] = kw
            keyword_items.append(row)
        intent = str(cluster.get("intent") or "informational")
        ctype = str(cluster.get("suggested_content_type") or "informational_article")
        plan = build_content_plan(
            cluster_id=str(cluster.get("cluster_id") or f"cluster_{i + 1}"),
            topic=str(cluster.get("cluster_name") or primary),
            main_kw=primary,
            keyword_items=keyword_items,
            cluster_intent=intent,
            suggested_content_type=ctype,
            content_angle="",
            total_volume=int(cluster.get("total_volume") or 0),
            confidence_score=float(cluster.get("score") or cluster.get("seo_priority_score") or 0.0),
        )
        cluster["content_plan"] = plan
        cluster["recommended_title"] = plan.get("recommended_title")
        cluster["suggested_outline"] = plan.get("outline")
        enriched.append(cluster)
    return enriched


def run_keyword_research_workflow(
    *,
    user_id: int,
    seed_keyword: str,
    language: str = "vi",
    country: str = "VN",
    max_keywords: int = 100,
    include_clustering: bool = False,
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    from app.services.chatbot_research_report import build_chatbot_research_report
    from app.services.keyword_research_pipeline import build_keyword_research_api_response

    step_defs = (
        ("research", "Research từ khóa"),
        ("complete", "Hoàn thành"),
    )
    steps = _init_steps(step_defs)
    result = SimpleWorkflowResult(intent=INTENT_KEYWORD_RESEARCH, status="running", steps=steps)
    seed = str(seed_keyword or "").strip()
    cap = max(20, min(500, int(max_keywords or 100)))

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            for s in steps:
                if s.id == step_id:
                    on_step(s)
                    break

    try:
        _emit("research", "running", "Đang mở rộng từ khóa…")
        loc_country = str(country or "VN").strip().upper()
        loc_lang = str(language or "vi").strip().lower()
        payload = build_keyword_research_api_response(
            seed_keyword=seed,
            language=loc_lang,
            country=loc_country,
            cluster_mode="tfidf",
            cluster_fetch_serp=False,
            cluster_max_keywords=min(cap, 80),
        )
        meta_err = (payload.get("meta") or {}).get("error")
        if meta_err:
            return _fail(result, steps, "research", str(meta_err))

        keywords = list(payload.get("keywords") or [])[:cap]
        if not keywords:
            return _fail(result, steps, "research", "Không tìm thấy từ khóa liên quan.")

        _emit("research", "done", f"Đã tìm {len(keywords)} từ khóa.")
        report = build_chatbot_research_report(
            mode="keywords",
            seed_keyword=seed,
            keywords=keywords,
            clusters=[],
            max_keywords=cap,
        )
        _emit("complete", "done", "Hoàn tất research từ khóa.")
        result.status = "completed"
        result.stats = {
            "seed_keyword": seed,
            "keywords_count": len(keywords),
            "clusters_count": 0,
        }
        result.result = {
            "seed_keyword": seed,
            "research_report": report,
            "keywords": keywords[:cap],
            "total_keywords": len(keywords),
        }
        result.actions = [
            {
                "type": "open_url",
                "label": "Mở Keyword Research",
                "url": f"/keywords/tools/research?seed={seed}",
            },
        ]
        result.steps = steps
        return result
    except Exception as exc:
        _LOG.exception("keyword research workflow failed")
        running = next((s.id for s in steps if s.status == "running"), "research")
        return _fail(result, steps, running, f"Lỗi research: {exc}")


def run_keyword_research_cluster_workflow(
    *,
    user_id: int,
    seed_keyword: str,
    language: str = "vi",
    country: str = "VN",
    max_keywords: int = 100,
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    from app.services.chatbot_research_report import build_chatbot_research_report
    from app.services.keyword_research_pipeline import build_keyword_research_api_response

    steps = _init_steps(
        (
            ("research", "Research từ khóa"),
            ("clustering", "Gom nhóm từ khóa"),
            ("planning", "Gợi ý title & outline"),
            ("complete", "Hoàn thành"),
        )
    )
    result = SimpleWorkflowResult(intent=INTENT_KEYWORD_RESEARCH_CLUSTER, status="running", steps=steps)
    seed = str(seed_keyword or "").strip()
    cap = max(20, min(500, int(max_keywords or 100)))

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            for s in steps:
                if s.id == step_id:
                    on_step(s)
                    break

    try:
        _emit("research", "running", "Đang mở rộng từ khóa…")
        loc_country = str(country or "VN").strip().upper()
        loc_lang = str(language or "vi").strip().lower()
        payload = build_keyword_research_api_response(
            seed_keyword=seed,
            language=loc_lang,
            country=loc_country,
            cluster_mode="hybrid",
            cluster_fetch_serp=True,
            cluster_max_keywords=min(cap, 80),
        )
        meta_err = (payload.get("meta") or {}).get("error")
        if meta_err:
            return _fail(result, steps, "research", str(meta_err))

        keywords = list(payload.get("keywords") or [])[:cap]
        if not keywords:
            return _fail(result, steps, "research", "Không tìm thấy từ khóa liên quan.")
        _emit("research", "done", f"Đã tìm {len(keywords)} từ khóa.")

        _emit("clustering", "running", "Đang gom cụm…")
        clusters = list(payload.get("clusters") or [])
        if not clusters:
            return _fail(result, steps, "clustering", "Không gom được cụm từ khóa.")
        _emit("clustering", "done", f"Đã gom {len(clusters)} cụm.")

        _emit("planning", "running", "Đang gợi ý title & outline…")
        clusters = _enrich_clusters_with_plans(clusters, keywords)
        _emit("planning", "done", f"Đã gợi ý cho {len(clusters)} cụm.")

        report = build_chatbot_research_report(
            mode="clusters",
            seed_keyword=seed,
            keywords=keywords,
            clusters=clusters,
            max_keywords=cap,
        )
        _emit("complete", "done", "Hoàn tất research + gom nhóm.")
        result.status = "completed"
        result.stats = {
            "seed_keyword": seed,
            "keywords_count": len(keywords),
            "clusters_count": len(clusters),
        }
        result.result = {
            "seed_keyword": seed,
            "research_report": report,
            "keywords": keywords[:cap],
            "clusters": clusters[:24],
            "total_keywords": len(keywords),
            "total_clusters": len(clusters),
        }
        result.actions = [
            {
                "type": "open_url",
                "label": "Mở Clustering",
                "url": "/keywords/tools/clustering",
            },
        ]
        result.steps = steps
        return result
    except Exception as exc:
        _LOG.exception("keyword research cluster workflow failed")
        running = next((s.id for s in steps if s.status == "running"), "research")
        return _fail(result, steps, running, f"Lỗi workflow: {exc}")


def run_url_seo_scoreboard_workflow(
    *,
    user_id: int,
    url: str,
    keyword: str = "",
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    from app.services.chatbot_seo_score_report import build_chatbot_seo_report_from_url
    from app.services.url_safety import assert_public_http_url
    from app.services.url_seo_scoreboard import build_url_seo_scoreboard

    steps = _init_steps(
        (
            ("crawl", "Crawl URL"),
            ("analyze", "Phân tích SEO Onpage"),
            ("complete", "Hoàn thành"),
        )
    )
    result = SimpleWorkflowResult(intent=INTENT_URL_SEO_SCOREBOARD, status="running", steps=steps)
    pk = str(keyword or "").strip()

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            for s in steps:
                if s.id == step_id:
                    on_step(s)
                    break

    try:
        assert_public_http_url(url, label="URL")
        _emit("crawl", "running", "Đang crawl URL…")
        raw = build_url_seo_scoreboard(url, keyword=pk or None)
        fetch = dict(raw.get("fetch") or {})
        if not fetch.get("ok"):
            return _fail(result, steps, "crawl", f"Không crawl được URL: {fetch.get('error') or fetch.get('status')}")
        _emit("crawl", "done", f"HTTP {fetch.get('status') or '—'}")

        _emit("analyze", "running", "Đang phân tích SEO Onpage…")
        seo_report = build_chatbot_seo_report_from_url(raw, keyword=pk, html="")
        score = int(seo_report.get("total_score") or 0)
        _emit("analyze", "done", f"Điểm tổng: {score}/100")
        _emit("complete", "done", "Hoàn tất chấm điểm.")
        result.status = "completed"
        result.stats = {
            "url": url,
            "score": score,
            "keyword": pk,
            "passed": bool(seo_report.get("passed")),
            "grade_label": seo_report.get("grade_label"),
        }
        result.result = {
            "url": url,
            "keyword": pk,
            "overall_score": score,
            "seo_report": seo_report,
        }
        result.steps = steps
        return result
    except Exception as exc:
        _LOG.exception("url seo scoreboard workflow failed")
        running = next((s.id for s in steps if s.status == "running"), "crawl")
        return _fail(result, steps, running, f"Không chấm được điểm: {exc}")


def run_content_seo_score_workflow(
    *,
    user_id: int,
    content_html: str,
    primary_keyword: str,
    title: str = "",
    meta_description: str = "",
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    from app.services.chatbot_seo_score_report import build_chatbot_seo_report_from_content
    from app.services.seo_core_30_score import score_seo_core_30
    from bs4 import BeautifulSoup

    steps = _init_steps(
        (
            ("analyze", "Phân tích nội dung"),
            ("complete", "Hoàn thành"),
        )
    )
    result = SimpleWorkflowResult(intent=INTENT_CONTENT_SEO_SCORE, status="running", steps=steps)
    pk = str(primary_keyword or "").strip()
    html = str(content_html or "").strip()

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            for s in steps:
                if s.id == step_id:
                    on_step(s)
                    break

    try:
        _emit("analyze", "running", "Đang phân tích SEO nội dung…")
        title_s = str(title or "").strip()
        meta_s = str(meta_description or "").strip()
        if not title_s or not meta_s:
            try:
                soup = BeautifulSoup(html[:800_000], "html.parser")
                if not title_s:
                    h1 = soup.find("h1")
                    title_s = h1.get_text(" ", strip=True) if h1 else ""
                if not meta_s:
                    meta_s = ""
            except Exception:
                pass

        checklist = score_seo_core_30(
            title=title_s,
            meta_description=meta_s,
            content_html=html,
            primary_keyword=pk,
        )
        seo_report = build_chatbot_seo_report_from_content(
            checklist,
            primary_keyword=pk,
            title=title_s,
            meta_description=meta_s,
            content_html=html,
        )
        score = int(seo_report.get("total_score") or 0)
        _emit("analyze", "done", f"Điểm tổng: {score}/100")
        _emit("complete", "done", "Hoàn tất phân tích.")
        result.status = "completed"
        result.stats = {
            "score": score,
            "keyword": pk,
            "passed": bool(seo_report.get("passed")),
            "grade_label": seo_report.get("grade_label"),
        }
        result.result = {
            "primary_keyword": pk,
            "overall_score": score,
            "seo_report": seo_report,
        }
        result.steps = steps
        return result
    except Exception as exc:
        _LOG.exception("content seo score workflow failed")
        running = next((s.id for s in steps if s.status == "running"), "analyze")
        return _fail(result, steps, running, f"Không phân tích được: {exc}")


def _run_technical_workflow_core(
    *,
    intent: str,
    mode: str,
    user_id: int,
    url: str,
    max_pages: int,
    save_audit: bool,
    step_defs: tuple[tuple[str, str], ...],
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    from app.services.analyzer import analyze_technical_seo
    from app.services.audit_store import save_technical_audit
    from app.services.chatbot_technical_report import build_chatbot_technical_report
    from app.services.url_safety import assert_public_http_url

    steps = _init_steps(step_defs)
    result = SimpleWorkflowResult(intent=intent, status="running", steps=steps)

    def _emit(step_id: str, status: StepStatus, message: str = "") -> None:
        _set_step(steps, step_id, status=status, message=message)
        if on_step:
            for s in steps:
                if s.id == step_id:
                    on_step(s)
                    break

    crawl_step = step_defs[0][0]
    analyze_step = step_defs[1][0]
    try:
        assert_public_http_url(url, label="URL")
        _emit(crawl_step, "running", "Đang thu thập dữ liệu…")
        audit = analyze_technical_seo(url, max_pages=max_pages, user_id=user_id)
        result_dict = audit.model_dump()
        pages = int(result_dict.get("pages_scanned") or 0)
        _emit(crawl_step, "done", f"Đã quét {pages} trang.")

        _emit(analyze_step, "running", "Đang phân tích technical…")
        audit_id = None
        if save_audit:
            saving_step = step_defs[2][0] if len(step_defs) > 3 else None
            if saving_step:
                _emit(saving_step, "running", "Đang lưu báo cáo…")
            audit_id = save_technical_audit(user_id=user_id, source_url=url, result=result_dict)
            result_dict["audit_id"] = audit_id
            if saving_step:
                _emit(saving_step, "done", f"Đã lưu báo cáo #{audit_id[:8]}…")

        technical_report = build_chatbot_technical_report(result_dict, mode=mode, url=url)
        score = int(technical_report.get("health_score") or 0)
        counts = technical_report.get("issue_counts") or {}
        _emit(analyze_step, "done", f"Điểm technical: {score}/100")

        complete_step = step_defs[-1][0]
        _emit(complete_step, "done", "Hoàn tất.")

        result.status = "completed"
        result.stats = {
            "url": url,
            "score": score,
            "pages_scanned": pages,
            "high_issues": int(counts.get("critical") or 0),
            "audit_id": audit_id,
            "mode": mode,
        }
        result.result = {
            "url": url,
            "audit_id": audit_id,
            "overall_score": score,
            "pages_scanned": pages,
            "technical_report": technical_report,
        }
        actions: list[dict[str, str]] = []
        if audit_id:
            actions.append(
                {"type": "open_url", "label": "Xem báo cáo Technical", "url": f"/report?audit_id={audit_id}"}
            )
        actions.append({"type": "open_url", "label": "Mở Technical SEO Tool", "url": "/seo-tool"})
        result.actions = actions
        result.steps = steps
        return result
    except Exception as exc:
        _LOG.exception("technical workflow failed intent=%s", intent)
        running = next((s.id for s in steps if s.status == "running"), crawl_step)
        return _fail(result, steps, running, f"Audit thất bại: {exc}")


def run_technical_quick_audit_workflow(
    *,
    user_id: int,
    url: str,
    max_pages: int = 10,
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    return _run_technical_workflow_core(
        intent=INTENT_TECHNICAL_QUICK_AUDIT,
        mode="quick",
        user_id=user_id,
        url=url,
        max_pages=max(3, min(15, int(max_pages or 10))),
        save_audit=False,
        step_defs=(
            ("crawl", "Crawl nhanh"),
            ("analyze", "Kiểm tra lỗi cơ bản"),
            ("complete", "Hoàn thành"),
        ),
        on_step=on_step,
    )


def run_technical_deep_audit_workflow(
    *,
    user_id: int,
    url: str,
    max_pages: int = 50,
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    return _run_technical_workflow_core(
        intent=INTENT_TECHNICAL_DEEP_AUDIT,
        mode="deep",
        user_id=user_id,
        url=url,
        max_pages=max(5, min(200, int(max_pages or 50))),
        save_audit=True,
        step_defs=(
            ("crawl", "Crawl nhiều trang"),
            ("analyze", "Phân tích chi tiết"),
            ("saving", "Lưu báo cáo"),
            ("complete", "Hoàn thành"),
        ),
        on_step=on_step,
    )


def run_technical_single_url_workflow(
    *,
    user_id: int,
    url: str,
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    return _run_technical_workflow_core(
        intent=INTENT_TECHNICAL_SINGLE_URL,
        mode="single",
        user_id=user_id,
        url=url,
        max_pages=1,
        save_audit=False,
        step_defs=(
            ("fetch", "Lấy dữ liệu URL"),
            ("analyze", "Kiểm tra technical"),
            ("complete", "Hoàn thành"),
        ),
        on_step=on_step,
    )


def run_technical_audit_workflow(
    *,
    user_id: int,
    url: str,
    max_pages: int = 50,
    on_step: Callable[[SimpleWorkflowStep], None] | None = None,
) -> SimpleWorkflowResult:
    """Legacy alias → audit chuyên sâu."""
    return run_technical_deep_audit_workflow(
        user_id=user_id,
        url=url,
        max_pages=max_pages,
        on_step=on_step,
    )


def build_simple_workflow_reply(run: SimpleWorkflowResult) -> str:
    if run.status == "failed":
        lines = ["Workflow không hoàn tất.", "", f"**Lỗi:** {run.error or 'Không xác định'}"]
        return "\n".join(lines)

    stats = run.stats or {}
    lines = ["Workflow đã hoàn tất.", ""]

    if run.intent == INTENT_KEYWORD_RESEARCH:
        lines.extend(
            [
                f"- **Từ khóa gốc:** {stats.get('seed_keyword', '—')}",
                f"- **Số keyword:** {stats.get('keywords_count', 0)}",
            ]
        )
    elif run.intent == INTENT_KEYWORD_RESEARCH_CLUSTER:
        lines.extend(
            [
                f"- **Từ khóa gốc:** {stats.get('seed_keyword', '—')}",
                f"- **Số keyword:** {stats.get('keywords_count', 0)}",
                f"- **Số cụm:** {stats.get('clusters_count', 0)}",
            ]
        )
    elif run.intent == INTENT_URL_SEO_SCOREBOARD:
        lines.extend(
            [
                f"- **URL:** {stats.get('url', '—')}",
                f"- **Điểm SEO:** {stats.get('score', 0)}/100",
            ]
        )
    elif run.intent == INTENT_CONTENT_SEO_SCORE:
        lines.extend(
            [
                f"- **Từ khóa:** {stats.get('keyword', '—')}",
                f"- **Điểm SEO:** {stats.get('score', 0)}/100",
                f"- **Xếp hạng:** {stats.get('grade_label', '—')}",
            ]
        )
    elif run.intent in (
        INTENT_TECHNICAL_QUICK_AUDIT,
        INTENT_TECHNICAL_DEEP_AUDIT,
        INTENT_TECHNICAL_SINGLE_URL,
    ):
        mode_label = {"quick": "Audit nhanh", "deep": "Audit chuyên sâu", "single": "Kiểm tra URL"}.get(
            str(stats.get("mode") or ""), "Technical"
        )
        lines.extend(
            [
                f"- **Workflow:** {mode_label}",
                f"- **URL:** {stats.get('url', '—')}",
                f"- **Điểm technical:** {stats.get('score', 0)}/100",
                f"- **Trang đã quét:** {stats.get('pages_scanned', 0)}",
                f"- **Lỗi nghiêm trọng:** {stats.get('high_issues', 0)}",
            ]
        )

    for act in run.actions:
        if act.get("url"):
            lines.append(f"- **{act.get('label', 'Mở')}:** {act['url']}")
    return "\n".join(lines)
