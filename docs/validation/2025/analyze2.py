import json, re, statistics
from collections import Counter
from datetime import date
FLAG=("재검토 필요","주의")
def stats(rows):
    c=Counter(r["pre"]["verdict"] for r in rows)
    ev=[r for r in rows if r["pre"]["verdict"] in ("재검토 필요","주의","유지")]
    return c, sum(1 for r in ev if r["pre"]["verdict"] in FLAG), sum(1 for r in ev if r["pre"]["verdict"]=="재검토 필요"), len(ev)
def why(r):
    rs=" ".join(r["pre"].get("reasons",[]))
    if r["pre"]["verdict"]!="재검토 필요": return r["pre"]["verdict"]
    return "재검토(EBITDA≤0)" if "EBITDA ≤ 0" in rs else "재검토(공시 강제)" if "강제 규칙" in rs else "재검토(점수)"
for ver in ("v0","v1"):
    print(f"########## {ver}")
    E=json.load(open(f"{ver}_us_events.json")); C=json.load(open(f"{ver}_us_controls.json")); K=json.load(open(f"{ver}_kr.json"))
    for name,rows in [("US 사건",E),("US 대조",C),("KR 사건",[r for r in K if r["group"]=="event"]),("KR 대조",[r for r in K if r["group"]=="control"])]:
        c,f,rv,n=stats(rows)
        print(f"{name:6} n={len(rows):2} 판정가능 {n:2} | 경고 {f}/{n} ({f/max(n,1):.0%}) 재검토만 {rv}/{n} ({rv/max(n,1):.0%}) | {dict(c)}")
        print("        사유:",dict(Counter(why(r) for r in rows)))
# lead time and post detection (v1, US+KR events)
print("########## 사후: 사건 전 최초 재무 경고 (v1)")
rows=json.load(open("v1_us_events.json"))+[r for r in json.load(open("v1_kr.json")) if r["group"]=="event"]
leads=[]; post_new=0; miss=[]
for r in rows:
    ed=r["event_date"]; pre=r["pre"]["verdict"]
    if pre in FLAG: leads.append((date.fromisoformat(ed)-date(2024,12,31)).days); continue
    fws=[re.match(r"\d{4}-\d{2}-\d{2}",x["fw"] or "") for x in r["post"].get("rows",[])]
    fws=sorted(m.group(0) for m in fws if m and m.group(0)<ed)
    if fws: post_new+=1; leads.append((date.fromisoformat(ed)-date.fromisoformat(fws[0])).days)
    else: miss.append((r["name"][:28],pre,ed))
print("사건 전 경고 있음:",len(leads),"/",len(rows)," 선행일 중앙값",statistics.median(leads),"최소",min(leads),"최대",max(leads))
print("기준일엔 경고 없었지만 이후 정기공시로 사건 전 경고:",post_new)
print("끝까지 사건 전 경고 없음:",len(miss)); [print("   ",m) for m in miss]
