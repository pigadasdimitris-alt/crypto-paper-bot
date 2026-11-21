"""Τρεις απλές, εξηγήσιμες στρατηγικές (μόνο long, spot).

Οι παράμετροι είναι οι «κλασικές» τιμές των βιβλίων και ορίστηκαν ΠΡΙΝ το backtest.
Δεν γίνεται βελτιστοποίηση παραμέτρων (για να μην υπάρχει overfitting).

Κάθε στρατηγική:
  prepare(bars)        -> dict με δείκτες
  entry(ind, i)        -> True αν στο ΚΛΕΙΣΙΜΟ της μπάρας i βγαίνει σήμα αγοράς
  exit_signal(ind, i)  -> True αν στο κλείσιμο της i πρέπει να βγούμε (πέρα από stop/στόχο)
  stop_atr / target_atr / max_hold_bars
Η εκτέλεση γίνεται στο ΑΝΟΙΓΜΑ της επόμενης μπάρας (ρεαλιστικό, χωρίς ματιά στο μέλλον).
"""
from . import indicators as I


class Strategy:
    key = ""
    name = ""
    description = ""
    stop_atr = 2.0
    target_atr = 3.0
    max_hold_bars = 48

    def prepare(self, bars):
        c, h, l = bars["c"], bars["h"], bars["l"]
        return {"c": c, "h": h, "l": l, "atr": I.atr(h, l, c, 14), "ema200": I.ema(c, 200)}

    def entry(self, ind, i):
        raise NotImplementedError

    def exit_signal(self, ind, i):
        return False


class Breakout(Strategy):
    key = "breakout"
    name = "Breakout εύρους"
    description = ("Αγορά όταν το κλείσιμο σπάει το υψηλό των 20 προηγούμενων μπαρών, μόνο σε ανοδική τάση "
                   "(τιμή πάνω από EMA200). Stop 1,5×ATR, στόχος 3×ATR, έως 48 μπάρες.")
    stop_atr, target_atr, max_hold_bars = 1.5, 3.0, 48

    def prepare(self, bars):
        ind = super().prepare(bars)
        ind["hh20"] = I.highest_prev(bars["h"], 20)
        return ind

    def entry(self, ind, i):
        hh, e = ind["hh20"][i], ind["ema200"][i]
        return hh is not None and e is not None and ind["c"][i] > hh and ind["c"][i] > e


class MeanReversion(Strategy):
    key = "meanrev"
    name = "Mean reversion RSI/Bollinger"
    description = ("Αγορά όταν η τιμή κλείνει κάτω από την κάτω Bollinger (20, 2) με RSI(14) < 30, "
                   "μόνο όταν EMA50 > EMA200 (ανοδική τάση). Έξοδος στη μέση Bollinger, stop 2×ATR, "
                   "στόχος 2×ATR, έως 24 μπάρες.")
    stop_atr, target_atr, max_hold_bars = 2.0, 2.0, 24

    def prepare(self, bars):
        ind = super().prepare(bars)
        c = bars["c"]
        ind["mid"] = I.sma(c, 20)
        ind["sd"] = I.stdev(c, 20)
        ind["rsi"] = I.rsi(c, 14)
        ind["ema50"] = I.ema(c, 50)
        return ind

    def entry(self, ind, i):
        m, s, r, e50, e200 = ind["mid"][i], ind["sd"][i], ind["rsi"][i], ind["ema50"][i], ind["ema200"][i]
        if None in (m, s, r, e50, e200):
            return False
        return ind["c"][i] < m - 2 * s and r < 30 and e50 > e200

    def exit_signal(self, ind, i):
        m = ind["mid"][i]
        return m is not None and ind["c"][i] >= m


class EmaTrend(Strategy):
    key = "ema"
    name = "Trend following EMA 20/50"
    description = ("Αγορά όταν η EMA20 περνά πάνω από την EMA50 και η τιμή είναι πάνω από EMA200. "
                   "Έξοδος όταν η EMA20 πέσει κάτω από την EMA50, stop 2×ATR, στόχος 4×ATR, έως 96 μπάρες.")
    stop_atr, target_atr, max_hold_bars = 2.0, 4.0, 96

    def prepare(self, bars):
        ind = super().prepare(bars)
        ind["e20"] = I.ema(bars["c"], 20)
        ind["e50"] = I.ema(bars["c"], 50)
        return ind

    def entry(self, ind, i):
        if i < 1:
            return False
        a0, b0, a1, b1, e = ind["e20"][i - 1], ind["e50"][i - 1], ind["e20"][i], ind["e50"][i], ind["ema200"][i]
        if None in (a0, b0, a1, b1, e):
            return False
        return a0 <= b0 and a1 > b1 and ind["c"][i] > e

    def exit_signal(self, ind, i):
        a, b = ind["e20"][i], ind["e50"][i]
        return a is not None and b is not None and a < b


ALL = [Breakout(), MeanReversion(), EmaTrend()]
BY_KEY = {s.key: s for s in ALL}
