/**
 * Global top-right account summary (plan + credits) on all app pages with main nav.
 */
(function () {
    const TOKEN_KEY = "seo_token";

    function cookieSecureSuffix() {
        try {
            return window.location.protocol === "https:" ? "; Secure" : "";
        } catch (_) {
            return "";
        }
    }

    function getToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken();
        }
        try {
            let t = (sessionStorage.getItem(TOKEN_KEY) || "").trim();
            if (!t) {
                const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
                t = m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
                if (t) sessionStorage.setItem(TOKEN_KEY, t);
            }
            return t;
        } catch (_) {
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
        }
    }

    window.DigiSeoSyncTokenFromCookie = function () {
        return getToken();
    };
    window.DigiSeoSyncTokenFromCookie();

    function hideAdminNavLinks() {
        document.querySelectorAll("[data-nav-admin]").forEach((el) => {
            el.remove();
        });
    }

    function formatCredits(n) {
        const v = Number(n);
        if (!Number.isFinite(v)) return "0";
        return v.toLocaleString("vi-VN");
    }

    function ensureAccountSlot() {
        let slot = document.getElementById("digiseoNavAccountSlot");
        if (slot) return slot;

        const hosts = [
            document.getElementById("digiseoTopNavStrip"),
            document.querySelector(".nav-strip"),
            document.querySelector("header.site-header"),
            document.querySelector("nav[aria-label='Menu chính']")?.closest(".nav-strip"),
        ].filter(Boolean);

        for (let i = 0; i < hosts.length; i++) {
            const host = hosts[i];
            if (host.querySelector("#digiseoNavAccountSlot")) {
                return host.querySelector("#digiseoNavAccountSlot");
            }
            slot = document.createElement("div");
            slot.id = "digiseoNavAccountSlot";
            slot.className = "digiseo-nav-account-slot";
            slot.setAttribute("aria-label", "Tài khoản");
            host.appendChild(slot);
            return slot;
        }

        return null;
    }

    function mountTarget() {
        return ensureAccountSlot() || document.body;
    }

    function removeLegacyAuthButtons() {
        ["digiseoNavLogin", "digiseoNavLogout"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.remove();
        });
    }

    function ensureBar() {
        let bar = document.getElementById("digiseoNavAuthBar");
        if (bar) {
            removeLegacyAuthButtons();
            return bar;
        }

        const target = mountTarget();
        bar = document.createElement("div");
        bar.id = "digiseoNavAuthBar";
        bar.className = "digiseo-nav-auth-bar";
        if (target === document.body) {
            bar.classList.add("digiseo-nav-auth-bar--floating");
        }
        bar.setAttribute("aria-label", "Account");
        bar.hidden = true;

        const accountLink = document.createElement("a");
        accountLink.id = "digiseoNavAccountLink";
        accountLink.className = "digiseo-nav-account-link";
        accountLink.href = "/account-billing";
        accountLink.setAttribute("title", "Tài khoản & Thanh toán");

        const creditChip = document.createElement("span");
        creditChip.id = "digiseoNavCreditChip";
        creditChip.className = "digiseo-nav-credit-chip";
        creditChip.innerHTML =
            '<span class="digiseo-nav-credit-label">Credit</span><strong id="digiseoNavCreditValue">—</strong>';

        accountLink.appendChild(creditChip);
        bar.appendChild(accountLink);
        target.appendChild(bar);
        return bar;
    }

    function setAccountSummary(saas, user) {
        const bar = document.getElementById("digiseoNavAuthBar");
        const accountLink = document.getElementById("digiseoNavAccountLink");
        const creditValue = document.getElementById("digiseoNavCreditValue");
        if (!bar || !accountLink || !creditValue) return;

        const credits =
            saas && saas.credit_balance != null
                ? saas.credit_balance
                : user && user.credit_balance != null
                  ? user.credit_balance
                  : 0;

        creditValue.textContent = formatCredits(credits);
        accountLink.setAttribute("title", formatCredits(credits) + " credit");
        bar.hidden = false;
    }

    function ensureFreeUsageBanner() {
        let el = document.getElementById("digiseoFreeUsageBanner");
        if (el) return el;
        el = document.createElement("div");
        el.id = "digiseoFreeUsageBanner";
        el.className = "digiseo-free-usage-banner";
        el.hidden = true;
        el.setAttribute("role", "status");
        const anchor =
            document.getElementById("digiseoTopNavStrip") ||
            document.querySelector(".nav-strip") ||
            document.querySelector("header.site-header");
        if (anchor && anchor.parentNode) {
            anchor.parentNode.insertBefore(el, anchor.nextSibling);
        } else {
            document.body.prepend(el);
        }
        return el;
    }

    function updateFreeUsageBanner(saas) {
        const el = ensureFreeUsageBanner();
        if (!saas || !saas.free_usage_active || saas.saas_trial_active) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        const days = Number(saas.free_usage_days_remaining || 0);
        const msg = saas.free_usage_banner || (days > 0 ? `Còn ${days} ngày dùng phần mềm` : "");
        let html = `<span class="digiseo-free-usage-banner__text">${msg}</span>`;
        if (saas.needs_credit_for_features) {
            html += ' <button type="button" class="digiseo-free-usage-banner__cta" data-digiseo-buy-credit="1">Mua credit</button>';
        }
        el.innerHTML = html;
        el.hidden = false;
    }

    function hideAccountSummary() {
        const bar = document.getElementById("digiseoNavAuthBar");
        if (bar) bar.hidden = true;
    }

    let _saasInflight = null;

    function fetchSaasMe(token, force) {
        if (!token) return Promise.resolve(null);
        if (!force && _saasInflight) return _saasInflight;

        _saasInflight = fetch("/api/saas/me", {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + token },
        })
            .then((r) => (r.ok ? r.json() : null))
            .catch(() => null)
            .finally(() => {
                _saasInflight = null;
            });

        return _saasInflight;
    }

    function syncBar(forceSaas) {
        ensureAccountSlot();
        const bar = ensureBar();
        if (!bar) return;

        removeLegacyAuthButtons();

        const t = getToken();
        if (!t) {
            hideAccountSummary();
            hideAdminNavLinks();
            const banner = document.getElementById("digiseoFreeUsageBanner");
            if (banner) banner.hidden = true;
            return;
        }

        const fetchMe = window.DigiSeoFetchAuthMe
            ? window.DigiSeoFetchAuthMe({ force: !!forceSaas })
            : fetch("/auth/me", { credentials: "same-origin", headers: { Authorization: "Bearer " + t } }).then((r) =>
                  r.ok ? r.json() : null
              );

        Promise.all([fetchMe, fetchSaasMe(t, !!forceSaas)])
            .then(([u, saas]) => {
                if (!u || !u.email) {
                    hideAccountSummary();
                    hideAdminNavLinks();
                    return;
                }
                setAccountSummary(saas, u);
                updateFreeUsageBanner(saas);
                if (typeof window.refreshDigiSeoAdminNav === "function") {
                    window.refreshDigiSeoAdminNav();
                }
            })
            .catch(() => {
                hideAccountSummary();
                hideAdminNavLinks();
            });
    }

    window.DigiSeoClearSession = function digiseoClearSession() {
        if (typeof window.DigiSeoClearAuthToken === "function") {
            window.DigiSeoClearAuthToken();
        } else {
            try {
                sessionStorage.removeItem(TOKEN_KEY);
            } catch (_) {}
            try {
                localStorage.removeItem(TOKEN_KEY);
            } catch (_) {}
            document.cookie = "seo_token=; path=/; max-age=0; SameSite=Lax" + cookieSecureSuffix();
        }
        if (typeof window.DigiSeoClearAuthMeCache === "function") {
            window.DigiSeoClearAuthMeCache();
        }
        if (typeof window.DigiSeoClearUserScopedStorage === "function") {
            window.DigiSeoClearUserScopedStorage();
        }
        hideAccountSummary();
        hideAdminNavLinks();
        if (typeof window.refreshDigiSeoGlobalDock === "function") {
            window.refreshDigiSeoGlobalDock();
        }
        window.dispatchEvent(new CustomEvent("digiseo-auth-change", { detail: { loggedIn: false } }));
    };

    window.DigiSeoLogout = function digiseoLogout() {
        window.DigiSeoClearSession();
        syncBar();
    };

    window.refreshDigiSeoNavAuth = syncBar;
    window.refreshDigiSeoNavAccount = function () {
        syncBar(true);
    };

    function init() {
        const hydrate =
            typeof window.DigiSeoHydrateSessionFromCookie === "function"
                ? window.DigiSeoHydrateSessionFromCookie(false)
                : Promise.resolve(getToken());
        hydrate
            .then(() => syncBar(true))
            .catch(() => syncBar());
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    window.addEventListener("digiseo-auth-change", () => syncBar(true));
    window.addEventListener("storage", (e) => {
        if (e.key === TOKEN_KEY || e.key === "digiseo_system_prefs_v1") syncBar(true);
    });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") syncBar(true);
    });
})();
