import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

_CACHE_TTL_SECONDS = 600  # 10 minutes
_BACKOFF_SECONDS = 600    # 10 minutes cooldown on failure

_cache = {}
_last_fetch = {}
_backoff_until = {}

_BULLISH_WORDS = [
    "surge", "surges", "soars", "rally", "rallies", "record high", "all-time high",
    "ath", "etf inflow", "etf inflows", "inflows", "approval", "approved", "adoption",
    "institutional", "whale", "bullish", "breakout", "buy", "buys", "accumulation",
    "hodl", "halving", "upgrade", "partnership", "integration", "growth", "gains",
    "milestone", "demand", "outflows",
]

_BEARISH_WORDS = [
    "crash", "plunge", "plunges", "dump", "dumps", "sell-off", "selloff", "ban",
    "banned", "hack", "hacked", "exploit", "fear", "fears", "bearish", "breakdown",
    "rejection", "reject", "liquidation", "liquidations", "fraud", "lawsuit",
    "regulation", "crackdown", "capitulation", "dead", "collapse", "collapse",
    "panic", "outflows", "sec", "withdrawal", "withdrawals",
]


def _parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _is_recent(dt: Optional[datetime], max_age_hours: int = 48) -> bool:
    if dt is None:
        return True
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) <= timedelta(hours=max_age_hours)


def _format_date(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    try:
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                mins = diff.seconds // 60
                return f"{mins} min ago"
            return f"{hours}h ago"
        if diff.days == 1:
            return "yesterday"
        return f"{diff.days}d ago"
    except Exception:
        return ""


def _fetch_google_news(symbol: str, max_items: int = 12) -> list[dict]:
    """Google News RSS for crypto news (English)."""
    clean = symbol.replace("USDT", "").strip().upper()
    queries = [f"Bitcoin {clean}", f"{clean} crypto market", f"Bitcoin price"]
    seen_titles = set()
    items = []

    for query in queries:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=8,
            )
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                dt = _parse_date(pub_date)
                if not _is_recent(dt):
                    continue
                items.append({
                    "title": title,
                    "link": link,
                    "source": "Google News",
                    "date": _format_date(dt),
                })
                if len(items) >= max_items:
                    return items
        except Exception:
            continue
    return items


def _fetch_cryptocompare_news(max_items: int = 10) -> list[dict]:
    """CryptoCompare news API (free, no key for limited public feed)."""
    try:
        resp = requests.get(
            "https://min-api.cryptocompare.com/data/v2/news/?lang=EN",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        data = resp.json().get("Data", [])
        items = []
        for entry in data:
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            dt = _parse_date(entry.get("published_on") and datetime.fromtimestamp(entry["published_on"], timezone.utc).isoformat())
            items.append({
                "title": title,
                "link": entry.get("url") or "",
                "source": entry.get("source") or "CryptoCompare",
                "date": _format_date(dt),
            })
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []


def _score_text(text: str) -> int:
    """Keyword-based sentiment scoring: +1 bullish, -1 bearish, 0 neutral per hit."""
    lowered = text.lower()
    score = 0
    for word in _BULLISH_WORDS:
        if word in lowered:
            score += 1
    for word in _BEARISH_WORDS:
        if word in lowered:
            score -= 1
    return score


def compute_sentiment(headlines: list[dict]) -> dict:
    """Aggregate headline sentiment into a -1..+1 score with label."""
    if not headlines:
        return {"sentiment_score": 0.0, "sentiment_label": "NEUTRAL", "analyzed": 0}
    total = sum(_score_text(h.get("title", "")) for h in headlines)
    # Normalize to -1..+1 by number of headlines
    score = max(-1.0, min(1.0, total / max(3, len(headlines))))
    if score >= 0.25:
        label = "BULLISH"
    elif score <= -0.25:
        label = "BEARISH"
    else:
        label = "NEUTRAL"
    return {
        "sentiment_score": round(score, 3),
        "sentiment_label": label,
        "analyzed": len(headlines),
    }


def get_crypto_news(max_items: int = 15) -> dict:
    """
    Top-level news fetch with cache + failure backoff.
    Returns dict with sentiment, top headlines, and source count.
    """
    key = "crypto_news"
    now = time.time()

    # Failure backoff: don't hammer a failing source
    if now < _backoff_until.get(key, 0):
        return _cache.get(key, {
            "sentiment_score": 0.0,
            "sentiment_label": "NEUTRAL",
            "top_headlines": [],
            "sources": 0,
            "cached": True,
        })

    if now - _last_fetch.get(key, 0) < _CACHE_TTL_SECONDS:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    headlines = _fetch_google_news("BTC", max_items=12) + _fetch_cryptocompare_news(max_items=10)

    if not headlines:
        _backoff_until[key] = now + _BACKOFF_SECONDS
        # Return stale cache if available
        if key in _cache:
            return _cache[key]
        return {
            "sentiment_score": 0.0,
            "sentiment_label": "NEUTRAL",
            "top_headlines": [],
            "sources": 0,
            "cached": True,
        }

    sentiment = compute_sentiment(headlines)
    result = {
        "sentiment_score": sentiment["sentiment_score"],
        "sentiment_label": sentiment["sentiment_label"],
        "top_headlines": [h["title"] for h in headlines[:5]],
        "headline_details": headlines[:8],
        "sources": len({h["source"] for h in headlines}),
        "cached": False,
    }
    _cache[key] = result
    _last_fetch[key] = now
    return result
