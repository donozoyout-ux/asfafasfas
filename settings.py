import os
import json
import config

_DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(_DATA_DIR):
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        _DATA_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")

# Runtime-editable settings mapped to config attributes.
# Keys = what the panel/API uses, values = config module attribute names.
EDITABLE_FIELDS = {
    "leverage": "LEVERAGE",
    "risk_per_trade_pct": "RISK_PER_TRADE_PCT",
    "confidence_threshold": "CONFIDENCE_THRESHOLD",
    "check_interval_seconds": "CHECK_INTERVAL_SECONDS",
    "sl_multiplier": "ATR_SL_MULTIPLIER",
    "tp_multiplier": "ATR_TP_MULTIPLIER",
    "daily_target_profit_pct": "DAILY_TARGET_PROFIT_PCT",
    "max_daily_drawdown_pct": "MAX_DAILY_DRAWDOWN_PCT",
    "timeframe": "TIMEFRAME",
    "kline_limit": "KLINE_LIMIT",
}

_STORE = {}


def load():
    """Loads settings.json (if present) and applies overrides onto the config module."""
    global _STORE
    if not os.path.exists(SETTINGS_PATH):
        _STORE = {}
        return
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for key, value in data.items():
            attr = EDITABLE_FIELDS.get(key)
            if attr is not None:
                setattr(config, attr, value)
                _STORE[key] = value
    except Exception as e:
        print(f"[SETTINGS] Load failed: {e}")
        _STORE = {}


def save():
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_STORE, f, indent=2)
    except Exception as e:
        print(f"[SETTINGS] Save failed: {e}")


def update(pairs: dict) -> dict:
    """Applies validated runtime settings. Returns {applied: [...], errors: [...]}."""
    applied = {}
    errors = {}
    for key, value in pairs.items():
        attr = EDITABLE_FIELDS.get(key)
        if attr is None:
            errors[key] = "Bilinmeyen ayar"
            continue
        if not _validate(key, value):
            errors[key] = "Geçersiz değer"
            continue
        setattr(config, attr, value)
        _STORE[key] = value
        applied[key] = value
    if applied:
        save()
    return {"applied": applied, "errors": errors}


def get_all() -> dict:
    """Returns current effective settings (values actually in config)."""
    result = {}
    for key, attr in EDITABLE_FIELDS.items():
        result[key] = getattr(config, attr, None)
    return result


def _validate(key: str, value) -> bool:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    ranges = {
        "leverage": (1, 125),
        "risk_per_trade_pct": (0.001, 0.20),
        "confidence_threshold": (0, 100),
        "check_interval_seconds": (5, 3600),
        "sl_multiplier": (0.5, 5.0),
        "tp_multiplier": (1.0, 8.0),
        "daily_target_profit_pct": (0.001, 0.50),
        "max_daily_drawdown_pct": (0.005, 0.50),
        "kline_limit": (50, 500),
    }
    lo, hi = ranges.get(key, (float("-inf"), float("inf")))
    return lo <= value <= hi
