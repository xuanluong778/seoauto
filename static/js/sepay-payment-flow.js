/**
 * Shared SePay payment UX helpers (billing only).
 * Used by account-billing.js and digiseo-credit-modal.js.
 */
(function (global) {
    "use strict";

    var STORAGE_KEY = "digiseo_payment_order_code";

    function isPaymentSuccess(order) {
        if (!order) return false;
        var pollStatus = String(order.poll_status || order.status || "").toLowerCase();
        var status = String(order.status || "").toLowerCase();
        var activation = String(order.activation_status || "").toLowerCase();
        if (activation === "activation_failed") return false;
        return pollStatus === "success" || (status === "paid" && activation === "activated");
    }

    function isPaymentFailed(order) {
        if (!order) return false;
        var pollStatus = String(order.poll_status || "").toLowerCase();
        var status = String(order.status || "").toLowerCase();
        if (pollStatus === "failed") return true;
        if (status === "expired" || status === "cancelled") return true;
        return status === "paid" && String(order.activation_status || "") === "activation_failed";
    }

    function isPaymentPending(order) {
        if (!order) return false;
        if (isPaymentSuccess(order) || isPaymentFailed(order)) return false;
        var status = String(order.status || "").toLowerCase();
        return status === "pending" || status === "partial_paid";
    }

    function rememberPendingOrder(orderCode) {
        var code = String(orderCode || "").trim();
        if (!code) return;
        try {
            sessionStorage.setItem(STORAGE_KEY, code);
        } catch (_) {}
    }

    function clearPendingOrder() {
        try {
            sessionStorage.removeItem(STORAGE_KEY);
        } catch (_) {}
    }

    function getPendingOrderCode() {
        try {
            return sessionStorage.getItem(STORAGE_KEY) || "";
        } catch (_) {
            return "";
        }
    }

    function redirectToPaymentSuccess(orderCode, order) {
        var code = String(orderCode || "").trim();
        if (!code) return;
        clearPendingOrder();
        if (order && isPaymentSuccess(order)) {
            console.info(
                "[sepay-payment] redirect_success order_code=%s poll_status=%s status=%s",
                code,
                order.poll_status || "",
                order.status || ""
            );
        }
        global.location.assign(
            "/account-billing/payment-success?order_code=" + encodeURIComponent(code)
        );
    }

    global.DigiSeoPaymentFlow = {
        STORAGE_KEY: STORAGE_KEY,
        isPaymentSuccess: isPaymentSuccess,
        isPaymentFailed: isPaymentFailed,
        isPaymentPending: isPaymentPending,
        rememberPendingOrder: rememberPendingOrder,
        clearPendingOrder: clearPendingOrder,
        getPendingOrderCode: getPendingOrderCode,
        redirectToPaymentSuccess: redirectToPaymentSuccess,
    };
})(typeof window !== "undefined" ? window : globalThis);
