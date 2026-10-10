/**
 * Auth routing — giữ URL hiện tại khi F5; chỉ redirect sau login hoặc khi gọi rõ ràng.
 * Không đọc last_page / active_tab / return_url từ storage khi reload.
 */
(function () {
    "use strict";

    var RETURN_KEY = "digiseo_post_login_return";
    var LOOP_TARGET_KEY = "digiseo_redirect_target";
    var LOOP_TS_KEY = "digiseo_redirect_ts";
    var LOOP_MS = 3000;

    var AUTH_CALLBACK_PARAMS = [
        "google_login",
        "google_login_error",
        "google_error",
        "fb",
        "web20",
        "detail",
        "platform",
    ];

    var PUBLIC_PATHS = ["/", "/pricing"];

    var ALLOWED_PREFIXES = [
        "/tool",
        "/content-ai",
        "/keywords",
        "/social-auto",
        "/index-control",
        "/report",
        "/settings",
        "/account-billing",
        "/admin",
        "/schema",
    ];

    function normPath(p) {
        if (!p) return "/";
        var x = String(p).split("?")[0].split("#")[0].replace(/\/+$/, "");
        return x || "/";
    }

    function currentLocation() {
        return window.location.pathname + window.location.search + window.location.hash;
    }

    function isSafeInternalPath(path) {
        if (!path || typeof path !== "string") return false;
        var raw = String(path).trim();
        if (!raw || raw.indexOf("//") === 0) return false;

        var pathname = raw;
        var search = "";
        var hash = "";
        if (raw.charAt(0) === "/") {
            var qIdx = raw.indexOf("?");
            var hIdx = raw.indexOf("#");
            var cut = raw.length;
            if (qIdx >= 0) cut = Math.min(cut, qIdx);
            if (hIdx >= 0) cut = Math.min(cut, hIdx);
            pathname = raw.slice(0, cut);
            if (qIdx >= 0) search = hIdx >= 0 ? raw.slice(qIdx, hIdx) : raw.slice(qIdx);
            if (hIdx >= 0) hash = raw.slice(hIdx);
        } else {
            try {
                var u = new URL(raw, window.location.origin);
                if (u.origin !== window.location.origin) return false;
                pathname = u.pathname;
                search = u.search;
                hash = u.hash;
            } catch (_) {
                return false;
            }
        }

        pathname = normPath(pathname);
        if (PUBLIC_PATHS.indexOf(pathname) >= 0) return true;
        for (var i = 0; i < ALLOWED_PREFIXES.length; i++) {
            var prefix = ALLOWED_PREFIXES[i];
            if (pathname === prefix || pathname.indexOf(prefix + "/") === 0) return true;
        }
        return false;
    }

    function resolveReturnUrl(raw) {
        if (raw == null || raw === "") return "";
        var value = String(raw).trim();
        try {
            value = decodeURIComponent(value);
        } catch (_) {}
        if (!value) return "";
        if (value.charAt(0) !== "/") {
            try {
                var u = new URL(value, window.location.origin);
                if (u.origin !== window.location.origin) return "";
                value = u.pathname + u.search + u.hash;
            } catch (_) {
                return "";
            }
        }
        return isSafeInternalPath(value) ? value : "";
    }

    function samePath(a, b) {
        return normPath(String(a || "").split("?")[0].split("#")[0]) ===
            normPath(String(b || "").split("?")[0].split("#")[0]);
    }

    function wouldLoop(target) {
        try {
            var last = sessionStorage.getItem(LOOP_TARGET_KEY) || "";
            var ts = parseInt(sessionStorage.getItem(LOOP_TS_KEY) || "0", 10);
            return last === target && Date.now() - ts < LOOP_MS;
        } catch (_) {
            return false;
        }
    }

    function markRedirect(target) {
        try {
            sessionStorage.setItem(LOOP_TARGET_KEY, target);
            sessionStorage.setItem(LOOP_TS_KEY, String(Date.now()));
        } catch (_) {}
    }

    function safeRedirect(url, opts) {
        opts = opts || {};
        var target = resolveReturnUrl(url);
        if (!target) return false;
        if (!opts.force && samePath(target, currentLocation())) return false;
        if (wouldLoop(target)) return false;
        markRedirect(target);
        if (opts.replace) window.location.replace(target);
        else window.location.assign(target);
        return true;
    }

    function rememberPostLoginReturn(url) {
        var target = resolveReturnUrl(url || currentLocation());
        if (!target) return;
        try {
            sessionStorage.setItem(RETURN_KEY, target);
        } catch (_) {}
    }

    function consumePostLoginReturn() {
        try {
            var value = sessionStorage.getItem(RETURN_KEY) || "";
            sessionStorage.removeItem(RETURN_KEY);
            return resolveReturnUrl(value);
        } catch (_) {
            return "";
        }
    }

    function stripAuthCallbackParams() {
        var q = new URLSearchParams(window.location.search);
        var changed = false;
        AUTH_CALLBACK_PARAMS.forEach(function (key) {
            if (q.has(key)) {
                q.delete(key);
                changed = true;
            }
        });
        if (!changed) return false;
        var search = q.toString();
        var nextUrl = window.location.pathname + (search ? "?" + search : "") + window.location.hash;
        history.replaceState({}, "", nextUrl);
        return true;
    }

    function syncTokenFromCookie() {
        if (typeof window.DigiSeoSyncTokenFromCookie === "function") {
            return window.DigiSeoSyncTokenFromCookie() || "";
        }
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken() || "";
        }
        return "";
    }

    function openLoginModal() {
        if (typeof window.DigiSeoOpenLoginModal === "function") {
            window.DigiSeoOpenLoginModal();
            return true;
        }
        var authModal = document.getElementById("authModal");
        if (!authModal) return false;
        authModal.hidden = false;
        if (typeof window.DigiSeoSetAuthTab === "function") {
            window.DigiSeoSetAuthTab("login");
        }
        var authPassword = document.getElementById("authPassword");
        if (authPassword) authPassword.value = "";
        var authEmail = document.getElementById("authEmail");
        if (authEmail) {
            try {
                authEmail.focus();
            } catch (_) {}
        }
        return true;
    }

    function goLogin(fromUrl) {
        rememberPostLoginReturn(fromUrl || currentLocation());
        if (openLoginModal()) return;
        var next = encodeURIComponent(currentLocation());
        safeRedirect("/tool?next=" + next);
    }

    function afterLoginSuccess() {
        var q = new URLSearchParams(window.location.search);
        var fromQuery = resolveReturnUrl(q.get("next") || q.get("return_url") || "");
        if (fromQuery && !samePath(fromQuery, currentLocation())) {
            if (q.has("next")) q.delete("next");
            if (q.has("return_url")) q.delete("return_url");
            var search = q.toString();
            history.replaceState({}, "", window.location.pathname + (search ? "?" + search : "") + window.location.hash);
            safeRedirect(fromQuery, { replace: true });
            return true;
        }
        var stored = consumePostLoginReturn();
        if (stored && !samePath(stored, currentLocation())) {
            safeRedirect(stored, { replace: true });
            return true;
        }
        return false;
    }

    function finishOAuthReturn(token) {
        if (token && typeof window.DigiSeoSetAuthToken === "function") {
            window.DigiSeoSetAuthToken(token);
        }
        stripAuthCallbackParams();
        afterLoginSuccess();
        try {
            window.dispatchEvent(new CustomEvent("digiseo-auth-change", { detail: { loggedIn: !!token } }));
        } catch (_) {}
        if (typeof window.refreshDigiSeoNavAuth === "function") {
            try {
                window.refreshDigiSeoNavAuth(true);
            } catch (_) {}
        }
        if (typeof window.refreshDigiSeoUserDock === "function") {
            try {
                window.refreshDigiSeoUserDock();
            } catch (_) {}
        }
    }

    function handleOAuthReturn() {
        var q = new URLSearchParams(window.location.search);
        if (q.get("google_login") !== "1") return false;
        var hydrate =
            typeof window.DigiSeoHydrateSessionFromCookie === "function"
                ? window.DigiSeoHydrateSessionFromCookie(true)
                : Promise.resolve(syncTokenFromCookie());
        hydrate
            .then(function (tok) {
                finishOAuthReturn(tok || syncTokenFromCookie() || "");
            })
            .catch(function () {
                finishOAuthReturn(syncTokenFromCookie() || "");
            });
        return true;
    }

    function onPageLoad() {
        syncTokenFromCookie();
        if (handleOAuthReturn()) return;
        stripAuthCallbackParams();
        // Cookie-only sessions (HttpOnly seo_token, empty localStorage)
        if (!syncTokenFromCookie() && typeof window.DigiSeoHydrateSessionFromCookie === "function") {
            window.DigiSeoHydrateSessionFromCookie(false).then(function (tok) {
                if (!tok) return;
                try {
                    window.dispatchEvent(
                        new CustomEvent("digiseo-auth-change", { detail: { loggedIn: true } }),
                    );
                } catch (_) {}
                if (typeof window.refreshDigiSeoNavAuth === "function") {
                    try {
                        window.refreshDigiSeoNavAuth(true);
                    } catch (_) {}
                }
            });
        }
    }

    window.DigiSeoSafeRedirect = safeRedirect;
    window.DigiSeoResolveReturnUrl = resolveReturnUrl;
    window.DigiSeoRememberPostLoginReturn = rememberPostLoginReturn;
    window.DigiSeoGoLogin = goLogin;
    window.DigiSeoAfterLoginSuccess = afterLoginSuccess;
    window.DigiSeoStripAuthCallbackParams = stripAuthCallbackParams;

    onPageLoad();
})();
