/**
 * Google Map SEO — Quản lý Review & trả lời AI
 */
(function () {
    "use strict";

    var FILTERS = [
        { id: "all", label: "Tất cả" },
        { id: "5", label: "5 sao" },
        { id: "4", label: "4 sao" },
        { id: "3", label: "3 sao" },
        { id: "2", label: "2 sao" },
        { id: "1", label: "1 sao" },
        { id: "unreplied", label: "Chưa phản hồi" },
        { id: "negative", label: "Review tiêu cực" },
    ];

    var TONES = [
        { id: "professional", label: "Chuyên nghiệp" },
        { id: "friendly", label: "Thân thiện" },
        { id: "apology", label: "Xin lỗi & xử lý khiếu nại" },
        { id: "thankful", label: "Cảm ơn khách hàng" },
    ];

    var revState = {
        filter: "all",
        reviews: [],
        summary: null,
        source: "demo",
        canPost: false,
        activeReviewId: null,
        drafts: {},
        replyDrafts: {},
        loading: false,
        aiLoading: false,
    };

    function lsKey(locId, reviewId) {
        return "gms_rev_reply_" + locId + "_" + reviewId;
    }

    function readLs(locId, reviewId) {
        try {
            var raw = localStorage.getItem(lsKey(locId, reviewId));
            return raw ? JSON.parse(raw) : null;
        } catch (_e) {
            return null;
        }
    }

    function writeLs(locId, reviewId, data) {
        try {
            localStorage.setItem(lsKey(locId, reviewId), JSON.stringify(data));
        } catch (_e) {}
    }

    function starsHtml(n) {
        var s = "";
        for (var i = 0; i < 5; i++) s += i < n ? "★" : "☆";
        return s;
    }

    function formatDate(iso) {
        if (!iso) return "—";
        if (iso.indexOf("ngày") >= 0 || iso.indexOf("tuần") >= 0) return iso;
        try {
            return new Date(iso).toLocaleString("vi-VN", { dateStyle: "medium", timeStyle: "short" });
        } catch (_e) {
            return iso;
        }
    }

    function suggestTone(stars) {
        if (stars <= 2) return "apology";
        if (stars >= 4) return "thankful";
        return "professional";
    }

    function renderSummary(ctx, sum) {
        if (!sum) return "";
        return (
            '<div class="gms-rev-summary">' +
            '<div class="gms-rev-stat"><span class="gms-rev-stat__val">' +
            (sum.avg_stars != null ? sum.avg_stars + " ★" : "—") + "</span><span>Điểm TB</span></div>" +
            '<div class="gms-rev-stat"><span class="gms-rev-stat__val">' + sum.count + "</span><span>Tổng review</span></div>" +
            '<div class="gms-rev-stat"><span class="gms-rev-stat__val">' + sum.unreplied + "</span><span>Chưa phản hồi</span></div>" +
            '<div class="gms-rev-stat gms-rev-stat--alert"><span class="gms-rev-stat__val">' + sum.negative +
            "</span><span>Tiêu cực (1–2★)</span></div></div>"
        );
    }

    function renderReplyPanel(ctx, r, locId) {
        var rid = r.id;
        var active = revState.activeReviewId === rid;
        if (!active) return "";
        var draft = revState.replyDrafts[rid] || readLs(locId, rid) || {};
        var tone = draft.tone || suggestTone(r.stars);
        var text = draft.reply_text || draft.text || "";
        return (
            '<div class="gms-rev-reply-panel" id="gmsRevPanel-' + ctx.esc(rid) + '">' +
            '<label class="gms-field-label">Giọng văn phản hồi</label>' +
            '<select class="gms-select gms-rev-tone" data-gms-rev-tone="' + ctx.esc(rid) + '">' +
            TONES.map(function (t) {
                return '<option value="' + t.id + '"' + (t.id === tone ? " selected" : "") + ">" + t.label + "</option>";
            }).join("") +
            "</select>" +
            '<label class="gms-field-label">Nội dung phản hồi</label>' +
            '<textarea class="gms-textarea gms-rev-reply-text" data-gms-rev-text="' + ctx.esc(rid) + '" rows="5">' +
            ctx.esc(text) + "</textarea>" +
            '<div class="gms-profile__actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" data-gms-rev-ai="' + ctx.esc(rid) + '"' +
            (revState.aiLoading ? " disabled" : "") + ">Trả lời bằng AI</button>" +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-rev-copy="' + ctx.esc(rid) + '">Sao chép</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-rev-save="' + ctx.esc(rid) + '">Lưu nháp</button>' +
            '<button type="button" class="gms-btn gms-btn--primary" data-gms-rev-post="' + ctx.esc(rid) + '"' +
            (!revState.canPost || !text ? " disabled" : "") + ">Gửi phản hồi</button>" +
            "</div>" +
            (!revState.canPost
                ? '<p class="gms-hint">Kết nối GBP thật để gửi trực tiếp — hiện dùng sao chép / lưu nháp.</p>'
                : "") +
            "</div>"
        );
    }

    function renderReviewCard(ctx, r, locId) {
        var neg = r.is_negative || r.stars <= 2;
        var replied = !!r.replied;
        return (
            '<article class="gms-rev-card' + (neg ? " gms-rev-card--negative" : "") + '" data-review-id="' + ctx.esc(r.id) + '">' +
            (neg ? '<div class="gms-rev-alert">⚠ Review tiêu cực (1–2 sao) — ưu tiên phản hồi và xử lý khiếu nại.</div>' : "") +
            '<div class="gms-rev-card__head">' +
            "<div><strong>" + ctx.esc(r.author) + '</strong><span class="gms-stars">' + starsHtml(r.stars) + "</span></div>" +
            (replied
                ? '<span class="gms-badge gms-badge--ok">Đã phản hồi</span>'
                : '<span class="gms-badge gms-badge--warn">Chưa phản hồi</span>') +
            "</div>" +
            '<p class="gms-muted gms-rev-date">' + ctx.esc(formatDate(r.date)) + "</p>" +
            '<p class="gms-rev-text">' + ctx.esc(r.text) + "</p>" +
            (replied && r.reply_text
                ? '<div class="gms-rev-existing"><span class="gms-muted">Phản hồi của bạn:</span> ' + ctx.esc(r.reply_text) + "</div>"
                : "") +
            '<button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" data-gms-rev-toggle="' + ctx.esc(r.id) + '">' +
            (revState.activeReviewId === r.id ? "Đóng" : "Trả lời") + "</button>" +
            renderReplyPanel(ctx, r, locId) +
            "</article>"
        );
    }

    function renderHtml(ctx) {
        var locId = ctx.location ? ctx.location.id : "default";
        var sum = revState.summary;
        var srcLabel = revState.source === "google_business_profile" ? "đồng bộ từ Google" : "dữ liệu mẫu";
        return (
            '<div class="gms-reviews">' +
            '<div class="gms-card"><h2 class="gms-card-title">Review Google Map</h2>' +
            '<p class="gms-hint">Nguồn: ' + srcLabel + " · " + (revState.reviews.length) + " review hiển thị</p>" +
            renderSummary(ctx, sum) +
            '<div class="gms-rev-filters" role="tablist">' +
            FILTERS.map(function (f) {
                var on = f.id === revState.filter;
                return '<button type="button" class="gms-rev-filter' + (on ? " active" : "") + '" data-gms-rev-filter="' +
                    f.id + '">' + f.label + "</button>";
            }).join("") +
            "</div></div>" +
            (revState.loading
                ? '<div class="gms-card"><p class="gms-hint">Đang tải review…</p></div>'
                : (revState.reviews.length
                    ? '<div class="gms-rev-list">' + revState.reviews.map(function (r) {
                        return renderReviewCard(ctx, r, locId);
                    }).join("") + "</div>"
                    : '<div class="gms-empty gms-empty--sm"><p>Không có review phù hợp bộ lọc.</p></div>')) +
            "</div>"
        );
    }

    async function loadReviews(ctx, locId) {
        revState.loading = true;
        render(ctx.host, ctx);
        try {
            if (ctx.authToken()) {
                var res = await ctx.apiFetch(
                    "/reviews?location_key=" + encodeURIComponent(locId) + "&filter=" + encodeURIComponent(revState.filter)
                );
                var data = res.data || {};
                revState.reviews = data.reviews || [];
                revState.summary = data.summary || null;
                revState.source = data.source || "demo";
                revState.canPost = !!data.can_post_reply;
            } else {
                revState.reviews = [];
                revState.summary = { count: 0, avg_stars: null, unreplied: 0, negative: 0 };
                revState.source = "demo";
                revState.canPost = false;
                ctx.showToast("Đăng nhập để xem review — hoặc bật dữ liệu mẫu từ Tổng quan.");
            }
        } catch (e) {
            ctx.showToast((e && e.message) || "Không tải được review.");
            revState.reviews = [];
        } finally {
            revState.loading = false;
            render(ctx.host, ctx);
        }
    }

    async function loadDrafts(ctx, locId) {
        if (!ctx.authToken()) return;
        try {
            var res = await ctx.apiFetch("/reviews/drafts?location_key=" + encodeURIComponent(locId));
            var rows = res.data || [];
            rows.forEach(function (d) {
                if (d.review_id) revState.replyDrafts[d.review_id] = d;
            });
        } catch (_e) {}
    }

    function getReviewById(id) {
        return revState.reviews.find(function (r) { return r.id === id; });
    }

    function getReplyText(host, reviewId) {
        var ta = host.querySelector('[data-gms-rev-text="' + reviewId + '"]');
        return ta ? String(ta.value || "").trim() : "";
    }

    function getTone(host, reviewId) {
        var sel = host.querySelector('[data-gms-rev-tone="' + reviewId + '"]');
        return sel ? String(sel.value || "professional") : "professional";
    }

    async function runAi(ctx, host, locId, reviewId) {
        if (!ctx.authToken()) {
            ctx.showToast("Đăng nhập để dùng AI.");
            return;
        }
        var review = getReviewById(reviewId);
        if (!review) return;
        revState.aiLoading = true;
        render(ctx.host, ctx);
        try {
            var res = await ctx.apiFetch("/reviews/ai-reply", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    review: review,
                    tone: getTone(host, reviewId),
                    business: {
                        name: ctx.location && ctx.location.name,
                        category: ctx.location && ctx.location.category,
                        address: ctx.location && ctx.location.address,
                    },
                },
            });
            var data = res.data || {};
            revState.replyDrafts[reviewId] = { tone: data.tone, reply_text: data.reply };
            writeLs(locId, reviewId, revState.replyDrafts[reviewId]);
            if (data.warnings && data.warnings.length) {
                ctx.showToast(data.warnings[0]);
            } else {
                ctx.showToast("Đã tạo phản hồi AI.");
            }
        } catch (e) {
            ctx.showToast((e && e.message) || "AI thất bại.");
        } finally {
            revState.aiLoading = false;
            revState.activeReviewId = reviewId;
            render(ctx.host, ctx);
        }
    }

    async function saveDraft(ctx, host, locId, reviewId) {
        var text = getReplyText(host, reviewId);
        if (!text) return;
        var tone = getTone(host, reviewId);
        revState.replyDrafts[reviewId] = { tone: tone, reply_text: text };
        writeLs(locId, reviewId, revState.replyDrafts[reviewId]);
        if (!ctx.authToken()) {
            ctx.showToast("Đã lưu nháp trên trình duyệt.");
            return;
        }
        try {
            await ctx.apiFetch("/reviews/drafts", {
                method: "POST",
                json: true,
                body: { location_key: locId, review_id: reviewId, tone: tone, reply_text: text },
            });
            ctx.showToast("Đã lưu nháp.");
        } catch (e) {
            ctx.showToast("Đã lưu local — " + ((e && e.message) || "lỗi server"));
        }
    }

    async function postReply(ctx, host, locId, reviewId) {
        var text = getReplyText(host, reviewId);
        if (!text) return;
        var review = getReviewById(reviewId);
        if (!review) return;
        try {
            await ctx.apiFetch("/reviews/post", {
                method: "POST",
                json: true,
                body: {
                    location_key: locId,
                    review_id: reviewId,
                    review_resource_name: review.resource_name || "",
                    reply_text: text,
                },
            });
            ctx.showToast("Đã gửi phản hồi lên Google.");
            revState.activeReviewId = null;
            await loadReviews(ctx, locId);
        } catch (e) {
            ctx.showToast((e && e.message) || "Không gửi được phản hồi.");
        }
    }

    function copyReply(ctx, host, reviewId) {
        var text = getReplyText(host, reviewId);
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () { ctx.showToast("Đã sao chép."); });
        } else {
            ctx.showToast("Chọn và sao chép thủ công.");
        }
    }

    function bindEvents(host, ctx) {
        if (host._gmsRevClick) host.removeEventListener("click", host._gmsRevClick);
        var locId = ctx.location ? ctx.location.id : "default";
        host._gmsRevClick = function (e) {
            var f = e.target && e.target.closest ? e.target.closest("[data-gms-rev-filter]") : null;
            if (f) {
                revState.filter = f.getAttribute("data-gms-rev-filter");
                loadReviews(ctx, locId);
                return;
            }
            var toggle = e.target && e.target.closest ? e.target.closest("[data-gms-rev-toggle]") : null;
            if (toggle) {
                var id = toggle.getAttribute("data-gms-rev-toggle");
                revState.activeReviewId = revState.activeReviewId === id ? null : id;
                render(ctx.host, ctx);
                return;
            }
            var ai = e.target && e.target.closest ? e.target.closest("[data-gms-rev-ai]") : null;
            if (ai) runAi(ctx, host, locId, ai.getAttribute("data-gms-rev-ai"));
            var cp = e.target && e.target.closest ? e.target.closest("[data-gms-rev-copy]") : null;
            if (cp) copyReply(ctx, host, cp.getAttribute("data-gms-rev-copy"));
            var sv = e.target && e.target.closest ? e.target.closest("[data-gms-rev-save]") : null;
            if (sv) saveDraft(ctx, host, locId, sv.getAttribute("data-gms-rev-save"));
            var post = e.target && e.target.closest ? e.target.closest("[data-gms-rev-post]") : null;
            if (post) postReply(ctx, host, locId, post.getAttribute("data-gms-rev-post"));
        };
        host.addEventListener("click", host._gmsRevClick);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
    }

    async function mount(host, ctx) {
        revState.filter = "all";
        revState.activeReviewId = null;
        revState.replyDrafts = {};
        ctx.host = host;
        var locId = ctx.location ? ctx.location.id : "default";
        await loadDrafts(ctx, locId);
        bindEvents(host, ctx);
        await loadReviews(ctx, locId);
    }

    window.GmsReviews = { mount: mount, reset: function () { revState.filter = "all"; revState.activeReviewId = null; } };
})();
