"""Technical analysis engine using pandas_ta."""

from __future__ import annotations

import pandas as pd
import pandas_ta as pta

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
        rsi_series = pta.rsi(close, length=self.rsi_period)
        if rsi_series is not None and len(rsi_series.dropna()) > 0:
            rsi = rsi_series.iloc[-1]
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
        macd_df = pta.macd(close, fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
        if macd_df is not None and len(macd_df.dropna()) > 1:
            hist_col = [c for c in macd_df.columns if "h" in c.lower() or "hist" in c.lower()]
            macd_col = [c for c in macd_df.columns if c.startswith("MACD_") and "h" not in c.lower() and "s" not in c.lower()]
            sig_col = [c for c in macd_df.columns if "s" in c.lower() and "h" not in c.lower()]

            if hist_col:
                macd_hist = macd_df[hist_col[0]].iloc[-1]
                prev_hist = macd_df[hist_col[0]].iloc[-2]
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
        bb_df = pta.bbands(close, length=self.bb_period, std=float(self.bb_std))
        if bb_df is not None and len(bb_df.dropna()) > 0:
            upper_col = [c for c in bb_df.columns if "u" in c.lower() or "upper" in c.lower()]
            lower_col = [c for c in bb_df.columns if "l" in c.lower() and "lower" in c.lower() or c.startswith("BBL")]
            mid_col = [c for c in bb_df.columns if "m" in c.lower() or "mid" in c.lower()]

            if upper_col and lower_col:
                bb_upper = bb_df[upper_col[0]].iloc[-1]
                bb_lower = bb_df[lower_col[0]].iloc[-1]
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
        ema_s = pta.ema(close, length=self.ema_short)
        ema_l = pta.ema(close, length=self.ema_long)
        if ema_s is not None and ema_l is not None and len(ema_s.dropna()) > 1 and len(ema_l.dropna()) > 1:
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
            symbol=symbol,
            signal=signal,
            confidence=round(confidence, 2),
            reasons=reasons,
            indicators=indicators,
        )
