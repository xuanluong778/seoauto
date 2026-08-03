/**
 * System-wide user dock: popover menu, pill, upgrade strip.
 */
(function () {
    const TOKEN_KEY = "seo_token";
    let lastMe = null;

    function readCookieToken() {
        const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    }

    function getToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken();
        }
        try {
            let t = (sessionStorage.getItem(TOKEN_KEY) || "").trim();
            if (!t) {
                t = readCookieToken();
                if (t) sessionStorage.setItem(TOKEN_KEY, t);
            }
            return t;
        } catch (_) {
            return readCookieToken();
        }
    }

    function friendlyEmailLabel(email) {
        if (!email || typeof email !== "string") return "Chưa đăng nhập";
        const s = email.trim();
        if (s.length <= 30) return s;
        return s.slice(0, 28) + "…";
    }

    function avatarLetter(email) {
        const local = (email || "").split("@")[0] || "";
        const ch = local.trim().charAt(0);
        return ch ? ch.toUpperCase() : "?";
    }

    function formatCreatedVi(iso) {
        if (!iso) return "";
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return "";
            return (
                "Ngày tạo tài khoản: " +
                d.toLocaleString("vi-VN", { dateStyle: "medium", timeStyle: "short" })
            );
        } catch {
            return "";
        }
    }

    let dockRoot = null;
    let popover = null;
    let pill = null;
    let label = null;
    let avatar = null;
    let dismiss = null;
    let sessionLabel = null;
    let sessionIconIn = null;
    let sessionIconOut = null;
    let btnAccount = null;
    let btnHistory = null;
    let btnPackage = null;
    let btnSession = null;
    let dockTop = null;

    function bindDockElements() {
        if (!dockRoot) return false;
        popover = dockRoot.querySelector("#userMenuPopover");
        pill = dockRoot.querySelector("#userPill");
        label = dockRoot.querySelector("#userDockLabel");
        avatar = dockRoot.querySelector("#userDockAvatar");
        dismiss = dockRoot.querySelector("#userPillDismiss");
        sessionLabel = dockRoot.querySelector("#userMenuSessionLabel");
        sessionIconIn = dockRoot.querySelector("#userMenuSessionIconIn");
        sessionIconOut = dockRoot.querySelector("#userMenuSessionIconOut");
        btnAccount = dockRoot.querySelector("#userMenuAccount");
        btnHistory = dockRoot.querySelector("#userMenuHistory");
        btnPackage = dockRoot.querySelector("#userMenuPackage");
        btnSession = dockRoot.querySelector("#userMenuSession");
        dockTop = dockRoot.querySelector(".user-dock-top");
        return !!(pill && label && avatar);
    }

    const accountModal = document.getElementById("accountMiniModal");
    const accountEmail = document.getElementById("accountMiniEmail");
    const accountCreated = document.getElementById("accountMiniCreated");
    const accountClose = document.getElementById("accountMiniClose");

    function closePopover() {
        if (!popover || popover.hidden) return;
        popover.hidden = true;
        if (pill) pill.setAttribute("aria-expanded", "false");
    }

    function openPopover() {
        if (!popover) return;
        popover.hidden = false;
        if (pill) pill.setAttribute("aria-expanded", "true");
    }

    function togglePopover() {
        if (!popover) return;
        if (popover.hidden) openPopover();
        else closePopover();
    }

    function setSessionRow(loggedIn) {
        if (sessionLabel) sessionLabel.textContent = loggedIn ? "Đăng xuất" : "Đăng nhập";
        if (sessionIconIn) sessionIconIn.hidden = !!loggedIn;
        if (sessionIconOut) sessionIconOut.hidden = !loggedIn;
    }

    function setGuestUi() {
        lastMe = null;
        setSessionRow(false);
        if (label) label.textContent = "Chưa đăng nhập";
        if (avatar) {
            avatar.textContent = "?";
            avatar.classList.add("is-guest");
        }
        if (pill) pill.hidden = false;
    }

    async function refreshUserDock() {
        if (!label || !avatar) return;
        closePopover();
        const token = getToken();
        if (!token) {
            setGuestUi();
            return;
        }
        setSessionRow(true);
        try {
            const d = window.DigiSeoFetchAuthMe
                ? await window.DigiSeoFetchAuthMe()
                : await fetch("/auth/me", {
                    credentials: "same-origin",
                    headers: { Authorization: "Bearer " + token },
                }).then((r) => (r.ok ? r.json().catch(() => null) : null));
            if (!d || !d.email) {
                if (label) label.textContent = "Đã đăng nhập";
                if (avatar) {
                    avatar.textContent = "U";
                    avatar.classList.remove("is-guest");
                }
                if (pill) pill.hidden = false;
                return;
            }
            lastMe = d;
            label.textContent = friendlyEmailLabel(d.email);
            avatar.textContent = avatarLetter(d.email);
            avatar.classList.remove("is-guest");
            if (pill) pill.hidden = false;
        } catch {
            setGuestUi();
        }
    }

    function openAuthModalDirect() {
        if (typeof window.DigiSeoOpenLoginModal === "function") {
            window.DigiSeoOpenLoginModal();
            return true;
        }
        const authModal = document.getElementById("authModal");
        if (authModal) {
            authModal.hidden = false;
            if (typeof window.DigiSeoSetAuthTab === "function") {
                window.DigiSeoSetAuthTab("login");
            }
            const authPassword = document.getElementById("authPassword");
            if (authPassword) authPassword.value = "";
            const authEmail = document.getElementById("authEmail");
            if (authEmail) {
                try {
                    authEmail.focus();
                } catch (_) {}
            }
            return true;
        }
        return false;
    }

    function triggerLogin() {
        if (openAuthModalDirect()) return;
        const local = document.getElementById("btnOpenLogin");
        if (local) {
            try {
                local.click();
            } catch (_) {}
            return;
        }
        if (typeof window.DigiSeoGoLogin === "function") {
            window.DigiSeoGoLogin();
            return;
        }
        window.location.assign("/tool");
    }

    function triggerLogout() {
        if (typeof window.DigiSeoLogout === "function") {
            window.DigiSeoLogout();
            return;
        }
        if (typeof window.DigiSeoClearSession === "function") {
            window.DigiSeoClearSession();
            return;
        }
        try {
            sessionStorage.removeItem(TOKEN_KEY);
        } catch (_) {}
        document.cookie = "seo_token=; path=/; max-age=0; SameSite=Lax";
        refreshUserDock();
    }

    async function openAccountModal() {
        closePopover();
        const token = getToken();
        if (!token) {
            triggerLogin();
            return;
        }
        let d = lastMe;
        if (!d || !d.email) {
            try {
                const r = await fetch("/auth/me", {
                    headers: { Authorization: "Bearer " + token },
                });
                const parsed = await r.json().catch(() => null);
                if (r.ok && parsed) {
                    d = parsed;
                    lastMe = parsed;
                }
            } catch {
                d = null;
            }
        }
        if (accountModal) {
            if (accountEmail) accountEmail.textContent = d && d.email ? String(d.email) : "—";
            if (accountCreated)
                accountCreated.textContent = d && d.created_at ? formatCreatedVi(d.created_at) : "";
            accountModal.hidden = false;
            return;
        }
        window.location.href = "/settings#account";
    }

    function onHistoryClick() {
        closePopover();
        const sidebarMain = document.querySelector(".sidebar-main");
        if (sidebarMain) {
            sidebarMain.scrollTo({ top: 0, behavior: "smooth" });
            sidebarMain.classList.remove("sb-dock-flash");
            void sidebarMain.offsetWidth;
            sidebarMain.classList.add("sb-dock-flash");
            window.setTimeout(() => sidebarMain.classList.remove("sb-dock-flash"), 2000);
            return;
        }
        const features = document.querySelector(".features-wrap");
        if (features) {
            features.scrollIntoView({ behavior: "smooth", block: "start" });
            features.classList.remove("home-dock-flash");
            void features.offsetWidth;
            features.classList.add("home-dock-flash");
            window.setTimeout(() => features.classList.remove("home-dock-flash"), 2000);
            return;
        }
        window.location.href = "/report";
    }

    function onPackageClick() {
        closePopover();
        if (typeof window.opendigiseoPricingModal === "function") {
            window.opendigiseoPricingModal();
            return;
        }
        window.location.href = "/account-billing?tab=plans";
    }

    function wireDock() {
        if (!dockRoot) return;

        if (pill && popover) {
            pill.addEventListener("click", () => {
                if (!getToken()) {
                    triggerLogin();
                    return;
                }
                togglePopover();
            });
            pill.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    if (!getToken()) triggerLogin();
                    else togglePopover();
                }
            });
        }
        if (dismiss) {
            dismiss.addEventListener("click", (e) => {
                e.stopPropagation();
                closePopover();
            });
        }
        if (dockTop) {
            dockTop.addEventListener("click", () => togglePopover());
        }
        document.addEventListener("mousedown", (e) => {
            if (!popover || popover.hidden || !dockRoot) return;
            if (!dockRoot.contains(e.target)) closePopover();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closePopover();
        });

        if (btnAccount) btnAccount.addEventListener("click", () => openAccountModal());
        if (btnHistory) btnHistory.addEventListener("click", onHistoryClick);
        if (btnPackage) btnPackage.addEventListener("click", onPackageClick);
        if (btnSession) {
            btnSession.addEventListener("click", () => {
                closePopover();
                if (getToken()) triggerLogout();
                else triggerLogin();
            });
        }
        if (accountClose && accountModal) {
            accountClose.addEventListener("click", () => {
                accountModal.hidden = true;
            });
        }
        if (accountModal) {
            accountModal.addEventListener("click", (e) => {
                if (e.target === accountModal) accountModal.hidden = true;
            });
        }

        const wrap = document.getElementById("globalUserDockWrap");
        if (wrap && dismiss) {
            dismiss.addEventListener("click", (e) => {
                e.stopPropagation();
                try {
                    sessionStorage.setItem("digiseo_global_dock_hidden", "1");
                } catch (_) {}
                wrap.hidden = true;
            });
        }

        refreshUserDock();
    }

    window.refreshDigiSeoUserDock = refreshUserDock;
    window.refreshDigiSeoGlobalDock = refreshUserDock;

    function resolveDockRoot() {
        return (
            document.getElementById("sidebarUserDock") ||
            document.getElementById("globalUserDockWrap") ||
            document.querySelector("[data-digiseo-user-dock-root]")
        );
    }

    function init() {
        const dockMode = document.body ? document.body.getAttribute("data-user-dock") : "";
        const globalWrap = document.getElementById("globalUserDockWrap");
        const sidebarWrap = document.getElementById("sidebarUserDock");
        if (globalWrap && sidebarWrap && globalWrap !== sidebarWrap) {
            globalWrap.remove();
        } else if (globalWrap && (dockMode === "sidebar" || dockMode === "hidden")) {
            globalWrap.remove();
        } else if (globalWrap && dockMode === "upgrade-only") {
            globalWrap.classList.add("is-upgrade-only");
            const p = document.getElementById("userPill");
            const pop = document.getElementById("userMenuPopover");
            const top = globalWrap.querySelector(".user-dock-top");
            if (p) p.remove();
            if (pop) pop.remove();
            if (top) top.remove();
        }

        if (globalWrap) {
            let hid = false;
            try {
                hid = sessionStorage.getItem("digiseo_global_dock_hidden") === "1";
            } catch (_) {}
            if (hid) globalWrap.hidden = true;
        }

        dockRoot = resolveDockRoot();
        if (!bindDockElements()) return;
        wireDock();
    }

    window.addEventListener("digiseo-auth-change", refreshUserDock);
    window.addEventListener("storage", (e) => {
        if (e.key === TOKEN_KEY) refreshUserDock();
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
