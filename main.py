import sys
import io
import time
import argparse
import os
import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import config
import market_data
import indicators
import ai_brain
import trade_logger
import tradingview_service
import learning_engine
import news_service
import settings
import sheets_exporter
import strategy
from risk_manager import RiskManager
from execution import BinanceFuturesExecutor
from telegram_bot import TelegramNotifier

RENDER_PORT = int(os.getenv("PORT", "8000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")

# Global reference to BotController for HTTP API handlers
bot_instance = None

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress HTTP server verbose logs

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(load_dashboard_html().encode("utf-8"))

        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            status_data = bot_instance.get_dashboard_state() if bot_instance else {}
            self.wfile.write(json.dumps(status_data).encode("utf-8"))

        elif self.path == "/api/trades":
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            trades = trade_logger.get_recent_trades(limit=20)
            self.wfile.write(json.dumps(trades).encode("utf-8"))

        elif self.path.startswith("/api/reports/"):
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.end_headers()
            report_type = self.path.split("/api/reports/")[-1]
            if bot_instance:
                if report_type == "risk":
                    payload = bot_instance.get_risk_report()
                elif report_type == "performance":
                    payload = bot_instance.get_performance_report()
                elif report_type == "learning":
                    payload = bot_instance.get_learning_report()
                else:
                    payload = {"error": f"Bilinmeyen rapor: {report_type}"}
            else:
                payload = {"error": "Bot hazır değil"}
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif self.path.startswith("/static/"):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            rel = self.path.lstrip("/").replace("/", os.sep)
            file_path = os.path.normpath(os.path.join(base_dir, rel))
            if not file_path.startswith(base_dir) or not os.path.isfile(file_path):
                self.send_response(404)
                self.end_headers()
                return
            if file_path.endswith(".js"):
                content_type = "application/javascript; charset=utf-8"
            elif file_path.endswith(".css"):
                content_type = "text/css; charset=utf-8"
            else:
                content_type = "application/octet-stream"
            with open(file_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/action":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                body = json.loads(post_data.decode('utf-8'))
                action = body.get("action", "")
                result_msg = "Invalid action"
                
                if bot_instance:
                    if action == "analyze":
                        bot_instance.trigger_manual_ai_analysis()
                        result_msg = "Groq AI Market Analysis triggered!"
                    elif action == "toggle_pause":
                        bot_instance.paused = not bot_instance.paused
                        state = "PAUSED" if bot_instance.paused else "ACTIVE"
                        result_msg = f"Bot state toggled to {state}"
                    elif action == "close":
                        bot_instance.manual_close_position()
                        result_msg = "Emergency Close Order sent!"
                    elif action == "force_trade":
                        bot_instance.force_test_trade()
                        result_msg = "Force test trade executed on Binance Futures Testnet!"

                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": result_msg}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif self.path in ["/webhook/tradingview", "/api/webhook/tradingview"]:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                alert = json.loads(post_data.decode('utf-8'))
                action = str(alert.get("action", "")).upper()
                print(f"\n[TRADINGVIEW WEBHOOK RECEIVED] Alert Signal: {action}")
                
                if bot_instance:
                    if action in ["BUY", "LONG"]:
                        bot_instance.force_test_trade()
                        msg = "TradingView Webhook: LONG Signal Received & Executed!"
                    elif action in ["SELL", "SHORT"]:
                        bot_instance.force_test_trade()
                        msg = "TradingView Webhook: SHORT Signal Received & Executed!"
                    elif action == "CLOSE":
                        bot_instance.manual_close_position()
                        msg = "TradingView Webhook: Close Signal Received!"
                    else:
                        msg = f"TradingView Alert Received: {action}"

                    self.send_response(200)
                    self.send_header("Content-type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "message": msg}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Invalid webhook payload: {e}"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def _run_http_server():
    server = HTTPServer(("0.0.0.0", RENDER_PORT), DashboardHandler)
    print(f"[HTTP SERVER] Bound to 0.0.0.0:{RENDER_PORT}")
    server.serve_forever()

def _self_ping_loop():
    import requests as _req
    while True:
        time.sleep(600)
        url = RENDER_URL if RENDER_URL else f"http://localhost:{RENDER_PORT}/"
        try:
            _req.get(url, timeout=5)
        except Exception:
            pass

class BotController:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        import settings
        settings.load()
        self.executor = BinanceFuturesExecutor()
        self.notifier = TelegramNotifier()
        self.paused = False
        self.active_trade_id = None
        
        # State tracking
        self.latest_summary = {}
        self.multiframe_summary = {}
        self.ticker_24h = {}
        self.latest_tradingview = {}
        self.latest_balance = 5000.0
        self.latest_position = {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "liquidation_price": 0}
        self.latest_ai_decision = {"action": "HOLD", "confidence": 0, "reasoning": "Sistem başlatılıyor..."}
        self.latest_news = {"sentiment_score": 0.0, "sentiment_label": "NEUTRAL", "top_headlines": [], "sources": 0}
        self.latest_derivatives = {"funding_rate": 0.0, "funding_rate_pct": 0.0, "open_interest": 0.0}
        self.order_error_stats = {}
        self.daily_start_balance = 5000.0
        self.risk_mgr = RiskManager()
        self._adopted_needs_protection = False
        
    def send_telegram_status(self):
        self.notifier.send_status_report(
            price=self.latest_summary.get('current_price', 0),
            rsi=self.latest_summary.get('rsi_14', 0),
            ema200=self.latest_summary.get('ema_200', 0),
            balance=self.latest_balance,
            position=self.latest_position
        )
        
    def send_telegram_balance(self):
        daily_pnl = self.latest_balance - self.daily_start_balance
        msg = (
            f"💰 *BAKİYE & KÂR BİLGİSİ*\n\n"
            f"💵 *Mevcut Bakiye:* ${self.latest_balance:.2f} USDT\n"
            f"📈 *Günlük PnL:* ${daily_pnl:+.2f} USDT\n"
            f"🎯 *Günlük Hedef:* %{config.DAILY_TARGET_PROFIT_PCT * 100:.1f}\n"
            f"🛡️ *Max Günlük Kayıp Sınırı:* %{config.MAX_DAILY_DRAWDOWN_PCT * 100:.1f}"
        )
        self.notifier.send_message(msg)

    def send_telegram_detailed_analysis(self):
        """Sends a detailed market analysis explaining WHY the AI made its decision."""
        ind = self.latest_summary
        ai = self.latest_ai_decision
        tv = self.latest_tradingview
        ticker = self.ticker_24h
        pos = self.latest_position

        if not ind:
            self.notifier.send_message("❌ Henüz analiz verisi yok. `/analyze` yazabilirsin.")
            return

        price = ind.get('current_price', 0)
        ema9 = ind.get('ema_9', 0)
        ema21 = ind.get('ema_21', 0)
        ema200 = ind.get('ema_200', 0)

        # Trend açıklaması
        trend_text = []
        trend_text.append(f"• Fiyat ($ {price:.2f}) EMA200'e ($ {ema200:.2f}) göre: {'🟢 BULLISH (üstünde)' if price > ema200 else '🔴 BEARISH (altında)'}")
        trend_text.append(f"• Kısa vade (EMA9/EMA21): {'🟢 Bullish Cross' if ema9 > ema21 else '🔴 Bearish Cross'}")

        # RSI açıklaması
        rsi = ind.get('rsi_14', 0)
        rsi_status = ind.get('rsi_status', 'N/A')
        rsi_comment = ""
        if rsi >= 70:
            rsi_comment = "Aşırı alım (overbought) - geri çekilme riski yüksek"
        elif rsi <= 30:
            rsi_comment = "Aşırı satım (oversold) - tepki alımı potansiyeli"
        elif rsi >= 55:
            rsi_comment = "Alıcı ağırlıklı, momentum yukarı yönlü"
        elif rsi <= 45:
            rsi_comment = "Satıcı ağırlıklı, momentum aşağı yönlü"
        else:
            rsi_comment = "Nötr bölge - yön belirsiz"

        # RSI divergence
        div = ind.get('rsi_divergence', 'NONE')
        div_comment = ""
        if div == "BULLISH_DIVERGENCE":
            div_comment = "🟢 Boğa sapması (yükseliş sinyali)"
        elif div == "BEARISH_DIVERGENCE":
            div_comment = "🔴 Ayı sapması (düşüş sinyali)"
        else:
            div_comment = "Sapma yok"

        # Crash durumu
        crash = "🚨 AKTİF - DİKKAT!" if ind.get('crash_alert') else "Normal"
        if ind.get('crash_alert'):
            crash += f"\n⚠️ {ind.get('crash_message', '')}"

        pos_str = "YOK (FLAT)"
        if pos.get("side") != "FLAT":
            pnl = pos.get('unrealized_pnl', 0)
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            pos_str = f"{pos['side']} {pos['amount']} BTC @ $ {pos['entry_price']:.2f} | UnPNL: {pnl_icon} $ {pnl:+.2f}"

        msg = (
            f"🔬 *DETAYLI PİYASA ANALİZİ*\n\n"
            f"📉 *NEDEN BU KARAR?*\n\n"
            f"1️⃣ *EMA Trend Analizi:*\n{chr(10).join(trend_text)}\n\n"
            f"2️⃣ *RSI Momentum:* RSI = {rsi} ({rsi_status})\n• {rsi_comment}\n• {div_comment}\n\n"
            f"3️⃣ *Volatilite (ATR):* ATR = $ {ind.get('atr_14', 0):.2f}\n"
            f"   → SL/TP mesafeleri bu değerle hesaplanır\n\n"
            f"4️⃣ *Bollinger Bands:* %B = {ind.get('bb_percent_b', 0)}\n"
            f"   Üst: $ {ind.get('bb_upper', 0):.2f} | Alt: $ {ind.get('bb_lower', 0):.2f}\n\n"
            f"5️⃣ *Destek/Direnç:*\n"
            f"   🛡️ Destek: $ {ind.get('support_level', 0):.2f}\n"
            f"   🎯 Direnç: $ {ind.get('resistance_level', 0):.2f}\n\n"
            f"6️⃣ *Market Yapısı:* {ind.get('market_structure', 'N/A')}\n\n"
            f"7️⃣ *Multi-Timeframe (15m/1h/4h):* {tv.get('consensus', 'N/A')}\n\n"
            f"8️⃣ *24s Değişim:* %{ticker.get('price_change_pct', 0):+.2f}\n"
            f"9️⃣ *Flash Crash Uyarısı:* {crash}\n\n"
            f"⚡ *Aktif Pozisyon:* {pos_str}\n\n"
            f"🤖 *AI KARARI:* [{ai.get('action', 'HOLD')}] (%{ai.get('confidence', 0)} güven)\n"
            f"💬 *Gerekçe:* {ai.get('reasoning', 'N/A')}"
        )
        self.notifier.send_message(msg)

    def send_telegram_indicators(self):
        """Sends a compact technical indicator summary."""
        ind = self.latest_summary
        if not ind:
            self.notifier.send_message("❌ Henüz indikatör verisi yok.")
            return
        ema_trend = "🟢 BULLISH" if ind.get('macro_trend_ema200') == "BULLISH" else "🔴 BEARISH"
        msg = (
            f"📐 *TEKNİK İNDİKATÖRLER*\n\n"
            f"• RSI (14): {ind.get('rsi_14', 0)} [{ind.get('rsi_status', 'N/A')}]\n"
            f"• RSI Sapma: {ind.get('rsi_divergence', 'NONE')}\n"
            f"• EMA 9: $ {ind.get('ema_9', 0):.2f}\n"
            f"• EMA 21: $ {ind.get('ema_21', 0):.2f}\n"
            f"• EMA 200: $ {ind.get('ema_200', 0):.2f}\n"
            f"• Makro Trend: {ema_trend}\n"
            f"• Kısa Vade Cross: {ind.get('short_term_ema_cross', 'N/A')}\n"
            f"• ATR (14): $ {ind.get('atr_14', 0):.2f}\n"
            f"• Bollinger %B: {ind.get('bb_percent_b', 0)}\n"
            f"• Destek: $ {ind.get('support_level', 0):.2f}\n"
            f"• Direnç: $ {ind.get('resistance_level', 0):.2f}\n"
            f"• Market Yapısı: {ind.get('market_structure', 'N/A')}\n"
            f"• Hacim Değişimi: %{ind.get('volume_change_pct', 0):+.2f}"
        )
        self.notifier.send_message(msg)

    def send_telegram_multiframe(self):
        """Sends multi-timeframe trend analysis."""
        mf = self.multiframe_summary
        tv = self.latest_tradingview
        if not mf:
            self.notifier.send_message("❌ Çoklu zaman dilimi verisi yok.")
            return
        lines = []
        for tf in ["15m", "1h", "4h"]:
            d = mf.get(tf, {})
            trend = d.get('trend', 'N/A')
            icon = "🟢" if trend == "BULLISH" else ("🔴" if trend == "BEARISH" else "⚪")
            tv_rec = tv.get(tf, {}).get('recommendation', 'N/A') if tv else 'N/A'
            lines.append(f"• *{tf}:* {icon} {trend} | Fiyat $ {d.get('last_close', 0):.2f} | TV: {tv_rec}")
        msg = (
            f"⏱️ *ÇOKLU ZAMAN DİLİMİ ANALİZİ*\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"💡 *Yorum:* Uyumlu trend = daha yüksek güven. "
            f"Çelişkili trendlerde AI temkinli davranır (HOLD)."
        )
        self.notifier.send_message(msg)

    def send_telegram_position(self):
        """Sends detailed position info with liquidation price."""
        pos = self.latest_position
        if pos.get("side") == "FLAT":
            self.notifier.send_message("📭 *Aktif pozisyon yok (FLAT).* Bot piyasayı taramaya devam ediyor.")
            return
        side_icon = "🟢" if pos["side"] == "LONG" else "🔴"
        liq = pos.get('liquidation_price', 0)
        msg = (
            f"⚡ *AKTİF POZİSYON DETAYI*\n\n"
            f"📌 *Yön:* {side_icon} {pos['side']}\n"
            f"🪙 *Sembol:* {pos.get('symbol', config.SYMBOL)}\n"
            f"📦 *Miktar:* {pos['amount']} BTC\n"
            f"💲 *Giriş Fiyatı:* $ {pos['entry_price']:.2f}\n"
            f"💰 *Gerçekleşmemiş PnL:* $ {pos['unrealized_pnl']:+.2f}\n"
            f"⚠️ *Likidasyon Fiyatı:* $ {liq:.2f}" if liq else f"⚠️ *Likidasyon Fiyatı:* Bilinmiyor"
        )
        self.notifier.send_message(msg)

    def send_telegram_settings(self):
        """Sends current bot configuration."""
        msg = (
            f"⚙️ *BOT AYARLARI*\n\n"
            f"• Sembol: {config.SYMBOL}\n"
            f"• Zaman Dilimi: {config.TIMEFRAME}\n"
            f"• Kaldıraç: {config.LEVERAGE}x\n"
            f"• İşlem Başına Risk: %{config.RISK_PER_TRADE_PCT * 100:.1f}\n"
            f"• Güven Eşiği: %{config.CONFIDENCE_THRESHOLD}\n"
            f"• Günlük Hedef: %{config.DAILY_TARGET_PROFIT_PCT * 100:.1f}\n"
            f"• Maks Günlük Kayıp: %{config.MAX_DAILY_DRAWDOWN_PCT * 100:.1f}\n"
            f"• SL Çarpanı: {config.ATR_SL_MULTIPLIER}x ATR\n"
            f"• TP Çarpanı: {config.ATR_TP_MULTIPLIER}x ATR\n"
            f"• Komisyon (çift yön): %{config.ROUNDTRIP_FEE_RATE * 100:.2f}\n"
            f"• Tarama Aralığı: {config.CHECK_INTERVAL_SECONDS}s"
        )
        self.notifier.send_message(msg)

    def send_telegram_history(self):
        """Sends recent trade history from SQLite DB."""
        trades = trade_logger.get_recent_trades(limit=10)
        if not trades:
            self.notifier.send_message("📭 *Henüz işlem kaydı yok.*")
            return
        lines = []
        for t in trades:
            icon = "🟢" if t['status'] == 'WIN' else ("🔴" if t['status'] == 'LOSS' else "⏳")
            pnl_str = "AÇIK" if t['status'] == 'OPEN' else f"$ {t['pnl_usdt']:+.2f}"
            lines.append(
                f"#{t['id']} | {icon} {t['side']} | $ {t['entry_price']:.2f} "
                f"| {t['quantity']} | PnL: {pnl_str}"
            )
        msg = (
            f"📚 *SON İŞLEM GEÇMİŞİ (SQLITE)*\n\n"
            f"{chr(10).join(lines)}"
        )
        self.notifier.send_message(msg)

    def send_telegram_risk(self):
        """Sends current risk manager status."""
        daily_pnl = self.latest_balance - self.daily_start_balance
        daily_pct = (daily_pnl / self.daily_start_balance * 100) if self.daily_start_balance > 0 else 0
        target = config.DAILY_TARGET_PROFIT_PCT * 100
        max_dd = config.MAX_DAILY_DRAWDOWN_PCT * 100
        status = "✅ TRADING AKTİF"
        if daily_pct >= target:
            status = "🎯 GÜNLÜK HEDEFE ULAŞILDI"
        elif daily_pct <= -max_dd:
            status = "🛑 CIRCUIT BREAKER AKTİF"
        msg = (
            f"🛡️ *RİSK YÖNETİMİ DURUMU*\n\n"
            f"• Durum: {status}\n"
            f"• Günlük PnL: $ {daily_pnl:+.2f} (%{daily_pct:+.2f})\n"
            f"• Günlük Hedef: %{target:.1f}\n"
            f"• Maks Kayıp Sınırı: %{max_dd:.1f}\n"
            f"• İşlem Başına Risk: %{config.RISK_PER_TRADE_PCT * 100:.1f}\n\n"
            f"💡 *Not:* Komisyonlar net PnL'den düşülür (%{config.ROUNDTRIP_FEE_RATE * 100:.2f} çift yön)."
        )
        self.notifier.send_message(msg)

    def manual_close_position(self):
        if not self.dry_run:
            success = self.executor.close_position(config.SYMBOL)
            if success:
                self.notifier.send_message("✅ *Pozisyon piyasa fiyatından başarıyla kapatıldı!*")
            else:
                self.notifier.send_message("❌ *Pozisyon kapatılırken hata veya açık pozisyon yok.*")
        else:
            self.notifier.send_message("🧪 *[DRY-RUN] Pozisyon kapatma simüle edildi.*")

    def trigger_manual_ai_analysis(self):
        df = market_data.fetch_klines(config.SYMBOL, config.TIMEFRAME, config.KLINE_LIMIT)
        if df.empty:
            self.notifier.send_message("❌ Veri çekilemedi.")
            return
            
        df_analyzed = indicators.compute_all_indicators(df)
        ind_summary = indicators.get_latest_indicator_summary(df_analyzed)
        ticker_24h = market_data.fetch_24h_ticker(config.SYMBOL)
        mf_data = market_data.fetch_multiframe_data(config.SYMBOL)
        tv_data = tradingview_service.fetch_tradingview_analysis(config.SYMBOL)
        news_data = news_service.get_crypto_news()
        deriv_data = market_data.fetch_derivatives_metrics(config.SYMBOL)

        ai_res = ai_brain.analyze_market_with_ai(
            ind_summary,
            ticker_24h,
            multiframe_data=mf_data,
            tradingview_data=tv_data,
            current_position=self.latest_position["side"],
            news_data=news_data,
            derivatives_data=deriv_data
        )
        self.latest_summary = ind_summary
        self.ticker_24h = ticker_24h
        self.multiframe_summary = mf_data
        self.latest_ai_decision = ai_res
        self.latest_tradingview = tv_data
        self.latest_news = news_data
        self.latest_derivatives = deriv_data
        
        report = (
            f"🧠 *ANLIK GROQ AI TEKNİK ANALİZ RAPORU*\n\n"
            f"🪙 *Fiyat:* ${ind_summary['current_price']:.2f}\n"
            f"📈 *RSI (14):* {ind_summary['rsi_14']} ({ind_summary['rsi_status']}) | Div: {ind_summary['rsi_divergence']}\n"
            f"📊 *TradingView Uyum:* {tv_data.get('consensus', 'N/A')}\n"
            f"🛡️ *Destek:* ${ind_summary['support_level']} | 🎯 *Direnç:* ${ind_summary['resistance_level']}\n"
            f"📐 *Market Yapısı:* {ind_summary['market_structure']}\n\n"
            f"🎯 *AI Tavsiyesi:* [{ai_res.get('action')}] (%{ai_res.get('confidence')} Güven)\n"
            f"💬 *Gerekçe:* {ai_res.get('reasoning')}"
        )
        self.notifier.send_message(report)

    def manual_trade(self, side: str = "LONG", qty: float = None, sl_mult: float = None, tp_mult: float = None) -> dict:
        """Opens a manual LONG/SHORT order with custom qty and ATR SL/TP multipliers.
        Returns {'success': bool, 'message': str, 'trade': {...}}"""
        current_price = self.latest_summary.get('current_price', 0) or market_data.fetch_current_price(config.SYMBOL)
        atr_14 = self.latest_summary.get('atr_14', 0) or 200.0
        side = str(side).upper()
        if side not in ("LONG", "SHORT"):
            return {"success": False, "message": f"Geçersiz yön: {side}"}
        sl_mult = sl_mult if sl_mult else config.ATR_SL_MULTIPLIER
        tp_mult = tp_mult if tp_mult else config.ATR_TP_MULTIPLIER
        qty = qty if qty else 0.002

        if side == "LONG":
            sl_price = round(current_price - (atr_14 * sl_mult), 2)
            tp_price = round(current_price + (atr_14 * tp_mult), 2)
            order_side = "BUY"
        else:
            sl_price = round(current_price + (atr_14 * sl_mult), 2)
            tp_price = round(current_price - (atr_14 * tp_mult), 2)
            order_side = "SELL"

        print(f"\n⚡ MANUAL {side} TRADE: {qty} BTC @ ${current_price:.2f} | SL ${sl_price} | TP ${tp_price}")

        if self.dry_run:
            self.active_trade_id = trade_logger.log_trade_entry(
                symbol=config.SYMBOL, side=side, entry_price=current_price,
                quantity=qty, sl_price=sl_price, tp_price=tp_price,
                ai_confidence=99, ai_reasoning=f"Manuel {side} işlem (DRY-RUN).",
                indicator_summary=self.latest_summary
            )
            self.notifier.send_trade_alert(
                action=f"[DRY-RUN] {side}", price=current_price, qty=qty,
                sl=sl_price, tp=tp_price, reasoning="Manuel işlem simüle edildi."
            )
            return {"success": True, "message": f"[DRY-RUN] {side} {qty} BTC simüle edildi", "trade": {"side": side, "qty": qty, "price": current_price, "sl": sl_price, "tp": tp_price}}

        if self.latest_position.get("side") != "FLAT":
            return {"success": False, "message": f"Zaten açık pozisyon var: {self.latest_position['side']}"}

        import risk_manager as risk_module
        adaptive = risk_module.adaptive_parameters(atr_14=atr_14, entry_price=current_price, base_leverage=config.LEVERAGE)
        try:
            self.executor.set_leverage(config.SYMBOL, int(adaptive["leverage"]))
        except Exception:
            pass

        order = self.executor.place_market_order(config.SYMBOL, order_side, qty)
        if not order:
            self.record_order_error("manual_trade_failed", f"{side} {qty} @ {current_price}")
            return {"success": False, "message": "Piyasa emri yerine getirilemedi (bakiye/kaldıraç yetersiz olabilir)."}

        time.sleep(1)
        self.executor.place_stop_loss_order(config.SYMBOL, side, sl_price, qty)
        self.executor.place_take_profit_order(config.SYMBOL, side, tp_price, qty)
        self.active_trade_id = trade_logger.log_trade_entry(
            symbol=config.SYMBOL, side=side, entry_price=current_price,
            quantity=qty, sl_price=sl_price, tp_price=tp_price,
            ai_confidence=99, ai_reasoning=f"Panelden manuel {side} işlem açıldı.",
            indicator_summary=self.latest_summary
        )
        self.notifier.send_trade_alert(
            action=side, price=current_price, qty=qty,
            sl=sl_price, tp=tp_price, reasoning="Panelden manuel işlem açıldı."
        )
        return {"success": True, "message": f"{side} {qty} BTC işlem açıldı", "trade": {"side": side, "qty": qty, "price": current_price, "sl": sl_price, "tp": tp_price}}

    def update_runtime_settings(self, pairs: dict) -> dict:
        """Applies settings via settings module and pushes leverage to Binance if changed."""
        import settings
        result = settings.update(pairs)
        if "leverage" in result.get("applied", {}):
            try:
                if not self.dry_run:
                    self.executor.set_leverage(config.SYMBOL, int(config.LEVERAGE))
                print(f"[SETTINGS] Leverage applied: {config.LEVERAGE}x")
            except Exception as e:
                print(f"[SETTINGS] Leverage apply failed: {e}")
        if result.get("applied"):
            self.notifier.send_message(
                f"⚙️ *AYARLAR GÜNCELLENDİ*\n" + "\n".join(
                    f"• {k}: {v}" for k, v in result["applied"].items()
                )
            )
        return result

    def get_risk_report(self) -> dict:
        daily_pnl = self.latest_balance - self.daily_start_balance
        daily_pct = (daily_pnl / self.daily_start_balance * 100) if self.daily_start_balance > 0 else 0
        target = config.DAILY_TARGET_PROFIT_PCT * 100
        max_dd = config.MAX_DAILY_DRAWDOWN_PCT * 100
        if daily_pct >= target:
            status = "TARGET_MET"
        elif daily_pct <= -max_dd:
            status = "CIRCUIT_BREAKER"
        else:
            status = "ACTIVE"
        return {
            "status": status,
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pct, 2),
            "daily_target_pct": target,
            "max_drawdown_pct": max_dd,
            "risk_per_trade_pct": config.RISK_PER_TRADE_PCT * 100,
            "order_error_stats": self.order_error_stats
        }

    def get_performance_report(self) -> dict:
        closed = trade_logger.get_closed_trades(limit=50)
        total = len(closed)
        wins = sum(1 for t in closed if t.get("pnl_usdt", 0) > 0)
        losses = sum(1 for t in closed if t.get("pnl_usdt", 0) < 0)
        total_pnl = sum(t.get("pnl_usdt", 0) for t in closed)
        return {
            "total_closed": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total * 100) if total else 0, 1),
            "total_pnl_usdt": round(total_pnl, 2)
        }

    def get_learning_report(self) -> dict:
        try:
            return {"report": learning_engine.format_learning_report()}
        except Exception as e:
            return {"report": f"Öğrenme raporu alınamadı: {e}"}

    def force_test_trade(self):
        """Triggers an instant manual test order on Binance Futures Testnet."""
        current_price = self.latest_summary.get('current_price', 60000.0)
        atr_14 = self.latest_summary.get('atr_14', 500.0)
        side = "LONG"
        qty = 0.002
        sl_price = round(current_price - (1.5 * atr_14), 2)
        tp_price = round(current_price + (2.5 * atr_14), 2)

        print("\n⚡ MANUALLY FORCING TEST TRADE ON BINANCE FUTURES TESTNET...")
        self.active_trade_id = trade_logger.log_trade_entry(
            symbol=config.SYMBOL,
            side=side,
            entry_price=current_price,
            quantity=qty,
            sl_price=sl_price,
            tp_price=tp_price,
            ai_confidence=99,
            ai_reasoning="Kullanıcı / TradingView Webhook tarafından tetiklenen test işlemi.",
            indicator_summary=self.latest_summary
        )

        if not self.dry_run:
            order = self.executor.place_market_order(config.SYMBOL, "BUY", qty)
            if order:
                time.sleep(1)
                self.executor.place_stop_loss_order(config.SYMBOL, side, sl_price, qty)
                self.executor.place_take_profit_order(config.SYMBOL, side, tp_price, qty)
                self.notifier.send_trade_alert(
                    action=f"[TEST] {side}",
                    price=current_price,
                    qty=qty,
                    sl=sl_price,
                    tp=tp_price,
                    reasoning="Binance Futures Testnet üzerinde test işlemi açıldı!"
                )
        else:
            self.notifier.send_trade_alert(
                action=f"[DRY-RUN TEST] {side}",
                price=current_price,
                qty=qty,
                sl=sl_price,
                tp=tp_price,
                reasoning="Simülasyon test işlemi kaydedildi."
            )

    def record_order_error(self, error_type: str, detail: str = ""):
        """Tracks failed order reasons for post-trade analysis."""
        self.order_error_stats[error_type] = self.order_error_stats.get(error_type, 0) + 1
        print(f"[ORDER-ERROR] {error_type}: {detail} (total: {self.order_error_stats[error_type]})")

    def get_dashboard_state(self) -> dict:
        daily_pnl = round(self.latest_balance - self.daily_start_balance, 2)
        daily_pnl_pct = round((daily_pnl / (self.daily_start_balance + 1e-5)) * 100, 2)
        pos = self.latest_position
        # SL/TP seviyelerini aktif pozisyondan türet (DB kaydı / algo emirleri)
        sl_price = None
        tp_price = None
        if pos.get("side") != "FLAT":
            try:
                open_algo = self.executor.get_open_algo_orders(config.SYMBOL)
                for o in open_algo:
                    if o.get("orderType") == "STOP_MARKET":
                        sl_price = float(o.get("triggerPrice") or 0) or None
                    elif o.get("orderType") == "TAKE_PROFIT_MARKET":
                        tp_price = float(o.get("triggerPrice") or 0) or None
            except Exception:
                pass
        pnl_usdt = pos.get("unrealized_pnl", 0) or 0
        pnl_pct = 0.0
        if pos.get("entry_price"):
            if pos.get("side") == "LONG":
                pnl_pct = (self.latest_summary.get("current_price", 0) - pos["entry_price"]) / pos["entry_price"] * 100
            elif pos.get("side") == "SHORT":
                pnl_pct = (pos["entry_price"] - self.latest_summary.get("current_price", 0)) / pos["entry_price"] * 100
        return {
            "status": "PAUSED" if self.paused else "RUNNING_24_7",
            "dry_run": self.dry_run,
            "symbol": config.SYMBOL,
            "timeframe": config.TIMEFRAME,
            "leverage": config.LEVERAGE,
            "price": self.latest_summary.get("current_price", 0.0),
            "price_change_24h": self.ticker_24h.get("price_change_pct", 0.0),
            "balance": round(self.latest_balance, 2),
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "daily_target_pct": config.DAILY_TARGET_PROFIT_PCT * 100,
            "max_drawdown_pct": config.MAX_DAILY_DRAWDOWN_PCT * 100,
            "position": pos,
            "position_detail": {
                "side": pos.get("side", "FLAT"),
                "entry_price": pos.get("entry_price", 0),
                "amount": pos.get("amount", 0),
                "unrealized_pnl": round(pnl_usdt, 2),
                "pnl_pct": round(pnl_pct, 2),
                "sl_price": sl_price,
                "tp_price": tp_price,
                "liquidation_price": pos.get("liquidation_price", 0)
            },
            "indicators": {
                "rsi_14": self.latest_summary.get("rsi_14", 0),
                "rsi_status": self.latest_summary.get("rsi_status", "N/A"),
                "rsi_divergence": self.latest_summary.get("rsi_divergence", "NONE"),
                "ema_9": self.latest_summary.get("ema_9", 0),
                "ema_21": self.latest_summary.get("ema_21", 0),
                "ema_200": self.latest_summary.get("ema_200", 0),
                "macro_trend": self.latest_summary.get("macro_trend_ema200", "N/A"),
                "atr_14": self.latest_summary.get("atr_14", 0),
                "support": self.latest_summary.get("support_level", 0),
                "resistance": self.latest_summary.get("resistance_level", 0),
                "market_structure": self.latest_summary.get("market_structure", "N/A"),
                "crash_alert": self.latest_summary.get("crash_alert", False),
                "crash_message": self.latest_summary.get("crash_message", "Normal")
            },
            "tradingview": self.latest_tradingview,
            "ai_decision": self.latest_ai_decision,
            "multiframe": self.multiframe_summary,
            "news": {
                "sentiment_score": self.latest_news.get("sentiment_score", 0.0),
                "sentiment_label": self.latest_news.get("sentiment_label", "NEUTRAL"),
                "top_headlines": self.latest_news.get("top_headlines", []),
                "sources": self.latest_news.get("sources", 0),
                "fear_greed_index": self.latest_news.get("fear_greed_index"),
                "fear_greed_label": self.latest_news.get("fear_greed_label", "")
            },
            "derivatives": {
                "funding_rate_pct": self.latest_derivatives.get("funding_rate_pct", 0.0),
                "open_interest": self.latest_derivatives.get("open_interest", 0.0)
            },
            "order_error_stats": self.order_error_stats,
            "settings": settings.get_all(),
            "adaptive": self.get_adaptive_state(),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def get_adaptive_state(self) -> dict:
        """Current auto-selected leverage/multipliers based on volatility."""
        import risk_manager as risk_module
        price = self.latest_summary.get('current_price', 0)
        atr = self.latest_summary.get('atr_14', 0)
        if not price or not atr:
            return {"leverage": config.LEVERAGE, "sl_multiplier": config.ATR_SL_MULTIPLIER,
                    "tp_multiplier": config.ATR_TP_MULTIPLIER, "atr_pct": 0}
        ad = risk_module.adaptive_parameters(atr, price, base_leverage=config.LEVERAGE)
        return {
            "leverage": ad["leverage"],
            "sl_multiplier": ad["sl_multiplier"],
            "tp_multiplier": ad["tp_multiplier"],
            "atr_pct": ad["atr_pct"]
        }

    def start(self):
        print_banner()
        trade_logger.init_db()
        
        self.notifier.listen_for_commands(self)
        
        def daily_report_scheduler():
            """Sends a daily profit report to Telegram every day at 12:00."""
            last_sent_date = None
            while True:
                try:
                    now = datetime.now()
                    if now.hour == 12 and now.minute == 0 and last_sent_date != now.date():
                        last_sent_date = now.date()
                        self.notifier.send_daily_report(self, trade_logger)
                        self.daily_start_balance = self.latest_balance
                        print("[DAILY REPORT] Günlük kâr raporu gönderildi (12:00)")
                    time.sleep(30)
                except Exception as e:
                    print(f"[EXCEPT] Daily report scheduler: {e}")
                    time.sleep(60)

        scheduler_thread = threading.Thread(target=daily_report_scheduler, daemon=True)
        scheduler_thread.start()
        
        if not self.dry_run:
            self.executor.set_leverage(config.SYMBOL, config.LEVERAGE)
            self.latest_balance = self.executor.get_account_balance("USDT")
        else:
            self.latest_balance = 5000.0
            print("[DRY-RUN MODE] Operating in simulation mode without placing orders.")
            
        self.daily_start_balance = self.latest_balance if self.latest_balance > 0 else 5000.0
        print(f"💰 Account Balance: ${self.latest_balance:.2f} USDT")
        self.notifier.send_message(
            f"🤖 *BINANCE AI TRADING BOT BAŞLATILDI!*\n\n"
            f"🪙 *Sembol:* {config.SYMBOL}\n"
            f"⏱️ *Zaman Dilimi:* {config.TIMEFRAME}\n"
            f"⚡ *Kaldıraç:* {config.LEVERAGE}x\n"
            f"💰 *Başlangıç Bakiyesi:* ${self.latest_balance:.2f} USDT\n\n"
            f"Komut listesi için Telegram'a `/help` yazabilirsiniz."
        )

        # === POSITION ADOPTION (from second start method) ===
        previous_position_side = "FLAT"
        try:
            if not self.dry_run:
                existing_pos = self.executor.get_open_position(config.SYMBOL)
                if existing_pos["side"] != "FLAT":
                    self.latest_position = existing_pos
                    previous_position_side = existing_pos["side"]
                    self.active_trade_id = trade_logger.log_trade_entry(
                        symbol=config.SYMBOL,
                        side=existing_pos["side"],
                        entry_price=existing_pos["entry_price"],
                        quantity=existing_pos["amount"],
                        sl_price=0.0,
                        tp_price=0.0,
                        ai_confidence=0,
                        ai_reasoning="Bot başlarken var olan pozisyon benimsendi.",
                        indicator_summary=self.latest_summary
                    )
                    print(f"[ADOPT] Mevcut {existing_pos['side']} pozisyon benimsendi (Trade #{self.active_trade_id})")
                    self._adopted_needs_protection = True
                else:
                    try:
                        stale = trade_logger.get_stale_open_trades()
                        for t in stale:
                            trade_logger.update_trade_exit(
                                trade_id=t["id"],
                                exit_price=self.latest_summary.get("current_price", t["entry_price"]),
                                pnl_usdt=t["entry_price"] * 0.0,
                                pnl_pct=0.0,
                                status="EXPIRED"
                            )
                            print(f"[ADOPT] Ölü OPEN kayıt #{t['id']} kapatıldı (Binance pozisyonu FLAT) -> EXPIRED")
                    except Exception as e2:
                        print(f"[WARN] Stale open trade cleanup failed: {e2}")
        except Exception as e:
            print(f"[WARN] Position adoption check failed: {e}")

        # === MAIN TRADING LOOP ===
        cycle_count = 0
        while True:
            try:
                if self.paused:
                    time.sleep(5)
                    continue
                    
                cycle_count += 1
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n--- [Cycle #{cycle_count} | {now_str}] Fetching Market Data & TradingView TA ---")
                
                # 1. Fetch Market Data, Indicators & TradingView Analysis
                df = market_data.fetch_klines(config.SYMBOL, config.TIMEFRAME, config.KLINE_LIMIT)
                if df.empty:
                    print("[WARN] Could not fetch market data. Retrying in 10s...")
                    time.sleep(10)
                    continue
                    
                df_analyzed = indicators.compute_all_indicators(df)
                self.latest_summary = indicators.get_latest_indicator_summary(df_analyzed)
                self.ticker_24h = market_data.fetch_24h_ticker(config.SYMBOL)
                self.multiframe_summary = market_data.fetch_multiframe_data(config.SYMBOL)
                self.latest_tradingview = tradingview_service.fetch_tradingview_analysis(config.SYMBOL)
                self.latest_news = news_service.get_crypto_news()
                self.latest_derivatives = market_data.fetch_derivatives_metrics(config.SYMBOL)
                
                print(f"📊 {config.SYMBOL} Mark Price: ${self.latest_summary['current_price']:.2f}")
                print(f"📈 RSI(14): {self.latest_summary['rsi_14']} [{self.latest_summary['rsi_status']}]")
                print(f"📡 TradingView TA Consensus: {self.latest_tradingview.get('consensus', 'N/A')}")
                print(f"📰 Sentiment: {self.latest_news.get('sentiment_label')} ({self.latest_news.get('sentiment_score')}) | "
                      f"Funding: {self.latest_derivatives.get('funding_rate_pct')}% | OI: {self.latest_derivatives.get('open_interest')}")
                
                # 2. Check Active Position & Balance
                if not self.dry_run:
                    self.latest_position = self.executor.get_open_position(config.SYMBOL)
                    if self.latest_position.get("error"):
                        print("[WARN] Position fetch failed (transient) - skipping cycle to avoid false FLAT")
                        time.sleep(config.CHECK_INTERVAL_SECONDS)
                        continue
                    self.latest_balance = self.executor.get_account_balance("USDT")
                else:
                    self.latest_position = {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "liquidation_price": 0}

                # Check if position was closed (Binance shows FLAT but we had a position)
                if previous_position_side != "FLAT" and self.latest_position["side"] == "FLAT":
                    print("[INFO] Position closed! Fetching realized PnL with fees...")
                    if self.active_trade_id:
                        realized = {"net_pnl": 0.0, "realized_pnl": 0.0, "commission": 0.0}
                        try:
                            if not self.dry_run:
                                start_ms = trade_logger.get_trade_timestamp(self.active_trade_id)
                                realized = self.executor.get_realized_pnl(config.SYMBOL, start_ms=start_ms)
                        except Exception as e:
                            print(f"[WARN] Could not fetch realized PnL: {e}")
                        trade_logger.update_trade_exit(
                            trade_id=self.active_trade_id,
                            exit_price=self.latest_summary['current_price'],
                            pnl_usdt=realized["net_pnl"],
                            pnl_pct=0.0
                        )
                        # Export closed trade to Google Sheets (via Google Form)
                        try:
                            if not self.dry_run:
                                trade_info = trade_logger.get_closed_trades(limit=1)
                                if trade_info:
                                    t = trade_info[0]
                                    sheets_exporter.export_trade({
                                        "trade_id": t["id"],
                                        "timestamp": t.get("timestamp", ""),
                                        "symbol": t["symbol"],
                                        "side": t["side"],
                                        "entry_price": t["entry_price"],
                                        "exit_price": t.get("exit_price", 0),
                                        "quantity": t["quantity"],
                                        "pnl_usdt": t.get("pnl_usdt", 0),
                                        "pnl_pct": t.get("pnl_pct", 0),
                                        "status": t.get("status", ""),
                                        "ai_confidence": t.get("ai_confidence", 0),
                                        "hold_time_min": t.get("hold_time_min", 0),
                                    })
                        except Exception as e:
                            print(f"[WARN] Sheets export failed: {e}")
                        self.active_trade_id = None
                        self.notifier.send_message(
                            f"✅ *İŞLEM KAPANDI!*\n\n"
                            f"💵 *Net Kâr (Komisyon Dahil):* ${realized['net_pnl']:+.2f} USDT\n"
                            f"💰 *Brüt Kâr:* ${realized['realized_pnl']:+.2f}\n"
                            f"🧾 *Komisyon:* ${realized['commission']:.2f}"
                        )
                        # Trigger learning update after each closed trade
                        try:
                            closed = trade_logger.get_closed_trades(limit=10)
                            adaptation = learning_engine.compute_adaptation(closed)
                            lessons = learning_engine.generate_lessons(
                                learning_engine.analyze_patterns(closed)
                            )
                            learn_msg = (
                                f"🧠 *ÖĞRENME GÜNCELLEMESİ*\n\n"
                                f"• Yeni Güven Eşiği: %{adaptation['confidence_threshold']}\n"
                                f"• İşlem Başına Risk: %{adaptation['risk_per_trade_pct']}\n"
                                f"• Seri: {adaptation['consecutive_wins']}W / {adaptation['consecutive_losses']}L\n"
                                f"• Genel Win Rate: %{adaptation['win_rate']}"
                            )
                            if lessons:
                                learn_msg += f"\n\n🎓 *En Kritik Ders:*\n{lessons[0]}"
                            self.notifier.send_message(learn_msg)
                        except Exception as e:
                            print(f"[WARN] Learning update failed: {e}")

                previous_position_side = self.latest_position["side"]

                # Protect adopted positions that have no SL/TP algo orders yet
                if getattr(self, '_adopted_needs_protection', False):
                    self._ensure_position_protected()

                # Check daily risk limits
                can_trade, limit_msg = self.risk_mgr.check_daily_limits(self.latest_balance)
                daily_target_hit = self.risk_mgr.is_daily_target_hit()
                print(f"🛡️  Risk Manager Status: {limit_msg}")

                # === POSITION MANAGEMENT (if position exists) ===
                if self.latest_position["side"] != "FLAT":
                    pnl = self.latest_position['unrealized_pnl']
                    pnl_color = "🟢" if pnl >= 0 else "🔴"
                    print(f"⚡ ACTIVE POSITION: {self.latest_position['side']} {self.latest_position['amount']} {config.SYMBOL} @ ${self.latest_position['entry_price']:.2f} | UnPNL: {pnl_color} ${pnl:+.2f}")
                    
                    # Manage open position (trailing SL, TP1 partial, etc.)
                    self.manage_open_position()
                    
                    print(f"😴 Sleeping for {config.CHECK_INTERVAL_SECONDS} seconds...\n")
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # === NO POSITION - CHECK IF WE CAN OPEN NEW ===
                if not can_trade:
                    print(f"⏸️  Trading paused by Risk Manager: {limit_msg}")
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # Prevent duplicate: if we have active_trade_id but no position, clean up
                if self.active_trade_id is not None:
                    print("[WARN] Active trade ID exists but no position on Binance - cleaning up stale trade")
                    self.cleanup_stale_trade()
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # 3. Deterministic strategy decides; Groq AI is an advisory vote
                print("🧠 Strateji katmanı karar veriyor, Groq AI oy veriyor...")
                strategy_signal = strategy.evaluate(
                    self.latest_summary,
                    multiframe_data=self.multiframe_summary,
                    tradingview_data=self.latest_tradingview,
                    news_data=self.latest_news,
                    derivatives_data=self.latest_derivatives,
                )
                ai_vote = ai_brain.analyze_market_with_ai(
                    self.latest_summary,
                    self.ticker_24h,
                    multiframe_data=self.multiframe_summary,
                    tradingview_data=self.latest_tradingview,
                    current_position=self.latest_position["side"],
                    news_data=self.latest_news,
                    derivatives_data=self.latest_derivatives
                )
                ai_decision = strategy.combine_with_ai(strategy_signal, ai_vote)
                self.latest_ai_decision = ai_decision
                
                action = ai_decision.get("action", "HOLD").upper()
                confidence = ai_decision.get("confidence", 0)
                reasoning = ai_decision.get("reasoning", "Henüz karar verilmedi")
                sl_mult = ai_decision.get("sl_multiplier_atr", config.ATR_SL_MULTIPLIER)
                tp_mult = ai_decision.get("tp_multiplier_atr", config.ATR_TP_MULTIPLIER)
                
                print(f"🤖 Strateji Kararı: [{action}] (Confidence: {confidence}%)")
                print(f"💬 {reasoning}")
                
                # Adaptive risk settings from learning engine, clamped to config
                adaptation = {"confidence_threshold": config.CONFIDENCE_THRESHOLD,
                              "risk_per_trade_pct": config.RISK_PER_TRADE_PCT * 100}
                try:
                    closed = trade_logger.get_closed_trades(limit=10)
                    adaptation = learning_engine.compute_adaptation(closed)
                except Exception:
                    pass
                current_threshold = adaptation["confidence_threshold"]
                
                # 4. Execute Trade if High Conviction (adaptive threshold)
                if action in ["LONG", "SHORT"] and confidence >= current_threshold:
                    # Auto-tune leverage + multipliers based on volatility
                    import risk_manager as risk_module
                    adaptive = risk_module.adaptive_parameters(
                        atr_14=self.latest_summary['atr_14'],
                        entry_price=self.latest_summary['current_price'],
                        base_leverage=config.LEVERAGE
                    )
                    adaptive_sl = adaptive["sl_multiplier"]
                    adaptive_tp = adaptive["tp_multiplier"]
                    adaptive_lev = adaptive["leverage"]
                    print(f"⚙️ Adaptive: kaldıraç {adaptive_lev}x | SL {adaptive_sl}x ATR | TP {adaptive_tp}x ATR | ATR% {adaptive['atr_pct']}")

                    trade_params = self.risk_mgr.calculate_position_parameters(
                        account_balance=self.latest_balance,
                        entry_price=self.latest_summary['current_price'],
                        atr_14=self.latest_summary['atr_14'],
                        side=action,
                        sl_mult=adaptive_sl,
                        tp_mult=adaptive_tp,
                        risk_pct=adaptation.get("risk_per_trade_pct", config.RISK_PER_TRADE_PCT) / 100,
                        leverage=adaptive_lev
                    )
                    
                    print(f"\n🎯 HIGH CONVICTION SIGNAL DETECTED!")
                    
                    if self.dry_run:
                        # DRY-RUN: simulate success, log the trade
                        self.active_trade_id = trade_logger.log_trade_entry(
                            symbol=config.SYMBOL,
                            side=action,
                            entry_price=trade_params['entry_price'],
                            quantity=trade_params['quantity'],
                            sl_price=trade_params['sl_price'],
                            tp_price=trade_params['tp_price'],
                            ai_confidence=confidence,
                            ai_reasoning=reasoning,
                            indicator_summary=self.latest_summary
                        )

                        self.notifier.send_trade_alert(
                            action=f"[DRY-RUN] {action}",
                            price=trade_params['entry_price'],
                            qty=trade_params['quantity'],
                            sl=trade_params['sl_price'],
                            tp=trade_params['tp_price'],
                            reasoning=reasoning
                        )
                    else:
                        order_side = "BUY" if action == "LONG" else "SELL"
                        try:
                            self.executor.set_leverage(config.SYMBOL, int(trade_params.get("leverage", config.LEVERAGE)))
                        except Exception as e:
                            print(f"[WARN] Leverage apply failed: {e}")
                        market_order = self.executor.place_market_order(config.SYMBOL, order_side, trade_params['quantity'])
                        
                        if market_order:
                            # Only log after the order actually fills
                            self.active_trade_id = trade_logger.log_trade_entry(
                                symbol=config.SYMBOL,
                                side=action,
                                entry_price=trade_params['entry_price'],
                                quantity=trade_params['quantity'],
                                sl_price=trade_params['sl_price'],
                                tp_price=trade_params['tp_price'],
                                ai_confidence=confidence,
                                ai_reasoning=reasoning,
                                indicator_summary=self.latest_summary
                            )
                            time.sleep(1)
                            self.executor.place_stop_loss_order(config.SYMBOL, action, trade_params['sl_price'], trade_params['quantity'])
                            self.executor.place_take_profit_order(config.SYMBOL, action, trade_params['tp_price'], trade_params['quantity'])
                            
                            self.notifier.send_trade_alert(
                                action=action,
                                price=trade_params['entry_price'],
                                qty=trade_params['quantity'],
                                sl=trade_params['sl_price'],
                                tp=trade_params['tp_price'],
                                reasoning=reasoning
                            )
                        else:
                            print(f"[ERROR] Market order FAILED for {action} - trade NOT logged.")
                            self.record_order_error("market_order_failed", f"{action} {trade_params['quantity']} @ {trade_params['entry_price']}")
                            self.notifier.send_message(
                                f"❌ *İŞLEM BAŞARISIZ:* {action} sinyali geldi ama piyasa emri yerine getirilemedi "
                                f"({trade_params['quantity']} {config.SYMBOL} @ ${trade_params['entry_price']:.2f}).\n"
                                f"Kasa/leverage yetersiz olabilir."
                            )
                else:
                    print("⌛ Decision: HOLD. Waiting for higher conviction setup...")

                print(f"😴 Sleeping for {config.CHECK_INTERVAL_SECONDS} seconds...\n")
                time.sleep(config.CHECK_INTERVAL_SECONDS)
                
            except KeyboardInterrupt:
                print("\n👋 Trading bot stopped by user.")
                sys.exit(0)
            except Exception as e:
                print(f"[EXCEPT] Loop exception: {e}")
                time.sleep(10)

    def _ensure_position_protected(self):
        """Places SL/TP algo orders on an adopted/open position that lacks them.

        Adopted positions (bot restart with an existing Binance position) used
        to run unprotected until SL/TP existed, which produced oversized losses.
        """
        if self.dry_run:
            return
        symbol = config.SYMBOL
        pos = self.latest_position
        if pos.get("side") == "FLAT":
            return
        try:
            open_algo = self.executor.get_open_algo_orders(symbol)
            has_sl = any(o.get("orderType") == "STOP_MARKET" for o in open_algo)
            has_tp = any(o.get("orderType") == "TAKE_PROFIT_MARKET" for o in open_algo)
            if has_sl and has_tp:
                self._adopted_needs_protection = False
                return
            atr = self.latest_summary.get("atr_14", 0)
            price = self.latest_summary.get("current_price", 0)
            side = pos.get("side")
            qty = pos.get("amount", 0)
            if not atr or not price or not side or not qty:
                print("[ADOPT-PROTECT] ATR/fiyat verisi yok, bir sonraki cycle'da tekrar denenir")
                return
            if not has_sl:
                sl = price - atr * config.ATR_SL_MULTIPLIER if side == "LONG" else price + atr * config.ATR_SL_MULTIPLIER
                self.executor.place_stop_loss_order(symbol, side, round(sl, 2), qty)
            if not has_tp:
                tp = price + atr * config.ATR_TP_MULTIPLIER if side == "LONG" else price - atr * config.ATR_TP_MULTIPLIER
                self.executor.place_take_profit_order(symbol, side, round(tp, 2), qty)
            self._adopted_needs_protection = False
            print(f"[ADOPT-PROTECT] Benimsenen {side} pozisyona SL/TP yerleştirildi (qty {qty})")
        except Exception as e:
            print(f"[ADOPT-PROTECT] Hata: {e}")

    def cleanup_stale_trade(self):
        """Cleans up stale trade ID when Binance shows no position but we have active_trade_id."""
        if self.active_trade_id:
            try:
                trade_logger.update_trade_exit(
                    trade_id=self.active_trade_id,
                    exit_price=self.latest_summary.get("current_price", 0),
                    pnl_usdt=0.0,
                    pnl_pct=0.0,
                    status="EXPIRED"
                )
                print(f"[CLEANUP] Stale trade #{self.active_trade_id} marked as EXPIRED")
            except Exception as e:
                print(f"[WARN] Stale trade cleanup failed: {e}")
            self.active_trade_id = None

    def manage_open_position(self):
        """
        Manages open position: trailing SL, TP1 partial close, 
        checks for EMA cross reversal, crash alerts.
        """
        pos = self.latest_position
        ind = self.latest_summary
        current_price = ind.get('current_price', 0)
        atr_14 = ind.get('atr_14', 0)
        side = pos.get('side', 'FLAT')
        entry_price = pos.get('entry_price', 0)
        qty = pos.get('amount', 0)
        unrealized_pnl = pos.get('unrealized_pnl', 0)
        
        if not current_price or not atr_14 or qty == 0:
            return

        pnl_pct = 0.0
        if entry_price > 0:
            if side == "LONG":
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100

        # === TRAILING STOP LOGIC ===
        # Activate trailing after 1% profit or 1x ATR move in favor
        min_trail_profit = max(0.01, atr_14 / entry_price * 100)  # 1% or 1x ATR
        
        if self.dry_run:
            return
            
        try:
            import risk_manager as risk_module
            
            # Check if trailing should activate
            if risk_module.RiskManager().should_trail_activate(entry_price, current_price, side, min_trail_profit / 100):
                # Calculate new trailing SL
                new_sl = risk_module.RiskManager().calculate_trailing_stop(
                    entry_price, current_price, atr_14, side, trail_mult=1.5
                )
                
                # Get current SL from open algo orders
                open_algo = self.executor.get_open_algo_orders(config.SYMBOL)
                current_sl = None
                for o in open_algo:
                    if o.get("orderType") == "STOP_MARKET":
                        current_sl = float(o.get("triggerPrice") or 0)
                        break
                
                # Only update SL if it improves (moves in our favor)
                should_update = False
                if side == "LONG" and current_sl and new_sl > current_sl:
                    should_update = True
                elif side == "SHORT" and current_sl and new_sl < current_sl:
                    should_update = True
                
                if should_update:
                    # Cancel old SL and place new one
                    self.executor.cancel_all_open_algo_orders(config.SYMBOL)
                    time.sleep(0.5)
                    self.executor.place_stop_loss_order(config.SYMBOL, side, new_sl, qty)
                    # Re-place TP (since we cancelled all algo orders)
                    tp_price = None
                    for o in open_algo:
                        if o.get("orderType") == "TAKE_PROFIT_MARKET":
                            tp_price = float(o.get("triggerPrice") or 0)
                            break
                    if tp_price:
                        self.executor.place_take_profit_order(config.SYMBOL, side, tp_price, qty)
                    print(f"🔄 Trailing SL updated: ${new_sl:.2f} (PnL: {pnl_pct:+.2f}%)")

            # === TP1 PARTIAL CLOSE (50% at 1.5% profit or RSI extreme) ===
            rsi = ind.get('rsi_14', 50)
            tp1_triggered = False
            
            if side == "LONG":
                if pnl_pct >= 1.5 or rsi >= 75:
                    tp1_triggered = True
            else:  # SHORT
                if pnl_pct >= 1.5 or rsi <= 25:
                    tp1_triggered = True
            
            if tp1_triggered:
                # Check if we already did TP1 (track via order quantity)
                open_algo = self.executor.get_open_algo_orders(config.SYMBOL)
                tp_qty = sum(float(o.get("quantity", 0)) for o in open_algo if o.get("orderType") == "TAKE_PROFIT_MARKET")
                
                # If TP quantity matches full position, we haven't done partial close yet
                if abs(tp_qty - qty) < 0.0001:
                    # Close 50% at market
                    close_qty = round(qty * 0.5, 3)
                    close_side = "SELL" if side == "LONG" else "BUY"
                    
                    # Reduce position
                    order = self.executor.place_market_order(config.SYMBOL, close_side, close_qty)
                    if order:
                        print(f"✅ TP1 PARTIAL CLOSE: {close_qty} {config.SYMBOL} @ ${current_price:.2f} (PnL: {pnl_pct:+.2f}%)")
                        self.notifier.send_message(
                            f"✅ *TP1 - YARIM KAPATMA*\n\n"
                            f"📌 {side} | {close_qty} BTC @ ${current_price:.2f}\n"
                            f"💰 PnL: ${unrealized_pnl * 0.5:+.2f} ({pnl_pct/2:+.2f}%)\n"
                            f"🛡️ SL -> Breakeven (${entry_price:.2f})"
                        )
                        # Move SL to breakeven for remaining position
                        self.executor.cancel_all_open_algo_orders(config.SYMBOL)
                        time.sleep(0.5)
                        self.executor.place_stop_loss_order(config.SYMBOL, side, entry_price, qty - close_qty)
                        # Re-place TP for remaining
                        tp_price = current_price + (atr_14 * 3.5) if side == "LONG" else current_price - (atr_14 * 3.5)
                        self.executor.place_take_profit_order(config.SYMBOL, side, tp_price, qty - close_qty)

            # === EMA CROSS REVERSAL CHECK ===
            ema9 = ind.get('ema_9', 0)
            ema21 = ind.get('ema_21', 0)
            short_cross = ind.get('short_term_ema_cross', '')
            
            reversal_signal = False
            if side == "LONG" and short_cross == "BEARISH_CROSS" and pnl_pct > 0.5:
                reversal_signal = True
                reason = "EMA9/21 Bearish Cross (profit protection)"
            elif side == "SHORT" and short_cross == "BULLISH_CROSS" and pnl_pct > 0.5:
                reversal_signal = True
                reason = "EMA9/21 Bullish Cross (profit protection)"
            
            if reversal_signal:
                print(f"🔄 REVERSAL SIGNAL: {reason} - Closing position")
                self.executor.close_position(config.SYMBOL)
                self.notifier.send_message(
                    f"🔄 *TREND REVERSAL - POZISYON KAPATILDI*\n\n"
                    f"📌 {side} @ ${entry_price:.2f} -> ${current_price:.2f}\n"
                    f"💰 PnL: ${unrealized_pnl:+.2f} ({pnl_pct:+.2f}%)\n"
                    f"⚡ Neden: {reason}"
                )

            # === CRASH ALERT PROTECTION ===
            if ind.get('crash_alert') and pnl_pct > -1.0:
                # If crash alert and we're not deep in loss, close defensively
                print(f"🚨 CRASH ALERT ACTIVE - Defensive close")
                self.executor.close_position(config.SYMBOL)
                self.notifier.send_message(
                    f"🚨 *FLASH CRASH KORUMASI - POZISYON KAPATILDI*\n\n"
                    f"⚠️ {ind.get('crash_message', 'Aniden düşüş tespit edildi')}\n"
                    f"📌 {side} @ ${entry_price:.2f} -> ${current_price:.2f}\n"
                    f"💰 PnL: ${unrealized_pnl:+.2f} ({pnl_pct:+.2f}%)"
                )

            # === DAILY TARGET HIT - CLOSE ALL ===
            # (Handled in main loop via self.risk_mgr.is_daily_target_hit())

        except Exception as e:
            print(f"[WARN] Position management failed: {e}")

_DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "dashboard.html")

def load_dashboard_html() -> str:
    try:
        with open(_DASHBOARD_HTML_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<html><body><h1>templates/dashboard.html bulunamadi</h1></body></html>"

def print_banner():
    print("=" * 70)
    print("      🚀 AI-POWERED BINANCE FUTURES TRADING BOT (GROQ LLAMA-3.3) 🚀")
    print("=" * 70)
    print(f" Symbol         : {config.SYMBOL}")
    print(f" Timeframe      : {config.TIMEFRAME}")
    print(f" Leverage       : {config.LEVERAGE}x")
    print(f" TradingView    : Connected (Live Widgets + TA Engine + Webhook API)")
    print(f" Web Dashboard  : Bound to Port {RENDER_PORT}")
    print(f" AI Brain       : Groq ({config.GROQ_MODEL}) + Self-Learning DB")
    print(f" Telegram Bot   : Enabled (Chat ID: {config.TELEGRAM_CHAT_ID})")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Powered Binance Futures Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Run in simulation mode without placing real orders")
    args = parser.parse_args()
    
    bot_instance = BotController(dry_run=args.dry_run)
    
    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()
    
    ping_thread = threading.Thread(target=_self_ping_loop, daemon=True)
    ping_thread.start()
    
    bot_instance.start()
