(() => {
    const byId = (id) => document.getElementById(id);
    const readCookieToken = () => {
        const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    };
    const getAuthToken = () => {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken();
        }
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
        if (typeof window.DigiSeoClearAuthToken === "function") {
            window.DigiSeoClearAuthToken();
            return;
        }
        try { sessionStorage.removeItem("seo_token"); } catch (_) {}
        try { localStorage.removeItem("seo_token"); } catch (_) {}
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
        const shouldClear =
            typeof window.DigiSeoIsTokenInvalid401 === "function"
                ? window.DigiSeoIsTokenInvalid401(data)
                : true;
        if (!shouldClear) return false;
        // Prefer refresh over hard logout — access JWT expires every ~20 minutes.
        if (typeof window.DigiSeoRefreshSessionFromCookie === "function") {
            window.DigiSeoRefreshSessionFromCookie().then(function (tok) {
                if (!tok) {
                    clearAuthToken();
                    if (typeof window.DigiSeoOpenLoginModal === "function") {
                        window.DigiSeoOpenLoginModal();
                    }
                }
            });
            return true;
        }
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
        if (typeof window.DigiSeoAuthFetch === "function") {
            return window.DigiSeoAuthFetch(url, opts);
        }
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
            "content_ai_bulk_last_job_id_v1",
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

    const stripImageAuthTokensFromHtml = (html) =>
        String(html || "").replace(
            /(\/api\/user-files\/[^"'\s>]+)[?&]token=[^"'\s&>]+/gi,
            "$1",
        );

    const withImageAuthTokensForHtml = (html) => {
        const t = getAuthToken();
        if (!t) return String(html || "");
        return String(html || "").replace(
            /src=(["'])(\/api\/user-files\/[^"']+)\1/gi,
            (full, quote, src) => {
                if (/[?&]token=/.test(src)) return full;
                const sep = src.includes("?") ? "&" : "?";
                return `src=${quote}${src}${sep}token=${encodeURIComponent(t)}${quote}`;
            },
        );
    };

    const isUsableImageSrcClient = (src) => {
        const s = String(src || "").trim();
        if (!s) return false;
        if (/^(#|about:blank|javascript:|data:image\/svg)/i.test(s)) return false;
        if (/^https?:\/\//i.test(s)) return true;
        if (s.startsWith("/static/") || s.startsWith("/api/user-files/")) return true;
        if (/^data:image\/(jpeg|jpg|png|webp|gif)/i.test(s)) return true;
        if (/\s/.test(s) && !/\.(jpe?g|png|webp|gif)(\?|#|$)/i.test(s)) return false;
        return false;
    };

    const attachContentImageFallbacks = (root) => {
        if (!root || !root.querySelectorAll) return;
        root.querySelectorAll("img").forEach((img) => {
            const src = String(img.getAttribute("src") || "").trim();
            if (!isUsableImageSrcClient(src)) {
                const fig = img.closest("figure");
                const msg = document.createElement("p");
                msg.className = "content-ai-image-fallback";
                msg.textContent = "Ảnh chưa tải được";
                if (fig) fig.replaceWith(msg);
                else img.replaceWith(msg);
                return;
            }
            if (!img.getAttribute("loading")) img.setAttribute("loading", "lazy");
            if (!img.getAttribute("alt")) img.setAttribute("alt", "Ảnh minh họa");
            img.style.maxWidth = "100%";
            img.style.height = "auto";
            img.onerror = function onImgErr() {
                const figEl = img.closest("figure");
                const note = document.createElement("p");
                note.className = "content-ai-image-fallback";
                note.textContent = "Ảnh chưa tải được";
                if (figEl) figEl.replaceWith(note);
                else img.replaceWith(note);
            };
        });
    };

    try {
        const bootToken = getAuthToken();
        if (bootToken && typeof window.DigiSeoSetAuthToken === "function") {
            window.DigiSeoSetAuthToken(bootToken);
        }
    } catch (_) {}
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
        const minPx = 120;
        const grow = () => {
            el.style.height = "auto";
            el.style.height = `${Math.max(minPx, el.scrollHeight + 2)}px`;
        };
        grow();
        requestAnimationFrame(grow);
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
        const pubSel = byId("singleWpCategoryIdPublish");
        const active = pubSel && document.activeElement === pubSel ? pubSel : sel;
        const v = String((active && active.value) || (sel && sel.value) || "").trim();
        if (sel && active === pubSel) sel.value = v;
        if (pubSel && active === sel) pubSel.value = v;
        const n = parseInt(v, 10);
        _draftWpCategoryIds = !Number.isNaN(n) && n > 0 ? [n] : null;
    };
    const fillSingleWpCategorySelect = (savedId) => {
        const sel = byId("singleWpCategoryId");
        const pubSel = byId("singleWpCategoryIdPublish");
        const site =
            String(byId("wpUrl")?.value || "").trim() ||
            String(byId("targetWebsite")?.value || "").trim();
        const sk = _getWpCategoriesSiteKey(site);
        let cached = sk ? _bulkWpCategoriesBySiteKey[sk] : null;
        if ((!cached || !cached.length) && typeof _hydrateWpCategoriesFromCache === "function") {
            const row = _hydrateWpCategoriesFromCache(sk, site);
            cached = row && row.items;
        }
        if (sel) fillBulkCategorySelectEl(sel, cached || [], savedId);
        if (pubSel) fillBulkCategorySelectEl(pubSel, cached || [], savedId);
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
        if (!el) return;
        const msg = text || "";
        el.textContent = msg;
        // #hint-google-images stays hidden unless we have an active web-image message
        if (field === "google-images") {
            if (String(msg).trim()) el.removeAttribute("hidden");
            else el.setAttribute("hidden", "");
        }
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
    const updateContentStatsFromHtml = (html) => {
        const contentHtml = html != null ? String(html) : String(getContentValue() || "");
        const text = _stripText(contentHtml);
        const words = _countWords(text);
        const chars = text.length;
        const sentences = _countSentences(text);
        const paragraphs = _countParagraphs(contentHtml);
        const pages = words ? (words / 260) : 0;
        if (statWords) statWords.textContent = String(words);
        if (statChars) statChars.textContent = String(chars);
        if (statSentences) statSentences.textContent = String(sentences);
        if (statParagraphs) statParagraphs.textContent = String(paragraphs);
        if (statPages) statPages.textContent = pages ? pages.toFixed(2) : "0";
        const caEdW = byId("caEditorWordCount");
        const caEdC = byId("caEditorCharCount");
        const caStickyW = byId("caStickyWordCount");
        if (caEdW) caEdW.textContent = String(words);
        if (caEdC) caEdC.textContent = String(chars);
        if (caStickyW) caStickyW.textContent = String(words);
        return { words, chars, sentences, paragraphs, pages };
    };
    const refreshPreview = () => {
        const contentHtml = getContentValue();
        updateContentStatsFromHtml(contentHtml);
        const element = byId("contentRender");
        const content = withImageAuthTokensForHtml(String(contentHtml || ""));
        const isEditing = element && document.activeElement === element;
        // In contenteditable mode, do not rewrite editor DOM while focused
        // to keep caret/range stable for image insertion at cursor position.
        if (element && !isEditing) {
            element.innerHTML = content;
            attachContentImageFallbacks(element);
        }
        const ta = byId("content");
        if (ta) ta.value = String(contentHtml || "");
    };

    const CONTENT_AI_LLM_UNAVAILABLE_CODE = "CONTENT_AI_LLM_UNAVAILABLE";
    const CONTENT_AI_LLM_UNAVAILABLE_MESSAGE =
        "Hệ thống đang nâng cấp tính năng, mong bạn thông cảm chúng tôi sẽ quay trở lại sớm nhất !";

    const extractContentAiApiError = (data) => {
        const detail = data && data.detail;
        if (detail && typeof detail === "object" && detail.code === CONTENT_AI_LLM_UNAVAILABLE_CODE) {
            return detail.message || CONTENT_AI_LLM_UNAVAILABLE_MESSAGE;
        }
        if (data && data.code === CONTENT_AI_LLM_UNAVAILABLE_CODE) {
            return data.message || CONTENT_AI_LLM_UNAVAILABLE_MESSAGE;
        }
        if (detail && typeof detail === "object" && detail.message) return String(detail.message);
        if (typeof detail === "string") return detail;
        if (data && data.message) return String(data.message);
        return "";
    };

    const isContentAiLlmUnavailable = (data, message) => {
        const detail = data && data.detail;
        if (detail && typeof detail === "object" && detail.code === CONTENT_AI_LLM_UNAVAILABLE_CODE) {
            return true;
        }
        if (data && data.code === CONTENT_AI_LLM_UNAVAILABLE_CODE) {
            return true;
        }
        const msg = String(message || "").trim();
        return msg === CONTENT_AI_LLM_UNAVAILABLE_MESSAGE;
    };

    const showContentAiLlmUnavailableIfNeeded = (data, message) => {
        if (!isContentAiLlmUnavailable(data, message)) return false;
        const text = String(
            message || extractContentAiApiError(data || {}) || CONTENT_AI_LLM_UNAVAILABLE_MESSAGE
        );
        showContentAiLlmUnavailable(text);
        return true;
    };

    const portalContentAiLlmUnavailableOverlay = () => {
        const overlay = byId("caLlmUnavailableOverlay");
        if (!overlay || !document.body) return;
        if (overlay.parentElement !== document.body) {
            document.body.appendChild(overlay);
        } else {
            document.body.appendChild(overlay);
        }
    };

    const hideContentAiLlmUnavailableModal = () => {
        const overlay = byId("caLlmUnavailableOverlay");
        if (!overlay) return;
        overlay.classList.remove("open");
        overlay.setAttribute("aria-hidden", "true");
        overlay.setAttribute("hidden", "");
        overlay.hidden = true;
        document.body.classList.remove("ca-llm-unavailable-open");
    };

    const showContentAiLlmUnavailable = (message) => {
        const text = String(message || CONTENT_AI_LLM_UNAVAILABLE_MESSAGE);
        portalContentAiLlmUnavailableOverlay();
        const overlay = byId("caLlmUnavailableOverlay");
        const msgEl = byId("caLlmUnavailableMessage");
        const closeBtn = byId("btnCaLlmUnavailableClose");
        const backdrop = byId("caLlmUnavailableBackdrop");
        if (overlay && msgEl) {
            msgEl.textContent = text;
            overlay.removeAttribute("hidden");
            overlay.hidden = false;
            overlay.classList.add("open");
            overlay.setAttribute("aria-hidden", "false");
            document.body.classList.add("ca-llm-unavailable-open");
            if (closeBtn && !closeBtn.dataset.bound) {
                closeBtn.dataset.bound = "1";
                closeBtn.addEventListener("click", (e) => {
                    e.preventDefault();
                    hideContentAiLlmUnavailableModal();
                });
            }
            if (backdrop && !backdrop.dataset.bound) {
                backdrop.dataset.bound = "1";
                backdrop.addEventListener("click", () => hideContentAiLlmUnavailableModal());
            }
            if (!window.__caLlmUnavailableEscBound) {
                window.__caLlmUnavailableEscBound = true;
                document.addEventListener("keydown", (e) => {
                    if (e.key === "Escape") hideContentAiLlmUnavailableModal();
                });
            }
            try { closeBtn && closeBtn.focus(); } catch (_) {}
        }
        try {
            const hint = byId("msg");
            if (hint) hint.textContent = text;
        } catch (_) {}
    };

    window.ContentAiErrors = {
        CODE: CONTENT_AI_LLM_UNAVAILABLE_CODE,
        MESSAGE: CONTENT_AI_LLM_UNAVAILABLE_MESSAGE,
        extract: extractContentAiApiError,
        isLlmUnavailable: isContentAiLlmUnavailable,
        showIfLlmUnavailable: showContentAiLlmUnavailableIfNeeded,
        show: showContentAiLlmUnavailableIfNeeded,
        hide: hideContentAiLlmUnavailableModal,
    };

