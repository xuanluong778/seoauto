/**
 * Content AI — Bulk Publish Center (Review step).
 * Depends on ContentAiBulkUi + ContentAiBulkCore.
 */
(function () {
    "use strict";

    /** @type {Record<string, object>} */
    let _readinessByProject = Object.create(null);
    let _modalProjectIds = [];

    function ui() {
        return window.ContentAiBulkUi || null;
    }

    function core() {
        return window.ContentAiBulkCore || null;
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

    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const d = data && data.detail;
            const msg = typeof d === "string" ? d : d && d.message ? d.message : `HTTP ${res.status}`;
            throw new Error(msg);
        }
        return data;
    }

    async function apiGet(path) {
        const res = await fetch(path, { headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
        return data;
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

    function requireImage() {
        const el = byId("bulkV2RequireImage");
        return !!(el && el.checked);
    }

    function getMergedArticles() {
        const u = ui();
        if (u && u.getMergedArticles) return u.getMergedArticles();
        const c = core();
        const rows = c && c.getRows ? c.getRows() : [];
        const jobs = u && u.getJobItems ? u.getJobItems() : [];
        const jobByKw = Object.create(null);
        jobs.forEach((j) => {
            const kw = String(j.keyword || "").trim().toLowerCase();
            if (kw) jobByKw[kw] = j;
        });
        return rows.map((row) => ({ row, job: jobByKw[String(row.keyword || "").trim().toLowerCase()] || null }));
    }

    function filterPublishableIds(projectIds) {
        const u = ui();
        const jobs = (u && u.getJobItems ? u.getJobItems() : []) || [];
        const byPid = Object.create(null);
        jobs.forEach((j) => {
            const pid = String(j.project_id || "").trim();
            if (pid) byPid[pid] = j;
        });
        const ok = [];
        const blocked = [];
        (projectIds || []).forEach((pid) => {
            const id = String(pid || "").trim();
            if (!id) return;
            const job = byPid[id];
            const project = u && u.getProjectById ? u.getProjectById(id) : null;
            const publishable =
                u && u.isJobPublishable
                    ? u.isJobPublishable(job, project)
                    : !!(job && job.status === "success");
            if (!publishable) {
                const kw = (job && job.keyword) || id;
                let msg = "Bài chưa sẵn sàng đăng.";
                if (job && job.status === "error") msg = "Lỗi LLM/API — không cho đăng hàng loạt.";
                else if (u && u.isContentEmpty && u.isContentEmpty(job)) msg = "Content rỗng — không cho đăng.";
                else if (!job || job.status !== "success") msg = "Bài chưa viết xong.";
                blocked.push({ kw, msg });
                return;
            }
            ok.push(id);
        });
        return { ok, blocked };
    }

    function getSelectedProjectIds() {
        const u = ui();
        if (u && u.getSelectedProjectIds) return u.getSelectedProjectIds();
        return [];
    }

    function getAllWrittenProjectIds() {
        const u = ui();
        if (u && u.getAllWrittenProjectIds) return u.getAllWrittenProjectIds();
        return [];
    }

    function getScheduleMap() {
        const u = ui();
        if (u && u.getScheduleByProject) return u.getScheduleByProject();
        return Object.create(null);
    }

    function getImageMeta() {
        const u = ui();
        if (u && u.getImageMetaByProject) return u.getImageMetaByProject();
        return Object.create(null);
    }

    async function loadReadiness(projectIds, opts) {
        const ids = [...new Set((projectIds || []).map((x) => String(x || "").trim()).filter(Boolean))];
        if (!ids.length) {
            _readinessByProject = Object.create(null);
            return;
        }
        const catEl = byId("bulkV2PubCategory");
        const catVal = catEl && catEl.value ? parseInt(catEl.value, 10) : null;
        const requireCat = !!(opts && opts.require_category);
        try {
            const data = await apiPost("/content-ai/bulk-publish/readiness-batch", {
                project_ids: ids,
                require_image: requireImage(),
                require_category: requireCat,
                wp_category_id: catVal && !Number.isNaN(catVal) ? catVal : null,
            });
            _readinessByProject = Object.create(null);
            ((data && data.items) || []).forEach((it) => {
                if (it && it.project_id) _readinessByProject[it.project_id] = it;
            });
        } catch (e) {
            toast(String(e.message || e));
        }
    }

    function isMissingContent(errs) {
        const t = (errs || []).join(" ").toLowerCase();
        return /title|meta|content|keyword|slug/.test(t);
    }

    function isMissingImage(errs, pid) {
        if ((errs || []).some((e) => /ảnh|image/.test(String(e).toLowerCase()))) return true;
        const img = getImageMeta()[pid];
        return img && String(img.status || "") !== "ok" && requireImage();
    }

    function computeStats(merged) {
        const schedMap = getScheduleMap();
        let total = merged.length;
        let ready = 0;
        let missingContent = 0;
        let missingImage = 0;
        let scheduled = 0;
        let published = 0;
        let errN = 0;
        const rowErrors = [];

        merged.forEach(({ row, job }) => {
            const pid = job && job.project_id ? String(job.project_id) : "";
            const kw = row.keyword || pid || "—";
            if (job && job.status === "error") {
                errN++;
                rowErrors.push({ kw, msg: job.error || "Lỗi LLM/API khi viết bài." });
            } else if (job && job.status === "success") {
                const u = ui();
                if (u && u.isContentEmpty && u.isContentEmpty(job)) {
                    errN++;
                    rowErrors.push({ kw, msg: "Content rỗng — không cho đăng hàng loạt." });
                }
            }
            const sched = pid ? schedMap[pid] : null;
            if (sched) {
                const st = String(sched.status || "").toLowerCase();
                if (st === "published") published++;
                else if (st === "scheduled" || st === "publishing") scheduled++;
                else if (st === "failed") {
                    errN++;
                    rowErrors.push({ kw, msg: sched.last_error || "Lỗi đăng/lịch." });
                }
            }
            if (pid && _readinessByProject[pid]) {
                const r = _readinessByProject[pid];
                if (r.ready) ready++;
                else {
                    if (isMissingContent(r.errors)) missingContent++;
                    if (isMissingImage(r.errors, pid)) missingImage++;
                    (r.errors || []).forEach((msg) => rowErrors.push({ kw, msg }));
                }
            } else if (job && job.status === "success") {
                missingContent++;
            }
        });

        return { total, ready, missingContent, missingImage, scheduled, published, errN, rowErrors };
    }

    function renderStats() {
        const merged = getMergedArticles();
        const st = computeStats(merged);
        const set = (id, v) => {
            const el = byId(id);
            if (el) el.textContent = String(v);
        };
        set("pubStatTotal", st.total);
        set("pubStatReady", st.ready);
        set("pubStatMissingContent", st.missingContent);
        set("pubStatMissingImage", st.missingImage);
        set("pubStatScheduled", st.scheduled);
        set("pubStatPublished", st.published);
        set("pubStatError", st.errN);

        const errUl = byId("bulkV2PublishRowErrors");
        if (errUl) {
            const uniq = [];
            const seen = new Set();
            st.rowErrors.forEach(({ kw, msg }) => {
                const k = kw + "|" + msg;
                if (seen.has(k)) return;
                seen.add(k);
                uniq.push({ kw, msg });
            });
            if (!uniq.length) {
                errUl.hidden = true;
                errUl.innerHTML = "";
            } else {
                errUl.hidden = false;
                errUl.innerHTML = uniq
                    .slice(0, 40)
                    .map((x) => `<li><strong>${esc(x.kw)}</strong>: ${esc(x.msg)}</li>`)
                    .join("");
            }
        }
    }

    async function refreshPublishCenter() {
        const ids = getAllWrittenProjectIds();
        await loadReadiness(ids);
        renderStats();
    }

    async function loadWpSites() {
        const sel = byId("bulkV2PubSite");
        if (!sel) return;
        const data = await apiGet("/api/settings/publishing-sites?ts=" + Date.now());
        const sites = ((data && (data.items || data.sites)) || []).filter(
            (s) => String(s.platform || "").toLowerCase() === "wordpress"
        );
        const tw = byId("bulkTargetWebsite") && byId("bulkTargetWebsite").value.trim();
        sel.innerHTML = sites
            .map((s) => `<option value="${esc(s.id)}" data-url="${esc(s.url)}">${esc(s.url || s.id)}</option>`)
            .join("");
        if (tw) {
            const n = tw.replace(/\/+$/, "").toLowerCase();
            const hit = sites.find((s) => String(s.url || "").replace(/\/+$/, "").toLowerCase() === n);
            if (hit) sel.value = hit.id;
        }
    }

    async function loadCategoriesForModal() {
        const sel = byId("bulkV2PubSite");
        const catSel = byId("bulkV2PubCategory");
        const hint = byId("bulkV2PubCategoryHint");
        if (!sel || !catSel) return;
        const siteId = sel.value;
        const opt = sel.selectedOptions && sel.selectedOptions[0];
        const url = opt ? opt.getAttribute("data-url") || "" : "";
        if (!siteId && !url) {
            if (hint) hint.textContent = "Chọn website trước.";
            return;
        }
        if (hint) hint.textContent = "Đang tải danh mục…";
        try {
            const data = await apiPost("/content-ai/wordpress/categories", {
                wp_site_id: siteId || null,
                wp_url: url || null,
            });
            const items = (data && data.items) || [];
            catSel.innerHTML =
                '<option value="">-- Chọn danh mục --</option>' +
                items.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");
            if (hint) hint.textContent = `Đã tải ${items.length} danh mục.`;
        } catch (e) {
            if (hint) hint.textContent = String(e.message || e);
        }
    }

    function getIntervalMinutes() {
        const sel = byId("bulkV2PubInterval");
        const custom = byId("bulkV2PubIntervalCustom");
        if (!sel) return 60;
        if (sel.value === "custom") {
            const n = parseInt(custom && custom.value, 10);
            return Number.isNaN(n) || n < 5 ? 60 : n;
        }
        return parseInt(sel.value, 10) || 60;
    }

    function buildScheduleTimes(count, startLocal, intervalMin) {
        const start = new Date(startLocal);
        if (Number.isNaN(start.getTime())) return [];
        const out = [];
        for (let i = 0; i < count; i++) {
            const d = new Date(start.getTime() + i * intervalMin * 60000);
            const pad = (n) => String(n).padStart(2, "0");
            out.push(
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
        return out;
    }

    function validateModalProjects(projectIds, requireCat) {
        const catEl = byId("bulkV2PubCategory");
        const catId = catEl && catEl.value ? parseInt(catEl.value, 10) : null;
        const siteEl = byId("bulkV2PubSite");
        if (!siteEl || !siteEl.value) {
            return { ok: false, errors: [{ kw: "—", msg: "Chọn website WordPress." }], readyIds: [] };
        }
        if (requireCat && (!catId || Number.isNaN(catId))) {
            return { ok: false, errors: [{ kw: "—", msg: "Chọn category WordPress." }], readyIds: [] };
        }
        const errors = [];
        const readyIds = [];
        projectIds.forEach((pid) => {
            const r = _readinessByProject[pid];
            const kw = (r && r.keyword) || pid;
            let errs = (r && r.errors) ? r.errors.slice() : ["Chưa kiểm tra readiness."];
            if (requireCat && (!catId || Number.isNaN(catId))) errs.push("Thiếu category WordPress.");
            if (requireImage() && errs.some((e) => /ảnh|image/i.test(e))) {
                /* keep */
            } else if (requireImage() && r && r.image_status !== "ok") {
                errs.push("Thiếu ảnh featured.");
            }
            errs = [...new Set(errs)];
            if (errs.length) errors.push({ kw, msg: errs.join(" ") });
            else readyIds.push(pid);
        });
        return { ok: errors.length === 0, errors, readyIds };
    }

    function renderPreview(projectIds) {
        const ul = byId("bulkV2PubPreview");
        if (!ul) return;
        const mode = document.querySelector('input[name="bulkV2PubMode"]:checked');
        const isSched = mode && mode.value === "schedule";
        const startEl = byId("bulkV2PubStartAt");
        const times = isSched
            ? buildScheduleTimes(projectIds.length, startEl && startEl.value, getIntervalMinutes())
            : projectIds.map(() => "Đăng ngay");
        ul.innerHTML = projectIds
            .map((pid, i) => {
                const r = _readinessByProject[pid] || {};
                const kw = r.keyword || pid;
                const t = times[i] || "—";
                const disp = t === "Đăng ngay" ? t : String(t).replace("T", " ");
                return `<li><span class="bulk-v2-pub-kw">${esc(kw)}</span><span class="bulk-v2-pub-time">${esc(disp)}</span></li>`;
            })
            .join("");
    }

    function showPublishModal(show) {
        const m = byId("bulkV2PublishCenterModal");
        const b = byId("bulkV2PublishCenterBackdrop");
        if (m) m.hidden = !show;
        if (b) b.hidden = !show;
    }

    async function openPublishModal(projectIds, title) {
        const filtered = filterPublishableIds(projectIds);
        if (filtered.blocked.length) {
            const errUl = byId("bulkV2PublishRowErrors");
            if (errUl) {
                errUl.hidden = false;
                errUl.innerHTML = filtered.blocked
                    .map((x) => `<li><strong>${esc(x.kw)}</strong>: ${esc(x.msg)}</li>`)
                    .join("");
            }
            toast(
                filtered.ok.length
                    ? `Đã loại ${filtered.blocked.length} bài lỗi/rỗng khỏi danh sách đăng.`
                    : "Không thể đăng — bài lỗi LLM/API hoặc content rỗng."
            );
        }
        if (!filtered.ok.length) return;
        _modalProjectIds = filtered.ok.slice();
        const titleEl = byId("bulkV2PublishCenterTitle");
        if (titleEl) titleEl.textContent = title || "Xác nhận đăng bài";
        await loadReadiness(_modalProjectIds);
        await loadWpSites();
        const errEl = byId("bulkV2PubModalErrors");
        if (errEl) {
            errEl.hidden = true;
            errEl.innerHTML = "";
        }
        renderPreview(_modalProjectIds);
        showPublishModal(true);
    }

    function closePublishModal() {
        showPublishModal(false);
        _modalProjectIds = [];
    }

    async function confirmPublishModal() {
        const btn = byId("btnBulkV2PubConfirm");
        if (btn) btn.disabled = true;
        const errEl = byId("bulkV2PubModalErrors");
        try {
            const siteEl = byId("bulkV2PubSite");
            const opt = siteEl && siteEl.selectedOptions && siteEl.selectedOptions[0];
            const wp_site_id = siteEl ? siteEl.value : "";
            const wp_url = opt ? opt.getAttribute("data-url") || "" : "";
            const catEl = byId("bulkV2PubCategory");
            const catId = catEl && catEl.value ? parseInt(catEl.value, 10) : null;
            const requireCat = !!(catEl && catEl.value);
            await loadReadiness(_modalProjectIds, { require_category: requireCat });
            const v = validateModalProjects(_modalProjectIds, requireCat);
            if (!v.ok || !v.readyIds.length) {
                if (errEl) {
                    errEl.hidden = false;
                    errEl.innerHTML = (v.errors || [])
                        .map((x) => `<li><strong>${esc(x.kw)}</strong>: ${esc(x.msg)}</li>`)
                        .join("");
                }
                toast("Một số bài chưa đủ điều kiện đăng — xem chi tiết trong modal.");
                return;
            }
            const mode = document.querySelector('input[name="bulkV2PubMode"]:checked');
            const isSched = mode && mode.value === "schedule";
            const c = core();
            const bulkJobId = c && c.getBulkJobId ? c.getBulkJobId() : "";
            if (isSched) {
                const startEl = byId("bulkV2PubStartAt");
                if (!startEl || !startEl.value) {
                    toast("Chọn thời gian bắt đầu.");
                    return;
                }
                const times = buildScheduleTimes(v.readyIds.length, startEl.value, getIntervalMinutes());
                await apiPost("/content-ai/bulk-publish/schedule-batch", {
                    wp_site_id,
                    wp_url,
                    bulk_job_id: bulkJobId || null,
                    items: v.readyIds.map((project_id, i) => ({
                        project_id,
                        scheduled_at: times[i],
                        wp_category_id: catId && !Number.isNaN(catId) ? catId : null,
                    })),
                });
                toast(`Đã đặt lịch ${v.readyIds.length} bài.`);
                closePublishModal();
            } else {
                const result = await apiPost("/content-ai/bulk-publish/publish-now-batch", {
                    wp_site_id,
                    wp_url,
                    bulk_job_id: bulkJobId || null,
                    project_ids: v.readyIds,
                });
                const apiErrs = (result && result.errors) || [];
                if (apiErrs.length) {
                    if (errEl) {
                        errEl.hidden = false;
                        errEl.innerHTML = apiErrs
                            .map((e) => {
                                const r = _readinessByProject[e.project_id] || {};
                                const kw = r.keyword || e.project_id || "—";
                                return `<li><strong>${esc(kw)}</strong>: ${esc(e.error || "Lỗi đăng")}</li>`;
                            })
                            .join("");
                    }
                    toast(`Đã đăng ${(result && result.count) || 0} bài, ${apiErrs.length} lỗi.`);
                } else {
                    toast(`Đã gửi đăng ${v.readyIds.length} bài.`);
                }
            }
            if (!errEl || errEl.hidden) closePublishModal();
            const u = ui();
            if (u && u.loadServerSchedules) await u.loadServerSchedules();
            if (u && u.refresh) u.refresh();
            await refreshPublishCenter();
        } catch (e) {
            toast(String(e.message || e));
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function publishSelectedNow() {
        const ids = getSelectedProjectIds();
        if (!ids.length) {
            toast("Chọn ít nhất một bài đã viết (không lỗi LLM/API, không rỗng).");
            return;
        }
        const filtered = filterPublishableIds(ids);
        if (!filtered.ok.length) {
            const errUl = byId("bulkV2PublishRowErrors");
            if (errUl) {
                errUl.hidden = false;
                errUl.innerHTML = filtered.blocked
                    .map((x) => `<li><strong>${esc(x.kw)}</strong>: ${esc(x.msg)}</li>`)
                    .join("");
            }
            toast("Không thể đăng — bài lỗi LLM/API hoặc content rỗng.");
            return;
        }
        await loadReadiness(filtered.ok);
        const v = validateModalProjects(filtered.ok, false);
        if (v.errors.length) {
            const errUl = byId("bulkV2PublishRowErrors");
            if (errUl) {
                errUl.hidden = false;
                errUl.innerHTML = v.errors.map((x) => `<li><strong>${esc(x.kw)}</strong>: ${esc(x.msg)}</li>`).join("");
            }
            toast("Không thể đăng — xem lỗi từng dòng bên dưới.");
            return;
        }
        if (!window.confirm(`Đăng ngay ${v.readyIds.length} bài đã chọn?`)) return;
        try {
            const data = await apiGet("/api/settings/publishing-sites?ts=" + Date.now());
            const sites = ((data && (data.items || data.sites)) || []).filter(
                (s) => String(s.platform || "").toLowerCase() === "wordpress"
            );
            if (!sites.length) throw new Error("Chưa có site WordPress.");
            const tw = byId("bulkTargetWebsite") && byId("bulkTargetWebsite").value.trim();
            let hit = sites[0];
            if (tw) {
                const n = tw.replace(/\/+$/, "").toLowerCase();
                hit = sites.find((s) => String(s.url || "").replace(/\/+$/, "").toLowerCase() === n) || hit;
            }
            const c = core();
            const bulkJobId = c && c.getBulkJobId ? c.getBulkJobId() : "";
            const result = await apiPost("/content-ai/bulk-publish/publish-now-batch", {
                wp_site_id: hit.id,
                wp_url: hit.url,
                bulk_job_id: bulkJobId || null,
                project_ids: v.readyIds,
            });
            const errN = ((result && result.errors) || []).length;
            const n = (result && result.count) || v.readyIds.length;
            toast(errN ? `Đã đăng ${n} bài, ${errN} lỗi.` : `Đã gửi đăng ${n} bài.`);
            const u = ui();
            if (u && u.loadServerSchedules) await u.loadServerSchedules();
            if (u && u.refresh) u.refresh();
            await refreshPublishCenter();
        } catch (e) {
            toast(String(e.message || e));
        }
    }

    async function scheduleSelected() {
        const ids = getSelectedProjectIds();
        if (!ids.length) {
            toast("Chọn bài đã viết (không lỗi LLM/API, không rỗng) để đặt lịch.");
            return;
        }
        await openPublishModal(ids, "Đặt lịch bài đã chọn");
        const schedRadio = document.querySelector('input[name="bulkV2PubMode"][value="schedule"]');
        if (schedRadio) schedRadio.checked = true;
        const opts = byId("bulkV2PubScheduleOpts");
        if (opts) opts.hidden = false;
    }

    async function cancelSelectedSchedules() {
        const ids = getSelectedProjectIds();
        if (!ids.length) {
            toast("Chọn bài có lịch để hủy.");
            return;
        }
        const schedMap = getScheduleMap();
        const scheduleIds = [];
        ids.forEach((pid) => {
            const s = schedMap[pid];
            if (s && s.id && String(s.status || "").toLowerCase() === "scheduled") scheduleIds.push(s.id);
        });
        if (!scheduleIds.length) {
            toast("Không có lịch scheduled trong các bài đã chọn.");
            return;
        }
        if (!window.confirm(`Hủy ${scheduleIds.length} lịch đăng?`)) return;
        try {
            await apiPost("/content-ai/bulk-publish/cancel-schedule", { schedule_ids: scheduleIds });
            toast("Đã hủy lịch.");
            const u = ui();
            if (u && u.loadServerSchedules) await u.loadServerSchedules();
            if (u && u.refresh) u.refresh();
            await refreshPublishCenter();
        } catch (e) {
            toast(String(e.message || e));
        }
    }

    function wireModal() {
        const closeBtn = byId("bulkV2PublishCenterClose");
        const cancelBtn = byId("btnBulkV2PubCancel");
        const back = byId("bulkV2PublishCenterBackdrop");
        const confirmBtn = byId("btnBulkV2PubConfirm");
        const loadCat = byId("btnBulkV2PubLoadCategories");
        const intervalSel = byId("bulkV2PubInterval");
        const modeRadios = document.querySelectorAll('input[name="bulkV2PubMode"]');

        if (closeBtn) closeBtn.addEventListener("click", closePublishModal);
        if (cancelBtn) cancelBtn.addEventListener("click", closePublishModal);
        if (back) back.addEventListener("click", (e) => { if (e.target === back) closePublishModal(); });
        if (confirmBtn) confirmBtn.addEventListener("click", () => void confirmPublishModal());
        if (loadCat) loadCat.addEventListener("click", () => void loadCategoriesForModal());

        if (intervalSel) {
            intervalSel.addEventListener("change", () => {
                const custom = byId("bulkV2PubIntervalCustom");
                if (custom) custom.hidden = intervalSel.value !== "custom";
                renderPreview(_modalProjectIds);
            });
        }
        const customInt = byId("bulkV2PubIntervalCustom");
        if (customInt) customInt.addEventListener("input", () => renderPreview(_modalProjectIds));
        const startAt = byId("bulkV2PubStartAt");
        if (startAt) startAt.addEventListener("change", () => renderPreview(_modalProjectIds));

        modeRadios.forEach((r) => {
            r.addEventListener("change", () => {
                const opts = byId("bulkV2PubScheduleOpts");
                const isSched = r.value === "schedule" && r.checked;
                if (opts) opts.hidden = !isSched;
                renderPreview(_modalProjectIds);
            });
        });
    }

    function init() {
        wireModal();
        const btnSel = byId("btnPublishCenterSelected");
        const btnSched = byId("btnPublishCenterScheduleSelected");
        const btnAll = byId("btnPublishCenterPublishAll");
        const btnCancel = byId("btnPublishCenterCancelSchedule");
        const reqImg = byId("bulkV2RequireImage");

        if (btnSel) btnSel.addEventListener("click", () => void publishSelectedNow());
        if (btnSched) btnSched.addEventListener("click", () => void scheduleSelected());
        if (btnAll) {
            btnAll.addEventListener("click", () => {
                const u = ui();
                const ids =
                    u && u.getAllWrittenProjectIds
                        ? u.getAllWrittenProjectIds({ allowBroken: true })
                        : getAllWrittenProjectIds();
                if (!ids.length) {
                    toast("Chưa có bài viết xong.");
                    return;
                }
                void openPublishModal(ids, "Đăng tất cả bài đã viết");
            });
        }
        if (btnCancel) btnCancel.addEventListener("click", () => void cancelSelectedSchedules());
        if (reqImg) reqImg.addEventListener("change", () => void refreshPublishCenter());
    }

    window.ContentAiBulkPublishCenter = {
        refresh: refreshPublishCenter,
        openModal: openPublishModal,
        publishSelected: publishSelectedNow,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
