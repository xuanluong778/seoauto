/**
 * Shared /auth/me fetch — dedupe concurrent calls and cache briefly across nav modules.
 */
(function () {
    "use strict";

    var TTL_MS = 60000;
    var cache = { token: "", user: null, at: 0 };
    var inflight = null;

    function getToken() {
        return typeof window.DigiSeoGetAuthToken === "function" ? window.DigiSeoGetAuthToken() : "";
    }

    function clearCache() {
        cache = { token: "", user: null, at: 0 };
        inflight = null;
    }

    window.DigiSeoClearAuthMeCache = clearCache;

    window.DigiSeoFetchAuthMe = function (opts) {
        opts = opts || {};
        var force = !!opts.force;
        var t = getToken();
        if (!t) {
            clearCache();
            return Promise.resolve(null);
        }
        if (!force && cache.token === t && cache.user && Date.now() - cache.at < TTL_MS) {
            return Promise.resolve(cache.user);
        }
        if (!force && inflight && inflight.token === t) {
            return inflight.promise;
        }

        var promise = fetch("/auth/me", {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + t },
        })
            .then(function (r) {
                if (r.status === 401) {
                    if (typeof window.DigiSeoClearAuthToken === "function") {
                        window.DigiSeoClearAuthToken();
                    }
                    clearCache();
                    return null;
                }
                return r.ok ? r.json() : null;
            })
            .then(function (u) {
                inflight = null;
                if (u && u.email) {
                    cache = { token: t, user: u, at: Date.now() };
                    return u;
                }
                cache = { token: t, user: null, at: Date.now() };
                return null;
            })
            .catch(function () {
                inflight = null;
                return null;
            });

        inflight = { token: t, promise: promise };
        return promise;
    };

    window.DigiSeoIsAdminUser = function (user) {
        if (!user || typeof user !== "object") return false;
        if (user.show_admin_nav === true) return true;
        var role = String(user.role || "").toLowerCase();
        return role === "admin" || role === "super_admin";
    };
})();
