(function () {
    "use strict";

    const API = "/api/admin/saas/plan-quotas";
    let plans = [];
    let planFilter = "";

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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

    async function apiPatch(path, body) {
        const res = await fetch(path, {
            method: "PATCH",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = typeof data.detail === "string" ? data.detail : data.message || data.error || "HTTP " + res.status;
            throw new Error(msg);
        }
        return data;
    }

    async function apiPost(path) {
        const res = await fetch(path, {
            method: "POST",
            headers: authHeaders(),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.message || "HTTP " + res.status);
        return data;
    }

    let toastTimer = null;
    function showToast(msg) {
        const el = byId("admPqToast");
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

    function featureSummary(features) {
        if (!features || typeof features !== "object") return "";
        const bits = [];
        if (features.google_map_seo) bits.push("Google Map");
        if (features.kw_advanced) bits.push("KW nâng cao");
        if (features.white_label_report) bits.push("White-label");
        if (features.byok_preferred) bits.push("Ưu tiên BYOK");
        if (features.chatbot_facebook) bits.push("Facebook bot");
        return bits.join(" · ");
    }

    function filteredPlans() {
        if (!planFilter) return plans;
        return plans.filter((p) => p.plan_slug === planFilter);
    }

    function render() {
        const grid = byId("admPqGrid");
        if (!grid) return;
        const list = filteredPlans();
        grid.innerHTML = list.map((plan) => {
            const feats = featureSummary(plan.features);
            const rows = (plan.quotas || []).map((q) => {
                const key = plan.plan_slug + ":" + q.quota_key;
                const customCls = q.is_custom ? " adm-pq-custom" : "";
                return `
                    <tr class="${customCls}" data-row="${esc(key)}">
                        <td>${esc(q.label)}</td>
                        <td class="adm-cc-action">${esc(q.quota_key)}</td>
                        <td><input type="number" min="0" step="1" data-field="limit_value" value="${esc(q.limit_value)}" /></td>
                        <td class="adm-cc-label">${esc(q.default_value)}</td>
                        <td>
                            <button type="button" class="ab-btn adm-cc-save" data-save="${esc(key)}">Lưu</button>
                            <button type="button" class="ab-btn secondary" data-reset="${esc(key)}">Reset</button>
                        </td>
                    </tr>
                `;
            }).join("");
            return `
                <section class="adm-pq-plan-card" data-plan="${esc(plan.plan_slug)}">
                    <div class="adm-pq-plan-head">
                        <div>
                            <h2>${esc(plan.plan_name)}</h2>
                            <div class="adm-pq-plan-slug">${esc(plan.plan_slug)}</div>
                        </div>
                        ${feats ? `<div class="adm-pq-features">${esc(feats)}</div>` : ""}
                    </div>
                    <div class="adm-cc-table-wrap">
                        <table class="adm-cc-table">
                            <thead>
                                <tr>
                                    <th>Nhãn</th>
                                    <th>Key</th>
                                    <th>Quota/tháng</th>
                                    <th>Mặc định</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </div>
                </section>
            `;
        }).join("");
        grid.hidden = list.length === 0;

        grid.querySelectorAll("[data-save]").forEach((btn) => {
            btn.addEventListener("click", () => saveRow(btn.getAttribute("data-save")));
        });
        grid.querySelectorAll("[data-reset]").forEach((btn) => {
            btn.addEventListener("click", () => resetRow(btn.getAttribute("data-reset")));
        });
    }

    function parseKey(key) {
        const parts = String(key || "").split(":");
        return { plan_slug: parts[0], quota_key: parts.slice(1).join(":") };
    }

    async function saveRow(key) {
        const tr = document.querySelector(`tr[data-row="${key}"]`);
        const { plan_slug, quota_key } = parseKey(key);
        if (!tr || !plan_slug || !quota_key) return;
        const el = tr.querySelector('[data-field="limit_value"]');
        const body = { limit_value: parseInt(el && el.value, 10) || 0 };
        tr.querySelectorAll("button").forEach((b) => { b.disabled = true; });
        try {
            const updated = await apiPatch(
                API + "/" + encodeURIComponent(plan_slug) + "/" + encodeURIComponent(quota_key),
                body
            );
            mergeQuota(plan_slug, updated);
            render();
            showToast("Đã lưu " + plan_slug + "/" + quota_key);
        } catch (err) {
            showToast(err.message || "Lưu thất bại");
        } finally {
            tr.querySelectorAll("button").forEach((b) => { b.disabled = false; });
        }
    }

    async function resetRow(key) {
        const { plan_slug, quota_key } = parseKey(key);
        if (!plan_slug || !quota_key) return;
        try {
            const updated = await apiPost(
                API + "/" + encodeURIComponent(plan_slug) + "/" + encodeURIComponent(quota_key) + "/reset"
            );
            mergeQuota(plan_slug, updated);
            render();
            showToast("Đã reset " + plan_slug + "/" + quota_key);
        } catch (err) {
            showToast(err.message || "Reset thất bại");
        }
    }

    function mergeQuota(planSlug, row) {
        const plan = plans.find((p) => p.plan_slug === planSlug);
        if (!plan || !row) return;
        const idx = (plan.quotas || []).findIndex((q) => q.quota_key === row.quota_key);
        if (idx >= 0) plan.quotas[idx] = Object.assign({}, plan.quotas[idx], row);
    }

    function fillPlanFilter() {
        const sel = byId("admPqPlanFilter");
        if (!sel) return;
        const cur = sel.value;
        sel.innerHTML = '<option value="">Tất cả gói</option>' +
            plans.map((p) => `<option value="${esc(p.plan_slug)}">${esc(p.plan_name)}</option>`).join("");
        sel.value = cur || "";
    }

    async function load() {
        const loading = byId("admPqLoading");
        const errEl = byId("admPqError");
        if (loading) loading.hidden = false;
        if (errEl) errEl.hidden = true;
        try {
            const data = await apiGet(API);
            plans = data.items || [];
            fillPlanFilter();
            render();
        } catch (err) {
            if (errEl) {
                errEl.textContent = err.message || "Không tải được dữ liệu.";
                errEl.hidden = false;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    async function ensureAdmin() {
        const blocked = byId("admPqBlocked");
        const app = byId("admPqApp");
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

    document.addEventListener("DOMContentLoaded", async () => {
        const ok = await ensureAdmin();
        if (!ok) return;
        const refresh = byId("btnAdmPqRefresh");
        const filter = byId("admPqPlanFilter");
        if (refresh) refresh.addEventListener("click", load);
        if (filter) {
            filter.addEventListener("change", () => {
                planFilter = filter.value || "";
                render();
            });
        }
        await load();
    });
})();
