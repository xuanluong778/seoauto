/**
 * Admin — Quản lý User (/admin)
 */
(function () {
    "use strict";

    const TOKEN_KEY = "seo_token";
    const MOBILE_MQ = window.matchMedia("(max-width: 767px)");

    const DETAIL_PANELS = {
        overview: "detailPanelOverview",
        saas: "detailPanelSaas",
        api: "detailPanelApi",
        data: "detailPanelData",
        credit: "detailPanelCredit",
        activity: "detailPanelActivity",
    };

    const CREDIT_TYPE_LABELS = {
        plan_monthly: "Gói tháng",
        purchased: "Mua thêm",
        admin_adjustment: "Điều chỉnh admin",
        refund: "Hoàn credit",
    };

    let grantCreditTarget = null;
    let grantChatbotCreditTarget = null;

    let toastTimer = null;
    let confirmResolve = null;
    let selectedUserId = null;
    let currentDetail = null;
    let apiToggleBusy = false;
    let usersLoading = false;
    let activeDetailTab = "overview";
    let saasGrantMode = "paid";
    let saasCache = { sub: null, usage: null, gifts: null, eligibility: null, error: null, loading: false };
    let allUserItems = [];
    let listTotal = 0;
    let listPage = 1;
    const PAGE_SIZE = 10;

    /* —— Utils —— */
    function readCookieToken() {
        const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
    }

    function getToken() {
        let t = (sessionStorage.getItem(TOKEN_KEY) || "").trim();
        if (!t) {
            t = readCookieToken();
            if (t) {
                try {
                    sessionStorage.setItem(TOKEN_KEY, t);
                } catch (_) {}
            }
        }
        return t;
    }

    function headers() {
        const t = getToken();
        const h = { "Content-Type": "application/json" };
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function fetchOpts(extra) {
        return { credentials: "same-origin", ...(extra || {}) };
    }

    function esc(s) {
        const d = document.createElement("div");
        d.textContent = String(s ?? "");
        return d.innerHTML;
    }

    function parseApiError(data, fallback) {
        if (!data) return fallback;
        const d = data.detail;
        if (typeof d === "string") return d;
        if (Array.isArray(d)) {
            return d.map((x) => (x && (x.msg || x.message)) || JSON.stringify(x)).join("; ");
        }
        if (d && typeof d === "object") {
            return d.msg || d.message || JSON.stringify(d);
        }
        return fallback;
    }

    function fmtDate(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN");
        } catch (_) {
            return iso;
        }
    }

    function fmtDay(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleDateString("vi-VN");
        } catch (_) {
            return String(iso).slice(0, 10);
        }
    }

    function fmtQuota(n) {
        if (n === null || n === undefined) return "∞";
        return String(n);
    }

    function fmtLimit(n) {
        if (n === null || n === undefined) return "—";
        if (Number(n) === -1) return "∞";
        return String(n);
    }

    function saasApi(path) {
        return "/api/admin/saas" + path;
    }

    function isMobileView() {
        return MOBILE_MQ.matches;
    }

    function avatarInitial(email) {
        const local = String(email || "").split("@")[0] || "?";
        const ch = local.replace(/[^a-zA-Z0-9]/g, "").charAt(0) || local.charAt(0) || "?";
        return ch.toUpperCase();
    }

    function apiOnForUser(u) {
        return !!u.api_access_enabled || String(u.role || "").toLowerCase() === "admin";
    }

    function apiAdminOnForUser(u) {
        return !!u.use_admin_api_pool || String(u.role || "").toLowerCase() === "admin";
    }

    function customApiOnForUser(u) {
        return !!u.allow_custom_api_key;
    }

    function llmSourceLabel(u) {
        const s = String((u && u.llm_source) || "system").toLowerCase();
        if (s === "custom") return "API riêng";
        if (s === "admin") return "Admin";
        return "API hệ thống";
    }

    function apiPermsCardsHtml(u, isAdminRole) {
        const apiOn = apiOnForUser(u);
        const poolOn = apiAdminOnForUser(u);
        const customOn = customApiOnForUser(u);
        const dis = isAdminRole || apiToggleBusy ? " disabled" : "";
        return `
            <p class="au-hint" style="margin:0 0 10px;">Nguồn AI hiện tại: <strong>${esc(llmSourceLabel(u))}</strong></p>
            <div class="au-api-toggle-card">
                <div>
                    <p class="au-api-toggle-label">Cho phép API key riêng</p>
                    <p class="au-api-toggle-hint">Legacy — đã tắt; mọi user dùng API hệ thống.</p>
                </div>
                <label class="au-toggle">
                    <input type="checkbox" id="toggleCustomApiKey"${customOn ? " checked" : ""}${dis} />
                    <span></span>
                </label>
            </div>
            <div class="au-api-toggle-card">
                <div>
                    <p class="au-api-toggle-label">Cho phép dùng API (legacy)</p>
                    <p class="au-api-toggle-hint">BYOK cũ — tương đương bật API key riêng.</p>
                </div>
                <label class="au-toggle">
                    <input type="checkbox" id="toggleApiAccess"${apiOn ? " checked" : ""}${dis} />
                    <span></span>
                </label>
            </div>
            <div class="au-api-toggle-card">
                <div>
                    <p class="au-api-toggle-label">Dùng API Admin pool (legacy)</p>
                    <p class="au-api-toggle-hint">User thường mặc định dùng API hệ thống khi có credit.</p>
                </div>
                <label class="au-toggle">
                    <input type="checkbox" id="toggleAdminPool"${poolOn ? " checked" : ""}${dis} />
                    <span></span>
                </label>
            </div>
            ${isAdminRole ? '<p class="au-panel-empty" style="margin-top:10px;">Tài khoản admin — quyền API luôn bật.</p>' : ""}`;
    }

    /* —— Toast & confirm —— */
    function showToast(message, type) {
        const el = document.getElementById("auToast");
        if (!el) return;
        el.textContent = message;
        el.className = "au-toast" + (type === "error" ? " is-error" : type === "success" ? " is-success" : "");
        el.hidden = false;
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            el.hidden = true;
        }, 4200);
    }

    function confirmAction(opts) {
        const modal = document.getElementById("auConfirmModal");
        const titleEl = document.getElementById("auConfirmTitle");
        const msgEl = document.getElementById("auConfirmMsg");
        const btnOk = document.getElementById("auConfirmOk");
        const btnCancel = document.getElementById("auConfirmCancel");
        if (!modal || !titleEl || !msgEl || !btnOk || !btnCancel) {
            return Promise.resolve(window.confirm((opts && opts.message) || "Xác nhận?"));
        }

        titleEl.textContent = (opts && opts.title) || "Xác nhận";
        msgEl.textContent = (opts && opts.message) || "Bạn có chắc muốn tiếp tục?";
        btnOk.textContent = (opts && opts.confirmLabel) || "Xác nhận";
        btnOk.className = "au-btn" + (opts && opts.danger ? " au-btn--danger" : " au-btn--primary");
        modal.hidden = false;
        btnOk.focus();

        return new Promise((resolve) => {
            if (confirmResolve) confirmResolve(false);
            confirmResolve = resolve;

            function cleanup(result) {
                modal.hidden = true;
                btnOk.removeEventListener("click", onOk);
                btnCancel.removeEventListener("click", onCancel);
                if (backdrop) backdrop.removeEventListener("click", onCancel);
                document.removeEventListener("keydown", onKey);
                const r = confirmResolve;
                confirmResolve = null;
                if (r) r(result);
            }

            function onOk() {
                cleanup(true);
            }
            function onCancel() {
                cleanup(false);
            }
            function onKey(e) {
                if (e.key === "Escape") onCancel();
            }

            const backdrop = document.getElementById("auConfirmBackdrop");
            btnOk.addEventListener("click", onOk);
            btnCancel.addEventListener("click", onCancel);
            if (backdrop) backdrop.addEventListener("click", onCancel);
            document.addEventListener("keydown", onKey);
        });
    }

    async function withButtonBusy(btn, fn) {
        if (!btn || btn.disabled) return;
        const prev = btn.textContent;
        btn.disabled = true;
        btn.classList.add("is-busy");
        if (btn.dataset.busyLabel) btn.textContent = btn.dataset.busyLabel;
        try {
            return await fn();
        } finally {
            btn.disabled = false;
            btn.classList.remove("is-busy");
            btn.textContent = prev;
        }
    }

    /* —— Badges —— */
    function roleBadge(role) {
        const r = String(role || "user").toLowerCase();
        const map = {
            admin: "au-badge--admin",
            user: "au-badge--user",
            editor: "au-badge--editor",
            viewer: "au-badge--viewer",
        };
        return `<span class="au-badge ${map[r] || "au-badge--user"}">${esc(r)}</span>`;
    }

    function statusBadge(st) {
        const s = String(st || "active").toLowerCase();
        const cls =
            s === "banned" ? "au-badge--banned" : s === "inactive" ? "au-badge--inactive" : "au-badge--active";
        return `<span class="au-badge ${cls}">${esc(s)}</span>`;
    }

    function trialBadge(u) {
        const st = String(u.trial_status || "none").toLowerCase();
        const map = {
            active: ["au-badge--trial", "Đang trial"],
            pending: ["au-badge--trial", "Chưa trial"],
            expired: ["au-badge--trial-expired", "Hết trial"],
            admin: ["au-badge--admin", "Admin"],
            api_granted: ["au-badge--api-on", "API cấp"],
            none: ["au-badge--trial-expired", "—"],
        };
        const [cls, label] = map[st] || map.none;
        return `<span class="au-badge ${cls}" title="${esc(u.trial_message || "")}">${label}</span>`;
    }

    function apiBadge(on) {
        const cls = on ? "au-badge--api-on" : "au-badge--api-off";
        return `<span class="au-badge ${cls}">${on ? "Bật" : "Tắt"}</span>`;
    }

    function apiAdminBadge(on) {
        const cls = on ? "au-badge--api-on" : "au-badge--api-off";
        return `<span class="au-badge ${cls}">${on ? "Pool bật" : "Pool tắt"}</span>`;
    }

    /* —— DOM refs —— */
    const blockedView = document.getElementById("blockedView");
    const adminApp = document.getElementById("adminApp");
    const adminMsg = document.getElementById("adminMsg");
    const userListMeta = document.getElementById("userListMeta");
    const userListLoading = document.getElementById("userListLoading");
    const userListEmpty = document.getElementById("userListEmpty");
    const userListError = document.getElementById("userListError");
    const userTableWrap = document.getElementById("userTableWrap");
    const userTableBody = document.getElementById("userTableBody");
    const userCardList = document.getElementById("userCardList");
    const detailEmpty = document.getElementById("detailEmpty");
    const detailContent = document.getElementById("detailContent");
    const detailLoading = document.getElementById("detailLoading");
    const detailError = document.getElementById("detailError");
    const detailCard = document.getElementById("detailCard");

    function showListError(msg) {
        if (!userListError) return;
        userListError.textContent = msg || "";
        userListError.hidden = !msg;
    }

    function showDetailError(msg) {
        if (!detailError) return;
        detailError.textContent = msg || "";
        detailError.hidden = !msg;
    }

    function setListLoading(on) {
        usersLoading = on;
        if (userListLoading) userListLoading.hidden = !on;
        if (on) {
            if (userTableWrap) userTableWrap.classList.add("is-hidden");
            if (userCardList) {
                userCardList.hidden = true;
                userCardList.classList.remove("is-visible");
            }
            if (userListEmpty) userListEmpty.hidden = true;
            showListError("");
        }
    }

    function setDetailLoading(on) {
        if (detailLoading) detailLoading.hidden = !on;
        if (on) {
            if (detailContent) detailContent.hidden = true;
            if (detailEmpty) detailEmpty.hidden = true;
            showDetailError("");
        }
    }

    function scrollToDetailOnMobile() {
        if (!isMobileView() || !detailCard) return;
        detailCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    /* —— Table / accordion helpers —— */
    function renderTable(cols, rows) {
        if (!rows || !rows.length) {
            return '<p class="au-panel-empty">Không có dữ liệu.</p>';
        }
        let h = "<table class='au-mini-table'><thead><tr>";
        cols.forEach((c) => {
            h += `<th>${esc(c.label)}</th>`;
        });
        h += "</tr></thead><tbody>";
        rows.forEach((row) => {
            h += "<tr>";
            cols.forEach((c) => {
                h += `<td>${c.html ? c.fn(row) : esc(c.fn(row))}</td>`;
            });
            h += "</tr>";
        });
        return h + "</tbody></table>";
    }

    function renderAccordion(title, count, innerHtml, open) {
        return `
            <details class="au-accordion"${open ? " open" : ""}>
                <summary>${esc(title)} <span class="au-accordion-count">${count}</span></summary>
                <div class="au-accordion-body">${innerHtml}</div>
            </details>`;
    }

    function usagePercent(used, limit) {
        const u = Number(used) || 0;
        const l = Number(limit);
        if (limit === null || limit === undefined || l < 0) return null;
        if (l === 0) return u > 0 ? 100 : 0;
        return Math.min(100, Math.round((u / l) * 100));
    }

    function usageProgressHtml(used, limit) {
        const pct = usagePercent(used, limit);
        if (pct === null) return "";
        const cls = pct >= 90 ? " is-danger" : pct >= 70 ? " is-warn" : "";
        return `<div class="au-progress" aria-hidden="true"><div class="au-progress-bar${cls}" style="width:${pct}%"></div></div>`;
    }

    function trialLabelShort(u) {
        const st = String(u.trial_status || "none").toLowerCase();
        if (st === "active") return "Đang trial";
        if (st === "pending") return "Chưa kích hoạt";
        if (st === "expired") return "Hết trial";
        if (st === "admin") return "Admin";
        return "—";
    }

    function saasPlanLabel() {
        const sub = saasCache.sub || {};
        if (sub.plan_slug) return sub.plan_name || sub.plan_slug;
        return "Chưa có gói";
    }

    function updateStats(items, total) {
        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = String(val);
        };
        const active = items.filter((u) => String(u.status).toLowerCase() === "active").length;
        const trial = items.filter((u) => {
            const s = String(u.trial_status || "").toLowerCase();
            return s === "active" || s === "pending";
        }).length;
        const adminEditor = items.filter((u) => {
            const r = String(u.role || "").toLowerCase();
            return r === "admin" || r === "editor";
        }).length;
        set("statTotal", total);
        set("statActive", active);
        set("statTrial", trial);
        set("statAdminEditor", adminEditor);
    }

    function renderPagination() {
        const wrap = document.getElementById("userPagination");
        if (!wrap) return;
        const total = allUserItems.length;
        const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
        if (!total) {
            wrap.hidden = true;
            wrap.innerHTML = "";
            return;
        }
        wrap.hidden = false;

        const from = (listPage - 1) * PAGE_SIZE + 1;
        const to = Math.min(listPage * PAGE_SIZE, total);
        const rangeText =
            totalPages > 1
                ? `Hiển thị ${from.toLocaleString("vi-VN")}–${to.toLocaleString("vi-VN")} / ${total.toLocaleString("vi-VN")} user`
                : `Hiển thị ${total.toLocaleString("vi-VN")} user`;

        let pages = "";
        if (totalPages > 1) {
            pages += `<button type="button" class="au-page-btn au-page-btn--nav" data-page="${listPage - 1}" ${listPage <= 1 ? "disabled" : ""} aria-label="Trang trước">‹</button>`;
            const maxBtns = 5;
            let start = Math.max(1, listPage - 2);
            let end = Math.min(totalPages, start + maxBtns - 1);
            start = Math.max(1, end - maxBtns + 1);
            for (let p = start; p <= end; p++) {
                pages += `<button type="button" class="au-page-btn${p === listPage ? " is-active" : ""}" data-page="${p}" aria-label="Trang ${p}"${p === listPage ? ' aria-current="page"' : ""}>${p}</button>`;
            }
            pages += `<button type="button" class="au-page-btn au-page-btn--nav" data-page="${listPage + 1}" ${listPage >= totalPages ? "disabled" : ""} aria-label="Trang sau">›</button>`;
        }

        wrap.innerHTML = `
            <div class="au-pagination-pages">${pages}</div>
            <span class="au-page-size">${rangeText} · ${PAGE_SIZE} / trang</span>`;
        wrap.querySelectorAll("[data-page]").forEach((btn) => {
            btn.addEventListener("click", () => {
                if (btn.disabled) return;
                const nextPage = parseInt(btn.getAttribute("data-page"), 10) || 1;
                if (nextPage < 1 || nextPage > totalPages || nextPage === listPage) return;
                listPage = nextPage;
                renderUserLists(allUserItems);
                wrap.scrollIntoView({ block: "nearest", behavior: "smooth" });
            });
        });
    }

    function copyEmailToClipboard(email) {
        const text = String(email || "");
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(
                () => showToast("Đã copy email", "success"),
                () => showToast("Không copy được email", "error")
            );
        } else {
            showToast(text, "success");
        }
    }

    function apiTableCell(on) {
        return on
            ? '<span class="au-api-icon-on" title="API bật">✓</span>'
            : '<span class="au-api-icon-off" title="API tắt">✕</span>';
    }

    function creditTypeLabel(key) {
        return CREDIT_TYPE_LABELS[key] || key || "—";
    }

    function formatCreditDelta(n) {
        const v = Number(n || 0);
        if (v > 0) return "+" + v.toLocaleString("vi-VN");
        return v.toLocaleString("vi-VN");
    }

    function renderCreditHistoryTable(rows) {
        if (!rows || !rows.length) {
            return '<p class="au-panel-empty">Chưa có lịch sử credit.</p>';
        }
        let h = `<div class="au-table-wrap"><table class="au-mini-table au-credit-history-table">
            <thead><tr>
                <th>Thời gian</th>
                <th>Loại credit</th>
                <th>Số credit</th>
                <th>Nguồn</th>
                <th>Lý do</th>
                <th>Admin</th>
                <th>Ghi chú nội bộ</th>
            </tr></thead><tbody>`;
        rows.forEach((row) => {
            const amt = Number(row.amount || 0);
            const amtClass = amt >= 0 ? "is-plus" : "is-minus";
            h += `<tr>
                <td>${esc(fmtDate(row.created_at))}</td>
                <td>${esc(creditTypeLabel(row.credit_type))}</td>
                <td class="au-credit-delta ${amtClass}">${esc(formatCreditDelta(amt))}</td>
                <td>${esc(row.source_label || row.transaction_type || "—")}</td>
                <td>${esc(row.grant_reason || "—")}</td>
                <td>${esc(row.admin_email || "—")}</td>
                <td class="au-credit-internal">${esc(row.internal_note || "—")}</td>
            </tr>`;
        });
        return h + "</tbody></table></div>";
    }

    function openGrantCreditModal(user) {
        if (!user || !user.id) return;
        grantCreditTarget = { id: user.id, email: user.email || "" };
        const modal = document.getElementById("auGrantCreditModal");
        const errEl = document.getElementById("grantCreditError");
        const subtitle = document.getElementById("auGrantCreditSubtitle");
        const typeEl = document.getElementById("grantCreditType");
        const amountEl = document.getElementById("grantCreditAmount");
        const reasonEl = document.getElementById("grantCreditReason");
        const noteEl = document.getElementById("grantCreditNote");
        if (errEl) errEl.hidden = true;
        if (subtitle) subtitle.textContent = "Tặng credit cho: " + (user.email || "user #" + user.id);
        if (typeEl) typeEl.value = "admin_adjustment";
        if (amountEl) amountEl.value = "";
        if (reasonEl) reasonEl.value = "";
        if (noteEl) noteEl.value = "";
        if (modal) modal.hidden = false;
        if (amountEl) {
            try {
                amountEl.focus();
            } catch (_) {}
        }
    }

    function closeGrantCreditModal() {
        grantCreditTarget = null;
        const modal = document.getElementById("auGrantCreditModal");
        if (modal) modal.hidden = true;
    }

    function openGrantChatbotCreditModal(user) {
        if (!user || !user.id) return;
        grantChatbotCreditTarget = { id: user.id, email: user.email || "" };
        const modal = document.getElementById("auGrantChatbotCreditModal");
        const errEl = document.getElementById("grantChatbotCreditError");
        const subtitle = document.getElementById("auGrantChatbotCreditSubtitle");
        const opEl = document.getElementById("grantChatbotCreditOp");
        const amountEl = document.getElementById("grantChatbotCreditAmount");
        const reasonEl = document.getElementById("grantChatbotCreditReason");
        const noteEl = document.getElementById("grantChatbotCreditNote");
        if (errEl) errEl.hidden = true;
        if (subtitle) {
            subtitle.textContent = "Credit chatbot bonus hiện tại: "
                + Number(user.chatbot_cskh_bonus_credits || 0).toLocaleString("vi-VN")
                + " — user: " + (user.email || "user #" + user.id);
        }
        if (opEl) opEl.value = "add";
        if (amountEl) amountEl.value = "";
        if (reasonEl) reasonEl.value = "";
        if (noteEl) noteEl.value = "";
        if (modal) modal.hidden = false;
        if (amountEl) {
            try { amountEl.focus(); } catch (_) {}
        }
    }

    function closeGrantChatbotCreditModal() {
        grantChatbotCreditTarget = null;
        const modal = document.getElementById("auGrantChatbotCreditModal");
        if (modal) modal.hidden = true;
    }

    async function submitGrantChatbotCredit(ev) {
        if (ev) ev.preventDefault();
        if (!grantChatbotCreditTarget || !grantChatbotCreditTarget.id) return;

        const errEl = document.getElementById("grantChatbotCreditError");
        const btnSubmit = document.getElementById("auGrantChatbotCreditSubmit");
        const operation = (document.getElementById("grantChatbotCreditOp")?.value || "add").trim();
        const amount = parseInt(document.getElementById("grantChatbotCreditAmount")?.value || "0", 10);
        const reason = (document.getElementById("grantChatbotCreditReason")?.value || "").trim();
        const note = (document.getElementById("grantChatbotCreditNote")?.value || "").trim();

        if (!Number.isFinite(amount) || amount <= 0) {
            if (errEl) { errEl.textContent = "Số credit không hợp lệ."; errEl.hidden = false; }
            return;
        }
        if (!reason) {
            if (errEl) { errEl.textContent = "Vui lòng nhập lý do."; errEl.hidden = false; }
            return;
        }

        const payload = { operation, amount, reason, note: note || null };

        try {
            await withButtonBusy(btnSubmit, async () => {
                const r = await fetch(
                    "/admin/api/users/" + grantChatbotCreditTarget.id + "/grant-chatbot-credits",
                    fetchOpts({ method: "POST", headers: headers(), body: JSON.stringify(payload) })
                );
                const data = await r.json().catch(() => ({}));
                if (r.status === 403) throw new Error("Bạn không có quyền thực hiện thao tác này.");
                if (!r.ok) throw new Error(parseApiError(data, "Không cập nhật được credit chatbot."));
                const targetId = grantChatbotCreditTarget.id;
                closeGrantChatbotCreditModal();
                showToast(data.message || "Đã cập nhật credit chatbot.", "success");
                await loadUsers();
                await loadAdminAudit();
                if (selectedUserId === targetId) await selectUser(selectedUserId);
            });
        } catch (e) {
            if (errEl) { errEl.textContent = e.message || "Có lỗi."; errEl.hidden = false; }
        }
    }

    async function submitGrantCredit(ev) {
        if (ev) ev.preventDefault();
        if (!grantCreditTarget || !grantCreditTarget.id) return;

        const errEl = document.getElementById("grantCreditError");
        const btnSubmit = document.getElementById("auGrantCreditSubmit");
        const creditType = (document.getElementById("grantCreditType")?.value || "").trim();
        const amount = parseInt(document.getElementById("grantCreditAmount")?.value || "0", 10);
        const reason = (document.getElementById("grantCreditReason")?.value || "").trim();
        const note = (document.getElementById("grantCreditNote")?.value || "").trim();

        if (!creditType) {
            if (errEl) {
                errEl.textContent = "Vui lòng chọn loại credit.";
                errEl.hidden = false;
            }
            return;
        }
        if (!Number.isFinite(amount) || amount <= 0) {
            if (errEl) {
                errEl.textContent = "Số credit không hợp lệ.";
                errEl.hidden = false;
            }
            return;
        }
        if (!reason) {
            if (errEl) {
                errEl.textContent = "Vui lòng nhập lý do tặng.";
                errEl.hidden = false;
            }
            return;
        }

        const payload = {
            credit_type: creditType,
            amount,
            reason,
            note: note || null,
        };

        try {
            await withButtonBusy(btnSubmit, async () => {
                const r = await fetch(
                    "/admin/api/users/" + grantCreditTarget.id + "/grant-credits",
                    fetchOpts({
                        method: "POST",
                        headers: headers(),
                        body: JSON.stringify(payload),
                    })
                );
                const data = await r.json().catch(() => ({}));
                if (r.status === 403) {
                    throw new Error("Bạn không có quyền thực hiện thao tác này.");
                }
                if (!r.ok) throw new Error(parseApiError(data, "Không tặng được credit."));
                const targetId = grantCreditTarget.id;
                closeGrantCreditModal();
                showToast(data.message || "Đã tặng credit thành công.", "success");
                await loadUsers();
                await loadAdminAudit();
                if (selectedUserId === targetId) {
                    await selectUser(selectedUserId);
                }
            });
        } catch (e) {
            if (errEl) {
                errEl.textContent = e.message || String(e);
                errEl.hidden = false;
            } else {
                showToast(e.message || String(e), "error");
            }
        }
    }

    function renderTimeline(logs) {
        if (!logs || !logs.length) {
            return '<p class="au-panel-empty">Chưa có hoạt động ghi nhận.</p>';
        }
        let h = '<ul class="au-timeline">';
        logs.forEach((row) => {
            h += `<li>
                <time>${esc(fmtDate(row.created_at))}</time>
                <strong>${esc(row.action)}</strong>
                <span>${esc(row.resource_type)}/${esc(row.resource_id)} · IP ${esc(row.ip_address || "—")}</span>
            </li>`;
        });
        return h + "</ul>";
    }

    /* —— Detail renderers —— */
    function renderUserHeader() {
        const mount = document.getElementById("userProfileHeader");
        if (!mount || !currentDetail) return;
        const u = currentDetail.user;
        const trialKpiClass = u.trial_is_active ? "au-mini-kpi--ok" : "au-mini-kpi--warn";
        const apiKpiClass = apiOnForUser(u) ? "au-mini-kpi--ok" : "au-mini-kpi--muted";
        const poolKpiClass = apiAdminOnForUser(u) ? "au-mini-kpi--ok" : "au-mini-kpi--muted";

        mount.innerHTML = `
            <article class="au-profile-v2">
                <div class="au-profile-top">
                    <div class="au-profile-avatar-v2" aria-hidden="true">${esc(avatarInitial(u.email))}</div>
                    <div class="au-profile-info">
                        <div class="au-profile-email-row">
                            <h3 class="au-profile-email-v2">${esc(u.email)}</h3>
                            <button type="button" class="au-icon-btn" id="btnCopyEmail" title="Copy email">⎘</button>
                        </div>
                        <div class="au-profile-badges">
                            ${roleBadge(u.role)}
                            ${statusBadge(u.status)}
                            <span class="au-badge au-badge--user">ID: ${u.id}</span>
                        </div>
                        <p class="au-profile-meta-v2">
                            Tạo lúc: ${esc(fmtDate(u.created_at))} · Credit: ${esc(Number(u.credit_balance || 0).toLocaleString("vi-VN"))}
                        </p>
                    </div>
                    <div class="au-profile-actions">
                        <button type="button" class="au-btn au-btn--primary" id="btnGrantCreditDetail">Tặng credit</button>
                        <details class="au-more-menu">
                            <summary class="au-btn au-btn--ghost">Hành động khác ▾</summary>
                            <div class="au-more-dropdown">
                                <button type="button" data-action="refresh-user">Làm mới user</button>
                                <button type="button" data-action="lock-user">Khóa tài khoản</button>
                                <button type="button" data-action="ban-user">Cấm tài khoản</button>
                                <button type="button" data-action="delete-user" class="au-text-danger">Xóa user vĩnh viễn</button>
                            </div>
                        </details>
                    </div>
                </div>
                <div class="au-mini-kpi-row">
                    <div class="au-mini-kpi ${trialKpiClass}">Trial<strong>${esc(trialLabelShort(u))}</strong></div>
                    <div class="au-mini-kpi ${apiKpiClass}">Nguồn AI<strong>${esc(llmSourceLabel(u))}</strong></div>
                    <div class="au-mini-kpi">Gói SaaS<strong>${esc(saasPlanLabel())}</strong></div>
                </div>
            </article>`;

        const btnGrantDetail = document.getElementById("btnGrantCreditDetail");
        if (btnGrantDetail) {
            btnGrantDetail.onclick = () => openGrantCreditModal(u);
        }
    }

    function renderOverviewTab() {
        const panel = document.getElementById(DETAIL_PANELS.overview);
        if (!panel || !currentDetail) return;
        const u = currentDetail.user;
        const trial = currentDetail.trial || {};
        const isAdminRole = String(u.role || "").toLowerCase() === "admin";
        const apiOn = apiOnForUser(u);
        const poolOn = apiAdminOnForUser(u);

        panel.innerHTML = `
            <div class="au-overview-grid">
                <section class="au-subcard">
                    <h4 class="au-subcard-title">Thông tin tài khoản</h4>
                    <ul class="au-info-list">
                        <li><span>Email</span><span>${esc(u.email)}</span></li>
                        <li><span>Role</span><span>${roleBadge(u.role)}</span></li>
                        <li><span>Status</span><span>${statusBadge(u.status)}</span></li>
                        <li><span>Credit</span><span>${esc(Number(u.credit_balance || 0).toLocaleString("vi-VN"))}</span></li>
                        <li><span>Ngày tạo</span><span>${esc(fmtDate(u.created_at))}</span></li>
                        <li><span>Trial bắt đầu</span><span>${esc(fmtDay(u.trial_started_at || trial.started_at))}</span></li>
                        <li><span>Trial hết hạn</span><span>${esc(fmtDay(u.trial_ends_at || trial.ends_at))}</span></li>
                        <li><span>Kích hoạt</span><span>${u.account_activated ? "Đã kích hoạt" : "Chưa"}</span></li>
                    </ul>
                </section>
                <section class="au-subcard">
                    <h4 class="au-subcard-title">Hành động nhanh</h4>
                    <div class="au-quick-actions">
                        <label class="au-field-stack">
                            <span class="au-field-label">Role</span>
                            <select id="selNewRole" class="au-select">
                                <option value="user">user</option>
                                <option value="editor">editor</option>
                                <option value="viewer">viewer</option>
                                <option value="admin">admin</option>
                            </select>
                        </label>
                        <label class="au-field-stack">
                            <span class="au-field-label">Status</span>
                            <select id="selNewStatus" class="au-select">
                                <option value="active">active</option>
                                <option value="inactive">inactive</option>
                                <option value="banned">banned</option>
                            </select>
                        </label>
                        <button type="button" class="au-btn au-btn--primary au-btn--block" id="btnGrantCreditOverview">Tặng credit</button>
                        <button type="button" class="au-btn au-btn--primary au-btn--block" id="btnSaveAccount" data-busy-label="Đang lưu…">Lưu thay đổi</button>
                        <button type="button" class="au-btn" id="btnResetTrial">Đặt lại trial</button>
                        <button type="button" class="au-btn" id="btnDeactivateAccount">Khóa tài khoản</button>
                        <button type="button" class="au-btn au-btn--danger au-btn--block" id="btnBanAccount">Cấm tài khoản</button>
                        <button type="button" class="au-btn au-btn--danger au-btn--block" id="btnDeleteAccount">Xóa user vĩnh viễn</button>
                        <div class="au-quick-api" id="apiPermsBlock">
                            <h5 class="au-quick-api-title">Quyền sử dụng API</h5>
                            ${apiPermsCardsHtml(u, isAdminRole)}
                        </div>
                    </div>
                </section>
            </div>`;

        document.getElementById("selNewRole").value = u.role;
        document.getElementById("selNewStatus").value = u.status;

        const btnGrantOverview = document.getElementById("btnGrantCreditOverview");
        if (btnGrantOverview) {
            btnGrantOverview.onclick = () => openGrantCreditModal(u);
        }
    }

    function renderCreditTab() {
        const panel = document.getElementById(DETAIL_PANELS.credit);
        if (!panel || !currentDetail) return;
        const u = currentDetail.user;
        panel.innerHTML = `
            <section class="au-subcard">
                <div class="au-credit-head">
                    <div>
                        <h4 class="au-subcard-title">Lịch sử credit</h4>
                        <p class="au-hint">Số dư keyword/content: <strong>${esc(Number(u.credit_balance || 0).toLocaleString("vi-VN"))}</strong> credit</p>
                        <p class="au-hint">Credit chatbot CSKH (bonus): <strong>${esc(Number(u.chatbot_cskh_bonus_credits || 0).toLocaleString("vi-VN"))}</strong></p>
                    </div>
                    <div class="au-credit-actions">
                        <button type="button" class="au-btn au-btn--primary" id="btnGrantCreditTab">Tặng credit</button>
                        <button type="button" class="au-btn" id="btnGrantChatbotCreditTab">Cộng/trừ credit Chatbot</button>
                    </div>
                </div>
                ${renderCreditHistoryTable(currentDetail.credit_history || [])}
            </section>`;
        const btn = document.getElementById("btnGrantCreditTab");
        if (btn) btn.onclick = () => openGrantCreditModal(u);
        const btnChatbot = document.getElementById("btnGrantChatbotCreditTab");
        if (btnChatbot) btnChatbot.onclick = () => openGrantChatbotCreditModal(u);
    }

    function renderSaasTab() {
        const panel = document.getElementById(DETAIL_PANELS.saas);
        if (!panel) return;

        if (saasCache.loading) {
            panel.innerHTML = '<div class="au-loading"><span class="au-spinner" aria-hidden="true"></span> Đang tải SaaS…</div>';
            return;
        }

        if (saasCache.error) {
            panel.innerHTML = `<div class="au-error-banner" role="alert">${esc(saasCache.error)}</div>`;
            return;
        }

        const sub = saasCache.sub || {};
        const usage = saasCache.usage || {};
        const items = usage.items || [];

        const planHtml = sub.plan_slug
            ? `<span class="au-badge au-badge--saas">${esc(sub.plan_name || sub.plan_slug)}</span>`
            : '<span class="au-badge au-badge--trial-expired">Chưa có gói</span>';

        let usageRows = "";
        if (!items.length) {
            usageRows = '<tr><td colspan="4" class="au-panel-empty">Chưa có usage tháng này.</td></tr>';
        } else {
            items.forEach((row) => {
                const used = row.quantity_used;
                const limit = row.limit_value;
                usageRows += `<tr class="au-usage-row">
                    <td>${esc(row.feature_key)}${usageProgressHtml(used, limit)}</td>
                    <td>${used}</td>
                    <td>${fmtLimit(limit)}</td>
                    <td>${fmtQuota(row.quota_remaining)}</td>
                </tr>`;
            });
        }

        panel.innerHTML = `
            <div class="au-kpi-row">
                <div class="au-kpi"><span class="au-kpi-label">Plan</span><span class="au-kpi-value">${planHtml}</span></div>
                <div class="au-kpi"><span class="au-kpi-label">Subscription</span><span class="au-kpi-value">${esc(sub.status || "—")}</span></div>
                <div class="au-kpi"><span class="au-kpi-label">Hết kỳ</span><span class="au-kpi-value">${esc(fmtDate(sub.current_period_end))}</span></div>
                <div class="au-kpi"><span class="au-kpi-label">Tháng usage</span><span class="au-kpi-value">${esc(usage.usage_month || "—")}</span></div>
            </div>
            ${sub.message || usage.message ? `<p class="au-saas-msg">${esc(sub.message || usage.message)}</p>` : ""}
            <section class="au-subcard">
                <h4 class="au-subcard-title">Usage tháng</h4>
                <div class="au-table-wrap">
                    <table class="au-mini-table">
                        <thead><tr><th>Feature</th><th>Đã dùng</th><th>Giới hạn</th><th>Còn lại</th></tr></thead>
                        <tbody>${usageRows}</tbody>
                    </table>
                </div>
            </section>
            <section class="au-subcard">
                <h4 class="au-subcard-title">Quản lý gói &amp; quà tặng</h4>
                <p class="au-saas-mode-hint">Chọn loại thao tác bên dưới để kích hoạt gói trả phí, tặng gói miễn phí hoặc tặng thêm ngày sử dụng.</p>
                <div class="au-grant-modes" id="saasGrantModes" role="tablist" aria-label="Loại thao tác">
                    <button type="button" class="au-grant-mode${saasGrantMode === "paid" ? " is-active" : ""}" data-grant-mode="paid" role="tab" aria-selected="${saasGrantMode === "paid"}">Kích hoạt gói trả phí</button>
                    <button type="button" class="au-grant-mode${saasGrantMode === "gift_plan" ? " is-active" : ""}" data-grant-mode="gift_plan" role="tab" aria-selected="${saasGrantMode === "gift_plan"}">Tặng gói miễn phí</button>
                    <button type="button" class="au-grant-mode${saasGrantMode === "gift_days" ? " is-active" : ""}" data-grant-mode="gift_days" role="tab" aria-selected="${saasGrantMode === "gift_days"}">Tặng ngày sử dụng</button>
                </div>

                <div id="saasPanelPaid">
                    <div class="au-saas-form">
                        <label>Gói<select id="saasGrantPlan" class="au-select">
                            <option value="free_trial_5d">Trial 5 ngày (BYOK)</option>
                            <option value="starter">Basic</option>
                            <option value="pro">Pro</option>
                            <option value="agency">Agency</option>
                            <option value="business">Business</option>
                        </select></label>
                        <label>Chu kỳ<select id="saasGrantCycle" class="au-select">
                            <option value="monthly">Tháng</option>
                            <option value="semi_annual">6 tháng</option>
                            <option value="yearly">Năm</option>
                        </select></label>
                        <label>Tháng<input type="number" id="saasGrantMonths" class="au-input" min="1" max="36" value="1" /></label>
                        <label class="grow">Ghi chú<input type="text" id="saasGrantNotes" class="au-input" placeholder="Ghi chú nội bộ…" /></label>
                        <button type="button" class="au-btn au-btn--primary" id="btnSaasGrant" data-busy-label="Đang kích hoạt…">Kích hoạt gói</button>
                    </div>
                    <p class="au-saas-hint" id="saasGrantCycleHint" hidden></p>
                </div>

                <div id="saasPanelGiftPlan" hidden>
                    <div class="au-saas-form">
                        <label>Gói<select id="saasGiftPlan" class="au-select">
                            <option value="starter">Basic</option>
                            <option value="pro">Pro</option>
                            <option value="agency">Agency</option>
                            <option value="business">Business</option>
                        </select></label>
                        <label>Đơn vị<select id="saasGiftDurationUnit" class="au-select">
                            <option value="days">Ngày</option>
                            <option value="months">Tháng</option>
                        </select></label>
                        <label>Thời hạn<input type="number" id="saasGiftDuration" class="au-input" min="1" max="365" value="30" /></label>
                        <label class="au-check-label"><input type="checkbox" id="saasGiftIncludeCredit" /> Tặng kèm credit (1 tháng theo gói)</label>
                        <label class="grow">Ghi chú<input type="text" id="saasGiftPlanNotes" class="au-input" placeholder="Lý do tặng gói…" /></label>
                        <button type="button" class="au-btn au-btn--primary" id="btnSaasGiftPlan" data-busy-label="Đang tặng…">Tặng gói</button>
                    </div>
                </div>

                <div id="saasPanelGiftDays" hidden>
                    <p class="au-saas-hint" id="saasGiftDaysInfo" hidden></p>
                    <div class="au-day-picks" id="saasGiftDayPicks">
                        <span class="au-day-picks-label">Chọn nhanh:</span>
                        <button type="button" class="au-btn au-btn--sm" data-gift-days="5">5 ngày</button>
                        <button type="button" class="au-btn au-btn--sm" data-gift-days="10">10 ngày</button>
                        <button type="button" class="au-btn au-btn--sm" data-gift-days="15">15 ngày</button>
                        <button type="button" class="au-btn au-btn--sm" data-gift-days="20">20 ngày</button>
                        <button type="button" class="au-btn au-btn--sm" data-gift-days="25">25 ngày</button>
                    </div>
                    <div class="au-saas-form" style="margin-top:10px;">
                        <label>Số ngày<input type="number" id="saasGiftDays" class="au-input" min="1" max="365" value="5" /></label>
                        <label class="grow">Ghi chú<input type="text" id="saasGiftDaysNotes" class="au-input" placeholder="Lý do tặng ngày…" /></label>
                        <button type="button" class="au-btn au-btn--primary" id="btnSaasGiftDays" data-busy-label="Đang tặng…">Tặng ngày</button>
                    </div>
                </div>

                <div class="au-saas-form" style="margin-top:14px;">
                    <label>Feature<select id="saasFeatureKey" class="au-select">
                        <option value="content_ai_article">content_ai_article</option>
                        <option value="technical_audit">technical_audit</option>
                        <option value="keyword_research">keyword_research</option>
                        <option value="content_ai_bulk_article">content_ai_bulk_article</option>
                        <option value="seo_score">seo_score</option>
                        <option value="keyword_cluster">keyword_cluster</option>
                    </select></label>
                    <button type="button" class="au-btn" id="btnSaasEntitlement" data-busy-label="Đang kiểm tra…">Kiểm tra quyền</button>
                </div>
                <div id="saasEntResult" class="au-ent-result" hidden></div>
            </section>
            <section class="au-subcard">
                <h4 class="au-subcard-title">Lịch sử quà tặng</h4>
                <div id="saasGiftHistoryList">${renderGiftHistoryHtml(saasCache.gifts)}</div>
            </section>`;
        syncSaasGrantModeUi();
        syncSaasGrantCycleUi();
    }

    function renderGiftHistoryHtml(giftsRes) {
        const items = (giftsRes && giftsRes.items) || [];
        if (!items.length) {
            return '<p class="au-panel-empty">Chưa có lịch sử quà tặng.</p>';
        }
        return `<div class="au-table-wrap"><table class="au-mini-table au-gift-table">
            <thead><tr><th>Thời gian</th><th>Loại</th><th>Gói</th><th>Chi tiết</th><th>Ghi chú</th></tr></thead>
            <tbody>${items.map((g) => {
                const badgeClass = g.gift_type === "plan" ? "au-gift-badge--plan" : "au-gift-badge--days";
                let detail = "";
                if (g.gift_type === "plan") {
                    const parts = [];
                    if (g.duration_days) parts.push(g.duration_days + " ngày");
                    if (g.duration_months) parts.push(g.duration_months + " tháng");
                    if (g.credits_granted) parts.push("+" + g.credits_granted + " credit");
                    detail = parts.join(", ") || "—";
                } else {
                    detail = (g.days_granted ? "+" + g.days_granted + " ngày" : "—");
                }
                return `<tr>
                    <td>${esc(fmtDate(g.created_at))}</td>
                    <td><span class="au-gift-badge ${badgeClass}">${esc(g.badge || "")}</span></td>
                    <td>${esc(g.plan_name || g.plan_slug || "—")}</td>
                    <td>${esc(detail)}</td>
                    <td>${esc(g.notes || "—")}</td>
                </tr>`;
            }).join("")}</tbody></table></div>`;
    }

    function setSaasGrantMode(mode) {
        saasGrantMode = mode || "paid";
        document.querySelectorAll(".au-grant-mode").forEach((btn) => {
            const active = btn.getAttribute("data-grant-mode") === saasGrantMode;
            btn.classList.toggle("is-active", active);
            btn.setAttribute("aria-selected", active ? "true" : "false");
        });
        syncSaasGrantModeUi();
    }

    function syncSaasGrantModeUi() {
        const paid = document.getElementById("saasPanelPaid");
        const giftPlan = document.getElementById("saasPanelGiftPlan");
        const giftDays = document.getElementById("saasPanelGiftDays");
        const mode = saasGrantMode || "paid";
        if (paid) paid.hidden = mode !== "paid";
        if (giftPlan) giftPlan.hidden = mode !== "gift_plan";
        if (giftDays) giftDays.hidden = mode !== "gift_days";

        const info = document.getElementById("saasGiftDaysInfo");
        const btnDays = document.getElementById("btnSaasGiftDays");
        const elig = saasCache.eligibility || {};
        if (mode === "gift_days" && info) {
            const daysLeft = elig.free_usage_days_remaining || 0;
            if (daysLeft > 0) {
                info.textContent = `User đang có ${daysLeft} ngày sử dụng miễn phí (tặng thêm sẽ cộng dồn).`;
                info.hidden = false;
            } else {
                info.textContent = "Tặng ngày sử dụng miễn phí — không cộng credit, user vẫn cần mua credit để dùng tính năng.";
                info.hidden = false;
            }
        } else if (info) {
            info.hidden = true;
        }
        if (btnDays) btnDays.disabled = false;
    }

    function renderApiTab() {
        const panel = document.getElementById(DETAIL_PANELS.api);
        if (!panel || !currentDetail) return;
        const u = currentDetail.user;
        const isAdminRole = String(u.role || "").toLowerCase() === "admin";
        const apiOn = apiOnForUser(u);
        const poolOn = apiAdminOnForUser(u);

        panel.innerHTML = `
            <section class="au-subcard" id="apiPermsBlock">
                <h4 class="au-subcard-title">API &amp; Quyền</h4>
                ${apiPermsCardsHtml(u, isAdminRole)}
            </section>`;
    }

    function renderDataTab() {
        const panel = document.getElementById(DETAIL_PANELS.data);
        if (!panel || !currentDetail) return;
        const d = currentDetail;

        const sections = [
            {
                title: "SEO Projects",
                rows: d.seo_projects || [],
                cols: [
                    { label: "ID", fn: (r) => r.id },
                    { label: "Domain", fn: (r) => r.domain },
                    { label: "Tạo", fn: (r) => fmtDate(r.created_at) },
                ],
            },
            {
                title: "Content AI",
                rows: d.content_ai_projects || [],
                cols: [
                    { label: "Tiêu đề", fn: (r) => r.title || r.primary_keyword || "—" },
                    { label: "Site", fn: (r) => r.target_website || "—" },
                    { label: "Status", fn: (r) => r.status },
                ],
            },
            {
                title: "Knowledge Base",
                rows: d.knowledge_bases || [],
                cols: [
                    { label: "Tên", fn: (r) => r.name },
                    { label: "Scope", fn: (r) => r.scope },
                    { label: "Docs", fn: (r) => r.doc_count },
                ],
            },
            {
                title: "Bulk Jobs",
                rows: d.bulk_jobs || [],
                cols: [
                    { label: "Job", fn: (r) => r.job_id },
                    { label: "State", fn: (r) => r.state },
                    { label: "KW", fn: (r) => r.keyword_count },
                ],
            },
            {
                title: "API Keys",
                rows: d.api_keys || [],
                cols: [
                    { label: "Tên", fn: (r) => r.name },
                    { label: "Provider", fn: (r) => r.provider_label || r.provider },
                    { label: "Key", fn: (r) => r.api_key_masked || "••••••••" },
                    { label: "On", fn: (r) => (r.enabled ? "yes" : "no") },
                ],
            },
            {
                title: "Publishing Sites",
                rows: d.publishing_sites || [],
                cols: [
                    { label: "Tên", fn: (r) => r.name },
                    { label: "Platform", fn: (r) => r.platform },
                    { label: "URL", fn: (r) => r.url },
                ],
            },
        ];

        panel.innerHTML = sections
            .map((s, i) =>
                renderAccordion(s.title, s.rows.length, renderTable(s.cols, s.rows), i === 0)
            )
            .join("");
    }

    function renderActivityTab() {
        const panel = document.getElementById(DETAIL_PANELS.activity);
        if (!panel || !currentDetail) return;
        panel.innerHTML = `
            <section class="au-subcard">
                <h4 class="au-subcard-title">Nhật ký hoạt động user</h4>
                ${renderTimeline(currentDetail.audit_logs || [])}
            </section>`;
    }

    function switchDetailTab(tab) {
        activeDetailTab = tab;
        document.querySelectorAll("#detailMainTabs .au-dtab").forEach((btn) => {
            btn.classList.toggle("is-active", btn.getAttribute("data-detail-tab") === tab);
        });
        Object.keys(DETAIL_PANELS).forEach((key) => {
            const el = document.getElementById(DETAIL_PANELS[key]);
            if (el) el.classList.toggle("is-active", key === tab);
        });
        if (tab === "saas") {
            renderSaasTab();
            if (!saasCache.sub && !saasCache.error && !saasCache.loading && selectedUserId) {
                loadSaasData(selectedUserId);
            }
        }
    }

    function renderDetailView() {
        renderUserHeader();
        switchDetailTab(activeDetailTab);
        renderOverviewTab();
        renderSaasTab();
        renderApiTab();
        renderDataTab();
        renderCreditTab();
        renderActivityTab();
    }

    function refreshDetailAfterUpdate() {
        renderUserHeader();
        renderOverviewTab();
        renderApiTab();
        renderDataTab();
        renderCreditTab();
        renderActivityTab();
        if (activeDetailTab === "saas") renderSaasTab();
    }

    /* —— SaaS data —— */
    async function loadSaasData(userId) {
        saasCache = { sub: null, usage: null, gifts: null, eligibility: null, error: null, loading: !!userId };
        renderSaasTab();

        if (!userId) {
            saasCache.loading = false;
            renderSaasTab();
            return;
        }

        try {
            const [subR, usageR, giftsR, eligR] = await Promise.all([
                fetch(saasApi("/users/" + userId + "/subscription"), fetchOpts({ headers: headers() })),
                fetch(saasApi("/users/" + userId + "/usage"), fetchOpts({ headers: headers() })),
                fetch(saasApi("/users/" + userId + "/gifts"), fetchOpts({ headers: headers() })),
                fetch(saasApi("/users/" + userId + "/gift-eligibility"), fetchOpts({ headers: headers() })),
            ]);
            const sub = await subR.json().catch(() => ({}));
            const usage = await usageR.json().catch(() => ({}));
            const gifts = await giftsR.json().catch(() => ({}));
            const eligibility = await eligR.json().catch(() => ({}));
            if (!subR.ok) throw new Error(parseApiError(sub, "Không tải subscription SaaS."));
            if (!usageR.ok) throw new Error(parseApiError(usage, "Không tải usage SaaS."));
            saasCache = { sub, usage, gifts, eligibility, error: null, loading: false };
        } catch (e) {
            saasCache = { sub: null, usage: null, gifts: null, eligibility: null, error: e.message || String(e), loading: false };
            showToast(saasCache.error, "error");
        }
        renderSaasTab();
        renderUserHeader();
    }

    function syncSaasGrantCycleUi() {
        const cycleEl = document.getElementById("saasGrantCycle");
        const monthsEl = document.getElementById("saasGrantMonths");
        const hintEl = document.getElementById("saasGrantCycleHint");
        if (!cycleEl) return;
        const cycle = cycleEl.value || "monthly";
        if (monthsEl) {
            if (cycle === "semi_annual") {
                monthsEl.value = "6";
                monthsEl.readOnly = true;
            } else if (cycle === "yearly") {
                monthsEl.value = "14";
                monthsEl.readOnly = true;
            } else {
                monthsEl.readOnly = false;
                if (Number(monthsEl.value) === 6 || Number(monthsEl.value) === 14) {
                    monthsEl.value = "1";
                }
            }
        }
        if (hintEl) {
            if (cycle === "semi_annual") {
                hintEl.textContent = "Đã bao gồm bonus 1 tháng credit";
                hintEl.hidden = false;
            } else if (cycle === "yearly") {
                hintEl.textContent = "Đã bao gồm tặng 2 tháng sử dụng và 2 tháng credit";
                hintEl.hidden = false;
            } else {
                hintEl.hidden = true;
            }
        }
    }

    async function grantSaasSubscription() {
        if (!selectedUserId) {
            showToast("Chọn user trước.", "error");
            return;
        }
        const planEl = document.getElementById("saasGrantPlan");
        const cycleEl = document.getElementById("saasGrantCycle");
        const monthsEl = document.getElementById("saasGrantMonths");
        const notesEl = document.getElementById("saasGrantNotes");
        const btn = document.getElementById("btnSaasGrant");
        if (!planEl || !btn) return;

        await withButtonBusy(btn, async () => {
            try {
                const billingCycle = (cycleEl && cycleEl.value) || "monthly";
                const r = await fetch(
                    saasApi("/users/" + selectedUserId + "/grant-subscription"),
                    fetchOpts({
                        method: "POST",
                        headers: headers(),
                        body: JSON.stringify({
                            plan_slug: planEl.value,
                            billing_cycle: billingCycle,
                            months: parseInt(monthsEl.value, 10) || 1,
                            notes: (notesEl.value || "").trim() || null,
                        }),
                    })
                );
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không gán được gói."));
                showToast("Đã kích hoạt gói " + (data.plan_name || planEl.value), "success");
                await loadSaasData(selectedUserId);
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function grantSaasGiftPlan() {
        if (!selectedUserId) {
            showToast("Chọn user trước.", "error");
            return;
        }
        const planEl = document.getElementById("saasGiftPlan");
        const unitEl = document.getElementById("saasGiftDurationUnit");
        const durEl = document.getElementById("saasGiftDuration");
        const creditEl = document.getElementById("saasGiftIncludeCredit");
        const notesEl = document.getElementById("saasGiftPlanNotes");
        const btn = document.getElementById("btnSaasGiftPlan");
        if (!planEl || !btn) return;

        const val = parseInt(durEl && durEl.value, 10) || 0;
        const unit = (unitEl && unitEl.value) || "days";
        const body = {
            plan_slug: planEl.value,
            include_credit: !!(creditEl && creditEl.checked),
            notes: (notesEl && notesEl.value || "").trim() || null,
        };
        if (unit === "months") body.duration_months = val;
        else body.duration_days = val;

        await withButtonBusy(btn, async () => {
            try {
                const r = await fetch(
                    saasApi("/users/" + selectedUserId + "/gift-plan"),
                    fetchOpts({ method: "POST", headers: headers(), body: JSON.stringify(body) })
                );
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không tặng được gói."));
                const creditMsg = data.credits_granted ? " (+" + data.credits_granted + " credit)" : "";
                showToast("Đã tặng gói " + (data.plan_name || planEl.value) + creditMsg, "success");
                await loadSaasData(selectedUserId);
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function grantSaasGiftDays() {
        if (!selectedUserId) {
            showToast("Chọn user trước.", "error");
            return;
        }
        const daysEl = document.getElementById("saasGiftDays");
        const notesEl = document.getElementById("saasGiftDaysNotes");
        const btn = document.getElementById("btnSaasGiftDays");
        if (!daysEl || !btn) return;

        const days = parseInt(daysEl.value, 10) || 0;
        if (days <= 0) {
            showToast("Số ngày phải > 0.", "error");
            return;
        }

        await withButtonBusy(btn, async () => {
            try {
                const r = await fetch(
                    saasApi("/users/" + selectedUserId + "/gift-usage-days"),
                    fetchOpts({
                        method: "POST",
                        headers: headers(),
                        body: JSON.stringify({
                            days: days,
                            notes: (notesEl && notesEl.value || "").trim() || null,
                        }),
                    })
                );
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không tặng được ngày."));
                showToast("Đã tặng " + days + " ngày sử dụng", "success");
                await loadSaasData(selectedUserId);
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function checkSaasEntitlement() {
        if (!selectedUserId) return;
        const featureEl = document.getElementById("saasFeatureKey");
        const box = document.getElementById("saasEntResult");
        const btn = document.getElementById("btnSaasEntitlement");
        if (!featureEl || !box || !btn) return;

        await withButtonBusy(btn, async () => {
            box.hidden = false;
            box.className = "au-ent-result";
            box.textContent = "Đang kiểm tra…";
            try {
                const params = new URLSearchParams({ feature_key: featureEl.value, quantity: "1" });
                const r = await fetch(
                    saasApi("/users/" + selectedUserId + "/entitlement-check?" + params),
                    fetchOpts({ headers: headers() })
                );
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Lỗi entitlement-check."));
                box.className = "au-ent-result " + (data.allowed ? "ok" : "no");
                box.innerHTML =
                    "<strong>" +
                    (data.allowed ? "Cho phép" : "Từ chối") +
                    "</strong> · <code>" +
                    esc(data.reason_code) +
                    "</code><br>" +
                    esc(data.message);
            } catch (e) {
                box.className = "au-ent-result no";
                box.textContent = e.message || String(e);
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function patchApiAccess(body) {
        if (!selectedUserId) return null;
        const r = await fetch("/admin/api/users/" + selectedUserId + "/api-access", fetchOpts({
            method: "PATCH",
            headers: headers(),
            body: JSON.stringify(body),
        }));
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(parseApiError(data, "Không cập nhật được quyền API."));
        if (currentDetail && data.user) currentDetail.user = data.user;
        return data.user;
    }

    /* —— User list —— */
    function renderUserLists(items) {
        if (!userTableBody || !userCardList) return;

        const source = items || allUserItems;
        const totalPages = Math.max(1, Math.ceil(source.length / PAGE_SIZE));
        if (listPage > totalPages) listPage = totalPages;
        const start = (listPage - 1) * PAGE_SIZE;
        const pageItems = source.slice(start, start + PAGE_SIZE);

        userTableBody.innerHTML = "";
        userCardList.innerHTML = "";

        if (!source.length) {
            if (userTableWrap) userTableWrap.classList.add("is-hidden");
            userCardList.hidden = true;
            userCardList.classList.remove("is-visible");
            if (userListEmpty) userListEmpty.hidden = false;
            const wrap = document.getElementById("userPagination");
            if (wrap) wrap.hidden = true;
            return;
        }

        if (userListEmpty) userListEmpty.hidden = true;
        if (userTableWrap) userTableWrap.classList.remove("is-hidden");
        userCardList.hidden = false;
        userCardList.classList.add("is-visible");

        pageItems.forEach((u) => {
            const selected = selectedUserId === u.id;
            const apiOn = apiOnForUser(u);
            const credit = Number(u.credit_balance || 0).toLocaleString("vi-VN");

            const tr = document.createElement("tr");
            tr.className = "au-row" + (selected ? " is-selected" : "");
            tr.innerHTML = `
                <td class="au-cell-id">${u.id}</td>
                <td class="au-cell-email" title="${esc(u.email)}">${esc(u.email)}</td>
                <td>${roleBadge(u.role)}</td>
                <td>${statusBadge(u.status)}</td>
                <td>${trialBadge(u)}</td>
                <td class="au-cell-api">${apiTableCell(apiOn)}</td>
                <td class="au-cell-credit">${credit}</td>
                <td class="au-cell-actions"><button type="button" class="au-btn au-btn--sm au-btn--primary au-btn-grant-credit" data-user-id="${u.id}">Tặng credit</button></td>`;
            tr.addEventListener("click", () => selectUser(u.id));
            tr.querySelector(".au-btn-grant-credit")?.addEventListener("click", (ev) => {
                ev.stopPropagation();
                openGrantCreditModal(u);
            });
            userTableBody.appendChild(tr);

            const card = document.createElement("button");
            card.type = "button";
            card.className = "au-user-card" + (selected ? " is-selected" : "");
            card.innerHTML = `<p class="au-user-card-email">${esc(u.email)}</p>`;
            card.addEventListener("click", () => selectUser(u.id));
            userCardList.appendChild(card);
        });

        renderPagination();
    }

    async function ensureAdmin() {
        const token = getToken();
        if (!token) {
            if (blockedView) blockedView.hidden = false;
            if (adminApp) adminApp.hidden = true;
            return false;
        }
        try {
            const me = await fetch("/auth/me", fetchOpts({ headers: headers() }));
            if (!me.ok) throw new Error("auth");
            const user = await me.json();
            if (!user.show_admin_nav) throw new Error("not_platform_admin");
            const chk = await fetch("/admin/api/check", fetchOpts({ headers: headers() }));
            if (!chk.ok) throw new Error("admin api");
            if (adminMsg) adminMsg.textContent = "Đăng nhập: " + user.email;
            if (blockedView) blockedView.hidden = true;
            if (adminApp) adminApp.hidden = false;
            return true;
        } catch (_) {
            if (blockedView) blockedView.hidden = false;
            if (adminApp) adminApp.hidden = true;
            return false;
        }
    }

    async function loadUsers(opts) {
        if (usersLoading) return;
        const resetPage = !opts || opts.resetPage !== false;
        setListLoading(true);
        showListError("");

        const q = document.getElementById("filterQ").value.trim();
        const role = document.getElementById("filterRole").value;
        const status = document.getElementById("filterStatus").value;
        const trialStatus = document.getElementById("filterTrialStatus").value;
        const useAdminApi = document.getElementById("filterUseAdminApi").value;
        const params = new URLSearchParams({ limit: "200", segment: "all" });
        if (q) params.set("q", q);
        if (role) params.set("role", role);
        if (status) params.set("status", status);
        if (trialStatus) params.set("trial_status", trialStatus);
        if (useAdminApi) params.set("use_admin_api", useAdminApi);

        try {
            const r = await fetch("/admin/api/users?" + params, fetchOpts({ headers: headers() }));
            const data = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(parseApiError(data, "Không tải được danh sách user."));
            const items = data.items || [];
            allUserItems = items;
            listTotal = data.total != null ? data.total : items.length;
            if (resetPage) listPage = 1;
            updateStats(items, listTotal);
            if (userListMeta) {
                userListMeta.textContent = `Tổng: ${listTotal.toLocaleString("vi-VN")} user`;
            }
            renderUserLists(allUserItems);
        } catch (e) {
            allUserItems = [];
            listTotal = 0;
            if (userTableWrap) userTableWrap.classList.add("is-hidden");
            if (userCardList) {
                userCardList.hidden = true;
                userCardList.classList.remove("is-visible");
            }
            if (userListEmpty) userListEmpty.hidden = true;
            showListError(e.message || String(e));
            showToast(e.message || String(e), "error");
            throw e;
        } finally {
            setListLoading(false);
        }
    }

    async function selectUser(id) {
        selectedUserId = id;
        activeDetailTab = "overview";
        setDetailLoading(true);
        showDetailError("");

        try {
            const r = await fetch("/admin/api/users/" + id, fetchOpts({ headers: headers() }));
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                const msg = parseApiError(data, "Không tải chi tiết user.");
                showDetailError(msg);
                showToast(msg, "error");
                if (detailEmpty) detailEmpty.hidden = false;
                if (detailContent) detailContent.hidden = true;
                selectedUserId = null;
                return;
            }

            currentDetail = data;
            saasCache = { sub: null, usage: null, gifts: null, eligibility: null, error: null, loading: true };
            renderDetailView();
            loadSaasData(id);

            if (detailEmpty) detailEmpty.hidden = true;
            if (detailContent) detailContent.hidden = false;
            await loadUsers({ resetPage: false });
            scrollToDetailOnMobile();
        } catch (e) {
            const msg = e.message || String(e);
            showDetailError(msg);
            showToast(msg, "error");
            if (detailEmpty) detailEmpty.hidden = false;
            if (detailContent) detailContent.hidden = true;
        } finally {
            setDetailLoading(false);
        }
    }

    /* —— Account actions —— */
    async function confirmRoleChange(role, prevRole) {
        if (role === "admin" && prevRole !== "admin") {
            return confirmAction({
                title: "Cấp quyền admin?",
                message: "Chỉ cấp cho người tin cậy.",
                confirmLabel: "Cấp admin",
                danger: true,
            });
        }
        if (prevRole === "admin" && role !== "admin") {
            return confirmAction({
                title: "Hạ quyền admin?",
                message: "User sẽ mất role admin.",
                confirmLabel: "Hạ quyền",
                danger: true,
            });
        }
        return true;
    }

    async function confirmStatusChange(status, email) {
        if (status === "banned") {
            return confirmAction({
                title: "Khóa tài khoản?",
                message: email + " sẽ không đăng nhập được.",
                confirmLabel: "Khóa",
                danger: true,
            });
        }
        if (status === "inactive") {
            return confirmAction({
                title: "Vô hiệu hóa tài khoản?",
                message: email + " sẽ không sử dụng được dịch vụ.",
                confirmLabel: "Vô hiệu hóa",
                danger: true,
            });
        }
        return true;
    }

    async function saveAccountChanges() {
        if (!selectedUserId || !currentDetail) return;
        const btn = document.getElementById("btnSaveAccount");
        const roleEl = document.getElementById("selNewRole");
        const statusEl = document.getElementById("selNewStatus");
        if (!roleEl || !statusEl) return;

        const role = roleEl.value;
        const status = statusEl.value;
        const prevRole = String(currentDetail.user.role || "").toLowerCase();
        const prevStatus = String(currentDetail.user.status || "").toLowerCase();
        const email = currentDetail.user.email || "";

        if (role === prevRole && status === prevStatus) {
            showToast("Không có thay đổi để lưu.", "error");
            return;
        }

        if (role !== prevRole && !(await confirmRoleChange(role, prevRole))) return;
        if (status !== prevStatus && !(await confirmStatusChange(status, email))) return;

        await withButtonBusy(btn, async () => {
            try {
                if (role !== prevRole) {
                    const r = await fetch("/admin/api/users/" + selectedUserId + "/role", fetchOpts({
                        method: "PATCH",
                        headers: headers(),
                        body: JSON.stringify({ role }),
                    }));
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) throw new Error(parseApiError(data, "Lỗi đổi role."));
                }
                if (status !== prevStatus) {
                    const r = await fetch("/admin/api/users/" + selectedUserId + "/status", fetchOpts({
                        method: "PATCH",
                        headers: headers(),
                        body: JSON.stringify({ status }),
                    }));
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) throw new Error(parseApiError(data, "Lỗi cập nhật status."));
                }
                showToast("Đã lưu thay đổi tài khoản", "success");
                await selectUser(selectedUserId);
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function deactivateAccount() {
        if (!selectedUserId || !currentDetail) return;
        const email = currentDetail.user.email || "";
        const ok = await confirmAction({
            title: "Khóa tài khoản?",
            message: email + " sẽ bị vô hiệu hóa và không sử dụng được dịch vụ.",
            confirmLabel: "Khóa ngay",
            danger: true,
        });
        if (!ok) return;

        const btn = document.getElementById("btnDeactivateAccount");
        await withButtonBusy(btn, async () => {
            try {
                const r = await fetch("/admin/api/users/" + selectedUserId + "/status", fetchOpts({
                    method: "PATCH",
                    headers: headers(),
                    body: JSON.stringify({ status: "inactive" }),
                }));
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không khóa được tài khoản."));
                showToast("Đã khóa tài khoản", "success");
                await selectUser(selectedUserId);
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function banAccount() {
        if (!selectedUserId || !currentDetail) return;
        const email = currentDetail.user.email || "";
        const ok = await confirmAction({
            title: "Cấm tài khoản?",
            message: email + " sẽ bị cấm và không đăng nhập được.",
            confirmLabel: "Cấm ngay",
            danger: true,
        });
        if (!ok) return;

        const btn = document.getElementById("btnBanAccount");
        await withButtonBusy(btn, async () => {
            try {
                const r = await fetch("/admin/api/users/" + selectedUserId + "/status", fetchOpts({
                    method: "PATCH",
                    headers: headers(),
                    body: JSON.stringify({ status: "banned" }),
                }));
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không cấm được tài khoản."));
                showToast("Đã cấm tài khoản", "success");
                await selectUser(selectedUserId);
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    async function deleteAccount() {
        if (!selectedUserId || !currentDetail) return;
        const targetId = selectedUserId;
        const email = currentDetail.user.email || "";
        const ok = await confirmAction({
            title: "Xóa user vĩnh viễn?",
            message:
                "Toàn bộ tài khoản và dữ liệu liên quan của " +
                email +
                " sẽ bị xóa. Thao tác này không thể hoàn tác.",
            confirmLabel: "Xóa vĩnh viễn",
            danger: true,
        });
        if (!ok) return;

        const btn = document.getElementById("btnDeleteAccount");
        await withButtonBusy(btn, async () => {
            try {
                const r = await fetch("/admin/api/users/" + targetId, fetchOpts({
                    method: "DELETE",
                    headers: headers(),
                }));
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không xóa được user."));

                selectedUserId = null;
                currentDetail = null;
                saasCache = { sub: null, usage: null, gifts: null, eligibility: null, error: null, loading: false };
                if (detailEmpty) detailEmpty.hidden = false;
                if (detailContent) detailContent.hidden = true;
                showToast(data.message || "Đã xóa user vĩnh viễn.", "success");
                await loadUsers();
                await loadAdminAudit();
            } catch (e) {
                showToast(e.message || String(e), "error");
            }
        });
    }

    function onResetTrial() {
        showToast("Đặt lại trial chưa có API backend.", "error");
    }

    async function onToggleCustomApiKey(ev) {
        if (!selectedUserId || apiToggleBusy || !currentDetail) return;
        const input = ev.target;
        const wanted = input.checked;
        const current = !!currentDetail.user.allow_custom_api_key;
        input.checked = current;

        apiToggleBusy = true;
        renderOverviewTab();
        renderApiTab();
        try {
            await patchApiAccess({ allow_custom_api_key: wanted });
            showToast(wanted ? "Đã bật API key riêng" : "Đã tắt API key riêng", "success");
            refreshDetailAfterUpdate();
            await loadUsers({ resetPage: false });
            await loadAdminAudit();
        } catch (e) {
            showToast(e.message || String(e), "error");
            renderOverviewTab();
            renderApiTab();
        } finally {
            apiToggleBusy = false;
            renderOverviewTab();
            renderApiTab();
        }
    }

    async function onToggleApiAccess(ev) {
        if (!selectedUserId || apiToggleBusy || !currentDetail) return;
        const input = ev.target;
        const wanted = input.checked;
        const current = !!currentDetail.user.api_access_enabled;

        input.checked = current;
        if (!wanted) {
            const ok = await confirmAction({
                title: "Tắt quyền API?",
                message: "User không dùng được LLM/crawl AI. Pool Admin cũng tắt.",
                confirmLabel: "Tắt API",
                danger: true,
            });
            if (!ok) return;
        }

        apiToggleBusy = true;
        renderOverviewTab();
        renderApiTab();
        try {
            const body = { api_access_enabled: wanted };
            if (!wanted) body.use_admin_api_pool = false;
            await patchApiAccess(body);
            showToast(wanted ? "Đã bật quyền API" : "Đã tắt quyền API", "success");
            refreshDetailAfterUpdate();
            await loadUsers({ resetPage: false });
            await loadAdminAudit();
        } catch (e) {
            showToast(e.message || String(e), "error");
            renderOverviewTab();
            renderApiTab();
        } finally {
            apiToggleBusy = false;
            renderOverviewTab();
            renderApiTab();
        }
    }

    async function onToggleAdminPool(ev) {
        if (!selectedUserId || apiToggleBusy || !currentDetail) return;
        const input = ev.target;
        const wanted = input.checked;
        const current = !!currentDetail.user.use_admin_api_pool;

        input.checked = current;
        if (!wanted) {
            const ok = await confirmAction({
                title: "Tắt API Admin pool?",
                message: "User phải dùng API key riêng.",
                confirmLabel: "Tắt pool",
                danger: true,
            });
            if (!ok) return;
        }

        apiToggleBusy = true;
        renderOverviewTab();
        renderApiTab();
        try {
            await patchApiAccess({ use_admin_api_pool: wanted });
            showToast(wanted ? "Đã bật API Admin pool" : "Đã tắt API Admin pool", "success");
            refreshDetailAfterUpdate();
            await loadUsers({ resetPage: false });
            await loadAdminAudit();
        } catch (e) {
            showToast(e.message || String(e), "error");
            renderOverviewTab();
            renderApiTab();
        } finally {
            apiToggleBusy = false;
            renderOverviewTab();
            renderApiTab();
        }
    }

    async function loadAdminAudit() {
        const r = await fetch("/admin/api/audit-logs?limit=80", fetchOpts({ headers: headers() }));
        if (!r.ok) return;
        const data = await r.json();
        const tbody = document.getElementById("adminAuditBody");
        if (!tbody) return;
        tbody.innerHTML = "";
        (data.items || []).forEach((row) => {
            const tr = document.createElement("tr");
            let detail = row.detail_json || "";
            try {
                detail = JSON.stringify(JSON.parse(detail));
            } catch (_) {}
            tr.innerHTML = `
                <td>${fmtDate(row.created_at)}</td>
                <td>${row.user_id ?? "—"}</td>
                <td>${esc(row.action)}</td>
                <td>${esc(detail).slice(0, 120)}</td>`;
            tbody.appendChild(tr);
        });
    }

    function openAddUserModal() {
        const modal = document.getElementById("auAddUserModal");
        const form = document.getElementById("auAddUserForm");
        const errEl = document.getElementById("addUserError");
        if (!modal || !form) return;
        form.reset();
        if (errEl) {
            errEl.textContent = "";
            errEl.hidden = true;
        }
        const roleEl = document.getElementById("addUserRole");
        const statusEl = document.getElementById("addUserStatus");
        const creditsEl = document.getElementById("addUserCredits");
        if (roleEl) roleEl.value = "user";
        if (statusEl) statusEl.value = "active";
        if (creditsEl) creditsEl.value = "0";
        modal.hidden = false;
        const emailEl = document.getElementById("addUserEmail");
        if (emailEl) {
            try {
                emailEl.focus();
            } catch (_) {}
        }
    }

    function closeAddUserModal() {
        const modal = document.getElementById("auAddUserModal");
        if (modal) modal.hidden = true;
    }

    async function submitAddUser(ev) {
        if (ev) ev.preventDefault();
        const errEl = document.getElementById("addUserError");
        const btnSubmit = document.getElementById("auAddUserSubmit");
        const email = (document.getElementById("addUserEmail")?.value || "").trim();
        const password = document.getElementById("addUserPassword")?.value || "";
        const role = document.getElementById("addUserRole")?.value || "user";
        const status = document.getElementById("addUserStatus")?.value || "active";
        const initialCredits = parseInt(document.getElementById("addUserCredits")?.value || "0", 10) || 0;
        const apiAccess = !!document.getElementById("addUserApiAccess")?.checked;
        const adminPool = !!document.getElementById("addUserAdminPool")?.checked;

        if (!email) {
            if (errEl) {
                errEl.textContent = "Vui lòng nhập email.";
                errEl.hidden = false;
            }
            return;
        }
        if (!password || password.length < 8) {
            if (errEl) {
                errEl.textContent = "Mật khẩu cần ít nhất 8 ký tự.";
                errEl.hidden = false;
            }
            return;
        }

        const payload = {
            email,
            password,
            role,
            status,
            api_access_enabled: apiAccess || adminPool,
            use_admin_api_pool: adminPool,
            initial_credits: Math.max(0, initialCredits),
        };

        try {
            await withButtonBusy(btnSubmit, async () => {
                const r = await fetch("/admin/api/users", fetchOpts({
                    method: "POST",
                    headers: headers(),
                    body: JSON.stringify(payload),
                }));
                const data = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(parseApiError(data, "Không tạo được user."));
                closeAddUserModal();
                showToast("Đã tạo user " + email, "success");
                await loadUsers({ resetPage: true });
                await loadAdminAudit();
                const newId = data.user && data.user.id;
                if (newId) await selectUser(newId);
            });
        } catch (e) {
            if (errEl) {
                errEl.textContent = e.message || String(e);
                errEl.hidden = false;
            } else {
                showToast(e.message || String(e), "error");
            }
        }
    }

    function bindEvents() {
        const btnSearch = document.getElementById("btnSearch");
        const filterQ = document.getElementById("filterQ");
        const btnAddUser = document.getElementById("btnAddUser");
        const addUserForm = document.getElementById("auAddUserForm");
        const addUserCancel = document.getElementById("auAddUserCancel");
        const addUserBackdrop = document.getElementById("auAddUserBackdrop");

        if (btnAddUser) {
            btnAddUser.addEventListener("click", openAddUserModal);
        }
        if (addUserForm) {
            addUserForm.addEventListener("submit", submitAddUser);
        }
        if (addUserCancel) {
            addUserCancel.addEventListener("click", closeAddUserModal);
        }
        if (addUserBackdrop) {
            addUserBackdrop.addEventListener("click", closeAddUserModal);
        }

        const grantCreditForm = document.getElementById("auGrantCreditForm");
        const grantCreditCancel = document.getElementById("auGrantCreditCancel");
        const grantCreditBackdrop = document.getElementById("auGrantCreditBackdrop");
        if (grantCreditForm) grantCreditForm.addEventListener("submit", submitGrantCredit);
        if (grantCreditCancel) grantCreditCancel.addEventListener("click", closeGrantCreditModal);
        if (grantCreditBackdrop) grantCreditBackdrop.addEventListener("click", closeGrantCreditModal);
        const grantChatbotForm = document.getElementById("auGrantChatbotCreditForm");
        const grantChatbotCancel = document.getElementById("auGrantChatbotCreditCancel");
        const grantChatbotBackdrop = document.getElementById("auGrantChatbotCreditBackdrop");
        if (grantChatbotForm) grantChatbotForm.addEventListener("submit", submitGrantChatbotCredit);
        if (grantChatbotCancel) grantChatbotCancel.addEventListener("click", closeGrantChatbotCreditModal);
        if (grantChatbotBackdrop) grantChatbotBackdrop.addEventListener("click", closeGrantChatbotCreditModal);

        if (btnSearch) {
            btnSearch.dataset.busyLabel = "Đang tìm…";
            btnSearch.addEventListener("click", () => {
                withButtonBusy(btnSearch, () => loadUsers()).catch(() => {});
            });
        }

        if (filterQ) {
            filterQ.addEventListener("keydown", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    loadUsers().catch(() => {});
                }
            });
        }

        const btnRefresh = document.getElementById("btnRefresh");
        if (btnRefresh) {
            btnRefresh.addEventListener("click", async () => {
                btnRefresh.disabled = true;
                try {
                    await loadUsers({ resetPage: false });
                    await loadAdminAudit();
                    if (selectedUserId) await selectUser(selectedUserId);
                    showToast("Đã làm mới dữ liệu", "success");
                } catch (e) {
                    showToast(e.message || String(e), "error");
                } finally {
                    btnRefresh.disabled = false;
                }
            });
        }

        if (detailContent) {
            detailContent.addEventListener("click", (e) => {
                const tabBtn = e.target.closest(".au-dtab");
                if (tabBtn) {
                    switchDetailTab(tabBtn.getAttribute("data-detail-tab"));
                    return;
                }

                const grantModeBtn = e.target.closest("[data-grant-mode]");
                if (grantModeBtn) {
                    setSaasGrantMode(grantModeBtn.getAttribute("data-grant-mode"));
                    return;
                }

                const giftDaysBtn = e.target.closest("[data-gift-days]");
                if (giftDaysBtn) {
                    const inp = document.getElementById("saasGiftDays");
                    if (inp) inp.value = giftDaysBtn.getAttribute("data-gift-days");
                    return;
                }

                const moreBtn = e.target.closest("[data-action]");
                if (moreBtn) {
                    const action = moreBtn.getAttribute("data-action");
                    if (action === "refresh-user" && selectedUserId) {
                        selectUser(selectedUserId).catch(() => {});
                    } else if (action === "lock-user") {
                        deactivateAccount();
                    } else if (action === "ban-user") {
                        banAccount();
                    } else if (action === "delete-user") {
                        deleteAccount();
                    }
                    return;
                }

                const id = e.target.id;
                if (id === "btnCopyEmail" && currentDetail) {
                    copyEmailToClipboard(currentDetail.user.email);
                } else if (id === "btnSaveAccount") saveAccountChanges();
                else if (id === "btnDeactivateAccount") deactivateAccount();
                else if (id === "btnBanAccount") banAccount();
                else if (id === "btnDeleteAccount") deleteAccount();
                else if (id === "btnResetTrial") onResetTrial();
                else if (id === "btnSaasGrant") grantSaasSubscription();
                else if (id === "btnSaasGiftPlan") grantSaasGiftPlan();
                else if (id === "btnSaasGiftDays") grantSaasGiftDays();
                else if (id === "btnSaasEntitlement") checkSaasEntitlement();
            });

            detailContent.addEventListener("change", (e) => {
                if (e.target.id === "toggleApiAccess") onToggleApiAccess(e);
                else if (e.target.id === "toggleAdminPool") onToggleAdminPool(e);
                else if (e.target.id === "toggleCustomApiKey") onToggleCustomApiKey(e);
                else if (e.target.id === "saasGrantCycle") syncSaasGrantCycleUi();
            });
        }
    }

    async function init() {
        bindEvents();
        const ok = await ensureAdmin();
        if (!ok) return;
        try {
            await loadUsers();
            await loadAdminAudit();
        } catch (_) {}
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
