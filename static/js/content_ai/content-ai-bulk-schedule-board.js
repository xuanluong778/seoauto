/**
 * Content AI Bulk — Schedule board modal (DB-backed, polling).
 * Depends on ContentAiBulkUi / ContentAiBulkCore when present.
 */
(function () {
    "use strict";

    const TZ = "Asia/Ho_Chi_Minh";
    const STATUS_LABEL = {
        unscheduled: "Chưa đặt lịch",
        scheduled: "Đã đặt lịch",
        publishing: "Đang đăng",
        published: "Đã đăng",
        failed: "Đăng lỗi",
    };

    let _items = [];
    let _allItems = [];
    let _boardSites = [];
    let _selected = new Set();
    let _page = 1;
    let _pageSize = 10;
    let _pollTimer = null;
    let _editProjectId = "";
    /** @type {"schedule"|"publish"} */
    let _editIntent = "schedule";
    /** @type {string[]} project ids when publishing from popup (1+). */
    let _publishIds = [];
    let _busy = false;
    let _cardActBusy = false;
    let _refreshSeq = 0;
    let _searchTimer = null;
    let _gridBound = false;
    let _lastGridSig = "";
    let _persistTimer = null;
    let _restoring = false;
    let _didRestore = false;
    let _openInFlight = false;
    let _editorWatch = null;
    const EDITOR_OVER_BOARD_Z = "2147483700";

    const UI_STATE_KEY = "ca_sched_board_ui_v1";

    function detectMainTab() {
        try {
            if (byId("tabMainBulk") && byId("tabMainBulk").classList.contains("active")) return "bulk";
            if (byId("tabMainAutoUpdate") && byId("tabMainAutoUpdate").classList.contains("active")) return "autoupdate";
            if (byId("tabMainSingle") && byId("tabMainSingle").classList.contains("active")) return "single";
        } catch (_) {}
        return "bulk";
    }

    function readUiState() {
        try {
            const raw = sessionStorage.getItem(UI_STATE_KEY);
            if (!raw) return null;
            const data = JSON.parse(raw);
            return data && typeof data === "object" ? data : null;
        } catch (_) {
            return null;
        }
    }

    function clearUiState() {
        try {
            sessionStorage.removeItem(UI_STATE_KEY);
        } catch (_) {}
        if (_persistTimer) {
            clearTimeout(_persistTimer);
            _persistTimer = null;
        }
    }

    function collectUiState() {
        const board = byId("caSchedBoardModal");
        const edit = byId("caSchedEditModal");
        const bulk = byId("caSchedBulkModal");
        const body = byId("caSchedBoardBody");
        const boardOpen = !!(board && !board.hidden);
        if (!boardOpen) return null;
        const editOpen = !!(edit && !edit.hidden);
        const bulkOpen = !!(bulk && !bulk.hidden);
        return {
            v: 1,
            boardOpen: true,
            mainTab: detectMainTab(),
            q: (byId("caSchedSearch") && byId("caSchedSearch").value) || "",
            status: (byId("caSchedFilterStatus") && byId("caSchedFilterStatus").value) || "",
            site: (byId("caSchedFilterSite") && byId("caSchedFilterSite").value) || "",
            category: (byId("caSchedFilterCategory") && byId("caSchedFilterCategory").value) || "",
            selected: Array.from(_selected),
            page: _page,
            pageSize: _pageSize,
            scrollTop: body ? Number(body.scrollTop) || 0 : 0,
            editOpen: editOpen,
            editProjectId: editOpen ? String(_editProjectId || (byId("caSchedEditProjectId") && byId("caSchedEditProjectId").value) || "") : "",
            editAt: editOpen && byId("caSchedEditAt") ? byId("caSchedEditAt").value : "",
            editSiteId: editOpen && byId("caSchedEditSite") ? byId("caSchedEditSite").value : "",
            editCategoryId: editOpen && byId("caSchedEditCategory") ? byId("caSchedEditCategory").value : "",
            editSlug: editOpen && byId("caSchedEditSlug") ? byId("caSchedEditSlug").value : "",
            editMode: editOpen && byId("caSchedEditMode") ? byId("caSchedEditMode").value : "",
            editIntent: editOpen ? _editIntent : "schedule",
            publishIds: editOpen && _editIntent === "publish" ? _publishIds.slice() : [],
            bulkOpen: bulkOpen,
            bulkStart: bulkOpen && byId("caSchedBulkStart") ? byId("caSchedBulkStart").value : "",
            bulkMode: bulkOpen && byId("caSchedBulkMode") ? byId("caSchedBulkMode").value : "",
            bulkInterval: bulkOpen && byId("caSchedBulkInterval") ? byId("caSchedBulkInterval").value : "",
            bulkCustom: bulkOpen && byId("caSchedBulkCustom") ? byId("caSchedBulkCustom").value : "",
        };
    }

    function persistUiStateSoon() {
        if (_restoring) return;
        if (_persistTimer) clearTimeout(_persistTimer);
        _persistTimer = setTimeout(() => {
            _persistTimer = null;
            try {
                const st = collectUiState();
                if (!st) {
                    sessionStorage.removeItem(UI_STATE_KEY);
                    return;
                }
                sessionStorage.setItem(UI_STATE_KEY, JSON.stringify(st));
            } catch (_) {}
        }, 80);
    }

    function applyFilterInputs(st) {
        if (!st) return;
        const search = byId("caSchedSearch");
        const status = byId("caSchedFilterStatus");
        const site = byId("caSchedFilterSite");
        const cat = byId("caSchedFilterCategory");
        const ps = byId("caSchedPageSize");
        if (search) search.value = st.q || "";
        if (status) status.value = st.status || "";
        if (site && st.site != null) {
            // Option may not exist yet; set after fillSiteFilter too.
            site.dataset.restoreValue = String(st.site || "");
            try {
                site.value = String(st.site || "");
            } catch (_) {}
        }
        if (cat && st.category != null) {
            cat.dataset.restoreValue = String(st.category || "");
            try {
                cat.value = String(st.category || "");
            } catch (_) {}
        }
        if (ps && st.pageSize) {
            const n = Number(st.pageSize) || 10;
            if (![...ps.options].some((o) => o.value === String(n))) {
                const opt = document.createElement("option");
                opt.value = String(n);
                opt.textContent = String(n);
                ps.appendChild(opt);
            }
            ps.value = String(n);
            _pageSize = n;
        }
    }

    function restoreFilterSelectValues() {
        const site = byId("caSchedFilterSite");
        const cat = byId("caSchedFilterCategory");
        if (site && site.dataset.restoreValue != null) {
            try {
                site.value = site.dataset.restoreValue;
            } catch (_) {}
        }
        if (cat && cat.dataset.restoreValue != null) {
            try {
                cat.value = cat.dataset.restoreValue;
            } catch (_) {}
        }
    }

    function applyScroll(st) {
        const body = byId("caSchedBoardBody");
        if (!body || !st) return;
        const top = Number(st.scrollTop) || 0;
        requestAnimationFrame(() => {
            try {
                body.scrollTop = top;
            } catch (_) {}
        });
    }

    function ensureMainTab(tab) {
        const want = String(tab || "bulk");
        if (detectMainTab() === want) return;
        try {
            if (want === "bulk" && byId("tabMainBulk")) byId("tabMainBulk").click();
            else if (want === "single" && byId("tabMainSingle")) byId("tabMainSingle").click();
            else if (want === "autoupdate" && byId("tabMainAutoUpdate")) byId("tabMainAutoUpdate").click();
        } catch (_) {}
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
    function authHeaders(extra) {
        const h = Object.assign({}, extra || {});
        let t = "";
        try {
            if (typeof window.DigiSeoGetAuthToken === "function") {
                t = String(window.DigiSeoGetAuthToken() || "").trim();
            }
        } catch (_) {}
        if (!t) {
            try {
                t = String(sessionStorage.getItem("seo_token") || "").trim();
            } catch (_) {}
        }
        if (!t) {
            try {
                const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
                t = m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
            } catch (_) {}
        }
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }
    async function api(method, path, body) {
        const opts = { method, credentials: "same-origin", headers: authHeaders({ "Content-Type": "application/json" }) };
        if (body != null) opts.body = JSON.stringify(body);
        const res = await fetch(path, opts);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data && data.detail;
            throw new Error(typeof detail === "string" ? detail : detail && detail.message ? detail.message : "Request failed");
        }
        return data;
    }
    function toast(msg, type) {
        const text = String(msg || "").trim();
        if (!text) return;
        const kind = type || "info";
        try {
            if (typeof window.showCaToast === "function") {
                window.showCaToast(text, kind);
                return;
            }
        } catch (_) {}
        const host = byId("caToastHost") || document.body;
        if (!host) return;
        const el = document.createElement("div");
        el.className = "ca-toast " + kind;
        el.textContent = text;
        host.appendChild(el);
        window.setTimeout(() => {
            try {
                el.style.opacity = "0";
                el.style.transition = "opacity 0.25s";
            } catch (_) {}
            window.setTimeout(() => {
                try {
                    el.remove();
                } catch (_) {}
            }, 280);
        }, 3200);
    }
    function core() {
        return window.ContentAiBulkCore || null;
    }
    function ui() {
        return window.ContentAiBulkUi || null;
    }
    function defaultLocal(mins) {
        const d = new Date(Date.now() + (mins || 30) * 60000);
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
    function assertFuture(val) {
        const d = new Date(val);
        if (Number.isNaN(d.getTime())) return "Thời gian không hợp lệ.";
        if (d.getTime() <= Date.now() + 5000) return "Thời gian đăng phải ở tương lai.";
        return "";
    }
    /** Flatten /api/settings/publishing-sites summary (items is { platform: [...] }). */
    function flattenPublishingSites(data, platforms) {
        const out = [];
        const items = data && data.items;
        const want = Array.isArray(platforms) && platforms.length
            ? new Set(platforms.map((p) => String(p).toLowerCase()))
            : null;
        if (Array.isArray(items)) {
            items.forEach((s) => {
                if (!s) return;
                const plat = String(s.platform || "").toLowerCase();
                if (want && !want.has(plat)) return;
                out.push(s);
            });
            return out;
        }
        if (items && typeof items === "object") {
            Object.keys(items).forEach((plat) => {
                const key = String(plat || "").toLowerCase();
                if (want && !want.has(key)) return;
                const arr = items[plat];
                if (!Array.isArray(arr)) return;
                arr.forEach((s) => {
                    if (!s) return;
                    out.push(Object.assign({ platform: key }, s));
                });
            });
            return out;
        }
        if (Array.isArray(data && data.sites)) {
            return flattenPublishingSites({ items: data.sites }, platforms);
        }
        return out;
    }
    function siteOptionLabel(s) {
        const name = String((s && s.name) || "").trim();
        const url = String((s && (s.url || s.website_url)) || "").trim();
        if (name && url) return name + " — " + url;
        return name || url || String((s && s.id) || "");
    }
    function bindDatetimePicker(el) {
        if (!el || el.dataset.caPickerBound === "1") return;
        el.dataset.caPickerBound = "1";
        const openPicker = () => {
            try {
                if (typeof el.showPicker === "function") el.showPicker();
            } catch (_) {}
        };
        el.addEventListener("click", openPicker);
        el.addEventListener("focus", openPicker);
    }
    function selectedProjectIds() {
        try {
            const u = ui();
            if (u && u.getSelectedProjectIds) {
                const ids = u.getSelectedProjectIds({ allowBroken: true }) || [];
                if (ids.length) return ids;
                const all = u.getAllWrittenProjectIds ? u.getAllWrittenProjectIds({ allowBroken: true }) : [];
                if (all && all.length) return all;
            }
        } catch (_) {}
        return [];
    }
    async function resolveWp() {
        const c = core();
        if (c && typeof c.resolveWpPublishPayload === "function") {
            return c.resolveWpPublishPayload();
        }
        // Fallback: first WP site from settings
        const data = await api("GET", "/api/settings/publishing-sites?ts=" + Date.now());
        const sites = flattenPublishingSites(data, ["wordpress"]);
        if (!sites.length) throw new Error("Chưa có website WordPress trong Settings.");
        return { wp_site_id: sites[0].id };
    }

    function portalToBody(nodes) {
        nodes.forEach((el) => {
            if (el && el.parentElement !== document.body) {
                document.body.appendChild(el);
            }
        });
    }

    function openModal(opts) {
        const restore = opts && opts.restore && typeof opts.restore === "object" ? opts.restore : null;
        const modal = byId("caSchedBoardModal");
        const back = byId("caSchedBoardBackdrop");
        const editModal = byId("caSchedEditModal");
        const editBack = byId("caSchedEditBackdrop");
        const bulkModal = byId("caSchedBulkModal");
        const bulkBack = byId("caSchedBulkBackdrop");
        if (!modal) {
            toast("Thiếu giao diện bảng đặt lịch. Hãy tải lại trang (Ctrl+F5).");
            return Promise.resolve();
        }
        // Already open and not restoring — avoid duplicate open/API work.
        if (!modal.hidden && !restore) {
            persistUiStateSoon();
            return Promise.resolve();
        }
        if (_openInFlight && !restore) return _openInFlight;

        const run = (async () => {
            // Escape stacking contexts (sidebar / workspace) so popup is always on top.
            portalToBody([back, modal, editBack, editModal, bulkBack, bulkModal]);
            if (restore) {
                applyFilterInputs(restore);
                _page = Math.max(1, Number(restore.page) || 1);
                _pageSize = Math.max(1, Number(restore.pageSize) || _pageSize);
                _selected = new Set((restore.selected || []).map((x) => String(x || "")).filter(Boolean));
            } else {
                // Fit rows without list scrollbar: 10 (5×2) / 4 / 2 by viewport.
                if (window.matchMedia("(max-width: 640px)").matches) _pageSize = 2;
                else if (window.matchMedia("(max-width: 1100px)").matches) _pageSize = 4;
                else _pageSize = 10;
                const ps = byId("caSchedPageSize");
                if (ps) {
                    if (![...ps.options].some((o) => o.value === String(_pageSize))) {
                        const opt = document.createElement("option");
                        opt.value = String(_pageSize);
                        opt.textContent = String(_pageSize);
                        ps.appendChild(opt);
                    }
                    ps.value = String(_pageSize);
                }
                _page = 1;
            }
            modal.hidden = false;
            if (back) back.hidden = false;
            restoreBoardVisibility();
            document.body.classList.add("ca-sched-board-open");
            showGridLoading();
            await refreshBoard({ silent: !!restore, keepPage: true });
            restoreFilterSelectValues();
            applyBoardFilters({ keepPage: true });
            updateSelectedCount();
            applyScroll(restore);
            startPoll();
            if (restore) {
                if (restore.editOpen && restore.editProjectId) {
                    await openEdit(restore.editProjectId, {
                        restore: restore,
                        intent: restore.editIntent || "schedule",
                        publishIds: restore.publishIds || [restore.editProjectId],
                    });
                }
                if (restore.bulkOpen) {
                    openBulk({ restore: restore });
                }
            }
            persistUiStateSoon();
            try {
                const c = core();
                if (c && typeof c.rehydrateBulkJobStatus === "function") {
                    void c.rehydrateBulkJobStatus({ skipIfHasResult: true });
                }
            } catch (_) {}
        })();

        _openInFlight = run.finally(() => {
            _openInFlight = null;
        });
        return _openInFlight;
    }
    function showGridLoading() {
        const grid = byId("caSchedGrid");
        const empty = byId("caSchedEmpty");
        if (empty) empty.hidden = true;
        if (grid) {
            grid.innerHTML =
                '<div class="ca-sched-loading" role="status">Đang tải danh sách bài…</div>';
        }
        _lastGridSig = "";
    }
    function closeModal(opts) {
        const keepState = !!(opts && opts.keepState);
        const modal = byId("caSchedBoardModal");
        const back = byId("caSchedBoardBackdrop");
        if (modal) {
            modal.hidden = true;
            modal.style.visibility = "";
            modal.style.pointerEvents = "";
        }
        if (back) {
            back.hidden = true;
            back.style.visibility = "";
            back.style.pointerEvents = "";
        }
        // Always clear schedule-board scroll lock + any soft-hide leftovers.
        document.body.classList.remove("ca-sched-board-open");
        stopPoll();
        closeEdit({ keepState: true });
        closeBulk({ keepState: true });
        if (!keepState && !_restoring) clearUiState();
    }

    /** Unlock page scroll / tear down invisible overlays without wiping filters if keepState. */
    function releaseBoardForNavigation() {
        closeModal({ keepState: true });
        // Safety: clear other accidental locks left by half-opened editor flows.
        try {
            if (!document.body.classList.contains("bulk-v2-editor-open")) {
                document.body.classList.remove("bulk-v2-drawer-open");
            }
        } catch (_) {}
        restoreBulkEditorZ();
    }
    function startPoll() {
        stopPoll();
        _pollTimer = setInterval(() => {
            if (document.hidden) return;
            const modal = byId("caSchedBoardModal");
            if (!modal || modal.hidden) return;
            void refreshBoard({ silent: true });
        }, 15000);
    }
    function stopPoll() {
        if (_pollTimer) clearInterval(_pollTimer);
        _pollTimer = null;
    }

    function computeStatsFromItems(items) {
        const stats = {
            total: 0,
            unscheduled: 0,
            scheduled: 0,
            publishing: 0,
            published: 0,
            failed: 0,
        };
        (items || []).forEach((it) => {
            const st = String(it.board_status || "unscheduled");
            if (stats[st] != null) stats[st] += 1;
            stats.total += 1;
        });
        return stats;
    }

    function applyBoardFilters(opts) {
        const resetPage = !(opts && opts.keepPage);
        const q = ((byId("caSchedSearch") && byId("caSchedSearch").value) || "").trim().toLowerCase();
        const status = (byId("caSchedFilterStatus") && byId("caSchedFilterStatus").value) || "";
        const siteFilter = (byId("caSchedFilterSite") && byId("caSchedFilterSite").value) || "";
        const catFilter = (byId("caSchedFilterCategory") && byId("caSchedFilterCategory").value) || "";

        _items = (_allItems || []).filter((it) => {
            const st = String(it.board_status || "unscheduled");
            if (status && st !== status) return false;
            if (siteFilter) {
                const want = normalizeBoardWebsiteUrl(siteFilter);
                if (!want) return false;
                const urls = itemWebsiteUrls(it);
                if (!urls.includes(want)) return false;
            }
            if (catFilter) {
                const catKey = String(it.category_id != null ? it.category_id : it.category_label || "").trim();
                if (catKey !== catFilter) return false;
            }
            if (q) {
                const kw = String(it.keyword || "").toLowerCase();
                const title = String(it.title || "").toLowerCase();
                if (!kw.includes(q) && !title.includes(q)) return false;
            }
            return true;
        });

        if (resetPage) _page = 1;
        const maxPage = Math.max(1, totalPages());
        if (_page > maxPage) _page = maxPage;

        fillSiteFilter({ sites: _boardSites, items: _allItems });
        fillCategoryFilter({ items: _allItems });
        restoreFilterSelectValues();
        renderStats(computeStatsFromItems(_items));
        renderGrid({ force: true });
        updateSelectedCount();
        persistUiStateSoon();
    }

    async function refreshBoard(opts) {
        const silent = !!(opts && opts.silent);
        const keepPage = !!(opts && opts.keepPage) || silent;
        const seq = ++_refreshSeq;
        try {
            const data = await api("POST", "/content-ai/bulk-publish/board", {
                limit: 500,
                include_sites: !silent && !_boardSites.length,
            });
            if (seq !== _refreshSeq) return;
            _allItems = (data && data.items) || [];
            if (data && data.sites && data.sites.length) _boardSites = data.sites;
            applyBoardFilters({ keepPage: keepPage });
        } catch (e) {
            if (seq !== _refreshSeq) return;
            if (!silent) toast(String(e.message || e));
            _allItems = [];
            _items = [];
            renderStats({ total: 0, unscheduled: 0, scheduled: 0, publishing: 0, published: 0, failed: 0 });
            const grid = byId("caSchedGrid");
            if (grid) {
                grid.innerHTML = "";
                const empty = byId("caSchedEmpty");
                if (empty) {
                    empty.hidden = false;
                    empty.textContent = "Không tải được danh sách. Bấm Làm mới để thử lại.";
                }
            }
        }
    }

    function optionsSig(entries) {
        return entries.map(([id, label]) => id + "\t" + label).join("\n");
    }

    /** Valid http(s) URL with a domain extension (.com, .vn, .com.vn, .local, …). */
    function normalizeBoardWebsiteUrl(value) {
        const raw = String(value || "").trim();
        if (!raw) return "";
        const lower = raw.toLowerCase();
        if (!lower.startsWith("http://") && !lower.startsWith("https://")) return "";
        let parsed;
        try {
            parsed = new URL(raw);
        } catch (_) {
            return "";
        }
        const scheme = String(parsed.protocol || "")
            .replace(":", "")
            .toLowerCase();
        if (scheme !== "http" && scheme !== "https") return "";
        const host = String(parsed.hostname || "")
            .trim()
            .toLowerCase();
        if (
            !host ||
            !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,})(?:\.[a-z]{2,})?$/i.test(host)
        ) {
            return "";
        }
        let netloc = host;
        const port = parsed.port ? Number(parsed.port) : 0;
        if (port && !((scheme === "http" && port === 80) || (scheme === "https" && port === 443))) {
            netloc = host + ":" + port;
        }
        return scheme + "://" + netloc;
    }

    function itemWebsiteUrls(it) {
        const out = [];
        const seen = new Set();
        [it && it.website_url, it && it.website_label, it && it.website_id].forEach((v) => {
            const n = normalizeBoardWebsiteUrl(v);
            if (n && !seen.has(n)) {
                seen.add(n);
                out.push(n);
            }
        });
        return out;
    }

    function fillSiteFilter(data) {
        const sel = byId("caSchedFilterSite");
        if (!sel) return;
        const cur = normalizeBoardWebsiteUrl(sel.value) || "";
        const seen = new Map();
        const addUrl = (value) => {
            const norm = normalizeBoardWebsiteUrl(value);
            if (!norm || seen.has(norm)) return;
            seen.set(norm, norm);
        };
        ((data && data.sites) || []).forEach((s) => {
            addUrl(s && s.label);
            addUrl(s && s.id);
            addUrl(s && s.url);
        });
        ((data && data.items) || []).forEach((it) => {
            itemWebsiteUrls(it).forEach(addUrl);
        });
        const entries = Array.from(seen.entries()).sort((a, b) =>
            a[1].localeCompare(b[1], undefined, { sensitivity: "base" })
        );
        const sig = "site:" + optionsSig(entries);
        if (sel.dataset.optSig === sig) {
            if (cur) sel.value = cur;
            else if (sel.dataset.restoreValue && seen.has(sel.dataset.restoreValue)) {
                sel.value = sel.dataset.restoreValue;
            }
            return;
        }
        sel.dataset.optSig = sig;
        sel.innerHTML =
            '<option value="">Website: Tất cả</option>' +
            entries.map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join("");
        if (cur && seen.has(cur)) sel.value = cur;
        else if (sel.dataset.restoreValue && seen.has(sel.dataset.restoreValue)) {
            sel.value = sel.dataset.restoreValue;
        } else {
            sel.value = "";
        }
    }

    function fillCategoryFilter(data) {
        const sel = byId("caSchedFilterCategory");
        if (!sel) return;
        const cur = sel.value;
        const seen = new Map();
        ((data && data.items) || []).forEach((it) => {
            const id = String(it.category_id || it.category_label || "").trim();
            if (!id) return;
            if (!seen.has(id)) seen.set(id, it.category_label || id);
        });
        const entries = Array.from(seen.entries());
        const sig = "cat:" + optionsSig(entries);
        if (sel.dataset.optSig === sig) {
            if (cur) sel.value = cur;
            else if (sel.dataset.restoreValue && seen.has(sel.dataset.restoreValue)) {
                sel.value = sel.dataset.restoreValue;
            }
            return;
        }
        sel.dataset.optSig = sig;
        sel.innerHTML =
            '<option value="">Danh mục: Tất cả</option>' +
            entries.map(([id, label]) => `<option value="${esc(id)}">${esc(label)}</option>`).join("");
        if (cur) sel.value = cur;
        else if (sel.dataset.restoreValue && seen.has(sel.dataset.restoreValue)) {
            sel.value = sel.dataset.restoreValue;
        }
    }

    function updateSelectedCount() {
        const el = byId("caSchedSelectedCount");
        if (el) el.textContent = `Đã chọn ${_selected.size} bài`;
        persistUiStateSoon();
    }

    function renderStats(stats) {
        const s = stats || {};
        const set = (id, v) => {
            const el = byId(id);
            if (el) el.textContent = String(v != null ? v : 0);
        };
        set("caSchedStatTotal", s.total != null ? s.total : _items.length);
        set("caSchedStatUnsched", s.unscheduled);
        set("caSchedStatSched", (Number(s.scheduled) || 0) + (Number(s.publishing) || 0));
        set("caSchedStatPub", s.published);
        set("caSchedStatFail", s.failed);
    }

    function pageItems() {
        const start = (_page - 1) * _pageSize;
        return _items.slice(start, start + _pageSize);
    }

    function totalPages() {
        if (!_items.length) return 0;
        return Math.max(1, Math.ceil(_items.length / _pageSize));
    }

    function updatePager() {
        const info = byId("caSchedPageInfo");
        const start = _items.length ? (_page - 1) * _pageSize + 1 : 0;
        const end = Math.min(_page * _pageSize, _items.length);
        if (info) info.textContent = `Hiển thị ${start} - ${end} trong tổng số ${_items.length} bài`;

        const nums = byId("caSchedPageNums");
        const tp = totalPages();
        if (nums) {
            if (!tp) {
                nums.innerHTML = "";
            } else {
                let first = 1;
                let last = Math.min(tp, 10);
                if (tp > 10) {
                    last = Math.min(tp, Math.max(10, _page));
                    first = Math.max(1, last - 9);
                    last = Math.min(tp, first + 9);
                }
                let html = "";
                for (let p = first; p <= last; p++) {
                    const active = p === _page ? " is-active" : "";
                    html +=
                        `<button type="button" class="ca-sched-page-num${active}" data-page="${p}" aria-label="Trang ${p}"` +
                        (p === _page ? ' aria-current="page"' : "") +
                        `>${p}</button>`;
                }
                nums.innerHTML = html;
            }
        }

        const prev = byId("caSchedPrev");
        const next = byId("caSchedNext");
        if (prev) prev.disabled = _page <= 1 || !tp;
        if (next) next.disabled = _page >= tp || !tp;
    }

    function renderGrid(opts) {
        const force = !!(opts && opts.force);
        const grid = byId("caSchedGrid");
        const empty = byId("caSchedEmpty");
        if (!grid) return;
        const rows = pageItems();
        const sig =
            _page +
            "|" +
            _pageSize +
            "|" +
            rows
                .map((it) => {
                    const s = it.schedule || {};
                    return [
                        it.project_id,
                        it.board_status,
                        it.keyword,
                        it.website_label,
                        s.id,
                        s.status,
                        s.publish_at || s.scheduled_at || "",
                        _selected.has(String(it.project_id)) ? "1" : "0",
                    ].join(":");
                })
                .join(";");
        if (!force && sig === _lastGridSig && !grid.querySelector(".ca-sched-loading")) {
            updatePager();
            return;
        }
        _lastGridSig = sig;
        if (!_items.length) {
            grid.innerHTML = "";
            if (empty) {
                empty.hidden = false;
                const hasRows = (() => {
                    try {
                        const c = core();
                        const rows = c && c.getRows ? c.getRows() : [];
                        return rows && rows.length > 0;
                    } catch (_) {
                        return false;
                    }
                })();
                empty.textContent = hasRows
                    ? "Chưa tìm thấy bài đã viết có project. Hãy hoàn tất viết bài hoặc bấm Làm mới."
                    : "Chưa có bài viết để đặt lịch.";
            }
        } else {
            if (empty) empty.hidden = true;
            grid.innerHTML = rows.map(cardHtml).join("");
        }
        updatePager();
        ensureGridDelegation();
    }

    function cardHtml(it) {
        const pid = String(it.project_id || "");
        const st = String(it.board_status || "unscheduled");
        const checked = _selected.has(pid) ? " checked" : "";
        const sched = it.schedule || {};
        const when = sched.publish_at || sched.scheduled_at || "";
        const whenTxt = when
            ? `<div class="ca-sched-time">🕒 ${esc(String(when).replace("T", " ").slice(0, 16))} (${TZ})</div>`
            : `<div class="ca-sched-time ca-sched-time--empty" aria-hidden="true">&nbsp;</div>`;
        const err =
            st === "failed" && sched.last_error
                ? `<div class="ca-sched-err">Lỗi: ${esc(sched.last_error)}</div>`
                : "";
        const preview =
            `<button type="button" class="ca-sched-btn outline" data-act="preview" data-pid="${esc(pid)}">Xem trước</button>`;
        const editBtn =
            `<button type="button" class="ca-sched-btn outline" data-act="edit-article" data-pid="${esc(pid)}">Sửa</button>`;
        let row2 = "";
        if (st === "unscheduled") {
            row2 =
                `<button type="button" class="ca-sched-btn is-outline-primary" data-act="schedule" data-pid="${esc(pid)}">Đặt lịch</button>` +
                `<button type="button" class="ca-sched-btn is-outline-success" data-act="publish" data-pid="${esc(pid)}">Đăng ngay</button>`;
        } else if (st === "scheduled") {
            row2 =
                `<button type="button" class="ca-sched-btn is-outline-danger" data-act="cancel" data-pid="${esc(pid)}" data-sid="${esc(sched.id || "")}">Hủy lịch</button>` +
                `<button type="button" class="ca-sched-btn is-outline-success" data-act="publish" data-pid="${esc(pid)}">Đăng ngay</button>`;
        } else if (st === "publishing") {
            row2 =
                `<button type="button" class="ca-sched-btn outline" disabled>Đang đăng…</button>` +
                `<button type="button" class="ca-sched-btn outline" disabled>—</button>`;
        } else if (st === "published") {
            const url = sched.published_url || sched.wp_post_url || "";
            row2 = url
                ? `<a class="ca-sched-btn is-outline-success" href="${esc(url)}" target="_blank" rel="noopener">Xem bài</a>` +
                  `<button type="button" class="ca-sched-btn outline" disabled>Đã đăng</button>`
                : `<button type="button" class="ca-sched-btn outline" disabled>Đã đăng</button>` +
                  `<button type="button" class="ca-sched-btn outline" disabled>—</button>`;
        } else {
            row2 =
                `<button type="button" class="ca-sched-btn is-outline-danger" data-act="retry" data-sid="${esc(sched.id || "")}">Thử lại</button>` +
                `<button type="button" class="ca-sched-btn is-outline-danger" data-act="cancel" data-pid="${esc(pid)}" data-sid="${esc(sched.id || "")}">Hủy lịch</button>`;
        }
        return (
            `<article class="ca-sched-card" data-pid="${esc(pid)}" data-status="${esc(st)}">` +
            `<div class="ca-sched-card-top">` +
            `<label><input type="checkbox" class="ca-sched-chk" data-pid="${esc(pid)}"${checked} /></label>` +
            `<span class="ca-sched-badge ${esc(st)}">${esc(STATUS_LABEL[st] || st)}</span>` +
            `</div><div class="ca-sched-card-body">` +
            `<div class="ca-sched-kw">${esc(it.keyword || "—")}</div>` +
            `<div class="ca-sched-meta"><span class="lbl">Website:</span> ${esc(it.website_label || "—")}</div>` +
            `<div class="ca-sched-meta"><span class="lbl">Danh mục:</span> ${esc(it.category_label || it.category_id || "—")}</div>` +
            `${whenTxt}${err}</div>` +
            `<div class="ca-sched-card-actions">${preview}${editBtn}${row2}</div></article>`
        );
    }

    function wireCardActions() {
        if (_gridBound) return;
        const root = byId("caSchedBoardModal");
        if (!root) return;
        _gridBound = true;
        // Bind on the board modal (bubble). Survives card innerHTML re-renders via delegation.
        root.addEventListener("change", onDelegatedGridChange);
        root.addEventListener("click", onDelegatedGridClick);
    }

    function ensureGridDelegation() {
        // Re-bind if the modal was replaced / not ready on first wire().
        if (!_gridBound) wireCardActions();
    }

    function onDelegatedGridChange(e) {
        const t = e.target;
        if (!t || !t.classList || !t.classList.contains("ca-sched-chk")) return;
        const grid = byId("caSchedGrid");
        if (!grid || !grid.contains(t)) return;
        const pid = t.getAttribute("data-pid");
        if (!pid) return;
        if (t.checked) _selected.add(pid);
        else _selected.delete(pid);
        updateSelectedCount();
    }

    function onDelegatedGridClick(e) {
        const grid = byId("caSchedGrid");
        if (!grid) return;
        const btn = e.target && e.target.closest ? e.target.closest("[data-act]") : null;
        if (!btn || !grid.contains(btn)) return;
        if (btn.disabled || btn.getAttribute("aria-disabled") === "true" || btn.dataset.busy === "1") return;
        e.preventDefault();
        void onCardAct(btn);
    }

    function findBoardItem(pid) {
        const want = String(pid || "");
        return (
            _items.find((x) => String(x.project_id) === want) ||
            _allItems.find((x) => String(x.project_id) === want) ||
            null
        );
    }

    function resolveRowIdForProject(pid) {
        const want = String(pid || "").trim();
        if (!want) return "";
        const u = ui();
        try {
            const merged = u && u.getMergedArticles ? u.getMergedArticles() : [];
            for (let i = 0; i < (merged || []).length; i++) {
                const m = merged[i];
                if (m && m.job && String(m.job.project_id) === want && m.row && m.row.id) {
                    return String(m.row.id);
                }
            }
        } catch (_) {}
        const it = findBoardItem(want);
        const kw = String((it && it.keyword) || "")
            .trim()
            .toLowerCase();
        const c = core();
        const rows = (c && c.getRows ? c.getRows() : []) || [];
        if (kw) {
            const byKw = rows.find((r) => String(r.keyword || "").trim().toLowerCase() === kw);
            if (byKw && byKw.id) return String(byKw.id);
        }
        try {
            const jobs = (u && u.getJobItems ? u.getJobItems() : []) || [];
            const job = jobs.find((j) => String(j.project_id || "") === want);
            if (job && job.keyword) {
                const jkw = String(job.keyword).trim().toLowerCase();
                const byJob = rows.find((r) => String(r.keyword || "").trim().toLowerCase() === jkw);
                if (byJob && byJob.id) return String(byJob.id);
            }
        } catch (_) {}
        return "";
    }

    function elevateBulkEditorOverBoard() {
        ["bulkV2ModalBackdrop", "bulkV2Modal"].forEach((id, idx) => {
            const el = byId(id);
            if (!el) return;
            if (el.dataset.caSchedZSaved == null) el.dataset.caSchedZSaved = el.style.zIndex || "";
            el.style.zIndex = String(Number(EDITOR_OVER_BOARD_Z) + idx);
        });
    }

    function restoreBulkEditorZ() {
        ["bulkV2ModalBackdrop", "bulkV2Modal"].forEach((id) => {
            const el = byId(id);
            if (!el || el.dataset.caSchedZSaved == null) return;
            el.style.zIndex = el.dataset.caSchedZSaved;
            delete el.dataset.caSchedZSaved;
        });
    }

    function restoreBoardVisibility() {
        const board = byId("caSchedBoardModal");
        const back = byId("caSchedBoardBackdrop");
        if (board) {
            board.style.visibility = "";
            board.style.pointerEvents = "";
        }
        if (back) {
            back.style.visibility = "";
            back.style.pointerEvents = "";
        }
    }

    function watchBulkEditorClose() {
        if (_editorWatch) {
            try {
                _editorWatch.disconnect();
            } catch (_) {}
            _editorWatch = null;
        }
        _editorWatch = new MutationObserver(() => {
            if (!document.body.classList.contains("bulk-v2-editor-open")) {
                restoreBulkEditorZ();
                // Board was closed before opening the editor — do not resurrect it.
                document.body.classList.remove("ca-sched-board-open");
                try {
                    _editorWatch.disconnect();
                } catch (_) {}
                _editorWatch = null;
            }
        });
        _editorWatch.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    }

    function triggerBulkEditor(rowId) {
        const id = String(rowId || "");
        if (!id) return false;
        const escId =
            window.CSS && typeof CSS.escape === "function"
                ? CSS.escape(id)
                : String(id).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        const sel = '[data-bulk-edit-row="' + escId + '"]';
        const btn = document.querySelector(sel);
        if (!btn) return false;
        elevateBulkEditorOverBoard();
        watchBulkEditorClose();
        btn.click();
        return true;
    }

    function nextTick() {
        return new Promise((resolve) => setTimeout(resolve, 0));
    }

    async function openArticleFromBoard(pid, act) {
        const want = String(pid || "").trim();
        if (!want) {
            toast("Thiếu project_id.", "error");
            return false;
        }
        // Leave the click call stack before heavy DOM work.
        await nextTick();

        const rowId = resolveRowIdForProject(want);
        // Always tear down schedule overlays + body scroll lock BEFORE navigating.
        releaseBoardForNavigation();
        await nextTick();

        const u = ui();
        if (u && typeof u.openEditorByProjectId === "function") {
            elevateBulkEditorOverBoard();
            watchBulkEditorClose();
            await u.openEditorByProjectId(want, { tab: act === "edit-article" ? "setup" : "review" });
            return true;
        }
        if (rowId && triggerBulkEditor(rowId)) return true;

        // Fallback: open in SEO Writing tab — scroll must already be unlocked.
        const c = core();
        if (c && typeof c.loadProject === "function") {
            try {
                await Promise.race([
                    Promise.resolve(c.loadProject(want)),
                    new Promise((_, rej) => setTimeout(() => rej(new Error("Mở bài quá lâu.")), 15000)),
                ]);
            } catch (e) {
                document.body.classList.remove("ca-sched-board-open");
                throw e;
            }
            document.body.classList.remove("ca-sched-board-open");
            toast("Đã mở bài trong tab viết. Bấm Đặt lịch để quay lại bảng.", "info");
            return true;
        }
        toast("Không tìm thấy bài tương ứng trong danh sách bulk.", "error");
        return false;
    }

    function setBtnBusy(btn, on, label) {
        if (!btn) return;
        if (on) {
            if (btn.dataset.labelSave == null) btn.dataset.labelSave = btn.textContent || "";
            btn.dataset.busy = "1";
            btn.disabled = true;
            btn.setAttribute("aria-busy", "true");
            if (label) btn.textContent = label;
        } else {
            btn.dataset.busy = "";
            btn.disabled = false;
            btn.removeAttribute("aria-busy");
            if (btn.dataset.labelSave != null) {
                btn.textContent = btn.dataset.labelSave;
                delete btn.dataset.labelSave;
            }
        }
    }

    async function onCardAct(btn) {
        // Do not gate Preview/Edit/Schedule on global _busy (submit lock) — that felt like a freeze.
        if (btn.dataset.busy === "1") return;
        const act = btn.getAttribute("data-act");
        const pid = btn.getAttribute("data-pid") || "";
        const sid = btn.getAttribute("data-sid") || "";
        if (act === "preview" || act === "edit-article") {
            if (_cardActBusy) return;
            _cardActBusy = true;
            setBtnBusy(btn, true, "Đang mở…");
            try {
                await openArticleFromBoard(pid, act);
            } catch (e) {
                toast(String((e && e.message) || e), "error");
            } finally {
                setBtnBusy(btn, false);
                _cardActBusy = false;
            }
            return;
        }
        if (act === "schedule") {
            void openEdit(pid, { intent: "schedule" });
            return;
        }
        if (act === "cancel") {
            if (_cardActBusy) return;
            if (!window.confirm("Hủy lịch đăng bài này?")) return;
            _cardActBusy = true;
            setBtnBusy(btn, true, "Đang hủy…");
            try {
                await api("POST", "/content-ai/bulk-publish/cancel-schedule", {
                    schedule_ids: sid ? [Number(sid)] : null,
                    project_ids: pid ? [pid] : null,
                });
                toast("Đã hủy lịch.");
                await refreshBoard();
            } catch (e) {
                toast(String(e.message || e));
            } finally {
                setBtnBusy(btn, false);
                _cardActBusy = false;
            }
            return;
        }
        if (act === "retry") {
            if (_cardActBusy) return;
            if (!sid) return toast("Thiếu schedule_id.");
            _cardActBusy = true;
            setBtnBusy(btn, true, "Đang thử…");
            try {
                const out = await api("POST", "/content-ai/bulk-publish/retry", { schedule_id: Number(sid) });
                toast(out.queued ? "Đã đưa vào hàng đợi thử lại (Celery)." : "Đã thử lại.");
                await refreshBoard();
            } catch (e) {
                toast(String(e.message || e));
            } finally {
                setBtnBusy(btn, false);
                _cardActBusy = false;
            }
            return;
        }
        if (act === "publish") {
            void openEdit(pid, { intent: "publish" });
        }
    }

    function applyEditIntent(intent, opts) {
        _editIntent = intent === "publish" ? "publish" : "schedule";
        const multi = !!(opts && opts.multi);
        const atField = byId("caSchedEditAt") && byId("caSchedEditAt").closest(".ca-sched-field");
        const slugField = byId("caSchedEditSlug") && byId("caSchedEditSlug").closest(".ca-sched-field");
        const modeField = byId("caSchedEditMode") && byId("caSchedEditMode").closest(".ca-sched-field");
        const saveBtn = byId("caSchedEditSave");
        const hideScheduleOnly = _editIntent === "publish";
        if (atField) atField.hidden = hideScheduleOnly;
        if (slugField) slugField.hidden = hideScheduleOnly;
        if (modeField) modeField.hidden = false;
        if (saveBtn) {
            saveBtn.textContent = hideScheduleOnly ? "Đăng ngay" : "Lưu lịch";
            saveBtn.classList.toggle("success", hideScheduleOnly);
            saveBtn.classList.toggle("primary", !hideScheduleOnly);
        }
        if (multi && hideScheduleOnly) {
            const titleEl = byId("caSchedEditTitle");
            if (titleEl) titleEl.textContent = `Đăng ngay ${_publishIds.length} bài đã chọn`;
        }
    }

    async function openEdit(pid, opts) {
        const restore = opts && opts.restore && typeof opts.restore === "object" ? opts.restore : null;
        const intent = (opts && opts.intent) || (restore && restore.editIntent) || "schedule";
        const modal = byId("caSchedEditModal");
        const back = byId("caSchedEditBackdrop");
        if (!modal) return toast("Không tìm thấy popup đặt lịch.");
        // Avoid re-rendering the same edit popup.
        if (
            !modal.hidden &&
            String(_editProjectId) === String(pid) &&
            !restore &&
            _editIntent === intent
        ) {
            persistUiStateSoon();
            return;
        }
        _editProjectId = pid;
        if (intent === "publish") {
            _publishIds =
                Array.isArray(opts && opts.publishIds) && opts.publishIds.length
                    ? opts.publishIds.map(String)
                    : [String(pid)];
        } else {
            _publishIds = [];
        }
        const it =
            _items.find((x) => String(x.project_id) === String(pid)) ||
            _allItems.find((x) => String(x.project_id) === String(pid));
        portalToBody([back, modal]);
        const hid = byId("caSchedEditProjectId");
        const titleEl = byId("caSchedEditTitle");
        const atEl = byId("caSchedEditAt");
        const slugEl = byId("caSchedEditSlug");
        const modeEl = byId("caSchedEditMode");
        if (!hid || !atEl) return toast("Form đặt lịch chưa sẵn sàng.");
        hid.value = pid;
        if (titleEl) {
            titleEl.textContent =
                intent === "publish"
                    ? (it && (it.title || it.keyword)) || "Đăng ngay bài viết"
                    : (it && (it.title || it.keyword)) || "Đặt lịch bài viết";
        }
        atEl.value = restore && restore.editAt ? restore.editAt : defaultLocal(30);
        bindDatetimePicker(atEl);
        if (slugEl) slugEl.value = restore && restore.editSlug != null ? restore.editSlug : (it && it.slug) || "";
        if (modeEl) modeEl.value = restore && restore.editMode ? restore.editMode : "publish";
        applyEditIntent(intent, { multi: _publishIds.length > 1 });
        modal.hidden = false;
        if (back) back.hidden = false;
        const saveBtn = byId("caSchedEditSave");
        setBtnBusy(saveBtn, true, "Đang tải…");
        try {
            await Promise.race([
                loadEditSites(it),
                new Promise((_, rej) =>
                    setTimeout(() => rej(new Error("Tải website/danh mục quá lâu. Thử lại.")), 20000)
                ),
            ]);
            if (restore) {
                const siteSel = byId("caSchedEditSite");
                const catSel = byId("caSchedEditCategory");
                if (siteSel && restore.editSiteId) {
                    siteSel.value = restore.editSiteId;
                    await loadEditCategories();
                }
                if (catSel && restore.editCategoryId) catSel.value = restore.editCategoryId;
                if (atEl && restore.editAt) atEl.value = restore.editAt;
                if (slugEl && restore.editSlug != null) slugEl.value = restore.editSlug;
                if (modeEl && restore.editMode) modeEl.value = restore.editMode;
            }
        } catch (e) {
            toast(String(e.message || e), "error");
        } finally {
            setBtnBusy(saveBtn, false);
            applyEditIntent(_editIntent, { multi: _publishIds.length > 1 });
        }
        persistUiStateSoon();
    }
    function closeEdit(opts) {
        const modal = byId("caSchedEditModal");
        const back = byId("caSchedEditBackdrop");
        if (modal) modal.hidden = true;
        if (back) back.hidden = true;
        _editProjectId = "";
        _publishIds = [];
        _editIntent = "schedule";
        const saveBtn = byId("caSchedEditSave");
        if (saveBtn) {
            delete saveBtn.dataset.labelSave;
            delete saveBtn.dataset.busy;
            saveBtn.disabled = false;
            saveBtn.removeAttribute("aria-busy");
        }
        applyEditIntent("schedule");
        if (!(opts && opts.keepState)) persistUiStateSoon();
    }
    async function loadEditSites(it) {
        const sel = byId("caSchedEditSite");
        if (!sel) return;
        const data = await api("GET", "/api/settings/publishing-sites?ts=" + Date.now());
        // Prefer WordPress (publish schedule uses WP), but still list all connected sites.
        let sites = flattenPublishingSites(data, ["wordpress"]);
        if (!sites.length) sites = flattenPublishingSites(data);
        const opts = ['<option value="">-- Chọn website --</option>'].concat(
            sites.map((s) => {
                const url = String(s.url || s.website_url || "").trim();
                return (
                    `<option value="${esc(s.id)}" data-url="${esc(url)}" data-platform="${esc(s.platform || "")}">` +
                    `${esc(siteOptionLabel(s))}</option>`
                );
            })
        );
        sel.innerHTML = opts.join("");
        if (!sites.length) {
            toast("Chưa có website kết nối — thêm trong Cài đặt → Site đăng bài.");
        }
        let chosen = "";
        if (it && it.website_id) chosen = String(it.website_id);
        if (!chosen && it && it.website) {
            const n = String(it.website || "")
                .replace(/\/+$/, "")
                .toLowerCase();
            const hit = sites.find(
                (s) =>
                    String(s.url || s.website_url || "")
                        .replace(/\/+$/, "")
                        .toLowerCase() === n
            );
            if (hit) chosen = String(hit.id);
        }
        if (chosen) sel.value = chosen;
        else if (sites.length === 1) sel.value = String(sites[0].id);
        await loadEditCategories();
    }
    async function fetchWpCategoriesForSite(siteId, fallbackUrl) {
        const sid = String(siteId || "").trim();
        const url = String(fallbackUrl || "").trim();
        const bodies = [];
        if (sid) bodies.push({ wp_site_id: sid });
        // Fallback: resolve credentials client-side (older servers / edge cases).
        if (!bodies.length && url) {
            throw new Error("Chọn website đã lưu để tải danh mục.");
        }
        const paths = [
            "/api/settings/publishing-sites/wordpress/categories",
            "/content-ai/wordpress/categories",
        ];
        let lastErr = "Không tải được danh mục.";
        for (const body of bodies) {
            for (const path of paths) {
                try {
                    const res = await fetch(path, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: authHeaders({ "Content-Type": "application/json" }),
                        body: JSON.stringify(body),
                    });
                    const data = await res.json().catch(() => ({}));
                    if (res.status === 404) {
                        lastErr = "API danh mục chưa sẵn sàng (404). Khởi động lại server rồi thử lại.";
                        continue;
                    }
                    if (!res.ok) {
                        const detail = data && data.detail;
                        lastErr =
                            typeof detail === "string"
                                ? detail
                                : Array.isArray(detail)
                                  ? detail.map((x) => (x && x.msg) || x).join("; ")
                                  : (detail && detail.message) || data.message || "HTTP " + res.status;
                        continue;
                    }
                    return data;
                } catch (e) {
                    lastErr = String((e && e.message) || e || lastErr);
                }
            }
        }
        throw new Error(lastErr);
    }
    async function loadEditCategories() {
        const siteSel = byId("caSchedEditSite");
        const catSel = byId("caSchedEditCategory");
        const hint = byId("caSchedEditCategoryHint");
        if (!siteSel || !catSel) return;
        const siteId = String(siteSel.value || "").trim();
        const opt = siteSel.selectedOptions && siteSel.selectedOptions[0];
        const url = opt ? opt.getAttribute("data-url") || "" : "";
        const seq = String(Date.now());
        catSel.dataset.loadSeq = seq;
        catSel.innerHTML = '<option value="">-- Đang tải danh mục… --</option>';
        catSel.disabled = true;
        if (hint) {
            hint.textContent = siteId ? "Đang tải danh mục từ website…" : "Chọn website trước.";
            hint.classList.remove("is-error", "is-ok");
        }
        if (!siteId) {
            catSel.innerHTML = '<option value="">-- Chọn danh mục --</option>';
            catSel.disabled = false;
            return;
        }
        try {
            const data = await fetchWpCategoriesForSite(siteId, url);
            if (catSel.dataset.loadSeq !== seq) return;
            if (data && data.ok === false) {
                throw new Error(data.message || "Không tải được danh mục từ WordPress.");
            }
            const items = (data && (data.items || data.categories)) || [];
            catSel.innerHTML =
                '<option value="">-- Chọn danh mục --</option>' +
                items
                    .map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.id)}</option>`)
                    .join("");
            if (hint) {
                hint.textContent = items.length
                    ? "Đã tải " + items.length + " danh mục."
                    : (data && data.message) || "Site chưa có danh mục.";
                hint.classList.toggle("is-ok", items.length > 0);
                hint.classList.toggle("is-error", items.length === 0);
            }
        } catch (e) {
            if (catSel.dataset.loadSeq !== seq) return;
            const msg = String((e && e.message) || e || "Không tải được danh mục.");
            catSel.innerHTML = '<option value="">-- Chọn danh mục --</option>';
            if (hint) {
                hint.textContent = msg;
                hint.classList.add("is-error");
                hint.classList.remove("is-ok");
            }
            toast(msg);
        } finally {
            if (catSel.dataset.loadSeq === seq) catSel.disabled = false;
        }
    }
    async function saveEdit() {
        if (_editIntent === "publish") {
            await confirmPublishFromPopup();
            return;
        }
        const pid = byId("caSchedEditProjectId").value;
        const at = byId("caSchedEditAt").value;
        const err = assertFuture(at);
        if (err) return toast(err, "error");
        const siteSel = byId("caSchedEditSite");
        const siteId = siteSel ? String(siteSel.value || "").trim() : "";
        if (!siteId) return toast("Vui lòng chọn website.", "warn");
        const opt = siteSel.selectedOptions && siteSel.selectedOptions[0];
        const siteUrl = opt ? opt.getAttribute("data-url") || "" : "";
        const cat = byId("caSchedEditCategory").value;
        const slugEl = byId("caSchedEditSlug");
        const slug = slugEl ? String(slugEl.value || "").trim() || null : null;
        const saveBtn = byId("caSchedEditSave");
        if (_busy) return;
        _busy = true;
        setBtnBusy(saveBtn, true, "Đang lưu…");
        try {
            const data = await api("POST", "/content-ai/bulk-publish/schedule-one", {
                project_id: pid,
                scheduled_at: at,
                wp_site_id: siteId || null,
                wp_url: siteUrl || null,
                wp_category_id: cat ? Number(cat) : null,
                slug,
            });
            if (!(data && (data.ok === true || data.item))) {
                throw new Error((data && data.detail) || "Không lưu được lịch đăng.");
            }
            closeEdit();
            toast("Lưu lịch thành công.", "success");
            // Refresh board in background — do not keep the save button waiting.
            void Promise.resolve()
                .then(() => refreshBoard({ silent: true }))
                .then(() => {
                    try {
                        if (ui() && ui().refresh) ui().refresh();
                    } catch (_) {}
                })
                .catch(() => {});
        } catch (e) {
            toast(String(e.message || e || "Lưu lịch thất bại."), "error");
            setBtnBusy(saveBtn, false);
            applyEditIntent("schedule");
        } finally {
            _busy = false;
        }
    }

    function readPublishWpFromForm() {
        const siteSel = byId("caSchedEditSite");
        const siteId = siteSel ? String(siteSel.value || "").trim() : "";
        if (!siteId) {
            toast("Vui lòng chọn website.", "warn");
            return null;
        }
        const opt = siteSel.selectedOptions && siteSel.selectedOptions[0];
        const siteUrl = opt ? opt.getAttribute("data-url") || "" : "";
        const cat = byId("caSchedEditCategory") ? byId("caSchedEditCategory").value : "";
        const modeEl = byId("caSchedEditMode");
        return {
            wp_site_id: siteId,
            wp_url: siteUrl || null,
            wp_category_id: cat ? Number(cat) : null,
            publish_mode: (modeEl && modeEl.value) || "publish",
            timezone: TZ,
        };
    }

    async function confirmPublishFromPopup() {
        const wp = readPublishWpFromForm();
        if (!wp) return;
        const ids = (_publishIds && _publishIds.length ? _publishIds : [byId("caSchedEditProjectId").value]).filter(Boolean);
        if (!ids.length) return toast("Chưa chọn bài.", "warn");
        const saveBtn = byId("caSchedEditSave");
        if (_busy) return;
        _busy = true;
        setBtnBusy(saveBtn, true, "Đang đăng…");
        try {
            await publishNow(ids, wp);
            closeEdit();
        } catch (e) {
            setBtnBusy(saveBtn, false);
            applyEditIntent("publish", { multi: ids.length > 1 });
        } finally {
            _busy = false;
        }
    }

    function openBulk(opts) {
        const restore = opts && opts.restore && typeof opts.restore === "object" ? opts.restore : null;
        const ids = Array.from(_selected);
        if (!ids.length && !restore) return toast("Chọn ít nhất một bài.");
        const modal = byId("caSchedBulkModal");
        const back = byId("caSchedBulkBackdrop");
        if (modal && !modal.hidden && !restore) {
            persistUiStateSoon();
            return;
        }
        const startEl = byId("caSchedBulkStart");
        if (startEl) {
            startEl.value = restore && restore.bulkStart ? restore.bulkStart : defaultLocal(30);
            bindDatetimePicker(startEl);
        }
        if (restore) {
            const modeEl = byId("caSchedBulkMode");
            const intEl = byId("caSchedBulkInterval");
            const customEl = byId("caSchedBulkCustom");
            const wrap = byId("caSchedBulkCustomWrap");
            if (modeEl && restore.bulkMode) modeEl.value = restore.bulkMode;
            if (intEl && restore.bulkInterval) intEl.value = restore.bulkInterval;
            if (customEl && restore.bulkCustom != null) customEl.value = restore.bulkCustom;
            if (wrap && intEl) wrap.hidden = intEl.value !== "custom";
        }
        modal.hidden = false;
        if (back) back.hidden = false;
        renderBulkPreview();
        persistUiStateSoon();
    }
    function closeBulk(opts) {
        const modal = byId("caSchedBulkModal");
        const back = byId("caSchedBulkBackdrop");
        if (modal) modal.hidden = true;
        if (back) back.hidden = true;
        if (!(opts && opts.keepState)) persistUiStateSoon();
    }
    function bulkIntervalMin() {
        const mode = byId("caSchedBulkMode").value;
        if (mode === "same") return 0;
        const v = byId("caSchedBulkInterval").value;
        if (v === "custom") return Math.max(5, Number(byId("caSchedBulkCustom").value) || 45);
        return Number(v) || 30;
    }
    function renderBulkPreview() {
        const box = byId("caSchedBulkPreview");
        if (!box) return;
        const start = byId("caSchedBulkStart").value;
        const ids = Array.from(_selected);
        const interval = bulkIntervalMin();
        const lines = ids.slice(0, 40).map((pid, i) => {
            const it = _items.find((x) => x.project_id === pid);
            let when = start;
            if (interval > 0 && start) {
                const d = new Date(start);
                d.setMinutes(d.getMinutes() + interval * i);
                when = defaultLocal(0).slice(0, 0) || "";
                const pad = (n) => String(n).padStart(2, "0");
                when =
                    d.getFullYear() +
                    "-" +
                    pad(d.getMonth() + 1) +
                    "-" +
                    pad(d.getDate()) +
                    "T" +
                    pad(d.getHours()) +
                    ":" +
                    pad(d.getMinutes());
            }
            return `<li><strong>${esc((it && it.title) || pid)}</strong> → ${esc(String(when).replace("T", " "))}</li>`;
        });
        box.innerHTML = `<ul>${lines.join("")}</ul>` + (ids.length > 40 ? `<p>… và ${ids.length - 40} bài khác</p>` : "");
    }
    async function confirmBulk() {
        const ids = Array.from(_selected);
        const start = byId("caSchedBulkStart").value;
        const err = assertFuture(start);
        if (err) return toast(err);
        const interval = bulkIntervalMin();
        if (_busy) return;
        _busy = true;
        try {
            const wp = await resolveWp();
            const c = core();
            const result = await api("POST", "/content-ai/bulk-publish/schedule-batch", {
                ...wp,
                bulk_job_id: (c && c.getBulkJobId && c.getBulkJobId()) || null,
                scheduled_at: start,
                interval_minutes: interval || null,
                timezone: TZ,
                publish_mode: "publish",
                items: ids.map((project_id) => ({ project_id })),
            });
            const count = result && result.count != null ? result.count : ((result && result.created) || []).length;
            const errors = (result && result.errors) || [];
            if (!count) {
                toast((errors[0] && errors[0].error) || "Không tạo được lịch.");
            } else {
                toast(`Đã đặt lịch ${count} bài.` + (errors.length ? ` (${errors.length} lỗi)` : ""));
            }
            closeBulk();
            await refreshBoard();
        } catch (e) {
            toast(String(e.message || e));
        } finally {
            _busy = false;
        }
    }

    async function publishNow(ids, wpPayload) {
        if (!ids.length) return toast("Chưa chọn bài.");
        if (_busy && !wpPayload) return;
        const heldBusy = _busy;
        if (!heldBusy) _busy = true;
        try {
            const wp = wpPayload || (await resolveWp());
            let ok = 0;
            let fail = 0;
            for (const project_id of ids) {
                try {
                    const out = await api("POST", "/content-ai/bulk-publish/publish-now-one", {
                        ...wp,
                        project_id,
                        publish_mode: (wp && wp.publish_mode) || "publish",
                        timezone: TZ,
                    });
                    if (out && out.item && out.item.deduped) ok++;
                    else ok++;
                } catch (_) {
                    fail++;
                }
            }
            toast(`Đã xếp hàng đăng: ${ok} OK` + (fail ? `, ${fail} lỗi` : "") + " (Celery/worker).", ok && !fail ? "success" : "info");
            await refreshBoard();
        } catch (e) {
            toast(String(e.message || e));
            throw e;
        } finally {
            if (!heldBusy) _busy = false;
        }
    }

    async function restoreUiStateOnce() {
        if (_didRestore) return;
        _didRestore = true;
        const st = readUiState();
        if (!st || !st.boardOpen) return;
        _restoring = true;
        try {
            ensureMainTab(st.mainTab || "bulk");
            // Wait a tick so tab switch can paint panels before opening modal.
            await new Promise((r) => setTimeout(r, 40));
            await openModal({ restore: st });
        } catch (_) {
            clearUiState();
        } finally {
            _restoring = false;
            persistUiStateSoon();
        }
    }

    function onScreenChange(nextTab) {
        if (_restoring) return;
        const next = String(nextTab || "");
        const board = byId("caSchedBoardModal");
        const boardOpen = !!(board && !board.hidden);
        // Leaving the Content AI bulk screen clears persisted schedule-board UI.
        if (next && next !== "bulk") {
            clearUiState();
            if (boardOpen) closeModal({ keepState: true });
        }
    }

    function wire() {
        const btn = byId("btnBulkV2Schedule");
        if (btn) {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopImmediatePropagation();
                void openModal();
            }, true);
        }
        const close = byId("caSchedBoardClose");
        const back = byId("caSchedBoardBackdrop");
        if (close) close.addEventListener("click", () => closeModal());
        if (back) back.addEventListener("click", () => closeModal());
        const refresh = byId("caSchedRefresh");
        if (refresh) refresh.addEventListener("click", () => void refreshBoard());
        const search = byId("caSchedSearch");
        if (search) {
            search.addEventListener("input", () => {
                if (_searchTimer) clearTimeout(_searchTimer);
                _searchTimer = setTimeout(() => applyBoardFilters(), 60);
            });
        }
        ["caSchedFilterStatus", "caSchedFilterSite", "caSchedFilterCategory"].forEach((id) => {
            const el = byId(id);
            if (el) el.addEventListener("change", () => applyBoardFilters());
        });
        const selAll = byId("caSchedSelectAll");
        if (selAll) {
            selAll.addEventListener("change", () => {
                if (selAll.checked) _items.forEach((it) => _selected.add(String(it.project_id)));
                else _selected.clear();
                renderGrid();
                updateSelectedCount();
            });
        }
        const pageSize = byId("caSchedPageSize");
        if (pageSize) {
            pageSize.addEventListener("change", () => {
                _pageSize = Number(pageSize.value) || 10;
                _page = 1;
                renderGrid();
                persistUiStateSoon();
            });
        }
        const prev = byId("caSchedPrev");
        const next = byId("caSchedNext");
        if (prev) {
            prev.addEventListener("click", () => {
                _page = Math.max(1, _page - 1);
                renderGrid();
                persistUiStateSoon();
            });
        }
        if (next) {
            next.addEventListener("click", () => {
                const max = totalPages() || 1;
                _page = Math.min(max, _page + 1);
                renderGrid();
                persistUiStateSoon();
            });
        }
        const pageNums = byId("caSchedPageNums");
        if (pageNums) {
            pageNums.addEventListener("click", (ev) => {
                const btnPage = ev.target.closest("[data-page]");
                if (!btnPage || !pageNums.contains(btnPage)) return;
                _page = Number(btnPage.getAttribute("data-page")) || 1;
                renderGrid();
                persistUiStateSoon();
            });
        }
        const bulkSched = byId("caSchedBulkSchedule");
        if (bulkSched) bulkSched.addEventListener("click", () => openBulk());
        const bulkPub = byId("caSchedBulkPublish");
        if (bulkPub) {
            bulkPub.addEventListener("click", () => {
                const ids = Array.from(_selected);
                if (!ids.length) return toast("Chọn bài cần đăng.");
                openEdit(ids[0], { intent: "publish", publishIds: ids });
            });
        }
        const editClose = byId("caSchedEditClose");
        const editCancel = byId("caSchedEditCancel");
        const editBack = byId("caSchedEditBackdrop");
        const editSave = byId("caSchedEditSave");
        if (editClose) editClose.addEventListener("click", () => closeEdit());
        if (editCancel) editCancel.addEventListener("click", () => closeEdit());
        if (editBack) editBack.addEventListener("click", () => closeEdit());
        if (editSave) editSave.addEventListener("click", () => void saveEdit());
        const editSite = byId("caSchedEditSite");
        if (editSite) {
            editSite.addEventListener("change", () => {
                void loadEditCategories();
                persistUiStateSoon();
            });
        }
        const editCat = byId("caSchedEditCategory");
        if (editCat) {
            editCat.addEventListener("change", () => persistUiStateSoon());
            editCat.addEventListener("focus", () => {
                // Reload if still empty after a prior failed attempt.
                if (editCat.options.length <= 1 && editSite && editSite.value) {
                    void loadEditCategories();
                }
            });
        }
        ["caSchedEditAt", "caSchedEditSlug", "caSchedEditMode"].forEach((id) => {
            const el = byId(id);
            if (!el) return;
            el.addEventListener("change", () => persistUiStateSoon());
            el.addEventListener("input", () => persistUiStateSoon());
        });

        const bulkClose = byId("caSchedBulkClose");
        const bulkCancel = byId("caSchedBulkCancel");
        const bulkBack = byId("caSchedBulkBackdrop");
        const bulkConfirm = byId("caSchedBulkConfirm");
        if (bulkClose) bulkClose.addEventListener("click", () => closeBulk());
        if (bulkCancel) bulkCancel.addEventListener("click", () => closeBulk());
        if (bulkBack) bulkBack.addEventListener("click", () => closeBulk());
        if (bulkConfirm) bulkConfirm.addEventListener("click", () => void confirmBulk());
        ["caSchedBulkStart", "caSchedBulkMode", "caSchedBulkInterval", "caSchedBulkCustom"].forEach((id) => {
            const el = byId(id);
            if (!el) return;
            el.addEventListener("change", () => {
                const wrap = byId("caSchedBulkCustomWrap");
                if (wrap && id === "caSchedBulkInterval") {
                    wrap.hidden = byId("caSchedBulkInterval").value !== "custom";
                }
                renderBulkPreview();
                persistUiStateSoon();
            });
            el.addEventListener("input", () => {
                renderBulkPreview();
                persistUiStateSoon();
            });
        });

        const boardBody = byId("caSchedBoardBody");
        if (boardBody) {
            boardBody.addEventListener(
                "scroll",
                () => {
                    persistUiStateSoon();
                },
                { passive: true }
            );
        }

        const tabMap = {
            tabMainSingle: "single",
            tabMainBulk: "bulk",
            tabMainAutoUpdate: "autoupdate",
        };
        Object.keys(tabMap).forEach((id) => {
            const el = byId(id);
            if (!el) return;
            el.addEventListener(
                "click",
                () => {
                    onScreenChange(tabMap[id]);
                },
                true
            );
        });

        // Persist across reload via sessionStorage; clear only on manual close / screen change.
        window.ContentAiScheduleBoard = {
            open: openModal,
            close: closeModal,
            refresh: refreshBoard,
            clearUiState: clearUiState,
        };
        wireCardActions();
        void restoreUiStateOnce();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
    else wire();
})();
