"""Κύριος βρόχος: τρέχει ~55 λεπτά. Κάθε 60'': τιμές από 2 πηγές -> stop· σε νέο κερί 4ω -> σήματα. Αποθηκεύει στο repo."""
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config as C
from . import data, engine
from .report import write_readme

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATE = DOCS / "state.json"
TRADES = DOCS / "trades.csv"


def load_state(now):
    if STATE.exists():
        state = json.loads(STATE.read_text())
        engine.apply_new_capital(state, now)
        return state
    return engine.new_state(now)


def save(state):
    DOCS.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    cols = ["id", "sym", "entry_time", "exit_time", "hold_min", "entry_market", "exit_market", "stop",
            "cost", "proceeds", "pnl", "pnl_pct", "peak_pct", "reason"]
    with TRADES.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for t in state["closed"]:
            w.writerow(t)
    write_readme(state, ROOT / "README.md")


def git_commit(msg):
    if os.environ.get("NO_GIT"):
        return
    subprocess.run(["git", "add", "docs", "README.md"], cwd=ROOT, check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=ROOT, check=False)
    for _ in range(3):
        if subprocess.run(["git", "push", "-q"], cwd=ROOT).returncode == 0:
            return
        subprocess.run(["git", "pull", "-q", "--rebase", "-X", "theirs"], cwd=ROOT, check=False)


def one_cycle(state):
    now = engine.now_utc()
    engine.roll_day(state, now)
    state["stats"]["cycles"] += 1
    now_s = int(now.timestamp())
    cur_bar = now_s - now_s % C.BAR_SECONDS
    for sym in C.SYMBOLS:
        price = engine.validate_price(state, sym, data.coinbase_price(sym), data.kraken_price(sym), now)
        if price:
            engine.on_tick(state, sym, price, now)
        # νέο κερί 4ω; (ελέγχουμε μία φορά ανά κερί, ή ξανά αν η διασταύρωση απέτυχε)
        last_done = state["bars"].get(sym)
        if last_done is not None and last_done + C.BAR_SECONDS * 1000 >= cur_bar * 1000:
            continue
        kr = data.kraken_4h(sym, now_s)
        cb = data.coinbase_4h(sym, now_s)
        ok, why = engine.validate_candles(kr, cb)
        if not ok:
            state["stats"]["candle_rejects"] += 1
            engine.log(state, now, f"{sym}: κερί 4ω χωρίς διασταύρωση ({why}) — ξαναδοκιμάζει")
            continue
        res = engine.on_bar(state, sym, kr, price, now)
        if res in ("χωρίς σήμα", "κράτημα"):
            s = state["signals"][sym]
            engine.log(state, now, f"{sym}: κερί 4ω έκλεισε ${s['close']:,.2f} — {res}"
                                   f" (σπάσιμο πάνω από ${s['hh20']:,.2f}, έξοδος κάτω από ${s['ll10']:,.2f})")
    engine.snapshot(state, engine.now_utc())


def main():
    run_minutes = float(os.environ.get("RUN_MINUTES", "55"))
    commit_every = int(os.environ.get("COMMIT_EVERY", "5"))
    deadline = time.time() + run_minutes * 60
    state = load_state(engine.now_utc())
    cycle = 0
    while True:
        t0 = time.time()
        try:
            one_cycle(state)
            px = " ".join(f"{s}={(state['prices'].get(s) or {}).get('price', 0):.2f}" for s in C.SYMBOLS)
            print(f"[{engine.iso(engine.now_utc())}] {px} open={len(state['positions'])} "
                  f"closed={len(state['closed'])} equity=${engine.equity(state):.2f}", flush=True)
        except Exception as e:  # ένας κακός γύρος δεν σταματά το bot
            engine.log(state, engine.now_utc(), f"Σφάλμα γύρου: {e!r}")
            print("cycle error:", repr(e), file=sys.stderr, flush=True)
        cycle += 1
        save(state)
        if cycle % commit_every == 0:
            git_commit(f"bot: ενημέρωση {engine.iso(engine.now_utc())}")
        if time.time() + C.POLL_SECONDS > deadline:
            break
        time.sleep(max(1, C.POLL_SECONDS - (time.time() - t0)))
    save(state)
    git_commit(f"bot: τέλος γύρου {engine.iso(engine.now_utc())}")


if __name__ == "__main__":
    main()
