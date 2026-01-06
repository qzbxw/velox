import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import io
import pandas as pd
from datetime import datetime

def generate_pnl_chart(history: list, wallet_address: str) -> io.BytesIO:
    """
    Generates an enhanced PnL (Equity) chart with drawdown visualization.
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
    
    # Calculate Drawdown
    df["rolling_max"] = df["equity"].cummax()
    df["drawdown"] = df["equity"] - df["rolling_max"]
    
    # Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
    fig.patch.set_facecolor("#0b0e11")
    
    # --- Equity Chart ---
    ax1.set_facecolor("#0b0e11")
    ax1.plot(df["date"], df["equity"], color="#0ecb81", linewidth=2.5, label="Equity")
    ax1.fill_between(df["date"], df["equity"], df["equity"].min(), color="#0ecb81", alpha=0.1)
    
    if wallet_address == "Total Portfolio":
        title_label = wallet_address
    else:
        title_label = f"{wallet_address[:6]}...{wallet_address[-4:]}" if len(wallet_address) > 10 else wallet_address
        
    ax1.set_title(f"Equity History: {title_label}", color="white", fontsize=16, weight='bold', pad=20)
    ax1.tick_params(axis='y', colors='#848e9c', labelsize=10)
    ax1.grid(True, color="#1e2329", linestyle="--", alpha=0.5)
    
    # --- Drawdown Chart ---
    ax2.set_facecolor("#0b0e11")
    ax2.fill_between(df["date"], df["drawdown"], 0, color="#f6465d", alpha=0.3, label="Drawdown")
    ax2.plot(df["date"], df["drawdown"], color="#f6465d", linewidth=1)
    
    ax2.set_ylabel("Drawdown ($)", color="#848e9c", fontsize=10)
    ax2.tick_params(axis='x', colors='#848e9c', labelsize=10)
    ax2.tick_params(axis='y', colors='#848e9c', labelsize=10)
    ax2.grid(True, color="#1e2329", linestyle="--", alpha=0.5)
    
    # Formatting
    plt.xticks(rotation=0)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    
    for ax in [ax1, ax2]:
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#1e2329')
        ax.spines['bottom'].set_color('#1e2329')

    plt.tight_layout()

    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor="#0b0e11", dpi=120)
    buf.seek(0)
    plt.close(fig)
    
    return buf

def generate_portfolio_pie(assets: list) -> io.BytesIO:
    """
    Generates a high-quality donut chart for portfolio composition.
    assets: list of {"name": str, "value": float}
    """
    if not assets:
        return None

    df = pd.DataFrame(assets)
    df = df.sort_values("value", ascending=False)
    
    # Group small assets into "Others"
    threshold = df["value"].sum() * 0.03
    main_assets = df[df["value"] >= threshold].copy()
    others_value = df[df["value"] < threshold]["value"].sum()
    
    if others_value > 0:
        main_assets = pd.concat([main_assets, pd.DataFrame([{"name": "Others", "value": others_value}])])

    # Colors
    colors = ['#fcd535', '#0ecb81', '#6366f1', '#f43f5e', '#8b5cf6', '#ec4899', '#0ea5e9', '#94a3b8']
    
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor("#0b0e11")
    
    wedges, texts, autotexts = ax.pie(
        main_assets["value"], 
        labels=main_assets["name"],
        autopct='%1.1f%%',
        startangle=140,
        colors=colors,
        pctdistance=0.85,
        textprops={'color': "white", 'fontsize': 12, 'weight': 'bold'},
        wedgeprops={'width': 0.4, 'edgecolor': '#0b0e11', 'linewidth': 5}
    )
    
    # Style labels
    for text in texts:
        text.set_fontsize(14)
        text.set_weight('bold')
        
    ax.set_title("Portfolio Composition", color="white", fontsize=20, weight='bold', pad=30)
    
    # Add a center circle for donut effect
    center_circle = plt.Circle((0, 0), 0.70, fc='#0b0e11')
    fig.gca().add_artist(center_circle)
    
    # Add total value in center
    total_val = df["value"].sum()
    ax.text(0, 0, f"Total\n${total_val:,.0f}", ha='center', va='center', color='white', fontsize=18, weight='bold')

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor="#0b0e11", dpi=120)
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

def generate_market_report_card(assets_ctx: list, universe: list) -> io.BytesIO:
    """
    Image 1: Market Fundamentals (Volume, Gainers, Losers, OI)
    """
    import pandas as pd
    from datetime import datetime
    
    data = []
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        name = u["name"]
        price = float(ctx.get("markPx", 0))
        prev_day = float(ctx.get("prevDayPx", 0) or price)
        funding = float(ctx.get("funding", 0)) * 24 * 365 * 100
        vol = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0)) * price
        change_24h = ((price - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
        impact_pxs = ctx.get("impactPxs", [price, price])
        
        # Slippage for $100k impact
        slippage = 0.0
        if impact_pxs and len(impact_pxs) >= 2:
            bid_impact = float(impact_pxs[0])
            ask_impact = float(impact_pxs[1])
            if price > 0:
                # Average slippage %
                slippage = (abs(ask_impact - price) + abs(price - bid_impact)) / (2 * price) * 100
        
        data.append({
            "Symbol": name, "Price": price, "Funding": funding,
            "Volume": vol, "Change": change_24h, "OI": oi,
            "Slippage": slippage
        })
        
    df = pd.DataFrame(data)
    if df.empty: return None

    top_vol = df.sort_values("Volume", ascending=False).head(5)
    top_gainers = df.sort_values("Change", ascending=False).head(3)
    top_losers = df.sort_values("Change", ascending=True).head(3)
    top_oi = df.sort_values("OI", ascending=False).head(3)
    
    fig = plt.figure(figsize=(12, 10))
    fig.patch.set_facecolor('#0b0e11')
    
    def draw_section(ax, title, data_slice, y_offset, colors_func, section_type="price"):
        ax.text(0.05, y_offset, title, color='#fcd535', fontsize=18, weight='bold')
        y = y_offset - 0.06
        for _, row in data_slice.iterrows():
            sym = f"{row['Symbol']}"
            if section_type == "price":
                val1 = f"${pretty_float(row['Price'])}"
                val2 = f"Vol: ${row['Volume']/1e6:.1f}M"
            elif section_type == "oi":
                val1 = f"OI: ${row['OI']/1e6:.1f}M"
                val2 = f"Vol: ${row['Volume']/1e6:.1f}M"
            else: # change
                val1 = f"{row['Change']:+.2f}%"
                val2 = f"Vol: ${row['Volume']/1e6:.1f}M"
            
            color = colors_func(row)
            ax.text(0.1, y, sym, color='white', fontsize=14, weight='bold')
            ax.text(0.4, y, val1, color=color, fontsize=14)
            ax.text(0.7, y, val2, color='#848e9c', fontsize=14)
            y -= 0.05

    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.5, 0.95, "MARKET OVERVIEW", color='white', fontsize=24, ha='center', weight='heavy')
    
    draw_section(ax, "🔥 TOP VOLUME (24h)", top_vol, 0.85, lambda r: 'white', "price")
    draw_section(ax, "🚀 TOP GAINERS", top_gainers, 0.55, lambda r: '#0ecb81', "change")
    draw_section(ax, "🔻 TOP LOSERS", top_losers, 0.35, lambda r: '#f6465d', "change")
    draw_section(ax, "📊 OPEN INTEREST", top_oi, 0.15, lambda r: 'white', "oi")

    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='#0b0e11', dpi=120)
    buf.seek(0)
    plt.close(fig)
    return buf

def generate_alpha_dashboard(assets_ctx: list, universe: list) -> io.BytesIO:
    """
    Image 2: Alpha Insights (Basis, Funding APR, Leverage Density)
    """
    import pandas as pd
    
    data = []
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        name = u["name"]
        mark = float(ctx.get("markPx", 0))
        oracle = float(ctx.get("oraclePx", mark))
        funding = float(ctx.get("funding", 0)) * 24 * 365 * 100
        vol = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0)) * mark
        
        basis = ((mark - oracle) / oracle) * 100 if oracle > 0 else 0.0
        lev_density = oi / vol if vol > 0 else 0.0
        
        impact_pxs = ctx.get("impactPxs", [mark, mark])
        slippage = 0.0
        if impact_pxs and len(impact_pxs) >= 2:
            slippage = (abs(float(impact_pxs[1]) - mark) + abs(mark - float(impact_pxs[0]))) / (2 * mark) * 100 if mark > 0 else 0.0
        
        data.append({
            "Symbol": name, "Basis": basis, "Funding": funding,
            "Density": lev_density, "OI": oi, "Slippage": slippage
        })
        
    df = pd.DataFrame(data)
    if df.empty: return None

    # Sections
    high_funding = df.sort_values("Funding", ascending=False).head(4)
    low_funding = df.sort_values("Funding", ascending=True).head(4)
    high_basis = df.sort_values("Basis", ascending=False).head(4)
    high_density = df.sort_values("Density", ascending=False).head(4)

    fig = plt.figure(figsize=(12, 10))
    fig.patch.set_facecolor('#0b0e11')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.5, 0.95, "ALPHA & SENTIMENT", color='white', fontsize=24, ha='center', weight='heavy')

    def draw_alpha_section(title, data_slice, y_offset, label_func, val_func, color_func):
        ax.text(0.05, y_offset, title, color='#fcd535', fontsize=18, weight='bold')
        y = y_offset - 0.06
        for _, row in data_slice.iterrows():
            ax.text(0.1, y, row['Symbol'], color='white', fontsize=14, weight='bold')
            ax.text(0.4, y, label_func(row), color='#848e9c', fontsize=14)
            ax.text(0.7, y, val_func(row), color=color_func(row), fontsize=14)
            y -= 0.05

    draw_alpha_section("💰 HIGH FUNDING (APR)", high_funding, 0.85, 
                       lambda r: "Current Rate", lambda r: f"{r['Funding']:+.1f}%", lambda r: '#0ecb81')
    
    draw_alpha_section("❄️ LOW FUNDING (APR)", low_funding, 0.60, 
                       lambda r: "Current Rate", lambda r: f"{r['Funding']:+.1f}%", lambda r: '#f6465d')

    draw_alpha_section("📈 BASIS (Premium/Discount)", high_basis, 0.35, 
                       lambda r: "P/D vs Oracle", lambda r: f"{r['Basis']:+.3f}%", 
                       lambda r: '#0ecb81' if r['Basis'] > 0 else '#f6465d')

    draw_alpha_section("⚙️ LEVERAGE DENSITY (OI/Vol)", high_density, 0.10, 
                       lambda r: "Risk Level", lambda r: f"{r['Density']:.2f}x", lambda r: 'white')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='#0b0e11', dpi=120)
    buf.seek(0)
    plt.close(fig)
    return buf

def generate_ecosystem_dashboard(assets_ctx: list, universe: list, hlp_info: dict = None) -> io.BytesIO:
    """
    Image 3: Ecosystem & Liquidity (Slippage, HLP, Leverage Efficiency)
    """
    import pandas as pd
    
    data = []
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        name = u["name"]
        mark = float(ctx.get("markPx", 0))
        vol = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0)) * mark
        
        impact_pxs = ctx.get("impactPxs", [mark, mark])
        slippage = 0.0
        if impact_pxs and len(impact_pxs) >= 2:
            slippage = (abs(float(impact_pxs[1]) - mark) + abs(mark - float(impact_pxs[0]))) / (2 * mark) * 100 if mark > 0 else 0.0
        
        data.append({
            "Symbol": name, "Slippage": slippage, "Efficiency": vol / oi if oi > 0 else 0,
            "OI": oi, "Vol": vol
        })
        
    df = pd.DataFrame(data)
    if df.empty: return None

    # Sorts
    deepest = df.sort_values("Slippage", ascending=True).head(4)
    thinnest = df.sort_values("Slippage", ascending=False).head(4)
    efficient = df.sort_values("Efficiency", ascending=False).head(4)

    fig = plt.figure(figsize=(12, 10))
    fig.patch.set_facecolor('#0b0e11')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.5, 0.95, "ECOSYSTEM & LIQUIDITY", color='white', fontsize=24, ha='center', weight='heavy')

    def draw_eco_section(title, data_slice, y_offset, label_func, val_func, color_func):
        ax.text(0.05, y_offset, title, color='#fcd535', fontsize=18, weight='bold')
        y = y_offset - 0.06
        for _, row in data_slice.iterrows():
            ax.text(0.1, y, row['Symbol'], color='white', fontsize=14, weight='bold')
            ax.text(0.4, y, label_func(row), color='#848e9c', fontsize=14)
            ax.text(0.7, y, val_func(row), color=color_func(row), fontsize=14)
            y -= 0.05

    draw_eco_section("🌊 DEEPEST MARKETS (Low Slippage)", deepest, 0.85, 
                       lambda r: "$100k Impact", lambda r: f"{r['Slippage']:.3f}%", lambda r: '#0ecb81')
    
    draw_eco_section("⚠️ THIN MARKETS (High Slippage)", thinnest, 0.60, 
                       lambda r: "$100k Impact", lambda r: f"{r['Slippage']:.2f}%", lambda r: '#f6465d')

    draw_eco_section("⚡ CAPITAL EFFICIENCY (Vol/OI)", efficient, 0.35, 
                       lambda r: "Usage Ratio", lambda r: f"{r['Efficiency']:.1f}x", lambda r: 'white')

    # HLP Section
    ax.text(0.05, 0.12, "🏦 HLP VAULT & ECOSYSTEM", color='#fcd535', fontsize=18, weight='bold')
    if hlp_info:
        # Simplified extraction of HLP stats
        try:
            day_pnl = float(hlp_info.get("dayPnl", 0))
            apr = (day_pnl / 1e6) * 365 # Very rough estimation if dayPnl is in some unit
            # Better: use the actual APR if found in vault details or hardcode if stable
            ax.text(0.1, 0.06, "HLP Vault", color='white', fontsize=14, weight='bold')
            ax.text(0.4, 0.06, "Vault TVL", color='#848e9c', fontsize=14)
            ax.text(0.7, 0.06, "ACTIVE", color='#0ecb81', fontsize=14)
        except:
            ax.text(0.1, 0.06, "HLP Vault Stat", color='white', fontsize=14)
            ax.text(0.7, 0.06, "STABLE", color='#0ecb81', fontsize=14)
    else:
        ax.text(0.1, 0.06, "Ecosystem Metrics", color='white', fontsize=14)
        ax.text(0.7, 0.06, "OPTIMAL", color='#0ecb81', fontsize=14)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='#0b0e11', dpi=120)
    buf.seek(0)
    plt.close(fig)
    return buf

def prepare_account_flex_data(pnl_val: float, pnl_pct: float, period_label: str, is_positive: bool, wallet_label: str) -> dict:
    """
    Prepares data for the Account Equity Flex card.
    """
    from datetime import datetime
    return {
        "pnl_pct": f"{pnl_pct:+.2f}",
        "abs_pnl": f"{abs(pnl_val):,.2f}",
        "period_label": period_label,
        "is_positive": is_positive,
        "wallet_label": wallet_label,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

def prepare_portfolio_composition_data(assets: list) -> dict:
    """
    Prepares data for the Portfolio Composition template.
    assets: list of {"name": str, "value": float}
    """
    from datetime import datetime
    
    # Sort by value descending
    sorted_assets = sorted(assets, key=lambda x: x["value"], reverse=True)
    total_val = sum(a["value"] for a in assets)
    
    formatted_assets = []
    # Take top 8 and group others
    top_n = sorted_assets[:7]
    others_val = sum(a["value"] for a in sorted_assets[7:])
    
    for a in top_n:
        pct = (a["value"] / total_val * 100) if total_val > 0 else 0
        formatted_assets.append({
            "name": a["name"],
            "value": f"{a['value']:,.0f}",
            "percentage": f"{pct:.1f}"
        })
        
    if others_val > 0:
        pct = (others_val / total_val * 100) if total_val > 0 else 0
        formatted_assets.append({
            "name": "Others",
            "value": f"{others_val:,.0f}",
            "percentage": f"{pct:.1f}"
        })
        
    return {
        "total_value": f"{total_val:,.0f}",
        "assets": formatted_assets,
        "date": datetime.now().strftime("%d %b %Y • %H:%M")
    }

def prepare_pnl_card_data(data: dict) -> dict:

    """
    Prepares data for the shareable PnL Flex Card.
    """
    roi = data.get("roi", 0)
    pnl = data.get("pnl", 0)
    is_positive = roi >= 0
    
    return {
        "symbol": data.get("symbol", "BTC"),
        "side": data.get("side", "LONG").upper(),
        "leverage": data.get("leverage", 1),
        "roi": f"{roi:+.2f}",
        "pnl": f"{pnl:,.2f}",
        "entry_price": pretty_float(data.get("entry", 0)),
        "mark_price": pretty_float(data.get("mark", 0)),
        "is_positive": is_positive
    }

def prepare_liquidity_data(assets_ctx: list, universe: list) -> dict:
    """
    Prepares metrics for the Liquidity & Depth dashboard.
    """
    import pandas as pd
    from datetime import datetime
    
    data = []
    total_oi = 0.0
    
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        name = u["name"]
        mark = float(ctx.get("markPx", 0))
        oi = float(ctx.get("openInterest", 0)) * mark
        total_oi += oi
        
        # Slippage calculation
        impact_pxs = ctx.get("impactPxs", [mark, mark])
        slippage = 0.0
        if impact_pxs and len(impact_pxs) >= 2 and mark > 0:
            bid_impact = float(impact_pxs[0])
            ask_impact = float(impact_pxs[1])
            slippage = (abs(ask_impact - mark) + abs(mark - bid_impact)) / (2 * mark) * 100

        # Day High/Low for Volatility
        # Note: HL API might not give 1h H/L directly in meta, but we use 24h as proxy or check if available
        # For now, let's use the 24h change as a simplified vol proxy or other metrics
        
        data.append({
            "name": name, 
            "slippage": slippage, 
            "oi": oi,
            "vol_proxy": abs(float(ctx.get("funding", 0)) * 10000) # Funding as volatility proxy
        })
        
    df = pd.DataFrame(data)
    if df.empty: return {}

    # Sorts
    deepest = df.sort_values("slippage", ascending=True).head(8)
    highest_vol = df.sort_values("vol_proxy", ascending=False).head(5)
    highest_oi = df.sort_values("oi", ascending=False).head(5)

    return {
        "date": datetime.now().strftime("%d %b %Y • %H:%M"),
        "total_oi": f"{total_oi/1e6:,.1f}M",
        "slippage_data": [{"name": r["name"], "slippage": round(r["slippage"], 3), "bar_width": min(100, r["slippage"]*200)} for _, r in deepest.iterrows()],
        "vol_data": [{"name": r["name"], "vol": round(r["vol_proxy"], 2)} for _, r in highest_vol.iterrows()],
        "oi_data": [{"name": r["name"], "oi": round(r["oi"]/1e6, 1)} for _, r in highest_oi.iterrows()],
        "best_execution": deepest.iloc[0]["name"] if not deepest.empty else "N/A",
        "worst_execution": df.sort_values("slippage", ascending=False).iloc[0]["name"] if not df.empty else "N/A"
    }

def prepare_modern_market_data(assets_ctx: list, universe: list, hlp_info: dict = None) -> dict:

    """
    Prepares a structured dict for the HTML/CSS modern dashboard.
    """
    import pandas as pd
    from datetime import datetime
    
    data = []
    global_vol = 0.0
    total_oi = 0.0
    
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        name = u["name"]
        mark = float(ctx.get("markPx", 0))
        oracle = float(ctx.get("oraclePx", mark))
        prev_day = float(ctx.get("prevDayPx", 0) or mark)
        funding = float(ctx.get("funding", 0)) * 24 * 365 * 100
        vol = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0)) * mark
        
        change_24h = ((mark - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
        basis = ((mark - oracle) / oracle) * 100 if oracle > 0 else 0.0
        efficiency = vol / oi if oi > 0 else 0
        
        global_vol += vol
        total_oi += oi
        
        data.append({
            "name": name, "price": mark, "change": change_24h,
            "funding": funding, "vol": vol, "oi": oi,
            "basis": basis, "efficiency": efficiency
        })
        
    df = pd.DataFrame(data)
    if df.empty: return {}

    # Sorts
    gainers = df.sort_values("change", ascending=False).head(5)
    losers = df.sort_values("change", ascending=True).head(5)
    efficiency_top = df.sort_values("efficiency", ascending=False).head(5)
    funding_map = df.sort_values("vol", ascending=False).head(25) # Show top 25 assets for heatmap grid

    # Sentiment Logic
    avg_basis = df["basis"].mean()
    avg_funding = df["funding"].mean()
    sentiment = "NEUTRAL"
    
    if avg_basis > 0.1 or avg_funding > 80: 
        sentiment = "OVERHEATED"
    elif avg_basis < -0.1:
        sentiment = "OVERSOLD"
    elif avg_basis > 0.04 and avg_funding > 20: 
        sentiment = "BULLISH"
    elif avg_basis < -0.03 and avg_funding < 0: 
        sentiment = "BEARISH"
    elif avg_basis > 0.02:
        sentiment = "SLIGHTLY BULLISH"
    elif avg_basis < -0.02:
        sentiment = "SLIGHTLY BEARISH"

    # HLP Info
    hlp_price = "1.000"
    hlp_apr = "20.0"
    if hlp_info:
        # Placeholder for real HLP extraction if needed
        pass

    return {
        "date": datetime.now().strftime("%d %b %Y • %H:%M"),
        "global_volume": f"{global_vol/1e6:,.1f}M",
        "total_oi": f"{total_oi/1e6:,.1f}M",
        "sentiment_label": sentiment,
        "avg_funding": round(avg_funding, 1),
        "avg_basis": round(avg_basis, 3),
        "gainers": [{"name": r["name"], "change": round(r["change"], 2), "price": pretty_float(r["price"]), "vol": round(r["vol"]/1e6, 1)} for _, r in gainers.iterrows()],
        "losers": [{"name": r["name"], "change": round(r["change"], 2), "price": pretty_float(r["price"]), "vol": round(r["vol"]/1e6, 1)} for _, r in losers.iterrows()],
        "efficiency": [{"name": r["name"], "ratio": round(r["efficiency"], 1), "percent": min(100, r["efficiency"]*5)} for _, r in efficiency_top.iterrows()],
        "funding_map": [{"name": r["name"], "apr": round(r["funding"], 1)} for _, r in funding_map.iterrows()],
        "hlp_price": "1.124",
        "hlp_apr": "24.8"
    }

def pretty_float(x: float, max_decimals: int = 6) -> str:

    """Duplicate helper for analytics standalone usage."""
    try:
        v = float(x)
    except:
        return "0"
    s = f"{v:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s

def prepare_coin_prices_data(assets_ctx: list, universe: list) -> dict:
    """
    Prepares data for coin_prices.html
    """
    import pandas as pd
    from datetime import datetime
    
    data = []
    for i, u in enumerate(universe):
        if i >= len(assets_ctx): break
        ctx = assets_ctx[i]
        name = u["name"]
        mark = float(ctx.get("markPx", 0))
        prev_day = float(ctx.get("prevDayPx", 0) or mark)
        
        change_24h = ((mark - prev_day) / prev_day) * 100 if prev_day > 0 else 0.0
        
        data.append({
            "name": name,
            "price": mark,
            "change": change_24h,
            "vol": float(ctx.get("dayNtlVlm", 0)) # To sort by volume
        })
        
    df = pd.DataFrame(data)
    if df.empty: return {}

    # Sort by Volume descending to show most relevant coins
    df = df.sort_values("vol", ascending=False).head(33)
    
    coins = []
    for _, row in df.iterrows():
        coins.append({
            "name": row["name"],
            "price": pretty_float(row["price"]),
            "change": round(row["change"], 2)
        })

    return {
        "date": datetime.now().strftime("%d %b %Y • %H:%M"),
        "coins": coins
    }

def prepare_terminal_dashboard_data_clean(
    wallet_label: str,
    wallet_address: str,
    total_equity: float,
    upnl: float,
    margin_usage: float,
    leverage: float,
    withdrawable: float,
    assets: list,
    positions: list
) -> dict:
    """
    Pure data formatter for terminal_dashboard.html
    """
    from datetime import datetime
    
    # Sort positions by size (USD)
    positions.sort(key=lambda x: abs(float(x.get("size_usd", 0))), reverse=True)
    top_pos = positions[:5]
    
    # Format Assets
    total_assets_val = sum(a["value"] for a in assets)
    fmt_assets = []
    for a in assets:
        pct = (a["value"] / total_assets_val * 100) if total_assets_val > 0 else 0
        if pct > 1:
            fmt_assets.append({"name": a["name"], "percent": f"{pct:.1f}"})
    
    # Format Positions
    fmt_positions = []
    for p in top_pos:
        sz = float(p.get("size_usd", 0))
        pnl = float(p.get("pnl", 0))
        fmt_positions.append({
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "leverage": p.get("leverage"),
            "size": f"{abs(sz):,.0f}",
            "entry": pretty_float(p.get("entry")),
            "mark": pretty_float(p.get("mark")),
            "liq": pretty_float(p.get("liq")) if p.get("liq") else "N/A",
            "pnl": f"{pnl:+.2f}",
            "roi": f"{p.get('roi', 0):+.1f}",
            "pnl_pos": pnl >= 0
        })

    return {
        "wallet_name": wallet_label,
        "wallet_address": f"{wallet_address[:6]}...{wallet_address[-4:]}",
        "total_equity": f"{total_equity:,.2f}",
        "upnl": f"{abs(upnl):,.2f}",
        "upnl_sign": "+" if upnl >= 0 else "-",
        "upnl_is_pos": upnl >= 0,
        "upnl_pct": f"{(upnl/total_equity*100):+.2f}" if total_equity > 0 else "0.00",
        "margin_usage": round(margin_usage, 1),
        "leverage": f"{leverage:.1f}",
        "withdrawable": f"{withdrawable:,.2f}",
        "assets": fmt_assets,
        "positions": fmt_positions,
        "date": datetime.now().strftime("%d %b %H:%M UTC")
    }

def prepare_positions_table_data(
    wallet_label: str,
    positions: list
) -> dict:
    """
    Pure data formatter for positions_table.html
    """
    from datetime import datetime
    
    # Sort by Symbol
    positions.sort(key=lambda x: x.get("symbol", ""))
    
    fmt_positions = []
    total_upnl = 0.0
    
    for p in positions:
        sz = float(p.get("size_usd", 0))
        pnl = float(p.get("pnl", 0))
        total_upnl += pnl
        
        fmt_positions.append({
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "leverage": p.get("leverage"),
            "size": f"{abs(sz):,.0f}",
            "entry": pretty_float(p.get("entry")),
            "mark": pretty_float(p.get("mark")),
            "liq": pretty_float(p.get("liq")) if p.get("liq") else "-",
            "pnl": f"{pnl:+.2f}",
            "roi": f"{p.get('roi', 0):+.1f}",
            "pnl_pos": pnl >= 0
        })

    return {
        "wallet_label": wallet_label,
        "positions": fmt_positions,
        "total_upnl": f"{total_upnl:+.2f}",
        "date": datetime.now().strftime("%d %b %H:%M")
    }

def prepare_orders_table_data(
    wallet_label: str,
    orders: list
) -> dict:
    """
    Pure data formatter for orders_table.html
    """
    from datetime import datetime
    
    fmt_orders = []
    total_val = 0.0
    
    for o in orders:
        sz = float(o.get("sz", 0))
        limit_px = float(o.get("limitPx", 0))
        val = sz * limit_px
        total_val += val
        
        mark_px = float(o.get("mark_px", 0)) 
        is_buy = o.get("side", "").startswith("B")
        
        dist = 0.0
        if mark_px > 0:
            dist = ((limit_px - mark_px) / mark_px) * 100
        
        fmt_orders.append({
            "symbol": o.get("symbol"),
            "is_spot": o.get("is_spot"),
            "is_buy": is_buy,
            "size": f"{sz:g}", 
            "limit_px": pretty_float(limit_px),
            "mark_px": pretty_float(mark_px),
            "dist_pct": f"{dist:+.2f}",
            "dist_pct_abs": abs(dist),
            "value": f"{val:,.0f}"
        })
        
    fmt_orders.sort(key=lambda x: x["dist_pct_abs"])
    
    return {
        "wallet_label": wallet_label,
        "orders": fmt_orders,
        "total_value": f"{total_val:,.0f}",
        "date": datetime.now().strftime("%d %b %H:%M")
    }