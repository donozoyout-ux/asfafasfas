import json
import re
import time
import requests
import config
import trade_logger
import learning_engine

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Rate-limit throttle: at most one AI call every N seconds to avoid burning the
# daily Groq token budget (100K/day on free tier). A 429 (rate limit) forces a
# long cooldown so the bot doesn't keep hammering a saturated API.
MIN_CALL_INTERVAL_SECONDS = 60
RATE_LIMIT_COOLDOWN_SECONDS = 1800  # 30 min after a 429

_last_call_time = 0.0
_cooldown_until = 0.0

SYSTEM_PROMPT = """You are a World-Class Master Cryptocurrency Quantitative Trader managing an automated Futures & Portfolio strategy on Binance, focused strictly on BITCOIN (BTC).
Your primary directive is to achieve consistent daily capital growth of 0.5% to 1.0% with STRICT risk management, protecting against sudden dumps, and achieving long-term profitability.

You evaluate market data based on 4 Core Quantitative Pillars:
1. Multi-Timeframe Alignment (15m Execution + 1h & 4h Macro Trend):
   - High conviction LONG requires 1h or 4h macro trend support or oversold bounce at key support.
   - High conviction SHORT requires macro bearish structure or breakdown below key support.
2. Market Structure & Support/Resistance Zones:
   - Identify if price is holding Key Support or breaking Resistance.
   - Do NOT buy directly into strong Resistance or short directly into major Support.
3. Technical Indicators (RSI, EMA 9/21/200, ATR, Bollinger Bands):
   - RSI Divergence (Bullish/Bearish) acts as strong reversal confirmation.
4. Sudden Crash & Flash Dip Protection:
   - If Crash Alert is ACTIVE, prioritize capital preservation (HOLD or quick defensive exit).
5. News Sentiment & Derivatives Speculation Guard:
   - NEVER chase pumps or dump into panic driven by news manipulation or forced liquidations.
   - If NEWS SENTIMENT is strongly BEARISH (score <= -0.5), VETO LONG entries (capital preservation).
   - If funding rate is EXTREME positive (> 0.05%) the crowd is over-leveraged LONG -> favor SHORT/avoid LONG. If EXTREME negative (< -0.05%) crowd is over-leveraged SHORT -> favor LONG/avoid SHORT.
   - Rapid Open Interest spike (+5%+ 24h) with weak price action = liquidation risk; stay cautious, prefer HOLD.

IN-CONTEXT SELF-LEARNING DIRECTIVE:
You have continuous memory of your recent trade outcomes. Analyze past trade performance (wins and losses). Adapt your thresholds dynamically to avoid repeating past mistakes.

CRITICAL INSTRUCTIONS:
- Return ONLY a valid, raw JSON object (NO markdown, NO code block ticks ```json, NO extra text).
- Action MUST be "LONG", "SHORT", or "HOLD".
- Require high conviction (confidence >= 60%) to recommend LONG or SHORT. Otherwise output HOLD.
- If recommending LONG or SHORT, provide dynamic ATR multipliers for Stop-Loss (e.g. 1.2 to 2.0) and Take-Profit (e.g. 2.0 to 3.5) ensuring Risk-Reward Ratio >= 1:1.5.

JSON Output Schema:
{
  "action": "LONG" | "SHORT" | "HOLD",
  "confidence": integer 0 to 100,
  "reasoning": "Concise technical rationale in Turkish (max 2 sentences)",
  "sl_multiplier_atr": float (1.0 to 2.5),
  "tp_multiplier_atr": float (1.5 to 4.0)
}
"""

def analyze_market_with_ai(indicator_summary: dict, ticker_24h: dict, multiframe_data: dict = None, tradingview_data: dict = None, current_position: str = "FLAT", news_data: dict = None, derivatives_data: dict = None) -> dict:
    """
    Sends technical data + TradingView TA ratings + support/resistance + market structure + past trade performance memory
    to Groq Llama-3.3-70b and receives self-adapting trading signal JSON.
    """
    global _last_call_time, _cooldown_until

    # Throttle: respect rate-limit cooldown and min call interval.
    now = time.time()
    if now < _cooldown_until:
        return {"action": "HOLD", "confidence": 0, "reasoning": "Groq rate-limit cooldown"}
    if now - _last_call_time < MIN_CALL_INTERVAL_SECONDS:
        return {"action": "HOLD", "confidence": 0, "reasoning": "Groq call throttled (rate-limit protection)"}
    _last_call_time = now

    learning_memory = learning_engine.build_learning_context(limit=6)
    mf_str = json.dumps(multiframe_data) if multiframe_data else "15m: ACTIVE, 1h: BULLISH, 4h: BULLISH"
    tv_str = json.dumps(tradingview_data) if tradingview_data else "TradingView: N/A"

    if news_data:
        fng = news_data.get("fear_greed_index")
        fng_str = f" (F&G Index: {fng}/{news_data.get('fear_greed_label', '')})" if fng is not None else ""
        news_str = (
            f"- Sentiment Score: {news_data.get('sentiment_score', 0.0)} "
            f"({news_data.get('sentiment_label', 'NEUTRAL')}){fng_str}\n"
            f"- Top Headlines: {json.dumps(news_data.get('top_headlines', []))}\n"
            f"- Rule: score <= -0.5 (BEARISH) vetoes LONG. "
            f"F&G <= 25 = EXTREME FEAR (oversold zone - be cautious of catching knife, but no chase). "
            f"Do NOT buy into fear-driven dumps or chase speculative pumps."
        )
    else:
        news_str = "- News data unavailable. Proceed on technicals only."

    if derivatives_data:
        funding_pct = derivatives_data.get("funding_rate_pct", 0.0)
        oi = derivatives_data.get("open_interest", 0.0)
        deriv_str = (
            f"- Funding Rate: {derivatives_data.get('funding_rate', 0.0)} "
            f"({funding_pct}%)\n"
            f"- Open Interest: {oi} BTC\n"
            f"- Rule: |funding| >= 0.05% = extreme leverage crowd -> fade direction. "
            f"OI spike + weak price = liquidation risk -> prefer HOLD."
        )
    else:
        deriv_str = "- Derivatives data unavailable."
    
    # Dynamic confidence threshold from learning engine adaptation
    try:
        closed = trade_logger.get_closed_trades(limit=10)
        adaptation = learning_engine.compute_adaptation(closed)
        dyn_threshold = adaptation["confidence_threshold"]
        dyn_risk = adaptation["risk_per_trade_pct"]
    except Exception:
        dyn_threshold = config.CONFIDENCE_THRESHOLD
        dyn_risk = config.RISK_PER_TRADE_PCT * 100
    
    user_prompt = f"""
ANALYZE MARKET STATE FOR {config.SYMBOL}:

[CURRENT ADAPTIVE STRATEGY]
- Confidence Threshold To Execute: >= {dyn_threshold}% (dynamically learned)
- Risk Per Trade: {dyn_risk}% of account (includes 0.10% roundtrip fees)
- Only LONG/SHORT if confidence >= {dyn_threshold}%. Otherwise HOLD.

[MARKET SNAPSHOT & CRASH STATUS]
- Current Mark Price: ${indicator_summary['current_price']}
- 24h Change: {ticker_24h.get('price_change_pct', 0)}%
- Active Bot Position: {current_position}
- Crash Alert Status: {indicator_summary.get('crash_alert', False)} ({indicator_summary.get('crash_message', 'Normal')})

[TRADINGVIEW OFFICIAL TECHNICAL ANALYSIS RATINGS]
{tv_str}

[MARKET STRUCTURE & ZONES]
- Support Level: ${indicator_summary.get('support_level', 0)}
- Resistance Level: ${indicator_summary.get('resistance_level', 0)}
- Market Structure: {indicator_summary.get('market_structure', 'N/A')}

[MULTI-TIMEFRAME ALIGNMENT (15m / 1h / 4h)]
{mf_str}

[TECHNICAL INDICATORS SUMMARY]
1. Momentum (RSI 14):
   - RSI Value: {indicator_summary['rsi_14']} ({indicator_summary['rsi_status']})
   - Divergence Signal: {indicator_summary['rsi_divergence']}

2. Trend Alignment (EMAs):
   - EMA 9: ${indicator_summary['ema_9']}
   - EMA 21: ${indicator_summary['ema_21']}
   - EMA 200: ${indicator_summary['ema_200']}
   - Macro Trend (EMA 200): {indicator_summary['macro_trend_ema200']}
   - Short-Term Cross (EMA 9/21): {indicator_summary['short_term_ema_cross']}

3. Volatility & Bands (ATR & Bollinger):
   - ATR (14): ${indicator_summary['atr_14']}
   - Bollinger Bands: Upper ${indicator_summary['bb_upper']} | Lower ${indicator_summary['bb_lower']}
   - BB Percent %B: {indicator_summary['bb_percent_b']}

[NEWS SENTIMENT]
{news_str}

[DERIVATIVES / SPECULATION METRICS]
{deriv_str}

[SELF-LEARNING MEMORY FEEDBACK]
{learning_memory}

Evaluate if there is a high-probability trade opportunity to reach our 0.5%-1% daily growth target while preserving capital. Return raw JSON.
"""

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 250
    }

    try:
        res = requests.post(GROQ_URL, json=payload, headers=headers, timeout=12)
        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()
                
            ai_data = json.loads(content)
            return ai_data
        else:
            print(f"[ERROR] Groq API returned {res.status_code}: {res.text}")
            if res.status_code == 429:
                # Use the reset time from Groq's message if present ("try again in 2m24.288s"),
                # otherwise fall back to a long fixed cooldown.
                m = re.search(r"try again in ([\d.]+)m([\d.]+)?s", res.text)
                if m:
                    minutes = float(m.group(1))
                    seconds = float(m.group(2)) if m.group(2) else 0.0
                    _cooldown_until = time.time() + minutes * 60 + seconds + 60
                    print(f"[RATE-LIMIT] AI throttled for {minutes:.0f}m{seconds:.0f}s + 60s buffer")
                else:
                    _cooldown_until = time.time() + RATE_LIMIT_COOLDOWN_SECONDS
                    print(f"[RATE-LIMIT] AI throttled for {RATE_LIMIT_COOLDOWN_SECONDS}s")
            return {"action": "HOLD", "confidence": 0, "reasoning": f"Groq HTTP Error {res.status_code}"}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse JSON from Groq output: {e}")
        return {"action": "HOLD", "confidence": 0, "reasoning": "JSON parse error"}
    except Exception as e:
        print(f"[EXCEPT] Groq AI analysis failed: {e}")
        return {"action": "HOLD", "confidence": 0, "reasoning": str(e)}


def is_rate_limited(result: dict) -> bool:
    """True if the AI result came from a rate-limit/cooldown failure."""
    reason = str(result.get("reasoning", ""))
    return result.get("action") == "HOLD" and any(
        token in reason.lower()
        for token in ("rate-limit", "throttled", "429", "http error")
    )


def get_fallback_signal(indicator_summary: dict, tradingview_data: dict = None,
                        news_data: dict = None, derivatives_data: dict = None,
                        multiframe_data: dict = None,
                        current_position: str = "FLAT") -> dict:
    """Rule-based trading signal used when Groq is rate-limited.

    Combines TradingView TA consensus across timeframes, multi-timeframe EMA
    trend, RSI, news sentiment and funding rate into a LONG / SHORT / HOLD
    decision with a confidence score.
    """
    action = "HOLD"
    confidence = 0
    score = 0  # positive = long bias, negative = short bias
    reasons = []

    # Multi-timeframe EMA trend (1h and 4h macro weigh more than 15m)
    mf = multiframe_data or {}
    for tf, weight in (("4h", 1.0), ("1h", 0.8), ("15m", 0.5)):
        entry = mf.get(tf) or {}
        trend = str(entry.get("trend", "")).upper()
        if trend == "BULLISH":
            score += weight
            reasons.append(f"{tf} bullish")
        elif trend == "BEARISH":
            score -= weight
            reasons.append(f"{tf} bearish")

    tv = tradingview_data or {}
    consensus = str(tv.get("consensus", "")).upper()
    # consensus can look like "15m: BUY | 1h: BUY | 4h: BUY"
    tf_scores = []
    for part in consensus.split("|"):
        p = part.strip()
        if ":" in p:
            _, val = p.split(":", 1)
            val = val.strip().upper()
        else:
            val = p
        if val in ("STRONG_BUY", "BUY"):
            tf_scores.append(1 if "STRONG" in val else 0.5)
        elif val in ("STRONG_SELL", "SELL"):
            tf_scores.append(-1 if "STRONG" in val else -0.5)
        else:
            tf_scores.append(0)
    if tf_scores:
        avg_tf = sum(tf_scores) / len(tf_scores)
        score += avg_tf * 1.5
        if avg_tf >= 0.5:
            reasons.append("TradingView multi-TF BUY")
        elif avg_tf <= -0.5:
            reasons.append("TradingView multi-TF SELL")

    rsi = indicator_summary.get("rsi_14")
    if rsi is not None:
        if rsi <= 30:
            score += 1.0
            reasons.append(f"RSI {rsi:.0f} oversold")
        elif rsi >= 70:
            score -= 1.0
            reasons.append(f"RSI {rsi:.0f} overbought")
        elif rsi < 40:
            score += 0.3
        elif rsi > 60:
            score -= 0.3

    # News sentiment guard
    if news_data:
        sent = float(news_data.get("sentiment_score", 0.0) or 0.0)
        if sent <= -0.5:
            score -= 1.0
            reasons.append("BEARISH news veto")
        elif sent >= 0.5:
            score += 0.5
            reasons.append("BULLISH news")

    # Funding extreme guard
    if derivatives_data:
        funding_pct = float(derivatives_data.get("funding_rate_pct", 0.0) or 0.0)
        if funding_pct >= 0.05:
            score -= 0.8
            reasons.append("extreme long funding")
        elif funding_pct <= -0.05:
            score += 0.8
            reasons.append("extreme short funding")

    # Compute raw action from score
    if score >= 1.0:
        action = "LONG"
    elif score <= -1.0:
        action = "SHORT"

    # Support / Resistance filter: do NOT buy into strong resistance, do NOT
    # short directly into major support (bad risk/reward).
    price = indicator_summary.get("current_price")
    resistance = indicator_summary.get("resistance_level")
    support = indicator_summary.get("support_level")
    sr_veto = False
    if price and resistance and support:
        dist_to_res = abs(price - resistance) / price * 100 if price else 999
        dist_to_sup = abs(price - support) / price * 100 if price else 999
        if action == "LONG" and dist_to_res < 0.35:
            action = "HOLD"
            sr_veto = True
            reasons.append(f"near resistance ${resistance:.0f} (LONG veto)")
        elif action == "SHORT" and dist_to_sup < 0.35:
            action = "HOLD"
            sr_veto = True
            reasons.append(f"near support ${support:.0f} (SHORT veto)")

    confidence = min(int(abs(score) * 50), 100)
    confidence = max(confidence, 10)  # at least show a signal exists

    if not reasons:
        reasons.append("No strong setup")

    reasoning = (f"[Fallback] {' | '.join(reasons)} (score {score:+.1f}). "
                 f"Groq AI rate-limited, using rule-based signal.")
    return {
        "action": action,
        "confidence": confidence,
        "reasoning": reasoning,
        "sl_multiplier_atr": config.ATR_SL_MULTIPLIER,
        "tp_multiplier_atr": config.ATR_TP_MULTIPLIER,
        "fallback": True,
    }

