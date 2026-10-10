/**
 * SEOAuto Chatbot CSKH — embeddable website widget
 * <script src="https://seoauto.vn/chatbot/widget.js" data-bot-id="123"></script>
 */
(function () {
    "use strict";

    var script = document.currentScript;
    if (!script) return;

    var botId = String(script.getAttribute("data-bot-id") || "").trim();
    if (!botId) return;

    var apiOrigin;
    try {
        apiOrigin = new URL(script.src).origin;
    } catch (_e) {
        apiOrigin = "https://seoauto.vn";
    }

    var API = apiOrigin + "/api/chatbot/public";
    var LAUNCHER_IMG = apiOrigin + "/static/chatbot/cskh-launcher.png?v=1";
    var VISITOR_KEY = "seoauto_cskh_vid_" + botId;
    var LEGACY_SESSION_KEY = "seoauto_cskh_sid_" + botId;
    var ACTIVITY_KEY = "seoauto_cskh_last_" + botId;
    var COOKIE_NAME = "seoauto_cskh_vid_" + botId;
    var SESSION_TTL_MS = 24 * 60 * 60 * 1000;
    var LEAD_DISMISS_KEY = "seoauto_cskh_lead_dismissed_" + botId;
    var visitorId = "";

    function readCookie(name) {
        var prefix = name + "=";
        var parts = String(document.cookie || "").split(";");
        for (var i = 0; i < parts.length; i++) {
            var c = parts[i].trim();
            if (c.indexOf(prefix) === 0) {
                return decodeURIComponent(c.substring(prefix.length));
            }
        }
        return "";
    }

    function writeCookie(name, value, maxAgeDays) {
        var maxAge = Math.max(1, parseInt(maxAgeDays, 10) || 365) * 24 * 60 * 60;
        document.cookie =
            name + "=" + encodeURIComponent(value) +
            "; path=/; max-age=" + maxAge + "; SameSite=Lax";
    }

    function generateVisitorId() {
        if (window.crypto && crypto.randomUUID) {
            return String(crypto.randomUUID()).replace(/-/g, "");
        }
        var s = "";
        for (var i = 0; i < 32; i++) {
            s += Math.floor(Math.random() * 16).toString(16);
        }
        return s;
    }

    function isValidVisitorId(id) {
        return /^[a-zA-Z0-9_-]{8,64}$/.test(String(id || ""));
    }

    function touchActivity() {
        try {
            localStorage.setItem(ACTIVITY_KEY, String(Date.now()));
        } catch (_e) {}
    }

    function isClientSessionExpired() {
        try {
            var raw = localStorage.getItem(ACTIVITY_KEY);
            if (!raw) return false;
            var ts = parseInt(raw, 10);
            if (!ts || isNaN(ts)) return false;
            return Date.now() - ts > SESSION_TTL_MS;
        } catch (_e2) {
            return false;
        }
    }

    function loadVisitorId() {
        var id = "";
        try {
            id = localStorage.getItem(VISITOR_KEY) || "";
        } catch (_e3) {}
        if (!isValidVisitorId(id)) {
            id = readCookie(COOKIE_NAME) || "";
        }
        if (!isValidVisitorId(id)) {
            try {
                id = localStorage.getItem(LEGACY_SESSION_KEY) || "";
            } catch (_e4) {}
        }
        if (!isValidVisitorId(id)) {
            id = generateVisitorId();
        }
        saveVisitorId(id);
        return id;
    }

    function saveVisitorId(id) {
        if (!isValidVisitorId(id)) return;
        visitorId = id;
        try {
            localStorage.setItem(VISITOR_KEY, id);
        } catch (_e5) {}
        writeCookie(COOKIE_NAME, id, 365);
        touchActivity();
    }

    visitorId = loadVisitorId();

    function isLeadDismissed() {
        try {
            return sessionStorage.getItem(LEAD_DISMISS_KEY) === "1";
        } catch (_e) {
            return false;
        }
    }

    function setLeadDismissed() {
        try {
            sessionStorage.setItem(LEAD_DISMISS_KEY, "1");
        } catch (_e) {}
    }

    var state = {
        open: false,
        blocked: false,
        blockedMsg: "",
        botName: "Chatbot",
        greeting: "",
        avatarUrl: LAUNCHER_IMG,
        hotline: "",
        messages: [],
        offerLead: false,
        leadFormOpen: false,
        leadSubmitted: false,
        leadDismissed: isLeadDismissed(),
        loading: false,
        lastSendAt: 0,
    };

    var MIN_SEND_MS = 2000;

    var root = document.createElement("div");
    root.id = "seoauto-cskh-widget";
    root.setAttribute("data-bot-id", botId);
    document.body.appendChild(root);

    var style = document.createElement("style");
    style.textContent = [
        "#seoauto-cskh-widget{--sa-primary:#4f46e5;--sa-bg:#fff;--sa-text:#0f172a;--sa-muted:#64748b;--sa-border:#e2e8f0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.45;z-index:2147483000;position:fixed;right:16px;bottom:16px}",
        "#seoauto-cskh-widget *{box-sizing:border-box}",
        ".sa-cskh-launcher{width:64px;height:64px;border-radius:50%;border:none;background:linear-gradient(135deg,#4f46e5,#6366f1);padding:0;cursor:pointer;box-shadow:0 8px 28px rgba(79,70,229,.28);display:flex;align-items:center;justify-content:center;transition:transform .15s,box-shadow .15s;overflow:hidden;color:#fff}",
        ".sa-cskh-launcher:hover{transform:scale(1.05);box-shadow:0 10px 32px rgba(79,70,229,.35)}",
        ".sa-cskh-launcher img{width:100%;height:100%;object-fit:cover;display:block;border-radius:50%}",
        ".sa-cskh-launcher svg{width:34px;height:34px;display:block}",
        ".sa-cskh-panel{display:none;width:min(380px,calc(100vw - 24px));height:min(560px,calc(100vh - 96px));background:var(--sa-bg);border-radius:16px;box-shadow:0 16px 48px rgba(15,23,42,.18);overflow:hidden;flex-direction:column;border:1px solid var(--sa-border)}",
        ".sa-cskh-panel.is-open{display:flex}",
        ".sa-cskh-head{display:flex;align-items:center;gap:10px;padding:12px 14px;background:linear-gradient(135deg,#4f46e5,#6366f1);color:#fff;flex:0 0 auto}",
        ".sa-cskh-avatar{width:40px;height:40px;border-radius:50%;object-fit:cover;background:#fff}",
        ".sa-cskh-head-text{flex:1;min-width:0}",
        ".sa-cskh-head-text strong{display:block;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
        ".sa-cskh-head-text span{font-size:12px;opacity:.9}",
        ".sa-cskh-close{background:rgba(255,255,255,.2);border:none;color:#fff;width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:18px;line-height:1}",
        ".sa-cskh-body{flex:1;overflow:auto;padding:12px;background:#f8fafc;min-height:0}",
        ".sa-cskh-msg{max-width:88%;margin:0 0 10px;padding:10px 12px;border-radius:12px;word-break:break-word}",
        ".sa-cskh-msg--bot{background:#fff;border:1px solid var(--sa-border);color:var(--sa-text)}",
        ".sa-cskh-msg--user{margin-left:auto;background:var(--sa-primary);color:#fff}",
        ".sa-cskh-msg--sys{background:#fef3c7;border:1px solid #fde68a;color:#92400e;font-size:13px}",
        ".sa-cskh-msg--typing{background:#fff;border:1px solid var(--sa-border);color:var(--sa-muted);font-style:italic;font-size:13px}",
        ".sa-cskh-lead-cta{margin:4px 0 10px;display:flex;flex-wrap:wrap;gap:8px}",
        ".sa-cskh-lead-cta button{border:1px solid var(--sa-primary);background:#eef2ff;color:#3730a3;border-radius:999px;padding:8px 12px;font:inherit;font-weight:600;font-size:13px;cursor:pointer}",
        ".sa-cskh-lead-cta button:hover{background:#e0e7ff}",
        ".sa-cskh-lead{margin-top:4px;margin-bottom:10px;padding:12px;background:#fff;border:1px solid var(--sa-border);border-radius:12px;max-height:min(42vh,280px);overflow:auto}",
        ".sa-cskh-lead-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:0 0 8px}",
        ".sa-cskh-lead-head strong{font-size:13px;color:var(--sa-text)}",
        ".sa-cskh-lead-close{border:none;background:#f1f5f9;color:#475569;width:28px;height:28px;border-radius:8px;cursor:pointer;font-size:16px;line-height:1;flex:0 0 auto}",
        ".sa-cskh-lead label{display:block;font-size:12px;color:var(--sa-muted);margin:0 0 4px}",
        ".sa-cskh-lead input,.sa-cskh-lead textarea{width:100%;border:1px solid var(--sa-border);border-radius:8px;padding:8px 10px;margin:0 0 8px;font:inherit}",
        ".sa-cskh-lead textarea{min-height:56px;max-height:96px;resize:vertical}",
        ".sa-cskh-lead-actions{display:flex;gap:8px}",
        ".sa-cskh-lead-actions button{flex:1;border:none;border-radius:8px;padding:10px;font-weight:600;cursor:pointer;font:inherit}",
        ".sa-lead-submit{background:var(--sa-primary);color:#fff}",
        ".sa-lead-cancel{background:#f1f5f9;color:#334155}",
        ".sa-cskh-foot{padding:10px;border-top:1px solid var(--sa-border);background:#fff;display:flex;gap:8px;flex:0 0 auto}",
        ".sa-cskh-foot input{flex:1;border:1px solid var(--sa-border);border-radius:10px;padding:10px 12px;font:inherit}",
        ".sa-cskh-foot button{border:none;border-radius:10px;padding:0 14px;background:var(--sa-primary);color:#fff;font-weight:600;cursor:pointer}",
        ".sa-cskh-foot button:disabled{opacity:.55;cursor:not-allowed}",
        "@media(max-width:480px){#seoauto-cskh-widget{right:8px;bottom:8px;left:8px}.sa-cskh-panel{width:100%;height:min(78vh,calc(100vh - 72px));max-height:calc(100dvh - 72px)}.sa-cskh-lead{max-height:min(36vh,220px)}}",
    ].join("");
    document.head.appendChild(style);

    function esc(s) {
        return String(s || "").replace(/[&<>"']/g, function (c) {
            return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
        });
    }

    function fmtReply(text) {
        return esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    }

    function pageUrl() {
        try {
            return window.location.href || "";
        } catch (_e) {
            return "";
        }
    }

    function extractReply(data) {
        if (!data || typeof data !== "object") return "";
        return String(data.reply || data.message || "").trim();
    }

    async function apiPost(path, body) {
        var r = await fetch(API + path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            mode: "cors",
            credentials: "omit",
        });
        var data = {};
        try {
            data = await r.json();
        } catch (_e) {}
        return { ok: r.ok, status: r.status, data: data };
    }

    async function apiGet(path) {
        var r = await fetch(API + path, { method: "GET", mode: "cors", credentials: "omit" });
        var data = {};
        try {
            data = await r.json();
        } catch (_e) {}
        return { ok: r.ok, status: r.status, data: data };
    }

    function applyVisitorFromResponse(data) {
        if (!data || typeof data !== "object") return;
        var vid = data.visitor_id || data.session_id || "";
        if (isValidVisitorId(vid)) saveVisitorId(vid);
    }

    function saveSession(sid) {
        applyVisitorFromResponse({ visitor_id: sid, session_id: sid });
    }

    function setComposerEnabled(enabled) {
        var footInput = root.querySelector(".sa-cskh-input");
        var footBtn = root.querySelector(".sa-cskh-send");
        if (footInput) footInput.disabled = !!state.blocked;
        if (footBtn) footBtn.disabled = !enabled || state.blocked;
        if (enabled && !state.blocked) focusComposer();
    }

    function focusComposer() {
        if (state.blocked || !state.open) return;
        var run = function () {
            var input = root.querySelector(".sa-cskh-input");
            if (!input || input.disabled) return;
            try {
                input.focus({ preventScroll: true });
            } catch (_e) {
                input.focus();
            }
        };
        run();
        setTimeout(run, 0);
    }

    function canShowLeadUi() {
        return state.offerLead && !state.leadSubmitted && !state.leadDismissed;
    }

    function openLeadForm() {
        if (state.leadSubmitted || state.leadDismissed) return;
        state.leadFormOpen = true;
        renderMessages();
    }

    function closeLeadForm(dismissSession) {
        state.leadFormOpen = false;
        if (dismissSession) {
            state.leadDismissed = true;
            state.offerLead = false;
            setLeadDismissed();
        }
        renderMessages();
    }

    function renderMessages() {
        var body = root.querySelector(".sa-cskh-body");
        if (!body) return;
        var html = "";
        state.messages.forEach(function (m) {
            var cls = m.role === "user" ? "sa-cskh-msg--user" : m.role === "sys" ? "sa-cskh-msg--sys" : m.role === "typing" ? "sa-cskh-msg--typing" : "sa-cskh-msg--bot";
            html += '<div class="sa-cskh-msg ' + cls + '">' + (m.role === "bot" ? fmtReply(m.text) : esc(m.text)) + "</div>";
        });
        if (state.loading) {
            html += '<div class="sa-cskh-msg sa-cskh-msg--typing">Đang trả lời…</div>';
        }
        if (canShowLeadUi()) {
            if (state.leadFormOpen) {
                html += '<div class="sa-cskh-lead" role="form" aria-label="Form tư vấn">' +
                    '<div class="sa-cskh-lead-head"><strong>Để lại thông tin tư vấn</strong>' +
                    '<button type="button" class="sa-cskh-lead-close" aria-label="Đóng form">×</button></div>' +
                    '<label>Họ tên</label><input type="text" class="sa-lead-name" placeholder="Tên của bạn" autocomplete="name">' +
                    '<label>Số điện thoại *</label><input type="tel" class="sa-lead-phone" placeholder="09xxxxxxxx" autocomplete="tel">' +
                    '<label>Nhu cầu</label><textarea class="sa-lead-need" placeholder="Bạn cần tư vấn gì?"></textarea>' +
                    '<div class="sa-cskh-lead-actions">' +
                    '<button type="button" class="sa-lead-cancel">Đóng</button>' +
                    '<button type="button" class="sa-lead-submit">Gửi thông tin</button>' +
                    "</div></div>";
            } else {
                html += '<div class="sa-cskh-lead-cta">' +
                    '<button type="button" class="sa-lead-open">Để lại thông tin tư vấn</button>' +
                    "</div>";
            }
        }
        body.innerHTML = html;
        body.scrollTop = body.scrollHeight;

        var openBtn = body.querySelector(".sa-lead-open");
        if (openBtn) openBtn.addEventListener("click", openLeadForm);
        var closeBtn = body.querySelector(".sa-cskh-lead-close");
        if (closeBtn) closeBtn.addEventListener("click", function () { closeLeadForm(true); });
        var cancelBtn = body.querySelector(".sa-lead-cancel");
        if (cancelBtn) cancelBtn.addEventListener("click", function () { closeLeadForm(true); });
        var submitBtn = body.querySelector(".sa-lead-submit");
        if (submitBtn) submitBtn.addEventListener("click", submitLead);
    }

    function renderShell() {
        root.innerHTML =
            '<div class="sa-cskh-panel' + (state.open ? " is-open" : "") + '">' +
            '<div class="sa-cskh-head">' +
            '<img class="sa-cskh-avatar" src="' + esc(state.avatarUrl) + '" alt="">' +
            '<div class="sa-cskh-head-text"><strong>' + esc(state.botName) + "</strong>" +
            "<span>Trợ lý ảo</span></div>" +
            '<button type="button" class="sa-cskh-close" aria-label="Đóng">×</button></div>' +
            '<div class="sa-cskh-body"></div>' +
            '<div class="sa-cskh-foot">' +
            '<input type="text" class="sa-cskh-input" placeholder="Nhập tin nhắn…" maxlength="2000"' +
            (state.blocked ? " disabled" : "") + ">" +
            '<button type="button" class="sa-cskh-send"' + (state.blocked ? " disabled" : "") + ">Gửi</button></div></div>" +
            '<button type="button" class="sa-cskh-launcher" aria-label="Mở chat">' +
            '<img src="' + esc(state.avatarUrl || LAUNCHER_IMG) + '" alt="Chatbot CSKH" width="64" height="64" decoding="async">' +
            '<svg class="sa-cskh-launcher-fallback" viewBox="0 0 24 24" fill="none" aria-hidden="true" hidden>' +
            '<path d="M12 3c4.4 0 8 3.1 8 7s-3.6 7-8 7c-.7 0-1.4-.1-2.1-.2L6 19.5 7 16C4.6 14.6 4 12.5 4 10c0-3.9 3.6-7 8-7z" fill="#fff"/>' +
            "</svg></button>";

        var launcher = root.querySelector(".sa-cskh-launcher");
        var launchImg = launcher ? launcher.querySelector("img") : null;
        var launchFallback = launcher ? launcher.querySelector(".sa-cskh-launcher-fallback") : null;
        if (launchImg && launchFallback) {
            launchImg.addEventListener("error", function () {
                launchImg.style.display = "none";
                launchFallback.removeAttribute("hidden");
            });
        }
        root.querySelector(".sa-cskh-launcher").addEventListener("click", toggleOpen);
        root.querySelector(".sa-cskh-close").addEventListener("click", function () {
            state.open = false;
            renderShell();
            renderMessages();
        });
        var sendBtn = root.querySelector(".sa-cskh-send");
        var input = root.querySelector(".sa-cskh-input");
        if (sendBtn) sendBtn.addEventListener("click", sendMessage);
        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }
        renderMessages();
        if (state.open) focusComposer();
    }

    function toggleOpen() {
        state.open = !state.open;
        var panel = root.querySelector(".sa-cskh-panel");
        var launcher = root.querySelector(".sa-cskh-launcher");
        if (panel) panel.classList.toggle("is-open", state.open);
        if (launcher) launcher.style.display = state.open ? "none" : "flex";
        if (state.open) {
            var body = root.querySelector(".sa-cskh-body");
            if (body) body.scrollTop = body.scrollHeight;
            focusComposer();
        }
    }

    async function sendMessage() {
        if (state.blocked || state.loading) {
            focusComposer();
            return;
        }
        var now = Date.now();
        if (state.lastSendAt && now - state.lastSendAt < MIN_SEND_MS) {
            state.messages.push({ role: "sys", text: "Vui lòng đợi vài giây trước khi gửi tiếp." });
            renderMessages();
            focusComposer();
            return;
        }
        var input = root.querySelector(".sa-cskh-input");
        var text = input ? String(input.value || "").trim() : "";
        if (!text) {
            focusComposer();
            return;
        }
        state.loading = true;
        state.lastSendAt = now;
        state.messages.push({ role: "user", text: text });
        if (input) input.value = "";
        setComposerEnabled(false);
        renderMessages();
        focusComposer();
        try {
            var res = await apiPost("/message", {
                bot_id: Number(botId),
                message: text,
                visitor_id: visitorId || null,
                session_id: visitorId || null,
                page_url: pageUrl(),
            });
            var data = res.data || {};
            applyVisitorFromResponse(data);
            touchActivity();
            var replyText = extractReply(data);
            if (!res.ok && !replyText) {
                replyText = "Không gửi được tin nhắn (mã " + res.status + "). Vui lòng thử lại.";
            }
            if (data.code === "rate_limited" || (data.blocked && data.code === "rate_limited")) {
                state.messages.push({ role: "sys", text: replyText || "Bạn gửi quá nhanh. Vui lòng đợi vài giây." });
            } else if (data.blocked) {
                state.blocked = true;
                state.blockedMsg = replyText || "Chatbot tạm ngưng.";
                state.messages.push({ role: "sys", text: state.blockedMsg });
                if (data.show_lead_form && !state.leadDismissed && !state.leadSubmitted) {
                    state.offerLead = true;
                    state.leadFormOpen = false;
                }
            } else if (replyText) {
                state.messages.push({ role: "bot", text: replyText });
                if (data.show_lead_form && !state.leadDismissed && !state.leadSubmitted) {
                    state.offerLead = true;
                    // Never auto-open form — only show CTA button.
                    state.leadFormOpen = false;
                }
            } else {
                state.messages.push({
                    role: "sys",
                    text: "Không nhận được phản hồi từ server. Vui lòng thử lại sau.",
                });
            }
        } catch (_err) {
            state.messages.push({
                role: "sys",
                text: "Mất kết nối tới server chatbot. Kiểm tra mạng và thử lại.",
            });
        } finally {
            state.loading = false;
            setComposerEnabled(!state.blocked);
            renderMessages();
            focusComposer();
        }
    }

    async function submitLead() {
        var body = root.querySelector(".sa-cskh-body");
        if (!body) return;
        var name = (body.querySelector(".sa-lead-name") || {}).value || "";
        var phone = String((body.querySelector(".sa-lead-phone") || {}).value || "").trim();
        var need = (body.querySelector(".sa-lead-need") || {}).value || "";
        if (phone.length < 6) {
            state.messages.push({ role: "sys", text: "Vui lòng nhập số điện thoại hợp lệ." });
            renderMessages();
            return;
        }
        var leadRes = await apiPost("/lead", {
            bot_id: Number(botId),
            visitor_id: visitorId || null,
            session_id: visitorId || null,
            name: name.trim(),
            phone: phone,
            need: need.trim(),
            page_url: pageUrl(),
        });
        var data = leadRes.data || {};
        applyVisitorFromResponse(data);
        touchActivity();
        state.leadSubmitted = true;
        state.offerLead = false;
        state.leadFormOpen = false;
        state.messages.push({ role: "bot", text: data.message || "Cảm ơn bạn! Chúng tôi sẽ liên hệ sớm." });
        renderMessages();
    }

    async function loadHistory() {
        if (!visitorId) visitorId = loadVisitorId();
        var histRes = await apiGet(
            "/history?bot_id=" + encodeURIComponent(botId) +
            "&visitor_id=" + encodeURIComponent(visitorId) +
            "&page_url=" + encodeURIComponent(pageUrl())
        );
        var hist = histRes.data || {};
        applyVisitorFromResponse(hist);
        if (hist.expired) {
            state.messages = [];
            try {
                localStorage.removeItem(ACTIVITY_KEY);
            } catch (_e) {}
        }
        if (Array.isArray(hist.messages) && hist.messages.length) {
            state.messages = hist.messages.map(function (m) {
                return {
                    role: m.role === "user" ? "user" : "bot",
                    text: String(m.text || ""),
                };
            });
            if (hist.show_lead_form && !state.leadDismissed) {
                state.offerLead = true;
            }
            if (hist.lead_submitted) {
                state.leadSubmitted = true;
                state.offerLead = false;
            }
            touchActivity();
            return true;
        }
        return false;
    }

    async function init() {
        renderShell();
        if (isClientSessionExpired()) {
            state.messages = [];
        }
        var cfgRes = await apiGet(
            "/config?bot_id=" + encodeURIComponent(botId) +
            "&page_url=" + encodeURIComponent(pageUrl())
        );
        var cfg = cfgRes.data || {};
        if (cfg.bot_name) state.botName = cfg.bot_name;
        if (cfg.avatar_url) state.avatarUrl = cfg.avatar_url;
        else state.avatarUrl = LAUNCHER_IMG;
        if (cfg.hotline) state.hotline = cfg.hotline;

        var hasHistory = false;
        if (!cfg.blocked) {
            hasHistory = await loadHistory();
        }

        if (cfg.blocked) {
            state.blocked = true;
            state.blockedMsg = extractReply(cfg) || "Chatbot tạm ngưng.";
            if (!state.messages.length) {
                state.messages.push({ role: "sys", text: state.blockedMsg });
            }
        } else if (!hasHistory && !state.messages.length) {
            var greet = cfg.greeting || "Xin chào! Tôi có thể hỗ trợ gì cho bạn?";
            state.greeting = greet;
            state.messages.push({ role: "bot", text: greet });
        } else if (!state.greeting && cfg.greeting) {
            state.greeting = cfg.greeting;
        }
        renderShell();
        renderMessages();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
