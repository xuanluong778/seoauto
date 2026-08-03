/** SEO Tool page — Nav: sidebar, tabs, pillars */
function bucketStatsForNav(bucket, allIssues) {
    const total = pillarTotalForBucket(bucket);
    const arr = Array.isArray(allIssues) ? allIssues : [];
    const inBucket = [];
    for (const it of arr) {
        if (issueSidebarBucket(it) === bucket) inBucket.push(it);
    }
    const open = dedupeIssuesByType(inBucket).length;
    const done = Math.max(0, total - Math.min(open, total));
    return { total, open, done };
}

let pillarCardToggleWired = false;
function wirePillarCardTogglesOnce() {
    if (pillarCardToggleWired) return;
    const root = document.getElementById("issuesPillarView");
    if (!root) return;
    pillarCardToggleWired = true;
    root.addEventListener("click", (ev) => {
        const head = ev.target.closest(".issues-pillar-card-head");
        if (!head) return;
        const card = head.closest(".issues-pillar-card");
        if (!card) return;
        const body = card.querySelector(".issues-pillar-card-body");
        if (!body) return;
        const willOpen = !card.classList.contains("is-open");
        card.classList.toggle("is-open", willOpen);
        body.hidden = !willOpen;
        head.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });
}

function severityPriorityLabel(sev) {
    if (sev === "high") return "Quan trọng";
    if (sev === "medium") return "Trung bình";
    return "Thấp";
}

function catalogPriorityLabelVi(priority) {
    const p = String(priority || "").toLowerCase();
    if (p === "high") return "Quan trọng";
    if (p === "medium") return "Trung bình";
    if (p === "low") return "Thấp";
    if (p === "reference") return "Tham khảo";
    return "";
}

function catalogPriorityPriClass(priority) {
    const p = String(priority || "").toLowerCase();
    if (p === "high") return "issues-pillar-criteria-pri cat-pri-high";
    if (p === "medium") return "issues-pillar-criteria-pri cat-pri-medium";
    if (p === "low") return "issues-pillar-criteria-pri cat-pri-low";
    if (p === "reference") return "issues-pillar-criteria-pri cat-pri-reference";
    return "issues-pillar-criteria-pri cat-pri-low";
}

function appendCatalogCriteriaLine(ol, raw) {
    const li = document.createElement("li");
    if (raw != null && typeof raw === "object" && !Array.isArray(raw)) {
        const title = raw.title_vi != null ? String(raw.title_vi) : raw.title != null ? String(raw.title) : "";
        const detail =
            raw.detail_en != null
                ? String(raw.detail_en)
                : raw.detail != null
                  ? String(raw.detail)
                  : "";
        const pr = raw.priority != null ? String(raw.priority) : "";
        li.className = "issues-pillar-criteria-row";
        const main = document.createElement("div");
        main.className = "issues-pillar-criteria-row-main";
        if (title) {
            const t = document.createElement("strong");
            t.className = "issues-pillar-criteria-row-title";
            t.textContent = title;
            main.appendChild(t);
        }
        if (detail) {
            const p = document.createElement("p");
            p.className = "issues-pillar-criteria-row-detail";
            p.textContent = detail;
            main.appendChild(p);
        }
        li.appendChild(main);
        const lab = catalogPriorityLabelVi(pr);
        if (lab) {
            const badge = document.createElement("span");
            badge.className = catalogPriorityPriClass(pr);
            badge.textContent = lab;
            li.appendChild(badge);
        }
    } else {
        li.textContent = String(raw != null ? raw : "");
    }
    ol.appendChild(li);
}

function pillarResultTitle(sev) {
    if (sev === "high") return "Chưa đạt";
    if (sev === "medium") return "Cần xem xét";
    return "Ghi nhận";
}

function issueCardScorePct(sev) {
    if (sev === "high") return 22;
    if (sev === "medium") return 48;
    return 72;
}

function buildPillarIssueCard(item) {
    const group = normalizeGroup(item.checklist_group || item.group || item.category);
    const sev = String(item.severity || "low").toLowerCase();
    const type = String(item.type || "issue");
    const viTitle = CHECKLIST_TITLE_VI[type] || type.replace(/_/g, " ");
    const suggested =
        item.suggested_fix != null && String(item.suggested_fix).trim()
            ? String(item.suggested_fix).trim()
            : "";
    const rem =
        item.remediation != null && String(item.remediation).trim()
            ? String(item.remediation).trim()
            : "";
    const sol =
        suggested || rem || (GROUP_SOLUTIONS_VI[group] || GROUP_SOLUTIONS_VI.General);
    let explain =
        item.explanation != null && String(item.explanation).trim()
            ? String(item.explanation).trim()
            : "";
    if (!explain) {
        explain = sol.length > 480 ? sol.slice(0, 480) + "…" : sol;
    }
    const message = item.message != null ? String(item.message) : "";
    const url = item.url != null ? String(item.url) : "";
    let conf = item.confidence != null && item.confidence !== "" ? Number(item.confidence) : null;
    if (conf == null || Number.isNaN(conf)) {
        conf = sev === "high" ? 0.88 : sev === "medium" ? 0.72 : 0.58;
    }
    conf = Math.max(0, Math.min(1, conf));
    const pctRound = issueCardScorePct(sev);
    const pctC = Math.round(conf * 100);

    const article = document.createElement("article");
    article.className = "issues-pillar-card";

    const head = document.createElement("button");
    head.type = "button";
    head.className = "issues-pillar-card-head";
    head.setAttribute("aria-expanded", "false");

    const left = document.createElement("div");
    left.className = "issues-pillar-card-head-left";
    const ico = document.createElement("span");
    ico.className =
        "issues-pillar-card-ico" + (sev === "high" ? " is-bad" : sev === "medium" ? " is-warn" : "");
    ico.setAttribute("aria-hidden", "true");
    ico.textContent = sev === "low" ? "ℹ" : "⚠";
    const titleWrap = document.createElement("div");
    titleWrap.className = "issues-pillar-card-title";
    titleWrap.textContent = viTitle;
    left.appendChild(ico);
    left.appendChild(titleWrap);

    const badges = document.createElement("div");
    badges.className = "issues-pillar-badges";
    if (item.gsc_badge) {
        const gscB = document.createElement("span");
        gscB.className = gscBadgeClass(item.gsc_badge);
        gscB.textContent = GSC_BADGE_LABELS[item.gsc_badge] || item.gsc_badge;
        badges.appendChild(gscB);
    }
    const pri = document.createElement("span");
    pri.className =
        "issues-pillar-pri" + (sev === "medium" ? " sev-medium" : sev === "low" ? " sev-low" : "");
    pri.textContent = severityPriorityLabel(sev);
    const pct = document.createElement("span");
    pct.className =
        "issues-pillar-pct" + (sev === "medium" ? " sev-medium" : sev === "low" ? " sev-low" : "");
    pct.textContent = String(pctRound) + "%";
    const chev = document.createElement("span");
    chev.className = "issues-pillar-chev";
    chev.setAttribute("aria-hidden", "true");
    chev.textContent = "▼";
    badges.appendChild(pri);
    badges.appendChild(pct);
    badges.appendChild(chev);
    head.appendChild(left);
    head.appendChild(badges);

    const body = document.createElement("div");
    body.className = "issues-pillar-card-body";
    body.hidden = true;

    const ex = document.createElement("div");
    ex.className = "issues-pillar-explain";
    ex.textContent = explain;

    const res = document.createElement("div");
    res.className =
        "issues-pillar-result" +
        (sev === "high" ? " sev-high" : sev === "medium" ? " sev-medium" : " sev-low");
    const rTitle = document.createElement("strong");
    rTitle.textContent = pillarResultTitle(sev);
    const rMsg = document.createElement("div");
    rMsg.textContent = message || "—";
    res.appendChild(rTitle);
    res.appendChild(rMsg);

    const prev = document.createElement("div");
    prev.className = "issues-pillar-preview";
    const pre = document.createElement("pre");
    const previewBits = [];
    if (message) previewBits.push(message);
    if (url) previewBits.push(url);
    pre.textContent = previewBits.join("\n\n") || "—";
    prev.appendChild(pre);

    const meterW = document.createElement("div");
    meterW.className = "issues-pillar-meter-wrap";
    const lab = document.createElement("div");
    lab.className = "issues-pillar-meter-label";
    const labL = document.createElement("span");
    labL.textContent = "Độ tin cậy rule";
    const labR = document.createElement("span");
    labR.textContent = pctC + " / 100";
    lab.appendChild(labL);
    lab.appendChild(labR);
    const track = document.createElement("div");
    track.className = "issues-pillar-meter-track";
    const fill = document.createElement("div");
    fill.className =
        "issues-pillar-meter-fill" +
        (sev === "high" ? " sev-high" : sev === "medium" ? " sev-medium" : "");
    fill.style.width = pctC + "%";
    track.appendChild(fill);
    meterW.appendChild(lab);
    meterW.appendChild(track);

    body.appendChild(ex);
    appendGscMetricsBlock(body, item);
    body.appendChild(res);
    body.appendChild(prev);
    body.appendChild(meterW);

    article.appendChild(head);
    article.appendChild(body);
    return article;
}

function renderPillarIssueView(bucket, list, allIssues) {
    wirePillarCardTogglesOnce();
    const wrap = document.getElementById("issuesPillarView");
    const tableWrap = document.getElementById("issuesTableWrap");
    const cardsView = document.getElementById("issuesCardsView");
    const toolbar = document.getElementById("seoToolIssuesToolbar");
    const heading = document.getElementById("issuesCardHeading");
    if (!wrap || !tableWrap || !heading) return;

    if (cardsView) cardsView.hidden = true;
    if (toolbar) toolbar.hidden = true;

    const ui = TECH_PILLAR_UI[bucket] || { label: bucket, icon: "📌", sub: "" };
    const stats = bucketStatsForNav(bucket, allIssues);

    heading.textContent =
        ui.label + (list.length ? " — " + list.length + " loại issue" : " — không có issue");

    wrap.hidden = false;
    tableWrap.hidden = true;
    wrap.textContent = "";

    const critLines = pillarCatalogItems(bucket);
    const critN = critLines.length;

    const headRow = document.createElement("div");
    headRow.className = "issues-pillar-head";
    const main = document.createElement("div");
    main.className = "issues-pillar-head-main";
    const ico = document.createElement("span");
    ico.className = "issues-pillar-head-ico";
    ico.setAttribute("aria-hidden", "true");
    ico.textContent = ui.icon;
    const textCol = document.createElement("div");
    const h4 = document.createElement("h4");
    h4.className = "issues-pillar-head-title";
    h4.textContent = ui.label;
    const sub = document.createElement("p");
    sub.className = "issues-pillar-head-sub";
    sub.textContent = stats.total + " tiêu chí kiểm tra" + (ui.sub ? " · " + ui.sub : "");
    textCol.appendChild(h4);
    textCol.appendChild(sub);
    main.appendChild(ico);
    main.appendChild(textCol);
    const badgeEl = document.createElement("div");
    badgeEl.className =
        "issues-pillar-summary-badge" +
        (stats.done >= stats.total ? " is-ok" : stats.done >= stats.total * 0.65 ? " is-warn" : "");
    if (allIssues.length) {
        if (critN > 0) {
            badgeEl.textContent = stats.open + " loại issue · " + critN + " tiêu chí tham chiếu";
            badgeEl.title =
                stats.open +
                " loại lỗi khác nhau (theo type, đã gộp URL). " +
                critN +
                " là số mục trong checklist tham chiếu — không phải mục nào cũng đã có rule quét tự động.";
        } else {
            badgeEl.textContent = stats.done + "/" + stats.total + " đạt";
            badgeEl.removeAttribute("title");
        }
    } else {
        badgeEl.textContent = "—";
        badgeEl.removeAttribute("title");
    }
    headRow.appendChild(main);
    headRow.appendChild(badgeEl);
    wrap.appendChild(headRow);

    if (critLines.length && bucket !== "onpage") {
        const critSec = document.createElement("section");
        critSec.className = "issues-pillar-criteria";
        critSec.setAttribute("aria-label", "Tiêu chí kiểm tra tham chiếu");
        const critH = document.createElement("h5");
        critH.className = "issues-pillar-criteria-title";
        if (bucket === "gsc") {
            critH.textContent = "Tiêu chí kiểm tra (Google Search Console & lập chỉ mục)";
        } else if (bucket === "onpage") {
            critH.textContent = critLines.length + " tiêu chí kiểm tra (SEO cơ bản)";
        } else {
            critH.textContent =
                "Tiêu chí kiểm tra (tham chiếu — " + (TECH_PILLAR_UI[bucket] ? TECH_PILLAR_UI[bucket].label : bucket) + ")";
        }
        const ol = document.createElement("ol");
        ol.className = "issues-pillar-criteria-list";
        if (critLines.some((x) => x && typeof x === "object" && !Array.isArray(x))) {
            ol.classList.add("issues-pillar-criteria-list--rich");
        }
        critLines.forEach((line) => {
            appendCatalogCriteriaLine(ol, line);
        });
        critSec.appendChild(critH);
        if (bucket === "onpage") {
            const hint = document.createElement("p");
            hint.className = "issues-pillar-criteria-hint";
            hint.innerHTML =
                "Danh sách <strong>đủ " +
                critLines.length +
                " mục</strong> đánh số 1–" +
                critLines.length +
                " — cuộn trong khung để xem từ đầu đến cuối.";
            critSec.appendChild(hint);
        }
        const needsScroll = bucket === "onpage" || critLines.length >= 12;
        if (needsScroll) {
            const scrollWrap = document.createElement("div");
            scrollWrap.className = "issues-pillar-criteria-scroll";
            scrollWrap.setAttribute("aria-label", "Danh sách " + critLines.length + " tiêu chí — cuộn để xem hết");
            scrollWrap.appendChild(ol);
            critSec.appendChild(scrollWrap);
        } else {
            critSec.appendChild(ol);
        }
        const foot = document.createElement("p");
        foot.className = "issues-pillar-criteria-footnote";
        foot.textContent =
            "Checklist trên là tham chiếu (" +
            critLines.length +
            " mục). Các thẻ trắng bên dưới chỉ xuất hiện khi rule quét ghi nhận lỗi thật — thường chỉ vài loại; nhiều mục chưa có engine rule riêng nên không sinh thẻ.";
        critSec.appendChild(foot);
        wrap.appendChild(critSec);
    }

    if (list.length) {
        const scanH = document.createElement("p");
        scanH.className = "issues-pillar-scan-note";
        scanH.textContent =
            "Mỗi thẻ = một loại issue (type) sau khi gộp nhiều URL. Số thẻ không bắt buộc bằng số mục checklist — chỉ những rule đã kích hoạt mới hiện.";
        wrap.appendChild(scanH);
    }

    const cardsRoot = document.createElement("div");
    cardsRoot.className = "issues-pillar-cards";
    if (!list.length) {
        const empty = document.createElement("div");
        empty.className = "issues-pillar-empty";
        empty.textContent = allIssues.length
            ? "Nhóm này không có issue nào từ lần quét hiện tại — các tiêu chí đang ổn trong phạm vi rule đã chạy."
            : "Chưa có dữ liệu checklist. Hãy chọn một domain trong mục «Lần quét gần đây» để tải bản quét.";
        cardsRoot.appendChild(empty);
    } else {
        for (const item of list) {
            cardsRoot.appendChild(buildPillarIssueCard(item));
        }
    }
    wrap.appendChild(cardsRoot);
}

function hidePillarIssueView() {
    const wrap = document.getElementById("issuesPillarView");
    const tableWrap = document.getElementById("issuesTableWrap");
    const cardsView = document.getElementById("issuesCardsView");
    const toolbar = document.getElementById("seoToolIssuesToolbar");
    const heading = document.getElementById("issuesCardHeading");
    if (wrap) {
        wrap.hidden = true;
        wrap.textContent = "";
    }
    if (toolbar) toolbar.hidden = false;
    if (issuesViewMode === "table") {
        if (tableWrap) tableWrap.hidden = false;
        if (cardsView) cardsView.hidden = true;
        if (heading) heading.textContent = ISSUES_CARD_HEADING_TABLE;
    } else {
        if (tableWrap) tableWrap.hidden = true;
        if (cardsView) cardsView.hidden = false;
        if (heading) heading.textContent = ISSUES_CARD_HEADING_CARDS;
    }
}

function badgeClassForRatio(done, total) {
    if (total <= 0) return "neutral";
    if (done >= total) return "ok";
    const r = done / total;
    if (r >= 0.65) return "mid";
    return "bad";
}

const NORM_CAT_TO_NAV_KEY = {
    gsc_indexing: "indexability",
    website: "crawlability",
    sitemap: "indexability",
    robots: "crawlability",
    schema: "structured_data",
    semantic_markup: "structured_data",
    images: "onpage",
    video: "onpage",
    site_speed: "performance",
    https: "security_http",
    response_code: "crawlability",
    onpage: "onpage",
    mobile: "ux_mobile",
    international: "onpage",
    other: "crawlability",
};

const TECH_NAV_KEYS = (window.TechSidebarV2 && window.TechSidebarV2.NAV_ORDER
    ? window.TechSidebarV2.NAV_ORDER.filter((k) => k !== "overview" && k !== "history")
    : null) || [
    "priority",
    "indexability",
    "crawlability",
    "onpage",
    "internal_links",
    "performance",
    "structured_data",
    "security_http",
    "ux_mobile",
    "gsc",
];

const PASSED_CHECK_DISPLAY = {
    https_protocol: "HTTPS redirect passed",
    robots_txt: "robots.txt exists",
    sitemap_xml: "XML sitemap found",
    http_status: "no 5xx found",
    internal_links: "internal links OK",
    title_meta: "title & meta OK",
    image_alt: "images alt passed",
    html_lang: "html lang found",
    gsc_manual_action: "no manual action",
    gsc_security: "no security issue",
    canonical_valid: "canonical valid",
    mobile_viewport: "mobile viewport found",
    schema_valid: "schema valid",
    overall_clean: "overall technical clean",
};

function normCatToNavKey(cat) {
    if (window.TechSidebarV2 && typeof window.TechSidebarV2.legacyCatToGroup === "function") {
        return window.TechSidebarV2.legacyCatToGroup(cat);
    }
    const c = String(cat || "").toLowerCase();
    return NORM_CAT_TO_NAV_KEY[c] || "crawlability";
}

function normalizedIssueNavBucket(issue) {
    if (window.TechSidebarV2 && typeof window.TechSidebarV2.issueNavGroup === "function") {
        return window.TechSidebarV2.issueNavGroup(issue, issueSidebarBucket);
    }
    if (!issue || typeof issue !== "object") return "crawlability";
    if (issue.category) return normCatToNavKey(issue.category);
    const bucket = issueSidebarBucket(issue);
    if (window.TechSidebarV2 && typeof window.TechSidebarV2.normalizeTechTabKey === "function") {
        return window.TechSidebarV2.normalizeTechTabKey(bucket);
    }
    return bucket;
}

function catalogItemsForNavGroup(group) {
    const g = normalizeTechTabKey(group);
    const pillars =
        window.TechSidebarV2 && typeof window.TechSidebarV2.navGroupCatalogPillars === "function"
            ? window.TechSidebarV2.navGroupCatalogPillars(g)
            : [g];
    let items = [];
    pillars.forEach((p) => {
        const rows = pillarCatalogItems(p);
        if (rows && rows.length) items = items.concat(rows);
    });
    return items;
}

function emptyNavStatRow() {
    return { open: 0, total: 0, critical: 0, high: 0, passed: 0, worst: "passed" };
}

function buildNavStatsFromPayload(payload) {
    const stats = {};
    TECH_NAV_KEYS.forEach((k) => {
        stats[k] = emptyNavStatRow();
    });
    if (!payload || typeof payload !== "object") return stats;

    if (window.TechDashboardV2 && typeof window.TechDashboardV2.resolveNavSummaries === "function") {
        const v2stats = window.TechDashboardV2.resolveNavSummaries(payload);
        if (v2stats) {
            Object.keys(v2stats).forEach((key) => {
                if (key === "passed") return;
                stats[key] = Object.assign(emptyNavStatRow(), v2stats[key]);
            });
            stats.priority = stats.priority || emptyNavStatRow();
            if (!stats.priority.open) {
                const pri = resolvePriorityFixes(payload);
                stats.priority.open = pri.length;
            }
            return stats;
        }
    }

    const norm = Array.isArray(payload.normalized_issues) && payload.normalized_issues.length
        ? payload.normalized_issues
        : cachedNormalizedIssues.length
          ? cachedNormalizedIssues
          : resolveNormalizedIssues(payload);

    const openTypesByKey = {};
    norm.forEach((issue) => {
        if (!issue || typeof issue !== "object") return;
        const sev = String(issue.severity || "").toLowerCase();
        if (sev === "passed") return;
        const key = normalizedIssueNavBucket(issue);
        const row = stats[key] || emptyNavStatRow();
        const tkey = issueNavTypeKey(issue);
        if (!openTypesByKey[key]) openTypesByKey[key] = new Set();
        openTypesByKey[key].add(tkey);
        if (sev === "critical") row.critical += 1;
        else if (sev === "warning" || sev === "high") row.high += 1;
        else if (sev === "medium") row.medium = (row.medium || 0) + 1;
        else if (sev === "opportunity" || sev === "low") row.low = (row.low || 0) + 1;
        const rank = { critical: 6, warning: 5, high: 5, medium: 4, opportunity: 3, low: 3, passed: 1 };
        if ((rank[sev] || 0) > (rank[row.worst] || 0)) row.worst = sev;
        stats[key] = row;
    });

    Object.keys(openTypesByKey).forEach((key) => {
        if (!stats[key]) stats[key] = emptyNavStatRow();
        stats[key].open = openTypesByKey[key].size;
    });

    if (!Object.keys(openTypesByKey).length) {
        const legacy = Array.isArray(payload.issues)
            ? payload.issues.filter((it) => it && !it.suppressed)
            : [];
        const grouped = {};
        legacy.forEach((it) => {
            const key = normalizedIssueNavBucket(it);
            if (!grouped[key]) grouped[key] = new Set();
            grouped[key].add(String(it.type || "issue"));
        });
        Object.keys(grouped).forEach((key) => {
            if (!stats[key]) stats[key] = emptyNavStatRow();
            stats[key].open = grouped[key].size;
        });
    }

    const passedChecks = Array.isArray(payload.passed_checks) ? payload.passed_checks : [];
    passedChecks.forEach((p) => {
        if (!p || typeof p !== "object") return;
        const key = normalizedIssueNavBucket({ category: p.category });
        const row = stats[key] || emptyNavStatRow();
        row.passed += 1;
        stats[key] = row;
    });

    stats.passed = stats.passed || emptyNavStatRow();
    stats.passed.open = passedChecks.length;

    const priorityFixes = resolvePriorityFixes(payload);
    stats.priority = stats.priority || emptyNavStatRow();
    stats.priority.open = priorityFixes.length || norm.filter((i) => {
        const s = String(i.severity || "").toLowerCase();
        return s === "critical" || s === "high";
    }).length;

    return stats;
}

function navStatBadgeClass(row) {
    if (window.TechSidebarV2 && typeof window.TechSidebarV2.navStatBadgeClass === "function") {
        return window.TechSidebarV2.navStatBadgeClass(row);
    }
    const open = row.open || 0;
    if (open === 0) return "ok";
    if ((row.critical || 0) > 0 || row.worst === "critical") return "bad";
    if ((row.high || 0) > 0 || row.worst === "high") return "mid";
    return "mid";
}

function renderNavStatElement(el, row, navKey) {
    const open = row.open || 0;
    const crit = row.critical || 0;
    const hi = row.high || 0;
    const passed = row.passed || 0;
    const cls = navStatBadgeClass(row);
    el.className = "tech-nav-stats " + cls;
    el.innerHTML = '<span class="tech-nav-count-pill ' + cls + '">' + String(open) + "</span>";
    const tips = [];
    tips.push(open + " loại issue mở");
    if (crit) tips.push(crit + " critical");
    if (hi) tips.push(hi + " high");
    if (passed) tips.push(passed + " passed");
    if (row.total) tips.push(row.total + " tổng ghi nhận");
    const catN = pillarCatalogItems(navKey || "");
    if (catN) tips.push("Checklist tham chiếu: " + catN + " mục");
    el.title = tips.join(" · ");
}

function updateTechSidebarFromPayload(payload) {
    const stats = payload ? buildNavStatsFromPayload(payload) : null;
    const badgeKeys = TECH_NAV_KEYS.slice();
    badgeKeys.forEach((key) => {
        const el = document.querySelector('[data-tech-badge="' + key + '"]');
        if (!el) return;
        if (!stats) {
            el.className = "tech-nav-stats neutral";
            el.innerHTML = '<span class="tech-nav-count-pill neutral">0</span>';
            el.removeAttribute("title");
            return;
        }
        if (key === "passed") {
            const n = (stats.passed && stats.passed.open) || 0;
            el.className = "tech-nav-stats ok";
            el.innerHTML = '<span class="tech-nav-count-pill ok">' + String(n) + "</span>";
            return;
        }
        renderNavStatElement(el, stats[key] || emptyNavStatRow(), key);
    });
    syncCategoryChipsBar(payload, stats);
    renderOverviewPassedPreview(payload);
}

function renderOverviewPassedPreview(payload) {
    if (window.TechDashboardV2 && window.TechDashboardV2.hasV2(payload)) {
        const sec = document.getElementById("seoToolOverviewPassedSection");
        if (sec) sec.hidden = true;
        if (window.TechDashboardV2.renderPassedCollapsible) {
            window.TechDashboardV2.renderPassedCollapsible(payload);
        }
        return;
    }
    const collapsible = document.getElementById("seoToolOverviewPassedCollapsible");
    if (collapsible) collapsible.hidden = true;
    const sec = document.getElementById("seoToolOverviewPassedSection");
    const list = document.getElementById("seoToolOverviewPassedList");
    const countEl = document.getElementById("seoToolOverviewPassedCount");
    if (!sec || !list) return;
    const checks = Array.isArray(payload && payload.passed_checks) ? payload.passed_checks : [];
    if (!checks.length) {
        sec.hidden = true;
        list.textContent = "";
        return;
    }
    sec.hidden = false;
    if (countEl) countEl.textContent = String(checks.length);
    list.textContent = "";
    checks.slice(0, 5).forEach((chk) => {
        if (!chk || typeof chk !== "object") return;
        const li = document.createElement("li");
        li.className = "seo-tool-overview-passed-item";
        li.textContent = "✓ " + passedCheckLabel(chk);
        list.appendChild(li);
    });
}

function renderSidebarPassedPreview(payload) {
    renderOverviewPassedPreview(payload);
}

function buildPassedCheckCard(chk) {
    const card = document.createElement("article");
    card.className = "seo-tool-issue-card seo-tool-passed-card";
    const head = document.createElement("div");
    head.className = "seo-tool-issue-card-head";
    head.innerHTML = '<span class="saas-badge saas-sev-passed">PASSED</span>';
    const title = document.createElement("h4");
    title.className = "seo-tool-issue-card-title";
    title.textContent = passedCheckLabel(chk);
    const desc = document.createElement("p");
    desc.className = "seo-tool-issue-card-desc";
    desc.textContent = chk.description || "—";
    const meta = document.createElement("p");
    meta.className = "seo-tool-issue-card-meta";
    meta.textContent = (chk.category || "other").replace(/_/g, " ");
    card.appendChild(head);
    card.appendChild(title);
    card.appendChild(desc);
    card.appendChild(meta);
    return card;
}

function renderPassedTabContent(payload) {
    const panel = document.getElementById("techContentPassed");
    const grid = document.getElementById("techPassedCardsGrid");
    const emptyEl = document.getElementById("techPassedEmpty");
    const countEl = document.getElementById("techPassedCount");
    if (!panel || !grid) return;
    const checks = Array.isArray(payload && payload.passed_checks) ? payload.passed_checks : [];
    grid.textContent = "";
    if (countEl) countEl.textContent = checks.length + " mục passed";
    if (!checks.length) {
        if (emptyEl) emptyEl.hidden = false;
        return;
    }
    if (emptyEl) emptyEl.hidden = true;
    checks.forEach((chk) => {
        if (!chk || typeof chk !== "object") return;
        grid.appendChild(buildPassedCheckCard(chk));
    });
}

function updateTechContentHeader() {
    const hdr = document.getElementById("techContentHeader");
    const titleEl = document.getElementById("techContentTitle");
    const subEl = document.getElementById("techContentSubtitle");
    if (!hdr || !titleEl) return;
    const tab = normalizeTechTabKey(activeTechTab);
    const label = TECH_TAB_LABELS[tab] || tab;
    titleEl.textContent = label;
    if (subEl) {
        const groupUi = window.TechSidebarV2 && window.TechSidebarV2.GROUP_UI;
        if (tab === "overview") {
            subEl.textContent = "Health score, lỗi ưu tiên và tóm tắt GSC.";
        } else if (tab === "priority") {
            const n = countIssuesForTab("priority", cachedNormalizedIssues);
            subEl.textContent = n + " lỗi cần xử lý trước theo mức ưu tiên.";
        } else if (tab === "passed") {
            const n = Array.isArray(cachedTechnicalPayload && cachedTechnicalPayload.passed_checks)
                ? cachedTechnicalPayload.passed_checks.length
                : 0;
            subEl.textContent = n + " kiểm tra đã đạt.";
        } else if (tab === "history") {
            subEl.textContent = "Các lần quét technical gần đây.";
        } else if (isIssueCategoryTab(tab)) {
            const n = countIssuesForTab(tab, cachedNormalizedIssues);
            const hint = groupUi && groupUi[tab] ? groupUi[tab].sub : "";
            subEl.textContent = (hint ? hint + " — " : "") + n + " lỗi trong nhóm này.";
        } else {
            subEl.textContent = "";
        }
    }
    hdr.hidden = !cachedTechnicalPayload;
}

function syncMobileNavSelect() {
    const sel = document.getElementById("techNavMobileSelect");
    if (!sel) return;
    const tab = normalizeTechTabKey(activeTechTab);
    if (sel.value !== tab) sel.value = tab;
}

function populateMobileNavSelect() {
    const sel = document.getElementById("techNavMobileSelect");
    if (!sel || sel.dataset.populated === "1") return;
    sel.dataset.populated = "1";
    const order = (window.TechSidebarV2 && window.TechSidebarV2.NAV_ORDER) || [
        "overview",
        "priority",
        "indexability",
        "crawlability",
        "onpage",
        "internal_links",
        "performance",
        "structured_data",
        "security_http",
        "ux_mobile",
        "gsc",
        "history",
    ];
    sel.textContent = "";
    order.forEach((key) => {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = TECH_TAB_LABELS[key] || key;
        sel.appendChild(opt);
    });
    sel.addEventListener("change", () => {
        navigateTechTab(sel.value || "overview");
    });
}

function mountTechResultsInRightPanel() {
    const panel = document.querySelector(".tech-right-panel");
    if (!panel || panel.dataset.resultsMounted === "1") return;
    const contentHdr = document.getElementById("techContentHeader");
    const resultsHdr = document.getElementById("seoToolResultsHeader");
    const overview = document.getElementById("seoToolResultsOverview");
    const chipsBar = document.getElementById("techCategoryChipsBar");
    const mobileSel = document.getElementById("techNavMobileSelect");
    if (resultsHdr && resultsHdr.parentElement !== panel) {
        panel.insertBefore(resultsHdr, panel.firstChild);
    }
    if (overview && overview.parentElement !== panel) {
        const after = contentHdr ? contentHdr.nextElementSibling : panel.children[1];
        panel.insertBefore(overview, after || null);
    }
    if (mobileSel && chipsBar && mobileSel.parentElement !== chipsBar) {
        chipsBar.insertBefore(mobileSel, chipsBar.firstChild);
    }
    panel.dataset.resultsMounted = "1";
}

function issueMatchesChecklistItem(issue, checklistText) {
    const hay = [
        issue.title,
        issue.description,
        issue._issue_type,
        issue.id,
    ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
    const needle = String(checklistText || "").toLowerCase();
    if (!hay || !needle) return false;
    const words = needle.split(/[\s,;–—\-/()]+/).filter((w) => w.length > 3);
    let hits = 0;
    words.forEach((w) => {
        if (hay.includes(w)) hits += 1;
    });
    return hits >= 2 || hay.includes(needle.slice(0, 24));
}

function getIssuesForTab(tab) {
    const all = Array.isArray(cachedNormalizedIssues) ? cachedNormalizedIssues : [];
    const nonPassed = all.filter((i) => String(i.severity || "").toLowerCase() !== "passed");
    const t = normalizeTechTabKey(tab);
    if (t === "priority") {
        const fixes = cachedTechnicalPayload ? resolvePriorityFixes(cachedTechnicalPayload) : [];
        if (fixes.length) {
            const ids = new Set(fixes.map((f) => String(f.id || "")));
            const types = new Set(fixes.map((f) => String(f.id || f.type || "")));
            const matched = nonPassed.filter(
                (i) => ids.has(String(i.id)) || types.has(String(i.type || i.id))
            );
            if (matched.length) return matched;
        }
        return nonPassed.filter((i) => {
            const s = String(i.severity || "").toLowerCase();
            return s === "critical" || s === "high";
        });
    }
    if (isIssueCategoryTab(t)) {
        return nonPassed.filter((i) => issueMatchesSidebarTab(i, t));
    }
    return nonPassed;
}

function renderCategoryTabExtras(tab) {
    const panel = document.getElementById("techCategoryPanel");
    const statsEl = document.getElementById("techCategoryStats");
    const wrap = document.getElementById("techCategoryChecklistWrap");
    const list = document.getElementById("techCategoryChecklist");
    const titleEl = document.getElementById("techCategoryChecklistTitle");
    const hintEl = document.getElementById("techCategoryChecklistHint");
    if (!panel || !statsEl) return;

    const t = normalizeTechTabKey(tab);
    const showPanel = isIssueCategoryTab(t) || t === "priority";
    if (!showPanel || !cachedTechnicalPayload) {
        panel.hidden = true;
        return;
    }

    panel.hidden = false;
    const tabIssues = getIssuesForTab(t);
    const stats = buildNavStatsFromPayload(cachedTechnicalPayload);
    const row = stats[t] || emptyNavStatRow();
    const label = TECH_TAB_LABELS[t] || t;

    let crit = 0;
    let hi = 0;
    let med = 0;
    let lo = 0;
    tabIssues.forEach((i) => {
        const s = String(i.severity || "").toLowerCase();
        if (s === "critical") crit += 1;
        else if (s === "high") hi += 1;
        else if (s === "medium") med += 1;
        else if (s === "low") lo += 1;
    });

    statsEl.innerHTML =
        '<div class="tech-category-stat-grid">' +
        '<article class="tech-category-stat"><span>Tổng lỗi</span><strong>' +
        tabIssues.length +
        "</strong></article>" +
        '<article class="tech-category-stat crit"><span>Critical</span><strong>' +
        crit +
        "</strong></article>" +
        '<article class="tech-category-stat high"><span>High</span><strong>' +
        hi +
        "</strong></article>" +
        '<article class="tech-category-stat med"><span>Medium</span><strong>' +
        med +
        "</strong></article>" +
        '<article class="tech-category-stat low"><span>Low</span><strong>' +
        lo +
        "</strong></article>" +
        '<article class="tech-category-stat"><span>Loại issue</span><strong>' +
        (row.open || tabIssues.length) +
        "</strong></article>" +
        "</div>";

    if (!wrap || !list || t === "priority") {
        if (wrap) wrap.hidden = true;
        return;
    }

    const catalogItems = catalogItemsForNavGroup(t);
    if (!catalogItems.length) {
        wrap.hidden = true;
        return;
    }

    wrap.hidden = false;
    if (titleEl) titleEl.textContent = "Checklist " + label + " (" + catalogItems.length + " tiêu chí)";
    if (hintEl) {
        hintEl.textContent =
            "Các mục có lỗi phát hiện được đánh dấu đỏ — chỉ hiện issue thực tế từ lần quét bên dưới.";
    }
    list.textContent = "";
    catalogItems.forEach((item, idx) => {
        const text = typeof item === "string" ? item : item.title_vi || item.title || String(item);
        const li = document.createElement("li");
        const detected = tabIssues.some((iss) => issueMatchesChecklistItem(iss, text));
        li.className = "tech-category-checklist-item" + (detected ? " is-detected" : " is-clear");
        li.innerHTML =
            '<span class="tech-category-checklist-idx">' +
            (idx + 1) +
            "</span>" +
            '<span class="tech-category-checklist-text">' +
            escHtml(text) +
            "</span>" +
            '<span class="tech-category-checklist-status">' +
            (detected ? "Có lỗi" : "OK / chưa phát hiện") +
            "</span>";
        list.appendChild(li);
    });
}

