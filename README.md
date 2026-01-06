# ⚡ Velox: Institutional-Grade Hyperliquid Terminal

**Velox** is a high-performance Telegram terminal designed for professional traders on the **Hyperliquid L1**. It transforms complex blockchain data into beautiful, actionable visual intelligence. 

Beyond simple wallet tracking, Velox provides a suite of tools for portfolio analytics, market sentiment monitoring, and automated risk management.

---

## 🚀 Key Features

### 1. 🛡️ Advanced Wallet Sentinel
*   **Omni-Channel Tracking**: Monitor multiple wallets simultaneously (Spot, Perpetuals, and HLP Vaults).
*   **Smart Notifications**: Custom filters to ignore "noise" (set USD thresholds for alerts).
*   **Real-time Fills**: Instant trade notifications with calculated realized PnL and fee tracking.
*   **Vault Analytics**: Automatic tracking of HLP and other vault equity performance.
*   **Proximity Alerts**: Get notified when market price approaches your open limit orders (customizable % distance).

### 2. 📊 Visual Intelligence (Playwright-Powered)
*   **Flex PnL Cards**: Generate sleek, exchange-style ROI cards for your winning trades.
*   **Portfolio Composition**: High-quality visual breakdown of your assets across Spot and Perps.
*   **Equity Curves**: Dynamic performance graphs showing account value history.
*   **Market Dashboards**: Professional-grade visual reports including:
    *   **Alpha & Sentiment**: Funding Rates (APR), Basis (Premium/Discount), and Leverage Density.
    *   **Liquidity & Depth**: Market Depth, Slippage monitoring, and Open Interest trends.
    *   **Funding Heatmaps**: Color-coded tables for instant market sentiment analysis.

### 3. ⏰ Automated Market Intelligence
*   **Scheduled Reports**: Set custom UTC times to receive full market dashboards automatically.
*   **Whale Watcher**: Live monitoring of institutional-sized trades ($50k+).
*   **Volatility Sentinel**: Real-time alerts for significant price moves (e.g., ±2% in 5 mins) on your watchlist.
*   **Triple-Layer Alerts**:
    1.  **Price Alerts**: Traditional Above/Below targets.
    2.  **Funding Alerts**: Alert when APR exceeds/drops below specific thresholds.
    3.  **OI Alerts**: Monitor Open Interest spikes for potential volatility.

### 4. 🛠️ Professional Trading Suite
*   **Risk Calculator**: Institutional-grade calculator for Spot/Perps. Computes position sizing based on risk-per-trade, SL/TP levels, R:R ratio, and estimated liquidation prices.
*   **Data Terminal**: Export your entire trade history and equity data to CSV/Excel for external audits.
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
1. **Install Chromium for Rendering**:
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
| `/f_alert <SYM> <APR>` | Alert on Funding Rate changes |
| `/oi_alert <SYM> <$M>` | Alert on Open Interest (in millions) |
| `/watch <SYM>` | Add asset to real-time Volatility Watchlist |
| `/set_vol <%>` | Set custom volatility notification % |
| `/export` | Download trade history & equity CSV |

---

## 📐 Architecture

Velox is built on a decoupled, event-driven architecture:
*   **`WSManager`**: Handles thousands of concurrent events from Hyperliquid L1 with built-in debouncing.
*   **`Renderer`**: A dedicated rendering pipeline using a headless browser to ensure pixel-perfect financial visuals.
*   **`Service Layer`**: Abstracted API logic ensuring high reliability and failover protection.
*   **`Database`**: Schema-less storage optimized for high-frequency trade logging.

---

## 📄 License
This project is licensed under the **MIT License**.

---
*Built for traders who demand more than just a bot.*