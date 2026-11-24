"""Quick setup: creates config.json with all 61 EUR crypto pairs."""
import json
import re
from pathlib import Path


def _clean(value: str) -> str:
    """Strip JSON formatting if user pasted a full JSON line."""
    value = value.strip().rstrip(",")
    m = re.search(r':\s*"([^"]*)"', value)
    if m:
        return m.group(1)
    return value.strip('"').strip("'")


def main():
    print("=== Configuracion del Bot Revolut X ===\n")

    existing = {}
    if Path("config.json").exists():
        existing = json.loads(Path("config.json").read_text())
        print("config.json existente encontrado. Se actualizara.\n")

    api_key = existing.get("api_key", "")
    if not api_key or "REVOLUT" in api_key.upper() or len(api_key) < 20:
        api_key = _clean(input("API Key de Revolut X: "))

    telegram_token = existing.get("alerts", {}).get("telegram_bot_token", "")
    if not telegram_token or ":" not in telegram_token or len(telegram_token) > 60:
        telegram_token = _clean(input("Telegram Bot Token: "))

    telegram_chat = existing.get("alerts", {}).get("telegram_chat_id", "")
    if not telegram_chat or not telegram_chat.isdigit():
        telegram_chat = _clean(input("Telegram Chat ID: "))

    config = {
        "api_key": api_key,
        "private_key_path": existing.get("private_key_path", "private.pem"),
        "base_url": "https://revx.revolut.com/api",
        "region": "EEA",
        "dry_run": existing.get("dry_run", True),
        "symbols": [
            "BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "BNB/EUR", "ADA/EUR",
            "ALGO/EUR", "APT/EUR", "ARB/EUR", "ATOM/EUR", "AVAX/EUR", "AVNT/EUR",
            "BCH/EUR", "BONK/EUR", "CHZ/EUR", "CRV/EUR", "DASH/EUR", "DOGE/EUR",
            "DOT/EUR", "ENA/EUR", "ETC/EUR", "FET/EUR", "FIDA/EUR", "FIL/EUR",
            "FLOKI/EUR", "HBAR/EUR", "HYPE/EUR", "ICP/EUR", "INJ/EUR", "JASMY/EUR",
            "LDO/EUR", "LINK/EUR", "LTC/EUR", "MAGIC/EUR", "NEAR/EUR", "ONDO/EUR",
            "OP/EUR", "PENDLE/EUR", "PENGU/EUR", "PEPE/EUR", "POL/EUR", "RENDER/EUR",
            "SEI/EUR", "SHIB/EUR", "SPX/EUR", "STRK/EUR", "STX/EUR", "SUI/EUR",
            "TIA/EUR", "TON/EUR", "TRUMP/EUR", "TRX/EUR", "UNI/EUR", "USDC/EUR",
            "VVV/EUR", "WIF/EUR", "WLD/EUR", "XLM/EUR", "ZRO/EUR", "AAVE/EUR",
            "1INCH/EUR"
        ],
        "strategy": "combined",
        "check_interval_seconds": 60,
        "risk": {
            "max_position_pct": 10,
            "stop_loss_pct": 3.0,
            "take_profit_pct": 6.0,
            "max_daily_trades": 20,
            "max_daily_loss_pct": 5.0
        },
        "alerts": {
            "console": True,
            "log_file": "trades.log",
            "telegram_bot_token": telegram_token,
            "telegram_chat_id": telegram_chat
        },
        "indicators": {
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "bb_period": 20,
            "bb_std": 2,
            "ema_short": 9,
            "ema_long": 21
        }
    }

    Path("config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"\nconfig.json creado con:")
    print(f"  - API Key: ...{api_key[-8:]}")
    print(f"  - Telegram token: ...{telegram_token[-10:]}")
    print(f"  - Telegram chat: {telegram_chat}")
    print(f"  - {len(config['symbols'])} cryptos EUR")
    print(f"  - Modo: {'DRY RUN (simulacion)' if config['dry_run'] else 'LIVE'}")
    print(f"\nListo! Arranca con: python -m bot run")


if __name__ == "__main__":
    main()
