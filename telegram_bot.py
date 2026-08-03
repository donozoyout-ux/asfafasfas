import time
import threading
import requests
from datetime import datetime
import config
import trade_logger
import learning_engine

class TelegramNotifier:
    def __init__(self):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Sends a message to user's Telegram chat with automatic plain-text fallback."""
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code != 200:
                # Fallback: Retry without Markdown formatting to bypass character parsing errors
                payload.pop("parse_mode", None)
                res_fallback = requests.post(url, json=payload, timeout=10)
                return res_fallback.status_code == 200
            return True
        except Exception as e:
            print(f"[EXCEPT] Telegram send_message error: {e}")
            return False

    def send_trade_alert(self, action: str, price: float, qty: float, sl: float, tp: float, reasoning: str):
        """Sends formatted trade entry alert."""
        icon = "🟢" if action == "LONG" else "🔴"
        msg = (
            f"🚀 *YENİ İŞLEM AÇILDI!* {icon}\n\n"
            f"📌 *Yön:* {action}\n"
            f"🪙 *Sembol:* {config.SYMBOL}\n"
            f"💲 *Giriş Fiyatı:* ${price:.2f}\n"
            f"📦 *Miktar:* {qty} BTC\n"
            f"🔴 *Stop Loss (Zarar Kes):* ${sl:.2f}\n"
            f"🟢 *Take Profit (Kâr Al):* ${tp:.2f}\n\n"
            f"🧠 *Yapay Zeka Mantığı:* {reasoning}"
        )
        self.send_message(msg)

    def send_status_report(self, price: float, rsi: float, ema200: float, balance: float, position: dict):
        """Sends a status summary on demand via /status command."""
        pos_str = "FLAT (Açık Pozisyon Yok)"
        if position.get("side") != "FLAT":
            pnl = position.get("unrealized_pnl", 0)
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            pos_str = f"{position['side']} {position['amount']} BTC @ ${position['entry_price']:.2f} | UnPNL: {pnl_icon} ${pnl:+.2f}"

        msg = (
            f"📊 *BINANCE AI BOT ANLIK DURUM*\n\n"
            f"💰 *Kasa Bakiyesi:* ${balance:.2f} USDT\n"
            f"🪙 *{config.SYMBOL} Fiyatı:* ${price:.2f}\n"
            f"📈 *RSI (14):* {rsi}\n"
            f"🔹 *EMA 200:* ${ema200:.2f}\n"
            f"⚡ *Aktif Pozisyon:* {pos_str}\n"
            f"🎯 *Günlük Kâr Hedefi:* %{config.DAILY_TARGET_PROFIT_PCT * 100:.1f}"
        )
        self.send_message(msg)

    def send_performance_report(self):
        """Sends self-learning performance metrics & history."""
        summary = trade_logger.get_performance_summary()
        msg = (
            f"🧠 *GROQ AI ÖĞRENME & PERFORMANS RAPORU*\n\n"
            f"📊 *Toplam Tamamlanan İşlem:* {summary['total_trades']}\n"
            f"🟢 *Başarılı İşlemler (Kâr):* {summary['wins']}\n"
            f"🔴 *Başarısız İşlemler (Zarar):* {summary['losses']}\n"
            f"🎯 *Kazanma Oranı (Win Rate):* %{summary['win_rate_pct']}\n"
            f"💵 *Toplam Geçmiş PnL:* ${summary['total_pnl_usdt']:+.2f} USDT\n\n"
            f"💡 *Yapay Zeka Hafızası:* Tamamlanan tüm işlemler kaydedilmekte ve sonraki analizlerde Groq promptuna beslenmektedir."
        )
        self.send_message(msg)

    def send_daily_report(self, bot_controller, trade_logger):
        """Sends a comprehensive daily profit report at 12:00."""
        try:
            balance = bot_controller.latest_balance
            daily_pnl = balance - bot_controller.daily_start_balance
            daily_pnl_pct = (daily_pnl / bot_controller.daily_start_balance * 100) if bot_controller.daily_start_balance > 0 else 0
            summary = trade_logger.get_performance_summary()
            pos = bot_controller.latest_position
            pos_str = "YOK (FLAT)"
            if pos.get("side") != "FLAT":
                pos_str = f"{pos['side']} {pos['amount']} BTC @ ${pos['entry_price']:.2f}"

            msg = (
                f"📊 *GÜNLÜK KÂR RAPORU ({datetime.now().strftime('%d.%m.%Y')})*\n\n"
                f"💰 *Kasa Bakiyesi:* ${balance:.2f} USDT\n"
                f"📈 *Günlük Kâr:* ${daily_pnl:+.2f} USDT (%{daily_pnl_pct:+.2f})\n"
                f"🎯 *Günlük Hedef:* %{config.DAILY_TARGET_PROFIT_PCT * 100:.1f}\n"
                f"🛡️ *Maks Kayıp Sınırı:* %{config.MAX_DAILY_DRAWDOWN_PCT * 100:.1f}\n"
                f"⚡ *Aktif Pozisyon:* {pos_str}\n\n"
                f"📚 *Geçmiş İşlemler:*\n"
                f"• Toplam: {summary['total_trades']}\n"
                f"• Kazanç: 🟢 {summary['wins']} | Kayıp: 🔴 {summary['losses']}\n"
                f"• Win Rate: %{summary['win_rate_pct']}\n"
                f"• Toplam Geçmiş PnL: ${summary['total_pnl_usdt']:+.2f}\n\n"
                f"🧠 *AI Kararı:* [{bot_controller.latest_ai_decision.get('action', 'HOLD')}] "
                f"(%{bot_controller.latest_ai_decision.get('confidence', 0)} güven)"
            )
            self.send_message(msg)
            return True
        except Exception as e:
            print(f"[EXCEPT] Daily report error: {e}")
            return False

    def listen_for_commands(self, bot_controller):
        """
        Background listener for incoming Telegram commands:
        /status, /analyze, /balance, /performance, /close, /help
        """
        def poll_updates():
            while True:
                try:
                    url = f"{self.api_url}/getUpdates"
                    params = {"offset": self.last_update_id + 1, "timeout": 5}
                    res = requests.get(url, params=params, timeout=10)
                    
                    if res.status_code == 200:
                        data = res.json()
                        for update in data.get("result", []):
                            self.last_update_id = update["update_id"]
                            message = update.get("message", {})
                            text = message.get("text", "").strip()
                            from_id = str(message.get("from", {}).get("id", ""))
                            
                            if from_id != str(self.chat_id):
                                continue
                                
                            if text.startswith("/start") or text.startswith("/help"):
                                help_txt = (
                                    "🤖 *BINANCE AI TRADING BOT KOMUTLARI*\n\n"
                                    "📊 *ANALİZ & DURUM*\n"
                                    "/status - Anlık fiyat, indikatörler, pozisyon ve kasa durumu\n"
                                    "/analyze - Anında Groq AI teknik analizi tetikle\n"
                                    "/analysis - DETAYLI analiz: AI neden bu kararı verdi?\n"
                                    "/indicators - Tüm teknik indikatörlerin özeti\n"
                                    "/multiframe - Çoklu zaman dilimi trend analizi (15m/1h/4h)\n"
                                    "/learn - Bot öğrenme durumu: kazanılan/kaybedilen dersler\n\n"
                                    "💰 *BALANCE & POZİSYON*\n"
                                    "/balance - Bakiye ve günlük PnL bilgisi\n"
                                    "/position - Aktif pozisyon detayı ve likidasyon fiyatı\n"
                                    "/performance - Yapay zeka öğrenme ve başarım oranı\n"
                                    "/history - Son 10 işlem kaydı\n"
                                    "/risk - Risk yönetimi durumu\n"
                                    "/daily - Günlük kâr raporu\n"
                                    "/settings - Bot ayarları ve parametreleri\n\n"
                                    "⚡ *İŞLEMLER*\n"
                                    "/forcetrade - Binance Testnet'te ANINDA test işlemi aç\n"
                                    "/close - Aktif pozisyonu hemen piyasa fiyatından kapat\n"
                                    "/pause - Otomatik taramayı geçici duraklat\n"
                                    "/resume - Otomatik taramayı tekrar başlat"
                                )
                                self.send_message(help_txt)
                                
                            elif text.startswith("/status"):
                                bot_controller.send_telegram_status()
                                
                            elif text.startswith("/analyze"):
                                self.send_message("🔍 *Groq AI Analizi Tetiklendi... Lütfen bekleyin.*")
                                bot_controller.trigger_manual_ai_analysis()

                            elif text.startswith("/analysis"):
                                bot_controller.send_telegram_detailed_analysis()

                            elif text.startswith("/indicators"):
                                bot_controller.send_telegram_indicators()

                            elif text.startswith("/multiframe"):
                                bot_controller.send_telegram_multiframe()

                            elif text.startswith("/learn"):
                                self.send_message(learning_engine.format_learning_report())

                            elif text.startswith("/position"):
                                bot_controller.send_telegram_position()

                            elif text.startswith("/settings"):
                                bot_controller.send_telegram_settings()

                            elif text.startswith("/history"):
                                bot_controller.send_telegram_history()

                            elif text.startswith("/risk"):
                                bot_controller.send_telegram_risk()

                            elif text.startswith("/daily"):
                                self.send_daily_report(bot_controller, trade_logger)

                            elif text.startswith("/performance"):
                                self.send_performance_report()
                                
                            elif text.startswith("/balance"):
                                bot_controller.send_telegram_balance()
                                
                            elif text.startswith("/forcetrade"):
                                self.send_message("⚡ *Manuel Test İşlemi Tetikleniyor...*")
                                bot_controller.force_test_trade()

                            elif text.startswith("/close"):
                                self.send_message("⚠️ *Aktif pozisyon kapatılıyor...*")
                                bot_controller.manual_close_position()
                                
                            elif text.startswith("/pause"):
                                bot_controller.paused = True
                                self.send_message("⏸️ *Bot otomatik taraması duraklatıldı.*")
                                
                            elif text.startswith("/resume"):
                                bot_controller.paused = False
                                self.send_message("▶️ *Bot otomatik taraması tekrar başlatıldı.*")
                                
                except Exception as e:
                    pass
                time.sleep(2)

        t = threading.Thread(target=poll_updates, daemon=True)
        t.start()
