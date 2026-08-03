/**
 * Index Control — SaaS UI (Tổng quan, Submit, Check Index Free, Lịch sử).
 */
(function () {
    "use strict";

    var TABS = {
        OVERVIEW: "overview",
        SUBMIT: "submit",
        CHECK_FREE: "check-free",
        RESULTS: "results"
    };
    var TAB_IDS = [TABS.OVERVIEW, TABS.SUBMIT, TABS.CHECK_FREE, TABS.RESULTS];

    var state = {
        quota: { used: 0, remaining: null, limit: null, is_unlimited: false },
        pendingCheckUrl: "",
        checkFree: {
            urls: [],
            rows: [],
            streaming: false,
            lastCheckId: null,
            pausedCheckId: null,
            pendingUrls: [],
            maxUrls: 100
        },
        resultsBatches: [],
        activeResultBatch: null,
        resultsFilters: { date_from: "", date_to: "", q: "", status: "" },
        resultsDetailIndexFilter: "",
        submitProjects: [],
        activeProject: null
    };

    function $(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function authToken() {
        return typeof window.DigiSeoGetAuthToken === "function" ? window.DigiSeoGetAuthToken() : "";
    }

    function authHeaders() {
        var t = authToken();
        var h = { "Content-Type": "application/json" };
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function showToast(msg) {
        var el = $("icToast");
        if (!el) return;
        el.textContent = msg;
        el.classList.add("is-visible");
        clearTimeout(showToast._t);
        showToast._t = setTimeout(function () { el.classList.remove("is-visible"); }, 3200);
    }

    function parseUrlLines(text) {
        var seen = {};
        var out = [];
        String(text || "").split(/\r?\n/).forEach(function (line) {
            var u = line.trim();
            if (!u || seen[u]) return;
            seen[u] = true;
            out.push(u);
        });
        return out;
    }

    function isValidHttpUrl(url) {
        try {
            var u = new URL(url);
            return u.protocol === "http:" || u.protocol === "https:";
        } catch (_) {
            return false;
        }
    }

    function countValidUrls(text) {
        return parseUrlLines(text).filter(isValidHttpUrl).length;
    }

    function normalizeTabId(tabId) {
        var id = String(tabId || "").trim().toLowerCase();
        if (id === "history") return TABS.RESULTS;
        return TAB_IDS.indexOf(id) >= 0 ? id : TABS.OVERVIEW;
    }

    function switchTab(tabId, opts) {
        opts = opts || {};
        tabId = normalizeTabId(tabId);

        document.querySelectorAll(".ic-tab").forEach(function (btn) {
            var on = btn.getAttribute("data-ic-tab") === tabId;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });

        document.querySelectorAll(".ic-panel").forEach(function (panel) {
            var on = panel.getAttribute("data-ic-panel") === tabId;
            panel.classList.toggle("active", on);
            panel.hidden = !on;
        });

        if (!opts.skipHash && window.location.hash !== "#tab=" + tabId) {
            history.replaceState({ icTab: tabId }, "", "/index-control#tab=" + tabId);
        }

        if (tabId === TABS.OVERVIEW && !opts.skipLoadOverview) loadOverview();
        if (tabId === TABS.SUBMIT && !opts.skipLoadQuota) refreshSubmitQuota();
        if (tabId === TABS.SUBMIT && !opts.skipLoadProjects) {
            var projectsPane = document.querySelector('[data-submit-pane="projects"]');
            if (projectsPane && !projectsPane.hidden) loadSubmitProjects();
        }
        if (tabId === TABS.RESULTS && !opts.skipLoadResults) loadResults();
    }

    function readInitialTab() {
        try {
            var q = new URLSearchParams(window.location.search).get("tab");
            if (q) return normalizeTabId(q);
        } catch (_) {}
        var m = (window.location.hash || "").match(/tab=([a-z0-9_-]+)/i);
        return m ? normalizeTabId(m[1]) : TABS.OVERVIEW;
    }

    function applyIncomingParams() {
        try {
            var params = new URLSearchParams(window.location.search);
            var url = params.get("url");
            if (!url) return false;
            var tab = params.get("tab") || TABS.SUBMIT;
            if (tab === "check" || tab === "check-free") {
                var cf = $("icCheckFreeUrls");
                if (cf) cf.value = url;
                return true;
            }
            var su = $("icSubmitUrls");
            if (su) su.value = url;
            return true;
        } catch (_) {
            return false;
        }
    }

    function formatDate(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit"
            });
        } catch (_) {
            return iso;
        }
    }

    function renderQuotaCards(data) {
        var quota = (data && data.quota) || {};
        state.quota = quota;

        var lifetime = data.lifetime_submitted != null ? data.lifetime_submitted : quota.used;
        var usedEl = $("icSaasUsedTotal");
        var monthEl = $("icSaasUsedMonth");
        var remEl = $("icSaasRemaining");
        var hintEl = $("icSaasLimitHint");

        if (usedEl) usedEl.textContent = String(lifetime);
        if (monthEl) monthEl.textContent = "Tháng này: " + String(quota.used != null ? quota.used : 0);

        if (quota.is_unlimited) {
            if (remEl) remEl.textContent = "∞";
            if (hintEl) hintEl.textContent = "Gói không giới hạn submit";
        } else if (quota.remaining != null) {
            if (remEl) remEl.textContent = String(quota.remaining);
            if (hintEl) hintEl.textContent = quota.limit != null
                ? "Giới hạn tháng: " + quota.limit
                : "Theo gói hiện tại";
        } else {
            if (remEl) remEl.textContent = "—";
            if (hintEl) hintEl.textContent = "Chưa có giới hạn gói";
        }

        updateSubmitLiveStats();
    }

    function loadOverview() {
        if (!authToken()) {
            var err = $("icOverviewError");
            if (err) { err.hidden = false; err.textContent = "Đăng nhập để xem tổng quan."; }
            return;
        }
        var loading = $("icOverviewLoading");
        var err = $("icOverviewError");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;

        fetch("/api/index-control/saas-overview", {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                return r.json();
            })
            .then(function (data) {
                if (!data.ok) throw new Error("fail");
                renderQuotaCards(data);
                var list = $("icRecentList");
                var empty = $("icRecentEmpty");
                var items = data.recent_submits || [];
                if (!items.length) {
                    if (list) list.innerHTML = "";
                    if (empty) empty.hidden = false;
                } else {
                    if (empty) empty.hidden = true;
                    if (list) {
                        list.innerHTML = items.map(function (it) {
                            return '<li><span class="ic-recent-list__url">' + esc(it.url) + '</span>' +
                                '<time class="ic-recent-list__time">' + esc(formatDate(it.created_at)) + "</time></li>";
                        }).join("");
                    }
                }
            })
            .catch(function (e) {
                if (err) {
                    err.hidden = false;
                    err.textContent = String(e && e.message) === "auth"
                        ? "Phiên đăng nhập hết hạn."
                        : "Không tải được tổng quan.";
                }
            })
            .finally(function () {
                if (loading) loading.hidden = true;
            });
    }

    function refreshSubmitQuota() {
        if (!authToken()) return;
        fetch("/api/index-control/submit-quota", {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ok && data.quota) {
                    state.quota = data.quota;
                    updateSubmitLiveStats();
                }
            })
            .catch(function () {});
    }

    function updateSubmitLiveStats() {
        var text = $("icSubmitUrls") && $("icSubmitUrls").value;
        var valid = countValidUrls(text);
        var validEl = $("icSubmitValidCount");
        var useEl = $("icSubmitUseCount");
        var afterEl = $("icSubmitAfterCount");
        if (validEl) validEl.textContent = String(valid);
        if (useEl) useEl.textContent = String(valid);

        if (state.quota.is_unlimited) {
            if (afterEl) afterEl.textContent = "∞";
            return;
        }
        var rem = state.quota.remaining;
        if (rem == null) {
            if (afterEl) afterEl.textContent = "—";
        } else {
            if (afterEl) afterEl.textContent = String(Math.max(0, rem - valid));
        }
    }

    function statusLabel(status) {
        if (status === "sent") return "Đã gửi";
        if (status === "duplicate") return "Trùng lặp";
        return "Lỗi";
    }

    function statusClass(status) {
        if (status === "sent") return "ok";
        if (status === "duplicate") return "warn";
        return "err";
    }

    function buildSubmitUrlMeta(urls) {
        var meta = {};
        var rowMap = {};
        (state.checkFree.rows || []).forEach(function (row) {
            if (row && row.url) rowMap[row.url] = row;
        });
        (urls || []).forEach(function (url) {
            var row = rowMap[url];
            if (!row) return;
            meta[url] = {
                status: row.status,
                index_status: row.index_status,
                status_label: row.status_label,
                indexed: checkFreeLabel(row.status || row.index_status),
                http_status: row.http_status,
                indexability: row.indexability,
                redirect_url: row.final_url || "",
                message: row.message
            };
        });
        return meta;
    }

    function switchSubmitTab(tabId) {
        document.querySelectorAll(".ic-submit-subtab").forEach(function (btn) {
            var on = btn.getAttribute("data-submit-tab") === tabId;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        });
        document.querySelectorAll(".ic-submit-pane").forEach(function (pane) {
            var on = pane.getAttribute("data-submit-pane") === tabId;
            pane.classList.toggle("active", on);
            pane.hidden = !on;
        });
        if (tabId === "projects") loadSubmitProjects();
    }

    function showProjectListView() {
        var listView = $("icSubmitProjectListView");
        var detailView = $("icSubmitProjectDetailView");
        if (listView) listView.hidden = false;
        if (detailView) detailView.hidden = true;
        state.activeProject = null;
    }

    function projectIndexClass(label) {
        if (label === "Index") return "ic-project-index--index";
        if (label === "No") return "ic-project-index--no";
        return "";
    }

    function renderSubmitProjectDetail(project) {
        var title = $("icProjectDetailTitle");
        var tbody = $("icProjectTableBody");
        var cards = $("icProjectCards");
        if (title) title.textContent = project.project_name || ("Project #" + project.id);
        var items = project.items || [];

        if (tbody) {
            tbody.innerHTML = items.map(function (it) {
                var idx = displayIndexLabel(it.indexed);
                var broken = it.broken || "—";
                return "<tr>" +
                    "<td>" + esc(String(it.id)) + "</td>" +
                    '<td class="ic-url-cell">' + esc(it.url) + "</td>" +
                    '<td class="' + esc(projectIndexClass(idx)) + '">' + esc(idx) + "</td>" +
                    "<td>" + esc(String(it.status_code || "—")) + "</td>" +
                    "<td>" + esc(String(it.indexability || "—")) + "</td>" +
                    "<td>" + esc(String(it.redirect_url || "—")) + "</td>" +
                    '<td class="ic-project-broken">' + esc(String(broken)) + "</td>" +
                    '<td class="ic-project-col-check"><input type="checkbox" class="ic-project-row-check" data-url="' +
                    esc(it.url) + '"></td></tr>';
            }).join("");
        }

        if (cards) {
            cards.innerHTML = items.map(function (it) {
                return '<article class="ic-project-card">' +
                    '<p><strong>#' + esc(String(it.id)) + "</strong> " +
                    '<span class="' + esc(projectIndexClass(it.indexed)) + '">' + esc(it.indexed || "—") + "</span></p>" +
                    '<p class="ic-url-cell">' + esc(it.url) + "</p>" +
                    '<p>Broken: <span class="ic-project-broken">' + esc(it.broken || "—") + "</span></p>" +
                    "</article>";
            }).join("");
        }

        var selectAll = $("icProjectSelectAll");
        if (selectAll) {
            selectAll.checked = false;
            selectAll.onchange = function () {
                document.querySelectorAll(".ic-project-row-check").forEach(function (cb) {
                    cb.checked = selectAll.checked;
                });
            };
        }
    }

    function openSubmitProject(projectId) {
        fetchSubmitProjectWithIndexCheck(projectId, {
            onSuccess: function (data) {
                state.activeProject = data;
                var listView = $("icSubmitProjectListView");
                var detailView = $("icSubmitProjectDetailView");
                if (listView) listView.hidden = true;
                if (detailView) detailView.hidden = false;
                renderSubmitProjectDetail(data);
            },
            onError: function () {
                showToast("Không tải được dự án.");
            },
        });
    }

    function fetchSubmitProjectWithIndexCheck(projectId, opts) {
        opts = opts || {};
        fetch("/api/index-control/submit-indexing/projects/" + encodeURIComponent(projectId) + "/check-index", {
            method: "POST",
            credentials: "same-origin",
            headers: authHeaders(),
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                if (!r.ok) throw new Error("load");
                return r.json();
            })
            .then(function (data) {
                if (typeof opts.onSuccess === "function") opts.onSuccess(data);
            })
            .catch(function () {
                if (typeof opts.onError === "function") opts.onError();
            });
    }

    function displayIndexLabel(raw) {
        var label = String(raw || "").trim();
        if (label === "Index") return "Index";
        if (label === "No" || label === "—" || !label) return "No";
        return label;
    }

    function formatResultsDate(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                year: "numeric",
                month: "long",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
                hour12: true
            });
        } catch (_) {
            return iso;
        }
    }

    function formatResultsDateShort(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit"
            });
        } catch (_) {
            return iso;
        }
    }

    function safeNum(n) {
        var v = Number(n);
        return Number.isFinite(v) ? v : 0;
    }

    function resultsBadgeClass(code) {
        var c = String(code || "").toLowerCase();
        if (c === "completed") return "ic-results-badge--completed";
        if (c === "error") return "ic-results-badge--error";
        if (c === "not_checked") return "ic-results-badge--not_checked";
        return "ic-results-badge--processing";
    }

    function googleIndexClass(label) {
        var s = String(label || "").trim().toLowerCase();
        if (s === "index") return "ic-results-index--index";
        if (s === "no index" || s === "noindex") return "ic-results-index--no";
        return "ic-results-index--pending";
    }

    function googleIndexFilterKey(label) {
        var s = String(label || "").trim().toLowerCase();
        if (s === "index") return "index";
        if (s === "no index" || s === "noindex") return "no_index";
        return "other";
    }

    function filterResultsDetailItems(items) {
        var filter = state.resultsDetailIndexFilter;
        if (!filter) return items || [];
        return (items || []).filter(function (it) {
            return googleIndexFilterKey(it.google_index) === filter;
        });
    }

    function showResultsListView() {
        var listView = $("icResultsListView");
        var detailView = $("icResultsDetailView");
        if (listView) listView.hidden = false;
        if (detailView) detailView.hidden = true;
        state.activeResultBatch = null;
        state.resultsDetailIndexFilter = "";
        var indexFilter = $("icResultsDetailIndexFilter");
        if (indexFilter) indexFilter.value = "";
    }

    function buildResultsQuery() {
        var f = state.resultsFilters || {};
        var params = new URLSearchParams();
        if (f.date_from) params.set("date_from", f.date_from);
        if (f.date_to) params.set("date_to", f.date_to);
        if (f.q) params.set("q", f.q);
        if (f.status) params.set("status", f.status);
        params.set("limit", "50");
        return params.toString();
    }

    function readResultsFiltersFromForm() {
        var fromEl = $("icResultsDateFrom");
        var toEl = $("icResultsDateTo");
        var qEl = $("icResultsSearch");
        var stEl = $("icResultsStatus");
        state.resultsFilters = {
            date_from: fromEl && fromEl.value ? fromEl.value : "",
            date_to: toEl && toEl.value ? toEl.value : "",
            q: qEl && qEl.value ? qEl.value.trim() : "",
            status: stEl && stEl.value ? stEl.value : ""
        };
    }

    function renderResultsTable(batches) {
        var tbody = $("icResultsTableBody");
        var cards = $("icResultsCards");
        var empty = $("icResultsEmpty");
        var wrap = $("icResultsTableWrap");
        batches = batches || [];
        if (empty) empty.hidden = batches.length > 0;
        if (wrap) wrap.hidden = batches.length === 0;

        function progressHtml(sent, total, pct, pctClass) {
            var s = safeNum(sent);
            var t = safeNum(total);
            var p = safeNum(pct);
            return esc(String(s)) + " / " + esc(String(t)) +
                ' <span class="ic-results-pct ' + pctClass + '">(' + esc(String(p)) + "%)</span>";
        }

        if (tbody) {
            tbody.innerHTML = batches.map(function (b) {
                var submitBadge = '<span class="ic-results-badge ' + resultsBadgeClass(b.submit_status) + '">' +
                    esc(b.submit_status_label || "—") + "</span>";
                var checkBadge = '<span class="ic-results-badge ' + resultsBadgeClass(b.check_status) + '">' +
                    esc(b.check_status_label || "—") + "</span>";
                return "<tr data-batch-id=\"" + esc(String(b.id)) + "\">" +
                    "<td><button type=\"button\" class=\"ic-results-batch-link\" data-batch-id=\"" +
                    esc(String(b.id)) + "\">" + esc(b.batch_name || b.project_name || "—") + "</button>" +
                    submitBadge + "</td>" +
                    "<td>" + esc(String(safeNum(b.total_links))) + "</td>" +
                    "<td>" + esc(formatResultsDate(b.uploaded_at)) + "</td>" +
                    "<td>" + esc(String(safeNum(b.dripfeed_days))) + "</td>" +
                    "<td>" + progressHtml(b.submitted_count, b.total_links, b.submitted_percent, "ic-results-pct--submit") + "</td>" +
                    "<td>" + checkBadge + "</td>" +
                    "<td>" + progressHtml(b.indexed_count, b.total_links, b.indexed_percent, "ic-results-pct--indexed") + "</td>" +
                    '<td class="ic-results-col-check"><input type="checkbox" class="ic-results-row-check" data-batch-id="' +
                    esc(String(b.id)) + '" aria-label="Chọn batch"></td></tr>';
            }).join("");
            tbody.querySelectorAll(".ic-results-batch-link").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    openResultsBatch(btn.getAttribute("data-batch-id"));
                });
            });
        }

        if (cards) {
            cards.innerHTML = batches.map(function (b) {
                return '<article class="ic-results-card-item" data-batch-id="' + esc(String(b.id)) + '">' +
                    '<div class="ic-results-card-item__head">' +
                    '<button type="button" class="ic-results-batch-link" data-batch-id="' + esc(String(b.id)) + '">' +
                    esc(b.batch_name || "—") + "</button>" +
                    '<span class="ic-results-badge ' + resultsBadgeClass(b.submit_status) + '">' +
                    esc(b.submit_status_label || "") + "</span></div>" +
                    '<p class="ic-results-card-item__url">Submit: ' +
                    esc(String(safeNum(b.submitted_count))) + "/" + esc(String(safeNum(b.total_links))) +
                    " · Index: " + esc(String(safeNum(b.indexed_count))) + "/" + esc(String(safeNum(b.total_links))) +
                    "</p></article>";
            }).join("");
            cards.querySelectorAll(".ic-results-batch-link").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    openResultsBatch(btn.getAttribute("data-batch-id"));
                });
            });
        }

        var selectAll = $("icResultsSelectAll");
        if (selectAll) {
            selectAll.checked = false;
            selectAll.onchange = function () {
                document.querySelectorAll(".ic-results-row-check").forEach(function (cb) {
                    cb.checked = selectAll.checked;
                });
            };
        }
    }

    function loadResults() {
        var skeleton = $("icResultsSkeleton");
        var err = $("icResultsError");
        var empty = $("icResultsEmpty");
        var wrap = $("icResultsTableWrap");
        if (!authToken()) {
            if (err) {
                err.hidden = false;
                err.textContent = "Đăng nhập để xem kết quả.";
            }
            return;
        }
        if (skeleton) skeleton.hidden = false;
        if (err) err.hidden = true;
        if (empty) empty.hidden = true;
        if (wrap) wrap.hidden = true;

        fetch("/api/index-control/results?" + buildResultsQuery(), {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                if (!r.ok) throw new Error("fail");
                return r.json();
            })
            .then(function (data) {
                state.resultsBatches = data.batches || [];
                renderResultsTable(state.resultsBatches);
            })
            .catch(function (e) {
                if (err) {
                    err.hidden = false;
                    err.textContent = String(e && e.message) === "auth"
                        ? "Phiên hết hạn."
                        : "Không tải được kết quả.";
                }
            })
            .finally(function () {
                if (skeleton) skeleton.hidden = true;
            });
    }

    function renderResultsDetail(batch) {
        var title = $("icResultsDetailTitle");
        var meta = $("icResultsDetailMeta");
        var tbody = $("icResultsDetailBody");
        var cards = $("icResultsDetailCards");
        if (title) title.textContent = batch.batch_name || batch.project_name || "—";
        var allItems = batch.items || [];
        var items = filterResultsDetailItems(allItems);
        if (meta) {
            var metaText = "Tổng " + safeNum(batch.total_links) + " link · Đã index " +
                safeNum(batch.indexed_count) + " (" + safeNum(batch.indexed_percent) + "%)";
            if (state.resultsDetailIndexFilter) {
                metaText += " · Đang lọc: " + items.length + " URL";
            }
            meta.textContent = metaText;
        }
        if (tbody) {
            if (!items.length) {
                tbody.innerHTML = '<tr><td colspan="8" class="ic-results-detail-empty">' +
                    (state.resultsDetailIndexFilter ? "Không có URL phù hợp bộ lọc." : "Chưa có URL trong batch.") +
                    "</td></tr>";
            } else {
                tbody.innerHTML = items.map(function (it) {
                    var gIdx = it.google_index || "Chưa check";
                    return "<tr>" +
                        "<td>" + esc(String(it.stt || "")) + "</td>" +
                        '<td class="ic-url-cell">' + esc(it.url) + "</td>" +
                        "<td>" + esc(it.submit_status_label || "—") + "</td>" +
                        "<td>" + esc(it.check_status_label || "—") + "</td>" +
                        '<td><span class="ic-results-index-pill ' + esc(googleIndexClass(gIdx)) + '">' + esc(gIdx) + "</span></td>" +
                        "<td>" + esc(it.no_index_reason || "—") + "</td>" +
                        "<td>" + esc(formatResultsDateShort(it.submitted_at)) + "</td>" +
                        "<td>" + esc(it.last_checked_at ? formatResultsDateShort(it.last_checked_at) : "—") + "</td>" +
                        "</tr>";
                }).join("");
            }
        }
        if (cards) {
            if (!items.length) {
                cards.innerHTML = '<p class="ic-results-detail-empty">' +
                    (state.resultsDetailIndexFilter ? "Không có URL phù hợp bộ lọc." : "Chưa có URL trong batch.") +
                    "</p>";
            } else {
                cards.innerHTML = items.map(function (it) {
                    var gIdx = it.google_index || "Chưa check";
                    return '<article class="ic-results-card-item">' +
                        '<div class="ic-results-card-item__head"><span>#' + esc(String(it.stt || "")) +
                        '</span><span class="ic-results-index-pill ' + esc(googleIndexClass(gIdx)) + '">' + esc(gIdx) + "</span></div>" +
                        '<p class="ic-results-card-item__url">' + esc(it.url) + "</p>" +
                        "<p>" + esc(it.submit_status_label || "") + " · " + esc(it.check_status_label || "") + "</p>" +
                        (it.no_index_reason ? "<p>" + esc(it.no_index_reason) + "</p>" : "") +
                        "</article>";
                }).join("");
            }
        }
    }

    function fetchResultsDetail(projectId, opts) {
        opts = opts || {};
        fetch("/api/index-control/results/" + encodeURIComponent(projectId), {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                if (!r.ok) throw new Error("load");
                return r.json();
            })
            .then(function (data) {
                if (typeof opts.onSuccess === "function") opts.onSuccess(data);
            })
            .catch(function () {
                if (typeof opts.onError === "function") opts.onError();
            });
    }

    function openResultsBatch(projectId) {
        var listView = $("icResultsListView");
        var detailView = $("icResultsDetailView");
        var loading = $("icResultsDetailLoading");
        var err = $("icResultsDetailError");
        if (listView) listView.hidden = true;
        if (detailView) detailView.hidden = false;
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        state.resultsDetailIndexFilter = "";
        var indexFilter = $("icResultsDetailIndexFilter");
        if (indexFilter) indexFilter.value = "";

        fetchResultsDetail(projectId, {
            onSuccess: function (data) {
                state.activeResultBatch = data;
                renderResultsDetail(data);
                if (loading) loading.hidden = true;
            },
            onError: function () {
                if (loading) loading.hidden = true;
                if (err) {
                    err.hidden = false;
                    err.textContent = "Không tải được chi tiết batch.";
                }
                showToast("Không mở được batch.");
            }
        });
    }

    function exportActiveResultBatch() {
        var batch = state.activeResultBatch;
        if (!batch || !batch.id) {
            showToast("Chưa có batch để xuất file.");
            return;
        }
        fetch("/api/index-control/submit-indexing/projects/" + encodeURIComponent(batch.id) + "/export", {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (!r.ok) throw new Error("export");
                return r.blob();
            })
            .then(function (blob) {
                var a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = (batch.batch_name || batch.project_name || "ket-qua-index") + ".xlsx";
                document.body.appendChild(a);
                a.click();
                a.remove();
                showToast("Đã tải file Excel.");
            })
            .catch(function () {
                showToast("Xuất Excel thất bại.");
            });
    }

    function recheckActiveResultBatch() {
        var batch = state.activeResultBatch;
        if (!batch || !batch.id) return;
        var loading = $("icResultsDetailLoading");
        if (loading) loading.hidden = false;
        fetchSubmitProjectWithIndexCheck(batch.id, {
            onSuccess: function (data) {
                state.activeResultBatch = data;
                renderResultsDetail(data);
                if (loading) loading.hidden = true;
                showToast("Đã cập nhật kết quả index.");
            },
            onError: function () {
                if (loading) loading.hidden = true;
                showToast("Check index thất bại.");
            }
        });
    }

    var formatHistoryDate = formatResultsDateShort;

    function loadSubmitProjects() {
        var loading = $("icProjectsLoading");
        var empty = $("icProjectsEmpty");
        var list = $("icProjectList");
        if (!authToken()) return;
        if (loading) loading.hidden = false;

        fetch("/api/index-control/submit-indexing/projects?limit=50", {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                return r.json();
            })
            .then(function (data) {
                state.submitProjects = data.projects || [];
                if (empty) empty.hidden = state.submitProjects.length > 0;
                if (list) {
                    list.innerHTML = state.submitProjects.map(function (p) {
                        return '<div class="ic-project-item">' +
                            '<button type="button" class="ic-project-item__open" data-project-id="' +
                            esc(String(p.id)) + '">' +
                            '<div><div class="ic-project-item__name">' + esc(p.project_name) + "</div>" +
                            '<div class="ic-project-item__meta">' + esc(String(p.sent_count || p.url_count || 0)) +
                            " URL · " + esc(formatHistoryDate(p.created_at)) + "</div></div>" +
                            '<span class="ic-badge ic-badge--info">→</span></button>' +
                            '<button type="button" class="ic-btn ic-btn--ghost ic-btn--xs ic-project-item__delete" data-delete-id="' +
                            esc(String(p.id)) + '" aria-label="Xóa dự án">Xóa</button>' +
                            "</div>";
                    }).join("");
                    list.querySelectorAll("[data-project-id]").forEach(function (btn) {
                        btn.addEventListener("click", function () {
                            openSubmitProject(btn.getAttribute("data-project-id"));
                        });
                    });
                    list.querySelectorAll("[data-delete-id]").forEach(function (btn) {
                        btn.addEventListener("click", function (e) {
                            e.stopPropagation();
                            var id = btn.getAttribute("data-delete-id");
                            var project = (state.submitProjects || []).find(function (p) {
                                return String(p.id) === String(id);
                            });
                            deleteSubmitProject(id, project && project.project_name);
                        });
                    });
                }
            })
            .catch(function () {
                showToast("Không tải được danh sách dự án.");
            })
            .finally(function () {
                if (loading) loading.hidden = true;
            });
    }

    function getProjectCheckedUrls() {
        var urls = [];
        document.querySelectorAll(".ic-project-row-check:checked").forEach(function (cb) {
            if (cb.getAttribute("data-url")) urls.push(cb.getAttribute("data-url"));
        });
        return urls;
    }

    function copyProjectUrls(urls) {
        if (!urls.length) {
            showToast("Chưa chọn URL.");
            return;
        }
        var text = urls.join("\n");
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () {
                showToast("Đã copy " + urls.length + " URL.");
            });
        }
    }

    function exportActiveProject() {
        var p = state.activeProject;
        if (!p || !p.id) return;
        fetch("/api/index-control/submit-indexing/projects/" + encodeURIComponent(p.id) + "/export", {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (!r.ok) throw new Error("export");
                return r.blob();
            })
            .then(function (blob) {
                var a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = (p.project_name || "submit-project") + ".xlsx";
                document.body.appendChild(a);
                a.click();
                a.remove();
                showToast("Đã tải file Excel.");
            })
            .catch(function () {
                showToast("Xuất Excel thất bại.");
            });
    }

    function deleteSubmitProject(projectId, projectName, opts) {
        opts = opts || {};
        var label = projectName || projectId;
        if (!window.confirm("Xóa dự án \"" + label + "\"?")) return Promise.resolve(false);
        return fetch("/api/index-control/submit-indexing/projects/" + encodeURIComponent(projectId), {
            method: "DELETE",
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (!r.ok) throw new Error("delete");
                showToast("Đã xóa dự án.");
                if (state.activeProject && String(state.activeProject.id) === String(projectId)) {
                    showProjectListView();
                }
                if (!opts.skipReload) {
                    loadSubmitProjects();
                    loadResults();
                }
                return true;
            })
            .catch(function () {
                showToast("Xóa dự án thất bại.");
                return false;
            });
    }

    function deleteAllSubmitProjects() {
        if (!authToken()) {
            showToast("Đăng nhập để xóa dự án.");
            return;
        }
        if (!(state.submitProjects || []).length && !(state.resultsBatches || []).length) {
            showToast("Chưa có dự án để xóa.");
            return;
        }
        if (!window.confirm("Xóa tất cả dự án submit? Thao tác này không thể hoàn tác.")) return;
        fetch("/api/index-control/submit-indexing/projects", {
            method: "DELETE",
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) {
                if (!r.ok) throw new Error("delete");
                return r.json();
            })
            .then(function (data) {
                showToast("Đã xóa " + (data.deleted || 0) + " dự án.");
                showProjectListView();
                loadSubmitProjects();
                loadResults();
            })
            .catch(function () {
                showToast("Xóa tất cả dự án thất bại.");
            });
    }

    function deleteActiveProject() {
        var p = state.activeProject;
        if (!p || !p.id) return;
        deleteSubmitProject(p.id, p.project_name);
    }

    function mergeUrlsIntoTextarea(ta, newLines, onUpdated) {
        if (!ta) return;
        var merged = parseUrlLines(ta.value);
        var seen = {};
        merged.forEach(function (u) { seen[u] = true; });
        newLines.forEach(function (line) {
            var u = String(line || "").trim();
            if (!u || seen[u]) return;
            seen[u] = true;
            merged.push(u);
        });
        ta.value = merged.join("\n");
        if (typeof onUpdated === "function") onUpdated();
    }

    function readTxtFileIntoTextarea(file, opts) {
        if (!file) return;
        var name = (file.name || "").toLowerCase();
        if (!name.endsWith(".txt") && file.type && file.type !== "text/plain") {
            showToast("Chỉ chấp nhận file .txt");
            return;
        }
        var reader = new FileReader();
        reader.onload = function () {
            var lines = parseUrlLines(reader.result);
            if (!lines.length) {
                showToast("File không có link hợp lệ.");
                return;
            }
            mergeUrlsIntoTextarea(opts.textarea, lines, opts.onUpdated);
            if (opts.fileNameEl) {
                opts.fileNameEl.hidden = false;
                opts.fileNameEl.textContent = file.name + " — " + lines.length + " dòng";
            }
            showToast("Đã thêm " + lines.length + " link từ file.");
        };
        reader.onerror = function () {
            showToast("Không đọc được file.");
        };
        reader.readAsText(file, "UTF-8");
    }

    function initTxtUploadZone(zoneId, inputId, fileNameId, textareaId, onUpdated) {
        var zone = $(zoneId);
        var input = $(inputId);
        if (!zone || !input) return;

        zone.addEventListener("click", function (e) {
            if (e.target === input) return;
            input.click();
        });
        zone.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                input.click();
            }
        });
        input.addEventListener("change", function () {
            if (input.files && input.files[0]) {
                readTxtFileIntoTextarea(input.files[0], {
                    textarea: $(textareaId),
                    fileNameEl: $(fileNameId),
                    onUpdated: onUpdated
                });
            }
            input.value = "";
        });
        ["dragenter", "dragover"].forEach(function (ev) {
            zone.addEventListener(ev, function (e) {
                e.preventDefault();
                zone.classList.add("is-dragover");
            });
        });
        zone.addEventListener("dragleave", function (e) {
            e.preventDefault();
            zone.classList.remove("is-dragover");
        });
        zone.addEventListener("drop", function (e) {
            e.preventDefault();
            zone.classList.remove("is-dragover");
            var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (f) {
                readTxtFileIntoTextarea(f, {
                    textarea: $(textareaId),
                    fileNameEl: $(fileNameId),
                    onUpdated: onUpdated
                });
            }
        });
    }

    function initSubmitUploadZone() {
        initTxtUploadZone(
            "icSubmitUploadZone",
            "icSubmitFileInput",
            "icSubmitUploadFileName",
            "icSubmitUrls",
            updateSubmitLiveStats
        );
    }

    function initCheckFreeUploadZone() {
        initTxtUploadZone(
            "icCheckFreeUploadZone",
            "icCheckFreeFileInput",
            "icCheckFreeUploadFileName",
            "icCheckFreeUrls",
            null
        );
    }

    function runSubmitIndexing() {
        if (!authToken()) {
            showToast("Đăng nhập để submit.");
            return;
        }
        var urls = parseUrlLines($("icSubmitUrls") && $("icSubmitUrls").value);
        if (!urls.length) {
            showToast("Nhập ít nhất một URL.");
            return;
        }

        var projectNameEl = $("icSubmitProjectName");
        var projectName = projectNameEl && projectNameEl.value.trim();

        var btn = $("icBtnSubmitIndexing");
        var msg = $("icSubmitMsg");
        if (btn) { btn.disabled = true; btn.textContent = "Đang gửi…"; }
        if (msg) msg.hidden = true;

        fetch("/api/index-control/submit-indexing", {
            method: "POST",
            credentials: "same-origin",
            headers: authHeaders(),
            body: JSON.stringify({
                urls: urls,
                url_meta: buildSubmitUrlMeta(urls),
                project_name: projectName || null
            })
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                return r.json();
            })
            .then(function (data) {
                var card = $("icSubmitResultsCard");
                var summary = $("icSubmitSummary");
                var list = $("icSubmitResultList");
                if (card) card.hidden = false;

                if (data.quota) state.quota = data.quota;

                if (!data.ok && (data.error === "quota_exceeded" || data.error === "service_unavailable")) {
                    if (msg) {
                        msg.hidden = false;
                        msg.textContent = data.message || "Submit thất bại, vui lòng thử lại sau.";
                        msg.className = "ic-status-line ic-status-line--err";
                    }
                    showToast(data.message || "Submit thất bại, vui lòng thử lại sau.");
                    updateSubmitLiveStats();
                    return;
                }

                var sum = data.summary || {};
                if (summary) {
                    summary.innerHTML =
                        '<span class="ic-badge ic-badge--ok">Đã gửi: ' + esc(String(sum.sent || 0)) + "</span> " +
                        '<span class="ic-badge ic-badge--warn">Trùng lặp: ' + esc(String(sum.duplicate || 0)) + "</span> " +
                        '<span class="ic-badge ic-badge--err">Lỗi: ' + esc(String(sum.error || 0)) + "</span>";
                }
                if (list) {
                    list.innerHTML = (data.items || []).map(function (it) {
                        return '<li class="ic-result-list__item ic-result-list__item--' + esc(it.status) + '">' +
                            '<span class="ic-badge ic-badge--' + statusClass(it.status) + '">' +
                            esc(statusLabel(it.status)) + "</span>" +
                            '<span class="ic-result-list__url">' + esc(it.url) + "</span>" +
                            (it.message ? '<span class="ic-result-list__msg">' + esc(it.message) + "</span>" : "") +
                            "</li>";
                    }).join("");
                }

                if (msg) {
                    msg.hidden = false;
                    msg.className = data.ok ? "ic-status-line ic-status-line--ok" : "ic-status-line ic-status-line--err";
                    msg.textContent = data.message || (data.ok ? "Submit thành công." : "Submit thất bại, vui lòng thử lại sau.");
                }
                showToast(data.message || (data.ok ? "Submit thành công." : "Submit thất bại, vui lòng thử lại sau."));
                updateSubmitLiveStats();
                if (data.ok && data.project_id) {
                    loadSubmitProjects();
                }
                if (document.querySelector('.ic-panel[data-ic-panel="overview"]:not([hidden])')) {
                    loadOverview();
                }
            })
            .catch(function (e) {
                showToast(String(e && e.message) === "auth" ? "Phiên hết hạn." : "Submit thất bại, vui lòng thử lại sau.");
            })
            .finally(function () {
                if (btn) { btn.disabled = false; btn.textContent = "Submit Indexing"; }
            });
    }

    function checkFreeLabel(status) {
        if (status === "pending") return "";
        if (status === "waiting_captcha") return "Chờ xác minh";
        if (!status) return "—";
        if (status === "indexed" || status === "INDEX") return "Index";
        if (status === "not_indexed" || status === "NO_INDEX") return "No";
        if (status === "captcha_required" || status === "CAPTCHA_REQUIRED") return "Captcha";
        if (status === "pending_retry" || status === "PENDING_RETRY") return "Retry";
        if (status === "unknown" || status === "UNKNOWN") return "Unknown";
        if (status === "error" || status === "ERROR") return "Error";
        if (status === "not_run") return "Chưa chạy";
        return String(status);
    }

    function checkFreeStatusBadgeHtml(it) {
        if (it.status === "pending") {
            return '<span class="ic-checkfree-spinner" aria-label="Đang kiểm tra" role="status"></span>';
        }
        var label = it.status_label || checkFreeLabel(it.status || it.index_status);
        return '<span class="ic-badge ic-badge--' + checkFreeClass(it.status) + '">' + esc(label) + "</span>";
    }

    function checkFreeClass(status) {
        if (status === "pending") return "pending";
        if (status === "waiting_captcha") return "captcha";
        if (!status) return "neutral";
        if (status === "indexed" || status === "INDEX") return "index";
        if (status === "not_indexed" || status === "NO_INDEX") return "no";
        if (status === "captcha_required" || status === "CAPTCHA_REQUIRED") return "captcha";
        if (status === "pending_retry" || status === "PENDING_RETRY") return "unknown";
        if (status === "unknown" || status === "UNKNOWN" || status === "not_run") return "unknown";
        if (status === "error" || status === "ERROR") return "no";
        return "neutral";
    }

    function mapCheckFreeReason(item) {
        var msg = (item.message || "").trim();
        if (msg) return msg;
        if (item.status === "pending") return "—";
        return checkFreeLabel(item.status || item.index_status);
    }

    function normalizeCheckFreeUrl(url) {
        var u = String(url || "").trim();
        if (!u) return "";
        try {
            var parsed = new URL(u);
            var path = parsed.pathname.replace(/\/+$/, "") || "/";
            return (parsed.protocol + "//" + parsed.hostname + path + parsed.search).toLowerCase();
        } catch (_) {
            return u.replace(/\/+$/, "").toLowerCase();
        }
    }

    function findCheckFreeRow(url) {
        var rows = state.checkFree.rows || [];
        var target = normalizeCheckFreeUrl(url);
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].url === url || normalizeCheckFreeUrl(rows[i].url) === target) return rows[i];
        }
        return null;
    }

    function buildCheckFreeRows(urls, opts) {
        opts = opts || {};
        var pending = !!opts.pending;
        return (urls || []).map(function (url) {
            return {
                url: url,
                status: pending ? "pending" : null,
                status_label: pending ? "" : "—",
                index_status: null,
                message: "",
                http_status: "—",
                indexability: "—",
                page_title: "—"
            };
        });
    }

    function showCheckFreeResults() {
        var card = $("icCheckFreeResultsCard");
        if (card) card.hidden = false;
        renderCheckFreeResults(state.checkFree.rows);
    }

    function resetCheckFreeIndexPending() {
        (state.checkFree.rows || []).forEach(function (row) {
            row.status = "pending";
            row.status_label = "";
            row.index_status = null;
            row.message = "";
        });
        renderCheckFreeResults(state.checkFree.rows);
    }

    function getNoIndexUrls() {
        return (state.checkFree.rows || []).filter(function (row) {
            var st = String(row.status || row.index_status || "").toLowerCase();
            if (!st || st === "pending" || st === "waiting_captcha" || st === "not_run") return false;
            if (st === "indexed" || st === "index") return false;
            if (st === "captcha_required") return false;
            if (st === "pending_retry") return false;
            return st === "not_indexed" || st === "no_index" || st === "no";
        }).map(function (row) { return row.url; });
    }

    function finalizeCheckFreePending(opts) {
        opts = opts || {};
        var status = opts.status || "not_run";
        var label = opts.label || "Chưa chạy";
        var message = opts.message || "Chưa kiểm tra trong lượt này.";
        var pendingSet = null;
        if (opts.onlyUrls && opts.onlyUrls.length) {
            pendingSet = {};
            opts.onlyUrls.forEach(function (u) {
                pendingSet[normalizeCheckFreeUrl(u)] = true;
            });
        }
        (state.checkFree.rows || []).forEach(function (row) {
            if (row.status !== "pending" && row.status !== "waiting_captcha") return;
            if (pendingSet && !pendingSet[normalizeCheckFreeUrl(row.url)]) return;
            row.status = status;
            row.status_label = label;
            row.index_status = status;
            row.message = message;
            refreshCheckFreeRow(row.url);
        });
    }

    function markWaitingCaptcha(urls) {
        (urls || []).forEach(function (u) {
            var row = findCheckFreeRow(u);
            if (!row) return;
            if (row.status && row.status !== "pending") return;
            row.status = "waiting_captcha";
            row.status_label = "Chờ xác minh";
            row.index_status = "waiting_captcha";
            row.message = "Đang chờ xác minh Google — không đánh dấu No Index.";
            refreshCheckFreeRow(u);
        });
    }

    function showCaptchaModal(data) {
        var modal = $("icCaptchaModal");
        var msg = $("icCaptchaModalMsg");
        var meta = $("icCaptchaModalMeta");
        if (msg) {
            msg.textContent = (data && data.message) ||
                "Google yêu cầu xác minh. Kết quả đã check được giữ nguyên.";
        }
        if (meta) {
            var pending = (data && data.pending_count) || (data && data.pending_urls && data.pending_urls.length) || 0;
            meta.textContent = "Đã xong " + (data && data.done || 0) + "/" + (data && data.total || 0) +
                " — còn " + pending + " URL chờ tiếp tục.";
        }
        if (modal) modal.hidden = false;
    }

    function hideCaptchaModal() {
        var modal = $("icCaptchaModal");
        if (modal) modal.hidden = true;
    }

    function updateCheckFreeButtons() {
        var hasUrls = (state.checkFree.urls || []).length > 0;
        var hasRows = (state.checkFree.rows || []).length > 0;
        var hasNoLinks = getNoIndexUrls().length > 0;
        var streaming = !!state.checkFree.streaming;
        var idxBtn = $("icBtnCheckFreeIndex");
        var respBtn = $("icBtnCheckFreeResponse");
        var copyBtn = $("icBtnCheckFreeCopy");
        if (idxBtn) idxBtn.disabled = !hasUrls || streaming;
        if (respBtn) respBtn.disabled = !hasNoLinks || streaming;
        if (copyBtn) copyBtn.disabled = !hasRows || streaming;
    }

    function renderCheckFreeResults(items) {
        var tbody = $("icCheckFreeTableBody");
        var cards = $("icCheckFreeCards");
        var meta = $("icCheckFreeResultMeta");
        items = items || [];

        if (meta) meta.textContent = items.length ? items.length + " URL" : "";

        if (tbody) {
            tbody.innerHTML = items.map(function (it, idx) {
                var reason = mapCheckFreeReason(it);
                var httpStatus = it.http_status || "—";
                var indexability = it.indexability || "—";
                var pageTitle = it.title || it.page_title || "—";
                return "<tr data-url=\"" + esc(it.url) + "\">" +
                    '<td class="ic-checkfree-col-stt">' + esc(String(idx + 1)) + "</td>" +
                    '<td class="ic-url-cell">' + esc(it.url) + "</td>" +
                    "<td>" + checkFreeStatusBadgeHtml(it) + "</td>" +
                    '<td class="ic-checkfree-col-response">' + esc(httpStatus) + "</td>" +
                    '<td class="ic-checkfree-col-indexability">' + esc(indexability) + "</td>" +
                    '<td class="ic-checkfree-col-title">' + esc(pageTitle) + "</td>" +
                    '<td class="ic-checkfree-reason">' + esc(reason) + "</td>" +
                    "</tr>";
            }).join("");
        }

        if (cards) {
            cards.innerHTML = items.map(function (it, idx) {
                var reason = mapCheckFreeReason(it);
                return '<article class="ic-checkfree-card" data-url="' + esc(it.url) + '">' +
                    '<div class="ic-checkfree-card__head">' +
                    '<span class="ic-checkfree-card__stt">#' + esc(String(idx + 1)) + "</span>" +
                    checkFreeStatusBadgeHtml(it) +
                    "</div>" +
                    '<p class="ic-checkfree-card__url">' + esc(it.url) + "</p>" +
                    '<div class="ic-checkfree-card__row"><span class="ic-checkfree-card__label">Mã phản hồi</span><span>' +
                    esc(it.http_status || "—") + "</span></div>" +
                    '<div class="ic-checkfree-card__row"><span class="ic-checkfree-card__label">Khả năng index</span><span>' +
                    esc(it.indexability || "—") + "</span></div>" +
                    '<div class="ic-checkfree-card__row"><span class="ic-checkfree-card__label">Tiêu đề</span><span>' +
                    esc(it.title || it.page_title || "—") + "</span></div>" +
                    '<p class="ic-checkfree-card__reason"><span class="ic-checkfree-card__reason-label">Gợi ý:</span> ' +
                    esc(reason) + "</p>" +
                    "</article>";
            }).join("");
        }
        updateCheckFreeExportButton();
        updateCheckFreeButtons();
    }

    function refreshCheckFreeRow(url) {
        var row = findCheckFreeRow(url);
        if (!row) return;
        var idx = state.checkFree.rows.indexOf(row);
        var tr = document.querySelector("#icCheckFreeTableBody tr:nth-child(" + (idx + 1) + ")");
        if (tr) {
            var cells = tr.querySelectorAll("td");
            if (cells.length >= 7) {
                cells[2].innerHTML = checkFreeStatusBadgeHtml(row);
                cells[3].textContent = row.http_status || "—";
                cells[4].textContent = row.indexability || "—";
                cells[5].textContent = row.title || row.page_title || "—";
                cells[6].textContent = mapCheckFreeReason(row);
            }
        }
        var card = document.querySelector(".ic-checkfree-card:nth-child(" + (idx + 1) + ")");
        if (card) {
            var head = card.querySelector(".ic-checkfree-card__head");
            if (head) {
                var oldBadge = head.querySelector(".ic-badge, .ic-checkfree-spinner");
                var badgeHtml = checkFreeStatusBadgeHtml(row);
                if (oldBadge) {
                    oldBadge.outerHTML = badgeHtml;
                } else {
                    head.insertAdjacentHTML("beforeend", badgeHtml);
                }
            }
            var rows = card.querySelectorAll(".ic-checkfree-card__row span:last-child");
            if (rows[0]) rows[0].textContent = row.http_status || "—";
            if (rows[1]) rows[1].textContent = row.indexability || "—";
            if (rows[2]) rows[2].textContent = row.title || row.page_title || "—";
            var reasonEl = card.querySelector(".ic-checkfree-card__reason");
            if (reasonEl) {
                reasonEl.innerHTML = '<span class="ic-checkfree-card__reason-label">Gợi ý:</span> ' + esc(mapCheckFreeReason(row));
            }
        }
        updateCheckFreeExportButton();
        updateCheckFreeButtons();
    }

    function loadCheckFreeUrls() {
        var ta = $("icCheckFreeUrls");
        var countEl = $("icCheckFreeUrlCount");
        var loadBtn = $("icBtnCheckFreeLoad");
        if (!ta) return;

        var seen = {};
        var valid = [];
        var skipped = 0;
        String(ta.value || "").split(/\r?\n/).forEach(function (line) {
            var u = line.trim();
            if (!u) {
                skipped += 1;
                return;
            }
            if (!isValidHttpUrl(u)) {
                skipped += 1;
                return;
            }
            if (seen[u]) {
                skipped += 1;
                return;
            }
            seen[u] = true;
            valid.push(u);
        });

        ta.value = valid.join("\n");
        state.checkFree.urls = valid;
        state.checkFree.rows = buildCheckFreeRows(valid);

        if (countEl) {
            countEl.hidden = false;
            var maxN = state.checkFree.maxUrls || 100;
            countEl.textContent = valid.length + " URL hợp lệ" +
                (skipped ? " (đã bỏ " + skipped + " dòng trống/trùng/không hợp lệ)" : "") +
                (valid.length > maxN ? " — mỗi lượt kiểm tra tối đa " + maxN + " URL đầu" : "");
        }
        if (loadBtn) loadBtn.classList.add("is-done");

        if (valid.length) {
            showCheckFreeResults();
        } else {
            var card = $("icCheckFreeResultsCard");
            if (card) card.hidden = true;
        }

        var prog = $("icCheckFreeProgress");
        if (prog) prog.hidden = true;

        updateCheckFreeButtons();
        showToast(valid.length ? "Đã tải " + valid.length + " URL vào bảng." : "Chưa có URL hợp lệ.");
        updateCheckFreeExportButton();
    }

    function parseSseChunk(buffer, onEvent) {
        var blocks = buffer.split("\n\n");
        var rest = blocks.pop() || "";
        blocks.forEach(function (block) {
            var lines = block.split("\n");
            var evt = "message";
            var data = "";
            lines.forEach(function (line) {
                if (line.indexOf("event:") === 0) evt = line.slice(6).trim();
                if (line.indexOf("data:") === 0) data += line.slice(5).trim();
            });
            if (!data) return;
            try {
                onEvent(evt, JSON.parse(data));
            } catch (_) {}
        });
        return rest;
    }

    function streamCheckFree(phase, onDone, opts) {
        opts = opts || {};
        var projectNameEl = $("icCheckFreeProjectName");
        var projectName = projectNameEl && projectNameEl.value.trim();
        var body = {
            urls: opts.urls || state.checkFree.urls,
            phase: phase,
            project_name: projectName || null
        };
        if (opts.resume && opts.checkId) {
            body.resume = true;
            body.check_id = opts.checkId;
            body.urls = opts.urls || state.checkFree.pendingUrls || [];
        }
        var finishedClean = false;
        return fetch("/api/index-control/check-free/stream", {
            method: "POST",
            credentials: "same-origin",
            headers: authHeaders(),
            body: JSON.stringify(body)
        }).then(function (response) {
            if (response.status === 401) throw new Error("auth");
            if (!response.ok || !response.body) throw new Error("stream");
            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = "";

            function pump() {
                return reader.read().then(function (result) {
                    if (result.done) return;
                    buffer += decoder.decode(result.value, { stream: true });
                    buffer = parseSseChunk(buffer, handleStreamEvent);
                    return pump();
                });
            }

            function handleStreamEvent(evt, data) {
                if (evt === "init") {
                    if (data.max_urls) state.checkFree.maxUrls = data.max_urls;
                    if (data.check_id) state.checkFree.lastCheckId = data.check_id;
                    var prog = $("icCheckFreeProgress");
                    if (prog && data.resume) {
                        prog.hidden = false;
                        prog.textContent = "Tiếp tục từ " + (data.done_count || 0) + "/" + (data.total || 0);
                    }
                }
                if (evt === "row" && data.item) {
                    var item = data.item;
                    var row = findCheckFreeRow(item.url);
                    if (!row && phase === "index") {
                        row = {
                            url: item.url,
                            http_status: "—",
                            indexability: "—",
                            page_title: "—",
                            title: "—"
                        };
                        state.checkFree.rows.push(row);
                        renderCheckFreeResults(state.checkFree.rows);
                        row = findCheckFreeRow(item.url);
                    }
                    if (row) {
                        if (phase === "index") {
                            row.status = item.status || item.index_status;
                            row.index_status = item.index_status;
                            row.status_label = item.status_label;
                            row.message = item.message;
                            row.reason = item.reason;
                            row.query = item.query;
                            row.matched_url = item.matched_url;
                            row.title = item.title || "—";
                            row.checked_at = item.checked_at || null;
                            row.retry_count = item.retry_count || 0;
                            row.source = item.source;
                        } else if (phase === "response") {
                            row.http_status = item.http_status || "—";
                            row.indexability = item.indexability || "—";
                            row.page_title = item.page_title || "—";
                            if (!row.title || row.title === "—") row.title = item.page_title || "—";
                            if (item.message && !row.message) row.message = item.message;
                        }
                        refreshCheckFreeRow(item.url);
                    }
                }
                if (evt === "progress") {
                    var progEl = $("icCheckFreeProgress");
                    if (progEl) {
                        progEl.hidden = false;
                        progEl.className = "ic-status-line";
                        progEl.textContent = "Đã kiểm tra " + (data.done || 0) + "/" + (data.total || 0) + " URL";
                    }
                }
                if (evt === "captcha_required") {
                    finishedClean = true;
                    state.checkFree.pausedCheckId = data.check_id || state.checkFree.lastCheckId;
                    state.checkFree.lastCheckId = state.checkFree.pausedCheckId;
                    state.checkFree.pendingUrls = data.pending_urls || [];
                    markWaitingCaptcha(state.checkFree.pendingUrls);
                    showCaptchaModal(data);
                    var msgCap = $("icCheckFreeMsg");
                    if (msgCap) {
                        msgCap.hidden = false;
                        msgCap.className = "ic-status-line ic-status-line--warn";
                        msgCap.textContent = data.message || "Google yêu cầu xác minh — batch đã tạm dừng.";
                    }
                    updateCheckFreeExportButton();
                    updateCheckFreeButtons();
                    if (typeof onDone === "function") onDone(data, { captcha: true });
                }
                if (evt === "done") {
                    finishedClean = true;
                    if (phase === "index" && data.check_id) {
                        state.checkFree.lastCheckId = data.check_id;
                    }
                    state.checkFree.pausedCheckId = null;
                    state.checkFree.pendingUrls = [];
                    hideCaptchaModal();
                    finalizeCheckFreePending({
                        status: "not_run",
                        label: "Chưa chạy",
                        message: "Vượt giới hạn lượt này hoặc không được gửi lên server."
                    });
                    updateCheckFreeExportButton();
                    updateCheckFreeButtons();
                    var msg = $("icCheckFreeMsg");
                    if (msg) {
                        msg.hidden = false;
                        msg.className = "ic-status-line ic-status-line--ok";
                        msg.textContent = phase === "index"
                            ? "Hoàn tất check index."
                            : "Hoàn tất check phản hồi link.";
                    }
                    if (typeof onDone === "function") onDone(data);
                }
                if (evt === "error") {
                    showToast((data && data.message) || "Lỗi kiểm tra index.");
                }
            }

            return pump().then(function () {
                buffer = parseSseChunk(buffer + "\n\n", handleStreamEvent);
                if (!finishedClean && phase === "index") {
                    finalizeCheckFreePending({
                        status: "not_run",
                        label: "Chưa chạy",
                        message: "Kết nối bị ngắt trước khi hoàn tất — thử chạy lại."
                    });
                }
            });
        });
    }

    function resumeCheckFreeAfterCaptcha() {
        if (!authToken()) {
            showToast("Đăng nhập để tiếp tục.");
            return;
        }
        var checkId = state.checkFree.pausedCheckId || state.checkFree.lastCheckId;
        var pending = state.checkFree.pendingUrls || [];
        if (!checkId || !pending.length) {
            showToast("Không còn URL chờ tiếp tục.");
            hideCaptchaModal();
            return;
        }
        hideCaptchaModal();
        var btn = $("icBtnCheckFreeIndex");
        var prog = $("icCheckFreeProgress");
        state.checkFree.streaming = true;
        updateCheckFreeButtons();
        if (btn) btn.textContent = "Đang tiếp tục…";
        if (prog) {
            prog.hidden = false;
            prog.textContent = "Tiếp tục kiểm tra " + pending.length + " URL còn lại…";
        }
        pending.forEach(function (u) {
            var row = findCheckFreeRow(u);
            if (row && (row.status === "waiting_captcha" || row.status === "not_run" || row.status === "pending")) {
                row.status = "pending";
                row.status_label = "";
                row.message = "";
                refreshCheckFreeRow(u);
            }
        });

        streamCheckFree("index", null, { resume: true, checkId: checkId, urls: pending })
            .catch(function (e) {
                showToast(String(e && e.message) === "auth" ? "Phiên hết hạn." : "Lỗi tiếp tục kiểm tra.");
            })
            .finally(function () {
                state.checkFree.streaming = false;
                if (btn) btn.textContent = "2. Check index";
                updateCheckFreeButtons();
            });
    }

    function restorePausedCheckFree() {
        if (!authToken()) return;
        fetch("/api/index-control/check-free/paused", {
            credentials: "same-origin",
            headers: authHeaders()
        })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data || !data.paused || !data.job) return;
                var job = data.job;
                state.checkFree.pausedCheckId = job.check_id;
                state.checkFree.lastCheckId = job.check_id;
                state.checkFree.pendingUrls = job.pending_urls || [];
                if (!state.checkFree.pendingUrls.length) return;
                markWaitingCaptcha(state.checkFree.pendingUrls);
                showCaptchaModal({
                    message: job.reason || "Google yêu cầu xác minh — phiên tạm dừng (khôi phục sau F5).",
                    pending_urls: state.checkFree.pendingUrls,
                    pending_count: state.checkFree.pendingUrls.length,
                    done: job.done_count,
                    total: job.total,
                    check_id: job.check_id
                });
            })
            .catch(function () {});
    }

    function runCheckFreeIndex() {
        if (!authToken()) {
            showToast("Đăng nhập để check index.");
            return;
        }
        if (!(state.checkFree.rows || []).length) {
            loadCheckFreeUrls();
        }
        if (!(state.checkFree.rows || []).length) {
            showToast("Bấm bước 1 để tải danh sách URL.");
            return;
        }

        var btn = $("icBtnCheckFreeIndex");
        var prog = $("icCheckFreeProgress");
        var msg = $("icCheckFreeMsg");
        state.checkFree.streaming = true;
        updateCheckFreeButtons();
        if (btn) btn.textContent = "Đang check index…";
        if (prog) prog.hidden = false;
        if (msg) msg.hidden = true;

        resetCheckFreeIndexPending();

        streamCheckFree("index")
            .catch(function (e) {
                showToast(String(e && e.message) === "auth" ? "Phiên hết hạn." : "Lỗi kiểm tra index.");
            })
            .finally(function () {
                state.checkFree.streaming = false;
                if (btn) btn.textContent = "2. Check index";
                updateCheckFreeButtons();
            });
    }

    function submitNoLinksToIndexing() {
        var noUrls = getNoIndexUrls();
        if (!noUrls.length) {
            showToast("Chưa có link NO. Chạy bước 2 Check index trước.");
            return;
        }

        var submitTa = $("icSubmitUrls");
        if (submitTa) {
            submitTa.value = noUrls.join("\n");
            updateSubmitLiveStats();
        }

        switchTab(TABS.SUBMIT, { skipLoadQuota: false });
        showToast("Đã chuyển " + noUrls.length + " link NO sang Submit Indexing.");
    }

    function toggleCheckFreeCopyMenu(force) {
        var menu = $("icCheckFreeCopyMenu");
        var btn = $("icBtnCheckFreeCopy");
        if (!menu || !btn) return;
        var open = typeof force === "boolean" ? force : !menu.classList.contains("is-open");
        menu.classList.toggle("is-open", open);
        menu.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function copyCheckFreeGroup(group) {
        var urls = (state.checkFree.rows || []).filter(function (row) {
            var st = row.status || row.index_status || "";
            if (group === "indexed") return st === "indexed";
            return st && st !== "indexed" && st !== "pending";
        }).map(function (row) { return row.url; });

        if (!urls.length) {
            showToast("Không có URL trong nhóm này.");
            toggleCheckFreeCopyMenu(false);
            return;
        }

        var text = urls.join("\n");
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () {
                showToast("Đã copy " + urls.length + " URL.");
            }).catch(function () {
                showToast("Không copy được.");
            });
        } else {
            showToast("Trình duyệt không hỗ trợ copy.");
        }
        toggleCheckFreeCopyMenu(false);
    }

    function hasCheckedExportRows() {
        return getExportableRows().some(function (row) {
            var st = row.status || row.index_status;
            return st && st !== "pending";
        });
    }

    function updateCheckFreeExportButton() {
        var wrap = $("icCheckFreeExportWrap");
        var btn = $("icBtnCheckFreeExport");
        var show = hasCheckedExportRows();
        if (wrap) wrap.hidden = !show;
        if (btn) btn.disabled = !show;
    }

    function getExportableRows() {
        return (state.checkFree.rows || []).filter(function (row) {
            return row && row.url;
        });
    }

    function exportCurrentCheckFreeExcel() {
        if (!authToken()) {
            showToast("Đăng nhập để xuất file.");
            return;
        }
        var rows = getExportableRows().filter(function (row) {
            var st = row.status || row.index_status;
            return st && st !== "pending";
        });
        if (!rows.length) {
            showToast("Chưa có kết quả để xuất.");
            return;
        }

        var payload = {
            check_id: state.checkFree.lastCheckId || null,
            rows: rows.map(function (row) {
                return {
                    url: row.url,
                    query: row.query,
                    status: row.status,
                    index_status: row.index_status,
                    status_label: row.status_label,
                    http_status: row.http_status,
                    indexability: row.indexability,
                    matched_url: row.matched_url,
                    title: row.title,
                    page_title: row.page_title,
                    reason: row.reason,
                    message: row.message,
                    checked_at: row.checked_at,
                    retry_count: row.retry_count
                };
            })
        };

        var btn = $("icBtnCheckFreeExport");
        if (btn) { btn.disabled = true; btn.textContent = "Đang tạo file…"; }

        fetch("/api/index-control/check-free/export", {
            method: "POST",
            credentials: "same-origin",
            headers: authHeaders(),
            body: JSON.stringify(payload)
        })
            .then(function (r) {
                if (r.status === 401) throw new Error("auth");
                if (!r.ok) throw new Error("export");
                return r.blob();
            })
            .then(function (blob) {
                var a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = state.checkFree.lastCheckId
                    ? "check-index-" + state.checkFree.lastCheckId + ".xlsx"
                    : "check-index-ket-qua.xlsx";
                document.body.appendChild(a);
                a.click();
                a.remove();
                setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
                showToast("Đã tải file Excel.");
            })
            .catch(function (e) {
                showToast(String(e && e.message) === "auth" ? "Phiên hết hạn." : "Xuất Excel thất bại.");
            })
            .finally(function () {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = "Xuất kết quả";
                    updateCheckFreeExportButton();
                }
            });
    }

    function init() {
        document.querySelectorAll(".ic-tab").forEach(function (btn) {
            btn.addEventListener("click", function () {
                switchTab(btn.getAttribute("data-ic-tab"));
            });
        });

        window.addEventListener("hashchange", function () {
            var m = (window.location.hash || "").match(/tab=([a-z0-9_-]+)/i);
            if (m) switchTab(m[1], { skipHash: true });
        });

        var submitTa = $("icSubmitUrls");
        if (submitTa) submitTa.addEventListener("input", updateSubmitLiveStats);

        initSubmitUploadZone();
        initCheckFreeUploadZone();

        var submitBtn = $("icBtnSubmitIndexing");
        if (submitBtn) submitBtn.addEventListener("click", runSubmitIndexing);

        document.querySelectorAll(".ic-submit-subtab").forEach(function (btn) {
            btn.addEventListener("click", function () {
                switchSubmitTab(btn.getAttribute("data-submit-tab"));
            });
        });

        var projectsDeleteAll = $("icBtnProjectsDeleteAll");
        if (projectsDeleteAll) projectsDeleteAll.addEventListener("click", deleteAllSubmitProjects);

        var projectBack = $("icBtnProjectBack");
        if (projectBack) projectBack.addEventListener("click", showProjectListView);

        var projectDelete = $("icBtnProjectDelete");
        if (projectDelete) projectDelete.addEventListener("click", deleteActiveProject);

        var projectExport = $("icBtnProjectExport");
        if (projectExport) projectExport.addEventListener("click", exportActiveProject);

        var projectCopyIndexed = $("icBtnProjectCopyIndexed");
        if (projectCopyIndexed) {
            projectCopyIndexed.addEventListener("click", function () {
                var urls = (state.activeProject && state.activeProject.items || [])
                    .filter(function (it) { return it.indexed === "Index"; })
                    .map(function (it) { return it.url; });
                copyProjectUrls(urls);
            });
        }

        var projectCopyAll = $("icBtnProjectCopyAll");
        if (projectCopyAll) {
            projectCopyAll.addEventListener("click", function () {
                var checked = getProjectCheckedUrls();
                if (checked.length) {
                    copyProjectUrls(checked);
                    return;
                }
                var urls = (state.activeProject && state.activeProject.items || [])
                    .map(function (it) { return it.url; });
                copyProjectUrls(urls);
            });
        }

        var loadBtn = $("icBtnCheckFreeLoad");
        if (loadBtn) loadBtn.addEventListener("click", loadCheckFreeUrls);

        var indexBtn = $("icBtnCheckFreeIndex");
        if (indexBtn) indexBtn.addEventListener("click", runCheckFreeIndex);

        var respBtn = $("icBtnCheckFreeResponse");
        if (respBtn) respBtn.addEventListener("click", submitNoLinksToIndexing);

        var copyBtn = $("icBtnCheckFreeCopy");
        if (copyBtn) {
            copyBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                toggleCheckFreeCopyMenu();
            });
        }

        var resultsFilterForm = $("icResultsFilterForm");
        if (resultsFilterForm) {
            resultsFilterForm.addEventListener("submit", function (e) {
                e.preventDefault();
                readResultsFiltersFromForm();
                loadResults();
            });
        }

        var resultsBack = $("icBtnResultsBack");
        if (resultsBack) resultsBack.addEventListener("click", showResultsListView);

        var resultsRecheck = $("icBtnResultsRecheck");
        if (resultsRecheck) resultsRecheck.addEventListener("click", recheckActiveResultBatch);

        var resultsExportLeft = $("icBtnResultsExportLeft");
        if (resultsExportLeft) resultsExportLeft.addEventListener("click", exportActiveResultBatch);

        var resultsExportRight = $("icBtnResultsExportRight");
        if (resultsExportRight) resultsExportRight.addEventListener("click", exportActiveResultBatch);

        var resultsIndexFilter = $("icResultsDetailIndexFilter");
        if (resultsIndexFilter) {
            resultsIndexFilter.addEventListener("change", function () {
                state.resultsDetailIndexFilter = resultsIndexFilter.value || "";
                if (state.activeResultBatch) renderResultsDetail(state.activeResultBatch);
            });
        }

        var exportBtn = $("icBtnCheckFreeExport");
        if (exportBtn) exportBtn.addEventListener("click", exportCurrentCheckFreeExcel);

        var captchaResume = $("icCaptchaResumeBtn");
        if (captchaResume) captchaResume.addEventListener("click", resumeCheckFreeAfterCaptcha);
        var captchaClose = $("icCaptchaCloseBtn");
        if (captchaClose) captchaClose.addEventListener("click", hideCaptchaModal);
        document.querySelectorAll("[data-ic-captcha-close]").forEach(function (el) {
            el.addEventListener("click", hideCaptchaModal);
        });
        var captchaOpenGoogle = $("icCaptchaOpenGoogleBtn");
        if (captchaOpenGoogle) {
            captchaOpenGoogle.addEventListener("click", function () {
                window.open("https://www.google.com/search?q=site:example.com", "_blank", "noopener");
            });
        }

        restorePausedCheckFree();

        document.querySelectorAll(".ic-checkfree-copy-item").forEach(function (btn) {
            btn.addEventListener("click", function () {
                copyCheckFreeGroup(btn.getAttribute("data-copy-group"));
            });
        });

        document.addEventListener("click", function (e) {
            var wrap = document.querySelector(".ic-checkfree-copy-wrap");
            if (!wrap || wrap.contains(e.target)) return;
            toggleCheckFreeCopyMenu(false);
        });

        applyIncomingParams();
        var tab = readInitialTab();
        var hasUrl = $("icSubmitUrls") && $("icSubmitUrls").value || $("icCheckFreeUrls") && $("icCheckFreeUrls").value;
        if (hasUrl && !new URLSearchParams(window.location.search).get("tab")) {
            tab = $("icCheckFreeUrls") && $("icCheckFreeUrls").value ? TABS.CHECK_FREE : TABS.SUBMIT;
        }
        switchTab(tab, {
            skipLoadOverview: tab !== TABS.OVERVIEW,
            skipLoadQuota: tab !== TABS.SUBMIT,
            skipLoadResults: tab !== TABS.RESULTS
        });
        if (tab === TABS.OVERVIEW) loadOverview();
        if (tab === TABS.RESULTS) loadResults();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
