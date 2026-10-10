/**
 * Global SaaS 3-day trial banner + activate button.
 */
(function () {
    "use strict";

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function getToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken();
        }
        try {
            return (sessionStorage.getItem("seo_token") || "").trim();
        } catch (_) {
            return "";
        }
    }

    function ensureBanner() {
        var el = document.getElementById("digiseoSaasTrialBanner");
        if (el) return el;
        el = document.createElement("div");
        el.id = "digiseoSaasTrialBanner";
        el.className = "digiseo-saas-trial-banner";
        el.hidden = true;
        el.setAttribute("role", "region");
        el.setAttribute("aria-label", "Dùng thử SEOAuto");
        var anchor =
            document.getElementById("digiseoFreeUsageBanner") ||
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

    function renderBanner(data) {
        var el = ensureBanner();
        if (!data) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        // SSOT from backend: paid / free-usage users never see trial-expired upgrade nag.
        if (data.has_paid_plan || data.free_usage_active) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        var canActivate = !!data.saas_trial_can_activate;
        var active = !!data.saas_trial_active;
        var used = !!data.saas_trial_used;
        var claimBlocked = !!data.trial_claim_blocked;
        if (active) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        if (claimBlocked && !active && !canActivate) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        if (!canActivate && !active && !used) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        if (used && !active && data.show_upgrade_banner === false) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        var msg =
            data.saas_trial_banner ||
            data.saas_trial_need_credit_message ||
            "";
        if (!msg && canActivate) {
            msg = "Bạn chưa kích hoạt dùng thử 3 ngày.";
        }
        if (!msg) {
            el.hidden = true;
            el.innerHTML = "";
            return;
        }
        var html = '<span class="digiseo-saas-trial-banner__text">' + esc(msg) + "</span>";
        if (canActivate) {
            html +=
                ' <button type="button" class="digiseo-saas-trial-banner__btn" id="btnActivateSaasTrial">Kích hoạt dùng thử</button>';
            html +=
                ' <button type="button" class="digiseo-saas-trial-banner__cta" data-digiseo-buy-credit="1">Mua credit</button>';
        } else if (data.needs_credit_for_features || data.saas_trial_need_credit_message) {
            html +=
                ' <button type="button" class="digiseo-saas-trial-banner__cta" data-digiseo-buy-credit="1">Mua credit</button>';
        } else if (used && !active && data.show_upgrade_banner !== false) {
            html += ' <a href="/pricing" class="digiseo-saas-trial-banner__cta">Nâng cấp gói</a>';
        }
        el.innerHTML = html;
        el.hidden = false;
        var btn = document.getElementById("btnActivateSaasTrial");
        if (btn && !btn.dataset.wired) {
            btn.dataset.wired = "1";
            btn.addEventListener("click", activateTrial);
        }
        el.querySelectorAll("[data-digiseo-buy-credit]").forEach(function (buyBtn) {
            if (buyBtn.dataset.wired) return;
            buyBtn.dataset.wired = "1";
            buyBtn.addEventListener("click", function (e) {
                e.preventDefault();
                if (typeof window.DigiSeoOpenCreditModal === "function") {
                    window.DigiSeoOpenCreditModal();
                } else {
                    window.location.href = "/account-billing?tab=plans&plans=credit";
                }
            });
        });
    }

    function activateTrial() {
        var token = getToken();
        if (!token) {
            if (typeof window.DigiSeoOpenAuthModal === "function") {
                window.DigiSeoOpenAuthModal("login");
            }
            return;
        }
        var btn = document.getElementById("btnActivateSaasTrial");
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Đang kích hoạt…";
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
                    syncTrialBanner(true);
                    return;
                }
                if (typeof window.refreshDigiSeoNavAccount === "function") {
                    window.refreshDigiSeoNavAccount();
                }
                syncTrialBanner(true);
            })
            .catch(function () {
                alert("Lỗi mạng — thử lại sau.");
            })
            .finally(function () {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = "Kích hoạt dùng thử";
                }
            });
    }

    function syncTrialBanner(force) {
        var token = getToken();
        if (!token) {
            renderBanner(null);
            return;
        }
        var fp = getDeviceFingerprint();
        var url = "/api/trial/status";
        if (fp) {
            url += "?device_fingerprint=" + encodeURIComponent(fp);
        }
        fetch(url, {
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + token },
        })
            .then(function (r) {
                return r.ok ? r.json() : null;
            })
            .then(function (status) {
                if (!status) {
                    renderBanner(null);
                    return;
                }
                renderBanner({
                    saas_trial_can_activate: status.can_activate,
                    saas_trial_active: status.trial_active,
                    saas_trial_used: status.trial_used,
                    saas_trial_banner: status.banner,
                    saas_trial_need_credit_message: status.need_credit_message,
                    needs_credit_for_features: status.needs_credit,
                    free_usage_active: status.free_usage_active,
                    trial_claim_blocked: status.trial_claim_blocked,
                    has_paid_plan: !!status.has_paid_plan,
                    effective_plan_slug: status.effective_plan_slug || null,
                    show_upgrade_banner: status.show_upgrade_banner !== false,
                    show_trial_expired_banner: !!status.show_trial_expired_banner,
                });
            })
            .catch(function () {
                renderBanner(null);
            });
    }

    window.syncDigiSeoSaasTrialBanner = syncTrialBanner;

    function init() {
        syncTrialBanner(false);
        window.addEventListener("digiseo-auth-change", function () {
            syncTrialBanner(true);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
