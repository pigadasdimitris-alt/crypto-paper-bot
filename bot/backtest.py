"""Backtest: προσομοίωση στρατηγικών σε ιστορικά κεριά με ρεαλιστικά κόστη.

Κανόνες εκτέλεσης (συντηρητικοί):
- Σήμα στο κλείσιμο της μπάρας i -> αγορά στο ΑΝΟΙΓΜΑ της i+1.
- Κάθε πλευρά πληρώνει 0,1% fee + 0,05% slippage.
- Αν μέσα στην ίδια μπάρα αγγίζονται και stop και στόχος, θεωρούμε ότι χτύπησε ΠΡΩΤΑ το stop.
- Αν η μπάρα ανοίγει ήδη πέρα από το stop (gap), βγαίνουμε στο άνοιγμα (χειρότερη τιμή).
- Μία θέση τη φορά ανά νόμισμα, 100% του κεφαλαίου του νομίσματος σε κάθε trade.
- Χαρτοφυλάκιο: 1/3 του κεφαλαίου σε κάθε νόμισμα (BTC, ETH, SOL).
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config as C
from . import strategies as S

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
COST = C.FEE_PER_SIDE + C.SLIPPAGE_PER_SIDE


def load_bars(path):
    t, o, h, l, c = [], [], [], [], []
    with open(path) as f:
        for row in csv.reader(f):
            if not row or not row[0].isdigit():
                continue
            t.append(int(row[0]))
            o.append(float(row[1])); h.append(float(row[2])); l.append(float(row[3])); c.append(float(row[4]))
    return {"t": t, "o": o, "h": h, "l": l, "c": c}


def trade_return(entry_px, exit_px):
    """Καθαρή απόδοση trade μετά από κόστη και στις δύο πλευρές."""
    return (exit_px * (1 - COST)) / (entry_px * (1 + COST)) - 1


def simulate(strategy, bars, start, end, ind=None):
    """Προσομοιώνει στο διάστημα μπαρών [start, end). Επιστρέφει (trades, equity_curve).
    equity_curve: λίστα (timestamp_ms, equity) με αρχή 1.0, αποτίμηση στο κλείσιμο κάθε μπάρας."""
    ind = ind or strategy.prepare(bars)
    o, h, l, c, t = bars["o"], bars["h"], bars["l"], bars["c"], bars["t"]
    start = max(start, C.WARMUP_BARS)
    eq = 1.0
    curve = []
    trades = []
    pos = None
    i = start
    while i < end:
        if pos is not None:
            exit_px, reason = None, None
            if o[i] <= pos["stop"]:
                exit_px, reason = o[i], "stop"
            elif l[i] <= pos["stop"]:
                exit_px, reason = pos["stop"], "stop"
            elif o[i] >= pos["target"]:
                exit_px, reason = o[i], "στόχος"
            elif h[i] >= pos["target"]:
                exit_px, reason = pos["target"], "στόχος"
            if exit_px is None:
                held = i - pos["i"] + 1
                last = i == end - 1
                if strategy.exit_signal(ind, i) or held >= strategy.max_hold_bars or last:
                    # έξοδος στο κλείσιμο (ισοδύναμο με άνοιγμα της επόμενης, χωρίς ματιά στο μέλλον)
                    exit_px = c[i]
                    reason = "τέλος δεδομένων" if last else ("σήμα" if strategy.exit_signal(ind, i) else "χρόνος")
            if exit_px is not None:
                r = trade_return(pos["entry"], exit_px)
                eq = pos["eq0"] * (1 + r)
                trades.append({"entry_t": t[pos["i"]], "exit_t": t[i], "entry": pos["entry"], "exit": exit_px,
                               "ret": r, "bars": i - pos["i"] + 1, "reason": reason})
                pos = None
                curve.append((t[i], eq))
                i += 1
                continue
            curve.append((t[i], pos["eq0"] * (1 + trade_return(pos["entry"], c[i]))))
            i += 1
            continue
        curve.append((t[i], eq))
        if i + 1 < end and strategy.entry(ind, i):
            a = ind["atr"][i]
            if a and a > 0:
                entry = o[i + 1] * 1.0
                pos = {"i": i + 1, "entry": entry, "eq0": eq,
                       "stop": entry - strategy.stop_atr * a, "target": entry + strategy.target_atr * a}
        i += 1
    return trades, curve


def buy_hold(bars, start, end):
    start = max(start, C.WARMUP_BARS)
    entry = bars["o"][start]
    curve = [(bars["t"][i], 1 + trade_return(entry, bars["c"][i])) for i in range(start, end)]
    r = trade_return(entry, bars["c"][end - 1])
    trades = [{"entry_t": bars["t"][start], "exit_t": bars["t"][end - 1], "ret": r, "bars": end - start}]
    return trades, curve


def max_drawdown(values):
    peak, mdd = float("-inf"), 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def metrics(trades, curve):
    rets = [x["ret"] for x in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gl = -sum(losses)
    pf = (sum(wins) / gl) if gl > 0 else (999.0 if wins else 0.0)
    return {
        "trades": len(rets),
        "win_rate": 100 * len(wins) / len(rets) if rets else 0.0,
        "profit_factor": pf,
        "avg_trade_pct": 100 * sum(rets) / len(rets) if rets else 0.0,
        "max_dd_pct": 100 * max_drawdown([v for _, v in curve]) if curve else 0.0,
        "total_return_pct": 100 * (curve[-1][1] - 1) if curve else 0.0,
    }


def combine(curves):
    """Χαρτοφυλάκιο ίσων βαρών: κάθε νόμισμα ξεκινά με 1/N. Ευθυγράμμιση ανά timestamp (forward fill)."""
    times = sorted({t for cv in curves for t, _ in cv})
    maps = [dict(cv) for cv in curves]
    last = [1.0] * len(curves)
    out = []
    for t in times:
        for k, m in enumerate(maps):
            if t in m:
                last[k] = m[t]
        out.append((t, sum(last) / len(curves)))
    return out


def split_index(bars):
    """Δείκτης της πρώτης μπάρας των τελευταίων OOS_DAYS ημερών."""
    cutoff = bars["t"][-1] - C.OOS_DAYS * 86400 * 1000
    for i, tt in enumerate(bars["t"]):
        if tt >= cutoff:
            return i
    return len(bars["t"])


def is_positive(m):
    return (m["trades"] >= C.MIN_OOS_TRADES and m["profit_factor"] >= C.MIN_OOS_PROFIT_FACTOR
            and m["total_return_pct"] > 0)


def fmt_date(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%d/%m/%Y")


def run_timeframe(tf):
    series = {}
    for sym in C.SYMBOLS:
        p = DATA / f"{sym}_{tf}.csv"
        if not p.exists():
            print(f"λείπει {p}", file=sys.stderr)
            return None
        series[sym] = load_bars(p)
    out = {"timeframe": tf, "symbols": {}, "strategies": {}}
    splits = {}
    for sym, b in series.items():
        k = split_index(b)
        splits[sym] = k
        out["symbols"][sym] = {"bars": len(b["t"]), "from": fmt_date(b["t"][0]), "split": fmt_date(b["t"][k]),
                               "to": fmt_date(b["t"][-1])}
    for strat in [*S.ALL, None]:
        key = strat.key if strat else "buyhold"
        res = {"name": strat.name if strat else "Buy & hold", "description": strat.description if strat else
               "Αγορά στην αρχή της περιόδου και κράτημα ως το τέλος (1/3 σε κάθε νόμισμα).",
               "per_symbol": {}, "train": None, "oos": None}
        seg_curves = {"train": [], "oos": []}
        seg_trades = {"train": [], "oos": []}
        for sym, b in series.items():
            n, k = len(b["t"]), splits[sym]
            ind = strat.prepare(b) if strat else None
            res["per_symbol"][sym] = {}
            for seg, (a, z) in {"train": (0, k), "oos": (k, n)}.items():
                tr, cv = simulate(strat, b, a, z, ind) if strat else buy_hold(b, a, z)
                res["per_symbol"][sym][seg] = metrics(tr, cv)
                seg_curves[seg].append(cv)
                seg_trades[seg] += tr
        for seg in ("train", "oos"):
            cv = combine(seg_curves[seg])
            res[seg] = metrics(seg_trades[seg], cv)
            # αραιό δείγμα της καμπύλης για γράφημα (≈ 400 σημεία)
            step = max(1, len(cv) // 400)
            res[seg + "_curve"] = [[t, round(v, 5)] for t, v in cv[::step]]
        res["positive_oos"] = bool(strat) and is_positive(res["oos"])
        out["strategies"][key] = res
    return out


def pf_str(x):
    return "∞" if x >= 999 else f"{x:.2f}"


def row(name, m):
    return (f"| {name} | {m['trades']} | {m['win_rate']:.0f}% | {pf_str(m['profit_factor'])} | "
            f"{m['avg_trade_pct']:+.3f}% | {m['max_dd_pct']:.1f}% | {m['total_return_pct']:+.1f}% |")


HEAD = ["| Στρατηγική | Trades | Επιτυχία | Profit factor | Μέσο/trade | Max DD | Απόδοση |",
        "|---|---|---|---|---|---|---|"]


def report(all_res):
    L = ["# Αποτελέσματα backtest", "",
         f"Κόστη: {C.FEE_PER_SIDE*100:.2f}% fee + {C.SLIPPAGE_PER_SIDE*100:.2f}% slippage **ανά πλευρά** "
         f"(~{2*COST*100:.1f}% ανά πλήρες trade). Χαρτοφυλάκιο 1/3 σε BTC, ETH, SOL. "
         f"Out-of-sample = τελευταίες {C.OOS_DAYS} μέρες, που δεν χρησιμοποιήθηκαν πουθενά.", "",
         f"Κριτήριο «θετικής» στρατηγικής (ορίστηκε από πριν): OOS απόδοση > 0, profit factor ≥ "
         f"{C.MIN_OOS_PROFIT_FACTOR}, τουλάχιστον {C.MIN_OOS_TRADES} trades.", ""]
    winners = []
    for res in all_res:
        tf = res["timeframe"]
        s0 = next(iter(res["symbols"].values()))
        L += [f"## Κεριά {tf}", "",
              f"Εκπαίδευση: {s0['from']} – {s0['split']} · **Out-of-sample: {s0['split']} – {s0['to']}**", "",
              "### Out-of-sample (αυτό μετράει)", "", *HEAD]
        for key, r in res["strategies"].items():
            L.append(row(r["name"], r["oos"]))
            if r["positive_oos"]:
                winners.append((tf, key, r))
        L += ["", "### Εκπαίδευση (για σύγκριση)", "", *HEAD]
        for r in res["strategies"].values():
            L.append(row(r["name"], r["train"]))
        L += ["", "### OOS ανά νόμισμα (απόδοση)", "", "| Στρατηγική | BTC | ETH | SOL |", "|---|---|---|---|"]
        for r in res["strategies"].values():
            ps = r["per_symbol"]
            L.append(f"| {r['name']} | " + " | ".join(f"{ps[s]['oos']['total_return_pct']:+.1f}%" for s in C.SYMBOLS) + " |")
        L.append("")
    L += ["## Ετυμηγορία (αυτόματη, με το προκαθορισμένο κριτήριο)", ""]
    if winners:
        for tf, key, r in winners:
            L.append(f"- Περνάει: **{r['name']} ({tf})** — OOS {r['oos']['total_return_pct']:+.1f}%, "
                     f"PF {pf_str(r['oos']['profit_factor'])}, {r['oos']['trades']} trades.")
    else:
        L.append("- **Καμία στρατηγική δεν πέρασε το κριτήριο out-of-sample. Δεν αξίζει live bot με αυτούς τους κανόνες.**")
    L += ["", "## Οι στρατηγικές", ""]
    for key, r in all_res[0]["strategies"].items():
        L.append(f"- **{r['name']}**: {r['description']}")
    L.append("")
    return "\n".join(L), winners


def main():
    RESULTS.mkdir(exist_ok=True)
    all_res = [r for r in (run_timeframe(tf) for tf in C.TIMEFRAMES) if r]
    if not all_res:
        sys.exit("Δεν βρέθηκαν δεδομένα")
    md, winners = report(all_res)
    (RESULTS / "BACKTEST.md").write_text(md)
    payload = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "costs": {"fee": C.FEE_PER_SIDE, "slippage": C.SLIPPAGE_PER_SIDE},
               "winners": [{"timeframe": tf, "strategy": k} for tf, k, _ in winners], "results": all_res}
    (RESULTS / "backtest.json").write_text(json.dumps(payload, ensure_ascii=False))
    print(md)


if __name__ == "__main__":
    main()
