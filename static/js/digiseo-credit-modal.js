/**
 * Popup mua credit — khung tab "Mua thêm credit" (account-billing).
 */
(function () {
    "use strict";

    var PAYMENT_POLL_MS = 4000;
    var pollTimer = null;
    var catalogCache = null;
    var currentProductCode = null;
    var wired = false;

    function byId(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function fmtVnd(n) {
        return Number(n || 0).toLocaleString("vi-VN") + " ₫";
    }

    function readToken() {
        if (typeof window.DigiSeoGetAuthToken === "function") {
            return window.DigiSeoGetAuthToken();
        }
        try {
            var t = (sessionStorage.getItem("seo_token") || "").trim();
            if (t) return t;
            var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            return m ? decodeURIComponent(m[1].replace(/\+/g, " ")).trim() : "";
        } catch (_) {
            return "";
        }
    }

    function authHeaders(extra) {
        var h = Object.assign({}, extra || {});
        var t = readToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function apiGet(path) {
        return fetch(path, { headers: authHeaders(), cache: "no-store" }).then(function (r) {
            return r.json().then(function (d) {
                if (!r.ok) {
                    var msg = (d && d.detail) || (d && d.message) || "HTTP " + r.status;
                    throw new Error(typeof msg === "string" ? msg : "Lỗi tải dữ liệu");
                }
                return d;
            });
        });
    }

    function apiPost(path, body) {
        return fetch(path, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
            cache: "no-store",
        }).then(function (r) {
            return r.json().then(function (d) {
                if (!r.ok) {
                    var detail = d && d.detail;
                    if (detail && typeof detail === "object" && detail.message) {
                        throw new Error(String(detail.message));
                    }
                    throw new Error(typeof detail === "string" ? detail : (d && d.message) || "HTTP " + r.status);
                }
                return d;
            });
        });
    }

    function openOverlay(modal) {
        if (!modal) return;
        modal.hidden = false;
        modal.classList.add("is-open");
        document.body.style.overflow = "hidden";
    }

    function closeOverlay(modal) {
        if (!modal) return;
        modal.classList.remove("is-open");
        modal.hidden = true;
        if (!byId("dcmCreditModal") || byId("dcmCreditModal").hidden) {
            if (!byId("dcmPayModal") || byId("dcmPayModal").hidden) {
                document.body.style.overflow = "";
            }
        }
    }

    function stopPoll() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function closeCreditModal() {
        closeOverlay(byId("dcmCreditModal"));
    }

    function closePayModal() {
        stopPoll();
        closeOverlay(byId("dcmPayModal"));
        document.body.style.overflow = "";
    }

    function closeAll() {
        closePayModal();
        closeCreditModal();
        document.body.style.overflow = "";
    }

    function ensureModalDom() {
        return !!(byId("dcmCreditModal") && byId("dcmPayModal"));
    }

    function injectModalIfNeeded() {
        if (ensureModalDom()) return Promise.resolve();
        return fetch("/static/html/digiseo-credit-modal.html", { cache: "no-store" })
            .then(function (r) { return r.text(); })
            .then(function (html) {
                var wrap = document.createElement("div");
                wrap.innerHTML = html.trim();
                while (wrap.firstChild) {
                    document.body.appendChild(wrap.firstChild);
                }
                wireEvents();
            });
    }

    function renderCreditTable(catalog) {
        var loading = byId("dcmLoading");
        var err = byId("dcmLoadError");
        var content = byId("dcmCreditContent");
        var body = byId("dcmCreditAddonBody");
        var notes = byId("dcmCreditAddonNotes");
        var packs = (catalog && catalog.credit_addons) || [];

        if (loading) loading.hidden = true;
        if (!packs.length) {
            if (err) {
                err.hidden = false;
                err.textContent = "Chưa có gói credit. Vui lòng liên hệ hỗ trợ.";
            }
            return;
        }
        if (err) err.hidden = true;
        if (content) content.hidden = false;

        if (body) {
            body.innerHTML = packs.map(function (row) {
                return (
                    "<tr>" +
                    '<td class="ab-addon-price">' + esc(fmtVnd(row.price)) + "</td>" +
                    "<td>" + esc(Number(row.credits || 0).toLocaleString("vi-VN")) + " credit</td>" +
                    '<td class="ab-addon-action">' +
                    '<button type="button" class="ab-btn ab-btn-sm dcm-select-btn" data-dcm-buy="' + esc(row.product_code) + '">Chọn</button>' +
                    "</td></tr>"
                );
            }).join("");
            body.querySelectorAll("[data-dcm-buy]").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    startCheckout(btn.getAttribute("data-dcm-buy"));
                });
            });
        }
        if (notes) {
            notes.innerHTML = (catalog.credit_addon_notes || [])
                .map(function (n) { return "<li>" + esc(n) + "</li>"; })
                .join("");
        }
    }

    function loadCatalog() {
        var loading = byId("dcmLoading");
        var err = byId("dcmLoadError");
        var content = byId("dcmCreditContent");
        if (loading) loading.hidden = false;
        if (err) err.hidden = true;
        if (content) content.hidden = true;

        if (catalogCache) {
            renderCreditTable(catalogCache);
            return;
        }
        apiGet("/api/saas/billing-catalog")
            .then(function (data) {
                catalogCache = data;
                renderCreditTable(data);
            })
            .catch(function (e) {
                if (loading) loading.hidden = true;
                if (err) {
                    err.hidden = false;
                    err.textContent = String(e.message || e);
                }
            });
    }

    function resetPayPanels() {
        ["dcmPayLoading", "dcmPayContent", "dcmPaySuccess", "dcmPayExpired", "dcmPayError"].forEach(function (id) {
            var el = byId(id);
            if (el) el.hidden = true;
        });
        var qrWrap = byId("dcmPayQrWrap");
        if (qrWrap) qrWrap.hidden = true;
    }

    function paymentBreakdown(order) {
        var raw = order || {};
        var vatPct = raw.vat_percent != null ? Number(raw.vat_percent) : 10;
        if (!Number.isFinite(vatPct) || vatPct < 0) vatPct = 10;
        var total = Number(raw.amount);
        var base = raw.base_amount != null ? Number(raw.base_amount) : NaN;
        var vat = raw.vat_amount != null ? Number(raw.vat_amount) : NaN;
        if ((!Number.isFinite(base) || !Number.isFinite(vat)) && Number.isFinite(total) && total > 0) {
            if (vatPct > 0) {
                base = Math.round(total / (1 + vatPct / 100));
                vat = total - base;
            } else {
                base = total;
                vat = 0;
            }
        }
        return {
            base: base || 0,
            vat: vat || 0,
            total: Number.isFinite(total) && total > 0 ? total : (base + vat),
            vatPct: vatPct,
        };
    }

    function showPaymentPending(order) {
        resetPayPanels();
        var content = byId("dcmPayContent");
        if (content) content.hidden = false;
        var b = paymentBreakdown(order);
        if (byId("dcmPayProductName")) byId("dcmPayProductName").textContent = order.product_name || order.product_code || "—";
        if (byId("dcmPayBase")) byId("dcmPayBase").textContent = fmtVnd(b.base);
        if (byId("dcmPayVat")) byId("dcmPayVat").textContent = fmtVnd(b.vat);
        if (byId("dcmPayVatPct")) byId("dcmPayVatPct").textContent = String(b.vatPct);
        if (byId("dcmPayAmount")) byId("dcmPayAmount").textContent = fmtVnd(b.total);
        if (byId("dcmPayBank")) byId("dcmPayBank").textContent = order.bank_code || "—";
        if (byId("dcmPayHolder")) byId("dcmPayHolder").textContent = order.bank_holder || "—";
        if (byId("dcmPayAccount")) byId("dcmPayAccount").textContent = order.bank_account || "—";
        if (byId("dcmPayTransfer")) byId("dcmPayTransfer").textContent = order.transfer_content || order.order_code || "—";
        var qrWrap = byId("dcmPayQrWrap");
        var qrImg = byId("dcmPayQrImg");
        if (order.qr_url && qrWrap && qrImg) {
            qrImg.src = order.qr_url;
            qrWrap.hidden = false;
        } else if (qrWrap) {
            qrWrap.hidden = true;
        }
        if (byId("dcmPayExpire")) {
            var expIso = order.expired_at || order.expires_at;
            if (expIso) {
                try {
                    byId("dcmPayExpire").textContent =
                        "Đơn hết hạn lúc " + new Date(expIso).toLocaleString("vi-VN") + ".";
                } catch (_) {}
            } else {
                byId("dcmPayExpire").textContent = "";
            }
        }
    }

    function redirectToPaymentSuccess(orderCode, order) {
        stopPoll();
        var flow = window.DigiSeoPaymentFlow || {};
        if (flow.redirectToPaymentSuccess) {
            flow.redirectToPaymentSuccess(orderCode, order);
            return;
        }
        window.location.assign(
            "/account-billing/payment-success?order_code=" + encodeURIComponent(orderCode)
        );
    }

    function isOrderPaymentSuccess(order) {
        var flow = window.DigiSeoPaymentFlow || {};
        if (flow.isPaymentSuccess) return flow.isPaymentSuccess(order);
        var status = String(order.status || "");
        var pollStatus = String(order.poll_status || status);
        var activation = String(order.activation_status || "");
        return pollStatus === "success" || (status === "paid" && activation === "activated");
    }

    function showPaymentSuccess(order) {
        redirectToPaymentSuccess(order.order_code || "", order);
    }

    function showPaymentExpired() {
        resetPayPanels();
        var el = byId("dcmPayExpired");
        if (el) el.hidden = false;
    }

    function showPaymentError(msg) {
        resetPayPanels();
        var el = byId("dcmPayError");
        if (el) {
            el.hidden = false;
            el.textContent = msg || "Không thể tạo đơn thanh toán.";
        }
    }

    function pollOrder(orderCode) {
        apiGet("/api/saas/payment-orders/" + encodeURIComponent(orderCode) + "/status")
            .then(function (order) {
                var status = String(order.status || "");
                var pollStatus = String(order.poll_status || status);
                var activation = String(order.activation_status || "");
                if (status === "paid" && activation === "activation_failed") {
                    stopPoll();
                    showPaymentError(
                        "Thanh toán đã nhận nhưng kích hoạt credit chưa xong. Vui lòng F5 hoặc liên hệ hỗ trợ."
                    );
                    return;
                }
                if (isOrderPaymentSuccess(order) || pollStatus === "success") {
                    stopPoll();
                    redirectToPaymentSuccess(order.order_code || orderCode, order);
                    return;
                }
                if (status === "partial_paid") {
                    stopPoll();
                    var need = order.amount != null ? Number(order.amount).toLocaleString("vi-VN") : "";
                    showPaymentError(
                        need
                            ? "Đã nhận chuyển khoản thiếu tiền (cần " + need + "₫)."
                            : "Đã nhận chuyển khoản thiếu tiền."
                    );
                    return;
                }
                if (status === "expired" || status === "cancelled") {
                    stopPoll();
                    showPaymentExpired();
                }
            })
            .catch(function () {});
    }

    function startPoll(orderCode) {
        stopPoll();
        pollOrder(orderCode);
        pollTimer = setInterval(function () { pollOrder(orderCode); }, PAYMENT_POLL_MS);
    }

    function openPayModal() {
        resetPayPanels();
        var loading = byId("dcmPayLoading");
        if (loading) loading.hidden = false;
        openOverlay(byId("dcmPayModal"));
    }

    function startCheckout(productCode) {
        var code = String(productCode || "").trim();
        if (!code) return;
        currentProductCode = code;
        closeCreditModal();
        openPayModal();
        apiPost("/api/saas/create-payment-order", { product_code: code })
            .then(function (res) {
                if (res.contact_sales) {
                    showPaymentError(res.message || "Gói này cần liên hệ kinh doanh.");
                    return;
                }
                if (!res.order_code) {
                    showPaymentError(res.message || "Không tạo được đơn.");
                    return;
                }
                var flow = window.DigiSeoPaymentFlow || {};
                if (flow.rememberPendingOrder) flow.rememberPendingOrder(res.order_code);
                apiGet("/api/saas/payment-orders/" + encodeURIComponent(res.order_code) + "/status")
                    .then(function (status) {
                        if (isOrderPaymentSuccess(status)) {
                            redirectToPaymentSuccess(res.order_code, status);
                            return;
                        }
                        showPaymentPending(res);
                        startPoll(res.order_code);
                    })
                    .catch(function () {
                        showPaymentPending(res);
                        startPoll(res.order_code);
                    });
            })
            .catch(function (e) {
                showPaymentError(String(e.message || e));
            });
    }

    function buyFirstPack() {
        var packs = (catalogCache && catalogCache.credit_addons) || [];
        if (packs[0] && packs[0].product_code) {
            startCheckout(packs[0].product_code);
        }
    }

    function copyText(text) {
        var v = String(text || "").trim();
        if (!v) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(v).catch(function () {});
        }
    }

    function wireEvents() {
        if (wired) return;
        if (!byId("dcmCreditModal")) return;
        wired = true;

        byId("dcmCloseBtn") && byId("dcmCloseBtn").addEventListener("click", closeAll);
        byId("dcmPayCloseBtn") && byId("dcmPayCloseBtn").addEventListener("click", closePayModal);
        byId("dcmBuyCreditBtn") && byId("dcmBuyCreditBtn").addEventListener("click", buyFirstPack);
        byId("dcmPayRetry") && byId("dcmPayRetry").addEventListener("click", function () {
            closePayModal();
            if (currentProductCode) startCheckout(currentProductCode);
            else openModal();
        });
        byId("dcmCopyAccount") && byId("dcmCopyAccount").addEventListener("click", function () {
            copyText(byId("dcmPayAccount") && byId("dcmPayAccount").textContent);
        });
        byId("dcmCopyTransfer") && byId("dcmCopyTransfer").addEventListener("click", function () {
            copyText(byId("dcmPayTransfer") && byId("dcmPayTransfer").textContent);
        });

        [byId("dcmCreditModal"), byId("dcmPayModal")].forEach(function (modal) {
            if (!modal) return;
            modal.addEventListener("click", function (e) {
                if (e.target === modal) {
                    if (modal.id === "dcmPayModal") closePayModal();
                    else closeAll();
                }
            });
        });

        document.addEventListener("keydown", function (e) {
            if (e.key !== "Escape") return;
            if (byId("dcmPayModal") && !byId("dcmPayModal").hidden) closePayModal();
            else if (byId("dcmCreditModal") && !byId("dcmCreditModal").hidden) closeAll();
        });
    }

    function openModal() {
        injectModalIfNeeded().then(function () {
            if (!ensureModalDom()) {
                window.location.href = "/account-billing?tab=plans&plans=credit";
                return;
            }
            wireEvents();
            var token = readToken();
            if (!token) {
                if (typeof window.DigiSeoOpenAuthModal === "function") {
                    window.DigiSeoOpenAuthModal("login");
                } else {
                    window.location.href = "/tool";
                }
                return;
            }
            openOverlay(byId("dcmCreditModal"));
            loadCatalog();
        }).catch(function () {
            window.location.href = "/account-billing?tab=plans&plans=credit";
        });
    }

    function interceptCreditLinks() {
        document.addEventListener("click", function (e) {
            var buyBtn = e.target && e.target.closest ? e.target.closest("[data-digiseo-buy-credit]") : null;
            if (buyBtn) {
                e.preventDefault();
                openModal();
                return;
            }
            var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
            if (!a) return;
            var href = String(a.getAttribute("href") || "").trim();
            var path = href.split("?")[0].replace(/\/+$/, "") || "/";
            if (path === "/account/billing") {
                e.preventDefault();
                openModal();
            }
        });
    }

    window.DigiSeoOpenCreditModal = openModal;

    function init() {
        wireEvents();
        interceptCreditLinks();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
