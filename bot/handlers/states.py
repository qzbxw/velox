from aiogram.fsm.state import State, StatesGroup

class CalcStates(StatesGroup):
    mode = State() # spot / perp
    side = State() # long / short
    balance = State()
    entry = State()
    sl = State()
    tp = State()
    risk = State()

class AlertStates(StatesGroup):
    waiting_for_symbol = State()
    waiting_for_target = State()

class SettingsStates(StatesGroup):
    waiting_for_prox = State()
    waiting_for_vol = State()
    waiting_for_whale = State()
    waiting_for_ov_time = State()
    waiting_for_ov_prompt = State()
    waiting_for_digest_time = State()

class MarketAlertStates(StatesGroup):
    waiting_for_time = State()
    waiting_for_type = State()

class AIStates(StatesGroup):
    waiting_for_chat = State()
    waiting_for_prompt_override = State()
