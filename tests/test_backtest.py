import math
import random

import pytest

from bot import backtest as B
from bot import config as C
from bot import history as H
from bot import indicators as I
from bot import strategies as S


# ---------------- δείκτες ----------------

def test_sma_and_ema_basic():
    x = [1, 2, 3, 4, 5]
    assert I.sma(x, 3) == [None, None, 2, 3, 4]
    e = I.ema(x, 3)
    assert e[:2] == [None, None] and e[2] == 2
    assert e[3] == pytest.approx(0.5 * 4 + 0.5 * 2)


def test_stdev():
    s = I.stdev([2, 4, 4, 4, 5, 5, 7, 9], 8)
    assert s[-1] == pytest.approx(2.0)


def test_rsi_extremes():
    up = list(range(1, 40))
    assert I.rsi(up, 14)[-1] == 100.0
    down = list(range(40, 1, -1))
    assert I.rsi(down, 14)[-1] == pytest.approx(0.0)


def test_atr_constant_range():
    n = 40
    h = [11.0] * n; l = [9.0] * n; c = [10.0] * n
    assert I.atr(h, l, c, 14)[-1] == pytest.approx(2.0)


def test_highest_prev_excludes_current():
    h = [1, 5, 2, 3, 9, 1, 1, 1]
    out = I.highest_prev(h, 3)
    assert out[:3] == [None, None, None]
    assert out[3] == 5          # από [1,5,2]
    assert out[4] == 5          # από [5,2,3] — ΟΧΙ το 9 της τρέχουσας
    assert out[5] == 9
    assert out[7] == 9          # [9,1,1]
    # σύγκριση με αφελή υλοποίηση
    rnd = random.Random(1)
    x = [rnd.random() for _ in range(300)]
    o = I.highest_prev(x, 20)
    for i in range(20, 300):
        assert o[i] == max(x[i - 20:i])


def test_indicators_are_causal():
    """Αλλαγή στο μέλλον δεν επηρεάζει παλιές τιμές δεικτών."""
    rnd = random.Random(2)
    c = [100 + rnd.gauss(0, 1) for _ in range(300)]
    c2 = c[:200] + [x * 3 for x in c[200:]]
    for f in (lambda x: I.ema(x, 20), lambda x: I.rsi(x, 14), lambda x: I.sma(x, 20), lambda x: I.stdev(x, 20)):
        assert f(c)[:200] == f(c2)[:200]


# ---------------- εκτέλεση / κόστη ----------------

def test_trade_return_includes_costs():
    cost = C.FEE_PER_SIDE + C.SLIPPAGE_PER_SIDE
    assert cost == pytest.approx(0.0015)
    r = B.trade_return(100, 100)
    assert r == pytest.approx(0.9985 / 1.0015 - 1)
    assert r < -0.0029


class _Always(S.Strategy):
    key = "always"; stop_atr = 1.0; target_atr = 1.0; max_hold_bars = 5

    def entry(self, ind, i):
        return True


def _bars(closes, spread=0.5):
    n = len(closes)
    o = [closes[0]] + closes[:-1]
    return {"t": [i * 900_000 for i in range(n)], "o": list(o), "c": list(closes),
            "h": [max(a, b) + spread for a, b in zip(o, closes)], "l": [min(a, b) - spread for a, b in zip(o, closes)]}


def test_entry_at_next_open_and_stop_first(monkeypatch):
    monkeypatch.setattr(C, "WARMUP_BARS", 20)
    closes = [100.0] * 30
    b = _bars(closes)
    # η μπάρα 22 αγγίζει ΚΑΙ stop ΚΑΙ στόχο -> πρέπει να μετρήσει stop
    b["h"][22] = 200.0
    b["l"][22] = 1.0
    st = _Always()
    trades, _ = B.simulate(st, b, 0, 30)
    t0 = trades[0]
    assert t0["entry_t"] == b["t"][21]          # σήμα στη 20 -> αγορά στο άνοιγμα της 21
    assert t0["entry"] == b["o"][21]
    second = [t for t in trades if t["entry_t"] == b["t"][22]]
    first_touching = [t for t in trades if t["exit_t"] == b["t"][22]]
    assert first_touching and first_touching[0]["reason"] == "stop"
    assert second == [] or second[0]["reason"] in ("stop", "στόχος", "χρόνος", "τέλος δεδομένων")


def test_gap_below_stop_exits_at_open(monkeypatch):
    monkeypatch.setattr(C, "WARMUP_BARS", 20)
    b = _bars([100.0] * 30)
    b["o"][23] = 50.0; b["l"][23] = 49.0; b["c"][23] = 51.0; b["h"][23] = 52.0
    trades, _ = B.simulate(_Always(), b, 0, 30)
    t = [x for x in trades if x["exit_t"] == b["t"][23]][0]
    assert t["exit"] == 50.0 and t["reason"] == "stop"


def test_no_lookahead_in_simulation(monkeypatch):
    """Τα trades πριν από μια αλλαγή στα δεδομένα δεν επηρεάζονται από τη μετέπειτα αλλαγή."""
    rnd = random.Random(5)
    closes = [100.0]
    for _ in range(2000):
        closes.append(closes[-1] * (1 + rnd.gauss(0, 0.004)))
    b1 = _bars(closes)
    closes2 = closes[:1500] + [x * 1.5 for x in closes[1500:]]
    b2 = _bars(closes2)
    for st in S.ALL:
        t1, _ = B.simulate(st, b1, 0, 2000)
        t2, _ = B.simulate(st, b2, 0, 2000)
        early1 = [t for t in t1 if t["exit_t"] < b1["t"][1499]]
        early2 = [t for t in t2 if t["exit_t"] < b1["t"][1499]]
        assert early1 == early2


def test_random_walk_loses_after_costs():
    """Σε τυχαίο περίπατο καμία στρατηγική δεν πρέπει να «βγάζει» λεφτά σταθερά — τα κόστη τρώνε."""
    rnd = random.Random(7)
    closes = [100.0]
    for _ in range(20000):
        closes.append(closes[-1] * math.exp(rnd.gauss(0, 0.003)))
    b = _bars(closes, spread=0.1)
    for st in S.ALL:
        trades, cv = B.simulate(st, b, 0, len(closes))
        m = B.metrics(trades, cv)
        assert m["trades"] > 20
        assert m["avg_trade_pct"] < 0.1


def test_metrics_values():
    trades = [{"ret": 0.10}, {"ret": -0.05}, {"ret": 0.05}, {"ret": -0.10}]
    curve = [(0, 1.0), (1, 1.2), (2, 0.9), (3, 1.1)]
    m = B.metrics(trades, curve)
    assert m["trades"] == 4
    assert m["win_rate"] == 50
    assert m["profit_factor"] == pytest.approx(1.0)
    assert m["avg_trade_pct"] == pytest.approx(0.0)
    assert m["max_dd_pct"] == pytest.approx(-25.0)
    assert m["total_return_pct"] == pytest.approx(10.0)


def test_combine_equal_weight():
    a = [(1, 1.0), (2, 1.2)]
    b = [(1, 1.0), (2, 0.8)]
    c = [(1, 1.0), (3, 1.3)]
    out = B.combine([a, b, c])
    assert out[1] == (2, pytest.approx(1.0))
    assert out[2] == (3, pytest.approx((1.2 + 0.8 + 1.3) / 3))


def test_positive_criterion():
    good = {"trades": 50, "profit_factor": 1.3, "total_return_pct": 5}
    assert B.is_positive(good)
    assert not B.is_positive({**good, "trades": 10})
    assert not B.is_positive({**good, "profit_factor": 1.05})
    assert not B.is_positive({**good, "total_return_pct": -1})


def test_split_index_last_months(monkeypatch):
    monkeypatch.setattr(C, "OOS_DAYS", 10)
    t = [i * 86400_000 for i in range(100)]
    k = B.split_index({"t": t})
    assert k == 89


# ---------------- δεδομένα ----------------

def test_parse_binance_microseconds_and_header():
    text = ("open_time,open,high,low,close,volume\n"
            "1735689600000000,1,2,0.5,1.5,10,0,0,0,0,0,0\n"
            "1704067200000,1,2,0.5,1.5,10,0,0,0,0,0,0\n")
    rows = H.parse_binance_csv(text)
    assert rows[0][0] == 1735689600000
    assert rows[1][0] == 1704067200000
    assert len(rows) == 2


def test_clean_removes_bad_and_duplicates():
    rows = [[2, 1, 2, 0.5, 1.5, 1], [1, 1, 2, 0.5, 1.5, 1], [1, 1, 2, 0.5, 1.5, 1],
            [3, 1, 0.9, 0.5, 1.5, 1],   # high < close -> χαλασμένο
            [4, -1, 2, 0.5, 1.5, 1]]
    out, st = H.clean(rows, "15m")
    assert [r[0] for r in out] == [1, 2]
    assert st["bad_removed"] == 2


# ---------------- υπόθεση 2 ----------------

def test_lowest_prev():
    rnd = random.Random(3)
    x = [rnd.random() for _ in range(200)]
    o = I.lowest_prev(x, 10)
    assert o[:10] == [None] * 10
    for i in range(10, 200):
        assert o[i] == min(x[i - 10:i])


def test_trend_strategies_ride_a_trend(monkeypatch):
    """Σε καθαρή ανοδική τάση οι trend στρατηγικές πρέπει να κερδίζουν, και να μη χάνουν σε τυχαίο περίπατο σταθερά."""
    monkeypatch.setattr(C, "WARMUP_BARS", 60)
    rnd = random.Random(11)
    closes = [100.0]
    for i in range(1500):
        drift = -0.004 if i < 300 else 0.004
        closes.append(closes[-1] * math.exp(drift + rnd.gauss(0, 0.01)))
    b = _bars(closes, spread=0.2)
    for st in S.TREND:
        trades, cv = B.simulate(st, b, 0, len(closes))
        assert trades, st.key
        assert B.metrics(trades, cv)["total_return_pct"] > 50, st.key


def test_trend_strategies_no_lookahead():
    rnd = random.Random(12)
    closes = [100.0]
    for _ in range(1200):
        closes.append(closes[-1] * (1 + rnd.gauss(0, 0.01)))
    b1 = _bars(closes)
    b2 = _bars(closes[:900] + [x * 0.5 for x in closes[900:]])
    for st in S.TREND:
        t1, _ = B.simulate(st, b1, 0, 1200)
        t2, _ = B.simulate(st, b2, 0, 1200)
        cut = b1["t"][899]
        assert [t for t in t1 if t["exit_t"] < cut] == [t for t in t2 if t["exit_t"] < cut]


def test_resample_1h_to_4h():
    h = 3600_000
    rows = [[i * h, 10 + i, 20 + i, 1 + i, 11 + i, 1] for i in range(8)]
    out = H.resample(rows, 14400)
    assert len(out) == 2
    assert out[0] == [0, 10, 23, 1, 14, 4]
    assert out[1][1] == 14 and out[1][4] == 18


def test_suites_defined():
    for name, cfg in C.SUITES.items():
        for k in cfg["strategies"]:
            assert k in S.BY_KEY
        for tf in cfg["timeframes"]:
            assert tf in H.TF_SEC
