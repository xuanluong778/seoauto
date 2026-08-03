/**
 * Global quota / credit error handler — popup nâng cấp hoặc mua addon.
 */
(function () {
    "use strict";

    function detailMessage(detail) {
        if (!detail) return "Đã hết quota hoặc không đủ credit.";
        if (typeof detail === "string") return detail;
        return String(detail.message || detail.error || "Đã hết quota hoặc không đủ credit.");
    }

    function shouldHandle(detail, status) {
        if (!detail || typeof detail !== "object") return false;
        const code = String(detail.code || "").toLowerCase();
        if (detail.upgrade_required === true) return true;
        if (code === "quota_exceeded" || code === "insufficient_credits") return true;
        if (code === "plan_required" || code === "daily_limit" || code === "monthly_limit") return true;
        if (code === "bot_limit_exceeded" || code === "reply_limit_exceeded") return true;
        if (status === 402 || status === 429) return true;
        return false;
    }

    function openPricing(message) {
        const url = (message && message.upgrade_url) || "/pricing";
        if (url.indexOf("/account/billing") >= 0 || url.indexOf("plans=credit") >= 0) {
            if (typeof window.DigiSeoOpenCreditModal === "function") {
                window.DigiSeoOpenCreditModal();
                return true;
            }
        }
        if (typeof window.opendigiseoPricingModal === "function") {
            window.opendigiseoPricingModal(message);
            return true;
        }
        window.location.href = url;
        return true;
    }

    function openAddon() {
        if (typeof window.DigiSeoOpenCreditModal === "function") {
            window.DigiSeoOpenCreditModal();
            return;
        }
        window.location.href = "/account-billing?tab=plans&plans=credit";
    }

    function showQuotaDialog(detail) {
        const msg = detailMessage(detail);
        const code = String((detail && detail.code) || "");
        const useAddon = code === "insufficient_credits" || code === "reply_limit_exceeded";
        const choice = window.confirm(
            msg +
                "\n\n" +
                (useAddon
                    ? "Bấm OK để mua thêm credit/addon, Cancel để xem nâng cấp gói."
                    : "Bấm OK để xem bảng giá nâng cấp gói, Cancel để đóng.")
        );
        if (choice) {
            if (useAddon) openAddon();
            else openPricing(detail);
        }
    }

    function handleFetchResponse(res, data) {
        const detail = data && (data.detail || data);
        if (!shouldHandle(detail, res && res.status)) return false;
        showQuotaDialog(typeof detail === "object" ? detail : { message: detail });
        return true;
    }

    window.DigiSeoHandleQuotaResponse = function (errOrRes, data) {
        if (errOrRes && errOrRes.status) {
            return handleFetchResponse(errOrRes, data);
        }
        const d = errOrRes && errOrRes.detail ? errOrRes : errOrRes;
        if (shouldHandle(d, 403)) {
            showQuotaDialog(d);
            return true;
        }
        return false;
    };

    window.DigiSeoQuotaFromFetch = async function (res) {
        let data = {};
        try {
            data = await res.clone().json();
        } catch (_) {}
        if (handleFetchResponse(res, data)) {
            const err = new Error(detailMessage(data.detail || data));
            err.quotaHandled = true;
            throw err;
        }
        return data;
    };
})();
