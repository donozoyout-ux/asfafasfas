function fmtUsd(n) {
    return '$' + (Number(n) || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(n) {
    const v = Number(n) || 0;
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
}
function num(n, d) {
    const v = Number(n);
    if (isNaN(v)) return d ?? '—';
    return d !== undefined ? v.toFixed(d) : v;
}

let lastAction = 'HOLD';

function loadTradingViewChart() {
    const el = document.getElementById('tradingview-chart');
    if (!el || window.tvChartLoaded) return;
    window.tvChartLoaded = true;
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/tv.js';
    script.async = true;
    script.onload = () => {
        if (typeof TradingView === 'undefined') return;
        new TradingView.widget({
            container_id: 'tradingview-chart',
            symbol: 'BINANCE:BTCUSDT',
            interval: '15',
            theme: 'dark',
            style: '1',
            locale: 'tr',
            autosize: true,
            studies: ['RSI@tv-basicstudies', 'MASimple@tv-basicstudies'],
            enable_publishing: false,
            hide_side_toolbar: true,
            withdateranges: false,
            save_image: false,
            backgroundColor: '#0a0e14',
            gridColor: '#1e2836'
        });
    };
    el.appendChild(script);
}

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const d = await res.json();
        const ind = d.indicators || {};
        const pos = d.position || {};
        const ai = d.ai_decision || {};
        const mf = d.multiframe || {};
        const news = d.news || {};
        const deriv = d.derivatives || {};

        const price = num(d.price, 0);
        const set = (id, txt, cls) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (cls) el.className = 'card-value ' + cls;
            el.textContent = txt;
        };

        set('btc-price', fmtUsd(price));
        const chg = d.price_change_24h || 0;
        const chgEl = document.getElementById('btc-change');
        if (chgEl) { chgEl.textContent = fmtPct(chg); chgEl.className = chg >= 0 ? 'up' : 'down'; }

        set('usdt-balance', fmtUsd(d.balance));

        const dpnl = d.daily_pnl || 0;
        set('daily-pnl', (dpnl >= 0 ? '+' : '') + fmtUsd(dpnl), dpnl >= 0 ? 'up' : 'down');
        const dpnlPct = document.getElementById('daily-pnl-pct');
        if (dpnlPct) {
            dpnlPct.textContent = fmtPct(d.daily_pnl_pct || 0) + ' · Hedef %' + (d.daily_target_pct || 1).toFixed(1);
            dpnlPct.className = 'card-sub ' + (dpnl >= 0 ? 'up' : 'down');
        }

        const posSide = document.getElementById('pos-side');
        if (posSide) {
            if (pos.side && pos.side !== 'FLAT') {
                posSide.textContent = pos.side;
                posSide.className = 'card-value ' + (pos.side === 'LONG' ? 'up' : 'down');
            } else {
                posSide.textContent = 'YOK';
                posSide.className = 'card-value flat';
            }
        }
        const posDetails = document.getElementById('pos-details');
        if (posDetails) {
            if (pos.side && pos.side !== 'FLAT') {
                posDetails.innerHTML = num(pos.amount, 3) + ' BTC @ ' + fmtUsd(pos.entry_price) +
                    ' · UnPNL <span class="' + (pos.unrealized_pnl >= 0 ? 'up' : 'down') + '">' +
                    (pos.unrealized_pnl >= 0 ? '+' : '') + fmtUsd(pos.unrealized_pnl) + '</span>';
            } else {
                posDetails.textContent = 'Açık pozisyon yok';
            }
        }

        const action = (ai.action || 'HOLD').toUpperCase();
        lastAction = action;
        const aiAction = document.getElementById('ai-action');
        if (aiAction) {
            aiAction.textContent = action;
            aiAction.className = 'ai-action ' + (action === 'LONG' ? 'long' : action === 'SHORT' ? 'short' : 'hold');
        }
        const aiConf = document.getElementById('ai-confidence');
        if (aiConf) aiConf.textContent = '%' + num(ai.confidence, 0) + ' GÜVEN';
        const confFill = document.getElementById('conf-fill');
        if (confFill) confFill.style.width = Math.min(100, Math.max(0, ai.confidence || 0)) + '%';
        const aiReason = document.getElementById('ai-reasoning');
        if (aiReason) aiReason.textContent = ai.reasoning || 'Piyasa taranıyor...';

        const rsiVal = document.getElementById('rsi-val');
        if (rsiVal) {
            const rsi = num(ind.rsi_14, 1);
            rsiVal.textContent = rsi;
            rsiVal.className = 'ind-val ' + (rsi >= 70 || rsi <= 30 ? (rsi >= 70 ? 'down' : 'up') : '');
        }
        const rsiNote = document.getElementById('rsi-note');
        if (rsiNote) {
            const s = ind.rsi_status || 'NEUTRAL';
            rsiNote.textContent = s + (ind.rsi_divergence && ind.rsi_divergence !== 'NONE' ? ' · ' + ind.rsi_divergence : '');
            rsiNote.className = 'ind-note ' + (s === 'OVERBOUGHT' || s === 'OVERSOLD' ? (s === 'OVERBOUGHT' ? 'down' : 'up') : 'flat');
        }
        const ema200 = document.getElementById('ema-200');
        if (ema200) ema200.textContent = fmtUsd(ind.ema_200);
        const emaNote = document.getElementById('ema-trend-note');
        if (emaNote) {
            const above = (d.price || 0) > (ind.ema_200 || 0);
            emaNote.textContent = above ? 'Fiyat EMA üzerinde' : 'Fiyat EMA altında';
            emaNote.className = 'ind-note ' + (above ? 'up' : 'down');
        }
        const atrVal = document.getElementById('atr-val');
        if (atrVal) atrVal.textContent = fmtUsd(ind.atr_14);
        const mkt = document.getElementById('market-structure');
        if (mkt) {
            const ms = ind.market_structure || 'N/A';
            mkt.textContent = ms.length > 30 ? ms.slice(0, 30) + '...' : ms;
            mkt.className = 'ind-val ' + (ms.startsWith('BULLISH') ? 'up' : ms.startsWith('BEARISH') ? 'down' : 'flat');
        }
        const crashNote = document.getElementById('crash-note');
        if (crashNote) {
            crashNote.textContent = ind.crash_alert ? ('⚠️ ' + (ind.crash_message || 'Flash Crash Riski!')) : 'Normal market volatilitesi';
            crashNote.className = 'ind-note ' + (ind.crash_alert ? 'down' : 'flat');
        }

        const mfList = document.getElementById('mf-list');
        if (mfList && Object.keys(mf).length > 0) {
            mfList.innerHTML = Object.entries(mf).map(([tf, v]) => {
                const trend = (v.trend || 'N/A').toUpperCase();
                const icon = trend === 'BULLISH' ? '🟢' : trend === 'BEARISH' ? '🔴' : '⚪';
                return '<div class="mf-row"><span class="tf">' + tf + ' ' + icon + '</span>' +
                    '<span class="' + (trend === 'BULLISH' ? 'up' : trend === 'BEARISH' ? 'down' : 'flat') + '">' +
                    trend + '</span><span style="color:var(--muted);">' + fmtUsd(v.last_close) + '</span></div>';
            }).join('');
        }

        const newsEl = document.getElementById('news-sentiment');
        if (newsEl) {
            const label = (news.sentiment_label || 'NEUTRAL').toUpperCase();
            const sc = Number(news.sentiment_score) || 0;
            newsEl.textContent = label + ' (' + (sc >= 0 ? '+' : '') + sc.toFixed(2) + ')';
            newsEl.className = 'card-value ' + (label === 'BULLISH' ? 'up' : label === 'BEARISH' ? 'down' : 'flat');
        }
        const newsSrc = document.getElementById('news-sources');
        if (newsSrc) {
            const fng = news.fear_greed_index;
            newsSrc.textContent = fng !== undefined && fng !== null
                ? 'F&G ' + fng + ' (' + (news.fear_greed_label || '') + ') · ' + (news.sources || 0) + ' kaynak'
                : (news.sources || 0) + ' kaynak';
        }
        const headlines = document.getElementById('news-headlines');
        if (headlines) {
            const tops = (news.top_headlines || []).slice(0, 3);
            headlines.textContent = tops.length ? '• ' + tops.join('\n• ') : 'Haber çekilemedi';
        }
        const fundingEl = document.getElementById('funding-rate');
        if (fundingEl) {
            const fr = num(deriv.funding_rate_pct, 5);
            fundingEl.textContent = fmtPct(fr);
            fundingEl.className = 'card-value ' + (Math.abs(fr) >= 0.05 ? (fr > 0 ? 'down' : 'up') : 'flat');
        }
        const oiEl = document.getElementById('open-interest');
        if (oiEl) oiEl.textContent = num(deriv.open_interest, 0) ? num(deriv.open_interest, 0).toLocaleString('en-US') + ' BTC' : '—';

        const ad = d.adaptive || {};
        const adaptEl = document.getElementById('adaptive-info');
        if (adaptEl && ad.leverage) {
            adaptEl.textContent = 'Otomatik: ' + ad.leverage + 'x kaldıraç · SL ' + ad.sl_multiplier + 'x ATR · TP ' + ad.tp_multiplier + 'x ATR (ATR% ' + num(ad.atr_pct, 2) + ')';
        }

        const st = d.settings || {};
        if (st && Object.keys(st).length) {
            if (!settingsDirty) {
                const setVal = (id, v, dflt) => { const el = document.getElementById(id); if (el && el.value === '') el.value = v ?? dflt; };
                setVal('set-leverage', st.leverage, 3);
                setVal('set-risk', st.risk_per_trade_pct !== undefined ? (st.risk_per_trade_pct * 100).toFixed(1) : 2.0);
                setVal('set-confidence', st.confidence_threshold, 50);
                setVal('set-interval', st.check_interval_seconds, 20);
                setVal('set-sl', st.sl_multiplier, 1.5);
                setVal('set-tp', st.tp_multiplier, 2.5);
                setVal('set-target', st.daily_target_profit_pct !== undefined ? (st.daily_target_profit_pct * 100).toFixed(1) : 2.0);
                setVal('set-dd', st.max_daily_drawdown_pct !== undefined ? (st.max_daily_drawdown_pct * 100).toFixed(1) : 5.0);
            }
        }

        const setPair = (id, v, up) => {
            const el = document.getElementById(id);
            if (el) { el.textContent = fmtUsd(v); el.className = up !== undefined ? (up ? 'up' : 'down') : ''; }
        };
        setPair('resistance-val', ind.resistance, (d.price || 0) < (ind.resistance || 0));
        setPair('support-val', ind.support, (d.price || 0) > (ind.support || 0));
        setPair('current-price-mid', d.price);
        const riskInfo = document.getElementById('risk-info');
        if (riskInfo) {
            riskInfo.textContent = '%' + (d.max_drawdown_pct || 0).toFixed(1) + ' stop · Kaldıraç ' + (d.leverage || 1) + 'x';
            riskInfo.className = 'flat';
        }

        const botStatus = document.getElementById('bot-status');
        if (botStatus) {
            if (d.status === 'PAUSED') {
                botStatus.textContent = 'BOT DURAKLATILDI';
                botStatus.className = 'status-pill paused';
            } else {
                botStatus.textContent = 'RENDER 24/7 AKTİF';
                botStatus.className = 'status-pill';
            }
        }

        const apiSt = document.getElementById('api-status');
        if (apiSt) apiSt.textContent = d.last_update ? 'API BAĞLI · ' + d.last_update : 'API BAĞLI';
    } catch (e) {
        console.error(e);
        const apiSt = document.getElementById('api-status');
        if (apiSt) apiSt.textContent = 'API BAĞLANTI HATASI';
        const botStatus = document.getElementById('bot-status');
        if (botStatus) { botStatus.textContent = 'BAĞLANTI YOK'; botStatus.className = 'status-pill error'; }
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
            tbody.innerHTML = '<tr><td colspan="9"><div class="empty">Henüz işlem kaydı yok.</div></td></tr>';
            if (countEl) countEl.textContent = '0 kayıt';
            return;
        }
        tbody.innerHTML = trades.map(t => {
            const pnl = t.pnl_usdt || 0;
            let pnlCell;
            if (t.status === 'OPEN') {
                pnlCell = '<span class="badge open">AÇIK</span>';
            } else {
                pnlCell = '<span class="' + (pnl >= 0 ? 'up' : 'down') + '">' +
                    (pnl >= 0 ? '+' : '') + fmtUsd(pnl) + '</span>';
            }
            const badge = t.side === 'LONG'
                ? '<span class="badge long">LONG</span>'
                : t.side === 'SHORT' ? '<span class="badge short">SHORT</span>' : t.side;
            return '<tr>' +
                '<td>#' + t.id + '</td>' +
                '<td>' + badge + '</td>' +
                '<td>' + t.symbol + '</td>' +
                '<td>' + fmtUsd(t.entry_price) + '</td>' +
                '<td>' + t.quantity + '</td>' +
                '<td>' + fmtUsd(t.sl_price) + '</td>' +
                '<td>' + fmtUsd(t.tp_price) + '</td>' +
                '<td>%' + t.ai_confidence + '</td>' +
                '<td>' + pnlCell + '</td></tr>';
        }).join('');
        if (countEl) countEl.textContent = trades.length + ' kayıt';
    } catch (e) {
        console.error(e);
    }
}

async function triggerAction(action) {
    const btnMap = { analyze: 'btn-analyze', toggle_pause: 'btn-pause', force_trade: 'btn-test', close: 'btn-close' };
    const btn = document.getElementById(btnMap[action]);
    const orig = btn ? btn.textContent : '';
    try {
        if (btn) { btn.disabled = true; btn.style.opacity = '0.6'; }
        const res = await fetch('/api/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action })
        });
        const data = await res.json();
        if (data.message) {
            const toast = document.createElement('div');
            toast.style.cssText = 'position:fixed;bottom:60px;left:50%;transform:translateX(-50%);' +
                'background:var(--panel);border:1px solid var(--green);color:var(--text);' +
                'padding:10px 18px;border-radius:8px;font-size:13px;z-index:99;box-shadow:0 4px 20px rgba(0,0,0,0.4);';
            toast.textContent = data.message;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }
        fetchStatus();
        fetchTrades();
    } catch (e) {
        alert('Hata: ' + e);
    } finally {
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
}

let settingsDirty = false;

function showToast(msg, ok = true) {
    const toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;bottom:60px;left:50%;transform:translateX(-50%);' +
        'background:var(--panel);border:1px solid ' + (ok ? 'var(--green)' : 'var(--red)') + ';color:var(--text);' +
        'padding:10px 18px;border-radius:8px;font-size:13px;z-index:99;box-shadow:0 4px 20px rgba(0,0,0,0.4);' +
        'max-width:80%;text-align:center;';
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

async function saveSettings() {
    const payload = {
        settings: {
            leverage: parseFloat(document.getElementById('set-leverage')?.value),
            risk_per_trade_pct: parseFloat(document.getElementById('set-risk')?.value) / 100,
            confidence_threshold: parseFloat(document.getElementById('set-confidence')?.value),
            check_interval_seconds: parseFloat(document.getElementById('set-interval')?.value),
            sl_multiplier: parseFloat(document.getElementById('set-sl')?.value),
            tp_multiplier: parseFloat(document.getElementById('set-tp')?.value),
            daily_target_profit_pct: parseFloat(document.getElementById('set-target')?.value) / 100,
            max_daily_drawdown_pct: parseFloat(document.getElementById('set-dd')?.value) / 100
        }
    };
    const btn = document.getElementById('btn-save-settings');
    try {
        if (btn) { btn.disabled = true; btn.style.opacity = '0.6'; }
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        showToast(data.message || 'Ayarlar kaydedildi', !!data.success);
        settingsDirty = false;
        fetchStatus();
    } catch (e) {
        showToast('Hata: ' + e, false);
    } finally {
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
}

async function openManualTrade() {
    const side = document.getElementById('trade-side')?.value || 'LONG';
    const qty = parseFloat(document.getElementById('trade-qty')?.value) || 0.002;
    const sl = parseFloat(document.getElementById('trade-sl')?.value) || 1.5;
    const tp = parseFloat(document.getElementById('trade-tp')?.value) || 2.5;
    const btn = document.getElementById('btn-trade');
    try {
        if (btn) { btn.disabled = true; btn.style.opacity = '0.6'; }
        const res = await fetch('/api/manual_trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ side, qty, sl_mult: sl, tp_mult: tp })
        });
        const data = await res.json();
        showToast(data.message || 'İşlem gönderildi', !!data.success);
        fetchStatus();
        fetchTrades();
    } catch (e) {
        showToast('Hata: ' + e, false);
    } finally {
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
}

async function loadReport(type) {
    const content = document.getElementById('report-content');
    if (!content) return;
    content.innerHTML = '<div class="empty">Yükleniyor...</div>';
    document.querySelectorAll('.report-tab').forEach(t => t.classList.toggle('active', t.dataset.report === type));
    try {
        const res = await fetch('/api/reports/' + type);
        const data = await res.json();
        let cards;
        if (type === 'risk') {
            const s = data.status || 'ACTIVE';
            cards = [
                ['Durum', s === 'TARGET_MET' ? '🎯 HEDEF' : s === 'CIRCUIT_BREAKER' ? '🛑 DUR' : '✅ AKTİF', s === 'TARGET_MET' ? 'up' : s === 'CIRCUIT_BREAKER' ? 'down' : ''],
                ['Günlük PnL', (data.daily_pnl >= 0 ? '+' : '') + fmtUsd(data.daily_pnl), data.daily_pnl >= 0 ? 'up' : 'down'],
                ['Günlük PnL %', fmtPct(data.daily_pnl_pct || 0), data.daily_pnl >= 0 ? 'up' : 'down'],
                ['Hedef', fmtPct(data.daily_target_pct || 0), ''],
                ['Max Kayıp', fmtPct(data.max_drawdown_pct || 0), ''],
                ['Risk/Trade', fmtPct(data.risk_per_trade_pct || 0), '']
            ];
            if (data.order_error_stats && Object.keys(data.order_error_stats).length) {
                const errs = Object.entries(data.order_error_stats).map(([k, v]) => `<div class="report-stat"><div class="v down">${v}</div><div class="k">${k}</div></div>`).join('');
                cards.push(['<span style="font-size:11px;">Hatalar</span>', errs, '']);
            }
        } else if (type === 'performance') {
            cards = [
                ['Kapalı İşlem', data.total_closed ?? 0, ''],
                ['Kazanç', data.wins ?? 0, 'up'],
                ['Kayıp', data.losses ?? 0, 'down'],
                ['Kazanma Oranı', (data.win_rate ?? 0) + '%', (data.win_rate ?? 0) >= 50 ? 'up' : 'down'],
                ['Toplam PnL', (data.total_pnl_usdt >= 0 ? '+' : '') + fmtUsd(data.total_pnl_usdt), (data.total_pnl_usdt ?? 0) >= 0 ? 'up' : 'down']
            ];
        } else {
            const report = (data.report || 'Veri yok').replace(/\*\*/g, '').replace(/^[-*]\s*/gm, '• ');
            content.innerHTML = '<div style="padding:16px 18px;font-size:12px;line-height:1.7;color:var(--muted);font-family:JetBrains Mono,monospace;white-space:pre-line;max-height:280px;overflow-y:auto;">' + report + '</div>';
            return;
        }
        content.innerHTML = cards.map(c =>
            '<div class="report-stat"><div class="v ' + (c[2] || '') + '">' + c[1] + '</div><div class="k">' + c[0] + '</div></div>'
        ).join('');
    } catch (e) {
        content.innerHTML = '<div class="empty">Rapor yüklenemedi: ' + e + '</div>';
    }
}

function updateTradeHint() {
    const s = document.getElementById('trade-side');
    const hint = document.getElementById('trade-side-hint');
    if (hint && s) {
        hint.textContent = s.value === 'LONG' ? '🟢 LONG seçili' : '🔴 SHORT seçili';
        hint.style.color = s.value === 'LONG' ? 'var(--green)' : 'var(--red)';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadTradingViewChart();
    document.getElementById('btn-analyze')?.addEventListener('click', () => triggerAction('analyze'));
    document.getElementById('btn-pause')?.addEventListener('click', () => triggerAction('toggle_pause'));
    document.getElementById('btn-test')?.addEventListener('click', () => triggerAction('force_trade'));
    document.getElementById('btn-close')?.addEventListener('click', () => triggerAction('close'));
    document.getElementById('btn-save-settings')?.addEventListener('click', saveSettings);
    document.getElementById('btn-trade')?.addEventListener('click', openManualTrade);
    document.getElementById('trade-side')?.addEventListener('change', updateTradeHint);
    document.querySelectorAll('#set-leverage,#set-risk,#set-confidence,#set-interval,#set-sl,#set-tp,#set-target,#set-dd')
        .forEach(el => el?.addEventListener('input', () => { settingsDirty = true; }));
    document.querySelectorAll('.report-tab').forEach(t =>
        t.addEventListener('click', () => loadReport(t.dataset.report))
    );

    fetchStatus();
    fetchTrades();
    loadReport('risk');
    setInterval(fetchStatus, 4000);
    setInterval(fetchTrades, 12000);
    setInterval(updateTime, 1000);
    updateTime();
    updateTradeHint();
});
