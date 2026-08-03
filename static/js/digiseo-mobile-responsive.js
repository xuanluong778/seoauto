/**
 * SEOAuto — responsive helpers (tool sidebar collapse, table scroll hint).
 * Không đụng logic nghiệp vụ / API.
 */
(function () {
    "use strict";

    var TOOL_BP = 1024;

    function isToolCompact() {
        return window.matchMedia("(max-width: " + TOOL_BP + "px)").matches;
    }

    function initToolCollapse() {
        if (!document.body.classList.contains("page-tool")) return;

        document.querySelectorAll(".digiseo-tool-collapse-btn").forEach(function (btn) {
            if (btn.dataset.digiseoToolCollapseBound) return;
            btn.dataset.digiseoToolCollapseBound = "1";

            var panelId = btn.getAttribute("aria-controls");
            var panel = panelId ? document.getElementById(panelId) : null;
            if (!panel) return;

            function sync(expanded) {
                btn.setAttribute("aria-expanded", expanded ? "true" : "false");
                panel.classList.toggle("is-expanded", expanded);
            }

            if (isToolCompact()) sync(false);
            else sync(true);

            btn.addEventListener("click", function () {
                if (!isToolCompact()) return;
                sync(!panel.classList.contains("is-expanded"));
            });
        });

        window.addEventListener("resize", function () {
            document.querySelectorAll(".digiseo-tool-collapse-btn").forEach(function (btn) {
                var panelId = btn.getAttribute("aria-controls");
                var panel = panelId ? document.getElementById(panelId) : null;
                if (!panel) return;
                if (!isToolCompact()) {
                    panel.classList.add("is-expanded");
                    btn.setAttribute("aria-expanded", "true");
                }
            });
        });
    }

    function wrapWideTables() {
        document.querySelectorAll(
            "table.issues-matrix, table.wide, table.audit-scan-matrix, table.seo-table"
        ).forEach(function (table) {
            if (table.closest(".digiseo-table-scroll, .digiseo-table-wrap, .issues-table-wrap, .table-scroll")) return;
            var wrap = document.createElement("div");
            wrap.className = "digiseo-table-scroll";
            table.parentNode.insertBefore(wrap, table);
            wrap.appendChild(table);
        });
    }

    function init() {
        initToolCollapse();
        wrapWideTables();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
