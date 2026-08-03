(function () {
    "use strict";

    function byId(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function readToken() {
        try {
            var t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
        } catch (_) {}
        return "";
    }

    function authHeaders(extra) {
        var h = Object.assign({ "Content-Type": "application/json" }, extra || {});
        var t = readToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function showToast(msg) {
        var el = byId("abToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        clearTimeout(showToast._t);
        showToast._t = setTimeout(function () { el.hidden = true; }, 3200);
    }

    function setMsg(text, kind) {
        var el = byId("admSinbyteMsg");
        if (!el) return;
        if (!text) {
            el.hidden = true;
            el.textContent = "";
            el.className = "adm-int-msg";
            return;
        }
        el.hidden = false;
        el.textContent = text;
        el.className = "adm-int-msg" + (kind === "ok" ? " is-ok" : kind === "err" ? " is-err" : "");
    }

    function fmtDt(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit",
            });
        } catch (_) { return "—"; }
    }

    function renderStatus(data) {
        var pill = byId("admSinbytePill");
        var meta = byId("admSinbyteMeta");
        var masked = byId("admSinbyteMasked");
        if (!data) return;

        var state = "disconnected";
        var pillText = "Chưa kết nối";
        if (data.configured && data.connected) {
            state = "connected";
            pillText = "Đã kết nối";
        } else if (data.configured) {
            state = "configured";
            pillText = "Đã cấu hình — chưa test";
        }

        if (pill) {
            pill.dataset.state = state;
            pill.textContent = pillText;
        }

        if (masked) {
            if (data.api_key_masked) {
                masked.hidden = false;
                masked.innerHTML = "Key hiện tại: <strong>" + esc(data.api_key_masked) + "</strong>";
            } else {
                masked.hidden = true;
                masked.innerHTML = "";
            }
        }

        if (meta) {
            var lines = [];
            if (data.source) {
                lines.push("Nguồn key: " + (data.source === "env" ? "Biến môi trường" : "Database (mã hóa)"));
            }
            if (data.updated_at) lines.push("Cập nhật: " + fmtDt(data.updated_at));
            if (data.last_test_at) {
                lines.push(
                    "Test gần nhất: " + fmtDt(data.last_test_at) +
                    (data.last_test_ok ? " — OK" : " — Lỗi")
                );
            }
            if (data.last_test_message) lines.push(data.last_test_message);
            if (lines.length) {
                meta.hidden = false;
                meta.innerHTML = lines.map(function (l) { return "<div>" + esc(l) + "</div>"; }).join("");
            } else {
                meta.hidden = true;
                meta.innerHTML = "";
            }
        }
    }

    async function apiGet(path) {
        var res = await fetch(path, { headers: authHeaders() });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) throw new Error(data.detail || data.message || "Lỗi API");
        return data;
    }

    async function apiPost(path, body) {
        var res = await fetch(path, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify(body || {}),
        });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) {
            var detail = data.detail;
            if (detail && typeof detail === "object") throw new Error(detail.message || "Lỗi API");
            throw new Error(detail || data.message || "Lỗi API");
        }
        return data;
    }

    async function apiDelete(path) {
        var res = await fetch(path, { method: "DELETE", headers: authHeaders() });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) throw new Error(data.detail || data.message || "Lỗi API");
        return data;
    }

    async function loadStatus() {
        var data = await apiGet("/api/admin/integrations/sinbyte/status");
        renderStatus(data);
        return data;
    }

    async function onSave() {
        var input = byId("admSinbyteKey");
        var key = input && input.value ? input.value.trim() : "";
        if (!key || key.length < 8) {
            setMsg("Nhập API key hợp lệ (tối thiểu 8 ký tự).", "err");
            return;
        }
        var btn = byId("btnAdmSinbyteSave");
        if (btn) btn.disabled = true;
        setMsg("");
        try {
            var res = await apiPost("/api/admin/integrations/sinbyte/save", { api_key: key });
            if (input) input.value = "";
            renderStatus(res.status || res);
            setMsg(res.message || "Đã lưu.", "ok");
            showToast("Đã lưu API key Sinbyte.");
        } catch (e) {
            setMsg(String(e.message || e), "err");
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function onTest() {
        var btn = byId("btnAdmSinbyteTest");
        if (btn) btn.disabled = true;
        setMsg("");
        try {
            var res = await apiPost("/api/admin/integrations/sinbyte/test", {});
            renderStatus(res.status || res);
            setMsg(res.message || "", res.ok ? "ok" : "err");
            showToast(res.ok ? "Kết nối Sinbyte OK." : "Test kết nối thất bại.");
        } catch (e) {
            setMsg(String(e.message || e), "err");
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function onDelete() {
        if (!window.confirm("Xóa API key Sinbyte đã lưu trong database?")) return;
        var btn = byId("btnAdmSinbyteDelete");
        if (btn) btn.disabled = true;
        setMsg("");
        try {
            var res = await apiDelete("/api/admin/integrations/sinbyte");
            var input = byId("admSinbyteKey");
            if (input) input.value = "";
            renderStatus(res.status || res);
            setMsg(res.message || "Đã xóa.", "ok");
            showToast("Đã xóa API key.");
        } catch (e) {
            setMsg(String(e.message || e), "err");
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function init() {
        var saveBtn = byId("btnAdmSinbyteSave");
        var testBtn = byId("btnAdmSinbyteTest");
        var delBtn = byId("btnAdmSinbyteDelete");
        if (saveBtn) saveBtn.addEventListener("click", onSave);
        if (testBtn) testBtn.addEventListener("click", onTest);
        if (delBtn) delBtn.addEventListener("click", onDelete);

        try {
            await loadStatus();
        } catch (e) {
            setMsg("Không tải được trạng thái — đăng nhập admin hoặc thử lại.", "err");
        }

        try {
            await loadLeadScannerStatus();
        } catch (_e) {
            var msg = byId("admLeadScannerMsg");
            if (msg) {
                msg.hidden = false;
                msg.textContent = "Không tải được thống kê Lead Scanner.";
                msg.className = "adm-int-msg is-err";
            }
        }
    }

    async function loadLeadScannerStatus() {
        var pill = byId("admLeadScannerPill");
        var meta = byId("admLeadScannerMeta");
        var data = await apiGet("/api/admin/lead-scanner/status");
        var cfg = data.config || {};
        var usage = data.usage || {};
        if (pill) {
            pill.dataset.state = cfg.enabled && cfg.places_configured ? "connected" : "disconnected";
            pill.textContent = cfg.enabled
                ? (cfg.places_configured ? "Đang bật" : "Thiếu Places API key")
                : "Đang tắt";
        }
        if (meta) {
            var lines = [
                "Places API: " + (cfg.places && cfg.places.masked ? cfg.places.masked : "chưa cấu hình"),
                "Quét hôm nay: " + (usage.scans_today || 0) + " · API requests: " + (usage.api_requests_today || 0),
                "Quét tháng: " + (usage.scans_month || 0) + " · API requests: " + (usage.api_requests_month || 0),
                "Ước tính chi phí tháng: $" + (usage.estimated_cost_usd_month || 0),
            ];
            if (usage.daily_cost_alert || usage.monthly_cost_alert) {
                lines.push("⚠ Vượt ngưỡng cảnh báo chi phí API");
            }
            meta.hidden = false;
            meta.innerHTML = lines.map(function (l) { return "<div>" + esc(l) + "</div>"; }).join("");
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
