/**
 * Unit tests for Keyword Research → Keyword Clustering prefill helpers.
 * Run: node tests/test_keyword_clustering_prefill.js
 */
"use strict";

function normalizeKeywords(list) {
    var seen = {};
    var out = [];
    (list || []).forEach(function (k) {
        if (k == null) return;
        var s = String(k).trim();
        if (!s) return;
        var key = s.toLowerCase();
        if (seen[key]) return;
        seen[key] = true;
        out.push(s);
    });
    return out;
}

function buildPrefillPayload(keywords, opts) {
    opts = opts || {};
    return {
        keywords: normalizeKeywords(keywords),
        source: "keyword_research",
        created_at: Date.now(),
        country: opts.country || "vn",
        language: opts.language || "vi",
        device: opts.device || "desktop",
    };
}

function assert(cond, msg) {
    if (!cond) throw new Error(msg || "assertion failed");
}

(function run() {
    assert(JSON.stringify(normalizeKeywords([" SEO ", "seo", "", null, undefined, "Blog"])) ===
        JSON.stringify(["SEO", "Blog"]), "dedupe empty null");

    var payload = buildPrefillPayload(["kw1", "kw2"], { country: "us" });
    assert(payload.source === "keyword_research", "source");
    assert(payload.keywords.length === 2, "keyword count");
    assert(payload.country === "us", "country passthrough");
    assert(typeof payload.created_at === "number", "created_at");

    console.log("test_keyword_clustering_prefill.js: OK");
})();
