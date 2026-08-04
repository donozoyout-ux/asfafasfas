import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
import config

class BinanceFuturesExecutor:
    def __init__(self):
        self.base_url = config.BINANCE_FUTURES_URL
        self.api_key = config.BINANCE_API_KEY
        self.secret_key = config.BINANCE_SECRET_KEY
        self.headers = {"X-MBX-APIKEY": self.api_key}

    def _sign_request(self, params: dict) -> str:
        """Generates HMAC SHA256 signature for signed endpoints."""
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return f"{query_string}&signature={signature}"

    def set_leverage(self, symbol: str = config.SYMBOL, leverage: int = config.LEVERAGE) -> bool:
        """Sets leverage for the specified symbol."""
        endpoint = "/fapi/v1/leverage"
        params = {"symbol": symbol, "leverage": leverage}
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.post(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                print(f"[SUCCESS] Leverage set to {leverage}x for {symbol}")
                return True
            else:
                print(f"[WARN] Set leverage warning {res.status_code}: {res.text}")
                return False
        except Exception as e:
            print(f"[EXCEPT] Set leverage error: {e}")
            return False

    def get_account_balance(self, asset: str = "USDT") -> float:
        """
        Fetches total equity (margin balance) for the specified asset.
        marginBalance = walletBalance + unrealized PnL, so daily PnL reflects
        open position changes instead of only free (available) balance.
        """
        endpoint = "/fapi/v2/account"
        params = {}
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for a in data.get("assets", []):
                    if a["asset"] == asset:
                        return float(a["marginBalance"])
            else:
                print(f"[ERROR] Get balance error {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[EXCEPT] Get balance exception: {e}")
        return 0.0

    def get_realized_pnl(self, symbol: str = config.SYMBOL, start_ms: int = None, end_ms: int = None) -> dict:
        """
        Fetches realized PnL and commissions from Binance Futures income API.
        Returns dict with total_realized_pnl and total_commission.
        """
        endpoint = "/fapi/v1/income"
        params = {"symbol": symbol}
        if start_ms:
            params["startTime"] = start_ms
        if end_ms:
            params["endTime"] = end_ms
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        realized_pnl = 0.0
        commission = 0.0
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                for record in res.json():
                    income_type = record.get("incomeType", "")
                    amount = float(record.get("income", 0))
                    if income_type == "REALIZED_PNL":
                        realized_pnl += amount
                    elif income_type == "COMMISSION":
                        commission += amount
            else:
                print(f"[WARN] Get income error {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[EXCEPT] Get income exception: {e}")
        return {
            "realized_pnl": round(realized_pnl, 2),
            "commission": round(commission, 2),
            "net_pnl": round(realized_pnl + commission, 2)
        }

    def get_open_position(self, symbol: str = config.SYMBOL) -> dict:
        """
        Fetches current open position risk for the specified symbol.
        Returns position dict if position size > 0, or a FLAT dict.
        On API failure returns {"side": "FLAT", "error": True} so callers can
        distinguish a real FLAT from a transient fetch problem.
        """
        endpoint = "/fapi/v2/positionRisk"
        params = {"symbol": symbol}
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                positions = res.json()
                for pos in positions:
                    amt = float(pos.get("positionAmt", 0))
                    if amt != 0:
                        side = "LONG" if amt > 0 else "SHORT"
                        return {
                            "symbol": pos["symbol"],
                            "side": side,
                            "amount": abs(amt),
                            "entry_price": float(pos["entryPrice"]),
                            "unrealized_pnl": float(pos["unRealizedProfit"]),
                            "liquidation_price": float(pos["liquidationPrice"])
                        }
                return {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "liquidation_price": 0}
            else:
                print(f"[ERROR] Get position failed {res.status_code}: {res.text}")
                return {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "error": True}
        except Exception as e:
            print(f"[EXCEPT] Get position exception: {e}")
            return {"side": "FLAT", "amount": 0, "entry_price": 0, "unrealized_pnl": 0, "error": True}

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Places a Market Order (BUY or SELL)."""
        endpoint = "/fapi/v1/order"
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": quantity
        }
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.post(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                print(f"[SUCCESS] Market {side} order executed! OrderID: {data.get('orderId')}")
                return data
            else:
                print(f"[ERROR] Market order failed {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[EXCEPT] Market order exception: {e}")
        return {}

    def _place_algo_order(self, params: dict) -> dict:
        """Places a conditional (algo) order via /fapi/v1/algoOrder.

        Since 2025-12-09 Binance migrated conditional order types
        (STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT, TRAILING_STOP_MARKET)
        from /fapi/v1/order to the Algo Order endpoint. The legacy endpoint now
        returns error -4120 for these types.
        """
        endpoint = "/fapi/v1/algoOrder"
        params = dict(params)
        params.setdefault("algoType", "CONDITIONAL")
        params.setdefault("workingType", "MARK_PRICE")
        params.setdefault("reduceOnly", "true")
        params.setdefault("positionSide", "BOTH")
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.post(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return data
            else:
                print(f"[WARN] Algo order failed {res.status_code}: {res.text}")
                return {}
        except Exception as e:
            print(f"[EXCEPT] Algo order exception: {e}")
            return {}

    def place_stop_loss_order(self, symbol: str, position_side: str, stop_price: float, quantity: float) -> dict:
        """Places a STOP_MARKET order to protect position (Algo Order API)."""
        order_side = "SELL" if position_side.upper() == "LONG" else "BUY"
        params = {
            "symbol": symbol,
            "side": order_side,
            "type": "STOP_MARKET",
            "triggerPrice": round(stop_price, 2),
            "quantity": quantity
        }
        data = self._place_algo_order(params)
        if data:
            print(f"[SUCCESS] Stop Loss order set at ${stop_price:.2f} (algoId: {data.get('algoId')})")
        return data

    def place_take_profit_order(self, symbol: str, position_side: str, tp_price: float, quantity: float) -> dict:
        """Places a TAKE_PROFIT_MARKET order to lock in profit (Algo Order API)."""
        order_side = "SELL" if position_side.upper() == "LONG" else "BUY"
        params = {
            "symbol": symbol,
            "side": order_side,
            "type": "TAKE_PROFIT_MARKET",
            "triggerPrice": round(tp_price, 2),
            "quantity": quantity
        }
        data = self._place_algo_order(params)
        if data:
            print(f"[SUCCESS] Take Profit order set at ${tp_price:.2f} (algoId: {data.get('algoId')})")
        return data

    def cancel_all_open_orders(self, symbol: str = config.SYMBOL):
        """Cancels all open standard orders for symbol."""
        endpoint = "/fapi/v1/allOpenOrders"
        params = {"symbol": symbol}
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.delete(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                print(f"[SUCCESS] Cancelled all open orders for {symbol}")
        except Exception as e:
            print(f"[EXCEPT] Cancel orders exception: {e}")

    def cancel_all_open_algo_orders(self, symbol: str = config.SYMBOL):
        """Cancels all open algo (conditional) orders for symbol."""
        open_algo = self.get_open_algo_orders(symbol)
        if not open_algo:
            print(f"[INFO] No open algo orders to cancel for {symbol}")
            return
        for order in open_algo:
            algo_id = order.get("algoId") or order.get("id")
            if not algo_id:
                continue
            endpoint = "/fapi/v1/algoOrder"
            params = {"symbol": symbol, "algoId": algo_id}
            query = self._sign_request(params)
            url = f"{self.base_url}{endpoint}?{query}"
            try:
                res = requests.delete(url, headers=self.headers, timeout=10)
                if res.status_code == 200:
                    print(f"[SUCCESS] Cancelled algo order {algo_id}")
                else:
                    print(f"[WARN] Cancel algo order {algo_id} failed {res.status_code}: {res.text}")
            except Exception as e:
                print(f"[EXCEPT] Cancel algo order exception: {e}")

    def get_open_algo_orders(self, symbol: str = config.SYMBOL) -> list:
        """Lists open algo (conditional) orders for symbol."""
        endpoint = "/fapi/v1/openAlgoOrders"
        params = {"symbol": symbol}
        query = self._sign_request(params)
        url = f"{self.base_url}{endpoint}?{query}"

        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code == 200:
                return res.json()
            else:
                print(f"[WARN] Get algo orders failed {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[EXCEPT] Get algo orders exception: {e}")
        return []

    def close_position(self, symbol: str = config.SYMBOL) -> bool:
        """Closes any active position at Market Price."""
        pos = self.get_open_position(symbol)
        if pos["side"] == "FLAT" or pos["amount"] == 0:
            print("[INFO] No active position to close.")
            return True
            
        self.cancel_all_open_orders(symbol)
        self.cancel_all_open_algo_orders(symbol)
        order_side = "SELL" if pos["side"] == "LONG" else "BUY"
        res = self.place_market_order(symbol, order_side, pos["amount"])
        return bool(res)
