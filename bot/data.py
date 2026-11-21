"""Live δημόσια δεδομένα από δύο ανεξάρτητες πηγές: Coinbase Exchange και Kraken. Μόνο ανάγνωση."""
import json
import time
import urllib.error
import urllib.request

from . import config as C

CB = "https://api.exchange.coinbase.com"
KR = "https://api.kraken.com/0/public"
UA = {"User-Agent": "crypto-paper-bot/1.0 (paper trading research)", "Accept": "application/json"}


def _get(url, retries=2):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


def _pos(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def coinbase_price(sym):
    d = _get(f"{CB}/products/{C.COINBASE_PAIR[sym]}/ticker")
    return _pos((d or {}).get("price"))


def _kraken_result(d):
    if not d or d.get("error"):
        return None
    res = d.get("result") or {}
    for k, v in res.items():
        if k != "last":
            return v
    return None


def kraken_price(sym):
    v = _kraken_result(_get(f"{KR}/Ticker?pair={C.KRAKEN_PAIR[sym]}"))
    try:
        return _pos(v["c"][0])
    except Exception:
        return None


def parse_kraken_ohlc(rows, now_s):
    """Kraken: [time, open, high, low, close, vwap, volume, count]. Κρατάμε ΜΟΝΟ κλειστά κεριά."""
    out = []
    for r in rows or []:
        t = int(r[0])
        if t + C.BAR_SECONDS <= now_s:
            out.append({"t": t * 1000, "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])})
    return out


def kraken_4h(sym, now_s):
    rows = _kraken_result(_get(f"{KR}/OHLC?pair={C.KRAKEN_PAIR[sym]}&interval=240"))
    return parse_kraken_ohlc(rows, now_s)


def resample_coinbase_1h(rows, now_s):
    """Coinbase 1ω [time, low, high, open, close, vol] -> κλειστά κεριά 4ω (μόνο πλήρη, με 4 ωριαία)."""
    groups = {}
    for r in rows or []:
        t = int(r[0])
        k = t - t % C.BAR_SECONDS
        groups.setdefault(k, []).append((t, float(r[3]), float(r[2]), float(r[1]), float(r[4])))
    out = []
    for k in sorted(groups):
        g = sorted(groups[k])
        if len(g) == 4 and k + C.BAR_SECONDS <= now_s:
            out.append({"t": k * 1000, "o": g[0][1], "h": max(x[2] for x in g), "l": min(x[3] for x in g), "c": g[-1][4]})
    return out


def coinbase_4h(sym, now_s):
    rows = _get(f"{CB}/products/{C.COINBASE_PAIR[sym]}/candles?granularity=3600")
    return resample_coinbase_1h(rows if isinstance(rows, list) else [], now_s)
