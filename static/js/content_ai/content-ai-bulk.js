    const _bulkFmtOutlineApiErr = (data, fallback) => {
        const d = data && data.detail;
        if (typeof d === "string") return d;
        if (d && typeof d === "object" && d.message) return String(d.message);
        if (Array.isArray(d)) {
            return d.map((x) => (x && x.msg) ? x.msg : String(x)).join("; ");
        }
        return fallback;
    };

    const _bulkEditorOpenForRow = (rowId) => {
        try {
            const openId = window.ContentAiBulkUi && window.ContentAiBulkUi.getDrawerRowId
                ? window.ContentAiBulkUi.getDrawerRowId()
                : null;
            return openId && String(openId) === String(rowId);
        } catch (_) {
            return false;
        }
    };

    const _bulkPatchOutlineUi = (rowId, outlineText) => {
        const r = _findBulkRow(rowId);
        if (!r) return;
        r.custom_outline = String(outlineText || "").trim();
        r.detailsOpen = true;
        const card = document.querySelector(`.bulk-kw-card[data-id="${CSS.escape(rowId)}"]`);
        if (card) {
            const ta = card.querySelector('textarea[data-field="custom_outline"]');
            if (ta) {
                ta.value = r.custom_outline;
                try { ta.dispatchEvent(new Event("input", { bubbles: true })); } catch (_) {}
            }
            card.classList.add("is-open", "is-active");
            const details = card.querySelector(".bulk-kw-details");
            if (details) details.style.display = "block";
        }
        scheduleSaveBulkState();
        updateBulkRemoveButtonForRow(rowId);
    };

    const renderBulkKeywordList = () => {
        if (!bulkKeywordList) return;
        bulkKeywordList.querySelectorAll(".bulk-kw-card").forEach((el) => el.remove());
        if (!bulkKeywordRows.length) {
            if (bulkKeywordListEmpty) {
                bulkKeywordListEmpty.hidden = false;
                bulkKeywordList.appendChild(bulkKeywordListEmpty);
            }
            return;
        }
        if (bulkKeywordListEmpty) bulkKeywordListEmpty.hidden = true;
        bulkKeywordRows.forEach((row) => {
            const card = document.createElement("div");
            card.className = `bulk-kw-card${row.detailsOpen ? " is-open is-active" : ""}`;
            card.dataset.id = row.id;
            const main = document.createElement("div");
            main.className = "bulk-kw-row-main";
            const kwEl = document.createElement("div");
            kwEl.className = "bulk-kw-keyword";
            kwEl.title = row.keyword;
            kwEl.textContent = row.keyword;
            const volEl = document.createElement("div");
            volEl.className = "bulk-kw-volume";
            volEl.title = "Search volume — hệ thống tự lấy, không chỉnh tay";
            const sv = String(row.search_volume || "").trim();
            if (row._volumeLoading) {
                volEl.textContent = "…";
                volEl.classList.add("is-loading");
            } else if (sv) {
                volEl.textContent = sv;
                volEl.classList.add("has-value");
            } else {
                volEl.textContent = "—";
            }
            const typeSel = document.createElement("select");
            typeSel.dataset.field = "content_type";
            BULK_CONTENT_TYPES.forEach((opt) => {
                const o = document.createElement("option");
                o.value = opt.value;
                o.textContent = opt.label;
                if (opt.value === row.content_type) o.selected = true;
                typeSel.appendChild(o);
            });
            const wcWrap = document.createElement("div");
            wcWrap.className = "field-mini";
            wcWrap.style.minWidth = "220px";
            const wcSel = document.createElement("select");
            wcSel.dataset.field = "target_word_count_mode";
            [
                { value: "auto", label: "AI tự phân bổ" },
                { value: "1000", label: "1000 từ" },
                { value: "1500", label: "1500 từ" },
                { value: "2000", label: "2000 từ" },
                { value: "custom", label: "Tùy chỉnh" },
            ].forEach((opt) => {
                const o = document.createElement("option");
                o.value = opt.value;
                o.textContent = opt.label;
                wcSel.appendChild(o);
            });
            const wcIn = document.createElement("input");
            wcIn.type = "number";
            wcIn.min = "200";
            wcIn.max = "8000";
            wcIn.step = "50";
            wcIn.placeholder = "Nhập số từ tùy chỉnh";
            wcIn.title = "Số từ bài viết";
            wcIn.dataset.field = "target_word_count";
            const rowWcRaw = String(row.target_word_count ?? "").trim();
            const rowWcNum = parseInt(rowWcRaw, 10);
            let wcMode = "auto";
            if (rowWcRaw && rowWcRaw.toLowerCase() !== "auto") {
                if ([1000, 1500, 2000].includes(rowWcNum)) wcMode = String(rowWcNum);
                else wcMode = "custom";
            }
            wcSel.value = wcMode;
            wcIn.value = wcMode === "custom" ? (rowWcRaw || "1000") : "";
            const syncWordCountUi = () => {
                const mode = String(wcSel.value || "auto");
                const isCustom = mode === "custom";
                wcIn.hidden = !isCustom;
                wcIn.disabled = !isCustom;
                if (mode === "auto") {
                    wcIn.value = "";
                    wcIn.placeholder = "AI tự phân bổ số từ";
                    wcWrap.title = "Để trống để hệ thống tự phân bổ số từ theo keyword.";
                } else if (isCustom) {
                    if (!String(wcIn.value || "").trim()) wcIn.value = "1000";
                    wcIn.placeholder = "Nhập số từ tùy chỉnh";
                    wcWrap.title = "Nhập số từ tùy chỉnh cho bài viết.";
                } else {
                    wcIn.value = mode;
                    wcIn.placeholder = "Số từ preset";
                    wcWrap.title = `Preset ${mode} từ.`;
                }
            };
            wcWrap.appendChild(wcSel);
            wcWrap.appendChild(wcIn);
            syncWordCountUi();
            const btnToggle = document.createElement("button");
            btnToggle.type = "button";
            btnToggle.className = "btn secondary btn-bulk-toggle";
            btnToggle.textContent = row.detailsOpen ? "Ẩn" : "Chi tiết";
            btnToggle.setAttribute("aria-expanded", row.detailsOpen ? "true" : "false");
            if (row.detailsOpen) btnToggle.classList.add("is-open");
            btnToggle.addEventListener("click", () => {
                const r = _findBulkRow(row.id);
                if (!r) return;
                r.detailsOpen = !r.detailsOpen;
                renderBulkKeywordList();
            });
            const btnRemove = document.createElement("button");
            btnRemove.type = "button";
            btnRemove.className = "btn secondary btn-bulk-remove";
            btnRemove.textContent = "×";
            btnRemove.title = "Xóa";
            if (!isBulkItemSetupComplete(bulkRowToApiItem(row))) {
                btnRemove.classList.add("btn-bulk-remove-incomplete");
                btnRemove.title = "Xóa — chưa setup đủ (title, meta, outline, số từ ≥ 200)";
            }
            main.appendChild(kwEl);
            main.appendChild(volEl);
            main.appendChild(typeSel);
            main.appendChild(btnToggle);
            main.appendChild(btnRemove);
            const details = document.createElement("div");
            details.className = "bulk-kw-details";
            const siteWrap = document.createElement("div");
            siteWrap.className = "field-mini bulk-website-field";
            const siteLbl = document.createElement("label");
            siteLbl.textContent = "URL website";
            const siteHint = document.createElement("p");
            siteHint.className = "hint bulk-website-hint";
            siteHint.textContent = "Hệ thống dùng URL này để lấy dữ liệu website và Knowledge Base khi viết bài.";
            const siteIn = document.createElement("input");
            siteIn.type = "url";
            siteIn.inputMode = "url";
            siteIn.autocomplete = "url";
            siteIn.placeholder = "https://website-cua-ban.com";
            const globalTw = byId("bulkTargetWebsite") ? String(byId("bulkTargetWebsite").value || "").trim() : "";
            siteIn.value = row.target_website || globalTw || "";
            siteIn.dataset.field = "target_website";
            siteIn.setAttribute("list", "targetWebsiteHistory");
            siteWrap.appendChild(siteLbl);
            siteWrap.appendChild(siteHint);
            siteWrap.appendChild(siteIn);
            const urlGrid = document.createElement("div");
            urlGrid.className = "bulk-kw-details-grid";
            const urlWrap = document.createElement("div");
            urlWrap.className = "field-mini";
            urlWrap.innerHTML = "<label>URL đối thủ (lấy outline)</label>";
            const urlIn = document.createElement("input");
            urlIn.type = "url";
            urlIn.placeholder = "https://domain-doi-thu.com/bai-viet";
            urlIn.value = row.competitor_url || "";
            urlIn.dataset.field = "competitor_url";
            urlWrap.appendChild(urlIn);
            const btnOutline = document.createElement("button");
            btnOutline.type = "button";
            btnOutline.className = "btn secondary";
            btnOutline.textContent = "Lấy outline";
            urlGrid.appendChild(urlWrap);
            urlGrid.appendChild(btnOutline);
            const mkField = (label, field, tag, ph) => {
                const w = document.createElement("div");
                w.className = "field-mini";
                const head = document.createElement("div");
                head.className = "bulk-field-head";
                const lb = document.createElement("label");
                lb.textContent = label;
                const btnAi = document.createElement("button");
                btnAi.type = "button";
                btnAi.className = "ai-btn";
                btnAi.textContent = "Gợi ý AI";
                head.appendChild(lb);
                head.appendChild(btnAi);
                const el = document.createElement(tag);
                el.dataset.field = field;
                el.placeholder = ph;
                if (field === "custom_outline") {
                    el.value = row.custom_outline || "";
                } else {
                    el.value = row[field] || "";
                }
                btnAi.addEventListener("click", () => void runBulkRowAiSuggest(row.id, field, el, btnAi));
                w.appendChild(head);
                w.appendChild(el);
                return w;
            };
            const mkOutlineField = () => {
                const w = document.createElement("div");
                w.className = "field-mini bulk-outline-field";
                const head = document.createElement("div");
                head.className = "bulk-field-head";
                const lb = document.createElement("label");
                lb.textContent = "Outline";
                const btnAi = document.createElement("button");
                btnAi.type = "button";
                btnAi.className = "ai-btn";
                btnAi.textContent = "Gợi ý AI";
                head.appendChild(lb);
                head.appendChild(btnAi);
                const tools = document.createElement("div");
                tools.className = "outline-tools bulk-outline-tools";
                const inpReplaceFrom = document.createElement("input");
                inpReplaceFrom.type = "text";
                inpReplaceFrom.placeholder = "Từ cần thay (vd: Vua Web Digi)";
                inpReplaceFrom.autocomplete = "off";
                const inpReplaceTo = document.createElement("input");
                inpReplaceTo.type = "text";
                inpReplaceTo.placeholder = "Thay bằng (vd: Thế Giới Digi)";
                inpReplaceTo.autocomplete = "off";
                const btnReplaceAll = document.createElement("button");
                btnReplaceAll.type = "button";
                btnReplaceAll.className = "btn secondary";
                btnReplaceAll.textContent = "Replace All";
                const btnRefreshOutline = document.createElement("button");
                btnRefreshOutline.type = "button";
                btnRefreshOutline.className = "btn secondary";
                btnRefreshOutline.textContent = "Làm mới Outline";
                tools.appendChild(inpReplaceFrom);
                tools.appendChild(inpReplaceTo);
                tools.appendChild(btnReplaceAll);
                tools.appendChild(btnRefreshOutline);
                const toolsHint = document.createElement("div");
                toolsHint.className = "hint bulk-outline-tools-hint";
                const wrap = document.createElement("div");
                wrap.className = "bulk-outline-wrap";
                const el = document.createElement("textarea");
                el.className = "bulk-outline-ta";
                el.dataset.field = "custom_outline";
                el.placeholder = "H2: …; H2: … hoặc markdown # / ##";
                el.value = row.custom_outline || "";
                const btnExpand = document.createElement("button");
                btnExpand.type = "button";
                btnExpand.className = "bulk-outline-expand";
                btnExpand.textContent = "Xem chi tiết";
                btnExpand.hidden = true;
                const syncOutlineUi = () => {
                    if (el.classList.contains("is-expanded")) {
                        btnExpand.hidden = false;
                        btnExpand.textContent = "Thu gọn";
                        return;
                    }
                    const lineCount = String(el.value || "").split(/\r?\n/).length;
                    const long = lineCount > 7 || el.scrollHeight > el.clientHeight + 2;
                    btnExpand.hidden = !long;
                    btnExpand.textContent = "Xem chi tiết";
                };
                btnExpand.addEventListener("click", () => {
                    const expanded = el.classList.toggle("is-expanded");
                    if (expanded) {
                        el.style.height = "auto";
                        btnExpand.textContent = "Thu gọn";
                    } else {
                        el.style.height = "120px";
                        btnExpand.textContent = "Xem chi tiết";
                    }
                    syncOutlineUi();
                });
                el.addEventListener("input", () => {
                    if (!el.classList.contains("is-expanded")) syncOutlineUi();
                });
                btnAi.addEventListener("click", () => void runBulkRowAiSuggest(row.id, "custom_outline", el, btnAi));
                btnReplaceAll.addEventListener("click", () => {
                    const from = inpReplaceFrom.value.trim();
                    const to = inpReplaceTo.value.trim();
                    const outline = el.value;
                    if (!outline.trim()) {
                        toolsHint.textContent = "Vui lòng có outline trước khi Replace All.";
                        return;
                    }
                    if (!from) {
                        toolsHint.textContent = "Vui lòng nhập từ cần thay.";
                        return;
                    }
                    const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
                    const rgx = new RegExp(escaped, "gi");
                    const count = (outline.match(rgx) || []).length;
                    el.value = outline.replace(rgx, to);
                    row.custom_outline = el.value;
                    toolsHint.textContent = `Đã thay ${count} vị trí.`;
                    if (!el.classList.contains("is-expanded")) syncOutlineUi();
                });
                btnRefreshOutline.addEventListener("click", async () => {
                    const outline = el.value.trim();
                    if (!outline) {
                        toolsHint.textContent = "Vui lòng nhập outline trước khi làm mới.";
                        return;
                    }
                    btnRefreshOutline.disabled = true;
                    toolsHint.textContent = "Đang làm mới outline...";
                    try {
                        const res = await fetch(`/content-ai/outline-refresh?ts=${Date.now()}`, {
                            method: "POST",
                            headers: authJsonHeaders(),
                            body: JSON.stringify({ outline }),
                        });
                        const data = await res.json().catch(() => ({}));
                        if (!res.ok) throw new Error(_bulkFmtOutlineApiErr(data, "Làm mới outline thất bại."));
                        if (data.outline) {
                            el.value = data.outline;
                            row.custom_outline = data.outline;
                        }
                        toolsHint.textContent = "Đã làm mới outline bằng từ đồng nghĩa.";
                        if (!el.classList.contains("is-expanded")) syncOutlineUi();
                    } catch (e) {
                        toolsHint.textContent = String(e.message || e);
                    } finally {
                        btnRefreshOutline.disabled = false;
                    }
                });
                wrap.appendChild(el);
                w.appendChild(head);
                w.appendChild(tools);
                w.appendChild(toolsHint);
                w.appendChild(wrap);
                w.appendChild(btnExpand);
                requestAnimationFrame(syncOutlineUi);
                return w;
            };
            details.appendChild(siteWrap);
            details.appendChild(urlGrid);
            details.appendChild(mkField("Title (SEO)", "custom_title", "input", "Tiêu đề tùy chỉnh"));
            details.appendChild(mkField("Meta description", "custom_description", "input", "Mô tả meta 140–160 ký tự"));
            details.appendChild(mkOutlineField());
            const wcDetail = document.createElement("div");
            wcDetail.className = "field-mini";
            const wcDetailLabel = document.createElement("label");
            wcDetailLabel.textContent = "Số từ bài viết";
            const wcDetailHint = document.createElement("div");
            wcDetailHint.className = "hint";
            wcDetailHint.style.marginTop = "4px";
            wcDetailHint.textContent = "Chọn 1000 / 1500 / 2000 từ, nhập tùy chỉnh, hoặc để AI tự phân bổ.";
            wcDetail.appendChild(wcDetailLabel);
            wcDetail.appendChild(wcWrap);
            wcDetail.appendChild(wcDetailHint);
            details.appendChild(wcDetail);
            const wpMeta = document.createElement("div");
            wpMeta.className = "bulk-wp-meta-box bulk-wp-meta-box--row";
            const secHead = document.createElement("div");
            secHead.className = "bulk-field-head";
            const secLb = document.createElement("label");
            secLb.textContent = "Từ khóa phụ";
            const btnSecAi = document.createElement("button");
            btnSecAi.type = "button";
            btnSecAi.className = "ai-btn";
            btnSecAi.textContent = "Gợi ý AI";
            secHead.appendChild(secLb);
            secHead.appendChild(btnSecAi);
            const secIn = document.createElement("input");
            secIn.type = "text";
            secIn.dataset.field = "secondary_keywords";
            secIn.placeholder = "Cách nhau bằng dấu phẩy hoặc chấm phẩy";
            secIn.autocomplete = "off";
            secIn.value = row.secondary_keywords || "";
            btnSecAi.addEventListener("click", () => void runBulkRowAiSuggest(row.id, "secondary_keywords", secIn, btnSecAi));
            const secHint = document.createElement("div");
            secHint.className = "hint";
            secHint.style.marginTop = "4px";
            secHint.textContent = "Chỉ áp dụng cho từ khóa này — AI dùng khi viết outline / content.";
            wpMeta.appendChild(secHead);
            wpMeta.appendChild(secIn);
            wpMeta.appendChild(secHint);
            const catHead = document.createElement("div");
            catHead.className = "field-head";
            catHead.style.marginTop = "12px";
            const catLb = document.createElement("label");
            catLb.textContent = "Danh mục WordPress khi đăng";
            catHead.appendChild(catLb);
            const catRow = document.createElement("div");
            catRow.className = "row";
            catRow.style.alignItems = "flex-end";
            catRow.style.gap = "10px";
            catRow.style.flexWrap = "wrap";
            const catWrap = document.createElement("div");
            catWrap.style.flex = "1";
            catWrap.style.minWidth = "200px";
            const catSel = document.createElement("select");
            catSel.dataset.field = "wp_category_id";
            const skCat = _getBulkWpCategoriesSiteKey();
            const cachedCat = skCat ? _bulkWpCategoriesBySiteKey[skCat] : null;
            fillBulkCategorySelectEl(catSel, cachedCat || [], row.wp_category_id || "");
            const btnLoadCat = document.createElement("button");
            btnLoadCat.type = "button";
            btnLoadCat.className = "btn secondary";
            btnLoadCat.textContent = "Tải danh mục";
            const catHint = document.createElement("div");
            catHint.className = "hint";
            catHint.style.marginTop = "6px";
            catHint.textContent =
                "Nhập Target website trùng site đã lưu (Thêm site đăng bài), rồi bấm Tải danh mục — gắn category khi publish.";
            btnLoadCat.addEventListener("click", () => {
                btnLoadCat.disabled = true;
                void loadBulkWpCategoriesForRow(row.id, catSel, catHint).finally(() => {
                    btnLoadCat.disabled = false;
                });
            });
            catWrap.appendChild(catSel);
            catRow.appendChild(catWrap);
            catRow.appendChild(btnLoadCat);
            wpMeta.appendChild(catHead);
            wpMeta.appendChild(catRow);
            wpMeta.appendChild(catHint);
            details.appendChild(wpMeta);
            card.appendChild(main);
            card.appendChild(details);
            const syncField = (el) => {
                const f = el.dataset.field;
                if (!f || !_findBulkRow(row.id)) return;
                const r = _findBulkRow(row.id);
                if (f === "target_word_count_mode") {
                    const mode = String(el.value || "auto");
                    if (mode === "auto") r.target_word_count = "";
                    else if (mode === "custom") r.target_word_count = String(_clampBulkWordCount(wcIn.value));
                    else r.target_word_count = String(_clampBulkWordCount(mode));
                    syncWordCountUi();
                } else if (f === "target_word_count") {
                    if (String(wcSel.value || "") === "auto") {
                        r.target_word_count = "";
                    } else if (String(wcSel.value || "") === "custom") {
                        r.target_word_count = String(_clampBulkWordCount(el.value));
                    } else {
                        r.target_word_count = String(_clampBulkWordCount(wcSel.value));
                    }
                } else if (f === "target_website") {
                    const v = String(el.value || "").trim();
                    r.target_website =
                        v && typeof normalizeTargetBase === "function" ? normalizeTargetBase(v) : v;
                } else r[f] = el.value;
                scheduleSaveBulkState();
                updateBulkRemoveButtonForRow(row.id);
                try {
                    if (window.ContentAiBulkUi && typeof window.ContentAiBulkUi.refresh === "function") {
                        clearTimeout(window._bulkV2SetupRefreshTimer);
                        window._bulkV2SetupRefreshTimer = setTimeout(() => {
                            try { window.ContentAiBulkUi.refresh(); } catch (_) {}
                        }, 200);
                    }
                } catch (_) {}
            };
            typeSel.addEventListener("change", () => syncField(typeSel));
            wcSel.addEventListener("change", () => syncField(wcSel));
            wcIn.addEventListener("input", () => syncField(wcIn));
            wcIn.addEventListener("change", () => syncField(wcIn));
            urlIn.addEventListener("input", () => syncField(urlIn));
            details.querySelectorAll("[data-field]").forEach((el) => {
                el.addEventListener("input", () => syncField(el));
                el.addEventListener("change", () => syncField(el));
            });
            btnRemove.addEventListener("click", () => {
                bulkKeywordRows = bulkKeywordRows.filter((x) => x.id !== row.id);
                renderBulkKeywordList();
                updateBulkKwCount();
                scheduleSaveBulkState();
            });
            btnOutline.addEventListener("click", async () => {
                const r = _findBulkRow(row.id);
                if (!r) return;
                const url = String(r.competitor_url || urlIn.value || "").trim();
                if (!url) {
                    appendBulkLog(`[${r.keyword}] Chưa có URL đối thủ.`);
                    return;
                }
                r.competitor_url = url;
                btnOutline.disabled = true;
                btnOutline.textContent = "Đang lấy…";
                try {
                    const res = await fetch(`/content-ai/outline-reference?ts=${Date.now()}`, {
                        method: "POST",
                        headers: authJsonHeaders(),
                        body: JSON.stringify({ competitor_url: url }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error(_bulkFmtOutlineApiErr(data, "Không lấy outline"));
                    const outline = (data.outline || "").trim();
                    _bulkPatchOutlineUi(row.id, outline);
                    if (!_bulkEditorOpenForRow(row.id)) {
                        renderBulkKeywordList();
                    } else {
                        syncBulkV2Ui();
                    }
                    appendBulkLog(`[${r.keyword}] Đã lấy ${data.count || 0} heading outline.`);
                } catch (e) {
                    appendBulkLog(`[${r.keyword}] ${String(e.message || e)}`);
                } finally {
                    btnOutline.disabled = false;
                    btnOutline.textContent = "Lấy outline";
                }
            });
            bulkKeywordList.appendChild(card);
        });
        void ensureBulkVolumes();
        scheduleSaveBulkState();
        syncBulkToolbarButtons();
        syncBulkV2Ui();
        syncBulkStepButtons();
    };
    const setAllBulkDetailsOpen = (open) => {
        if (!bulkKeywordRows.length) return;
        _bulkToolbarView = open ? "expand" : "collapse";
        bulkKeywordRows.forEach((r) => { r.detailsOpen = !!open; });
        renderBulkKeywordList();
    };
    const syncBulkToolbarButtons = () => {
        const hasRows = bulkKeywordRows.length > 0;
        const expandActive = hasRows && _bulkToolbarView === "expand";
        const collapseActive = hasRows && _bulkToolbarView === "collapse";
        if (btnBulkExpandAll) {
            btnBulkExpandAll.disabled = !hasRows;
            btnBulkExpandAll.classList.toggle("is-open", expandActive);
            btnBulkExpandAll.setAttribute("aria-pressed", expandActive ? "true" : "false");
        }
        if (btnBulkCollapseAll) {
            btnBulkCollapseAll.disabled = !hasRows;
            btnBulkCollapseAll.classList.toggle("is-open", collapseActive);
            btnBulkCollapseAll.setAttribute("aria-pressed", collapseActive ? "true" : "false");
        }
    };
    const addBulkKeywordsFromParsed = async (parsedList, { fetchVolume = true } = {}) => {
        const toAdd = [];
        for (const parsed of parsedList) {
            const lk = parsed.keyword.toLowerCase();
            if (bulkKeywordRows.some((r) => r.keyword.toLowerCase() === lk)) continue;
            toAdd.push(parsed);
        }
        if (!toAdd.length) return 0;
        let accepted = toAdd;
        if (window.ContentAiDuplicate && typeof window.ContentAiDuplicate.filterBulk === "function") {
            try {
                const filtered = await window.ContentAiDuplicate.filterBulk(toAdd);
                accepted = filtered.kept || [];
                const rejected = filtered.rejected || [];
                if (rejected.length) {
                    window.ContentAiDuplicate.logBulkRejections(rejected);
                    if (typeof window.ContentAiDuplicate.renderBulkWarning === "function") {
                        window.ContentAiDuplicate.renderBulkWarning(rejected);
                    } else {
                        const warn = byId("bulkDuplicateWarning");
                        if (warn) {
                            warn.hidden = false;
                            warn.setAttribute("aria-hidden", "false");
                            const first = rejected[0].duplicate || {};
                            const existing = window.ContentAiDuplicate.formatExisting(first.existing);
                            warn.innerHTML = "";
                            const msg = document.createElement("div");
                            msg.className = "ca-dup-msg";
                            msg.textContent = rejected.length === 1
                                ? String(first.message || "Bài viết này đã tồn tại")
                                : `Đã bỏ ${rejected.length} từ khóa trùng bài đã có.`;
                            warn.appendChild(msg);
                            if (existing) {
                                const meta = document.createElement("div");
                                meta.className = "ca-dup-meta";
                                meta.textContent = existing;
                                warn.appendChild(meta);
                            }
                        }
                    }
                }
            } catch (_) {
                accepted = toAdd;
            }
        }
        if (!accepted.length) return 0;
        for (const parsed of accepted) {
            const row = _rowFromParsed(parsed);
            const hasVol = String(row.search_volume || "").trim() !== "";
            row._volumeLoading = !!fetchVolume && !hasVol;
            bulkKeywordRows.push(row);
        }
        renderBulkKeywordList();
        updateBulkKwCount();
        if (fetchVolume) {
            const needVol = accepted.filter((p) => !String(p.search_volume ?? "").trim());
            const volMap = needVol.length
                ? await fetchBulkSearchVolumes(needVol.map((p) => p.keyword))
                : {};
            for (const parsed of accepted) {
                const row = bulkKeywordRows.find((r) => r.keyword.toLowerCase() === parsed.keyword.toLowerCase());
                if (!row) continue;
                if (!row.search_volume) {
                    const item = volMap[parsed.keyword];
                    if (item && item.search_volume != null) {
                        row.search_volume = String(item.search_volume);
                    }
                }
                row._volumeLoading = false;
            }
            renderBulkKeywordList();
        }
        scheduleSaveBulkState();
        syncBulkV2Ui();
        syncBulkStepButtons();
        return accepted.length;
    };
    const _apiItemToParsed = (it) => ({
        keyword: String(it.keyword || "").trim(),
        custom_title: String(it.custom_title || "").trim(),
        custom_description: String(it.custom_description || "").trim(),
        custom_outline: String(it.custom_outline || "").trim(),
        search_volume: it.search_volume != null ? it.search_volume : "",
        content_type: String(it.content_type || "").trim(),
        target_word_count: it.target_word_count != null ? it.target_word_count : "",
        competitor_url: String(it.competitor_url || "").trim(),
        target_website: String(it.target_website || "").trim(),
        secondary_keywords: Array.isArray(it.secondary_keywords)
            ? it.secondary_keywords.map((x) => String(x).trim()).filter(Boolean).join(", ")
            : String(it.secondary_keywords || "").trim(),
    });
    let _bulkClusterPreview = null;
    let _bulkClusterPreviewBusy = false;
    const getBulkImportMode = () => {
        const checked = document.querySelector('input[name="bulkImportMode"]:checked');
        return checked && checked.value === "clustered" ? "clustered" : "normal";
    };
    const syncBulkImportModeUi = () => {
        const mode = getBulkImportMode();
        const title = byId("bulkImportSectionTitle");
        const hint = byId("bulkImportSectionHint");
        const addBar = byId("bulkKwAddBar");
        const advanced = byId("bulkImportAdvanced");
        const btn = byId("btnBulkImportFile");
        if (mode === "clustered") {
            if (title) title.textContent = "Upload file đã gom nhóm";
            if (hint) {
                hint.innerHTML =
                    "Hỗ trợ file từ Keyword Clustering: <code>Từ khóa chính</code> + <code>Từ khóa phụ</code>, " +
                    "hoặc cột <code>cluster_id</code> / <code>primary_keyword</code>. Mỗi cluster = 1 bài viết.";
            }
            if (addBar) addBar.hidden = true;
            if (advanced) advanced.hidden = true;
            if (btn) btn.textContent = "Tải & xem trước nhóm";
        } else {
            if (title) title.textContent = "Upload file từ khóa";
            if (hint) {
                hint.innerHTML =
                    "Hỗ trợ <code>.xlsx</code>, <code>.txt</code>, <code>.csv</code> — tự điền keyword, title, meta, outline, loại content, số từ, URL đối thủ.";
            }
            if (addBar) addBar.hidden = false;
            if (advanced) advanced.hidden = false;
            if (btn) btn.textContent = "Tải file vào danh sách";
        }
    };
    const closeBulkClusterPreview = (opts) => {
        if (_bulkClusterPreviewBusy && !(opts && opts.force)) return;
        _bulkClusterPreview = null;
        const back = byId("bulkClusterPreviewBackdrop");
        if (back) back.hidden = true;
    };
    const openBulkClusterPreview = (data) => {
        _bulkClusterPreview = {
            clusters: Array.isArray(data.clusters) ? data.clusters.map((c) => Object.assign({}, c)) : [],
            warnings: Array.isArray(data.warnings) ? data.warnings.slice() : [],
            meta: data.meta || {},
        };
        const back = byId("bulkClusterPreviewBackdrop");
        const summary = byId("bulkClusterPreviewSummary");
        const warnEl = byId("bulkClusterPreviewWarnings");
        const body = byId("bulkClusterPreviewBody");
        if (!back || !body) return;
        const n = _bulkClusterPreview.clusters.length;
        const members = Number((_bulkClusterPreview.meta && _bulkClusterPreview.meta.member_count) || 0);
        if (summary) {
            summary.innerHTML =
                "<strong>" + n + "</strong> bài sẽ tạo" +
                (members ? " · <strong>" + members + "</strong> từ khóa trong file" : "") +
                " · file: " + String((_bulkClusterPreview.meta && _bulkClusterPreview.meta.filename) || "");
        }
        if (warnEl) {
            const gw = _bulkClusterPreview.warnings || [];
            if (gw.length) {
                warnEl.hidden = false;
                warnEl.innerHTML = gw.map((w) => "<div>• " + String(w) + "</div>").join("");
            } else {
                warnEl.hidden = true;
                warnEl.innerHTML = "";
            }
        }
        body.innerHTML = "";
        _bulkClusterPreview.clusters.forEach((c, idx) => {
            const tr = document.createElement("tr");
            tr.dataset.idx = String(idx);
            const mems = Array.isArray(c.members) ? c.members : [];
            const sel = document.createElement("select");
            sel.className = "bulk-cluster-primary-select";
            sel.dataset.idx = String(idx);
            const opts = mems.length
                ? mems.map((m) => String(m.keyword || "").trim()).filter(Boolean)
                : [String(c.primary_keyword || "").trim()].filter(Boolean);
            opts.forEach((kw) => {
                const o = document.createElement("option");
                o.value = kw;
                o.textContent = kw;
                if (kw.toLowerCase() === String(c.primary_keyword || "").toLowerCase()) o.selected = true;
                sel.appendChild(o);
            });
            const warnText = (Array.isArray(c.warnings) && c.warnings.length) ? c.warnings.join("; ") : "—";
            tr.innerHTML =
                "<td><code>" + String(c.cluster_id || idx + 1) + "</code></td>" +
                '<td class="bulk-cluster-primary-cell"></td>' +
                "<td>" + Number(c.secondary_count != null ? c.secondary_count : (c.secondary_keywords || []).length) + "</td>" +
                "<td>" + String(c.intent || "—") + "</td>" +
                "<td>" + (c.search_volume != null ? c.search_volume : "—") + "</td>" +
                '<td class="bulk-cluster-warn-cell">' + warnText + "</td>";
            const cell = tr.querySelector(".bulk-cluster-primary-cell");
            if (cell) cell.appendChild(sel);
            body.appendChild(tr);
        });
        body.querySelectorAll(".bulk-cluster-primary-select").forEach((sel) => {
            sel.addEventListener("change", () => {
                const i = Number(sel.dataset.idx || -1);
                if (!_bulkClusterPreview || !_bulkClusterPreview.clusters[i]) return;
                const c = _bulkClusterPreview.clusters[i];
                const pk = String(sel.value || "").trim();
                c.primary_keyword = pk;
                const mems = Array.isArray(c.members) ? c.members : [];
                c.secondary_keywords = mems
                    .map((m) => String(m.keyword || "").trim())
                    .filter((k) => k && k.toLowerCase() !== pk.toLowerCase());
                c.secondary_count = c.secondary_keywords.length;
                const hit = mems.find((m) => String(m.keyword || "").toLowerCase() === pk.toLowerCase());
                if (hit && hit.search_volume != null) c.search_volume = hit.search_volume;
                const row = sel.closest("tr");
                if (row) {
                    const cells = row.querySelectorAll("td");
                    if (cells[2]) cells[2].textContent = String(c.secondary_count);
                    if (cells[4]) cells[4].textContent = c.search_volume != null ? String(c.search_volume) : "—";
                }
            });
        });
        back.hidden = false;
    };
    const confirmBulkClusterPreview = async () => {
        if (_bulkClusterPreviewBusy) return;
        if (!_bulkClusterPreview || !_bulkClusterPreview.clusters.length) {
            closeBulkClusterPreview();
            return;
        }
        const confirmBtn = byId("btnBulkClusterPreviewConfirm");
        const cancelBtn = byId("btnBulkClusterPreviewCancel");
        const closeBtn = byId("btnBulkClusterPreviewClose");
        const idleLabel = (confirmBtn && confirmBtn.getAttribute("data-idle-label"))
            || "Xác nhận — thêm vào bảng";
        const busyLabel = (confirmBtn && confirmBtn.getAttribute("data-busy-label"))
            || "Đang thêm vào bảng…";
        _bulkClusterPreviewBusy = true;
        if (confirmBtn) {
            confirmBtn.disabled = true;
            confirmBtn.setAttribute("aria-busy", "true");
            confirmBtn.classList.add("is-loading");
            confirmBtn.textContent = busyLabel;
        }
        if (cancelBtn) cancelBtn.disabled = true;
        if (closeBtn) closeBtn.disabled = true;
        try {
            const items = _bulkClusterPreview.clusters.map((c) => ({
                keyword: String(c.primary_keyword || "").trim(),
                custom_title: "",
                custom_description: c.intent ? ("Search intent: " + c.intent) : "",
                custom_outline: "",
                search_volume: c.search_volume != null ? c.search_volume : "",
                content_type: "",
                target_word_count: "",
                competitor_url: "",
                secondary_keywords: Array.isArray(c.secondary_keywords)
                    ? c.secondary_keywords.join(", ")
                    : String(c.secondary_keywords || ""),
            })).filter((x) => x.keyword);
            const n = await addBulkKeywordsFromParsed(items, { fetchVolume: false });
            _bulkClusterPreviewBusy = false;
            closeBulkClusterPreview({ force: true });
            const msg = n > 0
                ? `Đã thêm thành công ${n} từ khóa vào bảng.`
                : "Không thêm được từ khóa nào (có thể đã trùng trong danh sách).";
            if (bulkImportFileHint) {
                bulkImportFileHint.textContent =
                    "Đã thêm " + n + " bài từ " + items.length +
                    " nhóm (mỗi nhóm 1 từ khóa chính; từ khóa phụ đã lưu vào cấu hình).";
            }
            appendBulkLog("Import clustered: +" + n + " bài / " + items.length + " nhóm.");
            updateBulkKwCount();
            try {
                if (typeof showCaToast === "function") {
                    showCaToast(msg, n > 0 ? "success" : "warn");
                }
            } catch (_) {}
        } catch (e) {
            const errMsg = String((e && e.message) || e || "Không thêm được vào bảng.");
            appendBulkLog("Import clustered lỗi: " + errMsg);
            try {
                if (typeof showCaToast === "function") showCaToast(errMsg, "error");
            } catch (_) {}
        } finally {
            _bulkClusterPreviewBusy = false;
            if (confirmBtn) {
                confirmBtn.disabled = false;
                confirmBtn.removeAttribute("aria-busy");
                confirmBtn.classList.remove("is-loading");
                confirmBtn.textContent = idleLabel;
            }
            if (cancelBtn) cancelBtn.disabled = false;
            if (closeBtn) closeBtn.disabled = false;
        }
    };
    const importBulkUploadFile = async (file) => {
        if (!file) return 0;
        const name = String(file.name || "").toLowerCase();
        const mode = getBulkImportMode();
        if (bulkImportFileHint) bulkImportFileHint.textContent = `Đang đọc ${file.name}…`;
        const fd = new FormData();
        fd.append("file", file, file.name || "upload");
        try {
            const res = await fetch(`/content-ai/bulk-import/file?mode=${encodeURIComponent(mode)}&ts=${Date.now()}`, {
                method: "POST",
                body: fd,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = data.detail;
                throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail) || `HTTP ${res.status}`);
            }
            const wantClustered = mode === "clustered" || data.mode === "clustered" || data.preview === true;
            if (wantClustered) {
                const clusters = Array.isArray(data.clusters) ? data.clusters : [];
                if (!clusters.length) {
                    throw new Error(
                        "Không đọc được nhóm từ khóa (0 bài). Máy chủ có thể chưa tải code mới — " +
                        "hãy F5 lại trang và thử lại. File cần cột Group/cluster_id hoặc Từ khóa chính + Từ khóa phụ."
                    );
                }
                openBulkClusterPreview(data);
                if (bulkImportFileHint) {
                    const meta = data.meta || {};
                    bulkImportFileHint.textContent =
                        `Đã đọc ${data.article_count || clusters.length} nhóm từ ${meta.filename || name}. Xem trước và xác nhận.`;
                }
                return Number(data.article_count || clusters.length || 0);
            }
            const items = (data.items || []).map(_apiItemToParsed).filter((x) => x.keyword);
            if (!items.length) throw new Error("File không có dòng từ khóa hợp lệ.");
            const n = await addBulkKeywordsFromParsed(items, { fetchVolume: true });
            const meta = data.meta || {};
            if (bulkImportFileHint) {
                bulkImportFileHint.textContent = `Đã import ${n} từ khóa từ ${meta.filename || name} (${meta.format || "file"}).`;
            }
            appendBulkLog(`Import file: +${n} từ khóa (${meta.format || name}).`);
            return n;
        } catch (e) {
            const msg = String(e.message || e);
            if (bulkImportFileHint) bulkImportFileHint.textContent = msg;
            appendBulkLog(`Import file lỗi: ${msg}`);
            return 0;
        }
    };
    const parseBulkKeywords = (raw) => splitBulkKeywordInput(raw);

    const syncBulkV2Ui = () => {
        try {
            if (window.ContentAiBulkUi && typeof window.ContentAiBulkUi.refresh === "function") {
                window.ContentAiBulkUi.refresh();
            }
        } catch (_) {}
    };

    const syncBulkStepButtons = () => {
        const hasKw = bulkKeywordRows.length > 0;
        document.querySelectorAll("[data-bulk-goto]").forEach((btn) => {
            const step = btn.getAttribute("data-bulk-goto") || "";
            if (step === "setup" || step === "run" || step === "review") {
                btn.disabled = !hasKw;
                btn.classList.toggle("is-disabled", !hasKw);
            }
        });
    };

    const addBulkKeywords = async (parsedList, options = {}) => {
        const list = Array.isArray(parsedList) ? parsedList : [];
        if (!list.length) return 0;
        return addBulkKeywordsFromParsed(list, options);
    };

    const addBulkKeywordFromInput = async () => {
        const raw = bulkAddKeywordInput ? bulkAddKeywordInput.value : "";
        const parsedList = parseBulkKeywords(raw);
        if (!parsedList.length) {
            const msg = "Vui lòng nhập ít nhất 1 từ khóa hợp lệ.";
            appendBulkLog(msg);
            try {
                if (typeof showCaToast === "function") showCaToast(msg, "warn");
            } catch (_) {}
            return;
        }
        const n = await addBulkKeywords(parsedList, { fetchVolume: true });
        if (!n) {
            const msg = "Tất cả từ khóa đã có trong danh sách.";
            appendBulkLog(msg);
            try {
                if (typeof showCaToast === "function") showCaToast(msg, "info");
            } catch (_) {}
            return;
        }
        appendBulkLog(`Đã thêm ${n} từ khóa.`);
        if (bulkAddKeywordInput) bulkAddKeywordInput.value = "";
        refreshContentAiStepStates();
        syncBulkStepButtons();
    };
    const importBulkTextToList = async () => {
        const quick = parseBulkItemsText(bulkQuickInput ? bulkQuickInput.value : "");
        const plain = parseBulkItemsText(bulkKeywordsText ? bulkKeywordsText.value : "");
        const all = [...quick, ...plain];
        if (!all.length) {
            appendBulkLog("Không có dòng để import.");
            return;
        }
        const n = await addBulkKeywordsFromParsed(all, { fetchVolume: true });
        appendBulkLog(`Đã thêm ${n} từ khóa vào danh sách.`);
        if (bulkKeywordsText) bulkKeywordsText.value = "";
        if (bulkQuickInput) bulkQuickInput.value = "";
    };
    const updateBulkKwCount = () => {
        const items = mergeBulkItems();
        const n = items.length;
        const customN = items.filter((x) => x.custom_title || x.custom_description || x.custom_outline).length;
        const label = customN
            ? `${n} từ khóa (${customN} có cấu hình chi tiết)`
            : n
                ? `${n} từ khóa`
                : "Chưa có từ khóa trong danh sách.";
        if (bulkKwCount) bulkKwCount.textContent = label;
        const hint = byId("bulkKeywordCountHint");
        if (hint) hint.textContent = label;
        syncBulkStepButtons();
        return n;
    };
    const _rowFromStored = (s) => ({
        id: s.id || _bulkRowId(),
        keyword: String(s.keyword || "").trim(),
        search_volume: s.search_volume != null ? String(s.search_volume) : "",
        content_type: String(s.content_type || ""),
        target_word_count: s.target_word_count != null ? String(s.target_word_count) : "",
        competitor_url: String(s.competitor_url || ""),
        target_website: String(s.target_website || ""),
        custom_title: String(s.custom_title || ""),
        custom_description: String(s.custom_description || ""),
        custom_outline: String(s.custom_outline || ""),
        secondary_keywords: String(s.secondary_keywords || ""),
        wp_category_id: s.wp_category_id != null && s.wp_category_id !== undefined ? String(s.wp_category_id) : "",
        detailsOpen: !!s.detailsOpen,
        _volumeLoading: false,
    });
    const collectBulkState = () => ({
        target_website: (byId("bulkTargetWebsite") && byId("bulkTargetWebsite").value) || "",
        brand_name: (byId("bulkBrandName") && byId("bulkBrandName").value) || "",
        quick_input: bulkQuickInput ? bulkQuickInput.value : "",
        keywords_text: bulkKeywordsText ? bulkKeywordsText.value : "",
        add_keyword_input: bulkAddKeywordInput ? bulkAddKeywordInput.value : "",
        job_log: bulkJobLog ? bulkJobLog.value : "",
        main_view: (bulkWritePanel && !bulkWritePanel.hidden)
            ? "bulk"
            : (contentAiProjectSitesPanel && !contentAiProjectSitesPanel.hidden)
                ? "projects"
                : (_contentAiMainView || "single"),
        toolbar_view: _bulkToolbarView,
        rows: bulkKeywordRows.map((r) => ({
            id: r.id,
            keyword: r.keyword,
            search_volume: r.search_volume ?? "",
            content_type: r.content_type || "",
            target_word_count: r.target_word_count ?? "",
            competitor_url: r.competitor_url || "",
            target_website: r.target_website || "",
            custom_title: r.custom_title || "",
            custom_description: r.custom_description || "",
            custom_outline: r.custom_outline || "",
            secondary_keywords: r.secondary_keywords || "",
            wp_category_id: r.wp_category_id || "",
            detailsOpen: !!r.detailsOpen,
        })),
    });
    let _bulkSaveTimer = null;
    const saveBulkState = () => {
        try {
            localStorage.setItem(BULK_STATE_KEY(), JSON.stringify(collectBulkState()));
        } catch (_) {}
    };
    const scheduleSaveBulkState = () => {
        if (_bulkSaveTimer) clearTimeout(_bulkSaveTimer);
        _bulkSaveTimer = setTimeout(saveBulkState, 350);
    };
    const getSavedBulkMainView = () => {
        try {
            const raw = localStorage.getItem(BULK_STATE_KEY());
            if (!raw) return "";
            const s = JSON.parse(raw);
            if (!s || typeof s !== "object") return "";
            const mv = String(s.main_view || "").trim().toLowerCase();
            if (mv === "bulk" || mv === "single" || mv === "projects" || mv === "autoupdate" || mv === "publish") {
                return mv;
            }
            return "";
        } catch (_) {
            return "";
        }
    };
    const restoreBulkState = () => {
        try {
            const raw = localStorage.getItem(BULK_STATE_KEY());
            if (!raw) return false;
            const s = JSON.parse(raw);
            if (!s || typeof s !== "object") return false;
            const btw = byId("bulkTargetWebsite");
            const bbn = byId("bulkBrandName");
            if (btw) btw.value = s.target_website || "";
            if (bbn) {
                bbn.value =
                    s.brand_name != null && s.brand_name !== undefined ? String(s.brand_name) : "";
            }
            if (bulkQuickInput) bulkQuickInput.value = s.quick_input || "";
            if (bulkKeywordsText) bulkKeywordsText.value = s.keywords_text || "";
            if (bulkAddKeywordInput) bulkAddKeywordInput.value = s.add_keyword_input || "";
            if (bulkJobLog) bulkJobLog.value = s.job_log || "";
            _bulkToolbarView = s.toolbar_view === "expand" ? "expand" : "collapse";
            bulkKeywordRows = (s.rows || [])
                .map(_rowFromStored)
                .filter((r) => r.keyword);
            renderBulkKeywordList();
            updateBulkKwCount();
            syncBulkV2Ui();
            syncBulkStepButtons();
            return (
                bulkKeywordRows.length > 0 ||
                !!(btw && btw.value.trim()) ||
                !!(bbn && String(bbn.value || "").trim())
            );
        } catch (_) {
            return false;
        }
    };
    const appendBulkLog = (line) => {
        if (!bulkJobLog) return;
        const ts = new Date().toLocaleTimeString("vi-VN");
        bulkJobLog.value = `${bulkJobLog.value}[${ts}] ${line}\n`.trimStart();
        bulkJobLog.scrollTop = bulkJobLog.scrollHeight;
        scheduleSaveBulkState();
    };
    let _bulkJobItemsCache = [];
    const renderBulkJobItems = (items, opts) => {
        const incoming = items || [];
        let rows;
        if (opts && opts.mode === "merge" && _bulkJobItemsCache.length) {
            const byKw = Object.create(null);
            _bulkJobItemsCache.forEach((it) => {
                const kw = String(it.keyword || "").trim().toLowerCase();
                if (kw) byKw[kw] = { ...it };
            });
            incoming.forEach((it) => {
                const kw = String(it.keyword || "").trim().toLowerCase();
                if (!kw) return;
                byKw[kw] = { ...(byKw[kw] || {}), ...it, keyword: it.keyword || (byKw[kw] && byKw[kw].keyword) || kw };
            });
            rows = Object.values(byKw);
        } else {
            rows = incoming.slice();
        }
        _bulkJobItemsCache = rows.slice();
        try {
            if (window.ContentAiBulkUi && typeof window.ContentAiBulkUi.refreshJob === "function") {
                window.ContentAiBulkUi.refreshJob(rows);
            }
        } catch (_) {}
        if (bulkJobItems) bulkJobItems.innerHTML = "";
        if (!bulkJobItems) return;
        rows.forEach((it) => {
            const row = document.createElement("div");
            const st = String(it.status || "pending");
            row.className = `bulk-job-item ${st === "success" ? "ok" : st === "error" ? "err" : "pending"}`;
            const left = document.createElement("span");
            left.textContent = it.keyword || "—";
            const right = document.createElement("span");
            if (st === "success") {
                const score = it.seo_score != null ? ` · SEO ${it.seo_score}` : "";
                const iss =
                    it.seo_issue_count != null
                        ? ` · ${it.seo_issue_count} lỗi`
                        : Array.isArray(it.seo_issues) && it.seo_issues.length
                          ? ` · ${it.seo_issues.length} lỗi`
                          : "";
                const seoSt = it.seo_status === "pass" ? " · Đạt" : it.seo_status ? " · Cần kiểm tra" : "";
                right.textContent = `✓ xong${score}${iss}${seoSt}`;
            } else if (st === "error") right.textContent = "✗ lỗi";
            else if (st === "running") right.textContent = "… đang viết";
            else right.textContent = "…";
            row.appendChild(left);
            row.appendChild(right);
            bulkJobItems.appendChild(row);
        });
    };
    const getLastBulkJobId = () => {
        try {
            return String(localStorage.getItem(BULK_LAST_JOB_KEY()) || "").trim();
        } catch (_) {
            return "";
        }
    };
    const hydrateBulkStatusFromProjects = () => {
        const ui = window.ContentAiBulkUi;
        if (!ui || typeof ui.getJobItems !== "function" || typeof ui.refreshJob !== "function") return;
        const jobs = ui.getJobItems().slice();
        const rows = bulkKeywordRows || [];
        let projects = [];
        try {
            projects = typeof allProjects !== "undefined" && Array.isArray(allProjects) ? allProjects : [];
        } catch (_) {}
        if (!rows.length && !jobs.length && !projects.length) return;
        const byKw = Object.create(null);
        projects.forEach((p) => {
            const kw = String((p && p.primary_keyword) || "").trim().toLowerCase();
            if (kw && p && p.id) byKw[kw] = String(p.id).trim();
        });
        const mergedByKw = Object.create(null);
        jobs.forEach((j) => {
            const kw = String(j.keyword || "").trim().toLowerCase();
            if (!kw) return;
            let pid = String(j.project_id || "").trim();
            if (!pid && byKw[kw]) pid = byKw[kw];
            mergedByKw[kw] = { ...j, project_id: pid || j.project_id || "" };
        });
        rows.forEach((r) => {
            const kw = String(r.keyword || "").trim().toLowerCase();
            if (!kw || mergedByKw[kw]) return;
            const pid = byKw[kw] || "";
            if (pid) mergedByKw[kw] = { keyword: r.keyword, status: "success", project_id: pid };
        });
        const merged = Object.values(mergedByKw);
        if (merged.length) ui.refreshJob(merged);
    };
    const rehydrateBulkJobStatus = async (opts) => {
        const skipIfHasResult = !!(opts && opts.skipIfHasResult);
        const ui = window.ContentAiBulkUi;
        const current = ui && ui.getJobItems ? ui.getJobItems() : [];
        if (skipIfHasResult && current.some((j) => String(j.project_id || "").trim() || j.status === "success")) {
            hydrateBulkStatusFromProjects();
            return;
        }
        let jid = "";
        try {
            jid = String(localStorage.getItem(BULK_JOB_STORAGE_KEY()) || "").trim();
            if (!jid) jid = getLastBulkJobId();
        } catch (_) {}
        if (jid) {
            try {
                const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}?ts=${Date.now()}`, {
                    headers: authHeaders(),
                });
                const data = await res.json().catch(() => ({}));
                if (res.ok && data && data.result && Array.isArray(data.result.items) && data.result.items.length) {
                    renderBulkJobItems(data.result.items, { mode: "merge" });
                }
            } catch (_) {}
        }
        hydrateBulkStatusFromProjects();
    };
    const initBulkJobStatusTable = (keywords) => {
        const rows = (keywords || []).map((kw) => ({ keyword: String(kw || "").trim(), status: "pending" })).filter((x) => x.keyword);
        if (rows.length) renderBulkJobItems(rows);
    };
    const resetBulkWriteForm = () => {
        stopBulkPoll();
        try {
            localStorage.removeItem(BULK_JOB_STORAGE_KEY());
            localStorage.removeItem(BULK_STATE_KEY());
        } catch (_) {}
        const ids = ["bulkTargetWebsite", "bulkBrandName", "bulkQuickInput", "bulkKeywordsText", "bulkAddKeywordInput"];
        ids.forEach((id) => {
            const el = byId(id);
            if (el) el.value = "";
        });
        bulkKeywordRows = [];
        _bulkToolbarView = "collapse";
        renderBulkKeywordList();
        if (bulkKeywordsFile) bulkKeywordsFile.value = "";
        if (bulkImportFile) bulkImportFile.value = "";
        if (bulkImportFileHint) bulkImportFileHint.textContent = "";
        if (bulkJobLog) bulkJobLog.value = "";
        if (bulkJobItems) bulkJobItems.innerHTML = "";
        renderBulkJobItems([]);
        if (bulkJobProgress) bulkJobProgress.hidden = true;
        if (bulkJobProgressFill) bulkJobProgressFill.style.width = "0%";
        if (bulkJobPct) bulkJobPct.textContent = "0%";
        if (bulkJobStatus) bulkJobStatus.textContent = "";
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = true;
        updateBulkKwCount();
        syncBulkV2Ui();
        syncBulkStepButtons();
    };
    const resetContentAiSingleForm = () => {
        _draftWpCategoryIds = null;
        const singleCat = byId("singleWpCategoryId");
        if (singleCat) {
            singleCat.innerHTML = '<option value="">-- Chọn danh mục --</option>';
        }
        setHint("singleWpCategory", "");
        [
            "primaryKeyword",
            "targetWebsite",
            "title",
            "slug",
            "secondaryKeywords",
            "competitorUrl",
            "replaceFrom",
            "replaceTo",
            "outlineContent",
            "meta",
            "tags",
            "scheduledAt",
            "wpUrl",
            "imageUpload",
        ].forEach((id) => {
            const el = byId(id);
            if (el) el.value = "";
        });
        try {
            setContentValue("");
        } catch (_) {
            const el = byId("content");
            if (el) el.value = "";
        }
        try {
            refreshPreview();
        } catch (_) {}
        try {
            autoGrowOutline();
        } catch (_) {}
        try {
            setOutputAccordionOpen(false);
        } catch (_) {}
        if (publishLog) publishLog.value = "";
        if (out) out.value = "";
        const twcReset = byId("targetWordCount");
        if (twcReset) twcReset.value = "1000";
        uploadedImages.length = 0;
        activeProjectId = "";
        renderUploadList();
        toggleAiAvailability();
        syncSlugFromPrimary(true);
        _internalCandidates = [];
        if (internalLinkCandidates) internalLinkCandidates.innerHTML = "";
        setHint("internal-links", "");
        try {
            localStorage.removeItem(FORM_STATE_KEY());
        } catch (_) {}
        setHint("outline-actions", "");
        setHint("competitor", "");
        setDetectedIntentDebug("");
        try {
            refreshContentAiStepStates();
        } catch (_) {}
        try {
            scheduleSaveFormState();
        } catch (_) {}
    };
    let _contentAiActiveStep = "research";
    const syncCaSidebarNav = (view) => {
        const v = String(view || "single");
        document.querySelectorAll(".ca-sidebar-secondary .ca-nav-item[data-ca-nav]").forEach((btn) => {
            const nav = btn.getAttribute("data-ca-nav");
            btn.classList.toggle("active", nav === v);
        });
    };
    const syncContentAiMainTabs = (view) => {
        const v = String(view || "single");
        const tabs = byId("contentAiMainTabs");
        if (tabs) tabs.hidden = v === "projects" || v === "publish";
        const tabMainSingle = byId("tabMainSingle");
        const tabMainBulk = byId("tabMainBulk");
        const tabMainAutoUpdate = byId("tabMainAutoUpdate");
        if (tabMainSingle) tabMainSingle.classList.toggle("active", v === "single");
        if (tabMainBulk) tabMainBulk.classList.toggle("active", v === "bulk");
        if (tabMainAutoUpdate) tabMainAutoUpdate.classList.toggle("active", v === "autoupdate");
    };
    const _getContentAiStepDefs = () => {
        const view = String(_contentAiMainView || "single");
        if (view === "bulk") {
            return [
                {
                    key: "bulk-import",
                    done: () =>
                        bulkKeywordRows.length > 0 ||
                        !!(byId("bulkImportFile") && byId("bulkImportFile").files && byId("bulkImportFile").files.length),
                },
                { key: "bulk-setup", done: () => !!String(byId("bulkTargetWebsite")?.value || "").trim() },
                {
                    key: "bulk-run",
                    done: () => {
                        const el = byId("bulkJobProgress");
                        return !!(el && !el.hidden);
                    },
                },
                {
                    key: "bulk-review",
                    done: () => {
                        const tbody = byId("caBulkStatusBody");
                        return !!(tbody && tbody.querySelector("tr td:not(.ca-bulk-empty)"));
                    },
                },
            ];
        }
        const contentText = String(byId("content")?.value || "")
            .replace(/<[^>]+>/g, "")
            .trim();
        const uploadList = byId("uploadList");
        const hasMedia =
            !!(uploadList && uploadList.children.length) || !!(byId("contentRender")?.querySelector("img"));
        return [
            {
                key: "research",
                done: () =>
                    !!String(byId("primaryKeyword")?.value || "").trim() &&
                    !!String(byId("title")?.value || "").trim() &&
                    !!String(byId("meta")?.value || "").trim(),
            },
            { key: "outline", done: () => !!String(byId("outlineContent")?.value || "").trim() },
            { key: "content", done: () => contentText.length > 40 },
            {
                key: "links",
                done: () => {
                    const candidates = byId("internalLinkCandidates");
                    return !!(candidates && candidates.children && candidates.children.length);
                },
            },
            { key: "media", done: () => hasMedia },
            { key: "publish", done: () => false },
        ];
    };
    const _pickDefaultContentAiStep = (defs) => {
        const pending = (defs || []).find((d) => !d.done());
        return pending ? pending.key : (defs || [])[defs.length - 1]?.key || "research";
    };
    const scrollToContentAiStep = (scrollSel) => {
        const sel = String(scrollSel || "").trim();
        if (!sel) return;
        const el = document.querySelector(sel);
        if (!el) return;
        if (el.tagName === "DETAILS" && !el.open) el.open = true;
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        if (typeof el.focus === "function") {
            try {
                el.focus({ preventScroll: true });
            } catch (_) {}
        }
    };
    const CA_STEP_MODAL_TITLES = {
        research: "Brief",
        outline: "Outline",
        content: "Viết bài",
        links: "Internal Link",
        media: "Ảnh",
        publish: "Publish",
    };
    const _caStepModalKeys = new Set(Object.keys(CA_STEP_MODAL_TITLES));
    let _caStepModalOpenKey = "";
    const _caRestoreStepSection = (stepKey) => {
        const key = String(stepKey || "").trim();
        if (!key) return;
        const section = document.querySelector(`[data-ca-inline-section="${key}"]`);
        const slot = document.querySelector(`[data-ca-inline-slot="${key}"]`);
        if (section && slot && section.parentElement !== slot) {
            slot.appendChild(section);
        }
    };
    const _caEnsureInlineStepSections = () => {
        document.querySelectorAll("[data-ca-inline-slot]").forEach((slot) => {
            const key = slot.getAttribute("data-ca-inline-slot");
            if (!key) return;
            const section = document.querySelector(`[data-ca-inline-section="${key}"]`);
            if (section && section.parentElement !== slot) {
                slot.appendChild(section);
            }
        });
    };
    const _mountCaStepModalRoot = () => {
        let root = byId("contentAiModalRoot");
        if (!root) {
            root = document.createElement("div");
            root.id = "contentAiModalRoot";
            document.body.appendChild(root);
        } else if (root.parentElement !== document.body) {
            document.body.appendChild(root);
        }
        let overlay = byId("caStepModalOverlay");
        if (!overlay) {
            const backdrop = byId("caStepModalBackdrop");
            const modal = byId("caStepModal");
            if (backdrop && modal && backdrop.parentElement) {
                overlay = document.createElement("div");
                overlay.id = "caStepModalOverlay";
                overlay.className = "ca-step-modal-overlay";
                overlay.hidden = true;
                overlay.setAttribute("aria-hidden", "true");
                const parent = backdrop.parentElement;
                parent.insertBefore(overlay, backdrop);
                overlay.appendChild(backdrop);
                overlay.appendChild(modal);
            }
        }
        if (overlay && overlay.parentElement !== root) {
            root.appendChild(overlay);
        }
        return { root, overlay };
    };
    const closeCaStepModal = () => {
        const prevKey = _caStepModalOpenKey;
        const overlay = byId("caStepModalOverlay");
        if (overlay) {
            overlay.hidden = true;
            overlay.setAttribute("aria-hidden", "true");
        }
        _caRestoreStepSection(prevKey);
        document.body.classList.remove("content-ai-modal-open");
        document.body.classList.remove("ca-step-modal-open");
        _caStepModalOpenKey = "";
    };
    const syncIlTabContextDisplay = () => {
        const siteEl = byId("caIlTabDisplaySite");
        const kwEl = byId("caIlTabDisplayKw");
        if (siteEl) siteEl.textContent = String(byId("targetWebsite")?.value || "").trim() || "—";
        if (kwEl) kwEl.textContent = String(byId("primaryKeyword")?.value || "").trim() || "—";
    };
    const initCaModalTabs = (root) => {
        if (!root || root.dataset.caTabsBound) return;
        root.dataset.caTabsBound = "1";
        const tabs = root.querySelectorAll(".ca-modal-tab");
        const panels = root.querySelectorAll(".ca-modal-tab-panel");
        const switchTo = (index) => {
            tabs.forEach((t, i) => {
                const on = i === index;
                t.classList.toggle("active", on);
                t.setAttribute("aria-selected", on ? "true" : "false");
            });
            panels.forEach((p, i) => {
                if (i === index) p.removeAttribute("hidden");
                else p.setAttribute("hidden", "");
            });
            if (root.getAttribute("data-ca-modal-tabs") === "il") syncIlTabContextDisplay();
            if (index === 3 && window.__caRefreshContentDemo) {
                const kind = root.getAttribute("data-ca-modal-tabs");
                if (kind === "il") window.__caRefreshContentDemo("caIlDemoPreview", "links");
                if (kind === "media") window.__caRefreshContentDemo("caMediaDemoPreview", "media");
            }
        };
        tabs.forEach((tab) => {
            tab.addEventListener("click", (e) => {
                e.preventDefault();
                const idx = parseInt(tab.getAttribute("data-tab-index"), 10);
                if (Number.isFinite(idx)) switchTo(idx);
            });
        });
        root._caSwitchTab = switchTo;
    };
    const switchCaModalTab = (root, index) => {
        if (!root) return;
        if (!root.dataset.caTabsBound) initCaModalTabs(root);
        if (typeof root._caSwitchTab === "function") root._caSwitchTab(index);
    };
    window.__caSwitchModalTab = switchCaModalTab;
    window.__caSyncIlTabContext = syncIlTabContextDisplay;
    const openCaStepModal = (stepKey) => {
        const { overlay } = _mountCaStepModalRoot();
        const key = _caStepModalKeys.has(String(stepKey || "")) ? String(stepKey) : "research";
        const titleEl = byId("caStepModalTitle");
        const modalBody = byId("caStepModalBody");
        if (!overlay || !modalBody) return;
        if (_caStepModalOpenKey && _caStepModalOpenKey !== key) {
            _caRestoreStepSection(_caStepModalOpenKey);
        }
        const section = document.querySelector(`[data-ca-inline-section="${key}"]`);
        if (section) {
            modalBody.innerHTML = "";
            modalBody.appendChild(section);
        }
        if (titleEl) titleEl.textContent = CA_STEP_MODAL_TITLES[key] || key;
        overlay.hidden = false;
        overlay.setAttribute("aria-hidden", "false");
        document.body.classList.add("content-ai-modal-open");
        document.body.classList.add("ca-step-modal-open");
        _caStepModalOpenKey = key;
        if (key === "publish") {
            void loadPublishWpCategories();
        }
        if (key === "links") {
            syncIlTabContextDisplay();
            const ilRoot = byId("internalLinkPanel");
            if (ilRoot) {
                initCaModalTabs(ilRoot);
                switchCaModalTab(ilRoot, 0);
            }
            const btnIlDemo = byId("btnRefreshIlDemo");
            if (btnIlDemo && !btnIlDemo.dataset.bound) {
                btnIlDemo.dataset.bound = "1";
                btnIlDemo.addEventListener("click", (e) => {
                    e.preventDefault();
                    if (window.__caRefreshContentDemo) window.__caRefreshContentDemo("caIlDemoPreview", "links");
                });
            }
        }
        if (key === "media") {
            const mediaRoot = byId("contentAiMediaPanel");
            if (mediaRoot) {
                initCaModalTabs(mediaRoot);
                switchCaModalTab(mediaRoot, 0);
            }
            if (window.__caBindMediaFindOrCreate) {
                window.__caBindMediaFindOrCreate(byId("btnMediaFindOrCreate"));
            }
            if (window.__caRefreshMediaPanel) window.__caRefreshMediaPanel();
            const btnMediaDemo = byId("btnRefreshMediaDemo");
            if (btnMediaDemo && !btnMediaDemo.dataset.bound) {
                btnMediaDemo.dataset.bound = "1";
                btnMediaDemo.addEventListener("click", (e) => {
                    e.preventDefault();
                    if (window.__caRefreshContentDemo) window.__caRefreshContentDemo("caMediaDemoPreview", "media");
                });
            }
        }
        const closeBtn = byId("caStepModalClose");
        if (closeBtn) {
            try { closeBtn.focus({ preventScroll: true }); } catch (_) {}
        }
    };
    window.__caOpenStepModal = openCaStepModal;
    window.__caCloseStepModal = closeCaStepModal;
    const initCaStepModals = () => {
        _mountCaStepModalRoot();
        _caEnsureInlineStepSections();
        document.querySelectorAll("[data-ca-proxy]").forEach((btn) => {
            if (btn._caProxyBound) return;
            btn._caProxyBound = true;
            btn.addEventListener("click", () => {
                const targetId = btn.getAttribute("data-ca-proxy");
                const target = targetId ? byId(targetId) : null;
                if (target && !target.disabled) target.click();
            });
        });
        const overlay = byId("caStepModalOverlay");
        const backdrop = byId("caStepModalBackdrop");
        const modal = byId("caStepModal");
        const closeBtn = byId("caStepModalClose");
        if (backdrop && !backdrop._caStepModalBound) {
            backdrop._caStepModalBound = true;
            backdrop.addEventListener("click", closeCaStepModal);
        }
        if (overlay && !overlay._caStepModalBound) {
            overlay._caStepModalBound = true;
            overlay.addEventListener("click", (e) => {
                if (e.target === overlay) closeCaStepModal();
            });
        }
        if (modal && !modal._caStepModalBound) {
            modal._caStepModalBound = true;
            modal.addEventListener("click", (e) => e.stopPropagation());
        }
        if (closeBtn && !closeBtn._caStepModalBound) {
            closeBtn._caStepModalBound = true;
            closeBtn.addEventListener("click", closeCaStepModal);
        }
        if (!document._caStepModalEscBound) {
            document._caStepModalEscBound = true;
            document.addEventListener("keydown", (e) => {
                if (e.key === "Escape" && _caStepModalOpenKey) closeCaStepModal();
            });
        }
        document.querySelectorAll("[data-ca-step-modal]").forEach((btn) => {
            if (btn._caStepModalTriggerBound) return;
            btn._caStepModalTriggerBound = true;
            btn.addEventListener("click", () => {
                openCaStepModal(btn.getAttribute("data-ca-step-modal"));
            });
        });
        const gotoEd = byId("btnStepGotoEditor");
        if (gotoEd && !gotoEd._caStepBound) {
            gotoEd._caStepBound = true;
            gotoEd.addEventListener("click", () => {
                closeCaStepModal();
                scrollToContentAiStep("#previewShell");
            });
        }
        const seoScroll = byId("btnSeoScrollPublish");
        if (seoScroll && !seoScroll._caStepScrollBound) {
            seoScroll._caStepScrollBound = true;
            seoScroll.addEventListener("click", () => openCaStepModal("publish"));
        }
    };
    initCaStepModals();
    const closeCaSeoScorePanel = () => {
        const overlay = byId("caSeoScoreOverlay");
        const openBtn = byId("btnOpenSeoScorePanel");
        if (overlay) {
            overlay.hidden = true;
            overlay.setAttribute("aria-hidden", "true");
        }
        if (openBtn) openBtn.setAttribute("aria-expanded", "false");
        document.body.classList.remove("content-ai-modal-open");
    };
    const openCaSeoScorePanel = () => {
        let root = byId("contentAiModalRoot");
        const overlay = byId("caSeoScoreOverlay");
        const openBtn = byId("btnOpenSeoScorePanel");
        if (!overlay) return;
        if (root && overlay.parentElement !== root) root.appendChild(overlay);
        overlay.hidden = false;
        overlay.setAttribute("aria-hidden", "false");
        if (openBtn) openBtn.setAttribute("aria-expanded", "true");
        document.body.classList.add("content-ai-modal-open");
        if (typeof refreshPublishChecklist === "function") void refreshPublishChecklist();
        const closeBtn = byId("btnSeoScoreClose");
        if (closeBtn) {
            try { closeBtn.focus({ preventScroll: true }); } catch (_) {}
        }
    };
    const initCaSeoScorePopup = () => {
        const openBtn = byId("btnOpenSeoScorePanel");
        const overlay = byId("caSeoScoreOverlay");
        const backdrop = byId("caSeoScoreBackdrop");
        const closeBtn = byId("btnSeoScoreClose");
        if (openBtn && !openBtn._caSeoPopupBound) {
            openBtn._caSeoPopupBound = true;
            openBtn.addEventListener("click", openCaSeoScorePanel);
        }
        if (backdrop && !backdrop._caSeoPopupBound) {
            backdrop._caSeoPopupBound = true;
            backdrop.addEventListener("click", closeCaSeoScorePanel);
        }
        if (closeBtn && !closeBtn._caSeoPopupBound) {
            closeBtn._caSeoPopupBound = true;
            closeBtn.addEventListener("click", closeCaSeoScorePanel);
        }
        if (!document._caSeoPopupEscBound) {
            document._caSeoPopupEscBound = true;
            document.addEventListener("keydown", (e) => {
                const ov = byId("caSeoScoreOverlay");
                if (e.key === "Escape" && ov && !ov.hidden) closeCaSeoScorePanel();
            });
        }
        const dialog = overlay && overlay.querySelector(".ca-seo-score-dialog");
        if (dialog && !dialog._caSeoPopupBound) {
            dialog._caSeoPopupBound = true;
            dialog.addEventListener("click", (e) => e.stopPropagation());
        }
    };
    initCaSeoScorePopup();
    const initBulkClusterImportUi = () => {
        syncBulkImportModeUi();
        document.querySelectorAll('input[name="bulkImportMode"]').forEach((el) => {
            if (el._bulkImportModeBound) return;
            el._bulkImportModeBound = true;
            el.addEventListener("change", syncBulkImportModeUi);
        });
        const closeBtn = byId("btnBulkClusterPreviewClose");
        const cancelBtn = byId("btnBulkClusterPreviewCancel");
        const confirmBtn = byId("btnBulkClusterPreviewConfirm");
        const back = byId("bulkClusterPreviewBackdrop");
        if (closeBtn && !closeBtn._bound) {
            closeBtn._bound = true;
            closeBtn.addEventListener("click", closeBulkClusterPreview);
        }
        if (cancelBtn && !cancelBtn._bound) {
            cancelBtn._bound = true;
            cancelBtn.addEventListener("click", closeBulkClusterPreview);
        }
        if (confirmBtn && !confirmBtn._bound) {
            confirmBtn._bound = true;
            confirmBtn.addEventListener("click", () => void confirmBulkClusterPreview());
        }
        if (back && !back._bound) {
            back._bound = true;
            back.addEventListener("click", (e) => {
                if (e.target === back) closeBulkClusterPreview();
            });
        }
    };
    initBulkClusterImportUi();
    window.__caOpenSeoScorePanel = openCaSeoScorePanel;
    window.__caCloseSeoScorePanel = closeCaSeoScorePanel;
    const closeCaStudioPanel = () => {
        const overlay = byId("caStudioOverlay");
        const openBtn = byId("btnOpenCaStudioPanel");
        if (overlay) {
            overlay.hidden = true;
            overlay.setAttribute("aria-hidden", "true");
        }
        if (openBtn) openBtn.setAttribute("aria-expanded", "false");
        document.body.classList.remove("content-ai-modal-open");
    };
    const openCaStudioPanel = () => {
        let root = byId("contentAiModalRoot");
        const overlay = byId("caStudioOverlay");
        const openBtn = byId("btnOpenCaStudioPanel");
        if (!overlay) return;
        if (root && overlay.parentElement !== root) root.appendChild(overlay);
        if (window.ContentAiUsage && window.ContentAiUsage.refresh) {
            void window.ContentAiUsage.refresh();
        }
        overlay.hidden = false;
        overlay.setAttribute("aria-hidden", "false");
        if (openBtn) openBtn.setAttribute("aria-expanded", "true");
        document.body.classList.add("content-ai-modal-open");
        const closeBtn = byId("btnCaStudioClose");
        if (closeBtn) {
            try { closeBtn.focus({ preventScroll: true }); } catch (_) {}
        }
    };
    const initCaStudioPopup = () => {
        const openBtn = byId("btnOpenCaStudioPanel");
        const overlay = byId("caStudioOverlay");
        const backdrop = byId("caStudioBackdrop");
        const closeBtn = byId("btnCaStudioClose");
        if (openBtn && !openBtn._caStudioPopupBound) {
            openBtn._caStudioPopupBound = true;
            openBtn.addEventListener("click", openCaStudioPanel);
        }
        if (backdrop && !backdrop._caStudioPopupBound) {
            backdrop._caStudioPopupBound = true;
            backdrop.addEventListener("click", closeCaStudioPanel);
        }
        if (closeBtn && !closeBtn._caStudioPopupBound) {
            closeBtn._caStudioPopupBound = true;
            closeBtn.addEventListener("click", closeCaStudioPanel);
        }
        if (!document._caStudioPopupEscBound) {
            document._caStudioPopupEscBound = true;
            document.addEventListener("keydown", (e) => {
                const ov = byId("caStudioOverlay");
                if (e.key === "Escape" && ov && !ov.hidden) closeCaStudioPanel();
            });
        }
        const dialog = overlay && overlay.querySelector(".ca-studio-dialog");
        if (dialog && !dialog._caStudioPopupBound) {
            dialog._caStudioPopupBound = true;
            dialog.addEventListener("click", (e) => e.stopPropagation());
        }
    };
    initCaStudioPopup();
    window.__caOpenStudioPanel = openCaStudioPanel;
    window.__caCloseStudioPanel = closeCaStudioPanel;
    const refreshContentAiStepStates = () => {
        const view = String(_contentAiMainView || "single");
        const stepView = view === "bulk" ? "bulk" : "single";
        const defs = _getContentAiStepDefs();
        const visibleKeys = [];
        document.querySelectorAll(".ca-vsteps").forEach((nav) => {
            const sv = nav.getAttribute("data-ca-steps-view") || "single";
            nav.hidden = sv !== stepView || view === "projects" || view === "publish";
        });
        syncContentAiMainTabs(view);
        document.querySelectorAll(`.ca-vsteps[data-ca-steps-view="${stepView}"] .ca-hstep-item`).forEach((btn) => {
            const key = btn.getAttribute("data-ca-step");
            if (!key) return;
            visibleKeys.push(key);
            const def = defs.find((d) => d.key === key);
            btn.classList.toggle("done", !!(def && def.done()));
            btn.classList.toggle("active", key === _contentAiActiveStep);
        });
        if (visibleKeys.length && !visibleKeys.includes(_contentAiActiveStep)) {
            _contentAiActiveStep = _pickDefaultContentAiStep(defs);
            document.querySelectorAll(`.ca-vsteps[data-ca-steps-view="${stepView}"] .ca-hstep-item`).forEach((btn) => {
                btn.classList.toggle("active", btn.getAttribute("data-ca-step") === _contentAiActiveStep);
            });
        }
        syncCaSidebarNav(view);
    };
    const _focusContentEditor = () => {
        closeCaStepModal();
        if (String(_contentAiMainView || "single") !== "single") setContentAiMainView("single");
        scrollToContentAiStep("#previewShell");
        const ed = byId("contentRender");
        if (ed && typeof ed.focus === "function") {
            try { ed.focus({ preventScroll: true }); } catch (_) { ed.focus(); }
        }
    };
    const _bindWorkflowSteps = () => {
        document.querySelectorAll(".ca-vsteps .ca-hstep-item").forEach((btn) => {
            if (btn._caHstepBound) return;
            btn._caHstepBound = true;
            btn.addEventListener("click", () => {
                const key = btn.getAttribute("data-ca-step");
                if (key) _contentAiActiveStep = key;
                refreshContentAiStepStates();
                if (key === "content") {
                    _focusContentEditor();
                    return;
                }
                const modalKey = btn.getAttribute("data-ca-step-modal");
                if (modalKey) openCaStepModal(modalKey);
                const scrollSel = btn.getAttribute("data-ca-scroll");
                if (scrollSel) scrollToContentAiStep(scrollSel);
            });
        });
    };
    _bindWorkflowSteps();
    _contentAiActiveStep = _pickDefaultContentAiStep(_getContentAiStepDefs());
    refreshContentAiStepStates();
    const setContentAiMainView = (view) => {
        const v = String(view || "single");
        _contentAiMainView = v;
        const showBulk = v === "bulk";
        const showProjects = v === "projects";
        const showPublish = v === "publish";
        const showAutoUpdate = v === "autoupdate";
        const autoUpdatePanel = byId("contentAiAutoUpdatePanel");
        if (bulkWritePanel) bulkWritePanel.hidden = !showBulk;
        if (contentAiSinglePanel) contentAiSinglePanel.hidden = showBulk || showProjects || showAutoUpdate;
        if (autoUpdatePanel) autoUpdatePanel.hidden = !showAutoUpdate;
        if (contentAiProjectSitesPanel) contentAiProjectSitesPanel.hidden = !showProjects;
        if (contentAiSidebar) {
            const steps = contentAiSidebar.querySelectorAll(".ca-vsteps");
            steps.forEach((nav) => { nav.hidden = showAutoUpdate; });
        }
        if (contentAiSidebar) contentAiSidebar.classList.remove("sidebar-collapsed");
        syncContentAiMainTabs(v);
        syncCaSidebarNav(v);
        if (showProjects) {
            try {
                renderConnectedSitesPanel();
            } catch (_) {}
            void refreshProjects();
            if (contentAiProjectSitesPanel) {
                contentAiProjectSitesPanel.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        } else if (showPublish) {
            const pub = byId("contentAiPublishBar");
            if (pub) pub.scrollIntoView({ behavior: "smooth", block: "start" });
        } else if (showAutoUpdate) {
            if (typeof window.__cauLoadSites === "function") {
                window.__cauLoadSites().catch(() => {});
            } else if (typeof window.__cauSyncUi === "function") {
                window.__cauSyncUi();
            }
        }
        if (!showProjects) {
            if (showBulk) _contentAiActiveStep = "bulk-import";
            else if (showPublish) _contentAiActiveStep = "publish";
            else _contentAiActiveStep = _pickDefaultContentAiStep(_getContentAiStepDefs());
            refreshContentAiStepStates();
        } else {
            document.querySelectorAll(".ca-vsteps").forEach((nav) => { nav.hidden = true; });
        }
        scheduleSaveBulkState();
    };

    const _BULK_BRAND_STOP = new Set([
        "sua", "repair", "service", "services", "dich", "vu", "cai", "dat", "win", "windows",
        "may", "tinh", "laptop", "pc", "macbook", "imac", "desktop", "printer", "print",
        "dien", "thoai", "in", "lanh", "anh", "giat", "ban", "mua", "thue",
        "cua", "hang", "shop", "store", "showroom", "daily", "dai", "ly", "chi", "nhanh",
        "uy", "tin", "chuyen", "nghiep", "nhanh", "chong", "gia", "re", "tot", "nhat",
        "tai", "nha", "tan", "noi", "gan", "day", "online", "local", "home", "center", "centre",
        "va", "cho", "cac", "mot", "nhung", "la", "co", "khong", "duoc", "tu", "voi", "o",
        "quan", "huyen", "phuong", "thi", "xa", "tp", "thanh", "pho", "district", "khu", "vuc",
        "q", "p", "hcm", "sg", "saigon", "hochiminh", "vietnam", "viet", "nam",
    ]);

    const _BULK_GEO_PHRASES = [
        "thu duc", "binh thanh", "go vap", "tan binh", "tan phu", "phu nhuan",
        "binh tan", "nha be", "can gio", "hoc mon", "cu chi", "binh chanh",
        "thu thiem", "tan thuan", "an phu", "phu my hung", "quan 1", "quan 2",
        "quan 3", "quan 4", "quan 5", "quan 6", "quan 7", "quan 8", "quan 9",
        "quan 10", "quan 11", "quan 12", "q 1", "q 2", "q 3", "q 4", "q 5",
        "q 6", "q 7", "q 8", "q 9", "q 10", "q 11", "q 12",
    ];

    const _foldBulkVi = (s) => {
        try {
            return String(s || "")
                .normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "")
                .replace(/đ/g, "d")
                .replace(/Đ/g, "d")
                .toLowerCase()
                .replace(/\s+/g, " ")
                .trim();
        } catch (_) {
            return String(s || "").toLowerCase().replace(/\s+/g, " ").trim();
        }
    };

    const _parseBulkBrandTerms = (raw) => {
        const folded = _foldBulkVi(raw);
        if (!folded) return [];
        return folded
            .split(/[,;|/]+/)
            .map((x) => x.trim())
            .filter((x) => x.length >= 2);
    };

    /** Local-service / store keywords that often append a brand name. */
    const _bulkKeywordHasCommercialSignal = (folded) =>
        /\b(sua|repair|dich\s*vu|cai\s*win|cai\s*dat|service|services|cua\s*hang|shop|store|showroom|dai\s*ly|chi\s*nhanh)\b/.test(folded);

    const _bulkBrandResidualTokens = (keyword) => {
        let folded = _foldBulkVi(keyword);
        if (!folded) return [];
        // Longer geo phrases first.
        const geos = _BULK_GEO_PHRASES.slice().sort((a, b) => b.length - a.length);
        for (const phrase of geos) {
            folded = folded.split(phrase).join(" ");
        }
        folded = folded
            .replace(/\b(?:quan|q\.?|huyen|phuong|district)\s*\d{1,2}\b/g, " ")
            .replace(/\b\d{1,2}\b/g, " ");
        return folded
            .split(/[^a-z0-9]+/)
            .filter((t) => t && t.length >= 2 && !_BULK_BRAND_STOP.has(t));
    };

    // Common Vietnamese leftover words that are NOT brands.
    const _BULK_NON_BRAND_RESIDUAL = new Set([
        "loi", "len", "nguon", "man", "hinh", "xanh", "wifi", "mang", "cham", "treo",
        "nhiet", "pin", "sac", "den", "mo", "tat", "dot", "ngot", "huong", "dan", "cach",
        "nguyen", "nhan", "khac", "phuc", "bao", "hanh", "doi", "moi", "cu", "re",
    ]);

    const _bulkLooksLikeBrandToken = (tok) => {
        const t = String(tok || "");
        if (t.length < 3) return false;
        if (_BULK_NON_BRAND_RESIDUAL.has(t)) return false;
        // Latin brand-like tokens (dolozi, itdolozi) or mixed alphanumerics.
        if (/[0-9]/.test(t)) return true;
        if (t.length >= 5) return true;
        // Short brand acronyms / names: pci, dell, asus…
        if (t.length >= 3 && t.length <= 4) return true;
        return false;
    };

    const isBulkBrandKeyword = (keyword, extraBrandTerms) => {
        const kw = String(keyword || "").trim();
        if (!kw) return false;
        const folded = _foldBulkVi(kw);
        const brands = Array.isArray(extraBrandTerms) ? extraBrandTerms : _parseBulkBrandTerms(extraBrandTerms);
        for (const brand of brands) {
            if (!brand || brand.length <= 2) continue;
            if (
                folded === brand
                || folded.includes(` ${brand} `)
                || folded.startsWith(`${brand} `)
                || folded.endsWith(` ${brand}`)
                || folded.includes(brand)
            ) {
                return true;
            }
        }

        const residual = _bulkBrandResidualTokens(kw);
        const brandish = residual.filter(_bulkLooksLikeBrandToken);

        // Service/store + leftover brand tokens (e.g. "cửa hàng laptop quận 9 dolozi store").
        if (_bulkKeywordHasCommercialSignal(folded) && brandish.length > 0) {
            return true;
        }

        // Pure brand-like short phrase (e.g. "PCI", "itdolozi", "dolozi store").
        const toks = folded.split(/[^a-z0-9]+/).filter(Boolean);
        if (
            toks.length >= 1
            && toks.length <= 4
            && !_bulkKeywordHasCommercialSignal(folded)
            && !/\b(?:quan|huyen|phuong|district)\b/.test(folded)
            && toks.every((t) => !_BULK_BRAND_STOP.has(t) && !/^\d+$/.test(t))
        ) {
            const joined = toks.join(" ");
            if (!_BULK_GEO_PHRASES.includes(joined) && brandish.length > 0) {
                return true;
            }
        }
        return false;
    };

    const findBulkBrandKeywordRows = (extraBrandTerms) => {
        const brandEl = byId("bulkBrandName");
        const fromField = _parseBulkBrandTerms(brandEl ? brandEl.value : "");
        const extra = Array.isArray(extraBrandTerms)
            ? extraBrandTerms
            : _parseBulkBrandTerms(extraBrandTerms);
        const brands = Array.from(new Set([...fromField, ...extra]));
        return bulkKeywordRows.filter((row) => isBulkBrandKeyword(row && row.keyword, brands));
    };

    const removeBulkBrandKeywordRows = (extraBrandTerms) => {
        const hits = findBulkBrandKeywordRows(extraBrandTerms);
        if (!hits.length) return { removed: 0, keywords: [] };
        const ids = hits.map((r) => r.id);
        const keywords = hits.map((r) => String(r.keyword || "").trim()).filter(Boolean);
        const idSet = new Set(ids.map((x) => String(x || "")).filter(Boolean));
        const before = bulkKeywordRows.length;
        bulkKeywordRows = bulkKeywordRows.filter((x) => !idSet.has(x.id));
        const removed = before - bulkKeywordRows.length;
        if (removed > 0) {
            renderBulkKeywordList();
            updateBulkKwCount();
            scheduleSaveBulkState();
            syncBulkV2Ui();
            syncBulkStepButtons();
        }
        return { removed, keywords };
    };

    window.ContentAiBulkCore = {
        getRows: () => bulkKeywordRows.slice(),
        findRow: (id) => bulkKeywordRows.find((r) => r.id === id) || null,
        removeRows: (ids) => {
            const idSet = new Set((ids || []).map((x) => String(x || "")).filter(Boolean));
            if (!idSet.size) return 0;
            const before = bulkKeywordRows.length;
            bulkKeywordRows = bulkKeywordRows.filter((x) => !idSet.has(x.id));
            const removed = before - bulkKeywordRows.length;
            if (removed > 0) {
                renderBulkKeywordList();
                updateBulkKwCount();
                scheduleSaveBulkState();
                syncBulkV2Ui();
                syncBulkStepButtons();
            }
            return removed;
        },
        removeAllRows: () => {
            const n = bulkKeywordRows.length;
            if (!n) return 0;
            bulkKeywordRows = [];
            renderBulkKeywordList();
            updateBulkKwCount();
            scheduleSaveBulkState();
            syncBulkV2Ui();
            syncBulkStepButtons();
            return n;
        },
        isBrandKeyword: isBulkBrandKeyword,
        findBrandKeywordRows: findBulkBrandKeywordRows,
        removeBrandKeywordRows: removeBulkBrandKeywordRows,
        rowToApiItem: (row) => bulkRowToApiItem(row),
        isItemSetupComplete: (item) => isBulkItemSetupComplete(item),
        renderKeywordList: () => {
            renderBulkKeywordList();
        },
        notifyStep: (step) => {
            const s = String(step || "").trim();
            if (s) _contentAiActiveStep = `bulk-${s}`;
            refreshContentAiStepStates();
            syncBulkStepButtons();
        },
        parseBulkKeywords,
        addBulkKeywords,
        addBulkKeywordsFromInput: addBulkKeywordFromInput,
        saveBulkState,
        syncBulkV2Ui,
        syncBulkStepButtons,
        startWriteSelected: async (keywords) => {
            const list = (keywords || []).map((k) => String(k || "").trim().toLowerCase()).filter(Boolean);
            if (!list.length) return;
            const rows = bulkKeywordRows.filter((r) => list.includes(String(r.keyword || "").trim().toLowerCase()));
            if (!rows.length) return;
            const prev = bulkKeywordRows.slice();
            try {
                bulkKeywordRows = rows;
                const btn = byId("btnBulkWriteStart");
                if (btn) btn.click();
                else appendBulkLog("Không tìm thấy nút Bắt đầu viết bài.");
            } finally {
                setTimeout(() => {
                    bulkKeywordRows = prev;
                    renderBulkKeywordList();
                    syncBulkV2Ui();
                }, 800);
            }
        },
        loadProject: (pid) => {
            if (typeof loadProjectIntoWriteTab === "function") return loadProjectIntoWriteTab(pid);
            return Promise.resolve();
        },
        getJobItems: () => {
            try {
                if (window.ContentAiBulkUi && typeof window.ContentAiBulkUi.getJobItems === "function") {
                    return window.ContentAiBulkUi.getJobItems();
                }
            } catch (_) {}
            return [];
        },
        getBulkJobId: () => {
            try {
                const active = localStorage.getItem(BULK_JOB_STORAGE_KEY()) || "";
                if (active) return active;
                return localStorage.getItem(BULK_LAST_JOB_KEY()) || "";
            } catch (_) {
                return "";
            }
        },
        rehydrateBulkJobStatus,
        hydrateBulkStatusFromProjects,
    };
