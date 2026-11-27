"""Each plant of a calib instance solved ALONE (pools effectively
unlimited, same weights and min-lot as the n-plant benchmark: weights
and median demand come from the whole n-plant instance). Per-plant rows:
status, gap, objective, late/backlog/early/setups from the independent
validator. Where does lateness live? env: MS_CLASS (calib3), MS_N (4),
MS_SEED, PA_LIMIT_S (40), PA_GAP (1e-4), BRAIN_LINKING_M (v1|v2),
PA_OUT. One thread; run alone or state the concurrency.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import monolith_scaling as ms  # noqa: E402
from brain_core.rolling.coupled import (build_coupled_mip,  # noqa: E402
                                        validate_coupled_plan)
from brain_core.rolling.two_level import (EARLY_W,  # noqa: E402
                                          ObjectiveWeights,
                                          linking_m_version)
from brain_core.synthetic import FnbParams, generate_fnb_factory  # noqa: E402
from coupled_comparison import qty_from_mip_x  # noqa: E402



import numpy as np, scipy.sparse as sp
from scipy.optimize import linprog

def lp_bound(mip):
    A = mip.A.tocsr(); rows_ub=[];b=[];eq=[];be=[]
    for i,s in enumerate(mip.sense):
        r=A[i]
        if s=="L": rows_ub.append(r); b.append(mip.rhs[i])
        elif s=="G": rows_ub.append(-r); b.append(-mip.rhs[i])
        else: eq.append(r); be.append(mip.rhs[i])
    res=linprog(mip.c,A_ub=sp.vstack(rows_ub),b_ub=b,A_eq=sp.vstack(eq) if eq else None,b_eq=be if eq else None,
      bounds=[(l,None if np.isinf(u) else u) for l,u in zip(mip.lb,mip.ub)],method="highs")
    return res.fun, res.status

def main():
    cls="calib3"; n=4; c=dict(ms.CLASSES[cls])
    ps=[generate_fnb_factory(FnbParams(seed=101*(i+1)+ms.SEED_OFF,n_lines=3,n_skus=c["n_skus"],days=c["days"],active_fraction=0.9,utilization=c["util"],n_raw_materials=6,families=("DAIRY","BAKERY"))) for i in range(n)]
    hs,cap,days=ps[0].params.horizon_start,ps[0].day_capacity_minutes,c["days"]
    fs=[p.factory for p in ps]; dd=ms.sku_daily_demand(fs,hs,days); d_med=statistics.median(dd.values())
    w=ObjectiveWeights(setup=c["tbo"]**2*EARLY_W*d_med/2.0)
    i=3; f=fs[i]
    mip,meta=build_coupled_mip([f],hs,days,cap,{},{},weights=w)
    if c.get("minlot_days"):
        def lot_fn(p_i,sk,M,i=i): return min(0.9*M,c["minlot_days"]*dd.get((i,sk),d_med))
        mip,_=ms.add_min_lot(mip,meta,None,lot_fn)
    t=time.perf_counter(); v,st=lp_bound(mip)
    print(json.dumps({"seed":ms.SEED_OFF,"plant":i,"linking_m_version":linking_m_version(),"lp_bound":v,"lp_status":st,"rows":mip.A.shape[0],"cols":mip.A.shape[1],"lp_s":round(time.perf_counter()-t,1),"sha":ms._sha()}),flush=True)
main()
