(() => {
    "use strict";

    const WIDGET_MAP = [
        { key: "content_ai_article", valId: "caUsageArticles", barId: "caUsageArticlesBar" },
        { key: "content_ai_brief", valId: "caUsageBriefs", barId: "caUsageBriefsBar" },
        { key: "image_generate", valId: "caUsageImages", barId: "caUsageImagesBar" },
        { key: "content_ai_bulk_article", valId: "caUsageBulk", barId: "caUsageBulkBar" },
        { key: "wp_publish", valId: "caUsagePublish", barId: "caUsagePublishBar" },
    ];

    const byId = (id) => document.getElementById(id);

    const readAuthHeaders = () => {
        const h = { "Content-Type": "application/json" };
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (!t) {
                const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
                t = m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
            }
            if (t) h.Authorization = "Bearer " + t;
        } catch (_) {}
        return h;
    };

    const formatQuotaText = (item) => {
        if (!item) return "—";
        const used = item.quantity_used || 0;
        const lim = item.limit_value;
        if (lim == null || lim === -1 || item.is_unlimited) {
            return lim === -1 || item.is_unlimited ? `${used} / ∞` : String(used);
        }
        return `${used} / ${lim}`;
    };

    const renderUsageBar = (barEl, item) => {
        if (!barEl || !item) {
            if (barEl) {
                barEl.style.width = "0%";
                barEl.className = "ca-usage-bar-fill";
            }
            return;
        }
        const used = item.quantity_used || 0;
        const lim = item.limit_value;
        if (lim == null || lim <= 0 || lim === -1 || item.is_unlimited) {
            barEl.style.width = "0%";
            barEl.className = "ca-usage-bar-fill";
            return;
        }
        const pct = Math.min(100, Math.round((used / lim) * 100));
        barEl.style.width = pct + "%";
        let cls = "ca-usage-bar-fill";
        if (pct >= 100) cls += " danger";
        else if (pct >= 80) cls += " warn";
        barEl.className = cls;
    };

    const openUpgradeModal = (message) => {
        const msgEl = byId("caQuotaModalMessage");
        if (msgEl && message) msgEl.textContent = message;
        const bd = byId("caQuotaModalBackdrop");
        if (bd) {
            bd.classList.add("open");
            bd.setAttribute("aria-hidden", "false");
        }
        if (typeof window.opendigiseoPricingModal === "function") {
            /* pricing modal opened via button inside quota modal */
        }
    };

    const closeQuotaModal = () => {
        const bd = byId("caQuotaModalBackdrop");
        if (bd) {
            bd.classList.remove("open");
            bd.setAttribute("aria-hidden", "true");
        }
    };

    const parseDetail = (detail) => {
        if (!detail) return {};
        if (typeof detail === "string") return { message: detail };
        if (typeof detail === "object" && !Array.isArray(detail)) return detail;
        return { message: String(detail) };
    };

    const isQuotaExceeded = (res, data) => {
        if (res && (res.status === 402 || res.status === 403)) {
            const d = parseDetail(data && data.detail);
            if (d.code === "quota_exceeded" || d.code === "insufficient_credits" || d.upgrade_required) return d;
            if (res.status === 403 && /hết quota|quota|gói|credit/i.test(String(d.message || ""))) return d;
            if (res.status === 402) return d;
        }
        return null;
    };

    const handleQuotaResponse = (res, data) => {
        const q = isQuotaExceeded(res, data);
        if (!q) return false;
        const msg =
            q.message ||
            "Bạn đã dùng hết quota tháng cho tính năng này. Nâng cấp gói để tiếp tục.";
        openUpgradeModal(msg);
        return true;
    };

    let _lastUsage = null;

    const loadUsagePanel = async () => {
        try {
            const res = await fetch("/content-ai/usage", {
                headers: readAuthHeaders(),
                credentials: "same-origin",
            });
            if (!res.ok) return null;
            const data = await res.json();
            _lastUsage = data;
            const planEl = byId("caUsagePlanName");
            const monthEl = byId("caUsageMonth");
            const panel = byId("caUsagePanel");
            const planLabel = data.plan_name || data.plan_slug || "Trial";
            if (planEl) planEl.textContent = planLabel;
            if (monthEl) monthEl.textContent = data.usage_month || "—";
            const triggerPlan = byId("caStudioTriggerPlan");
            if (triggerPlan) triggerPlan.textContent = "Gói: " + planLabel;
            const items = Array.isArray(data.items) ? data.items : [];
            const pick = (key) => items.find((q) => q.feature_key === key) || null;
            WIDGET_MAP.forEach(({ key, valId, barId }) => {
                const item = pick(key);
                const valEl = byId(valId);
                const barEl = byId(barId);
                const wrap = valEl ? valEl.closest(".ca-usage-item") : null;
                if (valEl) valEl.textContent = formatQuotaText(item);
                renderUsageBar(barEl, item);
                if (wrap) {
                    wrap.classList.toggle("ca-usage-item--warn", !!(item && item.is_warning && !item.is_over_quota));
                    wrap.classList.toggle("ca-usage-item--over", !!(item && item.is_over_quota));
                }
            });
            if (panel) {
                panel.classList.toggle("ca-usage-panel--warn", !!data.any_warning && !data.any_over_quota);
                panel.classList.toggle("ca-usage-panel--over", !!data.any_over_quota);
            }
            const warnEl = byId("caUsageWarnBanner");
            if (warnEl) {
                if (data.any_over_quota) {
                    warnEl.textContent = "Một số quota đã hết — nâng cấp gói để tiếp tục dùng AI.";
                    warnEl.hidden = false;
                } else if (data.any_warning) {
                    warnEl.textContent = "Bạn đã dùng trên 80% quota tháng — cân nhắc nâng cấp sớm.";
                    warnEl.hidden = false;
                } else {
                    warnEl.hidden = true;
                }
            }
            return data;
        } catch (_) {
            return null;
        }
    };

    const wireQuotaModal = () => {
        const bd = byId("caQuotaModalBackdrop");
        if (!bd) return;
        const closeBtn = byId("caQuotaModalClose");
        const dismissBtn = byId("caQuotaModalDismiss");
        if (closeBtn) closeBtn.addEventListener("click", closeQuotaModal);
        if (dismissBtn) dismissBtn.addEventListener("click", closeQuotaModal);
        bd.addEventListener("click", (e) => {
            if (e.target === bd) closeQuotaModal();
        });
        const upgradeBtn = byId("caQuotaModalUpgrade");
        if (upgradeBtn) {
            upgradeBtn.addEventListener("click", (ev) => {
                ev.preventDefault();
                closeQuotaModal();
                if (typeof window.opendigiseoPricingModal === "function") {
                    window.opendigiseoPricingModal();
                }
            });
        }
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && bd.classList.contains("open")) closeQuotaModal();
        });
    };

    const init = () => {
        wireQuotaModal();
        void loadUsagePanel();
    };

    window.ContentAiUsage = {
        loadUsagePanel,
        refresh: loadUsagePanel,
        handleQuotaResponse,
        openUpgradeModal,
        closeQuotaModal,
        getLastUsage: () => _lastUsage,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
