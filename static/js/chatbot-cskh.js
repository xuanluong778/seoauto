/**
 * Chatbot CSKH — SaaS UI
 */
(function () {
    "use strict";

    var API = "/api/chatbot";
    var API_LEGACY = "/api/chatbot-cskh";
    var state = {
        access: null,
        overview: null,
        tab: "overview",
        bots: [],
        sourceMode: "faq",
        convFilter: "all",
        activeConversationId: null,
        scanning: false,
        connectionError: false,
        kbNodes: [],
        kbMap: null,
        kbPreviewMessages: [],
        pendingKbImport: false,
    };

    function $(id) { return document.getElementById(id); }

    function authToken() {
        return typeof window.DigiSeoGetAuthToken === "function" ? window.DigiSeoGetAuthToken() : "";
    }

    function authHeaders(json) {
        var h = {};
        if (json) h["Content-Type"] = "application/json";
        var t = authToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function showToast(msg) {
        var el = $("cskhToast");
        if (!el) return;
        el.textContent = String(msg || "");
        el.classList.add("is-visible");
        clearTimeout(showToast._t);
        showToast._t = setTimeout(function () { el.classList.remove("is-visible"); }, 3200);
    }

    function apiDetail(data) {
        if (!data) return "Có lỗi xảy ra.";
        var d = data.detail;
        if (typeof d === "string") return d;
        if (d && d.message) return String(d.message);
        return "Có lỗi xảy ra.";
    }

    function apiErrorInfo(data) {
        var d = data && data.detail;
        if (!d || typeof d === "string") return { message: apiDetail(data), code: "", upgrade_url: "/pricing" };
        return {
            message: String(d.message || apiDetail(data)),
            code: String(d.code || ""),
            upgrade_url: String(d.upgrade_url || "/pricing"),
        };
    }

    function showUpgradeCta(message, upgradeUrl) {
        showToast(message);
        var wall = $("cskhUpgradeWall");
        var app = $("cskhApp");
        if (!wall) return;
        var title = $("cskhUpgradeTitle");
        var msg = $("cskhUpgradeMsg");
        if (title) title.textContent = "Nâng cấp gói để tiếp tục";
        if (msg) msg.textContent = message || "Nâng cấp gói SEOAuto để tạo thêm chatbot hoặc tăng lượt AI trả lời.";
        wall.hidden = false;
        if (app) app.hidden = true;
        var btn = $("cskhBtnUpgrade");
        if (btn) btn.onclick = function () { window.location.href = upgradeUrl || "/pricing"; };
    }

    async function apiFetch(path, opts) {
        opts = opts || {};
        var base = opts.legacy ? API_LEGACY : API;
        var r = await fetch(base + path, {
            method: opts.method || "GET",
            headers: authHeaders(opts.json),
            body: opts.body ? JSON.stringify(opts.body) : undefined,
            credentials: "same-origin",
            cache: "no-store",
        });
        var data = {};
        try { data = await r.json(); } catch (_e) {}
        if (!r.ok) {
            var err = new Error(apiDetail(data));
            err.code = apiErrorInfo(data).code;
            err.upgrade_url = apiErrorInfo(data).upgrade_url;
            err.payload = data;
            throw err;
        }
        return data;
    }

    function esc(s) {
        return String(s || "").replace(/[&<>"']/g, function (c) {
            return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
        });
    }

    function statusBadge(status) {
        var s = String(status || "draft").toLowerCase();
        var cls = s;
        var labels = {
            draft: "Draft",
            active: "Active",
            paused: "Paused",
            failed: "Error",
            error: "Error",
            pending: "Đang quét",
            ready: "Active",
            open: "Mở",
            needs_staff: "Cần tư vấn",
            handled: "Đã xử lý",
            new: "Mới",
            consulting: "Tư vấn",
            won: "Đã chốt",
            no_potential: "Không tiềm năng",
            disabled: "Disabled",
        };
        if (s === "failed" || s === "error") cls = "error";
        if (s === "ready") cls = "active";
        return '<span class="cskh-badge cskh-badge--' + esc(cls) + '">' + esc(labels[s] || s) + "</span>";
    }

    function statusTag(status) {
        return statusBadge(status);
    }

    function emptyState(title, hint, ctaHtml) {
        return '<div class="cskh-empty-state"><strong>' + esc(title) + "</strong><p>" + esc(hint) + "</p>" +
            (ctaHtml || "") + "</div>";
    }

    function renderStateBanner() {
        var el = $("cskhStateBanner");
        if (!el || !state.access || !state.access.allowed) {
            if (el) el.hidden = true;
            return;
        }
        var access = state.access;
        var ov = state.overview || {};
        var botsTotal = Number(ov.bots_total || 0);
        var botsActive = Number(ov.bots_active || 0);
        var remaining = ov.replies_remaining != null ? ov.replies_remaining : access.replies_remaining;
        var limit = access.effective_reply_limit;
        var html = "";
        var kind = "";

        if (state.connectionError) {
            kind = "error";
            html = '<div class="cskh-state-banner-text"><strong>Lỗi kết nối Fanpage.</strong> Webhook Messenger chưa subscribe — thử kết nối lại Fanpage hoặc kiểm tra cấu hình Meta.</div>' +
                '<button type="button" class="cskh-btn cskh-btn--secondary cskh-btn--sm" data-cskh-goto="channels">Kiểm tra kênh</button>';
        } else if (limit != null && remaining === 0 && botsTotal > 0) {
            kind = "no-credit";
            html = '<div class="cskh-state-banner-text"><strong>Hết credit AI tháng này.</strong> Bot vẫn nhận tin nhưng không tự trả lời — nâng cấp gói hoặc mua thêm credit.</div>' +
                '<button type="button" class="cskh-btn cskh-btn--secondary cskh-btn--sm" onclick="window.location.href=\'/pricing\'">Nâng cấp gói</button>';
        } else if (state.scanning) {
            kind = "scanning";
            html = '<div class="cskh-state-banner-text"><strong>Đang quét dữ liệu.</strong> Một hoặc nhiều nguồn website đang được xử lý — vui lòng đợi vài phút.</div>';
        } else if (botsTotal === 0) {
            kind = "no-bot";
            html = '<div class="cskh-state-banner-text"><strong>Chưa tạo chatbot.</strong> Tạo bot đầu tiên, thêm nguồn dữ liệu và nhúng widget lên website.</div>' +
                '<button type="button" class="cskh-btn cskh-btn--primary cskh-btn--sm" data-cskh-goto="bots">+ Tạo chatbot</button>';
        } else if (botsTotal > 0 && botsActive === 0) {
            kind = "no-bot";
            html = '<div class="cskh-state-banner-text"><strong>Bot chưa kích hoạt.</strong> Kích hoạt chatbot để widget hiển thị và AI bắt đầu trả lời khách.</div>' +
                '<button type="button" class="cskh-btn cskh-btn--primary cskh-btn--sm" data-cskh-goto="bots">Kích hoạt bot</button>';
        } else if (botsActive > 0) {
            kind = "active";
            html = '<div class="cskh-state-banner-text"><strong>Bot đang hoạt động.</strong> ' + botsActive + " chatbot đang phục vụ khách — theo dõi hội thoại và lead bên dưới.</div>" +
                '<button type="button" class="cskh-btn cskh-btn--secondary cskh-btn--sm" data-cskh-goto="conversations">Xem hội thoại</button>';
        } else {
            el.hidden = true;
            el.className = "cskh-state-banner";
            return;
        }

        el.className = "cskh-state-banner cskh-state-banner--" + kind;
        el.innerHTML = html;
        el.hidden = false;
        el.querySelectorAll("[data-cskh-goto]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setTab(btn.getAttribute("data-cskh-goto"));
            });
        });
    }

    function setTab(tab) {
        state.tab = tab;
        document.querySelectorAll(".cskh-nav-item, .cskh-tab").forEach(function (btn) {
            var on = btn.getAttribute("data-cskh-tab") === tab;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll(".cskh-panel").forEach(function (panel) {
            var on = panel.getAttribute("data-cskh-panel") === tab;
            panel.classList.toggle("active", on);
            panel.hidden = !on;
        });
        if (state.access && state.access.allowed) {
            if (tab === "overview") loadOverview();
            if (tab === "bots") loadBots();
            if (tab === "sources") { loadBotsForSources(); }
            if (tab === "kb") { loadBotsForKb(); }
            if (tab === "channels") loadChannels();
            if (tab === "conversations") { loadBotsForInbox(); }
            if (tab === "settings") loadSettings();
        }
    }

    function renderAccess(access) {
        state.access = access;
        var upgrade = $("cskhUpgradeWall");
        var app = $("cskhApp");
        var badge = $("cskhPlanBadge");
        var upgradeTitle = $("cskhUpgradeTitle");
        var upgradeMsg = $("cskhUpgradeMsg");

        if (!access || !access.logged_in) {
            if (upgradeTitle) upgradeTitle.textContent = "Đăng nhập để xem Chatbot CSKH";
            if (upgradeMsg) upgradeMsg.textContent = "Đăng nhập tài khoản SEOAuto để xem demo và nâng cấp gói sử dụng chatbot chăm sóc khách hàng.";
            if (upgrade) upgrade.hidden = false;
            if (app) app.hidden = true;
            if (badge) badge.hidden = true;
            return;
        }

        if (!access.allowed) {
            if (upgradeTitle) upgradeTitle.textContent = "Gói Free — chỉ xem demo";
            if (upgradeMsg) upgradeMsg.textContent = access.message || "Gói Free chỉ xem demo. Nâng cấp Basic, Pro, Agency hoặc Business để tạo chatbot.";
            if (upgrade) upgrade.hidden = false;
            if (app) app.hidden = true;
            if (badge) badge.hidden = true;
            return;
        }

        if (upgrade) upgrade.hidden = true;
        if (app) app.hidden = false;
        if (state.pendingKbImport && access.allowed) {
            state.pendingKbImport = false;
            setTimeout(function () { openKbImportModal(); }, 300);
        }
        if (badge) {
            badge.hidden = false;
            var badgeText = "Gói: " + (access.plan_name || access.plan_slug || "—");
            if (access.effective_reply_limit != null) {
                badgeText += " · AI: " + (access.monthly_replies_used || 0) + "/" + access.effective_reply_limit;
            }
            if (access.bot_limit != null) {
                badgeText += " · Bot: " + (access.bots_count != null ? access.bots_count : "0") + "/" + access.bot_limit;
            }
            badge.textContent = badgeText;
        }
        renderStateBanner();
        loadOverview();
    }

    async function loadAccess() {
        try {
            var res = await apiFetch("/access");
            renderAccess(res);
        } catch (e) {
            showToast(e.message || "Không tải được quyền truy cập.");
        }
    }

    async function loadOverview() {
        try {
            var res = await apiFetch("/overview");
            var d = res.data || {};
            state.overview = d;
            var used = d.monthly_replies_used != null ? d.monthly_replies_used : 0;
            var limit = d.effective_reply_limit != null ? d.effective_reply_limit : 0;
            var remaining = d.replies_remaining != null ? d.replies_remaining : Math.max(0, limit - used);
            var map = {
                cskhStatBots: d.bots_total,
                cskhStatSources: d.sources_total,
                cskhStatChannels: d.channels_total,
                cskhStatConversations: d.conversations_total,
                cskhStatLeads: d.leads_total,
                cskhStatCredits: d.credits_used_month,
                cskhStatReplyUsed: used,
                cskhStatBotLimit: (d.bots_count != null ? d.bots_count : 0) + "/" + (d.bot_limit != null ? d.bot_limit : "—"),
                cskhStatReplyRemaining: remaining + " lượt",
            };
            Object.keys(map).forEach(function (id) {
                var el = $(id);
                if (el) el.textContent = String(map[id] != null ? map[id] : "0");
            });
            var subBots = $("cskhStatBotsSub");
            if (subBots) subBots.textContent = (d.bots_active || 0) + " đang hoạt động";
            var subRate = $("cskhStatLeadRate");
            if (subRate) subRate.textContent = (d.lead_conversion_rate != null ? d.lead_conversion_rate : 0) + "% chuyển đổi";
            var subReply = $("cskhStatReplySub");
            if (subReply) subReply.textContent = "/ " + limit + " lượt";
            renderStateBanner();
        } catch (e) {
            showToast(e.message);
        }
    }

    async function loadBots() {
        var host = $("cskhBotsList");
        if (!host) return;
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        try {
            var res = await apiFetch("/bots");
            var items = res.data || [];
            if (!items.length) {
                host.innerHTML = emptyState(
                    "Chưa tạo chatbot",
                    "Tạo bot đầu tiên để bắt đầu phục vụ khách trên website và Messenger.",
                    '<button type="button" class="cskh-btn cskh-btn--primary cskh-btn--sm" data-cskh-goto="bots">+ Tạo chatbot</button>'
                );
                host.querySelectorAll("[data-cskh-goto]").forEach(function (btn) {
                    btn.addEventListener("click", function () { setTab(btn.getAttribute("data-cskh-goto")); });
                });
                return;
            }
            var html = '<div class="cskh-table-wrap"><table class="cskh-table"><thead><tr><th>Tên</th><th>Website</th><th>Trạng thái</th><th></th></tr></thead><tbody>';
            items.forEach(function (b) {
                var id = b.bot_id || b.id;
                var st = String(b.status || "draft").toLowerCase();
                html += "<tr><td><strong>" + esc(b.bot_name || b.name) + "</strong></td>" +
                    "<td>" + esc(b.website_url || "—") + "</td><td>" + statusBadge(st) + "</td><td>" +
                    '<div class="cskh-table-actions">';
                if (st !== "active") {
                    html += '<button type="button" class="cskh-btn cskh-btn--secondary cskh-btn--sm" data-bot-activate="' + esc(id) + '">Kích hoạt</button>';
                }
                html += '<button type="button" class="cskh-btn cskh-btn--ghost cskh-btn--sm" data-bot-embed="' + esc(id) + '">Copy mã</button>' +
                    '<button type="button" class="cskh-btn cskh-btn--danger cskh-btn--sm" data-bot-del="' + esc(id) + '">Xóa</button></div></td></tr>';
            });
            html += "</tbody></table></div>";
            host.innerHTML = html;
            host.querySelectorAll("[data-bot-del]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    deleteBot(btn.getAttribute("data-bot-del"));
                });
            });
            host.querySelectorAll("[data-bot-activate]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    activateBot(btn.getAttribute("data-bot-activate"));
                });
            });
            host.querySelectorAll("[data-bot-embed]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    showEmbedForBot(btn.getAttribute("data-bot-embed"));
                });
            });
        } catch (e) {
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    function showEmbedPanel(code) {
        var card = $("cskhEmbedCard");
        var pre = $("cskhEmbedCode");
        if (!card || !pre) return;
        pre.textContent = String(code || "");
        card.hidden = false;
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    async function showEmbedForBot(id) {
        try {
            var res = await apiFetch("/bots/" + encodeURIComponent(id));
            var b = res.data || {};
            showEmbedPanel(b.embed_code || "");
        } catch (e) {
            showToast(e.message);
        }
    }

    function copyEmbedCode() {
        var pre = $("cskhEmbedCode");
        var text = pre ? pre.textContent : "";
        if (!text) { showToast("Chưa có mã nhúng."); return; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () {
                showToast("Đã copy mã nhúng.");
            }).catch(function () {
                showToast("Không copy được — chọn và copy thủ công.");
            });
        } else {
            showToast("Chọn mã và copy thủ công.");
        }
    }

    async function createBot() {
        var name = ($("cskhBotName") || {}).value || "";
        if (!name.trim()) { showToast("Nhập tên chatbot."); return; }
        var body = {
            bot_name: name.trim(),
            website_url: (($("cskhBotWebsite") || {}).value || "").trim(),
            business_name: (($("cskhBotBusiness") || {}).value || "").trim(),
            industry: (($("cskhBotIndustry") || {}).value || "").trim(),
            hotline: (($("cskhBotHotline") || {}).value || "").trim(),
            main_services: (($("cskhBotServices") || {}).value || "").trim(),
            consultation_tone: (($("cskhBotTone") || {}).value || "friendly").trim(),
            status: "draft",
        };
        try {
            var res = await apiFetch("/bots", { method: "POST", body: body, json: true });
            var bot = res.data || {};
            if ($("cskhBotName")) $("cskhBotName").value = "";
            if ($("cskhBotWebsite")) $("cskhBotWebsite").value = "";
            if ($("cskhBotBusiness")) $("cskhBotBusiness").value = "";
            if ($("cskhBotIndustry")) $("cskhBotIndustry").value = "";
            if ($("cskhBotHotline")) $("cskhBotHotline").value = "";
            if ($("cskhBotServices")) $("cskhBotServices").value = "";
            showToast("Đã tạo chatbot. Kích hoạt để widget hoạt động trên website.");
            if (bot.embed_code) showEmbedPanel(bot.embed_code);
            loadBots();
            loadOverview();
        } catch (e) {
            if (e.code === "plan_required" || e.code === "bot_limit_exceeded" || e.code === "reply_limit_exceeded") {
                showUpgradeCta(e.message, e.upgrade_url);
            } else {
                showToast(e.message);
            }
        }
    }

    async function activateBot(id) {
        try {
            await apiFetch("/bots/" + encodeURIComponent(id), { method: "PUT", body: { status: "active" }, json: true });
            showToast("Đã kích hoạt chatbot.");
            loadBots();
        } catch (e) { showToast(e.message); }
    }

    async function deleteBot(id) {
        if (!confirm("Xóa chatbot này?")) return;
        try {
            await apiFetch("/bots/" + encodeURIComponent(id), { method: "DELETE" });
            showToast("Đã xóa chatbot.");
            loadBots();
            loadOverview();
        } catch (e) { showToast(e.message); }
    }

    function sourceTypeLabel(t) {
        var map = { faq: "FAQ", business: "Doanh nghiệp", website: "Website" };
        return map[String(t || "").toLowerCase()] || String(t || "—");
    }

    function formatDate(iso) {
        if (!iso) return "—";
        try {
            var d = new Date(iso);
            if (isNaN(d.getTime())) return String(iso).slice(0, 16);
            return d.toLocaleString("vi-VN");
        } catch (_e) {
            return String(iso).slice(0, 16);
        }
    }

    function selectedBotId() {
        var el = $("cskhSourceBot");
        var v = el ? String(el.value || "").trim() : "";
        return v ? parseInt(v, 10) : 0;
    }

    function selectedKbBotId() {
        var el = $("cskhKbBot");
        var v = el ? String(el.value || "").trim() : "";
        return v ? parseInt(v, 10) : 0;
    }

    function kbMapStatusBadge(status) {
        var s = String(status || "draft").toLowerCase();
        if (s === "active") return statusBadge("active");
        if (s === "disabled") return statusBadge("disabled");
        return statusBadge("draft");
    }

    function collectKbTags() {
        var host = $("cskhKbTags");
        if (!host) return [];
        var tags = [];
        host.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            if (cb.value) tags.push(cb.value);
        });
        return tags;
    }

    function setKbTags(tags) {
        var set = {};
        (tags || []).forEach(function (t) { set[String(t).toLowerCase()] = true; });
        var host = $("cskhKbTags");
        if (!host) return;
        host.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
            cb.checked = !!set[String(cb.value).toLowerCase()];
        });
    }

    function resetKbForm() {
        if ($("cskhKbEditNodeId")) $("cskhKbEditNodeId").value = "";
        if ($("cskhKbTitle")) $("cskhKbTitle").value = "";
        if ($("cskhKbContent")) $("cskhKbContent").value = "";
        if ($("cskhKbNodeType")) $("cskhKbNodeType").value = "node";
        if ($("cskhKbParent")) $("cskhKbParent").value = "";
        if ($("cskhKbPriority")) $("cskhKbPriority").value = "0";
        if ($("cskhKbActive")) $("cskhKbActive").checked = true;
        setKbTags([]);
        var card = $("cskhKbFormCard");
        if (card) card.hidden = true;
        if ($("cskhKbFormTitle")) $("cskhKbFormTitle").textContent = "Thêm node kiến thức";
    }

    function showKbForm(editNode) {
        var card = $("cskhKbFormCard");
        if (!card) return;
        resetKbForm();
        card.hidden = false;
        refreshKbParentSelect(editNode ? editNode.id : null);
        if (editNode) {
            if ($("cskhKbEditNodeId")) $("cskhKbEditNodeId").value = String(editNode.id);
            if ($("cskhKbFormTitle")) $("cskhKbFormTitle").textContent = "Sửa node kiến thức";
            if ($("cskhKbTitle")) $("cskhKbTitle").value = editNode.title || "";
            if ($("cskhKbContent")) $("cskhKbContent").value = editNode.content || "";
            if ($("cskhKbNodeType")) $("cskhKbNodeType").value = editNode.node_type || "node";
            if ($("cskhKbParent")) $("cskhKbParent").value = editNode.parent_id ? String(editNode.parent_id) : "";
            if ($("cskhKbPriority")) $("cskhKbPriority").value = String(editNode.priority != null ? editNode.priority : 0);
            if ($("cskhKbActive")) $("cskhKbActive").checked = !!editNode.is_active;
            setKbTags(editNode.tags || []);
        }
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function refreshKbParentSelect(excludeId) {
        var sel = $("cskhKbParent");
        if (!sel) return;
        var cur = sel.value;
        sel.innerHTML = '<option value="">— Không có —</option>';
        (state.kbNodes || []).forEach(function (n) {
            if (String(n.node_type) !== "group") return;
            if (excludeId && String(n.id) === String(excludeId)) return;
            var opt = document.createElement("option");
            opt.value = String(n.id);
            opt.textContent = n.title || ("Nhóm #" + n.id);
            sel.appendChild(opt);
        });
        if (cur) sel.value = cur;
    }

    function buildKbTreeHtml(nodes, parentId, depth) {
        depth = depth || 0;
        parentId = parentId == null ? null : parentId;
        var html = "";
        nodes.filter(function (n) {
            var pid = n.parent_id == null ? null : Number(n.parent_id);
            var want = parentId == null ? pid == null : pid === Number(parentId);
            return want;
        }).forEach(function (n) {
            var indent = depth * 16;
            var cls = "cskh-kb-node" + (n.node_type === "group" ? " cskh-kb-node--group" : "");
            if (!n.is_active) cls += " cskh-kb-node--inactive";
            html += '<div class="' + cls + '" style="margin-left:' + indent + 'px">';
            html += '<div class="cskh-kb-node-head"><div class="cskh-kb-node-title">' + esc(n.title) + "</div>";
            html += '<div class="cskh-kb-node-meta">';
            html += '<span class="cskh-tag cskh-tag--' + esc(n.node_type === "group" ? "open" : "active") + '">' +
                esc(n.node_type === "group" ? "Nhóm" : "Node") + "</span>";
            if (!n.is_active) html += statusBadge("disabled");
            (n.tags || []).forEach(function (t) {
                html += '<span class="cskh-tag cskh-tag--draft">' + esc(t) + "</span>";
            });
            html += "</div></div>";
            if (n.content && n.node_type !== "group") {
                html += '<div class="cskh-kb-node-content">' + esc(n.content.length > 280 ? n.content.slice(0, 280) + "…" : n.content) + "</div>";
            }
            html += '<div class="cskh-kb-node-actions">';
            html += '<button type="button" class="cskh-btn cskh-btn--ghost cskh-btn--sm" data-kb-edit="' + esc(n.id) + '">Sửa</button>';
            html += '<button type="button" class="cskh-btn cskh-btn--ghost cskh-btn--sm" data-kb-toggle="' + esc(n.id) + '">' +
                (n.is_active ? "Tắt" : "Bật") + "</button>";
            html += '<button type="button" class="cskh-btn cskh-btn--danger cskh-btn--sm" data-kb-del="' + esc(n.id) + '">Xóa</button>';
            html += "</div></div>";
            html += buildKbTreeHtml(nodes, n.id, depth + 1);
        });
        return html;
    }

    async function loadBotsForKb() {
        var sel = $("cskhKbBot");
        if (!sel) return;
        try {
            var res = await apiFetch("/bots");
            var items = res.data || [];
            var cur = sel.value;
            sel.innerHTML = '<option value="">— Chọn chatbot —</option>';
            items.forEach(function (b) {
                var id = b.bot_id || b.id;
                var opt = document.createElement("option");
                opt.value = String(id);
                opt.textContent = (b.bot_name || b.name || "Bot") + " (#" + id + ")";
                sel.appendChild(opt);
            });
            if (cur) sel.value = cur;
            if (!sel.value && items.length === 1) {
                sel.value = String(items[0].bot_id || items[0].id);
            }
            loadKb();
        } catch (e) {
            showToast(e.message);
        }
    }

    async function loadKb() {
        var host = $("cskhKbNodesList");
        var badgeHost = $("cskhKbMapBadge");
        var syncEl = $("cskhKbSyncBadge");
        var KB = window.SeoautoChatbotKb;
        if (!host) return;
        var botId = selectedKbBotId();
        if (!botId) {
            host.innerHTML = '<p class="cskh-empty">Chọn chatbot để quản lý sơ đồ tri thức.</p>';
            if (badgeHost) badgeHost.innerHTML = "";
            if (syncEl) syncEl.hidden = true;
            state.kbNodes = [];
            state.kbMap = null;
            return;
        }
        if (KB) KB.setProcessing(syncEl);
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        try {
            var res = await apiFetch("/kb/" + encodeURIComponent(botId));
            var d = res.data || {};
            state.kbNodes = d.nodes || [];
            state.kbMap = d.map || null;
            refreshKbParentSelect();
            fillKbImportParentOptions();
            if (badgeHost) {
                badgeHost.innerHTML = state.kbMap ? kbMapStatusBadge(state.kbMap.status) : statusBadge("draft");
            }
            if (KB) {
                KB.renderSyncBadge(syncEl, KB.syncStatusFromData(d), d.synced_at);
            }
            if (!state.kbNodes.length) {
                host.innerHTML = emptyState(
                    "Chưa có sơ đồ tri thức",
                    "Hãy import FAQ, nội dung doanh nghiệp, website đã quét hoặc tải file để chatbot trả lời chính xác hơn.",
                    '<button type="button" class="cskh-btn cskh-btn--primary cskh-btn--sm" id="cskhKbEmptyImport">Import dữ liệu KB</button>' +
                    ' <button type="button" class="cskh-btn cskh-btn--secondary cskh-btn--sm" id="cskhKbEmptyAdd">+ Thêm node kiến thức</button>'
                );
                var emptyBtn = $("cskhKbEmptyAdd");
                if (emptyBtn) emptyBtn.addEventListener("click", function () { showKbForm(null); });
                var emptyImport = $("cskhKbEmptyImport");
                if (emptyImport) emptyImport.addEventListener("click", openKbImportPanel);
                return;
            }
            host.innerHTML = '<div class="cskh-kb-tree">' + buildKbTreeHtml(state.kbNodes, null, 0) + "</div>";
            host.querySelectorAll("[data-kb-edit]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var id = btn.getAttribute("data-kb-edit");
                    var node = (state.kbNodes || []).find(function (n) { return String(n.id) === String(id); });
                    if (node) showKbForm(node);
                });
            });
            host.querySelectorAll("[data-kb-toggle]").forEach(function (btn) {
                btn.addEventListener("click", function () { toggleKbNode(btn.getAttribute("data-kb-toggle")); });
            });
            host.querySelectorAll("[data-kb-del]").forEach(function (btn) {
                btn.addEventListener("click", function () { deleteKbNode(btn.getAttribute("data-kb-del")); });
            });
        } catch (e) {
            if (window.SeoautoChatbotKb) window.SeoautoChatbotKb.setError($("cskhKbSyncBadge"));
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    async function saveKbNode() {
        var botId = selectedKbBotId();
        var KB = window.SeoautoChatbotKb;
        if (!botId) { showToast("Chọn chatbot trước."); return; }
        var editId = ($("cskhKbEditNodeId") || {}).value || "";
        var title = (($("cskhKbTitle") || {}).value || "").trim();
        if (!title) { showToast("Nhập tiêu đề node."); return; }
        var body = {
            title: title,
            content: (($("cskhKbContent") || {}).value || "").trim(),
            node_type: ($("cskhKbNodeType") || {}).value || "node",
            parent_id: parseInt(($("cskhKbParent") || {}).value || "0", 10) || null,
            tags: collectKbTags(),
            priority: parseInt(($("cskhKbPriority") || {}).value || "0", 10) || 0,
            is_active: ($("cskhKbActive") || {}).checked !== false,
        };
        if (!body.parent_id) body.parent_id = null;
        if (KB) KB.setProcessing($("cskhKbSyncBadge"));
        try {
            if (editId) {
                await apiFetch("/kb/nodes/" + encodeURIComponent(editId), {
                    method: "PUT",
                    json: true,
                    body: {
                        title: body.title,
                        content: body.content,
                        node_type: body.node_type,
                        parent_id: body.parent_id,
                        clear_parent: !body.parent_id,
                        tags: body.tags,
                        priority: body.priority,
                        is_active: body.is_active,
                    },
                });
                showToast("Đã cập nhật node.");
            } else {
                await apiFetch("/kb/" + encodeURIComponent(botId) + "/nodes", {
                    method: "POST",
                    json: true,
                    body: body,
                });
                showToast("Đã thêm node kiến thức.");
            }
            if (KB) KB.notifyChange(botId);
            resetKbForm();
            loadKb();
        } catch (e) {
            if (KB) KB.setError($("cskhKbSyncBadge"));
            showToast(e.message);
        }
    }

    async function toggleKbNode(id) {
        var botId = selectedKbBotId();
        var KB = window.SeoautoChatbotKb;
        if (KB) KB.setProcessing($("cskhKbSyncBadge"));
        try {
            await apiFetch("/kb/nodes/" + encodeURIComponent(id) + "/toggle", { method: "POST" });
            if (KB && botId) KB.notifyChange(botId);
            showToast("Đã đổi trạng thái node.");
            loadKb();
        } catch (e) {
            if (KB) KB.setError($("cskhKbSyncBadge"));
            showToast(e.message);
        }
    }

    async function deleteKbNode(id) {
        if (!confirm("Xóa node kiến thức này?")) return;
        var botId = selectedKbBotId();
        var KB = window.SeoautoChatbotKb;
        if (KB) KB.setProcessing($("cskhKbSyncBadge"));
        try {
            await apiFetch("/kb/nodes/" + encodeURIComponent(id), { method: "DELETE" });
            if (KB && botId) KB.notifyChange(botId);
            showToast("Đã xóa node.");
            resetKbForm();
            loadKb();
        } catch (e) {
            if (KB) KB.setError($("cskhKbSyncBadge"));
            showToast(e.message);
        }
    }

    async function importKbFromSources() {
        openKbImportPanel();
    }

    var kbImportTab = "sources";
    var kbImportFileContent = "";
    var kbImportFileFormat = "plain";
    var kbImportFileBase64 = "";
    var kbImportFileName = "";
    var kbImportFileBusy = false;

    function setKbImportTab(tab) {
        kbImportTab = tab || "sources";
        document.querySelectorAll("#cskhKbImportCard .cskh-kb-import-tab").forEach(function (btn) {
            btn.classList.toggle("active", btn.getAttribute("data-kb-import-tab") === kbImportTab);
        });
        document.querySelectorAll("#cskhKbImportCard .cskh-kb-import-pane").forEach(function (pane) {
            var on = pane.getAttribute("data-kb-import-pane") === kbImportTab;
            pane.classList.toggle("active", on);
            pane.hidden = !on;
        });
    }

    function closeKbImportPanel() {
        var card = $("cskhKbImportCard");
        if (card) card.hidden = true;
        showKbImportErr("");
        showKbImportResult("");
        var btn = $("cskhBtnKbImportSubmit");
        if (btn) { btn.disabled = false; btn.textContent = "Import vào KB"; }
    }

    function showKbImportErr(msg) {
        var err = $("cskhKbImportErr");
        if (!err) return;
        err.hidden = !msg;
        err.textContent = msg || "";
    }

    function showKbImportResult(msg) {
        var el = $("cskhKbImportResult");
        if (!el) return;
        el.hidden = !msg;
        el.textContent = msg || "";
    }

    function selectedImportTags() {
        var tags = [];
        document.querySelectorAll("#cskhKbImportTags input[type=checkbox]:checked").forEach(function (cb) {
            if (cb.value) tags.push(cb.value);
        });
        return tags;
    }

    function selectedImportParentId() {
        var el = $("cskhKbImportParent");
        var v = el ? String(el.value || "").trim() : "";
        if (!v) return null;
        var n = parseInt(v, 10);
        return Number.isFinite(n) && n > 0 ? n : null;
    }

    function fillKbImportParentOptions() {
        var sel = $("cskhKbImportParent");
        if (!sel) return;
        var current = sel.value;
        var html = '<option value="">— Không có —</option>';
        (state.kbNodes || []).forEach(function (n) {
            var id = n.id || n.node_id;
            html += '<option value="' + esc(id) + '">' + esc(n.title || ("Node #" + id)) + "</option>";
        });
        sel.innerHTML = html;
        if (current) sel.value = current;
    }

    async function loadKbImportSources() {
        var host = $("cskhKbImportSourcesList");
        var botId = selectedKbBotId();
        if (!host) return;
        if (!botId) {
            host.innerHTML = '<p class="cskh-empty">Chọn chatbot trước.</p>';
            return;
        }
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        try {
            var res = await apiFetch("/kb/" + encodeURIComponent(botId) + "/import/sources");
            var d = res.data || {};
            var items = d.sources || [];
            if (!items.length) {
                host.innerHTML = '<p class="cskh-empty">Chưa có nguồn dữ liệu. Thêm FAQ hoặc quét website ở tab «Nguồn dữ liệu» trước.</p>';
                return;
            }
            var html = "";
            var available = 0;
            items.forEach(function (s) {
                var disabled = !s.has_content || s.already_imported;
                if (!disabled) available += 1;
                html += '<label class="cskh-kb-import-item' + (disabled ? " is-disabled" : "") + '">' +
                    '<input type="checkbox" class="cskh-kb-import-src" value="' + esc(s.source_id) + '"' +
                    (disabled ? " disabled" : " checked") + ">" +
                    "<div><strong>" + esc(s.title) + "</strong> " +
                    '<span class="cskh-tag">' + esc(sourceTypeLabel(s.source_type || "")) + "</span>";
                if (s.already_imported) html += ' <span class="cskh-muted">(đã import)</span>';
                if (!s.has_content) html += ' <span class="cskh-muted">(trống)</span>';
                if (s.content_preview) html += '<br><span class="cskh-muted">' + esc(s.content_preview) + "</span>";
                html += "</div></label>";
            });
            host.innerHTML = html;
            var selectAll = $("cskhKbImportAllSources");
            if (selectAll) {
                selectAll.checked = available > 0;
                selectAll.onchange = function () {
                    var on = selectAll.checked;
                    document.querySelectorAll(".cskh-kb-import-src:not(:disabled)").forEach(function (cb) {
                        cb.checked = on;
                    });
                };
            }
        } catch (e) {
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    function openKbImportPanel() {
        var botId = selectedKbBotId();
        if (!botId) { showToast("Chọn chatbot trước."); return; }
        var card = $("cskhKbImportCard");
        if (!card) return;
        var formCard = $("cskhKbFormCard");
        if (formCard) formCard.hidden = true;
        kbImportFileContent = "";
        kbImportFileBase64 = "";
        kbImportFileName = "";
        kbImportFileFormat = "plain";
        kbImportFileBusy = false;
        if ($("cskhKbImportPaste")) $("cskhKbImportPaste").value = "";
        if ($("cskhKbImportTitleInput")) $("cskhKbImportTitleInput").value = "";
        if ($("cskhKbImportFileName")) $("cskhKbImportFileName").textContent = "";
        if ($("cskhKbImportFile")) $("cskhKbImportFile").value = "";
        if ($("cskhKbImportBulk")) $("cskhKbImportBulk").checked = false;
        document.querySelectorAll("#cskhKbImportTags input[type=checkbox]").forEach(function (cb) {
            cb.checked = false;
        });
        showKbImportErr("");
        showKbImportResult("");
        setKbImportTab("sources");
        fillKbImportParentOptions();
        card.hidden = false;
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
        loadKbImportSources();
    }

    // Backward-compatible alias used by URL ?import=1
    function openKbImportModal() { openKbImportPanel(); }

    async function submitKbImport() {
        var botId = selectedKbBotId();
        var KB = window.SeoautoChatbotKb;
        var submitBtn = $("cskhBtnKbImportSubmit");
        if (!botId) { showToast("Chọn chatbot trước."); return; }
        if (kbImportFileBusy) {
            showKbImportErr("Đang đọc file, vui lòng đợi…");
            return;
        }
        if (KB) KB.setProcessing($("cskhKbSyncBadge"));
        showKbImportErr("");
        showKbImportResult("");
        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Đang import…"; }
        try {
            var d;
            var parentId = selectedImportParentId();
            var tags = selectedImportTags();
            if (kbImportTab === "sources") {
                var ids = [];
                document.querySelectorAll(".cskh-kb-import-src:checked").forEach(function (cb) {
                    ids.push(parseInt(cb.value, 10));
                });
                if (!ids.length) {
                    showKbImportErr("Chọn ít nhất một nguồn dữ liệu để import.");
                    return;
                }
                var res = await apiFetch("/kb/" + encodeURIComponent(botId) + "/import", {
                    method: "POST",
                    json: true,
                    body: { source_ids: ids, parent_id: parentId },
                });
                d = res.data || {};
            } else if (kbImportTab === "paste") {
                var content = ($("cskhKbImportPaste") || {}).value || "";
                var title = ($("cskhKbImportTitleInput") || {}).value || "";
                var bulk = ($("cskhKbImportBulk") || {}).checked;
                if (!String(content).trim()) {
                    showKbImportErr("Nhập nội dung cần import.");
                    return;
                }
                var res2 = await apiFetch("/kb/" + encodeURIComponent(botId) + "/import/text", {
                    method: "POST",
                    json: true,
                    body: {
                        title: title.trim(),
                        content: content.trim(),
                        format: bulk ? "bulk" : "plain",
                        tags: tags,
                        parent_id: parentId,
                    },
                });
                d = res2.data || {};
            } else if (kbImportFileFormat === "xlsx") {
                if (!kbImportFileBase64) {
                    showKbImportErr("Chọn file .xlsx trước.");
                    return;
                }
                var resX = await apiFetch("/kb/" + encodeURIComponent(botId) + "/import/xlsx", {
                    method: "POST",
                    json: true,
                    body: {
                        filename: kbImportFileName || "import.xlsx",
                        content_base64: kbImportFileBase64,
                        parent_id: parentId,
                        tags: tags,
                        on_duplicate: "update",
                    },
                });
                d = resX.data || {};
            } else {
                if (!kbImportFileContent || !String(kbImportFileContent).trim()) {
                    showKbImportErr("Chọn file .txt, .md, .csv hoặc .xlsx trước.");
                    return;
                }
                var res3 = await apiFetch("/kb/" + encodeURIComponent(botId) + "/import/text", {
                    method: "POST",
                    json: true,
                    body: {
                        title: (($("cskhKbImportTitleInput") || {}).value || "").trim(),
                        content: kbImportFileContent,
                        format: kbImportFileFormat,
                        tags: tags,
                        parent_id: parentId,
                        filename: kbImportFileName || "",
                        on_duplicate: "update",
                    },
                });
                d = res3.data || {};
            }
            if (KB) KB.notifyChange(botId);
            var imported = d.imported || 0;
            var updated = d.updated || 0;
            var skipped = d.skipped || 0;
            var parts = [];
            if (imported) parts.push("thêm " + imported + " node mới");
            if (updated) parts.push("cập nhật " + updated + " node");
            var msg = parts.length
                ? ("Đã import KB: " + parts.join(", "))
                : "Không import được node nào";
            if (skipped) msg += " (bỏ qua " + skipped + ")";
            if (imported + updated > 0) {
                showToast(msg + ".");
                showKbImportResult(msg + ".");
                closeKbImportPanel();
                loadKb();
                loadOverview();
            } else {
                showKbImportErr(msg + (d.detail ? (": " + d.detail) : "."));
                loadKbImportSources();
                loadKb();
            }
        } catch (e) {
            if (KB) KB.setError($("cskhKbSyncBadge"));
            showKbImportErr(e.message);
        } finally {
            if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Import vào KB"; }
        }
    }

    function handleKbImportFile(file) {
        if (!file) return;
        var name = file.name || "";
        var ext = (name.split(".").pop() || "").toLowerCase();
        var el = $("cskhKbImportFileName");
        showKbImportErr("");
        showKbImportResult("");
        kbImportFileContent = "";
        kbImportFileBase64 = "";
        kbImportFileName = name;
        if (ext === "xlsx") {
            kbImportFileFormat = "xlsx";
            kbImportFileBusy = true;
            if (el) el.textContent = "Đang đọc " + name + "…";
            var reader = new FileReader();
            reader.onload = function () {
                try {
                    var bytes = new Uint8Array(reader.result);
                    var binary = "";
                    var chunk = 0x8000;
                    for (var i = 0; i < bytes.length; i += chunk) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                    }
                    kbImportFileBase64 = btoa(binary);
                    kbImportFileBusy = false;
                    if (el) el.textContent = name + " (" + Math.round(bytes.length / 1024) + " KB) — sẵn sàng import";
                } catch (e) {
                    kbImportFileBusy = false;
                    kbImportFileBase64 = "";
                    showKbImportErr("Không đọc được file Excel.");
                    if (el) el.textContent = "";
                }
            };
            reader.onerror = function () {
                kbImportFileBusy = false;
                showKbImportErr("Không đọc được file Excel.");
            };
            reader.readAsArrayBuffer(file);
            return;
        }
        if (ext === "csv") kbImportFileFormat = "csv";
        else if (ext === "md" || ext === "markdown") kbImportFileFormat = "markdown";
        else kbImportFileFormat = "auto";
        kbImportFileBusy = true;
        if (el) el.textContent = "Đang đọc " + name + "…";
        var textReader = new FileReader();
        textReader.onload = function () {
            kbImportFileContent = String(textReader.result || "");
            kbImportFileBusy = false;
            if (el) el.textContent = name + " (" + kbImportFileContent.length + " ký tự) — sẵn sàng import";
        };
        textReader.onerror = function () {
            kbImportFileBusy = false;
            showKbImportErr("Không đọc được file.");
        };
        textReader.readAsText(file);
    }

    function renderKbPreview() {
        var host = $("cskhKbPreviewBody");
        if (!host) return;
        var html = "";
        (state.kbPreviewMessages || []).forEach(function (m) {
            html += '<div class="cskh-kb-preview-msg cskh-kb-preview-msg--' + esc(m.role) + '">' + esc(m.text) + "</div>";
        });
        host.innerHTML = html || '<p class="cskh-empty">Nhập câu hỏi để xem bot trả lời theo KB.</p>';
        host.scrollTop = host.scrollHeight;
    }

    function openKbPreview() {
        var botId = selectedKbBotId();
        if (!botId) { showToast("Chọn chatbot trước."); return; }
        state.kbPreviewMessages = [];
        var modal = $("cskhKbPreviewModal");
        if (modal) modal.hidden = false;
        renderKbPreview();
    }

    function closeKbPreview() {
        var modal = $("cskhKbPreviewModal");
        if (modal) modal.hidden = true;
    }

    async function sendKbPreview() {
        var botId = selectedKbBotId();
        var input = $("cskhKbPreviewInput");
        var text = input ? String(input.value || "").trim() : "";
        if (!botId || !text) return;
        if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
            var ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.chatbotReply);
            if (!ok) return;
        }
        state.kbPreviewMessages.push({ role: "user", text: text });
        if (input) input.value = "";
        renderKbPreview();
        try {
            var res = await apiFetch("/kb/" + encodeURIComponent(botId) + "/preview", {
                method: "POST",
                json: true,
                body: { message: text },
            });
            var d = res.data || {};
            state.kbPreviewMessages.push({ role: "bot", text: d.reply || "—" });
            renderKbPreview();
        } catch (e) {
            state.kbPreviewMessages.push({ role: "bot", text: e.message });
            renderKbPreview();
        }
    }

    async function loadBotsForSources() {
        var sel = $("cskhSourceBot");
        if (!sel) return;
        try {
            var res = await apiFetch("/bots");
            var items = res.data || [];
            state.bots = items;
            var cur = sel.value;
            sel.innerHTML = '<option value="">— Chọn chatbot —</option>';
            items.forEach(function (b) {
                var id = b.bot_id || b.id;
                var opt = document.createElement("option");
                opt.value = String(id);
                opt.textContent = (b.bot_name || b.name || "Bot") + " (#" + id + ")";
                sel.appendChild(opt);
            });
            if (cur) sel.value = cur;
            if (!sel.value && items.length === 1) {
                sel.value = String(items[0].bot_id || items[0].id);
            }
            loadSources();
        } catch (e) {
            showToast(e.message);
        }
    }

    function setSourceMode(mode) {
        state.sourceMode = mode;
        document.querySelectorAll(".cskh-source-mode").forEach(function (btn) {
            var on = btn.getAttribute("data-source-mode") === mode;
            btn.classList.toggle("active", on);
        });
        document.querySelectorAll(".cskh-source-form").forEach(function (form) {
            var on = form.getAttribute("data-source-form") === mode;
            form.hidden = !on;
        });
    }

    function hideSourceEdit() {
        var card = $("cskhSourceEditCard");
        if (card) card.hidden = true;
        if ($("cskhEditSourceId")) $("cskhEditSourceId").value = "";
    }

    async function loadSources() {
        var host = $("cskhSourcesList");
        if (!host) return;
        var botId = selectedBotId();
        if (!botId) {
            host.innerHTML = '<p class="cskh-empty">Chọn chatbot để xem nguồn dữ liệu.</p>';
            return;
        }
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        try {
            var res = await apiFetch("/knowledge/" + encodeURIComponent(botId));
            var items = res.data || [];
            state.scanning = items.some(function (s) {
                return String(s.status || "").toLowerCase() === "pending";
            });
            renderStateBanner();
            if (!items.length) {
                host.innerHTML = emptyState(
                    "Chưa có nguồn dữ liệu",
                    "Thêm FAQ, nội dung doanh nghiệp hoặc quét website để bot có dữ liệu trả lời.",
                    '<button type="button" class="cskh-btn cskh-btn--primary cskh-btn--sm" data-cskh-goto="sources">Quét dữ liệu</button>'
                );
                host.querySelectorAll("[data-cskh-goto]").forEach(function (btn) {
                    btn.addEventListener("click", function () { setTab(btn.getAttribute("data-cskh-goto")); });
                });
                return;
            }
            var html = '<div class="cskh-table-wrap"><table class="cskh-table"><thead><tr>' +
                "<th>Tiêu đề</th><th>Loại</th><th>Trạng thái</th><th>Cập nhật</th><th></th></tr></thead><tbody>";
            items.forEach(function (s) {
                var sid = s.source_id || s.id;
                var st = String(s.status || "pending").toLowerCase();
                html += "<tr><td><strong>" + esc(s.title) + "</strong>";
                if (s.url) html += '<br><span class="cskh-muted">' + esc(s.url) + "</span>";
                if (st === "failed" && s.error_message) {
                    html += '<br><span class="cskh-muted">' + esc(s.error_message) + "</span>";
                }
                html += "</td><td>" + esc(sourceTypeLabel(s.source_type || s.type)) + "</td><td>" + statusTag(st) +
                    "</td><td>" + esc(formatDate(s.updated_at || s.created_at)) + "</td><td>";
                if ((s.source_type || s.type) !== "website") {
                    html += '<button type="button" class="cskh-btn cskh-btn--ghost" data-src-edit="' + esc(sid) + '">Sửa</button> ';
                }
                if ((s.source_type || s.type) === "website") {
                    html += '<button type="button" class="cskh-btn cskh-btn--ghost" data-src-recrawl="' + esc(sid) + '" data-src-url="' + esc(s.url || "") + '">Quét lại</button> ';
                }
                html += '<button type="button" class="cskh-btn cskh-btn--danger" data-src-del="' + esc(sid) + '">Xóa</button></td></tr>';
            });
            html += "</tbody></table></div>";
            host.innerHTML = html;
            host.querySelectorAll("[data-src-del]").forEach(function (btn) {
                btn.addEventListener("click", function () { deleteSource(btn.getAttribute("data-src-del")); });
            });
            host.querySelectorAll("[data-src-edit]").forEach(function (btn) {
                btn.addEventListener("click", function () { openSourceEdit(btn.getAttribute("data-src-edit")); });
            });
            host.querySelectorAll("[data-src-recrawl]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    recrawlSource(btn.getAttribute("data-src-recrawl"), btn.getAttribute("data-src-url"));
                });
            });
        } catch (e) {
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    async function openSourceEdit(id) {
        var botId = selectedBotId();
        if (!botId) return;
        try {
            var res = await apiFetch("/knowledge/" + encodeURIComponent(botId));
            var items = res.data || [];
            var row = items.find(function (s) { return String(s.source_id || s.id) === String(id); });
            if (!row) { showToast("Không tìm thấy nguồn."); return; }
            if ($("cskhEditSourceId")) $("cskhEditSourceId").value = String(id);
            if ($("cskhEditTitle")) $("cskhEditTitle").value = row.title || "";
            if ($("cskhEditContent")) $("cskhEditContent").value = row.content || row.content_preview || "";
            var card = $("cskhSourceEditCard");
            if (card) { card.hidden = false; card.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
        } catch (e) { showToast(e.message); }
    }

    async function saveSourceEdit() {
        var id = ($("cskhEditSourceId") || {}).value || "";
        if (!id) return;
        var title = ($("cskhEditTitle") || {}).value || "";
        var content = ($("cskhEditContent") || {}).value || "";
        try {
            await apiFetch("/knowledge/" + encodeURIComponent(id), {
                method: "PUT",
                json: true,
                body: { title: title.trim(), content: content.trim() },
            });
            showToast("Đã cập nhật nguồn dữ liệu.");
            hideSourceEdit();
            loadSources();
        } catch (e) { showToast(e.message); }
    }

    async function addKnowledge(sourceType, title, content) {
        var botId = selectedBotId();
        if (!botId) { showToast("Chọn chatbot trước."); return; }
        if (!title.trim()) { showToast("Nhập tiêu đề."); return; }
        if (!content.trim() || content.trim().length < 10) { showToast("Nội dung tối thiểu 10 ký tự."); return; }
        try {
            await apiFetch("/knowledge/add", {
                method: "POST",
                json: true,
                body: { bot_id: botId, source_type: sourceType, title: title.trim(), content: content.trim() },
            });
            showToast("Đã thêm nguồn dữ liệu.");
            if (sourceType === "faq") {
                if ($("cskhFaqTitle")) $("cskhFaqTitle").value = "";
                if ($("cskhFaqContent")) $("cskhFaqContent").value = "";
            } else if (sourceType === "business") {
                if ($("cskhBizTitle")) $("cskhBizTitle").value = "";
                if ($("cskhBizContent")) $("cskhBizContent").value = "";
            }
            loadSources();
            loadOverview();
        } catch (e) { showToast(e.message); }
    }

    async function crawlWebsite(sourceId, urlOverride) {
        var botId = selectedBotId();
        if (!botId) { showToast("Chọn chatbot trước."); return; }
        var url = String(urlOverride || ($("cskhCrawlUrl") || {}).value || "").trim();
        if (!url && !sourceId) { showToast("Nhập URL website."); return; }
        var title = (($("cskhCrawlTitle") || {}).value || "").trim();
        var body = { bot_id: botId, url: url, title: title };
        if (sourceId) body.source_id = parseInt(sourceId, 10);
        try {
            showToast(sourceId ? "Đang quét lại…" : "Đang quét website…");
            var res = await apiFetch("/knowledge/crawl", { method: "POST", json: true, body: body });
            var row = res.data || {};
            if (row.status === "failed") {
                showToast(row.error_message || "Quét thất bại.");
            } else {
                showToast("Đã quét và lưu nội dung.");
                if ($("cskhCrawlUrl")) $("cskhCrawlUrl").value = "";
                if ($("cskhCrawlTitle")) $("cskhCrawlTitle").value = "";
            }
            loadSources();
            loadOverview();
        } catch (e) { showToast(e.message); }
    }

    function recrawlSource(id, url) {
        crawlWebsite(id, url || "");
    }

    async function deleteSource(id) {
        if (!confirm("Xóa nguồn dữ liệu này?")) return;
        try {
            await apiFetch("/knowledge/" + encodeURIComponent(id), { method: "DELETE" });
            showToast("Đã xóa nguồn.");
            hideSourceEdit();
            loadSources();
            loadOverview();
        } catch (e) { showToast(e.message); }
    }

    async function loadChannels() {
        var webHost = $("cskhWebsiteChannelsList");
        var fbHost = $("cskhFacebookChannelsList");
        var fbCard = $("cskhFacebookChannelCard");
        var fbUpgrade = $("cskhFbUpgradeCard");
        var fbAllowed = state.access && state.access.facebook_beta_allowed;
        if (fbUpgrade) fbUpgrade.hidden = !!fbAllowed;
        if (fbCard) fbCard.hidden = !fbAllowed;
        if (webHost) webHost.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        if (fbHost && fbAllowed) fbHost.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        try {
            await loadBotsForFbSelect();
            var res = await apiFetch("/channels/overview");
            var d = res.data || {};
            var website = d.website || [];
            var facebook = d.facebook || [];
            state.connectionError = facebook.some(function (f) {
                return f.webhook_subscribed === false;
            });
            renderStateBanner();
            if (webHost) {
                if (!website.length) {
                    webHost.innerHTML = '<p class="cskh-empty">Chưa có chatbot. Tạo và kích hoạt bot để nhúng widget.</p>';
                } else {
                    var wh = '<div class="cskh-table-wrap"><table class="cskh-table"><thead><tr><th>Bot</th><th>Trạng thái</th><th></th></tr></thead><tbody>';
                    website.forEach(function (w) {
                        wh += "<tr><td>" + esc(w.bot_name || w.label) + "</td><td>" + statusBadge(w.status) + '</td><td>' +
                            '<button type="button" class="cskh-btn cskh-btn--ghost cskh-btn--sm" data-cskh-goto="bots">Mã nhúng</button></td></tr>';
                    });
                    wh += "</tbody></table></div>";
                    webHost.innerHTML = wh;
                    webHost.querySelectorAll("[data-cskh-goto]").forEach(function (btn) {
                        btn.addEventListener("click", function () { setTab(btn.getAttribute("data-cskh-goto")); });
                    });
                }
            }
            if (fbHost && fbAllowed) {
                if (!facebook.length) {
                    fbHost.innerHTML = '<p class="cskh-empty">Chưa kết nối Fanpage. Chọn chatbot và bấm «Kết nối Fanpage».</p>';
                } else {
                    var fh = '<div class="cskh-table-wrap"><table class="cskh-table"><thead><tr><th>Fanpage</th><th>Bot</th><th>Webhook</th><th>AI</th><th></th></tr></thead><tbody>';
                    facebook.forEach(function (f) {
                        var rid = f.id;
                        var whSt = f.webhook_subscribed === false ? statusBadge("error") : statusBadge("active");
                        fh += "<tr><td><strong>" + esc(f.page_name || f.page_id) + "</strong></td><td>#" + esc(f.bot_id) + "</td><td>" + whSt + "</td><td>";
                        fh += '<label class="cskh-check"><input type="checkbox" class="cskh-fb-ai-toggle" data-fb-id="' + esc(rid) + '"' + (f.ai_enabled ? " checked" : "") + "> Bật AI</label>";
                        fh += '</td><td><button type="button" class="cskh-btn cskh-btn--danger cskh-fb-disconnect" data-fb-id="' + esc(rid) + '">Ngắt</button></td></tr>';
                    });
                    fh += "</tbody></table></div>";
                    fbHost.innerHTML = fh;
                    fbHost.querySelectorAll(".cskh-fb-ai-toggle").forEach(function (cb) {
                        cb.addEventListener("change", function () {
                            toggleFacebookAi(cb.getAttribute("data-fb-id"), cb.checked);
                        });
                    });
                    fbHost.querySelectorAll(".cskh-fb-disconnect").forEach(function (btn) {
                        btn.addEventListener("click", function () {
                            disconnectFacebook(btn.getAttribute("data-fb-id"));
                        });
                    });
                }
            }
        } catch (e) {
            if (webHost) webHost.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
            if (fbHost) fbHost.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    async function loadBotsForFbSelect() {
        var sel = $("cskhFbBot");
        if (!sel) return;
        try {
            var res = await apiFetch("/bots");
            var bots = res.data || [];
            fillBotSelect(sel, bots, "— Chọn chatbot —");
        } catch (e) { /* ignore */ }
    }

    async function connectFacebook() {
        var botId = ($("cskhFbBot") || {}).value || "";
        if (!botId) { showToast("Chọn chatbot trước khi kết nối Fanpage."); return; }
        try {
            var res = await apiFetch("/facebook/oauth/start?bot_id=" + encodeURIComponent(botId));
            var url = res.url;
            if (!url) throw new Error("Không lấy được link OAuth.");
            window.location.href = url;
        } catch (e) {
            if (e.code === "facebook_plan_required") showUpgradeCta(e.message, e.upgrade_url);
            else showToast(e.message);
        }
    }

    async function toggleFacebookAi(id, enabled) {
        try {
            await apiFetch("/facebook/pages/" + encodeURIComponent(id), {
                method: "PATCH", json: true, body: { ai_enabled: !!enabled },
            });
            showToast(enabled ? "Đã bật AI trả lời Fanpage." : "Đã tắt AI — nhân viên xử lý thủ công.");
        } catch (e) { showToast(e.message); loadChannels(); }
    }

    async function disconnectFacebook(id) {
        if (!confirm("Ngắt kết nối Fanpage này?")) return;
        try {
            await apiFetch("/facebook/pages/" + encodeURIComponent(id), { method: "DELETE" });
            showToast("Đã ngắt kết nối Fanpage.");
            loadChannels();
        } catch (e) { showToast(e.message); }
    }

    async function createChannel() {
        var name = ($("cskhChannelName") || {}).value || "";
        var type = ($("cskhChannelType") || {}).value || "website_widget";
        if (!name.trim()) { showToast("Nhập tên kênh."); return; }
        try {
            await apiFetch("/channels", { method: "POST", body: { name: name.trim(), type: type }, json: true, legacy: true });
            showToast("Đã thêm kênh (chờ kết nối).");
            if ($("cskhChannelName")) $("cskhChannelName").value = "";
            loadChannels();
            loadOverview();
        } catch (e) { showToast(e.message); }
    }

    async function deleteChannel(id) {
        if (!confirm("Xóa kênh này?")) return;
        try {
            await apiFetch("/channels/" + encodeURIComponent(id), { method: "DELETE", legacy: true });
            showToast("Đã xóa kênh.");
            loadChannels();
        } catch (e) { showToast(e.message); }
    }

    function convStatusLabel(st) {
        var map = { open: "Chưa xử lý", needs_staff: "Cần tư vấn", handled: "Đã xử lý" };
        return map[String(st || "").toLowerCase()] || String(st || "—");
    }

    function leadStatusLabel(st) {
        var map = { new: "Mới", consulting: "Đang tư vấn", won: "Đã chốt", no_potential: "Không tiềm năng" };
        return map[String(st || "").toLowerCase()] || String(st || "—");
    }

    function fillBotSelect(sel, bots, placeholder) {
        if (!sel) return;
        var cur = sel.value;
        sel.innerHTML = '<option value="">' + esc(placeholder || "Tất cả bot") + "</option>";
        (bots || []).forEach(function (b) {
            var id = b.bot_id || b.id;
            var opt = document.createElement("option");
            opt.value = String(id);
            opt.textContent = (b.bot_name || b.name || "Bot") + " (#" + id + ")";
            sel.appendChild(opt);
        });
        if (cur) sel.value = cur;
    }

    async function loadBotsForInbox() {
        try {
            var res = await apiFetch("/bots");
            state.bots = res.data || [];
            fillBotSelect($("cskhConvBot"), state.bots, "Tất cả bot");
            fillBotSelect($("cskhLeadBot"), state.bots, "Tất cả bot");
            loadConversations();
            loadLeads();
        } catch (e) {
            showToast(e.message);
        }
    }

    function setConvFilter(filter) {
        state.convFilter = filter || "all";
        document.querySelectorAll(".cskh-conv-filter").forEach(function (btn) {
            btn.classList.toggle("active", btn.getAttribute("data-conv-filter") === state.convFilter);
        });
        loadConversations();
    }

    function channelTag(ch) {
        var c = (ch || "website").toLowerCase();
        if (c === "facebook") return '<span class="cskh-pill cskh-pill--fb">Facebook</span>';
        return '<span class="cskh-pill">Website</span>';
    }

    async function loadConversations() {
        var host = $("cskhConversationsList");
        if (!host) return;
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        var botId = ($("cskhConvBot") || {}).value || "";
        var q = "/conversations?filter=" + encodeURIComponent(state.convFilter || "all");
        if (botId) q += "&bot_id=" + encodeURIComponent(botId);
        try {
            var res = await apiFetch(q);
            var items = res.data || [];
            if (!items.length) {
                host.innerHTML = '<p class="cskh-empty">Chưa có hội thoại.</p>';
                return;
            }
            var html = "";
            items.forEach(function (c) {
                var id = c.conversation_id || c.id;
                var active = String(state.activeConversationId) === String(id) ? " active" : "";
                html += '<button type="button" class="cskh-conv-item' + active + '" data-conv-id="' + esc(id) + '">' +
                    '<div class="cskh-conv-item-title">' + channelTag(c.channel) + " " + esc(c.visitor_name || c.visitor || "Khách") +
                    (c.visitor_phone ? ' · <span class="cskh-muted">' + esc(c.visitor_phone) + "</span>" : "") + "</div>" +
                    '<div class="cskh-conv-item-meta">' + esc(c.preview || "—") + "</div>" +
                    '<div class="cskh-conv-item-meta">' + statusTag(c.status) + " · " + esc(formatDate(c.updated_at || c.created_at)) + "</div></button>";
            });
            host.innerHTML = html;
            host.querySelectorAll("[data-conv-id]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    openConversation(btn.getAttribute("data-conv-id"));
                });
            });
        } catch (e) {
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    async function openConversation(id) {
        state.activeConversationId = id;
        loadConversations();
        var host = $("cskhConversationDetail");
        if (!host) return;
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        try {
            var res = await apiFetch("/conversations/" + encodeURIComponent(id));
            var c = res.data || {};
            var html = '<div class="cskh-chat-head"><strong>' + esc(c.visitor_name || c.visitor || "Khách") + "</strong>";
            if (c.visitor_phone) html += ' · <span class="cskh-muted">' + esc(c.visitor_phone) + "</span>";
            html += '<div class="cskh-hint">' + channelTag(c.channel) + " · " + esc(c.bot_name || "") + " · " + statusTag(c.status);
            if (c.channel_ref) html += " · " + esc(c.channel_ref);
            html += "</div>";
            html += '<div style="margin-top:8px;"><button type="button" class="cskh-btn cskh-btn--ghost" data-conv-mark="handled">Đánh dấu đã xử lý</button> ';
            html += '<button type="button" class="cskh-btn cskh-btn--ghost" data-conv-mark="needs_staff">Cần tư vấn</button></div></div>';
            html += '<div class="cskh-chat-messages">';
            (c.messages || []).forEach(function (m) {
                var cls = m.role === "user" ? "cskh-chat-bubble--user" : "cskh-chat-bubble--assistant";
                html += '<div class="cskh-chat-bubble ' + cls + '">' + esc(m.message) +
                    "<time>" + esc(formatDate(m.created_at)) + "</time></div>";
            });
            html += "</div>";
            if ((c.leads || []).length) {
                var lead = c.leads[0];
                html += '<div class="cskh-lead-panel"><h3 class="cskh-card-title">Lead</h3>' +
                    "<p><strong>" + esc(lead.name || "—") + "</strong> · " + esc(lead.phone || "—") + "</p>" +
                    "<p class=\"cskh-muted\">" + esc(lead.need || "—") + "</p>" +
                    '<label class="cskh-label">Trạng thái lead</label>' +
                    '<select class="cskh-select" id="cskhLeadStatusSelect" data-lead-id="' + esc(lead.lead_id || lead.id) + '">' +
                    '<option value="new">Mới</option><option value="consulting">Đang tư vấn</option>' +
                    '<option value="won">Đã chốt</option><option value="no_potential">Không tiềm năng</option></select></div>';
            }
            host.innerHTML = html;
            var sel = $("cskhLeadStatusSelect");
            if (sel && c.leads && c.leads[0]) sel.value = c.leads[0].status || "new";
            host.querySelectorAll("[data-conv-mark]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    updateConversationStatus(id, btn.getAttribute("data-conv-mark"));
                });
            });
            if (sel) sel.addEventListener("change", function () {
                updateLeadStatus(sel.getAttribute("data-lead-id"), sel.value);
            });
        } catch (e) {
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    async function updateConversationStatus(id, status) {
        try {
            await apiFetch("/conversations/" + encodeURIComponent(id), {
                method: "PATCH", json: true, body: { status: status },
            });
            showToast("Đã cập nhật hội thoại.");
            openConversation(id);
            loadLeads();
        } catch (e) { showToast(e.message); }
    }

    async function loadLeads() {
        var host = $("cskhLeadsList");
        if (!host) return;
        host.innerHTML = '<p class="cskh-empty">Đang tải…</p>';
        var botId = ($("cskhLeadBot") || {}).value || "";
        var status = ($("cskhLeadStatus") || {}).value || "";
        var q = "/leads?";
        if (botId) q += "bot_id=" + encodeURIComponent(botId) + "&";
        if (status) q += "status=" + encodeURIComponent(status);
        try {
            var res = await apiFetch(q.replace(/\?$/, "").replace(/&$/, "") || "/leads");
            var items = res.data || [];
            if (!items.length) {
                host.innerHTML = '<p class="cskh-empty">Chưa có lead.</p>';
                return;
            }
            var html = '<div class="cskh-table-wrap"><table class="cskh-table"><thead><tr><th>Khách</th><th>SĐT</th><th>Nhu cầu</th><th>Trạng thái</th><th></th></tr></thead><tbody>';
            items.forEach(function (l) {
                var lid = l.lead_id || l.id;
                html += "<tr><td>" + esc(l.name || "—") + "</td><td>" + esc(l.phone || "—") + "</td><td>" + esc((l.need || "").slice(0, 80)) +
                    '</td><td><select class="cskh-select cskh-lead-status-select" data-lead-id="' + esc(lid) + '">' +
                    '<option value="new">Mới</option><option value="consulting">Đang tư vấn</option>' +
                    '<option value="won">Đã chốt</option><option value="no_potential">Không tiềm năng</option></select></td>' +
                    '<td><button type="button" class="cskh-btn cskh-btn--ghost" data-open-conv="' + esc(l.conversation_id || "") + '">Xem chat</button></td></tr>';
            });
            html += "</tbody></table></div>";
            host.innerHTML = html;
            host.querySelectorAll(".cskh-lead-status-select").forEach(function (sel) {
                var lid = sel.getAttribute("data-lead-id");
                var row = items.find(function (x) { return String(x.lead_id || x.id) === String(lid); });
                if (row) sel.value = row.status || "new";
                sel.addEventListener("change", function () {
                    updateLeadStatus(lid, sel.value);
                });
            });
            host.querySelectorAll("[data-open-conv]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var cid = btn.getAttribute("data-open-conv");
                    if (cid) openConversation(cid);
                });
            });
        } catch (e) {
            host.innerHTML = '<p class="cskh-empty">' + esc(e.message) + "</p>";
        }
    }

    async function updateLeadStatus(id, status) {
        try {
            await apiFetch("/leads/" + encodeURIComponent(id), {
                method: "PATCH", json: true, body: { status: status },
            });
            showToast("Đã cập nhật lead.");
            loadLeads();
            loadOverview();
            if (state.activeConversationId) openConversation(state.activeConversationId);
        } catch (e) { showToast(e.message); }
    }

    async function loadSettings() {
        try {
            var res = await apiFetch("/settings", { legacy: true });
            var s = res.data || {};
            if ($("cskhSettingModel")) $("cskhSettingModel").value = s.model || "";
            if ($("cskhSettingTemp")) $("cskhSettingTemp").value = s.temperature != null ? s.temperature : 0.4;
            if ($("cskhSettingPrompt")) $("cskhSettingPrompt").value = s.system_prompt || "";
            if ($("cskhSettingGreeting")) $("cskhSettingGreeting").value = s.greeting || "";
            if ($("cskhSettingFallback")) $("cskhSettingFallback").value = s.fallback_reply || "";
        } catch (e) { showToast(e.message); }
    }

    async function saveSettings() {
        try {
            await apiFetch("/settings", {
                method: "PUT",
                json: true,
                legacy: true,
                body: {
                    model: ($("cskhSettingModel") || {}).value || "",
                    temperature: parseFloat(($("cskhSettingTemp") || {}).value || "0.4"),
                    system_prompt: ($("cskhSettingPrompt") || {}).value || "",
                    greeting: ($("cskhSettingGreeting") || {}).value || "",
                    fallback_reply: ($("cskhSettingFallback") || {}).value || "",
                },
            });
            showToast("Đã lưu cài đặt AI.");
        } catch (e) { showToast(e.message); }
    }

    async function quickCopyEmbed() {
        try {
            var res = await apiFetch("/bots");
            var items = res.data || [];
            if (!items.length) {
                showToast("Chưa có chatbot — tạo bot trước.");
                setTab("bots");
                return;
            }
            var pick = items.find(function (b) { return String(b.status || "").toLowerCase() === "active"; }) || items[0];
            var id = pick.bot_id || pick.id;
            await showEmbedForBot(id);
            copyEmbedCode();
        } catch (e) {
            showToast(e.message);
        }
    }

    function bindUi() {
        document.querySelectorAll(".cskh-nav-item, .cskh-tab").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setTab(btn.getAttribute("data-cskh-tab"));
            });
        });
        var btnCreateBot = $("cskhBtnCreateBot");
        if (btnCreateBot) btnCreateBot.addEventListener("click", createBot);
        var btnCopyEmbed = $("cskhBtnCopyEmbed");
        if (btnCopyEmbed) btnCopyEmbed.addEventListener("click", copyEmbedCode);
        document.querySelectorAll(".cskh-source-mode").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setSourceMode(btn.getAttribute("data-source-mode"));
            });
        });
        var sourceBot = $("cskhSourceBot");
        if (sourceBot) sourceBot.addEventListener("change", loadSources);
        var btnAddFaq = $("cskhBtnAddFaq");
        if (btnAddFaq) btnAddFaq.addEventListener("click", function () {
            addKnowledge("faq", ($("cskhFaqTitle") || {}).value || "", ($("cskhFaqContent") || {}).value || "");
        });
        var btnAddBusiness = $("cskhBtnAddBusiness");
        if (btnAddBusiness) btnAddBusiness.addEventListener("click", function () {
            addKnowledge("business", ($("cskhBizTitle") || {}).value || "", ($("cskhBizContent") || {}).value || "");
        });
        var btnCrawl = $("cskhBtnCrawlWebsite");
        if (btnCrawl) btnCrawl.addEventListener("click", function () { crawlWebsite(null); });
        var btnSaveEdit = $("cskhBtnSaveSourceEdit");
        if (btnSaveEdit) btnSaveEdit.addEventListener("click", saveSourceEdit);
        var btnCancelEdit = $("cskhBtnCancelSourceEdit");
        if (btnCancelEdit) btnCancelEdit.addEventListener("click", hideSourceEdit);
        document.querySelectorAll(".cskh-conv-filter").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setConvFilter(btn.getAttribute("data-conv-filter"));
            });
        });
        var convBot = $("cskhConvBot");
        if (convBot) convBot.addEventListener("change", loadConversations);
        var leadBot = $("cskhLeadBot");
        if (leadBot) leadBot.addEventListener("change", loadLeads);
        var leadStatus = $("cskhLeadStatus");
        if (leadStatus) leadStatus.addEventListener("change", loadLeads);
        var btnConnectFb = $("cskhBtnConnectFacebook");
        if (btnConnectFb) btnConnectFb.addEventListener("click", connectFacebook);
        var btnSaveSettings = $("cskhBtnSaveSettings");
        if (btnSaveSettings) btnSaveSettings.addEventListener("click", saveSettings);
        var btnQuickEmbed = $("cskhBtnQuickEmbed");
        if (btnQuickEmbed) btnQuickEmbed.addEventListener("click", quickCopyEmbed);
        var btnQuickCreate = $("cskhBtnQuickCreate");
        if (btnQuickCreate) btnQuickCreate.addEventListener("click", function () { setTab("bots"); });
        var btnQuickCrawl = $("cskhBtnQuickCrawl");
        if (btnQuickCrawl) btnQuickCrawl.addEventListener("click", function () {
            setTab("sources");
            setSourceMode("website");
        });
        var btnQuickConv = $("cskhBtnQuickConv");
        if (btnQuickConv) btnQuickConv.addEventListener("click", function () { setTab("conversations"); });
        var kbBot = $("cskhKbBot");
        if (kbBot) kbBot.addEventListener("change", loadKb);
        var btnKbAdd = $("cskhBtnKbAddNode");
        if (btnKbAdd) btnKbAdd.addEventListener("click", function () { showKbForm(null); });
        var btnKbImport = $("cskhBtnKbImport");
        if (btnKbImport) btnKbImport.addEventListener("click", openKbImportPanel);
        document.querySelectorAll("#cskhKbImportCard .cskh-kb-import-tab").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setKbImportTab(btn.getAttribute("data-kb-import-tab"));
            });
        });
        var btnImportClose = $("cskhBtnKbImportClose");
        if (btnImportClose) btnImportClose.addEventListener("click", closeKbImportPanel);
        var btnImportCancel = $("cskhBtnKbImportCancel");
        if (btnImportCancel) btnImportCancel.addEventListener("click", closeKbImportPanel);
        var btnImportSubmit = $("cskhBtnKbImportSubmit");
        if (btnImportSubmit) btnImportSubmit.addEventListener("click", submitKbImport);
        var fileInput = $("cskhKbImportFile");
        var fileZone = $("cskhKbImportFileZone");
        if (fileInput) fileInput.addEventListener("change", function () {
            handleKbImportFile(fileInput.files && fileInput.files[0]);
        });
        if (fileZone && fileInput) {
            fileZone.addEventListener("click", function () { fileInput.click(); });
            fileZone.addEventListener("dragover", function (e) {
                e.preventDefault();
                fileZone.classList.add("is-dragover");
            });
            fileZone.addEventListener("dragleave", function () {
                fileZone.classList.remove("is-dragover");
            });
            fileZone.addEventListener("drop", function (e) {
                e.preventDefault();
                fileZone.classList.remove("is-dragover");
                var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
                if (f) {
                    try { fileInput.files = e.dataTransfer.files; } catch (_e) {}
                    handleKbImportFile(f);
                }
            });
        }
        var btnKbPreview = $("cskhBtnKbPreview");
        if (btnKbPreview) btnKbPreview.addEventListener("click", openKbPreview);
        var btnKbSave = $("cskhBtnKbSave");
        if (btnKbSave) btnKbSave.addEventListener("click", saveKbNode);
        var btnKbCancel = $("cskhBtnKbCancel");
        if (btnKbCancel) btnKbCancel.addEventListener("click", resetKbForm);
        var btnKbPreviewSend = $("cskhBtnKbPreviewSend");
        if (btnKbPreviewSend) btnKbPreviewSend.addEventListener("click", sendKbPreview);
        var kbPreviewInput = $("cskhKbPreviewInput");
        if (kbPreviewInput) {
            kbPreviewInput.addEventListener("keydown", function (e) {
                if (e.key === "Enter") { e.preventDefault(); sendKbPreview(); }
            });
        }
        document.querySelectorAll("[data-kb-preview-close]").forEach(function (el) {
            el.addEventListener("click", closeKbPreview);
        });
        if (window.SeoautoChatbotKb) {
            window.SeoautoChatbotKb.onChange(function (detail) {
                var bid = parseInt(detail.bot_id, 10) || 0;
                if (!bid || bid !== selectedKbBotId()) return;
                if (state.tab === "kb") loadKb();
            });
        }
        document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "visible" && state.tab === "kb" && selectedKbBotId()) {
                loadKb();
            }
        });
        var btnUpgrade = $("cskhBtnUpgrade");
        if (btnUpgrade) btnUpgrade.addEventListener("click", function () {
            window.location.href = "/pricing";
        });
        var btnLogin = $("cskhBtnLogin");
        if (btnLogin) btnLogin.addEventListener("click", function () {
            if (typeof window.DigiSeoOpenAuthModal === "function") {
                window.DigiSeoOpenAuthModal();
            } else {
                var b = document.getElementById("btnOpenLogin");
                if (b) b.click();
            }
        });
        document.querySelectorAll("[data-cskh-goto]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setTab(btn.getAttribute("data-cskh-goto"));
            });
        });
        window.addEventListener("digiseo-auth-change", function () {
            loadAccess();
        });
    }

    function initFromQuery() {
        try {
            var q = new URLSearchParams(window.location.search || "");
            var tab = q.get("tab");
            if (tab) setTab(tab);
            if (q.get("fb_connected") === "1") showToast("Đã kết nối Fanpage thành công.");
            if (q.get("import") === "1") state.pendingKbImport = true;
        } catch (_e) {}
    }

    function init() {
        bindUi();
        setTab("overview");
        loadAccess();
        initFromQuery();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
