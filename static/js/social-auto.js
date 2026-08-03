/**
 * Social Auto — Facebook Fanpage MVP (OAuth + safety).
 */
(function () {
    "use strict";

    const API = "/api/social";
    const API_WEB20 = "/api/social/web20";
    const state = {
        campaignId: "",
        currentPost: null,
        campaigns: [],
        stats: {},
        fb: { pages: [], active_page: null, mock_mode: true, safety: {} },
        web20: {
            accounts: [],
            posts: [],
            platforms: [],
            settings: {},
            currentPostId: null,
            platform: "wordpress_2_0",
            manualPackage: null,
            editorTab: "source",
            lastSafety: null,
        },
        compose: {
            selected: {},
            accountMap: {},
            activeChannel: null,
            variants: {},
            lastSafety: null,
        },
    };

    let toastTimer = null;

    function $(id) { return document.getElementById(id); }

    function readCookieToken() {
        const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    }

    function getAuthToken() {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (!t) { t = readCookieToken(); if (t) sessionStorage.setItem("seo_token", t); }
            return t;
        } catch (_) { return readCookieToken(); }
    }

    async function api(method, path, body) {
        const opts = {
            method: method,
            credentials: "same-origin",
            headers: Object.assign({}, body ? { "Content-Type": "application/json" } : {}),
        };
        const t = getAuthToken();
        if (t) opts.headers.Authorization = "Bearer " + t;
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(API + path, opts);
        const data = await res.json().catch(function () { return {}; });
        if (res.status === 401) {
            showToast("Vui lòng đăng nhập.");
            if (window.DigiSeoOpenLoginModal) window.DigiSeoOpenLoginModal();
            throw new Error("unauthorized");
        }
        if (!res.ok) {
            const msg = typeof data.detail === "object" ? (data.detail.message || JSON.stringify(data.detail)) : (data.detail || "Lỗi API");
            const err = new Error(msg);
            err.data = data;
            err.status = res.status;
            throw err;
        }
        return data;
    }

    async function apiWeb20(method, path, body) {
        const opts = {
            method: method,
            credentials: "same-origin",
            headers: Object.assign({}, body ? { "Content-Type": "application/json" } : {}),
        };
        const t = getAuthToken();
        if (t) opts.headers.Authorization = "Bearer " + t;
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(API_WEB20 + path, opts);
        const data = await res.json().catch(function () { return {}; });
        if (res.status === 401) {
            showToast("Vui lòng đăng nhập.");
            if (window.DigiSeoOpenLoginModal) window.DigiSeoOpenLoginModal();
            throw new Error("unauthorized");
        }
        if (!res.ok) {
            let msg = data.detail;
            if (typeof msg === "object") msg = msg.message || JSON.stringify(msg);
            if (!msg) msg = "Lỗi API Web 2.0";
            throw new Error(msg);
        }
        return data;
    }

    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function showToast(msg) {
        const el = $("saToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        el.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            el.classList.remove("is-visible");
            setTimeout(function () { el.hidden = true; }, 280);
        }, 3600);
    }

    const TAB_CACHE_MS = 30000;
    const tabFetchAt = {};
    const tabDirty = {};

    function invalidateSaTabs(keys) {
        (keys || Object.keys(tabFetchAt)).forEach(function (k) {
            tabDirty[k] = true;
            delete tabFetchAt[k];
        });
    }

    function saTabFresh(tab, maxAge) {
        if (tabDirty[tab]) return false;
        const at = tabFetchAt[tab];
        return !!at && (Date.now() - at) < (maxAge || TAB_CACHE_MS);
    }

    function markSaTabFetched(tab) {
        tabDirty[tab] = false;
        tabFetchAt[tab] = Date.now();
    }

    function refreshOverviewUi() {
        renderStats();
        renderCampaignSelect();
        renderCampaignList();
        renderPageSelects();
        renderFbPages();
        applySafetySettings(state.fb.safety || {});
    }

    const SA_TAB_IDS = ["overview", "campaigns", "compose", "schedule", "results", "safety"];

    function readTabFromLocation() {
        const hash = (window.location.hash || "").replace(/^#/, "");
        const m = hash.match(/^tab=([a-z]+)$/);
        if (m && SA_TAB_IDS.indexOf(m[1]) >= 0) return m[1];
        return "";
    }

    function writeTabToLocation(tab) {
        const nextHash = "#tab=" + tab;
        if (window.location.hash === nextHash) return;
        try {
            history.replaceState({}, "", window.location.pathname + window.location.search + nextHash);
        } catch (_) {}
    }

    function switchTab(tab, opts) {
        opts = opts || {};
        document.querySelectorAll(".sa-tab").forEach(function (btn) {
            const on = btn.getAttribute("data-sa-tab") === tab;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll(".sa-panel").forEach(function (p) {
            const on = p.getAttribute("data-sa-panel") === tab;
            p.classList.toggle("active", on);
            p.hidden = !on;
        });
        if (!opts.skipHash) writeTabToLocation(tab);
        if (opts.skipFetch || !getAuthToken()) return;
        if (tab === "schedule") {
            if (saTabFresh("schedule")) return;
            loadSchedule().then(function () { markSaTabFetched("schedule"); }).catch(function () {});
            return;
        }
        if (tab === "results") {
            if (saTabFresh("results")) return;
            loadResults().then(function () { markSaTabFetched("results"); }).catch(function () {});
            return;
        }
        if (tab === "safety") {
            if (saTabFresh("safety")) return;
            loadSafetyTab().then(function () { markSaTabFetched("safety"); }).catch(function () {});
            return;
        }
        if (tab === "overview") {
            if (saTabFresh("overview")) {
                refreshOverviewUi();
                return;
            }
            loadOverview().then(function () { markSaTabFetched("overview"); }).catch(function () {});
            return;
        }
        if (tab === "campaigns") {
            renderCampaignsFullList();
            return;
        }
        if (tab === "compose") {
            if (saTabFresh("compose")) {
                renderComposeChannelCards();
                renderComposeVariantsAccordion();
                syncComposeSourceToWeb20();
                updateComposeStepper();
                return;
            }
            loadComposeTab().catch(function (e) { if (e.message !== "unauthorized") showToast(e.message); });
        }
    }

    function formatDt(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
        } catch (_) { return iso; }
    }

    function statusBadge(st) {
        const m = {
            draft: "Nháp", approved: "Đã duyệt", scheduled: "Scheduled", published: "Published",
            failed: "Failed", cancelled: "Cancelled", retrying: "Retrying", publishing: "Publishing",
            manual: "Manual", ready: "Ready",
        };
        const c = {
            published: "published", failed: "failed", scheduled: "scheduled", cancelled: "cancelled",
            retrying: "retrying", publishing: "publishing", manual: "manual",
        };
        const key = String(st || "draft").toLowerCase();
        return '<span class="sa-badge sa-badge--' + (c[key] || "scheduled") + '">' + esc(m[key] || st) + "</span>";
    }

    function todayKey() {
        return new Date().toDateString();
    }

    function countPostsTodayForChannel(ch) {
        const tk = todayKey();
        if (ch.type === "facebook") {
            const pageId = state.compose.accountMap[ch.id];
            if (!pageId) return 0;
            return (state.fbPostsToday || []).filter(function (p) {
                return String(p.page_id) === String(pageId);
            }).length;
        }
        const accId = state.compose.accountMap[ch.id];
        if (!accId) return 0;
        return (state.web20.posts || []).filter(function (p) {
            if (String(p.account_id) !== String(accId)) return false;
            if (["published", "ready", "manual", "scheduled", "publishing"].indexOf(String(p.status)) < 0) return false;
            const at = p.published_at || p.updated_at || p.scheduled_at;
            return at && new Date(at).toDateString() === tk;
        }).length;
    }

    function safetyLimitForChannel(ch) {
        if (ch.type === "facebook") {
            return (state.fb.safety && state.fb.safety.max_posts_per_day) || 4;
        }
        return (state.web20.settings && state.web20.settings.max_posts_per_account_per_day) || 3;
    }

    function accountLabelForChannel(ch) {
        if (ch.type === "facebook") {
            const pid = state.compose.accountMap[ch.id];
            const page = (state.fb.pages || []).find(function (p) { return p.page_id === pid; });
            return page ? page.page_name : "Chưa chọn Fanpage";
        }
        const accId = state.compose.accountMap[ch.id];
        const acc = (state.web20.accounts || []).find(function (a) { return a.id === accId; });
        return acc ? (acc.label || acc.site_url || acc.platform) : "Chưa chọn tài khoản";
    }

    function formPayload() {
        return {
            campaign_id: state.campaignId || null,
            name: ($("saCampaignName") && $("saCampaignName").value.trim()) || "",
            source_title: ($("saTitle") && $("saTitle").value.trim()) || "",
            source_content: ($("saSourceContent") && $("saSourceContent").value.trim()) || "",
            keyword: ($("saKeyword") && $("saKeyword").value.trim()) || "",
            target_url: ($("saUrl") && $("saUrl").value.trim()) || "",
            tone: ($("saTone") && $("saTone").value) || "chuyên gia",
            cta: ($("saCta") && $("saCta").value.trim()) || "",
        };
    }

    function variantFromForm() {
        return {
            title: ($("saFbTitle") && $("saFbTitle").value.trim()) || "",
            content: ($("saFbContent") && $("saFbContent").value.trim()) || "",
            hashtags: ($("saFbHashtags") && $("saFbHashtags").value.trim()) || "",
            cta: ($("saFbCta") && $("saFbCta").value.trim()) || "",
        };
    }

    function fillVariantForm(post) {
        state.currentPost = post || null;
        if ($("saFbTitle")) $("saFbTitle").value = (post && post.title) || "";
        if ($("saFbContent")) $("saFbContent").value = (post && post.content) || "";
        if ($("saFbHashtags")) $("saFbHashtags").value = (post && post.hashtags) || "";
        if ($("saFbCta")) $("saFbCta").value = (post && post.cta) || "";
        if ($("saPostStatus")) $("saPostStatus").innerHTML = post ? statusBadge(post.status) : "";
    }

    function renderStats() {
        const s = state.stats || {};
        const map = {
            saStatCampaigns: s.campaigns,
            saStatDrafts: s.drafts,
            saStatScheduled: s.scheduled,
            saStatPublished: s.published,
            saStatFailed: s.failed,
            saStatPages: (state.fb.pages || []).length,
        };
        Object.keys(map).forEach(function (id) {
            const el = $(id);
            if (el) el.textContent = String(map[id] != null ? map[id] : 0);
        });
        const badge = $("saModeBadge");
        if (badge) badge.textContent = state.fb.mock_mode ? "Demo" : "Social Auto";
        const hint = $("saLimitHint");
        const saf = state.fb.safety || {};
        if (hint) {
            hint.textContent = "Tối đa " + (saf.max_posts_per_day || 4) + " bài/ngày · cách nhau " +
                (saf.min_hours_between_posts || 3) + " giờ · không trùng 100% · không đa Page cùng lúc.";
        }
    }

    function renderCampaignSelect() {
        const sel = $("saCampaignSelect");
        if (!sel) return;
        sel.innerHTML = '<option value="">— Chiến dịch mới —</option>' +
            state.campaigns.map(function (c) {
                return '<option value="' + esc(c.id) + '">' + esc(c.name || c.source_title) + "</option>";
            }).join("");
        sel.value = state.campaignId || "";
    }

    function renderCampaignList() {
        const box = $("saCampaignList");
        if (!box) return;
        if (!state.campaigns.length) {
            box.innerHTML = '<p class="sa-empty">Chưa có chiến dịch.</p>';
            return;
        }
        box.innerHTML = state.campaigns.slice(0, 8).map(function (c) {
            return '<button type="button" class="sa-mini-item" data-sa-load-campaign="' + esc(c.id) + '">' +
                "<strong>" + esc(c.name || c.source_title) + "</strong><span>" + esc(c.keyword || "") + "</span></button>";
        }).join("");
        renderCampaignsFullList();
    }

    function renderCampaignsFullList() {
        const box = $("saCampaignsFullList");
        if (!box) return;
        if (!state.campaigns.length) {
            box.innerHTML = '<p class="sa-empty">Chưa có chiến dịch.</p>';
            return;
        }
        box.innerHTML = state.campaigns.map(function (c) {
            return '<button type="button" class="sa-campaign-card" data-sa-load-campaign="' + esc(c.id) + '">' +
                "<strong>" + esc(c.name || c.source_title || "Chiến dịch") + "</strong>" +
                "<span>" + esc(c.keyword || "") + (c.target_url ? " · " + esc(c.target_url) : "") + "</span></button>";
        }).join("");
    }

    function renderPageSelects() {
        const pages = state.fb.pages || [];
        const active = state.fb.active_page;
        ["saActivePage"].forEach(function (id) {
            const sel = $(id);
            if (!sel) return;
            sel.innerHTML = '<option value="">— Chọn Fanpage —</option>' +
                pages.map(function (p) {
                    return '<option value="' + esc(p.page_id) + '">' + esc(p.page_name) + "</option>";
                }).join("");
            if (active) sel.value = active.page_id || "";
        });
    }

    function renderFbPages() {
        const box = $("saFbPagesList");
        if (!box) return;
        const pages = state.fb.pages || [];
        if (!pages.length) {
            box.innerHTML = '<div class="sa-fb-empty">' +
                '<p class="sa-empty">Chưa kết nối Fanpage Facebook.</p>' +
                facebookConnectButtonHtml("sa-btn--sm") +
                "</div>";
            renderFbConnectionBanner();
            return;
        }
        box.innerHTML = pages.map(function (p) {
            const st = p.status === "connected" ? "connected" : (p.status === "error" ? "error" : "disconnected");
            const active = p.is_active ? " · đang dùng" : "";
            return '<article class="sa-channel">' +
                '<div class="sa-channel-ico">📘</div>' +
                '<div class="sa-channel-info"><div class="sa-channel-name">' + esc(p.page_name) + active + '</div>' +
                '<div class="sa-channel-meta">' + esc(p.page_id) + "</div></div>" +
                '<span class="sa-status sa-status--' + st + '">● ' + esc(p.status || "connected") + "</span>" +
                '<div class="sa-channel-actions">' +
                (p.is_active ? "" : '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="activate-page" data-page-id="' + esc(p.page_id) + '">Chọn</button>') +
                '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="disconnect-page" data-page-id="' + esc(p.page_id) + '">Ngắt</button>' +
                "</div></article>";
        }).join("");
        renderFbConnectionBanner();
    }

    function renderSafetyInline(safety) {
        const box = $("saSafetyInline");
        if (!box) return;
        if (!safety || !safety.checks) { box.hidden = true; return; }
        const bad = safety.errors || [];
        const warn = safety.warnings || [];
        if (!bad.length && !warn.length) { box.hidden = true; return; }
        box.hidden = false;
        box.innerHTML = (bad.concat(warn)).map(function (c) {
            return '<div class="sa-safety-chip sa-safety-chip--' + esc(c.level) + '">' + esc(c.message) + "</div>";
        }).join("");
    }

    function renderSafetyChecks(safety) {
        const ul = $("saSafetyChecks");
        if (!ul) return;
        if (!safety || !safety.checks) {
            ul.innerHTML = '<li class="sa-empty">Chưa chạy kiểm tra.</li>';
            return;
        }
        ul.innerHTML = safety.checks.map(function (c) {
            return '<li class="sa-safety-row sa-safety-row--' + esc(c.level) + '"><strong>' + esc(c.code) + "</strong> " + esc(c.message) + "</li>";
        }).join("");
    }

    function renderApiLogs(items) {
        const box = $("saApiLogs");
        if (!box) return;
        if (!items || !items.length) {
            box.innerHTML = '<p class="sa-empty">Chưa có log.</p>';
            return;
        }
        box.innerHTML = items.map(function (l) {
            return '<div class="sa-log-item sa-log-item--' + esc(l.level) + '">' +
                "<time>" + esc(formatDt(l.created_at)) + "</time> " +
                "<code>" + esc(l.code) + "</code> " + esc(l.message) + "</div>";
        }).join("");
    }

    function applySafetySettings(s) {
        if ($("saMaxPerDay")) $("saMaxPerDay").value = s.max_posts_per_day || 4;
        if ($("saMinGap")) $("saMinGap").value = s.min_hours_between_posts || 3;
        if ($("saAutoRate")) $("saAutoRate").checked = s.auto_stop_on_rate_limit !== false;
        if ($("saAutoPerm")) $("saAutoPerm").checked = s.auto_stop_on_permission_error !== false;
        const hint = $("saPauseHint");
        if (hint) {
            if (s.is_paused) {
                hint.hidden = false;
                hint.textContent = "⏸ Tạm dừng: " + (s.pause_reason || "Lỗi API");
                hint.className = "sa-hint sa-hint--danger";
            } else {
                hint.hidden = true;
            }
        }
    }

    async function loadOverview() {
        const data = await api("GET", "/campaigns");
        state.campaigns = data.items || [];
        state.stats = data.stats || {};
        if (data.facebook) state.fb = Object.assign(state.fb, data.facebook);
        renderStats();
        renderCampaignSelect();
        renderCampaignList();
        renderPageSelects();
        renderFbPages();
        applySafetySettings(state.fb.safety || {});
    }

    async function loadCampaignPost(campaignId) {
        if (!campaignId) { fillVariantForm(null); return; }
        const data = await api("GET", "/posts?campaign_id=" + encodeURIComponent(campaignId) + "&platform=facebook");
        const posts = (data.items || []).filter(function (p) {
            return ["draft", "approved"].indexOf(p.status) >= 0;
        });
        const post = posts[0] || null;
        fillVariantForm(post);
        if (post) {
            state.compose.selected.facebook = true;
            state.compose.accountMap.facebook = post.page_id || activePageId() || "";
            state.compose.variants.facebook = { type: "facebook", post: post, postId: post.id };
            state.compose.activeChannel = "facebook";
            renderComposeChannelCards();
            renderComposeVariantsAccordion();
        }
    }

    async function loadSchedule() {
        const box = $("saScheduleList");
        const channelFilter = ($("saScheduleFilter") && $("saScheduleFilter").value) || "all";
        const statusFilter = ($("saScheduleStatusFilter") && $("saScheduleStatusFilter").value) || "scheduled";
        if (!box) return;
        try {
            const [fbData, w20Data] = await Promise.all([
                api("GET", "/posts?platform=facebook"),
                apiWeb20("GET", "/posts"),
            ]);
            const statusGroups = {
                scheduled: ["scheduled"],
                published: ["published", "manual", "ready"],
                failed: ["failed", "retrying"],
                cancelled: ["cancelled"],
            };
            let items = (fbData.items || []).map(function (p) {
                return {
                    id: p.id, channel: "facebook", channelLabel: "Facebook",
                    title: p.title, dest: p.page_id || "Fanpage",
                    at: p.scheduled_at || p.published_at || p.updated_at,
                    status: p.status, kind: "facebook",
                    url: p.published_url, error: p.error_message || p.last_error,
                    retry_count: p.retry_count || 0,
                };
            }).concat((w20Data.items || []).map(function (p) {
                return {
                    id: p.id, channel: p.platform || "wordpress_2_0",
                    channelLabel: WEB20_PLATFORM_LABELS[p.platform] || p.platform,
                    title: p.title, dest: p.account_id || "—",
                    at: p.scheduled_at || p.published_at || p.updated_at,
                    status: p.status, kind: "web20",
                    url: p.published_url, error: p.error_message,
                    retry_count: p.retry_count || 0,
                };
            }));
            items = items.filter(function (x) {
                return ["draft", "approved", "publishing"].indexOf(String(x.status)) < 0;
            });
            if (statusFilter !== "all") {
                const allowed = statusGroups[statusFilter] || [statusFilter];
                items = items.filter(function (x) { return allowed.indexOf(String(x.status)) >= 0; });
            }
            if (channelFilter !== "all") items = items.filter(function (x) { return x.channel === channelFilter; });
            items.sort(function (a, b) { return String(b.at || "").localeCompare(String(a.at || "")); });
            if (!items.length) {
                box.innerHTML = '<p class="sa-empty">Không có bài phù hợp bộ lọc.</p>';
                return;
            }
            box.innerHTML = items.map(function (p) {
                const st = String(p.status);
                let actions = "";
                if (st === "scheduled") {
                    actions = '<button type="button" class="sa-btn sa-btn--success sa-btn--sm" data-sa-action="schedule-publish-now" data-kind="' + esc(p.kind) + '" data-post-id="' + esc(p.id) + '">Publish now</button>' +
                        '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="cancel-schedule-item" data-kind="' + esc(p.kind) + '" data-post-id="' + esc(p.id) + '">Cancel</button>';
                } else if (st === "failed" || st === "retrying") {
                    actions = (p.kind === "web20"
                        ? '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="schedule-retry" data-post-id="' + esc(p.id) + '">Retry</button>'
                        : "") +
                        '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="cancel-schedule-item" data-kind="' + esc(p.kind) + '" data-post-id="' + esc(p.id) + '">Cancel</button>';
                } else if (p.url) {
                    actions = '<a class="sa-btn sa-btn--ghost sa-btn--sm" href="' + esc(p.url) + '" target="_blank" rel="noopener">Xem bài</a>';
                }
                const errHtml = p.error ? '<div class="sa-schedule-error">' + esc(p.error) + "</div>" : "";
                return '<article class="sa-schedule-item">' +
                    '<div class="sa-schedule-main"><strong>' + esc(p.title || "(không tiêu đề)") + '</strong>' +
                    '<div class="sa-schedule-meta"><span>' + esc(p.channelLabel) + '</span>' +
                    "<span>🕐 " + esc(formatDt(p.at)) + "</span>" + statusBadge(p.status) +
                    (p.retry_count ? "<span>Retry " + esc(p.retry_count) + "</span>" : "") + "</div>" +
                    errHtml + "</div>" +
                    '<div class="sa-schedule-actions">' + actions + "</div></article>";
            }).join("");
        } catch (e) {
            if (e.message !== "unauthorized") box.innerHTML = '<p class="sa-empty">' + esc(e.message) + "</p>";
        }
    }

    async function loadResults() {
        const body = $("saResultsBody");
        const filter = ($("saResultsFilter") && $("saResultsFilter").value) || "all";
        if (!body) return;
        try {
            const [fbPub, fbFail, fbCancel, w20All] = await Promise.all([
                api("GET", "/posts?status=published&platform=facebook"),
                api("GET", "/posts?status=failed&platform=facebook"),
                api("GET", "/posts?platform=facebook"),
                apiWeb20("GET", "/posts"),
            ]);
            const fbCancelled = (fbCancel.items || []).filter(function (p) { return p.status === "cancelled"; });
            let items = (fbPub.items || []).concat(fbFail.items || []).concat(fbCancelled).map(function (p) {
                return {
                    id: p.id, channel: "facebook", channelLabel: "Facebook",
                    title: p.title, at: p.published_at || p.scheduled_at || p.updated_at,
                    status: p.status, url: p.published_url, kind: "facebook",
                    error: p.error_message || p.last_error, retry_count: p.retry_count || 0,
                };
            }).concat((w20All.items || []).filter(function (p) {
                return ["published", "failed", "manual", "cancelled", "retrying"].indexOf(p.status) >= 0;
            }).map(function (p) {
                return {
                    id: p.id, channel: p.platform || "wordpress_2_0",
                    channelLabel: WEB20_PLATFORM_LABELS[p.platform] || p.platform,
                    title: p.title, at: p.published_at || p.scheduled_at || p.updated_at,
                    status: p.status, url: p.published_url, kind: "web20",
                    error: p.error_message, retry_count: p.retry_count || 0,
                };
            }));
            if (filter !== "all") items = items.filter(function (x) { return x.channel === filter; });
            items.sort(function (a, b) { return String(b.at || "").localeCompare(String(a.at || "")); });
            if (!items.length) {
                body.innerHTML = '<tr><td colspan="7" class="sa-empty-cell">Chưa có kết quả.</td></tr>';
                return;
            }
            body.innerHTML = items.map(function (p) {
                const url = p.url
                    ? '<a class="sa-link" href="' + esc(p.url) + '" target="_blank" rel="noopener">Mở link</a>'
                    : "—";
                const badge = p.kind === "web20" ? web20StatusBadge(p.status) : statusBadge(p.status);
                let action = "—";
                if (p.status === "failed" || p.status === "retrying") {
                    action = p.kind === "web20"
                        ? '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="web20-retry-post" data-post-id="' + esc(p.id) + '">Retry</button>'
                        : "—";
                } else if (p.url) {
                    action = '<a class="sa-btn sa-btn--ghost sa-btn--sm" href="' + esc(p.url) + '" target="_blank" rel="noopener">Xem</a>';
                }
                return "<tr><td>" + esc(formatDt(p.at)) + "</td><td>" + esc(p.channelLabel) +
                    "</td><td>" + esc(p.title || "—") + "</td><td>" + badge +
                    "</td><td>" + url + "</td><td>" + esc(p.error || "—") +
                    "</td><td>" + action + "</td></tr>";
            }).join("");
        } catch (e) {
            if (e.message !== "unauthorized") {
                body.innerHTML = '<tr><td colspan="7" class="sa-empty-cell">' + esc(e.message) + "</td></tr>";
            }
        }
    }

    function isFbInvalidScopeError(text) {
        const s = String(text || "").toLowerCase();
        return s.indexOf("invalid scope") >= 0 || s.indexOf("invalid_scopes") >= 0
            || (s.indexOf("scope") >= 0 && s.indexOf("permission") >= 0);
    }

    async function loadSafetyTab() {
        const st = await api("GET", "/facebook/status");
        state.fb = Object.assign(state.fb, st);
        applySafetySettings(st.safety || {});
        const logs = await api("GET", "/safety/logs?limit=30");
        renderApiLogs(logs.items || []);
        try {
            const w20 = await apiWeb20("GET", "/settings");
            const ws = (w20 && w20.settings) || {};
            if ($("saW20MaxPerDay")) $("saW20MaxPerDay").value = ws.max_posts_per_account_per_day || 3;
            if ($("saW20DefaultStatus")) $("saW20DefaultStatus").value = ws.default_wp_status || "draft";
        } catch (_) { /* web20 settings optional */ }
    }

    async function connectFacebook() {
        if (!getAuthToken()) {
            showToast("Đăng nhập SEOAuto trước khi kết nối Fanpage.");
            return;
        }
        try {
            showToast("Đang mở Facebook OAuth…");
            const data = await api("GET", "/facebook/oauth/start");
            if (!data || !data.url) {
                showToast("Không tạo được liên kết OAuth Facebook.");
                return;
            }
            if (data.mode === "mock") {
                showToast(data.message || "Chế độ demo — kết nối giả lập.");
            }
            window.location.assign(data.url);
        } catch (e) {
            const detail = e.data && e.data.detail;
            const setup = detail && typeof detail === "object" ? detail.setup : null;
            if (e.status === 422 && detail && detail.code === "facebook_oauth_not_ready") {
                showFbInvalidScopeModal(setup);
                return;
            }
            const msg = String(e.message || e);
            if (isFbInvalidScopeError(msg)) {
                showFbInvalidScopeModal(null);
                return;
            }
            showToast(msg);
        }
    }

    function showFbInvalidScopeModal(setup) {
        setup = setup || (state.fb && state.fb.oauth_setup) || {};
        const steps = setup.steps || CONNECTION_GUIDES.facebook.steps;
        const dash = setup.dashboard_url || "https://developers.facebook.com/apps/";
        const perms = setup.permissions_url || dash;
        let host = document.getElementById("saFbOauthSetupModal");
        if (!host) {
            host = document.createElement("div");
            host.id = "saFbOauthSetupModal";
            host.className = "sa-fb-setup-modal";
            host.innerHTML =
                '<div class="sa-fb-setup-backdrop" data-sa-action="close-fb-setup"></div>' +
                '<div class="sa-fb-setup-card" role="dialog" aria-labelledby="saFbSetupTitle">' +
                '<h2 id="saFbSetupTitle" class="sa-card-title">Meta App chưa sẵn sàng — Invalid Scopes</h2>' +
                '<p class="sa-hint sa-fb-setup-lead">Facebook từ chối scope <strong>pages_show_list, pages_read_engagement, pages_manage_posts</strong> ' +
                "vì App Meta chưa được cấu hình quyền Pages. <strong>Không dán App ID</strong> — cần Configuration ID riêng.</p>" +
                '<ol class="sa-fb-setup-steps" id="saFbSetupSteps"></ol>' +
                '<p class="sa-hint">' +
                '<a id="saFbSetupDash" href="#" target="_blank" rel="noopener">Facebook Login for Business</a> · ' +
                '<a id="saFbSetupPerms" href="#" target="_blank" rel="noopener">Use cases / Permissions</a></p>' +
                '<div id="saFbSetupAdmin" class="sa-fb-setup-admin" hidden>' +
                '<label for="saFbConfigId">Configuration ID (admin — lưu ngay, không cần restart)</label>' +
                '<div class="sa-btn-row">' +
                '<input type="text" id="saFbConfigId" class="sa-input" placeholder="9876543210123456" inputmode="numeric" autocomplete="off">' +
                '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="save-fb-oauth-config">Lưu</button>' +
                "</div></div>" +
                '<div class="sa-btn-row sa-fb-setup-actions">' +
                '<button type="button" class="sa-btn sa-btn--primary" data-sa-action="connect-fb">Thử kết nối lại</button>' +
                '<button type="button" class="sa-btn sa-btn--ghost" data-sa-action="close-fb-setup">Đóng</button>' +
                "</div></div>";
            document.body.appendChild(host);
        }
        const ol = $("saFbSetupSteps");
        if (ol) {
            ol.innerHTML = steps.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("");
        }
        const dashEl = $("saFbSetupDash");
        if (dashEl) dashEl.href = dash;
        const permsEl = $("saFbSetupPerms");
        if (permsEl) permsEl.href = perms;
        const adminBox = $("saFbSetupAdmin");
        if (adminBox) {
            window.DigiSeoFetchAuthMe().then(function (me) {
                const isAdmin = typeof window.DigiSeoIsAdminUser === "function"
                    ? window.DigiSeoIsAdminUser(me)
                    : !!(me && (me.show_admin_nav || String(me.role || "").toLowerCase() === "admin"));
                adminBox.hidden = !isAdmin;
            }).catch(function () { adminBox.hidden = true; });
        }
        host.classList.add("is-open");
    }

    function closeFbOauthSetupModal() {
        const host = document.getElementById("saFbOauthSetupModal");
        if (host) host.classList.remove("is-open");
    }

    async function saveFbOauthConfig() {
        const val = ($("saFbConfigId") && $("saFbConfigId").value || "").trim();
        try {
            const data = await api("PUT", "/facebook/oauth/config", { login_config_id: val });
            if (data.setup) state.fb.oauth_setup = data.setup;
            showToast(data.message || "Đã lưu Configuration ID.");
            closeFbOauthSetupModal();
            await connectFacebook();
        } catch (e) {
            showToast(String(e.message || e));
        }
    }

    function promptDateTime() {
        const val = window.prompt("Thời gian đăng (YYYY-MM-DDTHH:MM):", "");
        if (!val) return null;
        const d = new Date(val);
        if (Number.isNaN(d.getTime())) { showToast("Định dạng thời gian không hợp lệ."); return null; }
        return d.toISOString();
    }

    function activePageId() {
        const sel = $("saActivePage");
        return (sel && sel.value) || (state.fb.active_page && state.fb.active_page.page_id) || "";
    }

    async function saveCurrentDraft() {
        if (!state.currentPost || !state.currentPost.id) {
            showToast("Chưa có bài — tạo biến thể AI trước.");
            return;
        }
        const v = variantFromForm();
        const data = await api("PATCH", "/posts/" + state.currentPost.id, Object.assign(v, { status: "draft", page_id: activePageId() || null }));
        state.currentPost = data.item;
        fillVariantForm(state.currentPost);
        showToast("Đã lưu nháp.");
        loadOverview();
    }

    async function approveCurrent() {
        if (!state.currentPost || !state.currentPost.id) return;
        const v = variantFromForm();
        const data = await api("PATCH", "/posts/" + state.currentPost.id, Object.assign(v, { status: "approved" }));
        state.currentPost = data.item;
        fillVariantForm(state.currentPost);
        showToast("Đã duyệt nội dung.");
    }

    async function previewCurrent() {
        const v = variantFromForm();
        const data = await api("POST", "/posts/preview", Object.assign(v, { page_id: activePageId() || null }));
        const prev = data.preview || {};
        const mock = $("saFbMockPreview");
        const body = $("saFbMockBody");
        const page = $("saFbMockPage");
        if (mock && body) {
            mock.hidden = false;
            if (page) page.textContent = prev.page_name || "Fanpage";
            body.textContent = prev.message || "";
        }
        showToast("Xem trước caption (" + (prev.char_count || 0) + " ký tự).");
    }

    async function scheduleCurrent() {
        if (!state.currentPost || !state.currentPost.id) {
            showToast("Chưa có bài để lên lịch.");
            return;
        }
        const when = promptDateTime();
        if (!when) return;
        await api("PATCH", "/posts/" + state.currentPost.id, Object.assign(variantFromForm(), { page_id: activePageId() || null }));
        try {
            const data = await api("POST", "/posts/" + state.currentPost.id + "/schedule", {
                scheduled_at: when,
                page_id: activePageId() || null,
            });
            state.currentPost = data.item;
            renderSafetyInline(data.safety);
            showToast("Đã lên lịch đăng Fanpage.");
            loadOverview();
        } catch (e) {
            if (e.data && e.data.detail && e.data.detail.safety) renderSafetyInline(e.data.detail.safety);
            showToast(e.message);
        }
    }

    async function runSafetyCheck() {
        const fp = formPayload();
        const v = variantFromForm();
        const data = await api("POST", "/safety/check", {
            title: v.title,
            content: v.content,
            hashtags: v.hashtags,
            keyword: fp.keyword,
            source_content: fp.source_content,
            source_title: fp.source_title,
            page_id: activePageId() || null,
            post_id: state.currentPost && state.currentPost.id,
        });
        renderSafetyChecks(data);
        renderSafetyInline(data);
    }

    async function generateVariants() {
        const fp = formPayload();
        if (!fp.source_title) { showToast("Nhập tiêu đề bài viết."); return; }
        if (!activePageId()) { showToast("Chọn Fanpage trước (tab Kênh đăng)."); return; }
        const btn = $("btnSaGenerate");
        if (btn) { btn.disabled = true; btn.textContent = "Đang tạo…"; }
        try {
            const data = await api("POST", "/generate-variants", fp);
            state.campaignId = data.campaign_id;
            state.currentPost = (data.posts && data.posts[0]) || null;
            fillVariantForm(state.currentPost);
            renderSafetyInline(data.safety);
            await loadOverview();
            showToast("Đã tạo biến thể Facebook.");
        } catch (e) {
            showToast(e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = "Tạo biến thể AI"; }
        }
    }

    function readWeb20Form() {
        return {
            account_id: ($("saW20Account") && $("saW20Account").value) || "",
            title: ($("saW20Title") && $("saW20Title").value.trim()) || "",
            slug: ($("saW20Slug") && $("saW20Slug").value.trim()) || "",
            excerpt: ($("saW20Excerpt") && $("saW20Excerpt").value.trim()) || "",
            html_content: ($("saW20Html") && $("saW20Html").value) || "",
            tags: (($("saW20Tags") && $("saW20Tags").value) || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean),
            category: ($("saW20Category") && $("saW20Category").value.trim()) || "",
            wp_status: ($("saW20Status") && $("saW20Status").value) || "draft",
            main_site_url: ($("saW20MainUrl") && $("saW20MainUrl").value.trim()) || "",
            source_title: ($("saW20SourceTitle") && $("saW20SourceTitle").value.trim()) || "",
            source_content: ($("saW20SourceContent") && $("saW20SourceContent").value) || "",
            keyword: ($("saW20Keyword") && $("saW20Keyword").value.trim()) || "",
        };
    }

    function fillWeb20Form(item) {
        if (!item) return;
        state.web20.currentPostId = item.id || null;
        if ($("saW20Account")) $("saW20Account").value = item.account_id || "";
        if ($("saW20Title")) $("saW20Title").value = item.title || "";
        if ($("saW20Slug")) $("saW20Slug").value = item.slug || "";
        if ($("saW20Excerpt")) $("saW20Excerpt").value = item.excerpt || "";
        if ($("saW20Html")) $("saW20Html").value = item.html_content || "";
        if ($("saW20Tags")) $("saW20Tags").value = (item.tags || []).join(", ");
        if ($("saW20Category")) $("saW20Category").value = item.category || "";
        if ($("saW20Status")) $("saW20Status").value = item.wp_status || "draft";
        if ($("saW20MainUrl")) $("saW20MainUrl").value = item.main_site_url || "";
        if ($("saW20SourceTitle")) $("saW20SourceTitle").value = item.source_title || "";
        if ($("saW20SourceContent")) $("saW20SourceContent").value = item.source_content || "";
        if ($("saW20ScheduledAt")) $("saW20ScheduledAt").value = item.scheduled_at || "";
        if ($("saW20ScheduleInput") && item.scheduled_at) {
            try {
                $("saW20ScheduleInput").value = new Date(item.scheduled_at).toISOString().slice(0, 16);
            } catch (e) { /* ignore */ }
        }
        if (item.safety_score != null) {
            renderWeb20Safety({ score: item.safety_score, passed: item.safety_passed, checks: [], can_publish: item.safety_passed });
        }
        if (item.platform) {
            state.web20.platform = item.platform;
            renderWeb20PlatformCards();
            renderWeb20ConnectPanel();
            renderWeb20Accounts();
        }
        if (item.manual_package) renderWeb20ManualPanel(item.manual_package);
        renderWeb20Preview();
        updateWeb20Stepper();
        updateWeb20ActionButtons();
    }

    function renderWeb20Safety(safety) {
        state.web20.lastSafety = safety || null;
        const el = $("saW20Safety");
        const ring = $("saW20GaugeRing");
        const scoreEl = $("saW20GaugeScore");
        const labelEl = $("saW20GaugeLabel");
        if (!safety) {
            if (el) el.hidden = true;
            if (scoreEl) scoreEl.textContent = "—";
            if (labelEl) labelEl.textContent = "Chưa kiểm tra";
            updateWeb20ActionButtons();
            return;
        }
        const score = safety.score != null ? safety.score : 0;
        const cls = score >= 70 ? "" : (score >= 50 ? " is-warn" : " is-bad");
        if (ring) {
            ring.className = "sa-web20-gauge__ring" + cls;
            ring.style.setProperty("--gauge-pct", score + "%");
        }
        if (scoreEl) scoreEl.textContent = score + "/100";
        if (labelEl) {
            labelEl.textContent = score >= 70 ? "Rất tốt" : (score >= 50 ? "Cần cải thiện" : "Chưa đạt");
        }
        if (el) {
            let html = "<ul class=\"sa-safety-list\">";
            (safety.checks || []).forEach(function (c) {
                const lv = c.level === "error" || !c.ok ? "err" : (c.level === "warning" ? "warn" : "ok");
                html += '<li class="sa-check-' + lv + '">' + esc(c.message || c.code) + "</li>";
            });
            html += "</ul>";
            el.innerHTML = html;
            el.hidden = false;
        }
        updateWeb20Stepper();
        updateWeb20ActionButtons();
    }

    const WEB20_PLATFORM_LABELS = {
        wordpress_2_0: "WordPress 2.0",
        blogger: "Blogger",
        tumblr: "Tumblr",
        medium: "Medium (Beta)",
        google_sites_manual: "Google Sites (Manual)",
        zalo_oa: "Zalo OA",
    };

    const CARD_STATUS_LABELS = {
        connected: "Connected",
        need_setup: "Need setup",
        token_expired: "Token expired",
        beta: "Beta",
        manual: "Manual",
        coming_soon: "Coming soon",
    };

    const CHANNEL_ICON_SRC = {
        facebook: "/static/img/social/channels/facebook.png",
        wordpress_2_0: "/static/img/social/channels/wordpress.png",
        blogger: "/static/img/social/channels/blogger.png",
        tumblr: "/static/img/social/channels/tumblr.png",
        google_sites_manual: "/static/img/social/channels/google-sites.png",
    };

    const WEB20_PLATFORM_ICONS = {
        wordpress_2_0: "WP",
        blogger: "B",
        tumblr: "T",
        medium: "M",
        google_sites_manual: "GS",
    };

    function composeChannelIconHtml(ch) {
        const src = ch.iconSrc || CHANNEL_ICON_SRC[ch.id] || CHANNEL_ICON_SRC[ch.platform || ""];
        if (src) {
            return '<img src="' + esc(src) + '" alt="" class="sa-channel-card__icon-img" width="32" height="32" loading="lazy" decoding="async">';
        }
        return esc(ch.icon || WEB20_PLATFORM_ICONS[ch.platform || ch.id] || "?");
    }

    const COMPOSE_CHANNELS = [
        { id: "facebook", label: "Facebook Fanpage", iconSrc: CHANNEL_ICON_SRC.facebook, type: "facebook" },
        { id: "wordpress_2_0", label: "WordPress 2.0", iconSrc: CHANNEL_ICON_SRC.wordpress_2_0, type: "web20", platform: "wordpress_2_0" },
        { id: "blogger", label: "Blogger", iconSrc: CHANNEL_ICON_SRC.blogger, type: "web20", platform: "blogger" },
        { id: "tumblr", label: "Tumblr", iconSrc: CHANNEL_ICON_SRC.tumblr, type: "web20", platform: "tumblr" },
        { id: "medium", label: "Medium (Beta)", icon: "M", type: "web20", platform: "medium", supportsAutoPublish: true },
        { id: "google_sites_manual", label: "Google Sites (Manual)", iconSrc: CHANNEL_ICON_SRC.google_sites_manual, type: "web20", platform: "google_sites_manual", supportsAutoPublish: false },
        { id: "zalo_oa", label: "Zalo OA", icon: "Z", type: "coming_soon", comingSoon: true, supportsAutoPublish: false },
    ];

    const CONNECTION_GUIDE_COMMON = {
        posting: {
            title: "Cách đăng bài sau khi kết nối",
            steps: [
                "Vào tab Soạn & phân phối.",
                "Nhập tiêu đề, nội dung, từ khóa và link cần SEO.",
                "Chọn các kênh muốn đăng.",
                "Bấm Tạo biến thể AI.",
                "Xem trước nội dung từng nền tảng.",
                "Bấm Kiểm tra an toàn.",
                "Chọn Đăng ngay hoặc Hẹn giờ.",
                "Theo dõi trạng thái trong tab Lịch đăng và Kết quả.",
            ],
        },
        safety: {
            title: "Lưu ý an toàn",
            items: [
                "Không đăng quá nhiều bài trong thời gian ngắn.",
                "Không đăng một nội dung giống hệt lên nhiều kênh.",
                "Không nhồi nhét hashtag, link hoặc từ khóa.",
                "Luôn xem preview trước khi đăng.",
                "Chỉ kết nối tài khoản/kênh mà bạn có quyền quản lý.",
            ],
        },
    };

    const CONNECTION_GUIDES = {
        facebook: {
            title: "Kết nối Facebook Fanpage",
            steps: [
                "Facebook Login for Business → Configurations → tạo config với 3 quyền Pages.",
                "Copy Configuration ID → admin lưu trong modal hoặc FACEBOOK_LOGIN_CONFIG_ID trong env.",
                "Hoặc: Use case «Quản lý Trang» → bật pages_show_list, pages_read_engagement, pages_manage_posts.",
                "Redirect URI: https://seoauto.vn/api/social/facebook/oauth/callback",
                "Bấm «Kết nối Fanpage» → đăng nhập Facebook → chọn Fanpage.",
            ],
            notes: [
                "Redirect URI: https://seoauto.vn/api/social/facebook/oauth/callback",
                "Không nhập mật khẩu Facebook vào SEOAuto.",
            ],
        },
        wordpress_2_0: {
            title: "Kết nối WordPress vệ tinh",
            steps: [
                "Vào Nền tảng → bấm «+ Kết nối» → chọn WordPress.",
                "Nhập URL website WordPress.",
                "Nhập Username WordPress.",
                "Tạo và nhập Application Password trong WordPress.",
                "Bấm Test kết nối.",
                "Nếu thành công, lưu kênh và bắt đầu đăng bài.",
            ],
        },
        blogger: {
            title: "Kết nối Blogger",
            steps: [
                "Vào Nền tảng → bấm «+ Kết nối» → chọn Blogger.",
                "Bấm Kết nối Google/Blogger.",
                "Đăng nhập tài khoản Google có quyền quản lý blog.",
                "Cấp quyền cho hệ thống kết nối Blogger.",
                "Chọn blog muốn đăng bài.",
                "Bấm Test kết nối.",
                "Nếu trạng thái là Đã kết nối, bạn có thể đăng hoặc hẹn giờ.",
            ],
        },
        tumblr: {
            title: "Kết nối Tumblr",
            steps: [
                "Vào Nền tảng → bấm «+ Kết nối» → chọn Tumblr.",
                "Bấm Kết nối Tumblr.",
                "Đăng nhập tài khoản Tumblr.",
                "Cho phép hệ thống kết nối tài khoản.",
                "Chọn blog Tumblr muốn đăng.",
                "Bấm Test kết nối.",
                "Nếu thành công, bạn có thể đăng bài.",
            ],
        },
        medium: {
            title: "Kết nối Medium",
            steps: [
                "Vào Nền tảng → bấm «+ Kết nối» → chọn Medium.",
                "Lấy Medium Integration Token trong tài khoản Medium.",
                "Dán token vào phần mềm.",
                "Bấm Test kết nối.",
                "Nếu thành công, lưu kênh Medium.",
            ],
            notes: ["Medium đang là tính năng Beta — nếu token lỗi hãy tạo token mới."],
        },
        google_sites_manual: {
            title: "Google Sites Manual",
            steps: [
                "Vào Nền tảng → chọn Google Sites Manual.",
                "Không cần kết nối API.",
                "Khi tạo bài, hệ thống sẽ tạo gói nội dung gồm tiêu đề, nội dung, mô tả, CTA và hình ảnh gợi ý.",
                "Bấm Copy nội dung.",
                "Tự dán nội dung vào Google Sites.",
            ],
            notes: ["Google Sites hiện là đăng thủ công, không đăng tự động."],
        },
        zalo_oa: {
            title: "Zalo OA",
            steps: [
                "Zalo OA đang trong giai đoạn Coming soon.",
                "Hiện chưa hỗ trợ kết nối và đăng tự động.",
                "Theo dõi cập nhật trên Social Auto để biết khi tính năng mở.",
            ],
        },
    };

    function connectionGuideButtonHtml(channelId) {
        return '<button type="button" class="sa-btn sa-btn--ghost sa-btn--xs sa-channel-card__guide" data-sa-action="channel-guide" data-channel="' +
            esc(channelId) + '">Hướng dẫn kết nối</button>';
    }

    function facebookConnectionInfo() {
        return (state.fb && state.fb.connection) || { status: "not_connected", label: "Chưa kết nối" };
    }

    function facebookConnectButtonHtml(extraClass) {
        const conn = facebookConnectionInfo();
        const cls = "sa-btn sa-btn--primary sa-btn--xs sa-channel-card__connect" + (extraClass ? " " + extraClass : "");
        const statusCls = "sa-fb-connect-status sa-fb-connect-status--" + esc(conn.status || "not_connected");
        let label = "Kết nối Fanpage";
        if (conn.status === "connected") label = "Kết nối Fanpage khác";
        else if (conn.label) label = conn.label + " · Kết nối lại";
        return '<div class="sa-fb-connect-wrap">' +
            '<span class="' + statusCls + '">' + esc(conn.label || "Chưa kết nối") + "</span>" +
            '<button type="button" class="' + cls + '" data-sa-action="connect-fb">' +
            '<span class="sa-fb-connect-ico" aria-hidden="true">f</span> ' + esc(label) + "</button></div>";
    }

    function renderFbConnectionBanner() {
        const conn = facebookConnectionInfo();
        const box = $("saFbPagesList");
        if (!box || conn.status === "connected") return;
        const msg = conn.message ? '<p class="sa-hint sa-fb-connect-msg">' + esc(conn.message) + "</p>" : "";
        const existing = box.querySelector(".sa-fb-connect-banner");
        if (existing) existing.remove();
        if (conn.status === "not_connected" && !(state.fb.pages || []).length) return;
        const banner = document.createElement("div");
        banner.className = "sa-fb-connect-banner sa-fb-connect-banner--" + (conn.status || "not_connected");
        banner.innerHTML = '<strong>' + esc(conn.label || "") + "</strong>" + msg + facebookConnectButtonHtml("sa-btn--sm");
        box.insertBefore(banner, box.firstChild);
    }

    function channelCardFootHtml(ch) {
        let html = '<div class="sa-channel-card__foot">';
        if (ch.type === "facebook" && !(state.fb.pages || []).length) {
            html += facebookConnectButtonHtml();
        }
        html += connectionGuideButtonHtml(ch.id);
        html += "</div>";
        return html;
    }

    function renderConnectionGuideContent(channelId) {
        const guide = CONNECTION_GUIDES[channelId];
        if (!guide) return "<p class=\"sa-empty\">Chưa có hướng dẫn cho kênh này.</p>";
        let html = "<section class=\"sa-connection-guide__section\">";
        html += "<h3 class=\"sa-connection-guide__heading\">Các bước thực hiện</h3><ol class=\"sa-connection-guide__steps\">";
        guide.steps.forEach(function (step) {
            html += "<li>" + esc(step) + "</li>";
        });
        html += "</ol>";
        if (guide.notes && guide.notes.length) {
            html += "<ul class=\"sa-connection-guide__notes\">";
            guide.notes.forEach(function (note) {
                html += "<li>" + esc(note) + "</li>";
            });
            html += "</ul>";
        }
        html += "</section>";
        if (channelId !== "zalo_oa") {
            html += "<section class=\"sa-connection-guide__section sa-connection-guide__section--muted\">";
            html += "<h3 class=\"sa-connection-guide__heading\">" + esc(CONNECTION_GUIDE_COMMON.posting.title) + "</h3>";
            html += "<ol class=\"sa-connection-guide__steps\">";
            CONNECTION_GUIDE_COMMON.posting.steps.forEach(function (step) {
                html += "<li>" + esc(step) + "</li>";
            });
            html += "</ol></section>";
        }
        html += "<section class=\"sa-connection-guide__section sa-connection-guide__section--muted\">";
        html += "<h3 class=\"sa-connection-guide__heading\">" + esc(CONNECTION_GUIDE_COMMON.safety.title) + "</h3>";
        html += "<ul class=\"sa-connection-guide__bullets\">";
        CONNECTION_GUIDE_COMMON.safety.items.forEach(function (item) {
            html += "<li>" + esc(item) + "</li>";
        });
        html += "</ul></section>";
        return html;
    }

    function openConnectionGuideModal(channelId) {
        const dlg = $("saConnectionGuideModal");
        const body = $("saConnectionGuideBody");
        const titleEl = $("saConnectionGuideTitle");
        if (!dlg || !body) return;
        const ch = COMPOSE_CHANNELS.find(function (x) { return x.id === channelId; });
        const guide = CONNECTION_GUIDES[channelId];
        if (titleEl) titleEl.textContent = (guide && guide.title) || (ch && ch.label) || "Hướng dẫn kết nối";
        body.innerHTML = renderConnectionGuideContent(channelId);
        if (dlg.showModal) dlg.showModal();
    }

    function platformCardStatusBadge(status) {
        const st = String(status || "need_setup").toLowerCase();
        const label = CARD_STATUS_LABELS[st] || st;
        return '<span class="sa-platform-status sa-platform-status--' + esc(st) + '">' + esc(label) + "</span>";
    }

    function channelSupportsAutoPublish(ch) {
        if (!ch || ch.comingSoon || ch.type === "coming_soon") return false;
        if (ch.supportsAutoPublish === false) return false;
        if (ch.id === "google_sites_manual" || ch.platform === "google_sites_manual") return false;
        if (ch.type === "facebook") return (state.fb.pages || []).length > 0;
        const pf = ch.platform || ch.id;
        const plat = (state.web20.platforms || []).find(function (x) { return x.id === pf; });
        if (plat && plat.supports_auto_publish === false) return false;
        return true;
    }

    function channelReadyForPublish(ch) {
        if (!ch) return { ok: false, msg: "Kênh không hợp lệ." };
        if (ch.comingSoon || ch.type === "coming_soon") {
            return { ok: false, msg: "Zalo OA đang Coming soon — chưa hỗ trợ đăng tự động." };
        }
        if (ch.type === "facebook") {
            const pid = state.compose.accountMap[ch.id];
            if (!pid) return { ok: false, msg: "Chọn Fanpage Facebook." };
            const page = (state.fb.pages || []).find(function (p) { return p.page_id === pid; });
            if (!page) return { ok: false, msg: "Fanpage chưa kết nối — cần setup." };
            return { ok: true };
        }
        const pf = ch.platform || ch.id;
        if (pf === "google_sites_manual") return { ok: true, manual: true };
        const accId = state.compose.accountMap[ch.id];
        if (!accId) return { ok: false, msg: "Chọn tài khoản " + (ch.label || pf) + "." };
        const acc = (state.web20.accounts || []).find(function (a) { return a.id === accId; });
        if (!acc) return { ok: false, msg: "Tài khoản không tồn tại." };
        const st = acc.card_status || "need_setup";
        if (st === "need_setup") return { ok: false, msg: (ch.label || pf) + " — cần kết nối trước." };
        if (st === "token_expired") return { ok: false, msg: (ch.label || pf) + " — token hết hạn, kết nối lại." };
        if (st === "coming_soon") return { ok: false, msg: (ch.label || pf) + " — Coming soon." };
        return { ok: true };
    }

    function composeChannelCardStatus(ch) {
        if (ch.comingSoon || ch.type === "coming_soon") return "coming_soon";
        if (ch.type === "facebook") {
            return (state.fb.pages || []).length ? "connected" : "need_setup";
        }
        const pf = ch.platform || ch.id;
        const plat = (state.web20.platforms || []).find(function (x) { return x.id === pf; });
        if (plat && plat.card_status) return plat.card_status;
        const accs = web20AccountsForPlatform(pf);
        if (pf === "google_sites_manual") return accs.length ? "manual" : "need_setup";
        if (!accs.length) return "need_setup";
        if (accs.some(function (a) { return a.card_status === "token_expired"; })) return "token_expired";
        if (pf === "medium") return "beta";
        return "connected";
    }

    function updateComposeScheduleSection() {
        const section = $("saComposeScheduleSection");
        const hasAuto = composeSelectedChannels().some(channelSupportsAutoPublish);
        if (section) section.hidden = !hasAuto;
    }

    function composeChannelMeta(ch) {
        if (ch.type === "facebook") {
            const pages = state.fb.pages || [];
            if (!pages.length) return "Chưa kết nối";
            const active = state.fb.active_page;
            return active ? "Đã kết nối · " + pages.length + " page" : pages.length + " page · chọn đích";
        }
        const pf = ch.platform || ch.id;
        return web20PlatformMeta(pf);
    }

    function composeSelectedChannels() {
        return COMPOSE_CHANNELS.filter(function (ch) { return state.compose.selected[ch.id]; });
    }

    function syncComposeSourceToWeb20() {
        if ($("saW20SourceTitle")) $("saW20SourceTitle").value = ($("saTitle") && $("saTitle").value) || "";
        if ($("saW20SourceContent")) $("saW20SourceContent").value = ($("saSourceContent") && $("saSourceContent").value) || "";
        if ($("saW20Keyword")) $("saW20Keyword").value = ($("saKeyword") && $("saKeyword").value) || "";
        if ($("saW20MainUrl")) $("saW20MainUrl").value = ($("saUrl") && $("saUrl").value) || "";
        if ($("saW20Tone")) $("saW20Tone").value = ($("saTone") && $("saTone").value) || "chuyên gia";
        const c = $("saSourceTitleCount");
        if (c && $("saTitle")) c.textContent = ($("saTitle").value.length || 0) + "/500";
    }

    function renderComposeChannelCards() {
        const el = $("saChannelCards");
        if (!el) return;
        el.innerHTML = COMPOSE_CHANNELS.map(function (ch) {
            if (ch.comingSoon) {
                return '<div class="sa-channel-card sa-channel-card--disabled">' +
                    '<div class="sa-channel-card__body sa-channel-card__body--static">' +
                    '<span class="sa-channel-card__icon">' + composeChannelIconHtml(ch) + "</span>" +
                    '<span class="sa-channel-card__name">' + esc(ch.label) + "</span>" +
                    '<span class="sa-channel-card__meta">Coming soon</span></div>' +
                    channelCardFootHtml(ch) + "</div>";
            }
            const sel = !!state.compose.selected[ch.id];
            const cls = sel ? "sa-channel-card is-selected" : "sa-channel-card";
            let accountHtml = "";
            if (sel) {
                if (ch.type === "facebook") {
                    const pages = state.fb.pages || [];
                    accountHtml = '<select class="sa-channel-card__account" data-sa-action="compose-account" data-channel="' + esc(ch.id) + '">' +
                        '<option value="">— Chọn Fanpage —</option>' +
                        pages.map(function (p) {
                            const v = state.compose.accountMap[ch.id] || (state.fb.active_page && state.fb.active_page.page_id) || "";
                            return '<option value="' + esc(p.page_id) + '"' + (p.page_id === v ? " selected" : "") + ">" + esc(p.page_name) + "</option>";
                        }).join("") + "</select>";
                } else {
                    const pf = ch.platform || ch.id;
                    const accs = web20AccountsForPlatform(pf);
                    const cur = state.compose.accountMap[ch.id] || "";
                    accountHtml = '<select class="sa-channel-card__account" data-sa-action="compose-account" data-channel="' + esc(ch.id) + '">' +
                        '<option value="">— Chọn tài khoản —</option>' +
                        accs.map(function (a) {
                            return '<option value="' + esc(a.id) + '"' + (a.id === cur ? " selected" : "") + ">" +
                                esc(a.label || a.site_url || a.platform) + "</option>";
                        }).join("") + "</select>";
                }
            }
            return '<div class="' + cls + '">' +
                '<button type="button" class="sa-channel-card__body" data-sa-action="compose-toggle-channel" data-channel="' + esc(ch.id) + '">' +
                '<span class="sa-channel-card__icon">' + composeChannelIconHtml(ch) + "</span>" +
                '<span class="sa-channel-card__name">' + esc(ch.label) + "</span>" +
                '<span class="sa-channel-card__meta">' + esc(composeChannelMeta(ch)) + "</span>" +
                "</button>" +
                accountHtml +
                channelCardFootHtml(ch) + "</div>";
        }).join("");
        updateComposeStepper();
        updateComposeActionButtons();
        updateComposeScheduleSection();
    }

    function setComposeActiveChannel(channelId) {
        state.compose.activeChannel = channelId;
        const ch = COMPOSE_CHANNELS.find(function (x) { return x.id === channelId; });
        const v = state.compose.variants[channelId];
        if (ch && ch.type === "facebook" && v && v.post) {
            fillVariantForm(v.post);
            state.currentPost = v.post;
        }
        if (ch && ch.type === "web20" && v && v.post) {
            state.web20.platform = ch.platform || ch.id;
            fillWeb20Form(v.post);
            state.compose.lastSafety = v.safety || null;
        }
        document.querySelectorAll(".sa-variant-item").forEach(function (item) {
            item.classList.toggle("is-active", item.getAttribute("data-channel") === channelId);
        });
        renderComposePreview();
        renderComposeSafety(state.compose.lastSafety);
        updateComposeActionButtons();
    }

    function renderComposeVariantsAccordion() {
        const el = $("saVariantsAccordion");
        if (!el) return;
        const selected = composeSelectedChannels();
        if (!selected.length) {
            el.innerHTML = '<p class="sa-empty">Chọn ít nhất một kênh phân phối.</p>';
            return;
        }
        const hasAny = selected.some(function (ch) { return state.compose.variants[ch.id]; });
        if (!hasAny) {
            el.innerHTML = '<p class="sa-empty">Bấm «AI tạo biến thể» để tạo nội dung cho từng kênh.</p>';
            return;
        }
        el.innerHTML = selected.map(function (ch) {
            const v = state.compose.variants[ch.id];
            const open = state.compose.activeChannel === ch.id;
            const badge = v && v.safety && v.safety.score != null
                ? '<span class="sa-w20-badge sa-w20-badge--' + (v.safety.can_publish ? "published" : "draft") + '">' + esc(v.safety.score) + "/100</span>"
                : '<span class="sa-w20-badge sa-w20-badge--draft">chưa tạo</span>';
            let fields = "";
            if (v && v.post) {
                if (ch.type === "facebook") {
                    fields = '<div class="sa-field"><label>Tiêu đề / hook</label><input type="text" data-compose-field="fb-title" data-channel="' + esc(ch.id) + '" value="' + esc(v.post.title || "") + '"></div>' +
                        '<div class="sa-field"><label>Caption</label><textarea rows="5" data-compose-field="fb-content" data-channel="' + esc(ch.id) + '">' + esc(v.post.content || "") + "</textarea></div>" +
                        '<div class="sa-field"><label>Hashtags</label><input type="text" data-compose-field="fb-hashtags" data-channel="' + esc(ch.id) + '" value="' + esc(v.post.hashtags || "") + '"></div>' +
                        '<div class="sa-field"><label>CTA</label><input type="text" data-compose-field="fb-cta" data-channel="' + esc(ch.id) + '" value="' + esc(v.post.cta || "") + '"></div>';
                } else {
                    fields = '<div class="sa-field"><label>Title</label><input type="text" data-compose-field="w20-title" data-channel="' + esc(ch.id) + '" value="' + esc(v.post.title || "") + '"></div>' +
                        '<div class="sa-field"><label>Slug</label><input type="text" data-compose-field="w20-slug" data-channel="' + esc(ch.id) + '" value="' + esc(v.post.slug || "") + '"></div>' +
                        '<div class="sa-field"><label>Excerpt</label><textarea rows="2" data-compose-field="w20-excerpt" data-channel="' + esc(ch.id) + '">' + esc(v.post.excerpt || "") + "</textarea></div>" +
                        '<div class="sa-field"><label>Tags</label><input type="text" data-compose-field="w20-tags" data-channel="' + esc(ch.id) + '" value="' + esc((v.post.tags || []).join(", ")) + '"></div>' +
                        '<div class="sa-field"><label>HTML</label><textarea rows="6" data-compose-field="w20-html" data-channel="' + esc(ch.id) + '">' + esc(v.post.html_content || "") + "</textarea></div>";
                }
            } else {
                fields = '<p class="sa-empty">Chưa có biến thể — chạy AI tạo biến thể.</p>';
            }
            return '<article class="sa-variant-item' + (open ? " is-active" : "") + '" data-channel="' + esc(ch.id) + '">' +
                '<div class="sa-variant-item__head" data-sa-action="compose-open-variant" data-channel="' + esc(ch.id) + '">' +
                "<strong>" + esc(ch.label) + "</strong>" + badge + "</div>" +
                '<div class="sa-variant-item__body sa-variant-fields"' + (open ? "" : " hidden") + ">" + fields + "</div></article>";
        }).join("");
        if (!state.compose.activeChannel && selected.length) {
            setComposeActiveChannel(selected[0].id);
        }
        updateComposeStepper();
        updateComposeActionButtons();
    }

    function readComposeVariantFromDom(channelId) {
        const v = state.compose.variants[channelId];
        if (!v || !v.post) return v;
        const ch = COMPOSE_CHANNELS.find(function (x) { return x.id === channelId; });
        if (!ch) return v;
        if (ch.type === "facebook") {
            const t = document.querySelector('[data-compose-field="fb-title"][data-channel="' + channelId + '"]');
            const c = document.querySelector('[data-compose-field="fb-content"][data-channel="' + channelId + '"]');
            const h = document.querySelector('[data-compose-field="fb-hashtags"][data-channel="' + channelId + '"]');
            const ct = document.querySelector('[data-compose-field="fb-cta"][data-channel="' + channelId + '"]');
            v.post.title = t ? t.value.trim() : v.post.title;
            v.post.content = c ? c.value.trim() : v.post.content;
            v.post.hashtags = h ? h.value.trim() : v.post.hashtags;
            v.post.cta = ct ? ct.value.trim() : v.post.cta;
        } else {
            const fields = ["title", "slug", "excerpt", "html"];
            fields.forEach(function (f) {
                const el = document.querySelector('[data-compose-field="w20-' + f + '"][data-channel="' + channelId + '"]');
                if (el) v.post[f === "html" ? "html_content" : f] = el.value.trim ? (f === "html" ? el.value : el.value.trim()) : el.value;
            });
            const tg = document.querySelector('[data-compose-field="w20-tags"][data-channel="' + channelId + '"]');
            if (tg) v.post.tags = tg.value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
        }
        state.compose.variants[channelId] = v;
        return v;
    }

    function previewShellClass(ch) {
        if (!ch) return "empty";
        if (ch.type === "facebook") return "facebook";
        const pf = ch.platform || ch.id;
        if (pf === "wordpress_2_0") return "wordpress";
        if (pf === "google_sites_manual") return "google_sites";
        return pf.replace(/[^a-z0-9_]/g, "") || "empty";
    }

    function renderComposePreview() {
        const el = $("saComposePreview");
        const shell = $("saComposePreviewShell");
        const tagsEl = $("saComposePreviewTags");
        const badge = $("saComposePreviewChannel");
        const fbMock = $("saFbMockPreview");
        const chId = state.compose.activeChannel;
        const ch = COMPOSE_CHANNELS.find(function (x) { return x.id === chId; });
        if (!el) return;
        if (badge) badge.textContent = ch ? ch.label : "—";
        if (fbMock) fbMock.hidden = true;
        if (shell) shell.className = "sa-preview-shell sa-preview-shell--" + previewShellClass(ch);
        if (!chId || !ch) {
            el.innerHTML = '<p class="sa-empty">Chọn nền tảng để xem preview.</p>';
            if (tagsEl) tagsEl.innerHTML = "";
            return;
        }
        const v = readComposeVariantFromDom(chId);
        if (!v || !v.post) {
            el.innerHTML = '<p class="sa-empty">Chưa có biến thể — chạy AI tạo biến thể.</p>';
            if (tagsEl) tagsEl.innerHTML = "";
            return;
        }
        const post = v.post;
        if (ch.type === "facebook") {
            const pageName = accountLabelForChannel(ch);
            if (fbMock) {
                fbMock.hidden = false;
                if ($("saFbMockPage")) $("saFbMockPage").textContent = pageName;
                if ($("saFbMockBody")) {
                    $("saFbMockBody").innerHTML = (post.title ? "<strong>" + esc(post.title) + "</strong><br>" : "") +
                        esc(post.content || "") + (post.hashtags ? "<p><em>" + esc(post.hashtags) + "</em></p>" : "") +
                        (post.cta ? "<p>" + esc(post.cta) + "</p>" : "");
                }
            }
            el.innerHTML = "";
            if (tagsEl) tagsEl.innerHTML = "";
            return;
        }
        if (ch.platform === "google_sites_manual") {
            el.innerHTML = "<h4>" + esc(post.title || "") + "</h4>" +
                (post.excerpt ? "<p><em>" + esc(post.excerpt) + "</em></p>" : "") +
                (post.slug ? "<p class=\"sa-preview-slug\">/" + esc(post.slug) + "</p>" : "") +
                (post.html_content || "");
        } else if (ch.platform === "medium") {
            el.innerHTML = "<h2 class=\"sa-preview-medium-title\">" + esc(post.title || "") + "</h2>" +
                (post.excerpt ? "<p class=\"sa-preview-medium-sub\">" + esc(post.excerpt) + "</p>" : "") +
                (post.html_content || "");
        } else if (ch.platform === "tumblr") {
            el.innerHTML = "<h3>" + esc(post.title || "") + "</h3>" + (post.html_content || "");
        } else {
            el.innerHTML = (post.title ? "<h3>" + esc(post.title) + "</h3>" : "") +
                (post.excerpt ? "<p><em>" + esc(post.excerpt) + "</em></p>" : "") +
                (post.html_content || "");
        }
        if (tagsEl) {
            tagsEl.innerHTML = (post.tags || []).slice(0, 8).map(function (t) {
                return "<span>" + esc(t) + "</span>";
            }).join("");
        }
    }

    function renderComposeSafety(safety) {
        state.compose.lastSafety = safety || null;
        const ring = $("saComposeGaugeRing");
        const scoreEl = $("saComposeGaugeScore");
        const labelEl = $("saComposeGaugeLabel");
        const el = $("saComposeSafety");
        if (!safety) {
            if (ring) ring.className = "sa-web20-gauge__ring";
            if (scoreEl) scoreEl.textContent = "—";
            if (labelEl) labelEl.textContent = "Chưa kiểm tra";
            if ($("saSafetyBlockHint")) $("saSafetyBlockHint").hidden = true;
            if (el) el.hidden = true;
            updateComposeActionButtons();
            return;
        }
        const score = safety.score != null ? safety.score : 0;
        const cls = score >= 70 ? "" : (score >= 50 ? " is-warn" : " is-bad");
        if (ring) {
            ring.className = "sa-web20-gauge__ring" + cls;
            ring.style.setProperty("--gauge-pct", score + "%");
        }
        if (scoreEl) scoreEl.textContent = score + "/100";
        const blockHint = $("saSafetyBlockHint");
        if (blockHint) blockHint.hidden = score >= 70;
        if (labelEl) {
            labelEl.textContent = score >= 70 ? "Đạt — có thể đăng" : (score >= 50 ? "Cần cải thiện" : "Chưa đạt — cần sửa");
        }
        if (el) {
            let html = "<ul class=\"sa-safety-list\">";
            (safety.checks || []).forEach(function (c) {
                const lv = c.level === "error" || !c.ok ? "err" : (c.level === "warning" ? "warn" : "ok");
                if (!c.ok || c.level === "warning" || c.level === "error") {
                    html += '<li class="sa-check-' + lv + '">' + esc(c.message || c.code) + "</li>";
                }
            });
            html += "</ul>";
            el.innerHTML = html;
            el.hidden = !(safety.checks && safety.checks.length);
        }
        updateComposeActionButtons();
    }

    function updateComposeStepper() {
        const hasCamp = !!(state.campaignId || ($("saCampaignName") && $("saCampaignName").value.trim()));
        const hasSource = !!($("saTitle") && $("saTitle").value.trim() && $("saSourceContent") && $("saSourceContent").value.trim());
        const hasChannels = composeSelectedChannels().length > 0;
        const hasVariants = composeSelectedChannels().some(function (ch) { return state.compose.variants[ch.id]; });
        const hasSafety = !!state.compose.lastSafety;
        let active = 1;
        if (hasCamp) active = 2;
        if (hasCamp && hasSource) active = 3;
        if (hasCamp && hasSource && hasChannels) active = 4;
        if (hasCamp && hasSource && hasChannels && hasVariants) active = 5;
        if (hasVariants && hasSafety) active = 5;
        document.querySelectorAll(".sa-compose-step").forEach(function (step) {
            const n = parseInt(step.getAttribute("data-step"), 10);
            step.classList.toggle("is-active", n === active);
            step.classList.toggle("is-done", n < active);
        });
    }

    function composeCanPublishNow() {
        const selected = composeSelectedChannels().filter(channelSupportsAutoPublish);
        if (!selected.length) return false;
        return selected.every(function (ch) {
            const ready = channelReadyForPublish(ch);
            if (!ready.ok || ready.manual) return false;
            const v = state.compose.variants[ch.id];
            if (!v || !v.post) return false;
            if (ch.type === "facebook") return !!(v.post.title && v.post.content);
            if (!v.safety || !v.safety.can_publish) return false;
            return !!(v.post.title && v.post.html_content);
        });
    }

    function updateComposeActionButtons() {
        const selected = composeSelectedChannels();
        const hasAuto = selected.some(channelSupportsAutoPublish);
        const onlyManual = selected.length > 0 && !hasAuto;
        const allManual = selected.length > 0 && selected.every(function (ch) {
            const ready = channelReadyForPublish(ch);
            return ready.manual;
        });

        const nowBtn = $("saComposePublishNowBtn");
        const nowMob = $("saComposePublishNowBtnMobile");
        const draftBtn = $("saComposePublishDraftBtn");
        const draftMob = $("saComposePublishDraftBtnMobile");
        const hint = $("saComposeActionsHint");
        const canNow = composeCanPublishNow();

        if (nowBtn) { nowBtn.disabled = !canNow; nowBtn.hidden = onlyManual; }
        if (nowMob) { nowMob.disabled = !canNow; nowMob.hidden = onlyManual; }

        const draftLabel = allManual
            ? "Tạo gói copy thủ công"
            : "Đăng draft lên nền tảng";
        if (draftBtn) {
            draftBtn.textContent = draftLabel;
            draftBtn.hidden = !selected.length;
        }
        if (draftMob) {
            draftMob.textContent = allManual ? "Gói copy" : "Draft";
            draftMob.hidden = !selected.length;
        }
        if (hint) {
            hint.textContent = onlyManual
                ? "Google Sites cần copy thủ công — dùng «Tạo gói copy thủ công»."
                : "Đăng ngay yêu cầu Safety Score ≥ 70 trên từng kênh tự động.";
            hint.hidden = !selected.length;
        }

        updateComposeScheduleSection();
        updateComposeStepper();
    }

    async function loadComposeTab() {
        await Promise.all([loadOverview(), loadWeb20Tab()]);
        markSaTabFetched("overview");
        markSaTabFetched("compose");
        renderComposeChannelCards();
        renderComposeVariantsAccordion();
        syncComposeSourceToWeb20();
        updateComposeStepper();
    }

    async function composeGenerateAll() {
        syncComposeSourceToWeb20();
        const selected = composeSelectedChannels();
        if (!selected.length) { showToast("Chọn ít nhất một kênh phân phối."); return; }
        if (!($("saTitle") && $("saTitle").value.trim())) { showToast("Nhập tiêu đề bài gốc."); return; }
        const btn = $("btnSaGenerate");
        if (btn) { btn.disabled = true; btn.textContent = "Đang tạo…"; }
        let ok = 0;
        try {
            for (let i = 0; i < selected.length; i++) {
                const ch = selected[i];
                const accId = state.compose.accountMap[ch.id];
                if (ch.type === "facebook") {
                    if (!accId) { showToast("Chọn Fanpage cho Facebook."); continue; }
                    if ($("saActivePage")) $("saActivePage").value = accId;
                    await api("POST", "/facebook/pages/" + encodeURIComponent(accId) + "/activate");
                    const fp = formPayload();
                    const data = await api("POST", "/generate-variants", fp);
                    state.campaignId = data.campaign_id;
                    const post = (data.posts && data.posts[0]) || null;
                    state.compose.variants[ch.id] = { type: "facebook", post: post, safety: data.safety, postId: post && post.id };
                    state.currentPost = post;
                    ok++;
                } else {
                    const pf = ch.platform || ch.id;
                    if (!accId) { showToast("Chọn tài khoản cho " + ch.label + "."); continue; }
                    state.web20.platform = pf;
                    const toneEl = $("saTone");
                    const data = await apiWeb20("POST", "/generate", {
                        account_id: accId,
                        source_title: ($("saTitle") && $("saTitle").value.trim()) || "",
                        source_content: ($("saSourceContent") && $("saSourceContent").value) || "",
                        keyword: ($("saKeyword") && $("saKeyword").value.trim()) || "",
                        target_url: ($("saUrl") && $("saUrl").value.trim()) || "",
                        main_site_url: ($("saUrl") && $("saUrl").value.trim()) || "",
                        tone: (toneEl && toneEl.value) || "chuyên gia",
                    });
                    state.compose.variants[ch.id] = {
                        type: "web20", platform: pf, post: data.item,
                        safety: data.safety, postId: data.item && data.item.id,
                    };
                    ok++;
                }
            }
            await loadOverview();
            await loadWeb20Tab();
            renderComposeVariantsAccordion();
            if (selected[0]) setComposeActiveChannel(selected[0].id);
            showToast("Đã tạo " + ok + " biến thể.");
        } catch (e) {
            showToast(e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = "✨ AI tạo biến thể"; }
        }
    }

    async function composeSaveAll(opts) {
        opts = opts || {};
        const selected = composeSelectedChannels();
        for (let i = 0; i < selected.length; i++) {
            const ch = selected[i];
            const v = readComposeVariantFromDom(ch.id);
            if (!v || !v.post) continue;
            if (ch.type === "facebook" && v.postId) {
                if ($("saFbTitle")) $("saFbTitle").value = v.post.title || "";
                if ($("saFbContent")) $("saFbContent").value = v.post.content || "";
                if ($("saFbHashtags")) $("saFbHashtags").value = v.post.hashtags || "";
                if ($("saFbCta")) $("saFbCta").value = v.post.cta || "";
                state.currentPost = { id: v.postId };
                await saveCurrentDraft();
            } else if (ch.type === "web20" && v.postId) {
                state.web20.currentPostId = v.postId;
                state.web20.platform = ch.platform || ch.id;
                if ($("saW20Account")) $("saW20Account").value = state.compose.accountMap[ch.id] || "";
                fillWeb20Form(v.post);
                await web20SaveDraft();
            }
        }
        if (!opts.silent) {
            showToast("Đã lưu thay đổi.");
            await loadComposeTab();
        }
    }

    async function composeSaveBeforeAction() {
        const selected = composeSelectedChannels();
        if (!selected.length) return;
        await composeSaveAll({ silent: true });
    }

    async function composeScheduleAll() {
        await composeSaveBeforeAction();
        const when = ($("saComposeScheduleInput") && $("saComposeScheduleInput").value) || "";
        if (!when) { showToast("Chọn ngày giờ lên lịch."); return; }
        const iso = new Date(when).toISOString();
        const selected = composeSelectedChannels().filter(channelSupportsAutoPublish);
        if (!selected.length) { showToast("Không có kênh hỗ trợ lên lịch tự động."); return; }
        for (let i = 0; i < selected.length; i++) {
            const ch = selected[i];
            const ready = channelReadyForPublish(ch);
            if (!ready.ok) { showToast(ready.msg); return; }
            const v = readComposeVariantFromDom(ch.id);
            if (!v || !v.postId) continue;
            if (ch.type === "facebook") {
                await api("PATCH", "/posts/" + v.postId, {
                    title: v.post.title, content: v.post.content,
                    hashtags: v.post.hashtags, cta: v.post.cta,
                    page_id: state.compose.accountMap[ch.id] || null,
                });
                await api("POST", "/posts/" + v.postId + "/schedule", {
                    scheduled_at: iso, page_id: state.compose.accountMap[ch.id] || null,
                });
            } else {
                await apiWeb20("PATCH", "/posts/" + encodeURIComponent(v.postId), {
                    title: v.post.title, slug: v.post.slug, excerpt: v.post.excerpt,
                    html_content: v.post.html_content, tags: v.post.tags || [],
                });
                await apiWeb20("POST", "/posts/" + encodeURIComponent(v.postId) + "/schedule", { scheduled_at: iso });
            }
        }
        showToast("Đã lên lịch " + selected.length + " kênh.");
        invalidateSaTabs(["schedule", "overview", "results", "compose"]);
        loadSchedule();
        loadOverview();
    }

    async function composePublishAll() {
        await composeSaveBeforeAction();
        const selected = composeSelectedChannels();
        for (let i = 0; i < selected.length; i++) {
            const ch = selected[i];
            const ready = channelReadyForPublish(ch);
            if (!ready.ok) { showToast(ready.msg); return; }
            const v = readComposeVariantFromDom(ch.id);
            if (!v || !v.postId) continue;
            if (ch.type === "facebook") {
                await api("PATCH", "/posts/" + v.postId, {
                    title: v.post.title, content: v.post.content,
                    hashtags: v.post.hashtags, cta: v.post.cta,
                    page_id: state.compose.accountMap[ch.id] || null,
                });
                await api("POST", "/posts/" + v.postId + "/publish");
            } else {
                state.web20.currentPostId = v.postId;
                state.web20.platform = ch.platform || ch.id;
                fillWeb20Form(v.post);
                if ($("saW20Status")) $("saW20Status").value = "draft";
                await web20Publish();
            }
        }
        showToast("Đã đăng draft / tạo gói copy.");
        invalidateSaTabs(["results", "overview", "compose"]);
        loadResults();
        loadOverview();
    }

    async function composePublishNowAll() {
        if (!composeCanPublishNow()) {
            showToast("Cần biến thể đầy đủ, Safety Score đạt và nền tảng đã kết nối.");
            return;
        }
        await composeSaveBeforeAction();
        const selected = composeSelectedChannels().filter(channelSupportsAutoPublish);
        for (let i = 0; i < selected.length; i++) {
            const ch = selected[i];
            const ready = channelReadyForPublish(ch);
            if (!ready.ok || ready.manual) { showToast(ready.msg || "Kênh không hỗ trợ đăng tự động."); return; }
            const v = readComposeVariantFromDom(ch.id);
            if (!v || !v.postId) continue;
            if (ch.type === "facebook") {
                await api("PATCH", "/posts/" + v.postId, {
                    title: v.post.title, content: v.post.content,
                    hashtags: v.post.hashtags, cta: v.post.cta,
                    page_id: state.compose.accountMap[ch.id] || null,
                });
                await api("POST", "/posts/" + v.postId + "/publish-now");
            } else {
                state.web20.currentPostId = v.postId;
                state.web20.platform = ch.platform || ch.id;
                fillWeb20Form(v.post);
                await web20PublishNow();
            }
        }
        showToast("Đã đăng ngay.");
        loadResults();
    }

    async function composeRunSafety() {
        const chId = state.compose.activeChannel;
        const ch = COMPOSE_CHANNELS.find(function (x) { return x.id === chId; });
        if (!ch) { showToast("Chọn kênh trong accordion."); return; }
        const v = readComposeVariantFromDom(chId);
        if (!v || !v.post) { showToast("Chưa có biến thể."); return; }
        if (ch.type === "facebook") {
            const fp = formPayload();
            const data = await api("POST", "/safety/check", {
                title: v.post.title, content: v.post.content, hashtags: v.post.hashtags,
                keyword: fp.keyword, source_content: fp.source_content, source_title: fp.source_title,
                page_id: state.compose.accountMap[chId] || null, post_id: v.postId,
            });
            v.safety = data;
            state.compose.variants[chId] = v;
            renderComposeSafety(data);
            renderSafetyInline(data);
            showToast("FB Safety: " + (data.score != null ? data.score : "ok"));
        } else {
            const data = await apiWeb20("POST", "/safety/check", {
                title: v.post.title, html_content: v.post.html_content,
                account_id: state.compose.accountMap[chId] || "",
                main_site_url: ($("saUrl") && $("saUrl").value.trim()) || "",
                source_content: ($("saSourceContent") && $("saSourceContent").value) || "",
                post_id: v.postId,
            });
            v.safety = data.safety;
            state.compose.variants[chId] = v;
            renderComposeSafety(data.safety);
            showToast("Web 2.0 Safety: " + (data.safety && data.safety.score));
        }
        renderComposeVariantsAccordion();
        setComposeActiveChannel(chId);
    }

    function web20PlatformMeta(pf) {
        const items = web20AccountsForPlatform(pf);
        const n = items.length;
        const plat = (state.web20.platforms || []).find(function (x) { return x.id === pf; });
        const statusLabel = plat && plat.card_status_label ? plat.card_status_label : "";
        if (pf === "google_sites_manual") return statusLabel + (n ? " · " + n + " profile" : " · Manual");
        if (pf === "zalo_oa") return "Coming soon";
        if (!n) return statusLabel || (plat && plat.oauth_mode === "mock" ? "Mock mode" : "Chưa kết nối");
        if (plat && plat.oauth_mode === "mock") return statusLabel + " · Mock · " + n + " site";
        return (statusLabel || "Connected") + " · " + n + " site";
    }

    function switchWeb20EditorTab(tab) {
        state.web20.editorTab = tab || "source";
        document.querySelectorAll(".sa-web20-editor-tab").forEach(function (btn) {
            btn.classList.toggle("is-active", btn.getAttribute("data-tab") === state.web20.editorTab);
        });
        document.querySelectorAll(".sa-web20-editor-panel").forEach(function (panel) {
            const on = panel.getAttribute("data-panel") === state.web20.editorTab;
            panel.hidden = !on;
            panel.classList.toggle("is-active", on);
        });
    }

    function updateWeb20Stepper() {
        const f = readWeb20Form();
        const hasAcc = !!f.account_id;
        const hasSource = !!(f.source_title && f.source_content);
        const hasWeb20 = !!(f.title && f.html_content && f.html_content.length > 40);
        const safetyOk = state.web20.lastSafety && state.web20.lastSafety.can_publish;
        const steps = document.querySelectorAll(".sa-web20-step");
        if (!steps.length) return;
        let active = 1;
        if (hasAcc) active = 2;
        if (hasAcc && hasSource) active = 3;
        if (hasAcc && hasWeb20) active = 4;
        if (hasAcc && hasWeb20 && safetyOk) active = 5;
        steps.forEach(function (step) {
            const n = parseInt(step.getAttribute("data-step"), 10);
            step.classList.toggle("is-active", n === active);
            step.classList.toggle("is-done", n < active);
        });
    }

    function web20CanPublishNow() {
        const f = readWeb20Form();
        const acc = selectedWeb20Account();
        const pf = state.web20.platform || "wordpress_2_0";
        if (!f.account_id || !f.title || !f.html_content) return false;
        if (!state.web20.lastSafety || !state.web20.lastSafety.can_publish) return false;
        if (pf === "google_sites_manual" || pf === "zalo_oa") return false;
        const plat = (state.web20.platforms || []).find(function (x) { return x.id === pf; });
        if (plat && plat.supports_auto_publish === false) return false;
        if (pf === "medium" && !(acc && acc.has_credentials)) return false;
        if (acc && (acc.card_status === "token_expired" || acc.card_status === "need_setup")) return false;
        if (acc && acc.connection_mode === "error") return false;
        return true;
    }

    function updateWeb20ActionButtons() {
        const draftBtn = $("saW20PublishBtn");
        const nowBtn = $("saW20PublishNowBtn");
        const nowMob = $("saW20PublishNowBtnMobile");
        const pf = state.web20.platform || "wordpress_2_0";
        const acc = selectedWeb20Account();
        const f = readWeb20Form();
        const canDraft = !!(f.account_id && f.title && f.html_content);
        const canNow = web20CanPublishNow();

        if (draftBtn) {
            if (pf === "google_sites_manual") {
                draftBtn.textContent = "Tạo Manual Package";
                draftBtn.disabled = !canDraft;
            } else if (pf === "medium") {
                draftBtn.textContent = "Đăng draft (Beta)";
                draftBtn.disabled = !canDraft || !(acc && acc.has_credentials) || (acc && acc.card_status === "token_expired");
            } else {
                draftBtn.textContent = "Đăng draft";
                draftBtn.disabled = !canDraft || !!(acc && (acc.connection_mode === "error" || acc.card_status === "token_expired"));
            }
        }
        if (nowBtn) {
            nowBtn.hidden = pf === "google_sites_manual" || pf === "zalo_oa";
            nowBtn.disabled = !canNow;
        }
        if (nowMob) {
            nowMob.hidden = pf === "google_sites_manual" || pf === "zalo_oa";
            nowMob.disabled = !canNow;
        }

        const statusEl = $("saWeb20AccountStatus");
        if (statusEl) {
            if (!acc) {
                statusEl.textContent = "";
                statusEl.className = "sa-web20-account-status";
            } else if (acc.card_status === "token_expired") {
                statusEl.textContent = "Token hết hạn — kết nối lại nền tảng";
                statusEl.className = "sa-web20-account-status is-error";
            } else if (acc.connection_mode === "error" || acc.status === "error") {
                statusEl.textContent = "Kết nối lỗi — chạy Test hoặc kết nối lại";
                statusEl.className = "sa-web20-account-status is-error";
            } else if (acc.connection_mode === "mock") {
                statusEl.textContent = "Mock mode — không gọi API thật";
                statusEl.className = "sa-web20-account-status";
            } else {
                statusEl.textContent = "Kết nối thành công";
                statusEl.className = "sa-web20-account-status";
            }
        }

        const platBadge = $("saWeb20PreviewPlatform");
        if (platBadge) {
            const plat = (state.web20.platforms || []).find(function (x) { return x.id === pf; });
            platBadge.textContent = WEB20_PLATFORM_LABELS[pf] || pf;
            const st = (acc && acc.card_status) || (plat && plat.card_status) || "draft";
            platBadge.className = "sa-w20-badge sa-w20-badge--" + st;
        }

        document.querySelectorAll(".sa-web20-wp-only").forEach(function (el) {
            el.hidden = pf !== "wordpress_2_0";
        });
        updateWeb20Stepper();
    }

    function web20AccountsForPlatform(pf) {
        const platform = pf || state.web20.platform || "wordpress_2_0";
        return (state.web20.accounts || []).filter(function (a) {
            return (a.platform || "wordpress_2_0") === platform;
        });
    }

    function renderWeb20Preview() {
        const el = $("saW20Preview");
        const tagsEl = $("saW20PreviewTags");
        const title = ($("saW20Title") && $("saW20Title").value.trim()) || "";
        const html = ($("saW20Html") && $("saW20Html").value) || "";
        const tags = (($("saW20Tags") && $("saW20Tags").value) || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean);
        if (!el) return;
        if (!html.trim() && !title) {
            el.innerHTML = '<p class="sa-empty">Nhập HTML để xem preview.</p>';
            if (tagsEl) tagsEl.innerHTML = "";
            return;
        }
        el.innerHTML = (title ? "<h3>" + esc(title) + "</h3>" : "") + html;
        if (tagsEl) {
            tagsEl.innerHTML = tags.slice(0, 6).map(function (t) {
                return "<span>" + esc(t) + "</span>";
            }).join("");
        }
        updateWeb20ActionButtons();
    }

    function renderWeb20ManualPanel(pkg) {
        const panel = $("saW20ManualPanel");
        const list = $("saW20Checklist");
        const ta = $("saW20ManualHtml");
        state.web20.manualPackage = pkg || null;
        const isManual = state.web20.platform === "google_sites_manual";
        if (!panel) return;
        if (!isManual && !pkg) {
            panel.hidden = true;
            return;
        }
        panel.hidden = false;
        if (pkg && list) {
            list.innerHTML = (pkg.checklist || []).map(function (c) {
                return "<li>" + esc(c) + "</li>";
            }).join("");
        }
        const setVal = function (id, val) {
            const el = $(id);
            if (el) el.value = val || "";
        };
        if (pkg) {
            setVal("saW20ManualTitle", pkg.title);
            setVal("saW20ManualSlug", pkg.slug);
            setVal("saW20ManualExcerpt", pkg.excerpt);
            setVal("saW20ManualImagePrompt", pkg.image_prompt);
            setVal("saW20ManualCta", pkg.cta);
            if (ta) ta.value = pkg.html || "";
        } else if (ta) {
            ta.value = ($("saW20Html") && $("saW20Html").value) || "";
        }
    }

    function web20StatusBadge(st) {
        const s = String(st || "draft").toLowerCase();
        return '<span class="sa-w20-badge sa-w20-badge--' + esc(s) + '">' + esc(s) + "</span>";
    }

    function web20ConnBadge(a) {
        const st = a.card_status || a.connection_mode || a.status || "connected";
        const label = CARD_STATUS_LABELS[st] || st;
        return '<span class="sa-platform-status sa-platform-status--' + esc(st) + '">' + esc(label) + "</span>";
    }

    function selectedWeb20Account() {
        const id = ($("saW20Account") && $("saW20Account").value) || "";
        return (state.web20.accounts || []).find(function (x) { return x.id === id; }) || null;
    }

    function renderWeb20PlatformCards() {
        const items = state.web20.platforms.length
            ? state.web20.platforms
            : Object.keys(WEB20_PLATFORM_LABELS).map(function (id) {
                return { id: id, label: WEB20_PLATFORM_LABELS[id] };
            });
        const html = items.map(function (p) {
            const active = p.id === state.web20.platform ? " is-active" : "";
            const label = WEB20_PLATFORM_LABELS[p.id] || p.label || p.id;
            const check = active ? '<span class="sa-web20-pcard__check" aria-hidden="true">✓</span>' : "";
            const status = p.card_status || "need_setup";
            const badge = platformCardStatusBadge(status);
            const meta = p.id === "zalo_oa" ? "Coming soon" : esc(web20PlatformMeta(p.id));
            return '<button type="button" class="sa-web20-pcard' + active + '" data-sa-action="web20-switch-platform" data-platform="' + esc(p.id) + '"' +
                (p.id === "zalo_oa" ? " disabled" : "") + '>' +
                check +
                '<span class="sa-web20-pcard__icon">' + esc(WEB20_PLATFORM_ICONS[p.id] || "?") + '</span>' +
                '<span class="sa-web20-pcard__name">' + esc(label) + " " + badge + '</span>' +
                '<span class="sa-web20-pcard__meta">' + meta + "</span></button>";
        }).join("");
        ["saWeb20PlatformCards", "saWeb20PlatformPicker"].forEach(function (id) {
            const el = $(id);
            if (el) el.innerHTML = html;
        });
    }

    function renderWeb20PlatformTabs() {
        renderWeb20PlatformCards();
    }

    function renderWeb20ConnectPanel() {
        const el = $("saWeb20ConnectPanel");
        if (!el) return;
        const pf = state.web20.platform || "wordpress_2_0";
        if (pf === "wordpress_2_0") {
            el.innerHTML =
                '<details class="sa-web20-add" open>' +
                '<summary>+ Thêm WordPress vệ tinh</summary>' +
                '<div class="sa-web20-connect-fields">' +
                '<div class="sa-field"><label>Nhãn</label><input type="text" id="saW20Label" autocomplete="off"></div>' +
                '<div class="sa-field"><label>Trạng thái mặc định</label><select id="saW20DefaultStatus"><option value="draft" selected>Draft</option><option value="pending">Pending</option><option value="private">Private</option><option value="publish">Publish</option></select></div>' +
                '<div class="sa-field sa-field--full"><label>Site URL</label><input type="url" id="saW20Url" placeholder="https://blog-phu.example.com" autocomplete="off"></div>' +
                '<div class="sa-field"><label>Username</label><input type="text" id="saW20User" autocomplete="off"></div>' +
                '<div class="sa-field"><label>Application Password</label><input type="password" id="saW20Pass" autocomplete="new-password"></div>' +
                '<div class="sa-field sa-field--full"><button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="web20-add-account">Kết nối &amp; lưu</button></div>' +
                "</div></details>";
        } else if (pf === "blogger") {
            el.innerHTML = '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="web20-oauth-blogger">Kết nối Google OAuth (Blogger)</button>';
        } else if (pf === "tumblr") {
            el.innerHTML = '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="web20-oauth-tumblr">Kết nối Tumblr OAuth</button>';
        } else if (pf === "medium") {
            el.innerHTML =
                '<p class="sa-hint">Medium (Beta) — dùng Integration Token tại medium.com/settings/security.</p>' +
                '<div class="sa-field"><label>Integration token</label><input type="password" id="saW20MediumToken" autocomplete="off"></div>' +
                '<div class="sa-field"><label>Nhãn</label><input type="text" id="saW20MediumLabel" autocomplete="off"></div>' +
                '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="web20-connect-medium">Lưu token Medium</button>';
        } else if (pf === "google_sites_manual") {
            el.innerHTML =
                '<div class="sa-field"><label>Nhãn site</label><input type="text" id="saW20ManualLabel" value="Google Sites Manual" autocomplete="off"></div>' +
                '<div class="sa-field"><label>URL Google Site (tuỳ chọn)</label><input type="url" id="saW20ManualSiteUrl" autocomplete="off"></div>' +
                '<button type="button" class="sa-btn sa-btn--primary sa-btn--sm" data-sa-action="web20-add-manual">Thêm profile manual</button>' +
                '<p class="sa-hint">Manual Package — copy thủ công, không đăng tự động.</p>';
        } else if (pf === "zalo_oa") {
            el.innerHTML = '<p class="sa-hint">Zalo OA đang <strong>Coming soon</strong> — chưa có publish API hoàn chỉnh.</p>';
        } else {
            el.innerHTML = "";
        }
    }

    function renderWeb20Accounts() {
        const list = $("saWeb20AccountsList");
        const sel = $("saW20Account");
        const items = web20AccountsForPlatform();
        if (list) {
            if (!items.length) {
                list.innerHTML = '<p class="sa-empty">Chưa có tài khoản cho nền tảng này.</p>';
            } else {
                list.innerHTML = items.map(function (a) {
                    let blogSelect = "";
                    if ((a.blogs || []).length > 1) {
                        blogSelect = '<select class="sa-web20-blog-select" data-sa-action="web20-select-blog" data-account-id="' + esc(a.id) + '">' +
                            (a.blogs || []).map(function (b) {
                                const selOpt = String(b.id) === String(a.external_id) ? " selected" : "";
                                return '<option value="' + esc(b.id) + '"' + selOpt + ">" + esc(b.name || b.id) + "</option>";
                            }).join("") + "</select>";
                    }
                    return '<div class="sa-mini-row">' +
                        '<strong>' + esc(a.label || a.site_url || a.platform) + web20ConnBadge(a) + '</strong>' +
                        '<span class="sa-meta">' + esc(a.platform || "") + (a.site_url ? " · " + esc(a.site_url) : "") +
                        (a.last_test_message ? " · " + esc(a.last_test_message) : "") + '</span>' +
                        blogSelect +
                        '<div class="sa-btn-row">' +
                        '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="web20-test-account" data-account-id="' + esc(a.id) + '">Test</button>' +
                        '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="web20-del-account" data-account-id="' + esc(a.id) + '">Xóa</button>' +
                        "</div></div>";
                }).join("");
            }
        }
        if (sel) {
            const cur = sel.value;
            sel.innerHTML = '<option value="">— Chọn tài khoản —</option>' +
                items.map(function (a) {
                    return '<option value="' + esc(a.id) + '">' + esc(a.label || a.site_url || a.platform) + "</option>";
                }).join("");
            if (cur && items.some(function (x) { return x.id === cur; })) sel.value = cur;
            else if (items.length === 1) sel.value = items[0].id;
        }
        updateWeb20ActionButtons();
    }

    function ensureDialogOnBody(dlg) {
        if (!dlg || !dlg.parentElement) return dlg;
        // Nested under a [hidden] tabpanel makes showModal() inert the page while dialog stays invisible.
        if (dlg.closest("[hidden]") && dlg.parentElement !== document.body) {
            document.body.appendChild(dlg);
        }
        return dlg;
    }

    function openWeb20ConnectModal() {
        renderWeb20PlatformCards();
        renderWeb20ConnectPanel();
        const dlg = ensureDialogOnBody($("saWeb20ConnectModal"));
        if (dlg && typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
    }

    function openWeb20AccountsModal() {
        renderWeb20Accounts();
        const dlg = ensureDialogOnBody($("saWeb20AccountsModal"));
        if (dlg && typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
    }

    function renderWeb20Posts() {
        const list = $("saWeb20PostsList");
        const items = state.web20.posts || [];
        if (!list) return;
        if (!items.length) {
            list.innerHTML = '<p class="sa-empty">Chưa có bài.</p>';
            return;
        }
        list.innerHTML = items.slice(0, 20).map(function (p) {
            const retryBtn = (p.status === "failed" || p.status === "retrying")
                ? '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="web20-retry-post" data-post-id="' + esc(p.id) + '">Retry</button>'
                : "";
            const sched = p.scheduled_at ? '<span class="sa-meta"> · lịch: ' + esc(String(p.scheduled_at).replace("T", " ").slice(0, 16)) + "</span>" : "";
            const err = p.error_message ? '<span class="sa-meta is-error"> · ' + esc(String(p.error_message).slice(0, 80)) + "</span>" : "";
            return '<div class="sa-mini-row">' +
                '<strong>' + esc(p.title || "(không tiêu đề)") + web20StatusBadge(p.status) + '</strong>' +
                '<span class="sa-meta">score ' + esc(p.safety_score != null ? p.safety_score : "—") +
                (p.retry_count ? " · retry " + esc(p.retry_count) : "") + sched + err + "</span>" +
                '<div class="sa-btn-row">' +
                '<button type="button" class="sa-btn sa-btn--ghost sa-btn--sm" data-sa-action="web20-load-post" data-post-id="' + esc(p.id) + '">Mở</button>' +
                retryBtn +
                (p.published_url ? '<a class="sa-btn sa-btn--ghost sa-btn--sm" href="' + esc(p.published_url) + '" target="_blank" rel="noopener">Xem</a>' : "") +
                "</div></div>";
        }).join("");
    }

    function renderWeb20Logs(items) {
        const el = $("saWeb20Logs");
        if (!el) return;
        if (!items || !items.length) {
            el.innerHTML = '<p class="sa-empty">Chưa có log.</p>';
            return;
        }
        el.innerHTML = '<table class="sa-log-table"><thead><tr><th>Thời gian</th><th>Mức</th><th>Mã</th><th>Nội dung</th></tr></thead><tbody>' +
            items.slice(0, 40).map(function (l) {
                const cls = l.level === "error" ? " class=\"is-error\"" : "";
                return "<tr" + cls + "><td>" + esc((l.at || "").replace("T", " ").slice(0, 19)) +
                    "</td><td>" + esc(l.level || "") + "</td><td>" + esc(l.code || "") +
                    "</td><td>" + esc(l.message || "") + "</td></tr>";
            }).join("") + "</tbody></table>";
    }

    async function loadWeb20Tab() {
        const [plat, acc, posts, logs, settings] = await Promise.all([
            apiWeb20("GET", "/platforms"),
            apiWeb20("GET", "/accounts"),
            apiWeb20("GET", "/posts"),
            apiWeb20("GET", "/logs?limit=30"),
            apiWeb20("GET", "/settings").catch(function () { return { settings: {} }; }),
        ]);
        state.web20.platforms = plat.items || [];
        state.web20.accounts = acc.items || [];
        state.web20.posts = posts.items || [];
        state.web20.settings = (settings && settings.settings) || {};
        if ($("saW20MaxPerDay") && state.web20.settings.max_posts_per_account_per_day) {
            $("saW20MaxPerDay").value = state.web20.settings.max_posts_per_account_per_day;
        }
        const tk = todayKey();
        state.fbPostsToday = (await api("GET", "/posts?platform=facebook").catch(function () { return { items: [] }; })).items || [];
        state.fbPostsToday = state.fbPostsToday.filter(function (p) {
            const at = p.published_at || p.scheduled_at || p.updated_at;
            return at && new Date(at).toDateString() === tk && ["published", "scheduled"].indexOf(p.status) >= 0;
        });
        renderWeb20PlatformCards();
        renderWeb20ConnectPanel();
        renderWeb20Accounts();
        renderWeb20Posts();
        renderWeb20Logs(logs.items || []);
        renderWeb20Preview();
        switchWeb20EditorTab(state.web20.editorTab || "source");
        updateWeb20ActionButtons();
    }

    async function web20Generate() {
        const f = readWeb20Form();
        if (!f.account_id) { showToast("Chọn tài khoản Web 2.0."); return; }
        if (!f.source_title) { showToast("Cần tiêu đề bài gốc."); return; }
        const toneEl = $("saW20Tone");
        const data = await apiWeb20("POST", "/generate", {
            account_id: f.account_id,
            source_title: f.source_title,
            source_content: f.source_content,
            keyword: f.keyword,
            target_url: f.main_site_url,
            main_site_url: f.main_site_url,
            tone: (toneEl && toneEl.value) || "chuyên gia",
        });
        fillWeb20Form(data.item);
        renderWeb20Safety(data.safety);
        switchWeb20EditorTab("web20");
        renderWeb20Preview();
        await loadWeb20Tab();
        showToast("Đã tạo phiên bản Web 2.0 (draft).");
    }

    async function web20SaveDraft() {
        const f = readWeb20Form();
        if (!f.account_id) { showToast("Chọn site."); return; }
        if (state.web20.currentPostId) {
            await apiWeb20("PATCH", "/posts/" + encodeURIComponent(state.web20.currentPostId), f);
        } else {
            const data = await apiWeb20("POST", "/posts", f);
            state.web20.currentPostId = data.item && data.item.id;
            fillWeb20Form(data.item);
            renderWeb20Safety(data.item.safety);
        }
        await loadWeb20Tab();
        showToast("Đã lưu nháp Web 2.0.");
    }

    async function web20Schedule() {
        const pf = state.web20.platform || "wordpress_2_0";
        const acc = selectedWeb20Account();
        if (pf === "google_sites_manual" || pf === "zalo_oa") {
            showToast("Nền tảng này không hỗ trợ lên lịch tự động.");
            return;
        }
        if (acc && (acc.card_status === "need_setup" || acc.card_status === "token_expired")) {
            showToast("Kết nối lại nền tảng trước khi lên lịch.");
            return;
        }
        if (!state.web20.currentPostId) {
            await web20SaveDraft();
        }
        if (!state.web20.currentPostId) return;
        const when = ($("saW20ScheduleInput") && $("saW20ScheduleInput").value) || "";
        if (!when) { showToast("Chọn ngày giờ lên lịch."); return; }
        const iso = new Date(when).toISOString();
        if ($("saW20ScheduledAt")) $("saW20ScheduledAt").value = iso;
        const data = await apiWeb20("POST", "/posts/" + encodeURIComponent(state.web20.currentPostId) + "/schedule", {
            scheduled_at: iso,
        });
        fillWeb20Form(data.item);
        renderWeb20Safety(data.safety);
        await loadWeb20Tab();
        showToast("Đã lên lịch đăng tự động.");
    }

    async function web20RetryPost(postId) {
        const data = await apiWeb20("POST", "/posts/" + encodeURIComponent(postId) + "/retry");
        if (state.web20.currentPostId === postId) fillWeb20Form(data.item);
        await loadWeb20Tab();
        showToast("Retry publish — " + (data.item && data.item.status || "ok"));
    }

    async function web20Publish() {
        if ($("saW20Status")) $("saW20Status").value = "draft";
        if (!state.web20.currentPostId) {
            await web20SaveDraft();
        }
        if (!state.web20.currentPostId) return;
        const data = await apiWeb20("POST", "/posts/" + encodeURIComponent(state.web20.currentPostId) + "/publish");
        fillWeb20Form(data.item);
        renderWeb20Safety(data.safety);
        if (data.result && data.result.manual_package) {
            renderWeb20ManualPanel(data.result.manual_package);
        }
        await loadWeb20Tab();
        const pf = state.web20.platform || "";
        if (pf === "google_sites_manual") {
            showToast("Đã tạo gói copy — dán thủ công lên Google Sites.");
        } else {
            showToast("Đã đăng draft lên " + (WEB20_PLATFORM_LABELS[pf] || pf) + ".");
        }
    }

    async function web20PublishNow() {
        if (!web20CanPublishNow()) {
            showToast("Cần account đã kết nối, nội dung và Safety Score ≥ 70.");
            return;
        }
        const acc = selectedWeb20Account();
        if (acc && acc.card_status === "token_expired") {
            showToast("Token hết hạn — kết nối lại trước khi đăng.");
            return;
        }
        if ($("saW20Status")) $("saW20Status").value = "publish";
        if (!state.web20.currentPostId) await web20SaveDraft();
        if (!state.web20.currentPostId) return;
        await apiWeb20("PATCH", "/posts/" + encodeURIComponent(state.web20.currentPostId), { wp_status: "publish" });
        const data = await apiWeb20("POST", "/posts/" + encodeURIComponent(state.web20.currentPostId) + "/publish");
        fillWeb20Form(data.item);
        renderWeb20Safety(data.safety);
        await loadWeb20Tab();
        showToast("Đã đăng ngay (publish).");
    }

    function bindEvents() {
        document.querySelectorAll(".sa-tab").forEach(function (btn) {
            btn.addEventListener("click", function () { switchTab(btn.getAttribute("data-sa-tab")); });
        });

        const campSel = $("saCampaignSelect");
        if (campSel) {
            campSel.addEventListener("change", async function () {
                state.campaignId = campSel.value;
                const c = state.campaigns.find(function (x) { return x.id === state.campaignId; });
                if (c) {
                    if ($("saCampaignName")) $("saCampaignName").value = c.name || "";
                    if ($("saTitle")) $("saTitle").value = c.source_title || "";
                    if ($("saSourceContent")) $("saSourceContent").value = c.source_content || "";
                    if ($("saKeyword")) $("saKeyword").value = c.keyword || "";
                    if ($("saUrl")) $("saUrl").value = c.target_url || "";
                }
                try { await loadCampaignPost(state.campaignId); } catch (e) { if (e.message !== "unauthorized") showToast(e.message); }
                syncComposeSourceToWeb20();
                updateComposeStepper();
            });
        }

        ["saScheduleFilter", "saResultsFilter"].forEach(function (id) {
            const el = $(id);
            if (el) {
                el.addEventListener("change", function () {
                    if (id === "saScheduleFilter") loadSchedule();
                    else loadResults();
                });
            }
        });

        document.querySelectorAll("#saScheduleStatusPills .sa-pill").forEach(function (pill) {
            pill.addEventListener("click", function () {
                document.querySelectorAll("#saScheduleStatusPills .sa-pill").forEach(function (p) {
                    p.classList.toggle("is-active", p === pill);
                });
                const st = pill.getAttribute("data-status") || "scheduled";
                if ($("saScheduleStatusFilter")) $("saScheduleStatusFilter").value = st;
                loadSchedule();
            });
        });

        const pageSel = $("saActivePage");
        if (pageSel) {
            pageSel.addEventListener("change", async function () {
                const pid = pageSel.value;
                if (!pid) return;
                try {
                    await api("POST", "/facebook/pages/" + encodeURIComponent(pid) + "/activate");
                    await loadOverview();
                } catch (e) { showToast(e.message); }
            });
        }

        document.addEventListener("change", async function (e) {
            const sel = e.target.closest("[data-sa-action=\"web20-select-blog\"]");
            if (sel) {
                const aid = sel.getAttribute("data-account-id");
                const blogId = sel.value;
                try {
                    await apiWeb20("PATCH", "/accounts/" + encodeURIComponent(aid), { external_id: blogId });
                    await loadWeb20Tab();
                } catch (err) {
                    if (err.message !== "unauthorized") showToast(err.message);
                }
                return;
            }
            if (e.target && e.target.closest("[data-sa-action=\"compose-toggle-channel\"]")) {
                const toggleEl = e.target.closest("[data-sa-action=\"compose-toggle-channel\"]");
                const chId = toggleEl.getAttribute("data-channel");
                const chMeta = COMPOSE_CHANNELS.find(function (x) { return x.id === chId; });
                if (chMeta && chMeta.comingSoon) {
                    showToast("Zalo OA đang Coming soon — chưa hỗ trợ đăng tự động.");
                    return;
                }
                state.compose.selected[chId] = !state.compose.selected[chId];
                if (!state.compose.selected[chId]) delete state.compose.accountMap[chId];
                renderComposeChannelCards();
                renderComposeVariantsAccordion();
                return;
            }
            const accSel = e.target.closest("[data-sa-action=\"compose-account\"]");
            if (accSel) {
                const chId = accSel.getAttribute("data-channel");
                state.compose.accountMap[chId] = accSel.value;
                if (chId === "facebook" && $("saActivePage")) $("saActivePage").value = accSel.value;
                renderComposeChannelCards();
                updateComposeStepper();
                return;
            }
            if (e.target && e.target.id === "saW20Account") {
                updateWeb20ActionButtons();
                return;
            }
            const web20Inputs = ["saW20SourceTitle", "saW20SourceContent", "saW20Title", "saW20Html", "saW20MainUrl", "saW20Keyword"];
            if (e.target && web20Inputs.indexOf(e.target.id) >= 0) {
                if (e.target.id === "saW20SourceTitle") {
                    const c = $("saW20SourceTitleCount");
                    if (c) c.textContent = (e.target.value.length || 0) + "/500";
                }
                if (e.target.id === "saW20Html") renderWeb20Preview();
                updateWeb20Stepper();
                updateWeb20ActionButtons();
            }
        });

        document.addEventListener("input", function (e) {
            if (!e.target) return;
            if (e.target.id === "saTitle" || e.target.id === "saSourceContent" || e.target.id === "saKeyword" || e.target.id === "saUrl") {
                syncComposeSourceToWeb20();
                updateComposeStepper();
            }
            if (e.target.id === "saTitle") {
                const c = $("saSourceTitleCount");
                if (c) c.textContent = (e.target.value.length || 0) + "/500";
            }
            if (e.target.getAttribute && e.target.getAttribute("data-compose-field")) {
                const chId = e.target.getAttribute("data-channel");
                if (chId) readComposeVariantFromDom(chId);
                renderComposePreview();
                updateComposeActionButtons();
            }
            if (e.target.id === "saW20Html" || e.target.id === "saW20Title" || e.target.id === "saW20Tags") {
                renderWeb20Preview();
            }
            if (e.target.id === "saW20SourceTitle") {
                const c = $("saW20SourceTitleCount");
                if (c) c.textContent = (e.target.value.length || 0) + "/500";
            }
            updateWeb20Stepper();
            updateWeb20ActionButtons();
        });

        document.addEventListener("click", async function (e) {
            const t = e.target.closest("[data-sa-action], [data-sa-load-campaign]");
            if (!t) return;
            const loadId = t.getAttribute("data-sa-load-campaign");
            if (loadId) {
                e.preventDefault();
                state.campaignId = loadId;
                const c = state.campaigns.find(function (x) { return x.id === loadId; });
                if (c) {
                    if ($("saCampaignName")) $("saCampaignName").value = c.name || "";
                    if ($("saTitle")) $("saTitle").value = c.source_title || "";
                    if ($("saSourceContent")) $("saSourceContent").value = c.source_content || "";
                    if ($("saKeyword")) $("saKeyword").value = c.keyword || "";
                    if ($("saUrl")) $("saUrl").value = c.target_url || "";
                }
                renderCampaignSelect();
                switchTab("compose");
                try { await loadCampaignPost(loadId); } catch (err) { showToast(err.message); }
                return;
            }

            const action = t.getAttribute("data-sa-action");
            if (!action) return;
            e.preventDefault();
            try {
                if (action === "new-campaign") {
                    state.campaignId = "";
                    state.currentPost = null;
                    state.compose.variants = {};
                    ["saCampaignName", "saTitle", "saSourceContent", "saKeyword", "saUrl", "saCta"].forEach(function (id) {
                        const el = $(id); if (el) el.value = "";
                    });
                    fillVariantForm(null);
                    renderCampaignSelect();
                    switchTab("compose");
                    renderComposeVariantsAccordion();
                    return;
                }
                if (action === "goto-compose") { switchTab("compose"); return; }
                if (action === "compose-generate") { await composeGenerateAll(); return; }
                if (action === "compose-save") { await composeSaveAll(); return; }
                if (action === "compose-schedule") { await composeScheduleAll(); return; }
                if (action === "compose-publish") { await composePublishAll(); return; }
                if (action === "compose-publish-now") { await composePublishNowAll(); return; }
                if (action === "compose-safety") { await composeRunSafety(); return; }
                if (action === "compose-open-variant") {
                    setComposeActiveChannel(t.getAttribute("data-channel"));
                    renderComposeVariantsAccordion();
                    return;
                }
                if (action === "save-web20-safety") {
                    await apiWeb20("PATCH", "/settings", {
                        max_posts_per_account_per_day: parseInt($("saW20MaxPerDay").value, 10) || 3,
                        default_wp_status: ($("saW20DefaultStatus") && $("saW20DefaultStatus").value) || "draft",
                    });
                    showToast("Đã lưu cài đặt Web 2.0.");
                    return;
                }
                if (action === "cancel-schedule-item") {
                    const kind = t.getAttribute("data-kind");
                    const pid = t.getAttribute("data-post-id");
                    if (kind === "web20") {
                        await apiWeb20("POST", "/posts/" + encodeURIComponent(pid) + "/cancel-schedule");
                    } else {
                        await api("POST", "/posts/" + pid + "/cancel-schedule");
                    }
                    showToast("Đã hủy lịch.");
                    loadSchedule();
                    loadOverview();
                    return;
                }
                if (action === "schedule-publish-now") {
                    const kind = t.getAttribute("data-kind");
                    const pid = t.getAttribute("data-post-id");
                    if (kind === "web20") {
                        await apiWeb20("PATCH", "/posts/" + encodeURIComponent(pid), { wp_status: "publish" });
                        await apiWeb20("POST", "/posts/" + encodeURIComponent(pid) + "/publish");
                    } else {
                        await api("POST", "/posts/" + pid + "/publish-now");
                    }
                    showToast("Đã publish ngay.");
                    invalidateSaTabs(["schedule", "results", "overview"]);
                    loadSchedule();
                    loadResults();
                    return;
                }
                if (action === "schedule-retry") {
                    const pid = t.getAttribute("data-post-id");
                    await apiWeb20("POST", "/posts/" + encodeURIComponent(pid) + "/retry");
                    showToast("Đang retry publish…");
                    loadSchedule();
                    loadResults();
                    return;
                }
                if (action === "platform-test") {
                    const chId = t.getAttribute("data-channel");
                    const ch = COMPOSE_CHANNELS.find(function (x) { return x.id === chId; });
                    const accId = state.compose.accountMap[chId];
                    if (!ch || !accId) { showToast("Chọn tài khoản trước khi Test."); return; }
                    const r = await apiWeb20("POST", "/accounts/" + encodeURIComponent(accId) + "/test");
                    showToast(r.message || (r.ok ? "Kết nối OK" : "Lỗi kết nối"));
                    await loadWeb20Tab();
                    renderComposeChannelCards();
                    return;
                }
                if (action === "edit-schedule-item") {
                    const kind = t.getAttribute("data-kind");
                    const pid = t.getAttribute("data-post-id");
                    const when = promptDateTime();
                    if (!when) return;
                    if (kind === "web20") {
                        await apiWeb20("POST", "/posts/" + encodeURIComponent(pid) + "/schedule", { scheduled_at: when });
                    } else {
                        await api("POST", "/posts/" + pid + "/schedule", { scheduled_at: when });
                    }
                    showToast("Đã cập nhật lịch.");
                    loadSchedule();
                    return;
                }
                if (action === "preview-scheduled") {
                    const kind = t.getAttribute("data-kind");
                    const pid = t.getAttribute("data-post-id");
                    if (kind === "web20") {
                        const all = await apiWeb20("GET", "/posts");
                        const p = (all.items || []).find(function (x) { return x.id === pid; });
                        if (p) window.alert((p.title || "") + "\n\n" + (p.html_content || "").slice(0, 500));
                    } else {
                        const all = await api("GET", "/posts?platform=facebook");
                        const p = (all.items || []).find(function (x) { return x.id === pid; });
                        if (p) window.alert((p.title || "") + "\n\n" + (p.content || ""));
                    }
                    return;
                }
                if (action === "connect-fb") { await connectFacebook(); return; }
                if (action === "close-fb-setup") { closeFbOauthSetupModal(); return; }
                if (action === "save-fb-oauth-config") { await saveFbOauthConfig(); return; }
                if (action === "refresh-fb") { await loadOverview(); showToast("Đã làm mới."); return; }
                if (action === "generate") { await generateVariants(); return; }
                if (action === "save-draft") { await saveCurrentDraft(); return; }
                if (action === "approve") { await approveCurrent(); return; }
                if (action === "preview") { await previewCurrent(); return; }
                if (action === "schedule") { await scheduleCurrent(); return; }
                if (action === "run-safety") { await runSafetyCheck(); return; }
                if (action === "save-safety") {
                    await api("PATCH", "/safety/settings", {
                        max_posts_per_day: parseInt($("saMaxPerDay").value, 10) || 4,
                        min_hours_between_posts: parseInt($("saMinGap").value, 10) || 3,
                        auto_stop_on_rate_limit: $("saAutoRate").checked,
                        auto_stop_on_permission_error: $("saAutoPerm").checked,
                    });
                    await loadOverview();
                    showToast("Đã lưu cài đặt an toàn.");
                    return;
                }
                if (action === "clear-pause") {
                    await api("PATCH", "/safety/settings", { clear_pause: true });
                    await loadSafetyTab();
                    showToast("Đã bỏ tạm dừng.");
                    return;
                }
                if (action === "activate-page") {
                    await api("POST", "/facebook/pages/" + encodeURIComponent(t.getAttribute("data-page-id")) + "/activate");
                    await loadOverview();
                    return;
                }
                if (action === "disconnect-page") {
                    await api("DELETE", "/facebook/pages/" + encodeURIComponent(t.getAttribute("data-page-id")));
                    await loadOverview();
                    showToast("Đã ngắt kết nối Fanpage.");
                    return;
                }
                if (action === "cancel-schedule") {
                    await api("POST", "/posts/" + t.getAttribute("data-post-id") + "/cancel-schedule");
                    showToast("Đã hủy lịch.");
                    loadSchedule();
                    loadOverview();
                    return;
                }
                if (action === "edit-schedule") {
                    const when = promptDateTime();
                    if (!when) return;
                    await api("POST", "/posts/" + t.getAttribute("data-post-id") + "/schedule", { scheduled_at: when });
                    showToast("Đã cập nhật lịch.");
                    loadSchedule();
                    return;
                }
                if (action === "preview-post") {
                    const pid = t.getAttribute("data-post-id");
                    const all = await api("GET", "/posts?platform=facebook");
                    const p = (all.items || []).find(function (x) { return x.id === pid; });
                    if (p) window.alert((p.title || "") + "\n\n" + (p.content || "") + "\n\n" + (p.hashtags || ""));
                    return;
                }
                if (action === "mark-published") {
                    const url = window.prompt("URL bài đã đăng:", "https://");
                    if (!url) return;
                    await api("POST", "/posts/" + t.getAttribute("data-post-id") + "/mark-published", { published_url: url });
                    showToast("Đã cập nhật URL.");
                    loadResults();
                    loadOverview();
                    return;
                }
                if (action === "web20-switch-platform") {
                    const pf = t.getAttribute("data-platform") || "wordpress_2_0";
                    if (pf === "zalo_oa") {
                        showToast("Zalo OA đang Coming soon.");
                        return;
                    }
                    state.web20.platform = pf;
                    renderWeb20PlatformCards();
                    renderWeb20ConnectPanel();
                    renderWeb20Accounts();
                    renderWeb20ManualPanel(state.web20.platform === "google_sites_manual" ? state.web20.manualPackage : null);
                    updateWeb20ActionButtons();
                    return;
                }
                if (action === "web20-editor-tab") {
                    switchWeb20EditorTab(t.getAttribute("data-tab") || "source");
                    return;
                }
                if (action === "channel-guide") {
                    openConnectionGuideModal(t.getAttribute("data-channel") || "");
                    return;
                }
                if (action === "channel-guide-close") {
                    const guideDlg = $("saConnectionGuideModal");
                    if (guideDlg && guideDlg.close) guideDlg.close();
                    return;
                }
                if (action === "web20-open-connect") { openWeb20ConnectModal(); return; }
                if (action === "web20-close-connect") {
                    const dlg = $("saWeb20ConnectModal");
                    if (dlg && dlg.close) dlg.close();
                    return;
                }
                if (action === "web20-manage-accounts") { openWeb20AccountsModal(); return; }
                if (action === "web20-close-accounts") {
                    const dlg = $("saWeb20AccountsModal");
                    if (dlg && dlg.close) dlg.close();
                    return;
                }
                if (action === "web20-view-logs") {
                    const panel = $("saWeb20LogsPanel");
                    if (panel) {
                        panel.hidden = false;
                        panel.scrollIntoView({ behavior: "smooth", block: "start" });
                    }
                    return;
                }
                if (action === "web20-close-logs") {
                    const panel = $("saWeb20LogsPanel");
                    if (panel) panel.hidden = true;
                    return;
                }
                if (action === "web20-publish-now") { await web20PublishNow(); return; }
                if (action === "web20-oauth-blogger") {
                    const r = await apiWeb20("GET", "/blogger/oauth/start");
                    if (r.url) window.location.href = r.url;
                    return;
                }
                if (action === "web20-oauth-tumblr") {
                    const r = await apiWeb20("GET", "/tumblr/oauth/start");
                    if (r.url) window.location.href = r.url;
                    return;
                }
                if (action === "web20-connect-medium") {
                    const token = ($("saW20MediumToken") && $("saW20MediumToken").value.trim()) || "";
                    if (!token) { showToast("Cần integration token Medium."); return; }
                    await apiWeb20("POST", "/accounts/medium", {
                        integration_token: token,
                        label: ($("saW20MediumLabel") && $("saW20MediumLabel").value.trim()) || "",
                    });
                    await loadWeb20Tab();
                    showToast("Đã kết nối Medium.");
                    return;
                }
                if (action === "web20-add-manual") {
                    await apiWeb20("POST", "/accounts/google-sites-manual", {
                        label: ($("saW20ManualLabel") && $("saW20ManualLabel").value.trim()) || "Google Sites Manual",
                        site_url: ($("saW20ManualSiteUrl") && $("saW20ManualSiteUrl").value.trim()) || "",
                        main_site_url: ($("saW20MainUrl") && $("saW20MainUrl").value.trim()) || "",
                    });
                    await loadWeb20Tab();
                    showToast("Đã thêm Google Sites Manual.");
                    return;
                }
                if (action === "web20-select-blog") {
                    const aid = t.getAttribute("data-account-id");
                    const blogId = t.value;
                    await apiWeb20("PATCH", "/accounts/" + encodeURIComponent(aid), { external_id: blogId });
                    await loadWeb20Tab();
                    return;
                }
                if (action === "web20-copy-html") {
                    const text = ($("saW20ManualHtml") && $("saW20ManualHtml").value) || "";
                    if (text && navigator.clipboard) {
                        await navigator.clipboard.writeText(text);
                        showToast("Đã copy HTML.");
                    }
                    return;
                }
                if (action === "web20-copy-bundle") {
                    const pkg = state.web20.manualPackage;
                    const text = (pkg && pkg.copy_bundle) || "";
                    if (text && navigator.clipboard) {
                        await navigator.clipboard.writeText(text);
                        showToast("Đã copy nội dung Manual Package.");
                    }
                    return;
                }
                if (action === "web20-copy-plain") {
                    const pkg = state.web20.manualPackage;
                    const text = (pkg && pkg.plain_text) || "";
                    if (text && navigator.clipboard) {
                        await navigator.clipboard.writeText(text);
                        showToast("Đã copy plain text.");
                    }
                    return;
                }
                if (action === "web20-add-account") {
                    const url = ($("saW20Url") && $("saW20Url").value.trim()) || "";
                    const user = ($("saW20User") && $("saW20User").value.trim()) || "";
                    const pass = ($("saW20Pass") && $("saW20Pass").value) || "";
                    if (!url || !user || !pass) { showToast("Cần URL, username, application password."); return; }
                    await apiWeb20("POST", "/accounts", {
                        site_url: url,
                        username: user,
                        app_password: pass,
                        label: ($("saW20Label") && $("saW20Label").value.trim()) || url,
                        default_status: ($("saW20DefaultStatus") && $("saW20DefaultStatus").value) || "draft",
                    });
                    if ($("saW20Pass")) $("saW20Pass").value = "";
                    await loadWeb20Tab();
                    showToast("Đã kết nối site WordPress 2.0.");
                    return;
                }
                if (action === "web20-test-account") {
                    const aid = t.getAttribute("data-account-id");
                    const r = await apiWeb20("POST", "/accounts/" + encodeURIComponent(aid) + "/test");
                    showToast(r.message || (r.ok ? "OK" : "Lỗi"));
                    await loadWeb20Tab();
                    return;
                }
                if (action === "web20-del-account") {
                    const aid = t.getAttribute("data-account-id");
                    if (!window.confirm("Xóa tài khoản Web 2.0 này?")) return;
                    await apiWeb20("DELETE", "/accounts/" + encodeURIComponent(aid));
                    await loadWeb20Tab();
                    showToast("Đã xóa site.");
                    return;
                }
                if (action === "web20-generate") { await web20Generate(); return; }
                if (action === "web20-save") { await web20SaveDraft(); return; }
                if (action === "web20-schedule") { await web20Schedule(); return; }
                if (action === "web20-publish") { await web20Publish(); return; }
                if (action === "web20-retry-post") {
                    await web20RetryPost(t.getAttribute("data-post-id"));
                    return;
                }
                if (action === "web20-safety") {
                    const f = readWeb20Form();
                    if (!f.account_id) { showToast("Chọn tài khoản Web 2.0."); return; }
                    if (!f.title || !f.html_content) { showToast("Cần title và nội dung HTML."); return; }
                    const data = await apiWeb20("POST", "/safety/check", {
                        title: f.title,
                        html_content: f.html_content,
                        account_id: f.account_id,
                        main_site_url: f.main_site_url,
                        source_content: f.source_content,
                        post_id: state.web20.currentPostId,
                    });
                    renderWeb20Safety(data.safety);
                    showToast("Safety Score: " + (data.safety && data.safety.score));
                    return;
                }
                if (action === "web20-load-post") {
                    const pid = t.getAttribute("data-post-id");
                    const p = (state.web20.posts || []).find(function (x) { return x.id === pid; });
                    if (p) fillWeb20Form(p);
                    return;
                }
            } catch (err) {
                if (err.message !== "unauthorized") showToast(err.message);
            }
        });
    }

    function init() {
        bindEvents();
        const urlTab = readTabFromLocation();
        switchTab(urlTab || "overview", { skipFetch: true, skipHash: !!urlTab });
        if (window.location.search.indexOf("fb=connected") >= 0) {
            showToast("Đã kết nối Fanpage.");
            history.replaceState({}, "", "/social-auto#tab=compose");
        }
        const fbStatus = new URLSearchParams(window.location.search).get("fb_status");
        const fbErr = new URLSearchParams(window.location.search).get("fb_error");
        if (fbStatus || fbErr) {
            const decoded = fbErr ? decodeURIComponent(fbErr.replace(/\+/g, " ")) : "";
            if (fbStatus === "no_pages_permission" || isFbInvalidScopeError(decoded)) {
                showFbInvalidScopeModal(null);
            } else if (decoded) {
                showToast(decoded);
            } else if (fbStatus === "fb_logged_in") {
                showToast("Đã đăng nhập Facebook nhưng chưa có Fanpage.");
            }
            history.replaceState({}, "", window.location.pathname + window.location.hash);
        }
        if (window.location.search.indexOf("web20=connected") >= 0) {
            const m = window.location.search.match(/platform=([a-z0-9_]+)/);
            const pf = m ? m[1] : "blogger";
            state.web20.platform = pf;
            showToast("Đã kết nối " + (WEB20_PLATFORM_LABELS[pf] || pf) + ".");
            history.replaceState({}, "", "/social-auto#tab=compose");
            switchTab("compose", { skipFetch: true });
            loadComposeTab().catch(function () {});
        }
        const w20Html = $("saW20Html");
        if (w20Html) {
            w20Html.addEventListener("input", renderWeb20Preview);
        }
        if (!getAuthToken()) {
            showToast("Đăng nhập để dùng Social Auto.");
        } else {
            loadOverview()
                .then(function () { markSaTabFetched("overview"); })
                .catch(function (e) { if (e.message !== "unauthorized") showToast(e.message); });
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
