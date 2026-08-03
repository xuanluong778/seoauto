/**
 * Google Map SEO — Bài đăng Google Map bằng AI
 */
(function () {
    "use strict";

    var POST_TYPES = [
        { id: "service_update", label: "Cập nhật dịch vụ" },
        { id: "promotion", label: "Khuyến mãi" },
        { id: "event", label: "Sự kiện" },
        { id: "news", label: "Tin tức doanh nghiệp" },
        { id: "case_study", label: "Case study ngắn" },
    ];

    var CTAS = [
        { id: "call", label: "Gọi ngay" },
        { id: "book", label: "Đặt lịch" },
        { id: "learn_more", label: "Xem thêm" },
        { id: "message", label: "Nhắn tin" },
    ];

    var SCHEDULE_MODES = [
        { id: "once", label: "Một lần" },
        { id: "weekly", label: "Hàng tuần" },
        { id: "monthly", label: "Hàng tháng" },
    ];

    var CAL_VIEWS = [
        { id: "week", label: "Tuần" },
        { id: "month", label: "Tháng" },
    ];

    var postState = {
        posts: [],
        summary: null,
        canPublish: false,
        loading: false,
        aiLoading: false,
        view: "list",
        calView: "month",
        calDays: [],
        activePostId: null,
        composerOpen: false,
        draft: null,
        warnings: [],
    };

    function lsKey(locId) {
        return "gms_posts_" + locId;
    }

    function readLs(locId) {
        try {
            var raw = localStorage.getItem(lsKey(locId));
            return raw ? JSON.parse(raw) : [];
        } catch (_e) {
            return [];
        }
    }

    function writeLs(locId, posts) {
        try {
            localStorage.setItem(lsKey(locId), JSON.stringify(posts));
        } catch (_e) {}
    }

    function formatDate(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", { dateStyle: "medium", timeStyle: "short" });
        } catch (_e) {
            return iso;
        }
    }

    function formatDateShort(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
        } catch (_e) {
            return iso;
        }
    }

    function statusBadge(status) {
        var map = {
            draft: "gms-badge--warn",
            scheduled: "gms-badge--info",
            published: "gms-badge--ok",
            error: "gms-badge--danger",
        };
        var labels = {
            draft: "Nháp",
            scheduled: "Đã lên lịch",
            published: "Đã đăng",
            error: "Lỗi",
        };
        var cls = map[status] || "gms-badge--warn";
        return '<span class="gms-badge ' + cls + '">' + (labels[status] || status) + "</span>";
    }

    function prefillFromLocation(loc) {
        if (!loc) return {};
        return {
            keywords: loc.category || "",
            locality: loc.address || loc.locality || "",
            goal: "",
            cta_type: "learn_more",
            business_name: loc.name || "",
        };
    }

    function calRange(view) {
        var now = new Date();
        var from = new Date(now);
        var to = new Date(now);
        if (view === "week") {
            var day = now.getDay();
            var diff = day === 0 ? -6 : 1 - day;
            from.setDate(now.getDate() + diff);
            from.setHours(0, 0, 0, 0);
            to.setTime(from.getTime());
            to.setDate(from.getDate() + 6);
        } else {
            from.setDate(1);
            from.setHours(0, 0, 0, 0);
            to.setMonth(from.getMonth() + 1, 0);
        }
        to.setHours(23, 59, 59, 999);
        return { from: from.toISOString(), to: to.toISOString() };
    }

    function renderComposer(ctx) {
        if (!postState.composerOpen) return "";
        var d = postState.draft || {};
        var inp = d.input || {};
        var suggestions = d.image_suggestions || [];
        return (
            '<div class="gms-card gms-post-composer" id="gmsPostComposer">' +
            '<div class="gms-post-composer__head">' +
            '<h2 class="gms-card-title" style="margin:0">Tạo bài đăng bằng AI</h2>' +
            '<button type="button" class="gms-btn gms-btn--ghost gms-btn--xs" id="gmsPostCloseComposer">Đóng</button></div>' +
            '<div class="gms-post-composer__grid">' +
            '<div class="gms-post-composer__in">' +
            '<label class="gms-field-label" for="gmsPostType">Loại bài đăng</label>' +
            '<select class="gms-select" id="gmsPostType">' +
            POST_TYPES.map(function (t) {
                return '<option value="' + t.id + '"' + (d.post_type === t.id ? " selected" : "") + ">" + t.label + "</option>";
            }).join("") +
            "</select>" +
            '<label class="gms-field-label" for="gmsPostKeywords">Từ khóa / dịch vụ</label>' +
            '<input type="text" class="gms-input" id="gmsPostKeywords" maxlength="300" value="' + ctx.esc(inp.keywords || "") + '" />' +
            '<label class="gms-field-label" for="gmsPostLocality">Khu vực</label>' +
            '<input type="text" class="gms-input" id="gmsPostLocality" maxlength="200" value="' + ctx.esc(inp.locality || "") + '" />' +
            '<label class="gms-field-label" for="gmsPostGoal">Mục tiêu bài đăng</label>' +
            '<textarea class="gms-textarea" id="gmsPostGoal" rows="3" maxlength="800" placeholder="VD: thu hút khách gọi điện, giới thiệu gói mới…">' +
            ctx.esc(inp.goal || "") + "</textarea>" +
            '<label class="gms-field-label" for="gmsPostCta">CTA</label>' +
            '<select class="gms-select" id="gmsPostCta">' +
            CTAS.map(function (c) {
                return '<option value="' + c.id + '"' + ((d.cta_type || inp.cta_type) === c.id ? " selected" : "") + ">" + c.label + "</option>";
            }).join("") +
            "</select>" +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsPostBtnAi" ' +
            (postState.aiLoading ? "disabled" : "") + ">Tạo bằng AI</button></div>" +
            '<div class="gms-post-composer__out">' +
            '<label class="gms-field-label" for="gmsPostTitle">Tiêu đề</label>' +
            '<input type="text" class="gms-input" id="gmsPostTitle" maxlength="58" value="' + ctx.esc(d.title || "") + '" />' +
            '<label class="gms-field-label" for="gmsPostContent">Nội dung ngắn</label>' +
            '<textarea class="gms-textarea" id="gmsPostContent" rows="8" maxlength="4000">' + ctx.esc(d.content || "") + "</textarea>" +
            '<label class="gms-field-label" for="gmsPostCtaLabel">Nhãn CTA</label>' +
            '<input type="text" class="gms-input" id="gmsPostCtaLabel" maxlength="120" value="' + ctx.esc(d.cta_label || "") + '" />' +
            (suggestions.length
                ? '<div class="gms-post-images"><span class="gms-field-label">Gợi ý hình ảnh</span><ul class="gms-steps">' +
                suggestions.map(function (s) { return "<li>" + ctx.esc(s) + "</li>"; }).join("") + "</ul></div>"
                : '<p class="gms-hint">Gợi ý hình ảnh sẽ hiện sau khi tạo bằng AI.</p>') +
            (postState.warnings.length
                ? '<ul class="gms-profile-warn">' + postState.warnings.map(function (w) {
                    return "<li>" + ctx.esc(w) + "</li>";
                }).join("") + "</ul>"
                : "") +
            '<div class="gms-profile__actions">' +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsPostBtnCopy"' +
            (!d.content ? " disabled" : "") + '>Sao chép</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsPostBtnSave">Lưu nháp</button>' +
            '<label class="gms-field-label" style="margin-top:8px">Lên lịch</label>' +
            '<div class="gms-post-schedule-row">' +
            '<input type="datetime-local" class="gms-input" id="gmsPostScheduleAt" />' +
            '<select class="gms-select" id="gmsPostScheduleMode">' +
            SCHEDULE_MODES.map(function (m) {
                return '<option value="' + m.id + '">' + m.label + "</option>";
            }).join("") +
            "</select>" +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsPostBtnSchedule"' +
            (!d.title ? " disabled" : "") + '>Lên lịch</button>' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsPostBtnPublish"' +
            (!d.title || !postState.canPublish ? " disabled" : "") + '>Đăng ngay</button>' +
            "</div>" +
            (!postState.canPublish
                ? '<p class="gms-hint">Chưa kết nối GBP — bài lưu nháp nội bộ; sao chép và đăng thủ công trên Google.</p>'
                : "") +
            "</div></div></div>"
        );
    }

    function renderListTable(ctx) {
        if (!postState.posts.length) {
            return '<div class="gms-empty gms-empty--sm"><p>Chưa có bài đăng — bấm «Tạo bài đăng» để bắt đầu.</p></div>';
        }
        return (
            '<div class="gms-table-wrap"><table class="gms-table"><thead><tr>' +
            "<th>Tiêu đề</th><th>Loại</th><th>Lịch / Ngày</th><th>CTA</th><th>Trạng thái</th><th></th></tr></thead><tbody>" +
            postState.posts.map(function (p) {
                var date = p.scheduled_at ? formatDate(p.scheduled_at) : (p.published_at ? formatDate(p.published_at) : formatDateShort(p.updated_at));
                var schedHint = p.schedule_mode && p.schedule_mode !== "once"
                    ? ' <span class="gms-muted">(' + (p.schedule_mode === "weekly" ? "tuần" : "tháng") + ")</span>"
                    : "";
                return "<tr><td><strong>" + ctx.esc(p.title || "—") + "</strong>" +
                    (p.last_error && p.status === "error"
                        ? '<br><span class="gms-muted gms-post-err">' + ctx.esc(p.last_error.slice(0, 80)) + "</span>"
                        : "") +
                    "</td><td>" + ctx.esc(p.post_type_label || p.post_type) + "</td><td>" + date + schedHint +
                    "</td><td>" + ctx.esc(p.cta_label || "—") + "</td><td>" + statusBadge(p.status) +
                    '</td><td><button type="button" class="gms-btn gms-btn--ghost gms-btn--xs" data-gms-post-view="' +
                    p.id + '">Chi tiết</button></td></tr>';
            }).join("") +
            "</tbody></table></div>"
        );
    }

    function renderCalendar(ctx) {
        if (!postState.calDays.length) {
            return '<p class="gms-hint">Không có bài trong khoảng thời gian này.</p>';
        }
        return (
            '<div class="gms-post-cal">' +
            postState.calDays.map(function (day) {
                return (
                    '<div class="gms-post-cal-day"><div class="gms-post-cal-day__head">' +
                    formatDateShort(day.date) + ' <span class="gms-muted">(' + day.posts.length + ")</span></div>" +
                    '<ul class="gms-post-cal-list">' +
                    day.posts.map(function (p) {
                        return '<li><button type="button" class="gms-post-cal-item" data-gms-post-view="' + p.id + '">' +
                            statusBadge(p.status) + " " + ctx.esc(p.title || "—") + "</button></li>";
                    }).join("") +
                    "</ul></div>"
                );
            }).join("") +
            "</div>"
        );
    }

    function renderDetail(ctx, post) {
        if (!post) return "";
        var suggestions = post.image_suggestions || [];
        return (
            '<div class="gms-card gms-post-detail">' +
            '<div class="gms-post-composer__head">' +
            "<div>" + statusBadge(post.status) + " <strong>" + ctx.esc(post.title) + "</strong></div>" +
            '<button type="button" class="gms-btn gms-btn--ghost gms-btn--xs" id="gmsPostCloseDetail">Đóng</button></div>' +
            '<p class="gms-muted">' + ctx.esc(post.post_type_label) + " · CTA: " + ctx.esc(post.cta_label) + "</p>" +
            '<p class="gms-post-detail__content">' + ctx.esc(post.content) + "</p>" +
            (suggestions.length
                ? '<p class="gms-field-label">Gợi ý hình ảnh</p><ul class="gms-steps">' +
                suggestions.map(function (s) { return "<li>" + ctx.esc(s) + "</li>"; }).join("") + "</ul>"
                : "") +
            (post.scheduled_at ? '<p class="gms-hint">Lên lịch: ' + formatDate(post.scheduled_at) + "</p>" : "") +
            (post.last_error ? '<p class="gms-post-err">' + ctx.esc(post.last_error) + "</p>" : "") +
            "</div>"
        );
    }

    function renderHtml(ctx) {
        var sum = postState.summary || {};
        var active = postState.activePostId
            ? postState.posts.find(function (p) { return String(p.id) === String(postState.activePostId); })
            : null;
        return (
            '<div class="gms-posts">' +
            '<div class="gms-card">' +
            '<div class="gms-post-toolbar">' +
            '<div><h2 class="gms-card-title" style="margin:0">Bài đăng Google Map</h2>' +
            '<p class="gms-hint">Tạo bài bằng AI · Lưu nháp nội bộ · Lên lịch ngày/tuần/tháng</p></div>' +
            '<button type="button" class="gms-btn gms-btn--primary gms-btn--xs" id="gmsPostOpenComposer">+ Tạo bài đăng</button></div>' +
            '<div class="gms-post-stats">' +
            '<span>Nháp: <strong>' + (sum.draft || 0) + "</strong></span>" +
            '<span>Lên lịch: <strong>' + (sum.scheduled || 0) + "</strong></span>" +
            '<span>Đã đăng: <strong>' + (sum.published || 0) + "</strong></span>" +
            '<span>Lỗi: <strong>' + (sum.error || 0) + "</strong></span></div>" +
            '<div class="gms-post-view-tabs">' +
            '<button type="button" class="gms-post-view-tab' + (postState.view === "list" ? " active" : "") + '" data-gms-post-view-tab="list">Danh sách</button>' +
            '<button type="button" class="gms-post-view-tab' + (postState.view === "calendar" ? " active" : "") + '" data-gms-post-view-tab="calendar">Lịch đăng</button>' +
            (postState.view === "calendar"
                ? '<span class="gms-post-cal-switch">' +
                CAL_VIEWS.map(function (v) {
                    return '<button type="button" class="gms-btn gms-btn--ghost gms-btn--xs' +
                        (postState.calView === v.id ? " active" : "") + '" data-gms-post-cal="' + v.id + '">' + v.label + "</button>";
                }).join("") +
                "</span>"
                : "") +
            "</div>" +
            (postState.loading
                ? '<p class="gms-hint">Đang tải…</p>'
                : (postState.view === "calendar" ? renderCalendar(ctx) : renderListTable(ctx))) +
            "</div>" +
            renderComposer(ctx) +
            (active ? renderDetail(ctx, active) : "") +
            "</div>"
        );
    }

    function readComposerForm(host) {
        function v(id) {
            var el = host.querySelector("#" + id);
            return el ? String(el.value || "").trim() : "";
        }
        return {
            post_type: v("gmsPostType") || "service_update",
            input: {
                keywords: v("gmsPostKeywords"),
                locality: v("gmsPostLocality"),
                goal: v("gmsPostGoal"),
                cta_type: v("gmsPostCta") || "learn_more",
            },
            title: v("gmsPostTitle"),
            content: v("gmsPostContent"),
            cta_type: v("gmsPostCta") || "learn_more",
            cta_label: v("gmsPostCtaLabel"),
            image_suggestions: (postState.draft && postState.draft.image_suggestions) || [],
        };
    }

    async function loadPosts(ctx, locId) {
        postState.loading = true;
        render(ctx.host, ctx);
        try {
            if (ctx.authToken()) {
                var res = await ctx.apiFetch("/posts?location_key=" + encodeURIComponent(locId));
                var data = res.data || {};
                postState.posts = data.posts || [];
                postState.summary = data.summary || null;
                postState.canPublish = !!data.can_publish;
            } else {
                postState.posts = readLs(locId);
                postState.summary = {
                    total: postState.posts.length,
                    draft: postState.posts.filter(function (p) { return p.status === "draft"; }).length,
                    scheduled: postState.posts.filter(function (p) { return p.status === "scheduled"; }).length,
                    published: postState.posts.filter(function (p) { return p.status === "published"; }).length,
                    error: postState.posts.filter(function (p) { return p.status === "error"; }).length,
                };
                postState.canPublish = false;
            }
        } catch (e) {
            ctx.showToast((e && e.message) || "Không tải được bài đăng.");
            postState.posts = readLs(locId);
        } finally {
            postState.loading = false;
            render(ctx.host, ctx);
        }
    }

    async function loadCalendar(ctx, locId) {
        postState.loading = true;
        render(ctx.host, ctx);
        var range = calRange(postState.calView);
        try {
            if (ctx.authToken()) {
                var q = "/posts/calendar?location_key=" + encodeURIComponent(locId) +
                    "&from=" + encodeURIComponent(range.from) + "&to=" + encodeURIComponent(range.to);
                var res = await ctx.apiFetch(q);
                postState.calDays = (res.data && res.data.days) || [];
            } else {
                var posts = readLs(locId);
                var byDate = {};
                posts.forEach(function (p) {
                    var key = (p.scheduled_at || p.published_at || p.updated_at || "").slice(0, 10);
                    if (!key) return;
                    byDate[key] = byDate[key] || [];
                    byDate[key].push(p);
                });
                postState.calDays = Object.keys(byDate).sort().map(function (d) {
                    return { date: d, posts: byDate[d] };
                });
            }
        } catch (_e) {
            postState.calDays = [];
        } finally {
            postState.loading = false;
            render(ctx.host, ctx);
        }
    }

    async function runAi(ctx, host, locId) {
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để dùng AI.");
            return;
        }
        var form = readComposerForm(host);
        postState.aiLoading = true;
        render(ctx.host, ctx);
        try {
            var res = await ctx.apiFetch("/posts/generate", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    post_type: form.post_type,
                    input: form.input,
                },
            });
            var data = res.data || {};
            postState.draft = {
                post_type: data.post_type || form.post_type,
                title: data.title || "",
                content: data.content || "",
                cta_type: data.cta_type || form.cta_type,
                cta_label: data.cta_label || "",
                image_suggestions: data.image_suggestions || [],
                input: form.input,
            };
            postState.warnings = data.warnings || [];
            ctx.showToast("Đã tạo bài đăng AI.");
        } catch (e) {
            ctx.showToast((e && e.message) || "AI thất bại.");
        } finally {
            postState.aiLoading = false;
            postState.composerOpen = true;
            render(ctx.host, ctx);
        }
    }

    async function saveDraft(ctx, host, locId) {
        var form = readComposerForm(host);
        if (!form.title || !form.content) {
            ctx.showToast("Nhập tiêu đề và nội dung trước.");
            return;
        }
        if (!ctx.authToken()) {
            var local = readLs(locId);
            var item = {
                id: "local_" + Date.now(),
                location_key: locId,
                post_type: form.post_type,
                post_type_label: (POST_TYPES.find(function (t) { return t.id === form.post_type; }) || {}).label,
                status: "draft",
                title: form.title,
                content: form.content,
                cta_type: form.cta_type,
                cta_label: form.cta_label,
                image_suggestions: form.image_suggestions,
                input: form.input,
                updated_at: new Date().toISOString(),
            };
            local.unshift(item);
            writeLs(locId, local);
            postState.posts = local;
            ctx.showToast("Đã lưu nháp trên trình duyệt.");
            postState.composerOpen = false;
            render(ctx.host, ctx);
            return;
        }
        try {
            var res = await ctx.apiFetch("/posts", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    post_type: form.post_type,
                    title: form.title,
                    content: form.content,
                    cta_type: form.cta_type,
                    cta_label: form.cta_label,
                    image_suggestions: form.image_suggestions,
                    input: form.input,
                    status: "draft",
                },
            });
            ctx.showToast("Đã lưu nháp.");
            postState.composerOpen = false;
            postState.draft = null;
            await loadPosts(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Lưu nháp thất bại.");
        }
    }

    async function scheduleDraft(ctx, host, locId) {
        var form = readComposerForm(host);
        var schedEl = host.querySelector("#gmsPostScheduleAt");
        var modeEl = host.querySelector("#gmsPostScheduleMode");
        var schedRaw = schedEl ? schedEl.value : "";
        if (!schedRaw) {
            ctx.showToast("Chọn ngày giờ lên lịch.");
            return;
        }
        var scheduledAt = new Date(schedRaw).toISOString();
        var mode = modeEl ? modeEl.value : "once";
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để lên lịch trên server.");
            return;
        }
        try {
            var created = await ctx.apiFetch("/posts", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    post_type: form.post_type,
                    title: form.title,
                    content: form.content,
                    cta_type: form.cta_type,
                    cta_label: form.cta_label,
                    image_suggestions: form.image_suggestions,
                    input: form.input,
                    status: "scheduled",
                    scheduled_at: scheduledAt,
                    schedule_mode: mode,
                },
            });
            var pid = created.data && created.data.id;
            if (pid) {
                await ctx.apiFetch("/posts/" + pid + "/schedule", {
                    method: "POST",
                    json: true,
                    body: { scheduled_at: scheduledAt, schedule_mode: mode },
                });
            }
            ctx.showToast("Đã lên lịch bài đăng.");
            postState.composerOpen = false;
            postState.draft = null;
            await loadPosts(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Lên lịch thất bại.");
        }
    }

    async function publishDraft(ctx, host, locId) {
        var form = readComposerForm(host);
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để đăng hoặc lưu nháp server.");
            return;
        }
        try {
            var created = await ctx.apiFetch("/posts", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    post_type: form.post_type,
                    title: form.title,
                    content: form.content,
                    cta_type: form.cta_type,
                    cta_label: form.cta_label,
                    image_suggestions: form.image_suggestions,
                    input: form.input,
                    status: "draft",
                },
            });
            var pid = created.data && created.data.id;
            if (!pid) throw new Error("Không tạo được bài.");
            await ctx.apiFetch("/posts/" + pid + "/publish", { method: "POST", json: true, body: {} });
            ctx.showToast("Đã xử lý đăng bài.");
            postState.composerOpen = false;
            postState.draft = null;
            await loadPosts(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Đăng bài thất bại — có thể đã lưu nháp.");
            await loadPosts(ctx, locId);
        }
    }

    function copyDraft(ctx, host) {
        var form = readComposerForm(host);
        var text = (form.title ? form.title + "\n\n" : "") + form.content;
        if (!text.trim()) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () { ctx.showToast("Đã sao chép."); });
        }
    }

    function bindEvents(host, ctx) {
        if (host._gmsPostClick) host.removeEventListener("click", host._gmsPostClick);
        var locId = ctx.location ? ctx.location.id : "default";
        host._gmsPostClick = function (e) {
            var tab = e.target && e.target.closest ? e.target.closest("[data-gms-post-view-tab]") : null;
            if (tab) {
                postState.view = tab.getAttribute("data-gms-post-view-tab");
                if (postState.view === "calendar") loadCalendar(ctx, locId);
                else loadPosts(ctx, locId);
                return;
            }
            var cal = e.target && e.target.closest ? e.target.closest("[data-gms-post-cal]") : null;
            if (cal) {
                postState.calView = cal.getAttribute("data-gms-post-cal");
                loadCalendar(ctx, locId);
                return;
            }
            var view = e.target && e.target.closest ? e.target.closest("[data-gms-post-view]") : null;
            if (view) {
                postState.activePostId = view.getAttribute("data-gms-post-view");
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsPostOpenComposer") {
                postState.composerOpen = true;
                postState.draft = postState.draft || { input: prefillFromLocation(ctx.location) };
                postState.warnings = [];
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsPostCloseComposer") {
                postState.composerOpen = false;
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsPostCloseDetail") {
                postState.activePostId = null;
                render(ctx.host, ctx);
                return;
            }
            if (e.target && e.target.id === "gmsPostBtnAi") runAi(ctx, host, locId);
            if (e.target && e.target.id === "gmsPostBtnSave") saveDraft(ctx, host, locId);
            if (e.target && e.target.id === "gmsPostBtnSchedule") scheduleDraft(ctx, host, locId);
            if (e.target && e.target.id === "gmsPostBtnPublish") publishDraft(ctx, host, locId);
            if (e.target && e.target.id === "gmsPostBtnCopy") copyDraft(ctx, host);
        };
        host.addEventListener("click", host._gmsPostClick);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
    }

    async function mount(host, ctx) {
        postState.view = "list";
        postState.activePostId = null;
        postState.composerOpen = false;
        postState.draft = null;
        postState.warnings = [];
        ctx.host = host;
        var locId = ctx.location ? ctx.location.id : "default";
        bindEvents(host, ctx);
        await loadPosts(ctx, locId);
    }

    window.GmsPosts = {
        mount: mount,
        reset: function () {
            postState.view = "list";
            postState.composerOpen = false;
            postState.activePostId = null;
        },
    };
})();
