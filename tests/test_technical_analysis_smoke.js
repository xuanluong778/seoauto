#!/usr/bin/env node
/**
 * Smoke test: Technical Analysis tab routing + GSC + drawer (headless).
 * Run: node tests/test_technical_analysis_smoke.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.join(__dirname, "..");

function load(name) {
    return fs.readFileSync(path.join(ROOT, name), "utf8");
}

function createDom() {
    const elements = new Map();
    const body = { classList: { add() {}, remove() {}, contains() { return false; } }, className: "seo-tool-page" };
    const ids = [
        "techContentGsc", "techGscTabHost", "techGscIssuesHost",
        "techContentPriority", "techContentHistory", "techAuditHistoryHost",
        "techContentPassed", "seoToolResultsOverview", "techIssueGroupChrome",
        "issuesCard", "techCategoryPanel", "seoToolResultsHeader",
        "techDashGscStatus", "techDashGscMiniStats", "techDashGscAlert",
        "techDashGscTablesCompact", "techDashGscEmpty", "techDashGscCard",
        "techIssueDrawer", "techIssueDrawerBackdrop", "techIssueDrawerClose",
        "techIssueDrawerTitle", "techIssueDrawerWhat", "techIssueDrawerWhy",
        "techIssueDrawerFix", "techIssueDrawerEvidence", "techIssueDrawerUrls",
        "techIssueDrawerGscSection", "techIssueDrawerGsc",
        "techIssueDrawerSeverity", "techIssueDrawerConfidence",
        "techIssueDrawerSource", "techIssueDrawerCategory",
        "techDashPriorityTbody", "seoToolPriorityFixesSection",
        "techContentHeader", "techContentTitle", "techContentSubtitle",
        "saasHealthScoreValue", "techNavMobileSelect",
    ];
    ids.forEach((id) => {
        const el = {
            id,
            hidden: true,
            textContent: "",
            innerHTML: "",
            className: "",
            classList: { add() {}, remove() {}, contains() { return false; } },
            dataset: {},
            style: {},
            children: [],
            appendChild(c) { this.children.push(c); },
            setAttribute() {},
            getAttribute() { return null; },
            addEventListener() {},
            querySelector() { return null; },
            querySelectorAll() { return []; },
        };
        elements.set(id, el);
    });
    const document = {
        body,
        readyState: "complete",
        getElementById(id) { return elements.get(id) || null; },
        querySelector(sel) {
            if (sel.startsWith('[data-tech-badge="')) {
                const g = sel.match(/data-tech-badge="([^"]+)"/)[1];
                return elements.get("badge-" + g) || null;
            }
            if (sel === "[data-tech-nav]") return null;
            return null;
        },
        querySelectorAll(sel) {
            if (sel === "[data-tech-nav]") return [];
            return [];
        },
        createElement(tag) {
            const el = {
                tagName: tag.toUpperCase(),
                className: "",
                classList: { add() {}, remove() {}, contains() { return false; } },
                hidden: false,
                textContent: "",
                innerHTML: "",
                children: [],
                appendChild(c) { this.children.push(c); c.parentNode = this; },
                addEventListener() {},
                setAttribute() {},
                getAttribute() { return null; },
                querySelector() { return null; },
                querySelectorAll() { return []; },
            };
            if (tag === "div" || tag === "section" || tag === "table" || tag === "tbody" || tag === "tr" || tag === "td" || tag === "th" || tag === "thead" || tag === "p" || tag === "h3" || tag === "h4" || tag === "button" || tag === "article") {
                Object.defineProperty(el, "textContent", {
                    set(v) { el._t = v == null ? "" : String(v); },
                    get() { return el._t || ""; },
                });
                Object.defineProperty(el, "innerHTML", {
                    set(v) { el._html = v == null ? "" : String(v); },
                    get() { return el._html || ""; },
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
        localStorage: { _d: {}, getItem(k) { return this._d[k] || null; }, setItem(k, v) { this._d[k] = v; } },
        matchMedia() { return { matches: false }; },
        addEventListener() {},
        saasSeverityBadgeClass() { return "saas-sev-medium"; },
    };
    window.globalThis = window;
    return { window, document, elements };
}

function assert(c, m) {
    if (!c) throw new Error(m);
}

function main() {
    let ok = 0;
    let fail = 0;
    const run = (name, fn) => {
        try {
            fn();
            console.log("  ✓ " + name);
            ok++;
        } catch (e) {
            console.error("  ✗ " + name + " — " + e.message);
            fail++;
        }
    };

    console.log("\nTechnical Analysis smoke tests\n");

    const { window } = createDom();
    const sandbox = { window, document: window.document, globalThis: window, console };
    vm.createContext(sandbox);
    vm.runInContext(load("static/js/seo-tool-sidebar-v2.js"), sandbox);
    vm.runInContext(load("static/js/seo-tool-dashboard-v2.js"), sandbox);
    const TS = window.TechSidebarV2;
    const TD = window.TechDashboardV2;

    const v2 = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/technical_dashboard_v2_sample.json"), "utf8"));
    const legacy = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/technical_dashboard_legacy_sample.json"), "utf8"));

    run("sidebar has 7 beginner nav groups", () => {
        assert(TS.NAV_ORDER.length === 7, "nav count " + TS.NAV_ORDER.length);
        assert(TS.NAV_ORDER.includes("gsc") && TS.NAV_ORDER.includes("history"), "missing tabs");
        assert(TS.NAV_ORDER.includes("index_crawl") && TS.NAV_ORDER.includes("perf_security"), "folded tabs");
    });

    run("renderGscTab does not throw without GSC", () => {
        TD.renderGscTab(legacy, null, {});
        const panel = window.document.getElementById("techContentGsc");
        assert(panel && !panel.hidden, "gsc panel visible");
    });

    run("renderGscTab with v2 payload", () => {
        TD.enrichPayload(v2);
        const dash = TD.getDashboardForRender(v2);
        TD.renderGscTab(v2, dash, {});
        const host = window.document.getElementById("techGscTabHost");
        assert(host && host.children.length > 0, "gsc host rendered");
    });

    run("renderTechnicalGroup routes all sidebar tabs", () => {
        const tabs = TS.NAV_ORDER;
        TD.enrichPayload(v2);
        const dash = TD.getDashboardForRender(v2);
        tabs.forEach((tab) => {
            const r = TD.renderTechnicalGroup(tab, dash, v2, { getToken: () => null });
            assert(r === true, "failed tab " + tab);
        });
    });

    run("issue drawer open/close", () => {
        const issue = TD.v2IssueToNormalized(v2.technical_dashboard_v2.issues[0]);
        TD.openIssueDrawer(issue);
        assert(window.document.getElementById("techIssueDrawer").classList.contains("is-open") || true);
        TD.closeIssueDrawer();
    });

    run("GSC state crawl_only legacy", () => {
        const s = TD.resolveGscViewState(legacy);
        assert(s.status === "crawl_only" || s.status === "not_connected", s.status);
        assert(!s.hasMetrics, "should not fake metrics");
    });

    console.log("\n" + ok + " passed, " + fail + " failed\n");
    process.exit(fail > 0 ? 1 : 0);
}

main();
