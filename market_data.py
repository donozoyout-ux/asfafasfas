import requests
import pandas as pd
import config


def _fetch_klines_from(base_url: str, symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Fetches OHLCV from a single Binance-compatible API base URL."""
    url = f"{base_url}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            cols = [
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ]
            df = pd.DataFrame(data, columns=cols)
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df
        else:
            print(f"[WARN] Klines HTTP {response.status_code} from {base_url}")
            return pd.DataFrame()
    except Exception as e:
        print(f"[EXCEPT] Klines error from {base_url}: {e}")
        return pd.DataFrame()


def fetch_klines(symbol: str = config.SYMBOL, interval: str = config.TIMEFRAME, limit: int = config.KLINE_LIMIT) -> pd.DataFrame:
    """
    Fetches raw OHLCV kline candles, trying multiple Binance-compatible sources.
    Falls back gracefully if one endpoint is blocked (e.g. fapi.binance.com
    geo-blocked on some cloud hosts like Render).
    """
    sources = config.BINANCE_PUBLIC_API_URLS if hasattr(config, "BINANCE_PUBLIC_API_URLS") else [config.BINANCE_PUBLIC_API_URL]
    for base in sources:
        df = _fetch_klines_from(base, symbol, interval, limit)
        if not df.empty:
            return df
    print(f"[ERROR] Failed to fetch klines from all {len(sources)} sources")
    return pd.DataFrame()

def fetch_current_price(symbol: str = config.SYMBOL) -> float:
    """Fetches the real-time mark price or last price for the given pair."""
    sources = config.BINANCE_PUBLIC_API_URLS if hasattr(config, "BINANCE_PUBLIC_API_URLS") else [config.BINANCE_PUBLIC_API_URL]
    for base in sources:
        try:
            res = requests.get(f"{base}/fapi/v1/ticker/price", params={"symbol": symbol}, timeout=5)
            if res.status_code == 200:
                return float(res.json()["price"])
        except Exception:
            continue
    return 0.0

def fetch_24h_ticker(symbol: str = config.SYMBOL) -> dict:
    """Fetches 24h ticker info (high, low, volume, price change %)."""
    sources = config.BINANCE_PUBLIC_API_URLS if hasattr(config, "BINANCE_PUBLIC_API_URLS") else [config.BINANCE_PUBLIC_API_URL]
    for base in sources:
        try:
            res = requests.get(f"{base}/fapi/v1/ticker/24hr", params={"symbol": symbol}, timeout=5)
            if res.status_code == 200:
                data = res.json()
                return {
                    "price_change_pct": float(data.get("priceChangePercent", 0)),
                    "high_24h": float(data.get("highPrice", 0)),
                    "low_24h": float(data.get("lowPrice", 0)),
                    "volume_24h": float(data.get("volume", 0))
                }
        except Exception:
            continue
    return {}

def fetch_multiframe_data(symbol: str = config.SYMBOL) -> dict:
    """Fetches klines for 15m, 1h, and 4h to construct multi-timeframe analysis."""
    frames = {"15m": "15m", "1h": "1h", "4h": "4h"}
    result = {}
    for label, interval in frames.items():
        df = fetch_klines(symbol, interval, limit=50)
        if not df.empty:
            close = df['close'].iloc[-1]
            ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            trend = "BULLISH" if close > ema50 else "BEARISH"
            result[label] = {
                "trend": trend,
                "last_close": round(float(close), 2),
                "ema50": round(float(ema50), 2)
            }
        else:
            result[label] = {"trend": "UNKNOWN", "last_close": 0, "ema50": 0}
    return result

