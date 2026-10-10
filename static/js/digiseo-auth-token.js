/**
 * Central auth token storage: session/localStorage for Bearer.
 * Cookie seo_token / seo_refresh are HttpOnly (server-set only).
 * CSRF: double-submit via readable seo_csrf cookie + X-CSRF-Token header.
 *
 * Session mode (SERVER_SESSIONS): access JWT ~15–30m. This module:
 * - proactively refreshes via /auth/session when exp is near/past
 * - single-flights refresh so multi-tab/parallel calls do not kill the session
 * - on 401 Invalid token: one refresh retry before clearing login
 */
(function () {
    "use strict";

    var TOKEN_KEY = "seo_token";
    var CSRF_COOKIE = "seo_csrf";
    var REFRESH_SKEW_SEC = 120; // refresh 2 minutes before exp
    var _hydrateInflight = null;
    var _refreshInflight = null;

    function cookieSecureSuffix() {
        try {
            return window.location.protocol === "https:" ? "; Secure" : "";
        } catch (_) {
            return "";
        }
    }

    function readCookie(name) {
        try {
            var m = document.cookie.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]*)"));
            return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
        } catch (_) {
            return "";
        }
    }

    function getCsrfToken() {
        return readCookie(CSRF_COOKIE);
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
        return t;
    }

    function setToken(token) {
        token = (token || "").trim();
        if (!token) {
            clearToken();
            return;
        }
        syncStores(token);
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
        try {
            document.cookie = TOKEN_KEY + "=; path=/; max-age=0; SameSite=Lax" + cookieSecureSuffix();
            document.cookie = CSRF_COOKIE + "=; path=/; max-age=0; SameSite=Lax" + cookieSecureSuffix();
        } catch (_) {}
        if (typeof window.DigiSeoClearAuthMeCache === "function") {
            window.DigiSeoClearAuthMeCache();
        }
        window.dispatchEvent(new CustomEvent("digiseo-auth-change", { detail: { loggedIn: false } }));
    }

    function parseJwtPayload(token) {
        try {
            var part = String(token || "").split(".")[1];
            if (!part) return null;
            var b64 = part.replace(/-/g, "+").replace(/_/g, "/");
            var pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
            return JSON.parse(atob(pad));
        } catch (_) {
            return null;
        }
    }

    /** Returns seconds until exp (negative if expired). null if unknown. */
    function tokenSecondsRemaining(token) {
        var payload = parseJwtPayload(token);
        if (!payload || payload.exp == null) return null;
        var exp = Number(payload.exp);
        if (!Number.isFinite(exp)) return null;
        return exp - Math.floor(Date.now() / 1000);
    }

    function tokenNeedsRefresh(token) {
        if (!token) return true;
        var rem = tokenSecondsRemaining(token);
        if (rem == null) return false; // non-JWT / opaque — leave alone
        return rem <= REFRESH_SKEW_SEC;
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
        if (text.indexOf("invalid refresh") >= 0) return true;
        if (text.indexOf("hết hạn") >= 0 || text.indexOf("expired") >= 0) return true;
        if (text.indexOf("not authenticated") >= 0) return true;
        if (text.indexOf("đăng nhập") >= 0 && text.indexOf("credit") >= 0) return false;
        if (text.indexOf("đăng nhập") >= 0) return false;
        return false;
    }

    function authHeaders(extra) {
        var h = Object.assign({}, extra || {});
        var t = getToken();
        if (t) h["Authorization"] = "Bearer " + t;
        var csrf = getCsrfToken();
        if (csrf) h["X-CSRF-Token"] = csrf;
        return h;
    }

    /**
     * Refresh access token using HttpOnly seo_refresh via GET /auth/session.
     * Single-flight: concurrent callers share one request.
     */
    function refreshSessionFromCookie() {
        if (_refreshInflight) return _refreshInflight;
        var existing = getToken();
        _refreshInflight = fetch("/auth/session", {
            credentials: "same-origin",
            cache: "no-store",
            headers: existing ? { Authorization: "Bearer " + existing } : {},
        })
            .then(function (r) {
                if (!r.ok) return "";
                return r.json().catch(function () {
                    return null;
                });
            })
            .then(function (d) {
                var tok = d && d.access_token ? String(d.access_token).trim() : "";
                if (tok) {
                    setToken(tok);
                    return tok;
                }
                return "";
            })
            .catch(function () {
                return "";
            })
            .finally(function () {
                _refreshInflight = null;
            });
        return _refreshInflight;
    }

    /** seo_token is HttpOnly — hydrate SPA storage via /auth/session (cookie credentials). */
    function hydrateSessionFromCookie(force) {
        var existing = getToken();
        var mustRefresh = !!force || tokenNeedsRefresh(existing);
        if (existing && !mustRefresh) {
            return Promise.resolve(existing);
        }
        if (_hydrateInflight && !force) {
            return _hydrateInflight;
        }
        _hydrateInflight = refreshSessionFromCookie()
            .then(function (tok) {
                return tok || getToken() || "";
            })
            .finally(function () {
                _hydrateInflight = null;
            });
        return _hydrateInflight;
    }

    /**
     * Ensure Bearer is fresh before API calls. Always prefer this over raw getToken().
     */
    function ensureFreshAuthToken(force) {
        var existing = getToken();
        if (!force && existing && !tokenNeedsRefresh(existing)) {
            return Promise.resolve(existing);
        }
        return hydrateSessionFromCookie(!!force || tokenNeedsRefresh(existing)).then(function (tok) {
            return tok || getToken() || "";
        });
    }

    /**
     * fetch wrapper: attach auth, on 401 Invalid token → refresh once → retry once.
     * Does NOT clear token until refresh fails.
     */
    function authFetch(url, opts) {
        opts = opts || {};
        var retried = false;
        function once(forceRefresh) {
            return ensureFreshAuthToken(!!forceRefresh).then(function (tok) {
                var o = Object.assign({}, opts);
                o.credentials = o.credentials || "same-origin";
                o.headers = authHeaders(opts.headers || {});
                if (tok) o.headers["Authorization"] = "Bearer " + tok;
                return fetch(url, o).then(function (res) {
                    if (res.status !== 401 || retried) return res;
                    return res
                        .clone()
                        .json()
                        .catch(function () {
                            return {};
                        })
                        .then(function (data) {
                            if (!isTokenInvalid401(data)) return res;
                            retried = true;
                            return refreshSessionFromCookie().then(function (newTok) {
                                if (!newTok) {
                                    clearToken();
                                    return res;
                                }
                                return once(true);
                            });
                        });
                });
            });
        }
        return once(false);
    }

    window.DigiSeoGetAuthToken = getToken;
    window.DigiSeoSetAuthToken = setToken;
    window.DigiSeoClearAuthToken = clearToken;
    window.DigiSeoClearUserScopedStorage = clearUserScopedStorage;
    window.DigiSeoSyncTokenFromCookie = getToken;
    window.DigiSeoHydrateSessionFromCookie = hydrateSessionFromCookie;
    window.DigiSeoEnsureFreshAuthToken = ensureFreshAuthToken;
    window.DigiSeoRefreshSessionFromCookie = refreshSessionFromCookie;
    window.DigiSeoAuthFetch = authFetch;
    window.DigiSeoIsTokenInvalid401 = isTokenInvalid401;
    window.DigiSeoGetCsrfToken = getCsrfToken;
    window.DigiSeoAuthHeaders = authHeaders;
    window.DigiSeoTokenNeedsRefresh = tokenNeedsRefresh;

    // Background keep-alive: refresh before access JWT expires (multi-tab safe via single-flight).
    try {
        setInterval(function () {
            var t = getToken();
            if (t && tokenNeedsRefresh(t)) {
                refreshSessionFromCookie();
            }
        }, 60 * 1000);
    } catch (_) {}
})();
