"""Λήψη ιστορικών κεριών (τρέχει μέσα στο GitHub Actions).

Κύρια πηγή: data.binance.vision (δημόσια αρχεία ZIP, μηνιαία + ημερήσια για τον τρέχοντα μήνα).
Εφεδρική: Coinbase Exchange public candles με σελιδοποίηση.
Μετά τη λήψη γίνεται έλεγχος ποιότητας και διασταύρωση ημερήσιων κλεισιμάτων με δεύτερη πηγή (Coinbase).

Αποθήκευση: data/{SYM}_{tf}.csv  ->  t_ms,open,high,low,close,volume
"""
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config as C

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
UA = {"User-Agent": "crypto-paper-bot/1.0 (paper trading research)"}
TF_SEC = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}


def _get(url, retries=3, binary=False):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
                return b if binary else json.loads(b.decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


def parse_binance_csv(text):
    """Γραμμές kline της Binance. Από το 2025 τα spot αρχεία έχουν timestamps σε μικροδευτερόλεπτα."""
    rows = []
    for r in csv.reader(io.StringIO(text)):
        if not r or not r[0].strip().isdigit():
            continue  # επικεφαλίδα ή κενή γραμμή
        t = int(r[0])
        if t > 10 ** 14:      # μs -> ms
            t //= 1000
        rows.append([t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    return rows


def _unzip(b):
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        return z.read(z.namelist()[0]).decode()


def months(start, end):
    y, m = start.year, start.month
    while (y, m) < (end.year, end.month):
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def binance_vision(sym, tf, start, today):
    pair = C.BINANCE_PAIR[sym]
    base = "https://data.binance.vision/data/spot"
    rows, missing = [], 0
    for ym in months(start, today):
        b = _get(f"{base}/monthly/klines/{pair}/{tf}/{pair}-{tf}-{ym}.zip", binary=True)
        if b is None:
            missing += 1
            continue
        rows += parse_binance_csv(_unzip(b))
    d = date(today.year, today.month, 1)
    while d < today:
        b = _get(f"{base}/daily/klines/{pair}/{tf}/{pair}-{tf}-{d.isoformat()}.zip", binary=True)
        if b is not None:
            rows += parse_binance_csv(_unzip(b))
        d += timedelta(days=1)
    return rows, missing


def coinbase(sym, tf, start, today, granularity=None):
    """Coinbase δίνει έως 300 κεριά ανά κλήση: [time, low, high, open, close, volume] (φθίνουσα σειρά)."""
    g = granularity or TF_SEC[tf]
    pair = C.COINBASE_PAIR[sym]
    t0 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    t_end = int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp())
    rows = []
    while t0 < t_end:
        t1 = min(t0 + 300 * g, t_end)
        s = datetime.fromtimestamp(t0, timezone.utc).isoformat()
        e = datetime.fromtimestamp(t1, timezone.utc).isoformat()
        d = _get(f"https://api.exchange.coinbase.com/products/{pair}/candles?granularity={g}&start={s}&end={e}")
        for k in d or []:
            rows.append([int(k[0]) * 1000, float(k[3]), float(k[2]), float(k[1]), float(k[4]), float(k[5])])
        t0 = t1
        time.sleep(0.25)
    return rows


def clean(rows, tf):
    """Ταξινόμηση, αφαίρεση διπλών και χαλασμένων κεριών. Επιστρέφει (rows, στατιστικά)."""
    by_t = {}
    bad = 0
    for r in rows:
        t, o, h, l, c, v = r
        if min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h):
            bad += 1
            continue
        by_t[t] = r
    out = [by_t[t] for t in sorted(by_t)]
    step = TF_SEC[tf] * 1000
    gaps = sum(1 for a, b in zip(out, out[1:]) if b[0] - a[0] > step)
    # ακραία κεριά: κίνηση >25% μέσα σε ένα κερί 5'/15' είναι σχεδόν σίγουρα λάθος δεδομένων
    spikes = sum(1 for r in out if r[2] / r[3] > 1.25)
    return out, {"bars": len(out), "bad_removed": bad, "gaps": gaps, "spikes_over_25pct": spikes}


def daily_closes(rows):
    d = {}
    for t, o, h, l, c, v in rows:
        d[datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat()] = c
    return d


def cross_check(sym, rows, start, today):
    """Σύγκριση ημερήσιων κλεισιμάτων με Coinbase (δεύτερη ανεξάρτητη πηγή)."""
    ref = daily_closes(coinbase(sym, "1d", start, today, granularity=86400))
    ours = daily_closes(rows)
    common = [k for k in ours if k in ref]
    if not common:
        return {"days_compared": 0}
    devs = sorted((abs(ours[k] / ref[k] - 1), k) for k in common)
    return {"days_compared": len(common), "max_dev_pct": round(100 * devs[-1][0], 3), "max_dev_day": devs[-1][1],
            "days_over_2pct": sum(1 for d, _ in devs if d > 0.02)}


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "open", "high", "low", "close", "volume"])
        w.writerows(rows)


def main():
    DATA.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    start = date.fromisoformat(C.HISTORY_START)
    today = datetime.now(timezone.utc).date()
    report = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "series": {}}
    for sym in C.SYMBOLS:
        for tf in C.TIMEFRAMES:
            rows, missing = binance_vision(sym, tf, start, today)
            source = "data.binance.vision"
            if missing > 1 or len(rows) < 1000:
                print(f"{sym} {tf}: binance.vision απέτυχε ({missing} μήνες λείπουν) -> Coinbase", flush=True)
                rows, source = coinbase(sym, tf, start, today), "coinbase"
            rows, stats = clean(rows, tf)
            stats["source"] = source
            if rows:
                stats["from"] = datetime.fromtimestamp(rows[0][0] / 1000, timezone.utc).isoformat()
                stats["to"] = datetime.fromtimestamp(rows[-1][0] / 1000, timezone.utc).isoformat()
            if tf == C.TIMEFRAMES[0]:
                stats["cross_check_coinbase"] = cross_check(sym, rows, start, today)
            write_csv(DATA / f"{sym}_{tf}.csv", rows)
            report["series"][f"{sym}_{tf}"] = stats
            print(sym, tf, json.dumps(stats, ensure_ascii=False), flush=True)
    (RESULTS / "data_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    if any(s["bars"] < 1000 for s in report["series"].values()):
        sys.exit("Ανεπαρκή δεδομένα")


if __name__ == "__main__":
    main()
