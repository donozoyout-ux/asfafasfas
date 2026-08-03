import os
import sqlite3
import pandas as pd
from datetime import datetime

# Data directory: overridable via DATA_DIR env var (Render Persistent Disk).
# Falls back to the script directory for local dev.
_DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(_DATA_DIR):
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        _DATA_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(_DATA_DIR, "trades.db")

def init_db():
    """Initializes SQLite database for persistent trade logging and self-learning."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            sl_price REAL,
            tp_price REAL,
            pnl_usdt REAL,
            pnl_pct REAL,
            status TEXT, -- 'OPEN', 'WIN', 'LOSS', 'CLOSED'
            ai_confidence INTEGER,
            ai_reasoning TEXT,
            rsi_val REAL,
            ema200_trend TEXT,
            atr_val REAL,
            market_structure TEXT,
            multiframe_trend TEXT,
            rsi_status TEXT,
            rsi_divergence TEXT,
            crash_alert INTEGER DEFAULT 0,
            hold_time_min INTEGER DEFAULT 0
        )
    """)
    # Migrate old tables: add missing learning columns if they don't exist
    try:
        existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(trades)").fetchall()}
        migrate_cols = {
            "market_structure": "TEXT",
            "multiframe_trend": "TEXT",
            "rsi_status": "TEXT",
            "rsi_divergence": "TEXT",
            "crash_alert": "INTEGER DEFAULT 0",
            "hold_time_min": "INTEGER DEFAULT 0",
        }
        for col, col_type in migrate_cols.items():
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
                print(f"[DB] Added column: {col}")
    except Exception as e:
        print(f"[DB] Migration check warning: {e}")
    conn.commit()
    conn.close()

def log_trade_entry(symbol: str, side: str, entry_price: float, quantity: float, sl_price: float, tp_price: float, ai_confidence: int, ai_reasoning: str, indicator_summary: dict) -> int:
    """Logs a newly opened trade into the database."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO trades (
            timestamp, symbol, side, entry_price, exit_price, quantity,
            sl_price, tp_price, pnl_usdt, pnl_pct, status,
            ai_confidence, ai_reasoning, rsi_val, ema200_trend, atr_val,
            market_structure, multiframe_trend, rsi_status, rsi_divergence, crash_alert
        ) VALUES (?, ?, ?, ?, 0.0, ?, ?, ?, 0.0, 0.0, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now_str, symbol, side, entry_price, quantity,
        sl_price, tp_price, ai_confidence, ai_reasoning,
        indicator_summary.get('rsi_14', 0),
        indicator_summary.get('macro_trend_ema200', 'UNKNOWN'),
        indicator_summary.get('atr_14', 0),
        indicator_summary.get('market_structure', 'UNKNOWN'),
        indicator_summary.get('multiframe_trend', 'MIXED'),
        indicator_summary.get('rsi_status', 'NEUTRAL'),
        indicator_summary.get('rsi_divergence', 'NONE'),
        1 if indicator_summary.get('crash_alert') else 0
    ))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    print(f"[DB] Trade logged (ID #{trade_id}): {side} {quantity} {symbol} @ ${entry_price:.2f}")
    return trade_id

def update_trade_exit(trade_id: int, exit_price: float, pnl_usdt: float, pnl_pct: float):
    """Updates a closed trade with exit price and calculated PnL."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    status = "WIN" if pnl_usdt > 0 else "LOSS"
    
    # Compute hold time in minutes
    hold_min = 0
    try:
        cursor.execute("SELECT timestamp FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        if row and row[0]:
            entry_ts = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            hold_min = int((datetime.now() - entry_ts).total_seconds() / 60)
    except Exception:
        pass
    
    cursor.execute("""
        UPDATE trades 
        SET exit_price = ?, pnl_usdt = ?, pnl_pct = ?, status = ?, hold_time_min = ?
        WHERE id = ?
    """, (exit_price, pnl_usdt, pnl_pct, status, hold_min, trade_id))
    conn.commit()
    conn.close()
    print(f"[DB] Trade #{trade_id} closed! Status: {status} | PnL: ${pnl_usdt:+.2f} ({pnl_pct:+.2f}%) | Hold: {hold_min}m")

def get_performance_summary() -> dict:
    """Returns overall trade performance statistics and win rate."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM trades WHERE status IN ('WIN', 'LOSS')", conn)
    conn.close()
    
    if df.empty:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl_usdt": 0.0,
            "best_trade_usdt": 0.0,
            "worst_trade_usdt": 0.0
        }
        
    wins = len(df[df['status'] == 'WIN'])
    losses = len(df[df['status'] == 'LOSS'])
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0.0
    
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 1),
        "total_pnl_usdt": round(float(df['pnl_usdt'].sum()), 2),
        "best_trade_usdt": round(float(df['pnl_usdt'].max()), 2),
        "worst_trade_usdt": round(float(df['pnl_usdt'].min()), 2)
    }

def get_ai_learning_context(limit: int = 5) -> str:
    """
    Constructs a memory context of recent trades to feed into Groq AI prompt,
    enabling continuous in-context reinforcement learning.
    """
    init_db()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT * FROM trades WHERE status IN ('WIN', 'LOSS') ORDER BY id DESC LIMIT {limit}", conn)
    conn.close()
    
    if df.empty:
        return "NO PAST TRADE HISTORY YET. Apply baseline technical discipline."
        
    summary = get_performance_summary()
    memory_text = f"PAST PERFORMANCE MEMORY (Win Rate: {summary['win_rate_pct']}%, Total PnL: ${summary['total_pnl_usdt']:+.2f}):\n"
    
    for idx, row in df.iterrows():
        status_icon = "WIN (+)" if row['status'] == 'WIN' else "LOSS (-)"
        memory_text += f"- Trade #{row['id']}: {row['side']} @ ${row['entry_price']:.2f} -> Result: {status_icon} ${row['pnl_usdt']:+.2f} ({row['pnl_pct']:+.2f}%). AI Rationale at entry: '{row['ai_reasoning']}'. RSI: {row['rsi_val']}, Trend: {row['ema200_trend']}\n"
        
    memory_text += "\nSELF-LEARNING DIRECTIVE: Learn from the winning setups above. If past trades with similar RSI or trend conditions failed, tighten entry thresholds."
    return memory_text

def get_recent_trades(limit: int = 20) -> list:
    """Returns recent trades for the web dashboard (newest first)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, symbol, side, entry_price, quantity, sl_price, tp_price,
               pnl_usdt, ai_confidence, status
        FROM trades
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "symbol": r[1],
            "side": r[2],
            "entry_price": r[3],
            "quantity": r[4],
            "sl_price": r[5],
            "tp_price": r[6],
            "pnl_usdt": r[7],
            "ai_confidence": r[8],
            "status": r[9],
        }
        for r in rows
    ]

def get_stale_open_trades() -> list:
    """Returns all trades still marked OPEN in the DB (no longer matching Binance position)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, timestamp, symbol, side, entry_price, exit_price, quantity,
               pnl_usdt, pnl_pct, status, ai_confidence, ai_reasoning,
               rsi_val, ema200_trend, atr_val, market_structure,
               multiframe_trend, rsi_status, rsi_divergence, crash_alert, hold_time_min
        FROM trades
        WHERE status = 'OPEN'
        ORDER BY id ASC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    cols = [
        "id", "timestamp", "symbol", "side", "entry_price", "exit_price", "quantity",
        "pnl_usdt", "pnl_pct", "status", "ai_confidence", "ai_reasoning",
        "rsi_val", "ema200_trend", "atr_val", "market_structure",
        "multiframe_trend", "rsi_status", "rsi_divergence", "crash_alert", "hold_time_min"
    ]
    return [dict(zip(cols, r)) for r in rows]


def get_trade_timestamp(trade_id: int):
    """Returns the opening timestamp (as epoch ms) of a given trade, or None."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM trades WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return int(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    except Exception:
        return None


def get_closed_trades(limit: int = 50) -> list:
    """Returns closed (WIN/LOSS) trades with full learning context columns."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, timestamp, symbol, side, entry_price, exit_price, quantity,
               pnl_usdt, pnl_pct, status, ai_confidence, ai_reasoning,
               rsi_val, ema200_trend, atr_val, market_structure,
               multiframe_trend, rsi_status, rsi_divergence, crash_alert, hold_time_min
        FROM trades
        WHERE status IN ('WIN', 'LOSS')
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    cols = [
        "id", "timestamp", "symbol", "side", "entry_price", "exit_price", "quantity",
        "pnl_usdt", "pnl_pct", "status", "ai_confidence", "ai_reasoning",
        "rsi_val", "ema200_trend", "atr_val", "market_structure",
        "multiframe_trend", "rsi_status", "rsi_divergence", "crash_alert", "hold_time_min"
    ]
    return [dict(zip(cols, r)) for r in rows]
