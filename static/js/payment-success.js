(function () {
    "use strict";

    function byId(id) {
        return document.getElementById(id);
    }

    function fmtMoney(n) {
        var v = Number(n);
        if (!Number.isFinite(v)) return "—";
        return v.toLocaleString("vi-VN") + "₫";
    }

    function fmtDateTime(iso) {
        if (!iso) return "—";
        try {
            return new Date(iso).toLocaleString("vi-VN", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
            });
        } catch (_) {
            return "—";
        }
    }

    function apiGet(url) {
        var headers = { Accept: "application/json" };
        if (window.DigiSeoAuth && typeof window.DigiSeoAuth.authHeaders === "function") {
            Object.assign(headers, window.DigiSeoAuth.authHeaders());
        }
        return fetch(url, { credentials: "same-origin", headers: headers }).then(function (res) {
            if (!res.ok) {
                return res.json().catch(function () { return {}; }).then(function (body) {
                    var msg = (body && body.detail) || res.statusText || "Lỗi tải dữ liệu";
                    if (typeof msg === "object" && msg.message) msg = msg.message;
                    throw new Error(String(msg));
                });
            }
            return res.json();
        });
    }

    function showError(msg) {
        var loading = byId("psLoading");
        var card = byId("psCard");
        var err = byId("psError");
        if (loading) loading.hidden = true;
        if (card) card.hidden = true;
        if (err) {
            err.hidden = false;
            err.textContent = msg || "Không thể tải thông tin đơn hàng.";
        }
    }

    function renderSuccess(order) {
        var loading = byId("psLoading");
        var card = byId("psCard");
        var err = byId("psError");
        if (loading) loading.hidden = true;
        if (err) err.hidden = true;
        if (card) card.hidden = false;

        if (byId("psOrderCode")) byId("psOrderCode").textContent = order.order_code || "—";
        if (byId("psProductName")) {
            byId("psProductName").textContent = order.product_name || order.product_code || "—";
        }
        if (byId("psAmount")) byId("psAmount").textContent = fmtMoney(order.amount);
        if (byId("psPaidAt")) byId("psPaidAt").textContent = fmtDateTime(order.paid_at);

        if (window.DigiSeoPaymentFlow && typeof window.DigiSeoPaymentFlow.clearPendingOrder === "function") {
            window.DigiSeoPaymentFlow.clearPendingOrder();
        }
        if (typeof window.refreshDigiSeoNavAccount === "function") {
            window.refreshDigiSeoNavAccount();
        }
        window.dispatchEvent(new CustomEvent("digiseo-credit-purchased"));

        console.info(
            "[sepay-payment] success_page order_code=%s poll_status=%s status=%s amount=%s",
            order.order_code,
            order.poll_status,
            order.status,
            order.amount
        );
    }

    async function init() {
        var params = new URLSearchParams(window.location.search);
        var orderCode = String(params.get("order_code") || "").trim();
        if (!orderCode) {
            showError("Thiếu mã đơn hàng.");
            return;
        }

        try {
            var order = await apiGet(
                "/api/saas/payment-orders/" + encodeURIComponent(orderCode) + "/status"
            );
            var flow = window.DigiSeoPaymentFlow;
            if (flow && typeof flow.isPaymentSuccess === "function" && flow.isPaymentSuccess(order)) {
                renderSuccess(order);
                return;
            }
            if (flow && typeof flow.isPaymentPending === "function" && flow.isPaymentPending(order)) {
                window.location.replace(
                    "/account-billing?order_code=" + encodeURIComponent(orderCode) + "&tab=payment"
                );
                return;
            }
            showError("Đơn hàng chưa thanh toán thành công hoặc đã hết hạn.");
        } catch (e) {
            showError(String(e.message || e));
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        void init();
    }
})();
