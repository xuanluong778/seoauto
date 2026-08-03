    /* SEO Score popup — 10 nhóm / 30 yếu tố */
    const SEO_SCORE_CIRC = 263.9;
    let _lastSeoScoreData = null;

    const _seoEsc = (s) => String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");

    const _seoStatusClass = (st) => {
        const s = String(st || "");
        if (s === "passed" || s === "ok") return "passed";
        if (s === "failed" || s === "fail") return "failed";
        return "warning";
    };

    const _seoLegacyStatus = (st) => {
        const s = String(st || "");
        if (s === "passed") return "ok";
        if (s === "failed") return "fail";
        if (s === "warning") return "warn";
        return s;
    };

    const _pclItemHtml = (it) => {
        const st = _seoLegacyStatus(it.status || it._legacy_status || "warn");
        const badgeMap = { ok: "Đạt", warn: "Cần tối ưu", fail: "Không đạt", manual: "Thủ công" };
        const badge = it.status_label || badgeMap[st] || st;
        const label = _seoEsc(it.label || "");
        const detail = _seoEsc(it.message || it.detail || "");
        const sug = _seoEsc(it.suggestion || "");
        return (
            `<span class="pcl-badge ${st}">${badge}</span>` +
            `<span class="pcl-body"><strong>${label}</strong>${detail ? " " + detail : ""}${sug ? `<span class="pcl-sug">${sug}</span>` : ""}</span>`
        );
    };

    const _computeSeoScoreFromItems = (items) => {
        if (!items || !items.length) return null;
        let pts = 0;
        let max = 0;
        items.forEach((it) => {
            if (it.max_score != null && it.score != null) {
                pts += Number(it.score) || 0;
                max += Number(it.max_score) || 0;
                return;
            }
            const w = String(it.status || "") === "manual" ? 0.5 : 1;
            max += w;
            const st = _seoLegacyStatus(it.status);
            if (st === "ok") pts += w;
            else if (st === "warn") pts += w * 0.5;
            else if (st === "manual") pts += w * 0.75;
        });
        if (!max) return 0;
        return Math.round((pts / max) * 100);
    };

    const _seoFactorPriority = (f) => {
        const st = _seoStatusClass(f.status);
        if (st === "failed") return 0;
        if (st === "warning") return 1;
        return 2;
    };

    const _renderSeoGroupCard = (g) => {
        const pct = g.max_score ? Math.round((g.score / g.max_score) * 100) : 0;
        const st = pct >= 85 ? "passed" : pct >= 50 ? "warning" : "failed";
        return (
            `<article class="ca-seo-group-card ca-seo-group-card--${st}">` +
            `<div class="ca-seo-group-card-head">` +
            `<strong>${_seoEsc(g.label)}</strong>` +
            `<span class="ca-seo-group-score">${g.score}/${g.max_score}</span>` +
            `</div>` +
            `<div class="ca-seo-group-bar"><span style="width:${Math.max(4, pct)}%"></span></div>` +
            `</article>`
        );
    };

    const _renderSeoFactorRow = (f, { compact = false, showFixBtn = false } = {}) => {
        const st = _seoStatusClass(f.status);
        const label = _seoEsc(f.status_label || (st === "passed" ? "Đạt" : st === "failed" ? "Không đạt" : "Cần tối ưu"));
        const msg = _seoEsc(f.message || "");
        const sug = _seoEsc(f.suggestion || "");
        const scoreTxt = f.max_score != null ? `${f.score}/${f.max_score}` : "";
        const fid = _seoEsc(f.id || "");
        const rawFid = String(f.id || "");
        const fixBlock = (showFixBtn && (st === "warning" || st === "failed") && fid)
            ? (
                `<div class="ca-seo-fix-one-wrap" data-factor-wrap="${fid}">` +
                `<button type="button" class="ca-seo-fix-one-btn" data-ca-autofix-id="${fid}">AI sửa lỗi này</button>` +
                `<div class="ca-seo-fix-one-progress" hidden data-factor-progress="${fid}" aria-live="polite">` +
                `<div class="ca-seo-autofix-loading-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">` +
                `<div class="ca-seo-autofix-loading-fill"></div></div>` +
                `<p class="ca-seo-fix-one-progress-text"></p>` +
                `</div></div>`
            )
            : "";
        return (
            `<div class="ca-seo-factor ca-seo-factor--${st}${compact ? " ca-seo-factor--compact" : ""}" data-factor-id="${fid}">` +
            `<div class="ca-seo-factor-head">` +
            `<span class="ca-seo-factor-badge">${label}</span>` +
            `<strong>${_seoEsc(f.label)}</strong>` +
            (scoreTxt ? `<span class="ca-seo-factor-pts">${scoreTxt}</span>` : "") +
            `</div>` +
            (msg ? `<p class="ca-seo-factor-msg">${msg}</p>` : "") +
            (sug && !compact ? `<p class="ca-seo-factor-sug">${sug}</p>` : "") +
            fixBlock +
            `</div>`
        );
    };

    const _switchSeoScoreTab = (tabKey) => {
        document.querySelectorAll(".ca-seo-tab").forEach((btn) => {
            const on = btn.getAttribute("data-seo-tab") === tabKey;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll(".ca-seo-tab-panel").forEach((p) => {
            p.hidden = p.getAttribute("data-seo-panel") !== tabKey;
        });
    };

    const _initSeoScoreTabs = () => {
        document.querySelectorAll(".ca-seo-tab").forEach((btn) => {
            if (btn.dataset.seoTabBound) return;
            btn.dataset.seoTabBound = "1";
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                _switchSeoScoreTab(btn.getAttribute("data-seo-tab") || "overview");
            });
        });
    };

    const _renderSeoScoreTabs = (data) => {
        const groups = Array.isArray(data.groups) ? data.groups : [];
        const overview = byId("caSeoTabOverview");
        const fixPanel = byId("caSeoTabFix");
        const detailPanel = byId("caSeoTabDetail");
        const fixBadge = byId("caSeoFixBadge");
        if (!overview || !fixPanel || !detailPanel) return;

        overview.innerHTML = groups.length
            ? `<div class="ca-seo-group-grid">${groups.map(_renderSeoGroupCard).join("")}</div>`
            : '<p class="ca-il-empty">Chưa có dữ liệu nhóm.</p>';

        const issues = [];
        groups.forEach((g) => {
            (g.factors || []).forEach((f) => {
                const st = _seoStatusClass(f.status);
                if (st === "warning" || st === "failed") {
                    issues.push({ ...f, groupLabel: g.label, priority: _seoFactorPriority(f) });
                }
            });
        });
        issues.sort((a, b) => a.priority - b.priority || (b.max_score - a.max_score));

        if (fixBadge) {
            if (issues.length) {
                fixBadge.hidden = false;
                fixBadge.textContent = String(issues.length);
            } else {
                fixBadge.hidden = true;
            }
        }

        fixPanel.innerHTML = issues.length
            ? issues.map((f) => (
                `<div class="ca-seo-fix-item">` +
                `<div class="ca-seo-fix-group">${_seoEsc(f.groupLabel)}</div>` +
                _renderSeoFactorRow(f, { compact: true, showFixBtn: true }) +
                `</div>`
            )).join("")
            : '<p class="ca-il-empty ca-seo-all-pass">Tất cả yếu tố đạt — không có mục cần sửa.</p>';

        detailPanel.innerHTML = groups.map((g) => (
            `<details class="ca-seo-accordion">` +
            `<summary><span>${_seoEsc(g.label)}</span><span class="ca-seo-accordion-score">${g.score}/${g.max_score}</span></summary>` +
            `<div class="ca-seo-accordion-body">${(g.factors || []).map((f) => _renderSeoFactorRow(f, { showFixBtn: true })).join("")}</div>` +
            `</details>`
        )).join("");

        const autofixBar = byId("caSeoAutofixBar");
        if (autofixBar) autofixBar.hidden = !issues.length;
        _updateAutofixUndoBtn();
    };

    const _renderSeoScorePanel = (data) => {
        const empty = byId("caSeoEmpty");
        const tabsWrap = byId("caSeoTabsWrap");
        const list = byId("contentAiSeoChecklist");
        const valEl = byId("caSeoScoreValue");
        const arc = byId("caSeoScoreArc");
        const gradeEl = byId("caSeoGradeLabel");
        const pre = byId("caPublishPrecheck");
        const publishWarn = byId("caSeoPublishWarn");
        const publishBtn = byId("btnSeoScrollPublish");

        const groups = data && Array.isArray(data.groups) ? data.groups : [];
        const items = data && Array.isArray(data.items) ? data.items : [];
        const hasData = groups.length > 0 || items.length > 0;

        if (!hasData) {
            if (list) { list.innerHTML = ""; list.hidden = true; }
            if (tabsWrap) tabsWrap.hidden = true;
            if (empty) empty.hidden = false;
            if (valEl) valEl.textContent = "—";
            if (gradeEl) gradeEl.textContent = "—";
            if (publishWarn) publishWarn.hidden = true;
            const triggerScore = byId("caSeoTriggerScore");
            const triggerRing = byId("caSeoTriggerRing");
            if (triggerScore) triggerScore.textContent = "—";
            if (triggerRing) triggerRing.classList.remove("warn", "danger");
            if (arc) arc.style.strokeDashoffset = String(SEO_SCORE_CIRC);
            if (pre) { pre.textContent = "Chưa kiểm tra checklist"; pre.className = "ca-publish-precheck"; }
            const autofixBar0 = byId("caSeoAutofixBar");
            if (autofixBar0) autofixBar0.hidden = true;
            return;
        }

        if (empty) empty.hidden = true;
        if (tabsWrap) tabsWrap.hidden = false;
        _initSeoScoreTabs();
        _switchSeoScoreTab("overview");

        const sc = data.score != null ? Number(data.score) : _computeSeoScoreFromItems(data.factors || items);
        const scoreText = sc != null && !Number.isNaN(sc) ? String(Math.round(sc)) : "—";
        const gradeLabel = data.grade_label || "—";

        if (valEl) valEl.textContent = scoreText;
        if (gradeEl) {
            gradeEl.textContent = gradeLabel;
            gradeEl.className = "ca-seo-grade-label";
            const tier = data.grade_tier || "";
            if (tier === "excellent" || tier === "good") gradeEl.classList.add("ok");
            else if (tier === "needs_work") gradeEl.classList.add("warn");
            else if (tier === "not_ready") gradeEl.classList.add("danger");
        }

        const triggerScore = byId("caSeoTriggerScore");
        const triggerRing = byId("caSeoTriggerRing");
        if (triggerScore) triggerScore.textContent = scoreText;
        if (triggerRing) {
            triggerRing.classList.remove("warn", "danger");
            if (sc != null && sc < 60) triggerRing.classList.add("danger");
            else if (sc != null && sc < 75) triggerRing.classList.add("warn");
        }
        if (arc) {
            const pct = sc != null ? Math.max(0, Math.min(100, sc)) : 0;
            arc.style.strokeDashoffset = String(SEO_SCORE_CIRC * (1 - pct / 100));
            arc.classList.remove("warn", "danger");
            if (pct > 0 && pct < 60) arc.classList.add("danger");
            else if (pct > 0 && pct < 75) arc.classList.add("warn");
        }

        if (pre) {
            if (sc >= 90) { pre.textContent = "Xuất sắc — sẵn sàng publish"; pre.className = "ca-publish-precheck ok"; }
            else if (sc >= 75) { pre.textContent = "Tốt — có thể publish"; pre.className = "ca-publish-precheck ok"; }
            else if (sc >= 60) { pre.textContent = "Cần tối ưu thêm"; pre.className = "ca-publish-precheck warn"; }
            else { pre.textContent = "Không nên publish"; pre.className = "ca-publish-precheck warn"; }
        }

        const lowScore = sc != null && sc < 75;
        if (publishWarn) publishWarn.hidden = !lowScore;
        if (publishBtn) {
            publishBtn.classList.toggle("ca-seo-publish-warn-btn", !!lowScore);
            publishBtn.title = lowScore ? "Điểm SEO dưới 75 — nên tối ưu trước khi publish" : "";
        }

        _renderSeoScoreTabs(data);

        if (list) {
            list.innerHTML = items.map((it) => `<li class="ca-seo-check-item">${_pclItemHtml(it)}</li>`).join("");
            list.hidden = true;
        }
    };

    const renderPublishChecklist = (data) => {
        _lastSeoScoreData = data || null;
        _renderSeoScorePanel(data);
        const items = data && Array.isArray(data.items) ? data.items : [];
        if (!publishChecklistPanel || !publishChecklistList) return;
        if (!items.length) {
            publishChecklistPanel.style.display = "none";
            return;
        }
        publishChecklistList.innerHTML = items.map((it) => `<li>${_pclItemHtml(it)}</li>`).join("");
        publishChecklistPanel.style.display = "block";
    };

    window.__caGetLastSeoScore = () => _lastSeoScoreData;

    /* --- AI Auto Fix (SEO Core 30) — preview diff, localStorage undo --- */
    const _AUTOFIX_UNDO_KEY = () => `ca_seo_autofix_undo_${getAuthUserId() || "guest"}`;
    let _pendingAutofixPatch = null;
    let _pendingAutofixDiffData = null;
    let _autofixBulkBusy = false;
    let _autofixBulkTimer = null;
    let _autofixBulkPct = 0;
    let _autofixSessionUndoSaved = false;
    const _autofixFactorJobs = new Set();
    const _autofixFactorTimers = new Map();
    const _autofixFactorPct = new Map();
    const _autofixSingleQueue = [];
    let _autofixSinglePumping = false;
    const _autofixBtnLabels = new WeakMap();

    const _findFactorLabel = (factorId) => {
        const fid = String(factorId || "");
        const groups = (_lastSeoScoreData && _lastSeoScoreData.groups) || [];
        for (let gi = 0; gi < groups.length; gi += 1) {
            const factors = groups[gi].factors || [];
            for (let fi = 0; fi < factors.length; fi += 1) {
                if (String(factors[fi].id) === fid) return String(factors[fi].label || "");
            }
        }
        const flat = (_lastSeoScoreData && _lastSeoScoreData.factors) || [];
        const hit = flat.find((f) => String(f.id) === fid);
        return hit ? String(hit.label || "") : "";
    };

    const _autofixModeLabel = (mode, factorIds) => {
        if (mode === "severe") return "Đang sửa các lỗi nghiêm trọng bằng AI…";
        if (mode === "optimize_90") return "Đang tối ưu SEO lên 90+ bằng AI…";
        if (factorIds && factorIds.length === 1) {
            const lbl = _findFactorLabel(factorIds[0]);
            if (lbl) return `Đang sửa «${lbl}» bằng AI…`;
        }
        return "Đang phân tích và sửa bằng AI…";
    };

    const _factorProgressEl = (factorId, triggerBtn) => {
        const fid = String(factorId || "");
        if (triggerBtn) {
            const wrap = triggerBtn.closest(".ca-seo-fix-one-wrap");
            if (wrap) return wrap.querySelector(`[data-factor-progress="${fid}"]`);
        }
        return document.querySelector(`[data-factor-progress="${fid.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`);
    };

    const _showFactorLoading = (factorId, triggerBtn, text) => {
        const fid = String(factorId || "");
        const prog = _factorProgressEl(fid, triggerBtn);
        if (!prog) return;
        const fill = prog.querySelector(".ca-seo-autofix-loading-fill");
        const track = prog.querySelector(".ca-seo-autofix-loading-track");
        const txt = prog.querySelector(".ca-seo-fix-one-progress-text");
        prog.hidden = false;
        prog.classList.remove("is-done", "is-error");
        if (txt) txt.textContent = text || "Đang sửa bằng AI…";
        _autofixFactorPct.set(fid, 5);
        if (fill) fill.style.width = "5%";
        if (track) track.setAttribute("aria-valuenow", "5");
        if (_autofixFactorTimers.has(fid)) clearInterval(_autofixFactorTimers.get(fid));
        const timer = setInterval(() => {
            const cur = Math.min(92, (_autofixFactorPct.get(fid) || 5) + (4 + Math.random() * 8));
            _autofixFactorPct.set(fid, cur);
            if (fill) fill.style.width = String(Math.round(cur)) + "%";
            if (track) track.setAttribute("aria-valuenow", String(Math.round(cur)));
        }, 360);
        _autofixFactorTimers.set(fid, timer);

        if (triggerBtn) {
            if (!_autofixBtnLabels.has(triggerBtn)) {
                _autofixBtnLabels.set(triggerBtn, triggerBtn.textContent || "");
            }
            triggerBtn.classList.add("is-loading");
            triggerBtn.textContent = "Đang sửa…";
            triggerBtn.disabled = true;
        }
    };

    const _hideFactorLoading = (factorId, triggerBtn, state) => {
        const fid = String(factorId || "");
        const prog = _factorProgressEl(fid, triggerBtn);
        if (_autofixFactorTimers.has(fid)) {
            clearInterval(_autofixFactorTimers.get(fid));
            _autofixFactorTimers.delete(fid);
        }
        _autofixFactorPct.delete(fid);
        if (prog) {
            const fill = prog.querySelector(".ca-seo-autofix-loading-fill");
            const track = prog.querySelector(".ca-seo-autofix-loading-track");
            const txt = prog.querySelector(".ca-seo-fix-one-progress-text");
            if (state === "done") {
                prog.hidden = false;
                prog.classList.add("is-done");
                if (fill) fill.style.width = "100%";
                if (track) track.setAttribute("aria-valuenow", "100");
                if (txt) txt.textContent = "Đã đạt ✓";
                if (triggerBtn) {
                    triggerBtn.classList.remove("is-loading");
                    const orig = _autofixBtnLabels.get(triggerBtn);
                    if (orig != null) triggerBtn.textContent = orig;
                    triggerBtn.disabled = false;
                }
                setTimeout(() => {
                    if (!prog.classList.contains("is-done")) return;
                    prog.hidden = true;
                    prog.classList.remove("is-done");
                    if (fill) fill.style.width = "0%";
                    if (track) track.setAttribute("aria-valuenow", "0");
                    if (txt) txt.textContent = "";
                }, 2800);
                return;
            } else if (state === "error") {
                prog.hidden = false;
                prog.classList.add("is-error");
                if (fill) fill.style.width = "0%";
                if (track) track.setAttribute("aria-valuenow", "0");
                if (txt) txt.textContent = "Không sửa được — thử lại";
                setTimeout(() => {
                    if (!prog.classList.contains("is-error")) return;
                    prog.hidden = true;
                    prog.classList.remove("is-error");
                    if (txt) txt.textContent = "";
                }, 3200);
            } else {
                prog.hidden = true;
                prog.classList.remove("is-done", "is-error");
                if (fill) fill.style.width = "0%";
                if (track) track.setAttribute("aria-valuenow", "0");
                if (txt) txt.textContent = "";
            }
        }
        if (triggerBtn) {
            triggerBtn.classList.remove("is-loading");
            const orig = _autofixBtnLabels.get(triggerBtn);
            if (orig != null) triggerBtn.textContent = orig;
            triggerBtn.disabled = false;
        }
    };

    const _showAutofixLoading = (mode, factorIds, triggerBtn) => {
        const busy = byId("caSeoAutofixBusy");
        const fill = byId("caSeoAutofixLoadingFill");
        const text = byId("caSeoAutofixLoadingText");
        const track = busy && busy.querySelector(".ca-seo-autofix-loading-track");
        const panel = byId("contentAiSeoPanel");
        if (busy) {
            busy.hidden = false;
            busy.setAttribute("aria-busy", "true");
        }
        if (panel) panel.classList.add("is-autofix-busy");
        if (text) text.textContent = _autofixModeLabel(mode, factorIds);
        _autofixBulkPct = 4;
        if (fill) fill.style.width = "4%";
        if (track) track.setAttribute("aria-valuenow", "4");
        if (_autofixBulkTimer) clearInterval(_autofixBulkTimer);
        _autofixBulkTimer = setInterval(() => {
            _autofixBulkPct = Math.min(92, _autofixBulkPct + (4 + Math.random() * 7));
            if (fill) fill.style.width = String(Math.round(_autofixBulkPct)) + "%";
            if (track) track.setAttribute("aria-valuenow", String(Math.round(_autofixBulkPct)));
        }, 380);

        if (triggerBtn && triggerBtn.classList) {
            if (!_autofixBtnLabels.has(triggerBtn)) {
                _autofixBtnLabels.set(triggerBtn, triggerBtn.textContent || "");
            }
            triggerBtn.classList.add("is-loading");
            triggerBtn.textContent = "Đang sửa…";
            triggerBtn.disabled = true;
        }
    };

    const _hideAutofixLoading = (triggerBtn, done) => {
        const busy = byId("caSeoAutofixBusy");
        const fill = byId("caSeoAutofixLoadingFill");
        const track = busy && busy.querySelector(".ca-seo-autofix-loading-track");
        const panel = byId("contentAiSeoPanel");
        if (_autofixBulkTimer) {
            clearInterval(_autofixBulkTimer);
            _autofixBulkTimer = null;
        }
        if (fill) fill.style.width = done ? "100%" : "0%";
        if (track) track.setAttribute("aria-valuenow", done ? "100" : "0");
        if (busy) {
            busy.hidden = true;
            busy.setAttribute("aria-busy", "false");
        }
        if (panel) panel.classList.remove("is-autofix-busy");

        if (triggerBtn && triggerBtn.classList) {
            triggerBtn.classList.remove("is-loading");
            const orig = _autofixBtnLabels.get(triggerBtn);
            if (orig != null) triggerBtn.textContent = orig;
        }
    };

    const _caToast = (message, type) => {
        if (typeof showCaToast === "function") showCaToast(message, type);
        else {
            const m = byId("msg");
            if (m) m.textContent = String(message || "");
        }
    };

    const _collectAutofixPayload = () => ({
        title: (byId("title") && byId("title").value || "").trim(),
        meta_description: (byId("meta") && byId("meta").value || "").trim(),
        content_html: String(getContentValue() || ""),
        primary_keyword: (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim(),
        slug: (byId("slug") && byId("slug").value || "").trim(),
        secondary_keywords: String((byId("secondaryKeywords") && byId("secondaryKeywords").value) || "")
            .split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean),
        target_website: (byId("targetWebsite") && byId("targetWebsite").value || "").trim(),
    });

    const _saveAutofixUndoSnapshot = () => {
        const snap = _collectAutofixPayload();
        snap.saved_at = Date.now();
        snap.score = (_lastSeoScoreData && _lastSeoScoreData.score) || null;
        try {
            localStorage.setItem(_AUTOFIX_UNDO_KEY(), JSON.stringify(snap));
            _updateAutofixUndoBtn();
        } catch (_) {}
    };

    const _hasAutofixUndo = () => {
        try { return !!localStorage.getItem(_AUTOFIX_UNDO_KEY()); } catch (_) { return false; }
    };

    const _updateAutofixUndoBtn = () => {
        const btn = byId("btnSeoAutofixUndo");
        if (btn) btn.disabled = !_hasAutofixUndo();
    };

    const _hideAutofixDiff = () => {
        _pendingAutofixPatch = null;
        const overlay = byId("caSeoAutofixOverlay");
        const dialog = byId("caSeoAutofixDiff");
        if (overlay) {
            overlay.hidden = true;
            overlay.setAttribute("aria-hidden", "true");
        }
        if (dialog) dialog.hidden = true;
        document.body.classList.remove("ca-seo-autofix-open");
    };

    const _renderDiffField = (field) => {
        if (!field || !field.changed) return "";
        const name = _seoEsc(field.field || "");
        const isContent = String(field.field || "").toLowerCase() === "content";
        const limit = isContent ? 6000 : 2000;
        const oldP = _seoEsc((field.old_preview || "").slice(0, limit));
        const newP = _seoEsc((field.new_preview || "").slice(0, limit));
        const lines = Array.isArray(field.diff_lines) ? field.diff_lines.slice(0, 80) : [];
        const diffHtml = lines.length && !isContent
            ? `<pre class="ca-seo-diff-lines">${lines.map(_seoEsc).join("\n")}</pre>`
            : "";
        const wcOld = field.old_word_count != null ? ` <span class="ca-seo-diff-wc">(${field.old_word_count} từ)</span>` : "";
        const wcNew = field.new_word_count != null ? ` <span class="ca-seo-diff-wc">(${field.new_word_count} từ)</span>` : "";
        return (
            `<div class="ca-seo-diff-field">` +
            `<div class="ca-seo-diff-field-name">${name}</div>` +
            `<div class="ca-seo-diff-cols">` +
            `<div class="ca-seo-diff-col"><span class="ca-seo-diff-label">Trước${wcOld}</span><pre>${oldP}</pre></div>` +
            `<div class="ca-seo-diff-col ca-seo-diff-col--new"><span class="ca-seo-diff-label">Sau${wcNew}</span><pre>${newP}</pre></div>` +
            `</div>${diffHtml}</div>`
        );
    };

    const _showAutofixDiff = (data) => {
        _pendingAutofixPatch = data && data.patch ? { ...data.patch } : null;
        const overlay = byId("caSeoAutofixOverlay");
        const dialog = byId("caSeoAutofixDiff");
        const titleEl = byId("caSeoAutofixDiffTitle");
        const deltaEl = byId("caSeoAutofixDelta");
        const sumEl = byId("caSeoAutofixSummary");
        const bodyEl = byId("caSeoAutofixDiffBody");
        const warnEl = byId("caSeoAutofixMarkupWarn");
        if (!overlay || !dialog || !_pendingAutofixPatch) return;

        const before = data.seo_before || {};
        const after = data.seo_after || {};
        const delta = Number(data.score_delta) || 0;
        if (titleEl) titleEl.textContent = "Xem trước thay đổi SEO";
        if (deltaEl) {
            deltaEl.textContent = `Điểm: ${before.score ?? "—"} → ${after.score ?? "—"} (Δ${delta >= 0 ? "+" : ""}${delta})`;
            deltaEl.className = "ca-seo-autofix-delta" + (delta > 0 ? " is-up" : delta < 0 ? " is-down" : "");
        }
        if (sumEl) sumEl.textContent = String(data.summary || "");

        const fields = (data.diff && data.diff.fields) || [];
        const changed = fields.filter((f) => f.changed);
        if (bodyEl) {
            bodyEl.innerHTML = changed.length
                ? changed.map(_renderDiffField).join("")
                : '<p class="ca-il-empty">Không có trường nào thay đổi.</p>';
            bodyEl.scrollTop = 0;
        }

        const mw = Array.isArray(data.markup_warnings) ? data.markup_warnings : [];
        if (warnEl) {
            if (mw.length) {
                warnEl.hidden = false;
                warnEl.textContent = "Cảnh báo markup: " + mw.slice(0, 3).join("; ");
            } else {
                warnEl.hidden = true;
                warnEl.textContent = "";
            }
        }

        overlay.hidden = false;
        overlay.setAttribute("aria-hidden", "false");
        dialog.hidden = false;
        document.body.classList.add("ca-seo-autofix-open");
    };

    const _applyPatchToForm = (patch, { withUndo } = {}) => {
        if (!patch) return;
        if (withUndo && !_autofixSessionUndoSaved) {
            _saveAutofixUndoSnapshot();
            _autofixSessionUndoSaved = true;
        }
        if (patch.title != null && byId("title")) byId("title").value = String(patch.title);
        if (patch.meta_description != null && byId("meta")) byId("meta").value = String(patch.meta_description);
        if (patch.slug != null && byId("slug")) byId("slug").value = String(patch.slug);
        if (patch.content_html != null) setContentValue(String(patch.content_html));
        try {
            const ed = typeof getEditorInstance === "function" ? getEditorInstance() : null;
            if (ed && ed.save) ed.save();
        } catch (_) {}
        if (typeof refreshPreview === "function") refreshPreview();
    };

    const _fetchAndRenderSeoScore = async () => {
        const payload = _collectAutofixPayload();
        if (!payload.content_html.trim() && !payload.title.trim()) return null;
        try {
            const secRaw = byId("secondaryKeywords") ? byId("secondaryKeywords").value : "";
            const secondary_keywords = String(secRaw || "")
                .split(/[,;\n]+/).map((s) => s.trim()).filter(Boolean);
            const res = await fetch(`/content-ai/publish-checklist?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    title: payload.title,
                    meta_description: payload.meta_description,
                    content_html: payload.content_html,
                    primary_keyword: payload.primary_keyword,
                    slug: payload.slug,
                    secondary_keywords,
                }),
            });
            const data = await res.json().catch(() => null);
            if (res.ok && data && typeof renderPublishChecklist === "function") {
                renderPublishChecklist(data);
                return data;
            }
        } catch (_) {}
        return null;
    };

    const _refreshChecklistNow = async () => {
        await _fetchAndRenderSeoScore();
    };

    const _toastAutofixOutcome = (data, label) => {
        const outcomes = Array.isArray(data && data.factor_outcomes) ? data.factor_outcomes : [];
        const row = outcomes.find((o) => String(o.id) === String((data.factor_ids || [])[0])) || outcomes[0];
        const delta = Number(data && data.score_delta) || 0;
        const after = row && String(row.status_after || "").toLowerCase();
        if (after === "passed" || after === "ok") {
            _caToast(`«${label}» đã đạt ✓ (Δ${delta >= 0 ? "+" : ""}${delta} điểm).`, "success");
            return;
        }
        const hint = (row && row.message_after) || "chưa đủ điều kiện đạt";
        _caToast(`«${label}»: ${hint}`, "error");
    };

    const _isSingleFactorRun = (mode, factorIds) => (
        (mode || "single") === "single" && Array.isArray(factorIds) && factorIds.length === 1
    );

    const _pumpAutofixSingleQueue = async () => {
        if (_autofixSinglePumping || _autofixBulkBusy) return;
        const job = _autofixSingleQueue.shift();
        if (!job) return;

        const { factorId, factorIds, triggerBtn, label } = job;
        _autofixSinglePumping = true;
        _showFactorLoading(factorId, triggerBtn, `Đang sửa «${label}» bằng AI…`);

        let loadOk = false;
        try {
            const payload = _collectAutofixPayload();
            const res = await fetch(`/content-ai/auto-fix?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    ...payload,
                    mode: "single",
                    factor_ids: factorIds || [],
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                const err = (data && data.error) || (data && data.detail) || "AI không thể sửa — giữ nguyên nội dung.";
                _caToast(`«${label}»: ${String(err)}`, "error");
                _hideFactorLoading(factorId, triggerBtn, "error");
                return;
            }
            loadOk = true;
            _applyPatchToForm(data.patch, { withUndo: true });
            await _refreshChecklistNow();
            _pendingAutofixPatch = data.patch ? { ...data.patch } : null;
            _pendingAutofixDiffData = data;
            _hideFactorLoading(factorId, triggerBtn, "done");
            _toastAutofixOutcome(data, label);
        } catch (e) {
            _caToast(`«${label}»: AI lỗi — giữ nguyên nội dung.`, "error");
            _hideFactorLoading(factorId, triggerBtn, "error");
        } finally {
            _autofixFactorJobs.delete(factorId);
            if (!loadOk) _hideFactorLoading(factorId, triggerBtn, null);
            _autofixSinglePumping = false;
            _updateAutofixUndoBtn();
            _pumpAutofixSingleQueue();
        }
    };

    const _runSeoAutofix = async ({ mode, factorIds, triggerBtn }) => {
        const isSingle = _isSingleFactorRun(mode, factorIds);
        const factorId = isSingle ? String(factorIds[0]) : "";

        if (isSingle) {
            if (_autofixFactorJobs.has(factorId) || _autofixBulkBusy) return;
            const payload = _collectAutofixPayload();
            if (!payload.content_html.trim() && !payload.title.trim()) {
                _caToast("Chưa có nội dung để sửa.", "error");
                return;
            }
            const label = _findFactorLabel(factorId) || "yếu tố";
            _autofixFactorJobs.add(factorId);
            const queuePos = _autofixSingleQueue.length + (_autofixSinglePumping ? 1 : 0);
            const waitTxt = queuePos > 0
                ? `Đang chờ… (${queuePos + 1} lỗi trong hàng đợi)`
                : `Đang sửa «${label}» bằng AI…`;
            _showFactorLoading(factorId, triggerBtn, waitTxt);
            _autofixSingleQueue.push({ factorId, factorIds, triggerBtn, label });
            _pumpAutofixSingleQueue();
            return;
        }

        if (_autofixBulkBusy || _autofixSingleQueue.length || _autofixSinglePumping) return;

        const payload = _collectAutofixPayload();
        if (!payload.content_html.trim() && !payload.title.trim()) {
            _caToast("Chưa có nội dung để sửa.", "error");
            return;
        }

        _autofixBulkBusy = true;
        _hideAutofixDiff();
        _showAutofixLoading(mode, factorIds, triggerBtn);
        document.querySelectorAll(".ca-seo-autofix-btn, .ca-seo-fix-one-btn").forEach((b) => { b.disabled = true; });

        let loadOk = false;
        try {
            const res = await fetch(`/content-ai/auto-fix?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    ...payload,
                    mode: mode || "single",
                    factor_ids: factorIds || [],
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.success) {
                const err = (data && data.error) || (data && data.detail) || "AI không thể sửa — giữ nguyên nội dung.";
                _caToast(String(err), "error");
                return;
            }
            loadOk = true;
            _hideAutofixLoading(triggerBtn, true);
            _showAutofixDiff(data);
            _caToast("Đã tạo bản xem trước — kiểm tra diff rồi Áp dụng.", "success");
        } catch (e) {
            _caToast("AI lỗi — giữ nguyên nội dung. " + String(e.message || e), "error");
        } finally {
            _autofixBulkBusy = false;
            if (!loadOk) _hideAutofixLoading(triggerBtn, false);
            document.querySelectorAll(".ca-seo-autofix-btn, .ca-seo-fix-one-btn").forEach((b) => {
                b.classList.remove("is-loading");
                const orig = _autofixBtnLabels.get(b);
                if (orig != null) b.textContent = orig;
                b.disabled = false;
            });
            _updateAutofixUndoBtn();
            _pumpAutofixSingleQueue();
        }
    };

    const _applyAutofixPatch = () => {
        if (!_pendingAutofixPatch) {
            _caToast("Không có thay đổi để áp dụng.", "error");
            return;
        }
        _applyPatchToForm(_pendingAutofixPatch, { withUndo: !_autofixSessionUndoSaved });
        _autofixSessionUndoSaved = true;
        _hideAutofixDiff();
        _caToast("Đã áp dụng thay đổi SEO.", "success");
    };

    const _undoAutofix = () => {
        let snap = null;
        try {
            const raw = localStorage.getItem(_AUTOFIX_UNDO_KEY());
            if (raw) snap = JSON.parse(raw);
        } catch (_) {}
        if (!snap) {
            _caToast("Không có bản hoàn tác.", "error");
            return;
        }
        if (snap.title != null && byId("title")) byId("title").value = String(snap.title);
        if (snap.meta_description != null && byId("meta")) byId("meta").value = String(snap.meta_description);
        if (snap.slug != null && byId("slug")) byId("slug").value = String(snap.slug);
        if (snap.content_html != null) setContentValue(String(snap.content_html));
        if (typeof refreshPreview === "function") refreshPreview();
        schedulePublishChecklist();
        try { localStorage.removeItem(_AUTOFIX_UNDO_KEY()); } catch (_) {}
        _autofixSessionUndoSaved = false;
        _hideAutofixDiff();
        _updateAutofixUndoBtn();
        _caToast("Đã hoàn tác về bản trước.", "success");
    };

    const _initSeoAutofixUi = () => {
        if (document.body.dataset.caAutofixBound) return;
        document.body.dataset.caAutofixBound = "1";

        const severe = byId("btnSeoAutofixSevere");
        const opt90 = byId("btnSeoAutofix90");
        const undo = byId("btnSeoAutofixUndo");
        const apply = byId("btnSeoAutofixApply");
        const cancel = byId("btnSeoAutofixCancel");
        const closeBtn = byId("btnSeoAutofixClose");
        const backdrop = byId("caSeoAutofixBackdrop");

        if (severe) severe.addEventListener("click", () => _runSeoAutofix({ mode: "severe", triggerBtn: severe }));
        if (opt90) opt90.addEventListener("click", () => _runSeoAutofix({ mode: "optimize_90", triggerBtn: opt90 }));
        if (undo) undo.addEventListener("click", () => _undoAutofix());
        if (apply) apply.addEventListener("click", () => _applyAutofixPatch());
        if (cancel) cancel.addEventListener("click", () => _hideAutofixDiff());
        if (closeBtn) closeBtn.addEventListener("click", () => _hideAutofixDiff());
        if (backdrop) backdrop.addEventListener("click", () => _hideAutofixDiff());

        document.addEventListener("keydown", (e) => {
            if (e.key !== "Escape") return;
            const overlay = byId("caSeoAutofixOverlay");
            if (overlay && !overlay.hidden) _hideAutofixDiff();
        });

        const panel = byId("contentAiSeoPanel");
        if (panel) {
            panel.addEventListener("click", (e) => {
                const btn = e.target && e.target.closest && e.target.closest(".ca-seo-fix-one-btn[data-ca-autofix-id]");
                if (!btn) return;
                const fid = btn.getAttribute("data-ca-autofix-id");
                if (!fid || _autofixFactorJobs.has(fid)) return;
                e.preventDefault();
                e.stopPropagation();
                _runSeoAutofix({ mode: "single", factorIds: [fid], triggerBtn: btn });
            });
        }

        _updateAutofixUndoBtn();
    };

    window.__caSeoAutofix = {
        run: _runSeoAutofix,
        apply: _applyAutofixPatch,
        undo: _undoAutofix,
        init: _initSeoAutofixUi,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _initSeoAutofixUi);
    } else {
        _initSeoAutofixUi();
    }
