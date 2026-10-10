/**
 * CAU Sửa SEO — AI SEO Assistant (patch UI). Auto Update only.
 * Depends on ContentAiShared + CauBlockEditor (optional until modal opens).
 */
(function (global) {
    "use strict";

    var HEADING_ACTIONS = [
        { id: "expand_1_2", label: "Viết thêm 1–2 câu" },
        { id: "expand_3_5", label: "Viết thêm 3–5 câu" },
        { id: "expand_100", label: "Mở rộng ~100 từ" },
        { id: "expand_200", label: "Mở rộng ~200 từ" },
        { id: "rewrite_heading", label: "Viết lại heading" },
        { id: "rewrite_heading_sync_section", label: "Viết lại heading + đồng bộ section" },
        { id: "add_example", label: "Thêm ví dụ" },
        { id: "add_steps", label: "Thêm các bước" },
        { id: "add_table", label: "Thêm bảng" },
        { id: "add_faq", label: "Thêm FAQ" },
        { id: "add_cta", label: "Thêm CTA" },
        { id: "add_internal_link", label: "Thêm internal link" },
    ];

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function plain(html) {
        var d = document.createElement("div");
        d.innerHTML = String(html || "");
        return (d.textContent || "").replace(/\s+/g, " ").trim();
    }

    function CauAssistantUI(opts) {
        this.apiFetch = opts.apiFetch;
        this.authJsonHeaders = opts.authJsonHeaders;
        this.getEditor = opts.getEditor || function () { return null; };
        this.getForm = opts.getForm || function () { return {}; };
        this.setHint = opts.setHint || function () {};
        this.onContentApplied = opts.onContentApplied || function () {};
        this.pending = [];
        this.applied = [];
        this.history = [];
        this._selRange = null;
        this._selBlockId = null;
        this._bound = false;
    }

    CauAssistantUI.prototype.init = function () {
        if (this._bound) return;
        this._bound = true;
        var self = this;
        this._renderHeadingActions();
        this._bindAsstTabs();
        this._bindRefreshModal();
        this._bindSelectionToolbar();
        this._bindChangesTab();
        document.querySelectorAll("[data-cau-content-action='refresh']").forEach(function (btn) {
            btn.addEventListener("click", function () { self.openRefreshModal(); });
        });
    };

    CauAssistantUI.prototype._bindAsstTabs = function () {
        document.querySelectorAll("[data-cau-asst-tab]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var key = btn.getAttribute("data-cau-asst-tab");
                document.querySelectorAll("[data-cau-asst-tab]").forEach(function (b) {
                    var on = b.getAttribute("data-cau-asst-tab") === key;
                    b.classList.toggle("active", on);
                    b.setAttribute("aria-selected", on ? "true" : "false");
                });
                document.querySelectorAll("[data-cau-asst-panel]").forEach(function (p) {
                    var on = p.getAttribute("data-cau-asst-panel") === key;
                    if (on) p.removeAttribute("hidden");
                    else p.setAttribute("hidden", "");
                });
            });
        });
    };

    CauAssistantUI.prototype._renderHeadingActions = function () {
        var grid = document.getElementById("cauHeadingActionsGrid");
        if (!grid) return;
        var self = this;
        grid.innerHTML = HEADING_ACTIONS.map(function (a) {
            return '<button type="button" class="mini-btn" data-cau-heading-act="' + a.id + '">' + esc(a.label) + "</button>";
        }).join("");
        grid.querySelectorAll("[data-cau-heading-act]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                self.requestPatch(btn.getAttribute("data-cau-heading-act"), {});
            });
        });
    };

    CauAssistantUI.prototype.onBlockSelected = function (block) {
        var wrap = document.getElementById("cauHeadingActions");
        if (!wrap) return;
        var isHeading = block && (block.block_type === "heading" || /<h[1-6]\b/i.test(block.current_content || ""));
        if (isHeading && block && !block.locked) wrap.removeAttribute("hidden");
        else wrap.setAttribute("hidden", "");
    };

    CauAssistantUI.prototype._payloadBase = function () {
        var form = this.getForm() || {};
        var ed = this.getEditor();
        var blocks = ed && typeof ed.getBlocksPayload === "function" ? ed.getBlocksPayload() : [];
        var html = ed && typeof ed.getHtml === "function" ? ed.getHtml() : (form.content_html || form.content || "");
        var scoreEl = document.getElementById("cauModalScore");
        var scoreRaw = scoreEl ? String(scoreEl.textContent || "").trim() : "";
        var seo = parseInt(scoreRaw, 10);
        return {
            content_html: html,
            blocks: blocks,
            primary_keyword: form.primary_keyword || form.keyword || "",
            seo_score: isNaN(seo) ? null : seo,
            post_id: form.post_id || null,
            post_url: form.post_url || "",
            session_id: form.session_id || "",
            use_llm: false,
        };
    };

    CauAssistantUI.prototype.requestPatch = function (action, extra) {
        var self = this;
        var ed = this.getEditor();
        var targetId = (extra && extra.target_block_id) || (ed && ed.selectedId) || null;
        if (!String(action || "").startsWith("selection_") && !targetId) {
            this.setHint("err", "Chọn một heading/block trước.");
            return Promise.resolve();
        }
        if (ed && targetId) {
            var idx = ed._blockIndex(targetId);
            if (idx >= 0 && ed.blocks[idx] && ed.blocks[idx].locked) {
                this.setHint("err", "Block đã khóa AI — không tạo patch.");
                return Promise.resolve();
            }
        }
        var body = Object.assign(this._payloadBase(), extra || {}, {
            action: action,
            target_block_id: targetId,
        });
        this.setHint("ok", "Đang tạo patch…");
        return this.apiFetch("/content-ai/auto-update/modal/assistant/patch", {
            method: "POST",
            headers: this.authJsonHeaders(),
            body: JSON.stringify(body),
        })
            .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw j; return j; }); })
            .then(function (data) {
                if (!data.patch) throw new Error("Không có patch");
                self.pending.unshift(data.patch);
                self.history.unshift({
                    at: Date.now(),
                    action: action,
                    patch_id: data.patch.patch_id,
                    credits: data.credits_charged || 0,
                    status: "pending",
                });
                self.renderPatchQueue();
                self.renderHistory();
                self.setHint("ok", data.message || "Đã tạo patch.");
            })
            .catch(function (e) {
                var msg = (e && (e.detail || e.message)) || "Tạo patch thất bại";
                if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
                self.setHint("err", String(msg));
            });
    };

    CauAssistantUI.prototype.renderPatchQueue = function () {
        var box = document.getElementById("cauPatchQueue");
        if (!box) return;
        var self = this;
        var list = this.pending.filter(function (p) { return p.status === "pending" || !p.applied; });
        if (!list.length) {
            box.innerHTML = "";
            return;
        }
        box.innerHTML = list.map(function (p) {
            return (
                '<article class="cau-patch-card" data-patch-id="' + esc(p.patch_id) + '">' +
                "<header><strong>" + esc(p.action) + "</strong> · " + esc(p.patch_id) + "</header>" +
                '<p class="cau-patch-card__reason">' + esc(p.reason) + "</p>" +
                '<div class="cau-patch-card__meta">' +
                "<span>Vị trí: " + esc(p.target_block_id || ("insert@" + p.insert_index)) + "</span>" +
                "<span>+" + (p.words_added || 0) + " / −" + (p.words_removed || 0) + " từ</span>" +
                "<span>SEO: " + (p.seo_score_before != null ? p.seo_score_before : "—") +
                " → " + (p.seo_score_after_est != null ? p.seo_score_after_est : "—") + "</span>" +
                "</div>" +
                '<div class="cau-patch-card__cols">' +
                "<div><label>Cũ</label><pre>" + esc(plain(p.old_html).slice(0, 400)) + "</pre></div>" +
                "<div><label>Mới</label><pre>" + esc(plain(p.new_html).slice(0, 400)) + "</pre></div>" +
                "</div>" +
                '<div class="cau-patch-card__actions">' +
                '<button type="button" class="mini-btn" data-cau-patch="apply">Áp dụng</button>' +
                '<button type="button" class="mini-btn" data-cau-patch="edit">Chỉnh sửa</button>' +
                '<button type="button" class="mini-btn" data-cau-patch="regen">Tạo lại</button>' +
                '<button type="button" class="mini-btn" data-cau-patch="skip">Bỏ qua</button>' +
                "</div></article>"
            );
        }).join("");
        box.querySelectorAll(".cau-patch-card").forEach(function (card) {
            var id = card.getAttribute("data-patch-id");
            card.querySelectorAll("[data-cau-patch]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var act = btn.getAttribute("data-cau-patch");
                    if (act === "apply") self.applyPatch(id);
                    else if (act === "skip") self.skipPatch(id);
                    else if (act === "regen") self.regenPatch(id);
                    else if (act === "edit") self.editPatch(id);
                });
            });
        });
    };

    CauAssistantUI.prototype._findPending = function (id) {
        for (var i = 0; i < this.pending.length; i++) {
            if (this.pending[i].patch_id === id) return { i: i, p: this.pending[i] };
        }
        return null;
    };

    CauAssistantUI.prototype.applyPatch = function (patchId) {
        var self = this;
        var found = this._findPending(patchId);
        if (!found) return Promise.resolve();
        var ed = this.getEditor();
        var body = {
            content_html: ed ? ed.getHtml() : "",
            blocks: ed && ed.getBlocksPayload ? ed.getBlocksPayload() : [],
            patch: found.p,
        };
        return this.apiFetch("/content-ai/auto-update/modal/assistant/apply", {
            method: "POST",
            headers: this.authJsonHeaders(),
            body: JSON.stringify(body),
        })
            .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw j; return j; }); })
            .then(function (data) {
                if (ed && data.blocks && typeof ed.loadBlocks === "function") {
                    ed.loadBlocks(data.blocks);
                } else if (ed && data.content_html) {
                    ed.loadHtml(data.content_html);
                }
                found.p = data.patch || found.p;
                found.p.applied = true;
                found.p.status = "applied";
                self.applied.push(found.p);
                self.pending.splice(found.i, 1);
                self.renderPatchQueue();
                self.renderChanges();
                self.renderHistory();
                self.onContentApplied(data.content_html || "");
                self.setHint("ok", "Đã áp dụng patch.");
            })
            .catch(function (e) {
                var msg = (e && (e.detail || e.message)) || "Áp dụng thất bại";
                if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
                self.setHint("err", String(msg));
            });
    };

    CauAssistantUI.prototype.skipPatch = function (patchId) {
        var found = this._findPending(patchId);
        if (!found) return;
        found.p.status = "skipped";
        this.pending.splice(found.i, 1);
        this.history.unshift({ at: Date.now(), action: found.p.action, patch_id: patchId, status: "skipped", credits: 0 });
        this.renderPatchQueue();
        this.renderHistory();
    };

    CauAssistantUI.prototype.regenPatch = function (patchId) {
        var found = this._findPending(patchId);
        if (!found) return Promise.resolve();
        var action = found.p.action;
        var target = found.p.target_block_id;
        var sel = (found.p.meta && found.p.meta.selection) ? found.p.old_html : "";
        this.pending.splice(found.i, 1);
        return this.requestPatch(action, {
            target_block_id: target,
            selection_html: sel,
        });
    };

    CauAssistantUI.prototype.editPatch = function (patchId) {
        var found = this._findPending(patchId);
        if (!found) return;
        var next = window.prompt("Chỉnh HTML mới của patch:", found.p.new_html || "");
        if (next == null) return;
        found.p.new_html = next;
        this.renderPatchQueue();
    };

    CauAssistantUI.prototype.renderChanges = function () {
        var box = document.getElementById("cauModalChangesList");
        var hint = document.getElementById("cauHint-changes");
        if (!box) return;
        var self = this;
        var list = this.applied.filter(function (p) { return p.status === "applied" || p.applied; });
        if (!list.length) {
            box.innerHTML = '<p class="cau-factor-empty">Chưa có patch đã áp dụng.</p>';
            if (hint) hint.textContent = "Danh sách patch đã áp dụng — hoàn tác từng cái hoặc tất cả.";
            return;
        }
        box.innerHTML = list.map(function (p) {
            return (
                '<article class="cau-change-item" data-patch-id="' + esc(p.patch_id) + '">' +
                "<strong>" + esc(p.action) + "</strong>" +
                '<div class="cau-change-item__diff"><span>Trước: ' + esc(plain(p.old_html).slice(0, 180)) +
                "</span><span>Sau: " + esc(plain(p.new_html).slice(0, 180)) + "</span></div>" +
                '<div class="cau-change-item__actions">' +
                '<button type="button" class="mini-btn" data-cau-change="view">Xem thay đổi</button>' +
                '<button type="button" class="mini-btn" data-cau-change="undo">Hoàn tác</button>' +
                "</div></article>"
            );
        }).join("");
        box.querySelectorAll(".cau-change-item").forEach(function (el) {
            var id = el.getAttribute("data-patch-id");
            el.querySelectorAll("[data-cau-change]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    var act = btn.getAttribute("data-cau-change");
                    if (act === "undo") self.undoOne(id);
                    else if (act === "view") self.viewChange(id);
                });
            });
        });
        if (hint) hint.textContent = list.length + " patch đã áp dụng.";
    };

    CauAssistantUI.prototype.viewChange = function (patchId) {
        var p = null;
        for (var i = 0; i < this.applied.length; i++) {
            if (this.applied[i].patch_id === patchId) { p = this.applied[i]; break; }
        }
        if (!p) return;
        window.alert(
            "Action: " + p.action + "\n\nTRƯỚC:\n" + plain(p.old_html).slice(0, 800) +
            "\n\nSAU:\n" + plain(p.new_html).slice(0, 800)
        );
    };

    CauAssistantUI.prototype.undoOne = function (patchId) {
        var self = this;
        var p = null;
        var idx = -1;
        for (var i = 0; i < this.applied.length; i++) {
            if (this.applied[i].patch_id === patchId) { p = this.applied[i]; idx = i; break; }
        }
        if (!p) return Promise.resolve();
        var ed = this.getEditor();
        return this.apiFetch("/content-ai/auto-update/modal/assistant/undo", {
            method: "POST",
            headers: this.authJsonHeaders(),
            body: JSON.stringify({
                content_html: ed ? ed.getHtml() : "",
                blocks: ed && ed.getBlocksPayload ? ed.getBlocksPayload() : [],
                patch: p,
                undo_all: false,
            }),
        })
            .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw j; return j; }); })
            .then(function (data) {
                if (ed && data.blocks && ed.loadBlocks) ed.loadBlocks(data.blocks);
                else if (ed && data.content_html) ed.loadHtml(data.content_html);
                self.applied.splice(idx, 1);
                self.renderChanges();
                self.onContentApplied(data.content_html || "");
                self.setHint("ok", "Đã hoàn tác patch.");
            })
            .catch(function (e) {
                var msg = (e && (e.detail || e.message)) || "Hoàn tác thất bại";
                if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
                self.setHint("err", String(msg));
            });
    };

    CauAssistantUI.prototype.undoAll = function () {
        var self = this;
        if (!this.applied.length) return Promise.resolve();
        var ed = this.getEditor();
        return this.apiFetch("/content-ai/auto-update/modal/assistant/undo", {
            method: "POST",
            headers: this.authJsonHeaders(),
            body: JSON.stringify({
                content_html: ed ? ed.getHtml() : "",
                blocks: ed && ed.getBlocksPayload ? ed.getBlocksPayload() : [],
                patches: this.applied.slice(),
                undo_all: true,
            }),
        })
            .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw j; return j; }); })
            .then(function (data) {
                if (ed && data.blocks && ed.loadBlocks) ed.loadBlocks(data.blocks);
                else if (ed && data.content_html) ed.loadHtml(data.content_html);
                self.applied = [];
                self.renderChanges();
                self.onContentApplied(data.content_html || "");
                self.setHint("ok", "Đã hoàn tác tất cả patch.");
            })
            .catch(function (e) {
                var msg = (e && (e.detail || e.message)) || "Hoàn tác tất cả thất bại";
                if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
                self.setHint("err", String(msg));
            });
    };

    CauAssistantUI.prototype._bindChangesTab = function () {
        var self = this;
        var btn = document.getElementById("btnCauUndoAllPatches");
        if (btn) btn.addEventListener("click", function () { self.undoAll(); });
    };

    CauAssistantUI.prototype.renderHistory = function () {
        var box = document.getElementById("cauAsstHistoryList");
        if (!box) return;
        if (!this.history.length) {
            box.innerHTML = '<p class="cau-fix-empty">Chưa có lịch sử AI trong phiên này.</p>';
            return;
        }
        box.innerHTML = this.history.slice(0, 40).map(function (h) {
            var t = new Date(h.at || Date.now()).toLocaleTimeString();
            return (
                '<div class="cau-asst-history__item" role="listitem">' +
                "<strong>" + esc(h.action) + "</strong> · " + esc(h.status || "") +
                " · credit " + (h.credits || 0) + " · " + esc(t) +
                "</div>"
            );
        }).join("");
    };

    CauAssistantUI.prototype.openRefreshModal = function () {
        var modal = document.getElementById("cauRefreshModal");
        if (!modal) return;
        modal.removeAttribute("hidden");
        var planBox = document.getElementById("cauRefreshPlanBox");
        if (planBox) planBox.setAttribute("hidden", "");
    };

    CauAssistantUI.prototype.closeRefreshModal = function () {
        var modal = document.getElementById("cauRefreshModal");
        if (modal) modal.setAttribute("hidden", "");
    };

    CauAssistantUI.prototype._selectedLevel = function () {
        var el = document.querySelector('input[name="cauRefreshLevel"]:checked');
        return el ? el.value : "standard";
    };

    CauAssistantUI.prototype.previewRefreshPlan = function () {
        var self = this;
        var body = Object.assign(this._payloadBase(), { level: this._selectedLevel() });
        return this.apiFetch("/content-ai/auto-update/modal/assistant/refresh-plan", {
            method: "POST",
            headers: this.authJsonHeaders(),
            body: JSON.stringify(body),
        })
            .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw j; return j; }); })
            .then(function (data) {
                self._showPlan(data.plan || {});
            })
            .catch(function (e) {
                var msg = (e && (e.detail || e.message)) || "Không lấy được kế hoạch";
                if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
                self.setHint("err", String(msg));
            });
    };

    CauAssistantUI.prototype._showPlan = function (plan) {
        var box = document.getElementById("cauRefreshPlanBox");
        var meta = document.getElementById("cauRefreshPlanMeta");
        var impact = document.getElementById("cauRefreshPlanImpact");
        var risk = document.getElementById("cauRefreshPlanRisk");
        if (!box || !meta) return;
        box.removeAttribute("hidden");
        meta.innerHTML =
            "<li>Mức: <strong>" + esc(plan.label || plan.level) + "</strong></li>" +
            "<li>Số section dự kiến sửa: <strong>" + esc(plan.sections_estimated) + "</strong></li>" +
            "<li>Số từ dự kiến thêm: <strong>" + esc(plan.words_estimated) + "</strong></li>" +
            "<li>Credit tối đa: <strong>" + esc(plan.credit_max) + "</strong></li>" +
            "<li>Block khóa bỏ qua: <strong>" + esc(plan.locked_skipped || 0) + "</strong></li>";
        impact.innerHTML = "<h6>Phần bị tác động</h6><ul>" +
            (plan.impacted || []).map(function (it) {
                return "<li><code>" + esc(it.block_id) + "</code> — " + esc(it.preview) + "</li>";
            }).join("") + "</ul>";
        if (risk) risk.textContent = "Cảnh báo rủi ro: " + (plan.risk_warning || "");
    };

    CauAssistantUI.prototype.runRefresh = function () {
        var self = this;
        var level = this._selectedLevel();
        var body = Object.assign(this._payloadBase(), { level: level, use_llm: false });
        this.setHint("ok", "Đang làm mới (patch)…");
        return this.apiFetch("/content-ai/auto-update/modal/assistant/refresh-run", {
            method: "POST",
            headers: this.authJsonHeaders(),
            body: JSON.stringify(body),
        })
            .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw j; return j; }); })
            .then(function (data) {
                (data.patches || []).forEach(function (p) {
                    self.pending.unshift(p);
                    self.history.unshift({
                        at: Date.now(),
                        action: "refresh:" + level + ":" + p.action,
                        patch_id: p.patch_id,
                        credits: p.credit_charged || 0,
                        status: "pending",
                    });
                });
                self.renderPatchQueue();
                self.renderHistory();
                self.closeRefreshModal();
                self.setHint("ok", data.message || "Đã tạo patch làm mới. Chọn Áp dụng từng patch.");
            })
            .catch(function (e) {
                var msg = (e && (e.detail || e.message)) || "Làm mới thất bại";
                if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
                self.setHint("err", String(msg));
            });
    };

    CauAssistantUI.prototype._bindRefreshModal = function () {
        var self = this;
        document.querySelectorAll("[data-cau-refresh-close]").forEach(function (el) {
            el.addEventListener("click", function () { self.closeRefreshModal(); });
        });
        var preview = document.getElementById("btnCauRefreshPreviewPlan");
        if (preview) preview.addEventListener("click", function () { self.previewRefreshPlan(); });
        var run = document.getElementById("btnCauRefreshRun");
        if (run) {
            run.addEventListener("click", function () {
                self.previewRefreshPlan().then(function () {
                    if (!window.confirm("Chạy làm mới theo kế hoạch đã xem? AI không ghi đè cả bài.")) return;
                    self.runRefresh();
                });
            });
        }
        document.querySelectorAll('input[name="cauRefreshLevel"]').forEach(function (inp) {
            inp.addEventListener("change", function () { self.previewRefreshPlan(); });
        });
    };

    CauAssistantUI.prototype._bindSelectionToolbar = function () {
        var self = this;
        var bar = document.getElementById("cauSelectionToolbar");
        if (!bar) return;
        document.addEventListener("selectionchange", function () {
            self._onSelectionChange();
        });
        bar.querySelectorAll("[data-cau-sel]").forEach(function (btn) {
            btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });
            btn.addEventListener("click", function () {
                var action = btn.getAttribute("data-cau-sel");
                var html = self._selRange;
                var blockId = self._selBlockId;
                if (!html || !blockId) {
                    self.setHint("err", "Bôi đen đoạn văn trong block trước.");
                    return;
                }
                self.hideSelectionToolbar();
                self.requestPatch(action, {
                    target_block_id: blockId,
                    selection_html: html,
                });
            });
        });
    };

    CauAssistantUI.prototype.hideSelectionToolbar = function () {
        var bar = document.getElementById("cauSelectionToolbar");
        if (bar) bar.setAttribute("hidden", "");
    };

    CauAssistantUI.prototype._onSelectionChange = function () {
        var bar = document.getElementById("cauSelectionToolbar");
        if (!bar) return;
        var sel = global.getSelection && global.getSelection();
        if (!sel || sel.isCollapsed || !sel.rangeCount) {
            bar.setAttribute("hidden", "");
            return;
        }
        var node = sel.anchorNode;
        var el = node && node.nodeType === 3 ? node.parentElement : node;
        if (!el || !el.closest) {
            bar.setAttribute("hidden", "");
            return;
        }
        var body = el.closest("[data-cau-be-edit]");
        var blockEl = el.closest("[data-block-id]");
        var mount = document.getElementById("cauBlockEditorMount");
        if (!body || !blockEl || !mount || !mount.contains(body)) {
            bar.setAttribute("hidden", "");
            return;
        }
        var range = sel.getRangeAt(0);
        var frag = range.cloneContents();
        var div = document.createElement("div");
        div.appendChild(frag);
        var html = div.innerHTML;
        if (!plain(html) || plain(html).length < 2) {
            bar.setAttribute("hidden", "");
            return;
        }
        this._selRange = html;
        this._selBlockId = blockEl.getAttribute("data-block-id");
        var rect = range.getBoundingClientRect();
        bar.style.position = "fixed";
        bar.style.left = Math.max(8, rect.left + rect.width / 2 - 160) + "px";
        bar.style.top = Math.max(8, rect.top - 42) + "px";
        bar.removeAttribute("hidden");
    };

    CauAssistantUI.prototype.resetSession = function () {
        this.pending = [];
        this.applied = [];
        this.history = [];
        this.renderPatchQueue();
        this.renderChanges();
        this.renderHistory();
        this.hideSelectionToolbar();
        var wrap = document.getElementById("cauHeadingActions");
        if (wrap) wrap.setAttribute("hidden", "");
    };

    global.CauAssistantUI = CauAssistantUI;
})(typeof window !== "undefined" ? window : globalThis);
