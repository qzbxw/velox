# ⚡ Velox: Complete Technical Documentation & Architectural Blueprint

This document serves as the **ultimate, exhaustive technical manual** for the Velox project. It contains every detail necessary for an AI or lead engineer to fully understand the project's logic, database schemas, alert mechanisms, RAG infrastructure, and rendering pipelines.

---

## 🏗️ 1. System Architecture Overview

Velox operates as an asynchronous, event-driven Telegram application. It is conceptually split into five internal sub-systems:
1.  **L1 WebSockets Engine (`ws_manager.py`)**: Persistent connections to the Hyperliquid node.
2.  **RAG AI & LLM Core (`market_overview.py`)**: Multi-agent system utilizing Google Search Grounding and RSS scraping.
3.  **Rendering Engine (`renderer.py` & `analytics.py`)**: Converts Jinja2 HTML templates into Retina-quality images via Playwright, and numerical arrays into Matplotlib graphs.
4.  **Delta Neutral & Math Suite (`delta_neutral.py` & `handlers.py`)**: Complex portfolio logic, risk equations, and yield calculations.
5.  **Billing & Limits Engine (`billing.py`)**: Hardcoded quota system linked to Telegram Stars payments.

---

## 🗄️ 2. Database Schema (MongoDB)

Velox uses a NoSQL structure optimized for fast reads during WebSocket event streams.

### Collections & Indexes
*   **`users`**: Stores user settings, AI settings, and legacy single-wallet bindings.
    *   *Fields*: `user_id`, `lang`, `hedge_settings`, `overview` (RAG schedules), `digest_settings`, `vault_reports`, `billing` (plan, active_until), `usage_daily` (limits tracking), `hedge_memory` (40-message sliding window for AI context).
*   **`wallets`**: Dedicated collection for tracking multiple wallets per user.
    *   *Indexes*: `[("user_id", 1), ("address", 1)]` (Unique).
    *   *Fields*: `address`, `user_id`, `tag` (custom name), `threshold` (min USD for fill alerts).
*   **`fills`**: Historical trade execution log.
    *   *Indexes*: `[("oid", 1)]` (Unique order ID).
    *   *Fields*: `user`, `coin`, `px`, `sz`, `side`, `time`, `fee`, `closedPnl`.
*   **`watchlist`**: User's monitored assets for volatility alerts.
    *   *Fields*: `user_id`, `symbols` (Array of Strings).
*   **`alerts`**: Active user-defined market thresholds.
    *   *Indexes*: `[("symbol", 1)]`, `[("user_id", 1)]`.
    *   *Fields*: `type` (`price`, `funding`, `oi`), `symbol`, `target`, `direction` (`above`/`below`).
*   **`vault_snapshots`**: Daily equity logs for HLP and user vaults to calculate Weekly/Monthly yield.
    *   *Indexes*: `[("user_id", 1), ("wallet", 1), ("vault_address", 1), ("snapshot_day", 1)]` (Unique).
*   **`billing_payments`**: Audit log for Telegram Stars transactions (`telegram_payment_charge_id`).
*   **`wallet_states`**: Tracks the last checked `timestamp` for the REST Ledger monitor to prevent duplicate deposit/withdrawal alerts.

---

## 📡 3. WebSocket L1 Monitors & Alerts (`ws_manager.py`)

The bot subscribes to multiple Hyperliquid WebSocket streams.

### 1. `allMids` Stream (Prices & Proximity)
*   **Price Cache**: Maintains an in-memory dictionary of all asset mid-prices.
*   **Proximity Alerts**: Iterates over all `openOrders` in memory. If `|current_px - limit_px| / limit_px` falls below the threshold (default: `1.0%` for Buys, `1.5%` for Sells), OR if the absolute distance is `< $10`, it fires an alert.
*   **Volatility Scanner (`/watch`)**: Keeps a 15-minute rolling deque `(timestamp, price)`. Checks every asset every few seconds. If an asset moves `> 2.0%` within a 5-minute window, it triggers a Volatility Alert.

### 2. `userFills` Stream (Executions)
*   Monitors execution of trades.
*   If `usd_value < user.threshold`, it silences the alert (unless it's a liquidation).
*   Calculates and displays Realized PnL and exact Fees.
*   Triggers the **Velox Assistant (Hedge Insight)** to assess portfolio risk post-fill.

### 3. `webData2` Stream (Clearinghouse & Margin)
*   **Liquidation Radar**: Polls `clearinghouseState.marginSummary`.
*   Calculates **Margin Ratio**: `totalMarginUsed / accountValue`.
*   If Ratio `> 0.8` (80%), an emergency liquidation warning is dispatched. Cooldown: 1 hour.

### 4. `trades` Stream (Whale Watcher)
*   Subscribes dynamically to the top 20 assets by volume (updated every 5 mins).
*   Intercepts every public trade. If `sz * px > user.whale_threshold` (default $50,000), it sends a Whale Alert. 
*   Includes deduplication logic via trade hashes to prevent spam from aggregated fills.

---

## 🎨 4. Render Engine (Playwright & Jinja2)

Instead of relying solely on Telegram text, Velox generates UI components locally.

### Templates (`bot/templates/`)
1.  **`terminal_dashboard.html`**: A massive overarching view. Displays Equity, uPnL, margin bars, leverage, and top 5 sorted open positions.
2.  **`portfolio_composition.html`**: Grouped donut chart (Spot vs Perps vs Vaults).
3.  **`market_overview.html`**: The AI summary image, showing Fear & Greed Index, Top Gainers/Losers, Highest Volume, and Highest Funding rates.
4.  **`funding_heatmap.html`**: Renders a dynamic grid of colored blocks representing APR values across the Hyperliquid universe.
5.  **`liquidity_stats.html`**: Calculates estimated slippage for a $100k market order on every asset.
6.  **`account_flex.html` & `pnl_card.html`**: Generates high-quality ROI images suitable for Twitter/X sharing.

### Rendering Logic
*   Uses `playwright.async_api`. Runs in headless mode (`--no-sandbox`, `--disable-dev-shm-usage`).
*   Sets `device_scale_factor=2` to ensure the output PNG is crisp (Retina quality).
*   Utilizes an `asyncio.Semaphore(3)` to prevent RAM exhaustion during mass broadcasts.

---

## 🧠 5. The RAG AI Ecosystem (gemini-3.1-flash-lite-preview)

Velox uses a highly advanced, multi-tiered Prompt Engineering setup using Google's Gemini API.

### A. Market Insight Agent (`market_overview.py`)
Triggered via `/overview` or cron jobs (Morning/Evening schedules).
1.  **Data Ingestion**: 
    *   **Farside ETF Scraper**: Uses BeautifulSoup to parse HTML from `farside.co.uk/btc/` and `eth/`, finding the exact daily flow in millions.
    *   **Hyperliquid Stats**: Calculates 24h Global Volume and Total Open Interest.
    *   **Fear & Greed Index**: REST call to `alternative.me`.
2.  **News Agent (Google Search Tooling)**: 
    *   Fires a distinct prompt using the `google_search` tool to ground responses in current crypto events.
    *   Also ingests 13 hardcoded RSS feeds (CoinDesk, The Block, Decrypt, etc.) utilizing `feedparser`.
3.  **Synthesis (Hedge Agent)**: 
    *   Receives the numerical data + the text digest with `groundingMetadata` for source transparency.
    *   Prompt explicitly demands a 500-char summary, a single-word sentiment (BULLISH/BEARISH/NEUTRAL/EXPLOSIVE), and the "next_event" to watch.

### B. Velox Assistant (Hedge Insight)
A reactionary AI triggered automatically by WebSockets (Fills, Liquidations, Whales).
*   **Context Injection**: Before prompting the AI, Velox fetches the user's *actual* `spot_balances` and `perps_state`. 
*   **Relevance Hinting**: The code injects hidden instructions: *“User has a LONG on BTC and a Whale just dumped BTC. Warn them.”* or *“User has no open positions, give a generic market view.”*
*   **Sliding Window Memory**: Appends the last 40 interactions to the `hedge_memory` array in MongoDB so the AI remembers past warnings.

---

## 🧮 6. Delta Neutral & Yield Suite (`delta_neutral.py`)

A professional suite for basis traders.

### Core Calculations
*   **Delta Match**: Scans all Spot holdings (e.g., +10 ETH) and matches them against short Perp positions (e.g., -10 ETH).
*   **Net Delta ($)**: `(Spot Quantity + Perp Quantity) * Current Mark Price`.
*   **Net Delta (%)**: `(Net Delta $) / (Total Notional Value) * 100`.
*   **Drift Monitoring**: A background cron job (`scheduler.py`) evaluates the portfolio every 30 minutes. If Delta % moves beyond user tolerance (default 5%), a "Rebalance Required" alert is dispatched.
*   **Yield Calculation**: Fetches `userFundingHistory`. Aggregates all *paid* vs *received* funding to calculate true APR. Checks for continuous "Negative Funding Streaks" (e.g., paying funding for 4+ consecutive hours).

---

## 🎯 7. The Institutional Risk Calculator

Accessible via `calc_start` callback. Implements a "Reverse Risk" algorithm.

**Input Flow**:
1. User enters: `[Balance] [Entry Price] [Stop Loss Price]`

**Execution Logic**:
*   Determines `Risk Per Coin = abs(Entry - Stop Loss)`.
*   Calculates `Position Size (Coins) = Total Risk Allowance (USD) / Risk Per Coin`.
*   Calculates `Position Size (USD) = Position Size (Coins) * Entry`.
*   Calculates `Required Leverage = Position Size (USD) / Balance`.
*   Calculates exact `Liquidation Price` based on the leverage curve.
*   Calculates Taker Fees (`0.00035 * 2`).
*   Spits out a **50/50 Take Profit Scaling Plan** based on a 1:2 Risk/Reward ratio.

---

## 🎮 8. Telegram Command & Feature Matrix

### Portfolio Management
*   `/start` - Initializes user in MongoDB, shows welcome screen.
*   `/add_wallet <address>` - Adds an L1 address to tracking.
*   `/tag` - Opens interactive menu to assign a custom string (e.g., "Main") to a wallet.
*   `/threshold` - Sets the minimum USD value (e.g., $1000) for a trade fill to trigger a notification.
*   `/funding` - Opens the multipage Yield Analytics UI.
*   `/export` - Triggers a background generation of `.csv` files containing Trade History and Daily Equity Curve data. (Pro Feature).
*   `/status` - Opens the Delta Neutral Analysis dashboard.

### Alert Engine
*   `/alert <sym> <price>` - Sets a hard price threshold alert.
*   `/f_alert <sym> <apr>` - Sets an alert for Funding Rate (e.g., `/f_alert ETH 50` alerts if ETH funding > 50% APR).
*   `/oi_alert <sym> <millions>` - Sets an Open Interest alert (e.g., `/oi_alert SOL 100` alerts if SOL OI > $100M).
*   `/watch <sym>` - Adds symbol to Volatility Scanner (±2% moves in 5 mins).
*   `/unwatch <sym>` - Removes from Scanner.
*   `/set_vol <pct>` - Modifies the default 2% Volatility threshold.
*   `/set_whale <usd>` - Sets the global trade scanner minimum USD (e.g., $100000).
*   `/set_prox <pct>` - Adjusts the Limit Order proximity warning distance (e.g., 0.5%).

### AI & Intelligence
*   `/overview` - Forces an immediate RAG Market Report generation.
*   `/overview_settings` - Configures the AI Persona (custom prompt injection) and sets daily delivery schedules (e.g., 08:00 UTC).

### System & Monetization
*   `/billing` - Opens the subscription UI. Generates Telegram Stars payment invoices (via `bill_buy:pro:1` callback data).
*   `/help` - Documentation.
*   `/paysupport` - Contact info for billing issues.

---

## ⚙️ 9. Background Workers (APScheduler)

Velox uses `AsyncIOScheduler` located in `bot/scheduler.py` to manage background tasks.

1.  **Scheduled Digests (`send_scheduled_digests`)**: Runs every minute. Checks the `users` collection to see if any user has requested a `portfolio_daily`, `portfolio_weekly`, or `vault_monthly` report for the current minute.
2.  **Vault Snapshots (`collect_vault_snapshots`)**: Runs daily at 00:15 UTC. Fetches equity from `userVaultEquities` and saves it to MongoDB to enable historical plotting.
3.  **Market Overviews (`send_scheduled_overviews`)**: Runs at the top of every hour (Minute 0). Broadcasts AI reports to users who have that hour configured.
4.  **Delta Drift Monitor (`run_delta_neutral_alerts`)**: Runs every 30 minutes.

---

## 💳 10. Billing Limits & Quota Logic (`billing.py`)

Velox enforces hard quotas per subscription tier. 

| Feature | **Free** | **Pro ($12 / 850⭐)** | **Pro+ ($24 / 1700⭐)** |
| :--- | :---: | :---: | :---: |
| **Tracked Wallets** | 1 | 3 | 10 |
| **Watchlist Symbols** | 7 | 30 | 150 |
| **Active Alerts** | 5 | 30 | 120 |
| **Market Reports Slots** | 1 | 4 | 12 |
| **Daily Overview Runs** | 3 | 25 | 120 |
| **Daily AI Assistant Messages** | 10 | 80 | 400 |
| **Automated Digest Slots** | 0 | 3 | 5 |
| **Terminal Visuals** | ❌ | ✅ | ✅ |
| **CSV Exports** | ❌ | ✅ | ✅ |
| **Shareable PnL Cards** | ❌ | ✅ | ✅ |

*Usage tracking resets automatically every day based on UTC timestamps stored in `usage_daily`.*

---
*End of Technical Specification.*
