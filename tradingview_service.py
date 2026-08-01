from tradingview_ta import TA_Handler, Interval, Exchange
import config

def fetch_tradingview_analysis(symbol: str = "BTCUSDT", exchange: str = "BINANCE") -> dict:
    """
    Fetches official TradingView Technical Analysis summary, Oscillators rating,
    and Moving Averages rating across 15m, 1h, and 4h intervals.
    """
    timeframes = {
        "15m": Interval.INTERVAL_15_MINUTES,
        "1h": Interval.INTERVAL_1_HOUR,
        "4h": Interval.INTERVAL_4_HOURS,
    }
    
    results = {}
    
    for tf_label, interval in timeframes.items():
        try:
            handler = TA_Handler(
                symbol=symbol,
                exchange=exchange,
                screener="crypto",
                interval=interval
            )
            analysis = handler.get_analysis()
            summary = analysis.summary
            
            results[tf_label] = {
                "recommendation": summary.get("RECOMMENDATION", "NEUTRAL"),
                "buy_count": summary.get("BUY", 0),
                "sell_count": summary.get("SELL", 0),
                "neutral_count": summary.get("NEUTRAL", 0),
                "oscillators": analysis.oscillators.get("RECOMMENDATION", "NEUTRAL"),
                "moving_averages": analysis.moving_averages.get("RECOMMENDATION", "NEUTRAL")
            }
        except Exception as e:
            print(f"[EXCEPT] TradingView TA Error ({tf_label}): {e}")
            results[tf_label] = {
                "recommendation": "NEUTRAL",
                "buy_count": 0,
                "sell_count": 0,
                "neutral_count": 0,
                "oscillators": "NEUTRAL",
                "moving_averages": "NEUTRAL"
            }
            
    # Calculate overall consensus
    rec_15m = results.get("15m", {}).get("recommendation", "NEUTRAL")
    rec_1h = results.get("1h", {}).get("recommendation", "NEUTRAL")
    rec_4h = results.get("4h", {}).get("recommendation", "NEUTRAL")
    
    results["consensus"] = f"15m: {rec_15m} | 1h: {rec_1h} | 4h: {rec_4h}"
    return results
