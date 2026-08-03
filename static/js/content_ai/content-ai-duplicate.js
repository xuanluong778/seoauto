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
