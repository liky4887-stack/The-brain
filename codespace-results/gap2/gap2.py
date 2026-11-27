import sys, time, json
sys.path.insert(0,"/tmp/wm/benchmarks"); sys.path.insert(0,"/tmp/wm/packages/brain-core")
import coupled_cg_scaling as S
from brain_core.rolling.coupled import build_coupled_mip, validate_coupled_plan
from brain_core.solvers.highs_mip import solve_mip
ps,hs,cap=S.build_cluster(2); caps,_=S.binding_caps(ps,hs,cap); fs=[p.factory for p in ps]
mip,meta=build_coupled_mip(fs,hs,S.DAYS,cap,caps,{})
t0=time.time(); res=solve_mip(mip,time_limit_s=float(sys.argv[1]),mip_rel_gap=1e-4)
print("monolith",res["status"],"obj",res["objective"],"gap",res.get("gap"),"nodes",res.get("node_count"),round(time.time()-t0,1),flush=True)
from brain_core.rolling.coupled_dw import column_generation, integer_master
dw=column_generation(fs,hs,S.DAYS,cap,supplier_cap=caps,max_iter=60,time_limit_s=30.0)
print("CG LB",dw.lower_bound,"conv",dw.converged,"iters",dw.iterations,"UB before IM",dw.upper_bound,"ub_series",dw.ub_series[:5])
dw=integer_master(dw,fs,hs,S.DAYS,time_limit_s=60.0)
print("UB after IM",dw.upper_bound,"cols",dw.columns_per_plant,[p for p in dw.problems if 'integer' in p.lower() or 'master' in p.lower()][-3:])
for kw in ({"alloc_every":5},{"alloc_every":1},{"im_every":5}):
    t0=time.time()
    d=column_generation(fs,hs,S.DAYS,cap,supplier_cap=caps,max_iter=60,time_limit_s=30.0,**kw)
    print(kw,"converged",d.converged,"it",d.iterations,"LB",d.lower_bound,"UB(before final IM)",d.upper_bound,"first_ub_s",d.first_ub_s,round(time.time()-t0,1),flush=True)
    d=integer_master(d,fs,hs,S.DAYS,time_limit_s=30.0); print("   after final IM UB",d.upper_bound,flush=True)
