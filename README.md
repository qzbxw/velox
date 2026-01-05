# 🤖 Velox — Hyperliquid Watcher

**Velox** is a powerful, watch-only Telegram bot for monitoring your [Hyperliquid](https://hyperliquid.xyz) portfolio. It allows you to track wallets, receive real-time notifications for fills and price alerts, and analyze your PnL without ever needing your private keys.

> **Safety First:** This bot operates in **watch-only** mode. It does NOT require private keys or API signing rights. It simply listens to public blockchain data and user-specified events.

---

## ✨ Features

*   **👀 Watch-Only Tracking:** Monitor any Hyperliquid wallet address (`0x...`) safely.
*   **🔔 Real-time Notifications:**
    *   **Fills:** Get instant alerts when your buy or sell orders are executed.
    *   **Proximity Alerts:** Receive a notification when the market price gets close to your open limit orders (configurable threshold).
*   **💰 Portfolio Insights:**
    *   **`/balance`**: View spot balances, portfolio allocation (%), and Unrealized PnL (uPnL).
    *   **`/pnl`**: Track Realized PnL over 24h, 7d, and 30d periods (calculated from recorded history).
*   **🧾 Order Management:**
    *   **`/orders`**: List open limit orders with "distance to fill" and "edge" calculations.
*   **📊 Market Data:**
    *   **`/market`**: Quick snapshot of BTC/ETH volatility and price moves.
    *   **`/watch`**: Create a custom watchlist for specific assets.
*   **🌍 Multi-language:** Supports **English** and **Russian**.

---

## 🚀 Quick Start (Docker)

The easiest way to run Velox is using Docker.

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/hyperliquid-wallet-watcher.git
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
docker-compose up -d
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
| `/balance` | Show current spot balances, portfolio % and uPnL. |
| `/orders` | Show open limit orders and how close they are to filling. |
| `/pnl` | Show Realized PnL for 24h/7d/30d. |
| `/market` | View volatility and price moves for BTC & ETH. |
| `/price <SYMBOL>` | Check the current price of a specific token. |
| `/watch <SYMBOL>` | Add a token to your personal watchlist. |
| `/unwatch <SYMBOL>` | Remove a token from your watchlist. |
| `/watchlist` | Show your current watchlist. |
| `/lang` | Switch language (English/Russian). |
| `/help` | Show the help message. |

---

## ⚙️ Configuration (.env)

You can fine-tune the bot's behavior in `.env`:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PROXIMITY_THRESHOLD` | `0.005` (0.5%) | Legacy alert threshold. |
| `BUY_PROXIMITY_THRESHOLD` | `0.003` (0.3%) | Alert when price is within 0.3% of buy order. |
| `SELL_PROXIMITY_THRESHOLD` | `0.007` (0.7%) | Alert when price is within 0.7% of sell order. |
| `PROXIMITY_USD_THRESHOLD` | `5.0` | Also alert if USD distance is < $5.00. |
| `ALERT_COOLDOWN` | `1800` (30m) | Cooldown for proximity alerts in seconds. |

---

## 📝 Notes on PnL Calculation

*   **uPnL (Unrealized):** Calculated based on your current balance and the `Avg Entry` price provided by the Hyperliquid API (or inferred).
*   **Realized PnL:** The bot calculates this by recording `fills` (trades) while it is running.
    *   *Note:* If the bot is offline during a trade, that trade might not be recorded, potentially affecting the accuracy of the Realized PnL history.

---

## 📄 License

MIT License.
