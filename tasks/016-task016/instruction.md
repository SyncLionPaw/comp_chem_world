# Diagnose equilibration and statistical reliability in native molecular-dynamics trajectories

## Background
Two native MD trajectories, metadata and three diagnostic control series are supplied. Controls test analysis, not molecular equilibrium.

## Task
Audit observables/time metadata, assess sampling and recommend further work within the evidence limits.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

From topology masses and orthorhombic cells calculate frame volume/density. Report native times in ps, short-NPT temperature mean/sample SD (ddof=1), and signed density change (last−first)/first in native order. For nonconstant series use normalized autocorrelation with lag covariance denominator N−k and variance denominator N; sum (1−k/N)ρk until just before first nonpositive lag; g=1+2Σ(1−k/N)ρk, clamped [1,N], and Neff=N/g. Constant series: g=null, Neff=1, not molecular independence. Apply controls/index.json policy: ≥50 observations, ≥10 effective, four-consecutive-block mean range/sample SD≤0.5; block statistic undefined for <4 points or zero variance. Convert times to ps, check available native references, report all reasons, and distinguish operational screen from equilibrium. Assess ten independent clusters from numerical values, not names/order. Read native/provenance inputs; submit audit.json, analysis.md and runnable analysis.py. Public output-contract defines fields, aliases, units and reasons; CLI recomputes in a clean directory.

The numerical comparison tolerance is 1e−6. Use 1e−12 for the constant-data check.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Trajectories, topology, metadata and controls. |
| `/app/output-contract.yaml` | Output format and evidence requirements. |

/app/inputs/: trajectories/topology/metadata/controls; /app/output-contract.yaml: output schema; /app/final/: audit deliverables.
