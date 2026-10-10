/**
 * Chatbot CSKH inbox notify — badge + dropdown next to Chatbot FAB.
 * Isolated from Content AI and the floating Chatbot AI panel.
 */
(function () {
    "use strict";

    var API = "/api/chatbot";
    var WS_PATH = "/api/chatbot/inbox-ws";
    var BC_NAME = "seoauto-cskh-inbox";
    var root, fab, badgeEl, dropdown, listEl, backdrop;
    var items = [];
    var unreadCount = 0;
    var open = false;
    var ws = null;
    var wsTimer = null;
    var pingTimer = null;
    var pollTimer = null;
    var bc = null;

    function $(id) {
        return document.getElementById(id);
    }

    function token() {
        return typeof window.DigiSeoGetAuthToken === "function" ? window.DigiSeoGetAuthToken() : "";
    }

    function authHeaders(json) {
        var h = {};
        if (json) h["Content-Type"] = "application/json";
        var t = token();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function formatTime(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d.getTime())) return "";
        var sec = Math.round((Date.now() - d.getTime()) / 1000);
        if (sec < 45) return "Vừa xong";
        if (sec < 3600) return Math.max(1, Math.floor(sec / 60)) + " phút trước";
        if (sec < 86400) return Math.max(1, Math.floor(sec / 3600)) + " giờ trước";
        return d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
    }

    function setOpen(next) {
        open = !!next;
        if (root) root.classList.toggle("is-open", open);
        if (dropdown) dropdown.hidden = !open;
        if (backdrop) backdrop.hidden = !open;
        if (fab) {
            fab.setAttribute("aria-expanded", open ? "true" : "false");
            fab.classList.toggle("is-active", open);
        }
    }

    function render() {
        if (!badgeEl || !listEl) return;
        var n = Math.max(0, Number(unreadCount) || items.length);
        if (n > 0) {
            badgeEl.hidden = false;
            badgeEl.textContent = n > 99 ? "99+" : String(n);
        } else {
            badgeEl.hidden = true;
            badgeEl.textContent = "0";
        }
        if (!items.length) {
            listEl.innerHTML = '<p class="digiseo-inbox-empty">Chưa có tin nhắn mới.</p>';
            return;
        }
        listEl.innerHTML = items
            .map(function (it) {
                return (
                    '<button type="button" class="digiseo-inbox-item" data-conv-id="' +
                    esc(it.conversation_id) +
                    '">' +
                    '<span class="digiseo-inbox-item-name">' +
                    esc(it.visitor_name || "Khách") +
                    "</span>" +
                    '<span class="digiseo-inbox-item-preview">' +
                    esc(it.preview || "") +
                    "</span>" +
                    '<span class="digiseo-inbox-item-time">' +
                    esc(formatTime(it.created_at)) +
                    "</span></button>"
                );
            })
            .join("");
        listEl.querySelectorAll("[data-conv-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                void openConversation(btn.getAttribute("data-conv-id"));
            });
        });
    }

    function applySnapshot(data) {
        if (!data || typeof data !== "object") return;
        if (Array.isArray(data.items)) items = data.items.slice();
        if (data.unread_count != null) unreadCount = Number(data.unread_count) || 0;
        else unreadCount = items.length;
        render();
    }

    function applyNew(payload) {
        var item = payload && payload.item;
        if (!item || !item.conversation_id) return;
        var cid = String(item.conversation_id);
        items = items.filter(function (x) {
            return String(x.conversation_id) !== cid;
        });
        items.unshift(item);
        if (payload.unread_count != null) unreadCount = Number(payload.unread_count) || items.length;
        else unreadCount = Math.max(unreadCount, items.length);
        render();
    }

    function applyRead(conversationId, count) {
        var cid = String(conversationId || "");
        items = items.filter(function (x) {
            return String(x.conversation_id) !== cid;
        });
        if (count != null) unreadCount = Math.max(0, Number(count) || 0);
        else unreadCount = items.length;
        render();
    }

    function handleEvent(payload, fromBc) {
        if (!payload || typeof payload !== "object") return;
        var t = String(payload.type || "");
        if (t === "inbox_snapshot") applySnapshot(payload);
        else if (t === "inbox_new") applyNew(payload);
        else if (t === "inbox_read") applyRead(payload.conversation_id, payload.unread_count);
        if (!fromBc && bc && (t === "inbox_new" || t === "inbox_read" || t === "inbox_snapshot")) {
            try {
                bc.postMessage(payload);
            } catch (_) {}
        }
    }

    function openCskhUrl(id) {
        return "/chatbot-cskh?tab=conversations&conversation_id=" + encodeURIComponent(id);
    }

    async function openConversation(id) {
        var cid = String(id || "").trim();
        if (!cid) return;
        applyRead(cid, Math.max(0, unreadCount - 1));
        setOpen(false);
        try {
            await fetch(API + "/inbox-notifications/" + encodeURIComponent(cid) + "/read", {
                method: "POST",
                credentials: "same-origin",
                headers: authHeaders(true),
                body: "{}",
            });
        } catch (_) {}
        var path = String(window.location.pathname || "").replace(/\/$/, "");
        if (path === "/chatbot-cskh" && typeof window.DigiSeoCskhOpenConversation === "function") {
            try {
                history.replaceState({}, "", openCskhUrl(cid));
            } catch (_) {}
            window.DigiSeoCskhOpenConversation(cid);
            return;
        }
        window.location.href = openCskhUrl(cid);
    }

    async function refresh() {
        if (!token()) {
            hide();
            return;
        }
        try {
            var res = await fetch(API + "/inbox-notifications", {
                credentials: "same-origin",
                headers: authHeaders(),
            });
            if (res.status === 401 || res.status === 403) {
                hide();
                return;
            }
            if (!res.ok) return;
            var data = await res.json();
            show();
            applySnapshot((data && data.data) || data || {});
        } catch (_) {}
    }

    function show() {
        if (root) root.hidden = false;
    }

    function hide() {
        if (root) root.hidden = true;
        setOpen(false);
        stopWs();
    }

    function stopWs() {
        if (wsTimer) {
            clearTimeout(wsTimer);
            wsTimer = null;
        }
        if (pingTimer) {
            clearInterval(pingTimer);
            pingTimer = null;
        }
        if (ws) {
            try {
                ws.onclose = null;
                ws.close();
            } catch (_) {}
            ws = null;
        }
    }

    function connectWs() {
        if (!token() || !root || root.hidden) return;
        stopWs();
        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + WS_PATH + "?token=" + encodeURIComponent(token());
        try {
            ws = new WebSocket(url);
        } catch (_) {
            return;
        }
        ws.onmessage = function (ev) {
            try {
                handleEvent(JSON.parse(ev.data), false);
            } catch (_) {}
        };
        ws.onopen = function () {
            if (pingTimer) clearInterval(pingTimer);
            pingTimer = setInterval(function () {
                if (ws && ws.readyState === 1) {
                    try {
                        ws.send(JSON.stringify({ type: "ping" }));
                    } catch (_) {}
                }
            }, 25000);
        };
        ws.onclose = function () {
            ws = null;
            if (pingTimer) {
                clearInterval(pingTimer);
                pingTimer = null;
            }
            if (!token() || (root && root.hidden)) return;
            wsTimer = setTimeout(connectWs, 4000);
        };
    }

    function bindUi() {
        if (!fab || !dropdown) return;
        fab.addEventListener("click", function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            setOpen(!open);
        });
        if (backdrop) {
            backdrop.addEventListener("click", function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                setOpen(false);
            });
        }
        document.addEventListener(
            "mousedown",
            function (ev) {
                if (!open || !root) return;
                var t = ev.target;
                if (root.contains(t)) return;
                setOpen(false);
            },
            true
        );
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape") setOpen(false);
        });
    }

    function start() {
        root = $("digiseoInboxNotify");
        fab = $("digiseoInboxFab");
        badgeEl = $("digiseoInboxBadge");
        dropdown = $("digiseoInboxDropdown");
        listEl = $("digiseoInboxList");
        backdrop = $("digiseoInboxBackdrop");
        if (!root || !fab) return;
        setOpen(false);
        bindUi();
        try {
            bc = new BroadcastChannel(BC_NAME);
            bc.onmessage = function (ev) {
                handleEvent(ev.data, true);
            };
        } catch (_) {
            bc = null;
        }
        void refresh().then(connectWs);
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(function () {
            if (!token()) return;
            if (ws && ws.readyState === 1) return;
            void refresh();
        }, 20000);
    }

    window.addEventListener("digiseo-auth-change", function (e) {
        if (e.detail && e.detail.loggedIn === false) hide();
        else void refresh().then(connectWs);
    });

    window.DigiSeoInboxNotify = {
        refresh: refresh,
        onConversationOpened: function (id) {
            applyRead(id, Math.max(0, unreadCount - 1));
        },
    };

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
