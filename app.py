import os
import subprocess
import threading
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# Store latest trade output for UI
latest_output = ""

def run_trade():
    global latest_output
    # Set env vars for Binance API (already in env)
    env = os.environ.copy()
    # Execute the existing trade script
    proc = subprocess.Popen(
        ["python", "execute_test_trade.py"],
        cwd=os.path.abspath(os.path.dirname(__file__)),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    out_lines = []
    for line in proc.stdout:
        out_lines.append(line)
        latest_output = "".join(out_lines)
    proc.wait()
    latest_output = "".join(out_lines)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run-trade', methods=['POST'])
def start_trade():
    threading.Thread(target=run_trade, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"output": latest_output})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
