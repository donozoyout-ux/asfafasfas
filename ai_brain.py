import json
import requests
import config
import trade_logger

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a World-Class Master Cryptocurrency Quantitative Trader managing an automated Futures portfolio on Binance.
Your primary directive is to achieve consistent daily capital growth of 0.5% to 1.0% with STRICT risk management and ZERO emotional bias.

You evaluate market data based on 3 Core Indicators:
1. RSI (14) & Divergence: Momentum, Overbought/Oversold levels, and trend reversal/continuation signals.
2. EMA Trend System (EMA 9, EMA 21, EMA 200): Macro trend direction filter (EMA 200) and short-term execution crosses (EMA 9/21).
   - RULE: DO NOT open LONG if price is significantly below EMA 200 unless there is a strong Bullish RSI Divergence.
   - RULE: DO NOT open SHORT if price is significantly above EMA 200 unless there is a strong Bearish RSI Divergence.
3. ATR (14) & Bollinger Bands: Dynamic volatility assessment for dynamic Stop-Loss & Take-Profit placement.

IN-CONTEXT SELF-LEARNING DIRECTIVE:
You have continuous memory of your recent trade outcomes. Analyze past trade performance (wins and losses). Adapt your thresholds dynamically to avoid repeating past mistakes while reinforcing winning patterns.

CRITICAL INSTRUCTIONS:
- Return ONLY a valid, raw JSON object (NO markdown, NO code block ticks ```json, NO extra text).
- Action MUST be "LONG", "SHORT", or "HOLD".
- Require high conviction (confidence >= 70%) to recommend LONG or SHORT. Otherwise output HOLD.
- If recommending LONG or SHORT, provide dynamic ATR multipliers for Stop-Loss (e.g. 1.2 to 2.0) and Take-Profit (e.g. 2.0 to 3.5) ensuring Risk-Reward Ratio >= 1:1.5.

JSON Output Schema:
{
  "action": "LONG" | "SHORT" | "HOLD",
  "confidence": integer 0 to 100,
  "reasoning": "Concise technical rationale (max 2 sentences in Turkish)",
  "sl_multiplier_atr": float (1.0 to 2.5),
  "tp_multiplier_atr": float (1.5 to 4.0)
}
"""

def analyze_market_with_ai(indicator_summary: dict, ticker_24h: dict, current_position: str = "FLAT") -> dict:
    """
    Sends technical data + past trade performance memory to Groq Llama-3.3-70b
    and receives self-adapting trading signal JSON.
    """
    learning_memory = trade_logger.get_ai_learning_context(limit=5)
    
    user_prompt = f"""
ANALYZE MARKET STATE FOR {config.SYMBOL} ({config.TIMEFRAME} Timeframe):

[MARKET SNAPSHOT]
- Current Mark Price: ${indicator_summary['current_price']}
- 24h Change: {ticker_24h.get('price_change_pct', 0)}%
- Active Bot Position: {current_position}

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
   - BB Percent %B: {indicator_summary['bb_percent_b']} (Squeeze/Expansion indicator)

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
