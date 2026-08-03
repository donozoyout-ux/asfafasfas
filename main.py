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
        self.daily_start_balance = 5000.0
        
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
        
        ai_res = ai_brain.analyze_market_with_ai(
            ind_summary,
            ticker_24h,
            multiframe_data=mf_data,
            tradingview_data=tv_data,
            current_position=self.latest_position["side"]
        )
        self.latest_summary = ind_summary
        self.ticker_24h = ticker_24h
        self.multiframe_summary = mf_data
        self.latest_ai_decision = ai_res
        self.latest_tradingview = tv_data
        
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

    def get_dashboard_state(self) -> dict:
        daily_pnl = round(self.latest_balance - self.daily_start_balance, 2)
        daily_pnl_pct = round((daily_pnl / (self.daily_start_balance + 1e-5)) * 100, 2)
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
            "position": self.latest_position,
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
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def start(self):
        print_banner()
        trade_logger.init_db()
        
        self.notifier.listen_for_commands(self)
        
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
        
        risk_mgr = RiskManager(initial_balance=self.latest_balance)
        cycle_count = 0
        previous_position_side = "FLAT"
        
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
                
                print(f"📊 {config.SYMBOL} Mark Price: ${self.latest_summary['current_price']:.2f}")
                print(f"📈 RSI(14): {self.latest_summary['rsi_14']} [{self.latest_summary['rsi_status']}]")
                print(f"📡 TradingView TA Consensus: {self.latest_tradingview.get('consensus', 'N/A')}")
                
                # 2. Check Active Position & Balance
                if not self.dry_run:
                    self.latest_position = self.executor.get_open_position(config.SYMBOL)
                    self.latest_balance = self.executor.get_account_balance("USDT")
                else:
                    self.latest_position = {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "liquidation_price": 0}

                if previous_position_side != "FLAT" and self.latest_position["side"] == "FLAT":
                    print("[INFO] Position closed! Updating trade performance logger...")
                    if self.active_trade_id:
                        trade_logger.update_trade_exit(
                            trade_id=self.active_trade_id,
                            exit_price=self.latest_summary['current_price'],
                            pnl_usdt=self.latest_position.get('unrealized_pnl', 0.0),
                            pnl_pct=0.0
                        )
                        self.active_trade_id = None

                previous_position_side = self.latest_position["side"]

                # Check daily risk limits
                can_trade, limit_msg = risk_mgr.check_daily_limits(self.latest_balance)
                print(f"🛡️  Risk Manager Status: {limit_msg}")
                
                if self.latest_position["side"] != "FLAT":
                    pnl = self.latest_position['unrealized_pnl']
                    pnl_color = "🟢" if pnl >= 0 else "🔴"
                    print(f"⚡ ACTIVE POSITION: {self.latest_position['side']} {self.latest_position['amount']} {config.SYMBOL} @ ${self.latest_position['entry_price']:.2f} | UnPNL: {pnl_color} ${pnl:+.2f}")
                else:
                    if not can_trade:
                        print(f"⏸️  Trading paused by Risk Manager: {limit_msg}")
                        time.sleep(config.CHECK_INTERVAL_SECONDS)
                        continue

                    # 3. Request Groq AI Decision with TradingView Context
                    print("🧠 Consulting Groq Llama-3.3 AI Brain...")
                    ai_decision = ai_brain.analyze_market_with_ai(
                        self.latest_summary,
                        self.ticker_24h,
                        multiframe_data=self.multiframe_summary,
                        tradingview_data=self.latest_tradingview,
                        current_position=self.latest_position["side"]
                    )
                    self.latest_ai_decision = ai_decision
                    
                    action = ai_decision.get("action", "HOLD").upper()
                    confidence = ai_decision.get("confidence", 0)
                    reasoning = ai_decision.get("reasoning", "Henüz karar verilmedi")
                    sl_mult = ai_decision.get("sl_multiplier_atr", config.ATR_SL_MULTIPLIER)
                    tp_mult = ai_decision.get("tp_multiplier_atr", config.ATR_TP_MULTIPLIER)
                    
                    print(f"🤖 AI Recommendation: [{action}] (Confidence: {confidence}%)")
                    print(f"💬 AI Reasoning: {reasoning}")
                    
                    # 4. Execute Trade if High Conviction
                    if action in ["LONG", "SHORT"] and confidence >= 70:
                        trade_params = risk_mgr.calculate_position_parameters(
                            account_balance=self.latest_balance,
                            entry_price=self.latest_summary['current_price'],
                            atr_14=self.latest_summary['atr_14'],
                            side=action,
                            sl_mult=sl_mult,
                            tp_mult=tp_mult
                        )
                        
                        print(f"\n🎯 HIGH CONVICTION SIGNAL DETECTED!")
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
                        
                        if not self.dry_run:
                            order_side = "BUY" if action == "LONG" else "SELL"
                            market_order = self.executor.place_market_order(config.SYMBOL, order_side, trade_params['quantity'])
                            
                            if market_order:
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
                            self.notifier.send_trade_alert(
                                action=f"[DRY-RUN] {action}",
                                price=trade_params['entry_price'],
                                qty=trade_params['quantity'],
                                sl=trade_params['sl_price'],
                                tp=trade_params['tp_price'],
                                reasoning=reasoning
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


_DASHBOARD_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "dashboard.html")

def load_dashboard_html() -> str:
    try:
        with open(_DASHBOARD_HTML_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<html><body><h1>static/dashboard.html bulunamadi</h1></body></html>"

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
