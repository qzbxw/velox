from bot.config import HLP_VAULT_ADDR

def _vault_display_name(vault_address: str) -> str:
    v = str(vault_address or "").lower()
    if not v:
        return "Vault"
    if HLP_VAULT_ADDR[2:] in v:
        return "HLP"
    return f"Vault {v[:6]}"

def format_money(val: float, lang: str = "en", compact: bool = False) -> str:
    """Format money with sign and currency symbol."""
    if compact and abs(val) >= 1_000_000:
        return f"${val/1_000_000:.2f}M"
    if compact and abs(val) >= 1_000:
        return f"${val/1_000:.1f}K"
    sign = "-" if val < 0 else ""
    return f"{sign}${abs(val):,.2f}"

def pretty_float(x: float, max_decimals: int = 6) -> str:
    """Human-friendly float: trim trailing zeros while keeping up to max_decimals."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "0"
    if v == 0:
        return "0"
    
    # Using format specifier to avoid scientific notation for small floats
    s = f"{v:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s
