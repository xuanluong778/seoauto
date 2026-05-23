
// Load TinyMCE to make Content editor like WordPress.
// If the CDN is blocked/unavailable, we keep the textarea as-is.
(function () {
    window.__USE_TINYMCE = false;
    if (!window.__USE_TINYMCE) {
        window.__tinymceReady = false;
        return;
    }
    const sources = [
        "https://cdn.jsdelivr.net/npm/tinymce@6/tinymce.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/tinymce/6.8.6/tinymce.min.js",
        "https://unpkg.com/tinymce@6/tinymce.min.js",
    ];
    const loadAt = (idx) => {
        if (idx >= sources.length) {
            window.__tinymceReady = false;
            return;
        }
        const s = document.createElement("script");
        s.referrerPolicy = "origin";
        s.src = sources[idx];
        s.onload = () => { window.__tinymceReady = true; };
        s.onerror = () => loadAt(idx + 1);
        document.head.appendChild(s);
    };
    loadAt(0);
})();
(() => {
    const byId = (id) => document.getElementById(id);
    const readCookieToken = () => {
        const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    };
    const getAuthToken = () => {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (!t) {
                t = readCookieToken();
                if (t) sessionStorage.setItem("seo_token", t);
            }
            return t;
        } catch (_) {
            return readCookieToken();
        }
    };
    const clearAuthToken = () => {
        try { sessionStorage.removeItem("seo_token"); } catch (_) {}
        document.cookie = "seo_token=; path=/; max-age=0; SameSite=Lax";
    };
    const parseApiDetail = (data) => {
        const d = data && data.detail;
        if (typeof d === "string") return d;
        if (Array.isArray(d)) return d.map((x) => (x && (x.msg || x.message)) || x).join(", ");
        if (d && typeof d === "object") {
            if (d.message) return String(d.message);
            if (d.code === "trial_expired") return "Gói dùng thử / trial đã hết hạn.";
            try { return JSON.stringify(d); } catch (_) { return "Lỗi API"; }
        }
        return "";
    };
    const handleApiAuthFailure = (res, data) => {
        if (!res || res.status !== 401) return false;
        clearAuthToken();
        const detail = parseApiDetail(data) || "Invalid token";
        const msg =
            detail.toLowerCase().includes("invalid token") || detail.toLowerCase().includes("đăng nhập")
                ? "Phiên đăng nhập hết hạn hoặc không hợp lệ — không phải do thiếu tiền. Bấm Đăng nhập ở góc trên (menu user) để đăng nhập lại."
                : detail + " — hãy đăng nhập lại.";
        try { setHint("content", msg); } catch (_) {}
        try { setHint("internal-links", msg); } catch (_) {}
        if (typeof window.DigiSeoOpenLoginModal === "function") {
            window.DigiSeoOpenLoginModal();
        }
        return true;
    };
    const apiFetch = (url, opts = {}) => {
        const o = { credentials: "same-origin", ...opts };
        o.headers = authHeaders({ ...(opts.headers || {}) });
        return fetch(url, o).then(async (res) => {
            if (res.status === 401) {
                const data = await res.clone().json().catch(() => ({}));
                handleApiAuthFailure(res, data);
            }
            return res;
        });
    };
    const getAuthUserId = () => {
        const t = getAuthToken();
        if (!t) return 0;
        try {
            const part = t.split(".")[1];
            if (!part) return 0;
            const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
            const pad = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
            const payload = JSON.parse(atob(pad));
            return parseInt(payload.user_id, 10) || 0;
        } catch (_) {
            return 0;
        }
    };
    const userStorageKey = (base) => {
        const uid = getAuthUserId();
        return uid > 0 ? `${base}_u${uid}` : base;
    };
    const purgeLegacySharedStorage = () => {
        const legacyKeys = [
            "content_ai_site_profiles_v1",
            "content_ai_wp_profiles_v1",
            "content_ai_target_website_history_v1",
            "content_ai_wp_url_history_v1",
            "content_ai_wp_user_history_v1",
            "content_ai_form_state_v1",
            "content_ai_bulk_job_id_v1",
            "content_ai_bulk_state_v1",
        ];
        legacyKeys.forEach((k) => {
            try {
                localStorage.removeItem(k);
            } catch (_) {}
        });
    };
    const authHeaders = (extra) => {
        const h = { ...(extra || {}) };
        const t = getAuthToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    };
    const authJsonHeaders = () => authHeaders({ "Content-Type": "application/json" });
    // Highlight active menu link
    try {
        const path = (window.location && window.location.pathname) ? window.location.pathname.replace(/\/+$/, "") : "";
        document.querySelectorAll(".nav a").forEach((a) => {
            const href = (a.getAttribute("href") || "").trim();
            if (!href || href.startsWith("http")) return;
            const h = href.replace(/\/+$/, "");
            if (h && h === path) a.classList.add("active");
        });
        if (path === "/settings") {
            document.querySelectorAll('a[href="/settings"]').forEach((b) => b.classList.add("active"));
        }
    } catch (_) {}

    // Ensure fixed bars never overlap content (nav can wrap to 2 lines).
    const syncFixedHeights = () => {
        try {
            const strip = document.getElementById("digiseoTopNavStrip") || document.querySelector(".nav-strip");
            const nav = document.querySelector(".nav-strip .nav, .nav-strip nav[aria-label=\"Menu chính\"], .nav");
            const topBar = byId("topFixedBar");
            const navEl = strip || nav;
            const navH = navEl ? Math.ceil(navEl.getBoundingClientRect().height) : 76;
            document.documentElement.style.setProperty("--navH", `${navH}px`);
            if (topBar) {
                const sideW = Math.ceil(topBar.getBoundingClientRect().width);
                if (sideW) document.documentElement.style.setProperty("--sideW", `${sideW}px`);
            }
        } catch (_) {}
    };
    syncFixedHeights();
    window.addEventListener("resize", () => {
        // debounce a bit
        window.clearTimeout(window.__fixedHTimer);
        window.__fixedHTimer = window.setTimeout(syncFixedHeights, 80);
    });
    const btn = byId("btnDraft");
    const btnCreateContent = byId("btnCreateContent");
    const btnPublish = byId("btnPublish");
    const btnPublishNow = byId("btnPublishNow");
    const btnWpUpdateContent = byId("btnWpUpdateContent");
    const btnUploadImage = byId("btnUploadImage");
    const btnGoogleImageSearch = byId("btnGoogleImageSearch");
    const btnOutlineReference = byId("btnOutlineReference");
    const btnReplaceAll = byId("btnReplaceAll");
    const btnRefreshOutline = byId("btnRefreshOutline");
    const btnResetForm = byId("btnResetForm");
    const out = byId("output");
    const outputFormat = byId("outputFormat");
    const outputAccordion = byId("outputAccordion");
    const btnToggleOutput = byId("btnToggleOutput");
    const outputAccordionBody = byId("outputAccordionBody");
    const outputChev = byId("outputChev");
    const btnFindInternalLinks = byId("btnFindInternalLinks");
    const btnApplyInternalLinks = byId("btnApplyInternalLinks");
    const btnDownloadScreamingFrog = byId("btnDownloadScreamingFrog");
    const btnSeoJsonFill = byId("btnSeoJsonFill");
    const statWords = byId("statWords");
    const statChars = byId("statChars");
    const statSentences = byId("statSentences");
    const statParagraphs = byId("statParagraphs");
    const statPages = byId("statPages");
    const publishLog = byId("publishLog");
    const msg = byId("msg");
    const uploadList = byId("uploadList");
    const googleImageResults = byId("googleImageResults");
    const googleImageQuery = byId("googleImageQuery");
    const internalLinkCandidates = byId("internalLinkCandidates");
    const genBackdrop = byId("genBackdrop");
    const genModal = byId("genModal");
    const btnGenClose = byId("btnGenClose");
    const genFill = byId("genFill");
    const genPct = byId("genPct");
    const genHint = byId("genHint");
    const genStream = byId("genStream");
    const inlineProgress = byId("inlineProgress");
    const inlineProgressFill = byId("inlineProgressFill");
    const inlineProgressPct = byId("inlineProgressPct");
    const previewLoading = byId("previewLoading");
    const previewLoadingFill = byId("previewLoadingFill");
    const previewLoadingPct = byId("previewLoadingPct");
    const previewLoadingText = byId("previewLoadingText");
    const btnModeVisual = byId("btnModeVisual");
    const btnModeCode = byId("btnModeCode");
    const btnToolBold = byId("btnToolBold");
    const btnToolItalic = byId("btnToolItalic");
    const btnToolUnderline = byId("btnToolUnderline");
    const btnToolQuote = byId("btnToolQuote");
    const btnToolH2 = byId("btnToolH2");
    const btnToolH3 = byId("btnToolH3");
    const btnToolUl = byId("btnToolUl");
    const btnToolOl = byId("btnToolOl");
    const btnToolAlignLeft = byId("btnToolAlignLeft");
    const btnToolAlignCenter = byId("btnToolAlignCenter");
    const btnToolAlignRight = byId("btnToolAlignRight");
    const btnToolUndo = byId("btnToolUndo");
    const btnToolRedo = byId("btnToolRedo");
    const btnToolLink = byId("btnToolLink");
    const btnToolHr = byId("btnToolHr");
    const btnToolTable = byId("btnToolTable");
    const btnToolClear = byId("btnToolClear");
    const editorBlockFormat = byId("editorBlockFormat");
    const editorTools = byId("editorTools");
    const USE_TINYMCE = !!window.__USE_TINYMCE;
    const FORCE_VISUAL_MODE = true;
    let editorMode = "visual";
    const autoGrowOutline = () => {
        const el = byId("outlineContent");
        if (!el) return;
        // Reset height then grow to fit full content (no internal scroll).
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight}px`;
    };
    const googleImageNum = byId("googleImageNum");
    const targetWebsiteHistoryList = byId("targetWebsiteHistory");
    const wpUrlHistoryList = byId("wpUrlHistory");
    const wpUserHistoryList = byId("wpUserHistory");
    const projectList = byId("projectList");
    const projectHint = byId("projectHint");
    const projectPager = byId("projectPager");
    const btnProjectPrev = byId("btnProjectPrev");
    const btnProjectNext = byId("btnProjectNext");
    const projectPageInfo = byId("projectPageInfo");
    const projectPageButtons = byId("projectPageButtons");
    const aiButtons = document.querySelectorAll(".ai-btn");
    let lastSuggestedTitle = "";
    const uploadedImages = [];
    let activeProjectId = "";
    /** WP category term IDs gắn với draft khi publish (từ dự án bulk hoặc draft JSON). */
    let _draftWpCategoryIds = null;
    const syncSingleWpCategoryFromSelect = () => {
        const sel = byId("singleWpCategoryId");
        if (!sel) return;
        const v = String(sel.value || "").trim();
        const n = parseInt(v, 10);
        _draftWpCategoryIds = !Number.isNaN(n) && n > 0 ? [n] : null;
    };
    const fillSingleWpCategorySelect = (savedId) => {
        const sel = byId("singleWpCategoryId");
        if (!sel) return;
        const site = String(byId("targetWebsite")?.value || "").trim();
        const sk = _getWpCategoriesSiteKey(site);
        if (sk) _hydrateWpCategoriesFromCache(sk);
        const cached = sk ? _bulkWpCategoriesBySiteKey[sk] : null;
        fillBulkCategorySelectEl(sel, cached || [], savedId);
        _syncWpCategoryLoadButtonLabel(site);
        const hint = byId("hint-singleWpCategory");
        if (hint && cached && cached.length) {
            hint.textContent = `Đã nạp ${cached.length} danh mục đã lưu cho site này.`;
        }
    };
    let allProjects = [];
    /** Site từ Cài đặt → Xuất bản (server), đồng bộ gợi ý / danh sách kết nối */
    let settingsPublishingSitesFlat = [];
    let projectPage = 1;
    /** Chuẩn hóa https://host — lọc danh sách dự án theo target_website đã lưu */
    let _projectsSiteFilterBase = "";
    const SIDEBAR_RECENT_PROJECT_COUNT = 3;
    const TARGET_HISTORY_KEY = () => userStorageKey("content_ai_target_website_history_v1");
    const WP_URL_HISTORY_KEY = () => userStorageKey("content_ai_wp_url_history_v1");
    const WP_USER_HISTORY_KEY = () => userStorageKey("content_ai_wp_user_history_v1");
    const FORM_STATE_KEY = () => userStorageKey("content_ai_form_state_v1");
    let _internalCandidates = [];
    let _pendingInternalCandidatesRestore = null;
    const collectInternalCandidateAnchors = () => {
        const out = {};
        document.querySelectorAll("input.internal-link-anchor-input[data-idx]").forEach((inp) => {
            const idx = inp.getAttribute("data-idx");
            if (idx == null || idx === "") return;
            const v = String(inp.value || "").trim();
            if (v) out[idx] = v;
        });
        return out;
    };
    const INTERNAL_LINK_USE_LLM_KEY = "contentAiInternalLinkUseLlm";
    const getInternalLinkUseLlm = () => {
        try {
            return localStorage.getItem(INTERNAL_LINK_USE_LLM_KEY) === "1";
        } catch (_) {
            return false;
        }
    };
    const syncLlmSwitchHighlight = (inputEl) => {
        const el = inputEl || byId("internalLinkUseLlm") || byId("customLinkUseLlm");
        if (!el) return;
        const lbl = el.closest(".il-llm-switch");
        if (lbl) lbl.classList.toggle("is-on", !!el.checked);
    };
    const setInternalLinkUseLlm = (on) => {
        try {
            localStorage.setItem(INTERNAL_LINK_USE_LLM_KEY, on ? "1" : "0");
        } catch (_) {}
        const el = byId("internalLinkUseLlm");
        if (el) {
            el.checked = !!on;
            syncLlmSwitchHighlight(el);
        }
    };
    const slimInternalCandidatesForStorage = (items) =>
        (Array.isArray(items) ? items : []).slice(0, 25).map((it) => ({
            title: String((it && it.title) || ""),
            link: String((it && it.link) || ""),
            slug: String((it && it.slug) || ""),
            anchor_text: String((it && it.anchor_text) || ""),
            target_primary_keyword: String((it && it.target_primary_keyword) || ""),
            kw_hint_primary: String((it && it.kw_hint_primary) || ""),
        }));
    const OUTPUT_FORMAT_KEY = "content_ai_output_format_v1";
    const OUTPUT_ACCORDION_KEY = "content_ai_output_accordion_open_v1";
    const setHint = (field, text) => {
        const el = byId(`hint-${field}`);
        if (el) el.textContent = text || "";
    };

    const _stripText = (html) => {
        const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
        return (doc && doc.body ? doc.body.textContent : "") || "";
    };
    const _firstLine = (s) => {
        const raw = String(s || "").replace(/\r/g, "");
        const parts = raw.split("\n").map((x) => x.trim()).filter(Boolean);
        return parts[0] || String(s || "").trim();
    };
    const _countSentences = (text) => {
        const t = String(text || "").replace(/\s+/g, " ").trim();
        if (!t) return 0;
        const parts = t.split(/[.!?]+/).map((x) => x.trim()).filter((x) => x.length >= 2);
        return parts.length;
    };
    const _countWords = (text) => {
        const t = String(text || "").replace(/\s+/g, " ").trim();
        if (!t) return 0;
        return t.split(" ").filter(Boolean).length;
    };
    const _countParagraphs = (html) => {
        const doc = new DOMParser().parseFromString(String(html || ""), "text/html");
        const ps = doc ? doc.querySelectorAll("p") : [];
        if (ps && ps.length) return ps.length;
        const t = _stripText(html);
        if (!t) return 0;
        return t.split(/\n{2,}/).filter((x) => x.trim()).length;
    };

    const _escapeHtml = (s) =>
        String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");

    const _splitSentences = (text) => {
        const t = String(text || "").replace(/\s+/g, " ").trim();
        if (!t) return [];
        // Split after punctuation (Vietnamese-friendly heuristic)
        const parts = t
            .split(/(?<=[.!?…])\s+/)
            .map((x) => x.trim())
            .filter(Boolean);
        return parts.length ? parts : [t];
    };

    const formatContentSeo = () => {
        // Treat current editor content as markdown-like if it contains leading # headings.
        const rawText = (() => {
            try {
                if (window.tinymce && tinymce.get("content")) {
                    return tinymce.get("content").getContent({ format: "text" }) || "";
                }
            } catch (_) {}
            return _stripText(getContentValue());
        })();
        const lines = String(rawText || "")
            .replace(/\r\n/g, "\n")
            .split("\n")
            .map((l) => l.trim())
            .filter((l) => l.length);
        if (!lines.length) return;

        const outHtml = [];
        let inUl = false;
        let inOl = false;
        let tableRows = null;

        const closeLists = () => {
            if (inUl) {
                outHtml.push("</ul>");
                inUl = false;
            }
            if (inOl) {
                outHtml.push("</ol>");
                inOl = false;
            }
        };
        const isMdTableSep = (cells) =>
            cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(String(c || "").trim()));
        const flushTable = () => {
            if (!tableRows || tableRows.length < 2) {
                tableRows = null;
                return;
            }
            const header = tableRows[0];
            const body = tableRows.slice(1).filter((row) => !isMdTableSep(row));
            outHtml.push('<div class="digiseo-table-wrap"><table class="digiseo-table"><thead><tr>');
            header.forEach((c) => outHtml.push(`<th>${_escapeHtml(c)}</th>`));
            outHtml.push("</tr></thead><tbody>");
            body.forEach((row) => {
                outHtml.push("<tr>");
                row.forEach((c) => outHtml.push(`<td>${_escapeHtml(c)}</td>`));
                outHtml.push("</tr>");
            });
            outHtml.push("</tbody></table></div>");
            tableRows = null;
        };

        const pushParagraphs = (text) => {
            const sentences = _splitSentences(text);
            sentences.forEach((s) => outHtml.push(`<p>${_escapeHtml(s)}</p>`));
        };

        for (const line of lines) {
            const mH = line.match(/^(#{1,6})\s+(.*)$/);
            if (mH) {
                closeLists();
                const lvl = Math.min(3, Math.max(1, mH[1].length)); // cap to h1-h3 for readability
                const txt = mH[2].trim();
                outHtml.push(`<h${lvl}>${_escapeHtml(txt)}</h${lvl}>`);
                continue;
            }
            const mOl = line.match(/^(\d+)[.)]\s+(.*)$/);
            if (mOl) {
                if (inUl) closeLists();
                if (!inOl) {
                    outHtml.push("<ol>");
                    inOl = true;
                }
                outHtml.push(`<li>${_escapeHtml(mOl[2].trim())}</li>`);
                continue;
            }
            const mUl = line.match(/^[-*]\s+(.*)$/);
            if (mUl) {
                if (inOl) closeLists();
                if (!inUl) {
                    outHtml.push("<ul>");
                    inUl = true;
                }
                outHtml.push(`<li>${_escapeHtml(mUl[1].trim())}</li>`);
                continue;
            }
            if (/\|/.test(line)) {
                const cells = line
                    .replace(/^\|/, "")
                    .replace(/\|$/, "")
                    .split("|")
                    .map((c) => c.trim());
                if (cells.length >= 2) {
                    closeLists();
                    if (!tableRows) tableRows = [];
                    tableRows.push(cells);
                    continue;
                }
            }
            flushTable();
            closeLists();
            pushParagraphs(line);
        }
        flushTable();
        closeLists();

        // Ensure we have a H1 if user forgot
        const hasH1 = outHtml.some((x) => x.startsWith("<h1>"));
        const titleText = byId("title").value.trim();
        if (!hasH1 && titleText) {
            outHtml.unshift(`<h1>${_escapeHtml(titleText)}</h1>`);
        }

        setContentValue(outHtml.join("\n"));
        refreshPreview();
    };
    const refreshPreview = () => {
        const contentHtml = getContentValue();
        const text = _stripText(contentHtml);
        const words = _countWords(text);
        const chars = text.length;
        const sentences = _countSentences(text);
        const paragraphs = _countParagraphs(contentHtml);
        const pages = words ? (words / 260) : 0; // ~260 words/page
        if (statWords) statWords.textContent = String(words);
        if (statChars) statChars.textContent = String(chars);
        if (statSentences) statSentences.textContent = String(sentences);
        if (statParagraphs) statParagraphs.textContent = String(paragraphs);
        if (statPages) statPages.textContent = pages ? pages.toFixed(2) : "0";
        const element = byId("contentRender");
        const content = String(contentHtml || "");
        // In contenteditable mode, do not rewrite editor DOM on refresh
        // to keep caret/range stable for image insertion at cursor position.
        if (element && USE_TINYMCE && document.activeElement !== element) element.innerHTML = content;
        const ta = byId("content");
        if (ta) ta.value = content;
    };

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
        if (ed) {
            try {
                const v = String(ed.getContent({ format: "html" }) || "");
                if (v.trim()) return v;
            } catch (_) {}
        }
        const cr = byId("contentRender");
        const crVal = cr ? String(cr.innerHTML || "") : "";
        if (crVal.trim()) return crVal;
        const ta = byId("content");
        const taVal = ta ? String(ta.value || "") : "";
        if (taVal.trim()) return taVal;
        return "";
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
    const autoInjectBlockquoteForContent = async (html) => {
        const src = decodeHtmlEntitiesDeep(String(html || ""));
        if (!src.trim()) return src;
        try {
            const res = await fetch(`/content-ai/postprocess-content?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ content_html: src }),
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
    const _pclStatusLabel = { ok: "Đạt", warn: "Cần xem", fail: "Chưa đạt", manual: "Thủ công" };
    const renderPublishChecklist = (data) => {
        if (!publishChecklistPanel || !publishChecklistList) return;
        const items = data && Array.isArray(data.items) ? data.items : [];
        if (!items.length) {
            publishChecklistPanel.style.display = "none";
            return;
        }
        publishChecklistList.innerHTML = items
            .map((it) => {
                const st = String(it.status || "warn");
                const badge = _pclStatusLabel[st] || st;
                const label = String(it.label || "").replace(/</g, "&lt;");
                const detail = String(it.detail || "").replace(/</g, "&lt;");
                return (
                    `<li><span class="pcl-badge ${st}">${badge}</span>` +
                    `<span class="pcl-body"><strong>${label}</strong>${detail}</span></li>`
                );
            })
            .join("");
        publishChecklistPanel.style.display = "block";
    };
    const refreshPublishChecklist = async () => {
        if (!publishChecklistPanel || !publishChecklistList) return;
        if (_publishChecklistBusy || _publishChecklistApplyingStrip) return;
        const pk = (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim();
        const title = (byId("title") && byId("title").value || "").trim();
        const meta = (byId("meta") && byId("meta").value || "").trim();
        const contentHtml = String(getContentValue() || "");
        if (!contentHtml.trim() && !title && !meta) {
            publishChecklistPanel.style.display = "none";
            return;
        }
        _publishChecklistBusy = true;
        try {
            const res = await fetch(`/content-ai/publish-checklist?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    title,
                    meta_description: meta,
                    content_html: contentHtml,
                    primary_keyword: pk,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) return;
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

    const contentScorePanel = byId("contentScorePanel");
    const contentScoreNum = byId("contentScoreNum");
    const contentScoreGrade = byId("contentScoreGrade");
    const contentScoreRing = byId("contentScoreRing");
    const contentScoreMeta = byId("contentScoreMeta");
    const contentScorePillars = byId("contentScorePillars");
    const contentScoreMissingWrap = byId("contentScoreMissingWrap");
    const contentScoreMissingList = byId("contentScoreMissingList");
    const contentScoreWarnWrap = byId("contentScoreWarnWrap");
    const contentScoreWarnList = byId("contentScoreWarnList");
    const contentScoreSuggestWrap = byId("contentScoreSuggestWrap");
    const contentScoreSuggestList = byId("contentScoreSuggestList");
    const btnContentScore = byId("btnContentScore");
    const _contentScorePillarLabels = {
        search_intent: "Search intent",
        title_meta_slug: "Title / Meta / Slug",
        heading_structure: "Heading",
        keyword_semantic: "Từ khóa",
        content_depth: "Độ sâu",
        eeat_helpful: "E-E-A-T",
        internal_link: "Internal link",
        image_alt: "Ảnh / Alt",
        readability: "Dễ đọc",
        cta: "CTA",
    };
    const _escScoreHtml = (s) => String(s || "").replace(/</g, "&lt;");
    const collectPlannedInternalLinks = () => {
        const out = [];
        if (!internalLinkCandidates) return out;
        internalLinkCandidates.querySelectorAll("tr[data-idx]").forEach((tr) => {
            const cb = tr.querySelector("input.internal-link-cb");
            if (cb && !cb.checked) return;
            const urlEl = tr.querySelector(".internal-target-url");
            const anchorInp = tr.querySelector(".internal-link-anchor-input");
            const url = urlEl ? String(urlEl.textContent || "").trim() : "";
            const anchor_text = anchorInp ? String(anchorInp.value || "").trim() : "";
            if (url) out.push({ url, anchor_text });
        });
        return out;
    };
    const renderContentScore = (data) => {
        if (!contentScorePanel) return;
        const score = Number(data && data.total_score);
        const grade = String((data && data.grade) || "—");
        if (!Number.isFinite(score)) {
            contentScorePanel.style.display = "none";
            return;
        }
        if (contentScoreNum) contentScoreNum.textContent = String(score);
        if (contentScoreGrade) contentScoreGrade.textContent = grade;
        if (contentScoreRing) {
            contentScoreRing.classList.remove("cs-high", "cs-mid", "cs-low");
            if (score >= 75) contentScoreRing.classList.add("cs-high");
            else if (score >= 50) contentScoreRing.classList.add("cs-mid");
            else contentScoreRing.classList.add("cs-low");
        }
        const wc = data && data.word_count != null ? Number(data.word_count) : null;
        const mode = String((data && data.scoring_mode) || "rule_based");
        if (contentScoreMeta) {
            const parts = [];
            if (Number.isFinite(wc)) parts.push(`~${wc} từ`);
            parts.push(mode === "rule_based" ? "rule-based" : mode);
            contentScoreMeta.textContent = parts.join(" · ");
        }
        if (contentScorePillars && data && data.detail_scores) {
            const ds = data.detail_scores;
            contentScorePillars.innerHTML = Object.keys(_contentScorePillarLabels)
                .map((key) => {
                    const row = ds[key] || {};
                    const sc = Number(row.score);
                    const st = String(row.status || "");
                    const label = _contentScorePillarLabels[key] || key;
                    const val = Number.isFinite(sc) ? `${sc}/100` : "—";
                    return (
                        `<div class="content-score-pillar" title="${_escScoreHtml(key)}">` +
                        `<span class="csp-label">${_escScoreHtml(label)}</span>` +
                        `<span class="csp-val">${_escScoreHtml(val)} ${st ? "· " + _escScoreHtml(st) : ""}</span></div>`
                    );
                })
                .join("");
        }
        const fillList = (wrap, listEl, items) => {
            if (!wrap || !listEl) return;
            const arr = Array.isArray(items) ? items.filter(Boolean) : [];
            if (!arr.length) {
                wrap.style.display = "none";
                listEl.innerHTML = "";
                return;
            }
            wrap.style.display = "block";
            listEl.innerHTML = arr.map((t) => `<li>${_escScoreHtml(t)}</li>`).join("");
        };
        fillList(contentScoreMissingWrap, contentScoreMissingList, data && data.missing_items);
        fillList(contentScoreWarnWrap, contentScoreWarnList, data && data.warning_items);
        fillList(contentScoreSuggestWrap, contentScoreSuggestList, data && data.suggestions);
        contentScorePanel.style.display = "block";
    };
    const refreshContentScore = async () => {
        if (!contentScorePanel) return;
        const title = (byId("title") && byId("title").value || "").trim();
        const slug = (byId("slug") && byId("slug").value || "").trim();
        const meta = (byId("meta") && byId("meta").value || "").trim();
        const pk = (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim();
        const sk = (byId("secondaryKeywords") && byId("secondaryKeywords").value || "").trim();
        const html_content = String(getContentValue() || "");
        const target_website = normalizeTargetBase(String(byId("targetWebsite") && byId("targetWebsite").value || "").trim());
        const internal_links = collectPlannedInternalLinks();
        try {
            const res = await fetch(`/content-ai/score?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    title,
                    slug,
                    meta_description: meta,
                    primary_keyword: pk,
                    secondary_keywords: sk,
                    html_content,
                    target_word_count: parseTargetWordCount(),
                    target_website,
                    internal_links: internal_links.length ? internal_links : null,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const msg = (data && data.detail) || "Chấm điểm thất bại.";
                setHint("content", typeof msg === "string" ? msg : JSON.stringify(msg));
                return;
            }
            renderContentScore(data);
            setHint("content", `Điểm SEO: ${data.total_score}/100 (${data.grade}) — chỉ gợi ý, không chặn publish.`);
        } catch (e) {
            setHint("content", "Lỗi kết nối khi chấm điểm SEO.");
        }
    };
    if (btnContentScore) {
        btnContentScore.addEventListener("click", async (ev) => {
            ev.preventDefault();
            const old = btnContentScore.textContent;
            btnContentScore.disabled = true;
            btnContentScore.textContent = "Đang chấm...";
            try {
                await refreshContentScore();
            } finally {
                btnContentScore.disabled = false;
                btnContentScore.textContent = old;
            }
        });
    }

    const contentBriefPanel = byId("contentBriefPanel");
    const contentBriefGrid = byId("contentBriefGrid");
    const contentBriefOutline = byId("contentBriefOutline");
    const contentBriefMode = byId("contentBriefMode");
    const btnCreateContentBrief = byId("btnCreateContentBrief");
    const btnApplyBriefOutline = byId("btnApplyBriefOutline");
    const collectInternalLinkCandidatesForBrief = () => {
        const fromTable = collectPlannedInternalLinks();
        if (fromTable.length) return fromTable;
        return (_internalCandidates || [])
            .slice(0, 8)
            .map((it) => ({
                url: String(it.link || it.url || "").trim(),
                title: String(it.title || "").trim(),
                anchor_text: String(it.suggested_anchor || it.anchor_text || "").trim(),
            }))
            .filter((x) => x.url);
    };
    const renderContentBrief = (brief) => {
        if (!contentBriefPanel) return;
        if (!brief || typeof brief !== "object") {
            contentBriefPanel.style.display = "none";
            return;
        }
        const cells = [
            ["Search intent", brief.search_intent],
            ["Loại bài", brief.content_type],
            ["Đối tượng", brief.target_audience],
            ["Mục tiêu", brief.content_goal],
            ["Góc viết (angle)", brief.angle],
            ["Số từ đề xuất", brief.recommended_word_count],
            ["Title gợi ý", brief.suggested_title],
            ["Meta gợi ý", brief.suggested_meta_description],
        ];
        if (contentBriefGrid) {
            contentBriefGrid.innerHTML = cells
                .map(
                    ([k, v]) =>
                        `<div class="cbb"><span class="cbb-k">${_escScoreHtml(k)}</span>` +
                        `<span class="cbb-v">${_escScoreHtml(String(v || "—"))}</span></div>`
                )
                .join("");
        }
        const fillUl = (wrapId, listId, items) => {
            const wrap = byId(wrapId);
            const list = byId(listId);
            if (!wrap || !list) return;
            const arr = Array.isArray(items) ? items.filter(Boolean) : [];
            if (!arr.length) {
                wrap.style.display = "none";
                list.innerHTML = "";
                return;
            }
            wrap.style.display = "block";
            list.innerHTML = arr
                .map((t) => {
                    if (typeof t === "object" && t && t.url) {
                        return (
                            `<li>${_escScoreHtml(t.anchor_suggestion || "")} → ` +
                            `<code>${_escScoreHtml(t.url)}</code> (${_escScoreHtml(t.placement_hint || "")})</li>`
                        );
                    }
                    return `<li>${_escScoreHtml(String(t))}</li>`;
                })
                .join("");
        };
        fillUl("contentBriefEntitiesWrap", "contentBriefEntities", brief.required_entities);
        fillUl("contentBriefFaqWrap", "contentBriefFaq", brief.faq_questions);
        fillUl("contentBriefLinksWrap", "contentBriefLinks", brief.internal_link_plan);
        const eeatCta = []
            .concat(brief.eeat_suggestions || [])
            .concat((brief.cta_suggestions || []).map((c) => `CTA: ${c}`));
        fillUl("contentBriefEeatWrap", "contentBriefEeat", eeatCta);
        fillUl("contentBriefWarnWrap", "contentBriefWarnings", brief.warnings);
        if (contentBriefOutline) contentBriefOutline.textContent = String(brief.outline || "");
        if (contentBriefMode) {
            const mode = String(brief.brief_mode || "rule_based");
            const kb = brief.knowledge_used ? " · KB" : "";
            contentBriefMode.textContent = `${mode}${kb}`;
        }
        contentBriefPanel.style.display = "block";
        if (btnApplyBriefOutline) btnApplyBriefOutline.style.display = "inline-block";
    };
    const refreshContentBrief = async () => {
        const pk = (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim();
        if (!pk) {
            setHint("content-brief", "Nhập từ khóa chính trước khi tạo Brief.");
            return null;
        }
        const internal_link_candidates = collectInternalLinkCandidatesForBrief();
        const res = await fetch(`/content-ai/brief?ts=${Date.now()}`, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify({
                primary_keyword: pk,
                secondary_keywords: (byId("secondaryKeywords") && byId("secondaryKeywords").value || "").trim(),
                title: (byId("title") && byId("title").value || "").trim(),
                target_website: normalizeTargetBase(String(byId("targetWebsite") && byId("targetWebsite").value || "").trim()),
                target_word_count: parseTargetWordCount(),
                competitor_url: (byId("competitorUrl") && byId("competitorUrl").value || "").trim(),
                brand_name: "",
                content_type: "",
                category: (byId("tags") && byId("tags").value || "").trim(),
                tags: (byId("tags") && byId("tags").value || "").trim(),
                existing_outline: (byId("outlineContent") && byId("outlineContent").value || "").trim(),
                internal_link_candidates: internal_link_candidates.length ? internal_link_candidates : null,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data && data.detail;
            const errMsg =
                typeof detail === "string"
                    ? detail
                    : detail && detail.message
                      ? detail.message
                      : "Tạo Content Brief thất bại.";
            throw new Error(errMsg);
        }
        if (data.search_intent_raw) setDetectedIntentDebug(data.search_intent_raw);
        return data;
    };
    if (btnCreateContentBrief) {
        btnCreateContentBrief.addEventListener("click", async (ev) => {
            ev.preventDefault();
            const old = btnCreateContentBrief.textContent;
            btnCreateContentBrief.disabled = true;
            btnCreateContentBrief.textContent = "Đang tạo Brief...";
            try {
                const brief = await refreshContentBrief();
                if (brief) {
                    _contentAiBrief = brief;
                    renderContentBrief(brief);
                    setHint("content-brief", "Đã tạo Brief — dùng khi «Tạo content» (nếu có LLM).");
                    scheduleSaveFormState();
                }
            } catch (e) {
                setHint("content-brief", String((e && e.message) || e));
            } finally {
                btnCreateContentBrief.disabled = false;
                btnCreateContentBrief.textContent = old;
            }
        });
    }
    if (btnApplyBriefOutline) {
        btnApplyBriefOutline.addEventListener("click", (ev) => {
            ev.preventDefault();
            if (!_contentAiBrief || !_contentAiBrief.outline) {
                setHint("content-brief", "Chưa có outline trong Brief.");
                return;
            }
            const oc = byId("outlineContent");
            if (oc) {
                oc.value = String(_contentAiBrief.outline || "");
                autoGrowOutline();
            }
            if (!byId("title").value.trim() && _contentAiBrief.suggested_title) {
                byId("title").value = String(_contentAiBrief.suggested_title);
            }
            if (!byId("meta").value.trim() && _contentAiBrief.suggested_meta_description) {
                byId("meta").value = String(_contentAiBrief.suggested_meta_description);
            }
            if (_contentAiBrief.recommended_word_count && byId("targetWordCount")) {
                byId("targetWordCount").value = String(_contentAiBrief.recommended_word_count);
            }
            setHint("content-brief", "Đã áp dụng outline/title/meta từ Brief.");
            scheduleSaveFormState();
        });
    }

    const contentGapPanel = byId("contentGapPanel");
    const contentGapScoreNum = byId("contentGapScoreNum");
    const contentGapRing = byId("contentGapRing");
    const contentGapSeverity = byId("contentGapSeverity");
    const contentGapMeta = byId("contentGapMeta");
    const btnContentGap = byId("btnContentGap");
    const _cgSeverityLabels = { good: "Tốt", warning: "Cần bổ sung", poor: "Thiếu nhiều" };
    const renderContentGap = (data) => {
        if (!contentGapPanel) return;
        const score = Number(data && data.gap_score);
        if (!Number.isFinite(score)) {
            contentGapPanel.style.display = "none";
            return;
        }
        const sev = String((data && data.severity) || "warning");
        if (contentGapScoreNum) contentGapScoreNum.textContent = String(score);
        if (contentGapRing) {
            contentGapRing.classList.remove("sev-good", "sev-warning", "sev-poor");
            contentGapRing.classList.add(
                sev === "good" ? "sev-good" : sev === "poor" ? "sev-poor" : "sev-warning"
            );
        }
        if (contentGapSeverity) {
            contentGapSeverity.textContent = `/100 · ${_cgSeverityLabels[sev] || sev}`;
        }
        if (contentGapMeta) {
            const parts = [];
            if (data.word_count != null) parts.push(`~${data.word_count} từ trong bài`);
            if (data.brief_used) parts.push("có Brief");
            parts.push(data.analysis_mode || "rule_based");
            contentGapMeta.textContent = parts.join(" · ");
        }
        const fillGapList = (wrapId, listId, items, missingStyle) => {
            const wrap = byId(wrapId);
            const list = byId(listId);
            if (!wrap || !list) return;
            const arr = Array.isArray(items) ? items.filter(Boolean) : [];
            if (!arr.length) {
                wrap.style.display = "none";
                list.innerHTML = "";
                return;
            }
            wrap.style.display = "block";
            list.className = "content-gap-list" + (missingStyle ? " cg-missing" : " cg-suggest");
            list.innerHTML = arr.map((t) => `<li>${_escScoreHtml(String(t))}</li>`).join("");
        };
        fillGapList("contentGapSectionsWrap", "contentGapSectionsList", data.missing_sections, true);
        fillGapList("contentGapEntitiesWrap", "contentGapEntitiesList", data.missing_entities, true);
        fillGapList("contentGapFaqWrap", "contentGapFaqList", data.missing_faq, true);
        fillGapList("contentGapLinksWrap", "contentGapLinksList", data.missing_internal_links, true);
        fillGapList("contentGapCtaWrap", "contentGapCtaList", data.missing_cta, true);
        fillGapList("contentGapThinWrap", "contentGapThinList", data.thin_sections, false);
        const suggestions = []
            .concat(data.improvement_suggestions || [])
            .concat(data.generic_sections || []);
        fillGapList("contentGapSuggestWrap", "contentGapSuggestList", suggestions, false);
        fillGapList(
            "contentGapOutlineAddWrap",
            "contentGapOutlineAddList",
            data.suggested_outline_additions,
            false
        );
        fillGapList("contentGapBlocksWrap", "contentGapBlocksList", data.suggested_content_blocks, false);
        contentGapPanel.style.display = "block";
    };
    const refreshContentGap = async () => {
        const html_content = String(getContentValue() || "");
        const pk = (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim();
        const internal_links = collectInternalLinkCandidatesForBrief();
        const res = await fetch(`/content-ai/content-gap?ts=${Date.now()}`, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify({
                title: (byId("title") && byId("title").value || "").trim(),
                primary_keyword: pk,
                secondary_keywords: (byId("secondaryKeywords") && byId("secondaryKeywords").value || "").trim(),
                html_content,
                target_word_count: parseTargetWordCount(),
                content_brief: _contentAiBrief || null,
                competitor_outline: _competitorOutlineCache || "",
                internal_links: internal_links.length ? internal_links : null,
                target_website: normalizeTargetBase(String(byId("targetWebsite") && byId("targetWebsite").value || "").trim()),
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data && data.detail;
            const errMsg =
                typeof detail === "string"
                    ? detail
                    : detail && detail.message
                      ? detail.message
                      : "Phân tích Content Gap thất bại.";
            throw new Error(errMsg);
        }
        return data;
    };
    if (btnContentGap) {
        btnContentGap.addEventListener("click", async (ev) => {
            ev.preventDefault();
            const old = btnContentGap.textContent;
            btnContentGap.disabled = true;
            btnContentGap.textContent = "Đang phân tích...";
            try {
                const data = await refreshContentGap();
                renderContentGap(data);
                setHint(
                    "content",
                    `Content Gap: ${data.gap_score}/100 (${_cgSeverityLabels[data.severity] || data.severity}) — chỉ gợi ý, không sửa HTML.`
                );
            } catch (e) {
                setHint("content", String((e && e.message) || e));
            } finally {
                btnContentGap.disabled = false;
                btnContentGap.textContent = old;
            }
        });
    }

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
    const setContentValue = (html) => {
        const v = decodeHtmlEntitiesDeep(String(html || ""));
        const ta = byId("content");
        if (ta) ta.value = v;
        const element = byId("contentRender");
        if (element) element.innerHTML = v;
        const ed = getEditorInstance();
        if (ed) {
            try {
                ed.setContent(v, { format: "html" });
                ed.save();
                ed.nodeChanged();
            } catch (_) {}
        }
        syncPreviewFallback();
        schedulePublishChecklist();
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
    const parseTargetWordCount = () => {
        const raw = String((byId("targetWordCount") && byId("targetWordCount").value) || "").trim();
        if (!raw) return 1000;
        // Accept formats like "1200", "1.200", "1,200", "1200 chữ".
        const digits = raw.replace(/[^\d]/g, "");
        const n = parseInt(digits || "1000", 10);
        return Number.isFinite(n) ? Math.max(200, Math.min(n, 20000)) : 1000;
    };
    let _contentAiBrief = null;
    let _competitorOutlineCache = "";
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
        content: getContentValue(),
        scheduled_at: byId("scheduledAt").value || "",
        featured_image: uploadedImages[0] || "",
        gallery_images: uploadedImages.slice(),
        content_brief: _contentAiBrief || null,
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
    const syncSlugFromPrimary = () => {
        const strict = buildStrictSlug();
        if (!strict) return;
        byId("slug").value = strict;
    };
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
        const clean = items.map(normalizeStoredProfile).filter(Boolean);
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
    /** Khi Edit site / dự án — chỉ hiển thị & sửa đúng một website (không liệt kê site khác). */
    let _wpProfilesFocusSiteKey = "";
    /** Mở «Thêm site đăng bài» — form trống, không hiện card site cũ phía trên form; lưu vẫn cộng thêm site. */
    let _wpProfilesAddNewMode = false;
    const wpProfilesBackdropEl = byId("wpProfilesBackdrop");
    const wpProfilesModalEl = byId("wpProfilesModal");
    const resolveWpPublishCredentials = () => {
        const wpUrlRaw = byId("wpUrl") ? String(byId("wpUrl").value || "").trim() : "";
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
                app_password = String(p.app_password || "");
                seo_plugin = String(p.seo_plugin || "auto").trim() || "auto";
            }
        }
        return { wpUrl, username, app_password, seo_plugin };
    };
    const resolveWpPublishCredentialsForSite = (siteUrlRaw) => {
        const raw = String(siteUrlRaw || "").trim();
        const wpUrl = normalizeWpUrl(raw) || raw;
        const key = connectedSiteKey(wpUrl);
        let username = "";
        let app_password = "";
        if (key) {
            const p = readSiteProfiles().find(
                (x) => normalizePlatform(x.platform) === "wordpress" && connectedSiteKey(profileSiteUrl(x)) === key,
            );
            if (p) {
                username = String(p.username || "").trim();
                app_password = String(p.app_password || "");
            }
        }
        return { wpUrl, username, app_password };
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
            if (typeof d.message === "string" && d.message.trim()) return d.message.trim();
            if (typeof d.msg === "string" && d.msg.trim()) return d.msg.trim();
        }
        if (Array.isArray(d)) return d.map((x) => (x && x.msg) ? x.msg : JSON.stringify(x)).join("; ");
        return String(d);
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
    const deleteConfirmBackdropEl = byId("deleteConfirmBackdrop");
    const deleteConfirmModalEl = byId("deleteConfirmModal");
    let _deleteConfirmResolve = null;
    let _siteArticlesModalCtx = { base: "", label: "" };
    const closeDeleteConfirmModal = (confirmed) => {
        if (deleteConfirmBackdropEl) deleteConfirmBackdropEl.classList.remove("open");
        if (deleteConfirmModalEl) {
            deleteConfirmModalEl.classList.remove("open");
            deleteConfirmModalEl.setAttribute("aria-hidden", "true");
        }
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
            if (deleteConfirmBackdropEl) deleteConfirmBackdropEl.classList.add("open");
            if (deleteConfirmModalEl) {
                deleteConfirmModalEl.classList.add("open");
                deleteConfirmModalEl.setAttribute("aria-hidden", "false");
            }
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
    document.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        if (deleteConfirmModalEl && deleteConfirmModalEl.classList.contains("open")) {
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
            { wrap: byId("contentAiConnectedSitesListSidebar"), hint: byId("hintConnectedSitesSidebar") },
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
    const fetchSuggestion = async (field, ctx) => {
        const res = await fetch(`/content-ai/suggest?ts=${Date.now()}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ field, ...ctx }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(fmtApiDetail(data.detail) || data.message || "Gợi ý AI thất bại.");
        return {
            value: (data && data.value) ? data.value : "",
            detected_intent: (data && data.detected_intent) ? data.detected_intent : "",
        };
    };

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

    const streamSuggestion = async (field, ctx) => {
        // fallback=true: if LLM fails (quota), backend will use deterministic generator
        const url = `/content-ai/suggest-stream?ts=${Date.now()}&delay_ms=2&fallback=true`;
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ field, ...ctx }),
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(fmtApiDetail(data.detail) || data.message || `Gợi ý AI thất bại (HTTP ${res.status})`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        let finalValue = "";
        let sawChunk = false;
        let streamErrorMsg = "";

        // Typewriter effect for "content" stream:
        // We progressively reveal STRIPPED TEXT (not raw HTML) to avoid breaking tags mid-stream.
        let typingTimer = null;
        let typingTargetText = "";
        let typingTypedLen = 0;
        let typingCps = 560; // faster chars per second (auto-adjust by chunk speed)
        let typingLastChunkAt = 0;
        let typingLastTargetLen = 0;

        const _stripTextWithNewlines = (html) => {
            try {
                // Works with full HTML and also incomplete HTML fragments during streaming.
                const src = String(html || "")
                    .replace(/<\s*br\s*\/?>/gi, "\n")
                    .replace(/<\s*\/\s*(p|h1|h2|h3|h4|li|blockquote|tr)\s*>/gi, "\n")
                    .replace(/<\s*li[^>]*>/gi, "\n• ")
                    .replace(/<[^>]+>/g, " ");
                const txt = src
                    .replace(/&nbsp;/gi, " ")
                    .replace(/&amp;/gi, "&")
                    .replace(/&lt;/gi, "<")
                    .replace(/&gt;/gi, ">")
                    .replace(/\r/g, "")
                    .replace(/[ \t]+\n/g, "\n")
                    .replace(/\n{3,}/g, "\n\n")
                    .replace(/[ \t]{2,}/g, " ")
                    .trim();
                return txt;
            } catch (_) {
                return String(html || "");
            }
        };

        const _ensureTypingTimer = () => {
            if (typingTimer) return;
            const cr = byId("contentRender");
            if (!cr) return;
            if (genStream) genStream.classList.add("typing");
            typingTimer = window.setInterval(() => {
                const cr2 = byId("contentRender");
                if (!cr2) return;
                if (!typingTargetText) return;
                const intervalMs = 16;
                const step = Math.max(1, Math.round((typingCps * intervalMs) / 1000));
                typingTypedLen = Math.min(typingTargetText.length, typingTypedLen + step);
                const typed = typingTargetText.slice(0, typingTypedLen);
                cr2.textContent = typed;
                cr2.scrollTop = cr2.scrollHeight;
                if (genStream) {
                    genStream.textContent = typed;
                    genStream.scrollTop = genStream.scrollHeight;
                }
            }, 16);
        };

        const clampPct = (n) => Math.max(0, Math.min(100, Number(n || 0)));

        const onEvent = (evtName, dataObj) => {
            if (evtName === "meta") {
                if (genHint) genHint.textContent = "Đang tạo nội dung...";
                return;
            }
            if (evtName === "chunk") {
                sawChunk = true;
                const pct = clampPct(dataObj && dataObj.pct);
                if (genFill) genFill.style.width = `${pct}%`;
                if (genPct) genPct.textContent = `${pct}%`;
                if (inlineProgressFill) inlineProgressFill.style.width = `${pct}%`;
                if (inlineProgressPct) inlineProgressPct.textContent = `${pct}%`;
                if (previewLoadingFill) previewLoadingFill.style.width = `${pct}%`;
                if (previewLoadingPct) previewLoadingPct.textContent = `${pct}%`;
                if (field === "content" && dataObj && typeof dataObj.sofar === "string") {
                    // Update typing target, adjust speed based on how fast the stream grows.
                    typingTargetText = _stripTextWithNewlines(dataObj.sofar);

                    const now = Date.now();
                    const dt = typingLastChunkAt ? (now - typingLastChunkAt) / 1000 : 0;
                    const inc = typingTargetText.length - typingLastTargetLen;
                    if (dt > 0 && inc > 0) {
                        // Slightly smooth to avoid jitter.
                        const cps = inc / dt;
                        typingCps = Math.max(180, Math.min(2600, cps * 1.3));
                    }
                    typingLastChunkAt = now;
                    typingLastTargetLen = typingTargetText.length;

                    // If new target is shorter (shouldn't happen), clamp typed length.
                    typingTypedLen = Math.min(typingTypedLen, typingTargetText.length);

                    _ensureTypingTimer();
                }
                // Avoid showing raw HTML "code" during streaming.
                // We already have a typing preview in #contentRender.
                if (genStream && typingTargetText) {
                    genStream.textContent = typingTargetText.slice(0, typingTypedLen);
                    genStream.scrollTop = genStream.scrollHeight;
                }
                return;
            }
            if (evtName === "done") {
                finalValue = String((dataObj && dataObj.value) || "");
                if (field === "content") {
                    if (typingTimer) {
                        window.clearInterval(typingTimer);
                        typingTimer = null;
                    }
                    if (genStream) genStream.classList.remove("typing");
                    const fullPlain = _stripTextWithNewlines(finalValue);
                    typingTargetText = fullPlain;
                    typingTypedLen = fullPlain.length;
                    if (genStream) {
                        genStream.textContent = fullPlain;
                        genStream.scrollTop = genStream.scrollHeight;
                    }
                    if (!sawChunk && finalValue) {
                        const crTxt = byId("contentRender");
                        if (crTxt) {
                            crTxt.textContent = fullPlain;
                            crTxt.scrollTop = crTxt.scrollHeight;
                        }
                    }
                    // Post-process blockquotes (server) then sync editor.
                    void (async () => {
                        try {
                            finalValue = await autoInjectBlockquoteForContent(finalValue);
                            setContentValue(finalValue);
                            editorMode = "visual";
                            refreshEditorModeUi();
                            try { refreshPreview(); } catch (_) {}
                            window.setTimeout(ensureEditorVisible, 140);
                            window.setTimeout(ensureEditorVisible, 420);
                        } catch (_) {
                            setContentValue(finalValue);
                        }
                    })();
                }
                if (genFill) genFill.style.width = "100%";
                if (genPct) genPct.textContent = "100%";
                if (inlineProgressFill) inlineProgressFill.style.width = "100%";
                if (inlineProgressPct) inlineProgressPct.textContent = "100%";
                if (previewLoadingFill) previewLoadingFill.style.width = "100%";
                if (previewLoadingPct) previewLoadingPct.textContent = "100%";
                if (genHint) genHint.textContent = "Hoàn tất.";
                if (btnGenClose) btnGenClose.disabled = false;
                return;
            }
            if (evtName === "error") {
                const err = String((dataObj && dataObj.error) || "Unknown error");
                streamErrorMsg = err;
                if (genHint) genHint.textContent = err;
                if (btnGenClose) btnGenClose.disabled = false;
                if (typingTimer) {
                    window.clearInterval(typingTimer);
                    typingTimer = null;
                }
                if (genStream) genStream.classList.remove("typing");
                if (inlineProgress) inlineProgress.classList.remove("show");
                if (previewLoading) previewLoading.classList.remove("show");
            }
        };

        const parseBuffer = () => {
            // Normalize CRLF -> LF to support browsers/proxies that emit \r\n.
            if (buffer.indexOf("\r") >= 0) buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
            while (true) {
                const idx = buffer.indexOf("\n\n");
                if (idx < 0) break;
                const raw = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                const lines = raw.split("\n");
                let evt = "message";
                let data = "";
                for (const ln of lines) {
                    if (ln.startsWith("event:")) evt = ln.slice(6).trim();
                    if (ln.startsWith("data:")) data += ln.slice(5).trim();
                }
                if (!data) continue;
                try {
                    const obj = JSON.parse(data);
                    onEvent(evt, obj);
                } catch (_) {}
            }
        };

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            parseBuffer();
        }
        parseBuffer();
        // Hard fallback on client side: if stream broke/no final payload, call non-stream suggest API.
        if (field === "content" && !String(finalValue || "").trim()) {
            try {
                const fb = await fetchSuggestion("content", ctx);
                finalValue = String((fb && fb.value) || "");
                if (finalValue) {
                    finalValue = await autoInjectBlockquoteForContent(finalValue);
                    setContentValue(finalValue);
                    refreshEditorModeUi();
                    try { refreshPreview(); } catch (_) {}
                    if (inlineProgressFill) inlineProgressFill.style.width = "100%";
                    if (inlineProgressPct) inlineProgressPct.textContent = "100%";
                    if (previewLoadingFill) previewLoadingFill.style.width = "100%";
                    if (previewLoadingPct) previewLoadingPct.textContent = "100%";
                    if (genHint) genHint.textContent = "Hoàn tất (fallback).";
                }
            } catch (_) {}
        }
        if (field === "content" && !String(finalValue || "").trim() && streamErrorMsg) {
            throw new Error(streamErrorMsg);
        }
        return finalValue;
    };
    const appendPublishLog = (line) => {
        const ts = new Date().toLocaleTimeString("vi-VN");
        const old = publishLog.value ? `${publishLog.value}\n` : "";
        publishLog.value = `${old}[${ts}] ${line}`;
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
            headers: { "Content-Type": "application/json" },
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
        targetWordCount: (byId("targetWordCount") && byId("targetWordCount").value) || "1000",
        competitorUrl: byId("competitorUrl").value,
        competitorOutline: _competitorOutlineCache,
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
        contentAiBrief: _contentAiBrief,
        competitorOutline: _competitorOutlineCache,
    });
    let _saveFormStateTimer = null;
    const flushSaveFormState = () => {
        try {
            localStorage.setItem(FORM_STATE_KEY(), JSON.stringify(collectFormState()));
        } catch (_) {}
    };
    const scheduleSaveFormState = () => {
        if (_saveFormStateTimer) window.clearTimeout(_saveFormStateTimer);
        _saveFormStateTimer = window.setTimeout(() => {
            _saveFormStateTimer = null;
            flushSaveFormState();
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
            if (byId("targetWordCount")) byId("targetWordCount").value = String(s.targetWordCount || "1000");
            byId("competitorUrl").value = s.competitorUrl || "";
            _competitorOutlineCache = String(s.competitorOutline || "").trim();
            byId("replaceFrom").value = s.replaceFrom || "";
            byId("replaceTo").value = s.replaceTo || "";
            byId("outlineContent").value = s.outlineContent || "";
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
                if (u) uploadedImages.push(u);
            }
            activeProjectId = s.activeProjectId || "";
            const wpcSaved = String(s.singleWpCategoryId || "").trim();
            if (wpcSaved) {
                const n = parseInt(wpcSaved, 10);
                _draftWpCategoryIds = !Number.isNaN(n) && n > 0 ? [n] : null;
            }
            fillSingleWpCategorySelect(wpcSaved);
            renderUploadList();
            toggleAiAvailability();
            syncSlugFromPrimary();
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
            if (s.contentAiBrief && typeof s.contentAiBrief === "object") {
                _contentAiBrief = s.contentAiBrief;
                renderContentBrief(_contentAiBrief);
            }
            return true;
        } catch (_) {
            return false;
        }
    };
    const renderUploadList = () => {
        uploadList.innerHTML = "";
        if (!uploadedImages.length) return;
        uploadedImages.forEach((url, idx) => {
            const div = document.createElement("div");
            div.className = "upload-item";
            const meta = document.createElement("div");
            meta.className = "u-meta";
            meta.innerHTML = `<div><strong>${idx === 0 ? "Ảnh đại diện" : "Ảnh phụ"}</strong></div><div class="u-url">${String(url || "")}</div>`;
            const actions = document.createElement("div");
            actions.className = "u-actions";
            const bCrop = document.createElement("button");
            bCrop.type = "button";
            bCrop.className = "mini-btn";
            bCrop.textContent = "Cắt ảnh";
            bCrop.addEventListener("click", () => openCropModal(url));
            const bDel = document.createElement("button");
            bDel.type = "button";
            bDel.className = "mini-btn danger";
            bDel.textContent = "Xóa khỏi list";
            bDel.addEventListener("click", () => {
                const i = uploadedImages.indexOf(url);
                if (i >= 0) uploadedImages.splice(i, 1);
                renderUploadList();
                saveFormState();
            });
            actions.appendChild(bCrop);
            actions.appendChild(bDel);
            div.appendChild(meta);
            div.appendChild(actions);
            uploadList.appendChild(div);
        });
    };

    const renderGoogleImageResults = (items) => {
        if (!googleImageResults) return;
        googleImageResults.innerHTML = "";
        const arr = Array.isArray(items) ? items : [];
        if (!arr.length) return;
        arr.forEach((it) => {
            const wrap = document.createElement("div");
            wrap.className = "upload-item";
            wrap.style.flexDirection = "column";
            wrap.style.alignItems = "stretch";
            wrap.style.gap = "8px";
            const thumb = document.createElement("img");
            thumb.src = it.thumbnail || it.link;
            thumb.alt = it.title || "";
            thumb.loading = "lazy";
            thumb.style.width = "100%";
            thumb.style.height = "140px";
            thumb.style.objectFit = "cover";
            thumb.style.borderRadius = "10px";
            thumb.style.border = "1px solid rgba(255,255,255,0.18)";
            const title = document.createElement("div");
            title.style.fontWeight = "700";
            title.style.fontSize = "0.78rem";
            title.style.lineHeight = "1.25";
            title.textContent = (it.title || "").slice(0, 90) || "Google image";
            const actions = document.createElement("div");
            actions.className = "u-actions";
            actions.style.justifyContent = "flex-start";
            const bImport = document.createElement("button");
            bImport.type = "button";
            bImport.className = "mini-btn";
            bImport.textContent = "Import";
            bImport.addEventListener("click", async () => {
                try {
                    setHint("google-images", "Đang import ảnh...");
                    bImport.disabled = true;
                    const res = await fetch(`/content-ai/google-images/import?ts=${Date.now()}`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ url: it.link }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Import ảnh thất bại");
                    if (data.url) {
                        uploadedImages.push(data.url);
                        renderUploadList();
                        insertImageIntoEditor(data.url);
                        saveFormState();
                    }
                    setHint("google-images", "Đã import và chèn ảnh vào Content.");
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
            bCrop.addEventListener("click", async () => {
                try {
                    setHint("google-images", "Đang import ảnh để cắt...");
                    bCrop.disabled = true;
                    const res = await fetch(`/content-ai/google-images/import?ts=${Date.now()}`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
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
            wrap.appendChild(thumb);
            wrap.appendChild(title);
            wrap.appendChild(actions);
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
        const snippet = `<p><br></p><figure class="editor-image"><img src="${src}" alt="" loading="lazy" /></figure><p><br></p>`;
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
        byId("primaryKeyword").value = p.primary_keyword || "";
        byId("secondaryKeywords").value = (p.secondary_keywords || []).join(", ");
        byId("outlineContent").value = p.outline_content || "";
        byId("meta").value = p.meta_description || "";
        byId("tags").value = (p.tags || []).join(", ");
        setContentValue(p.content || "");
        byId("scheduledAt").value = p.scheduled_at || "";
        uploadedImages.length = 0;
        for (const u of (p.gallery_images || [])) uploadedImages.push(u);
        if ((p.featured_image || "").trim() && !uploadedImages.includes(p.featured_image)) {
            uploadedImages.unshift(p.featured_image);
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
            msg.textContent = "Đã tải đúng dữ liệu dự án.";
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
        if (_siteArticlesFilter === "setup_draft") {
            out = out.filter((p) => !!p.is_setup_draft);
        } else if (_siteArticlesFilter === "all") {
            out = out.filter((p) => !p.is_setup_draft);
        } else if (_siteArticlesFilter === "missing_section") {
            out = out.filter((p) => !p.has_section);
        } else if (_siteArticlesFilter === "ready") {
            out = out.filter((p) => String(p.status || "").toLowerCase() === "ready");
        } else if (_siteArticlesFilter === "published") {
            out = out.filter((p) => String(p.status || "").toLowerCase() === "published");
        }
        return out;
    };
    const countSiteArticles = (list) => {
        const all = list || [];
        let published = 0;
        let ready = 0;
        let missingSection = 0;
        let setupDraft = 0;
        all.forEach((p) => {
            const st = String(p.status || "").toLowerCase();
            if (p.is_setup_draft) setupDraft += 1;
            if (st === "published") published += 1;
            if (st === "ready") ready += 1;
            if (!p.has_section) missingSection += 1;
        });
        const allTab = Math.max(0, all.length - setupDraft);
        return { total: all.length, allTab, published, ready, missingSection, setupDraft };
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
                { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
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
    const autoInsertImagesAfterWriteEl = byId("autoInsertImagesAfterWrite");
    const btnAutoInsertImages = byId("btnAutoInsertImages");
    const btnSiteArticlesAutoImages = byId("btnSiteArticlesAutoImages");
    const restoreAutoInsertImagesPref = () => {
        try {
            if (!autoInsertImagesAfterWriteEl) return;
            const v = localStorage.getItem(AUTO_INSERT_IMAGES_KEY);
            if (v === "0") autoInsertImagesAfterWriteEl.checked = false;
            else if (v === "1") autoInsertImagesAfterWriteEl.checked = true;
        } catch (_) {}
    };
    const persistAutoInsertImagesPref = () => {
        try {
            if (!autoInsertImagesAfterWriteEl) return;
            localStorage.setItem(
                AUTO_INSERT_IMAGES_KEY,
                autoInsertImagesAfterWriteEl.checked ? "1" : "0",
            );
        } catch (_) {}
    };
    restoreAutoInsertImagesPref();
    if (autoInsertImagesAfterWriteEl) {
        autoInsertImagesAfterWriteEl.addEventListener("change", persistAutoInsertImagesPref);
    }
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
        const res = await fetch(
            `/content-ai/projects/${encodeURIComponent(pid)}/auto-insert-images?ts=${Date.now()}`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ max_inline: 4, update_featured: true, force: !!opts.force }),
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
        const payload = buildDraftPayload();
        const res = await fetch(`/content-ai/auto-insert-images?ts=${Date.now()}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
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

    /* AI Visual Content Studio */
    const studioGallery = byId("studioGallery");
    const studioIncludeText = byId("studioIncludeText");
    const studioTextHintWrap = byId("studioTextHintWrap");
    let studioPreviews = [];
    let studioSelectedIndex = 0;
    let studioCatalogCache = null;
    let studioLightboxIndex = 0;

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
        fillStudioSelect("studioOutputFormat", cat.output_formats || [
            { id: "webp", label_vi: "WEBP" },
            { id: "png", label_vi: "PNG" },
            { id: "jpeg", label_vi: "JPEG / JPG" },
        ], "id", "label_vi");
        const fmtEl = byId("studioOutputFormat");
        if (fmtEl && !fmtEl.value) fmtEl.value = "webp";
        toggleStudioCustomSize();
        refreshStudioH2Select();
    };

    const getStudioOutputFormat = () => {
        const el = byId("studioOutputFormat");
        const v = (el && el.value) || "webp";
        return String(v).toLowerCase() === "jpg" ? "jpeg" : String(v).toLowerCase();
    };

    const getStudioTargetDimensions = () => {
        const arEl = byId("studioAspectRatio");
        const aspectRatio = (arEl && arEl.value) || "16:9";
        if (aspectRatio === "custom") {
            const cw = parseInt(byId("studioCustomWidth")?.value || "800", 10);
            const ch = parseInt(byId("studioCustomHeight")?.value || "400", 10);
            return { width: cw, height: ch, size_preset: "" };
        }
        const m = /^(\d{3,4})x(\d{3,4})$/i.exec(aspectRatio);
        if (m) {
            return {
                width: parseInt(m[1], 10),
                height: parseInt(m[2], 10),
                size_preset: aspectRatio.toLowerCase(),
            };
        }
        return { width: null, height: null, size_preset: "" };
    };

    const openStudioLightbox = (urlOrIndex) => {
        const box = byId("studioLightbox");
        const img = byId("studioLightboxImg");
        const counter = byId("studioLightboxCounter");
        if (!box || !img || !studioPreviews.length) return;
        let idx = typeof urlOrIndex === "number" ? urlOrIndex : studioPreviews.findIndex((p) => p.url === urlOrIndex);
        if (idx < 0) idx = 0;
        studioLightboxIndex = idx;
        const p = studioPreviews[idx] || {};
        img.src = p.url || "";
        img.alt = p.alt || "Preview";
        img.classList.remove("is-zoomed");
        if (counter) {
            counter.textContent = `${idx + 1} / ${studioPreviews.length}`;
        }
        box.classList.add("open");
        box.setAttribute("aria-hidden", "false");
    };
    const closeStudioLightbox = () => {
        const box = byId("studioLightbox");
        const img = byId("studioLightboxImg");
        if (!box) return;
        box.classList.remove("open");
        box.setAttribute("aria-hidden", "true");
        if (img) {
            img.src = "";
            img.classList.remove("is-zoomed");
        }
    };
    const stepStudioLightbox = (delta) => {
        if (!studioPreviews.length) return;
        let next = studioLightboxIndex + delta;
        if (next < 0) next = studioPreviews.length - 1;
        if (next >= studioPreviews.length) next = 0;
        openStudioLightbox(next);
    };

    const setStudioHint = (text) => {
        const h = byId("hint-visual-studio");
        if (h) h.textContent = text || "";
    };

    const buildStudioGeneratePayload = (overrides = {}) => {
        const draft = buildDraftPayload();
        const selected = getSelectedStudioH2s();
        const arEl = byId("studioAspectRatio");
        const aspectRatio = (arEl && arEl.value) || "16:9";
        const custom = aspectRatio === "custom";
        const cw = parseInt(byId("studioCustomWidth")?.value || "800", 10);
        const ch = parseInt(byId("studioCustomHeight")?.value || "400", 10);
        const dims = getStudioTargetDimensions();
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
            output_format: getStudioOutputFormat(),
            size_preset: dims.size_preset || "",
            target_width: dims.width,
            target_height: dims.height,
            count: Math.max(2, Math.min(4, parseInt(byId("studioImageCount")?.value || "3", 10) || 3)),
            include_text: !!(studioIncludeText && studioIncludeText.checked),
            text_hint: (byId("studioTextHint") && byId("studioTextHint").value.trim()) || "",
        };
        return { ...base, ...overrides };
    };

    const studioBuildInsertExtras = () => {
        const dims = getStudioTargetDimensions();
        return {
            output_format: getStudioOutputFormat(),
            target_width: dims.width,
            target_height: dims.height,
        };
    };

    const renderStudioGallery = () => {
        if (!studioGallery) return;
        studioGallery.innerHTML = "";
        if (!studioPreviews.length) return;
        studioPreviews.forEach((p, idx) => {
            const card = document.createElement("div");
            card.className = "visual-studio-card" + (idx === studioSelectedIndex ? " selected" : "");
            const img = document.createElement("img");
            img.src = p.url;
            img.alt = p.alt || "Preview";
            img.loading = "lazy";
            img.className = "studio-thumb-click";
            img.title = "Bấm để xem ảnh lớn";
            img.addEventListener("click", (ev) => {
                ev.stopPropagation();
                openStudioLightbox(idx);
            });
            if (p.alt) {
                const altCap = document.createElement("div");
                altCap.className = "hint";
                altCap.style.cssText = "padding:2px 6px 0;margin:0;font-size:0.62rem;line-height:1.2;color:#94a3b8;";
                altCap.textContent = p.alt.length > 56 ? p.alt.slice(0, 54) + "…" : p.alt;
                card.appendChild(altCap);
            }
            card.appendChild(img);
            if (p.section_heading) {
                const cap = document.createElement("div");
                cap.className = "hint";
                cap.style.cssText = "padding:4px 6px;margin:0;font-size:0.68rem;line-height:1.2;";
                cap.textContent = p.section_heading.length > 42
                    ? p.section_heading.slice(0, 40) + "…"
                    : p.section_heading;
                card.appendChild(cap);
            }
            const btns = document.createElement("div");
            btns.className = "visual-studio-card-btns";
            const mk = (label, handler) => {
                const b = document.createElement("button");
                b.type = "button";
                b.className = "mini-btn";
                b.textContent = label;
                b.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    studioSelectedIndex = idx;
                    renderStudioGallery();
                    handler(p, idx);
                });
                return b;
            };
            btns.appendChild(mk("Chọn", () => {}));
            btns.appendChild(mk("Chèn bài", () => studioInsertSelected(p, "inline")));
            btns.appendChild(mk("Cuối bài", () => studioInsertSelected(p, "append")));
            btns.appendChild(mk("Featured", () => studioInsertSelected(p, "featured")));
            btns.appendChild(mk("Tải", () => studioDownloadPreview(p)));
            btns.appendChild(mk("Tạo lại", () => studioRegenerateOne(idx)));
            btns.appendChild(mk("Crop", () => {
                if (typeof openCropModal === "function") openCropModal(p.url);
            }));
            card.appendChild(btns);
            card.addEventListener("click", (ev) => {
                if (ev.target.closest("button")) return;
                studioSelectedIndex = idx;
                renderStudioGallery();
            });
            studioGallery.appendChild(card);
        });
    };

    const studioDownloadPreview = (preview) => {
        if (!preview || !preview.url) return;
        const a = document.createElement("a");
        a.href = preview.url;
        a.download = preview.filename || `studio-preview${preview.url.slice(preview.url.lastIndexOf("."))}`;
        a.rel = "noopener";
        document.body.appendChild(a);
        a.click();
        a.remove();
    };

    const studioInsertSelected = async (preview, mode) => {
        const pk = byId("primaryKeyword").value.trim();
        if (!pk) {
            setStudioHint("Cần từ khóa chính.");
            return;
        }
        const payload = buildStudioGeneratePayload();
        const insertH2 = preview.section_heading || payload.section_heading || "";
        const insertIdx = preview.h2_index != null ? preview.h2_index : payload.h2_index;
        setStudioHint(mode === "featured" ? "Đang đặt featured…" : "Đang chèn vào bài…");
        try {
            const res = await fetch("/content-ai/images/insert-selected?ts=" + Date.now(), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    url: preview.url,
                    mode,
                    project_id: activeProjectId || null,
                    content_html: payload.content_html,
                    title: payload.title,
                    primary_keyword: pk,
                    section_heading: insertH2,
                    h2_index: insertIdx,
                    alt: preview.alt || "",
                    ...studioBuildInsertExtras(),
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : "Chèn ảnh thất bại");
            }
            if (data.url && preview) preview.url = data.url;
            if (data.content) setContentValue(data.content);
            if (data.featured_image) {
                if (!uploadedImages.includes(data.featured_image)) uploadedImages.unshift(data.featured_image);
                renderUploadList();
            }
            if (data.gallery_images && Array.isArray(data.gallery_images)) {
                data.gallery_images.forEach((u) => {
                    const s = String(u || "").trim();
                    if (s && !uploadedImages.includes(s)) uploadedImages.push(s);
                });
                renderUploadList();
            }
            if (data.project && activeProjectId) applyProjectToForm(data.project);
            else if (mode === "inline" && preview.url) {
                try { insertImageIntoEditor(preview.url); } catch (_) {}
            }
            try { refreshPreview(); } catch (_) {}
            saveFormState();
            const pl = data.placement || {};
            const place = pl.placement
                ? ` (${pl.placement}${pl.placement_reason ? ": " + pl.placement_reason : ""})`
                : "";
            setStudioHint(
                data.ok
                    ? (mode === "featured"
                        ? "Đã đặt ảnh đại diện."
                        : mode === "append"
                            ? "Đã chèn ảnh cuối bài."
                            : "Đã chèn ảnh vào bài." + place)
                    : "Xong."
            );
            setHint("image", mode === "featured" ? "Featured từ AI Studio." : "Đã chèn ảnh từ AI Studio.");
        } catch (e) {
            setStudioHint(String(e.message || e));
        }
    };

    const studioRegenerateOne = async (idx) => {
        setStudioHint("Đang tạo lại…");
        const btn = byId("btnStudioGenerate");
        if (btn) btn.disabled = true;
        try {
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
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : "Tạo lại thất bại");
            }
            const newPrev = (data.previews && data.previews[0]) || null;
            if (newPrev && studioPreviews[idx]) {
                studioPreviews[idx] = { ...studioPreviews[idx], ...newPrev };
                renderStudioGallery();
                setStudioHint("Đã tạo lại ảnh #" + (idx + 1));
            }
        } catch (e) {
            setStudioHint(String(e.message || e));
        } finally {
            if (btn) btn.disabled = false;
        }
    };

    const runStudioGenerate = async () => {
        const pk = byId("primaryKeyword").value.trim();
        if (!pk) {
            setStudioHint("Cần từ khóa chính trước khi tạo ảnh AI.");
            return;
        }
        const btn = byId("btnStudioGenerate");
        if (btn) btn.disabled = true;
        setStudioHint("Đang tạo ảnh AI (OpenAI)…");
        studioPreviews = [];
        renderStudioGallery();
        try {
            const payload = buildStudioGeneratePayload();
            const res = await fetch("/content-ai/images/generate-professional?ts=" + Date.now(), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : "Tạo ảnh AI thất bại");
            }
            studioPreviews = Array.isArray(data.previews) ? data.previews : [];
            studioSelectedIndex = 0;
            renderStudioGallery();
            setStudioHint(data.message || `Đã tạo ${studioPreviews.length} ảnh preview.`);
            const panel = byId("visualStudioPanel");
            if (panel) panel.open = true;
        } catch (e) {
            const err = String(e.message || e);
            setStudioHint(err);
            if (/OPENAI_API_KEY|Model ảnh|Thiếu OPENAI/i.test(err)) {
                setHint("image", err + " — thêm OPENAI_API_KEY vào env.local hoặc dùng «Tự động chèn ảnh» (web).");
            }
        } finally {
            if (btn) btn.disabled = false;
        }
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
    const studioLightboxPrev = byId("studioLightboxPrev");
    const studioLightboxNext = byId("studioLightboxNext");
    const studioLightboxImg = byId("studioLightboxImg");
    if (studioLightboxClose) {
        studioLightboxClose.addEventListener("click", (e) => {
            e.preventDefault();
            closeStudioLightbox();
        });
    }
    if (studioLightboxPrev) {
        studioLightboxPrev.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            stepStudioLightbox(-1);
        });
    }
    if (studioLightboxNext) {
        studioLightboxNext.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            stepStudioLightbox(1);
        });
    }
    if (studioLightboxImg) {
        studioLightboxImg.addEventListener("click", (e) => {
            e.stopPropagation();
            studioLightboxImg.classList.toggle("is-zoomed");
        });
    }
    if (studioLightbox) {
        studioLightbox.addEventListener("click", (e) => {
            if (e.target === studioLightbox) closeStudioLightbox();
        });
    }
    document.addEventListener("keydown", (e) => {
        if (!studioLightbox || !studioLightbox.classList.contains("open")) return;
        if (e.key === "Escape") closeStudioLightbox();
        if (e.key === "ArrowLeft") stepStudioLightbox(-1);
        if (e.key === "ArrowRight") stepStudioLightbox(1);
    });
    const btnStudioGenerate = byId("btnStudioGenerate");
    if (btnStudioGenerate) {
        btnStudioGenerate.addEventListener("click", (e) => {
            e.preventDefault();
            runStudioGenerate();
        });
    }
    const visualStudioPanel = byId("visualStudioPanel");
    if (visualStudioPanel) {
        visualStudioPanel.addEventListener("toggle", () => {
            if (visualStudioPanel.open) {
                refreshStudioH2Select();
                if (!studioCatalogCache) initVisualStudio();
            }
        });
    }
    initVisualStudio();
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
            statsEl.innerHTML = `<span>Tổng: <strong>${counts.total}</strong></span><span class="stat-pub">Published: ${counts.published}</span><span class="stat-ready">Ready: ${counts.ready}</span>`;
        }
        const filtersEl = byId("siteArticlesFilters");
        if (filtersEl) {
            const tabs = [
                { id: "all", label: `Tất cả (${counts.allTab})` },
                { id: "setup_draft", label: `Lưu nháp (${counts.setupDraft})` },
                { id: "missing_section", label: `Thiếu section (${counts.missingSection})` },
                { id: "ready", label: `Ready (${counts.ready})` },
                { id: "published", label: `Published (${counts.published})` },
            ];
            filtersEl.innerHTML = "";
            tabs.forEach((tab) => {
                const b = document.createElement("button");
                b.type = "button";
                b.className = `articles-filter-tab${_siteArticlesFilter === tab.id ? " active" : ""}`;
                b.textContent = tab.label;
                b.addEventListener("click", () => {
                    _siteArticlesFilter = tab.id;
                    renderSiteArticlesBoard();
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
    const BULK_STATE_KEY = () => userStorageKey("content_ai_bulk_state_v1");
    const _bulkWpCategoriesBySiteKey = Object.create(null);
    const WP_CATEGORIES_CACHE_KEY = () => userStorageKey("content_ai_wp_categories_cache_v1");
    const _readWpCategoriesCache = (sk) => {
        if (!sk) return null;
        try {
            const raw = localStorage.getItem(WP_CATEGORIES_CACHE_KEY());
            const all = raw ? JSON.parse(raw) : {};
            const row = all && typeof all === "object" ? all[sk] : null;
            if (!row || !Array.isArray(row.items) || !row.items.length) return null;
            return {
                items: row.items,
                message: String(row.message || ""),
                fetchedAt: Number(row.fetchedAt) || 0,
            };
        } catch (_) {
            return null;
        }
    };
    const _writeWpCategoriesCache = (sk, items, message) => {
        if (!sk || !Array.isArray(items) || !items.length) return;
        try {
            const raw = localStorage.getItem(WP_CATEGORIES_CACHE_KEY());
            const all = raw && typeof JSON.parse(raw) === "object" ? JSON.parse(raw) : {};
            all[sk] = { items, message: String(message || ""), fetchedAt: Date.now() };
            localStorage.setItem(WP_CATEGORIES_CACHE_KEY(), JSON.stringify(all));
        } catch (_) {}
    };
    const _hydrateWpCategoriesFromCache = (sk) => {
        if (!sk) return null;
        if (_bulkWpCategoriesBySiteKey[sk] && _bulkWpCategoriesBySiteKey[sk].length) {
            return { items: _bulkWpCategoriesBySiteKey[sk], fromMemory: true };
        }
        const row = _readWpCategoriesCache(sk);
        if (!row) return null;
        _bulkWpCategoriesBySiteKey[sk] = row.items;
        return row;
    };
    const _syncWpCategoryLoadButtonLabel = (siteUrlRaw) => {
        const btn = byId("btnSingleLoadWpCategories");
        if (!btn) return;
        const sk = _getWpCategoriesSiteKey(siteUrlRaw);
        const has = !!(sk && (_readWpCategoriesCache(sk) || (_bulkWpCategoriesBySiteKey[sk] || []).length));
        btn.textContent = has ? "Tải lại danh mục" : "Tải danh mục";
        btn.title = has
            ? "Cập nhật danh mục từ website (đã có bản lưu trong trình duyệt)"
            : "Tải danh mục từ website và lưu để dùng lần sau";
    };
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
    const loadWpCategoriesForSite = async ({
        siteUrlRaw,
        selectEl,
        hintEl,
        savedId = "",
        forceNetwork = false,
    }) => {
        const site = String(siteUrlRaw ?? "").trim();
        if (!site) {
            if (hintEl) hintEl.textContent = "Nhập Target website trước.";
            return false;
        }
        const sk = _getWpCategoriesSiteKey(site);
        if (!sk) return false;
        if (!forceNetwork) {
            const cached = _hydrateWpCategoriesFromCache(sk);
            if (cached && cached.items && cached.items.length) {
                fillBulkCategorySelectEl(selectEl, cached.items, savedId);
                if (hintEl) {
                    hintEl.textContent = `Đã dùng ${cached.items.length} danh mục đã lưu (không gọi API).`;
                }
                _syncWpCategoryLoadButtonLabel(site);
                return true;
            }
        }
        const cred = await resolveWpCredentialsForBulk(site);
        if (!cred.username || !cred.app_password) {
            const msg =
                "Chưa có username / Application Password — mở «Thêm site đăng bài», nhập đủ và bấm «Lưu & áp dụng».";
            if (hintEl) hintEl.textContent = msg;
            return false;
        }
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
            _writeWpCategoriesCache(sk, _bulkWpCategoriesBySiteKey[sk], data.message || "");
            fillBulkCategorySelectEl(selectEl, _bulkWpCategoriesBySiteKey[sk], savedId);
            if (hintEl) {
                hintEl.textContent =
                    data.message || `Đã tải và lưu ${(_bulkWpCategoriesBySiteKey[sk] || []).length} danh mục.`;
            }
            _syncWpCategoryLoadButtonLabel(site);
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
    const loadSingleWpCategories = async (forceNetwork = false) => {
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
            forceNetwork,
        });
        if (ok) {
            syncSingleWpCategoryFromSelect();
            saveFormState();
        }
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
    const _defaultBulkWordCount = () => 1000;
    const _clampBulkWordCount = (n) => {
        const v = parseInt(n, 10);
        if (!v || v < 200) return 1000;
        return Math.min(8000, v);
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
        const wc =
            parsed.target_word_count != null && String(parsed.target_word_count).trim() !== ""
                ? _clampBulkWordCount(parsed.target_word_count)
                : extra.target_word_count != null
                  ? _clampBulkWordCount(extra.target_word_count)
                  : _defaultBulkWordCount();
        const comp = (parsed.competitor_url || extra.competitor_url || "").trim();
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
            target_word_count: String(wc),
            competitor_url: comp,
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
                secStr ||
                wpc
            ),
        };
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
            target_word_count: _clampBulkWordCount(row.target_word_count),
            secondary_keywords,
            wp_category_id,
        };
    };
    const mergeBulkItems = () => bulkKeywordRows.map(bulkRowToApiItem);
    const isBulkItemSetupComplete = (item) => {
        const title = String(item.custom_title || "").trim();
        const desc = String(item.custom_description || "").trim();
        const outline = String(item.custom_outline || "").trim();
        const wc = Number(item.target_word_count) || 0;
        return !!(title && desc && outline && wc >= 200);
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
        const btw = byId("bulkTargetWebsite");
        const tw = btw ? normalizeTargetBase(String(btw.value || "").trim()) : "";
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
        };
        const apiField = apiMap[bulkField] || bulkField;
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
            appendBulkLog(`[${r.keyword}] Đã gợi ý ${bulkField === "custom_title" ? "title" : bulkField === "custom_description" ? "meta" : "outline"}.`);
        } catch (e) {
            appendBulkLog(`[${r.keyword}] Gợi ý AI lỗi: ${String(e.message || e)}`);
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
                headers: { "Content-Type": "application/json" },
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
            card.className = `bulk-kw-card${row.detailsOpen ? " is-open" : ""}`;
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
            const wcIn = document.createElement("input");
            wcIn.type = "number";
            wcIn.min = "200";
            wcIn.max = "8000";
            wcIn.step = "50";
            wcIn.placeholder = "Số từ";
            wcIn.title = "Số từ bài viết (mặc định 1000)";
            wcIn.value = row.target_word_count || String(_defaultBulkWordCount());
            wcIn.dataset.field = "target_word_count";
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
            main.appendChild(wcIn);
            main.appendChild(btnToggle);
            main.appendChild(btnRemove);
            const details = document.createElement("div");
            details.className = "bulk-kw-details";
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
            details.appendChild(urlGrid);
            details.appendChild(mkField("Title (SEO)", "custom_title", "input", "Tiêu đề tùy chỉnh"));
            details.appendChild(mkField("Meta description", "custom_description", "input", "Mô tả meta 140–160 ký tự"));
            details.appendChild(mkField("Outline", "custom_outline", "textarea", "H2: …; H2: … hoặc markdown # / ##"));
            const wpMeta = document.createElement("div");
            wpMeta.className = "bulk-wp-meta-box bulk-wp-meta-box--row";
            const secHead = document.createElement("div");
            secHead.className = "field-head";
            const secLb = document.createElement("label");
            secLb.textContent = "Từ khóa phụ";
            secHead.appendChild(secLb);
            const secIn = document.createElement("input");
            secIn.type = "text";
            secIn.dataset.field = "secondary_keywords";
            secIn.placeholder = "Cách nhau bằng dấu phẩy hoặc chấm phẩy";
            secIn.autocomplete = "off";
            secIn.value = row.secondary_keywords || "";
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
            catLb.textContent = "Danh mục website khi đăng";
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
            if (skCat) _hydrateWpCategoriesFromCache(skCat);
            const cachedCat = skCat ? _bulkWpCategoriesBySiteKey[skCat] : null;
            fillBulkCategorySelectEl(catSel, cachedCat || [], row.wp_category_id || "");
            const btnLoadCat = document.createElement("button");
            btnLoadCat.type = "button";
            btnLoadCat.className = "btn secondary";
            btnLoadCat.textContent =
                skCat && _readWpCategoriesCache(skCat) ? "Tải lại danh mục" : "Tải danh mục";
            const catHint = document.createElement("div");
            catHint.className = "hint";
            catHint.style.marginTop = "6px";
            catHint.textContent = cachedCat && cachedCat.length
                ? `Đã nạp ${cachedCat.length} danh mục đã lưu.`
                : "Tải một lần — lần sau dùng danh mục đã lưu theo Target website.";
            btnLoadCat.addEventListener("click", () => {
                btnLoadCat.disabled = true;
                const skNow = _getBulkWpCategoriesSiteKey();
                const forceNet = btnLoadCat.textContent.includes("lại");
                void (async () => {
                    const tw = byId("bulkTargetWebsite");
                    const site = tw ? tw.value.trim() : "";
                    const r = _findBulkRow(row.id);
                    const ok = await loadWpCategoriesForSite({
                        siteUrlRaw: site,
                        selectEl: catSel,
                        hintEl: catHint,
                        savedId: r ? r.wp_category_id : "",
                        forceNetwork: forceNet,
                    });
                    if (ok) scheduleSaveBulkState();
                })().finally(() => {
                    btnLoadCat.disabled = false;
                    const skAfter = _getBulkWpCategoriesSiteKey();
                    btnLoadCat.textContent =
                        skAfter && _readWpCategoriesCache(skAfter) ? "Tải lại danh mục" : "Tải danh mục";
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
                if (f === "target_word_count") r.target_word_count = String(_clampBulkWordCount(el.value));
                else r[f] = el.value;
                scheduleSaveBulkState();
                updateBulkRemoveButtonForRow(row.id);
            };
            typeSel.addEventListener("change", () => syncField(typeSel));
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
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ competitor_url: url }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không lấy outline");
                    r.custom_outline = (data.outline || "").trim();
                    r.detailsOpen = true;
                    renderBulkKeywordList();
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
    };
    const addBulkKeywordsFromParsed = async (parsedList, { fetchVolume = true } = {}) => {
        const toAdd = [];
        for (const parsed of parsedList) {
            const lk = parsed.keyword.toLowerCase();
            if (bulkKeywordRows.some((r) => r.keyword.toLowerCase() === lk)) continue;
            toAdd.push(parsed);
        }
        if (!toAdd.length) return 0;
        for (const parsed of toAdd) {
            const row = _rowFromParsed(parsed);
            const hasVol = String(row.search_volume || "").trim() !== "";
            row._volumeLoading = !!fetchVolume && !hasVol;
            bulkKeywordRows.push(row);
        }
        renderBulkKeywordList();
        updateBulkKwCount();
        if (fetchVolume) {
            const needVol = toAdd.filter((p) => !String(p.search_volume ?? "").trim());
            const volMap = needVol.length
                ? await fetchBulkSearchVolumes(needVol.map((p) => p.keyword))
                : {};
            for (const parsed of toAdd) {
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
        return toAdd.length;
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
    });
    const importBulkUploadFile = async (file) => {
        if (!file) return 0;
        const name = String(file.name || "").toLowerCase();
        if (bulkImportFileHint) bulkImportFileHint.textContent = `Đang đọc ${file.name}…`;
        const fd = new FormData();
        fd.append("file", file, file.name || "upload");
        try {
            const res = await fetch(`/content-ai/bulk-import/file?ts=${Date.now()}`, {
                method: "POST",
                body: fd,
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = data.detail;
                throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail) || `HTTP ${res.status}`);
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
    const addBulkKeywordFromInput = async () => {
        const raw = bulkAddKeywordInput ? bulkAddKeywordInput.value : "";
        const parsedList = splitBulkKeywordInput(raw);
        if (!parsedList.length) {
            appendBulkLog("Chưa có từ khóa để thêm.");
            return;
        }
        const n = await addBulkKeywordsFromParsed(parsedList, { fetchVolume: true });
        if (!n) {
            appendBulkLog("Tất cả từ khóa đã có trong danh sách.");
            return;
        }
        appendBulkLog(`Đã thêm ${n} từ khóa.`);
        if (bulkAddKeywordInput) bulkAddKeywordInput.value = "";
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
        if (bulkKwCount) {
            bulkKwCount.textContent = customN
                ? `${n} từ khóa (${customN} có cấu hình chi tiết)`
                : `${n} từ khóa`;
        }
        return n;
    };
    const _rowFromStored = (s) => ({
        id: s.id || _bulkRowId(),
        keyword: String(s.keyword || "").trim(),
        search_volume: s.search_volume != null ? String(s.search_volume) : "",
        content_type: String(s.content_type || ""),
        target_word_count: s.target_word_count != null ? String(s.target_word_count) : "",
        competitor_url: String(s.competitor_url || ""),
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
        rows: bulkKeywordRows.map((r) => ({
            id: r.id,
            keyword: r.keyword,
            search_volume: r.search_volume ?? "",
            content_type: r.content_type || "",
            target_word_count: r.target_word_count ?? "",
            competitor_url: r.competitor_url || "",
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
            bulkKeywordRows = (s.rows || [])
                .map(_rowFromStored)
                .filter((r) => r.keyword);
            renderBulkKeywordList();
            updateBulkKwCount();
            const mv = String(s.main_view || "");
            if (mv === "bulk" || mv === "projects" || mv === "single") {
                _contentAiMainView = mv;
            }
            return (
                bulkKeywordRows.length > 0 ||
                !!(btw && btw.value.trim()) ||
                !!(bbn && String(bbn.value || "").trim()) ||
                mv === "bulk"
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
    const renderBulkJobItems = (items) => {
        if (!bulkJobItems) return;
        bulkJobItems.innerHTML = "";
        (items || []).forEach((it) => {
            const row = document.createElement("div");
            const st = String(it.status || "pending");
            row.className = `bulk-job-item ${st === "success" ? "ok" : st === "error" ? "err" : "pending"}`;
            const left = document.createElement("span");
            left.textContent = it.keyword || "—";
            const right = document.createElement("span");
            if (st === "success") right.textContent = "✓ xong";
            else if (st === "error") right.textContent = "✗ lỗi";
            else right.textContent = "…";
            row.appendChild(left);
            row.appendChild(right);
            bulkJobItems.appendChild(row);
        });
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
        renderBulkKeywordList();
        if (bulkKeywordsFile) bulkKeywordsFile.value = "";
        if (bulkImportFile) bulkImportFile.value = "";
        if (bulkImportFileHint) bulkImportFileHint.textContent = "";
        if (bulkJobLog) bulkJobLog.value = "";
        if (bulkJobItems) bulkJobItems.innerHTML = "";
        if (bulkJobProgress) bulkJobProgress.hidden = true;
        if (bulkJobProgressFill) bulkJobProgressFill.style.width = "0%";
        if (bulkJobPct) bulkJobPct.textContent = "0%";
        if (bulkJobStatus) bulkJobStatus.textContent = "";
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = true;
        updateBulkKwCount();
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
        publishLog.value = "";
        out.value = "";
        uploadedImages.length = 0;
        activeProjectId = "";
        renderUploadList();
        toggleAiAvailability();
        syncSlugFromPrimary();
        _internalCandidates = [];
        if (internalLinkCandidates) internalLinkCandidates.innerHTML = "";
        setHint("internal-links", "");
        try {
            localStorage.removeItem(FORM_STATE_KEY());
        } catch (_) {}
        setHint("outline-actions", "");
        setHint("competitor", "");
    };
    const setContentAiMainView = (view) => {
        const v = String(view || "single");
        _contentAiMainView = v;
        const showBulk = v === "bulk";
        const showProjects = v === "projects";
        if (bulkWritePanel) bulkWritePanel.hidden = !showBulk;
        if (contentAiSinglePanel) contentAiSinglePanel.hidden = showBulk || showProjects;
        if (contentAiProjectSitesPanel) contentAiProjectSitesPanel.hidden = !showProjects;
        if (contentAiMainTabs) contentAiMainTabs.hidden = showProjects;
        if (contentAiSidebar) contentAiSidebar.classList.remove("sidebar-collapsed");
        const tabMainSingle = byId("tabMainSingle");
        const tabMainBulk = byId("tabMainBulk");
        if (tabMainSingle) tabMainSingle.classList.toggle("active", v === "single");
        if (tabMainBulk) tabMainBulk.classList.toggle("active", showBulk);
        if (showProjects) {
            try {
                renderConnectedSitesPanel();
            } catch (_) {}
            void refreshProjects();
            if (contentAiProjectSitesPanel) {
                contentAiProjectSitesPanel.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        } else if (showBulk && bulkWritePanel) {
            bulkWritePanel.scrollIntoView({ behavior: "smooth", block: "start" });
        } else if (v === "single" && contentAiSinglePanel) {
            contentAiSinglePanel.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        scheduleSaveBulkState();
    };

    const allArticlesBackdropEl = byId("allArticlesBackdrop");
    const allArticlesModalEl = byId("allArticlesModal");
    const allArticlesListEl = byId("allArticlesList");
    const allArticlesSearchEl = byId("allArticlesSearch");
    const allArticlesEmptyEl = byId("allArticlesEmpty");
    const closeAllArticlesModal = () => {
        if (allArticlesBackdropEl) allArticlesBackdropEl.classList.remove("open");
        if (allArticlesModalEl) {
            allArticlesModalEl.classList.remove("open");
            allArticlesModalEl.setAttribute("aria-hidden", "true");
        }
    };
    const scrollSidebarActiveProject = () => {
        try {
            const el = projectList && projectList.querySelector(".project-item.active");
            if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
        } catch (_) {}
    };
    const selectProjectFromAllModal = async (projectId) => {
        const pid = String(projectId || "").trim();
        if (!pid) return;
        closeAllArticlesModal();
        closeSiteArticlesModal();
        closeArticleDetailModal();
        activeProjectId = pid;
        try {
            renderProjects();
            renderConnectedSitesPanel();
        } catch (_) {}
        setContentAiMainView("single");
        if (railNav) {
            railNav.querySelectorAll(".content-ai-nav-item").forEach((n) => n.classList.remove("active"));
        }
        await loadProject(pid);
        try {
            renderProjects();
            scrollSidebarActiveProject();
        } catch (_) {}
        window.setTimeout(() => {
            if (contentAiSinglePanel) {
                contentAiSinglePanel.scrollIntoView({ behavior: "smooth", block: "start" });
            }
            const pk = byId("primaryKeyword");
            if (pk) pk.focus({ preventScroll: true });
        }, 320);
    };
    const loadProjectIntoWriteTab = async (projectId) => selectProjectFromAllModal(projectId);
    const allProjectsModalCountEl = byId("allProjectsModalCount");
    const updateAllPublishingSitesModalCount = (shown, total) => {
        if (!allProjectsModalCountEl) return;
        if (!total) {
            allProjectsModalCountEl.hidden = true;
            return;
        }
        allProjectsModalCountEl.hidden = false;
        allProjectsModalCountEl.textContent =
            shown === total
                ? `Hiển thị ${total} website`
                : `Hiển thị ${shown} / ${total} website (đang lọc tìm kiếm)`;
    };
    const renderAllPublishingSitesList = () => {
        if (!allArticlesListEl) return;
        const q = String((allArticlesSearchEl && allArticlesSearchEl.value) || "")
            .trim()
            .toLowerCase();
        let sites = collectConnectedSites();
        const totalAll = sites.length;
        if (q) {
            sites = sites.filter((it) => {
                let host = String(it.url || "").toLowerCase();
                try {
                    host = (new URL(it.url).host || host).toLowerCase();
                } catch (_) {}
                return host.includes(q) || String(it.url || "").toLowerCase().includes(q);
            });
        }
        updateAllPublishingSitesModalCount(sites.length, totalAll);
        allArticlesListEl.innerHTML = "";
        if (!sites.length) {
            if (allArticlesEmptyEl) allArticlesEmptyEl.hidden = false;
            return;
        }
        if (allArticlesEmptyEl) allArticlesEmptyEl.hidden = true;
        const filterKey = String(_projectsSiteFilterBase || "").toLowerCase();
        const wpNorm = normalizeWpUrl(byId("wpUrl") && byId("wpUrl").value.trim());
        const tgNorm = normalizeTargetBase(byId("targetWebsite") && byId("targetWebsite").value.trim());
        const activeKeys = new Set([wpNorm, tgNorm, filterKey].filter(Boolean).map((u) => u.toLowerCase()));
        const platLbl = { shopify: "Shopify", haravan: "Haravan", webcake: "Webcake" };
        sites.forEach((it) => {
            const btn = document.createElement("button");
            btn.type = "button";
            const key = String(it.url).toLowerCase();
            btn.className = `all-publishing-site-item${activeKeys.has(key) || (filterKey && key === filterKey) ? " active" : ""}`;
            btn.setAttribute("role", "listitem");
            const dot = document.createElement("span");
            dot.className = "dot";
            const body = document.createElement("div");
            body.style.flex = "1";
            const hostEl = document.createElement("div");
            hostEl.className = "host";
            try {
                hostEl.textContent = new URL(it.url).host || it.url;
            } catch (_) {
                hostEl.textContent = it.url;
            }
            const badges = document.createElement("div");
            badges.className = "badges";
            if (it.wp) {
                const b = document.createElement("span");
                b.className = "connected-site-badge wp";
                b.textContent = "WP";
                badges.appendChild(b);
            }
            (it.platforms || []).forEach((pl) => {
                const b = document.createElement("span");
                b.className = `connected-site-badge plat plat-${pl}`;
                b.textContent = platLbl[pl] || pl;
                badges.appendChild(b);
            });
            body.appendChild(hostEl);
            body.appendChild(badges);
            btn.appendChild(dot);
            btn.appendChild(body);
            btn.title = it.url;
            btn.addEventListener("click", async () => {
                closeAllArticlesModal();
                await applyConnectedSiteSelection(it, { openArticles: false });
            });
            allArticlesListEl.appendChild(btn);
        });
    };
    const openAllPublishingSitesModal = async () => {
        if (allArticlesSearchEl) allArticlesSearchEl.value = "";
        const titleEl = byId("allPublishingSitesModalTitle");
        if (titleEl) titleEl.textContent = "Tất cả website đăng bài";
        try {
            await fetchSettingsPublishingSites();
            renderConnectedSitesPanel();
        } catch (_) {}
        renderAllPublishingSitesList();
        if (allArticlesBackdropEl) allArticlesBackdropEl.classList.add("open");
        if (allArticlesModalEl) {
            allArticlesModalEl.classList.add("open");
            allArticlesModalEl.setAttribute("aria-hidden", "false");
        }
        if (allArticlesSearchEl) {
            window.setTimeout(() => allArticlesSearchEl.focus(), 120);
        }
    };
    const stopBulkPoll = () => {
        if (_bulkPollTimer) {
            clearInterval(_bulkPollTimer);
            _bulkPollTimer = null;
        }
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = true;
    };
    const pollBulkJob = async (jobId) => {
        const jid = String(jobId || "").trim();
        if (!jid) return;
        try {
            const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}?ts=${Date.now()}`, {
                headers: authHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Poll failed");
            const pct = Number(data.progress) || 0;
            if (bulkJobProgress) bulkJobProgress.hidden = false;
            if (bulkJobProgressFill) bulkJobProgressFill.style.width = `${pct}%`;
            if (bulkJobPct) bulkJobPct.textContent = `${pct}%`;
            if (bulkJobStatus) bulkJobStatus.textContent = data.message || data.state || "";
            if (data.result && data.result.items) renderBulkJobItems(data.result.items);
            if (data.state === "SUCCESS") {
                appendBulkLog(`Hoàn tất: ${(data.result && data.result.success) || 0}/${(data.result && data.result.total) || "?"} bài.`);
                stopBulkPoll();
                try {
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                await refreshProjects(true);
                return;
            }
            if (data.state === "ERROR") {
                appendBulkLog(`Lỗi: ${data.error || data.message || "unknown"}`);
                stopBulkPoll();
                try {
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
            }
        } catch (e) {
            appendBulkLog(String(e.message || e));
        }
    };
    const startBulkPoll = (jobId) => {
        stopBulkPoll();
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = false;
        pollBulkJob(jobId);
        _bulkPollTimer = setInterval(() => pollBulkJob(jobId), 2200);
    };
    if (btnBulkAddKeyword) {
        btnBulkAddKeyword.addEventListener("click", () => void addBulkKeywordFromInput());
    }
    if (bulkAddKeywordInput) {
        bulkAddKeywordInput.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
                ev.preventDefault();
                void addBulkKeywordFromInput();
            }
        });
    }
    if (btnBulkImportText) {
        btnBulkImportText.addEventListener("click", () => void importBulkTextToList());
    }
    if (btnBulkImportFile) {
        btnBulkImportFile.addEventListener("click", async () => {
            const f = bulkImportFile && bulkImportFile.files && bulkImportFile.files[0];
            if (!f) {
                if (bulkImportFileHint) bulkImportFileHint.textContent = "Chọn file .xlsx, .txt hoặc .csv trước.";
                return;
            }
            await importBulkUploadFile(f);
            if (bulkImportFile) bulkImportFile.value = "";
        });
    }
    if (bulkImportFile) {
        bulkImportFile.addEventListener("change", () => {
            if (bulkImportFileHint) bulkImportFileHint.textContent = "";
        });
    }
    if (bulkKeywordsFile) {
        bulkKeywordsFile.addEventListener("change", async () => {
            const f = bulkKeywordsFile.files && bulkKeywordsFile.files[0];
            if (!f) return;
            const name = String(f.name || "").toLowerCase();
            if (name.endsWith(".xlsx")) {
                await importBulkUploadFile(f);
            } else {
                const text = await f.text();
                if (bulkKeywordsText) {
                    const cur = bulkKeywordsText.value.trim();
                    bulkKeywordsText.value = cur ? `${cur}\n${text}` : text;
                }
                await importBulkTextToList();
            }
            bulkKeywordsFile.value = "";
        });
    }
    const saveBulkSetupToProjects = async () => {
        const bulkItems = mergeBulkItems();
        if (!bulkItems.length) {
            appendBulkLog("Chưa có từ khóa để lưu nháp.");
            return false;
        }
        const twEl = byId("bulkTargetWebsite");
        const target_website = twEl ? twEl.value.trim() : "";
        if (!target_website) {
            appendBulkLog("Cần Target website để lưu nháp theo domain.");
            if (msg) msg.textContent = "Nhập Target website trước khi lưu nháp.";
            return false;
        }
        const keywords = bulkItems.map((x) => x.keyword);
        try {
            const res = await fetch("/content-ai/bulk-setup/save", {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ keywords, items: bulkItems, target_website, brand_name }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error((data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`);
            }
            const n = Number(data.saved) || 0;
            appendBulkLog(`Đã lưu ${n} bài nháp (setup, chưa content) — xem tab Lưu nháp trong Bài viết site.`);
            if (msg) msg.textContent = `Đã lưu ${n} bài nháp cho ${normalizeTargetBase(target_website) || target_website}.`;
            await refreshProjects(false);
            return true;
        } catch (e) {
            appendBulkLog(`Lưu nháp lỗi: ${String(e.message || e)}`);
            if (msg) msg.textContent = String(e.message || e);
            return false;
        }
    };
    const btnBulkSaveSetup = byId("btnBulkSaveSetup");
    if (btnBulkSaveSetup) {
        btnBulkSaveSetup.addEventListener("click", async () => {
            btnBulkSaveSetup.disabled = true;
            try {
                await saveBulkSetupToProjects();
            } finally {
                btnBulkSaveSetup.disabled = false;
            }
        });
    }
    const bulkWriteModeBackdropEl = byId("bulkWriteModeBackdrop");
    const bulkWriteModeModalEl = byId("bulkWriteModeModal");
    const bulkWriteModeAllEl = byId("bulkWriteModeAll");
    const bulkWriteModeSetupEl = byId("bulkWriteModeSetup");
    let _bulkWriteModeResolve = null;
    const closeBulkWriteModeModal = (mode) => {
        if (bulkWriteModeBackdropEl) bulkWriteModeBackdropEl.classList.remove("open");
        if (bulkWriteModeModalEl) {
            bulkWriteModeModalEl.classList.remove("open");
            bulkWriteModeModalEl.setAttribute("aria-hidden", "true");
        }
        if (_bulkWriteModeResolve) {
            _bulkWriteModeResolve(mode);
            _bulkWriteModeResolve = null;
        }
    };
    const openBulkWriteModeModal = () => {
        const all = mergeBulkItems();
        if (!all.length) return Promise.resolve(null);
        return new Promise((resolve) => {
            _bulkWriteModeResolve = resolve;
            if (bulkWriteModeAllEl) bulkWriteModeAllEl.checked = true;
            if (bulkWriteModeSetupEl) bulkWriteModeSetupEl.checked = false;
            if (bulkWriteModeBackdropEl) bulkWriteModeBackdropEl.classList.add("open");
            if (bulkWriteModeModalEl) {
                bulkWriteModeModalEl.classList.add("open");
                bulkWriteModeModalEl.setAttribute("aria-hidden", "false");
            }
        });
    };
    if (bulkWriteModeAllEl && bulkWriteModeSetupEl) {
        const syncBulkWriteModeChecks = (picked) => {
            if (picked === "all") {
                bulkWriteModeAllEl.checked = true;
                bulkWriteModeSetupEl.checked = false;
            } else {
                bulkWriteModeAllEl.checked = false;
                bulkWriteModeSetupEl.checked = true;
            }
        };
        bulkWriteModeAllEl.addEventListener("change", () => {
            if (bulkWriteModeAllEl.checked) syncBulkWriteModeChecks("all");
            else if (!bulkWriteModeSetupEl.checked) bulkWriteModeAllEl.checked = true;
        });
        bulkWriteModeSetupEl.addEventListener("change", () => {
            if (bulkWriteModeSetupEl.checked) syncBulkWriteModeChecks("setup");
            else if (!bulkWriteModeAllEl.checked) bulkWriteModeAllEl.checked = true;
        });
    }
    const btnBulkWriteModeCancel = byId("btnBulkWriteModeCancel");
    if (btnBulkWriteModeCancel) btnBulkWriteModeCancel.addEventListener("click", () => closeBulkWriteModeModal(null));
    const btnBulkWriteModeOk = byId("btnBulkWriteModeOk");
    if (btnBulkWriteModeOk) {
        btnBulkWriteModeOk.addEventListener("click", () => {
            const setupOnly = bulkWriteModeSetupEl && bulkWriteModeSetupEl.checked;
            const mode = setupOnly ? "setup" : "all";
            const filtered = filterBulkItemsByWriteMode(mergeBulkItems(), mode);
            if (!filtered.length) {
                appendBulkLog(
                    mode === "setup"
                        ? "Không có bài đã setup đủ (title, meta, outline, số từ)."
                        : "Chưa có từ khóa."
                );
                return;
            }
            closeBulkWriteModeModal(mode);
        });
    }
    if (bulkWriteModeBackdropEl) {
        bulkWriteModeBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === bulkWriteModeBackdropEl) closeBulkWriteModeModal(null);
        });
    }
    document.addEventListener("keydown", (ev) => {
        if (ev.key !== "Escape") return;
        if (bulkWriteModeModalEl && bulkWriteModeModalEl.classList.contains("open")) {
            closeBulkWriteModeModal(null);
        }
    });
    const startBulkWriteJob = async (writeMode) => {
        const mode = writeMode === "setup" ? "setup" : "all";
        let bulkItems = filterBulkItemsByWriteMode(mergeBulkItems(), mode);
        if (!bulkItems.length) {
            appendBulkLog(
                mode === "setup"
                    ? "Không có bài đã setup đủ (số từ, title, meta, outline)."
                    : "Chưa có từ khóa."
            );
            return;
        }
        const keywords = bulkItems.map((x) => x.keyword);
        const twEl = byId("bulkTargetWebsite");
        const bnEl = byId("bulkBrandName");
        const target_website = twEl ? twEl.value.trim() : "";
        const brand_name = bnEl ? bnEl.value.trim() : "";
        const target_word_count = 1000;
        const modeLabel = mode === "setup" ? "đã Setup" : "tất cả";
        appendBulkLog(`Gửi job ${keywords.length} từ khóa (${modeLabel}) lên server…`);
        const res = await fetch("/content-ai/bulk-jobs/start", {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify({
                keywords,
                items: bulkItems,
                target_website,
                target_word_count,
                secondary_keywords: [],
                brand_name,
                wp_category_id: null,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            let errMsg = (data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`;
            if (res.status === 404) {
                errMsg =
                    "API viết hàng loạt chưa có trên server (404). Tắt cửa sổ run.bat/uvicorn cũ, chạy lại run.bat, rồi Ctrl+F5 trang này.";
            }
            throw new Error(errMsg);
        }
        appendBulkLog(data.note || `Job ${data.job_id} đã xếp hàng (${modeLabel}, ${keywords.length} bài).`);
        try {
            localStorage.setItem(BULK_JOB_STORAGE_KEY(), data.job_id);
        } catch (_) {}
        startBulkPoll(data.job_id);
    };
    const btnBulkWriteStart = byId("btnBulkWriteStart");
    if (btnBulkWriteStart) {
        btnBulkWriteStart.addEventListener("click", async () => {
            const bulkItems = mergeBulkItems();
            if (!bulkItems.length) {
                appendBulkLog("Chưa có từ khóa.");
                return;
            }
            const writeMode = await openBulkWriteModeModal();
            if (!writeMode) return;
            btnBulkWriteStart.disabled = true;
            try {
                await startBulkWriteJob(writeMode);
            } catch (e) {
                appendBulkLog(String(e.message || e));
            } finally {
                btnBulkWriteStart.disabled = false;
            }
        });
    }
    const btnBulkWriteStopPoll = byId("btnBulkWriteStopPoll");
    if (btnBulkWriteStopPoll) {
        btnBulkWriteStopPoll.addEventListener("click", () => {
            stopBulkPoll();
            appendBulkLog("Đã dừng theo dõi trên trình duyệt (job vẫn chạy trên server).");
        });
    }

    const tabMainSingle = byId("tabMainSingle");
    const tabMainBulk = byId("tabMainBulk");
    if (tabMainSingle) {
        tabMainSingle.addEventListener("click", () => {
            setContentAiMainView("single");
        });
    }
    if (tabMainBulk) {
        tabMainBulk.addEventListener("click", () => {
            setContentAiMainView("bulk");
            const tw = byId("targetWebsite");
            const btw = byId("bulkTargetWebsite");
            if (tw && btw && !btw.value.trim()) btw.value = tw.value;
            renderBulkKeywordList();
            updateBulkKwCount();
        });
    }
    const linkNavProjects = byId("linkNavProjects");
    if (linkNavProjects) {
        linkNavProjects.addEventListener("click", (ev) => {
            ev.preventDefault();
            setContentAiMainView("projects");
        });
    }
    const closeProjectView = () => {
        setContentAiMainView("single");
        if (railNav) {
            railNav.querySelectorAll(".content-ai-nav-item").forEach((n) => n.classList.remove("active"));
        }
    };
    const btnCloseProjectSitesPanel = byId("btnCloseProjectSitesPanel");
    if (btnCloseProjectSitesPanel) btnCloseProjectSitesPanel.addEventListener("click", closeProjectView);
    document.querySelectorAll(".btn-close-project-view").forEach((btn) => {
        btn.addEventListener("click", closeProjectView);
    });
    updateBulkKwCount();

    const resolveSiteForAllArticles = () => {
        const fromFilter = String(_projectsSiteFilterBase || "").trim();
        if (fromFilter) return fromFilter;
        const wp = normalizeWpUrl(byId("wpUrl") && byId("wpUrl").value.trim());
        if (wp) return wp;
        const tg = normalizeTargetBase(byId("targetWebsite") && byId("targetWebsite").value.trim());
        if (tg) return tg;
        const sites = collectConnectedSites();
        if (sites.length) return sites[0].url;
        return "";
    };
    const openViewAllSiteArticles = async () => {
        const base = resolveSiteForAllArticles();
        if (!base) {
            if (msg) msg.textContent = "Chưa có website — thêm site đăng bài hoặc chọn một site trong danh sách.";
            return;
        }
        let hostLabel = base;
        try {
            hostLabel = new URL(base).host || base;
        } catch (_) {}
        _projectsSiteFilterBase = normalizeTargetBase(base) || normalizeWpUrl(base) || "";
        try {
            renderProjects();
            renderConnectedSitesPanel();
        } catch (_) {}
        await openSiteArticlesModal(_projectsSiteFilterBase, hostLabel, {
            resetFilter: true,
            clearSearch: true,
        });
    };
    const btnViewAllSiteArticles = byId("btnViewAllSiteArticles");
    if (btnViewAllSiteArticles) btnViewAllSiteArticles.addEventListener("click", () => void openViewAllSiteArticles());
    const btnViewAllProjects = byId("btnViewAllProjects");
    if (btnViewAllProjects) btnViewAllProjects.addEventListener("click", () => void openAllPublishingSitesModal());
    const btnAllArticlesClose = byId("btnAllArticlesClose");
    if (btnAllArticlesClose) btnAllArticlesClose.addEventListener("click", closeAllArticlesModal);
    if (allArticlesBackdropEl) {
        allArticlesBackdropEl.addEventListener("click", (ev) => {
            if (ev.target === allArticlesBackdropEl) closeAllArticlesModal();
        });
    }
    if (allArticlesSearchEl) {
        allArticlesSearchEl.addEventListener("input", () => {
            try {
                if (allArticlesModalEl && allArticlesModalEl.classList.contains("open")) {
                    renderAllPublishingSitesList();
                }
            } catch (_) {}
        });
    }
    const btnContentAiRecentPlus = byId("btnContentAiRecentPlus");
    if (btnContentAiRecentPlus) {
        btnContentAiRecentPlus.addEventListener("click", () => {
            setContentAiMainView("single");
            const pk = byId("primaryKeyword");
            window.setTimeout(() => {
                if (pk) pk.focus({ preventScroll: true });
            }, 350);
        });
    }
    const toggleAiAvailability = () => {
        const hasPrimary = !!byId("primaryKeyword").value.trim();
        aiButtons.forEach((btnItem) => {
            const field = btnItem.dataset.field;
            btnItem.disabled = field === "target_website" ? false : !hasPrimary;
        });
        if (!hasPrimary) {
            setHint("primary_keyword", "Hãy nhập từ khóa chính trước để kích hoạt toàn bộ gợi ý AI.");
        } else {
            setHint("primary_keyword", "Da kich hoat goi y AI theo tu khoa chinh.");
        }
    };

    const applySuggestion = (field, value) => {
        const mapping = {
            title: "title",
            target_website: "targetWebsite",
            slug: "slug",
            primary_keyword: "primaryKeyword",
            secondary_keywords: "secondaryKeywords",
            outline_content: "outlineContent",
            meta_description: "meta",
            tags: "tags",
            content: "content",
        };
        const id = mapping[field];
        if (!id) return;
        const input = byId(id);
        if (!input) return;
        input.value = value || "";
        // removed "Lịch sử gợi ý AI" panel
    };

    aiButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            const field = button.dataset.field;
            if (!field) return;
            const oldText = button.textContent;
            button.textContent = "Đang gợi ý...";
            button.disabled = true;
            setHint(field, "");
            try {
                const ctx = buildContext();
                let value = "";
                let detectedIntent = "";
                if (field === "title") {
                    const current = byId("title").value.trim();
                    for (let i = 0; i < 3; i += 1) {
                        const nextObj = await fetchSuggestion(field, ctx);
                        const next = nextObj.value || "";
                        detectedIntent = nextObj.detected_intent || detectedIntent;
                        if (next && next !== current && next !== lastSuggestedTitle) {
                            value = next;
                            break;
                        }
                        value = next;
                    }
                    lastSuggestedTitle = value || lastSuggestedTitle;
                } else if (field === "slug") {
                    value = buildStrictSlug();
                    if (!value) {
                        const out = await fetchSuggestion(field, ctx);
                        value = out.value || "";
                        detectedIntent = out.detected_intent || "";
                    }
                } else if (field === "target_website") {
                    const seenTw = new Set();
                    const mergedTw = [];
                    const pushTw = (raw) => {
                        const b = normalizeTargetBase(raw) || normalizeWpUrl(raw);
                        if (!b) return;
                        const k = b.toLowerCase();
                        if (seenTw.has(k)) return;
                        seenTw.add(k);
                        mergedTw.push(b);
                    };
                    settingsPublishingSitesFlat.forEach((s) => pushTw(s.url));
                    readTargetHistory().forEach(pushTw);
                    if (mergedTw[0]) {
                        value = mergedTw[0];
                    } else {
                        const out = await fetchSuggestion(field, ctx);
                        value = out.value || "";
                        detectedIntent = out.detected_intent || "";
                    }
                } else {
                    const out = await fetchSuggestion(field, ctx);
                    value = out.value || "";
                    detectedIntent = out.detected_intent || "";
                }
                applySuggestion(field, value);
                setDetectedIntentDebug(detectedIntent);
                if (field === "target_website") {
                    rememberTargetWebsite(value);
                }
                setHint(field, "Da cap nhat goi y AI theo tu khoa chinh.");
            } catch (err) {
                setHint(field, String(err.message || err));
            } finally {
                button.textContent = oldText;
                button.disabled = false;
                toggleAiAvailability();
            }
        });
    });
    byId("primaryKeyword").addEventListener("input", () => {
        toggleAiAvailability();
        syncSlugFromPrimary();
    });
    byId("targetWebsite").addEventListener("input", () => {
        syncSlugFromPrimary();
    });
    byId("targetWebsite").addEventListener("change", () => {
        rememberTargetWebsite(byId("targetWebsite").value);
        const wpcSaved =
            (_draftWpCategoryIds && _draftWpCategoryIds[0]) ||
            String(byId("singleWpCategoryId")?.value || "").trim() ||
            "";
        fillSingleWpCategorySelect(wpcSaved);
    });
    toggleAiAvailability();
    syncSlugFromPrimary();
    renderUploadList();
    renderTargetHistory();
    renderWpUrlHistory();
    renderWpUserHistory();
    const restored = restoreFormState();
    const bulkRestored = restoreBulkState();
    try {
        const savedJob = localStorage.getItem(BULK_JOB_STORAGE_KEY());
        if (savedJob) {
            setContentAiMainView("bulk");
            startBulkPoll(savedJob);
        } else if (bulkRestored && (_contentAiMainView === "bulk" || bulkKeywordRows.length)) {
            setContentAiMainView("bulk");
            const tw = byId("targetWebsite");
            const btw = byId("bulkTargetWebsite");
            if (tw && btw && !btw.value.trim()) btw.value = tw.value;
        }
    } catch (_) {}
    ["bulkTargetWebsite", "bulkBrandName", "bulkQuickInput", "bulkKeywordsText", "bulkAddKeywordInput"].forEach((id) => {
        const el = byId(id);
        if (el) {
            el.addEventListener("input", scheduleSaveBulkState);
            el.addEventListener("change", scheduleSaveBulkState);
        }
    });
    window.addEventListener("beforeunload", saveBulkState);
    renderConnectedSitesPanel();
    try {
        refreshPreview();
    } catch (_) {}
    // Initialize rich editor after restoring state so it picks up existing content.
    void initRichEditor();
    // Keep outline textarea expanded to always show full outline.
    try {
        const outlineEl = byId("outlineContent");
        if (outlineEl) outlineEl.addEventListener("input", autoGrowOutline);
        autoGrowOutline();
    } catch (_) {}
    purgeLegacySharedStorage();
    allProjects = [];
    settingsPublishingSitesFlat = [];
    refreshProjects(!restored);
    try { schedulePublishChecklist(); } catch (_) {}
    void fetchSettingsPublishingSites().then(() => {
        renderTargetHistory();
        renderWpUrlHistory();
        renderConnectedSitesPanel();
    });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") return;
        void fetchSettingsPublishingSites().then(() => {
            renderTargetHistory();
            renderWpUrlHistory();
            renderConnectedSitesPanel();
        });
    });
    document.querySelectorAll("input, textarea").forEach((el) => {
        if (el.type === "file") return;
        if (el.id === "content") return;
        el.addEventListener("input", scheduleSaveFormState);
        el.addEventListener("change", scheduleSaveFormState);
    });
    window.addEventListener("beforeunload", () => {
        if (_saveFormStateTimer) {
            window.clearTimeout(_saveFormStateTimer);
            _saveFormStateTimer = null;
        }
        flushSaveFormState();
    });

    if (btnUploadImage) btnUploadImage.addEventListener("click", async () => {
        const files = byId("imageUpload").files;
        if (!files || !files.length) {
            setHint("image", "Vui lòng chọn hình ảnh trước khi tải lên.");
            return;
        }
        setHint("image", "Đang tải hình ảnh...");
        btnUploadImage.disabled = true;
        try {
            for (const file of files) {
                const formData = new FormData();
                formData.append("file", file);
                const res = await fetch(`/content-ai/upload-image?ts=${Date.now()}`, {
                    method: "POST",
                    body: formData,
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Upload failed");
                if (data.url) {
                    uploadedImages.push(data.url);
                    // Auto-insert into content immediately (no extra step).
                    try { insertImageIntoEditor(data.url); } catch (_) {}
                }
            }
            renderUploadList();
            setHint("image", "Đã tải ảnh và chèn vào Content.");
            saveFormState();
        } catch (e) {
            setHint("image", String(e.message || e));
        } finally {
            btnUploadImage.disabled = false;
            byId("imageUpload").value = "";
        }
    });

    btnOutlineReference.addEventListener("click", async () => {
        const competitorUrl = byId("competitorUrl").value.trim();
        if (!competitorUrl) {
            setHint("competitor", "Vui lòng dán link đối thủ trước.");
            return;
        }
        btnOutlineReference.disabled = true;
        setHint("competitor", "Đang phân tích outline đối thủ...");
        try {
            const res = await fetch(`/content-ai/outline-reference?ts=${Date.now()}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ competitor_url: competitorUrl }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không lấy được outline đối thủ.");
            _competitorOutlineCache = String(data.outline || "").trim();
            const current = byId("outlineContent").value.trim();
            byId("outlineContent").value = _competitorOutlineCache;
            autoGrowOutline();
            setHint("competitor", `Đã lấy ${data.count || 0} heading từ bài đối thủ.`);
            if (!current && data.outline) {
                msg.textContent = "Đã điền outline tham khảo từ link đối thủ.";
            }
            saveFormState();
        } catch (e) {
            const raw = String(e.message || e);
            if (/not found/i.test(raw)) {
                setHint("competitor", "Không tìm thấy endpoint hoặc outline. Hãy refresh trang và thử lại URL đối thủ.");
            } else {
                setHint("competitor", raw);
            }
        } finally {
            btnOutlineReference.disabled = false;
        }
    });

    const runGoogleImageSearch = async () => {
        const q = (googleImageQuery ? googleImageQuery.value : "").trim() || byId("primaryKeyword").value.trim();
        if (!q) {
            setHint("google-images", "Vui lòng nhập từ khóa để tìm ảnh.");
            return;
        }
        const num = parseInt((googleImageNum && googleImageNum.value) ? googleImageNum.value : "8", 10) || 8;
        setHint("google-images", "Đang tìm ảnh Google...");
        if (btnGoogleImageSearch) btnGoogleImageSearch.disabled = true;
        try {
            const res = await fetch(`/content-ai/google-images/search?q=${encodeURIComponent(q)}&num=${encodeURIComponent(String(num))}&ts=${Date.now()}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Tìm ảnh thất bại (kiểm tra GOOGLE_API_KEY + GOOGLE_CSE_ID).");
            renderGoogleImageResults(data.items || []);
            setHint("google-images", `Đã tìm thấy ${(data.items || []).length} ảnh.`);
        } catch (e) {
            setHint("google-images", String(e.message || e));
        } finally {
            if (btnGoogleImageSearch) btnGoogleImageSearch.disabled = false;
        }
    };

    if (btnGoogleImageSearch) btnGoogleImageSearch.addEventListener("click", runGoogleImageSearch);
    if (googleImageQuery) {
        googleImageQuery.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                runGoogleImageSearch();
            }
        });
    }

    btnReplaceAll.addEventListener("click", () => {
        const from = byId("replaceFrom").value.trim();
        const to = byId("replaceTo").value.trim();
        const outline = byId("outlineContent").value;
        if (!outline.trim()) {
            setHint("outline-actions", "Vui lòng có outline trước khi Replace All.");
            return;
        }
        if (!from) {
            setHint("outline-actions", "Vui lòng nhập từ cần thay.");
            return;
        }
        const escaped = from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const rgx = new RegExp(escaped, "gi");
        const count = (outline.match(rgx) || []).length;
        byId("outlineContent").value = outline.replace(rgx, to);
        setHint("outline-actions", `Đã thay ${count} vị trí.`);
        autoGrowOutline();
        saveFormState();
    });

    btnRefreshOutline.addEventListener("click", async () => {
        const outline = byId("outlineContent").value.trim();
        if (!outline) {
            setHint("outline-actions", "Vui lòng nhập outline trước khi làm mới.");
            return;
        }
        btnRefreshOutline.disabled = true;
        setHint("outline-actions", "Đang làm mới outline...");
        try {
            const res = await fetch(`/content-ai/outline-refresh?ts=${Date.now()}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ outline }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Làm mới outline thất bại.");
            if (data.outline) byId("outlineContent").value = data.outline;
            autoGrowOutline();
            setHint("outline-actions", "Đã làm mới outline bằng từ đồng nghĩa.");
            saveFormState();
        } catch (e) {
            setHint("outline-actions", String(e.message || e));
        } finally {
            btnRefreshOutline.disabled = false;
        }
    });

    btnCreateContent.addEventListener("click", async () => {
        const primaryKeyword = byId("primaryKeyword").value.trim();
        if (!primaryKeyword) {
            msg.textContent = "Cần nhập từ khóa chính trước.";
            return;
        }
        msg.textContent = "Đang tạo content...";
        _openGenModal();
        try {
            const ctx = buildContext();
            const suggestOutline = await fetch("/content-ai/suggest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ field: "outline_content", ...ctx }),
            });
            const outlineData = await suggestOutline.json().catch(() => ({}));
            if (suggestOutline.ok && outlineData.detected_intent) {
                setDetectedIntentDebug(outlineData.detected_intent);
            }
            if (suggestOutline.ok && outlineData.value && !byId("outlineContent").value.trim()) {
                byId("outlineContent").value = outlineData.value;
                autoGrowOutline();
            }

            const generated = await streamSuggestion("content", ctx);
            if (generated) setContentValue(generated);

            const suggestTitle = await fetch("/content-ai/suggest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ field: "title", ...buildContext() }),
            });
            const titleData = await suggestTitle.json().catch(() => ({}));
            if (suggestTitle.ok && titleData.detected_intent) {
                setDetectedIntentDebug(titleData.detected_intent);
            }
            if (suggestTitle.ok && titleData.value) {
                byId("title").value = _firstLine(titleData.value);
            }

            const suggestMeta = await fetch("/content-ai/suggest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ field: "meta_description", ...buildContext() }),
            });
            const metaData = await suggestMeta.json().catch(() => ({}));
            if (suggestMeta.ok && metaData.detected_intent) {
                setDetectedIntentDebug(metaData.detected_intent);
            }
            if (suggestMeta.ok && metaData.value) {
                byId("meta").value = _firstLine(metaData.value);
            }

            const suggestSlug = await fetch("/content-ai/suggest", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ field: "slug", ...buildContext() }),
            });
            const slugData = await suggestSlug.json().catch(() => ({}));
            if (suggestSlug.ok && slugData.detected_intent) {
                setDetectedIntentDebug(slugData.detected_intent);
            }
            if (suggestSlug.ok && slugData.value) {
                byId("slug").value = _firstLine(slugData.value);
            }
            syncSlugFromPrimary();

            // Ensure the editor content is formatted SEO-friendly (H1/H2/H3, paragraphs, lists).
            // Only run formatter when content is plain text / markdown-like (avoid double-formatting HTML).
            try {
                const cur = String(getContentValue() || "");
                const looksLikeHtml = /<\s*[a-z][^>]*>/i.test(cur);
                const looksLikeMd = /(^|\n)\s{0,3}(#|[-*]\s+|\d+[.)]\s+)/.test(cur);
                if (!looksLikeHtml && (looksLikeMd || cur.includes("\n"))) {
                    formatContentSeo();
                }
            } catch (_) {}

            const draftPayload = buildDraftPayload();
            const draftRes = await fetchDraftOutput(draftPayload);
            const newPid = draftRes && draftRes.project_id ? String(draftRes.project_id).trim() : "";
            if (newPid) activeProjectId = newPid;
            const autoImgEl = byId("autoInsertImagesAfterWrite");
            if (newPid && autoImgEl && autoImgEl.checked) {
                msg.textContent = "Đang chèn ảnh minh họa vào bài…";
                try {
                    const imgData = await autoInsertImagesForProject(newPid, { force: false });
                    const n = Number(imgData.inline_images_count) || 0;
                    msg.textContent =
                        n > 0
                            ? `Đã tạo content và chèn ${n} ảnh vào bài.`
                            : "Đã tạo content và thêm ảnh đại diện.";
                } catch (imgErr) {
                    msg.textContent = `Content xong; chèn ảnh lỗi: ${String(imgErr.message || imgErr)}`;
                }
            }
            await refreshProjects(true);
            rememberTargetWebsite(byId("targetWebsite").value);
            msg.textContent = `Đã tạo content thành công. Output đang ở chế độ ${getOutputFormat() === "json" ? "JSON" : "chữ thường"}.`;
            byId("content").scrollIntoView({ behavior: "smooth", block: "center" });
            saveFormState();
            try { if (btnGenClose) btnGenClose.disabled = false; } catch (_) {}
        try { if (inlineProgress) inlineProgress.classList.remove("show"); } catch (_) {}
        try { if (previewLoading) previewLoading.classList.remove("show"); } catch (_) {}
        } catch (e) {
            msg.textContent = String(e.message || e);
            if (genHint) genHint.textContent = String(e.message || e);
            try { if (btnGenClose) btnGenClose.disabled = false; } catch (_) {}
        try { if (inlineProgress) inlineProgress.classList.remove("show"); } catch (_) {}
        try { if (previewLoading) previewLoading.classList.remove("show"); } catch (_) {}
        }
    });

    if (btnSeoJsonFill) {
        btnSeoJsonFill.addEventListener("click", async () => {
            const keyword = byId("primaryKeyword").value.trim();
            if (!keyword) {
                setHint("primary_keyword", "Vui lòng nhập keyword chính trước.");
                return;
            }
            const secondaryRaw = byId("secondaryKeywords").value || "";
            const secondary = secondaryRaw
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean)
                .slice(0, 20);
            const outline = byId("outlineContent").value || "";
            const contextData = (byId("targetWebsite").value || "").trim();
            const intent = window.prompt("Search intent (ví dụ: thông tin / so sánh / mua dịch vụ...):", "") || "";
            const audience = window.prompt("Đối tượng đọc (ví dụ: người mới / chủ doanh nghiệp...):", "") || "";
            const brand = window.prompt("Brand (tên thương hiệu):", "") || "";

            const oldText = btnSeoJsonFill.textContent;
            btnSeoJsonFill.textContent = "Đang tạo SEO JSON...";
            btnSeoJsonFill.disabled = true;
            try {
                setHint("wp", "");
                const res = await fetch(`/content-ai/article-json?ts=${Date.now()}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        keyword: keyword,
                        secondary_keywords: secondary,
                        intent: intent,
                        audience: audience,
                        brand_name: brand,
                        outline: outline,
                        context_data: contextData,
                    }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không tạo được SEO JSON.");

                // Fill form fields
                if (data.title) byId("title").value = String(data.title || "");
                if (data.meta_description) byId("meta").value = String(data.meta_description || "");
                if (data.slug) byId("slug").value = String(data.slug || "");
                if (Array.isArray(data.tags)) byId("tags").value = (data.tags || []).join(", ");
                if (data.content_html) setContentValue(String(data.content_html || ""));

                // Put full JSON (incl. schema) into Output
                if (outputFormat) outputFormat.value = "json";
                try { persistOutputFormat(); } catch (_) {}
                out.value = JSON.stringify(data, null, 2);

                refreshPreview();
                saveFormState();
                appendPublishLog("OK: Đã đổ title/meta/slug/tags/content + schema vào Output (JSON).");
            } catch (e) {
                appendPublishLog(`Lỗi SEO JSON: ${String((e && e.message) || e)}`);
            } finally {
                btnSeoJsonFill.textContent = oldText;
                btnSeoJsonFill.disabled = false;
            }
        });
    }

    const btnSingleLoadWpCategories = byId("btnSingleLoadWpCategories");
    const singleWpCategoryIdEl = byId("singleWpCategoryId");
    if (btnSingleLoadWpCategories) {
        _syncWpCategoryLoadButtonLabel(String(byId("targetWebsite")?.value || ""));
        btnSingleLoadWpCategories.addEventListener("click", () => {
            btnSingleLoadWpCategories.disabled = true;
            const site = String(byId("targetWebsite")?.value || "").trim();
            const sk = _getWpCategoriesSiteKey(site);
            const isReload = !!(sk && _readWpCategoriesCache(sk));
            void loadSingleWpCategories(isReload).finally(() => {
                btnSingleLoadWpCategories.disabled = false;
                _syncWpCategoryLoadButtonLabel(site);
            });
        });
    }
    if (singleWpCategoryIdEl) {
        singleWpCategoryIdEl.addEventListener("change", () => {
            syncSingleWpCategoryFromSelect();
            saveFormState();
        });
    }

    btn.addEventListener("click", async () => {
        const payload = buildDraftPayload();
        const title = payload.title || "";
        const content = payload.content || "";
        const outline = payload.outline_content || "";
        const primaryKeyword = payload.primary_keyword || "";
        if (!primaryKeyword) {
            msg.textContent = "Can nhap tu khoa chinh truoc.";
            return;
        }
        if (!title || (!content && !outline)) {
            msg.textContent = "Can nhap title va content hoac outline.";
            return;
        }
        msg.textContent = "Đang tạo draft...";
        try {
            await fetchDraftOutput(payload);
            msg.textContent = `Đã tạo draft (${getOutputFormat() === "json" ? "JSON" : "chữ thường"}).`;
            activeProjectId = "";
            await refreshProjects(true);
            rememberTargetWebsite(byId("targetWebsite").value);
            saveFormState();
        } catch (e) {
            msg.textContent = String(e.message || e);
        }
    });

    if (outputFormat) {
        restoreOutputFormat();
        outputFormat.addEventListener("change", () => {
            persistOutputFormat();
            saveFormState();
        });
    }

    restoreOutputAccordion();
    if (btnToggleOutput) {
        const toggle = () => setOutputAccordionOpen(!outputAccordion.classList.contains("open"));
        btnToggleOutput.addEventListener("click", toggle);
        btnToggleOutput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                toggle();
            }
        });
    }

    const publishGateBackdrop = byId("publishGateBackdrop");
    const publishGateModal = byId("publishGateModal");
    const publishGateLists = byId("publishGateLists");
    const publishGateScoreNum = byId("publishGateScoreNum");
    const publishGateGrade = byId("publishGateGrade");
    const publishGateScoreRing = byId("publishGateScoreRing");
    const publishGateSeverity = byId("publishGateSeverity");
    const publishGateSubtitle = byId("publishGateSubtitle");
    const publishGateBack = byId("publishGateBack");
    const publishGateForce = byId("publishGateForce");
    const publishGateClose = byId("publishGateClose");
    let _publishGateProceed = null;

    const closePublishGateModal = () => {
        if (publishGateBackdrop) publishGateBackdrop.classList.remove("open");
        if (publishGateModal) {
            publishGateModal.classList.remove("open");
            publishGateModal.setAttribute("aria-hidden", "true");
        }
        _publishGateProceed = null;
    };
    const renderPublishGateLists = (gate) => {
        if (!publishGateLists) return;
        const sections = [
            { key: "blockers", title: "Chặn publish (blocker)", cls: "pg-blockers" },
            { key: "required_fixes", title: "Bắt buộc sửa", cls: "pg-required" },
            { key: "warnings", title: "Cảnh báo", cls: "pg-warnings" },
            { key: "optional_fixes", title: "Nên tối ưu thêm", cls: "" },
            { key: "suggestions", title: "Gợi ý", cls: "" },
        ];
        let html = "";
        for (const sec of sections) {
            const arr = Array.isArray(gate && gate[sec.key]) ? gate[sec.key].filter(Boolean) : [];
            if (!arr.length) continue;
            html += `<h4 class="${sec.cls}">${_escScoreHtml(sec.title)}</h4><ul class="${sec.cls}">`;
            html += arr.map((t) => `<li>${_escScoreHtml(t)}</li>`).join("");
            html += "</ul>";
        }
        publishGateLists.innerHTML = html || "<p class=\"hint\">Không có chi tiết bổ sung.</p>";
    };
    const openPublishGateModal = (gate, onProceed) => {
        _publishGateProceed = typeof onProceed === "function" ? onProceed : null;
        const sev = String((gate && gate.severity) || "warning");
        const score = Number(gate && gate.total_score);
        const grade = String((gate && gate.grade) || "—");
        if (publishGateScoreNum) publishGateScoreNum.textContent = Number.isFinite(score) ? String(score) : "—";
        if (publishGateGrade) publishGateGrade.textContent = `/100 · ${grade}`;
        if (publishGateScoreRing) {
            publishGateScoreRing.classList.remove("sev-pass", "sev-warn", "sev-blocker");
            publishGateScoreRing.classList.add(
                sev === "pass" ? "sev-pass" : sev === "blocker" ? "sev-blocker" : "sev-warn"
            );
        }
        const sevLabels = { pass: "Đạt", warning: "Cảnh báo", blocker: "Blocker" };
        if (publishGateSeverity) publishGateSeverity.textContent = sevLabels[sev] || sev;
        if (publishGateSubtitle) {
            publishGateSubtitle.textContent =
                sev === "pass"
                    ? "Bài đạt ngưỡng chất lượng — có thể publish."
                    : "Bài chưa đạt đủ tiêu chí — bạn vẫn có thể «Vẫn publish» (soft gate).";
        }
        renderPublishGateLists(gate);
        if (publishGateBackdrop) publishGateBackdrop.classList.add("open");
        if (publishGateModal) {
            publishGateModal.classList.add("open");
            publishGateModal.setAttribute("aria-hidden", "false");
        }
    };
    const runPublishGateCheck = async (publishTarget) => {
        const title = (byId("title") && byId("title").value || "").trim();
        const slug = (byId("slug") && byId("slug").value || "").trim();
        const meta = (byId("meta") && byId("meta").value || "").trim();
        const pk = (byId("primaryKeyword") && byId("primaryKeyword").value || "").trim();
        const sk = (byId("secondaryKeywords") && byId("secondaryKeywords").value || "").trim();
        const html_content = String(getContentValue() || "");
        const target_website = normalizeTargetBase(String(byId("targetWebsite") && byId("targetWebsite").value || "").trim());
        const internal_links = collectPlannedInternalLinks();
        const featured = (uploadedImages && uploadedImages[0]) || "";
        const res = await fetch(`/content-ai/publish-gate?ts=${Date.now()}`, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify({
                title,
                slug,
                meta_description: meta,
                primary_keyword: pk,
                secondary_keywords: sk,
                html_content,
                target_word_count: parseTargetWordCount(),
                target_website,
                internal_links: internal_links.length ? internal_links : null,
                publish_target: publishTarget || "wordpress",
                featured_image_url: featured,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data && data.detail;
            const msgErr =
                typeof detail === "string"
                    ? detail
                    : detail && detail.message
                      ? detail.message
                      : "Publish gate thất bại — không tự động publish.";
            throw new Error(msgErr);
        }
        return data;
    };
    const withPublishGate = async (publishTarget, publishFn) => {
        let gate;
        try {
            gate = await runPublishGateCheck(publishTarget);
        } catch (e) {
            const errMsg = String((e && e.message) || e);
            msg.textContent = errMsg;
            appendPublishLog(`Publish gate lỗi: ${errMsg}`);
            setHint("content", errMsg);
            return;
        }
        if (gate && gate.can_publish) {
            await publishFn();
            return;
        }
        openPublishGateModal(gate, publishFn);
    };
    if (publishGateBack) {
        publishGateBack.addEventListener("click", (ev) => {
            ev.preventDefault();
            closePublishGateModal();
        });
    }
    if (publishGateClose) {
        publishGateClose.addEventListener("click", (ev) => {
            ev.preventDefault();
            closePublishGateModal();
        });
    }
    if (publishGateBackdrop) {
        publishGateBackdrop.addEventListener("click", () => closePublishGateModal());
    }
    if (publishGateForce) {
        publishGateForce.addEventListener("click", async (ev) => {
            ev.preventDefault();
            const fn = _publishGateProceed;
            closePublishGateModal();
            if (fn) await fn();
        });
    }

    const executeWpPublishDraft = async (publishMode) => {
        const cred = resolveWpPublishCredentials();
        const wpUrl = cred.wpUrl;
        const wpUsername = cred.username;
        const wpAppPassword = cred.app_password;
        const wpSeoPlugin = cred.seo_plugin;
        const primaryKeyword = byId("primaryKeyword").value.trim();
        const title = byId("title").value.trim();
        const content = getContentValue().trim();
        if (!wpUrl || !primaryKeyword || !title || !content) {
            const m = "Vui lòng nhập URL WordPress, từ khóa, tiêu đề và nội dung.";
            msg.textContent = m;
            appendPublishLog(m);
            return;
        }
        if (!wpUsername || !wpAppPassword) {
            const m = "Chưa có username/app password cho site này — bấm Edit (hoặc Thêm site đăng bài) để lưu.";
            msg.textContent = m;
            appendPublishLog(m);
            return;
        }
        const isPublish = publishMode === "publish";
        publishLog.value = "";
        appendPublishLog(
            isPublish ? "Bắt đầu publish (đăng bài) lên WordPress..." : "Bắt đầu publish draft lên WordPress..."
        );
        msg.textContent = isPublish ? "Đang đăng bài lên WordPress..." : "Đang đăng bản nháp lên WordPress...";
        const btn = isPublish ? btnPublishNow : btnPublish;
        const oldPublishText = btn ? btn.textContent : "";
        if (btn) {
            btn.disabled = true;
            btn.classList.add("loading");
            btn.textContent = isPublish ? "Đang đăng bài..." : "Đang đăng bản nháp...";
        }
        try {
            const draftPayload = await ensureDraftPayloadForPublish();
            appendPublishLog("Đã có draft payload.");
            const res = await fetch("/content-ai/publish-draft", {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({
                    wp_url: wpUrl,
                    username: wpUsername,
                    app_password: wpAppPassword,
                    seo_plugin: wpSeoPlugin,
                    primary_keyword: primaryKeyword,
                    publish_mode: publishMode,
                    draft_payload: draftPayload,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const detail = data && data.detail ? data.detail : {};
                if (detail && Array.isArray(detail.logs)) {
                    setPublishLogLines(detail.logs);
                } else if (detail && typeof detail === "string") {
                    appendPublishLog(detail);
                } else {
                    appendPublishLog(JSON.stringify(detail || data));
                }
                throw new Error((detail && detail.message) ? detail.message : "Publish thất bại.");
            }
            if (Array.isArray(data.logs)) setPublishLogLines(data.logs);
            appendPublishLog(`Thành công: post_id=${data.post_id || ""}, status=${data.status || ""}`);
            msg.textContent = isPublish
                ? "Đăng bài thành công lên WordPress."
                : "Đăng bản nháp thành công lên WordPress.";
            rememberTargetWebsite(byId("targetWebsite").value);
            rememberWpUrl(wpUrl);
            rememberWpUser(wpUsername);
            saveFormState();
        } catch (e) {
            msg.textContent = String(e.message || e);
            appendPublishLog(`Lỗi: ${String(e.message || e)}`);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.classList.remove("loading");
                btn.textContent = oldPublishText;
            }
        }
    };

    btnPublish.addEventListener("click", async () => {
        if (btnPublish.disabled) return;
        await withPublishGate("wordpress", () => executeWpPublishDraft("draft"));
    });

    if (btnPublishNow) {
        btnPublishNow.addEventListener("click", async () => {
            if (btnPublishNow.disabled) return;
            await withPublishGate("wordpress", () => executeWpPublishDraft("publish"));
        });
    }

    if (btnWpUpdateContent) {
        btnWpUpdateContent.addEventListener("click", async () => {
            const cred = resolveWpPublishCredentials();
            const wpUrl = cred.wpUrl;
            const wpUsername = cred.username;
            const wpAppPassword = cred.app_password;
            if (!wpUrl) {
                appendPublishLog("Thiếu WP URL.");
                return;
            }
            if (!wpUsername || !wpAppPassword) {
                appendPublishLog("Chưa có username/app password — lưu site qua Edit / Thêm site đăng bài.");
                return;
            }
            const postIdRaw = window.prompt("Nhập Post ID cần cập nhật (ví dụ: 123):", "");
            const postId = Number(String(postIdRaw || "").trim());
            if (!Number.isFinite(postId) || postId <= 0) {
                appendPublishLog("Post ID không hợp lệ.");
                return;
            }
            const ok = window.confirm(`Cập nhật content hiện tại lên WordPress?\\nPost ID: ${postId}`);
            if (!ok) return;
            try {
                btnWpUpdateContent.disabled = true;
                appendPublishLog(`Đang cập nhật Post ID ${postId}...`);
                const res = await fetch("/wp/update-post", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        wp_url: wpUrl,
                        username: wpUsername,
                        app_password: wpAppPassword,
                        post_type: "posts",
                        post_id: postId,
                        content_html: getContentValue(),
                        dry_run: false,
                    }),
                });
                const d = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error((d && (d.detail || d.message)) ? String(d.detail || d.message) : "Update failed");
                appendPublishLog(`OK: Đã cập nhật. Link: ${d.link || "—"}`);
            } catch (e) {
                appendPublishLog(`Lỗi cập nhật: ${String((e && e.message) || e)}`);
            } finally {
                btnWpUpdateContent.disabled = false;
            }
        });
    }

    // Remember WP URL as user types/leaves field (builds history even before publish).
    const wpUrlEl = byId("wpUrl");
    if (wpUrlEl) {
        wpUrlEl.addEventListener("blur", () => {
            rememberWpUrl(wpUrlEl.value);
            fillWpCredentialsFromSavedProfile();
        });
        wpUrlEl.addEventListener("change", () => {
            rememberWpUrl(wpUrlEl.value);
            fillWpCredentialsFromSavedProfile();
        });
    }

    if (btnModeVisual) {
        btnModeVisual.addEventListener("click", () => {
            editorMode = "visual";
            try { if (window.tinymce && tinymce.get("content")) tinymce.get("content").save(); } catch (_) {}
            refreshEditorModeUi();
            refreshPreview();
        });
    }
    if (btnModeCode) {
        btnModeCode.addEventListener("click", () => {
            if (FORCE_VISUAL_MODE) return;
            editorMode = "code";
            const ta = byId("content");
            if (ta) ta.value = getContentValue();
            refreshEditorModeUi();
        });
    }
    if (btnToolBold) btnToolBold.addEventListener("click", () => execEditorCommand("bold"));
    if (btnToolItalic) btnToolItalic.addEventListener("click", () => execEditorCommand("italic"));
    if (btnToolUnderline) btnToolUnderline.addEventListener("click", () => execEditorCommand("underline"));
    if (btnToolQuote) btnToolQuote.addEventListener("click", () => execEditorCommand("blockquote"));
    if (btnToolH2) btnToolH2.addEventListener("click", () => execEditorCommand("h2"));
    if (btnToolH3) btnToolH3.addEventListener("click", () => execEditorCommand("h3"));
    if (btnToolUl) btnToolUl.addEventListener("click", () => execEditorCommand("ul"));
    if (btnToolOl) btnToolOl.addEventListener("click", () => execEditorCommand("ol"));
    if (btnToolAlignLeft) btnToolAlignLeft.addEventListener("click", () => execEditorCommand("align-left"));
    if (btnToolAlignCenter) btnToolAlignCenter.addEventListener("click", () => execEditorCommand("align-center"));
    if (btnToolAlignRight) btnToolAlignRight.addEventListener("click", () => execEditorCommand("align-right"));
    if (btnToolUndo) btnToolUndo.addEventListener("click", () => execEditorCommand("undo"));
    if (btnToolRedo) btnToolRedo.addEventListener("click", () => execEditorCommand("redo"));
    if (btnToolLink) btnToolLink.addEventListener("click", () => execEditorCommand("link"));
    if (btnToolHr) btnToolHr.addEventListener("click", () => execEditorCommand("hr"));
    if (btnToolTable) btnToolTable.addEventListener("click", () => execEditorCommand("table"));
    if (btnToolClear) btnToolClear.addEventListener("click", () => execEditorCommand("clear"));
    if (editorBlockFormat) {
        editorBlockFormat.addEventListener("change", () => {
            const v = String(editorBlockFormat.value || "");
            if (v === "blockquote") execEditorCommand("blockquote");
            else if (v === "h1") execEditorCommand("h1");
            else if (v === "h2") execEditorCommand("h2");
            else if (v === "h3") execEditorCommand("h3");
            else if (v === "h4") execEditorCommand("h4");
            else if (v === "h5") execEditorCommand("h5");
            else if (v === "h6") execEditorCommand("h6");
            else execEditorCommand("paragraph");
        });
    }
    let _lastScreamingFrogTsv = "";
    const LEGACY_CUSTOM_LINK_LIB_KEY = "digiseo_content_ai_custom_link_library";
    const getCustomLinkRowsEl = () => document.getElementById("customLinkRows");
    const customLinkLibraryList = byId("customLinkLibraryList");
    const internalLinkApplyResults = byId("internalLinkApplyResults");
    const btnAddCustomLink = byId("btnAddCustomLink");
    const btnSaveCustomToLibrary = byId("btnSaveCustomToLibrary");
    const btnApplyCustomInternalLinks = byId("btnApplyCustomInternalLinks");
    const customLinkUseLlm = byId("customLinkUseLlm");
    const hintCustomLinkApply = byId("hint-custom-link-apply");
    if (customLinkUseLlm && !customLinkUseLlm.dataset.llmSwitchBound) {
        customLinkUseLlm.dataset.llmSwitchBound = "1";
        syncLlmSwitchHighlight(customLinkUseLlm);
        customLinkUseLlm.addEventListener("change", () => syncLlmSwitchHighlight(customLinkUseLlm));
    }
    let _customLinkRowSeq = 0;

    const customLinkUrlHost = (url) => {
        try {
            let h = new URL(String(url || "").includes("://") ? url : `https://${url}`).hostname.toLowerCase();
            if (h.startsWith("www.")) h = h.slice(4);
            return h;
        } catch (_) {
            return "";
        }
    };
    const customLinkBelongsToSite = (linkUrl, siteBase) => {
        const lh = customLinkUrlHost(linkUrl);
        const sh = customLinkUrlHost(siteBase);
        if (!lh || !sh) return false;
        return lh === sh || lh.endsWith(`.${sh}`) || sh.endsWith(`.${lh}`);
    };
    const getCustomLinkLibraryScope = () => {
        const pid = String(activeProjectId || "").trim();
        if (pid) {
            const p = (allProjects || []).find((x) => String(x.id) === pid);
            const tw = normalizeTargetBase(String((p && p.target_website) || byId("targetWebsite")?.value || ""));
            let label = String((p && (p.title || p.primary_keyword)) || "").trim();
            if (!label && tw) label = connectedSiteHostLabel(tw);
            if (!label) label = "Dự án hiện tại";
            return { ok: true, type: "project", storageId: `p_${pid}`, label, siteBase: tw };
        }
        const tw = normalizeTargetBase(String(byId("targetWebsite")?.value || "").trim());
        if (tw) {
            const sk = connectedSiteKey(tw) || tw;
            return {
                ok: true,
                type: "site",
                storageId: `s_${sk.replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 120)}`,
                label: connectedSiteHostLabel(tw),
                siteBase: tw,
            };
        }
        return { ok: false, type: "none", storageId: "", label: "", siteBase: "" };
    };
    const customLinkLibraryStorageKey = () => {
        const scope = getCustomLinkLibraryScope();
        if (!scope.ok || !scope.storageId) return "";
        return userStorageKey(`content_ai_custom_link_library_v2_${scope.storageId}`);
    };
    const loadLegacyGlobalCustomLinkLibrary = () => {
        try {
            const raw = localStorage.getItem(LEGACY_CUSTOM_LINK_LIB_KEY);
            const arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (_) {
            return [];
        }
    };
    const tryMigrateLegacyCustomLinkLibrary = (scope) => {
        if (!scope.ok || !scope.siteBase) return;
        const key = customLinkLibraryStorageKey();
        if (!key) return;
        try {
            if (localStorage.getItem(key)) return;
        } catch (_) {
            return;
        }
        const legacy = loadLegacyGlobalCustomLinkLibrary();
        if (!legacy.length) return;
        const migrated = legacy.filter((it) => customLinkBelongsToSite(it && it.target_url, scope.siteBase));
        if (!migrated.length) return;
        try {
            localStorage.setItem(key, JSON.stringify(migrated.slice(0, 80)));
        } catch (_) { /* ignore */ }
    };
    const loadCustomLinkLibrary = () => {
        const scope = getCustomLinkLibraryScope();
        if (!scope.ok) return [];
        tryMigrateLegacyCustomLinkLibrary(scope);
        const key = customLinkLibraryStorageKey();
        if (!key) return [];
        try {
            const raw = localStorage.getItem(key);
            const arr = raw ? JSON.parse(raw) : [];
            if (!Array.isArray(arr)) return [];
            if (!scope.siteBase) return arr;
            return arr.filter((it) => customLinkBelongsToSite(it && it.target_url, scope.siteBase));
        } catch (_) {
            return [];
        }
    };
    const saveCustomLinkLibrary = (items) => {
        const scope = getCustomLinkLibraryScope();
        if (!scope.ok) return false;
        const key = customLinkLibraryStorageKey();
        if (!key) return false;
        let clean = (items || []).map((x) => ({ ...x }));
        if (scope.siteBase) {
            clean = clean.filter((it) => customLinkBelongsToSite(it.target_url, scope.siteBase));
        }
        try {
            localStorage.setItem(key, JSON.stringify(clean.slice(0, 80)));
            return true;
        } catch (_) {
            return false;
        }
    };
    const renderCustomLinkLibrary = () => {
        if (!customLinkLibraryList) return;
        const scope = getCustomLinkLibraryScope();
        if (btnSaveCustomToLibrary) {
            btnSaveCustomToLibrary.disabled = !scope.ok;
            btnSaveCustomToLibrary.title = scope.ok
                ? `Lưu vào thư viện của ${scope.label}`
                : "Cần dự án hoặc Target website";
        }
        const lib = loadCustomLinkLibrary();
        customLinkLibraryList.innerHTML = "";
        if (!scope.ok || !lib.length) {
            return;
        }
        lib.forEach((it, idx) => {
            const row = document.createElement("div");
            row.className = "custom-link-lib-item";
            const meta = document.createElement("div");
            meta.style.minWidth = "0";
            const t = document.createElement("div");
            t.textContent = String(it.anchor_text || "").trim() || "(anchor)";
            t.style.fontWeight = "700";
            const u = document.createElement("div");
            u.className = "hint";
            u.textContent = String(it.target_url || "").trim();
            u.style.wordBreak = "break-all";
            meta.appendChild(t);
            meta.appendChild(u);
            const actions = document.createElement("div");
            actions.style.display = "flex";
            actions.style.gap = "4px";
            const btnUse = document.createElement("button");
            btnUse.type = "button";
            btnUse.className = "mini-btn";
            btnUse.textContent = "Dùng";
            btnUse.addEventListener("click", () => addCustomLinkRow(it));
            const btnDel = document.createElement("button");
            btnDel.type = "button";
            btnDel.className = "mini-btn danger";
            btnDel.textContent = "Xóa";
            btnDel.addEventListener("click", () => {
                const next = loadCustomLinkLibrary().filter((_, i) => i !== idx);
                saveCustomLinkLibrary(next);
                renderCustomLinkLibrary();
            });
            actions.appendChild(btnUse);
            actions.appendChild(btnDel);
            row.appendChild(meta);
            row.appendChild(actions);
            customLinkLibraryList.appendChild(row);
        });
    };
    const normalizeCustomUrl = (raw) => {
        let s = String(raw || "").trim();
        if (!s) return "";
        if (!/^https?:\/\//i.test(s)) s = `https://${s.replace(/^\/+/, "")}`;
        return s;
    };
    const addCustomLinkRow = (seed) => {
        const customLinkRows = getCustomLinkRowsEl();
        if (!customLinkRows) return;
        const id = ++_customLinkRowSeq;
        const s = seed && typeof seed === "object" ? seed : {};
        const row = document.createElement("div");
        row.className = "custom-link-row";
        row.setAttribute("data-custom-id", String(id));
        row.innerHTML = `
            <input type="checkbox" class="custom-link-cb" data-custom-id="${id}" checked title="Chọn" />
            <input type="text" class="cl-url" inputmode="url" autocomplete="url" placeholder="https://..." value="${String(s.target_url || "").replace(/"/g, "&quot;")}" />
            <input type="text" class="cl-anchor" placeholder="Anchor text" value="${String(s.anchor_text || "").replace(/"/g, "&quot;")}" />
            <select class="cl-type">
                <option value="money_page">money_page</option>
                <option value="blog">blog</option>
                <option value="category">category</option>
                <option value="service">service</option>
                <option value="course">course</option>
                <option value="manual">manual</option>
            </select>
            <select class="cl-priority">
                <option value="high">high</option>
                <option value="medium">medium</option>
                <option value="low">low</option>
            </select>
            <input type="number" class="cl-max" min="1" max="3" value="${Number(s.max_insert) > 0 ? Number(s.max_insert) : 1}" title="max_insert" />
            <button type="button" class="mini-btn danger cl-del" title="Xóa dòng">×</button>
        `;
        const typeSel = row.querySelector(".cl-type");
        const priSel = row.querySelector(".cl-priority");
        if (typeSel && s.link_type) typeSel.value = String(s.link_type);
        if (priSel && s.priority) priSel.value = String(s.priority);
        row.querySelector(".cl-del")?.addEventListener("click", () => row.remove());
        customLinkRows.appendChild(row);
    };
    const collectCheckedCustomLinks = () => {
        const root = document.getElementById("customLinkPanel") || getCustomLinkRowsEl();
        if (!root) return [];
        const out = [];
        root.querySelectorAll(".custom-link-row").forEach((row) => {
            const cbs = row.querySelectorAll("input.custom-link-cb[type='checkbox'], input.custom-link-cb");
            const hasCheckbox = cbs.length > 0;
            const isChecked = !hasCheckbox || Array.from(cbs).some((c) => c.checked);
            if (!isChecked) return;
            const url = normalizeCustomUrl(row.querySelector(".cl-url")?.value);
            const anchor = String(row.querySelector(".cl-anchor")?.value || "").trim();
            if (!url && !anchor) return;
            out.push({
                target_url: url,
                anchor_text: anchor,
                link_type: String(row.querySelector(".cl-type")?.value || "manual"),
                priority: String(row.querySelector(".cl-priority")?.value || "medium"),
                max_insert: Math.max(1, Math.min(3, Number(row.querySelector(".cl-max")?.value) || 1)),
            });
        });
        return out;
    };
    const getValidCustomLinksForApply = () =>
        collectCheckedCustomLinks().filter((x) => x.target_url && x.anchor_text);
    const renderInternalApplyResults = (rows) => {
        if (!internalLinkApplyResults) return;
        const arr = Array.isArray(rows) ? rows : [];
        if (!arr.length) {
            internalLinkApplyResults.style.display = "none";
            internalLinkApplyResults.innerHTML = "";
            return;
        }
        internalLinkApplyResults.style.display = "block";
        const tbl = document.createElement("table");
        const thead = document.createElement("thead");
        thead.innerHTML = "<tr><th>Anchor</th><th>URL</th><th>Nguồn</th><th>Trạng thái</th><th>Ghi chú</th></tr>";
        tbl.appendChild(thead);
        const tbody = document.createElement("tbody");
        arr.forEach((r) => {
            const tr = document.createElement("tr");
            const st = String(r.status || "");
            const stCls = st === "inserted" ? "st-inserted" : "st-skipped";
            tr.innerHTML = `
                <td>${escapeHtml(String(r.anchor_text || ""))}</td>
                <td style="word-break:break-all;">${escapeHtml(String(r.target_url || ""))}</td>
                <td>${escapeHtml(String(r.source || ""))}</td>
                <td class="${stCls}">${escapeHtml(st)}</td>
                <td>${escapeHtml(String(r.reason || ""))}</td>
            `;
            tbody.appendChild(tr);
        });
        tbl.appendChild(tbody);
        internalLinkApplyResults.innerHTML = "";
        const cap = document.createElement("div");
        cap.className = "internal-suggest-sub";
        cap.textContent = "KẾT QUẢ CHÈN LINK";
        internalLinkApplyResults.appendChild(cap);
        internalLinkApplyResults.appendChild(tbl);
    };
    const escapeHtml = (s) => String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    if (btnAddCustomLink) btnAddCustomLink.addEventListener("click", () => addCustomLinkRow({ link_type: "money_page", priority: "high" }));
    if (btnSaveCustomToLibrary) {
        btnSaveCustomToLibrary.addEventListener("click", () => {
            const scope = getCustomLinkLibraryScope();
            if (!scope.ok) {
                setHint(
                    "content",
                    "Mở dự án hoặc nhập Target website trước khi lưu thư viện custom link."
                );
                return;
            }
            const picked = getValidCustomLinksForApply();
            if (!picked.length) {
                setHint("content", "Chọn ít nhất một custom link hợp lệ (URL + anchor) để lưu thư viện.");
                return;
            }
            const mismatched = scope.siteBase
                ? picked.filter((p) => !customLinkBelongsToSite(p.target_url, scope.siteBase))
                : [];
            if (mismatched.length) {
                setHint(
                    "content",
                    `Có ${mismatched.length} link không thuộc site «${scope.label}» — chỉ lưu link cùng domain Target website.`
                );
                return;
            }
            const lib = loadCustomLinkLibrary();
            picked.forEach((p) => {
                const dup = lib.some(
                    (x) => String(x.target_url).trim() === p.target_url && String(x.anchor_text).trim() === p.anchor_text
                );
                if (!dup) lib.unshift({ ...p, saved_at: Date.now(), scope_label: scope.label });
            });
            if (!saveCustomLinkLibrary(lib)) {
                setHint("content", "Không ghi được thư viện (localStorage).");
                return;
            }
            renderCustomLinkLibrary();
            setHint("content", `Đã lưu ${picked.length} link vào thư viện «${scope.label}».`);
        });
    }
    renderCustomLinkLibrary();
    const targetWebsiteForCustomLib = byId("targetWebsite");
    if (targetWebsiteForCustomLib) {
        let _customLibRefreshTimer = null;
        const scheduleCustomLibRefresh = () => {
            if (_customLibRefreshTimer) clearTimeout(_customLibRefreshTimer);
            _customLibRefreshTimer = setTimeout(() => {
                try {
                    renderCustomLinkLibrary();
                } catch (_) {}
            }, 300);
        };
        targetWebsiteForCustomLib.addEventListener("input", scheduleCustomLibRefresh);
        targetWebsiteForCustomLib.addEventListener("change", scheduleCustomLibRefresh);
    }
    const _currentUrlGuess = () => {
        const site = String(byId("targetWebsite").value || "").trim().replace(/\/+$/, "");
        const slug = String(byId("slug").value || "").trim().replace(/^\/+/, "");
        if (!site) return "";
        return slug ? `${site}/${slug}` : site;
    };
    const renderInternalCandidates = (items) => {
        if (!internalLinkCandidates) return;
        internalLinkCandidates.innerHTML = "";
        const arr = Array.isArray(items) ? items : [];
        const hintIl = byId("hint-internal-links");
        if (hintIl) {
            hintIl.textContent = arr.length
                ? "Tick chọn dòng (hoặc «Chọn tất cả») → bấm «Đi link» để chèn lần lượt (loading tròn → ✓ khi xong)."
                : "Bấm «Tìm bài liên quan» khi đã có target website.";
        }
        if (!arr.length) {
            internalLinkCandidates.innerHTML = "<div class=\"hint\">Không tìm thấy bài liên quan. Thử thêm từ khóa phụ, hoặc viết trong content các cụm liên quan chủ đề (để vừa làm seed tìm WP vừa làm anchor).</div>";
            return;
        }
        const artTitle = (byId("title") && String(byId("title").value || "").trim()) || "(Bài đang soạn)";
        const pk = (byId("primaryKeyword") && String(byId("primaryKeyword").value || "").trim()) || "";
        const wrap = document.createElement("div");
        wrap.className = "internal-suggest-wrap";

        const head = document.createElement("div");
        head.className = "internal-suggest-head";
        const curRow = document.createElement("div");
        curRow.className = "internal-suggest-current";
        const ch = document.createElement("span");
        ch.className = "internal-suggest-check";
        ch.textContent = "✓";
        const tit = document.createElement("span");
        tit.className = "internal-suggest-cur-title";
        tit.textContent = artTitle;
        curRow.appendChild(ch);
        curRow.appendChild(tit);
        head.appendChild(curRow);
        const meta = document.createElement("div");
        meta.className = "internal-suggest-meta";
        const urlLbl = document.createElement("span");
        urlLbl.textContent = "🔗 URL";
        meta.appendChild(urlLbl);
        if (pk) {
            const pkEl = document.createElement("span");
            pkEl.className = "internal-suggest-pk";
            pkEl.textContent = `"${pk}"`;
            meta.appendChild(pkEl);
        }
        const cnt = document.createElement("span");
        cnt.className = "internal-suggest-count";
        cnt.textContent = `${arr.length} gợi ý`;
        meta.appendChild(cnt);
        head.appendChild(meta);
        wrap.appendChild(head);

        const sub = document.createElement("div");
        sub.className = "internal-suggest-sub";
        sub.textContent = `GỢI Ý MỚI (${arr.length})`;
        wrap.appendChild(sub);

        const ilToolbar = document.createElement("div");
        ilToolbar.className = "internal-suggest-toolbar";
        const llmLbl = document.createElement("label");
        llmLbl.className = "il-llm-switch";
        if (getInternalLinkUseLlm()) llmLbl.classList.add("is-on");
        const llmInp = document.createElement("input");
        llmInp.type = "checkbox";
        llmInp.id = "internalLinkUseLlm";
        llmInp.className = "il-llm-switch-input";
        llmInp.checked = getInternalLinkUseLlm();
        const llmTrack = document.createElement("span");
        llmTrack.className = "il-llm-switch-track";
        llmTrack.setAttribute("aria-hidden", "true");
        const llmTxt = document.createElement("span");
        llmTxt.className = "il-llm-switch-text";
        llmTxt.textContent = "Dùng LLM (viết đoạn ngắn + chèn anchor)";
        llmLbl.appendChild(llmInp);
        llmLbl.appendChild(llmTrack);
        llmLbl.appendChild(llmTxt);
        llmInp.addEventListener("change", () => {
            setInternalLinkUseLlm(llmInp.checked);
            llmLbl.classList.toggle("is-on", llmInp.checked);
            ilHint.textContent = getInternalLinkUseLlm()
                ? "Bật LLM: mỗi link bọc trong 1–2 câu ngữ cảnh (không chèn link trần sát nhau)."
                : "Ưu tiên: anchor trong bài (lần đầu). Thiếu anchor → popup «Tham khảo thêm».";
        });
        ilToolbar.appendChild(llmLbl);
        const ilHint = document.createElement("span");
        ilHint.className = "hint";
        ilHint.style.margin = "0";
        ilHint.textContent = getInternalLinkUseLlm()
            ? "Bật LLM: mỗi link bọc trong 1–2 câu ngữ cảnh (không chèn link trần sát nhau)."
            : "Ưu tiên: anchor trong bài (lần đầu). Thiếu anchor → popup «Tham khảo thêm».";
        ilToolbar.appendChild(ilHint);
        const btnIlSelectAll = document.createElement("button");
        btnIlSelectAll.type = "button";
        btnIlSelectAll.className = "mini-btn";
        btnIlSelectAll.textContent = "Chọn tất cả";
        btnIlSelectAll.title = "Tick chọn mọi dòng gợi ý";
        ilToolbar.appendChild(btnIlSelectAll);
        wrap.appendChild(ilToolbar);

        const tbl = document.createElement("table");
        tbl.className = "internal-suggest-table no-digiseo-table";
        const thead = document.createElement("thead");
        const trh = document.createElement("tr");
        const th0 = document.createElement("th");
        th0.className = "col-cb";
        const headerSelectAll = document.createElement("input");
        headerSelectAll.type = "checkbox";
        headerSelectAll.id = "internalLinkSelectAll";
        headerSelectAll.title = "Chọn tất cả";
        headerSelectAll.checked = false;
        th0.appendChild(headerSelectAll);
        const th1 = document.createElement("th");
        th1.textContent = "ANCHOR / ĐIỂM";
        const th2 = document.createElement("th");
        th2.textContent = "BÀI VIẾT ĐÍCH";
        const th3 = document.createElement("th");
        th3.className = "col-action";
        const bulkApplyBtn = document.createElement("button");
        bulkApplyBtn.type = "button";
        bulkApplyBtn.className = "btn-il-bulk-apply";
        bulkApplyBtn.textContent = "Đi link";
        bulkApplyBtn.title = "Chèn internal link lần lượt cho các dòng đã tick chọn";
        bulkApplyBtn.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            runInternalLinksBulkFromTable(bulkApplyBtn);
        });
        th3.appendChild(bulkApplyBtn);
        trh.appendChild(th0);
        trh.appendChild(th1);
        trh.appendChild(th2);
        trh.appendChild(th3);
        thead.appendChild(trh);
        tbl.appendChild(thead);
        const tbody = document.createElement("tbody");
        const syncInternalLinkSelectAllHeader = () => {
            const all = tbody.querySelectorAll("input.internal-link-cb:not(:disabled)");
            const checked = tbody.querySelectorAll("input.internal-link-cb:checked:not(:disabled)");
            if (!all.length) {
                headerSelectAll.checked = false;
                headerSelectAll.indeterminate = false;
                return;
            }
            headerSelectAll.checked = checked.length === all.length;
            headerSelectAll.indeterminate = checked.length > 0 && checked.length < all.length;
            btnIlSelectAll.textContent =
                checked.length === all.length && all.length ? "Bỏ chọn tất cả" : "Chọn tất cả";
        };
        const setAllInternalLinkRows = (on) => {
            tbody.querySelectorAll("input.internal-link-cb:not(:disabled)").forEach((rowCb) => {
                rowCb.checked = !!on;
            });
            syncInternalLinkSelectAllHeader();
            scheduleSaveFormState();
        };
        headerSelectAll.addEventListener("change", () => {
            setAllInternalLinkRows(headerSelectAll.checked);
        });
        btnIlSelectAll.addEventListener("click", (ev) => {
            ev.preventDefault();
            const all = tbody.querySelectorAll("input.internal-link-cb:not(:disabled)");
            const checked = tbody.querySelectorAll("input.internal-link-cb:checked:not(:disabled)");
            setAllInternalLinkRows(checked.length !== all.length);
        });
        arr.forEach((it, idx) => {
            const displayTitle = String(it.title || "").trim()
                || String(it.slug || "").replace(/-/g, " ").trim()
                || String(it.link || "").trim()
                || `Bài liên quan #${idx + 1}`;
            const tr = document.createElement("tr");
            tr.setAttribute("data-idx", String(idx));
            const td0 = document.createElement("td");
            td0.className = "col-cb";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.className = "internal-link-cb";
            cb.setAttribute("data-idx", String(idx));
            cb.checked = false;
            cb.addEventListener("change", syncInternalLinkSelectAllHeader);
            td0.appendChild(cb);
            const td1 = document.createElement("td");
            td1.className = "internal-anchor-cell";
            const inp = document.createElement("input");
            inp.type = "text";
            inp.className = "internal-link-anchor-input";
            inp.setAttribute("data-idx", String(idx));
            inp.setAttribute("placeholder", "Từ khóa chính bài đích (có dấu)");
            const anchorDefault =
                String(it.suggested_anchor || it.anchor_text || it.target_primary_keyword || it.kw_hint_primary || "").trim() ||
                String(it.title || "")
                    .trim()
                    .split("|")[0]
                    .trim();
            inp.value = anchorDefault.slice(0, 120);
            const scoreWrap = document.createElement("div");
            scoreWrap.style.marginTop = "6px";
            const rel = Number(it.relevance_score);
            if (Number.isFinite(rel)) {
                const badge = document.createElement("span");
                badge.className = "il-score-badge " + (rel >= 80 ? "il-score-high" : rel >= 60 ? "il-score-med" : "il-score-low");
                badge.textContent = `${rel}/100`;
                badge.title = "Điểm liên quan (relevance_score)";
                scoreWrap.appendChild(badge);
            }
            if (it.anchor_in_body) {
                const ab = document.createElement("span");
                ab.className = "hint";
                ab.style.fontSize = "0.65rem";
                ab.textContent = "có trong bài";
                scoreWrap.appendChild(ab);
            }
            td1.appendChild(inp);
            if (scoreWrap.childNodes.length) td1.appendChild(scoreWrap);
            const td2 = document.createElement("td");
            td2.className = "internal-target-cell";
            const tdiv = document.createElement("div");
            tdiv.className = "internal-target-title";
            tdiv.textContent = displayTitle;
            td2.appendChild(tdiv);
            const pt = String(it.page_type || "").trim();
            if (pt) {
                const ptl = document.createElement("div");
                ptl.className = "il-page-type";
                const ptLabels = {
                    money_page: "Money page",
                    service: "Dịch vụ",
                    pillar: "Pillar",
                    course: "Khóa học",
                    blog: "Blog",
                    category: "Danh mục",
                };
                ptl.textContent = (ptLabels[pt] || pt) + (it.priority ? ` · ${it.priority}` : "");
                td2.appendChild(ptl);
            }
            const udiv = document.createElement("div");
            udiv.className = "hint internal-target-url";
            udiv.textContent = String(it.link || "");
            td2.appendChild(udiv);
            const td3 = document.createElement("td");
            td3.className = "col-action";
            const statusWrap = document.createElement("div");
            statusWrap.className = "il-row-status";
            const circle = document.createElement("span");
            circle.className = "il-row-circle";
            circle.setAttribute("data-idx", String(idx));
            circle.setAttribute("aria-label", "Trạng thái chèn link");
            statusWrap.appendChild(circle);
            td3.appendChild(statusWrap);
            tr.appendChild(td0);
            tr.appendChild(td1);
            tr.appendChild(td2);
            tr.appendChild(td3);
            tbody.appendChild(tr);
        });
        syncInternalLinkSelectAllHeader();
        tbl.appendChild(tbody);
        wrap.appendChild(tbl);
        internalLinkCandidates.appendChild(wrap);
    };
    if (btnFindInternalLinks) {
        btnFindInternalLinks.addEventListener("click", async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            const siteRaw = String(byId("targetWebsite").value || "").trim();
            const site = normalizeTargetBase(siteRaw) || siteRaw;
            if (!site) {
                const msg = "Thiếu Target website — nhập https://domain.com ở form phía trên hoặc chọn site đã kết nối.";
                setHint("content", msg);
                setHint("internal-links", msg);
                return;
            }
            const oldText = btnFindInternalLinks.textContent;
            btnFindInternalLinks.textContent = "Đang tìm...";
            btnFindInternalLinks.disabled = true;
            setHint("internal-links", "Đang tìm bài trên WordPress + SERP…");
            try {
                const res = await apiFetch(`/content-ai/wp-internal-links/candidates?ts=${Date.now()}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        target_website: site,
                        primary_keyword: byId("primaryKeyword").value.trim(),
                        secondary_keywords: byId("secondaryKeywords").value.trim(),
                        content_html: getContentValue(),
                        current_slug: byId("slug").value.trim(),
                        current_url: _currentUrlGuess(),
                        limit: 15,
                    }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    throw new Error(parseApiDetail(data) || "Không tìm được bài liên quan.");
                }
                _internalCandidates = Array.isArray(data.items) ? data.items : [];
                renderInternalCandidates(_internalCandidates);
                saveFormState();
                const panel = byId("internalLinkPanel");
                if (panel) {
                    try { panel.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) {}
                }
                if (_internalCandidates.length) {
                    const msg = `Tìm thấy ${_internalCandidates.length} bài — anchor = từ khóa chính bài đích (sửa từng ô nếu cần).`;
                    setHint("content", msg);
                    setHint("internal-links", msg);
                } else {
                    const apiHint = String(data.hint || "").trim();
                    const msg = apiHint || (
                        `Không có bài phù hợp (đã quét ${Number(data.wp_posts_fetched) || 0} URL). `
                        + "Thử nhập từ khóa chính, thêm H2 trong content, hoặc kiểm tra WP REST API công khai."
                    );
                    setHint("content", msg);
                    setHint("internal-links", msg);
                }
            } catch (e) {
                const errMsg = String((e && e.message) || e);
                setHint("content", errMsg);
                setHint("internal-links", errMsg);
            } finally {
                btnFindInternalLinks.textContent = oldText;
                btnFindInternalLinks.disabled = false;
            }
        });
    }
    const restoreInternalCandidatesFromPending = () => {
        try {
            const pending = _pendingInternalCandidatesRestore;
            if (!pending || !Array.isArray(pending.items) || !pending.items.length) return;
            _pendingInternalCandidatesRestore = null;
            _internalCandidates = pending.items;
            renderInternalCandidates(_internalCandidates);
            const anchors = pending.anchors && typeof pending.anchors === "object" ? pending.anchors : {};
            Object.keys(anchors).forEach((idx) => {
                const inp = document.querySelector(`input.internal-link-anchor-input[data-idx="${idx}"]`);
                if (inp) inp.value = String(anchors[idx] ?? "");
            });
        } catch (e) {
            _pendingInternalCandidatesRestore = null;
            console.error("[content-ai] restore internal candidates failed", e);
        }
    };
    window.setTimeout(() => restoreInternalCandidatesFromPending(), 0);
    if (internalLinkCandidates && !internalLinkCandidates.dataset.persistBound) {
        internalLinkCandidates.dataset.persistBound = "1";
        internalLinkCandidates.addEventListener("input", (e) => {
            if (e.target && e.target.classList && e.target.classList.contains("internal-link-anchor-input")) {
                scheduleSaveFormState();
            }
        });
        internalLinkCandidates.addEventListener("change", (e) => {
            if (e.target && e.target.classList && e.target.classList.contains("internal-link-cb")) {
                scheduleSaveFormState();
            }
        });
    }
    const collectWpInternalChecked = () =>
        Array.from(document.querySelectorAll(".internal-link-cb:checked"))
            .map((el) => Number(el.getAttribute("data-idx")))
            .filter((n) => Number.isFinite(n) && _internalCandidates[n])
            .map((n) => {
                const inp = document.querySelector(`input.internal-link-anchor-input[data-idx="${n}"]`);
                const anchor = inp ? String(inp.value || "").trim() : "";
                return {
                    title: _internalCandidates[n].title,
                    link: _internalCandidates[n].link,
                    anchor_text: anchor,
                };
            });

    const getInternalRowPost = (idx) => {
        const n = Number(idx);
        if (!Number.isFinite(n) || !_internalCandidates[n]) return null;
        const inp = document.querySelector(`input.internal-link-anchor-input[data-idx="${n}"]`);
        const anchor = inp ? String(inp.value || "").trim() : "";
        const it = _internalCandidates[n];
        const title = String(it.title || "").trim();
        const link = String(it.link || "").trim();
        if (!link) return null;
        return {
            title: title || anchor,
            link,
            anchor_text: anchor || title,
        };
    };

    const getInternalRowCircle = (idx) => {
        const tr = document.querySelector(`tr[data-idx="${idx}"]`);
        if (!tr) return null;
        return tr.querySelector(".il-row-circle");
    };

    const setInternalRowCircleState = (idx, state) => {
        const tr = document.querySelector(`tr[data-idx="${idx}"]`);
        const circle = getInternalRowCircle(idx);
        if (!tr || !circle) return;
        circle.classList.remove("il-loading", "il-done", "il-error");
        circle.innerHTML = "";
        if (state === "loading") {
            circle.classList.add("il-loading");
            const sp = document.createElement("span");
            sp.className = "il-row-spinner";
            sp.setAttribute("aria-label", "Đang chèn link");
            circle.appendChild(sp);
            return;
        }
        if (state === "done") {
            tr.classList.add("il-row-applied");
            circle.classList.add("il-done");
            circle.textContent = "✓";
            circle.title = "Đã chèn internal link";
            const cb = tr.querySelector(".internal-link-cb");
            if (cb) cb.disabled = true;
            return;
        }
        if (state === "error") {
            circle.classList.add("il-error");
            circle.title = "Không chèn được — thử lại";
            return;
        }
        circle.title = "Chờ chèn link";
    };

    const getSelectedInternalRowIndices = () =>
        Array.from(document.querySelectorAll(".internal-link-cb:checked"))
            .map((el) => Number(el.getAttribute("data-idx")))
            .filter((n) => Number.isFinite(n) && _internalCandidates[n]);

    let _thamKhaoModalResolver = null;
    const closeThamKhaoAppendModal = () => {
        const modal = byId("thamKhaoAppendModal");
        if (modal) {
            modal.classList.remove("open");
            modal.setAttribute("aria-hidden", "true");
        }
        if (_thamKhaoModalResolver) {
            _thamKhaoModalResolver(null);
            _thamKhaoModalResolver = null;
        }
    };
    const showThamKhaoAppendModal = (offers) => {
        const list = Array.isArray(offers) ? offers : [];
        if (!list.length) return Promise.resolve(null);
        const modal = byId("thamKhaoAppendModal");
        const box = byId("thamKhaoAppendList");
        if (!modal || !box) return Promise.resolve(null);
        box.innerHTML = "";
        list.forEach((o, i) => {
            const row = document.createElement("label");
            row.className = "tham-khao-item";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = true;
            cb.setAttribute("data-url", String(o.target_url || ""));
            cb.setAttribute("data-idx", String(o.row_idx != null ? o.row_idx : i));
            const prev = document.createElement("div");
            prev.className = "tham-khao-preview";
            const anchor = String(o.anchor_text || "").trim();
            const url = String(o.target_url || "").trim();
            prev.innerHTML = `Tham khảo thêm: <a href="${url.replace(/"/g, "&quot;")}" target="_blank" rel="noopener">${anchor.replace(/</g, "&lt;")}</a>.`;
            row.appendChild(cb);
            row.appendChild(prev);
            box.appendChild(row);
        });
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
        return new Promise((resolve) => {
            _thamKhaoModalResolver = resolve;
        });
    };
    const bindThamKhaoModalOnce = () => {
        const closeBtn = byId("thamKhaoAppendClose");
        const cancelBtn = byId("thamKhaoAppendCancel");
        const confirmBtn = byId("thamKhaoAppendConfirm");
        const modal = byId("thamKhaoAppendModal");
        if (closeBtn && !closeBtn.dataset.bound) {
            closeBtn.dataset.bound = "1";
            closeBtn.addEventListener("click", (e) => { e.preventDefault(); closeThamKhaoAppendModal(); });
        }
        if (cancelBtn && !cancelBtn.dataset.bound) {
            cancelBtn.dataset.bound = "1";
            cancelBtn.addEventListener("click", (e) => { e.preventDefault(); closeThamKhaoAppendModal(); });
        }
        if (modal && !modal.dataset.bound) {
            modal.dataset.bound = "1";
            modal.addEventListener("click", (e) => {
                if (e.target === modal) closeThamKhaoAppendModal();
            });
        }
        if (confirmBtn && !confirmBtn.dataset.bound) {
            confirmBtn.dataset.bound = "1";
            confirmBtn.addEventListener("click", async (e) => {
                e.preventDefault();
                const box = byId("thamKhaoAppendList");
                const selected = [];
                if (box) {
                    box.querySelectorAll('input[type="checkbox"]:checked').forEach((cb) => {
                        selected.push({
                            target_url: cb.getAttribute("data-url") || "",
                            row_idx: parseInt(cb.getAttribute("data-idx"), 10),
                        });
                    });
                }
                const modalEl = byId("thamKhaoAppendModal");
                if (modalEl) {
                    modalEl.classList.remove("open");
                    modalEl.setAttribute("aria-hidden", "true");
                }
                if (_thamKhaoModalResolver) {
                    _thamKhaoModalResolver(selected);
                    _thamKhaoModalResolver = null;
                }
            });
        }
    };
    bindThamKhaoModalOnce();

    const showIlVerification = (verification) => {
        const box = byId("ilVerifyHint");
        if (!box) return;
        const v = verification && typeof verification === "object" ? verification : null;
        if (!v || v.ok) {
            box.style.display = "none";
            box.textContent = "";
            return;
        }
        const issues = Array.isArray(v.issues) ? v.issues : [];
        box.style.display = "block";
        box.textContent = issues.length
            ? `Verify sau chèn: ${issues.join(" · ")}`
            : "Verify: có cảnh báo — kiểm tra lại HTML.";
    };

    const applyInternalLinksApi = async (selectedPosts, extra = {}) => {
        const site = resolveTargetWebsite([]);
        const res = await apiFetch(`/content-ai/wp-internal-links/apply?ts=${Date.now()}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                content_html: getContentValue().trim(),
                target_website: site,
                selected_posts: selectedPosts,
                custom_links: [],
                current_url: _currentUrlGuess(),
                article_primary_keyword: byId("primaryKeyword")?.value?.trim() || "",
                article_secondary_keywords: byId("secondaryKeywords")?.value?.trim() || "",
                use_llm_rewrite: !!getInternalLinkUseLlm(),
                apply_mode: extra.apply_mode || "full",
                append_lead: "Tham khảo thêm:",
                confirmed_append_urls: extra.confirmed_append_urls || null,
            }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(parseApiDetail(data) || "Đi internal link thất bại.");
        }
        return data;
    };

    const applyConfirmedThamKhao = async (confirmedRows) => {
        const posts = (confirmedRows || []).map((r) => {
            const idx = Number(r.row_idx);
            if (Number.isFinite(idx)) return getInternalRowPost(idx);
            const url = String(r.target_url || "");
            const found = _internalCandidates.findIndex((c) => String(c.link || "") === url);
            if (found >= 0) return getInternalRowPost(found);
            return null;
        }).filter(Boolean);
        if (!posts.length) return { ok: false };
        const data = await applyInternalLinksApi(posts, {
            apply_mode: "append_only",
            confirmed_append_urls: posts.map((p) => p.link),
        });
        const outHtml = String(data.content_html || "").trim();
        if (outHtml) {
            setContentValue(outHtml);
            refreshPreview();
            saveFormState();
        }
        return { ok: true, data };
    };

    const applyInternalLinkForRow = async (idx) => {
        const tr = document.querySelector(`tr[data-idx="${idx}"]`);
        if (tr && tr.classList.contains("il-row-applied")) {
            return { ok: true, skipped: true };
        }
        const cur = getContentValue().trim();
        if (!cur) {
            return { ok: false, message: "Chưa có content để đi internal link." };
        }
        const post = getInternalRowPost(idx);
        if (!post || !post.link) {
            return { ok: false, message: "Thiếu URL bài đích hoặc anchor — kiểm tra lại dòng này." };
        }
        if (!post.anchor_text) {
            return { ok: false, message: "Nhập anchor text trước khi đi link." };
        }
        const site = resolveTargetWebsite([]);
        if (!site) {
            return { ok: false, message: "Nhập Target website để đi internal link." };
        }
        setInternalRowCircleState(idx, "loading");
        try {
            const data = await applyInternalLinksApi([post]);
            const outHtml = String(data.content_html || "").trim();
            if (outHtml) {
                setContentValue(outHtml);
                refreshPreview();
                saveFormState();
            }
            _lastScreamingFrogTsv = String(data.screaming_frog_tsv || _lastScreamingFrogTsv || "");
            if (btnDownloadScreamingFrog) btnDownloadScreamingFrog.disabled = !_lastScreamingFrogTsv;
            const ins = Number(data.inserted_links || 0);
            const results = Array.isArray(data.link_results) ? data.link_results : [];
            const rowRes = results[0];
            const pending = (data.pending_append_offers || []).map((p) => ({
                ...p,
                row_idx: idx,
            }));
            if (ins > 0 || (rowRes && rowRes.status === "inserted")) {
                setInternalRowCircleState(idx, "done");
                showIlVerification(data.verification);
                return { ok: true, anchor: post.anchor_text, pending: [] };
            }
            if (pending.length || (rowRes && rowRes.status === "needs_confirm")) {
                setInternalRowCircleState(idx, "idle");
                return { ok: false, needsConfirm: true, pending, message: rowRes?.reason || "" };
            }
            setInternalRowCircleState(idx, "error");
            const reason = rowRes && rowRes.reason
                ? String(rowRes.reason)
                : "Không chèn được (đã có link hoặc không tìm được vị trí).";
            return { ok: false, message: reason, pending: [] };
        } catch (e) {
            setInternalRowCircleState(idx, "error");
            return { ok: false, message: String((e && e.message) || e), pending: [] };
        }
    };

    const runInternalLinksBulkFromTable = async (triggerBtn) => {
        const indices = getSelectedInternalRowIndices().filter((idx) => {
            const tr = document.querySelector(`tr[data-idx="${idx}"]`);
            return tr && !tr.classList.contains("il-row-applied");
        });
        if (!indices.length) {
            setHint("content", "Tick chọn ít nhất một dòng chưa chèn link.");
            setHint("internal-links", "Tick chọn bài cần đi link.");
            return;
        }
        const btn = triggerBtn || document.querySelector(".btn-il-bulk-apply");
        const oldLabel = btn ? btn.textContent : "";
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Đang chèn…";
        }
        setHint("internal-links", `Đang chèn ${indices.length} internal link lần lượt…`);
        let okCount = 0;
        let failCount = 0;
        const allPending = [];
        for (let i = 0; i < indices.length; i += 1) {
            const idx = indices[i];
            setHint(
                "internal-links",
                `Đang chèn link (${i + 1}/${indices.length})…`,
            );
            const result = await applyInternalLinkForRow(idx);
            if (result && result.skipped) {
                okCount += 1;
            } else if (result && result.ok) {
                okCount += 1;
            } else if (result && result.needsConfirm && result.pending && result.pending.length) {
                allPending.push(...result.pending);
            } else {
                failCount += 1;
                if (result && result.message) {
                    setHint("content", result.message);
                }
            }
        }
        if (allPending.length && !getInternalLinkUseLlm()) {
            const dedup = [];
            const seenUrl = new Set();
            allPending.forEach((p) => {
                const u = String(p.target_url || "");
                if (!u || seenUrl.has(u)) return;
                seenUrl.add(u);
                dedup.push(p);
            });
            setHint("internal-links", "Một số link cần xác nhận dạng «Tham khảo thêm»…");
            const confirmed = await showThamKhaoAppendModal(dedup);
            if (confirmed && confirmed.length) {
                for (const c of confirmed) {
                    const ridx = Number(c.row_idx);
                    if (Number.isFinite(ridx)) setInternalRowCircleState(ridx, "loading");
                }
                try {
                    const appendData = await applyConfirmedThamKhao(confirmed);
                    if (appendData.ok) {
                        confirmed.forEach((c) => {
                            const ridx = Number(c.row_idx);
                            if (Number.isFinite(ridx)) setInternalRowCircleState(ridx, "done");
                        });
                        okCount += confirmed.length;
                    }
                } catch (err) {
                    setHint("content", String(err.message || err));
                    failCount += confirmed.length;
                }
            } else {
                failCount += dedup.length;
            }
        }
        const summary =
            failCount > 0
                ? `Xong: ${okCount} link đã chèn, ${failCount} dòng lỗi/bỏ qua.`
                : `Đã chèn ${okCount} internal link vào bài.`;
        setHint("content", summary);
        setHint("internal-links", summary);
        if (btn) {
            btn.disabled = false;
            btn.textContent = oldLabel || "Đi link";
        }
    };

    const resolveTargetWebsite = (customLinks) => {
        let site = normalizeTargetBase(String(byId("targetWebsite")?.value || "").trim())
            || String(byId("targetWebsite")?.value || "").trim();
        if (site) return site;
        const first = (customLinks || []).find((x) => x.target_url);
        if (!first) return "";
        try {
            return new URL(String(first.target_url)).origin;
        } catch (_) {
            return "";
        }
    };

    const runApplyInternalLinks = async ({ fromCustomPanel = false, triggerBtn = null } = {}) => {
        const cur = getContentValue().trim();
        if (!cur) {
            setHint("content", "Chưa có content để đi internal link.");
            if (fromCustomPanel && hintCustomLinkApply) {
                hintCustomLinkApply.textContent = "Chưa có nội dung bài trong editor.";
            }
            return;
        }
        const allCustomRows = collectCheckedCustomLinks();
        const customLinks = getValidCustomLinksForApply();
        const customInvalid = allCustomRows.filter(
            (x) => (x.target_url && !x.anchor_text) || (!x.target_url && x.anchor_text)
        );
        if (customInvalid.length) {
            const msg = "Custom link: mỗi dòng đã tick cần đủ URL và anchor (hoặc bỏ tick dòng thiếu).";
            setHint("content", msg);
            if (fromCustomPanel && hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        const checked = collectWpInternalChecked();
        if (fromCustomPanel && !customLinks.length) {
            const msg =
                "Chưa có custom link hợp lệ: tick chọn dòng, nhập URL (https://...) và anchor text, rồi bấm lại «Đi Internal link».";
            setHint("content", msg);
            if (hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        if (!checked.length && !customLinks.length) {
            const msg = fromCustomPanel
                ? "Thêm custom link (URL + anchor) hoặc chọn bài ở bảng WordPress phía trên."
                : "Chọn bài WordPress và/hoặc custom link (URL + anchor) để đi internal link.";
            setHint("content", msg);
            if (fromCustomPanel && hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        const site = resolveTargetWebsite(customLinks);
        if (!site) {
            const msg = "Nhập Target website hoặc URL đầy đủ (https://...) trong custom link.";
            setHint("content", msg);
            if (fromCustomPanel && hintCustomLinkApply) hintCustomLinkApply.textContent = msg;
            return;
        }
        const useLlm = customLinkUseLlm ? !!customLinkUseLlm.checked : false;
        const buttons = [triggerBtn, btnApplyInternalLinks, btnApplyCustomInternalLinks].filter(Boolean);
        const oldLabels = buttons.map((b) => b.textContent);
        buttons.forEach((b) => {
            b.disabled = true;
            if (b === btnApplyCustomInternalLinks) b.textContent = "Đang viết lại & chèn link...";
            else if (b === btnApplyInternalLinks) b.textContent = "Đang đi link...";
        });
        if (previewLoading) {
            previewLoading.classList.add("show");
            if (previewLoadingText) {
                previewLoadingText.textContent = fromCustomPanel
                    ? "Đang chèn custom internal link (rule-based, tối thiểu thay đổi)..."
                    : "Đang chèn internal link (giữ nguyên bài, thêm đoạn ngắn nếu cần)...";
            }
            if (previewLoadingFill) previewLoadingFill.style.width = "35%";
            if (previewLoadingPct) previewLoadingPct.textContent = "35%";
        }
        if (hintCustomLinkApply && fromCustomPanel) {
            hintCustomLinkApply.textContent = `Đang chèn ${customLinks.length} custom link — LLM có thể mất 30–90 giây...`;
        }
        try {
            const res = await fetch(`/content-ai/wp-internal-links/apply?ts=${Date.now()}`, {
                method: "POST",
                headers: authJsonHeaders(),
                credentials: "same-origin",
                body: JSON.stringify({
                    content_html: cur,
                    target_website: site,
                    selected_posts: checked,
                    custom_links: customLinks,
                    current_url: _currentUrlGuess(),
                    article_primary_keyword: byId("primaryKeyword")?.value?.trim() || "",
                    article_secondary_keywords: byId("secondaryKeywords")?.value?.trim() || "",
                    use_llm_rewrite: useLlm,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Đi internal link thất bại.");
            const outHtml = String(data.content_html || "").trim();
            if (!outHtml) throw new Error("Không nhận được nội dung sau khi đi link.");
            setContentValue(outHtml);
            refreshPreview();
            saveFormState();
            _lastScreamingFrogTsv = String(data.screaming_frog_tsv || "");
            if (btnDownloadScreamingFrog) btnDownloadScreamingFrog.disabled = !_lastScreamingFrogTsv;
            renderInternalApplyResults(data.link_results);
            showIlVerification(data.verification);
            const via = data.used_llm_rewrite ? "rule + LLM tối thiểu" : "rule-based (không rewrite cả bài)";
            const ins = Number(data.inserted_links || 0);
            const skipped = (Array.isArray(data.link_results) ? data.link_results : []).filter((r) => r.status === "skipped").length;
            let msgHint = fromCustomPanel
                ? `Custom link: đã chèn ${ins} link — ${via}.`
                : `Đã chèn ${ins} internal link — ${via}.`;
            if (customLinks.length) msgHint += ` ${customLinks.length} custom.`;
            if (skipped) msgHint += ` ${skipped} bỏ qua — xem bảng bên dưới.`;
            setHint("content", msgHint);
            if (hintCustomLinkApply) {
                hintCustomLinkApply.textContent = skipped
                    ? `Xong: ${ins} chèn, ${skipped} bỏ qua.`
                    : `Xong: đã chèn ${ins} custom internal link vào bài.`;
            }
            if (previewLoadingFill) previewLoadingFill.style.width = "100%";
            if (previewLoadingPct) previewLoadingPct.textContent = "100%";
        } catch (e) {
            const errMsg = String((e && e.message) || e);
            setHint("content", errMsg);
            if (hintCustomLinkApply) hintCustomLinkApply.textContent = errMsg.slice(0, 120);
        } finally {
            buttons.forEach((b, i) => {
                b.disabled = false;
                if (oldLabels[i]) b.textContent = oldLabels[i];
            });
            if (previewLoading) previewLoading.classList.remove("show");
        }
    };

    if (btnApplyInternalLinks) {
        btnApplyInternalLinks.addEventListener("click", () => runApplyInternalLinks({ triggerBtn: btnApplyInternalLinks }));
    }
    if (btnApplyCustomInternalLinks) {
        btnApplyCustomInternalLinks.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            runApplyInternalLinks({ fromCustomPanel: true, triggerBtn: btnApplyCustomInternalLinks });
        });
    }
    if (btnDownloadScreamingFrog) {
        btnDownloadScreamingFrog.addEventListener("click", () => {
            if (!_lastScreamingFrogTsv) return;
            const blob = new Blob([_lastScreamingFrogTsv], { type: "text/tab-separated-values;charset=utf-8;" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "screaming-frog-internal-links.tsv";
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        });
    }

    // keep preview reasonably fresh without spamming
    let _previewTimer = null;
    const schedulePreview = () => {
        if (_previewTimer) clearTimeout(_previewTimer);
        _previewTimer = setTimeout(refreshPreview, 250);
    };
    document.querySelectorAll("input, textarea, select").forEach((el) => {
        if (el.id === "output") return;
        el.addEventListener("input", schedulePreview);
        el.addEventListener("change", schedulePreview);
        if (el.id === "title" || el.id === "meta" || el.id === "primaryKeyword" || el.id === "content") {
            el.addEventListener("input", schedulePublishChecklist);
            el.addEventListener("change", schedulePublishChecklist);
        }
    });
    const contentTa = byId("content");
    if (contentTa) {
        contentTa.addEventListener("input", () => {
            refreshPreview();
            syncPreviewFallback();
        });
    }
    const contentEditable = byId("contentRender");
    if (contentEditable) {
        contentEditable.addEventListener("mouseover", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            const a = target.closest("a");
            if (a && contentEditable.contains(a)) {
                showLinkToolsFor(a);
            }
        });
        contentEditable.addEventListener("mousemove", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            const a = target.closest("a");
            if (!a || !contentEditable.contains(a)) {
                scheduleHideLinkTools();
            } else {
                if (linkToolsHideTimer) {
                    clearTimeout(linkToolsHideTimer);
                    linkToolsHideTimer = null;
                }
            }
        });
        contentEditable.addEventListener("mouseleave", () => {
            scheduleHideLinkTools(180);
        });
        contentEditable.addEventListener("focus", rememberEditorSelection);
        contentEditable.addEventListener("keyup", rememberEditorSelection);
        contentEditable.addEventListener("mouseup", rememberEditorSelection);
        contentEditable.addEventListener("input", rememberEditorSelection);
        contentEditable.addEventListener("mousedown", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            if (!target.closest(".img-action-delete")) return;
            e.preventDefault();
            e.stopPropagation();
            const fig = target.closest("figure.editor-image");
            deleteFigureElement(fig);
        });
        contentEditable.addEventListener("click", (e) => {
            const target = e.target;
            if (target && target instanceof Element) {
                if (target.closest(".img-action-delete")) return;
                const img = target.closest("img");
                if (img) {
                    selectEditorImage(img);
                    return;
                }
            }
            clearSelectedEditorFigure();
        });
        contentEditable.addEventListener("keydown", (e) => {
            if (!selectedEditorFigure) return;
            if (e.key === "Delete" || e.key === "Backspace") {
                e.preventDefault();
                deleteSelectedEditorFigure();
            }
        });
        contentEditable.addEventListener("input", () => {
            const ta = byId("content");
            if (ta) ta.value = String(contentEditable.innerHTML || "");
            schedulePreview();
            schedulePublishChecklist();
            scheduleSaveFormState();
        });
        contentEditable.addEventListener("keyup", () => {
            schedulePreview();
        });
        contentEditable.addEventListener("paste", () => {
            window.setTimeout(schedulePreview, 0);
        });
        contentEditable.addEventListener("click", syncBlockFormatBySelection);
        contentEditable.addEventListener("keyup", syncBlockFormatBySelection);
        contentEditable.addEventListener("mouseup", syncBlockFormatBySelection);
    }
    document.addEventListener("selectionchange", () => {
        syncBlockFormatBySelection();
        rememberEditorSelection();
    });
    refreshEditorModeUi();

    btnResetForm.addEventListener("click", async () => {
        const view = String(_contentAiMainView || "single");
        if (view === "projects") {
            if (msg) {
                msg.textContent =
                    "Chuyển sang tab «Viết 1 bài» hoặc «Viết bài theo từ khóa» rồi bấm Làm mới để xóa nhập liệu tab đó.";
            }
            return;
        }
        const isBulk = view === "bulk";
        const tabLabel = isBulk ? "Viết bài theo từ khóa" : "Viết 1 bài";
        const ok = window.confirm(
            isBulk
                ? "Bạn có chắc muốn làm mới tab «Viết bài theo từ khóa»? Danh sách từ khóa và form bulk (kể cả bản nháp trên trình duyệt) sẽ bị xóa. Tab «Viết 1 bài» và dự án trên server không đổi."
                : "Bạn có chắc muốn làm mới tab «Viết 1 bài»? Toàn bộ ô nhập và bản nháp trên trình duyệt của tab này sẽ bị xóa. Tab «Viết bài theo từ khóa» và dự án trên server không đổi."
        );
        if (!ok) return;
        if (isBulk) {
            resetBulkWriteForm();
            if (msg) {
                msg.textContent =
                    "Đã làm mới tab «Viết bài theo từ khóa». Tab «Viết 1 bài» và dự án trên server giữ nguyên.";
            }
        } else {
            resetContentAiSingleForm();
            if (msg) {
                msg.textContent =
                    "Đã làm mới tab «Viết 1 bài». Tab «Viết bài theo từ khóa» và dự án trên server giữ nguyên.";
            }
            await refreshProjects(true);
        }
    });
})();
