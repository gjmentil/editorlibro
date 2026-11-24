"""Technical analysis engine using pure pandas/numpy (no external TA library)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import Signal, TradeSignal


class TechnicalAnalyzer:
    def __init__(self, config: dict):
        self.rsi_period = config.get("rsi_period", 14)
        self.rsi_oversold = config.get("rsi_oversold", 30)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.macd_fast = config.get("macd_fast", 12)
        self.macd_slow = config.get("macd_slow", 26)
        self.macd_signal = config.get("macd_signal", 9)
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 2)
        self.ema_short = config.get("ema_short", 9)
        self.ema_long = config.get("ema_long", 21)

    def analyze(self, symbol: str, prices: list[float]) -> TradeSignal:
        min_len = max(self.macd_slow, self.bb_period, self.ema_long) + 5
        if len(prices) < min_len:
            return TradeSignal(symbol=symbol, signal=Signal.HOLD, confidence=0, reasons=["Datos insuficientes"])

        close = pd.Series(prices, dtype=float)
        indicators: dict = {}
        reasons: list[str] = []
        scores: list[float] = []

        # RSI
        rsi = self._calc_rsi(close, self.rsi_period)
        if rsi is not None:
            indicators["rsi"] = round(rsi, 2)
            if rsi < self.rsi_oversold:
                scores.append(1.0)
                reasons.append(f"RSI sobrevendido ({rsi:.1f})")
            elif rsi > self.rsi_overbought:
                scores.append(-1.0)
                reasons.append(f"RSI sobrecomprado ({rsi:.1f})")
            else:
                scores.append(0.0)

        # MACD
        macd_line, signal_line, hist = self._calc_macd(close)
        if hist is not None and len(hist.dropna()) > 1:
            macd_hist = hist.iloc[-1]
            prev_hist = hist.iloc[-2]
            indicators["macd_hist"] = round(macd_hist, 4)

            if macd_hist > 0 and prev_hist <= 0:
                scores.append(1.0)
                reasons.append("MACD cruce alcista")
            elif macd_hist < 0 and prev_hist >= 0:
                scores.append(-1.0)
                reasons.append("MACD cruce bajista")
            elif macd_hist > 0:
                scores.append(0.3)
            elif macd_hist < 0:
                scores.append(-0.3)
            else:
                scores.append(0.0)

        # Bollinger Bands
        bb_upper, bb_mid, bb_lower = self._calc_bollinger(close)
        if bb_upper is not None:
            current_price = prices[-1]
            indicators["bb_upper"] = round(bb_upper, 2)
            indicators["bb_lower"] = round(bb_lower, 2)

            if current_price <= bb_lower:
                scores.append(0.8)
                reasons.append("Precio en banda inferior de Bollinger")
            elif current_price >= bb_upper:
                scores.append(-0.8)
                reasons.append("Precio en banda superior de Bollinger")
            else:
                scores.append(0.0)

        # EMA Cross
        ema_s = close.ewm(span=self.ema_short, adjust=False).mean()
        ema_l = close.ewm(span=self.ema_long, adjust=False).mean()
        if len(ema_s.dropna()) > 1 and len(ema_l.dropna()) > 1:
            ema_short_val = ema_s.iloc[-1]
            ema_long_val = ema_l.iloc[-1]
            prev_ema_s = ema_s.iloc[-2]
            prev_ema_l = ema_l.iloc[-2]
            indicators["ema_short"] = round(ema_short_val, 2)
            indicators["ema_long"] = round(ema_long_val, 2)

            if ema_short_val > ema_long_val and prev_ema_s <= prev_ema_l:
                scores.append(1.0)
                reasons.append("Cruce EMA alcista (golden cross)")
            elif ema_short_val < ema_long_val and prev_ema_s >= prev_ema_l:
                scores.append(-1.0)
                reasons.append("Cruce EMA bajista (death cross)")
            elif ema_short_val > ema_long_val:
                scores.append(0.2)
            elif ema_short_val < ema_long_val:
                scores.append(-0.2)
            else:
                scores.append(0.0)

        # Momentum
        if len(prices) >= 5:
            recent_change = (prices[-1] - prices[-5]) / prices[-5] * 100
            indicators["momentum_5"] = round(recent_change, 2)
            if recent_change > 3:
                scores.append(0.5)
                reasons.append(f"Momentum positivo fuerte ({recent_change:.1f}%)")
            elif recent_change < -3:
                scores.append(-0.5)
                reasons.append(f"Momentum negativo fuerte ({recent_change:.1f}%)")

        if not scores:
            return TradeSignal(symbol=symbol, signal=Signal.HOLD, confidence=0, reasons=["Sin datos suficientes"])

        avg_score = sum(scores) / len(scores)
        confidence = min(abs(avg_score), 1.0)

        if avg_score >= 0.6:
            signal = Signal.STRONG_BUY
        elif avg_score >= 0.25:
            signal = Signal.BUY
        elif avg_score <= -0.6:
            signal = Signal.STRONG_SELL
        elif avg_score <= -0.25:
            signal = Signal.SELL
        else:
            signal = Signal.HOLD

        if not reasons:
            reasons.append("Sin señales claras")

        return TradeSignal(
            symbol=symbol, signal=signal, confidence=round(confidence, 2),
            reasons=reasons, indicators=indicators, price=prices[-1],
        )

    @staticmethod
    def _calc_rsi(close: pd.Series, period: int) -> float | None:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
        last_loss = avg_loss.iloc[-1]
        if last_loss == 0:
            return 100.0
        rs = avg_gain.iloc[-1] / last_loss
        return 100 - (100 / (1 + rs))

    def _calc_macd(self, close: pd.Series) -> tuple:
        ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _calc_bollinger(self, close: pd.Series) -> tuple:
        sma = close.rolling(window=self.bb_period).mean()
        std = close.rolling(window=self.bb_period).std()
        if sma.iloc[-1] is None or np.isnan(sma.iloc[-1]):
            return None, None, None
        upper = sma.iloc[-1] + self.bb_std * std.iloc[-1]
        lower = sma.iloc[-1] - self.bb_std * std.iloc[-1]
        return upper, sma.iloc[-1], lower
