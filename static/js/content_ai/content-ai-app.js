/* Auto-generated — run scripts/build_content_ai_js_bundle.py after editing split files */
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
        if (shouldClear) clearAuthToken();
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
        const cached = sk ? _bulkWpCategoriesBySiteKey[sk] : null;
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
        const caEdW = byId("caEditorWordCount");
        const caEdC = byId("caEditorCharCount");
        const caStickyW = byId("caStickyWordCount");
        if (caEdW) caEdW.textContent = String(words);
        if (caEdC) caEdC.textContent = String(chars);
        if (caStickyW) caStickyW.textContent = String(words);
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
    const setContentValue = (html) => {
        const v = stripImageAuthTokensFromHtml(decodeHtmlEntitiesDeep(String(html || "")));
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
        row.addEventListener("click", (e) => {
            const btn = e.target && e.target.closest(".wc-preset-btn");
            if (!btn) return;
            const preset = String(btn.dataset.wc || "");
            if (preset === "auto") {
                row.querySelectorAll(".wc-preset-btn").forEach((b) => b.classList.remove("active"));
                btn.classList.add("active");
                syncTargetWordCountInputUi();
                saveFormState();
                try { updateAutoInsertImagePreview(); } catch (_) {}
                return;
            }
            if (preset === "custom") {
                input.disabled = false;
                input.hidden = false;
                input.focus();
                syncWordCountPresetActive();
                return;
            }
            const n = parseInt(preset, 10);
            if (Number.isFinite(n)) input.value = String(n);
            syncWordCountPresetActive();
            saveFormState();
            try { updateAutoInsertImagePreview(); } catch (_) {}
        });
        input.addEventListener("input", () => {
            syncWordCountPresetActive();
            try { updateAutoInsertImagePreview(); } catch (_) {}
        });
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

        let res = await postSuggest(preferSync);
        let data = await res.json().catch(() => ({}));
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
                if (options.signal && options.signal.aborted) throw new Error("Đã hủy.");
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
    const _contentWriteSession = { controller: null, reader: null, progressTimer: null, active: false, contentVisible: false };
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
    const _stopContentWrite = () => {
        const s = _contentWriteSession;
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
        _stopContentWrite();
        const controller = new AbortController();
        _contentWriteSession.controller = controller;
        _contentWriteSession.active = true;
        _contentWriteSession.contentVisible = false;
        return controller.signal;
    };
    const _getContentWriteSignal = () => {
        const c = _contentWriteSession.controller;
        return c ? c.signal : null;
    };
    const _assertContentWriteActive = (signal) => {
        if (signal && signal.aborted) throw new DOMException("Aborted", "AbortError");
        if (!_contentWriteSession.active) throw new DOMException("Aborted", "AbortError");
    };
    const _raceAbort = (signal, promise) => {
        if (!signal) return promise;
        if (signal.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
        return new Promise((resolve, reject) => {
            const onAbort = () => reject(new DOMException("Aborted", "AbortError"));
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
                reject(new DOMException("Aborted", "AbortError"));
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
    const _hideContentWriteOverlay = () => {
        const ov = byId("caContentWriteOverlay");
        const stage = byId("caContentEditorStage");
        if (ov) {
            ov.hidden = true;
            ov.setAttribute("aria-hidden", "true");
        }
        if (stage) stage.classList.remove("is-writing");
        _contentWriteSession.contentVisible = true;
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
            _hideContentWriteOverlay();
        } else {
            _showContentWriteOverlay(label);
        }
    };
    const _hideEditorWriteBar = () => {
        if (caEditorWriteBar) caEditorWriteBar.hidden = true;
        _hideContentWriteOverlay();
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
    };
    const _sleepMs = (ms, signal) => new Promise((resolve, reject) => {
        if (signal && signal.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
        }
        const t = window.setTimeout(resolve, ms);
        if (signal) {
            signal.addEventListener("abort", () => {
                window.clearTimeout(t);
                reject(new DOMException("Aborted", "AbortError"));
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
    const _parseDeltaSseBuffer = (buffer, handlers) => {
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
                } else if (obj && obj.replace_html) {
                    if (handlers.onReplaceHtml) handlers.onReplaceHtml(String(obj.replace_html));
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
        // Prompt 2.4: SSE stream disabled on API — poll LLM worker job (same UX end-state).
        _caStreamLog("poll suggest job (stream detached)");
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
    const writeContentToEditor = async (ctx, options = {}) => {
        const signal = options.signal || _beginContentWriteSession();

        await confirmContentAiCredit("content", ctx);

        _clearEditorWriteError();
        _setCreateContentButtonsBusy(true);
        _showEditorWriteBar("Đang kiểm tra yêu cầu…");
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
                    onPing: () => { sawDelta = true; },
                    onDelta: (delta) => {
                        sawDelta = true;
                        _hideContentWriteOverlay();
                        _enqueueStreamDelta(delta, signal);
                        if (caEditorWriteBar) caEditorWriteBar.hidden = false;
                        if (caEditorWriteStatus) caEditorWriteStatus.textContent = "Đang viết nội dung…";
                    },
                    onReplaceHtml: async (html) => {
                        sawDelta = true;
                        _hideContentWriteOverlay();
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
                }, { firstChunkMs: 120000 });
            } catch (e) {
                if (e && e.name === "AbortError") throw e;
                if (!_contentWriteSession.active) throw new DOMException("Aborted", "AbortError");
                streamErrorMsg = streamErrorMsg || String(e.message || e);
                _caStreamLog("stream exception", streamErrorMsg);
            }

            await _flushContentTypingQueue(signal);
            let finalValue = String(_contentEditorAcc || "");

            if (streamErrorMsg) {
                throw new Error(streamErrorMsg);
            }

            if (!String(finalValue || "").trim()) {
                const errMsg = (window.ContentAiErrors && window.ContentAiErrors.MESSAGE) ||
                    "Hệ thống đang nâng cấp tính năng, mong bạn thông cảm chúng tôi sẽ quay trở lại sớm nhất !";
                throw new Error(errMsg);
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
            _caStreamLog("write complete", { chars: finalValue.length, sawDelta, streamDone });
            return finalValue;
        } catch (e) {
            if (e && e.name === "AbortError") {
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
            _stopContentWrite();
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
        const statsEl = byId("mediaInsertedStatsText");
        if (statsEl) statsEl.textContent = msg;
    };
    const switchMediaToInsertedTab = () => {
        const root = byId("contentAiMediaPanel");
        if (root && window.__caSwitchModalTab) window.__caSwitchModalTab(root, 2);
    };
    window.__caSwitchMediaInsertedTab = switchMediaToInsertedTab;
    let _mediaContentBeforeInsert = "";
    const renderUploadList = () => {
        if (!uploadList) return;
        uploadList.innerHTML = "";
        if (!uploadedImages.length) {
            uploadList.innerHTML = '<p class="ca-il-empty">Chưa có ảnh đã chọn.</p>';
            return;
        }
        uploadedImages.forEach((url, idx) => {
            const div = document.createElement("div");
            div.className = "ca-media-selected-item upload-item";
            const thumb = document.createElement("img");
            thumb.src = url;
            thumb.alt = idx === 0 ? "Featured" : "Inline";
            thumb.loading = "lazy";
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
                ev.stopPropagation();
                try {
                    if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
                        const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.googleImage);
                        if (!ok) return;
                    }
                    setHint("google-images", "Đang import ảnh...");
                    bImport.disabled = true;
                    const res = await fetch(`/content-ai/google-images/import?ts=${Date.now()}`, {
                        method: "POST",
                        headers: authJsonHeaders(),
                        body: JSON.stringify({ url: it.link }),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Import ảnh thất bại");
                    if (data.url) {
                        if (!_mediaContentBeforeInsert) _mediaContentBeforeInsert = getContentValue();
                        uploadedImages.push(data.url);
                        renderUploadList();
                        insertImageIntoEditor(data.url);
                        saveFormState();
                        const undoBtn = byId("btnMediaUndo");
                        if (undoBtn) undoBtn.hidden = false;
                        showMediaInsertSummary("Đã chèn 1 ảnh web — ALT từ tiêu đề ảnh, vị trí sau H2.");
                        switchMediaToInsertedTab();
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

    // --- Content AI duplicate / same-intent detection (uses /content-ai/duplicate-check) ---
    let _caDupSeq = 0;
    let _caDupBlocked = false;
    let _caDupTimer = null;
    let _caDupAbort = null;
    let _caDupClickBound = false;

    const _caDupFormatExisting = (existing) => {
        if (!existing || typeof existing !== "object") return "";
        const title = String(existing.title || existing.primary_keyword || "").trim();
        const url = String(existing.url || "").trim();
        if (title && url) return `${title} — ${url}`;
        return title || url || "";
    };

    const _caDupMatchLabel = (matchType) => {
        const t = String(matchType || "").toLowerCase();
        if (t === "exact") return "Trùng chính xác";
        if (t === "same_intent") return "Chung search intent";
        return "Đã tồn tại";
    };

    const _caDupCollectMatches = (dupResult) => {
        if (!dupResult || typeof dupResult !== "object") return [];
        const raw = Array.isArray(dupResult.matches) ? dupResult.matches.slice() : [];
        if (!raw.length && dupResult.existing && typeof dupResult.existing === "object") {
            const ex = dupResult.existing;
            raw.push({
                article_id: String(ex.article_id || ex.project_id || "").trim(),
                title: String(ex.title || "").trim(),
                url: String(ex.url || "").trim(),
                match_type: String(dupResult.match_type || "").trim(),
                message: String(dupResult.message || "").trim(),
                primary_keyword: String(ex.primary_keyword || "").trim(),
            });
        }
        const out = [];
        const seen = new Set();
        for (const m of raw) {
            if (!m || typeof m !== "object") continue;
            const articleId = String(m.article_id || m.project_id || "").trim();
            const url = String(m.url || "").trim();
            const dedupe = articleId ? `id:${articleId}` : (url ? `url:${url}` : "");
            if (dedupe && seen.has(dedupe)) continue;
            if (dedupe) seen.add(dedupe);
            out.push({
                article_id: articleId,
                title: String(m.title || m.primary_keyword || "").trim(),
                url: String(m.publicUrl || m.url || "").trim(),
                publicUrl: String(m.publicUrl || m.url || "").trim(),
                editUrl: String(m.editUrl || "").trim(),
                postId: parseInt(m.postId || m.post_id || 0, 10) || 0,
                target_website: String(m.target_website || "").trim(),
                source: String(m.source || "").trim(),
                match_type: String(m.match_type || dupResult.match_type || "").trim(),
                message: String(m.message || dupResult.message || "").trim(),
                primary_keyword: String(m.primary_keyword || "").trim(),
            });
            if (out.length >= 3) break;
        }
        return out;
    };

    const _caDupCollectFromRejected = (rejected) => {
        const out = [];
        const seen = new Set();
        for (const item of (Array.isArray(rejected) ? rejected : [])) {
            const dup = item && item.duplicate ? item.duplicate : item;
            for (const m of _caDupCollectMatches(dup)) {
                const key = m.article_id ? `id:${m.article_id}` : (m.url ? `url:${m.url}` : "");
                if (key && seen.has(key)) continue;
                if (key) seen.add(key);
                out.push(m);
                if (out.length >= 3) return out;
            }
        }
        return out;
    };

    const openDuplicateArticleById = async (articleId) => {
        const id = String(articleId || "").trim();
        if (!id) return false;
        try {
            if (typeof window.DigiSeoLoadContentAiProject === "function") {
                await window.DigiSeoLoadContentAiProject(id);
                return true;
            }
        } catch (err) {
            try {
                if (typeof showCaToast === "function") {
                    showCaToast(String(err && err.message || "Không mở được bài viết."), "error");
                }
            } catch (_) {}
            return false;
        }
        // Fallback: deep-link into existing Content AI open flow (?article_id=).
        try {
            const u = new URL(window.location.href);
            u.pathname = "/content-ai";
            u.searchParams.set("article_id", id);
            window.location.assign(u.pathname + "?" + u.searchParams.toString() + (u.hash || ""));
            return true;
        } catch (_) {
            return false;
        }
    };

    const openDuplicateInCauSeoEditor = async (payload) => {
        const url = String((payload && (payload.url || payload.publicUrl)) || "").trim();
        if (!url) return false;
        try {
            if (window.ContentAiTabLoader && typeof window.ContentAiTabLoader.ensureAutoUpdateTab === "function") {
                await window.ContentAiTabLoader.ensureAutoUpdateTab();
            }
            const tab = document.getElementById("tabMainAutoUpdate");
            if (tab) tab.click();
            await new Promise((resolve) => setTimeout(resolve, 80));
            if (typeof window.cauOpenSeoEditFromUrl === "function") {
                await window.cauOpenSeoEditFromUrl(payload);
                return true;
            }
            if (typeof showCaToast === "function") {
                showCaToast("Chưa tải xong tab Auto Update — thử lại sau vài giây.", "warn");
            }
            return false;
        } catch (err) {
            try {
                if (typeof showCaToast === "function") {
                    showCaToast(String(err && err.message || "Không mở được Sửa SEO."), "error");
                }
            } catch (_) {}
            return false;
        }
    };

    const renderDuplicateMatchCards = (box, matches, options = {}) => {
        if (!box) return;
        const list = Array.isArray(matches) ? matches.slice(0, 3) : [];
        const heading = String(options.heading || "").trim();
        box.innerHTML = "";
        if (!list.length) {
            box.hidden = true;
            box.setAttribute("aria-hidden", "true");
            return;
        }
        box.hidden = false;
        box.setAttribute("aria-hidden", "false");
        if (heading) {
            const msg = document.createElement("div");
            msg.className = "ca-dup-msg";
            msg.textContent = heading;
            box.appendChild(msg);
        }
        const cards = document.createElement("div");
        cards.className = "ca-dup-cards";
        const defaultSiteUrl = String(options.target_website || "").trim()
            || String((document.getElementById("targetWebsite") || {}).value || "").trim();
        list.forEach((m) => {
            const articleId = String(m.article_id || "").trim();
            const publicUrl = String(m.publicUrl || m.url || "").trim();
            const postId = parseInt(m.postId || 0, 10) || 0;
            const hasProject = !!articleId;
            const hasPublicUrl = !!publicUrl && /^https?:\/\//i.test(publicUrl);
            const canCauEdit = hasPublicUrl;
            const card = document.createElement("div");
            card.className = "ca-dup-card" + ((hasProject || hasPublicUrl) ? " ca-dup-card--clickable" : "");
            const status = document.createElement("span");
            status.className = "ca-dup-card-status ca-dup-card-status--" + String(m.match_type || "exact");
            status.textContent = _caDupMatchLabel(m.match_type);
            const title = document.createElement("span");
            title.className = "ca-dup-card-title";
            title.textContent = String(m.title || m.primary_keyword || "Bài viết").trim() || "Bài viết";
            const sourceEl = document.createElement("span");
            sourceEl.className = "ca-dup-card-source";
            const srcRaw = String(m.source || "").trim().toLowerCase();
            if (srcRaw === "published") sourceEl.textContent = "Nguồn: Website đã đăng";
            else if (srcRaw === "content_ai" || hasProject) sourceEl.textContent = "Nguồn: Content AI";
            else if (hasPublicUrl) sourceEl.textContent = "Nguồn: Website";
            else sourceEl.textContent = "";
            const kw = document.createElement("span");
            kw.className = "ca-dup-card-kw";
            kw.textContent = String(m.primary_keyword || "").trim()
                ? `Từ khóa: ${String(m.primary_keyword).trim()}`
                : "";
            const urlEl = document.createElement("span");
            urlEl.className = "ca-dup-card-url";
            if (hasPublicUrl) {
                const a = document.createElement("a");
                a.href = publicUrl;
                a.target = "_blank";
                a.rel = "noopener noreferrer";
                a.className = "ca-dup-card-url-link";
                a.textContent = publicUrl.length > 70 ? publicUrl.slice(0, 67) + "…" : publicUrl;
                a.title = publicUrl;
                a.addEventListener("click", (ev) => ev.stopPropagation());
                urlEl.appendChild(a);
            } else {
                urlEl.textContent = hasProject ? `ID: ${articleId}` : "";
            }
            const actions = document.createElement("div");
            actions.className = "ca-dup-card-actions";
            if (hasPublicUrl) {
                const openBtn = document.createElement("a");
                openBtn.href = publicUrl;
                openBtn.target = "_blank";
                openBtn.rel = "noopener noreferrer";
                openBtn.className = "ca-dup-card-btn ca-dup-card-btn--open";
                openBtn.textContent = "Mở bài viết";
                openBtn.addEventListener("click", (ev) => ev.stopPropagation());
                actions.appendChild(openBtn);
            }
            if (canCauEdit) {
                const editBtn = document.createElement("button");
                editBtn.type = "button";
                editBtn.className = "ca-dup-card-btn ca-dup-card-btn--edit";
                editBtn.setAttribute("data-ca-cau-edit", "1");
                editBtn.setAttribute("data-ca-cau-url", publicUrl);
                if (postId > 0) editBtn.setAttribute("data-ca-cau-post-id", String(postId));
                const siteUrl = String(m.target_website || defaultSiteUrl || "").trim();
                if (siteUrl) editBtn.setAttribute("data-ca-cau-site-url", siteUrl);
                editBtn.setAttribute("data-ca-cau-title", String(m.title || m.primary_keyword || "").trim());
                editBtn.textContent = "Chỉnh sửa bài viết";
                editBtn.title = "Mở Sửa SEO trong tab Auto Update";
                actions.appendChild(editBtn);
            } else if (hasProject) {
                const editBtn = document.createElement("button");
                editBtn.type = "button";
                editBtn.className = "ca-dup-card-btn ca-dup-card-btn--edit";
                editBtn.setAttribute("data-ca-article-id", articleId);
                editBtn.setAttribute("data-ca-open-article", "1");
                editBtn.textContent = "Chỉnh sửa bài viết";
                editBtn.title = "Mở bài trong Content AI";
                actions.appendChild(editBtn);
            }
            card.appendChild(status);
            card.appendChild(title);
            if (sourceEl.textContent) card.appendChild(sourceEl);
            if (kw.textContent) card.appendChild(kw);
            if (urlEl.textContent || urlEl.children.length) card.appendChild(urlEl);
            if (actions.children.length) card.appendChild(actions);
            cards.appendChild(card);
        });
        box.appendChild(cards);
    };

    const bindDuplicateCardDelegation = () => {
        if (_caDupClickBound) return;
        _caDupClickBound = true;
        document.addEventListener("click", (ev) => {
            const t = ev.target;
            if (!t || typeof t.closest !== "function") return;
            // Auto Update → Sửa SEO for published WordPress posts
            const cauEditBtn = t.closest("[data-ca-cau-edit][data-ca-cau-url]");
            if (cauEditBtn) {
                const url = String(cauEditBtn.getAttribute("data-ca-cau-url") || "").trim();
                if (!url) return;
                ev.preventDefault();
                ev.stopPropagation();
                const postId = parseInt(cauEditBtn.getAttribute("data-ca-cau-post-id") || "0", 10) || 0;
                void openDuplicateInCauSeoEditor({
                    url,
                    publicUrl: url,
                    postId,
                    title: String(cauEditBtn.getAttribute("data-ca-cau-title") || "").trim(),
                    siteUrl: String(cauEditBtn.getAttribute("data-ca-cau-site-url") || "").trim(),
                    target_website: String(cauEditBtn.getAttribute("data-ca-cau-site-url") || "").trim(),
                });
                return;
            }
            // Content AI project open (no published URL)
            const openCard = t.closest("[data-ca-open-article][data-ca-article-id]");
            if (openCard) {
                const id = String(openCard.getAttribute("data-ca-article-id") || "").trim();
                if (!id) return;
                ev.preventDefault();
                ev.stopPropagation();
                void openDuplicateArticleById(id);
            }
        });
    };

    const checkContentAiDuplicates = async (keywords, options = {}) => {
        const list = (Array.isArray(keywords) ? keywords : [keywords])
            .map((k) => String(k || "").trim())
            .filter(Boolean);
        if (!list.length) {
            return { results: [], has_duplicates: false };
        }
        const body = {
            keywords: list,
            target_website: String(options.target_website || "").trim() || null,
            exclude_project_id: String(options.exclude_project_id || "").trim() || null,
            refresh: !!options.refresh,
        };
        const fetchOpts = {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify(body),
            credentials: "same-origin",
        };
        if (options.signal) fetchOpts.signal = options.signal;
        const doFetch = (typeof apiFetch === "function") ? apiFetch : fetch;
        const res = await doFetch("/content-ai/duplicate-check", fetchOpts);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = (data && data.detail) ? data.detail : `HTTP ${res.status}`;
            throw new Error(typeof detail === "string" ? detail : (detail.message || "Duplicate check failed"));
        }
        return data;
    };

    const setSingleDuplicateUi = (result, options = {}) => {
        const hint = byId("hint-primary_keyword");
        const box = byId("caDuplicateWarning");
        const meta = options.meta || null;
        const isDup = !!(result && result.is_duplicate);
        const matchType = String((result && result.match_type) || "").toLowerCase();
        // exact → block; same_intent → warn only
        _caDupBlocked = isDup && matchType === "exact";
        bindDuplicateCardDelegation();
        const targetWebsiteEl = byId("targetWebsite");
        const targetWebsiteVal = targetWebsiteEl ? String(targetWebsiteEl.value || "").trim() : "";
        if (box) {
            if (isDup) {
                const matches = _caDupCollectMatches(result);
                renderDuplicateMatchCards(box, matches, {
                    heading: String(result.message || "Bài viết này đã tồn tại"),
                    target_website: targetWebsiteVal,
                });
            } else {
                const metaMsg = String((meta && meta.message) || "").trim();
                const scanned = Number(meta && meta.wp_articles_scanned) || 0;
                let okMsg = "Không tìm thấy bài trùng với từ khóa này.";
                if (scanned > 0) {
                    okMsg += ` Đã quét ${scanned} bài trên website.`;
                }
                if (metaMsg) {
                    okMsg += ` ${metaMsg}`;
                }
                box.hidden = false;
                box.setAttribute("aria-hidden", "false");
                box.innerHTML = `<div class="ca-dup-msg ca-dup-msg--ok">${okMsg}</div>`;
            }
        }
        if (hint && isDup) {
            hint.textContent = String(result.message || "");
            hint.classList.add("ca-hint-dup");
        } else if (hint && !isDup && options.checked) {
            hint.textContent = "Đã kiểm tra trùng nội dung.";
            hint.classList.remove("ca-hint-dup");
        } else if (hint && !isDup) {
            hint.classList.remove("ca-hint-dup");
        }
        const busy = !!(window.__caCreateContentBusy);
        if (btnCreateContent) {
            btnCreateContent.disabled = busy || _caDupBlocked;
            if (!busy) btnCreateContent.textContent = _CREATE_CONTENT_LABEL || "Tạo content";
        }
        const sticky = byId("caStickyCreateContent");
        if (sticky) {
            sticky.disabled = busy || _caDupBlocked;
            if (!busy) sticky.textContent = _CREATE_CONTENT_LABEL || "Tạo content";
        }
    };

    const clearSingleDuplicateUi = () => {
        setSingleDuplicateUi(null);
        _caDupBlocked = false;
    };

    const scheduleSingleDuplicateCheck = () => {
        if (_caDupTimer) window.clearTimeout(_caDupTimer);
        _caDupTimer = window.setTimeout(() => {
            void runSingleDuplicateCheck();
        }, 500);
    };

    const runSingleDuplicateCheck = async (options = {}) => {
        const pkEl = byId("primaryKeyword");
        const kw = pkEl ? String(pkEl.value || "").trim() : "";
        if (!kw) {
            if (_caDupAbort) {
                try { _caDupAbort.abort(); } catch (_) {}
                _caDupAbort = null;
            }
            clearSingleDuplicateUi();
            return null;
        }
        const seq = ++_caDupSeq;
        const requestedKw = kw;
        if (_caDupAbort) {
            try { _caDupAbort.abort(); } catch (_) {}
        }
        const controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
        _caDupAbort = controller;
        try {
            const tw = byId("targetWebsite");
            const data = await checkContentAiDuplicates([kw], {
                target_website: tw ? tw.value.trim() : "",
                exclude_project_id: typeof activeProjectId !== "undefined" ? activeProjectId : "",
                refresh: !!options.refresh,
                signal: controller ? controller.signal : undefined,
            });
            // Stale response: newer keystroke / aborted request must not overwrite UI.
            if (seq !== _caDupSeq) return null;
            const liveKw = pkEl ? String(pkEl.value || "").trim() : "";
            if (liveKw !== requestedKw) return null;
            const result = (data.results && data.results[0]) || null;
            setSingleDuplicateUi(result, { meta: data.meta || null, checked: true });
            if (options.toast !== false) {
                try {
                    if (typeof showCaToast === "function") {
                        if (result && result.is_duplicate) {
                            showCaToast(String(result.message || "Phát hiện bài trùng."), "warn");
                        } else {
                            showCaToast("Không tìm thấy bài trùng.", "success");
                        }
                    }
                } catch (_) {}
            }
            return result;
        } catch (err) {
            const aborted = !!(err && (err.name === "AbortError" || err.code === 20));
            if (aborted || seq !== _caDupSeq) return null;
            clearSingleDuplicateUi();
            try {
                const hint = byId("hint-primary_keyword");
                const box = byId("caDuplicateWarning");
                const errText = String(err && err.message ? err.message : "Không kiểm tra được trùng nội dung.");
                if (hint) {
                    hint.textContent = errText;
                    hint.classList.add("ca-hint-dup");
                }
                if (box) {
                    box.hidden = false;
                    box.setAttribute("aria-hidden", "false");
                    box.innerHTML = `<div class="ca-dup-msg ca-dup-msg--error">${errText}</div>`;
                }
                if (typeof showCaToast === "function") showCaToast(errText, "error");
            } catch (_) {}
            return null;
        } finally {
            if (_caDupAbort === controller) _caDupAbort = null;
        }
    };

    const filterBulkKeywordsByDuplicateCheck = async (parsedList, options = {}) => {
        const list = Array.isArray(parsedList) ? parsedList : [];
        if (!list.length) return { kept: [], rejected: [] };
        const keywords = list.map((p) => String(p.keyword || "").trim()).filter(Boolean);
        const twEl = byId("bulkTargetWebsite");
        let data;
        try {
            data = await checkContentAiDuplicates(keywords, {
                target_website: options.target_website
                    || (twEl ? twEl.value.trim() : ""),
            });
        } catch (_) {
            return { kept: list, rejected: [] };
        }
        const byKw = new Map();
        (data.results || []).forEach((r) => {
            const k = String(r.keyword || "").trim().toLowerCase();
            if (k) byKw.set(k, r);
        });
        const kept = [];
        const rejected = [];
        for (const parsed of list) {
            const k = String(parsed.keyword || "").trim().toLowerCase();
            const r = byKw.get(k);
            if (r && r.is_duplicate) {
                rejected.push({ ...parsed, duplicate: r });
            } else {
                kept.push(parsed);
            }
        }
        return { kept, rejected };
    };

    const renderBulkDuplicateWarning = (rejected) => {
        const warn = byId("bulkDuplicateWarning");
        if (!warn) return;
        bindDuplicateCardDelegation();
        const list = Array.isArray(rejected) ? rejected : [];
        if (!list.length) {
            warn.hidden = true;
            warn.setAttribute("aria-hidden", "true");
            warn.innerHTML = "";
            return;
        }
        const matches = _caDupCollectFromRejected(list);
        const first = list[0].duplicate || {};
        const heading = list.length === 1
            ? String(first.message || "Bài viết này đã tồn tại")
            : `Đã bỏ ${list.length} từ khóa trùng bài đã có.`;
        renderDuplicateMatchCards(warn, matches, { heading });
    };

    const logBulkDuplicateRejections = (rejected) => {
        if (!rejected || !rejected.length) return;
        rejected.forEach((item) => {
            const dup = item.duplicate || {};
            const msg = String(dup.message || "Bài viết này đã tồn tại");
            const existing = _caDupFormatExisting(dup.existing);
            const line = existing
                ? `Bỏ từ khóa trùng: "${item.keyword}" — ${msg} (${existing})`
                : `Bỏ từ khóa trùng: "${item.keyword}" — ${msg}`;
            try {
                if (typeof appendBulkLog === "function") appendBulkLog(line);
            } catch (_) {}
            try {
                if (typeof showCaToast === "function") showCaToast(line, "warn");
            } catch (_) {}
        });
    };

    bindDuplicateCardDelegation();

    window.ContentAiDuplicate = {
        check: checkContentAiDuplicates,
        scheduleSingleCheck: scheduleSingleDuplicateCheck,
        runSingleCheck: runSingleDuplicateCheck,
        clearSingleUi: clearSingleDuplicateUi,
        isBlocked: () => !!_caDupBlocked,
        filterBulk: filterBulkKeywordsByDuplicateCheck,
        logBulkRejections: logBulkDuplicateRejections,
        renderBulkWarning: renderBulkDuplicateWarning,
        formatExisting: _caDupFormatExisting,
        collectMatches: _caDupCollectMatches,
        openArticle: openDuplicateArticleById,
    };

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


    /* AI Visual Content Studio */
    const studioGallery = byId("studioGallery");
    const studioIncludeText = byId("studioIncludeText");
    const studioTextHintWrap = byId("studioTextHintWrap");
    let studioPreviews = [];
    let studioSelectedIndex = 0;
    let studioCatalogCache = null;
    let _pendingMediaPanelRestore = null;

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
        if (s.hintGoogleImages) setHint("google-images", s.hintGoogleImages);
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
        if (h) h.textContent = msg;
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

    const renderStudioGallery = () => {
        if (!studioGallery) return;
        studioGallery.innerHTML = "";
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
            img.src = p.url;
            img.alt = p.alt || "Preview AI";
            img.loading = "lazy";
            img.className = "ca-media-thumb-img studio-thumb-click";
            img.draggable = false;
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
                    studioSelectedIndex = idx;
                    renderStudioGallery();
                    handler(p, idx);
                });
                return b;
            };
            btns.appendChild(mk("Chọn", () => {}));
            btns.appendChild(mk("Chèn", () => studioInsertSelected(p, "inline")));
            btns.appendChild(mk("Featured", () => studioInsertSelected(p, "featured")));
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
                headers: authJsonHeaders(),
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
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : "Chèn ảnh thất bại");
            }
            if (data.content) {
                if (typeof _mediaContentBeforeInsert !== "undefined" && !_mediaContentBeforeInsert) {
                    _mediaContentBeforeInsert = getContentValue();
                }
                setContentValue(data.content);
            }
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
            setStudioHint(data.ok ? (mode === "featured" ? "Đã đặt ảnh đại diện." : "Đã chèn ảnh vào bài.") : "Xong.");
            setHint("image", mode === "featured" ? "Featured từ AI Studio." : "Đã chèn ảnh từ AI Studio.");
            if (typeof showMediaInsertSummary === "function") {
                showMediaInsertSummary(
                    mode === "featured"
                        ? "1 ảnh featured — ALT từ ngữ cảnh H2."
                        : `1 ảnh inline — vị trí: ${insertH2 || "sau H2"}.`,
                );
            }
            if (typeof window.__caSwitchMediaInsertedTab === "function") {
                window.__caSwitchMediaInsertedTab();
            } else if (window.__caSwitchModalTab) {
                window.__caSwitchModalTab(byId("contentAiMediaPanel"), 2);
            }
            const undoBtn = byId("btnMediaUndo");
            if (undoBtn) undoBtn.hidden = false;
        } catch (e) {
            setStudioHint(String(e.message || e));
        }
    };

    const studioRegenerateOne = async (idx) => {
        setStudioHint("Đang tạo lại…");
        const btn = byId("btnStudioGenerate");
        if (btn) btn.disabled = true;
        try {
            if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
                const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.aiImage);
                if (!ok) return;
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
        }
    };

    const runStudioGenerate = async () => {
        const pk = String(byId("primaryKeyword")?.value || "").trim();
        if (!pk) {
            setStudioHint("Cần từ khóa chính trước khi tạo ảnh AI.");
            return;
        }
        const btn = byId("btnStudioGenerate");
        const findBtn = byId("btnMediaFindOrCreate");
        if (btn) btn.disabled = true;
        if (findBtn) findBtn.disabled = true;
        setStudioHint("Đang tạo ảnh AI (OpenRouter)…");
        studioPreviews = [];
        renderStudioGallery();
        try {
            if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
                const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.aiImage);
                if (!ok) return;
            }
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
            setStudioHint(data.message || `Đã tạo ${studioPreviews.length} ảnh preview.`);
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

    window.DigiSeoLoadContentAiProject = async function (projectId) {
        const pid = String(projectId || "").trim();
        if (!pid) return;
        await loadProjectIntoWriteTab(pid);
        try {
            saveFormState();
        } catch (_) {}
    };
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
        const stopBar = byId("btnBulkV2StopWrite");
        if (stopBar) {
            stopBar.disabled = false;
            stopBar.classList.remove("is-busy");
        }
    };
    const getActiveBulkJobId = () => {
        try {
            return String(localStorage.getItem(BULK_JOB_STORAGE_KEY()) || "").trim();
        } catch (_) {
            return "";
        }
    };
    const cancelBulkWriteJob = async () => {
        const jid = getActiveBulkJobId();
        if (!jid) {
            stopBulkPoll();
            appendBulkLog("Không có job đang chạy trên trình duyệt.");
            try {
                if (window.ContentAiBulkUi && window.ContentAiBulkUi.setStep) {
                    window.ContentAiBulkUi.setStep("setup");
                }
            } catch (_) {}
            return;
        }
        const ok = window.confirm(
            "Dừng viết hàng loạt?\nBài đang viết có thể hoàn tất; các bài còn lại sẽ không chạy.\nBạn có thể setup lại rồi viết tiếp."
        );
        if (!ok) return;
        appendBulkLog("Đang gửi lệnh dừng viết…");
        try {
            const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}/cancel`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: "{}",
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error((data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`);
            }
            appendBulkLog(String((data && data.message) || "Đã dừng viết hàng loạt."));
            if (data.result && Array.isArray(data.result.items)) {
                renderBulkJobItems(data.result.items, { mode: "merge" });
            } else if (bulkJobStatus) {
                bulkJobStatus.textContent = String((data && data.message) || "Đã dừng");
            }
            // Pull latest items once after cancel.
            try {
                const pollRes = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}?ts=${Date.now()}`, {
                    headers: authHeaders(),
                });
                const pollData = await pollRes.json().catch(() => ({}));
                if (pollRes.ok && pollData.result && Array.isArray(pollData.result.items)) {
                    renderBulkJobItems(pollData.result.items, { mode: "merge" });
                }
            } catch (_) {}
            try {
                localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                localStorage.removeItem(BULK_JOB_STORAGE_KEY());
            } catch (_) {}
            scheduleSaveBulkState();
            stopBulkPoll();
            try {
                if (window.ContentAiBulkUi && window.ContentAiBulkUi.setStep) {
                    window.ContentAiBulkUi.setStep("setup");
                }
            } catch (_) {}
            if (msg) msg.textContent = "Đã dừng viết — bạn có thể setup lại rồi bấm viết tiếp.";
        } catch (e) {
            appendBulkLog(`Dừng viết thất bại: ${String(e.message || e)}`);
            // Still stop local polling so UI unlocks.
            stopBulkPoll();
        }
    };
    const pollBulkJob = async (jobId) => {
        const jid = String(jobId || "").trim();
        if (!jid) return;
        try {
            const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jid)}?ts=${Date.now()}`, {
                headers: authHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (res.status === 404) {
                appendBulkLog("Job không còn trên server — đã xóa khỏi bộ nhớ trình duyệt.");
                try {
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                    localStorage.removeItem(BULK_LAST_JOB_KEY());
                } catch (_) {}
                stopBulkPoll();
                if (bulkJobStatus) bulkJobStatus.textContent = "Job đã hết hạn hoặc không tồn tại.";
                return;
            }
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Poll failed");
            const pct = Number(data.progress) || 0;
            if (bulkJobProgress) bulkJobProgress.hidden = false;
            if (bulkJobProgressFill) bulkJobProgressFill.style.width = `${pct}%`;
            if (bulkJobPct) bulkJobPct.textContent = `${pct}%`;
            if (bulkJobStatus) bulkJobStatus.textContent = data.message || data.state || "";
            if (data.result && Array.isArray(data.result.items) && data.result.items.length) {
                // Merge so unselected / previously written rows keep their UI status.
                renderBulkJobItems(data.result.items, { mode: "merge" });
            }
            if (data.state === "SUCCESS") {
                appendBulkLog(`Hoàn tất: ${(data.result && data.result.success) || 0}/${(data.result && data.result.total) || "?"} bài.`);
                stopBulkPoll();
                try {
                    localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                scheduleSaveBulkState();
                await refreshProjects(true);
                return;
            }
            if (data.state === "CANCELLED") {
                appendBulkLog(data.message || data.error || "Đã dừng viết hàng loạt.");
                stopBulkPoll();
                try {
                    localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                scheduleSaveBulkState();
                try {
                    if (window.ContentAiBulkUi && window.ContentAiBulkUi.setStep) {
                        window.ContentAiBulkUi.setStep("setup");
                    }
                } catch (_) {}
                return;
            }
            if (data.state === "ERROR") {
                appendBulkLog(`Lỗi: ${data.error || data.message || "unknown"}`);
                stopBulkPoll();
                try {
                    localStorage.setItem(BULK_LAST_JOB_KEY(), jid);
                    localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                } catch (_) {}
                scheduleSaveBulkState();
            }
        } catch (e) {
            appendBulkLog(String(e.message || e));
        }
    };
    const startBulkPoll = (jobId) => {
        stopBulkPoll();
        const stopBtn = byId("btnBulkWriteStopPoll");
        if (stopBtn) stopBtn.hidden = false;
        const stopBar = byId("btnBulkV2StopWrite");
        if (stopBar) {
            stopBar.disabled = false;
            stopBar.classList.remove("is-busy");
        }
        pollBulkJob(jobId);
        _bulkPollTimer = setInterval(() => pollBulkJob(jobId), 2200);
    };
    if (btnBulkAddKeyword) {
        btnBulkAddKeyword.addEventListener("click", () => void addBulkKeywordFromInput());
    }
    if (btnBulkExpandAll) {
        btnBulkExpandAll.addEventListener("click", () => setAllBulkDetailsOpen(true));
    }
    if (btnBulkCollapseAll) {
        btnBulkCollapseAll.addEventListener("click", () => setAllBulkDetailsOpen(false));
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
    const bulkWriteModeSelectedEl = byId("bulkWriteModeSelected") || byId("bulkWriteModeSetup");
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
    const countBulkUiSelected = () => {
        try {
            if (window.ContentAiBulkUi && typeof window.ContentAiBulkUi.getSelectedKeywords === "function") {
                return (window.ContentAiBulkUi.getSelectedKeywords() || []).length;
            }
        } catch (_) {}
        return 0;
    };
    const openBulkWriteModeModal = (preferredMode) => {
        const all = mergeBulkItems();
        if (!all.length) return Promise.resolve(null);
        return new Promise((resolve) => {
            _bulkWriteModeResolve = resolve;
            const hasSelected = countBulkUiSelected() > 0;
            const preferSelected = preferredMode === "selected" || (preferredMode !== "all" && hasSelected);
            if (bulkWriteModeAllEl) bulkWriteModeAllEl.checked = !preferSelected;
            if (bulkWriteModeSelectedEl) bulkWriteModeSelectedEl.checked = !!preferSelected;
            if (bulkWriteModeBackdropEl) bulkWriteModeBackdropEl.classList.add("open");
            if (bulkWriteModeModalEl) {
                bulkWriteModeModalEl.classList.add("open");
                bulkWriteModeModalEl.setAttribute("aria-hidden", "false");
            }
        });
    };
    if (bulkWriteModeAllEl && bulkWriteModeSelectedEl) {
        const syncBulkWriteModeChecks = (picked) => {
            if (picked === "all") {
                bulkWriteModeAllEl.checked = true;
                bulkWriteModeSelectedEl.checked = false;
            } else {
                bulkWriteModeAllEl.checked = false;
                bulkWriteModeSelectedEl.checked = true;
            }
        };
        bulkWriteModeAllEl.addEventListener("change", () => {
            if (bulkWriteModeAllEl.checked) syncBulkWriteModeChecks("all");
            else if (!bulkWriteModeSelectedEl.checked) bulkWriteModeAllEl.checked = true;
        });
        bulkWriteModeSelectedEl.addEventListener("change", () => {
            if (bulkWriteModeSelectedEl.checked) syncBulkWriteModeChecks("selected");
            else if (!bulkWriteModeAllEl.checked) bulkWriteModeAllEl.checked = true;
        });
    }
    const btnBulkWriteModeCancel = byId("btnBulkWriteModeCancel");
    if (btnBulkWriteModeCancel) btnBulkWriteModeCancel.addEventListener("click", () => closeBulkWriteModeModal(null));
    const btnBulkWriteModeOk = byId("btnBulkWriteModeOk");
    if (btnBulkWriteModeOk) {
        btnBulkWriteModeOk.addEventListener("click", () => {
            const selectedOnly = bulkWriteModeSelectedEl && bulkWriteModeSelectedEl.checked;
            const mode = selectedOnly ? "selected" : "all";
            const filtered = filterBulkItemsByWriteMode(mergeBulkItems(), mode);
            if (!filtered.length) {
                appendBulkLog(
                    mode === "selected"
                        ? "Chưa tích chọn bài nào trong bảng. Hãy tích checkbox các bài cần viết."
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
        const mode = writeMode === "selected" || writeMode === "setup" ? "selected" : "all";
        let bulkItems = filterBulkItemsByWriteMode(mergeBulkItems(), mode);
        if (!bulkItems.length) {
            appendBulkLog(
                mode === "selected"
                    ? "Chưa tích chọn bài nào trong bảng. Hãy tích checkbox các bài cần viết."
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
        const modeLabel = mode === "selected" ? "đã chọn" : "tất cả";
        if (window.DigiSeoConfirmCredit) {
            const ok = await window.DigiSeoConfirmCredit({
                module: "content_ai",
                action: "article_short",
                quantity: keywords.length,
                wordCount: target_word_count,
                quotaKey: "ai_articles",
                label: "Content AI — viết hàng loạt (" + keywords.length + " bài)",
            });
            if (!ok) return;
        }
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
            if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
            }
            let errMsg = (data && data.detail) ? String(data.detail) : `Lỗi HTTP ${res.status}`;
            if (typeof data.detail === "object" && data.detail && data.detail.message) {
                errMsg = String(data.detail.message);
            }
            if (res.status === 409 && typeof data.detail === "object" && data.detail) {
                errMsg = String(data.detail.message || errMsg);
                const rejected = Array.isArray(data.detail.rejected) ? data.detail.rejected : [];
                rejected.forEach((r) => {
                    const existing = window.ContentAiDuplicate
                        ? window.ContentAiDuplicate.formatExisting(r.existing)
                        : "";
                    appendBulkLog(
                        existing
                            ? `Trùng: "${r.keyword}" — ${r.message || ""} (${existing})`
                            : `Trùng: "${r.keyword}" — ${r.message || ""}`
                    );
                });
                if (
                    rejected.length
                    && window.ContentAiDuplicate
                    && typeof window.ContentAiDuplicate.renderBulkWarning === "function"
                ) {
                    window.ContentAiDuplicate.renderBulkWarning(
                        rejected.map((r) => ({ keyword: r.keyword, duplicate: r }))
                    );
                }
            }
            if (res.status === 404) {
                errMsg =
                    "API viết hàng loạt chưa có trên server (404). Tắt cửa sổ run.bat/uvicorn cũ, chạy lại run.bat, rồi Ctrl+F5 trang này.";
            }
            throw new Error(errMsg);
        }
        if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
        appendBulkLog(data.note || `Job ${data.job_id} đã xếp hàng (${modeLabel}, ${keywords.length} bài).`);
        if (Array.isArray(data.rejected_duplicates) && data.rejected_duplicates.length) {
            data.rejected_duplicates.forEach((r) => {
                const existing = window.ContentAiDuplicate
                    ? window.ContentAiDuplicate.formatExisting(r.existing)
                    : "";
                appendBulkLog(
                    existing
                        ? `Đã bỏ trùng: "${r.keyword}" — ${r.message || ""} (${existing})`
                        : `Đã bỏ trùng: "${r.keyword}" — ${r.message || ""}`
                );
            });
            if (window.ContentAiDuplicate && typeof window.ContentAiDuplicate.renderBulkWarning === "function") {
                window.ContentAiDuplicate.renderBulkWarning(
                    data.rejected_duplicates.map((r) => ({ keyword: r.keyword, duplicate: r }))
                );
            }
        }
        const jobKeywords = Array.isArray(data.rejected_duplicates) && data.rejected_duplicates.length
            ? keywords.filter((k) => {
                const lk = String(k || "").trim().toLowerCase();
                return !(data.rejected_duplicates || []).some(
                    (r) => String(r.keyword || "").trim().toLowerCase() === lk
                );
            })
            : keywords;
        initBulkJobStatusTable(jobKeywords);
        if (bulkJobProgress) bulkJobProgress.hidden = false;
        if (bulkJobProgressFill) bulkJobProgressFill.style.width = "1%";
        if (bulkJobPct) bulkJobPct.textContent = "0%";
        if (bulkJobStatus) bulkJobStatus.textContent = "Đã xếp hàng — chờ server viết bài…";
        try {
            localStorage.setItem(BULK_JOB_STORAGE_KEY(), data.job_id);
        } catch (_) {}
        startBulkPoll(data.job_id);
    };
    // Expose for bulk board "Viết bài đã chọn" (avoid racey row-swap hack).
    window.__contentAiStartBulkWriteJob = startBulkWriteJob;
    window.__contentAiOpenBulkWriteModeModal = openBulkWriteModeModal;
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
            void cancelBulkWriteJob();
        });
    }
    const btnBulkV2StopWrite = byId("btnBulkV2StopWrite");
    if (btnBulkV2StopWrite) {
        btnBulkV2StopWrite.addEventListener("click", () => {
            void cancelBulkWriteJob();
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
    const tabMainAutoUpdate = byId("tabMainAutoUpdate");
    if (tabMainAutoUpdate) {
        tabMainAutoUpdate.addEventListener("click", () => {
            setContentAiMainView("autoupdate");
        });
    }
    const closeProjectView = () => {
        setContentAiMainView("single");
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
            try {
                if (window.ContentAiDuplicate) window.ContentAiDuplicate.clearSingleUi();
            } catch (_) {}
        } else {
            const dupBlocked = !!(window.ContentAiDuplicate && window.ContentAiDuplicate.isBlocked());
            if (!dupBlocked) {
                setHint("primary_keyword", "Da kich hoat goi y AI theo tu khoa chinh.");
            }
            try {
                if (window.ContentAiDuplicate) window.ContentAiDuplicate.scheduleSingleCheck();
            } catch (_) {}
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
        if (field === "outline_content") {
            try {
                autoGrowOutline();
            } catch (_) {}
        }
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
                    const nextObj = await fetchSuggestion(field, ctx);
                    const next = nextObj.value || "";
                    detectedIntent = nextObj.detected_intent || detectedIntent;
                    value = next;
                    if (value && value !== current) lastSuggestedTitle = value;
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
                const errText = String(err.message || err);
                setHint(field, errText);
            } finally {
                button.textContent = oldText;
                button.disabled = false;
                toggleAiAvailability();
            }
        });
    });
    const pkInputEl = byId("primaryKeyword");
    if (pkInputEl) {
        pkInputEl.addEventListener("input", () => {
            toggleAiAvailability();
            syncSlugFromPrimary(true);
        });
    }
    const targetWebsiteEl = byId("targetWebsite");
    if (targetWebsiteEl) {
        targetWebsiteEl.addEventListener("input", () => {
            syncSlugFromPrimary();
        });
        targetWebsiteEl.addEventListener("change", () => {
            rememberTargetWebsite(targetWebsiteEl.value);
        });
    }
    const checkDupBtn = byId("btnCheckDuplicate");
    if (checkDupBtn) {
        checkDupBtn.addEventListener("click", async () => {
            const pk = byId("primaryKeyword");
            const kw = pk ? pk.value.trim() : "";
            if (!kw) {
                try { if (typeof showCaToast === "function") showCaToast("Nhập từ khóa chính trước.", "warn"); } catch (_) {}
                return;
            }
            checkDupBtn.disabled = true;
            checkDupBtn.textContent = "⏳ Đang kiểm tra…";
            try {
                const result = await window.ContentAiDuplicate.runSingleCheck({ refresh: true, toast: true });
                if (!result) {
                    try { if (typeof showCaToast === "function") showCaToast("Không nhận được kết quả kiểm tra trùng.", "warn"); } catch (_) {}
                }
            } catch (err) {
                try { if (typeof showCaToast === "function") showCaToast(String(err && err.message || "Kiểm tra trùng thất bại."), "error"); } catch (_) {}
            }
            checkDupBtn.disabled = false;
            checkDupBtn.textContent = "🔍 Kiểm tra trùng";
        });
    }
    toggleAiAvailability();
    syncSlugFromPrimary(true);
    renderUploadList();
    renderTargetHistory();
    renderWpUrlHistory();
    renderWpUserHistory();
    const CLUSTER_PREFILL_KEY = "seoauto_content_ai_prefill";
    const CLUSTER_PREFILL_LEGACY_KEYS = ["seoauto_cluster_bulk_prefill", "seoauto_cluster_single_prefill"];
    const CLUSTER_PREFILL_TOAST = "Đã nhập đầy đủ từ khóa và outline từ cụm keyword";
    const clearClusterPrefillStorage = () => {
        try {
            sessionStorage.removeItem(CLUSTER_PREFILL_KEY);
            CLUSTER_PREFILL_LEGACY_KEYS.forEach((k) => sessionStorage.removeItem(k));
        } catch (_) {}
    };
    const keywordTextFromToken = (k) => {
        if (k == null) return "";
        if (typeof k === "string") return k.trim();
        if (typeof k === "object") return String(k.keyword || k.text || "").trim();
        return String(k).trim();
    };
    const collectSecondaryFromPayload = (p, mainKw) => {
        const mainLower = String(mainKw || "").trim().toLowerCase();
        const buckets = [];
        const addList = (list) => {
            if (!list) return;
            buckets.push(Array.isArray(list) ? list : [list]);
        };
        addList(p.secondary_keywords);
        addList(p.supporting_keywords);
        addList(p.keywords);
        addList(p.variations);
        addList(p.semantic_keywords);
        const seen = new Set();
        const out = [];
        buckets.forEach((list) => {
            (list || []).forEach((item) => {
                const k = keywordTextFromToken(item);
                if (!k) return;
                const lk = k.toLowerCase();
                if (lk === mainLower || seen.has(lk)) return;
                seen.add(lk);
                out.push(k);
            });
        });
        return out;
    };
    const isRawJsonOutlineText = (s) => {
        const t = String(s || "").trim();
        if (!t) return false;
        const first = t.charAt(0);
        const last = t.charAt(t.length - 1);
        if ((first === "{" && last === "}") || (first === "[" && last === "]")) {
            try {
                JSON.parse(t);
                return true;
            } catch (_) {}
        }
        return false;
    };
    const generateSeoOutlineFromPayload = (p, mainKw, secKws) => {
        const title = String(p.recommended_title || p.topic || mainKw || "").trim();
        const mk = String(mainKw || p.topic || "").trim();
        const intent = String(p.intent || "").trim();
        const contentType = String(p.content_type || p.suggested_content_type || "").trim();
        const lines = [`H1: ${title}`, ""];
        if (mk) lines.push(`H2: ${mk} là gì?`);
        if (secKws.length) {
            lines.push(`H2: ${contentType ? `${contentType} — ` : "Chi tiết về "}${mk}`);
            secKws.slice(0, 6).forEach((kw) => lines.push(`  H3: ${kw}`));
        }
        lines.push("H2: Lợi ích và ứng dụng");
        if (secKws.length > 6) {
            lines.push("H2: Câu hỏi thường gặp");
            secKws.slice(6, 10).forEach((kw) => lines.push(`  - ${kw}`));
        }
        lines.push("H2: Kết luận");
        const meta = [];
        if (intent) meta.push(`Intent: ${intent}`);
        if (contentType) meta.push(`Loại bài: ${contentType}`);
        if (meta.length) {
            lines.push("");
            lines.push(meta.join(" · "));
        }
        return lines.join("\n").trim();
    };
    const resolveOutlineFromPayload = (p, mainKw, secKws) => {
        const candidates = [p.custom_outline, p.outline, p.content_angle].filter(Boolean);
        for (const raw of candidates) {
            const s = String(raw).trim();
            if (s && !isRawJsonOutlineText(s)) return s;
        }
        return generateSeoOutlineFromPayload(p, mainKw, secKws);
    };
    const readClusterPrefillPayload = () => {
        try {
            let raw = sessionStorage.getItem(CLUSTER_PREFILL_KEY);
            if (raw) {
                sessionStorage.removeItem(CLUSTER_PREFILL_KEY);
                return JSON.parse(raw);
            }
            raw = sessionStorage.getItem("seoauto_cluster_bulk_prefill");
            if (raw) {
                sessionStorage.removeItem("seoauto_cluster_bulk_prefill");
                const bulk = JSON.parse(raw);
                return { mode: "bulk", ...bulk };
            }
            raw = sessionStorage.getItem("seoauto_cluster_single_prefill");
            if (raw) {
                sessionStorage.removeItem("seoauto_cluster_single_prefill");
                return { mode: "single", data: JSON.parse(raw) };
            }
        } catch (_) {}
        return null;
    };
    const applySingleClusterPrefill = (p) => {
        const mainKw = keywordTextFromToken(p.primary_keyword || p.main_keyword || "");
        const pk = byId("primaryKeyword");
        if (pk) pk.value = mainKw;
        const secKws = collectSecondaryFromPayload(p, mainKw);
        const sk = byId("secondaryKeywords");
        if (sk) sk.value = secKws.join(", ");
        const ti = byId("title");
        const topicTitle = String(p.recommended_title || p.topic || "").trim();
        if (ti && topicTitle) ti.value = topicTitle;
        const mt = byId("meta");
        if (mt && p.meta_description) mt.value = String(p.meta_description);
        const tw = byId("targetWebsite");
        if (tw && p.target_website) tw.value = String(p.target_website);
        const twc = byId("targetWordCount");
        if (twc && p.target_word_count != null && String(p.target_word_count).trim() !== "") {
            twc.value = String(p.target_word_count);
        }
        const ol = byId("outlineContent");
        if (ol) ol.value = resolveOutlineFromPayload(p, mainKw, secKws);
        if (p.intent) setDetectedIntentDebug(p.intent);
        syncSlugFromPrimary(true);
        toggleAiAvailability();
        try {
            autoGrowOutline();
        } catch (_) {}
    };
    const applyClusterPrefillFromSession = async () => {
        let appliedMode = false;
        try {
            const payload = readClusterPrefillPayload();
            if (payload && payload.mode === "bulk" && Array.isArray(payload.items) && payload.items.length) {
                resetBulkWriteForm();
                setContentAiMainView("bulk");
                const btw = byId("bulkTargetWebsite");
                if (btw && payload.target_website) btw.value = payload.target_website;
                const parsed = payload.items.map((it) => {
                    const main = keywordTextFromToken(it.keyword || it.primary_keyword || it.main_keyword || "");
                    const secKws = collectSecondaryFromPayload(it, main);
                    const outlineRaw = String(it.custom_outline || it.outline || "").trim();
                    const outline = outlineRaw && !isRawJsonOutlineText(outlineRaw)
                        ? outlineRaw
                        : generateSeoOutlineFromPayload(it, main, secKws);
                    const intent = String(it.intent || "").trim();
                    return {
                        keyword: main,
                        custom_title: String(it.custom_title || it.topic || "").trim(),
                        custom_description: String(it.custom_description || it.meta_description || (intent ? `Search intent: ${intent}` : "")).trim(),
                        custom_outline: outline,
                        search_volume: it.search_volume != null && it.search_volume !== "" ? it.search_volume : "",
                        content_type: String(it.content_type || it.suggested_content_type || "").trim(),
                        target_word_count: it.target_word_count != null && it.target_word_count !== "" ? it.target_word_count : "",
                        secondary_keywords: secKws.length ? secKws.join(", ") : (
                            Array.isArray(it.secondary_keywords)
                                ? it.secondary_keywords.map((x) => keywordTextFromToken(x)).filter(Boolean).join(", ")
                                : String(it.secondary_keywords || "").trim()
                        ),
                    };
                }).filter((x) => x.keyword);
                if (parsed.length) {
                    await addBulkKeywordsFromParsed(parsed, { fetchVolume: false });
                    bulkKeywordRows.forEach((row) => {
                        if (row.custom_title || row.custom_description || row.custom_outline || row.secondary_keywords) {
                            row.detailsOpen = true;
                        }
                    });
                    renderBulkKeywordList();
                }
                scheduleSaveBulkState();
                appliedMode = "bulk";
            } else if (payload && payload.mode === "single" && payload.data && typeof payload.data === "object") {
                resetContentAiSingleForm();
                setContentAiMainView("single");
                applySingleClusterPrefill(payload.data);
                scheduleSaveFormState();
                appliedMode = "single";
            } else {
                const params = new URLSearchParams(window.location.search || "");
                const modeParam = params.get("mode");
                const wantBulk = modeParam === "bulk" || params.get("view") === "bulk";
                if (wantBulk) setContentAiMainView("bulk");
                else if (modeParam === "single") setContentAiMainView("single");
            }
        } catch (_) {}
        clearClusterPrefillStorage();
        return appliedMode;
    };
    window.addEventListener("digiseo:content-ai-prefill", function () {
        void (async () => {
            try {
                setContentAiMainView("single");
            } catch (_) {}
            const applied = await applyClusterPrefillFromSession();
            if (applied) {
                try {
                    const host = byId("caToastHost");
                    if (host) {
                        const el = document.createElement("div");
                        el.className = "ca-toast success";
                        el.textContent = CLUSTER_PREFILL_TOAST;
                        host.appendChild(el);
                        window.setTimeout(() => {
                            el.style.opacity = "0";
                            el.style.transition = "opacity 0.25s";
                            window.setTimeout(() => el.remove(), 280);
                        }, 3200);
                    }
                } catch (_) {}
            }
        })();
    });
    void (async () => {
        const prefillMode = await applyClusterPrefillFromSession();
        if (prefillMode) {
            try {
                const host = byId("caToastHost");
                if (host) {
                    const el = document.createElement("div");
                    el.className = "ca-toast success";
                    el.textContent = CLUSTER_PREFILL_TOAST;
                    host.appendChild(el);
                    window.setTimeout(() => {
                        el.style.opacity = "0";
                        el.style.transition = "opacity 0.25s";
                        window.setTimeout(() => el.remove(), 280);
                    }, 3200);
                }
            } catch (_) {}
            try {
                await refreshProjects(true);
            } catch (_) {}
            return;
        }

        const params = new URLSearchParams(window.location.search || "");
        const articleIdFromUrl = String(params.get("article_id") || "").trim();

        if (articleIdFromUrl) {
            setContentAiMainView("single");
            try {
                await refreshProjects(false);
                await loadProjectIntoWriteTab(articleIdFromUrl);
                try {
                    const u = new URL(window.location.href);
                    u.searchParams.delete("article_id");
                    const qs = u.searchParams.toString();
                    window.history.replaceState({}, "", u.pathname + (qs ? "?" + qs : "") + u.hash);
                } catch (_) {}
            } catch (e) {
                try {
                    msg.textContent = "Không tải được bài viết từ chatbot: " + String(e.message || e);
                } catch (_) {}
            }
            try {
                await refreshProjects(false);
            } catch (_) {}
            return;
        }

        const restored = restoreFormState();
        restoreBulkState();
        try {
            const modeParam = params.get("mode");
            const viewParam = params.get("view");
            const savedJob = localStorage.getItem(BULK_JOB_STORAGE_KEY());
            const lastJob = localStorage.getItem(BULK_LAST_JOB_KEY()) || "";
            const savedView = getSavedBulkMainView();
            if (savedJob) {
                setContentAiMainView("bulk");
                startBulkPoll(savedJob);
            } else if (modeParam === "bulk" || viewParam === "bulk") {
                setContentAiMainView("bulk");
            } else if (modeParam === "autoupdate" || viewParam === "autoupdate") {
                setContentAiMainView("autoupdate");
            } else if (modeParam === "projects" || viewParam === "projects") {
                setContentAiMainView("projects");
            } else if (modeParam === "single") {
                setContentAiMainView("single");
            } else if (savedView) {
                setContentAiMainView(savedView);
            } else {
                setContentAiMainView("single");
            }
            // Re-fetch completed job once so F5 still shows written status.
            if (!savedJob && lastJob) {
                try {
                    const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(lastJob)}?ts=${Date.now()}`, {
                        headers: authHeaders(),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.status === 404) {
                        try {
                            localStorage.removeItem(BULK_LAST_JOB_KEY());
                            localStorage.removeItem(BULK_JOB_STORAGE_KEY());
                        } catch (_) {}
                    } else if (res.ok && data && data.result && Array.isArray(data.result.items) && data.result.items.length) {
                        renderBulkJobItems(data.result.items, { mode: "merge" });
                        if (data.state === "SUCCESS" || data.state === "ERROR") {
                            setContentAiMainView("bulk");
                        }
                    }
                } catch (_) {}
            }
        } catch (_) {
            const savedView = getSavedBulkMainView();
            setContentAiMainView(savedView || "single");
        }
        try {
            await refreshProjects(!restored);
        } catch (_) {}
        try {
            hydrateBulkStatusFromProjects();
        } catch (_) {}
        try {
            refreshPreview();
        } catch (_) {}
        try {
            syncPreviewFallback();
        } catch (_) {}
    })();
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

    if (btnOutlineReference) btnOutlineReference.addEventListener("click", async () => {
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
                headers: authJsonHeaders(),
                body: JSON.stringify({ competitor_url: competitorUrl }),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Không lấy được outline đối thủ.");
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            const current = byId("outlineContent").value.trim();
            byId("outlineContent").value = (data.outline || "").trim();
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
            const res = await fetch(`/content-ai/google-images/search?q=${encodeURIComponent(q)}&num=${encodeURIComponent(String(num))}&ts=${Date.now()}`, {
                headers: authJsonHeaders(),
            });
            let data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error((data && data.detail) ? data.detail : "Tìm ảnh thất bại (kiểm tra GOOGLE_API_KEY + GOOGLE_CSE_ID).");
            if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
            }
            renderGoogleImageResults(data.items || []);
            setHint("google-images", `Đã tìm thấy ${(data.items || []).length} ảnh.`);
            saveFormState();
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

    if (btnReplaceAll) btnReplaceAll.addEventListener("click", () => {
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

    if (btnRefreshOutline) btnRefreshOutline.addEventListener("click", async () => {
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
                headers: authJsonHeaders(),
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

    if (btnCreateContent) btnCreateContent.addEventListener("click", async () => {
        const primaryKeyword = byId("primaryKeyword").value.trim();
        if (!primaryKeyword) {
            msg.textContent = "Cần nhập từ khóa chính trước.";
            return;
        }
        if (btnCreateContent.disabled) return;
        try {
            if (window.ContentAiDuplicate) {
                const dup = await window.ContentAiDuplicate.runSingleCheck({ toast: false });
                if (dup && dup.is_duplicate) {
                    msg.textContent = String(dup.message || "Bài viết này đã tồn tại");
                    return;
                }
            }
        } catch (_) {}
        const writeSignal = _beginContentWriteSession();
        _setCreateContentButtonsBusy(true);
        _clearEditorWriteError();
        _showEditorWriteBar("Đang chuẩn bị viết bài…");
        msg.textContent = "";
        try {
            const ctx = buildContext();
            if (!byId("outlineContent").value.trim()) {
                _showEditorWriteBar("Đang tạo outline…");
                const outlineOut = await fetchSuggestion("outline_content", ctx, { signal: writeSignal, skipConfirm: true });
                if (outlineOut && outlineOut.value) {
                    byId("outlineContent").value = outlineOut.value;
                    autoGrowOutline();
                }
                if (outlineOut && outlineOut.detected_intent) {
                    setDetectedIntentDebug(outlineOut.detected_intent);
                }
            }

            const generated = await streamSuggestion("content", ctx, { signal: writeSignal });
            if (!String(generated || "").trim()) return;

            const postCtx = buildContext();
            const [titleOut, metaOut, slugOut] = await Promise.all([
                fetchSuggestion("title", postCtx, { skipConfirm: true }),
                fetchSuggestion("meta_description", postCtx, { skipConfirm: true }),
                fetchSuggestion("slug", postCtx, { skipConfirm: true }),
            ]);
            if (titleOut && titleOut.detected_intent) {
                setDetectedIntentDebug(titleOut.detected_intent);
            }
            if (titleOut && titleOut.value) {
                byId("title").value = _firstLine(titleOut.value);
            }
            if (metaOut && metaOut.detected_intent) {
                setDetectedIntentDebug(metaOut.detected_intent);
            }
            if (metaOut && metaOut.value) {
                byId("meta").value = _firstLine(metaOut.value);
            }
            if (slugOut && slugOut.detected_intent) {
                setDetectedIntentDebug(slugOut.detected_intent);
            }
            if (slugOut && slugOut.value) {
                byId("slug").value = _firstLine(slugOut.value);
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
            const imgSrc = typeof getAutoInsertImageSource === "function" ? getAutoInsertImageSource() : "google";
            if (newPid && autoImgEl && autoImgEl.checked && imgSrc !== "none") {
                msg.textContent = "Đang tìm và chèn ảnh minh họa vào bài…";
                try {
                    const imgData = await autoInsertImagesForProject(newPid, {
                        force: false,
                        image_source: imgSrc,
                    });
                    const n = Number(imgData.inline_images_count) || 0;
                    msg.textContent =
                        n > 0
                            ? `Đã tạo content và chèn ${n} ảnh vào bài.`
                            : "Đã tạo content; không lấy được ảnh phù hợp.";
                } catch (imgErr) {
                    msg.textContent = `Content xong; không lấy được ảnh phù hợp.`;
                }
            }
            await refreshProjects(true);
            rememberTargetWebsite(byId("targetWebsite").value);
            msg.textContent = `Đã tạo content thành công. Output đang ở chế độ ${getOutputFormat() === "json" ? "JSON" : "chữ thường"}.`;
            showCaToast("Đã tạo content thành công.", "success");
            byId("content").scrollIntoView({ behavior: "smooth", block: "center" });
            saveFormState();
        } catch (e) {
            if (e && e.name === "AbortError") {
                showCaToast("Đã dừng viết.", "info");
                msg.textContent = "Đã dừng viết.";
                saveFormState();
                return;
            }
            msg.textContent = String(e.message || e);
            showCaToast(String(e.message || e), "error");
        } finally {
            if (_contentWriteSession.active) _resetContentWriteUi();
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
                    headers: authJsonHeaders(),
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
                const final = (window.SeoautoAwaitQueued)
                    ? await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() })
                    : data;

                // Fill form fields
                if (final.title) byId("title").value = String(final.title || "");
                if (final.meta_description) byId("meta").value = String(final.meta_description || "");
                if (final.slug) byId("slug").value = String(final.slug || "");
                if (Array.isArray(final.tags)) byId("tags").value = (final.tags || []).join(", ");
                if (final.content_html) setContentValue(String(final.content_html || ""));

                // Put full JSON (incl. schema) into Output
                if (outputFormat) outputFormat.value = "json";
                try { persistOutputFormat(); } catch (_) {}
                out.value = JSON.stringify(final, null, 2);

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
        btnSingleLoadWpCategories.addEventListener("click", () => {
            btnSingleLoadWpCategories.disabled = true;
            void loadSingleWpCategories().finally(() => {
                btnSingleLoadWpCategories.disabled = false;
            });
        });
    }
    if (singleWpCategoryIdEl) {
        singleWpCategoryIdEl.addEventListener("change", () => {
            syncSingleWpCategoryFromSelect();
            saveFormState();
        });
    }

    if (btn) btn.addEventListener("click", async () => {
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

    const _getPublishMode = () => {
        const mode = byId("caPublishStatus");
        return mode && String(mode.value || "draft") === "publish" ? "publish" : "draft";
    };
    if (btnPublishNow) {
        btnPublishNow.addEventListener("click", async () => {
            if (btnPublishNow.disabled) return;
            const cred = await resolveWpPublishCredentialsAsync();
            const wpUrl = cred.wpUrl;
            const wpUsername = cred.username;
            const wpAppPassword = cred.app_password;
            const wpSeoPlugin = cred.seo_plugin;
            const primaryKeyword = byId("primaryKeyword").value.trim();
            const title = byId("title").value.trim();
            const content = getContentValue().trim();
            const publishMode = _getPublishMode();
            if (!wpUrl || !primaryKeyword || !title || !content) {
                const miss = "Vui lòng nhập URL WordPress, từ khóa, tiêu đề và nội dung.";
                if (msg) msg.textContent = miss;
                appendPublishLog(miss);
                return;
            }
            if (!wpUsername || !wpAppPassword) {
                const missCred =
                    "Chưa lấy được username/app password từ site đã lưu. Mở Edit site, kiểm tra đã «Lưu & áp dụng» đủ thông tin trên server, rồi thử lại.";
                if (msg) msg.textContent = missCred;
                appendPublishLog(missCred);
                return;
            }
            if (publishMode === "publish") {
                const ok = window.confirm("Đăng bài ngay (Publish)? Nếu có hẹn giờ tương lai, hệ thống sẽ schedule.");
                if (!ok) return;
            }
            publishLog.value = "";
            appendPublishLog(
                publishMode === "publish"
                    ? "Bắt đầu đăng bài lên WordPress..."
                    : "Bắt đầu đăng bản nháp lên WordPress..."
            );
            if (msg) {
                msg.textContent =
                    publishMode === "publish"
                        ? "Đang đăng bài lên WordPress..."
                        : "Đang đăng bản nháp lên WordPress...";
            }
            const oldPublishText = btnPublishNow.textContent;
            btnPublishNow.disabled = true;
            btnPublishNow.classList.add("loading");
            btnPublishNow.textContent = publishMode === "publish" ? "Đang đăng bài..." : "Đang đăng bản nháp...";
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
                let data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (window.ContentAiUsage && window.ContentAiUsage.handleQuotaResponse(res, data)) {
                        throw new Error("Đã hết quota — vui lòng nâng cấp gói.");
                    }
                    const detail = data && data.detail ? data.detail : {};
                    if (detail && Array.isArray(detail.logs)) {
                        setPublishLogLines(detail.logs);
                    } else if (detail && typeof detail === "string") {
                        appendPublishLog(detail);
                    } else if (detail && typeof detail.message === "string") {
                        appendPublishLog(detail.message);
                    } else {
                        appendPublishLog(JSON.stringify(detail || data));
                    }
                    throw new Error((detail && detail.message) ? detail.message : "Publish thất bại.");
                }
                if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                    appendPublishLog("Đã xếp hàng crawl worker — đang chờ publish…");
                    data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
                }
                if (window.ContentAiUsage && window.ContentAiUsage.refresh) void window.ContentAiUsage.refresh();
                if (Array.isArray(data.logs)) setPublishLogLines(data.logs);
                appendPublishLog(
                    `Thành công: post_id=${data.post_id || ""}, status=${data.status || ""}, link=${data.link || "—"}`
                );
                if (msg) {
                    msg.textContent =
                        publishMode === "publish"
                            ? "Đăng bài thành công lên WordPress."
                            : "Đăng bản nháp thành công lên WordPress.";
                }
                rememberTargetWebsite(byId("targetWebsite").value);
                rememberWpUrl(wpUrl);
                rememberWpUser(wpUsername);
                saveFormState();
            } catch (e) {
                if (msg) msg.textContent = String(e.message || e);
                appendPublishLog(`Lỗi: ${String(e.message || e)}`);
            } finally {
                btnPublishNow.disabled = false;
                btnPublishNow.classList.remove("loading");
                btnPublishNow.textContent = oldPublishText;
            }
        });
    }

    if (btnWpUpdateContent) {
        btnWpUpdateContent.addEventListener("click", async () => {
            const cred = await resolveWpPublishCredentialsAsync();
            const wpUrl = cred.wpUrl;
            const wpUsername = cred.username;
            const wpAppPassword = cred.app_password;
            if (!wpUrl) {
                appendPublishLog("Thiếu WP URL.");
                return;
            }
            if (!wpUsername || !wpAppPassword) {
                appendPublishLog(
                    "Chưa lấy được username/app password từ site đã lưu — mở Edit / Thêm site đăng bài và «Lưu & áp dụng»."
                );
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
                    headers: authJsonHeaders(),
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
        const onWpUrlSiteChange = () => {
            rememberWpUrl(wpUrlEl.value);
            fillWpCredentialsFromSavedProfile();
            schedulePublishWpCategoriesLoad();
        };
        wpUrlEl.addEventListener("blur", onWpUrlSiteChange);
        wpUrlEl.addEventListener("change", onWpUrlSiteChange);
        wpUrlEl.addEventListener("input", schedulePublishWpCategoriesLoad);
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
        const hintLib = byId("hint-custom-link-library");
        if (hintLib) {
            hintLib.textContent = scope.ok
                ? `Thư viện riêng cho ${scope.type === "project" ? "dự án" : "site"} «${scope.label}» — không hiện link của dự án/site khác.`
                : "Mở một dự án hoặc nhập Target website để lưu / xem thư viện custom link.";
        }
        if (btnSaveCustomToLibrary) {
            btnSaveCustomToLibrary.disabled = !scope.ok;
            btnSaveCustomToLibrary.title = scope.ok
                ? `Lưu vào thư viện của ${scope.label}`
                : "Cần dự án hoặc Target website";
        }
        const lib = loadCustomLinkLibrary();
        customLinkLibraryList.innerHTML = "";
        if (!scope.ok) {
            customLinkLibraryList.innerHTML =
                "<div class=\"hint\">Chưa gắn dự án hoặc Target website. Mở dự án (ví dụ backlinkbrand) rồi mới lưu link money page cho đúng bài.</div>";
            return;
        }
        if (!lib.length) {
            customLinkLibraryList.innerHTML =
                "<div class=\"hint\">Thêm custom link rồi bấm «Lưu dòng đã chọn vào thư viện».</div>";
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
        row.querySelector(".cl-del")?.addEventListener("click", () => {
            row.remove();
            syncIlSelectedPanel();
        });
        row.addEventListener("input", () => syncIlSelectedPanel());
        row.addEventListener("change", () => syncIlSelectedPanel());
        customLinkRows.appendChild(row);
        syncIlSelectedPanel();
    };
    const collectCheckedCustomLinks = () => {
        const root = byId("internalLinkPanel") || getCustomLinkRowsEl();
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
    const escapeHtml = (s) => String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    let _ilContentBeforeApply = "";
    const showIlInsertSummary = (text, { warn = false } = {}) => {
        const box = byId("ilInsertSummary");
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
        const statsEl = byId("ilInsertedStatsText");
        if (statsEl) statsEl.textContent = msg;
    };
    const switchIlToInsertedTab = () => {
        const root = byId("internalLinkPanel");
        if (root && window.__caSwitchModalTab) window.__caSwitchModalTab(root, 2);
    };
    const syncIlSelectedPanel = () => {
        const host = byId("ilSelectedLinks");
        if (!host) return;
        const wp = collectWpInternalChecked();
        const custom = getValidCustomLinksForApply();
        const chips = [];
        wp.forEach((p) => {
            chips.push({ label: p.anchor_text || p.title, sub: p.link });
        });
        custom.forEach((p) => {
            chips.push({ label: p.anchor_text, sub: p.target_url });
        });
        if (!chips.length) {
            host.innerHTML = '<p class="ca-il-empty">Chưa chọn link — tick gợi ý hoặc thêm custom link.</p>';
            return;
        }
        host.innerHTML = "";
        chips.forEach((c) => {
            const row = document.createElement("div");
            row.className = "ca-il-selected-chip";
            row.innerHTML = `<strong>${escapeHtml(c.label)}</strong><span class="hint">${escapeHtml(c.sub)}</span>`;
            host.appendChild(row);
        });
    };
    const _inferIlH2Hint = () => {
        const html = String(getContentValue() || "");
        const m = html.match(/<h2\b[^>]*>(.*?)<\/h2>/i);
        if (!m) return "Tự động theo mục H2 gần anchor";
        return String(m[1] || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 80) || "Tự động theo H2";
    };
    const _getInternalRowEl = (idx) =>
        document.querySelector(`.ca-il-card[data-idx="${idx}"], tr[data-idx="${idx}"]`);
    const renderInternalApplyResults = (rows) => {
        if (!internalLinkApplyResults) return;
        const arr = Array.isArray(rows) ? rows : [];
        if (!arr.length) {
            internalLinkApplyResults.style.display = "none";
            internalLinkApplyResults.innerHTML = "";
            return;
        }
        internalLinkApplyResults.style.display = "block";
        internalLinkApplyResults.innerHTML = "";
        arr.forEach((r) => {
            const st = String(r.status || "");
            const row = document.createElement("div");
            row.className = "ca-il-result-row";
            const ok = st === "inserted";
            row.innerHTML = `
                <span class="il-row-circle ${ok ? "il-done" : ""}">${ok ? "✓" : "·"}</span>
                <div>
                    <strong>${escapeHtml(String(r.anchor_text || ""))}</strong>
                    <div class="hint" style="word-break:break-all;">${escapeHtml(String(r.target_url || ""))}</div>
                    ${r.reason ? `<div class="hint">${escapeHtml(String(r.reason))}</div>` : ""}
                </div>
            `;
            internalLinkApplyResults.appendChild(row);
        });
        const inserted = arr.filter((r) => String(r.status) === "inserted").length;
        showIlInsertSummary(
            inserted
                ? `Đã chèn ${inserted} link vào bài. Kiểm tra editor bên trái.`
                : "Không chèn được link nào — xem chi tiết bên dưới.",
            { warn: !inserted }
        );
    };
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
    const _mountIlAdvancedLlm = () => {
        const slot = byId("ilAdvancedLlmSlot");
        if (!slot || slot.dataset.mounted) return;
        slot.dataset.mounted = "1";
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
        llmTxt.textContent = "Dùng LLM khi rule không chèn được anchor";
        llmLbl.appendChild(llmInp);
        llmLbl.appendChild(llmTrack);
        llmLbl.appendChild(llmTxt);
        llmInp.addEventListener("change", () => {
            setInternalLinkUseLlm(llmInp.checked);
            llmLbl.classList.toggle("is-on", llmInp.checked);
        });
        slot.appendChild(llmLbl);
    };
    const renderInternalCandidates = (items) => {
        if (!internalLinkCandidates) return;
        internalLinkCandidates.innerHTML = "";
        _mountIlAdvancedLlm();
        const arr = Array.isArray(items) ? items : [];
        const hintIl = byId("hint-internal-links");
        if (hintIl) {
            hintIl.textContent = arr.length
                ? `${arr.length} gợi ý — chọn card và bấm «Chèn link vào bài».`
                : "Bấm «Tìm bài liên quan» khi đã có Target website.";
        }
        if (!arr.length) {
            internalLinkCandidates.innerHTML = '<p class="ca-il-empty">Không tìm thấy bài liên quan. Thử thêm từ khóa phụ hoặc nội dung liên quan trong bài.</p>';
            syncIlSelectedPanel();
            return;
        }
        const ptLabels = {
            money_page: "Money page",
            service: "Dịch vụ",
            pillar: "Pillar",
            course: "Khóa học",
            blog: "Blog",
            category: "Danh mục",
        };
        arr.forEach((it, idx) => {
            const displayTitle = String(it.title || "").trim()
                || String(it.slug || "").replace(/-/g, " ").trim()
                || String(it.link || "").trim()
                || `Bài liên quan #${idx + 1}`;
            const card = document.createElement("article");
            card.className = "ca-il-card";
            card.setAttribute("data-idx", String(idx));
            card.setAttribute("role", "listitem");
            const anchorDefault =
                String(it.suggested_anchor || it.anchor_text || it.target_primary_keyword || it.kw_hint_primary || "").trim() ||
                String(it.title || "").trim().split("|")[0].trim();
            const rel = Number(it.relevance_score);
            const relCls = rel >= 80 ? "high" : rel >= 60 ? "med" : "low";
            const pt = String(it.page_type || "").trim();
            const url = String(it.link || "");
            const shortUrl = url.length > 48 ? url.slice(0, 46) + "…" : url;
            card.innerHTML = `
                <div class="ca-il-card-head">
                    <input type="checkbox" class="internal-link-cb ca-il-card-check" data-idx="${idx}" checked aria-label="Chọn link" />
                    <div class="ca-il-card-title">${escapeHtml(displayTitle)}</div>
                    ${Number.isFinite(rel) ? `<span class="ca-il-relevance ${relCls}">${rel}%</span>` : ""}
                    <span class="il-row-circle il-row-status content-ai-aux-hidden" data-idx="${idx}" aria-hidden="true"></span>
                </div>
                <div class="ca-il-card-url" title="${escapeHtml(url)}">${escapeHtml(shortUrl)}</div>
                <div class="ca-il-card-field">
                    <input type="text" class="internal-link-anchor-input" data-idx="${idx}" placeholder="Anchor đề xuất" value="${escapeHtml(anchorDefault.slice(0, 120))}" />
                </div>
                <div class="ca-il-card-actions">
                    <button type="button" class="mini-btn ca-il-btn-edit" data-idx="${idx}">Sửa anchor</button>
                </div>
            `;
            const cb = card.querySelector(".internal-link-cb");
            if (cb) {
                cb.addEventListener("change", () => {
                    card.classList.toggle("is-selected", cb.checked);
                    syncIlSelectedPanel();
                    scheduleSaveFormState();
                });
            }
            card.querySelector(".ca-il-btn-edit")?.addEventListener("click", (ev) => {
                ev.preventDefault();
                const inp = card.querySelector(".internal-link-anchor-input");
                if (inp) inp.focus({ preventScroll: true });
            });
            if (cb && cb.checked) card.classList.add("is-selected");
            internalLinkCandidates.appendChild(card);
        });
        syncIlSelectedPanel();
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
                    headers: authJsonHeaders(),
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
                let data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    throw new Error(parseApiDetail(data) || "Không tìm được bài liên quan.");
                }
                if (window.SeoautoAwaitQueued && data.job_id && data.poll_url) {
                    data = await window.SeoautoAwaitQueued(data, { headers: authJsonHeaders() });
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
            setHint(
                "internal-links",
                `Đã khôi phục ${_internalCandidates.length} bài liên quan (lưu trên trình duyệt). Tick → «Đi link» để chèn.`
            );
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
                syncIlSelectedPanel();
            }
        });
    }
    const btnIlUndo = byId("btnIlUndo");
    if (btnIlUndo && !btnIlUndo.dataset.bound) {
        btnIlUndo.dataset.bound = "1";
        btnIlUndo.addEventListener("click", (e) => {
            e.preventDefault();
            if (!_ilContentBeforeApply) return;
            setContentValue(_ilContentBeforeApply);
            _ilContentBeforeApply = "";
            refreshPreview();
            saveFormState();
            btnIlUndo.hidden = true;
            showIlInsertSummary("Đã hoàn tác — khôi phục nội dung trước khi chèn link.");
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
        const row = _getInternalRowEl(idx);
        if (!row) return null;
        return row.querySelector(".il-row-circle");
    };

    const setInternalRowCircleState = (idx, state) => {
        const row = _getInternalRowEl(idx);
        const circle = getInternalRowCircle(idx);
        if (!row || !circle) return;
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
            row.classList.add("il-row-applied");
            circle.classList.add("il-done");
            circle.textContent = "✓";
            circle.title = "Đã chèn internal link";
            const cb = row.querySelector(".internal-link-cb");
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
            headers: authJsonHeaders(),
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
        const row = _getInternalRowEl(idx);
        if (row && row.classList.contains("il-row-applied")) {
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
                if (!_ilContentBeforeApply) _ilContentBeforeApply = getContentValue();
                setContentValue(outHtml);
                refreshPreview();
                saveFormState();
                const undoBtn = byId("btnIlUndo");
                if (undoBtn) undoBtn.hidden = false;
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
            const row = _getInternalRowEl(idx);
            return row && !row.classList.contains("il-row-applied");
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
        if (okCount > 0) {
            showIlInsertSummary(summary);
            switchIlToInsertedTab();
        }
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
            if (!_ilContentBeforeApply) _ilContentBeforeApply = cur;
            setContentValue(outHtml);
            refreshPreview();
            saveFormState();
            const undoBtn = byId("btnIlUndo");
            if (undoBtn) undoBtn.hidden = false;
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
            if (ins > 0) {
                showIlInsertSummary(msgHint);
                switchIlToInsertedTab();
            }
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

    const showCaToast = (message, type) => {
        const host = byId("caToastHost");
        if (!host) return;
        const el = document.createElement("div");
        el.className = "ca-toast " + (type || "info");
        el.textContent = String(message || "");
        host.appendChild(el);
        window.setTimeout(() => {
            el.style.opacity = "0";
            el.style.transition = "opacity 0.25s";
            window.setTimeout(() => el.remove(), 280);
        }, 3200);
    };
    window.showCaToast = showCaToast;
    const _usageLabels = {
        content_ai_article: "Bài viết AI",
        content_ai_brief: "Content Brief",
        image_generate: "Ảnh AI",
        content_ai_bulk_article: "Bulk job",
        wp_publish: "WordPress Publish",
    };
    /* usage widget: static/js/content_ai/content-ai-usage.js */

    const caStickyCreate = byId("caStickyCreateContent");
    const caStickyDraft = byId("caStickyDraft");
    const caStickyPublish = byId("caStickyPublish");
    if (caStickyCreate && btnCreateContent) {
        caStickyCreate.addEventListener("click", () => btnCreateContent.click());
    }
    if (caStickyDraft && btn) {
        caStickyDraft.addEventListener("click", () => btn.click());
    }
    if (caStickyPublish && btnPublishNow) {
        caStickyPublish.addEventListener("click", () => btnPublishNow.click());
    }
    const pubCatPublish = byId("singleWpCategoryIdPublish");
    if (pubCatPublish) {
        pubCatPublish.addEventListener("change", syncSingleWpCategoryFromSelect);
    }
    const btnSeoRefresh = byId("btnSeoRefreshChecklist");
    if (btnSeoRefresh) btnSeoRefresh.addEventListener("click", () => void refreshPublishChecklist());
    if (typeof window.__caSeoAutofix !== "undefined" && window.__caSeoAutofix.init) {
        window.__caSeoAutofix.init();
    }
    const btnSeoScrollPublish = byId("btnSeoScrollPublish");
    if (btnSeoScrollPublish) {
        btnSeoScrollPublish.addEventListener("click", () => {
            if (typeof window.__caCloseSeoScorePanel === "function") window.__caCloseSeoScorePanel();
            if (typeof window.__caOpenStepModal === "function") {
                window.__caOpenStepModal("publish");
            } else {
                const el = byId("contentAiPublishBar");
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    }

    if (btnResetForm) btnResetForm.addEventListener("click", async () => {
        try {
            const view = String(_contentAiMainView || "single");
            if (view === "projects" || view === "autoupdate") {
                const hint =
                    "Chuyển sang tab «Viết 1 bài» hoặc «Viết hàng loạt» rồi bấm Làm mới để xóa nhập liệu tab đó.";
                if (msg) msg.textContent = hint;
                showCaToast(hint, "info");
                return;
            }
            const isBulk = view === "bulk";
            const ok = window.confirm(
                isBulk
                    ? "Bạn có chắc muốn làm mới tab «Viết hàng loạt»? Danh sách từ khóa và form bulk (kể cả bản nháp trên trình duyệt) sẽ bị xóa."
                    : "Bạn có chắc muốn làm mới tab «Viết 1 bài»? Toàn bộ ô nhập và bản nháp trên trình duyệt của tab này sẽ bị xóa."
            );
            if (!ok) return;
            if (isBulk) {
                resetBulkWriteForm();
                scheduleSaveBulkState();
                if (msg) msg.textContent = "Đã làm mới tab «Viết hàng loạt».";
                showCaToast("Đã làm mới form Viết hàng loạt.", "success");
            } else {
                resetContentAiSingleForm();
                try {
                    await refreshProjects(true);
                } catch (_) {}
                if (msg) msg.textContent = "Đã làm mới tab «Viết 1 bài».";
                showCaToast("Đã làm mới form Viết 1 bài.", "success");
            }
        } catch (e) {
            showCaToast(String((e && e.message) || "Không thể làm mới form."), "error");
        }
    });

    window.ContentAiShared = {
        byId: byId,
        apiFetch: apiFetch,
        authJsonHeaders: authJsonHeaders,
        getAuthToken: getAuthToken,
        userStorageKey: userStorageKey,
        normalizeTargetBase: typeof normalizeTargetBase === "function" ? normalizeTargetBase : null,
    };
})();
