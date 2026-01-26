# ⚡ Velox & 🧠 Velox AI: Institutional Hyperliquid Terminal

![Velox AI](https://img.shields.io/badge/Velox-AI-blueviolet?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Production-success?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**Velox & Velox AI** is a dual-core institutional trading system built for **Hyperliquid L1**. It combines a high-performance, real-time tracking terminal (**Velox**) with an autonomous quantitative analyst (**Velox AI**) powered by Google Gemini.

---

# 🖥️ Part 1: Velox Terminal
**The Execution & Monitoring Engine.**
Velox is designed to replace standard exchange interfaces with a Telegram-based "Headless Terminal" that offers superior latency and risk management tools.

### 1. 🔔 Advanced Alerting Suite
Velox monitors the L1 state via WebSockets to provide alerts that standard interfaces cannot match:

*   **🎯 Proximity Alerts (Limit Order Tracking)**
    *   Monitors your open Limit Orders in real-time.
    *   Alerts you when market price gets within **0.5% - 1.0%** (configurable) of your order.
    *   *Why?* To let you know you are about to get filled or if front-running is occurring.
*   **🐋 Whale Watcher**
    *   Scans **all market trades** globally on Hyperliquid.
    *   Filters for trades exceeding **$50,000 - $250,000+** (user configurable).
    *   Includes symbol filtering (Watchlist only vs. Global).
*   **🌊 Volatility Scanner**
    *   High-frequency monitor for rapid price movements.
    *   Alerts on **±2% moves within 5 minutes** (configurable windows).
    *   Perfect for catching pump/dump starts before they hit major news channels.
*   **📊 Market Structure Alerts**
    *   **Funding Rates**: Set alerts for APR spikes (e.g., >50% APR) to catch delta-neutral yield opportunities.
    *   **Open Interest (OI)**: Alert when OI crosses $100M+ thresholds to detect leverage build-up.
    *   **Listing Monitor**: Instantly detects new assets added to the Hyperliquid universe (Spot & Perps) within seconds of deployment.

### 2. 🛡️ Risk Management & Calculator
*   **Liquidation Radar**: Real-time monitoring of all sub-accounts. Alerts immediately if **Margin Ratio > 80%**.
*   **Ledger Monitor**: Detects and reports **Deposits, Withdrawals, and Internal Transfers** for all tracked wallets (great for team/security monitoring).
*   **Institutional Calculator**: A built-in "Reverse Risk" calculator.
    *   *Input*: Entry, Stop Loss, and **Dollar Risk** (e.g., "I want to risk $100").
    *   *Output*: Exact position size (in Coins and USD) and Leverage required.
    *   *Visuals*: Generates a "Trade Plan" card with R:R ratio, fees, and scaling targets.

### 3. 🎨 Visual Engine (Headless Browser)
Velox does not send text walls. It uses **Playwright (Chromium)** to render HTML/CSS templates into high-resolution images:
*   **Unified Dashboard**: A single snapshot showing Equity, uPnL, Margin Usage, and top positions across all wallets.
*   **Flex PnL Cards**: Generate "Exchange-Style" ROI cards with entry, mark price, and leverage data (perfect for sharing).
*   **Portfolio Composition**: Donuts charts breaking down Spot vs. Perps vs. HLP Vaults.
*   **Liquidity Heatmaps**: Visualizes orderbook depth and slippage ($100k impact) for top assets.

### 4. 💼 Multi-Wallet & Export
*   **Unlimited Wallets**: Track 1 or 100 wallets simultaneously.
*   **Custom Tags**: Name your wallets (e.g., "Main", "Degen", "Vault").
*   **CSV Export**: One-click export of full trade history, funding payments, and equity curves for tax/analysis.

---

# 🧠 Part 2: Velox AI
**The Quantitative Analyst.**
Velox AI is not a chatbot; it is an event-driven analytical layer injected into the terminal.

### 1. ⚡ Contextual Insights
When a major event occurs, Velox AI analyzes it instantly and adds a "Commentary" layer:
*   **On Liquidation**: Analyzes *why* it happened (volatility spike vs. slow bleed) and suggests collateral adjustments.
*   **On Whale Trade**: contextualizes the trade (e.g., "Whale bought $500k SOL near resistance, possible breakout").
*   **On New Listing**: Scrapes project info and provides a rapid fundamental summary.

### 2. 📰 Autonomous Market Reports
Velox AI scrapes global data sources to generate human-readable reports:
*   **Data Sources**: Hyperliquid L1 Data (OI, Vol, Basis), **Farside Investors** (BTC/ETH ETF Flows), and RSS News Feeds (CoinDesk, Decrypt).
*   **Scheduled Reports**:
    *   **Morning Brief (06:00 UTC)**: Overnight moves + ETF flows.
    *   **Evening Wrap (18:00 UTC)**: Day's session summary.
    *   **Weekly Digest (Sunday)**: Net PnL, realized gains, and net flow analysis.
*   **Custom Persona**: You can configure Velox AI's personality (e.g., "Brief & Professional" or "Degen Slang") via `/overview_settings`.

### 3. 💬 AI Chat
An interactive interface where you can ask questions about your specific portfolio:
*   *"What is my current exposure to SOL?"*
*   *"Summarize the last 24h of funding payments."*
*   *"Am I at risk of liquidation?"*

---

## 🛠️ Installation & Setup

### Prerequisites
*   **Docker** (Recommended) OR Python 3.10+ & MongoDB.

### Docker (Recommended)
```bash
# 1. Clone & Configure
git clone https://github.com/qzbxw/velox.git
cd velox
cp .env.example .env
# Edit .env with your BOT_TOKEN and GEMINI_API_KEY

# 2. Deploy
make deploy
```

### Manual (No Docker)
```bash
pip install -r requirements.txt
playwright install chromium
python -m bot.main
```

### Quick Commands
```bash
make deploy        # Pull, rebuild, restart
make quick         # Pull & restart (no rebuild)
make logs          # View logs
make stop          # Stop bot
make help          # All commands
```

---

## ⚙️ Configuration (.env)

| Variable | Description | Required |
| :--- | :--- | :--- |
| `BOT_TOKEN` | Telegram Bot API Token | ✅ |
| `MONGO_URI` | MongoDB Connection String | ✅ |
| `GEMINI_API_KEY` | Google Gemini API Key (for AI features) | ⚠️ (Rec.) |
| `HYPERLIQUID_WS_URL` | WebSocket Endpoint (Default: Mainnet) | ✅ |
| `PROXIMITY_THRESHOLD` | % distance for Limit Order alerts (default: 0.01) | ❌ |
| `WATCH_ALERT_PCT` | % move for Volatility Scanner (default: 0.02) | ❌ |

---

## 🎮 Command Reference

### 🔹 Portfolio & Tracking
| Command | Usage | Description |
| :--- | :--- | :--- |
| `/add_wallet` | `/add_wallet 0x...` | Track a new Hyperliquid address (Spot/Perps). |
| `/tag` | `/tag 0x... Main` | Assign a readable name to a wallet. |
| `/threshold` | `/threshold 0x... 500` | Set min USD value to trigger fill alerts (ignore dust). |
| `/funding` | `/funding` | Show a log of funding payments from the last 24h. |
| `/export` | `/export` | Generate CSV files for Trade History and Equity. |

### 🔹 Alerts & Monitoring
| Command | Usage | Description |
| :--- | :--- | :--- |
| `/alert` | `/alert BTC 60000` | Set a server-side price alert. |
| `/f_alert` | `/f_alert ETH 50` | Alert if Funding Rate > 50% APR (or < -20%). |
| `/oi_alert` | `/oi_alert SOL 100` | Alert if Open Interest crosses $100M. |
| `/watch` | `/watch HYPE` | Add asset to **Volatility Scanner** (±2% moves). |
| `/set_whale` | `/set_whale 100000` | Set min USD threshold for global **Whale Watcher**. |

### 🔹 Velox AI & Market
| Command | Usage | Description |
| :--- | :--- | :--- |
| `/overview` | `/overview` | Force-generate an AI Market Report now. |
| `/overview_settings` | `/overview_settings` | Configure report schedule and AI persona. |
| `/calc` | Button only | Open the Risk/Position Calculator. |

---

## 🔒 Security & Privacy
*   **Non-Custodial**: Velox **never** asks for Private Keys. It watches public addresses only.
*   **Local Data**: All portfolio data is stored in your private MongoDB.
*   **Open Source**: The code is fully auditable.

---

*Velox x Velox AI*