(function () {
    "use strict";

    const API = "/api/admin/saas/pricing-plans";
    const FIELD_DEFS = [
        { key: "month_price", label: "Giá tháng (VND)", type: "number" },
        { key: "year_price", label: "Giá năm (VND)", type: "number" },
        { key: "credit_per_month", label: "Credit/tháng", type: "number" },
        { key: "users", label: "Số user", type: "number" },
        { key: "projects", label: "Website/project", type: "number" },
        { key: "ai_articles_per_month", label: "Bài AI/tháng", type: "number" },
        { key: "bulk_writer_per_run", label: "Bulk writer/lần", type: "number" },
        { key: "rank_tracking", label: "Rank Tracking limit", type: "number" },
        { key: "technical_audit", label: "Technical Audit limit", type: "number" },
        { key: "crawl_per_run", label: "Crawl limit/lần", type: "number" },
        { key: "seo_score", label: "SEO Score limit", type: "number" },
        { key: "auto_update", label: "Auto Update limit", type: "number" },
        { key: "saved_articles_max", label: "Bài viết lưu tối đa", type: "number" },
    ];

    let plans = [];
    let pendingSaveSlug = null;
    let pendingResetSlug = null;
    let confirmCallback = null;

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function fmtVnd(n) {
        return Number(n || 0).toLocaleString("vi-VN") + "đ";
    }

    function readToken() {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
        } catch (_) {}
        return "";
    }

    function authHeaders(extra) {
        const h = Object.assign({}, extra || {});
        const t = readToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    async function apiGet(path) {
        const res = await fetch(path, { headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (res.status === 403) throw new Error("Chỉ admin mới truy cập được.");
        if (!res.ok) throw new Error(data.detail || data.message || data.error || "HTTP " + res.status);
        return data;
    }

    async function apiPut(path, body) {
        const res = await fetch(path, {
            method: "PUT",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.message || data.error || "HTTP " + res.status);
        return data;
    }

    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.message || data.error || "HTTP " + res.status);
        return data;
    }

    let toastTimer = null;
    function showToast(msg) {
        const el = byId("admPricingToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        el.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            el.classList.remove("is-visible");
            setTimeout(() => { el.hidden = true; }, 300);
        }, 2400);
    }

    function openModal(id) {
        const el = byId(id);
        if (el) el.hidden = false;
    }

    function closeModal(id) {
        const el = byId(id);
        if (el) el.hidden = true;
    }

    function confirmSave(title, desc, onOk) {
        byId("admPricingConfirmTitle").textContent = title;
        byId("admPricingConfirmDesc").textContent = desc;
        confirmCallback = onOk;
        openModal("admPricingConfirmModal");
    }

    function readForm(slug) {
        const root = document.querySelector(`[data-plan-form="${slug}"]`);
        if (!root) return null;
        const body = {};
        FIELD_DEFS.forEach((f) => {
            const el = root.querySelector(`[name="${f.key}"]`);
            body[f.key] = el ? parseInt(el.value, 10) || 0 : 0;
        });
        body.is_popular = !!(root.querySelector('[name="is_popular"]') && root.querySelector('[name="is_popular"]').checked);
        body.is_active = !!(root.querySelector('[name="is_active"]') && root.querySelector('[name="is_active"]').checked);
        return body;
    }

    function renderPlans() {
        const grid = byId("admPricingGrid");
        if (!grid) return;
        grid.innerHTML = plans.map((p) => {
            const fields = FIELD_DEFS.map((f) => `
                <div class="adm-plan-field">
                    <label for="${esc(p.slug)}_${esc(f.key)}">${esc(f.label)}</label>
                    <input type="number" min="0" step="1" id="${esc(p.slug)}_${esc(f.key)}"
                        name="${esc(f.key)}" value="${esc(p[f.key])}" />
                </div>
            `).join("");
            const popularCls = p.is_popular ? " is-popular" : "";
            const inactiveCls = p.is_active ? "" : " is-inactive";
            return `
                <article class="adm-plan-card${popularCls}${inactiveCls}" data-plan-card="${esc(p.slug)}">
                    <div class="adm-plan-card-head">
                        <div>
                            <div class="adm-plan-slug">${esc(p.slug)}</div>
                            <h2>${esc(p.name)}</h2>
                            <p class="ab-muted-text">${esc(p.fit || "")}</p>
                        </div>
                        <div>
                            ${p.is_popular ? '<span class="ab-badge active">Phổ biến</span>' : ""}
                            ${p.is_active ? "" : '<span class="ab-badge suspended">Tắt</span>'}
                        </div>
                    </div>
                    <form class="adm-plan-form" data-plan-form="${esc(p.slug)}" onsubmit="return false;">
                        ${fields}
                        <div class="adm-plan-checks">
                            <label><input type="checkbox" name="is_popular" ${p.is_popular ? "checked" : ""} /> Phổ biến nhất</label>
                            <label><input type="checkbox" name="is_active" ${p.is_active ? "checked" : ""} /> Đang bán (is_active)</label>
                        </div>
                        <div class="adm-plan-actions">
                            <button type="button" class="ab-btn" data-save-plan="${esc(p.slug)}">Lưu gói</button>
                            <button type="button" class="ab-btn secondary" data-reset-plan="${esc(p.slug)}">Reset gói này</button>
                        </div>
                    </form>
                </article>
            `;
        }).join("");

        grid.querySelectorAll("[data-save-plan]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const slug = btn.getAttribute("data-save-plan");
                const plan = plans.find((x) => x.slug === slug);
                const body = readForm(slug);
                if (!body || !plan) return;
                pendingSaveSlug = slug;
                confirmSave(
                    "Xác nhận lưu " + (plan.name || slug),
                    `Giá tháng: ${fmtVnd(body.month_price)} · Credit/tháng: ${body.credit_per_month.toLocaleString("vi-VN")}. Thay đổi sẽ áp dụng lên trang /pricing và Tài khoản & Thanh toán.`,
                    async () => {
                        const updated = await apiPut(API + "/" + encodeURIComponent(slug), body);
                        const idx = plans.findIndex((x) => x.slug === slug);
                        if (idx >= 0) plans[idx] = updated;
                        renderPlans();
                        showToast("Đã lưu gói " + (plan.name || slug));
                    }
                );
            });
        });

        grid.querySelectorAll("[data-reset-plan]").forEach((btn) => {
            btn.addEventListener("click", () => {
                pendingResetSlug = btn.getAttribute("data-reset-plan");
                const plan = plans.find((x) => x.slug === pendingResetSlug);
                byId("admPricingResetDesc").textContent =
                    "Reset gói " + (plan && plan.name || pendingResetSlug) + " về giá trị mặc định trong hệ thống?";
                openModal("admPricingResetModal");
            });
        });
    }

    async function loadPlans() {
        const loading = byId("admPricingLoading");
        const err = byId("admPricingError");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        try {
            const data = await apiGet(API);
            plans = data.items || [];
            renderPlans();
            if (loading) loading.hidden = true;
        } catch (e) {
            if (loading) loading.hidden = true;
            if (err) {
                err.hidden = false;
                err.textContent = String(e.message || e);
            }
        }
    }

    async function ensureAdmin() {
        const blocked = byId("admPricingBlocked");
        const app = byId("admPricingApp");
        const token = readToken();
        if (!token) {
            if (blocked) blocked.hidden = false;
            if (app) app.hidden = true;
            return false;
        }
        try {
            const meRes = await fetch("/auth/me", { headers: authHeaders() });
            if (!meRes.ok) throw new Error("auth");
            const user = await meRes.json();
            if (String(user.role || "").toLowerCase() !== "admin") throw new Error("role");
            const chk = await fetch("/admin/api/check", { headers: authHeaders() });
            if (!chk.ok) throw new Error("admin");
            if (blocked) blocked.hidden = true;
            if (app) app.hidden = false;
            return true;
        } catch (_) {
            if (blocked) blocked.hidden = false;
            if (app) app.hidden = true;
            return false;
        }
    }

    async function init() {
        const ok = await ensureAdmin();
        if (!ok) return;

        await loadPlans();

        const refreshBtn = byId("btnAdmPricingRefresh");
        if (refreshBtn) refreshBtn.addEventListener("click", () => loadPlans());

        const resetAllBtn = byId("btnAdmPricingResetAll");
        if (resetAllBtn) {
            resetAllBtn.addEventListener("click", () => {
                pendingResetSlug = null;
                byId("admPricingResetDesc").textContent =
                    "Reset tất cả 4 gói (Starter, Pro, Agency, Business) về giá trị mặc định?";
                openModal("admPricingResetModal");
            });
        }

        byId("btnAdmPricingConfirmCancel").addEventListener("click", () => {
            confirmCallback = null;
            pendingSaveSlug = null;
            closeModal("admPricingConfirmModal");
        });
        byId("btnAdmPricingConfirmOk").addEventListener("click", async () => {
            const cb = confirmCallback;
            closeModal("admPricingConfirmModal");
            confirmCallback = null;
            if (!cb) return;
            try {
                await cb();
            } catch (e) {
                alert(String(e.message || e));
            } finally {
                pendingSaveSlug = null;
            }
        });

        byId("btnAdmPricingResetCancel").addEventListener("click", () => {
            pendingResetSlug = null;
            closeModal("admPricingResetModal");
        });
        byId("btnAdmPricingResetOk").addEventListener("click", async () => {
            const slug = pendingResetSlug;
            closeModal("admPricingResetModal");
            pendingResetSlug = null;
            try {
                const data = await apiPost(API + "/reset", slug ? { slug } : {});
                plans = data.items || [];
                renderPlans();
                showToast(slug ? "Đã reset gói " + slug : "Đã reset tất cả gói");
            } catch (e) {
                alert(String(e.message || e));
            }
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
