# 🤖 Velox — Hyperliquid Watcher

**Velox** is a powerful, watch-only Telegram bot for monitoring your [Hyperliquid](https://hyperliquid.xyz) portfolio. It allows you to track wallets, receive real-time notifications for fills and price alerts, and analyze your PnL without ever needing your private keys.

> **Safety First:** This bot operates in **watch-only** mode. It does NOT require private keys or API signing rights. It simply listens to public blockchain data and user-specified events.

---

## ✨ Features

*   **👀 Watch-Only Tracking:** Monitor any Hyperliquid wallet address (`0x...`) safely.
*   **🎰 Perps Support:** Full monitoring of Perpetual positions including Leverage, Liquidation Price, and ROI%.
*   **🔔 Real-time Notifications:**
    *   **Fills:** Get instant alerts when your buy or sell orders are executed.
    *   **Proximity Alerts:** Receive a notification when the market price gets close to your open limit orders.
*   **💰 Portfolio Insights:**
    *   **`/balance`**: View spot balances, perps equity, and account margin.
    *   **`/positions`**: Detailed view of all active long/short positions.
*   **📊 Market Intelligence:**
    *   **`/funding`**: Check real-time funding rates and APR for any asset.
    *   **`/stats`**: View Open Interest (OI) and 24h Volume.
    *   **`/market`**: Quick snapshot of BTC/ETH/HYPE volatility and price moves.
*   **🌍 Multi-language:** Supports **English** and **Russian**.

---

## 🚀 Quick Start (Docker)

The easiest way to run Velox is using Docker.

### 1. Clone the repository
```bash
git clone https://github.com/qzbxw/hyperliquid-wallet-watcher.git
cd hyperliquid-wallet-watcher
```

### 2. Configure Environment
Create a `.env` file from the example:
```bash
cp .env.example .env
```
Edit `.env` and add your **Telegram Bot Token** (get one from [@BotFather](https://t.me/BotFather)):
```ini
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
MONGO_URI=mongodb://mongo:27017
MONGO_DB_NAME=hyperliquid_bot
```

### 3. Run with Docker Compose
```bash
docker compose up -d --build
```
The bot should now be running! Open your bot in Telegram and press `/start`.

---

## 🛠 Manual Installation (Local)

If you prefer running without Docker:

**Prerequisites:** Python 3.10+, MongoDB running locally.

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Set Environment Variables:**
    Ensure `.env` is configured (set `MONGO_URI` to your local MongoDB instance, e.g., `mongodb://localhost:27017`).

3.  **Run the Bot:**
    ```bash
    python -m bot.main
    ```

---

## 📚 Commands Guide

| Command | Description |
| :--- | :--- |
| `/start` | Show the main menu and welcome message. |
| `/add_wallet <0x...>` | Start tracking a wallet address. |
| `/balance` | Show current spot balances and perps equity. |
| `/positions` | Show open Futures (Perps) positions. |
| `/orders` | Show open limit orders with distance to fill. |
| `/funding <SYM>` | Show funding rates (current & APR). |
| `/stats <SYM>` | Show OI and 24h Volume. |
| `/pnl` | Show PnL analysis (Realized/Unrealized). |
| `/market` | View volatility and price moves for top assets. |
| `/watch <SYMBOL>` | Add a token to your personal watchlist. |
| `/lang` | Switch language (English/Russian). |

---

## 📄 License

MIT License.