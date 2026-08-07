import sqlite3
conn = sqlite3.connect('trades.db')
c = conn.cursor()
c.execute('SELECT COUNT(*), SUM(pnl_usdt) FROM trades WHERE status IN ("WIN", "LOSS")')
print('Closed:', c.fetchone())
c.execute('SELECT side, COUNT(*), SUM(pnl_usdt) FROM trades WHERE status IN ("WIN", "LOSS") GROUP BY side')
print('By side:', c.fetchall())
c.execute('SELECT status, COUNT(*) FROM trades GROUP BY status')
print('By status:', c.fetchall())