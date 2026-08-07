import sqlite3
conn = sqlite3.connect('trades.db')
c = conn.cursor()

# Check OPEN trades
c.execute('SELECT id, side, entry_price, timestamp FROM trades WHERE status = "OPEN"')
open_trades = c.fetchall()
print("OPEN trades:")
for t in open_trades:
    print(f"  ID {t[0]}: {t[1]} @ ${t[2]:.2f} ({t[3]})")

# Mark them as EXPIRED since bot has no position
c.execute('UPDATE trades SET status = "EXPIRED", exit_price = entry_price, pnl_usdt = 0, pnl_pct = 0, hold_time_min = 0 WHERE status = "OPEN"')
print(f"\nMarked {c.rowcount} OPEN trades as EXPIRED")

conn.commit()
conn.close()

# Verify
conn = sqlite3.connect('trades.db')
c = conn.cursor()
c.execute('SELECT status, COUNT(*) FROM trades GROUP BY status')
print("\nAfter cleanup:")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")
conn.close()