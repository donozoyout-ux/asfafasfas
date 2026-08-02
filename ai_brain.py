import os
import requests

OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")

def analyze_market_with_ai(indicator_summary: dict, ticker_24h: dict, multiframe_data: dict = None,
                           symbol: str = "BTCUSDT") -> dict:
    url = f"{OLLAMA_API_BASE}/analyze"
    payload = {
        "indicator_summary": indicator_summary,
        "ticker_24h": ticker_24h,
        "multiframe_data": multiframe_data,
        "symbol": symbol
    }
    headers = {'Content-Type': 'application/json'}
    
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error analyzing market with AI: {response.text}")
