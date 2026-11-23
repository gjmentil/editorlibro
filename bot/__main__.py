"""Entry point for the crypto trading bot."""

from __future__ import annotations

import argparse
import logging
import sys
import threading

import uvicorn
from rich.console import Console

from .auth import generate_keypair
from .dashboard import create_dashboard
from .database import Database
from .trader import Trader

console = Console()


def main():
    parser = argparse.ArgumentParser(description="🤖 Revolut X Crypto Trading Bot")
    sub = parser.add_subparsers(dest="command", help="Comando")

    sub.add_parser("run", help="Iniciar el bot de trading")
    sub.add_parser("keygen", help="Generar par de claves Ed25519")
    sub.add_parser("dashboard", help="Iniciar solo el dashboard web")

    status_p = sub.add_parser("status", help="Ver estado actual")
    status_p.add_argument("--config", default="config.json")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "keygen":
        cmd_keygen()
    elif args.command == "run":
        cmd_run()
    elif args.command == "dashboard":
        cmd_dashboard()
    elif args.command == "status":
        cmd_status(args.config)
    else:
        parser.print_help()


def cmd_keygen():
    console.print("\n[bold cyan]Generando par de claves Ed25519...[/]\n")
    public_key = generate_keypair()
    console.print("[green]Claves generadas correctamente.[/]\n")
    console.print("Archivos creados:")
    console.print("  - [cyan]private.pem[/] (clave privada - NO compartir)")
    console.print("  - [cyan]public.pem[/]  (clave pública)\n")
    console.print("[yellow]Pasos siguientes:[/]")
    console.print("1. Ve a Revolut X → Configuración → API")
    console.print("2. Crea una nueva clave API")
    console.print("3. Pega la clave pública:\n")
    console.print(f"[dim]{public_key}[/]")
    console.print("\n4. Activa 'Vista de órdenes al contado' y 'Operaciones al contado'")
    console.print("5. Copia el API Key y pégalo en config.json\n")


def cmd_run():
    console.print("\n[bold cyan]🤖 Revolut X Crypto Trading Bot[/]\n")

    trader = Trader()
    db = trader.db

    app = create_dashboard(db)
    server_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning"),
        daemon=True,
    )
    server_thread.start()
    console.print("[dim]Dashboard disponible en http://localhost:8080[/]\n")

    try:
        trader.start()
    except KeyboardInterrupt:
        trader.stop()
        console.print("\n[yellow]Bot detenido.[/]")


def cmd_dashboard():
    console.print("\n[bold cyan]📊 Dashboard[/]\n")
    db = Database()
    app = create_dashboard(db)
    console.print("Dashboard en http://localhost:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


def cmd_status(config_path: str):
    db = Database()
    daily = db.get_daily_pnl()
    trades = db.get_recent_trades(limit=10)

    console.print(f"\n[bold cyan]Estado del día {daily['date']}[/]")
    console.print(f"  Trades: [blue]{daily['trades']}[/]")
    pnl_color = "green" if daily["pnl"] >= 0 else "red"
    console.print(f"  P&L: [{pnl_color}]{daily['pnl']:+.2f} EUR[/]")
    console.print(f"  Comisiones: [yellow]{daily['fees']:.2f} EUR[/]")

    if trades:
        console.print(f"\n[bold]Últimas operaciones:[/]")
        for t in trades[:5]:
            side_color = "green" if t["side"] == "BUY" else "red"
            console.print(
                f"  [{side_color}]{t['side']}[/] {t['symbol']} "
                f"qty={t['quantity']:.6f} "
                f"{'@ ' + str(round(t['filled_price'], 2)) if t.get('filled_price') else ''} "
                f"[dim]{t['created_at']}[/]"
            )

    db.close()


if __name__ == "__main__":
    main()
