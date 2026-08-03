/**
 * Shared Chatbot KB client — single API source for CSKH + Settings.
 * Data lives in DB (/api/chatbot/kb/*); no localStorage for KB content.
 */
(function (global) {
    "use strict";

    var API = "/api/chatbot";
    var CHANNEL_NAME = "seoauto_chatbot_kb_v1";
    var channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(CHANNEL_NAME) : null;

    function esc(s) {
        return String(s || "").replace(/[&<>"']/g, function (c) {
            return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
        });
    }

    function authHeaders(token, json) {
        var h = {};
        if (json) h["Content-Type"] = "application/json";
        if (token) h.Authorization = "Bearer " + token;
        return h;
    }

    async function apiRequest(token, path, opts) {
        opts = opts || {};
        var r = await fetch(API + path, {
            method: opts.method || "GET",
            headers: authHeaders(token, opts.json),
            body: opts.body ? JSON.stringify(opts.body) : undefined,
            credentials: "same-origin",
            cache: "no-store",
        });
        var data = {};
        try { data = await r.json(); } catch (_e) {}
        if (!r.ok) {
            var msg = "Có lỗi xảy ra.";
            if (typeof data.detail === "string") msg = data.detail;
            else if (data.detail && data.detail.message) msg = String(data.detail.message);
            var err = new Error(msg);
            err.status = r.status;
            throw err;
        }
        return data;
    }

    function notifyChange(botId) {
        var bid = parseInt(botId, 10) || 0;
        if (!bid) return;
        var payload = { type: "kb_changed", bot_id: bid, at: Date.now() };
        if (channel) {
            try { channel.postMessage(payload); } catch (_e) {}
        }
        try {
            global.dispatchEvent(new CustomEvent("seoauto-kb-changed", { detail: payload }));
        } catch (_e2) {}
    }

    function onChange(handler) {
        if (typeof handler !== "function") return function () {};
        var wrapped = function (ev) {
            var d = (ev && ev.detail) || (ev && ev.data) || {};
            if (d.type === "kb_changed" || d.bot_id) handler(d);
        };
        global.addEventListener("seoauto-kb-changed", wrapped);
        if (channel) channel.addEventListener("message", wrapped);
        return function () {
            global.removeEventListener("seoauto-kb-changed", wrapped);
            if (channel) channel.removeEventListener("message", wrapped);
        };
    }

    var SYNC_LABELS = {
        synced: "Đã đồng bộ",
        empty: "Chưa có KB",
        processing: "Đang xử lý",
        error: "Lỗi đồng bộ",
    };

    var SYNC_CLASS = {
        synced: "ckb-sync--synced",
        empty: "ckb-sync--empty",
        processing: "ckb-sync--processing",
        error: "ckb-sync--error",
    };

    function syncStatusFromData(data) {
        if (!data) return "empty";
        var s = String(data.sync_status || "").toLowerCase();
        if (s === "synced" || s === "empty" || s === "processing" || s === "error") return s;
        if (!data.nodes || !data.nodes.length) return "empty";
        return "synced";
    }

    function renderSyncBadge(el, status, syncedAt) {
        if (!el) return;
        var s = String(status || "empty").toLowerCase();
        if (!SYNC_LABELS[s]) s = "empty";
        var label = SYNC_LABELS[s];
        if (s === "synced" && syncedAt) {
            label += " · " + String(syncedAt).slice(0, 16).replace("T", " ");
        }
        el.className = "ckb-sync " + (SYNC_CLASS[s] || SYNC_CLASS.empty);
        el.textContent = label;
        el.hidden = false;
    }

    function setProcessing(el) {
        renderSyncBadge(el, "processing");
    }

    function setError(el) {
        renderSyncBadge(el, "error");
    }

    var api = {
        get: function (token, botId) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId)).then(function (r) { return r.data || {}; });
        },
        createNode: function (token, botId, body) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId) + "/nodes", {
                method: "POST", json: true, body: body,
            }).then(function (r) {
                notifyChange(botId);
                return r.data;
            });
        },
        updateNode: function (token, nodeId, body, botId) {
            return apiRequest(token, "/kb/nodes/" + encodeURIComponent(nodeId), {
                method: "PUT", json: true, body: body,
            }).then(function (r) {
                if (botId) notifyChange(botId);
                return r.data;
            });
        },
        deleteNode: function (token, nodeId, botId) {
            return apiRequest(token, "/kb/nodes/" + encodeURIComponent(nodeId), {
                method: "DELETE",
            }).then(function (r) {
                if (botId) notifyChange(botId);
                return r;
            });
        },
        toggleNode: function (token, nodeId, botId) {
            return apiRequest(token, "/kb/nodes/" + encodeURIComponent(nodeId) + "/toggle", {
                method: "POST",
            }).then(function (r) {
                if (botId) notifyChange(botId);
                return r.data;
            });
        },
        importSources: function (token, botId) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId) + "/import", {
                method: "POST",
            }).then(function (r) {
                notifyChange(botId);
                return r.data || {};
            });
        },
        import: function (token, botId) {
            return apiRequest(token, "/kb/import", {
                method: "POST", json: true, body: { bot_id: parseInt(botId, 10) },
            }).then(function (r) {
                notifyChange(botId);
                return r.data || {};
            });
        },
        preview: function (token, botId, message) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId) + "/preview", {
                method: "POST", json: true, body: { message: message },
            }).then(function (r) { return r.data || {}; });
        },
        listBots: function (token) {
            return apiRequest(token, "/bots").then(function (r) { return r.data || []; });
        },
        listImportSources: function (token, botId) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId) + "/import/sources")
                .then(function (r) { return r.data || {}; });
        },
        importText: function (token, botId, body) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId) + "/import/text", {
                method: "POST", json: true, body: body,
            }).then(function (r) {
                notifyChange(botId);
                return r.data || {};
            });
        },
        importSourceIds: function (token, botId, sourceIds) {
            return apiRequest(token, "/kb/" + encodeURIComponent(botId) + "/import", {
                method: "POST",
                json: true,
                body: { source_ids: sourceIds || [] },
            }).then(function (r) {
                notifyChange(botId);
                return r.data || {};
            });
        },
    };

    global.SeoautoChatbotKb = {
        API: API,
        esc: esc,
        api: api,
        notifyChange: notifyChange,
        onChange: onChange,
        renderSyncBadge: renderSyncBadge,
        setProcessing: setProcessing,
        setError: setError,
        syncStatusFromData: syncStatusFromData,
        SYNC_LABELS: SYNC_LABELS,
    };
})(typeof window !== "undefined" ? window : globalThis);
