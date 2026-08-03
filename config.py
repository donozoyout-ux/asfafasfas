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

# Binance Futures Testnet Endpoints
BINANCE_FUTURES_URL = "https://testnet.binancefuture.com"
BINANCE_PUBLIC_API_URL = "https://fapi.binance.com"  # Public klines (TradingView source)

# AI Settings
GROQ_MODEL = "llama-3.3-70b-versatile"

# Bot Trading Parameters
SYMBOL = "BTCUSDT"
TIMEFRAME = "15m"
KLINE_LIMIT = 100  # Number of candles to fetch for indicator analysis
LEVERAGE = 3        # Default leverage for Futures

# Risk & Money Management (Daily 0.5% - 1.0% Growth Strategy)
RISK_PER_TRADE_PCT = 0.02       # 2.0% account equity risk per trade
DAILY_TARGET_PROFIT_PCT = 0.02  # 2.0% daily growth goal
MAX_DAILY_DRAWDOWN_PCT = 0.05   # 5.0% max daily drawdown limit (safety circuit breaker)
CONFIDENCE_THRESHOLD = 60       # AI confidence threshold (%) to execute trades

# Binance Futures Fee Rates (Standard Taker Fee = 0.05%)
BINANCE_FUTURES_TAKER_FEE = 0.0005  # 0.05% per order
ROUNDTRIP_FEE_RATE = BINANCE_FUTURES_TAKER_FEE * 2  # 0.10% total fee for opening + closing

# ATR Dynamic Risk Multipliers
ATR_SL_MULTIPLIER = 1.5  # Stop Loss = Entry +/- (1.5 * ATR)
ATR_TP_MULTIPLIER = 2.5  # Take Profit = Entry +/- (2.5 * ATR)

# Log / Execution Settings
CHECK_INTERVAL_SECONDS = 30  # Interval to check position / market state in seconds

# Ollama API Base URL
OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
