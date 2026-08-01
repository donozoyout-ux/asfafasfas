import pandas as pd
import numpy as np

def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI)."""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    # Exponential moving average method for smoother RSI
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    
    rs = gain / (loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    """Calculate Exponential Moving Average (EMA)."""
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR)."""
    high = df['high']
    low = df['low']
    close = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr

def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0):
    """Calculate Bollinger Bands (Upper, Middle, Lower, Bandwidth, %B)."""
    sma = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()
    
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    bandwidth = (upper_band - lower_band) / sma
    percent_b = (df['close'] - lower_band) / (upper_band - lower_band + 1e-10)
    return upper_band, sma, lower_band, bandwidth, percent_b

def detect_rsi_divergence(df: pd.DataFrame, lookback: int = 20) -> str:
    """
    Detects RSI Bullish or Bearish divergence over recent candles.
    Bullish Divergence: Price makes Lower Low, RSI makes Higher Low.
    Bearish Divergence: Price makes Higher High, RSI makes Lower High.
    """
    if len(df) < lookback or 'rsi' not in df.columns:
        return "NONE"
    
    recent_df = df.iloc[-lookback:].copy()
    
    p_min1 = recent_df['close'].iloc[-5:].min()
    p_min2 = recent_df['close'].iloc[:-5].min()
    
    r_min1 = recent_df['rsi'].iloc[-5:].min()
    r_min2 = recent_df['rsi'].iloc[:-5].min()
    
    p_max1 = recent_df['close'].iloc[-5:].max()
    p_max2 = recent_df['close'].iloc[:-5].max()
    
    r_max1 = recent_df['rsi'].iloc[-5:].max()
    r_max2 = recent_df['rsi'].iloc[:-5].max()
    
    if p_min1 < p_min2 and r_min1 > r_min2:
        return "BULLISH_DIVERGENCE"
    elif p_max1 > p_max2 and r_max1 < r_max2:
        return "BEARISH_DIVERGENCE"
    
    return "NONE"

def calculate_support_resistance(df: pd.DataFrame, window: int = 15) -> tuple:
    """Calculates dynamic Support and Resistance levels from recent swing points."""
    if len(df) < window * 2:
        current = df['close'].iloc[-1]
        return current * 0.98, current * 1.02
        
    recent_df = df.iloc[-window*3:]
    highs = recent_df['high'].values
    lows = recent_df['low'].values
    
    resistance = float(np.max(highs))
    support = float(np.min(lows))
    
    return round(support, 2), round(resistance, 2)

def detect_market_structure(df: pd.DataFrame) -> str:
    """Detects Market Structure (BULLISH_STRUCTURE, BEARISH_STRUCTURE, or CONSOLIDATION)."""
    if len(df) < 15:
        return "CONSOLIDATION"
        
    recent = df.iloc[-10:]
    highs = recent['high'].values
    lows = recent['low'].values
    
    first_half_h = np.max(highs[:5])
    second_half_h = np.max(highs[5:])
    first_half_l = np.min(lows[:5])
    second_half_l = np.min(lows[5:])
    
    if second_half_h > first_half_h and second_half_l > first_half_l:
        return "BULLISH_STRUCTURE (Higher Highs & Higher Lows)"
    elif second_half_h < first_half_h and second_half_l < first_half_l:
        return "BEARISH_STRUCTURE (Lower Highs & Lower Lows)"
    else:
        return "CONSOLIDATION / SIDEWAYS"

def detect_crash_risk(df: pd.DataFrame) -> dict:
    """Detects rapid flash crashes or sudden high volume sell-offs."""
    if len(df) < 5:
        return {"crash_alert": False, "message": "Normal market volatility"}
        
    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]
    
    pct_drop_1c = ((last_candle['close'] - last_candle['open']) / last_candle['open']) * 100
    three_candle_drop = ((last_candle['close'] - df.iloc[-4]['open']) / df.iloc[-4]['open']) * 100
    
    if pct_drop_1c < -1.8 or three_candle_drop < -3.0:
        return {
            "crash_alert": True,
            "message": f"🚨 FLASH DIP DETECTED! Price dropped {pct_drop_1c:.2f}% rapidly. Extreme caution."
        }
    return {"crash_alert": False, "message": "Normal market volatility"}

def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes all primary technical indicators and enriches DataFrame:
    1. RSI (14) & Divergence
    2. EMA 9, EMA 21, EMA 200 (Trend Alignment)
    3. ATR (14) & Bollinger Bands
    4. Support/Resistance & Market Structure
    """
    df = df.copy()
    
    # Ensure numeric columns
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # 1. RSI
    df['rsi'] = calculate_rsi(df, period=14)
    
    # 2. EMA
    df['ema_9'] = calculate_ema(df, period=9)
    df['ema_21'] = calculate_ema(df, period=21)
    df['ema_200'] = calculate_ema(df, period=200)
    
    # EMA Signals
    df['ema_macro_trend'] = np.where(df['close'] > df['ema_200'], 'BULLISH', 'BEARISH')
    df['ema_cross'] = np.where(df['ema_9'] > df['ema_21'], 'BULLISH_CROSS', 'BEARISH_CROSS')
    
    # 3. ATR & Bollinger
    df['atr'] = calculate_atr(df, period=14)
    bb_upper, bb_mid, bb_lower, bb_width, percent_b = calculate_bollinger_bands(df, period=20, std_dev=2.0)
    df['bb_upper'] = bb_upper
    df['bb_middle'] = bb_mid
    df['bb_lower'] = bb_lower
    df['bb_bandwidth'] = bb_width
    df['bb_percent_b'] = percent_b
    
    # RSI Divergence
    df['rsi_divergence'] = detect_rsi_divergence(df)
    
    return df

def get_latest_indicator_summary(df: pd.DataFrame) -> dict:
    """Returns a clean dictionary of the latest technical state for AI prompt injection."""
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    rsi_val = float(latest['rsi'])
    if rsi_val > 70:
        rsi_status = "OVERBOUGHT"
    elif rsi_val < 30:
        rsi_status = "OVERSOLD"
    else:
        rsi_status = "NEUTRAL"
        
    support, resistance = calculate_support_resistance(df)
    market_structure = detect_market_structure(df)
    crash_info = detect_crash_risk(df)
    
    return {
        "current_price": float(latest['close']),
        "rsi_14": round(rsi_val, 2),
        "rsi_status": rsi_status,
        "rsi_divergence": latest['rsi_divergence'],
        "ema_9": round(float(latest['ema_9']), 2),
        "ema_21": round(float(latest['ema_21']), 2),
        "ema_200": round(float(latest['ema_200']), 2),
        "macro_trend_ema200": latest['ema_macro_trend'],
        "short_term_ema_cross": latest['ema_cross'],
        "atr_14": round(float(latest['atr']), 2),
        "bb_upper": round(float(latest['bb_upper']), 2),
        "bb_lower": round(float(latest['bb_lower']), 2),
        "bb_bandwidth": round(float(latest['bb_bandwidth']), 4),
        "bb_percent_b": round(float(latest['bb_percent_b']), 2),
        "support_level": support,
        "resistance_level": resistance,
        "market_structure": market_structure,
        "crash_alert": crash_info["crash_alert"],
        "crash_message": crash_info["message"],
        "volume_change_pct": round(((float(latest['volume']) - float(prev['volume'])) / (float(prev['volume']) + 1e-5)) * 100, 2)
    }

