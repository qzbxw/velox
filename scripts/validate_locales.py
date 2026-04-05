import json
import os

def validate():
    en_path = "bot/locales/en.json"
    ru_path = "bot/locales/ru.json"
    
    if not os.path.exists(en_path) or not os.path.exists(ru_path):
        print("Locale files missing!")
        return

    with open(en_path, "r", encoding="utf-8") as f:
        en = json.load(f)
    with open(ru_path, "r", encoding="utf-8") as f:
        ru = json.load(f)

    en_keys = set(en.keys())
    ru_keys = set(ru.keys())

    only_en = en_keys - ru_keys
    only_ru = ru_keys - en_keys

    if not only_en and not only_ru:
        print("✅ Locales are synced!")
    else:
        if only_en:
            print(f"❌ Missing in RU: {only_en}")
        if only_ru:
            print(f"❌ Missing in EN: {only_ru}")

if __name__ == "__main__":
    validate()
