/**
 * Technical Analysis sidebar — beginner 7-tab nav
 */
(function (global) {
    "use strict";

    var NAV_ORDER = [
        "overview",
        "priority",
        "index_crawl",
        "onpage",
        "perf_security",
        "gsc",
        "history",
    ];

    var TAB_LABELS = {
        overview: "Tổng quan",
        priority: "Việc cần sửa",
        index_crawl: "Index & Crawl",
        onpage: "On-page",
        perf_security: "Performance & Security",
        gsc: "GSC",
        history: "Lịch sử",
        indexability: "Index & Crawl",
        crawlability: "Index & Crawl",
        internal_links: "Index & Crawl",
        structured_data: "On-page",
        ux_mobile: "On-page",
        performance: "Performance & Security",
        security_http: "Performance & Security",
    };

    var TAB_CHILDREN = {
        index_crawl: ["indexability", "crawlability", "internal_links"],
        onpage: ["onpage", "structured_data", "ux_mobile"],
        perf_security: ["performance", "security_http"],
    };

    var FINE_TO_SIMPLE = {
        indexability: "index_crawl",
        crawlability: "index_crawl",
        internal_links: "index_crawl",
        structured_data: "onpage",
        ux_mobile: "onpage",
        performance: "perf_security",
        security_http: "perf_security",
        gsc_insights: "gsc",
        audit_history: "history",
    };

    var CATEGORY_TABS = new Set(["priority", "index_crawl", "onpage", "perf_security", "gsc"]);

    var LEGACY_TAB_TO_GROUP = {
        all_issues: "priority",
        recent: "history",
        gsc: "gsc",
        gsc_insights: "gsc",
        website: "index_crawl",
        sitemap: "index_crawl",
        robots: "index_crawl",
        schema: "onpage",
        images: "onpage",
        video: "onpage",
        site_speed: "perf_security",
        https: "perf_security",
        response_code: "index_crawl",
        onpage: "onpage",
        mobile: "onpage",
        international: "onpage",
        other: "index_crawl",
        https_security: "perf_security",
        http_codes: "index_crawl",
        seo_basic: "onpage",
        speed: "perf_security",
        security: "perf_security",
        security_ux: "perf_security",
        errors_console: "gsc",
        url_redirect: "index_crawl",
        passed: "overview",
        indexability: "index_crawl",
        crawlability: "index_crawl",
        internal_links: "index_crawl",
        structured_data: "onpage",
        ux_mobile: "onpage",
        performance: "perf_security",
        security_http: "perf_security",
        history: "history",
        audit_history: "history",
        index_crawl: "index_crawl",
        perf_security: "perf_security",
        priority: "priority",
        overview: "overview",
    };

    var LEGACY_CAT_TO_GROUP = {
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

    var INTERNAL_LINK_TYPES = new Set([
        "broken_internal_link",
        "broken_internal_http_error",
        "orphan_page",
        "redirect_chain",
        "redirect_loop",
        "internal_link_broken",
        "internal_link_dns_error",
        "internal_link_ssl_error",
        "internal_link_timeout",
        "internal_link_forbidden",
        "internal_link_server_error",
    ]);

    var NAV_GROUP_CATALOG_PILLARS = {
        index_crawl: ["sitemap", "robots", "gsc", "website", "response_code"],
        indexability: ["sitemap", "robots", "gsc"],
        crawlability: ["website", "response_code", "robots"],
        onpage: ["onpage", "images", "video", "international", "schema", "mobile"],
        internal_links: ["website"],
        perf_security: ["site_speed", "https"],
        performance: ["site_speed"],
        structured_data: ["schema"],
        security_http: ["https"],
        ux_mobile: ["mobile"],
        gsc: ["gsc"],
    };

    var GROUP_UI = {
        index_crawl: { sub: "Index, crawl, robots, sitemap và liên kết nội bộ." },
        onpage: { sub: "Title, meta, schema và hiển thị trên điện thoại." },
        perf_security: { sub: "Tốc độ, Core Web Vitals, HTTPS và bảo mật." },
        gsc: { sub: "Dữ liệu Google Search Console." },
        priority: { sub: "Các lỗi nên sửa trước." },
        indexability: { sub: "Index Google, sitemap XML, canonical và khả năng lập chỉ mục." },
        crawlability: { sub: "Sitemap & robots.txt, HTTP status, redirect và khả năng crawl." },
        internal_links: { sub: "Liên kết nội bộ hỏng, orphan page và cấu trúc link." },
        performance: { sub: "Tốc độ tải, PageSpeed và tài nguyên nặng." },
        structured_data: { sub: "Schema markup, JSON-LD và rich results." },
        security_http: { sub: "HTTPS, chứng chỉ SSL và mã phản hồi HTTP." },
        ux_mobile: { sub: "Mobile-friendly, viewport và trải nghiệm người dùng." },
    };

    var SVG = {
        overview:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>',
        priority:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        indexability:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
        crawlability:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M12 2v4"/><circle cx="12" cy="12" r="3"/></svg>',
        onpage:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><line x1="16" y1="13" x2="8" y2="13"/></svg>',
        internal_links:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
        performance:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>',
        structured_data:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
        security_http:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
        ux_mobile:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><rect x="5" y="2" width="14" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>',
        gsc:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
        history:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
        index_crawl:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
        perf_security:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
        collapse:
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><polyline points="15 18 9 12 15 6"/></svg>',
    };

    function foldNavGroup(group) {
        var g = String(group || "");
        if (FINE_TO_SIMPLE[g]) return FINE_TO_SIMPLE[g];
        if (LEGACY_TAB_TO_GROUP[g]) return LEGACY_TAB_TO_GROUP[g];
        return g;
    }

    function tabChildren(group) {
        return TAB_CHILDREN[String(group || "")] || null;
    }

    function normalizeTechTabKey(tab) {
        var t = String(tab || "overview");
        if (LEGACY_TAB_TO_GROUP[t]) return LEGACY_TAB_TO_GROUP[t];
        return foldNavGroup(t);
    }

    function isIssueCategoryTab(tab) {
        return CATEGORY_TABS.has(normalizeTechTabKey(tab));
    }

    function legacyCatToGroup(cat) {
        var c = String(cat || "").toLowerCase();
        return LEGACY_CAT_TO_GROUP[c] || "crawlability";
    }

    function issueTypeKey(issue) {
        return String(issue.type || issue._issue_type || issue.issue_type || "").toLowerCase();
    }

    function isIndexabilityIssue(issue) {
        var itype = issueTypeKey(issue);
        if (/^sitemap_/.test(itype) || /^sitemap_contains/.test(itype)) return true;
        if (
            itype === "meta_robots_noindex" ||
            itype === "x_robots_tag_noindex" ||
            itype === "indexability_blocked" ||
            itype === "indexability_signal_conflict" ||
            itype === "robots_meta_noindex_contradiction" ||
            itype === "canonical_points_to_bad_status" ||
            itype === "canonical_points_to_non_indexable" ||
            itype === "canonical_scheme_mismatch" ||
            itype === "canonical_trailing_slash_mismatch" ||
            itype === "page_unlikely_indexed" ||
            itype === "google_may_ignore_canonical"
        ) {
            return true;
        }
        return false;
    }

    function issueNavGroupFine(issue, legacyBucketFn) {
        if (!issue || typeof issue !== "object") return "crawlability";
        var ng = String(issue.nav_group || "").trim();
        if (ng === "gsc_insights") return "gsc";
        if (ng === "audit_history") return "history";
        if (ng && (FINE_TO_SIMPLE[ng] || ng === "onpage" || ng === "gsc" || ng === "priority")) return ng;
        var sk = String(issue.sidebar_key || "").trim();
        if (sk && (FINE_TO_SIMPLE[sk] || sk === "onpage" || sk === "gsc" || sk === "priority")) return sk;
        if (isInternalLinkIssue(issue)) return "internal_links";
        if (isIndexabilityIssue(issue)) return "indexability";
        if (isGscInsightIssue(issue)) return "gsc";
        if (issue.category) return legacyCatToGroup(issue.category);
        if (typeof legacyBucketFn === "function") return legacyBucketFn(issue);
        return "crawlability";
    }

    function issueNavGroup(issue, legacyBucketFn) {
        return foldNavGroup(issueNavGroupFine(issue, legacyBucketFn));
    }

    function isInternalLinkIssue(issue) {
        var type = String(issue.type || issue._issue_type || issue.issue_type || "").toLowerCase();
        if (INTERNAL_LINK_TYPES.has(type)) return true;
        return /internal.*link|broken.*link|orphan/.test(type);
    }

    function isGscInsightIssue(issue) {
        var itype = issueTypeKey(issue);
        if (itype.startsWith("gsc_")) return true;
        if (issue.gsc_badge) return true;
        var cat = String(issue.category || "").toLowerCase();
        if (cat === "gsc_indexing") return false;
        var src = String(issue.source || "").toLowerCase();
        if (src === "gsc") return true;
        if (src === "hybrid" && (issue.gsc_badge || itype.startsWith("gsc_"))) return true;
        return false;
    }

    function navStatBadgeClass(row) {
        var open = row.open || 0;
        if (open === 0) return row.passed ? "ok" : "neutral";
        if ((row.critical || 0) > 0 || row.worst === "critical") return "bad";
        if ((row.high || 0) > 0 || row.worst === "high" || row.worst === "warning") return "warn";
        return "opp";
    }

    function navGroupCatalogPillars(group) {
        return NAV_GROUP_CATALOG_PILLARS[group] || [group];
    }

    function techNavIcon(name) {
        return SVG[name] || SVG.overview;
    }

    function wireSidebarCollapse() {
        var btn = document.getElementById("techSidebarCollapseBtn");
        var page = document.body;
        if (!btn || btn.dataset.wired === "1") return;
        btn.dataset.wired = "1";
        var lsKey = "tool_technical_sidebar_collapsed";
        try {
            if (localStorage.getItem(lsKey) === "1") {
                page.classList.add("tech-sidebar-collapsed");
                btn.setAttribute("aria-expanded", "false");
            }
        } catch (_e) {}
        btn.addEventListener("click", function () {
            var collapsed = page.classList.toggle("tech-sidebar-collapsed");
            btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
            try {
                localStorage.setItem(lsKey, collapsed ? "1" : "0");
            } catch (_e2) {}
        });
    }

    function injectNavIcons() {
        document.querySelectorAll("[data-tech-nav]").forEach(function (btn) {
            var key = btn.getAttribute("data-tech-nav");
            var ico = btn.querySelector(".tech-nav-ico");
            if (!ico || ico.querySelector("svg")) return;
            ico.innerHTML = techNavIcon(key);
        });
    }

    function syncNavLabels() {
        document.querySelectorAll("[data-tech-nav]").forEach(function (btn) {
            var key = btn.getAttribute("data-tech-nav");
            var labelEl = btn.querySelector(".tech-nav-label");
            if (labelEl && TAB_LABELS[key]) labelEl.textContent = TAB_LABELS[key];
        });
    }

    function init() {
        injectNavIcons();
        syncNavLabels();
        wireSidebarCollapse();
    }

    global.TechSidebarV2 = {
        NAV_ORDER: NAV_ORDER,
        TAB_LABELS: TAB_LABELS,
        TAB_CHILDREN: TAB_CHILDREN,
        CATEGORY_TABS: CATEGORY_TABS,
        GROUP_UI: GROUP_UI,
        LEGACY_TAB_TO_GROUP: LEGACY_TAB_TO_GROUP,
        normalizeTechTabKey: normalizeTechTabKey,
        foldNavGroup: foldNavGroup,
        tabChildren: tabChildren,
        isIssueCategoryTab: isIssueCategoryTab,
        issueNavGroup: issueNavGroup,
        issueNavGroupFine: issueNavGroupFine,
        legacyCatToGroup: legacyCatToGroup,
        navStatBadgeClass: navStatBadgeClass,
        navGroupCatalogPillars: navGroupCatalogPillars,
        techNavIcon: techNavIcon,
        syncNavLabels: syncNavLabels,
        issueTypeKey: issueTypeKey,
        init: init,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    }
})(typeof window !== "undefined" ? window : globalThis);
