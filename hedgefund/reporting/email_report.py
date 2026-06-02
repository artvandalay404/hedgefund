"""Transactional email via Resend (ADR-0006).

The email digest is the product surface for the portfolio manager — it must
be genuinely readable, not a log dump.
"""
from __future__ import annotations

import structlog
import resend

from hedgefund.config import settings

log = structlog.get_logger(__name__)


# ── HTML helpers ──────────────────────────────────────────────────────────────

_CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         font-size: 14px; color: #1a1a1a; background: #f8f8f8; padding: 20px; }
  .card { background: #fff; border-radius: 8px; padding: 24px;
          max-width: 700px; margin: 0 auto; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  h1 { font-size: 20px; margin: 0 0 4px; }
  h2 { font-size: 15px; margin: 24px 0 8px; border-bottom: 1px solid #e5e5e5;
       padding-bottom: 4px; color: #444; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 6px 8px; background: #f3f3f3;
       font-weight: 600; color: #555; }
  td { padding: 6px 8px; border-bottom: 1px solid #f0f0f0; }
  .tag { display: inline-block; padding: 2px 6px; border-radius: 3px;
         font-size: 11px; font-weight: 600; }
  .green  { color: #166534; background: #dcfce7; }
  .red    { color: #991b1b; background: #fee2e2; }
  .yellow { color: #92400e; background: #fef3c7; }
  .meta   { font-size: 12px; color: #888; margin-top: 16px; }
"""


def _wrap(title: str, body: str, date_str: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">
<h1>{title}</h1>
<p class="meta">{date_str} &mdash; paper trading (results do not count as track record)</p>
{body}
</div></body></html>"""


def _status_row(label: str, value: str, tag: str | None = None) -> str:
    tag_html = f' <span class="tag {tag}">{tag}</span>' if tag else ""
    return f"<tr><td><b>{label}</b></td><td>{value}{tag_html}</td></tr>"


def _pct(v: float) -> str:
    return f"{v:+.2%}"


def _dollar(v: float) -> str:
    return f"${v:,.2f}"


def _signal_row(s: dict) -> str:
    return (
        f"<tr>"
        f"<td><b>{s['symbol']}</b></td>"
        f"<td>{s['direction'].upper()}</td>"
        f"<td>{_dollar(s['entry_price'])}</td>"
        f"<td>{_dollar(s['stop_price'])}</td>"
        f"<td>{_dollar(s['target_price'])}</td>"
        f"<td>{s['final_qty']}</td>"
        f"<td>{_dollar(s['risk_amount'])}</td>"
        f"</tr>"
    )


# ── Pre-market email ──────────────────────────────────────────────────────────

def build_pre_market_html(
    date_str: str,
    equity: float,
    peak_equity: float,
    portfolio_heat_pct: float,
    kill_switch: bool,
    kill_switch_reason: str,
    signals: list[dict],        # list of signal dicts
    orders_placed: int,
    open_positions: list[dict],
) -> str:
    drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0

    ks_tag = "red" if kill_switch else "green"
    ks_label = f"HALTED — {kill_switch_reason}" if kill_switch else "Active"

    status_rows = "".join([
        _status_row("Equity", _dollar(equity)),
        _status_row("Peak equity", _dollar(peak_equity)),
        _status_row("Drawdown from peak", _pct(-drawdown)),
        _status_row("Portfolio heat", f"{portfolio_heat_pct:.1%}"),
        _status_row("Kill switch", ks_label, ks_tag),
    ])

    signal_rows = "".join(_signal_row(s) for s in signals) if signals else "<tr><td colspan='7'>No signals today.</td></tr>"

    pos_rows = ""
    if open_positions:
        for p in open_positions:
            pos_rows += (
                f"<tr><td>{p['symbol']}</td><td>{p['qty']}</td>"
                f"<td>{_dollar(p['avg_entry_price'])}</td>"
                f"<td>{_dollar(p.get('current_price', 0))}</td>"
                f"<td>{_dollar(p.get('unrealized_pnl', 0))}</td></tr>"
            )
    else:
        pos_rows = "<tr><td colspan='5'>No open positions.</td></tr>"

    body = f"""
<h2>System Status</h2>
<table>{status_rows}</table>

<h2>New Signals ({len(signals)}) → Orders Placed ({orders_placed})</h2>
<table>
  <thead><tr>
    <th>Symbol</th><th>Dir</th><th>Entry</th><th>Stop</th><th>Target</th><th>Qty</th><th>$ Risk</th>
  </tr></thead>
  <tbody>{signal_rows}</tbody>
</table>

<h2>Open Positions ({len(open_positions)})</h2>
<table>
  <thead><tr>
    <th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Last</th><th>Unreal P&amp;L</th>
  </tr></thead>
  <tbody>{pos_rows}</tbody>
</table>
"""
    return _wrap(f"Pre-Market Plan — {date_str}", body, date_str)


# ── Post-market email ─────────────────────────────────────────────────────────

def build_post_market_html(
    date_str: str,
    equity: float,
    daily_pnl: float,
    peak_equity: float,
    portfolio_heat_pct: float,
    kill_switch: bool,
    kill_switch_reason: str,
    fills_today: list[dict],
    open_positions: list[dict],
    recent_equity: list[dict],  # last 5 rows of equity_curve [{date, equity, daily_pnl}]
) -> str:
    drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
    pnl_tag = "green" if daily_pnl >= 0 else "red"
    ks_tag = "red" if kill_switch else "green"
    ks_label = f"HALTED — {kill_switch_reason}" if kill_switch else "Active"

    status_rows = "".join([
        _status_row("Equity", _dollar(equity)),
        _status_row("Day P&L", _pct(daily_pnl / equity) + f" ({_dollar(daily_pnl)})", pnl_tag),
        _status_row("Peak equity", _dollar(peak_equity)),
        _status_row("Drawdown from peak", _pct(-drawdown)),
        _status_row("Portfolio heat", f"{portfolio_heat_pct:.1%}"),
        _status_row("Kill switch", ks_label, ks_tag),
    ])

    fill_rows = ""
    if fills_today:
        for f in fills_today:
            fill_rows += (
                f"<tr><td>{f['symbol']}</td><td>{f['side'].upper()}</td>"
                f"<td>{f['qty']}</td><td>{_dollar(f.get('filled_avg_price') or 0)}</td>"
                f"<td>{f['status']}</td></tr>"
            )
    else:
        fill_rows = "<tr><td colspan='5'>No fills today.</td></tr>"

    pos_rows = ""
    if open_positions:
        for p in open_positions:
            pos_rows += (
                f"<tr><td>{p['symbol']}</td><td>{p['qty']}</td>"
                f"<td>{_dollar(p['avg_entry_price'])}</td>"
                f"<td>{_dollar(p.get('current_price', 0))}</td>"
                f"<td>{_dollar(p.get('unrealized_pnl', 0))}</td></tr>"
            )
    else:
        pos_rows = "<tr><td colspan='5'>No open positions.</td></tr>"

    equity_rows = ""
    for row in reversed(recent_equity):
        pnl_cls = "green" if row["daily_pnl"] >= 0 else "red"
        equity_rows += (
            f"<tr><td>{row['date']}</td><td>{_dollar(row['equity'])}</td>"
            f"<td><span class='tag {pnl_cls}'>{_dollar(row['daily_pnl'])}</span></td></tr>"
        )

    body = f"""
<h2>Session Summary</h2>
<table>{status_rows}</table>

<h2>Today's Fills ({len(fills_today)})</h2>
<table>
  <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Fill Price</th><th>Status</th></tr></thead>
  <tbody>{fill_rows}</tbody>
</table>

<h2>Open Positions ({len(open_positions)})</h2>
<table>
  <thead><tr>
    <th>Symbol</th><th>Qty</th><th>Avg Entry</th><th>Last</th><th>Unreal P&amp;L</th>
  </tr></thead>
  <tbody>{pos_rows}</tbody>
</table>

<h2>Recent Equity Curve</h2>
<table>
  <thead><tr><th>Date</th><th>Equity</th><th>Day P&L</th></tr></thead>
  <tbody>{equity_rows}</tbody>
</table>
"""
    return _wrap(f"Post-Market Recap — {date_str}", body, date_str)


# ── Send ──────────────────────────────────────────────────────────────────────

def send_email(subject: str, html: str) -> bool:
    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send({
            "from": settings.email_from,
            "to": [settings.email_to],
            "subject": subject,
            "html": html,
        })
        log.info("email.sent", subject=subject, to=settings.email_to)
        return True
    except Exception as exc:
        log.error("email.failed", subject=subject, error=str(exc))
        return False
