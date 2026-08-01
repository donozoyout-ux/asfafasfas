import sys
import time
import argparse
import os
import json
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

RENDER_PORT = int(os.getenv("PORT", 10000))
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
            self.wfile.write(render_dashboard_html().encode("utf-8"))

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
        
        ai_res = ai_brain.analyze_market_with_ai(ind_summary, ticker_24h, multiframe_data=mf_data, current_position=self.latest_position["side"])
        self.latest_ai_decision = ai_res
        
        report = (
            f"🧠 *ANLIK GROQ AI TEKNİK ANALİZ RAPORU*\n\n"
            f"🪙 *Fiyat:* ${ind_summary['current_price']:.2f}\n"
            f"📈 *RSI (14):* {ind_summary['rsi_14']} ({ind_summary['rsi_status']}) | Div: {ind_summary['rsi_divergence']}\n"
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
        qty = 0.002  # Safe micro lot size for test
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
            ai_reasoning="Kullanıcı tarafından Web Panel / Telegram üzerinden tetiklenen test işlemi.",
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
                    reasoning="Binance Futures Testnet üzerinde manuel test işlemi başarıyla açıldı!"
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
            "ai_decision": self.latest_ai_decision,
            "multiframe": self.multiframe_summary,
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def start(self):
        print_banner()
        trade_logger.init_db()
        
        # Start Telegram command listener in background
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
                print(f"\n--- [Cycle #{cycle_count} | {now_str}] Fetching Market Data ---")
                
                # 1. Fetch Market Data & Calculate Indicators
                df = market_data.fetch_klines(config.SYMBOL, config.TIMEFRAME, config.KLINE_LIMIT)
                if df.empty:
                    print("[WARN] Could not fetch market data. Retrying in 10s...")
                    time.sleep(10)
                    continue
                    
                df_analyzed = indicators.compute_all_indicators(df)
                self.latest_summary = indicators.get_latest_indicator_summary(df_analyzed)
                self.ticker_24h = market_data.fetch_24h_ticker(config.SYMBOL)
                self.multiframe_summary = market_data.fetch_multiframe_data(config.SYMBOL)
                
                print(f"📊 {config.SYMBOL} Mark Price: ${self.latest_summary['current_price']:.2f}")
                print(f"📈 RSI(14): {self.latest_summary['rsi_14']} [{self.latest_summary['rsi_status']}] | Div: {self.latest_summary['rsi_divergence']}")
                print(f"🔹 EMAs: 9=${self.latest_summary['ema_9']} | 21=${self.latest_summary['ema_21']} | 200=${self.latest_summary['ema_200']} ({self.latest_summary['macro_trend_ema200']})")
                print(f"🛡️ Support: ${self.latest_summary['support_level']} | Resistance: ${self.latest_summary['resistance_level']}")
                
                # 2. Check Active Position & Balance
                if not self.dry_run:
                    self.latest_position = self.executor.get_open_position(config.SYMBOL)
                    self.latest_balance = self.executor.get_account_balance("USDT")
                else:
                    self.latest_position = {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "liquidation_price": 0}

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

                    # 3. Request Groq AI Trading Decision
                    print("🧠 Consulting Groq Llama-3.3 AI Brain for technical decision...")
                    ai_decision = ai_brain.analyze_market_with_ai(
                        self.latest_summary,
                        self.ticker_24h,
                        multiframe_data=self.multiframe_summary,
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

def render_dashboard_html() -> str:
    """Returns the full HTML, CSS, and JS code for the Web Dashboard Panel."""
    return """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Binance AI Trading Bot - Control Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #0b0e14;
            --card-bg: #151a23;
            --card-border: #222936;
            --accent-green: #00c087;
            --accent-red: #f6465d;
            --accent-blue: #2979ff;
            --accent-yellow: #f0b90b;
            --text-main: #f0f4f8;
            --text-muted: #848e9c;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background: var(--bg-main); color: var(--text-main); padding: 20px; min-height: 100vh; }
        .container { max-width: 1350px; margin: 0 auto; }
        
        /* Header */
        header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--card-border); margin-bottom: 25px; }
        .logo-box { display: flex; align-items: center; gap: 12px; }
        .logo-box h1 { font-size: 1.5rem; font-weight: 800; background: linear-gradient(90deg, #f0b90b, #00c087); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .badge { background: #1e2532; padding: 6px 14px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; border: 1px solid var(--card-border); }
        .badge.online { color: var(--accent-green); border-color: rgba(0, 192, 135, 0.3); }

        /* Grid Layout */
        .grid-top { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; margin-bottom: 25px; }
        .card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 14px; padding: 20px; transition: transform 0.2s; }
        .card:hover { transform: translateY(-2px); }
        .card-label { font-size: 0.82rem; color: var(--text-muted); font-weight: 600; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .card-val { font-size: 1.6rem; font-weight: 800; }

        .grid-middle { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px; }
        @media (max-width: 900px) { .grid-middle { grid-template-columns: 1fr; } }

        /* AI Decision Box */
        .ai-box { background: linear-gradient(135deg, rgba(41, 121, 255, 0.08), rgba(0, 192, 135, 0.08)); border: 1px solid rgba(41, 121, 255, 0.3); }
        .signal-badge { display: inline-block; padding: 8px 18px; border-radius: 8px; font-weight: 800; font-size: 1.1rem; margin-top: 8px; }
        .signal-LONG { background: rgba(0, 192, 135, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .signal-SHORT { background: rgba(246, 70, 93, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }
        .signal-HOLD { background: rgba(240, 185, 11, 0.2); color: var(--accent-yellow); border: 1px solid var(--accent-yellow); }

        /* Controls */
        .controls-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-top: 15px; }
        .btn { padding: 12px; border: none; border-radius: 10px; font-weight: 700; font-size: 0.88rem; cursor: pointer; transition: 0.2s; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .btn-blue { background: var(--accent-blue); color: #fff; }
        .btn-green { background: var(--accent-green); color: #fff; }
        .btn-yellow { background: var(--accent-yellow); color: #000; }
        .btn-red { background: var(--accent-red); color: #fff; }
        .btn:hover { opacity: 0.88; transform: scale(1.02); }

        /* Table */
        .table-box { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.88rem; }
        .table-box th { text-align: left; padding: 12px; color: var(--text-muted); border-bottom: 1px solid var(--card-border); font-size: 0.8rem; }
        .table-box td { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.04); }
        
        .pnl-positive { color: var(--accent-green); font-weight: 700; }
        .pnl-negative { color: var(--accent-red); font-weight: 700; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-box">
                <h1>⚡ BINANCE AI TRADER</h1>
                <span class="badge online">● RENDER 24/7 CLOUD ACTIVE</span>
            </div>
            <div>
                <span class="badge" id="bot-status">Yükleniyor...</span>
                <span class="badge" id="last-updated">Yenileniyor...</span>
            </div>
        </header>

        <!-- Top Stat Cards -->
        <div class="grid-top">
            <div class="card">
                <div class="card-label">BTC Mark Fiyatı</div>
                <div class="card-val" id="btc-price">$0.00</div>
                <div style="font-size:0.82rem; margin-top:4px;" id="btc-change">24s Değişim: %0.00</div>
            </div>
            <div class="card">
                <div class="card-label">Kasa Bakiyesi (USDT)</div>
                <div class="card-val" id="usdt-balance">$0.00</div>
                <div style="font-size:0.82rem; margin-top:4px;" id="daily-pnl">Günlük PnL: $0.00 (%0.00)</div>
            </div>
            <div class="card">
                <div class="card-label">Günlük Hedef & Limitler</div>
                <div class="card-val" style="color:var(--accent-green);">%1.0 Target</div>
                <div style="font-size:0.82rem; margin-top:4px; color:var(--accent-red);">Max Stop Limit: %3.0</div>
            </div>
            <div class="card">
                <div class="card-label">Aktif Pozisyon</div>
                <div class="card-val" id="pos-side">FLAT</div>
                <div style="font-size:0.82rem; margin-top:4px;" id="pos-details">Açık pozisyon yok</div>
            </div>
        </div>

        <!-- Middle Grid: AI Conviction & Technical Matrix -->
        <div class="grid-middle">
            <!-- AI Brain Card -->
            <div class="card ai-box">
                <div class="card-label">🧠 Groq Llama-3.3 AI Karar Motoru</div>
                <div class="signal-badge signal-HOLD" id="ai-action">HOLD (%0 Güven)</div>
                <div style="margin-top:14px; font-size:0.92rem; line-height:1.5; color:#d1d5db;" id="ai-reasoning">
                    Yapay zeka piyasa verilerini analiz ediyor...
                </div>

                <div class="controls-grid" style="margin-top:20px;">
                    <button class="btn btn-blue" onclick="triggerAction('analyze')">🧠 Analiz Et</button>
                    <button class="btn btn-yellow" onclick="triggerAction('toggle_pause')">⏯️ Duraklat / Başlat</button>
                    <button class="btn btn-green" onclick="triggerAction('force_trade')">⚡ Test İşlemi Aç</button>
                    <button class="btn btn-red" onclick="triggerAction('close')">🚨 Pozisyonu Kapat</button>
                </div>
            </div>

            <!-- Technical Analysis & Market Structure -->
            <div class="card">
                <div class="card-label">📈 Teknik İndikatörler & Market Yapısı</div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px; font-size:0.9rem;">
                    <div><b>RSI (14):</b> <span id="rsi-val">-</span></div>
                    <div><b>EMA 200:</b> <span id="ema-200">-</span></div>
                    <div><b>Destek Seviyesi:</b> <span id="support-val" style="color:var(--accent-green);">-</span></div>
                    <div><b>Direnç Seviyesi:</b> <span id="resistance-val" style="color:var(--accent-red);">-</span></div>
                    <div><b>Market Yapısı:</b> <span id="market-struct">-</span></div>
                    <div><b>1h / 4h Trend:</b> <span id="mf-trend">-</span></div>
                </div>
                <div id="crash-alert-box" style="margin-top:14px; padding:10px; border-radius:8px; background:rgba(0,192,135,0.1); color:var(--accent-green); font-size:0.85rem; font-weight:600;">
                    ✅ Market Durumu Normal (Ani Çakılma Riski Yok)
                </div>
            </div>
        </div>

        <!-- Trade History Table -->
        <div class="card">
            <div class="card-label">📜 Son İşlem ve Öğrenme Geçmişi (SQLite)</div>
            <table class="table-box">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Yön</th>
                        <th>Sembol</th>
                        <th>Giriş Fiyatı</th>
                        <th>Miktar</th>
                        <th>Stop Loss</th>
                        <th>Take Profit</th>
                        <th>Güven %</th>
                        <th>Çıkış PnL ($)</th>
                    </tr>
                </thead>
                <tbody id="trade-table-body">
                    <tr><td colspan="9" style="text-align:center;">İşlem geçmişi yükleniyor...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const d = await res.json();
                
                document.getElementById('btc-price').innerText = '$' + (d.price || 0).toLocaleString('en-US', {minimumFractionDigits:2});
                const chg = d.price_change_24h || 0;
                document.getElementById('btc-change').innerText = `24s Değişim: %${chg.toFixed(2)}`;
                document.getElementById('btc-change').style.color = chg >= 0 ? '#00c087' : '#f6465d';

                document.getElementById('usdt-balance').innerText = '$' + (d.balance || 0).toLocaleString('en-US', {minimumFractionDigits:2});
                const pnl = d.daily_pnl || 0;
                document.getElementById('daily-pnl').innerText = `Günlük PnL: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} (%${(d.daily_pnl_pct||0).toFixed(2)})`;
                document.getElementById('daily-pnl').style.color = pnl >= 0 ? '#00c087' : '#f6465d';

                const pos = d.position || {};
                document.getElementById('pos-side').innerText = pos.side || 'FLAT';
                document.getElementById('pos-side').style.color = pos.side === 'LONG' ? '#00c087' : (pos.side === 'SHORT' ? '#f6465d' : '#f0f4f8');
                if(pos.side !== 'FLAT') {
                    document.getElementById('pos-details').innerText = `${pos.amount} BTC @ $${pos.entry_price} | PnL: $${pos.unrealized_pnl}`;
                } else {
                    document.getElementById('pos-details').innerText = 'Açık pozisyon yok';
                }

                const ai = d.ai_decision || {};
                const aiBadge = document.getElementById('ai-action');
                aiBadge.innerText = `${ai.action || 'HOLD'} (%${ai.confidence || 0} Güven)`;
                aiBadge.className = `signal-badge signal-${ai.action || 'HOLD'}`;
                document.getElementById('ai-reasoning').innerText = ai.reasoning || 'Taranıyor...';

                const ind = d.indicators || {};
                document.getElementById('rsi-val').innerText = `${ind.rsi_14 || 0} (${ind.rsi_status || ''})`;
                document.getElementById('ema-200').innerText = `$${ind.ema_200 || 0} (${ind.macro_trend || ''})`;
                document.getElementById('support-val').innerText = `$${ind.support || 0}`;
                document.getElementById('resistance-val').innerText = `$${ind.resistance || 0}`;
                document.getElementById('market-struct').innerText = ind.market_structure || 'Normal';

                const mf = d.multiframe || {};
                document.getElementById('mf-trend').innerText = `1h: ${mf['1h']?.trend || '-'}, 4h: ${mf['4h']?.trend || '-'}`;

                const crashBox = document.getElementById('crash-alert-box');
                if(ind.crash_alert) {
                    crashBox.style.background = 'rgba(246,70,93,0.2)';
                    crashBox.style.color = '#f6465d';
                    crashBox.innerText = ind.crash_message;
                } else {
                    crashBox.style.background = 'rgba(0,192,135,0.1)';
                    crashBox.style.color = '#00c087';
                    crashBox.innerText = '✅ Market Durumu Normal (Ani Çakılma Riski Yok)';
                }

                document.getElementById('bot-status').innerText = d.status === 'RUNNING_24_7' ? '● OTOMATİK TARAMA AKTİF' : '⏸️ DURAKLATILDI';
                document.getElementById('bot-status').style.color = d.status === 'RUNNING_24_7' ? '#00c087' : '#f0b90b';
                document.getElementById('last-updated').innerText = d.last_update || '';
            } catch(e) {
                console.error(e);
            }
        }

        async function fetchTrades() {
            try {
                const res = await fetch('/api/trades');
                const trades = await res.json();
                const tbody = document.getElementById('trade-table-body');
                if(!trades || trades.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#848e9c;">Henüz işlem kaydı bulunmuyor.</td></tr>';
                    return;
                }
                tbody.innerHTML = trades.map(t => `
                    <tr>
                        <td>#${t.id}</td>
                        <td style="color:${t.side==='LONG'?'#00c087':'#f6465d'}; font-weight:700;">${t.side}</td>
                        <td>${t.symbol}</td>
                        <td>$${t.entry_price}</td>
                        <td>${t.quantity}</td>
                        <td>$${t.sl_price}</td>
                        <td>$${t.tp_price}</td>
                        <td>%${t.ai_confidence}</td>
                        <td class="${t.pnl_usdt >= 0 ? 'pnl-positive' : 'pnl-negative'}">${t.pnl_usdt !== null ? '$' + t.pnl_usdt.toFixed(2) : 'AÇIK'}</td>
                    </tr>
                `).join('');
            } catch(e) {
                console.error(e);
            }
        }

        async function triggerAction(act) {
            try {
                const res = await fetch('/api/action', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: act})
                });
                const data = await res.json();
                alert(data.message || 'İşlem gönderildi.');
                fetchStatus();
                fetchTrades();
            } catch(e) {
                alert('Hata: ' + e);
            }
        }

        fetchStatus();
        fetchTrades();
        setInterval(fetchStatus, 4000);
        setInterval(fetchTrades, 10000);
    </script>
</body>
</html>"""

def print_banner():
    print("=" * 70)
    print("      🚀 AI-POWERED BINANCE FUTURES TRADING BOT (GROQ LLAMA-3.3) 🚀")
    print("=" * 70)
    print(f" Symbol         : {config.SYMBOL}")
    print(f" Timeframe      : {config.TIMEFRAME}")
    print(f" Leverage       : {config.LEVERAGE}x")
    print(f" Web Dashboard  : Bound to Port {RENDER_PORT}")
    print(f" AI Brain       : Groq ({config.GROQ_MODEL}) + Self-Learning DB")
    print(f" Telegram Bot   : Enabled (Chat ID: {config.TELEGRAM_CHAT_ID})")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI-Powered Binance Futures Trading Bot")
    parser.add_argument("--dry-run", action="store_true", help="Run in simulation mode without placing real orders")
    args = parser.parse_args()
    
    bot_instance = BotController(dry_run=args.dry_run)
    
    # 1. Start HTTP Server for Web Dashboard & Render Health Checks BEFORE anything else
    http_thread = threading.Thread(target=_run_http_server, daemon=True)
    http_thread.start()
    
    # 2. Start Self-Ping Thread for Render 24/7 Keep-Alive
    ping_thread = threading.Thread(target=_self_ping_loop, daemon=True)
    ping_thread.start()
    
    # 3. Start Main Bot Controller Loop
    bot_instance.start()
