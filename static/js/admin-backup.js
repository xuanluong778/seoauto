(function () {
    "use strict";
    const PAGE = 25;
    let offset = 0, total = 0;
    function $(id) { return document.getElementById(id); }
    function esc(s) { return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;"); }
    function fmtDt(iso) {
        if (!iso) return "—";
        try { return new Date(iso).toLocaleString("vi-VN"); } catch (_) { return "—"; }
    }
    function fmtSize(b) {
        const n = Number(b || 0);
        if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
        if (n >= 1048576) return (n / 1048576).toFixed(2) + " MB";
        if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
        return n ? n + " B" : "—";
    }
    function token() {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1]).trim();
        } catch (_) {}
        return "";
    }
    function hdr() {
        const h = { "Content-Type": "application/json" };
        const t = token();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }
    async function api(path, opts) {
        const res = await fetch(path, opts || { headers: hdr() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || "HTTP " + res.status);
        return data;
    }
    function msg(text, ok) {
        const el = $("admBkMsg");
        if (!el) return;
        el.hidden = !text;
        el.textContent = text || "";
        el.className = "adm-bk-msg " + (ok ? "ok" : "err");
    }
    function badge(s) {
        const v = String(s || "unknown").toLowerCase();
        return '<span class="ab-badge ' + esc(v) + '">' + esc(v) + "</span>";
    }
    async function loadStatus() {
        const data = await api("/admin/api/backup/status");
        const el = $("admBkStatus");
        if (!el) return;
        let html = '<div class="adm-bk-status-grid">';
        for (const [k, row] of Object.entries(data.last_runs || {})) {
            const st = row ? row.status : "chưa có";
            const at = row ? fmtDt(row.started_at) : "—";
            html += '<div class="adm-bk-stat"><strong>' + esc(k.toUpperCase()) + '</strong>' + esc(st) + '<br><small>' + esc(at) + "</small></div>";
        }
        html += '<div class="adm-bk-stat"><strong>Lock</strong>' + (data.lock_active ? "Đang chạy" : "Rảnh") + "</div>";
        html += "</div>";
        if (data.timers && data.timers.length) {
            html += "<p style='margin-top:.75rem;font-size:.85rem;color:#9ca3af'>";
            data.timers.forEach(function (t) {
                html += esc(t.label) + ": " + esc(t.schedule) + " · ";
            });
            html += "</p>";
        }
        el.innerHTML = html;
    }
    async function loadRuns() {
        const type = ($("admBkFilterType") || {}).value || "";
        const status = ($("admBkFilterStatus") || {}).value || "";
        let q = "/admin/api/backup/runs?limit=" + PAGE + "&offset=" + offset;
        if (type) q += "&backup_type=" + encodeURIComponent(type);
        if (status) q += "&status=" + encodeURIComponent(status);
        const data = await api(q);
        total = data.total || 0;
        const body = $("admBkBody");
        if (!body) return;
        if (!data.items || !data.items.length) {
            body.innerHTML = '<tr><td colspan="8">Chưa có bản backup.</td></tr>';
            return;
        }
        body.innerHTML = data.items.map(function (r) {
            return "<tr>" +
                "<td>" + esc(fmtDt(r.started_at)) + "</td>" +
                "<td>" + esc(r.backup_type) + "</td>" +
                "<td>" + badge(r.status) + (r.error_message ? '<br><small>' + esc(r.error_message.slice(0,80)) + "</small>" : "") + "</td>" +
                "<td>" + badge(r.verify_status || "—") + "</td>" +
                "<td>" + esc(fmtSize(r.size_bytes)) + "</td>" +
                "<td>" + (r.duration_seconds != null ? r.duration_seconds + "s" : "—") + "</td>" +
                "<td><code>" + esc(r.run_id) + "</code></td>" +
                '<td><button type="button" class="ab-btn secondary adm-bk-verify" data-id="' + esc(r.run_id) + '">Verify</button></td>' +
                "</tr>";
        }).join("");
        body.querySelectorAll(".adm-bk-verify").forEach(function (btn) {
            btn.addEventListener("click", function () { verifyRun(btn.getAttribute("data-id")); });
        });
        const pager = $("admBkPager");
        if (pager) {
            pager.innerHTML = "<span>" + (offset + 1) + "–" + Math.min(offset + PAGE, total) + " / " + total + "</span>";
            if (offset > 0) pager.innerHTML += ' <button type="button" class="ab-btn secondary" id="bkPrev">Trước</button>';
            if (offset + PAGE < total) pager.innerHTML += ' <button type="button" class="ab-btn secondary" id="bkNext">Sau</button>';
            const p = $("bkPrev"); if (p) p.onclick = function () { offset = Math.max(0, offset - PAGE); loadRuns(); };
            const n = $("bkNext"); if (n) n.onclick = function () { offset += PAGE; loadRuns(); };
        }
    }
    async function trigger(mode) {
        msg("Đang khởi chạy backup " + mode + "…", true);
        try {
            const data = await api("/admin/api/backup/trigger?mode=" + encodeURIComponent(mode), { method: "POST", headers: hdr() });
            msg(data.message || "Đã khởi chạy", data.ok);
            setTimeout(function () { loadStatus(); loadRuns(); }, 3000);
        } catch (e) { msg(e.message, false); }
    }
    async function verifyRun(runId) {
        msg("Đang verify " + runId + "…", true);
        try {
            const data = await api("/admin/api/backup/runs/" + encodeURIComponent(runId) + "/verify", { method: "POST", headers: hdr() });
            msg(data.message, data.ok);
            loadRuns();
        } catch (e) { msg(e.message, false); }
    }
    function bind() {
        if ($("btnBkRefresh")) $("btnBkRefresh").onclick = function () { loadStatus(); loadRuns(); };
        if ($("btnBkTriggerDb")) $("btnBkTriggerDb").onclick = function () { trigger("db"); };
        if ($("btnBkTriggerSource")) $("btnBkTriggerSource").onclick = function () { trigger("source"); };
        if ($("btnBkTriggerFull")) $("btnBkTriggerFull").onclick = function () { trigger("full"); };
        if ($("admBkFilterType")) $("admBkFilterType").onchange = function () { offset = 0; loadRuns(); };
        if ($("admBkFilterStatus")) $("admBkFilterStatus").onchange = function () { offset = 0; loadRuns(); };
    }
    document.addEventListener("DOMContentLoaded", function () {
        bind();
        loadStatus().catch(function (e) { msg(e.message, false); });
        loadRuns().catch(function (e) { msg(e.message, false); });
    });
})();
