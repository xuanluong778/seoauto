/**
 * Google Map SEO — Ảnh & Media
 */
(function () {
    "use strict";

    var API = "/api/google-map-seo";
    var MAX_BYTES = 10 * 1024 * 1024;
    var MIN_EDGE = 720;

    var MEDIA_TYPES = [
        { id: "logo", label: "Logo", hint: "Vuông, nền trong suốt/trắng, ≥250px" },
        { id: "cover", label: "Ảnh bìa", hint: "Tỷ lệ 16:9, 1080×608 khuyến nghị" },
        { id: "storefront", label: "Ảnh mặt tiền", hint: "Cửa hàng/văn phòng nhìn từ đường" },
        { id: "interior", label: "Ảnh nội thất", hint: "Không gian làm việc, quầy lễ tân" },
        { id: "product_service", label: "Ảnh sản phẩm/dịch vụ", hint: "Sản phẩm hoặc quy trình dịch vụ" },
        { id: "team", label: "Ảnh đội ngũ", hint: "Nhân sự, tư vấn viên" },
        { id: "customer_case", label: "Ảnh khách hàng/case", hint: "Kết quả thực tế (có sự đồng ý)" },
    ];

    var WEEKDAYS = [
        { id: 0, label: "Thứ 2" },
        { id: 1, label: "Thứ 3" },
        { id: 2, label: "Thứ 4" },
        { id: 3, label: "Thứ 5" },
        { id: 4, label: "Thứ 6" },
        { id: 5, label: "Thứ 7" },
        { id: 6, label: "Chủ nhật" },
    ];

    var mediaState = {
        items: [],
        byType: {},
        typesPresent: {},
        summary: null,
        auditIssues: [],
        auditSummary: null,
        reminder: null,
        canPublish: false,
        loading: false,
        uploading: null,
        aiLoading: null,
        activeId: null,
        keywords: "",
        locality: "",
    };

    function lsKey(locId) {
        return "gms_media_" + locId;
    }

    function readLs(locId) {
        try {
            var raw = localStorage.getItem(lsKey(locId));
            return raw ? JSON.parse(raw) : [];
        } catch (_e) {
            return [];
        }
    }

    function writeLs(locId, items) {
        try {
            localStorage.setItem(lsKey(locId), JSON.stringify(items));
        } catch (_e) {}
    }

    function formatSize(bytes) {
        var n = Number(bytes) || 0;
        if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
        return Math.round(n / 1024) + " KB";
    }

    function severityClass(sev) {
        if (sev === "critical") return "gms-media-issue--critical";
        if (sev === "warning") return "gms-media-issue--warn";
        return "gms-media-issue--opp";
    }

    function clientValidate(file) {
        var issues = [];
        if (!file) return { ok: false, issues: ["Chưa chọn file."] };
        var name = (file.name || "").toLowerCase();
        if (!/\.(jpe?g|png|webp)$/.test(name)) {
            issues.push("Chỉ hỗ trợ JPG, PNG, WebP.");
        }
        if (file.size > MAX_BYTES) {
            issues.push("Dung lượng vượt " + (MAX_BYTES / 1024 / 1024) + "MB.");
        }
        return { ok: issues.length === 0, issues: issues };
    }

    function prefillKeywords(ctx) {
        var loc = ctx.location || {};
        return {
            keywords: loc.category || "",
            locality: loc.address || loc.locality || "",
        };
    }

    function uploadHeaders(ctx) {
        var h = {};
        var tok = ctx.authToken ? ctx.authToken() : "";
        if (tok) h.Authorization = "Bearer " + tok;
        return h;
    }

    async function uploadFile(ctx, locId, mediaType, file) {
        var pre = clientValidate(file);
        if (!pre.ok) {
            ctx.showToast(pre.issues[0]);
            return;
        }
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để upload ảnh lên server.");
            return;
        }
        mediaState.uploading = mediaType;
        render(ctx.host, ctx);
        var fd = new FormData();
        fd.append("location_key", locId);
        fd.append("media_type", mediaType);
        fd.append("keywords", mediaState.keywords || "");
        fd.append("locality", mediaState.locality || "");
        fd.append("file", file);
        try {
            var r = await fetch(API + "/media/upload", {
                method: "POST",
                headers: uploadHeaders(ctx),
                body: fd,
                credentials: "same-origin",
            });
            var data = {};
            try { data = await r.json(); } catch (_e) {}
            if (!r.ok) {
                throw new Error((data.detail && (typeof data.detail === "string" ? data.detail : data.detail.message)) || "Upload thất bại.");
            }
            var item = data.data || {};
            if (item.validation_warnings && item.validation_warnings.length) {
                ctx.showToast(item.validation_warnings[0]);
            } else {
                ctx.showToast("Đã upload ảnh.");
            }
            await refreshAll(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Upload thất bại.");
        } finally {
            mediaState.uploading = null;
            render(ctx.host, ctx);
        }
    }

    function renderAudit(ctx) {
        if (!mediaState.auditIssues.length) {
            return '<p class="gms-hint gms-media-audit-ok">Đã có đủ các loại ảnh quan trọng trong thư viện nội bộ.</p>';
        }
        return (
            '<ul class="gms-media-audit">' +
            mediaState.auditIssues.map(function (i) {
                return (
                    '<li class="gms-media-issue ' + severityClass(i.severity) + '">' +
                    "<strong>" + ctx.esc(i.title) + "</strong>" +
                    '<span class="gms-muted">' + ctx.esc(i.fix) + "</span></li>"
                );
            }).join("") +
            "</ul>"
        );
    }

    function renderTypeCard(ctx, meta, locId) {
        var items = mediaState.byType[meta.id] || [];
        var has = items.length > 0;
        var uploading = mediaState.uploading === meta.id;
        var thumbs = items.slice(0, 4).map(function (it) {
            var active = String(mediaState.activeId) === String(it.id);
            return (
                '<button type="button" class="gms-media-thumb' + (active ? " active" : "") + '" data-gms-media-view="' + it.id + '">' +
                '<img src="' + ctx.esc(it.public_url) + '" alt="" loading="lazy" />' +
                '<span class="gms-media-thumb__meta">' + (it.width_px || "?") + "×" + (it.height_px || "?") + "</span></button>"
            );
        }).join("");
        return (
            '<div class="gms-media-type' + (has ? " gms-media-type--ok" : " gms-media-type--miss") + '" data-type="' + meta.id + '">' +
            '<div class="gms-media-type__head">' +
            "<div><strong>" + meta.label + "</strong>" +
            (has ? '<span class="gms-badge gms-badge--ok">' + items.length + " ảnh</span>" : '<span class="gms-badge gms-badge--warn">Thiếu</span>') +
            "</div>" +
            '<label class="gms-btn gms-btn--secondary gms-btn--xs' + (uploading ? " disabled" : "") + '">' +
            (uploading ? "Đang tải…" : "Upload") +
            '<input type="file" accept="image/jpeg,image/png,image/webp" class="gms-media-file" data-gms-media-upload="' + meta.id + '" hidden /></label></div>' +
            '<p class="gms-hint">' + meta.hint + "</p>" +
            (thumbs ? '<div class="gms-media-thumbs">' + thumbs + "</div>" : '<div class="gms-media-empty-slot">Chưa có ảnh</div>') +
            "</div>"
        );
    }

    function renderDetail(ctx) {
        var item = mediaState.items.find(function (x) { return String(x.id) === String(mediaState.activeId); });
        if (!item) return "";
        var aiBusy = mediaState.aiLoading === item.id;
        return (
            '<div class="gms-card gms-media-detail">' +
            '<div class="gms-media-detail__grid">' +
            '<div class="gms-media-preview"><img src="' + ctx.esc(item.public_url) + '" alt="" /></div>' +
            '<div class="gms-media-detail__meta">' +
            '<div class="gms-media-detail__head">' +
            "<div><strong>" + ctx.esc(item.media_type_label) + "</strong> " +
            (item.status === "published"
                ? '<span class="gms-badge gms-badge--ok">Đã đăng GBP</span>'
                : '<span class="gms-badge gms-badge--warn">Lưu nội bộ</span>') +
            "</div>" +
            '<button type="button" class="gms-btn gms-btn--ghost gms-btn--xs" id="gmsMediaCloseDetail">Đóng</button></div>' +
            '<p class="gms-muted">' + (item.width_px || "?") + "×" + (item.height_px || "?") +
            " · " + formatSize(item.file_size_bytes) + "</p>" +
            '<label class="gms-field-label">Tên file SEO gợi ý</label>' +
            '<input type="text" class="gms-input" id="gmsMediaFilename" value="' + ctx.esc(item.suggested_filename || "") + '" />' +
            '<label class="gms-field-label">Caption / mô tả</label>' +
            '<textarea class="gms-textarea" id="gmsMediaCaption" rows="4">' + ctx.esc(item.caption || "") + "</textarea>" +
            '<div class="gms-profile__actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" data-gms-media-ai="' + item.id + '"' +
            (aiBusy ? " disabled" : "") + ">Gợi ý caption AI</button>" +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-media-save="' + item.id + '">Lưu</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-media-del="' + item.id + '">Xóa</button>' +
            '<button type="button" class="gms-btn gms-btn--primary" data-gms-media-pub="' + item.id + '"' +
            (!mediaState.canPublish ? " disabled" : "") + ">Đăng GBP</button></div>" +
            (!mediaState.canPublish
                ? '<p class="gms-hint">Chưa kết nối GBP — ảnh lưu nội bộ, tải về và đăng thủ công trên Google.</p>'
                : "") +
            (item.last_error ? '<p class="gms-post-err">' + ctx.esc(item.last_error) + "</p>" : "") +
            "</div></div></div>"
        );
    }

    function renderHtml(ctx) {
        var sum = mediaState.summary || {};
        var aud = mediaState.auditSummary || {};
        var rem = mediaState.reminder || {};
        var pre = prefillKeywords(ctx);
        return (
            '<div class="gms-media-module">' +
            '<div class="gms-card">' +
            '<h2 class="gms-card-title">Ảnh &amp; Media Google Map</h2>' +
            '<p class="gms-hint">Upload · kiểm tra kích thước · gợi ý tên file SEO local · caption AI · nhắc thêm ảnh hàng tuần</p>' +
            '<div class="gms-media-stats">' +
            "<span>Tổng <strong>" + (sum.total || 0) + "</strong> ảnh</span>" +
            "<span>Loại đã có <strong>" + (sum.types_covered || 0) + "/" + (sum.types_total || 7) + "</strong></span>" +
            (aud.critical ? '<span class="gms-media-stat-alert">Thiếu quan trọng: <strong>' + aud.critical + "</strong></span>" : "") +
            "</div>" +
            '<div class="gms-media-keywords">' +
            '<label class="gms-field-label" for="gmsMediaKw">Từ khóa (tên file SEO)</label>' +
            '<input type="text" class="gms-input" id="gmsMediaKw" maxlength="120" value="' + ctx.esc(mediaState.keywords || pre.keywords) + '" />' +
            '<label class="gms-field-label" for="gmsMediaLoc">Khu vực</label>' +
            '<input type="text" class="gms-input" id="gmsMediaLoc" maxlength="200" value="' + ctx.esc(mediaState.locality || pre.locality) + '" /></div></div>' +
            '<div class="gms-card"><h3 class="gms-card-title">Lỗi tối ưu — thiếu loại ảnh</h3>' +
            renderAudit(ctx) + "</div>" +
            (mediaState.loading
                ? '<div class="gms-card"><p class="gms-hint">Đang tải thư viện ảnh…</p></div>'
                : '<div class="gms-media-types">' + MEDIA_TYPES.map(function (m) {
                    return renderTypeCard(ctx, m, ctx.location ? ctx.location.id : "default");
                }).join("") + "</div>") +
            renderDetail(ctx) +
            '<div class="gms-grid-2">' +
            '<div class="gms-card"><h3 class="gms-card-title">Tiêu chí ảnh tốt</h3>' +
            '<ul class="gms-steps"><li>Cạnh ngắn tối thiểu ' + MIN_EDGE + "px</li>" +
            "<li>Dung lượng ≤ " + (MAX_BYTES / 1024 / 1024) + "MB · JPG/PNG/WebP</li>" +
            "<li>Ánh sáng tự nhiên, ảnh thật, không watermark che khuất</li></ul></div>" +
            '<div class="gms-card gms-media-reminder"><h3 class="gms-card-title">Nhắc thêm ảnh hàng tuần</h3>' +
            '<label class="gms-media-rem-check"><input type="checkbox" id="gmsMediaRemEnable" ' +
            (rem.enabled ? "checked" : "") + " /> Bật nhắc nhở</label>" +
            '<label class="gms-field-label" for="gmsMediaRemDay">Ngày nhắc</label>' +
            '<select class="gms-select" id="gmsMediaRemDay">' +
            WEEKDAYS.map(function (d) {
                return '<option value="' + d.id + '"' + (Number(rem.remind_weekday) === d.id ? " selected" : "") + ">" + d.label + "</option>";
            }).join("") +
            "</select>" +
            '<button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" id="gmsMediaRemSave">Lưu lịch nhắc</button>' +
            (rem.next_remind_at ? '<p class="gms-hint">Nhắc tiếp theo: ' + ctx.esc(rem.next_remind_at) + "</p>" : "") +
            "</div></div></div>"
        );
    }

    function syncCheckMedia(ctx) {
        if (!ctx.location || !ctx.location.gbp) return;
        ctx.location.gbp.media = ctx.location.gbp.media || {};
        ctx.location.gbp.media.typesPresent = mediaState.typesPresent;
        ctx.location.gbp.media.photoCount = mediaState.summary ? mediaState.summary.total : 0;
        ctx.location.gbp.media.hasLogo = !!mediaState.typesPresent.logo;
        ctx.location.gbp.media.hasCover = !!mediaState.typesPresent.cover;
    }

    async function loadMedia(ctx, locId) {
        if (!ctx.authToken()) {
            var local = readLs(locId);
            mediaState.items = local;
            mediaState.byType = {};
            MEDIA_TYPES.forEach(function (t) { mediaState.byType[t.id] = []; });
            local.forEach(function (it) {
                if (mediaState.byType[it.media_type]) mediaState.byType[it.media_type].push(it);
            });
            mediaState.typesPresent = {};
            MEDIA_TYPES.forEach(function (t) {
                mediaState.typesPresent[t.id] = (mediaState.byType[t.id] || []).length > 0;
            });
            mediaState.summary = {
                total: local.length,
                types_covered: Object.keys(mediaState.typesPresent).filter(function (k) { return mediaState.typesPresent[k]; }).length,
                types_total: MEDIA_TYPES.length,
            };
            return;
        }
        var res = await ctx.apiFetch("/media?location_key=" + encodeURIComponent(locId));
        var data = res.data || {};
        mediaState.items = data.items || [];
        mediaState.byType = data.by_type || {};
        mediaState.typesPresent = data.types_present || {};
        mediaState.summary = data.summary || null;
        mediaState.canPublish = !!data.can_publish;
    }

    async function loadAudit(ctx, locId) {
        if (!ctx.authToken()) {
            mediaState.auditIssues = [];
            MEDIA_TYPES.forEach(function (t) {
                if (!mediaState.typesPresent[t.id]) {
                    var sev = t.id === "logo" || t.id === "cover" ? "critical" : "warning";
                    mediaState.auditIssues.push({
                        severity: sev,
                        title: "Thiếu " + t.label.toLowerCase(),
                        fix: "Upload " + t.label.toLowerCase() + ".",
                    });
                }
            });
            mediaState.auditSummary = {
                critical: mediaState.auditIssues.filter(function (i) { return i.severity === "critical"; }).length,
                warning: mediaState.auditIssues.filter(function (i) { return i.severity === "warning"; }).length,
            };
            return;
        }
        var res = await ctx.apiFetch("/media/audit?location_key=" + encodeURIComponent(locId));
        var data = res.data || {};
        mediaState.auditIssues = data.optimization_issues || [];
        mediaState.auditSummary = data.summary || null;
    }

    async function loadReminder(ctx, locId) {
        if (!ctx.authToken()) {
            mediaState.reminder = { enabled: false, remind_weekday: 1 };
            return;
        }
        try {
            var res = await ctx.apiFetch("/media/reminder?location_key=" + encodeURIComponent(locId));
            mediaState.reminder = res.data || null;
        } catch (_e) {
            mediaState.reminder = { enabled: false, remind_weekday: 1 };
        }
    }

    async function refreshAll(ctx, locId) {
        mediaState.loading = true;
        render(ctx.host, ctx);
        try {
            await loadMedia(ctx, locId);
            await loadAudit(ctx, locId);
            syncCheckMedia(ctx);
        } finally {
            mediaState.loading = false;
            render(ctx.host, ctx);
        }
    }

    async function saveDetail(ctx, host, locId, id) {
        var cap = host.querySelector("#gmsMediaCaption");
        var fn = host.querySelector("#gmsMediaFilename");
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để lưu trên server.");
            return;
        }
        try {
            await ctx.apiFetch("/media/" + id, {
                method: "PATCH",
                json: true,
                body: {
                    caption: cap ? cap.value : "",
                    suggested_filename: fn ? fn.value : "",
                },
            });
            ctx.showToast("Đã lưu.");
            await refreshAll(ctx, locId);
            mediaState.activeId = id;
            render(ctx.host, ctx);
        } catch (e) {
            ctx.showToast((e && e.message) || "Lưu thất bại.");
        }
    }

    async function runAi(ctx, host, locId, id) {
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để dùng AI.");
            return;
        }
        mediaState.aiLoading = id;
        render(ctx.host, ctx);
        try {
            var res = await ctx.apiFetch("/media/" + id + "/ai-caption", {
                method: "POST",
                json: true,
                body: {
                    keywords: mediaState.keywords,
                    locality: mediaState.locality,
                },
            });
            var data = res.data || {};
            mediaState.activeId = id;
            if (data.warnings && data.warnings.length) ctx.showToast(data.warnings[0]);
            else ctx.showToast("Đã tạo caption AI.");
            await refreshAll(ctx, locId);
            mediaState.activeId = id;
            render(ctx.host, ctx);
        } catch (e) {
            ctx.showToast((e && e.message) || "AI thất bại.");
        } finally {
            mediaState.aiLoading = null;
            render(ctx.host, ctx);
        }
    }

    async function deleteItem(ctx, locId, id) {
        if (!ctx.authToken()) {
            var local = readLs(locId).filter(function (x) { return String(x.id) !== String(id); });
            writeLs(locId, local);
            mediaState.activeId = null;
            await refreshAll(ctx, locId);
            return;
        }
        try {
            await ctx.apiFetch("/media/" + id, { method: "DELETE" });
            mediaState.activeId = null;
            ctx.showToast("Đã xóa ảnh.");
            await refreshAll(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Xóa thất bại.");
        }
    }

    async function publishItem(ctx, locId, id) {
        try {
            await ctx.apiFetch("/media/" + id + "/publish", { method: "POST", json: true, body: {} });
            ctx.showToast("Đã xử lý đăng ảnh.");
            await refreshAll(ctx, locId);
            mediaState.activeId = id;
            render(ctx.host, ctx);
        } catch (e) {
            ctx.showToast((e && e.message) || "Chưa đăng được — ảnh vẫn lưu nội bộ.");
            await refreshAll(ctx, locId);
        }
    }

    async function saveReminder(ctx, host, locId) {
        var en = host.querySelector("#gmsMediaRemEnable");
        var day = host.querySelector("#gmsMediaRemDay");
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để lưu lịch nhắc.");
            return;
        }
        try {
            var res = await ctx.apiFetch("/media/reminder", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    enabled: !!(en && en.checked),
                    remind_weekday: day ? parseInt(day.value, 10) : 1,
                },
            });
            mediaState.reminder = res.data || mediaState.reminder;
            ctx.showToast("Đã lưu lịch nhắc.");
            render(ctx.host, ctx);
        } catch (e) {
            ctx.showToast((e && e.message) || "Lưu nhắc thất bại.");
        }
    }

    function bindEvents(host, ctx) {
        if (host._gmsMediaClick) host.removeEventListener("click", host._gmsMediaClick);
        if (host._gmsMediaChange) host.removeEventListener("change", host._gmsMediaChange);
        var locId = ctx.location ? ctx.location.id : "default";

        host._gmsMediaChange = function (e) {
            var inp = e.target;
            if (!inp || !inp.classList || !inp.classList.contains("gms-media-file")) return;
            var type = inp.getAttribute("data-gms-media-upload");
            var file = inp.files && inp.files[0];
            inp.value = "";
            if (type && file) uploadFile(ctx, locId, type, file);
            var kw = host.querySelector("#gmsMediaKw");
            var loc = host.querySelector("#gmsMediaLoc");
            if (kw) mediaState.keywords = String(kw.value || "").trim();
            if (loc) mediaState.locality = String(loc.value || "").trim();
        };
        host.addEventListener("change", host._gmsMediaChange);

        host._gmsMediaClick = function (e) {
            var view = e.target && e.target.closest ? e.target.closest("[data-gms-media-view]") : null;
            if (view) {
                mediaState.activeId = view.getAttribute("data-gms-media-view");
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsMediaCloseDetail") {
                mediaState.activeId = null;
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsMediaRemSave") saveReminder(ctx, host, locId);
            var ai = e.target && e.target.closest ? e.target.closest("[data-gms-media-ai]") : null;
            if (ai) runAi(ctx, host, locId, ai.getAttribute("data-gms-media-ai"));
            var sv = e.target && e.target.closest ? e.target.closest("[data-gms-media-save]") : null;
            if (sv) saveDetail(ctx, host, locId, sv.getAttribute("data-gms-media-save"));
            var del = e.target && e.target.closest ? e.target.closest("[data-gms-media-del]") : null;
            if (del) deleteItem(ctx, locId, del.getAttribute("data-gms-media-del"));
            var pub = e.target && e.target.closest ? e.target.closest("[data-gms-media-pub]") : null;
            if (pub) publishItem(ctx, locId, pub.getAttribute("data-gms-media-pub"));
        };
        host.addEventListener("click", host._gmsMediaClick);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
    }

    async function mount(host, ctx) {
        mediaState.activeId = null;
        mediaState.uploading = null;
        mediaState.aiLoading = null;
        ctx.host = host;
        var locId = ctx.location ? ctx.location.id : "default";
        var pre = prefillKeywords(ctx);
        mediaState.keywords = pre.keywords;
        mediaState.locality = pre.locality;
        bindEvents(host, ctx);
        await loadReminder(ctx, locId);
        await refreshAll(ctx, locId);
    }

    window.GmsMedia = {
        mount: mount,
        reset: function () { mediaState.activeId = null; },
        getAuditIssues: function () { return mediaState.auditIssues.slice(); },
        getTypesPresent: function () { return Object.assign({}, mediaState.typesPresent); },
    };
})();
