/**
 * Top nav: highlight tab trùng trang hiện tại + active ngay khi click (không nhảy layout).
 */
(function () {
    var TOP_NAV_LINK =
        '[aria-label="Menu chính"] a[href], ' +
        '.digiseo-nav-links > a[href], ' +
        '.nav-strip .nav > a[href], .nav-strip nav > a[href], ' +
        '.header-inner .main-nav > a[href], ' +
        '.report-top > a[href], p.report-top > a[href], ' +
        '.pricing-page-nav .inner > a[href], .pricing-page-nav .digiseo-nav-links > a[href]';

    var NAV_CONTAINERS =
        '#digiseoNavMenu, .digiseo-nav-links, nav[aria-label="Menu chính"]';

    function normPath(p) {
        if (!p) return "/";
        var x = String(p).split("?")[0].split("#")[0].replace(/\/+$/, "");
        return x || "/";
    }

    function normHref(href) {
        if (!href || href.indexOf("http") === 0 || href.indexOf("#") === 0) return "";
        return normPath(href);
    }

    function pathMatches(linkPath, pagePath) {
        if (!linkPath || !pagePath) return false;
        if (linkPath === pagePath) return true;

        if (linkPath === "/") {
            return pagePath === "/" || pagePath === "";
        }

        if (linkPath === "/report") {
            return pagePath === "/report" || pagePath.indexOf("/report/") === 0;
        }

        if (linkPath === "/tool/seo-score") {
            return pagePath === "/tool/seo-score" || pagePath.indexOf("/tool/seo-score/") === 0;
        }

        if (linkPath === "/tool") {
            return pagePath === "/tool";
        }

        if (linkPath === "/keywords/tools/research" || linkPath === "/keywords") {
            return pagePath === "/keywords" || pagePath.indexOf("/keywords/") === 0;
        }

        if (linkPath === "/content-ai") {
            return pagePath === "/content-ai" || pagePath.indexOf("/content-ai/") === 0;
        }

        if (linkPath === "/social-auto") {
            return pagePath === "/social-auto" || pagePath.indexOf("/social-auto/") === 0;
        }

        if (linkPath === "/index-control") {
            return pagePath === "/index-control" || pagePath.indexOf("/index-control/") === 0;
        }

        if (linkPath === "/google-map-seo") {
            return pagePath === "/google-map-seo" || pagePath.indexOf("/google-map-seo/") === 0;
        }

        if (linkPath === "/chatbot-cskh") {
            return pagePath === "/chatbot-cskh" || pagePath.indexOf("/chatbot-cskh/") === 0;
        }

        if (linkPath === "/schema") {
            return pagePath === "/schema" || pagePath.indexOf("/schema/") === 0;
        }

        if (linkPath === "/pricing") {
            return pagePath === "/pricing";
        }

        if (linkPath === "/settings") {
            return pagePath === "/settings" || pagePath.indexOf("/settings/") === 0;
        }

        if (linkPath === "/account-billing") {
            return pagePath === "/account-billing" || pagePath.indexOf("/account-billing/") === 0;
        }

        if (linkPath === "/admin") {
            return pagePath === "/admin" || pagePath.indexOf("/admin/") === 0;
        }

        return pagePath.indexOf(linkPath + "/") === 0;
    }

    function topNavLinks() {
        return Array.prototype.slice.call(document.querySelectorAll(TOP_NAV_LINK));
    }

    function clearActive(links) {
        links.forEach(function (a) {
            a.classList.remove("active", "is-active");
            a.removeAttribute("aria-current");
        });
    }

    function setActive(a) {
        a.classList.add("active", "is-active");
        a.setAttribute("aria-current", "page");
    }

    function markTopNavActive() {
        var pagePath = normPath(window.location && window.location.pathname);
        var links = topNavLinks();
        clearActive(links);
        links.forEach(function (a) {
            var linkPath = normHref(a.getAttribute("href") || "");
            if (!linkPath || linkPath === "/") return;
            if (pathMatches(linkPath, pagePath)) {
                setActive(a);
            }
        });
    }

    function bindTopNavClicks() {
        document.querySelectorAll(NAV_CONTAINERS).forEach(function (wrap) {
            if (wrap.dataset.digiseoNavBound) return;
            wrap.dataset.digiseoNavBound = "1";
            wrap.addEventListener("click", function (e) {
                var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
                if (!a || !wrap.contains(a)) return;
                if (a.target === "_blank" || a.hasAttribute("download")) return;
                if (a.classList.contains("digiseo-brand-link")) return;
                var linkPath = normHref(a.getAttribute("href") || "");
                if (!linkPath || linkPath === "/") return;
                clearActive(topNavLinks());
                setActive(a);
            });
        });
    }

    var prefetchedHrefs = Object.create(null);
    function prefetchTopNavLink(a) {
        if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
        var href = a.href;
        if (!href || href.indexOf("#") >= 0) return;
        try {
            var u = new URL(href, window.location.href);
            if (u.origin !== window.location.origin) return;
            if (normPath(u.pathname) === normPath(window.location.pathname)) return;
            if (prefetchedHrefs[href]) return;
            prefetchedHrefs[href] = 1;
            var link = document.createElement("link");
            link.rel = "prefetch";
            link.href = href;
            document.head.appendChild(link);
        } catch (_) {}
    }

    function bindPrefetch() {
        topNavLinks().forEach(function (a) {
            if (a.dataset.digiseoNavPrefetch) return;
            a.dataset.digiseoNavPrefetch = "1";
            a.addEventListener("mouseenter", function () {
                prefetchTopNavLink(a);
            }, { passive: true });
            a.addEventListener("focus", function () {
                prefetchTopNavLink(a);
            });
        });
    }

    function init() {
        markTopNavActive();
        bindTopNavClicks();
        bindPrefetch();
        if (window.DigiSeoI18n && typeof window.DigiSeoI18n.init === "function") {
            window.addEventListener("digiseo:i18n-applied", function () {
                markTopNavActive();
                bindPrefetch();
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
    window.setTimeout(function () {
        markTopNavActive();
        bindTopNavClicks();
        bindPrefetch();
    }, 0);
    window.addEventListener("pageshow", markTopNavActive);
    window.addEventListener("popstate", markTopNavActive);
    window.markdigiseoTopNavActive = markTopNavActive;
})();
