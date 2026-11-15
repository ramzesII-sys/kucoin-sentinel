# sentinel.py v4 - per-run files in data/, alert on persistent funding extremes
import csv, glob, json, os, time
import urllib.request

FUT = ["XBTCUSDT", "ETHUSDTM", "SOLUSDTM", "XRPUSDTM", "ADAUSDTM", "DOGEUSDTM",
       "UNIUSDTM", "JCTUSDTM", "LUNAUSDTM", "LISTAUSDTM", "UBUSDTM", "UAIUSDTM",
       "CTCUSDTM", "SHIBUSDTM"]
TH = float(os.environ.get("SENT_TH", "0.0005"))
NEED = int(os.environ.get("SENT_NEED", "3"))
FBASE = "https://api-futures.kucoin.com"
SBASE = "https://api.kucoin.com"
OUTDIR = "data"
HDR = ["ts", "symbol", "funding", "predicted", "timePoint",
       "perpLast", "spreadPct", "spotLast", "basisPct"]

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

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    now = int(time.time())
    d = get(FBASE + "/api/v1/allTickers")
    tickers = d.get("tickers") if isinstance(d, dict) else d
    fmap = {}
    for t in tickers or []:
        bid = fnum(t, "bestBidPrice"); ask = fnum(t, "bestAskPrice")
        sp = 100.0 * (ask - bid) / ((ask + bid) / 2.0) if bid and ask and bid > 0 else None
        fmap[t.get("symbol")] = (fnum(t, "price", "lastTradePrice"), sp)
    d = get(SBASE + "/api/v1/market/allTickers")
    st = {}
    for t in (d.get("ticker") if isinstance(d, dict) else None) or []:
        st[t.get("symbol")] = fnum(t, "last")
    rows = []
    for s in FUT:
        fd = get(FBASE + "/api/v1/funding-rate/" + s + "/current")
        fr = fnum(fd, "value", "fundingRate")
        pr = fnum(fd, "predictedValue", "nextFundingRate")
        tp = fnum(fd, "timePoint")
        if fr is None and pr is None:
            print("DEBUG %s funding raw=%s" % (s, str(fd)[:200]))
        if tp is None:
            tp = float(now // 28800)
        last, sp = fmap.get(s, (None, None))
        spot = st.get(s[:-1].replace("USDT", "-USDT"))
        basis = 100.0 * (last - spot) / spot if last and spot else None
        rows.append([now, s, fr, pr, int(tp), last, sp, spot, basis])
        print("%s funding=%s pred=%s spread=%s basis=%s" % (s, fr, pr, sp, basis), flush=True)
    fn = os.path.join(OUTDIR, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".csv")
    with open(fn, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        for r in rows:
            w.writerow(["" if x is None else x for x in r])
    print("wrote " + fn)

    series = {}
    files = sorted(glob.glob(os.path.join(OUTDIR, "*.csv")))[-60:]
    for fp in files:
        with open(fp, newline="") as f:
            rd = csv.reader(f)
            next(rd, None)
            for r in rd:
                if len(r) < 5:
                    continue
                v = r[3] or r[2]
                if v == "":
                    continue
                try:
                    series.setdefault(r[1], {})[int(float(r[4]))] = abs(float(v))
                except Exception:
                    pass
    alerts = []
    for s, m in series.items():
        tps = sorted(m)[-NEED:]
        if len(tps) == NEED and all(m[t] >= TH for t in tps):
            lastf = m[tps[-1]]
            alerts.append("%s: |funding|=%.4f%%/8h x%d epochs, APR~%.0f%%, carry: %s perp" %
                          (s, lastf * 100.0, NEED, lastf * 3 * 365 * 100.0,
                           "long" if lastf < 0 else "short"))
    if alerts:
        with open("alert.txt", "w") as f:
            f.write("CARRY CANDIDATES (KuCoin):\n" + "\n".join(alerts))
        print("ALERT:\n" + "\n".join(alerts))
    print("done files=%d symbols=%d" % (len(files), len(series)))

if __name__ == "__main__":
    main()

