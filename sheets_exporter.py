"""
Google Sheets exporter via Google Forms.

How it works:
  - User creates a Google Form with fields matching the trade result columns.
  - The form's "viewform" URL is used to POST responses (formResponse endpoint).
  - Google Forms automatically writes each submission into the linked Google
    Sheet (Responses tab). No API keys / service accounts needed.
"""

import os
import re
import time
import requests

import config

# Entry point for the form submission. Expected to be like:
#   https://docs.google.com/forms/d/e/<ID>/viewform
# Read from config so the .env file is loaded exactly once (config.py handles it).
FORM_URL = config.GOOGLE_FORM_URL

# Optional: if the form uses a prefilled entry for a hidden field, set it here.
FORM_ENTRY = os.getenv("GOOGLE_FORM_ENTRY", "")

_FIELD_ENTRY_MAP = {
    "trade_id": "entry.1636594966",
    "timestamp": "entry.708984115",
    "symbol": "entry.71097525",
    "side": "entry.1158640561",
    "entry_price": "entry.620676542",
    "exit_price": "entry.917238069",
    "quantity": "entry.1727377833",
    "pnl_usdt": "entry.1526109894",
    "pnl_pct": "entry.2025502699",
    "status": "entry.1736208606",
    "ai_confidence": "entry.1827741123",
    "hold_time_min": "entry.1808883219",
}

_last_sent = {}
_sent_ids = set()

# Google Forms returns HTTP 200 on both success and failure, so we must verify
# the response body actually confirms the submission (localized markers).
_SUCCESS_MARKERS = [
    "response has been recorded",
    "your response has been recorded",
    "yanıtınız kaydedildi",
    "yanitiniz kaydedildi",
    "teşekkür",
    "tesekkur",
]


def _is_success(response_text: str) -> bool:
    """True if the Google Forms response page confirms the submission."""
    lower = response_text.lower()
    return any(m in lower for m in _SUCCESS_MARKERS)


def is_enabled() -> bool:
    return bool(FORM_URL and FORM_URL.strip())


def _extract_form_id(form_url: str) -> str:
    """Extracts the form ID from a Google Form URL for the response endpoint."""
    url = form_url.strip()
    if "/forms/d/e/" in url:
        part = url.split("/forms/d/e/", 1)[1]
        form_id = part.split("/", 1)[0]
        return form_id
    if "/forms/d/" in url:
        part = url.split("/forms/d/", 1)[1]
        form_id = part.split("/", 1)[0]
        return form_id
    return ""


def export_trade(trade: dict) -> bool:
    """Sends a closed trade result to the Google Form (and thus to Sheets).

    Idempotent: each trade_id is only sent once per process run.
    Returns True on success, False otherwise.
    """
    if not is_enabled():
        return False

    trade_id = trade.get("id") or trade.get("trade_id")
    if trade_id is None:
        return False
    if trade_id in _sent_ids:
        return True  # already exported

    form_id = _extract_form_id(FORM_URL)
    if not form_id:
        print("[SHEETS] Could not parse form ID from GOOGLE_FORM_URL")
        return False

    payload = {}
    for field, entry in _FIELD_ENTRY_MAP.items():
        val = trade.get(field)
        if val is None:
            continue
        payload[entry] = str(val)

    # Optional hidden entry (e.g. bot instance name)
    if FORM_ENTRY:
        payload.setdefault("entry.0", FORM_ENTRY)

    endpoint = f"https://docs.google.com/forms/d/e/{form_id}/formResponse"
    try:
        res = requests.post(
            endpoint,
            data=payload,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15,
        )
        # Google Forms returns 200 on success (even if it also returns HTML),
        # so confirm via the response body marker instead of trusting status.
        if res.status_code == 200 and _is_success(res.text):
            _sent_ids.add(trade_id)
            print(f"[SHEETS] Trade #{trade_id} exported to Google Sheets (form {form_id})")
            return True
        print(f"[SHEETS] Export not confirmed for trade #{trade_id} (HTTP {res.status_code})")
        return False
    except Exception as e:
        print(f"[SHEETS] Export exception for trade #{trade_id}: {e}")
        return False


def export_closed_trade(trade_id: int, timestamp: str, symbol: str, side: str,
                        entry_price: float, exit_price: float, quantity: float,
                        pnl_usdt: float, pnl_pct: float, status: str,
                        ai_confidence: int = 0, hold_time_min: int = 0) -> bool:
    """Convenience wrapper to export a closed trade given plain values."""
    return export_trade({
        "trade_id": trade_id,
        "timestamp": timestamp,
        "symbol": symbol,
        "side": side,
        "entry_price": round(float(entry_price), 2),
        "exit_price": round(float(exit_price), 2),
        "quantity": quantity,
        "pnl_usdt": round(float(pnl_usdt), 2),
        "pnl_pct": round(float(pnl_pct), 2),
        "status": status,
        "ai_confidence": ai_confidence,
        "hold_time_min": hold_time_min,
    })
