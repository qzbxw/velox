import os
import json

# Path to locales folder (current directory)
_LOCALES_DIR = os.path.dirname(__file__)

_translations = {}

# Load all JSON files from the folder
for file_name in os.listdir(_LOCALES_DIR):
    if file_name.endswith(".json"):
        lang = file_name[:-5].lower()
        file_path = os.path.join(_LOCALES_DIR, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                _translations[lang] = json.load(f)
        except Exception:
            # Silently skip if file is corrupted
            continue

# Backward compatibility for global EN/RU
EN = _translations.get("en", {})
RU = _translations.get("ru", {})

def _t(lang: str, key: str, **kwargs) -> str:
    """
    Multilingual support for Velox Bot.
    """
    l = (lang or "ru").lower()
    
    # Try current lang, then RU, then EN, then any available, then return key
    table = _translations.get(l)
    if not table:
        table = _translations.get("ru", _translations.get("en", next(iter(_translations.values())) if _translations else {}))
    
    text = table.get(key, key)
    
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
            
    return text
