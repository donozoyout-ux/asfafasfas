import os
import threading
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request

import config
import trade_logger
from main import BotController

app = Flask(__name__)

bot_instance = None


def load_dashboard_html():
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    dashboard_path = os.path.join(template_dir, "dashboard.html")
    try:
        with open(dashboard_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<html><body><h1>Dashboard template not found</h1></body></html>"


@app.route('/')
def index():
    return load_dashboard_html()


@app.route('/api/status')
def api_status():
    if bot_instance:
        status_data = bot_instance.get_dashboard_state()
    else:
        status_data = {}
    return jsonify(status_data)


@app.route('/api/trades')
def api_trades():
    trades = trade_logger.get_recent_trades(limit=20)
    return jsonify(trades)


@app.route('/api/action', methods=['POST'])
def api_action():
    body = request.get_json() or {}
    action = body.get('action', '')
    result_msg = 'Invalid action'

    if bot_instance:
        if action == 'analyze':
            bot_instance.trigger_manual_ai_analysis()
            result_msg = 'Groq AI Market Analysis triggered!'
        elif action == 'toggle_pause':
            bot_instance.paused = not bot_instance.paused
            state = 'PAUSED' if bot_instance.paused else 'ACTIVE'
            result_msg = f'Bot state toggled to {state}'
        elif action == 'close':
            bot_instance.manual_close_position()
            result_msg = 'Emergency Close Order sent!'
        elif action == 'force_trade':
            bot_instance.force_test_trade()
            result_msg = 'Force test trade executed on Binance Futures Testnet!'

    return jsonify({'success': True, 'message': result_msg})


@app.route('/api/webhook/tradingview', methods=['POST'])
def api_webhook():
    body = request.get_json() or {}
    action = str(body.get('action', '')).upper()
    msg = f'TradingView Alert Received: {action}'

    if bot_instance:
        if action in ('BUY', 'LONG'):
            bot_instance.force_test_trade()
            msg = 'TradingView Webhook: LONG Signal Received & Executed!'
        elif action in ('SELL', 'SHORT'):
            bot_instance.force_test_trade()
            msg = 'TradingView Webhook: SHORT Signal Received & Executed!'
        elif action == 'CLOSE':
            bot_instance.manual_close_position()
            msg = 'TradingView Webhook: Close Signal Received!'

    return jsonify({'success': True, 'message': msg})


def start_bot():
    global bot_instance
    trade_logger.init_db()
    bot_instance = BotController(dry_run=False)
    bot_instance.start()


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=port, debug=False)