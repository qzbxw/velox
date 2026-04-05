import logging
import time
from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from bot.locales import _t
from bot.services import (
    get_mid_price, pretty_float
)

router = Router(name="inline")
logger = logging.getLogger(__name__)

@router.inline_query()
async def inline_query_handler(query: InlineQuery):
    query_text = query.query.strip().upper()
    if not query_text: return
    
    price, symbol = 0.0, query_text
    ws = getattr(query.bot, "ws_manager", None)
    if ws: price = ws.get_price(symbol)
    if not price: price = await get_mid_price(symbol)
    if not price: return

    result_id = f"price_{symbol}_{time.time()}"
    title = f"{symbol}: ${pretty_float(price)}"
    description = "Click to send current price."
    
    input_content = InputTextMessageContent(
        message_text=f"💎 <b>{symbol}</b>\nPrice: <code>${pretty_float(price)}</code>",
        parse_mode="HTML"
    )
    
    item = InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=description,
        input_message_content=input_content
    )
    
    await query.answer([item], cache_time=5)
