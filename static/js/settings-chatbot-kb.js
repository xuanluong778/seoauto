/**
 * Settings — Chatbot KB panel (shared DB API with Chatbot CSKH tab).
 */
(function () {
    "use strict";

    var KB = window.SeoautoChatbotKb;
    if (!KB) return;

    var page = document.getElementById("chatbot-knowledge");
    if (!page) return;

    var state = { botId: 0, nodes: [], map: null, loading: false };

    function $(id) { return document.getElementById(id); }

    function token() {
        return typeof window.__settingsReadSeoToken === "function" ? window.__settingsReadSeoToken() : "";
    }

    function selectedBotId() {
        var el = $("stgKbBot");
        var v = el ? String(el.value || "").trim() : "";
        return v ? parseInt(v, 10) : 0;
    }

    function statusBadge(status) {
        var s = String(status || "draft").toLowerCase();
        var labels = { draft: "Draft", active: "Active", disabled: "Disabled" };
        return '<span class="ckb-badge ckb-badge--' + KB.esc(s) + '">' + KB.esc(labels[s] || s) + "</span>";
    }

    function buildTree(nodes, parentId, depth) {
        depth = depth || 0;
        var html = "";
        nodes.filter(function (n) {
            var pid = n.parent_id == null ? null : Number(n.parent_id);
            var want = parentId == null ? pid == null : pid === Number(parentId);
            return want;
        }).forEach(function (n) {
            var cls = "ckb-node" + (n.node_type === "group" ? " ckb-node--group" : "");
            if (!n.is_active) cls += " ckb-node--inactive";
            html += '<div class="' + cls + '" style="margin-left:' + (depth * 16) + 'px">';
            html += "<strong>" + KB.esc(n.title) + "</strong>";
            if (n.content && n.node_type !== "group") {
                var c = n.content.length > 200 ? n.content.slice(0, 200) + "…" : n.content;
                html += '<p class="ckb-node-preview">' + KB.esc(c) + "</p>";
            }
            html += '<div class="ckb-node-actions">';
            html += '<button type="button" class="aikb-btn-ghost ckb-btn-sm" data-stg-kb-edit="' + KB.esc(n.id) + '">Sửa</button>';
            html += '<button type="button" class="aikb-btn-ghost ckb-btn-sm" data-stg-kb-toggle="' + KB.esc(n.id) + '">' +
                (n.is_active ? "Tắt" : "Bật") + "</button>";
            html += '<button type="button" class="aikb-btn-ghost ckb-btn-sm" data-stg-kb-del="' + KB.esc(n.id) + '">Xóa</button>";
            html += "</div></div>";
            html += buildTree(nodes, n.id, depth + 1);
        });
        return html;
    }

    function refreshParentSelect(excludeId) {
        var sel = $("stgKbParent");
        if (!sel) return;
        sel.innerHTML = '<option value="">— Không có —</option>';
        (state.nodes || []).forEach(function (n) {
            if (n.node_type !== "group") return;
            if (excludeId && String(n.id) === String(excludeId)) return;
            var opt = document.createElement("option");
            opt.value = String(n.id);
            opt.textContent = n.title || ("Nhóm #" + n.id);
            sel.appendChild(opt);
        });
    }

    function collectTags() {
        var host = $("stgKbTags");
        if (!host) return [];
        var tags = [];
        host.querySelectorAll('input[type="checkbox"]:checked').forEach(function (cb) {
            if (cb.value) tags.push(cb.value);
        });
        return tags;
    }

    function resetForm() {
        if ($("stgKbEditId")) $("stgKbEditId").value = "";
        if ($("stgKbTitle")) $("stgKbTitle").value = "";
        if ($("stgKbContent")) $("stgKbContent").value = "";
        if ($("stgKbFormCard")) $("stgKbFormCard").hidden = true;
    }

    async function loadBots() {
        var sel = $("stgKbBot");
        if (!sel) return;
        try {
            var items = await KB.api.listBots(token());
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
            if (!sel.value && items.length === 1) sel.value = String(items[0].bot_id || items[0].id);
            loadKb();
        } catch (e) {
            KB.setError($("stgKbSyncBadge"));
        }
    }

    async function loadKb() {
        var host = $("stgKbNodesList");
        var syncEl = $("stgKbSyncBadge");
        var mapBadge = $("stgKbMapBadge");
        var botId = selectedBotId();
        state.botId = botId;
        if (!host) return;
        if (!botId) {
            host.innerHTML = "<p class=\"apik-help\">Chọn chatbot để quản lý sơ đồ tri thức.</p>";
            if (syncEl) syncEl.hidden = true;
            return;
        }
        if (state.loading) return;
        state.loading = true;
        KB.setProcessing(syncEl);
        host.innerHTML = "<p class=\"apik-help\">Đang tải…</p>";
        try {
            var d = await KB.api.get(token(), botId);
            state.nodes = d.nodes || [];
            state.map = d.map || null;
            refreshParentSelect();
            KB.renderSyncBadge(syncEl, KB.syncStatusFromData(d), d.synced_at);
            if (mapBadge) {
                mapBadge.innerHTML = state.map ? statusBadge(state.map.status) : statusBadge("draft");
            }
            if (!state.nodes.length) {
                host.innerHTML = "<div class=\"ckb-empty\"><strong>Chưa có sơ đồ tri thức</strong>" +
                    "<p>Hãy thêm dữ liệu để chatbot trả lời chính xác hơn.</p></div>";
                return;
            }
            host.innerHTML = '<div class="ckb-tree">' + buildTree(state.nodes, null, 0) + "</div>";
            bindTreeActions(host);
        } catch (e) {
            KB.setError(syncEl);
            host.innerHTML = "<p class=\"apik-help\">" + KB.esc(e.message) + "</p>";
        } finally {
            state.loading = false;
        }
    }

    function bindTreeActions(host) {
        host.querySelectorAll("[data-stg-kb-edit]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var id = btn.getAttribute("data-stg-kb-edit");
                var node = state.nodes.find(function (n) { return String(n.id) === String(id); });
                if (!node) return;
                if ($("stgKbEditId")) $("stgKbEditId").value = String(node.id);
                if ($("stgKbTitle")) $("stgKbTitle").value = node.title || "";
                if ($("stgKbContent")) $("stgKbContent").value = node.content || "";
                if ($("stgKbNodeType")) $("stgKbNodeType").value = node.node_type || "node";
                refreshParentSelect(node.id);
                if ($("stgKbParent")) $("stgKbParent").value = node.parent_id ? String(node.parent_id) : "";
                if ($("stgKbFormCard")) $("stgKbFormCard").hidden = false;
            });
        });
        host.querySelectorAll("[data-stg-kb-toggle]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                toggleNode(btn.getAttribute("data-stg-kb-toggle"));
            });
        });
        host.querySelectorAll("[data-stg-kb-del]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                deleteNode(btn.getAttribute("data-stg-kb-del"));
            });
        });
    }

    async function saveNode() {
        var botId = selectedBotId();
        if (!botId) return;
        var editId = ($("stgKbEditId") || {}).value || "";
        var title = (($("stgKbTitle") || {}).value || "").trim();
        if (!title) return;
        var body = {
            title: title,
            content: (($("stgKbContent") || {}).value || "").trim(),
            node_type: ($("stgKbNodeType") || {}).value || "node",
            parent_id: parseInt(($("stgKbParent") || {}).value || "0", 10) || null,
            tags: collectTags(),
            priority: 0,
            is_active: true,
        };
        if (!body.parent_id) body.parent_id = null;
        KB.setProcessing($("stgKbSyncBadge"));
        try {
            if (editId) {
                await KB.api.updateNode(token(), editId, {
                    title: body.title,
                    content: body.content,
                    node_type: body.node_type,
                    parent_id: body.parent_id,
                    clear_parent: !body.parent_id,
                    tags: body.tags,
                }, botId);
            } else {
                await KB.api.createNode(token(), botId, body);
            }
            resetForm();
            loadKb();
        } catch (e) {
            KB.setError($("stgKbSyncBadge"));
        }
    }

    async function toggleNode(id) {
        var botId = selectedBotId();
        KB.setProcessing($("stgKbSyncBadge"));
        try {
            await KB.api.toggleNode(token(), id, botId);
            loadKb();
        } catch (e) { KB.setError($("stgKbSyncBadge")); }
    }

    async function deleteNode(id) {
        if (!confirm("Xóa node kiến thức này?")) return;
        var botId = selectedBotId();
        KB.setProcessing($("stgKbSyncBadge"));
        try {
            await KB.api.deleteNode(token(), id, botId);
            resetForm();
            loadKb();
        } catch (e) { KB.setError($("stgKbSyncBadge")); }
    }

    async function importSources() {
        var botId = selectedBotId();
        if (!botId) return;
        KB.setProcessing($("stgKbSyncBadge"));
        try {
            await KB.api.import(token(), botId);
            loadKb();
        } catch (e) { KB.setError($("stgKbSyncBadge")); }
    }

    function bindUi() {
        var botSel = $("stgKbBot");
        if (botSel) botSel.addEventListener("change", loadKb);
        var btnAdd = $("stgKbBtnAdd");
        if (btnAdd) btnAdd.addEventListener("click", function () {
            resetForm();
            if ($("stgKbFormCard")) $("stgKbFormCard").hidden = false;
        });
        var btnSave = $("stgKbBtnSave");
        if (btnSave) btnSave.addEventListener("click", saveNode);
        var btnCancel = $("stgKbBtnCancel");
        if (btnCancel) btnCancel.addEventListener("click", resetForm);
        var btnImport = $("stgKbBtnImport");
        if (btnImport) btnImport.addEventListener("click", function () {
            window.location.href = "/chatbot-cskh?tab=kb&import=1";
        });
        var linkCskh = $("stgKbLinkCskh");
        if (linkCskh) linkCskh.addEventListener("click", function (e) {
            e.preventDefault();
            window.location.href = "/chatbot-cskh?tab=kb";
        });
    }

    function maybeLoad() {
        var h = (window.location.hash || "").split("?")[0];
        if (h === "#chatbot-knowledge") loadBots();
    }

    KB.onChange(function (detail) {
        var bid = parseInt(detail.bot_id, 10) || 0;
        if (!bid || bid !== selectedBotId()) return;
        loadKb();
    });

    document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "visible" && selectedBotId()) loadKb();
    });

    bindUi();
    window.addEventListener("hashchange", maybeLoad);
    maybeLoad();
})();
