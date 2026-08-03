/**
 * Google Map SEO — Phân tích đối thủ Local Pack
 */
(function () {
    "use strict";

    var cmpState = {
        keyword: "",
        locality: "",
        data: null,
        loading: false,
    };

    function lsKey(locId) {
        return "gms_comp_" + locId;
    }

    function readLs(locId) {
        try {
            var raw = localStorage.getItem(lsKey(locId));
            return raw ? JSON.parse(raw) : null;
        } catch (_e) {
            return null;
        }
    }

    function writeLs(locId, kw, loc) {
        try {
            localStorage.setItem(lsKey(locId), JSON.stringify({ keyword: kw, locality: loc }));
        } catch (_e) {}
    }

    function prefill(ctx) {
        var loc = ctx.location || {};
        var saved = readLs(loc.id || "default") || {};
        return {
            keyword: saved.keyword || loc.category || "dịch vụ SEO",
            locality: saved.locality || loc.address || loc.locality || "Quận 1, TP.HCM",
        };
    }

    function sourceBadge(source) {
        if (source === "demo") {
            return '<span class="gms-badge gms-badge--warn">Dữ liệu mẫu (demo)</span>';
        }
        if (source === "google_places") {
            return '<span class="gms-badge gms-badge--ok">Dữ liệu thật</span>';
        }
        return '<span class="gms-badge gms-badge--info">Chưa đủ dữ liệu</span>';
    }

    function fmtNum(n) {
        var v = Number(n);
        return Number.isFinite(v) ? v.toLocaleString("vi-VN") : "—";
    }

    function renderTable(ctx, rows) {
        if (!rows || !rows.length) return "";
        return (
            '<div class="gms-table-wrap gms-comp-table-wrap"><table class="gms-table gms-comp-table"><thead><tr>' +
            "<th>#</th><th>Doanh nghiệp</th><th>Review</th><th>Sao TB</th><th>Ngành</th>" +
            "<th>Ảnh</th><th>Bài đăng/tháng</th><th>Website</th><th>Điểm ước tính</th><th>K/c</th></tr></thead><tbody>" +
            rows.map(function (c) {
                var self = !!c.is_self;
                return (
                    "<tr" + (self ? ' class="gms-comp-row--self"' : "") + ">" +
                    "<td><strong>#" + ctx.esc(String(c.rank || "—")) + "</strong></td>" +
                    "<td>" + ctx.esc(c.name || "—") + (self ? ' <span class="gms-badge gms-badge--ok gms-badge--xs">Bạn</span>' : "") + "</td>" +
                    "<td>" + fmtNum(c.reviews) + "</td>" +
                    "<td>" + (c.rating != null ? Number(c.rating).toFixed(1) + " ★" : "—") + "</td>" +
                    "<td>" + ctx.esc(c.category || "—") + "</td>" +
                    "<td>" + fmtNum(c.photo_count) + "</td>" +
                    "<td>" + (c.posts_per_month != null ? Number(c.posts_per_month).toFixed(1) : "—") + "</td>" +
                    "<td>" + (c.website
                        ? '<a href="' + ctx.esc(c.website) + '" target="_blank" rel="noopener" class="gms-comp-link">Có</a>'
                        : '<span class="gms-muted">—</span>') + "</td>" +
                    "<td>" + (c.estimated_score != null ? c.estimated_score + "/100" : "—") + "</td>" +
                    "<td>" + ctx.esc(c.distance || "—") + "</td></tr>"
                );
            }).join("") +
            "</tbody></table></div>"
        );
    }

    function renderActions(ctx, actions) {
        if (!actions || !actions.length) {
            return '<p class="gms-hint">Chưa có gợi ý — cần dữ liệu so sánh.</p>';
        }
        var priCls = { high: "gms-comp-pri--high", medium: "gms-comp-pri--med", low: "gms-comp-pri--low" };
        return (
            '<div class="gms-table-wrap"><table class="gms-table"><thead><tr>' +
            "<th>Ưu tiên</th><th>Chỉ số</th><th>Khoảng cách</th><th>Cần làm gì để vượt đối thủ</th></tr></thead><tbody>" +
            actions.map(function (a) {
                var p = a.priority || "medium";
                return (
                    "<tr><td><span class=\"gms-comp-pri " + (priCls[p] || "") + "\">" +
                    (p === "high" ? "Cao" : p === "low" ? "Thấp" : "TB") + "</span></td>" +
                    "<td>" + ctx.esc(a.metric || "—") + "</td>" +
                    "<td>" + ctx.esc(a.gap || "—") + "</td>" +
                    "<td>" + ctx.esc(a.action || "") + "</td></tr>"
                );
            }).join("") +
            "</tbody></table></div>"
        );
    }

    function renderHtml(ctx) {
        var d = cmpState.data;
        var pre = prefill(ctx);
        var kw = cmpState.keyword || pre.keyword;
        var loc = cmpState.locality || pre.locality;
        return (
            '<div class="gms-competitors">' +
            '<div class="gms-card">' +
            '<h2 class="gms-card-title">Phân tích đối thủ Google Map</h2>' +
            '<p class="gms-hint">Nhập từ khóa + khu vực để xem Local Pack (demo minh họa cho đến khi có Places API).</p>' +
            '<div class="gms-comp-search">' +
            '<div><label class="gms-field-label" for="gmsCompKw">Từ khóa</label>' +
            '<input type="text" class="gms-input" id="gmsCompKw" maxlength="200" value="' + ctx.esc(kw) + '" placeholder="VD: dịch vụ SEO" /></div>' +
            '<div><label class="gms-field-label" for="gmsCompLoc">Khu vực</label>' +
            '<input type="text" class="gms-input" id="gmsCompLoc" maxlength="200" value="' + ctx.esc(loc) + '" placeholder="VD: Quận 1, TP.HCM" /></div>' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsCompSearch"' +
            (cmpState.loading ? " disabled" : "") + ">Phân tích</button></div></div>" +
            (cmpState.loading
                ? '<div class="gms-card"><p class="gms-hint">Đang phân tích…</p></div>'
                : (d
                    ? '<div class="gms-card">' +
                    '<div class="gms-comp-head">' +
                    "<div>" + sourceBadge(d.source) +
                    ' <span class="gms-muted">«' + ctx.esc(d.keyword) + "» · " + ctx.esc(d.locality) +
                    (d.radius_km ? " · bán kính " + d.radius_km + " km" : "") + "</span></div></div>" +
                    (d.disclaimer ? '<p class="gms-comp-disclaimer">' + ctx.esc(d.disclaimer) + "</p>" : "") +
                    (d.message
                        ? '<p class="gms-hint">' + ctx.esc(d.message) + "</p>"
                        : "") +
                    (d.summary
                        ? '<div class="gms-comp-summary">' +
                        "<span>Hạng của bạn: <strong>#" + d.summary.your_rank + "</strong></span>" +
                        "<span>Leader: <strong>" + ctx.esc(d.summary.leader_name) + "</strong> (" +
                        fmtNum(d.summary.leader_reviews) + " review)</span>" +
                        (d.summary.review_gap > 0
                            ? '<span class="gms-comp-gap">Cách leader ~' + d.summary.review_gap + " review</span>"
                            : "") +
                        "</div>"
                        : "") +
                    renderTable(ctx, d.competitors) +
                    "</div>" +
                    '<div class="gms-card"><h3 class="gms-card-title">Cần làm gì để vượt đối thủ</h3>' +
                    renderActions(ctx, d.actions) + "</div>"
                    : '<div class="gms-card gms-empty gms-empty--sm"><p>Nhập từ khóa và khu vực rồi bấm Phân tích.</p></div>')) +
            "</div>"
        );
    }

    async function runSearch(ctx, host, locId) {
        var kwEl = host.querySelector("#gmsCompKw");
        var locEl = host.querySelector("#gmsCompLoc");
        var kw = kwEl ? String(kwEl.value || "").trim() : "";
        var loc = locEl ? String(locEl.value || "").trim() : "";
        if (!kw || !loc) {
            ctx.showToast("Nhập từ khóa và khu vực.");
            return;
        }
        cmpState.keyword = kw;
        cmpState.locality = loc;
        writeLs(locId, kw, loc);
        cmpState.loading = true;
        render(ctx.host, ctx);
        try {
            if (ctx.authToken()) {
                var q = "/competitors?location_key=" + encodeURIComponent(locId) +
                    "&keyword=" + encodeURIComponent(kw) + "&locality=" + encodeURIComponent(loc);
                var res = await ctx.apiFetch(q);
                cmpState.data = res.data || null;
            } else {
                ctx.showToast("Đăng nhập để phân tích — hoặc bật dữ liệu mẫu từ Tổng quan.");
                cmpState.data = {
                    source: "insufficient",
                    message: "Đăng nhập để dùng phân tích đối thủ. Tab Tổng quan có thể bật chế độ demo.",
                    keyword: kw,
                    locality: loc,
                    competitors: [],
                    actions: [],
                };
            }
        } catch (e) {
            ctx.showToast((e && e.message) || "Phân tích thất bại.");
            cmpState.data = null;
        } finally {
            cmpState.loading = false;
            render(ctx.host, ctx);
        }
    }

    function bindEvents(host, ctx) {
        if (host._gmsCompClick) host.removeEventListener("click", host._gmsCompClick);
        var locId = ctx.location ? ctx.location.id : "default";
        host._gmsCompClick = function (e) {
            if (e.target && e.target.id === "gmsCompSearch") runSearch(ctx, host, locId);
        };
        host.addEventListener("click", host._gmsCompClick);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
    }

    async function mount(host, ctx) {
        var pre = prefill(ctx);
        cmpState.keyword = pre.keyword;
        cmpState.locality = pre.locality;
        cmpState.data = null;
        ctx.host = host;
        bindEvents(host, ctx);
        render(host, ctx);
        if (ctx.authToken()) {
            await runSearch(ctx, host, ctx.location ? ctx.location.id : "default");
        }
    }

    window.GmsCompetitors = {
        mount: mount,
        reset: function () {
            cmpState.data = null;
            cmpState.loading = false;
        },
    };
})();
