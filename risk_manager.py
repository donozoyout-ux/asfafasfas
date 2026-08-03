import config

# Binance Futures Fee Rates (Standard Taker Fee = 0.05%)
BINANCE_FUTURES_TAKER_FEE = config.BINANCE_FUTURES_TAKER_FEE
ROUNDTRIP_FEE_RATE = config.ROUNDTRIP_FEE_RATE

class RiskManager:
    def __init__(self, initial_balance: float = 5000.0):
        self.initial_daily_balance = initial_balance
        self.current_daily_profit_pct = 0.0
        self.trades_today = 0
        
    def reset_daily_stats(self, current_balance: float):
        """Resets starting balance at the start of a new trading day."""
        self.initial_daily_balance = current_balance
        self.current_daily_profit_pct = 0.0
        self.trades_today = 0

    def check_daily_limits(self, current_balance: float) -> tuple[bool, str]:
        """
        Checks if daily target profit (0.5%-1.0%) or max daily drawdown (-3%) has been hit.
        Returns (can_trade: bool, reason: str).
        """
        if self.initial_daily_balance <= 0:
            return True, "Valid balance"
            
        profit_amount = current_balance - self.initial_daily_balance
        self.current_daily_profit_pct = profit_amount / self.initial_daily_balance
        
        if self.current_daily_profit_pct >= config.DAILY_TARGET_PROFIT_PCT:
            return False, f"Daily target profit achieved (+{self.current_daily_profit_pct*100:.2f}%). Capital preserved."
            
        if self.current_daily_profit_pct <= -config.MAX_DAILY_DRAWDOWN_PCT:
            return False, f"Max daily drawdown hit ({self.current_daily_profit_pct*100:.2f}%). Circuit breaker active."
            
        return True, f"Trading active (Daily PnL: {self.current_daily_profit_pct*100:+.2f}%)"

    def calculate_position_parameters(
        self,
        account_balance: float,
        entry_price: float,
        atr_14: float,
        side: str,
        sl_mult: float = config.ATR_SL_MULTIPLIER,
        tp_mult: float = config.ATR_TP_MULTIPLIER,
        risk_pct: float = None
    ) -> dict:
        """
        Calculates exact Stop-Loss, Take-Profit, and position size (quantity in BTC)
        matching account risk tolerance and accounting for Binance Futures trading fees.
        risk_pct can be overridden by the learning engine (adaptive risk).
        """
        if risk_pct is None:
            risk_pct = config.RISK_PER_TRADE_PCT
        # Ensure Take Profit covers roundtrip trading fees (0.10%) + ATR target
        fee_offset = entry_price * ROUNDTRIP_FEE_RATE
        
        if side.upper() == "LONG":
            sl_price = entry_price - (atr_14 * sl_mult)
            tp_price = entry_price + (atr_14 * tp_mult) + fee_offset
        elif side.upper() == "SHORT":
            sl_price = entry_price + (atr_14 * sl_mult)
            tp_price = entry_price - (atr_14 * tp_mult) - fee_offset
        else:
            return {}

        sl_distance = abs(entry_price - sl_price)
        sl_distance_pct = sl_distance / entry_price
        
        # Risk amount in USDT = Balance * Risk_per_trade_pct (adaptive)
        risk_usdt = account_balance * risk_pct
        
        # Position Notional Value = Risk_USDT / SL_distance_pct
        notional_val = risk_usdt / (sl_distance_pct + 1e-6)
        
        # Apply leverage constraint with a safety margin so Binance always has
        # room for maintenance margin + fees (full-leverage usage gets rejected
        # with "Margin is insufficient"). Max 60% of balance used as margin.
        margin_utilization = 0.60
        max_notional = account_balance * config.LEVERAGE * margin_utilization
        position_notional = min(notional_val, max_notional)
        
        # Quantity in contracts (e.g. BTC)
        quantity = round(position_notional / entry_price, 3)
        
        # Minimum Binance contract size guard for BTCUSDT (0.001 BTC)
        if quantity < 0.001:
            quantity = 0.001

        actual_notional = quantity * entry_price
        est_roundtrip_fee_usdt = actual_notional * ROUNDTRIP_FEE_RATE

        return {
            "entry_price": round(entry_price, 2),
            "sl_price": round(sl_price, 2),
            "tp_price": round(tp_price, 2),
            "quantity": quantity,
            "risk_usdt": round(risk_usdt, 2),
            "notional_value": round(actual_notional, 2),
            "est_roundtrip_fee_usdt": round(est_roundtrip_fee_usdt, 3),
            "risk_reward_ratio": round(tp_mult / sl_mult, 2)
        }
