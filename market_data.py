import requests
import pandas as pd
import config

def fetch_klines(symbol: str = config.SYMBOL, interval: str = config.TIMEFRAME, limit: int = config.KLINE_LIMIT) -> pd.DataFrame:
    """
    Fetches raw OHLCV kline candles from Binance Futures API.
    Returns clean pandas DataFrame.
    """
    url = f"{config.BINANCE_PUBLIC_API_URL}/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
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
            print(f"[ERROR] Failed to fetch klines: HTTP {response.status_code} - {response.text}")
            return pd.DataFrame()
    except Exception as e:
        print(f"[EXCEPT] Error fetching klines: {e}")
        return pd.DataFrame()

def fetch_current_price(symbol: str = config.SYMBOL) -> float:
    """Fetches the real-time mark price or last price for the given pair."""
    url = f"{config.BINANCE_PUBLIC_API_URL}/fapi/v1/ticker/price"
    params = {"symbol": symbol}
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            return float(res.json()["price"])
    except Exception as e:
        print(f"[EXCEPT] Error fetching price: {e}")
    return 0.0

def fetch_24h_ticker(symbol: str = config.SYMBOL) -> dict:
    """Fetches 24h ticker info (high, low, volume, price change %)."""
    url = f"{config.BINANCE_PUBLIC_API_URL}/fapi/v1/ticker/24hr"
    params = {"symbol": symbol}
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return {
                "price_change_pct": float(data.get("priceChangePercent", 0)),
                "high_24h": float(data.get("highPrice", 0)),
                "low_24h": float(data.get("lowPrice", 0)),
                "volume_24h": float(data.get("volume", 0))
            }
    except Exception as e:
        print(f"[EXCEPT] Error fetching 24h ticker: {e}")
    return {}
