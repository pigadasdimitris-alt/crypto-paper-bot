import random
from datetime import datetime, timedelta, timezone

import pytest

from bot import backtest as B
from bot import config as C
from bot import data as D
from bot import engine as E
from bot import strategies as S

T0 = datetime(2026, 11, 21, 12, 0, 5, tzinfo=timezone.utc)
H4 = C.BAR_SECONDS * 1000


def st():
    return E.new_state(T0)


# ---------------- έλεγχος τιμών ----------------

def test_two_sources_agree_accepted():
    s = st()
    assert E.validate_price(s, "BTC", 100000, 100300, T0) == 100000


def test_two_sources_disagree_rejected():
    s = st()
    assert E.validate_price(s, "BTC", 100000, 103000, T0) is None
    assert s["stats"]["price_rejects"] == 1


def test_fake_spike_from_one_source_needs_confirmation():
    """Το μάθημα των 1.150.000$: μια τρελή τιμή από μία πηγή ΔΕΝ γίνεται δεκτή αμέσως."""
    s = st()
    E.validate_price(s, "SOL", 140, 140.2, T0)
    assert E.validate_price(s, "SOL", 1400, None, T0) is None          # 10x από μία πηγή
    assert E.validate_price(s, "SOL", 141, None, T0) == 141            # κανονική τιμή -> δεκτή
    assert E.validate_price(s, "SOL", 1400, None, T0) is None
    assert E.validate_price(s, "SOL", 1401, None, T0) == 1401          # επιβεβαιώθηκε σε 2ο γύρο


def test_big_move_confirmed_by_both_sources_accepted():
    s = st()
    E.validate_price(s, "ETH", 3000, 3001, T0)
    assert E.validate_price(s, "ETH", 2600, 2602, T0) == 2600


def test_no_sources():
    assert E.validate_price(st(), "BTC", None, None, T0) is None


def test_candle_cross_check():
    kr = [{"t": 0, "o": 1, "h": 2, "l": 0.5, "c": 100.0}]
    assert E.validate_candles(kr, [{"t": 0, "c": 100.4}])[0]
    assert not E.validate_candles(kr, [{"t": 0, "c": 103.0}])[0]
    assert not E.validate_candles(kr, [{"t": 4, "c": 100.0}])[0]
    assert not E.validate_candles([], [])[0]


# ---------------- δεδομένα ----------------

def test_kraken_drops_open_candle():
    now = 10 * C.BAR_SECONDS + 100
    rows = [[8 * C.BAR_SECONDS, "1", "2", "0.5", "1.5", "0", "0", 0],
            [9 * C.BAR_SECONDS, "1", "2", "0.5", "1.6", "0", "0", 0],
            [10 * C.BAR_SECONDS, "1", "2", "0.5", "1.7", "0", "0", 0]]   # ανοιχτό
    out = D.parse_kraken_ohlc(rows, now)
    assert [b["c"] for b in out] == [1.5, 1.6]


def test_coinbase_resample_only_complete_closed():
    base = 5 * C.BAR_SECONDS
    rows = [[base + i * 3600, 9 + i, 11 + i, 10 + i, 10.5 + i, 1] for i in range(4)]       # πλήρες
    rows += [[base + C.BAR_SECONDS + i * 3600, 1, 2, 1, 1, 1] for i in range(2)]          # μισό
    rows.reverse()   # το Coinbase τα δίνει φθίνοντα
    out = D.resample_coinbase_1h(rows, base + 2 * C.BAR_SECONDS)
    assert len(out) == 1
    b = out[0]
    assert b["t"] == base * 1000 and b["o"] == 10 and b["c"] == 13.5 and b["h"] == 14 and b["l"] == 9


# ---------------- στρατηγική live = backtest ----------------

def make_bars(n=120, seed=1, trend=0.0):
    rnd = random.Random(seed)
    out, p = [], 100.0
    for i in range(n):
        o = p
        p = p * (1 + trend + rnd.gauss(0, 0.01))
        out.append({"t": i * H4, "o": o, "h": max(o, p) * 1.003, "l": min(o, p) * 0.997, "c": p})
    return out


def breakout_bars():
    bars = make_bars(60, seed=3)
    hh = max(b["h"] for b in bars[-20:])
    last = bars[-1]["c"]
    bars.append({"t": 60 * H4, "o": last, "h": hh * 1.05, "l": last * 0.99, "c": hh * 1.04})
    return bars


def at_close(bars, minutes=2):
    return datetime.fromtimestamp((bars[-1]["t"] + H4) / 1000, timezone.utc) + timedelta(minutes=minutes)


def test_live_signals_match_backtest_strategy():
    bars = make_bars(300, seed=9)
    b = {k: [x[k] for x in bars] for k in ("t", "o", "h", "l", "c")}
    ind = S.BY_KEY["donchian"].prepare(b)
    for n in range(40, 300, 7):
        sig = E.bar_signals(bars[:n])
        assert sig["entry"] == S.BY_KEY["donchian"].entry(ind, n - 1)
        assert sig["exit"] == S.BY_KEY["donchian"].exit_signal(ind, n - 1)


def test_entry_on_breakout_with_costs_and_sizing():
    s = st()
    bars = breakout_bars()
    now = at_close(bars)
    assert E.on_bar(s, "BTC", bars, 200.0, now) == "αγορά"
    p = s["positions"][0]
    assert p["cost"] == pytest.approx(70 / 3)
    assert p["qty"] == pytest.approx((70 / 3) / (200 * 1.0015))
    assert p["stop"] == pytest.approx(200 - 2 * E.bar_signals(bars)["atr"])
    # ίδιο κερί δεν ξαναελέγχεται
    assert E.on_bar(s, "BTC", bars, 200.0, now) == "ήδη ελέγχθηκε"
    # άμεση πώληση στην ίδια τιμή = ζημιά μόνο τα κόστη (~0,3%)
    t = E.close_position(s, p, 200.0, now, "test")
    assert t["pnl_pct"] == pytest.approx(100 * B.trade_return(200, 200), abs=1e-3)


def test_late_signal_ignored():
    s = st()
    bars = breakout_bars()
    assert E.on_bar(s, "BTC", bars, 200.0, at_close(bars, minutes=C.ACT_WINDOW_MIN + 5)) == "αργά"
    assert not s["positions"]


def test_stop_on_tick():
    s = st()
    bars = breakout_bars()
    E.on_bar(s, "ETH", bars, 200.0, at_close(bars))
    p = s["positions"][0]
    E.on_tick(s, "ETH", 210.0, T0)
    assert p["peak_pct"] == pytest.approx(5.0)
    E.on_tick(s, "ETH", p["stop"] - 0.01, T0)
    assert not s["positions"] and s["closed"][0]["reason"] == "stop"
    assert s["closed"][0]["pnl"] < 0


def test_channel_exit_on_bar():
    s = st()
    bars = breakout_bars()
    E.on_bar(s, "SOL", bars, 200.0, at_close(bars))
    ll = min(b["l"] for b in bars[-10:])
    nb = bars + [{"t": bars[-1]["t"] + H4, "o": 200, "h": 201, "l": ll * 0.9, "c": ll * 0.95}]
    # αν το κλείσιμο έπεσε κάτω από το stop, θα είχε βγει ήδη από το tick· εδώ ελέγχουμε το σήμα καναλιού
    s["positions"][0]["stop"] = 0
    assert E.on_bar(s, "SOL", nb, ll * 0.95, at_close(nb)) == "έξοδος"
    assert s["closed"][0]["reason"].startswith("κάτω από χαμηλό")


def test_no_reentry_in_bar_of_exit():
    s = st()
    bars = breakout_bars()
    E.on_bar(s, "BTC", bars, 200.0, at_close(bars))
    E.on_tick(s, "BTC", 1.0, at_close(bars, 30))          # stop μέσα στο επόμενο κερί
    nb = bars + [{"t": bars[-1]["t"] + H4, "o": 1, "h": 999, "l": 1, "c": 998}]
    assert E.on_bar(s, "BTC", nb, 998, at_close(nb)) == "έξοδος στο ίδιο κερί"


def test_risk_limits():
    s = st()
    s["daily"]["realized"] = -C.MAX_DAILY_LOSS_USD
    assert E.can_open(s, "BTC") == "όριο ημερήσιας ζημιάς"
    s = st()
    s["positions"] = [{"sym": x} for x in ("BTC", "ETH", "SOL")]
    assert E.can_open(s, "BTC") == "ήδη σε θέση"
    s["positions"] = [{"sym": x} for x in ("A", "B", "C")]
    assert E.can_open(s, "BTC") == "max ανοιχτές θέσεις"
    s = st()
    s["balance"] = 1
    assert E.can_open(s, "BTC") == "χωρίς υπόλοιπο"


def test_three_positions_use_all_capital_without_overdraft():
    s = st()
    bars = breakout_bars()
    now = at_close(bars)
    for sym in C.SYMBOLS:
        E.on_bar(s, sym, bars, 200.0, now)
    assert len(s["positions"]) == 3
    assert s["balance"] >= -1e-9
    assert E.equity(s) == pytest.approx(70 * (1 - E.COST) / (1 + E.COST), rel=1e-3)


def test_daily_roll_and_snapshot():
    s = st()
    s["daily"]["realized"] = -3
    E.roll_day(s, T0 + timedelta(days=1))
    assert s["daily"]["realized"] == 0
    E.snapshot(s, T0)
    E.snapshot(s, T0 + timedelta(minutes=1))
    E.snapshot(s, T0 + timedelta(minutes=11))
    assert len(s["equity_history"]) == 2
