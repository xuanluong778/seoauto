/**
 * Inject "Social Auto" nav link only for admin users (/auth/me).
 * Regular users never receive the link in the DOM.
 */
(function () {
    "use strict";

    function isAdminUser(user) {
        if (typeof window.DigiSeoIsAdminUser === "function") {
            return window.DigiSeoIsAdminUser(user);
        }
        return !!(user && (user.show_admin_nav === true || String(user.role || "").toLowerCase() === "admin"));
    }

    function applyNavI18n(el) {
        if (!el || !window.DigiSeoI18n || typeof window.DigiSeoI18n.t !== "function") return;
        var key = el.getAttribute("data-i18n");
        if (!key) return;
        el.textContent = window.DigiSeoI18n.t(window.DigiSeoI18n.readLang(), key);
    }

    function applyNavI18nAll() {
        if (window.DigiSeoI18n && typeof window.DigiSeoI18n.apply === "function") {
            window.DigiSeoI18n.apply(window.DigiSeoI18n.readLang());
        }
    }

    function navLinkContainers() {
        var seen = new Set();
        var out = [];
        document.querySelectorAll("#digiseoNavMenu, .digiseo-nav-links, .main-nav.nav").forEach(function (el) {
            if (seen.has(el)) return;
            seen.add(el);
            out.push(el);
        });
        return out;
    }

    function removeSocialAutoLinks() {
        document.querySelectorAll("[data-nav-social-auto]").forEach(function (el) {
            el.remove();
        });
    }

    function createSocialAutoLink() {
        var a = document.createElement("a");
        a.href = "/social-auto";
        a.setAttribute("data-nav-social-auto", "");
        a.className = "nav-admin-only";
        a.setAttribute("data-i18n", "nav.social_auto");
        a.textContent = "Social Auto";
        return a;
    }

    function injectSocialAutoLinks() {
        navLinkContainers().forEach(function (container) {
            if (container.querySelector("[data-nav-social-auto]")) return;
            var link = createSocialAutoLink();
            applyNavI18n(link);
            var settings = container.querySelector('a[href="/settings"]');
            if (settings) container.insertBefore(link, settings);
            else container.appendChild(link);
        });
        if (typeof window.markdigiseoTopNavActive === "function") {
            window.markdigiseoTopNavActive();
        }
        applyNavI18nAll();
    }

    function token() {
        return typeof window.DigiSeoGetAuthToken === "function" ? window.DigiSeoGetAuthToken() : "";
    }

    function run() {
        removeSocialAutoLinks();
        var t = token();
        if (!t) return;

        var fetchMe = window.DigiSeoFetchAuthMe
            ? window.DigiSeoFetchAuthMe()
            : fetch("/auth/me", { credentials: "same-origin", headers: { Authorization: "Bearer " + t } })
                .then(function (r) { return r.ok ? r.json() : null; });

        fetchMe
            .then(function (u) {
                if (isAdminUser(u)) injectSocialAutoLinks();
            })
            .catch(function () {});
    }

    window.isAdminUser = isAdminUser;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run);
    } else {
        run();
    }

    window.addEventListener("storage", function (e) {
        if (e.key === "digiseo_system_prefs_v1") applyNavI18nAll();
    });

    window.refreshDigiSeoSocialAutoNav = run;

    window.addEventListener("digiseo-auth-change", function (e) {
        if (e.detail && e.detail.loggedIn === false) removeSocialAutoLinks();
        else run();
    });
})();
