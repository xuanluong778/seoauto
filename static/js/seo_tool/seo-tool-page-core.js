/** SEO Tool page — Core: bootstrap, overview, scan */
let CHECKLIST_TITLE_VI = {};
try {
    const _chkViEl = document.getElementById("seoChecklistTitleViData");
    if (_chkViEl && _chkViEl.textContent) CHECKLIST_TITLE_VI = JSON.parse(_chkViEl.textContent);
} catch (_e) {
    CHECKLIST_TITLE_VI = {};
}

const btn = document.getElementById("btnTechnical");
const urlInput = document.getElementById("url");
const msg = document.getElementById("msg");
const issuesCard = document.getElementById("issuesCard");
const issuesTbody = document.getElementById("issuesTbody");

let lastTechnicalAuditId = null;

function setSeoToolExportVisible(visible) {
    const exportSec = document.getElementById("seoToolExportSection");
    if (exportSec) exportSec.hidden = !visible;
    if (document.body) {
        document.body.classList.toggle("seo-tool-has-results", !!visible);
    }
}

const SAAS_SCAN_MODE_LABEL = {
    crawl_only: "Chỉ quét website",
    hybrid_gsc: "Kết hợp Search Console",
    partial_gsc: "Search Console một phần",
};
const SAAS_SOURCE_LABEL = {
    crawl: "Quét website",
    gsc: "Search Console",
    hybrid: "Kết hợp",
    crawl_detected: "Quét website",
};

function saasFmtNum(n) {
    if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
    return String(n);
}

/** Chuẩn hóa payload audit (mới hoặc cũ) — tránh crash khi thiếu field SaaS/GSC. */
function normalizeAuditPayload(d) {
    if (!d || typeof d !== "object") return {};
    const out = Object.assign({}, d);
    out.issues = Array.isArray(d.issues) ? d.issues : [];
    out.normalized_issues = Array.isArray(d.normalized_issues) ? d.normalized_issues : [];
    out.priority_fixes = Array.isArray(d.priority_fixes) ? d.priority_fixes : [];
    out.category_summaries = Array.isArray(d.category_summaries) ? d.category_summaries : [];
    out.passed_checks = Array.isArray(d.passed_checks) ? d.passed_checks : [];
    out.disclaimers = Array.isArray(d.disclaimers) ? d.disclaimers : [];
    out.gsc_confirmed_issues = Array.isArray(d.gsc_confirmed_issues) ? d.gsc_confirmed_issues : [];
    out.gsc_opportunities = Array.isArray(d.gsc_opportunities) ? d.gsc_opportunities : [];
    out.gsc_enriched_pages = Array.isArray(d.gsc_enriched_pages) ? d.gsc_enriched_pages : [];
    out.gsc_query_rows = Array.isArray(d.gsc_query_rows) ? d.gsc_query_rows : [];
    out.url_inspection_results = Array.isArray(d.url_inspection_results)
        ? d.url_inspection_results
        : [];
    out.gsc_intelligence_summary =
        d.gsc_intelligence_summary && typeof d.gsc_intelligence_summary === "object"
            ? d.gsc_intelligence_summary
            : {};
    out.gsc_summary = d.gsc_summary && typeof d.gsc_summary === "object" ? d.gsc_summary : null;
    out.technical_summary =
        d.technical_summary && typeof d.technical_summary === "object" ? d.technical_summary : {};
    out.saas_summary = d.saas_summary && typeof d.saas_summary === "object" ? d.saas_summary : null;
    out.partial_data = !!d.partial_data;
    out.audit_id = d.audit_id || d.id || null;
    if (!out.source_url && d.domain) {
        out.source_url = d.source_url || "https://" + String(d.domain);
    }
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.enrichPayload === "function") {
        window.TechDashboardV2.enrichPayload(out);
    }
    return out;
}

function resolveSaasSummary(payload) {
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.resolveSummary === "function") {
        const v2 = window.TechDashboardV2.resolveSummary(payload);
        if (v2 && v2.is_v2) {
            let scanMode = v2.scan_mode || "crawl_only";
            const gs = payload && payload.gsc_summary;
            if (!v2.scan_mode && gs && gs.enabled) {
                scanMode = payload.partial_data || gs.partial_data ? "partial_gsc" : "hybrid_gsc";
            }
            return {
                technical_score: v2.health_score,
                critical_count: v2.critical,
                warning_count: v2.warning,
                opportunity_count: v2.opportunity,
                high_count: v2.warning,
                medium_count: 0,
                low_count: v2.opportunity,
                passed_count: v2.passed,
                pages_scanned: v2.pages_scanned,
                gsc_confidence: null,
                scan_mode: scanMode,
                is_v2: true,
            };
        }
    }
    const ss = payload && payload.saas_summary;
    if (
        ss &&
        typeof ss === "object" &&
        (ss.technical_score != null || ss.scan_mode || ss.critical_count != null)
    ) {
        return ss;
    }
    const ts = (payload && payload.technical_summary) || {};
    const by = ts.issues_by_severity || {};
    const norm = Array.isArray(payload && payload.normalized_issues) ? payload.normalized_issues : [];
    let critical = 0;
    let high = 0;
    let medium = 0;
    let low = 0;
    if (norm.length) {
        norm.forEach((i) => {
            const s = String(i.severity || "").toLowerCase();
            if (s === "critical") critical += 1;
            else if (s === "high") high += 1;
            else if (s === "medium") medium += 1;
            else if (s === "low") low += 1;
        });
    } else {
        const legacyIssues = Array.isArray(payload.issues)
            ? payload.issues.filter((it) => it && !it.suppressed)
            : [];
        if (legacyIssues.length) {
            legacyIssues.forEach((it) => {
                const s = String(it.severity || "").toLowerCase();
                if (s === "critical") critical += 1;
                else if (s === "high") high += 1;
                else if (s === "medium") medium += 1;
                else if (s === "low") low += 1;
            });
        } else {
            high = Number(by.high != null ? by.high : 0) || 0;
            medium = Number(by.medium != null ? by.medium : 0) || 0;
            low = Number(by.low != null ? by.low : 0) || 0;
        }
    }
    const gs = payload && payload.gsc_summary;
    let scanMode = "crawl_only";
    if (gs && gs.enabled) {
        scanMode = payload.partial_data || gs.partial_data ? "partial_gsc" : "hybrid_gsc";
    }
    let gscConf = 0;
    if (ss && ss.gsc_confidence != null) gscConf = Number(ss.gsc_confidence);
    else if (payload && payload.confidence_overall != null) {
        gscConf = Math.round(Number(payload.confidence_overall) * 100);
    }
    const passed = Array.isArray(payload && payload.passed_checks) ? payload.passed_checks.length : 0;
    let score = ts.health_score;
    if (score == null && ss) score = ss.technical_score;
    return {
        technical_score: score != null && score !== "" ? Number(score) : null,
        critical_count: critical,
        high_count: high,
        medium_count: medium,
        low_count: low,
        passed_count: passed,
        gsc_confidence: gscConf,
        scan_mode: scanMode,
    };
}

function renderSaasSummary(payload) {
    if (!payload || typeof payload !== "object") return;
    const ss = resolveSaasSummary(payload);
    const dom = (payload.domain || "").trim() || (urlInput && urlInput.value.trim()) || "—";
    const pill = document.getElementById("techCompleteDomainPill");
    if (pill) {
        pill.textContent = "🔗 " + dom;
        pill.setAttribute("title", dom);
    }

    if (window.TechDashboardV2 && window.TechDashboardV2.renderOverviewV2Summary(payload)) {
        let scoreNum =
            ss.technical_score != null && ss.technical_score !== ""
                ? Math.round(Number(ss.technical_score))
                : null;
        if (scoreNum != null && Number.isNaN(scoreNum)) scoreNum = null;
        if (scoreNum != null) scoreNum = Math.max(0, Math.min(100, scoreNum));
        const card = document.getElementById("seoToolHealthScoreCard");
        if (card) {
            card.classList.remove("score-band-good", "score-band-mid", "score-band-low");
            if (scoreNum == null) card.classList.add("score-band-mid");
            else if (scoreNum >= 80) card.classList.add("score-band-good");
            else if (scoreNum >= 50) card.classList.add("score-band-mid");
            else card.classList.add("score-band-low");
        }
        const hint = document.getElementById("saasHealthScoreHint");
        if (hint) {
            if (scoreNum == null) hint.textContent = "Chưa có điểm tổng hợp từ lần quét này.";
            else if (scoreNum >= 80) hint.textContent = "Tốt — Tiếp tục duy trì và tinh chỉnh định kỳ.";
            else if (scoreNum >= 50) hint.textContent = "Trung bình — Cần tối ưu đáng kể.";
            else hint.textContent = "Yếu — Ưu tiên xử lý Critical và Warning trước.";
        }
        return;
    }

    const ssLegacy = ss;
    let scoreNum =
        ssLegacy.technical_score != null && ssLegacy.technical_score !== ""
            ? Math.round(Number(ssLegacy.technical_score))
            : null;
    if (scoreNum != null && Number.isNaN(scoreNum)) scoreNum = null;
    if (scoreNum != null) scoreNum = Math.max(0, Math.min(100, scoreNum));

    const valEl = document.getElementById("saasHealthScoreValue");
    if (valEl) valEl.textContent = scoreNum != null ? String(scoreNum) : "—";
    const legacyVal = document.getElementById("techCompleteScoreValue");
    if (legacyVal) legacyVal.textContent = scoreNum != null ? String(scoreNum) : "—";

    const card = document.getElementById("seoToolHealthScoreCard");
    if (card) {
        card.classList.remove("score-band-good", "score-band-mid", "score-band-low");
        if (scoreNum == null) card.classList.add("score-band-mid");
        else if (scoreNum >= 80) card.classList.add("score-band-good");
        else if (scoreNum >= 50) card.classList.add("score-band-mid");
        else card.classList.add("score-band-low");
    }

    const hint = document.getElementById("saasHealthScoreHint");
    if (hint) {
        if (scoreNum == null) hint.textContent = "Chưa có điểm tổng hợp từ lần quét này.";
        else if (scoreNum >= 80) hint.textContent = "Tốt — Tiếp tục duy trì và tinh chỉnh định kỳ.";
        else if (scoreNum >= 50) hint.textContent = "Trung bình — Cần tối ưu đáng kể.";
        else hint.textContent = "Yếu — Ưu tiên xử lý các mục Critical / High trước.";
    }

    const setCount = (id, n) => {
        const el = document.getElementById(id);
        if (el) el.textContent = String(Number(n) || 0);
    };
    setCount("saasCountCritical", ss.critical_count);
    setCount("saasCountHigh", ss.high_count);
    setCount("saasCountMedium", ss.medium_count);
    setCount("saasCountLow", ss.low_count);
    setCount("saasCountPassed", ss.passed_count);
    const elLo = document.getElementById("techCompleteCountLow");
    const elMed = document.getElementById("techCompleteCountMed");
    const elHi = document.getElementById("techCompleteCountHigh");
    if (elLo) elLo.textContent = String(ss.low_count || 0);
    if (elMed) elMed.textContent = String(ss.medium_count || 0);
    if (elHi) elHi.textContent = String(ss.high_count || 0);

    const gscEl = document.getElementById("saasGscConfidence");
    if (gscEl) {
        const conf = ss.gsc_confidence;
        gscEl.textContent =
            conf != null && conf !== "" && !Number.isNaN(Number(conf))
                ? Math.round(Number(conf)) + "%"
                : "—";
    }

    const modeEl = document.getElementById("saasScanMode");
    if (modeEl) {
        const mode = ss.scan_mode || "crawl_only";
        modeEl.textContent = SAAS_SCAN_MODE_LABEL[mode] || mode;
        modeEl.className = "seo-tool-scan-mode seo-tool-scan-mode-" + String(mode).replace(/_/g, "-");
    }

    const urlStatEl = document.getElementById("seoToolUrlsScannedStat");
    if (urlStatEl) {
        const pages = payload.pages_scanned;
        if (pages != null && pages !== "" && !Number.isNaN(Number(pages))) {
            urlStatEl.textContent = String(Number(pages));
        } else {
            urlStatEl.textContent = "—";
        }
    }
}

function resolvePriorityFixes(payload) {
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.resolvePriorityIssues === "function") {
        const v2 = window.TechDashboardV2.resolvePriorityIssues(payload);
        if (v2 && v2.length) return v2;
    }
    const fixes = payload && payload.priority_fixes;
    if (Array.isArray(fixes) && fixes.length) return fixes;
    const issues = Array.isArray(payload && payload.issues)
        ? payload.issues.filter((it) => it && !it.suppressed)
        : [];
    const sevRank = { critical: 4, high: 3, medium: 2, low: 1 };
    const grouped = {};
    issues.forEach((it) => {
        const key = it.type || it.group || it.message || "issue";
        if (!grouped[key]) grouped[key] = { issue: it, urls: [] };
        if (it.url) grouped[key].urls.push(it.url);
    });
    return Object.values(grouped)
        .sort((a, b) => (sevRank[b.issue.severity] || 0) - (sevRank[a.issue.severity] || 0))
        .slice(0, 5)
        .map((g, idx) => ({
            id: g.issue.type || "legacy-" + idx,
            title: g.issue.message || g.issue.type || "Issue",
            category: g.issue.group || "General",
            severity:
                g.issue.severity === "high"
                    ? "high"
                    : g.issue.severity === "medium"
                      ? "medium"
                      : "low",
            priority_score: (sevRank[g.issue.severity] || 1) * 10,
            how_to_fix: "",
            sample_urls: [...new Set(g.urls)].slice(0, 8),
            source: g.issue.gsc_badge === "gsc_confirmed" ? "gsc" : "crawl",
        }));
}

function enrichPriorityFix(fix, payload) {
    const norm = Array.isArray(payload && payload.normalized_issues) ? payload.normalized_issues : [];
    const match = norm.find((i) => i.id === fix.id || i.type === fix.id);
    const urls = fix.sample_urls || (match && match.sample_urls) || [];
    const affected =
        (match && (match.count || (match.affected_urls && match.affected_urls.length))) ||
        urls.length ||
        0;
    return {
        id: fix.id,
        title: fix.title || (match && match.title) || "Issue",
        category: fix.category || (match && match.category) || "other",
        severity: fix.severity || (match && match.severity) || "medium",
        priority_score: fix.priority_score != null ? fix.priority_score : (match && match.priority_score) || 0,
        how_to_fix: fix.how_to_fix || (match && match.how_to_fix) || "",
        why_it_matters: fix.why_it_matters || (match && match.why_it_matters) || "",
        sample_urls: urls,
        source: fix.source || (match && match.source) || "crawl",
        affected_count: affected,
    };
}

function saasSeverityBadgeClass(severity) {
    const s = String(severity || "medium").toLowerCase();
    if (s === "critical") return "saas-sev-critical";
    if (s === "warning") return "saas-sev-warning";
    if (s === "high") return "saas-sev-high";
    if (s === "opportunity") return "saas-sev-opportunity";
    if (s === "low") return "saas-sev-low";
    if (s === "passed") return "saas-sev-passed";
    return "saas-sev-medium";
}
window.saasSeverityBadgeClass = saasSeverityBadgeClass;

function saasSourceBadgeClass(source) {
    const s = String(source || "crawl").toLowerCase();
    if (s === "gsc") return "saas-src-gsc";
    if (s === "hybrid") return "saas-src-hybrid";
    return "saas-src-crawl";
}

function renderPriorityFixes(priorityFixes, payload) {
    const sec = document.getElementById("seoToolPriorityFixesSection");
    const list = document.getElementById("seoToolPriorityFixesList");
    if (!sec || !list) return;
    const fixes = Array.isArray(priorityFixes) ? priorityFixes : [];
    list.textContent = "";
    if (!fixes.length) {
        sec.hidden = true;
        return;
    }
    sec.hidden = false;
    fixes.forEach((rawFix, idx) => {
        const fix = enrichPriorityFix(rawFix, payload || {});
        const card = document.createElement("article");
        card.className = "seo-tool-priority-card";
        card.dataset.fixId = String(fix.id || idx);

        const head = document.createElement("div");
        head.className = "seo-tool-priority-head";
        head.innerHTML =
            '<span class="seo-tool-priority-rank">' +
            (idx + 1) +
            "</span>" +
            '<span class="saas-badge ' +
            saasSeverityBadgeClass(fix.severity) +
            '">' +
            String(fix.severity || "medium").toUpperCase() +
            "</span>" +
            '<span class="saas-badge ' +
            saasSourceBadgeClass(fix.source) +
            '">' +
            (SAAS_SOURCE_LABEL[fix.source] || SAAS_SOURCE_LABEL.crawl) +
            "</span>" +
            '<span class="seo-tool-priority-score">Score: <strong>' +
            saasFmtNum(fix.priority_score) +
            "</strong></span>";

        const title = document.createElement("h3");
        title.className = "seo-tool-priority-title";
        title.textContent = fix.title || "—";

        const meta = document.createElement("p");
        meta.className = "seo-tool-priority-meta";
        meta.textContent =
            "Ảnh hưởng ~" + (fix.affected_count || 0) + " URL";

        const why = document.createElement("p");
        why.className = "seo-tool-priority-why";
        why.textContent = fix.why_it_matters || "Ảnh hưởng khả năng index, crawl hoặc trải nghiệm người dùng.";

        const actions = document.createElement("div");
        actions.className = "seo-tool-priority-actions";
        const btnUrls = document.createElement("button");
        btnUrls.type = "button";
        btnUrls.className = "btn-priority-view-urls";
        btnUrls.textContent = "Xem URL";
        btnUrls.disabled = !(fix.sample_urls && fix.sample_urls.length);
        const btnFix = document.createElement("button");
        btnFix.type = "button";
        btnFix.className = "btn-priority-how-to-fix";
        btnFix.textContent = "Hướng dẫn sửa";

        const urlPanel = document.createElement("div");
        urlPanel.className = "seo-tool-priority-urls";
        urlPanel.hidden = true;
        if (fix.sample_urls && fix.sample_urls.length) {
            const ul = document.createElement("ul");
            fix.sample_urls.forEach((u) => {
                const li = document.createElement("li");
                const a = document.createElement("a");
                a.href = u;
                a.target = "_blank";
                a.rel = "noopener noreferrer";
                a.textContent = u;
                li.appendChild(a);
                ul.appendChild(li);
            });
            urlPanel.appendChild(ul);
        }

        const fixPanel = document.createElement("div");
        fixPanel.className = "seo-tool-priority-guide";
        fixPanel.hidden = true;
        const fixText = fix.how_to_fix || (GROUP_SOLUTIONS_VI && GROUP_SOLUTIONS_VI[fix.category]) || GROUP_SOLUTIONS_VI.General;
        fixPanel.textContent = fixText;

        btnUrls.addEventListener("click", () => {
            urlPanel.hidden = !urlPanel.hidden;
        });
        btnFix.addEventListener("click", () => {
            fixPanel.hidden = !fixPanel.hidden;
        });

        actions.appendChild(btnUrls);
        actions.appendChild(btnFix);
        card.appendChild(head);
        card.appendChild(title);
        card.appendChild(meta);
        card.appendChild(why);
        card.appendChild(actions);
        card.appendChild(urlPanel);
        card.appendChild(fixPanel);
        list.appendChild(card);
    });
}

function resolveGscIntelligenceSummary(payload) {
    const gi = payload && payload.gsc_intelligence_summary;
    if (gi && typeof gi === "object" && gi.enabled) return gi;
    const gs = payload && payload.gsc_summary;
    if (!gs || !gs.enabled) return null;
    const confirmed = Array.isArray(payload.gsc_confirmed_issues) ? payload.gsc_confirmed_issues.length : 0;
    const opps = Array.isArray(payload.gsc_opportunities) ? payload.gsc_opportunities.length : 0;
    return {
        enabled: true,
        property: gs.property,
        start_date: gs.start_date,
        end_date: gs.end_date,
        clicks: gs.clicks,
        impressions: gs.impressions,
        avg_ctr: gs.avg_ctr,
        avg_position: gs.avg_position,
        urls_inspected: gs.urls_inspected,
        confirmed_issues_count: confirmed,
        opportunity_count: opps,
        partial_data: !!(payload.partial_data || gs.partial_data),
        message: gs.message || "",
    };
}

function renderGscIntelligenceSummary(summary, payload) {
    const sec = document.getElementById("seoToolGscIntelSection");
    if (!sec) return;
    const s = summary && summary.enabled ? summary : resolveGscIntelligenceSummary(payload || {});
    if (!s || !s.enabled) {
        sec.hidden = true;
        return;
    }
    sec.hidden = false;
    const propEl = document.getElementById("gscIntelProperty");
    if (propEl) {
        propEl.textContent = s.property
            ? "Property: " + s.property + (s.start_date ? " · " + s.start_date + " → " + s.end_date : "")
            : "—";
    }
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };
    set("gscStatClicks", saasFmtNum(s.clicks));
    set("gscStatImpressions", saasFmtNum(s.impressions));
    set(
        "gscStatCtr",
        s.avg_ctr != null && s.avg_ctr !== "" ? (Number(s.avg_ctr) * 100).toFixed(2) + "%" : "—"
    );
    set(
        "gscStatPosition",
        s.avg_position != null && s.avg_position !== "" ? Number(s.avg_position).toFixed(1) : "—"
    );
    set("gscStatInspected", saasFmtNum(s.urls_inspected));
    const confirmed =
        s.confirmed_issues_count != null
            ? s.confirmed_issues_count
            : Array.isArray(payload && payload.gsc_confirmed_issues)
              ? payload.gsc_confirmed_issues.length
              : 0;
    set("gscStatConfirmed", saasFmtNum(confirmed));
    set("gscStatOpportunities", saasFmtNum(s.opportunity_count != null ? s.opportunity_count : 0));

    const partial = !!(payload && payload.partial_data) || !!s.partial_data;
    const warnEl = document.getElementById("gscIntelPartialWarn");
    if (warnEl) {
        if (partial) {
            warnEl.hidden = false;
            warnEl.textContent =
                "Dữ liệu Search Console một phần — một số URL chưa được kiểm tra. Kết quả vẫn hữu ích nhưng nên xác minh thêm trong Search Console.";
        } else {
            warnEl.hidden = true;
            warnEl.textContent = "";
        }
    }
    const msgEl = document.getElementById("gscIntelMessage");
    if (msgEl) {
        msgEl.textContent = s.message || "";
        msgEl.className = "seo-tool-gsc-intel-note" + (partial ? " is-warn" : "");
    }
}

function renderSaasDisclaimers(payload) {
    const el = document.getElementById("seoToolDisclaimers");
    if (!el) return;
    const items = Array.isArray(payload && payload.disclaimers) ? payload.disclaimers : [];
    el.textContent = "";
    if (!items.length) {
        el.hidden = true;
        return;
    }
    el.hidden = false;
    items.forEach((line) => {
        const p = document.createElement("p");
        p.className = "seo-tool-disclaimer-line";
        p.textContent = line;
        el.appendChild(p);
    });
}

function issueNavTypeKey(issue) {
    if (!issue || typeof issue !== "object") return "issue";
    if (issue._issue_type) return String(issue._issue_type);
    const id = String(issue.id || issue.type || "");
    if (/^.+_[a-f0-9]{12}$/.test(id)) {
        const parts = id.split("_");
        return parts.slice(0, -1).join("_") || id;
    }
    if (id.includes("|")) return id.split("|")[0];
    return id || String(issue.title || "issue");
}

function renderSidebarWebsiteSnapshot(payload) {
    const box = document.getElementById("techSidebarWebsiteSnapshot");
    if (!box) return;
    if (!payload || typeof payload !== "object" || !(payload.domain || payload.source_url)) {
        box.hidden = true;
        return;
    }
    box.hidden = false;
    const set = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text != null && text !== "" ? String(text) : "—";
    };
    const dom = (payload.domain || "").trim() || (payload.source_url || "").replace(/^https?:\/\//i, "").split("/")[0];
    set("techSnapDomain", dom);
    set("techSnapPages", payload.pages_scanned != null ? payload.pages_scanned : "—");
    const ss = resolveSaasSummary(payload);
    set(
        "techSnapHealth",
        ss.technical_score != null && ss.technical_score !== "" ? Math.round(Number(ss.technical_score)) + "/100" : "—"
    );
    const robots = payload.robots && typeof payload.robots === "object" ? payload.robots : {};
    const rs = robots.status != null ? Number(robots.status) : null;
    set(
        "techSnapRobots",
        rs == null ? "—" : rs === 200 || rs === 0 ? "OK" : "Lỗi"
    );
    const sitemap = payload.sitemap && typeof payload.sitemap === "object" ? payload.sitemap : {};
    const smUrls = Array.isArray(sitemap.urls) ? sitemap.urls.length : 0;
    const smSt = sitemap.status != null ? Number(sitemap.status) : null;
    set(
        "techSnapSitemap",
        smSt == null ? "—" : (smSt === 200 || smSt === 0 ? "OK" : "Lỗi") + (smUrls ? " · " + smUrls + " URL" : "")
    );
    const broken = Array.isArray(payload.broken_internal_links) ? payload.broken_internal_links.length : 0;
    const chains = Array.isArray(payload.redirect_chains) ? payload.redirect_chains.length : 0;
    set("techSnapBroken", broken);
    set("techSnapRedirects", chains);
    const modeLabels = {
        crawl_only: "Chỉ quét website",
        hybrid_gsc: "Kết hợp Search Console",
        partial_gsc: "Search Console một phần",
    };
    set("techSnapScanMode", modeLabels[ss.scan_mode] || ss.scan_mode || "—");
    const norm = resolveNormalizedIssues(payload).filter((i) => i && String(i.severity).toLowerCase() !== "passed");
    const legacy = Array.isArray(payload.issues) ? payload.issues.filter((it) => it && !it.suppressed) : [];
    set("techSnapIssueTotal", norm.length || legacy.length || 0);
}

function hideTechnicalCompleteBanner() {
    const ov = document.getElementById("seoToolResultsOverview");
    if (ov) ov.hidden = true;
    const hdr = document.getElementById("seoToolResultsHeader");
    if (hdr) hdr.hidden = true;
    const snap = document.getElementById("techSidebarWebsiteSnapshot");
    if (snap) snap.hidden = true;
    const ovPassed = document.getElementById("seoToolOverviewPassedSection");
    if (ovPassed) ovPassed.hidden = true;
    setSeoToolExportVisible(false);
}

function renderOverviewContent(payload) {
    const ov = document.getElementById("seoToolResultsOverview");
    if (!ov || !payload) return;
    payload = normalizeAuditPayload(payload);
    const TD = window.TechDashboardV2;
    if (TD && typeof TD.canUseGroupRenderer === "function" && TD.canUseGroupRenderer(payload)) {
        if (typeof TD.enrichPayload === "function") TD.enrichPayload(payload);
        TD.renderOverview(
            typeof TD.getDashboardForRender === "function" ? TD.getDashboardForRender(payload) : null,
            payload,
            {
                navigateTab: navigateTechTab,
                openAudit: openAuditRun,
                getToken: function () { return token; },
            }
        );
        lastTechnicalAuditId = payload.audit_id || null;
        const btnEx = document.getElementById("btnTechnicalDownloadExcel");
        if (btnEx) btnEx.disabled = !payload.audit_id;
        if (payload.audit_id) {
            btnExportCsv.disabled = false;
            btnExportGsheet.disabled = false;
            btnExportCsv.dataset.auditExportId = String(payload.audit_id);
            btnExportGsheet.dataset.auditExportId = String(payload.audit_id);
        } else {
            delete btnExportCsv.dataset.auditExportId;
            delete btnExportGsheet.dataset.auditExportId;
        }
        setSeoToolExportVisible(true);
        ov.hidden = false;
        return;
    }
    renderSaasSummary(payload);
    renderPriorityFixes(resolvePriorityFixes(payload), payload);
    renderGscIntelligenceSummary(payload.gsc_intelligence_summary, payload);
    renderSaasDisclaimers(payload);
    renderSidebarWebsiteSnapshot(payload);
    renderResultsHeader(payload);
    renderOverviewPassedPreview(payload);
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.renderPassedCollapsible === "function") {
        window.TechDashboardV2.renderPassedCollapsible(payload);
    }

    lastTechnicalAuditId = payload.audit_id || null;
    const btnEx = document.getElementById("btnTechnicalDownloadExcel");
    if (btnEx) btnEx.disabled = !payload.audit_id;
    if (payload.audit_id) {
        btnExportCsv.disabled = false;
        btnExportGsheet.disabled = false;
        btnExportCsv.dataset.auditExportId = String(payload.audit_id);
        btnExportGsheet.dataset.auditExportId = String(payload.audit_id);
    } else {
        delete btnExportCsv.dataset.auditExportId;
        delete btnExportGsheet.dataset.auditExportId;
    }

    setSeoToolExportVisible(true);
    ov.hidden = false;
}

function showTechnicalCompleteBanner(payload) {
    renderOverviewContent(payload);
    const ov = document.getElementById("seoToolResultsOverview");
    if (!ov) return;
    try {
        ov.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (_e) {
        ov.scrollIntoView();
    }
}

function revealToolResultsPanel() {
    const ttp = document.getElementById("toolTablePanel");
    if (ttp) {
        ttp.hidden = false;
        ttp.classList.add("is-visible");
    }
    const hdr = document.getElementById("techContentHeader");
    if (hdr && cachedTechnicalPayload) hdr.hidden = false;
}

/** Hiển thị issue cards / bảng lỗi + crawl extras sau quét hoặc khi mở audit từ sidebar */
function applyTechnicalScanPayload(d) {
    if (!d || typeof d !== "object") return;
    d = normalizeAuditPayload(d);
    mountTechResultsInRightPanel();
    cachedTechnicalPayload = d;
    const issues = Array.isArray(d.issues)
        ? d.issues.filter((it) => it && !it.suppressed)
        : [];
    cachedTechnicalIssues = issues.slice();
    cachedNormalizedIssues = resolveNormalizedIssues(d);
    indexNormalizedIssues(cachedNormalizedIssues);
    renderCrawlExtras(d);
    renderTechnicalHealthSummary(d.technical_summary || {});
    updateTechSidebarFromPayload(d);
    renderPassedChecks(d);
    renderOverviewPassedPreview(d);
    renderSidebarWebsiteSnapshot(d);
    lastTechnicalAuditId = d.audit_id || null;
    if (typeof window !== "undefined") {
        window.__seoLastTechnicalAuditId = lastTechnicalAuditId;
    }
    activeTechTab = "overview";
    syncIssuesTableFilterBucket();
    revealToolResultsPanel();
    setTechNavActive("overview");
    renderTechTabContent();
    setSeoToolExportVisible(!!d.audit_id);
    const ov = document.getElementById("seoToolResultsOverview");
    if (ov) {
        try {
            ov.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } catch (_e) {
            ov.scrollIntoView();
        }
    }
    try {
        const target = document.getElementById("issuesCard") || document.getElementById("toolTablePanel");
        if (target) scrollToTechPanel(target);
    } catch (_e) {}
}

/** Đồng bộ với app/services/report_builder.py — map group → gợi ý / tài liệu */
const GROUP_SOLUTIONS_VI = {
    GSC:
        "Rà soát coverage/index trong GSC, rút gọn chuỗi redirect, chuẩn hóa canonical để Google crawl ổn định. " +
        "Ví dụ: GSC → Cài đặt → chọn đúng property (https://www.tenmien.com/ hoặc sc-domain:tenmien.com) → Lập chỉ mục → xuất CSV theo từng «Lý do».",
    Onpage: "Chỉnh title, meta description, cấu trúc H1–H2 đồng nhất theo template.",
    Sitemap: "Giữ sitemap XML hợp lệ, bỏ sitemap thừa/lỗi, gửi lại index sạch trong GSC.",
    Robots: "Cập nhật robots.txt: chặn path kém giá trị, khai báo dòng Sitemap đúng.",
    Speed: "Cải thiện Core Web Vitals, nén ảnh/CSS/JS, giảm render-blocking.",
    Security:
        "Đảm bảo HTTPS, chứng chỉ hợp lệ, mã phản hồi máy chủ ổn định. " +
        "Ví dụ: curl -I https://tenmien.com phải thấy HTTP/2 200; curl -I http://tenmien.com phải 301 Location: https://… (không để 200 trên HTTP).",
    Mobile: "Tối ưu UX và tốc độ mobile, tránh layout/ads cản trở người dùng.",
    Images: "Nén ảnh nặng, bổ sung alt mô tả liên quan nội dung.",
    Video: "Chuẩn hóa embed/video schema, thêm ngữ cảnh text hỗ trợ index.",
    International: "Bổ sung hreflang/lang đúng, self-referential canonical.",
    General: "Phân công SEO/Dev xử lý theo từng hạng mục Technical-SEO.txt.",
};
const GROUP_REFERENCES = {
    GSC: "https://support.google.com/webmasters/answer/7440203",
    Onpage: "https://developers.google.com/search/docs/fundamentals/seo-starter-guide",
    Sitemap: "https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap",
    Robots: "https://developers.google.com/search/docs/crawling-indexing/robots/intro",
    Speed: "https://web.dev/vitals/",
    Security: "https://developers.google.com/search/docs/crawling-indexing/https",
    Mobile: "https://developers.google.com/search/mobile-sites/",
    Images: "https://developers.google.com/search/docs/appearance/google-images",
    Video: "https://developers.google.com/search/docs/appearance/video",
    International: "https://developers.google.com/search/docs/specialty/international",
    General: "https://developers.google.com/search/docs",
};
const SEVERITY_LABEL_VI = {
    critical: "Critical",
    high: "Cao",
    medium: "Trung bình",
    low: "Thấp",
    passed: "Passed",
};

/** Icon SVG theo loại lỗi (minh họa nhanh trong checklist). */
function issueIllusSvg(type) {
    const t = String(type || "issue");
    if (t === "broken_internal_link" || t === "broken_internal_http_error") {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#7f1d1d"/><path fill="none" stroke="#fecaca" stroke-width="3" d="M14 18h8v8M26 22h8M18 30h12"/><text x="24" y="21" text-anchor="middle" fill="#fff" font-size="9" font-weight="700">HTTP</text></svg>';
    }
    if (t === "redirect_chain") {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#78350f"/><path fill="none" stroke="#fde68a" stroke-width="2.5" d="M10 24h28M32 18l6 6-6 6"/></svg>';
    }
    if (t.startsWith("robots_") || t === "robots_unreachable") {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#14532d"/><text x="24" y="30" text-anchor="middle" fill="#bbf7d0" font-size="11" font-weight="700">R</text></svg>';
    }
    if (t.startsWith("sitemap_")) {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#1e3a5f"/><path fill="#93c5fd" d="M12 32V16h8l4 4h12v12z"/></svg>';
    }
    if (t === "https_not_used" || t === "crawl_page_non_200" || t === "http_status_error") {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#991b1b"/><text x="24" y="31" text-anchor="middle" fill="#fecaca" font-size="14" font-weight="800">!</text></svg>';
    }
    if (t.includes("title") || t.includes("h1") || t.includes("meta") || t.includes("canonical") || t.includes("favicon") || t.includes("lang")) {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#312e81"/><text x="24" y="30" text-anchor="middle" fill="#e0e7ff" font-size="10" font-weight="700">TAG</text></svg>';
    }
    if (t.includes("image") || t.includes("alt")) {
        return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#14532d"/><rect x="12" y="14" width="24" height="18" rx="3" fill="none" stroke="#86efac" stroke-width="2"/><circle cx="18" cy="20" r="2" fill="#86efac"/></svg>';
    }
    return '<svg viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#334155"/><text x="24" y="31" text-anchor="middle" fill="#cbd5e1" font-size="18">?</text></svg>';
}

function renderCrawlExtras(d) {
    const card = document.getElementById("crawlExtrasCard");
    const br = document.getElementById("brokenLinksDetailBody");
    const rc = document.getElementById("redirectChainsDetailBody");
    if (!card || !br || !rc) return;
    const broken = Array.isArray(d.broken_internal_links) ? d.broken_internal_links : [];
    if (!broken.length) {
        br.innerHTML = '<p class="cell-muted" style="margin:0;">Không có liên kết nội bộ trả lỗi trong phạm vi đã kiểm tra.</p>';
    } else {
        const li = broken.map((row) => {
            const u = escHtml(row.url || "");
            const st = row.status != null ? String(row.status) : "?";
            const stLabel = st === "0" ? "0 (timeout / không phản hồi)" : st;
            return "<li><strong>Lỗi " + escHtml(stLabel) + "</strong> — <a href=\"" + u + "\" target=\"_blank\" rel=\"noopener noreferrer\">" + u + "</a></li>";
        }).join("");
        br.innerHTML = "<ol class=\"crawl-detail-list\">" + li + "</ol><p class=\"crawl-detail-meta\">Liệt kê theo từng URL đích đã kiểm tra (song song để rút ngắn thời gian).</p>";
    }
    const chains = Array.isArray(d.redirect_chains) ? d.redirect_chains : [];
    if (!chains.length) {
        rc.innerHTML = '<p class="cell-muted" style="margin:0;">Không phát hiện chuỗi redirect dài.</p>';
    } else {
        rc.innerHTML = chains.map((c) => {
            const steps = Array.isArray(c.chain)
                ? c.chain.map((x) => "<li><a href=\"" + escHtml(x) + "\" target=\"_blank\" rel=\"noopener noreferrer\">" + escHtml(x) + "</a></li>").join("")
                : "";
            const hops = c.hops != null ? c.hops : 0;
            return "<div style=\"margin-bottom:14px;\"><strong>" + escHtml(c.url || "") + "</strong> (" + escHtml(String(hops)) + " bước)<ol class=\"crawl-detail-list\">" + steps + "</ol></div>";
        }).join("");
    }
    card.hidden = false;
}

function escHtml(s) {
    if (s == null) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
}

const GSC_BADGE_LABELS = {
    gsc_confirmed: "Đã xác nhận Search Console",
    crawl_detected: "Crawl Detected",
    inferred_warning: "Inferred Warning",
};

function gscBadgeClass(badge) {
    const b = String(badge || "crawl_detected").toLowerCase();
    if (b === "gsc_confirmed") return "gsc-badge gsc-badge-confirmed";
    if (b === "inferred_warning") return "gsc-badge gsc-badge-inferred";
    return "gsc-badge gsc-badge-crawl";
}

function appendGscMetricsBlock(parent, item) {
    if (!parent || !item) return;
    const imp = item.gsc_impressions;
    const clk = item.gsc_clicks;
    if (imp == null && clk == null && !item.gsc_index_verdict) return;
    const box = document.createElement("div");
    box.className = "issue-gsc-metrics";
    const parts = [];
    if (clk != null) parts.push("Clicks 28d: " + clk);
    if (imp != null) parts.push("Impressions 28d: " + imp);
    if (item.gsc_ctr != null) parts.push("CTR: " + (Number(item.gsc_ctr) * 100).toFixed(2) + "%");
    if (item.gsc_position != null && item.gsc_position > 0) {
        parts.push("Vị trí TB: " + Number(item.gsc_position).toFixed(1));
    }
    if (item.gsc_index_verdict) parts.push("Index: " + item.gsc_index_verdict);
    if (item.gsc_coverage_state) parts.push("Coverage: " + item.gsc_coverage_state);
    if (item.gsc_google_canonical) parts.push("Google canonical: " + item.gsc_google_canonical);
    if (item.gsc_user_canonical) parts.push("User canonical: " + item.gsc_user_canonical);
    box.textContent = parts.join(" · ");
    parent.appendChild(box);
}

function renderGscIntelligence(payload) {
    renderGscIntelligenceSummary(
        payload && payload.gsc_intelligence_summary,
        payload || {}
    );
}

function getGscAuditRequestExtras() {
    const useGsc = document.getElementById("chkUseGscAudit");
    const sel = document.getElementById("gscSiteSelect");
    const dr = document.getElementById("gscDateRangeSelect");
    const lim = document.getElementById("gscInspectionLimitSelect");
    const property = sel && sel.value ? sel.value.trim() : "";
    if (!useGsc || !useGsc.checked || !property) {
        return { use_gsc: false };
    }
    return {
        use_gsc: true,
        gsc_property: property,
        gsc_date_range: dr ? dr.value : "28d",
        url_inspection_limit: lim ? parseInt(lim.value, 10) || 10 : 10,
    };
}

