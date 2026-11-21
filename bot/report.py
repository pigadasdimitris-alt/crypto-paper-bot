"""Γράφει το README.md με σύνοψη — φαίνεται αμέσως στην αρχική σελίδα του repo από το κινητό."""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as C
from . import engine


def _local(s):
    dt = engine.parse_time(s)
    return dt.astimezone(ZoneInfo(C.TIMEZONE)).strftime("%d/%m %H:%M") if dt else "-"


def summary(state):
    c = state["closed"]
    wins = [t for t in c if t["pnl"] > 0]
    gw = sum(t["pnl"] for t in wins)
    gl = -sum(t["pnl"] for t in c if t["pnl"] <= 0)
    eq = engine.equity(state)
    return {"equity": eq, "pnl": eq - state["start_balance"], "pnl_pct": 100 * (eq / state["start_balance"] - 1),
            "trades": len(c), "wins": len(wins), "win_rate": 100 * len(wins) / len(c) if c else 0.0,
            "pf": (gw / gl) if gl > 0 else None, "avg": (gw - gl) / len(c) if c else 0.0}


def write_readme(state, path):
    s = summary(state)
    pf = "-" if s["pf"] is None else f"{s['pf']:.2f}"
    L = [
        "# crypto-paper-bot", "",
        "**Μόνο εικονικά χρήματα (paper).** Κανένα πορτοφόλι, κανένα API key, καμία πραγματική εντολή.", "",
        f"Στρατηγική: **{state['strategy']['name']}** σε κεριά 4ω, BTC/ETH/SOL. {state['strategy']['description']} "
        f"Κόστη {C.FEE_PER_SIDE*100:.1f}% fee + {C.SLIPPAGE_PER_SIDE*100:.2f}% slippage ανά πλευρά. "
        "Τιμές από Coinbase + Kraken (πρέπει να συμφωνούν).", "",
        "## Σύνοψη live paper", "", "| | |", "|---|---|",
        f"| Αρχικό κεφάλαιο | ${state['start_balance']:.2f} |",
        f"| **Τώρα** | **${s['equity']:.2f}** ({s['pnl']:+.2f}$, {s['pnl_pct']:+.1f}%) |",
        f"| Κλειστά trades | {s['trades']} (κερδισμένα {s['wins']}, {s['win_rate']:.0f}%) · PF {pf} · μέσο {s['avg']:+.2f}$ |",
        f"| Ανοιχτά τώρα | {len(state['positions'])} |",
        f"| Ξεκίνησε | {_local(state['started_at'])} |",
        f"| Τελευταίος έλεγχος | {_local(state['last_run'])} |", "",
    ]
    if state["positions"]:
        L += ["## Ανοιχτά", "", "| # | Νόμισμα | Αγορά | Τιμή αγοράς | Τώρα | Stop |", "|---|---|---|---|---|---|"]
        for p in state["positions"]:
            L.append(f"| {p['id']} | {p['sym']} | {_local(p['entry_time'])} | ${p['entry_market']:,.2f} | "
                     f"{p['last_pct']:+.1f}% | ${p['stop']:,.2f} |")
        L.append("")
    if state["closed"]:
        L += ["## Τελευταία trades", "", "| # | Νόμισμα | Ώρες | Αποτέλεσμα | Λόγος |", "|---|---|---|---|---|"]
        for t in reversed(state["closed"][-20:]):
            L.append(f"| {t['id']} | {t['sym']} | {t['hold_min']/60:.0f} | {t['pnl']:+.2f}$ ({t['pnl_pct']:+.1f}%) | {t['reason']} |")
        L.append("")
    L += ["## Backtests", "",
          "- Υπόθεση 1 (intraday 5′/15′): [results/BACKTEST.md](results/BACKTEST.md) — απέτυχε",
          "- Υπόθεση 2 (4ω/ημέρα): [results/BACKTEST_TREND.md](results/BACKTEST_TREND.md) — πέρασε μόνο το Donchian 4ω",
          "", f"_Ενημερώθηκε αυτόματα: {datetime.now(ZoneInfo(C.TIMEZONE)).strftime('%d/%m/%Y %H:%M')}_", ""]
    path.write_text("\n".join(L))
