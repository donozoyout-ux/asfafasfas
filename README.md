# Binance AI Trading Bot

Binance Futures (testnet) üzerinde çalışan, Groq Llama-3.3 ile AI destekli otomatik al/sat botu.

## Özellikler

- BTCUSDT Futures otomatik LONG/SHORT işlemleri (testnet)
- Groq AI analizi + rule-based yedek sinyal (rate-limit durumunda)
- Teknik indikatörler (RSI, EMA, ATR, Bollinger) ve çoklu zaman dilimi analizi
- Haber duyarlılığı + fonlama oranı / open interest korumaları
- Risk yönetimi: günlük hedef, maks drawdown, adaptif kaldıraç/SL/TP
- Telegram bot komutları ve web dashboard
- SQLite işlem geçmişi + kendi kendine öğrenme motoru

## Çalıştırma

```bash
pip install -r requirements.txt
python app.py            # web dashboard + bot (port 5000)
python main.py --dry-run # simülasyon modu
```

Gerekli ortam değişkenleri için `.env` dosyasını doldurun (örnek: `BINANCE_API_KEY`, `BINANCE_SECRET_KEY`, `GROQ_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`).
