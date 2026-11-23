"""Trading strategies with risk management."""

from __future__ import annotations

import logging

from .analyzer import TechnicalAnalyzer
from .models import Balance, OrderType, Side, Signal, TradeSignal

log = logging.getLogger(__name__)


class TradingStrategy:
    def __init__(self, config: dict):
        self.risk = config.get("risk", {})
        self.max_position_pct = self.risk.get("max_position_pct", 10)
        self.stop_loss_pct = self.risk.get("stop_loss_pct", 3.0)
        self.take_profit_pct = self.risk.get("take_profit_pct", 6.0)
        self.max_daily_trades = self.risk.get("max_daily_trades", 20)
        self.max_daily_loss_pct = self.risk.get("max_daily_loss_pct", 5.0)
        self.analyzer = TechnicalAnalyzer(config.get("indicators", {}))

    def evaluate(self, symbol: str, prices: list[float], balance_quote: Balance | None,
                 current_position: float, daily_trades: int, daily_pnl: float,
                 total_portfolio_value: float) -> TradeDecision | None:

        if daily_trades >= self.max_daily_trades:
            log.info("Max daily trades reached (%d)", self.max_daily_trades)
            return None

        if total_portfolio_value > 0:
            loss_pct = abs(min(daily_pnl, 0)) / total_portfolio_value * 100
            if loss_pct >= self.max_daily_loss_pct:
                log.info("Max daily loss reached (%.1f%%)", loss_pct)
                return None

        signal = self.analyzer.analyze(symbol, prices)

        if signal.signal == Signal.HOLD:
            return TradeDecision(signal=signal, action=None)

        current_price = prices[-1] if prices else 0

        if signal.signal in (Signal.BUY, Signal.STRONG_BUY):
            return self._evaluate_buy(signal, balance_quote, current_price,
                                      current_position, total_portfolio_value)

        if signal.signal in (Signal.SELL, Signal.STRONG_SELL):
            return self._evaluate_sell(signal, current_price, current_position)

        return TradeDecision(signal=signal, action=None)

    def _evaluate_buy(self, signal: TradeSignal, balance_quote: Balance | None,
                      current_price: float, current_position: float,
                      total_portfolio_value: float) -> TradeDecision:
        if not balance_quote or balance_quote.available <= 0 or current_price <= 0:
            return TradeDecision(signal=signal, action=None, reason="Sin balance disponible")

        max_spend = total_portfolio_value * (self.max_position_pct / 100)
        current_value = current_position * current_price
        remaining_budget = max(0, max_spend - current_value)
        spend = min(balance_quote.available * 0.95, remaining_budget)

        if spend < 1:
            return TradeDecision(signal=signal, action=None, reason="Presupuesto insuficiente")

        quantity = spend / current_price
        multiplier = 1.5 if signal.signal == Signal.STRONG_BUY else 1.0
        quantity *= min(multiplier, 1.0 + signal.confidence)

        quantity = spend / current_price

        stop_loss = current_price * (1 - self.stop_loss_pct / 100)
        take_profit = current_price * (1 + self.take_profit_pct / 100)

        return TradeDecision(
            signal=signal,
            action="BUY",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def _evaluate_sell(self, signal: TradeSignal, current_price: float,
                       current_position: float) -> TradeDecision:
        if current_position <= 0:
            return TradeDecision(signal=signal, action=None, reason="Sin posición para vender")

        sell_pct = 1.0 if signal.signal == Signal.STRONG_SELL else 0.5
        quantity = current_position * sell_pct

        return TradeDecision(
            signal=signal,
            action="SELL",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=current_price,
        )

    def check_stop_loss_take_profit(self, symbol: str, current_price: float,
                                     entry_price: float, position: float) -> TradeDecision | None:
        if position <= 0 or entry_price <= 0:
            return None

        change_pct = (current_price - entry_price) / entry_price * 100

        if change_pct <= -self.stop_loss_pct:
            return TradeDecision(
                signal=TradeSignal(symbol=symbol, signal=Signal.STRONG_SELL,
                                   confidence=1.0, reasons=[f"Stop loss activado ({change_pct:.1f}%)"]),
                action="SELL",
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=position,
                price=current_price,
                reason=f"STOP LOSS: {change_pct:.1f}%",
            )

        if change_pct >= self.take_profit_pct:
            return TradeDecision(
                signal=TradeSignal(symbol=symbol, signal=Signal.SELL,
                                   confidence=0.9, reasons=[f"Take profit activado ({change_pct:.1f}%)"]),
                action="SELL",
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=position * 0.75,
                price=current_price,
                reason=f"TAKE PROFIT: {change_pct:.1f}%",
            )

        return None


class TradeDecision:
    def __init__(self, signal: TradeSignal, action: str | None,
                 side: Side | None = None, order_type: OrderType | None = None,
                 quantity: float = 0, price: float = 0,
                 stop_loss: float | None = None, take_profit: float | None = None,
                 reason: str = ""):
        self.signal = signal
        self.action = action
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.price = price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.reason = reason
