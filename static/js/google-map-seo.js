/**
 * Google Map SEO — mock UI dashboard (SEOAuto)
 */
(function () {
    "use strict";

    var LS_DEMO = "gms_demo_mode";
    var LS_COOLDOWN = "gms_sync_cooldown_until";
    var API = "/api/google-map-seo";

    var GBP_ERRORS = {
        access_denied: "Bạn đã hủy cấp quyền Google Business Profile.",
        no_refresh_token: "Google không trả refresh token — hãy kết nối lại và chọn Cho phép đầy đủ.",
        no_accounts: "Tài khoản Google không có quyền quản lý Business Profile nào.",
        callback_failed: "Kết nối thất bại — vui lòng thử lại.",
        invalid_state: "Phiên OAuth hết hạn — vui lòng bấm Kết nối lại.",
        missing_code: "Google không trả mã xác thực — vui lòng thử lại.",
        api_disabled:
            "Google Cloud chưa bật Business Profile API. Admin bật 2 API trong link bên dưới (cùng project OAuth), đợi 5–10 phút rồi kết nối lại.",
        api_forbidden:
            "Tài khoản Google hoặc project OAuth chưa có quyền gọi Business Profile API. Kiểm tra API đã bật và OAuth consent đã publish.",
        api_unauthorized: "Token Google không hợp lệ — hãy kết nối lại.",
        api_quota: "Vượt giới hạn gọi Google API (quota/phút). Đợi 1–2 phút rồi bấm «↻ Làm mới» hoặc kết nối lại.",
        accounts_failed: "Không lấy được danh sách tài khoản GBP — thử lại sau.",
        user_not_found: "Không tìm thấy tài khoản SEOAuto — đăng nhập lại rồi kết nối.",
    };

    var MOCK = {
        locations: [
            {
                id: "loc1",
                name: "DigiSEO Agency — Quận 1",
                address: "12 Nguyễn Huệ, Quận 1, TP.HCM",
                category: "Dịch vụ SEO",
                rating: 4.8,
                reviews: 127,
                unrepliedReviews: 5,
                views: 2840,
                calls: 86,
                directions: 214,
                websiteClicks: 142,
                mapScore: 78,
                profileComplete: 85,
                verified: true,
                verificationStatus: "verified",
                latestPost: { title: "Khuyến mãi audit SEO miễn phí tháng 6", date: "12/06/2026" },
                gbp: {
                    synced: true,
                    businessInfo: { hasName: true, hasAddress: true, hasPhone: true, hasHours: false, hoursDaysCovered: 6, verified: true },
                    category: { primary: "Dịch vụ SEO", secondaryCount: 2 },
                    description: { textLength: 180, hasLocalKeywords: false },
                    media: { photoCount: 22, videoCount: 2, hasLogo: true, hasCover: true },
                    reviews: { count: 127, avgRating: 4.8, unrepliedCount: 5 },
                    posts: { publishedCount: 3, daysSinceLastPost: 18 },
                    services: { itemCount: 8, hasDescriptions: true },
                    website: { url: "https://digiseo.vn", napConsistent: true, hasTracking: false, hasLocalLanding: true },
                },
            },
            {
                id: "loc2",
                name: "DigiSEO — Chi nhánh Thủ Đức",
                address: "88 Võ Văn Ngân, Thủ Đức, TP.HCM",
                category: "Marketing Agency",
                rating: 4.5,
                reviews: 43,
                unrepliedReviews: 12,
                views: 1120,
                calls: 31,
                directions: 67,
                websiteClicks: 58,
                mapScore: 62,
                profileComplete: 68,
                verified: true,
                verificationStatus: "pending",
                latestPost: { title: "5 lỗi Local SEO khiến mất khách trên Map", date: "05/06/2026" },
                gbp: {
                    synced: true,
                    businessInfo: { hasName: true, hasAddress: true, hasPhone: true, hasHours: true, hoursDaysCovered: 7, verified: false },
                    category: { primary: "Marketing Agency", secondaryCount: 0 },
                    description: { textLength: 320, hasLocalKeywords: true },
                    media: { photoCount: 9, videoCount: 0, hasLogo: true, hasCover: false },
                    reviews: { count: 43, avgRating: 4.5, unrepliedCount: 12 },
                    posts: { publishedCount: 2, daysSinceLastPost: 35 },
                    services: { itemCount: 3, hasDescriptions: false },
                    website: { url: "https://digiseo.vn", napConsistent: true, hasTracking: false, hasLocalLanding: false },
                },
            },
            {
                id: "loc3",
                name: "DigiSEO — Hà Nội",
                address: "45 Láng Hạ, Đống Đa, Hà Nội",
                category: "Dịch vụ Marketing",
                rating: 4.2,
                reviews: 18,
                unrepliedReviews: 8,
                views: 420,
                calls: 9,
                directions: 22,
                websiteClicks: 15,
                mapScore: 41,
                profileComplete: 52,
                verified: false,
                verificationStatus: "unverified",
                latestPost: null,
                gbp: {
                    synced: true,
                    businessInfo: { hasName: true, hasAddress: true, hasPhone: false, hasHours: false, hoursDaysCovered: 0, verified: false },
                    category: { primary: "Dịch vụ Marketing", secondaryCount: 0 },
                    description: null,
                    media: { photoCount: 4, videoCount: 0, hasLogo: false, hasCover: false },
                    reviews: { count: 18, avgRating: 4.2, unrepliedCount: 8 },
                    posts: { publishedCount: 0, daysSinceLastPost: null },
                    services: null,
                    website: null,
                },
            },
        ],
        checkIssues: [],
        profileFields: [
            { name: "Tên doanh nghiệp", done: true },
            { name: "Địa chỉ & bản đồ", done: true },
            { name: "Số điện thoại", done: true },
            { name: "Website", done: true },
            { name: "Giờ mở cửa", done: false },
            { name: "Mô tả (750 ký tự)", done: false },
            { name: "Danh mục chính", done: true },
            { name: "Dịch vụ / Sản phẩm", done: false },
            { name: "Thuộc tính (Attributes)", done: false },
            { name: "Liên kết đặt lịch", done: false },
        ],
        reviews: [
            { author: "Minh Tuấn", stars: 5, date: "2 ngày trước", text: "Dịch vụ SEO rất chuyên nghiệp, tư vấn nhiệt tình. Website lên top nhanh hơn dự kiến." },
            { author: "Lan Anh", stars: 4, date: "1 tuần trước", text: "Báo cáo rõ ràng, team hỗ trợ nhanh. Mong thêm tài liệu hướng dẫn chi tiết hơn." },
            { author: "Hoàng Nam", stars: 5, date: "2 tuần trước", text: "Tối ưu Google Map giúp shop nhận thêm khách gọi điện mỗi tuần." },
            { author: "Thu Hà", stars: 3, date: "3 tuần trước", text: "Kết quả ổn nhưng thời gian triển khai hơi lâu so với cam kết ban đầu." },
        ],
        posts: [
            { title: "Khuyến mãi audit SEO miễn phí tháng 6", type: "Ưu đãi", date: "12/06/2026", status: "published" },
            { title: "5 lỗi Local SEO khiến mất khách trên Map", type: "Cập nhật", date: "05/06/2026", status: "published" },
            { title: "Mở rộng giờ tư vấn cuối tuần", type: "Sự kiện", date: "28/05/2026", status: "published" },
            { title: "Bản nháp: Case study tăng 40% cuộc gọi", type: "Cập nhật", date: "—", status: "draft" },
        ],
        media: [
            { label: "Logo", count: 1 },
            { label: "Ảnh bìa", count: 1 },
            { label: "Nội thất văn phòng", count: 8 },
            { label: "Đội ngũ", count: 4 },
            { label: "Sản phẩm / Dịch vụ", count: 6 },
            { label: "Video", count: 2 },
        ],
        competitors: [
            { name: "SEO Việt Pro", rating: 4.6, reviews: 198, distance: "1.2 km", rank: 2 },
            { name: "TopRank Agency", rating: 4.4, reviews: 89, distance: "2.8 km", rank: 4 },
            { name: "Local Boost VN", rating: 4.7, reviews: 156, distance: "0.9 km", rank: 1 },
            { name: "DigiSEO Agency", rating: 4.8, reviews: 127, distance: "—", rank: 3, self: true },
        ],
        reportMonths: [
            { label: "T1", views: 42, calls: 12 },
            { label: "T2", views: 55, calls: 18 },
            { label: "T3", views: 61, calls: 22 },
            { label: "T4", views: 78, calls: 28 },
            { label: "T5", views: 92, calls: 35 },
            { label: "T6", views: 105, calls: 41 },
        ],
    };

    var state = {
        locationId: MOCK.locations[0].id,
        tab: "overview",
        googleConnected: false,
        demoMode: false,
        locations: [],
        gbpStatus: null,
        lastGbpError: null,
        loading: false,
        syncing: false,
        cooldownUntil: 0,
        cooldownTimer: null,
    };

    function getConnectionState() {
        var st = state.gbpStatus || {};
        if (st.sync_status) return st.sync_status === "pending" ? "connected_no_locations" : st.sync_status;
        if (st.connection_state) return st.connection_state;
        if (!st.connected) return "not_connected";
        if (st.api_quota_limited) return "rate_limited";
        if ((st.locations_count || 0) === 0 && !(state.locations || []).length) return "connected_no_locations";
        return "connected";
    }

    function isRateLimitedState() {
        var cs = getConnectionState();
        return cs === "rate_limited" || !!(state.gbpStatus && state.gbpStatus.api_quota_limited);
    }

    function isOAuthReconnectNeeded() {
        var st = state.gbpStatus || {};
        if (st.oauth_valid === false) return true;
        var code = st.error_code || state.lastGbpError;
        return code === "oauth_invalid" || code === "no_refresh_token" || code === "api_unauthorized" || code === "invalid_state";
    }

    function reconnectButtonHtml() {
        if (!isOAuthReconnectNeeded()) return "";
        return '<button type="button" class="gms-btn gms-btn--secondary" id="gmsPendingReconnect">Kết nối lại Google</button>';
    }

    function readCooldownUntil() {
        try {
            var raw = localStorage.getItem(LS_COOLDOWN);
            var n = raw ? parseInt(raw, 10) : 0;
            return Number.isFinite(n) ? n : 0;
        } catch (_e) {
            return 0;
        }
    }

    function writeCooldownUntil(ts) {
        try {
            if (ts && ts > Date.now()) localStorage.setItem(LS_COOLDOWN, String(ts));
            else localStorage.removeItem(LS_COOLDOWN);
        } catch (_e) {}
    }

    function applyCooldownFromStatus(st) {
        if (!st) return;
        if (st.retry_after_seconds != null && Number(st.retry_after_seconds) > 0) {
            state.cooldownUntil = Date.now() + Number(st.retry_after_seconds) * 1000;
            writeCooldownUntil(state.cooldownUntil);
            startCooldownTicker();
            return;
        }
        var untilIso = st.rate_limit_until;
        if (!untilIso) return;
        var ts = Date.parse(untilIso);
        if (Number.isFinite(ts) && ts > Date.now()) {
            state.cooldownUntil = ts;
            writeCooldownUntil(ts);
            startCooldownTicker();
        }
    }

    function isSyncBlocked() {
        var now = Date.now();
        if (state.syncing || state.loading) return true;
        if (!state.cooldownUntil) state.cooldownUntil = readCooldownUntil();
        return state.cooldownUntil > now;
    }

    function cooldownSecondsLeft() {
        if (!state.cooldownUntil) state.cooldownUntil = readCooldownUntil();
        return Math.max(0, Math.ceil((state.cooldownUntil - Date.now()) / 1000));
    }

    function formatCooldown(sec) {
        var s = Math.max(0, sec || 0);
        var m = Math.floor(s / 60);
        var r = s % 60;
        return (m > 0 ? m + " phút " : "") + r + " giây";
    }

    function updateCooldownUiOnly() {
        var left = cooldownSecondsLeft();
        var blocked = isSyncBlocked();
        var label = document.getElementById("gmsCooldownLabel");
        if (label) label.textContent = formatCooldown(left);
        var syncBtn = document.getElementById("gmsPendingSync");
        if (syncBtn) {
            syncBtn.disabled = blocked || state.syncing;
            syncBtn.textContent = state.syncing ? "Đang đồng bộ…" : "Thử đồng bộ lại";
        }
        var bannerRetry = document.getElementById("gmsBannerRetrySync");
        if (bannerRetry) {
            bannerRetry.disabled = blocked || state.syncing;
        }
        var refresh = $("gmsBtnRefresh");
        if (refresh) {
            refresh.disabled = blocked || state.syncing;
            refresh.textContent = state.syncing ? "Đang đồng bộ…" : "↻ Làm mới";
        }
    }

    function startCooldownTicker() {
        if (state.cooldownTimer) return;
        state.cooldownTimer = window.setInterval(function () {
            if (!isSyncBlocked()) {
                window.clearInterval(state.cooldownTimer);
                state.cooldownTimer = null;
                state.cooldownUntil = 0;
                writeCooldownUntil(0);
                updateChrome();
                return;
            }
            updateCooldownUiOnly();
        }, 1000);
    }

    function setCooldown(seconds) {
        var sec = Math.max(120, Math.min(seconds || 120, 600));
        state.cooldownUntil = Date.now() + sec * 1000;
        writeCooldownUntil(state.cooldownUntil);
        startCooldownTicker();
        updateCooldownUiOnly();
    }

    function authToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            var t = window.DigiSeoGetAuthToken();
            if (t) return t;
        }
        try {
            var key = "seo_token";
            var t2 = (localStorage.getItem(key) || sessionStorage.getItem(key) || "").trim();
            if (t2) return t2;
            var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
        } catch (_e) {
            return "";
        }
    }

    function promptLoginForGbp() {
        showToast("Vui lòng đăng nhập SEOAuto để kết nối Google Business Profile.");
        if (typeof window.DigiSeoRememberPostLoginReturn === "function") {
            window.DigiSeoRememberPostLoginReturn();
        }
        if (typeof window.DigiSeoGoLogin === "function") {
            window.DigiSeoGoLogin();
            return;
        }
        if (typeof window.DigiSeoOpenLoginModal === "function") {
            window.DigiSeoOpenLoginModal();
            return;
        }
        window.location.href = "/?login=1";
    }

    function migrateLegacyPrefs() {
        try {
            var old = localStorage.getItem("gms_google_connected");
            if (old === "1" && localStorage.getItem(LS_DEMO) !== "0") {
                localStorage.setItem(LS_DEMO, "1");
            }
            localStorage.removeItem("gms_google_connected");
        } catch (_e) {}
    }

    function authHeaders(json) {
        var h = { Accept: "application/json" };
        var t = authToken();
        if (t) h.Authorization = "Bearer " + t;
        if (json) h["Content-Type"] = "application/json";
        return h;
    }

    function apiDetail(data) {
        if (!data) return "Yêu cầu thất bại.";
        if (typeof data.detail === "string") return data.detail;
        if (data.detail && data.detail.message) return String(data.detail.message);
        return "Yêu cầu thất bại.";
    }

    async function apiFetch(path, opts) {
        opts = opts || {};
        var r = await fetch(API + path, {
            method: opts.method || "GET",
            headers: authHeaders(opts.json),
            body: opts.body ? JSON.stringify(opts.body) : undefined,
            credentials: "same-origin",
            cache: "no-store",
        });
        var data = {};
        try { data = await r.json(); } catch (_e) {}
        if (!r.ok) {
            var err = new Error(apiDetail(data));
            err.status = r.status;
            err.payload = data;
            throw err;
        }
        return data;
    }

    function activeLocations() {
        return state.demoMode ? MOCK.locations : state.locations;
    }

    function readDemoPref() {
        try {
            return localStorage.getItem(LS_DEMO) === "1";
        } catch (_e) {}
        return false;
    }

    function saveDemoPref(on) {
        try {
            localStorage.setItem(LS_DEMO, on ? "1" : "0");
        } catch (_e) {}
    }

    function fmtNum(n) {
        var v = Number(n);
        if (!Number.isFinite(v)) return "0";
        return v.toLocaleString("vi-VN");
    }

    function scoreLevel(score) {
        if (score >= 75) return "good";
        if (score >= 50) return "warn";
        return "err";
    }

    function scoreLevelLabel(level) {
        if (level === "good") return "Tốt";
        if (level === "warn") return "Cảnh báo";
        return "Cần cải thiện";
    }

    function verificationBadge(status) {
        if (status === "verified") {
            return '<span class="gms-badge gms-badge--ok">Đã xác minh</span>';
        }
        if (status === "pending") {
            return '<span class="gms-badge gms-badge--info">Đang chờ duyệt</span>';
        }
        if (status === "needs_reverify") {
            return '<span class="gms-badge gms-badge--danger">Cần xác minh lại</span>';
        }
        if (status === "rejected") {
            return '<span class="gms-badge gms-badge--err">Bị từ chối</span>';
        }
        return '<span class="gms-badge gms-badge--warn">Chưa xác minh</span>';
    }

    function healthBadge(score) {
        var level = scoreLevel(score);
        var cls = badgeClass(level === "good" ? "ok" : level === "warn" ? "warn" : "err");
        return '<span class="gms-badge ' + cls + '">Map: ' + scoreLevelLabel(level) + "</span>";
    }

    function $(id) {
        return document.getElementById(id);
    }

    function esc(s) {
        if (s == null) return "";
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function badgeClass(level) {
        if (level === "ok") return "gms-badge--ok";
        if (level === "warn") return "gms-badge--warn";
        if (level === "err") return "gms-badge--err";
        return "gms-badge--info";
    }

    function badgeLabel(level) {
        if (level === "ok") return "OK";
        if (level === "warn") return "Cảnh báo";
        if (level === "err") return "Lỗi";
        return "Info";
    }

    function currentLocation() {
        var locs = activeLocations();
        return locs.find(function (l) { return l.id === state.locationId; }) || locs[0] || null;
    }

    function scoreRing(score) {
        var pct = Math.max(0, Math.min(100, score));
        var r = 42;
        var c = 2 * Math.PI * r;
        var off = c - (pct / 100) * c;
        var color = pct >= 75 ? "#34a853" : pct >= 50 ? "#fbbf24" : "#f87171";
        return (
            '<div class="gms-score-ring">' +
            '<svg viewBox="0 0 100 100" aria-hidden="true">' +
            '<circle cx="50" cy="50" r="' + r + '" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="10"/>' +
            '<circle cx="50" cy="50" r="' + r + '" fill="none" stroke="' + color + '" stroke-width="10" ' +
            'stroke-dasharray="' + c + '" stroke-dashoffset="' + off + '" stroke-linecap="round"/>' +
            "</svg>" +
            '<div class="gms-score-ring__val">' + pct + "</div></div>"
        );
    }

    function showToast(msg) {
        var el = $("gmsToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        clearTimeout(showToast._t);
        showToast._t = setTimeout(function () { el.hidden = true; }, 2800);
    }

    function renderStats() {
        var host = $("gmsStatsBar");
        if (!host) return;
        if (!state.googleConnected || !activeLocations().length) {
            host.hidden = true;
            host.innerHTML = "";
            return;
        }
        host.hidden = false;
        var locs = activeLocations();
        var totalViews = locs.reduce(function (s, l) { return s + l.views; }, 0);
        var totalCalls = locs.reduce(function (s, l) { return s + l.calls; }, 0);
        var totalReviews = locs.reduce(function (s, l) { return s + l.reviews; }, 0);
        var avgScore = Math.round(
            locs.reduce(function (s, l) { return s + (getDisplayScore(l) || 0); }, 0) / locs.length
        );
        var unreplied = locs.reduce(function (s, l) { return s + (l.unrepliedReviews || 0); }, 0);
        host.innerHTML =
            '<article class="gms-stat-card"><div class="gms-stat-label">Địa điểm</div>' +
            '<div class="gms-stat-value">' + locs.length + "</div>" +
            '<div class="gms-stat-sub">đã kết nối GBP</div></article>' +
            '<article class="gms-stat-card"><div class="gms-stat-label">Map Score TB</div>' +
            '<div class="gms-stat-value">' + avgScore + "/100</div>" +
            '<div class="gms-stat-sub">' + scoreLevelLabel(scoreLevel(avgScore)) + "</div></article>" +
            '<article class="gms-stat-card"><div class="gms-stat-label">Tổng review</div>' +
            '<div class="gms-stat-value">' + fmtNum(totalReviews) + "</div>" +
            '<div class="gms-stat-sub' + (unreplied ? " gms-stat-trend--down" : "") + '">' +
            (unreplied ? unreplied + " chưa phản hồi" : "đã phản hồi đủ") + "</div></article>" +
            '<article class="gms-stat-card"><div class="gms-stat-label">Lượt xem (30 ngày)</div>' +
            '<div class="gms-stat-value">' + fmtNum(totalViews) + "</div>" +
            '<div class="gms-stat-sub gms-stat-trend--up">+12% so với kỳ trước</div></article>' +
            '<article class="gms-stat-card"><div class="gms-stat-label">Cuộc gọi</div>' +
            '<div class="gms-stat-value">' + fmtNum(totalCalls) + "</div>" +
            '<div class="gms-stat-sub">từ Google Map</div></article>';
    }

    function renderMetric(label, value, sub, alert) {
        return '<div class="gms-metric' + (alert ? " gms-metric--alert" : "") + '">' +
            '<div class="gms-metric__label">' + esc(label) + "</div>" +
            '<div class="gms-metric__value">' + esc(value) + "</div>" +
            (sub ? '<div class="gms-metric__sub">' + esc(sub) + "</div>" : "") +
            "</div>";
    }

    function renderLocationCard(loc) {
        var sc = getDisplayScore(loc);
        var level = scoreLevel(sc != null ? sc : 0);
        var latest = loc.latestPost
            ? "<strong>" + esc(loc.latestPost.title) + "</strong> · " + esc(loc.latestPost.date)
            : '<span class="gms-muted">Chưa có bài đăng — nên đăng ít nhất 1 bài/tháng</span>';
        return (
            '<article class="gms-loc-card gms-loc-card--' + level + '" data-gms-loc-id="' + esc(loc.id) + '">' +
            '<div class="gms-loc-card__head">' +
            "<div><h3 class=\"gms-loc-card__title\">" + esc(loc.name) + "</h3>" +
            '<p class="gms-loc-card__addr">' + esc(loc.address) + "</p>" +
            '<span class="gms-loc-card__cat">' + esc(loc.category) + "</span></div>" +
            '<div class="gms-loc-score gms-loc-score--' + level + '">' +
            '<span class="gms-loc-score__val">' + (sc != null ? sc : "—") + "</span>" +
            '<span class="gms-loc-score__label">Map Score</span></div></div>' +
            '<div class="gms-loc-badges">' + verificationBadge(loc.verificationStatus) +
            (sc != null ? healthBadge(sc) : "") +
            "</div>" +
            '<div class="gms-loc-metrics">' +
            renderMetric("Tổng review", fmtNum(loc.reviews), "đánh giá Google") +
            renderMetric("Điểm sao TB", loc.rating != null ? loc.rating + " \u2605" : "—", "trung bình") +
            renderMetric("Chưa phản hồi", fmtNum(loc.unrepliedReviews || 0), "cần xử lý", (loc.unrepliedReviews || 0) > 0) +
            renderMetric("Lượt xem", fmtNum(loc.views), "30 ngày qua") +
            renderMetric("Gọi điện", fmtNum(loc.calls), "từ Map") +
            renderMetric("Chỉ đường", fmtNum(loc.directions), "yêu cầu") +
            renderMetric("Click website", fmtNum(loc.websiteClicks), "từ hồ sơ") +
            renderMetric("Hoàn thiện hồ sơ", loc.profileComplete != null ? loc.profileComplete + "%" : "—", "GBP checklist") +
            "</div>" +
            '<div class="gms-loc-latest"><span class="gms-muted">Bài đăng gần nhất:</span> ' + latest + "</div>" +
            '<div class="gms-loc-actions">' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-action="check-map" data-gms-loc="' + esc(loc.id) + '">Check Map</button>' +
            '<button type="button" class="gms-btn gms-btn--primary" data-gms-action="profile" data-gms-loc="' + esc(loc.id) + '">Tối ưu ngay</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-action="reports" data-gms-loc="' + esc(loc.id) + '">Xem báo cáo</button>' +
            "</div></article>"
        );
    }

    function renderOverviewRateLimited() {
        if (activeLocations().length > 0) {
            return renderOverviewDashboard();
        }
        return (
            '<div class="gms-empty gms-empty--pending gms-empty--rate">' +
            '<div class="gms-empty__icon" aria-hidden="true">⏳</div>' +
            "<h2>Đã kết nối Google — chờ đồng bộ địa điểm</h2>" +
            "<p>Google API đang giới hạn lượt gọi tạm thời. Xem cảnh báo phía trên và bấm «Thử đồng bộ lại» khi hết thời gian chờ.</p>" +
            "</div>"
        );
    }

    function renderOverviewPendingSync() {
        if (isRateLimitedState()) {
            return renderOverviewRateLimited();
        }
        return (
            '<div class="gms-empty gms-empty--pending">' +
            '<div class="gms-empty__icon" aria-hidden="true">⏳</div>' +
            "<h2>Đã cấp quyền Google — chưa có địa điểm</h2>" +
            "<p>Google đã cấp quyền nhưng chưa đồng bộ được địa điểm. Bấm «Thử đồng bộ lại» trên thanh cảnh báo hoặc nút bên dưới.</p>" +
            '<div class="gms-empty-actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsPendingSync"' +
            (isSyncBlocked() || state.syncing ? " disabled" : "") + ">" +
            (state.syncing ? "Đang đồng bộ…" : "Thử đồng bộ lại") + "</button>" +
            reconnectButtonHtml() +
            "</div></div>"
        );
    }

    function renderOverviewEmpty() {
        return (
            '<div class="gms-empty">' +
            '<div class="gms-empty__icon" aria-hidden="true">📍</div>' +
            "<h2>Chưa kết nối Google Business Profile</h2>" +
            "<p>Kết nối tài khoản Google để đồng bộ địa điểm, review, bài đăng và chỉ số hiệu suất Map. " +
            "SEOAuto sẽ giúp bạn kiểm tra, tối ưu và theo dõi Local SEO tập trung.</p>" +
            '<div class="gms-empty-steps">' +
            '<div class="gms-empty-step"><span class="gms-empty-step__num">1</span><p>Đăng nhập bằng tài khoản Google sở hữu địa điểm trên Google Maps.</p></div>' +
            '<div class="gms-empty-step"><span class="gms-empty-step__num">2</span><p>Chọn một hoặc nhiều địa điểm cần quản lý trong Business Profile.</p></div>' +
            '<div class="gms-empty-step"><span class="gms-empty-step__num">3</span><p>Xem Map Score, review và chạy Check Map để tối ưu ngay.</p></div>' +
            "</div>" +
            '<div class="gms-empty-actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsEmptyConnect">Kết nối Google Business Profile</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" id="gmsEmptyDemo">Xem dữ liệu mẫu</button>' +
            "</div></div>"
        );
    }

    function renderOverviewDashboard() {
        var locs = activeLocations();
        var hint = state.demoMode
            ? locs.length + " địa điểm · dữ liệu mẫu minh họa"
            : locs.length + " địa điểm · đồng bộ từ Google Business Profile";
        return (
            '<div class="gms-overview-head">' +
            "<div><h2>Địa điểm Google Map</h2>" +
            '<p class="gms-hint">' + hint + "</p></div>" +
            '<div class="gms-overview-actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsOverviewConnect">+ Kết nối thêm địa điểm</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-goto="check-map">Check Map tất cả</button>' +
            '<button type="button" class="gms-btn gms-btn--secondary" data-gms-goto="reports">Xem báo cáo tổng</button>' +
            "</div></div>" +
            '<div class="gms-loc-list">' +
            locs.map(renderLocationCard).join("") +
            "</div>"
        );
    }

    function renderOverview() {
        var host = $("gmsPanelOverview");
        if (!host) return;
        var cs = getConnectionState();
        if (cs === "not_connected" || !state.googleConnected) {
            host.innerHTML = renderOverviewEmpty();
            return;
        }
        if (!state.demoMode && activeLocations().length > 0) {
            host.innerHTML = renderOverviewDashboard();
            return;
        }
        if (cs === "rate_limited") {
            host.innerHTML = renderOverviewRateLimited();
            return;
        }
        if (cs === "connected_no_locations") {
            host.innerHTML = renderOverviewPendingSync();
            return;
        }
        host.innerHTML = renderOverviewDashboard();
    }

    function updateDemoBadge() {
        var badge = $("gmsDemoBadge");
        if (!badge) return;
        badge.hidden = !(state.demoMode && state.googleConnected);
    }

    function gbpErrorMessage(code) {
        return GBP_ERRORS[code] || ("Lỗi kết nối: " + code);
    }

    function renderApiBanner() {
        var el = $("gmsApiBanner");
        if (!el) return;
        var st = state.gbpStatus;
        var err = state.lastGbpError;

        if (err === "api_disabled" || err === "api_forbidden") {
            var links = (st && st.api_setup_links) || [];
            var html = "<strong>" + esc(gbpErrorMessage(err)) + "</strong>";
            if (links.length) {
                html += '<ul class="gms-api-links">';
                links.forEach(function (l) {
                    html += '<li><a href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">' +
                        esc(l.label) + " — Bật API</a></li>";
                });
                html += "</ul>";
            }
            el.hidden = false;
            el.classList.add("gms-api-banner--err");
            el.innerHTML = html;
            return;
        }

        if (err) {
            el.hidden = false;
            el.classList.add("gms-api-banner--err");
            el.innerHTML = "<strong>" + esc(gbpErrorMessage(err)) + "</strong>";
            return;
        }

        if (st && (st.api_quota_limited || st.connection_state === "rate_limited" || st.sync_status === "rate_limited")) {
            el.hidden = false;
            el.classList.add("gms-api-banner--err");
            var left = cooldownSecondsLeft();
            var msg = st.friendly_message || gbpErrorMessage("api_quota");
            el.innerHTML =
                "<strong>" + esc(msg) + "</strong>" +
                (left > 0
                    ? '<p class="gms-hint gms-cooldown">Thử lại sau: <strong id="gmsCooldownLabel">' +
                      esc(formatCooldown(left)) + "</strong></p>"
                    : "") +
                '<div class="gms-api-banner-actions">' +
                '<button type="button" class="gms-btn gms-btn--primary gms-btn--sm" id="gmsBannerRetrySync"' +
                (isSyncBlocked() || state.syncing ? " disabled" : "") + ">Thử đồng bộ lại</button>" +
                reconnectButtonHtml() +
                "</div>";
            return;
        }

        if (st && st.sync_pending && st.last_sync_error) {
            el.hidden = false;
            el.classList.add("gms-api-banner--err");
            el.innerHTML = "<strong>" + esc(st.last_sync_error) + "</strong>";
            return;
        }

        if (!st || st.configured !== false || !st.is_admin) {
            el.hidden = true;
            el.textContent = "";
            el.innerHTML = "";
            el.classList.remove("gms-api-banner--err");
            return;
        }
        el.hidden = false;
        el.classList.remove("gms-api-banner--err");
        el.textContent = st.admin_message || "Chưa cấu hình API Google Business Profile trên server.";
    }

    function updateChrome() {
        document.body.classList.toggle("gms-not-connected", !state.googleConnected);
        document.body.classList.toggle("gms-rate-limited", getConnectionState() === "rate_limited");
        updateDemoBadge();
        renderApiBanner();
        var connect = $("gmsBtnConnect");
        if (connect) {
            connect.textContent = state.googleConnected
                ? "+ Kết nối thêm địa điểm"
                : "+ Kết nối Google Business";
        }
        var refresh = $("gmsBtnRefresh");
        if (refresh) {
            refresh.disabled = !!state.syncing || isSyncBlocked();
            refresh.textContent = state.syncing ? "Đang đồng bộ…" : "↻ Làm mới";
        }
    }

    function selectLocation(id) {
        if (!id) return;
        state.locationId = id;
        var sel = $("gmsLocationSelect");
        if (sel) sel.value = id;
    }

    function enableDemoMode(showToastMsg) {
        state.demoMode = true;
        state.googleConnected = true;
        saveDemoPref(true);
        if (!state.locationId && MOCK.locations[0]) state.locationId = MOCK.locations[0].id;
        fillLocationSelect();
        updateChrome();
        renderAllPanels();
        if (showToastMsg !== false) {
            showToast("Đã bật dữ liệu mẫu. Kết nối Google Business Profile để dùng dữ liệu thật.");
        }
    }

    async function startGbpOAuth() {
        state.demoMode = false;
        saveDemoPref(false);
        updateDemoBadge();

        if (!authToken()) {
            promptLoginForGbp();
            return;
        }
        if (state.gbpStatus && state.gbpStatus.configured === false) {
            showToast("Server chưa cấu hình Google API — liên hệ quản trị viên.");
            return;
        }

        showToast("Đang chuyển tới Google để cấp quyền…");
        try {
            var res = await apiFetch("/oauth/start", { method: "POST", json: true });
            if (res.auth_url) {
                window.location.assign(res.auth_url);
                return;
            }
        } catch (e) {
            if (e && e.status === 401) {
                promptLoginForGbp();
                return;
            }
            if (e && e.status === 503) {
                showToast((e && e.message) || "Chưa cấu hình Google API trên server.");
                return;
            }
        }
        window.location.assign(API + "/oauth/redirect");
    }

    async function syncGbpNow(showOkToast) {
        if (state.demoMode) {
            renderAllPanels();
            showToast("Đã làm mới dữ liệu mẫu.");
            return;
        }
        if (!authToken()) {
            showToast("Vui lòng đăng nhập để đồng bộ.");
            return;
        }
        if (isSyncBlocked()) {
            showToast("Google API đang cooldown — thử lại sau " + formatCooldown(cooldownSecondsLeft()) + ".");
            renderOverview();
            return;
        }
        if (state.syncing) {
            showToast("Đang đồng bộ — vui lòng đợi.");
            return;
        }
        var prevLocations = (state.locations || []).slice();
        state.syncing = true;
        updateChrome();
        renderOverview();
        try {
            var syncRes = await apiFetch("/sync", { method: "POST", json: true });
            var data = syncRes.data || {};
            if (data.api_quota_limited) {
                applyCooldownFromStatus(data);
                if (data.rate_limit_until) applyCooldownFromStatus({ rate_limit_until: data.rate_limit_until, retry_after_seconds: data.retry_after_seconds });
                state.lastGbpError = null;
                showToast(data.message || gbpErrorMessage("api_quota"));
            } else if (data.already_syncing) {
                showToast(data.message || "Đang đồng bộ — vui lòng đợi.");
                return;
            }
            var statusRes = await apiFetch("/status");
            state.gbpStatus = statusRes.data || state.gbpStatus || {};
            applyCooldownFromStatus(state.gbpStatus);
            var locRes = await apiFetch("/locations");
            var newLocs = locRes.data || [];
            if (newLocs.length) {
                state.locations = newLocs;
            } else {
                state.locations = prevLocations;
            }
            if (state.locations.length && !state.locations.some(function (l) { return l.id === state.locationId; })) {
                state.locationId = state.locations[0].id;
            }
            state.googleConnected = !!(state.gbpStatus && state.gbpStatus.connected);
            fillLocationSelect();
            renderAllPanels();
            if (showOkToast !== false && data.synced_locations > 0) {
                showToast(data.message || "Đã đồng bộ địa điểm từ Google Business Profile.");
            } else if (showOkToast !== false && !data.api_quota_limited && !data.errors.length) {
                showToast(data.message || "Đồng bộ hoàn tất.");
            }
        } catch (e) {
            state.locations = prevLocations;
            showToast((e && e.message) || "Đồng bộ thất bại.");
            try {
                var stRes = await apiFetch("/status");
                state.gbpStatus = stRes.data || state.gbpStatus;
                applyCooldownFromStatus(state.gbpStatus);
            } catch (_e2) {}
            renderAllPanels();
        } finally {
            state.syncing = false;
            updateChrome();
        }
    }

    async function refreshGbpData() {
        return syncGbpNow(true);
    }

    var _loadGbpInFlight = null;

    async function loadGbpFromApi() {
        if (_loadGbpInFlight) return _loadGbpInFlight;
        _loadGbpInFlight = (async function () {
        if (!authToken()) {
            if (readDemoPref()) enableDemoMode(false);
            else {
                state.googleConnected = false;
                state.demoMode = false;
                state.locations = [];
            }
            return;
        }
        try {
            var statusRes = await apiFetch("/status");
            state.gbpStatus = statusRes.data || {};
            if (readDemoPref() && !state.gbpStatus.connected) {
                enableDemoMode(false);
                return;
            }
            state.demoMode = false;
            saveDemoPref(false);
            state.cooldownUntil = readCooldownUntil();
            if (state.gbpStatus.connected) {
                var locRes = await apiFetch("/locations");
                state.locations = locRes.data || [];
                state.googleConnected = true;
                if (state.locations.length && !state.locations.some(function (l) { return l.id === state.locationId; })) {
                    state.locationId = state.locations[0].id;
                }
                applyCooldownFromStatus(state.gbpStatus);
                if (
                    state.gbpStatus.api_quota_limited ||
                    state.gbpStatus.connection_state === "rate_limited" ||
                    state.gbpStatus.sync_status === "rate_limited"
                ) {
                    startCooldownTicker();
                }
            } else {
                state.locations = [];
                state.googleConnected = false;
            }
        } catch (e) {
            state.gbpStatus = state.gbpStatus || { configured: false, connected: false };
            if (readDemoPref()) enableDemoMode(false);
            else if ((state.locations || []).length) {
                state.googleConnected = true;
            } else {
                state.googleConnected = false;
                state.demoMode = false;
                state.locations = [];
            }
        }
        })();
        try {
            return await _loadGbpInFlight;
        } finally {
            _loadGbpInFlight = null;
        }
    }

    function connectGoogle(mockOnly) {
        if (mockOnly) {
            enableDemoMode(true);
            return;
        }
        startGbpOAuth();
    }

    function onConnectClick() {
        startGbpOAuth();
    }

    function mapCheckApi() {
        return window.GmsMapCheck || null;
    }

    function getDisplayScore(loc) {
        if (!loc) return null;
        var api = mapCheckApi();
        if (api) {
            var last = api.getLastCheck(loc.id);
            if (last) return last.totalScore;
            var ev = api.evaluateLocation(loc);
            if (ev && ev.ok && ev.totalScore != null) return ev.totalScore;
        }
        return loc.mapScore != null ? loc.mapScore : null;
    }

    function formatCheckDate(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
        } catch (_e) {
            return iso;
        }
    }

    function sevBadge(severity) {
        if (severity === "critical") return '<span class="gms-sev gms-sev--critical">Critical</span>';
        if (severity === "warning") return '<span class="gms-sev gms-sev--warning">Warning</span>';
        return '<span class="gms-sev gms-sev--opportunity">Opportunity</span>';
    }

    function runMapCheck(saveHistory) {
        var loc = currentLocation();
        var api = mapCheckApi();
        if (!api) {
            showToast("Module Check Map chưa tải.");
            return null;
        }
        var result = api.evaluateLocation(loc);
        if (!result.ok || result.totalScore == null) {
            showToast(result.message || "Chưa đủ dữ liệu để chấm điểm.");
            return result;
        }
        if (saveHistory !== false) api.saveCheckResult(result);
        loc.mapScore = result.totalScore;
        return result;
    }

    function getActiveCheckResult() {
        var loc = currentLocation();
        var api = mapCheckApi();
        if (!api) return null;
        var last = api.getLastCheck(loc.id);
        if (last) {
            return {
                ok: true,
                totalScore: last.totalScore,
                groups: last.groups,
                issues: last.issues,
                summary: last.summary,
                checkedAt: last.at,
                earned: last.earned,
                maxEarnable: last.maxEarnable,
                fromHistory: true,
            };
        }
        return api.evaluateLocation(loc);
    }

    function renderCheckMap() {
        var host = $("gmsPanelCheckMap");
        if (!host) return;

        if (!state.googleConnected) {
            host.innerHTML =
                '<div class="gms-empty gms-empty--compact">' +
                '<div class="gms-empty__icon" aria-hidden="true">🔍</div>' +
                "<h2>Check Map Score</h2>" +
                "<p>Kết nối Google Business Profile để chấm điểm tối ưu Map từ dữ liệu thật.</p>" +
                '<button type="button" class="gms-btn gms-btn--primary" id="gmsEmptyConnect">Kết nối Google Business Profile</button></div>';
            return;
        }

        var loc = currentLocation();
        var api = mapCheckApi();
        if (!api) {
            host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module Check Map…</p></div>';
            return;
        }

        if (!loc.gbp || loc.gbp.synced !== true) {
            host.innerHTML =
                '<div class="gms-card">' +
                '<h2 class="gms-card-title">Check Map Score</h2>' +
                '<p class="gms-hint gms-check-insufficient">Chưa đủ dữ liệu đồng bộ từ Google Business Profile để đánh giá.</p></div>';
            return;
        }

        var result = getActiveCheckResult();
        var history = api.getHistory(loc.id);
        var prev = history.length > 1 ? history[1] : null;
        var hasScore = result && result.ok && result.totalScore != null;
        var isPreview = hasScore && !history.length;

        var html = '<div class="gms-check-head">' +
            '<div><h2 class="gms-card-title" style="margin:0">Check Map Score</h2>' +
            '<p class="gms-hint">' + esc(loc.name) + " · chỉ chấm từ dữ liệu GBP đã đồng bộ</p></div>" +
            '<div class="gms-overview-actions">' +
            '<button type="button" class="gms-btn gms-btn--primary" id="gmsBtnRunCheck">Chạy Check Map Score</button>' +
            "</div></div>";

        if (!hasScore) {
            html += '<div class="gms-card gms-check-insufficient-box">' +
                '<p class="gms-check-insufficient">' + esc(result.message || "Chưa đủ dữ liệu để đánh giá") + "</p>" +
                '<p class="gms-hint">Bấm «Chạy Check Map Score» sau khi Google đồng bộ đủ trường hồ sơ.</p></div>';
            host.innerHTML = html;
            return;
        }

        var delta = prev ? result.totalScore - prev.totalScore : null;
        var deltaHtml = delta == null ? "" : '<span class="gms-check-delta gms-check-delta--' + (delta >= 0 ? "up" : "down") + '">' +
            (delta >= 0 ? "+" : "") + delta + " so với lần trước</span>";

        html += '<div class="gms-card gms-check-summary">' +
            '<div class="gms-score-wrap">' + scoreRing(result.totalScore) +
            "<div><p><strong>Map Score: " + result.totalScore + "/100</strong></p>" +
            '<p class="gms-hint">' + result.earned + "/" + result.maxEarnable + " điểm nhóm (chỉ tính nhóm đủ dữ liệu)</p>" +
            '<p class="gms-hint">Lần check: ' + formatCheckDate(result.checkedAt || (history[0] && history[0].at)) + " " + deltaHtml +
            (isPreview ? ' · <span class="gms-muted">Xem trước — bấm «Chạy Check» để lưu lịch sử</span>' : "") + "</p>" +
            '<p class="gms-hint">' +
            (result.summary.critical || 0) + " Critical · " +
            (result.summary.warning || 0) + " Warning · " +
            (result.summary.opportunity || 0) + " Opportunity</p></div></div></div>";

        html += '<div class="gms-card"><h3 class="gms-card-title">Điểm theo nhóm</h3><div class="gms-check-groups">';
        (result.groups || []).forEach(function (g) {
            var pct = g.sufficient && g.score != null ? Math.round((g.score / g.maxPoints) * 100) : null;
            html += '<div class="gms-check-group gms-check-group--' + (g.sufficient ? scoreLevel(pct || 0) : "na") + '">' +
                '<div class="gms-check-group__head"><span class="gms-check-group__label">' + esc(g.label) + "</span>" +
                (g.sufficient
                    ? '<strong class="gms-check-group__score">' + g.score + "/" + g.maxPoints + "</strong>"
                    : '<span class="gms-check-group__na">Chưa đủ dữ liệu để đánh giá</span>') +
                "</div>";
            if (g.sufficient && pct != null) {
                html += '<div class="gms-progress"><div class="gms-progress__bar" style="width:' + pct + '%"></div></div>';
            }
            html += "</div>";
        });
        html += "</div></div>";

        html += '<div class="gms-card"><h3 class="gms-card-title">Bảng vấn đề &amp; khuyến nghị</h3>';
        if (!(result.issues || []).length) {
            html += '<p class="gms-hint">Không phát hiện vấn đề từ dữ liệu hiện có. Tiếp tục duy trì hồ sơ.</p>';
        } else {
            html += '<div class="gms-table-wrap"><table class="gms-table gms-check-table"><thead><tr>' +
                "<th>Mức độ</th><th>Nhóm</th><th>Vấn đề</th><th>Nguyên nhân</th><th>Cách sửa</th><th></th></tr></thead><tbody>";
            (result.issues || []).forEach(function (iss) {
                html += "<tr><td>" + sevBadge(iss.severity) + "</td><td>" + esc(api.groupLabel(iss.groupId)) + "</td>" +
                    "<td><strong>" + esc(iss.title) + "</strong></td><td>" + esc(iss.cause) + "</td><td>" + esc(iss.fix) + "</td>" +
                    '<td><button type="button" class="gms-btn gms-btn--secondary gms-btn--xs" data-gms-ai-fix="' + iss.id + '"' +
                    (iss.aiFixable === false ? " disabled title=\"Cần thao tác thủ công\"" : "") + ">Sửa bằng AI</button></td></tr>";
            });
            html += "</tbody></table></div>";
        }
        html += "</div>";

        if (history.length) {
            html += '<div class="gms-card"><h3 class="gms-card-title">Lịch sử Check Map</h3>' +
                '<div class="gms-table-wrap"><table class="gms-table"><thead><tr>' +
                "<th>Thời gian</th><th>Map Score</th><th>Thay đổi</th><th>Critical</th><th>Warning</th><th>Opportunity</th></tr></thead><tbody>";
            history.forEach(function (h, idx) {
                var prevH = history[idx + 1];
                var d = prevH ? h.totalScore - prevH.totalScore : null;
                var dTxt = d == null ? "—" : (d >= 0 ? "+" : "") + d;
                html += "<tr><td>" + formatCheckDate(h.at) + "</td><td><strong>" + h.totalScore + "</strong></td><td>" + dTxt + "</td>" +
                    "<td>" + ((h.summary && h.summary.critical) || 0) + "</td>" +
                    "<td>" + ((h.summary && h.summary.warning) || 0) + "</td>" +
                    "<td>" + ((h.summary && h.summary.opportunity) || 0) + "</td></tr>";
            });
            html += "</tbody></table></div></div>";
        }

        host.innerHTML = html;
    }

    function renderProfile() {
        var host = $("gmsPanelProfile");
        if (!host) return;
        if (!state.googleConnected) {
            host.innerHTML =
                '<div class="gms-empty gms-empty--sm">' +
                "<h2>Chưa có địa điểm</h2>" +
                "<p>Kết nối Google Business Profile hoặc xem dữ liệu mẫu để tối ưu hồ sơ bằng AI.</p></div>";
            return;
        }
        var loc = currentLocation();
        if (window.GmsProfile && typeof window.GmsProfile.mount === "function") {
            window.GmsProfile.resetSection();
            window.GmsProfile.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module tối ưu hồ sơ…</p></div>';
    }

    function renderReview() {
        var host = $("gmsPanelReview");
        if (!host) return;
        if (!state.googleConnected) {
            host.innerHTML =
                '<div class="gms-empty gms-empty--sm">' +
                "<h2>Chưa có địa điểm</h2>" +
                "<p>Kết nối Google Business Profile hoặc xem dữ liệu mẫu để quản lý review.</p></div>";
            return;
        }
        var loc = currentLocation();
        if (window.GmsReviews && typeof window.GmsReviews.mount === "function") {
            window.GmsReviews.reset();
            window.GmsReviews.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module review…</p></div>';
    }

    function renderPosts() {
        var host = $("gmsPanelPosts");
        if (!host) return;
        var loc = currentLocation();
        if (window.GmsPosts && typeof window.GmsPosts.mount === "function") {
            window.GmsPosts.reset();
            window.GmsPosts.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module bài đăng…</p></div>';
    }

    function renderMedia() {
        var host = $("gmsPanelMedia");
        if (!host) return;
        var loc = currentLocation();
        if (window.GmsMedia && typeof window.GmsMedia.mount === "function") {
            window.GmsMedia.reset();
            window.GmsMedia.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module ảnh & media…</p></div>';
    }

    function renderVerification() {
        var host = $("gmsPanelVerification");
        if (!host) return;
        var loc = currentLocation();
        if (window.GmsVerification && typeof window.GmsVerification.mount === "function") {
            window.GmsVerification.reset();
            window.GmsVerification.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải trợ lý xác minh…</p></div>';
    }

    function renderCompetitors() {
        var host = $("gmsPanelCompetitors");
        if (!host) return;
        var loc = currentLocation();
        if (window.GmsCompetitors && typeof window.GmsCompetitors.mount === "function") {
            window.GmsCompetitors.reset();
            window.GmsCompetitors.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
                demoMode: state.demoMode,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module đối thủ…</p></div>';
    }

    function renderReports() {
        var host = $("gmsPanelReports");
        if (!host) return;
        var loc = currentLocation();
        if (window.GmsReports && typeof window.GmsReports.mount === "function") {
            window.GmsReports.reset();
            window.GmsReports.mount(host, {
                location: loc,
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
                demoMode: state.demoMode,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải module báo cáo…</p></div>';
    }

    function renderLeadScanner() {
        var host = $("gmsPanelLeadScanner");
        if (!host) return;
        if (window.GmsLeads && typeof window.GmsLeads.mount === "function") {
            window.GmsLeads.reset();
            window.GmsLeads.mount(host, {
                esc: esc,
                showToast: showToast,
                authToken: authToken,
                apiFetch: apiFetch,
            });
            return;
        }
        host.innerHTML = '<div class="gms-card"><p class="gms-hint">Đang tải Lead Map Scanner…</p></div>';
    }

    function renderAllPanels() {
        try {
            updateChrome();
            renderStats();
            renderOverview();
            renderLeadScanner();
            if (!state.googleConnected) return;
            renderCheckMap();
            renderProfile();
            renderReview();
            renderPosts();
            renderMedia();
            renderVerification();
            renderCompetitors();
            renderReports();
        } catch (err) {
            console.error("GMS render error", err);
        }
    }

    function fillLocationSelect() {
        var sel = $("gmsLocationSelect");
        if (!sel) return;
        if (!state.googleConnected) {
            sel.innerHTML = "";
            return;
        }
        sel.innerHTML = activeLocations().map(function (l) {
            return '<option value="' + esc(l.id) + '"' + (l.id === state.locationId ? " selected" : "") + ">" +
                esc(l.name) + "</option>";
        }).join("");
    }

    function setTab(tab) {
        state.tab = tab;
        document.querySelectorAll("[data-gms-tab]").forEach(function (btn) {
            var on = btn.getAttribute("data-gms-tab") === tab;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll("[data-gms-panel]").forEach(function (panel) {
            var on = panel.getAttribute("data-gms-panel") === tab;
            panel.classList.toggle("active", on);
            panel.hidden = !on;
        });
        try {
            var url = new URL(window.location.href);
            if (tab === "overview") url.searchParams.delete("tab");
            else url.searchParams.set("tab", tab);
            window.history.replaceState({}, "", url.pathname + url.search);
        } catch (_e) {}
    }

    function bindUi() {
        document.querySelectorAll("[data-gms-tab]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                setTab(btn.getAttribute("data-gms-tab"));
            });
        });

        document.addEventListener("click", function (e) {
            var goto = e.target && e.target.closest ? e.target.closest("[data-gms-goto]") : null;
            if (goto) setTab(goto.getAttribute("data-gms-goto"));

            var action = e.target && e.target.closest ? e.target.closest("[data-gms-action]") : null;
            if (action) {
                var locId = action.getAttribute("data-gms-loc");
                var act = action.getAttribute("data-gms-action");
                if (locId) selectLocation(locId);
                if (act === "check-map") setTab("check-map");
                else if (act === "profile") setTab("profile");
                else if (act === "reports") setTab("reports");
                renderAllPanels();
            }

            if (e.target && e.target.id === "gmsEmptyConnect") {
                connectGoogle(false);
            }
            if (e.target && e.target.id === "gmsEmptyDemo") {
                connectGoogle(true);
            }
            if (e.target && e.target.id === "gmsPendingSync") {
                syncGbpNow(true);
            }
            if (e.target && e.target.id === "gmsBannerRetrySync") {
                syncGbpNow(true);
            }
            if (e.target && e.target.id === "gmsPendingReconnect") {
                startGbpOAuth();
            }
            if (e.target && e.target.id === "gmsOverviewConnect") {
                startGbpOAuth();
            }
            if (e.target && e.target.id === "gmsBtnRunCheck") {
                var r = runMapCheck(true);
                if (r && r.totalScore != null) {
                    showToast("Map Score: " + r.totalScore + "/100 — đã lưu lịch sử.");
                    renderAllPanels();
                }
            }
            var aiBtn = e.target && e.target.closest ? e.target.closest("[data-gms-ai-fix]") : null;
            if (aiBtn && !aiBtn.disabled) {
                showToast("Sửa bằng AI — sẽ kết nối Content AI / GBP ở bước tiếp theo.");
            }
        });

        var sel = $("gmsLocationSelect");
        if (sel) {
            sel.addEventListener("change", function () {
                state.locationId = sel.value;
                renderAllPanels();
                showToast(state.demoMode ? "Đã chuyển địa điểm (dữ liệu mẫu)." : "Đã chuyển địa điểm.");
            });
        }

        var refresh = $("gmsBtnRefresh");
        if (refresh) {
            refresh.addEventListener("click", function () {
                if (isSyncBlocked()) {
                    showToast("Google API đang cooldown — thử lại sau " + formatCooldown(cooldownSecondsLeft()) + ".");
                    return;
                }
                syncGbpNow(true);
            });
        }

        var connect = $("gmsBtnConnect");
        if (connect) {
            connect.addEventListener("click", onConnectClick);
        }

        window.addEventListener("digiseo-auth-change", function (ev) {
            if (!ev || !ev.detail || !ev.detail.loggedIn) return;
            loadGbpFromApi().then(function () {
                fillLocationSelect();
                renderAllPanels();
            });
        });
    }

    function handleGbpQueryParams() {
        try {
            var q = new URLSearchParams(window.location.search || "");
            var gbp = q.get("gbp");
            var err = q.get("gbp_error");
            var changed = false;
            if (gbp === "connected") {
                showToast("Đã kết nối Google Business Profile — đang tải địa điểm…");
                changed = true;
            }
            var syncPending = q.get("gbp_sync");
            if (syncPending === "pending") {
                state.lastGbpError = null;
                changed = true;
            }
            if (err) {
                state.lastGbpError = err;
                showToast(gbpErrorMessage(err));
                renderApiBanner();
                changed = true;
            }
            if (changed) {
                q.delete("gbp");
                q.delete("gbp_error");
                q.delete("gbp_sync");
                var qs = q.toString();
                window.history.replaceState({}, "", window.location.pathname + (qs ? "?" + qs : ""));
            }
        } catch (_e) {}
    }

    function initFromQuery() {
        try {
            var q = new URLSearchParams(window.location.search || "");
            var tab = q.get("tab");
            if (tab && document.querySelector('[data-gms-tab="' + tab + '"]')) {
                setTab(tab);
            }
        } catch (_e) {}
    }

    async function init() {
        migrateLegacyPrefs();
        handleGbpQueryParams();
        bindUi();
        initFromQuery();
        await loadGbpFromApi();
        fillLocationSelect();
        renderAllPanels();
        setTab(state.tab);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
