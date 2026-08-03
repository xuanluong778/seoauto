"""SEOAuto hybrid SaaS pricing — subscription quota + monthly credit + addon packs.

Mô hình:
- 4 gói trả phí: Basic, Pro, Agency, Business (slug starter/pro/agency/business).
- Free/Demo (free_trial_5d): BYOK, quota thấp — không dùng nhiều API tốn phí.
- Không tách gói theo module; mua thêm qua credit pack / article addon.
- Gói năm ≈ 10 tháng giá tháng.
- product_code SePay giữ nguyên (STARTER_M, PRO_M, …) — chỉ đổi số tiền trong catalog.
"""

from __future__ import annotations

from typing import Any

HYBRID_PRICING_REVISION = 3
YEARLY_MONTHS_EQUIVALENT = 10  # giá năm = 10× tháng (giữ nguyên hiển thị)
YEARLY_BASE_DURATION_MONTHS = 12
YEARLY_BONUS_DURATION_MONTHS = 2
YEARLY_DURATION_MONTHS_TOTAL = 14
YEARLY_CREDIT_MONTHS_TOTAL = 14  # 12 tháng base + 2 tháng bonus credit
SEMI_ANNUAL_MONTHS_PAID = 5
SEMI_ANNUAL_MONTHS_USAGE = 6
SEMI_ANNUAL_CREDIT_MONTHS_TOTAL = 7  # 6 tháng base + 1 tháng bonus credit

PAID_PLAN_SLUGS: tuple[str, ...] = ("starter", "pro", "agency", "business")

# Giá 6 tháng: trả 5 tháng, dùng 6 tháng (đồng bộ catalog SePay)
SEMI_ANNUAL_PRICES_VND: dict[str, int] = {
    "starter": 1_995_000,
    "pro": 3_995_000,
    "agency": 8_450_000,
    "business": 17_450_000,
}

HYBRID_PLAN_DEFAULTS: dict[str, dict[str, Any]] = {
    "starter": {
        "name": "Basic",
        "month_price": 399_000,
        "credits_per_month": 500,
        "is_popular": False,
    },
    "pro": {
        "name": "Pro",
        "month_price": 799_000,
        "credits_per_month": 2_500,
        "is_popular": True,
    },
    "agency": {
        "name": "Agency",
        "month_price": 1_690_000,
        "credits_per_month": 7_000,
        "is_popular": False,
    },
    "business": {
        "name": "Business",
        "month_price": 3_490_000,
        "credits_per_month": 18_000,
        "is_popular": False,
    },
}

_BILLING_SKU_TEMPLATE: list[tuple[str, str, str]] = [
    ("STARTER_M", "starter", "monthly"),
    ("STARTER_6M", "starter", "semi_annual"),
    ("STARTER_Y", "starter", "yearly"),
    ("PRO_M", "pro", "monthly"),
    ("PRO_6M", "pro", "semi_annual"),
    ("PRO_Y", "pro", "yearly"),
    ("AGENCY_M", "agency", "monthly"),
    ("AGENCY_6M", "agency", "semi_annual"),
    ("AGENCY_Y", "agency", "yearly"),
    ("BUSINESS_M", "business", "monthly"),
    ("BUSINESS_6M", "business", "semi_annual"),
    ("BUSINESS_Y", "business", "yearly"),
]


def yearly_price(month_price: int) -> int:
    return int(month_price) * YEARLY_MONTHS_EQUIVALENT


def semi_annual_price(slug: str) -> int:
    key = str(slug or "").strip().lower()
    if key in SEMI_ANNUAL_PRICES_VND:
        return int(SEMI_ANNUAL_PRICES_VND[key])
    cfg = HYBRID_PLAN_DEFAULTS.get(key)
    if not cfg:
        return 0
    return int(cfg["month_price"]) * SEMI_ANNUAL_MONTHS_PAID


def plan_cycle_credit_breakdown(slug: str, billing_cycle: str) -> dict[str, int]:
    """Credit/duration breakdown per billing cycle."""
    key = str(slug or "").strip().lower()
    monthly = int(HYBRID_PLAN_DEFAULTS.get(key, {}).get("credits_per_month") or 0)
    cycle = str(billing_cycle or "monthly").strip().lower()
    if cycle == "semi_annual":
        return {
            "monthly_credit": monthly,
            "base_credit": monthly * 6,
            "bonus_credit": monthly * 1,
            "total_credit": monthly * SEMI_ANNUAL_CREDIT_MONTHS_TOTAL,
        }
    if cycle == "yearly":
        return {
            "monthly_credit": monthly,
            "base_duration_months": YEARLY_BASE_DURATION_MONTHS,
            "bonus_duration_months": YEARLY_BONUS_DURATION_MONTHS,
            "total_duration_months": YEARLY_DURATION_MONTHS_TOTAL,
            "base_credit": monthly * YEARLY_BASE_DURATION_MONTHS,
            "bonus_credit": monthly * YEARLY_BONUS_DURATION_MONTHS,
            "total_credit": monthly * YEARLY_CREDIT_MONTHS_TOTAL,
        }
    return {
        "monthly_credit": monthly,
        "base_credit": monthly,
        "bonus_credit": 0,
        "total_credit": monthly,
    }


def plan_monthly_bonus_credits() -> dict[str, int]:
    return {
        slug: int(cfg["credits_per_month"])
        for slug, cfg in HYBRID_PLAN_DEFAULTS.items()
    }


PLAN_MONTHLY_BONUS_CREDITS: dict[str, int] = plan_monthly_bonus_credits()


def build_billing_saas_products() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for product_code, slug, cycle in _BILLING_SKU_TEMPLATE:
        cfg = HYBRID_PLAN_DEFAULTS[slug]
        month = int(cfg["month_price"])
        credits = plan_cycle_credit_breakdown(slug, cycle)
        if cycle == "monthly":
            price = month
            period_days = 30
            duration_months = 1
        elif cycle == "semi_annual":
            price = semi_annual_price(slug)
            period_days = 183
            duration_months = SEMI_ANNUAL_MONTHS_USAGE
        else:
            price = yearly_price(month)
            period_days = 426
            duration_months = YEARLY_DURATION_MONTHS_TOTAL
        product: dict[str, Any] = {
            "product_code": product_code,
            "name": str(cfg["name"]),
            "plan_slug": slug,
            "billing_cycle": cycle,
            "price": price,
            "currency": "VND",
            "period_days": period_days,
            "duration_months": duration_months,
            "monthly_credit": credits["monthly_credit"],
            "base_credit": credits["base_credit"],
            "bonus_credit": credits["bonus_credit"],
            "total_credit": credits["total_credit"],
        }
        if cycle == "yearly":
            product["base_duration_months"] = YEARLY_BASE_DURATION_MONTHS
            product["bonus_duration_months"] = YEARLY_BONUS_DURATION_MONTHS
            product["total_duration_months"] = YEARLY_DURATION_MONTHS_TOTAL
        out.append(product)
    return out


def apply_hybrid_prices_to_pricing_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for spec in specs:
        slug = str(spec.get("slug") or "")
        cfg = HYBRID_PLAN_DEFAULTS.get(slug)
        if not cfg:
            continue
        month = int(cfg["month_price"])
        spec["month_price"] = month
        spec["year_price"] = yearly_price(month)
        spec["semi_annual_price"] = semi_annual_price(slug)
        credits = plan_cycle_credit_breakdown(slug, "semi_annual")
        spec["semi_annual_total_credit"] = credits["total_credit"]
        spec["semi_annual_bonus_credit"] = credits["bonus_credit"]
        yearly_credits = plan_cycle_credit_breakdown(slug, "yearly")
        spec["yearly_total_credit"] = yearly_credits["total_credit"]
        spec["yearly_bonus_credit"] = yearly_credits["bonus_credit"]
        if "is_popular" in cfg:
            spec["is_popular"] = bool(cfg["is_popular"])
        credits = int(cfg["credits_per_month"])
        feats: list[tuple[str, str]] = []
        for item in spec.get("features") or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                label, val = item[0], item[1]
                if str(label) == "Credit/tháng":
                    val = str(credits)
                feats.append((str(label), str(val)))
            elif isinstance(item, dict):
                label = str(item.get("label") or "")
                val = str(item.get("value") or "")
                if label == "Credit/tháng":
                    val = str(credits)
                feats.append((label, val))
        spec["features"] = feats
        compare = dict(spec.get("compare") or {})
        compare["hybrid_model"] = True
        compare["credits_per_month"] = credits
        spec["compare"] = compare
    return specs


HYBRID_CREDIT_ADDON_NOTES: list[str] = [
    "Mô hình hybrid: gói tháng gồm quota tính năng + credit pool; vượt quota có thể mua credit pack.",
    "Credit gói (monthly bonus) cộng dồn tối đa 2 chu kỳ — không xóa khi hết tháng.",
    "Hết hạn gói: credit gói bị khóa; gia hạn qua SePay để mở khóa và nhận credit tháng mới.",
    "Credit mua thêm (purchased) có hạn 12 tháng — không tính vào cap credit gói.",
]

FREE_TRIAL_HYBRID_NOTE = (
    "Demo 5 ngày — BYOK bắt buộc. Quota thấp, không dùng nhiều API pool SEOAuto."
)
