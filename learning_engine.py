"""
Learning Engine - The bot's brain for self-improvement.

Analyzes past trade outcomes, identifies winning/losing patterns,
and produces lessons that get injected into the AI prompt. The bot
learns from its mistakes just like a human trader: it remembers what
conditions led to wins and losses, then adapts its behavior.
"""
import json
import os
import trade_logger

_DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
LEARNING_STATE_PATH = os.path.join(_DATA_DIR, "learning_state.json")


def _load_state() -> dict:
    """Loads persistent learning state from disk."""
    try:
        with open(LEARNING_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "lesson_history": [],
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            "last_confidence_adjustment": 0.0,
            "last_risk_adjustment": 0.0,
        }


def _save_state(state: dict):
    """Persists learning state to disk."""
    try:
        with open(LEARNING_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[LEARN] State save error: {e}")


def _bucket_rsi(rsi: float) -> str:
    """Groups RSI values into meaningful buckets for pattern analysis."""
    if rsi >= 70:
        return "RSI>=70 (aşırı alım)"
    elif rsi >= 60:
        return "RSI 60-70 (güçlü)"
    elif rsi >= 55:
        return "RSI 55-60 (yükseliş) "
    elif rsi >= 45:
        return "RSI 45-55 (nötr)"
    elif rsi >= 30:
        return "RSI 30-45 (düşüş)"
    else:
        return "RSI<30 (aşırı satım)"


def analyze_patterns(closed_trades: list) -> dict:
    """
    Analyzes closed trades and returns pattern stats per condition:
    - win rate per market structure
    - win rate per RSI bucket
    - win rate per multi-timeframe trend
    - win rate per side (LONG vs SHORT)
    - average hold time
    """
    result = {
        "by_side": {},
        "by_structure": {},
        "by_rsi": {},
        "by_multiframe": {},
        "by_rsi_status": {},
        "hold_time_avg_win": 0,
        "hold_time_avg_loss": 0,
    }

    if not closed_trades:
        return result

    def add_bucket(bucket: dict, key: str, won: bool, pnl: float):
        if key not in bucket:
            bucket[key] = {"total": 0, "wins": 0, "pnl": 0.0}
        bucket[key]["total"] += 1
        bucket[key]["wins"] += 1 if won else 0
        bucket[key]["pnl"] += pnl

    hold_win = []
    hold_loss = []

    for t in closed_trades:
        won = t["status"] == "WIN"
        pnl = t.get("pnl_usdt", 0) or 0
        add_bucket(result["by_side"], t["side"], won, pnl)
        add_bucket(result["by_structure"], t.get("market_structure") or "UNKNOWN", won, pnl)
        add_bucket(result["by_rsi"], _bucket_rsi(t.get("rsi_val", 50)), won, pnl)
        add_bucket(result["by_multiframe"], t.get("multiframe_trend") or "MIXED", won, pnl)
        add_bucket(result["by_rsi_status"], t.get("rsi_status") or "NEUTRAL", won, pnl)
        if won:
            hold_win.append(t.get("hold_time_min", 0))
        else:
            hold_loss.append(t.get("hold_time_min", 0))

    def finalize(bucket: dict):
        for key, data in bucket.items():
            if data["total"] > 0:
                data["win_rate"] = round(data["wins"] / data["total"] * 100, 1)
                data["avg_pnl"] = round(data["pnl"] / data["total"], 2)
            else:
                data["win_rate"] = 0.0
                data["avg_pnl"] = 0.0
        return bucket

    for k in ["by_side", "by_structure", "by_rsi", "by_multiframe", "by_rsi_status"]:
        result[k] = finalize(result[k])

    result["hold_time_avg_win"] = round(sum(hold_win) / len(hold_win), 1) if hold_win else 0
    result["hold_time_avg_loss"] = round(sum(hold_loss) / len(hold_loss), 1) if hold_loss else 0
    return result


def generate_lessons(patterns: dict) -> list:
    """
    Produces actionable lessons from pattern analysis.
    E.g. "RSI>=70 ile SHORT işlemlerde %20 kazanma oranı - bu koşuldan kaçın."
    """
    lessons = []

    def analyze_bucket(bucket: dict, condition_name: str):
        for key, data in sorted(bucket.items(), key=lambda x: x[1]["total"], reverse=True):
            if data["total"] < 3:  # Require at least 3 trades for statistical significance (was 2)
                continue
            if data["win_rate"] >= 60:
                lessons.append(
                    f"🟢 {condition_name} '{key}': %{data['win_rate']} kazanma oranı "
                    f"({data['total']} işlem, ort PnL ${data['avg_pnl']:+.2f}) → Bu koşulda işlem açma eğilimini artır."
                )
            elif data["win_rate"] <= 35:
                lessons.append(
                    f"🔴 {condition_name} '{key}': %{data['win_rate']} kazanma oranı "
                    f"({data['total']} işlem, ort PnL ${data['avg_pnl']:+.2f}) → Bu koşuldan KAÇIN, sinyal gelse bile açma."
                )

    analyze_bucket(patterns.get("by_side", {}), "Yön")
    analyze_bucket(patterns.get("by_structure", {}), "Market Yapısı")
    analyze_bucket(patterns.get("by_rsi", {}), "RSI")
    analyze_bucket(patterns.get("by_multiframe", {}), "Çoklu Zaman Dilimi")
    analyze_bucket(patterns.get("by_rsi_status", {}), "RSI Durumu")

    return lessons


def compute_adaptation(closed_trades: list) -> dict:
    """
    Computes adaptive strategy adjustments based on recent performance:
    - If consecutive losses mount, raise confidence threshold + reduce risk.
    - If winning streak, keep risk steady but allow slightly lower confidence.
    """
    state = _load_state()
    summary = trade_logger.get_performance_summary()

    recents = closed_trades[:20]  # Use last 20 trades for streak calculation (was 10)
    if recents:
        # Update streaks
        streak = 0
        streak_type = None
        for t in recents:
            if streak_type is None:
                streak_type = "WIN" if t["status"] == "WIN" else "LOSS"
                streak = 1
            elif t["status"] == streak_type:
                streak += 1
            else:
                break
        if streak_type == "WIN":
            state["consecutive_wins"] = streak
            state["consecutive_losses"] = 0
        else:
            state["consecutive_losses"] = streak
            state["consecutive_wins"] = 0

    base_confidence = 60.0
    base_risk = 0.02  # 2% risk per trade

    # Adapt confidence threshold
    if state["consecutive_losses"] >= 3:
        confidence = min(base_confidence + state["consecutive_losses"] * 3, 75)
    elif state["consecutive_wins"] >= 3:
        confidence = max(base_confidence - (state["consecutive_wins"] - 2) * 2, 50)
    else:
        confidence = base_confidence

    # Adapt risk per trade
    if state["consecutive_losses"] >= 2:
        risk = max(base_risk - state["consecutive_losses"] * 0.003, 0.005)  # Min 0.5%
    else:
        risk = base_risk

    # Roundtrip fee must be recovered
    fee_rate = 0.001  # 0.10% roundtrip

    adaptation = {
        "confidence_threshold": round(confidence, 1),
        "risk_per_trade_pct": round(risk * 100, 2),
        "consecutive_wins": state["consecutive_wins"],
        "consecutive_losses": state["consecutive_losses"],
        "total_trades": summary["total_trades"],
        "win_rate": summary["win_rate_pct"],
        "total_pnl": summary["total_pnl_usdt"],
        "fee_recovery_note": f"Her işlemde %{fee_rate*100:.2f} komisyon geri kazanılmalı; "
                             f"bu yüzden net kâr < %0.10 ise işlem kârsız sayılır.",
    }
    _save_state(state)
    return adaptation


def build_learning_context(limit: int = 6) -> str:
    """
    Builds a rich, human-like learning context for the AI prompt:
    recent trades + pattern lessons + adaptive strategy state.
    """
    closed = trade_logger.get_closed_trades(limit=limit)
    if not closed:
        return ("HENÜZ TAMAMLANMIŞ İŞLEM YOK. Temel teknik disiplinle başla. "
                "Risk parametreleri: varsayılan güven eşiği %60, işlem başına risk %2.")

    patterns = analyze_patterns(closed)
    lessons = generate_lessons(patterns)
    adaptation = compute_adaptation(closed)

    lines = [f"SON {len(closed)} İŞLEM SONUCU (öğrenme verisi):"]
    for t in closed:
        icon = "✅ KAZANÇ" if t["status"] == "WIN" else "❌ KAYIP"
        lines.append(
            f"- #{t['id']} {t['side']} @ ${t['entry_price']:.2f} → {icon} ${t.get('pnl_usdt', 0):+.2f} "
            f"| RSI {t.get('rsi_val', 0)} [{t.get('rsi_status', '?')}] | {t.get('ema200_trend', '?')} "
            f"| Yapı: {t.get('market_structure', '?')} | MF: {t.get('multiframe_trend', '?')} "
            f"| Tutma: {t.get('hold_time_min', 0)}dk"
        )

    if lessons:
        lines.append("\nÖĞRENİLEN DERSLER:")
        lines.extend(lessons)

    lines.append(f"\nUYARLANMIŞ STRATEJİ:")
    lines.append(f"- Güven eşiği: %{adaptation['confidence_threshold']} "
                 f"(seri: {adaptation['consecutive_wins']}W/{adaptation['consecutive_losses']}L)")
    lines.append(f"- İşlem başına risk: %{adaptation['risk_per_trade_pct']}")
    lines.append(f"- Genel: {adaptation['total_trades']} işlem, %{adaptation['win_rate']} kazanma oranı, "
                 f"toplam PnL ${adaptation['total_pnl']:+.2f}")
    lines.append(f"- {adaptation['fee_recovery_note']}")
    lines.append("\nSELF-LEARNING DIRECTIVE: Kazanan senaryoları tekrarla, kaybedenlerden kaçın. "
                 "Ayarlanan güven eşiğine göre karar ver.")
    return "\n".join(lines)


def format_learning_report() -> str:
    """Formats a human-readable learning report for Telegram (/learn)."""
    closed = trade_logger.get_closed_trades(limit=50)
    if not closed:
        return "🧠 *ÖĞRENME DURUMU*\n\nHenüz yeterli işlem verisi yok. Bot hâlâ öğreniyor. 🐣"

    patterns = analyze_patterns(closed)
    lessons = generate_lessons(patterns)
    adaptation = compute_adaptation(closed)
    summary = trade_logger.get_performance_summary()

    lines = [
        f"🧠 *BOT ÖĞRENME RAPORU*\n",
        f"📊 *Genel Performans:*\n"
        f"• İşlem: {summary['total_trades']} | Kazanç: 🟢 {summary['wins']} | Kayıp: 🔴 {summary['losses']}\n"
        f"• Win Rate: %{summary['win_rate_pct']} | Toplam PnL: ${summary['total_pnl_usdt']:+.2f}\n",
        f"🧬 *Uyarlanmış Strateji:*\n"
        f"• Güven Eşiği: %{adaptation['confidence_threshold']}\n"
        f"• İşlem Başına Risk: %{adaptation['risk_per_trade_pct']}\n"
        f"• Seri: {adaptation['consecutive_wins']}W / {adaptation['consecutive_losses']}L\n",
    ]

    if lessons:
        lines.append(f"🎓 *Öğrenilen Dersler:*")
        lines.extend([f"• {l}" for l in lessons[:6]])

    return "\n".join(lines)
