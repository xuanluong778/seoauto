(function () {
    "use strict";

    const API = "/api/admin/credit-costs";
    let rows = [];
    let filterText = "";

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

    let toastTimer = null;
    function showToast(msg) {
        const el = byId("admCcToast");
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

    function filteredRows() {
        const q = filterText.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter((r) => {
            const hay = [r.module, r.action, r.label, r.description].join(" ").toLowerCase();
            return hay.indexOf(q) >= 0;
        });
    }

    function rowKey(r) {
        return r.module + ":" + r.action;
    }

    function renderTable() {
        const tbody = byId("admCcTbody");
        const wrap = byId("admCcTableWrap");
        if (!tbody || !wrap) return;
        const list = filteredRows();
        tbody.innerHTML = list.map((r) => {
            const key = rowKey(r);
            return `
                <tr data-row="${esc(key)}">
                    <td class="adm-cc-module">${esc(r.module)}</td>
                    <td class="adm-cc-action">${esc(r.action)}</td>
                    <td class="adm-cc-label">${esc(r.label || "")}</td>
                    <td><input type="number" min="0" step="1" data-field="credit_cost" value="${esc(r.credit_cost)}" /></td>
                    <td><input type="number" min="0" max="100" step="1" data-field="cache_discount_percent" value="${esc(r.cache_discount_percent)}" /></td>
                    <td><input type="checkbox" data-field="cache_zero_cost" ${r.cache_zero_cost ? "checked" : ""} /></td>
                    <td><button type="button" class="ab-btn adm-cc-save" data-save="${esc(key)}">Lưu</button></td>
                </tr>
            `;
        }).join("");
        wrap.hidden = list.length === 0;

        tbody.querySelectorAll("[data-save]").forEach((btn) => {
            btn.addEventListener("click", () => saveRow(btn.getAttribute("data-save")));
        });
    }

    async function saveRow(key) {
        const tr = document.querySelector(`tr[data-row="${key}"]`);
        const parts = String(key || "").split(":");
        if (!tr || parts.length < 2) return;
        const module = parts[0];
        const action = parts.slice(1).join(":");
        const creditEl = tr.querySelector('[data-field="credit_cost"]');
        const discEl = tr.querySelector('[data-field="cache_discount_percent"]');
        const zeroEl = tr.querySelector('[data-field="cache_zero_cost"]');
        const body = {
            credit_cost: parseInt(creditEl && creditEl.value, 10) || 0,
            cache_discount_percent: parseInt(discEl && discEl.value, 10) || 0,
            cache_zero_cost: !!(zeroEl && zeroEl.checked),
        };
        btnDisable(tr, true);
        try {
            const updated = await apiPatch(
                API + "/" + encodeURIComponent(module) + "/" + encodeURIComponent(action),
                body
            );
            const idx = rows.findIndex((x) => rowKey(x) === key);
            if (idx >= 0) rows[idx] = Object.assign({}, rows[idx], updated);
            showToast("Đã lưu " + module + "/" + action);
        } catch (err) {
            showToast(err.message || "Lưu thất bại");
        } finally {
            btnDisable(tr, false);
        }
    }

    function btnDisable(tr, on) {
        const btn = tr && tr.querySelector("[data-save]");
        if (btn) btn.disabled = !!on;
    }

    async function load() {
        const loading = byId("admCcLoading");
        const errEl = byId("admCcError");
        if (loading) loading.hidden = false;
        if (errEl) errEl.hidden = true;
        try {
            const data = await apiGet(API);
            rows = (data && data.items) || [];
            renderTable();
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
        const blocked = byId("admCcBlocked");
        const app = byId("admCcApp");
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
        await load();
    }

    document.addEventListener("DOMContentLoaded", () => {
        const refresh = byId("btnAdmCcRefresh");
        const filter = byId("admCcFilter");
        if (refresh) refresh.addEventListener("click", load);
        if (filter) {
            filter.addEventListener("input", () => {
                filterText = filter.value || "";
                renderTable();
            });
        }
        init();
    });
})();
