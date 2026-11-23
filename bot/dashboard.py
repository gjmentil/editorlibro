"""Simple web dashboard for monitoring the bot."""

from __future__ import annotations

import json
from datetime import datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .database import Database

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crypto Trading Bot</title>
<style>
:root {
  --bg: #0d1117; --card: #161b22; --border: #30363d;
  --text: #e6edf3; --dim: #8b949e; --green: #3fb950;
  --red: #f85149; --blue: #58a6ff; --yellow: #d29922;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 16px; }
h1 { font-size: 1.4rem; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 0.85rem; color: var(--dim); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.card .value { font-size: 1.5rem; font-weight: 600; }
.green { color: var(--green); }
.red { color: var(--red); }
.blue { color: var(--blue); }
.yellow { color: var(--yellow); }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
th { color: var(--dim); font-weight: 500; font-size: 0.8rem; text-transform: uppercase; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
.badge-buy { background: rgba(63,185,80,0.15); color: var(--green); }
.badge-sell { background: rgba(248,81,73,0.15); color: var(--red); }
.badge-filled { background: rgba(88,166,255,0.15); color: var(--blue); }
#refresh { position: fixed; bottom: 16px; right: 16px; background: var(--blue); color: #fff; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>🤖 Crypto Trading Bot - Dashboard</h1>
<div class="grid" id="stats"></div>
<div class="card">
  <h3>Operaciones recientes</h3>
  <table>
    <thead><tr><th>Fecha</th><th>Símbolo</th><th>Tipo</th><th>Cantidad</th><th>Precio</th><th>Estado</th></tr></thead>
    <tbody id="trades"></tbody>
  </table>
</div>
<div class="card" style="margin-top: 12px;">
  <h3>Historial de precios</h3>
  <canvas id="chart" height="200"></canvas>
</div>
<button id="refresh" onclick="load()">Actualizar</button>
<script>
async function load() {
  const r = await fetch('/api/status');
  const d = await r.json();
  document.getElementById('stats').innerHTML = `
    <div class="card"><h3>P&L Hoy</h3><div class="value ${d.daily.pnl>=0?'green':'red'}">${d.daily.pnl>=0?'+':''}${d.daily.pnl.toFixed(2)} EUR</div></div>
    <div class="card"><h3>Trades Hoy</h3><div class="value blue">${d.daily.trades}</div></div>
    <div class="card"><h3>Compras / Ventas</h3><div class="value">${d.daily.buys} / ${d.daily.sells}</div></div>
    <div class="card"><h3>Comisiones</h3><div class="value yellow">${d.daily.fees.toFixed(2)} EUR</div></div>
  `;
  const tbody = document.getElementById('trades');
  tbody.innerHTML = d.trades.map(t => `
    <tr>
      <td>${t.created_at||''}</td>
      <td>${t.symbol}</td>
      <td><span class="badge badge-${t.side.toLowerCase()}">${t.side}</span></td>
      <td>${parseFloat(t.quantity).toFixed(6)}</td>
      <td>${t.filled_price ? parseFloat(t.filled_price).toFixed(2) : '-'}</td>
      <td><span class="badge badge-filled">${t.status}</span></td>
    </tr>
  `).join('');
  drawChart(d.prices);
}
function drawChart(prices) {
  const c = document.getElementById('chart');
  const ctx = c.getContext('2d');
  c.width = c.parentElement.clientWidth - 32;
  ctx.clearRect(0, 0, c.width, c.height);
  if (!prices || !prices.length) return;
  const vals = prices.map(p => p.price);
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const range = mx - mn || 1;
  ctx.strokeStyle = vals[vals.length-1] >= vals[0] ? '#3fb950' : '#f85149';
  ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = (i / (vals.length-1)) * c.width;
    const y = c.height - ((v - mn) / range) * (c.height - 20) - 10;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}
load();
setInterval(load, 30000);
</script>
</body>
</html>"""


def create_dashboard(db: Database) -> Starlette:
    async def homepage(request: Request) -> HTMLResponse:
        return HTMLResponse(DASHBOARD_HTML)

    async def api_status(request: Request) -> JSONResponse:
        daily = db.get_daily_pnl()
        trades = db.get_recent_trades(limit=20)
        prices = []
        for row in db._conn.execute(
            "SELECT price, recorded_at FROM prices ORDER BY recorded_at DESC LIMIT 100"
        ).fetchall():
            prices.append({"price": row["price"], "time": row["recorded_at"]})
        prices.reverse()
        return JSONResponse({"daily": daily, "trades": trades, "prices": prices})

    return Starlette(routes=[
        Route("/", homepage),
        Route("/api/status", api_status),
    ])
