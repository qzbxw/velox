# ⚡ Velox Hedge AI: Institutional Hyperliquid Terminal

![Velox Hedge AI](https://img.shields.io/badge/Velox-Hedge_AI-blueviolet?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Production-success?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**Velox Hedge AI** is not just a Telegram bot; it is an autonomous, institutional-grade trading terminal and risk management system built specifically for the **Hyperliquid L1** ecosystem.

Powered by **Google Gemini AI** and advanced quantitative analytics, Velox acts as your personal hedge fund analyst, monitoring your portfolio, analyzing market sentiment, and managing risk in real-time, 24/7. It transforms raw blockchain data into high-resolution visual intelligence, giving you the edge of a professional trading desk on your mobile device.

---

## 🧠 The AI Core: Velox Intelligence

At the heart of the system lies the **Velox AI Engine**, designed to provide more than just alerts. It offers deep market understanding:

*   **AI Market Overviews**: Integrates with LLMs (Google Gemini) to generate human-readable summaries of market conditions, funding rate anomalies, and volatility structures.
*   **Sentiment Analysis**: Aggregates Fear & Greed indices, funding heatmaps, and Open Interest (OI) flows to determine the psychological state of the market.
*   **Smart Anomaly Detection**: The AI doesn't just watch price; it watches *deviation*. It detects when funding rates decouple from price action or when OI spikes without volume, alerting you to potential squeezes or traps.

---

## 🚀 Key Modules & Capabilities

### 1. 🖥️ The Velox Terminal (Visual Dashboard)
Velox bypasses standard text alerts by using a **Headless Browser Rendering Engine (Playwright)** to generate pixel-perfect, CSS-styled financial dashboards directly in Telegram.
*   **Unified Dashboard**: A single high-res image showing Equity, uPnL, Margin Usage, and Top Positions.
*   **Flex PnL Cards**: Generate "Exchange-Style" ROI cards for any position to share with communities, complete with entry, mark price, and leverage data.
*   **Portfolio Composition**: Visual pie charts and breakdowns of your asset allocation (Spot vs. Perps vs. Vaults).

### 2. 🛡️ Velox Hedge: Risk Sentinel
The "Hedge" in our name stands for uncompromised safety. The bot includes a sophisticated Risk Engine:
*   **Liquidation Radar**: Instantly scans all open positions for liquidation proximity.
*   **Margin Health Monitor**: Alerts when Account Margin Ratio exceeds safe thresholds.
*   **Reverse Risk Calculator**: A professional calculator that derives position size based on your dollar risk tolerance (e.g., "I want to risk $100 on this trade").
*   **Exposure Analysis**: Tracks net delta exposure across all sub-accounts.

### 3. ⚡ Real-Time L1 Connectivity
Velox connects directly to Hyperliquid's **WebSocket** feed for institutional latency:
*   **Event-Driven Architecture**: Uses Python's `asyncio` for non-blocking handling of thousands of concurrent price updates.
*   **Debounced Alerts**: Intelligent filtering prevents alert fatigue during high-volatility events.
*   **Multi-Wallet Tracking**: Monitor an unlimited number of wallets (Spot, Perps, and HLP Vaults) simultaneously.

### 4. 📊 Quantitative Analytics
*   **Funding Heatmaps**: Visual color-coded grids showing APR hotspots across the entire market.
*   **Liquidity Stats**: Analysis of order book depth and volume profiles.
*   **Whale Watcher**: Filters and reports individual trades exceeding $50k-$100k+ in real-time.
*   **Volatility Watchlist**: Custom watchlists that alert on rapid % moves within configurable time windows (e.g., ±2% in 5 mins).

---

## 📂 Project Structure & Architecture

The codebase is engineered for scalability and modularity. Here is a detailed breakdown of the `bot/` core:

```
bot/
├── main.py              # 🚀 Entry Point: Bootstraps Bot, DB, WS Manager, and Scheduler.
├── config.py            # ⚙️ Configuration: Pydantic-based settings management and env validation.
├── handlers.py          # 🎮 Interaction Layer: massive router handling all user commands, callbacks, and menus.
├── ws_manager.py        # 🔌 L1 Uplink: Manages WebSocket connections to Hyperliquid, handles heartbeats and subscriptions.
├── renderer.py          # 🎨 Visual Engine: Controls Playwright to render HTML templates into PNG images.
├── analytics.py         # 📈 Data Science: Pandas/NumPy logic for calculating PnL curves, heatmaps, and stats.
├── database.py          # 💾 Persistence: Async Motor (MongoDB) driver for user state, wallets, and alerts.
├── market_overview.py   # 📰 Intelligence: Aggregates data for the AI/Global market reports.
├── scheduler.py         # ⏰ Cron Jobs: Manages recurring tasks like funding checks and daily reports.
├── services.py          # 🛠️ Service Layer: Business logic for API calls, price fetching, and balance calculations.
├── locales.py           # 🌍 i18n: Localization system supporting English and Russian.
└── templates/           # 🖼️ UI Templates: Jinja2 + TailwindCSS HTML templates for image generation.
    ├── terminal_dashboard.html
    ├── pnl_card.html
    ├── funding_heatmap.html
    └── ...
```

---

## 🛠️ Installation & Deployment

### Prerequisites
*   **Docker & Docker Compose** (Recommended)
*   OR Python 3.10+ and MongoDB (Manual)

### Option A: Docker (Production Ready)

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/your-repo/velox-hedge-ai.git
    cd velox-hedge-ai
    ```

2.  **Configure Environment**
    Copy the example configuration:
    ```bash
    cp .env.example .env
    ```
    Edit `.env` and populate the fields (see Configuration section below).

3.  **Launch Velox**
    ```bash
    docker-compose up -d --build
    ```
    The bot will build the image, install Playwright browsers, and start the container.

### Option B: Manual Setup (Development)

1.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Install Browsers** (Required for Rendering Engine)
    ```bash
    playwright install chromium
    ```

3.  **Run MongoDB**
    Ensure a local MongoDB instance is running on port 27017.

4.  **Start the Bot**
    ```bash
    python -m bot.main
    ```

---

## ⚙️ Configuration

The `.env` file is the control panel for Velox Hedge.

| Variable | Description | Required |
| :--- | :--- | :--- |
| `BOT_TOKEN` | Telegram Bot API Token from @BotFather | ✅ Yes |
| `MONGO_URI` | MongoDB Connection String (default: `mongodb://mongo:27017`) | ✅ Yes |
| `GEMINI_API_KEY` | Google Gemini API Key for AI Insights | ⚠️ Optional (Recommended) |
| `HYPERLIQUID_WS_URL` | WebSocket Endpoint (Default: Mainnet) | ✅ Yes |
| `HYPERLIQUID_API_URL` | REST API Endpoint (Default: Mainnet) | ✅ Yes |
| `PROXIMITY_THRESHOLD` | % Distance for price alerts (e.g., 0.01 for 1%) | ❌ No |
| `ALERT_COOLDOWN` | Seconds between repeat alerts | ❌ No |

---

## 🎮 Command Reference

| Command | Description |
| :--- | :--- |
| `/start` | Initializes the Velox Terminal interface. |
| `/overview` | **AI Market Report**: Triggers the Gemini-powered market analysis. |
| `/add_wallet <addr>` | Adds a wallet to the monitoring engine. |
| `/watch <SYMBOL>` | Adds a specific asset to the high-frequency volatility scanner. |
| `/alert <SYM> <$$>` | Sets a server-side price alert. |
| `/f_alert <SYM> <%>` | Sets a Funding Rate alert (APR). |
| `/oi_alert <SYM> <$M>`| Sets an Open Interest alert (in Millions USD). |
| `/export` | Generates and sends a CSV of trade history and equity curves. |
| `/help` | Displays the help menu. |

---

## 🔒 Security & Privacy

Velox Hedge AI is a **non-custodial** monitoring tool.
*   **Read-Only**: The bot only requires wallet addresses (public keys) to function. It **never** asks for Private Keys or Seed Phrases.
*   **Data Isolation**: All user data is stored in your private MongoDB instance.
*   **Source Available**: Fully auditable Python codebase.

---

## 📜 License

This project is licensed under the **MIT License**. You are free to fork, modify, and deploy Velox Hedge AI for personal or commercial use.

---

*Velox Hedge AI — Clarity in Chaos.*