import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import pandas as pd
from datetime import datetime

def generate_pnl_chart(history: list, wallet_address: str) -> io.BytesIO:
    """
    Generates a PnL (Equity) chart from history data.
    history: list of [timestamp_ms, equity_value]
    """
    if not history:
        return None

    # Sort by time
    history.sort(key=lambda x: x[0])
    
    # Convert to DataFrame
    df = pd.DataFrame(history, columns=["ts", "equity"])
    df["equity"] = pd.to_numeric(df["equity"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms")
    
    # Plot
    fig, ax = plt.subplots(figsize=(10, 5))
    
    ax.plot(df["date"], df["equity"], color="#00ff00", linewidth=2)
    ax.set_title(f"Equity Curve: {wallet_address[:6]}...{wallet_address[-4:]}", color="white")
    ax.set_facecolor("#1e1e1e")
    fig.patch.set_facecolor("#1e1e1e")
    
    # Formatting
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.grid(True, color="#333333", linestyle="--", alpha=0.5)
    
    # Remove spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color('white')
    ax.spines['left'].set_color('white')

    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    
    return buf

def generate_pnl_card(data: dict) -> io.BytesIO:
    """
    Generates a stylized PnL Card image.
    data: {
        symbol: str,
        side: str (Long/Short),
        leverage: float,
        entry: float,
        mark: float,
        roi: float,
        pnl: float
    }
    """
    symbol = data.get("symbol", "UNKNOWN")
    side = data.get("side", "LONG")
    lev = data.get("leverage", 1)
    entry = data.get("entry", 0)
    mark = data.get("mark", 0)
    roi = data.get("roi", 0)
    pnl = data.get("pnl", 0)
    
    # Colors
    bg_color = "#121212"
    text_color = "#ffffff"
    green = "#00ff9d"
    red = "#ff4d4d"
    accent = green if roi >= 0 else red
    
    # Setup Figure
    fig = plt.figure(figsize=(8, 4))
    fig.patch.set_facecolor(bg_color)
    
    # Add Text
    # 1. ROI (Huge)
    roi_str = f"{roi:+.2f}%"
    plt.text(0.5, 0.7, roi_str, color=accent, fontsize=40, ha='center', va='center', weight='bold')
    
    # 2. PnL Value
    pnl_str = f"${pnl:+.2f}"
    plt.text(0.5, 0.55, pnl_str, color=accent, fontsize=20, ha='center', va='center')
    
    # 3. Symbol & Side
    header = f"{symbol} {side} {lev}x"
    plt.text(0.05, 0.9, header, color=text_color, fontsize=16, ha='left', va='center', weight='bold')
    
    # 4. Prices
    prices = f"Entry: ${entry:.4f}  →  Mark: ${mark:.4f}"
    plt.text(0.5, 0.3, prices, color="#aaaaaa", fontsize=12, ha='center', va='center')
    
    # 5. Footer
    plt.text(0.5, 0.1, "Velox Terminal", color="#666666", fontsize=10, ha='center', va='center', style='italic')
    
    plt.axis('off')
    
    # Save
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=bg_color, dpi=100)
    buf.seek(0)
    plt.close(fig)
    return buf

def generate_flex_pnl_card(pnl_val: float, pnl_pct: float, period_label: str, is_positive: bool, wallet_label: str = "Net Worth") -> io.BytesIO:
    """
    Generates a stylized PnL Flex Card image for a specific period.
    pnl_val: The raw USD PnL value (e.g. 1250.50)
    pnl_pct: The percentage PnL (e.g. 15.4)
    period_label: "Day", "Week", "Month", "All-Time"
    is_positive: True if profit, False if loss
    """
    
    # Colors
    bg_color = "#161a1e" # Darker sleek bg
    card_bg = "#1e2329"  # Binance-ish card color
    text_color = "#eaeaea"
    green = "#0ecb81"
    red = "#f6465d"
    accent = green if is_positive else red
    
    # Setup Figure
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # Set explicit limits to ensure coordinates 0-1 work correctly
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    
    # 1. Header Row
    # VELOX Logo Text
    ax.text(0.08, 0.88, "VELOX", color="#fcd535", fontsize=24, ha='left', va='center', weight='heavy', style='italic')
    
    # Period Label (e.g. "Monthly PnL")
    ax.text(0.92, 0.88, f"{period_label} PnL", color="#848e9c", fontsize=18, ha='right', va='center', weight='bold')
    
    # 2. Main Content
    # Percentage (Huge)
    sign = "+" if pnl_pct >= 0 else ""
    pct_str = f"{sign}{pnl_pct:.2f}%"
    ax.text(0.5, 0.60, pct_str, color=accent, fontsize=64, ha='center', va='center', weight='bold')
    
    # Value (Medium)
    sign_val = "+" if pnl_val >= 0 else "-"
    val_str = f"{sign_val}${abs(pnl_val):,.2f}"
    ax.text(0.5, 0.42, val_str, color=text_color, fontsize=36, ha='center', va='center')
    
    # 3. Decorative Elements
    # Draw a thin line
    ax.plot([0.08, 0.92], [0.28, 0.28], color="#2b3139", linewidth=2)
    
    # 4. Footer Row
    # Wallet / User
    ax.text(0.08, 0.15, wallet_label, color="#848e9c", fontsize=14, ha='left', va='center')
    
    # Bot Link
    ax.text(0.92, 0.15, "t.me/veloxhlbot", color="#848e9c", fontsize=14, ha='right', va='center', style='italic')
    
    ax.axis('off')
    
    # Save
    buf = io.BytesIO()
    # Removed bbox_inches='tight' to keep exact figsize dimensions
    plt.savefig(buf, format='png', facecolor=bg_color, dpi=120)
    buf.seek(0)
    plt.close(fig)
    return buf

def calculate_trade_stats(fills: list) -> dict:
    """
    Calculates statistics from raw fills.
    Returns dict with win_rate, profit_factor, total_pnl, etc.
    """
    if not fills:
        return {}

    # Simplified logic: group fills by closedPnl
    # Note: userFills returns all fills. We only care about those with closedPnl != 0 (closing trades)
    
    closing_trades = [f for f in fills if float(f.get("closedPnl", 0) or 0) != 0]
    
    if not closing_trades:
        return {}
        
    total_trades = len(closing_trades)
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    
    for trade in closing_trades:
        pnl = float(trade.get("closedPnl", 0))
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        else:
            losses += 1
            gross_loss += abs(pnl)
            
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    
    pf = 0.0
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = 999.0 # Infinite
        
    net_pnl = gross_profit - gross_loss
    
    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "profit_factor": pf,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": net_pnl
    }

def format_funding_heatmap(assets_ctx: list, universe: list) -> str:
    """
    Generates a text-based Heatmap of funding rates.
    """
    # Create list of (Symbol, APR)
    data = []
    
    for idx, ctx in enumerate(assets_ctx):
        if idx >= len(universe): break
        
        name = universe[idx]["name"]
        funding = float(ctx.get("funding", 0))
        apr = funding * 24 * 365 * 100
        data.append((name, apr))
        
    # Sort by APR descending
    data.sort(key=lambda x: x[1], reverse=True)
    
    # Top 5 Highest
    top = data[:5]
    # Top 5 Lowest (Negative)
    bottom = data[-5:]
    
    lines = ["🔥 <b>Highest Funding (APR)</b>"]
    for sym, apr in top:
        lines.append(f"  • {sym}: <b>{apr:+.1f}%</b>")
        
    lines.append("\n❄️ <b>Lowest Funding (APR)</b>")
    for sym, apr in bottom:
        lines.append(f"  • {sym}: <b>{apr:+.1f}%</b>")
        
    return "\n".join(lines)

def generate_market_overview_image(assets_ctx: list, universe: list, sort_by: str = "vol") -> io.BytesIO:
    """
    Generates a rich image summary of the market.
    sort_by: 'vol' (Volume), 'change' (24h Change), 'funding' (Funding Rate), 'oi' (Open Interest)
    """
    import pandas as pd
    
    # Prepare Data
    data = []
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        
        name = u["name"]
        price = float(ctx.get("markPx", 0))
        prev_day = float(ctx.get("prevDayPx", 0) or price) # Fallback to price if 0
        
        funding = float(ctx.get("funding", 0)) * 24 * 365 * 100 # APR
        vol = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0)) * price
        
        change_24h = 0.0
        if prev_day > 0:
            change_24h = ((price - prev_day) / prev_day) * 100
        
        data.append({
            "Symbol": name,
            "Price": price,
            "Funding%": funding,
            "Volume": vol,
            "OI": oi,
            "Change%": change_24h
        })
        
    df = pd.DataFrame(data)
    
    if df.empty: return None
    
    # Sort
    if sort_by == "funding":
        df = df.sort_values("Funding%", ascending=False)
    elif sort_by == "oi":
        df = df.sort_values("OI", ascending=False)
    elif sort_by == "change":
        df = df.sort_values("Change%", ascending=False)
    else: # vol
        df = df.sort_values("Volume", ascending=False)
        
    top_n = df.head(15).copy()
    
    # Formatting for display
    # We will create a Table plot
    
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.patch.set_facecolor('#121212')
    ax.set_facecolor('#121212')
    
    # Hide axes
    ax.axis('off')
    ax.axis('tight')
    
    # Columns text
    cell_text = []
    colors = []
    
    for index, row in top_n.iterrows():
        # Colorize Funding
        fund_color = "#ffffff"
        if row["Funding%"] > 50: fund_color = "#00ff00"
        elif row["Funding%"] < -20: fund_color = "#ff0000"
        
        # Colorize Change
        ch_color = "#ffffff"
        if row["Change%"] > 0: ch_color = "#00ff00"
        elif row["Change%"] < 0: ch_color = "#ff0000"
        
        # Format rows
        r = [
            row["Symbol"],
            f"${pretty_float(row['Price'], 4)}",
            f"{row['Change%']:+.2f}%",
            f"{row['Funding%']:+.1f}%",
            f"${row['Volume']/1e6:.1f}M",
            f"${row['OI']/1e6:.1f}M"
        ]
        cell_text.append(r)
        # Colors corresponding to columns
        # Sym, Price, Change, Fund, Vol, OI
        colors.append([ "#ffffff", "#ffffff", ch_color, fund_color, "#aaaaaa", "#aaaaaa" ])

    # Create Table
    cols = ["Token", "Price", "24h Chg", "Funding (APR)", "24h Vol", "Open Interest"]
    table = ax.table(
        cellText=cell_text,
        colLabels=cols,
        cellColours=[["#1e1e1e"]*len(cols) for _ in range(len(cell_text))], # bg color
        cellLoc='center',
        loc='center',
        edges='B' # horizontal lines only
    )
    
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 2)
    
    # Custom styling
    for (row, col), cell in table.get_celld().items():
        cell.set_text_props(color='white')
        cell.set_facecolor("#1e1e1e")
        cell.set_edgecolor("#333333")
        
        if row == 0: # Header
            cell.set_text_props(weight='bold', color='#eda611')
            cell.set_facecolor("#2b2b2b")
        elif row > 0:
            # Apply content color overrides
            c_color = colors[row-1][col]
            cell.set_text_props(color=c_color)

    plt.title(f"Market Overview (Top 15 by {sort_by.upper()})", color='white', pad=20, size=16)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#121212', dpi=100)
    buf.seek(0)
    plt.close(fig)
    return buf

def pretty_float(x: float, max_decimals: int = 6) -> str:
    """Duplicate helper for analytics standalone usage."""
    try:
        v = float(x)
    except: return "0"
    s = f"{v:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s
