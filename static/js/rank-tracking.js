(function () {
    "use strict";

    var API = "/api/rank-tracking";
    var state = { projects: [], activeProjectId: null, summary: null, dashboard: [] };
    var toastTimer = null;

    function $(id) { return document.getElementById(id); }

    function getToken() {
        try {
            var t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
        } catch (_) {}
        var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    }

    function showToast(msg) {
        var el = $("rtToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        el.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            el.classList.remove("is-visible");
            setTimeout(function () { el.hidden = true; }, 220);
        }, 3200);
    }

    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function fmtDt(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
        } catch (_) { return iso; }
    }

    function fmtChange(change) {
        if (change === null || change === undefined || change === "") return '<span class="rt-change-flat">—</span>';
        var n = Number(change);
        if (isNaN(n) || n === 0) return '<span class="rt-change-flat">0</span>';
        if (n > 0) return '<span class="rt-change-up">▲ ' + esc(String(n)) + "</span>";
        return '<span class="rt-change-down">▼ ' + esc(String(Math.abs(n))) + "</span>";
    }

    async function api(method, path, body) {
        var token = getToken();
        if (!token) {
            showToast("Đăng nhập để dùng Rank Tracking.");
            if (typeof window.DigiSeoOpenLoginModal === "function") window.DigiSeoOpenLoginModal();
            throw new Error("unauthorized");
        }
        var opts = {
            method: method,
            credentials: "same-origin",
            headers: { Authorization: "Bearer " + token },
        };
        if (body !== undefined) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        var res = await fetch(API + path, opts);
        var data = null;
        try { data = await res.json(); } catch (_) {}
        if (res.status === 401) {
            showToast("Phiên đăng nhập hết hạn.");
            throw new Error("unauthorized");
        }
        if (!res.ok) {
            var detail = data && data.detail;
            var msg = "";
            if (typeof detail === "string") msg = detail;
            else if (detail && typeof detail === "object" && detail.message) msg = String(detail.message);
            else if (Array.isArray(detail) && detail.length) {
                msg = detail.map(function (x) { return (x && x.msg) || String(x); }).join("; ");
            }
            throw new Error(msg || ("HTTP " + res.status));
        }
        return data;
    }

    function activeProject() {
        return state.projects.find(function (p) { return p.id === state.activeProjectId; }) || null;
    }

    function renderProjects() {
        var box = $("rtProjectList");
        if (!box) return;
        if (!state.projects.length) {
            box.innerHTML = '<p class="rt-empty">Chưa có project.</p>';
            return;
        }
        box.innerHTML = state.projects.map(function (p) {
            var cls = p.id === state.activeProjectId ? "rt-project-item is-active" : "rt-project-item";
            return '<button type="button" class="' + cls + '" data-rt-project="' + esc(p.id) + '">' +
                "<strong>" + esc(p.name || p.domain) + "</strong>" +
                "<span>" + esc(p.domain) + " · " + esc(p.location_name) + " · " + esc(p.device) + "</span>" +
                "</button>";
        }).join("");
    }

    function renderHeader() {
        var p = activeProject();
        var title = $("rtActiveProjectTitle");
        var meta = $("rtActiveProjectMeta");
        var badge = $("rtModeBadge");
        if (title) title.textContent = p ? (p.name || p.domain) : "Chọn project";
        if (meta) {
            meta.textContent = p
                ? (p.domain + " · " + p.location_name + " · " + p.language_name + " · " + p.device)
                : "Tạo hoặc chọn project để quản lý keyword.";
        }
        var disabled = !p;
        if ($("rtKeywordInput")) $("rtKeywordInput").disabled = disabled;
        if ($("rtKeywordSubmit")) $("rtKeywordSubmit").disabled = disabled;
        if ($("rtCheckNowBtn")) $("rtCheckNowBtn").disabled = disabled;
        if (badge && state.summary && state.summary.mock_mode) {
            badge.textContent = "Mock mode";
        } else if (badge) {
            badge.textContent = "Rank Tracking";
        }
    }

    function renderStats() {
        var s = state.summary || {};
        if ($("rtStatKeywords")) $("rtStatKeywords").textContent = String(s.keywords_count || 0);
        if ($("rtStatRanked")) $("rtStatRanked").textContent = String(s.ranked_count || 0);
        if ($("rtStatNotFound")) $("rtStatNotFound").textContent = String(s.not_found_count || 0);
        if ($("rtStatAvg")) $("rtStatAvg").textContent = s.avg_rank != null ? String(s.avg_rank) : "—";
        if ($("rtStatUp")) $("rtStatUp").textContent = String(s.improved_count || 0);
        if ($("rtStatDown")) $("rtStatDown").textContent = String(s.declined_count || 0);
    }

    function renderDashboard() {
        var body = $("rtKeywordTableBody");
        if (!body) return;
        if (!state.activeProjectId) {
            body.innerHTML = '<tr><td colspan="5" class="rt-empty">Chọn project để xem keyword.</td></tr>';
            return;
        }
        if (!state.dashboard.length) {
            body.innerHTML = '<tr><td colspan="5" class="rt-empty">Chưa có keyword. Thêm keyword và bấm Check now.</td></tr>';
            return;
        }
        body.innerHTML = state.dashboard.map(function (row) {
            var rank = row.current_rank != null ? row.current_rank : "100+";
            var url = row.best_url
                ? '<a href="' + esc(row.best_url) + '" target="_blank" rel="noopener">' + esc(row.best_url) + "</a>"
                : '<span class="rt-empty">Không thấy trong top 100</span>';
            return "<tr>" +
                "<td>" + esc(row.keyword) + (row.mock ? ' <span class="rt-empty">(mock)</span>' : "") + "</td>" +
                '<td class="rt-rank">' + esc(String(rank)) + "</td>" +
                "<td>" + fmtChange(row.rank_change) + "</td>" +
                "<td>" + url + "</td>" +
                "<td>" + esc(fmtDt(row.last_checked)) + "</td>" +
                "</tr>";
        }).join("");
    }

    async function loadProjects(selectId) {
        var data = await api("GET", "/projects");
        state.projects = data.items || [];
        if (selectId && state.projects.some(function (p) { return p.id === selectId; })) {
            state.activeProjectId = selectId;
        } else if (!state.activeProjectId && state.projects.length) {
            state.activeProjectId = state.projects[0].id;
        }
        renderProjects();
        renderHeader();
    }

    async function loadSummaryAndDashboard() {
        if (!state.activeProjectId) {
            state.summary = null;
            state.dashboard = [];
            renderStats();
            renderDashboard();
            return;
        }
        var data = await api("GET", "/summary?project_id=" + encodeURIComponent(state.activeProjectId));
        state.summary = data.summary || null;
        state.dashboard = data.dashboard || [];
        renderStats();
        renderDashboard();
        renderHeader();
    }

    async function refreshAll() {
        await loadProjects(state.activeProjectId);
        await loadSummaryAndDashboard();
    }

    function bindEvents() {
        var projectForm = $("rtProjectForm");
        if (projectForm) {
            projectForm.addEventListener("submit", async function (e) {
                e.preventDefault();
                try {
                    var domain = ($("rtProjectDomain") && $("rtProjectDomain").value || "").trim();
                    if (!domain) { showToast("Nhập domain."); return; }
                    var data = await api("POST", "/projects", {
                        name: ($("rtProjectName") && $("rtProjectName").value || "").trim(),
                        domain: domain,
                        location_name: ($("rtProjectLocation") && $("rtProjectLocation").value || "Vietnam").trim(),
                        language_name: ($("rtProjectLanguage") && $("rtProjectLanguage").value || "Vietnamese").trim(),
                        device: ($("rtProjectDevice") && $("rtProjectDevice").value) || "desktop",
                    });
                    state.activeProjectId = data.item && data.item.id;
                    showToast("Đã tạo project.");
                    projectForm.reset();
                    if ($("rtProjectLocation")) $("rtProjectLocation").value = "Vietnam";
                    if ($("rtProjectLanguage")) $("rtProjectLanguage").value = "Vietnamese";
                    await refreshAll();
                } catch (err) {
                    if (err.message !== "unauthorized") showToast(err.message);
                }
            });
        }

        var keywordForm = $("rtKeywordForm");
        if (keywordForm) {
            keywordForm.addEventListener("submit", async function (e) {
                e.preventDefault();
                if (!state.activeProjectId) return;
                try {
                    var kw = ($("rtKeywordInput") && $("rtKeywordInput").value || "").trim();
                    if (!kw) { showToast("Nhập keyword."); return; }
                    await api("POST", "/keywords", { project_id: state.activeProjectId, keyword: kw });
                    if ($("rtKeywordInput")) $("rtKeywordInput").value = "";
                    showToast("Đã thêm keyword.");
                    await loadSummaryAndDashboard();
                } catch (err) {
                    if (err.message !== "unauthorized") showToast(err.message);
                }
            });
        }

        var list = $("rtProjectList");
        if (list) {
            list.addEventListener("click", async function (e) {
                var btn = e.target && e.target.closest("[data-rt-project]");
                if (!btn) return;
                state.activeProjectId = btn.getAttribute("data-rt-project");
                renderProjects();
                renderHeader();
                await loadSummaryAndDashboard();
            });
        }

        var checkBtn = $("rtCheckNowBtn");
        if (checkBtn) {
            checkBtn.addEventListener("click", async function () {
                if (!state.activeProjectId) return;
                checkBtn.disabled = true;
                checkBtn.textContent = "Đang check…";
                try {
                    var out = await api("POST", "/check-now", { project_id: state.activeProjectId, depth: 100 });
                    var msg = "Đã check " + (out.checked_count || 0) + " keyword.";
                    if (out.mock) msg += " (mock mode)";
                    showToast(msg);
                    await loadSummaryAndDashboard();
                } catch (err) {
                    if (err.message !== "unauthorized") showToast(err.message);
                } finally {
                    checkBtn.disabled = !state.activeProjectId;
                    checkBtn.textContent = "Check now";
                }
            });
        }

        var refreshBtn = $("rtRefreshBtn");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", function () {
                refreshAll().catch(function (err) {
                    if (err.message !== "unauthorized") showToast(err.message);
                });
            });
        }
    }

    async function init() {
        bindEvents();
        try {
            var raw = sessionStorage.getItem("seoauto_cluster_rank_prefill");
            if (raw) {
                sessionStorage.removeItem("seoauto_cluster_rank_prefill");
                var pre = JSON.parse(raw);
                var kws = (pre && pre.keywords) || [];
                if (kws.length && $("rtKeywordInput")) {
                    $("rtKeywordInput").placeholder = "Gợi ý: " + kws.slice(0, 3).join(", ") + "…";
                    $("rtKeywordInput").value = kws[0] || "";
                }
            }
        } catch (_e) {}
        if (!getToken()) {
            showToast("Đăng nhập để dùng Rank Tracking.");
            renderHeader();
            return;
        }
        try {
            await refreshAll();
        } catch (err) {
            if (err.message !== "unauthorized") showToast(err.message);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
