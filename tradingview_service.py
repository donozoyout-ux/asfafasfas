import time
import threading
from tradingview_ta import TA_Handler, Interval
import config

_CACHE = {}
_CACHE_TTL = 300  # 5 minutes between successful TradingView refreshes
_FAIL_TTL = 600    # 10 minutes before retrying a failed timeframe (429 backoff)
_LOCK = threading.Lock()

# 1h is the primary macro timeframe. 15m/4h are refreshed less frequently.
_TIME_FRAMES = {
    "1h": Interval.INTERVAL_1_HOUR,
    "15m": Interval.INTERVAL_15_MINUTES,
    "4h": Interval.INTERVAL_4_HOURS,
}


def fetch_tradingview_analysis(symbol: str = "BTCUSDT", exchange: str = "BINANCE") -> dict:
    """
    Fetches official TradingView Technical Analysis summary with rate-limit protection.
    - Results are cached per timeframe for _CACHE_TTL seconds.
    - On failure, the last known result is returned instead of empty NEUTRAL.
    This avoids the HTTP 429 errors from TradingView's shared API.
    """
    results = {}
    now = time.time()

    for tf_label, interval in _TIME_FRAMES.items():
        key = f"{symbol}:{tf_label}"
        with _LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached["ts"]) < _CACHE_TTL:
                results[tf_label] = cached["data"]
                continue
            # If a previous attempt failed recently, back off and reuse last result
            failed = _CACHE.get(key + ":fail")
            if failed and (now - failed) < _FAIL_TTL:
                stale = _CACHE.get(key)
                results[tf_label] = stale["data"] if stale else {
                    "recommendation": "UNKNOWN",
                    "buy_count": 0, "sell_count": 0, "neutral_count": 0,
                    "oscillators": "UNKNOWN", "moving_averages": "UNKNOWN"
                }
                continue

        try:
            handler = TA_Handler(
                symbol=symbol,
                exchange=exchange,
                screener="crypto",
                interval=interval
            )
            analysis = handler.get_analysis()
            summary = analysis.summary

            data = {
                "recommendation": summary.get("RECOMMENDATION", "NEUTRAL"),
                "buy_count": summary.get("BUY", 0),
                "sell_count": summary.get("SELL", 0),
                "neutral_count": summary.get("NEUTRAL", 0),
                "oscillators": analysis.oscillators.get("RECOMMENDATION", "NEUTRAL"),
                "moving_averages": analysis.moving_averages.get("RECOMMENDATION", "NEUTRAL")
            }
            with _LOCK:
                _CACHE[key] = {"ts": now, "data": data}
                _CACHE.pop(key + ":fail", None)
            results[tf_label] = data
        except Exception as e:
            print(f"[EXCEPT] TradingView TA Error ({tf_label}): {e}")
            # Fall back to last known result and back off retries for a while
            with _LOCK:
                stale = _CACHE.get(key)
                _CACHE[key + ":fail"] = now
            if stale:
                results[tf_label] = stale["data"]
            else:
                results[tf_label] = {
                    "recommendation": "UNKNOWN",
                    "buy_count": 0,
                    "sell_count": 0,
                    "neutral_count": 0,
                    "oscillators": "UNKNOWN",
                    "moving_averages": "UNKNOWN"
                }

    # Calculate overall consensus
    rec_1h = results.get("1h", {}).get("recommendation", "NEUTRAL")
    rec_15m = results.get("15m", {}).get("recommendation", "NEUTRAL")
    rec_4h = results.get("4h", {}).get("recommendation", "NEUTRAL")

    results["consensus"] = f"15m: {rec_15m} | 1h: {rec_1h} | 4h: {rec_4h}"
    return results
