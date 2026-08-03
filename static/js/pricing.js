(() => {
    "use strict";

    /** Promo badge label per billing cycle — monthly has no gift. */
    const PROMO_BADGE_BY_CYCLE = {
        monthly: "",
        semi_annual: "Tặng 1 tháng credit",
        yearly: "Tặng 2 tháng",
    };

    function formatVnd(amount) {
        const n = Number(amount || 0);
        return n.toLocaleString("vi-VN");
    }

    function normalizeBilling(mode) {
        if (mode === "yearly") return "yearly";
        if (mode === "semi_annual") return "semi_annual";
        return "monthly";
    }

    function setPromoBadge(card, billing) {
        const promoBadge = card.querySelector("[data-promo-badge]");
        if (!promoBadge) return;

        const label = PROMO_BADGE_BY_CYCLE[billing] || "";
        promoBadge.textContent = label;
        promoBadge.hidden = !label;
    }

    function setCreditRows(card, billing) {
        const semiCreditRow = card.querySelector("[data-semi-credit-row]");
        const yearlyCreditRow = card.querySelector("[data-year-credit-row]");
        if (semiCreditRow) semiCreditRow.hidden = billing !== "semi_annual";
        if (yearlyCreditRow) yearlyCreditRow.hidden = billing !== "yearly";
    }

    function setBilling(mode) {
        const billing = normalizeBilling(mode);

        document.querySelectorAll(".sp-toggle-btn[data-billing]").forEach((btn) => {
            const active = btn.getAttribute("data-billing") === billing;
            btn.classList.toggle("is-active", active);
            btn.setAttribute("aria-pressed", active ? "true" : "false");
        });

        const note = document.getElementById("spBillingNote");
        const semiNote = document.getElementById("spSemiAnnualNote");
        const yearlyNote = document.getElementById("spYearlyNote");
        if (note) note.hidden = true;
        if (semiNote) semiNote.hidden = billing !== "semi_annual";
        if (yearlyNote) yearlyNote.hidden = billing !== "yearly";

        document.body.setAttribute("data-sp-billing", billing);

        document.querySelectorAll(".sp-card[data-month][data-year]").forEach((card) => {
            let val;
            let unit;
            if (billing === "yearly") {
                val = card.getAttribute("data-year");
                unit = "/năm";
            } else if (billing === "semi_annual") {
                val = card.getAttribute("data-semi");
                unit = "/6 tháng";
            } else {
                val = card.getAttribute("data-month");
                unit = "/tháng";
            }
            const el = card.querySelector("[data-price]");
            if (el) el.textContent = formatVnd(val);
            const unitEl = card.querySelector("[data-unit]");
            if (unitEl) unitEl.textContent = unit;

            setPromoBadge(card, billing);
            setCreditRows(card, billing);
        });
    }

    function init() {
        const btns = Array.from(document.querySelectorAll(".sp-toggle-btn[data-billing]"));
        btns.forEach((btn) => {
            btn.addEventListener("click", () => setBilling(btn.getAttribute("data-billing") || "monthly"));
        });
        setBilling("monthly");

        const compareAccs = Array.from(document.querySelectorAll("details.sp-acc"));
        compareAccs.forEach((d) => {
            d.addEventListener("toggle", () => {
                if (!d.open) return;
                compareAccs.forEach((x) => {
                    if (x !== d) x.open = false;
                });
            });
        });

        const faqItems = Array.from(document.querySelectorAll("details.sp-faq-item"));
        faqItems.forEach((d) => {
            d.addEventListener("toggle", () => {
                if (!d.open) return;
                faqItems.forEach((x) => {
                    if (x !== d) x.open = false;
                });
            });
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
