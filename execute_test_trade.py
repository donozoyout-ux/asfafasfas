import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

import config
import market_data
import indicators
from risk_manager import RiskManager
from execution import BinanceFuturesExecutor
from telegram_bot import TelegramNotifier

def place_test_trade():
    print("=== BINANCE FUTURES TESTNET - CANLI TEST ISLEMI BASLATILIYOR ===")
    
    executor = BinanceFuturesExecutor()
    notifier = TelegramNotifier()
    
    # 1. Set leverage
    executor.set_leverage(config.SYMBOL, config.LEVERAGE)
    
    # 2. Get current price & balance
    current_price = market_data.fetch_current_price(config.SYMBOL)
    balance = executor.get_account_balance("USDT")
    print(f"Bakiyeniz: ${balance:.2f} USDT")
    print(f"{config.SYMBOL} Mevcut Fiyat: ${current_price:.2f}")
    
    # 3. Calculate indicators for ATR SL/TP
    df = market_data.fetch_klines(config.SYMBOL, config.TIMEFRAME, 50)
    df_analyzed = indicators.compute_all_indicators(df)
    summary = indicators.get_latest_indicator_summary(df_analyzed)
    
    # Set a safe contract size for demo trade test: 0.01 BTC (~$630 notional value, ~$210 margin)
    qty = 0.01
    sl_price = round(current_price - (summary['atr_14'] * 1.5), 2)
    tp_price = round(current_price + (summary['atr_14'] * 2.5), 2)
    
    print("\n--- TEST ISLEMI DETAYLARI ---")
    print(f"Islem Tipi  : LONG (ALIM)")
    print(f"Sembol      : {config.SYMBOL}")
    print(f"Miktar      : {qty} BTC")
    print(f"Giris Fiyati: ${current_price:.2f}")
    print(f"Stop Loss   : ${sl_price}")
    print(f"Take Profit : ${tp_price}")
    
    # 4. Execute Market Buy Order
    print("\nExecuting Market Order on Binance Futures Testnet...")
    market_res = executor.place_market_order(config.SYMBOL, "BUY", qty)
    
    if market_res:
        time.sleep(1)
        # 5. Place SL and TP
        executor.place_stop_loss_order(config.SYMBOL, "LONG", sl_price, qty)
        executor.place_take_profit_order(config.SYMBOL, "LONG", tp_price, qty)
        
        # 6. Verify Position
        time.sleep(1)
        pos = executor.get_open_position(config.SYMBOL)
        print(f"\n[SUCCESS] Binance Testnet Pozisyonu Basariyla Acildi!")
        print(f"   Pozisyon    : {pos['side']} {pos['amount']} BTC")
        print(f"   Giris Fiyati: ${pos['entry_price']}")
        print(f"   Unrealized PnL: ${pos['unrealized_pnl']}")
        
        # 7. Notify via Telegram
        notifier.send_trade_alert(
            action="LONG (DEMO CANLI TEST)",
            price=current_price,
            qty=qty,
            sl=sl_price,
            tp=tp_price,
            reasoning="Binance Demo ekranında canlı görünürlük testi için alım emri iletildi."
        )
        print("Telegram bildirimi gonderildi!")
    else:
        print("[FAIL] Islem basarisiz oldu!")

if __name__ == "__main__":
    place_test_trade()
