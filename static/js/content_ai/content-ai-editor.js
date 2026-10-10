    // Lazy-load Cropper.js only when needed (crop modal).
    const ensureCropperLoaded = async () => {
        if (window.Cropper) return true;
        // CSS
        if (!document.getElementById("cropperCss")) {
            const l = document.createElement("link");
            l.id = "cropperCss";
            l.rel = "stylesheet";
            l.href = "https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.css";
            document.head.appendChild(l);
        }
        // JS
        await new Promise((resolve) => {
            const s = document.createElement("script");
            s.src = "https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.js";
            s.onload = resolve;
            s.onerror = resolve;
            document.head.appendChild(s);
        });
        return !!window.Cropper;
    };
    const getEditorInstance = () => {
        if (!USE_TINYMCE) return null;
        try {
            if (window.tinymce && tinymce.get("content")) return tinymce.get("content");
        } catch (_) {}
        return null;
    };
    const getContentValue = () => {
        const ed = getEditorInstance();
        let raw = "";
        if (ed) {
            try {
                const v = String(ed.getContent({ format: "html" }) || "");
                if (v.trim()) raw = v;
            } catch (_) {}
        }
        if (!raw) {
            const cr = byId("contentRender");
            const crVal = cr ? String(cr.innerHTML || "") : "";
            if (crVal.trim()) raw = crVal;
        }
        if (!raw) {
            const ta = byId("content");
            raw = ta ? String(ta.value || "") : "";
        }
        return stripImageAuthTokensFromHtml(raw);
    };
    const decodeHtmlEntitiesDeep = (value) => {
        const raw = String(value || "");
        if (!raw) return "";
        const ta = document.createElement("textarea");
        ta.innerHTML = raw;
        const once = ta.value;
        ta.innerHTML = once;
        return ta.value;
    };
    const autoInjectBlockquoteForContent = async (html, options = {}) => {
        const src = decodeHtmlEntitiesDeep(String(html || ""));
        if (!src.trim()) return src;
        try {
            const res = await fetch(`/content-ai/postprocess-content?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ content_html: src }),
                signal: options.signal,
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok && data && data.content_html) {
                const out = decodeHtmlEntitiesDeep(String(data.content_html));
                schedulePublishChecklist();
                return out;
            }
        } catch (_) {}
        return src;
    };
    let _publishChecklistTimer = null;
    let _publishChecklistBusy = false;
    let _publishChecklistApplyingStrip = false;
    const publishChecklistPanel = byId("publishChecklistPanel");
    const publishChecklistList = byId("publishChecklistList");
    const _publishChecklistHtmlNorm = (h) =>
        String(h || "").replace(/\s+/g, " ").trim();
    const refreshPublishChecklist = async () => {
        if (_publishChecklistBusy || _publishChecklistApplyingStrip) return;
        const pk = (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim();
        const title = (byId("title") && byId("title").value || "").trim();
        const meta = (byId("meta") && byId("meta").value || "").trim();
        const contentHtml = String(getContentValue() || "");
        if (!contentHtml.trim() && !title && !meta) {
            if (publishChecklistPanel) publishChecklistPanel.style.display = "none";
            if (typeof renderPublishChecklist === "function") renderPublishChecklist(null);
            return;
        }
        _publishChecklistBusy = true;
        try {
            const secRaw = byId("secondaryKeywords") ? byId("secondaryKeywords").value : "";
            const secondary_keywords = secRaw.split(",").map((s) => s.trim()).filter(Boolean);
            const res = await fetch(`/content-ai/publish-checklist?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    title,
                    meta_description: meta,
                    content_html: contentHtml,
                    primary_keyword: pk,
                    slug: (byId("slug") && byId("slug").value || "").trim(),
                    secondary_keywords,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (typeof renderPublishChecklist === "function") renderPublishChecklist(null);
                return;
            }
            const stripped = data && data.content_html_stripped;
            const normCur = _publishChecklistHtmlNorm(contentHtml);
            const normStrip = _publishChecklistHtmlNorm(stripped);
            const hasChecklistSection = /checklist\s*seo|checklist\s*trước\s*khi\s*publish/i.test(contentHtml);
            if (
                hasChecklistSection &&
                normStrip &&
                normStrip !== normCur
            ) {
                _publishChecklistApplyingStrip = true;
                try {
                    setContentValue(stripped);
                } finally {
                    window.setTimeout(() => {
                        _publishChecklistApplyingStrip = false;
                    }, 900);
                }
            }
            renderPublishChecklist(data);
        } catch (_) {
        } finally {
            _publishChecklistBusy = false;
        }
    };
    const schedulePublishChecklist = () => {
        if (_publishChecklistApplyingStrip) return;
        clearTimeout(_publishChecklistTimer);
        _publishChecklistTimer = setTimeout(() => void refreshPublishChecklist(), 1200);
    };
    const syncPreviewFallback = () => {
        try {
            const cr = byId("contentRender");
            if (!cr) return;
            const srcHtml = decodeHtmlEntitiesDeep(String(getContentValue() || ""));
            const srcTextLen = _stripText(srcHtml).length;
            const ed = getEditorInstance();
            if (!ed) {
                cr.innerHTML = srcHtml;
                // Luôn hiển thị contenteditable khi không dùng TinyMCE (tránh ẩn editor khi bài rỗng → thống kê không cập nhận được).
                cr.style.display = "block";
                return;
            }
            const body = ed.getBody ? ed.getBody() : null;
            const bodyVisible = !!(body && body.offsetHeight > 80);
            const tinyTextLen = body ? String(body.innerText || "").trim().length : 0;
            const tinyHtmlLen = String(ed.getContent({ format: "html" }) || "").trim().length;
            if (srcTextLen > 80 && tinyHtmlLen === 0 && (!bodyVisible || tinyTextLen < 20)) {
                cr.innerHTML = srcHtml;
                cr.style.display = "block";
            } else {
                cr.style.display = "none";
            }
        } catch (_) {}
    };
    const stripCorruptTargetWebsiteFromAppMedia = (html) =>
        String(html || "")
            // Customer site wrongly prefixed onto private app media
            .replace(/https?:\/\/[^/"'\s>]+(\/api\/user-files\/[^"'\s?#]+)/gi, "$1")
            .replace(/https?:\/\/[^/"'\s>]+(\/static\/uploads\/[^"'\s?#]+)/gi, "$1");
    const setContentValue = (html) => {
        const cleaned = stripCorruptTargetWebsiteFromAppMedia(String(html || ""));
        const v = stripImageAuthTokensFromHtml(decodeHtmlEntitiesDeep(cleaned));
        const displayHtml = withImageAuthTokensForHtml(v);
        const ta = byId("content");
        if (ta) ta.value = v;
        const element = byId("contentRender");
        if (element) element.innerHTML = displayHtml;
        const ed = getEditorInstance();
        if (ed) {
            try {
                ed.setContent(displayHtml, { format: "html" });
                ed.save();
                ed.nodeChanged();
            } catch (_) {}
        }
        syncPreviewFallback();
        schedulePublishChecklist();
        try {
            if (typeof updateContentStatsFromHtml === "function") {
                updateContentStatsFromHtml(v);
            }
        } catch (_) {}
    };
    const refreshEditorModeUi = () => {
        const cr = byId("contentRender");
        const ta = byId("content");
        if (!cr || !ta) return;
        const tiny = getEditorInstance();
        const visual = FORCE_VISUAL_MODE ? true : (editorMode !== "code");
        if (tiny) {
            if (visual) {
                try { tiny.show(); } catch (_) {}
                cr.style.display = "none";
                ta.style.display = "none";
            } else {
                try { tiny.hide(); } catch (_) {}
                ta.style.display = "block";
                cr.style.display = "none";
                ta.value = getContentValue();
            }
        } else {
            // No TinyMCE: edit directly on contenteditable box.
            ta.style.display = "none";
            cr.style.display = "block";
        }
        if (btnModeVisual) btnModeVisual.classList.toggle("active", visual);
        if (btnModeCode) btnModeCode.classList.toggle("active", !visual);
        if (btnModeCode) {
            btnModeCode.disabled = FORCE_VISUAL_MODE;
            btnModeCode.style.display = FORCE_VISUAL_MODE ? "none" : "";
        }
        syncPreviewFallback();
        try { refreshPreview(); } catch (_) {}
    };
    const ensureEditorVisible = () => {
        try {
            const tiny = getEditorInstance();
            if (!tiny) return;
            const container = tiny.getContainer ? tiny.getContainer() : null;
            const iframe = container ? container.querySelector("iframe") : null;
            const iframeH = iframe ? Math.ceil(iframe.getBoundingClientRect().height) : 0;
            const cur = String(tiny.getContent({ format: "html" }) || "").trim();
            const ta = byId("content");
            if (!cur && ta && String(ta.value || "").trim()) {
                tiny.setContent(String(ta.value || ""));
                tiny.save();
            }
            // If Tiny iframe is collapsed, restore size and keep visual mode.
            if (iframeH < 120) {
                if (container) container.style.minHeight = "520px";
                if (iframe) iframe.style.minHeight = "420px";
                if (iframe) iframe.style.display = "block";
                editorMode = "visual";
                refreshEditorModeUi();
            }
            syncPreviewFallback();
        } catch (_) {}
    };
    const execEditorCommand = (cmd) => {
        const tiny = window.tinymce && tinymce.get("content") ? tinymce.get("content") : null;
        if (tiny && editorMode !== "code") {
            if (cmd === "h2") tiny.execCommand("FormatBlock", false, "h2");
            else if (cmd === "h3") tiny.execCommand("FormatBlock", false, "h3");
            else if (cmd === "ul") tiny.execCommand("InsertUnorderedList");
            else if (cmd === "ol") tiny.execCommand("InsertOrderedList");
            else if (cmd === "table") tiny.execCommand("mceInsertTable", false, { rows: 3, columns: 2 });
            else if (cmd === "bold") tiny.execCommand("Bold");
            else if (cmd === "italic") tiny.execCommand("Italic");
            else if (cmd === "underline") tiny.execCommand("Underline");
            tiny.save();
            refreshPreview();
            return;
        }
        const cr = byId("contentRender");
        if (!cr) return;
        try { cr.focus(); } catch (_) {}
        if (cmd === "bold") document.execCommand("bold");
        else if (cmd === "italic") document.execCommand("italic");
        else if (cmd === "underline") document.execCommand("underline");
        else if (cmd === "h1") document.execCommand("formatBlock", false, "h1");
        else if (cmd === "h2") document.execCommand("formatBlock", false, "h2");
        else if (cmd === "h3") document.execCommand("formatBlock", false, "h3");
        else if (cmd === "h4") document.execCommand("formatBlock", false, "h4");
        else if (cmd === "h5") document.execCommand("formatBlock", false, "h5");
        else if (cmd === "h6") document.execCommand("formatBlock", false, "h6");
        else if (cmd === "blockquote") document.execCommand("formatBlock", false, "blockquote");
        else if (cmd === "paragraph") document.execCommand("formatBlock", false, "p");
        else if (cmd === "ul") document.execCommand("insertUnorderedList");
        else if (cmd === "ol") document.execCommand("insertOrderedList");
        else if (cmd === "align-left") document.execCommand("justifyLeft");
        else if (cmd === "align-center") document.execCommand("justifyCenter");
        else if (cmd === "align-right") document.execCommand("justifyRight");
        else if (cmd === "undo") document.execCommand("undo");
        else if (cmd === "redo") document.execCommand("redo");
        else if (cmd === "clear") document.execCommand("removeFormat");
        else if (cmd === "hr") document.execCommand("insertHorizontalRule");
        else if (cmd === "table") {
            document.execCommand("insertHTML", false, "<table><tr><th>Cột 1</th><th>Cột 2</th></tr><tr><td>Nội dung</td><td>Nội dung</td></tr></table>");
        } else if (cmd === "link") {
            const url = window.prompt("Nhập URL:", "https://");
            if (!url) return;
            document.execCommand("createLink", false, String(url));
        }
        const ta = byId("content");
        if (ta) ta.value = String(cr.innerHTML || "");
        if (editorBlockFormat) {
            if (cmd === "h1") editorBlockFormat.value = "h1";
            else if (cmd === "h2") editorBlockFormat.value = "h2";
            else if (cmd === "h3") editorBlockFormat.value = "h3";
            else if (cmd === "h4") editorBlockFormat.value = "h4";
            else if (cmd === "h5") editorBlockFormat.value = "h5";
            else if (cmd === "h6") editorBlockFormat.value = "h6";
            else if (cmd === "blockquote") editorBlockFormat.value = "blockquote";
            else if (cmd === "paragraph") editorBlockFormat.value = "p";
        }
        refreshPreview();
        saveFormState();
    };
    const syncBlockFormatBySelection = () => {
        try {
            if (!editorBlockFormat) return;
            const cr = byId("contentRender");
            if (!cr) return;
            const sel = window.getSelection ? window.getSelection() : null;
            if (!sel || sel.rangeCount < 1) return;
            let node = sel.anchorNode;
            if (!node) return;
            if (node.nodeType === Node.TEXT_NODE) node = node.parentElement;
            if (!(node instanceof Element)) return;
            if (!cr.contains(node)) return;
            const block = node.closest("h1, h2, h3, h4, h5, h6, blockquote");
            if (!block) {
                editorBlockFormat.value = "p";
                return;
            }
            const tag = String(block.tagName || "").toLowerCase();
            if (/^h[1-6]$/.test(tag) || tag === "blockquote") editorBlockFormat.value = tag;
            else editorBlockFormat.value = "";
        } catch (_) {}
    };
    const getTargetWordCountMode = () => {
        const row = byId("wordCountPresetRow");
        const active = row && row.querySelector(".wc-preset-btn.active");
        return active && String(active.dataset.wc || "") === "auto" ? "auto" : "manual";
    };
    const isAutoWordCountMode = () => getTargetWordCountMode() === "auto";
    const parseTargetWordCount = () => {
        if (isAutoWordCountMode()) return null;
        const el = byId("targetWordCount");
        const raw = String((el && el.value) || "").trim();
        if (!raw) return 1000;
        const digits = raw.replace(/[^\d]/g, "");
        const n = parseInt(digits || "1000", 10);
        return Number.isFinite(n) ? Math.max(200, Math.min(n, 20000)) : 1000;
    };
    const resolveClientWordTarget = (ctx) => {
        const mode = (ctx && ctx.target_word_count_mode) || getTargetWordCountMode();
        if (mode === "auto") {
            const resolved = Number(
                (ctx && (ctx.validated_word_count ?? ctx.word_count_target ?? ctx.target_word_count)) || 0,
            );
            return resolved > 0 ? resolved : null;
        }
        return Number((ctx && ctx.target_word_count) || parseTargetWordCount()) || 1000;
    };
    const syncTargetWordCountInputUi = () => {
        const input = byId("targetWordCount");
        if (!input) return;
        const auto = isAutoWordCountMode();
        input.disabled = auto;
        input.hidden = auto;
        if (auto) {
            input.value = "";
            input.removeAttribute("required");
        } else if (!String(input.value || "").trim()) {
            input.value = "1000";
        }
        const hint = byId("hint-target_word_count");
        if (hint) {
            hint.textContent = auto
                ? "AI tự quyết: hệ thống xác định độ dài phù hợp theo chủ đề, từ khóa và mục đích bài (sai lệch tối đa ±10%)."
                : "Chọn preset, nhập tùy chỉnh, hoặc AI tự quyết — hệ thống xác định độ dài phù hợp theo chủ đề, từ khóa và mục đích bài (sai lệch tối đa ±10%).";
        }
    };
    const updateWordCountStatus = (stats) => {
        const box = byId("wordCountStatus");
        if (!box || !stats) {
            if (box) box.hidden = true;
            return;
        }
        const requested = Number(stats.requested_word_count ?? stats.word_count_target) || 0;
        const validated = Number(stats.validated_word_count ?? stats.word_count_target) || 0;
        const actual = Number(stats.actual_word_count ?? stats.word_count_actual) || 0;
        const autoMode = String(stats.target_word_count_mode || "").toLowerCase() === "auto"
            || isAutoWordCountMode();
        if (!requested && !validated && stats.word_count_target == null && !autoMode) {
            box.hidden = true;
            return;
        }
        const status = String(stats.word_count_status || "").toLowerCase()
            || (stats.word_count_ok ? "ok" : actual < validated ? "short" : "long");
        const statusLabel = status === "ok" ? "Đạt" : status === "short" ? "Thiếu" : "Vượt";
        box.hidden = false;
        box.classList.remove("ok", "fail", "short", "long");
        box.classList.add(status === "ok" ? "ok" : "fail");
        box.textContent = autoMode
            ? `AI chọn mục tiêu: ${validated || "…"} từ · Thực tế: ${actual} từ · ${statusLabel}`
            : `Yêu cầu: ${requested || validated} từ · Mục tiêu: ${validated} từ · Thực tế: ${actual} từ · ${statusLabel}`;
    };
    const _stripTextFromHtml = (html) => String(html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const _wordCountFromHtml = (html) => {
        const t = _stripTextFromHtml(html);
        return t ? t.split(/\s+/).filter(Boolean).length : 0;
    };
    const _outlineHeadingStats = (outline) => {
        let h2 = 0;
        let h3 = 0;
        String(outline || "").split(/\r?\n/).forEach((line) => {
            const s = line.trim();
            if (s.startsWith("###")) h3 += 1;
            else if (s.startsWith("##")) h2 += 1;
        });
        return { h2, h3 };
    };
    const _effectiveWordTargetForCtx = (ctx) => {
        const base = resolveClientWordTarget(ctx || {}) || 1000;
        const outline = String(
            (ctx && ctx.outline_content) || (byId("outlineContent") && byId("outlineContent").value) || "",
        ).trim();
        if (!outline) return base;
        const { h2, h3 } = _outlineHeadingStats(outline);
        if (h2 <= 0 && h3 <= 0) return base;
        const floor = 150 + h2 * 90 + h3 * 45;
        return Math.max(base, Math.min(floor, 20000));
    };
    const _needsClientWordCountEnforce = (html, ctx) => {
        const validated = resolveClientWordTarget(ctx || {});
        if (!validated) return false;
        const actual = _wordCountFromHtml(html);
        const minRepair = Math.floor(validated * 0.85);
        const maxTrim = Math.ceil(validated * 1.15);
        if (actual > maxTrim) return true;
        const outline = String((ctx && ctx.outline_content) || "").trim();
        if (outline && actual >= minRepair) {
            const { h2, h3 } = _outlineHeadingStats(outline);
            if (h2 + h3 >= 6) {
                return actual < minRepair;
            }
        }
        return actual < minRepair || actual > maxTrim;
    };
    const _shouldSkipClientEnforce = (html, ctx, hint) => {
        if (_needsClientWordCountEnforce(html, ctx)) return false;
        if (hint && (hint.skip_client_enforce || hint.word_count_ok)) return true;
        return true;
    };
    const _localWordCountStats = (html, ctx) => {
        const validated = resolveClientWordTarget(ctx || {}) || 1000;
        const actual = _wordCountFromHtml(html);
        const minOk = Math.floor(validated * 0.9);
        const maxOk = Math.ceil(validated * 1.1);
        let status = "ok";
        if (actual < minOk) status = "short";
        else if (actual > maxOk) status = "long";
        return {
            requested_word_count: validated,
            validated_word_count: validated,
            actual_word_count: actual,
            word_count_status: status,
            word_count_ok: status === "ok",
            skip_client_enforce: !_needsClientWordCountEnforce(html, ctx),
        };
    };
    const enforceWordCountAfterWrite = async (html, ctx, signal) => {
        const ENFORCE_TIMEOUT_MS = 45000;
        const runEnforce = async () => {
            const res = await fetch(`/content-ai/enforce-word-count?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    content_html: html,
                    target_word_count: ctx.target_word_count,
                    target_word_count_mode: ctx.target_word_count_mode || getTargetWordCountMode(),
                    title: ctx.title || "",
                    primary_keyword: ctx.primary_keyword || "",
                    outline_content: ctx.outline_content || "",
                }),
                signal,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                    throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
                }
                const local = _localWordCountStats(html, ctx);
                const validated = Number(local.validated_word_count) || 1000;
                const nearTarget = Number(local.actual_word_count) >= Math.floor(validated * 0.85);
                _caStreamLog("enforce-word-count fail", res.status, data, local);
                if (nearTarget) {
                    return {
                        value: html,
                        soft_fail: true,
                        word_count_target: local.validated_word_count,
                        word_count_actual: local.actual_word_count,
                        word_count_ok: local.word_count_ok,
                        validated_word_count: local.validated_word_count,
                        actual_word_count: local.actual_word_count,
                        word_count_status: local.word_count_status,
                    };
                }
                throw new Error(fmtApiDetail(data.detail) || data.message || "Chuẩn hóa số từ thất bại.");
            }
            if (data && data.sync && (data.value || data.content_html)) {
                updateWordCountStatus(data);
                return {
                    value: String(data.value || data.content_html || html),
                    word_count_target: data.word_count_target ?? data.validated_word_count,
                    word_count_actual: data.word_count_actual ?? data.actual_word_count,
                    word_count_ok: data.word_count_ok,
                    validated_word_count: data.validated_word_count,
                    actual_word_count: data.actual_word_count,
                    word_count_status: data.word_count_status,
                };
            }
            const final = (window.SeoautoAwaitQueued)
                ? await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders(), signal })
                : data;
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
                void window.ContentAiUsage.refresh();
            }
            updateWordCountStatus(final);
            return {
                value: String((final && final.value) || (final && final.content_html) || html),
                word_count_target: final.word_count_target,
                word_count_actual: final.word_count_actual,
                word_count_ok: final.word_count_ok,
            };
        };
        try {
            let timeoutId = null;
            const timeoutPromise = new Promise((_, reject) => {
                timeoutId = window.setTimeout(
                    () => reject(new Error("ENFORCE_TIMEOUT")),
                    ENFORCE_TIMEOUT_MS,
                );
            });
            if (signal) {
                signal.addEventListener("abort", () => {
                    if (timeoutId) window.clearTimeout(timeoutId);
                }, { once: true });
            }
            try {
                return await Promise.race([runEnforce(), timeoutPromise]);
            } finally {
                if (timeoutId) window.clearTimeout(timeoutId);
            }
        } catch (e) {
            if (String(e && e.message) === "ENFORCE_TIMEOUT") {
                const local = _localWordCountStats(html, ctx);
                _caStreamLog("enforce-word-count timeout, keep content", local);
                return { value: html, soft_fail: true, enforce_timeout: true, ...local };
            }
            throw e;
        }
    };
    const syncWordCountPresetActive = () => {
        const wc = parseTargetWordCount();
        const row = byId("wordCountPresetRow");
        if (!row) return;
        let matched = false;
        if (isAutoWordCountMode()) {
            row.querySelectorAll(".wc-preset-btn").forEach((btn) => {
                const active = String(btn.dataset.wc || "") === "auto";
                btn.classList.toggle("active", active);
                if (active) matched = true;
            });
        } else {
            row.querySelectorAll(".wc-preset-btn").forEach((btn) => {
                const preset = String(btn.dataset.wc || "");
                if (preset === "auto") {
                    btn.classList.toggle("active", false);
                    return;
                }
                const isPreset = preset !== "custom" && Number(preset) === wc;
                const isCustom = preset === "custom" && ![1000, 1500, 2000].includes(wc);
                const active = isPreset || isCustom;
                btn.classList.toggle("active", active);
                if (active) matched = true;
            });
        }
        if (!matched) {
            const customBtn = row.querySelector('[data-wc="custom"]');
            if (customBtn && !isAutoWordCountMode()) customBtn.classList.add("active");
        }
        syncTargetWordCountInputUi();
    };
    const initWordCountPresets = () => {
        const row = byId("wordCountPresetRow");
        const input = byId("targetWordCount");
        if (!row || !input) return;
        const activatePresetBtn = (btn) => {
            row.querySelectorAll(".wc-preset-btn").forEach((b) => {
                b.classList.remove("active");
                b.disabled = false;
            });
            btn.classList.add("active");
        };
        if (row.dataset.wcBound !== "1") {
            row.dataset.wcBound = "1";
            row.addEventListener("click", (e) => {
                const btn = e.target && e.target.closest(".wc-preset-btn");
                if (!btn || !row.contains(btn)) return;
                e.preventDefault();
                const preset = String(btn.dataset.wc || "");
                activatePresetBtn(btn);
                if (preset === "auto") {
                    syncTargetWordCountInputUi();
                    saveFormState();
                    try { updateAutoInsertImagePreview(); } catch (_) {}
                    return;
                }
                if (preset === "custom") {
                    syncTargetWordCountInputUi();
                    try { input.focus(); } catch (_) {}
                    saveFormState();
                    try { updateAutoInsertImagePreview(); } catch (_) {}
                    return;
                }
                const n = parseInt(preset, 10);
                if (Number.isFinite(n)) input.value = String(n);
                syncTargetWordCountInputUi();
                saveFormState();
                try { updateAutoInsertImagePreview(); } catch (_) {}
            });
            input.addEventListener("input", () => {
                if (isAutoWordCountMode()) return;
                syncWordCountPresetActive();
                try { updateAutoInsertImagePreview(); } catch (_) {}
            });
        }
        syncWordCountPresetActive();
    };
    initWordCountPresets();

    const getSelectedAiProvider = () => {
        const el = byId("contentAiLlmProvider");
        const v = el && el.value ? String(el.value).trim().toLowerCase() : "auto";
        return v || "auto";
    };

    const showLlmFallbackNotice = (msg) => {
        const box = byId("contentAiLlmFallbackNotice");
        if (!box) return;
        const text = String(msg || "").trim();
        if (!text) {
            box.hidden = true;
            box.textContent = "";
            return;
        }
        box.textContent = text;
        box.hidden = false;
    };

    const CONTENT_AI_LLM_PROVIDER_CATALOG = [
        {
            id: "auto",
            label: "Tự động – Khuyên dùng",
            description: "Hệ thống chọn AI phù hợp theo loại bài, số từ, tốc độ và chi phí.",
            selectable: true,
        },
        {
            id: "openai",
            label: "OpenAI GPT",
            description: "Chất lượng toàn diện, phù hợp đa dạng loại bài SEO.",
            selectable: true,
        },
        {
            id: "gemini",
            label: "Google Gemini",
            description: "Phù hợp bài dài, xử lý ngữ cảnh rộng.",
            selectable: true,
        },
        {
            id: "anthropic",
            label: "Claude",
            description: "Văn phong tự nhiên, mạch lạc.",
            selectable: true,
        },
        {
            id: "deepseek",
            label: "DeepSeek",
            description: "Tiết kiệm chi phí, tốc độ ổn định.",
            selectable: true,
        },
        {
            id: "qwen",
            label: "Qwen",
            description: "Mô hình đa ngôn ngữ, phù hợp nội dung tiếng Việt.",
            selectable: true,
        },
    ];

    const mergeLlmProviderChoices = (apiChoices) => {
        const apiMap = new Map(
            (Array.isArray(apiChoices) ? apiChoices : [])
                .filter((c) => c && c.id)
                .map((c) => [String(c.id).toLowerCase(), c])
        );
        return CONTENT_AI_LLM_PROVIDER_CATALOG.map((base) => {
            const fromApi = apiMap.get(base.id);
            if (!fromApi) return { ...base };
            return {
                ...base,
                label: fromApi.label || base.label,
                description: fromApi.description || base.description,
                selectable: fromApi.selectable !== false,
            };
        });
    };

    const populateLlmProviderSelect = (sel, choices, preferredId) => {
        if (!sel || !choices.length) return "auto";
        sel.innerHTML = "";
        choices.forEach((c) => {
            const opt = document.createElement("option");
            opt.value = String(c.id || "auto");
            opt.textContent = String(c.label || c.id || "auto");
            opt.title = String(c.description || "");
            if (c.selectable === false) opt.disabled = true;
            sel.appendChild(opt);
        });
        const preferred = String(preferredId || "auto").toLowerCase();
        const preferredRow = choices.find((c) => c.id === preferred);
        if (preferredRow && preferredRow.selectable !== false) {
            sel.value = preferred;
            return preferred;
        }
        sel.value = "auto";
        return "auto";
    };

    const initContentAiLlmProviderSelect = async () => {
        const sel = byId("contentAiLlmProvider");
        const hint = byId("hint-contentAiLlmProvider");
        if (!sel) return;
        const savedKey = userStorageKey("content_ai_llm_provider");
        let savedVal = "auto";
        try { savedVal = localStorage.getItem(savedKey) || "auto"; } catch (_) {}
        let choices = mergeLlmProviderChoices([]);
        try {
            const res = await fetch("/content-ai/llm-providers", { headers: authJsonHeaders() });
            const data = await res.json().catch(() => ({}));
            choices = mergeLlmProviderChoices(data.choices);
        } catch (_) {
            choices = mergeLlmProviderChoices([]);
        }
        const effective = populateLlmProviderSelect(sel, choices, savedVal);
        if (effective !== savedVal) {
            try { localStorage.setItem(savedKey, effective); } catch (_) {}
        }
        const refreshHint = () => {
            const cur = choices.find((c) => c.id === sel.value);
            if (hint && cur && cur.description) {
                hint.textContent = String(cur.description);
                hint.hidden = false;
                hint.removeAttribute("aria-hidden");
            }
        };
        refreshHint();
        sel.addEventListener("change", () => {
            const row = choices.find((c) => c.id === sel.value);
            if (row && row.selectable === false) {
                sel.value = "auto";
            }
            try { localStorage.setItem(savedKey, sel.value || "auto"); } catch (_) {}
            refreshHint();
            showLlmFallbackNotice("");
        });
    };
    void initContentAiLlmProviderSelect();

    const buildContext = () => ({
        title: byId("title").value.trim(),
        target_website: normalizeTargetBase(byId("targetWebsite").value.trim()),
        slug: byId("slug").value.trim(),
        primary_keyword: byId("primaryKeyword").value.trim(),
        secondary_keywords: byId("secondaryKeywords").value.trim(),
        outline_content: byId("outlineContent").value,
        meta_description: byId("meta").value.trim(),
        tags: byId("tags").value.trim(),
        target_word_count: parseTargetWordCount(),
        target_word_count_mode: getTargetWordCountMode(),
        content: getContentValue(),
        scheduled_at: byId("scheduledAt").value || "",
        featured_image: uploadedImages[0] || "",
        gallery_images: uploadedImages.slice(),
        ai_provider: getSelectedAiProvider(),
    });
    const normalizeKeywordSlug = (value) => {
        const map = { "đ": "d", "Đ": "D" };
        const replaced = (value || "").replace(/[đĐ]/g, (m) => map[m] || m);
        return replaced
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .replace(/-+/g, "-");
    };
    const normalizeTargetBase = (target) => {
        const raw = (target || "").trim();
        if (!raw) return "";
        try {
            const parsed = new URL(raw.includes("://") ? raw : `https://${raw}`);
            return `${parsed.protocol}//${parsed.host.toLowerCase()}`;
        } catch (_) {
            return "";
        }
    };
    const buildStrictSlug = () => {
        const kw = normalizeKeywordSlug(byId("primaryKeyword").value.trim());
        if (!kw) return "";
        return kw;
    };
    const syncSlugFromPrimary = (force) => {
        const strict = buildStrictSlug();
        if (!strict) return;
        const slugEl = byId("slug");
        if (!slugEl) return;
        const cur = slugEl.value.trim();
        if (force || !cur || cur === _lastAutoSlug) {
            slugEl.value = strict;
            _lastAutoSlug = strict;
        }
    };
    let _lastAutoSlug = "";
    const readTargetHistory = () => {
        try {
            const raw = localStorage.getItem(TARGET_HISTORY_KEY());
            if (!raw) return [];
            const arr = JSON.parse(raw);
            if (!Array.isArray(arr)) return [];
            return arr.map((x) => String(x || "").trim()).filter(Boolean);
        } catch (_) {
            return [];
        }
    };
    const writeTargetHistory = (items) => {
        try {
            localStorage.setItem(TARGET_HISTORY_KEY(), JSON.stringify(items.slice(0, 10)));
        } catch (_) {}
    };
    const renderTargetHistory = () => {
        const seen = new Set();
        const merged = [];
        const pushUrl = (raw) => {
            const b = normalizeTargetBase(raw) || normalizeWpUrl(raw);
            if (!b) return;
            const k = b.toLowerCase();
            if (seen.has(k)) return;
            seen.add(k);
            merged.push(b);
        };
        settingsPublishingSitesFlat.forEach((s) => pushUrl(s.url));
        readTargetHistory().forEach(pushUrl);
        targetWebsiteHistoryList.innerHTML = "";
        merged.slice(0, 28).forEach((url) => {
            const opt = document.createElement("option");
            opt.value = url;
            targetWebsiteHistoryList.appendChild(opt);
        });
    };
    const rememberTargetWebsite = (value) => {
        const base = normalizeTargetBase(value);
        if (!base) return;
        const existing = readTargetHistory().filter((x) => x.toLowerCase() !== base.toLowerCase());
        existing.unshift(base);
        writeTargetHistory(existing);
        renderTargetHistory();
        renderConnectedSitesPanel();
    };

    const readWpUrlHistory = () => {
        try {
            const raw = localStorage.getItem(WP_URL_HISTORY_KEY());
            if (!raw) return [];
            const arr = JSON.parse(raw);
            if (!Array.isArray(arr)) return [];
            return arr.map((x) => String(x || "").trim()).filter(Boolean);
        } catch (_) {
            return [];
        }
    };
    const writeWpUrlHistory = (items) => {
        try {
            localStorage.setItem(WP_URL_HISTORY_KEY(), JSON.stringify(items.slice(0, 12)));
        } catch (_) {}
    };
    const normalizeWpUrl = (value) => {
        const raw = (value || "").trim();
        if (!raw) return "";
        try {
            const u = new URL(raw.includes("://") ? raw : `https://${raw}`);
            return `${u.protocol}//${u.host}`;
        } catch (_) {
            return "";
        }
    };
    const connectedSiteKey = (raw) => {
        const b = normalizeWpUrl(raw) || normalizeTargetBase(raw);
        if (!b) return "";
        try {
            const u = new URL(b.includes("://") ? b : `https://${b}`);
            let host = u.hostname.toLowerCase();
            if (host.startsWith("www.")) host = host.slice(4);
            return `${u.protocol}//${host}`;
        } catch (_) {
            return b.toLowerCase();
        }
    };
    const connectedSiteHostLabel = (raw) => {
        const u = String(raw || "").trim();
        if (!u) return "website này";
        try {
            const h = new URL(u.includes("://") ? u : `https://${u}`).host;
            return h || u;
        } catch (_) {
            return u;
        }
    };
    const renderWpUrlHistory = () => {
        if (!wpUrlHistoryList) return;
        const seen = new Set();
        const merged = [];
        const pushUrl = (raw) => {
            const b = normalizeWpUrl(raw);
            if (!b) return;
            const k = b.toLowerCase();
            if (seen.has(k)) return;
            seen.add(k);
            merged.push(b);
        };
        settingsPublishingSitesFlat.forEach((s) => {
            if (s.platform === "wordpress") pushUrl(s.url);
        });
        readWpUrlHistory().forEach(pushUrl);
        wpUrlHistoryList.innerHTML = "";
        merged.slice(0, 28).forEach((u) => {
            const opt = document.createElement("option");
            opt.value = u;
            wpUrlHistoryList.appendChild(opt);
        });
    };
    const rememberWpUrl = (value) => {
        const base = normalizeWpUrl(value);
        if (!base) return;
        const existing = readWpUrlHistory().filter((x) => x.toLowerCase() !== base.toLowerCase());
        existing.unshift(base);
        writeWpUrlHistory(existing);
        renderWpUrlHistory();
        renderConnectedSitesPanel();
    };

    const readWpUserHistory = () => {
        try {
            const raw = localStorage.getItem(WP_USER_HISTORY_KEY());
            if (!raw) return [];
            const arr = JSON.parse(raw);
            if (!Array.isArray(arr)) return [];
            return arr.map((x) => String(x || "").trim()).filter(Boolean);
        } catch (_) {
            return [];
        }
    };
    const writeWpUserHistory = (items) => {
        try {
            localStorage.setItem(WP_USER_HISTORY_KEY(), JSON.stringify(items.slice(0, 12)));
        } catch (_) {}
    };
    const renderWpUserHistory = () => {
        if (!wpUserHistoryList) return;
        const items = readWpUserHistory();
        wpUserHistoryList.innerHTML = "";
        items.forEach((u) => {
            const opt = document.createElement("option");
            opt.value = u;
            wpUserHistoryList.appendChild(opt);
        });
    };
    const rememberWpUser = (value) => {
        const raw = String(value || "").trim();
        if (!raw) return;
        const v = raw.length > 120 ? raw.slice(0, 120) : raw;
        const existing = readWpUserHistory().filter((x) => x.toLowerCase() !== v.toLowerCase());
        existing.unshift(v);
        writeWpUserHistory(existing);
        renderWpUserHistory();
    };
    const SITE_PROFILES_KEY = () => userStorageKey("content_ai_site_profiles_v1");
    const LEGACY_WP_PROFILES_KEY = "content_ai_wp_profiles_v1";
    const MAX_SITE_PROFILES = 32;
    const PUB_PLATFORM_LABELS = { wordpress: "WordPress", shopify: "Shopify", haravan: "Haravan", webcake: "Webcake" };
    const newSiteProfileId = () =>
        typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `site_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    const normalizeWpProfileSiteUrl = (v) => normalizeWpUrl(v) || normalizeTargetBase(v) || "";
    const normalizePlatform = (p) => {
        const x = String(p || "wordpress").toLowerCase();
        return Object.prototype.hasOwnProperty.call(PUB_PLATFORM_LABELS, x) ? x : "wordpress";
    };
    const fetchSettingsPublishingSites = async () => {
        if (!getAuthToken()) {
            settingsPublishingSitesFlat = [];
            return;
        }
        try {
            const r = await apiFetch(`/api/settings/publishing-sites?ts=${Date.now()}`);
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                settingsPublishingSitesFlat = [];
                return;
            }
            const itemsObj = data.items || {};
            const flat = [];
            Object.keys(PUB_PLATFORM_LABELS).forEach((plat) => {
                const arr = itemsObj[plat];
                if (!Array.isArray(arr)) return;
                arr.forEach((s) => {
                    const raw = String((s && s.url) || "").trim();
                    const url = normalizeWpUrl(raw) || normalizeTargetBase(raw);
                    if (!url) return;
                    flat.push({
                        platform: normalizePlatform(plat),
                        url,
                        name: String((s && s.name) || "").trim(),
                        id: String((s && s.id) || ""),
                        username: String((s && s.username) || "").trim(),
                    });
                });
            });
            settingsPublishingSitesFlat = flat;
        } catch (_) {
            settingsPublishingSitesFlat = [];
        }
    };
    const profileSiteUrl = (p) => normalizeWpProfileSiteUrl(String((p && (p.site_url || p.wp_url)) || "").trim());
    const normalizeStoredProfile = (p) => {
        if (!p || typeof p !== "object") return null;
        const platform = normalizePlatform(p.platform);
        const site_url = normalizeWpProfileSiteUrl(String(p.site_url || p.wp_url || "").trim());
        if (!site_url) return null;
        return {
            id: String(p.id || newSiteProfileId()),
            platform,
            site_url,
            name: String(p.name || "").trim(),
            username: String(p.username || "").trim(),
            app_password: String(p.app_password || ""),
            seo_plugin: String(p.seo_plugin || "auto").trim() || "auto",
        };
    };
    const readSiteProfiles = () => {
        try {
            const raw = localStorage.getItem(SITE_PROFILES_KEY());
            if (raw) {
                const arr = JSON.parse(raw);
                if (Array.isArray(arr)) return arr.map(normalizeStoredProfile).filter(Boolean);
            }
        } catch (_) {}
        if (getAuthUserId() > 0) return [];
        try {
            const raw = localStorage.getItem(LEGACY_WP_PROFILES_KEY);
            if (!raw) return [];
            const arr = JSON.parse(raw);
            if (!Array.isArray(arr)) return [];
            return arr
                .filter((x) => x && typeof x === "object")
                .map((p) =>
                    normalizeStoredProfile({
                        id: p.id,
                        platform: "wordpress",
                        site_url: normalizeWpProfileSiteUrl(String(p.wp_url || "").trim()),
                        username: p.username,
                        app_password: p.app_password,
                        seo_plugin: p.seo_plugin,
                    }),
                )
                .filter(Boolean);
        } catch (_) {
            return [];
        }
    };
    const persistSiteProfiles = (items) => {
        const clean = items
            .map(normalizeStoredProfile)
            .filter(Boolean)
            .map((p) => ({ ...p, app_password: "" }));
        try {
            localStorage.setItem(SITE_PROFILES_KEY(), JSON.stringify(clean.slice(0, MAX_SITE_PROFILES)));
            try {
                localStorage.removeItem(LEGACY_WP_PROFILES_KEY);
            } catch (_) {}
            return true;
        } catch (e) {
            console.error("persistSiteProfiles failed", e);
            return false;
        }
    };
    const fetchPublishingSiteWithSecrets = async (siteId) => {
        const sid = String(siteId || "").trim();
        if (!sid) return null;
        try {
            const r = await fetch(
                `/api/settings/publishing-sites/${encodeURIComponent(sid)}?reveal_password=1&ts=${Date.now()}`,
                { headers: authHeaders() }
            );
            const data = await r.json().catch(() => ({}));
            if (!r.ok) return null;
            return data.item && typeof data.item === "object" ? data.item : null;
        } catch (_) {
            return null;
        }
    };
    const syncPublishingSiteToServer = async (entry) => {
        const plat = normalizePlatform(entry.platform);
        const url = profileSiteUrl(entry);
        if (!url) return { ok: false, message: "Thiếu URL site." };
        await fetchSettingsPublishingSites();
        const siteKey = connectedSiteKey(url);
        const hit = settingsPublishingSitesFlat.find(
            (s) => normalizePlatform(s.platform) === plat && connectedSiteKey(s.url) === siteKey
        );
        const displayName = String(entry.name || "").trim() || url;
        const passNorm = String(entry.app_password || "").trim().replace(/\s+/g, "");
        if (plat === "wordpress") {
            const body = {
                platform: "wordpress",
                name: displayName,
                url,
                username: String(entry.username || "").trim(),
                app_password: passNorm,
                default_status: "draft",
            };
            if (hit && hit.id) {
                const patch = { name: body.name, url: body.url, username: body.username };
                if (passNorm) patch.app_password = passNorm;
                const r = await fetch(`/api/settings/publishing-sites/${encodeURIComponent(hit.id)}`, {
                    method: "PATCH",
                    headers: authJsonHeaders(),
                    body: JSON.stringify(patch),
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    return {
                        ok: false,
                        message: (data && data.detail) ? String(data.detail) : `Lỗi cập nhật server (HTTP ${r.status})`,
                    };
                }
                if (siteKey && body.username && passNorm) {
                    _wpCredSessionCache.set(siteKey, {
                        wpUrl: url,
                        username: body.username,
                        app_password: passNorm,
                        seo_plugin: String(entry.seo_plugin || "auto").trim() || "auto",
                    });
                }
                return { ok: true, message: "Đã cập nhật site trên server (Cài đặt → Xuất bản)." };
            }
            if (!body.username || !body.app_password) {
                return { ok: false, message: "Thiếu username hoặc Application password." };
            }
            const r = await fetch("/api/settings/publishing-sites", {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify(body),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                return {
                    ok: false,
                    message: (data && data.detail) ? String(data.detail) : `Lỗi tạo site server (HTTP ${r.status})`,
                };
            }
            if (siteKey && body.username && passNorm) {
                _wpCredSessionCache.set(siteKey, {
                    wpUrl: url,
                    username: body.username,
                    app_password: passNorm,
                    seo_plugin: String(entry.seo_plugin || "auto").trim() || "auto",
                });
            }
            return { ok: true, message: "Đã lưu site lên server (Cài đặt → Xuất bản)." };
        }
        const body = {
            platform: plat,
            name: displayName,
            url,
            username: "",
            app_password: passNorm,
            default_status: "draft",
        };
        if (hit && hit.id) {
            const patch = { name: body.name, url: body.url };
            if (passNorm) patch.app_password = passNorm;
            const r = await fetch(`/api/settings/publishing-sites/${encodeURIComponent(hit.id)}`, {
                method: "PATCH",
                headers: authJsonHeaders(),
                body: JSON.stringify(patch),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                return {
                    ok: false,
                    message: (data && data.detail) ? String(data.detail) : `Lỗi cập nhật (HTTP ${r.status})`,
                };
            }
            return { ok: true, message: "Đã cập nhật site trên server." };
        }
        if (!passNorm) {
            return { ok: false, message: "Thiếu token / app password." };
        }
        const r = await fetch("/api/settings/publishing-sites", {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify(body),
        });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) {
            return {
                ok: false,
                message: (data && data.detail) ? String(data.detail) : `Lỗi tạo site (HTTP ${r.status})`,
            };
        }
        return { ok: true, message: "Đã lưu site lên server." };
    };
    let currentPubPlatform = "wordpress";
    /** Session cache: siteKey -> { username, app_password, seo_plugin, wpUrl } */
    const _wpCredSessionCache = new Map();
    /** Khi Edit site / dự án — chỉ hiển thị & sửa đúng một website (không liệt kê site khác). */
    let _wpProfilesFocusSiteKey = "";
    /** Mở «Thêm site đăng bài» — form trống, không hiện card site cũ phía trên form; lưu vẫn cộng thêm site. */
    let _wpProfilesAddNewMode = false;
    const wpProfilesBackdropEl = byId("wpProfilesBackdrop");
    const wpProfilesModalEl = byId("wpProfilesModal");
    const resolveWpPublishCredentialsLocal = (siteUrlRaw) => {
        const wpUrlRaw =
            siteUrlRaw != null
                ? String(siteUrlRaw || "").trim()
                : byId("wpUrl")
                  ? String(byId("wpUrl").value || "").trim()
                  : "";
        const wpUrl = normalizeWpUrl(wpUrlRaw) || wpUrlRaw;
        const key = connectedSiteKey(wpUrl);
        let username = "";
        let app_password = "";
        let seo_plugin = "auto";
        if (key) {
            const p = readSiteProfiles().find(
                (x) => normalizePlatform(x.platform) === "wordpress" && connectedSiteKey(profileSiteUrl(x)) === key,
            );
            if (p) {
                username = String(p.username || "").trim();
                app_password = String(p.app_password || "").trim().replace(/\s+/g, "");
                seo_plugin = String(p.seo_plugin || "auto").trim() || "auto";
            }
        }
        return { wpUrl, username, app_password, seo_plugin, siteKey: key || "" };
    };
    /** Sync helper (local only). Prefer async resolveWpPublishCredentials for publish. */
    const resolveWpPublishCredentials = () => {
        const c = resolveWpPublishCredentialsLocal();
        return {
            wpUrl: c.wpUrl,
            username: c.username,
            app_password: c.app_password,
            seo_plugin: c.seo_plugin,
        };
    };
    const resolveWpPublishCredentialsForSite = (siteUrlRaw) => {
        const c = resolveWpPublishCredentialsLocal(siteUrlRaw);
        return { wpUrl: c.wpUrl, username: c.username, app_password: c.app_password };
    };
    /**
     * Resolve WP credentials for publish: local profile first, then Settings API (reveal_password).
     * localStorage intentionally strips app_password — must fall back to server.
     */
    const resolveWpPublishCredentialsAsync = async (siteUrlRaw) => {
        let cred = resolveWpPublishCredentialsLocal(siteUrlRaw);
        if (cred.username && cred.app_password) {
            return {
                wpUrl: cred.wpUrl,
                username: cred.username,
                app_password: cred.app_password,
                seo_plugin: cred.seo_plugin,
            };
        }
        const key = cred.siteKey || connectedSiteKey(cred.wpUrl);
        if (key && _wpCredSessionCache.has(key)) {
            const cached = _wpCredSessionCache.get(key);
            if (cached && cached.username && cached.app_password) {
                return {
                    wpUrl: cached.wpUrl || cred.wpUrl,
                    username: cached.username,
                    app_password: cached.app_password,
                    seo_plugin: cached.seo_plugin || cred.seo_plugin || "auto",
                };
            }
        }
        try {
            await fetchSettingsPublishingSites();
        } catch (_) {}
        const hit = settingsPublishingSitesFlat.find(
            (s) =>
                normalizePlatform(s.platform) === "wordpress" &&
                key &&
                connectedSiteKey(s.url) === key,
        );
        if (hit) {
            if (!cred.username && hit.username) {
                cred.username = String(hit.username || "").trim();
            }
            if (hit.id) {
                const full = await fetchPublishingSiteWithSecrets(hit.id);
                if (full) {
                    const u = String(full.username || hit.username || cred.username || "").trim();
                    const p = String(full.app_password || "").trim().replace(/\s+/g, "");
                    const url = normalizeWpUrl(full.url || hit.url || cred.wpUrl) || cred.wpUrl;
                    if (u) cred.username = u;
                    if (p) cred.app_password = p;
                    if (url) cred.wpUrl = url;
                }
            }
        }
        if (key && cred.username && cred.app_password) {
            _wpCredSessionCache.set(key, {
                wpUrl: cred.wpUrl,
                username: cred.username,
                app_password: cred.app_password,
                seo_plugin: cred.seo_plugin || "auto",
            });
        }
        return {
            wpUrl: cred.wpUrl,
            username: cred.username,
            app_password: cred.app_password,
            seo_plugin: cred.seo_plugin || "auto",
        };
    };
    const applyWpProfileToForm = (p) => {
        if (normalizePlatform(p.platform) !== "wordpress") return false;
        const url = profileSiteUrl(p);
        if (!url) return false;
        const wpEl = byId("wpUrl");
        if (wpEl) wpEl.value = url;
        const nameEl = byId("inpWpProfileName");
        if (nameEl) nameEl.value = String(p.name || "").trim();
        rememberWpUrl(url);
        rememberWpUser(String(p.username || "").trim());
        rememberTargetWebsite(url);
        try {
            renderConnectedSitesPanel();
        } catch (_) {}
        try {
            saveFormState();
        } catch (_) {}
        return true;
    };
    const setPubModalTitle = (text) => {
        const t = wpProfilesModalEl && wpProfilesModalEl.querySelector(".modal-title");
        if (t) t.textContent = text || "Thêm site đăng bài";
    };
    const prefillPubModalUrlOnly = (plat, url) => {
        const u = normalizeWpProfileSiteUrl(url) || String(url || "").trim();
        if (!u) return;
        if (plat === "wordpress") {
            const el = byId("inpWpProfileUrl");
            if (el) el.value = u;
        } else if (plat === "shopify") {
            const el = byId("inpPubShopifyUrl");
            if (el) el.value = u;
        } else if (plat === "haravan") {
            const el = byId("inpPubHaravanUrl");
            if (el) el.value = u;
        } else if (plat === "webcake") {
            const el = byId("inpPubWebcakeUrl");
            if (el) el.value = u;
        }
    };
    const applyProfileToPubModal = (p) => {
        if (!p) return;
        const plat = normalizePlatform(p.platform);
        setPubPlatformTab(plat, { force: !!_wpProfilesFocusSiteKey });
        const url = profileSiteUrl(p);
        if (plat === "wordpress") {
            const nameEl = byId("inpWpProfileName");
            const urlEl = byId("inpWpProfileUrl");
            const unEl = byId("inpWpProfileUsername");
            const pwEl = byId("inpWpProfileAppPassword");
            const seoEl = byId("selWpProfileSeo");
            if (nameEl) nameEl.value = String(p.name || "").trim();
            if (urlEl) urlEl.value = url;
            if (unEl) unEl.value = String(p.username || "").trim();
            if (pwEl) pwEl.value = String(p.app_password || "");
            if (seoEl) seoEl.value = String(p.seo_plugin || "auto").trim() || "auto";
        } else if (plat === "shopify") {
            const urlEl = byId("inpPubShopifyUrl");
            const nameEl = byId("inpPubShopifyName");
            const tokEl = byId("inpPubShopifyToken");
            if (urlEl) urlEl.value = url;
            if (nameEl) nameEl.value = String(p.name || "").trim();
            if (tokEl) tokEl.value = String(p.app_password || "");
        } else if (plat === "haravan") {
            const urlEl = byId("inpPubHaravanUrl");
            const nameEl = byId("inpPubHaravanName");
            const tokEl = byId("inpPubHaravanToken");
            if (urlEl) urlEl.value = url;
            if (nameEl) nameEl.value = String(p.name || "").trim();
            if (tokEl) tokEl.value = String(p.app_password || "");
        } else if (plat === "webcake") {
            const urlEl = byId("inpPubWebcakeUrl");
            const nameEl = byId("inpPubWebcakeName");
            const tokEl = byId("inpPubWebcakeToken");
            if (urlEl) urlEl.value = url;
            if (nameEl) nameEl.value = String(p.name || "").trim();
            if (tokEl) tokEl.value = String(p.app_password || "");
        }
    };
    const findProfilesForSiteUrl = (siteUrl) => {
        const key = connectedSiteKey(siteUrl);
        if (!key) return [];
        return readSiteProfiles().filter((p) => connectedSiteKey(profileSiteUrl(p)) === key);
    };
    const pickProfileForConnectedSite = (siteUrl, siteMeta) => {
        const profiles = findProfilesForSiteUrl(siteUrl);
        if (!profiles.length) return null;
        const meta = siteMeta || {};
        if (meta.wp) {
            const wp = profiles.find((p) => normalizePlatform(p.platform) === "wordpress");
            if (wp) return wp;
        }
        const plats = meta.platforms || [];
        for (const pl of plats) {
            const hit = profiles.find((p) => normalizePlatform(p.platform) === normalizePlatform(pl));
            if (hit) return hit;
        }
        return profiles[0];
    };
    const syncWpProfilesFocusUi = () => {
        const focused = !!_wpProfilesFocusSiteKey;
        if (wpProfilesModalEl) {
            wpProfilesModalEl.classList.toggle("is-site-focus", focused);
            wpProfilesModalEl.classList.toggle(
                "is-add-new-site",
                !!_wpProfilesAddNewMode && !focused
            );
        }
    };
    const resetPubModalFormForSite = (plat, siteUrl) => {
        const p = normalizePlatform(plat);
        const urlNorm =
            normalizeWpProfileSiteUrl(String(siteUrl || "").trim()) ||
            normalizeWpUrl(String(siteUrl || "").trim()) ||
            String(siteUrl || "").trim();
        if (p === "wordpress") {
            const nameEl = byId("inpWpProfileName");
            const urlEl = byId("inpWpProfileUrl");
            const unEl = byId("inpWpProfileUsername");
            const pwEl = byId("inpWpProfileAppPassword");
            const seoEl = byId("selWpProfileSeo");
            if (nameEl) nameEl.value = "";
            if (urlEl) urlEl.value = urlNorm;
            if (unEl) unEl.value = "";
            if (pwEl) pwEl.value = "";
            if (seoEl) seoEl.value = "auto";
        } else if (p === "shopify") {
            const urlEl = byId("inpPubShopifyUrl");
            const nameEl = byId("inpPubShopifyName");
            const tokEl = byId("inpPubShopifyToken");
            if (urlEl) urlEl.value = urlNorm;
            if (nameEl) nameEl.value = "";
            if (tokEl) tokEl.value = "";
        } else if (p === "haravan") {
            const urlEl = byId("inpPubHaravanUrl");
            const nameEl = byId("inpPubHaravanName");
            const tokEl = byId("inpPubHaravanToken");
            if (urlEl) urlEl.value = urlNorm;
            if (nameEl) nameEl.value = "";
            if (tokEl) tokEl.value = "";
        } else if (p === "webcake") {
            const urlEl = byId("inpPubWebcakeUrl");
            const nameEl = byId("inpPubWebcakeName");
            const tokEl = byId("inpPubWebcakeToken");
            if (urlEl) urlEl.value = urlNorm;
            if (nameEl) nameEl.value = "";
            if (tokEl) tokEl.value = "";
        }
    };
    const openWpProfilesModalForSite = async (siteUrl, siteMeta) => {
        const key = connectedSiteKey(siteUrl);
        _wpProfilesFocusSiteKey = key || "";
        _wpProfilesAddNewMode = false;
        const meta = siteMeta || {};
        let plat = "wordpress";
        if (meta.wp) plat = "wordpress";
        else if (meta.platforms && meta.platforms.length) plat = normalizePlatform(meta.platforms[0]);
        openWpProfilesModal({ clearCredentials: false, focusPlatform: plat });
        resetPubModalFormForSite(plat, siteUrl);
        setPubPlatformTab(plat, { force: true });
        syncWpProfilesFocusUi();
        renderWpProfilesSavedList();
        let profile = pickProfileForConnectedSite(siteUrl, siteMeta);
        if (!profile && key) {
            const locals = findProfilesForSiteUrl(siteUrl);
            profile = locals.find((x) => normalizePlatform(x.platform) === plat) || locals[0] || null;
        }
        if (profile) {
            applyProfileToPubModal(profile);
            setPubModalTitle("Chỉnh sửa site đăng bài");
            showWpProfileFeedback("Đã tải thông tin site này.", "ok");
            return;
        }
        const serverHit = settingsPublishingSitesFlat.find((s) => connectedSiteKey(s.url) === key);
        if (serverHit && serverHit.name) {
            if (plat === "wordpress") {
                const nameEl = byId("inpWpProfileName");
                if (nameEl) nameEl.value = serverHit.name;
            }
        }
        if (serverHit && serverHit.id) {
            showWpProfileFeedback("Đang tải thông tin đăng nhập đã lưu…", "info");
            const full = await fetchPublishingSiteWithSecrets(serverHit.id);
            if (full) {
                const merged = normalizeStoredProfile({
                    id: full.id || serverHit.id,
                    platform: full.platform || plat,
                    site_url: full.url || serverHit.url,
                    name: full.name || serverHit.name,
                    username: full.username || serverHit.username || "",
                    app_password: full.app_password || "",
                    seo_plugin: "auto",
                });
                if (merged) {
                    applyProfileToPubModal(merged);
                    showWpProfileFeedback(
                        merged.username && merged.app_password
                            ? "Đã tải username và Application password từ Cài đặt."
                            : "Site có trên server — nhập username và Application password rồi bấm «Lưu & áp dụng».",
                        merged.username && merged.app_password ? "ok" : "info"
                    );
                } else {
                    showWpProfileFeedback("", "");
                }
            } else if (serverHit.username) {
                const unEl = byId("inpWpProfileUsername");
                if (unEl) unEl.value = serverHit.username;
                showWpProfileFeedback(
                    "Đã tải username. Nhập Application password (server không trả lại mật khẩu cũ) rồi lưu.",
                    "info"
                );
            } else {
                showWpProfileFeedback("", "");
            }
        }
        setPubModalTitle("Chỉnh sửa site đăng bài");
    };
    const fillWpCredentialsFromSavedProfile = () => {
        /* Credentials lấy từ site đã lưu khi đăng bài — không còn ô trên thanh publish. */
    };
    const updatePubPlatformTabCounts = () => {
        const all = readSiteProfiles();
        const c = { wordpress: 0, shopify: 0, haravan: 0, webcake: 0 };
        all.forEach((p) => {
            const pl = normalizePlatform(p.platform);
            if (Object.prototype.hasOwnProperty.call(c, pl)) c[pl] += 1;
        });
        if (wpProfilesModalEl) {
            wpProfilesModalEl.querySelectorAll(".ppt-count[data-count-for]").forEach((el) => {
                const k = el.getAttribute("data-count-for");
                el.textContent = String((k && c[k]) || 0);
            });
        }
    };
    const syncPubModalSaveLabel = () => {
        const btn = byId("btnWpProfileSaveConnect");
        if (!btn) return;
        btn.textContent = currentPubPlatform === "wordpress" ? "Lưu & áp dụng" : "Lưu site";
    };
    const setPubPlatformTab = (plat, opts = {}) => {
        if (_wpProfilesFocusSiteKey && !opts.force) return;
        currentPubPlatform = normalizePlatform(plat);
        if (wpProfilesModalEl) {
            wpProfilesModalEl.querySelectorAll(".pub-platform-tab[data-platform]").forEach((b) => {
                const on = b.getAttribute("data-platform") === currentPubPlatform;
                b.classList.toggle("active", on);
                b.setAttribute("aria-selected", on ? "true" : "false");
            });
            wpProfilesModalEl.querySelectorAll(".pub-platform-panel[data-platform-panel]").forEach((panel) => {
                const on = panel.getAttribute("data-platform-panel") === currentPubPlatform;
                panel.classList.toggle("active", on);
            });
        }
        syncPubModalSaveLabel();
        const connWrap = byId("wpProfileConnActions");
        const testBtn = byId("btnWpProfileTestConn");
        const syncBtn = byId("btnWpProfileSyncPosts");
        const showConn = currentPubPlatform === "wordpress" || currentPubPlatform === "haravan";
        if (connWrap) connWrap.style.display = showConn ? "flex" : "none";
        if (testBtn) testBtn.textContent = currentPubPlatform === "haravan" ? "Test connection" : "Kiểm tra kết nối";
        if (syncBtn) syncBtn.textContent = currentPubPlatform === "haravan" ? "Sync Blogs" : "Đồng bộ bài viết";
        renderWpProfilesSavedList();
    };
    const wpProfileFormErrEl = byId("wpProfileFormErr");
    const fmtApiDetail = (d) => {
        if (!d) return "";
        if (typeof d === "string") return d;
        if (typeof d === "object" && !Array.isArray(d)) {
            if (d.code === "CONTENT_AI_LLM_UNAVAILABLE" && d.message) return String(d.message).trim();
            if (typeof d.message === "string" && d.message.trim()) return d.message.trim();
            if (typeof d.msg === "string" && d.msg.trim()) return d.msg.trim();
        }
        if (Array.isArray(d)) return d.map((x) => (x && x.msg) ? x.msg : JSON.stringify(x)).join("; ");
        return String(d);
    };
    const _contentAiErrMessage = (data, res) => {
        if (window.ContentAiErrors && window.ContentAiErrors.extract) {
            const m = window.ContentAiErrors.extract(data || {});
            if (m) return m;
        }
        return fmtApiDetail(data && data.detail) || (data && data.message) || `Gợi ý AI thất bại (HTTP ${res && res.status ? res.status : "?"})`;
    };
    const pubApiPaths = {
        wordpress: {
            test: ["/content-ai/wordpress/test-connection", "/api/settings/publishing-sites/wordpress/test-connection"],
            sync: ["/content-ai/wordpress/sync-posts", "/api/settings/publishing-sites/wordpress/sync-posts"],
            categories: [
                "/content-ai/wordpress/categories",
                "/api/settings/publishing-sites/wordpress/categories",
            ],
        },
        haravan: {
            test: ["/content-ai/haravan/test-connection", "/api/settings/publishing-sites/haravan/test-connection"],
            sync: ["/content-ai/haravan/sync-blogs", "/api/settings/publishing-sites/haravan/sync-blogs"],
        },
    };
    const postPubApi = async (paths, body) => {
        let lastResp = null;
        let lastData = {};
        for (const path of paths) {
            const r = await fetch(path, {
                method: "POST",
                headers: authHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify(body),
            });
            lastResp = r;
            lastData = await r.json().catch(() => ({}));
            if (r.status !== 404) return { r, data: lastData };
        }
        return { r: lastResp, data: lastData };
    };
    const showWpProfileFeedback = (text, kind) => {
        if (!wpProfileFormErrEl) return;
        wpProfileFormErrEl.textContent = text || "";
        wpProfileFormErrEl.classList.remove("ok", "info", "err");
        if (kind === "ok") wpProfileFormErrEl.classList.add("ok");
        else if (kind === "info") wpProfileFormErrEl.classList.add("info");
        else if (kind === "err") wpProfileFormErrEl.classList.add("err");
    };
    const profilePreviewBody = () => {
        const plat = currentPubPlatform;
        if (plat === "wordpress") {
            return {
                url: normalizeWpProfileSiteUrl(String(byId("inpWpProfileUrl").value || "").trim()),
                username: String(byId("inpWpProfileUsername").value || "").trim(),
                app_password: String(byId("inpWpProfileAppPassword").value || "").trim().replace(/\s+/g, ""),
            };
        }
        if (plat === "haravan") {
            return {
                store_url: String(byId("inpPubHaravanUrl").value || "").trim(),
                private_token: String(byId("inpPubHaravanToken").value || "").trim(),
            };
        }
        return null;
    };
    const renderWpProfilesSavedList = () => {
        const box = byId("wpProfilesSavedList");
        if (!box) return;
        box.innerHTML = "";
        syncWpProfilesFocusUi();
        const plat = currentPubPlatform;
        let profiles = readSiteProfiles().filter((x) => normalizePlatform(x.platform) === plat);
        if (_wpProfilesFocusSiteKey) {
            profiles = profiles.filter((p) => connectedSiteKey(profileSiteUrl(p)) === _wpProfilesFocusSiteKey);
        }
        if (_wpProfilesAddNewMode && !_wpProfilesFocusSiteKey) {
            const em = document.createElement("div");
            em.className = "hint";
            em.style.marginTop = "0";
            const n = profiles.length;
            em.textContent = n
                ? `Đang thêm site mới — ${n} site ${PUB_PLATFORM_LABELS[plat] || plat} đã lưu vẫn giữ nguyên. Điền form bên dưới (không hiện lại thông tin site cũ).`
                : `Điền form bên dưới để thêm site ${PUB_PLATFORM_LABELS[plat] || plat} mới.`;
            box.appendChild(em);
            return;
        }
        if (!profiles.length) {
            const em = document.createElement("div");
            em.className = "hint";
            em.style.marginTop = "0";
            em.textContent = _wpProfilesFocusSiteKey
                ? "Chưa lưu credential cho site này — điền form bên dưới và bấm «Lưu & áp dụng»."
                : plat === "wordpress"
                  ? "Chưa có site WordPress đã lưu. Điền form bên dưới và bấm «Lưu & áp dụng»."
                  : `Chưa có site ${PUB_PLATFORM_LABELS[plat] || plat} đã lưu. Điền form bên dưới và bấm «Lưu site».`;
            box.appendChild(em);
            return;
        }
        if (_wpProfilesFocusSiteKey && profiles.length === 1) {
            const p = profiles[0];
            const urlNorm = profileSiteUrl(p);
            let host = urlNorm;
            try {
                host = new URL(urlNorm).host || host;
            } catch (_) {}
            const card = document.createElement("div");
            card.className = "wp-profile-card is-current";
            card.innerHTML = `<div class="wp-profile-card-main"><strong>${String(p.name || "").trim() || host}</strong><div class="hint" style="margin:4px 0 0;font-size:0.72rem;">${plat === "wordpress" ? `User: ${String(p.username || "").trim() || "—"}` : "Token đã lưu"}</div></div>`;
            box.appendChild(card);
            return;
        }
        profiles.forEach((p) => {
            const urlNorm = profileSiteUrl(p);
            let host = urlNorm;
            try {
                host = new URL(urlNorm).host || host;
            } catch (_) {}
            const title = String(p.name || "").trim() || host;
            const row = document.createElement("div");
            row.className = "wp-profile-card";
            const main = document.createElement("div");
            main.className = "wp-profile-card-main";
            const strong = document.createElement("strong");
            strong.textContent = title;
            const hint = document.createElement("div");
            hint.className = "hint";
            hint.style.margin = "4px 0 0";
            hint.style.fontSize = "0.72rem";
            hint.textContent =
                plat === "wordpress"
                    ? `User: ${String(p.username || "").trim() || "—"}`
                    : `${PUB_PLATFORM_LABELS[plat] || plat} · token đã lưu cục bộ (không hiện lại)`;
            main.appendChild(strong);
            main.appendChild(hint);
            const actions = document.createElement("div");
            actions.className = "wp-profile-card-actions";
            const bu = document.createElement("button");
            bu.type = "button";
            bu.className = "mini-btn";
            bu.textContent = "Áp dụng";
            bu.addEventListener("click", () => {
                if (normalizePlatform(p.platform) === "wordpress") {
                    applyWpProfileToForm(p);
                    closeWpProfilesModal();
                    if (msg) msg.textContent = `Đã áp dụng đăng bài cho ${host}.`;
                    return;
                }
                const tgEl = byId("targetWebsite");
                const u = profileSiteUrl(p);
                if (tgEl) tgEl.value = u;
                rememberTargetWebsite(u);
                try {
                    renderConnectedSitesPanel();
                } catch (_) {}
                try {
                    saveFormState();
                } catch (_) {}
                closeWpProfilesModal();
                if (msg) {
                    msg.textContent = `Đã đặt Target website (${PUB_PLATFORM_LABELS[plat] || plat}): ${host}.`;
                }
            });
            const bx = document.createElement("button");
            bx.type = "button";
            bx.className = "mini-btn danger";
            bx.textContent = "Xóa";
            bx.addEventListener("click", () => {
                const next = readSiteProfiles().filter((x) => String(x.id) !== String(p.id));
                persistSiteProfiles(next);
                updatePubPlatformTabCounts();
                renderWpProfilesSavedList();
                try {
                    renderConnectedSitesPanel();
                } catch (_) {}
            });
            actions.appendChild(bu);
            actions.appendChild(bx);
            row.appendChild(main);
            row.appendChild(actions);
            box.appendChild(row);
        });
    };
    const clearPubModalCredentialFields = (plat) => {
        const p = normalizePlatform(plat);
        if (p === "wordpress") {
            const unEl = byId("inpWpProfileUsername");
            const pwEl = byId("inpWpProfileAppPassword");
            if (unEl) unEl.value = "";
            if (pwEl) pwEl.value = "";
        } else if (p === "shopify") {
            const tok = byId("inpPubShopifyToken");
            if (tok) tok.value = "";
        } else if (p === "haravan") {
            const tok = byId("inpPubHaravanToken");
            if (tok) tok.value = "";
        } else if (p === "webcake") {
            const tok = byId("inpPubWebcakeToken");
            if (tok) tok.value = "";
        }
    };
    const openWpProfilesModal = ({ clearCredentials = true, focusPlatform = null } = {}) => {
        if (clearCredentials) {
            _wpProfilesFocusSiteKey = "";
            _wpProfilesAddNewMode = true;
        }
        setPubModalTitle(_wpProfilesFocusSiteKey ? "Chỉnh sửa site đăng bài" : "Thêm site đăng bài");
        if (clearCredentials) {
            ["wordpress", "shopify", "haravan", "webcake"].forEach((p) => clearPubModalCredentialFields(p));
            const nameEl = byId("inpWpProfileName");
            const urlIn = byId("inpWpProfileUrl");
            if (nameEl) nameEl.value = "";
            if (urlIn) urlIn.value = "";
            const nShop = byId("inpPubShopifyName");
            const uShop = byId("inpPubShopifyUrl");
            const nHar = byId("inpPubHaravanName");
            const uHar = byId("inpPubHaravanUrl");
            const nWc = byId("inpPubWebcakeName");
            const uWc = byId("inpPubWebcakeUrl");
            if (nShop) nShop.value = "";
            if (uShop) uShop.value = "";
            if (nHar) nHar.value = "";
            if (uHar) uHar.value = "";
            if (nWc) nWc.value = "";
            if (uWc) uWc.value = "";
        }
        if (!_wpProfilesAddNewMode) {
            const urlIn = byId("inpWpProfileUrl");
            const cur = byId("wpUrl") && String(byId("wpUrl").value || "").trim();
            if (urlIn && cur && !String(urlIn.value || "").trim()) urlIn.value = cur;
            const uShop = byId("inpPubShopifyUrl");
            const uHar = byId("inpPubHaravanUrl");
            const uWc = byId("inpPubWebcakeUrl");
            if (cur) {
                if (uShop && !String(uShop.value || "").trim()) uShop.value = cur;
                if (uHar && !String(uHar.value || "").trim()) uHar.value = cur;
                if (uWc && !String(uWc.value || "").trim()) uWc.value = cur;
            }
        }
        updatePubPlatformTabCounts();
        syncPubModalSaveLabel();
        setPubPlatformTab(currentPubPlatform);
        showWpProfileFeedback("", "");
        renderWpProfilesSavedList();
        if (wpProfilesBackdropEl) wpProfilesBackdropEl.classList.add("open");
        if (wpProfilesModalEl) {
            wpProfilesModalEl.classList.add("open");
            wpProfilesModalEl.setAttribute("aria-hidden", "false");
        }
    };
    const closeWpProfilesModal = () => {
        _wpProfilesFocusSiteKey = "";
        _wpProfilesAddNewMode = false;
        syncWpProfilesFocusUi();
        if (wpProfilesBackdropEl) wpProfilesBackdropEl.classList.remove("open");
        if (wpProfilesModalEl) {
            wpProfilesModalEl.classList.remove("open");
            wpProfilesModalEl.setAttribute("aria-hidden", "true");
        }
    };
    const saveSiteProfileFromModal = async () => {
        const plat = currentPubPlatform;
        let url = "";
        let username = "";
        let pass = "";
        let seo = "auto";
        let name = "";
        if (plat === "wordpress") {
            url = normalizeWpProfileSiteUrl(String(byId("inpWpProfileUrl").value || "").trim());
            username = String(byId("inpWpProfileUsername").value || "").trim();
            pass = String(byId("inpWpProfileAppPassword").value || "").trim().replace(/\s+/g, "");
            name = String(byId("inpWpProfileName").value || "").trim();
            const seoEl = byId("selWpProfileSeo");
            seo = seoEl ? String(seoEl.value || "auto") : "auto";
            if (!url || !username || !pass) {
                showWpProfileFeedback("Nhập đủ URL WordPress, username và Application password.", "err");
                return;
            }
        } else if (plat === "shopify") {
            url = normalizeWpProfileSiteUrl(String(byId("inpPubShopifyUrl").value || "").trim());
            pass = String(byId("inpPubShopifyToken").value || "");
            name = String(byId("inpPubShopifyName").value || "").trim();
            if (!url || !pass) {
                showWpProfileFeedback("Nhập đủ URL cửa hàng Shopify và Admin API access token.", "err");
                return;
            }
        } else if (plat === "haravan") {
            url = normalizeWpProfileSiteUrl(String(byId("inpPubHaravanUrl").value || "").trim());
            pass = String(byId("inpPubHaravanToken").value || "");
            name = String(byId("inpPubHaravanName").value || "").trim();
            if (!url || !pass) {
                showWpProfileFeedback("Nhập đủ URL Haravan và private app token.", "err");
                return;
            }
        } else if (plat === "webcake") {
            url = normalizeWpProfileSiteUrl(String(byId("inpPubWebcakeUrl").value || "").trim());
            pass = String(byId("inpPubWebcakeToken").value || "");
            name = String(byId("inpPubWebcakeName").value || "").trim();
            if (!url || !pass) {
                showWpProfileFeedback("Nhập đủ URL Webcake và API token.", "err");
                return;
            }
        }
        const saveBtn = byId("btnWpProfileSaveConnect");
        const oldSaveLabel = saveBtn ? saveBtn.textContent : "";
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.textContent = "Đang lưu…";
        }
        showWpProfileFeedback("Đang lưu cấu hình…", "info");
        const list = readSiteProfiles().map((x) => ({ ...x }));
        const keyUrl = url.toLowerCase();
        const idx = list.findIndex(
            (x) => normalizePlatform(x.platform) === plat && profileSiteUrl(x).toLowerCase() === keyUrl
        );
        const entry = {
            id: idx >= 0 ? list[idx].id : newSiteProfileId(),
            platform: plat,
            site_url: url,
            name,
            username,
            app_password: pass,
            seo_plugin: seo,
        };
        if (idx >= 0) list[idx] = entry;
        else list.unshift(entry);
        if (!persistSiteProfiles(list)) {
            showWpProfileFeedback(
                "Không ghi được vào trình duyệt (localStorage). Kiểm tra chế độ ẩn danh hoặc dung lượng.",
                "err"
            );
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.textContent = oldSaveLabel;
            }
            return;
        }
        const serverSync = await syncPublishingSiteToServer(entry);
        if (!serverSync.ok) {
            showWpProfileFeedback(
                `Đã lưu trên trình duyệt nhưng server: ${serverSync.message}`,
                "err"
            );
        }
        await fetchSettingsPublishingSites();
        applyProfileToPubModal(entry);
        if (plat === "wordpress") applyWpProfileToForm(entry);
        if (plat === "wordpress" && typeof window.__cauLoadSites === "function") {
            window.__cauLoadSites().catch(() => {});
        }
        updatePubPlatformTabCounts();
        renderWpProfilesSavedList();
        try {
            renderConnectedSitesPanel();
        } catch (_) {}
        const okMsg =
            plat === "wordpress"
                ? idx >= 0
                    ? "Đã cập nhật site WordPress (trình duyệt + Cài đặt)."
                    : "Đã thêm site WordPress mới (trình duyệt + Cài đặt)."
                : idx >= 0
                  ? `Đã cập nhật site ${PUB_PLATFORM_LABELS[plat] || plat}.`
                  : `Đã thêm site ${PUB_PLATFORM_LABELS[plat] || plat} mới.`;
        showWpProfileFeedback(serverSync.ok ? okMsg : `Trình duyệt: OK. Server: ${serverSync.message}`, serverSync.ok ? "ok" : "err");
        if (msg && serverSync.ok) {
            msg.textContent =
                plat === "wordpress"
                    ? idx >= 0
                        ? "Đã cập nhật kết nối đăng bài WordPress."
                        : "Đã thêm site đăng bài WordPress — các site cũ vẫn giữ nguyên."
                    : idx >= 0
                      ? `Đã cập nhật site ${PUB_PLATFORM_LABELS[plat] || plat}.`
                      : `Đã thêm site ${PUB_PLATFORM_LABELS[plat] || plat}.`;
        }
        _wpProfilesAddNewMode = false;
        syncWpProfilesFocusUi();
        if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = oldSaveLabel;
        }
    };
    const btnWpProfileSaveConnectEl = byId("btnWpProfileSaveConnect");
    if (btnWpProfileSaveConnectEl) {
        btnWpProfileSaveConnectEl.addEventListener("click", () => {
            void saveSiteProfileFromModal();
        });
    }
    const btnWpProfileTestConnEl = byId("btnWpProfileTestConn");
    if (btnWpProfileTestConnEl) {
        btnWpProfileTestConnEl.addEventListener("click", async () => {
            const plat = currentPubPlatform;
            btnWpProfileTestConnEl.disabled = true;
            showWpProfileFeedback(plat === "haravan" ? "Testing connection…" : "Đang kiểm tra kết nối…", "info");
            try {
                if (plat === "wordpress") {
                    const b = profilePreviewBody();
                    if (!b || !b.url || !b.username || !b.app_password) {
                        showWpProfileFeedback("Nhập đủ URL, username và Application password.", "err");
                        return;
                    }
                    const { r, data } = await postPubApi(pubApiPaths.wordpress.test, b);
                    if (!r.ok) {
                        let err = fmtApiDetail(data.detail) || data.message || ("HTTP " + r.status);
                        if (r.status === 401 || r.status === 403) {
                            err = "Vui lòng đăng nhập (Cài đặt → Tài khoản) rồi thử lại.";
                        } else if (r.status === 404) {
                            err = "API kiểm tra kết nối chưa sẵn sàng — hãy khởi động lại run.bat rồi thử lại.";
                        }
                        showWpProfileFeedback(err, "err");
                        return;
                    }
                    const m = data.message || (data.ok ? "Kết nối WordPress thành công." : "Không kết nối được.");
                    showWpProfileFeedback(m, data.ok ? "ok" : "err");
                } else if (plat === "haravan") {
                    const b = profilePreviewBody();
                    if (!b || !b.private_token) {
                        showWpProfileFeedback("Nhập Private Token để kiểm tra.", "err");
                        return;
                    }
                    const { r, data } = await postPubApi(pubApiPaths.haravan.test, b);
                    if (!r.ok) {
                        const err = fmtApiDetail(data.detail) || data.message || ("HTTP " + r.status);
                        showWpProfileFeedback(r.status === 404 ? "API chưa sẵn sàng — khởi động lại run.bat." : err, "err");
                        return;
                    }
                    showWpProfileFeedback(data.message || (data.ok ? "Connection OK." : "Connection failed."), data.ok ? "ok" : "err");
                }
            } catch (_) {
                showWpProfileFeedback("Lỗi mạng khi kiểm tra kết nối.", "err");
            } finally {
                btnWpProfileTestConnEl.disabled = false;
            }
        });
    }
    const btnWpProfileSyncPostsEl = byId("btnWpProfileSyncPosts");
    if (btnWpProfileSyncPostsEl) {
        btnWpProfileSyncPostsEl.addEventListener("click", async () => {
            const plat = currentPubPlatform;
            btnWpProfileSyncPostsEl.disabled = true;
            showWpProfileFeedback(plat === "haravan" ? "Syncing blogs…" : "Đang đồng bộ bài viết…", "info");
            try {
                if (plat === "wordpress") {
                    const b = profilePreviewBody();
                    if (!b || !b.url || !b.username || !b.app_password) {
                        showWpProfileFeedback("Nhập đủ URL, username và Application password.", "err");
                        return;
                    }
                    const { r, data } = await postPubApi(pubApiPaths.wordpress.sync, b);
                    if (!r.ok) {
                        const err = fmtApiDetail(data.detail) || data.message || ("HTTP " + r.status);
                        showWpProfileFeedback(r.status === 404 ? "API đồng bộ chưa sẵn sàng — khởi động lại run.bat." : err, "err");
                        return;
                    }
                    showWpProfileFeedback(data.message || "Đồng bộ xong.", data.ok ? "ok" : "err");
                } else if (plat === "haravan") {
                    const b = profilePreviewBody();
                    if (!b || !b.private_token) {
                        showWpProfileFeedback("Nhập Private Token để đồng bộ.", "err");
                        return;
                    }
                    const { r, data } = await postPubApi(pubApiPaths.haravan.sync, b);
                    if (!r.ok) {
                        const err = fmtApiDetail(data.detail) || data.message || ("HTTP " + r.status);
                        showWpProfileFeedback(r.status === 404 ? "API chưa sẵn sàng — khởi động lại run.bat." : err, "err");
                        return;
                    }
                    showWpProfileFeedback(data.message || "Sync done.", data.ok ? "ok" : "err");
                }
            } catch (_) {
                showWpProfileFeedback("Lỗi mạng khi đồng bộ.", "err");
            } finally {
                btnWpProfileSyncPostsEl.disabled = false;
            }
        });
    }
    if (wpProfilesModalEl) {
        wpProfilesModalEl.querySelectorAll(".pub-platform-tab[data-platform]").forEach((btn) => {
            btn.addEventListener("click", () => setPubPlatformTab(btn.getAttribute("data-platform")));
        });
    }
    const btnWpProfilesCloseEl = byId("btnWpProfilesClose");
    if (btnWpProfilesCloseEl) btnWpProfilesCloseEl.addEventListener("click", closeWpProfilesModal);
    const btnWpProfilesCancelEl = byId("btnWpProfilesCancel");
    if (btnWpProfilesCancelEl) btnWpProfilesCancelEl.addEventListener("click", closeWpProfilesModal);
    if (wpProfilesBackdropEl) {
        wpProfilesBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === wpProfilesBackdropEl) closeWpProfilesModal();
        });
    }
    const siteArticlesBackdropEl = byId("siteArticlesBackdrop");
    const siteArticlesModalEl = byId("siteArticlesModal");
    function closeSiteArticlesModal() {
        if (siteArticlesBackdropEl) siteArticlesBackdropEl.classList.remove("open");
        if (siteArticlesModalEl) {
            siteArticlesModalEl.classList.remove("open");
            siteArticlesModalEl.setAttribute("aria-hidden", "true");
        }
    }
    const btnSiteArticlesCloseEl = byId("btnSiteArticlesClose");
    if (btnSiteArticlesCloseEl) btnSiteArticlesCloseEl.addEventListener("click", closeSiteArticlesModal);
    if (siteArticlesBackdropEl) {
        siteArticlesBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === siteArticlesBackdropEl) closeSiteArticlesModal();
        });
    }
    let _siteArticlesFilter = "all";
    let _siteArticlesHighlightId = "";
    const siteArticlesSearchEl = byId("siteArticlesSearch");
    const btnSiteArticlesAddEl = byId("btnSiteArticlesAdd");
    const btnSiteArticlesRefreshEl = byId("btnSiteArticlesRefresh");
    const siteArticlesSelectAllEl = byId("siteArticlesSelectAll");
    if (siteArticlesSearchEl) {
        siteArticlesSearchEl.addEventListener("input", () => {
            try {
                renderSiteArticlesBoard();
            } catch (_) {}
        });
    }
    if (btnSiteArticlesAddEl) {
        btnSiteArticlesAddEl.addEventListener("click", () => {
            const ctx = _siteArticlesModalCtx;
            if (ctx && ctx.base) {
                const tgEl = byId("targetWebsite");
                const wpEl = byId("wpUrl");
                if (tgEl) tgEl.value = ctx.base;
                if (wpEl) wpEl.value = ctx.base;
                try {
                    rememberTargetWebsite(ctx.base);
                    rememberWpUrl(ctx.base);
                } catch (_) {}
                _projectsSiteFilterBase = normalizeTargetBase(ctx.base) || normalizeWpUrl(ctx.base) || "";
                projectPage = 1;
                try {
                    renderProjects();
                } catch (_) {}
            }
            closeSiteArticlesModal();
            if (msg) msg.textContent = "Tạo bài mới — điền form và bấm Lưu dự án.";
        });
    }
    if (btnSiteArticlesRefreshEl) {
        btnSiteArticlesRefreshEl.addEventListener("click", async () => {
            try {
                await refreshProjects(false);
            } catch (_) {}
            try {
                renderSiteArticlesBoard();
            } catch (_) {}
        });
    }
    const btnSiteArticlesGenThumbsEl = byId("btnSiteArticlesGenThumbs");
    if (btnSiteArticlesGenThumbsEl) {
        btnSiteArticlesGenThumbsEl.addEventListener("click", () => {
            void generateMissingThumbnailsForBoard();
        });
    }
    if (siteArticlesSelectAllEl) {
        siteArticlesSelectAllEl.addEventListener("change", () => {
            const on = !!siteArticlesSelectAllEl.checked;
            const box = byId("siteArticlesModalList");
            if (!box) return;
            box.querySelectorAll('input[type="checkbox"][data-article-row]').forEach((cb) => {
                cb.checked = on;
            });
        });
    }
    const deleteConfirmOverlayEl = byId("deleteConfirmOverlay");
    const deleteConfirmBackdropEl = byId("deleteConfirmBackdrop");
    let _deleteConfirmResolve = null;
    let _siteArticlesModalCtx = { base: "", label: "" };
    const mountDeleteConfirmOverlay = () => {
        if (!deleteConfirmOverlayEl) return;
        deleteConfirmOverlayEl.style.setProperty("position", "fixed", "important");
        deleteConfirmOverlayEl.style.setProperty("inset", "0", "important");
        deleteConfirmOverlayEl.style.setProperty("z-index", "2147483000", "important");
        deleteConfirmOverlayEl.style.setProperty("display", "none", "important");
        deleteConfirmOverlayEl.style.setProperty("align-items", "center", "important");
        deleteConfirmOverlayEl.style.setProperty("justify-content", "center", "important");
        deleteConfirmOverlayEl.style.setProperty("padding", "24px", "important");
        deleteConfirmOverlayEl.style.setProperty("box-sizing", "border-box", "important");
        deleteConfirmOverlayEl.style.setProperty("pointer-events", "auto", "important");
        document.body.appendChild(deleteConfirmOverlayEl);
    };
    const closeDeleteConfirmModal = (confirmed) => {
        if (deleteConfirmOverlayEl) {
            deleteConfirmOverlayEl.classList.remove("open");
            deleteConfirmOverlayEl.setAttribute("aria-hidden", "true");
            deleteConfirmOverlayEl.style.setProperty("display", "none", "important");
        }
        document.body.classList.remove("ca-delete-confirm-open");
        if (_deleteConfirmResolve) {
            _deleteConfirmResolve(!!confirmed);
            _deleteConfirmResolve = null;
        }
    };
    const confirmDeleteDialog = (message, title) => {
        return new Promise((resolve) => {
            _deleteConfirmResolve = resolve;
            const tEl = byId("deleteConfirmTitle");
            const mEl = byId("deleteConfirmMessage");
            if (tEl) tEl.textContent = title || "Xác nhận xóa";
            if (mEl) {
                mEl.textContent =
                    message ||
                    "Bạn có chắc muốn xóa? Dữ liệu sẽ bị xóa vĩnh viễn và không thể khôi phục.";
            }
            mountDeleteConfirmOverlay();
            if (deleteConfirmOverlayEl) {
                deleteConfirmOverlayEl.classList.add("open");
                deleteConfirmOverlayEl.setAttribute("aria-hidden", "false");
                deleteConfirmOverlayEl.style.setProperty("display", "flex", "important");
            }
            document.body.classList.add("ca-delete-confirm-open");
        });
    };
    const btnDeleteConfirmCancelEl = byId("btnDeleteConfirmCancel");
    if (btnDeleteConfirmCancelEl) btnDeleteConfirmCancelEl.addEventListener("click", () => closeDeleteConfirmModal(false));
    const btnDeleteConfirmOkEl = byId("btnDeleteConfirmOk");
    if (btnDeleteConfirmOkEl) btnDeleteConfirmOkEl.addEventListener("click", () => closeDeleteConfirmModal(true));
    if (deleteConfirmBackdropEl) {
        deleteConfirmBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === deleteConfirmBackdropEl) closeDeleteConfirmModal(false);
        });
    }
    mountDeleteConfirmOverlay();
    document.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        if (deleteConfirmOverlayEl && deleteConfirmOverlayEl.classList.contains("open")) {
            closeDeleteConfirmModal(false);
            return;
        }
        if (articleDetailModalEl && articleDetailModalEl.classList.contains("open")) {
            closeArticleDetailModal();
            return;
        }
        if (siteArticlesModalEl && siteArticlesModalEl.classList.contains("open")) {
            closeSiteArticlesModal();
            return;
        }
        if (!wpProfilesModalEl || !wpProfilesModalEl.classList.contains("open")) return;
        closeWpProfilesModal();
    });
    document.querySelectorAll(".js-open-wp-profiles").forEach((btn) => {
        btn.addEventListener("click", () => {
            const filtered = String(_projectsSiteFilterBase || "").trim();
            if (filtered) {
                void openWpProfilesModalForSite(filtered, { wp: true, target: true });
                return;
            }
            openWpProfilesModal({ clearCredentials: true });
        });
    });
    const collectConnectedSites = () => {
        const keyTo = new Map();
        const order = [];
        const pushUrl = (raw, source) => {
            const base = normalizeWpUrl(raw) || normalizeTargetBase(raw);
            if (!base) return;
            const key = base.toLowerCase();
            let o = keyTo.get(key);
            if (!o) {
                o = { url: base, wp: false, target: false, platforms: [] };
                keyTo.set(key, o);
                order.push(key);
            }
            if (source === "wp") o.wp = true;
            if (source === "tg") o.target = true;
        };
        const addSavedPlatform = (raw, plat) => {
            const base = normalizeWpUrl(raw) || normalizeTargetBase(raw);
            if (!base) return;
            const key = base.toLowerCase();
            let o = keyTo.get(key);
            if (!o) {
                o = { url: base, wp: false, target: false, platforms: [] };
                keyTo.set(key, o);
                order.push(key);
            }
            const tag = normalizePlatform(plat);
            if (tag === "wordpress") {
                o.wp = true;
            } else {
                if (!o.platforms.includes(tag)) o.platforms.push(tag);
                o.target = true;
            }
        };
        readSiteProfiles().forEach((p) => addSavedPlatform(profileSiteUrl(p), p.platform));
        settingsPublishingSitesFlat.forEach((s) => addSavedPlatform(s.url, s.platform));
        if (getAuthUserId() <= 0) {
            readWpUrlHistory().forEach((u) => pushUrl(u, "wp"));
            readTargetHistory().forEach((u) => pushUrl(u, "tg"));
        }
        return order.map((k) => keyTo.get(k)).filter(Boolean);
    };
    const removeConnectedSite = async (siteUrl) => {
        const key = connectedSiteKey(siteUrl);
        if (!key) return false;
        const hostLabel = connectedSiteHostLabel(siteUrl);
        const ok = await confirmDeleteDialog(
            `Bạn có chắc muốn gỡ «${hostLabel}» khỏi danh sách website đã kết nối?\nCấu hình đăng bài (trình duyệt + Cài đặt) cho URL này sẽ bị xóa. Các dự án Content AI đã lưu vẫn giữ nguyên.`,
            "Xác nhận xóa website"
        );
        if (!ok) return false;
        const matchUrl = (raw) => connectedSiteKey(raw) === key;
        persistSiteProfiles(readSiteProfiles().filter((p) => !matchUrl(profileSiteUrl(p))));
        writeWpUrlHistory(readWpUrlHistory().filter((u) => !matchUrl(u)));
        writeTargetHistory(readTargetHistory().filter((u) => !matchUrl(u)));
        const serverIds = settingsPublishingSitesFlat.filter((s) => matchUrl(s.url) && s.id).map((s) => s.id);
        for (const sid of serverIds) {
            try {
                await fetch(`/api/settings/publishing-sites/${encodeURIComponent(sid)}`, {
                    method: "DELETE",
                    headers: authHeaders(),
                });
            } catch (_) {}
        }
        await fetchSettingsPublishingSites();
        if (_projectsSiteFilterBase && connectedSiteKey(_projectsSiteFilterBase) === key) {
            _projectsSiteFilterBase = "";
            projectPage = 1;
            try {
                await refreshProjects(false);
            } catch (_) {}
        }
        try {
            renderWpUrlHistory();
        } catch (_) {}
        try {
            renderTargetHistory();
        } catch (_) {}
        try {
            updatePubPlatformTabCounts();
        } catch (_) {}
        try {
            renderWpProfilesSavedList();
        } catch (_) {}
        try {
            renderConnectedSitesPanel();
        } catch (_) {}
        if (msg) msg.textContent = `Đã gỡ ${hostLabel} khỏi danh sách kết nối.`;
        return true;
    };
    const applyConnectedSiteSelection = async (it, opts = {}) => {
        const o = opts || {};
        const u = String((it && it.url) || "").trim();
        if (!u) return;
        const wpEl = byId("wpUrl");
        const tgEl = byId("targetWebsite");
        if (wpEl) wpEl.value = u;
        if (tgEl) tgEl.value = u;
        rememberWpUrl(u);
        rememberTargetWebsite(u);
        _projectsSiteFilterBase = normalizeTargetBase(u) || normalizeWpUrl(u) || "";
        projectPage = 1;
        try {
            await refreshProjects(false);
        } catch (_) {}
        try {
            renderProjects();
            renderConnectedSitesPanel();
            saveFormState();
        } catch (_) {}
        if (o.openArticles) {
            let hostLabel = u;
            try {
                hostLabel = new URL(u).host || u;
            } catch (_) {}
            await openSiteArticlesModal(_projectsSiteFilterBase, hostLabel, {
                resetFilter: true,
                clearSearch: true,
            });
        }
    };
    const connectedSitesRenderTargets = () =>
        [
            { wrap: byId("contentAiConnectedSitesListSidebar"), hint: null },
            { wrap: byId("contentAiConnectedSitesListMain"), hint: byId("hintConnectedSitesMain") },
        ].filter((t) => t.wrap);
    const appendConnectedSiteItem = (wrap, it, activeKeys, filterKey) => {
            const itemWrap = document.createElement("div");
            itemWrap.className = "connected-site-item";
            itemWrap.setAttribute("role", "listitem");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "connected-site-row";
            const key = String(it.url).toLowerCase();
            if (activeKeys.has(key) || (filterKey && key === filterKey)) btn.classList.add("active");
            const dot = document.createElement("span");
            dot.className = "dot";
            const body = document.createElement("span");
            body.className = "connected-site-body";
            const host = document.createElement("div");
            host.className = "connected-site-host";
            try {
                const h = new URL(it.url).host;
                host.textContent = h || it.url;
            } catch (_) {
                host.textContent = it.url;
            }
            const badges = document.createElement("div");
            badges.className = "connected-site-badges";
            if (it.wp) {
                const b = document.createElement("span");
                b.className = "connected-site-badge wp";
                b.textContent = "WP";
                badges.appendChild(b);
            }
            if (it.target || it.wp || (it.platforms && it.platforms.length)) {
                const b = document.createElement("button");
                b.type = "button";
                b.className = "connected-site-badge edit";
                b.textContent = "Edit";
                b.title = "Chỉnh sửa thông tin site đăng bài";
                b.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    void openWpProfilesModalForSite(it.url, it);
                });
                badges.appendChild(b);
            }
            const platLbl = { shopify: "Shopify", haravan: "Haravan", webcake: "Webcake" };
            (it.platforms || []).forEach((pl) => {
                const b = document.createElement("span");
                b.className = `connected-site-badge plat plat-${pl}`;
                b.textContent = platLbl[pl] || pl;
                badges.appendChild(b);
            });
            body.appendChild(host);
            body.appendChild(badges);
            btn.appendChild(dot);
            btn.appendChild(body);
            btn.title = it.url;
            btn.addEventListener("click", async () => {
                await applyConnectedSiteSelection(it, { openArticles: true });
            });
            const delSiteBtn = document.createElement("button");
            delSiteBtn.type = "button";
            delSiteBtn.className = "connected-site-del-btn";
            delSiteBtn.textContent = "Xóa";
            delSiteBtn.title = `Gỡ ${connectedSiteHostLabel(it.url)} khỏi danh sách`;
            delSiteBtn.addEventListener("click", async (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                await removeConnectedSite(it.url);
            });
            itemWrap.appendChild(btn);
            itemWrap.appendChild(delSiteBtn);
            wrap.appendChild(itemWrap);
    };
    const renderConnectedSitesPanel = () => {
        const targets = connectedSitesRenderTargets();
        if (!targets.length) return;
        const items = collectConnectedSites();
        const wpNorm = normalizeWpUrl(byId("wpUrl").value.trim());
        const tgNorm = normalizeTargetBase(byId("targetWebsite").value.trim());
        const activeKeys = new Set(
            [wpNorm, tgNorm].filter(Boolean).map((u) => u.toLowerCase()),
        );
        const emptyHint =
            "Chưa có site trong lịch sử. Đăng bài WP hoặc nhập Target website — site sẽ lưu và hiện ở đây.";
        const filledHint =
            "Site từ Cài đặt → Xuất bản xuất hiện ở đây. Bấm website để xem bài — nút Xóa để gỡ site khỏi danh sách.";
        const filterKey = String(_projectsSiteFilterBase || "").toLowerCase();
        targets.forEach(({ wrap, hint }) => {
            wrap.innerHTML = "";
            if (hint) hint.textContent = items.length ? filledHint : emptyHint;
        });
        if (!items.length) return;
        const SIDEBAR_SITE_LIMIT = 3;
        targets.forEach(({ wrap }) => {
            const isSidebar = wrap && wrap.id === "contentAiConnectedSitesListSidebar";
            if (isSidebar) {
                wrap.classList.remove("connected-sites-list--scroll");
            } else {
                wrap.classList.toggle("connected-sites-list--scroll", items.length > SIDEBAR_SITE_LIMIT);
            }
            const slice = isSidebar ? items.slice(0, SIDEBAR_SITE_LIMIT) : items;
            slice.forEach((it) => appendConnectedSiteItem(wrap, it, activeKeys, filterKey));
        });
    };
    const setDetectedIntentDebug = (intent) => {
        const el = byId("hint-detected-intent");
        if (!el) return;
        const v = String(intent || "").trim();
        el.textContent = v ? `Intent debug: ${v}` : "Intent debug: -";
    };
    const buildContentAiBillingFlags = (ctx) => {
        const wc = Number((ctx && ctx.target_word_count) || parseTargetWordCount() || 1000);
        const outlineEl = byId("outlineContent");
        const hasOutline = outlineEl && String(outlineEl.value || "").trim().length > 40;
        const plain = String((ctx && ctx.content) || getContentValue() || "")
            .replace(/<[^>]+>/g, " ")
            .trim();
        const hasContent = plain.length >= 80;
        let imageSource = "none";
        try {
            const srcEl = byId("autoInsertImageSource");
            const autoEl = byId("autoInsertImagesAfterWrite");
            const raw = srcEl ? String(srcEl.value || "none").trim() : "none";
            if (autoEl && autoEl.checked && (raw === "google" || raw === "ai")) {
                imageSource = raw;
            }
        } catch (_) {}
        const pid =
            typeof activeProjectId !== "undefined" && activeProjectId
                ? String(activeProjectId)
                : null;
        return {
            include_research: false,
            include_outline: !hasOutline,
            include_internal_links: false,
            include_rewrite: hasContent,
            image_source: imageSource,
            project_id: pid,
            article_title: (ctx && ctx.title) || byId("title").value.trim(),
            primary_keyword: (ctx && ctx.primary_keyword) || byId("primaryKeyword").value.trim(),
        };
    };
    const buildContentAiQuoteBody = (field, ctx) => ({
        field: field || "content",
        title: (ctx && ctx.title) || "",
        content: (ctx && ctx.content) || "",
        target_website: (ctx && ctx.target_website) || "",
        slug: (ctx && ctx.slug) || "",
        tags: (ctx && ctx.tags) || "",
        meta_description: (ctx && ctx.meta_description) || "",
        primary_keyword: (ctx && ctx.primary_keyword) || "",
        secondary_keywords: (ctx && ctx.secondary_keywords) || "",
        outline_content: (ctx && ctx.outline_content) || "",
        target_word_count: (ctx && ctx.target_word_count) || parseTargetWordCount(),
        target_word_count_mode: (ctx && ctx.target_word_count_mode) || getTargetWordCountMode(),
        billing: buildContentAiBillingFlags(ctx),
    });
    const confirmContentAiCredit = async (field, ctx) => {
        if (field !== "content") return true;
        if (!window.DigiSeoConfirmCredit || !window.DigiSeoCreditActions) return true;
        const preset = window.DigiSeoCreditActions.contentArticleQuote(buildContentAiQuoteBody(field, ctx));
        const ok = await window.DigiSeoConfirmCredit(preset);
        if (!ok) throw new Error("Đã hủy.");
        return true;
    };
    const CONTENT_AI_BRIEF_SYNC_FIELDS = new Set([
        "title", "meta_description", "slug", "tags", "primary_keyword", "secondary_keywords", "outline_content",
    ]);
    let _suggestChain = Promise.resolve();
    const _enqueueSuggest = (fn) => {
        const run = _suggestChain.then(() => fn());
        _suggestChain = run.catch(() => {});
        return run;
    };
    const _briefSuggestParallel = new Set([
        "title", "meta_description", "slug", "tags", "primary_keyword", "secondary_keywords",
    ]);
    const _fetchSuggestionCore = async (field, ctx, options = {}) => {
        if (!options.skipConfirm) {
            await confirmContentAiCredit(field, ctx);
        }
        const billing = buildContentAiBillingFlags(ctx);
        const reqId = "cas_" + Date.now() + "_" + Math.random().toString(36).slice(2, 10);
        const preferSync = options.sync === true || CONTENT_AI_BRIEF_SYNC_FIELDS.has(field) || field === "content";

        const postSuggest = async (syncMode) => {
            const q = syncMode ? "&sync=1" : "";
            return fetch(`/content-ai/suggest?ts=${Date.now()}&llm=1${q}`, {
                method: "POST",
                headers: Object.assign({}, authJsonHeaders(), { "X-Request-Id": reqId }),
                body: JSON.stringify({ field, ...ctx, billing }),
                signal: options.signal,
            });
        };

        let res;
        let data;
        try {
            res = await postSuggest(preferSync);
            data = await res.json().catch(() => ({}));
        } catch (e) {
            if (e && e.name === "AbortError") {
                if (_contentWriteSession && _contentWriteSession.userAborted) throw e;
                throw new Error("Kết nối viết bài bị đóng.");
            }
            throw e;
        }
        if (!res.ok) {
            if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
            }
            const errMsg = _contentAiErrMessage(data, res);
            if (window.ContentAiErrors && window.ContentAiErrors.showIfLlmUnavailable) {
                window.ContentAiErrors.showIfLlmUnavailable(data, errMsg);
            }
            throw new Error(errMsg);
        }

        const suggestHasFinalValue = (payload) => {
            if (!payload || payload.value == null || payload.value === "") return false;
            if (!payload.job_id) return true;
            const st = String(payload.state || "").toUpperCase();
            return st === "COMPLETED" || st === "SUCCESS" || payload.sync === true || payload.sync_fallback === true;
        };
        if (suggestHasFinalValue(data)) {
            if (data.provider_fallback_notice) showLlmFallbackNotice(data.provider_fallback_notice);
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
                void window.ContentAiUsage.refresh();
            }
            return {
                value: data.value || "",
                detected_intent: data.detected_intent || "",
                word_count_target: data.word_count_target,
                word_count_actual: data.word_count_actual,
                word_count_ok: data.word_count_ok,
                skip_client_enforce: data.skip_client_enforce,
                validated_word_count: data.validated_word_count,
                actual_word_count: data.actual_word_count,
                word_count_status: data.word_count_status,
            };
        }

        let final = data;
        if (data && data.job_id && data.poll_url) {
            const pollUrl = data.poll_url;
            let done = false;
            let poll404 = false;
            const pollMs = 600;
            for (let i = 0; i < 600; i++) {
                if (options.signal && options.signal.aborted) {
                    if (_contentWriteSession && _contentWriteSession.userAborted) {
                        throw new DOMException("Aborted", "AbortError");
                    }
                    throw new Error("Kết nối viết bài bị đóng.");
                }
                await new Promise((r) => setTimeout(r, pollMs));
                const pr = await fetch(pollUrl, { headers: authJsonHeaders(), signal: options.signal });
                const st = await pr.json().catch(() => ({}));
                if (pr.status === 404) {
                    poll404 = true;
                    break;
                }
                if (!pr.ok) continue;
                const state = String(st.state || "");
                if (state === "QUEUED" || state === "PENDING" || state === "RUNNING") continue;
                if (state === "COMPLETED" || state === "SUCCESS") {
                    final = st;
                    done = true;
                    break;
                }
                if (state === "FAILED" || state === "ERROR") {
                    throw new Error(st.error || st.message || "Gợi ý AI thất bại.");
                }
            }
            if (!done && poll404) {
                res = await fetch(`/content-ai/suggest?ts=${Date.now()}&llm=1&sync=1`, {
                    method: "POST",
                    headers: Object.assign({}, authJsonHeaders(), { "X-Request-Id": reqId + "_sync" }),
                    body: JSON.stringify({ field, ...ctx, billing }),
                    signal: options.signal,
                });
                data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    throw new Error(_contentAiErrMessage(data, res) || "Không tìm thấy job gợi ý AI.");
                }
                final = data;
                done = !!final.value;
            }
            if (!done) throw new Error("Hết thời gian chờ job gợi ý AI.");
            if (final && final.provider_fallback_notice) showLlmFallbackNotice(final.provider_fallback_notice);
        }
        if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
            void window.ContentAiUsage.refresh();
        }
        return {
            value: (final && final.value) ? final.value : "",
            detected_intent: (final && final.detected_intent) ? final.detected_intent : "",
            word_count_target: final.word_count_target,
            word_count_actual: final.word_count_actual,
            word_count_ok: final.word_count_ok,
            skip_client_enforce: final.skip_client_enforce,
            validated_word_count: final.validated_word_count,
            actual_word_count: final.actual_word_count,
            word_count_status: final.word_count_status,
        };
    };
    const fetchSuggestion = (field, ctx, options = {}) =>
        _briefSuggestParallel.has(field)
            ? _fetchSuggestionCore(field, ctx, options)
            : _enqueueSuggest(() => _fetchSuggestionCore(field, ctx, options));
    const caEditorWriteBar = byId("caEditorWriteBar");
    const caEditorWriteStatus = byId("caEditorWriteStatus");
    const caEditorWriteError = byId("caEditorWriteError");
    const btnStopContentWrite = byId("btnStopContentWrite");
    const caStickyCreateBtn = byId("caStickyCreateContent");
    const _contentWriteSession = {
        controller: null,
        reader: null,
        progressTimer: null,
        active: false,
        contentVisible: false,
        userAborted: false,
    };
    const _CREATE_CONTENT_LABEL = "Tạo content";
    const _CREATE_CONTENT_BUSY_LABEL = "Đang viết...";

    const _resetContentWriteUi = () => {
        if (_contentWriteSession.progressTimer) {
            window.clearInterval(_contentWriteSession.progressTimer);
            _contentWriteSession.progressTimer = null;
        }
        _contentWriteSession.active = false;
        _contentWriteSession.controller = null;
        _contentWriteSession.reader = null;
        _contentWriteSession.contentVisible = false;
        _setCreateContentButtonsBusy(false);
        _hideEditorWriteBar();
    };
    const _stopContentWrite = (fromUser) => {
        const s = _contentWriteSession;
        if (fromUser) s.userAborted = true;
        s.active = false;
        s.contentVisible = false;
        if (s.progressTimer) {
            window.clearInterval(s.progressTimer);
            s.progressTimer = null;
        }
        if (s.reader) {
            try { void s.reader.cancel(); } catch (_) {}
            s.reader = null;
        }
        if (s.controller) {
            try { s.controller.abort(); } catch (_) {}
            s.controller = null;
        }
        _setCreateContentButtonsBusy(false);
        _hideEditorWriteBar();
    };
    const _beginContentWriteSession = () => {
        if (
            _contentWriteSession.active
            && _contentWriteSession.controller
            && !_contentWriteSession.controller.signal.aborted
            && !_contentWriteSession.userAborted
        ) {
            return _contentWriteSession.controller.signal;
        }
        _stopContentWrite(false);
        const controller = new AbortController();
        _contentWriteSession.controller = controller;
        _contentWriteSession.active = true;
        _contentWriteSession.contentVisible = false;
        _contentWriteSession.userAborted = false;
        return controller.signal;
    };
    const _getContentWriteSignal = () => {
        const c = _contentWriteSession.controller;
        return c ? c.signal : null;
    };
    const _assertContentWriteActive = (signal) => {
        if (_contentWriteSession.userAborted) throw new DOMException("Aborted", "AbortError");
        if (signal && signal.aborted) {
            if (_contentWriteSession.userAborted) throw new DOMException("Aborted", "AbortError");
            throw new Error("Kết nối viết bài bị đóng.");
        }
        if (!_contentWriteSession.active) {
            throw new Error("WRITE_SESSION_ENDED");
        }
    };
    const _raceAbort = (signal, promise) => {
        if (!signal) return promise;
        if (signal.aborted) {
            return Promise.reject(
                _contentWriteSession.userAborted
                    ? new DOMException("Aborted", "AbortError")
                    : new Error("Kết nối viết bài bị đóng.")
            );
        }
        return new Promise((resolve, reject) => {
            const onAbort = () => reject(
                _contentWriteSession.userAborted
                    ? new DOMException("Aborted", "AbortError")
                    : new Error("Kết nối viết bài bị đóng.")
            );
            signal.addEventListener("abort", onAbort, { once: true });
            promise.then(
                (v) => { signal.removeEventListener("abort", onAbort); resolve(v); },
                (e) => { signal.removeEventListener("abort", onAbort); reject(e); },
            );
        });
    };
    const _startWriteProgressPulse = (signal) => {
        let tick = 0;
        if (_contentWriteSession.progressTimer) {
            window.clearInterval(_contentWriteSession.progressTimer);
        }
        _contentWriteSession.progressTimer = window.setInterval(() => {
            if (!_contentWriteSession.active || (signal && signal.aborted)) return;
            tick += 1;
            const dots = ".".repeat((tick % 3) + 1);
            _showEditorWriteBar(`AI đang viết bài${dots}`);
        }, 900);
    };
    const _rejectAfterMs = (ms, signal, err) => new Promise((_, reject) => {
        const t = window.setTimeout(() => reject(err || new Error("TIMEOUT")), ms);
        if (signal) {
            signal.addEventListener("abort", () => {
                window.clearTimeout(t);
                reject(
                    _contentWriteSession.userAborted
                        ? new DOMException("Aborted", "AbortError")
                        : new Error("Kết nối viết bài bị đóng.")
                );
            }, { once: true });
        }
    });

    const _setCreateContentButtonsBusy = (busy) => {
        window.__caCreateContentBusy = !!busy;
        const dupBlocked = !!(window.ContentAiDuplicate && window.ContentAiDuplicate.isBlocked());
        const label = busy ? _CREATE_CONTENT_BUSY_LABEL : _CREATE_CONTENT_LABEL;
        if (btnCreateContent) {
            btnCreateContent.disabled = busy || dupBlocked;
            btnCreateContent.textContent = label;
        }
        if (caStickyCreateBtn) {
            caStickyCreateBtn.disabled = busy || dupBlocked;
            caStickyCreateBtn.textContent = label;
        }
    };
    const _showContentWriteOverlay = (text) => {
        const ov = byId("caContentWriteOverlay");
        const lab = byId("caContentWriteOverlayLabel");
        const stage = byId("caContentEditorStage");
        if (ov) {
            ov.hidden = false;
            ov.setAttribute("aria-hidden", "false");
        }
        if (lab) lab.textContent = String(text || "Đang viết bài…");
        if (stage) stage.classList.add("is-writing");
    };
    const _hideContentWriteOverlay = (markContentVisible) => {
        const ov = byId("caContentWriteOverlay");
        const stage = byId("caContentEditorStage");
        if (ov) {
            ov.hidden = true;
            ov.setAttribute("aria-hidden", "true");
        }
        if (stage) stage.classList.remove("is-writing");
        if (markContentVisible) _contentWriteSession.contentVisible = true;
    };
    const _showEditorWriteBar = (text) => {
        if (caEditorWriteBar) caEditorWriteBar.hidden = false;
        const label = String(text || "Đang viết bài…");
        if (caEditorWriteStatus) caEditorWriteStatus.textContent = label;
        const low = label.toLowerCase();
        const revealContent =
            _contentWriteSession.contentVisible ||
            low.startsWith("hoàn thành") ||
            low.startsWith("đang hiển thị");
        if (revealContent) {
            _hideContentWriteOverlay(true);
        } else if (!_contentWriteSession.userAborted) {
            _showContentWriteOverlay(label);
        }
    };
    const _hideEditorWriteBar = () => {
        if (caEditorWriteBar) caEditorWriteBar.hidden = true;
        _hideContentWriteOverlay(false);
    };
    const _clearEditorWriteError = () => {
        if (caEditorWriteError) {
            caEditorWriteError.textContent = "";
            caEditorWriteError.hidden = true;
        }
    };
    const _showEditorWriteError = (msg) => {
        if (!caEditorWriteError) return;
        const v = String(msg || "").trim();
        caEditorWriteError.textContent = v;
        caEditorWriteError.hidden = !v;
    };
    const _setContentHtmlLive = (html) => {
        const v = decodeHtmlEntitiesDeep(String(html || ""));
        const ta = byId("content");
        if (ta) ta.value = v;
        const element = byId("contentRender");
        if (element) {
            element.innerHTML = v;
            element.scrollTop = element.scrollHeight;
        }
        const ed = getEditorInstance();
        if (ed) {
            try {
                ed.setContent(v, { format: "html" });
                ed.save();
            } catch (_) {}
        }
        syncPreviewFallback();
        try {
            if (typeof updateContentStatsFromHtml === "function") {
                updateContentStatsFromHtml(v);
            }
        } catch (_) {}
    };
    const _sleepMs = (ms, signal) => new Promise((resolve, reject) => {
        const fail = () => reject(
            _contentWriteSession.userAborted
                ? new DOMException("Aborted", "AbortError")
                : new Error("Kết nối viết bài bị đóng.")
        );
        if (signal && signal.aborted) {
            fail();
            return;
        }
        const t = window.setTimeout(resolve, ms);
        if (signal) {
            signal.addEventListener("abort", () => {
                window.clearTimeout(t);
                fail();
            }, { once: true });
        }
    });
    const _splitHtmlTypingChunks = (html) => {
        const src = String(html || "");
        if (!src.trim()) return [];
        const re = /<\/(?:p|h[1-6]|li|ul|ol|blockquote|tr|div|section|article)>/gi;
        const chunks = [];
        let last = 0;
        let m;
        while ((m = re.exec(src))) {
            const end = m.index + m[0].length;
            chunks.push(src.slice(last, end));
            last = end;
        }
        if (last < src.length) chunks.push(src.slice(last));
        return chunks.filter((x) => String(x || "").trim());
    };
    const _typingEffectEnabled = () => {
        try {
            if (localStorage.getItem("content_ai_typing_off") === "1") return false;
        } catch (_) {}
        return true;
    };
    const _simulateHtmlTyping = async (html, signal, onProgress) => {
        const chunks = _splitHtmlTypingChunks(html);
        if (!chunks.length) {
            _setContentHtmlLive(html);
            return String(html || "");
        }
        let acc = "";
        const delayMs = Math.max(12, Math.min(48, Math.floor(12000 / Math.max(chunks.length, 1))));
        for (let i = 0; i < chunks.length; i++) {
            acc += chunks[i];
            _setContentHtmlLive(acc);
            if (onProgress) onProgress(Math.round(((i + 1) / chunks.length) * 100));
            await _sleepMs(delayMs, signal);
        }
        return acc;
    };
    const _caStreamLog = () => {};
    let _contentEditorAcc = "";
    const appendToContentEditor = (delta) => {
        const piece = String(delta || "");
        if (!piece) return;
        _contentEditorAcc += piece;
        _setContentHtmlLive(_contentEditorAcc);
        const el = byId("contentRender");
        if (el) {
            try { el.scrollTop = el.scrollHeight; } catch (_) {}
        }
        const tiny = getEditorInstance();
        if (tiny) {
            try {
                const iframe = tiny.getContainer && tiny.getContainer().querySelector("iframe");
                if (iframe && iframe.contentWindow) {
                    const doc = iframe.contentDocument || iframe.contentWindow.document;
                    const body = doc && doc.body;
                    if (body) body.scrollTop = body.scrollHeight;
                }
            } catch (_) {}
        }
    };
    const _contentTypingQueue = [];
    let _contentTypingPump = null;
    const _flushContentTypingQueue = async (signal) => {
        while (_contentTypingQueue.length > 0 || _contentTypingPump) {
            if (signal && signal.aborted) break;
            await _sleepMs(20, signal).catch(() => {});
        }
    };
    const _pumpContentTypingQueue = (signal) => {
        if (_contentTypingPump) return;
        _contentTypingPump = (async () => {
            try {
                while (_contentTypingQueue.length > 0) {
                    _assertContentWriteActive(signal);
                    const ch = _contentTypingQueue.shift();
                    appendToContentEditor(ch);
                    await _sleepMs(9, signal);
                }
            } catch (e) {
                if (e && e.name !== "AbortError") _caStreamLog("typing pump error", e);
            } finally {
                _contentTypingPump = null;
            }
        })();
    };
    const _enqueueStreamDelta = (delta, signal) => {
        const s = String(delta || "");
        if (!s) return;
        for (let i = 0; i < s.length; i++) _contentTypingQueue.push(s[i]);
        _pumpContentTypingQueue(signal);
    };
    const _parseDeltaSseBuffer = async (buffer, handlers) => {
        let buf = buffer;
        if (buf.indexOf("\r") >= 0) buf = buf.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        while (true) {
            const idx = buf.indexOf("\n\n");
            if (idx < 0) break;
            const raw = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const lines = raw.split("\n");
            let data = "";
            for (const ln of lines) {
                if (ln.startsWith("data:")) data += ln.slice(5).trim();
            }
            if (!data) continue;
            if (data === "[DONE]") {
                handlers.onDone();
                continue;
            }
            try {
                const obj = JSON.parse(data);
                if (obj && obj.code === "CONTENT_AI_LLM_UNAVAILABLE") {
                    handlers.onError(String(obj.message || (window.ContentAiErrors && window.ContentAiErrors.MESSAGE) || ""));
                } else if (obj && obj.ok === false && obj.message) {
                    handlers.onError(String(obj.message));
                } else if (obj && obj.error) handlers.onError(String(obj.error));
                else if (obj && obj.ping) {
                    if (handlers.onPing) handlers.onPing();
                }                 else if (obj && obj.replace_html) {
                    if (handlers.onReplaceHtml) await handlers.onReplaceHtml(String(obj.replace_html));
                } else if (
                    obj
                    && obj.word_count_target != null
                    && obj.word_count_actual != null
                    && handlers.onWordCountMeta
                ) {
                    handlers.onWordCountMeta(obj);
                } else if (obj && obj.delta) handlers.onDelta(String(obj.delta));
            } catch (_) {}
        }
        return buf;
    };
    const _readContentSuggestStream = async (ctx, signal, handlers, opts = {}) => {
        const billing = buildContentAiBillingFlags(ctx);
        const reqId = "cas_" + Date.now() + "_" + Math.random().toString(36).slice(2, 10);
        const runPollFallback = async () => {
            _caStreamLog("poll suggest job fallback");
            const result = await fetchSuggestion("content", ctx, { signal, skipConfirm: true });
            const html = String((result && result.value) || "");
            if (handlers.onReplaceHtml) {
                await handlers.onReplaceHtml(html);
            } else if (handlers.onDelta && html) {
                handlers.onDelta(html);
            }
            if (handlers.onWordCountMeta) {
                handlers.onWordCountMeta({
                    ...(result || {}),
                    word_count_target: (result && (result.word_count_target ?? result.validated_word_count)) ?? null,
                    word_count_actual: (result && (result.word_count_actual ?? result.actual_word_count)) ?? null,
                    word_count_ok: result && result.word_count_ok,
                    word_count_status: result && result.word_count_status,
                });
            }
            if (handlers.onDone) handlers.onDone();
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
                void window.ContentAiUsage.refresh();
            }
            return Boolean(html);
        };
        let res;
        try {
            res = await fetch(`/content-ai/suggest-stream?ts=${Date.now()}&llm=1`, {
                method: "POST",
                headers: Object.assign({}, authJsonHeaders(), {
                    "X-Request-Id": reqId,
                    Accept: "text/event-stream",
                }),
                body: JSON.stringify({ field: "content", ...ctx, billing }),
                signal,
            });
        } catch (e) {
            if (e && e.name === "AbortError") {
                if (_contentWriteSession.userAborted) throw e;
                throw new Error("Kết nối viết bài bị đóng.");
            }
            return runPollFallback();
        }
        const ctype = String((res && res.headers && res.headers.get("content-type")) || "");
        if (!res.ok || !res.body || ctype.indexOf("text/event-stream") < 0) {
            if (res && res.body) {
                try { await res.body.cancel(); } catch (_) {}
            }
            if (res && res.status >= 400 && res.status !== 404 && res.status !== 405) {
                const data = await res.json().catch(() => ({}));
                const errMsg = _contentAiErrMessage(data, res);
                if (handlers.onError) handlers.onError(errMsg);
                throw new Error(errMsg);
            }
            return runPollFallback();
        }
        const reader = res.body.getReader();
        _contentWriteSession.reader = reader;
        const decoder = new TextDecoder();
        let buffer = "";
        try {
            while (true) {
                _assertContentWriteActive(signal);
                const chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                buffer = await _parseDeltaSseBuffer(buffer, handlers);
            }
            if (buffer) buffer = await _parseDeltaSseBuffer(buffer + "\n\n", handlers);
        } finally {
            _contentWriteSession.reader = null;
            try { reader.releaseLock(); } catch (_) {}
        }
        if (handlers.onDone) handlers.onDone();
        if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
            void window.ContentAiUsage.refresh();
        }
        return true;
    };
    const writeContentToEditor = async (ctx, options = {}) => {
        const signal = options.signal || _beginContentWriteSession();

        await confirmContentAiCredit("content", ctx);

        _clearEditorWriteError();
        _setCreateContentButtonsBusy(true);
        _showEditorWriteBar("Đang kiểm tra yêu cầu…");
        _startWriteProgressPulse(signal);
        editorMode = "visual";
        refreshEditorModeUi();
        _contentEditorAcc = "";
        _contentTypingQueue.length = 0;
        _setContentHtmlLive("");

        let streamErrorMsg = "";
        let streamDone = false;
        let sawDelta = false;
        let suggestMeta = null;
        const _applyStreamHtml = (html) => {
            const s = String(html || "");
            _contentEditorAcc = s;
            _contentTypingQueue.length = 0;
            _setContentHtmlLive(s);
        };

        try {
            _showEditorWriteBar("Đang viết nội dung…");
            try {
                sawDelta = await _readContentSuggestStream(ctx, signal, {
                    onPing: () => {
                        sawDelta = true;
                        if (!_contentWriteSession.contentVisible && !_contentWriteSession.userAborted) {
                            _showContentWriteOverlay(
                                (caEditorWriteStatus && caEditorWriteStatus.textContent) || "Đang viết nội dung…"
                            );
                        }
                    },
                    onDelta: (delta) => {
                        sawDelta = true;
                        _enqueueStreamDelta(delta, signal);
                        if (caEditorWriteBar) caEditorWriteBar.hidden = false;
                        if (caEditorWriteStatus) caEditorWriteStatus.textContent = "Đang viết nội dung…";
                    },
                    onReplaceHtml: async (html) => {
                        sawDelta = true;
                        _contentEditorAcc = "";
                        _contentTypingQueue.length = 0;
                        _setContentHtmlLive("");
                        if (_typingEffectEnabled() && String(html || "").trim()) {
                            _showEditorWriteBar("Đang hiển thị nội dung…");
                            _contentEditorAcc = await _simulateHtmlTyping(html, signal, (pct) => {
                                _showEditorWriteBar(`Đang hiển thị nội dung… ${pct}%`);
                            });
                        } else {
                            _applyStreamHtml(html);
                        }
                        _showEditorWriteBar("Đang chuẩn hóa số từ…");
                    },
                    onWordCountMeta: (meta) => {
                        suggestMeta = meta;
                        updateWordCountStatus(meta);
                    },
                    onDone: () => {
                        streamDone = true;
                        _caStreamLog("stream done");
                    },
                    onError: (err) => {
                        streamErrorMsg = String(err || "Unknown error");
                        _caStreamLog("stream error", streamErrorMsg);
                    },
                });
            } catch (e) {
                if (_contentWriteSession.userAborted || (e && e.name === "AbortError" && _contentWriteSession.userAborted)) {
                    throw e;
                }
                if (e && e.name === "AbortError" && !_contentWriteSession.userAborted) {
                    streamErrorMsg = streamErrorMsg || "Kết nối viết bài bị đóng.";
                } else {
                    streamErrorMsg = streamErrorMsg || String((e && e.message) || e);
                }
                _caStreamLog("stream exception", streamErrorMsg);
            }

            await _flushContentTypingQueue(signal);
            let finalValue = String(_contentEditorAcc || "");

            if (_contentWriteSession.userAborted) {
                throw new DOMException("Aborted", "AbortError");
            }

            if (streamErrorMsg) {
                throw new Error(streamErrorMsg);
            }

            if (!String(finalValue || "").trim()) {
                throw new Error("Không nhận được nội dung. Vui lòng thử lại.");
            }

            _assertContentWriteActive(signal);
            _showEditorWriteBar("Đang kiểm tra số từ…");
            let enforced = { value: finalValue };
            if (_shouldSkipClientEnforce(finalValue, ctx, suggestMeta)) {
                updateWordCountStatus(suggestMeta || _localWordCountStats(finalValue, ctx));
            } else {
                try {
                    enforced = await enforceWordCountAfterWrite(finalValue, ctx, signal);
                } catch (enforceErr) {
                    _caStreamLog("enforce exception, keep streamed content", enforceErr);
                    enforced = { value: finalValue, soft_fail: true, ..._localWordCountStats(finalValue, ctx) };
                }
                if (enforced && enforced.value && enforced.value !== finalValue) {
                    _contentEditorAcc = enforced.value;
                    _contentTypingQueue.length = 0;
                    _setContentHtmlLive(enforced.value);
                    finalValue = enforced.value;
                } else if (enforced) {
                    updateWordCountStatus(enforced);
                }
            }

            _assertContentWriteActive(signal);
            _showEditorWriteBar("Đang tối ưu SEO…");
            finalValue = await autoInjectBlockquoteForContent(finalValue, { signal });
            _assertContentWriteActive(signal);
            setContentValue(finalValue);
            editorMode = "visual";
            refreshEditorModeUi();
            try { refreshPreview(); } catch (_) {}
            window.setTimeout(ensureEditorVisible, 140);
            window.setTimeout(ensureEditorVisible, 420);
            saveFormState();
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
                void window.ContentAiUsage.refresh();
            }
            _showEditorWriteBar("Hoàn thành");
            try {
                const el = byId("contentRender");
                const html = el
                    ? String(el.innerHTML || el.textContent || "")
                    : String(finalValue || "");
                const ta = byId("content");
                if (ta) {
                    ta.value = html;
                    try { ta.dispatchEvent(new Event("input", { bubbles: true })); } catch (_) {}
                }
                if (typeof updateContentStatsFromHtml === "function") updateContentStatsFromHtml(html);
                else refreshPreview();
                if (el) {
                    try { el.dispatchEvent(new Event("input", { bubbles: true })); } catch (_) {}
                }
            } catch (_) {}
            _caStreamLog("write complete", { chars: finalValue.length, sawDelta, streamDone });
            return finalValue;
        } catch (e) {
            if (_contentWriteSession.userAborted) {
                await _flushContentTypingQueue(signal).catch(() => {});
                _showEditorWriteError("Đã dừng viết.");
                saveFormState();
                throw e;
            }
            const preserved = String(_contentEditorAcc || "").trim();
            if (preserved) {
                _caStreamLog("write error after stream, preserving content", e);
                try {
                    setContentValue(preserved);
                    editorMode = "visual";
                    refreshEditorModeUi();
                    try {
                        if (typeof updateContentStatsFromHtml === "function") {
                            updateContentStatsFromHtml(preserved);
                        } else {
                            refreshPreview();
                        }
                    } catch (_) {}
                    saveFormState();
                    _showEditorWriteBar("Hoàn thành (giữ nội dung đã viết)");
                } catch (_) {}
                return preserved;
            }
            _showEditorWriteError(String(e.message || e));
            if (window.ContentAiErrors && window.ContentAiErrors.showIfLlmUnavailable) {
                window.ContentAiErrors.showIfLlmUnavailable(null, String(e.message || e));
            }
            _contentEditorAcc = "";
            _contentTypingQueue.length = 0;
            _setContentHtmlLive("");
            throw e;
        } finally {
            _contentTypingQueue.length = 0;
            _contentTypingPump = null;
            _resetContentWriteUi();
        }
    };
    if (btnStopContentWrite) {
        btnStopContentWrite.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            _stopContentWrite(true);
            _showEditorWriteError("Đã dừng viết.");
            saveFormState();
        });
    }

    const _openGenModal = () => {
        try {
            if (genBackdrop) genBackdrop.classList.add("open");
            if (genModal) {
                genModal.classList.add("open");
                genModal.setAttribute("aria-hidden", "false");
            }
            if (btnGenClose) btnGenClose.disabled = true;
            if (genFill) genFill.style.width = "0%";
            if (genPct) genPct.textContent = "0%";
            if (genHint) genHint.textContent = "Đang tạo nội dung...";
            if (genStream) genStream.textContent = "";
            if (inlineProgress) inlineProgress.classList.remove("show");
            if (previewLoading) previewLoading.classList.remove("show");
        } catch (_) {}
    };
    const _closeGenModal = () => {
        try {
            if (genBackdrop) genBackdrop.classList.remove("open");
            if (genModal) {
                genModal.classList.remove("open");
                genModal.setAttribute("aria-hidden", "true");
            }
            if (inlineProgress) inlineProgress.classList.remove("show");
            if (previewLoading) previewLoading.classList.remove("show");
        } catch (_) {}
    };
    if (btnGenClose) btnGenClose.addEventListener("click", _closeGenModal);
    if (genBackdrop) genBackdrop.addEventListener("click", () => {
        if (btnGenClose && !btnGenClose.disabled) _closeGenModal();
    });

    const _finishGenProgress = () => {
        if (genFill) genFill.style.width = "100%";
        if (genPct) genPct.textContent = "100%";
        if (inlineProgressFill) inlineProgressFill.style.width = "100%";
        if (inlineProgressPct) inlineProgressPct.textContent = "100%";
        if (previewLoadingFill) previewLoadingFill.style.width = "100%";
        if (previewLoadingPct) previewLoadingPct.textContent = "100%";
        if (genHint) genHint.textContent = "Hoàn tất.";
        if (btnGenClose) btnGenClose.disabled = false;
    };

    const streamSuggestion = async (field, ctx, options = {}) => {
        if (field === "content") {
            return writeContentToEditor(ctx, options);
        }
        // Prompt 2.4: non-content fields also poll LLM job (stream detached from API).
        return fetchSuggestion(field, ctx, options);
    };
    const appendPublishLog = (line) => {
        const ts = new Date().toLocaleTimeString("vi-VN");
        const old = publishLog.value ? `${publishLog.value}\n` : "";
        publishLog.value = `${old}[${ts}] ${line}`;
    };
    const setPublishNotice = (text, kind, link, linkLabel) => {
        const el = byId("caPublishNotice");
        if (!el) return;
        const t = String(text || "").trim();
        el.replaceChildren();
        el.classList.remove("ca-publish-notice--ok", "ca-publish-notice--err", "ca-publish-notice--info");
        if (!t) {
            el.hidden = true;
            return;
        }
        el.hidden = false;
        if (kind === "ok" || kind === "err" || kind === "info") {
            el.classList.add(`ca-publish-notice--${kind}`);
        }
        const span = document.createElement("strong");
        span.textContent = t;
        el.appendChild(span);
        const href = String(link || "").trim();
        if (href && /^https?:\/\//i.test(href)) {
            el.appendChild(document.createTextNode(" "));
            const a = document.createElement("a");
            a.href = href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = String(linkLabel || "Xem bài").trim() || "Xem bài";
            el.appendChild(a);
        }
        try {
            el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } catch (_) {}
    };
    const setPublishLogLines = (lines) => {
        if (!Array.isArray(lines) || !lines.length) return;
        publishLog.value = lines.join("\n");
    };
    const ensureDraftPayloadForPublish = async () => {
        // Always rebuild from current editor state to avoid stale payload
        // (common cause: content has new images but old JSON payload is reused).
        const payload = buildDraftPayload();
        const r = await fetch("/content-ai/draft", {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify(payload),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error((d && d.detail) ? d.detail : "Tạo Draft JSON thất bại.");
        out.value = JSON.stringify(d, null, 2);
        saveFormState();
        return d;
    };
    const getOutputFormat = () => {
        const v = (outputFormat && outputFormat.value) ? outputFormat.value : "text";
        return (v === "json") ? "json" : "text";
    };
    const persistOutputFormat = () => {
        try {
            localStorage.setItem(OUTPUT_FORMAT_KEY, getOutputFormat());
        } catch (_) {}
    };
    const restoreOutputFormat = () => {
        try {
            const v = (localStorage.getItem(OUTPUT_FORMAT_KEY) || "").trim().toLowerCase();
            if (outputFormat) outputFormat.value = (v === "json") ? "json" : "text";
        } catch (_) {}
    };

    const setOutputAccordionOpen = (open) => {
        if (!outputAccordion) return;
        const isOpen = !!open;
        outputAccordion.classList.toggle("open", isOpen);
        if (btnToggleOutput) btnToggleOutput.setAttribute("aria-expanded", isOpen ? "true" : "false");
        if (outputAccordionBody) outputAccordionBody.style.display = isOpen ? "block" : "none";
        if (outputChev) outputChev.textContent = isOpen ? "▴" : "▾";
        try { localStorage.setItem(OUTPUT_ACCORDION_KEY, isOpen ? "1" : "0"); } catch (_) {}
    };
    const restoreOutputAccordion = () => {
        try {
            const v = (localStorage.getItem(OUTPUT_ACCORDION_KEY) || "").trim();
            setOutputAccordionOpen(v === "1");
        } catch (_) {
            setOutputAccordionOpen(false);
        }
    };
    const fetchDraftOutput = async (payload) => {
        const fmt = getOutputFormat();
        const url = fmt === "json" ? "/content-ai/draft" : "/content-ai/draft?format=text";
        const r = await fetch(url, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify(payload),
        });
        if (fmt === "json") {
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error((d && d.detail) ? d.detail : "Draft failed");
            out.value = JSON.stringify(d, null, 2);
            try {
                if (d && typeof d === "object" && d.content != null) {
                    setContentValue(String(d.content || ""));
                    refreshPreview();
                }
            } catch (_) {}
            return { fmt: "json", data: d, project_id: String(d.project_id || "").trim() };
        }
        const t = await r.text().catch(() => "");
        if (!r.ok) throw new Error(t || "Draft failed");
        out.value = t;
        try {
            setContentValue(String(t || ""));
            refreshPreview();
        } catch (_) {}
        return { fmt: "text" };
    };
    const buildDraftPayload = () => {
        syncSingleWpCategoryFromSelect();
        const title = byId("title").value.trim();
        const content = getContentValue();
        const outline = byId("outlineContent").value;
        const primaryKeyword = byId("primaryKeyword").value.trim();
        const tags = byId("tags").value.split(",").map((s) => s.trim()).filter(Boolean);
        const targetWebsiteNorm = normalizeTargetBase(byId("targetWebsite").value.trim());
        return {
            title,
            content,
            target_website: targetWebsiteNorm || null,
            slug: byId("slug").value.trim() || null,
            primary_keyword: primaryKeyword,
            secondary_keywords: byId("secondaryKeywords").value.split(",").map((s) => s.trim()).filter(Boolean),
            outline_content: outline || null,
            tags: tags.length ? tags : null,
            meta_description: byId("meta").value.trim() || null,
            target_word_count: parseTargetWordCount(),
            target_word_count_mode: getTargetWordCountMode(),
            featured_image: uploadedImages[0] || null,
            gallery_images: uploadedImages.length ? uploadedImages : null,
            scheduled_at: byId("scheduledAt").value || null,
            categories:
                _draftWpCategoryIds && _draftWpCategoryIds.length ? _draftWpCategoryIds : null,
        };
    };
    const collectFormState = () => ({
        primaryKeyword: byId("primaryKeyword").value,
        targetWebsite: byId("targetWebsite").value,
        title: byId("title").value,
        slug: byId("slug").value,
        secondaryKeywords: byId("secondaryKeywords").value,
        targetWordCountMode: getTargetWordCountMode(),
        targetWordCount: isAutoWordCountMode()
            ? ""
            : String((byId("targetWordCount") && byId("targetWordCount").value) || "1000"),
        competitorUrl: byId("competitorUrl").value,
        replaceFrom: byId("replaceFrom").value,
        replaceTo: byId("replaceTo").value,
        outlineContent: byId("outlineContent").value,
        meta: byId("meta").value,
        tags: byId("tags").value,
        content: getContentValue(),
        scheduledAt: byId("scheduledAt").value,
        publishLog: publishLog.value,
        output: out.value,
        outputFormat: getOutputFormat(),
        uploadedImages: uploadedImages.slice(),
        activeProjectId,
        singleWpCategoryId: byId("singleWpCategoryId") ? byId("singleWpCategoryId").value : "",
        internalCandidates: slimInternalCandidatesForStorage(_internalCandidates),
        internalCandidateAnchors: collectInternalCandidateAnchors(),
        mediaPanel: typeof window.__caCollectMediaPanelState === "function" ? window.__caCollectMediaPanelState() : null,
    });
    let _saveFormStateTimer = null;
    const _setAutosaveUi = (state) => {
        const labels = { saving: "Đang lưu nháp…", saved: "Đã lưu nháp", error: "Lỗi lưu nháp" };
        ["caAutosaveIndicator", "caStickyAutosave"].forEach((id) => {
            const el = byId(id);
            if (!el) return;
            el.textContent = labels[state] || labels.saved;
            el.classList.remove("saving", "saved");
            el.classList.add(state === "saving" ? "saving" : "saved");
        });
    };
    const flushSaveFormState = () => {
        try {
            localStorage.setItem(FORM_STATE_KEY(), JSON.stringify(collectFormState()));
            _setAutosaveUi("saved");
        } catch (_) {
            _setAutosaveUi("error");
        }
    };
    const scheduleSaveFormState = () => {
        _setAutosaveUi("saving");
        if (_saveFormStateTimer) window.clearTimeout(_saveFormStateTimer);
        _saveFormStateTimer = window.setTimeout(() => {
            _saveFormStateTimer = null;
            flushSaveFormState();
            try {
                refreshContentAiStepStates();
            } catch (_) {}
        }, 400);
    };
    const saveFormState = () => flushSaveFormState();
    const restoreFormState = () => {
        try {
            const raw = localStorage.getItem(FORM_STATE_KEY());
            if (!raw) return false;
            const s = JSON.parse(raw);
            if (!s || typeof s !== "object") return false;
            byId("primaryKeyword").value = s.primaryKeyword || "";
            byId("targetWebsite").value = s.targetWebsite || "";
            byId("title").value = s.title || "";
            byId("slug").value = s.slug || "";
            byId("secondaryKeywords").value = s.secondaryKeywords || "";
            if (byId("targetWordCount")) {
                const autoMode = String(s.targetWordCountMode || "") === "auto";
                if (autoMode) {
                    const row = byId("wordCountPresetRow");
                    if (row) {
                        row.querySelectorAll(".wc-preset-btn").forEach((btn) => {
                            btn.classList.toggle("active", String(btn.dataset.wc || "") === "auto");
                        });
                    }
                    byId("targetWordCount").value = "";
                } else {
                    byId("targetWordCount").value = String(s.targetWordCount || "1000");
                }
                syncWordCountPresetActive();
            }
            byId("competitorUrl").value = s.competitorUrl || "";
            byId("replaceFrom").value = s.replaceFrom || "";
            byId("replaceTo").value = s.replaceTo || "";
            byId("outlineContent").value = s.outlineContent || "";
            try {
                autoGrowOutline();
            } catch (_) {}
            byId("meta").value = s.meta || "";
            byId("tags").value = s.tags || "";
            setContentValue(s.content || "");
            byId("scheduledAt").value = s.scheduledAt || "";
            byId("wpUrl").value = "";
            publishLog.value = s.publishLog || "";
            out.value = s.output || "";
            if (outputFormat) outputFormat.value = (s.outputFormat === "json") ? "json" : "text";
            uploadedImages.length = 0;
            for (const u of (s.uploadedImages || [])) {
                const sUrl = String(u || "").trim().split("?")[0];
                if (sUrl && (sUrl.startsWith("/api/user-files/") || sUrl.startsWith("/static/"))) {
                    uploadedImages.push(sUrl);
                }
            }
            activeProjectId = s.activeProjectId || "";
            const wpcSaved = String(s.singleWpCategoryId || "").trim();
            if (wpcSaved) {
                const n = parseInt(wpcSaved, 10);
                _draftWpCategoryIds = !Number.isNaN(n) && n > 0 ? [n] : null;
            }
            fillSingleWpCategorySelect(wpcSaved);
            try { scheduleSingleWpCategoriesLoad(); } catch (_) {}
            renderUploadList();
            toggleAiAvailability();
            syncSlugFromPrimary(true);
            _pendingInternalCandidatesRestore = null;
            if (Array.isArray(s.internalCandidates) && s.internalCandidates.length) {
                _pendingInternalCandidatesRestore = {
                    items: s.internalCandidates,
                    anchors:
                        s.internalCandidateAnchors && typeof s.internalCandidateAnchors === "object"
                            ? s.internalCandidateAnchors
                            : {},
                };
            }
            if (window.__caRestoreMediaPanelState && s.mediaPanel) {
                window.__caRestoreMediaPanelState(s.mediaPanel);
            }
            try {
                refreshPreview();
            } catch (_) {}
            try {
                syncPreviewFallback();
            } catch (_) {}
            return true;
        } catch (_) {
            return false;
        }
    };
    const showMediaInsertSummary = (text, { warn = false } = {}) => {
        const box = byId("mediaInsertSummary");
        if (!box) return;
        const msg = String(text || "").trim();
        if (!msg) {
            box.hidden = true;
            box.textContent = "";
            box.classList.remove("warn");
            return;
        }
        box.hidden = false;
        box.textContent = msg;
        box.classList.toggle("warn", !!warn);
        // Do NOT mirror identical text into #mediaInsertedStatsText (double green/grey banners).
    };
    const switchMediaToInsertedTab = () => {
        const root = byId("contentAiMediaPanel");
        if (root && window.__caSwitchModalTab) window.__caSwitchModalTab(root, 2);
        // Refresh demo payload so "Xem demo" reflects just-inserted figures.
        try {
            if (window.__caRefreshContentDemo) {
                window.__caRefreshContentDemo("caMediaDemoPreview", "media");
            }
        } catch (_) {}
    };
    window.__caSwitchMediaInsertedTab = switchMediaToInsertedTab;
    let _mediaContentBeforeInsert = "";
    const normalizeMediaUrlClient = (u) =>
        String(u || "")
            .trim()
            .replace(/[?&]token=[^&"']*/gi, "")
            .replace(/[?&]$/, "")
            .split("#")[0]
            .split("?")[0];
    const isStoredMediaUrlClient = (u) => {
        const s = normalizeMediaUrlClient(u);
        return s.startsWith("/api/user-files/") || s.startsWith("/static/");
    };
    const mediaThumbSrc = (u) => {
        const raw = String(u || "").trim();
        if (!raw) return "";
        if (!isStoredMediaUrlClient(raw)) return normalizeMediaUrlClient(raw);
        try {
            const wrapped = withImageAuthTokensForHtml(
                `<img src="${normalizeMediaUrlClient(raw).replace(/"/g, "")}" alt="" />`,
            );
            const m = wrapped.match(/src=(["'])([^"']+)\1/i);
            if (m && m[2]) return m[2];
        } catch (_) {}
        return normalizeMediaUrlClient(raw);
    };
    const extractStoredMediaUrlsFromHtml = (html) => {
        const out = [];
        const re = /<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/gi;
        let m;
        while ((m = re.exec(String(html || "")))) {
            const s = normalizeMediaUrlClient(m[1]);
            if (s && isStoredMediaUrlClient(s) && !out.includes(s)) out.push(s);
        }
        return out;
    };
    /** Rebuild Đã chèn list: only local/app-hosted URLs. Drops dead external links. */
    const rebuildUploadedImagesList = (opts = {}) => {
        const prefer = [];
        const add = (u) => {
            const s = normalizeMediaUrlClient(u);
            if (!s || !isStoredMediaUrlClient(s) || prefer.includes(s)) return;
            prefer.push(s);
        };
        if (opts.featured) add(opts.featured);
        if (opts.url) add(opts.url);
        (opts.extra || []).forEach(add);
        extractStoredMediaUrlsFromHtml(
            typeof getContentValue === "function" ? getContentValue() : "",
        ).forEach(add);
        // Keep previous stored entries (feature order) after content scan
        (uploadedImages || []).forEach(add);
        uploadedImages.length = 0;
        prefer.forEach((u) => uploadedImages.push(u));
        renderUploadList();
        return uploadedImages.slice();
    };
    window.__caRebuildUploadedImagesList = rebuildUploadedImagesList;
    const renderUploadList = () => {
        if (!uploadList) return;
        uploadList.innerHTML = "";
        // Drop broken remote leftovers from older drafts
        const clean = [];
        (uploadedImages || []).forEach((u) => {
            const s = normalizeMediaUrlClient(u);
            if (s && isStoredMediaUrlClient(s) && !clean.includes(s)) clean.push(s);
        });
        if (clean.length !== uploadedImages.length) {
            uploadedImages.length = 0;
            clean.forEach((u) => uploadedImages.push(u));
        }
        if (!uploadedImages.length) {
            uploadList.innerHTML = '<p class="ca-il-empty">Chưa có ảnh đã chọn (chỉ hiện ảnh đã lưu trên hệ thống).</p>';
            return;
        }
        uploadedImages.forEach((url, idx) => {
            const div = document.createElement("div");
            div.className = "ca-media-selected-item upload-item";
            const thumb = document.createElement("img");
            thumb.src = mediaThumbSrc(url);
            thumb.alt = idx === 0 ? "Featured" : "Inline";
            thumb.loading = "lazy";
            thumb.onerror = () => {
                thumb.style.display = "none";
                const ph = document.createElement("div");
                ph.className = "hint";
                ph.style.cssText = "width:72px;height:54px;display:flex;align-items:center;justify-content:center;font-size:0.65rem;border:1px dashed rgba(255,255,255,0.2);border-radius:6px;";
                ph.textContent = "Lỗi";
                if (thumb.parentNode) thumb.parentNode.insertBefore(ph, thumb);
            };
            const meta = document.createElement("div");
            meta.className = "u-meta";
            meta.style.flex = "1";
            meta.innerHTML = `<div><strong>${idx === 0 ? "Ảnh đại diện" : "Ảnh trong bài"}</strong></div><div class="hint">${idx === 0 ? "Featured" : "Inline"} · ALT từ từ khóa</div>`;
            const actions = document.createElement("div");
            actions.className = "u-actions";
            const bCrop = document.createElement("button");
            bCrop.type = "button";
            bCrop.className = "mini-btn";
            bCrop.textContent = "Cắt";
            bCrop.addEventListener("click", () => openCropModal(url));
            const bDel = document.createElement("button");
            bDel.type = "button";
            bDel.className = "mini-btn danger";
            bDel.textContent = "Xóa";
            bDel.addEventListener("click", () => {
                const i = uploadedImages.indexOf(url);
                if (i >= 0) uploadedImages.splice(i, 1);
                renderUploadList();
                saveFormState();
            });
            actions.appendChild(bCrop);
            actions.appendChild(bDel);
            div.appendChild(thumb);
            div.appendChild(meta);
            div.appendChild(actions);
            uploadList.appendChild(div);
        });
        showMediaInsertSummary(`${uploadedImages.length} ảnh trong danh sách — ${uploadedImages.length === 1 ? "1 featured/inline" : "featured + inline"}.`);
    };

    const _demoEscHtml = (s) => String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    let _contentViewEditMode = false;
    let _contentViewEditSnapshot = { title: "", html: "" };
    const _contentViewTitleEl = () => byId("caContentViewTitle");
    const _contentViewEditBtn = () => byId("btnContentViewEdit");
    const _contentViewSaveBtn = () => byId("btnContentViewSave");
    const _contentViewCancelBtn = () => byId("btnContentViewCancelEdit");
    const _syncContentViewEditUi = () => {
        const editing = _contentViewEditMode;
        const titleEl = _contentViewTitleEl();
        const editBtn = _contentViewEditBtn();
        const saveBtn = _contentViewSaveBtn();
        const cancelBtn = _contentViewCancelBtn();
        if (titleEl) titleEl.textContent = editing ? "Chỉnh sửa nội dung bài viết" : "Xem nội dung bài viết";
        if (editBtn) editBtn.hidden = editing;
        if (saveBtn) saveBtn.hidden = !editing;
        if (cancelBtn) cancelBtn.hidden = !editing;
    };
    const _readContentViewEditDraft = () => {
        const viewport = byId("caContentViewPreview");
        if (!viewport) return { title: "", html: "" };
        const titleEl = viewport.querySelector(".ca-demo-title");
        const bodyEl = viewport.querySelector(".ca-demo-body");
        return {
            title: titleEl ? String(titleEl.textContent || "").trim() : "",
            html: bodyEl ? String(bodyEl.innerHTML || "").trim() : "",
        };
    };
    const _contentViewDraftDirty = () => {
        if (!_contentViewEditMode) return false;
        const draft = _readContentViewEditDraft();
        return draft.title !== _contentViewEditSnapshot.title
            || draft.html !== _contentViewEditSnapshot.html;
    };
    const refreshContentDemoPreview = (containerId, focus, editMode = false) => {
        const el = byId(containerId);
        if (!el) return;
        const html = withImageAuthTokensForHtml(String(getContentValue() || "").trim());
        const title = String(byId("title")?.value || "").trim();
        const focusCls = focus === "links" ? " ca-demo-focus-links" : focus === "media" ? " ca-demo-focus-media" : "";
        const editingCls = editMode ? " ca-content-view-editing" : "";
        el.className = `ca-content-demo-viewport ca-demo-article-shell${focusCls}${editingCls}`;
        if (!html && !editMode) {
            el.innerHTML = '<p class="ca-il-empty">Chưa có nội dung trong editor — viết bài trước khi xem demo.</p>';
            return;
        }
        const linkCount = (html.match(/<a\b[^>]*\bhref\s*=/gi) || []).length;
        const imgCount = (html.match(/<img\b/gi) || []).length;
        const focusNote = focus === "links"
            ? " · Link được tô sáng xanh lá"
            : focus === "media"
                ? " · Ảnh được viền xanh lá"
                : "";
        const metaNote = editMode ? " · Đang chỉnh sửa — thay đổi sẽ lưu vào editor chính" : "";
        const titleHtml = editMode
            ? `<h1 class="ca-demo-title ca-content-view-editable" contenteditable="true" spellcheck="true">${_demoEscHtml(title || "Tiêu đề bài viết")}</h1>`
            : (title ? `<h1 class="ca-demo-title">${_demoEscHtml(title)}</h1>` : "");
        const bodyAttrs = editMode
            ? ' class="ca-demo-body content-render ca-content-view-editable" contenteditable="true" spellcheck="true"'
            : ' class="ca-demo-body content-render"';
        el.innerHTML = `
            <p class="ca-demo-meta">${linkCount} link · ${imgCount} ảnh trong bài${focusNote}${metaNote}</p>
            ${titleHtml}
            <div${bodyAttrs}>${html || (editMode ? "<p><br></p>" : "")}</div>
        `;
        if (editMode) {
            const bodyEl = el.querySelector(".ca-demo-body");
            if (bodyEl) {
                window.setTimeout(() => {
                    try { bodyEl.focus(); } catch (_) {}
                }, 0);
            }
        }
    };
    window.__caRefreshContentDemo = refreshContentDemoPreview;
    const applyContentViewEditToEditor = () => {
        const draft = _readContentViewEditDraft();
        const titleInput = byId("title");
        if (titleInput) titleInput.value = draft.title;
        setContentValue(draft.html);
        try { refreshPreview(); } catch (_) {}
        saveFormState();
    };
    const enterContentViewEditMode = () => {
        _contentViewEditMode = true;
        _contentViewEditSnapshot = {
            title: String(byId("title")?.value || "").trim(),
            html: String(getContentValue() || "").trim(),
        };
        refreshContentDemoPreview("caContentViewPreview", undefined, true);
        _syncContentViewEditUi();
    };
    const exitContentViewEditMode = (save) => {
        if (save) applyContentViewEditToEditor();
        _contentViewEditMode = false;
        refreshContentDemoPreview("caContentViewPreview");
        _syncContentViewEditUi();
    };
    const confirmDiscardContentViewEdit = () => {
        if (!_contentViewDraftDirty()) return true;
        try {
            return window.confirm("Bạn có thay đổi chưa lưu. Bỏ thay đổi và tiếp tục?");
        } catch (_) {
            return true;
        }
    };
    const openContentViewModal = () => {
        const backdrop = byId("caContentViewBackdrop");
        const modal = byId("caContentViewModal");
        if (!backdrop || !modal) return;
        _contentViewEditMode = false;
        refreshContentDemoPreview("caContentViewPreview");
        _syncContentViewEditUi();
        backdrop.classList.add("open");
        modal.classList.add("open");
        backdrop.setAttribute("aria-hidden", "false");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("ca-content-view-open");
    };
    const closeContentViewModal = () => {
        if (_contentViewEditMode && _contentViewDraftDirty()) {
            if (!confirmDiscardContentViewEdit()) return;
            exitContentViewEditMode(false);
        } else if (_contentViewEditMode) {
            exitContentViewEditMode(false);
        }
        const backdrop = byId("caContentViewBackdrop");
        const modal = byId("caContentViewModal");
        if (backdrop) {
            backdrop.classList.remove("open");
            backdrop.setAttribute("aria-hidden", "true");
        }
        if (modal) {
            modal.classList.remove("open");
            modal.setAttribute("aria-hidden", "true");
        }
        document.body.classList.remove("ca-content-view-open");
    };
    const btnViewContentPreview = byId("btnViewContentPreview");
    if (btnViewContentPreview && !btnViewContentPreview.dataset.bound) {
        btnViewContentPreview.dataset.bound = "1";
        btnViewContentPreview.addEventListener("click", (e) => {
            e.preventDefault();
            openContentViewModal();
        });
    }
    const btnCloseContentView = byId("btnCloseContentView");
    if (btnCloseContentView && !btnCloseContentView.dataset.bound) {
        btnCloseContentView.dataset.bound = "1";
        btnCloseContentView.addEventListener("click", (e) => {
            e.preventDefault();
            closeContentViewModal();
        });
    }
    const btnContentViewEdit = byId("btnContentViewEdit");
    if (btnContentViewEdit && !btnContentViewEdit.dataset.bound) {
        btnContentViewEdit.dataset.bound = "1";
        btnContentViewEdit.addEventListener("click", (e) => {
            e.preventDefault();
            enterContentViewEditMode();
        });
    }
    const btnContentViewSave = byId("btnContentViewSave");
    if (btnContentViewSave && !btnContentViewSave.dataset.bound) {
        btnContentViewSave.dataset.bound = "1";
        btnContentViewSave.addEventListener("click", (e) => {
            e.preventDefault();
            exitContentViewEditMode(true);
        });
    }
    const btnContentViewCancelEdit = byId("btnContentViewCancelEdit");
    if (btnContentViewCancelEdit && !btnContentViewCancelEdit.dataset.bound) {
        btnContentViewCancelEdit.dataset.bound = "1";
        btnContentViewCancelEdit.addEventListener("click", (e) => {
            e.preventDefault();
            if (_contentViewDraftDirty() && !confirmDiscardContentViewEdit()) return;
            exitContentViewEditMode(false);
        });
    }
    const caContentViewBackdrop = byId("caContentViewBackdrop");
    if (caContentViewBackdrop && !caContentViewBackdrop.dataset.bound) {
        caContentViewBackdrop.dataset.bound = "1";
        caContentViewBackdrop.addEventListener("click", (e) => {
            if (e.target === caContentViewBackdrop) closeContentViewModal();
        });
    }
    const caContentViewModal = byId("caContentViewModal");
    if (caContentViewModal && !caContentViewModal.dataset.bound) {
        caContentViewModal.dataset.bound = "1";
        caContentViewModal.addEventListener("click", (e) => {
            if (e.target === caContentViewModal) closeContentViewModal();
        });
    }
    document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        const modal = byId("caContentViewModal");
        if (!modal || !modal.classList.contains("open")) return;
        if (_contentViewEditMode) {
            e.preventDefault();
            if (_contentViewDraftDirty() && !confirmDiscardContentViewEdit()) return;
            exitContentViewEditMode(false);
            return;
        }
        closeContentViewModal();
    });
    const btnRefreshIlDemo = byId("btnRefreshIlDemo");
    if (btnRefreshIlDemo && !btnRefreshIlDemo.dataset.bound) {
        btnRefreshIlDemo.dataset.bound = "1";
        btnRefreshIlDemo.addEventListener("click", (e) => {
            e.preventDefault();
            refreshContentDemoPreview("caIlDemoPreview", "links");
        });
    }
    const btnRefreshMediaDemo = byId("btnRefreshMediaDemo");
    if (btnRefreshMediaDemo && !btnRefreshMediaDemo.dataset.bound) {
        btnRefreshMediaDemo.dataset.bound = "1";
        btnRefreshMediaDemo.addEventListener("click", (e) => {
            e.preventDefault();
            refreshContentDemoPreview("caMediaDemoPreview", "media");
        });
    }

    const openMediaImageLightbox = (url) => {
        const box = byId("studioLightbox");
        const img = byId("studioLightboxImg");
        if (!box || !img || !url) return;
        img.src = url;
        box.classList.add("open");
        box.setAttribute("aria-hidden", "false");
    };
    window.__caOpenMediaLightbox = openMediaImageLightbox;

    const renderGoogleImageResults = (items) => {
        window.__caGoogleImageResultsCache = Array.isArray(items) ? items.slice() : [];
        if (!googleImageResults) return;
        googleImageResults.innerHTML = "";
        const arr = Array.isArray(items) ? items : [];
        if (!arr.length) {
            googleImageResults.innerHTML = '<p class="ca-il-empty">Không có kết quả — thử từ khóa khác.</p>';
            return;
        }
        arr.forEach((it) => {
            const wrap = document.createElement("article");
            wrap.className = "ca-media-card ca-media-gallery-card";
            wrap.setAttribute("role", "listitem");
            const fullUrl = String(it.link || it.thumbnail || "").trim();
            const thumbBtn = document.createElement("button");
            thumbBtn.type = "button";
            thumbBtn.className = "ca-media-thumb-wrap";
            thumbBtn.setAttribute("aria-label", "Xem ảnh lớn");
            const thumb = document.createElement("img");
            thumb.className = "ca-media-thumb-img";
            thumb.src = it.thumbnail || it.link;
            thumb.alt = it.title || "Web image";
            thumb.loading = "lazy";
            thumb.draggable = false;
            thumbBtn.addEventListener("click", (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                openMediaImageLightbox(fullUrl || thumb.src);
            });
            thumbBtn.appendChild(thumb);
            const body = document.createElement("div");
            body.className = "ca-media-gallery-card-body";
            const meta = document.createElement("div");
            meta.className = "ca-media-gallery-meta";
            meta.innerHTML = '<span class="ca-media-src-badge">Web</span><span class="ca-media-src-badge">Phù hợp —</span>';
            const title = document.createElement("div");
            title.style.fontWeight = "700";
            title.style.fontSize = "0.76rem";
            title.style.lineHeight = "1.25";
            title.style.marginBottom = "4px";
            title.textContent = (it.title || "").slice(0, 90) || "Ảnh web";
            const altHint = document.createElement("div");
            altHint.className = "hint";
            altHint.style.fontSize = "0.68rem";
            altHint.textContent = `ALT: ${(it.title || byId("primaryKeyword")?.value || "minh họa").toString().slice(0, 60)}`;
            const posHint = document.createElement("div");
            posHint.className = "hint";
            posHint.style.fontSize = "0.68rem";
            posHint.textContent = "Vị trí: sau H2 gần nhất";
            const actions = document.createElement("div");
            actions.className = "u-actions";
            actions.style.marginTop = "6px";
            const bImport = document.createElement("button");
            bImport.type = "button";
            bImport.className = "mini-btn";
            bImport.textContent = "Chọn";
            bImport.addEventListener("click", async (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                try {
                    if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
                        const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.googleImage);
                        if (!ok) {
                            setHint("google-images", "Đã hủy hoặc không đủ credit để import ảnh web.");
                            return;
                        }
                    }
                    bImport.disabled = true;
                    const fullUrl = String(it.link || "").trim();
                    const thumbUrl = String(it.thumbnail || "").trim();
                    if (!fullUrl && !thumbUrl) {
                        throw new Error("Thiếu URL ảnh web.");
                    }

                    // 1) Chọn vị trí trước (thấy rõ popup). Chỉ import sau khi đã chọn heading.
                    setHint("google-images", "Chọn vị trí chèn ảnh (H2/H3)…");
                    let place = null;
                    if (typeof window.__caOpenMediaHeadingPicker === "function") {
                        place = await window.__caOpenMediaHeadingPicker();
                    }
                    if (!place) {
                        setHint("google-images", "Đã hủy — chưa chọn vị trí chèn.");
                        return;
                    }

                    // 2) Import về server (thử full link rồi fallback thumbnail)
                    setHint("google-images", "Đang tải ảnh về server…");
                    const tryImport = async (remoteUrl) => {
                        const res = await fetch(`/content-ai/google-images/import?ts=${Date.now()}`, {
                            method: "POST",
                            headers: authJsonHeaders(),
                            body: JSON.stringify({ url: remoteUrl }),
                        });
                        const data = await res.json().catch(() => ({}));
                        if (!res.ok) {
                            const d = data.detail;
                            throw new Error(typeof d === "string" ? d : "Import ảnh thất bại");
                        }
                        return String((data && data.url) || "").trim();
                    };
                    let localUrl = "";
                    let importErr = "";
                    const candidates = [];
                    if (fullUrl) candidates.push(fullUrl);
                    if (thumbUrl && thumbUrl !== fullUrl) candidates.push(thumbUrl);
                    for (const cand of candidates) {
                        try {
                            localUrl = await tryImport(cand);
                            if (localUrl) break;
                        } catch (e1) {
                            importErr = String((e1 && e1.message) || e1);
                        }
                    }
                    if (!localUrl) {
                        throw new Error(importErr || "Không tải được ảnh về server.");
                    }

                    if (!_mediaContentBeforeInsert) _mediaContentBeforeInsert = getContentValue();
                    // 3) Chèn dưới heading đã chọn
                    setHint("google-images", "Đang chèn ảnh vào bài…");
                    const placeOpts = {
                        placement: place.placement || "after_heading",
                        section_heading: place.section_heading || "",
                        h2_index: place.level === "h3" ? null : place.h2_index,
                        h3_index: place.level === "h3" ? place.h3_index : null,
                    };
                    let insertedOk = false;
                    if (typeof window.__caStudioInsertWithPlacement === "function") {
                        const result = await window.__caStudioInsertWithPlacement(
                            { url: localUrl, alt: it.title || "" },
                            placeOpts,
                        );
                        insertedOk = !!(result && result.ok);
                    } else {
                        insertImageIntoEditor(localUrl);
                        insertedOk = true;
                        if (typeof window.__caRebuildUploadedImagesList === "function") {
                            window.__caRebuildUploadedImagesList({ url: localUrl });
                        } else if (!uploadedImages.includes(localUrl)) {
                            uploadedImages.push(localUrl);
                            renderUploadList();
                        }
                        if (typeof switchMediaToInsertedTab === "function") switchMediaToInsertedTab();
                    }
                    if (!insertedOk) {
                        throw new Error("Ảnh đã import nhưng chưa chèn vào editor. Thử lại.");
                    }
                    // Ensure list only has durable local images (avoid broken external leftovers)
                    if (typeof window.__caRebuildUploadedImagesList === "function") {
                        window.__caRebuildUploadedImagesList({ url: localUrl });
                    }
                    setHint("google-images", "Đã import và chèn ảnh vào Content — mở tab Xem demo hoặc đóng modal để kiểm tra editor.");
                    if (typeof showMediaInsertSummary === "function") {
                        showMediaInsertSummary(
                            `1 ảnh web — vị trí: ${place.section_heading || place.placement || "đã chọn"}.`,
                        );
                    }
                    try {
                        if (window.__caRefreshContentDemo) {
                            window.__caRefreshContentDemo("caMediaDemoPreview", "media");
                        }
                    } catch (_) {}
                    saveFormState();
                    const undoBtn = byId("btnMediaUndo");
                    if (undoBtn) undoBtn.hidden = false;
                } catch (e) {
                    setHint("google-images", String(e.message || e));
                } finally {
                    bImport.disabled = false;
                }
            });
            const bCrop = document.createElement("button");
            bCrop.type = "button";
            bCrop.className = "mini-btn";
            bCrop.textContent = "Import & Cắt";
            bCrop.addEventListener("click", async (ev) => {
                ev.stopPropagation();
                try {
                    if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
                        const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.googleImage);
                        if (!ok) return;
                    }
                    setHint("google-images", "Đang import ảnh để cắt...");
                    bCrop.disabled = true;
                    const res = await fetch(`/content-ai/google-images/import?ts=${Date.now()}`, {
                        method: "POST",
                        headers: authJsonHeaders(),
                        body: JSON.stringify({ url: it.link }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Import ảnh thất bại");
                    if (data.url) {
                        uploadedImages.push(data.url);
                        renderUploadList();
                        saveFormState();
                        openCropModal(data.url);
                    }
                    setHint("google-images", "Đã import ảnh. Bạn có thể cắt và chèn.");
                } catch (e) {
                    setHint("google-images", String(e.message || e));
                } finally {
                    bCrop.disabled = false;
                }
            });
            actions.appendChild(bImport);
            actions.appendChild(bCrop);
            body.appendChild(meta);
            body.appendChild(title);
            body.appendChild(altHint);
            body.appendChild(posHint);
            body.appendChild(actions);
            wrap.appendChild(thumbBtn);
            wrap.appendChild(body);
            googleImageResults.appendChild(wrap);
        });
    };

    const replaceImageInEditor = (oldUrl, newUrl) => {
        const cr = byId("contentRender");
        if (!cr) return false;
        const oldSrc = String(oldUrl || "").trim();
        const newSrc = String(newUrl || "").trim();
        if (!oldSrc || !newSrc) return false;
        const imgs = cr.querySelectorAll("img");
        let changed = false;
        imgs.forEach((img) => {
            const src = String(img.getAttribute("src") || "").trim();
            if (src === oldSrc) {
                img.setAttribute("src", newSrc);
                changed = true;
            }
        });
        if (changed) {
            const taSync = byId("content");
            if (taSync) taSync.value = String(cr.innerHTML || "");
            refreshPreview();
            saveFormState();
        }
        return changed;
    };
    const normalizeEditorImages = () => {
        const cr = byId("contentRender");
        if (!cr) return;
        // Ensure each image lives in its own figure so delete works per-image.
        const figures = Array.from(cr.querySelectorAll("figure.editor-image"));
        figures.forEach((fig) => {
            const imgs = Array.from(fig.querySelectorAll("img"));
            if (!imgs.length) return;
            if (imgs.length === 1) return;
            const parent = fig.parentNode;
            if (!parent) return;
            imgs.forEach((img, idx) => {
                const holder = document.createElement("figure");
                holder.className = "editor-image";
                if (idx === 0) {
                    fig.replaceWith(holder);
                } else {
                    parent.insertBefore(holder, fig.nextSibling);
                }
                holder.appendChild(img);
            });
        });
        // Wrap naked img tags into a dedicated figure container.
        Array.from(cr.querySelectorAll("img")).forEach((img) => {
            if (img.closest("figure.editor-image")) return;
            const fig = document.createElement("figure");
            fig.className = "editor-image";
            img.replaceWith(fig);
            fig.appendChild(img);
        });
    };
    const insertImageIntoEditor = (url) => {
        const src = String(url || "").trim();
        if (!src) return;
        const usable =
            /^https?:\/\//i.test(src) ||
            src.startsWith("/static/") ||
            src.startsWith("/api/user-files/") ||
            /^data:image\/(jpeg|jpg|png|webp|gif)/i.test(src);
        if (!usable || (/\s/.test(src) && !/\.(jpe?g|png|webp|gif)/i.test(src))) {
            try {
                window.alert("URL ảnh không hợp lệ — cần https hoặc /static/.");
            } catch (_) {}
            return;
        }
        const snippet = `<p><br></p><figure class="editor-image"><img src="${src.replace(/"/g, "&quot;")}" alt="Ảnh minh họa" loading="lazy" style="max-width:100%;height:auto;" /></figure><p><br></p>`;
        try {
            if (window.tinymce && tinymce.get("content")) {
                tinymce.get("content").insertContent(snippet);
                tinymce.get("content").save();
                saveFormState();
                return;
            }
        } catch (_) {}
        // contenteditable fallback (no TinyMCE)
        const cr = byId("contentRender");
        if (cr) {
            try { cr.focus(); } catch (_) {}
            try {
                const sel = window.getSelection ? window.getSelection() : null;
                let range = null;
                if (lastEditorRange && cr.contains(lastEditorRange.startContainer)) {
                    range = lastEditorRange.cloneRange();
                } else if (sel && sel.rangeCount > 0 && cr.contains(sel.getRangeAt(0).startContainer)) {
                    range = sel.getRangeAt(0).cloneRange();
                } else {
                    range = document.createRange();
                    range.selectNodeContents(cr);
                    range.collapse(false);
                }
                const holder = document.createElement("div");
                holder.innerHTML = snippet;
                const frag = document.createDocumentFragment();
                let lastNode = null;
                while (holder.firstChild) {
                    lastNode = holder.firstChild;
                    frag.appendChild(lastNode);
                }
                range.deleteContents();
                range.insertNode(frag);
                if (lastNode) {
                    const after = document.createRange();
                    after.setStartAfter(lastNode);
                    after.collapse(true);
                    if (sel) {
                        sel.removeAllRanges();
                        sel.addRange(after);
                    }
                    lastEditorRange = after.cloneRange();
                }
            } catch (_) {
                cr.innerHTML = `${String(cr.innerHTML || "")}\n${snippet}`;
            }
            normalizeEditorImages();
            const taSync = byId("content");
            if (taSync) taSync.value = String(cr.innerHTML || "");
            refreshPreview();
            saveFormState();
            return;
        }
        // textarea fallback
        const el = byId("content");
        const snippetText = `\n\n<img src="${src}" alt="" loading="lazy" />\n\n`;
        if (el) el.value = (el.value || "") + snippetText;
        saveFormState();
    };

    const cropBackdrop = byId("cropBackdrop");
    const cropModal = byId("cropModal");
    const cropImage = byId("cropImage");
    const btnCropClose = byId("btnCropClose");
    const btnCropInsert = byId("btnCropInsert");
    const btnCropRotateL = byId("btnCropRotateL");
    const btnCropRotateR = byId("btnCropRotateR");
    const btnCropZoomIn = byId("btnCropZoomIn");
    const btnCropZoomOut = byId("btnCropZoomOut");
    let cropper = null;
    let cropSourceUrl = "";

    const closeCropModal = () => {
        try { if (cropper) cropper.destroy(); } catch (_) {}
        cropper = null;
        cropSourceUrl = "";
        cropModal.style.display = "none";
        cropBackdrop.style.display = "none";
        cropModal.setAttribute("aria-hidden", "true");
    };

    const openCropModal = async (url) => {
        const src = String(url || "").trim();
        if (!src) return;
        const ok = await ensureCropperLoaded();
        if (!ok) {
            setHint("image", "Không tải được thư viện cắt ảnh (Cropper). Vui lòng thử lại hoặc upload lại ảnh để tự chèn vào Content.");
            return;
        }
        cropSourceUrl = src;
        cropImage.src = src;
        cropModal.style.display = "block";
        cropBackdrop.style.display = "block";
        cropModal.setAttribute("aria-hidden", "false");
        // Wait image to load
        await new Promise((r) => {
            if (cropImage.complete) return r();
            cropImage.onload = r;
            cropImage.onerror = r;
        });
        try { if (cropper) cropper.destroy(); } catch (_) {}
        cropper = new Cropper(cropImage, {
            viewMode: 1,
            dragMode: "move",
            autoCropArea: 0.9,
            responsive: true,
            background: false,
        });
    };

    btnCropClose.addEventListener("click", closeCropModal);
    cropBackdrop.addEventListener("click", closeCropModal);
    btnCropRotateL.addEventListener("click", () => { if (cropper) cropper.rotate(-90); });
    btnCropRotateR.addEventListener("click", () => { if (cropper) cropper.rotate(90); });
    btnCropZoomIn.addEventListener("click", () => { if (cropper) cropper.zoom(0.1); });
    btnCropZoomOut.addEventListener("click", () => { if (cropper) cropper.zoom(-0.1); });

    let selectedEditorFigure = null;
    let currentHoverLinkEl = null;
    let linkToolsHideTimer = null;
    const linkHoverTools = document.createElement("div");
    linkHoverTools.className = "link-hover-tools";
    linkHoverTools.innerHTML = `
        <button type="button" class="mini-btn" id="btnEditHoveredLink">Edit link</button>
        <button type="button" class="mini-btn danger" id="btnRemoveHoveredLink">Xóa link</button>
    `;
    document.body.appendChild(linkHoverTools);
    const btnEditHoveredLink = byId("btnEditHoveredLink");
    const btnRemoveHoveredLink = byId("btnRemoveHoveredLink");
    const hideLinkTools = () => {
        if (linkToolsHideTimer) {
            clearTimeout(linkToolsHideTimer);
            linkToolsHideTimer = null;
        }
        linkHoverTools.classList.remove("show");
        currentHoverLinkEl = null;
    };
    const scheduleHideLinkTools = (ms = 220) => {
        if (linkToolsHideTimer) clearTimeout(linkToolsHideTimer);
        linkToolsHideTimer = window.setTimeout(() => {
            if (!linkHoverTools.matches(":hover")) hideLinkTools();
        }, ms);
    };
    const showLinkToolsFor = (aEl) => {
        if (!aEl) return;
        currentHoverLinkEl = aEl;
        const r = aEl.getBoundingClientRect();
        const left = Math.max(8, Math.min(window.innerWidth - 220, r.left));
        const top = Math.max(8, r.top - 40);
        linkHoverTools.style.left = `${left}px`;
        linkHoverTools.style.top = `${top}px`;
        linkHoverTools.classList.add("show");
    };
    if (btnEditHoveredLink) {
        btnEditHoveredLink.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const a = currentHoverLinkEl;
            if (!a) return;
            const cur = String(a.getAttribute("href") || "").trim();
            const next = window.prompt("Nhập URL mới:", cur || "https://");
            if (!next) return;
            a.setAttribute("href", next.trim());
            a.setAttribute("target", "_blank");
            a.setAttribute("rel", "noopener");
            syncEditorHtmlState();
            hideLinkTools();
        });
    }
    if (btnRemoveHoveredLink) {
        btnRemoveHoveredLink.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            const a = currentHoverLinkEl;
            if (!a) return;
            const txt = document.createTextNode(String(a.textContent || ""));
            a.replaceWith(txt);
            syncEditorHtmlState();
            hideLinkTools();
        });
    }
    linkHoverTools.addEventListener("mouseenter", () => {
        if (linkToolsHideTimer) {
            clearTimeout(linkToolsHideTimer);
            linkToolsHideTimer = null;
        }
    });
    linkHoverTools.addEventListener("mouseleave", () => {
        scheduleHideLinkTools(120);
    });
    let lastEditorRange = null;
    const rememberEditorSelection = () => {
        try {
            const cr = byId("contentRender");
            if (!cr) return;
            const sel = window.getSelection ? window.getSelection() : null;
            if (!sel || sel.rangeCount < 1) return;
            const range = sel.getRangeAt(0);
            const node = range.commonAncestorContainer;
            if (cr.contains(node)) {
                lastEditorRange = range.cloneRange();
            }
        } catch (_) {}
    };
    const restoreEditorSelection = () => {
        try {
            const cr = byId("contentRender");
            if (!cr) return false;
            if (!lastEditorRange) {
                const range = document.createRange();
                range.selectNodeContents(cr);
                range.collapse(false);
                const sel0 = window.getSelection ? window.getSelection() : null;
                if (!sel0) return false;
                sel0.removeAllRanges();
                sel0.addRange(range);
                return true;
            }
            const sel = window.getSelection ? window.getSelection() : null;
            if (!sel) return false;
            sel.removeAllRanges();
            sel.addRange(lastEditorRange);
            return true;
        } catch (_) {
            return false;
        }
    };
    const syncEditorHtmlState = () => {
        try {
            const cr = byId("contentRender");
            const ta = byId("content");
            if (cr && ta) ta.value = String(cr.innerHTML || "");
            refreshPreview();
            saveFormState();
        } catch (_) {}
    };
    const clearSelectedEditorFigure = () => {
        try {
            if (!selectedEditorFigure) return;
            selectedEditorFigure.classList.remove("selected");
            const btn = selectedEditorFigure.querySelector(".img-action-delete");
            if (btn) btn.remove();
        } catch (_) {}
        selectedEditorFigure = null;
    };
    const deleteFigureElement = (fig) => {
        if (!fig) return;
        try {
            if (selectedEditorFigure === fig) clearSelectedEditorFigure();
            fig.remove();
            normalizeEditorImages();
            syncEditorHtmlState();
        } catch (_) {}
    };
    const deleteSelectedEditorFigure = () => {
        if (!selectedEditorFigure) return;
        deleteFigureElement(selectedEditorFigure);
    };
    const selectEditorImage = (imgEl) => {
        const cr = byId("contentRender");
        if (!cr || !imgEl) return;
        let fig = imgEl.closest("figure.editor-image");
        if (!fig) {
            fig = document.createElement("figure");
            fig.className = "editor-image";
            const clone = imgEl.cloneNode(true);
            fig.appendChild(clone);
            imgEl.replaceWith(fig);
        }
        clearSelectedEditorFigure();
        selectedEditorFigure = fig;
        selectedEditorFigure.classList.add("selected");
        let btn = selectedEditorFigure.querySelector(".img-action-delete");
        if (!btn) {
            btn = document.createElement("button");
            btn.type = "button";
            btn.className = "img-action-delete";
            btn.textContent = "Xóa ảnh";
            btn.setAttribute("contenteditable", "false");
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                deleteFigureElement(fig);
            });
            selectedEditorFigure.appendChild(btn);
        }
    };

    const uploadCroppedBlob = async (blob) => {
        const fd = new FormData();
        fd.append("file", blob, `crop-${Date.now()}.png`);
        const res = await fetch(`/content-ai/upload-image?ts=${Date.now()}`, { method: "POST", body: fd });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Upload ảnh đã cắt thất bại");
        if (!data || !data.url) throw new Error("Upload ảnh đã cắt thất bại");
        return data.url;
    };

    btnCropInsert.addEventListener("click", async () => {
        if (!cropper) return;
        try {
            btnCropInsert.disabled = true;
            setHint("image", "Đang cắt & upload ảnh...");
            const canvas = cropper.getCroppedCanvas({ imageSmoothingEnabled: true, imageSmoothingQuality: "high" });
            const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png", 0.92));
            if (!blob) throw new Error("Không tạo được ảnh đã cắt");
            const url = await uploadCroppedBlob(blob);
            const srcOld = String(cropSourceUrl || "").trim();
            const idxOld = uploadedImages.findIndex((u) => String(u || "").trim() === srcOld);
            if (idxOld >= 0) uploadedImages[idxOld] = url;
            else uploadedImages.push(url);
            renderUploadList();
            if (!replaceImageInEditor(srcOld, url)) {
                insertImageIntoEditor(url);
            }
            setHint("image", "Đã cắt và chèn ảnh vào Content.");
            saveFormState();
            closeCropModal();
        } catch (e) {
            setHint("image", String(e.message || e));
        } finally {
            btnCropInsert.disabled = false;
        }
    });
    const fmtDate = (iso) => {
        if (!iso) return "";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleString("vi-VN");
    };
    const applyProjectToForm = (p) => {
        if (!p) return;
        if (p.id) activeProjectId = String(p.id);
        _draftWpCategoryIds = null;
        const d = p.draft_output;
        if (d && typeof d === "object" && Array.isArray(d.categories) && d.categories.length) {
            _draftWpCategoryIds = d.categories
                .map((x) => parseInt(x, 10))
                .filter((n) => !Number.isNaN(n) && n > 0);
        } else {
            const wk = parseInt(p.wp_category_id, 10);
            if (!Number.isNaN(wk) && wk > 0) {
                _draftWpCategoryIds = [wk];
            }
        }
        byId("title").value = p.title || "";
        byId("slug").value = p.slug || "";
        byId("targetWebsite").value = p.target_website || "";
        fillSingleWpCategorySelect(
            _draftWpCategoryIds && _draftWpCategoryIds[0] ? String(_draftWpCategoryIds[0]) : ""
        );
        try { scheduleSingleWpCategoriesLoad(); } catch (_) {}
        byId("primaryKeyword").value = p.primary_keyword || "";
        byId("secondaryKeywords").value = (p.secondary_keywords || []).join(", ");
        byId("outlineContent").value = p.outline_content || "";
        try {
            autoGrowOutline();
        } catch (_) {}
        byId("meta").value = p.meta_description || "";
        byId("tags").value = (p.tags || []).join(", ");
        setContentValue(p.content || "");
        byId("scheduledAt").value = p.scheduled_at || "";
        uploadedImages.length = 0;
        for (const u of (p.gallery_images || [])) {
            const sUrl = String(u || "").trim().split("?")[0];
            if (sUrl && (sUrl.startsWith("/api/user-files/") || sUrl.startsWith("/static/"))) {
                uploadedImages.push(sUrl);
            }
        }
        if ((p.featured_image || "").trim()) {
            const f = String(p.featured_image).trim().split("?")[0];
            if (f && (f.startsWith("/api/user-files/") || f.startsWith("/static/")) && !uploadedImages.includes(f)) {
                uploadedImages.unshift(f);
            }
        }
        renderUploadList();
        if (getOutputFormat() === "json") {
            if (p.draft_output) out.value = JSON.stringify(p.draft_output, null, 2);
        } else {
            out.value = p.content || "";
        }
        toggleAiAvailability();
        try {
            refreshPreview();
        } catch (_) {}
        saveFormState();
        try {
            renderCustomLinkLibrary();
        } catch (_) {}
    };

    const initRichEditor = async () => {
        try {
            if (!USE_TINYMCE) {
                editorMode = "visual";
                if (editorTools) editorTools.style.display = "flex";
                refreshEditorModeUi();
                syncPreviewFallback();
                return;
            }
            // Wait briefly for TinyMCE script to load
            for (let i = 0; i < 40; i++) {
                if (window.__tinymceReady && window.tinymce) break;
                await new Promise((r) => setTimeout(r, 100));
            }
            if (!window.__tinymceReady || !window.tinymce) {
                editorMode = "visual";
                if (editorTools) editorTools.style.display = "flex";
                refreshEditorModeUi();
                syncPreviewFallback();
                return;
            }
            const textarea = byId("content");
            if (!textarea) return;
            textarea.style.display = "block";
            await tinymce.init({
                selector: "#content",
                height: 520,
                min_height: 420,
                resize: true,
                menubar: false,
                branding: false,
                toolbar_mode: "wrap",
                block_formats: "Paragraph=p; Heading 2=h2; Heading 3=h3; Heading 4=h4",
                font_size_formats: "10pt 11pt 12pt 14pt 18pt 24pt 36pt",
                plugins:
                    "advlist autolink lists link image table code charmap searchreplace visualblocks fullscreen nonbreaking wordcount",
                toolbar1:
                    "blocks | bold italic underline blockquote | bullist numlist | alignleft aligncenter alignright | link unlink | undo redo | removeformat | code",
                toolbar2:
                    "fontfamily fontsize | forecolor backcolor | outdent indent | table charmap | superscript subscript | visualblocks fullscreen",
                images_upload_handler: async (blobInfo) => {
                    const fd = new FormData();
                    fd.append("file", blobInfo.blob(), blobInfo.filename());
                    const res = await fetch(`/content-ai/upload-image?ts=${Date.now()}`, { method: "POST", body: fd });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Upload ảnh thất bại");
                    if (!data || !data.url) throw new Error("Upload ảnh thất bại");
                    return data.url;
                },
                setup: (editor) => {
                    const enforceTinyVisibility = () => {
                        try {
                            const container = editor.getContainer ? editor.getContainer() : null;
                            const body = editor.getBody ? editor.getBody() : null;
                            if (container) {
                                container.style.opacity = "1";
                                container.style.visibility = "visible";
                                container.style.display = "block";
                            }
                            if (body) {
                                body.style.opacity = "1";
                                body.style.visibility = "visible";
                                body.style.display = "block";
                                body.style.color = "#0f172a";
                                body.style.background = "#ffffff";
                            }
                        } catch (_) {}
                    };
                    editor.on("change keyup SetContent", () => {
                        try { schedulePublishChecklist(); } catch (_) {}
                    });
                    editor.on("init", () => {
                        try {
                            const ta = byId("content");
                            const cr = byId("contentRender");
                            const seed = String((ta && ta.value) || (cr && cr.innerHTML) || "").trim();
                            const cur = String(editor.getContent({ format: "html" }) || "").trim();
                            if (!cur && seed) {
                                editor.setContent(seed);
                            }
                        } catch (_) {}
                        try { editor.save(); } catch (_) {}
                        try { refreshPreview(); } catch (_) {}
                        try { schedulePublishChecklist(); } catch (_) {}
                        if (editorTools) editorTools.style.display = "flex";
                        editorMode = "visual";
                        refreshEditorModeUi();
                        enforceTinyVisibility();
                        window.setTimeout(ensureEditorVisible, 120);
                        window.setTimeout(ensureEditorVisible, 360);
                    });
                    editor.on("change keyup", () => {
                        try { editor.save(); } catch (_) {}
                        scheduleSaveFormState();
                        // update stats from editor changes
                        try { refreshPreview(); } catch (_) {}
                        enforceTinyVisibility();
                    });
                    editor.on("SetContent NodeChange", enforceTinyVisibility);
                },
                content_css: "/static/css/digiseo-tables.css?v=3",
                content_style:
                    "html{color-scheme:light} body{font-family:Inter,system-ui,sans-serif;font-size:15px;line-height:1.7;background:#ffffff !important;color:#0f172a !important;opacity:1 !important} p,li,span,div{color:#0f172a !important;opacity:1 !important} h1,h2,h3,h4,h5,h6{color:#0f172a !important;line-height:1.25;font-weight:800;opacity:1 !important} a{color:#2563eb !important}"
                    + " table{border:2px dashed #0f172a !important;border-collapse:collapse} th,td{border:2px dashed #0f172a !important;color:#0f172a !important;font-weight:500;opacity:1 !important}"
                    + " thead th{background:#43a047 !important;color:#fff !important;font-weight:700}",
            });
        } catch (_) {
            // fallback to textarea
            editorMode = "visual";
            if (editorTools) editorTools.style.display = "flex";
            refreshEditorModeUi();
            syncPreviewFallback();
        } finally {
            try {
                refreshPreview();
            } catch (_) {}
        }
    };
    const projectDisplayLabel = (item) =>
        String((item && (item.title || item.primary_keyword)) || "(Không tiêu đề)").trim();
    const deleteContentAiProject = async (projectId, label) => {
        const pid = String(projectId || "").trim();
        if (!pid) return false;
        const name = String(label || "").trim() || "mục này";
        const ok = await confirmDeleteDialog(
            `Bạn có chắc muốn xóa «${name}»?\nDữ liệu bài viết sẽ bị xóa vĩnh viễn và không thể khôi phục.`,
            "Xác nhận xóa dự án"
        );
        if (!ok) return false;
        try {
            let res = await fetch(`/content-ai/projects/${encodeURIComponent(pid)}/delete`, {
                method: "POST",
                headers: authJsonHeaders(),
            });
            if (res.status === 404 || res.status === 405) {
                res = await fetch(`/content-ai/projects/${encodeURIComponent(pid)}`, {
                    method: "DELETE",
                    headers: authHeaders(),
                });
            }
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Xóa dự án thất bại.");
            if (activeProjectId === pid) activeProjectId = "";
            if (msg) msg.textContent = "Đã xóa dự án.";
            await refreshProjects(false);
            return true;
        } catch (e) {
            if (msg) msg.textContent = String(e.message || e);
            return false;
        }
    };
