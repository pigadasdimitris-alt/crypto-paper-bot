"""Απλοί τεχνικοί δείκτες σε καθαρή Python. Όλοι είναι αιτιατοί: η τιμή στη θέση i
χρησιμοποιεί ΜΟΝΟ δεδομένα έως και την i (καμία ματιά στο μέλλον)."""
import math


def ema(x, n):
    out = [None] * len(x)
    if len(x) < n:
        return out
    a = 2 / (n + 1)
    v = sum(x[:n]) / n          # σπόρος: SMA των πρώτων n
    out[n - 1] = v
    for i in range(n, len(x)):
        v = a * x[i] + (1 - a) * v
        out[i] = v
    return out


def sma(x, n):
    out = [None] * len(x)
    s = 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def stdev(x, n):
    """Κυλιόμενη τυπική απόκλιση πληθυσμού (όπως στις Bollinger)."""
    out = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / n)
    return out


def rsi(c, n=14):
    """RSI με εξομάλυνση Wilder."""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(h, l, c, n=14):
    """Average True Range (Wilder)."""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    v = sum(tr[1:n + 1]) / n
    out[n] = v
    for i in range(n + 1, len(c)):
        v = (v * (n - 1) + tr[i]) / n
        out[i] = v
    return out


def highest_prev(h, n):
    """Υψηλότερο high των n ΠΡΟΗΓΟΥΜΕΝΩΝ μπαρών (χωρίς την τρέχουσα)."""
    out = [None] * len(h)
    from collections import deque
    dq = deque()  # δείκτες με φθίνουσες τιμές
    for i in range(len(h)):
        if i >= n:
            while dq and dq[0] < i - n:
                dq.popleft()
            out[i] = h[dq[0]]
        while dq and h[dq[-1]] <= h[i]:
            dq.pop()
        dq.append(i)
    return out


def lowest_prev(l, n):
    """Χαμηλότερο low των n ΠΡΟΗΓΟΥΜΕΝΩΝ μπαρών (χωρίς την τρέχουσα)."""
    neg = highest_prev([-v for v in l], n)
    return [None if v is None else -v for v in neg]
