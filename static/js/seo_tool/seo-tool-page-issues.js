/** SEO Tool page — Issues: normalization, filters, cards */
function syncGscAuditOptionsUi(connected) {
    const opts = document.getElementById("gscAuditOptions");
    const cta = document.getElementById("gscConnectCta");
    if (opts) opts.hidden = !connected;
    if (cta) cta.hidden = connected;
}

function normalizeGroup(g) {
    if (g == null || g === "") return "General";
    const s = String(g);
    const hit = Object.keys(GROUP_SOLUTIONS_VI).find((k) => k.toLowerCase() === s.toLowerCase());
    return hit || s;
}
function refLinkCell(group) {
    const g = normalizeGroup(group);
    const u = GROUP_REFERENCES[g] || GROUP_REFERENCES.General;
    if (!u) return '<span class="cell-muted">—</span>';
    return '<a href="' + escHtml(u) + '" target="_blank" rel="noopener noreferrer">' + escHtml(u) + "</a>";
}

let cachedTechnicalIssues = [];
let cachedNormalizedIssues = [];
let cachedIssuesById = {};
let cachedTechnicalPayload = null;
let activeTechTab = "overview";
/** @deprecated alias — dùng activeTechTab; giữ để tương thích chip bar cũ */
let issuesTableFilterBucket = null;
let technicalIssueSort = "severity";
const fixedIssueIds = new Set();

const TECH_TAB_LABELS = (window.TechSidebarV2 && window.TechSidebarV2.TAB_LABELS) || {
    overview: "Tổng quan",
    priority: "Việc cần sửa",
    index_crawl: "Index & Crawl",
    onpage: "On-page",
    perf_security: "Performance & Security",
    indexability: "Index & Crawl",
    crawlability: "Index & Crawl",
    internal_links: "Index & Crawl",
    performance: "Performance & Security",
    structured_data: "On-page",
    security_http: "Performance & Security",
    ux_mobile: "On-page",
    security_ux: "Performance & Security",
    gsc: "GSC",
    passed: "Passed Checks",
    history: "Lịch sử",
};

const TECH_CATEGORY_TABS = (window.TechSidebarV2 && window.TechSidebarV2.CATEGORY_TABS) || new Set([
    "priority",
    "index_crawl",
    "onpage",
    "perf_security",
    "gsc",
]);

const TECH_NAV_LEGACY_KEYS = (window.TechSidebarV2 && window.TechSidebarV2.LEGACY_TAB_TO_GROUP) || {
    all_issues: "priority",
    recent: "history",
    https_security: "security_http",
    http_codes: "crawlability",
    seo_basic: "onpage",
    speed: "performance",
    security: "security_http",
    security_ux: "security_http",
    errors_console: "gsc",
    url_redirect: "indexability",
    website: "crawlability",
    sitemap: "indexability",
    robots: "crawlability",
    schema: "structured_data",
    images: "onpage",
    video: "onpage",
    site_speed: "performance",
    https: "security_http",
    response_code: "crawlability",
    mobile: "ux_mobile",
    international: "onpage",
    other: "crawlability",
    passed: "overview",
};

function normalizeTechTabKey(tab) {
    if (window.TechSidebarV2 && typeof window.TechSidebarV2.normalizeTechTabKey === "function") {
        return window.TechSidebarV2.normalizeTechTabKey(tab);
    }
    const t = String(tab || "overview");
    return TECH_NAV_LEGACY_KEYS[t] || t;
}

function isIssueCategoryTab(tab) {
    if (window.TechSidebarV2 && typeof window.TechSidebarV2.isIssueCategoryTab === "function") {
        return window.TechSidebarV2.isIssueCategoryTab(tab);
    }
    return TECH_CATEGORY_TABS.has(normalizeTechTabKey(tab));
}

function issueMatchesSidebarTab(issue, tab) {
    const t = normalizeTechTabKey(tab);
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.issueMatchesSidebarTab === "function") {
        return window.TechDashboardV2.issueMatchesSidebarTab(issue, t);
    }
    return normalizedIssueNavBucket(issue) === t;
}

function syncIssuesTableFilterBucket() {
    const tab = normalizeTechTabKey(activeTechTab);
    issuesTableFilterBucket = isIssueCategoryTab(tab) ? tab : null;
}
let technicalIssueFilter = "all";
let technicalIssueSearchQuery = "";
let issuesViewMode = "cards";

const ISSUES_CARD_HEADING_CARDS = "Issue Explorer — Card View";
const ISSUES_CARD_HEADING_TABLE =
    "Issue Explorer — Table View (cuộn trong khung bảng)";

const NORM_CAT_TO_LEGACY_GROUP = {
    gsc_indexing: "GSC",
    website: "General",
    sitemap: "Sitemap",
    robots: "Robots",
    schema: "General",
    images: "Images",
    video: "Video",
    site_speed: "Speed",
    https: "Security",
    response_code: "General",
    onpage: "Onpage",
    mobile: "Mobile",
    international: "International",
    other: "General",
};

function indexNormalizedIssues(issues) {
    cachedIssuesById = {};
    (Array.isArray(issues) ? issues : []).forEach((it) => {
        if (it && it.id != null) cachedIssuesById[String(it.id)] = it;
    });
}

function legacyToNormalized(item) {
    const type = String(item.type || "issue");
    const url = item.url ? String(item.url) : "";
    const group = normalizeGroup(item.checklist_group || item.group || item.category);
    const catSlug = String(item.category || "")
        .toLowerCase()
        .replace(/\s+/g, "_");
    const category =
        catSlug && catSlug !== "general"
            ? catSlug
            : Object.keys(NORM_CAT_TO_LEGACY_GROUP).find(
                  (k) => NORM_CAT_TO_LEGACY_GROUP[k] === group
              ) || "other";
    const suggested =
        item.suggested_fix != null && String(item.suggested_fix).trim()
            ? String(item.suggested_fix).trim()
            : "";
    const rem =
        item.remediation != null && String(item.remediation).trim()
            ? String(item.remediation).trim()
            : "";
    let source = "crawl";
    if (item.gsc_badge === "gsc_confirmed") source = "gsc";
    else if (item.source) source = String(item.source).toLowerCase();
    const affected = url ? [url] : [];
    return {
        id: type + (url ? "|" + url : ""),
        category: category,
        title: CHECKLIST_TITLE_VI[type] || item.message || type.replace(/_/g, " "),
        description: String(item.message || item.description || "").trim(),
        source: source,
        severity: String(item.severity || "low").toLowerCase(),
        status: item.status || "failed",
        count: affected.length || 1,
        affected_urls: affected.slice(),
        sample_urls: affected.slice(0, 5),
        impact_area: Array.isArray(item.impact_area) ? item.impact_area : [],
        why_it_matters: String(item.why_it_matters || "").trim(),
        how_to_fix:
            suggested ||
            rem ||
            (GROUP_SOLUTIONS_VI[group] || GROUP_SOLUTIONS_VI.General),
        priority_score: item.priority_score != null ? Number(item.priority_score) : 0,
        confidence: item.confidence,
        gsc_badge: item.gsc_badge,
        gsc_clicks: item.gsc_clicks,
        gsc_impressions: item.gsc_impressions,
        gsc_ctr: item.gsc_ctr,
        gsc_position: item.gsc_position,
        gsc_index_verdict: item.gsc_index_verdict,
        _issue_type: type,
    };
}

function resolveNormalizedIssues(payload) {
    if (!payload || typeof payload !== "object") return [];
    const norm = payload.normalized_issues;
    if (Array.isArray(norm) && norm.length > 0) {
        return norm.filter((i) => i && typeof i === "object").map((i) => ({ ...i }));
    }
    const issues = Array.isArray(payload.issues)
        ? payload.issues.filter((it) => it && !it.suppressed)
        : [];
    const sevRank = { critical: 4, high: 3, medium: 2, low: 1 };
    const map = new Map();
    for (const it of issues) {
        const type = String(it.type || "issue");
        let entry = map.get(type);
        if (!entry) {
            entry = legacyToNormalized(it);
            entry.id = type;
            entry.affected_urls = [];
            entry.sample_urls = [];
            entry.count = 0;
            map.set(type, entry);
        }
        if (it.url) {
            const u = String(it.url);
            if (!entry.affected_urls.includes(u)) entry.affected_urls.push(u);
            if (entry.sample_urls.length < 8 && !entry.sample_urls.includes(u)) {
                entry.sample_urls.push(u);
            }
        }
        const sev = String(it.severity || "low").toLowerCase();
        const cur = String(entry.severity || "low").toLowerCase();
        if ((sevRank[sev] || 0) > (sevRank[cur] || 0)) entry.severity = sev;
        if (it.gsc_badge === "gsc_confirmed") entry.source = "gsc";
        entry.count = Math.max(entry.affected_urls.length, entry.count || 1);
    }
    const out = Array.from(map.values());
    const passed = Array.isArray(payload.passed_checks) ? payload.passed_checks : [];
    passed.forEach((p) => {
        if (!p || typeof p !== "object") return;
        out.push({
            id: p.id || "passed-" + out.length,
            category: p.category || "other",
            title: p.title || "Passed check",
            description: p.description || "",
            source: p.source || "crawl",
            severity: "passed",
            status: "passed",
            count: 0,
            affected_urls: [],
            sample_urls: [],
            impact_area: p.impact_area || [],
            why_it_matters: p.why_it_matters || "",
            how_to_fix: p.how_to_fix || "",
            priority_score: 0,
        });
    });
    return out;
}

function issueAffectedCount(issue) {
    if (!issue) return 0;
    if (issue.count != null && issue.count !== "") return Number(issue.count) || 0;
    const urls = issue.affected_urls || issue.sample_urls;
    return Array.isArray(urls) ? urls.length : 0;
}

function issueSearchHaystack(issue) {
    const urls = []
        .concat(issue.affected_urls || [])
        .concat(issue.sample_urls || [])
        .join(" ");
    return [
        issue.title,
        issue.description,
        issue.category,
        issue.source,
        issue.severity,
        issue._issue_type,
        urls,
    ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
}

const SEVERITY_SORT_RANK = { critical: 6, warning: 5, high: 5, medium: 4, opportunity: 3, low: 3, passed: 1 };

function issuePrimaryUrl(issue) {
    const urls = (issue && (issue.sample_urls || issue.affected_urls)) || [];
    return urls.length ? String(urls[0]) : "";
}

function sortNormalizedIssues(list) {
    const arr = Array.isArray(list) ? list.slice() : [];
    const mode = technicalIssueSort || "severity";
    if (mode === "url") {
        return arr.sort((a, b) => issuePrimaryUrl(a).localeCompare(issuePrimaryUrl(b)));
    }
    if (mode === "category") {
        return arr.sort((a, b) =>
            String(a.category || "").localeCompare(String(b.category || ""))
        );
    }
    return arr.sort((a, b) => {
        const ra = SEVERITY_SORT_RANK[String(a.severity || "").toLowerCase()] || 0;
        const rb = SEVERITY_SORT_RANK[String(b.severity || "").toLowerCase()] || 0;
        if (rb !== ra) return rb - ra;
        return (Number(b.priority_score) || 0) - (Number(a.priority_score) || 0);
    });
}

function filterNormalizedIssues(issues) {
    const list = Array.isArray(issues) ? issues.slice() : [];
    const q = String(technicalIssueSearchQuery || "")
        .trim()
        .toLowerCase();
    const tab = normalizeTechTabKey(activeTechTab);
    let out = list.filter((i) => String(i.severity || "").toLowerCase() !== "passed");
    if (tab === "priority") {
        out = getIssuesForTab("priority");
    } else if (isIssueCategoryTab(tab)) {
        out = out.filter((i) => issueMatchesSidebarTab(i, tab));
    } else if (tab !== "overview" && tab !== "passed" && tab !== "history") {
        out = out.filter((i) => issueMatchesSidebarTab(i, tab));
    }
    if (technicalIssueFilter === "critical") {
        out = out.filter((i) => String(i.severity).toLowerCase() === "critical");
    } else if (technicalIssueFilter === "warning") {
        out = out.filter((i) => String(i.severity).toLowerCase() === "warning");
    } else if (technicalIssueFilter === "opportunity") {
        out = out.filter((i) => String(i.severity).toLowerCase() === "opportunity");
    } else if (technicalIssueFilter === "high") {
        out = out.filter((i) => String(i.severity).toLowerCase() === "high");
    } else if (technicalIssueFilter === "medium") {
        out = out.filter((i) => String(i.severity).toLowerCase() === "medium");
    } else if (technicalIssueFilter === "low") {
        out = out.filter((i) => String(i.severity).toLowerCase() === "low");
    }
    if (q) {
        out = out.filter((i) => {
            const title = String(i.title || "").toLowerCase();
            const urls = []
                .concat(i.affected_urls || [])
                .concat(i.sample_urls || [])
                .join(" ")
                .toLowerCase();
            return title.includes(q) || urls.includes(q);
        });
    }
    if (window.TechDashboardV2) {
        const v2f = window.TechDashboardV2.getExplorerV2Filters
            ? window.TechDashboardV2.getExplorerV2Filters()
            : {};
        if (window.TechDashboardV2.issueMatchesV2Filters) {
            out = out.filter((i) => window.TechDashboardV2.issueMatchesV2Filters(i, v2f));
        }
        const catEl = document.getElementById("seoToolFilterCategory");
        if (catEl && catEl.value && catEl.value !== "all") {
            out = out.filter((i) => normalizedIssueNavBucket(i) === catEl.value);
        }
    }
    out = out.filter((i) => !fixedIssueIds.has(String(i.id != null ? i.id : "")));
    return sortNormalizedIssues(out);
}

function getTechnicalDomain() {
    const p = cachedTechnicalPayload || {};
    return (
        (p.domain || "").trim() ||
        (urlInput && urlInput.value.trim()) ||
        "website"
    );
}

function buildIssueFixPrompt(issue) {
    const title = issue.title || issue.id || "lỗi technical";
    const domain = getTechnicalDomain();
    const count = issueAffectedCount(issue);
    const severity = String(issue.severity || "medium");
    const description = issue.description || issue.why_it_matters || "—";
    const how = issue.how_to_fix || "—";
    return (
        "Bạn là chuyên gia Technical SEO. Hãy sửa lỗi " +
        title +
        " trên website " +
        domain +
        ". Lỗi ảnh hưởng " +
        count +
        " URL. Mức độ " +
        severity +
        ". Nguyên nhân: " +
        description +
        ". Cách sửa đề xuất: " +
        how +
        ". Không làm ảnh hưởng các URL đang index tốt."
    );
}

function issueCardSelector(issueId) {
    const safe = String(issueId).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return '.seo-tool-issue-card[data-issue-id="' + safe + '"]';
}

function openIssueUrls(issueId) {
    const issue = cachedIssuesById[String(issueId)];
    const card = document.querySelector(issueCardSelector(issueId));
    if (card) {
        const panel = card.querySelector(".seo-tool-issue-url-panel");
        if (panel) {
            panel.hidden = !panel.hidden;
            if (!panel.hidden) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
    }
    if (issue && issue.sample_urls && issue.sample_urls[0]) {
        try {
            window.open(issue.sample_urls[0], "_blank", "noopener,noreferrer");
        } catch (_e) {}
    }
}

function openIssueFixGuide(issueId) {
    const card = document.querySelector(issueCardSelector(issueId));
    if (!card) return;
    const panel = card.querySelector(".seo-tool-issue-guide-panel");
    if (panel) {
        panel.hidden = !panel.hidden;
        if (!panel.hidden) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
}

async function copyIssueFixPrompt(issueId) {
    const issue = cachedIssuesById[String(issueId)];
    if (!issue) return;
    const text = buildIssueFixPrompt(issue);
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
        }
        setMsg("Đã copy prompt sửa lỗi vào clipboard.", "ok");
    } catch (_e) {
        setMsg("Không copy được — hãy chọn thủ công trong hộp Hướng dẫn sửa.", "error");
    }
}

function formatImpactAreas(areas) {
    if (!Array.isArray(areas) || !areas.length) return "—";
    return areas.map((a) => String(a).replace(/_/g, " ")).join(", ");
}

function buildNormalizedIssueCard(issue) {
    const id = String(issue.id != null ? issue.id : "");
    const card = document.createElement("article");
    card.className = "seo-tool-issue-card is-clickable";
    if (fixedIssueIds.has(id)) card.classList.add("is-marked-fixed");
    card.dataset.issueId = id;

    const head = document.createElement("div");
    head.className = "seo-tool-issue-card-head";
    head.innerHTML =
        '<span class="saas-badge ' +
        saasSeverityBadgeClass(issue.severity) +
        '">' +
        String(issue.severity || "medium").toUpperCase() +
        "</span>";

    const title = document.createElement("h4");
    title.className = "seo-tool-issue-card-title";
    title.textContent = issue.title || "—";

    const urls = (issue.sample_urls || issue.affected_urls || []).filter(Boolean);
    const urlWrap = document.createElement("div");
    urlWrap.className = "seo-tool-issue-card-urls";
    if (!urls.length) {
        const emptyUrl = document.createElement("p");
        emptyUrl.className = "seo-tool-issue-card-url";
        emptyUrl.textContent = "—";
        urlWrap.appendChild(emptyUrl);
    } else {
        const ul = document.createElement("ul");
        ul.className = "seo-tool-issue-url-list";
        urls.slice(0, 25).forEach((u) => {
            const li = document.createElement("li");
            const a = document.createElement("a");
            a.href = u;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = u;
            li.appendChild(a);
            ul.appendChild(li);
        });
        urlWrap.appendChild(ul);
        if (urls.length > 25) {
            const more = document.createElement("p");
            more.className = "seo-tool-issue-url-more";
            more.textContent = "+ " + (urls.length - 25) + " URL khác";
            urlWrap.appendChild(more);
        }
    }

    const desc = document.createElement("p");
    desc.className = "seo-tool-issue-card-desc";
    desc.innerHTML =
        "<strong>Mô tả:</strong> " + (issue.description || "—");

    const impact = document.createElement("p");
    impact.className = "seo-tool-issue-card-impact";
    impact.innerHTML =
        "<strong>Ảnh hưởng:</strong> " +
        (issue.why_it_matters || formatImpactAreas(issue.impact_area) || "—");

    const fix = document.createElement("p");
    fix.className = "seo-tool-issue-card-fix";
    fix.innerHTML = "<strong>Cách sửa:</strong> " + (issue.how_to_fix || "—");

    const detailPanel = document.createElement("div");
    detailPanel.className = "seo-tool-issue-detail-panel";
    detailPanel.hidden = true;
    const detailBits = [];
    if (issue.category) detailBits.push("Category: " + issue.category);
    if (issue.source) detailBits.push("Source: " + issue.source);
    if (issue.priority_score != null) detailBits.push("Priority: " + issue.priority_score);
    if (urls.length > 1) {
        detailBits.push("URLs:\n" + urls.slice(0, 12).join("\n"));
    }
    detailPanel.textContent = detailBits.join("\n\n") || "—";

    const actions = document.createElement("div");
    actions.className = "seo-tool-issue-card-actions";
    const btnCopyFix = document.createElement("button");
    btnCopyFix.type = "button";
    btnCopyFix.className = "btn-issue-copy-fix";
    btnCopyFix.textContent = "Copy cách sửa";
    btnCopyFix.dataset.issueId = id;
    const btnMark = document.createElement("button");
    btnMark.type = "button";
    btnMark.className = "btn-issue-mark-fixed";
    btnMark.textContent = fixedIssueIds.has(id) ? "Đã đánh dấu" : "Đánh dấu đã sửa";
    btnMark.dataset.issueId = id;
    const btnDetail = document.createElement("button");
    btnDetail.type = "button";
    btnDetail.className = "btn-issue-details";
    btnDetail.textContent = "Chi tiết";
    btnDetail.dataset.issueId = id;
    actions.appendChild(btnCopyFix);
    actions.appendChild(btnMark);
    actions.appendChild(btnDetail);

    card.appendChild(head);
    card.appendChild(title);
    card.appendChild(urlWrap);
    card.appendChild(desc);
    card.appendChild(impact);
    card.appendChild(fix);
    card.appendChild(actions);
    card.appendChild(detailPanel);
    return card;
}

async function copyIssueHowToFix(issueId) {
    const issue = cachedIssuesById[String(issueId)];
    if (!issue) return;
    const text = issue.how_to_fix || issue.description || "";
    if (!text) {
        setMsg("Không có nội dung cách sửa để copy.", "error");
        return;
    }
    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.left = "-9999px";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
        }
        setMsg("Đã copy cách sửa vào clipboard.", "ok");
    } catch (_e) {
        setMsg("Không copy được — hãy chọn thủ công.", "error");
    }
}

function markIssueFixed(issueId) {
    const id = String(issueId || "");
    if (!id) return;
    if (fixedIssueIds.has(id)) fixedIssueIds.delete(id);
    else fixedIssueIds.add(id);
    renderTechTabContent();
}

function updateIssuesCountLabel(shown, total) {
    const el = document.getElementById("seoToolIssuesCount");
    if (!el) return;
    if (!total) {
        el.textContent = "Không có issue nào trong dữ liệu quét.";
        return;
    }
    el.textContent =
        "Hiển thị " + shown + " / " + total + " issue" + (shown !== 1 ? "s" : "");
}

function applyTechnicalFilters() {
    renderTechTabContent();
}

function countIssuesForTab(tab, issues) {
    const list = Array.isArray(issues) ? issues : [];
    const t = normalizeTechTabKey(tab);
    const nonPassed = list.filter((i) => String(i.severity || "").toLowerCase() !== "passed");
    if (t === "priority") {
        if (cachedTechnicalPayload) {
            return resolvePriorityFixes(cachedTechnicalPayload).length || nonPassed.length;
        }
        return nonPassed.length;
    }
    if (isIssueCategoryTab(t)) {
        if (window.TechDashboardV2 && typeof window.TechDashboardV2.issueMatchesSidebarTab === "function") {
            return nonPassed.filter((i) => window.TechDashboardV2.issueMatchesSidebarTab(i, t)).length;
        }
        return nonPassed.filter((i) => issueMatchesSidebarTab(i, t)).length;
    }
    return nonPassed.length;
}

function renderNormalizedIssues(issues) {
    const root = document.getElementById("issuesCardsView");
    const emptyEl = document.getElementById("techIssuesEmpty");
    if (!root) return;
    const all = Array.isArray(issues) ? issues : [];
    indexNormalizedIssues(all);
    const tabFiltered = filterNormalizedIssues(all);
    const tab = normalizeTechTabKey(activeTechTab);
    let pool = all.filter((i) => String(i.severity || "").toLowerCase() !== "passed");
    if (tab === "priority") {
        pool = getIssuesForTab("priority");
    } else if (isIssueCategoryTab(tab)) {
        pool = pool.filter((i) => issueMatchesSidebarTab(i, tab));
    }
    root.textContent = "";
    updateIssuesCountLabel(tabFiltered.length, pool.length);
    if (emptyEl) {
        emptyEl.hidden = tabFiltered.length > 0;
        emptyEl.textContent =
            pool.length > 0
                ? "Không có lỗi khớp bộ lọc / từ khóa tìm kiếm."
                : "Không phát hiện lỗi trong nhóm này.";
    }
    if (!tabFiltered.length) return;
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.buildSimpleIssueTable === "function") {
        root.appendChild(window.TechDashboardV2.buildSimpleIssueTable(tabFiltered));
        return;
    }
    tabFiltered.forEach((issue) => {
        root.appendChild(buildNormalizedIssueCard(issue));
    });
}

function isDesktopIssuesLayout() {
    return window.matchMedia("(min-width: 1025px)").matches;
}

function enforceIssuesViewForViewport() {
    if (!isDesktopIssuesLayout() && issuesViewMode === "table") {
        setIssuesViewMode("cards");
        if (cachedTechnicalIssues.length) {
            renderIssuesTable(cachedTechnicalIssues);
        }
    }
}

function setIssuesViewMode(mode) {
    if (mode === "table" && !isDesktopIssuesLayout()) {
        mode = "cards";
    }
    issuesViewMode = mode === "table" ? "table" : "cards";
    const toggle = document.getElementById("seoToolIssuesViewToggle");
    if (toggle) {
        toggle.querySelectorAll("[data-issues-view]").forEach((btn) => {
            btn.classList.toggle("is-active", btn.getAttribute("data-issues-view") === issuesViewMode);
        });
    }
    const cardsView = document.getElementById("issuesCardsView");
    const tableWrap = document.getElementById("issuesTableWrap");
    const toolbar = document.getElementById("seoToolIssuesToolbar");
    const heading = document.getElementById("issuesCardHeading");
    renderTechTabContent();
}

let issuesToolbarWired = false;
function wireIssuesToolbarOnce() {
    if (issuesToolbarWired) return;
    issuesToolbarWired = true;

    const searchEl = document.getElementById("seoToolIssuesSearch");
    if (searchEl) {
        searchEl.addEventListener("input", () => {
            technicalIssueSearchQuery = searchEl.value;
            applyTechnicalFilters();
        });
    }

    const filters = document.getElementById("seoToolIssuesFilters");
    if (filters) {
        filters.addEventListener("click", (ev) => {
            const btn = ev.target.closest("[data-tech-filter]");
            if (!btn) return;
            technicalIssueFilter = btn.getAttribute("data-tech-filter") || "all";
            filters.querySelectorAll("[data-tech-filter]").forEach((b) => {
                b.classList.toggle("is-active", b === btn);
            });
            applyTechnicalFilters();
        });
    }

    const toggle = document.getElementById("seoToolIssuesViewToggle");
    if (toggle) {
        toggle.addEventListener("click", (ev) => {
            const btn = ev.target.closest("[data-issues-view]");
            if (!btn) return;
            setIssuesViewMode(btn.getAttribute("data-issues-view"));
            if (issuesViewMode === "table") {
                renderIssuesTable(cachedTechnicalIssues);
            }
        });
    }

    const sortEl = document.getElementById("seoToolIssuesSort");
    if (sortEl) {
        sortEl.addEventListener("change", () => {
            technicalIssueSort = sortEl.value || "severity";
            applyTechnicalFilters();
        });
    }

    if (window.TechDashboardV2 && typeof window.TechDashboardV2.wireExplorerV2Filters === "function") {
        window.TechDashboardV2.wireExplorerV2Filters(applyTechnicalFilters);
    }
    const catFilter = document.getElementById("seoToolFilterCategory");
    if (catFilter && catFilter.dataset.wired !== "1") {
        catFilter.dataset.wired = "1";
        catFilter.addEventListener("change", applyTechnicalFilters);
    }

    const cardsRoot = document.getElementById("issuesCardsView");
    if (cardsRoot) {
        cardsRoot.addEventListener("click", (ev) => {
            const copyFixBtn = ev.target.closest(".btn-issue-copy-fix");
            const markBtn = ev.target.closest(".btn-issue-mark-fixed");
            const detailBtn = ev.target.closest(".btn-issue-details");
            if (copyFixBtn && copyFixBtn.dataset.issueId) {
                copyIssueHowToFix(copyFixBtn.dataset.issueId);
                return;
            }
            if (markBtn && markBtn.dataset.issueId) {
                markIssueFixed(markBtn.dataset.issueId);
                return;
            }
            if (detailBtn && detailBtn.dataset.issueId) {
                const issue = cachedIssuesById[String(detailBtn.dataset.issueId)];
                if (issue && window.TechDashboardV2 && window.TechDashboardV2.openIssueDrawer) {
                    window.TechDashboardV2.openIssueDrawer(issue);
                }
                return;
            }
            const card = ev.target.closest(".seo-tool-issue-card.is-clickable");
            if (card && card.dataset.issueId && !ev.target.closest("button, a")) {
                const issue = cachedIssuesById[String(card.dataset.issueId)];
                if (issue && window.TechDashboardV2 && window.TechDashboardV2.openIssueDrawer) {
                    window.TechDashboardV2.openIssueDrawer(issue);
                }
            }
        });
    }
}

/* Đồng bộ số mục với data/technical_audit_catalog.json (độ dài mảng items mỗi pillar) */
const TECH_NAV_TOTALS = {
    gsc: 14,
    website: 28,
    sitemap: 10,
    robots: 6,
    schema: 3,
    images: 4,
    video: 4,
    site_speed: 8,
    https: 11,
    response_code: 2,
    onpage: 8,
    mobile: 14,
    international: 11,
    other: 4,
};

let TECH_AUDIT_CATALOG = { pillars: [] };
try {
    const _catEl = document.getElementById("technicalAuditCatalogData");
    if (_catEl && _catEl.textContent) {
        const raw = JSON.parse(_catEl.textContent);
        if (raw && Array.isArray(raw.pillars)) TECH_AUDIT_CATALOG = raw;
    }
} catch (_e) {
    TECH_AUDIT_CATALOG = { pillars: [] };
}

function catalogPillarIdForNav(navKey) {
    const k = String(navKey || "");
    if (k === "https") return "https_security";
    if (k === "response_code") return "http_codes";
    return k;
}

function pillarCatalogItems(pillarId) {
    const lookup = catalogPillarIdForNav(pillarId);
    const rows = TECH_AUDIT_CATALOG.pillars || [];
    for (let i = 0; i < rows.length; i++) {
        const p = rows[i];
        if (p && p.id === lookup && Array.isArray(p.items)) return p.items;
    }
    return [];
}

function pillarTotalForBucket(id) {
    const n = pillarCatalogItems(id).length;
    if (n > 0) return n;
    return TECH_NAV_TOTALS[id] || 0;
}

function issueSidebarBucket(item) {
    const catSlug = String(item.category || "").toLowerCase();
    const normBucket = {
        gsc_indexing: "gsc",
        website: "website",
        sitemap: "sitemap",
        robots: "robots",
        schema: "schema",
        semantic_markup: "schema",
        images: "images",
        video: "video",
        site_speed: "site_speed",
        https: "https",
        response_code: "response_code",
        onpage: "onpage",
        mobile: "mobile",
        international: "international",
        other: "other",
    };
    if (normBucket[catSlug]) return normBucket[catSlug];
    const g = normalizeGroup(item.checklist_group || item.group || item.category);
    const t = String(item.type || item._issue_type || "").toLowerCase();
    if (g === "Sitemap" || /^sitemap_/.test(t)) return "sitemap";
    if (g === "Robots" || /^robots_/.test(t)) return "robots";
    if (g === "Images") return "images";
    if (g === "Video") return "video";
    if (g === "Mobile") return "mobile";
    if (g === "International") return "international";
    if (g === "Speed") return "site_speed";
    if (g === "Security") return "https";
    if (/^js_seo_|^js_shell_/.test(t)) return "website";
    if (g === "Onpage") return "onpage";
    if (t === "crawl_page_non_200" || t === "http_status_error") return "response_code";
    if (t === "link_check_truncated" || t === "crawl_data_low_trust") return "website";
    if (g === "GSC") {
        if (t === "broken_internal_link" || t === "broken_internal_http_error") return "website";
        return "gsc";
    }
    if (g === "General" || g === "Crawl quality") return "other";
    return "other";
}

/** Gộp nhiều URL cùng một loại issue — tránh lặp thẻ trong chế độ theo chuyên mục. */
function dedupeIssuesByType(items) {
    const arr = Array.isArray(items) ? items : [];
    const rank = { high: 3, medium: 2, low: 1 };
    const map = new Map();
    for (const it of arr) {
        const t = String(it.type != null ? it.type : "issue");
        const sev = String(it.severity || "low").toLowerCase();
        const r = rank[sev] || 0;
        const prev = map.get(t);
        if (!prev) {
            map.set(t, it);
            continue;
        }
        const r0 = rank[String(prev.severity || "low").toLowerCase()] || 0;
        if (r > r0) map.set(t, it);
    }
    return Array.from(map.values());
}

const TECH_PILLAR_UI = {
    gsc: {
        label: "Google Search Console",
        icon: "📡",
        sub: "Excluded URL, indexing, crawl, coverage, manual actions, security.",
    },
    website: { label: "Website", icon: "🌐", sub: "HTTP/HTTPS, links, JS crawl, cloaking, favicon, malware." },
    sitemap: { label: "Sitemap", icon: "🗺", sub: "XML sitemap, broken links, GSC/Bing submit." },
    robots: { label: "Robots.txt", icon: "🤖", sub: "robots.txt rules, disallow, sitemap declaration." },
    schema: { label: "Semantic Markup", icon: "📋", sub: "Structured data, schema errors, Local Business." },
    images: { label: "Images", icon: "🖼", sub: "Alt text, file size, image sitemap." },
    video: { label: "Video", icon: "🎬", sub: "Video sitemap, mobile-friendly video." },
    site_speed: { label: "Site Speed", icon: "⚡", sub: "PageSpeed, caching, minify CSS/JS." },
    https: { label: "HTTPS", icon: "🔒", sub: "SSL, mixed content, canonical, hreflang on HTTPS." },
    response_code: { label: "Response Code", icon: "🔢", sub: "3xx redirects, 4xx client errors." },
    onpage: { label: "Onpage", icon: "📝", sub: "Title, meta, H1/H2, duplicate tags." },
    mobile: { label: "Mobile", icon: "📱", sub: "Mobile-friendly, viewport, AMP, interstitials." },
    international: { label: "International", icon: "🌍", sub: "hreflang, lang attribute, geo parameters." },
    other: { label: "Lỗi khác", icon: "📌", sub: "Menu bar, redundant schema, miscellaneous." },
};

