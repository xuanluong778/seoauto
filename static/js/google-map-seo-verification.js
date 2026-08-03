/**
 * Google Map SEO — Trợ lý xác minh Google Map
 */
(function () {
    "use strict";

    var API = "/api/google-map-seo";

    var STATUS_META = {
        verified: { label: "Đã xác minh", badge: "gms-badge--ok" },
        unverified: { label: "Chưa xác minh", badge: "gms-badge--warn" },
        needs_reverify: { label: "Cần xác minh lại", badge: "gms-badge--danger" },
        pending: { label: "Đang chờ Google duyệt", badge: "gms-badge--info" },
        rejected: { label: "Bị từ chối", badge: "gms-badge--err" },
    };

    var verState = {
        data: null,
        loading: false,
        saving: false,
        uploading: false,
        openMethod: null,
    };

    function lsKey(locId) {
        return "gms_verif_" + locId;
    }

    function readLs(locId) {
        try {
            var raw = localStorage.getItem(lsKey(locId));
            return raw ? JSON.parse(raw) : null;
        } catch (_e) {
            return null;
        }
    }

    function writeLs(locId, data) {
        try {
            localStorage.setItem(lsKey(locId), JSON.stringify(data));
        } catch (_e) {}
    }

    function statusBadge(status) {
        var m = STATUS_META[status] || STATUS_META.unverified;
        return '<span class="gms-badge ' + m.badge + '">' + m.label + "</span>";
    }

    function demoStatusFromLoc(loc) {
        if (!loc) return "unverified";
        if (loc.verificationStatus) return loc.verificationStatus;
        return loc.verified ? "verified" : "unverified";
    }

    function uploadHeaders(ctx) {
        var h = {};
        var tok = ctx.authToken ? ctx.authToken() : "";
        if (tok) h.Authorization = "Bearer " + tok;
        return h;
    }

    function renderChecklist(ctx) {
        var d = verState.data;
        if (!d || !d.checklist_template) return "";
        var cl = d.checklist || {};
        var prog = d.checklist_progress || { checked: 0, total: 5 };
        return (
            '<div class="gms-card gms-ver-checklist">' +
            '<h3 class="gms-card-title">Checklist chuẩn bị xác minh</h3>' +
            '<p class="gms-hint">Đánh dấu những gì bạn đã sẵn sàng — dùng khi quay video hoặc chờ thư PIN.</p>' +
            '<div class="gms-ver-progress"><div class="gms-ver-progress__bar" style="width:' +
            Math.round((prog.checked / Math.max(prog.total, 1)) * 100) + '%"></div></div>' +
            '<p class="gms-muted gms-ver-progress__label">' + prog.checked + "/" + prog.total + " mục đã chuẩn bị</p>" +
            '<ul class="gms-ver-checks">' +
            d.checklist_template.map(function (item) {
                var on = !!cl[item.id];
                return (
                    '<li class="gms-ver-check-item">' +
                    '<label><input type="checkbox" class="gms-ver-check" data-ver-check="' + item.id + '"' +
                    (on ? " checked" : "") + " /> " +
                    "<strong>" + ctx.esc(item.label) + "</strong>" +
                    '<span class="gms-muted">' + ctx.esc(item.hint) + "</span></label></li>"
                );
            }).join("") +
            "</ul></div>"
        );
    }

    function renderMethods(ctx) {
        var methods = (verState.data && verState.data.methods) || [];
        return (
            '<div class="gms-card"><h3 class="gms-card-title">Hướng dẫn phương thức xác minh</h3>' +
            '<p class="gms-hint">Google quyết định phương thức khả dụng cho từng hồ sơ — danh sách dưới đây là gợi ý chuẩn bị.</p>' +
            '<div class="gms-ver-methods">' +
            methods.map(function (m) {
                var open = verState.openMethod === m.id;
                return (
                    '<div class="gms-ver-method' + (m.available ? "" : " gms-ver-method--off") + '">' +
                    '<button type="button" class="gms-ver-method__head" data-ver-method="' + m.id + '">' +
                    "<div><strong>" + ctx.esc(m.label) + "</strong>" +
                    (m.available
                        ? '<span class="gms-badge gms-badge--ok gms-badge--xs">Có thể khả dụng</span>'
                        : '<span class="gms-badge gms-badge--warn gms-badge--xs">Có thể chưa khả dụng</span>') +
                    "</div><span class=\"gms-ver-method__toggle\">" + (open ? "−" : "+") + "</span></button>" +
                    '<p class="gms-muted gms-ver-method__hint">' + ctx.esc(m.available_hint) + "</p>" +
                    (open
                        ? '<ol class="gms-ver-steps">' + m.steps.map(function (s) {
                            return "<li>" + ctx.esc(s) + "</li>";
                        }).join("") + "</ol>"
                        : "") +
                    "</div>"
                );
            }).join("") +
            "</div></div>"
        );
    }

    function renderAssets(ctx) {
        var assets = (verState.data && verState.data.assets) || [];
        var photos = assets.filter(function (a) { return a.asset_type === "photo"; });
        var docs = assets.filter(function (a) { return a.asset_type === "document"; });
        function grid(items, type) {
            if (!items.length) return '<p class="gms-hint">Chưa có ' + (type === "photo" ? "ảnh" : "tài liệu") + ".</p>";
            return (
                '<div class="gms-ver-assets">' +
                items.map(function (a) {
                    var isImg = /\.(jpe?g|png|webp)$/i.test(a.file_name || "");
                    return (
                        '<div class="gms-ver-asset">' +
                        (isImg
                            ? '<a href="' + ctx.esc(a.public_url) + '" target="_blank" rel="noopener"><img src="' + ctx.esc(a.public_url) + '" alt="" /></a>'
                            : '<a class="gms-ver-doc" href="' + ctx.esc(a.public_url) + '" target="_blank" rel="noopener">📄 ' + ctx.esc(a.file_name) + "</a>") +
                        (a.label ? '<span class="gms-muted">' + ctx.esc(a.label) + "</span>" : "") +
                        '<button type="button" class="gms-btn gms-btn--ghost gms-btn--xs" data-ver-del-asset="' + a.id + '">Xóa</button></div>'
                    );
                }).join("") +
                "</div>"
            );
        }
        return (
            '<div class="gms-card gms-ver-assets-card">' +
            '<h3 class="gms-card-title">Ảnh &amp; tài liệu phục vụ xác minh</h3>' +
            '<p class="gms-hint">Lưu nội bộ trên SEOAuto — dùng khi quay video hoặc đối chiếu với Google. Không tự động gửi lên Google.</p>' +
            '<div class="gms-ver-upload-row">' +
            '<label class="gms-btn gms-btn--secondary gms-btn--xs">' +
            (verState.uploading === "photo" ? "Đang tải…" : "Thêm ảnh") +
            '<input type="file" accept="image/jpeg,image/png,image/webp" class="gms-ver-file" data-ver-upload="photo" hidden /></label>' +
            '<label class="gms-btn gms-btn--secondary gms-btn--xs">' +
            (verState.uploading === "document" ? "Đang tải…" : "Thêm tài liệu (PDF/ảnh)") +
            '<input type="file" accept=".pdf,image/jpeg,image/png,image/webp" class="gms-ver-file" data-ver-upload="document" hidden /></label>' +
            '<input type="text" class="gms-input gms-ver-asset-label" id="gmsVerAssetLabel" placeholder="Nhãn (tùy chọn)" maxlength="120" /></div>' +
            "<h4 class=\"gms-ver-assets-sub\">Ảnh</h4>" + grid(photos, "photo") +
            "<h4 class=\"gms-ver-assets-sub\">Tài liệu</h4>" + grid(docs, "document") +
            "</div>"
        );
    }

    function renderHtml(ctx) {
        var d = verState.data;
        if (!d) {
            return '<div class="gms-card"><p class="gms-hint">Đang tải trợ lý xác minh…</p></div>';
        }
        return (
            '<div class="gms-verification">' +
            '<div class="gms-card gms-ver-status-card">' +
            '<h2 class="gms-card-title">Trợ lý xác minh Google Map</h2>' +
            '<div class="gms-ver-status-row">' + statusBadge(d.status) +
            '<span class="gms-muted">Nguồn: ' +
            (d.status_source === "google_business_profile" ? "đồng bộ GBP" : "theo dõi nội bộ") +
            "</span></div>" +
            '<p class="gms-ver-disclaimer">⚠ ' + ctx.esc(d.disclaimer) + "</p>" +
            (d.status === "rejected" || d.status === "needs_reverify"
                ? '<p class="gms-ver-alert">Kiểm tra email/thông báo từ Google, cập nhật hồ sơ và thử lại phương thức phù hợp.</p>'
                : "") +
            (d.status === "pending"
                ? '<p class="gms-ver-pending">Google đang xử lý — thường vài ngày đến 2 tuần (thư PIN / video). Không gửi lại nhiều lần.</p>'
                : "") +
            '<div class="gms-ver-manual">' +
            '<label class="gms-field-label" for="gmsVerManualStatus">Theo dõi trạng thái (nội bộ)</label>' +
            '<select class="gms-select" id="gmsVerManualStatus">' +
            Object.keys(STATUS_META).map(function (k) {
                return '<option value="' + k + '"' + (d.status === k ? " selected" : "") + ">" + STATUS_META[k].label + "</option>";
            }).join("") +
            "</select></div></div>" +
            renderChecklist(ctx) +
            renderMethods(ctx) +
            '<div class="gms-card"><h3 class="gms-card-title">Ghi chú xác minh</h3>' +
            '<textarea class="gms-textarea" id="gmsVerNotes" rows="5" maxlength="8000" placeholder="Mã PIN đã nhận, ngày gửi video, liên hệ Google Support…">' +
            ctx.esc(d.notes || "") + "</textarea>" +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsVerSave"' +
            (verState.saving ? " disabled" : "") + ">Lưu checklist &amp; ghi chú</button></div>" +
            renderAssets(ctx) +
            "</div>"
        );
    }

    function readChecklist(host) {
        var out = {};
        host.querySelectorAll(".gms-ver-check").forEach(function (el) {
            var id = el.getAttribute("data-ver-check");
            if (id) out[id] = !!el.checked;
        });
        return out;
    }

    function buildLocalData(loc, saved) {
        var st = demoStatusFromLoc(loc);
        var checklist = (saved && saved.checklist) || {};
        var template = [
            { id: "business_sign", label: "Bảng hiệu doanh nghiệp", hint: "Tên thương hiệu khớp với hồ sơ Google" },
            { id: "storefront", label: "Mặt tiền / cửa hàng", hint: "Ảnh hoặc video thấy rõ địa chỉ/ cửa vào" },
            { id: "workspace", label: "Khu vực làm việc", hint: "Quầy lễ tân, phòng làm việc" },
            { id: "products_services", label: "Công cụ / sản phẩm / dịch vụ thật", hint: "Thiết bị hoặc quy trình thực tế" },
            { id: "business_documents", label: "Giấy tờ doanh nghiệp (nếu có)", hint: "GPKD, hóa đơn địa chỉ" },
        ];
        var checked = template.filter(function (t) { return checklist[t.id]; }).length;
        return {
            status: (saved && saved.manual_status) || st,
            status_label: (STATUS_META[(saved && saved.manual_status) || st] || STATUS_META.unverified).label,
            status_source: "demo",
            disclaimer: "Google là bên duyệt cuối cùng. SEOAuto chỉ hỗ trợ chuẩn bị — không cam kết xác minh 100% tự động.",
            checklist_template: template,
            checklist: checklist,
            checklist_progress: { checked: checked, total: template.length },
            notes: (saved && saved.notes) || "",
            methods: [
                { id: "postcard", label: "Thư bưu điện", available: true, available_hint: "Thường khả dụng", steps: ["Chọn nhận PIN qua thư.", "Chờ 5–14 ngày.", "Nhập mã trong GBP."] },
                { id: "phone", label: "Điện thoại / SMS", available: false, available_hint: "Cần SĐT trên hồ sơ", steps: ["Gọi/SMS mã PIN.", "Nhập mã ngay."] },
                { id: "email", label: "Email domain", available: !!(loc && loc.gbp && loc.gbp.website && loc.gbp.website.url), available_hint: "Cần website", steps: ["Mở email @domain.", "Xác nhận link Google."] },
                { id: "video", label: "Video xác minh", available: true, available_hint: "Google có thể yêu cầu", steps: ["Quay tại địa điểm.", "Hiện bảng hiệu/mặt tiền.", "Tải lên GBP."] },
            ],
            assets: (saved && saved.assets) || [],
        };
    }

    async function loadData(ctx, locId) {
        verState.loading = true;
        render(ctx.host, ctx);
        try {
            if (ctx.authToken()) {
                var q = "/verification?location_key=" + encodeURIComponent(locId);
                var demo = demoStatusFromLoc(ctx.location);
                if (demo && !String(locId).startsWith("gbp_")) {
                    q += "&demo_status=" + encodeURIComponent(demo);
                }
                var res = await ctx.apiFetch(q);
                verState.data = res.data || null;
            } else {
                verState.data = buildLocalData(ctx.location, readLs(locId));
            }
        } catch (e) {
            verState.data = buildLocalData(ctx.location, readLs(locId));
            ctx.showToast((e && e.message) || "Dùng dữ liệu nội bộ.");
        } finally {
            verState.loading = false;
            render(ctx.host, ctx);
        }
    }

    async function saveAll(ctx, host, locId) {
        var notesEl = host.querySelector("#gmsVerNotes");
        var statusEl = host.querySelector("#gmsVerManualStatus");
        var payload = {
            location_key: locId,
            checklist: readChecklist(host),
            notes: notesEl ? notesEl.value : "",
            manual_status: statusEl ? statusEl.value : "",
        };
        verState.saving = true;
        render(ctx.host, ctx);
        if (!ctx.authToken()) {
            var local = readLs(locId) || {};
            local.checklist = payload.checklist;
            local.notes = payload.notes;
            local.manual_status = payload.manual_status;
            local.assets = (verState.data && verState.data.assets) || [];
            writeLs(locId, local);
            verState.data = buildLocalData(ctx.location, local);
            ctx.showToast("Đã lưu trên trình duyệt.");
            verState.saving = false;
            render(ctx.host, ctx);
            return;
        }
        try {
            var res = await ctx.apiFetch("/verification", {
                method: "PUT",
                json: true,
                body: payload,
            });
            verState.data = res.data || verState.data;
            ctx.showToast("Đã lưu.");
        } catch (e) {
            ctx.showToast((e && e.message) || "Lưu thất bại.");
        } finally {
            verState.saving = false;
            render(ctx.host, ctx);
        }
    }

    async function uploadAsset(ctx, host, locId, type, file) {
        if (!file) return;
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để upload lên server.");
            return;
        }
        var labelEl = host.querySelector("#gmsVerAssetLabel");
        var label = labelEl ? String(labelEl.value || "").trim() : "";
        verState.uploading = type;
        render(ctx.host, ctx);
        var fd = new FormData();
        fd.append("location_key", locId);
        fd.append("asset_type", type);
        fd.append("label", label);
        fd.append("file", file);
        try {
            var r = await fetch(API + "/verification/assets/upload", {
                method: "POST",
                headers: uploadHeaders(ctx),
                body: fd,
                credentials: "same-origin",
            });
            var data = {};
            try { data = await r.json(); } catch (_e) {}
            if (!r.ok) throw new Error((typeof data.detail === "string" ? data.detail : null) || "Upload thất bại.");
            ctx.showToast("Đã thêm tài liệu.");
            if (labelEl) labelEl.value = "";
            await loadData(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Upload thất bại.");
        } finally {
            verState.uploading = false;
            render(ctx.host, ctx);
        }
    }

    async function deleteAsset(ctx, locId, id) {
        if (!ctx.authToken()) {
            var local = readLs(locId) || {};
            local.assets = (local.assets || []).filter(function (a) { return String(a.id) !== String(id); });
            writeLs(locId, local);
            verState.data = buildLocalData(ctx.location, local);
            render(ctx.host, ctx);
            return;
        }
        try {
            await ctx.apiFetch("/verification/assets/" + id, { method: "DELETE" });
            ctx.showToast("Đã xóa.");
            await loadData(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Xóa thất bại.");
        }
    }

    function bindEvents(host, ctx) {
        if (host._gmsVerClick) host.removeEventListener("click", host._gmsVerClick);
        if (host._gmsVerChange) host.removeEventListener("change", host._gmsVerChange);
        var locId = ctx.location ? ctx.location.id : "default";

        host._gmsVerChange = function (e) {
            var inp = e.target;
            if (inp && inp.classList && inp.classList.contains("gms-ver-file")) {
                var type = inp.getAttribute("data-ver-upload");
                var file = inp.files && inp.files[0];
                inp.value = "";
                if (type && file) uploadAsset(ctx, host, locId, type, file);
            }
        };
        host.addEventListener("change", host._gmsVerChange);

        host._gmsVerClick = function (e) {
            var method = e.target && e.target.closest ? e.target.closest("[data-ver-method]") : null;
            if (method) {
                var id = method.getAttribute("data-ver-method");
                verState.openMethod = verState.openMethod === id ? null : id;
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsVerSave") saveAll(ctx, host, locId);
            var del = e.target && e.target.closest ? e.target.closest("[data-ver-del-asset]") : null;
            if (del) deleteAsset(ctx, locId, del.getAttribute("data-ver-del-asset"));
        };
        host.addEventListener("click", host._gmsVerClick);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
    }

    async function mount(host, ctx) {
        verState.openMethod = null;
        ctx.host = host;
        var locId = ctx.location ? ctx.location.id : "default";
        bindEvents(host, ctx);
        await loadData(ctx, locId);
    }

    window.GmsVerification = { mount: mount, reset: function () { verState.openMethod = null; } };
})();
