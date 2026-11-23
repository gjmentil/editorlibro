"""Main trading engine that orchestrates everything."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .alerts import AlertManager
from .client import RevolutXClient
from .database import Database
from .models import OrderType, Side
from .strategy import TradingStrategy
from .telegram_bot import TelegramBot

log = logging.getLogger(__name__)


class Trader:
    def __init__(self, config_path: str = "config.json"):
        self.config = json.loads(Path(config_path).read_text())
        self.dry_run = self.config.get("dry_run", True)
        self.symbols = self.config.get("symbols", ["BTC/EUR"])
        self.interval = self.config.get("check_interval_seconds", 60)

        self.client = RevolutXClient(
            api_key=self.config["api_key"],
            private_key_path=self.config["private_key_path"],
            base_url=self.config.get("base_url", "https://revx.revolut.com/api"),
            region=self.config.get("region", "EEA"),
        )
        self.db = Database()
        self.alerts = AlertManager(self.config.get("alerts", {}))
        self.strategy = TradingStrategy(self.config)
        self.positions: dict[str, float] = {}
        self.entry_prices: dict[str, float] = {}
        self._running = False
        self._last_tickers: list = []

        alerts_cfg = self.config.get("alerts", {})
        self.telegram = TelegramBot(
            token=alerts_cfg.get("telegram_bot_token", ""),
            chat_id=alerts_cfg.get("telegram_chat_id", ""),
        )
        self.alerts.telegram_bot = self.telegram

    def start(self):
        mode = "DRY RUN" if self.dry_run else "LIVE"
        self.alerts.info(f"Bot iniciado en modo {mode}")
        self.alerts.info(f"Simbolos: {', '.join(self.symbols)}")
        self.alerts.info(f"Intervalo: {self.interval}s")

        if self.telegram.enabled:
            self._register_telegram_commands()
            self.telegram.start_polling()
            self.telegram.send(f"🤖 <b>Bot iniciado en modo {mode}</b>\n{len(self.symbols)} cryptos monitorizadas\n/help para ver comandos")
            self.alerts.info("Telegram bot conectado")

        if not self.dry_run:
            self._load_positions()

        self._running = True
        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                self.alerts.info("Bot detenido por el usuario")
                break
            except Exception as e:
                self.alerts.error_alert(f"Error en tick: {e}")
                log.exception("Tick error")

            time.sleep(self.interval)

        self.telegram.stop()
        self.client.close()
        self.db.close()

    def stop(self):
        self._running = False

    def _register_telegram_commands(self):
        self.telegram.register_command("/precios", self._cmd_prices)
        self.telegram.register_command("/estado", self._cmd_status)
        self.telegram.register_command("/portfolio", self._cmd_portfolio)

    def _cmd_prices(self):
        try:
            tickers = self._last_tickers or self.client.get_tickers()
            watched = [t for t in tickers if t.symbol in self.symbols]
            watched.sort(key=lambda t: abs(t.change_24h_pct), reverse=True)
            self.telegram.send_prices(watched[:20])
        except Exception as e:
            self.telegram.send_error(str(e))

    def _cmd_status(self):
        try:
            daily = self.db.get_daily_pnl()
            total = self._estimate_portfolio_value("EUR")
            self.telegram.send_status(daily, self.positions, total)
        except Exception as e:
            self.telegram.send_error(str(e))

    def _cmd_portfolio(self):
        try:
            lines = ["📊 <b>Portfolio</b>\n"]
            has_positions = False
            for currency, qty in self.positions.items():
                if qty > 0:
                    has_positions = True
                    entry = self.entry_prices.get(f"{currency}/EUR", 0)
                    entry_str = f" (entrada: {entry:,.2f})" if entry else ""
                    lines.append(f"  • <b>{currency}</b>: {qty:.6f}{entry_str}")
            if not has_positions:
                lines.append("Sin posiciones abiertas")
            self.telegram.send("\n".join(lines))
        except Exception as e:
            self.telegram.send_error(str(e))

    def _load_positions(self):
        try:
            balances = self.client.get_balances()
            for b in balances:
                if b.available > 0:
                    self.positions[b.currency] = b.available
        except Exception as e:
            self.alerts.error_alert(f"Error cargando balances: {e}")

    def _tick(self):
        try:
            all_tickers = self.client.get_tickers()
            self._last_tickers = all_tickers
            ticker_map = {t.symbol: t for t in all_tickers}
        except Exception as e:
            self.alerts.error_alert(f"Error obteniendo tickers: {e}")
            return

        for symbol in self.symbols:
            try:
                ticker = ticker_map.get(symbol)
                if not ticker:
                    continue
                self._process_symbol(symbol, ticker)
            except Exception as e:
                self.alerts.error_alert(f"Error procesando {symbol}: {e}")

    def _process_symbol(self, symbol: str, ticker=None):
        if ticker is None:
            ticker = self.client.get_ticker(symbol)
        self.db.record_price(symbol, ticker.last_price, ticker.bid, ticker.ask, ticker.volume_24h)

        prices = self.db.get_price_history(symbol, limit=200)
        if len(prices) < 30:
            return

        base_currency = symbol.split("/")[0]
        quote_currency = symbol.split("/")[1] if "/" in symbol else "EUR"

        position = self.positions.get(base_currency, 0)
        entry_price = self.entry_prices.get(symbol, 0)

        if position > 0 and entry_price > 0:
            sl_tp = self.strategy.check_stop_loss_take_profit(
                symbol, ticker.last_price, entry_price, position
            )
            if sl_tp and sl_tp.action:
                self.alerts.signal_alert(sl_tp.signal)
                self._execute(symbol, sl_tp.side, sl_tp.order_type, sl_tp.quantity, sl_tp.reason)
                return

        quote_balance = None
        if not self.dry_run:
            quote_balance = self.client.get_balance(quote_currency)

        total_portfolio = self._estimate_portfolio_value(quote_currency)
        daily_trades = self.db.get_trades_today_count()
        daily_pnl = self.db.get_daily_loss()

        from .models import Balance
        if self.dry_run and quote_balance is None:
            quote_balance = Balance(currency=quote_currency, available=10000, locked=0)

        decision = self.strategy.evaluate(
            symbol=symbol,
            prices=prices,
            balance_quote=quote_balance,
            current_position=position,
            daily_trades=daily_trades,
            daily_pnl=daily_pnl,
            total_portfolio_value=total_portfolio,
        )

        if decision is None:
            return

        self.alerts.signal_alert(decision.signal)

        if decision.action and decision.side and decision.order_type:
            self._execute(symbol, decision.side, decision.order_type,
                          decision.quantity, decision.reason)

    def _execute(self, symbol: str, side: Side, order_type: OrderType,
                 quantity: float, reason: str = ""):
        base_currency = symbol.split("/")[0]

        if self.dry_run:
            self.alerts.trade_alert(symbol, side.value, quantity, None, order_type.value, dry_run=True)
            self.db.record_trade(
                order_id=f"DRY-{int(time.time()*1000)}",
                symbol=symbol, side=side.value, order_type=order_type.value,
                quantity=quantity, price=None, status="FILLED",
                strategy="combined", signal_data={"reason": reason},
            )
            if side == Side.BUY:
                self.positions[base_currency] = self.positions.get(base_currency, 0) + quantity
                prices = self.db.get_price_history(symbol, limit=1)
                if prices:
                    self.entry_prices[symbol] = prices[-1]
            elif side == Side.SELL:
                self.positions[base_currency] = max(0, self.positions.get(base_currency, 0) - quantity)
                if self.positions.get(base_currency, 0) == 0:
                    self.entry_prices.pop(symbol, None)
            return

        try:
            order = self.client.place_order(symbol, side, order_type, quantity)
            self.alerts.trade_alert(symbol, side.value, quantity, order.price, order_type.value)
            self.db.record_trade(
                order_id=order.id, symbol=symbol, side=side.value,
                order_type=order_type.value, quantity=quantity,
                price=order.price, status=order.status.value,
                strategy="combined", signal_data={"reason": reason},
            )

            if side == Side.BUY:
                self.positions[base_currency] = self.positions.get(base_currency, 0) + quantity
                if order.filled_price:
                    self.entry_prices[symbol] = order.filled_price
            elif side == Side.SELL:
                self.positions[base_currency] = max(0, self.positions.get(base_currency, 0) - quantity)
                if self.positions.get(base_currency, 0) == 0:
                    self.entry_prices.pop(symbol, None)

        except Exception as e:
            self.alerts.error_alert(f"Error ejecutando orden {side.value} {symbol}: {e}")

    def _estimate_portfolio_value(self, quote_currency: str) -> float:
        if self.dry_run:
            return 10000.0
        try:
            balances = self.client.get_balances()
            total = 0.0
            for b in balances:
                if b.currency == quote_currency:
                    total += b.available + b.locked
                elif b.total > 0:
                    try:
                        t = self.client.get_ticker(f"{b.currency}/{quote_currency}")
                        total += b.total * t.last_price
                    except Exception:
                        pass
            return total
        except Exception:
            return 0.0
