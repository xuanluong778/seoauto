/**
 * Nav policy — ẩn Tài khoản & Thanh toán / Quản trị viên trên menu chính khi đã đăng nhập.
 * Các mục này truy cập qua avatar góc trái dưới.
 */
(function () {
    "use strict";

    function isAdminUser(user) {
        if (typeof window.DigiSeoIsAdminUser === "function") {
            return window.DigiSeoIsAdminUser(user);
        }
        if (!user || typeof user !== "object") return false;
        if (user.show_admin_nav === true) return true;
        var role = String(user.role || "").toLowerCase();
        return role === "admin" || role === "super_admin";
    }

    function isLoggedInUser(user) {
        if (!user || typeof user !== "object") return false;
        if (user.id != null) return true;
        return !!String(user.email || "").trim();
    }

    function setNavLinkHidden(el, hide) {
        if (!el) return;
        el.hidden = !!hide;
        if (hide) el.setAttribute("aria-hidden", "true");
        else el.removeAttribute("aria-hidden");
    }

    window.DigiSeoApplyAdminNavPolicy = function (me) {
        var isAdmin = isAdminUser(me);
        var isLoggedIn = isLoggedInUser(me);
        if (document.body) {
            document.body.classList.toggle("digiseo-admin-nav-via-avatar", isLoggedIn);
        }
        document.querySelectorAll("[data-nav-account-billing]").forEach(function (el) {
            setNavLinkHidden(el, isLoggedIn);
        });
        document.querySelectorAll("[data-nav-admin]").forEach(function (el) {
            setNavLinkHidden(el, isAdmin);
        });
    };

    function removeLegacyAdminNavLinks() {
        document.querySelectorAll("[data-nav-admin]").forEach(function (el) {
            el.remove();
        });
    }

    function token() {
        return typeof window.DigiSeoGetAuthToken === "function" ? window.DigiSeoGetAuthToken() : "";
    }

    function syncAccountWidget() {
        if (typeof window.refreshDigiSeoAccountWidget === "function") {
            window.refreshDigiSeoAccountWidget();
        }
    }

    function run() {
        removeLegacyAdminNavLinks();
        var t = token();
        if (!t) {
            window.DigiSeoApplyAdminNavPolicy(null);
            return;
        }
        var fetchMe = window.DigiSeoFetchAuthMe
            ? window.DigiSeoFetchAuthMe()
            : fetch("/auth/me", {
                  credentials: "same-origin",
                  headers: { Authorization: "Bearer " + t },
              }).then(function (r) {
                  return r.ok ? r.json() : null;
              });
        fetchMe
            .then(function (u) {
                window.DigiSeoApplyAdminNavPolicy(u);
                syncAccountWidget();
            })
            .catch(function () {
                window.DigiSeoApplyAdminNavPolicy(null);
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", run);
    } else {
        run();
    }

    window.refreshDigiSeoAdminNav = run;
    window.syncDigiSeoAccountNavFromUser = window.DigiSeoApplyAdminNavPolicy;

    window.addEventListener("digiseo-auth-change", function (e) {
        if (e.detail && e.detail.loggedIn === false) {
            window.DigiSeoApplyAdminNavPolicy(null);
        }
        run();
    });
})();
