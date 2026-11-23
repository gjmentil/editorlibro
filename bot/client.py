"""Revolut X API client."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .auth import load_private_key, sign_request
from .models import Balance, Order, OrderBook, OrderBookEntry, OrderStatus, OrderType, Side, Ticker

log = logging.getLogger(__name__)


class RevolutXClient:
    def __init__(self, api_key: str, private_key_path: str, base_url: str = "https://revx.revolut.com/api", region: str = "EEA"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.region = region
        self._private_key = load_private_key(private_key_path)
        self._http = httpx.Client(timeout=30, headers={"Content-Type": "application/json"})
        self._tickers_cache: dict[str, Ticker] = {}

    def close(self):
        self._http.close()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        return symbol.replace("-", "/")

    def _build_headers(self, method: str, path: str, query_params: dict | None = None, body: dict | None = None) -> dict:
        ts, sig = sign_request(self._private_key, method, path, query_params, body)
        return {
            "X-Revx-API-Key": self.api_key,
            "X-Revx-Timestamp": ts,
            "X-Revx-Signature": sig,
        }

    def _request(self, method: str, path: str, query_params: dict | None = None, body: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._build_headers(method, path, query_params, body)

        resp = self._http.request(
            method,
            url,
            headers=headers,
            params=query_params,
            json=body,
        )

        if resp.status_code >= 400:
            log.error("API error %d %s: %s", resp.status_code, path, resp.text[:300])
            resp.raise_for_status()

        if resp.status_code == 204:
            return None
        return resp.json()

    def _public_get(self, path: str, query_params: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._http.get(url, params=query_params)
        if resp.status_code >= 400:
            log.error("Public API error %d %s: %s", resp.status_code, path, resp.text[:300])
            resp.raise_for_status()
        return resp.json()

    # --- Market Data (public, no auth needed) ---

    def get_tickers(self) -> list[Ticker]:
        data = self._public_get("/1.0/public/tickers")
        items = data.get("data", []) if isinstance(data, dict) else data
        tickers = []
        for item in items:
            t = self._parse_ticker(item)
            tickers.append(t)
            self._tickers_cache[t.symbol] = t
        return tickers

    def get_ticker(self, symbol: str) -> Ticker:
        symbol = self.normalize_symbol(symbol)
        tickers = self.get_tickers()
        for t in tickers:
            if t.symbol == symbol:
                return t
        raise ValueError(f"Symbol {symbol} not found")

    def get_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        symbol = self.normalize_symbol(symbol)
        data = self._request("GET", "/1.0/public/order-book", query_params={"symbol": symbol, "limit": depth})
        bids = [OrderBookEntry(float(b[0]), float(b[1])) for b in data.get("bids", [])]
        asks = [OrderBookEntry(float(a[0]), float(a[1])) for a in data.get("asks", [])]
        return OrderBook(symbol=symbol, bids=bids, asks=asks)

    # --- Account (authenticated) ---

    def get_balances(self) -> list[Balance]:
        data = self._request("GET", "/1.0/balances")
        items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        balances = []
        for item in items:
            balances.append(Balance(
                currency=item.get("currency", item.get("asset", "")),
                available=float(item.get("available", item.get("free", 0))),
                locked=float(item.get("locked", item.get("used", 0))),
            ))
        return balances

    def get_balance(self, currency: str) -> Balance | None:
        for b in self.get_balances():
            if b.currency.upper() == currency.upper():
                return b
        return None

    # --- Orders (authenticated) ---

    def place_order(self, symbol: str, side: Side, order_type: OrderType, quantity: float, price: float | None = None) -> Order:
        symbol = self.normalize_symbol(symbol)
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "quantity": str(quantity),
        }
        if price is not None and order_type == OrderType.LIMIT:
            body["price"] = str(price)

        data = self._request("POST", "/1.0/orders", body=body)
        return self._parse_order(data)

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._request("DELETE", f"/1.0/orders/{order_id}")
            return True
        except httpx.HTTPStatusError:
            return False

    def get_order(self, order_id: str) -> Order:
        data = self._request("GET", f"/1.0/orders/{order_id}")
        return self._parse_order(data)

    def get_active_orders(self, symbol: str | None = None) -> list[Order]:
        params = {}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)
        data = self._request("GET", "/1.0/orders", query_params=params if params else None)
        items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return [self._parse_order(o) for o in items]

    def get_order_history(self, symbol: str | None = None, limit: int = 50) -> list[Order]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)
        data = self._request("GET", "/1.0/orders/history", query_params=params)
        items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        return [self._parse_order(o) for o in items]

    @staticmethod
    def _parse_ticker(data: dict) -> Ticker:
        return Ticker(
            symbol=data.get("symbol", ""),
            last_price=float(data.get("last_price", 0)),
            bid=float(data.get("bid", 0)),
            ask=float(data.get("ask", 0)),
            high_24h=float(data.get("high_24h", 0)),
            low_24h=float(data.get("low_24h", 0)),
            volume_24h=float(data.get("volume_24h", 0)),
            change_24h_pct=float(data.get("price_change_24h", 0)),
        )

    @staticmethod
    def _parse_order(data: dict) -> Order:
        return Order(
            id=data.get("id", data.get("order_id", "")),
            symbol=data.get("symbol", ""),
            side=Side(data.get("side", "BUY")),
            order_type=OrderType(data.get("type", "MARKET")),
            quantity=float(data.get("quantity", 0)),
            price=float(data["price"]) if data.get("price") else None,
            status=OrderStatus(data.get("status", "PENDING")),
            filled_quantity=float(data.get("filled_quantity", data.get("executed_quantity", 0))),
            filled_price=float(data["filled_price"]) if data.get("filled_price") else None,
            fee=float(data.get("fee", 0)),
        )
