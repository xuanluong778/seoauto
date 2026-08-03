/**
 * Seoauto Pricing — modal (Upgrade plan) + page /pricing.
 * Plans from /api/saas/plans or SSR JSON; legacy static fallback for modal only.
 */
(function () {
    const VND_PER_USD = 25000;

    const DURATIONS = [
        { id: "m6", label: "6 months", months: 6 },
        { id: "y1", label: "1 year", months: 12 },
        { id: "y2", label: "2 years", months: 24 },
        { id: "life", label: "Lifetime", months: null },
    ];

    const FEATURE_LABELS = {
        content_ai_article: "AI article writing",
        content_ai_bulk_article: "Bulk content AI",
        technical_audit: "Technical SEO audit",
        seo_score: "URL SEO scoreboard",
        keyword_research: "Keyword research",
        keyword_cluster: "Keyword clustering",
        schema_generate: "Schema JSON-LD",
        wp_publish: "WordPress publishing",
        image_generate: "AI image generation",
        chatbot_message: "Chatbot messages",
        knowledge_base_search: "Knowledge base search",
        wordpress_site: "Dự án website",
        internal_link: "Internal Links",
    };

    const PRICING_SLUG_ORDER = ["starter", "pro", "agency", "business"];
    const FREE_TRIAL_SLUG = "free_trial_5d"; // legacy — hidden from public pricing UI
    const PRICING_SLUGS = new Set(PRICING_SLUG_ORDER);

    const FREE_TRIAL_DISPLAY_ROWS = [
        { included: true, label: "1 project" },
        { included: true, label: "10 bài viết AI / 5 ngày (demo)" },
        { included: true, label: "Tối đa 3 bài / ngày" },
        { included: true, label: "Check Technical SEO 3 lần" },
        { included: true, label: "Research 200 keyword (demo)" },
        { included: true, label: "BYOK — dùng API key riêng" },
        { included: false, label: "API pool SEOAuto (volume cao)" },
        { included: false, label: "Bulk Content AI" },
        { included: false, label: "Google Search Console" },
        { included: false, label: "Hỗ trợ ưu tiên" },
    ];

    const LEGACY_PLANS = [
        { id: "starter", name: "Basic", popular: false, priceMonthly: 399000, billingCycle: "monthly", limits: [], legacy: true, articles: "30 bài AI/tháng", projects: "3 website/project", devices: "1 user", gsc: true, priority: false },
        { id: "pro", name: "Pro", popular: true, priceMonthly: 799000, billingCycle: "monthly", limits: [], legacy: true, articles: "80 bài AI/tháng", projects: "8 website/project", devices: "3 user", gsc: true, priority: false },
        { id: "agency", name: "Agency", popular: false, priceMonthly: 1690000, billingCycle: "monthly", limits: [], legacy: true, articles: "200 bài AI/tháng", projects: "20 website/project", devices: "5 user", gsc: true, priority: true },
        { id: "business", name: "Business", popular: false, priceMonthly: 3490000, billingCycle: "monthly", limits: [], legacy: true, articles: "500 bài AI/tháng", projects: "50 website/project", devices: "10 user", gsc: true, priority: true },
    ];

    const PAID_SLUGS = new Set(["starter", "pro", "agency", "business"]);

    const PAID_CATALOG = {
        starter: {
            articles: "30 bài AI/tháng",
            projects: "3 website/project",
            devices: "1 user",
            gsc: true,
            priority_support: false,
        },
        pro: {
            articles: "80 bài AI/tháng",
            projects: "8 website/project",
            devices: "3 user",
            gsc: true,
            priority_support: false,
        },
        agency: {
            articles: "200 bài AI/tháng",
            projects: "20 website/project",
            devices: "5 user",
            gsc: true,
            priority_support: true,
        },
        business: {
            articles: "500 bài AI/tháng",
            projects: "50 website/project",
            devices: "10 user",
            gsc: true,
            priority_support: true,
        },
    };

    const PAID_FEATURE_ROWS = [
        { key: "ai_write", label: "AI article writing" },
        { key: "ai_image", label: "AI image generation" },
        { key: "wp_pub", label: "WordPress publishing" },
        { key: "internal_links", label: "Internal Links" },
        { key: "knowledge", label: "knowledge_base" },
        { key: "gsc", label: "Google Search Console" },
        { key: "priority", label: "Priority support" },
    ];

    const LEGACY_FEATS = PAID_FEATURE_ROWS.slice();

    let state = { duration: "m6", payment: "payos" };
    let plans = [];
    let currentPlanSlug = null;
    const isPage = !!document.getElementById("digiseoPricingPage");

    function formatVnd(n) {
        const x = Math.round(Number(n) || 0);
        return x.toLocaleString("vi-VN") + "đ";
    }

    function formatUsd(n) {
        const usd = (Number(n) || 0) / VND_PER_USD;
        return "$" + Math.max(1, Math.round(usd)).toLocaleString("en-US");
    }

    function labelForFeature(key) {
        return FEATURE_LABELS[key] || String(key || "").replace(/_/g, " ");
    }

    function limitLine(ul) {
        const val = Number(ul.limit_value);
        const periodMap = { monthly: "month", daily: "day", yearly: "year" };
        const period = periodMap[ul.period] || ul.period || "";
        if (val === -1) return "Unlimited" + (period ? " / " + period : "");
        if (val === 0 && ul.is_hard_limit) return "Not included";
        return String(val).replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (period ? " / " + period : "");
    }

    function paidFlagsForSlug(slug) {
        const cfg = PAID_CATALOG[slug] || {};
        return {
            ai_write: true,
            ai_image: true,
            wp_pub: true,
            internal_links: true,
            knowledge: true,
            gsc: !!cfg.gsc,
            priority: !!cfg.priority_support,
        };
    }

    function attachFreeTrialDisplay(plan) {
        plan.planKind = "free_trial";
        plan.trialDays = plan.trialDays || 5;
        plan.byokNote = plan.byokNote || "Yêu cầu API key cá nhân";
        if (!plan.displayRows || !plan.displayRows.length) {
            plan.displayRows = FREE_TRIAL_DISPLAY_ROWS.slice();
        }
        return plan;
    }

    function attachPaidDisplay(plan) {
        const cfg = PAID_CATALOG[plan.id];
        if (!cfg) return plan;
        plan.articles = cfg.articles;
        plan.projects = cfg.projects;
        plan.devices = cfg.devices;
        plan.gsc = cfg.gsc;
        plan.priority = cfg.priority_support;
        plan.featureFlags = paidFlagsForSlug(plan.id);
        return plan;
    }

    function sortPricingPlans(list) {
        const order = {};
        PRICING_SLUG_ORDER.forEach((id, i) => {
            order[id] = i;
        });
        return (list || []).slice().sort((a, b) => (order[a.id] ?? 99) - (order[b.id] ?? 99));
    }

    function normalizeFromApiItem(p) {
        const limits = (p.usage_limits || []).map((ul) => ({
            feature_key: ul.feature_key,
            label: labelForFeature(ul.feature_key),
            display: limitLine(ul),
            limit_value: ul.limit_value,
            is_hard_limit: ul.is_hard_limit,
        }));
        const base = {
            id: p.slug,
            name: p.name,
            popular: p.slug === "pro",
            priceMonthly: Number(p.price_amount) || 0,
            billingCycle: p.billing_cycle || "monthly",
            limits,
            legacy: false,
        };
        if (p.slug === FREE_TRIAL_SLUG) return attachFreeTrialDisplay(base);
        return PAID_SLUGS.has(p.slug) ? attachPaidDisplay(base) : base;
    }

    function normalizeFromSsrCard(p) {
        const limits = (p.features || []).map((f) => ({
            feature_key: f.feature_key,
            label: f.label || labelForFeature(f.feature_key),
            display: f.display,
            limit_value: null,
            is_hard_limit: false,
        }));
        const base = {
            id: p.slug,
            name: p.name,
            popular: !!p.is_highlight || p.slug === "pro",
            priceMonthly: Number(p.price_amount) || 0,
            billingCycle: p.billing_cycle || "monthly",
            limits,
            legacy: false,
            description: p.description || "",
            planKind: p.plan_kind || "",
            trialDays: p.trial_days || null,
            byokNote: p.byok_note || "",
            displayRows: p.display_rows || [],
        };
        if (p.slug === FREE_TRIAL_SLUG || base.planKind === "free_trial") {
            return attachFreeTrialDisplay(base);
        }
        const qm = p.quota_meta || {};
        if (qm.articles) base.articles = qm.articles;
        if (qm.projects) base.projects = qm.projects;
        if (qm.devices) base.devices = qm.devices;
        if (Array.isArray(p.feature_rows) && p.feature_rows.length) {
            base.featureFlags = {};
            p.feature_rows.forEach((row) => {
                base.featureFlags[row.key] = !!row.included;
            });
        }
        return PAID_SLUGS.has(p.slug) ? attachPaidDisplay(base) : base;
    }

    function filterPublicPlans(list) {
        return sortPricingPlans(
            (list || []).filter(
                (p) =>
                    p.id !== "free_trial" &&
                    p.id !== "unlimited" &&
                    (p.id === FREE_TRIAL_SLUG || PRICING_SLUGS.has(p.id)),
            ),
        );
    }

    function isFreeTrialPlan(plan) {
        return plan.planKind === "free_trial" || plan.id === FREE_TRIAL_SLUG;
    }

    function readSsrPlans() {
        const el = document.getElementById("digiseoSaasPlansJson");
        if (!el || !el.textContent) return null;
        try {
            const data = JSON.parse(el.textContent);
            if (Array.isArray(data) && data.length) {
                return filterPublicPlans(data.map(normalizeFromSsrCard));
            }
        } catch (_) {}
        return null;
    }

    function fetchApiPlans() {
        return fetch("/api/saas/plans", { credentials: "same-origin" })
            .then((r) => (r.ok ? r.json() : null))
            .then((data) => {
                if (!data || !Array.isArray(data.items) || !data.items.length) return null;
                return filterPublicPlans(data.items.map(normalizeFromApiItem));
            })
            .catch(() => null);
    }

    function loadPlans() {
        const ssr = readSsrPlans();
        if (ssr && ssr.length) {
            plans = ssr;
            return Promise.resolve(plans);
        }
        return fetchApiPlans().then((api) => {
            if (api && api.length) {
                plans = api;
                return plans;
            }
            if (!isPage) {
                plans = filterPublicPlans(LEGACY_PLANS.slice());
            }
            return plans;
        });
    }

    function durationDiscount(months) {
        if (months === 12) return 0.92;
        if (months === 24) return 0.85;
        return 1;
    }

    function priceForPlan(plan) {
        const monthly = Number(plan.priceMonthly) || 0;
        if (plan.billingCycle === "none" || monthly <= 0) return 0;
        const dur = DURATIONS.find((d) => d.id === state.duration);
        if (state.duration === "life") return Math.round(monthly * 48);
        if (!dur || !dur.months) return monthly;
        return Math.round(monthly * dur.months * durationDiscount(dur.months));
    }

    function perMonthVnd(total, months) {
        if (!months) return null;
        return Math.round(total / months);
    }

    function buildFeatureHtml(plan) {
        if (isFreeTrialPlan(plan) && plan.displayRows && plan.displayRows.length) {
            return plan.displayRows
                .map((row) => {
                    const mark = row.included
                        ? '<span class="ok">✓</span>'
                        : '<span class="no">✗</span>';
                    return `<li>${mark}<span>${row.label}</span></li>`;
                })
                .join("");
        }
        const flags = plan.featureFlags || (plan.legacy ? null : paidFlagsForSlug(plan.id));
        if (plan.legacy || flags) {
            const fmap = flags || {};
            return PAID_FEATURE_ROWS.map((f) => {
                let on = fmap[f.key];
                if (on === undefined) {
                    if (f.key === "gsc") on = !!plan.gsc;
                    else if (f.key === "priority") on = !!plan.priority;
                    else on = true;
                }
                const mark = on ? '<span class="ok">✓</span>' : '<span class="no">✗</span>';
                return `<li>${mark}<span>${f.label}</span></li>`;
            }).join("");
        }
        return '<li><span class="ok">✓</span><span>Liên hệ admin để biết chi tiết</span></li>';
    }

    function metaRow(icon, text) {
        const label = /^Unlimited/i.test(text)
            ? text.replace(/^(Unlimited)(\s+)/i, "<strong>$1</strong>$2")
            : text;
        const inner = /^Unlimited/i.test(text) ? label : `<strong>${text}</strong>`;
        return `<div class="digiseo-plan-meta-row"><span class="digiseo-plan-meta-icon" aria-hidden="true">${icon}</span>${inner}</div>`;
    }

    function buildMetaHtml(plan) {
        if (isFreeTrialPlan(plan)) {
            return "";
        }
        if (plan.articles && plan.projects && plan.devices) {
            return (
                metaRow("📄", plan.articles) +
                metaRow("📁", plan.projects) +
                metaRow("💻", plan.devices)
            );
        }
        return metaRow("✦", `Gói ${plan.name}`);
    }

    function ctaForPlan(plan) {
        if (currentPlanSlug && plan.id === currentPlanSlug) {
            return { text: "Gói hiện tại", href: null, disabled: true };
        }
        if (isFreeTrialPlan(plan)) {
            return { text: "Bắt đầu miễn phí", href: "/settings#api-keys", disabled: false };
        }
        return { text: "Mua ngay", href: "/settings#account", disabled: false };
    }

    function renderGrid() {
        const grid = document.getElementById("digiseoPricingGrid");
        if (!grid) return;
        if (!plans.length) {
            grid.innerHTML =
                '<p style="grid-column:1/-1;text-align:center;color:#94a3b8;padding:24px;">Chưa có gói hiển thị. Chạy seed plans hoặc liên hệ admin.</p>';
            return;
        }

        const dur = DURATIONS.find((d) => d.id === state.duration);
        const months = dur ? dur.months : null;

        grid.innerHTML = plans
            .map((p) => {
                const totalVnd = priceForPlan(p);
                const isFreeTrial = isFreeTrialPlan(p);
                const isFree = isFreeTrial || totalVnd <= 0;
                let displayMain;
                if (isFreeTrial) {
                    displayMain = state.payment === "paypal" ? "$0" : "0đ / 5 ngày";
                } else if (isFree) {
                    displayMain = state.payment === "paypal" ? "$0" : "0đ";
                } else if (state.payment === "paypal") {
                    displayMain = formatUsd(totalVnd) + " / " + (dur ? dur.label : "Lifetime");
                } else {
                    displayMain = formatVnd(totalVnd) + " / " + (dur ? dur.label : "Lifetime");
                }

                let perLine = "";
                if (!isFree && state.payment === "payos" && months) {
                    perLine = `(~ ${formatVnd(perMonthVnd(totalVnd, months))}/month)`;
                } else if (!isFree && state.payment === "paypal" && months) {
                    const pm = totalVnd / VND_PER_USD / months;
                    perLine = `(~ $${Math.max(1, Math.round(pm))}/month)`;
                } else if (state.duration === "life" && !isFree) {
                    perLine = state.payment === "paypal" ? "One-time payment" : "Thanh toán một lần";
                }

                const byokLine =
                    isFreeTrial && p.byokNote
                        ? `<div class="digiseo-plan-byok">${p.byokNote}</div>`
                        : "";

                const isCurrent = currentPlanSlug && p.id === currentPlanSlug;
                const cta = ctaForPlan(p);
                const badges = [];
                if (p.popular && !isCurrent) {
                    badges.push('<div class="digiseo-plan-badge">Most popular</div>');
                }
                if (isCurrent) {
                    badges.push('<div class="digiseo-plan-badge digiseo-plan-badge--current">Gói hiện tại</div>');
                }

                const buyTag = cta.href
                    ? `<a class="digiseo-plan-buy" href="${cta.href}">${cta.text}</a>`
                    : `<button type="button" class="digiseo-plan-buy" disabled>${cta.text}</button>`;

                return (
                    `<article class="digiseo-plan-card${p.popular ? " is-popular" : ""}${isFreeTrial ? " is-free-trial" : ""}${isCurrent ? " is-current-plan" : ""}" data-plan="${p.id}">` +
                    badges.join("") +
                    `<div class="digiseo-plan-name">${p.name}</div>` +
                    `<div class="digiseo-plan-price">${displayMain}</div>` +
                    (perLine ? `<div class="digiseo-plan-per">${perLine}</div>` : "") +
                    byokLine +
                    `<div class="digiseo-plan-meta">${buildMetaHtml(p)}</div>` +
                    `<ul class="digiseo-plan-features">${buildFeatureHtml(p)}</ul>` +
                    buyTag +
                    `</article>`
                );
            })
            .join("");

        grid.querySelectorAll(".digiseo-plan-buy:not([disabled])").forEach((btn) => {
            if (btn.tagName === "A") return;
            btn.addEventListener("click", () => {
                window.alert(
                    "Thanh toán PayOS / PayPal sẽ được kết nối trong bản cập nhật tới. Liên hệ admin hoặc mở Cài đặt → Tài khoản.",
                );
            });
        });
    }

    function syncToggles() {
        document.querySelectorAll(".digiseo-dur-btn").forEach((b) => {
            b.classList.toggle("is-active", b.getAttribute("data-dur") === state.duration);
        });
        document.querySelectorAll(".digiseo-pay-btn").forEach((b) => {
            b.classList.toggle("is-active", b.getAttribute("data-pay") === state.payment);
        });
    }

    function wireToolbar() {
        if (wireToolbar._bound) return;
        wireToolbar._bound = true;
        document.querySelectorAll(".digiseo-dur-btn").forEach((b) => {
            b.addEventListener("click", () => {
                state.duration = b.getAttribute("data-dur") || "m6";
                syncToggles();
                renderGrid();
            });
        });
        document.querySelectorAll(".digiseo-pay-btn").forEach((b) => {
            b.addEventListener("click", () => {
                state.payment = b.getAttribute("data-pay") || "payos";
                syncToggles();
                renderGrid();
            });
        });
    }

    function loadCurrentPlan() {
        let token = "";
        try {
            token = sessionStorage.getItem("seo_token") || "";
        } catch (_) {}
        if (!token) return Promise.resolve();
        return fetch("/api/saas/me", {
            headers: { Authorization: "Bearer " + token },
            credentials: "same-origin",
        })
            .then((r) => (r.ok ? r.json() : null))
            .then((me) => {
                if (!me || !me.plan_slug) return;
                currentPlanSlug = me.plan_slug;
                const banner = document.getElementById("pricingCurrentBanner");
                if (banner) {
                    banner.textContent =
                        "Bạn đang dùng gói: " +
                        (me.plan_name || me.plan_slug) +
                        (me.current_period_end
                            ? " — hết kỳ " + new Date(me.current_period_end).toLocaleDateString("vi-VN")
                            : "");
                    banner.classList.add("visible");
                }
            })
            .catch(() => {});
    }

    function goToUpgradeBilling(planSlug) {
        const url = new URL("/account-billing", window.location.origin);
        url.searchParams.set("tab", "plans");
        if (planSlug) url.searchParams.set("plan", String(planSlug).toLowerCase());
        window.location.href = url.pathname + "?" + url.searchParams.toString();
    }

    function openModal(planSlug) {
        goToUpgradeBilling(planSlug);
    }

    function closeModal() {
        const bd = document.getElementById("digiseoPricingBackdrop");
        if (!bd) return;
        bd.classList.remove("is-open");
        document.body.classList.remove("digiseo-pricing-open");
        document.body.style.overflow = "";
    }

    function wireModal() {
        const bd = document.getElementById("digiseoPricingBackdrop");
        if (!bd) return;
        const closeBtn = document.getElementById("digiseoPricingClose");
        if (closeBtn) closeBtn.addEventListener("click", closeModal);
        bd.addEventListener("click", (e) => {
            if (e.target === bd) closeModal();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && bd.classList.contains("is-open")) closeModal();
        });
        document.querySelectorAll("[data-digiseo-pricing-open]").forEach((el) => {
            el.addEventListener("click", (ev) => {
                ev.preventDefault();
                openModal(el.getAttribute("data-plan") || "");
            });
        });
    }

    function initPage() {
        wireToolbar();
        Promise.all([loadPlans(), loadCurrentPlan()]).then(() => {
            syncToggles();
            renderGrid();
        });
    }

    window.opendigiseoPricingModal = openModal;
    window.closedigiseoPricingModal = closeModal;

    function init() {
        if (isPage) {
            initPage();
        } else {
            wireModal();
            wireToolbar();
            loadPlans().then(() => {
                syncToggles();
                renderGrid();
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
