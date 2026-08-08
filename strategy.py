"""
Deterministic strategy layer.

The primary LONG/SHORT/HOLD decision is made by coded, transparent rules
(market structure + EMA trend + RSI + multi-timeframe + sentiment guards)
instead of relying on an LLM's ad-hoc output. Groq (ai_brain) is reduced to
an advisory "vote" via combine_with_ai(): it can confirm, temper, or veto the
deterministic signal, but the deterministic rules are the source of truth.

Self-improvement: pattern statistics from the SQLite trade history are applied
as scoring adjustments (e.g. avoid RSI buckets / sides that statistically lose
money). The bot therefore keeps adapting its analysis to what actually works,
while risk and confidence thresholds stay pinned to config.
"""
import config
import trade_logger
import learning_engine

# Sub-signal weights
W_STRUCTURE = 1.5
W_EMA_MACRO = 1.0
W_EMA_CROSS = 0.8
W_RSI_EXTREME = 0.6
W_RSI_DIVERGENCE = 0.8
W_TF = {"4h": 1.0, "1h": 0.8, "15m": 0.5}
W_TV = 1.5
W_NEWS = 0.5
W_FUNDING = 0.8

# Action triggers
LONG_SCORE = 1.5
SHORT_SCORE = -1.5

# Learning adjustment strength (self-improvement)
LEARN_SIDE_ADJUST = 0.4
LEARN_RSI_ADJUST = 0.5


def _tradingview_consensus(tradingview_data) -> float:
    """Averages per-timeframe TradingView ratings into a -1..+1 score."""
    tv = tradingview_data or {}
    consensus = str(tv.get("consensus", "")).upper()
    if not consensus:
        return None
    vals = []
    for part in consensus.split("|"):
        p = part.strip()
        if ":" in p:
            _, val = p.split(":", 1)
            val = val.strip().upper()
        else:
            val = p
        if val in ("STRONG_BUY", "BUY"):
            vals.append(1 if "STRONG" in val else 0.5)
        elif val in ("STRONG_SELL", "SELL"):
            vals.append(-1 if "STRONG" in val else -0.5)
        else:
            vals.append(0)
    return sum(vals) / len(vals) if vals else None


def _apply_learned_patterns(score: float) -> tuple:
    """
    Self-improvement: adjusts the score based on real trade outcomes.
    Uses only statistically meaningful buckets (>= 3 trades).
    """
    reasons = []
    try:
        closed = trade_logger.get_closed_trades(limit=50)
        if len(closed) < 5:
            return score, reasons
        patterns = learning_engine.analyze_patterns(closed)

        by_rsi = patterns.get("by_rsi", {})
        for key, data in by_rsi.items():
            if data["total"] >= 3 and data["win_rate"] <= 35 and data["avg_pnl"] < 0:
                if "aşırı satım" in key:
                    score -= LEARN_RSI_ADJUST
                    reasons.append(f"öğrenme: {key} zararlı, LONG baskısı azaltıldı")
                elif "aşırı alım" in key:
                    score += LEARN_RSI_ADJUST
                    reasons.append(f"öğrenme: {key} zararlı, SHORT baskısı azaltıldı")

        by_side = patterns.get("by_side", {})
        long_d = by_side.get("LONG")
        short_d = by_side.get("SHORT")
        if long_d and long_d["total"] >= 3 and long_d["avg_pnl"] < 0:
            score -= LEARN_SIDE_ADJUST
            reasons.append("öğrenme: LONG ortalamada zararlı")
        if short_d and short_d["total"] >= 3 and short_d["avg_pnl"] > 0:
            score += LEARN_SIDE_ADJUST
            reasons.append("öğrenme: SHORT ortalamada kârlı")
    except Exception as e:
        reasons.append(f"öğrenme hatası: {e}")
    return score, reasons


def _apply_vetoes(action: str, indicator_summary: dict, news_data: dict) -> str:
    """Hard rules that cannot be overridden. Returns a reason or None."""
    structure = str(indicator_summary.get("market_structure", "")).upper()
    rsi = indicator_summary.get("rsi_14")
    crash = indicator_summary.get("crash_alert", False)
    sent = float((news_data or {}).get("sentiment_score", 0.0) or 0.0)

    if crash:
        return "crash_alert aktif, işlem yasak"
    if action == "LONG" and "BEARISH_STRUCTURE" in structure and (rsi is None or rsi > 30):
        return "ayı yapısında LONG yasak (RSI>30)"
    if action == "SHORT" and "BULLISH_STRUCTURE" in structure and (rsi is None or rsi < 70):
        return "boğa yapısında SHORT yasak (RSI<70)"
    if action == "LONG" and sent <= -0.5:
        return "haber duyarlılığı çok bearish, LONG yasak"
    if action == "SHORT" and sent >= 0.5:
        return "haber duyarlılığı çok bullish, SHORT yasak"

    price = indicator_summary.get("current_price")
    resistance = indicator_summary.get("resistance_level")
    support = indicator_summary.get("support_level")
    if price and resistance and support:
        dist_res = abs(price - resistance) / price * 100
        dist_sup = abs(price - support) / price * 100
        if action == "LONG" and dist_res < 0.35:
            return f"direnç yakınında LONG yasak (${resistance:.0f})"
        if action == "SHORT" and dist_sup < 0.35:
            return f"destek yakınında SHORT yasak (${support:.0f})"
    return None


def evaluate(indicator_summary: dict, multiframe_data: dict = None,
             tradingview_data: dict = None, news_data: dict = None,
             derivatives_data: dict = None) -> dict:
    """
    Deterministic market analysis. Returns a signal dict:
    {action, confidence, reasoning, score, sl_multiplier_atr, tp_multiplier_atr}
    """
    score = 0.0
    reasons = []

    # 1. Market structure
    structure = str(indicator_summary.get("market_structure", "")).upper()
    if "BULLISH_STRUCTURE" in structure:
        score += W_STRUCTURE
        reasons.append("BULLISH yapı")
    elif "BEARISH_STRUCTURE" in structure:
        score -= W_STRUCTURE
        reasons.append("BEARISH yapı")
    else:
        reasons.append("Konsolidasyon")

    # 2. EMA macro trend (200)
    macro = str(indicator_summary.get("macro_trend_ema200", "")).upper()
    if macro == "BULLISH":
        score += W_EMA_MACRO
        reasons.append("EMA200 bullish")
    elif macro == "BEARISH":
        score -= W_EMA_MACRO
        reasons.append("EMA200 bearish")

    # 3. EMA cross (9/21)
    cross = str(indicator_summary.get("short_term_ema_cross", "")).upper()
    if cross == "BULLISH_CROSS":
        score += W_EMA_CROSS
        reasons.append("EMA9/21 bullish cross")
    elif cross == "BEARISH_CROSS":
        score -= W_EMA_CROSS
        reasons.append("EMA9/21 bearish cross")

    # 4. RSI
    rsi = indicator_summary.get("rsi_14")
    if rsi is not None:
        if rsi <= 30:
            score += W_RSI_EXTREME
            reasons.append(f"RSI {rsi:.0f} aşırı satım")
        elif rsi >= 70:
            score -= W_RSI_EXTREME
            reasons.append(f"RSI {rsi:.0f} aşırı alım")
        elif rsi < 40:
            score += 0.3
        elif rsi > 60:
            score -= 0.3

    # 5. RSI divergence
    div = indicator_summary.get("rsi_divergence", "NONE")
    if div == "BULLISH_DIVERGENCE":
        score += W_RSI_DIVERGENCE
        reasons.append("RSI boğa sapması")
    elif div == "BEARISH_DIVERGENCE":
        score -= W_RSI_DIVERGENCE
        reasons.append("RSI ayı sapması")

    # 6. Multi-timeframe trends
    mf = multiframe_data or {}
    for tf, w in W_TF.items():
        trend = str((mf.get(tf) or {}).get("trend", "")).upper()
        if trend == "BULLISH":
            score += w
            reasons.append(f"{tf} bullish")
        elif trend == "BEARISH":
            score -= w
            reasons.append(f"{tf} bearish")

    # 7. TradingView consensus
    tv_score = _tradingview_consensus(tradingview_data)
    if tv_score is not None:
        score += tv_score * W_TV
        if tv_score >= 0.5:
            reasons.append("TV multi-TF BUY")
        elif tv_score <= -0.5:
            reasons.append("TV multi-TF SELL")

    # 8. News sentiment (soft)
    sent = float((news_data or {}).get("sentiment_score", 0.0) or 0.0)
    if sent <= -0.3:
        score -= W_NEWS
        reasons.append("bearish haber")
    elif sent >= 0.3:
        score += W_NEWS
        reasons.append("bullish haber")

    # 9. Funding extreme fade
    funding_pct = float((derivatives_data or {}).get("funding_rate_pct", 0.0) or 0.0)
    if funding_pct >= 0.05:
        score -= W_FUNDING
        reasons.append("aşırı long fonlama")
    elif funding_pct <= -0.05:
        score += W_FUNDING
        reasons.append("aşırı short fonlama")

    # 10. Self-improvement from real trade outcomes
    score, learn_reasons = _apply_learned_patterns(score)
    reasons.extend(learn_reasons)

    # Entry gates: need at least one "major" confluence + aligned 4h
    mf_4h = str((mf.get("4h") or {}).get("trend", "")).upper()
    long_gate = (macro == "BULLISH" or "BULLISH_STRUCTURE" in structure) and mf_4h != "BEARISH"
    short_gate = (macro == "BEARISH" or "BEARISH_STRUCTURE" in structure) and mf_4h != "BULLISH"

    # Raw action from score + gates
    action = "HOLD"
    if score >= LONG_SCORE and long_gate:
        action = "LONG"
    elif score <= SHORT_SCORE and short_gate:
        action = "SHORT"
    if action == "HOLD" and (score >= LONG_SCORE or score <= SHORT_SCORE):
        reasons.append("giriş kapısı sağlanmadı (makro/yapı/4h uyumu yok)")

    # Hard vetoes
    veto_reason = _apply_vetoes(action, indicator_summary, news_data)
    if veto_reason:
        action = "HOLD"
        reasons.append(f"VETO: {veto_reason}")

    # Confidence
    if action == "HOLD":
        confidence = 0
    else:
        confidence = min(int(60 + (abs(score) - 1.0) * 40), 95)

    reasoning = " | ".join(reasons) if reasons else "Yeterli koşul yok"
    return {
        "action": action,
        "confidence": max(confidence, 0),
        "reasoning": f"[Strateji] {reasoning} (score {score:+.1f})",
        "score": round(score, 2),
        "sl_multiplier_atr": config.ATR_SL_MULTIPLIER,
        "tp_multiplier_atr": config.ATR_TP_MULTIPLIER,
        "deterministic": True,
        "fallback": True,
    }


def combine_with_ai(strategy_signal: dict, ai_vote: dict = None) -> dict:
    """
    Groq is an advisory vote. The deterministic signal stays primary:
    - same direction  -> confirm, +10 confidence
    - AI HOLD         -> -10 confidence; below threshold -> HOLD
    - opposite vote   -> veto (HOLD) only if AI is itself confident
    - strategy HOLD   -> HOLD regardless of AI
    """
    result = dict(strategy_signal)
    strat_action = result["action"]
    strat_conf = result["confidence"]

    if not ai_vote or not ai_vote.get("action"):
        result["confidence"] = min(strat_conf, config.CONFIDENCE_THRESHOLD)
        result["reasoning"] = f"{result['reasoning']} | AI erişilemedi, deterministik sinyal korundu"
        return result

    ai_action = str(ai_vote.get("action", "HOLD")).upper()
    ai_conf = int(ai_vote.get("confidence", 0) or 0)

    if strat_action == "HOLD":
        result["reasoning"] = f"{result['reasoning']} | AI oy: {ai_action} (%{ai_conf})"
        return result

    if ai_action == strat_action:
        result["confidence"] = min(95, strat_conf + 10)
        result["reasoning"] = f"{result['reasoning']} | AI onayladı (%{ai_conf})"
    elif ai_action == "HOLD":
        result["confidence"] = max(0, strat_conf - 10)
        result["reasoning"] = f"{result['reasoning']} | AI nötr (%{ai_conf})"
        if result["confidence"] < config.CONFIDENCE_THRESHOLD:
            result["action"] = "HOLD"
            result["reasoning"] += " → eşik altı, HOLD"
    else:
        if ai_conf >= config.CONFIDENCE_THRESHOLD:
            result["action"] = "HOLD"
            result["reasoning"] = f"{result['reasoning']} | AI zıt oy (%{ai_conf}) → HOLD veto"
        else:
            result["confidence"] = max(0, strat_conf - 5)
            result["reasoning"] = f"{result['reasoning']} | AI zıt ama düşük güven (%{ai_conf}), sinyal korundu"
    return result
