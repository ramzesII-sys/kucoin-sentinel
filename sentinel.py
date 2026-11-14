# sentinel.py - ежечасный снимок KuCoin: funding + spread + basis; алерт по упорному экстремуму
import csv, json, os, time
import urllib.request

FUT = ["BTCUSDTM", "ETHUSDTM", "SOLUSDTM", "XRPUSDTM", "ADAUSDTM", "DOGEUSDTM",
       "UNIUSDTM", "JCTUSDTM", "LUNAUSDTM", "LISTAUSDTM", "UBUSDTM", "UAIUSDTM",
       "CTCUSDTM", "SHIBUSDTM"]
TH = float(os.environ.get("SENT_TH", "0.0005"))
NEED = int(os.environ.get("SENT_NEED", "3"))
FBASE = "https://api-futures.kucoin.com"
SBASE = "https://api.kucoin.com"
OUT = "snapshot.csv"
ALERT = "alert.txt"

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
        if tp is None:
            tp = float(now // 28800)
        tp = int(tp)
        last, sp = fmap.get(s, (None, None))
        spot = st.get(s[:-1].replace("USDT", "-USDT"))
        basis = 100.0 * (last - spot) / spot if last and spot else None
        rows.append([now, s, fr, pr, tp, last, sp, spot, basis])
        print("%s funding=%s pred=%s tp=%d spread=%s basis=%s" %
              (s, fr, pr, tp, sp, basis), flush=True)
    old = []
    if os.path.exists(OUT):
        with open(OUT, newline="") as f:
            rd = csv.reader(f)
            if next(rd, None):
                old = list(rd)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "symbol", "funding", "predicted", "timePoint",
                    "perpLast", "spreadPct", "spotLast", "basisPct"])
        for r in old:
            w.writerow(r)
        for r in rows:
            w.writerow(["" if x is None else x for x in r])
    series = {}
    for r in old + [[str(x) if x is not None else "" for x in row] for row in rows]:
        if len(r) < 5:
            continue
        try:
            v = r[3] or r[2]
            if v == "":
                continue
            series.setdefault(r[1], {})[int(float(r[4]))] = abs(float(v))
        except Exception:
            pass
    alerts = []
    for s, m in series.items():
        tps = sorted(m)[-NEED:]
        if len(tps) == NEED and all(m[t] >= TH for t in tps):
            apr = m[tps[-1]] * 3 * 365 * 100.0
            side = "SHORT perp / long spot" if m[tps[-1]] == m[tps[-1]] else ""
            alerts.append("%s: |funding|=%.4f%%/8h x%d эпох, APR~%.0f%%" %
                          (s, m[tps[-1]] * 100.0, NEED, apr))
    if alerts:
        with open(ALERT, "w") as f:
            f.write("CARRY CANDIDATES (KuCoin):\n" + "\n".join(alerts))
        print("ALERT:\n" + "\n".join(alerts))
    elif os.path.exists(ALERT):
        os.remove(ALERT)
    print("done rows_now=%d history=%d" % (len(rows), len(old)))

if __name__ == "__main__":
    main()
