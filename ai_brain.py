import json
import requests
import config
import trade_logger
import learning_engine

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

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

def analyze_market_with_ai(indicator_summary: dict, ticker_24h: dict, multiframe_data: dict = None, tradingview_data: dict = None, current_position: str = "FLAT") -> dict:
    """
    Sends technical data + TradingView TA ratings + support/resistance + market structure + past trade performance memory
    to Groq Llama-3.3-70b and receives self-adapting trading signal JSON.
    """
    learning_memory = learning_engine.build_learning_context(limit=6)
    mf_str = json.dumps(multiframe_data) if multiframe_data else "15m: ACTIVE, 1h: BULLISH, 4h: BULLISH"
    tv_str = json.dumps(tradingview_data) if tradingview_data else "TradingView: N/A"
    
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
            return {"action": "HOLD", "confidence": 0, "reasoning": f"Groq HTTP Error {res.status_code}"}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse JSON from Groq output: {e}")
        return {"action": "HOLD", "confidence": 0, "reasoning": "JSON parse error"}
    except Exception as e:
        print(f"[EXCEPT] Groq AI analysis failed: {e}")
        return {"action": "HOLD", "confidence": 0, "reasoning": str(e)}

