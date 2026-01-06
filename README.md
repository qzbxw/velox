# ⚡ Velox: Institutional-Grade Hyperliquid Terminal

**Velox** is a high-performance Telegram terminal designed for professional traders on the **Hyperliquid L1**. It transforms complex blockchain data into beautiful, actionable visual intelligence, serving as a command center for your trading operations.

Beyond simple wallet tracking, Velox provides a suite of tools for portfolio analytics, market sentiment monitoring, and automated risk management.

---

## 🚀 Key Features

### 1. 🖥️ The Velox Terminal (New)
*   **Unified Dashboard**: Get a high-resolution terminal view of your entire portfolio (Equity, uPnL, Margin Usage, and Top Positions) in a single visual dashboard.
*   **Active Positions Table**: Generate professional, clean visual tables of all your active Spot and Perp positions.
*   **Real-time Fills**: Instant trade notifications with calculated realized PnL and fee tracking.

### 2. 🛡️ Risk Management & Sentinel
*   **⚠️ Risk Check**: One-tap system scan for high margin usage or positions nearing liquidation.
*   **Reverse Risk Calculator**: Professional tool to calculate exact position sizes based on a fixed dollar risk ($), helping you maintain strict discipline.
*   **Advanced Risk Suite**: Calculate SL/TP levels, R:R ratio, and estimated liquidation prices for both Spot and Perps.
*   **Omni-Channel Tracking**: Monitor multiple wallets simultaneously (Spot, Perpetuals, and HLP Vaults).

### 3. 📊 Visual Intelligence (Playwright-Powered)
*   **Flex PnL Cards**: Generate sleek, exchange-style ROI cards for your winning trades to share with your community.
*   **Portfolio Composition**: High-quality visual breakdown of your assets across Spot and Perps.
*   **Equity Curves**: Dynamic performance graphs showing account value history across all tracked wallets.
*   **Market Heatmaps**: Color-coded funding and price change heatmaps for instant market sentiment analysis.

### 4. ⏰ Automated Market Intelligence
*   **Scheduled Reports**: Set custom UTC times to receive full market dashboards automatically (Daily or Once).
*   **Whale Watcher**: Live monitoring of institutional-sized trades ($50k+) with customizable thresholds.
*   **Volatility Sentinel**: Real-time alerts for significant price moves (e.g., ±2% in 5 mins) on your watchlist.
*   **Triple-Layer Alerts**:
    1.  **Price Alerts**: Traditional Above/Below targets.
    2.  **Funding Alerts**: Alert when APR exceeds/drops below specific thresholds (e.g., alert if ETH funding > 50% APR).
    3.  **OI Alerts**: Monitor Open Interest spikes (in $M) for potential volatility.

### 5. 🛠️ Professional Trading Suite
*   **📜 Trading History**: Access your last 10 trades with detailed PnL and execution data.
*   **Data Terminal**: Export your entire trade history and equity data to CSV/Excel for external audits or tax reporting.
*   **Inline Terminal**: Instant price checks in any chat using `@your_bot_name SYMBOL`.
*   **Multilingual Support**: Fully localized in 🇬🇧 English and 🇷🇺 Russian.

---

## 🛠️ Tech Stack

-   **Runtime**: Python 3.10+ (Asynchronous / `asyncio`)
-   **Telegram Engine**: `aiogram 3.x` (State-of-the-art framework)
-   **Rendering Engine**: `Playwright` + `Jinja2` + `TailwindCSS` (HTML-to-Image rendering)
-   **Database**: `MongoDB` + `Motor` (Async persistence)
-   **Analytics**: `Pandas`, `Matplotlib`, `NumPy`
-   **Task Engine**: `APScheduler`
-   **L1 Connectivity**: High-speed `WebSockets` + REST API

---

## 📦 Quick Start

### 🐳 Docker Deployment (Recommended)
```bash
# Clone the terminal
git clone https://github.com/qzbxw/velox.git && cd velox

# Set up credentials
cp .env.example .env
# Edit .env with your BOT_TOKEN and MONGO_URI

# Launch
docker-compose up -d --build
```

### 🐍 Manual Setup
1. **Install Requirements**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
2. **Launch**:
   ```bash
   python -m bot.main
   ```

---

## 🎮 Command Interface

| Command | Action |
| :--- | :--- |
| `/start` | Open the interactive Main Menu |
| `/add_wallet <0x...>` | Register a new wallet for tracking |
| `/tag <0x...> <Name>` | Assign a custom name to a wallet |
| `/threshold <0x...> <$>` | Filter out small trade notifications |
| `/alert <SYM> <Price>` | Set a custom price target |
| `/f_alert <SYM> <APR>` | Alert on Funding Rate changes (APR %) |
| `/oi_alert <SYM> <$M>` | Alert on Open Interest (in millions) |
| `/watch <SYM>` | Add asset to real-time Volatility Watchlist |
| `/set_vol <%>` | Set custom volatility notification % |
| `/export` | Download trade history & equity CSV |

---

## 📐 Architecture

Velox is built on a decoupled, event-driven architecture:
*   **`WSManager`**: Handles thousands of concurrent events from Hyperliquid L1 with built-in debouncing and price monitoring.
*   **`Renderer`**: A dedicated rendering pipeline using a headless browser to ensure pixel-perfect financial visuals.
*   **`Service Layer`**: Abstracted API logic ensuring high reliability and failover protection.
*   **`Database`**: Schema-less storage optimized for high-frequency trade logging and user settings.

---

## 📄 License
This project is licensed under the **MIT License**.

---
*Built for traders who demand more than just a bot.*
