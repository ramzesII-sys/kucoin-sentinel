 # sentinel.py v5.1 - universe scan of all KuCoin USDTM perps, liquidity-gated carry alerts
import csv, glob, json, os, time
import urllib.request

FUT_URL = "https://api-futures.kucoin.com/api/v1/allTickers"
FUN_URL = "https://api-futures.kucoin.com/api/v1/funding-rate/%s/current"
SPOT_URL = "https://api.kucoin.com/api/v1/market/allTickers"
TH = float(os.environ.get("SENT_TH", "0.0005"))
NEED = int(os.environ.get("SENT_NEED", "3"))
SMAX = float(os.environ.get("SENT_SMAX", "0.5"))
BMAX = float(os.environ.get("SENT_BMAX", "1.5"))
PAUSE = float(os.environ.get("SENT_PAUSE", "0.13"))
OUTDIR = "data"
HDR = ["ts", "symbol", "funding", "predicted", "timePoint",
       "spreadPct", "hasSpot", "perpLast", "spotLast", "basisPct"]

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode())
            if str(j.get("code")) in ("200", "200000"):
                return j.get("data")
        except Exception:
            pass
        time.sleep(1 + a)
    return None

def fnum(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        try:
            return float(d[k])
        except Exception:
            pass
    return None

def spot_pair(sym):
    s = sym[:-1]
    if s.startswith("XBT"):
        s = "BTC" + s[3:]
    return s.replace("USDT", "-USDT")

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    now = int(time.time())
    d = get(FUT_URL)
    tickers = (d.get("tickers") if isinstance(d, dict) else d) or []
    fmap, spread = {}, {}
    for t in tickers:
        s = t.get("symbol", "")
        if not s.endswith("USDTM"):
            continue
        bid, ask = fnum(t, "bestBidPrice"), fnum(t, "bestAskPrice")
        sp = 100.0 * (ask - bid) / ((ask + bid) / 2.0) if bid and ask and bid > 0 else None
        spread[s] = sp
        fmap[s] = fnum(t, "price", "lastTradePrice")
    d = get(SPOT_URL)
    spot = {}
    for t in (d.get("ticker") if isinstance(d, dict) else None) or []:
        spot[t.get("symbol")] = fnum(t, "last")
    cand = []
    for s in sorted(fmap):
        sp = spread.get(s)
        if sp is None or sp > SMAX:
            continue
        if spot_pair(s) not in spot:
            continue
        cand.append(s)
    print("universe=%d candidates=%d (spread<=%.2f%% & spot exists)" %
          (len(fmap), len(cand), SMAX), flush=True)
    rows = []
    nfun = 0
    for s in cand:
        fd = get(FUN_URL % s)
        nfun += 1
        if nfun % 100 == 0:
            print("  funding %d/%d" % (nfun, len(cand)), flush=True)
        time.sleep(PAUSE)
        fr, pr, tp = fnum(fd, "value", "fundingRate"), \
            fnum(fd, "predictedValue", "nextFundingRate"), fnum(fd, "timePoint")
        if tp is None:
            continue
        sp = spread[s]
        last = fmap[s]
        sl = spot.get(spot_pair(s))
        basis = 100.0 * (last - sl) / sl if last and sl else None
        rows.append([now, s, fr, pr, int(tp), sp, 1, last, sl, basis])
    fn = os.path.join(OUTDIR, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".csv")
    with open(fn, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for r in rows:
            w.writerow(["" if x is None else x for x in r])
    print("wrote %s rows=%d" % (fn, len(rows)))

    series = {}
    meta = {}
    files = sorted(glob.glob(os.path.join(OUTDIR, "*.csv")))[-90:]
    for fp in files:
        try:
            with open(fp, newline="") as f:
                rd = csv.DictReader(f)
                for r in rd:
                    s = r.get("symbol")
                    v = (r.get("predicted") or "") or (r.get("funding") or "")
                    if not s or v == "":
                        continue
                    try:
                        tp = int(float(r["timePoint"]))
                        series.setdefault(s, {})[tp] = float(v)
                        sp = r.get("spreadPct")
                        ok = float(sp) <= SMAX if sp not in (None, "") else False
                        bas = r.get("basisPct")
                        bok = abs(float(bas)) <= BMAX if bas not in (None, "") else False
                        meta.setdefault(s, {})[tp] = (ok, str(r.get("hasSpot", "1")) != "0", bok)
                    except Exception:
                        pass
        except Exception:
            pass
    alerts = []
    for s, m in series.items():
        tps = sorted(m)[-NEED:]
        if len(tps) < NEED:
            continue
        if not all(abs(m[t]) >= TH for t in tps):
            continue
        if not all(meta.get(s, {}).get(t, (False, False, False))[0] and
                   meta.get(s, {}).get(t, (False, False, False))[1] and
                   meta.get(s, {}).get(t, (False, False, False))[2] for t in tps):
            continue
        hrs = (tps[-1] - tps[0]) / (NEED - 1) / 3600000.0
        if hrs <= 0:
            continue
        perday = 24.0 / hrs
        apr = m[tps[-1]] * perday * 365.0 * 100.0
        sp = spread.get(s)
        ba = None
        if sp is not None:
            last = fmap.get(s); sl = spot.get(spot_pair(s))
            ba = 100.0 * (last - sl) / sl if last and sl else None
        carry = "long perp / short spot" if m[tps[-1]] < 0 else "short perp / long spot"
        alerts.append("%s: funding=%.4f%% x%d ep (%.0fh each), APR~%+.0f%%, spread=%.3f%%, basis=%s, carry: %s" %
                      (s, m[tps[-1]] * 100.0, NEED, hrs, apr, sp if sp is not None else -1,
                       ("%+.3f%%" % ba) if ba is not None else "?", carry))
    if alerts:
        with open("alert.txt", "w") as f:
            f.write("CARRY CANDIDATES (KuCoin, liquidity-gated):\n" + "\n".join(alerts))
        print("ALERT:\n" + "\n".join(alerts))
    else:
        print("no candidates")
    print("done files=%d symbols=%d" % (len(files), len(series)))

if __name__ == "__main__":
    main()
