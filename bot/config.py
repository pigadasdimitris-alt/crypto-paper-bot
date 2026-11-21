"""Ρυθμίσεις. Όλα εικονικά (paper) — κανένα πορτοφόλι, κανένα API key, καμία πραγματική εντολή."""

SYMBOLS = ["BTC", "ETH", "SOL"]
BINANCE_PAIR = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
COINBASE_PAIR = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
KRAKEN_PAIR = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD"}

# --- Ρεαλιστικά κόστη (ανά πλευρά: αγορά Η πώληση) ---
FEE_PER_SIDE = 0.001        # 0,1%
SLIPPAGE_PER_SIDE = 0.0005  # 0,05%

# --- Backtest ---
HISTORY_START = "2023-11-01"   # ~3 χρόνια ιστορικό (intraday)
TIMEFRAMES = ["15m", "5m"]

# Κάθε «σουίτα» είναι μια ξεχωριστή υπόθεση με κανόνες κλειδωμένους ΠΡΙΝ το τρέξιμο.
SUITES = {
    # Υπόθεση 1 (21/11/2026): intraday — ΑΠΕΤΥΧΕ σε όλα.
    "intraday": {"timeframes": ["15m", "5m"], "start": "2023-11-01",
                 "strategies": ["breakout", "meanrev", "ema"], "out": "BACKTEST"},
    # Υπόθεση 2 (21/11/2026): trend following σε μεγαλύτερα κεριά, όπου τα κόστη βαραίνουν λιγότερο.
    "trend": {"timeframes": ["4h", "1d"], "start": "2020-09-01",
              "strategies": ["donchian", "ema_slow", "sma50"], "out": "BACKTEST_TREND"},
}
OOS_DAYS = 182                 # τελευταίοι ~6 μήνες = «άγνωστα» δεδομένα (κρίνουμε ΜΟΝΟ από εδώ)
WARMUP_BARS = 250              # μπάρες για να «ζεσταθούν» οι δείκτες (EMA200 κ.λπ.)

# Κριτήρια για να θεωρηθεί μια στρατηγική «θετική» out-of-sample.
# Ορίστηκαν ΠΡΙΝ δούμε αποτελέσματα — δεν αλλάζουν μετά.
MIN_OOS_TRADES = 30
MIN_OOS_PROFIT_FACTOR = 1.15

# --- Live paper (Βήμα 2 — μόνο αν περάσει το backtest) ---
START_BALANCE_USD = 70.0
TIMEZONE = "Europe/Athens"
