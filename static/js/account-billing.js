(function () {
    "use strict";

    function byId(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function fmtMoney(n) {
        return Number(n || 0).toLocaleString("vi-VN") + " ₫";
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
        const res = await fetch(path, { headers: authHeaders(), cache: "no-store" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || data.error || "HTTP " + res.status);
        return data;
    }
    async function apiPost(path, body) {
        const res = await fetch(path, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
            cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const d = data.detail;
            if (typeof d === "object" && d && d.message) throw new Error(String(d.message));
            throw new Error(typeof d === "string" ? d : data.message || data.error || "HTTP " + res.status);
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

    const STATUS_LABELS = {
        active: "Hoạt động",
        review: "Cần xem xét",
        suspended: "Tạm khóa",
        pending: "Chờ duyệt",
        approved: "Đã duyệt",
        paid: "Đã thanh toán",
        rejected: "Từ chối",
        cancelled: "Đã hủy",
        registered: "Đã đăng ký",
        requested: "Đã gửi",
        processing: "Đang xử lý",
    };

    function statusLabel(status) {
        const s = String(status || "").toLowerCase();
        return STATUS_LABELS[s] || s;
    }

    function badge(status) {
        const s = String(status || "").toLowerCase();
        return `<span class="ab-badge ${esc(s)}">${esc(statusLabel(s))}</span>`;
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
        }, 2200);
    }

    async function copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (_) {
            const ta = document.createElement("textarea");
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            ta.remove();
            return true;
        }
    }

    let affOverview = null;
    const affLoaded = { referrals: false, commissions: false, payouts: false, adminReg: false, adminPayout: false };
    const adminRegState = { offset: 0, total: 0 };
    const adminPayoutState = { offset: 0, total: 0 };
    const ADMIN_REG_PAGE = 20;
    const ADMIN_PAYOUT_PAGE = 20;
    let isAffiliateAdmin = false;
    let markAdminPayoutId = null;
    let rejectAdminPayoutId = null;

    let billingCatalogRef = null;
    let billingOverviewRef = null;
    let plansBillingModeRef = "monthly";
    let paymentPollTimer = null;
    let currentCheckoutProductCode = null;
    let currentPaymentOrderCode = null;
    const PAYMENT_POLL_MS = 4000;
    const paymentFlow = () => window.DigiSeoPaymentFlow || {};

    function redirectToPaymentSuccess(orderCode, order) {
        stopPaymentPoll();
        closePaymentModal();
        if (paymentFlow().redirectToPaymentSuccess) {
            paymentFlow().redirectToPaymentSuccess(orderCode, order);
        } else {
            window.location.assign(
                "/account-billing/payment-success?order_code=" + encodeURIComponent(orderCode)
            );
        }
    }

    function isOrderPaymentSuccess(order) {
        if (paymentFlow().isPaymentSuccess) return paymentFlow().isPaymentSuccess(order);
        const status = String(order.status || "");
        const pollStatus = String(order.poll_status || status);
        const activation = String(order.activation_status || "");
        return pollStatus === "success" || (status === "paid" && activation === "activated");
    }

    function stopPaymentPoll() {
        if (paymentPollTimer) {
            clearInterval(paymentPollTimer);
            paymentPollTimer = null;
        }
    }

    function resetPaymentModalPanels() {
        ["abPaymentLoading", "abPaymentContent", "abPaymentSuccess", "abPaymentExpired", "abPaymentContact", "abPaymentError"].forEach((id) => {
            const el = byId(id);
            if (el) el.hidden = true;
        });
    }

    function openPaymentModal() {
        const modal = byId("abPaymentModal");
        if (!modal) return;
        resetPaymentModalPanels();
        if (byId("abPaymentLoading")) byId("abPaymentLoading").hidden = false;
        modal.hidden = false;
        modal.classList.add("is-open");
        document.body.style.overflow = "hidden";
    }

    function closePaymentModal() {
        stopPaymentPoll();
        const modal = byId("abPaymentModal");
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.hidden = true;
        document.body.style.overflow = "";
        currentPaymentOrderCode = null;
    }

    function fmtPaymentExpire(iso) {
        if (!iso) return "";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit",
            });
        } catch (_) {
            return "";
        }
    }

    function paymentBreakdown(order) {
        const raw = order || {};
        const pctRaw = raw.vat_percent != null ? Number(raw.vat_percent) : 10;
        const vatPct = Number.isFinite(pctRaw) && pctRaw >= 0 ? pctRaw : 10;
        const total = Number(raw.amount);
        let base = raw.base_amount != null ? Number(raw.base_amount) : NaN;
        let vat = raw.vat_amount != null ? Number(raw.vat_amount) : NaN;
        if ((!Number.isFinite(base) || !Number.isFinite(vat)) && Number.isFinite(total) && total > 0) {
            if (vatPct > 0) {
                base = Math.round(total / (1 + vatPct / 100));
                vat = total - base;
            } else {
                base = total;
                vat = 0;
            }
        }
        if (!Number.isFinite(base)) base = 0;
        if (!Number.isFinite(vat)) vat = 0;
        const finalTotal = Number.isFinite(total) && total > 0 ? total : base + vat;
        return { base, vat, total: finalTotal, vatPct };
    }

    function showPaymentPending(order) {
        resetPaymentModalPanels();
        const content = byId("abPaymentContent");
        if (content) content.hidden = false;

        const productName = order.product_name || order.product_code || "—";
        const breakdown = paymentBreakdown(order);
        const baseAmount = fmtMoney(breakdown.base);
        const vatAmount = fmtMoney(breakdown.vat);
        const totalAmount = fmtMoney(breakdown.total);
        const vatPct = String(breakdown.vatPct);
        const bankCode = order.bank_code || "—";
        const bankHolder = order.bank_holder || "—";
        const bankAccount = order.bank_account || "—";
        const transfer = order.transfer_content || order.order_code || "—";

        if (byId("abPayProductName")) byId("abPayProductName").textContent = productName;
        if (byId("abPayBase")) byId("abPayBase").textContent = baseAmount;
        if (byId("abPayVat")) byId("abPayVat").textContent = vatAmount;
        if (byId("abPayVatPct")) byId("abPayVatPct").textContent = vatPct;
        if (byId("abPayAmount")) byId("abPayAmount").textContent = totalAmount;
        if (byId("abPayBank")) byId("abPayBank").textContent = bankCode;
        if (byId("abPayHolder")) byId("abPayHolder").textContent = bankHolder;
        if (byId("abPayAccount")) byId("abPayAccount").textContent = bankAccount;
        if (byId("abPayTransfer")) byId("abPayTransfer").textContent = transfer;

        const qrWrap = byId("abPayQrWrap");
        const qrImg = byId("abPayQrImg");
        if (order.qr_url && qrWrap && qrImg) {
            qrImg.src = order.qr_url;
            qrWrap.hidden = false;
        } else if (qrWrap) {
            qrWrap.hidden = true;
        }

        const statusEl = byId("abPayStatus");
        const statusText = byId("abPayStatusText");
        if (statusEl) {
            statusEl.classList.remove("is-paid", "is-expired");
        }
        if (statusText) statusText.textContent = "Đang chờ thanh toán… Hệ thống tự xác nhận sau vài phút.";

        const expireEl = byId("abPayExpire");
        if (expireEl) {
            const exp = fmtPaymentExpire(order.expired_at);
            expireEl.textContent = exp ? `Đơn hết hạn lúc ${exp}.` : "";
        }
    }

    function showPaymentSuccess(order) {
        resetPaymentModalPanels();
        const panel = byId("abPaymentSuccess");
        if (panel) panel.hidden = false;
        const detail = byId("abPaySuccessDetail");
        if (detail) {
            const name = order.product_name || order.product_code || "";
            detail.textContent = name
                ? `${name} · ${order.order_code || ""}`.trim()
                : "Cảm ơn bạn! Tài khoản sẽ được cập nhật trong giây lát.";
        }
        billingOverviewRef = null;
        void loadBillingOverview(true);
        void loadPlans();
        if (typeof window.refreshDigiSeoNavAccount === "function") {
            window.refreshDigiSeoNavAccount();
        }
        window.dispatchEvent(new CustomEvent("digiseo-credit-purchased"));
    }

    function showPaymentPartial(order) {
        resetPaymentModalPanels();
        const err = byId("abPaymentError");
        if (err) {
            err.hidden = false;
            const need = order.amount != null ? Number(order.amount).toLocaleString("vi-VN") : "";
            err.textContent = need
                ? `Đã nhận chuyển khoản thiếu tiền (cần ${need}₫). Vui lòng chuyển đủ hoặc liên hệ hỗ trợ.`
                : "Đã nhận chuyển khoản thiếu tiền. Vui lòng chuyển đủ hoặc liên hệ hỗ trợ.";
        }
    }

    function showPaymentActivationFailed(order) {
        resetPaymentModalPanels();
        const err = byId("abPaymentError");
        if (err) {
            err.hidden = false;
            err.textContent =
                "Thanh toán đã nhận nhưng kích hoạt gói/credit chưa xong. Hệ thống sẽ xử lý hoặc admin sẽ kích hoạt lại sớm.";
        }
        billingOverviewRef = null;
        void loadBillingOverview(true);
    }

    function showPaymentExpired() {
        resetPaymentModalPanels();
        const panel = byId("abPaymentExpired");
        if (panel) panel.hidden = false;
    }

    function showPaymentContact(message) {
        resetPaymentModalPanels();
        const panel = byId("abPaymentContact");
        const msg = byId("abPayContactMsg");
        if (panel) panel.hidden = false;
        if (msg) msg.textContent = message || "Vui lòng liên hệ hỗ trợ để được tư vấn gói này.";
    }

    function showPaymentError(message) {
        resetPaymentModalPanels();
        const err = byId("abPaymentError");
        if (err) {
            err.hidden = false;
            err.textContent = message || "Không thể tạo đơn thanh toán.";
        }
    }

    async function pollPaymentOrder(orderCode) {
        if (!orderCode) return;
        try {
            const order = await apiGet(`/api/saas/payment-orders/${encodeURIComponent(orderCode)}/status`);
            const status = String(order.status || "");
            const pollStatus = String(order.poll_status || status);
            const activation = String(order.activation_status || "");

            if (status === "paid" && activation === "activation_failed") {
                stopPaymentPoll();
                showPaymentActivationFailed(order);
                return;
            }
            if (isOrderPaymentSuccess(order) || pollStatus === "success") {
                stopPaymentPoll();
                showToast("Thanh toán thành công!");
                redirectToPaymentSuccess(orderCode, order);
                return;
            }
            if (status === "partial_paid") {
                stopPaymentPoll();
                showPaymentPartial(order);
                return;
            }
            if (status === "expired" || status === "cancelled" || pollStatus === "failed") {
                stopPaymentPoll();
                showPaymentExpired();
                return;
            }
        } catch (_) {
            /* keep polling */
        }
    }

    function startPaymentPoll(orderCode) {
        stopPaymentPoll();
        currentPaymentOrderCode = orderCode;
        void pollPaymentOrder(orderCode);
        paymentPollTimer = setInterval(() => {
            void pollPaymentOrder(orderCode);
        }, PAYMENT_POLL_MS);
    }

    async function resumePendingCheckout(orderCode) {
        const code = String(orderCode || "").trim();
        if (!code) return;
        try {
            const order = await apiGet(`/api/saas/payment-orders/${encodeURIComponent(code)}/status`);
            if (isOrderPaymentSuccess(order)) {
                redirectToPaymentSuccess(code, order);
                return;
            }
            if (paymentFlow().isPaymentFailed && paymentFlow().isPaymentFailed(order)) {
                return;
            }
            const full = await apiGet(`/api/saas/payment-orders/${encodeURIComponent(code)}`);
            const pending = Object.assign({}, full, order, {
                transfer_content: code,
                product_name: order.product_name || order.product_code,
            });
            currentPaymentOrderCode = code;
            openPaymentModal();
            showPaymentPending(pending);
            startPaymentPoll(code);
        } catch (_) {
            /* ignore invalid resume */
        }
    }

    async function startCheckout(productCode) {
        const code = String(productCode || "").trim();
        if (!code) {
            showToast("Không xác định được sản phẩm.");
            return;
        }
        currentCheckoutProductCode = code;
        openPaymentModal();
        try {
            const res = await apiPost("/api/saas/create-payment-order", { product_code: code });
            if (res.contact_sales) {
                showPaymentContact(res.message || "Gói này cần liên hệ bộ phận kinh doanh.");
                return;
            }
            if (!res.order_code) {
                showPaymentError(res.message || "Không tạo được đơn thanh toán.");
                return;
            }
            if (paymentFlow().rememberPendingOrder) {
                paymentFlow().rememberPendingOrder(res.order_code);
            }
            const status = await apiGet(
                `/api/saas/payment-orders/${encodeURIComponent(res.order_code)}/status`
            );
            if (isOrderPaymentSuccess(status)) {
                redirectToPaymentSuccess(res.order_code, status);
                return;
            }
            showPaymentPending(res);
            startPaymentPoll(res.order_code);
        } catch (e) {
            showPaymentError(String(e.message || e));
        }
    }

    function fmtDateShort(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
        } catch (_) {
            return "—";
        }
    }

    function fmtDateTime(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
            });
        } catch (_) {
            return "—";
        }
    }

    function renderAlertList(container, alerts, compact) {
        if (!container) return;
        const rows = Array.isArray(alerts) ? alerts : [];
        if (!rows.length) {
            container.hidden = true;
            container.innerHTML = "";
            return;
        }
        container.hidden = false;
        container.innerHTML = rows.map((a) => {
            const level = String(a.level || "info").toLowerCase();
            return `<div class="ab-alert is-${esc(level)}${compact ? " is-compact" : ""}" role="status">${esc(a.message || "")}</div>`;
        }).join("");
    }

    function renderQuotaBars(container, quotas, emptyEl) {
        if (!container) return;
        const rows = (quotas || []).filter((q) => q && q.limit > 0);
        if (!rows.length) {
            container.innerHTML = "";
            if (emptyEl) emptyEl.hidden = false;
            return;
        }
        if (emptyEl) emptyEl.hidden = true;
        container.innerHTML = rows.map((q) => {
            const pct = Math.min(100, Math.max(0, Number(q.percent_used || 0)));
            const warn = q.warning ? " is-warn" : "";
            const barClass = pct >= 90 ? " is-danger" : (pct >= 70 ? " is-warn" : "");
            return `
                <div class="ab-quota-row${warn}">
                    <div class="ab-quota-head">
                        <span class="ab-quota-label">${esc(q.label || q.key || "")}</span>
                        <span class="ab-quota-meta">${esc(Number(q.used || 0).toLocaleString("vi-VN"))} / ${esc(Number(q.limit || 0).toLocaleString("vi-VN"))}</span>
                    </div>
                    <div class="ab-quota-bar${barClass}" role="progressbar" aria-valuenow="${esc(String(pct))}" aria-valuemin="0" aria-valuemax="100">
                        <span style="width:${esc(String(pct))}%"></span>
                    </div>
                    <div class="ab-quota-foot">Còn ${esc(Number(q.remaining || 0).toLocaleString("vi-VN"))} trong tháng</div>
                </div>
            `;
        }).join("");
    }

    function renderBillingOverview(data) {
        if (!data) return;
        const body = byId("abOverviewBody");
        const sub = byId("abOverviewSub");
        const badgeEl = byId("abOverviewStatusBadge");
        const kpi = byId("abOverviewKpi");
        const planName = data.plan_name || data.plan_slug || "Chưa có gói";
        const status = data.subscription_status || data.trial_status || "—";
        const creditBal = Number(data.available_credit != null ? data.available_credit : (data.credit_balance != null ? data.credit_balance : 0));
        const lockedCredit = Number(data.locked_credit || 0);
        const purchasedCredit = Number(data.purchased_credit || 0);
        const renewalPreview = data.renewal_grant_preview || {};
        const renewalGrant = Number(renewalPreview.amount || 0);
        const periodEnd = fmtDateShort(data.current_period_end);
        const periodStart = fmtDateShort(data.current_period_start);
        const hasSub = !!(data.plan_slug && data.subscription_status);

        if (badgeEl) {
            badgeEl.textContent = statusLabel(String(status));
            badgeEl.className = "ab-badge " + esc(String(status).toLowerCase());
        }
        if (sub) {
            const month = data.usage_month || "";
            sub.textContent = hasSub
                ? `Chu kỳ ${periodStart} → ${periodEnd} · Thống kê quota tháng ${month}`
                : (data.trial_message || "Đăng ký gói để mở đầy đủ tính năng và theo dõi quota.");
        }
        const expiringTotal = (data.credit_expiring_soon || []).reduce((s, b) => s + Number(b.amount || 0), 0);
        if (kpi) {
            kpi.innerHTML = [
                { label: "Gói hiện tại", value: planName, highlight: true },
                { label: "Credit khả dụng", value: creditBal.toLocaleString("vi-VN"), money: true },
                {
                    label: "Credit bị khóa",
                    value: lockedCredit > 0 ? lockedCredit.toLocaleString("vi-VN") : "—",
                    warn: lockedCredit > 0,
                },
                {
                    label: "Credit mua thêm",
                    value: purchasedCredit > 0 ? purchasedCredit.toLocaleString("vi-VN") : "—",
                },
                {
                    label: "Nhận khi gia hạn",
                    value: renewalGrant > 0 ? ("+" + renewalGrant.toLocaleString("vi-VN")) : "—",
                },
                {
                    label: "Credit sắp hết hạn (30 ngày)",
                    value: expiringTotal > 0 ? expiringTotal.toLocaleString("vi-VN") : "—",
                    warn: expiringTotal > 0,
                },
                { label: "Hết hạn / chu kỳ", value: hasSub ? periodEnd : "—" },
            ].map((item) => `
                <div class="ab-stat${item.highlight ? " is-highlight" : ""}${item.money ? " is-money" : ""}${item.warn ? " is-warn" : ""}">
                    <span>${esc(item.label)}</span>
                    <strong>${esc(String(item.value))}</strong>
                </div>
            `).join("");
        }

        const lockedBanner = byId("abLockedBanner");
        if (lockedBanner) {
            if (data.locked_message && lockedCredit > 0) {
                lockedBanner.hidden = false;
                lockedBanner.textContent = data.locked_message;
            } else {
                lockedBanner.hidden = true;
                lockedBanner.textContent = "";
            }
        }
        const freeUsageBanner = byId("abFreeUsageBanner");
        const freeUsageText = byId("abFreeUsageBannerText");
        const freeUsageBuyBtn = byId("btnAbFreeUsageBuyCredit");
        if (freeUsageBanner && freeUsageText) {
            if (data.free_usage_active) {
                freeUsageBanner.hidden = false;
                freeUsageText.textContent = data.free_usage_banner
                    || (Number(data.free_usage_days_remaining || 0) > 0
                        ? `Còn ${Number(data.free_usage_days_remaining)} ngày dùng phần mềm`
                        : "");
                if (freeUsageBuyBtn) {
                    freeUsageBuyBtn.hidden = !data.needs_credit_for_features;
                    if (!freeUsageBuyBtn.dataset.wired) {
                        freeUsageBuyBtn.dataset.wired = "1";
                        freeUsageBuyBtn.addEventListener("click", () => {
                            const buyBtn = byId("btnAbOverviewBuyCredit");
                            if (buyBtn) buyBtn.click();
                        });
                    }
                }
            } else {
                freeUsageBanner.hidden = true;
                if (freeUsageBuyBtn) freeUsageBuyBtn.hidden = true;
            }
        }
        const walletGrid = byId("abCreditWalletGrid");
        if (walletGrid) {
            walletGrid.innerHTML = [
                { label: "Khả dụng", value: creditBal, cls: "is-money" },
                { label: "Bị khóa (gói)", value: lockedCredit, cls: lockedCredit > 0 ? "is-warn" : "" },
                { label: "Mua thêm", value: purchasedCredit },
                { label: "Sắp hết hạn", value: expiringTotal },
            ].map((item) => `
                <div class="ab-stat ${esc(item.cls || "")}">
                    <span>${esc(item.label)}</span>
                    <strong>${esc(Number(item.value || 0).toLocaleString("vi-VN"))}</strong>
                </div>
            `).join("");
        }

        renderAlertList(byId("abBillingAlerts"), data.alerts, false);
        renderAlertList(byId("abPlansAlerts"), data.alerts, true);

        const expCard = byId("abExpiringCard");
        const expList = byId("abExpiringList");
        const expiring = data.credit_expiring_soon || [];
        if (expCard && expList) {
            if (!expiring.length) {
                expCard.hidden = true;
            } else {
                expCard.hidden = false;
                expList.innerHTML = expiring.map((b) => `
                    <div class="ab-expiring-item">
                        <div>
                            <strong>${esc(Number(b.amount || 0).toLocaleString("vi-VN"))} credit</strong>
                            <span class="ab-muted-text"> · ${esc(b.source_label || b.source_type || "")}</span>
                        </div>
                        <span class="ab-expiring-date">Hết hạn ${esc(fmtDateShort(b.expired_at))}${b.days_left != null ? ` (${esc(String(b.days_left))} ngày)` : ""}</span>
                    </div>
                `).join("");
            }
        }

        const topCard = byId("abTopModuleCard");
        const topBody = byId("abTopModuleBody");
        const topSub = byId("abTopModuleSub");
        const top = data.top_credit_module;
        if (topCard && topBody) {
            if (!top || !top.credits_used) {
                topCard.hidden = true;
            } else {
                topCard.hidden = false;
                if (topSub) topSub.textContent = `Tháng ${data.usage_month || ""} — tổng ${esc(Number(top.credits_used).toLocaleString("vi-VN"))} credit`;
                const modules = data.module_credit_usage || [];
                topBody.innerHTML = `
                    <div class="ab-top-module-hero">
                        <span class="ab-top-module-name">${esc(top.label || top.module || "")}</span>
                        <span class="ab-top-module-pct">${top.share_percent != null ? esc(String(top.share_percent)) + "%" : ""}</span>
                    </div>
                    ${modules.length > 1 ? `<ul class="ab-module-usage-list">${modules.slice(0, 5).map((m) => `
                        <li><span>${esc(m.label || m.module)}</span><strong>${esc(Number(m.credits_used || 0).toLocaleString("vi-VN"))}</strong></li>
                    `).join("")}</ul>` : ""}
                `;
            }
        }

        const quotaLabel = byId("abQuotaMonthLabel");
        if (quotaLabel) quotaLabel.textContent = `Quota tháng ${data.usage_month || ""}`;
        renderQuotaBars(byId("abQuotaList"), data.quotas, byId("abQuotaEmpty"));

        const histBody = byId("abCreditHistoryBody");
        const histEmpty = byId("abCreditHistoryEmpty");
        const histTable = byId("abCreditHistoryTable");
        const history = data.credit_history || [];
        if (histBody) {
            if (!history.length) {
                histBody.innerHTML = "";
                if (histEmpty) histEmpty.hidden = false;
                if (histTable) histTable.hidden = true;
            } else {
                if (histEmpty) histEmpty.hidden = true;
                if (histTable) histTable.hidden = false;
                histBody.innerHTML = history.map((row) => `
                    <tr>
                        <td>${esc(fmtDateTime(row.created_at))}</td>
                        <td>
                            <span class="ab-hist-label">${esc(row.label || "")}</span>
                            ${row.note ? `<span class="ab-hist-note">${esc(row.note)}</span>` : ""}
                        </td>
                        <td class="ab-num ab-credit-minus">−${esc(Number(row.credit_used || Math.abs(row.delta || 0)).toLocaleString("vi-VN"))}</td>
                        <td class="ab-num">${esc(Number(row.balance_after || 0).toLocaleString("vi-VN"))}</td>
                    </tr>
                `).join("");
            }
        }

        if (body) body.hidden = false;
    }

    function renderPaymentHistory(data) {
        const loading = byId("abPaymentHistoryLoading");
        const err = byId("abPaymentHistoryError");
        const wrap = byId("abPaymentHistoryWrap");
        const empty = byId("abPaymentHistoryEmpty");
        const body = byId("abPaymentHistoryBody");
        const rows = (data && data.payment_history) || [];
        if (loading) loading.hidden = true;
        if (err) err.hidden = true;
        if (!rows.length) {
            if (wrap) wrap.hidden = true;
            if (empty) empty.hidden = false;
            return;
        }
        if (empty) empty.hidden = true;
        if (wrap) wrap.hidden = false;
        if (body) {
            body.innerHTML = rows.map((o) => {
                const date = o.paid_at || o.created_at;
                const act = o.activation_status ? ` · ${statusLabel(o.activation_status)}` : "";
                return `
                    <tr>
                        <td><code class="ab-code">${esc(o.order_code || "—")}</code></td>
                        <td>${esc(o.product_name || o.product_code || "")}</td>
                        <td class="ab-num">${esc(fmtMoney(o.amount).replace(" ₫", "đ"))}</td>
                        <td>${badge(o.status)}${act ? `<span class="ab-muted-text">${esc(act)}</span>` : ""}</td>
                        <td>${esc(fmtDateShort(date))}</td>
                    </tr>
                `;
            }).join("");
        }
    }

    async function loadBillingOverview(force) {
        const loading = byId("abOverviewLoading");
        const body = byId("abOverviewBody");
        const err = byId("abOverviewError");
        if (billingOverviewRef && !force) {
            renderBillingOverview(billingOverviewRef);
            renderPaymentHistory(billingOverviewRef);
            if (loading) loading.hidden = true;
            if (body) body.hidden = false;
            return billingOverviewRef;
        }
        if (loading) loading.hidden = false;
        if (body) body.hidden = true;
        if (err) err.hidden = true;
        try {
            const data = await apiGet("/api/saas/billing-overview");
            billingOverviewRef = data;
            if (loading) loading.hidden = true;
            renderBillingOverview(data);
            renderPaymentHistory(data);
            return data;
        } catch (e) {
            if (loading) loading.hidden = true;
            if (err) { err.hidden = false; err.textContent = String(e.message || e); }
            return null;
        }
    }

    function goBuyCredit() {
        setMainTab("plans");
        setPlansSubTab("credit");
        const first = billingCatalogRef && (billingCatalogRef.credit_addons || [])[0];
        if (first && first.product_code) void startCheckout(first.product_code);
    }

    function goUpgradePlan() {
        setMainTab("plans");
        setPlansSubTab("packages");
        const grid = byId("abPlansGrid");
        if (grid) grid.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function planProductCode(plan) {
        const codes = plan && plan.product_codes;
        if (!codes) return null;
        if (plansBillingModeRef === "yearly") return codes.yearly;
        if (plansBillingModeRef === "semi_annual") return codes.semi_annual;
        return codes.monthly;
    }

    function setMainTab(tab) {
        document.querySelectorAll(".ab-tab").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-ab-tab") === tab);
        });
        document.querySelectorAll(".ab-panel").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-ab-panel") === tab);
        });
        const url = new URL(window.location.href);
        url.searchParams.set("tab", tab);
        history.replaceState(null, "", url.pathname + "?" + url.searchParams.toString());
        if (tab === "affiliate") void loadAffiliate();
        if (tab === "profile") void loadBillingOverview();
        if (tab === "plans") void loadPlans();
        if (tab === "payment") void loadBillingOverview();
        if (tab === "plans") {
            const plansSub = new URLSearchParams(window.location.search).get("plans");
            if (plansSub) setPlansSubTab(plansSub);
        }
    }

    function setAffTab(tab) {
        document.querySelectorAll(".ab-subtab").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-aff-tab") === tab);
        });
        document.querySelectorAll(".ab-aff-panel").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-aff-panel") === tab);
        });
        if (tab === "referrals" && !affLoaded.referrals) void loadReferrals();
        if (tab === "commissions" && !affLoaded.commissions) void loadCommissions();
        if (tab === "payout" && !affLoaded.payouts) void loadPayouts();
        if (tab === "admin-registrations" && !affLoaded.adminReg) void loadAdminRegistrations();
        if (tab === "admin-payouts" && !affLoaded.adminPayout) void loadAdminPayouts();
    }

    function toggleAffiliateAdminUi(show) {
        isAffiliateAdmin = !!show;
        const tabBtn = byId("affAdminRegTab");
        const payoutTab = byId("affAdminPayoutTab");
        const panel = byId("affAdminRegPanel");
        const payoutPanel = byId("affAdminPayoutPanel");
        if (tabBtn) tabBtn.hidden = !show;
        if (payoutTab) payoutTab.hidden = !show;
        if (panel && !show) panel.classList.remove("is-active");
        if (payoutPanel && !show) payoutPanel.classList.remove("is-active");
    }

    function formatAdminBank(p) {
        if (!p.bank_name && !p.bank_account_name) return "—";
        return `${esc(p.bank_name || "")}<br>${esc(p.bank_account_name || "")}<br><span class="ab-muted-text">${esc(p.bank_account_number || "")}</span>`;
    }

    function adminPayoutActions(p) {
        const parts = [];
        if (p.status === "requested") {
            parts.push(`<button type="button" class="ab-btn" data-aff-approve-payout="${p.id}">Duyệt</button>`);
            parts.push(`<button type="button" class="ab-btn secondary" data-aff-reject-payout="${p.id}">Từ chối</button>`);
        } else if (p.status === "processing") {
            parts.push(`<button type="button" class="ab-btn" data-aff-mark-paid="${p.id}" data-amount="${p.amount}">Đã chuyển khoản</button>`);
            parts.push(`<button type="button" class="ab-btn secondary" data-aff-reject-payout="${p.id}">Từ chối</button>`);
        } else {
            parts.push(`<span class="ab-muted-text">${esc(p.transaction_ref || p.note || "—")}</span>`);
        }
        return `<div class="ab-admin-aff-actions">${parts.join("")}</div>`;
    }

    function openAffAdminPayoutModal(id) {
        const modal = byId(id);
        if (!modal) return;
        modal.hidden = false;
        modal.classList.add("is-open");
    }

    function closeAffAdminPayoutModal(id) {
        const modal = byId(id);
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.hidden = true;
    }

    function renderAdminPayoutPager() {
        const pager = byId("affAdminPayoutPager");
        if (!pager) return;
        const total = adminPayoutState.total;
        const off = adminPayoutState.offset;
        if (total <= ADMIN_PAYOUT_PAGE) {
            pager.hidden = true;
            return;
        }
        pager.hidden = false;
        const page = Math.floor(off / ADMIN_PAYOUT_PAGE) + 1;
        const pages = Math.ceil(total / ADMIN_PAYOUT_PAGE);
        pager.innerHTML = `
            <span>Trang ${page}/${pages} · ${total} yêu cầu</span>
            <button type="button" class="ab-btn secondary" data-aff-payout-page="prev" ${off <= 0 ? "disabled" : ""}>Trước</button>
            <button type="button" class="ab-btn secondary" data-aff-payout-page="next" ${off + ADMIN_PAYOUT_PAGE >= total ? "disabled" : ""}>Sau</button>`;
        pager.querySelectorAll("[data-aff-payout-page]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const dir = btn.getAttribute("data-aff-payout-page");
                if (dir === "prev" && off > 0) adminPayoutState.offset = Math.max(0, off - ADMIN_PAYOUT_PAGE);
                else if (dir === "next" && off + ADMIN_PAYOUT_PAGE < total) adminPayoutState.offset = off + ADMIN_PAYOUT_PAGE;
                affLoaded.adminPayout = false;
                void loadAdminPayouts();
            });
        });
    }

    function wireAdminPayoutActions(root) {
        if (!root) return;
        root.querySelectorAll("[data-aff-approve-payout]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-aff-approve-payout");
                if (!id || !window.confirm("Duyệt yêu cầu rút tiền này?")) return;
                try {
                    await apiPost(`/admin/api/affiliate/payouts/${id}/approve`, {});
                    showToast("Đã duyệt yêu cầu rút tiền.");
                    affLoaded.adminPayout = false;
                    await loadAdminPayouts();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        });
        root.querySelectorAll("[data-aff-mark-paid]").forEach((btn) => {
            btn.addEventListener("click", () => {
                markAdminPayoutId = btn.getAttribute("data-aff-mark-paid");
                const amount = btn.getAttribute("data-amount");
                const desc = byId("affAdminPayoutPaidDesc");
                if (desc) desc.textContent = `Xác nhận đã chuyển ${fmtMoney(amount)}?`;
                if (byId("affAdminPayoutRef")) byId("affAdminPayoutRef").value = "";
                if (byId("affAdminPayoutNote")) byId("affAdminPayoutNote").value = "";
                openAffAdminPayoutModal("affAdminPayoutPaidModal");
            });
        });
        root.querySelectorAll("[data-aff-reject-payout]").forEach((btn) => {
            btn.addEventListener("click", () => {
                rejectAdminPayoutId = btn.getAttribute("data-aff-reject-payout");
                if (byId("affAdminPayoutRejectReason")) byId("affAdminPayoutRejectReason").value = "";
                openAffAdminPayoutModal("affAdminPayoutRejectModal");
            });
        });
    }

    async function loadAdminPayouts() {
        if (!isAffiliateAdmin) return;
        const loading = byId("affAdminPayoutLoading");
        const err = byId("affAdminPayoutError");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        try {
            const q = (byId("affAdminPayoutSearch") && byId("affAdminPayoutSearch").value) || "";
            const status = (byId("affAdminPayoutStatus") && byId("affAdminPayoutStatus").value) || "";
            const off = adminPayoutState.offset;
            const res = await apiGet(
                `/admin/api/affiliate/payouts?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}&limit=${ADMIN_PAYOUT_PAGE}&offset=${off}`
            );
            affLoaded.adminPayout = true;
            const data = res.data || {};
            const items = data.items || [];
            adminPayoutState.total = Number(data.total || 0);
            const tbody = document.querySelector("#affAdminPayoutTable tbody");
            const cards = byId("affAdminPayoutCards");
            const empty = byId("affAdminPayoutEmpty");
            const tableWrap = byId("affAdminPayoutTableWrap");
            if (empty) empty.hidden = items.length > 0;
            if (tableWrap) tableWrap.hidden = items.length === 0;
            if (cards) cards.hidden = items.length === 0;
            if (tbody) {
                tbody.innerHTML = items.map((p) =>
                    `<tr>
                        <td>${esc(p.affiliate_email)}</td>
                        <td><strong>${fmtMoney(p.amount)}</strong></td>
                        <td>${formatAdminBank(p)}</td>
                        <td>${badge(p.status)}</td>
                        <td>${esc((p.requested_at || "").slice(0, 10))}</td>
                        <td>${adminPayoutActions(p)}</td>
                    </tr>`
                ).join("");
                wireAdminPayoutActions(tbody);
            }
            if (cards) {
                cards.innerHTML = items.map((p) =>
                    `<div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${esc(p.affiliate_email)}</strong>${badge(p.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Số tiền</span><strong>${fmtMoney(p.amount)}</strong></div>
                        <div class="ab-mcard-row">${formatAdminBank(p)}</div>
                        ${adminPayoutActions(p)}
                    </div>`
                ).join("");
                wireAdminPayoutActions(cards);
            }
            renderAdminPayoutPager();
        } catch (e) {
            if (err) { err.hidden = false; err.textContent = String(e.message || e); }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    function adminRegActions(a) {
        const parts = [];
        parts.push(`<button type="button" class="ab-btn secondary" data-aff-view-reg="${a.id}">Chi tiết</button>`);
        if (a.status !== "active") {
            parts.push(`<button type="button" class="ab-btn" data-aff-activate-reg="${a.id}">Mở khóa</button>`);
        }
        if (a.status !== "review") {
            parts.push(`<button type="button" class="ab-btn secondary" data-aff-review-reg="${a.id}">Cần xem xét</button>`);
        }
        if (a.status !== "suspended") {
            parts.push(`<button type="button" class="ab-btn secondary" data-aff-suspend-reg="${a.id}">Tạm khóa</button>`);
        }
        return parts.length ? `<div class="ab-admin-aff-actions">${parts.join("")}</div>` : "—";
    }

    function renderAdminRegPager() {
        const pager = byId("affAdminRegPager");
        if (!pager) return;
        const total = adminRegState.total;
        const off = adminRegState.offset;
        if (total <= ADMIN_REG_PAGE) {
            pager.hidden = true;
            return;
        }
        pager.hidden = false;
        const page = Math.floor(off / ADMIN_REG_PAGE) + 1;
        const pages = Math.ceil(total / ADMIN_REG_PAGE);
        pager.innerHTML = `
            <span>Trang ${page}/${pages} · ${total} đăng ký</span>
            <button type="button" class="ab-btn secondary" data-aff-reg-page="prev" ${off <= 0 ? "disabled" : ""}>Trước</button>
            <button type="button" class="ab-btn secondary" data-aff-reg-page="next" ${off + ADMIN_REG_PAGE >= total ? "disabled" : ""}>Sau</button>`;
        pager.querySelectorAll("[data-aff-reg-page]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const dir = btn.getAttribute("data-aff-reg-page");
                if (dir === "prev" && off > 0) adminRegState.offset = Math.max(0, off - ADMIN_REG_PAGE);
                else if (dir === "next" && off + ADMIN_REG_PAGE < total) adminRegState.offset = off + ADMIN_REG_PAGE;
                affLoaded.adminReg = false;
                void loadAdminRegistrations();
            });
        });
    }

    function openAffAdminRegModal() {
        const modal = byId("affAdminRegDetailModal");
        if (!modal) return;
        modal.hidden = false;
        modal.classList.add("is-open");
    }

    function closeAffAdminRegModal() {
        const modal = byId("affAdminRegDetailModal");
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.hidden = true;
    }

    async function showAffAdminRegDetail(id) {
        if (!id) return;
        try {
            const res = await apiGet(`/admin/api/affiliate/accounts/${id}`);
            const d = res.data || {};
            const bal = d.balances || {};
            const pi = d.payout_info || {};
            const body = byId("affAdminRegDetailBody");
            if (!body) return;
            body.innerHTML = `
                <dl class="ab-aff-detail-grid">
                    <dt>Email</dt><dd>${esc(d.email)}</dd>
                    <dt>Mã giới thiệu</dt><dd><code>${esc(d.referral_code)}</code></dd>
                    <dt>Trạng thái</dt><dd>${badge(d.status)}</dd>
                    <dt>Hoa hồng</dt><dd>${esc(d.commission_rate || 30)}%</dd>
                    <dt>Click / Đăng ký / Trả phí</dt><dd>${esc(d.clicks)} / ${esc(d.signups)} / ${esc(d.paid_users)}</dd>
                    <dt>Hoàn tiền (hủy)</dt><dd>${esc(d.refunds || 0)}</dd>
                    <dt>Tổng hoa hồng</dt><dd>${fmtMoney(d.total_commission)}</dd>
                    <dt>Chờ duyệt HH / Rút được / Đã nhận</dt><dd>${fmtMoney(bal.pending)} / ${fmtMoney(bal.withdrawable)} / ${fmtMoney(bal.paid)}</dd>
                    <dt>Ngân hàng</dt><dd>${esc(pi.bank_name || "—")} · ${esc(pi.bank_account_name || "—")} · ${esc(pi.bank_account_number_masked || "—")}</dd>
                    <dt>Ngày đăng ký</dt><dd>${esc((d.created_at || "").slice(0, 10))}</dd>
                </dl>
                ${d.fraud_flag ? `<div class="ab-aff-fraud-note"><strong>⚠ Cảnh báo:</strong> ${esc(d.fraud_note || "Phát hiện bất thường")}</div>` : ""}`;
            openAffAdminRegModal();
        } catch (e) {
            alert(String(e.message || e));
        }
    }

    function wireAdminRegActions(root) {
        if (!root) return;
        root.querySelectorAll("[data-aff-view-reg]").forEach((btn) => {
            btn.addEventListener("click", () => {
                void showAffAdminRegDetail(btn.getAttribute("data-aff-view-reg"));
            });
        });
        root.querySelectorAll("[data-aff-activate-reg]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-aff-activate-reg");
                if (!id || !window.confirm("Mở khóa affiliate này? Tài khoản sẽ hoạt động bình thường.")) return;
                try {
                    await apiPost(`/admin/api/affiliate/accounts/${id}/activate`, {});
                    showToast("Đã mở khóa affiliate.");
                    affLoaded.adminReg = false;
                    await loadAdminRegistrations();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        });
        root.querySelectorAll("[data-aff-review-reg]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-aff-review-reg");
                if (!id || !window.confirm("Chuyển affiliate sang trạng thái cần xem xét?")) return;
                try {
                    await apiPost(`/admin/api/affiliate/accounts/${id}/review`, {});
                    showToast("Đã chuyển sang cần xem xét.");
                    affLoaded.adminReg = false;
                    await loadAdminRegistrations();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        });
        root.querySelectorAll("[data-aff-suspend-reg]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-aff-suspend-reg");
                if (!id || !window.confirm("Tạm khóa affiliate này?")) return;
                try {
                    await apiPost(`/admin/api/affiliate/accounts/${id}/suspend`, {});
                    showToast("Đã tạm khóa affiliate.");
                    affLoaded.adminReg = false;
                    await loadAdminRegistrations();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        });
    }

    async function loadAdminRegistrations() {
        if (!isAffiliateAdmin) return;
        const loading = byId("affAdminRegLoading");
        const err = byId("affAdminRegError");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        try {
            const q = (byId("affAdminRegSearch") && byId("affAdminRegSearch").value) || "";
            const status = (byId("affAdminRegStatus") && byId("affAdminRegStatus").value) || "";
            const off = adminRegState.offset;
            const res = await apiGet(
                `/admin/api/affiliate/accounts?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}&limit=${ADMIN_REG_PAGE}&offset=${off}`
            );
            affLoaded.adminReg = true;
            const data = res.data || {};
            const items = data.items || [];
            adminRegState.total = Number(data.total || 0);
            const tbody = document.querySelector("#affAdminRegTable tbody");
            const cards = byId("affAdminRegCards");
            const empty = byId("affAdminRegEmpty");
            const tableWrap = byId("affAdminRegTableWrap");
            if (empty) empty.hidden = items.length > 0;
            if (tableWrap) tableWrap.hidden = items.length === 0;
            if (cards) cards.hidden = items.length === 0;
            if (tbody) {
                tbody.innerHTML = items.map((a) =>
                    `<tr>
                        <td>${esc((a.created_at || "").slice(0, 10))}</td>
                        <td>${esc(a.email)}${a.fraud_flag ? " ⚠️" : ""}</td>
                        <td><code>${esc(a.referral_code)}</code></td>
                        <td>${badge(a.status)}</td>
                        <td>${esc(a.clicks)}</td>
                        <td>${esc(a.signups)}</td>
                        <td>${esc(a.paid_users)}</td>
                        <td>${fmtMoney(a.total_commission)}</td>
                        <td>${adminRegActions(a)}</td>
                    </tr>`
                ).join("");
                wireAdminRegActions(tbody);
            }
            if (cards) {
                cards.innerHTML = items.map((a) =>
                    `<div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${esc(a.email)}</strong>${badge(a.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Ngày DK</span><span>${esc((a.created_at || "").slice(0, 10))}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Mã</span><code>${esc(a.referral_code)}</code></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Click/Signup/Paid</span><span>${a.clicks}/${a.signups}/${a.paid_users}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Hoa hồng</span><strong>${fmtMoney(a.total_commission)}</strong></div>
                        ${adminRegActions(a)}
                    </div>`
                ).join("");
                wireAdminRegActions(cards);
            }
            renderAdminRegPager();
        } catch (e) {
            if (err) { err.hidden = false; err.textContent = String(e.message || e); }
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    async function loadProfile() {
        await loadBillingOverview();
    }

    async function loadPlans() {
        const loading = byId("abPlansLoading");
        const summary = byId("abPlansSummary");
        const err = byId("abPlansError");
        const grid = byId("abPlansGrid");
        if (loading) loading.hidden = false;
        if (summary) summary.hidden = true;
        if (err) err.hidden = true;

        const PLAN_TIER_ORDER = ["free_trial_5d", "starter", "pro", "agency", "business"];
        let billingCatalog = null;
        let saas = null;
        let plansBillingMode = "monthly";
        plansBillingModeRef = plansBillingMode;

        function planTier(slug) {
            const s = String(slug || "").toLowerCase();
            const idx = PLAN_TIER_ORDER.indexOf(s);
            return idx >= 0 ? idx : -1;
        }

        function fmtVnd(n) {
            return Number(n || 0).toLocaleString("vi-VN") + "đ";
        }

        function fmtDate(iso) {
            if (!iso) return "—";
            try {
                return new Date(iso).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
            } catch (_) {
                return "—";
            }
        }

        function quotaRow(quotas, key) {
            return (quotas || []).find((q) => q.feature_key === key) || null;
        }

        function planAction(currentSlug, cardSlug, hasActiveSub) {
            const cur = String(currentSlug || "").toLowerCase();
            const card = String(cardSlug || "").toLowerCase();
            if (cur && cur === card) {
                return { label: "Gói hiện tại", disabled: true, kind: "current" };
            }
            const curTier = planTier(cur);
            const cardTier = planTier(card);
            if (curTier >= 0 && cardTier >= 0) {
                if (cardTier > curTier) return { label: "Nâng cấp", disabled: false, kind: "upgrade" };
                return {
                    label: hasActiveSub ? "Liên hệ hỗ trợ" : "Hạ gói",
                    disabled: false,
                    kind: "downgrade",
                };
            }
            return { label: "Nâng cấp", disabled: false, kind: "upgrade" };
        }

        function renderSummary() {
            if (!summary) return;
            const kpi = byId("abPlansKpi");
            const badgeEl = byId("abPlansStatusBadge");
            const sub = byId("abPlansSummarySub");
            const overview = billingOverviewRef;
            const planName = (overview && overview.plan_name) || saas.plan_name || saas.plan_slug || "Chưa có gói";
            const status = (overview && overview.subscription_status) || saas.subscription_status || saas.trial_status || "—";
            const creditBal = Number(
                overview && overview.credit_balance != null ? overview.credit_balance
                    : (saas.credit_balance != null ? saas.credit_balance : 0)
            );
            const art = quotaRow(saas.quotas, "content_ai_article");
            const artRemain = art && art.quota_remaining != null ? art.quota_remaining : "—";
            const artLimit = art && art.limit_value != null ? art.limit_value : null;
            const periodEnd = fmtDate(saas.current_period_end);
            const periodStart = fmtDate(saas.current_period_start);
            const hasSub = !!(saas.plan_slug && saas.subscription_status);
            const expiringTotal = overview
                ? (overview.credit_expiring_soon || []).reduce((s, b) => s + Number(b.amount || 0), 0)
                : 0;

            if (badgeEl) {
                badgeEl.textContent = statusLabel(String(status));
                badgeEl.className = "ab-badge " + esc(String(status).toLowerCase());
            }
            if (sub) {
                sub.textContent = hasSub
                    ? `Chu kỳ ${periodStart} → ${periodEnd}`
                    : (saas.message || saas.trial_message || "Đăng ký gói để mở đầy đủ tính năng.");
            }
            if (kpi) {
                kpi.innerHTML = [
                    { label: "Gói hiện tại", value: planName, highlight: true },
                    { label: "Credit còn lại", value: creditBal.toLocaleString("vi-VN"), money: true },
                    {
                        label: "Credit sắp hết hạn",
                        value: expiringTotal > 0 ? expiringTotal.toLocaleString("vi-VN") : "—",
                        warn: expiringTotal > 0,
                    },
                    {
                        label: "Bài AI còn lại (tháng)",
                        value: artRemain === "—" ? "—" : `${artRemain}${artLimit != null ? ` / ${artLimit}` : ""}`,
                    },
                    { label: "Hết hạn / chu kỳ", value: hasSub ? periodEnd : "—" },
                ].map((item) => `
                    <div class="ab-stat${item.highlight ? " is-highlight" : ""}${item.money ? " is-money" : ""}${item.warn ? " is-warn" : ""}">
                        <span>${esc(item.label)}</span>
                        <strong>${esc(String(item.value))}</strong>
                    </div>
                `).join("");
            }
            if (overview) renderAlertList(byId("abPlansAlerts"), overview.alerts, true);
            summary.hidden = false;
        }

        function highlightPlanCard(slug) {
            if (!slug || !grid) return;
            const normalized = String(slug).toLowerCase();
            grid.querySelectorAll(".ab-plan-card.is-target").forEach((el) => el.classList.remove("is-target"));
            const card = grid.querySelector(`.ab-plan-card[data-plan="${normalized}"]`);
            if (!card) return;
            card.classList.add("is-target");
            window.setTimeout(() => {
                card.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 100);
        }

        function planDisplayPrice(plan) {
            const code = planProductCode(plan);
            const products = (billingCatalog && billingCatalog.products) || [];
            const match = products.find((p) => String(p.product_code || "").toUpperCase() === String(code || "").toUpperCase());
            if (match && match.price != null) return Number(match.price) || 0;
            if (plansBillingMode === "yearly") return Number(plan.year_price) || 0;
            if (plansBillingMode === "semi_annual") return Number(plan.semi_annual_price) || 0;
            return Number(plan.month_price) || 0;
        }

        function planBillingUnit() {
            if (plansBillingMode === "yearly") return "/năm";
            if (plansBillingMode === "semi_annual") return "/6 tháng";
            return "/tháng";
        }

        function planSemiCreditTotal(plan) {
            const code = planProductCode(plan);
            const products = (billingCatalog && billingCatalog.products) || [];
            const match = products.find((p) => String(p.product_code || "").toUpperCase() === String(code || "").toUpperCase());
            if (match && match.total_credit != null) return Number(match.total_credit) || 0;
            return Number(plan.semi_annual_total_credit) || 0;
        }

        function planYearlyCreditTotal(plan) {
            const code = planProductCode(plan);
            const products = (billingCatalog && billingCatalog.products) || [];
            const match = products.find((p) => String(p.product_code || "").toUpperCase() === String(code || "").toUpperCase());
            if (match && match.total_credit != null) return Number(match.total_credit) || 0;
            return Number(plan.yearly_total_credit) || 0;
        }

        function fmtQuotaNum(n) {
            return Number(n || 0).toLocaleString("vi-VN");
        }

        function highlightValue(plan, labelMatch) {
            const needle = String(labelMatch || "").toLowerCase();
            const row = (plan.highlights || []).find((h) => String(h.label || "").toLowerCase().includes(needle));
            return row ? String(row.value || "") : "";
        }

        function buildPlanFeatureGroups(plan) {
            const c = plan.compare || {};
            const kw = c.keyword_research_quota != null
                ? `${fmtQuotaNum(c.keyword_research_quota)}/tháng`
                : (highlightValue(plan, "keyword research") || "—");
            const cluster = c.keyword_cluster_quota != null
                ? `${fmtQuotaNum(c.keyword_cluster_quota)}/tháng`
                : (highlightValue(plan, "gom nhóm") || "—");
            const articles = c.content_ai_per_month != null
                ? fmtQuotaNum(c.content_ai_per_month)
                : "—";
            const indexSubmit = c.index_submit_quota != null
                ? `${fmtQuotaNum(c.index_submit_quota)} URL/tháng`
                : "—";
            const credits = c.credits_month != null
                ? fmtQuotaNum(c.credits_month)
                : (highlightValue(plan, "credit") || "—");
            const projects = c.platform_projects != null
                ? fmtQuotaNum(c.platform_projects)
                : "—";
            const users = c.platform_users != null
                ? fmtQuotaNum(c.platform_users)
                : "—";
            let chatbot = "Từ gói Pro";
            if (c.chatbot_enabled) {
                const bots = c.chatbot_bots != null ? fmtQuotaNum(c.chatbot_bots) : "—";
                const replies = c.chatbot_reply_monthly != null ? fmtQuotaNum(c.chatbot_reply_monthly) : "—";
                chatbot = `${bots} bot · ${replies} reply`;
            }

            // Same row order on every card so features align horizontally across plans.
            return [
                [
                    { label: "Keyword Research", value: kw, emphasize: true },
                    { label: "Gom nhóm từ khóa", value: cluster, emphasize: true },
                ],
                [
                    { label: "Bài AI", value: articles },
                    { label: "Submit Index", value: indexSubmit },
                    { label: "Check Index", free: true },
                    { label: "Technical", free: true },
                    { label: "SEO Score", free: true },
                    { label: "Schema", free: true },
                ],
                [
                    { label: "Credit Premium", value: credits },
                    { label: "AI Chatbot", value: chatbot, muted: !c.chatbot_enabled, chatbot: true },
                ],
                [
                    { label: "Website / Project", value: projects },
                    { label: "User / Team", value: users },
                ],
            ];
        }

        function renderFeatureRow(row) {
            if (row.free) {
                return `<li class="ab-plan-feat is-free">
                    <span class="ab-plan-feat-label">${esc(row.label)}</span>
                    <span class="ab-plan-feat-value ab-plan-feat-free"><span class="ab-plan-check" aria-hidden="true">✓</span> Miễn phí</span>
                </li>`;
            }
            const cls = [
                "ab-plan-feat",
                row.emphasize ? "is-emphasis" : "",
                row.muted ? "is-muted" : "",
                row.chatbot ? "is-chatbot" : "",
            ].filter(Boolean).join(" ");
            return `<li class="${cls}">
                <span class="ab-plan-feat-label">${esc(row.label)}</span>
                <span class="ab-plan-feat-value">${esc(row.value || "—")}</span>
            </li>`;
        }

        function renderPlanCards() {
            if (!grid || !billingCatalog) return;
            const plans = billingCatalog.plans || [];
            const currentSlug = String(saas && saas.plan_slug || "").toLowerCase();
            const hasActiveSub = ["active", "trialing"].includes(String(saas && saas.subscription_status || "").toLowerCase());
            const isSemi = plansBillingMode === "semi_annual";
            const isYearly = plansBillingMode === "yearly";
            const unit = planBillingUnit();

            grid.innerHTML = plans.map((p) => {
                const action = planAction(currentSlug, p.slug, hasActiveSub);
                const price = planDisplayPrice(p);
                const semiCredit = isSemi ? planSemiCreditTotal(p) : 0;
                const yearlyCredit = isYearly ? planYearlyCreditTotal(p) : 0;
                const groups = buildPlanFeatureGroups(p);
                const sectionsHtml = groups.map((rows, idx) => `
                    ${idx > 0 ? '<div class="ab-plan-divider" role="presentation"></div>' : ""}
                    <ul class="ab-plan-feats">${rows.map(renderFeatureRow).join("")}</ul>
                `).join("");
                const btnClass = (action.kind === "upgrade" && p.is_popular)
                    ? "ab-btn ab-plan-btn is-primary"
                    : "ab-btn secondary ab-plan-btn";
                const featured = p.is_popular ? " is-featured" : "";
                const current = action.kind === "current" ? " is-current" : "";
                const cycleNote = isSemi
                    ? '<div class="ab-plan-cycle-chip">Tặng thêm 1 tháng credit</div>'
                    : (isYearly
                        ? '<div class="ab-plan-cycle-chip">Tặng 2 tháng sử dụng + 2 tháng credit</div>'
                        : "");
                const creditRow = isSemi
                    ? `<p class="ab-plan-credit-total">Tổng credit 6 tháng: <strong>${esc(Number(semiCredit).toLocaleString("vi-VN"))}</strong></p>`
                    : (isYearly
                        ? `<p class="ab-plan-credit-total">Tổng credit năm: <strong>${esc(Number(yearlyCredit).toLocaleString("vi-VN"))}</strong></p>`
                        : "");
                return `
                    <article class="ab-plan-card${featured}${current}" data-plan="${esc(p.slug)}">
                        ${p.is_popular ? '<div class="ab-plan-pop">Phổ biến nhất</div>' : ""}
                        <div class="ab-plan-card-body">
                            <header class="ab-plan-header">
                                <h4 class="ab-plan-name">${esc(p.name)}</h4>
                                <div class="ab-plan-price">
                                    <span class="ab-plan-amount">${esc(fmtVnd(price))}</span>
                                    <span class="ab-plan-unit">${esc(unit)}</span>
                                </div>
                                ${cycleNote}
                                ${creditRow}
                                <p class="ab-plan-fit">${esc(p.fit || "")}</p>
                                <p class="ab-plan-vat">Giá chưa VAT</p>
                            </header>
                            <div class="ab-plan-sections">${sectionsHtml}</div>
                        </div>
                        <footer class="ab-plan-footer">
                            <button type="button"
                                class="${btnClass}"
                                data-plan-action="${esc(p.slug)}"
                                data-action-kind="${esc(action.kind)}"
                                ${action.disabled ? "disabled" : ""}>
                                ${esc(action.label)}
                            </button>
                        </footer>
                    </article>
                `;
            }).join("");

            grid.querySelectorAll("[data-plan-action]").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const kind = btn.getAttribute("data-action-kind");
                    const slug = btn.getAttribute("data-plan-action");
                    if (kind === "current") return;
                    if (kind === "upgrade") {
                        const plan = (billingCatalog.plans || []).find((p) => String(p.slug).toLowerCase() === String(slug).toLowerCase());
                        const productCode = plan ? planProductCode(plan) : null;
                        if (!productCode) {
                            showToast("Không tìm thấy mã sản phẩm cho gói này.");
                            return;
                        }
                        void startCheckout(productCode);
                        return;
                    }
                    showToast("Vui lòng liên hệ hỗ trợ để thay đổi hoặc hạ gói.");
                });
            });
        }

        function formatCompareCell(v) {
            if (v === true) return '<span class="ab-cmp-yes">✓</span>';
            if (v === false || v == null || v === "") return '<span class="ab-cmp-no">—</span>';
            if (typeof v === "number") return `<span class="ab-cmp-val">${esc(Number(v).toLocaleString("vi-VN"))}</span>`;
            const s = String(v);
            if (s.toUpperCase() === "FREE") return '<span class="ab-cmp-free">FREE</span>';
            return `<span class="ab-cmp-val">${esc(s)}</span>`;
        }

        function renderPlansCompareModal() {
            const body = byId("abPlansCompareBody");
            if (!body || !billingCatalog) return;
            const plans = billingCatalog.plans || [];
            const rows = billingCatalog.compare_rows || [];
            if (!plans.length || !rows.length) {
                body.innerHTML = '<p class="ab-muted-text">Chưa có dữ liệu so sánh.</p>';
                return;
            }
            const head = `<tr><th class="ab-cmp-feature">Hạng mục</th>${plans.map((p) =>
                `<th class="ab-cmp-plan${p.is_popular ? " is-pro" : ""}">${esc(p.name)}${p.is_popular ? '<span class="ab-cmp-badge">Phổ biến nhất</span>' : ""}</th>`
            ).join("")}</tr>`;
            const tbody = rows.map((r) => {
                const cells = plans.map((p) => {
                    const v = (p.compare || {})[r.key];
                    return `<td class="ab-cmp-plan${p.is_popular ? " is-pro" : ""}">${formatCompareCell(v)}</td>`;
                }).join("");
                return `<tr><td class="ab-cmp-feature">${esc(r.label || r.key)}</td>${cells}</tr>`;
            }).join("");
            const mobile = plans.map((p) => {
                const items = rows.map((r) => {
                    const v = (p.compare || {})[r.key];
                    return `<div class="ab-cmp-mrow"><span>${esc(r.label || r.key)}</span><span>${formatCompareCell(v)}</span></div>`;
                }).join("");
                return `<div class="ab-cmp-mcard${p.is_popular ? " is-pro" : ""}"><div class="ab-cmp-mhead">${esc(p.name)}${p.is_popular ? ' <em>Phổ biến nhất</em>' : ""}</div>${items}</div>`;
            }).join("");
            body.innerHTML = `
                <div class="ab-cmp-table-wrap">
                    <table class="ab-cmp-table">
                        <thead>${head}</thead>
                        <tbody>${tbody}</tbody>
                    </table>
                </div>
                <div class="ab-cmp-mobile">${mobile}</div>
            `;
        }

        function openPlansCompareModal() {
            const modal = byId("abPlansCompareModal");
            if (!modal) return;
            renderPlansCompareModal();
            modal.hidden = false;
            modal.classList.add("is-open");
        }

        function closePlansCompareModal() {
            const modal = byId("abPlansCompareModal");
            if (!modal) return;
            modal.hidden = true;
            modal.classList.remove("is-open");
        }

        function renderAddons() {
            const creditBody = byId("abCreditAddonBody");
            const creditNotes = byId("abCreditAddonNotes");
            const articleBody = byId("abArticleAddonBody");
            const articleNotes = byId("abArticleAddonNotes");
            if (!billingCatalog) return;

            if (creditBody) {
                creditBody.innerHTML = (billingCatalog.credit_addons || []).map((row) => `
                    <tr>
                        <td class="ab-addon-price">${esc(fmtVnd(row.price))}</td>
                        <td>${esc(Number(row.credits || 0).toLocaleString("vi-VN"))} credit</td>
                        <td class="ab-addon-action">
                            <button type="button" class="ab-btn ab-btn-sm dcm-select-btn" data-buy-product="${esc(row.product_code)}">Chọn</button>
                        </td>
                    </tr>
                `).join("");
                creditBody.querySelectorAll("[data-buy-product]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        void startCheckout(btn.getAttribute("data-buy-product"));
                    });
                });
            }
            if (creditNotes) {
                creditNotes.innerHTML = (billingCatalog.credit_addon_notes || [])
                    .map((n) => `<li>${esc(n)}</li>`).join("");
            }
            if (articleBody) {
                articleBody.innerHTML = (billingCatalog.article_addons || []).map((row) => {
                    const priceCell = row.price_label
                        ? esc(row.price_label)
                        : esc(fmtVnd(row.price));
                    const btn = row.contact_sales
                        ? `<button type="button" class="ab-btn secondary ab-btn-sm" data-contact-sales="1">Liên hệ</button>`
                        : `<button type="button" class="ab-btn secondary ab-btn-sm" data-buy-product="${esc(row.product_code)}">Chọn</button>`;
                    return `
                        <tr>
                            <td>+${esc(Number(row.articles || 0).toLocaleString("vi-VN"))} bài/tháng</td>
                            <td class="ab-addon-price">${priceCell}</td>
                            <td class="ab-addon-action">${btn}</td>
                        </tr>
                    `;
                }).join("");
                articleBody.querySelectorAll("[data-buy-product]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        void startCheckout(btn.getAttribute("data-buy-product"));
                    });
                });
                articleBody.querySelectorAll("[data-contact-sales]").forEach((btn) => {
                    btn.addEventListener("click", () => {
                        openPaymentModal();
                        showPaymentContact("Gói +1.000 bài/tháng cần liên hệ bộ phận kinh doanh để được báo giá.");
                    });
                });
            }
            if (articleNotes) {
                articleNotes.innerHTML = (billingCatalog.article_addon_notes || [])
                    .map((n) => `<li>${esc(n)}</li>`).join("");
            }
        }

        function setPlansBilling(mode) {
            plansBillingMode = mode === "yearly"
                ? "yearly"
                : (mode === "semi_annual" ? "semi_annual" : "monthly");
            plansBillingModeRef = plansBillingMode;
            document.querySelectorAll(".ab-billing-btn[data-ab-billing]").forEach((btn) => {
                const active = btn.getAttribute("data-ab-billing") === plansBillingMode;
                btn.classList.toggle("is-active", active);
                btn.setAttribute("aria-pressed", active ? "true" : "false");
            });
            const yearNote = byId("abBillingYearNote");
            const semiNote = byId("abBillingSemiNote");
            if (yearNote) yearNote.hidden = plansBillingMode !== "yearly";
            if (semiNote) semiNote.hidden = plansBillingMode !== "semi_annual";
            renderPlanCards();
        }

        try {
            const [saasRes, catalogRes, overviewRes] = await Promise.all([
                apiGet("/api/saas/me"),
                apiGet("/api/saas/billing-catalog"),
                apiGet("/api/saas/billing-overview").catch(() => null),
            ]);
            saas = saasRes;
            billingCatalog = catalogRes;
            billingCatalogRef = billingCatalog;
            if (overviewRes) {
                billingOverviewRef = overviewRes;
            }
            if (loading) loading.hidden = true;
            renderSummary();
            renderPlanCards();
            renderAddons();

            const planHighlight = new URLSearchParams(window.location.search).get("plan");
            if (planHighlight) highlightPlanCard(planHighlight);

            document.querySelectorAll(".ab-billing-btn[data-ab-billing]").forEach((btn) => {
                if (btn.dataset.abBillingWired) return;
                btn.dataset.abBillingWired = "1";
                btn.addEventListener("click", () => setPlansBilling(btn.getAttribute("data-ab-billing")));
            });

            const openCompare = byId("abOpenPlansCompare");
            if (openCompare && !openCompare.dataset.wired) {
                openCompare.dataset.wired = "1";
                openCompare.addEventListener("click", () => openPlansCompareModal());
            }
            const closeCompare = byId("abClosePlansCompare");
            if (closeCompare && !closeCompare.dataset.wired) {
                closeCompare.dataset.wired = "1";
                closeCompare.addEventListener("click", () => closePlansCompareModal());
            }
            const compareModal = byId("abPlansCompareModal");
            if (compareModal && !compareModal.dataset.wired) {
                compareModal.dataset.wired = "1";
                compareModal.addEventListener("click", (ev) => {
                    if (ev.target === compareModal) closePlansCompareModal();
                });
            }

            const buyCredit = byId("btnAbBuyCredit");
            if (buyCredit) {
                buyCredit.disabled = false;
                if (!buyCredit.dataset.wired) {
                    buyCredit.dataset.wired = "1";
                    buyCredit.addEventListener("click", () => {
                        setPlansSubTab("credit");
                        const first = billingCatalog && (billingCatalog.credit_addons || [])[0];
                        if (first && first.product_code) void startCheckout(first.product_code);
                        else showToast("Chọn gói credit trong bảng bên dưới.");
                    });
                }
            }
            const buyArticles = byId("btnAbBuyArticles");
            if (buyArticles) {
                buyArticles.disabled = false;
                if (!buyArticles.dataset.wired) {
                    buyArticles.dataset.wired = "1";
                    buyArticles.addEventListener("click", () => {
                        setPlansSubTab("articles");
                        showToast("Chọn gói bài viết trong bảng bên dưới.");
                    });
                }
            }
        } catch (e) {
            if (loading) loading.hidden = true;
            if (err) {
                err.hidden = false;
                err.textContent = String(e.message || e);
            }
        }
    }

    function setPlansSubTab(sub) {
        const tab = sub || "packages";
        document.querySelectorAll("[data-plans-subtab]").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-plans-subtab") === tab);
        });
        document.querySelectorAll("[data-plans-panel]").forEach((el) => {
            el.classList.toggle("is-active", el.getAttribute("data-plans-panel") === tab);
        });
        const url = new URL(window.location.href);
        if (tab === "packages") url.searchParams.delete("plans");
        else url.searchParams.set("plans", tab);
        history.replaceState(null, "", url.pathname + "?" + url.searchParams.toString());
    }

    function updateQrCode(link) {
        const img = byId("affQrImg");
        const ph = byId("affQrPlaceholder");
        if (!link) {
            if (img) img.hidden = true;
            if (ph) { ph.hidden = false; ph.textContent = "Chưa có link"; }
            return;
        }
        const url = "https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=" + encodeURIComponent(link);
        if (img) {
            img.src = url;
            img.hidden = false;
            img.onload = () => { if (ph) ph.hidden = true; };
            img.onerror = () => {
                if (ph) { ph.hidden = false; ph.textContent = "Không tạo được QR"; }
                img.hidden = true;
            };
        }
    }

    function updateUtmPreview() {
        const base = (byId("affLink") && byId("affLink").value) || "";
        if (!base) return;
        const u = new URL(base, window.location.origin);
        const s = byId("affUtmSource") && byId("affUtmSource").value.trim();
        const m = byId("affUtmMedium") && byId("affUtmMedium").value.trim();
        const c = byId("affUtmCampaign") && byId("affUtmCampaign").value.trim();
        if (s) u.searchParams.set("utm_source", s); else u.searchParams.delete("utm_source");
        if (m) u.searchParams.set("utm_medium", m); else u.searchParams.delete("utm_medium");
        if (c) u.searchParams.set("utm_campaign", c); else u.searchParams.delete("utm_campaign");
        const preview = u.toString();
        if (byId("affUtmPreview")) byId("affUtmPreview").value = preview;
        updateQrCode(preview);
    }

    function tip(label, text) {
        return `${esc(label)} <span class="ab-tip" tabindex="0" aria-label="${esc(text)}" data-tip="${esc(text)}">ⓘ</span>`;
    }

    const TIPS = {
        pending: "Hoa hồng đã phát sinh nhưng admin chưa duyệt. Sau khi duyệt sẽ chuyển sang có thể rút.",
        withdrawable: "Số tiền đã được duyệt và đủ điều kiện — bạn có thể gửi yêu cầu rút về ngân hàng.",
        paid: "Tổng hoa hồng đã chuyển vào tài khoản ngân hàng của bạn.",
        cookie: "Khách click link của bạn sẽ được ghi nhận trong 60 ngày. Đăng ký trong thời gian này vẫn tính cho bạn.",
        commPending: "Đơn hàng đã thanh toán, hoa hồng đang chờ admin xác nhận.",
        commApproved: "Hoa hồng đã duyệt, chờ đủ điều kiện rút hoặc đợi lệnh rút tiền.",
        commPaid: "Hoa hồng đã được thanh toán cho bạn.",
    };

    function renderKpiRow(data) {
        const st = data.stats || {};
        const bal = data.balances || {};
        const earned = Number(bal.paid || 0) + Number(bal.withdrawable || 0) + Number(bal.pending || 0);
        const items = [
            { label: "Đã kiếm được", value: fmtMoney(earned), tip: "Tổng hoa hồng từ khách giới thiệu (chờ duyệt + có thể rút + đã nhận).", cls: "ab-kpi-earned" },
            { label: "Người đăng ký", value: st.signups || 0, tip: "Số tài khoản đăng ký qua link của bạn.", cls: "" },
            { label: "Có thể rút", value: fmtMoney(bal.withdrawable), tip: TIPS.withdrawable, cls: "ab-kpi-withdraw" },
            { label: "Đang chờ duyệt", value: fmtMoney(bal.pending), tip: TIPS.pending, cls: "ab-kpi-pending" },
        ];
        const row = byId("affKpiRow");
        if (!row) return;
        row.innerHTML = items.map((it) =>
            `<div class="ab-kpi ${esc(it.cls)}">
                <span class="ab-kpi-label">${tip(it.label, it.tip)}</span>
                <strong class="ab-kpi-value">${esc(it.value)}</strong>
            </div>`
        ).join("");
    }

    function renderOverviewStats(data) {
        const st = data.stats || {};
        const bal = data.balances || {};
        const link = data.referral_link || "";
        renderKpiRow(data);
        const emptyClicks = byId("affOverviewEmptyClicks");
        if (emptyClicks) emptyClicks.hidden = Number(st.clicks || 0) > 0;
        const items = [
            { label: "Lượt click link", value: st.clicks, cls: "", tip: "Số lần khách mở link giới thiệu của bạn." },
            { label: "Người đăng ký", value: st.signups, cls: "", tip: "Khách tạo tài khoản qua link của bạn." },
            { label: "Khách đã trả phí", value: st.paid_users, cls: "is-highlight", tip: "Khách giới thiệu đã mua gói trả phí." },
            { label: "Tỷ lệ chuyển đổi", value: (st.conversion_rate || 0) + "%", cls: "", tip: "Tỷ lệ khách trả phí / lượt click." },
            { label: "Chờ duyệt", value: fmtMoney(bal.pending), cls: "is-money", tip: TIPS.pending },
            { label: "Có thể rút", value: fmtMoney(bal.withdrawable), cls: "is-money is-highlight", tip: TIPS.withdrawable },
            { label: "Đã nhận", value: fmtMoney(bal.paid), cls: "is-money", tip: TIPS.paid },
        ];
        const grid = byId("affOverviewStats");
        if (grid) {
            grid.innerHTML = items.map((it) =>
                `<div class="ab-stat ${esc(it.cls)}"><span>${tip(it.label, it.tip)}</span><strong>${esc(it.value)}</strong></div>`
            ).join("");
        }
        if (byId("affOverviewLink")) byId("affOverviewLink").value = link;
        if (byId("affCode")) byId("affCode").value = data.referral_code || "";
        if (byId("affLink")) byId("affLink").value = link;
        if (byId("affCommissionRate")) byId("affCommissionRate").textContent = (data.commission_rate || 30) + "%";
        if (byId("affCookieDays")) byId("affCookieDays").textContent = data.cookie_days || 60;

        const statusBadge = byId("affAccountStatusBadge");
        if (statusBadge) {
            const stt = data.status || "active";
            statusBadge.className = "ab-badge " + stt;
            statusBadge.textContent = statusLabel(stt);
        }

        updateUtmPreview();

        const note = byId("affStatusNote");
        if (note) {
            if (data.status === "review") note.textContent = "Tài khoản affiliate đang được xem xét. Hoa hồng mới tạm dừng cho đến khi được mở khóa.";
            else if (data.status === "suspended") note.textContent = "Tài khoản affiliate đã bị tạm khóa. Liên hệ hỗ trợ để được hỗ trợ.";
            else note.textContent = "";
        }

        const pi = data.payout_info || {};
        if (byId("affBankName") && pi.bank_name) byId("affBankName").value = pi.bank_name;
        if (byId("affBankOwner") && pi.bank_account_name) byId("affBankOwner").value = pi.bank_account_name;
        const masked = byId("affBankMasked");
        if (masked) {
            masked.textContent = pi.bank_account_number_masked
                ? "Số tài khoản đã lưu: " + pi.bank_account_number_masked
                : "";
        }

        const minNote = byId("affMinPayoutNote");
        if (minNote && data.min_payout_amount) {
            minNote.textContent = "Số tiền rút tối thiểu: " + fmtMoney(data.min_payout_amount) + ".";
        }

        renderPayoutBalances(bal, data.min_payout_amount);
    }

    let payoutRequestBusy = false;

    function renderPayoutBalances(bal, minPayout) {
        const grid = byId("affPayoutBalances");
        if (!grid) return;
        bal = bal || {};
        grid.innerHTML = [
            { label: "Có thể rút", value: fmtMoney(bal.withdrawable), cls: "is-money is-highlight", tip: TIPS.withdrawable },
            { label: "Chờ duyệt", value: fmtMoney(bal.pending), cls: "is-money", tip: TIPS.pending },
            { label: "Đã nhận", value: fmtMoney(bal.paid), cls: "is-money", tip: TIPS.paid },
        ].map((it) =>
            `<div class="ab-stat ${esc(it.cls)}"><span>${tip(it.label, it.tip)}</span><strong>${esc(it.value)}</strong></div>`
        ).join("");

        const payoutBtn = byId("btnAffRequestPayoutTab");
        const overviewBtn = byId("btnAffRequestPayout");
        const hasBank = !!(affOverview && affOverview.payout_info && affOverview.payout_info.has_bank_info);
        const withdrawable = Number(bal.withdrawable || 0);
        const minAmt = Number(minPayout || 0);
        const canWithdraw = withdrawable >= minAmt && withdrawable > 0 && hasBank && !payoutRequestBusy;
        [payoutBtn, overviewBtn].forEach((btn) => {
            if (!btn) return;
            btn.disabled = !canWithdraw;
            if (!hasBank && withdrawable >= minAmt && withdrawable > 0) {
                btn.title = "Cập nhật đủ thông tin ngân hàng trước khi rút.";
            } else if (withdrawable < minAmt) {
                btn.title = "Số dư có thể rút chưa đạt mức tối thiểu.";
            } else {
                btn.title = "";
            }
        });
    }

    function setPanelLoading(loadingId, show) {
        const el = byId(loadingId);
        if (el) el.hidden = !show;
    }

    function setPanelError(errorId, msg) {
        const el = byId(errorId);
        if (!el) return;
        if (msg) { el.hidden = false; el.textContent = msg; }
        else { el.hidden = true; el.textContent = ""; }
    }

    async function loadReferrals() {
        setPanelLoading("affReferralsLoading", true);
        setPanelError("affReferralsError", null);
        try {
            const res = await apiGet("/affiliate/referrals");
            affLoaded.referrals = true;
            const items = (res.data && res.data.items) || [];
            const tbody = document.querySelector("#affReferralsTable tbody");
            const cards = byId("affReferralsCards");
            const empty = byId("affReferralsEmpty");
            const tableWrap = byId("affReferralsTableWrap");
            if (empty) empty.hidden = items.length > 0;
            if (tableWrap) tableWrap.hidden = items.length === 0;
            if (cards) cards.hidden = items.length === 0;
            if (tbody) {
                tbody.innerHTML = items.map((r) =>
                    `<tr>
                        <td>${esc((r.registered_at || "").slice(0, 10))}</td>
                        <td>${esc(r.customer_email || r.customer_masked || "—")}</td>
                        <td>${badge(r.status)}</td>
                        <td>${esc(r.plan_name || "—")}</td>
                        <td>${esc(r.first_paid_at ? (r.first_paid_at).slice(0, 10) : "—")}</td>
                    </tr>`
                ).join("");
            }
            if (cards) {
                cards.innerHTML = items.map((r) =>
                    `<div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${esc(r.customer_email || r.customer_masked || "—")}</strong>${badge(r.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Đăng ký</span><span>${esc((r.registered_at || "").slice(0, 10))}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Gói</span><span>${esc(r.plan_name || "—")}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Thanh toán đầu</span><span>${esc(r.first_paid_at ? (r.first_paid_at).slice(0, 10) : "—")}</span></div>
                    </div>`
                ).join("");
            }
        } catch (e) {
            setPanelError("affReferralsError", String(e.message || e));
        } finally {
            setPanelLoading("affReferralsLoading", false);
        }
    }

    async function loadCommissions() {
        setPanelLoading("affCommissionsLoading", true);
        setPanelError("affCommissionsError", null);
        try {
            const res = await apiGet("/affiliate/commissions");
            affLoaded.commissions = true;
            const items = (res.data && res.data.items) || [];
            const tbody = document.querySelector("#affCommissionsTable tbody");
            const cards = byId("affCommissionsCards");
            const empty = byId("affCommissionsEmpty");
            const tableWrap = byId("affCommissionsTableWrap");
            if (empty) empty.hidden = items.length > 0;
            if (tableWrap) tableWrap.hidden = items.length === 0;
            if (cards) cards.hidden = items.length === 0;
            if (tbody) {
                tbody.innerHTML = items.map((c) =>
                    `<tr>
                        <td>${esc((c.created_at || "").slice(0, 10))}</td>
                        <td>${esc(c.customer_masked)}</td>
                        <td>${fmtMoney(c.order_amount)}</td>
                        <td><strong>${fmtMoney(c.commission_amount)}</strong> <span class="ab-muted-text" style="font-size:0.78rem;">(${c.commission_rate || 30}%)</span></td>
                        <td>${badge(c.status)}</td>
                        <td class="ab-note-cell">${esc(c.note || "—")}</td>
                    </tr>`
                ).join("");
            }
            if (cards) {
                cards.innerHTML = items.map((c) =>
                    `<div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${esc(c.customer_masked)}</strong>${badge(c.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Ngày</span><span>${esc((c.created_at || "").slice(0, 10))}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Giá trị đơn</span><span>${fmtMoney(c.order_amount)}</span></div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Hoa hồng</span><strong>${fmtMoney(c.commission_amount)}</strong></div>
                        ${c.note ? `<div class="ab-mcard-note">${esc(c.note)}</div>` : ""}
                    </div>`
                ).join("");
            }
        } catch (e) {
            setPanelError("affCommissionsError", String(e.message || e));
        } finally {
            setPanelLoading("affCommissionsLoading", false);
        }
    }

    async function loadPayouts() {
        setPanelLoading("affPayoutsLoading", true);
        setPanelError("affPayoutsError", null);
        try {
            const res = await apiGet("/affiliate/payouts");
            affLoaded.payouts = true;
            const items = (res.data && res.data.items) || [];
            const bal = (affOverview && affOverview.balances) || {};
            renderPayoutBalances(bal, affOverview && affOverview.min_payout_amount);

            const tbody = document.querySelector("#affPayoutsTable tbody");
            const cards = byId("affPayoutsCards");
            const empty = byId("affPayoutsEmpty");
            const tableWrap = byId("affPayoutsTableWrap");
            if (empty) empty.hidden = items.length > 0;
            if (tableWrap) tableWrap.hidden = items.length === 0;
            if (cards) cards.hidden = items.length === 0;
            if (tbody) {
                tbody.innerHTML = items.map((p) =>
                    `<tr>
                        <td>${esc((p.requested_at || "").slice(0, 10))}</td>
                        <td><strong>${fmtMoney(p.amount)}</strong></td>
                        <td>${badge(p.status)}</td>
                        <td class="ab-note-cell">${esc(p.note || p.transaction_ref || "—")}</td>
                    </tr>`
                ).join("");
            }
            if (cards) {
                cards.innerHTML = items.map((p) =>
                    `<div class="ab-mcard">
                        <div class="ab-mcard-row"><strong>${fmtMoney(p.amount)}</strong>${badge(p.status)}</div>
                        <div class="ab-mcard-row"><span class="ab-mcard-label">Ngày</span><span>${esc((p.requested_at || "").slice(0, 10))}</span></div>
                        ${(p.note || p.transaction_ref) ? `<div class="ab-mcard-note">${esc(p.note || p.transaction_ref)}</div>` : ""}
                    </div>`
                ).join("");
            }
        } catch (e) {
            setPanelError("affPayoutsError", String(e.message || e));
        } finally {
            setPanelLoading("affPayoutsLoading", false);
        }
    }

    async function requestPayout() {
        if (payoutRequestBusy) return;
        const bal = (affOverview && affOverview.balances) || {};
        const minAmt = Number((affOverview && affOverview.min_payout_amount) || 0);
        const hasBank = !!(affOverview && affOverview.payout_info && affOverview.payout_info.has_bank_info);
        if (!hasBank) {
            alert("Vui lòng cập nhật đủ thông tin ngân hàng trước khi rút tiền.");
            return;
        }
        if (Number(bal.withdrawable || 0) < minAmt) {
            alert("Số dư có thể rút chưa đạt mức tối thiểu " + fmtMoney(minAmt) + ".");
            return;
        }
        if (!window.confirm("Gửi yêu cầu rút toàn bộ số dư khả dụng?")) return;

        payoutRequestBusy = true;
        const buttons = [byId("btnAffRequestPayoutTab"), byId("btnAffRequestPayout")].filter(Boolean);
        buttons.forEach((btn) => {
            btn.disabled = true;
            btn.dataset.prevLabel = btn.textContent || "";
            btn.textContent = "Đang gửi…";
        });
        try {
            await apiPost("/affiliate/payout-request", {});
            affLoaded.payouts = false;
            await loadAffiliate();
            await loadPayouts();
            showToast("Đã gửi yêu cầu rút tiền!");
        } catch (e) {
            alert(String(e.message || e));
        } finally {
            payoutRequestBusy = false;
            buttons.forEach((btn) => {
                btn.textContent = btn.dataset.prevLabel || "Yêu cầu rút tiền";
            });
            renderPayoutBalances(
                (affOverview && affOverview.balances) || {},
                affOverview && affOverview.min_payout_amount
            );
        }
    }

    async function loadAffiliate() {
        const loading = byId("abAffLoading");
        const err = byId("abAffError");
        const notReg = byId("abAffNotRegistered");
        const reg = byId("abAffRegistered");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        try {
            const res = await apiGet("/affiliate/overview");
            affOverview = res.data || {};
            toggleAffiliateAdminUi(!!affOverview.show_admin_registrations);
            if (loading) loading.hidden = true;
            if (!affOverview.registered) {
                if (notReg) notReg.hidden = false;
                if (reg) reg.hidden = true;
                return;
            }
            if (notReg) notReg.hidden = true;
            if (reg) reg.hidden = false;
            renderOverviewStats(affOverview);
            affLoaded.referrals = false;
            affLoaded.commissions = false;
            affLoaded.payouts = false;
            const activeAffTab = document.querySelector(".ab-subtab.is-active");
            const tab = activeAffTab ? activeAffTab.getAttribute("data-aff-tab") : "overview";
            if (tab === "referrals") await loadReferrals();
            else if (tab === "commissions") await loadCommissions();
            else if (tab === "payout") await loadPayouts();
            else if (tab === "admin-registrations") await loadAdminRegistrations();
            else if (tab === "admin-payouts") await loadAdminPayouts();
        } catch (e) {
            if (loading) loading.hidden = true;
            if (err) { err.hidden = false; err.textContent = String(e.message || e); }
        }
    }

    function wireCopy(btnId, getText, label) {
        const btn = byId(btnId);
        if (!btn) return;
        btn.addEventListener("click", async () => {
            const text = typeof getText === "function" ? getText() : "";
            if (!text) return;
            await copyText(text);
            showToast(label || "Đã copy!");
        });
    }

    function wire() {
        document.querySelectorAll(".ab-tab").forEach((btn) => {
            btn.addEventListener("click", () => setMainTab(btn.getAttribute("data-ab-tab") || "profile"));
        });
        document.querySelectorAll("[data-plans-subtab]").forEach((btn) => {
            btn.addEventListener("click", () => setPlansSubTab(btn.getAttribute("data-plans-subtab") || "packages"));
        });
        const scrollPlansBtn = byId("btnAbScrollPlans");
        if (scrollPlansBtn) {
            scrollPlansBtn.addEventListener("click", () => goUpgradePlan());
        }
        const plansBuyCredit = byId("btnAbPlansBuyCredit");
        if (plansBuyCredit) plansBuyCredit.addEventListener("click", () => goBuyCredit());
        const overviewBuyCredit = byId("btnAbOverviewBuyCredit");
        if (overviewBuyCredit) overviewBuyCredit.addEventListener("click", () => goBuyCredit());
        const overviewUpgrade = byId("btnAbOverviewUpgrade");
        if (overviewUpgrade) overviewUpgrade.addEventListener("click", () => goUpgradePlan());
        document.querySelectorAll(".ab-subtab").forEach((btn) => {
            btn.addEventListener("click", () => setAffTab(btn.getAttribute("data-aff-tab") || "overview"));
        });
        document.querySelectorAll("[data-aff-goto]").forEach((btn) => {
            btn.addEventListener("click", () => setAffTab(btn.getAttribute("data-aff-goto") || "overview"));
        });
        ["affUtmSource", "affUtmMedium", "affUtmCampaign"].forEach((id) => {
            const el = byId(id);
            if (el) el.addEventListener("input", updateUtmPreview);
        });

        const regBtn = byId("btnAffRegister");
        if (regBtn) {
            regBtn.addEventListener("click", async () => {
                regBtn.disabled = true;
                try {
                    await apiPost("/affiliate/register", {});
                    showToast("Đã đăng ký Affiliate!");
                    await loadAffiliate();
                } catch (e) {
                    alert(String(e.message || e));
                } finally {
                    regBtn.disabled = false;
                }
            });
        }

        wireCopy("btnAffCopyOverview", () => byId("affOverviewLink") && byId("affOverviewLink").value, "Đã copy link!");
        wireCopy("btnAffCopyOverview2", () => byId("affOverviewLink") && byId("affOverviewLink").value, "Đã copy link!");
        wireCopy("btnAffCopyLink", () => byId("affLink") && byId("affLink").value, "Đã copy link!");
        wireCopy("btnAffCopyCode", () => byId("affCode") && byId("affCode").value, "Đã copy mã!");
        wireCopy("btnAffCopyUtm", () => byId("affUtmPreview") && byId("affUtmPreview").value, "Đã copy link UTM!");

        const payoutBtn = byId("btnAffRequestPayout");
        if (payoutBtn) payoutBtn.addEventListener("click", requestPayout);
        const payoutTabBtn = byId("btnAffRequestPayoutTab");
        if (payoutTabBtn) payoutTabBtn.addEventListener("click", requestPayout);

        const bankForm = byId("affBankForm");
        if (bankForm) {
            bankForm.addEventListener("submit", async (e) => {
                e.preventDefault();
                try {
                    await apiPut("/affiliate/payout-info", {
                        bank_name: byId("affBankName").value.trim(),
                        bank_account_name: byId("affBankOwner").value.trim(),
                        bank_account_number: byId("affBankNumber").value.trim(),
                    });
                    showToast("Đã lưu thông tin ngân hàng.");
                    await loadAffiliate();
                } catch (err) {
                    alert(String(err.message || err));
                }
            });
        }

        const affAdminSearch = byId("affAdminRegSearch");
        const affAdminStatus = byId("affAdminRegStatus");
        const affAdminRefresh = byId("btnAffAdminRegRefresh");
        let affAdminSearchTimer = null;
        if (affAdminSearch) {
            affAdminSearch.addEventListener("input", () => {
                clearTimeout(affAdminSearchTimer);
                affAdminSearchTimer = setTimeout(() => {
                    adminRegState.offset = 0;
                    affLoaded.adminReg = false;
                    void loadAdminRegistrations();
                }, 350);
            });
        }
        if (affAdminStatus) {
            affAdminStatus.addEventListener("change", () => {
                adminRegState.offset = 0;
                affLoaded.adminReg = false;
                void loadAdminRegistrations();
            });
        }
        if (affAdminRefresh) {
            affAdminRefresh.addEventListener("click", () => {
                affLoaded.adminReg = false;
                void loadAdminRegistrations();
            });
        }

        const affAdminDetailClose = byId("btnAffAdminRegDetailClose");
        const affAdminDetailModal = byId("affAdminRegDetailModal");
        if (affAdminDetailClose) {
            affAdminDetailClose.addEventListener("click", closeAffAdminRegModal);
        }
        if (affAdminDetailModal) {
            affAdminDetailModal.addEventListener("click", (e) => {
                if (e.target === affAdminDetailModal) closeAffAdminRegModal();
            });
        }

        const affAdminPayoutSearch = byId("affAdminPayoutSearch");
        const affAdminPayoutStatus = byId("affAdminPayoutStatus");
        const affAdminPayoutRefresh = byId("btnAffAdminPayoutRefresh");
        let affAdminPayoutSearchTimer = null;
        if (affAdminPayoutSearch) {
            affAdminPayoutSearch.addEventListener("input", () => {
                clearTimeout(affAdminPayoutSearchTimer);
                affAdminPayoutSearchTimer = setTimeout(() => {
                    adminPayoutState.offset = 0;
                    affLoaded.adminPayout = false;
                    void loadAdminPayouts();
                }, 350);
            });
        }
        if (affAdminPayoutStatus) {
            affAdminPayoutStatus.addEventListener("change", () => {
                adminPayoutState.offset = 0;
                affLoaded.adminPayout = false;
                void loadAdminPayouts();
            });
        }
        if (affAdminPayoutRefresh) {
            affAdminPayoutRefresh.addEventListener("click", () => {
                affLoaded.adminPayout = false;
                void loadAdminPayouts();
            });
        }
        const btnPayoutPaidCancel = byId("btnAffAdminPayoutPaidCancel");
        const btnPayoutPaidConfirm = byId("btnAffAdminPayoutPaidConfirm");
        if (btnPayoutPaidCancel) {
            btnPayoutPaidCancel.addEventListener("click", () => {
                markAdminPayoutId = null;
                closeAffAdminPayoutModal("affAdminPayoutPaidModal");
            });
        }
        if (btnPayoutPaidConfirm) {
            btnPayoutPaidConfirm.addEventListener("click", async () => {
                if (!markAdminPayoutId) return;
                try {
                    await apiPost(`/admin/api/affiliate/payouts/${markAdminPayoutId}/mark-paid`, {
                        transaction_ref: (byId("affAdminPayoutRef") && byId("affAdminPayoutRef").value.trim()) || null,
                        note: (byId("affAdminPayoutNote") && byId("affAdminPayoutNote").value.trim()) || null,
                    });
                    markAdminPayoutId = null;
                    closeAffAdminPayoutModal("affAdminPayoutPaidModal");
                    showToast("Đã xác nhận chuyển khoản.");
                    affLoaded.adminPayout = false;
                    await loadAdminPayouts();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        }
        const btnPayoutRejectCancel = byId("btnAffAdminPayoutRejectCancel");
        const btnPayoutRejectConfirm = byId("btnAffAdminPayoutRejectConfirm");
        if (btnPayoutRejectCancel) {
            btnPayoutRejectCancel.addEventListener("click", () => {
                rejectAdminPayoutId = null;
                closeAffAdminPayoutModal("affAdminPayoutRejectModal");
            });
        }
        if (btnPayoutRejectConfirm) {
            btnPayoutRejectConfirm.addEventListener("click", async () => {
                if (!rejectAdminPayoutId) return;
                const reason = (byId("affAdminPayoutRejectReason") && byId("affAdminPayoutRejectReason").value.trim()) || "";
                if (!reason) { alert("Nhập lý do từ chối."); return; }
                try {
                    await apiPost(`/admin/api/affiliate/payouts/${rejectAdminPayoutId}/reject`, { reason });
                    rejectAdminPayoutId = null;
                    closeAffAdminPayoutModal("affAdminPayoutRejectModal");
                    showToast("Đã từ chối yêu cầu rút tiền.");
                    affLoaded.adminPayout = false;
                    await loadAdminPayouts();
                } catch (e) {
                    alert(String(e.message || e));
                }
            });
        }

        const btnPaymentClose = byId("btnAbPaymentClose");
        if (btnPaymentClose) btnPaymentClose.addEventListener("click", closePaymentModal);
        const paymentModal = byId("abPaymentModal");
        if (paymentModal) {
            paymentModal.addEventListener("click", (e) => {
                if (e.target !== paymentModal) return;
                const successPanel = byId("abPaymentSuccess");
                if (!successPanel || successPanel.hidden) closePaymentModal();
            });
        }
        const btnCopyAccount = byId("btnAbCopyAccount");
        if (btnCopyAccount) {
            btnCopyAccount.addEventListener("click", async () => {
                const v = byId("abPayAccount") && byId("abPayAccount").textContent;
                if (v) { await copyText(v.trim()); showToast("Đã copy số tài khoản!"); }
            });
        }
        const btnCopyTransfer = byId("btnAbCopyTransfer");
        if (btnCopyTransfer) {
            btnCopyTransfer.addEventListener("click", async () => {
                const v = byId("abPayTransfer") && byId("abPayTransfer").textContent;
                if (v) { await copyText(v.trim()); showToast("Đã copy nội dung CK!"); }
            });
        }
        const btnPaymentRetry = byId("btnAbPaymentRetry");
        if (btnPaymentRetry) {
            btnPaymentRetry.addEventListener("click", () => {
                if (currentCheckoutProductCode) void startCheckout(currentCheckoutProductCode);
            });
        }
        const btnPaymentContactClose = byId("btnAbPaymentContactClose");
        if (btnPaymentContactClose) btnPaymentContactClose.addEventListener("click", closePaymentModal);

        const params = new URLSearchParams(window.location.search);
        const tab = params.get("tab") || "profile";
        setMainTab(tab);
        const resumeOrder =
            params.get("order_code") ||
            (paymentFlow().getPendingOrderCode ? paymentFlow().getPendingOrderCode() : "");
        if (resumeOrder) {
            void resumePendingCheckout(resumeOrder);
        }
        if (tab === "plans") {
            const plansSub = params.get("plans");
            if (plansSub) setPlansSubTab(plansSub);
            const planHighlight = params.get("plan");
            if (planHighlight) {
                window.setTimeout(() => {
                    const grid = byId("abPlansGrid");
                    if (!grid) return;
                    const card = grid.querySelector(`.ab-plan-card[data-plan="${String(planHighlight).toLowerCase()}"]`);
                    if (card) {
                        card.classList.add("is-target");
                        card.scrollIntoView({ behavior: "smooth", block: "center" });
                    }
                }, 600);
            }
        }
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
    else wire();
})();
