import config

# Binance Futures Fee Rates (Standard Taker Fee = 0.05%)
BINANCE_FUTURES_TAKER_FEE = config.BINANCE_FUTURES_TAKER_FEE
ROUNDTRIP_FEE_RATE = config.ROUNDTRIP_FEE_RATE


class RiskManager:
    def __init__(self, initial_balance: float = 5000.0):
        self.initial_daily_balance = initial_balance
        self.current_daily_profit_pct = 0.0
        self.daily_target_hit = False

    def reset_daily_stats(self, current_balance: float):
        """Resets starting balance at the start of a new trading day."""
        self.initial_daily_balance = current_balance
        self.current_daily_profit_pct = 0.0
        self.daily_target_hit = False

    def check_daily_limits(self, current_balance: float) -> tuple[bool, str]:
        """
        Checks if daily target profit or max daily drawdown has been hit.
        Returns (can_trade: bool, reason: str).
        NO trade count limit - only profit/loss limits.
        """
        if self.initial_daily_balance <= 0:
            return True, "Valid balance"

        profit_amount = current_balance - self.initial_daily_balance
        self.current_daily_profit_pct = profit_amount / self.initial_daily_balance

        # Check max drawdown FIRST (safety)
        if self.current_daily_profit_pct <= -config.MAX_DAILY_DRAWDOWN_PCT:
            return False, f"Max daily drawdown hit ({self.current_daily_profit_pct*100:.2f}%). Circuit breaker active."

        # Check daily target - if hit, stop NEW trades but allow managing open positions
        if self.current_daily_profit_pct >= config.DAILY_TARGET_PROFIT_PCT:
            self.daily_target_hit = True
            return False, f"Daily target profit achieved (+{self.current_daily_profit_pct*100:.2f}%). No new trades."

        return True, f"Trading active (Daily PnL: {self.current_daily_profit_pct*100:+.2f}%)"

    def is_daily_target_hit(self) -> bool:
        """Returns True if daily target was hit - no new trades allowed."""
        return self.daily_target_hit

    def calculate_position_parameters(
        self,
        account_balance: float,
        entry_price: float,
        atr_14: float,
        side: str,
        sl_mult: float = config.ATR_SL_MULTIPLIER,
        tp_mult: float = config.ATR_TP_MULTIPLIER,
        risk_pct: float = None,
        leverage: float = None
    ) -> dict:
        """
        Calculates exact Stop-Loss, Take-Profit, and position size (quantity in BTC)
        matching account risk tolerance and accounting for Binance Futures trading fees.
        risk_pct can be overridden by the learning engine (adaptive risk).
        leverage can be overridden by the adaptive strategy (defaults to config.LEVERAGE).
        """
        if risk_pct is None:
            risk_pct = config.RISK_PER_TRADE_PCT
        if leverage is None:
            leverage = config.LEVERAGE
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
        max_notional = account_balance * leverage * margin_utilization
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
            "risk_reward_ratio": round(tp_mult / sl_mult, 2),
            "leverage": leverage
        }

    def calculate_trailing_stop(self, entry_price: float, current_price: float, atr_14: float, side: str, trail_mult: float = 1.5) -> float:
        """
        Calculates trailing stop price based on ATR.
        Only activates after price moves in favor by at least 1% (or 1x ATR).
        """
        if side.upper() == "LONG":
            # Trail below current price
            trail_distance = atr_14 * trail_mult
            new_sl = current_price - trail_distance
            # Only move SL up (never down)
            return max(new_sl, entry_price)  # At minimum, breakeven
        else:
            # SHORT: trail above current price
            trail_distance = atr_14 * trail_mult
            new_sl = current_price + trail_distance
            # Only move SL down (never up)
            return min(new_sl, entry_price)  # At minimum, breakeven

    def should_trail_activate(self, entry_price: float, current_price: float, side: str, min_profit_pct: float = 0.01) -> bool:
        """Check if trailing stop should activate (price moved favorably by min_profit_pct)."""
        if side.upper() == "LONG":
            return (current_price - entry_price) / entry_price >= min_profit_pct
        else:
            return (entry_price - current_price) / entry_price >= min_profit_pct


def adaptive_parameters(atr_14: float, entry_price: float, base_leverage: float = None) -> dict:
    """
    Bot auto-selects leverage + ATR multipliers based on current volatility.
    High volatility -> lower leverage + wider stops (avoid liquidation whipsaws).
    Low volatility -> higher leverage + tighter stops.

    Never lets SL/TP fall below the config baselines (config.ATR_SL_MULTIPLIER /
    config.ATR_TP_MULTIPLIER) so the bot keeps the widened risk envelope.
    """
    base_leverage = base_leverage if base_leverage else config.LEVERAGE
    atr_pct = (atr_14 / entry_price * 100) if entry_price > 0 else 1.0

    if atr_pct >= 1.0:      # Extreme volatility
        leverage = min(base_leverage, 2)
        sl_mult = 2.0
        tp_mult = 3.5
    elif atr_pct >= 0.6:    # High volatility
        leverage = min(base_leverage, 3)
        sl_mult = 1.8
        tp_mult = 3.2
    elif atr_pct >= 0.35:   # Medium volatility
        leverage = min(base_leverage, 4)
        sl_mult = 1.6
        tp_mult = 3.0
    else:                   # Low volatility
        leverage = base_leverage
        sl_mult = 1.4
        tp_mult = 2.8

    # Ensure minimums from config
    sl_mult = max(sl_mult, config.ATR_SL_MULTIPLIER)
    tp_mult = max(tp_mult, config.ATR_TP_MULTIPLIER)

    return {
        "leverage": max(1, int(leverage)),
        "sl_multiplier": sl_mult,
        "tp_multiplier": tp_mult,
        "atr_pct": round(atr_pct, 3)
    }