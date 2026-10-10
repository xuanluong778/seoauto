/**
 * Technical Health Dashboard — reads technical_dashboard_v3, then v2, legacy fallback.
 */
(function (global) {
    "use strict";

    var FRONT_NAV_TO_V2 = {
        security_ux: "security_http",
        security_http: "security_http",
        ux_mobile: "ux_mobile",
        gsc: "gsc_insights",
        gsc_insights: "gsc_insights",
        history: "audit_history",
    };

    var V2_TO_FRONT_NAV = {
        security_http: "security_http",
        ux_mobile: "ux_mobile",
        gsc_insights: "gsc",
        audit_history: "history",
    };

    function safeObj(o) {
        return o && typeof o === "object" ? o : null;
    }

    function safeArr(a) {
        return Array.isArray(a) ? a : [];
    }

    function getDash(payload) {
        var v3 = safeObj(payload && payload.technical_dashboard_v3);
        if (v3) {
            var sv3 = Number(v3.schema_version);
            if (sv3 >= 3 || safeArr(v3.issues).length || safeArr(v3.priority_issues).length) return v3;
        }
        return safeObj(payload && payload.technical_dashboard_v2);
    }

    function dashSchemaVersion(payload) {
        var d = getDash(payload);
        return d && d.schema_version != null ? Number(d.schema_version) : 0;
    }

    function hasV2(payload) {
        var d = getDash(payload);
        if (!d) return false;
        var sv = Number(d.schema_version) || 0;
        if (sv !== 2 && sv < 3) return false;
        if (safeArr(d.issues).length > 0) return true;
        if (safeArr(d.priority_issues).length > 0) return true;
        var s = safeObj(d.summary);
        if (Number(s.total) > 0) return true;
        var pages = d.pages_scanned != null ? Number(d.pages_scanned) : 0;
        if (!pages && payload && payload.pages_scanned != null) {
            pages = Number(payload.pages_scanned) || 0;
        }
        if (pages > 0 && d.technical_health_score != null) return true;
        return false;
    }

    function frontNavFromV2(navGroup) {
        var g = String(navGroup || "");
        return V2_TO_FRONT_NAV[g] || g;
    }

    function v2NavToFront(navGroup) {
        return frontNavFromV2(navGroup);
    }

    /** Map v2 issue → normalized issue shape used by existing explorer. */
    function v2IssueToNormalized(issue) {
        if (!issue || typeof issue !== "object") return null;
        var urls = safeArr(issue.affected_urls).length
            ? safeArr(issue.affected_urls)
            : safeArr(issue.sample_urls);
        var sev = String(issue.severity || "warning").toLowerCase();
        var legacySev = sev;
        if (sev === "warning") legacySev = "high";
        if (sev === "opportunity") legacySev = "low";
        return {
            id: issue.issue_id || issue.id || "",
            issue_id: issue.issue_id || issue.id || "",
            _issue_type: issue.issue_type || "",
            type: issue.issue_type || "",
            category: issue.category || "other",
            nav_group: issue.nav_group || "",
            sidebar_key: issue.sidebar_key || "",
            title: issue.title || issue.issue_type || "Issue",
            description: issue.description || "",
            source: issue.source || "crawl",
            severity: sev,
            legacy_severity: legacySev,
            status: issue.status || "",
            count: urls.length || 1,
            affected_urls: urls.slice(),
            sample_urls: safeArr(issue.sample_urls).length ? safeArr(issue.sample_urls) : urls.slice(0, 5),
            evidence: safeArr(issue.evidence),
            impact_area: safeArr(issue.impact),
            why_it_matters: issue.why_it_matters || "",
            how_to_fix: issue.how_to_fix || "",
            priority_score: issue.priority_score != null ? issue.priority_score : 0,
            confidence: issue.confidence != null ? issue.confidence : null,
            gsc_badge: issue.gsc_badge || null,
            gsc_clicks: issue.gsc_clicks != null ? issue.gsc_clicks : null,
            gsc_impressions: issue.gsc_impressions != null ? issue.gsc_impressions : null,
            gsc_ctr: issue.gsc_ctr != null ? issue.gsc_ctr : null,
            gsc_position: issue.gsc_position != null ? issue.gsc_position : null,
            gsc_index_verdict: issue.gsc_index_verdict || null,
            gsc_coverage_state: issue.gsc_coverage_state || null,
            gsc_google_canonical: issue.gsc_google_canonical || null,
            gsc_user_canonical: issue.gsc_user_canonical || null,
        };
    }

    function v2PassedToNormalized(row) {
        if (!row || typeof row !== "object") return null;
        return {
            id: row.issue_id || row.id || "passed-" + Math.random().toString(36).slice(2, 8),
            category: row.category || "other",
            title: row.title || "Passed check",
            description: row.title || "",
            source: row.source || "crawl",
            severity: "passed",
            status: "passed",
            count: 0,
            affected_urls: [],
            sample_urls: [],
            impact_area: [],
            why_it_matters: "",
            how_to_fix: "",
            priority_score: 0,
        };
    }

    function resolveIssues(payload) {
        var dash = getDash(payload);
        if (dash && safeArr(dash.issues).length) {
            return safeArr(dash.issues).map(v2IssueToNormalized).filter(Boolean);
        }
        return null;
    }

    function resolvePriorityIssues(payload) {
        var dash = getDash(payload);
        if (dash && safeArr(dash.priority_issues).length) {
            return safeArr(dash.priority_issues).map(function (p) {
                var n = v2IssueToNormalized(p);
                if (!n) return null;
                return {
                    id: n.id,
                    title: n.title,
                    category: n.category,
                    severity: n.severity || n.legacy_severity || "medium",
                    priority_score: n.priority_score,
                    how_to_fix: n.how_to_fix,
                    why_it_matters: n.why_it_matters,
                    sample_urls: n.sample_urls,
                    source: n.source,
                    nav_group: n.nav_group,
                    confidence: n.confidence,
                    evidence: n.evidence,
                };
            }).filter(Boolean);
        }
        return null;
    }

    function resolveSummary(payload) {
        var dash = getDash(payload);
        if (!dash) return null;
        var s = safeObj(dash.summary) || {};
        var passed = safeArr(dash.passed_checks).length;
        if (!passed && payload && Array.isArray(payload.passed_checks)) {
            passed = payload.passed_checks.length;
        }
        return {
            health_score:
                dash.technical_health_score != null
                    ? dash.technical_health_score
                    : dash.health_score != null
                      ? dash.health_score
                      : null,
            critical: Number(s.critical) || 0,
            warning: Number(s.warning) || 0,
            opportunity: Number(s.opportunity) || 0,
            passed: passed,
            pages_scanned: dash.pages_scanned != null ? dash.pages_scanned : payload && payload.pages_scanned,
            scan_mode: dash.scan_mode || null,
            is_v2: true,
        };
    }

    function resolveNavSummaries(payload) {
        var dash = getDash(payload);
        if (!dash || !safeArr(dash.nav_group_summaries).length) return null;
        var out = {};
        safeArr(dash.nav_group_summaries).forEach(function (row) {
            if (!row || !row.group) return;
            var front = frontNavFromV2(row.group);
            if (front === "overview" || front === "audit_history") return;
            var worst = String(row.worst_severity || "passed").toLowerCase();
            out[front] = {
                open: Number(row.open_issues != null ? row.open_issues : row.issue_count) || 0,
                total: Number(row.issue_count) || 0,
                critical: worst === "critical" ? 1 : 0,
                high: worst === "warning" || worst === "high" ? 1 : 0,
                medium: worst === "medium" ? 1 : 0,
                low: worst === "opportunity" || worst === "low" ? 1 : 0,
                worst: worst === "warning" ? "high" : worst === "opportunity" ? "low" : worst,
                passed: 0,
            };
        });
        var pri = safeArr(dash.priority_issues).length;
        out.priority = out.priority || { open: 0, total: 0, critical: 0, high: 0, worst: "passed", passed: 0 };
        out.priority.open = pri || out.priority.open;
        out.passed = { open: safeArr(dash.passed_checks).length, passed: safeArr(dash.passed_checks).length, worst: "passed" };
        function rollup(dest, keys) {
            var row = { open: 0, total: 0, critical: 0, high: 0, medium: 0, low: 0, worst: "passed", passed: 0 };
            keys.forEach(function (k) {
                var s = out[k];
                if (!s) return;
                row.open += Number(s.open) || 0;
                row.total += Number(s.total) || 0;
                row.critical += Number(s.critical) || 0;
                row.high += Number(s.high) || 0;
                row.medium += Number(s.medium) || 0;
                row.low += Number(s.low) || 0;
                row.passed += Number(s.passed) || 0;
                var rank = { critical: 6, warning: 5, high: 5, medium: 4, opportunity: 3, low: 3 };
                if ((rank[s.worst] || 0) > (rank[row.worst] || 0)) row.worst = s.worst;
            });
            out[dest] = row;
        }
        rollup("index_crawl", ["indexability", "crawlability", "internal_links"]);
        rollup("onpage", ["onpage", "structured_data", "ux_mobile"]);
        rollup("perf_security", ["performance", "security_http"]);
        return out;
    }

    /** Enrich payload in-place for legacy renderers. */
    function enrichPayload(payload) {
        if (!payload || typeof payload !== "object") return payload;
        payload.technical_dashboard_v2 = safeObj(payload.technical_dashboard_v2) || null;
        if (!hasV2(payload)) {
            if (payload && payload.documentElement) return payload;
            global.document && global.document.body && global.document.body.classList.remove("tech-dash-v2-mode");
            return payload;
        }
        if (global.document && global.document.body) {
            global.document.body.classList.add("tech-dash-v2-mode");
        }
        var issues = resolveIssues(payload);
        if (issues && issues.length) {
            payload.normalized_issues = issues;
        }
        var pri = resolvePriorityIssues(payload);
        if (pri && pri.length) {
            payload.priority_fixes = pri;
        }
        var dash = getDash(payload);
        if (dash && safeArr(dash.passed_checks).length) {
            payload.passed_checks = safeArr(dash.passed_checks).map(function (p) {
                return {
                    id: p.issue_id || p.id,
                    title: p.title,
                    category: p.category,
                    nav_group: p.nav_group,
                    source: p.source,
                    severity: "passed",
                    status: "passed",
                };
            });
        }
        return payload;
    }

    var SCORE_RING_C = 326.73;

    function fmtNum(n) {
        if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
        return Number(n).toLocaleString("vi-VN");
    }

    function fmtDuration(ms) {
        if (ms == null || !Number.isFinite(ms) || ms <= 0) return null;
        var sec = Math.round(ms / 1000);
        if (sec < 60) return sec + " giây";
        var min = Math.floor(sec / 60);
        var rem = sec % 60;
        return rem ? min + " phút " + rem + " giây" : min + " phút";
    }

    function setScoreRing(score) {
        var fill = document.getElementById("techDashScoreRingFill");
        if (!fill) return;
        if (score == null || Number.isNaN(score)) {
            fill.style.strokeDashoffset = String(SCORE_RING_C);
            return;
        }
        var pct = Math.max(0, Math.min(100, score));
        fill.style.strokeDashoffset = String(SCORE_RING_C * (1 - pct / 100));
    }

    function impactClass(sev) {
        var s = String(sev || "").toLowerCase();
        if (s === "critical") return "is-high";
        if (s === "warning" || s === "high") return "is-med";
        return "is-low";
    }

    function sevLabelVi(sev) {
        var s = String(sev || "").toLowerCase();
        if (s === "critical") return "Nghiêm trọng";
        if (s === "warning" || s === "high") return "Cảnh báo";
        if (s === "medium") return "Cảnh báo";
        if (s === "opportunity" || s === "low") return "Cơ hội";
        return s || "—";
    }

    var IMPACT_AREA_VI = {
        indexing: "Khả năng lập chỉ mục",
        organic_traffic: "Traffic organic",
        crawl_budget: "Crawl budget",
        user_experience: "Trải nghiệm người dùng",
        rich_results: "Rich results",
        security: "Bảo mật",
        performance: "Tốc độ trang",
        mobile: "Mobile",
        general: "SEO tổng thể",
    };

    var EVIDENCE_KIND_VI = {
        robots_txt: "Robots.txt",
        http_status: "Mã HTTP",
        html: "HTML",
        description: "Mô tả",
        url: "URL",
        domain_scope: "Phạm vi domain",
        remediation_hint: "Gợi ý sửa",
        detected_from: "Phát hiện từ",
        gsc_index_verdict: "Kết quả index GSC",
        gsc_coverage_state: "Trạng thái coverage",
        gsc_badge: "Nhãn GSC",
        gsc_clicks: "Click GSC",
        gsc_impressions: "Impressions GSC",
        gsc_ctr: "CTR GSC",
        gsc_position: "Vị trí trung bình",
    };

    var GSC_BADGE_VI = {
        gsc_confirmed: "Đã xác nhận bởi Search Console",
        crawl_detected: "Phát hiện khi crawl",
        inferred_warning: "Cảnh báo suy luận từ GSC",
    };

    var SOURCE_VI = {
        crawl: "Quét website",
        gsc: "Search Console",
        hybrid: "Quét + Search Console",
    };

    function severityRank(sev) {
        var s = sevLabel(sev);
        return { critical: 4, warning: 3, opportunity: 2, passed: 0 }[s] || 1;
    }

    function gscImpactBoost(issue) {
        if (!issue) return 0;
        var boost = 0;
        if (issue.gsc_badge === "gsc_confirmed") boost += 15;
        else if (issue.gsc_badge === "inferred_warning") boost += 8;
        var imp = Number(issue.gsc_impressions);
        if (imp > 1000) boost += 12;
        else if (imp > 100) boost += 6;
        var clk = Number(issue.gsc_clicks);
        if (clk > 50) boost += 5;
        if (String(issue.source || "").toLowerCase() === "gsc") boost += 5;
        return boost;
    }

    function sortPriorityIssues(issues) {
        return safeArr(issues).slice().sort(function (a, b) {
            var ps = (Number(b.priority_score) || 0) - (Number(a.priority_score) || 0);
            if (ps !== 0) return ps;
            var sr = severityRank(b.severity) - severityRank(a.severity);
            if (sr !== 0) return sr;
            return gscImpactBoost(b) - gscImpactBoost(a);
        });
    }

    function collectPriorityIssues(dash) {
        var pri = safeArr(dash && dash.priority_issues);
        if (pri.length) return sortPriorityIssues(pri);
        var all = safeArr(dash && dash.issues).filter(function (i) {
            if (!i) return false;
            var s = sevLabel(i.severity);
            return s !== "passed" && s !== "opportunity";
        });
        return sortPriorityIssues(all);
    }

    function getTopPriorityIssues(dash, limit) {
        return collectPriorityIssues(dash).slice(0, limit == null ? 5 : limit);
    }

    function formatImpactAreasVi(areas) {
        return safeArr(areas)
            .map(function (a) {
                var key = String(a || "").toLowerCase();
                return IMPACT_AREA_VI[key] || String(a).replace(/_/g, " ");
            })
            .filter(Boolean)
            .join(" · ");
    }

    function formatSeoImpactText(issue) {
        if (!issue) return "—";
        if (issue.why_it_matters) return String(issue.why_it_matters);
        var areas = formatImpactAreasVi(issue.impact_area || issue.impact);
        if (areas) return areas;
        var sev = sevLabel(issue.severity);
        if (sev === "critical") return "Có thể chặn index hoặc làm giảm thứ hạng nghiêm trọng.";
        if (sev === "warning") return "Ảnh hưởng khả năng crawl, index hoặc trải nghiệm tìm kiếm.";
        return "Cải thiện để tối ưu hiển thị trên Google.";
    }

    function truncateText(text, max) {
        var s = String(text || "").trim();
        if (!s) return "—";
        if (s.length <= max) return s;
        return s.slice(0, max - 1) + "…";
    }

    function humanizeEvidenceKind(kind) {
        var k = String(kind || "item").toLowerCase();
        return EVIDENCE_KIND_VI[k] || k.replace(/_/g, " ");
    }

    function formatEvidenceValue(e) {
        if (!e || typeof e !== "object") return "";
        var kind = String(e.kind || "").toLowerCase();
        if (e.text) return esc(e.text);
        if (e.url) {
            return '<a href="' + esc(e.url) + '" target="_blank" rel="noopener">' + esc(e.url) + "</a>";
        }
        if (e.domain) return "Domain: " + esc(e.domain);
        if (kind === "http_status" && e.value != null) return "Mã phản hồi: <strong>" + esc(String(e.value)) + "</strong>";
        if (kind === "gsc_clicks" && e.value != null) return "Click (28 ngày): <strong>" + esc(String(e.value)) + "</strong>";
        if (kind === "gsc_impressions" && e.value != null) {
            return "Impressions (28 ngày): <strong>" + esc(String(e.value)) + "</strong>";
        }
        if (kind === "gsc_ctr" && e.value != null) {
            return "CTR: <strong>" + esc((Number(e.value) * 100).toFixed(2)) + "%</strong>";
        }
        if (kind === "gsc_position" && e.value != null) {
            return "Vị trí TB: <strong>" + esc(Number(e.value).toFixed(1)) + "</strong>";
        }
        if (kind === "gsc_index_verdict" && e.value) return esc(String(e.value));
        if (kind === "gsc_coverage_state" && e.value) return esc(String(e.value));
        if (kind === "gsc_badge" && e.value) {
            return esc(GSC_BADGE_VI[e.value] || String(e.value));
        }
        if (e.value != null && typeof e.value !== "object") return esc(String(e.value));
        if (e.value && typeof e.value === "object") {
            var parts = [];
            Object.keys(e.value).forEach(function (key) {
                var v = e.value[key];
                if (v == null || v === "") return;
                parts.push(esc(key.replace(/_/g, " ")) + ": " + esc(String(v)));
            });
            if (parts.length) return parts.join(", ");
        }
        if (e.urls && Array.isArray(e.urls)) {
            return (
                "<ul class=\"tech-drawer-evidence-urls\">" +
                e.urls
                    .slice(0, 10)
                    .map(function (u) {
                        return "<li><a href=\"" + esc(u) + "\" target=\"_blank\" rel=\"noopener\">" + esc(u) + "</a></li>";
                    })
                    .join("") +
                "</ul>"
            );
        }
        return "";
    }

    function issueHasGscData(issue) {
        if (!issue) return false;
        return !!(
            issue.gsc_badge ||
            issue.gsc_clicks != null ||
            issue.gsc_impressions != null ||
            issue.gsc_index_verdict ||
            issue.gsc_coverage_state ||
            issue.gsc_google_canonical ||
            issue.gsc_user_canonical
        );
    }

    function renderGscDrawerBlock(issue) {
        var sec = document.getElementById("techIssueDrawerGscSection");
        var host = document.getElementById("techIssueDrawerGsc");
        if (!sec || !host) return;
        if (!issueHasGscData(issue)) {
            sec.hidden = true;
            host.textContent = "";
            return;
        }
        sec.hidden = false;
        var rows = [];
        if (issue.gsc_badge) {
            rows.push({ label: "Trạng thái GSC", value: GSC_BADGE_VI[issue.gsc_badge] || issue.gsc_badge });
        }
        if (issue.gsc_clicks != null) rows.push({ label: "Click (28 ngày)", value: fmtNum(issue.gsc_clicks) });
        if (issue.gsc_impressions != null) rows.push({ label: "Impressions (28 ngày)", value: fmtNum(issue.gsc_impressions) });
        if (issue.gsc_ctr != null) rows.push({ label: "CTR", value: (Number(issue.gsc_ctr) * 100).toFixed(2) + "%" });
        if (issue.gsc_position != null && Number(issue.gsc_position) > 0) {
            rows.push({ label: "Vị trí trung bình", value: Number(issue.gsc_position).toFixed(1) });
        }
        if (issue.gsc_index_verdict) rows.push({ label: "Kết quả index", value: issue.gsc_index_verdict });
        if (issue.gsc_coverage_state) rows.push({ label: "Coverage", value: issue.gsc_coverage_state });
        if (issue.gsc_google_canonical) rows.push({ label: "Canonical Google chọn", value: issue.gsc_google_canonical });
        if (issue.gsc_user_canonical) rows.push({ label: "Canonical trên trang", value: issue.gsc_user_canonical });
        host.innerHTML = rows
            .map(function (row) {
                return (
                    '<div class="tech-drawer-gsc-item"><span>' +
                    esc(row.label) +
                    "</span><strong>" +
                    esc(String(row.value)) +
                    "</strong></div>"
                );
            })
            .join("");
    }

    function renderOverviewV2Summary(payload) {
        if (!payload || typeof payload !== "object") return false;
        var sum = resolveSummary(payload);
        if (!sum) {
            var fb = buildFallbackDashboard(payload);
            if (fb && fb.summary) {
                sum = {
                    health_score: fb.technical_health_score,
                    critical: Number(fb.summary.critical) || 0,
                    warning: Number(fb.summary.warning) || 0,
                    opportunity: Number(fb.summary.opportunity) || 0,
                    passed: safeArr(fb.passed_checks).length,
                    pages_scanned: fb.pages_scanned,
                    scan_mode: fb.scan_mode,
                };
            }
        }
        if (!sum) return false;
        var score = sum.health_score != null ? Math.round(Number(sum.health_score)) : null;
        if (score != null && !Number.isNaN(score)) score = Math.max(0, Math.min(100, score));

        var valEl = document.getElementById("saasHealthScoreValue");
        if (valEl) valEl.textContent = score != null ? String(score) : "—";
        setScoreRing(score);

        var card = document.getElementById("seoToolHealthScoreCard");
        if (card) {
            card.classList.remove("score-band-good", "score-band-mid", "score-band-low");
            if (score == null) card.classList.add("score-band-mid");
            else if (score >= 80) card.classList.add("score-band-good");
            else if (score >= 50) card.classList.add("score-band-mid");
            else card.classList.add("score-band-low");
        }

        var hint = document.getElementById("saasHealthScoreHint");
        if (hint) {
            if (score == null) hint.textContent = "Chưa có điểm từ lần quét này.";
            else if (score >= 80) hint.textContent = "Tốt";
            else if (score >= 50) hint.textContent = "Trung bình";
            else hint.textContent = "Cần cải thiện";
        }

        function set(id, n, dash) {
            var el = document.getElementById(id);
            if (!el) return;
            el.textContent = n == null || n === "" ? "—" : String(Number(n) || 0);
        }
        set("saasCountCritical", sum.critical);
        set("saasCountWarning", sum.warning);
        set("saasCountOpportunity", sum.opportunity);
        set("saasCountPassed", sum.passed);

        var pages = sum.pages_scanned != null ? sum.pages_scanned : payload && payload.pages_scanned;
        var pagesEl = document.getElementById("seoToolUrlsScannedStat");
        if (pagesEl) pagesEl.textContent = pages != null ? String(pages) : "—";
        var pagesCard = document.getElementById("saasPagesCrawled");
        if (pagesCard) pagesCard.textContent = pages != null ? fmtNum(pages) : "—";

        var modeEl = document.getElementById("saasScanMode");
        if (modeEl && sum.scan_mode) {
            var labels = {
                crawl_only: "Chỉ quét website",
                hybrid_gsc: "Kết hợp Search Console",
                partial_gsc: "Search Console một phần",
            };
            modeEl.textContent = labels[sum.scan_mode] || sum.scan_mode;
        }

        var scanMs = global.__seoLastScanElapsedMs;
        var scanTimeEl = document.getElementById("techDashKpiScanTime");
        var scanSubEl = document.getElementById("techDashKpiScanTimeSub");
        var dur = fmtDuration(scanMs);
        if (scanTimeEl) scanTimeEl.textContent = dur || "—";
        if (scanSubEl) {
            var at = payload && payload.at ? String(payload.at).slice(0, 16).replace("T", " ") : "";
            scanSubEl.textContent = at ? "Hoàn thành " + at : "";
        }

        var pagesFoot = document.getElementById("techDashKpiPagesFoot");
        if (pagesFoot) {
            pagesFoot.textContent = pages != null ? "URL đã crawl" : "";
        }

        return true;
    }

    function renderPassedCollapsible(payload) {
        var sec = document.getElementById("seoToolOverviewPassedCollapsible");
        var body = document.getElementById("seoToolOverviewPassedCollapsibleBody");
        var countEl = document.getElementById("seoToolOverviewPassedCollapsibleCount");
        if (sec) sec.hidden = true;
        if (!body) return;
        var dash = getDash(payload);
        var passed = dash ? safeArr(dash.passed_checks) : safeArr(payload && payload.passed_checks);
        if (countEl) countEl.textContent = String(passed.length || 0);
        body.innerHTML = "";
        passed.slice(0, 50).forEach(function (p) {
            var li = document.createElement("li");
            li.className = "tech-passed-collapsible-item";
            li.textContent = (p.title || p.issue_id || "Check") + (p.nav_group ? " · " + p.nav_group : "");
            body.appendChild(li);
        });
    }

    function wirePassedCollapsibleToggle() {
        var btn = document.getElementById("seoToolOverviewPassedCollapsibleToggle");
        var body = document.getElementById("seoToolOverviewPassedCollapsibleBody");
        if (!btn || btn.dataset.wired === "1") return;
        btn.dataset.wired = "1";
        btn.addEventListener("click", function () {
            var open = btn.getAttribute("aria-expanded") === "true";
            btn.setAttribute("aria-expanded", open ? "false" : "true");
            if (body) body.hidden = open;
        });
    }

    function esc(s) {
        var d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    function renderEvidenceList(evidence) {
        if (!evidence || !evidence.length) {
            return "<p class=\"tech-drawer-muted\">Chưa có bằng chứng kỹ thuật chi tiết cho lỗi này.</p>";
        }
        var items = evidence
            .map(function (e) {
                if (!e || typeof e !== "object") return "";
                var body = formatEvidenceValue(e);
                if (!body) return "";
                var kind = humanizeEvidenceKind(e.kind || "item");
                return (
                    "<li class=\"tech-drawer-evidence-item\"><span class=\"ev-kind\">" +
                    esc(kind) +
                    "</span><div class=\"ev-body\">" +
                    body +
                    "</div></li>"
                );
            })
            .filter(Boolean);
        if (!items.length) {
            return "<p class=\"tech-drawer-muted\">Chưa có bằng chứng kỹ thuật chi tiết cho lỗi này.</p>";
        }
        return "<ul class=\"tech-drawer-evidence-list\">" + items.join("") + "</ul>";
    }

    function describeIssueWhat(issue) {
        if (!issue) return "—";
        var desc = String(issue.description || "").trim();
        if (desc && desc !== String(issue.title || "").trim()) return desc;
        var title = String(issue.title || "").trim();
        if (title) return title;
        return "Hệ thống phát hiện một vấn đề technical cần xử lý trên website.";
    }

    function renderIssueDrawerBody(issue) {
        var sev = sevLabel(issue.severity);
        document.getElementById("techIssueDrawerTitle").textContent = issue.title || "Chi tiết lỗi";
        var sevEl = document.getElementById("techIssueDrawerSeverity");
        if (sevEl) {
            sevEl.textContent = sevLabelVi(sev);
            sevEl.className =
                "tech-drawer-sev saas-badge " +
                (typeof global.saasSeverityBadgeClass === "function"
                    ? global.saasSeverityBadgeClass(issue.severity)
                    : "saas-sev-medium");
        }

        var conf = issue.confidence != null ? Math.round(Number(issue.confidence) * 100) + "%" : "—";
        document.getElementById("techIssueDrawerConfidence").textContent = conf;
        var srcKey = String(issue.source || "crawl").toLowerCase();
        document.getElementById("techIssueDrawerSource").textContent = SOURCE_VI[srcKey] || issue.source || "—";
        document.getElementById("techIssueDrawerCategory").textContent =
            groupLabel(frontNavFromV2(issue.nav_group)) || issue.category || "—";

        var whatEl = document.getElementById("techIssueDrawerWhat");
        if (whatEl) whatEl.textContent = describeIssueWhat(issue);

        var whyEl = document.getElementById("techIssueDrawerWhy");
        if (whyEl) whyEl.textContent = formatSeoImpactText(issue);

        var fixText = String(issue.how_to_fix || "").trim();
        document.getElementById("techIssueDrawerFix").textContent = fixText || "Liên hệ team kỹ thuật hoặc mở tab nhóm lỗi tương ứng để xem hướng dẫn chi tiết hơn.";

        renderGscDrawerBlock(issue);

        var urls = safeArr(issue.affected_urls).length ? issue.affected_urls : issue.sample_urls;
        var urlsEl = document.getElementById("techIssueDrawerUrls");
        if (urlsEl) {
            var total = issue.affected_urls_total || urls.length || affectedCount(issue);
            if (!urls.length) {
                urlsEl.innerHTML = "<p class=\"tech-drawer-muted\">Không có URL cụ thể — lỗi có thể áp dụng cho toàn site.</p>";
            } else {
                urlsEl.innerHTML =
                    "<p class=\"tech-drawer-url-count\">" +
                    esc(String(total)) +
                    " URL bị ảnh hưởng</p><ul class=\"tech-drawer-url-list\">" +
                    urls
                        .slice(0, 30)
                        .map(function (u) {
                            return "<li><a href=\"" + esc(u) + "\" target=\"_blank\" rel=\"noopener\">" + esc(u) + "</a></li>";
                        })
                        .join("") +
                    (total > 30 ? "<li class=\"tech-drawer-url-more\">+ " + (total - 30) + " URL khác</li>" : "") +
                    "</ul>";
            }
        }

        document.getElementById("techIssueDrawerEvidence").innerHTML = renderEvidenceList(issue.evidence);
    }

    function openIssueDrawer(issue) {
        if (!issue) return;
        var drawer = document.getElementById("techIssueDrawer");
        var backdrop = document.getElementById("techIssueDrawerBackdrop");
        if (!drawer) return;

        renderIssueDrawerBody(issue);

        drawer.classList.add("is-open");
        drawer.setAttribute("aria-hidden", "false");
        if (backdrop) {
            backdrop.hidden = false;
            backdrop.classList.add("is-visible");
        }
        document.body.classList.add("tech-drawer-open");

        if (!issue._urls_truncated) return;
        var issueId = issue.issue_id || issue.id || issue.type || issue._issue_type;
        var auditId =
            (typeof global.__seoLastTechnicalAuditId !== "undefined" && global.__seoLastTechnicalAuditId) ||
            issue._audit_id;
        var token = (function () {
                if (typeof window.DigiSeoGetAuthToken === "function") {
                    return window.DigiSeoGetAuthToken() || "";
                }
                try {
                    var lt = (localStorage.getItem("seo_token") || "").trim();
                    if (lt) return lt;
                    return sessionStorage.getItem("seo_token") || "";
                } catch (_e) {
                    return "";
                }
            })();
        if (!auditId || !issueId || !token) return;
        fetch(
            "/api/audit/" +
                encodeURIComponent(auditId) +
                "/issue-detail?issue_id=" +
                encodeURIComponent(String(issueId)),
            { headers: { Authorization: "Bearer " + token } }
        )
            .then(function (r) {
                return r.json().then(function (d) {
                    return { ok: r.ok, d: d };
                });
            })
            .then(function (res) {
                if (!res.ok || !res.d || !res.d.issue) return;
                renderIssueDrawerBody(v2IssueToNormalized(res.d.issue) || res.d.issue);
            })
            .catch(function () {});
    }

    function closeIssueDrawer() {
        var drawer = document.getElementById("techIssueDrawer");
        var backdrop = document.getElementById("techIssueDrawerBackdrop");
        if (drawer) {
            drawer.classList.remove("is-open");
            drawer.setAttribute("aria-hidden", "true");
        }
        if (backdrop) {
            backdrop.hidden = true;
            backdrop.classList.remove("is-visible");
        }
        document.body.classList.remove("tech-drawer-open");
    }

    function wireIssueDrawer() {
        var closeBtn = document.getElementById("techIssueDrawerClose");
        var backdrop = document.getElementById("techIssueDrawerBackdrop");
        if (closeBtn && closeBtn.dataset.wired !== "1") {
            closeBtn.dataset.wired = "1";
            closeBtn.addEventListener("click", closeIssueDrawer);
        }
        if (backdrop && backdrop.dataset.wired !== "1") {
            backdrop.dataset.wired = "1";
            backdrop.addEventListener("click", closeIssueDrawer);
        }
        document.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape") closeIssueDrawer();
        });
    }

    function wireExplorerV2Filters(onChange) {
        var src = document.getElementById("seoToolFilterSource");
        var conf = document.getElementById("seoToolFilterConfidence");
        if (!src || src.dataset.wired === "1") return;
        src.dataset.wired = "1";
        if (conf) conf.dataset.wired = "1";
        var handler = function () {
            if (typeof onChange === "function") onChange();
        };
        src.addEventListener("change", handler);
        if (conf) conf.addEventListener("change", handler);
    }

    function getExplorerV2Filters() {
        return {
            source: (document.getElementById("seoToolFilterSource") || {}).value || "all",
            confidence: (document.getElementById("seoToolFilterConfidence") || {}).value || "all",
        };
    }

    function issueMatchesV2Filters(issue, filters) {
        if (!filters) return true;
        if (filters.source && filters.source !== "all") {
            if (String(issue.source || "").toLowerCase() !== filters.source) return false;
        }
        if (filters.confidence && filters.confidence !== "all") {
            var c = Number(issue.confidence);
            if (Number.isNaN(c)) return filters.confidence === "low";
            if (filters.confidence === "high" && c < 0.85) return false;
            if (filters.confidence === "medium" && (c < 0.65 || c >= 0.85)) return false;
            if (filters.confidence === "low" && c >= 0.65) return false;
        }
        return true;
    }

    function getMaxPages() {
        var el = document.getElementById("techMaxPages");
        if (!el) return 25;
        var n = parseInt(el.value, 10);
        if (Number.isNaN(n) || n < 1) return 25;
        return Math.min(500, n);
    }

    var ISSUE_GROUP_TABS = {
        index_crawl: true,
        onpage: true,
        perf_security: true,
        indexability: true,
        crawlability: true,
        internal_links: true,
        performance: true,
        structured_data: true,
        security_http: true,
        ux_mobile: true,
    };

    var SCAN_STEPS = [
        "Crawl URL",
        "Parse HTML",
        "Check robots/sitemap",
        "Analyze issues",
        "Build dashboard",
    ];

    var SCAN_MODE_LABELS = {
        crawl_only: "Chỉ quét website",
        gsc_hybrid: "Kết hợp Search Console",
        hybrid_gsc: "Kết hợp Search Console",
        partial_gsc: "Search Console một phần",
    };

    var _scanProgressTimer = null;
    var _scanStepIndex = 0;
    var _historyLoaded = false;

    function sidebarToV2NavGroup(groupKey) {
        var g = String(groupKey || "");
        return FRONT_NAV_TO_V2[g] || g;
    }

    function sevBadgeClass(sev) {
        if (typeof global.saasSeverityBadgeClass === "function") {
            return global.saasSeverityBadgeClass(sev);
        }
        var s = String(sev || "").toLowerCase();
        if (s === "critical") return "saas-sev-critical";
        if (s === "warning" || s === "high") return "saas-sev-warning";
        if (s === "opportunity" || s === "low") return "saas-sev-opportunity";
        if (s === "passed") return "saas-sev-passed";
        return "saas-sev-medium";
    }

    function sevLabel(sev) {
        var s = String(sev || "").toLowerCase();
        if (s === "high") return "warning";
        if (s === "low") return "opportunity";
        return s || "warning";
    }

    function groupLabel(groupKey) {
        var TS = global.TechSidebarV2;
        if (TS && TS.TAB_LABELS && TS.TAB_LABELS[groupKey]) return TS.TAB_LABELS[groupKey];
        return String(groupKey || "").replace(/_/g, " ");
    }

    function issueNavGroupForFallback(issue) {
        if (issue && issue.nav_group) return frontNavFromV2(issue.nav_group);
        var TS = global.TechSidebarV2;
        if (TS && typeof TS.issueNavGroup === "function") return TS.issueNavGroup(issue);
        return "crawlability";
    }

    function rawIssuesFromPayload(payload) {
        var dash = getDash(payload);
        if (dash && safeArr(dash.issues).length) return safeArr(dash.issues);
        var resolved = resolveIssues(payload);
        if (resolved && resolved.length) {
            return resolved.map(function (n) {
                return {
                    issue_id: n.issue_id || n.id,
                    issue_type: n._issue_type || n.type,
                    title: n.title,
                    description: n.description,
                    severity: n.severity,
                    category: n.category,
                    nav_group: sidebarToV2NavGroup(issueNavGroupForFallback(n)),
                    source: n.source,
                    confidence: n.confidence,
                    affected_urls: n.affected_urls,
                    sample_urls: n.sample_urls,
                    evidence: n.evidence,
                    why_it_matters: n.why_it_matters,
                    how_to_fix: n.how_to_fix,
                    priority_score: n.priority_score,
                };
            });
        }
        var norm = safeArr(payload && payload.normalized_issues);
        if (norm.length) {
            return norm.map(function (n) {
                return {
                    issue_id: n.issue_id || n.id,
                    title: n.title,
                    severity: n.severity,
                    nav_group: sidebarToV2NavGroup(issueNavGroupForFallback(n)),
                    source: n.source,
                    confidence: n.confidence,
                    affected_urls: n.affected_urls || n.sample_urls,
                    sample_urls: n.sample_urls,
                    evidence: n.evidence,
                    why_it_matters: n.why_it_matters,
                    how_to_fix: n.how_to_fix,
                    priority_score: n.priority_score,
                };
            });
        }
        return safeArr(payload && payload.issues).filter(function (i) {
            return i && !i.suppressed;
        });
    }

    function buildFallbackDashboard(payload) {
        if (!payload || typeof payload !== "object") return null;
        var issues = rawIssuesFromPayload(payload);
        var pri = safeArr(payload.priority_fixes).length
            ? safeArr(payload.priority_fixes)
            : issues
                  .filter(function (i) {
                      var s = String(i.severity || "").toLowerCase();
                      return s !== "passed" && s !== "opportunity" && s !== "low";
                  })
                  .sort(function (a, b) {
                      return (Number(b.priority_score) || 0) - (Number(a.priority_score) || 0);
                  })
                  .slice(0, 10);
        var summary = { critical: 0, warning: 0, opportunity: 0, total: 0 };
        var navMap = {};
        issues.forEach(function (issue) {
            var sev = sevLabel(issue.severity);
            if (sev === "passed") return;
            summary.total += 1;
            if (sev === "critical") summary.critical += 1;
            else if (sev === "warning") summary.warning += 1;
            else if (sev === "opportunity") summary.opportunity += 1;
            var ng = frontNavFromV2(issue.nav_group || sidebarToV2NavGroup(issueNavGroupForFallback(issue)));
            if (!navMap[ng]) navMap[ng] = { open: 0, worst: "passed" };
            navMap[ng].open += 1;
            var rank = { critical: 4, warning: 3, opportunity: 2, passed: 0 };
            if ((rank[sev] || 0) > (rank[navMap[ng].worst] || 0)) navMap[ng].worst = sev;
        });
        var navSummaries = Object.keys(navMap).map(function (g) {
            return {
                group: sidebarToV2NavGroup(g),
                issue_count: navMap[g].open,
                open_issues: navMap[g].open,
                worst_severity: navMap[g].worst,
            };
        });
        var ts = safeObj(payload.technical_summary) || {};
        var ss = resolveSaasSummaryCompat(payload);
        return {
            schema_version: 2,
            domain: payload.domain,
            pages_scanned: payload.pages_scanned,
            scan_mode: (ss && ss.scan_mode) || "crawl_only",
            technical_health_score: ss && ss.health_score != null ? ss.health_score : ts.health_score,
            summary: summary,
            issues: issues,
            priority_issues: pri,
            nav_group_summaries: navSummaries,
            passed_checks: safeArr(payload.passed_checks),
        };
    }

    function resolveSaasSummaryCompat(payload) {
        return resolveSummary(payload);
    }

    function getDashboardForRender(payload) {
        if (hasV2(payload)) return getDash(payload);
        return buildFallbackDashboard(payload);
    }

    function canUseGroupRenderer(payload) {
        if (!payload) return false;
        if (hasV2(payload)) return true;
        var dash = buildFallbackDashboard(payload);
        return !!(dash && (safeArr(dash.issues).length || safeArr(dash.priority_issues).length));
    }

    function issueMatchesSidebarTab(issue, groupKey) {
        if (!issue) return false;
        var key = String(groupKey || "");
        var TS = global.TechSidebarV2;
        if (key === "priority") return false;
        var fine =
            TS && typeof TS.issueNavGroupFine === "function"
                ? TS.issueNavGroupFine(issue)
                : String(issue.sidebar_key || issue.nav_group || "");
        if (fine === "gsc_insights") fine = "gsc";
        var children = TS && TS.TAB_CHILDREN && TS.TAB_CHILDREN[key];
        if (children && children.length) {
            return children.indexOf(fine) !== -1;
        }
        if (TS && typeof TS.normalizeTechTabKey === "function") {
            var simple = TS.normalizeTechTabKey(key);
            children = TS.TAB_CHILDREN && TS.TAB_CHILDREN[simple];
            if (children && children.length && simple !== key) {
                /* keep fine-grained match when caller asks crawlability/onpage/etc. */
            }
        }
        if (fine === key) return true;
        if (TS && typeof TS.issueNavGroup === "function") {
            return TS.issueNavGroup(issue) === key;
        }
        var v2g = sidebarToV2NavGroup(key);
        var ng = String(issue.sidebar_key || issue.nav_group || "");
        if (ng === v2g || ng === key || frontNavFromV2(ng) === key) return true;
        if (issue.category && TS && typeof TS.legacyCatToGroup === "function") {
            return TS.legacyCatToGroup(issue.category) === key;
        }
        return false;
    }

    function filterIssuesByGroup(dashboardV2, groupKey) {
        var dash = dashboardV2 || {};
        return safeArr(dash.issues).filter(function (issue) {
            return issueMatchesSidebarTab(issue, groupKey);
        });
    }

    function countBySeverity(issues) {
        var out = { critical: 0, warning: 0, opportunity: 0, passed: 0 };
        safeArr(issues).forEach(function (i) {
            var s = sevLabel(i.severity);
            if (out[s] != null) out[s] += 1;
        });
        return out;
    }

    function affectedCount(issue) {
        var urls = safeArr(issue.affected_urls).length ? issue.affected_urls : safeArr(issue.sample_urls);
        return urls.length || Number(issue.count) || 1;
    }

    function ensureEl(id, tag, parentId, className) {
        var el = document.getElementById(id);
        if (el) return el;
        var parent = parentId ? document.getElementById(parentId) : document.body;
        if (!parent) return null;
        el = document.createElement(tag || "div");
        el.id = id;
        if (className) el.className = className;
        parent.appendChild(el);
        return el;
    }

    function setPanelVisible(ids, visibleId) {
        safeArr(ids).forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.hidden = id !== visibleId;
        });
    }

    function hideTechPanels() {
        if (global.document && global.document.body) {
            global.document.body.classList.remove("tech-gsc-tab-active");
        }
        [
            "seoToolResultsOverview",
            "techContentPriority",
            "techContentHistory",
            "techContentPassed",
            "techContentGsc",
            "issuesCard",
            "techCategoryPanel",
            "crawlExtrasCard",
            "techIssueGroupChrome",
        ].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.hidden = true;
        });
        var dr = document.querySelector(".tech-dash-date-range");
        if (dr) dr.hidden = true;
        var contentHdr = document.getElementById("techContentHeader");
        if (contentHdr) contentHdr.hidden = true;
    }

    function renderOverviewScanHeader(payload, dash) {
        var hdr = document.getElementById("seoToolResultsHeader");
        if (!hdr || !payload) return;
        hdr.hidden = false;
        var url =
            (payload.source_url || "").trim() ||
            (payload.domain ? "https://" + String(payload.domain).replace(/^https?:\/\//i, "") : "—");
        var urlEl = document.getElementById("seoResultsHeaderUrl");
        if (urlEl) urlEl.textContent = url;
        var score =
            dash && dash.technical_health_score != null
                ? Math.round(Number(dash.technical_health_score))
                : null;
        var mode = (dash && dash.scan_mode) || "crawl_only";
        var pages = dash && dash.pages_scanned != null ? dash.pages_scanned : payload.pages_scanned;
        var domain = (payload.domain || "").trim() || url.replace(/^https?:\/\//i, "").split("/")[0];
        var metaEl = document.getElementById("seoResultsHeaderMeta");
        if (metaEl) {
            var parts = [];
            if (domain) parts.push(domain);
            if (score != null && !Number.isNaN(score)) parts.push(score + "/100");
            if (pages != null) parts.push(fmtNum(pages) + " trang");
            metaEl.textContent = parts.length ? parts.join(" · ") : "—";
        }
        var auditId = payload.audit_id || payload.id;
        var pdfBtn = document.getElementById("btnTechDownloadPdf");
        if (pdfBtn) pdfBtn.disabled = !auditId;
        var expBtn = document.getElementById("btnTechnicalExportHeader");
        if (expBtn) expBtn.disabled = !auditId;
        var gscBtn = document.getElementById("btnTechOverviewConnectGsc");
        var gscOn = !!(payload.gsc_summary && payload.gsc_summary.enabled);
        if (gscBtn) {
            gscBtn.hidden = gscOn || mode === "hybrid_gsc" || mode === "gsc_hybrid";
        }
        var dr = document.getElementById("techDashDateRange");
        var gi = payload.gsc_intelligence_summary || safeObj(dash && dash.gsc_intelligence) || {};
        if (dr && gi.date_range) dr.value = gi.date_range === "90d" ? "90d" : "28d";
    }

    function formatAffectedUrlCell(issue) {
        var urls = safeArr(issue.affected_urls).length ? issue.affected_urls : safeArr(issue.sample_urls);
        if (!urls.length) return "Toàn site";
        var first = String(urls[0] || "");
        if (first.length > 52) first = first.slice(0, 49) + "…";
        if (urls.length > 1) return first + " +" + (urls.length - 1);
        return first || "—";
    }

    function buildSimpleIssueTable(issues, opts) {
        opts = opts || {};
        var wrap = document.createElement("div");
        wrap.className = "tech-simple-table-wrap";
        var table = document.createElement("table");
        table.className = "tech-simple-issue-table";
        table.innerHTML =
            "<thead><tr><th>Mức độ</th><th>Lỗi</th><th>URL ảnh hưởng</th><th>Tác động</th><th>Xem chi tiết</th></tr></thead>";
        var tbody = document.createElement("tbody");
        if (!issues.length) {
            var emptyRow = document.createElement("tr");
            emptyRow.innerHTML = '<td colspan="5" class="tech-simple-empty">Chưa có lỗi trong nhóm này.</td>';
            tbody.appendChild(emptyRow);
        } else {
            issues.forEach(function (raw) {
                var issue = v2IssueToNormalized(raw) || raw;
                var sev = sevLabel(issue.severity);
                var tr = document.createElement("tr");
                tr.className = "tech-simple-issue-row";
                tr.innerHTML =
                    '<td><span class="tech-sev-pill tech-sev-' +
                    esc(sev) +
                    '">' +
                    esc(sevLabelVi(sev)) +
                    "</span></td>" +
                    '<td class="tech-simple-issue-title">' +
                    esc(issue.title || "—") +
                    "</td>" +
                    '<td class="tech-simple-issue-url">' +
                    esc(formatAffectedUrlCell(issue)) +
                    "</td>" +
                    '<td class="tech-simple-issue-impact">' +
                    esc(truncateText(formatSeoImpactText(issue), 80)) +
                    "</td>" +
                    '<td><button type="button" class="tech-simple-detail-btn">Xem chi tiết</button></td>';
                var btn = tr.querySelector("button");
                if (btn) {
                    btn.addEventListener("click", function (ev) {
                        ev.stopPropagation();
                        openIssueDrawer(issue);
                    });
                }
                tr.addEventListener("click", function () {
                    openIssueDrawer(issue);
                });
                tbody.appendChild(tr);
            });
        }
        table.appendChild(tbody);
        wrap.appendChild(table);
        return wrap;
    }

    function renderOverviewPriorityTop(dash, hooks) {
        var sec = document.getElementById("seoToolPriorityFixesSection");
        var tbody = document.getElementById("techDashPriorityTbody");
        var empty = document.getElementById("techDashPriorityEmpty");
        var countBadge = document.getElementById("techDashPriorityCount");
        var list = document.getElementById("seoToolPriorityFixesList");
        if (!sec) return;
        sec.hidden = false;
        var allPri = collectPriorityIssues(dash);
        var fixes = getTopPriorityIssues(dash, 5);
        if (countBadge) countBadge.textContent = fixes.length ? String(fixes.length) : "0";
        if (tbody) {
            tbody.textContent = "";
            if (!fixes.length) {
                if (empty) empty.hidden = false;
            } else {
                if (empty) empty.hidden = true;
                fixes.forEach(function (raw) {
                    var norm = v2IssueToNormalized(raw) || raw;
                    var sev = sevLabel(raw.severity);
                    var tr = document.createElement("tr");
                    tr.className = "tech-simple-issue-row";
                    tr.innerHTML =
                        '<td><span class="tech-sev-pill tech-sev-' +
                        esc(sev) +
                        '">' +
                        esc(sevLabelVi(sev)) +
                        "</span></td>" +
                        '<td class="tech-simple-issue-title">' +
                        esc(raw.title || "—") +
                        "</td>" +
                        '<td class="tech-simple-issue-url">' +
                        esc(formatAffectedUrlCell(norm)) +
                        "</td>" +
                        '<td class="tech-simple-issue-impact">' +
                        esc(truncateText(formatSeoImpactText(raw), 80)) +
                        "</td>" +
                        '<td><button type="button" class="tech-simple-detail-btn">Xem chi tiết</button></td>';
                    var btn = tr.querySelector("button");
                    if (btn) {
                        btn.addEventListener("click", function (ev) {
                            ev.stopPropagation();
                            openIssueDrawer(norm);
                        });
                    }
                    tr.addEventListener("click", function () {
                        openIssueDrawer(norm);
                    });
                    tbody.appendChild(tr);
                });
            }
        }
        if (list) {
            list.textContent = "";
            list.hidden = true;
        }
        var viewAll = document.getElementById("techDashPriorityViewAll");
        if (viewAll) {
            viewAll.hidden = allPri.length <= 5;
            if (!viewAll.dataset.wired) {
                viewAll.dataset.wired = "1";
                viewAll.addEventListener("click", function () {
                    if (hooks && typeof hooks.navigateTab === "function") hooks.navigateTab("priority");
                });
            }
        }
    }

    function formatGscDateRangeLabel(state) {
        if (!state) return "—";
        if (state.startDate && state.endDate) return state.startDate + " → " + state.endDate;
        if (state.dateRange === "90d") return "90 ngày qua";
        if (state.dateRange === "28d") return "28 ngày qua";
        return state.dateRange || "—";
    }

    function resolveGscViewState(payload) {
        payload = payload || {};
        var gi = payload.gsc_intelligence_summary || safeObj(getDash(payload) && getDash(payload).gsc_intelligence) || {};
        var gs = safeObj(payload.gsc_summary) || {};
        var dash = getDash(payload);
        var scanMode =
            (dash && dash.scan_mode) ||
            (gs.enabled ? (gs.partial_data || gs.quota_exceeded ? "partial_gsc" : "hybrid_gsc") : "crawl_only");
        var connected = !!(gi.connected || gs.connected);
        var enabled = !!(gi.enabled || gs.enabled);
        var property = String(gi.property || gs.property || "").trim();
        var errors = safeArr(gi.errors).length ? safeArr(gi.errors) : safeArr(gs.errors);
        var quotaExceeded = !!(gi.quota_exceeded || gs.quota_exceeded);
        var partialData = !!(gi.partial_data || gs.partial_data || payload.partial_data);
        var impressions = gi.impressions != null ? Number(gi.impressions) : gs.impressions != null ? Number(gs.impressions) : null;
        var clicks = gi.clicks != null ? Number(gi.clicks) : gs.clicks != null ? Number(gs.clicks) : null;
        var pagesWithData = Number(gs.pages_with_data || gi.pages_with_data || 0);
        var hasMetrics =
            enabled &&
            ((impressions != null && impressions > 0) ||
                (clicks != null && clicks > 0) ||
                pagesWithData > 0);
        var status = "not_connected";
        var statusLabel = "Chưa kết nối";
        var statusClass = "is-off";
        var statusDetail =
            gi.message ||
            gs.message ||
            "Kết nối Google Search Console để xác thực index, canonical và traffic thật.";

        if (scanMode === "crawl_only" && !enabled) {
            status = "crawl_only";
            statusLabel = "Chỉ quét website";
            statusClass = "is-crawl";
            statusDetail = "Lần quét này không dùng GSC — bật GSC và chọn property để quét hybrid.";
        } else if (quotaExceeded) {
            status = "quota";
            statusLabel = "Quota GSC đã hết";
            statusClass = "is-warn";
            statusDetail = statusDetail || "Một phần URL Inspection / Search Analytics không lấy được do quota.";
        } else if (errors.length && /permission|quyền|403|forbidden/i.test(errors.join(" "))) {
            status = "permission";
            statusLabel = "Thiếu quyền GSC";
            statusClass = "is-warn";
            statusDetail = errors[0];
        } else if (errors.length) {
            status = "error";
            statusLabel = "Lỗi GSC";
            statusClass = "is-warn";
            statusDetail = errors[0];
        } else if (connected && !property) {
            status = "no_property";
            statusLabel = "Đã kết nối — chưa chọn property";
            statusClass = "is-mid";
            statusDetail = "Chọn property Search Console trước khi quét hybrid.";
        } else if (partialData) {
            status = "partial";
            statusLabel = "Dữ liệu GSC một phần";
            statusClass = "is-mid";
            statusDetail = statusDetail || "Một số URL/metric chưa lấy đủ — kết quả crawl vẫn hợp lệ.";
        } else if (enabled && property) {
            status = "active";
            statusLabel = "Đã kết nối";
            statusClass = "is-on";
            if (!hasMetrics) {
                statusDetail = "Property đã chọn nhưng chưa có impression/click trong khoảng thời gian này.";
            } else {
                statusDetail = statusDetail || "Đã tích hợp Search Analytics và URL Inspection.";
            }
        } else if (connected) {
            status = "connected";
            statusLabel = "Đã kết nối Google";
            statusClass = "is-mid";
        }

        return {
            status: status,
            statusLabel: statusLabel,
            statusClass: statusClass,
            statusDetail: statusDetail,
            connected: connected,
            enabled: enabled,
            property: property,
            dateRange: gi.date_range || gs.date_range || "",
            startDate: gi.start_date || gs.start_date || "",
            endDate: gi.end_date || gs.end_date || "",
            scanMode: scanMode,
            hasMetrics: hasMetrics,
            metrics: hasMetrics
                ? {
                      impressions: impressions,
                      clicks: clicks,
                      ctr: gi.avg_ctr != null ? gi.avg_ctr : gs.avg_ctr,
                      position: gi.avg_position != null ? gi.avg_position : gs.avg_position,
                  }
                : null,
            errors: errors,
            quotaExceeded: quotaExceeded,
            partialData: partialData,
            opportunities: safeArr(payload.gsc_opportunities),
            enrichedPages: safeArr(payload.gsc_enriched_pages),
            queryRows: safeArr(payload.gsc_query_rows || payload.gsc_queries),
            urlsInspected: gi.urls_inspected != null ? gi.urls_inspected : gs.urls_inspected,
        };
    }

    function truncateUrl(url, max) {
        var s = String(url || "");
        if (s.length <= max) return s;
        return s.slice(0, max - 1) + "…";
    }

    function buildGscLowCtrRows(state) {
        return state.opportunities
            .filter(function (o) {
                return o && o.type === "ctr_opportunity";
            })
            .map(function (o) {
                return {
                    url: o.url || "—",
                    impressions: o.impressions,
                    clicks: o.clicks,
                    ctr: o.ctr,
                    position: o.position,
                    note: o.message || "",
                };
            })
            .sort(function (a, b) {
                return (Number(b.impressions) || 0) - (Number(a.impressions) || 0);
            });
    }

    var GSC_TECH_ISSUE_RE =
        /missing_title|missing_meta|canonical|noindex|meta_robots|title_too|description|indexability/i;

    function buildGscTechIssueRows(payload, dash) {
        var rows = [];
        var seen = new Set();
        var state = resolveGscViewState(payload);

        state.opportunities.forEach(function (o) {
            if (!o || o.type !== "high_impression_technical_issue") return;
            var url = String(o.url || "").trim();
            var issueLabel = o.issue_type || o.message || "—";
            var key = url + "|" + issueLabel;
            if (!url || seen.has(key)) return;
            seen.add(key);
            rows.push({
                url: url,
                issue: issueLabel,
                impressions: o.impressions,
                clicks: o.clicks,
            });
        });

        var issues = dash ? safeArr(dash.issues) : safeArr(payload.normalized_issues || payload.issues);
        issues.forEach(function (issue) {
            if (!issue) return;
            var imp = Number(issue.gsc_impressions);
            if (!imp || imp < 50) return;
            var itype = String(issue.issue_type || issue.type || issue._issue_type || "");
            var ng = String(issue.nav_group || "");
            if (!GSC_TECH_ISSUE_RE.test(itype) && ng !== "indexability" && ng !== "onpage" && ng !== "gsc_insights") {
                return;
            }
            var urls = safeArr(issue.affected_urls).length ? issue.affected_urls : safeArr(issue.sample_urls);
            var url = urls[0] || "—";
            var key = url + "|" + itype;
            if (seen.has(key)) return;
            seen.add(key);
            rows.push({
                url: url,
                issue: issue.title || itype || "—",
                impressions: imp,
                clicks: issue.gsc_clicks,
            });
        });

        rows.sort(function (a, b) {
            return (Number(b.impressions) || 0) - (Number(a.impressions) || 0);
        });
        return rows;
    }

    function buildGscQueryRows(state) {
        return state.queryRows
            .filter(function (q) {
                if (!q || typeof q !== "object") return false;
                var imp = Number(q.impressions);
                if (!imp || imp <= 0) return false;
                var query = String(q.query || q.keys || q.keyword || "").trim();
                return !!query;
            })
            .map(function (q) {
                var query = String(q.query || q.keys || q.keyword || "").trim();
                return {
                    query: query,
                    impressions: q.impressions,
                    clicks: q.clicks,
                    ctr: q.ctr,
                    position: q.position,
                };
            })
            .sort(function (a, b) {
                return (Number(b.impressions) || 0) - (Number(a.impressions) || 0);
            });
    }

    function renderGscDataTable(title, columns, rows, emptyMessage) {
        var wrap = document.createElement("div");
        wrap.className = "tech-gsc-table-block";
        var h4 = document.createElement("h4");
        h4.className = "tech-gsc-table-title";
        h4.textContent = title;
        wrap.appendChild(h4);
        if (!rows.length) {
            var empty = document.createElement("p");
            empty.className = "tech-gsc-table-empty";
            empty.textContent = emptyMessage;
            wrap.appendChild(empty);
            return wrap;
        }
        var tableWrap = document.createElement("div");
        tableWrap.className = "tech-dash-table-wrap";
        var table = document.createElement("table");
        table.className = "tech-dash-table tech-gsc-data-table";
        var thead = document.createElement("thead");
        var trh = document.createElement("tr");
        columns.forEach(function (col) {
            var th = document.createElement("th");
            th.textContent = col.label;
            trh.appendChild(th);
        });
        thead.appendChild(trh);
        table.appendChild(thead);
        var tbody = document.createElement("tbody");
        rows.forEach(function (row) {
            var tr = document.createElement("tr");
            columns.forEach(function (col) {
                var td = document.createElement("td");
                var raw = typeof col.get === "function" ? col.get(row) : row[col.key];
                if (col.html) td.innerHTML = raw == null ? "—" : String(raw);
                else td.textContent = raw != null && raw !== "" ? String(raw) : "—";
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        tableWrap.appendChild(table);
        wrap.appendChild(tableWrap);
        return wrap;
    }

    function renderGscStatusBar(host, state) {
        if (!host) return;
        host.className = "tech-gsc-status-bar " + (state.statusClass || "");
        host.innerHTML =
            '<div class="tech-gsc-status-main">' +
            '<span class="tech-gsc-status-pill ' +
            esc(state.statusClass || "") +
            '">' +
            esc(state.statusLabel) +
            "</span>" +
            (state.property
                ? '<span class="tech-gsc-status-prop" title="' + esc(state.property) + '">' + esc(state.property) + "</span>"
                : "") +
            '<span class="tech-gsc-status-range">' +
            esc(formatGscDateRangeLabel(state)) +
            "</span>" +
            "</div>" +
            (state.statusDetail
                ? '<p class="tech-gsc-status-detail">' + esc(state.statusDetail) + "</p>"
                : "");
    }

    function renderGscMetricsRow(host, state) {
        if (!host) return;
        host.textContent = "";
        if (!state.hasMetrics || !state.metrics) {
            host.hidden = true;
            return;
        }
        host.hidden = false;
        var m = state.metrics;
        var stats = [
            { label: "Impressions", val: fmtNum(m.impressions) },
            { label: "Clicks", val: fmtNum(m.clicks) },
            {
                label: "CTR",
                val: m.ctr != null && m.ctr !== "" ? (Number(m.ctr) * 100).toFixed(2) + "%" : "—",
            },
            {
                label: "Position",
                val: m.position != null && m.position !== "" ? Number(m.position).toFixed(1) : "—",
            },
        ];
        stats.forEach(function (st) {
            var el = document.createElement("div");
            el.className = "tech-dash-gsc-stat";
            el.innerHTML = "<span>" + esc(st.label) + "</span><strong>" + esc(st.val) + "</strong>";
            host.appendChild(el);
        });
    }

    function renderGscAlert(host, state) {
        if (!host) return;
        var show =
            state.quotaExceeded ||
            state.partialData ||
            (state.errors && state.errors.length) ||
            (state.status === "crawl_only" && !state.enabled) ||
            (state.status === "no_property");
        if (!show && state.status !== "error" && state.status !== "permission") {
            host.hidden = true;
            host.textContent = "";
            return;
        }
        host.hidden = false;
        var cls = "tech-gsc-alert";
        if (state.quotaExceeded || state.status === "permission" || state.status === "error") cls += " is-warn";
        else if (state.partialData || state.status === "no_property") cls += " is-info";
        host.className = cls;
        var lines = [];
        if (state.quotaExceeded) lines.push("Quota GSC đã hết — audit vẫn hoàn tất với dữ liệu crawl.");
        if (state.partialData && !state.quotaExceeded) lines.push("Dữ liệu GSC không đầy đủ — hiển thị những gì API trả về.");
        safeArr(state.errors).forEach(function (e) {
            if (e) lines.push(String(e));
        });
        if (state.status === "no_property") lines.push("Chọn property Search Console trước khi quét.");
        if (state.status === "crawl_only" && !state.enabled) {
            lines.push("Chế độ crawl_only — không có metric GSC cho lần quét này.");
        }
        host.textContent = lines.filter(Boolean).join(" ");
    }

    function renderGscTables(host, payload, dash, opts) {
        if (!host) return;
        host.textContent = "";
        var state = resolveGscViewState(payload);
        var compact = opts && opts.compact;
        var limit = compact ? 3 : 12;

        var lowCtr = buildGscLowCtrRows(state).slice(0, limit);
        var techRows = buildGscTechIssueRows(payload, dash).slice(0, limit);
        var queryRows = buildGscQueryRows(state).slice(0, limit);

        var ctrCols = [
            {
                label: "Trang",
                get: function (r) {
                    return '<span title="' + esc(r.url) + '">' + esc(truncateUrl(r.url, 48)) + "</span>";
                },
                html: true,
            },
            { label: "Impressions", get: function (r) { return fmtNum(r.impressions); } },
            {
                label: "CTR",
                get: function (r) {
                    return r.ctr != null ? (Number(r.ctr) * 100).toFixed(2) + "%" : "—";
                },
            },
            {
                label: "Vị trí",
                get: function (r) {
                    return r.position != null ? Number(r.position).toFixed(1) : "—";
                },
            },
        ];

        var techCols = [
            {
                label: "Trang",
                get: function (r) {
                    return '<span title="' + esc(r.url) + '">' + esc(truncateUrl(r.url, 42)) + "</span>";
                },
                html: true,
            },
            { label: "Lỗi", get: function (r) { return r.issue; } },
            { label: "Impressions", get: function (r) { return fmtNum(r.impressions); } },
        ];

        var queryCols = [
            { label: "Query", get: function (r) { return r.query; } },
            { label: "Impressions", get: function (r) { return fmtNum(r.impressions); } },
            {
                label: "CTR",
                get: function (r) {
                    return r.ctr != null ? (Number(r.ctr) * 100).toFixed(2) + "%" : "—";
                },
            },
            {
                label: "Vị trí",
                get: function (r) {
                    return r.position != null ? Number(r.position).toFixed(1) : "—";
                },
            },
        ];

        host.appendChild(
            renderGscDataTable(
                "Top trang: impression cao, CTR thấp",
                ctrCols,
                lowCtr,
                state.enabled
                    ? "Chưa phát hiện trang nào đủ điều kiện (cần impression cao + CTR thấp + vị trí hợp lệ)."
                    : "Cần quét hybrid với GSC để phân tích CTR theo trang."
            )
        );
        host.appendChild(
            renderGscDataTable(
                "Trang có impression + lỗi title/meta/canonical/index",
                techCols,
                techRows,
                state.enabled
                    ? "Chưa có trang traffic cao kèm lỗi on-page/index trong dữ liệu này."
                    : "Cần quét hybrid với GSC để đối chiếu traffic và lỗi kỹ thuật."
            )
        );
        host.appendChild(
            renderGscDataTable(
                "Query có impression — cần tối ưu nội dung",
                queryCols,
                queryRows,
                state.queryRows.length
                    ? "Không có query nào có impression trong payload."
                    : "Lần quét này chưa thu thập dữ liệu query từ GSC — chỉ hiển thị khi API trả về."
            )
        );
    }

    function renderGscHub(payload, opts) {
        opts = opts || {};
        var state = resolveGscViewState(payload);
        var dash = opts.dash || getDashboardForRender(payload);

        if (opts.statusHost) renderGscStatusBar(opts.statusHost, state);
        if (opts.metricsHost) renderGscMetricsRow(opts.metricsHost, state);
        if (opts.alertHost) renderGscAlert(opts.alertHost, state);
        if (opts.tablesHost) renderGscTables(opts.tablesHost, payload, dash, opts);

        var emptyEl = opts.emptyHost;
        if (emptyEl) {
            var hasContent =
                state.enabled ||
                state.connected ||
                state.hasMetrics ||
                state.opportunities.length ||
                state.enrichedPages.length;
            emptyEl.hidden = hasContent;
        }

        var viewTab = document.getElementById("techDashGscViewTab");
        if (viewTab) {
            viewTab.hidden = !state.enabled && !state.connected;
            if (!viewTab.dataset.wired && opts.hooks) {
                viewTab.dataset.wired = "1";
                viewTab.addEventListener("click", function () {
                    if (opts.hooks && typeof opts.hooks.navigateTab === "function") {
                        opts.hooks.navigateTab("gsc");
                    }
                });
            }
        }

        return state;
    }

    function renderDashboardGscCard(payload, hooks) {
        var card = document.getElementById("techDashGscCard");
        if (!card) return;
        renderGscHub(payload, {
            statusHost: document.getElementById("techDashGscStatus"),
            metricsHost: document.getElementById("techDashGscMiniStats"),
            alertHost: document.getElementById("techDashGscAlert"),
            tablesHost: document.getElementById("techDashGscTablesCompact"),
            emptyHost: document.getElementById("techDashGscEmpty"),
            compact: true,
            hooks: hooks,
        });
    }

    function renderGscTabIssues(host, dash, fullPayload) {
        if (!host) return;
        host.textContent = "";
        var issues = filterIssuesByGroup(dash, "gsc");
        if (!issues.length) return;
        var sec = document.createElement("section");
        sec.className = "tech-gsc-issues-section";
        sec.innerHTML = "<h3 class=\"tech-gsc-issues-title\">Issue xác nhận từ GSC</h3>";
        var list = document.createElement("div");
        list.className = "tech-v2-issue-grid";
        issues.slice(0, 20).forEach(function (issue) {
            list.appendChild(buildExplorerIssueCard(issue));
        });
        sec.appendChild(list);
        host.appendChild(sec);
    }

    function renderGscTab(fullPayload, dashboardV2, hooks) {
        hideTechPanels();
        var panel = document.getElementById("techContentGsc");
        var host = document.getElementById("techGscTabHost");
        var issuesHost = document.getElementById("techGscIssuesHost");
        if (!panel || !host) return;
        panel.hidden = false;
        var dash = dashboardV2 || getDashboardForRender(fullPayload);
        var hdr = document.getElementById("seoToolResultsHeader");
        if (hdr) hdr.hidden = false;
        renderOverviewScanHeader(fullPayload, dash);
        host.textContent = "";
        renderGscHub(fullPayload, {
            statusHost: (function () {
                var el = document.createElement("div");
                el.className = "tech-gsc-status-bar";
                host.appendChild(el);
                return el;
            })(),
            metricsHost: (function () {
                var el = document.createElement("div");
                el.className = "tech-dash-gsc-mini";
                host.appendChild(el);
                return el;
            })(),
            alertHost: (function () {
                var el = document.createElement("div");
                el.className = "tech-gsc-alert";
                el.hidden = true;
                host.appendChild(el);
                return el;
            })(),
            tablesHost: (function () {
                var el = document.createElement("div");
                el.className = "tech-gsc-tables-full";
                host.appendChild(el);
                return el;
            })(),
            dash: dash,
            hooks: hooks,
        });
        renderGscTabIssues(issuesHost, dash, fullPayload);
        var chrome = document.getElementById("techIssueGroupChrome");
        if (chrome) chrome.hidden = true;
        var issuesCard = document.getElementById("issuesCard");
        if (issuesCard) issuesCard.hidden = true;
        if (global.document && global.document.body) {
            global.document.body.classList.add("tech-gsc-tab-active");
        }
        var dr = document.querySelector(".tech-dash-date-range");
        if (dr) dr.hidden = false;
        var contentHdr = document.getElementById("techContentHeader");
        if (contentHdr) contentHdr.hidden = false;
        var titleEl = document.getElementById("techContentTitle");
        if (titleEl) titleEl.textContent = "Google Search Console";
        var subEl = document.getElementById("techContentSubtitle");
        if (subEl) {
            var n = filterIssuesByGroup(dash, "gsc").length;
            subEl.textContent =
                "Search Analytics, URL Inspection, quota và dữ liệu hybrid." +
                (n ? " — " + n + " lỗi GSC." : "");
        }
    }

    function aggregateIndexBuckets(payload) {
        var inspections = safeArr(payload.url_inspection_results);
        var buckets = { indexed: 0, crawlable: 0, blocked: 0, error: 0 };
        if (inspections.length) {
            inspections.forEach(function (insp) {
                if (!insp || insp.status === "error") {
                    buckets.error += 1;
                    return;
                }
                var cov = String(insp.coverage_state || insp.indexing_state || "").toLowerCase();
                if (cov.indexOf("indexed") >= 0 && cov.indexOf("not") < 0) buckets.indexed += 1;
                else if (cov.indexOf("blocked") >= 0 || cov.indexOf("forbidden") >= 0) buckets.blocked += 1;
                else if (cov.indexOf("crawl") >= 0 || cov.indexOf("discovered") >= 0) buckets.crawlable += 1;
                else buckets.error += 1;
            });
            return buckets;
        }
        var dash = getDash(payload);
        var issues = dash ? safeArr(dash.issues) : safeArr(payload.issues);
        issues.forEach(function (iss) {
            var ng = String(iss.nav_group || "");
            if (ng === "indexability") buckets.blocked += 1;
            else if (ng === "crawlability") buckets.error += 1;
        });
        var passed = dash ? safeArr(dash.passed_checks).length : 0;
        if (passed) buckets.indexed = passed;
        return buckets;
    }

    function renderDonut(host, segments) {
        if (!host) return;
        var total = segments.reduce(function (s, x) { return s + x.value; }, 0);
        if (!total) {
            host.textContent = "";
            return;
        }
        var r = 42;
        var c = 2 * Math.PI * r;
        var offset = 0;
        var svg = '<svg viewBox="0 0 100 100">';
        segments.forEach(function (seg) {
            if (!seg.value) return;
            var frac = seg.value / total;
            var dash = c * frac;
            svg +=
                '<circle cx="50" cy="50" r="' + r + '" fill="none" stroke="' + seg.color +
                '" stroke-width="14" stroke-dasharray="' + dash + " " + (c - dash) +
                '" stroke-dashoffset="' + (-offset) + '" transform="rotate(-90 50 50)"/>';
            offset += dash;
        });
        svg += "</svg>";
        host.innerHTML = svg;
    }

    function renderDashboardIndexCard(payload) {
        var body = document.getElementById("techDashIndexBody");
        var chart = document.getElementById("techDashIndexChart");
        var legend = document.getElementById("techDashIndexLegend");
        var empty = document.getElementById("techDashIndexEmpty");
        if (!body || !legend) return;
        var buckets = aggregateIndexBuckets(payload);
        var total = buckets.indexed + buckets.crawlable + buckets.blocked + buckets.error;
        if (!total) {
            body.hidden = true;
            if (empty) empty.hidden = false;
            return;
        }
        body.hidden = false;
        if (empty) empty.hidden = true;
        var segments = [
            { key: "indexed", label: "Đã index", color: "#22c55e", value: buckets.indexed },
            { key: "crawlable", label: "Có thể index", color: "#3b82f6", value: buckets.crawlable },
            { key: "blocked", label: "Bị chặn", color: "#f59e0b", value: buckets.blocked },
            { key: "error", label: "Lỗi", color: "#ef4444", value: buckets.error },
        ];
        renderDonut(chart, segments);
        legend.textContent = "";
        segments.forEach(function (seg) {
            if (!seg.value) return;
            var li = document.createElement("li");
            var pct = Math.round((seg.value / total) * 100);
            li.innerHTML =
                '<span class="lbl"><span class="dot" style="background:' + seg.color + '"></span>' +
                esc(seg.label) + "</span><strong>" + seg.value + " (" + pct + "%)</strong>";
            legend.appendChild(li);
        });
    }

    function findCwvMetric(issues, key) {
        var re = new RegExp(key, "i");
        for (var i = 0; i < issues.length; i++) {
            var iss = issues[i];
            var t = String(iss.issue_type || iss.type || "") + " " + String(iss.title || "");
            if (!re.test(t)) continue;
            var ev = safeArr(iss.evidence);
            for (var j = 0; j < ev.length; j++) {
                var v = ev[j] && ev[j].value;
                if (v != null && v !== "") return { raw: v, issue: iss };
            }
        }
        return null;
    }

    function renderDashboardPerfCard(payload) {
        var grid = document.getElementById("techDashCwvGrid");
        var empty = document.getElementById("techDashPerfEmpty");
        if (!grid) return;
        var dash = getDash(payload);
        var issues = dash ? safeArr(dash.issues) : safeArr(payload.normalized_issues || payload.issues);
        var perfIssues = issues.filter(function (i) {
            var ng = String(i.nav_group || "");
            return ng === "performance" || /lcp|inp|cls|cwv|pagespeed|speed/i.test(String(i.issue_type || i.type || ""));
        });
        var metrics = [
            { id: "Lcp", key: "lcp", label: "LCP" },
            { id: "Inp", key: "inp", label: "INP" },
            { id: "Cls", key: "cls", label: "CLS" },
        ];
        var any = false;
        metrics.forEach(function (m) {
            var hit = findCwvMetric(perfIssues.length ? perfIssues : issues, m.key);
            var valEl = document.getElementById("techDashCwv" + m.id);
            var stEl = document.getElementById("techDashCwv" + m.id + "Status");
            if (!valEl) return;
            if (hit) {
                any = true;
                valEl.textContent = String(hit.raw);
                if (stEl) {
                    stEl.textContent = "Cần xem";
                    stEl.className = "tech-dash-cwv-status is-mid";
                }
            } else {
                valEl.textContent = "—";
                if (stEl) {
                    stEl.textContent = perfIssues.length ? "Không đo" : "—";
                    stEl.className = "tech-dash-cwv-status";
                }
            }
        });
        if (grid) grid.hidden = !any && !perfIssues.length;
        if (empty) empty.hidden = any || perfIssues.length > 0;
        if (!any && perfIssues.length) {
            if (empty) {
                empty.hidden = false;
                empty.textContent = perfIssues.length + " vấn đề performance — mở tab Performance để xem chi tiết.";
            }
        }
    }

    function renderDashboardMobileCard(payload) {
        var scoreEl = document.getElementById("techDashMobileScore");
        var checks = document.getElementById("techDashMobileChecks");
        var body = document.getElementById("techDashMobileBody");
        var empty = document.getElementById("techDashMobileEmpty");
        if (!checks) return;
        var dash = getDash(payload);
        var issues = dash ? safeArr(dash.issues) : [];
        var mobileIssues = issues.filter(function (i) {
            return String(i.nav_group || "") === "ux_mobile" || /mobile/i.test(String(i.issue_type || ""));
        });
        var passedMobile = safeArr(dash && dash.passed_checks).filter(function (p) {
            return String(p.nav_group || "") === "ux_mobile";
        });
        checks.textContent = "";
        if (!mobileIssues.length && !passedMobile.length) {
            if (body) body.hidden = true;
            if (empty) empty.hidden = false;
            if (scoreEl) scoreEl.textContent = "—";
            return;
        }
        if (body) body.hidden = false;
        if (empty) empty.hidden = true;
        var total = mobileIssues.length + passedMobile.length;
        var pct = total ? Math.round((passedMobile.length / total) * 100) : null;
        if (scoreEl) {
            scoreEl.textContent = pct != null ? pct + "% Mobile Friendly" : "—";
            scoreEl.style.color = pct != null && pct >= 80 ? "#4ade80" : "#fbbf24";
        }
        mobileIssues.slice(0, 5).forEach(function (iss) {
            var li = document.createElement("li");
            var cnt = affectedCount(iss);
            li.innerHTML = "<span>" + esc(iss.title || "Vấn đề mobile") + "</span><strong>" + cnt + "</strong>";
            checks.appendChild(li);
        });
    }

    function renderDashboardAiCard(payload, dash, hooks) {
        var list = document.getElementById("techDashAiSuggestions");
        var empty = document.getElementById("techDashAiEmpty");
        if (!list) return;
        list.textContent = "";
        var tips = [];
        safeArr(dash && dash.priority_issues).slice(0, 3).forEach(function (p) {
            if (p && p.title) tips.push({ icon: "⚠", text: "Ưu tiên: " + p.title });
        });
        safeArr(dash && dash.score_explanation).slice(0, 2).forEach(function (line) {
            if (line) tips.push({ icon: "📊", text: String(line) });
        });
        safeArr(payload.disclaimers).slice(0, 2).forEach(function (line) {
            if (line) tips.push({ icon: "ℹ", text: String(line) });
        });
        if (!tips.length) {
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        tips.slice(0, 6).forEach(function (tip) {
            var li = document.createElement("li");
            li.innerHTML = '<span class="ai-ico">' + esc(tip.icon) + "</span><span>" + esc(tip.text) + "</span>";
            list.appendChild(li);
        });
        var viewAll = document.getElementById("techDashAiViewAll");
        if (viewAll && !viewAll.dataset.wired) {
            viewAll.dataset.wired = "1";
            viewAll.addEventListener("click", function () {
                if (hooks && typeof hooks.navigateTab === "function") hooks.navigateTab("priority");
            });
        }
    }

    function wireDashboardHeaderActions(hooks) {
        var share = document.getElementById("btnTechShareReport");
        if (share && !share.dataset.wired) {
            share.dataset.wired = "1";
            share.addEventListener("click", function () {
                var aid = global.__seoLastTechnicalAuditId;
                var url = location.origin + "/tool" + (aid ? "#audit=" + encodeURIComponent(aid) : "");
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(url).then(function () {
                        if (typeof global.setMsg === "function") global.setMsg("Đã sao chép link báo cáo.", "ok");
                    });
                }
            });
        }
        var pdf = document.getElementById("btnTechDownloadPdf");
        if (pdf && !pdf.dataset.wired) {
            pdf.dataset.wired = "1";
            pdf.addEventListener("click", function () {
                var aid = global.__seoLastTechnicalAuditId;
                if (aid && typeof global.downloadAuditExport === "function") {
                    global.downloadAuditExport(aid, "pdf");
                }
            });
        }
        var cmp = document.getElementById("btnTechCompare");
        if (cmp && !cmp.dataset.wired) {
            cmp.dataset.wired = "1";
            cmp.addEventListener("click", function () {
                global.__seoCompareTargetId = global.__seoLastTechnicalAuditId || null;
                global.__seoCompareAuto = true;
                if (hooks && typeof hooks.navigateTab === "function") hooks.navigateTab("history");
            });
        }
        var dr = document.getElementById("techDashDateRange");
        var gscSel = document.getElementById("gscDateRangeSelect");
        if (dr && gscSel && !dr.dataset.wired) {
            dr.dataset.wired = "1";
            dr.addEventListener("change", function () {
                gscSel.value = dr.value;
            });
        }
    }

    function wireOverviewGscBtnOnce() {
        var btn = document.getElementById("btnTechOverviewConnectGsc");
        if (!btn || btn.dataset.wired === "1") return;
        btn.dataset.wired = "1";
        btn.addEventListener("click", function () {
            var connect = document.getElementById("btnGoogleApisConnect");
            if (connect) {
                connect.scrollIntoView({ behavior: "smooth", block: "nearest" });
                connect.focus();
            }
        });
    }

    function buildPriorityCard(issue, idx) {
        var card = document.createElement("article");
        card.className = "seo-tool-priority-card tech-v2-priority-card";
        var sev = sevLabel(issue.severity);
        card.innerHTML =
            '<div class="seo-tool-priority-head">' +
            '<span class="seo-tool-priority-rank">' +
            (idx + 1) +
            "</span>" +
            '<span class="saas-badge ' +
            sevBadgeClass(sev) +
            '">' +
            sev.toUpperCase() +
            "</span>" +
            '<span class="tech-v2-nav-pill">' +
            esc(groupLabel(frontNavFromV2(issue.nav_group))) +
            "</span>" +
            "</div>";
        var h3 = document.createElement("h3");
        h3.className = "seo-tool-priority-title";
        h3.textContent = issue.title || "—";
        var meta = document.createElement("p");
        meta.className = "seo-tool-priority-meta";
        meta.textContent = "Ảnh hưởng ~" + affectedCount(issue) + " URL";
        var fix = document.createElement("p");
        fix.className = "seo-tool-priority-why";
        fix.textContent = (issue.how_to_fix || "").slice(0, 160) || issue.why_it_matters || "";
        var actions = document.createElement("div");
        actions.className = "seo-tool-priority-actions";
        var btnView = document.createElement("button");
        btnView.type = "button";
        btnView.className = "btn-priority-view-urls";
        btnView.textContent = "Xem URL ảnh hưởng";
        var btnDetail = document.createElement("button");
        btnDetail.type = "button";
        btnDetail.className = "btn-priority-how-to-fix";
        btnDetail.textContent = "Chi tiết";
        var norm = v2IssueToNormalized(issue) || issue;
        btnView.addEventListener("click", function (ev) {
            ev.stopPropagation();
            openIssueDrawer(norm);
        });
        btnDetail.addEventListener("click", function (ev) {
            ev.stopPropagation();
            openIssueDrawer(norm);
        });
        card.addEventListener("click", function () {
            openIssueDrawer(norm);
        });
        actions.appendChild(btnView);
        actions.appendChild(btnDetail);
        card.appendChild(h3);
        card.appendChild(meta);
        card.appendChild(fix);
        card.appendChild(actions);
        return card;
    }

    function renderNavGroupSummaries(dash, hooks) {
        var sec = document.getElementById("seoToolNavGroupSummaries");
        var grid = document.getElementById("seoToolNavGroupGrid");
        if (!sec || !grid) return;
        var rows = safeArr(dash && dash.nav_group_summaries).filter(function (r) {
            return r && r.group && r.group !== "audit_history" && r.group !== "overview";
        });
        grid.textContent = "";
        if (!rows.length) {
            sec.hidden = true;
            return;
        }
        sec.hidden = false;
        rows.forEach(function (row) {
            var front = frontNavFromV2(row.group);
            if (front === "overview" || front === "history") return;
            var card = document.createElement("button");
            card.type = "button";
            card.className = "tech-nav-group-card";
            var worst = String(row.worst_severity || "passed").toLowerCase();
            card.classList.add("tech-nav-group-card--" + (worst === "passed" ? "ok" : worst));
            card.innerHTML =
                '<span class="tech-nav-group-card-label">' +
                esc(groupLabel(front)) +
                "</span>" +
                '<span class="tech-nav-group-card-count">' +
                (Number(row.open_issues != null ? row.open_issues : row.issue_count) || 0) +
                " lỗi</span>" +
                '<span class="saas-badge ' +
                sevBadgeClass(worst === "warning" ? "warning" : worst) +
                '">' +
                (worst === "passed" ? "OK" : worst.toUpperCase()) +
                "</span>";
            card.addEventListener("click", function () {
                if (hooks && typeof hooks.navigateTab === "function") hooks.navigateTab(front);
            });
            grid.appendChild(card);
        });
    }

    function renderOverview(dashboardV2, fullPayload, hooks) {
        hideTechPanels();
        var ov = document.getElementById("seoToolResultsOverview");
        if (ov) ov.hidden = false;
        var dash = dashboardV2 || getDashboardForRender(fullPayload);
        renderOverviewV2Summary(fullPayload);
        renderOverviewScanHeader(fullPayload, dash);
        renderOverviewPriorityTop(dash, hooks);
        renderDashboardPerfCard(fullPayload);
        renderScoreTrend(fullPayload, hooks);
        hideOverviewExtraCards();
    }

    function hideOverviewExtraCards() {
        [
            "techDashGscCard",
            "techDashIndexCard",
            "techDashMobileCard",
            "techDashAiCard",
            "seoToolGscIntelSection",
            "seoToolNavGroupSummaries",
            "seoToolOverviewPassedCollapsible",
            "seoToolOverviewPassedSection",
        ].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.hidden = true;
        });
    }

    function renderScoreTrend(payload, hooks) {
        var host = document.getElementById("techDashScoreTrend");
        if (!host) return;
        var dash = getDash(payload);
        var current =
            dash && dash.technical_health_score != null
                ? Number(dash.technical_health_score)
                : payload && payload.technical_summary && payload.technical_summary.health_score != null
                  ? Number(payload.technical_summary.health_score)
                  : null;
        var domain = String((payload && payload.domain) || "").toLowerCase();
        function paint(points) {
            host.hidden = false;
            if (!points.length) {
                host.innerHTML = '<p class="tech-dash-empty">Cần thêm lần quét để xem xu hướng điểm.</p>';
                return;
            }
            var bars = points
                .map(function (p, i) {
                    var v = Math.max(0, Math.min(100, Number(p.score) || 0));
                    var h = Math.max(6, Math.round((v / 100) * 72));
                    var isLast = i === points.length - 1;
                    return (
                        '<span class="tech-trend-bar' +
                        (isLast ? " is-current" : "") +
                        '" style="height:' +
                        h +
                        'px" title="' +
                        esc(String(Math.round(v))) +
                        (p.at ? " · " + esc(String(p.at).slice(0, 10)) : "") +
                        '"></span>'
                    );
                })
                .join("");
            var last = points[points.length - 1];
            var prev = points.length > 1 ? points[points.length - 2] : null;
            var delta = prev && last ? Math.round(Number(last.score) - Number(prev.score)) : null;
            var deltaTxt = "Lần quét này";
            if (delta != null && !Number.isNaN(delta)) {
                if (delta > 0) deltaTxt = "Tăng " + delta + " điểm so với lần trước";
                else if (delta < 0) deltaTxt = "Giảm " + Math.abs(delta) + " điểm so với lần trước";
                else deltaTxt = "Không đổi so với lần trước";
            }
            host.innerHTML =
                '<div class="tech-trend-bars" aria-hidden="true">' +
                bars +
                '</div><p class="tech-trend-caption">' +
                esc(deltaTxt) +
                "</p>";
        }
        var token = hooks && typeof hooks.getToken === "function" ? hooks.getToken() : null;
        if (!token) {
            paint(current != null && !Number.isNaN(current) ? [{ score: current, at: "" }] : []);
            return;
        }
        fetch("/api/audit/runs?limit=8", { headers: { Authorization: "Bearer " + token } })
            .then(function (r) {
                return r.json();
            })
            .then(function (d) {
                var items = safeArr(d && (d.items || d.runs || d));
                var pts = items
                    .filter(function (run) {
                        if (!domain) return true;
                        return String(run.domain || "").toLowerCase() === domain;
                    })
                    .map(function (run) {
                        var st = auditRunStats(run);
                        return { score: st.score, at: run.at };
                    })
                    .filter(function (p) {
                        return p.score != null && !Number.isNaN(Number(p.score));
                    })
                    .slice(0, 6)
                    .reverse();
                if (!pts.length && current != null && !Number.isNaN(current)) {
                    pts = [{ score: current, at: "" }];
                }
                paint(pts);
            })
            .catch(function () {
                paint(current != null && !Number.isNaN(current) ? [{ score: current, at: "" }] : []);
            });
    }

    function renderPriorityIssues(dashboardV2, fullPayload) {
        hideTechPanels();
        var panel = document.getElementById("techContentPriority");
        var host = document.getElementById("techContentPriorityHost");
        if (!panel || !host) return;
        panel.hidden = false;
        host.textContent = "";
        var dash = dashboardV2 || getDashboardForRender(fullPayload);
        var issues = safeArr(dash && dash.priority_issues);
        var hdr = document.createElement("header");
        hdr.className = "tech-group-page-header";
        hdr.innerHTML = "<h3>Việc cần sửa</h3><p class=\"tech-group-page-sub\">Sửa những lỗi này trước.</p>";
        host.appendChild(hdr);
        host.appendChild(buildSimpleIssueTable(sortPriorityIssues(issues)));
    }

    function buildFullPriorityCard(issue, idx) {
        var card = document.createElement("article");
        card.className = "tech-v2-issue-card seo-tool-priority-card";
        var sev = sevLabel(issue.severity);
        var conf =
            issue.confidence != null && !Number.isNaN(Number(issue.confidence))
                ? Math.round(Number(issue.confidence) * 100) + "%"
                : "";
        card.innerHTML =
            '<div class="tech-v2-issue-card-head">' +
            '<span class="saas-badge ' +
            sevBadgeClass(sev) +
            '">' +
            sev.toUpperCase() +
            "</span>" +
            '<span class="tech-v2-nav-pill">' +
            esc(groupLabel(frontNavFromV2(issue.nav_group))) +
            "</span>" +
            (conf ? '<span class="tech-v2-conf-pill">Confidence ' + conf + "</span>" : "") +
            '<span class="tech-v2-src-pill">' +
            esc(issue.source || "crawl") +
            "</span>" +
            "</div>";
        var title = document.createElement("h4");
        title.className = "tech-v2-issue-title";
        title.textContent = issue.title || "—";
        var meta = document.createElement("p");
        meta.className = "tech-v2-issue-meta";
        meta.textContent = formatSeoImpactText(issue);
        var urlMeta = document.createElement("p");
        urlMeta.className = "tech-v2-issue-meta";
        urlMeta.textContent = affectedCount(issue) + " URL bị ảnh hưởng";
        var fix = document.createElement("p");
        fix.className = "tech-v2-issue-fix";
        fix.textContent = issue.how_to_fix || "—";
        var actions = document.createElement("div");
        actions.className = "tech-v2-issue-actions";
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tech-dash-detail-btn";
        btn.textContent = "Xem chi tiết";
        var norm = v2IssueToNormalized(issue) || issue;
        btn.addEventListener("click", function (ev) {
            ev.stopPropagation();
            openIssueDrawer(norm);
        });
        card.addEventListener("click", function () {
            openIssueDrawer(norm);
        });
        actions.appendChild(btn);
        card.appendChild(title);
        card.appendChild(urlMeta);
        card.appendChild(meta);
        card.appendChild(fix);
        card.appendChild(actions);
        return card;
    }

    function ensureGroupChrome() {
        var chrome = document.getElementById("techIssueGroupChrome");
        if (!chrome) {
            chrome = document.createElement("div");
            chrome.id = "techIssueGroupChrome";
            chrome.className = "tech-issue-group-chrome";
            var panel = document.getElementById("toolTablePanel");
            var issuesCard = document.getElementById("issuesCard");
            if (panel) {
                var container = panel.querySelector(".container--wide") || panel;
                if (issuesCard && issuesCard.parentNode === container) {
                    container.insertBefore(chrome, issuesCard);
                } else {
                    container.appendChild(chrome);
                }
            }
        }
        if (!document.getElementById("techGroupHeaderHost")) {
            var hdr = document.createElement("section");
            hdr.id = "techGroupHeaderHost";
            hdr.className = "card seo-tool-card tech-group-header-card";
            chrome.appendChild(hdr);
        }
        if (!document.getElementById("techGroupSummaryGrid")) {
            var grid = document.createElement("div");
            grid.id = "techGroupSummaryGrid";
            grid.className = "tech-group-summary-grid";
            chrome.appendChild(grid);
        }
        if (!document.getElementById("techGroupExplorerHost")) {
            var exp = document.createElement("div");
            exp.id = "techGroupExplorerHost";
            exp.className = "tech-group-explorer-host";
            chrome.appendChild(exp);
        }
        if (!document.getElementById("techGroupPassedHost")) {
            var passed = document.createElement("div");
            passed.id = "techGroupPassedHost";
            passed.className = "tech-group-passed-host";
            chrome.appendChild(passed);
        }
        return chrome;
    }

    function renderGroupHeader(groupKey, issues, passedCount) {
        var host = document.getElementById("techGroupHeaderHost");
        if (!host) return;
        var counts = countBySeverity(issues);
        host.innerHTML =
            '<div class="tech-group-header-inner">' +
            "<h3>" +
            esc(groupLabel(groupKey)) +
            "</h3>" +
            '<p class="tech-group-header-stats">' +
            "<span>" +
            issues.length +
            " lỗi</span>" +
            '<span class="tech-stat-critical">' +
            counts.critical +
            " nghiêm trọng</span>" +
            '<span class="tech-stat-warning">' +
            counts.warning +
            " cảnh báo</span>" +
            '<span class="tech-stat-opportunity">' +
            counts.opportunity +
            " cơ hội</span>" +
            "</p></div>";
    }

    function renderGroupSummaryCards(issues) {
        var grid = document.getElementById("techGroupSummaryGrid");
        if (!grid) return;
        grid.innerHTML = "";
        grid.hidden = true;
    }

    function buildExplorerIssueCard(issue) {
        var card = document.createElement("article");
        card.className = "tech-v2-issue-card seo-tool-issue-card is-clickable";
        var sev = sevLabel(issue.severity);
        var conf =
            issue.confidence != null && !Number.isNaN(Number(issue.confidence))
                ? Math.round(Number(issue.confidence) * 100) + "%"
                : "—";
        card.innerHTML =
            '<div class="tech-v2-issue-card-head">' +
            '<span class="saas-badge ' +
            sevBadgeClass(sev) +
            '">' +
            sev.toUpperCase() +
            "</span>" +
            '<span class="tech-v2-src-pill">' +
            esc(issue.source || "crawl") +
            "</span>" +
            '<span class="tech-v2-conf-pill">' +
            conf +
            "</span>" +
            "</div>";
        var title = document.createElement("h4");
        title.className = "tech-v2-issue-title";
        title.textContent = issue.title || "—";
        var meta = document.createElement("p");
        meta.className = "tech-v2-issue-meta";
        meta.textContent = affectedCount(issue) + " URL ảnh hưởng";
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tech-v2-issue-detail-btn";
        btn.textContent = "Xem chi tiết";
        var norm = v2IssueToNormalized(issue) || issue;
        btn.addEventListener("click", function (ev) {
            ev.stopPropagation();
            openIssueDrawer(norm);
        });
        card.addEventListener("click", function () {
            openIssueDrawer(norm);
        });
        card.appendChild(title);
        card.appendChild(meta);
        card.appendChild(btn);
        return card;
    }

    function renderIssueExplorer(issues) {
        var host = document.getElementById("techGroupExplorerHost");
        if (!host) return;
        host.textContent = "";
        host.appendChild(buildSimpleIssueTable(issues));
    }

    function renderGroupPassedChecks(groupKey, dash) {
        var host = document.getElementById("techGroupPassedHost");
        if (!host) return;
        host.textContent = "";
        var v2g = sidebarToV2NavGroup(groupKey);
        var passed = safeArr(dash && dash.passed_checks).filter(function (p) {
            if (!p) return false;
            var ng = String(p.nav_group || "");
            return ng === v2g || frontNavFromV2(ng) === groupKey;
        });
        if (!passed.length) return;
        var sec = document.createElement("section");
        sec.className = "card seo-tool-card tech-group-passed-card";
        sec.innerHTML = "<h4>Passed checks trong nhóm</h4>";
        var ul = document.createElement("ul");
        ul.className = "tech-passed-collapsible-body";
        passed.forEach(function (p) {
            var li = document.createElement("li");
            li.className = "tech-passed-collapsible-item";
            li.textContent = p.title || p.issue_id || "Check";
            ul.appendChild(li);
        });
        sec.appendChild(ul);
        host.appendChild(sec);
    }

    function renderIssueGroup(groupKey, dashboardV2, fullPayload) {
        hideTechPanels();
        var chrome = ensureGroupChrome();
        if (chrome) chrome.hidden = false;
        var dash = dashboardV2 || getDashboardForRender(fullPayload);
        var issues = filterIssuesByGroup(dash, groupKey);
        renderGroupHeader(groupKey, issues, 0);
        renderGroupSummaryCards(issues);
        var explorer = document.getElementById("techGroupExplorerHost");
        if (explorer) {
            explorer.textContent = "";
            explorer.appendChild(buildSimpleIssueTable(issues));
        }
        var passedHost = document.getElementById("techGroupPassedHost");
        if (passedHost) passedHost.textContent = "";
        var issuesCard = document.getElementById("issuesCard");
        if (issuesCard) issuesCard.hidden = true;
        var catPanel = document.getElementById("techCategoryPanel");
        if (catPanel) catPanel.hidden = true;
        var crawlExtras = document.getElementById("crawlExtrasCard");
        if (crawlExtras) {
            crawlExtras.hidden = groupKey !== "index_crawl" && groupKey !== "crawlability" && groupKey !== "internal_links";
        }
    }

    function formatAuditTime(at) {
        if (!at) return "—";
        return String(at).slice(0, 16).replace("T", " ");
    }

    function auditRunStats(run) {
        var ts = safeObj(run.technical_summary) || {};
        var by = safeObj(ts.issues_by_severity) || {};
        var dash = safeObj(run.technical_dashboard_v3) || safeObj(run.technical_dashboard_v2);
        if (dash && dash.summary) {
            return {
                score: dash.technical_health_score != null ? dash.technical_health_score : ts.health_score,
                critical: Number(dash.summary.critical) || 0,
                warning: Number(dash.summary.warning) || 0,
                pages: dash.pages_scanned != null ? dash.pages_scanned : run.pages_scanned,
            };
        }
        return {
            score: ts.health_score,
            critical: Number(by.critical) || 0,
            warning: Number(by.high) || Number(by.warning) || 0,
            pages: run.pages_scanned,
        };
    }

    function findPreviousRunForDomain(runs, targetRun) {
        if (!targetRun || !runs || !runs.length) return null;
        var dom = String(targetRun.domain || targetRun.source_url || "").trim().toLowerCase();
        if (!dom) return null;
        var seenTarget = false;
        for (var i = 0; i < runs.length; i++) {
            var r = runs[i];
            var rd = String(r.domain || r.source_url || "").trim().toLowerCase();
            if (String(r.id) === String(targetRun.id)) {
                seenTarget = true;
                continue;
            }
            if (seenTarget && rd === dom) return r;
        }
        return null;
    }

    function renderCompareIssueList(title, items, tone) {
        var sec = document.createElement("div");
        sec.className = "tech-compare-list tech-compare-list-" + (tone || "neutral");
        var h = document.createElement("h4");
        h.className = "tech-compare-list-title";
        h.textContent = title + " (" + (items ? items.length : 0) + ")";
        sec.appendChild(h);
        if (!items || !items.length) {
            var empty = document.createElement("p");
            empty.className = "tech-compare-empty";
            empty.textContent = "Không có.";
            sec.appendChild(empty);
            return sec;
        }
        var ul = document.createElement("ul");
        ul.className = "tech-compare-issue-ul";
        items.slice(0, 12).forEach(function (it) {
            var li = document.createElement("li");
            var tier = it.priority_tier ? " [" + it.priority_tier + "]" : "";
            li.textContent = (it.title || it.issue_type || "—") + tier;
            ul.appendChild(li);
        });
        if (items.length > 12) {
            var more = document.createElement("li");
            more.className = "tech-compare-more";
            more.textContent = "+ " + (items.length - 12) + " lỗi khác…";
            ul.appendChild(more);
        }
        sec.appendChild(ul);
        return sec;
    }

    function renderAuditComparePanel(data, hooks) {
        var host = document.getElementById("techAuditCompareHost");
        if (!host) return;
        host.hidden = false;
        host.textContent = "";
        var card = document.createElement("div");
        card.className = "tech-audit-compare-card";
        var delta = data.score_delta;
        var deltaText =
            delta == null
                ? "—"
                : (delta > 0 ? "+" : "") + Math.round(Number(delta)) + " điểm";
        var deltaCls =
            delta == null ? "" : delta > 0 ? "is-up" : delta < 0 ? "is-down" : "is-flat";
        card.innerHTML =
            '<div class="tech-compare-head">' +
            "<h3>So sánh audit</h3>" +
            '<button type="button" class="tech-compare-close">Đóng</button>' +
            "</div>" +
            '<div class="tech-compare-scores">' +
            '<div class="tech-compare-score"><span class="lbl">Trước</span><strong>' +
            (data.score_before != null ? Math.round(Number(data.score_before)) : "—") +
            "</strong></div>" +
            '<div class="tech-compare-score tech-compare-delta ' +
            esc(deltaCls) +
            '"><span class="lbl">Thay đổi</span><strong>' +
            esc(deltaText) +
            "</strong></div>" +
            '<div class="tech-compare-score"><span class="lbl">Sau</span><strong>' +
            (data.score_after != null ? Math.round(Number(data.score_after)) : "—") +
            "</strong></div>" +
            "</div>";
        var grid = document.createElement("div");
        grid.className = "tech-compare-grid";
        grid.appendChild(renderCompareIssueList("Đã sửa", safeArr(data.fixed), "fixed"));
        grid.appendChild(renderCompareIssueList("Lỗi mới", safeArr(data.new), "new"));
        grid.appendChild(renderCompareIssueList("Còn lại", safeArr(data.remaining), "remaining"));
        card.appendChild(grid);
        host.appendChild(card);
        var closeBtn = card.querySelector(".tech-compare-close");
        if (closeBtn) {
            closeBtn.addEventListener("click", function () {
                host.hidden = true;
                host.textContent = "";
            });
        }
    }

    function fetchAuditCompare(baseId, targetId, token, hooks) {
        var host = document.getElementById("techAuditCompareHost");
        if (!host || !baseId || !targetId || !token) return;
        host.hidden = false;
        host.innerHTML = '<p class="tech-history-loading">Đang so sánh…</p>';
        fetch(
            "/api/audit/compare?base_id=" +
                encodeURIComponent(baseId) +
                "&target_id=" +
                encodeURIComponent(targetId),
            { headers: { Authorization: "Bearer " + token } }
        )
            .then(function (r) {
                return r.json().then(function (d) {
                    return { ok: r.ok, d: d };
                });
            })
            .then(function (res) {
                if (!res.ok) throw new Error((res.d && res.d.detail) || "Không so sánh được");
                renderAuditComparePanel(res.d, hooks);
            })
            .catch(function (err) {
                host.innerHTML =
                    '<div class="tech-scan-error-inline"><p>' +
                    esc(String(err.message || err)) +
                    "</p></div>";
            });
    }

    function renderAuditHistory(hooks) {
        hideTechPanels();
        var panel = document.getElementById("techContentHistory");
        var host = document.getElementById("techAuditHistoryHost");
        if (!panel) return;
        panel.hidden = false;
        if (!host) return;
        host.innerHTML = '<p class="tech-history-loading">Đang tải lịch sử…</p>';
        var token = hooks && typeof hooks.getToken === "function" ? hooks.getToken() : null;
        if (!token) {
            host.innerHTML =
                '<div class="tech-empty-state-card"><p>Đăng nhập để xem lịch sử audit.</p></div>';
            return;
        }
        fetch("/api/audit/runs?limit=20", {
            headers: { Authorization: "Bearer " + token },
        })
            .then(function (r) {
                return r.json().then(function (d) {
                    return { ok: r.ok, d: d };
                });
            })
            .then(function (res) {
                if (!res.ok) throw new Error((res.d && res.d.detail) || "Không tải được lịch sử");
                var runs = safeArr(res.d && res.d.runs);
                if (!runs.length) {
                    host.innerHTML =
                        '<div class="tech-empty-state-card"><p>Chưa có lần quét nào.</p></div>';
                    return;
                }
                var table = document.createElement("div");
                table.className = "tech-audit-history-table-wrap";
                table.innerHTML =
                    "<table class=\"tech-audit-history-table\"><thead><tr>" +
                    "<th>Thời gian</th><th>Domain</th><th>Score</th><th>Critical</th><th>Warning</th><th>Pages</th><th></th><th></th>" +
                    "</tr></thead><tbody></tbody></table>";
                var tbody = table.querySelector("tbody");
                runs.forEach(function (run, idx) {
                    var st = auditRunStats(run);
                    var tr = document.createElement("tr");
                    tr.innerHTML =
                        "<td>" +
                        esc(formatAuditTime(run.at)) +
                        "</td>" +
                        "<td>" +
                        esc(run.domain || run.source_url || "—") +
                        "</td>" +
                        "<td>" +
                        (st.score != null ? Math.round(Number(st.score)) : "—") +
                        "</td>" +
                        "<td>" +
                        (st.critical || 0) +
                        "</td>" +
                        "<td>" +
                        (st.warning || 0) +
                        "</td>" +
                        "<td>" +
                        (st.pages != null ? st.pages : "—") +
                        "</td>" +
                        '<td><button type="button" class="tech-audit-open-btn">Mở</button></td>' +
                        '<td><button type="button" class="tech-audit-compare-btn">So sánh</button></td>';
                    tr.querySelector(".tech-audit-open-btn").addEventListener("click", function () {
                        if (hooks && typeof hooks.openAudit === "function" && run.id) {
                            hooks.openAudit(run.id);
                        }
                    });
                    tr.querySelector(".tech-audit-compare-btn").addEventListener("click", function () {
                        var prev = findPreviousRunForDomain(runs, run);
                        if (!prev) {
                            if (typeof global.setMsg === "function") {
                                global.setMsg("Không có lần quét trước cùng domain để so sánh.", "error");
                            }
                            return;
                        }
                        fetchAuditCompare(prev.id, run.id, token, hooks);
                    });
                    tbody.appendChild(tr);
                });
                host.textContent = "";
                host.appendChild(table);
                if (global.__seoCompareAuto && global.__seoCompareTargetId) {
                    var targetId = global.__seoCompareTargetId;
                    global.__seoCompareAuto = false;
                    var targetRun = runs.filter(function (r) {
                        return String(r.id) === String(targetId);
                    })[0];
                    if (targetRun) {
                        var baseRun = findPreviousRunForDomain(runs, targetRun);
                        if (baseRun) fetchAuditCompare(baseRun.id, targetRun.id, token, hooks);
                    }
                }
            })
            .catch(function (err) {
                host.innerHTML =
                    '<div class="tech-scan-error-inline"><p>' +
                    esc(String(err.message || err)) +
                    '</p><button type="button" class="tech-audit-retry-btn">Thử lại</button></div>';
                var retry = host.querySelector(".tech-audit-retry-btn");
                if (retry) {
                    retry.addEventListener("click", function () {
                        renderAuditHistory(hooks);
                    });
                }
            });
    }

    function renderTechnicalGroup(groupKey, dashboardV2, fullPayload, hooks) {
        var key = String(groupKey || "overview");
        var dash = dashboardV2 || getDashboardForRender(fullPayload);
        if (!fullPayload || !dash) return false;
        if (key === "overview") {
            renderOverview(dash, fullPayload, hooks);
            return true;
        }
        var hdr = document.getElementById("seoToolResultsHeader");
        if (hdr) hdr.hidden = false;
        renderOverviewScanHeader(fullPayload, dash);
        if (key === "priority") {
            renderPriorityIssues(dash, fullPayload);
            return true;
        }
        if (key === "history") {
            renderAuditHistory(hooks);
            return true;
        }
        if (key === "gsc") {
            renderGscTab(fullPayload, dash, hooks);
            return true;
        }
        if (ISSUE_GROUP_TABS[key]) {
            renderIssueGroup(key, dash, fullPayload);
            return true;
        }
        return false;
    }

    function updateScanSteps(activeIndex) {
        var wrap = document.getElementById("technicalScanProgressSteps");
        if (!wrap) return;
        wrap.querySelectorAll(".tech-scan-step").forEach(function (el, idx) {
            el.classList.toggle("is-done", idx < activeIndex);
            el.classList.toggle("is-active", idx === activeIndex);
        });
    }

    function showScanProgress() {
        var wrap = document.getElementById("technicalScanProgressWrap");
        var bar = document.getElementById("technicalScanProgressBar");
        var label = document.getElementById("technicalScanProgressLabel");
        if (!wrap || !bar) return;
        hideScanError();
        wrap.hidden = false;
        bar.style.width = "0%";
        _scanStepIndex = 0;
        updateScanSteps(0);
        if (label) label.textContent = "Đang quét Technical Analysis…";
        var stepsHost = document.getElementById("technicalScanProgressSteps");
        if (stepsHost && !stepsHost.children.length) {
            SCAN_STEPS.forEach(function (text, idx) {
                var div = document.createElement("div");
                div.className = "tech-scan-step";
                div.textContent = idx + 1 + ". " + text;
                stepsHost.appendChild(div);
            });
        }
        var t0 = Date.now();
        global.__seoScanStartedAt = t0;
        if (_scanProgressTimer) clearInterval(_scanProgressTimer);
        _scanProgressTimer = setInterval(function () {
            var elapsed = Date.now() - t0;
            var pct = Math.min(96, (1 - Math.exp((-3.2 * elapsed) / (15 * 60 * 1000))) * 100);
            bar.style.width = pct.toFixed(2) + "%";
            var step = Math.min(SCAN_STEPS.length - 1, Math.floor(elapsed / 18000));
            if (step !== _scanStepIndex) {
                _scanStepIndex = step;
                updateScanSteps(step);
            }
        }, 450);
    }

    function setScanJobProgress(pct, message) {
        var wrap = document.getElementById("technicalScanProgressWrap");
        var bar = document.getElementById("technicalScanProgressBar");
        var label = document.getElementById("technicalScanProgressLabel");
        if (!wrap || !bar) return;
        wrap.hidden = false;
        if (_scanProgressTimer) {
            clearInterval(_scanProgressTimer);
            _scanProgressTimer = null;
        }
        var n = Math.max(1, Math.min(96, Number(pct) || 0));
        bar.style.width = n.toFixed(1) + "%";
        if (label && message) label.textContent = String(message);
        var step = Math.min(SCAN_STEPS.length - 1, Math.floor(n / (100 / SCAN_STEPS.length)));
        if (step !== _scanStepIndex) {
            _scanStepIndex = step;
            updateScanSteps(step);
        }
    }

    function hideScanProgress(completedOk) {
        if (_scanProgressTimer) {
            clearInterval(_scanProgressTimer);
            _scanProgressTimer = null;
        }
        var wrap = document.getElementById("technicalScanProgressWrap");
        var bar = document.getElementById("technicalScanProgressBar");
        var label = document.getElementById("technicalScanProgressLabel");
        if (!wrap || !bar) return;
        if (completedOk) {
            if (global.__seoScanStartedAt) {
                global.__seoLastScanElapsedMs = Date.now() - global.__seoScanStartedAt;
            }
            updateScanSteps(SCAN_STEPS.length);
            bar.style.width = "100%";
            if (label) label.textContent = "Hoàn tất — đang hiển thị kết quả…";
            setTimeout(function () {
                wrap.hidden = true;
                bar.style.width = "0%";
                if (label) label.textContent = "";
                updateScanSteps(0);
            }, 450);
        } else {
            wrap.hidden = true;
            bar.style.width = "0%";
            if (label) label.textContent = "";
            updateScanSteps(0);
        }
    }

    function showScanError(message, onRetry) {
        var card = document.getElementById("techScanErrorCard");
        var msgEl = document.getElementById("techScanErrorMessage");
        var btn = document.getElementById("btnTechScanRetry");
        if (!card) return;
        card.hidden = false;
        if (msgEl) msgEl.textContent = message || "Đã xảy ra lỗi khi quét.";
        if (btn && btn.dataset.wired !== "1") {
            btn.dataset.wired = "1";
            btn.addEventListener("click", function () {
                hideScanError();
                if (typeof onRetry === "function") onRetry();
            });
        }
        if (btn && onRetry) btn.onclick = function () {
            hideScanError();
            onRetry();
        };
    }

    function hideScanError() {
        var card = document.getElementById("techScanErrorCard");
        if (card) card.hidden = true;
    }

    function init() {
        wireIssueDrawer();
        wirePassedCollapsibleToggle();
        wireOverviewGscBtnOnce();
        wireDashboardHeaderActions(null);
    }

    global.TechDashboardV2 = {
        hasV2: hasV2,
        getDash: getDash,
        dashSchemaVersion: dashSchemaVersion,
        enrichPayload: enrichPayload,
        resolveIssues: resolveIssues,
        resolvePriorityIssues: resolvePriorityIssues,
        resolveSummary: resolveSummary,
        resolveNavSummaries: resolveNavSummaries,
        v2IssueToNormalized: v2IssueToNormalized,
        frontNavFromV2: frontNavFromV2,
        getDashboardForRender: getDashboardForRender,
        canUseGroupRenderer: canUseGroupRenderer,
        issueMatchesSidebarTab: issueMatchesSidebarTab,
        filterIssuesByGroup: filterIssuesByGroup,
        renderTechnicalGroup: renderTechnicalGroup,
        renderOverview: renderOverview,
        renderPriorityIssues: renderPriorityIssues,
        renderIssueGroup: renderIssueGroup,
        renderAuditHistory: renderAuditHistory,
        renderAuditComparePanel: renderAuditComparePanel,
        fetchAuditCompare: fetchAuditCompare,
        renderOverviewV2Summary: renderOverviewV2Summary,
        renderPassedCollapsible: renderPassedCollapsible,
        getTopPriorityIssues: getTopPriorityIssues,
        sortPriorityIssues: sortPriorityIssues,
        renderOverviewPriorityTop: renderOverviewPriorityTop,
        buildSimpleIssueTable: buildSimpleIssueTable,
        renderGscTab: renderGscTab,
        resolveGscViewState: resolveGscViewState,
        buildGscLowCtrRows: buildGscLowCtrRows,
        buildGscTechIssueRows: buildGscTechIssueRows,
        openIssueDrawer: openIssueDrawer,
        closeIssueDrawer: closeIssueDrawer,
        wireExplorerV2Filters: wireExplorerV2Filters,
        getExplorerV2Filters: getExplorerV2Filters,
        issueMatchesV2Filters: issueMatchesV2Filters,
        getMaxPages: getMaxPages,
        showScanProgress: showScanProgress,
        setScanJobProgress: setScanJobProgress,
        hideScanProgress: hideScanProgress,
        showScanError: showScanError,
        hideScanError: hideScanError,
        init: init,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})(typeof window !== "undefined" ? window : globalThis);
