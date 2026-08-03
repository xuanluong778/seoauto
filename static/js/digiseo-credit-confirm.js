/**
 * Popup xác nhận credit trước tác vụ tốn phí.
 * Không gọi API bên ngoài — chỉ POST /api/credits/preview (nội bộ).
 */
(function () {
    "use strict";

    var PREVIEW_API = "/api/credits/preview";

    function readToken() {
        try {
            if (typeof window.DigiSeoGetAuthToken === "function") {
                var t = window.DigiSeoGetAuthToken();
                if (t) return t;
            }
            var m = document.cookie.match(/(?:^|;\s*)seo_token=([^;]*)/);
            if (m) return decodeURIComponent(m[1].replace(/\+/g, " ")).trim();
        } catch (_) {}
        return "";
    }

    function authHeaders(extra) {
        var h = Object.assign({}, extra || {});
        var t = readToken();
        if (t) h.Authorization = "Bearer " + t;
        return h;
    }

    function fmt(n) {
        return Number(n || 0).toLocaleString("vi-VN");
    }

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function removeBackdrop() {
        var el = document.getElementById("dccBackdrop");
        if (el) el.remove();
    }

    function openPricing() {
        if (typeof window.opendigiseoPricingModal === "function") {
            window.opendigiseoPricingModal("Nâng cấp gói để tiếp tục sử dụng tính năng này.");
            return;
        }
        window.location.href = "/pricing";
    }

    function openAddon() {
        window.location.href = "/account-billing";
    }

    function showModal(html, modalClass) {
        removeBackdrop();
        var wrap = document.createElement("div");
        wrap.id = "dccBackdrop";
        wrap.className = "dcc-backdrop";
        wrap.innerHTML =
            '<div class="dcc-modal' +
            (modalClass ? " " + modalClass : "") +
            '" role="dialog" aria-modal="true">' +
            html +
            "</div>";
        document.body.appendChild(wrap);
        return wrap;
    }

    function breakdownHtml(preview) {
        var lines = (preview.breakdown && preview.breakdown.lines) || preview.billing_lines || [];
        if (!lines.length) return "";
        var rows = lines
            .map(function (ln) {
                return (
                    '<div class="dcc-row dcc-row--sub"><span>' +
                    esc(ln.label || ln.key) +
                    '</span><strong>' +
                    fmt(ln.credit_cost) +
                    "</strong></div>"
                );
            })
            .join("");
        var sub = preview.breakdown && preview.breakdown.subtotal != null ? preview.breakdown.subtotal : null;
        var subRow =
            sub != null && Number(preview.credit_cost) !== Number(sub)
                ? '<div class="dcc-row dcc-row--sub"><span>Tạm tính</span><strong>' +
                  fmt(sub) +
                  "</strong></div>"
                : "";
        return '<div class="dcc-breakdown">' + rows + subRow + "</div>";
    }

    function waitConfirm(preview, opts) {
        opts = opts || {};
        return new Promise(function (resolve) {
            var highWarn = preview.high_cost_warning
                ? '<div class="dcc-alert dcc-alert--warn">Hành động này tốn <strong>' +
                  fmt(preview.credit_cost) +
                  " credit</strong> — vui lòng xác nhận trước khi chạy.</div>"
                : "";

            var quotaHtml =
                preview.quota_remaining != null
                    ? fmt(preview.quota_remaining) +
                      (preview.quota_limit != null ? " / " + fmt(preview.quota_limit) : "")
                    : "—";
            var balanceAfter =
                preview.credit_balance_after != null
                    ? preview.credit_balance_after
                    : Math.max(0, Number(preview.credit_balance || 0) - Number(preview.credit_cost || 0));

            var html =
                '<div class="dcc-head"><h3>Xác nhận sử dụng credit</h3><p>' +
                esc(preview.label || "Tác vụ tốn phí") +
                "</p></div>" +
                '<div class="dcc-body">' +
                breakdownHtml(preview) +
                '<div class="dcc-row"><span>Module</span><strong>' +
                esc(preview.module) +
                "</strong></div>" +
                '<div class="dcc-row"><span>Hành động</span><strong>' +
                esc(preview.action) +
                "</strong></div>" +
                '<div class="dcc-row"><span>Tổng credit sẽ trừ</span><strong class="is-cost">' +
                fmt(preview.credit_cost) +
                "</strong></div>" +
                '<div class="dcc-row"><span>Số dư credit hiện tại</span><strong>' +
                fmt(preview.credit_balance) +
                "</strong></div>" +
                '<div class="dcc-row"><span>Số dư còn lại sau khi chạy</span><strong>' +
                fmt(balanceAfter) +
                "</strong></div>" +
                '<div class="dcc-row"><span>Quota còn lại</span><strong>' +
                quotaHtml +
                (preview.quota_label ? " (" + esc(preview.quota_label) + ")" : "") +
                "</strong></div>" +
                '<div class="dcc-row"><span>Nguồn dữ liệu</span><strong>' +
                esc(preview.data_source_label || preview.data_source) +
                "</strong></div>" +
                highWarn +
                "</div>" +
                '<div class="dcc-foot">' +
                '<button type="button" class="dcc-btn dcc-btn--ghost" data-dcc-cancel>Hủy</button>' +
                '<button type="button" class="dcc-btn dcc-btn--primary" data-dcc-ok>Xác nhận & chạy</button>' +
                "</div>";

            var backdrop = showModal(html, preview.high_cost_warning ? "dcc-modal--warn" : "");
            backdrop.querySelector("[data-dcc-cancel]").addEventListener("click", function () {
                removeBackdrop();
                resolve(false);
            });
            backdrop.querySelector("[data-dcc-ok]").addEventListener("click", function () {
                removeBackdrop();
                resolve(true);
            });
            backdrop.addEventListener("click", function (ev) {
                if (ev.target === backdrop) {
                    removeBackdrop();
                    resolve(false);
                }
            });
        });
    }

    function showBlockedModal(title, message, primaryLabel, primaryAction) {
        return new Promise(function (resolve) {
            var html =
                '<div class="dcc-head"><h3>' +
                esc(title) +
                "</h3><p>" +
                esc(message) +
                "</p></div>" +
                '<div class="dcc-foot">' +
                '<button type="button" class="dcc-btn dcc-btn--ghost" data-dcc-close>Đóng</button>' +
                '<button type="button" class="dcc-btn dcc-btn--upgrade" data-dcc-primary>' +
                esc(primaryLabel) +
                "</button></div>";
            var backdrop = showModal(html, "dcc-modal--danger");
            backdrop.querySelector("[data-dcc-close]").addEventListener("click", function () {
                removeBackdrop();
                resolve(false);
            });
            backdrop.querySelector("[data-dcc-primary]").addEventListener("click", function () {
                removeBackdrop();
                primaryAction();
                resolve(false);
            });
        });
    }

    async function fetchQuoteApi(url, body) {
        var res = await fetch(url, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        var data = await res.json().catch(function () {
            return {};
        });
        if (!res.ok) {
            throw new Error(data.detail || data.message || "Không lấy được báo giá credit.");
        }
        if (data.preview) return normalizePreviewClient(data.preview);
        return normalizePreviewClient({
            credits_enabled: data.credits_enabled,
            module: data.module,
            action: data.action,
            label: data.label,
            credit_cost: data.credit_cost,
            credit_balance: data.credit_balance,
            sufficient_credits: data.sufficient_credits,
            quota_key: "ai_articles",
            data_source: data.data_source,
            data_source_label: data.data_source_label,
            high_cost_warning: data.high_cost_warning,
            high_cost_threshold: data.high_cost_threshold,
            can_proceed: data.can_proceed,
            breakdown: data.breakdown,
            billing_lines: data.lines,
        });
    }

    async function fetchPreview(body) {
        var res = await fetch(PREVIEW_API, {
            method: "POST",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body || {}),
        });
        var data = await res.json().catch(function () {
            return {};
        });
        if (!res.ok) {
            var msg =
                (data.detail && (data.detail.message || data.detail)) ||
                data.message ||
                "Không lấy được báo giá credit.";
            throw new Error(typeof msg === "string" ? msg : "Không lấy được báo giá credit.");
        }
        return data;
    }

    function normalizePreviewClient(data) {
        return {
            credits_enabled: data.credits_enabled !== false,
            module: data.module || "",
            action: data.action || "",
            label: data.label || "Tác vụ tốn phí",
            credit_cost: Number(data.credit_cost != null ? data.credit_cost : data.credit_required || 0),
            credit_balance: Number(data.credit_balance || 0),
            credit_balance_after:
                data.credit_balance_after != null
                    ? Number(data.credit_balance_after)
                    : Math.max(
                          0,
                          Number(data.credit_balance || 0) -
                              Number(data.credit_cost != null ? data.credit_cost : data.credit_required || 0)
                      ),
            sufficient_credits: data.sufficient_credits !== false,
            quota_key: data.quota_key,
            quota_label: data.quota_label,
            quota_remaining: data.quota_remaining,
            quota_limit: data.quota_limit,
            quota_exceeded: !!data.quota_exceeded,
            data_source: data.data_source || (data.from_cache ? "cache" : "api"),
            data_source_label:
                data.data_source_label ||
                (data.from_cache ? "Dữ liệu từ cache" : "Sẽ gọi API thật sau khi xác nhận"),
            high_cost_warning: !!data.high_cost_warning,
            high_cost_threshold: Number(data.high_cost_threshold || 40),
            can_proceed: data.can_proceed !== false,
            breakdown: data.breakdown,
        };
    }

    /**
     * Hiển thị popup xác nhận. Trả về true nếu user xác nhận, false nếu hủy/chặn.
     * opts: { module, action, quantity, fromCache, quotaKey, wordCount, label, leadMode, leadLimit, preview }
     */
    window.DigiSeoConfirmCredit = async function (opts) {
        opts = opts || {};
        if (!readToken()) return false;

        var preview;
        if (opts.preview) {
            preview = normalizePreviewClient(opts.preview);
        } else if (opts.quoteApi) {
            preview = await fetchQuoteApi(opts.quoteApi, opts.quoteBody || {});
        } else {
            preview = await fetchPreview({
                module: opts.module,
                action: opts.action,
                quantity: opts.quantity || 1,
                from_cache: !!opts.fromCache,
                quota_key: opts.quotaKey || null,
                word_count: opts.wordCount != null ? opts.wordCount : null,
                label: opts.label || null,
                lead_mode: opts.leadMode || null,
                lead_limit: opts.leadLimit != null ? opts.leadLimit : null,
            });
        }

        if (!preview.credits_enabled || preview.credit_cost <= 0) {
            return true;
        }

        if (preview.quota_exceeded) {
            await showBlockedModal(
                "Đã hết quota tháng",
                "Bạn đã dùng hết quota cho tính năng này. Nâng cấp gói để tiếp tục.",
                "Nâng cấp gói",
                openPricing
            );
            return false;
        }

        if (!preview.sufficient_credits) {
            var blockedMsg =
                preview.module === "content_ai"
                    ? "Bạn không đủ credit để tạo content. Vui lòng nạp thêm credit hoặc nâng cấp gói."
                    : "Cần " +
                      fmt(preview.credit_cost) +
                      " credit, bạn còn " +
                      fmt(preview.credit_balance) +
                      ". Mua thêm credit hoặc nâng cấp gói.";
            await showBlockedModal(
                preview.module === "content_ai" ? "Không đủ credit" : "Không đủ credit",
                blockedMsg,
                "Mua credit / Addon",
                openAddon
            );
            return false;
        }

        return waitConfirm(preview, opts);
    };

    /** Preset actions cho các module */
    window.DigiSeoCreditActions = {
        keywordResearch: {
            module: "keyword",
            action: "research_run",
            quotaKey: "keyword_research",
            label: "Keyword Research",
        },
        technicalAudit: {
            module: "audit",
            action: "technical_deep",
            quotaKey: "technical_audit",
            label: "Technical Audit",
        },
        seoScore: {
            module: "seo_score",
            action: "url_scoreboard",
            quotaKey: "seo_score",
            label: "SEO Score — URL",
        },
        seoScoreAiFix: {
            module: "seo_score",
            action: "ai_fix",
            quotaKey: "seo_score",
            label: "SEO Score — Sửa bằng AI",
        },
        contentBrief: {
            module: "content_ai",
            action: "brief_suggest",
            quotaKey: "ai_articles",
            label: "Content AI — gợi ý",
        },
        contentArticle: function (wordCount) {
            return {
                module: "content_ai",
                action: "article_short",
                quotaKey: "ai_articles",
                label: "Content AI — viết bài",
                wordCount: wordCount,
            };
        },
        contentArticleQuote: function (body) {
            return {
                quoteApi: "/content-ai/credit-quote",
                quoteBody: body || {},
            };
        },
        googleImage: {
            module: "content_ai",
            action: "google_image",
            quotaKey: "ai_articles",
            label: "Ảnh Google/CSE",
        },
        aiImage: {
            module: "content_ai",
            action: "ai_image",
            quotaKey: "ai_articles",
            label: "Ảnh AI",
        },
        cauSeoFix: {
            module: "cau",
            action: "seo_ai_fix",
            quotaKey: "ai_articles",
            label: "Auto Update — Sửa SEO AI",
        },
        cauRewrite: {
            module: "cau",
            action: "modal_rewrite",
            quotaKey: "ai_articles",
            label: "Auto Update — Viết lại",
        },
        cauAppend: {
            module: "cau",
            action: "modal_append",
            quotaKey: "ai_articles",
            label: "Auto Update — Thêm heading",
        },
        leadScan: function (mode, limit, fromCache) {
            return {
                module: "lead_scanner",
                action: "basic_scan",
                quotaKey: "lead_scan",
                label: "Lead Map Scanner",
                leadMode: mode,
                leadLimit: limit,
                fromCache: !!fromCache,
            };
        },
        leadDetail: {
            module: "lead_scanner",
            action: "place_detail",
            quotaKey: "lead_detail",
            label: "Lead — chi tiết SĐT",
        },
        chatbotReply: {
            module: "chatbot_cskh",
            action: "reply_overage",
            quotaKey: "chatbot_reply",
            label: "Chatbot CSKH — trả lời AI",
        },
    };
})();
