function fmtUsd(n) {
    return '$' + (Number(n) || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n) {
    const v = Number(n) || 0;
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const d = await res.json();

        const priceEl = document.getElementById('btc-price');
        if (priceEl) priceEl.textContent = fmtUsd(d.price);

        const chgEl = document.getElementById('btc-change');
        if (chgEl) {
            const chg = d.price_change_24h || 0;
            chgEl.textContent = fmtPct(chg);
            chgEl.className = 'text-[12px] font-label-mono font-bold ' + (chg >= 0 ? 'text-primary-container' : 'text-error');
        }

        const balEl = document.getElementById('usdt-balance');
        if (balEl) balEl.textContent = fmtUsd(d.balance);

        const pnlEl = document.getElementById('daily-pnl');
        if (pnlEl) {
            const pnl = d.daily_pnl || 0;
            pnlEl.textContent = 'PnL: ' + (pnl >= 0 ? '+' : '') + fmtUsd(pnl);
            pnlEl.className = 'text-[12px] font-label-mono font-bold ' + (pnl >= 0 ? 'text-primary-container' : 'text-error');
        }

        const targetLbl = document.getElementById('daily-target-label');
        const stopLbl = document.getElementById('max-stop-label');
        if (targetLbl) targetLbl.textContent = 'Target %' + (d.daily_target_pct || 1).toFixed(1);
        if (stopLbl) stopLbl.textContent = 'Max Stop %' + (d.max_drawdown_pct || 3).toFixed(1);

        const prog = document.getElementById('daily-progress');
        if (prog) {
            const pct = Math.min(100, Math.max(0, ((d.daily_pnl_pct || 0) / (d.daily_target_pct || 1)) * 100));
            prog.style.width = pct + '%';
        }

        const pos = d.position || {};
        const posSide = document.getElementById('pos-side');
        if (posSide) {
            const side = pos.side && pos.side !== 'FLAT' ? pos.side : 'FLAT';
            posSide.textContent = side === 'FLAT' ? 'YOK' : side;
            posSide.className = side === 'LONG' ? 'text-primary-container font-bold' :
                side === 'SHORT' ? 'text-error font-bold' : 'text-on-surface-variant font-bold';
        }
        const posDetails = document.getElementById('pos-details');
        const posPnl = document.getElementById('pos-pnl');
        if (pos.side && pos.side !== 'FLAT') {
            if (posDetails) posDetails.textContent = pos.amount + ' BTC @ ' + fmtUsd(pos.entry_price);
            if (posPnl) {
                const upnl = pos.unrealized_pnl || 0;
                posPnl.textContent = (upnl >= 0 ? '+' : '') + fmtUsd(upnl);
                posPnl.className = 'font-bold font-label-mono text-[11px] ' + (upnl >= 0 ? 'text-primary-container' : 'text-error');
            }
        } else {
            if (posDetails) posDetails.textContent = 'Açık pozisyon yok';
            if (posPnl) posPnl.textContent = '$0.00';
        }

        const ai = d.ai_decision || {};
        const aiAction = document.getElementById('ai-action');
        if (aiAction) aiAction.textContent = (ai.action || 'HOLD').toUpperCase();
        const aiConf = document.getElementById('ai-confidence');
        if (aiConf) aiConf.textContent = '%' + (ai.confidence || 0) + ' GÜVEN SEVİYESİ';
        const aiReason = document.getElementById('ai-reasoning');
        if (aiReason) aiReason.textContent = ai.reasoning || 'Piyasa taranıyor...';

        const ind = d.indicators || {};
        const rsiVal = document.getElementById('rsi-val');
        if (rsiVal) rsiVal.textContent = ind.rsi_14 ?? '—';
        const rsiBar = document.getElementById('rsi-bar');
        if (rsiBar) rsiBar.style.width = Math.min(100, Math.max(0, ind.rsi_14 || 0)) + '%';
        const ema200 = document.getElementById('ema-200');
        if (ema200) ema200.textContent = fmtUsd(ind.ema_200);
        const emaNote = document.getElementById('ema-trend-note');
        if (emaNote) {
            const above = (d.price || 0) > (ind.ema_200 || 0);
            emaNote.textContent = above ? 'Price above EMA' : 'Price below EMA';
            emaNote.className = 'text-[10px] font-label-mono ' + (above ? 'text-primary-container' : 'text-error');
        }
        const sup = document.getElementById('support-val');
        const res = document.getElementById('resistance-val');
        const mid = document.getElementById('current-price-mid');
        if (sup) sup.textContent = fmtUsd(ind.support);
        if (res) res.textContent = fmtUsd(ind.resistance);
        if (mid) mid.textContent = fmtUsd(d.price);

        const mkt = document.getElementById('market-status');
        if (mkt) {
            if (ind.crash_alert) {
                mkt.textContent = ind.crash_message || 'Uyarı';
                mkt.parentElement.className = 'flex items-center gap-1.5 px-2 py-0.5 bg-error/10 border border-error/30 rounded';
            } else {
                mkt.textContent = 'Market Durumu Normal';
                mkt.parentElement.className = 'flex items-center gap-1.5 px-2 py-0.5 bg-primary-container/10 border border-primary-container/20 rounded';
            }
        }

        const botStatus = document.getElementById('bot-status');
        if (botStatus) {
            botStatus.textContent = d.status === 'PAUSED' ? 'BOT DURAKLATILDI' : 'RENDER 24/7 CLOUD ACTIVE';
        }

        const apiSt = document.getElementById('api-status');
        if (apiSt) apiSt.textContent = d.last_update ? 'API CONNECTED · ' + d.last_update : 'API CONNECTED';
    } catch (e) {
        console.error(e);
        const apiSt = document.getElementById('api-status');
        if (apiSt) apiSt.textContent = 'API BAĞLANTI HATASI';
    }
}

async function fetchTrades() {
    try {
        const res = await fetch('/api/trades');
        const trades = await res.json();
        const tbody = document.getElementById('trade-table-body');
        const countEl = document.getElementById('trade-count');
        if (!tbody) return;
        if (!trades || trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="px-4 py-6 text-center text-on-surface-variant font-label-mono text-[12px]">Henüz işlem kaydı yok.</td></tr>';
            if (countEl) countEl.textContent = 'Görüntülenen: 0 kayıt';
            return;
        }
        tbody.innerHTML = trades.map(t => {
            const pnl = t.pnl_usdt;
            const pnlCell = t.status === 'OPEN'
                ? '<span class="text-on-surface-variant">AÇIK</span>'
                : '<span class="' + (pnl >= 0 ? 'text-primary-container' : 'text-error') + '">' +
                    (pnl >= 0 ? '+' : '') + fmtUsd(pnl) + '</span>';
            const sideClass = t.side === 'LONG' ? 'text-primary-container' : 'text-error';
            return '<tr class="hover:bg-surface-container-highest/20 transition-colors">' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">#' + t.id + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px] ' + sideClass + ' font-bold">' + t.side + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">' + t.symbol + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">' + fmtUsd(t.entry_price) + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">' + t.quantity + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">' + fmtUsd(t.sl_price) + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">' + fmtUsd(t.tp_price) + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">%' + t.ai_confidence + '</td>' +
                '<td class="px-4 py-3 font-label-mono text-[12px]">' + pnlCell + '</td></tr>';
        }).join('');
        if (countEl) countEl.textContent = 'Görüntülenen: ' + trades.length + ' kayıt';
    } catch (e) {
        console.error(e);
    }
}

async function triggerAction(action) {
    try {
        const res = await fetch('/api/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action })
        });
        const data = await res.json();
        if (data.message) alert(data.message);
        fetchStatus();
        fetchTrades();
    } catch (e) {
        alert('Hata: ' + e);
    }
}

function updateTime() {
    const el = document.getElementById('current-time');
    if (!el) return;
    const now = new Date();
    el.innerText = now.toISOString().split('T')[1].split('.')[0] + ' UTC';
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-analyze')?.addEventListener('click', () => triggerAction('analyze'));
    document.getElementById('btn-pause')?.addEventListener('click', () => triggerAction('toggle_pause'));
    ['btn-test', 'btn-test-mobile', 'btn-quick-exec'].forEach(id => {
        document.getElementById(id)?.addEventListener('click', () => triggerAction('force_trade'));
    });
    document.getElementById('btn-close')?.addEventListener('click', () => triggerAction('close'));
    document.getElementById('btn-refresh-trades')?.addEventListener('click', () => fetchTrades());

    fetchStatus();
    fetchTrades();
    setInterval(fetchStatus, 4000);
    setInterval(fetchTrades, 10000);
    setInterval(updateTime, 1000);
    updateTime();
});
