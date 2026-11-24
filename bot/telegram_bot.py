"""Telegram bot with interactive commands and alerts."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import httpx

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._http = httpx.Client(timeout=30)
        self._last_update_id = 0
        self._running = False
        self._command_handlers: dict[str, callable] = {}
        self._poll_thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def verify(self) -> bool:
        if not self.enabled:
            log.warning("Telegram desactivado: falta token o chat_id")
            return False
        try:
            resp = self._http.get(f"{self.base_url}/getMe", timeout=10)
            if resp.status_code == 200:
                bot_info = resp.json().get("result", {})
                log.info("Telegram OK: @%s", bot_info.get("username", "?"))
                return True
            else:
                log.error("Telegram error: getMe devolvio %s - token invalido?", resp.status_code)
                return False
        except Exception as e:
            log.error("Telegram no accesible: %s", e)
            return False

    def start_polling(self):
        if not self.enabled:
            return
        if not self.verify():
            log.error("Telegram: polling NO iniciado por error de verificacion")
            return
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        log.info("Telegram bot polling started")

    def stop(self):
        self._running = False

    def register_command(self, command: str, handler):
        self._command_handlers[command] = handler

    def send(self, text: str, parse_mode: str = "HTML"):
        if not self.enabled:
            return
        try:
            self._http.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        except Exception as e:
            log.warning("Telegram send failed: %s", e)

    def send_signal(self, symbol: str, signal: str, confidence: float, reasons: list[str], indicators: dict):
        emoji = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "HOLD": "⚪", "SELL": "🔴", "STRONG_SELL": "🔴🔴"}.get(signal, "⚪")
        reason_text = "\n".join(f"  • {r}" for r in reasons)
        ind_text = "\n".join(f"  <code>{k}: {v}</code>" for k, v in indicators.items())

        text = (
            f"{emoji} <b>{signal}</b> — {symbol}\n"
            f"Confianza: {confidence:.0%}\n\n"
            f"<b>Razones:</b>\n{reason_text}\n\n"
            f"<b>Indicadores:</b>\n{ind_text}"
        )
        self.send(text)

    def send_trade(self, symbol: str, side: str, quantity: float, price: float | None, dry_run: bool = False):
        emoji = "🟢" if side == "BUY" else "🔴"
        mode = " (simulacion)" if dry_run else ""
        price_str = f"{price:,.2f} EUR" if price else "mercado"

        text = (
            f"{emoji} <b>TRADE{mode}</b>\n"
            f"{side} {quantity:.6f} {symbol}\n"
            f"Precio: {price_str}"
        )
        self.send(text)

    def send_error(self, message: str):
        self.send(f"⚠️ <b>Error:</b> {message}")

    def send_prices(self, tickers: list):
        lines = [f"📊 <b>Precios — {datetime.now().strftime('%H:%M')}</b>\n"]
        for t in tickers:
            emoji = "🟢" if t.change_24h_pct > 0 else "🔴"
            lines.append(f"{emoji} <b>{t.symbol}</b>: {t.last_price:,.2f} EUR ({t.change_24h_pct:+.2f})")
        self.send("\n".join(lines))

    def send_status(self, daily_stats: dict, positions: dict, total_value: float):
        pnl = daily_stats.get("pnl", 0)
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        pos_lines = []
        for symbol, qty in positions.items():
            if qty > 0:
                pos_lines.append(f"  • {symbol}: {qty:.6f}")

        text = (
            f"🤖 <b>Estado del Bot</b>\n\n"
            f"{pnl_emoji} P&L hoy: <b>{pnl:+,.2f} EUR</b>\n"
            f"📈 Trades hoy: {daily_stats.get('trades', 0)}\n"
            f"💰 Portfolio: {total_value:,.2f} EUR\n"
            f"📊 Comisiones: {daily_stats.get('fees', 0):.2f} EUR\n"
        )
        if pos_lines:
            text += f"\n<b>Posiciones:</b>\n" + "\n".join(pos_lines)
        else:
            text += "\nSin posiciones abiertas"

        self.send(text)

    def send_help(self):
        self.send(
            "🤖 <b>Comandos disponibles:</b>\n\n"
            "/precios — Precios actuales\n"
            "/estado — Estado del bot y P&L\n"
            "/portfolio — Posiciones abiertas\n"
            "/alertas — Activar/desactivar alertas\n"
            "/help — Este mensaje"
        )

    def _poll_loop(self):
        while self._running:
            try:
                resp = self._http.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": self._last_update_id + 1, "timeout": 10},
                    timeout=15,
                )
                if resp.status_code != 200:
                    time.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if chat_id != self.chat_id:
                        continue

                    cmd = text.split()[0].lower() if text else ""
                    if cmd.startswith("/"):
                        cmd = cmd.split("@")[0]
                        log.info("Telegram comando recibido: %s de chat %s", cmd, chat_id)
                        handler = self._command_handlers.get(cmd)
                        if handler:
                            try:
                                handler()
                            except Exception as e:
                                log.error("Command %s error: %s", cmd, e)
                        elif cmd == "/help" or cmd == "/start":
                            self.send_help()
                        else:
                            self.send(f"Comando no reconocido: {cmd}\nEscribe /help")

            except Exception as e:
                log.warning("Telegram poll error: %s", e)
                time.sleep(5)

            time.sleep(1)
