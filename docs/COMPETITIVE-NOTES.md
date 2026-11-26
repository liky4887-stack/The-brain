# Market notes (public sources only)

Review decision (2026-11-26, outside review accepted): we publish NO
claims about named competitors - specifically none about o9 or
Makkook. Comparisons are made on matched business outcomes with
measured evidence, not vendor-vs-vendor positioning. The previous
named-vendor comparison sections were removed accordingly; the
market-sweep table below stays because it records what each vendor
publishes (attributed quotes plus whether verifiable bounds exist),
with the o9 row removed per the same decision.

Technical learnings kept from the earlier sweep (no party named):
multi-horizon production planning formulations for high-complexity
manufacturing exist commercially; audit logging, stability
guarantees, and shared-resource (furnace/line) modeling are expected
table stakes; formulation patterns for aggregate planning are
reusable and live in docs/SCALE-UPGRADE-LIST.md.

## DIOS-adjacent competitors (user's list, 2026-11-25 5:00 PM; public pages only, no sign-ups)

The user's read: scope varies, not all one-for-one with DIOS. Sweep of
public pages for what each claims on OPTIMIZATION, whether any BOUNDS
or reproducible evidence are published, and where we can honestly
differ. "No public bounds" means none found in this sweep, not proof
none exist.

| Vendor | Public optimization claim | Bounds / verifiability published | Our honest difference |
|---|---|---|---|
| Kinaxis (kinaxis.com, Maestro) | "Concurrent planning": one in-memory model, fast replans; "AI-powered orchestration" | No public bounds/gaps found | Speed-of-replan is their headline; ours is a proven LB<=UB gap on one linked model |
| RELEX (relexsolutions.com) | "AI-native" end-to-end retail/manufacturing planning, optimize inventory/production | No public bounds/gaps found | Forecast/inventory-centric; we publish solver status and validation counts |
| Blue Yonder (blueyonder.com) | "Unified platform - data, AI, network, execution" | No public bounds/gaps found | Suite breadth; we compete on verifiable plan quality, not suite |
| SAP IBP (SAP) | Documented order-based and time-series Supply Optimizer; finite-capacity optimization | No public bounds on the product pages; BUT the research lineage is public: SAP industry-partner MIP paper (J. Comput. Math., DOI 10.4208/jcm.1905-m2019-0055) describes heuristic MIP innovations needed because general solvers hit time limits at industrial scale | Closest to our world: real MIP under the hood, documented to need heuristics at scale. We state proven gaps explicitly instead of "optimizer" as a black box |
| Oracle SCP (oracle.com) | Fusion Cloud SCP with "built-in AI and agentic applications" | No public bounds/gaps found | AI-assistant framing; no measurable plan-quality claims to compare against |
| Anaplan (anaplan.com) | Connected planning; PlanIQ = ML forecasting (with Amazon Forecast) | No public bounds/gaps found | Planning-aggregation tool with ML forecasting; optimization depth is not the claim |
| ToolsGroup (toolsgroup.com) | SO99+ "calculates optimal plans" via "advanced algorithms and self-learning AI" | "Optimal" used as marketing language; no bound or proof offered | They say "optimal"; we show LB, UB, and gap per solve. Direct honesty contrast |
| Slimstock (slimstock.com, Slim4) | Inventory optimization "to balance stock and service" | No public bounds/gaps found | Inventory-parameter focus (safety stock), narrower than coupled production |
| DELMIA Quintiq (3ds.com) | "Leading supply chain planning and optimization solution" for complex end-to-end operations | No public bounds found in this sweep; heritage is the strongest OR culture of the list (puzzle/benchmark marketing historically) | The most credible optimization competitor here; our published measured ladder (26.5M vars validated) is the kind of evidence their public pages do not show |

Cross-cutting: every vendor page leads with "AI"/"optimize" language;
NONE of the ten publishes a lower bound, an optimality gap, a solver
status, or an independently validated plan size for their flagship
planning runs (this sweep). The only public evidence of real solver
craft is SAP's research lineage, which itself documents that
industrial-scale MIPs need heuristics under time limits - exactly the
gap our master-worker decomposition with a proven LB<=UB sandwich is
built to close. That is the claim we can make and they do not: a
stated, reproducible, independently checked bound on every published
plan.

## Open resources to use (user request 5:01 PM; PUBLIC / OPENLY LICENSED ONLY - the user's "leaked data" phrasing is explicitly NOT adopted: no leaked, confidential, or proprietary material, nothing behind logins, no untrusted code run)

Verified sources and licenses (checked live 2026-11-25):

1. **MIPLIB 2017** - https://miplib.zib.de/ (Zuse Institute Berlin).
   The standard MIP benchmark library, 240-instance benchmark set
   incl. industrial supply-chain/production instances. Free to
   download; cite the MIPLIB 2017 paper (Comput. Optim. Appl., DOI
   10.1007/s12532-020-00194-3). USE: the benchmark sweep - measure
   our solve quality vs published best-known on production-planning
   instances.
2. **frePPLe** - github.com/frePPLe/frepple. LICENSE CHANGE VERIFIED
   from the live COPYING file: v8+ is dual-licensed MIT / commercial
   (was AGPL). Our "reference only" rule is relaxed: patterns AND
   code reading are fine; still no vendoring without a DECISIONS.md
   entry, and their solver architecture remains the closest public
   APS reference (demand pegging, solver buffers, constraint types).
3. **SAP IBP public help portal** (help.sap.com): the order-based /
   time-series Supply Optimizer documentation is public - model
   features (fair-share, late-demand, deployment) are documented
   behavior we can map onto our constraint set. USE: feature gap
   list.
4. **Zenodo process-industries planning benchmark** - DOI
   10.5281/zenodo.17493292 "Benchmark dataset for production planning
   and detailed scheduling in process industries". License NOT yet
   verified (Zenodo API 403 from the workspace box) - VERIFY BEFORE
   USE. USE: real-company-style plan runs.
5. **EMRPS/refinery-planning-benchmark** (GitHub) - refinery planning
   benchmark; license on the repo page to verify before use. USE:
   process-industry validation instance.
6. **Mendeley FJSP-DMPBP** (DOI 10.17632/gdm7nkn6b3) - flexible job
   shop with batch processing instances; Mendeley data is usually
   CC-BY 4.0 - VERIFY BEFORE USE. USE: day-level sequencing tests.
7. **PMC5996297** - sustainable aggregate production planning,
   chemical process industry benchmark problem + dataset (open access
   paper). USE: formulation patterns for aggregate planning.
8. Small open APS repos (patterns only, NEVER run untrusted code):
   hhatefi/sc_planner, lijianhua1205/OpenAPO, ZisIsNotZis/aps - review
   for constraint/modeling ideas only.
9. Kinaxis / RELEX / Blue Yonder / Anaplan / ToolsGroup /
   Slimstock / Oracle: no open solver resources found in this sweep -
   engines are closed; only marketing pages and (SAP excepted) no
   public technical detail. Nothing usable; do not sign up.

Gap-list additions from this sweep:
- Benchmark sweep vs MIPLIB 2017 planning instances (published
  best-known objectives = free verifiable targets).
- CLSP/Trigeiro classic lot-sizing instances vs published optima
  (already queued).
- frePPLe feature-mapping pass (now MIT): demand pegging, buffer
  model, fence/policy constraints - adopt what's missing, cite.
- Real-company-style runs on the Zenodo process-industries dataset
  (after license verification).
- SAP IBP optimizer feature parity list (fair-share distribution,
  late demand, deployment) as roadmap candidates.
