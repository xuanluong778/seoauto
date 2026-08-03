    const loadProject = async (projectId) => {
        if (!projectId) return;
        try {
            const res = await fetch(`/content-ai/projects/${projectId}?ts=${Date.now()}`, {
                headers: authHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Load project failed");
            activeProjectId = projectId;
            applyProjectToForm(data);
            if (
                data.images_repaired
                && String(data.primary_keyword || "").trim()
                && typeof autoInsertImagesForProject === "function"
            ) {
                try {
                    await autoInsertImagesForProject(projectId);
                    msg.textContent = "Đã tải dự án và chèn lại ảnh minh họa.";
                } catch (_) {
                    msg.textContent = "Đã tải dự án (ảnh hỏng đã gỡ — chưa chèn được ảnh mới).";
                }
            } else {
                msg.textContent = "Đã tải đúng dữ liệu dự án.";
            }
            // re-render current page to keep highlight in sync
            renderProjects();
        } catch (e) {
            msg.textContent = String(e.message || e);
        }
    };
    const articleStatusLabel = (status, item) => {
        if (item && item.is_setup_draft) return { cls: "setup_draft", text: "Lưu nháp" };
        const s = String(status || "draft").toLowerCase();
        if (s === "published") return { cls: "published", text: "Published" };
        if (s === "ready") return { cls: "ready", text: "Ready" };
        if (s === "setup_draft") return { cls: "setup_draft", text: "Lưu nháp" };
        return { cls: "draft", text: "Draft" };
    };
    const formatArticlePageCount = (n) => {
        const p = Number(n) || 0;
        return p > 0 ? p.toFixed(2) : "0";
    };
    const needsArticleStatsEnrich = (item) =>
        item && item.char_count == null && item.word_count == null;
    const _projectContentFromDetail = (full) => {
        if (!full || typeof full !== "object") return "";
        const c = String(full.content || "").trim();
        if (c) return c;
        const draft = full.draft_output;
        if (draft && typeof draft === "object") {
            const dc = String(draft.content || "").trim();
            if (dc) return dc;
        }
        return "";
    };
    const articleStatsFromContent = (html) => {
        const raw = String(html || "");
        const text = _stripText(raw);
        const words = _countWords(text);
        const chars = text.length;
        const sentences = _countSentences(text);
        const paragraphs = _countParagraphs(raw);
        const pages = words ? words / 260 : 0;
        return {
            word_count: words,
            char_count: chars,
            sentence_count: sentences,
            paragraph_count: paragraphs,
            page_count: pages,
            has_content: words > 0,
        };
    };
    const mergeArticleStatsIntoProjects = (rows) => {
        const byId = new Map((rows || []).map((x) => [x.id, x]));
        allProjects = (allProjects || []).map((p) => {
            const u = byId.get(p.id);
            return u ? { ...p, ...u } : p;
        });
    };
    const enrichProjectsWithStats = async (items) => {
        const list = [...(items || [])];
        if (!list.length || !needsArticleStatsEnrich(list[0])) return list;
        const pending = list.filter(needsArticleStatsEnrich);
        const concurrency = 6;
        let cursor = 0;
        const worker = async () => {
            while (cursor < pending.length) {
                const item = pending[cursor];
                cursor += 1;
                if (!item || !item.id) continue;
                try {
                    const res = await fetch(
                        `/content-ai/projects/${encodeURIComponent(item.id)}?ts=${Date.now()}`
                    );
                    const full = await res.json().catch(() => ({}));
                    if (!res.ok) continue;
                    const html = _projectContentFromDetail(full);
                    const stats = articleStatsFromContent(html);
                    const outline = String(full.outline_content || "");
                    const idx = list.findIndex((x) => x.id === item.id);
                    if (idx < 0) continue;
                    list[idx] = {
                        ...list[idx],
                        ...stats,
                        has_outline: !!outline.trim(),
                        has_section: /^#{2,3}\s/m.test(outline),
                        has_thumb: !!String(list[idx].featured_image || full.featured_image || "").trim(),
                        has_research: !!String(list[idx].primary_keyword || full.primary_keyword || "").trim(),
                    };
                } catch (_) {}
            }
        };
        await Promise.all(
            Array.from({ length: Math.min(concurrency, pending.length) }, () => worker())
        );
        mergeArticleStatsIntoProjects(list);
        return list;
    };
    const buildArticleStatsRow = (item) => {
        const row = document.createElement("div");
        row.className = "ab-stats-row";
        const cards = [
            { k: "SỐ TỪ", v: String(Number(item.word_count) || 0) },
            { k: "KÝ TỰ", v: String(Number(item.char_count) || 0) },
            { k: "SỐ CÂU", v: String(Number(item.sentence_count) || 0) },
            { k: "ĐOẠN VĂN", v: String(Number(item.paragraph_count) || 0) },
            { k: "SỐ TRANG", v: formatArticlePageCount(item.page_count) },
        ];
        cards.forEach((c) => {
            const card = document.createElement("div");
            card.className = "ab-stat";
            const k = document.createElement("div");
            k.className = "k";
            k.textContent = c.k;
            const v = document.createElement("div");
            v.className = "v";
            v.textContent = c.v;
            card.appendChild(k);
            card.appendChild(v);
            row.appendChild(card);
        });
        return row;
    };
    const getSiteArticlesRawList = () => {
        const ctx = _siteArticlesModalCtx;
        const want = String((ctx && ctx.base) || "").toLowerCase();
        if (!want) return [];
        let list = (allProjects || []).filter((p) => {
            const tw = normalizeTargetBase(String((p && p.target_website) || ""));
            return tw && tw.toLowerCase() === want;
        });
        list = [...list].sort((a, b) => {
            const ta = new Date(String(a.created_at || "").trim()).getTime();
            const tb = new Date(String(b.created_at || "").trim()).getTime();
            return (Number.isNaN(tb) ? 0 : tb) - (Number.isNaN(ta) ? 0 : ta);
        });
        return list;
    };
    const filterSiteArticlesList = (list) => {
        const q = String((siteArticlesSearchEl && siteArticlesSearchEl.value) || "")
            .trim()
            .toLowerCase();
        let out = list || [];
        if (q) {
            out = out.filter((p) => {
                const title = String(p.title || "").toLowerCase();
                const kw = String(p.primary_keyword || "").toLowerCase();
                const slug = String(p.slug || "").toLowerCase();
                return title.includes(q) || kw.includes(q) || slug.includes(q);
            });
        }
        const stOf = (p) => String(p.status || "").toLowerCase();
        if (_siteArticlesFilter === "setup_draft") {
            out = out.filter((p) => !!p.is_setup_draft || stOf(p) === "setup_draft" || stOf(p) === "draft");
        } else if (_siteArticlesFilter === "all") {
            out = out.filter((p) => !p.is_setup_draft);
        } else if (_siteArticlesFilter === "missing_section") {
            out = out.filter((p) => !p.has_section && !p.is_setup_draft);
        } else if (_siteArticlesFilter === "ready") {
            out = out.filter((p) => stOf(p) === "ready" && !p.is_setup_draft);
        } else if (_siteArticlesFilter === "published") {
            out = out.filter((p) => stOf(p) === "published");
        } else if (_siteArticlesFilter === "unpublished") {
            // Chưa đăng: có nội dung / ready nhưng chưa published, không tính bản nháp setup
            out = out.filter((p) => {
                if (p.is_setup_draft || stOf(p) === "setup_draft") return false;
                return stOf(p) !== "published";
            });
        }
        return out;
    };
    const countSiteArticles = (list) => {
        const all = list || [];
        let published = 0;
        let ready = 0;
        let missingSection = 0;
        let setupDraft = 0;
        let unpublished = 0;
        all.forEach((p) => {
            const st = String(p.status || "").toLowerCase();
            if (p.is_setup_draft || st === "setup_draft" || st === "draft") setupDraft += 1;
            if (st === "published") published += 1;
            if (st === "ready") ready += 1;
            if (!p.has_section) missingSection += 1;
            if (!p.is_setup_draft && st !== "setup_draft" && st !== "published") unpublished += 1;
        });
        const allTab = Math.max(0, all.length - setupDraft);
        return { total: all.length, allTab, published, ready, missingSection, setupDraft, unpublished };
    };
    const buildArticleExternalUrl = (item) => {
        const base = normalizeTargetBase(String((item && item.target_website) || ""));
        const slug = String((item && item.slug) || "").replace(/^\/+/, "");
        if (!base) return "";
        try {
            const u = new URL(base);
            if (slug) u.pathname = `/${slug}`.replace(/\/+/g, "/");
            return u.href;
        } catch (_) {
            return slug ? `${base.replace(/\/+$/, "")}/${slug}` : base;
        }
    };
    const patchProjectFeaturedImage = (projectId, url) => {
        const pid = String(projectId || "").trim();
        const u = String(url || "").trim();
        if (!pid || !u) return;
        allProjects = (allProjects || []).map((p) =>
            p.id === pid ? { ...p, featured_image: u, has_thumb: true } : p,
        );
    };
    const generateThumbnailForProject = async (projectId, opts = {}) => {
        const pid = String(projectId || "").trim();
        if (!pid) return null;
        const hintEl = byId("siteArticlesModalHint");
        const showHint = opts.showHint !== false;
        if (showHint && hintEl) {
            hintEl.hidden = false;
            hintEl.textContent = "Đang tìm ảnh trên Google…";
        }
        try {
            const res = await fetch(
                `/content-ai/projects/${encodeURIComponent(pid)}/generate-thumbnail?ts=${Date.now()}`,
                { method: "POST", headers: authJsonHeaders(), body: "{}" },
            );
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = data && data.detail;
                const msgErr =
                    typeof detail === "string"
                        ? detail
                        : Array.isArray(detail)
                          ? detail.map((x) => x.msg || x).join(", ")
                          : "Lấy ảnh Google thất bại";
                throw new Error(msgErr);
            }
            const url = String(data.featured_image || "").trim();
            if (url) patchProjectFeaturedImage(pid, url);
            const inlineN = Number(data.inline_images_count) || 0;
            if (data.project && String(activeProjectId || "") === pid) {
                applyProjectToForm(data.project);
            }
            if (showHint && hintEl) {
                hintEl.textContent = inlineN > 0
                    ? `Đã lấy thumbnail + chèn ${inlineN} ảnh vào nội dung bài.`
                    : "Đã lấy thumbnail (ảnh đại diện). Mở bài trong tab Viết để xem content.";
            }
            if (opts.refreshBoard !== false) {
                try {
                    await renderSiteArticlesBoard();
                } catch (_) {}
            }
            try {
                renderProjects();
            } catch (_) {}
            return data;
        } catch (e) {
            if (showHint && hintEl) hintEl.textContent = String(e.message || e);
            throw e;
        } finally {
            if (showHint && hintEl) {
                window.setTimeout(() => {
                    hintEl.hidden = true;
                }, 2800);
            }
        }
    };

    const AUTO_INSERT_IMAGES_KEY = "contentAiAutoInsertImages";
    const AUTO_INSERT_IMAGE_SOURCE_KEY = "contentAiAutoInsertImageSource";
    const autoInsertImagesAfterWriteEl = byId("autoInsertImagesAfterWrite");
    const autoInsertImageSourceEl = byId("autoInsertImageSource");
    const autoInsertImagePreviewEl = byId("autoInsertImagePreview");
    const btnAutoInsertImages = byId("btnAutoInsertImages");
    const btnSiteArticlesAutoImages = byId("btnSiteArticlesAutoImages");

    const imageCountForWordCount = (wc) => {
        const n = Number(wc) || 0;
        if (n >= 2000) return 4;
        if (n >= 1500) return 3;
        if (n >= 1000) return 2;
        if (n >= 500) return 1;
        return 0;
    };

    const getAutoInsertImageSource = () => {
        const el = autoInsertImageSourceEl;
        const v = el ? String(el.value || "none").trim() : "none";
        return v === "google" || v === "ai" ? v : "none";
    };

    const syncAutoInsertCheckboxFromSource = () => {
        if (!autoInsertImagesAfterWriteEl) return;
        autoInsertImagesAfterWriteEl.checked = getAutoInsertImageSource() !== "none";
    };

    const updateAutoInsertImagePreview = () => {
        if (!autoInsertImagePreviewEl) return;
        const src = getAutoInsertImageSource();
        const wc = Number((byId("targetWordCount") && byId("targetWordCount").value) || 1000);
        const n = imageCountForWordCount(wc);
        if (src === "none") {
            autoInsertImagePreviewEl.textContent = "Không tự động chèn ảnh sau khi viết bài.";
            return;
        }
        const srcLabel = src === "ai" ? "AI" : "Google";
        autoInsertImagePreviewEl.textContent =
            n > 0
                ? `Sẽ chèn ${n} ảnh từ ${srcLabel} (bài ${wc} từ) sau các mục H2 phù hợp.`
                : `Bài ngắn (<500 từ) — chỉ thêm ảnh đại diện từ ${srcLabel} nếu tìm được.`;
    };

    const restoreAutoInsertImagesPref = () => {
        try {
            const srcEl = autoInsertImageSourceEl;
            if (srcEl) {
                const src = localStorage.getItem(AUTO_INSERT_IMAGE_SOURCE_KEY);
                if (src === "none" || src === "google" || src === "ai") srcEl.value = src;
            }
            if (autoInsertImagesAfterWriteEl) {
                const v = localStorage.getItem(AUTO_INSERT_IMAGES_KEY);
                if (v === "0" && srcEl) srcEl.value = "none";
                else if (v === "1" && srcEl && srcEl.value === "none") srcEl.value = "google";
            }
            syncAutoInsertCheckboxFromSource();
            updateAutoInsertImagePreview();
        } catch (_) {}
    };
    const persistAutoInsertImagesPref = () => {
        try {
            syncAutoInsertCheckboxFromSource();
            if (autoInsertImagesAfterWriteEl) {
                localStorage.setItem(
                    AUTO_INSERT_IMAGES_KEY,
                    autoInsertImagesAfterWriteEl.checked ? "1" : "0",
                );
            }
            if (autoInsertImageSourceEl) {
                localStorage.setItem(AUTO_INSERT_IMAGE_SOURCE_KEY, getAutoInsertImageSource());
            }
            updateAutoInsertImagePreview();
        } catch (_) {}
    };
    restoreAutoInsertImagesPref();
    if (autoInsertImagesAfterWriteEl) {
        autoInsertImagesAfterWriteEl.addEventListener("change", persistAutoInsertImagesPref);
    }
    if (autoInsertImageSourceEl) {
        autoInsertImageSourceEl.addEventListener("change", persistAutoInsertImagesPref);
    }
    const twcEl = byId("targetWordCount");
    if (twcEl) twcEl.addEventListener("input", updateAutoInsertImagePreview);
    const applyAutoInsertResultToForm = (data) => {
        if (!data || typeof data !== "object") return;
        const content = String(data.content || "").trim();
        const feat = String(data.featured_image || "").trim();
        if (content) setContentValue(content);
        if (feat) {
            if (!uploadedImages.includes(feat)) uploadedImages.unshift(feat);
            renderUploadList();
        }
        const gal = data.gallery_images;
        if (Array.isArray(gal)) {
            gal.forEach((u) => {
                const s = String(u || "").trim();
                if (s && !uploadedImages.includes(s)) uploadedImages.push(s);
            });
            renderUploadList();
        }
        try { refreshPreview(); } catch (_) {}
        saveFormState();
    };
    const autoInsertImagesForProject = async (projectId, opts = {}) => {
        const pid = String(projectId || "").trim();
        if (!pid) throw new Error("Thiếu project id.");
        const src = opts.image_source != null ? opts.image_source : getAutoInsertImageSource();
        const wc = Number((byId("targetWordCount") && byId("targetWordCount").value) || 0) || null;
        const res = await fetch(
            `/content-ai/projects/${encodeURIComponent(pid)}/auto-insert-images?ts=${Date.now()}`,
            {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    max_inline: null,
                    word_count_target: wc,
                    update_featured: true,
                    force: !!opts.force,
                    image_source: src,
                }),
            },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data && data.detail;
            const msgErr =
                typeof detail === "string"
                    ? detail
                    : Array.isArray(detail)
                      ? detail.map((x) => x.msg || x).join(", ")
                      : "Chèn ảnh tự động thất bại";
            throw new Error(msgErr);
        }
        if (data.project && String(activeProjectId || "") === pid) {
            applyProjectToForm(data.project);
        }
        return data;
    };
    const autoInsertImagesLive = async () => {
        const pk = byId("primaryKeyword").value.trim();
        if (!pk) {
            setHint("image", "Cần từ khóa chính trước khi chèn ảnh tự động.");
            return null;
        }
        const content = String(getContentValue() || "").trim();
        if (!content) {
            setHint("image", "Cần có nội dung bài (content) trước.");
            return null;
        }
        setHint("image", "Đang tìm và chèn ảnh vào bài…");
        if (typeof _mediaContentBeforeInsert !== "undefined" && !_mediaContentBeforeInsert) {
            _mediaContentBeforeInsert = content;
        }
        const payload = buildDraftPayload();
        const res = await fetch(`/content-ai/auto-insert-images?ts=${Date.now()}`, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data && data.detail;
            throw new Error(typeof detail === "string" ? detail : "Chèn ảnh tự động thất bại");
        }
        applyAutoInsertResultToForm(data);
        const n = Number(data.inline_images_count) || 0;
        setHint(
            "image",
            n > 0
                ? `Đã chèn ${n} ảnh minh họa vào content + ảnh đại diện.`
                : "Đã thêm ảnh đại diện. (Bài ngắn hoặc đã có đủ ảnh trong content.)",
        );
        if (typeof showMediaInsertSummary === "function") {
            showMediaInsertSummary(
                n > 0
                    ? `Đã chèn ${n} ảnh — vị trí theo H2, ALT từ từ khóa.`
                    : "Đã cập nhật featured — không thêm inline.",
            );
        }
        const undoBtn = byId("btnMediaUndo");
        if (undoBtn) undoBtn.hidden = false;
        if (typeof window.__caSwitchMediaInsertedTab === "function") {
            window.__caSwitchMediaInsertedTab();
        } else if (window.__caSwitchModalTab) {
            window.__caSwitchModalTab(byId("contentAiMediaPanel"), 2);
        }
        if (activeProjectId) {
            try {
                await autoInsertImagesForProject(activeProjectId, { force: false });
            } catch (_) {}
        }
        return data;
    };
    const batchAutoInsertImagesForBoard = async () => {
        let raw = getSiteArticlesRawList();
        const withContent = raw.filter((p) => p.has_content || p.word_count > 0);
        const hintEl = byId("siteArticlesModalHint");
        const btn = byId("btnSiteArticlesAutoImages");
        if (!withContent.length) {
            if (hintEl) {
                hintEl.hidden = false;
                hintEl.textContent = "Không có bài nào đã có content.";
                window.setTimeout(() => { hintEl.hidden = true; }, 2200);
            }
            return;
        }
        if (btn) btn.disabled = true;
        let ok = 0;
        let fail = 0;
        for (let i = 0; i < withContent.length; i += 1) {
            const item = withContent[i];
            if (hintEl) {
                hintEl.hidden = false;
                hintEl.textContent = `Đang chèn ảnh (${i + 1}/${withContent.length})…`;
            }
            try {
                await autoInsertImagesForProject(item.id, { force: false });
                ok += 1;
            } catch (_) {
                fail += 1;
            }
        }
        try { await refreshProjects(false); } catch (_) {}
        try { await renderSiteArticlesBoard(); } catch (_) {}
        if (hintEl) {
            hintEl.hidden = false;
            hintEl.textContent =
                fail > 0 ? `Xong: ${ok} bài có ảnh, ${fail} lỗi.` : `Đã chèn ảnh cho ${ok} bài.`;
            window.setTimeout(() => { hintEl.hidden = true; }, 3500);
        }
        if (btn) btn.disabled = false;
    };
    const runAutoInsertImagesClick = async () => {
        const btn = byId("btnAutoInsertImages");
        if (btn) btn.disabled = true;
        try {
            if (activeProjectId) {
                const data = await autoInsertImagesForProject(activeProjectId);
                const n = Number(data.inline_images_count) || 0;
                setHint(
                    "image",
                    n > 0 ? `Đã chèn ${n} ảnh vào content + thumbnail.` : "Đã cập nhật ảnh đại diện.",
                );
            } else {
                await autoInsertImagesLive();
            }
        } catch (e) {
            const errMsg = String(e.message || e);
            setHint("image", errMsg);
            if (msg) msg.textContent = errMsg;
        } finally {
            if (btn) btn.disabled = false;
        }
    };
    if (btnAutoInsertImages) {
        btnAutoInsertImages.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            runAutoInsertImagesClick();
        });
    }

