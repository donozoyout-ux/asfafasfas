import time
import threading
import requests
import config

class TelegramNotifier:
    def __init__(self):
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Sends a message to user's Telegram chat."""
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            return res.status_code == 200
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

    def listen_for_commands(self, bot_controller):
        """
        Background listener for incoming Telegram commands:
        /status, /analyze, /balance, /close, /help
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
                            
                            # Authorize chat ID
                            if from_id != str(self.chat_id):
                                continue
                                
                            if text.startswith("/start") or text.startswith("/help"):
                                help_txt = (
                                    "🤖 *BINANCE AI TRADING BOT KOMUTLARI*\n\n"
                                    "/status - Anlık fiyat, indikatörler, pozisyon ve kasa durumu\n"
                                    "/analyze - Anında Groq AI teknik analizi tetikle\n"
                                    "/balance - Bakiye ve günlük PnL bilgisini göster\n"
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
                                
                            elif text.startswith("/balance"):
                                bot_controller.send_telegram_balance()
                                
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
                    # Ignore polling network hiccups
                    pass
                time.sleep(2)

        t = threading.Thread(target=poll_updates, daemon=True)
        t.start()
