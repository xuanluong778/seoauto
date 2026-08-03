(function () {
    "use strict";

    const PAGE_SIZE = 25;
    const state = { offset: 0, total: 0, currentOrderId: null };

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function fmtMoney(n) { return Number(n || 0).toLocaleString("vi-VN") + " ₫"; }
    function fmtDt(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit",
            });
        } catch (_) { return "—"; }
    }

    const STATUS_LABELS = {
        pending: "Chờ TT",
        paid: "Đã TT",
        expired: "Hết hạn",
        partial_paid: "TT một phần",
        cancelled: "Đã hủy",
        activation_failed: "Lỗi kích hoạt",
        activated: "Đã kích hoạt",
    };

    function statusLabel(s) { return STATUS_LABELS[String(s || "").toLowerCase()] || s; }
    function badge(status) {
        const s = String(status || "").toLowerCase();
        return `<span class="ab-badge ${esc(s)}">${esc(statusLabel(s))}</span>`;
    }
    function statusStack(row) {
        const parts = [badge(row.status)];
        if (row.activation_status) parts.push(badge(row.activation_status));
        return `<div class="adm-bill-status-stack">${parts.join("")}</div>`;
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
        if (!res.ok) {
            const d = data.detail;
            if (typeof d === "object" && d && d.message) throw new Error(String(d.message));
            throw new Error(typeof d === "string" ? d : data.message || "HTTP " + res.status);
        }
        return data;
    }
    async function apiPost(path) {
        const res = await fetch(path, { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }), body: "{}" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const d = data.detail;
            if (typeof d === "object" && d && d.message) throw new Error(String(d.message));
            throw new Error(typeof d === "string" ? d : data.message || "HTTP " + res.status);
        }
        return data;
    }

    let toastTimer = null;
    function showToast(msg) {
        const el = byId("abToast");
        if (!el) return;
        el.textContent = msg;
        el.hidden = false;
        el.classList.add("is-visible");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            el.classList.remove("is-visible");
            setTimeout(() => { el.hidden = true; }, 300);
        }, 2400);
    }

    function rowActions(row) {
        const parts = [`<button type="button" class="ab-btn secondary ab-btn-sm" data-bill-view="${row.id}">Chi tiết</button>`];
        if (row.status === "paid" && row.activation_status === "activation_failed") {
            parts.push(`<button type="button" class="ab-btn ab-btn-sm" data-bill-retry="${row.id}">Retry activation</button>`);
        }
        if (row.status !== "paid" && row.status !== "cancelled") {
            parts.push(`<button type="button" class="ab-btn ab-btn-sm" data-bill-mark-paid="${row.id}">Mark paid</button>`);
            parts.push(`<button type="button" class="ab-btn secondary ab-btn-sm" data-bill-cancel="${row.id}">Cancel</button>`);
        }
        return `<div class="adm-bill-actions">${parts.join("")}</div>`;
    }

    function renderPager() {
        const pager = byId("admBillPager");
        if (!pager) return;
        if (state.total <= PAGE_SIZE) { pager.hidden = true; return; }
        pager.hidden = false;
        const page = Math.floor(state.offset / PAGE_SIZE) + 1;
        const pages = Math.ceil(state.total / PAGE_SIZE);
        pager.innerHTML = `
            <span>Trang ${page}/${pages} · ${state.total} đơn</span>
            <button type="button" class="ab-btn secondary adm-btn-sm" data-bill-page="prev" ${state.offset <= 0 ? "disabled" : ""}>Trước</button>
            <button type="button" class="ab-btn secondary adm-btn-sm" data-bill-page="next" ${state.offset + PAGE_SIZE >= state.total ? "disabled" : ""}>Sau</button>`;
        pager.querySelectorAll("[data-bill-page]").forEach((btn) => {
            btn.addEventListener("click", () => {
                if (btn.getAttribute("data-bill-page") === "prev" && state.offset > 0) {
                    state.offset = Math.max(0, state.offset - PAGE_SIZE);
                } else if (btn.getAttribute("data-bill-page") === "next" && state.offset + PAGE_SIZE < state.total) {
                    state.offset += PAGE_SIZE;
                }
                void loadOrders();
            });
        });
    }

    function wireRowActions(root) {
        if (!root) return;
        root.querySelectorAll("[data-bill-view]").forEach((btn) => {
            btn.addEventListener("click", () => void showDetail(btn.getAttribute("data-bill-view")));
        });
        root.querySelectorAll("[data-bill-retry]").forEach((btn) => {
            btn.addEventListener("click", () => void doRetry(btn.getAttribute("data-bill-retry")));
        });
        root.querySelectorAll("[data-bill-mark-paid]").forEach((btn) => {
            btn.addEventListener("click", () => void doMarkPaid(btn.getAttribute("data-bill-mark-paid")));
        });
        root.querySelectorAll("[data-bill-cancel]").forEach((btn) => {
            btn.addEventListener("click", () => void doCancel(btn.getAttribute("data-bill-cancel")));
        });
    }

    async function loadOrders() {
        const loading = byId("admBillLoading");
        const err = byId("admBillError");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        try {
            const q = (byId("admBillSearch") && byId("admBillSearch").value.trim()) || "";
            const status = (byId("admBillStatus") && byId("admBillStatus").value) || "";
            const res = await apiGet(
                `/admin/api/billing/payment-orders?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}&limit=${PAGE_SIZE}&offset=${state.offset}`
            );
            state.total = Number(res.total || 0);
            const items = res.items || [];
            const tbody = document.querySelector("#admBillTable tbody");
            const cards = byId("admBillCards");
            const empty = byId("admBillEmpty");
            const wrap = byId("admBillTableWrap");
            if (empty) empty.hidden = items.length > 0;
            if (wrap) wrap.hidden = items.length === 0;
            if (cards) cards.hidden = items.length === 0;

            if (tbody) {
                tbody.innerHTML = items.map((row) => `
                    <tr>
                        <td>${esc(row.id)}</td>
                        <td><div>${esc(row.user_email)}</div><span class="ab-muted-text">#${esc(row.user_id)}</span></td>
                        <td><code>${esc(row.order_code || "—")}</code></td>
                        <td><div>${esc(row.product_name)}</div><span class="ab-muted-text">${esc(row.product_code)}</span></td>
                        <td><strong>${fmtMoney(row.amount)}</strong></td>
                        <td>${statusStack(row)}</td>
                        <td>${esc(fmtDt(row.created_at))}</td>
                        <td>${esc(fmtDt(row.paid_at))}</td>
                        <td>${esc(row.sepay_transaction_count || 0)}</td>
                        <td>${rowActions(row)}</td>
                    </tr>`).join("");
                wireRowActions(tbody);
            }
            if (cards) {
                cards.innerHTML = items.map((row) => `
                    <div class="ab-mcard">
                        <div class="ab-mcard-row"><strong><code>${esc(row.order_code)}</code></strong>${statusStack(row)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">User</span><span>${esc(row.user_email)} (#${row.user_id})</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Product</span><span>${esc(row.product_name)}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Số tiền</span><strong>${fmtMoney(row.amount)}</strong></div>
                        ${rowActions(row)}
                    </div>`).join("");
                wireRowActions(cards);
            }
            renderPager();
        } catch (e) {
            if (err) { err.hidden = false; err.textContent = String(e.message || e); }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function renderSepayList(txs) {
        if (!txs || !txs.length) {
            return '<p class="ab-muted-text">Chưa có giao dịch SePay liên kết.</p>';
        }
        return `<div class="adm-bill-sepay-list">${txs.map((tx) => {
            const raw = typeof tx.raw_payload === "string"
                ? tx.raw_payload
                : JSON.stringify(tx.raw_payload, null, 2);
            return `
                <details class="adm-bill-sepay-card">
                    <summary>${esc(tx.sepay_transaction_id)} · ${fmtMoney(tx.transfer_amount)} · ${esc(fmtDt(tx.created_at))}</summary>
                    <dl class="adm-bill-detail-grid" style="margin-top:8px;">
                        <dt>Loại</dt><dd>${esc(tx.transfer_type || "—")}</dd>
                        <dt>STK nhận</dt><dd>${esc(tx.account_number || "—")}</dd>
                        <dt>Nội dung</dt><dd>${esc(tx.content || "—")}</dd>
                    </dl>
                    <div class="ab-muted-text" style="font-size:0.78rem;margin-top:6px;">Raw webhook payload</div>
                    <pre class="adm-bill-raw">${esc(raw)}</pre>
                </details>`;
        }).join("")}</div>`;
    }

    function renderDetailActions(row) {
        const parts = [];
        if (row.status === "paid" && row.activation_status === "activation_failed") {
            parts.push(`<button type="button" class="ab-btn" data-bill-retry="${row.id}">Retry activation</button>`);
        }
        if (row.status !== "paid" && row.status !== "cancelled") {
            parts.push(`<button type="button" class="ab-btn" data-bill-mark-paid="${row.id}">Mark paid thủ công</button>`);
            parts.push(`<button type="button" class="ab-btn secondary" data-bill-cancel="${row.id}">Cancel order</button>`);
        }
        return parts.join("");
    }

    async function showDetail(orderId) {
        if (!orderId) return;
        state.currentOrderId = orderId;
        try {
            const row = await apiGet(`/admin/api/billing/payment-orders/${orderId}`);
            const body = byId("admBillDetailBody");
            const actions = byId("admBillDetailActions");
            const title = byId("admBillDetailTitle");
            if (title) title.textContent = `Đơn ${row.order_code || row.id}`;
            if (body) {
                body.innerHTML = `
                    <dl class="adm-bill-detail-grid">
                        <dt>User</dt><dd>${esc(row.user_email)} <span class="ab-muted-text">(#${row.user_id})</span></dd>
                        <dt>Order code</dt><dd><code>${esc(row.order_code)}</code></dd>
                        <dt>Product</dt><dd>${esc(row.product_name)} <span class="ab-muted-text">(${esc(row.product_code)})</span></dd>
                        <dt>Số tiền</dt><dd>${fmtMoney(row.amount)}</dd>
                        <dt>Trạng thái</dt><dd>${statusStack(row)}</dd>
                        <dt>Activation error</dt><dd>${esc(row.activation_error || "—")}</dd>
                        <dt>Tạo lúc</dt><dd>${esc(fmtDt(row.created_at))}</dd>
                        <dt>Thanh toán</dt><dd>${esc(fmtDt(row.paid_at))}</dd>
                        <dt>Hết hạn</dt><dd>${esc(fmtDt(row.expired_at))}</dd>
                        <dt>Ngân hàng</dt><dd>${esc(row.bank_code)} · ${esc(row.bank_account)} · ${esc(row.bank_holder)}</dd>
                    </dl>
                    <h4 class="ab-section-title">Giao dịch SePay (${esc(row.sepay_transactions ? row.sepay_transactions.length : 0)})</h4>
                    ${renderSepayList(row.sepay_transactions)}`;
            }
            if (actions) {
                actions.innerHTML = renderDetailActions(row);
                wireRowActions(actions);
            }
            const modal = byId("admBillDetailModal");
            if (modal) { modal.hidden = false; modal.classList.add("is-open"); }
        } catch (e) {
            alert(String(e.message || e));
        }
    }

    function closeDetail() {
        const modal = byId("admBillDetailModal");
        if (modal) { modal.classList.remove("is-open"); modal.hidden = true; }
        state.currentOrderId = null;
    }

    async function doRetry(orderId) {
        if (!orderId || !window.confirm("Retry kích hoạt sản phẩm cho đơn này?")) return;
        try {
            const res = await apiPost(`/admin/api/billing/payment-orders/${orderId}/retry-activation`);
            showToast(res.message || "Đã retry activation.");
            await loadOrders();
            if (String(state.currentOrderId) === String(orderId)) await showDetail(orderId);
        } catch (e) { alert(String(e.message || e)); }
    }

    async function doMarkPaid(orderId) {
        if (!orderId || !window.confirm("Đánh dấu đơn đã thanh toán thủ công và kích hoạt sản phẩm?")) return;
        try {
            const res = await apiPost(`/admin/api/billing/payment-orders/${orderId}/mark-paid`);
            showToast(res.message || "Đã mark paid.");
            await loadOrders();
            if (String(state.currentOrderId) === String(orderId)) await showDetail(orderId);
        } catch (e) { alert(String(e.message || e)); }
    }

    async function doCancel(orderId) {
        if (!orderId || !window.confirm("Hủy đơn hàng này?")) return;
        try {
            const res = await apiPost(`/admin/api/billing/payment-orders/${orderId}/cancel`);
            showToast(res.message || "Đã hủy đơn.");
            await loadOrders();
            closeDetail();
        } catch (e) { alert(String(e.message || e)); }
    }

    function wire() {
        const searchBtn = byId("btnAdmBillSearch");
        const refreshBtn = byId("btnAdmBillRefresh");
        const searchInput = byId("admBillSearch");
        const statusSel = byId("admBillStatus");
        if (searchBtn) searchBtn.addEventListener("click", () => { state.offset = 0; void loadOrders(); });
        if (refreshBtn) refreshBtn.addEventListener("click", () => void loadOrders());
        if (statusSel) statusSel.addEventListener("change", () => { state.offset = 0; void loadOrders(); });
        if (searchInput) {
            let timer = null;
            searchInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter") { state.offset = 0; void loadOrders(); }
            });
            searchInput.addEventListener("input", () => {
                clearTimeout(timer);
                timer = setTimeout(() => { state.offset = 0; void loadOrders(); }, 400);
            });
        }
        const closeBtn = byId("btnAdmBillDetailClose");
        if (closeBtn) closeBtn.addEventListener("click", closeDetail);
        const modal = byId("admBillDetailModal");
        if (modal) {
            modal.addEventListener("click", (e) => {
                if (e.target === modal) closeDetail();
            });
        }
        void loadOrders();
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
    else wire();
})();
