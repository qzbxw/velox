from aiogram import Router
from .menu import router as menu_router
from .portfolio import router as portfolio_router
from .trading import router as trading_router
from .market import router as market_router
from .alerts import router as alerts_router
from .vaults import router as vaults_router
from .billing import router as billing_router
from .digests import router as digests_router
from .settings import router as settings_router
from .ai import router as ai_router
from .inline import router as inline_router
from .export import router as export_router
from ._common import global_error_handler, CallbackThrottleMiddleware

main_router = Router(name="handlers")
main_router.callback_query.middleware(CallbackThrottleMiddleware())
main_router.include_routers(
    menu_router,
    portfolio_router,
    trading_router,
    market_router,
    alerts_router,
    vaults_router,
    billing_router,
    digests_router,
    settings_router,
    ai_router,
    inline_router,
    export_router
)

# Register error handler
main_router.error()(global_error_handler)
