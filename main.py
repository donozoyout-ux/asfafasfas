import sys
import time
import argparse
import os
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import config
import market_data
import indicators
import ai_brain
import trade_logger
from risk_manager import RiskManager
from execution import BinanceFuturesExecutor
from telegram_bot import TelegramNotifier

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = (
            "<!DOCTYPE html><html><head><title>Binance AI Bot Status</title>"
            "<style>body{font-family:sans-serif;background:#0d1117;color:#c9d1d9;text-align:center;padding:50px;}"
            "h1{color:#2ea043;}.box{background:#161b22;padding:20px;border-radius:10px;display:inline-block;margin-top:20px;}</style></head>"
            "<body><h1>🚀 Binance AI Trading Bot is Live & Running!</h1>"
            "<div class='box'><p><b>Status:</b> 🟢 Active & Operational</p>"
            "<p><b>Model:</b> Groq Llama-3.3-70b</p>"
            "<p><b>Target:</b> Daily 0.5% - 1.0% Capital Growth</p></div></body></html>"
        )
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.getenv("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"[HEALTH-CHECK] HTTP Web Health-check server listening on port {port}...")
        server.serve_forever()
    except Exception as e:
        print(f"[HEALTH-CHECK] Server notice: {e}")

def launch_health_server_in_bg():
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

class BotController:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.executor = BinanceFuturesExecutor()
        self.notifier = TelegramNotifier()
        self.paused = False
        self.active_trade_id = None
        
        # State tracking
        self.latest_summary = {}
        self.latest_balance = 5000.0
        self.latest_position = {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0}
        
    def send_telegram_status(self):
        """Called via Telegram /status command."""
        self.notifier.send_status_report(
            price=self.latest_summary.get('current_price', 0),
            rsi=self.latest_summary.get('rsi_14', 0),
            ema200=self.latest_summary.get('ema_200', 0),
            balance=self.latest_balance,
            position=self.latest_position
        )
        
    def send_telegram_balance(self):
        """Called via Telegram /balance command."""
        msg = (
            f"💰 *BAKİYE & KÂR BİLGİSİ*\n\n"
            f"💵 *Mevcut Bakiye:* ${self.latest_balance:.2f} USDT\n"
            f"🎯 *Günlük Hedef:* %{config.DAILY_TARGET_PROFIT_PCT * 100:.1f}\n"
            f"🛡️ *Max Günlük Kayıp Sınırı:* %{config.MAX_DAILY_DRAWDOWN_PCT * 100:.1f}"
        )
        self.notifier.send_message(msg)

    def manual_close_position(self):
        """Called via Telegram /close command."""
        if not self.dry_run:
            success = self.executor.close_position(config.SYMBOL)
            if success:
                self.notifier.send_message("✅ *Pozisyon piyasa fiyatından başarıyla kapatıldı!*")
            else:
                self.notifier.send_message("❌ *Pozisyon kapatılırken bir hata oluştu veya açık pozisyon yok.*")
        else:
            self.notifier.send_message("🧪 *[DRY-RUN] Pozisyon kapatma simüle edildi.*")

    def trigger_manual_ai_analysis(self):
        """Called via Telegram /analyze command."""
        df = market_data.fetch_klines(config.SYMBOL, config.TIMEFRAME, config.KLINE_LIMIT)
        if df.empty:
            self.notifier.send_message("❌ Veri çekilemedi.")
            return
            
        df_analyzed = indicators.compute_all_indicators(df)
        ind_summary = indicators.get_latest_indicator_summary(df_analyzed)
        ticker_24h = market_data.fetch_24h_ticker(config.SYMBOL)
        
        ai_res = ai_brain.analyze_market_with_ai(ind_summary, ticker_24h, current_position=self.latest_position["side"])
        
        report = (
            f"🧠 *ANLIK GROQ AI TEKNİK ANALİZ RAPORU*\n\n"
            f"🪙 *Fiyat:* ${ind_summary['current_price']:.2f}\n"
            f"📈 *RSI (14):* {ind_summary['rsi_14']} ({ind_summary['rsi_status']}) | Div: {ind_summary['rsi_divergence']}\n"
            f"🔹 *EMA 200:* ${ind_summary['ema_200']:.2f} ({ind_summary['macro_trend_ema200']})\n"
            f"📐 *ATR (14):* ${ind_summary['atr_14']:.2f}\n\n"
            f"🎯 *AI Tavsiyesi:* [{ai_res.get('action')}] (%{ai_res.get('confidence')} Güven)\n"
            f"💬 *Gerekçe:* {ai_res.get('reasoning')}"
        )
        self.notifier.send_message(report)

    def start(self):
        print_banner()
        trade_logger.init_db()
        
        # Launch lightweight HTTP web server for Render Web Service health check compliance
        launch_health_server_in_bg()
        
        # Start Telegram command listener in background
        self.notifier.listen_for_commands(self)
        
        if not self.dry_run:
            self.executor.set_leverage(config.SYMBOL, config.LEVERAGE)
            self.latest_balance = self.executor.get_account_balance("USDT")
        else:
            self.latest_balance = 5000.0
            print("[DRY-RUN MODE] Operating in simulation mode without placing orders.")
            
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
                print(f"\n--- [Cycle #{cycle_count} | {now_str}] Fetching Market Data ---")
                
                # 1. Fetch Market Data & Calculate Indicators
                df = market_data.fetch_klines(config.SYMBOL, config.TIMEFRAME, config.KLINE_LIMIT)
                if df.empty:
                    print("[WARN] Could not fetch market data. Retrying in 10s...")
                    time.sleep(10)
                    continue
                    
                df_analyzed = indicators.compute_all_indicators(df)
                self.latest_summary = indicators.get_latest_indicator_summary(df_analyzed)
                ticker_24h = market_data.fetch_24h_ticker(config.SYMBOL)
                
                print(f"📊 {config.SYMBOL} Mark Price: ${self.latest_summary['current_price']:.2f}")
                print(f"📈 RSI(14): {self.latest_summary['rsi_14']} [{self.latest_summary['rsi_status']}] | Div: {self.latest_summary['rsi_divergence']}")
                print(f"🔹 EMAs: 9=${self.latest_summary['ema_9']} | 21=${self.latest_summary['ema_21']} | 200=${self.latest_summary['ema_200']} ({self.latest_summary['macro_trend_ema200']})")
                print(f"📐 ATR(14): ${self.latest_summary['atr_14']} | BB %B: {self.latest_summary['bb_percent_b']}")
                
                # 2. Check Active Position & Balance
                if not self.dry_run:
                    self.latest_position = self.executor.get_open_position(config.SYMBOL)
                    self.latest_balance = self.executor.get_account_balance("USDT")
                else:
                    self.latest_position = {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0}

                # Detect position close event for self-learning log
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

                # Check daily limits (0.5%-1.0% target hit or drawdown limit)
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

                    # 3. Request Groq AI Trading Decision (with Self-Learning Memory Injection)
                    print("🧠 Consulting Groq Llama-3.3 AI Brain for technical decision...")
                    ai_decision = ai_brain.analyze_market_with_ai(self.latest_summary, ticker_24h, current_position=self.latest_position["side"])
                    
                    action = ai_decision.get("action", "HOLD").upper()
                    confidence = ai_decision.get("confidence", 0)
                    reasoning = ai_decision.get("reasoning", "No reason provided")
                    sl_mult = ai_decision.get("sl_multiplier_atr", config.ATR_SL_MULTIPLIER)
                    tp_mult = ai_decision.get("tp_multiplier_atr", config.ATR_TP_MULTIPLIER)
                    
                    print(f"🤖 AI Recommendation: [{action}] (Confidence: {confidence}%)")
                    print(f"💬 AI Reasoning: {reasoning}")
                    
                    # 4. Execute Trade if High Conviction (Action in [LONG, SHORT] and confidence >= 70%)
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
                        print(f"   Action       : {action}")
                        print(f"   Qty (BTC)    : {trade_params['quantity']}")
                        print(f"   Est. Entry   : ${trade_params['entry_price']}")
                        print(f"   Stop Loss    : ${trade_params['sl_price']} (Risk: ${trade_params['risk_usdt']})")
                        print(f"   Take Profit  : ${trade_params['tp_price']} (RR Ratio: 1:{trade_params['risk_reward_ratio']})")
                        
                        # Log trade entry into database
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
                            print(f"🚀 Executing {action} order on Binance Futures Testnet...")
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
                            print("🧪 [DRY-RUN] Order simulation complete.")
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

                print(f"😴 Sleeping for {config.CHECK_INTERVAL_SECONDS} seconds before next check...\n")
                time.sleep(config.CHECK_INTERVAL_SECONDS)
                
            except KeyboardInterrupt:
                print("\n👋 Trading bot stopped by user.")
                sys.exit(0)
            except Exception as e:
                print(f"[EXCEPT] Loop exception: {e}")
                time.sleep(10)

def print_banner():
    print("=" * 70)
    print("      🚀 AI-POWERED BINANCE FUTURES TRADING BOT (GROQ LLAMA-3.3) 🚀")
    print("=" * 70)
    print(f" Symbol         : {config.SYMBOL}")
    print(f" Timeframe      : {config.TIMEFRAME}")
    print(f" Leverage       : {config.LEVERAGE}x")
    print(f" Target Growth  : {config.DAILY_TARGET_PROFIT_PCT * 100}% Daily")
    print(f" AI Brain       : Groq ({config.GROQ_MODEL}) + Self-Learning DB")
    print(f" Telegram Bot   : Enabled (Chat ID: {config.TELEGRAM_CHAT_ID})")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Powered Binance Futures Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Run in simulation mode without placing real orders")
    args = parser.parse_args()
    
    bot = BotController(dry_run=args.dry_run)
    bot.start()
