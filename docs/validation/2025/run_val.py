"""Run pre (T0=end=2024-12-31) and post (2024-12-31 -> 2025-12-31) reviews. Usage: run_val.py in.json out.json"""
import json, os, re, sys, traceback
os.environ["RISKPROBE_DISABLE_LLM"]="1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from concurrent.futures import ThreadPoolExecutor
from riskprobe import lifecycle
from riskprobe.http import Http
from riskprobe.report import WARN_CODES
http=Http()
items=json.load(open(sys.argv[1]))
def one(it):
    q=it["query"]; r={**it}
    for tag,(t0,end) in {"pre":("2024-12-31","2024-12-31"),"post":("2024-12-31","2025-12-31")}.items():
        try:
            res=lifecycle.run(q,t0,end,http,{},rate_bp=100,ebitda_pct=-20)
            r[tag]=dict(verdict=res.verdict,score=round(res.score,2),reasons=res.reasons[:6],
                warn=sorted({u.code for u in res.unknowns if u.code in WARN_CODES}),
                rows=[dict(id=x.id,st=x.statement[:40],t0=x.at_t0,fw=x.first_warning,now=x.now,type=x.failure_type,score=round(x.score,2)) for x in res.rows],
                first_event=res.first_event, name=res.name,
                events=[(e.date,", ".join(e.labels),e.severity) for e in res.events if e.severity in("high","medium")][:12])
        except Exception as ex:
            r[tag]=dict(verdict="오류",error=traceback.format_exc()[-400:])
    print(q, r.get("pre",{}).get("verdict"), r.get("post",{}).get("verdict"), flush=True)
    return r
with ThreadPoolExecutor(4) as ex: out=list(ex.map(one,items))
json.dump(out,open(sys.argv[2],"w"),ensure_ascii=False,indent=1)
