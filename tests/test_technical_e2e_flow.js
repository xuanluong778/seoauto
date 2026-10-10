/**
 * E2E flow smoke — scoring → compare identity → history/compare helpers (no live crawl).
 */
"use strict";

const assert = require("assert");
const path = require("path");
const vm = require("vm");

function loadDashboard() {
    const file = path.join(__dirname, "..", "static", "js", "seo-tool-dashboard-v2.js");
    const src = require("fs").readFileSync(file, "utf8");
    const sandbox = {
        window: {},
        document: {
            readyState: "complete",
            addEventListener() {},
            getElementById: () => null,
            querySelector: () => null,
            querySelectorAll: () => [],
            createElement: (tag) => ({
                tagName: tag,
                className: "",
                hidden: false,
                innerHTML: "",
                textContent: "",
                style: {},
                dataset: {},
                children: [],
                appendChild() {},
                querySelector: () => null,
                querySelectorAll: () => [],
                addEventListener() {},
            }),
        },
        global: {},
        console,
        setTimeout,
        clearTimeout,
        setInterval,
        clearInterval,
    };
    sandbox.global = sandbox;
    sandbox.window = sandbox;
    vm.runInNewContext(src, sandbox);
    return sandbox.TechDashboardV2;
}

function loadCompareModule() {
    // Mirror Python issue_identity + compare counts via inline logic for JS layer smoke
    return {
        identity(issue) {
            const itype = String(issue.issue_type || issue.type || "issue").toLowerCase();
            const url = String((issue.affected_urls && issue.affected_urls[0]) || issue.url || "").toLowerCase();
            return itype + "|" + (url || "__site__");
        },
        compare(baseIssues, targetIssues) {
            const baseMap = {};
            baseIssues.forEach((i) => {
                baseMap[this.identity(i)] = i;
            });
            const targetMap = {};
            targetIssues.forEach((i) => {
                targetMap[this.identity(i)] = i;
            });
            const baseKeys = new Set(Object.keys(baseMap));
            const targetKeys = new Set(Object.keys(targetMap));
            return {
                fixed: [...baseKeys].filter((k) => !targetKeys.has(k)).length,
                new: [...targetKeys].filter((k) => !baseKeys.has(k)).length,
                remaining: [...targetKeys].filter((k) => baseKeys.has(k)).length,
            };
        },
    };
}

function main() {
    const TD = loadDashboard();
    assert(TD, "TechDashboardV2 loaded");
    assert(typeof TD.buildSimpleIssueTable === "function", "buildSimpleIssueTable");
    assert(typeof TD.sortPriorityIssues === "function", "sortPriorityIssues");
    assert(typeof TD.renderAuditComparePanel === "function", "renderAuditComparePanel");
    assert(typeof TD.setScanJobProgress === "function", "setScanJobProgress");

    const issues = [
        { issue_id: "a", title: "High", severity: "critical", priority_score: 88, priority_tier: "P0", affected_urls: ["https://x.com/a"] },
        { issue_id: "b", title: "Low", severity: "low", priority_score: 22, priority_tier: "P3", affected_urls: ["https://x.com/b"] },
    ];
    const sorted = TD.sortPriorityIssues(issues.slice());
    assert(Number(sorted[0].priority_score) >= Number(sorted[1].priority_score), "priority sort desc");

    const table = TD.buildSimpleIssueTable(sorted);
    assert(table && table.className.indexOf("tech-simple-table-wrap") >= 0, "simple table wrap");

    const cmp = loadCompareModule();
    const diff = cmp.compare(
        [{ issue_type: "t1", affected_urls: ["https://a.com/1"] }, { issue_type: "t2", affected_urls: ["https://a.com/2"] }],
        [{ issue_type: "t2", affected_urls: ["https://a.com/2"] }, { issue_type: "t3", affected_urls: ["https://a.com/3"] }]
    );
    assert.strictEqual(diff.fixed, 1);
    assert.strictEqual(diff.new, 1);
    assert.strictEqual(diff.remaining, 1);

    console.log("test_technical_e2e_flow.js: all passed");
}

main();
