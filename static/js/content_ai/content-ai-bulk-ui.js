/**
 * Content AI — Bulk write tab UI (SaaS layout).
 * Depends on ContentAiBulkCore from content-ai-app.js (same page, load after app).
 */
(function () {
    "use strict";

    const STATUS = {
        draft: { label: "Chưa viết", cls: "st-draft" },
        setup: { label: "Đã cấu hình", cls: "st-setup" },
        pending: { label: "Đang chờ", cls: "st-pending" },
        running: { label: "Đang viết", cls: "st-run" },
        cancelled: { label: "Đã dừng", cls: "st-pending" },
        written: { label: "Đã viết", cls: "st-ok" },
        success: { label: "Đã viết", cls: "st-ok" },
        error: { label: "Lỗi", cls: "st-err" },
        img_none: { label: "Chưa có ảnh", cls: "st-img-none" },
        img_loading: { label: "Đang lấy ảnh", cls: "st-img-load" },
        img_ok: { label: "Đã có ảnh", cls: "st-img-ok" },
        img_error: { label: "Lỗi ảnh", cls: "st-img-err" },
        img_bad_format: { label: "Ảnh sai định dạng", cls: "st-img-fmt" },
        img_too_large: { label: "Ảnh quá 200KB", cls: "st-img-size" },
        scheduled: { label: "Đã đặt lịch", cls: "st-sched" },
        unpublished: { label: "Chưa đăng", cls: "st-draft" },
        published: { label: "Đã đăng", cls: "st-pub" },
        seo_pass: { label: "Đạt", cls: "st-ok" },
        seo_review: { label: "Cần kiểm tra", cls: "st-warn" },
        seo_pending: { label: "—", cls: "st-pending" },
        wc_ok: { label: "Đạt ±10%", cls: "st-ok" },
        wc_short: { label: "Thiếu từ", cls: "st-warn" },
        wc_long: { label: "Thừa từ", cls: "st-warn" },
        wc_pending: { label: "—", cls: "st-pending" },
        llm_ok: { label: "OK", cls: "st-ok" },
        llm_running: { label: "Đang viết", cls: "st-run" },
        llm_error: { label: "Lỗi", cls: "st-err" },
        llm_pending: { label: "Chưa chạy", cls: "st-pending" },
        badge_ok: { label: "Thành công", cls: "st-ok" },
        badge_running: { label: "Đang viết", cls: "st-run" },
        badge_review: { label: "Cần kiểm tra", cls: "st-warn" },
        badge_llm: { label: "Lỗi", cls: "st-err" },
        badge_wc: { label: "Sai số từ", cls: "st-warn" },
        badge_seo: { label: "SEO thấp", cls: "st-warn" },
        badge_empty: { label: "Content rỗng", cls: "st-err" },
    };

    const WC_TOL_MIN = 0.9;
    const WC_TOL_MAX = 1.1;
    const SEO_PASS_SCORE = 75;

    let _jobItems = [];
    let _selected = new Set();
    let _activeStep = "import";
    let _drawerRowId = null;
    /** @type {Record<string, object>} project_id -> schedule row from server */
    let _scheduleByProject = Object.create(null);
    /** @type {Record<string, object>} project_id -> full project payload */
    let _projectById = Object.create(null);
    /** @type {Record<string, object>} project_id -> image status payload from API */
    let _imageMetaByProject = Object.create(null);
    /** @type {Set<string>} project_ids currently fetching images */
    const _imageLoading = new Set();
    /** @type {Record<string, string>} project_id -> last fetch error message */
    const _imageErrors = Object.create(null);
    let _editorImageProjectId = "";
    let _editorRowId = "";

    function readAuthToken() {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
        } catch (_) {}
        return "";
    }

    function authHeaders(extra) {
        const h = { ...(extra || {}) };
        const t = readAuthToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function authJsonHeaders() {
        return authHeaders({ "Content-Type": "application/json" });
    }

    function parseApiError(data, fallback) {
        const d = data && data.detail;
        if (typeof d === "string") return d;
        if (d && typeof d.message === "string") return d.message;
        return fallback || "Lỗi API";
    }

    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: "POST",
            headers: authJsonHeaders(),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(parseApiError(data, `HTTP ${res.status}`));
        return data;
    }

    async function apiGet(path) {
        const res = await fetch(path, { headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(parseApiError(data, `HTTP ${res.status}`));
        return data;
    }

    function normSiteUrl(u) {
        return String(u || "")
            .trim()
            .replace(/\/+$/, "")
            .toLowerCase();
    }

    async function resolveWpPayload() {
        const tw = byId("bulkTargetWebsite") && byId("bulkTargetWebsite").value.trim();
        const data = await apiGet("/api/settings/publishing-sites?ts=" + Date.now());
        const sites = (data && (data.items || data.sites)) || [];
        const wpSites = sites.filter((s) => String(s.platform || "").toLowerCase() === "wordpress");
        if (!wpSites.length) {
            throw new Error("Chưa có site WordPress — thêm trong Cài đặt → Site đăng bài.");
        }
        let hit = null;
        if (tw) {
            const n = normSiteUrl(tw);
            hit = wpSites.find((s) => normSiteUrl(s.url) === n);
        }
        if (!hit) hit = wpSites[0];
        return { wp_site_id: hit.id, wp_url: hit.url };
    }

    function getSelectedProjectIds(opts) {
        const allowBroken = !!(opts && opts.allowBroken);
        const c = core();
        const kws = new Set(getSelectedKeywords().map((k) => String(k).trim().toLowerCase()));
        const jobs = c && c.getJobItems ? c.getJobItems() : _jobItems;
        const ids = [];
        const seen = new Set();
        (jobs || []).forEach((j) => {
            let pid = String(j.project_id || "").trim();
            const kw = String(j.keyword || "").trim().toLowerCase();
            if (!pid && kw) pid = resolveProjectIdForKeyword(j.keyword);
            if (!pid || !kws.has(kw) || seen.has(pid)) return;
            if (!allowBroken && !isJobPublishable(j, _projectById[pid] || null)) return;
            seen.add(pid);
            ids.push(pid);
        });
        if (!ids.length && allowBroken) {
            getSelectedKeywords().forEach((kwRaw) => {
                const pid = resolveProjectIdForKeyword(kwRaw);
                if (pid && !seen.has(pid)) {
                    seen.add(pid);
                    ids.push(pid);
                }
            });
        }
        return ids;
    }

    function resolveProjectIdForKeyword(keyword) {
        const kw = String(keyword || "").trim().toLowerCase();
        if (!kw) return "";
        const job = (_jobItems || []).find((x) => String(x.keyword || "").trim().toLowerCase() === kw);
        const fromJob = job && job.project_id ? String(job.project_id).trim() : "";
        if (fromJob) return fromJob;
        try {
            if (typeof allProjects !== "undefined" && Array.isArray(allProjects)) {
                const hit = allProjects.find(
                    (p) => String((p && p.primary_keyword) || "").trim().toLowerCase() === kw
                );
                if (hit && hit.id) return String(hit.id).trim();
            }
        } catch (_) {}
        return "";
    }

    function getAllWrittenProjectIds(opts) {
        const allowBroken = !!(opts && opts.allowBroken);
        const jobs = (core() && core().getJobItems ? core().getJobItems() : _jobItems) || [];
        const ids = [];
        const seen = new Set();
        jobs.forEach((j) => {
            const pid = String(j.project_id || "").trim();
            if (!pid || seen.has(pid)) return;
            if (!allowBroken && !isJobPublishable(j, _projectById[pid] || null)) return;
            seen.add(pid);
            ids.push(pid);
        });
        const rows = (core() && core().getRows ? core().getRows() : []) || [];
        rows.forEach((row) => {
            const pid = resolveProjectIdForKeyword(row && row.keyword);
            if (!pid || seen.has(pid)) return;
            const job = findJobItem(row.keyword);
            if (!allowBroken && job && !isJobPublishable(job, _projectById[pid] || null)) return;
            seen.add(pid);
            ids.push(pid);
        });
        return ids;
    }

    function stripHtmlText(html) {
        return String(html || "")
            .replace(/<[^>]+>/g, " ")
            .replace(/\s+/g, " ")
            .trim();
    }

    function resolveTargetWc(row, job) {
        if (job && job.target_word_count != null && job.target_word_count !== "") {
            const n = parseInt(job.target_word_count, 10);
            if (n >= 200) return n;
        }
        if (row && row.target_word_count != null && String(row.target_word_count).trim()) {
            const raw = String(row.target_word_count).trim().toLowerCase();
            if (raw && raw !== "auto") {
                const n = parseInt(raw, 10);
                if (n >= 200) return n;
            }
        }
        const proj =
            job && job.project_id ? _projectById[String(job.project_id)] : null;
        if (proj && proj.target_word_count) {
            const n = parseInt(proj.target_word_count, 10);
            if (n >= 200) return n;
        }
        return null;
    }

    function formatTargetWcLabel(row, job) {
        const n = resolveTargetWc(row, job);
        return n != null ? String(n) : "AI tự phân phối";
    }

    function resolveActualWc(row, job) {
        if (job && job.actual_word_count != null) {
            const n = parseInt(job.actual_word_count, 10);
            if (!Number.isNaN(n)) return n;
        }
        if (job && job.word_count != null) {
            const n = parseInt(job.word_count, 10);
            if (!Number.isNaN(n)) return n;
        }
        const proj =
            job && job.project_id ? _projectById[String(job.project_id)] : null;
        if (proj) {
            if (proj.actual_word_count != null) {
                const n = parseInt(proj.actual_word_count, 10);
                if (!Number.isNaN(n)) return n;
            }
            if (proj.word_count != null) {
                const n = parseInt(proj.word_count, 10);
                if (!Number.isNaN(n)) return n;
            }
            const fromHtml = stripHtmlText(proj.content || "").split(/\s+/).filter(Boolean).length;
            if (fromHtml) return fromHtml;
        }
        return null;
    }

    function resolveWcStatus(actual, target, job) {
        if (job && job.word_count_status) {
            const s = String(job.word_count_status).toLowerCase();
            if (s === "ok" || s === "short" || s === "long") return s;
        }
        if (actual == null || target == null || target < 200) return "pending";
        if (actual < target * WC_TOL_MIN) return "short";
        if (actual > target * WC_TOL_MAX) return "long";
        return "ok";
    }

    function resolveContentHtml(job) {
        const proj =
            job && job.project_id ? _projectById[String(job.project_id)] : null;
        if (proj && proj.content) return String(proj.content);
        if (job && job.content) return String(job.content);
        return "";
    }

    function isLiveBulkWrite() {
        const stop = byId("btnBulkWriteStopPoll");
        if (stop && !stop.disabled) return true;
        const start = byId("btnBulkWriteStart");
        return !!(start && start.getAttribute("aria-busy") === "true");
    }

    function jobLooksWritten(row, job) {
        const wc = resolveActualWc(row, job);
        if (wc != null && wc >= 40) return true;
        if (stripHtmlText(resolveContentHtml(job)).length >= 40) return true;
        try {
            if (typeof allProjects !== "undefined" && Array.isArray(allProjects)) {
                const kw = String((row && row.keyword) || (job && job.keyword) || "")
                    .trim()
                    .toLowerCase();
                const hit = allProjects.find(
                    (p) => String((p && p.primary_keyword) || "").trim().toLowerCase() === kw
                );
                if (hit) {
                    const pwc = parseInt(hit.actual_word_count || hit.word_count || 0, 10);
                    if (!Number.isNaN(pwc) && pwc >= 40) return true;
                    if (stripHtmlText(hit.content || "").length >= 40) return true;
                    const pst = String(hit.status || "").toLowerCase();
                    if (pst === "ready" || pst === "published") return true;
                }
            }
        } catch (_) {}
        return false;
    }

    function reconcileJobItem(row, job) {
        if (!job) return job;
        const out = { ...job };
        const pid =
            String(out.project_id || "").trim() ||
            resolveProjectIdForKeyword((row && row.keyword) || out.keyword);
        if (pid) out.project_id = pid;
        const st = String(out.status || "").toLowerCase();
        if (st === "error" || st === "success") return out;
        // Keep spinner on the row currently being written; do not reset already-written rows.
        if (st === "running" && isLiveBulkWrite()) {
            return out;
        }
        if (!jobLooksWritten(row, out)) return out;
        out.status = "success";
        if (out.word_count == null && out.actual_word_count == null) {
            const n = resolveActualWc(row, out);
            if (n != null) out.word_count = n;
        }
        return out;
    }

    function reconcileAllJobItems() {
        const rows = (core() && core().getRows ? core().getRows() : []) || [];
        const byKw = Object.create(null);
        rows.forEach((r) => {
            const kw = String((r && r.keyword) || "").trim().toLowerCase();
            if (kw) byKw[kw] = r;
        });
        _jobItems = (_jobItems || []).map((j) => {
            const kw = String((j && j.keyword) || "").trim().toLowerCase();
            return reconcileJobItem(byKw[kw] || { keyword: j && j.keyword }, j);
        });
    }

    function isContentEmpty(job) {
        if (!job || job.status !== "success") return true;
        const html = resolveContentHtml(job);
        return stripHtmlText(html).length < 40;
    }

    function isLlmError(job) {
        return !!(job && String(job.status || "") === "error");
    }

    function isWordCountBad(row, job) {
        if (!job || job.status !== "success") return false;
        const st = resolveWcStatus(resolveActualWc(row, job), resolveTargetWc(row, job), job);
        return st === "short" || st === "long";
    }

    function isSeoLow(job) {
        if (!job || job.status !== "success") return false;
        const score = job.seo_score != null ? Number(job.seo_score) : null;
        const st = String(job.seo_status || "").toLowerCase();
        if (st === "needs_review") return true;
        if (score != null && !Number.isNaN(score) && score < SEO_PASS_SCORE) return true;
        return false;
    }

    function isJobPublishable(job, project) {
        if (!job || String(job.status || "") !== "success") return false;
        if (isLlmError(job)) return false;
        const html =
            (project && project.content) ||
            (job && job.content) ||
            resolveContentHtml(job);
        return stripHtmlText(html).length >= 40;
    }

    function rowLlmStatus(job, row) {
        const j = job || { keyword: row && row.keyword, status: "pending" };
        const st = String(j.status || "pending");
        if (st === "error") return "llm_error";
        if (st === "running") return "llm_running";
        if (st === "success" || st === "written" || st === "ok") return "llm_ok";
        if (jobLooksWritten(row || { keyword: j.keyword }, j)) return "llm_ok";
        return "llm_pending";
    }

    function rowWcStatusKey(row, job) {
        if (!job || job.status !== "success") return "wc_pending";
        const st = resolveWcStatus(resolveActualWc(row, job), resolveTargetWc(row, job), job);
        if (st === "ok") return "wc_ok";
        if (st === "short") return "wc_short";
        if (st === "long") return "wc_long";
        return "wc_pending";
    }

    function rowBadges(row, job) {
        if (!job) {
            if (jobLooksWritten(row, { keyword: row && row.keyword })) return [pill("badge_ok")];
            return [pill("badge_review")];
        }
        if (isLlmError(job)) return [pillWithError("badge_llm", job)];
        if (job.status !== "success") {
            if (job.status === "running") return [pill("badge_running")];
            if (jobLooksWritten(row, job)) return [pill("badge_ok")];
            return [pill("badge_review")];
        }
        const badges = [];
        if (isContentEmpty(job)) badges.push(pill("badge_empty"));
        if (isWordCountBad(row, job)) badges.push(pill("badge_wc"));
        if (isSeoLow(job)) badges.push(pill("badge_seo"));
        if (!badges.length) badges.push(pill("badge_ok"));
        else if (!isContentEmpty(job)) badges.unshift(pill("badge_review"));
        return badges;
    }

    async function loadServerSchedules() {
        try {
            const c = core();
            const jobId = c && c.getBulkJobId ? c.getBulkJobId() : "";
            const q = jobId
                ? `/content-ai/bulk-publish/schedules?bulk_job_id=${encodeURIComponent(jobId)}&limit=500`
                : "/content-ai/bulk-publish/schedules?limit=500";
            const data = await apiGet(q + "&ts=" + Date.now());
            _scheduleByProject = Object.create(null);
            ((data && data.items) || []).forEach((it) => {
                if (it && it.project_id) _scheduleByProject[it.project_id] = it;
            });
        } catch (_) {
            /* keep previous cache on transient errors */
        }
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function core() {
        return window.ContentAiBulkCore || null;
    }

    function isSetupComplete(row) {
        if (!row) return false;
        const c = core();
        if (c && typeof c.isItemSetupComplete === "function" && typeof c.rowToApiItem === "function") {
            try {
                return !!c.isItemSetupComplete(c.rowToApiItem(row));
            } catch (_) {}
        }
        const title = String(row.custom_title || "").trim();
        const desc = String(row.custom_description || "").trim();
        const outline = String(row.custom_outline || "").trim();
        const rawWc = String(row.target_word_count ?? "").trim().toLowerCase();
        const wcOk = !rawWc || rawWc === "auto" || parseInt(rawWc, 10) >= 200;
        return !!(title && desc && outline && wcOk);
    }

    function rowContentStatus(row, jobItem) {
        if (jobItem) {
            const st = String(jobItem.status || "pending");
            if (st === "success") return "written";
            if (st === "error") return "error";
            if (st === "running") return "running";
            if (st === "cancelled") return "draft";
            return "pending";
        }
        if (isSetupComplete(row)) return "setup";
        return "draft";
    }

    function classifyImageError(msg) {
        const t = String(msg || "").toLowerCase();
        if (/định dạng|format|jpg|webp|jpeg|png|gif/.test(t) && /sai|không|invalid|unsupported/.test(t)) {
            return "img_bad_format";
        }
        if (/200\s*kb|quá lớn|too large|vượt/.test(t)) return "img_too_large";
        return "img_error";
    }

    function mapServerImageStatus(item) {
        if (!item) return "img_none";
        const st = String(item.status || "none");
        if (st === "ok") return "img_ok";
        if (st === "bad_format") return "img_bad_format";
        if (st === "too_large") return "img_too_large";
        return "img_none";
    }

    async function loadImageStatuses(projectIds) {
        const ids = [...new Set((projectIds || []).map((x) => String(x || "").trim()).filter(Boolean))];
        if (!ids.length) return;
        try {
            const data = await apiGet(
                "/content-ai/bulk-images/status?project_ids=" + encodeURIComponent(ids.join(",")) + "&ts=" + Date.now()
            );
            ((data && data.items) || []).forEach((it) => {
                if (!it || !it.project_id) return;
                _imageMetaByProject[it.project_id] = it;
                delete _imageErrors[it.project_id];
            });
        } catch (e) {
            /* keep cached meta on transient errors */
        }
    }

    function rowImageStatus(row, jobItem) {
        const pid = jobItem && jobItem.project_id ? String(jobItem.project_id) : "";
        if (pid && _imageLoading.has(pid)) return "img_loading";
        if (pid && _imageErrors[pid]) return classifyImageError(_imageErrors[pid]);
        if (pid && _imageMetaByProject[pid]) return mapServerImageStatus(_imageMetaByProject[pid]);
        if (jobItem && jobItem.status === "success") return "img_none";
        return "img_none";
    }

    function rowPublishStatus(row, jobItem) {
        const pid = jobItem && jobItem.project_id ? String(jobItem.project_id) : "";
        const sched = pid ? _scheduleByProject[pid] : null;
        if (sched) {
            const st = String(sched.status || "").toLowerCase();
            if (st === "published") return "published";
            if (st === "scheduled" || st === "publishing") return "scheduled";
            if (st === "failed") return "error";
        }
        if (jobItem && jobItem.published) return "published";
        const proj = pid ? _projectById[pid] : null;
        const wpSt = String((proj && (proj.wp_publish_status || proj.publish_status || proj.status)) || "").toLowerCase();
        if (wpSt === "publish" || wpSt === "published") return "published";
        return "unpublished";
    }

    function rowSchedule(row, jobItem) {
        const pid = jobItem && jobItem.project_id ? String(jobItem.project_id) : "";
        const sched = pid ? _scheduleByProject[pid] : null;
        if (sched && sched.scheduled_at) return String(sched.scheduled_at);
        return row && row.scheduled_at ? row.scheduled_at : "";
    }

    function pill(key) {
        const m = STATUS[key] || { label: key, cls: "st-pending" };
        return `<span class="bulk-v2-pill ${m.cls}">${esc(m.label)}</span>`;
    }

    function truncate(s, n) {
        const t = String(s || "").trim();
        if (!t) return "—";
        return t.length > n ? t.slice(0, n - 1) + "…" : t;
    }

    function jobErrorMessage(job) {
        if (!job || String(job.status || "") !== "error") return "";
        return String(job.error || job.message || "").trim();
    }

    function jobErrorShortLabel(job) {
        const msg = jobErrorMessage(job);
        if (!msg) return "Lỗi";
        const low = msg.toLowerCase();
        if (low.includes("mất kết nối db") || low.includes("server closed the connection")) {
            return "Lỗi lưu DB";
        }
        if (low.includes("401") || low.includes("unauthorized") || low.includes("đăng nhập")) {
            return "Lỗi đăng nhập";
        }
        if (low.includes("quota") || low.includes("credit") || low.includes("hết quota")) {
            return "Hết quota/credit";
        }
        if (low.includes("timeout") || low.includes("timed out")) {
            return "Timeout LLM";
        }
        if (low.includes("rate limit") || low.includes("429")) {
            return "Rate limit LLM";
        }
        return truncate(msg, 28);
    }

    function pillWithError(key, job) {
        const m = STATUS[key] || { label: key, cls: "st-pending" };
        if ((key === "llm_error" || key === "badge_llm") && job && job.status === "error") {
            const label = jobErrorShortLabel(job);
            const tip = jobErrorMessage(job);
            const title = tip ? ` title="${esc(tip)}"` : "";
            return `<span class="bulk-v2-pill ${m.cls}"${title}>${esc(label)}</span>`;
        }
        return pill(key);
    }

    function rowSeoCell(jobItem) {
        if (!jobItem || jobItem.status !== "success") {
            return `<span class="bulk-v2-seo-score">—</span>`;
        }
        const score = jobItem.seo_score != null ? Number(jobItem.seo_score) : null;
        const scoreTxt = score != null && !Number.isNaN(score) ? String(score) : "—";
        const issues = Array.isArray(jobItem.seo_issues) ? jobItem.seo_issues : [];
        const tip = issues.length ? ` title="${esc(issues.slice(0, 8).join(" · "))}"` : "";
        const low = isSeoLow(jobItem);
        return (
            `<span class="bulk-v2-seo-score${low ? " is-low" : ""}"${tip}>${esc(scoreTxt)}</span>`
        );
    }

    function findJobItem(keyword) {
        const kw = String(keyword || "").trim().toLowerCase();
        return (_jobItems || []).find((x) => String(x.keyword || "").trim().toLowerCase() === kw);
    }

    function mergeRows() {
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        return rows.map((row) => ({
            row,
            job: reconcileJobItem(row, findJobItem(row.keyword)),
        }));
    }

    function renderTable() {
        const tbody = byId("caBulkStatusBody");
        const cards = byId("bulkV2Cards");
        const merged = mergeRows();
        if (!tbody) return;

        if (!merged.length) {
            tbody.innerHTML =
                '<tr><td colspan="9" class="ca-bulk-empty">Chưa có từ khóa — thêm ở bước Import.</td></tr>';
            if (cards) cards.innerHTML = '<div class="bulk-v2-card-empty">Chưa có từ khóa.</div>';
            return;
        }

        tbody.innerHTML = merged
            .map(({ row, job }) => {
                const id = row.id;
                const checked = _selected.has(id) ? " checked" : "";
                const targetWc = formatTargetWcLabel(row, job);
                const actualWc = resolveActualWc(row, job);
                const llmKey = rowLlmStatus(job, row);
                const ps = rowPublishStatus(row, job);
                const badges = rowBadges(row, job).join(" ");
                const pid = job && job.project_id ? String(job.project_id) : "";
                const setupOk = isSetupComplete(row);
                const openBtn =
                    `<button type="button" class="ca-bulk-action${setupOk ? " ca-bulk-action--setup" : ""}" data-bulk-edit-row="${esc(id)}" title="${setupOk ? "Đã setup cấu hình" : "Chưa setup đủ cấu hình"}">Sửa</button>`;
                const deleteBtn = `<button type="button" class="ca-bulk-action ca-bulk-action--danger" data-bulk-delete-row="${esc(id)}">Xóa</button>`;
                const retryBtn =
                    job && job.status === "error"
                        ? ` <button type="button" class="ca-bulk-action ca-bulk-action--retry" data-bulk-retry-row="${esc(id)}" title="Thử lại bài lỗi">Retry</button>`
                        : "";
                const openProj = pid
                    ? ` <button type="button" class="ca-bulk-action" data-bulk-open-project="${esc(pid)}">Mở</button>`
                    : "";
                return (
                    `<tr data-row-id="${esc(id)}">` +
                    `<td class="col-chk"><input type="checkbox" class="bulk-v2-row-chk" data-row-id="${esc(id)}"${checked}></td>` +
                    `<td class="col-kw"><button type="button" class="bulk-v2-kw-link" data-bulk-edit-row="${esc(id)}">${esc(row.keyword)}</button></td>` +
                    `<td class="col-target-wc">${esc(targetWc)}</td>` +
                    `<td class="col-actual-wc">${actualWc != null ? esc(String(actualWc)) : "—"}</td>` +
                    `<td class="col-seo">${rowSeoCell(job)}</td>` +
                    `<td class="col-llm">${pillWithError(llmKey, job)}</td>` +
                    `<td class="col-publish">${pill(ps)}</td>` +
                    `<td class="col-badges">${badges}</td>` +
                    `<td class="col-act"><div class="bulk-v2-act-btns">${openBtn}${retryBtn}${deleteBtn}${openProj}</div></td>` +
                    `</tr>`
                );
            })
            .join("");

        if (cards) {
            cards.innerHTML = merged
                .map(({ row, job }) => {
                    const id = row.id;
                    const checked = _selected.has(id) ? " checked" : "";
                    const title = row.custom_title || (job && job.title) || "";
                    const targetWc = formatTargetWcLabel(row, job);
                    const actualWc = resolveActualWc(row, job);
                    const setupOk = isSetupComplete(row);
                    return (
                        `<article class="bulk-v2-card" data-row-id="${esc(id)}">` +
                        `<label class="bulk-v2-card-chk"><input type="checkbox" class="bulk-v2-row-chk" data-row-id="${esc(id)}"${checked}> Chọn</label>` +
                        `<h4 class="bulk-v2-card-kw">${esc(row.keyword)}</h4>` +
                        `<p class="bulk-v2-card-meta">${esc(truncate(title, 60))}</p>` +
                        `<p class="bulk-v2-card-wc">WC ${esc(targetWc)} → ${actualWc != null ? esc(String(actualWc)) : "—"} · SEO ${job && job.seo_score != null ? esc(String(job.seo_score)) : "—"}</p>` +
                        `<div class="bulk-v2-card-pills">${rowBadges(row, job).join(" ")} ${pillWithError(rowLlmStatus(job, row), job)} ${pill(rowPublishStatus(row, job))}</div>` +
                        `<div class="bulk-v2-card-actions">` +
                        `<button type="button" class="btn secondary btn-sm bulk-v2-card-edit${setupOk ? " ca-bulk-action--setup" : ""}" data-bulk-edit-row="${esc(id)}">Sửa bài</button>` +
                        `<button type="button" class="btn secondary btn-sm bulk-v2-card-delete" data-bulk-delete-row="${esc(id)}">Xóa</button>` +
                        `</div>` +
                        `</article>`
                    );
                })
                .join("");
        }

        wireTableEvents();
        syncChkAll();
    }

    function deleteBrandKeywordRows(opts) {
        const skipConfirm = !!(opts && opts.skipConfirm);
        const c = core();
        if (!c || !c.findBrandKeywordRows || !c.removeBrandKeywordRows) {
            toast("Chức năng lọc thương hiệu chưa sẵn sàng — tải lại trang.");
            return;
        }
        const rows = c.getRows ? c.getRows() : [];
        if (!rows.length) {
            toast("Không có từ khóa để lọc.");
            return;
        }
        const hits = c.findBrandKeywordRows();
        if (!hits.length) {
            toast("Không tìm thấy từ khóa thương hiệu trong danh sách.");
            return;
        }
        const preview = hits
            .slice(0, 8)
            .map((r) => `• ${String(r.keyword || "").trim()}`)
            .join("\n");
        const more = hits.length > 8 ? `\n… và ${hits.length - 8} từ khóa khác` : "";
        if (!skipConfirm) {
            const ok = window.confirm(
                `Tìm thấy ${hits.length} từ khóa thương hiệu. Xóa các hàng này?\n\n${preview}${more}`
            );
            if (!ok) return;
        }
        const hitIds = new Set(hits.map((r) => String(r.id || "")));
        hitIds.forEach((id) => _selected.delete(id));
        if ((_editorRowId && hitIds.has(_editorRowId)) || (_drawerRowId && hitIds.has(_drawerRowId))) {
            closeEditor();
        }
        const result = c.removeBrandKeywordRows();
        const removed = result && result.removed ? result.removed : 0;
        if (removed) {
            toast(`Đã xóa ${removed} từ khóa thương hiệu.`);
            refresh();
        } else {
            toast("Không xóa được từ khóa thương hiệu.");
        }
    }

    function deleteRow(rowId) {
        const id = String(rowId || "").trim();
        if (!id) return;
        const c = core();
        if (!c || !c.removeRows) return;
        const row = c.findRow ? c.findRow(id) : null;
        if (!row) return;
        const removed = c.removeRows([id]);
        if (!removed) return;
        _selected.delete(id);
        if (_editorRowId === id || _drawerRowId === id) closeEditor();
        toast(`Đã xóa «${row.keyword}».`);
    }

    function deleteAllRows(opts) {
        const skipConfirm = !!(opts && opts.skipConfirm);
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        if (!rows.length) {
            toast("Không có từ khóa để xóa.");
            return;
        }
        if (!skipConfirm) {
            const ok = window.confirm(`Xóa tất cả ${rows.length} từ khóa trong danh sách?`);
            if (!ok) return;
        }
        _selected.clear();
        if (_editorRowId || _drawerRowId) closeEditor();
        const removed = c.removeAllRows ? c.removeAllRows() : 0;
        if (removed) toast(`Đã xóa ${removed} từ khóa.`);
    }

    function deleteSelectedRows(opts) {
        const skipConfirm = !!(opts && opts.skipConfirm);
        const c = core();
        if (!c || !c.removeRows) return;
        const ids = Array.from(_selected);
        if (!ids.length) {
            toast("Chọn ít nhất một từ khóa để xóa.");
            return;
        }
        if (!skipConfirm) {
            const ok = window.confirm(`Xóa ${ids.length} từ khóa đã chọn?`);
            if (!ok) return;
        }
        if (_editorRowId && ids.includes(_editorRowId)) closeEditor();
        else if (_drawerRowId && ids.includes(_drawerRowId)) closeEditor();
        const removed = c.removeRows(ids);
        _selected.clear();
        if (removed) toast(`Đã xóa ${removed} từ khóa đã chọn.`);
        refresh();
    }

    function closeDeleteModal() {
        const overlay = byId("bulkV2DeleteOverlay");
        if (overlay) overlay.hidden = true;
        document.body.classList.remove("bulk-v2-delete-open");
    }

    function openDeleteModal() {
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        if (!rows.length) {
            toast("Không có từ khóa để xóa.");
            return;
        }
        const selectedCount = Array.from(_selected).filter((id) => rows.some((r) => r.id === id)).length;
        const total = rows.length;
        const brandHits = c.findBrandKeywordRows ? c.findBrandKeywordRows() : [];
        const brandCount = brandHits.length;
        const summary = byId("bulkV2DeleteSummary");
        const selHint = byId("bulkV2DeleteSelectedHint");
        const allHint = byId("bulkV2DeleteAllHint");
        const brandHint = byId("bulkV2DeleteBrandHint");
        const radioSel = byId("bulkV2DeleteModeSelected");
        const radioAll = byId("bulkV2DeleteModeAll");
        const radioBrand = byId("bulkV2DeleteModeBrand");
        const optSel = byId("bulkV2DeleteOptSelected");
        const optBrand = byId("bulkV2DeleteOptBrand");
        if (summary) {
            summary.textContent =
                selectedCount > 0
                    ? `Đang tích ${selectedCount}/${total} từ khóa.`
                    : `Chưa tích chọn — mặc định xóa tất cả ${total} từ khóa.`;
        }
        if (selHint) {
            selHint.textContent = selectedCount > 0
                ? `${selectedCount} từ khóa đang được tích`
                : "Chưa tích chọn từ khóa nào";
        }
        if (allHint) allHint.textContent = `Toàn bộ ${total} từ khóa trong bảng`;
        if (brandHint) {
            brandHint.textContent = brandCount > 0
                ? `Tìm thấy ${brandCount} từ khóa thương hiệu`
                : "Không tìm thấy từ khóa thương hiệu";
        }
        if (optSel) optSel.classList.toggle("is-disabled", selectedCount === 0);
        if (optBrand) optBrand.classList.toggle("is-disabled", brandCount === 0);
        if (radioSel) {
            radioSel.disabled = selectedCount === 0;
            radioSel.checked = selectedCount > 0;
        }
        if (radioBrand) {
            radioBrand.disabled = brandCount === 0;
            if (brandCount === 0 && radioBrand.checked) radioBrand.checked = false;
        }
        if (radioAll) {
            radioAll.checked = selectedCount === 0 && !(radioBrand && radioBrand.checked);
        }

        const overlay = byId("bulkV2DeleteOverlay");
        if (!overlay) return;
        /* Gắn vào body để tránh parent transform/scroll làm lệch viewport */
        if (overlay.parentElement !== document.body) {
            document.body.appendChild(overlay);
        }
        overlay.hidden = false;
        document.body.classList.add("bulk-v2-delete-open");
        try {
            window.scrollTo({ top: window.scrollY, left: 0 });
        } catch (_) {}
    }

    function confirmDeleteModal() {
        const modeEl = document.querySelector('input[name="bulkV2DeleteMode"]:checked');
        const mode = modeEl ? modeEl.value : "all";
        closeDeleteModal();
        if (mode === "selected") deleteSelectedRows({ skipConfirm: true });
        else if (mode === "brand") deleteBrandKeywordRows({ skipConfirm: true });
        else deleteAllRows({ skipConfirm: true });
    }

    async function retryBulkRow(rowId) {
        const id = String(rowId || "").trim();
        if (!id) return;
        const c = core();
        const row = c && c.findRow ? c.findRow(id) : null;
        if (!row || !row.keyword) {
            toast("Không tìm thấy từ khóa để retry.");
            return;
        }
        let jobId = "";
        try {
            if (c && c.getBulkJobId) jobId = String(c.getBulkJobId() || "").trim();
        } catch (_) {}
        if (!jobId) {
            try {
                jobId = String(localStorage.getItem(c && c.BULK_LAST_JOB_KEY ? c.BULK_LAST_JOB_KEY() : "") || "").trim();
            } catch (_) {}
        }
        if (!jobId && typeof window !== "undefined") {
            try {
                const keys = Object.keys(localStorage || {});
                const hit = keys.find((k) => k.includes("content_ai_bulk_job_id") || k.includes("content_ai_bulk_last_job"));
                if (hit) jobId = String(localStorage.getItem(hit) || "").trim();
            } catch (_) {}
        }
        if (!jobId) {
            toast("Không có job bulk — chạy viết hàng loạt trước.");
            return;
        }
        try {
            const res = await fetch(`/content-ai/bulk-jobs/${encodeURIComponent(jobId)}/retry`, {
                method: "POST",
                headers: authJsonHeaders(),
                body: JSON.stringify({ keywords: [row.keyword] }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error((data && data.detail) || `HTTP ${res.status}`);
            }
            toast(`Đang thử lại: ${row.keyword}`);
            if (c && c.setBulkJobId && data.job_id) c.setBulkJobId(data.job_id);
            if (c && c.startBulkPoll && data.job_id) c.startBulkPoll(data.job_id);
            else if (c && c.reconnectActiveJob) c.reconnectActiveJob();
        } catch (e) {
            toast(`Retry thất bại: ${String(e.message || e)}`);
        }
    }

    function wireTableEvents() {
        const tbody = byId("caBulkStatusBody");
        if (!tbody) return;
        tbody.querySelectorAll("[data-bulk-open-project]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const pid = btn.getAttribute("data-bulk-open-project");
                const c = core();
                if (pid && c && c.loadProject) void c.loadProject(pid);
            });
        });
        tbody.querySelectorAll("[data-bulk-edit-row]").forEach((btn) => {
            btn.addEventListener("click", () => openEditor(btn.getAttribute("data-bulk-edit-row")));
        });
        tbody.querySelectorAll("[data-bulk-delete-row]").forEach((btn) => {
            btn.addEventListener("click", () => deleteRow(btn.getAttribute("data-bulk-delete-row")));
        });
        tbody.querySelectorAll("[data-bulk-retry-row]").forEach((btn) => {
            btn.addEventListener("click", () => void retryBulkRow(btn.getAttribute("data-bulk-retry-row")));
        });
        tbody.querySelectorAll(".bulk-v2-row-chk").forEach((chk) => {
            chk.addEventListener("change", () => {
                const id = chk.getAttribute("data-row-id");
                if (!id) return;
                if (chk.checked) _selected.add(id);
                else _selected.delete(id);
                syncChkAll();
            });
        });
        const cards = byId("bulkV2Cards");
        if (cards) {
            cards.querySelectorAll("[data-bulk-edit-row]").forEach((btn) => {
                btn.addEventListener("click", () => openEditor(btn.getAttribute("data-bulk-edit-row")));
            });
            cards.querySelectorAll("[data-bulk-delete-row]").forEach((btn) => {
                btn.addEventListener("click", () => deleteRow(btn.getAttribute("data-bulk-delete-row")));
            });
            cards.querySelectorAll(".bulk-v2-row-chk").forEach((chk) => {
                chk.addEventListener("change", () => {
                    const id = chk.getAttribute("data-row-id");
                    if (!id) return;
                    if (chk.checked) _selected.add(id);
                    else _selected.delete(id);
                    syncChkAll();
                });
            });
        }
    }

    function syncChkAll() {
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        const n = rows.length;
        const sel = rows.filter((r) => _selected.has(r.id)).length;
        const allChk = byId("bulkV2TableChkAll");
        if (allChk) {
            allChk.checked = n > 0 && sel === n;
            allChk.indeterminate = sel > 0 && sel < n;
        }
    }

    function setSelectAll(checked) {
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        _selected.clear();
        if (checked) rows.forEach((r) => _selected.add(r.id));
        renderTable();
    }

    function isTabletOrMobile() {
        return window.matchMedia("(max-width: 1024px)").matches;
    }

    function wireEditorTabs(shell) {
        if (!shell || shell.dataset.tabsWired === "1") return;
        shell.dataset.tabsWired = "1";
        shell.querySelectorAll(".bulk-v2-editor-tab").forEach((btn) => {
            btn.addEventListener("click", () => switchEditorTab(btn.getAttribute("data-editor-tab") || "review"));
        });
    }

    function buildEditorShell() {
        const shell = document.createElement("div");
        shell.className = "bulk-v2-editor-shell";
        shell.innerHTML =
            '<nav class="bulk-v2-editor-tabs" role="tablist">' +
            '<button type="button" class="bulk-v2-editor-tab is-active" data-editor-tab="review" role="tab">Nội dung</button>' +
            '<button type="button" class="bulk-v2-editor-tab" data-editor-tab="setup" role="tab">Cấu hình</button>' +
            '<button type="button" class="bulk-v2-editor-tab" data-editor-tab="images" role="tab">Ảnh SEO</button>' +
            '<button type="button" class="bulk-v2-editor-tab" data-editor-tab="schedule" role="tab">Lịch đăng</button>' +
            "</nav>" +
            '<div class="bulk-v2-editor-panel is-active" data-editor-panel="review"></div>' +
            '<div class="bulk-v2-editor-panel" data-editor-panel="setup" hidden></div>' +
            '<div class="bulk-v2-editor-panel" data-editor-panel="images" hidden></div>' +
            '<div class="bulk-v2-editor-panel" data-editor-panel="schedule" hidden></div>';
        wireEditorTabs(shell);
        return shell;
    }

    function renderArticleReviewPanel(container, row, job, project) {
        if (!container) return;
        const p = project || {};
        const kw = (row && row.keyword) || (job && job.keyword) || "";
        const title = p.title || (job && job.title) || (row && row.custom_title) || "";
        const meta =
            p.meta_description ||
            (job && job.meta_description) ||
            (row && row.custom_description) ||
            "";
        const slug = p.slug || (job && job.slug) || "";
        const outline =
            p.outline_content ||
            (row && row.custom_outline) ||
            (job && job.custom_outline) ||
            "";
        const content = p.content || (job && job.content) || "";
        const targetWc = formatTargetWcLabel(row, job);
        const actualWc = resolveActualWc(row, job);
        const seoScore = (job && job.seo_score != null ? job.seo_score : p.seo_score);
        const seoIssues =
            (job && Array.isArray(job.seo_issues) && job.seo_issues.length
                ? job.seo_issues
                : Array.isArray(p.seo_issues)
                  ? p.seo_issues
                  : []) || [];
        const seoStatus = (job && job.seo_status) || p.seo_status || "";
        const llmErr = jobErrorMessage(job);
        const issueLis = seoIssues.length
            ? seoIssues
                  .slice(0, 40)
                  .map((x) => `<li>${esc(x)}</li>`)
                  .join("")
            : "<li>Không có lỗi SEO được ghi nhận.</li>";

        container.innerHTML =
            `<div class="bulk-v2-article-review">` +
            (llmErr
                ? `<div class="bulk-v2-article-alert is-err">${esc(llmErr)}</div>`
                : "") +
            `<div class="bulk-v2-article-grid">` +
            `<div class="bulk-v2-article-field"><label>Keyword</label><div>${esc(kw) || "—"}</div></div>` +
            `<div class="bulk-v2-article-field"><label>Title</label><div>${esc(title) || "—"}</div></div>` +
            `<div class="bulk-v2-article-field"><label>Slug</label><div>${esc(slug) || "—"}</div></div>` +
            `<div class="bulk-v2-article-field"><label>Meta description</label><div>${esc(meta) || "—"}</div></div>` +
            `<div class="bulk-v2-article-field"><label>Target word count</label><div>${esc(targetWc)}</div></div>` +
            `<div class="bulk-v2-article-field"><label>Actual word count</label><div>${actualWc != null ? esc(String(actualWc)) : "—"} · ${pill(rowWcStatusKey(row, job))}</div></div>` +
            `<div class="bulk-v2-article-field"><label>SEO score</label><div>${seoScore != null ? esc(String(seoScore)) : "—"} · ${esc(seoStatus || "—")}</div></div>` +
            `<div class="bulk-v2-article-field"><label>LLM</label><div>${pillWithError(rowLlmStatus(job, row), job)}</div></div>` +
            `</div>` +
            `<div class="bulk-v2-article-field"><label>Outline</label><pre class="bulk-v2-article-pre">${esc(outline) || "—"}</pre></div>` +
            `<div class="bulk-v2-article-field"><label>SEO issues</label><ul class="bulk-v2-seo-issue-list">${issueLis}</ul></div>` +
            `<div class="bulk-v2-article-field"><label>Content HTML</label><textarea class="bulk-v2-article-html" readonly rows="14">${esc(content)}</textarea></div>` +
            `</div>`;
    }

    async function loadProjectsByIds(projectIds) {
        const ids = [...new Set((projectIds || []).map((x) => String(x || "").trim()).filter(Boolean))];
        await Promise.all(
            ids.map(async (pid) => {
                if (_projectById[pid] && _projectById[pid].content) return;
                try {
                    const data = await apiGet(`/content-ai/projects/${encodeURIComponent(pid)}?ts=${Date.now()}`);
                    if (data && (data.id || data.project)) {
                        const p = data.project || data;
                        _projectById[pid] = p;
                    }
                } catch (_) {
                    /* keep cache */
                }
            })
        );
    }

    function switchEditorTab(tab) {
        const shell = document.querySelector(".bulk-v2-editor-shell");
        if (!shell) return;
        shell.querySelectorAll(".bulk-v2-editor-tab").forEach((btn) => {
            btn.classList.toggle("is-active", btn.getAttribute("data-editor-tab") === tab);
        });
        shell.querySelectorAll(".bulk-v2-editor-panel").forEach((panel) => {
            const on = panel.getAttribute("data-editor-panel") === tab;
            panel.classList.toggle("is-active", on);
            panel.hidden = !on;
        });
        if (tab === "images" && _editorImageProjectId) {
            const imgPanel = shell.querySelector('[data-editor-panel="images"]');
            if (imgPanel) void renderImageSeoPanel(imgPanel, _editorImageProjectId);
        }
        if (tab === "schedule") {
            const schedPanel = shell.querySelector('[data-editor-panel="schedule"]');
            if (schedPanel) renderSchedulePanel(schedPanel, _editorRowId);
        }
        if (tab === "review") {
            const reviewPanel = shell.querySelector('[data-editor-panel="review"]');
            const c = core();
            const row = c && c.findRow ? c.findRow(_editorRowId) : null;
            const job = findJobItem(row && row.keyword);
            const pid = job && job.project_id ? String(job.project_id) : "";
            const project = pid ? _projectById[pid] : null;
            if (reviewPanel) renderArticleReviewPanel(reviewPanel, row, job, project);
        }
    }

    function toDatetimeLocalValue(iso) {
        const s = String(iso || "").trim();
        if (!s) return "";
        const d = new Date(s);
        if (Number.isNaN(d.getTime())) return s.slice(0, 16);
        const pad = (n) => String(n).padStart(2, "0");
        return (
            d.getFullYear() +
            "-" +
            pad(d.getMonth() + 1) +
            "-" +
            pad(d.getDate()) +
            "T" +
            pad(d.getHours()) +
            ":" +
            pad(d.getMinutes())
        );
    }

    function scheduleStatusLabel(sched) {
        if (!sched) return "Chưa đặt lịch";
        const st = String(sched.status || "").toLowerCase();
        if (st === "published") return "Đã đăng lên WordPress";
        if (st === "publishing") return "Đang đăng…";
        if (st === "scheduled") return "Đã hẹn giờ đăng";
        if (st === "failed") return "Lỗi đăng: " + (sched.last_error || "—");
        if (st === "cancelled") return "Đã hủy lịch";
        return st || "—";
    }

    function renderSchedulePanel(container, rowId) {
        if (!container) return;
        const c = core();
        const row = c && c.findRow ? c.findRow(rowId) : null;
        const job = row ? findJobItem(row.keyword) : null;
        const pid = job && job.project_id ? String(job.project_id) : "";
        if (!pid || !job || job.status !== "success") {
            container.innerHTML =
                '<div class="bulk-v2-schedule-panel">' +
                '<div class="bulk-v2-img-state is-empty">Viết bài xong trước khi hẹn giờ đăng.</div>' +
                "</div>";
            return;
        }
        const sched = _scheduleByProject[pid] || null;
        const curVal = sched && sched.scheduled_at ? toDatetimeLocalValue(sched.scheduled_at) : "";
        container.innerHTML =
            '<div class="bulk-v2-schedule-panel">' +
            '<div class="bulk-v2-schedule-status" id="bulkV2EditorSchedStatus">' +
            esc(scheduleStatusLabel(sched)) +
            (sched && sched.scheduled_at
                ? '<br><span class="hint">Giờ hẹn: ' + esc(String(sched.scheduled_at).replace("T", " ")) + "</span>"
                : "") +
            "</div>" +
            '<div class="bulk-v2-schedule-field">' +
            '<label for="bulkV2EditorScheduleAt">Hẹn giờ đăng bài này</label>' +
            '<input type="datetime-local" id="bulkV2EditorScheduleAt" value="' +
            esc(curVal) +
            '" />' +
            "</div>" +
            '<p class="hint">Lịch lưu trên server — worker sẽ tự đăng lên WordPress đúng giờ.</p>' +
            '<div class="bulk-v2-schedule-actions">' +
            '<button type="button" class="btn btn-sm" id="btnBulkV2EditorSaveSchedule">Lưu lịch</button>' +
            '<button type="button" class="btn secondary btn-sm" id="btnBulkV2EditorCancelSchedule"' +
            (sched && sched.id ? "" : " disabled") +
            ">Hủy lịch</button>" +
            '<button type="button" class="btn secondary btn-sm" id="btnBulkV2EditorPublishNow">Đăng ngay</button>' +
            "</div></div>";

        const btnSave = container.querySelector("#btnBulkV2EditorSaveSchedule");
        const btnCancel = container.querySelector("#btnBulkV2EditorCancelSchedule");
        const btnPub = container.querySelector("#btnBulkV2EditorPublishNow");
        if (btnSave) {
            btnSave.addEventListener("click", async () => {
                const val = byId("bulkV2EditorScheduleAt") && byId("bulkV2EditorScheduleAt").value;
                if (!val) {
                    toast("Chọn ngày giờ đăng.");
                    return;
                }
                btnSave.disabled = true;
                try {
                    const wp = await resolveWpPayload();
                    const bulkJobId = c && c.getBulkJobId ? c.getBulkJobId() : "";
                    if (sched && sched.id) {
                        await apiPost("/content-ai/bulk-publish/update-schedule", {
                            schedule_id: sched.id,
                            scheduled_at: val,
                        });
                    } else {
                        await apiPost("/content-ai/bulk-publish/schedule-one", {
                            ...wp,
                            project_id: pid,
                            scheduled_at: val,
                            bulk_job_id: bulkJobId || null,
                        });
                    }
                    await loadServerSchedules();
                    refresh();
                    renderSchedulePanel(container, rowId);
                    toast("Đã lưu lịch đăng cho bài này.");
                } catch (e) {
                    toast(String(e.message || e));
                } finally {
                    btnSave.disabled = false;
                }
            });
        }
        if (btnCancel) {
            btnCancel.addEventListener("click", async () => {
                if (!sched || !sched.id) return;
                if (!window.confirm("Hủy lịch đăng bài này?")) return;
                btnCancel.disabled = true;
                try {
                    await apiPost("/content-ai/bulk-publish/cancel-schedule", {
                        schedule_ids: [sched.id],
                    });
                    await loadServerSchedules();
                    refresh();
                    renderSchedulePanel(container, rowId);
                    toast("Đã hủy lịch.");
                } catch (e) {
                    toast(String(e.message || e));
                } finally {
                    btnCancel.disabled = false;
                }
            });
        }
        if (btnPub) {
            btnPub.addEventListener("click", async () => {
                if (!window.confirm("Đăng ngay bài này lên WordPress?")) return;
                btnPub.disabled = true;
                try {
                    const wp = await resolveWpPayload();
                    const bulkJobId = c && c.getBulkJobId ? c.getBulkJobId() : "";
                    await apiPost("/content-ai/bulk-publish/publish-now-one", {
                        ...wp,
                        project_id: pid,
                        bulk_job_id: bulkJobId || null,
                    });
                    await loadServerSchedules();
                    refresh();
                    renderSchedulePanel(container, rowId);
                    toast("Đã gửi đăng bài.");
                } catch (e) {
                    toast(String(e.message || e));
                } finally {
                    btnPub.disabled = false;
                }
            });
        }
    }

    function formatBytesKb(n) {
        const b = Number(n) || 0;
        if (!b) return "—";
        return (b / 1024).toFixed(1) + " KB";
    }

    function imageSourceLabel(feat) {
        if (!feat) return "—";
        const parts = [];
        if (feat.provider) parts.push(String(feat.provider));
        if (feat.author) parts.push(String(feat.author));
        if (feat.license) parts.push(String(feat.license));
        if (feat.source_url) parts.push(String(feat.source_url));
        return parts.length ? parts.join(" · ") : "—";
    }

    async function renderImageSeoPanel(container, projectId) {
        if (!container) return;
        const pid = String(projectId || "").trim();
        container.innerHTML =
            '<div class="bulk-v2-img-seo">' +
            '<div class="bulk-v2-img-state is-loading">Đang tải thông tin ảnh…</div>' +
            "</div>";
        if (!pid) {
            container.innerHTML =
                '<div class="bulk-v2-img-seo">' +
                '<div class="bulk-v2-img-state is-empty">Chưa có project — viết bài trước khi lấy ảnh.</div>' +
                "</div>";
            return;
        }
        if (_imageLoading.has(pid)) {
            container.innerHTML =
                '<div class="bulk-v2-img-seo">' +
                '<div class="bulk-v2-img-state is-loading">Đang lấy ảnh…</div>' +
                "</div>";
            return;
        }
        try {
            await loadImageStatuses([pid]);
        } catch (e) {
            container.innerHTML =
                '<div class="bulk-v2-img-seo">' +
                `<div class="bulk-v2-img-state is-error">${esc(String(e.message || e))}</div>` +
                '<div class="bulk-v2-img-actions">' +
                `<button type="button" class="btn secondary btn-sm" data-img-action="fetch" data-project-id="${esc(pid)}">Thử lại</button>` +
                "</div></div>";
            wireImagePanelActions(container);
            return;
        }
        const meta = _imageMetaByProject[pid] || {};
        const feat = meta.featured || null;
        const errMsg = _imageErrors[pid] || meta.error || "";
        const stKey = rowImageStatus(null, { project_id: pid, status: "success" });
        if (stKey === "img_error" || stKey === "img_bad_format" || stKey === "img_too_large") {
            container.innerHTML =
                '<div class="bulk-v2-img-seo">' +
                `<div class="bulk-v2-img-state is-error">${esc(errMsg || STATUS[stKey].label)}</div>` +
                renderImageSeoBody(feat, pid) +
                "</div>";
            wireImagePanelActions(container);
            return;
        }
        if (!feat || !feat.url) {
            container.innerHTML =
                '<div class="bulk-v2-img-seo">' +
                '<div class="bulk-v2-img-state is-empty">Chưa có ảnh SEO cho bài này.</div>' +
                renderImageSeoBody(null, pid) +
                "</div>";
            wireImagePanelActions(container);
            return;
        }
        container.innerHTML = '<div class="bulk-v2-img-seo">' + renderImageSeoBody(feat, pid) + "</div>";
        wireImagePanelActions(container);
    }

    function renderImageSeoBody(feat, projectId) {
        const pid = esc(projectId);
        const preview = feat && feat.url
            ? `<div class="bulk-v2-img-preview"><img src="${esc(feat.url)}" alt="${esc(feat.alt || "")}" loading="lazy"></div>`
            : '<div class="bulk-v2-img-preview"><div class="bulk-v2-img-preview-empty">Chưa có preview</div></div>';
        const alt = feat && feat.alt ? esc(feat.alt) : "—";
        const caption = feat && feat.caption ? esc(feat.caption) : "—";
        const source = esc(imageSourceLabel(feat));
        const fmt = feat && feat.format ? esc(String(feat.format).toUpperCase()) : "—";
        const size = feat ? esc(formatBytesKb(feat.bytes)) : "—";
        return (
            preview +
            '<dl class="bulk-v2-img-meta">' +
            "<dt>ALT</dt><dd>" + alt + "</dd>" +
            "<dt>Caption</dt><dd>" + caption + "</dd>" +
            "<dt>Source</dt><dd>" + source + "</dd>" +
            "<dt>Format</dt><dd>" + fmt + "</dd>" +
            "<dt>Size</dt><dd>" + size + "</dd>" +
            "</dl>" +
            '<div class="bulk-v2-img-actions">' +
            `<button type="button" class="btn secondary btn-sm" data-img-action="fetch" data-project-id="${pid}">Tự lấy ảnh</button>` +
            `<button type="button" class="btn secondary btn-sm" data-img-action="replace" data-project-id="${pid}">Đổi ảnh</button>` +
            `<button type="button" class="btn secondary btn-sm" data-img-action="clear" data-project-id="${pid}">Xóa ảnh</button>` +
            "</div>"
        );
    }

    function wireImagePanelActions(container) {
        if (!container || container.dataset.imgWired === "1") return;
        container.dataset.imgWired = "1";
        container.addEventListener("click", async (ev) => {
            const btn = ev.target.closest("[data-img-action]");
            if (!btn) return;
            const action = btn.getAttribute("data-img-action");
            const pid = btn.getAttribute("data-project-id");
            if (!pid) return;
            btn.disabled = true;
            try {
                if (action === "clear") {
                    if (!window.confirm("Xóa ảnh featured và ảnh inline khỏi bài này?")) return;
                    await apiPost("/content-ai/bulk-images/clear", { project_id: pid });
                    delete _imageMetaByProject[pid];
                    delete _imageErrors[pid];
                    toast("Đã xóa ảnh.");
                } else {
                    const force = action === "replace";
                    if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
                        const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.googleImage);
                        if (!ok) return;
                    }
                    _imageLoading.add(pid);
                    refresh();
                    const data = await apiPost("/content-ai/bulk-images/fetch-one", {
                        project_id: pid,
                        max_inline: 4,
                        force,
                    });
                    if (data && data.image_status) _imageMetaByProject[pid] = data.image_status;
                    delete _imageErrors[pid];
                    toast(force ? "Đã đổi ảnh." : "Đã lấy ảnh.");
                }
                await loadImageStatuses([pid]);
                refresh();
                if (_editorImageProjectId === pid) {
                    const shell = document.querySelector(".bulk-v2-editor-shell");
                    const imgPanel = shell && shell.querySelector('[data-editor-panel="images"]');
                    if (imgPanel) await renderImageSeoPanel(imgPanel, pid);
                }
            } catch (e) {
                _imageErrors[pid] = String(e.message || e);
                toast(String(e.message || e));
                const shell = document.querySelector(".bulk-v2-editor-shell");
                const imgPanel = shell && shell.querySelector('[data-editor-panel="images"]');
                if (imgPanel) await renderImageSeoPanel(imgPanel, pid);
                refresh();
            } finally {
                _imageLoading.delete(pid);
                btn.disabled = false;
                refresh();
            }
        });
    }

    function showImageSummaryModal(loading) {
        const modal = byId("bulkV2ImageSummaryModal");
        const back = byId("bulkV2ImageSummaryBackdrop");
        const loadEl = byId("bulkV2ImageSummaryLoading");
        const statsEl = byId("bulkV2ImageSummaryStats");
        const errEl = byId("bulkV2ImageSummaryErrors");
        if (!modal) return;
        modal.hidden = false;
        if (back) back.hidden = false;
        if (loadEl) loadEl.hidden = !loading;
        if (statsEl) statsEl.hidden = loading;
        if (errEl) errEl.hidden = loading;
        if (loading) {
            if (statsEl) statsEl.innerHTML = "";
            if (errEl) {
                errEl.innerHTML = "";
                errEl.hidden = true;
            }
        }
    }

    function closeImageSummaryModal() {
        const modal = byId("bulkV2ImageSummaryModal");
        const back = byId("bulkV2ImageSummaryBackdrop");
        if (modal) modal.hidden = true;
        if (back) back.hidden = true;
    }

    function renderImageSummary(data) {
        const statsEl = byId("bulkV2ImageSummaryStats");
        const errEl = byId("bulkV2ImageSummaryErrors");
        const loadEl = byId("bulkV2ImageSummaryLoading");
        if (loadEl) loadEl.hidden = true;
        const results = (data && data.results) || [];
        const errors = (data && data.errors) || [];
        const okN = results.filter((r) => r && r.ok).length;
        const skipN = results.filter((r) => r && r.skipped).length;
        const errN = errors.length;
        if (statsEl) {
            statsEl.hidden = false;
            statsEl.innerHTML =
                `<div class="bulk-v2-img-summary-stat"><span>Thành công</span><strong>${okN}</strong></div>` +
                `<div class="bulk-v2-img-summary-stat"><span>Lỗi ảnh</span><strong>${errN}</strong></div>` +
                (skipN ? `<div class="bulk-v2-img-summary-stat"><span>Bỏ qua (đã có ảnh)</span><strong>${skipN}</strong></div>` : "");
        }
        if (errEl) {
            if (!errN) {
                errEl.hidden = true;
                errEl.innerHTML = "";
            } else {
                errEl.hidden = false;
                const c = core();
                const jobs = (c && c.getJobItems ? c.getJobItems() : _jobItems) || [];
                const kwByPid = Object.create(null);
                jobs.forEach((j) => {
                    if (j.project_id) kwByPid[j.project_id] = j.keyword || j.project_id;
                });
                errEl.innerHTML = errors
                    .map((e) => {
                        const kw = kwByPid[e.project_id] || e.project_id || "—";
                        return `<li><strong>${esc(kw)}</strong>: ${esc(e.error || "Lỗi không xác định")}</li>`;
                    })
                    .join("");
            }
        }
    }

    async function runBulkImageFetch(projectIds, options) {
        const ids = [...new Set((projectIds || []).map((x) => String(x || "").trim()).filter(Boolean))];
        if (!ids.length) {
            toast("Không có bài đã viết để lấy ảnh.");
            return;
        }
        const force = !!(options && options.force);
        const onlyWithout = options && options.only_without_images !== false;
        if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
            const preset = Object.assign({}, window.DigiSeoCreditActions.googleImage, { quantity: ids.length });
            const ok = await window.DigiSeoConfirmCredit(preset);
            if (!ok) return;
        }
        ids.forEach((id) => _imageLoading.add(id));
        refresh();
        showImageSummaryModal(true);
        try {
            const data = await apiPost("/content-ai/bulk-images/fetch-batch", {
                project_ids: ids,
                max_inline: 4,
                force,
                only_without_images: onlyWithout,
            });
            ((data && data.results) || []).forEach((r) => {
                if (!r || !r.project_id) return;
                if (r.ok) delete _imageErrors[r.project_id];
            });
            ((data && data.errors) || []).forEach((e) => {
                if (e && e.project_id) _imageErrors[e.project_id] = e.error || "Lỗi ảnh";
            });
            await loadImageStatuses(ids);
            renderImageSummary(data);
            refresh();
        } catch (e) {
            if (byId("bulkV2ImageSummaryStats")) {
                byId("bulkV2ImageSummaryStats").hidden = false;
                byId("bulkV2ImageSummaryStats").innerHTML =
                    `<div class="bulk-v2-img-summary-stat is-error"><span>Lỗi</span><strong>${esc(String(e.message || e))}</strong></div>`;
            }
            if (byId("bulkV2ImageSummaryLoading")) byId("bulkV2ImageSummaryLoading").hidden = true;
        } finally {
            ids.forEach((id) => _imageLoading.delete(id));
            refresh();
        }
    }

    function openEditor(rowId) {
        if (!rowId) return;
        _drawerRowId = rowId;
        _editorRowId = rowId;
        const legacy = document.querySelector(`.bulk-kw-card[data-id="${CSS.escape(rowId)}"]`);
        const target = byId("bulkV2ModalBody");
        const titleEl = byId("bulkV2ModalTitle");
        const c = core();
        const row = (c && c.findRow ? c.findRow(rowId) : null) ||
            ((c && c.getRows ? c.getRows() : []).find((r) => r.id === rowId) || null);
        if (titleEl && row) titleEl.textContent = row.keyword || "Chi tiết bài viết";
        if (!target) {
            toast("Không mở được popup sửa bài.");
            return;
        }
        target.innerHTML = "";
        const shell = buildEditorShell();
        const reviewPanel = shell.querySelector('[data-editor-panel="review"]');
        const setupPanel = shell.querySelector('[data-editor-panel="setup"]');
        const imgPanel = shell.querySelector('[data-editor-panel="images"]');
        const schedPanel = shell.querySelector('[data-editor-panel="schedule"]');
        target.appendChild(shell);

        if (legacy) {
            legacy.classList.remove("bulk-v2-legacy-hidden");
            legacy.hidden = false;
            legacy.removeAttribute("aria-hidden");
            legacy.classList.add("is-open", "is-active", "bulk-kw-card--editor");
            const details = legacy.querySelector(".bulk-kw-details");
            if (details) details.style.display = "block";
            if (row) row.detailsOpen = true;
            if (setupPanel) setupPanel.appendChild(legacy);
        } else if (setupPanel) {
            setupPanel.innerHTML =
                '<p class="hint">Không tìm thấy form cấu hình trong danh sách — xem tab Nội dung.</p>';
        }

        const job = findJobItem(row && row.keyword);
        _editorImageProjectId = job && job.project_id ? String(job.project_id) : "";

        const finishOpen = () => {
            const project = _editorImageProjectId ? _projectById[_editorImageProjectId] : null;
            if (reviewPanel) renderArticleReviewPanel(reviewPanel, row, job, project);
            if (imgPanel) {
                imgPanel.dataset.imgWired = "";
                void renderImageSeoPanel(imgPanel, _editorImageProjectId);
            }
            if (schedPanel) {
                void loadServerSchedules().then(() => renderSchedulePanel(schedPanel, rowId));
            }
            switchEditorTab("review");
            showDrawer(false);
            showEditorModal(true);
            const overlay = byId("bulkV2ModalBackdrop");
            if (overlay) overlay.scrollTop = 0;
        };

        if (_editorImageProjectId) {
            void loadProjectsByIds([_editorImageProjectId]).then(finishOpen);
        } else {
            finishOpen();
        }
    }

    function portalEditorOverlay() {
        const b = byId("bulkV2ModalBackdrop");
        if (b && b.parentElement !== document.body) {
            document.body.insertBefore(b, document.body.firstChild);
        }
    }

    function showEditorModal(on) {
        const b = byId("bulkV2ModalBackdrop");
        const m = byId("bulkV2Modal");
        if (on) portalEditorOverlay();
        if (b) {
            b.hidden = !on;
            b.classList.toggle("bulk-v2-editor-active", !!on);
        }
        if (m) {
            m.hidden = !on;
            m.setAttribute("aria-hidden", on ? "false" : "true");
        }
        document.body.classList.toggle("bulk-v2-editor-open", !!on);
        if (on) {
            document.addEventListener("keydown", onEditorEscape, true);
        } else {
            document.removeEventListener("keydown", onEditorEscape, true);
        }
    }

    function onEditorEscape(e) {
        if (e.key === "Escape" && _drawerRowId) {
            e.preventDefault();
            closeEditor();
        }
    }

    function showDrawer(on) {
        const d = byId("bulkV2Drawer");
        const b = byId("bulkV2DrawerBackdrop");
        if (d) {
            d.hidden = !on;
            d.setAttribute("aria-hidden", on ? "false" : "true");
        }
        if (b) b.hidden = !on;
        document.body.classList.toggle("bulk-v2-drawer-open", !!on);
    }

    function showModal(on) {
        showEditorModal(on);
    }

    function closeEditor() {
        const list = byId("bulkKeywordList");
        if (_drawerRowId && list) {
            const card = document.querySelector(`.bulk-kw-card[data-id="${CSS.escape(_drawerRowId)}"]`);
            if (card && card.parentElement !== list) {
                card.classList.remove("bulk-kw-card--editor");
                card.classList.add("bulk-v2-legacy-hidden");
                card.hidden = true;
                card.setAttribute("aria-hidden", "true");
                list.appendChild(card);
            }
        }
        showDrawer(false);
        showEditorModal(false);
        _editorImageProjectId = "";
        _editorRowId = "";
        const rid = _drawerRowId;
        _drawerRowId = null;
        const c = core();
        if (c && c.renderKeywordList) c.renderKeywordList();
        /* Bắt buộc refresh bảng để cập nhật viền nút Sửa theo trạng thái setup */
        refresh();
        if (c && c.syncBulkV2Ui) c.syncBulkV2Ui();
        if (rid) {
            try {
                const btn = document.querySelector(`#caBulkStatusTable [data-bulk-edit-row="${CSS.escape(rid)}"]`);
                if (btn) btn.focus({ preventScroll: true });
            } catch (_) {}
        }
    }

    function setStep(step) {
        _activeStep = step;
        document.querySelectorAll(".bulk-v2-panel").forEach((el) => {
            const p = el.getAttribute("data-bulk-panel");
            // Import + Target website / thương hiệu luôn hiển thị trên tab Viết hàng loạt
            if (p === "import" || p === "setup") {
                el.classList.add("is-active");
                el.hidden = false;
                return;
            }
            const on = p === step;
            el.classList.toggle("is-active", on);
            el.hidden = !on;
        });
        const c = core();
        if (c && c.notifyStep) c.notifyStep(step);
        if (window.ContentAiBulkPublishCenter && window.ContentAiBulkPublishCenter.refresh) {
            setTimeout(() => void window.ContentAiBulkPublishCenter.refresh(), 50);
        }
    }

    function getSelectedKeywords() {
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        return rows.filter((r) => _selected.has(r.id)).map((r) => r.keyword);
    }

    function toast(msg) {
        const host = byId("caToastHost");
        if (!host) return;
        const el = document.createElement("div");
        el.className = "ca-toast";
        el.textContent = msg;
        host.appendChild(el);
        setTimeout(() => el.remove(), 4200);
    }

    function initStepper() {
        document.querySelectorAll("[data-bulk-goto]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const step = btn.getAttribute("data-bulk-goto") || "import";
                if (step !== "import") {
                    const c = core();
                    const rows = c && c.getRows ? c.getRows() : [];
                    if (!rows.length) {
                        toast("Vui lòng nhập ít nhất 1 từ khóa hợp lệ.");
                        return;
                    }
                }
                setStep(step);
            });
        });
        const c = core();
        if (c && c.syncBulkStepButtons) c.syncBulkStepButtons();
    }

    function initActions() {
        const tableChkAll = byId("bulkV2TableChkAll");
        if (tableChkAll) {
            tableChkAll.addEventListener("change", () => setSelectAll(tableChkAll.checked));
        }

        const btnDeleteMenu = byId("btnBulkV2DeleteMenu");
        if (btnDeleteMenu && !btnDeleteMenu._bulkDeleteMenuBound) {
            btnDeleteMenu._bulkDeleteMenuBound = true;
            btnDeleteMenu.addEventListener("click", () => openDeleteModal());
        }
        const btnDeleteConfirm = byId("btnBulkV2DeleteConfirm");
        if (btnDeleteConfirm && !btnDeleteConfirm._bulkDeleteConfirmBound) {
            btnDeleteConfirm._bulkDeleteConfirmBound = true;
            btnDeleteConfirm.addEventListener("click", () => confirmDeleteModal());
        }
        ["btnBulkV2DeleteCancel", "bulkV2DeleteClose", "bulkV2DeleteOverlay"].forEach((id) => {
            const el = byId(id);
            if (!el || el._bulkDeleteCloseBound) return;
            el._bulkDeleteCloseBound = true;
            el.addEventListener("click", (e) => {
                if (id === "bulkV2DeleteOverlay" && e.target !== el) return;
                closeDeleteModal();
            });
        });
        if (!document._bulkDeleteModalEscBound) {
            document._bulkDeleteModalEscBound = true;
            document.addEventListener("keydown", (e) => {
                if (e.key !== "Escape") return;
                const overlay = byId("bulkV2DeleteOverlay");
                if (overlay && !overlay.hidden) closeDeleteModal();
            });
        }

        const btnWrite = byId("btnBulkV2WriteSelected");
        if (btnWrite) {
            btnWrite.addEventListener("click", async () => {
                const c = core();
                if (!c || !c.startWriteSelected) {
                    byId("btnBulkWriteStart") && byId("btnBulkWriteStart").click();
                    return;
                }
                const kws = getSelectedKeywords();
                if (!kws.length) {
                    toast("Chọn ít nhất một từ khóa.");
                    return;
                }
                setStep("run");
                await c.startWriteSelected(kws);
            });
        }

        const btnImg = byId("btnBulkV2FetchImages");
        if (btnImg) {
            btnImg.addEventListener("click", async () => {
                const projectIds = getSelectedProjectIds({ allowBroken: true });
                if (!projectIds.length) {
                    toast("Chọn bài đã viết xong (có project) để lấy ảnh.");
                    return;
                }
                btnImg.disabled = true;
                try {
                    await runBulkImageFetch(projectIds, { only_without_images: true, force: false });
                } finally {
                    btnImg.disabled = false;
                }
            });
        }

        const btnImgAll = byId("btnBulkV2FetchImagesAll");
        if (btnImgAll) {
            btnImgAll.addEventListener("click", async () => {
                const projectIds = getAllWrittenProjectIds({ allowBroken: true });
                if (!projectIds.length) {
                    toast("Chưa có bài viết xong để lấy ảnh.");
                    return;
                }
                if (!window.confirm(`Tự lấy ảnh cho ${projectIds.length} bài đã viết?`)) return;
                btnImgAll.disabled = true;
                try {
                    await runBulkImageFetch(projectIds, { only_without_images: true, force: false });
                } finally {
                    btnImgAll.disabled = false;
                }
            });
        }

        const imgSumClose = byId("bulkV2ImageSummaryClose");
        const imgSumBack = byId("bulkV2ImageSummaryBackdrop");
        if (imgSumClose) imgSumClose.addEventListener("click", closeImageSummaryModal);
        if (imgSumBack) imgSumBack.addEventListener("click", closeImageSummaryModal);

        const btnSched = byId("btnBulkV2Schedule");
        if (btnSched && !btnSched._bulkSchedUiFallbackBound) {
            btnSched._bulkSchedUiFallbackBound = true;
            btnSched.addEventListener("click", () => {
                if (window.ContentAiScheduleBoard && typeof window.ContentAiScheduleBoard.open === "function") {
                    window.ContentAiScheduleBoard.open();
                    return;
                }
                const schedModal = byId("bulkV2ScheduleModal");
                const schedBack = byId("bulkV2ScheduleBackdrop");
                if (!getSelectedKeywords().length) {
                    toast("Chọn ít nhất một bài.");
                    return;
                }
                if (schedModal) schedModal.hidden = false;
                if (schedBack) schedBack.hidden = false;
            });
        }
        const schedModal = byId("bulkV2ScheduleModal");
        const schedBack = byId("bulkV2ScheduleBackdrop");
        const schedClose = byId("bulkV2ScheduleClose");
        const closeSched = () => {
            if (schedModal) schedModal.hidden = true;
            if (schedBack) schedBack.hidden = true;
        };
        if (schedClose) schedClose.addEventListener("click", closeSched);
        if (schedBack) schedBack.addEventListener("click", closeSched);
        const schedApply = byId("btnBulkV2ScheduleApply");
        if (schedApply) {
            schedApply.addEventListener("click", async () => {
                const val = byId("bulkV2ScheduleAt") && byId("bulkV2ScheduleAt").value;
                if (!val) {
                    toast("Chọn ngày giờ.");
                    return;
                }
                const projectIds = getSelectedProjectIds({ allowBroken: true });
                if (!projectIds.length) {
                    toast("Chọn bài đã viết xong (có project).");
                    return;
                }
                schedApply.disabled = true;
                try {
                    const wp = await resolveWpPayload();
                    const c = core();
                    const bulkJobId = c && c.getBulkJobId ? c.getBulkJobId() : "";
                    await apiPost("/content-ai/bulk-publish/schedule-batch", {
                        ...wp,
                        bulk_job_id: bulkJobId || null,
                        scheduled_at: val,
                        items: projectIds.map((project_id) => ({ project_id, scheduled_at: val })),
                    });
                    closeSched();
                    await loadServerSchedules();
                    refresh();
                    toast("Đã lưu lịch đăng trên server.");
                } catch (e) {
                    toast(String(e.message || e));
                } finally {
                    schedApply.disabled = false;
                }
            });
        }

        const btnPub = byId("btnBulkV2PublishAll");
        if (btnPub) {
            btnPub.addEventListener("click", () => {
                const projectIds = getSelectedProjectIds({ allowBroken: true });
                if (!projectIds.length) {
                    toast("Chọn bài đã viết xong để đăng.");
                    return;
                }
                const pc = window.ContentAiBulkPublishCenter;
                if (pc && pc.openModal) void pc.openModal(projectIds, "Đăng bài đã chọn");
            });
        }

        const closeD = byId("bulkV2DrawerClose");
        const closeM = byId("bulkV2ModalClose");
        const backD = byId("bulkV2DrawerBackdrop");
        const backM = byId("bulkV2ModalBackdrop");
        if (closeD) closeD.addEventListener("click", closeEditor);
        if (closeM) closeM.addEventListener("click", closeEditor);
        if (backD) backD.addEventListener("click", closeEditor);
        if (backM) {
            backM.addEventListener("click", (e) => {
                if (e.target === backM) closeEditor();
            });
        }
    }

    function refresh() {
        reconcileAllJobItems();
        const ids = getAllWrittenProjectIds({ allowBroken: true });
        const done = () => {
            renderTable();
            if (window.ContentAiBulkPublishCenter && window.ContentAiBulkPublishCenter.refresh) {
                void window.ContentAiBulkPublishCenter.refresh();
            }
        };
        if (ids.length) {
            void Promise.all([loadImageStatuses(ids), loadProjectsByIds(ids)]).then(done);
        } else {
            done();
        }
    }

    function mergeJobItemNoDowngrade(prev, incoming) {
        const a = prev && typeof prev === "object" ? prev : {};
        const b = incoming && typeof incoming === "object" ? incoming : {};
        const rank = (s) => {
            const v = String(s || "").toLowerCase();
            if (v === "success" || v === "written" || v === "ok") return 40;
            if (v === "error") return 30;
            if (v === "cancelled") return 20;
            if (v === "running") return 10;
            return 0;
        };
        const merged = { ...a, ...b };
        if (rank(a.status) > rank(b.status)) {
            merged.status = a.status;
            if (a.project_id && !String(merged.project_id || "").trim()) merged.project_id = a.project_id;
            if (a.word_count != null && merged.word_count == null) merged.word_count = a.word_count;
            if (a.actual_word_count != null && merged.actual_word_count == null) {
                merged.actual_word_count = a.actual_word_count;
            }
            if (a.seo_score != null && merged.seo_score == null) merged.seo_score = a.seo_score;
        }
        if (a.project_id && !String(b.project_id || "").trim()) merged.project_id = a.project_id;
        merged.keyword = b.keyword || a.keyword || "";
        return merged;
    }

    function refreshJob(items, opts) {
        const incoming = Array.isArray(items) ? items : [];
        const wipe = !!(opts && opts.replace && !incoming.length);
        if (wipe) {
            _jobItems = [];
        } else if (!incoming.length && !(_jobItems || []).length) {
            _jobItems = [];
        } else {
            const byKw = Object.create(null);
            (_jobItems || []).forEach((it) => {
                const kw = String((it && it.keyword) || "").trim().toLowerCase();
                if (kw) byKw[kw] = { ...it };
            });
            incoming.forEach((it) => {
                const kw = String((it && it.keyword) || "").trim().toLowerCase();
                if (!kw) return;
                byKw[kw] = mergeJobItemNoDowngrade(byKw[kw], it);
            });
            _jobItems = Object.values(byKw);
        }
        reconcileAllJobItems();
        if (_jobItems.some((x) => x.status === "running")) {
            setStep("run");
        } else if (_jobItems.some((x) => x.status === "success" || x.status === "error")) {
            setStep("review");
        }
        renderTable();
        void loadServerSchedules().then(() => refresh());
    }

    function init() {
        initStepper();
        initActions();
        setStep("import");
        const tryRefresh = () => {
            if (core()) {
                if (core().syncBulkStepButtons) core().syncBulkStepButtons();
                void loadServerSchedules().then(() => refresh());
                return;
            }
            setTimeout(tryRefresh, 200);
        };
        tryRefresh();
    }

    window.ContentAiBulkUi = {
        refresh,
        refreshJob,
        setStep,
        getSelectedIds: () => Array.from(_selected),
        getSelectedKeywords,
        getDrawerRowId: () => _drawerRowId,
        closeEditor,
        getSelectedProjectIds,
        getAllWrittenProjectIds,
        getMergedArticles: mergeRows,
        getJobItems: () => _jobItems.slice(),
        getScheduleByProject: () => ({ ..._scheduleByProject }),
        getImageMetaByProject: () => ({ ..._imageMetaByProject }),
        getProjectById: (pid) => _projectById[String(pid || "")] || null,
        isJobPublishable,
        isContentEmpty,
        isLlmError,
        loadServerSchedules,
        loadProjectsByIds,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
