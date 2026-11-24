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

    def send_signal(self, symbol: str, signal: str, confidence: float, reasons: list[str], indicators: dict, price: float = 0):
        if not self.alerts_enabled:
            return
        if signal == "HOLD":
            return

        name = symbol.split("/")[0]
        rsi = indicators.get("rsi", 0)
        macd = indicators.get("macd_hist", 0)
        bb_upper = indicators.get("bb_upper", 0)
        bb_lower = indicators.get("bb_lower", 0)
        ema_s = indicators.get("ema_short", 0)
        ema_l = indicators.get("ema_long", 0)
        momentum = indicators.get("momentum_5", 0)

        price_usd = self._usd(price) if price else "?"

        if signal == "STRONG_BUY":
            header = f"🟢🟢 <b>COMPRAR {name}</b> — Senal fuerte"
            advice = f"Multiples indicadores tecnicos coinciden: buen momento para entrar en <b>{name}</b>."
        elif signal == "BUY":
            header = f"🟢 <b>COMPRAR {name}</b> — Senal moderada"
            advice = f"Los indicadores sugieren que <b>{name}</b> podria subir. Oportunidad moderada."
        elif signal == "SELL":
            header = f"🔴 <b>VENDER {name}</b> — Senal de salida"
            advice = f"Los indicadores muestran debilidad en <b>{name}</b>. Considera vender."
        else:
            header = f"🔴🔴 <b>VENDER {name}</b> — Senal fuerte de salida"
            advice = f"Multiples indicadores en contra de <b>{name}</b>. Recomendable salir."

        stars = "⭐" * max(1, min(5, int(confidence * 5)))

        # Technical analysis section
        tech = []
        if rsi:
            if rsi < 30:
                tech.append(f"📉 RSI: <b>{rsi:.0f}</b> — Sobreventa (precio muy bajo, probable rebote)")
            elif rsi > 70:
                tech.append(f"📈 RSI: <b>{rsi:.0f}</b> — Sobrecompra (precio muy alto, probable caida)")
            else:
                tech.append(f"📊 RSI: <b>{rsi:.0f}</b> — Zona neutral")

        if macd:
            if macd > 0:
                tech.append(f"📊 MACD: <b>Alcista</b> — Tendencia subiendo")
            else:
                tech.append(f"📊 MACD: <b>Bajista</b> — Tendencia bajando")

        if ema_s and ema_l:
            if ema_s > ema_l:
                tech.append(f"📈 EMA: Rapida sobre lenta — Tendencia alcista")
            else:
                tech.append(f"📉 EMA: Rapida bajo lenta — Tendencia bajista")

        if momentum:
            tech.append(f"🔄 Momentum: <b>{momentum:+.2f}%</b> (ultimas 5 lecturas)")

        tech_text = "\n".join(tech)

        # Price targets
        targets = ""
        if price > 0 and signal in ("STRONG_BUY", "BUY"):
            sl = price * 0.97
            tp = price * 1.06
            targets = (
                f"\n\n💰 <b>Objetivos:</b>\n"
                f"  📍 Entrada: {price_usd}\n"
                f"  🎯 Ganancia (+6%): {self._usd(tp)}\n"
                f"  🛑 Stop-loss (-3%): {self._usd(sl)}\n"
                f"  📊 Ratio riesgo/beneficio: 1:2"
            )

        text = (
            f"{header}\n"
            f"Confianza: {stars} ({confidence:.0%})\n"
            f"Precio actual: {price_usd}\n\n"
            f"{advice}\n\n"
            f"<b>Analisis tecnico:</b>\n{tech_text}"
            f"{targets}"
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
