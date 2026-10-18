import os, json, time, requests
K=os.environ['DART_API_KEY']; A="https://opendart.fss.or.kr/api"
def get(path,**p):
    for i in range(4):
        try: return requests.get(f"{A}/{path}",params=dict(crtfc_key=K,**p),timeout=120).json()
        except Exception: time.sleep(3*(i+1))
raw=json.load(open("kr_events_raw.json"))
first={}
for x in raw:
    if x["stock_code"] not in first or x["rcept_dt"]<first[x["stock_code"]]["rcept_dt"]: first[x["stock_code"]]=x
corps=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data", "dart_corps.json")))
codes=sorted(c["stock_code"] for c in corps); bycode={c["stock_code"]:c for c in corps}
evcodes=set(first)
ev=[];ctl=[];used=set()
for sc,x in sorted(first.items(), key=lambda kv: kv[1]["rcept_dt"]):
    l=get("list.json",corp_code=x["corp_code"],bgn_de="20240101",end_de="20241231",pblntf_ty="B",page_count=100)
    prior=any("회생절차개시신청" in y["report_nm"] or "파산신청" in y["report_nm"] for y in l.get("list",[]))
    ind=get("company.json",corp_code=x["corp_code"]).get("induty_code","")
    ev.append(dict(group="event",query="KR:"+sc,name=x["corp_name"],event_date=f'{x["rcept_dt"][:4]}-{x["rcept_dt"][4:6]}-{x["rcept_dt"][6:]}',induty=ind,prior=prior))
    pick=None
    i=codes.index(sc)
    for c in codes[i+1:i+80]:
        if c in evcodes or c in used: continue
        ci=get("company.json",corp_code=bycode[c]["corp_code"]).get("induty_code","")
        if ci[:3]==ind[:3]:
            l2=get("list.json",corp_code=bycode[c]["corp_code"],bgn_de="20240101",end_de="20251231",pblntf_ty="B",page_count=100)
            if not any("회생절차" in y["report_nm"] or "파산" in y["report_nm"] for y in l2.get("list",[])):
                pick=c; break
    if pick: used.add(pick); ctl.append(dict(group="control",query="KR:"+pick,name=bycode[pick]["corp_name"],pair=x["corp_name"],induty=ind))
    print(x["corp_name"],ind,"prior" if prior else "", "->", pick and bycode[pick]["corp_name"], flush=True)
json.dump([e for e in ev if not e["prior"]],open("in_kr_events.json","w"),ensure_ascii=False,indent=0)
json.dump(ctl,open("in_kr_controls.json","w"),ensure_ascii=False,indent=0)
