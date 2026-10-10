#!/usr/bin/env node
/**
 * Headless UI contract tests for Technical Health Dashboard v2.
 * Run: node tests/test_dashboard_v2_ui.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");
const FIXTURES = path.join(__dirname, "fixtures");

function readJson(name) {
    return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf8"));
}

function loadScript(file) {
    return fs.readFileSync(path.join(ROOT, file), "utf8");
}

/** Minimal DOM for dashboard + sidebar modules. */
function createDom() {
    const elements = new Map();
    const body = makeEl("body");
    body.classList = makeClassList(body);
    elements.set("body", body);

    const ids = [
        "saasHealthScoreValue",
        "saasCountCritical",
        "saasCountWarning",
        "saasCountOpportunity",
        "saasCountPassed",
        "saasPagesCrawled",
        "seoToolUrlsScannedStat",
        "saasScanMode",
        "saasHealthScoreHint",
        "seoToolOverviewPassedCollapsible",
        "seoToolOverviewPassedCollapsibleBody",
        "seoToolOverviewPassedCollapsibleCount",
        "seoToolOverviewPassedCollapsibleToggle",
        "seoToolPriorityFixesSection",
        "seoToolPriorityFixesList",
        "techIssueDrawer",
        "techIssueDrawerBackdrop",
        "techIssueDrawerTitle",
        "techIssueDrawerSeverity",
        "techIssueDrawerConfidence",
        "techIssueDrawerSource",
        "techIssueDrawerCategory",
        "techIssueDrawerWhy",
        "techIssueDrawerFix",
        "techIssueDrawerWhat",
        "techIssueDrawerGsc",
        "techIssueDrawerGscSection",
        "techIssueDrawerUrls",
        "techIssueDrawerEvidence",
        "techIssueDrawerClose",
        "seoToolFilterSource",
        "seoToolFilterConfidence",
        "seoToolFilterCategory",
        "techDashPriorityTbody",
        "techDashPriorityEmpty",
        "techDashPriorityCount",
        "seoToolPriorityFixesSection",
        "techMaxPages",
        "btnOpenLogin",
    ];

    ids.forEach((id) => {
        const el = makeEl(id);
        el.id = id;
        if (id.startsWith("seoToolFilter") || id === "techMaxPages") {
            el.value = id === "techMaxPages" ? "25" : "all";
        }
        if (id === "techIssueDrawerEvidence" || id === "techIssueDrawerUrls") {
            Object.defineProperty(el, "innerHTML", {
                configurable: true,
                enumerable: true,
                set(v) {
                    el._html = v == null ? "" : String(v);
                },
                get() {
                    return el._html || "";
                },
            });
        }
        if (id === "techIssueDrawerBackdrop") el.hidden = true;
        if (id === "seoToolOverviewPassedCollapsible") el.hidden = true;
        if (id === "techIssueDrawer") {
            el.classList = makeClassList(el);
        }
        elements.set(id, el);
        body.appendChild(el);
    });

    // Nav badges for beginner tabs + fine-grained groups used in tests
    const navGroups = [
        "priority",
        "index_crawl",
        "onpage",
        "perf_security",
        "gsc",
        "indexability",
        "crawlability",
        "internal_links",
        "performance",
        "structured_data",
        "security_http",
        "ux_mobile",
    ];
    navGroups.forEach((g) => {
        const el = makeEl("badge-" + g);
        el.setAttribute("data-tech-badge", g);
        el.className = "tech-nav-stats neutral";
        el.innerHTML = '<span class="tech-nav-count-pill neutral">0</span>';
        elements.set("badge-" + g, el);
        body.appendChild(el);
    });

    function makeClassList(el) {
        const s = new Set(["seo-tool-page"]);
        return {
            add() {
                [].slice.call(arguments).forEach((c) => s.add(c));
                if (el) el.className = [...s].join(" ");
            },
            remove() {
                [].slice.call(arguments).forEach((c) => s.delete(c));
                if (el) el.className = [...s].join(" ");
            },
            toggle(c) {
                if (s.has(c)) s.delete(c);
                else s.add(c);
                el && (el.className = [...s].join(" "));
                return s.has(c);
            },
            contains(c) {
                return s.has(c);
            },
        };
    }

    function makeEl(tag) {
        return {
            tagName: tag.toUpperCase(),
            id: "",
            hidden: false,
            textContent: "",
            innerHTML: "",
            _html: "",
            className: "",
            classList: makeClassList(null),
            dataset: {},
            style: {},
            children: [],
            attributes: {},
            appendChild(child) {
                this.children.push(child);
                child.parentNode = this;
            },
            setAttribute(k, v) {
                this.attributes[k] = v;
            },
            getAttribute(k) {
                return this.attributes[k];
            },
            addEventListener() {},
            querySelector() {
                return null;
            },
            querySelectorAll() {
                return [];
            },
            parentNode: null,
        };
    }

    const document = {
        body,
        readyState: "complete",
        getElementById(id) {
            return elements.get(id) || null;
        },
        querySelector(sel) {
            if (sel.startsWith('[data-tech-badge="')) {
                const g = sel.match(/data-tech-badge="([^"]+)"/)[1];
                return elements.get("badge-" + g) || null;
            }
            return null;
        },
        querySelectorAll(sel) {
            if (sel === "[data-tech-nav]") return [];
            return [];
        },
        createElement(tag) {
            const el = makeEl(tag);
            el.classList = makeClassList(el);
            if (tag === "div") {
                Object.defineProperty(el, "textContent", {
                    set(v) {
                        this._text = v == null ? "" : String(v);
                    },
                    get() {
                        return this._text || "";
                    },
                });
                Object.defineProperty(el, "innerHTML", {
                    set(v) {
                        this._html = v == null ? "" : String(v);
                    },
                    get() {
                        if (this._html != null) return this._html;
                        const t = this._text || "";
                        return t
                            .replace(/&/g, "&amp;")
                            .replace(/</g, "&lt;")
                            .replace(/>/g, "&gt;");
                    },
                });
            }
            return el;
        },
        addEventListener() {},
    };

    const window = {
        document,
        TechSidebarV2: null,
        TechDashboardV2: null,
        saasSeverityBadgeClass(sev) {
            const s = String(sev || "").toLowerCase();
            if (s === "critical") return "saas-sev-critical";
            if (s === "warning") return "saas-sev-warning";
            if (s === "opportunity") return "saas-sev-opportunity";
            return "saas-sev-medium";
        },
        localStorage: {
            _d: {},
            getItem(k) {
                return this._d[k] || null;
            },
            setItem(k, v) {
                this._d[k] = v;
            },
        },
        matchMedia() {
            return { matches: true };
        },
        addEventListener() {},
    };
    window.globalThis = window;

    return { window, document, elements, body };
}

function runInContext(code, window) {
    const sandbox = { window, document: window.document, globalThis: window, console };
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox);
    return sandbox;
}

function assert(cond, msg) {
    if (!cond) throw new Error("ASSERT: " + msg);
}

function test(name, fn) {
    try {
        fn();
        console.log("  ✓ " + name);
        return true;
    } catch (e) {
        console.error("  ✗ " + name + " — " + e.message);
        return false;
    }
}

function main() {
    let passed = 0;
    let failed = 0;
    const run = (name, fn) => (test(name, fn) ? passed++ : failed++);

    console.log("\nTechnical Health Dashboard UI tests\n");

    const { window, document, body } = createDom();
    runInContext(loadScript("static/js/seo-tool-sidebar-v2.js"), window);
    runInContext(loadScript("static/js/seo-tool-dashboard-v2.js"), window);

    const TD = window.TechDashboardV2;
    const TS = window.TechSidebarV2;
    const v2Payload = readJson("technical_dashboard_v2_sample.json");
    const legacyPayload = readJson("technical_dashboard_legacy_sample.json");

    run("TechDashboardV2 and TechSidebarV2 exported", () => {
        assert(TD && TS, "modules missing");
        assert(TS.NAV_ORDER.length === 7, "expected 7 nav groups, got " + TS.NAV_ORDER.length);
        assert(TS.NAV_ORDER.join(",") === "overview,priority,index_crawl,onpage,perf_security,gsc,history", "nav order");
        assert(!TS.NAV_ORDER.includes("passed"), "passed should not be in sidebar");
    });

    run("hasV2 detects schema_version", () => {
        assert(TD.hasV2(v2Payload), "v2 payload not detected");
        assert(!TD.hasV2(legacyPayload), "legacy wrongly detected as v2");
        const stub = {
            technical_dashboard_v2: {
                schema_version: 2,
                generated_at: "2026-01-01T00:00:00Z",
                summary: { critical: 0, warning: 0, opportunity: 0, total: 0 },
                issues: [],
                pages_scanned: 0,
            },
        };
        assert(!TD.hasV2(stub), "empty v2 stub should not activate v2 mode");
    });

    run("enrichPayload maps v2 issues to normalized_issues", () => {
        const p = JSON.parse(JSON.stringify(v2Payload));
        TD.enrichPayload(p);
        assert(Array.isArray(p.normalized_issues) && p.normalized_issues.length === 4, "normalized count");
        assert(Array.isArray(p.priority_fixes) && p.priority_fixes.length === 2, "priority_fixes count");
        assert(p.passed_checks.length === 2, "passed_checks mapped");
        assert(body.classList.contains("tech-dash-v2-mode"), "v2 mode class on body");
    });

    run("resolveSummary overview counts", () => {
        const s = TD.resolveSummary(v2Payload);
        assert(s.health_score === 72, "health score");
        assert(s.critical === 1 && s.warning === 2 && s.opportunity === 1, "severity counts");
        assert(s.passed === 2 && s.pages_scanned === 12, "passed/pages");
    });

    run("renderOverviewV2Summary updates DOM cards", () => {
        TD.renderOverviewV2Summary(v2Payload);
        assert(document.getElementById("saasHealthScoreValue").textContent === "72", "score card");
        assert(document.getElementById("saasCountCritical").textContent === "1", "critical");
        assert(document.getElementById("saasCountWarning").textContent === "2", "warning");
        assert(document.getElementById("saasCountOpportunity").textContent === "1", "opportunity");
        assert(document.getElementById("saasCountPassed").textContent === "2", "passed");
        assert(document.getElementById("saasPagesCrawled").textContent === "12", "pages crawled");
    });

    run("resolveNavSummaries maps nav_group badges", () => {
        const stats = TD.resolveNavSummaries(v2Payload);
        assert(stats.crawlability.open === 1, "crawlability badge");
        assert(stats.onpage.open === 2, "onpage badge");
        assert(stats.internal_links.open === 1, "internal_links badge");
        assert(stats.index_crawl.open === 2, "index_crawl rollup");
        assert(stats.perf_security.open === 0, "perf_security empty");
        assert(stats.priority.open === 2, "priority badge");
        assert(stats.security_http.open === 0, "security_http empty");
    });

    run("issueNavGroup routes internal_links and security", () => {
        const issue = v2Payload.technical_dashboard_v2.issues[2];
        assert(TS.issueNavGroupFine(issue) === "internal_links", "internal link fine group");
        assert(TS.issueNavGroup(issue) === "index_crawl", "internal link folded group");
        assert(TS.normalizeTechTabKey("passed") === "overview", "passed → overview");
        assert(TS.normalizeTechTabKey("security_ux") === "perf_security", "legacy security_ux");
    });

    run("resolvePriorityIssues from priority_issues", () => {
        const pri = TD.resolvePriorityIssues(v2Payload);
        assert(pri.length === 2, "priority count");
        assert(pri[0].title.includes("Robots"), "top priority title");
        assert(pri[0].priority_score === 98, "priority score");
    });

    run("issueMatchesV2Filters source and confidence", () => {
        const issue = v2Payload.technical_dashboard_v2.issues[3];
        assert(TD.issueMatchesV2Filters(issue, { source: "hybrid", confidence: "all" }), "hybrid match");
        assert(!TD.issueMatchesV2Filters(issue, { source: "crawl", confidence: "all" }), "crawl mismatch");
        assert(TD.issueMatchesV2Filters(issue, { source: "all", confidence: "medium" }), "medium conf");
        assert(!TD.issueMatchesV2Filters(issue, { source: "all", confidence: "high" }), "not high conf");
    });

    run("openIssueDrawer fills all fields", () => {
        const issue = TD.v2IssueToNormalized(v2Payload.technical_dashboard_v2.issues[0]);
        TD.openIssueDrawer(issue);
        assert(document.getElementById("techIssueDrawerTitle").textContent.includes("Robots"), "title");
        assert(document.getElementById("techIssueDrawerWhat").textContent.length > 5, "what section");
        assert(document.getElementById("techIssueDrawerWhy").textContent.includes("Google"), "why");
        assert(document.getElementById("techIssueDrawerFix").textContent.includes("robots.txt"), "fix");
        assert(document.getElementById("techIssueDrawerSource").textContent === "Quét website", "source vi");
        assert(document.getElementById("techIssueDrawerConfidence").textContent === "95%", "confidence");
        const evHtml = document.getElementById("techIssueDrawerEvidence").innerHTML;
        assert(evHtml.length > 10, "evidence html present");
        assert(!evHtml.includes("JSON.stringify") && !evHtml.includes('{"'), "no raw json in evidence");
        assert(document.getElementById("techIssueDrawer").classList.contains("is-open"), "drawer open");
        TD.closeIssueDrawer();
        assert(!document.getElementById("techIssueDrawer").classList.contains("is-open"), "drawer closed");
    });

    run("getTopPriorityIssues returns max 5 sorted by score", () => {
        const dash = v2Payload.technical_dashboard_v2;
        const top = TD.getTopPriorityIssues(dash, 5);
        assert(top.length <= 5, "max 5");
        assert(top[0].priority_score >= (top[1] && top[1].priority_score || 0), "sorted by score");
    });

    run("renderPassedCollapsible shows passed checks", () => {
        TD.renderPassedCollapsible(v2Payload);
        const sec = document.getElementById("seoToolOverviewPassedCollapsible");
        assert(sec.hidden, "collapsible hidden on overview");
        assert(document.getElementById("seoToolOverviewPassedCollapsibleCount").textContent === "2", "count");
        assert(document.getElementById("seoToolOverviewPassedCollapsibleBody").children.length === 2, "items");
    });

    run("legacy payload does not enable v2 mode", () => {
        const p = JSON.parse(JSON.stringify(legacyPayload));
        body.classList.remove("tech-dash-v2-mode");
        TD.enrichPayload(p);
        assert(!body.classList.contains("tech-dash-v2-mode"), "no v2 class");
        assert(!TD.resolveSummary(p), "no v2 summary");
    });

    run("filterIssuesByGroup routes issues to correct sidebar tab", () => {
        const dash = TD.getDashboardForRender(v2Payload);
        const crawl = TD.filterIssuesByGroup(dash, "crawlability");
        const onpage = TD.filterIssuesByGroup(dash, "onpage");
        const internal = TD.filterIssuesByGroup(dash, "internal_links");
        const indexCrawl = TD.filterIssuesByGroup(dash, "index_crawl");
        assert(crawl.length === 1 && crawl[0].issue_type === "robots_disallow_all", "crawlability");
        assert(onpage.length === 2, "onpage count");
        assert(internal.length === 1 && internal[0].issue_type === "broken_internal_link", "internal_links");
        assert(indexCrawl.length === 2, "index_crawl includes crawl + internal");
        assert(
            !onpage.some((i) => i.issue_type === "robots_disallow_all"),
            "onpage must not include crawlability issue"
        );
        assert(
            !crawl.some((i) => i.issue_type === "broken_internal_link"),
            "fine crawlability must not include internal_links"
        );
    });

    run("issueMatchesSidebarTab respects nav_group and category", () => {
        const issues = v2Payload.technical_dashboard_v2.issues;
        assert(TD.issueMatchesSidebarTab(issues[0], "crawlability"), "robots → crawlability");
        assert(TD.issueMatchesSidebarTab(issues[1], "onpage"), "title → onpage");
        assert(!TD.issueMatchesSidebarTab(issues[1], "gsc"), "onpage not gsc");
        const hybridOnpage = issues[3];
        assert(TD.issueMatchesSidebarTab(hybridOnpage, "onpage"), "hybrid onpage stays onpage");
    });

    run("getDash prefers technical_dashboard_v3 when present", () => {
        const p = JSON.parse(JSON.stringify(v2Payload));
        p.technical_dashboard_v3 = {
            schema_version: 3,
            issues: [{ issue_id: "v3-only", nav_group: "performance", severity: "warning" }],
            nav_group_summaries: [{ group: "performance", open_issues: 1, worst_severity: "warning" }],
            summary: { total: 1 },
        };
        const dash = TD.getDash(p);
        assert(dash.schema_version === 3, "v3 selected");
        assert(dash.issues[0].issue_id === "v3-only", "v3 issues used");
        assert(TD.dashSchemaVersion(p) === 3, "schema version helper");
    });

    run("TAB_LABELS use Vietnamese SaaS labels", () => {
        assert(TS.TAB_LABELS.priority === "Việc cần sửa", "priority label");
        assert(TS.TAB_LABELS.index_crawl === "Index & Crawl", "index_crawl label");
        assert(TS.TAB_LABELS.indexability === "Index & Crawl", "indexability alias");
        assert(TS.TAB_LABELS.gsc === "GSC", "gsc label");
        assert(TS.TAB_LABELS.history === "Lịch sử", "history label");
    });

    run("legacyCatToGroup maps sitemap/robots to sidebar tabs", () => {
        assert(TS.legacyCatToGroup("sitemap") === "indexability", "sitemap");
        assert(TS.legacyCatToGroup("robots") === "crawlability", "robots");
        assert(TS.issueNavGroupFine({ category: "sitemap" }) === "indexability", "fine sitemap");
        assert(TS.issueNavGroup({ category: "sitemap" }) === "index_crawl", "category sitemap folded");
    });

    run("resolveGscViewState crawl_only when GSC disabled", () => {
        const state = TD.resolveGscViewState(legacyPayload);
        assert(state.status === "crawl_only" || state.status === "not_connected", "crawl fallback");
        assert(!state.hasMetrics, "no fake metrics");
    });

    run("buildGscLowCtrRows only from ctr_opportunity", () => {
        const payload = {
            gsc_summary: { enabled: true, connected: true, property: "https://example.com/" },
            gsc_opportunities: [
                {
                    type: "ctr_opportunity",
                    url: "https://example.com/a",
                    impressions: 500,
                    clicks: 2,
                    ctr: 0.004,
                    position: 8.2,
                },
                {
                    type: "high_impression_technical_issue",
                    url: "https://example.com/b",
                    impressions: 300,
                    issue_type: "missing_title",
                },
            ],
        };
        const rows = TD.buildGscLowCtrRows(TD.resolveGscViewState(payload));
        assert(rows.length === 1, "only ctr rows");
        assert(rows[0].url.includes("example.com/a"), "ctr url");
        assert(rows[0].impressions === 500, "impressions");
    });

    run("resolveGscViewState shows quota and permission states", () => {
        const quota = TD.resolveGscViewState({
            gsc_summary: {
                enabled: true,
                connected: true,
                property: "sc-domain:example.com",
                quota_exceeded: true,
                partial_data: true,
            },
            gsc_intelligence_summary: { enabled: true, quota_exceeded: true },
        });
        assert(quota.status === "quota", "quota status");
        const perm = TD.resolveGscViewState({
            gsc_summary: {
                enabled: true,
                connected: true,
                errors: ["403 Permission denied for property"],
            },
        });
        assert(perm.status === "permission", "permission status");
    });

    run("getMaxPages reads input", () => {
        document.getElementById("techMaxPages").value = "50";
        assert(TD.getMaxPages() === 50, "max pages");
        document.getElementById("techMaxPages").value = "9999";
        assert(TD.getMaxPages() === 500, "max cap 500");
    });

    // CSS sanity: drawer width uses min(440px, 100vw)
    run("drawer CSS uses responsive width", () => {
        const css = fs.readFileSync(path.join(ROOT, "static/css/seo-tool-dashboard-v2.css"), "utf8");
        assert(css.includes("min(440px, 100vw)"), "desktop drawer width");
        assert(css.includes("width: 100vw") && css.includes("@media (max-width: 1024px)"), "mobile full width");
        assert(css.includes(".tech-nav-row[data-tech-nav=\"passed\"]"), "passed hidden from sidebar");
        assert(!css.includes('.seo-tool-gsc-card {\n    display: none'), "must not hide GSC card");
        const dashJs = fs.readFileSync(path.join(ROOT, "static/js/seo-tool-dashboard-v2.js"), "utf8");
        assert(dashJs.includes("Issue xác nhận từ GSC"), "GSC issues heading preserved");
        assert(dashJs.includes("buildExplorerIssueCard(issue)"), "GSC issues keep original cards");
        assert(!dashJs.includes('gscCard.hidden = true'), "must not hide GSC connect card in JS");
    });

    // Template wiring checks
    run("seo_tool.html includes v2 assets and drawer markup", () => {
        const html = fs.readFileSync(path.join(ROOT, "templates/seo_tool.html"), "utf8");
        assert(html.includes("seo-tool-dashboard-v2.js"), "dashboard js linked");
        assert(html.includes("seo-tool-dashboard-v2.css"), "dashboard css linked");
        assert(html.includes("techIssueDrawer"), "drawer markup");
        assert(html.includes("data-tech-nav=\"index_crawl\""), "index_crawl nav");
        assert(html.includes("data-tech-nav=\"perf_security\""), "perf_security nav");
        assert(html.includes("data-tech-nav=\"onpage\""), "onpage nav");
        assert(!html.includes('data-tech-nav="security_http"'), "fine security_http nav removed");
        assert(!html.includes('data-tech-nav="ux_mobile"'), "fine ux_mobile nav removed");
        assert(!html.includes('data-tech-nav="passed"'), "passed nav removed");
        assert(html.includes(">Vấn đề<"), "drawer vấn đề");
        assert(html.includes("Tại sao quan trọng"), "drawer why");
        assert(html.includes(">Evidence<"), "drawer evidence");
        assert(html.includes("URL lỗi"), "drawer urls");
        assert(html.includes("Cách sửa"), "drawer fix");
        assert(html.includes("5 lỗi cần sửa nhất"), "overview top issues");
        assert(html.includes("Xu hướng điểm"), "score trend");
        assert(html.includes("Mức độ"), "issue table severity col");
        assert(html.includes("Xem chi tiết"), "issue table detail col");
        assert(!/seo-tool-gsc-card"\s+hidden/.test(html), "GSC connect card remains visible");
        assert(html.includes('id="btnGoogleApisConnect"'), "GSC connect");
        assert(html.includes('id="btnGoogleApisDisconnect"'), "GSC disconnect");
        assert(html.includes('id="gscSiteSelect"'), "GSC property select");
        assert(html.includes('id="gscDateRangeSelect"'), "GSC 28/90 days");
        assert(html.includes('id="gscInspectionLimitSelect"'), "URL Inspection limit");
        assert(html.includes('id="techContentGsc"'), "GSC tab panel");
        assert(html.includes('id="techGscTabHost"'), "GSC hub host");
        assert(html.includes("saasCountWarning"), "warning stat");
        assert(html.includes("saasCountOpportunity"), "opportunity stat");
        assert(html.includes("seoToolFilterCategory"), "category filter");
        assert(html.includes("authBoxTop"), "auth preserved");
        assert(html.includes("digiseo_top_nav.html"), "top nav preserved");
    });

    run("technical scan uses background job poll", () => {
        const initJs = fs.readFileSync(path.join(ROOT, "static/js/seo_tool/seo-tool-page-init.js"), "utf8");
        assert(initJs.includes("/analyze/technical/jobs"), "start job endpoint");
        assert(initJs.includes("pollTechnicalScanJob"), "poll helper");
        assert(initJs.includes('useSyncFallback'), "404 fallback to sync scan");
        const dashJs = loadScript("static/js/seo-tool-dashboard-v2.js");
        assert(dashJs.includes("function setScanJobProgress"), "job progress helper");
    });

    console.log("\n" + passed + " passed, " + failed + " failed\n");
    process.exit(failed > 0 ? 1 : 0);
}

main();
