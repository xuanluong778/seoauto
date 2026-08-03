    const refreshProjects = async (preferLatest = false) => {
        if (!getAuthToken()) {
            allProjects = [];
            activeProjectId = "";
            renderProjects();
            return;
        }
        try {
            const items = await fetchProjects();
            allProjects = await enrichProjectsWithStats(items || []);
            if (preferLatest && allProjects.length && !activeProjectId) {
                activeProjectId = allProjects[0].id;
            }
            renderProjects();
            if (siteArticlesModalEl && siteArticlesModalEl.classList.contains("open") && _siteArticlesModalCtx.base) {
                try {
                    await renderSiteArticlesBoard();
                } catch (_) {}
            }
        } catch (e) {
            allProjects = [];
            activeProjectId = "";
            renderProjects();
            projectHint.textContent = String(e.message || e);
        }
    };
    if (btnProjectPrev) {
        btnProjectPrev.addEventListener("click", () => {
            projectPage = Math.max(1, projectPage - 1);
            renderProjects();
        });
    }
    if (btnProjectNext) {
        btnProjectNext.addEventListener("click", () => {
            projectPage = 1;
            renderProjects();
        });
    }
    const btnClearProjectSiteFilter = byId("btnClearProjectSiteFilter");
    if (btnClearProjectSiteFilter) {
        btnClearProjectSiteFilter.addEventListener("click", () => {
            _projectsSiteFilterBase = "";
            projectPage = 1;
            renderProjects();
            try {
                renderConnectedSitesPanel();
            } catch (_) {}
        });
    }
    const railNav = document.querySelector(".content-ai-nav");
    const setRailActive = (activeEl) => {
        if (!railNav) return;
        railNav.querySelectorAll(".content-ai-nav-item").forEach((n) => n.classList.remove("active"));
        if (activeEl) activeEl.classList.add("active");
    };
    if (railNav) {
        railNav.querySelectorAll("a.content-ai-nav-item").forEach((a) => {
            a.addEventListener("click", () => {
                setRailActive(a);
            });
        });
    }
    const BULK_JOB_STORAGE_KEY = () => userStorageKey("content_ai_bulk_job_id_v1");
    const BULK_LAST_JOB_KEY = () => userStorageKey("content_ai_bulk_last_job_id_v1");
    const BULK_STATE_KEY = () => userStorageKey("content_ai_bulk_state_v1");
    const _bulkWpCategoriesBySiteKey = Object.create(null);
    const _getWpCategoriesSiteKey = (siteUrlRaw) => {
        let site = siteUrlRaw != null ? String(siteUrlRaw).trim() : "";
        if (!site) {
            const tw = byId("bulkTargetWebsite");
            site = tw ? String(tw.value || "").trim() : "";
        }
        const cred = resolveWpPublishCredentialsForSite(site);
        return String(cred.wpUrl || "").trim().toLowerCase() || "";
    };
    const _getBulkWpCategoriesSiteKey = () => _getWpCategoriesSiteKey("");
    const fillBulkCategorySelectEl = (selectEl, items, savedId) => {
        if (!selectEl) return;
        const cur = String(savedId != null && savedId !== undefined ? savedId : selectEl.value || "").trim();
        selectEl.innerHTML = '<option value="">-- Chọn danh mục --</option>';
        (items || []).forEach((it) => {
            const id = it && it.id != null ? String(it.id) : "";
            const name = it && it.name ? String(it.name) : id;
            if (!id) return;
            const opt = document.createElement("option");
            opt.value = id;
            opt.textContent = name;
            selectEl.appendChild(opt);
        });
        if (cur && ![...selectEl.options].some((o) => o.value === cur)) {
            const opt = document.createElement("option");
            opt.value = cur;
            opt.textContent = `Danh mục #${cur}`;
            selectEl.appendChild(opt);
        }
        if (cur && [...selectEl.options].some((o) => o.value === cur)) {
            selectEl.value = cur;
        }
    };
    const resolveWpCredentialsForBulk = async (siteUrlRaw) => {
        const site = String(siteUrlRaw || "").trim();
        let cred = resolveWpPublishCredentialsForSite(site);
        if (cred.username && cred.app_password) {
            return cred;
        }
        const local = findProfilesForSiteUrl(site).find((p) => normalizePlatform(p.platform) === "wordpress");
        if (local) {
            cred = {
                wpUrl: profileSiteUrl(local) || cred.wpUrl,
                username: String(local.username || "").trim(),
                app_password: String(local.app_password || "").trim().replace(/\s+/g, ""),
            };
            if (cred.username && cred.app_password) return cred;
        }
        await fetchSettingsPublishingSites();
        const key = connectedSiteKey(site);
        const hit = settingsPublishingSitesFlat.find(
            (s) => normalizePlatform(s.platform) === "wordpress" && connectedSiteKey(s.url) === key
        );
        if (hit && hit.id) {
            const full = await fetchPublishingSiteWithSecrets(hit.id);
            if (full) {
                cred = {
                    wpUrl: normalizeWpUrl(full.url || hit.url) || cred.wpUrl,
                    username: String(full.username || hit.username || "").trim(),
                    app_password: String(full.app_password || "").trim().replace(/\s+/g, ""),
                };
            }
        }
        return cred;
    };
    const loadWpCategoriesForSite = async ({ siteUrlRaw, selectEl, hintEl, savedId = "" }) => {
        const site = String(siteUrlRaw ?? "").trim();
        if (!site) {
            if (hintEl) hintEl.textContent = "Nhập Target website trước.";
            return false;
        }
        const cred = await resolveWpCredentialsForBulk(site);
        if (!cred.username || !cred.app_password) {
            const msg =
                "Chưa có username / Application Password — mở «Thêm site đăng bài», nhập đủ và bấm «Lưu & áp dụng».";
            if (hintEl) hintEl.textContent = msg;
            return false;
        }
        const sk = _getWpCategoriesSiteKey(site);
        if (!sk) return false;
        if (hintEl) hintEl.textContent = "Đang tải danh mục…";
        try {
            const body = {
                url: cred.wpUrl || normalizeWpUrl(site) || site,
                username: cred.username,
                app_password: cred.app_password,
            };
            const paths = pubApiPaths.wordpress.categories || ["/content-ai/wordpress/categories"];
            let data = {};
            let lastStatus = 0;
            for (const path of paths) {
                const res = await fetch(path, {
                    method: "POST",
                    headers: authHeaders({ "Content-Type": "application/json" }),
                    body: JSON.stringify(body),
                });
                lastStatus = res.status;
                data = await res.json().catch(() => ({}));
                if (res.status !== 404) break;
            }
            if (lastStatus === 404) {
                throw new Error(
                    "API tải danh mục chưa có (404). Khởi động lại run.bat / uvicorn, rồi Ctrl+F5 trang này."
                );
            }
            if (lastStatus === 401 || lastStatus === 403) {
                throw new Error("Vui lòng đăng nhập rồi thử lại.");
            }
            if (lastStatus >= 400 && !data.ok) {
                throw new Error(fmtApiDetail(data.detail) || data.message || `HTTP ${lastStatus}`);
            }
            if (!data.ok) {
                if (hintEl) hintEl.textContent = data.message || "Không tải được danh mục.";
                return false;
            }
            _bulkWpCategoriesBySiteKey[sk] = data.items || [];
            fillBulkCategorySelectEl(selectEl, _bulkWpCategoriesBySiteKey[sk], savedId);
            if (hintEl) hintEl.textContent = data.message || `Đã tải ${(data.items || []).length} danh mục.`;
            return true;
        } catch (e) {
            if (hintEl) hintEl.textContent = String((e && e.message) || e);
            return false;
        }
    };
    const loadBulkWpCategoriesForRow = async (rowId, selectEl, hintEl) => {
        const tw = byId("bulkTargetWebsite");
        const site = tw ? tw.value.trim() : "";
        const r = _findBulkRow(rowId);
        const ok = await loadWpCategoriesForSite({
            siteUrlRaw: site,
            selectEl,
            hintEl,
            savedId: r ? r.wp_category_id : "",
        });
        if (ok) scheduleSaveBulkState();
    };
    const loadSingleWpCategories = async () => {
        const site = String(byId("targetWebsite")?.value || "").trim();
        const sel = byId("singleWpCategoryId");
        const hint = byId("hint-singleWpCategory");
        const saved =
            (_draftWpCategoryIds && _draftWpCategoryIds[0]) ||
            String(sel?.value || "").trim() ||
            "";
        const ok = await loadWpCategoriesForSite({
            siteUrlRaw: site,
            selectEl: sel,
            hintEl: hint,
            savedId: saved,
        });
        if (ok) {
            syncSingleWpCategoryFromSelect();
            saveFormState();
        }
    };
    let _publishWpCatTimer = null;
    const loadPublishWpCategories = async () => {
        const site = String(byId("wpUrl")?.value || "").trim();
        const pubSel = byId("singleWpCategoryIdPublish");
        const hint = byId("hint-wp");
        if (!site) {
            if (hint) hint.textContent = "";
            return false;
        }
        const saved =
            (_draftWpCategoryIds && _draftWpCategoryIds[0]) ||
            String(pubSel?.value || "").trim() ||
            "";
        const ok = await loadWpCategoriesForSite({
            siteUrlRaw: site,
            selectEl: pubSel,
            hintEl: hint,
            savedId: saved,
        });
        if (ok) {
            const sk = _getWpCategoriesSiteKey(site);
            const cached = sk ? _bulkWpCategoriesBySiteKey[sk] : null;
            const sel = byId("singleWpCategoryId");
            if (sel && cached) fillBulkCategorySelectEl(sel, cached, saved);
            syncSingleWpCategoryFromSelect();
            saveFormState();
        }
        return ok;
    };
    const schedulePublishWpCategoriesLoad = () => {
        if (_publishWpCatTimer) clearTimeout(_publishWpCatTimer);
        _publishWpCatTimer = setTimeout(() => {
            const site = String(byId("wpUrl")?.value || "").trim();
            if (!site || site.length < 4) return;
            void loadPublishWpCategories();
        }, 500);
    };
    let _bulkPollTimer = null;
    const bulkWritePanel = byId("bulkWritePanel");
    const contentAiSinglePanel = byId("contentAiSinglePanel");
    const contentAiSidebar = byId("contentAiSidebar");
    const contentAiProjectSitesPanel = byId("contentAiProjectSitesPanel");
    const contentAiMainTabs = byId("contentAiMainTabs");
    const bulkKeywordsText = byId("bulkKeywordsText");
    const bulkQuickInput = byId("bulkQuickInput");
    const bulkKeywordsFile = byId("bulkKeywordsFile");
    const bulkImportFile = byId("bulkImportFile");
    const btnBulkImportFile = byId("btnBulkImportFile");
    const bulkImportFileHint = byId("bulkImportFileHint");
    const bulkKwCount = byId("bulkKwCount");
    const bulkKeywordList = byId("bulkKeywordList");
    const bulkKeywordListEmpty = byId("bulkKeywordListEmpty");
    const bulkAddKeywordInput = byId("bulkAddKeywordInput");
    const btnBulkAddKeyword = byId("btnBulkAddKeyword");
    const btnBulkExpandAll = byId("btnBulkExpandAll");
    const btnBulkCollapseAll = byId("btnBulkCollapseAll");
    const btnBulkImportText = byId("btnBulkImportText");
    const bulkJobLog = byId("bulkJobLog");
    const bulkJobProgress = byId("bulkJobProgress");
    const bulkJobProgressFill = byId("bulkJobProgressFill");
    const bulkJobStatus = byId("bulkJobStatus");
    const bulkJobPct = byId("bulkJobPct");
    const bulkJobItems = byId("bulkJobItems");
    const BULK_CONTENT_TYPES = [
        { value: "", label: "Loại content" },
        { value: "blog", label: "Blog / Informational" },
        { value: "landing", label: "Landing dịch vụ" },
        { value: "category", label: "Trang danh mục" },
        { value: "comparison", label: "So sánh / Review" },
        { value: "howto", label: "Hướng dẫn How-to" },
        { value: "local", label: "Local / Địa phương" },
    ];
    let bulkKeywordRows = [];
    let _bulkToolbarView = "collapse";
    let _contentAiMainView = "single";
    const _bulkRowId = () => `bk_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    const parseBulkInputLine = (line) => {
        let raw = String(line || "").trim();
        if (!raw) return null;
        if (raw.startsWith('"') && raw.endsWith('"') && raw.length > 1) raw = raw.slice(1, -1).trim();
        let keyword = "";
        let custom_title = "";
        let custom_description = "";
        let custom_outline = "";
        if (raw.includes("|")) {
            const parts = raw.split("|").map((x) => x.trim());
            keyword = parts[0] || "";
            custom_title = parts[1] || "";
            custom_description = parts[2] || "";
            custom_outline = parts.slice(3).join(" | ").trim();
        } else if (raw.includes(",") && !/\bH[1-3]\s*:/i.test(raw)) {
            keyword = raw.split(",")[0].trim();
        } else {
            keyword = raw;
        }
        keyword = keyword.replace(/\s+/g, " ").trim();
        if (!keyword) return null;
        return { keyword, custom_title, custom_description, custom_outline };
    };
    const parseBulkItemsText = (raw) => {
        const lines = String(raw || "").replace(/\r/g, "").split("\n");
        const out = [];
        const seen = new Set();
        for (const line of lines) {
            const row = parseBulkInputLine(line);
            if (!row) continue;
            const lk = row.keyword.toLowerCase();
            if (seen.has(lk)) continue;
            seen.add(lk);
            out.push(row);
        }
        return out;
    };
    const _defaultBulkWordCount = () => null;
    const _parseBulkWordCount = (n) => {
        const raw = String(n ?? "").trim().toLowerCase();
        if (!raw || raw === "auto") return null;
        const v = parseInt(raw, 10);
        if (!v || v < 200) return null;
        return Math.min(8000, v);
    };
    const _clampBulkWordCount = (n) => {
        const parsed = _parseBulkWordCount(n);
        if (parsed != null) return parsed;
        return 1000;
    };
    const splitBulkKeywordInput = (raw) => {
        const text = String(raw || "").trim();
        if (!text) return [];
        const out = [];
        const seen = new Set();
        const lines = text.replace(/\r/g, "\n").split("\n");
        for (const line of lines) {
            const chunks = String(line || "")
                .split(/[,;]+/)
                .map((x) => x.trim())
                .filter(Boolean);
            for (const chunk of chunks) {
                const parsed = parseBulkInputLine(chunk);
                if (!parsed) continue;
                const lk = parsed.keyword.toLowerCase();
                if (seen.has(lk)) continue;
                seen.add(lk);
                out.push(parsed);
            }
        }
        return out;
    };
    const _rowFromParsed = (parsed, extra = {}) => {
        const hasVol = parsed.search_volume != null && String(parsed.search_volume).trim() !== "";
        const sv = hasVol
            ? String(parsed.search_volume)
            : extra.search_volume != null
              ? String(extra.search_volume)
              : "";
        const parsedWc = _parseBulkWordCount(parsed.target_word_count);
        const extraWc = _parseBulkWordCount(extra.target_word_count);
        const wc = parsedWc != null
            ? parsedWc
            : extraWc != null
              ? extraWc
              : _defaultBulkWordCount();
        const comp = (parsed.competitor_url || extra.competitor_url || "").trim();
        const btw = byId("bulkTargetWebsite");
        const globalTw = btw ? String(btw.value || "").trim() : "";
        const rowTw = String(parsed.target_website || extra.target_website || globalTw || "").trim();
        let secStr = "";
        if (Array.isArray(parsed.secondary_keywords)) {
            secStr = parsed.secondary_keywords.map((x) => String(x).trim()).filter(Boolean).join(", ");
        } else if (parsed.secondary_keywords != null) {
            secStr = String(parsed.secondary_keywords).trim();
        }
        const wpc = parsed.wp_category_id != null ? String(parsed.wp_category_id).trim() : "";
        return {
            id: _bulkRowId(),
            keyword: parsed.keyword,
            search_volume: sv,
            content_type: (parsed.content_type || extra.content_type || "").trim(),
            target_word_count: wc == null ? "" : String(wc),
            competitor_url: comp,
            target_website: rowTw,
            custom_title: parsed.custom_title || "",
            custom_description: parsed.custom_description || "",
            custom_outline: parsed.custom_outline || "",
            secondary_keywords: secStr,
            wp_category_id: wpc,
            detailsOpen: !!(
                parsed.custom_title ||
                parsed.custom_description ||
                parsed.custom_outline ||
                comp ||
                rowTw ||
                secStr ||
                wpc
            ),
        };
    };
    const _bulkRowTargetWebsite = (row) => {
        const rowSite = String((row && row.target_website) || "").trim();
        if (rowSite) {
            return typeof normalizeTargetBase === "function" ? normalizeTargetBase(rowSite) : rowSite;
        }
        const btw = byId("bulkTargetWebsite");
        const globalTw = btw ? String(btw.value || "").trim() : "";
        if (!globalTw) return "";
        return typeof normalizeTargetBase === "function" ? normalizeTargetBase(globalTw) : globalTw;
    };
    const bulkRowToApiItem = (row) => {
        const secStr = String(row.secondary_keywords || "").trim();
        const secondary_keywords = secStr
            .split(/[,;\n\r]+/)
            .map((s) => s.trim())
            .filter(Boolean);
        let wp_category_id = null;
        const wpc = String(row.wp_category_id || "").trim();
        if (wpc) {
            const n = parseInt(wpc, 10);
            if (!Number.isNaN(n) && n > 0) wp_category_id = n;
        }
        return {
            keyword: row.keyword,
            custom_title: row.custom_title || "",
            custom_description: row.custom_description || "",
            custom_outline: row.custom_outline || "",
            search_volume: row.search_volume ? parseInt(row.search_volume, 10) || 0 : 0,
            content_type: row.content_type || "",
            competitor_url: row.competitor_url || "",
            target_website: _bulkRowTargetWebsite(row),
            target_word_count: _parseBulkWordCount(row.target_word_count),
            secondary_keywords,
            wp_category_id,
        };
    };
    const mergeBulkItems = () => bulkKeywordRows.map(bulkRowToApiItem);
    const isBulkItemSetupComplete = (item) => {
        const title = String(item.custom_title || "").trim();
        const desc = String(item.custom_description || "").trim();
        const outline = String(item.custom_outline || "").trim();
        const wc = item.target_word_count == null ? null : Number(item.target_word_count) || 0;
        return !!(title && desc && outline && (wc == null || wc >= 200));
    };
    const filterBulkItemsByWriteMode = (items, mode) => {
        const list = items || [];
        if (mode === "setup") {
            return list.filter(isBulkItemSetupComplete);
        }
        return list;
    };
    const countBulkSetupComplete = (items) => (items || []).filter(isBulkItemSetupComplete).length;
    const parseBulkKeywordsText = (raw) => parseBulkItemsText(raw).map((x) => x.keyword);
    const mergeBulkKeywords = () => mergeBulkItems().map((x) => x.keyword);
    const _findBulkRow = (id) => bulkKeywordRows.find((r) => r.id === id);
    const updateBulkRemoveButtonForRow = (rowId) => {
        const r = _findBulkRow(rowId);
        if (!r || !bulkKeywordList) return;
        const esc = String(rowId).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        const card = bulkKeywordList.querySelector(`.bulk-kw-card[data-id="${esc}"]`);
        const rm = card && card.querySelector(".btn-bulk-remove");
        if (!rm) return;
        const ok = isBulkItemSetupComplete(bulkRowToApiItem(r));
        rm.classList.toggle("btn-bulk-remove-incomplete", !ok);
        rm.title = ok ? "Xóa" : "Xóa — chưa setup đủ (title, meta, outline, số từ ≥ 200)";
    };
    const buildBulkSuggestContext = (row) => {
        const tw = _bulkRowTargetWebsite(row);
        const brand = (byId("bulkBrandName") && String(byId("bulkBrandName").value || "").trim()) || "";
        return {
            title: String(row.custom_title || row.keyword || "").trim(),
            primary_keyword: String(row.keyword || "").trim(),
            target_website: tw,
            outline_content: String(row.custom_outline || ""),
            meta_description: String(row.custom_description || ""),
            secondary_keywords: String(row.secondary_keywords || "").trim(),
            content: brand ? `TÊN THƯƠNG HIỆU: ${brand}` : "",
            target_word_count: _clampBulkWordCount(row.target_word_count),
            slug: "",
            tags: "",
        };
    };
    const runBulkRowAiSuggest = async (rowId, bulkField, inputEl, btnEl) => {
        const r = _findBulkRow(rowId);
        if (!r) return;
        if (!String(r.keyword || "").trim()) {
            appendBulkLog("Cần từ khóa để gợi ý AI.");
            return;
        }
        const apiMap = {
            custom_title: "title",
            custom_description: "meta_description",
            custom_outline: "outline_content",
            secondary_keywords: "secondary_keywords",
        };
        const apiField = apiMap[bulkField] || bulkField;
        const bulkSuggestLabels = {
            custom_title: "title",
            custom_description: "meta",
            custom_outline: "outline",
            secondary_keywords: "từ khóa phụ",
        };
        const oldLabel = btnEl ? btnEl.textContent : "";
        if (btnEl) {
            btnEl.disabled = true;
            btnEl.textContent = "Đang gợi ý…";
        }
        try {
            const out = await fetchSuggestion(apiField, buildBulkSuggestContext(r));
            let val = String(out.value || "").trim();
            if (bulkField === "custom_title" || bulkField === "custom_description") {
                val = _firstLine(val);
            }
            r[bulkField] = val;
            if (inputEl) inputEl.value = val;
            if (val && !r.detailsOpen) r.detailsOpen = true;
            appendBulkLog(`[${r.keyword}] Đã gợi ý ${bulkSuggestLabels[bulkField] || bulkField}.`);
        } catch (e) {
            const msg = String(e.message || e);
            appendBulkLog(`[${r.keyword}] Gợi ý AI lỗi: ${msg}`);
        } finally {
            if (btnEl) {
                btnEl.disabled = false;
                btnEl.textContent = oldLabel || "Gợi ý AI";
            }
            scheduleSaveBulkState();
            updateBulkRemoveButtonForRow(rowId);
        }
    };
    let _bulkVolumeFetchRunning = false;
    const fetchBulkSearchVolumes = async (keywords) => {
        const kws = [...new Set((keywords || []).map((k) => String(k || "").trim()).filter(Boolean))];
        if (!kws.length) return {};
        try {
            const res = await fetch("/keywords/volume/batch", {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ keywords: kws.slice(0, 200), country: "vn", language: "vi" }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return {};
            return (data && data.items) || {};
        } catch (_) {
            return {};
        }
    };
    const ensureBulkVolumes = async () => {
        if (_bulkVolumeFetchRunning) return;
        const missing = bulkKeywordRows.filter((r) => !String(r.search_volume || "").trim() && !r._volumeLoading);
        if (!missing.length) return;
        _bulkVolumeFetchRunning = true;
        missing.forEach((r) => {
            r._volumeLoading = true;
        });
        renderBulkKeywordList();
        try {
            const volMap = await fetchBulkSearchVolumes(missing.map((r) => r.keyword));
            missing.forEach((r) => {
                const item = volMap[r.keyword];
                if (item && item.search_volume != null) {
                    r.search_volume = String(item.search_volume);
                }
                r._volumeLoading = false;
            });
        } catch (_) {
            missing.forEach((r) => {
                r._volumeLoading = false;
            });
        }
        renderBulkKeywordList();
        _bulkVolumeFetchRunning = false;
    };
