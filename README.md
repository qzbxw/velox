# ⚡ Velox: Hyperliquid Wallet Watcher & Analytics Terminal

**Velox** is an institutional-grade Telegram bot designed for real-time monitoring, portfolio analytics, and market intelligence on the Hyperliquid L1 (Spot & Perpetuals). It transforms raw blockchain data into actionable insights through a sleek, visual-first interface.

---

## 🚀 Key Features

### 1. 🛡️ Real-Time Wallet Sentinel
*   **Multi-Wallet Tracking**: Monitor an unlimited number of wallets with custom tags and individual notification thresholds.
*   **Instant Fill Alerts**: Real-time notifications for trades (Spot/Perps) including realized PnL and fee tracking.
*   **Liquidation Watch**: Immediate alerts for account liquidations and margin ratio warnings (alerts at >80% margin usage).
*   **Proximity Alerts**: Never miss a fill. Velox notifies you when the market price approaches your open limit orders (customizable USD and percentage thresholds).

### 2. 📊 Visual Performance Analytics
*   **Equity Curves**: Dynamic generation of performance graphs showing account value history directly in Telegram.
*   **Flex PnL Cards**: Generate stylized, shareable ROI cards (Day/Week/Month/All-time) inspired by top-tier exchange UIs.
*   **Trade Statistics**: Comprehensive breakdown of Win Rate, Profit Factor, Gross Profit/Loss, and Net PnL.
*   **Data Export**: Export your entire trade history and equity data to CSV for external analysis.

### 3. 🌊 Market Intelligence
*   **Whale Watcher**: Live feed of institutional-sized trades ($50k+) for high-volume assets.
*   **Volatility Alerts**: Real-time monitoring of significant price moves (e.g., ±2% within 5 minutes) for your custom watchlist.
*   **Scheduled Market Dashboards**: Automated delivery of professional-grade market reports at user-defined times. Reports include three distinct visual dashboards:
    1.  **Market Overview**: Prices, Volume, Gainers/Losers, and Open Interest.
    2.  **Alpha & Sentiment**: Funding Rates (High/Low), Basis (Premium/Discount), and Leverage Density.
    3.  **Ecosystem & Liquidity**: Market Depth (Slippage), Capital Efficiency, and HLP Vault performance.
*   **Market Heatmaps**: Visual tables summarizing Funding Rates (APR), Open Interest, and 24h Volume across the Hyperliquid ecosystem.
*   **Custom Price Alerts**: User-defined "Above/Below" alerts with persistent monitoring.

### 4. 🛠️ Advanced Trading Tools
*   **Professional Calculator**: Sophisticated risk management tool for Spot and Perps. Calculates position size, leverage, liquidation price, fees, and R:R ratios.
*   **Inline Price Search**: Access real-time asset prices in any Telegram chat by typing `@your_bot_name SYMBOL`.
*   **Automated Summaries**: Daily digests and weekly performance reports delivered straight to your DM.

---

## 🛠️ Tech Stack

-   **Backend**: Python 3.10+ (Asynchronous event-driven architecture).
-   **Framework**: `aiogram 3.x` for the Telegram Bot interface.
-   **Real-time Data**: High-performance `websockets` integration with Hyperliquid L1.
-   **Database**: `MongoDB` with `Motor` (async driver) for persistent storage of trades and user settings.
-   **Data Vis**: `Matplotlib` & `Pandas` for dynamic image rendering and financial calculations.
-   **Configuration**: `Pydantic Settings` for robust environment management.
-   **Scheduling**: `APScheduler` for automated reports and background tasks.

---

## 📦 Installation & Setup

### Docker (Recommended)
The easiest way to deploy Velox is using Docker Compose.

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/qzbxw/velox.git
    cd velox
    ```

2.  **Configure environment**:
    ```bash
    cp .env.example .env
    # Edit .env with your BOT_TOKEN and MONGO_URI
    ```

3.  **Launch**:
    ```bash
    docker-compose up -d --build
    ```

### Local Development
1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Run the bot**:
    ```bash
    python -m bot.main
    ```

---

## 🎮 Commands Overview

| Command | Description |
| :--- | :--- |
| `/start` | Open the main interactive menu |
| `/add_wallet <0x...>` | Start tracking a new wallet |
| `/tag <0x...> <Name>` | Assign a human-readable name to a wallet |
| `/threshold <0x...> <USD>` | Set minimum trade size for notifications |
| `/alert <SYM> <Price>` | Set a custom price alert |
| `/watch <SYM>` | Add symbol to volatility watchlist |
| `/set_whale <USD>` | Set minimum threshold for whale alerts |
| `/export` | Get CSV export of trades and equity |

---

## 📐 Architecture

Velox is built with scalability and reliability in mind:
-   **`WSManager`**: A central engine managing real-time subscriptions and debouncing alerts to prevent spam.
-   **`Analytics Engine`**: Decoupled logic for financial calculations and image rendering.
-   **`Stateful Handlers`**: FSM-based interaction flow for complex operations like the risk calculator.
-   **`Service Layer`**: Abstraction over the Hyperliquid REST API for data consistency.

---

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

---

*Developed for traders who demand precision and speed.*
