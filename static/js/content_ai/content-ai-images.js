    /* AI Visual Content Studio */
    const getStudioGalleryEl = () => byId("studioGallery");
    let studioGallery = getStudioGalleryEl();
    const studioIncludeText = byId("studioIncludeText");
    const studioTextHintWrap = byId("studioTextHintWrap");
    let studioPreviews = [];
    let studioSelectedIndex = 0;
    let studioCatalogCache = null;
    let _pendingMediaPanelRestore = null;

    const setGoogleImageHint = (text) => {
        const msg = String(text || "").trim();
        const el = byId("hint-google-images");
        if (!el) return;
        el.textContent = msg;
        if (msg) el.removeAttribute("hidden");
        else el.setAttribute("hidden", "");
    };

    const clearConflictingMediaHints = ({ keepStudio = false } = {}) => {
        // Stale web-import errors used to remain under AI success ("Không tải được ảnh: fetch_error").
        setGoogleImageHint("");
        if (!keepStudio) {
            const vs = byId("hint-visual-studio");
            if (vs) {
                vs.textContent = "";
                vs.setAttribute("hidden", "");
            }
        }
    };

    const updateMediaResultsLabel = (n, kind) => {
        const label = byId("mediaResultsLabel");
        if (!label) return;
        const count = Math.max(0, parseInt(n || 0, 10) || 0);
        if (count <= 0) {
            label.setAttribute("hidden", "");
            label.textContent = "Kết quả ảnh";
            return;
        }
        const kindLabel = kind === "web" ? "ảnh web" : "ảnh preview AI";
        label.textContent = `Kết quả: ${count} ${kindLabel} — chọn ảnh rồi bấm Chèn / Featured.`;
        label.removeAttribute("hidden");
    };

    const _mediaPanelVal = (id) => {
        const el = byId(id);
        return el ? String(el.value || "").trim() : "";
    };

    const collectMediaPanelState = () => {
        const panel = byId("contentAiMediaPanel");
        const activeCard = panel
            ? panel.querySelector(".ca-media-source-card.active")
            : document.querySelector(".ca-media-source-card.active");
        const studioH2Checked = [];
        const list = byId("studioH2List");
        if (list) {
            list.querySelectorAll('input[type="checkbox"][data-h2-index]:checked').forEach((cb) => {
                studioH2Checked.push(String(cb.getAttribute("data-h2-index")));
            });
        }
        return {
            studioPreviews: studioPreviews.map((p) => ({ ...p })),
            studioSelectedIndex,
            googleImageItems: Array.isArray(window.__caGoogleImageResultsCache)
                ? window.__caGoogleImageResultsCache.slice()
                : [],
            googleImageQuery: _mediaPanelVal("googleImageQuery"),
            googleImageNum: _mediaPanelVal("googleImageNum") || "8",
            mediaSource: activeCard ? activeCard.getAttribute("data-media-source") || "ai" : "ai",
            studioH2Checked,
            studioImageType: _mediaPanelVal("studioImageType"),
            studioStylePreset: _mediaPanelVal("studioStylePreset"),
            studioAspectRatio: _mediaPanelVal("studioAspectRatio"),
            studioImageCount: _mediaPanelVal("studioImageCount"),
            studioBrandTone: _mediaPanelVal("studioBrandTone"),
            studioCustomWidth: _mediaPanelVal("studioCustomWidth"),
            studioCustomHeight: _mediaPanelVal("studioCustomHeight"),
            studioIncludeText: !!(studioIncludeText && studioIncludeText.checked),
            studioTextHint: _mediaPanelVal("studioTextHint"),
            hintImage: String(byId("hint-image")?.textContent || "").trim(),
            hintGoogleImages: String(byId("hint-google-images")?.textContent || "").trim(),
            hintVisualStudio: String(byId("hint-visual-studio")?.textContent || "").trim(),
            mediaInsertSummary: String(byId("mediaInsertSummary")?.textContent || "").trim(),
        };
    };

    const applyMediaPanelState = (s) => {
        if (!s || typeof s !== "object") return;
        studioPreviews = Array.isArray(s.studioPreviews)
            ? s.studioPreviews.map((p) => ({ ...p }))
            : [];
        studioSelectedIndex = Number.isFinite(Number(s.studioSelectedIndex)) ? Number(s.studioSelectedIndex) : 0;
        if (studioSelectedIndex >= studioPreviews.length) studioSelectedIndex = 0;
        renderStudioGallery();

        if (typeof renderGoogleImageResults === "function") {
            renderGoogleImageResults(Array.isArray(s.googleImageItems) ? s.googleImageItems : []);
        }

        const setVal = (id, val) => {
            const el = byId(id);
            if (el && val != null && val !== "") el.value = String(val);
        };
        setVal("googleImageQuery", s.googleImageQuery);
        setVal("googleImageNum", s.googleImageNum);
        setVal("studioImageType", s.studioImageType);
        setVal("studioStylePreset", s.studioStylePreset);
        setVal("studioAspectRatio", s.studioAspectRatio);
        setVal("studioImageCount", s.studioImageCount);
        setVal("studioBrandTone", s.studioBrandTone);
        setVal("studioCustomWidth", s.studioCustomWidth);
        setVal("studioCustomHeight", s.studioCustomHeight);
        if (studioIncludeText) {
            studioIncludeText.checked = !!s.studioIncludeText;
            if (studioTextHintWrap) {
                studioTextHintWrap.style.display = studioIncludeText.checked ? "block" : "none";
            }
        }
        setVal("studioTextHint", s.studioTextHint);
        toggleStudioCustomSize();

        refreshStudioH2Select();
        if (Array.isArray(s.studioH2Checked) && s.studioH2Checked.length) {
            const h2List = byId("studioH2List");
            if (h2List) {
                h2List.querySelectorAll('input[type="checkbox"][data-h2-index]').forEach((cb) => {
                    cb.checked = s.studioH2Checked.includes(String(cb.getAttribute("data-h2-index")));
                });
            }
        }

        const src = String(s.mediaSource || "ai");
        const panel = byId("contentAiMediaPanel");
        const card = panel
            ? panel.querySelector(`.ca-media-source-card[data-media-source="${src}"]`)
            : document.querySelector(`.ca-media-source-card[data-media-source="${src}"]`);
        if (card && !card.classList.contains("active")) card.click();

        if (s.hintImage) setHint("image", s.hintImage);
        // Don't resurrect stale web-import errors under AI previews.
        if (s.hintGoogleImages) {
            const g = String(s.hintGoogleImages || "").trim();
            const staleImportErr =
                studioPreviews.length > 0 && /Không tải được ảnh|fetch_error/i.test(g);
            setHint("google-images", staleImportErr ? "" : g);
        }
        if (s.hintVisualStudio) setStudioHint(s.hintVisualStudio);
        if (s.mediaInsertSummary && typeof showMediaInsertSummary === "function") {
            showMediaInsertSummary(s.mediaInsertSummary);
        }
    };

    const restoreMediaPanelState = (s) => {
        _pendingMediaPanelRestore = s;
        applyMediaPanelState(s);
    };

    const extractH2ForStudio = () => {
        const html = String(getContentValue() || "");
        const outline = String(byId("outlineContent")?.value || "");
        const out = [];
        const re = /<h2\b[^>]*>(.*?)<\/h2>/gi;
        let m;
        while ((m = re.exec(html))) {
            const t = String(m[1] || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
            if (t && !out.includes(t)) out.push(t);
        }
        outline.split("\n").forEach((line) => {
            const mm = /^##\s+(.+?)\s*$/.exec(line.trim());
            if (mm) {
                const t = mm[1].trim();
                if (t && !out.includes(t)) out.push(t);
            }
        });
        return out.slice(0, 12);
    };

    const getStudioH2CheckedKeys = () => {
        const list = byId("studioH2List");
        if (!list) return new Set();
        const keys = new Set();
        list.querySelectorAll('input[type="checkbox"][data-h2-index]:checked').forEach((cb) => {
            keys.add(String(cb.getAttribute("data-h2-index")));
        });
        return keys;
    };

    const refreshStudioH2Select = () => {
        const list = byId("studioH2List");
        if (!list) return;
        const checked = getStudioH2CheckedKeys();
        const h2s = extractH2ForStudio();
        if (!h2s.length) {
            list.innerHTML = '<span class="hint">Chưa có H2 trong bài — thêm heading H2 trong content.</span>';
            return;
        }
        list.innerHTML = "";
        h2s.forEach((h, i) => {
            const label = document.createElement("label");
            label.className = "studio-h2-item";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.setAttribute("data-h2-index", String(i));
            cb.setAttribute("data-h2-heading", h);
            if (checked.has(String(i)) || (!checked.size && i === 0)) cb.checked = true;
            const span = document.createElement("span");
            span.textContent = h;
            label.appendChild(cb);
            label.appendChild(span);
            list.appendChild(label);
        });
    };

    const getSelectedStudioH2s = () => {
        const list = byId("studioH2List");
        if (!list) return [];
        const out = [];
        list.querySelectorAll('input[type="checkbox"][data-h2-index]:checked').forEach((cb) => {
            out.push({
                index: parseInt(cb.getAttribute("data-h2-index"), 10),
                heading: cb.getAttribute("data-h2-heading") || "",
            });
        });
        return out.filter((x) => Number.isFinite(x.index) && x.heading);
    };

    const toggleStudioCustomSize = () => {
        const ar = byId("studioAspectRatio");
        const wrap = byId("studioCustomSizeWrap");
        if (!wrap || !ar) return;
        wrap.classList.toggle("visible", ar.value === "custom");
    };

    const fillStudioSelect = (elId, items, valueKey, labelKey) => {
        const el = byId(elId);
        if (!el || !Array.isArray(items)) return;
        el.innerHTML = "";
        items.forEach((it) => {
            const opt = document.createElement("option");
            opt.value = it[valueKey] || it.id || "";
            opt.textContent = it[labelKey] || it.label_vi || opt.value;
            el.appendChild(opt);
        });
    };

    const loadStudioCatalog = async () => {
        if (studioCatalogCache) return studioCatalogCache;
        try {
            const res = await apiFetch("/content-ai/images/studio-presets?ts=" + Date.now());
            const data = await res.json().catch(() => ({}));
            if (res.ok) studioCatalogCache = data;
        } catch (_) {}
        return studioCatalogCache || {};
    };

    const initVisualStudio = async () => {
        const cat = await loadStudioCatalog();
        fillStudioSelect("studioImageType", cat.image_types || [], "id", "label_vi");
        fillStudioSelect("studioStylePreset", cat.style_presets || [], "id", "label_vi");
        fillStudioSelect("studioAspectRatio", cat.aspect_ratios || [], "id", "label_vi");
        fillStudioSelect("studioBrandTone", cat.brand_tones || [], "id", "label_vi");
        fillStudioSelect("studioImageModel", cat.image_models || [], "id", "label_vi");
        const modelEl = byId("studioImageModel");
        if (modelEl && cat.default_image_model) {
            modelEl.value = cat.default_image_model;
        }
        toggleStudioCustomSize();
        refreshStudioH2Select();
        if (_pendingMediaPanelRestore) applyMediaPanelState(_pendingMediaPanelRestore);
    };

    const openStudioLightbox = (url) => {
        const box = byId("studioLightbox");
        const img = byId("studioLightboxImg");
        if (!box || !img || !url) return;
        img.src = url;
        box.classList.add("open");
        box.setAttribute("aria-hidden", "false");
    };
    const closeStudioLightbox = () => {
        const box = byId("studioLightbox");
        const img = byId("studioLightboxImg");
        if (!box) return;
        box.classList.remove("open");
        box.setAttribute("aria-hidden", "true");
        if (img) img.src = "";
    };

    const setStudioHint = (text) => {
        const msg = String(text || "").trim();
        const h = byId("hint-visual-studio");
        if (h) {
            h.textContent = msg;
            // Keep dual channel off-screen; user-facing copy is #hint-image
            h.setAttribute("hidden", "");
        }
        if (msg) setHint("image", msg);
    };

    const buildStudioGeneratePayload = (overrides = {}) => {
        const draft = buildDraftPayload();
        const selected = getSelectedStudioH2s();
        const arEl = byId("studioAspectRatio");
        const aspectRatio = (arEl && arEl.value) || "16:9";
        const custom = aspectRatio === "custom";
        const cw = parseInt(byId("studioCustomWidth")?.value || "800", 10);
        const ch = parseInt(byId("studioCustomHeight")?.value || "400", 10);
        const base = {
            project_id: activeProjectId || null,
            title: draft.title || "",
            primary_keyword: draft.primary_keyword || "",
            secondary_keywords: draft.secondary_keywords || [],
            content_html: draft.content || "",
            outline_content: draft.outline_content || "",
            section_heading: selected.length === 1 ? selected[0].heading : "",
            h2_index: selected.length === 1 ? selected[0].index : null,
            h2_headings: selected.map((s) => s.heading),
            h2_indices: selected.map((s) => s.index),
            target_audience: "",
            industry: "",
            brand_name: draft.target_website || "",
            brand_tone: (byId("studioBrandTone") && byId("studioBrandTone").value) || "professional",
            image_type: (byId("studioImageType") && byId("studioImageType").value) || "inline_h2",
            style_preset: (byId("studioStylePreset") && byId("studioStylePreset").value) || "seo_3d_premium",
            aspect_ratio: aspectRatio,
            custom_width: custom ? Math.max(256, Math.min(cw, 2048)) : null,
            custom_height: custom ? Math.max(256, Math.min(ch, 2048)) : null,
            count: Math.max(2, Math.min(4, parseInt(byId("studioImageCount")?.value || "3", 10) || 3)),
            include_text: !!(studioIncludeText && studioIncludeText.checked),
            text_hint: (byId("studioTextHint") && byId("studioTextHint").value.trim()) || "",
            image_model: (byId("studioImageModel") && byId("studioImageModel").value) || "",
        };
        return { ...base, ...overrides };
    };

    const getMediaModalScroller = () => {
        // Media modal scrolls on #caStepModalBody (not nested .ca-modal-body-scroll).
        const body = byId("caStepModalBody");
        if (body && body.querySelector(".ca-media-workspace")) return body;
        const panel = byId("contentAiMediaPanel");
        return (panel && panel.querySelector(".ca-modal-body-scroll")) || null;
    };

    const scrollStudioGalleryIntoView = () => {
        try {
            const scroller = getMediaModalScroller();
            const label = byId("mediaResultsLabel");
            const gal = getStudioGalleryEl() || byId("googleImageResults");
            const target = (label && !label.hasAttribute("hidden") && label) || gal;
            if (!target) return;
            if (scroller && scroller.contains(target)) {
                const tRect = target.getBoundingClientRect();
                const sRect = scroller.getBoundingClientRect();
                const nextTop = scroller.scrollTop + (tRect.top - sRect.top) - 10;
                scroller.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
            } else {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        } catch (_) {}
    };

    const resolveMediaImageUrl = (raw) => {
        let u = String(raw || "").trim();
        if (!u) return "";
        // Relative private user-files: cookie/HttpOnly handles same-origin; cache-bust for re-generate.
        if (u.startsWith("/api/user-files/") || u.startsWith("/static/")) {
            u += (u.includes("?") ? "&" : "?") + "v=" + Date.now();
        }
        return u;
    };

    const renderStudioGallery = () => {
        studioGallery = getStudioGalleryEl();
        if (!studioGallery) return;
        studioGallery.innerHTML = "";
        updateMediaResultsLabel(studioPreviews.length, "ai");
        if (!studioPreviews.length) return;
        studioPreviews.forEach((p, idx) => {
            const card = document.createElement("article");
            card.className = "ca-media-card ca-media-gallery-card visual-studio-card" + (idx === studioSelectedIndex ? " is-selected selected" : "");
            card.setAttribute("role", "listitem");
            const thumbBtn = document.createElement("button");
            thumbBtn.type = "button";
            thumbBtn.className = "ca-media-thumb-wrap";
            thumbBtn.setAttribute("aria-label", "Xem ảnh lớn");
            const img = document.createElement("img");
            const src = resolveMediaImageUrl(p.url);
            img.src = src;
            img.alt = p.alt || "Preview AI";
            img.loading = "eager";
            img.decoding = "async";
            img.className = "ca-media-thumb-img studio-thumb-click";
            img.draggable = false;
            img.onerror = () => {
                img.alt = "Không hiển thị được preview";
                img.style.opacity = "0.35";
                setStudioHint("Không hiển thị được preview (URL private hoặc lỗi mạng). Thử tạo lại.");
            };
            thumbBtn.addEventListener("click", (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                openStudioLightbox(p.url);
            });
            thumbBtn.appendChild(img);
            const body = document.createElement("div");
            body.className = "ca-media-gallery-card-body";
            const meta = document.createElement("div");
            meta.className = "ca-media-gallery-meta";
            meta.innerHTML = '<span class="ca-media-src-badge">AI</span><span class="ca-media-src-badge">Cao</span>';
            const h2 = p.section_heading
                ? (p.section_heading.length > 42 ? p.section_heading.slice(0, 40) + "…" : p.section_heading)
                : "Theo ngữ cảnh bài";
            const altLine = document.createElement("div");
            altLine.className = "hint";
            altLine.style.fontSize = "0.68rem";
            altLine.textContent = `ALT: ${String(p.alt || p.section_heading || byId("primaryKeyword")?.value || "minh họa").slice(0, 60)}`;
            const posLine = document.createElement("div");
            posLine.className = "hint";
            posLine.style.fontSize = "0.68rem";
            posLine.textContent = `Vị trí: ${h2}`;
            const btns = document.createElement("div");
            btns.className = "visual-studio-card-btns u-actions";
            btns.style.marginTop = "6px";
            const mk = (label, handler) => {
                const b = document.createElement("button");
                b.type = "button";
                b.className = "mini-btn";
                b.textContent = label;
                b.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    studioSelectedIndex = idx;
                    // Do NOT re-render gallery before async handlers — wipes listener mid-click.
                    try {
                        handler(p, idx);
                    } catch (err) {
                        setStudioHint(String((err && err.message) || err));
                    }
                });
                return b;
            };
            btns.appendChild(mk("Chọn", () => { void pickHeadingAndInsertStudio(p); }));
            btns.appendChild(mk("Chèn", () => { void studioInsertSelected(p, "inline"); }));
            btns.appendChild(mk("Featured", () => { void studioInsertSelected(p, "featured"); }));
            body.appendChild(meta);
            body.appendChild(altLine);
            body.appendChild(posLine);
            body.appendChild(btns);
            card.appendChild(thumbBtn);
            card.appendChild(body);
            card.addEventListener("click", (ev) => {
                if (ev.target.closest("button")) return;
                studioSelectedIndex = idx;
                renderStudioGallery();
            });
            studioGallery.appendChild(card);
        });
        // After cards render, ensure gallery is within the scrollable area
        requestAnimationFrame(() => scrollStudioGalleryIntoView());
    };

    const studioInsertSelected = async (preview, mode, placeOpts = null) => {
        const pk = String(byId("primaryKeyword")?.value || "").trim();
        if (!pk && mode !== "featured") {
            if (!(placeOpts && placeOpts.placement)) {
                setStudioHint("Cần từ khóa chính.");
                return { ok: false, reason: "need_keyword" };
            }
        }
        const payload = buildStudioGeneratePayload();
        // Always prefer live editor HTML (not a stale draft snapshot).
        const liveHtml = String(
            (typeof getContentValue === "function" ? getContentValue() : "") ||
                payload.content_html ||
                "",
        );
        let insertH2 = preview.section_heading || payload.section_heading || "";
        let insertIdx = preview.h2_index != null ? preview.h2_index : payload.h2_index;
        let insertH3 = null;
        let placement = "";
        if (placeOpts && typeof placeOpts === "object") {
            if (placeOpts.section_heading != null) insertH2 = String(placeOpts.section_heading || "");
            if (placeOpts.h2_index !== undefined) insertIdx = placeOpts.h2_index;
            if (placeOpts.h3_index !== undefined) insertH3 = placeOpts.h3_index;
            if (placeOpts.placement) placement = String(placeOpts.placement);
        }
        const cleanUrl = String(preview.url || "").trim().split("?")[0];
        if (!cleanUrl) {
            setStudioHint("Thiếu URL ảnh.");
            return { ok: false, reason: "no_url" };
        }
        setStudioHint(mode === "featured" ? "Đang đặt featured…" : "Đang chèn vào bài…");
        try {
            const body = {
                url: cleanUrl,
                mode,
                project_id: activeProjectId || null,
                content_html: liveHtml,
                title: payload.title || String(byId("title")?.value || "").trim(),
                primary_keyword: pk || String(byId("primaryKeyword")?.value || "").trim(),
                section_heading: insertH2 || "",
                alt: preview.alt || "",
            };
            if (insertIdx !== null && insertIdx !== undefined && insertIdx !== "") {
                body.h2_index = insertIdx;
            }
            if (insertH3 !== null && insertH3 !== undefined && insertH3 !== "") {
                body.h3_index = insertH3;
            }
            if (placement) body.placement = placement;

            const res = await fetch("/content-ai/images/insert-selected?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify(body),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : "Chèn ảnh thất bại");
            }
            if (data.skipped_duplicate) {
                setStudioHint(data.message || "Ảnh đã có trong bài — không chèn trùng.");
                setHint("image", data.message || "Không chèn trùng.");
                return { ok: false, reason: "duplicate", data };
            }

            // Prefer API content; fall back to client-side figure inject under the chosen heading.
            let nextHtml = String(data.content || "");
            const finalUrlBase = String(data.url || cleanUrl)
                .trim()
                .split("?")[0]
                .split("#")[0];
            const urlIn = (html) => {
                const h = String(html || "");
                if (!h) return false;
                if (finalUrlBase && h.includes(finalUrlBase)) return true;
                if (cleanUrl && h.includes(cleanUrl)) return true;
                // TinyMCE may expand relative → absolute host URL
                try {
                    if (finalUrlBase && h.includes(encodeURI(finalUrlBase))) return true;
                    if (finalUrlBase && window.location && h.includes(window.location.origin + finalUrlBase)) {
                        return true;
                    }
                } catch (_) {}
                return false;
            };
            if (mode === "inline" && !urlIn(nextHtml)) {
                nextHtml = clientInjectImageUnderHeading(liveHtml, {
                    url: finalUrlBase || cleanUrl,
                    alt: data.alt || preview.alt || "",
                    placement: placement || "after_heading",
                    section_heading: insertH2,
                    h2_index: insertIdx,
                    h3_index: insertH3,
                });
            }
            if (mode === "inline" && !urlIn(nextHtml)) {
                throw new Error("Chèn ảnh thất bại — không tìm thấy ảnh trong nội dung sau khi chèn.");
            }

            if (typeof _mediaContentBeforeInsert !== "undefined" && !_mediaContentBeforeInsert) {
                _mediaContentBeforeInsert = liveHtml;
            }

            // Write into editor (textarea + contentRender + TinyMCE). Avoid wiping via applyProjectToForm.
            if (nextHtml) {
                setContentValue(nextHtml);
            }

            // Force second path: if editor still missing image after TinyMCE quirks, inject client HTML again.
            const confirmEditorHasImage = () => {
                const after0 = String(
                    (typeof getContentValue === "function" ? getContentValue() : "") || "",
                );
                if (mode !== "inline") return true;
                if (urlIn(after0)) return true;
                setContentValue(nextHtml);
                const after1 = String(getContentValue() || "");
                if (urlIn(after1)) return true;
                // Last resort: append figure via insertImageIntoEditor (end of content)
                if (typeof insertImageIntoEditor === "function" && finalUrlBase) {
                    insertImageIntoEditor(finalUrlBase);
                }
                const after2 = String(getContentValue() || "");
                if (urlIn(after2)) return true;
                // Hard-append into raw HTML
                const forced =
                    after2 +
                    `<figure class="editor-image content-ai-inline-image"><img src="${String(finalUrlBase).replace(/"/g, "&quot;")}" alt="${String(data.alt || preview.alt || "Ảnh minh họa").replace(/"/g, "&quot;")}" loading="lazy" style="max-width:100%;height:auto;" /></figure>`;
                setContentValue(forced);
                return urlIn(String(getContentValue() || ""));
            };
            if (mode === "inline" && !confirmEditorHasImage()) {
                throw new Error("Ảnh chưa hiện trong editor sau khi đồng bộ. Thử lại.");
            }

            // Rebuild "Đã chèn" from editor + this insert only (no dead external URLs).
            const finalUrl = finalUrlBase || cleanUrl;
            if (typeof window.__caRebuildUploadedImagesList === "function") {
                window.__caRebuildUploadedImagesList({
                    url: mode === "inline" ? finalUrl : "",
                    featured: mode === "featured" ? (data.featured_image || finalUrl) : (data.featured_image || ""),
                    extra: Array.isArray(data.gallery_images) ? data.gallery_images : [],
                });
            } else {
                if (mode === "featured" && (data.featured_image || finalUrl)) {
                    const f = String(data.featured_image || finalUrl).split("?")[0];
                    if (f && !uploadedImages.includes(f)) uploadedImages.unshift(f);
                } else if (finalUrl && !uploadedImages.includes(finalUrl)) {
                    uploadedImages.push(finalUrl);
                }
                renderUploadList();
            }

            try { refreshPreview(); } catch (_) {}
            try {
                if (window.__caRefreshContentDemo) {
                    window.__caRefreshContentDemo("caMediaDemoPreview", "media");
                }
            } catch (_) {}
            saveFormState();

            const placeMeta = data.placement || {};
            const placeLabel =
                placeMeta.placement === "start"
                    ? "đầu bài"
                    : placeMeta.placement === "end"
                      ? "cuối bài"
                      : insertH2 ||
                        (placeMeta.h3_index != null ? `H3 #${placeMeta.h3_index + 1}` : "sau heading");
            setStudioHint(data.message || (mode === "featured" ? "Đã đặt ảnh đại diện." : "Đã chèn ảnh vào bài."));
            setHint(
                "image",
                mode === "featured" ? "Featured từ AI Studio." : `Đã chèn ảnh — ${placeLabel}. Kiểm tra editor / tab Xem demo.`,
            );
            if (typeof showMediaInsertSummary === "function") {
                showMediaInsertSummary(
                    mode === "featured"
                        ? "1 ảnh featured — ALT từ ngữ cảnh H2."
                        : `1 ảnh inline — vị trí: ${placeLabel}.`,
                );
            }
            // Only switch tab after verified insert
            if (typeof window.__caSwitchMediaInsertedTab === "function") {
                window.__caSwitchMediaInsertedTab();
            } else if (window.__caSwitchModalTab) {
                window.__caSwitchModalTab(byId("contentAiMediaPanel"), 2);
            }
            const undoBtn = byId("btnMediaUndo");
            if (undoBtn) undoBtn.hidden = false;
            return { ok: true, data };
        } catch (e) {
            setStudioHint(String(e.message || e));
            setHint("image", String(e.message || e));
            return { ok: false, reason: "error", error: e };
        }
    };

    const clientInjectImageUnderHeading = (html, opts) => {
        const src = String(opts.url || "").trim();
        if (!src) return String(html || "");
        const alt = String(opts.alt || "Ảnh minh họa").replace(/"/g, "&quot;");
        const fig =
            `<figure class="editor-image content-ai-inline-image">` +
            `<img src="${src.replace(/"/g, "&quot;")}" alt="${alt}" loading="lazy" ` +
            `style="max-width:100%;height:auto;" /></figure>`;
        const placement = String(opts.placement || "after_heading");
        let raw = String(html || "");
        if (raw.includes(src)) return raw;
        if (placement === "start") return fig + raw;
        if (placement === "end") return raw + fig;
        try {
            const doc = new DOMParser().parseFromString(
                raw || "<div></div>",
                "text/html",
            );
            const body = doc.body;
            const heads = Array.from(body.querySelectorAll("h2, h3"));
            let target = null;
            if (opts.h3_index != null && Number.isFinite(Number(opts.h3_index))) {
                const h3s = Array.from(body.querySelectorAll("h3"));
                target = h3s[Number(opts.h3_index)] || null;
            } else if (opts.h2_index != null && Number.isFinite(Number(opts.h2_index))) {
                const h2s = Array.from(body.querySelectorAll("h2"));
                target = h2s[Number(opts.h2_index)] || null;
            }
            if (!target && opts.section_heading) {
                const want = String(opts.section_heading).replace(/\s+/g, " ").trim().toLowerCase();
                target =
                    heads.find(
                        (el) =>
                            String(el.textContent || "")
                                .replace(/\s+/g, " ")
                                .trim()
                                .toLowerCase() === want,
                    ) || null;
            }
            if (!target) {
                return raw + fig;
            }
            const holder = doc.createElement("div");
            holder.innerHTML = fig;
            const node = holder.firstChild;
            if (target.nextSibling) target.parentNode.insertBefore(node, target.nextSibling);
            else target.parentNode.appendChild(node);
            return body.innerHTML;
        } catch (_) {
            return raw + fig;
        }
    };

    const listContentHeadingsForInsert = () => {
        const html = String(
            (typeof getContentValue === "function" ? getContentValue() : "") ||
                byId("content")?.value ||
                "",
        );
        if (!html.trim()) return [];
        try {
            const doc = new DOMParser().parseFromString(html, "text/html");
            const out = [];
            let h2i = -1;
            let h3i = -1;
            doc.body.querySelectorAll("h2, h3").forEach((el) => {
                const level = String(el.tagName || "").toLowerCase();
                const text = String(el.textContent || "").replace(/\s+/g, " ").trim();
                if (!text) return;
                if (level === "h2") {
                    h2i += 1;
                    out.push({ level: "h2", text, h2_index: h2i, h3_index: null });
                } else if (level === "h3") {
                    h3i += 1;
                    out.push({
                        level: "h3",
                        text,
                        h2_index: Math.max(0, h2i),
                        h3_index: h3i,
                    });
                }
            });
            return out;
        } catch (_) {
            return [];
        }
    };

    let _headingPickerResolve = null;
    const closeMediaHeadingPicker = (result) => {
        const modal = byId("mediaHeadingPickerModal");
        const backdrop = byId("mediaHeadingPickerBackdrop");
        if (modal) {
            modal.classList.remove("open");
            modal.setAttribute("aria-hidden", "true");
        }
        if (backdrop) {
            backdrop.classList.remove("open");
            backdrop.setAttribute("aria-hidden", "true");
        }
        const r = _headingPickerResolve;
        _headingPickerResolve = null;
        // Preserve falsy-but-valid results only when object is passed; null = cancelled
        if (r) r(result == null ? null : result);
    };

    const openMediaHeadingPicker = () =>
        new Promise((resolve) => {
            const modal = byId("mediaHeadingPickerModal");
            const backdrop = byId("mediaHeadingPickerBackdrop");
            const list = byId("mediaHeadingPickerList");
            const empty = byId("mediaHeadingPickerEmpty");
            if (!modal || !list) {
                resolve(null);
                return;
            }
            if (_headingPickerResolve) closeMediaHeadingPicker(null);
            _headingPickerResolve = resolve;
            list.innerHTML = "";
            const headings = listContentHeadingsForInsert();
            const mkBtn = (label, tag, onClick, extraClass) => {
                const b = document.createElement("button");
                b.type = "button";
                b.className = "ca-media-heading-pick-btn" + (extraClass ? " " + extraClass : "");
                b.setAttribute("role", "option");
                b.style.pointerEvents = "auto";
                if (tag) {
                    const t = document.createElement("span");
                    t.className = "tag";
                    t.textContent = tag;
                    t.style.pointerEvents = "none";
                    b.appendChild(t);
                }
                b.appendChild(document.createTextNode(label));
                const fire = (ev) => {
                    if (ev) {
                        ev.preventDefault();
                        ev.stopPropagation();
                    }
                    onClick();
                };
                // pointerup beats overlay/backdrop race better than click alone
                b.addEventListener("pointerup", fire);
                b.addEventListener("click", fire);
                return b;
            };
            if (!headings.length) {
                if (empty) empty.hidden = false;
                list.appendChild(
                    mkBtn("Đầu bài", "↑", () => closeMediaHeadingPicker({ placement: "start" }), "is-anchor"),
                );
                list.appendChild(
                    mkBtn("Cuối bài", "↓", () => closeMediaHeadingPicker({ placement: "end" }), "is-anchor"),
                );
            } else {
                if (empty) empty.hidden = true;
                headings.forEach((h) => {
                    const tag = h.level === "h3" ? "H3" : "H2";
                    const indent = h.level === "h3" ? " — " : "";
                    list.appendChild(
                        mkBtn(indent + h.text, tag, () =>
                            closeMediaHeadingPicker({
                                placement: "after_heading",
                                section_heading: h.text,
                                h2_index: h.h2_index,
                                h3_index: h.h3_index,
                                level: h.level,
                            }),
                        ),
                    );
                });
            }
            // Ensure floating above media step modal (body-level fixed)
            try {
                if (modal.parentElement !== document.body) document.body.appendChild(modal);
                if (backdrop && backdrop.parentElement !== document.body) {
                    document.body.appendChild(backdrop);
                }
                // Backdrop must paint under modal in DOM + CSS z-index
                if (backdrop && modal.compareDocumentPosition(backdrop) & Node.DOCUMENT_POSITION_FOLLOWING) {
                    document.body.insertBefore(backdrop, modal);
                }
            } catch (_) { /* ignore */ }
            if (backdrop) {
                backdrop.classList.add("open");
                backdrop.setAttribute("aria-hidden", "false");
                backdrop.style.zIndex = "100700";
            }
            modal.classList.add("open");
            modal.setAttribute("aria-hidden", "false");
            modal.style.zIndex = "100710";
            modal.style.pointerEvents = "none";
            const card = modal.querySelector(".modal-card");
            if (card) card.style.pointerEvents = "auto";
        });

    const pickHeadingAndInsertStudio = async (preview) => {
        const place = await openMediaHeadingPicker();
        if (!place) {
            setStudioHint("Đã hủy chọn vị trí chèn.");
            return;
        }
        const opts = {
            placement: place.placement || "after_heading",
            section_heading: place.section_heading || "",
            h2_index: place.level === "h3" ? null : place.h2_index,
            h3_index: place.level === "h3" ? place.h3_index : null,
        };
        if (place.level === "h3") {
            opts.h2_index = null;
            opts.h3_index = place.h3_index;
        } else if (place.placement === "after_heading") {
            opts.h2_index = place.h2_index;
            opts.h3_index = null;
        }
        const result = await studioInsertSelected(preview, "inline", opts);
        if (result && result.ok) {
            // Highlight selected after success
            renderStudioGallery();
        }
        return result;
    };

    // Expose for google-image "Chọn" path (editor.js)
    window.__caOpenMediaHeadingPicker = openMediaHeadingPicker;
    window.__caStudioInsertWithPlacement = (preview, placeOpts) =>
        studioInsertSelected(preview, "inline", placeOpts || null);
    window.__caPickHeadingAndInsertImage = async (img) => {
        const place = await openMediaHeadingPicker();
        if (!place) return null;
        const preview = typeof img === "string" ? { url: img, alt: "" } : { ...img };
        const opts = {
            placement: place.placement || "after_heading",
            section_heading: place.section_heading || "",
            h2_index: place.level === "h3" ? null : place.h2_index,
            h3_index: place.level === "h3" ? place.h3_index : null,
        };
        const result = await studioInsertSelected(preview, "inline", opts);
        return result && result.ok ? place : null;
    };

    // Bind heading picker close once
    (() => {
        const closeBtn = byId("mediaHeadingPickerClose");
        const cancelBtn = byId("mediaHeadingPickerCancel");
        const backdrop = byId("mediaHeadingPickerBackdrop");
        const onClose = (e) => {
            if (e) e.preventDefault();
            closeMediaHeadingPicker(null);
        };
        if (closeBtn && !closeBtn.dataset.bound) {
            closeBtn.dataset.bound = "1";
            closeBtn.addEventListener("click", onClose);
        }
        if (cancelBtn && !cancelBtn.dataset.bound) {
            cancelBtn.dataset.bound = "1";
            cancelBtn.addEventListener("click", onClose);
        }
        if (backdrop && !backdrop.dataset.bound) {
            backdrop.dataset.bound = "1";
            backdrop.addEventListener("click", onClose);
        }
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && byId("mediaHeadingPickerModal")?.classList.contains("open")) {
                closeMediaHeadingPicker(null);
            }
        });
    })();

    const getStudioModelCreditCost = (count) => {
        const modelId = (byId("studioImageModel") && byId("studioImageModel").value) || "";
        const models = (studioCatalogCache && studioCatalogCache.image_models) || [];
        const m = models.find((x) => x && x.id === modelId) || models[0] || {};
        const cpi = Number(m.credits_per_image != null ? m.credits_per_image : 52) || 52;
        const n = Math.max(1, Math.min(4, parseInt(count || 1, 10) || 1));
        return {
            modelId: m.id || modelId,
            label: m.label_vi || modelId || "Ảnh AI",
            creditsPerImage: cpi,
            total: cpi * n,
            count: n,
        };
    };

    const confirmStudioImageCredits = async (count) => {
        const info = getStudioModelCreditCost(count);
        if (!(window.DigiSeoConfirmCredit && window.DigiSeoCreditActions)) return true;
        const base = window.DigiSeoCreditActions.aiImage || {
            module: "content_ai",
            action: "ai_image",
            quotaKey: "ai_articles",
        };
        return window.DigiSeoConfirmCredit({
            module: base.module,
            action: base.action,
            quotaKey: base.quotaKey,
            quantity: 1,
            creditCost: info.total,
            label: `Ảnh AI · ${info.label} × ${info.count}`,
        });
    };

    const studioRegenerateOne = async (idx) => {
        setStudioHint("Đang tạo lại…");
        const btn = byId("btnStudioGenerate");
        const findBtn = byId("btnMediaFindOrCreate");
        if (btn) btn.disabled = true;
        if (findBtn) findBtn.disabled = true;
        try {
            const ok = await confirmStudioImageCredits(1);
            if (!ok) {
                setStudioHint("Đã hủy xác nhận credit.");
                return;
            }
            const prev = studioPreviews[idx] || {};
            const payload = buildStudioGeneratePayload({
                count: 1,
                section_heading: prev.section_heading || "",
                h2_index: prev.h2_index != null ? prev.h2_index : null,
                h2_headings: prev.section_heading ? [prev.section_heading] : undefined,
                h2_indices: prev.h2_index != null ? [prev.h2_index] : undefined,
            });
            const res = await fetch("/content-ai/images/generate-professional?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                    throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
                }
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : (d && d.message) || "Tạo lại thất bại");
            }
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
            const newPrev = (data.previews && data.previews[0]) || null;
            if (newPrev && studioPreviews[idx]) {
                studioPreviews[idx] = { ...studioPreviews[idx], ...newPrev };
                renderStudioGallery();
                setStudioHint("Đã tạo lại ảnh #" + (idx + 1));
                saveFormState();
            }
        } catch (e) {
            setStudioHint(String(e.message || e));
        } finally {
            if (btn) btn.disabled = false;
            if (findBtn) findBtn.disabled = false;
        }
    };

    const runStudioGenerate = async () => {
        const pk = String(byId("primaryKeyword")?.value || "").trim();
        if (!pk) {
            setStudioHint("Cần từ khóa chính trước khi tạo ảnh AI.");
            return;
        }
        if (studioCatalogCache && studioCatalogCache.openrouter_key_configured === false) {
            setStudioHint(
                "Chưa cấu hình OPENROUTER_API_KEY trên server — không thể tạo ảnh AI. Liên hệ admin.",
            );
            setHint("image", "Thiếu OPENROUTER_API_KEY trên server.");
            return;
        }
        const btn = byId("btnStudioGenerate");
        const findBtn = byId("btnMediaFindOrCreate");
        if (btn) btn.disabled = true;
        if (findBtn) findBtn.disabled = true;
        const count = Math.max(
            1,
            Math.min(4, parseInt(byId("studioImageCount")?.value || "3", 10) || 3),
        );
        const info = getStudioModelCreditCost(count);
        clearConflictingMediaHints();
        setStudioHint(`Đang tạo ${count} ảnh AI (${info.label})…`);
        studioPreviews = [];
        // Hide leftover web results so AI previews are not mixed/confused with old lists.
        const webBox = byId("googleImageResults");
        if (webBox) webBox.innerHTML = "";
        window.__caGoogleImageResultsCache = [];
        renderStudioGallery();
        try {
            const ok = await confirmStudioImageCredits(count);
            if (!ok) {
                setStudioHint("Đã hủy xác nhận credit.");
                return;
            }
            setStudioHint(`Đang gọi OpenRouter · ${info.label}…`);
            const payload = buildStudioGeneratePayload();
            const res = await fetch("/content-ai/images/generate-professional?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                    throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
                }
                const d = data.detail;
                const msg = typeof d === "string" ? d : (d && d.message) || "Tạo ảnh AI thất bại";
                throw new Error(msg);
            }
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
            studioPreviews = Array.isArray(data.previews) ? data.previews : [];
            studioSelectedIndex = 0;
            renderStudioGallery();
            if (!studioPreviews.length) {
                throw new Error("OpenRouter không trả về ảnh preview.");
            }
            clearConflictingMediaHints({ keepStudio: true });
            setStudioHint(data.message || `Đã tạo ${studioPreviews.length} ảnh preview.`);
            // Force scroll after paint — gallery sits below the H2 form and used to be clipped.
            requestAnimationFrame(() => {
                scrollStudioGalleryIntoView();
                setTimeout(() => scrollStudioGalleryIntoView(), 120);
                setTimeout(() => scrollStudioGalleryIntoView(), 400);
            });
            saveFormState();
        } catch (e) {
            const err = String(e.message || e);
            setStudioHint(err);
            if (/OPENROUTER_API_KEY|Thiếu OPENROUTER|OpenRouter|Model.*không hỗ trợ/i.test(err)) {
                setHint("image", err + " — thêm OPENROUTER_API_KEY vào env.local hoặc đổi model ảnh.");
            }
        } finally {
            if (btn) btn.disabled = false;
            if (findBtn) findBtn.disabled = false;
        }
    };

    const runMediaFindOrCreate = () => {
        const panel = byId("contentAiMediaPanel");
        const active = panel
            ? panel.querySelector(".ca-media-source-card.active")
            : document.querySelector(".ca-media-source-card.active");
        const src = active ? active.getAttribute("data-media-source") : "ai";
        if (src === "web") {
            const q = byId("googleImageQuery");
            if (q && !q.value.trim()) {
                const pk = String(byId("primaryKeyword")?.value || "").trim();
                if (pk) q.value = pk;
            }
            const searchBtn = byId("btnGoogleImageSearch");
            if (searchBtn) searchBtn.click();
            else setHint("image", "Không tìm thấy nút tìm ảnh web.");
            return;
        }
        if (src === "upload") {
            const uploadBtn = byId("btnUploadImage");
            if (uploadBtn) uploadBtn.click();
            else setHint("image", "Không tìm thấy nút upload ảnh.");
            return;
        }
        void runStudioGenerate();
    };

    const bindMediaFindOrCreate = (btn) => {
        if (!btn || btn.dataset.bound) return;
        btn.dataset.bound = "1";
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            runMediaFindOrCreate();
        });
    };

    if (studioIncludeText && studioTextHintWrap) {
        studioIncludeText.addEventListener("change", () => {
            studioTextHintWrap.style.display = studioIncludeText.checked ? "block" : "none";
        });
    }
    const studioAspectRatio = byId("studioAspectRatio");
    if (studioAspectRatio) {
        studioAspectRatio.addEventListener("change", toggleStudioCustomSize);
    }
    const studioH2SelectAll = byId("studioH2SelectAll");
    const studioH2ClearAll = byId("studioH2ClearAll");
    if (studioH2SelectAll) {
        studioH2SelectAll.addEventListener("click", (e) => {
            e.preventDefault();
            const list = byId("studioH2List");
            if (!list) return;
            list.querySelectorAll('input[type="checkbox"]').forEach((cb) => { cb.checked = true; });
        });
    }
    if (studioH2ClearAll) {
        studioH2ClearAll.addEventListener("click", (e) => {
            e.preventDefault();
            const list = byId("studioH2List");
            if (!list) return;
            list.querySelectorAll('input[type="checkbox"]').forEach((cb) => { cb.checked = false; });
        });
    }
    const studioLightboxClose = byId("studioLightboxClose");
    const studioLightbox = byId("studioLightbox");
    if (studioLightboxClose) {
        studioLightboxClose.addEventListener("click", (e) => {
            e.preventDefault();
            closeStudioLightbox();
        });
    }
    if (studioLightbox) {
        studioLightbox.addEventListener("click", (e) => {
            if (e.target === studioLightbox) closeStudioLightbox();
        });
    }
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && studioLightbox && studioLightbox.classList.contains("open")) {
            closeStudioLightbox();
        }
    });
    const btnStudioGenerate = byId("btnStudioGenerate");
    if (btnStudioGenerate) {
        btnStudioGenerate.addEventListener("click", (e) => {
            e.preventDefault();
            runStudioGenerate();
        });
    }
    const initMediaSourceCards = () => {
        const cards = document.querySelectorAll(".ca-media-source-card");
        const panels = document.querySelectorAll("[data-media-panel]");
        if (!cards.length) return;
        const activate = (source) => {
            cards.forEach((c) => {
                const on = c.getAttribute("data-media-source") === source;
                c.classList.toggle("active", on);
                c.setAttribute("aria-pressed", on ? "true" : "false");
            });
            panels.forEach((p) => {
                p.hidden = p.getAttribute("data-media-panel") !== source;
            });
            if (source === "ai") {
                refreshStudioH2Select();
                if (!studioCatalogCache) void initVisualStudio();
            }
            if (source === "hybrid" && byId("btnAutoInsertImages")) {
                setHint("image", "Bấm «Tự động chèn» ở header để chạy hybrid.");
            }
        };
        cards.forEach((card) => {
            if (card._caMediaSourceBound) return;
            card._caMediaSourceBound = true;
            card.addEventListener("click", (e) => {
                e.preventDefault();
                activate(card.getAttribute("data-media-source") || "ai");
                saveFormState();
            });
        });
        activate("ai");
    };
    bindMediaFindOrCreate(byId("btnMediaFindOrCreate"));
    window.__caRunMediaFindOrCreate = runMediaFindOrCreate;
    window.__caBindMediaFindOrCreate = bindMediaFindOrCreate;
    window.__caCollectMediaPanelState = collectMediaPanelState;
    window.__caRestoreMediaPanelState = restoreMediaPanelState;
    window.__caRefreshMediaPanel = () => {
        refreshStudioH2Select();
        if (!studioCatalogCache) void initVisualStudio();
    };
    initMediaSourceCards();
    initVisualStudio();
    [
        "googleImageQuery",
        "googleImageNum",
        "studioImageType",
        "studioStylePreset",
        "studioAspectRatio",
        "studioImageCount",
        "studioBrandTone",
        "studioCustomWidth",
        "studioCustomHeight",
        "studioTextHint",
    ].forEach((id) => {
        const el = byId(id);
        if (!el || el.dataset.caMediaPersistBound) return;
        el.dataset.caMediaPersistBound = "1";
        el.addEventListener("change", () => saveFormState());
        el.addEventListener("input", () => scheduleSaveFormState());
    });
    if (studioIncludeText && !studioIncludeText.dataset.caMediaPersistBound) {
        studioIncludeText.dataset.caMediaPersistBound = "1";
        studioIncludeText.addEventListener("change", () => saveFormState());
    }
    document.addEventListener("change", (ev) => {
        const t = ev.target;
        if (!t || t.type !== "checkbox") return;
        if (t.closest("#studioH2List")) scheduleSaveFormState();
    });
    const btnMediaUndo = byId("btnMediaUndo");
    if (btnMediaUndo && !btnMediaUndo.dataset.bound) {
        btnMediaUndo.dataset.bound = "1";
        btnMediaUndo.addEventListener("click", (e) => {
            e.preventDefault();
            if (typeof _mediaContentBeforeInsert === "undefined" || !_mediaContentBeforeInsert) return;
            setContentValue(_mediaContentBeforeInsert);
            _mediaContentBeforeInsert = "";
            refreshPreview();
            saveFormState();
            btnMediaUndo.hidden = true;
            if (typeof showMediaInsertSummary === "function") {
                showMediaInsertSummary("Đã hoàn tác — khôi phục nội dung trước khi chèn ảnh.");
            }
        });
    }
    document.addEventListener("input", (ev) => {
        if (!ev.target) return;
        const id = ev.target.id || "";
        if (id === "contentRender" || id === "outlineContent") {
            try { refreshStudioH2Select(); } catch (_) {}
        }
    });

    if (btnSiteArticlesAutoImages) {
        btnSiteArticlesAutoImages.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            batchAutoInsertImagesForBoard();
        });
    }
    const generateMissingThumbnailsForBoard = async () => {
        let raw = getSiteArticlesRawList();
        const missing = raw.filter((p) => !String(p.featured_image || "").trim());
        const hintEl = byId("siteArticlesModalHint");
        const btn = byId("btnSiteArticlesGenThumbs");
        if (!missing.length) {
            if (hintEl) {
                hintEl.hidden = false;
                hintEl.textContent = "Tất cả bài trong danh sách đã có thumbnail.";
                window.setTimeout(() => {
                    hintEl.hidden = true;
                }, 2200);
            }
            return;
        }
        if (btn) btn.disabled = true;
        let ok = 0;
        let fail = 0;
        for (let i = 0; i < missing.length; i += 1) {
            const item = missing[i];
            if (hintEl) {
                hintEl.hidden = false;
                hintEl.textContent = `Đang lấy ảnh Google (${i + 1}/${missing.length})…`;
            }
            try {
                await generateThumbnailForProject(item.id, { showHint: false, refreshBoard: false });
                ok += 1;
            } catch (_) {
                fail += 1;
            }
        }
        try {
            await refreshProjects(false);
        } catch (_) {}
        try {
            await renderSiteArticlesBoard();
        } catch (_) {}
        if (hintEl) {
            hintEl.hidden = false;
            hintEl.textContent =
                fail > 0
                    ? `Xong: ${ok} ảnh, ${fail} lỗi (kiểm tra GOOGLE_API_KEY + GOOGLE_CSE_ID).`
                    : `Đã lấy ${ok} ảnh từ Google.`;
            window.setTimeout(() => {
                hintEl.hidden = true;
            }, 3500);
        }
        if (btn) btn.disabled = false;
    };
    const renderSiteArticlesBoard = async () => {
        const ctx = _siteArticlesModalCtx;
        let raw = getSiteArticlesRawList();
        if (raw.some(needsArticleStatsEnrich)) {
            raw = await enrichProjectsWithStats(raw);
        }
        const counts = countSiteArticles(raw);
        const filtered = filterSiteArticlesList(raw);
        const titleEl = byId("siteArticlesModalTitle");
        if (titleEl) {
            titleEl.textContent = `Bài viết — ${(ctx && ctx.label) || (ctx && ctx.base) || "site"}`;
        }
        const statsEl = byId("siteArticlesStats");
        if (statsEl) {
            statsEl.innerHTML =
                `<span>Tổng: <strong>${counts.total}</strong></span>` +
                `<span class="stat-pub">Đã đăng: ${counts.published}</span>` +
                `<span class="stat-ready">Chưa đăng: ${counts.unpublished}</span>` +
                `<span class="stat-draft">Nháp: ${counts.setupDraft}</span>`;
        }
        const pubFilterEl = byId("siteArticlesPublishFilter");
        if (pubFilterEl) {
            const allowed = new Set(["all", "published", "unpublished", "setup_draft"]);
            const cur = allowed.has(_siteArticlesFilter) ? _siteArticlesFilter : "all";
            if (pubFilterEl.value !== cur) pubFilterEl.value = cur;
            if (!pubFilterEl._sitePubFilterBound) {
                pubFilterEl._sitePubFilterBound = true;
                pubFilterEl.addEventListener("change", () => {
                    _siteArticlesFilter = String(pubFilterEl.value || "all");
                    void renderSiteArticlesBoard();
                });
            }
        }
        const filtersEl = byId("siteArticlesFilters");
        if (filtersEl) {
            const tabs = [
                { id: "all", label: `Tất cả (${counts.allTab})` },
                { id: "published", label: `Đã đăng (${counts.published})` },
                { id: "unpublished", label: `Chưa đăng (${counts.unpublished})` },
                { id: "setup_draft", label: `Bản nháp (${counts.setupDraft})` },
            ];
            filtersEl.innerHTML = "";
            tabs.forEach((tab) => {
                const b = document.createElement("button");
                b.type = "button";
                b.className = `articles-filter-tab${_siteArticlesFilter === tab.id ? " active" : ""}`;
                b.textContent = tab.label;
                b.addEventListener("click", () => {
                    _siteArticlesFilter = tab.id;
                    const sel = byId("siteArticlesPublishFilter");
                    if (sel) sel.value = tab.id;
                    void renderSiteArticlesBoard();
                });
                filtersEl.appendChild(b);
            });
        }
        const emptyEl = byId("siteArticlesEmpty");
        const box = byId("siteArticlesModalList");
        if (!box) return;
        box.innerHTML = "";
        if (siteArticlesSelectAllEl) siteArticlesSelectAllEl.checked = false;
        if (!raw.length) {
            if (emptyEl) {
                emptyEl.hidden = false;
                emptyEl.textContent =
                    "Chưa có bài viết cho site này — lưu dự án với đúng Target website khớp URL.";
            }
            return;
        }
        if (emptyEl) {
            emptyEl.hidden = filtered.length > 0;
            emptyEl.textContent = "Không có bài phù hợp bộ lọc / từ khóa tìm kiếm.";
        }
        filtered.forEach((item) => {
            const tr = document.createElement("tr");
            if (_siteArticlesHighlightId && item.id === _siteArticlesHighlightId) {
                tr.className = "row-highlight";
            }
            const tdCheck = document.createElement("td");
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.dataset.articleRow = "1";
            tdCheck.appendChild(cb);
            const tdThumb = document.createElement("td");
            const thumbUrl = String(item.featured_image || "").trim();
            if (thumbUrl) {
                const img = document.createElement("img");
                img.className = "ab-thumb";
                img.src = thumbUrl;
                img.alt = "";
                img.loading = "lazy";
                img.referrerPolicy = "no-referrer";
                tdThumb.appendChild(img);
            } else {
                const slot = document.createElement("div");
                slot.className = "ab-thumb-slot";
                const ph = document.createElement("div");
                ph.className = "ab-thumb-empty";
                const genBtn = document.createElement("button");
                genBtn.type = "button";
                genBtn.className = "ab-thumb-ai-btn";
                genBtn.title = "Lấy thumbnail từ Google Image Search";
                genBtn.textContent = "G";
                genBtn.addEventListener("click", async (ev) => {
                    ev.preventDefault();
                    ev.stopPropagation();
                    genBtn.disabled = true;
                    genBtn.classList.add("is-loading");
                    try {
                        await generateThumbnailForProject(item.id);
                    } catch (_) {}
                    genBtn.classList.remove("is-loading");
                    genBtn.disabled = false;
                });
                slot.appendChild(ph);
                slot.appendChild(genBtn);
                tdThumb.appendChild(slot);
            }
            const tdTitle = document.createElement("td");
            tdTitle.className = "ab-title-cell";
            const titleDiv = document.createElement("div");
            titleDiv.className = "ab-title";
            titleDiv.textContent = item.title || projectDisplayLabel(item);
            const kwDiv = document.createElement("div");
            kwDiv.className = "ab-kw";
            kwDiv.textContent = item.primary_keyword ? `Keyword · ${item.primary_keyword}` : "Keyword";
            tdTitle.appendChild(titleDiv);
            tdTitle.appendChild(kwDiv);
            const tdStats = document.createElement("td");
            tdStats.className = "ab-stats-cell";
            tdStats.appendChild(buildArticleStatsRow(item));
            [tdCheck, tdThumb, tdTitle, tdStats].forEach((td) => tr.appendChild(td));
            const tdGsc = document.createElement("td");
            tdGsc.className = "col-progress";
            tdGsc.innerHTML = '<span class="ab-gsc">..</span>';
            tr.appendChild(tdGsc);
            const tdStatus = document.createElement("td");
            const st = articleStatusLabel(item.status, item);
            const badge = document.createElement("span");
            badge.className = `ab-status ${st.cls}`;
            badge.textContent = st.text;
            tdStatus.appendChild(badge);
            tr.appendChild(tdStatus);
            const tdActions = document.createElement("td");
            tdActions.className = "ab-actions";
            const viewBtn = document.createElement("button");
            viewBtn.type = "button";
            viewBtn.className = "mini-btn";
            viewBtn.title = "Mở bài";
            viewBtn.textContent = "👁";
            viewBtn.addEventListener("click", async (ev) => {
                ev.stopPropagation();
                await openArticleDetailModal(item.id);
            });
            const extUrl = buildArticleExternalUrl(item);
            if (extUrl) {
                const extBtn = document.createElement("a");
                extBtn.className = "mini-btn";
                extBtn.href = extUrl;
                extBtn.target = "_blank";
                extBtn.rel = "noopener noreferrer";
                extBtn.title = "Mở trên site";
                extBtn.textContent = "↗";
                extBtn.addEventListener("click", (ev) => ev.stopPropagation());
                tdActions.appendChild(extBtn);
            }
            const delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className = "mini-btn danger";
            delBtn.title = "Xóa";
            delBtn.textContent = "🗑";
            delBtn.addEventListener("click", async (ev) => {
                ev.stopPropagation();
                const deleted = await deleteContentAiProject(item.id, projectDisplayLabel(item));
                if (!deleted) return;
                renderSiteArticlesBoard();
            });
            tdActions.appendChild(viewBtn);
            tdActions.appendChild(delBtn);
            tr.appendChild(tdActions);
            tr.style.cursor = "pointer";
            tr.addEventListener("click", (ev) => {
                const t = ev.target;
                if (
                    t &&
                    (t.tagName === "BUTTON" ||
                        t.tagName === "A" ||
                        t.tagName === "INPUT" ||
                        t.closest("button") ||
                        t.closest("a"))
                ) {
                    return;
                }
                openArticleDetailModal(item.id);
            });
            box.appendChild(tr);
        });
    };
    let _articleDetailProjectId = "";
    const articleDetailBackdropEl = byId("articleDetailBackdrop");
    const articleDetailModalEl = byId("articleDetailModal");
    const articleDetailBodyEl = byId("articleDetailBody");
    const closeArticleDetailModal = () => {
        if (articleDetailBackdropEl) articleDetailBackdropEl.classList.remove("open");
        if (articleDetailModalEl) {
            articleDetailModalEl.classList.remove("open");
            articleDetailModalEl.setAttribute("aria-hidden", "true");
        }
        _articleDetailProjectId = "";
    };
    const btnArticleDetailBackEl = byId("btnArticleDetailBack");
    const btnArticleDetailCloseEl = byId("btnArticleDetailClose");
    if (btnArticleDetailBackEl) btnArticleDetailBackEl.addEventListener("click", closeArticleDetailModal);
    if (btnArticleDetailCloseEl) {
        btnArticleDetailCloseEl.addEventListener("click", () => {
            closeArticleDetailModal();
            closeSiteArticlesModal();
        });
    }
    if (articleDetailBackdropEl) {
        articleDetailBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === articleDetailBackdropEl) closeArticleDetailModal();
        });
    }
    const _adEscapeHtml = (s) =>
        String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    const _parseIntroFromOutline = (outlineText) => {
        const intro = { hook: "", problem: "", promise: "" };
        const lines = String(outlineText || "").split(/\r?\n/);
        let inIntro = false;
        for (const raw of lines) {
            const line = String(raw || "").trim();
            if (/^##\s+/.test(line)) {
                if (inIntro) break;
                if (/giới\s*thiệu|introduction/i.test(line)) inIntro = true;
                continue;
            }
            if (/^#\s+/.test(line) && !/^##/.test(line)) continue;
            const labeled =
                line.match(/^(?:[-*]\s+)?(?:\*\*)?(Hook|Problem|Promise|Vấn đề|Lời hứa)(?:\*\*)?\s*[:：]\s*(.+)$/i) ||
                line.match(/^(?:[-*]\s+)?(Hook|Problem|Promise)\s*[-–]\s*(.+)$/i);
            if (labeled) {
                const key = labeled[1].toLowerCase();
                const val = labeled[2].trim();
                if (key === "hook") intro.hook = val;
                else if (key === "problem" || key === "vấn đề") intro.problem = val;
                else intro.promise = val;
                continue;
            }
            if (inIntro) {
                const li = line.match(/^[-*]\s+(.+)$/);
                if (!li) continue;
                const t = li[1];
                if (/^hook\s*[:：]/i.test(t)) intro.hook = t.replace(/^hook\s*[:：]\s*/i, "").trim();
                else if (/^problem|^vấn đề/i.test(t))
                    intro.problem = t.replace(/^(?:problem|vấn đề)\s*[:：]\s*/i, "").trim();
                else if (/^promise|^lời hứa/i.test(t))
                    intro.promise = t.replace(/^(?:promise|lời hứa)\s*[:：]\s*/i, "").trim();
            }
        }
        return intro;
    };
    const _splitMetaIntro = (meta) => {
        const t = String(meta || "").trim();
        if (!t) return { hook: "", problem: "", promise: "" };
        const parts = t.split(/(?<=[.!?…])\s+/).filter((x) => x.trim());
        return {
            hook: parts[0] || "",
            problem: parts[1] || "",
            promise: parts.slice(2).join(" ") || "",
        };
    };
    const _estimateSectionWords = (sec) => {
        const n = (sec.bullets || []).join(" ").split(/\s+/).filter(Boolean).length;
        const base = Math.max(180, n * 45 + String(sec.title || "").split(/\s+/).length * 12);
        return `~${Math.min(920, base)} words`;
    };
    const _parseOutlineSections = (outlineText) => {
        const lines = String(outlineText || "").split(/\r?\n/);
        const sections = [];
        let cur = null;
        for (const raw of lines) {
            const line = String(raw || "").trim();
            if (!line) continue;
            if (/^#\s+/.test(line) && !/^##/.test(line)) continue;
            const h2 = line.match(/^##\s+(.+)$/);
            if (h2) {
                const title = h2[1].trim();
                if (/giới\s*thiệu|introduction/i.test(title)) continue;
                if (cur) sections.push(cur);
                cur = { title, bullets: [] };
                continue;
            }
            const h3 = line.match(/^###\s+(.+)$/);
            if (h3 && cur) {
                cur.bullets.push(h3[1].trim());
                continue;
            }
            const li = line.match(/^[-*]\s+(.+)$/) || line.match(/^\d+[.)]\s+(.+)$/);
            if (li && cur) cur.bullets.push(li[1].trim());
        }
        if (cur) sections.push(cur);
        const conclusionIdx = sections.findIndex((s) => /kết\s*luận|tổng\s*kết|conclusion/i.test(s.title || ""));
        let conclusion = null;
        if (conclusionIdx >= 0) {
            const c = sections.splice(conclusionIdx, 1)[0];
            conclusion = {
                summary: (c.bullets || [])[0] || c.title || "",
                cta: (c.bullets || []).slice(1).join(" ") || "",
            };
        }
        return {
            sections: sections.map((s, i) => ({
                num: i + 1,
                title: s.title,
                bullets: s.bullets.length ? s.bullets : ["Nội dung triển khai theo mục này trong bài viết."],
                words: _estimateSectionWords(s),
            })),
            conclusion,
        };
    };
    const _seoCharClass = (len, min, max) => {
        if (len >= min && len <= max) return "ok";
        if (len > 0) return "warn";
        return "";
    };
    const _projectProgressSteps = (p) => {
        const pk = String(p.primary_keyword || "").trim();
        const outline = String(p.outline_content || "").trim();
        const content = String(_projectContentFromDetail(p) || "").trim();
        const thumb = String(p.featured_image || "").trim();
        const hasSection = /^#{2,3}\s/m.test(outline) || /<h[23]\b/i.test(content);
        return [
            { key: "research", label: "Research", done: !!pk },
            { key: "outline", label: "Outline", done: !!outline, active: !!outline && !content },
            { key: "content", label: "Content", done: !!content },
            { key: "thumb", label: "Thumb", done: !!thumb },
            { key: "section", label: "Section", done: hasSection },
        ];
    };
    let _articleDetailCtx = null;
    let _articleDetailActiveStep = "outline";
    const _pickDefaultArticleDetailStep = (steps) => {
        const active = (steps || []).find((s) => s.active);
        if (active) return active.key;
        const pending = (steps || []).find((s) => !s.done);
        if (pending) return pending.key;
        return "review";
    };
    const _adFieldRow = (label, val, emptyText) => {
        const v = String(val || "").trim();
        const empty = emptyText || "—";
        return (
            `<div class="ad-field"><div class="ad-field-label">${_adEscapeHtml(label)}</div>` +
            `<div class="ad-field-val${v ? "" : " muted"}">${_adEscapeHtml(v || empty)}</div></div>`
        );
    };
    const _buildArticleDetailStepHtml = (stepKey, ctx) => {
        const p = ctx.project;
        const k = String(stepKey || "").toLowerCase();
        if (k === "research") {
            const secKw = Array.isArray(p.secondary_keywords)
                ? p.secondary_keywords.join(", ")
                : String(p.secondary_keywords || "");
            const tagStr = Array.isArray(p.tags) ? p.tags.join(", ") : String(p.tags || "");
            let html = '<div class="ad-panel"><h3>Research — thiết lập từ khóa</h3><div class="ad-field-grid">';
            html += _adFieldRow("Từ khóa chính (bắt buộc)", p.primary_keyword, "Chưa nhập");
            html += _adFieldRow("Từ khóa phụ", secKw, "Chưa có");
            html += _adFieldRow("Target website", p.target_website, "Chưa chọn");
            html += _adFieldRow("Title", p.title, "Chưa có");
            html += _adFieldRow("Slug", p.slug, "Chưa có");
            html += _adFieldRow("Tags", tagStr, "Chưa có");
            html += _adFieldRow("Link đối thủ", p.competitor_url, "Chưa có");
            html += "</div></div>";
            if (ctx.uniqTags.length) {
                html += '<div class="ad-panel"><h3>SEO Keywords</h3><div class="ad-kw-tags">';
                ctx.uniqTags.slice(0, 24).forEach((t) => {
                    html += `<span class="ad-kw-tag">${_adEscapeHtml(t)}</span>`;
                });
                html += "</div></div>";
            }
            return html;
        }
        if (k === "outline") {
            let html = '<div class="ad-panel"><h3>SEO</h3>';
            html += '<div class="ad-seo-row"><div class="ad-seo-label">SEO Title</div>';
            html += `<div class="ad-seo-val">${_adEscapeHtml(ctx.seoTitle)}</div>`;
            html += `<div class="ad-seo-count ${ctx.titleCharClass}">${ctx.titleLen}/60 chars</div></div>`;
            html += '<div class="ad-seo-row"><div class="ad-seo-label">Meta Description</div>';
            html += `<div class="ad-seo-val">${_adEscapeHtml(ctx.meta || "—")}</div>`;
            html += `<div class="ad-seo-count ${ctx.metaCharClass}">${ctx.metaLen}/160 chars</div></div></div>`;
            html += '<div class="ad-panel"><h3>Introduction</h3><div class="ad-intro-grid">';
            html += `<div class="ad-intro-block hook"><div class="lbl">Hook</div><p>${_adEscapeHtml(ctx.intro.hook || "—")}</p></div>`;
            html += `<div class="ad-intro-block problem"><div class="lbl">Problem</div><p>${_adEscapeHtml(ctx.intro.problem || "—")}</p></div>`;
            html += `<div class="ad-intro-block promise"><div class="lbl">Promise</div><p>${_adEscapeHtml(ctx.intro.promise || "—")}</p></div></div></div>`;
            if (ctx.parsed.sections.length) {
                html += `<div class="ad-panel"><h3>Sections (${ctx.parsed.sections.length})</h3>`;
                ctx.parsed.sections.forEach((sec) => {
                    html += '<div class="ad-section-card"><div class="ad-section-head">';
                    html += `<span class="ad-section-num">${sec.num}</span>`;
                    html += `<div class="ad-section-title">${_adEscapeHtml(sec.title)}</div>`;
                    html += `<span class="ad-section-wc">${_adEscapeHtml(sec.words)}</span></div>`;
                    html += '<ul class="ad-section-body">';
                    sec.bullets.forEach((b) => {
                        html += `<li>${_adEscapeHtml(b)}</li>`;
                    });
                    html += "</ul></div>";
                });
                html += "</div>";
            }
            const outlineRaw = String(p.outline_content || "").trim();
            if (outlineRaw) {
                html += '<div class="ad-panel"><h3>Outline content (markdown)</h3>';
                html += `<pre class="ad-pre">${_adEscapeHtml(outlineRaw)}</pre></div>`;
            }
            return html;
        }
        if (k === "content") {
            const stats = ctx.contentStats;
            let html = '<div class="ad-panel"><h3>Content — thống kê</h3>';
            html += `<div class="ab-stats-row">`;
            [
                ["SỐ TỪ", stats.word_count],
                ["KÝ TỰ", stats.char_count],
                ["SỐ CÂU", stats.sentence_count],
                ["ĐOẠN VĂN", stats.paragraph_count],
                ["SỐ TRANG", formatArticlePageCount(stats.page_count)],
            ].forEach(([label, val]) => {
                html += `<div class="ab-stat"><div class="k">${_adEscapeHtml(label)}</div><div class="v">${_adEscapeHtml(String(val))}</div></div>`;
            });
            html += "</div></div>";
            if (ctx.contentHtml) {
                html += '<div class="ad-panel"><h3>Nội dung bài viết</h3>';
                html += `<div class="ad-content-preview">${ctx.contentHtml}</div></div>`;
            } else {
                html += '<div class="ad-panel"><p class="hint">Chưa có content — bấm Chỉnh sửa để tạo hoặc Tạo content trong form setup.</p></div>';
            }
            return html;
        }
        if (k === "thumb") {
            const thumb = String(p.featured_image || "").trim();
            const gallery = Array.isArray(p.gallery_images) ? p.gallery_images : [];
            let html = '<div class="ad-panel"><h3>Thumbnail & ảnh minh họa</h3>';
            if (thumb) {
                html += `<div class="ad-field"><div class="ad-field-label">Ảnh đại diện (featured)</div>`;
                html += `<img class="ad-thumb-hero" src="${_adEscapeHtml(thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer" /></div>`;
            } else {
                html += '<p class="hint">Chưa có ảnh đại diện.</p>';
            }
            const extras = gallery.filter((u) => String(u || "").trim() && String(u).trim() !== thumb);
            if (extras.length) {
                html += '<div class="ad-field-label" style="margin-top:12px;">Gallery</div><div class="ad-thumb-grid">';
                extras.forEach((u) => {
                    const url = String(u).trim();
                    html += `<img src="${_adEscapeHtml(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`;
                });
                html += "</div>";
            }
            html += "</div>";
            return html;
        }
        if (k === "section") {
            if (!ctx.parsed.sections.length) {
                return '<div class="ad-panel"><p class="hint">Chưa có section trong outline (cần heading ## / ### hoặc bullet).</p></div>';
            }
            let html = `<div class="ad-panel"><h3>Sections (${ctx.parsed.sections.length})</h3>`;
            ctx.parsed.sections.forEach((sec) => {
                html += '<div class="ad-section-card"><div class="ad-section-head">';
                html += `<span class="ad-section-num">${sec.num}</span>`;
                html += `<div class="ad-section-title">${_adEscapeHtml(sec.title)}</div>`;
                html += `<span class="ad-section-wc">${_adEscapeHtml(sec.words)}</span></div>`;
                html += '<ul class="ad-section-body">';
                sec.bullets.forEach((b) => {
                    html += `<li>${_adEscapeHtml(b)}</li>`;
                });
                html += "</ul></div>";
            });
            html += "</div>";
            return html;
        }
        if (k === "review") {
            const conc = ctx.parsed.conclusion;
            let html = '<div class="ad-panel"><h3>Pending review</h3><div class="ad-field-grid">';
            html += _adFieldRow("Trạng thái", ctx.statusText);
            html += _adFieldRow("Tiêu đề", ctx.seoTitle);
            html += _adFieldRow("Từ khóa chính", p.primary_keyword);
            html += "</div></div>";
            html += '<div class="ad-panel"><h3>SEO</h3>';
            html += '<div class="ad-seo-row"><div class="ad-seo-label">SEO Title</div>';
            html += `<div class="ad-seo-val">${_adEscapeHtml(ctx.seoTitle)}</div>`;
            html += `<div class="ad-seo-count ${ctx.titleCharClass}">${ctx.titleLen}/60 chars</div></div>`;
            html += '<div class="ad-seo-row"><div class="ad-seo-label">Meta Description</div>';
            html += `<div class="ad-seo-val">${_adEscapeHtml(ctx.meta || "—")}</div>`;
            html += `<div class="ad-seo-count ${ctx.metaCharClass}">${ctx.metaLen}/160 chars</div></div></div>`;
            html += '<div class="ad-panel"><h3>Conclusion</h3><div class="ad-intro-grid">';
            html += `<div class="ad-intro-block promise"><div class="lbl">Summary</div><p>${_adEscapeHtml(conc && conc.summary ? conc.summary : "Tóm tắt nội dung chính của bài viết.")}</p></div>`;
            html += `<div class="ad-intro-block hook"><div class="lbl">Call to Action</div><p>${_adEscapeHtml(conc && conc.cta ? conc.cta : "Kêu gọi hành động phù hợp với mục tiêu bài viết.")}</p></div></div></div>`;
            if (ctx.uniqTags.length) {
                html += '<div class="ad-panel"><h3>SEO Keywords</h3><div class="ad-kw-tags">';
                ctx.uniqTags.slice(0, 24).forEach((t) => {
                    html += `<span class="ad-kw-tag">${_adEscapeHtml(t)}</span>`;
                });
                html += "</div></div>";
            }
            return html;
        }
        return '<div class="hint">Không có dữ liệu cho mục này.</div>';
    };
    const _showArticleDetailStep = (stepKey) => {
        if (!_articleDetailCtx) return;
        _articleDetailActiveStep = String(stepKey || "outline");
        const panel = byId("articleDetailStepPanel");
        if (panel) {
            panel.innerHTML = _buildArticleDetailStepHtml(_articleDetailActiveStep, _articleDetailCtx);
        }
        document.querySelectorAll("#articleDetailBody .ad-step[data-ad-step]").forEach((el) => {
            const on = el.getAttribute("data-ad-step") === _articleDetailActiveStep;
            el.classList.toggle("selected", on);
            if (on && !el.classList.contains("done") && !el.classList.contains("active")) {
                el.classList.add("selected");
            }
        });
        const regen = byId("btnArticleDetailRegenOutline");
        if (regen) {
            regen.hidden = _articleDetailActiveStep !== "outline";
        }
    };
    const _bindArticleDetailStepClicks = () => {
        document.querySelectorAll("#articleDetailBody .ad-step[data-ad-step]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const key = btn.getAttribute("data-ad-step");
                if (key) _showArticleDetailStep(key);
            });
        });
    };
    const renderArticleDetail = (p) => {
        if (!articleDetailBodyEl || !p) return;
        const title = String(p.title || p.primary_keyword || "Bài viết").trim();
        const pk = String(p.primary_keyword || "").trim();
        const meta = String(p.meta_description || "").trim();
        const seoTitle = title;
        const st = articleStatusLabel(p.status || (p.content && p.outline_content ? "ready" : "draft"));
        const fromOutline = _parseIntroFromOutline(p.outline_content || "");
        const fromMeta = _splitMetaIntro(meta);
        const intro = {
            hook: fromOutline.hook || fromMeta.hook,
            problem: fromOutline.problem || fromMeta.problem,
            promise: fromOutline.promise || fromMeta.promise || meta,
        };
        const parsed = _parseOutlineSections(p.outline_content || "");
        const tags = [];
        if (pk) tags.push(pk);
        const secKw = p.secondary_keywords;
        if (Array.isArray(secKw)) secKw.forEach((k) => tags.push(String(k)));
        else if (typeof secKw === "string") {
            secKw.split(",").forEach((k) => {
                const t = k.trim();
                if (t) tags.push(t);
            });
        }
        (p.tags || []).forEach((k) => {
            const t = String(k).trim();
            if (t) tags.push(t);
        });
        const uniqTags = [];
        const seenTag = new Set();
        tags.forEach((t) => {
            const k = t.toLowerCase();
            if (!k || seenTag.has(k)) return;
            seenTag.add(k);
            uniqTags.push(t);
        });
        const steps = _projectProgressSteps(p);
        const titleLen = seoTitle.length;
        const metaLen = meta.length;
        const contentRaw = _projectContentFromDetail(p);
        const contentStats = articleStatsFromContent(contentRaw);
        const pendingLabel = st.cls === "ready" ? "Pending review" : st.text;
        _articleDetailCtx = {
            project: p,
            seoTitle,
            meta,
            intro,
            parsed,
            uniqTags,
            titleLen,
            metaLen,
            titleCharClass: _seoCharClass(titleLen, 50, 60),
            metaCharClass: _seoCharClass(metaLen, 120, 160),
            contentHtml: contentRaw,
            contentStats,
            statusText: st.text,
        };
        _articleDetailActiveStep = _pickDefaultArticleDetailStep(steps);
        let html = "";
        html += '<div class="ad-hero">';
        html += "<div>";
        html += '<div class="ad-hero-title-row">';
        html += `<div class="ad-hero-title">${_adEscapeHtml(title)}</div>`;
        html += `<span class="ad-badge ${st.cls}">${_adEscapeHtml(st.text)}</span>`;
        html += "</div>";
        html += `<div class="ad-kw-line">Keyword: <strong>${_adEscapeHtml(pk || "—")}</strong></div>`;
        html += "</div>";
        html += '<div class="ad-hero-actions">';
        html += '<button type="button" class="mini-btn" id="btnArticleDetailEdit">Chỉnh sửa</button>';
        html += '<button type="button" class="mini-btn primary" id="btnArticleDetailPublish">Publish</button>';
        html += "</div></div>";
        html += '<div class="ad-progress" role="tablist" aria-label="Tiến trình bài viết">';
        steps.forEach((s) => {
            const cls = [s.done ? "done" : "", s.active ? "active" : ""].filter(Boolean).join(" ");
            const icon = s.done ? "✓" : s.active ? "●" : "○";
            const sel = s.key === _articleDetailActiveStep ? " selected" : "";
            html += `<button type="button" class="ad-step ${cls}${sel}" data-ad-step="${s.key}" role="tab">`;
            html += `<span class="ad-step-icon">${icon}</span>${_adEscapeHtml(s.label)}</button>`;
        });
        const reviewSel = _articleDetailActiveStep === "review" ? " selected" : "";
        html += `<button type="button" class="ad-step${reviewSel}" data-ad-step="review" role="tab">`;
        html += `<span class="ad-step-icon">⏳</span>${_adEscapeHtml(pendingLabel)}</button>`;
        html += "</div>";
        html += '<div class="ad-toolbar">';
        html += '<button type="button" class="mini-btn" id="btnArticleDetailEdit2">Edit</button>';
        html += '<button type="button" class="mini-btn" id="btnArticleDetailRegenOutline">Regenerate outline</button>';
        html += "</div>";
        html += '<div id="articleDetailStepPanel" class="ad-step-panel"></div>';
        articleDetailBodyEl.innerHTML = html;
        _showArticleDetailStep(_articleDetailActiveStep);
        _bindArticleDetailStepClicks();
        const headTitle = byId("articleDetailHeadTitle");
        if (headTitle) headTitle.textContent = title.slice(0, 80);
        const wireEdit = async () => {
            const pid = String(_articleDetailProjectId || "").trim();
            closeArticleDetailModal();
            closeSiteArticlesModal();
            setContentAiMainView("single");
            if (railNav) {
                railNav.querySelectorAll(".content-ai-nav-item").forEach((n) => n.classList.remove("active"));
            }
            if (pid) {
                await loadProject(pid);
            }
            window.setTimeout(() => {
                if (contentAiSinglePanel) {
                    contentAiSinglePanel.scrollIntoView({ behavior: "smooth", block: "start" });
                }
                const pk = byId("primaryKeyword");
                if (pk) pk.focus({ preventScroll: true });
            }, 320);
        };
        const btnEdit = byId("btnArticleDetailEdit");
        const btnEdit2 = byId("btnArticleDetailEdit2");
        if (btnEdit) btnEdit.addEventListener("click", wireEdit);
        if (btnEdit2) btnEdit2.addEventListener("click", wireEdit);
        const btnPub = byId("btnArticleDetailPublish");
        if (btnPub) {
            btnPub.addEventListener("click", async () => {
                closeArticleDetailModal();
                await loadProject(_articleDetailProjectId);
                const pub = byId("btnPublishNow");
                if (pub) pub.click();
            });
        }
        const btnRegen = byId("btnArticleDetailRegenOutline");
        if (btnRegen) {
            btnRegen.addEventListener("click", async () => {
                closeArticleDetailModal();
                await loadProject(_articleDetailProjectId);
                const r = byId("btnOutlineRefresh");
                if (r) r.click();
            });
        }
    };
    const openArticleDetailModal = async (projectId) => {
        const pid = String(projectId || "").trim();
        if (!pid) return;
        _articleDetailProjectId = pid;
        if (articleDetailBodyEl) {
            articleDetailBodyEl.innerHTML = '<div class="hint">Đang tải chi tiết bài viết…</div>';
        }
        if (articleDetailBackdropEl) articleDetailBackdropEl.classList.add("open");
        if (articleDetailModalEl) {
            articleDetailModalEl.classList.add("open");
            articleDetailModalEl.setAttribute("aria-hidden", "false");
        }
        try {
            const res = await fetch(`/content-ai/projects/${encodeURIComponent(pid)}?ts=${Date.now()}`, {
                headers: authHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không tải được bài viết.");
            renderArticleDetail(data);
        } catch (e) {
            if (articleDetailBodyEl) {
                articleDetailBodyEl.innerHTML = `<div class="hint">${_adEscapeHtml(String(e.message || e))}</div>`;
            }
        }
    };

    async function openSiteArticlesModal(siteBaseNorm, hostLabel, opts) {
        const o = opts || {};
        _siteArticlesModalCtx = { base: siteBaseNorm, label: hostLabel };
        _siteArticlesHighlightId = String(o.highlightId || "").trim();
        if (o.resetFilter) _siteArticlesFilter = "all";
        if (siteArticlesSearchEl && o.clearSearch) siteArticlesSearchEl.value = "";
        await renderSiteArticlesBoard();
        if (siteArticlesBackdropEl) siteArticlesBackdropEl.classList.add("open");
        if (siteArticlesModalEl) {
            siteArticlesModalEl.classList.add("open");
            siteArticlesModalEl.setAttribute("aria-hidden", "false");
        }
        if (_siteArticlesHighlightId) {
            await openArticleDetailModal(_siteArticlesHighlightId);
        }
    }
    const getFilteredProjects = () => {
        if (!_projectsSiteFilterBase) return allProjects || [];
        const want = String(_projectsSiteFilterBase).toLowerCase();
        return (allProjects || []).filter((p) => {
            const tw = normalizeTargetBase(String((p && p.target_website) || ""));
            return tw && tw.toLowerCase() === want;
        });
    };
    const updateProjectSiteFilterBanner = () => {
        const bar = byId("projectSiteFilterBanner");
        if (bar) bar.hidden = true;
    };
    const _projectSortTime = (p) => {
        const t = Date.parse(String((p && (p.updated_at || p.created_at)) || ""));
        return Number.isFinite(t) ? t : 0;
    };
    const _getSidebarRecentItems = () => {
        const sorted = getFilteredProjects()
            .slice()
            .sort((a, b) => _projectSortTime(b) - _projectSortTime(a));
        const top = sorted.slice(0, SIDEBAR_RECENT_PROJECT_COUNT);
        const aid = String(activeProjectId || "").trim();
        if (!aid) return top;
        if (top.some((p) => String(p.id) === aid)) return top;
        const active = sorted.find((p) => String(p.id) === aid);
        if (!active) return top;
        return [active, ...top.filter((p) => String(p.id) !== aid)].slice(0, SIDEBAR_RECENT_PROJECT_COUNT);
    };
    const _renderPager = () => {
        if (projectPager) projectPager.style.display = "none";
    };
    const renderProjects = () => {
        updateProjectSiteFilterBanner();
        const items = _getSidebarRecentItems();
        projectList.innerHTML = "";
        if (!allProjects || !allProjects.length) {
            _projectsSiteFilterBase = "";
            projectHint.textContent = "Chưa có dự án.";
            if (projectPager) projectPager.style.display = "none";
            updateProjectSiteFilterBanner();
            return;
        }
        if (!getFilteredProjects().length) {
            if (projectPager) projectPager.style.display = "none";
            return;
        }
        if (projectHint) projectHint.textContent = "";
        for (const item of items) {
            const wrap = document.createElement("div");
            wrap.className = `project-item${activeProjectId === item.id ? " active" : ""}`;
            wrap.dataset.id = item.id;
            const titleDiv = document.createElement("div");
            titleDiv.className = "project-title";
            const articleTitle = String(item.title || "").trim();
            const pk = String(item.primary_keyword || "").trim();
            titleDiv.textContent = articleTitle || pk || "(Chưa có tiêu đề)";
            wrap.appendChild(titleDiv);
            wrap.addEventListener("click", () => {
                loadProjectIntoWriteTab(item.id);
            });
            projectList.appendChild(wrap);
        }
        _renderPager();
    };
    const fetchProjects = async (limit = 500) => {
        const cap = Math.max(1, Math.min(Number(limit) || 500, 500));
        const res = await apiFetch(`/content-ai/projects?limit=${cap}&ts=${Date.now()}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (res.status === 401) return [];
            throw new Error(parseApiDetail(data) || "Load projects failed");
        }
        return data.items || [];
    };
