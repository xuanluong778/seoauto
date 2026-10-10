/**
 * Google Map SEO — Lead Map Scanner (2-step, cost-optimized)
 */
(function () {
    "use strict";

    var API = "/api/google-map-seo/lead-scanner";

    var FILTERS = [
        { id: "", label: "Tất cả" },
        { id: "has_phone", label: "Có SĐT" },
        { id: "no_phone", label: "Không có SĐT" },
        { id: "has_website", label: "Có website" },
        { id: "no_website", label: "Chưa có website" },
        { id: "low_rating", label: "Rating thấp" },
        { id: "few_reviews", label: "Ít review" },
    ];

    var leadState = {
        mode: "keyword",
        config: null,
        quote: null,
        scan: null,
        history: [],
        filter: "",
        loading: false,
        quoting: false,
        detailLoadingId: null,
        activeScanId: null,
    };

    function fmtNum(n) {
        var v = Number(n);
        return Number.isFinite(v) ? v.toLocaleString("vi-VN") : "—";
    }

    function fmtDate(iso) {
        if (!iso) return "—";
        try { return new Date(iso).toLocaleString("vi-VN"); } catch (_e) { return iso; }
    }

    function readForm(host) {
        var modeEl = host.querySelector('input[name="gmsLeadMode"]:checked');
        return {
            mode: modeEl ? modeEl.value : "keyword",
            keyword: (host.querySelector("#gmsLeadKeyword") || {}).value || "",
            category: (host.querySelector("#gmsLeadCategory") || {}).value || "",
            province: (host.querySelector("#gmsLeadProvince") || {}).value || "",
            district: (host.querySelector("#gmsLeadDistrict") || {}).value || "",
            radius_km: Number((host.querySelector("#gmsLeadRadius") || {}).value || 5),
            limit: Number((host.querySelector("#gmsLeadLimit") || {}).value || 20),
        };
    }

    function payloadFromForm(host) {
        var f = readForm(host);
        return {
            mode: f.mode,
            keyword: String(f.keyword || "").trim(),
            category: String(f.category || "").trim(),
            province: String(f.province || "").trim(),
            district: String(f.district || "").trim(),
            radius_km: f.radius_km,
            limit: f.limit,
        };
    }

    function validatePayload(p) {
        if (p.mode === "keyword") {
            if (!p.keyword) return "Nhập từ khóa tìm kiếm.";
            return null;
        }
        if (!p.category) return "Nhập ngành nghề/danh mục.";
        if (!p.province) return "Nhập tỉnh/thành.";
        return null;
    }

    function configBanner(ctx) {
        var cfg = leadState.config || {};
        if (!cfg.enabled) {
            return '<div class="gms-lead-alert gms-lead-alert--warn" role="alert"><strong>Lead Map Scanner đang tắt</strong></div>';
        }
        if (!cfg.places_configured) {
            return (
                '<div class="gms-lead-alert gms-lead-alert--warn" role="alert">' +
                "<strong>Chưa cấu hình Google Places API</strong>" +
                "<p>Admin cần thêm <code>GOOGLE_PLACES_API_KEY</code> trong env backend.</p></div>"
            );
        }
        var bal = cfg.balance != null ? fmtNum(cfg.balance) : "—";
        var usage = cfg.usage || {};
        var html =
            '<div class="gms-lead-meta">' +
            '<span class="gms-badge gms-badge--ok">Places API sẵn sàng</span>' +
            (cfg.credits_enforced
                ? '<span class="gms-muted">Credit: <strong>' + ctx.esc(String(bal)) + "</strong></span>"
                : '<span class="gms-muted">Credit chưa bật</span>') +
            '<span class="gms-muted">Gói: <strong>' + ctx.esc(cfg.plan_slug || "free") + "</strong></span>" +
            '<span class="gms-muted">Quét hôm nay: <strong>' + fmtNum(usage.daily_used) + "/" + fmtNum(usage.daily_limit) + "</strong></span>" +
            '<span class="gms-muted">Tháng này: <strong>' + fmtNum(usage.monthly_used) + "/" + fmtNum(usage.monthly_limit) + "</strong></span>" +
            "</div>";
        if (cfg.detail_cost_warning) {
            html += '<p class="gms-lead-warn">' + ctx.esc(cfg.detail_cost_warning) + "</p>";
        }
        return html;
    }

    function quoteBreakdown(q) {
        if (!q) return "";
        var lines = [];
        if (q.from_cache) {
            lines.push("<li><strong>Dùng cache — 0 credit</strong> (đã quét gần đây)</li>");
        } else {
            if (q.geocode_cost) lines.push("<li>Geocode: " + q.geocode_cost + " credit</li>");
            lines.push(
                "<li>Tìm kiếm cơ bản: " + (q.search_pages || 0) + " trang = " + (q.search_cost || 0) + " credit</li>"
            );
            lines.push("<li><strong>Tổng quét cơ bản: " + (q.credit_required || 0) + " credit</strong></li>");
        }
        lines.push("<li>Dự kiến ~" + (q.expected_leads || q.limit || "—") + " lead</li>");
        lines.push("<li>Lấy dữ liệu: place_id, tên, địa chỉ, rating, review, category, link Map</li>");
        lines.push(
            '<li class="gms-lead-warn-li">SĐT/website: <strong>' + (q.detail_credit_per_lead || "—") +
            " credit/lead</strong> — chỉ khi bấm «Lấy SĐT»</li>"
        );
        return '<ul class="gms-lead-quote-list">' + lines.join("") + "</ul>";
    }

    function renderTable(ctx, rows, scanId) {
        if (!rows || !rows.length) {
            return '<p class="gms-hint">Chưa có lead — thử điều chỉnh từ khóa hoặc khu vực.</p>';
        }
        var detailCost = (leadState.config && leadState.config.costs && leadState.config.costs.place_detail) || 2;
        return (
            '<div class="gms-table-wrap gms-lead-table-wrap"><table class="gms-table gms-lead-table"><thead><tr>' +
            "<th>STT</th><th>Tên doanh nghiệp</th><th>SĐT</th><th>Địa chỉ</th><th>Website</th>" +
            "<th>Rating</th><th>Review</th><th>Category</th><th>Google Map</th><th>Trạng thái</th><th></th>" +
            "</tr></thead><tbody>" +
            rows.map(function (r) {
                var hasPhone = !!(r.phone && String(r.phone).trim());
                var hasWeb = !!(r.website && String(r.website).trim());
                var fetching = leadState.detailLoadingId === r.id;
                var detailBtn = "";
                if (!hasPhone && !r.detail_fetched) {
                    detailBtn =
                        '<button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" data-gms-lead-detail="' +
                        r.id + '" data-gms-lead-scan="' + scanId + '"' +
                        (fetching ? " disabled" : "") + ">Lấy SĐT (" + detailCost + ")</button>";
                } else if (r.detail_fetched && !hasPhone) {
                    detailBtn = '<span class="gms-muted gms-badge--xs">Không có SĐT</span>';
                }
                return (
                    "<tr>" +
                    "<td>" + ctx.esc(String(r.index || "—")) + "</td>" +
                    "<td><strong>" + ctx.esc(r.name || "—") + "</strong></td>" +
                    "<td>" + (hasPhone ? ctx.esc(r.phone) : '<span class="gms-muted">—</span>') + "</td>" +
                    "<td>" + ctx.esc(r.address || "—") + "</td>" +
                    "<td>" + (hasWeb
                        ? '<a href="' + ctx.esc(r.website) + '" target="_blank" rel="noopener" class="gms-lead-link">Link</a>'
                        : '<span class="gms-muted">—</span>') + "</td>" +
                    "<td>" + (r.rating != null ? Number(r.rating).toFixed(1) + " ★" : "—") + "</td>" +
                    "<td>" + fmtNum(r.review_count) + "</td>" +
                    "<td>" + ctx.esc(r.category || "—") + "</td>" +
                    "<td>" + (r.maps_url
                        ? '<a href="' + ctx.esc(r.maps_url) + '" target="_blank" rel="noopener" class="gms-lead-link">Mở</a>'
                        : "—") + "</td>" +
                    '<td><span class="gms-badge gms-badge--info gms-badge--xs">' + ctx.esc(r.lead_status_label || "Mới") + "</span></td>" +
                    "<td>" + detailBtn + "</td></tr>"
                );
            }).join("") +
            "</tbody></table></div>"
        );
    }

    function renderHistory(ctx) {
        var rows = leadState.history || [];
        if (!rows.length) return '<p class="gms-hint">Chưa có lịch sử quét.</p>';
        return (
            '<div class="gms-table-wrap"><table class="gms-table gms-lead-history-table"><thead><tr>' +
            "<th>Thời gian</th><th>Chế độ</th><th>Truy vấn</th><th>Lead</th><th>Credit</th><th>Nguồn</th><th></th></tr></thead><tbody>" +
            rows.map(function (h) {
                var q = h.mode === "category"
                    ? (h.category || "") + " · " + (h.district || "") + ", " + (h.province || "")
                    : (h.keyword || "");
                var active = leadState.activeScanId === h.id ? ' class="gms-lead-history-row--active"' : "";
                var src = h.data_source === "cache" ? "Cache" : "API";
                return (
                    "<tr" + active + ">" +
                    "<td>" + fmtDate(h.created_at) + "</td>" +
                    "<td>" + (h.mode === "category" ? "Ngành + KV" : "Từ khóa") + "</td>" +
                    "<td>" + ctx.esc(q) + "</td>" +
                    "<td>" + fmtNum(h.unique_count) + "/" + fmtNum(h.result_count) + "</td>" +
                    "<td>" + fmtNum(h.credits_charged) + "</td>" +
                    "<td>" + src + "</td>" +
                    '<td><button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" data-gms-lead-view="' +
                    h.id + '">Xem</button></td></tr>'
                );
            }).join("") +
            "</tbody></table></div>"
        );
    }

    function renderModal(ctx) {
        if (!leadState.quote) return "";
        var q = leadState.quote;
        return (
            '<div class="gms-lead-modal" id="gmsLeadModal" role="dialog" aria-modal="true">' +
            '<div class="gms-lead-modal__backdrop" data-gms-lead-modal-close></div>' +
            '<div class="gms-lead-modal__panel">' +
            "<h3>Xác nhận quét lead</h3>" +
            "<p>Chỉ quét danh sách cơ bản — <strong>không</strong> tự lấy SĐT toàn bộ.</p>" +
            quoteBreakdown(q) +
            '<div class="gms-lead-modal__actions">' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-lead-modal-close>Hủy</button>' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsLeadConfirmScan">Quét (' +
            (q.from_cache ? "0" : (q.credit_required || 0)) + " credit)</button></div></div></div>"
        );
    }

    function renderUpgradeModal(ctx, detail) {
        var msg = (detail && detail.message) || "Không đủ credit.";
        var url = (detail && detail.upgrade_url) || "/pricing";
        return (
            '<div class="gms-lead-modal" id="gmsLeadUpgradeModal" role="dialog" aria-modal="true">' +
            '<div class="gms-lead-modal__backdrop" data-gms-lead-upgrade-close></div>' +
            '<div class="gms-lead-modal__panel gms-lead-modal__panel--warn">' +
            "<h3>Không đủ credit</h3><p>" + ctx.esc(msg) + "</p>" +
            '<div class="gms-lead-modal__actions">' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-lead-upgrade-close>Đóng</button>' +
            '<a href="' + ctx.esc(url) + '" class="gms-btn gms-btn--primary">Nâng cấp / mua credit</a></div></div></div>'
        );
    }

    function renderHtml(ctx) {
        var mode = leadState.mode || "keyword";
        var scan = leadState.scan;
        var scanMeta = scan && scan.scan ? scan.scan : null;
        var fromCache = scan && scan.from_cache;
        return (
            '<div class="gms-leads">' +
            '<div class="gms-card"><h2 class="gms-card-title">Lead Map Scanner</h2>' +
            '<p class="gms-hint">Quét cơ bản qua Places API — SĐT chỉ lấy khi bạn xác nhận từng lead.</p>' +
            configBanner(ctx) +
            '<div class="gms-lead-modes" role="radiogroup" aria-label="Chế độ quét">' +
            '<label class="gms-lead-mode"><input type="radio" name="gmsLeadMode" value="keyword"' +
            (mode === "keyword" ? " checked" : "") + '> Quét theo <strong>từ khóa</strong></label>' +
            '<label class="gms-lead-mode"><input type="radio" name="gmsLeadMode" value="category"' +
            (mode === "category" ? " checked" : "") + '> Quét theo <strong>ngành nghề + khu vực</strong></label></div>' +
            '<div class="gms-lead-form">' +
            '<div class="gms-lead-form__row gms-lead-form__row--keyword"' + (mode === "keyword" ? "" : ' hidden') + '>' +
            '<div class="gms-lead-field gms-lead-field--wide"><label class="gms-field-label" for="gmsLeadKeyword">Từ khóa</label>' +
            '<input type="text" class="gms-input" id="gmsLeadKeyword" maxlength="300" placeholder="VD: spa quận 1" /></div></div>' +
            '<div class="gms-lead-form__row gms-lead-form__row--category"' + (mode === "category" ? "" : ' hidden') + '>' +
            '<div class="gms-lead-field"><label class="gms-field-label" for="gmsLeadCategory">Ngành nghề</label>' +
            '<input type="text" class="gms-input" id="gmsLeadCategory" maxlength="200" placeholder="VD: spa, nha khoa" /></div></div>' +
            '<div class="gms-lead-form__row">' +
            '<div class="gms-lead-field"><label class="gms-field-label" for="gmsLeadProvince">Tỉnh/thành</label>' +
            '<input type="text" class="gms-input" id="gmsLeadProvince" maxlength="120" placeholder="VD: TP.HCM" /></div>' +
            '<div class="gms-lead-field"><label class="gms-field-label" for="gmsLeadDistrict">Quận/huyện</label>' +
            '<input type="text" class="gms-input" id="gmsLeadDistrict" maxlength="120" placeholder="VD: Quận 1" /></div>' +
            '<div class="gms-lead-field"><label class="gms-field-label" for="gmsLeadRadius">Bán kính (km)</label>' +
            '<input type="number" class="gms-input" id="gmsLeadRadius" min="0.5" max="50" step="0.5" value="5" /></div>' +
            '<div class="gms-lead-field"><label class="gms-field-label" for="gmsLeadLimit">Số kết quả</label>' +
            '<select class="gms-select" id="gmsLeadLimit"><option value="20">20</option><option value="50">50</option><option value="100">100</option></select></div>' +
            '<div class="gms-lead-field gms-lead-field--action">' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsLeadScanBtn"' +
            (leadState.quoting || leadState.loading ? " disabled" : "") + ">Quét leads</button></div></div></div></div>" +
            (leadState.loading ? '<div class="gms-card"><p class="gms-hint">Đang quét lead…</p></div>' : "") +
            (scan
                ? '<div class="gms-card"><div class="gms-lead-result-head"><div><strong>' +
                fmtNum((scan.leads || []).length) + " lead</strong>" +
                (scanMeta ? ' · <span class="gms-muted">' + ctx.esc(fmtDate(scanMeta.created_at)) + "</span>" : "") +
                (fromCache ? ' <span class="gms-badge gms-badge--info">Dữ liệu từ cache</span>' : ' <span class="gms-badge gms-badge--ok">Dữ liệu API</span>') +
                "</div>" +
                '<div class="gms-lead-export"><select class="gms-select gms-lead-filter" id="gmsLeadFilter">' +
                FILTERS.map(function (f) {
                    return '<option value="' + f.id + '"' + (leadState.filter === f.id ? " selected" : "") + ">" + f.label + "</option>";
                }).join("") +
                "</select>" +
                '<button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" data-gms-lead-export="csv">CSV</button>' +
                '<button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" data-gms-lead-export="xlsx">XLSX</button></div></div>' +
                renderTable(ctx, scan.leads || [], leadState.activeScanId) + "</div>"
                : "") +
            '<div class="gms-card"><h3 class="gms-card-title">Lịch sử quét</h3>' + renderHistory(ctx) + "</div>" +
            renderModal(ctx) + "</div>"
        );
    }

    async function loadConfig(ctx) {
        try {
            var res = await ctx.apiFetch("/lead-scanner/config");
            leadState.config = res.data || null;
        } catch (_e) {
            leadState.config = { places_configured: false, enabled: false };
        }
    }

    async function loadHistory(ctx) {
        try {
            var res = await ctx.apiFetch("/lead-scanner/history?limit=25");
            leadState.history = (res.data && res.data.scans) || [];
        } catch (_e) {
            leadState.history = [];
        }
    }

    async function loadScan(ctx, scanId, filter) {
        var q = "/lead-scanner/scans/" + encodeURIComponent(scanId);
        if (filter) q += "?filter=" + encodeURIComponent(filter);
        var res = await ctx.apiFetch(q);
        leadState.scan = res.data || null;
        leadState.activeScanId = scanId;
        leadState.filter = filter || "";
    }

    function closeModals(host) {
        ["#gmsLeadModal", "#gmsLeadUpgradeModal"].forEach(function (sel) {
            var el = host.querySelector(sel);
            if (el) el.remove();
        });
    }

    function showUpgrade(host, ctx, detail) {
        closeModals(host);
        host.insertAdjacentHTML("beforeend", renderUpgradeModal(ctx, detail));
    }

    function parseErr(e) {
        var d = (e && e.payload && e.payload.detail) || {};
        return typeof d === "string" ? { message: d } : d;
    }

    async function requestQuote(ctx, host) {
        var payload = payloadFromForm(host);
        var err = validatePayload(payload);
        if (err) { ctx.showToast(err); return; }
        if (!(leadState.config && leadState.config.places_configured && leadState.config.enabled)) {
            ctx.showToast("Lead Scanner chưa sẵn sàng.");
            return;
        }
        leadState.quoting = true;
        render(host, ctx);
        try {
            var res = await ctx.apiFetch("/lead-scanner/quote", { method: "POST", json: true, body: payload });
            leadState.quote = res.data || null;
            closeModals(host);
            var q = leadState.quote || {};
            if (window.DigiSeoConfirmCredit) {
                var preview = {
                    module: "lead_scanner",
                    action: "basic_scan",
                    label: "Lead Map Scanner — quét cơ bản",
                    credit_cost: q.from_cache ? 0 : (q.credit_required || 0),
                    credit_balance: (leadState.config && leadState.config.balance) || 0,
                    from_cache: !!q.from_cache,
                    quota_key: "lead_scan",
                    quota_label: "Lead scan/tháng",
                    data_source: q.from_cache ? "cache" : "api",
                    data_source_label: q.from_cache
                        ? "Dữ liệu từ cache — không gọi API bên ngoài"
                        : "Sẽ gọi Google Places API sau khi xác nhận",
                    sufficient_credits: q.sufficient_credits !== false,
                    quota_exceeded: !!q.quota_exceeded,
                    can_proceed: q.can_proceed !== false,
                };
                var ok = await window.DigiSeoConfirmCredit({ preview: preview, quotaKey: "lead_scan" });
                if (ok) await runScan(ctx, host);
            } else {
                host.insertAdjacentHTML("beforeend", renderModal(ctx));
            }
        } catch (e) {
            var d = parseErr(e);
            ctx.showToast(d.message || (e && e.message) || "Không lấy được báo giá.");
        } finally {
            leadState.quoting = false;
            render(host, ctx);
        }
    }

    async function runScan(ctx, host) {
        var payload = payloadFromForm(host);
        closeModals(host);
        leadState.loading = true;
        render(host, ctx);
        try {
            var res = await ctx.apiFetch("/lead-scanner/scan", { method: "POST", json: true, body: payload });
            leadState.scan = res.data || null;
            leadState.activeScanId = leadState.scan && leadState.scan.scan ? leadState.scan.scan.id : null;
            leadState.quote = null;
            if (leadState.config && res.data && res.data.balance_after != null) {
                leadState.config.balance = res.data.balance_after;
            }
            var n = (res.data && res.data.scan && res.data.scan.unique_count) || 0;
            ctx.showToast(res.data && res.data.from_cache ? "Lấy từ cache — " + n + " lead." : "Quét xong — " + n + " lead.");
            await loadConfig(ctx);
            await loadHistory(ctx);
        } catch (e) {
            var d = parseErr(e);
            if (e && e.status === 402) showUpgrade(host, ctx, d);
            else if (e && e.status === 429) ctx.showToast(d.message || "Vượt giới hạn — thử lại sau.");
            else ctx.showToast(d.message || (e && e.message) || "Quét thất bại.");
        } finally {
            leadState.loading = false;
            leadState.quote = null;
            render(host, ctx);
        }
    }

    async function fetchLeadDetail(ctx, host, scanId, leadId) {
        if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
            var okDetail = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.leadDetail);
            if (!okDetail) return;
        }
        leadState.detailLoadingId = leadId;
        render(host, ctx);
        try {
            var res = await ctx.apiFetch(
                "/lead-scanner/scans/" + scanId + "/leads/" + leadId + "/detail",
                { method: "POST", json: true, body: {} }
            );
            var lead = res.data && res.data.lead;
            if (lead && leadState.scan && leadState.scan.leads) {
                leadState.scan.leads = leadState.scan.leads.map(function (r) {
                    return r.id === lead.id ? lead : r;
                });
            }
            if (leadState.config && res.data && res.data.balance_after != null) {
                leadState.config.balance = res.data.balance_after;
            }
            ctx.showToast(res.data && res.data.from_cache ? "Đã có SĐT (cache)." : "Đã lấy SĐT/website.");
        } catch (e) {
            var d = parseErr(e);
            if (e && e.status === 402) showUpgrade(host, ctx, d);
            else ctx.showToast(d.message || "Lấy SĐT thất bại.");
        } finally {
            leadState.detailLoadingId = null;
            render(host, ctx);
        }
    }

    function exportScan(ctx, fmt) {
        if (!leadState.activeScanId) { ctx.showToast("Chưa có kết quả."); return; }
        if (!ctx.authToken || !ctx.authToken()) { ctx.showToast("Đăng nhập để xuất."); return; }
        var exportCost = (leadState.config && leadState.config.costs && leadState.config.costs.export) || 0;
        // Không hiện confirm credit — backend/export API vẫn enforce credit nếu có.
        var q = "/scans/" + encodeURIComponent(leadState.activeScanId) + "/export?format=" + encodeURIComponent(fmt);
        if (leadState.filter) q += "&filter=" + encodeURIComponent(leadState.filter);
        fetch(API + q, { headers: { Authorization: "Bearer " + ctx.authToken() } })
            .then(function (r) {
                if (r.status === 402) throw new Error("Không đủ credit để xuất.");
                if (!r.ok) throw new Error("Xuất thất bại.");
                return r.blob().then(function (blob) {
                    var disp = r.headers.get("Content-Disposition") || "";
                    var match = /filename="?([^";]+)"?/.exec(disp);
                    var name = match ? match[1] : "lead-scan." + fmt;
                    var url = URL.createObjectURL(blob);
                    var a = document.createElement("a");
                    a.href = url; a.download = name; a.click();
                    URL.revokeObjectURL(url);
                    ctx.showToast("Đã tải " + fmt.toUpperCase() + ".");
                });
            })
            .catch(function (e) { ctx.showToast((e && e.message) || "Xuất thất bại."); });
    }

    function bindEvents(host, ctx) {
        if (host._gmsLeadClick) host.removeEventListener("click", host._gmsLeadClick);
        if (host._gmsLeadChange) host.removeEventListener("change", host._gmsLeadChange);
        host._gmsLeadClick = function (e) {
            var t = e.target;
            if (t && t.id === "gmsLeadScanBtn") { requestQuote(ctx, host); return; }
            if (t && t.id === "gmsLeadConfirmScan") { runScan(ctx, host); return; }
            if (t && t.closest && t.closest("[data-gms-lead-modal-close]")) { closeModals(host); leadState.quote = null; return; }
            if (t && t.closest && t.closest("[data-gms-lead-upgrade-close]")) { closeModals(host); return; }
            var detailBtn = t && t.closest ? t.closest("[data-gms-lead-detail]") : null;
            if (detailBtn) {
                fetchLeadDetail(ctx, host, detailBtn.getAttribute("data-gms-lead-scan"), detailBtn.getAttribute("data-gms-lead-detail"));
                return;
            }
            var viewBtn = t && t.closest ? t.closest("[data-gms-lead-view]") : null;
            if (viewBtn) {
                var sid = Number(viewBtn.getAttribute("data-gms-lead-view"));
                if (sid) loadScan(ctx, sid, leadState.filter).then(function () { render(host, ctx); });
                return;
            }
            var exp = t && t.closest ? t.closest("[data-gms-lead-export]") : null;
            if (exp) exportScan(ctx, exp.getAttribute("data-gms-lead-export") || "csv");
        };
        host._gmsLeadChange = function (e) {
            var t = e.target;
            if (t && t.name === "gmsLeadMode") { leadState.mode = t.value; render(host, ctx); return; }
            if (t && t.id === "gmsLeadFilter") {
                leadState.filter = t.value || "";
                if (leadState.activeScanId) loadScan(ctx, leadState.activeScanId, leadState.filter).then(function () { render(host, ctx); });
            }
        };
        host.addEventListener("click", host._gmsLeadClick);
        host.addEventListener("change", host._gmsLeadChange);
    }

    function render(host, ctx) {
        if (!host) return;
        ctx.host = host;
        host.innerHTML = renderHtml(ctx);
        bindEvents(host, ctx);
    }

    async function mount(host, ctx) {
        leadState.mode = "keyword";
        leadState.scan = null;
        leadState.quote = null;
        leadState.filter = "";
        leadState.activeScanId = null;
        ctx.host = host;
        render(host, ctx);
        if (!ctx.authToken()) {
            host.querySelector(".gms-leads").insertAdjacentHTML(
                "afterbegin",
                '<div class="gms-lead-alert gms-lead-alert--info">Đăng nhập để quét lead và lưu lịch sử.</div>'
            );
            return;
        }
        await loadConfig(ctx);
        await loadHistory(ctx);
        render(host, ctx);
    }

    window.GmsLeads = {
        mount: mount,
        reset: function () {
            leadState.scan = null;
            leadState.quote = null;
            leadState.loading = false;
            leadState.quoting = false;
            leadState.detailLoadingId = null;
        },
    };
})();
