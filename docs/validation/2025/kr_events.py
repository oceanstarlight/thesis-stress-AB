import os, requests, json, time
from concurrent.futures import ThreadPoolExecutor
K=os.environ['DART_API_KEY']; A="https://opendart.fss.or.kr/api/list.json"
def q(rng):
    b,e=rng; out=[]; page=1
    while True:
        for _ in range(3):
            try:
                d=requests.get(A,params=dict(crtfc_key=K,bgn_de=b,end_de=e,pblntf_ty="B",page_no=page,page_count=100),timeout=120).json(); break
            except Exception as ex: time.sleep(3)
        if d.get("status")!="000": break
        out+=[x for x in d["list"] if any(k in x["report_nm"].replace(" ","") for k in ("회생절차개시신청","파산신청")) and x["corp_cls"] in ("Y","K")]
        if page>=d["total_page"]: break
        page+=1
    return rng,out
rngs=[("20250101","20250331"),("20250401","20250630"),("20250701","20250930"),("20251001","20251231")]
with ThreadPoolExecutor(4) as ex: res=list(ex.map(q,rngs))
allx=[x for _,o in res for x in o]
json.dump(allx,open("kr_events_raw.json","w"),ensure_ascii=False,indent=0)
for x in allx: print(x["rcept_dt"],x["corp_name"],x["stock_code"],x["corp_cls"],x["report_nm"])
