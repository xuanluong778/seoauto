/** SEO Tool page — Audit: passed, export, sidebar */
function navigateTechTab(tabId) {
    var next = normalizeTechTabKey(tabId || "overview");
    if (next === "passed") next = "overview";
    var changed = next !== activeTechTab;
    activeTechTab = next;
    syncIssuesTableFilterBucket();
    mountTechResultsInRightPanel();
    setTechNavActive(activeTechTab);
    revealToolResultsPanel();
    if (changed) {
        renderTechTabContent();
    }
    syncMobileNavSelect();
    document.body.classList.add("seo-tool-tab-active");
    if (changed) {
        var anchor =
            document.getElementById("techContentHeader") ||
            document.getElementById("toolTablePanel");
        scrollToTechPanel(anchor);
    }
}

function renderTechTabContent() {
    wireIssuesToolbarOnce();
    populateMobileNavSelect();
    mountTechResultsInRightPanel();
    updateTechContentHeader();
    const tab = normalizeTechTabKey(activeTechTab);
    const TD = window.TechDashboardV2;

    if (!cachedTechnicalPayload) {
        const ov = document.getElementById("seoToolResultsOverview");
        const issuesCardEl = document.getElementById("issuesCard");
        const passedPanel = document.getElementById("techContentPassed");
        const priorityPanel = document.getElementById("techContentPriority");
        const historyPanel = document.getElementById("techContentHistory");
        const catPanel = document.getElementById("techCategoryPanel");
        const resultsHdr = document.getElementById("seoToolResultsHeader");
        if (ov) ov.hidden = true;
        if (issuesCardEl) issuesCardEl.hidden = true;
        if (passedPanel) passedPanel.hidden = true;
        if (priorityPanel) priorityPanel.hidden = true;
        if (historyPanel) historyPanel.hidden = true;
        if (catPanel) catPanel.hidden = true;
        if (resultsHdr) resultsHdr.hidden = true;
        const chrome = document.getElementById("techIssueGroupChrome");
        if (chrome) chrome.hidden = true;
        return;
    }

    if (TD && typeof TD.canUseGroupRenderer === "function" && TD.canUseGroupRenderer(cachedTechnicalPayload)) {
        if (typeof TD.enrichPayload === "function") TD.enrichPayload(cachedTechnicalPayload);
        const dash = typeof TD.getDashboardForRender === "function"
            ? TD.getDashboardForRender(cachedTechnicalPayload)
            : null;
        TD.renderTechnicalGroup(tab, dash, cachedTechnicalPayload, {
            navigateTab: navigateTechTab,
            openAudit: openAuditRun,
            getToken: function () { return token; },
        });
        if (tab !== "overview") {
            const ov = document.getElementById("seoToolResultsOverview");
            if (ov) ov.hidden = true;
        }
        return;
    }

    const ov = document.getElementById("seoToolResultsOverview");
    const issuesCardEl = document.getElementById("issuesCard");
    const passedPanel = document.getElementById("techContentPassed");
    const priorityPanel = document.getElementById("techContentPriority");
    const historyPanel = document.getElementById("techContentHistory");
    const crawlExtras = document.getElementById("crawlExtrasCard");
    const passedLegacy = document.getElementById("seoToolPassedChecksSection");
    const resultsHdr = document.getElementById("seoToolResultsHeader");
    const catPanel = document.getElementById("techCategoryPanel");

    if (!cachedTechnicalPayload) {
        if (ov) ov.hidden = true;
        if (issuesCardEl) issuesCardEl.hidden = true;
        if (passedPanel) passedPanel.hidden = true;
        if (priorityPanel) priorityPanel.hidden = true;
        if (historyPanel) historyPanel.hidden = true;
        if (catPanel) catPanel.hidden = true;
        if (resultsHdr) resultsHdr.hidden = true;
        return;
    }

    if (resultsHdr) resultsHdr.hidden = false;
    renderResultsHeader(cachedTechnicalPayload);

    if (tab === "overview") {
        if (ov) ov.hidden = false;
        if (issuesCardEl) issuesCardEl.hidden = true;
        if (passedPanel) passedPanel.hidden = true;
        if (priorityPanel) priorityPanel.hidden = true;
        if (historyPanel) historyPanel.hidden = true;
        if (crawlExtras) crawlExtras.hidden = true;
        if (passedLegacy) passedLegacy.hidden = true;
        if (catPanel) catPanel.hidden = true;
        renderOverviewContent(cachedTechnicalPayload);
        return;
    }

    if (ov) ov.hidden = true;
    if (passedLegacy) passedLegacy.hidden = true;

    if (tab === "passed") {
        if (issuesCardEl) issuesCardEl.hidden = true;
        if (passedPanel) passedPanel.hidden = false;
        if (priorityPanel) priorityPanel.hidden = true;
        if (historyPanel) historyPanel.hidden = true;
        if (crawlExtras) crawlExtras.hidden = true;
        if (catPanel) catPanel.hidden = true;
        renderPassedTabContent(cachedTechnicalPayload);
        return;
    }

    if (tab === "history") {
        if (issuesCardEl) issuesCardEl.hidden = true;
        if (passedPanel) passedPanel.hidden = true;
        if (priorityPanel) priorityPanel.hidden = true;
        if (historyPanel) historyPanel.hidden = false;
        if (crawlExtras) crawlExtras.hidden = true;
        if (catPanel) catPanel.hidden = true;
        if (TD && typeof TD.renderAuditHistory === "function") {
            TD.renderAuditHistory({
                navigateTab: navigateTechTab,
                openAudit: openAuditRun,
                getToken: function () { return token; },
            });
        }
        return;
    }

    if (issuesCardEl) issuesCardEl.hidden = false;
    if (passedPanel) passedPanel.hidden = true;
    if (priorityPanel) priorityPanel.hidden = true;
    if (historyPanel) historyPanel.hidden = true;
    if (crawlExtras) {
        crawlExtras.hidden = tab !== "crawlability" && tab !== "internal_links";
    }

    renderCategoryTabExtras(tab);

    const heading = document.getElementById("issuesCardHeading");
    const label = TECH_TAB_LABELS[tab] || tab;
    const n = countIssuesForTab(tab, cachedNormalizedIssues);
    if (heading) heading.textContent = label + " — " + n + " lỗi phát hiện";

    hidePillarIssueView();
    if (!cachedNormalizedIssues.length) {
        cachedNormalizedIssues = resolveNormalizedIssues(cachedTechnicalPayload);
    }

    const toolbar = document.getElementById("seoToolIssuesToolbar");
    if (toolbar) toolbar.hidden = false;

    issuesViewMode = "cards";
    const cardsView = document.getElementById("issuesCardsView");
    const tableWrap = document.getElementById("issuesTableWrap");
    if (cardsView) cardsView.hidden = false;
    if (tableWrap) tableWrap.hidden = true;

    renderNormalizedIssues(cachedNormalizedIssues);
}

function renderResultsHeader(payload) {
    const hdr = document.getElementById("seoToolResultsHeader");
    if (!hdr) return;
    if (!payload || !(payload.domain || payload.source_url)) {
        hdr.hidden = true;
        return;
    }
    hdr.hidden = false;
    const url =
        (payload.source_url || "").trim() ||
        (payload.domain ? "https://" + String(payload.domain).replace(/^https?:\/\//i, "") : "");
    const urlEl = document.getElementById("seoResultsHeaderUrl");
    if (urlEl) urlEl.textContent = url || "—";
    const ss = resolveSaasSummary(payload);
    const modeLabels = {
        crawl_only: "Chỉ quét website",
        hybrid_gsc: "Kết hợp Search Console",
        partial_gsc: "Search Console một phần",
    };
    const meta = [];
    if (payload.at) meta.push("Quét: " + String(payload.at).slice(0, 16).replace("T", " "));
    meta.push("Độ sâu: " + (payload.pages_scanned != null ? payload.pages_scanned : "—") + " trang");
    meta.push("Nguồn: " + (modeLabels[ss.scan_mode] || ss.scan_mode || "Crawl"));
    if (ss.technical_score != null) meta.push("Health: " + Math.round(Number(ss.technical_score)) + "/100");
    const metaEl = document.getElementById("seoResultsHeaderMeta");
    if (metaEl) metaEl.textContent = meta.join(" · ");
    const expBtn = document.getElementById("btnTechnicalExportHeader");
    if (expBtn) expBtn.disabled = !payload.audit_id;
}

function updateTechSidebarBadges(issues) {
    if (cachedTechnicalPayload) {
        updateTechSidebarFromPayload(cachedTechnicalPayload);
        return;
    }
    updateTechSidebarFromPayload(
        issues && issues.length ? { issues: issues, category_summaries: [] } : null
    );
}

function passedCheckLabel(chk) {
    const id = String(chk.id || "").toLowerCase();
    if (PASSED_CHECK_DISPLAY[id]) return PASSED_CHECK_DISPLAY[id];
    if (chk.title) return String(chk.title);
    return id.replace(/_/g, " ");
}

let passedChecksToggleWired = false;
function wirePassedChecksToggleOnce() {
    if (passedChecksToggleWired) return;
    passedChecksToggleWired = true;
    const btn = document.getElementById("seoToolPassedChecksToggle");
    const body = document.getElementById("seoToolPassedChecksBody");
    if (!btn || !body) return;
    btn.addEventListener("click", () => {
        const open = body.hidden;
        body.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        btn.classList.toggle("is-open", open);
    });
}

function renderPassedChecks(payload) {
    wirePassedChecksToggleOnce();
    const sec = document.getElementById("seoToolPassedChecksSection");
    const list = document.getElementById("seoToolPassedChecksList");
    const countEl = document.getElementById("seoToolPassedChecksCount");
    if (!sec || !list) return;
    const checks = Array.isArray(payload && payload.passed_checks) ? payload.passed_checks : [];
    if (!checks.length) {
        sec.hidden = true;
        list.textContent = "";
        return;
    }
    sec.hidden = false;
    if (countEl) countEl.textContent = String(checks.length);
    list.textContent = "";
    checks.forEach((chk) => {
        if (!chk || typeof chk !== "object") return;
        const li = document.createElement("li");
        li.className = "seo-tool-passed-item";
        const title = document.createElement("strong");
        title.className = "seo-tool-passed-item-title";
        title.textContent = passedCheckLabel(chk);
        const meta = document.createElement("span");
        meta.className = "seo-tool-passed-item-meta";
        const cat = chk.category ? String(chk.category).replace(/_/g, " ") : "";
        meta.textContent = cat ? cat + (chk.source ? " · " + chk.source : "") : chk.source || "";
        const desc = document.createElement("p");
        desc.className = "seo-tool-passed-item-desc";
        desc.textContent = chk.description || "";
        li.appendChild(title);
        if (meta.textContent) li.appendChild(meta);
        if (desc.textContent) li.appendChild(desc);
        list.appendChild(li);
    });
}

function hidePassedChecksSection() {
    const sec = document.getElementById("seoToolPassedChecksSection");
    if (sec) sec.hidden = true;
    const bar = document.getElementById("techCategoryChipsBar");
    if (bar) bar.hidden = true;
}

const TECH_CHIP_NAV_ORDER = (window.TechSidebarV2 && window.TechSidebarV2.NAV_ORDER) || [
    "overview",
    "priority",
    "index_crawl",
    "onpage",
    "perf_security",
    "gsc",
];

function syncCategoryChipsBar(payload, stats) {
    const bar = document.getElementById("techCategoryChipsBar");
    if (bar) bar.hidden = true;
    const scroll = document.getElementById("techCategoryChipsScroll");
    if (scroll) scroll.textContent = "";
}

let passedFilterExpandWired = false;
function wirePassedFilterExpandOnce() {
    if (passedFilterExpandWired) return;
    passedFilterExpandWired = true;
    const filters = document.getElementById("seoToolIssuesFilters");
    if (!filters) return;
    filters.addEventListener("click", (ev) => {
        const btn = ev.target.closest('[data-tech-filter="passed"]');
        if (!btn) return;
        setTimeout(() => {
            if (technicalIssueFilter !== "passed") return;
            const body = document.getElementById("seoToolPassedChecksBody");
            const toggle = document.getElementById("seoToolPassedChecksToggle");
            const sec = document.getElementById("seoToolPassedChecksSection");
            if (body && toggle && sec && !sec.hidden) {
                body.hidden = false;
                toggle.setAttribute("aria-expanded", "true");
                toggle.classList.add("is-open");
                try {
                    sec.scrollIntoView({ behavior: "smooth", block: "nearest" });
                } catch (_e) {
                    sec.scrollIntoView();
                }
            }
        }, 0);
    });
}

const TECH_SIDEBAR_TAB_LS = "tool_technical_sidebar_tab";

function readTechSidebarTab() {
    try {
        let v = localStorage.getItem(TECH_SIDEBAR_TAB_LS);
        if (v && TECH_NAV_LEGACY_KEYS[v]) {
            v = TECH_NAV_LEGACY_KEYS[v];
            try {
                localStorage.setItem(TECH_SIDEBAR_TAB_LS, v);
            } catch (_e2) {}
        }
        const allowed = new Set(
            (window.TechSidebarV2 && window.TechSidebarV2.NAV_ORDER) || [
                "overview",
                "priority",
                "indexability",
                "crawlability",
                "onpage",
                "internal_links",
                "performance",
                "structured_data",
                "security_http",
                "ux_mobile",
                "gsc",
                "history",
            ]
        );
        if (v && allowed.has(v)) return v;
    } catch (_e) {}
    return "overview";
}

function persistTechSidebarTab(which) {
    try {
        if (which) localStorage.setItem(TECH_SIDEBAR_TAB_LS, String(which));
    } catch (_e) {}
}

function setTechNavActive(which) {
    const w = normalizeTechTabKey(which || "overview");
    persistTechSidebarTab(w);
    document.querySelectorAll("[data-tech-nav]").forEach((b) => {
        b.classList.toggle("is-active", b.getAttribute("data-tech-nav") === w);
    });
    syncMobileNavSelect();
}

function restoreTechSidebarTab() {
    activeTechTab = normalizeTechTabKey(readTechSidebarTab());
    syncIssuesTableFilterBucket();
    setTechNavActive(activeTechTab);
    renderTechTabContent();
}

function scrollToTechPanel(el) {
    if (!el) return;
    try {
        el.scrollIntoView({ behavior: "instant", block: "start" });
    } catch (_e) {
        try {
            el.scrollIntoView({ behavior: "auto", block: "start" });
        } catch (_e2) {
            el.scrollIntoView();
        }
    }
}

function renderTechnicalHealthSummary(summary) {
    const row = document.getElementById("technicalHealthRow");
    const valEl = document.getElementById("healthScoreValue");
    const metaEl = document.getElementById("healthScoreMeta");
    if (!row || !valEl || !metaEl) return;
    const s = summary || {};
    const raw = s.health_score;
    if (raw == null || raw === "") {
        row.hidden = true;
        valEl.textContent = "—";
        metaEl.textContent = "";
        return;
    }
    const num = Number(raw);
    if (Number.isNaN(num)) {
        row.hidden = true;
        return;
    }
    row.hidden = false;
    valEl.textContent = String(num);
    const parts = [];
    if (s.weighted_penalty != null && s.weighted_penalty !== "") {
        const p = Number(s.weighted_penalty);
        if (!Number.isNaN(p)) parts.push("Penalty tổng hợp: " + p.toFixed(2));
    }
    const by = s.issues_by_severity;
    if (by && typeof by === "object") {
        const hi = by.high != null ? by.high : 0;
        const med = by.medium != null ? by.medium : 0;
        const lo = by.low != null ? by.low : 0;
        parts.push("Số issue: cao " + hi + " · trung bình " + med + " · thấp " + lo);
    }
    metaEl.textContent = parts.join(" · ");
}
function renderIssuesTable(issues) {
    cachedTechnicalIssues = Array.isArray(issues) ? issues.slice() : [];
    updateTechSidebarBadges(cachedTechnicalIssues);
    renderTechTabContent();
}

function renderIssuesTableRows(list) {
    // The current UI renders issue cards; the legacy table is no longer in seo_tool.html.
    if (!issuesTbody) return;
    issuesTbody.textContent = "";
    const rows = Array.isArray(list) ? list : [];
    if (rows.length === 0) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 8;
        td.className = "cell-muted";
        td.textContent = "Không phát hiện lỗi technical.";
        tr.appendChild(td);
        issuesTbody.appendChild(tr);
        return;
    }
    for (const item of rows) {
        const group = normalizeGroup(item.checklist_group || item.group || item.category);
        const bucket = issueSidebarBucket(item);
        const suggested =
            item.suggested_fix != null && String(item.suggested_fix).trim()
                ? String(item.suggested_fix).trim()
                : "";
        const rem = item.remediation != null && String(item.remediation).trim()
            ? String(item.remediation).trim()
            : "";
        const sol =
            suggested ||
            rem ||
            (GROUP_SOLUTIONS_VI[group] || GROUP_SOLUTIONS_VI.General);
        const sev = String(item.severity || "low").toLowerCase();
        const sevVi = SEVERITY_LABEL_VI[sev] || sev;
        const type = item.type || "issue";
        const message = item.message || "";
        const url = item.url || "";

        const tr = document.createElement("tr");
        tr.setAttribute("data-bucket", bucket);
        const th0 = document.createElement("th");
        th0.scope = "row";
        th0.className = "col-tool-checklist-cell";
        const typeRow = document.createElement("div");
        typeRow.className = "issue-type-row";
        const iconSpan = document.createElement("span");
        iconSpan.className = "issue-illus";
        iconSpan.innerHTML = issueIllusSvg(type);
        iconSpan.title = type;
        const lab = document.createElement("div");
        lab.className = "issue-type-label";
        const keyLine = document.createElement("div");
        keyLine.className = "issue-type-key";
        keyLine.textContent = type;
        lab.appendChild(keyLine);
        const viLine = document.createElement("div");
        viLine.className = "issue-type-vi";
        const viText = CHECKLIST_TITLE_VI[type] || "";
        viLine.textContent = viText || "—";
        lab.appendChild(viLine);
        typeRow.appendChild(iconSpan);
        typeRow.appendChild(lab);
        th0.appendChild(typeRow);
        tr.appendChild(th0);

        const tdDg = document.createElement("td");
        const badge = document.createElement("span");
        badge.className = "badge " + severityClass(item.severity);
        badge.textContent = sevVi.toUpperCase();
        tdDg.appendChild(badge);
        if (item.gsc_badge) {
            tdDg.appendChild(document.createElement("br"));
            const gscB = document.createElement("span");
            gscB.className = gscBadgeClass(item.gsc_badge);
            gscB.textContent = GSC_BADGE_LABELS[item.gsc_badge] || item.gsc_badge;
            tdDg.appendChild(gscB);
        }
        if (item.priority_score != null) {
            tdDg.appendChild(document.createElement("br"));
            const ps = document.createElement("span");
            ps.className = "cell-muted";
            ps.textContent = "Ưu tiên: " + item.priority_score;
            tdDg.appendChild(ps);
        }
        tdDg.appendChild(document.createElement("br"));
        const gspan = document.createElement("span");
        gspan.className = "cell-muted";
        gspan.textContent = group;
        tdDg.appendChild(gspan);

        const tdDc = document.createElement("td");
        if (message) {
            const p1 = document.createElement("div");
            p1.textContent = message;
            tdDc.appendChild(p1);
        }
        if (url) {
            if (message) tdDc.appendChild(document.createElement("br"));
            const a = document.createElement("a");
            a.href = url;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.textContent = url;
            tdDc.appendChild(a);
        }
        if (!message && !url) {
            const sp = document.createElement("span");
            sp.className = "cell-muted";
            sp.textContent = "—";
            tdDc.appendChild(sp);
        }
        appendGscMetricsBlock(tdDc, item);

        const tdSol = document.createElement("td");
        tdSol.className = ["col-tool-solution-cell", suggested || rem ? "cell-pre" : ""].filter(Boolean).join(" ");
        const solInner = document.createElement("div");
        solInner.className = "tool-solution-inner";
        solInner.textContent = sol;
        tdSol.appendChild(solInner);

        const tdRef = document.createElement("td");
        tdRef.className = "col-tool-ref-cell";
        tdRef.innerHTML = refLinkCell(group);

        const tdHt = document.createElement("td");
        tdHt.textContent = "Quét tự động — " + sevVi;

        const tdTri = document.createElement("td");
        tdTri.innerHTML = '<span class="cell-muted">—</span>';

        const tdNote = document.createElement("td");
        const expl =
            item.explanation != null && String(item.explanation).trim()
                ? String(item.explanation).trim()
                : "";
        const confRaw = item.confidence;
        const confNum = confRaw != null && confRaw !== "" ? Number(confRaw) : null;
        const confOk = confNum != null && !Number.isNaN(confNum);
        const pt = item.page_type != null && String(item.page_type).trim()
            ? String(item.page_type).trim()
            : "";
        if (expl || confOk || pt) {
            tdNote.className = "cell-pre";
            const bits = [];
            if (pt) bits.push("Loại trang: " + pt);
            if (expl) bits.push(expl);
            if (confOk) bits.push("Độ tin cậy rule: " + Math.round(confNum * 1000) / 1000);
            tdNote.textContent = bits.join("\n");
        } else {
            tdNote.innerHTML = '<span class="cell-muted">—</span>';
        }

        tr.appendChild(tdDg);
        tr.appendChild(tdDc);
        tr.appendChild(tdSol);
        tr.appendChild(tdRef);
        tr.appendChild(tdHt);
        tr.appendChild(tdTri);
        tr.appendChild(tdNote);
        issuesTbody.appendChild(tr);
    }
}

function wireTechSidebarNav() {
    const nav = document.getElementById("techSidebarNav");
    if (!nav || nav.dataset.wired === "1") return;
    nav.dataset.wired = "1";
    populateMobileNavSelect();
    nav.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-tech-nav]");
        if (!btn) return;
        const id = btn.getAttribute("data-tech-nav");
        if (!cachedTechnicalPayload && id !== "history") {
            setMsg("Chạy quét hoặc chọn domain trong Lịch sử Audit để xem lỗi.", "");
            scrollToTechPanel(document.getElementById("url"));
            return;
        }
        if (!cachedTechnicalPayload && id === "history") {
            navigateTechTab("history");
            return;
        }
        revealToolResultsPanel();
        navigateTechTab(id);
    });
}
const btnExportCsv = document.getElementById("btnExportCsv");
const btnExportGsheet = document.getElementById("btnExportGsheet");
const authMsg = document.getElementById("authMsg");
const authModal = document.getElementById("authModal");
const btnOpenLogin = document.getElementById("btnOpenLogin");
const btnGoogleLogin = document.getElementById("btnGoogleLogin");
const btnCloseModal = document.getElementById("btnCloseModal");
const authEmail = document.getElementById("authEmail");
const authPassword = document.getElementById("authPassword");
const authLoginHint = document.getElementById("authLoginHint");
const authPanelLogin = document.getElementById("authPanelLogin");
        const authPanelRegister = document.getElementById("authPanelRegister");
        const authTabLogin = document.getElementById("authTabLogin");
        const authTabRegister = document.getElementById("authTabRegister");
        const regEmail = document.getElementById("regEmail");
        const regOtp = document.getElementById("regOtp");
        const regPassword = document.getElementById("regPassword");
        const btnRegOtpSend = document.getElementById("btnRegOtpSend");
        const btnSubmitRegister = document.getElementById("btnSubmitRegister");
        const linkGoRegister = document.getElementById("linkGoRegister");
        const linkGoLogin = document.getElementById("linkGoLogin");
        const btnToggleRegPw = document.getElementById("btnToggleRegPw");

        function setAuthTab(tab) {
            const isLogin = tab === "login";
        if (authTabLogin) {
            authTabLogin.classList.toggle("active", isLogin);
            authTabLogin.setAttribute("aria-selected", isLogin ? "true" : "false");
        }
        if (authTabRegister) {
            authTabRegister.classList.toggle("active", !isLogin);
            authTabRegister.setAttribute("aria-selected", !isLogin ? "true" : "false");
        }
        if (authPanelLogin) authPanelLogin.hidden = !isLogin;
        if (authPanelRegister) authPanelRegister.hidden = isLogin;
        setModalAuthMsg("", "");
    }

        function fillLoginFromRegister(email, password) {
        if (authEmail) authEmail.value = email;
        if (authPassword) authPassword.value = password;
        updatePwRuleEls();
    }

        function updateRegPwRuleEls() {
        if (!regPassword) return false;
            const v = regPassword.value;
            const len = v.length >= 8;
            const up = /[A-Z]/.test(v);
            const low = /[a-z]/.test(v);
            const num = /[0-9]/.test(v);
            const set = (id, ok) => { const el = document.getElementById(id); if (el) el.className = ok ? "ok" : ""; };
        set("reg-rule-len", len); set("reg-rule-up", up); set("reg-rule-low", low); set("reg-rule-num", num);
        return len && up && low && num;
    }

        if (regPassword) regPassword.addEventListener("input", updateRegPwRuleEls);
    if (btnToggleRegPw && regPassword) {
        btnToggleRegPw.addEventListener("click", function () {
                const isPw = regPassword.type === "password";
            regPassword.type = isPw ? "text" : "password";
            btnToggleRegPw.textContent = isPw ? "🙈" : "👁";
        });
    }

        document.querySelectorAll("[data-auth-tab]").forEach((btn) => {
        btn.addEventListener("click", () => setAuthTab(btn.getAttribute("data-auth-tab") || "login"));
    });
        if (linkGoRegister) linkGoRegister.addEventListener("click", () => setAuthTab("register"));
    if (linkGoLogin) linkGoLogin.addEventListener("click", () => setAuthTab("login"));

        let otpSendInFlight = false;
        let otpCooldownTimer = null;

        function setOtpSendEnabled(enabled, label) {
            if (!btnRegOtpSend) return;
            btnRegOtpSend.disabled = !enabled;
            if (label != null) btnRegOtpSend.textContent = label;
        }

        function startOtpCooldown(seconds) {
            let left = Math.max(1, Number(seconds) || 60);
            if (otpCooldownTimer) clearInterval(otpCooldownTimer);
            setOtpSendEnabled(false, "Gửi lại sau " + left + "s");
            otpCooldownTimer = setInterval(function () {
                left -= 1;
                if (left <= 0) {
                    clearInterval(otpCooldownTimer);
                    otpCooldownTimer = null;
                    setOtpSendEnabled(true, "Nhận mã OTP (gửi về Gmail)");
                    return;
                }
                setOtpSendEnabled(false, "Gửi lại sau " + left + "s");
            }, 1000);
        }

        async function sendRegOtp() {
            if (otpSendInFlight || (btnRegOtpSend && btnRegOtpSend.disabled)) return;
            const email = (regEmail && regEmail.value || "").trim().toLowerCase();
            if (!email) { setModalAuthMsg("Nhập Gmail trước.", "error"); return; }
            if (!email.endsWith("@gmail.com") && !email.endsWith("@googlemail.com")) {
                setModalAuthMsg("Chỉ gửi OTP cho Gmail.", "error"); return;
            }
            otpSendInFlight = true;
            setOtpSendEnabled(false, "Đang gửi...");
            try {
                setModalAuthMsg("Đang gửi mã OTP...", "");
                const r = await fetch("/auth/otp/send", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email: email }),
                });
                const d = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(apiDetail(d));
                setModalAuthMsg(
                    (d.message || "Đã gửi OTP.") + " Kiểm tra hộp thư đến và Spam/Promotions; dùng mã trong email mới nhất.",
                    "ok"
                );
                startOtpCooldown(60);
            } catch (e) {
                setModalAuthMsg(String(e.message || e), "error");
                setOtpSendEnabled(true, "Nhận mã OTP (gửi về Gmail)");
            } finally {
                otpSendInFlight = false;
            }
        }

        async function doRegister() {
            const email = (regEmail && regEmail.value || "").trim().toLowerCase();
            const password = regPassword ? regPassword.value : "";
            const otp = (regOtp && regOtp.value || "").trim().replace(/\s/g, "");
        if (!email || !password || !otp) {
            setModalAuthMsg("Nhập đủ Gmail, OTP và mật khẩu.", "error");
            return;
        }
        if (!email.endsWith("@gmail.com") && !email.endsWith("@googlemail.com")) {
            setModalAuthMsg("Chỉ đăng ký bằng Gmail (@gmail.com).", "error");
            return;
        }
        if (!updateRegPwRuleEls()) {
            setModalAuthMsg("Mật khẩu chưa đủ tiêu chí.", "error");
            return;
        }
        try {
            setModalAuthMsg("Đang đăng ký...", "");
                const r = await fetch("/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: email, password: password, otp: otp }),
            });
                const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(apiDetail(d));
            fillLoginFromRegister(email, password);
            setAuthTab("login");
            setModalAuthMsg(
                (d.message || "Đăng ký thành công.") + " Đã điền sẵn email và mật khẩu — bấm Đăng nhập.",
                "ok"
            );
        } catch (e) {
            setModalAuthMsg(String(e.message || e), "error");
        }
    }

if (btnRegOtpSend) btnRegOtpSend.addEventListener("click", sendRegOtp);
if (btnSubmitRegister) btnSubmitRegister.addEventListener("click", doRegister);
const btnTogglePw = document.getElementById("btnTogglePw");
const btnSubmitAuth = document.getElementById("btnSubmitAuth");
const btnLogout = document.getElementById("btnLogout");
const authBoxTop = document.getElementById("authBoxTop");
const btnGoogleApisConnect = document.getElementById("btnGoogleApisConnect");
const btnGoogleApisDisconnect = document.getElementById("btnGoogleApisDisconnect");
const googleLinkStatus = document.getElementById("googleLinkStatus");
if (typeof window.DigiSeoSyncTokenFromCookie === "function") {
    window.DigiSeoSyncTokenFromCookie();
}
let token = typeof window.DigiSeoGetAuthToken === "function"
    ? (window.DigiSeoGetAuthToken() || "")
    : (sessionStorage.getItem("seo_token") || "");

function httpErrorFromResponse(r, d) {
    const st = r && r.status != null ? Number(r.status) : 0;
    if (st === 504) {
        return (
            "Gateway timeout (504) — quét technical mất quá lâu. " +
            "Thử lại sau vài phút; nếu vẫn lỗi: tắt Search Console trong tuỳ chọn nâng cao hoặc dùng site nhỏ hơn."
        );
    }
    if (st === 502 || st === 503) {
        return "Hệ thống tạm không phản hồi. Thử lại sau vài phút.";
    }
    if (st === 404) {
        return "Không tìm thấy API quét. Thử tải lại trang (Ctrl+F5). Nếu vẫn lỗi, báo quản trị restart seoauto-web.";
    }
    if (st === 408) {
        return "Hết thời gian chờ phía máy chủ (408). Site có thể quá chậm — thử lại hoặc giảm phạm vi quét.";
    }
    return apiDetail(d);
}

function apiDetail(d) {
    if (d == null || typeof d !== "object") return "Lỗi không xác định";
    if (typeof d.detail === "string") return d.detail;
    if (Array.isArray(d.detail)) {
        const parts = d.detail.map((e) => {
            if (typeof e === "string") return e;
            if (e && typeof e === "object") return e.msg || e.message || "";
            return String(e);
        });
        const s = parts.filter(Boolean).join("; ");
        return s || "Dữ liệu gửi lên không hợp lệ.";
    }
    if (typeof d.message === "string" && d.message.trim()) return d.message.trim();
    if (d.detail != null && typeof d.detail === "object" && !Array.isArray(d.detail)) {
        const x = d.detail;
        if (typeof x.msg === "string" && x.msg) return x.msg;
        if (typeof x.message === "string" && x.message) return x.message;
    }
    if (Object.keys(d).length === 0) {
        return "Máy chủ không gửi mô tả lỗi. Kiểm tra kết nối hoặc thử lại sau.";
    }
    try {
        const s = JSON.stringify(d);
        return s.length > 400 ? s.slice(0, 400) + "…" : s;
    } catch {
        return "Lỗi không xác định";
    }
}

