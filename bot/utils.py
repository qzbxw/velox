from bot.config import HLP_VAULT_ADDR

def _vault_display_name(vault_address: str) -> str:
    v = str(vault_address or "").lower()
    if not v:
        return "Vault"
    if HLP_VAULT_ADDR[2:] in v:
        return "HLP"
    return f"Vault {v[:6]}"
