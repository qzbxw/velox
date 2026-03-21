TEST_BILLING_ADMIN_IDS = {5371784916}

PLAN_MONTH_OPTIONS = (1, 3, 6, 12)

PLANS = {
    "free": {
        "title_en": "Velox Free",
        "title_ru": "Velox Free",
        "monthly_price_usd": 0,
        "prices": {1: 0, 3: 0, 6: 0, 12: 0},
        "star_prices": {1: 0, 3: 0, 6: 0, 12: 0},
        "limits": {
            "wallets": 1,
            "watchlist": 7,
            "alerts": 5,
            "market_reports": 1,
            "overview_runs_daily": 3,
            "assistant_messages_daily": 10,
            "exports_daily": 0,
            "share_pnl_daily": 0,
            "digest_slots": 0,
        },
        "features": {
            "terminal": False,
            "export": False,
            "digests": False,
            "vault_reports": False,
            "flex": False,
            "advanced_ai_settings": False,
            "share_pnl": False,
        },
    },
    "pro": {
        "title_en": "Velox Pro",
        "title_ru": "Velox Pro",
        "monthly_price_usd": 12,
        "prices": {1: 12, 3: 30, 6: 54, 12: 96},
        "star_prices": {1: 850, 3: 2100, 6: 3800, 12: 6800},
        "limits": {
            "wallets": 3,
            "watchlist": 30,
            "alerts": 30,
            "market_reports": 4,
            "overview_runs_daily": 25,
            "assistant_messages_daily": 80,
            "exports_daily": 5,
            "share_pnl_daily": 15,
            "digest_slots": 3,
        },
        "features": {
            "terminal": True,
            "export": True,
            "digests": True,
            "vault_reports": True,
            "flex": True,
            "advanced_ai_settings": True,
            "share_pnl": True,
        },
    },
    "pro_plus": {
        "title_en": "Velox Pro+",
        "title_ru": "Velox Pro+",
        "monthly_price_usd": 24,
        "prices": {1: 24, 3: 60, 6: 108, 12: 192},
        "star_prices": {1: 1700, 3: 4200, 6: 7600, 12: 13600},
        "limits": {
            "wallets": 10,
            "watchlist": 150,
            "alerts": 120,
            "market_reports": 12,
            "overview_runs_daily": 120,
            "assistant_messages_daily": 400,
            "exports_daily": 20,
            "share_pnl_daily": 60,
            "digest_slots": 5,
        },
        "features": {
            "terminal": True,
            "export": True,
            "digests": True,
            "vault_reports": True,
            "flex": True,
            "advanced_ai_settings": True,
            "share_pnl": True,
        },
    },
}


def normalize_plan(plan: str | None) -> str:
    candidate = str(plan or "free").strip().lower()
    if candidate not in PLANS:
        return "free"
    return candidate


def get_plan_config(plan: str | None) -> dict:
    return PLANS[normalize_plan(plan)]


def get_plan_title(plan: str | None, lang: str = "en") -> str:
    cfg = get_plan_config(plan)
    return cfg["title_ru"] if str(lang or "en").lower().startswith("ru") else cfg["title_en"]


def get_plan_price(plan: str | None, months: int) -> int:
    cfg = get_plan_config(plan)
    return int(cfg.get("prices", {}).get(int(months), cfg.get("monthly_price_usd", 0) * int(months)))


def get_plan_price_options(plan: str | None) -> str:
    return " / ".join(f"${get_plan_price(plan, months)}" for months in PLAN_MONTH_OPTIONS)


def get_plan_star_price(plan: str | None, months: int) -> int:
    cfg = get_plan_config(plan)
    return int(cfg.get("star_prices", {}).get(int(months), 0))


def get_plan_star_price_options(plan: str | None) -> str:
    return " / ".join(f"{get_plan_star_price(plan, months)}⭐" for months in PLAN_MONTH_OPTIONS)
