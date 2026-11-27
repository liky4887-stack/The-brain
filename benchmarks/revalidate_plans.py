"""Re-validate every retained plan (monolith-results mono-plan/ and mpv2/) with the
current validator and guards. The validator uses the plan's own linking-M version
(BRAIN_LINKING_M is set per row: M is part of the instance). Run: python3 benchmarks/revalidate_plans.py
(reads /tmp/mr/codespace-results/)."""
import json, os, sys, glob
sys.path.insert(0,"/tmp/wm/benchmarks"); sys.path.insert(0,"/tmp/wm/packages/brain-core")
os.environ["CMP_SUPPLIER_FACTOR"]="0.9"; os.environ["CMP_LABOR_FACTOR"]="0.9"
import coupled_comparison as cc
from brain_core.rolling.coupled import validate_coupled_plan
from brain_core.guards.physical_bound import lateness_check
from brain_core.guards.anomaly import check_record
from brain_core.guards.pool_identity import pools_hash
from brain_core.rolling import two_level as T
R="/tmp/mr/codespace-results/"
def caps(path):
    d=json.load(open(path)); return ({tuple(json.loads(k)):v for k,v in d["sup"].items()},{int(k):v for k,v in d["lab"].items()},d["version"])
cluster={}
rows=[]
for kind,pat in (("v1caps","mono-plan/mp-v*-*.json"),("v2caps","mpv2/mp-*.json")):
    for f in sorted(glob.glob(R+pat)):
        d=json.load(open(f))
        if "plan" not in d: continue
        seed=d["seed_base"]
        if kind=="v1caps":
            cp=R+f"mono-plan/mp-caps-{seed}.json"
            if not os.path.exists(cp): cp=R+"mono-plan/mp-caps.json"
        else: cp=R+f"mpv2/caps-{seed}.json"
        sup,lab,ver=caps(cp)
        if seed not in cluster: cluster[seed]=cc.build_cluster(2,seed_base=seed)
        ps,hs,cap=cluster[seed]; fs=[p.factory for p in ps]
        q=[{(s,t,l):v for s,t,l,v in pl} for pl in d["plan"]]
        os.environ["BRAIN_LINKING_M"]=d["linking_m_version"]
        probs,k=validate_coupled_plan(fs,q,hs,cc.DAYS,cap,supplier_cap=sup,labor_cap=lab)
        lc=lateness_check(fs,hs,cc.DAYS,cap*(1-T.DEFAULT_CHG_ALLOWANCE),sup,lab,[None]*2,k["backlog_units_end"] if False else d["decomposition"]["short"])
        fnd=check_record({"status":"optimal","incumbent":d["objective"],"lateness_check":lc}) if True else []
        rows.append((os.path.relpath(f,R),seed,d["linking_m_version"],ver,pools_hash(sup,lab),len(probs),probs[:2],round(lc["lower_bound"],3),round(d["decomposition"]["short"],3),[x.rule for x in fnd]))
        print(rows[-1],flush=True)

json.dump([dict(zip(("file","seed","solve_M","caps_M","pools_hash","validator_problems","first_problems","lateness_lower_bound","plan_short","guard_findings"),r)) for r in rows], open("/tmp/revalidation.json","w"), indent=1)
