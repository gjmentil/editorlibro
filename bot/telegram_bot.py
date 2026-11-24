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
        self.eur_usd_rate: float = 0.0
        self.alerts_enabled: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _usd(self, eur_amount: float) -> str:
        if self.eur_usd_rate > 0:
            val = eur_amount * self.eur_usd_rate
        else:
            val = eur_amount
        if abs(val) < 0.01:
            return f"${val:.6f}"
        if abs(val) < 1:
            return f"${val:.4f}"
        return f"${val:,.2f}"

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
        if not self.alerts_enabled:
            return
        if signal == "HOLD":
            return

        name = symbol.split("/")[0]
        rsi = indicators.get("rsi", 0)
        macd = indicators.get("macd_hist", 0)

        if signal == "STRONG_BUY":
            header = f"🟢🟢 <b>COMPRAR {name}</b> — Oportunidad fuerte"
            advice = (
                f"Varios indicadores coinciden en que <b>{name}</b> esta en un buen punto de entrada.\n"
                f"El precio esta bajo respecto a su rango reciente y muestra impulso alcista."
            )
        elif signal == "BUY":
            header = f"🟢 <b>COMPRAR {name}</b> — Oportunidad moderada"
            advice = (
                f"Los indicadores sugieren que <b>{name}</b> podria subir.\n"
                f"No es una senal tan fuerte, pero las condiciones son favorables."
            )
        elif signal == "SELL":
            header = f"🔴 <b>VENDER {name}</b> — Momento de salir"
            advice = (
                f"Los indicadores sugieren que <b>{name}</b> podria bajar.\n"
                f"Si tienes esta crypto, considera vender para proteger tus ganancias."
            )
        else:
            header = f"🔴🔴 <b>VENDER {name}</b> — Salir ya"
            advice = (
                f"Multiples indicadores muestran que <b>{name}</b> esta sobrecomprada y podria caer.\n"
                f"Es recomendable vender lo antes posible."
            )

        risk_note = ""
        if signal in ("STRONG_BUY", "BUY"):
            risk_note = "\n⚠️ Stop-loss automatico al -3%. Take-profit al +6%."

        rsi_text = ""
        if rsi:
            if rsi < 30:
                rsi_text = f"\n📉 RSI: {rsi:.0f} (sobreventa = oportunidad de compra)"
            elif rsi > 70:
                rsi_text = f"\n📈 RSI: {rsi:.0f} (sobrecompra = riesgo de caida)"
            else:
                rsi_text = f"\n📊 RSI: {rsi:.0f} (zona neutral)"

        stars = "⭐" * max(1, min(5, int(confidence * 5)))
        text = (
            f"{header}\n"
            f"Confianza: {stars} ({confidence:.0%})\n\n"
            f"{advice}{rsi_text}{risk_note}"
        )
        self.send(text)

    def send_trade(self, symbol: str, side: str, quantity: float, price: float | None, dry_run: bool = False):
        name = symbol.split("/")[0]
        price_str = self._usd(price) if price else "precio de mercado"
        mode = " (simulacion)" if dry_run else ""

        if side == "BUY":
            text = (
                f"🛒 <b>COMPRA{mode}</b>\n\n"
                f"He comprado <b>{quantity:.6f} {name}</b>\n"
                f"Precio: {price_str}\n\n"
                f"📌 Vigilare esta posicion:\n"
                f"  • Si baja -3% → vendo automaticamente (stop-loss)\n"
                f"  • Si sube +6% → vendo automaticamente (take-profit)"
            )
        else:
            text = (
                f"💰 <b>VENTA{mode}</b>\n\n"
                f"He vendido <b>{quantity:.6f} {name}</b>\n"
                f"Precio: {price_str}\n\n"
                f"Posicion cerrada."
            )
        self.send(text)

    def send_error(self, message: str):
        self.send(f"⚠️ <b>Error:</b> {message}")

    def send_prices(self, tickers: list):
        lines = []
        for t in tickers:
            prev = t.last_price - t.change_24h_pct
            pct = (t.change_24h_pct / prev * 100) if prev != 0 else 0
            emoji = "🟢" if pct > 0 else "🔴"
            name = t.symbol.split("/")[0]
            lines.append(f"{emoji} <b>{name}</b>: {self._usd(t.last_price)} ({pct:+.2f}%)")

        header = f"📊 <b>Precios — {datetime.now().strftime('%H:%M')}</b>\n"
        batch_size = 30
        for i in range(0, len(lines), batch_size):
            batch = lines[i:i + batch_size]
            prefix = header if i == 0 else ""
            self.send(prefix + "\n".join(batch))

    def send_status(self, daily_stats: dict, positions: dict, total_value: float):
        pnl = daily_stats.get("pnl", 0)
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"

        pos_lines = []
        for symbol, qty in positions.items():
            if qty > 0:
                pos_lines.append(f"  • {symbol}: {qty:.6f}")

        text = (
            f"🤖 <b>Estado del Bot</b>\n\n"
            f"{pnl_emoji} P&L hoy: <b>{self._usd(pnl)}</b>\n"
            f"📈 Trades hoy: {daily_stats.get('trades', 0)}\n"
            f"💰 Portfolio: {self._usd(total_value)}\n"
            f"📊 Comisiones: {self._usd(daily_stats.get('fees', 0))}\n"
        )
        if pos_lines:
            text += f"\n<b>Posiciones:</b>\n" + "\n".join(pos_lines)
        else:
            text += "\nSin posiciones abiertas"

        self.send(text)

    def send_help(self):
        alerts_state = "activadas" if self.alerts_enabled else "desactivadas"
        self.send(
            "🤖 <b>Tu asesor crypto</b>\n\n"
            "Te aviso cuando detecto oportunidades de compra o venta.\n\n"
            "<b>Comandos:</b>\n"
            "/precios — Ver todas las cryptos y sus precios\n"
            "/estado — Como va el bot hoy (ganancias/perdidas)\n"
            "/portfolio — Que cryptos tienes ahora\n"
            f"/alertas — Activar/desactivar avisos ({alerts_state})\n"
            "/help — Ver estos comandos\n\n"
            "<b>Como funciona:</b>\n"
            "Analizo 61 cryptos cada minuto. Cuando detecto una buena "
            "oportunidad de compra o venta, te aviso. El bot tiene "
            "proteccion automatica: si una crypto baja -3% la vende "
            "(stop-loss) y si sube +6% tambien (take-profit)."
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
