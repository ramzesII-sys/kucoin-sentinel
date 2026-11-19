# carry_paper.py - stateless paper ledger (правила зафиксированы 2026-11-19 до первой цифры)
import csv, glob, json, os, time

SYMBOLS = ["ARIAUSDTM"]
PERP_NOTIONAL = 50.0
FEE_ROUNDTRIP = 0.40
EXIT_DAYS = 7
EXIT_FUND_FLOOR = 0.0002
DATA = "data"
CDIR = "carry"
ENTRY_FILE = os.path.join(CDIR, "entry.json")
LEDGER = os.path.join(CDIR, "carry_ledger.csv")
DIGEST = os.path.join(CDIR, "digest.txt")

def load_epoch(sym):
    seen, basis = {}, {}
    for fp in sorted(glob.glob(os.path.join(DATA, "*.csv"))):
        try:
            with open(fp, newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("symbol") != sym:
                        continue
                    tv, fv, bv, tp = r.get("ts"), r.get("funding"), r.get("basisPct"), r.get("timePoint")
                    if fv in (None, "") or tp in (None, ""):
                        continue
                    try:
                        seen[int(float(tp))] = float(fv)
                    except Exception:
                        continue
                    if bv:
                        try:
                            basis[int(float(tp))] = float(bv)
                        except Exception:
                            pass
        except Exception:
            pass
    return seen, basis

def main():
    now = int(time.time())
    os.makedirs(CDIR, exist_ok=True)
    st = {}
    if os.path.exists(ENTRY_FILE):
        try:
            st = json.load(open(ENTRY_FILE))
        except Exception:
            st = {}
    lines, rows = [], []
    for sym in SYMBOLS:
        seen, basis = load_epoch(sym)
        if not seen:
            lines.append(sym + " no data yet")
            continue
        tps = sorted(seen)
        cur = tps[-1]
        completed = tps[:-1]
        e = st.get(sym)
        if e is None:
            e = {"entry_ts": now, "entry_tp": cur, "basis_open": basis.get(cur), "status": "OPEN"}
            st[sym] = e
        accrual = [t for t in completed if t >= e["entry_tp"]]
        fund_pct = sum(seen[t] for t in accrual)
        fund_usd = fund_pct / 100.0 * PERP_NOTIONAL
        b_now = basis.get(cur)
        b_open = e.get("basis_open")
        basis_usd = (b_open - b_now) / 100.0 * PERP_NOTIONAL if (b_open is not None and b_now is not None) else 0.0
        days_used = ((e.get("close_ts") or now) - e["entry_ts"]) / 86400.0
        net = fund_usd + basis_usd - FEE_ROUNDTRIP
        if e["status"] == "OPEN":
            tail = [seen[t] for t in (accrual + [cur])][-2:]
            if days_used >= EXIT_DAYS:
                e.update(status="CLOSED", close_ts=now, close_reason="time")
            elif len(tail) == 2 and all(abs(x) < EXIT_FUND_FLOOR for x in tail):
                e.update(status="CLOSED", close_ts=now, close_reason="funding_dead")
        lines.append("%s %s D%d ep%d fund%+.2f$ basis%+.2f$ net%+.2f$" %
                     (sym, e["status"], int(days_used), len(accrual), fund_usd, basis_usd, net))
        rows.append([time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(now)), sym, e["status"],
                     round(days_used, 2), len(accrual), round(fund_pct, 5), round(fund_usd, 4),
                     b_open, b_now, round(basis_usd, 4), round(net, 4), e.get("close_reason", "")])
    json.dump(st, open(ENTRY_FILE, "w"), indent=1)
    with open(DIGEST, "w") as f:
        f.write("CARRY PAPER ARIA ($50 spot + $50 short perp, fees $0.40 roundtrip):\n" + "\n".join(lines))
    hdr = ["ts", "symbol", "status", "days", "epochs", "fund_pct_cum", "fund_usd",
           "basis_open_pct", "basis_now_pct", "basis_usd", "net_usd", "close_reason"]
    old = []
    if os.path.exists(LEDGER):
        with open(LEDGER, newline="") as f:
            rd = csv.reader(f)
            if next(rd, None):
                old = list(rd)
    with open(LEDGER, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        for r in old + rows:
            w.writerow(r)
    print("\n".join(lines))

if __name__ == "__main__":
    main()
