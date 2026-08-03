/**
 * Content AI — Auto Update tab still lazy; Bulk UI is loaded via index.html defer.
 * Prefetch Auto Update on idle. Keeps ContentAiTabLoader API for view restore.
 *
 * Auto Update tab bundle includes CauBlockEditor + CauAssistantUI + CAU logic
 * (content-ai-auto-update-tab.js). Core app exposes window.ContentAiShared.
 */
(function () {
    "use strict";

    var BULK_UI = "/static/js/content_ai/content-ai-bulk-ui.js?v=36";
    var BULK_PUB = "/static/js/content_ai/content-ai-bulk-publish-center.js?v=5";
    var AUTO_TAB = "/static/js/content_ai/content-ai-auto-update-tab.js?v=55";

    var loaded = {
        bulk: !!(document.querySelector('script[src*="content-ai-bulk-ui.js"]')),
        autoupdate: false,
    };
    var inflight = { bulk: null, autoupdate: null };

    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            if (document.querySelector('script[src="' + src + '"]')) {
                resolve();
                return;
            }
            var s = document.createElement("script");
            s.src = src;
            s.async = true;
            s.onload = function () { resolve(); };
            s.onerror = function () { reject(new Error("Failed to load " + src)); };
            document.body.appendChild(s);
        });
    }

    function prefetch(src) {
        try {
            if (document.querySelector('link[rel="prefetch"][href="' + src + '"],script[src="' + src + '"]')) {
                return;
            }
            var l = document.createElement("link");
            l.rel = "prefetch";
            l.as = "script";
            l.href = src;
            document.head.appendChild(l);
        } catch (_) {}
    }

    function ensureBulkTab() {
        if (window.ContentAiBulkUi) {
            loaded.bulk = true;
            try {
                if (window.ContentAiBulkCore && typeof window.ContentAiBulkCore.rehydrateBulkJobStatus === "function") {
                    void window.ContentAiBulkCore.rehydrateBulkJobStatus({ skipIfHasResult: true });
                }
            } catch (_) {}
            return Promise.resolve();
        }
        if (inflight.bulk) return inflight.bulk;
        inflight.bulk = Promise.all([loadScript(BULK_UI), loadScript(BULK_PUB)])
            .then(function () {
                loaded.bulk = true;
                inflight.bulk = null;
                try {
                    if (window.ContentAiBulkCore && typeof window.ContentAiBulkCore.rehydrateBulkJobStatus === "function") {
                        void window.ContentAiBulkCore.rehydrateBulkJobStatus({ skipIfHasResult: true });
                    }
                } catch (_) {}
            })
            .catch(function (e) {
                inflight.bulk = null;
                throw e;
            });
        return inflight.bulk;
    }

    function ensureAutoUpdateTab() {
        if (loaded.autoupdate && typeof window.__cauSyncUi === "function") {
            try { window.__cauSyncUi(); } catch (_) {}
            return Promise.resolve();
        }
        if (inflight.autoupdate) return inflight.autoupdate;
        inflight.autoupdate = loadScript(AUTO_TAB)
            .then(function () {
                loaded.autoupdate = true;
                inflight.autoupdate = null;
                if (typeof window.__cauSyncUi === "function") {
                    try { window.__cauSyncUi(); } catch (_) {}
                }
            })
            .catch(function (e) {
                inflight.autoupdate = null;
                throw e;
            });
        return inflight.autoupdate;
    }

    window.ContentAiTabLoader = {
        ensureBulkTab: ensureBulkTab,
        ensureAutoUpdateTab: ensureAutoUpdateTab,
    };

    function restoreIfNeeded() {
        try {
            var bulkPanel = document.getElementById("bulkWritePanel");
            if (bulkPanel && !bulkPanel.hidden) {
                ensureBulkTab().catch(function () {});
            }
            var auPanel = document.getElementById("contentAiAutoUpdatePanel");
            if (auPanel && !auPanel.hidden) {
                ensureAutoUpdateTab().catch(function () {});
            }
        } catch (_) {}
    }

    function wire() {
        var bulk = document.getElementById("tabMainBulk");
        var au = document.getElementById("tabMainAutoUpdate");
        if (bulk) {
            bulk.addEventListener("click", function () {
                ensureBulkTab().catch(function (e) {
                    console.warn("[ContentAI] bulk tab load", e);
                });
            });
        }
        if (au) {
            au.addEventListener("click", function () {
                ensureAutoUpdateTab().catch(function (e) {
                    console.warn("[ContentAI] auto-update tab load", e);
                });
            });
        }
        restoreIfNeeded();
        setTimeout(restoreIfNeeded, 0);
        setTimeout(restoreIfNeeded, 200);
        var ric = window.requestIdleCallback || function (cb) { return setTimeout(cb, 1200); };
        ric(function () { prefetch(AUTO_TAB); }, { timeout: 4000 });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", wire);
    } else {
        wire();
    }
})();
