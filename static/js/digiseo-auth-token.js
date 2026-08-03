/**
 * Central auth token storage: localStorage + sessionStorage + cookie (HTTPS-safe).
 */
(function () {
    "use strict";

    var TOKEN_KEY = "seo_token";
    var MAX_AGE_SEC = 2592000;

    function cookieSecureSuffix() {
        try {
            return window.location.protocol === "https:" ? "; Secure" : "";
        } catch (_) {
            return "";
        }
    }

    function readCookieToken() {
        var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    }

    function syncStores(token) {
        if (!token) return;
        try {
            sessionStorage.setItem(TOKEN_KEY, token);
        } catch (_) {}
        try {
            localStorage.setItem(TOKEN_KEY, token);
        } catch (_) {}
    }

    function getToken() {
        var t = "";
        try {
            t = (localStorage.getItem(TOKEN_KEY) || "").trim();
        } catch (_) {}
        if (!t) {
            try {
                t = (sessionStorage.getItem(TOKEN_KEY) || "").trim();
            } catch (_) {}
        }
        if (!t) {
            t = readCookieToken();
            if (t) syncStores(t);
        }
        return t;
    }

    function setToken(token) {
        token = (token || "").trim();
        if (!token) {
            clearToken();
            return;
        }
        syncStores(token);
        document.cookie =
            TOKEN_KEY +
            "=" +
            encodeURIComponent(token) +
            "; path=/; SameSite=Lax; max-age=" +
            MAX_AGE_SEC +
            cookieSecureSuffix();
        if (typeof window.DigiSeoClearAuthMeCache === "function") {
            window.DigiSeoClearAuthMeCache();
        }
        window.dispatchEvent(new CustomEvent("digiseo-auth-change", { detail: { loggedIn: true } }));
    }

    function clearUserScopedStorage() {
        try {
            var keys = [];
            for (var i = 0; i < localStorage.length; i++) {
                var k = localStorage.key(i);
                if (k) keys.push(k);
            }
            keys.forEach(function (k) {
                if (k.indexOf("seoauto:") === 0 || k === "technical_current_audit_id") {
                    localStorage.removeItem(k);
                }
            });
        } catch (_) {}
        try {
            sessionStorage.removeItem("gsc_selected_site_url");
        } catch (_) {}
    }

    function clearToken() {
        try {
            sessionStorage.removeItem(TOKEN_KEY);
        } catch (_) {}
        try {
            localStorage.removeItem(TOKEN_KEY);
        } catch (_) {}
        clearUserScopedStorage();
        document.cookie = TOKEN_KEY + "=; path=/; max-age=0; SameSite=Lax" + cookieSecureSuffix();
        if (typeof window.DigiSeoClearAuthMeCache === "function") {
            window.DigiSeoClearAuthMeCache();
        }
        window.dispatchEvent(new CustomEvent("digiseo-auth-change", { detail: { loggedIn: false } }));
    }

    function isTokenInvalid401(data) {
        var d = data && data.detail;
        var text = "";
        if (typeof d === "string") text = d;
        else if (d && d.message) text = String(d.message);
        else if (Array.isArray(d)) {
            text = d
                .map(function (x) {
                    return (x && (x.msg || x.message)) || x;
                })
                .join(", ");
        }
        text = text.toLowerCase();
        if (!text) return true;
        if (text.indexOf("invalid token") >= 0) return true;
        if (text.indexOf("hết hạn") >= 0 || text.indexOf("expired") >= 0) return true;
        if (text.indexOf("not authenticated") >= 0) return true;
        if (text.indexOf("đăng nhập") >= 0 && text.indexOf("credit") >= 0) return false;
        if (text.indexOf("đăng nhập") >= 0) return false;
        return false;
    }

    window.DigiSeoGetAuthToken = getToken;
    window.DigiSeoSetAuthToken = setToken;
    window.DigiSeoClearAuthToken = clearToken;
    window.DigiSeoClearUserScopedStorage = clearUserScopedStorage;
    window.DigiSeoSyncTokenFromCookie = getToken;
    window.DigiSeoIsTokenInvalid401 = isTokenInvalid401;
})();
