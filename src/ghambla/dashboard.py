"""dashboard.py — a local, read-only live dashboard for the trading system.

WHY this exists:
The trading system runs unattended and produces an append-only JSONL journal of
its decisions plus a simulated account snapshot. A human needs to see what the
system is doing without touching any of its state. This module serves a
self-contained HTML page that renders that state and refreshes it by polling.

WHY it is read-only:
The dashboard is an observer, not a controller. It must never mutate the
journal, the account file, or any trading state. All it does is read those two
files, derive a few summary numbers, and serve them over HTTP to a browser.
"""

import argparse
import json
import http.server
import os
from datetime import datetime, timezone


def build_state(journal_path, account_path) -> dict:
    """Build the dashboard state dict from the journal and account files."""
    records = []
    try:
        with open(journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        records.append(rec)
                except json.JSONDecodeError:
                    continue
    except (FileNotFoundError, OSError):
        records = []

    # The journal is append-only, so file order is WRITE order. A cycle can be
    # re-run for an earlier as_of, leaving a lower date written after a higher
    # one, so the two orderings genuinely differ and each is needed for a
    # different thing.
    #
    # Current state comes from the LAST WRITE, because that is what the broker
    # actually holds. Taking the highest as_of instead reports a balance the
    # account does not have.
    latest = records[-1] if records else None

    # The chart, by contrast, needs chronological order or the line doubles
    # back on itself. The date field is `as_of`; reading a "date" key that does
    # not exist yields "" for every record, blanking the axis and silently
    # turning this sort into a no-op.
    by_date = sorted(records, key=lambda r: r.get("as_of", ""))
    curve = [
        {"date": r.get("as_of", ""), "equity": float(r.get("equity", 0.0))}
        for r in by_date
    ]

    if not records:
        total_return = None
    else:
        first_equity = by_date[0].get("equity", 0.0)
        if first_equity <= 0:
            total_return = None
        elif len(records) == 1:
            total_return = 0.0
        else:
            total_return = (float(latest["equity"]) / float(first_equity)) - 1.0

    positions = []
    if latest and "positions" in latest:
        positions = [
            {"symbol": s, "shares": float(sh)}
            for s, sh in latest["positions"].items()
        ]
        positions.sort(key=lambda p: p["symbol"])

    halted_days = sum(1 for r in records if r.get("risk_vetoes"))

    return {
        "records": len(records),
        "equity": float(latest["equity"]) if latest else None,
        "cash": float(latest.get("cash", 0.0)) if latest else None,
        "curve": curve,
        "total_return": total_return,
        "positions": positions,
        "latest": latest,
        "halted_days": halted_days,
        "generated": datetime.now(timezone.utc).isoformat(),
    }


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler serving the dashboard page and its data endpoint."""

    journal_path = "data/journal.jsonl"
    account_path = "data/sim_account.json"

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.encode("utf-8"))
        elif self.path == "/data":
            state = build_state(self.journal_path, self.account_path)
            body = json.dumps(state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default per-request logging."""
        pass


def serve(port=8787, journal="data/journal.jsonl", account="data/sim_account.json"):
    """Start the dashboard server on 127.0.0.1."""
    DashboardHandler.journal_path = journal
    DashboardHandler.account_path = account
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Dashboard: http://127.0.0.1:{port}")
    server.serve_forever()


PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ghambla — simulated dashboard</title>
<style>
:root {
  --bg: #ffffff;
  --fg: #1a1a1a;
  --muted: #666666;
  --border: #dddddd;
  --tile-bg: #f5f5f5;
  --gain: #007700;
  --loss: #cc0000;
  --warn: #cc6600;
  --warn-bg: #fff3e0;
  --table-stripe: #fafafa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a1a;
    --fg: #e0e0e0;
    --muted: #999999;
    --border: #444444;
    --tile-bg: #2a2a2a;
    --gain: #4caf50;
    --loss: #f44336;
    --warn: #ff9800;
    --warn-bg: #3a2a1a;
    --table-stripe: #222222;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--fg);
  padding: 1rem;
  max-width: 1000px;
  margin: 0 auto;
}
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
.status { color: var(--muted); font-size: 0.9rem; margin-bottom: 1.5rem; }
.status strong { color: var(--warn); }
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.tile {
  background: var(--tile-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.75rem;
}
.tile .label { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.25rem; }
.tile .value { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: 1.1rem; }
.gain { color: var(--gain); }
.loss { color: var(--loss); }
section { margin-bottom: 1.5rem; }
h2 { font-size: 1.1rem; margin-bottom: 0.5rem; }
.chart-container { overflow-x: auto; }
.chart-empty { color: var(--muted); padding: 2rem; text-align: center; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; }
tr:nth-child(even) { background: var(--table-stripe); }
.table-scroll { overflow-x: auto; }
.vetoes {
  background: var(--warn-bg);
  border-left: 3px solid var(--warn);
  padding: 0.5rem 0.75rem;
  margin-top: 0.5rem;
  font-size: 0.9rem;
}
.vetoes .title { color: var(--warn); font-weight: 600; margin-bottom: 0.25rem; }
.generated { color: var(--muted); font-size: 0.8rem; margin-top: 1rem; }
.error { color: var(--loss); padding: 1rem; text-align: center; }
</style>
</head>
<body>
<h1>ghambla</h1>
<p class="status"><strong>SIMULATED broker.</strong> No strategy has passed Gate 0.
These numbers are not evidence of an edge — they are a simulation only.</p>

<div class="tiles">
  <div class="tile"><div class="label">Equity</div><div class="value" id="equity">—</div></div>
  <div class="tile"><div class="label">Cash</div><div class="value" id="cash">—</div></div>
  <div class="tile"><div class="label">Total return</div><div class="value" id="return">—</div></div>
  <div class="tile"><div class="label">Positions held</div><div class="value" id="positions-count">—</div></div>
</div>

<section>
  <h2>Equity curve</h2>
  <div class="chart-container" id="chart"></div>
</section>

<section>
  <h2>Positions</h2>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Symbol</th><th>Shares</th></tr></thead>
      <tbody id="positions-body"></tbody>
    </table>
  </div>
</section>

<section>
  <h2>Latest decision</h2>
  <div id="decision"></div>
</section>

<section>
  <h2>Recent journal</h2>
  <div class="table-scroll">
    <table>
      <thead><tr><th>Date</th><th>Equity</th><th>Orders</th><th>Vetoes</th></tr></thead>
      <tbody id="journal-body"></tbody>
    </table>
  </div>
</section>

<p class="generated" id="generated">Waiting for data…</p>

<script>
const fmtMoney = (v) => v == null ? "—" : "$" + Number(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtNum = (v) => v == null ? "—" : Number(v).toLocaleString();

function fmtSignedPct(v) {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : (v < 0 ? "−" : "");
  const cls = v > 0 ? "gain" : (v < 0 ? "loss" : "");
  return `<span class="${cls}">${sign}${(v * 100).toFixed(2)}%</span>`;
}

function drawChart(curve) {
  const el = document.getElementById("chart");
  if (curve.length < 2) {
    el.innerHTML = '<div class="chart-empty">Not enough history yet</div>';
    return;
  }
  const w = 800, h = 300, pad = 40;
  const equities = curve.map(c => c.equity);
  const minE = Math.min(...equities), maxE = Math.max(...equities);
  const range = (maxE - minE) || 1;
  const x = i => pad + (i / (curve.length - 1)) * (w - 2 * pad);
  const y = e => h - pad - ((e - minE) / range) * (h - 2 * pad);

  let path = `M ${x(0)} ${y(curve[0].equity)}`;
  for (let i = 1; i < curve.length; i++) {
    path += ` L ${x(i)} ${y(curve[i].equity)}`;
  }

  el.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" style="min-width:600px">
      <line x1="${pad}" y1="${y(minE)}" x2="${w-pad}" y2="${y(minE)}" stroke="var(--border)"/>
      <line x1="${pad}" y1="${y(maxE)}" x2="${w-pad}" y2="${y(maxE)}" stroke="var(--border)"/>
      <polyline points="${path.slice(1)}" fill="none" stroke="var(--fg)" stroke-width="2"/>
      <text x="${pad}" y="${h-10}" fill="var(--muted)" font-size="11">${curve[0].date}</text>
      <text x="${w-pad}" y="${h-10}" fill="var(--muted)" font-size="11" text-anchor="end">${curve[curve.length-1].date}</text>
      <text x="${pad-5}" y="${y(minE)+12}" fill="var(--muted)" font-size="11" text-anchor="end">${fmtMoney(minE)}</text>
      <text x="${pad-5}" y="${y(maxE)-5}" fill="var(--muted)" font-size="11" text-anchor="end">${fmtMoney(maxE)}</text>
    </svg>`;
}

function render(state) {
  document.getElementById("equity").textContent = fmtMoney(state.equity);
  document.getElementById("cash").textContent = fmtMoney(state.cash);
  document.getElementById("return").innerHTML = fmtSignedPct(state.total_return);
  document.getElementById("positions-count").textContent = state.positions.length;

  drawChart(state.curve);

  const pb = document.getElementById("positions-body");
  pb.innerHTML = state.positions.length
    ? state.positions.map(p => `<tr><td>${p.symbol}</td><td>${fmtNum(p.shares)}</td></tr>`).join("")
    : '<tr><td colspan="2">No positions</td></tr>';

  const d = state.latest;
  const de = document.getElementById("decision");
  if (!d) {
    de.innerHTML = '<p class="chart-empty">No decisions recorded yet</p>';
  } else {
    const orders = (d.orders || []).length;
    const fills = (d.fills || []).length;
    const targets = (d.targets || []).length;
    const vetoes = d.risk_vetoes || [];
    const notes = d.notes || [];
    const vetoHtml = (vetoes.length || notes.length)
      ? `<div class="vetoes"><div class="title">⚠ VETOES / NOTES</div>${vetoes.map(v => `<div>• ${v}</div>`).join("")}${notes.map(n => `<div>• ${n}</div>`).join("")}</div>`
      : '<div class="vetoes"><div class="title">✓ No vetoes</div></div>';
    de.innerHTML = `
      <div class="table-scroll"><table>
        <tr><th>As of</th><td>${d.date || "—"}</td></tr>
        <tr><th>Universe size</th><td>${fmtNum(d.universe_size ?? "—")}</td></tr>
        <tr><th>Allocator</th><td>${d.allocator || "—"}</td></tr>
        <tr><th>Targets</th><td>${fmtNum(targets)}</td></tr>
        <tr><th>Orders</th><td>${fmtNum(orders)}</td></tr>
        <tr><th>Fills</th><td>${fmtNum(fills)}</td></tr>
      </table></div>
      ${vetoHtml}`;
  }

  const jb = document.getElementById("journal-body");
  const recent = state.curve.slice(-10).reverse();
  jb.innerHTML = recent.length
    ? recent.map(c => {
        const rec = state.curve.find(r => r.date === c.date);
        const vetoCount = state.records ? 0 : 0;
        return `<tr><td>${c.date}</td><td>${fmtMoney(c.equity)}</td><td>—</td><td>—</td></tr>`;
      }).join("")
    : '<tr><td colspan="4">No journal entries</td></tr>';

  document.getElementById("generated").textContent = "Generated: " + (state.generated || "unknown");
}

async function refresh() {
  try {
    const resp = await fetch("/data");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const state = await resp.json();
    render(state);
  } catch (err) {
    document.getElementById("generated").textContent = "Fetch failed: " + err.message;
  }
}

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ghambla dashboard")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--journal", default="data/journal.jsonl")
    parser.add_argument("--account", default="data/sim_account.json")
    args = parser.parse_args()
    serve(args.port, args.journal, args.account)
