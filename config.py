import os

# Try loading .env file locally if present
try:
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
except Exception:
    pass

# API Credentials (Loaded via Environment Variables on Render / Local .env)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Telegram Bot Credentials
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Google Sheets export (via Google Form) - see sheets_exporter.py
GOOGLE_FORM_URL = os.getenv("GOOGLE_FORM_URL", "")

# Binance Futures Testnet Endpoints
BINANCE_FUTURES_URL = "https://testnet.binancefuture.com"
BINANCE_PUBLIC_API_URL = "https://fapi.binance.com"  # Public klines (TradingView source)
# Fallback public data sources (fapi.binance.com is geo-blocked in some regions/clouds)
BINANCE_PUBLIC_API_URLS = [
    "https://fapi.binance.com",
    "https://testnet.binancefuture.com",
]

# AI Settings
GROQ_MODEL = "llama-3.3-70b-versatile"

# Bot Trading Parameters
SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
KLINE_LIMIT = 100  # Number of candles to fetch for indicator analysis
LEVERAGE = 2        # Default leverage for Futures (reduced from 3 for safety)

# Risk & Money Management (Daily 1.0% - 1.5% Growth Strategy)
RISK_PER_TRADE_PCT = 0.005       # 0.5% account equity risk per trade (conservative)
DAILY_TARGET_PROFIT_PCT = 0.015  # 1.5% daily growth goal
MAX_DAILY_DRAWDOWN_PCT = 0.025   # 2.5% max daily drawdown limit (safety circuit breaker)
CONFIDENCE_THRESHOLD = 70        # AI confidence threshold (%) to execute trades (selective)

# Binance Futures Fee Rates (Standard Taker Fee = 0.05%)
BINANCE_FUTURES_TAKER_FEE = 0.0005  # 0.05% per order
ROUNDTRIP_FEE_RATE = BINANCE_FUTURES_TAKER_FEE * 2  # 0.10% total fee for opening + closing

# ATR Dynamic Risk Multipliers
ATR_SL_MULTIPLIER = 1.5  # Stop Loss = Entry +/- (1.5 * ATR) - 1:2 R:R target
ATR_TP_MULTIPLIER = 3.0  # Take Profit = Entry +/- (3.0 * ATR) - better R:R

# Log / Execution Settings
CHECK_INTERVAL_SECONDS = 300  # Interval to check position / market state in seconds (5 min)
