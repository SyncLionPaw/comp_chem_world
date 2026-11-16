# Task: Recompute Binding Free Energy and Choose a Stop/Go Decision

## Background

The package contains the complete 353,353-row archived G4 COLVAR record and provenance. `environment/assets/thermodynamic-method.md` defines the baseline FES, funnel standard-state integral, block weighting and uncertainty quantities.

## Task

Recompute the baseline binding free energy, then perform at least one predeclared burn-in, bin-count or time-window sensitivity. Use the result and sampling evidence to state the precision the record supports and whether to stop or continue.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Follow the method asset: use the native units, wall and z filters, 300 K reweighting, 72-bin baseline, funnel geometry and empty-bin rule. Report the five equal-elapsed-time block estimates, weighted block SD and formal SE separately from frame ESS. Explain the time-correlation and single-replica limits; This archived record is one simulation record, not an independent replica; matching an external numerical value does not establish convergence.

A bin-count sensitivity may use at most 144 bins. If a required unbound bin is truly empty, report that sensitivity unsupported with a reason; do not fabricate a finite result. Do not claim full reproduction of the published Table 1.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |
| `/app/environment/assets/thermodynamic-method.md` | Thermodynamic analysis method |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/FES.csv` | Free-energy surface |
| `/app/blocks.csv` | Block estimates |
| `/app/thermodynamics.json` | Thermodynamic estimates |
| `/app/sensitivity.csv` | Sensitivity analysis |
| `/app/sampling-decision.json` | Sampling decision |
| `/app/audit-report.md` | Audit report |
| `/app/provenance.json` | Data provenance |
