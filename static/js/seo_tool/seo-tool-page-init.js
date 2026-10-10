/** SEO Tool page — Auth, GSC, events, startup */
function setMsg(text, cls) {
    msg.textContent = text;
    msg.className = cls || "";
}

/** Timeout fetch trình duyệt — audit có Playwright + kiểm tra link nội bộ có thể > 3 phút. */
const TECH_ANALYZE_CLIENT_TIMEOUT_MS = 15 * 60 * 1000;
let _techProgressTimer = null;
let _techScanIdempotencyKey = null;
let _techScanIdempotencyUrl = null;

function technicalScanIdempotencyKey(url) {
    const u = String(url || "").trim().toLowerCase();
    if (_techScanIdempotencyUrl !== u || !_techScanIdempotencyKey) {
        _techScanIdempotencyUrl = u;
        const rand =
            typeof crypto !== "undefined" && crypto.randomUUID
                ? crypto.randomUUID()
                : String(Date.now()) + Math.random().toString(36).slice(2);
        _techScanIdempotencyKey = "ts_" + String(rand).replace(/-/g, "").slice(0, 24);
    }
    return _techScanIdempotencyKey;
}

function resetTechnicalScanIdempotency() {
    _techScanIdempotencyKey = null;
    _techScanIdempotencyUrl = null;
}

function applyTechnicalJobProgress(job) {
    const pct = job && job.progress != null ? Number(job.progress) : 0;
    const message = (job && job.message) || "Đang quét technical…";
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.setScanJobProgress === "function") {
        window.TechDashboardV2.setScanJobProgress(pct, message);
        return;
    }
    const bar = document.getElementById("technicalScanProgressBar");
    const label = document.getElementById("technicalScanProgressLabel");
    if (bar) bar.style.width = Math.max(2, Math.min(96, pct)) + "%";
    if (label) label.textContent = message;
}

async function pollTechnicalScanJob(jobId, token, signal) {
    const url = "/analyze/technical/jobs/" + encodeURIComponent(jobId);
    while (!signal.aborted) {
        const r = await fetch(url, {
            headers: { Authorization: "Bearer " + token },
            signal: signal,
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(httpErrorFromResponse(r, d));
        applyTechnicalJobProgress(d);
        const st = String(d.state || "").toUpperCase();
        if (st === "SUCCESS" && d.result) return d.result;
        if (st === "ERROR") throw new Error(d.error || "Quét technical thất bại.");
        await new Promise(function (resolve) {
            const t = setTimeout(resolve, 3000);
            if (signal) {
                signal.addEventListener(
                    "abort",
                    function () {
                        clearTimeout(t);
                        resolve();
                    },
                    { once: true }
                );
            }
        });
    }
    const abortErr = new Error("Aborted");
    abortErr.name = "AbortError";
    throw abortErr;
}

function showTechnicalScanProgress() {
    window.__seoScanStartedAt = Date.now();
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.showScanProgress === "function") {
        window.TechDashboardV2.showScanProgress();
        if (window.TechDashboardV2.hideScanError) window.TechDashboardV2.hideScanError();
        return;
    }
    const wrap = document.getElementById("technicalScanProgressWrap");
    const bar = document.getElementById("technicalScanProgressBar");
    const label = document.getElementById("technicalScanProgressLabel");
    if (!wrap || !bar) return;
    wrap.hidden = false;
    bar.style.width = "0%";
    const t0 = Date.now();
    if (_techProgressTimer) clearInterval(_techProgressTimer);
    const tick = () => {
        const elapsed = Date.now() - t0;
        const t = TECH_ANALYZE_CLIENT_TIMEOUT_MS;
        const k = 3.2;
        const pct = Math.min(96, (1 - Math.exp((-k * elapsed) / t)) * 100);
        bar.style.width = pct.toFixed(2) + "%";
        if (label) {
            const sec = Math.floor(elapsed / 1000);
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            label.textContent =
                "Đã chạy " +
                m +
                " phút " +
                s +
                " giây — crawl + kiểm tra liên kết nội bộ đang xử lý phía máy chủ…";
        }
    };
    tick();
    _techProgressTimer = setInterval(tick, 450);
}

function hideTechnicalScanProgress(completedOk) {
    if (window.TechDashboardV2 && typeof window.TechDashboardV2.hideScanProgress === "function") {
        window.TechDashboardV2.hideScanProgress(completedOk);
        return;
    }
    if (_techProgressTimer) {
        clearInterval(_techProgressTimer);
        _techProgressTimer = null;
    }
    const wrap = document.getElementById("technicalScanProgressWrap");
    const bar = document.getElementById("technicalScanProgressBar");
    const label = document.getElementById("technicalScanProgressLabel");
    if (!wrap || !bar) return;
    if (completedOk) {
        bar.style.width = "100%";
        if (label) label.textContent = "Hoàn tất — đang hiển thị kết quả…";
        setTimeout(() => {
            wrap.hidden = true;
            bar.style.width = "0%";
            if (label) label.textContent = "";
        }, 450);
    } else {
        wrap.hidden = true;
        bar.style.width = "0%";
        if (label) label.textContent = "";
    }
}
function setAuthMsg(text, cls) {
    authMsg.textContent = text;
    authMsg.className = "auth-status " + (cls || "");
}
function setModalAuthMsg(text, cls) {
    const el = document.getElementById("modalAuthMsg");
    el.textContent = text;
    el.className = "modal-auth-msg " + (cls || "");
}
function updatePwRuleEls() {
    const v = authPassword.value;
    const len = v.length >= 8;
    const up = /[A-Z]/.test(v);
    const low = /[a-z]/.test(v);
    const num = /[0-9]/.test(v);
    const setRule = (id, ok) => { const el = document.getElementById(id); if (el) el.className = ok ? "ok" : ""; };
    setRule("rule-len", len); setRule("rule-up", up); setRule("rule-low", low); setRule("rule-num", num);
    setRule("reg-rule-len", len); setRule("reg-rule-up", up); setRule("reg-rule-low", low); setRule("reg-rule-num", num);
    return len && up && low && num;
}

authPassword.addEventListener("input", updatePwRuleEls);

btnTogglePw.addEventListener("click", () => {
    const isPw = authPassword.type === "password";
    authPassword.type = isPw ? "text" : "password";
    btnTogglePw.textContent = isPw ? "🙈" : "👁";
    btnTogglePw.setAttribute("aria-label", isPw ? "Ẩn mật khẩu" : "Hiện mật khẩu");
});

const projectSidebar = document.getElementById("projectSidebar");
const sidebarProjectList = document.getElementById("sidebarProjectList");
const sidebarRecentList = document.getElementById("sidebarRecentList");

function auditListTargets() {
    const out = [];
    if (sidebarRecentList) out.push(sidebarRecentList);
    const sidebarHistoryList = document.getElementById("sidebarHistoryList");
    if (sidebarHistoryList) out.push(sidebarHistoryList);
    if (sidebarProjectList) out.push(sidebarProjectList);
    return out;
}

function isCompactAuditUl(ul) {
    const sidebarHistoryList = document.getElementById("sidebarHistoryList");
    return ul === sidebarRecentList || ul === sidebarHistoryList;
}

function buildAuditListItem(it, compact) {
    const li = document.createElement("li");
    li.className = compact ? "tech-sidebar-recent-item" : "sb-item";
    li.setAttribute("data-audit-id", String(it.id || ""));
    li.addEventListener("click", (ev) => {
        const t = ev.target;
        if (t && (t.tagName === "BUTTON" || t.closest("button"))) return;
        if (it.id) openAuditRun(it.id);
    });
    const domainEl = document.createElement("div");
    domainEl.className = compact ? "tech-sidebar-recent-domain" : "sb-domain";
    domainEl.textContent = it.domain || it.source_url || "(unknown)";
    const meta = document.createElement("div");
    meta.className = compact ? "tech-sidebar-recent-meta" : "sb-meta";
    const ts = it.at || "";
    const pages = it.pages_scanned != null ? it.pages_scanned : "—";
    const ic = it.issue_count != null ? it.issue_count : 0;
    let scoreTxt = "";
    const hs = it.technical_summary && it.technical_summary.health_score;
    if (hs != null && hs !== "") scoreTxt = " · " + Math.round(Number(hs));
    meta.textContent =
        (ts ? ts.replace("T", " ").replace("+00:00", "").slice(0, 16) + " · " : "") +
        pages +
        " trang · " +
        ic +
        " lỗi" +
        scoreTxt;
    li.appendChild(domainEl);
    li.appendChild(meta);
    if (!compact) {
        const actions = document.createElement("div");
        actions.className = "sb-actions";
        const bCsv = document.createElement("button");
        bCsv.type = "button";
        bCsv.className = "sb-excel";
        bCsv.textContent = "Excel (CSV)";
        bCsv.addEventListener("click", () => downloadAuditExport(it.id, "csv"));
        const bGsheet = document.createElement("button");
        bGsheet.type = "button";
        bGsheet.className = "sb-excel";
        bGsheet.textContent = "Google Sheet";
        bGsheet.addEventListener("click", () => downloadAuditExport(it.id, "gsheet"));
        actions.appendChild(bCsv);
        actions.appendChild(bGsheet);
        const bDel = document.createElement("button");
        bDel.type = "button";
        bDel.className = "sb-del";
        bDel.textContent = "Xóa";
        bDel.addEventListener("click", () => deleteAuditRun(it.id));
        li.appendChild(actions);
        li.appendChild(bDel);
    }
    return li;
}
const sidebarMainEl = document.querySelector(".sidebar-main");
let lastMe = null;
let currentAuditId = null;
const AUDIT_LS_KEY_LEGACY = "technical_current_audit_id";

function auditStorageKey(userId) {
    const uid = userId != null && String(userId).trim() ? String(userId).trim() : "";
    return uid ? "seoauto:" + uid + ":technical_current_audit_id" : AUDIT_LS_KEY_LEGACY;
}

function gscSiteStorageKey() {
    const uid = lastMe && lastMe.id != null ? String(lastMe.id).trim() : "";
    return uid ? "seoauto:" + uid + ":gsc_selected_site_url" : "gsc_selected_site_url";
}

function refreshSidebarUser() {
    if (typeof window.refreshDigiSeoUserDock === "function") window.refreshDigiSeoUserDock();
}

function sidebarPlaceholderLoggedOut() {
    auditListTargets().forEach((ul) => {
        ul.innerHTML = "";
        const li = document.createElement("li");
        li.className = isCompactAuditUl(ul) ? "tech-sidebar-recent-empty" : "sb-empty";
        li.textContent = "Đăng nhập để xem lần quét gần đây.";
        ul.appendChild(li);
    });
    updateTechSidebarBadges(cachedTechnicalIssues);
}

function setActiveAuditInSidebar(auditId) {
    currentAuditId = auditId || null;
    try {
        const key = auditStorageKey(lastMe && lastMe.id);
        if (currentAuditId) localStorage.setItem(key, String(currentAuditId));
        else localStorage.removeItem(key);
        localStorage.removeItem(AUDIT_LS_KEY_LEGACY);
    } catch (_e) {}
    const items = document.querySelectorAll(".sb-item[data-audit-id], .tech-sidebar-recent-item[data-audit-id]");
    if (!items) return;
    items.forEach((el) => {
        const id = el.getAttribute("data-audit-id");
        if (!id) return;
        if (currentAuditId && String(id) === String(currentAuditId)) el.classList.add("is-active");
        else el.classList.remove("is-active");
    });
}

async function openAuditRun(auditId) {
    if (!token || !auditId) return;
    hideTechnicalCompleteBanner();
    if (issuesCard) issuesCard.hidden = true;
    if (issuesTbody) issuesTbody.textContent = "";
    const thRow = document.getElementById("technicalHealthRow");
    if (thRow) thRow.hidden = true;
    const crawlExtrasCard = document.getElementById("crawlExtrasCard");
    if (crawlExtrasCard) crawlExtrasCard.hidden = true;
    setMsg("Đang tải dự án đã quét…", "");
    setActiveAuditInSidebar(auditId);
    try {
        const r = await fetch("/api/audit/" + encodeURIComponent(auditId) + "?lite=1", {
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));

        // Fill URL input (so Export buttons and rerun feel consistent)
        if (d.start_url) urlInput.value = String(d.start_url);
        else if (d.domain) urlInput.value = "https://" + String(d.domain);

        applyTechnicalScanPayload(d);
        setMsg("Đã tải dự án từ sidebar.", "ok");
    } catch (e) {
        const ttp = document.getElementById("toolTablePanel");
        if (ttp) ttp.classList.remove("is-visible");
        setMsg("Không tải được dự án: " + String(e.message || e), "error");
    }
}

async function loadSidebarProjects() {
    if (!token) {
        sidebarPlaceholderLoggedOut();
        return;
    }
    try {
        const r = await fetch("/api/audit/mine?limit=8", {
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));
        const items = Array.isArray(d.items) ? d.items : [];
        if (sidebarProjectList) sidebarProjectList.innerHTML = "";
        if (sidebarRecentList) sidebarRecentList.innerHTML = "";
        const sidebarHistoryList = document.getElementById("sidebarHistoryList");
        if (sidebarHistoryList) sidebarHistoryList.innerHTML = "";
        if (items.length === 0) {
            auditListTargets().forEach((ul) => {
                const li = document.createElement("li");
                li.className = isCompactAuditUl(ul) ? "tech-sidebar-recent-empty" : "sb-empty";
                li.textContent = "Chưa có lần quét. Nhập URL và bấm «Kiểm tra Technical».";
                ul.appendChild(li);
            });
            updateTechSidebarBadges(cachedTechnicalIssues);
            return;
        }
        items.forEach((it, idx) => {
            if (sidebarRecentList && idx < 3) {
                sidebarRecentList.appendChild(buildAuditListItem(it, true));
            }
            if (sidebarHistoryList) {
                sidebarHistoryList.appendChild(buildAuditListItem(it, true));
            }
            if (sidebarProjectList) {
                sidebarProjectList.appendChild(buildAuditListItem(it, false));
            }
        });
        if (items.length > 3 && sidebarRecentList) {
            const more = document.createElement("li");
            more.className = "tech-sidebar-recent-more";
            more.textContent = "+" + (items.length - 3) + " audit khác — xem tab Lịch sử Audit";
            sidebarRecentList.appendChild(more);
        }
        updateTechSidebarBadges(cachedTechnicalIssues);
    } catch (e) {
        auditListTargets().forEach((ul) => {
            ul.innerHTML = "";
            const li = document.createElement("li");
            li.className = isCompactAuditUl(ul) ? "tech-sidebar-recent-empty" : "sb-empty";
            li.textContent = "Không tải được danh sách: " + String(e.message || e);
            ul.appendChild(li);
        });
        updateTechSidebarBadges(cachedTechnicalIssues);
    }
}

async function downloadAuditExport(auditId, ext) {
    if (!token || !auditId) return;
    try {
        const r = await fetch("/api/audit/" + encodeURIComponent(auditId) + "/export." + ext, {
            headers: { Authorization: "Bearer " + token },
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            throw new Error(apiDetail(err));
        }
        const blob = await r.blob();
        const dispo = r.headers.get("Content-Disposition") || "";
        let fname = "technical-audit." + ext;
        const m = /filename="?([^";]+)"?/i.exec(dispo);
        if (m) fname = m[1].trim();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = fname;
        a.click();
        URL.revokeObjectURL(a.href);
    } catch (e) {
        setMsg(String(e.message || e), "error");
    }
}
window.downloadAuditExport = downloadAuditExport;
window.setMsg = setMsg;

async function deleteAuditRun(auditId) {
    if (!token || !auditId) return;
    if (!confirm("Xóa bản quét này khỏi danh sách?")) return;
    try {
        const r = await fetch("/api/audit/" + encodeURIComponent(auditId), {
            method: "DELETE",
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));
        await loadSidebarProjects();
        setMsg("Đã xóa bản quét.", "ok");
    } catch (e) {
        setMsg(String(e.message || e), "error");
    }
}

function clearGscPropertyUi() {
    const p = document.getElementById("gscPropertyPanel");
    const sel = document.getElementById("gscSiteSelect");
    const h = document.getElementById("gscPropertyHint");
    if (p) p.hidden = true;
    if (sel) sel.innerHTML = "";
    if (h) {
        h.textContent = "";
        h.hidden = true;
    }
}

async function loadGscSites() {
    const p = document.getElementById("gscPropertyPanel");
    const sel = document.getElementById("gscSiteSelect");
    const h = document.getElementById("gscPropertyHint");
    if (!token || !p || !sel || !h) return;
    try {
        const r = await fetch("/integrations/gsc/sites", {
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));
        const entries = Array.isArray(d.siteEntry) ? d.siteEntry : [];
        sel.innerHTML = "";
        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = entries.length ? "— Chọn property (siteUrl) —" : "— Không có property —";
        sel.appendChild(opt0);
        for (const e of entries) {
            const u = e.siteUrl || "";
            if (!u) continue;
            const o = document.createElement("option");
            o.value = u;
            o.textContent = u + (e.permissionLevel ? " (" + e.permissionLevel + ")" : "");
            sel.appendChild(o);
        }
        const saved = sessionStorage.getItem(gscSiteStorageKey()) || "";
        if (saved && [...sel.options].some((o) => o.value === saved)) {
            sel.value = saved;
        }
        p.hidden = entries.length === 0;
        h.textContent = "";
        h.hidden = true;
    } catch (e) {
        p.hidden = false;
        sel.innerHTML = "";
        const optE = document.createElement("option");
        optE.value = "";
        optE.textContent = "— Lỗi tải danh sách —";
        sel.appendChild(optE);
        h.textContent = "Không tải được danh sách. Bấm «Tải lại danh sách».";
        h.hidden = false;
    }
}

async function refreshGoogleIntegrationStatus() {
    const glsBase = "auth-status google-inline-status";
    googleLinkStatus.textContent = "";
    googleLinkStatus.className = glsBase;
    clearGscPropertyUi();
    if (!token) {
        btnGoogleApisConnect.disabled = true;
        btnGoogleApisDisconnect.disabled = true;
        googleLinkStatus.textContent = "Đăng nhập để kết nối Google.";
        syncGscAuditOptionsUi(false);
        return;
    }
    try {
        const r = await fetch("/integrations/google/status", {
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));
        btnGoogleApisConnect.disabled = !d.configured;
        btnGoogleApisDisconnect.disabled = !d.connected;
        if (!d.configured) {
            googleLinkStatus.textContent = "Chưa bật đăng nhập Google. Liên hệ quản trị.";
            googleLinkStatus.className = glsBase + " error";
            syncGscAuditOptionsUi(false);
        } else if (d.connected) {
            googleLinkStatus.textContent = "Đã kết nối Google.";
            googleLinkStatus.className = glsBase + " ok";
            syncGscAuditOptionsUi(true);
            await loadGscSites();
        } else {
            googleLinkStatus.textContent = "Chưa kết nối — bấm «Kết nối Google».";
            googleLinkStatus.className = glsBase;
            syncGscAuditOptionsUi(false);
        }
    } catch (e) {
        googleLinkStatus.textContent = "Không đọc được trạng thái Google: " + String(e.message || e);
        googleLinkStatus.className = glsBase + " error";
        btnGoogleApisConnect.disabled = true;
        btnGoogleApisDisconnect.disabled = true;
    }
}

function dispatchAuthChange() {
    try {
        window.dispatchEvent(
            new CustomEvent("digiseo-auth-change", { detail: { loggedIn: !!token } }),
        );
    } catch (_) {}
    if (typeof window.refreshDigiSeoNavAuth === "function") window.refreshDigiSeoNavAuth();
    if (typeof window.refreshDigiSeoUserDock === "function") window.refreshDigiSeoUserDock();
}

function applyAuthState() {
    const loggedIn = !!token;
    document.body.classList.toggle("is-logged-in", loggedIn);
    btn.disabled = !loggedIn;
    btnExportCsv.disabled = !loggedIn;
    btnExportGsheet.disabled = !loggedIn;
    urlInput.disabled = !loggedIn;
    if (btnGoogleLogin) btnGoogleLogin.disabled = loggedIn;
    authModal.hidden = true;
    if (btnOpenLogin) {
        btnOpenLogin.hidden = loggedIn;
        btnOpenLogin.disabled = false;
    }
    if (btnLogout) {
        btnLogout.hidden = true;
    }
    if (authBoxTop) authBoxTop.hidden = loggedIn;
    setAuthMsg(loggedIn ? "" : "");
    dispatchAuthChange();
    if (loggedIn) {
        loadSidebarProjects().then(function () {
            try {
                var savedId = localStorage.getItem(auditStorageKey(lastMe && lastMe.id));
                if (!savedId) savedId = localStorage.getItem(AUDIT_LS_KEY_LEGACY);
                if (savedId && !currentAuditId) openAuditRun(savedId);
            } catch (_e) {}
        });
    } else {
        sidebarPlaceholderLoggedOut();
        hideTechnicalCompleteBanner();
        lastTechnicalAuditId = null;
        const btnExL = document.getElementById("btnTechnicalDownloadExcel");
        if (btnExL) btnExL.disabled = true;
        delete btnExportCsv.dataset.auditExportId;
        delete btnExportGsheet.dataset.auditExportId;
    }
    refreshGoogleIntegrationStatus();
    refreshSidebarUser();
}

function severityClass(sev) {
    const s = String(sev || "").toLowerCase();
    if (s === "critical") return "sev-critical";
    if (s === "high") return "sev-high";
    if (s === "medium") return "sev-medium";
    if (s === "passed") return "sev-passed";
    return "sev-low";
}

btn.addEventListener("click", async () => {
    const url = document.getElementById("url").value.trim();
    if (issuesCard) issuesCard.hidden = true;
    if (issuesTbody) issuesTbody.textContent = "";
    const thRow = document.getElementById("technicalHealthRow");
    if (thRow) thRow.hidden = true;

    if (!url) {
        setMsg("Vui lòng nhập URL.", "error");
        return;
    }

    if (window.DigiSeoConfirmCredit && window.DigiSeoCreditActions) {
        const ok = await window.DigiSeoConfirmCredit(window.DigiSeoCreditActions.technicalAudit);
        if (!ok) return;
    }

    // Keep session alive: access JWT expires ~20m; refresh via HttpOnly cookie before scan.
    if (typeof window.DigiSeoEnsureFreshAuthToken === "function") {
        try {
            const fresh = await window.DigiSeoEnsureFreshAuthToken(false);
            if (fresh) token = fresh;
        } catch (_e) {}
    }
    if (!token) {
        setMsg("Phiên đăng nhập hết hạn. Bấm Đăng nhập ở góc trên rồi quét lại.", "error");
        if (typeof window.DigiSeoOpenLoginModal === "function") window.DigiSeoOpenLoginModal();
        return;
    }

    hideTechnicalCompleteBanner();
    hidePassedChecksSection();
    lastTechnicalAuditId = null;
    const btnExStart = document.getElementById("btnTechnicalDownloadExcel");
    if (btnExStart) btnExStart.disabled = true;
    delete btnExportCsv.dataset.auditExportId;
    delete btnExportGsheet.dataset.auditExportId;

    const crawlExtrasCard = document.getElementById("crawlExtrasCard");
    if (crawlExtrasCard) crawlExtrasCard.hidden = true;

    const ttp0 = document.getElementById("toolTablePanel");
    if (ttp0) ttp0.classList.remove("is-visible");
    cachedTechnicalIssues = [];
    cachedNormalizedIssues = [];
    cachedIssuesById = {};
    cachedTechnicalPayload = null;
    activeTechTab = "overview";
    issuesTableFilterBucket = null;
    fixedIssueIds.clear();
    technicalIssueFilter = "all";
    technicalIssueSearchQuery = "";
    const issuesSearchReset = document.getElementById("seoToolIssuesSearch");
    if (issuesSearchReset) issuesSearchReset.value = "";
    const issuesCardsReset = document.getElementById("issuesCardsView");
    if (issuesCardsReset) issuesCardsReset.textContent = "";
    setTechNavActive("overview");
    updateTechSidebarBadges([]);

    setMsg(
        "Đang kiểm tra technical… Crawl chạy nền (không bị Gateway 504). Thường 1–6 phút tùy site; tối đa ~15 phút.",
        "",
    );
    showTechnicalScanProgress();
    btn.disabled = true;
    const ac = new AbortController();
    const abortTimer = setTimeout(() => ac.abort(), TECH_ANALYZE_CLIENT_TIMEOUT_MS);
    let scanOk = false;
    const idemKey = technicalScanIdempotencyKey(url);
    try {
        const startHeaders = {
            "Content-Type": "application/json",
            Authorization: "Bearer " + token,
            "X-Idempotency-Key": idemKey,
        };
        const body = JSON.stringify({
            url,
            idempotency_key: idemKey,
            max_pages:
                window.TechDashboardV2 && typeof window.TechDashboardV2.getMaxPages === "function"
                    ? window.TechDashboardV2.getMaxPages()
                    : 25,
            ...getGscAuditRequestExtras(),
        });
        const fetchFn = typeof window.DigiSeoAuthFetch === "function" ? window.DigiSeoAuthFetch : fetch;
        const r = await fetchFn("/analyze/technical/jobs", {
            method: "POST",
            headers: startHeaders,
            body,
            signal: ac.signal,
            credentials: "same-origin",
        });
        if (typeof window.DigiSeoGetAuthToken === "function") {
            token = window.DigiSeoGetAuthToken() || token;
        }
        let start = await r.json().catch(() => ({}));
        let useSyncFallback = r.status === 404;
        if (!r.ok && !useSyncFallback) throw new Error(httpErrorFromResponse(r, start));

        let payload = useSyncFallback ? null : start.result;
        if (!useSyncFallback && !payload) {
            const jobId = start.job_id;
            if (!jobId) throw new Error("Không nhận được job_id để theo dõi quét.");
            applyTechnicalJobProgress(start);
            payload = await pollTechnicalScanJob(jobId, token, ac.signal);
        }
        if (useSyncFallback || !payload) {
            const syncRes = await fetch("/analyze/technical", {
                method: "POST",
                headers: startHeaders,
                body,
                signal: ac.signal,
            });
            payload = await syncRes.json().catch(() => ({}));
            if (!syncRes.ok) throw new Error(httpErrorFromResponse(syncRes, payload));
        }
        applyTechnicalScanPayload(payload);
        if (payload && payload.audit_id) setActiveAuditInSidebar(payload.audit_id);
        clearTimeout(abortTimer);
        setMsg(
            "Đã quét xong. Chọn nhóm lỗi ở sidebar trái để xem chi tiết từng chuyên mục.",
            "ok",
        );
        loadSidebarProjects();
        scanOk = true;
        resetTechnicalScanIdempotency();
    } catch (e) {
        clearTimeout(abortTimer);
        const errMsg =
            e && e.name === "AbortError"
                ? "Hết thời gian chờ trình duyệt (~15 phút). Site có thể quá chậm hoặc quá nhiều trang — thử giảm max_pages hoặc chạy lại sau."
                : String(e.message || e);
        if (e && e.name === "AbortError") {
            setMsg(errMsg, "error");
        } else {
            setMsg(errMsg, "error");
        }
        if (window.TechDashboardV2 && typeof window.TechDashboardV2.showScanError === "function") {
            window.TechDashboardV2.showScanError(errMsg, function () {
                btn.click();
            });
        }
    } finally {
        hideTechnicalScanProgress(scanOk);
        btn.disabled = !token;
    }
});

async function doLogin() {
    const email = authEmail.value.trim().toLowerCase();
    const password = authPassword.value;
    if (!email || !password) {
        setModalAuthMsg("Vui lòng nhập đủ email và mật khẩu.", "error");
        return;
    }
    try {
        setModalAuthMsg("Đang đăng nhập...", "");
        const body = { email, password };
        const r = await fetch("/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const rawText = await r.text();
        let d = {};
        if (rawText) {
            try {
                const parsed = JSON.parse(rawText);
                if (parsed != null && typeof parsed === "object" && !Array.isArray(parsed)) d = parsed;
            } catch {
                if (!r.ok) throw new Error(rawText.slice(0, 200) || "Phản hồi không phải JSON.");
                throw new Error("Phản hồi đăng nhập không hợp lệ.");
            }
        }
        if (!r.ok) throw new Error(apiDetail(d));
        token = d.access_token || "";
        if (!token) {
            setModalAuthMsg("Đăng nhập thất bại: không có mã truy cập. Thử lại.", "error");
            return;
        }
        if (typeof window.DigiSeoSetAuthToken === "function") {
            window.DigiSeoSetAuthToken(token);
        } else {
            // Storage only — seo_token cookie is HttpOnly (server-set); never write it from JS.
            sessionStorage.setItem("seo_token", token);
            try { localStorage.setItem("seo_token", token); } catch (_) {}
        }
        setModalAuthMsg("");
        applyAuthState();
        if (typeof window.DigiSeoAfterLoginSuccess === "function") {
            window.DigiSeoAfterLoginSuccess();
        }
    } catch (e) {
        setModalAuthMsg(String(e.message || e), "error");
    }
}

function openLoginModal() {
    if (!authModal) return;
    setModalAuthMsg("");
    if (authPassword) authPassword.value = "";
    if (typeof updatePwRuleEls === "function") updatePwRuleEls();
    authModal.hidden = false;
    if (typeof setAuthTab === "function") setAuthTab("login");
    try {
        if (authEmail) authEmail.focus();
    } catch (_) {}
}
window.DigiSeoOpenLoginModal = openLoginModal;
window.DigiSeoSetAuthTab = setAuthTab;

if (btnOpenLogin) {
    btnOpenLogin.addEventListener("click", openLoginModal);
}

if (btnGoogleLogin) {
    btnGoogleLogin.addEventListener("click", async () => {
        try {
            const r = await fetch("/auth/google/configured");
            const d = await r.json().catch(() => ({}));
            if (!r.ok || !d.configured) {
                setModalAuthMsg("Chưa bật đăng nhập Google. Liên hệ quản trị.", "error");
                return;
            }
            if (typeof window.DigiSeoRememberPostLoginReturn === "function") {
                window.DigiSeoRememberPostLoginReturn();
            }
            window.location.assign("/auth/google/login");
        } catch (e) {
            setModalAuthMsg("Không kết nối được OAuth Google. Thử lại sau.", "error");
        }
    });
}

if (btnSubmitAuth) {
    btnSubmitAuth.addEventListener("click", async () => {
        await doLogin();
    });
}

if (btnCloseModal && authModal) {
    btnCloseModal.addEventListener("click", () => {
        authModal.hidden = true;
        setModalAuthMsg("");
    });
}

if (btnLogout) btnLogout.addEventListener("click", () => {
    token = "";
    if (typeof window.DigiSeoLogout === "function") window.DigiSeoLogout();
    else {
        sessionStorage.removeItem("seo_token");
        try { localStorage.removeItem("seo_token"); } catch (_) {}
        try { fetch("/auth/logout", { method: "POST", credentials: "same-origin" }).catch(function () {}); } catch (_) {}
    }
    applyAuthState();
});

if (btnExportCsv) btnExportCsv.addEventListener("click", () => {
    if (!token) {
        setMsg("Cần đăng nhập trước khi xuất dữ liệu.", "error");
        return;
    }
    const id = btnExportCsv.dataset.auditExportId;
    if (id) {
        downloadAuditExport(id, "csv");
        return;
    }
    window.open("/api/report.csv", "_blank");
});

if (btnExportGsheet) btnExportGsheet.addEventListener("click", () => {
    if (!token) {
        setMsg("Cần đăng nhập trước khi xuất dữ liệu.", "error");
        return;
    }
    const id = btnExportGsheet.dataset.auditExportId;
    if (id) {
        downloadAuditExport(id, "gsheet");
        return;
    }
    window.open("/api/report.csv", "_blank");
});

const btnTechnicalDownloadExcel = document.getElementById("btnTechnicalDownloadExcel");
if (btnTechnicalDownloadExcel) {
    btnTechnicalDownloadExcel.addEventListener("click", () => {
        if (lastTechnicalAuditId) downloadAuditExport(lastTechnicalAuditId, "csv");
    });
}
const btnTechnicalNewAnalysis = document.getElementById("btnTechnicalNewAnalysis");
if (btnTechnicalNewAnalysis) {
    btnTechnicalNewAnalysis.addEventListener("click", () => {
        hideTechnicalCompleteBanner();
        lastTechnicalAuditId = null;
        const ex = document.getElementById("btnTechnicalDownloadExcel");
        if (ex) ex.disabled = true;
        btnExportCsv.disabled = true;
        btnExportGsheet.disabled = true;
        delete btnExportCsv.dataset.auditExportId;
        delete btnExportGsheet.dataset.auditExportId;
        setMsg("", "");
        urlInput.focus();
        try {
            urlInput.scrollIntoView({ behavior: "smooth", block: "center" });
        } catch (_e) {
            urlInput.scrollIntoView();
        }
    });
}

if (btnGoogleApisConnect) btnGoogleApisConnect.addEventListener("click", async () => {
    if (!token) return;
    try {
        const r = await fetch("/integrations/google/start", {
            method: "POST",
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));
        if (d.auth_url) window.location.href = d.auth_url;
    } catch (e) {
        setMsg(String(e.message || e), "error");
    }
});

if (btnGoogleApisDisconnect) btnGoogleApisDisconnect.addEventListener("click", async () => {
    if (!token) return;
    try {
        const r = await fetch("/integrations/google/disconnect", {
            method: "DELETE",
            headers: { Authorization: "Bearer " + token },
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(apiDetail(d));
        setMsg("Đã ngắt kết nối Google.", "ok");
        sessionStorage.removeItem(gscSiteStorageKey());
        sessionStorage.removeItem("gsc_selected_site_url");
        await refreshGoogleIntegrationStatus();
    } catch (e) {
        setMsg(String(e.message || e), "error");
    }
});

const gscSiteSelect = document.getElementById("gscSiteSelect");
if (gscSiteSelect) {
    gscSiteSelect.addEventListener("change", function () {
        if (this.value) {
            sessionStorage.setItem(gscSiteStorageKey(), this.value);
        }
    });
}
const btnGscCopySiteUrl = document.getElementById("btnGscCopySiteUrl");
if (btnGscCopySiteUrl) {
    btnGscCopySiteUrl.addEventListener("click", async () => {
        const sel = document.getElementById("gscSiteSelect");
        const v = sel && sel.value ? sel.value : "";
        if (!v) {
            setMsg("Chọn một property trong danh sách GSC trước.", "error");
            return;
        }
        try {
            await navigator.clipboard.writeText(v);
            setMsg("Đã sao chép siteUrl: " + v, "ok");
        } catch {
            setMsg(v, "ok");
        }
    });
}
const btnGscReloadSites = document.getElementById("btnGscReloadSites");
if (btnGscReloadSites) {
    btnGscReloadSites.addEventListener("click", () => loadGscSites());
}

(async function syncGoogleLoginReturn() {
    const q = new URLSearchParams(window.location.search);
    if (q.get("google_login") !== "1") {
        if (!token && typeof window.DigiSeoHydrateSessionFromCookie === "function") {
            try {
                const hydrated = await window.DigiSeoHydrateSessionFromCookie(false);
                if (hydrated) {
                    token = hydrated;
                    applyAuthState();
                }
            } catch (_e) {}
        }
        return;
    }
    // seo_token cookie is HttpOnly — read via /auth/session, not document.cookie
    if (typeof window.DigiSeoHydrateSessionFromCookie === "function") {
        try {
            token = (await window.DigiSeoHydrateSessionFromCookie(true)) || token;
        } catch (_e) {}
    } else if (typeof window.DigiSeoSyncTokenFromCookie === "function") {
        token = window.DigiSeoSyncTokenFromCookie() || token;
    }
    if (typeof window.DigiSeoSetAuthToken === "function" && token) {
        window.DigiSeoSetAuthToken(token);
    } else if (token) {
        try {
            sessionStorage.setItem("seo_token", token);
            localStorage.setItem("seo_token", token);
        } catch (_e) {}
    }
    if (typeof window.DigiSeoAfterLoginSuccess === "function") {
        window.DigiSeoAfterLoginSuccess();
    } else {
        history.replaceState({}, "", window.location.pathname);
    }
    applyAuthState();
    if (token) setMsg("Đăng nhập Google thành công.", "ok");
    else setMsg("Đăng nhập Google chưa hoàn tất session. Thử lại hoặc dùng email/mật khẩu.", "error");
})();

applyAuthState();
if (window.TechSidebarV2 && typeof window.TechSidebarV2.init === "function") {
    window.TechSidebarV2.init();
}
if (window.TechDashboardV2 && typeof window.TechDashboardV2.init === "function") {
    window.TechDashboardV2.init();
}
mountTechResultsInRightPanel();
wireTechSidebarNav();
const seoToolOverviewPassedViewAll = document.getElementById("seoToolOverviewPassedViewAll");
if (seoToolOverviewPassedViewAll) {
    seoToolOverviewPassedViewAll.addEventListener("click", () => {
        const btn = document.getElementById("seoToolOverviewPassedCollapsibleToggle");
        const body = document.getElementById("seoToolOverviewPassedCollapsibleBody");
        if (btn && body) {
            btn.setAttribute("aria-expanded", "true");
            body.hidden = false;
            try {
                body.scrollIntoView({ behavior: "smooth", block: "nearest" });
            } catch (_e) {
                body.scrollIntoView();
            }
            return;
        }
        revealToolResultsPanel();
        navigateTechTab("overview");
    });
}
const btnTechnicalRescan = document.getElementById("btnTechnicalRescan");
if (btnTechnicalRescan && btnTechnical) {
    btnTechnicalRescan.addEventListener("click", () => {
        if (!token) {
            setMsg("Đăng nhập để quét lại.", "error");
            return;
        }
        btnTechnical.click();
    });
}
const btnTechnicalExportHeader = document.getElementById("btnTechnicalExportHeader");
if (btnTechnicalExportHeader) {
    btnTechnicalExportHeader.addEventListener("click", () => {
        if (lastTechnicalAuditId) {
            downloadAuditExport(lastTechnicalAuditId, "csv");
            return;
        }
        const ex = document.getElementById("seoToolExportSection");
        if (ex) scrollToTechPanel(ex);
    });
}
wireIssuesToolbarOnce();
wirePassedChecksToggleOnce();
wirePassedFilterExpandOnce();
enforceIssuesViewForViewport();
window.addEventListener("resize", enforceIssuesViewForViewport);
restoreTechSidebarTab();
updateTechSidebarBadges([]);
(function googleReturnParams() {
    const q = new URLSearchParams(window.location.search);
    if (q.get("google") === "connected") {
        setMsg("Đã kết nối Google Search Console & Analytics (GA4).", "ok");
        history.replaceState({}, "", window.location.pathname);
    }
    const ge = q.get("google_error");
    if (ge) {
        setMsg("Lỗi Google OAuth: " + ge, "error");
        history.replaceState({}, "", window.location.pathname);
    }
})();
