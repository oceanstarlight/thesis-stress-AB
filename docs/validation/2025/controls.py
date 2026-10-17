import json, os, re, time, requests
H={"User-Agent":os.environ["SEC_USER_AGENT"]}
def get(url):
    for i in range(4):
        try:
            r=requests.get(url,headers=H,timeout=60); time.sleep(0.15)
            if r.status_code==200: return r
        except Exception: pass
        time.sleep(2*(i+1))
    raise RuntimeError(url)
ev=[e for e in json.load(open("events_us.json")) if not e["prior103"]]
tick={str(v["cik_str"]).zfill(10):v["ticker"] for v in get("https://www.sec.gov/files/company_tickers.json").json().values()}
evciks={e["cik"].zfill(10) for e in json.load(open("events_us.json"))}
sic_ciks={}
def by_sic(sic):
    if sic in sic_ciks: return sic_ciks[sic]
    out=set(); start=0
    while start<4000:
        t=get(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=&dateb=&owner=include&count=100&start={start}&output=atom").text
        c=re.findall(r"<cik>(\d+)</cik>",t)
        if not c: break
        out|=set(c); start+=100
    sic_ciks[sic]=sorted(out); return sic_ciks[sic]
def ok(cik):
    d=get(f"https://data.sec.gov/submissions/CIK{cik}.json").json(); r=d["filings"]["recent"]
    rows=list(zip(r["form"],r["filingDate"],r.get("items",[""]*len(r["form"]))))
    b103=any(f[0].startswith("8-K") and "1.03" in (f[2] or "") and "2024-01-01"<=f[1]<="2025-12-31" for f in rows)
    per=any(f[0] in("10-K","10-Q") and f[1]<="2024-12-31" for f in rows)
    return (not b103) and per, d.get("name")
used=set(); res=[]
for e in ev:
    cands=[c for c in by_sic(e["sic"]) if c in tick and c not in evciks and c not in used]
    above=sorted([c for c in cands if int(c)>int(e["cik"])])+sorted([c for c in cands if int(c)<int(e["cik"])],reverse=True)
    pick=None
    for c in above[:15]:
        good,name=ok(c)
        if good: pick=(c,tick[c],name); break
    if pick: used.add(pick[0])
    res.append(dict(event_cik=e["cik"],event=e["name"],sic=e["sic"],control=pick))
    print(e["name"][:30],e["sic"],"->",pick,flush=True)
json.dump(res,open("controls_us.json","w"),indent=1)
