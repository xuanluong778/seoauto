(function () {
    "use strict";

    const API = "/api/admin/saas/economics";
    const PROVIDERS = [
        "openai", "anthropic", "dataforseo", "google_places", "google_cse", "crawl", "other",
    ];

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function fmt(n) {
        return Number(n || 0).toLocaleString("vi-VN");
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
        if (!res.ok) {
            const msg = typeof data.detail === "string" ? data.detail : data.message || data.error || "HTTP " + res.status;
            throw new Error(msg);
        }
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
        const res = await fetch(path, { method: "POST", headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.message || data.detail || "HTTP " + res.status);
        return data;
    }

    let toastTimer = null;
    function showToast(msg) {
        const el = byId("admEcoToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        el.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            el.classList.remove("is-visible");
            setTimeout(() => { el.hidden = true; }, 300);
        }, 2600);
    }

    function renderKpis(d) {
        const el = byId("admEcoKpis");
        if (!el) return;
        const burn = d.credit_burn || {};
        const cost = d.estimated_cost_vnd || {};
        const profit = d.profit_vnd || {};
        const revM = (d.revenue && d.revenue.month) || {};
        const gm = d.gross_margin_pct || {};
        const gmM = gm.month == null ? "—" : ((Number(gm.month) * 100).toFixed(1) + "%");
        const gmT = gm.today == null ? "—" : ((Number(gm.today) * 100).toFixed(1) + "%");
        el.innerHTML = [
            kpi("Credit đốt hôm nay", fmt(burn.today), "Tháng: " + fmt(burn.month)),
            kpi("Chi phí ước tính hôm nay", fmt(cost.today) + " ₫", "Tháng: " + fmt(cost.month) + " ₫"),
            kpi("Doanh thu tháng (gross)", fmt(revM.total_gross_vnd) + " ₫", "Pre-VAT: " + fmt(revM.total_base_vnd) + " ₫"),
            kpi("Gross margin tháng", gmM, "Hôm nay: " + gmT + " · mục tiêu ≥70%"),
            kpi("Lợi nhuận ước tính tháng", fmt(profit.month) + " ₫", "Hôm nay: " + fmt(profit.today) + " ₫"),
        ].join("");
    }

    function kpi(label, value, sub) {
        return `<div class="adm-eco-kpi"><p class="adm-eco-kpi-label">${esc(label)}</p><p class="adm-eco-kpi-value">${esc(value)}</p><p class="adm-eco-kpi-sub">${esc(sub)}</p></div>`;
    }

    function fillTable(tbodySel, rows, fn) {
        const tbody = document.querySelector(tbodySel + " tbody");
        if (!tbody) return;
        tbody.innerHTML = (rows || []).map(fn).join("") || "<tr><td colspan='9'>Không có dữ liệu</td></tr>";
    }

    function renderAlerts(d) {
        const wrap = byId("admEcoAlerts");
        const banner = byId("admEcoBlockBanner");
        const unblockBtn = byId("btnAdmEcoUnblock");
        if (!wrap) return;
        const alerts = d.alerts || [];
        wrap.hidden = alerts.length === 0;
        wrap.innerHTML = alerts.map((a) => {
            const cls = a.level === "critical" ? "is-critical" : "is-warning";
            return `<div class="adm-eco-alert ${cls}">${esc(a.message)}</div>`;
        }).join("");
        if (banner) {
            if (d.expensive_api_blocked) {
                banner.hidden = false;
                banner.textContent = "API đắt đang BỊ CHẶN — " + (d.block_reason || "");
            } else {
                banner.hidden = true;
            }
        }
        if (unblockBtn) unblockBtn.hidden = !d.expensive_api_blocked;
    }

    function renderDashboard(d) {
        renderKpis(d);
        renderAlerts(d);
        fillTable("#admEcoProviderTable", (d.by_provider && d.by_provider.month) || [], (r) =>
            `<tr><td>${esc(r.label || r.provider)}</td><td>${fmt(r.credits)}</td><td>${fmt(r.estimated_cost_vnd)} ₫</td></tr>`
        );
        fillTable("#admEcoModuleTable", (d.by_module && d.by_module.month) || [], (r) =>
            `<tr><td>${esc(r.module)}</td><td>${fmt(r.credits)}</td></tr>`
        );
        fillTable("#admEcoUserTable", (d.by_user && d.by_user.month) || [], (r) =>
            `<tr><td>${esc(r.email)}</td><td>${fmt(r.credits)}</td></tr>`
        );
        fillTable("#admEcoActionTable", (d.by_action && d.by_action.month) || [], (r) =>
            `<tr><td>${esc(r.module)}.${esc(r.action)}</td><td>${fmt(r.credits)}</td></tr>`
        );
        fillTable("#admEcoOrgTable", (d.by_org && d.by_org.month) || [], (r) =>
            `<tr><td>org#${esc(r.organization_id)}</td><td>${fmt(r.credits)}</td></tr>`
        );
        fillTable("#admEcoRiskTable", d.at_risk_users || [], (r) =>
            `<tr><td>${esc(r.email)}</td><td>${fmt(r.credits_burned)}</td><td>${fmt(r.estimated_cost_vnd)} ₫</td><td>${fmt(r.revenue_base_vnd)} ₫</td><td>${esc(r.risk_score)}</td></tr>`
        );

        const revEl = byId("admEcoRevenue");
        const rev = (d.revenue && d.revenue.month) || {};
        if (revEl) {
            revEl.innerHTML = `
                <p><strong>Subscription (gross):</strong> ${fmt(rev.subscription_gross_vnd)} ₫</p>
                <p><strong>Credit pack (gross):</strong> ${fmt(rev.credit_pack_gross_vnd)} ₫</p>
                <p><strong>Tổng gross:</strong> ${fmt(rev.total_gross_vnd)} ₫</p>
                <p><strong>Tổng pre-VAT:</strong> ${fmt(rev.total_base_vnd)} ₫</p>
            `;
        }

        const gen = byId("admEcoGenerated");
        if (gen) gen.textContent = "Cập nhật: " + (d.generated_at || "—");

        bindSettings(d.settings || {});
    }

    function bindSettings(settings) {
        const form = byId("admEcoSettingsForm");
        if (!form) return;
        form.daily_cost_threshold_vnd.value = settings.daily_cost_threshold_vnd || 0;
        form.monthly_cost_threshold_vnd.value = settings.monthly_cost_threshold_vnd || 0;
        form.auto_block_expensive_api.checked = !!settings.auto_block_expensive_api;
        form.alert_cooldown_hours.value = settings.alert_cooldown_hours || 6;

        const vpc = settings.vnd_per_credit || {};
        const grid = byId("admEcoVpcGrid");
        if (grid) {
            grid.innerHTML = PROVIDERS.map((p) => `
                <label>${esc(p)}
                    <input type="number" min="0" data-vpc="${esc(p)}" value="${esc(vpc[p] || 0)}" />
                </label>
            `).join("");
        }
    }

    async function loadDashboard() {
        const loading = byId("admEcoLoading");
        const err = byId("admEcoError");
        const content = byId("admEcoContent");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        if (content) content.hidden = true;
        try {
            const data = await apiGet(API + "/dashboard");
            renderDashboard(data);
            if (content) content.hidden = false;
        } catch (e) {
            if (err) {
                err.textContent = e.message || String(e);
                err.hidden = false;
            }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    async function saveSettings(ev) {
        ev.preventDefault();
        const form = byId("admEcoSettingsForm");
        if (!form) return;
        const vpc = {};
        form.querySelectorAll("[data-vpc]").forEach((inp) => {
            vpc[inp.getAttribute("data-vpc")] = parseInt(inp.value, 10) || 0;
        });
        const body = {
            daily_cost_threshold_vnd: parseInt(form.daily_cost_threshold_vnd.value, 10) || 0,
            monthly_cost_threshold_vnd: parseInt(form.monthly_cost_threshold_vnd.value, 10) || 0,
            auto_block_expensive_api: !!form.auto_block_expensive_api.checked,
            alert_cooldown_hours: parseInt(form.alert_cooldown_hours.value, 10) || 6,
            vnd_per_credit: vpc,
        };
        try {
            await apiPatch(API + "/settings", body);
            showToast("Đã lưu cấu hình ngưỡng.");
            await loadDashboard();
        } catch (e) {
            showToast(e.message || "Lưu thất bại");
        }
    }

    async function ensureAdmin() {
        const blocked = byId("admEcoBlocked");
        const app = byId("admEcoApp");
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
            const isAdmin = typeof window.DigiSeoIsAdminUser === "function"
                ? window.DigiSeoIsAdminUser(user)
                : String(user.role || "").toLowerCase() === "admin";
            if (!isAdmin) throw new Error("role");
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

        const refresh = byId("btnAdmEcoRefresh");
        if (refresh) refresh.addEventListener("click", loadDashboard);
        const form = byId("admEcoSettingsForm");
        if (form) form.addEventListener("submit", saveSettings);
        const unblock = byId("btnAdmEcoUnblock");
        if (unblock) {
            unblock.addEventListener("click", async () => {
                try {
                    await apiPost(API + "/unblock");
                    showToast("Đã gỡ chặn API đắt.");
                    await loadDashboard();
                } catch (e) {
                    showToast(e.message || "Gỡ chặn thất bại");
                }
            });
        }
        await loadDashboard();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
