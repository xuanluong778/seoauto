    /* Content Auto Update */
    const CAU_ACTION_BUTTONS = {
        connect: ["btnCauConnect"],
        test: ["btnCauTestSite"],
        fetch: ["btnCauFetch"],
        scan: ["btnCauScanPosts"],
        scanRefresh: ["btnCauRefreshScan"],
        scanCats: ["btnCauScanCategories"],
        loadMore: ["btnCauLoadMorePosts"],
        generate: ["btnCauGenerate"],
        preview: ["btnCauPreview"],
        publishDraft: ["btnCauSaveDraft"],
        publishLive: ["btnCauPublishLive"],
        history: ["btnCauRefreshHistory"],
        modalAnalyze: ["btnCauModalAnalyze"],
        modalUpdate: ["btnCauModalUpdate"],
    };

    const CAU_LOAD_LABELS = {
        scanCats: "Đang tải danh mục...",
        scan: "Đang quét bài...",
        scanRefresh: "Đang làm mới dữ liệu...",
        loadMore: "Đang tải thêm...",
        modalAnalyze: "AI đang phân tích SEO Core 30...",
        modalUpdate: "Đang cập nhật WordPress...",
    };

    const CAU_MODAL_DRAFT_KEY = () => (
        typeof userStorageKey === "function"
            ? userStorageKey("content_ai_cau_modal_draft_v1")
            : "content_ai_cau_modal_draft_v1"
    );
    const CAU_SITE_ID_KEY = "content_ai_cau_site_id";
    const CAU_CAT_HISTORY_KEY = "content_ai_cau_category_history";
    const CAU_WORKSPACE_KEY = () => (
        typeof userStorageKey === "function"
            ? userStorageKey("content_ai_cau_workspace_v1")
            : "content_ai_cau_workspace_v1"
    );

    const CAU_SKIP_LINK_PREFIXES = ["javascript:", "mailto:", "tel:", "#"];
    const CAU_FACTOR_FIX_SCOPES = {
        intent_title_match: "title",
        intent_h1_keyword: "content",
        intent_answer_early: "content",
        helpful_word_count: "content",
        helpful_actionable: "content",
        helpful_faq_conclusion: "content",
        eeat_specifics: "content",
        eeat_unique_value: "content",
        eeat_trust_signals: "content",
        title_keyword: "title",
        meta_quality: "meta",
        slug_seo: "slug",
        heading_single_h1: "content",
        heading_h2_count: "content",
        heading_hierarchy: "content",
        keyword_in_body: "content",
        keyword_density: "content",
        semantic_keywords: "content",
        depth_word_count: "content",
        depth_paragraphs: "content",
        depth_per_section: "content",
        links_internal: "content",
        links_external: "content",
        links_anchor_text: "content",
        media_images: "content",
        media_alt_text: "content",
        media_schema_blockquote: "content",
        readability_sentence: "content",
        readability_paragraphs: "content",
        readability_formatting: "content",
    };

    const normalizeVietnameseSeoText = (text) => {
        const raw = String(text || "").trim().toLowerCase()
            .normalize("NFD")
            .replace(/đ/g, "d")
            .replace(/[\u0300-\u036f]/g, "");
        return raw.replace(/[^\w\s-]/g, " ")
            .replace(/[\s_\-]+/g, " ")
            .trim();
    };

    const isInternalLink = (href, postUrl) => {
        const h = String(href || "").trim();
        if (!h) return false;
        const lower = h.toLowerCase();
        if (CAU_SKIP_LINK_PREFIXES.some((p) => lower.startsWith(p))) return false;
        if (h.startsWith("/")) return true;
        try {
            const link = new URL(h.includes("://") ? h : "https://" + h);
            if (link.protocol && link.protocol !== "http:" && link.protocol !== "https:") return false;
            const post = new URL(String(postUrl || "").trim() || "https://example.com");
            const lh = (link.hostname || "").toLowerCase().replace(/^www\./, "");
            const ph = (post.hostname || "").toLowerCase().replace(/^www\./, "");
            return !!(lh && ph && lh === ph);
        } catch (_) {
            return false;
        }
    };

    const hasWordPressH1 = (title, contentHtml) => {
        if (String(title || "").trim()) return true;
        return /<h1\b/i.test(String(contentHtml || ""));
    };

    const slugMatchesKeyword = (slug, keyword) => {
        const slugRaw = String(slug || "").trim().toLowerCase();
        const kwRaw = String(keyword || "").trim();
        if (!slugRaw) return false;
        if (!kwRaw) return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slugRaw);
        const compact = normalizeVietnameseSeoText(slugRaw.replace(/-/g, " ")).replace(/\s+/g, "");
        const spaced = normalizeVietnameseSeoText(slugRaw.replace(/-/g, " "));
        const tokens = normalizeVietnameseSeoText(kwRaw).split(/\s+/).filter(Boolean);
        if (!tokens.length) return true;
        return tokens.every((t) => compact.includes(t) || spaced.split(/\s+/).includes(t));
    };

    const getSeoFixAction = (factorId) => {
        const fid = String(factorId || "").trim();
        const scope = CAU_FACTOR_FIX_SCOPES[fid] || "content";
        const labels = { title: "Tiêu đề", meta: "Meta description", slug: "Slug", content: "Nội dung" };
        return { factor_id: fid, scope, scope_label: labels[scope] || "Nội dung", mode: "single" };
    };

    const cauReadWorkspace = () => {
        try {
            const raw = localStorage.getItem(CAU_WORKSPACE_KEY());
            const data = raw ? JSON.parse(raw) : null;
            return data && typeof data === "object" ? data : {};
        } catch (_) {
            return {};
        }
    };

    const cauSaveWorkspace = () => {
        const payload = {
            siteId: String(cauState.siteId || ""),
            activeTab: String(cauState.activeTab || "select"),
            postUrl: String(cauState.postUrl || ""),
            keyword: String(cauState.keyword || ""),
            focus: String(cauState.focus || ""),
            scanSearch: String(cauState.scanSearch || ""),
            scanStatus: String(cauState.scanStatus || "all"),
            scanScoreFilter: String(cauState.scanScoreFilter || "all"),
            scanSortScore: String(cauState.scanSortScore || "asc"),
            scanCategoryId: String(cauState.scanCategoryId || ""),
            scanScannedAt: String(cauState.scanScannedAt || ""),
            scanFromCache: !!cauState.scanFromCache,
            scanPosts: (cauState.scanPosts || []).slice(0, 100),
            scanPage: parseInt(cauState.scanPage, 10) || 1,
            scanHasMore: !!cauState.scanHasMore,
            scanQueried: !!cauState.scanQueried,
            sessionId: String(cauState.sessionId || ""),
            fetchedTitle: String(cauState.fetchedTitle || ""),
            updatedAt: new Date().toISOString(),
        };
        try {
            localStorage.setItem(CAU_WORKSPACE_KEY(), JSON.stringify(payload));
        } catch (_) {}
        if (payload.siteId) cauPersistSiteId(payload.siteId);
    };

    const cauRestoreWorkspaceFromStorage = () => {
        const ws = cauReadWorkspace();
        if (!ws || typeof ws !== "object") return;
        if (ws.siteId) cauState.siteId = String(ws.siteId);
        if (ws.activeTab) cauState.activeTab = String(ws.activeTab);
        if (ws.postUrl != null) cauState.postUrl = String(ws.postUrl || "");
        if (ws.keyword != null) cauState.keyword = String(ws.keyword || "");
        if (ws.focus != null) cauState.focus = String(ws.focus || "");
        if (ws.scanSearch != null) cauState.scanSearch = String(ws.scanSearch || "");
        if (ws.scanStatus) cauState.scanStatus = String(ws.scanStatus || "all");
        if (ws.scanScoreFilter) cauState.scanScoreFilter = String(ws.scanScoreFilter || "all");
        if (ws.scanSortScore) cauState.scanSortScore = String(ws.scanSortScore || "asc");
        if (ws.scanScannedAt) cauState.scanScannedAt = String(ws.scanScannedAt || "");
        if (ws.scanFromCache != null) cauState.scanFromCache = !!ws.scanFromCache;
        if (ws.scanCategoryId != null) cauState.scanCategoryId = String(ws.scanCategoryId || "");
        if (Array.isArray(ws.scanPosts)) cauState.scanPosts = ws.scanPosts;
        if (ws.scanPage) cauState.scanPage = parseInt(ws.scanPage, 10) || 1;
        if (ws.scanHasMore != null) cauState.scanHasMore = !!ws.scanHasMore;
        if (ws.scanQueried != null) cauState.scanQueried = !!ws.scanQueried;
        if (ws.sessionId) cauState.sessionId = String(ws.sessionId);
        if (ws.fetchedTitle) cauState.fetchedTitle = String(ws.fetchedTitle);
    };

    const cauRestoreScanFiltersUi = () => {
        const searchEl = byId("cauPostSearch");
        const statusEl = byId("cauPostStatusFilter");
        const scoreEl = byId("cauPostScoreFilter");
        if (searchEl && document.activeElement !== searchEl) {
            searchEl.value = cauState.scanSearch || "";
        }
        if (statusEl && document.activeElement !== statusEl) {
            statusEl.value = cauState.scanStatus || "all";
        }
        if (scoreEl && document.activeElement !== scoreEl) {
            scoreEl.value = cauState.scanScoreFilter || "all";
        }
        const sortIcon = byId("cauSortScoreIcon");
        if (sortIcon) sortIcon.textContent = (cauState.scanSortScore || "asc") === "desc" ? "↓" : "↑";
    };

    const cauFinalizeWorkspaceRestore = () => {
        const ws = cauReadWorkspace();
        if (ws.scanCategoryId != null) cauState.scanCategoryId = String(ws.scanCategoryId || "");
        if (ws.scanSearch != null) cauState.scanSearch = String(ws.scanSearch || "");
        if (ws.scanStatus) cauState.scanStatus = String(ws.scanStatus || "all");
        if (ws.scanScoreFilter) cauState.scanScoreFilter = String(ws.scanScoreFilter || "all");
        if (ws.scanSortScore) cauState.scanSortScore = String(ws.scanSortScore || "asc");
        if (ws.scanScannedAt) cauState.scanScannedAt = String(ws.scanScannedAt || "");
        if (ws.scanFromCache != null) cauState.scanFromCache = !!ws.scanFromCache;
        if (Array.isArray(ws.scanPosts)) cauState.scanPosts = ws.scanPosts;
        if (ws.scanPage) cauState.scanPage = parseInt(ws.scanPage, 10) || 1;
        if (ws.scanHasMore != null) cauState.scanHasMore = !!ws.scanHasMore;
        if (ws.scanQueried != null) {
            cauState.scanQueried = !!ws.scanQueried;
        } else if (Array.isArray(ws.scanPosts) && ws.scanPosts.length) {
            cauState.scanQueried = true;
        }
        if (ws.postUrl != null) cauState.postUrl = String(ws.postUrl || "");
        if (ws.keyword != null) cauState.keyword = String(ws.keyword || "");
        if (ws.focus != null) cauState.focus = String(ws.focus || "");
        if (ws.sessionId) cauState.sessionId = String(ws.sessionId);
        if (ws.fetchedTitle) cauState.fetchedTitle = String(ws.fetchedTitle);
        cauRestoreScanFiltersUi();
        if ((cauState.scanCategories || []).length) cauRenderCategoryFilter();
        cauUpdateScanScopeHint();
        cauUpdateScanCatHint();
        cauRenderScanPosts();
    };

    const cauReadCatHistoryStore = () => {
        try {
            const raw = localStorage.getItem(CAU_CAT_HISTORY_KEY);
            const data = raw ? JSON.parse(raw) : {};
            return data && typeof data === "object" ? data : {};
        } catch (_) {
            return {};
        }
    };

    const cauSaveCatHistoryStore = (store) => {
        try {
            localStorage.setItem(CAU_CAT_HISTORY_KEY, JSON.stringify(store));
        } catch (_) {}
    };

    const cauSaveCatHistory = (siteId, categories, selectedCategoryId) => {
        const sid = String(siteId || "").trim();
        if (!sid) return;
        const store = cauReadCatHistoryStore();
        store[sid] = {
            categories: (categories || []).filter((c) => c && c.id != null),
            selectedCategoryId: String(selectedCategoryId || ""),
            scanSearch: String(cauState.scanSearch || ""),
            scanStatus: String(cauState.scanStatus || "all"),
            updatedAt: new Date().toISOString(),
        };
        cauSaveCatHistoryStore(store);
        cauSaveWorkspace();
    };

    const cauRestoreCatHistoryForSite = (siteId) => {
        const sid = String(siteId || "").trim();
        if (!sid) return false;
        const entry = cauReadCatHistoryStore()[sid];
        if (!entry || !Array.isArray(entry.categories) || !entry.categories.length) return false;
        cauState.scanCategories = entry.categories;
        cauState.scanCategoryId = String(entry.selectedCategoryId || "");
        if (entry.scanSearch != null) cauState.scanSearch = String(entry.scanSearch || "");
        if (entry.scanStatus) cauState.scanStatus = String(entry.scanStatus || "all");
        cauRenderCategoryFilter();
        cauSetStatus(
            "scanCat",
            "ok",
            "Đã khôi phục " + entry.categories.length + " danh mục cấp 1 đã lưu."
        );
        return true;
    };

    const cauUpdateScanCatHint = () => {
        const el = byId("cauScanCatHint");
        if (!el) return;
        const sid = String(
            (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value) ||
            cauState.siteId || ""
        ).trim();
        if (!sid || (!(cauState.scanCategories || []).length && !cauState.loadingCategories)) {
            el.textContent = "Chọn website rồi bấm Tải danh mục.";
            return;
        }
        el.textContent = "";
    };

    const cauOnScanSiteChanged = (siteId) => {
        const sid = String(siteId || "").trim();
        if (!sid) {
            cauResetCategoryFilter({ keepPlaceholder: true });
            cauUpdateScanCatHint();
            return;
        }
        if (!cauRestoreCatHistoryForSite(sid)) {
            cauResetCategoryFilter({ keepPlaceholder: true });
            cauSetStatus("scanCat", "", "");
        }
        cauUpdateScanCatHint();
    };

    const cauNormalizeSiteUrl = (raw) => {
        const s = String(raw || "").trim();
        if (!s) return "";
        try {
            const u = new URL(s.includes("://") ? s : "https://" + s);
            return String(u.origin || "").replace(/\/$/, "").toLowerCase();
        } catch (_) {
            return s.toLowerCase().replace(/\/$/, "");
        }
    };

    const cauFindSiteById = (id) =>
        (cauState.sites || []).find((s) => String(s.id) === String(id || "")) || null;

    const cauFindSiteByUrl = (url) => {
        const key = cauNormalizeSiteUrl(url);
        if (!key) return null;
        return (cauState.sites || []).find((s) => cauNormalizeSiteUrl(s.url) === key) || null;
    };

    const cauApplySiteToForm = (site) => {
        if (!site) return;
        const urlEl = byId("cauSiteUrl");
        const userEl = byId("cauSiteUser");
        const passEl = byId("cauSitePass");
        const labelEl = byId("cauSiteLabel");
        if (urlEl) urlEl.value = String(site.url || "");
        if (labelEl) labelEl.value = String(site.label || site.url || "");
        if (userEl) userEl.value = String(site.username || "");
        if (passEl) passEl.value = "";
    };

    const cauPersistSiteId = (siteId) => {
        const sid = String(siteId || "").trim();
        if (!sid) return;
        try {
            sessionStorage.setItem(CAU_SITE_ID_KEY, sid);
        } catch (_) {}
    };

    const cauReadPersistedSiteId = () => {
        try {
            const fromSession = String(sessionStorage.getItem(CAU_SITE_ID_KEY) || "").trim();
            if (fromSession) return fromSession;
            const ws = cauReadWorkspace();
            return String(ws.siteId || "").trim();
        } catch (_) {
            return "";
        }
    };

    const cauResolveDefaultSiteId = () => {
        const sites = cauState.sites || [];
        if (!sites.length) return "";

        const current = cauFindSiteById(cauState.siteId);
        if (current) return String(current.id);

        const wsSite = cauFindSiteById(cauReadWorkspace().siteId);
        if (wsSite) return String(wsSite.id);

        const saved = cauFindSiteById(cauReadPersistedSiteId());
        if (saved) return String(saved.id);

        const formUrl = byId("cauSiteUrl") && byId("cauSiteUrl").value;
        const byUrl = cauFindSiteByUrl(formUrl);
        if (byUrl) return String(byUrl.id);

        if (sites.length === 1) return String(sites[0].id);
        return "";
    };

    const cauSelectSite = (siteId, opts) => {
        const sid = String(siteId || "").trim();
        cauState.siteId = sid;
        const sel = byId("cauSiteSelect");
        if (sel && sid) sel.value = sid;
        const scanSel = byId("cauScanSiteSelect");
        if (scanSel && sid) scanSel.value = sid;
        const site = cauFindSiteById(sid);
        if (site && !(opts && opts.skipForm)) cauApplySiteToForm(site);
        if (sid) cauPersistSiteId(sid);
        if (!(opts && opts.skipSave)) cauSaveWorkspace();
    };

    const cauState = {
        activeTab: "select",
        loading: null,
        sessionId: "",
        backupId: "",
        siteId: "",
        sites: [],
        post: null,
        fetchedTitle: "",
        postUrl: "",
        seoBefore: null,
        seoAfter: null,
        seoSummary: null,
        seoSummaryAfter: null,
        failedFactorsBefore: [],
        failedItems: [],
        warningItems: [],
        failedAfter: [],
        scoreRegressed: false,
        canPublishLive: false,
        canSaveDraft: false,
        keyword: "",
        focus: "",
        proposal: null,
        warnings: [],
        seoComparison: null,
        publishChecklist: null,
        canPublish: false,
        diff: null,
        historyItems: null,
        previewSummary: null,
        hasProposal: false,
        quota: null,
        scanPosts: [],
        scanPage: 1,
        scanPerPage: 20,
        scanHasMore: false,
        scanQueried: false,
        scanFetchToken: 0,
        scanTypeCounts: {},
        scanSearch: "",
        scanStatus: "all",
        scanScoreFilter: "all",
        scanSortScore: "asc",
        scanFromCache: false,
        scanScannedAt: "",
        scanLastRefresh: false,
        scanCategoryId: "",
        scanCategories: [],
        scanCategoriesLoading: false,
        loadingCategories: false,
        loadingPosts: false,
        status: {
            connect: "",
            connectType: "",
            fetch: "",
            fetchType: "",
            ai: "",
            aiType: "",
            backup: "",
            backupType: "",
            publish: "",
            publishType: "",
            history: "",
            historyType: "",
            scan: "",
            scanType: "",
            scanCat: "",
            scanCatType: "",
        },
    };

    const cauFormatApiError = (err, context) => {
        const raw = String((err && err.message) || err || "").trim();
        if (context === "fix") {
            return raw || "Không sửa được yếu tố SEO.";
        }
        const lower = raw.toLowerCase();
        if (
            lower.includes("401") || lower.includes("403") ||
            lower.includes("application password") || lower.includes("rest_forbidden") ||
            lower.includes("không có quyền") || lower.includes("unauthorized")
        ) {
            return "Không có quyền truy cập WordPress REST API. Kiểm tra Application Password và quyền tài khoản.";
        }
        if (
            lower.includes("502") || lower.includes("wordpress") ||
            lower.includes("không gọi được") || lower.includes("không kết nối") ||
            lower.includes("không trả") || lower.includes("không lấy được bài") ||
            lower.includes("rest api")
        ) {
            return raw || "Lỗi kết nối WordPress — thử quét theo danh mục hoặc kiểm tra Application Password.";
        }
        if (raw === "Không thể xử lý yêu cầu. Vui lòng thử lại sau." || (err && err.status === 502)) {
            return "Lỗi kết nối WordPress khi quét bài. Thử «Tải danh mục» rồi quét theo 1 danh mục, hoặc kiểm tra Application Password.";
        }
        if (context === "update") {
            return "Cập nhật thất bại — bản nháp trong modal vẫn được giữ. " + (raw || "");
        }
        return raw || "Lỗi không xác định.";
    };

    const cauApi = (method, path, body) => {
        const opts = { method, credentials: "same-origin", headers: authJsonHeaders() };
        if (body) opts.body = JSON.stringify(body);
        return apiFetch(path, opts).then(async (res) => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const d = data.detail;
                let msg = "Lỗi API";
                if (res.status === 499) {
                    msg = "Antivirus/web shield đã chặn phản hồi HTML từ WordPress. Tạm tắt quét HTTPS cho localhost rồi thử lại.";
                } else if (typeof d === "object" && d) {
                    msg = d.message || (Array.isArray(d.blockers) ? d.blockers.join("; ") : JSON.stringify(d));
                } else if (d) {
                    msg = String(d);
                }
                const err = new Error(msg);
                err.status = res.status;
                err.detail = d;
                throw err;
            }
            if (window.SeoautoAwaitQueued && data && data.job_id && data.poll_url) {
                return window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            return data;
        });
    };

    const cauDecodeHtmlField = (obj, field) => {
        if (!obj || typeof obj !== "object") return "";
        const enc = String(obj[field + "_encoding"] || obj.content_encoding || "");
        const b64 = obj[field + "_b64"] || (field === "content" ? obj.content_b64 : "");
        if ((enc === "utf8_b64" || enc === "b64") && b64) {
            try {
                const bin = atob(String(b64));
                if (typeof TextDecoder !== "undefined") {
                    const bytes = new Uint8Array(bin.length);
                    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                    return new TextDecoder("utf-8").decode(bytes);
                }
                return decodeURIComponent(escape(bin));
            } catch (_) {
                return String(obj[field] || "");
            }
        }
        return String(obj[field] || "");
    };

    const cauEsc = (s) => String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    const cauValidateUrl = (url, label) => {
        const u = String(url || "").trim();
        if (!u) return (label || "URL") + " không được để trống.";
        try {
            const p = new URL(u);
            if (!/^https?:$/i.test(p.protocol)) return (label || "URL") + " phải dùng http hoặc https.";
            if (!p.host) return (label || "URL") + " không hợp lệ.";
        } catch (_) {
            return (label || "URL") + " không hợp lệ.";
        }
        return "";
    };

    const cauValidateConnectForm = () => {
        const urlErr = cauValidateUrl(byId("cauSiteUrl") && byId("cauSiteUrl").value, "URL site");
        if (urlErr) return urlErr;
        const user = (byId("cauSiteUser") && byId("cauSiteUser").value.trim()) || "";
        const pass = (byId("cauSitePass") && byId("cauSitePass").value) || "";
        if (!user) return "Username không được để trống.";
        if (!pass || pass.length < 4) return "Application Password phải có ít nhất 4 ký tự.";
        return "";
    };

    const cauValidateSiteSelected = () => {
        const siteId = (byId("cauSiteSelect") && byId("cauSiteSelect").value) || cauState.siteId;
        if (!siteId) return "Chọn site WordPress đã lưu hoặc kết nối site mới.";
        return "";
    };

    const cauPersistFormToState = () => {
        cauState.keyword = (byId("cauKeyword") && byId("cauKeyword").value.trim()) || "";
        cauState.focus = (byId("cauFocus") && byId("cauFocus").value.trim()) || "";
        cauState.postUrl = (byId("cauPostUrl") && byId("cauPostUrl").value.trim()) || cauState.postUrl;
        const sid = (byId("cauSiteSelect") && byId("cauSiteSelect").value) || "";
        if (sid) cauState.siteId = sid;
        cauSaveWorkspace();
    };

    const cauSetStatus = (scope, type, msg) => {
        const key = scope === "connect" ? "connect" : scope;
        if (cauState.status[key] !== undefined) {
            cauState.status[key] = msg || "";
            cauState.status[key + "Type"] = type || "";
        }
        const hintMap = {
            connect: "cauConnectHint",
            fetch: "cauFetchHint",
            ai: "cauAiSummary",
            backup: "cauBackupInfo",
            publish: "cauPublishResult",
            history: "cauPublishResult",
            scan: "cauScanHint",
            scanCat: "cauScanCatHint",
        };
        const el = byId(hintMap[key] || key);
        if (!el) return;
        el.textContent = msg || "";
        el.classList.remove("cau-hint--ok", "cau-hint--err", "cau-hint--loading");
        if (type === "ok") el.classList.add("cau-hint--ok");
        else if (type === "err") el.classList.add("cau-hint--err");
        else if (type === "loading") el.classList.add("cau-hint--loading");
    };

    const cauBeginLoad = (action) => {
        cauState.loading = action;
        const ids = CAU_ACTION_BUTTONS[action] || [];
        ids.forEach((id) => {
            const btn = byId(id);
            if (!btn) return;
            if (!btn.dataset.cauOrigText) btn.dataset.cauOrigText = btn.textContent;
            btn.classList.add("cau-btn-loading");
            btn.disabled = true;
            btn.setAttribute("aria-busy", "true");
            btn.textContent = CAU_LOAD_LABELS[action] || "Đang xử lý…";
        });
    };

    const cauEndLoad = (action) => {
        const act = action || cauState.loading;
        if (act) {
            (CAU_ACTION_BUTTONS[act] || []).forEach((id) => {
                const btn = byId(id);
                if (!btn) return;
                btn.classList.remove("cau-btn-loading");
                btn.removeAttribute("aria-busy");
                if (btn.dataset.cauOrigText) btn.textContent = btn.dataset.cauOrigText;
                // Publish buttons keep their own enable rules via cauSetPublishButtons.
                if (id !== "btnCauSaveDraft" && id !== "btnCauPublishLive") {
                    btn.disabled = false;
                }
            });
        }
        if (!action || cauState.loading === action) cauState.loading = null;
        cauSetPublishButtons({ draft: cauState.canSaveDraft, live: cauState.canPublishLive });
    };

    const cauWithLoad = (action, scope, fn) => {
        if (cauState.loading) return Promise.resolve();
        cauBeginLoad(action);
        if (scope) cauSetStatus(scope, "loading", "Đang xử lý…");
        return Promise.resolve()
            .then(fn)
            .catch((e) => {
                if (scope) cauSetStatus(scope, "err", e.message || "Lỗi không xác định.");
                throw e;
            })
            .finally(() => cauEndLoad(action));
    };

    const cauSetPublishButtons = (opts) => {
        const o = typeof opts === "boolean" ? { draft: opts, live: opts } : (opts || {});
        cauState.canSaveDraft = !!o.draft;
        cauState.canPublishLive = !!o.live;
        cauState.canPublish = cauState.canPublishLive;
        if (cauState.loading === "publishDraft" || cauState.loading === "publishLive") return;
        const draftBtn = byId("btnCauSaveDraft");
        const liveBtn = byId("btnCauPublishLive");
        const draftReason = o.draftReason || (cauState.publishChecklist && cauState.publishChecklist.draft_block_reasons) || [];
        const liveReason = o.liveReason || (cauState.publishChecklist && cauState.publishChecklist.live_block_reasons) || [];
        if (draftBtn) {
            draftBtn.disabled = !cauState.canSaveDraft;
            draftBtn.title = cauState.canSaveDraft ? "Lưu nháp lên WordPress" : (draftReason.join("; ") || "Cần backup + nội dung mới");
        }
        if (liveBtn) {
            liveBtn.disabled = !cauState.canPublishLive;
            liveBtn.title = cauState.canPublishLive ? "Publish live lên WordPress" : (liveReason.join("; ") || "Chưa đủ điều kiện publish live");
        }
    };

    const cauQuotaBlocked = (featureKey) => {
        const q = cauState.quota;
        if (!q || q.bypass_entitlement) return false;
        const row = (q.items || []).find((i) => i.feature_key === featureKey);
        return !!(row && row.is_over_quota);
    };

    const cauAiFixSnapshot = () => (cauState.quota && cauState.quota.ai_fix) || null;

    const cauAiFixBlocked = () => {
        const snap = cauAiFixSnapshot();
        if (!snap) return false;
        return !snap.allowed;
    };

    const cauAiFixBlockMessage = () => {
        const snap = cauAiFixSnapshot();
        return (snap && snap.message) || "Tính năng AI Fix SEO chỉ dành cho gói Basic trở lên.";
    };

    const cauAiFixCreditHint = () => {
        const snap = cauAiFixSnapshot();
        if (!snap || !snap.allowed) return "";
        const cost = snap.credit_cost != null ? snap.credit_cost : 0;
        const bal = snap.credit_balance != null ? snap.credit_balance : "—";
        if (!cost) return "";
        return " (mỗi lần sửa AI: " + cost + " credit, còn " + bal + ")";
    };

    const cauRenderQuotaBanner = () => {
        const el = byId("cauQuotaBanner");
        if (!el) return;
        const q = cauState.quota;
        if (!q || q.bypass_entitlement) {
            el.hidden = true;
            return;
        }
        const over = (q.items || []).filter((i) => i.is_over_quota);
        if (!over.length) {
            el.hidden = true;
            return;
        }
        el.hidden = false;
        el.textContent = "Đã hết quota tháng: " + over.map((i) => i.label || i.feature_key).join(", ") + ". Vui lòng nâng cấp gói.";
    };

    const cauLoadQuota = () =>
        cauApi("GET", "/content-ai/auto-update/quota").then((data) => {
            cauState.quota = data;
            cauRenderQuotaBanner();
        }).catch(() => {});

    const cauFormatDate = (iso) => {
        const s = String(iso || "").trim();
        if (!s) return "—";
        const d = new Date(s);
        if (Number.isNaN(d.getTime())) return s.slice(0, 10);
        return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
    };

    const cauStatusBadgeClass = (status) => {
        const st = String(status || "").toLowerCase();
        if (st === "publish") return "cau-status-badge--publish";
        if (st === "draft") return "cau-status-badge--draft";
        if (st === "private") return "cau-status-badge--private";
        return "cau-status-badge--other";
    };

    const cauStatusBadgeLabel = (status) => {
        const st = String(status || "").toLowerCase();
        if (st === "publish") return "Published";
        if (st === "draft") return "Draft";
        if (st === "private") return "Private";
        return st || "—";
    };

    const cauStatusLabel = (status) => {
        const st = String(status || "").toLowerCase();
        if (st === "publish") return "Đã xuất bản";
        if (st === "draft") return "Nháp";
        if (st === "private") return "Riêng tư";
        return st || "—";
    };

    const cauFindScopeItem = (value) => {
        const key = String(value || "").trim();
        if (!key) return null;
        return (cauState.scanCategories || []).find((c) => cauFilterOptionValue(c) === key) || null;
    };

    const cauScopeDisplayName = (item) => {
        if (!item) return "";
        return String(item.name || item.slug || "—").replace(/\s*\(\d+\)\s*$/, "").trim();
    };

    const cauUpdateScanScopeHint = () => {
        const el = byId("cauScanScopeHint");
        if (!el) return;
        el.hidden = true;
        el.textContent = "";
    };

    const cauSetScanLoading = (on, msg) => {
        const box = byId("cauScanLoading");
        const text = byId("cauScanLoadingText");
        if (box) {
            if (on) {
                box.removeAttribute("hidden");
            } else {
                box.setAttribute("hidden", "");
            }
        }
        if (text) text.textContent = msg || "Đang quét bài viết…";
    };

    const cauResetCategoryFilter = (opts) => {
        const keepPlaceholder = !!(opts && opts.keepPlaceholder);
        cauState.scanCategoryId = "";
        cauState.scanCategories = [];
        const catSel = byId("cauPostCategoryFilter");
        if (!catSel) return;
        catSel.innerHTML = keepPlaceholder
            ? '<option value="">Chọn website rồi bấm Tải danh mục.</option>'
            : '<option value="">Toàn bộ website</option>';
        catSel.value = "";
        catSel.disabled = true;
        cauUpdateScanScopeHint();
        cauUpdateScanCatHint();
    };

    const cauFilterOptionValue = (item) => {
        if (!item || item.id == null || item.id === "") return "";
        return "category:" + String(item.id);
    };

    const cauFilterOptionLabel = (item) => {
        const name = cauEsc(item.name || "—");
        const count = item.count != null ? parseInt(item.count, 10) : 0;
        return name + " (" + (count || 0) + ")";
    };

    const cauRenderCategoryFilter = () => {
        const catSel = byId("cauPostCategoryFilter");
        if (!catSel) return;
        const cats = (cauState.scanCategories || []).filter((c) => c && c.id != null);
        const opts = ['<option value="">Toàn bộ website</option>'];
        cats.forEach((c) => {
            const value = cauFilterOptionValue(c);
            opts.push('<option value="' + cauEsc(value) + '">' + cauFilterOptionLabel(c) + "</option>");
        });
        catSel.innerHTML = opts.join("");
        catSel.disabled = false;
        const saved = String(cauState.scanCategoryId || "");
        if (saved && Array.from(catSel.options).some((o) => o.value === saved)) {
            catSel.value = saved;
        } else {
            catSel.value = "";
            cauState.scanCategoryId = "";
        }
        cauUpdateScanScopeHint();
        cauUpdateScanCatHint();
    };

    const cauSelectedCategoryName = () => {
        const item = cauFindScopeItem(cauState.scanCategoryId);
        if (!item) return "";
        return String(item.name || "").replace(/\s*\(\d+\)\s*$/, "").trim();
    };

    const cauScanEmptyMessage = () => {
        if (cauState.loadingPosts) {
            return "Đang quét bài viết từ WordPress…";
        }
        if (!cauState.scanQueried) {
            return "Chọn website, tải danh mục — hệ thống sẽ tự tải dữ liệu đã lưu.";
        }
        if (cauState.scanLastRefresh) {
            if (cauState.scanCategoryId) {
                return "Không tìm thấy bài viết trong danh mục đã chọn.";
            }
            return "Không tìm thấy bài viết phù hợp với bộ lọc hiện tại.";
        }
        if (cauState.scanCategoryId) {
            return "Chưa có dữ liệu đã lưu cho danh mục này — bấm Quét bài viết hoặc Làm mới dữ liệu.";
        }
        return "Chưa có dữ liệu đã lưu — bấm Quét bài viết hoặc Làm mới dữ liệu.";
    };

    const cauSanitizeScanSearch = (search, hasCategory) => {
        const q = String(search || "").trim();
        if (!q) return "";
        if (!hasCategory && /^https?:\/\//i.test(q)) return "";
        if (!hasCategory && /^www\./i.test(q)) return "";
        return q;
    };

    const cauTypeLabel = (type, restBase) => {
        const slug = String(type || restBase || "post").toLowerCase();
        const base = String(restBase || type || "").toLowerCase();
        if (slug === "post" || slug === "posts" || base === "posts") return "Bài viết";
        if (slug === "page" || slug === "pages" || base === "pages") return "Trang";
        return "Dịch vụ";
    };

    const cauSummarizeTypeCounts = (typeCounts) => {
        const tc = typeCounts || {};
        let posts = 0;
        let pages = 0;
        let services = 0;
        Object.keys(tc).forEach((key) => {
            const n = parseInt(tc[key], 10) || 0;
            const k = String(key || "").toLowerCase();
            if (k === "posts" || k === "post") posts += n;
            else if (k === "pages" || k === "page") pages += n;
            else services += n;
        });
        return { posts, pages, services };
    };

    const cauFormatTypeCountsMessage = (total, typeCounts) => {
        const n = parseInt(total, 10) || 0;
        const sums = cauSummarizeTypeCounts(typeCounts);
        const parts = [];
        if (sums.posts) parts.push(sums.posts + " bài viết");
        if (sums.pages) parts.push(sums.pages + " trang");
        if (sums.services) parts.push(sums.services + " dịch vụ");
        if (!parts.length) return "Đang hiển thị " + n + " nội dung";
        return "Đang hiển thị " + n + " nội dung (" + parts.join(", ") + ")";
    };

    const cauPostScoreValue = (post) => {
        const raw = post && (post.seo_score != null ? post.seo_score : post.score);
        if (raw == null || raw === "") return null;
        const n = parseInt(raw, 10);
        return Number.isFinite(n) ? n : null;
    };

    const cauPostScoreLevel = (post) => {
        const level = post && post.score_level;
        if (level) return String(level);
        const score = cauPostScoreValue(post);
        if (score == null) return "unscored";
        if (score < 20) return "very_weak";
        if (score < 50) return "urgent";
        if (score < 80) return "optimize";
        return "good";
    };

    const cauScoreBandClass = (score) => {
        if (score == null) return "cau-seo-score--unscored";
        const n = parseInt(score, 10);
        if (n < 20) return "cau-seo-score--critical";
        if (n < 50) return "cau-seo-score--urgent";
        if (n < 80) return "cau-seo-score--optimize";
        return "cau-seo-score--good";
    };

    const cauPriorityLabel = (post) => String((post && post.priority) || "Trung bình");

    const cauPriorityClass = (post) => {
        const label = cauPriorityLabel(post);
        if (label === "Rất cao") return "cau-priority--very-high";
        if (label === "Cao") return "cau-priority--high";
        if (label === "Thấp") return "cau-priority--low";
        return "cau-priority--medium";
    };

    const cauSeoScoreActionText = (post) => {
        const score = cauPostScoreValue(post);
        if (score == null) return "Chưa chấm điểm";
        return "Điểm seo " + score + "/100";
    };

    const cauEditSeoButtonLabel = () => "Sửa SEO";

    const cauFormatScannedAt = (iso) => {
        if (!iso) return "";
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return "";
        const pad = (n) => String(n).padStart(2, "0");
        return pad(d.getHours()) + ":" + pad(d.getMinutes()) + " " +
            pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + "/" + d.getFullYear();
    };

    const cauUpdateScanCacheHint = () => {
        const el = byId("cauScanCacheHint");
        if (!el) return;
        if (!cauState.scanFromCache || !cauState.scanScannedAt) {
            el.hidden = true;
            el.textContent = "";
            return;
        }
        const when = cauFormatScannedAt(cauState.scanScannedAt);
        el.hidden = false;
        el.textContent = when
            ? "Đang dùng dữ liệu đã lưu lúc " + when
            : "Đang dùng dữ liệu đã lưu";
    };

    const cauFilterScanPosts = (posts) => {
        const filter = String(cauState.scanScoreFilter || "all");
        if (filter === "all") return posts.slice();
        return (posts || []).filter((p) => {
            const level = cauPostScoreLevel(p);
            if (filter === "unscored") return cauPostScoreValue(p) == null;
            return level === filter;
        });
    };

    const cauSortScanPosts = (posts) => {
        const dir = String(cauState.scanSortScore || "asc");
        const rows = posts.slice();
        rows.sort((a, b) => {
            const sa = cauPostScoreValue(a);
            const sb = cauPostScoreValue(b);
            const va = sa == null ? 9999 : sa;
            const vb = sb == null ? 9999 : sb;
            if (va === vb) {
                return String(a.title || "").localeCompare(String(b.title || ""), "vi");
            }
            return dir === "desc" ? (vb - va) : (va - vb);
        });
        return rows;
    };

    const cauGetDisplayScanPosts = () =>
        cauSortScanPosts(cauFilterScanPosts(cauState.scanPosts || []));

    const cauUpsertScanScore = (post, score) => {
        const siteId = cauState.siteId || (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value);
        const postId = parseInt((post && (post.post_id || post.id)) || 0, 10);
        if (!siteId || !postId || score == null) return Promise.resolve();
        const payload = {
            site_id: siteId,
            post_id: postId,
            post_type: String((post && (post.post_type || post.type)) || "post"),
            url: String((post && (post.url || post.link)) || ""),
            slug: String((post && post.slug) || ""),
            title: String((post && post.title) || ""),
            status: String((post && post.status) || ""),
            modified: String((post && post.modified) || ""),
            seo_score: parseInt(score, 10),
        };
        return cauApi("POST", "/content-ai/auto-update/scan-cache/score", payload)
            .then((data) => {
                cauUpdatePostScoreInList(postId, payload.post_type, data);
            })
            .catch(() => {});
    };

    const cauUpdatePostScoreInList = (postId, postType, data) => {
        const score = parseInt((data && (data.post_score && data.post_score.seo_score)) || data.seo_score, 10);
        if (!Number.isFinite(score)) return;
        const level = (data && data.score_level) || cauPostScoreLevel({ seo_score: score });
        const priority = (data && data.priority) || "";
        (cauState.scanPosts || []).forEach((p) => {
            const pid = parseInt(p.post_id || p.id, 10);
            const ptype = String(p.post_type || p.type || "post");
            if (pid === parseInt(postId, 10) && ptype === String(postType || "post")) {
                p.seo_score = score;
                p.score_level = level;
                p.priority = priority || (score < 50 ? "Rất cao" : (score < 80 ? "Cao" : "Thấp"));
            }
        });
        cauRenderScanPosts();
        cauSaveWorkspace();
    };

    const cauScanResultMessage = (count, typeCounts) => {
        const n = parseInt(count, 10) || 0;
        const catName = cauSelectedCategoryName();
        const tc = typeCounts || cauState.scanTypeCounts || {};
        if (cauState.scanCategoryId && catName) {
            return "Đang hiển thị " + n + " bài viết trong danh mục: " + catName;
        }
        return cauFormatTypeCountsMessage(n, tc);
    };

    const cauAutoScanPosts = () => {
        const siteId = cauState.siteId || (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value);
        if (!siteId) return Promise.resolve();
        if (!(cauState.scanCategories || []).length) return Promise.resolve();
        if (cauState.loadingPosts) return Promise.resolve();
        cauSetScanLoading(true, "Đang tải dữ liệu đã lưu…");
        return cauFetchScanPosts({ append: false, refresh: false, silent: true });
    };

    const cauLoadScanCategories = (siteId) => {
        const sid = String(siteId || "").trim() ||
            (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value) ||
            cauState.siteId || "";
        if (!sid) {
            cauSetStatus("scanCat", "err", "Vui lòng chọn website trước khi tải danh mục.");
            return Promise.resolve();
        }
        if (cauState.loadingCategories) return Promise.resolve();

        cauState.siteId = sid;
        const scanSel = byId("cauScanSiteSelect");
        if (scanSel) scanSel.value = sid;
        cauSelectSite(sid, { skipForm: true });

        const catSel = byId("cauPostCategoryFilter");
        if (catSel) {
            catSel.disabled = true;
            catSel.innerHTML = '<option value="">Đang tải danh mục…</option>';
        }

        cauState.scanCategoriesLoading = true;
        cauState.loadingCategories = true;
        cauBeginLoad("scanCats");
        cauSetStatus("scanCat", "loading", CAU_LOAD_LABELS.scanCats);

        return cauApi("GET", "/content-ai/auto-update/categories?site_id=" + encodeURIComponent(sid))
            .then((data) => {
                cauState.scanCategories = (data.categories || data.items || [])
                    .filter((c) => c && c.id != null);
                cauRenderCategoryFilter();
                const n = cauState.scanCategories.length;
                cauSaveCatHistory(sid, cauState.scanCategories, cauState.scanCategoryId);
                if (n) {
                    cauSetStatus("scanCat", "ok", "Đã tải " + n + " danh mục cấp 1.");
                } else {
                    cauSetStatus("scanCat", "", "Không tìm thấy danh mục cấp 1.");
                }
                cauUpdateScanScopeHint();
                cauUpdateScanCatHint();
                return cauAutoScanPosts();
            })
            .catch((e) => {
                cauState.scanCategories = [];
                cauResetCategoryFilter({ keepPlaceholder: true });
                cauSetStatus("scanCat", "err", cauFormatApiError(e, "categories"));
            })
            .finally(() => {
                cauState.scanCategoriesLoading = false;
                cauState.loadingCategories = false;
                cauEndLoad("scanCats");
            });
    };

    const cauScanCategories = () => cauLoadScanCategories();

    const cauRenderScanPosts = () => {
        const wrap = byId("cauPostsTableWrap");
        const body = byId("cauPostsTableBody");
        const footer = byId("cauScanFooter");
        const meta = byId("cauScanMeta");
        const emptyEl = byId("cauScanEmpty");
        const allPosts = cauState.scanPosts || [];
        const posts = cauGetDisplayScanPosts();
        cauUpdateScanCacheHint();
        if (!body) return;
        if (!allPosts.length) {
            if (wrap) wrap.hidden = true;
            if (footer) footer.hidden = true;
            body.innerHTML = "";
            if (meta) meta.textContent = "";
            if (emptyEl) {
                emptyEl.hidden = false;
                emptyEl.textContent = cauScanEmptyMessage();
            }
            return;
        }
        if (!posts.length) {
            if (wrap) wrap.hidden = true;
            if (footer) footer.hidden = true;
            body.innerHTML = "";
            if (emptyEl) {
                emptyEl.hidden = false;
                emptyEl.textContent = "Không có bài phù hợp bộ lọc điểm SEO.";
            }
            if (meta) meta.textContent = cauScanResultMessage(0, cauState.scanTypeCounts);
            return;
        }
        if (emptyEl) emptyEl.hidden = true;
        if (wrap) wrap.hidden = false;
        if (footer) footer.hidden = false;
        body.innerHTML = posts.map((p, idx) => {
            const url = p.url || p.link || "";
            const st = p.status || "";
            const typeLabel = cauTypeLabel(p.type || p.post_type, p.rest_base);
            const score = cauPostScoreValue(p);
            const scoreClass = cauScoreBandClass(score);
            const weakWarn = score != null && score < 20
                ? ' title="Bài quá yếu, nên viết lại hoặc tối ưu lớn."'
                : "";
            const scoreLine = cauSeoScoreActionText(p);
            return (
                "<tr>" +
                '<td class="cau-col-stt">' + (idx + 1) + "</td>" +
                '<td><div class="cau-post-title">' + cauEsc(p.title || "—") + "</div></td>" +
                '<td class="cau-col-type">' + cauEsc(typeLabel) + "</td>" +
                '<td class="cau-col-url">' +
                (url
                    ? '<a class="cau-post-link" href="' + cauEsc(url) + '" target="_blank" rel="noopener">' + cauEsc(url) + "</a>"
                    : "—") +
                "</td>" +
                '<td class="cau-col-status"><span class="cau-status-badge ' + cauStatusBadgeClass(st) + '">' +
                cauEsc(cauStatusBadgeLabel(st)) + "</span></td>" +
                '<td class="cau-col-date">' + cauEsc(cauFormatDate(p.modified || p.date)) + "</td>" +
                '<td class="cau-col-action"><div class="cau-action-cell"' + weakWarn + ">" +
                '<div class="cau-action-score ' + scoreClass + '">' + cauEsc(scoreLine) + "</div>" +
                '<button type="button" class="cau-btn-edit-seo ' + scoreClass + '" data-cau-edit-seo="' +
                cauEsc(String(p.post_id || p.id || "")) + '">' + cauEsc(cauEditSeoButtonLabel()) + "</button></div></td>" +
                "</tr>"
            );
        }).join("");
        body.querySelectorAll("[data-cau-edit-seo]").forEach((btn) => {
            btn.addEventListener("click", (ev) => {
                if (ev && typeof ev.preventDefault === "function") ev.preventDefault();
                if (ev && typeof ev.stopPropagation === "function") ev.stopPropagation();
                const pid = btn.getAttribute("data-cau-edit-seo");
                const post = allPosts.find((x) => String(x.post_id || x.id) === String(pid));
                if (post) cauEditSeoFromPost(post);
            });
        });
        const loadBtn = byId("btnCauLoadMorePosts");
        if (loadBtn) loadBtn.hidden = !cauState.scanHasMore;
        if (meta) {
            const filterNote = String(cauState.scanScoreFilter || "all") !== "all"
                ? " · lọc " + posts.length + "/" + allPosts.length
                : "";
            meta.textContent = cauScanResultMessage(allPosts.length, cauState.scanTypeCounts) + filterNote;
        }
    };

    const cauSyncScanSiteSelect = () => {
        const scanSel = byId("cauScanSiteSelect");
        const mainSel = byId("cauSiteSelect");
        if (!scanSel) return;
        scanSel.innerHTML = '<option value="">— Chọn website —</option>' +
            (cauState.sites || []).map((s) => (
                '<option value="' + s.id + '">' + cauEsc(s.label || s.url) + "</option>"
            )).join("");
        const sid = (mainSel && mainSel.value) || cauState.siteId || "";
        if (sid) scanSel.value = sid;
        if (sid) cauOnScanSiteChanged(sid);
    };

    const cauPersistScanFilters = () => {
        cauState.scanSearch = (byId("cauPostSearch") && byId("cauPostSearch").value.trim()) || "";
        cauState.scanStatus = (byId("cauPostStatusFilter") && byId("cauPostStatusFilter").value) || "all";
        cauState.scanScoreFilter = (byId("cauPostScoreFilter") && byId("cauPostScoreFilter").value) || "all";
        cauState.scanCategoryId = (byId("cauPostCategoryFilter") && byId("cauPostCategoryFilter").value) || "";
        const scanSid = (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value) || "";
        if (scanSid) {
            cauState.siteId = scanSid;
            cauSelectSite(scanSid, { skipForm: true, skipSave: true });
        }
        cauSaveWorkspace();
    };

    const cauFetchScanPosts = (opts) => {
        const append = !!(opts && opts.append);
        const refresh = !!(opts && opts.refresh);
        const silent = !!(opts && opts.silent);
        const page = append ? (cauState.scanPage + 1) : 1;
        cauPersistScanFilters();
        const siteId = cauState.siteId || (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value);
        if (!siteId) {
            cauSetStatus("scan", "err", "Chọn website WordPress trước khi quét.");
            return Promise.resolve();
        }
        if (cauState.loadingPosts && append) return Promise.resolve();

        const hasCategory = !!String(cauState.scanCategoryId || "").trim();
        const useFetchAll = !append;
        const scanSearch = cauSanitizeScanSearch(cauState.scanSearch, hasCategory);
        const params = new URLSearchParams({
            site_id: siteId,
            page: String(page),
            per_page: String(useFetchAll ? 100 : (cauState.scanPerPage || 20)),
            search: scanSearch,
            status: cauState.scanStatus || "all",
        });
        if (hasCategory) {
            params.set("category_id", cauState.scanCategoryId);
        }
        if (useFetchAll) {
            params.set("fetch_all", "1");
            params.set("refresh", refresh ? "true" : "false");
        }

        const loadKey = append
            ? "loadMore"
            : ((opts && opts.loadKey) || (refresh ? "scanRefresh" : (silent ? "" : "scan")));
        const fetchToken = ++cauState.scanFetchToken;
        cauState.loadingPosts = true;
        if (!append && loadKey) cauBeginLoad(loadKey);
        const loadingMsg = refresh
            ? (hasCategory ? "Đang quét bài viết theo danh mục…" : "Đang quét toàn bộ website…")
            : (silent ? "Đang tải dữ liệu đã lưu…" : CAU_LOAD_LABELS.scan);
        cauSetScanLoading(true, append ? CAU_LOAD_LABELS.loadMore : loadingMsg);
        if (!append) cauRenderScanPosts();

        return cauApi("GET", "/content-ai/auto-update/posts?" + params.toString())
            .then((data) => {
                if (fetchToken !== cauState.scanFetchToken) return;
                const rows = data.posts || [];
                if (!append) cauState.scanQueried = true;
                cauState.scanPage = data.page || page;
                cauState.scanHasMore = !!data.has_more;
                cauState.scanTypeCounts = data.type_counts || {};
                cauState.scanFromCache = !!data.from_cache;
                cauState.scanScannedAt = data.scanned_at || "";
                cauState.scanLastRefresh = refresh && !data.from_cache;
                cauState.scanPosts = append ? (cauState.scanPosts || []).concat(rows) : rows;
                if (data.type_counts) {
                    console.debug("[CAU] scan type_counts:", data.type_counts);
                }
                if (!rows.length) {
                    cauSetStatus("scan", refresh ? "err" : "", cauScanEmptyMessage());
                } else if (data.from_cache) {
                    cauSetStatus("scan", "ok", cauScanResultMessage(cauState.scanPosts.length, cauState.scanTypeCounts));
                } else {
                    cauSetStatus("scan", "ok", "Đã quét " + cauState.scanPosts.length + " nội dung từ WordPress.");
                }
                cauRenderScanPosts();
                cauSaveWorkspace();
            })
            .catch((e) => {
                if (fetchToken !== cauState.scanFetchToken) return;
                if (!append) {
                    cauState.scanQueried = true;
                    cauState.scanLastRefresh = refresh;
                    cauState.scanPosts = [];
                    cauRenderScanPosts();
                }
                cauSetStatus("scan", "err", cauFormatApiError(e, "scan"));
            })
            .finally(() => {
                cauState.loadingPosts = false;
                cauSetScanLoading(false);
                if (fetchToken === cauState.scanFetchToken) {
                    if (loadKey) cauEndLoad(loadKey);
                    cauEndLoad("scan");
                    cauEndLoad("scanRefresh");
                }
            });
    };

    const cauScanPosts = () => {
        const siteId = cauState.siteId || (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value);
        if (!siteId) {
            cauSetStatus("scan", "err", "Chọn website WordPress trước khi quét.");
            return Promise.resolve();
        }
        cauEndLoad("scan");
        cauEndLoad("scanRefresh");
        cauState.scanPosts = [];
        cauState.scanPage = 1;
        cauState.scanHasMore = false;
        cauState.scanTypeCounts = {};
        cauState.scanFromCache = false;
        cauState.scanScannedAt = "";
        cauState.scanLastRefresh = false;
        cauState.scanQueried = false;
        return cauFetchScanPosts({ append: false, refresh: true, loadKey: "scan" });
    };

    const cauRefreshScanPosts = () => {
        cauEndLoad("scan");
        cauEndLoad("scanRefresh");
        cauState.scanPosts = [];
        cauState.scanPage = 1;
        cauState.scanHasMore = false;
        cauState.scanTypeCounts = {};
        cauState.scanFromCache = false;
        cauState.scanScannedAt = "";
        cauState.scanLastRefresh = false;
        cauState.scanQueried = false;
        return cauFetchScanPosts({ append: false, refresh: true, loadKey: "scanRefresh" });
    };

    const cauLoadMorePosts = () => {
        if (!cauState.scanHasMore) return Promise.resolve();
        return cauFetchScanPosts({ append: true });
    };

    const cauModalState = {
        open: false,
        loadingPost: false,
        aiLoading: false,
        updateLoading: false,
        sessionId: "",
        backupId: "",
        siteId: "",
        postUrl: "",
        postStatus: "",
        postId: 0,
        postType: "post",
        pendingProposal: null,
        suggestions: [],
        groupedSuggestions: [],
        internalLinkSuggestions: [],
        ilCandidates: [],
        imageResults: [],
        editorTab: "content",
        seoFactors: [],
        originalContent: "",
        wpModified: "",
        htmlSourceSyncing: false,
        pendingFix: null,
        fixingFactorIds: {},
        lastSeo: null,
    };

    const cauPickWpModified = (post) => String((post && (post.modified_gmt || post.modified)) || "");

    const CAU_FIX_STATUS_LABELS = {
        fixed: "Đã sửa",
        no_change: "Không cần sửa",
        failed: "Không sửa được",
    };

    const CAU_HISTORY_ACTION_LABELS = {
        seo_ai_fix: "Sửa SEO AI",
        modal_update: "Cập nhật modal",
        publish: "Publish",
        draft: "Lưu nháp",
        restore: "Khôi phục",
    };

    const CAU_SUGGEST_GROUP_DEFS = [
        { key: "titleMeta", label: "Title / Meta" },
        { key: "heading", label: "Heading" },
        { key: "content", label: "Nội dung" },
        { key: "internalLink", label: "Internal link" },
        { key: "image", label: "Hình ảnh" },
    ];

    const cauModalClassifyGroup = (text, factor) => {
        const blob = String(text || "") + " " + String((factor && factor.label) || "") + " " + String((factor && factor.id) || "");
        const lower = blob.toLowerCase();
        if (/internal|liên kết nội|internal link|anchor/.test(lower)) return "internalLink";
        if (/hình|ảnh|image|alt|img|media/.test(lower)) return "image";
        if (/heading|h1|h2|h3|tiêu đề phụ/.test(lower)) return "heading";
        if (/title|meta|slug|description|excerpt|mô tả/.test(lower)) return "titleMeta";
        return "content";
    };

    const CAU_LD_JSON_SCRIPT_RE = /<script[^>]*type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>/gi;

    const cauModalExtractLdJsonScripts = (html) => {
        const scripts = [];
        String(html || "").replace(CAU_LD_JSON_SCRIPT_RE, (match) => {
            scripts.push(match);
            return "";
        });
        return scripts;
    };

    const cauModalMergeContentHtml = (editorHtml, storedHtml) => {
        let merged = String(editorHtml || "");
        const scripts = cauModalExtractLdJsonScripts(storedHtml);
        if (!scripts.length) return merged;
        CAU_LD_JSON_SCRIPT_RE.lastIndex = 0;
        if (!CAU_LD_JSON_SCRIPT_RE.test(merged)) {
            merged = merged.replace(/\s+$/, "") + "\n" + scripts.join("\n");
        }
        return merged;
    };

    const cauModalSyncEditorToStore = () => {
        const hidden = byId("cauModalContent");
        if (!hidden) return;
        if (cauBlockEditor) {
            hidden.value = cauBlockEditor.getHtml();
        } else {
            const editor = byId("cauModalContentEditor");
            if (editor) hidden.value = cauModalMergeContentHtml(editor.innerHTML, hidden.value);
        }
        const htmlTa = byId("cauModalContentHtml");
        const adv = byId("cauModalAdvanced");
        if (htmlTa && adv && !adv.open) htmlTa.value = hidden.value;
    };

    let cauBlockEditor = null;
    let cauInsertState = {
        index: 0, type: "", presetLevel: 2, forceHeading: false,
        previewHtml: "", previewValid: false, wordTarget: 0, generating: false,
    };

    const cauEnsureBlockEditor = () => {
        if (cauBlockEditor) return cauBlockEditor;
        if (!window.CauBlockEditor || !window.CauBlockEditor.Editor) return null;
        const mount = byId("cauBlockEditorMount");
        const structureMount = byId("cauStructureMount");
        if (!mount) return null;
        cauBlockEditor = new window.CauBlockEditor.Editor({
            mount: mount,
            structureMount: structureMount,
            onChange: (html) => {
                const hidden = byId("cauModalContent");
                if (hidden) hidden.value = html;
                const htmlTa = byId("cauModalContentHtml");
                if (htmlTa) htmlTa.value = html;
                cauModalSaveDraft();
            },
            onSelect: (block) => {
                if (cauAssistantUI) cauAssistantUI.onBlockSelected(block);
                try { cauAsstCtxSetBlock(block); } catch (_) {}
            },
        });
        cauBlockEditor.onRequestInsert = (index, opts) => {
            cauInsertOpen(index, opts || {});
        };
        // Hide legacy contenteditable — its white #f8fafc frame must not show under block editor
        const legacyEd = byId("cauModalContentEditor");
        if (legacyEd) {
            legacyEd.setAttribute("hidden", "");
            legacyEd.setAttribute("aria-hidden", "true");
            legacyEd.style.display = "none";
            legacyEd.innerHTML = "";
        }
        return cauBlockEditor;
    };

    let cauAssistantUI = null;
    const cauEnsureAssistantUI = () => {
        if (cauAssistantUI) return cauAssistantUI;
        if (!window.CauAssistantUI) return null;
        cauAssistantUI = new window.CauAssistantUI({
            apiFetch: apiFetch,
            authJsonHeaders: authJsonHeaders,
            getEditor: () => cauEnsureBlockEditor(),
            getForm: () => {
                const f = cauModalReadForm();
                return {
                    primary_keyword: f.primary_keyword || f.keyword || "",
                    keyword: f.keyword || "",
                    content_html: cauModalGetContentHtml(),
                    post_id: cauModalState.postId || null,
                    post_url: cauModalState.postUrl || "",
                    session_id: cauModalState.sessionId || "",
                };
            },
            setHint: (kind, msg) => cauSetStatus("cauModalAssistantHint", kind, msg),
            onContentApplied: (html) => {
                if (html) cauModalSetContentHtml(html);
                cauModalSaveDraft();
            },
        });
        cauAssistantUI.init();
        return cauAssistantUI;
    };

    const cauModalSetContentHtml = (html) => {
        const val = String(html || "");
        const hidden = byId("cauModalContent");
        const editor = byId("cauModalContentEditor");
        const htmlTa = byId("cauModalContentHtml");
        if (hidden) hidden.value = val;
        if (htmlTa) htmlTa.value = val;
        const be = cauEnsureBlockEditor();
        if (be) {
            be.loadHtml(val);
            if (editor) editor.innerHTML = "";
            return;
        }
        if (editor) editor.innerHTML = val;
    };

    const cauModalGetContentHtml = () => {
        const hidden = byId("cauModalContent");
        if (!hidden) return "";
        if (cauBlockEditor) {
            hidden.value = cauBlockEditor.getHtml();
            return hidden.value;
        }
        const editor = byId("cauModalContentEditor");
        if (editor && !editor.hidden) {
            hidden.value = cauModalMergeContentHtml(editor.innerHTML, hidden.value);
        }
        return hidden.value;
    };

    const cauModalContentHasLink = (url) => {
        const href = String(url || "").trim();
        if (!href) return false;
        const html = cauModalGetContentHtml();
        const norm = href.replace(/\/$/, "");
        return html.indexOf(href) >= 0 || html.indexOf(norm) >= 0;
    };

    const cauModalInsertLinkHtml = (url, anchor) => {
        const href = String(url || "").trim();
        const text = String(anchor || "").trim() || href;
        if (!href) return false;
        if (cauModalContentHasLink(href)) return false;
        const linkHtml = '<p><a href="' + href.replace(/"/g, "&quot;") + '">' + text.replace(/</g, "&lt;") + "</a></p>";
        const be = cauEnsureBlockEditor();
        if (be) {
            be.insertAt(be.blocks.length, linkHtml, true);
            return true;
        }
        const editor = byId("cauModalContentEditor");
        if (!editor) return false;
        editor.focus();
        try {
            document.execCommand("insertHTML", false, linkHtml);
        } catch (_) {
            editor.innerHTML = editor.innerHTML + linkHtml;
        }
        cauModalSyncEditorToStore();
        return true;
    };

    const cauModalSetFieldHint = (field, text) => {
        const el = byId("cauHint-" + field);
        if (el) el.textContent = String(text || "");
    };

    const cauModalGetTargetWebsite = () => {
        const url = String(cauModalState.postUrl || "").trim();
        if (!url) return "";
        try {
            const u = new URL(url.includes("://") ? url : "https://" + url);
            return u.protocol + "//" + u.host;
        } catch (_) {
            return typeof normalizeTargetBase === "function" ? normalizeTargetBase(url) : url.replace(/\/[^/]*$/, "");
        }
    };

    const cauModalBuildSuggestContext = () => ({
        title: (byId("cauModalTitle") && byId("cauModalTitle").value.trim()) || "",
        target_website: cauModalGetTargetWebsite(),
        slug: (byId("cauModalSlug") && byId("cauModalSlug").value.trim()) || "",
        primary_keyword: (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "",
        secondary_keywords: (byId("cauModalSecondaryKw") && byId("cauModalSecondaryKw").value.trim()) || "",
        outline_content: (byId("cauModalOutline") && byId("cauModalOutline").value) || "",
        meta_description: (byId("cauModalExcerpt") && byId("cauModalExcerpt").value.trim()) || "",
        content: cauModalGetContentHtml(),
        target_word_count: 1200,
    });

    const cauModalFetchSuggestion = async (field) => {
        const ctx = cauModalBuildSuggestContext();
        const reqId = "cau_" + Date.now() + "_" + Math.random().toString(36).slice(2, 10);
        const postSuggest = (syncMode) =>
            fetch("/content-ai/suggest?ts=" + Date.now() + "&llm=1" + (syncMode ? "&sync=1" : ""), {
                method: "POST",
                headers: Object.assign({}, authJsonHeaders(), { "X-Request-Id": reqId + (syncMode ? "_sync" : "") }),
                body: JSON.stringify({ field, ...ctx }),
            });
        const parseSuggestOk = (payload) => ({
            value: String((payload && payload.value) || "").trim(),
            detected_intent: (payload && payload.detected_intent) ? payload.detected_intent : "",
            credits_charged: payload && payload.credits_charged != null ? Number(payload.credits_charged) : 0,
        });
        const hasFinalValue = (payload) => {
            if (!payload || payload.value == null || payload.value === "") return false;
            if (!payload.job_id) return true;
            const st = String(payload.state || "").toUpperCase();
            return st === "COMPLETED" || st === "SUCCESS" || payload.sync === true || payload.sync_fallback === true;
        };

        const preferSync = field === "content" || ["title", "meta_description", "slug", "tags", "primary_keyword", "secondary_keywords", "outline_content"].includes(field);

        let res = await postSuggest(preferSync);
        let data = await res.json().catch(() => ({}));
        if (!res.ok) {
            if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
            }
            const detail = data.detail;
            let msg = "";
            if (window.ContentAiErrors && window.ContentAiErrors.extract) {
                msg = window.ContentAiErrors.extract(data) || "";
            }
            if (!msg && detail && typeof detail === "object" && detail.message) {
                msg = String(detail.message);
            } else if (!msg && typeof detail === "string") {
                msg = detail;
            }
            if (!msg) {
                msg =
                    (typeof fmtApiDetail === "function" ? fmtApiDetail(detail) : "") ||
                    data.message ||
                    "Gợi ý AI thất bại.";
            }
            if (window.ContentAiErrors && window.ContentAiErrors.showIfLlmUnavailable) {
                window.ContentAiErrors.showIfLlmUnavailable(data, msg);
            }
            throw new Error(msg);
        }
        if (hasFinalValue(data)) {
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
            return parseSuggestOk(data);
        }
        if (data && data.job_id && data.poll_url) {
            let final = data;
            let done = false;
            let poll404 = false;
            for (let i = 0; i < 600; i++) {
                await new Promise((r) => setTimeout(r, 600));
                const pr = await fetch(data.poll_url, { headers: authJsonHeaders() });
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
                res = await postSuggest(true);
                data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || data.message || "Không tìm thấy job gợi ý AI.");
                final = data;
                done = hasFinalValue(data);
            }
            if (!done) throw new Error("Hết thời gian chờ job gợi ý AI.");
            if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
            return parseSuggestOk(final);
        }
        if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
        return parseSuggestOk(data);
    };

    const cauModalApplyAiField = (field, value) => {
        const map = {
            title: "cauModalTitle",
            meta_description: "cauModalExcerpt",
            secondary_keywords: "cauModalSecondaryKw",
            outline_content: "cauModalOutline",
        };
        const id = map[field];
        if (!id) return;
        const el = byId(id);
        if (el) el.value = value || "";
    };

    const cauModalToggleAiButtons = () => {
        const hasKw = !!((byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()));
        document.querySelectorAll("[data-cau-ai-field]").forEach((btn) => {
            btn.disabled = !hasKw;
        });
        if (!hasKw) {
            cauModalSetFieldHint("title", "Nhập Focus keyword trước để bật gợi ý AI.");
        } else {
            cauModalSetFieldHint("title", "");
        }
    };

    const cauModalSwitchEditorTab = (tabKey) => {
        const key = String(tabKey || "content");
        cauModalState.editorTab = key;
        document.querySelectorAll("[data-cau-editor-tab]").forEach((btn) => {
            const on = btn.getAttribute("data-cau-editor-tab") === key;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll("[data-cau-editor-panel]").forEach((panel) => {
            const on = panel.getAttribute("data-cau-editor-panel") === key;
            if (on) panel.removeAttribute("hidden");
            else panel.setAttribute("hidden", "");
        });
        const siteEl = byId("cauModalIlSite");
        const kwEl = byId("cauModalIlKw");
        if (siteEl) siteEl.textContent = cauModalGetTargetWebsite() || "—";
        if (kwEl) kwEl.textContent = (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "—";
        if (cauBlockEditor && typeof cauBlockEditor.setStructureActive === "function") {
            cauBlockEditor.setStructureActive(key === "outline");
        } else if (key === "outline" && cauBlockEditor) {
            cauBlockEditor.renderStructure();
        }
        if (key === "changes" && cauAssistantUI) cauAssistantUI.renderChanges();
        if (cauModalState.open && cauModalState.postUrl) cauModalSaveDraft();
    };

    // ---- «Thêm nội dung» modal: per-type forms, AI suggest, server preview ----

    const CAU_INSERT_TYPE_TO_FORM = {
        h2: "heading", h3: "heading", h4: "heading",
        paragraph: "paragraph", list: "list", table: "table",
        faq: "faq", cta: "cta", image: "image", internal: "internal",
    };

    const cauInsertWordCountOf = (html) => {
        const d = document.createElement("div");
        d.innerHTML = String(html || "");
        const t = (d.textContent || "").replace(/\s+/g, " ").trim();
        return t ? t.split(" ").length : 0;
    };

    // Số từ phần nội dung (không tính chữ trong heading) — khớp cách backend đếm
    const cauInsertBodyWordCountOf = (html) => {
        const d = document.createElement("div");
        d.innerHTML = String(html || "");
        d.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach((h) => h.remove());
        const t = (d.textContent || "").replace(/\s+/g, " ").trim();
        return t ? t.split(" ").length : 0;
    };

    const cauInsertContentGetHtml = () => {
        const el = byId("cauInsertContentBody");
        return el ? el.innerHTML.trim() : "";
    };

    const cauInsertContentHasData = () => {
        const el = byId("cauInsertContentBody");
        if (!el) return false;
        if ((el.textContent || "").trim()) return true;
        return !!el.querySelector("img,table,figure,iframe,a");
    };

    const cauInsertUpdateWordCounter = () => {
        const counter = byId("cauInsertWordCounter");
        if (!counter) return;
        const html = cauInsertContentGetHtml();
        const words = cauInsertBodyWordCountOf(html);
        const target = cauInsertState.wordTarget || 0;
        if (!cauInsertContentHasData()) {
            counter.hidden = true;
            counter.textContent = "";
            return;
        }
        counter.hidden = false;
        counter.textContent = target
            ? "Đã viết " + words + "/" + target + " từ"
            : words + " từ";
        counter.classList.toggle("is-short", !!target && words < Math.round(target * 0.9));
    };

    const cauInsertSyncContentState = () => {
        const el = byId("cauInsertContentBody");
        // Xóa hết chữ nhưng trình duyệt để sót <br>/<p> rỗng → dọn để placeholder hiện lại
        if (el && !cauInsertContentHasData() && el.innerHTML !== "") el.innerHTML = "";
        const has = cauInsertContentHasData();
        cauInsertState.previewHtml = has ? cauInsertContentGetHtml() : "";
        cauInsertState.previewValid = has;
        cauInsertSetApplyEnabled(has);
        cauInsertUpdateWordCounter();
        const s2 = byId("cauInsertStep2");
        if (s2 && !s2.hidden) cauInsertSetStep(has ? 3 : 2);
    };

    const cauInsertSetContentHtml = (html) => {
        const el = byId("cauInsertContentBody");
        if (el) el.innerHTML = String(html || "");
        cauInsertSyncContentState();
    };

    const cauInsertSetError = (msg) => {
        const err = byId("cauInsertError");
        if (!err) return;
        if (msg) { err.hidden = false; err.textContent = msg; }
        else { err.hidden = true; err.textContent = ""; }
    };

    const cauInsertSetApplyEnabled = (on) => {
        const btn = byId("btnCauInsertApply");
        if (btn) btn.disabled = !on;
        const regen = byId("btnCauInsertRegen");
        if (regen) regen.hidden = !on;
    };

    const cauInsertResetPreview = () => {
        cauInsertState.previewHtml = "";
        cauInsertState.previewValid = false;
        cauInsertState.wordTarget = 0;
        const body = byId("cauInsertContentBody");
        if (body) body.innerHTML = "";
        const counter = byId("cauInsertWordCounter");
        if (counter) { counter.hidden = true; counter.textContent = ""; }
        cauInsertSetApplyEnabled(false);
        // Nếu đang ở bước 2/3 thì lùi chỉ báo về bước 2 (chưa có nội dung)
        const s2 = byId("cauInsertStep2");
        if (s2 && !s2.hidden) cauInsertSetStep(2);
    };

    const CAU_INSERT_TYPE_LABEL = {
        h2: "Tiêu đề H2 — mục lớn mới",
        h3: "Tiêu đề H3 — mục nhỏ trong mục lớn",
        h4: "Tiêu đề H4",
        paragraph: "Đoạn văn — đoạn chữ giải thích",
        list: "Danh sách — các bước / lợi ích",
        table: "Bảng",
        faq: "FAQ — câu hỏi thường gặp",
        cta: "CTA — nút kêu gọi hành động",
        image: "Ảnh minh họa",
        internal: "Internal link — link bài trên web của bạn",
    };

    const cauInsertSetStep = (step) => {
        const s1 = byId("cauInsertStep1");
        const s2 = byId("cauInsertStep2");
        if (s1) s1.hidden = step !== 1;
        if (s2) s2.hidden = step === 1;
        document.querySelectorAll("[data-cau-ins-step-dot]").forEach((el) => {
            const n = parseInt(el.getAttribute("data-cau-ins-step-dot"), 10);
            el.classList.toggle("is-active", n === step);
            el.classList.toggle("is-done", n < step);
        });
    };

    const cauInsertClose = () => {
        const modal = byId("cauInsertModal");
        if (modal) modal.setAttribute("hidden", "");
        cauInsertResetPreview();
        cauInsertSetError("");
        document.querySelectorAll(".cau-ins-suggest-list").forEach((el) => {
            el.setAttribute("hidden", "");
            el.innerHTML = "";
        });
        if (cauAssistantUI && cauAssistantUI.setInsertPreview) cauAssistantUI.setInsertPreview("");
        cauAsstCtxSetPreview("");
    };

    const cauInsertShowForm = (type) => {
        const formKey = CAU_INSERT_TYPE_TO_FORM[type] || "heading";
        document.querySelectorAll("#cauInsertForms .cau-ins-form").forEach((f) => {
            f.hidden = f.getAttribute("data-cau-ins-form") !== formKey;
        });
        cauInsertState.type = type;
        if (formKey === "heading") {
            const lvl = byId("cauInsHeadingLevel");
            if (lvl && /^h[234]$/.test(type)) lvl.value = type.replace("h", "");
        }
        const label = byId("cauInsertStepLabel");
        if (label) label.textContent = CAU_INSERT_TYPE_LABEL[type] || "";
        cauInsertSetStep(2);
        cauInsertResetPreview();
        cauInsertSetError("");
    };

    const cauInsertOpen = (index, opts) => {
        opts = opts || {};
        cauInsertState = {
            index: parseInt(index, 10) || 0,
            type: "",
            presetLevel: opts.presetLevel || 2,
            forceHeading: !!opts.forceHeading,
            previewHtml: "",
            previewValid: false,
            wordTarget: 0,
            generating: false,
        };
        const modal = byId("cauInsertModal");
        if (!modal) return;
        modal.removeAttribute("hidden");
        // Prefill keyword fields from modal keyword
        const kwMain = (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "";
        ["cauInsHeadingKeyword", "cauInsParaKeyword", "cauInsFaqKeyword", "cauInsTableKeyword"].forEach((id) => {
            const el = byId(id);
            if (el && !el.value) el.value = kwMain;
        });
        if (opts.forceHeading) {
            cauInsertShowForm("h" + (opts.presetLevel || 2));
        } else {
            cauInsertSetStep(1);
        }
    };

    const cauInsertContextPayload = () => {
        const ed = cauEnsureBlockEditor();
        return {
            session_id: String(cauModalState.sessionId || ""),
            content_html: ed ? ed.getHtml() : cauModalGetContentHtml(),
            blocks: ed && ed.getBlocksPayload ? ed.getBlocksPayload() : [],
            insert_index: cauInsertState.index,
            title: (byId("cauModalTitle") && byId("cauModalTitle").value.trim()) || "",
            primary_keyword: (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "",
            post_url: String(cauModalState.postUrl || ""),
        };
    };

    // Collect per-type options. Returns null with an error shown when invalid.
    const cauInsertCollectOptions = () => {
        const type = cauInsertState.type;
        const v = (id) => (byId(id) && byId(id).value != null ? String(byId(id).value).trim() : "");
        if (CAU_INSERT_TYPE_TO_FORM[type] === "heading") {
            const mode = (document.querySelector('input[name="cauInsHeadingMode"]:checked') || {}).value || "heading_only";
            const title = v("cauInsHeadingTitle");
            if (!title) { cauInsertSetError("Nhập tên heading hoặc chọn từ «AI gợi ý heading»."); return null; }
            return {
                insert_type: "heading",
                use_llm: mode === "ai_write",
                options: {
                    title: title,
                    level: parseInt(v("cauInsHeadingLevel") || "2", 10) || 2,
                    with_content: mode === "ai_write",
                    word_count: parseInt(v("cauInsHeadingWords") || "200", 10) || 200,
                    keyword: v("cauInsHeadingKeyword"),
                },
            };
        }
        if (type === "paragraph") {
            return {
                insert_type: "paragraph",
                use_llm: true,
                options: {
                    purpose: v("cauInsParaPurpose") || "explain",
                    length: v("cauInsParaLength") || "medium",
                    tone: v("cauInsParaTone") || "neutral",
                    keyword: v("cauInsParaKeyword"),
                },
            };
        }
        if (type === "cta") {
            return {
                insert_type: "cta",
                use_llm: true,
                options: {
                    channel: v("cauInsCtaChannel") || "call",
                    target: v("cauInsCtaTarget"),
                    title: v("cauInsCtaTitle"),
                    body: v("cauInsCtaBody"),
                    button: v("cauInsCtaButton"),
                },
            };
        }
        if (type === "faq") {
            const items = v("cauInsFaqQuestions").split(/\n+/).map((s) => s.trim()).filter(Boolean)
                .map((q) => ({ question: q, answer: "" }));
            return {
                insert_type: "faq",
                use_llm: true,
                options: { keyword: v("cauInsFaqKeyword"), items: items },
            };
        }
        if (type === "list") {
            const items = v("cauInsListItems").split(/\n+/).map((s) => s.trim()).filter(Boolean);
            return {
                insert_type: "list",
                use_llm: items.length === 0,
                options: { list_kind: v("cauInsListKind") || "steps", items: items },
            };
        }
        if (type === "table") {
            return {
                insert_type: "table",
                use_llm: true,
                options: { table_kind: v("cauInsTableKind") || "comparison", keyword: v("cauInsTableKeyword") },
            };
        }
        if (type === "internal") {
            const url = v("cauInsLinkUrl");
            if (!url) { cauInsertSetError("Chọn URL nội bộ (bấm «Tìm URL» để tải bài từ website)."); return null; }
            return {
                insert_type: "internal_link",
                use_llm: false,
                options: { url: url, anchor: v("cauInsLinkAnchor"), sentence: v("cauInsLinkSentence") },
            };
        }
        if (type === "image") {
            const url = v("cauInsImageUrl");
            const urlErr = cauValidateUrl(url, "URL ảnh");
            if (urlErr) { cauInsertSetError(urlErr); return null; }
            const alt = v("cauInsImageAlt");
            const caption = v("cauInsImageCaption");
            return {
                insert_type: "image",
                use_llm: !alt || !caption,
                options: { url: url, alt: alt, caption: caption },
            };
        }
        cauInsertSetError("Chọn loại nội dung trước.");
        return null;
    };

    // AI trả kết quả → ghi thẳng vào ô «Nội dung» (không dùng box preview riêng)
    const cauInsertRenderPreview = (preview) => {
        cauInsertState.wordTarget = parseInt(preview.word_target, 10) || 0;
        cauInsertSetContentHtml(String(preview.html || ""));
        (preview.warnings || []).length
            ? cauInsertSetError((preview.warnings || []).join(" "))
            : cauInsertSetError("");
        cauAsstCtxSetPreview(cauInsertState.previewHtml);
    };

    const cauInsertGeneratePreview = () => {
        if (cauInsertState.generating) return Promise.resolve();
        const spec = cauInsertCollectOptions();
        if (!spec) return Promise.resolve();
        cauInsertSetError("");
        cauInsertState.generating = true;
        const btn = byId("btnCauInsertPreviewGen");
        const regen = byId("btnCauInsertRegen");
        if (btn) { btn.disabled = true; btn.textContent = "Đang tạo…"; }
        if (regen) regen.disabled = true;
        const payload = Object.assign(cauInsertContextPayload(), {
            insert_type: spec.insert_type,
            options: spec.options,
            use_llm: !!spec.use_llm,
            site_id: String(cauModalState.siteId || ""),
        });
        const call = (useLlm) => cauApi("POST", "/content-ai/auto-update/modal/insert/generate",
            Object.assign({}, payload, { use_llm: useLlm }));
        return call(payload.use_llm)
            .catch((e) => {
                // LLM not available for this plan/credits — fall back to free template
                if (payload.use_llm && (e.status === 402 || e.status === 403)) {
                    cauInsertSetError("AI không khả dụng (" + (e.message || "quota") + ") — dùng bản mẫu, 0 credit.");
                    return call(false);
                }
                throw e;
            })
            .then((data) => {
                if (data && data.preview) cauInsertRenderPreview(data.preview);
            })
            .catch((e) => {
                cauInsertSetError(e.message || "Không tạo được nội dung.");
            })
            .then(() => {
                cauInsertState.generating = false;
                if (btn) { btn.disabled = false; btn.textContent = "Tạo nội dung AI"; }
                if (regen) regen.disabled = false;
            });
    };

    const cauInsertRenderSuggestions = (kind, items) => {
        const map = { heading: "cauInsSuggestHeading", cta: "cauInsSuggestCta", faq: "cauInsSuggestFaq" };
        const box = byId(map[kind]);
        if (!box) return;
        box.innerHTML = "";
        (items || []).forEach((it) => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "cau-ins-suggest-item";
            if (kind === "heading") b.textContent = it.title || "";
            else if (kind === "cta") b.textContent = (it.title || "") + (it.button ? (" [" + it.button + "]") : "");
            else b.textContent = it.question || "";
            b.addEventListener("click", () => {
                if (kind === "heading") {
                    const el = byId("cauInsHeadingTitle");
                    if (el) el.value = it.title || "";
                } else if (kind === "cta") {
                    if (byId("cauInsCtaTitle")) byId("cauInsCtaTitle").value = it.title || "";
                    if (it.body && byId("cauInsCtaBody")) byId("cauInsCtaBody").value = it.body;
                    if (it.button && byId("cauInsCtaButton")) byId("cauInsCtaButton").value = it.button;
                    if (it.channel && byId("cauInsCtaChannel")) byId("cauInsCtaChannel").value = it.channel;
                } else if (kind === "faq") {
                    const ta = byId("cauInsFaqQuestions");
                    if (ta) ta.value = (ta.value ? ta.value.replace(/\s+$/, "") + "\n" : "") + (it.question || "");
                }
                // Giữ nguyên nội dung đã nhập — chỉ điền tiêu đề/câu hỏi được chọn
            });
            box.appendChild(b);
        });
        box.hidden = !(items || []).length;
    };

    const cauInsertSuggest = (kind, btn) => {
        const payload = Object.assign(cauInsertContextPayload(), {
            kind: kind, count: 5, use_llm: true,
        });
        if (btn) { btn.disabled = true; btn.textContent = "Đang gợi ý…"; }
        const call = (useLlm) => cauApi("POST", "/content-ai/auto-update/modal/insert/suggest",
            Object.assign({}, payload, { use_llm: useLlm }));
        return call(true)
            .catch((e) => {
                if (e.status === 402 || e.status === 403) return call(false);
                throw e;
            })
            .then((data) => {
                cauInsertRenderSuggestions(kind, (data && data.suggestions) || []);
            })
            .catch((e) => {
                cauInsertSetError(e.message || "Không lấy được gợi ý.");
            })
            .then(() => {
                if (btn) { btn.disabled = false; btn.textContent = "AI gợi ý " + (kind === "heading" ? "heading" : kind === "cta" ? "CTA" : "câu hỏi"); }
            });
    };

    const cauInsertLoadSiteLinks = () => {
        const sid = String(cauModalState.siteId || "");
        const sel = byId("cauInsLinkUrl");
        if (!sel) return Promise.resolve();
        if (!sid) {
            cauInsertSetError("Chưa xác định website (site) của phiên sửa.");
            return Promise.resolve();
        }
        const q = (byId("cauInsLinkSearch") && byId("cauInsLinkSearch").value.trim()) || "";
        sel.innerHTML = '<option value="">Đang tải URL…</option>';
        return cauApi("GET", "/content-ai/auto-update/modal/insert/site-links?site_id=" +
            encodeURIComponent(sid) + "&q=" + encodeURIComponent(q))
            .then((data) => {
                const items = (data && data.items) || [];
                sel.innerHTML = "";
                if (!items.length) {
                    sel.innerHTML = '<option value="">Không tìm thấy bài phù hợp</option>';
                    return;
                }
                items.forEach((it) => {
                    const o = document.createElement("option");
                    o.value = it.url;
                    o.textContent = (it.title || it.slug || it.url).slice(0, 90);
                    o.setAttribute("data-title", it.title || "");
                    sel.appendChild(o);
                });
                const anchor = byId("cauInsLinkAnchor");
                if (anchor && !anchor.value && items[0]) anchor.value = items[0].title || "";
            })
            .catch((e) => {
                sel.innerHTML = '<option value="">Lỗi tải URL</option>';
                cauInsertSetError(e.message || "Không tải được URL của website.");
            });
    };

    const cauInsertApplyToArticle = () => {
        cauInsertSyncContentState();
        if (!cauInsertState.previewValid) return;
        const be = cauEnsureBlockEditor();
        if (!be) return;
        // Lấy nội dung (có thể đã sửa tay) từ ô «Nội dung»
        const html = cauInsertContentGetHtml() || cauInsertState.previewHtml;
        if (!html) return;
        be.insertAt(cauInsertState.index, html, true);
        cauInsertClose();
        cauModalSaveDraft();
    };

    // ---- Trợ lý AI (cột phải): block đang chọn, lý do, gợi ý SEO, preview ----

    const cauAsstCtxSetPreview = (html) => {
        const wrap = byId("cauAsstCtxPreviewWrap");
        const body = byId("cauAsstCtxPreview");
        if (!wrap || !body) return;
        const h = String(html || "").trim();
        body.innerHTML = h;
        wrap.hidden = !h;
    };

    const cauAsstCtxSetBlock = (block) => {
        const el = byId("cauAsstCtxBlock");
        const reasonWrap = byId("cauAsstCtxReasonWrap");
        const reason = byId("cauAsstCtxReason");
        const seoWrap = byId("cauAsstCtxSeoWrap");
        const seo = byId("cauAsstCtxSeo");
        if (!el) return;
        if (!block) {
            el.textContent = "Chưa chọn block nào — bấm vào một khối trong bài.";
            if (reasonWrap) reasonWrap.hidden = true;
            if (seoWrap) seoWrap.hidden = true;
            return;
        }
        const div = document.createElement("div");
        div.innerHTML = String(block.current_content || "");
        const text = (div.textContent || "").replace(/\s+/g, " ").trim();
        const words = text ? text.split(" ").length : 0;
        const typeMap = {
            heading: "Tiêu đề", paragraph: "Đoạn văn", list: "Danh sách", table: "Bảng",
            image: "Ảnh", shortcode: "Shortcode", embed: "Embed", gutenberg: "Khối", html: "Khối",
        };
        el.textContent = (typeMap[block.block_type] || "Khối") + ": «" +
            (text.slice(0, 80) || "(trống)") + (text.length > 80 ? "…" : "") + "»" +
            (words ? " · " + words + " từ" : "");
        // Lý do nên thêm nội dung — heuristic đơn giản, dễ hiểu
        let why = "";
        if (block.block_type === "heading") {
            why = "Sau tiêu đề này nên có đoạn văn giải thích, danh sách hoặc FAQ. Bấm «+» bên dưới tiêu đề để thêm.";
        } else if (block.block_type === "paragraph" && words > 0 && words < 40) {
            why = "Đoạn này khá ngắn (" + words + " từ) — có thể bấm «+» để thêm ví dụ hoặc giải thích chi tiết hơn.";
        } else if (block.block_type === "image") {
            why = "Ảnh nên có mô tả (ALT) và chú thích để tốt cho SEO.";
        }
        if (reason) reason.textContent = why;
        if (reasonWrap) reasonWrap.hidden = !why;
        // Gợi ý SEO từ lần phân tích gần nhất
        let seoTip = "";
        const factors = (cauModalState && cauModalState.seoFactors) || [];
        const firstFail = factors.find((f) => String(f.status) === "failed");
        if (firstFail) seoTip = String(firstFail.label || firstFail.name || firstFail.id || "");
        if (seo) seo.textContent = seoTip ? (seoTip + " — xem tab «SEO Core 30».") : "";
        if (seoWrap) seoWrap.hidden = !seoTip;
    };

    const cauInsertBindUi = () => {
        document.querySelectorAll("[data-cau-insert-close]").forEach((el) => {
            el.addEventListener("click", () => cauInsertClose());
        });
        document.querySelectorAll("[data-cau-insert-type]").forEach((btn) => {
            btn.addEventListener("click", () => {
                cauInsertShowForm(btn.getAttribute("data-cau-insert-type"));
            });
        });
        // Nút «AI gợi ý» ngay trên card loại nội dung: mở form + tự chạy gợi ý
        document.querySelectorAll("[data-cau-ins-quick]").forEach((quick) => {
            quick.addEventListener("click", (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                const type = quick.getAttribute("data-cau-ins-quick");
                cauInsertShowForm(type);
                if (type === "h2" || type === "h3" || type === "h4") {
                    const b = document.querySelector('[data-cau-ins-suggest="heading"]');
                    if (b) b.click();
                } else if (type === "cta" || type === "faq") {
                    const b = document.querySelector('[data-cau-ins-suggest="' + type + '"]');
                    if (b) b.click();
                } else if (type === "internal") {
                    cauInsertLoadSiteLinks();
                } else if (type === "paragraph" || type === "list") {
                    // AI viết ngay bản xem thử
                    cauInsertGeneratePreview();
                }
                // image: cần dán URL ảnh trước, chỉ mở form
            });
        });
        const btnBack = byId("btnCauInsertBack");
        if (btnBack) btnBack.addEventListener("click", () => {
            cauInsertResetPreview();
            cauInsertSetError("");
            cauInsertSetStep(1);
        });
        document.querySelectorAll('input[name="cauInsHeadingMode"]').forEach((r) => {
            r.addEventListener("change", () => {
                const ai = byId("cauInsHeadingAiFields");
                const mode = (document.querySelector('input[name="cauInsHeadingMode"]:checked') || {}).value;
                if (ai) ai.hidden = mode !== "ai_write";
                cauInsertResetPreview();
            });
        });
        document.querySelectorAll("[data-cau-ins-suggest]").forEach((btn) => {
            btn.addEventListener("click", () => {
                cauInsertSuggest(btn.getAttribute("data-cau-ins-suggest"), btn);
            });
        });
        const btnGen = byId("btnCauInsertPreviewGen");
        if (btnGen) btnGen.addEventListener("click", () => { cauInsertGeneratePreview(); });
        const btnRegen = byId("btnCauInsertRegen");
        if (btnRegen) btnRegen.addEventListener("click", () => { cauInsertGeneratePreview(); });
        const btnApply = byId("btnCauInsertApply");
        if (btnApply) btnApply.addEventListener("click", () => { cauInsertApplyToArticle(); });
        const btnCancel = byId("btnCauInsertCancel");
        if (btnCancel) btnCancel.addEventListener("click", () => cauInsertClose());
        // Ô «Nội dung» — gõ tay cũng bật «Chèn vào bài viết» + cập nhật bộ đếm từ
        const contentBody = byId("cauInsertContentBody");
        if (contentBody) contentBody.addEventListener("input", () => {
            cauInsertSyncContentState();
        });
        const btnLinks = byId("btnCauInsLinkSearch");
        if (btnLinks) btnLinks.addEventListener("click", () => { cauInsertLoadSiteLinks(); });
        const linkSel = byId("cauInsLinkUrl");
        if (linkSel) linkSel.addEventListener("change", () => {
            const opt = linkSel.options[linkSel.selectedIndex];
            const anchor = byId("cauInsLinkAnchor");
            if (opt && anchor && !anchor.value) anchor.value = opt.getAttribute("data-title") || "";
            cauInsertResetPreview();
        });
    };

    const cauModalInsertImageHtml = (url, alt) => {
        const src = String(url || "").trim();
        if (!src) return false;
        const altText = String(alt || "").trim().replace(/"/g, "&quot;");
        const snippet = '<figure class="wp-block-image"><img src="' + src.replace(/"/g, "&quot;") +
            '" alt="' + altText + '" loading="lazy" /></figure>';
        const be = cauEnsureBlockEditor();
        if (be) {
            be.insertAt(be.blocks.length, snippet, true);
            return true;
        }
        const editor = byId("cauModalContentEditor");
        if (!editor) return false;
        editor.focus();
        try {
            document.execCommand("insertHTML", false, "<p><br></p>" + snippet + "<p><br></p>");
        } catch (_) {
            editor.innerHTML = editor.innerHTML + snippet;
        }
        cauModalSyncEditorToStore();
        return true;
    };

    const cauModalRenderIlCandidates = (items) => {
        const box = byId("cauModalIlCandidates");
        cauModalState.ilCandidates = Array.isArray(items) ? items : [];
        if (!box) return;
        if (!cauModalState.ilCandidates.length) {
            box.innerHTML = '<p class="cau-factor-empty">Chưa có gợi ý — bấm «Tìm link liên quan».</p>';
            return;
        }
        box.innerHTML = cauModalState.ilCandidates.map((it, idx) => {
            const anchor = String(it.anchor_text || it.target_primary_keyword || it.kw_hint_primary || "").trim();
            return (
                '<div class="cau-il-card" role="listitem">' +
                '<input type="checkbox" class="cau-il-cb" data-idx="' + idx + '" checked aria-label="Chọn bài ' + (idx + 1) + '" />' +
                '<div class="cau-il-card__body">' +
                "<strong class=\"cau-il-card__title\">" + cauEsc(it.title || "Bài liên quan") + "</strong>" +
                "<small class=\"cau-il-card__url\">" + cauEsc(it.link || "") + "</small>" +
                '<input type="text" class="cau-il-anchor" data-idx="' + idx + '" value="' + cauEsc(anchor) + '" placeholder="Anchor text" />' +
                "</div></div>"
            );
        }).join("");
    };

    const cauModalGetIlRowPost = (idx) => {
        const n = Number(idx);
        const it = cauModalState.ilCandidates[n];
        if (!it) return null;
        const inp = document.querySelector('.cau-il-anchor[data-idx="' + n + '"]');
        const anchor = inp ? String(inp.value || "").trim() : "";
        const title = String(it.title || "").trim();
        const link = String(it.link || "").trim();
        if (!link) return null;
        return { title: title || anchor, link, anchor_text: anchor || title };
    };

    const cauModalFindInternalLinks = async () => {
        const site = cauModalGetTargetWebsite();
        if (!site) {
            cauModalSetFieldHint("internal-links", "Thiếu URL bài — không xác định được website.");
            return;
        }
        const btn = byId("btnCauFindInternalLinks");
        const old = btn ? btn.textContent : "";
        if (btn) { btn.textContent = "Đang tìm..."; btn.disabled = true; }
        cauModalSetFieldHint("internal-links", "Đang tìm bài trên WordPress + SERP…");
        try {
            const res = await apiFetch("/content-ai/wp-internal-links/candidates?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    target_website: site,
                    primary_keyword: (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "",
                    secondary_keywords: (byId("cauModalSecondaryKw") && byId("cauModalSecondaryKw").value.trim()) || "",
                    content_html: cauModalGetContentHtml(),
                    current_slug: (byId("cauModalSlug") && byId("cauModalSlug").value.trim()) || "",
                    current_url: cauModalState.postUrl || "",
                    limit: 15,
                }),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(String(data.detail || data.message || "Không tìm được bài liên quan."));
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            cauModalRenderIlCandidates(data.items || []);
            const n = (data.items || []).length;
            cauModalSetFieldHint("internal-links", n
                ? "Tìm thấy " + n + " bài — tick và sửa anchor nếu cần, rồi «Chèn đã chọn»."
                : String(data.hint || "Không có bài phù hợp — thử đổi từ khóa hoặc thêm H2 trong bài."));
        } catch (e) {
            cauModalSetFieldHint("internal-links", String(e.message || e));
        } finally {
            if (btn) { btn.textContent = old; btn.disabled = false; }
        }
    };

    const cauModalApplyInternalLinks = async () => {
        const checked = Array.from(document.querySelectorAll(".cau-il-cb:checked"))
            .map((cb) => Number(cb.getAttribute("data-idx")))
            .filter((n) => Number.isFinite(n));
        if (!checked.length) {
            cauModalSetFieldHint("internal-links", "Tick chọn ít nhất một bài.");
            return;
        }
        const posts = checked.map((idx) => cauModalGetIlRowPost(idx)).filter(Boolean);
        if (!posts.length) {
            cauModalSetFieldHint("internal-links", "Thiếu URL hoặc anchor — kiểm tra lại.");
            return;
        }
        const btn = byId("btnCauApplyInternalLinks");
        const old = btn ? btn.textContent : "";
        if (btn) { btn.textContent = "Đang chèn..."; btn.disabled = true; }
        try {
            const res = await apiFetch("/content-ai/wp-internal-links/apply?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    content_html: cauModalGetContentHtml(),
                    target_website: cauModalGetTargetWebsite(),
                    selected_posts: posts,
                    custom_links: [],
                    current_url: cauModalState.postUrl || "",
                    article_primary_keyword: (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "",
                    article_secondary_keywords: (byId("cauModalSecondaryKw") && byId("cauModalSecondaryKw").value.trim()) || "",
                    use_llm_rewrite: false,
                    apply_mode: "full",
                    append_lead: "Tham khảo thêm:",
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(String(data.detail || data.message || "Chèn internal link thất bại."));
            const outHtml = String(data.content_html || "").trim();
            if (outHtml) {
                cauModalSetContentHtml(outHtml);
                cauModalSaveDraft();
                cauModalScoreLive().catch(() => {});
            }
            const ins = Number(data.inserted_links || posts.length);
            cauModalSetFieldHint("internal-links", "Đã chèn " + ins + " internal link vào bài.");
            cauSetStatus("cauModalEditorHint", "ok", "Đã cập nhật nội dung với internal link.");
        } catch (e) {
            cauModalSetFieldHint("internal-links", String(e.message || e));
        } finally {
            if (btn) { btn.textContent = old; btn.disabled = false; }
        }
    };

    const cauModalRenderImageResults = (items) => {
        const box = byId("cauModalImageResults");
        if (!box) return;
        const list = Array.isArray(items) ? items : [];
        cauModalState.imageResults = list;
        if (!list.length) {
            box.innerHTML = '<p class="cau-factor-empty">Không có ảnh phù hợp.</p>';
            return;
        }
        const kw = (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "";
        box.innerHTML = list.map((it, idx) => {
            const thumb = String(it.thumbnail || it.link || "").trim();
            const title = String(it.title || "").trim();
            const cap = title ? '<p class="cau-image-card__title" title="' + cauEsc(title) + '">' + cauEsc(title.slice(0, 72)) + (title.length > 72 ? "…" : "") + "</p>" : "";
            return (
                '<div class="cau-image-card" role="listitem">' +
                (thumb ? '<img src="' + cauEsc(thumb) + '" alt="" loading="lazy" />' : "") +
                cap +
                '<div class="cau-image-card__actions">' +
                '<button type="button" class="mini-btn" data-cau-insert-img="' + idx + '">Chèn</button>' +
                "</div></div>"
            );
        }).join("");
        box.querySelectorAll("[data-cau-insert-img]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const idx = Number(btn.getAttribute("data-cau-insert-img"));
                const it = (cauModalState.imageResults || [])[idx];
                if (!it) return;
                const alt = String(it.title || kw || "").trim() || kw;
                void cauModalImportAndInsertImage(it, alt);
            });
        });
    };

    const cauModalFindImages = async () => {
        const ctx = cauModalBuildSuggestContext();
        const kw = String(ctx.primary_keyword || "").trim();
        if (!kw && !(byId("cauModalImageQuery") && byId("cauModalImageQuery").value.trim())) {
            cauModalSetFieldHint("images", "Nhập Focus keyword hoặc từ khóa ảnh.");
            return;
        }
        const manualRaw = (byId("cauModalImageQuery") && byId("cauModalImageQuery").value.trim()) || "";
        const manualQ = (manualRaw && manualRaw.toLowerCase() !== kw.toLowerCase()) ? manualRaw : "";
        const num = (byId("cauModalImageNum") && byId("cauModalImageNum").value) || "8";
        const btn = byId("btnCauFindImages");
        const old = btn ? btn.textContent : "";
        if (btn) { btn.textContent = "Đang tìm..."; btn.disabled = true; }
        cauModalSetFieldHint("images", "Đang tìm ảnh theo ngữ cảnh bài...");
        try {
            const res = await fetch("/content-ai/google-images/search-context?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    primary_keyword: kw,
                    title: ctx.title || "",
                    outline_content: ctx.outline_content || "",
                    content_html: ctx.content || "",
                    q: manualQ,
                    num: Number(num) || 8,
                }),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(String(data.detail || data.message || "Tìm ảnh thất bại."));
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            cauModalRenderImageResults(data.items || []);
            const usedQ = String(data.query || manualQ || kw).trim();
            const src = String(data.source || "").trim();
            const n = (data.items || []).length;
            let hint = "Tìm thấy " + n + " ảnh";
            if (usedQ) hint += " — truy vấn: «" + usedQ + "»";
            if (src) hint += " (" + src + ")";
            hint += " — bấm «Chèn».";
            cauModalSetFieldHint("images", hint);
        } catch (e) {
            cauModalSetFieldHint("images", String(e.message || e));
        } finally {
            if (btn) { btn.textContent = old; btn.disabled = false; }
        }
    };

    const cauModalImportAndInsertImage = async (item, alt) => {
        const link = String((item && (item.link || item.url)) || "").trim();
        if (!link) return;
        cauModalSetFieldHint("images", "Đang import ảnh...");
        try {
            const res = await fetch("/content-ai/google-images/import?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ url: link }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(String(data.detail || data.message || "Import ảnh thất bại."));
            if (data.url && cauModalInsertImageHtml(data.url, alt)) {
                cauModalSaveDraft();
                cauModalScoreLive().catch(() => {});
                cauModalSetFieldHint("images", "Đã chèn ảnh vào bài.");
                cauSetStatus("cauModalEditorHint", "ok", "Đã chèn ảnh minh họa.");
                cauModalSwitchEditorTab("content");
            }
        } catch (e) {
            cauModalSetFieldHint("images", String(e.message || e));
        }
    };

    const cauModalCountReplaceMatches = (text, rgx) => (String(text || "").match(rgx) || []).length;

    const cauModalReplaceAllBrands = () => {
        const from = (byId("cauModalReplaceFrom") && byId("cauModalReplaceFrom").value.trim()) || "";
        const to = (byId("cauModalReplaceTo") && byId("cauModalReplaceTo").value.trim()) || "";
        if (!from) {
            cauModalSetFieldHint("outline-actions", "Vui lòng nhập từ cần thay.");
            return;
        }
        const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const rgx = new RegExp(escaped, "gi");
        let total = 0;
        [
            "cauModalTitle",
            "cauModalExcerpt",
            "cauModalKeyword",
            "cauModalSecondaryKw",
            "cauModalSlug",
            "cauModalOutline",
        ].forEach((id) => {
            const el = byId(id);
            if (!el) return;
            const before = el.value;
            const n = cauModalCountReplaceMatches(before, rgx);
            if (n) {
                el.value = before.replace(rgx, to);
                total += n;
            }
        });
        cauModalSyncEditorToStore();
        const content = cauModalGetContentHtml();
        const cn = cauModalCountReplaceMatches(content, rgx);
        if (cn) {
            cauModalSetContentHtml(content.replace(rgx, to));
            total += cn;
        }
        if (!total) {
            cauModalSetFieldHint("outline-actions", "Không tìm thấy «" + from + "» trong bài.");
            return;
        }
        cauModalSaveDraft();
        cauModalScoreLive().catch(() => {});
        cauModalSetFieldHint("outline-actions", "Đã thay " + total + " vị trí (title, meta, keyword, outline, content).");
        cauSetStatus("cauModalEditorHint", "ok", "Đã thay thế thương hiệu đối thủ trong toàn bộ bài.");
    };

    const cauModalRefreshOutline = async () => {
        const ol = byId("cauModalOutline");
        const outline = (ol && ol.value.trim()) || "";
        if (!outline) {
            cauModalSetFieldHint("outline-actions", "Vui lòng nhập outline trước khi làm mới.");
            return;
        }
        const btn = byId("btnCauModalRefreshOutline");
        const old = btn ? btn.textContent : "";
        if (btn) { btn.disabled = true; btn.textContent = "Đang làm mới..."; }
        cauModalSetFieldHint("outline-actions", "Đang làm mới outline...");
        try {
            const res = await fetch("/content-ai/outline-refresh?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ outline }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(String(data.detail || data.message || "Làm mới outline thất bại."));
            if (ol && data.outline) ol.value = String(data.outline).trim();
            cauModalSaveDraft();
            cauModalSetFieldHint("outline-actions", "Đã làm mới outline bằng từ đồng nghĩa.");
        } catch (e) {
            cauModalSetFieldHint("outline-actions", String(e.message || e));
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = old || "Làm mới Outline"; }
        }
    };

    const cauModalOutlineDetailMessage = (detail) => {
        if (!detail) return "";
        if (typeof detail === "string") return detail;
        if (Array.isArray(detail)) {
            return detail.map((it) => {
                if (typeof it === "string") return it;
                if (it && typeof it === "object") return String(it.msg || it.message || JSON.stringify(it));
                return String(it);
            }).filter(Boolean).join("; ");
        }
        if (typeof detail === "object") {
            return String(detail.message || detail.msg || JSON.stringify(detail));
        }
        return String(detail);
    };

    const cauModalOutlineReference = async () => {
        const url = (byId("cauModalCompetitorUrl") && byId("cauModalCompetitorUrl").value.trim()) || "";
        if (!url) {
            cauModalSetFieldHint("competitor", "Nhập link đối thủ trước.");
            return;
        }
        const btn = byId("btnCauOutlineReference");
        const old = btn ? btn.textContent : "";
        if (btn) { btn.disabled = true; btn.textContent = "Đang lấy..."; }
        cauModalSetFieldHint("competitor", "Đang phân tích outline đối thủ...");
        try {
            const res = await fetch("/content-ai/outline-reference?ts=" + Date.now(), {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ competitor_url: url }),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(
                    cauModalOutlineDetailMessage(data.detail) ||
                    String(data.message || "Không lấy được outline đối thủ.")
                );
            }
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            const ol = byId("cauModalOutline");
            if (ol && data.outline) ol.value = String(data.outline).trim();
            cauModalSaveDraft();
            cauModalSwitchEditorTab("outline");
            cauModalSetFieldHint("competitor", "Đã lấy " + (data.count || 0) + " heading từ bài đối thủ.");
            cauModalSetFieldHint("outline_content", "Đã điền outline tham khảo — kiểm tra và chỉnh sửa trước khi viết bài.");
        } catch (e) {
            cauModalSetFieldHint("competitor", String(e.message || e));
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = old || "Outline tham khảo"; }
        }
    };

    const cauModalInitEditorTools = () => {
        document.querySelectorAll("[data-cau-editor-tab]").forEach((btn) => {
            btn.addEventListener("click", () => {
                cauModalSwitchEditorTab(btn.getAttribute("data-cau-editor-tab"));
            });
        });
        document.querySelectorAll("[data-cau-ai-field]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const field = btn.getAttribute("data-cau-ai-field");
                if (!field) return;
                const old = btn.textContent;
                btn.textContent = "Đang gợi ý...";
                btn.disabled = true;
                cauModalSetFieldHint(field, "");
                try {
                    const out = await cauModalFetchSuggestion(field);
                    const value = out.value || "";
                    if (value) {
                        cauModalApplyAiField(field, value);
                        cauModalSaveDraft();
                        if (field !== "outline_content") cauModalScoreLive().catch(() => {});
                        const creditNote = out.credits_charged > 0
                            ? " (đã trừ " + out.credits_charged + " credit)"
                            : "";
                        cauModalSetFieldHint(field, "Đã cập nhật gợi ý AI." + creditNote);
                    } else {
                        cauModalSetFieldHint(field, "AI không trả nội dung — thử lại.");
                    }
                } catch (e) {
                    const msg = String(e.message || e);
                    cauModalSetFieldHint(field, msg);
                } finally {
                    btn.textContent = old;
                    cauModalToggleAiButtons();
                }
            });
        });
        const btnOlRef = byId("btnCauOutlineReference");
        if (btnOlRef) btnOlRef.addEventListener("click", () => { cauModalOutlineReference().catch(() => {}); });
        const btnReplaceAll = byId("btnCauModalReplaceAll");
        if (btnReplaceAll) btnReplaceAll.addEventListener("click", () => { cauModalReplaceAllBrands(); });
        const btnRefreshOl = byId("btnCauModalRefreshOutline");
        if (btnRefreshOl) btnRefreshOl.addEventListener("click", () => { cauModalRefreshOutline().catch(() => {}); });
        const btnIlFind = byId("btnCauFindInternalLinks");
        if (btnIlFind) btnIlFind.addEventListener("click", () => { cauModalFindInternalLinks().catch(() => {}); });
        const btnIlApply = byId("btnCauApplyInternalLinks");
        if (btnIlApply) btnIlApply.addEventListener("click", () => { cauModalApplyInternalLinks().catch(() => {}); });
        const btnImg = byId("btnCauFindImages");
        if (btnImg) btnImg.addEventListener("click", () => { cauModalFindImages().catch(() => {}); });
        const kwEl = byId("cauModalKeyword");
        if (kwEl) kwEl.addEventListener("input", () => cauModalToggleAiButtons());
        cauModalToggleAiButtons();
        cauModalSwitchEditorTab("content");
    };

    const cauModalSetLoadState = (key, on, msg) => {
        if (key === "loadingPost" || key === "aiLoading" || key === "updateLoading") {
            cauModalState[key] = !!on;
        }
        const any = cauModalState.loadingPost || cauModalState.aiLoading || cauModalState.updateLoading;
        const box = byId("cauSeoModalLoading");
        const text = byId("cauSeoModalLoadingText");
        const body = byId("cauSeoModalBody");
        const footer = document.querySelector(".cau-seo-modal__footer");
        if (box) {
            if (any) box.removeAttribute("hidden");
            else box.setAttribute("hidden", "");
        }
        if (text) {
            text.textContent = msg ||
                (cauModalState.loadingPost ? "Đang tải bài viết từ WordPress…" :
                    cauModalState.aiLoading ? CAU_LOAD_LABELS.modalAnalyze :
                        cauModalState.updateLoading ? CAU_LOAD_LABELS.modalUpdate : "");
        }
        if (body) {
            body.style.opacity = any ? "0.55" : "";
            body.style.pointerEvents = any ? "none" : "";
        }
        if (footer) footer.style.pointerEvents = any ? "none" : "";
    };

    const cauModalReadForm = () => {
        cauModalSyncEditorToStore();
        return {
            title: (byId("cauModalTitle") && byId("cauModalTitle").value.trim()) || "",
            slug: (byId("cauModalSlug") && byId("cauModalSlug").value.trim()) || "",
            excerpt: (byId("cauModalExcerpt") && byId("cauModalExcerpt").value.trim()) || "",
            keyword: (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "",
            secondary_keywords: (byId("cauModalSecondaryKw") && byId("cauModalSecondaryKw").value.trim()) || "",
            outline: (byId("cauModalOutline") && byId("cauModalOutline").value.trim()) || "",
            replace_from: (byId("cauModalReplaceFrom") && byId("cauModalReplaceFrom").value) || "",
            replace_to: (byId("cauModalReplaceTo") && byId("cauModalReplaceTo").value) || "",
            content: cauModalGetContentHtml(),
            focus: (byId("cauModalFocus") && byId("cauModalFocus").value.trim()) || "",
        };
    };

    const cauModalReadDraft = () => {
        try {
            const raw = localStorage.getItem(CAU_MODAL_DRAFT_KEY());
            const data = raw ? JSON.parse(raw) : null;
            return data && typeof data === "object" ? data : null;
        } catch (_) {
            return null;
        }
    };

    const cauModalSaveDraft = () => {
        if (!cauModalState.open && !cauModalState.postUrl) return;
        const form = cauModalReadForm();
        const ed = cauEnsureBlockEditor();
        const patches = (cauAssistantUI && cauAssistantUI.applied) ? cauAssistantUI.applied.slice() : [];
        const payload = {
            sessionId: String(cauModalState.sessionId || ""),
            siteId: String(cauModalState.siteId || ""),
            postUrl: String(cauModalState.postUrl || ""),
            postStatus: String(cauModalState.postStatus || ""),
            postId: parseInt(cauModalState.postId || 0, 10) || 0,
            postType: String(cauModalState.postType || "post"),
            postTitle: (byId("cauSeoModalTitle") && byId("cauSeoModalTitle").textContent) || "",
            wpModified: String(cauModalState.wpModified || ""),
            originalContent: String(cauModalState.originalContent || ""),
            blocks: ed && ed.getBlocksPayload ? ed.getBlocksPayload() : [],
            patches: patches,
            form,
            // Only auto-reopen on F5 when modal was actually open.
            modalOpen: !!cauModalState.open,
            editorTab: String(cauModalState.editorTab || "content"),
            savedAt: new Date().toISOString(),
        };
        if (!payload.postUrl) return;
        try {
            localStorage.setItem(CAU_MODAL_DRAFT_KEY(), JSON.stringify(payload));
        } catch (_) {}
    };

    const cauModalSaveSessionExplicit = () => {
        if (!cauModalState.postUrl) {
            cauSetStatus("cauModalEditorHint", "err", "Chưa có bài để lưu phiên.");
            return;
        }
        cauModalState.open = true;
        cauModalSaveDraft();
        cauSetStatus("cauModalEditorHint", "ok", "Đã lưu phiên sửa trên SEOAuto (chưa cập nhật WordPress).");
    };

    const cauModalClearDraft = () => {
        try {
            localStorage.removeItem(CAU_MODAL_DRAFT_KEY());
        } catch (_) {}
    };

    const cauModalFillFormFromDraft = (draft, opts) => {
        const form = (draft && draft.form) || {};
        const titleEl = byId("cauModalTitle");
        const slugEl = byId("cauModalSlug");
        const excerptEl = byId("cauModalExcerpt");
        const kwEl = byId("cauModalKeyword");
        const secEl = byId("cauModalSecondaryKw");
        const focusEl = byId("cauModalFocus");
        if (titleEl) titleEl.value = String(form.title || "");
        if (slugEl) slugEl.value = String(form.slug || "");
        if (excerptEl) excerptEl.value = String(form.excerpt || "");
        if (kwEl) kwEl.value = String(form.keyword || "");
        if (secEl) secEl.value = String(form.secondary_keywords || "");
        const olEl = byId("cauModalOutline");
        if (olEl) olEl.value = String(form.outline || "");
        const repFrom = byId("cauModalReplaceFrom");
        const repTo = byId("cauModalReplaceTo");
        if (repFrom) repFrom.value = String(form.replace_from || "");
        if (repTo) repTo.value = String(form.replace_to || "");
        if (!(opts && opts.skipContent)) {
            cauModalSetContentHtml(form.content || "");
        }
        if (focusEl) focusEl.value = String(form.focus || "");
        cauModalToggleAiButtons();
    };

    const cauModalRestoreFromDraft = (draft) => {
        if (!draft || !draft.postUrl) return Promise.resolve();
        const modal = byId("cauSeoModal");
        if (!modal) return Promise.resolve();

        cauModalState.open = true;
        cauModalState.sessionId = String(draft.sessionId || "");
        cauModalState.siteId = String(draft.siteId || "");
        cauModalState.postUrl = String(draft.postUrl || "");
        cauModalState.postStatus = String(draft.postStatus || "");
        cauModalState.postId = parseInt(draft.postId || 0, 10) || 0;
        cauModalState.postType = String(draft.postType || "post");
        cauModalState.wpModified = String(draft.wpModified || "");
        cauModalState.originalContent = String(draft.originalContent || (draft.form && draft.form.content) || "");
        cauModalState.pendingProposal = null;
        cauModalState.suggestions = [];
        cauModalState.groupedSuggestions = [];
        cauModalState.internalLinkSuggestions = [];
        cauEnsureAssistantUI();
        cauModalRenderSuggestionGroups(null);
        cauModalRenderInternalLinks([]);

        modal.removeAttribute("hidden");
        document.body.classList.add("cau-seo-modal-open");

        const titleEl = byId("cauSeoModalTitle");
        const urlEl = byId("cauSeoModalUrl");
        const statusEl = byId("cauSeoModalStatus");
        if (titleEl) titleEl.textContent = String(draft.postTitle || "Sửa SEO bài viết");
        if (urlEl) {
            urlEl.href = draft.postUrl;
            urlEl.textContent = draft.postUrl;
        }
        if (statusEl) {
            statusEl.textContent = cauStatusLabel(cauModalState.postStatus);
            statusEl.className = "cau-status-badge " + cauStatusBadgeClass(cauModalState.postStatus);
        }

        cauModalFillFormFromDraft(draft, { skipContent: Array.isArray(draft.blocks) && draft.blocks.length > 0 });
        if (Array.isArray(draft.blocks) && draft.blocks.length) {
            const be = cauEnsureBlockEditor();
            if (be && be.loadBlocks) be.loadBlocks(draft.blocks);
        } else {
            cauModalSetContentHtml(String((draft.form && draft.form.content) || draft.originalContent || ""));
        }
        if (cauAssistantUI && Array.isArray(draft.patches)) {
            cauAssistantUI.applied = draft.patches.slice();
            cauAssistantUI.renderChanges();
        }
        cauModalSwitchEditorTab(String(draft.editorTab || "content"));
        cauSetStatus("cauModalEditorHint", "ok", "Đã khôi phục phiên chỉnh sửa đã lưu.");
        cauSetStatus("cauModalAssistantHint", "", "");
        return cauModalScoreLive().catch(() => {});
    };

    const cauModalPromptRestoreDraft = () => {
        let draft = null;
        try {
            const raw = localStorage.getItem(CAU_MODAL_DRAFT_KEY());
            if (raw && raw.length > 2000000) {
                cauSetStatus("select", "warn", "Phiên sửa quá lớn — mở lại bài từ danh sách thay vì khôi phục tự động.");
                return;
            }
            draft = raw ? JSON.parse(raw) : null;
        } catch (_) {
            draft = cauModalReadDraft();
        }
        if (!draft || !draft.postUrl) return;
        // Closed popup must stay closed after F5 — only reopen if user left it open.
        if (draft.modalOpen !== true) return;
        const run = () => { cauModalRestoreFromDraft(draft).catch(() => {}); };
        const idle = window.requestIdleCallback || function (cb) { return setTimeout(cb, 400); };
        idle(run, { timeout: 2500 });
    };

    const cauModalFillForm = (post) => {
        const titleEl = byId("cauModalTitle");
        const slugEl = byId("cauModalSlug");
        const excerptEl = byId("cauModalExcerpt");
        if (titleEl) titleEl.value = String((post && post.title) || "");
        if (slugEl) slugEl.value = String((post && post.slug) || "");
        if (excerptEl) excerptEl.value = cauDecodeHtmlField(post, "excerpt") || String((post && post.excerpt) || "");
        cauModalSetContentHtml(cauDecodeHtmlField(post, "content"));
        cauModalToggleAiButtons();
    };

    const cauModalRenderFactorGroups = (seo) => {
        const factors = (seo && seo.factors) || [];
        cauModalState.seoFactors = factors;
        cauModalState.lastSeo = seo || null;
        const failed = factors.filter((f) => String(f.status) === "failed");
        const warning = factors.filter((f) => String(f.status) === "warning");
        const passed = factors.filter((f) => String(f.status) === "passed");
        const modalFactorOpts = { showAiFix: true };
        cauRenderFactorList("cauModalTopIssues", failed.slice(0, 5), "Không có lỗi ưu tiên.", modalFactorOpts);
        cauRenderFactorList("cauModalFailedList", failed, "Không có yếu tố chưa đạt.", modalFactorOpts);
        cauRenderFactorList("cauModalWarningList", warning, "Không có cảnh báo.", modalFactorOpts);
        cauRenderFactorList("cauModalPassedList", passed, "Chưa có dữ liệu.");
        cauRenderSeoCounts("cauModalSeoCounts", seo ? {
            passed: passed.length,
            warning: warning.length,
            failed: failed.length,
            total: factors.length,
        } : null);
        const score = seo && seo.score != null ? seo.score : "—";
        const scoreEl = byId("cauModalScore");
        const headerScore = byId("cauSeoModalHeaderScore");
        if (scoreEl) scoreEl.textContent = String(score);
        if (headerScore) headerScore.textContent = String(score);
    };

    const cauModalDetectApplyType = (groupKey, text, factor) => {
        const lower = String(text || "").toLowerCase();
        if (groupKey === "titleMeta") {
            if (/meta|description|excerpt|mô tả/.test(lower)) return "excerpt";
            if (/slug/.test(lower)) return "slug";
            return "title";
        }
        if (groupKey === "heading" || groupKey === "content" || groupKey === "image") return "content";
        if (groupKey === "internalLink") return "internalLink";
        if (factor && /internal|link/i.test(String(factor.id || "") + String(factor.label || ""))) return "internalLink";
        return "content";
    };

    const cauModalBuildGroupedSuggestions = (data) => {
        const prop = (data && data.proposal) || cauModalState.pendingProposal || {};
        const failed = (data && data.failed_items) || [];
        const raw = [];
        if (prop.summary) raw.push({ text: String(prop.summary), source: "summary" });
        (prop.notes || []).forEach((note, idx) => {
            if (note) raw.push({ text: String(note), source: "note-" + idx });
        });
        ((data && data.suggestions) || cauModalState.suggestions || []).forEach((s, idx) => {
            if (s) raw.push({ text: String(s), source: "sug-" + idx });
        });
        failed.forEach((f, idx) => {
            const sug = String(f.suggestion || f.message || "").trim();
            if (sug) {
                raw.push({
                    text: (f.label || f.id || "SEO") + ": " + sug,
                    source: "factor-" + idx,
                    factor: f,
                });
            }
        });

        const seen = new Set();
        const groups = {};
        CAU_SUGGEST_GROUP_DEFS.forEach((g) => { groups[g.key] = []; });

        raw.forEach((item, idx) => {
            const text = String(item.text || "").trim();
            if (!text || seen.has(text)) return;
            seen.add(text);
            const groupKey = cauModalClassifyGroup(text, item.factor);
            groups[groupKey].push({
                id: item.source || ("item-" + idx),
                text,
                groupKey,
                applyType: cauModalDetectApplyType(groupKey, text, item.factor),
                factor: item.factor || null,
            });
        });

        return { groups, prop };
    };

    const cauModalExtractInternalLinks = (data) => {
        const prop = (data && data.proposal) || cauModalState.pendingProposal || {};
        const failed = (data && data.failed_items) || [];
        const items = [];
        const siteBase = String(cauModalState.postUrl || "").replace(/\/[^/]*$/, "/");
        const keyword = (byId("cauModalKeyword") && byId("cauModalKeyword").value.trim()) || "xem thêm";

        failed.forEach((f) => {
            const blob = String(f.label || "") + " " + String(f.id || "") + " " + String(f.suggestion || f.message || "");
            if (!/internal|liên kết|link nội/i.test(blob)) return;
            const urlMatch = blob.match(/https?:\/\/[^\s"'<>]+/i);
            const url = urlMatch ? urlMatch[0] : siteBase;
            items.push({
                id: "ilink-" + (f.id || items.length),
                url,
                anchor: keyword,
                text: String(f.suggestion || f.message || f.label || "Thêm internal link"),
            });
        });

        (prop.notes || []).forEach((note, idx) => {
            const text = String(note || "");
            if (!/internal|liên kết|link/i.test(text)) return;
            const urlMatch = text.match(/https?:\/\/[^\s"'<>]+/i);
            items.push({
                id: "ilink-note-" + idx,
                url: urlMatch ? urlMatch[0] : siteBase,
                anchor: keyword,
                text,
            });
        });

        const uniq = [];
        const seenUrl = new Set();
        items.forEach((it) => {
            const u = String(it.url || "").trim();
            if (!u || seenUrl.has(u)) return;
            seenUrl.add(u);
            uniq.push(it);
        });
        return uniq.slice(0, 5);
    };

    const cauModalApplySuggestion = (item) => {
        const prop = cauModalState.pendingProposal;
        if (!item) return;
        const type = item.applyType || "content";
        if (type === "title" && prop && prop.title) {
            const el = byId("cauModalTitle");
            if (el) el.value = String(prop.title);
        } else if (type === "excerpt" && prop) {
            const el = byId("cauModalExcerpt");
            if (el) el.value = String(prop.excerpt || prop.meta_description || "");
        } else if (type === "slug" && prop && prop.slug) {
            const el = byId("cauModalSlug");
            if (el) el.value = String(prop.slug);
        } else if (type === "content" && prop && prop.content) {
            cauModalSetContentHtml(prop.content);
        } else if (type === "internalLink") {
            const url = window.prompt("URL internal link", cauModalState.postUrl || "https://");
            if (!url) return;
            const anchor = window.prompt("Anchor text", (byId("cauModalKeyword") && byId("cauModalKeyword").value) || "xem thêm");
            if (!anchor) return;
            if (!cauModalInsertLinkHtml(url, anchor)) {
                cauSetStatus("cauModalAssistantHint", "err", "Link đã tồn tại trong nội dung.");
                return;
            }
        }
        cauSetStatus("cauModalAssistantHint", "ok", "Đã áp dụng gợi ý vào editor.");
        cauModalSaveDraft();
        cauModalScoreLive().catch(() => {});
    };

    const cauModalRenderSuggestionGroups = (data) => {
        const el = byId("cauModalSuggestionGroups");
        if (!el) return;
        const built = data ? cauModalBuildGroupedSuggestions(data) : { groups: {} };
        const groups = built.groups || {};
        cauModalState.groupedSuggestions = groups;
        const hasAny = CAU_SUGGEST_GROUP_DEFS.some((g) => (groups[g.key] || []).length);
        if (!hasAny) {
            el.innerHTML = '<p class="cau-factor-empty">Bấm «AI phân tích SEO» để nhận gợi ý theo nhóm.</p>';
            return;
        }
        el.innerHTML = CAU_SUGGEST_GROUP_DEFS.map((def) => {
            const items = (groups[def.key] || []).slice(0, 5);
            if (!items.length) return "";
            return (
                '<section class="cau-suggest-group">' +
                '<h5 class="cau-suggest-group__title">' + cauEsc(def.label) + "</h5>" +
                items.map((item) => (
                    '<div class="cau-suggest-item">' +
                    '<span class="cau-suggest-item__text">' + cauEsc(item.text) + "</span>" +
                    '<button type="button" class="cau-suggest-item__apply" data-cau-apply-sug="' + cauEsc(item.id) + '"' +
                    (cauModalState.pendingProposal ? "" : " disabled") + ">Áp dụng</button>" +
                    "</div>"
                )).join("") +
                "</section>"
            );
        }).join("");
        el.querySelectorAll("[data-cau-apply-sug]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-cau-apply-sug");
                let hit = null;
                CAU_SUGGEST_GROUP_DEFS.some((def) => {
                    hit = (groups[def.key] || []).find((x) => x.id === id);
                    return !!hit;
                });
                if (hit) cauModalApplySuggestion(hit);
            });
        });
    };

    const cauModalRenderInternalLinks = (links) => {
        const wrap = byId("cauModalInternalLinks");
        const list = byId("cauModalInternalLinksList");
        const items = (links || cauModalState.internalLinkSuggestions || []).slice(0, 5);
        cauModalState.internalLinkSuggestions = items;
        if (!wrap || !list) return;
        if (!items.length) {
            wrap.setAttribute("hidden", "");
            list.innerHTML = "";
            return;
        }
        wrap.removeAttribute("hidden");
        list.innerHTML = items.map((it) => {
            const exists = cauModalContentHasLink(it.url);
            return (
                '<li class="cau-internal-link-item">' +
                '<div class="cau-internal-link-item__meta">' + cauEsc(it.text) +
                "<small>" + cauEsc(it.url) + "</small></div>" +
                '<button type="button" class="cau-suggest-item__apply" data-cau-insert-link="' + cauEsc(it.id) + '"' +
                (exists ? " disabled title=\"Link đã có trong bài\"" : "") + ">Chèn link</button>" +
                "</li>"
            );
        }).join("");
        list.querySelectorAll("[data-cau-insert-link]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-cau-insert-link");
                const it = items.find((x) => x.id === id);
                if (!it) return;
                if (!cauModalInsertLinkHtml(it.url, it.anchor)) {
                    cauSetStatus("cauModalAssistantHint", "err", "Link đã tồn tại trong nội dung.");
                    return;
                }
                cauSetStatus("cauModalAssistantHint", "ok", "Đã chèn internal link.");
                cauModalSaveDraft();
                cauModalRenderInternalLinks(items);
                cauModalScoreLive().catch(() => {});
            });
        });
    };

    const cauModalApplyPatch = (patch) => {
        if (!patch || typeof patch !== "object") return;
        if (patch.title != null) {
            const el = byId("cauModalTitle");
            if (el) el.value = String(patch.title);
        }
        if (patch.meta_description != null) {
            const el = byId("cauModalExcerpt");
            if (el) el.value = String(patch.meta_description);
        }
        if (patch.slug != null) {
            const el = byId("cauModalSlug");
            if (el) el.value = String(patch.slug);
        }
        if (patch.content_html != null) {
            cauModalSetContentHtml(patch.content_html);
        }
    };

    const cauModalMergePatches = (reports) => {
        const merged = {};
        (reports || []).forEach((entry) => {
            const p = (entry && entry.patch) || {};
            ["title", "meta_description", "slug", "content_html"].forEach((k) => {
                if (p[k] != null) merged[k] = p[k];
            });
        });
        return merged;
    };

    const cauModalCloseFixDetail = () => {
        const panel = byId("cauFixDetailPanel");
        if (panel) panel.setAttribute("hidden", "");
    };

    const cauModalStripHtmlText = (html) => {
        const el = document.createElement("div");
        el.innerHTML = String(html || "");
        return (el.textContent || el.innerText || "").replace(/\s+/g, " ").trim();
    };

    const cauModalBuildFixDiffItems = (entry, pending) => {
        const rep = entry.change_report || {};
        const items = (rep.items || []).filter((it) => it && (it.old_text || it.new_text || it.old_html || it.new_html));
        if (items.length) return items;

        const snapB = rep.factor_snap_before || entry.factor_snap_before || pending.beforeSnapshot || {};
        const snapA = rep.factor_snap_after || entry.factor_snap_after || {};
        const patch = entry.patch || {};
        const built = [];
        const rows = [
            ["title", "Tiêu đề", snapB.title, snapA.title || patch.title],
            ["meta_description", "Meta description", snapB.meta_description, snapA.meta_description || patch.meta_description],
            ["slug", "Slug", snapB.slug, snapA.slug || patch.slug],
            ["content_html", "Nội dung", snapB.content_html, snapA.content_html || patch.content_html],
        ];
        rows.forEach(([field, label, oldVal, newVal]) => {
            const oldRaw = String(oldVal || "");
            const newRaw = String(newVal || "");
            if (!newRaw || oldRaw === newRaw) return;
            const isContent = field === "content_html";
            const oldText = isContent ? cauModalStripHtmlText(oldRaw).slice(0, 1200) : oldRaw.slice(0, 500);
            const newText = isContent ? cauModalStripHtmlText(newRaw).slice(0, 1200) : newRaw.slice(0, 500);
            built.push({
                field: field,
                location: label,
                old_text: oldText || "—",
                new_text: newText || "—",
                old_html: "",
                new_html: "",
                old_raw_html: isContent ? oldRaw : "",
                new_raw_html: isContent ? newRaw : "",
                is_snippet: isContent,
            });
        });
        if (!built.length && rep.error) {
            built.push({
                field: "info",
                location: rep.location || "Thông tin",
                old_text: String(rep.summary || rep.reason || "—").slice(0, 500),
                new_text: String(rep.error || "Không sửa được").slice(0, 500),
            });
        }
        return built;
    };

    const cauModalRenderFixDiffBlock = (it) => {
        const loc = cauEsc(it.position || it.location || "Nội dung");
        const conf = it.confidence != null ? " · tin cậy " + it.confidence + "%" : "";
        const lowConf = it.confidence != null && parseInt(it.confidence, 10) < 80
            ? '<div class="cau-fix-detail__warn">Cần kiểm tra lại trước khi áp dụng (tin cậy &lt; 80%).</div>'
            : "";
        const reasonLine = it.reason
            ? '<div class="cau-fix-detail__item-reason"><strong>Lý do:</strong> ' + cauEsc(it.reason) + "</div>"
            : "";
        const snippetNote = it.is_snippet ? " · chỉ hiển thị đoạn liên quan" : (
            it.preview_full_content ? " · hiển thị toàn bộ nội dung" : ""
        );
        const isContent = it.field === "content_html";
        const oldRawHtml = it.old_raw_html || "";
        const newRawHtml = it.new_raw_html || "";
        const richClass = it.preview_full_content ? " cau-fix-detail__html-rich--full" : "";
        let oldBlock;
        let newBlock;
        if (isContent && oldRawHtml) {
            oldBlock =
                '<div class="cau-fix-detail__html-rich' + richClass + '">' + oldRawHtml + "</div>" +
                '<pre class="cau-fix-detail__plain">' + cauEsc(it.old_text || cauModalStripHtmlText(oldRawHtml) || "—") + "</pre>";
        } else if (it.old_html) {
            oldBlock = '<div class="cau-fix-detail__html">' + it.old_html + "</div>";
        } else {
            oldBlock = "<pre>" + cauEsc(it.old_text || "—") + "</pre>";
        }
        if (isContent && newRawHtml) {
            newBlock =
                '<div class="cau-fix-detail__html-rich' + richClass + '">' + newRawHtml + "</div>" +
                '<pre class="cau-fix-detail__plain">' + cauEsc(it.new_text || cauModalStripHtmlText(newRawHtml) || "—") + "</pre>";
        } else if (it.new_html) {
            newBlock = '<div class="cau-fix-detail__html">' + it.new_html + "</div>";
        } else {
            newBlock = "<pre>" + cauEsc(it.new_text || "—") + "</pre>";
        }
        return (
            '<div class="cau-fix-detail__item">' +
            '<div class="cau-fix-detail__item-meta">Vị trí: ' + loc + snippetNote + conf + "</div>" +
            reasonLine +
            lowConf +
            '<div class="cau-fix-detail__cols">' +
            '<div class="cau-fix-detail__col"><label>Bản cũ</label>' + oldBlock + "</div>" +
            '<div class="cau-fix-detail__col"><label>Bản mới</label>' + newBlock + "</div>" +
            "</div></div>"
        );
    };

    const cauModalRenderFixDetail = () => {
        const pending = cauModalState.pendingFix;
        const summaryEl = byId("cauFixDetailSummary");
        const bodyEl = byId("cauFixDetailBody");
        const applyBtn = byId("btnCauFixApply");
        if (!summaryEl || !bodyEl || !pending) return;

        const reports = pending.reports || [];
        const scoreBefore = pending.scoreBefore;
        const scoreAfter = pending.scoreAfter;
        const delta = (scoreBefore != null && scoreAfter != null) ? (scoreAfter - scoreBefore) : null;
        summaryEl.innerHTML =
            '<div class="cau-fix-detail__score">' +
            "<span><strong>Lỗi đã xử lý:</strong> " + reports.length + "</span>" +
            (scoreBefore != null ? "<span>Điểm trước: <strong>" + scoreBefore + "</strong>/100</span>" : "") +
            (scoreAfter != null ? "<span>Điểm sau (dự kiến): <strong>" + scoreAfter + "</strong>/100</span>" : "") +
            (delta != null ? "<span>Chênh lệch: <strong>" + (delta >= 0 ? "+" : "") + delta + "</strong></span>" : "") +
            "</div>" +
            "<p>AI chỉ đề xuất thay đổi — chưa áp dụng vào form. Kiểm tra bản cũ / bản mới bên dưới.</p>";

        bodyEl.innerHTML = reports.map((entry, idx) => {
            const rep = entry.change_report || {};
            const status = String(rep.status || "failed");
            const statusLabel = rep.status_label || CAU_FIX_STATUS_LABELS[status] || status;
            const items = cauModalBuildFixDiffItems(entry, pending);
            const itemsHtml = items.length
                ? items.map((it) => cauModalRenderFixDiffBlock(it)).join("")
                : '<div class="cau-fix-detail__item"><p class="cau-factor-empty">Không có thay đổi nội dung cụ thể.</p></div>';

            const sb = rep.score_before != null ? rep.score_before : "";
            const sa = rep.score_after != null ? rep.score_after : "";
            const scoreLine = (sb !== "" || sa !== "")
                ? " · Điểm " + sb + "→" + sa
                : "";

            const reviewWarn = rep.needs_review && rep.validation_warning
                ? '<div class="cau-fix-detail__warn">' + cauEsc(rep.validation_warning) + "</div>"
                : "";

            const articleTypeLine = rep.article_type_label
                ? (
                    '<div class="cau-fix-detail__context">' +
                    "<strong>Loại bài nhận diện:</strong> " + cauEsc(rep.article_type_label) +
                    (rep.article_type_reason ? " — " + cauEsc(rep.article_type_reason) : "") +
                    "</div>"
                )
                : "";

            return (
                '<section class="cau-fix-detail__report">' +
                '<div class="cau-fix-detail__report-head">' +
                "<div><strong>" + cauEsc(rep.factor_label || ("Lỗi #" + (idx + 1))) + "</strong>" +
                (rep.location ? " · " + cauEsc(rep.location) : "") +
                scoreLine +
                "</div>" +
                '<span class="cau-fix-detail__status cau-fix-detail__status--' + cauEsc(status) + '">' +
                cauEsc(statusLabel) +
                "</span></div>" +
                articleTypeLine +
                (rep.reason ? '<div class="cau-fix-detail__reason"><strong>Lý do:</strong> ' + cauEsc(rep.reason) + "</div>" : "") +
                reviewWarn +
                itemsHtml +
                "</section>"
            );
        }).join("");

        const hasPatch = pending.patch && Object.keys(pending.patch).length > 0;
        const validationRejected = !!(pending.validationRejected || reports.some((r) => (r.change_report || {}).validation_rejected));
        if (applyBtn) {
            applyBtn.disabled = !hasPatch || validationRejected;
            if (validationRejected) {
                applyBtn.textContent = "Nội dung không hợp lệ — không thể áp dụng";
            } else {
                applyBtn.textContent = hasPatch ? "Áp dụng thay đổi" : "Không có thay đổi để áp dụng";
            }
        }
    };

    const cauModalOpenFixDetail = () => {
        const panel = byId("cauFixDetailPanel");
        if (!panel) return;
        cauModalRenderFixDetail();
        panel.removeAttribute("hidden");
    };

    const cauModalQueueFixPreview = (data, opts) => {
        const options = opts || {};
        const report = data.change_report || {};
        const patch = data.patch || {};
        const beforeSnap = data.before_snapshot || {};
        const batchReports = options.batch ? (data.change_reports || []) : [];

        if (!cauModalState.pendingFix) {
            cauModalState.pendingFix = {
                beforeSnapshot: beforeSnap,
                reports: [],
                patch: {},
                scoreBefore: null,
                scoreAfter: null,
            };
        }
        const pending = cauModalState.pendingFix;
        if (!pending.reports.length && beforeSnap && Object.keys(beforeSnap).length) {
            pending.beforeSnapshot = beforeSnap;
        }
        if (pending.scoreBefore == null) {
            const sb = (data.seo_before && data.seo_before.score != null)
                ? parseInt(data.seo_before.score, 10)
                : (report.score_before != null ? parseInt(report.score_before, 10) : null);
            pending.scoreBefore = sb;
        }
        const sa = (data.seo_after && data.seo_after.score != null)
            ? parseInt(data.seo_after.score, 10)
            : (report.score_after != null ? parseInt(report.score_after, 10) : pending.scoreAfter);
        pending.scoreAfter = sa;

        const entries = batchReports.length
            ? batchReports.map((rep) => {
                const sub = (data.results || []).find((r) => ((r.change_report || {}).factor_id) === rep.factor_id) || {};
                return {
                    factor_id: rep.factor_id || "",
                    change_report: rep,
                    patch: sub.patch || patch,
                    factor_snap_before: rep.factor_snap_before || sub.factor_snap_before || beforeSnap,
                    factor_snap_after: rep.factor_snap_after || sub.factor_snap_after || {},
                    seo_before: data.seo_before || null,
                    seo_after: data.seo_after || null,
                };
            })
            : [{
                factor_id: report.factor_id || data.factor_id || "",
                change_report: report,
                patch: patch,
                factor_snap_before: report.factor_snap_before || beforeSnap,
                factor_snap_after: report.factor_snap_after || data.factor_snap_after || {},
                seo_before: data.seo_before || null,
                seo_after: data.seo_after || null,
            }];

        entries.forEach((entry) => {
            if (!entry.factor_id) return;
            const idx = pending.reports.findIndex((r) => r.factor_id === entry.factor_id);
            if (idx >= 0) pending.reports[idx] = entry;
            else pending.reports.push(entry);
        });
        pending.patch = cauModalMergePatches(pending.reports);
        pending.validationRejected = !!(
            data.validation_rejected
            || (report && report.validation_rejected)
            || batchReports.some((r) => r.validation_rejected)
        );
        cauModalOpenFixDetail();
    };

    const cauModalClearPendingFix = () => {
        cauModalState.pendingFix = null;
        cauModalCloseFixDetail();
    };

    const cauModalApplyPendingFix = () => {
        const pending = cauModalState.pendingFix;
        if (!pending || !pending.patch || !Object.keys(pending.patch).length) {
            return Promise.resolve();
        }
        const patch = pending.patch;
        const reports = pending.reports || [];
        const scoreBefore = pending.scoreBefore;
        cauModalApplyPatch(patch);
        return cauModalScoreLive().then((scoreData) => {
            const seo = (scoreData && scoreData.seo) || {};
            const scoreAfter = seo.score != null ? parseInt(seo.score, 10) : pending.scoreAfter;
            const factorIds = reports.map((r) => r.factor_id).filter(Boolean);
            const payload = {
                session_id: cauModalState.sessionId,
                post_url: cauModalState.postUrl || "",
                factor_ids: factorIds,
                change_reports: reports.map((r) => r.change_report).filter(Boolean),
                patch,
                seo_before_score: scoreBefore,
                seo_after_score: scoreAfter,
            };
            return cauApi("POST", "/content-ai/auto-update/modal/fix-factor/apply", payload)
                .then(() => {
                    cauSetStatus("cauModalAssistantHint", "ok", "Đã áp dụng thay đổi AI vào form và chấm lại SEO.");
                    cauModalClearPendingFix();
                    cauLoadHistory();
                    return scoreData;
                });
        }).catch((e) => {
            cauSetStatus("cauModalAssistantHint", "warn", "Đã áp dụng vào form nhưng ghi log thất bại: " + cauFormatApiError(e, "apply"));
            cauModalClearPendingFix();
            throw e;
        });
    };

    const cauModalUndoPendingFix = () => {
        cauModalClearPendingFix();
        cauSetStatus("cauModalAssistantHint", "", "Đã hoàn tác — giữ nguyên nội dung form hiện tại.");
    };

        const cauModalFixFactor = (factorId) => {
        if (!factorId || cauModalState.fixingFactorIds[factorId]) return Promise.resolve();
        if (cauAiFixBlocked()) {
            cauSetStatus("cauModalAssistantHint", "err", cauAiFixBlockMessage());
            return Promise.resolve();
        }
        const form = cauModalReadForm();
        const runFix = () => {
        cauModalState.fixingFactorIds[factorId] = true;
        if (cauModalState.lastSeo) cauModalRenderFactorGroups(cauModalState.lastSeo);
        return cauApi("POST", "/content-ai/auto-update/modal/fix-factor", {
            factor_id: factorId,
            post_id: cauModalState.postId || null,
            post_url: cauModalState.postUrl || "",
            title: form.title,
            meta_description: form.excerpt,
            content_html: form.content,
            primary_keyword: form.keyword,
            slug: form.slug,
            secondary_keywords: form.secondary_keywords,
            category_name: cauSelectedCategoryName(),
        }).then((data) => {
            cauModalQueueFixPreview(data);
            cauLoadQuota();
            const rep = data.change_report || {};
            const cacheNote = data.from_cache ? " (từ cache)" : "";
            const srcNote = data.source === "rule" ? " [kiểm tra]" : (data.source === "llm" ? " [LLM]" : "");
            const creditNote = (data.credit && data.credit.credit_charged)
                ? " · đã trừ " + (data.credit.credit_cost || 0) + " credit"
                : "";
            const msg = (rep.reason || data.message || "Đã tạo bản sửa — xem chi tiết trước khi áp dụng.") + srcNote + cacheNote + creditNote;
            cauSetStatus("cauModalAssistantHint", data.success ? "ok" : "warn", msg);
            return data;
        }).catch((e) => {
            cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "fix"));
            throw e;
        }).finally(() => {
            delete cauModalState.fixingFactorIds[factorId];
            if (cauModalState.lastSeo) cauModalRenderFactorGroups(cauModalState.lastSeo);
        });
        };
        if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
            return window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.cauSeoFix).then((ok) => (ok ? runFix() : Promise.resolve()));
        }
        return runFix();
    };

    const cauModalBuildContentAiPayload = (form) => ({
        post_id: cauModalState.postId || null,
        post_url: cauModalState.postUrl || "",
        title: form.title,
        meta_description: form.excerpt,
        content_html: form.content,
        primary_keyword: form.keyword,
        slug: form.slug,
        secondary_keywords: form.secondary_keywords,
        outline_content: form.outline,
    });

    const cauModalContentAiCreditNote = (credit) => {
        if (!credit || !credit.credit_charged) return "";
        return " · đã trừ " + (credit.credit_cost || 0) + " credit";
    };

    const cauModalClearRewriteFieldHints = () => {
        ["title", "meta_description", "secondary_keywords", "outline_content"].forEach((f) => {
            cauModalSetFieldHint(f, "");
        });
    };

    const cauModalValidateRewriteBrief = (form) => {
        const rules = [
            {
                ok: () => !!(form.title && form.title.trim()),
                msg: "Hãy nhập Title để tiến hành viết bài.",
                hint: "title",
                focus: "cauModalTitle",
            },
            {
                ok: () => !!(form.keyword && form.keyword.trim()),
                msg: "Hãy nhập Focus keyword (từ khóa chính) để tiến hành viết bài.",
                focus: "cauModalKeyword",
            },
            {
                ok: () => !!(form.secondary_keywords && form.secondary_keywords.trim()),
                msg: "Hãy nhập từ khóa phụ để tiến hành viết bài.",
                hint: "secondary_keywords",
                focus: "cauModalSecondaryKw",
            },
            {
                ok: () => !!(form.slug && form.slug.trim()),
                msg: "Hãy nhập Slug để tiến hành viết bài.",
                focus: "cauModalSlug",
            },
            {
                ok: () => !!(form.excerpt && form.excerpt.trim()),
                msg: "Hãy nhập Meta description để tiến hành viết bài.",
                hint: "meta_description",
                focus: "cauModalExcerpt",
            },
            {
                ok: () => {
                    const ol = String(form.outline || "").trim();
                    if (!ol) return false;
                    return /(^|\n)\s*#{1,3}\s+\S/m.test(ol);
                },
                msg: () => {
                    const ol = String(form.outline || "").trim();
                    if (!ol) return "Hãy nhập outline content để tiến hành viết bài.";
                    return "Outline cần có ít nhất 1 heading (ví dụ: ## Tiêu đề mục).";
                },
                hint: "outline_content",
                tab: "outline",
                focus: "cauModalOutline",
            },
        ];
        for (let i = 0; i < rules.length; i++) {
            const rule = rules[i];
            if (rule.ok()) continue;
            const msg = typeof rule.msg === "function" ? rule.msg() : rule.msg;
            cauModalClearRewriteFieldHints();
            if (rule.hint) cauModalSetFieldHint(rule.hint, msg);
            if (rule.tab) cauModalSwitchEditorTab(rule.tab);
            const focusEl = byId(rule.focus);
            if (focusEl && typeof focusEl.focus === "function") focusEl.focus();
            cauSetStatus("cauModalAssistantHint", "err", msg);
            cauSetStatus("cauModalEditorHint", "err", msg);
            return { ok: false, message: msg };
        }
        cauModalClearRewriteFieldHints();
        return { ok: true };
    };

    const cauModalRewriteContent = () => {
        const form = cauModalReadForm();
        const valid = cauModalValidateRewriteBrief(form);
        if (!valid.ok) return Promise.resolve();
        if (cauModalState.aiLoading) return Promise.resolve();
        const runRewrite = () => {
        cauModalState.pendingFix = null;
        const wrap = byId("cauModalHeadingsInputWrap");
        if (wrap) wrap.setAttribute("hidden", "");
        cauModalSetLoadState("aiLoading", true, "Đang viết lại content…");
        return cauApi("POST", "/content-ai/auto-update/modal/rewrite-content", cauModalBuildContentAiPayload(form))
            .then((data) => {
                cauModalQueueFixPreview(data);
                cauLoadQuota();
                const msg = (data.message || "Đã viết lại content — xem bản cũ / bản mới.") +
                    cauModalContentAiCreditNote(data.credit);
                cauSetStatus("cauModalAssistantHint", "ok", msg);
            })
            .catch((e) => {
                cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "rewrite"));
                throw e;
            })
            .finally(() => cauModalSetLoadState("aiLoading", false));
        };
        if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
            return window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.cauRewrite).then((ok) => (ok ? runRewrite() : Promise.resolve()));
        }
        return runRewrite();
    };

    const cauModalShowAppendHeadingsInput = () => {
        const wrap = byId("cauModalHeadingsInputWrap");
        if (!wrap) return;
        wrap.removeAttribute("hidden");
        const ta = byId("cauModalNewHeadings");
        if (ta) ta.focus();
        cauSetStatus(
            "cauModalAssistantHint",
            "",
            "Nhập heading (tùy chọn) hoặc để trống để AI tự đề xuất — rồi bấm «Bắt đầu viết»."
        );
    };

    const cauModalHideAppendHeadingsInput = () => {
        const wrap = byId("cauModalHeadingsInputWrap");
        if (wrap) wrap.setAttribute("hidden", "");
    };

    const cauModalRunAppendHeadings = () => {
        const form = cauModalReadForm();
        const raw = (byId("cauModalNewHeadings") && byId("cauModalNewHeadings").value) || "";
        const headings = raw.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
        const autoGenerate = !headings.length;
        if (!form.keyword.trim()) {
            cauSetStatus("cauModalAssistantHint", "err", "Nhập Focus keyword trước.");
            return Promise.resolve();
        }
        if (!String(form.content || "").trim()) {
            cauSetStatus("cauModalAssistantHint", "err", "Cần nội dung bài viết để AI phân tích.");
            return Promise.resolve();
        }
        if (cauModalState.aiLoading) return Promise.resolve();
        const runAppend = () => {
        cauModalState.pendingFix = null;
        cauModalSetLoadState(
            "aiLoading",
            true,
            autoGenerate ? "AI đang phân tích bài và đề xuất heading mới…" : "Đang viết thêm nội dung…"
        );
        const payload = Object.assign({}, cauModalBuildContentAiPayload(form), {
            headings: headings,
            auto_generate_heading: autoGenerate,
        });
        return cauApi("POST", "/content-ai/auto-update/modal/append-headings", payload)
            .then((data) => {
                cauModalHideAppendHeadingsInput();
                cauModalQueueFixPreview(data);
                cauLoadQuota();
                const msg = (data.message || (autoGenerate
                    ? "AI đã tự thêm heading — xem bản cũ / bản mới."
                    : "Đã viết thêm section — xem bản cũ / bản mới.")) +
                    cauModalContentAiCreditNote(data.credit);
                cauSetStatus("cauModalAssistantHint", "ok", msg);
            })
            .catch((e) => {
                cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "append"));
                throw e;
            })
            .finally(() => cauModalSetLoadState("aiLoading", false));
        };
        if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
            return window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.cauAppend).then((ok) => (ok ? runAppend() : Promise.resolve()));
        }
        return runAppend();
    };

    const cauModalFixAllFactors = () => {
        const factors = cauModalState.seoFactors || [];
        const ids = factors
            .filter((f) => f.status === "failed" || f.status === "warning")
            .map((f) => String(f.id || ""))
            .filter(Boolean);
        if (!ids.length) {
            cauSetStatus("cauModalAssistantHint", "", "Không có lỗi cần sửa.");
            return Promise.resolve();
        }
        if (cauModalState.aiLoading) return Promise.resolve();
        if (cauAiFixBlocked()) {
            cauSetStatus("cauModalAssistantHint", "err", cauAiFixBlockMessage());
            return Promise.resolve();
        }
        const form = cauModalReadForm();
        ids.forEach((id) => { cauModalState.fixingFactorIds[id] = true; });
        if (cauModalState.lastSeo) cauModalRenderFactorGroups(cauModalState.lastSeo);
        cauModalSetLoadState("aiLoading", true, "Đang sửa " + ids.length + " lỗi…");
        return cauApi("POST", "/content-ai/auto-update/modal/fix-factors", {
            factor_ids: ids,
            post_id: cauModalState.postId || null,
            post_url: cauModalState.postUrl || "",
            title: form.title,
            meta_description: form.excerpt,
            content_html: form.content,
            primary_keyword: form.keyword,
            slug: form.slug,
            secondary_keywords: form.secondary_keywords,
            category_name: cauSelectedCategoryName(),
        }).then((data) => {
            cauModalQueueFixPreview(data, { batch: true });
            cauLoadQuota();
            const charged = data.credit && data.credit.charged_total ? (" · đã trừ " + data.credit.charged_total + " credit") : "";
            cauSetStatus("cauModalAssistantHint", "ok", (data.message || "Đã xử lý — xem chi tiết trước khi áp dụng.") + charged);
            return data;
        }).catch((e) => {
            cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "fix"));
            throw e;
        }).finally(() => {
            ids.forEach((id) => { delete cauModalState.fixingFactorIds[id]; });
            if (cauModalState.lastSeo) cauModalRenderFactorGroups(cauModalState.lastSeo);
            cauModalSetLoadState("aiLoading", false);
        });
    };

    const cauModalScoreLive = () => {
        const form = cauModalReadForm();
        return cauApi("POST", "/content-ai/auto-update/modal/score", {
            title: form.title,
            meta_description: form.excerpt,
            content_html: form.content,
            primary_keyword: form.keyword,
            slug: form.slug,
            secondary_keywords: form.secondary_keywords,
            post_url: cauModalState.postUrl || "",
        }).then((data) => {
            cauModalRenderFactorGroups(data.seo || {});
            const score = data.seo && data.seo.score != null ? parseInt(data.seo.score, 10) : null;
            if (score != null && cauModalState.postId) {
                cauUpsertScanScore({
                    post_id: cauModalState.postId,
                    id: cauModalState.postId,
                    post_type: cauModalState.postType,
                    type: cauModalState.postType,
                    link: cauModalState.postUrl,
                    url: cauModalState.postUrl,
                    title: form.title,
                    slug: form.slug,
                    status: cauModalState.postStatus,
                }, score);
            }
            return data;
        });
    };

    const cauModalClose = () => {
        const modal = byId("cauSeoModal");
        if (modal) modal.setAttribute("hidden", "");
        document.body.classList.remove("cau-seo-modal-open");
        const hadUrl = !!cauModalState.postUrl;
        cauModalState.open = false;
        cauModalState.loadingPost = false;
        cauModalState.aiLoading = false;
        cauModalState.updateLoading = false;
        cauModalState.pendingProposal = null;
        cauModalClearPendingFix();
        // Persist edits but mark modalOpen=false so F5 does not reopen the popup.
        if (hadUrl) cauModalSaveDraft();
        if (cauAssistantUI) cauAssistantUI.resetSession();
        const success = byId("cauSeoModalSuccess");
        if (success) success.setAttribute("hidden", "");
        const preview = byId("cauModalPreviewBox");
        if (preview) preview.setAttribute("hidden", "");
        const adv = byId("cauModalAdvanced");
        if (adv) adv.removeAttribute("open");
        cauModalSetLoadState("loadingPost", false);
    };

    const cauModalOpen = (post) => {
        const modal = byId("cauSeoModal");
        if (!modal) return Promise.resolve();
        const url = String((post && post.link) || "").trim();
        if (!url) {
            cauSetStatus("scan", "err", "Bài viết không có URL.");
            return Promise.resolve();
        }
        const siteId = (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value) || cauState.siteId;
        if (!siteId) {
            cauSetStatus("scan", "err", "Chọn website trước khi sửa SEO.");
            return Promise.resolve();
        }

        cauModalState.open = true;
        cauModalState.siteId = siteId;
        cauModalState.postUrl = url;
        cauModalState.postStatus = String((post && post.status) || "");
        cauModalState.postId = parseInt((post && (post.post_id || post.id)) || 0, 10);
        cauModalState.postType = String((post && (post.post_type || post.type)) || "post");
        cauModalState.pendingProposal = null;
        cauModalState.suggestions = [];
        cauModalState.groupedSuggestions = [];
        cauModalState.internalLinkSuggestions = [];
        cauModalRenderSuggestionGroups(null);
        cauModalRenderInternalLinks([]);

        modal.removeAttribute("hidden");
        document.body.classList.add("cau-seo-modal-open");

        const titleEl = byId("cauSeoModalTitle");
        const urlEl = byId("cauSeoModalUrl");
        const statusEl = byId("cauSeoModalStatus");
        if (titleEl) titleEl.textContent = String((post && post.title) || "Sửa SEO bài viết");
        if (urlEl) {
            urlEl.href = url;
            urlEl.textContent = url;
        }
        if (statusEl) {
            statusEl.textContent = cauStatusLabel(cauModalState.postStatus);
            statusEl.className = "cau-status-badge " + cauStatusBadgeClass(cauModalState.postStatus);
        }

        const existingDraft = cauModalReadDraft();
        if (existingDraft && existingDraft.postUrl && existingDraft.postUrl !== url) {
            cauModalClearDraft();
        }

        cauSetStatus("cauModalEditorHint", "", "");
        cauSetStatus("cauModalAssistantHint", "", "");
        cauModalSetLoadState("loadingPost", true, "Đang tải bài viết từ WordPress…");

        const fetchBody = {
            site_id: siteId,
            url,
            wp_id: cauModalState.postId > 0 ? cauModalState.postId : undefined,
            post_type: cauModalState.postType || undefined,
            rest_base: String((post && post.rest_base) || "").trim() || undefined,
        };
        return cauApi("POST", "/content-ai/auto-update/fetch-url", fetchBody)
            .then((data) => {
                const p = data.post || {};
                cauModalState.sessionId = (data.session && data.session.id) || "";
                if (p.wp_id) cauModalState.postId = parseInt(p.wp_id, 10) || cauModalState.postId;
                if (p.post_type) cauModalState.postType = String(p.post_type);
                if (p.status) cauModalState.postStatus = String(p.status);
                cauModalState.originalContent = cauDecodeHtmlField(p, "content");
                cauModalState.wpModified = cauPickWpModified(p);
                cauModalFillForm(p);
                cauModalRenderFactorGroups(data.seo_before || {});
                cauModalState.pendingProposal = null;
                const beforeScore = data.seo_before && data.seo_before.score != null
                    ? parseInt(data.seo_before.score, 10) : null;
                if (beforeScore != null) {
                    cauUpsertScanScore({
                        post_id: cauModalState.postId || p.wp_id,
                        id: cauModalState.postId || p.wp_id,
                        post_type: p.post_type || cauModalState.postType,
                        type: p.post_type || cauModalState.postType,
                        link: p.link || url,
                        url: p.link || url,
                        title: p.title,
                        slug: p.slug,
                        status: p.status,
                        modified: p.modified,
                    }, beforeScore);
                }
                cauModalState.suggestions = [];
                cauModalRenderSuggestionGroups(null);
                cauModalRenderInternalLinks([]);
                cauModalSaveDraft();
            })
            .catch((e) => {
                // Keep modal open so user can see the error and retry / close manually.
                cauSetStatus("cauModalEditorHint", "err", cauFormatApiError(e, "fetch"));
            })
            .finally(() => cauModalSetLoadState("loadingPost", false));
    };

    const cauModalAnalyze = () => {
        if (!cauModalState.sessionId) {
            cauSetStatus("cauModalAssistantHint", "err", "Chưa có session — tải lại bài.");
            return Promise.resolve();
        }
        const form = cauModalReadForm();
        cauModalSetLoadState("aiLoading", true, CAU_LOAD_LABELS.modalAnalyze);
        cauBeginLoad("modalAnalyze");
        return cauApi("POST", "/content-ai/auto-update/modal/analyze", {
            session_id: cauModalState.sessionId,
            title: form.title,
            content: form.content,
            excerpt: form.excerpt,
            keyword: form.keyword,
            focus: form.focus,
            slug: form.slug,
        }).then((data) => {
            cauModalState.pendingProposal = data.proposal || null;
            cauModalState.suggestions = data.suggestions || [];
            cauModalRenderSuggestionGroups(data);
            cauModalRenderInternalLinks(cauModalExtractInternalLinks(data));
            if (data.seo_after) cauModalRenderFactorGroups(data.seo_after);
            const warns = (data.warnings || []).length
                ? (" Cảnh báo markup: " + data.warnings.join("; "))
                : "";
            cauSetStatus(
                "cauModalAssistantHint",
                "ok",
                "AI đã phân tích xong. Bấm «Áp dụng» từng gợi ý khi cần (chưa lưu lên web)." + warns
            );
        }).catch((e) => {
            cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "analyze"));
        }).finally(() => {
            cauModalSetLoadState("aiLoading", false);
            cauEndLoad("modalAnalyze");
        });
    };

    const cauModalPreview = () => {
        const form = cauModalReadForm();
        const box = byId("cauModalPreviewBox");
        const frame = byId("cauModalPreviewFrame");
        if (!box || !frame) return;
        const html = "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>" +
            cauEsc(form.title) + "</title></head><body>" + form.content + "</body></html>";
        frame.srcdoc = html;
        box.removeAttribute("hidden");
    };

    const cauModalUndoEditor = () => {
        const be = cauEnsureBlockEditor();
        if (be && typeof be.undo === "function") {
            be.undo();
            cauSetStatus("cauModalEditorHint", "ok", "Đã hoàn tác một bước trên editor.");
            return;
        }
        if (cauAssistantUI && cauAssistantUI.applied && cauAssistantUI.applied.length) {
            cauAssistantUI.undoAll();
            return;
        }
        cauSetStatus("cauModalEditorHint", "err", "Không còn bước để hoàn tác.");
    };

    const cauModalViewChanges = () => {
        cauModalSwitchEditorTab("changes");
        if (cauAssistantUI) cauAssistantUI.renderChanges();
        const oldHtml = cauModalState.originalContent || "";
        const newHtml = cauModalGetContentHtml();
        const box = byId("cauHint-changes");
        if (box) {
            box.textContent = oldHtml === newHtml
                ? "Chưa có thay đổi so với bản tải từ WordPress."
                : "Đang xem thay đổi phiên hiện tại (chưa cập nhật WordPress).";
        }
    };

    const cauModalCloseWpConfirm = () => {
        const m = byId("cauWpConfirmModal");
        if (m) m.setAttribute("hidden", "");
    };
    const cauModalCloseWpConflict = () => {
        const m = byId("cauWpConflictModal");
        if (m) m.setAttribute("hidden", "");
    };

    const cauModalShowConflict = (conflict, summary) => {
        const m = byId("cauWpConflictModal");
        const msg = byId("cauWpConflictMsg");
        const diff = byId("cauWpConflictDiff");
        if (msg) msg.textContent = (conflict && conflict.message) || "Conflict — không cập nhật.";
        if (diff) {
            const lines = (summary && summary.diff_lines) || [];
            diff.textContent = lines.length
                ? lines.join("\n")
                : ("expected=" + ((conflict && conflict.expected_modified) || "") +
                    "\nremote=" + ((conflict && conflict.remote_modified) || ""));
        }
        if (m) m.removeAttribute("hidden");
    };

    const cauModalRenderConfirmSummary = (data) => {
        const s = (data && data.summary) || {};
        const box = byId("cauWpConfirmSummary");
        const diff = byId("cauWpConfirmDiff");
        const warn = byId("cauWpConfirmWarnings");
        if (!box) return;
        const hAdd = (s.headings_added || []).slice(0, 8).map((t) => "• " + t).join("<br>") || "—";
        const hChg = (s.headings_changed || []).slice(0, 8).map((h) => "• " + (h.from || "") + " → " + (h.to || "")).join("<br>") || "—";
        box.innerHTML =
            "<ul>" +
            "<li><strong>Điểm SEO:</strong> " + (s.seo_before != null ? s.seo_before : "—") +
            " → " + (s.seo_after != null ? s.seo_after : "—") +
            (s.seo_delta != null ? " (Δ" + (s.seo_delta >= 0 ? "+" : "") + s.seo_delta + ")" : "") + "</li>" +
            "<li><strong>Status bài hiện tại:</strong> " + cauEsc(s.post_status || cauModalState.postStatus || "—") + "</li>" +
            "<li><strong>Số đoạn đã sửa:</strong> " + (s.paragraphs_edited || 0) + "</li>" +
            "<li><strong>Số từ thêm/xóa:</strong> +" + (s.words_added || 0) + " / −" + (s.words_removed || 0) + "</li>" +
            "<li><strong>Heading thêm:</strong><br>" + hAdd + "</li>" +
            "<li><strong>Heading đổi:</strong><br>" + hChg + "</li>" +
            "<li><strong>Internal link thêm:</strong> " + ((s.internal_links_added || []).length) +
            " · gỡ: " + ((s.internal_links_removed || []).length) + "</li>" +
            "<li><strong>Ảnh thêm:</strong> " + ((s.images_added || []).length) +
            " · gỡ: " + ((s.images_removed || []).length) + "</li>" +
            "<li><strong>Patch:</strong> " + (s.patches_count || 0) + "</li>" +
            "</ul>";
        if (diff) diff.textContent = ((s.diff_lines || []).join("\n")) || "(không có diff text)";
        const warnings = ((data.validation && data.validation.warnings) || []).join(" · ");
        if (warn) warn.textContent = warnings ? ("Cảnh báo: " + warnings) : "";
    };

    const cauModalOpenUpdateConfirm = () => {
        if (!cauModalState.sessionId) {
            cauSetStatus("cauModalEditorHint", "err", "Chưa có session — tải lại bài.");
            return Promise.resolve();
        }
        const form = cauModalReadForm();
        if (!form.title.trim() || !form.content.trim()) {
            cauSetStatus("cauModalEditorHint", "err", "Title/Content không được để trống.");
            return Promise.resolve();
        }
        const patches = (cauAssistantUI && cauAssistantUI.applied) ? cauAssistantUI.applied.slice() : [];
        cauModalSetLoadState("updateLoading", true, "Đang chuẩn bị xác nhận…");
        return cauApi("POST", "/content-ai/auto-update/modal/update-confirm", {
            session_id: cauModalState.sessionId,
            title: form.title,
            content: form.content,
            excerpt: form.excerpt,
            slug: form.slug,
            keyword: form.keyword,
            secondary_keywords: form.secondary_keywords,
            expected_modified: cauModalState.wpModified || "",
            patches: patches,
        }).then((data) => {
            if (data.conflict) {
                cauModalShowConflict(data.conflict, data.summary);
                return;
            }
            if (data.remote_modified) cauModalState.wpModified = String(data.remote_modified);
            cauModalRenderConfirmSummary(data);
            const m = byId("cauWpConfirmModal");
            if (m) m.removeAttribute("hidden");
        }).catch((e) => {
            const detail = e && e.detail;
            if (detail && detail.conflict) {
                cauModalShowConflict(detail, detail);
                return;
            }
            cauSetStatus("cauModalEditorHint", "err", cauFormatApiError(e, "update"));
        }).finally(() => cauModalSetLoadState("updateLoading", false));
    };

    const cauModalUpdate = () => {
        // Open confirm first — never auto-publish.
        return cauModalOpenUpdateConfirm();
    };

    const cauModalConfirmFinalUpdate = () => {
        if (!cauModalState.sessionId) return Promise.resolve();
        const form = cauModalReadForm();
        const patches = (cauAssistantUI && cauAssistantUI.applied) ? cauAssistantUI.applied.slice() : [];
        cauModalSetLoadState("updateLoading", true, CAU_LOAD_LABELS.modalUpdate);
        cauBeginLoad("modalUpdate");
        return cauApi("POST", "/content-ai/auto-update/modal/update", {
            session_id: cauModalState.sessionId,
            title: form.title,
            content: form.content,
            excerpt: form.excerpt,
            slug: form.slug,
            keyword: form.keyword,
            secondary_keywords: form.secondary_keywords,
            confirmed: true,
            expected_modified: cauModalState.wpModified || "",
            patches: patches,
        }).then((data) => {
            cauModalCloseWpConfirm();
            const link = data.link || (data.result && data.result.link) || cauModalState.postUrl;
            const success = byId("cauSeoModalSuccess");
            const msg = byId("cauSeoModalSuccessMsg");
            const linkEl = byId("cauSeoModalSuccessLink");
            if (msg) msg.textContent = data.message || "Đã cập nhật bài viết thành công";
            if (linkEl && link) {
                linkEl.href = link;
                linkEl.textContent = "Mở bài trên website";
            }
            if (success) success.removeAttribute("hidden");
            cauModalState.originalContent = form.content;
            if (data.result) cauModalState.wpModified = cauPickWpModified(data.result);
            cauModalState.pendingProposal = null;
            if (data.seo_after) cauModalRenderFactorGroups(data.seo_after);
            const afterScore = data.seo_after && data.seo_after.score != null
                ? parseInt(data.seo_after.score, 10) : null;
            if (afterScore != null && cauModalState.postId) {
                cauUpsertScanScore({
                    post_id: cauModalState.postId,
                    id: cauModalState.postId,
                    post_type: cauModalState.postType,
                    type: cauModalState.postType,
                    link: cauModalState.postUrl,
                    url: cauModalState.postUrl,
                    title: form.title,
                    slug: form.slug,
                    status: cauModalState.postStatus,
                }, afterScore);
            }
            const warns = (data.warnings || []).length ? (" Backup ID: " + (data.backup_id || "—")) : "";
            cauSetStatus("cauModalEditorHint", "ok", (data.message || "Đã cập nhật.") + warns);
            cauModalState.backupId = data.backup_id || cauModalState.backupId;
            cauModalClearDraft();
            cauSaveWorkspace();
        }).catch((e) => {
            const detail = e && e.detail;
            if (e && (e.status === 409 || (detail && detail.conflict))) {
                cauModalCloseWpConfirm();
                cauModalShowConflict(detail || { message: "Conflict" }, detail);
                return;
            }
            cauModalSaveDraft();
            cauSetStatus("cauModalEditorHint", "err", cauFormatApiError(e, "update"));
        }).finally(() => {
            cauModalSetLoadState("updateLoading", false);
            cauEndLoad("modalUpdate");
        });
    };

    const cauModalReloadRemote = () => {
        if (!cauModalState.sessionId) return Promise.resolve();
        return cauApi("POST", "/content-ai/auto-update/modal/reload-remote", {
            session_id: cauModalState.sessionId,
        }).then((data) => {
            const p = data.post || {};
            cauModalState.originalContent = cauDecodeHtmlField(p, "content");
            cauModalState.wpModified = cauPickWpModified(p);
            if (p.status) cauModalState.postStatus = String(p.status);
            cauModalFillForm(p);
            if (data.seo_before) cauModalRenderFactorGroups(data.seo_before);
            cauModalCloseWpConflict();
            cauModalSaveDraft();
            cauSetStatus("cauModalEditorHint", "ok", data.message || "Đã tải lại bản WordPress.");
        }).catch((e) => {
            cauSetStatus("cauModalEditorHint", "err", cauFormatApiError(e, "fetch"));
        });
    };

    const cauModalViewBackup = () => {
        const sid = cauModalState.siteId;
        const pid = cauModalState.postId;
        const q = "?limit=10" + (sid ? ("&site_id=" + encodeURIComponent(sid)) : "") +
            (pid ? ("&wp_id=" + encodeURIComponent(String(pid))) : "");
        return cauApi("GET", "/content-ai/auto-update/modal/snapshots" + q).then((data) => {
            const items = data.items || [];
            if (!items.length) {
                cauSetStatus("cauModalAssistantHint", "err", "Chưa có backup cho bài này.");
                return;
            }
            const lines = items.map((it, i) =>
                (i + 1) + ". " + (it.created_at || "") + " · " + (it.old_title || "") +
                " · status=" + (it.old_status || "") + " · id=" + (it.id || "")
            ).join("\n");
            window.alert("Backup gần đây (chỉ của bạn):\n\n" + lines);
            cauModalState.backupId = items[0].id || cauModalState.backupId;
        }).catch((e) => {
            cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "fetch"));
        });
    };

    const cauModalRestoreBackupBtn = () => {
        const run = (backupId) => {
            if (!backupId) return Promise.resolve();
            if (!window.confirm("Restore bản cũ lên WordPress? Thao tác này ghi đè nội dung hiện tại trên WP.")) {
                return Promise.resolve();
            }
            return cauApi("POST", "/content-ai/auto-update/restore", { backup_id: backupId }).then(() => {
                cauSetStatus("cauModalAssistantHint", "ok", "Đã restore bản cũ lên WordPress.");
                return cauModalReloadRemote();
            }).catch((e) => {
                cauSetStatus("cauModalAssistantHint", "err", cauFormatApiError(e, "update"));
            });
        };
        if (cauModalState.backupId) return run(cauModalState.backupId);
        return cauModalViewBackup().then(() => run(cauModalState.backupId));
    };

    const cauEditSeoFromPost = (post) => cauModalOpen(post);

    const cauRenderCheckItem = (c) => {
        const st = c.status === "ok" ? "ok" : (c.status === "warn" ? "warn" : "block");
        const icon = st === "ok" ? "✓" : (st === "warn" ? "!" : "✕");
        return (
            '<li class="cau-pub-check cau-pub-check--' + st + '">' +
            "<span class=\"cau-pub-icon\">" + icon + "</span>" +
            "<span><strong>" + cauEsc(c.label) + "</strong>" +
            (c.detail ? "<em>" + cauEsc(c.detail) + "</em>" : "") +
            "</span></li>"
        );
    };

    const cauRenderPreviewSummary = () => {
        const box = byId("cauPreviewSummary");
        const s = cauState.previewSummary;
        if (!box) return;
        if (!s) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        const title = s.title || {};
        const wc = s.word_count || {};
        const seo = s.seo_score || {};
        const improved = (s.improved_factors || []).slice(0, 5).map((f) => cauEsc(f.label || f.id)).join(", ");
        const failed = (s.failed_after || []).slice(0, 5).map((f) => cauEsc(f.label || f.id)).join(", ");
        box.innerHTML =
            '<div class="cau-prev-row"><strong>Backup ID:</strong> ' + cauEsc(s.backup_id) + "</div>" +
            '<div class="cau-prev-row"><strong>Title:</strong> ' + cauEsc(title.old) + " → " + cauEsc(title.new) + "</div>" +
            '<div class="cau-prev-row"><strong>Word count:</strong> ' + (wc.old || 0) + " → " + (wc.new || 0) + "</div>" +
            '<div class="cau-prev-row"><strong>SEO Core:</strong> ' + (seo.before != null ? seo.before : "—") +
            " → " + (seo.after != null ? seo.after : "—") +
            (seo.delta != null ? " (Δ" + (seo.delta >= 0 ? "+" : "") + seo.delta + ")" : "") + "</div>" +
            (improved ? '<div class="cau-prev-row"><strong>Đã cải thiện:</strong> ' + improved + "</div>" : "") +
            (failed ? '<div class="cau-prev-row"><strong>Còn chưa đạt:</strong> ' + failed + "</div>" : "") +
            '<div class="cau-prev-row"><strong>Diff:</strong> ' + cauEsc(s.diff_summary || "") + "</div>";
    };

    const cauRenderSeoCounts = (elId, summary) => {
        const el = byId(elId);
        if (!el) return;
        if (!summary) {
            el.innerHTML = "";
            return;
        }
        el.innerHTML =
            '<span class="cau-count cau-count--ok">Đạt: <strong>' + (summary.passed || 0) + "</strong></span>" +
            '<span class="cau-count cau-count--warn">Cảnh báo: <strong>' + (summary.warning || 0) + "</strong></span>" +
            '<span class="cau-count cau-count--fail">Chưa đạt: <strong>' + (summary.failed || 0) + "</strong></span>";
    };

    const cauRenderSeoAiBefore = () => {
        const box = byId("cauSeoAiBefore");
        const scoreEl = byId("cauAiScoreBefore");
        if (!box) return;
        if (!cauState.seoBefore) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        if (scoreEl) scoreEl.textContent = String(cauState.seoBefore.score != null ? cauState.seoBefore.score : "—");
        cauRenderSeoCounts("cauSeoCounts", cauState.seoSummary);
        cauRenderFactorList("cauFailedItems", cauState.failedItems, "Không có yếu tố chưa đạt.");
        cauRenderFactorList("cauWarningItems", cauState.warningItems, "Không có cảnh báo.");
    };

    const cauRenderFactorList = (elId, factors, emptyMsg, opts) => {
        const el = byId(elId);
        if (!el) return;
        const items = factors || [];
        const showAiFix = !!(opts && opts.showAiFix);
        if (!items.length) {
            el.innerHTML = '<li class="cau-factor-empty">' + cauEsc(emptyMsg) + "</li>";
            return;
        }
        el.innerHTML = items.map((f) => {
            const label = cauEsc(f.label || f.id || "");
            const detail = cauEsc(f.message || f.detail || "");
            const delta = f.before_score != null && f.after_score != null
                ? " (" + f.before_score + "→" + f.after_score + ")"
                : "";
            const fid = String(f.id || "").trim();
            const status = String(f.status || "");
            const isFixing = showAiFix && fid && !!cauModalState.fixingFactorIds[fid];
            const aiBlocked = showAiFix && cauAiFixBlocked();
            const canFix = showAiFix && fid && (status === "failed" || status === "warning") && !isFixing && !aiBlocked;
            const fixBtnTitle = aiBlocked ? cauAiFixBlockMessage() : (cauAiFixCreditHint() || "");
            const fixBtn = (showAiFix && fid && (status === "failed" || status === "warning"))
                ? '<button type="button" class="cau-btn-ai-fix' + (isFixing ? " cau-btn-ai-fix--loading" : "") + '"' +
                (isFixing || aiBlocked ? " disabled" : "") +
                (fixBtnTitle ? ' title="' + cauEsc(fixBtnTitle) + '"' : "") +
                ' data-cau-fix-factor="' + cauEsc(fid) + '">' +
                (isFixing ? "Đang sửa…" : "Sửa bằng AI") + "</button>"
                : "";
            return (
                '<li class="cau-factor-item">' +
                '<div class="cau-factor-item__body">' +
                "<strong>" + label + delta + "</strong>" +
                (detail ? "<span>" + detail + "</span>" : "") +
                "</div>" +
                fixBtn +
                "</li>"
            );
        }).join("");
        if (showAiFix) {
            el.querySelectorAll("[data-cau-fix-factor]").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const factorId = btn.getAttribute("data-cau-fix-factor");
                    if (factorId) cauModalFixFactor(factorId).catch(() => {});
                });
            });
        }
    };

    const cauRenderDiff = (diff) => {
        const box = byId("cauDiffBox");
        if (!box) return;
        if (!diff || !(diff.fields || []).length) {
            box.innerHTML = '<p class="cau-hint">Chưa có diff — chạy Preview.</p>';
            return;
        }
        box.innerHTML = (diff.fields || []).map((f) => (
            '<div class="cau-diff-field">' +
            "<strong>" + cauEsc(f.field) + (f.changed ? " (đổi)" : "") + "</strong>" +
            (f.diff_lines && f.diff_lines.length
                ? "<pre>" + cauEsc(f.diff_lines.join("\n")) + "</pre>"
                : '<p class="cau-hint">Không đổi</p>') +
            "</div>"
        )).join("");
    };

    const cauRenderSeoBeforeFetch = () => {
        const box = byId("cauSeoBeforeFetch");
        const scoreEl = byId("cauScoreBeforeFetch");
        const seoBefore = cauState.seoBefore;
        if (box) box.hidden = !seoBefore;
        if (scoreEl && seoBefore) scoreEl.textContent = String(seoBefore.score != null ? seoBefore.score : "—");
        cauRenderFactorList("cauFailedBeforeFetch", cauState.failedFactorsBefore, "Chưa có yếu tố chưa đạt.");
    };

    const cauRenderSeoCompare = () => {
        const comparison = cauState.seoComparison;
        const box = byId("cauSeoCompare");
        if (!box) return;
        if (!comparison) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        const beforeEl = byId("cauScoreBefore");
        const afterEl = byId("cauScoreAfter");
        const deltaEl = byId("cauScoreDelta");
        const alertEl = byId("cauScoreDropAlert");
        const before = comparison.before_score != null ? comparison.before_score : "—";
        const after = comparison.after_score != null ? comparison.after_score : "—";
        if (beforeEl) beforeEl.textContent = String(before);
        if (afterEl) afterEl.textContent = String(after);
        const delta = comparison.delta != null ? comparison.delta : 0;
        if (deltaEl) {
            deltaEl.textContent = (delta >= 0 ? "+" : "") + delta;
            deltaEl.className = "cau-seo-delta" + (delta < 0 ? " cau-seo-delta--down" : " cau-seo-delta--up");
        }
        if (alertEl) {
            if (cauState.scoreRegressed || delta < 0) {
                alertEl.hidden = false;
                alertEl.textContent = "Cảnh báo: điểm SEO Core giảm — không publish live.";
            } else {
                alertEl.hidden = true;
                alertEl.textContent = "";
            }
        }
        cauRenderSeoCounts("cauSeoCountsAfter", cauState.seoSummaryAfter);
        cauRenderFactorList("cauImprovedFactors", comparison.improved_factors, "Chưa cải thiện yếu tố nào.");
        cauRenderFactorList("cauFailedAfter", cauState.failedAfter || comparison.failed_after, "Không còn yếu tố chưa đạt.");
        const markupUl = byId("cauMarkupWarnings");
        if (markupUl) {
            const warns = cauState.warnings || [];
            markupUl.innerHTML = warns.length
                ? warns.map((w) => "<li><strong>" + cauEsc(w) + "</strong></li>").join("")
                : '<li class="cau-factor-empty">Không có cảnh báo markup.</li>';
        }
    };

    const cauRenderPublishChecklist = () => {
        const box = byId("cauChecklistGroups");
        const hint = byId("cauPublishGateHint");
        const draftReasonEl = byId("cauDraftBlockReason");
        const liveReasonEl = byId("cauLiveBlockReason");
        const data = cauState.publishChecklist;
        if (!box) return;
        if (!data || !data.checks || !data.checks.length) {
            box.innerHTML = '<p class="cau-factor-empty">Chạy Preview để xem checklist.</p>';
            cauSetPublishButtons({ draft: false, live: false });
            if (hint) hint.textContent = "";
            if (draftReasonEl) draftReasonEl.hidden = true;
            if (liveReasonEl) liveReasonEl.hidden = true;
            return;
        }
        const grouped = data.grouped || {
            ok: data.checks.filter((c) => c.status === "ok"),
            warn: data.checks.filter((c) => c.status === "warn"),
            block: data.checks.filter((c) => c.status === "block"),
        };
        const section = (title, items, cls) =>
            (items && items.length)
                ? '<div class="cau-check-group cau-check-group--' + cls + '"><h4>' + title + "</h4><ul>" +
                items.map(cauRenderCheckItem).join("") + "</ul></div>"
                : "";
        box.innerHTML =
            section("Đạt", grouped.ok, "ok") +
            section("Cảnh báo", grouped.warn, "warn") +
            section("Chặn publish live", grouped.block, "block");

        const regressed = !!data.score_regressed || cauState.scoreRegressed;
        const canLive = !!(data.can_publish_live != null ? data.can_publish_live : data.can_publish);
        const canDraft = !!data.can_save_draft;
        const draftReasons = data.draft_block_reasons || [];
        const liveReasons = data.live_block_reasons || data.live_blockers || [];
        cauState.scoreRegressed = regressed;
        cauSetPublishButtons({
            draft: canDraft,
            live: canLive,
            draftReason: draftReasons,
            liveReason: liveReasons,
        });
        if (draftReasonEl) {
            draftReasonEl.hidden = canDraft || !draftReasons.length;
            draftReasonEl.textContent = canDraft ? "" : ("Lưu nháp: " + draftReasons.join("; "));
        }
        if (liveReasonEl) {
            liveReasonEl.hidden = canLive || !liveReasons.length;
            liveReasonEl.textContent = canLive ? "" : ("Publish live: " + liveReasons.join("; "));
        }
        if (hint) {
            if (canLive && canDraft) hint.textContent = "Đủ điều kiện lưu nháp và publish live.";
            else if (canDraft) hint.textContent = "Có thể lưu nháp. Publish live chưa đủ điều kiện.";
            else hint.textContent = "Chưa đủ điều kiện publish.";
        }
    };

    const cauRenderHistory = () => {
        const box = byId("cauHistoryList");
        if (!box) return;
        const items = cauState.historyItems;
        if (!items || !items.length) {
            box.innerHTML = '<p class="cau-empty">Chưa có lịch sử.</p>';
            return;
        }
        box.innerHTML = items.map((h) => {
            const seo = h.seo_before_score != null && h.seo_after_score != null
                ? " · SEO " + h.seo_before_score + "→" + h.seo_after_score
                : "";
            const url = h.link || h.post_url || "";
            const actionLabel = CAU_HISTORY_ACTION_LABELS[h.action] || h.mode || h.action || "";
            return (
                '<div class="cau-history-item">' +
                "<div class=\"cau-history-meta\">" +
                "<span>" + cauEsc(h.created_at || "") + "</span>" +
                "<span class=\"cau-history-mode\">" + cauEsc(actionLabel) + "</span>" +
                "<span class=\"cau-history-status\">" + cauEsc(h.status || "") + seo + "</span>" +
                "</div>" +
                "<div class=\"cau-history-body\">" +
                "<strong>" + cauEsc(h.title || "—") + "</strong>" +
                (url ? '<a href="' + cauEsc(url) + '" target="_blank" rel="noopener">' + cauEsc(url) + "</a>" : "") +
                (h.message ? "<em>" + cauEsc(h.message) + "</em>" : "") +
                (h.factor_labels && h.factor_labels.length
                    ? "<span class=\"cau-hint\">Yếu tố: " + cauEsc(h.factor_labels.join(", ")) + "</span>"
                    : "") +
                "</div>" +
                (h.backup_id && h.action !== "restore"
                    ? '<button type="button" class="mini-btn" data-cau-restore="' + h.backup_id + '">Restore</button>'
                    : "") +
                "</div>"
            );
        }).join("");
        box.querySelectorAll("[data-cau-restore]").forEach((btn) => {
            btn.addEventListener("click", () => cauRestore(btn.getAttribute("data-cau-restore")));
        });
    };

    const cauRenderSites = () => {
        const sel = byId("cauSiteSelect");
        if (!sel) return;
        sel.innerHTML = '<option value="">— Chọn site —</option>' +
            (cauState.sites || []).map((s) => (
                '<option value="' + s.id + '">' + cauEsc(s.label || s.url) + "</option>"
            )).join("");

        const defaultId = cauResolveDefaultSiteId();
        if (defaultId) {
            cauSelectSite(defaultId);
        } else {
            cauState.siteId = "";
            sel.value = "";
        }
        cauSyncScanSiteSelect();
    };

    const cauSyncUiFromState = () => {
        cauRenderSites();
        const kw = byId("cauKeyword");
        const focus = byId("cauFocus");
        const postUrl = byId("cauPostUrl");
        if (kw && document.activeElement !== kw) kw.value = cauState.keyword || "";
        if (focus && document.activeElement !== focus) focus.value = cauState.focus || "";
        if (postUrl && document.activeElement !== postUrl) postUrl.value = cauState.postUrl || "";

        const titleEl = byId("cauFetchedTitle");
        if (titleEl) {
            const t = cauState.fetchedTitle || (cauState.post && cauState.post.title) || "";
            titleEl.hidden = !t;
            titleEl.textContent = t;
        }

        const ul = byId("cauAiWarnings");
        if (ul) {
            const warns = cauState.warnings || [];
            ul.innerHTML = warns.length ? warns.map((w) => "<li>" + cauEsc(w) + "</li>").join("") : "";
        }

        cauRenderSeoBeforeFetch();
        cauRenderSeoAiBefore();
        cauRenderSeoCompare();
        cauRenderPreviewSummary();
        cauRenderDiff(cauState.diff);
        cauRenderPublishChecklist();
        cauRenderHistory();
        cauRenderQuotaBanner();
        const auPanel = byId("contentAiAutoUpdatePanel");
        if (!auPanel || !auPanel.hidden) {
            cauRestoreScanFiltersUi();
            cauRenderScanPosts();
        }

        Object.keys(cauState.status).forEach((k) => {
            if (!k.endsWith("Type")) {
                const type = cauState.status[k + "Type"] || "";
                if (cauState.status[k]) cauSetStatus(k, type, cauState.status[k]);
            }
        });

        if (cauState.backupId) {
            cauSetStatus("backup", cauState.status.backupType || "ok", cauState.status.backup || ("Backup ID: " + cauState.backupId));
        }

        document.querySelectorAll(".cau-tab").forEach((btn) => {
            const on = btn.getAttribute("data-cau-tab") === cauState.activeTab;
            btn.classList.toggle("active", on);
        });
        document.querySelectorAll(".cau-panel").forEach((p) => {
            const on = p.getAttribute("data-cau-panel") === cauState.activeTab;
            p.classList.toggle("active", on);
            p.hidden = !on;
        });
    };

    const cauSwitchTab = (key, opts) => {
        const tab = String(key || "select");
        cauPersistFormToState();
        cauState.activeTab = tab;
        document.querySelectorAll(".cau-tab").forEach((btn) => {
            btn.classList.toggle("active", btn.getAttribute("data-cau-tab") === tab);
        });
        document.querySelectorAll(".cau-panel").forEach((p) => {
            const on = p.getAttribute("data-cau-panel") === tab;
            p.classList.toggle("active", on);
            p.hidden = !on;
        });
        if (tab === "history" && !(opts && opts.skipHistoryLoad)) cauLoadHistory();
        cauSaveWorkspace();
        cauSyncUiFromState();
    };

    const cauLoadSites = () =>
        cauApi("GET", "/content-ai/sites").then((data) => {
            cauState.sites = data.items || [];
            cauRenderSites();
            if (cauState.siteId) {
                const site = cauFindSiteById(cauState.siteId);
                if (site) {
                    cauApplySiteToForm(site);
                    if (!cauState.status.connect) {
                        cauSetStatus("connect", "ok", "Đã chọn site: " + (site.label || site.url) + ".");
                    }
                }
            } else if (cauState.sites.length) {
                cauSetStatus(
                    "connect",
                    "",
                    "Có " + cauState.sites.length + " site đã lưu — chọn trong danh sách hoặc kết nối site mới."
                );
            }
            cauFinalizeWorkspaceRestore();
            cauSyncUiFromState();
        });

    const cauConnectSite = () => {
        const err = cauValidateConnectForm();
        if (err) {
            cauSetStatus("connect", "err", err);
            return Promise.resolve();
        }
        const body = {
            url: (byId("cauSiteUrl") && byId("cauSiteUrl").value.trim()) || "",
            username: (byId("cauSiteUser") && byId("cauSiteUser").value.trim()) || "",
            app_password: (byId("cauSitePass") && byId("cauSitePass").value) || "",
            label: (byId("cauSiteLabel") && byId("cauSiteLabel").value.trim()) || "",
        };
        return cauWithLoad("connect", "connect", () =>
            cauApi("POST", "/content-ai/sites/connect", body).then((data) => {
                const item = data.item || {};
                cauState.siteId = item.id || "";
                if (item.id) cauPersistSiteId(item.id);
                cauApplySiteToForm(item);
                cauSetStatus("connect", "ok", "Đã kết nối site thành công.");
                return cauLoadSites();
            }).then(() => {
                if (cauState.siteId) cauSelectSite(cauState.siteId);
                cauSetStatus("connect", "ok", "Đã kết nối và lưu site.");
            })
        );
    };

    const cauTestSite = () => {
        const siteErr = cauValidateSiteSelected();
        if (siteErr) {
            cauSetStatus("connect", "err", siteErr);
            return Promise.resolve();
        }
        const sid = (byId("cauSiteSelect") && byId("cauSiteSelect").value) || cauState.siteId;
        cauState.siteId = sid;
        return cauWithLoad("test", "connect", () =>
            cauApi("POST", "/content-ai/sites/test", { site_id: sid }).then((r) => {
                const ok = !!r.ok;
                cauSetStatus("connect", ok ? "ok" : "err", r.message || (ok ? "Kết nối OK." : "Kiểm tra thất bại."));
            })
        );
    };

    const cauFetchPost = () => {
        if (cauQuotaBlocked("content_auto_update_fetch")) {
            cauSetStatus("fetch", "err", "Đã hết quota lấy bài — nâng cấp gói.");
            return Promise.resolve();
        }
        const siteErr = cauValidateSiteSelected();
        if (siteErr) {
            cauSetStatus("fetch", "err", siteErr);
            return Promise.resolve();
        }
        const url = (byId("cauPostUrl") && byId("cauPostUrl").value.trim()) || "";
        const urlErr = cauValidateUrl(url, "URL bài viết");
        if (urlErr) {
            cauSetStatus("fetch", "err", urlErr);
            return Promise.resolve();
        }
        const siteId = (byId("cauSiteSelect") && byId("cauSiteSelect").value) || cauState.siteId;
        cauState.siteId = siteId;
        cauState.postUrl = url;
        return cauWithLoad("fetch", "fetch", () =>
            cauApi("POST", "/content-ai/auto-update/fetch-url", { site_id: siteId, url }).then((data) => {
                cauState.sessionId = data.session && data.session.id;
                cauState.backupId = "";
                cauState.canPublish = false;
                cauState.publishChecklist = null;
                cauState.proposal = null;
                cauState.seoComparison = null;
                cauState.diff = null;
                cauState.post = data.post || null;
                cauState.fetchedTitle = (data.post && data.post.title) || "";
                cauState.seoBefore = data.seo_before || null;
                cauState.seoSummary = data.seo_summary || null;
                cauState.failedFactorsBefore = data.failed_factors || [];
                cauState.failedItems = data.failed_items || [];
                cauState.warningItems = data.warning_items || [];
                cauState.seoAfter = null;
                cauState.failedAfter = [];
                cauState.scoreRegressed = false;
                cauSetPublishButtons({ draft: false, live: false });
                cauSetStatus(
                    "fetch",
                    "ok",
                    "Đã lấy bài WP #" + (data.post && data.post.wp_id) +
                    (data.seo_before ? " · SEO Core: " + data.seo_before.score + "/100" : "")
                );
                cauSaveWorkspace();
                cauSwitchTab("ai", { skipHistoryLoad: true });
            })
        );
    };

    const cauGenerate = () => {
        if (cauQuotaBlocked("content_auto_update_generate")) {
            cauSetStatus("ai", "err", "Đã hết quota AI — nâng cấp gói.");
            return Promise.resolve();
        }
        if (!cauState.sessionId) {
            cauSetStatus("ai", "err", "Chưa có session — lấy bài trước.");
            return Promise.resolve();
        }
        cauPersistFormToState();
        return cauWithLoad("generate", "ai", () =>
            cauApi("POST", "/content-ai/auto-update/generate", {
                session_id: cauState.sessionId,
                keyword: cauState.keyword,
                focus: cauState.focus,
            }).then((data) => {
                cauState.proposal = data.proposal || null;
                cauState.warnings = data.warnings || [];
                cauState.seoBefore = data.seo_before || cauState.seoBefore;
                cauState.seoAfter = data.seo_after || null;
                cauState.seoSummary = data.seo_summary_before || cauState.seoSummary;
                cauState.seoSummaryAfter = data.seo_summary_after || null;
                cauState.seoComparison = data.seo_comparison || null;
                cauState.failedFactorsBefore = data.failed_factors || cauState.failedFactorsBefore;
                cauState.failedItems = data.failed_items || cauState.failedItems;
                cauState.warningItems = data.warning_items || cauState.warningItems;
                cauState.failedAfter = data.failed_after || [];
                cauState.scoreRegressed = !!data.score_regressed;
                cauState.hasProposal = true;
                if (data.session && data.session.id) cauState.sessionId = data.session.id;
                cauSetStatus("ai", "ok", data.ai_summary || (data.proposal && data.proposal.summary) || "Đã tạo đề xuất AI.");
                cauSwitchTab("preview", { skipHistoryLoad: true });
            })
        );
    };

    const cauPreview = () => {
        if (!cauState.sessionId) {
            cauSetStatus("backup", "err", "Chưa có session.");
            return Promise.resolve();
        }
        if (!cauState.hasProposal && !cauState.proposal) {
            cauSetStatus("backup", "err", "Chưa có đề xuất AI — bấm Tạo đề xuất trước.");
            return Promise.resolve();
        }
        return cauWithLoad("preview", "backup", () =>
            cauApi("POST", "/content-ai/auto-update/preview", { session_id: cauState.sessionId }).then((data) => {
                cauState.backupId = data.backup_id || "";
                cauState.diff = data.diff || null;
                cauState.previewSummary = data.preview_summary || null;
                if (data.seo_comparison) cauState.seoComparison = data.seo_comparison;
                cauState.publishChecklist = data.publish_checklist || null;
                cauState.scoreRegressed = !!data.score_regressed;
                cauRenderPreviewSummary();
                cauSetStatus("backup", "ok", "Đã backup · ID: " + cauState.backupId);
                cauSwitchTab("publish", { skipHistoryLoad: true });
            })
        );
    };

    const cauPublish = (mode) => {
        if (!cauState.sessionId) {
            cauSetStatus("publish", "err", "Chưa có session.");
            return Promise.resolve();
        }
        if (!cauState.backupId) {
            cauSetStatus("publish", "err", "Chưa backup — chạy Preview trước.");
            return Promise.resolve();
        }
        if (mode === "publish" && cauState.scoreRegressed) {
            cauSetStatus("publish", "err", "Điểm SEO giảm — không publish live.");
            return Promise.resolve();
        }
        if (mode === "publish" && !cauState.canPublishLive) {
            cauSetStatus("publish", "err", "Chưa đủ điều kiện publish live — xem checklist.");
            return Promise.resolve();
        }
        if (mode === "draft" && !cauState.canSaveDraft) {
            cauSetStatus("publish", "err", "Chưa đủ điều kiện lưu nháp — xem checklist.");
            return Promise.resolve();
        }
        if (mode === "publish" && cauQuotaBlocked("content_auto_update_publish")) {
            cauSetStatus("publish", "err", "Đã hết quota publish — nâng cấp gói.");
            return Promise.resolve();
        }
        if (mode === "publish" && !window.confirm("Publish live lên WordPress?")) return Promise.resolve();
        const loadKey = mode === "publish" ? "publishLive" : "publishDraft";
        return cauWithLoad(loadKey, "publish", () =>
            cauApi("POST", "/content-ai/auto-update/publish", {
                session_id: cauState.sessionId,
                mode: mode,
            }).then((data) => {
                const res = data.result || {};
                const job = data.job || {};
                cauSetStatus("publish", "ok", "Thành công — " + (res.status || mode));
                const okBox = byId("cauPublishSuccess");
                if (okBox) {
                    okBox.hidden = false;
                    okBox.innerHTML =
                        "<strong>Đã publish</strong><br>" +
                        "Mode: " + cauEsc(res.mode || mode) + "<br>" +
                        "Trạng thái: " + cauEsc(res.status || "") + "<br>" +
                        (res.link ? 'URL: <a href="' + cauEsc(res.link) + '" target="_blank" rel="noopener">' + cauEsc(res.link) + "</a><br>" : "") +
                        "Thời gian: " + cauEsc(job.created_at || new Date().toISOString());
                }
                return cauLoadQuota().then(() => cauLoadHistory({ silent: true }));
            })
        );
    };

    const cauRestore = (backupId) => {
        if (cauQuotaBlocked("content_auto_update_restore")) {
            cauSetStatus("publish", "err", "Đã hết quota restore — nâng cấp gói.");
            return Promise.resolve();
        }
        if (!backupId || !window.confirm("Khôi phục bản cũ lên WordPress?")) return Promise.resolve();
        return cauWithLoad("publishLive", "publish", () =>
            cauApi("POST", "/content-ai/auto-update/restore", { backup_id: backupId }).then(() => {
                cauSetStatus("publish", "ok", "Đã restore bản cũ lên WordPress.");
                return cauLoadQuota().then(() => cauLoadHistory({ silent: true }));
            })
        );
    };

    const cauLoadHistory = (opts) => {
        const silent = !!(opts && opts.silent);
        const doFetch = () =>
            cauApi("GET", "/content-ai/auto-update/history?limit=40").then((data) => {
                cauState.historyItems = data.items || [];
                cauRenderHistory();
            });
        if (silent) return doFetch().catch(() => {});
        return cauWithLoad("history", "history", doFetch).catch(() => {});
    };

    let cauInitialized = false;

    const initContentAutoUpdate = () => {
        if (cauInitialized) return;
        cauInitialized = true;
        cauRestoreWorkspaceFromStorage();

        // Clear stuck loading state (e.g. after failed request left buttons disabled).
        Object.keys(CAU_ACTION_BUTTONS).forEach((act) => cauEndLoad(act));
        cauState.loading = null;

        document.querySelectorAll(".cau-tab").forEach((btn) => {
            btn.addEventListener("click", () => cauSwitchTab(btn.getAttribute("data-cau-tab")));
        });

        const bind = (id, fn) => {
            const el = byId(id);
            if (el) el.addEventListener("click", () => { fn().catch(() => {}); });
        };

        bind("btnCauConnect", cauConnectSite);
        bind("btnCauTestSite", cauTestSite);
        bind("btnCauFetch", cauFetchPost);
        bind("btnCauScanCategories", cauScanCategories);
        bind("btnCauScanPosts", cauScanPosts);
        bind("btnCauRefreshScan", cauRefreshScanPosts);
        bind("btnCauLoadMorePosts", cauLoadMorePosts);
        bind("btnCauGenerate", cauGenerate);
        bind("btnCauPreview", cauPreview);
        bind("btnCauSaveDraft", () => cauPublish("draft"));
        bind("btnCauPublishLive", () => cauPublish("publish"));
        bind("btnCauRefreshHistory", cauLoadHistory);

        ["cauKeyword", "cauFocus", "cauPostUrl"].forEach((id) => {
            const el = byId(id);
            if (el) el.addEventListener("input", cauPersistFormToState);
        });

        const siteSel = byId("cauSiteSelect");
        if (siteSel) {
            siteSel.addEventListener("change", () => {
                cauSelectSite(siteSel.value, { skipForm: false });
                cauSyncScanSiteSelect();
                cauState.scanPosts = [];
                cauState.scanQueried = false;
                cauState.scanTypeCounts = {};
                cauState.scanFromCache = false;
                cauState.scanScannedAt = "";
                cauRenderScanPosts();
                cauSaveWorkspace();
            });
        }

        const scanSiteSel = byId("cauScanSiteSelect");
        if (scanSiteSel) {
            scanSiteSel.addEventListener("change", () => {
                cauSelectSite(scanSiteSel.value, { skipForm: true });
                const mainSel = byId("cauSiteSelect");
                if (mainSel) mainSel.value = scanSiteSel.value;
                cauOnScanSiteChanged(scanSiteSel.value);
                cauState.scanPosts = [];
                cauState.scanQueried = false;
                cauState.scanTypeCounts = {};
                cauState.scanFromCache = false;
                cauState.scanScannedAt = "";
                cauRenderScanPosts();
                cauSaveWorkspace();
                if ((cauState.scanCategories || []).length) {
                    cauAutoScanPosts().catch(() => {});
                }
            });
        }

        const scanSearchEl = byId("cauPostSearch");
        if (scanSearchEl) {
            scanSearchEl.addEventListener("input", () => {
                cauState.scanSearch = scanSearchEl.value.trim();
                cauSaveWorkspace();
            });
            scanSearchEl.addEventListener("keydown", (ev) => {
                if (ev.key === "Enter") {
                    ev.preventDefault();
                    cauScanPosts().catch(() => {});
                }
            });
        }

        const statusFilter = byId("cauPostStatusFilter");
        if (statusFilter) {
            statusFilter.addEventListener("change", () => {
                cauState.scanStatus = statusFilter.value || "all";
                cauSaveWorkspace();
                if ((cauState.scanCategories || []).length) {
                    cauAutoScanPosts().catch(() => {});
                }
            });
        }

        const scoreFilter = byId("cauPostScoreFilter");
        if (scoreFilter) {
            scoreFilter.addEventListener("change", () => {
                cauState.scanScoreFilter = scoreFilter.value || "all";
                cauSaveWorkspace();
                cauRenderScanPosts();
            });
        }

        const sortScoreBtn = byId("btnCauSortScore");
        if (sortScoreBtn) {
            sortScoreBtn.addEventListener("click", () => {
                cauState.scanSortScore = (cauState.scanSortScore || "asc") === "asc" ? "desc" : "asc";
                cauRestoreScanFiltersUi();
                cauSaveWorkspace();
                cauRenderScanPosts();
            });
        }

        const categoryFilter = byId("cauPostCategoryFilter");
        if (categoryFilter) {
            categoryFilter.addEventListener("change", () => {
                cauState.scanCategoryId = categoryFilter.value || "";
                if (!cauState.scanCategoryId) {
                    const q = String(cauState.scanSearch || "").trim();
                    if (q && !cauSanitizeScanSearch(q, false)) {
                        cauState.scanSearch = "";
                        const searchEl = byId("cauPostSearch");
                        if (searchEl) searchEl.value = "";
                    }
                }
                cauUpdateScanScopeHint();
                const sid = (byId("cauScanSiteSelect") && byId("cauScanSiteSelect").value) || cauState.siteId;
                if (sid && (cauState.scanCategories || []).length) {
                    cauSaveCatHistory(sid, cauState.scanCategories, cauState.scanCategoryId);
                }
                cauSaveWorkspace();
                if ((cauState.scanCategories || []).length) {
                    cauAutoScanPosts().catch(() => {});
                }
            });
        }

        const siteUrlEl = byId("cauSiteUrl");
        if (siteUrlEl) {
            siteUrlEl.addEventListener("change", () => {
                const hit = cauFindSiteByUrl(siteUrlEl.value);
                if (hit) cauSelectSite(hit.id);
            });
        }

        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState !== "visible" || !getAuthToken()) return;
            const panel = byId("contentAiAutoUpdatePanel");
            if (panel && !panel.hidden) cauLoadSites().catch(() => {});
        });

        window.addEventListener("beforeunload", () => {
            cauPersistScanFilters();
            cauPersistFormToState();
            if (cauModalState.open) cauModalSaveDraft();
        });

        const bindModal = (id, fn) => {
            const el = byId(id);
            if (el) el.addEventListener("click", () => { fn().catch(() => {}); });
        };
        const closeModalBtn = byId("btnCauSeoModalClose");
        if (closeModalBtn) closeModalBtn.addEventListener("click", () => cauModalClose());
        document.querySelectorAll("[data-cau-modal-close]").forEach((el) => {
            el.addEventListener("click", () => cauModalClose());
        });
        bindModal("btnCauModalAnalyze", cauModalAnalyze);
        bindModal("btnCauModalUpdate", cauModalUpdate);
        bindModal("btnCauModalFixAll", cauModalFixAllFactors);
        const btnUndo = byId("btnCauModalUndo");
        if (btnUndo) btnUndo.addEventListener("click", () => cauModalUndoEditor());
        const btnSaveSession = byId("btnCauModalSaveSession");
        if (btnSaveSession) btnSaveSession.addEventListener("click", () => cauModalSaveSessionExplicit());
        const btnViewChanges = byId("btnCauModalViewChanges");
        if (btnViewChanges) btnViewChanges.addEventListener("click", () => cauModalViewChanges());
        const btnConfirmFinal = byId("btnCauWpConfirmFinal");
        if (btnConfirmFinal) btnConfirmFinal.addEventListener("click", () => { cauModalConfirmFinalUpdate().catch(() => {}); });
        document.querySelectorAll("[data-cau-wp-confirm-close]").forEach((el) => {
            el.addEventListener("click", () => cauModalCloseWpConfirm());
        });
        document.querySelectorAll("[data-cau-wp-conflict-close]").forEach((el) => {
            el.addEventListener("click", () => cauModalCloseWpConflict());
        });
        const btnReloadRemote = byId("btnCauWpReloadRemote");
        if (btnReloadRemote) btnReloadRemote.addEventListener("click", () => { cauModalReloadRemote().catch(() => {}); });
        const btnConflictDiff = byId("btnCauWpConflictDiff");
        if (btnConflictDiff) btnConflictDiff.addEventListener("click", () => {
            const d = byId("cauWpConflictDiff");
            if (d) window.alert(d.textContent || "Không có diff.");
        });
        const btnViewBackup = byId("btnCauModalViewBackup");
        if (btnViewBackup) btnViewBackup.addEventListener("click", () => { cauModalViewBackup().catch(() => {}); });
        const btnRestoreBackup = byId("btnCauModalRestoreBackup");
        if (btnRestoreBackup) btnRestoreBackup.addEventListener("click", () => { cauModalRestoreBackupBtn().catch(() => {}); });
        document.querySelectorAll("[data-cau-content-action='append']").forEach((btn) => {
            btn.addEventListener("click", () => { cauModalShowAppendHeadingsInput(); });
        });
        cauEnsureAssistantUI();
        const btnAppendRun = byId("btnCauModalRunAppendHeadings");
        if (btnAppendRun) btnAppendRun.addEventListener("click", () => { cauModalRunAppendHeadings().catch(() => {}); });
        const btnAppendCancel = byId("btnCauModalCancelAppendHeadings");
        if (btnAppendCancel) btnAppendCancel.addEventListener("click", () => cauModalHideAppendHeadingsInput());
        const btnFixApply = byId("btnCauFixApply");
        if (btnFixApply) btnFixApply.addEventListener("click", () => { cauModalApplyPendingFix().catch(() => {}); });
        const btnFixUndo = byId("btnCauFixUndo");
        if (btnFixUndo) btnFixUndo.addEventListener("click", () => cauModalUndoPendingFix());
        const btnFixClose = byId("btnCauFixDetailClose");
        if (btnFixClose) btnFixClose.addEventListener("click", () => cauModalUndoPendingFix());
        document.querySelectorAll("[data-cau-fix-close]").forEach((el) => {
            el.addEventListener("click", () => cauModalUndoPendingFix());
        });
        const btnPreview = byId("btnCauModalPreview");
        if (btnPreview) btnPreview.addEventListener("click", () => {
            cauModalPreview();
            const scroll = byId("cauSeoModalScroll");
            const box = byId("cauModalPreviewBox");
            if (scroll && box) scroll.scrollTop = box.offsetTop - 8;
        });
        const btnPreviewClose = byId("btnCauModalPreviewClose");
        if (btnPreviewClose) btnPreviewClose.addEventListener("click", () => {
            const box = byId("cauModalPreviewBox");
            if (box) box.setAttribute("hidden", "");
        });
        document.addEventListener("keydown", (ev) => {
            if (ev.key === "Escape" && cauModalState.open) cauModalClose();
        });

        const contentEditor = byId("cauModalContentEditor");
        if (contentEditor) {
            let timer = null;
            contentEditor.addEventListener("input", () => {
                if (!cauModalState.open) return;
                cauModalSyncEditorToStore();
                cauModalSaveDraft();
                clearTimeout(timer);
                timer = setTimeout(() => { cauModalScoreLive().catch(() => {}); }, 600);
            });
        }
        const htmlSource = byId("cauModalContentHtml");
        const advPanel = byId("cauModalAdvanced");
        if (htmlSource) {
            htmlSource.addEventListener("input", () => {
                if (!cauModalState.open || !advPanel || !advPanel.open) return;
                const hidden = byId("cauModalContent");
                if (hidden) hidden.value = htmlSource.value;
                if (cauBlockEditor) {
                    // live preview deferred to blur to avoid parse thrash
                } else {
                    const editor = byId("cauModalContentEditor");
                    if (editor) editor.innerHTML = htmlSource.value;
                }
                cauModalSaveDraft();
            });
            htmlSource.addEventListener("blur", () => {
                if (!cauModalState.open || !advPanel || !advPanel.open) return;
                if (cauBlockEditor) cauBlockEditor.loadHtml(htmlSource.value || "");
            });
        }
        if (advPanel) {
            advPanel.addEventListener("toggle", () => {
                if (!advPanel.open) {
                    if (cauBlockEditor && htmlSource) {
                        cauBlockEditor.loadHtml(htmlSource.value || cauModalGetContentHtml());
                    }
                    return;
                }
                const hidden = byId("cauModalContent");
                const htmlTa = byId("cauModalContentHtml");
                if (cauBlockEditor && hidden) hidden.value = cauBlockEditor.getHtml();
                if (hidden && htmlTa) htmlTa.value = hidden.value;
            });
        }

        ["cauModalTitle", "cauModalExcerpt", "cauModalKeyword", "cauModalSlug", "cauModalSecondaryKw", "cauModalOutline"].forEach((id) => {
            const el = byId(id);
            if (!el) return;
            let timer = null;
            el.addEventListener("input", () => {
                if (!cauModalState.open) return;
                cauModalSaveDraft();
                clearTimeout(timer);
                timer = setTimeout(() => { cauModalScoreLive().catch(() => {}); }, 600);
            });
        });

        cauSetPublishButtons({ draft: false, live: false });
        cauModalInitEditorTools();
        cauInsertBindUi();
        cauEnsureBlockEditor();
        if (getAuthToken()) {
            cauLoadSites().then(() => {
                cauModalPromptRestoreDraft();
            }).catch(() => {});
            cauLoadQuota();
        }
        const idle = window.requestIdleCallback || function (cb) { return setTimeout(cb, 0); };
        idle(() => {
            cauSwitchTab(cauState.activeTab || "select", { skipHistoryLoad: true });
        }, { timeout: 1200 });
    };

    window.__cauSyncUi = cauSyncUiFromState;
    window.__cauLoadSites = cauLoadSites;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initContentAutoUpdate);
    } else {
        initContentAutoUpdate();
    }
})();
