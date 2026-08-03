(function () {
    "use strict";

    const PAGE_SIZE = 20;
    const state = {
        acc: { offset: 0, total: 0 },
        comm: { offset: 0, total: 0 },
        payout: { offset: 0, total: 0 },
    };
    let rejectCommissionId = null;
    let rejectPayoutId = null;
    let markPayoutId = null;
    let confirmCallback = null;

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function fmtMoney(n) { return Number(n || 0).toLocaleString("vi-VN") + " ₫"; }

    const STATUS_LABELS = {
        active: "Hoạt động", review: "Cần xem xét", suspended: "Tạm khóa",
        pending: "Chờ duyệt", approved: "Đã duyệt", paid: "Đã thanh toán", rejected: "Từ chối",
        cancelled: "Đã hủy", registered: "Đã đăng ký",
        requested: "Đã gửi", processing: "Đang xử lý",
    };
    function statusLabel(s) { return STATUS_LABELS[String(s || "").toLowerCase()] || s; }
    function badge(status) {
        const s = String(status || "").toLowerCase();
        return `<span class="ab-badge ${esc(s)}">${esc(statusLabel(s))}</span>`;
    }

    function attrEsc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
    }
    function readToken() {
        try {
            let t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            const m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
        } catch (_) {}
        return "";
    }
    function authHeaders(extra) {
        const h = Object.assign({}, extra || {});
        const t = readToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }
    async function apiGet(path) {
        const res = await fetch(path, { headers: authHeaders() });
        const data = await res.json().catch(() => ({}));
        if (res.status === 403) throw new Error("Chỉ admin mới truy cập được.");
        if (!res.ok) throw new Error(data.detail || data.message || data.error || "HTTP " + res.status);
        return data;
    }
    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = data.detail;
            const msg = typeof detail === "string"
                ? detail
                : (detail && detail.message) || data.message || data.error || ("HTTP " + res.status);
            throw new Error(msg);
        }
        return data;
    }
    async function apiPut(path, body) {
        const res = await fetch(path, {
            method: "PUT",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.message || data.error || "HTTP " + res.status);
        return data;
    }

    let toastTimer = null;
    function showToast(msg) {
        const el = byId("admToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        el.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            el.classList.remove("is-visible");
            setTimeout(() => { el.hidden = true; }, 300);
        }, 2500);
    }

    function setError(msg) {
        const el = byId("admError");
        if (!el) return;
        if (msg) { el.hidden = false; el.textContent = msg; }
        else { el.hidden = true; el.textContent = ""; }
    }

    function openModal(id) { byId(id).classList.add("open"); }
    function closeModal(id) { byId(id).classList.remove("open"); }

    function confirmAction(title, desc, onOk) {
        byId("admConfirmTitle").textContent = title;
        byId("admConfirmDesc").textContent = desc;
        confirmCallback = onOk;
        openModal("admConfirmModal");
    }

    function renderPager(prefix, offset, total, limit, onPage) {
        const pager = byId(prefix + "Pager");
        const info = byId(prefix + "PagerInfo");
        const prev = byId(prefix + "Prev");
        const next = byId(prefix + "Next");
        if (!pager) return;
        if (total <= 0) { pager.hidden = true; return; }
        pager.hidden = false;
        const from = offset + 1;
        const to = Math.min(offset + limit, total);
        if (info) info.textContent = `Hiển thị ${from}–${to} / ${total}`;
        if (prev) {
            prev.disabled = offset <= 0;
            prev.onclick = () => { if (offset > 0) onPage(offset - limit); };
        }
        if (next) {
            next.disabled = offset + limit >= total;
            next.onclick = () => { if (offset + limit < total) onPage(offset + limit); };
        }
    }

    function fraudType(note) {
        const n = String(note || "").toLowerCase();
        if (n.includes("ip") || n.includes("thiết bị")) return { label: "Trùng IP/thiết bị", danger: true };
        if (n.includes("hoàn") || n.includes("hủy") || n.includes("refund")) return { label: "Nhiều refund/hủy", danger: true };
        if (n.includes("đăng ký") || n.includes("trả phí")) return { label: "Nhiều signup, không paid", danger: false };
        return { label: "Cảnh báo khác", danger: false };
    }

    function setTab(tab) {
        document.querySelectorAll("#admTabs .ab-subtab").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-adm-tab") === tab);
        });
        document.querySelectorAll("[data-adm-panel]").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-adm-panel") === tab);
        });
        setError(null);
        if (tab === "overview") void loadOverview();
        if (tab === "accounts") void loadAccounts();
        if (tab === "commissions") void loadCommissions();
        if (tab === "payouts") void loadPayouts();
        if (tab === "fraud") void loadFraud();
        if (tab === "settings") void loadSettings();
    }

    function openCommissionsForAffiliate(email) {
        const q = String(email || "").trim();
        if (!q) return;
        const search = byId("admCommSearch");
        const status = byId("admCommStatus");
        if (search) search.value = q;
        if (status) status.value = "pending";
        state.comm.offset = 0;
        setTab("commissions");
    }

    async function loadOverview() {
        try {
            const res = await apiGet("/admin/api/affiliate/overview");
            const d = res.data || {};
            const grid = byId("admOverviewStats");
            if (!grid) return;
            const items = [
                { label: "Tổng affiliate", value: d.total_affiliates, cls: "" },
                { label: "Affiliate đang hoạt động", value: d.active_affiliates, cls: "is-highlight" },
                { label: "Tổng click", value: d.total_clicks, cls: "" },
                { label: "Tổng signup", value: d.total_signups, cls: "" },
                { label: "Tổng khách trả phí", value: d.total_paid_users, cls: "" },
                { label: "Commission pending", value: fmtMoney(d.commission_pending), cls: "is-warn is-money" },
                { label: "Commission approved", value: fmtMoney(d.commission_approved), cls: "is-money" },
                { label: "Tổng đã thanh toán", value: fmtMoney(d.commission_paid), cls: "is-purple is-money" },
            ];
            grid.innerHTML = items.map((it) =>
                `<div class="ab-stat ${esc(it.cls)}"><span>${esc(it.label)}</span><strong>${esc(it.value)}</strong></div>`
            ).join("");
        } catch (e) {
            setError(String(e.message || e));
        }
    }

    function accountActions(a) {
        const parts = [];
        parts.push(`<button type="button" class="ab-btn secondary adm-btn-sm" data-view-acc="${a.id}">Chi tiết</button>`);
        if (a.status !== "active") {
            parts.push(`<button type="button" class="ab-btn adm-btn-sm" data-activate-acc="${a.id}">Mở khóa</button>`);
        }
        if (a.status !== "review") {
            parts.push(`<button type="button" class="ab-btn secondary adm-btn-sm" data-review-acc="${a.id}">Cần xem xét</button>`);
        }
        if (a.status !== "suspended") {
            parts.push(`<button type="button" class="ab-btn secondary adm-btn-sm" data-suspend-acc="${a.id}">Tạm khóa</button>`);
        }
        return parts.join("");
    }

    async function loadAccounts() {
        const loading = byId("admAccLoading");
        if (loading) loading.hidden = false;
        setError(null);
        try {
            const q = (byId("admAccSearch") && byId("admAccSearch").value) || "";
            const status = (byId("admAccStatus") && byId("admAccStatus").value) || "";
            const off = state.acc.offset;
            const res = await apiGet(
                `/admin/api/affiliate/accounts?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}&limit=${PAGE_SIZE}&offset=${off}`
            );
            const data = res.data || {};
            const items = data.items || [];
            state.acc.total = data.total || 0;
            const tbody = document.querySelector("#admAccountsTable tbody");
            const cards = byId("admAccountsCards");
            const empty = byId("admAccountsEmpty");
            if (empty) empty.hidden = items.length > 0;
            if (tbody) {
                tbody.innerHTML = items.map((a) => `
                    <tr>
                        <td>
                            <button type="button" class="adm-user-email-link" data-open-commissions="${attrEsc(a.email)}" title="Xem hoa hồng chờ duyệt của affiliate này">
                                ${esc(a.email)}
                            </button>${a.fraud_flag ? ' <span title="Cảnh báo">⚠️</span>' : ""}
                        </td>
                        <td><code>${esc(a.referral_code)}</code></td>
                        <td>${badge(a.status)}</td>
                        <td>${a.clicks}</td>
                        <td>${a.signups}</td>
                        <td>${a.paid_users}</td>
                        <td>${fmtMoney(a.total_commission)}</td>
                        <td class="adm-actions-cell">${accountActions(a)}</td>
                    </tr>`).join("");
                wireAccountActions(tbody);
            }
            if (cards) {
                cards.innerHTML = items.map((a) => `
                    <div class="ab-mcard">
                        <div class="ab-mcard-row">
                            <button type="button" class="adm-user-email-link" data-open-commissions="${attrEsc(a.email)}" title="Xem hoa hồng chờ duyệt của affiliate này">
                                <strong>${esc(a.email)}</strong>
                            </button>
                            ${badge(a.status)}
                        </div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Code</span><code>${esc(a.referral_code)}</code></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Click/Signup/Paid</span><span>${a.clicks}/${a.signups}/${a.paid_users}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Commission</span><strong>${fmtMoney(a.total_commission)}</strong></div>
                        <div class="adm-actions-cell" style="margin-top:8px;">${accountActions(a)}</div>
                    </div>`).join("");
                wireAccountActions(cards);
            }
            renderPager("admAcc", off, state.acc.total, PAGE_SIZE, (o) => { state.acc.offset = o; void loadAccounts(); });
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function wireAccountActions(root) {
        root.querySelectorAll("[data-activate-acc]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-activate-acc");
                confirmAction("Mở khóa affiliate", "Affiliate sẽ hoạt động bình thường và nhận hoa hồng mới.", async () => {
                    await apiPost(`/admin/api/affiliate/accounts/${id}/activate`, {});
                    showToast("Đã mở khóa affiliate.");
                    await loadAccounts();
                });
            });
        });
        root.querySelectorAll("[data-review-acc]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-review-acc");
                confirmAction("Cần xem xét", "Affiliate sẽ chuyển sang trạng thái cần xem xét.", async () => {
                    await apiPost(`/admin/api/affiliate/accounts/${id}/review`, {});
                    showToast("Đã chuyển sang cần xem xét.");
                    await loadAccounts();
                });
            });
        });
        root.querySelectorAll("[data-suspend-acc]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-suspend-acc");
                confirmAction("Tạm khóa affiliate", "Affiliate sẽ bị tạm khóa và không nhận hoa hồng mới.", async () => {
                    await apiPost(`/admin/api/affiliate/accounts/${id}/suspend`, {});
                    showToast("Đã tạm khóa affiliate.");
                    await loadAccounts();
                });
            });
        });
        root.querySelectorAll("[data-view-acc]").forEach((btn) => {
            btn.addEventListener("click", () => void showAccountDetail(btn.getAttribute("data-view-acc")));
        });
        root.querySelectorAll("[data-open-commissions]").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                e.stopPropagation();
                openCommissionsForAffiliate(btn.getAttribute("data-open-commissions"));
            });
        });
    }

    async function showAccountDetail(id) {
        try {
            const res = await apiGet(`/admin/api/affiliate/accounts/${id}`);
            const d = res.data || {};
            const bal = d.balances || {};
            const pi = d.payout_info || {};
            byId("admDetailBody").innerHTML = `
                <dl class="adm-detail-grid">
                    <dt>Email</dt><dd>${esc(d.email)}</dd>
                    <dt>Referral code</dt><dd><code>${esc(d.referral_code)}</code></dd>
                    <dt>Trạng thái</dt><dd>${badge(d.status)}</dd>
                    <dt>Hoa hồng</dt><dd>${d.commission_rate || 30}%</dd>
                    <dt>Click / Signup / Paid</dt><dd>${d.clicks} / ${d.signups} / ${d.paid_users}</dd>
                    <dt>Refund (hủy)</dt><dd>${d.refunds || 0}</dd>
                    <dt>Tổng commission</dt><dd>${fmtMoney(d.total_commission)}</dd>
                    <dt>Pending / Rút được / Đã nhận</dt><dd>${fmtMoney(bal.pending)} / ${fmtMoney(bal.withdrawable)} / ${fmtMoney(bal.paid)}</dd>
                    <dt>Ngân hàng</dt><dd>${esc(pi.bank_name || "—")} · ${esc(pi.bank_account_name || "—")} · ${esc(pi.bank_account_number_masked || "—")}</dd>
                    <dt>Ngày tạo</dt><dd>${esc((d.created_at || "").slice(0, 10))}</dd>
                </dl>
                ${d.fraud_flag ? `<div class="adm-fraud-card"><div class="adm-fraud-type">⚠ Cảnh báo</div>${esc(d.fraud_note)}</div>` : ""}`;
            openModal("admDetailModal");
        } catch (e) {
            alert(String(e.message || e));
        }
    }

    async function loadCommissions() {
        const loading = byId("admCommLoading");
        if (loading) loading.hidden = false;
        try {
            const q = (byId("admCommSearch") && byId("admCommSearch").value) || "";
            const status = (byId("admCommStatus") && byId("admCommStatus").value) || "pending";
            const off = state.comm.offset;
            const res = await apiGet(
                `/admin/api/affiliate/commissions?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}&limit=${PAGE_SIZE}&offset=${off}`
            );
            const data = res.data || {};
            const items = data.items || [];
            state.comm.total = data.total || 0;
            const isPending = status === "pending";
            const tbody = document.querySelector("#admCommTable tbody");
            const cards = byId("admCommCards");
            const empty = byId("admCommEmpty");
            if (empty) empty.hidden = items.length > 0;
            const customerEmail = (c) => esc(c.customer_email || c.customer_masked || "—");
            const rowHtml = (c) => `
                <tr>
                    <td>${esc(c.affiliate_email)}</td>
                    <td>${customerEmail(c)}</td>
                    <td>${esc(c.order_id || "—")}</td>
                    <td>${fmtMoney(c.order_amount)}</td>
                    <td><strong>${fmtMoney(c.commission_amount)}</strong> <span style="color:var(--ab-muted);font-size:0.78rem;">(${c.commission_rate || 30}%)</span></td>
                    <td>${esc((c.created_at || "").slice(0, 10))}</td>
                    <td class="adm-actions-cell">
                        ${isPending ? `
                            <button type="button" class="ab-btn adm-btn-sm" data-approve-comm="${c.id}">Duyệt</button>
                            <button type="button" class="ab-btn secondary adm-btn-sm" data-reject-comm="${c.id}">Từ chối</button>
                        ` : badge(c.status)}
                    </td>
                </tr>`;
            if (tbody) {
                tbody.innerHTML = items.map(rowHtml).join("");
                wireCommissionActions(tbody);
            }
            if (cards) {
                cards.innerHTML = items.map((c) => `
                    <div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${esc(c.affiliate_email)}</strong>${isPending ? "" : badge(c.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Khách</span><span>${customerEmail(c)}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Đơn</span><span>${fmtMoney(c.order_amount)} → <strong>${fmtMoney(c.commission_amount)}</strong></span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Ngày</span><span>${esc((c.created_at || "").slice(0, 10))}</span></div>
                        ${isPending ? `<div class="adm-actions-cell" style="margin-top:8px;">
                            <button type="button" class="ab-btn adm-btn-sm" data-approve-comm="${c.id}">Duyệt</button>
                            <button type="button" class="ab-btn secondary adm-btn-sm" data-reject-comm="${c.id}">Từ chối</button>
                        </div>` : ""}
                    </div>`).join("");
                wireCommissionActions(cards);
            }
            renderPager("admComm", off, state.comm.total, PAGE_SIZE, (o) => { state.comm.offset = o; void loadCommissions(); });
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function wireCommissionActions(root) {
        root.querySelectorAll("[data-approve-comm]").forEach((btn) => {
            btn.addEventListener("click", () => {
                if (btn.disabled) return;
                const id = btn.getAttribute("data-approve-comm");
                confirmAction("Duyệt hoa hồng", "Hoa hồng sẽ chuyển sang trạng thái approved và có thể rút ngay.", async () => {
                    const buttons = document.querySelectorAll(`[data-approve-comm="${id}"]`);
                    buttons.forEach((b) => { b.disabled = true; b.textContent = "Đang duyệt…"; });
                    try {
                        const res = await apiPost(`/admin/api/affiliate/commissions/${id}/approve`, {});
                        const st = (res.data && res.data.status) || "approved";
                        showToast(st === "approved" ? "Đã duyệt hoa hồng — đã cộng vào số dư có thể rút." : "Đã duyệt hoa hồng.");
                        await loadCommissions();
                        await loadOverview();
                    } catch (e) {
                        buttons.forEach((b) => { b.disabled = false; b.textContent = "Duyệt"; });
                        throw e;
                    }
                });
            });
        });
        root.querySelectorAll("[data-reject-comm]").forEach((btn) => {
            btn.addEventListener("click", () => {
                rejectCommissionId = btn.getAttribute("data-reject-comm");
                byId("admRejectReason").value = "";
                openModal("admRejectModal");
            });
        });
    }

    function formatBank(p) {
        if (!p.bank_name && !p.bank_account_name) return "—";
        return `<div class="adm-bank-cell"><strong>${esc(p.bank_name || "")}</strong><br>${esc(p.bank_account_name || "")}<br><span style="color:var(--ab-muted)">${esc(p.bank_account_number || "")}</span></div>`;
    }

    function payoutActions(p) {
        const parts = [];
        if (p.status === "requested") {
            parts.push(`<button type="button" class="ab-btn adm-btn-sm" data-approve-payout="${p.id}">Duyệt</button>`);
            parts.push(`<button type="button" class="ab-btn secondary adm-btn-sm" data-reject-payout="${p.id}">Từ chối</button>`);
        } else if (p.status === "processing") {
            parts.push(`<button type="button" class="ab-btn adm-btn-sm" data-mark-paid="${p.id}" data-amount="${p.amount}" data-email="${attrEsc(p.affiliate_email)}">Đã chuyển khoản</button>`);
            parts.push(`<button type="button" class="ab-btn secondary adm-btn-sm" data-reject-payout="${p.id}">Từ chối</button>`);
        } else {
            parts.push(`<span class="ab-muted-text">${esc(p.transaction_ref || p.note || "—")}</span>`);
        }
        return parts.join("");
    }

    async function loadPayouts() {
        const loading = byId("admPayoutLoading");
        if (loading) loading.hidden = false;
        try {
            const q = (byId("admPayoutSearch") && byId("admPayoutSearch").value) || "";
            const status = (byId("admPayoutStatus") && byId("admPayoutStatus").value) || "";
            const off = state.payout.offset;
            const res = await apiGet(
                `/admin/api/affiliate/payouts?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}&limit=${PAGE_SIZE}&offset=${off}`
            );
            const data = res.data || {};
            const items = data.items || [];
            state.payout.total = data.total || 0;
            const tbody = document.querySelector("#admPayoutTable tbody");
            const cards = byId("admPayoutCards");
            const empty = byId("admPayoutEmpty");
            if (empty) empty.hidden = items.length > 0;
            if (tbody) {
                tbody.innerHTML = items.map((p) => `
                    <tr>
                        <td>${esc(p.affiliate_email)}</td>
                        <td><strong>${fmtMoney(p.amount)}</strong></td>
                        <td>${formatBank(p)}</td>
                        <td>${badge(p.status)}</td>
                        <td>${esc((p.requested_at || "").slice(0, 10))}</td>
                        <td class="adm-actions-cell">${payoutActions(p)}</td>
                    </tr>`).join("");
                wirePayoutActions(tbody);
            }
            if (cards) {
                cards.innerHTML = items.map((p) => `
                    <div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${esc(p.affiliate_email)}</strong>${badge(p.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Số tiền</span><strong>${fmtMoney(p.amount)}</strong></div>
                        <div style="margin:8px 0;">${formatBank(p)}</div>
                        <div class="adm-actions-cell">${payoutActions(p)}</div>
                    </div>`).join("");
                wirePayoutActions(cards);
            }
            renderPager("admPayout", off, state.payout.total, PAGE_SIZE, (o) => { state.payout.offset = o; void loadPayouts(); });
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function wirePayoutActions(root) {
        root.querySelectorAll("[data-approve-payout]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const id = btn.getAttribute("data-approve-payout");
                confirmAction("Duyệt rút tiền", "Xác nhận duyệt yêu cầu rút tiền? Trạng thái chuyển sang Đang xử lý.", async () => {
                    await apiPost(`/admin/api/affiliate/payouts/${id}/approve`, {});
                    showToast("Đã duyệt yêu cầu rút tiền.");
                    await loadPayouts();
                    await loadOverview();
                });
            });
        });
        root.querySelectorAll("[data-mark-paid]").forEach((btn) => {
            btn.addEventListener("click", () => {
                markPayoutId = btn.getAttribute("data-mark-paid");
                const amount = btn.getAttribute("data-amount");
                const email = btn.getAttribute("data-email");
                byId("admPayoutModalDesc").textContent = `Xác nhận đã chuyển ${fmtMoney(amount)} cho ${email}?`;
                byId("admPayoutRef").value = "";
                byId("admPayoutNote").value = "";
                openModal("admPayoutModal");
            });
        });
        root.querySelectorAll("[data-reject-payout]").forEach((btn) => {
            btn.addEventListener("click", () => {
                rejectPayoutId = btn.getAttribute("data-reject-payout");
                byId("admPayoutRejectReason").value = "";
                openModal("admPayoutRejectModal");
            });
        });
    }

    async function loadFraud() {
        const loading = byId("admFraudLoading");
        if (loading) loading.hidden = false;
        try {
            const res = await apiGet("/admin/api/affiliate/fraud-flags");
            const items = (res.data && res.data.items) || [];
            const el = byId("admFraudList");
            const empty = byId("admFraudEmpty");
            if (empty) empty.hidden = items.length > 0;
            if (!el) return;
            el.innerHTML = items.map((f) => {
                const ft = fraudType(f.fraud_note);
                return `
                    <div class="adm-fraud-card ${ft.danger ? "is-danger" : ""}">
                        <div class="adm-fraud-head">
                            <div><strong>${esc(f.email)}</strong> · <code>${esc(f.referral_code)}</code> ${badge(f.status)}</div>
                            <span class="adm-fraud-type">${esc(ft.label)}</span>
                        </div>
                        <p style="margin:0;font-size:0.88rem;line-height:1.45;">${esc(f.fraud_note)}</p>
                        <div class="adm-fraud-stats">
                            <span>Signup: <strong>${f.signups}</strong></span>
                            <span>Paid: <strong>${f.paid_users}</strong></span>
                            <span>Refund/hủy: <strong>${f.refunds}</strong></span>
                        </div>
                        <div class="ab-actions" style="margin-top:10px;">
                            <button type="button" class="ab-btn secondary adm-btn-sm" data-view-acc="${f.affiliate_id}">Xem chi tiết</button>
                        </div>
                    </div>`;
            }).join("");
            wireAccountActions(el);
        } catch (e) {
            setError(String(e.message || e));
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    async function loadSettings() {
        try {
            const res = await apiGet("/admin/api/affiliate/settings");
            const d = res.data || {};
            if (byId("admSetRate")) byId("admSetRate").value = d.default_commission_rate || 30;
            if (byId("admSetCookie")) byId("admSetCookie").value = d.cookie_days || 60;
            if (byId("admSetMinPayout")) byId("admSetMinPayout").value = d.min_payout_amount || 200000;
            if (byId("admSetHold")) byId("admSetHold").value = d.commission_hold_days || 7;
            if (byId("admSetAutoApprove")) byId("admSetAutoApprove").checked = !!d.auto_approve_commissions;
        } catch (e) {
            setError(String(e.message || e));
        }
    }

    function wire() {
        document.querySelectorAll("#admTabs .ab-subtab").forEach((btn) => {
            btn.addEventListener("click", () => setTab(btn.getAttribute("data-adm-tab") || "overview"));
        });

        byId("btnAdmAccSearch").addEventListener("click", () => { state.acc.offset = 0; void loadAccounts(); });
        byId("admAccSearch").addEventListener("keydown", (e) => {
            if (e.key === "Enter") { state.acc.offset = 0; void loadAccounts(); }
        });

        byId("btnAdmCommSearch").addEventListener("click", () => { state.comm.offset = 0; void loadCommissions(); });
        byId("btnAdmPayoutSearch").addEventListener("click", () => { state.payout.offset = 0; void loadPayouts(); });

        byId("btnAdmConfirmCancel").addEventListener("click", () => {
            closeModal("admConfirmModal");
            confirmCallback = null;
        });
        byId("btnAdmConfirmOk").addEventListener("click", async () => {
            const cb = confirmCallback;
            const okBtn = byId("btnAdmConfirmOk");
            if (!cb) {
                closeModal("admConfirmModal");
                return;
            }
            if (okBtn && okBtn.disabled) return;
            if (okBtn) {
                okBtn.disabled = true;
                okBtn.dataset.prevLabel = okBtn.textContent || "";
                okBtn.textContent = "Đang xử lý…";
            }
            try {
                await cb();
                closeModal("admConfirmModal");
                confirmCallback = null;
            } catch (e) {
                alert(String(e.message || e));
            } finally {
                if (okBtn) {
                    okBtn.disabled = false;
                    okBtn.textContent = okBtn.dataset.prevLabel || "Xác nhận";
                }
            }
        });

        byId("btnAdmRejectCancel").addEventListener("click", () => {
            closeModal("admRejectModal");
            rejectCommissionId = null;
        });
        byId("btnAdmRejectConfirm").addEventListener("click", async () => {
            if (!rejectCommissionId) return;
            const reason = byId("admRejectReason").value.trim();
            if (!reason) { alert("Nhập lý do từ chối."); return; }
            try {
                await apiPost(`/admin/api/affiliate/commissions/${rejectCommissionId}/reject`, { reason });
                closeModal("admRejectModal");
                rejectCommissionId = null;
                showToast("Đã từ chối hoa hồng.");
                await loadCommissions();
            } catch (e) {
                alert(String(e.message || e));
            }
        });

        byId("btnAdmPayoutCancel").addEventListener("click", () => {
            closeModal("admPayoutModal");
            markPayoutId = null;
        });
        byId("btnAdmPayoutConfirm").addEventListener("click", async () => {
            if (!markPayoutId) return;
            try {
                await apiPost(`/admin/api/affiliate/payouts/${markPayoutId}/mark-paid`, {
                    transaction_ref: byId("admPayoutRef").value.trim() || null,
                    note: byId("admPayoutNote").value.trim() || null,
                });
                closeModal("admPayoutModal");
                markPayoutId = null;
                showToast("Đã đánh dấu đã chuyển khoản.");
                await loadPayouts();
                await loadOverview();
            } catch (e) {
                alert(String(e.message || e));
            }
        });

        byId("btnAdmPayoutRejectCancel").addEventListener("click", () => {
            closeModal("admPayoutRejectModal");
            rejectPayoutId = null;
        });
        byId("btnAdmPayoutRejectConfirm").addEventListener("click", async () => {
            if (!rejectPayoutId) return;
            const reason = byId("admPayoutRejectReason").value.trim();
            if (!reason) { alert("Nhập lý do từ chối."); return; }
            try {
                await apiPost(`/admin/api/affiliate/payouts/${rejectPayoutId}/reject`, { reason });
                closeModal("admPayoutRejectModal");
                rejectPayoutId = null;
                showToast("Đã từ chối yêu cầu rút tiền.");
                await loadPayouts();
                await loadOverview();
            } catch (e) {
                alert(String(e.message || e));
            }
        });

        byId("btnAdmDetailClose").addEventListener("click", () => closeModal("admDetailModal"));

        byId("admSettingsForm").addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await apiPut("/admin/api/affiliate/settings", {
                    default_commission_rate: parseInt(byId("admSetRate").value, 10) || 30,
                    cookie_days: parseInt(byId("admSetCookie").value, 10) || 60,
                    min_payout_amount: parseInt(byId("admSetMinPayout").value, 10) || 200000,
                    commission_hold_days: parseInt(byId("admSetHold").value, 10) || 7,
                    auto_approve_commissions: byId("admSetAutoApprove").checked,
                });
                showToast("Đã lưu cài đặt.");
            } catch (err) {
                alert(String(err.message || err));
            }
        });

        setTab("overview");
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
    else wire();
})();
