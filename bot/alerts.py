"""Alert system: console, log file, and optional Telegram."""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Signal, TradeSignal

console = Console()
log = logging.getLogger(__name__)


def _safe_log(logger_fn, message: str):
    try:
        logger_fn(message)
    except UnicodeEncodeError:
        logger_fn(message.encode("ascii", errors="replace").decode())


class AlertManager:
    def __init__(self, config: dict):
        self.console_enabled = config.get("console", True)
        self.log_file = config.get("log_file", "")
        self.telegram_bot = None

        if self.log_file:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
            log.addHandler(handler)

    def signal_alert(self, signal: TradeSignal):
        color = _signal_color(signal.signal)
        msg = (
            f"[{signal.signal.value}] {signal.symbol} | "
            f"Confianza: {signal.confidence:.0%} | "
            f"{', '.join(signal.reasons)}"
        )

        if self.console_enabled:
            console.print(Panel(msg, title=f"Signal {signal.symbol}", border_style=color))

        _safe_log(log.info, msg)
        if self.telegram_bot:
            self.telegram_bot.send_signal(signal.symbol, signal.signal.value, signal.confidence, signal.reasons, signal.indicators)

    def trade_alert(self, symbol: str, side: str, quantity: float, price: float | None, order_type: str, dry_run: bool = False):
        prefix = "[DRY RUN]" if dry_run else "[TRADE]"
        price_str = f"@ {price:.2f}" if price else "@ mercado"
        msg = f"{prefix} {side} {quantity} {symbol} {price_str} ({order_type})"

        if self.console_enabled:
            color = "green" if side == "BUY" else "red"
            console.print(f"[bold {color}]{msg}[/]")

        _safe_log(log.info, msg)
        if self.telegram_bot:
            self.telegram_bot.send_trade(symbol, side, quantity, price, dry_run)

    def error_alert(self, message: str):
        if self.console_enabled:
            console.print(f"[bold red]ERROR: {message}[/]")
        _safe_log(log.error, message)
        if self.telegram_bot:
            self.telegram_bot.send_error(message)

    def info(self, message: str):
        if self.console_enabled:
            console.print(f"[dim]{message}[/]")
        _safe_log(log.info, message)

    def status_table(self, balances: list, positions: dict, signals: dict):
        if not self.console_enabled:
            return

        table = Table(title=f"Estado del Bot - {datetime.now().strftime('%H:%M:%S')}")
        table.add_column("Moneda", style="cyan")
        table.add_column("Balance", justify="right")
        table.add_column("Signal", justify="center")
        table.add_column("Indicadores", style="dim")

        for b in balances:
            sig = signals.get(b.currency, None)
            sig_str = ""
            ind_str = ""
            if sig:
                color = _signal_color(sig.signal)
                sig_str = f"[{color}]{sig.signal.value}[/]"
                ind_str = " | ".join(f"{k}={v}" for k, v in list(sig.indicators.items())[:3])

            table.add_row(
                b.currency,
                f"{b.available:.6f}",
                sig_str,
                ind_str,
            )

        console.print(table)



def _signal_color(signal: Signal) -> str:
    return {
        Signal.STRONG_BUY: "bold green",
        Signal.BUY: "green",
        Signal.HOLD: "yellow",
        Signal.SELL: "red",
        Signal.STRONG_SELL: "bold red",
    }.get(signal, "white")
