/**
 * SEOAuto account avatar widget — góc trái dưới, popup tài khoản.
 */
(function () {
    "use strict";

    var TOKEN_KEY = "seo_token";
    var root = null;
    var popover = null;
    var avatarBtn = null;
    var avatarEl = null;
    var emailEl = null;
    var planEl = null;
    var creditsEl = null;
    var upgradeBtn = null;
    var adminLink = null;
    var sessionBtn = null;
    var trialHint = null;
    var activateTrialBtn = null;
    var buyCreditBtn = null;
    var lastMe = null;
    var lastSaas = null;
    var lastTrial = null;

    function getToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken();
        }
        try {
            var t = (sessionStorage.getItem(TOKEN_KEY) || "").trim();
            if (!t) {
                var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
                t = m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
                if (t) sessionStorage.setItem(TOKEN_KEY, t);
            }
            return t;
        } catch (_) {
            var m2 = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            return m2 ? decodeURIComponent(m2[1].replace(/\+/g, " ")).trim() : "";
        }
    }

    function avatarLetter(email) {
        var local = String(email || "").split("@")[0] || "";
        var ch = local.trim().charAt(0);
        return ch ? ch.toUpperCase() : "?";
    }

    function formatCredits(n) {
        var v = Number(n);
        if (!Number.isFinite(v)) return "0";
        return v.toLocaleString("vi-VN");
    }

    function resolvePlanLabel(saas) {
        if (!saas || typeof saas !== "object") return "Chưa có gói";
        if (saas.saas_trial_active) {
            var d = Number(saas.saas_trial_days_remaining || 0);
            return d > 0 ? "Còn " + d + " ngày dùng thử" : "Hết dùng thử";
        }
        if (saas.free_usage_active && !saas.plan_slug) {
            var days = Number(saas.free_usage_days_remaining || 0);
            return days > 0 ? "Còn " + days + " ngày dùng phần mềm" : "Chưa có gói";
        }
        if (saas.plan_name) {
            var pn = String(saas.plan_name).trim();
            var slug = String(saas.plan_slug || "").toLowerCase();
            if (slug === "trial_3d" || slug === "free_trial_5d" || /trial/i.test(pn)) {
                return "Dùng thử 3 ngày";
            }
            return pn;
        }
        if (saas.plan_slug) {
            var ps = String(saas.plan_slug).toLowerCase();
            if (ps === "trial_3d" || ps === "free_trial_5d") return "Dùng thử 3 ngày";
            return String(saas.plan_slug);
        }
        var trial = String(saas.trial_status || "").toLowerCase();
        if (trial === "active" || trial === "pending") return "Dùng thử 3 ngày";
        if (trial === "admin") return "Admin";
        return "Chưa có gói";
    }

    function getDeviceFingerprint() {
        var fp = "";
        try {
            fp = (localStorage.getItem("digiseo_device_fp") || "").trim();
            if (!fp) {
                fp = "fp_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
                localStorage.setItem("digiseo_device_fp", fp);
            }
        } catch (_) {}
        return fp;
    }

    function fetchTrialStatus(token) {
        if (!token) return Promise.resolve(null);
        var fp = getDeviceFingerprint();
        var url = "/api/trial/status";
        if (fp) {
            url += "?device_fingerprint=" + encodeURIComponent(fp);
        }
        return fetch(url, {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + token },
        })
            .then(function (r) {
                return r.ok ? r.json() : null;
            })
            .catch(function () {
                return null;
            });
    }

    function hasPaidPlan(saas) {
        if (!saas || !saas.plan_slug) return false;
        var slug = String(saas.plan_slug || "").toLowerCase();
        return slug && slug !== "trial_3d" && slug !== "free_trial_5d";
    }

    function updateTrialActions(saas, trial) {
        if (!activateTrialBtn || !buyCreditBtn) return;
        lastTrial = trial;
        if (!saas || !trial) {
            activateTrialBtn.hidden = true;
            buyCreditBtn.hidden = true;
            if (trialHint) {
                trialHint.hidden = true;
                trialHint.textContent = "";
            }
            return;
        }

        var canActivate = !!trial.can_activate;
        var active = !!trial.trial_active;
        var freeUsage = !!trial.free_usage_active || !!saas.free_usage_active;
        var claimBlocked = !!trial.trial_claim_blocked;
        var needsCredit =
            !!trial.needs_credit ||
            !!saas.needs_credit_for_features ||
            !!trial.need_credit_message ||
            !!saas.saas_trial_need_credit_message;
        var paid = hasPaidPlan(saas);

        var showActivate = canActivate && !freeUsage && !claimBlocked;
        var showBuyCredit = !paid || showActivate || needsCredit || active || freeUsage;

        var hint = "";
        if (showActivate) {
            hint =
                "Dùng thử SEOAuto 3 ngày — Content AI, Auto Update, SEO Score, Technical Audit. Cần mua credit để sử dụng.";
        } else if (freeUsage && needsCredit && !active) {
            hint =
                saas.free_usage_need_credit_message ||
                "Vui lòng mua credit để sử dụng các tính năng.";
        }

        if (trialHint) {
            trialHint.textContent = hint;
            trialHint.hidden = !hint;
        }
        activateTrialBtn.hidden = !showActivate;
        buyCreditBtn.hidden = !showBuyCredit;
    }

    function updateTrialPanel(saas, trial) {
        updateTrialActions(saas, trial);
    }

    function activateSaasTrial() {
        var token = getToken();
        if (!token) {
            openLogin();
            return;
        }
        if (activateTrialBtn) {
            activateTrialBtn.disabled = true;
            activateTrialBtn.textContent = "Đang kích hoạt…";
        }
        var fp = getDeviceFingerprint();
        fetch("/api/trial/activate", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                Authorization: "Bearer " + token,
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ device_fingerprint: fp || null }),
        })
            .then(function (r) {
                return r.json().then(function (d) {
                    return { ok: r.ok, data: d };
                });
            })
            .then(function (res) {
                if (!res.ok) {
                    var detail = res.data && (res.data.detail || res.data.message);
                    alert(typeof detail === "string" ? detail : "Không kích hoạt được dùng thử.");
                    return;
                }
                if (typeof window.refreshDigiSeoNavAccount === "function") {
                    window.refreshDigiSeoNavAccount();
                }
                if (typeof window.syncDigiSeoSaasTrialBanner === "function") {
                    window.syncDigiSeoSaasTrialBanner(true);
                }
                refreshAccountWidget();
            })
            .catch(function () {
                alert("Lỗi mạng — thử lại sau.");
            })
            .finally(function () {
                if (activateTrialBtn) {
                    activateTrialBtn.disabled = false;
                    activateTrialBtn.textContent = "Kích hoạt dùng thử 3 ngày";
                }
            });
    }

    function fetchSaasMe(token) {
        if (!token) return Promise.resolve(null);
        return fetch("/api/saas/me", {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + token },
        })
            .then(function (r) {
                return r.ok ? r.json() : null;
            })
            .catch(function () {
                return null;
            });
    }

    function fetchAuthMe(token) {
        if (window.DigiSeoFetchAuthMe) {
            return window.DigiSeoFetchAuthMe();
        }
        return fetch("/auth/me", {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + token },
        })
            .then(function (r) {
                return r.ok ? r.json().catch(function () {
                    return null;
                }) : null;
            })
            .catch(function () {
                return null;
            });
    }

    function isAdminUser(me) {
        if (typeof window.DigiSeoIsAdminUser === "function") {
            return window.DigiSeoIsAdminUser(me);
        }
        if (!me || typeof me !== "object") return false;
        if (me.show_admin_nav === true) return true;
        var role = String(me.role || "").toLowerCase();
        return role === "admin" || role === "super_admin";
    }

    function isLoggedInUser(me) {
        if (!me || typeof me !== "object") return false;
        if (me.id != null) return true;
        return !!String(me.email || "").trim();
    }

    function applyAdminNavPolicy(me) {
        if (typeof window.DigiSeoApplyAdminNavPolicy === "function") {
            window.DigiSeoApplyAdminNavPolicy(me);
        } else {
            var isAdmin = isAdminUser(me);
            var isLoggedIn = isLoggedInUser(me);
            if (document.body) {
                document.body.classList.toggle("digiseo-admin-nav-via-avatar", isLoggedIn);
            }
            document.querySelectorAll("[data-nav-account-billing]").forEach(function (el) {
                el.hidden = isLoggedIn;
            });
            document.querySelectorAll("[data-nav-admin]").forEach(function (el) {
                el.hidden = isAdmin;
            });
        }
        if (adminLink) {
            adminLink.hidden = !isAdminUser(me);
        }
    }

    function setGuestUi() {
        lastMe = null;
        lastSaas = null;
        if (!root) return;
        root.classList.add("is-guest");
        if (avatarEl) {
            avatarEl.textContent = "?";
            avatarEl.classList.add("is-guest");
        }
        if (emailEl) emailEl.textContent = "Chưa đăng nhập";
        if (planEl) planEl.textContent = "—";
        if (creditsEl) creditsEl.textContent = "—";
        if (sessionBtn) sessionBtn.textContent = "Đăng nhập";
        if (avatarBtn) avatarBtn.title = "Đăng nhập";
        updateTrialActions(null, null);
    }

    function setLoggedInUi(me, saas) {
        if (!root) return;
        root.classList.remove("is-guest");
        lastMe = me;
        lastSaas = saas;
        var email = me && me.email ? String(me.email) : "";
        if (avatarEl) {
            avatarEl.textContent = avatarLetter(email || "U");
            avatarEl.classList.remove("is-guest");
        }
        if (emailEl) emailEl.textContent = email || "Đã đăng nhập";
        if (planEl) planEl.textContent = resolvePlanLabel(saas);
        var credits =
            saas && saas.credit_balance != null
                ? saas.credit_balance
                : me && me.credit_balance != null
                  ? me.credit_balance
                  : 0;
        if (creditsEl) creditsEl.textContent = formatCredits(credits);
        if (sessionBtn) sessionBtn.textContent = "Đăng xuất";
        if (avatarBtn) avatarBtn.title = email || "Tài khoản";
        updateTrialActions(saas, lastTrial);
    }

    function closePopover() {
        if (!popover || popover.hidden) return;
        popover.hidden = true;
        popover.classList.remove("is-below");
        if (avatarBtn) avatarBtn.setAttribute("aria-expanded", "false");
    }

    function clampPopoverPosition() {
        if (!popover || popover.hidden || !root) return;
        popover.classList.remove("is-below");
        var rect = popover.getBoundingClientRect();
        if (rect.top < 8) {
            popover.classList.add("is-below");
            rect = popover.getBoundingClientRect();
        }
        if (rect.right > window.innerWidth - 8) {
            var shift = rect.right - (window.innerWidth - 8);
            popover.style.left = Math.max(0, -shift) + "px";
        } else {
            popover.style.left = "0";
        }
        if (rect.left < 8) {
            popover.style.left = 8 - root.getBoundingClientRect().left + "px";
        }
    }

    function openPopover() {
        if (!popover || !avatarBtn) return;
        popover.hidden = false;
        avatarBtn.setAttribute("aria-expanded", "true");
        popover.style.left = "0";
        clampPopoverPosition();
    }

    function togglePopover() {
        if (!popover) return;
        if (popover.hidden) openPopover();
        else closePopover();
    }

    function openLogin() {
        closePopover();
        if (typeof window.DigiSeoOpenLoginModal === "function") {
            window.DigiSeoOpenLoginModal();
            return;
        }
        var authModal = document.getElementById("authModal");
        if (authModal) {
            authModal.hidden = false;
            if (typeof window.DigiSeoSetAuthTab === "function") {
                window.DigiSeoSetAuthTab("login");
            }
            return;
        }
        if (typeof window.DigiSeoGoLogin === "function") {
            window.DigiSeoGoLogin();
            return;
        }
        window.location.assign("/tool");
    }

    function triggerLogout() {
        closePopover();
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
        window.dispatchEvent(new CustomEvent("digiseo-auth-change"));
        refreshAccountWidget();
    }

    function openBuyCredit() {
        closePopover();
        if (typeof window.DigiSeoOpenCreditModal === "function") {
            window.DigiSeoOpenCreditModal();
            return;
        }
        window.location.href = "/account-billing?tab=plans&plans=credit";
    }

    function openUpgrade() {
        closePopover();
        if (typeof window.opendigiseoPricingModal === "function") {
            window.opendigiseoPricingModal();
            return;
        }
        window.location.href = "/account-billing?tab=plans";
    }

    async function refreshAccountWidget() {
        closePopover();
        var token = getToken();
        if (!token) {
            applyAdminNavPolicy(null);
            if (!root) return;
            root.hidden = false;
            setGuestUi();
            return;
        }
        try {
            var me = await fetchAuthMe(token);
            applyAdminNavPolicy(me);
            if (!root) return;
            root.hidden = false;
            var saas = await fetchSaasMe(token);
            var trial = await fetchTrialStatus(token);
            if (!me || !me.email) {
                setGuestUi();
                return;
            }
            updateTrialActions(saas, trial);
            setLoggedInUi(me, saas);
        } catch (_) {
            applyAdminNavPolicy(null);
            if (!root) return;
            setGuestUi();
        }
    }

    function onDocumentPointerDown(e) {
        if (!popover || popover.hidden || !root) return;
        if (!root.contains(e.target)) closePopover();
    }

    function wireEvents() {
        if (!avatarBtn) return;

        avatarBtn.addEventListener("click", function () {
            var token = getToken();
            if (!token) {
                openLogin();
                return;
            }
            togglePopover();
        });

        avatarBtn.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                avatarBtn.click();
            }
        });

        if (upgradeBtn) {
            upgradeBtn.addEventListener("click", function (e) {
                if (typeof window.opendigiseoPricingModal !== "function") {
                    e.preventDefault();
                    openUpgrade();
                }
            });
        }

        if (activateTrialBtn) {
            activateTrialBtn.addEventListener("click", activateSaasTrial);
        }

        if (buyCreditBtn) {
            buyCreditBtn.addEventListener("click", function (e) {
                e.preventDefault();
                if (typeof window.DigiSeoOpenCreditModal === "function") {
                    closePopover();
                    window.DigiSeoOpenCreditModal();
                    return;
                }
                openBuyCredit();
            });
        }

        if (sessionBtn) {
            sessionBtn.addEventListener("click", function () {
                if (getToken()) triggerLogout();
                else openLogin();
            });
        }

        document.addEventListener("mousedown", onDocumentPointerDown);
        document.addEventListener("touchstart", onDocumentPointerDown, { passive: true });
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") closePopover();
        });
        window.addEventListener("resize", function () {
            if (!popover || popover.hidden) return;
            clampPopoverPosition();
        });
    }

    function bindElements() {
        root = document.getElementById("digiseoAccountWidget");
        if (!root) return false;
        popover = root.querySelector("#dawPopover");
        avatarBtn = root.querySelector("#dawAvatarBtn");
        avatarEl = root.querySelector("#dawAvatar");
        emailEl = root.querySelector("#dawEmail");
        planEl = root.querySelector("#dawPlan");
        creditsEl = root.querySelector("#dawCredits");
        upgradeBtn = root.querySelector("#dawUpgrade");
        adminLink = root.querySelector("#dawAdminLink");
        sessionBtn = root.querySelector("#dawSessionBtn");
        trialHint = root.querySelector("#dawTrialHint");
        activateTrialBtn = root.querySelector("#dawActivateTrial");
        buyCreditBtn = root.querySelector("#dawBuyCredit");
        return !!(popover && avatarBtn && avatarEl);
    }

    function init() {
        if (!bindElements()) return;
        if (adminLink && window.DigiSeoI18n && typeof window.DigiSeoI18n.t === "function") {
            var i18nKey = adminLink.getAttribute("data-i18n");
            if (i18nKey) {
                adminLink.textContent = window.DigiSeoI18n.t(window.DigiSeoI18n.readLang(), i18nKey);
            }
        }
        wireEvents();
        refreshAccountWidget();
    }

    window.syncDigiSeoAccountNavFromUser = applyAdminNavPolicy;
    window.refreshDigiSeoAccountWidget = refreshAccountWidget;
    window.refreshDigiSeoGlobalDock = refreshAccountWidget;
    window.refreshDigiSeoUserDock = refreshAccountWidget;

    window.addEventListener("digiseo-auth-change", refreshAccountWidget);
    window.addEventListener("storage", function (e) {
        if (e.key === TOKEN_KEY) refreshAccountWidget();
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
