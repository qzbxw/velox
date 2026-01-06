# Multilingual support for Velox Bot

def _t(lang: str, key: str, **kwargs) -> str:
    l = (lang or "ru").lower()
    # Default to RU if not found or empty
    if l not in ["en", "ru"]: l = "ru"
    
    table = RU if l == "ru" else EN
    text = table.get(key, key)
    
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
            
    return text

# --- ENGLISH ---
EN = {
    "welcome": "👋 <b>Velox Terminal</b>\n\nReal-time Hyperliquid portfolio monitoring & analytics.\n\n/add_wallet <code>address</code> - Track wallet\n/help - Show commands",
    "set_wallet": "⚠️ No wallet connected. Use /add_wallet <code>0x...</code>",
    "tracking": "✅ Tracking: <code>{wallet}</code>",
    "help_msg": "<b>Available Commands:</b>\n\n🔹 <b>Portfolio</b>\n/add_wallet <code>0x...</code> - Track wallet\n/tag <code>0x...</code> <code>Name</code> - Rename wallet\n/threshold <code>0x...</code> <code>1000</code> - Min fill USD to alert\n\n🔹 <b>Alerts</b>\n/alert <code>ETH</code> <code>3000</code> - Price alert\n/watch <code>SOL</code> - Add to watchlist\n/unwatch <code>SOL</code> - Remove from watchlist\n/set_prox <code>0.5</code> - Proximity alert %\n/set_vol <code>2.0</code> - Volatility alert %\n/set_whale <code>250000</code> - Whale alert min USD\n\n🔹 <b>Misc</b>\n/start - Main Menu\n/export - Export PnL history CSV",
    
    # Alerts - Management
    "alert_added": "✅ Alert set: <b>{symbol}</b> {dir} <b>${price}</b>",
    "alert_usage": "⚠️ Usage: <code>/alert ETH 3500</code> (Target Price)",
    "alert_error": "❌ Error. Check format.",
    "no_alerts": "📭 No active price alerts.",
    "alerts_list": "🔔 <b>Your Active Alerts:</b>",
    "deleted": "🗑️ Deleted.",
    
    # Alerts - Notifications
    "custom_alert_title": "🔔 <b>Price Alert</b>",
    "custom_alert_msg": "<b>{symbol}</b> hit <b>${price}</b>\n(Target: {direction} {target})",
    
    "whale_alert": "🐋 <b>Whale Alert</b>",
    "whale_msg": "{icon} {side} <b>{symbol}</b>\nSize: <b>${val}</b>\nPrice: ${price}",
    
    "watch_alert_title": "👀 <b>Watchlist Alert</b>",
    "watch_alert_msg": "{dir_icon} <b>{symbol}</b> moved <b>{move}%</b> in <b>{time}m</b>\nNow: <b>${curr}</b>\nWas: <b>${prev}</b>",
    
    "prox_alert_title": "⚠️ <b>Proximity Alert</b>",
    "prox_alert_buy": "🟢 BUY",
    "prox_alert_sell": "🔴 SELL",
    "prox_alert_order": "🟡 ORDER",
    "prox_alert_mid": "Mid",
    "prox_alert_limit": "Limit",
    "prox_alert_to_fill": "To fill",
    "prox_alert_diff": "Diff",
    "prox_alert_dist": "USD dist",
    
    "fill_alert_title": "⚡ <b>Order Fill</b>",
    "fill_alert_liq": "💀 <b>LIQUIDATION</b>",
    "fill_alert_msg": "{side_icon} {side} {sz} <b>{symbol}</b> @ ${px}\nValue: <b>${val}</b>\nWallet: {wallet}",
    "order_placed_title": "Order Placed",
    
    "liq_risk_title": "⚠️ <b>DANGER: High Liquidation Risk!</b>",
    "liq_risk_msg": "Wallet: {wallet}\nMargin Ratio: <b>{ratio}%</b>\nEquity: ${equity}\n\n<i>Consider adding collateral or reducing positions!</i>",

    # Titles
    "balance_title": "🏦 <b>Balances & Portfolio</b>",
    "positions_title": "🎰 <b>Open Positions</b>",
    "orders_title": "🧾 <b>Open Orders</b>",
    "market_title": "📊 <b>Market Overview</b>",
    "settings_title": "⚙️ <b>Settings</b>",
    "lang_title": "🌍 <b>Language</b>",
    "pnl_title": "🧮 <b>PnL Analysis</b>",
    "stats_title": "📈 <b>Trading Performance</b>",
    "whales_title": "🐋 <b>Whale Watch</b>",

    # Calculator
    "calc_btn": "🧮 Calculator",
    "calc_mode": "🧮 <b>Position Calculator</b>\n\nChoose market:",
    "calc_spot": "💎 Spot",
    "calc_perp": "⚙️ Perps",
    "calc_side_msg": "Choose direction:",
    "calc_long": "🟢 Long",
    "calc_short": "🔴 Short",
    "calc_balance": "⌨️ Enter your <b>Account Balance ($)</b>:",
    "calc_entry": "⌨️ Enter <b>Entry Price</b>:",
    "calc_sl": "⌨️ Enter <b>Stop Loss</b>:",
    "calc_tp": "⌨️ Enter <b>Take Profit</b> (or multiple via space):",
    "calc_risk": "⌨️ Enter <b>Risk Amount ($)</b>:",
    "calc_result": "📊 <b>{side} Plan ({mode})</b>\n\n"
                   "💰 Balance: <code>${balance}</code>\n"
                   "🎯 Risk: <code>${risk}</code>\n"
                   "🏁 Entry: <code>{entry}</code>\n"
                   "🛑 SL: <code>{sl}</code> (<code>{sl_pct}%</code>)\n"
                   "✅ TP: <code>{tp}</code> (<code>{tp_pct}%</code>)\n\n"
                   "⚖️ <b>R:R: 1:{rr}</b>\n"
                   "{lev_row}"
                   "{liq_row}\n"
                   "👉 <b>Position Size:</b>\n"
                   "💵 USD: <code>${size_usd}</code>\n"
                   "💎 Coins: <code>{size_coins}</code>\n\n"
                   "💸 Fees (Taker): <code>${fees}</code>\n"
                   "📉 Net Loss: <code>-${total_loss}</code>\n"
                   "📈 Net Profit: <code>+${total_profit}</code>\n\n"
                   "🥞 <b>Scaling (50/50):</b>\n"
                   "• TP1 (50%): <code>+${p50}</code>\n"
                   "• TP2 (50%): <code>+${p100}</code>",
    "calc_low_bal": "\n\n⚠️ <b>Not enough balance for Spot!</b>\nNeed: <code>${need}</code>",
    "calc_liq_warn": "\n\n⚠️ <b>LIQUIDATION BEFORE STOP!</b>",
    "calc_side_wrong": "\n\n⚠️ <b>Stop Loss is on the wrong side!</b>",
    "calc_none": "None",
    "calc_lev_lbl": "⚙️ <b>Leverage: <code>{lev}x</code></b>\n",
    "calc_liq_lbl": "💀 <b>Est. Liq: <code>{liq}</code></b>\n",
    "calc_error": "❌ Invalid number. Try again.",
    
    # Misc
    "wait": "⏳ Loading...",
    "need_wallet": "⛔ Add wallet first: /add_wallet",
    "select_pos": "👇 Select Position to Share:",
    "tag_usage": "⚠️ Usage: <code>/tag 0x... MyTag</code>",
    "threshold_usage": "⚠️ Usage: <code>/threshold 0x... 1000</code> (min USD for alerts)",
    "settings_updated": "✅ Settings updated.",
    "watch_added": "✅ Added <b>{symbol}</b> to watchlist.",
    "watch_removed": "🗑️ Removed <b>{symbol}</b> from watchlist.",
    "prox_set": "✅ Proximity alert threshold set to <b>{val}%</b>",
    "vol_set": "✅ Volatility alert threshold set to <b>{val}%</b>",
    "whale_set": "✅ Whale threshold set to <b>${val}</b>",
    "whale_input": "⌨️ Enter minimum whale trade value (USD):\nExample: <code>/set_whale 250000</code>",
    "prox_input": "⌨️ Enter proximity alert threshold (e.g. 0.5%):\nExample: <code>/set_prox 0.5</code>",
    "vol_input": "⌨️ Enter Volatility Alert threshold (e.g. 2.0%):\nExample: <code>/set_vol 2.0</code>",
    
    # Errors & Usage
    "add_wallet_usage": "⚠️ Usage: <code>/add_wallet 0x...</code>",
    "invalid_number": "❌ Invalid number.",
    "unknown_price": "❌ Unknown price for <b>{symbol}</b>",
    "watch_usage": "⚠️ Usage: <code>/watch SOL</code>",
    "watch_invalid": "❌ Invalid symbol.",
    "unwatch_usage": "⚠️ Usage: <code>/unwatch SOL</code>",
    "set_vol_usage": "⚠️ Usage: <code>/set_vol 2.5</code> (Percentage)",
    "set_whale_usage": "⚠️ Usage: <code>/set_whale 250000</code> (USD)",
    "set_prox_usage": "⚠️ Usage: <code>/set_prox 0.5</code> (Percentage)",
    "pos_not_found": "❌ Position not found (closed?).",
    "card_error": "❌ Error generating card.",
    "enable": "🟢 Enable",
    "disable": "🔴 Disable",
    "sort_vol": "Sort: Volume",
    "sort_funding": "Sort: Funding",
    "sort_oi": "Sort: OI",
    "sort_change": "Sort: 24h %",
    
    # Market Alerts
    "btn_market_alerts": "🔔 Market Alerts",
    "market_alerts_title": "🔔 <b>Market Overview Alerts</b>",
    "market_alerts_msg": "Configure scheduled market reports.\nYou will receive detailed dashboards (Fundamentals & Alpha Insights).\nNote: All times are in <b>UTC</b>.",
    "add_time_prompt": "⌨️ Enter time in <b>HH:MM</b> format (UTC):\nExample: <code>09:00</code> or <code>18:30</code>",
    "invalid_time": "❌ Invalid time format. Use HH:MM (e.g., 09:30)",
    "market_alert_added": "✅ Market alert scheduled for <b>{time} UTC</b>",
    "market_alert_removed": "🗑️ Alert for <b>{time}</b> removed.",
    "no_market_alerts": "📭 No scheduled market reports.",
    "btn_add_time": "➕ Add Time",

    "market_report_global": "🌍 <b>Global Market Pulse</b>",
    "market_report_vol": "24h Volume",
    "market_report_oi": "Open Interest",
    "market_report_sentiment": "Sentiment",
    "market_report_top_gainers": "🚀 <b>Top Gainers</b>",
    "market_report_top_losers": "📉 <b>Top Losers</b>",
    "market_report_efficiency": "⚡ <b>Capital Efficiency (Vol/OI)</b>",
    "market_report_funding": "💰 <b>High Funding (APR)</b>",
    "market_report_footer": "<i>Updated: {time} • Velox Intelligence</i>",
    
    # Buttons
    "btn_balance": "🏦 Balance",
    "btn_positions": "🎰 Positions",
    "btn_orders": "🧾 Orders",
    "btn_pnl": "🧮 PnL",
    "btn_market": "📊 Market",
    "btn_stats": "📈 Stats",
    "btn_whales": "🐋 Whales",
    "btn_settings": "⚙️ Settings",
    "btn_alerts": "🔔 Alerts",
    "btn_lang": "🌍 Language",
    "btn_back": "🔙 Back",
    "btn_graph": "📈 Graph",
    
    # Categories
    "cat_portfolio": "💼 Portfolio",
    "cat_trading": "⚡ Trading",
    "cat_market": "🌊 Market Data",
    "cat_settings": "⚙️ Settings",
    
    "menu_portfolio": "💼 <b>Portfolio Menu</b>",
    "menu_trading": "⚡ <b>Trading Menu</b>",
    "menu_market": "🌊 <b>Market Data</b>",

    "btn_market_overview": "📊 Market Insights",
    "btn_share": "🖼️ Share PnL",
    "btn_wallets": "👛 Wallets",
    "btn_refresh": "🔄 Refresh",
    "btn_analysis": "🧠 Analysis",
    "btn_export": "📥 Export CSV",
    "btn_flex": "💪 Flex PnL",
    "flex_title": "💪 <b>PnL Flex Mode</b>",
    "flex_period_day": "Day",
    "flex_period_week": "Week",
    "flex_period_month": "Month",
    "flex_period_all": "All-Time",
    "flex_gen_error": "❌ Error generating Flex card.",
    
    # Metrics
    "equity": "💰 Equity",
    "wallet_bal": "💵 Wallet Balance",
    "upnl": "📊 Unreal. PnL",
    "day_change": "📅 24h Change",
    "week_change": "📅 7d Change",
    "month_change": "📅 30d Change",
    "cum_pnl": "📈 Cum. PnL",
    "empty_pnl": "📭 No history data.",
    "liq_price": "💀 Liq",
    "roi": "ROI",
    "margin": "Margin",
    "leverage": "⚙️ Lev",
    "funding": "Funding",
    "withdrawable": "💳 Withdr.",
    "margin_ratio": "⚠️ M.Ratio",
    "win_rate": "🏆 Win Rate",
    "total_trades": "🔢 Trades",
    "profit_factor": "⚖️ Profit Factor",
    "gross_profit": "🟢 Gross Profit",
    "gross_loss": "🔴 Gross Loss",
    
    "net_worth": "💰 Global Net Worth",
    "spot_bal": "🔹 Spot",
    "perps_bal": "🔸 Perps",
    "total_upnl": "📊 Total uPnL",
    "total_lbl": "Total",
    "net_pnl": "Net PnL",
    "empty_state": "<i>Empty</i>",
    
    # Whales
    "whale_alerts_on": "🔔 Whale Alerts: <b>ON</b>",
    "whale_alerts_off": "🔕 Whale Alerts: <b>OFF</b>",
    "whale_intro": "Tracking large trades > $100k globally.",
    "funding_alert_set": "✅ Funding alert set for <b>{symbol}</b>: {dir} <b>{val}% APR</b>",
    "oi_alert_set": "✅ OI alert set for <b>{symbol}</b>: {dir} <b>${val}M</b>",
    "new_listing_msg": "🚀 <b>New Asset Listed on Hyperliquid!</b>\n\nSymbol: <b>${sym}</b>\n\n<i>Trading is now available. Use /watch {sym} to monitor volatility.</i>",
    "funding_alert_msg": "💰 <b>FUNDING Alert: {sym}</b>\n\nCurrent: <b>{current}{unit}</b>\nTarget: {direction} <b>{target}{unit}</b>",
    "oi_alert_msg": "📊 <b>OI Alert: {sym}</b>\n\nCurrent: <b>{current}{unit}</b>\nTarget: {direction} <b>{target}{unit}</b>",
    "vaults_lbl": "Vaults",
    "calc_exit_btn": "🧮 Calc Exit {sym}",
    "exit_calc_title": "📊 <b>Exit Calculator: {sym}</b>\nPre-filled from position.\n\n",
}

# --- RUSSIAN ---
RU = {
    "welcome": "👋 <b>Velox Terminal</b>\n\nМониторинг и аналитика портфеля Hyperliquid в реальном времени.\n\n/add_wallet <code>address</code> - Добавить кошелёк\n/help - Список команд",
    "set_wallet": "⚠️ Кошелёк не подключен. Используй /add_wallet <code>0x...</code>",
    "tracking": "✅ Отслеживаю: <code>{wallet}</code>",
    "help_msg": "<b>Доступные команды:</b>\n\n🔹 <b>Портфель</b>\n/add_wallet <code>0x...</code> - Трекать кошелёк\n/tag <code>0x...</code> <code>Name</code> - Назвать кошелёк\n/threshold <code>0x...</code> <code>1000</code> - Мин. сумма исполнения ($) для алерта\n\n🔹 <b>Алерты</b>\n/alert <code>ETH</code> <code>3000</code> - Ценовой алерт\n/watch <code>SOL</code> - Добавить в вотчлист\n/unwatch <code>SOL</code> - Убрать из вотчлиста\n/set_prox <code>0.5</code> - Порог 'Цена рядом' %\n/set_vol <code>2.0</code> - Порог волатильности %\n/set_whale <code>250000</code> - Мин. сумма кита\n\n🔹 <b>Прочее</b>\n/start - Главное меню\n/export - Скачать CSV историю PnL",
    
    # Alerts - Management
    "alert_added": "✅ Алерт установлен: <b>{symbol}</b> {dir} <b>${price}</b>",
    "alert_usage": "⚠️ Пример: <code>/alert ETH 3500</code>",
    "alert_error": "❌ Ошибка формата.",
    "no_alerts": "📭 Нет активных алертов.",
    "alerts_list": "🔔 <b>Твои активные алерты:</b>",
    "deleted": "🗑️ Удалено.",
    
    # Alerts - Notifications
    "custom_alert_title": "🔔 <b>Ценовой Алерт</b>",
    "custom_alert_msg": "<b>{symbol}</b> достиг <b>${price}</b>\n(Цель: {direction} {target})",
    
    "whale_alert": "🐋 <b>Whale Alert</b>",
    "whale_msg": "{icon} {side} <b>{symbol}</b>\nОбъем: <b>${val}</b>\nЦена: ${price}",
    
    "watch_alert_title": "👀 <b>Watchlist Alert</b>",
    "watch_alert_msg": "{dir_icon} <b>{symbol}</b> изменение <b>{move}%</b> за <b>{time}м</b>\nСейчас: <b>${curr}</b>\nБыло: <b>${prev}</b>",
    
    "prox_alert_title": "⚠️ <b>Алерт: Цена рядом</b>",
    "prox_alert_buy": "🟢 BUY",
    "prox_alert_sell": "🔴 SELL",
    "prox_alert_order": "🟡 ORDER",
    "prox_alert_mid": "Mid",
    "prox_alert_limit": "Лимит",
    "prox_alert_to_fill": "До исполнения",
    "prox_alert_diff": "Отклонение",
    "prox_alert_dist": "USD дист.",
    
    "fill_alert_title": "⚡ <b>Исполнение Ордера</b>",
    "fill_alert_liq": "💀 <b>ЛИКВИДАЦИЯ</b>",
    "fill_alert_msg": "{side_icon} {side} {sz} <b>{symbol}</b> по ${px}\nОбъем: <b>${val}</b>\nКошелёк: {wallet}",
    "order_placed_title": "Ордер Размещен",
    
    "liq_risk_title": "⚠️ <b>ОПАСНОСТЬ: Риск Ликвидации!</b>",
    "liq_risk_msg": "Кошелёк: {wallet}\nMargin Ratio: <b>{ratio}%</b>\nEquity: ${equity}\n\n<i>Рассмотрите добавление маржи или сокращение позиций!</i>",

    # Titles
    "balance_title": "🏦 <b>Балансы и Портфель</b>",
    "positions_title": "🎰 <b>Открытые Позиции</b>",
    "orders_title": "🧾 <b>Активные Ордера</b>",
    "market_title": "📊 <b>Обзор Рынка</b>",
    "settings_title": "⚙️ <b>Настройки</b>",
    "lang_title": "🌍 <b>Язык / Language</b>",
    "pnl_title": "🧮 <b>PnL Анализ</b>",
    "stats_title": "📈 <b>Статистика торговли</b>",
    "whales_title": "🐋 <b>Whale Watch</b>",

    # Calculator
    "calc_btn": "🧮 Калькулятор",
    "calc_mode": "🧮 <b>Калькулятор Позиции</b>\n\nВыберите рынок:",
    "calc_spot": "💎 Spot",
    "calc_perp": "⚙️ Perps",
    "calc_side_msg": "Выберите направление:",
    "calc_long": "🟢 Long",
    "calc_short": "🔴 Short",
    "calc_balance": "⌨️ Введите ваш <b>Баланс ($)</b>:",
    "calc_entry": "⌨️ Введите <b>Точку Входа</b> (Цена):",
    "calc_sl": "⌨️ Введите <b>Stop Loss</b> (Цена):",
    "calc_tp": "⌨️ Введите <b>Take Profit</b> (Цена):",
    "calc_risk": "⌨️ Введите <b>Риск на сделку ($)</b>:",
    "calc_result": "📊 <b>План {side} ({mode})</b>\n\n"
                   "💰 Баланс: <code>${balance}</code>\n"
                   "🎯 Риск: <code>${risk}</code>\n"
                   "🏁 Вход: <code>{entry}</code>\n"
                   "🛑 Стоп: <code>{sl}</code> (<code>{sl_pct}%</code>)\n"
                   "✅ Тейк: <code>{tp}</code> (<code>{tp_pct}%</code>)\n\n"
                   "⚖️ <b>R:R: 1:{rr}</b>\n"
                   "{lev_row}"
                   "{liq_row}\n"
                   "👉 <b>Размер Позиции:</b>\n"
                   "💵 USD: <code>${size_usd}</code>\n"
                   "💎 Монеты: <code>{size_coins}</code>\n\n"
                   "💸 Комса (Taker): <code>${fees}</code>\n"
                   "📉 Чистый убыток: <code>-${total_loss}</code>\n"
                   "📈 Чистый профит: <code>+${total_profit}</code>\n\n"
                   "🥞 <b>Скейлинг (50/50):</b>\n"
                   "• TP1 (50%): <code>+${p50}</code>\n"
                   "• TP2 (50%): <code>+${p100}</code>",
    "calc_low_bal": "\n\n⚠️ <b>Недостаточно баланса для Спота!</b>\nНужно: <code>${need}</code>",
    "calc_liq_warn": "\n\n⚠️ <b>ЛИКВИДАЦИЯ РАНЬШЕ СТОПА!</b>",
    "calc_side_wrong": "\n\n⚠️ <b>Стоп-лосс указан не с той стороны!</b>",
    "calc_none": "Нет",
    "calc_lev_lbl": "⚙️ <b>Плечо: <code>{lev}x</code></b>\n",
    "calc_liq_lbl": "💀 <b>Ликвидация (~): <code>{liq}</code></b>\n",
    "calc_error": "❌ Некорректное число. Попробуйте снова.",
    
    # Misc
    "wait": "⏳ Загрузка...",
    "need_wallet": "⛔ Сначала добавь кошелёк: /add_wallet",
    "select_pos": "👇 Выбери позицию:",
    "tag_usage": "⚠️ Пример: <code>/tag 0x... Main</code>",
    "threshold_usage": "⚠️ Пример: <code>/threshold 0x... 1000</code>",
    "settings_updated": "✅ Настройки обновлены.",
    "watch_added": "✅ Добавлено в список: <b>{symbol}</b>",
    "watch_removed": "🗑️ Удалено из списка: <b>{symbol}</b>",
    "prox_set": "✅ Порог 'Цена рядом' установлен на <b>{val}%</b>",
    "vol_set": "✅ Порог волатильности установлен на <b>{val}%</b>",
    "whale_set": "✅ Порог китов установлен на <b>${val}</b>",
    "whale_input": "⌨️ Введите минимальную сумму сделки кита (USD):\nПример: <code>/set_whale 250000</code>",
    "prox_input": "⌨️ Введите порог срабатывания для 'Цена рядом' (например 0.5%):\nПример: <code>/set_prox 0.5</code>",
    "vol_input": "⌨️ Введите порог волатильности (например 2.0%):\nПример: <code>/set_vol 2.0</code>",
    
    # Errors & Usage
    "add_wallet_usage": "⚠️ Пример: <code>/add_wallet 0x...</code>",
    "invalid_number": "❌ Некорректное число.",
    "unknown_price": "❌ Нет цены для <b>{symbol}</b>",
    "watch_usage": "⚠️ Пример: <code>/watch SOL</code>",
    "watch_invalid": "❌ Некорректный символ.",
    "unwatch_usage": "⚠️ Пример: <code>/unwatch SOL</code>",
    "set_vol_usage": "⚠️ Пример: <code>/set_vol 2.5</code> (Процент)",
    "set_whale_usage": "⚠️ Пример: <code>/set_whale 250000</code> (USD)",
    "set_prox_usage": "⚠️ Пример: <code>/set_prox 0.5</code> (Процент)",
    "pos_not_found": "❌ Позиция не найдена (закрыта?).",
    "card_error": "❌ Ошибка генерации.",
    "enable": "🟢 Включить",
    "disable": "🔴 Выключить",
    "sort_vol": "Сорт: Объем",
    "sort_funding": "Сорт: Фандинг",
    "sort_oi": "Сорт: OI",
    "sort_change": "Сорт: Изм. 24ч",
    
    # Market Alerts
    "btn_market_alerts": "🔔 Алерты Рынка",
    "market_alerts_title": "🔔 <b>Алерты обзора рынка</b>",
    "market_alerts_msg": "Настройте расписание отчетов по рынку.\nВы будете получать детальные дашборды (Обзор рынка + Alpha аналитика).\nПримечание: Все время указывается в <b>UTC</b>.",
    "add_time_prompt": "⌨️ Введите время в формате <b>ЧЧ:ММ</b> (UTC):\nПример: <code>09:00</code> или <code>18:30</code>",
    "invalid_time": "❌ Неверный формат. Используйте ЧЧ:ММ (например, 09:30)",
    "market_alert_added": "✅ Отчет запланирован на <b>{time} UTC</b>",
    "market_alert_removed": "🗑️ Отчет на <b>{time}</b> удален.",
    "no_market_alerts": "📭 У вас нет запланированных отчетов.",
    "btn_add_time": "➕ Добавить время",

    "market_report_global": "🌍 <b>Пульс Рынка</b>",
    "market_report_vol": "Объем 24ч",
    "market_report_oi": "Откр. интерес",
    "market_report_sentiment": "Настроение",
    "market_report_top_gainers": "🚀 <b>Лидеры роста (24ч)</b>",
    "market_report_top_losers": "📉 <b>Лидеры падения (24ч)</b>",
    "market_report_efficiency": "⚡ <b>Эффективность капитала (Vol/OI)</b>",
    "market_report_funding": "💰 <b>Высокий Фандинг (APR)</b>",
    "market_report_footer": "<i>Обновлено: {time} • Velox Intelligence</i>",
    
    # Buttons
    "btn_balance": "🏦 Баланс",
    "btn_positions": "🎰 Позиции",
    "btn_orders": "🧾 Ордера",
    "btn_pnl": "🧮 PnL",
    "btn_market": "📊 Рынок",
    "btn_stats": "📈 Статы",
    "btn_whales": "🐋 Киты",
    "btn_settings": "⚙️ Настройки",
    "btn_alerts": "🔔 Алерты",
    "btn_lang": "🌍 Язык",
    "btn_back": "🔙 Назад",
    "btn_graph": "📈 График",
    
    # Categories
    "cat_portfolio": "💼 Портфель",
    "cat_trading": "⚡ Торговля",
    "cat_market": "🌊 Рынок",
    "cat_settings": "⚙️ Настройки",
    
    "menu_portfolio": "💼 <b>Меню: Портфель</b>",
    "menu_trading": "⚡ <b>Меню: Торговля</b>",
    "menu_market": "🌊 <b>Меню: Рынок</b>",

    "btn_market_overview": "📊 Обзор Рынка",
    "btn_share": "🖼️ Share PnL",
    "btn_wallets": "👛 Кошельки",
    "btn_refresh": "🔄 Обновить",
    "btn_analysis": "🧠 Анализ",
    "btn_export": "📥 Скачать CSV",
    "btn_flex": "💪 Flex PnL",
    "flex_title": "💪 <b>PnL Flex Mode</b>",
    "flex_period_day": "День",
    "flex_period_week": "Неделя",
    "flex_period_month": "Месяц",
    "flex_period_all": "Все время",
    "flex_gen_error": "❌ Ошибка генерации.",
    
    # Metrics
    "equity": "💰 Equity",
    "wallet_bal": "💵 Баланс",
    "upnl": "📊 Нереал. PnL",
    "day_change": "📅 Изм. 24ч",
    "week_change": "📅 Изм. 7д",
    "month_change": "📅 Изм. 30д",
    "cum_pnl": "📈 Совок. PnL",
    "empty_pnl": "📭 Нет истории.",
    "liq_price": "💀 Liq",
    "roi": "ROI",
    "margin": "Margin",
    "leverage": "⚙️ Плечо",
    "funding": "Funding",
    "withdrawable": "💳 Доступно",
    "margin_ratio": "⚠️ M.Ratio",
    "win_rate": "🏆 Winrate",
    "total_trades": "🔢 Сделок",
    "profit_factor": "⚖️ Profit Factor",
    "gross_profit": "🟢 Прибыль",
    "gross_loss": "🔴 Убыток",
    
    "net_worth": "💰 Общий капитал",
    "spot_bal": "🔹 Спот",
    "perps_bal": "🔸 Фьючерсы",
    "total_upnl": "📊 Общий uPnL",
    "total_lbl": "Всего",
    "net_pnl": "Чистый PnL",
    "empty_state": "<i>Пусто</i>",
    
    # Whales
    "whale_alerts_on": "🔔 Алерты Китов: <b>ВКЛ</b>",
    "whale_alerts_off": "🔕 Алерты Китов: <b>ВЫКЛ</b>",
        "whale_intro": "Отслеживание сделок >     00k по всему рынку.",
            "funding_alert_set": "✅ Алерт на фандинг установлен: <b>{symbol}</b> {dir} <b>{val}% APR</b>",
            "oi_alert_set": "✅ Алерт на OI установлен: <b>{symbol}</b> {dir} <b>${val}M</b>",
            "new_listing_msg": "🚀 <b>Новый актив на Hyperliquid!</b>\n\nСимвол: <b>${sym}</b>\n\n<i>Торговля уже доступна. Используй /watch {sym} для отслеживания волатильности.</i>",
            "funding_alert_msg": "💰 <b>Алерт: Фандинг {sym}</b>\n\nТекущий: <b>{current}{unit}</b>\nЦель: {direction} <b>{target}{unit}</b>",
            "oi_alert_msg": "📊 <b>Алерт: Open Interest {sym}</b>\n\nТекущий: <b>{current}{unit}</b>\nЦель: {direction} <b>{target}{unit}</b>",
            "vaults_lbl": "Ваулты",
            "calc_exit_btn": "🧮 Выход {sym}",
            "exit_calc_title": "📊 <b>Калькулятор выхода: {sym}</b>\nДанные подтянуты из позиции.\n\n",
        }
        