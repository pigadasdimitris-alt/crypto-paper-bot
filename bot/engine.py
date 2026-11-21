"""Λογική του live paper bot (χωρίς δίκτυο — εύκολα testable).

Στρατηγική: Donchian 20/10 σε κεριά 4ω, ΑΚΡΙΒΩΣ όπως στο backtest:
- Στο κλείσιμο κεριού: αν κλείσιμο > υψηλό 20 προηγούμενων -> αγορά στην τρέχουσα τιμή.
- Stop = τιμή εισόδου − 2×ATR(14) (σταθερό), ελέγχεται σε κάθε γύρο (κάθε λεπτό).
- Στο κλείσιμο κεριού: αν κλείσιμο < χαμηλό 10 προηγούμενων -> έξοδος.
- Κόστη: 0,1% fee + 0,05% slippage ανά πλευρά.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import config as C
from . import strategies as S

COST = C.FEE_PER_SIDE + C.SLIPPAGE_PER_SIDE
STRAT = S.BY_KEY[C.LIVE_STRATEGY]


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


def local_date(now):
    return now.astimezone(ZoneInfo(C.TIMEZONE)).strftime("%Y-%m-%d")


def new_state(now):
    return {
        "version": 1,
        "strategy": {"key": STRAT.key, "name": STRAT.name, "timeframe": "4h", "description": STRAT.description},
        "started_at": iso(now),
        "start_balance": C.START_BALANCE_USD,
        "balance": C.START_BALANCE_USD,
        "positions": [],
        "closed": [],
        "prices": {},
        "pending": {},
        "bars": {},
        "signals": {},
        "daily": {"date": local_date(now), "realized": 0.0, "entries": 0},
        "stats": {"cycles": 0, "price_rejects": 0, "price_confirms": 0, "bars_checked": 0, "candle_rejects": 0},
        "equity_history": [],
        "log": [],
        "last_run": None,
        "next_id": 1,
    }


def log(state, now, msg):
    state["log"].append({"t": iso(now), "msg": msg})
    state["log"] = state["log"][-300:]


def roll_day(state, now):
    d = local_date(now)
    if state["daily"]["date"] != d:
        state["daily"] = {"date": d, "realized": 0.0, "entries": 0}


def agrees(a, b, tol):
    return a is not None and b is not None and a > 0 and b > 0 and abs(a / b - 1) <= tol


# ---------------- Έλεγχος τιμών από δύο πηγές ----------------

def validate_price(state, sym, cb, kr, now):
    """Επιστρέφει αποδεκτή τιμή ή None.
    - Δύο πηγές που συμφωνούν (≤1%) -> δεκτή (η ίδια η συμφωνία είναι επιβεβαίωση).
    - Δύο πηγές που διαφωνούν -> απορρίπτεται.
    - Μία πηγή: δεκτή αν δεν απέχει >8% από την τελευταία αποδεκτή· αλλιώς θέλει επιβεβαίωση στον επόμενο γύρο."""
    prev = (state["prices"].get(sym) or {}).get("price")
    pend = state["pending"]
    if cb and kr:
        if agrees(cb, kr, C.PRICE_TOLERANCE):
            price, src = cb, "coinbase+kraken"
        else:
            state["stats"]["price_rejects"] += 1
            log(state, now, f"{sym}: οι πηγές διαφωνούν (Coinbase {cb:.6g} / Kraken {kr:.6g}) — η τιμή αγνοείται")
            return None
    elif cb or kr:
        price, src = (cb, "coinbase") if cb else (kr, "kraken")
        if prev and abs(price / prev - 1) > C.MAX_JUMP:
            p = pend.get(sym)
            if p and agrees(price, p["price"], C.PRICE_TOLERANCE):
                state["stats"]["price_confirms"] += 1
            else:
                pend[sym] = {"price": price, "t": iso(now)}
                log(state, now, f"{sym}: απότομη αλλαγή {100*(price/prev-1):+.1f}% από μία μόνο πηγή — περιμένει επιβεβαίωση")
                return None
    else:
        return None
    pend.pop(sym, None)
    state["prices"][sym] = {"price": price, "t": iso(now), "src": src}
    return price


def validate_candles(kr_bars, cb_bars):
    """Το τελευταίο κλειστό κερί πρέπει να συμφωνεί και στις δύο πηγές. Επιστρέφει (ok, λόγος)."""
    if not kr_bars:
        return False, "χωρίς κεριά Kraken"
    last = kr_bars[-1]
    ref = {b["t"]: b for b in cb_bars or []}.get(last["t"])
    if ref is None:
        return False, "δεν υπάρχει το ίδιο κερί στο Coinbase"
    if not agrees(last["c"], ref["c"], C.CANDLE_TOLERANCE):
        return False, f"κλείσιμο διαφωνεί ({last['c']:.6g} / {ref['c']:.6g})"
    return True, ""


# ---------------- Θέσεις ----------------

def equity(state):
    return state["balance"] + sum(p["qty"] * p["last_price"] * (1 - COST) for p in state["positions"])


def can_open(state, sym):
    if any(p["sym"] == sym for p in state["positions"]):
        return "ήδη σε θέση"
    if len(state["positions"]) >= C.MAX_OPEN_POSITIONS:
        return "max ανοιχτές θέσεις"
    if state["daily"]["realized"] <= -C.MAX_DAILY_LOSS_USD:
        return "όριο ημερήσιας ζημιάς"
    if state["balance"] < C.MIN_ORDER_USD:
        return "χωρίς υπόλοιπο"
    return None


def open_position(state, sym, price, atr, exit_level, now):
    size = min(state["balance"], equity(state) * C.ALLOC_FRACTION)
    qty = size / (price * (1 + COST))
    stop = price - STRAT.stop_atr * atr
    state["balance"] -= size
    pos = {
        "id": state["next_id"], "sym": sym, "name": f"{sym}/USD",
        "entry_time": iso(now), "entry_market": price, "qty": qty, "cost": round(size, 6),
        "atr": atr, "stop": stop, "stop_pct": round(100 * (stop / price - 1), 2),
        "exit_level": exit_level,
        "last_price": price, "last_pct": 0.0, "peak_price": price, "peak_pct": 0.0,
    }
    state["next_id"] += 1
    state["positions"].append(pos)
    state["daily"]["entries"] += 1
    log(state, now, f"ΑΓΟΡΑ #{pos['id']} {sym} @ ${price:,.2f} (${size:.2f}) · stop ${stop:,.2f}")
    return pos


def close_position(state, pos, price, now, reason):
    proceeds = pos["qty"] * price * (1 - COST)
    pnl = proceeds - pos["cost"]
    state["balance"] += proceeds
    state["daily"]["realized"] += pnl
    hold = (now - parse_time(pos["entry_time"])).total_seconds() / 60
    t = dict(pos)
    t.update({"exit_time": iso(now), "exit_market": price, "proceeds": round(proceeds, 4), "pnl": round(pnl, 4),
              "pnl_pct": round(100 * pnl / pos["cost"], 2) if pos["cost"] else 0.0,
              "reason": reason, "hold_min": round(hold, 1)})
    state["positions"] = [x for x in state["positions"] if x["id"] != pos["id"]]
    state["closed"].append(t)
    state.setdefault("last_exit", {})[pos["sym"]] = iso(now)
    log(state, now, f"ΠΩΛΗΣΗ #{pos['id']} {pos['sym']} @ ${price:,.2f} — {reason} — {pnl:+.2f}$")
    return t


def on_tick(state, sym, price, now):
    """Κάθε γύρο: ενημέρωση θέσης και έλεγχος stop."""
    for pos in [p for p in state["positions"] if p["sym"] == sym]:
        pos["last_price"] = price
        pos["last_pct"] = round(100 * (price / pos["entry_market"] - 1), 2)
        if price > pos["peak_price"]:
            pos["peak_price"] = price
            pos["peak_pct"] = round(100 * (price / pos["entry_market"] - 1), 2)
        if price <= pos["stop"]:
            close_position(state, pos, price, now, "stop")


def bar_signals(bars):
    """Δείκτες της στρατηγικής στο τελευταίο κλειστό κερί."""
    b = {k: [x[k] for x in bars] for k in ("t", "o", "h", "l", "c")}
    ind = STRAT.prepare(b)
    i = len(bars) - 1
    return {
        "bar_t": bars[-1]["t"], "close": b["c"][i], "hh20": ind["hh20"][i], "ll10": ind["ll10"][i], "atr": ind["atr"][i],
        "entry": STRAT.entry(ind, i), "exit": STRAT.exit_signal(ind, i),
    }


def on_bar(state, sym, bars, price, now):
    """Καλείται όταν υπάρχει νέο κλειστό κερί 4ω (ήδη διασταυρωμένο). Επιστρέφει τι έγινε."""
    if len(bars) < 30:
        return "λίγα κεριά"
    sig = bar_signals(bars)
    if state["bars"].get(sym) == sig["bar_t"]:
        return "ήδη ελέγχθηκε"
    state["bars"][sym] = sig["bar_t"]
    state["stats"]["bars_checked"] += 1
    state["signals"][sym] = {k: sig[k] for k in ("bar_t", "close", "hh20", "ll10", "atr")}
    state["signals"][sym]["checked"] = iso(now)
    close_ms = sig["bar_t"] + C.BAR_SECONDS * 1000
    late = (now.timestamp() * 1000 - close_ms) / 60000 > C.ACT_WINDOW_MIN
    pos = next((p for p in state["positions"] if p["sym"] == sym), None)
    if pos:
        pos["exit_level"] = sig["ll10"]
        if sig["exit"] and price:
            close_position(state, pos, price, now, "κάτω από χαμηλό 10 κεριών")
            return "έξοδος"
        return "κράτημα"
    if not sig["entry"]:
        return "χωρίς σήμα"
    le = parse_time(state.get("last_exit", {}).get(sym))
    if le and le.timestamp() * 1000 >= sig["bar_t"]:
        return "έξοδος στο ίδιο κερί"           # όπως στο backtest: όχι νέα αγορά στο κερί που έκλεισε θέση
    if late:
        log(state, now, f"{sym}: σήμα αγοράς σε παλιό κερί — αγνοείται (δεν μπαίνουμε καθυστερημένα)")
        return "αργά"
    if not price or not sig["atr"]:
        log(state, now, f"{sym}: σήμα αγοράς αλλά χωρίς επιβεβαιωμένη τιμή — αναβολή")
        state["bars"].pop(sym, None)        # ξαναδοκιμάζει στον επόμενο γύρο
        return "χωρίς τιμή"
    blocked = can_open(state, sym)
    if blocked:
        log(state, now, f"{sym}: σήμα αγοράς αλλά {blocked}")
        return blocked
    open_position(state, sym, price, sig["atr"], sig["ll10"], now)
    return "αγορά"


def snapshot(state, now):
    h = state["equity_history"]
    last = parse_time(h[-1][0]) if h else None
    if not last or (now - last).total_seconds() >= C.SNAPSHOT_MINUTES * 60:
        h.append([iso(now), round(equity(state), 4)])
    state["equity_history"] = h[-15000:]
    state["last_run"] = iso(now)
