# crypto-paper-bot

**Μόνο εικονικά χρήματα (paper).** Κανένα πορτοφόλι, κανένα API key, καμία πραγματική εντολή.

Βήμα 1: backtest τριών απλών intraday στρατηγικών σε BTC, ETH, SOL (κεριά 15′ και 5′, ~3 χρόνια),
με κόστη 0,1% fee + 0,05% slippage ανά πλευρά. Κρίνουμε ΜΟΝΟ από τους τελευταίους 6 μήνες (out-of-sample).

- Υπόθεση 1 (intraday 5′/15′): [results/BACKTEST.md](results/BACKTEST.md) — **απέτυχε**
- Υπόθεση 2 (trend following 4ω/ημέρα, από 09/2020): [results/BACKTEST_TREND.md](results/BACKTEST_TREND.md)
- Έλεγχος δεδομένων: [results/data_check.json](results/data_check.json)

Βήμα 2 (live paper bot + dashboard) γίνεται **μόνο** αν κάποια στρατηγική περάσει το κριτήριο out-of-sample.
