"""Data models for the trading bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Signal(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


@dataclass
class Ticker:
    symbol: str
    last_price: float
    bid: float
    ask: float
    high_24h: float
    low_24h: float
    volume_24h: float
    change_24h_pct: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OrderBookEntry:
    price: float
    quantity: float


@dataclass
class OrderBook:
    symbol: str
    bids: list[OrderBookEntry]
    asks: list[OrderBookEntry]
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def spread(self) -> float:
        if self.asks and self.bids:
            return self.asks[0].price - self.bids[0].price
        return 0.0

    @property
    def spread_pct(self) -> float:
        if self.asks and self.bids and self.bids[0].price > 0:
            return (self.spread / self.bids[0].price) * 100
        return 0.0


@dataclass
class Balance:
    currency: str
    available: float
    locked: float

    @property
    def total(self) -> float:
        return self.available + self.locked


@dataclass
class Order:
    id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    price: float | None
    status: OrderStatus
    filled_quantity: float = 0.0
    filled_price: float | None = None
    fee: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class TradeSignal:
    symbol: str
    signal: Signal
    confidence: float
    reasons: list[str]
    indicators: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
