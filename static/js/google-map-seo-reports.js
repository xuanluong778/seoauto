/**
 * Google Map SEO — Báo cáo Agency (theo map & thời gian)
 */
(function () {
    "use strict";

    var API = "/api/google-map-seo";

    var METRICS = [
        { key: "map_score", label: "Map Score", suffix: "/100" },
        { key: "reviews_new", label: "Review mới" },
        { key: "reviews_replied", label: "Review đã phản hồi" },
        { key: "views", label: "Lượt xem" },
        { key: "calls", label: "Lượt gọi điện" },
        { key: "directions", label: "Lượt chỉ đường" },
        { key: "website_clicks", label: "Lượt click website" },
        { key: "posts_published", label: "Bài đăng đã đăng" },
        { key: "photos_new", label: "Ảnh mới" },
        { key: "issues_fixed", label: "Lỗi đã sửa" },
    ];

    var rptState = {
        period: "30d",
        data: null,
        loading: false,
    };

    function lsKey(locId) {
        return "gms_rpt_period_" + (locId || "default");
    }

    function readPeriod(locId) {
        try {
            return localStorage.getItem(lsKey(locId)) || "30d";
        } catch (_e) {
            return "30d";
        }
    }

    function writePeriod(locId, period) {
        try {
            localStorage.setItem(lsKey(locId), period);
        } catch (_e) {}
    }

    function fmtNum(n) {
        var v = Number(n);
        return Number.isFinite(v) ? v.toLocaleString("vi-VN") : "—";
    }

    function fmtDelta(delta, pct) {
        if (delta == null) return "—";
        var d = Number(delta);
        if (!Number.isFinite(d)) return "—";
        var sign = d > 0 ? "+" : "";
        var pctS = pct != null && Number.isFinite(Number(pct)) ? " (" + sign + Number(pct).toFixed(1) + "%)" : "";
        return sign + fmtNum(d) + pctS;
    }

    function deltaCls(delta) {
        var d = Number(delta);
        if (!Number.isFinite(d) || d === 0) return "gms-rpt-delta--flat";
        return d > 0 ? "gms-rpt-delta--up" : "gms-rpt-delta--down";
    }

    function sourceBadge(source, label) {
        if (source === "mixed") {
            return '<span class="gms-badge gms-badge--info">' + (label || "Dữ liệu thật + mẫu") + "</span>";
        }
        if (source === "demo") {
            return '<span class="gms-badge gms-badge--warn">' + (label || "Dữ liệu mẫu") + "</span>";
        }
        return '<span class="gms-badge gms-badge--ok">' + (label || "Dữ liệu thật") + "</span>";
    }

    function clientDemoReport(ctx, period) {
        var loc = ctx.location || {};
        var seed = (loc.id || "loc1").length + (loc.mapScore || 50);
        var months = [
            { label: "T1", views: 42, calls: 12, directions: 18, website_clicks: 8, map_score: Math.max(30, (loc.mapScore || 50) - 15) },
            { label: "T2", views: 55, calls: 18, directions: 22, website_clicks: 11, map_score: Math.max(32, (loc.mapScore || 50) - 12) },
            { label: "T3", views: 61, calls: 22, directions: 28, website_clicks: 14, map_score: Math.max(35, (loc.mapScore || 50) - 9) },
            { label: "T4", views: 78, calls: 28, directions: 35, website_clicks: 18, map_score: Math.max(38, (loc.mapScore || 50) - 6) },
            { label: "T5", views: 92, calls: 35, directions: 42, website_clicks: 22, map_score: Math.max(40, (loc.mapScore || 50) - 3) },
            { label: "T6", views: 105, calls: 41, directions: 48, website_clicks: 26, map_score: loc.mapScore || 50 },
        ];
        var series = months.map(function (m, i) {
            return {
                label: m.label,
                metrics: {
                    map_score: m.map_score,
                    reviews_new: 2 + (seed + i) % 5,
                    reviews_replied: 1 + (seed + i) % 4,
                    views: m.views * 8 + (seed % 20),
                    calls: m.calls + (seed % 5),
                    directions: m.directions + (seed % 6),
                    website_clicks: m.website_clicks + (seed % 4),
                    posts_published: i % 2 === 0 ? 1 : 0,
                    photos_new: (seed + i) % 3,
                    issues_fixed: Math.floor(i / 2) + 1,
                },
            };
        });
        var first = series[0].metrics;
        var last = series[series.length - 1].metrics;
        var comparison = { period_label: "T1 → T6", metrics: {} };
        METRICS.forEach(function (m) {
            var b = Number(first[m.key] || 0);
            var a = Number(last[m.key] || 0);
            comparison.metrics[m.key] = {
                before: b,
                after: a,
                delta: a - b,
                pct: b ? Math.round(((a - b) / b) * 1000) / 10 : (a ? 100 : null),
            };
        });
        var totals = {};
        METRICS.forEach(function (m) {
            if (m.key === "map_score") {
                totals[m.key] = last[m.key];
            } else {
                totals[m.key] = series.reduce(function (s, pt) {
                    return s + Number((pt.metrics || {})[m.key] || 0);
                }, 0);
            }
        });
        return {
            source: "demo",
            source_label: "Dữ liệu mẫu (chưa đăng nhập)",
            period: period,
            generated_at: new Date().toISOString(),
            location_key: loc.id || "loc1",
            location: {
                name: loc.name || "Địa điểm demo",
                address: loc.address || "",
                category: loc.category || "",
            },
            branding: {
                agency_name: "SEOAuto Agency",
                logo_url: null,
                accent_color: "#34a853",
                footer_text: "Báo cáo Google Map SEO — cấu trúc sẵn sàng white-label.",
                contact_email: null,
                white_label_ready: true,
            },
            totals: totals,
            comparison: comparison,
            series: series,
            chart_metrics: ["views", "calls", "directions", "website_clicks"],
        };
    }

    function renderKpis(ctx, totals) {
        return (
            '<div class="gms-rpt-kpis">' +
            METRICS.map(function (m) {
                var v = (totals || {})[m.key];
                var suffix = m.suffix || "";
                return (
                    '<div class="gms-rpt-kpi">' +
                    '<span class="gms-rpt-kpi-label">' + ctx.esc(m.label) + "</span>" +
                    '<strong class="gms-rpt-kpi-val">' + fmtNum(v) + suffix + "</strong></div>"
                );
            }).join("") +
            "</div>"
        );
    }

    function renderChart(ctx, series, keys) {
        if (!series || !series.length) return '<p class="gms-hint">Chưa có dữ liệu biểu đồ.</p>';
        var metricKeys = keys && keys.length ? keys : ["views", "calls"];
        var maxV = 1;
        series.forEach(function (pt) {
            metricKeys.forEach(function (k) {
                var v = Number((pt.metrics || {})[k] || 0);
                if (v > maxV) maxV = v;
            });
        });
        return (
            '<div class="gms-rpt-charts">' +
            metricKeys.map(function (k) {
                var label = (METRICS.find(function (m) { return m.key === k; }) || {}).label || k;
                return (
                    '<div class="gms-rpt-chart-block">' +
                    '<h3 class="gms-rpt-chart-title">' + ctx.esc(label) + "</h3>" +
                    '<div class="gms-chart gms-rpt-chart">' +
                    series.map(function (pt) {
                        var v = Number((pt.metrics || {})[k] || 0);
                        var h = Math.max(4, Math.round((v / maxV) * 100));
                        return (
                            '<div class="gms-chart-bar" style="height:' + h + '%" title="' + fmtNum(v) + '">' +
                            "<span>" + ctx.esc(pt.label || "") + "</span></div>"
                        );
                    }).join("") +
                    "</div></div>"
                );
            }).join("") +
            "</div>"
        );
    }

    function renderComparison(ctx, comparison) {
        var comp = (comparison || {}).metrics || {};
        return (
            '<div class="gms-table-wrap gms-rpt-table-wrap"><table class="gms-table gms-rpt-table">' +
            "<thead><tr><th>Chỉ số</th><th>Trước tối ưu</th><th>Sau tối ưu</th><th>Thay đổi</th></tr></thead><tbody>" +
            METRICS.map(function (m) {
                var c = comp[m.key] || {};
                return (
                    "<tr><td>" + ctx.esc(m.label) + "</td>" +
                    "<td>" + fmtNum(c.before) + (m.suffix || "") + "</td>" +
                    "<td><strong>" + fmtNum(c.after) + (m.suffix || "") + "</strong></td>" +
                    '<td class="' + deltaCls(c.delta) + '">' + fmtDelta(c.delta, c.pct) + "</td></tr>"
                );
            }).join("") +
            "</tbody></table></div>"
        );
    }

    function renderHtml(ctx) {
        var d = rptState.data;
        var loc = (d && d.location) || ctx.location || {};
        var branding = (d && d.branding) || {};
        var accent = branding.accent_color || "#34a853";
        var period = rptState.period || "30d";
        var periodOpts = [
            { v: "7d", l: "7 ngày" },
            { v: "30d", l: "30 ngày" },
            { v: "90d", l: "90 ngày" },
            { v: "6m", l: "6 tháng" },
        ];
        if (rptState.loading) {
            return '<div class="gms-card"><p class="gms-hint">Đang tải báo cáo…</p></div>';
        }
        if (!d) {
            return '<div class="gms-card"><p class="gms-hint">Chưa có dữ liệu báo cáo.</p></div>';
        }
        return (
            '<div class="gms-reports" style="--gms-rpt-accent:' + ctx.esc(accent) + '">' +
            '<div class="gms-rpt-agency-header">' +
            '<div class="gms-rpt-agency-brand">' +
            (branding.logo_url
                ? '<img class="gms-rpt-logo" src="' + ctx.esc(branding.logo_url) + '" alt="" />'
                : '<div class="gms-rpt-logo-ph">' + ctx.esc((branding.agency_name || "A").charAt(0)) + "</div>") +
            "<div><h2 class=\"gms-rpt-agency-name\">" + ctx.esc(branding.agency_name || "SEOAuto Agency") + "</h2>" +
            '<p class="gms-rpt-agency-sub">Báo cáo Google Map SEO cho khách hàng</p></div></div>' +
            '<div class="gms-rpt-agency-meta">' +
            sourceBadge(d.source, d.source_label) +
            '<span class="gms-muted gms-rpt-date">Tạo: ' + ctx.esc((d.generated_at || "").slice(0, 16).replace("T", " ")) + "</span></div></div>" +
            '<div class="gms-card gms-rpt-location-card">' +
            '<div class="gms-rpt-location-head">' +
            "<div><h2 class=\"gms-card-title\">" + ctx.esc(loc.name || "—") + "</h2>" +
            '<p class="gms-hint">' + ctx.esc(loc.address || "") +
            (loc.category ? " · " + ctx.esc(loc.category) : "") + "</p></div>" +
            '<div class="gms-rpt-toolbar">' +
            '<label class="gms-field-label" for="gmsRptPeriod">Kỳ báo cáo</label>' +
            '<select class="gms-select gms-rpt-period" id="gmsRptPeriod">' +
            periodOpts.map(function (o) {
                return '<option value="' + o.v + '"' + (period === o.v ? " selected" : "") + ">" + o.l + "</option>";
            }).join("") +
            "</select>" +
            '<button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" id="gmsRptRefresh">↻ Làm mới</button>' +
            '<button type="button" class="gms-btn gms-btn--primary gms-btn--xs" id="gmsRptCsv">Xuất CSV</button>' +
            '<button type="button" class="gms-btn gms-btn--primary gms-btn--xs" id="gmsRptPdf">Xuất PDF</button></div></div>' +
            renderKpis(ctx, d.totals) +
            "</div>" +
            '<div class="gms-grid-2">' +
            '<div class="gms-card"><h2 class="gms-card-title">Biểu đồ tăng trưởng</h2>' +
            renderChart(ctx, d.series, d.chart_metrics) +
            "</div>" +
            '<div class="gms-card"><h2 class="gms-card-title">Trước / Sau tối ưu</h2>' +
            '<p class="gms-hint gms-rpt-comp-hint">' + ctx.esc((d.comparison || {}).period_label || "") + " — so sánh điểm đầu và cuối kỳ.</p>" +
            renderComparison(ctx, d.comparison) +
            "</div></div>" +
            '<div class="gms-card gms-rpt-footer-card">' +
            '<p class="gms-rpt-wl-note"><span class="gms-badge gms-badge--info">White-label</span> ' +
            "Cấu trúc agency sẵn sàng — sau này tùy chỉnh logo, màu và footer qua API branding.</p>" +
            (branding.footer_text ? '<p class="gms-hint">' + ctx.esc(branding.footer_text) + "</p>" : "") +
            (branding.contact_email ? '<p class="gms-hint">Liên hệ: ' + ctx.esc(branding.contact_email) + "</p>" : "") +
            "</div></div>"
        );
    }

    async function loadReport(ctx) {
        var loc = ctx.location || {};
        var locKey = loc.id || "loc1";
        rptState.loading = true;
        render(ctx.host, ctx);
        try {
            if (ctx.authToken && ctx.authToken()) {
                var q = "?location_key=" + encodeURIComponent(locKey) + "&period=" + encodeURIComponent(rptState.period);
                var res = await ctx.apiFetch("/reports" + q);
                rptState.data = res.data || null;
            } else {
                rptState.data = clientDemoReport(ctx, rptState.period);
            }
        } catch (e) {
            ctx.showToast((e && e.message) || "Không tải được báo cáo.");
            rptState.data = clientDemoReport(ctx, rptState.period);
        } finally {
            rptState.loading = false;
            render(ctx.host, ctx);
        }
    }

    function exportFile(ctx, format) {
        var loc = ctx.location || {};
        var locKey = loc.id || "loc1";
        if (!ctx.authToken || !ctx.authToken()) {
            ctx.showToast("Đăng nhập để xuất file từ server — hoặc dùng dữ liệu mẫu trên màn hình.");
            return;
        }
        var q =
            "?location_key=" + encodeURIComponent(locKey) +
            "&period=" + encodeURIComponent(rptState.period) +
            "&format=" + encodeURIComponent(format);
        var tok = ctx.authToken();
        fetch(API + "/reports/export" + q, {
            headers: { Authorization: "Bearer " + tok },
        })
            .then(function (r) {
                if (!r.ok) throw new Error("Xuất " + format.toUpperCase() + " thất bại.");
                return r.blob().then(function (blob) {
                    var disp = r.headers.get("Content-Disposition") || "";
                    var match = /filename="?([^";]+)"?/.exec(disp);
                    var name = match ? match[1] : "gms-report." + format;
                    var url = URL.createObjectURL(blob);
                    var a = document.createElement("a");
                    a.href = url;
                    a.download = name;
                    a.click();
                    URL.revokeObjectURL(url);
                    ctx.showToast("Đã tải " + format.toUpperCase() + ".");
                });
            })
            .catch(function (e) {
                ctx.showToast((e && e.message) || "Xuất file thất bại.");
            });
    }

    function bindEvents(host, ctx) {
        if (host._gmsRptClick) host.removeEventListener("click", host._gmsRptClick);
        if (host._gmsRptChange) host.removeEventListener("change", host._gmsRptChange);
        var locId = ctx.location ? ctx.location.id : "default";
        host._gmsRptClick = function (e) {
            if (!e.target) return;
            if (e.target.id === "gmsRptRefresh") loadReport(ctx);
            if (e.target.id === "gmsRptCsv") exportFile(ctx, "csv");
            if (e.target.id === "gmsRptPdf") exportFile(ctx, "pdf");
        };
        host._gmsRptChange = function (e) {
            if (e.target && e.target.id === "gmsRptPeriod") {
                rptState.period = e.target.value || "30d";
                writePeriod(locId, rptState.period);
                loadReport(ctx);
            }
        };
        host.addEventListener("click", host._gmsRptClick);
        host.addEventListener("change", host._gmsRptChange);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
    }

    async function mount(host, ctx) {
        var locId = ctx.location ? ctx.location.id : "default";
        rptState.period = readPeriod(locId);
        rptState.data = null;
        ctx.host = host;
        bindEvents(host, ctx);
        render(host, ctx);
        await loadReport(ctx);
    }

    window.GmsReports = {
        mount: mount,
        reset: function () {
            rptState.data = null;
            rptState.loading = false;
        },
    };
})();
