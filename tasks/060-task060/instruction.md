# Diagnose silicon transport convergence

## Background

Scattering-rate predictions depend on interpolation grids, the Fermi–Dirac truncation window (`fd_tol`), scattering mechanisms, and carrier concentration. This task measures those effects for silicon within a fixed compute budget.

## Task

Using the supplied native Si inputs, calculate ADP, IMP, and total transport at 300 K for six concentrations. Compare fitting/grid and energy-window settings, then state and test a falsifiable follow-up prediction. Use `/app/environment/case06_rpc.py`; the complete procedure and output contract are in `/app/environment/assets/public/output-contract.md`.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include AMSET, ASE, BoltzTraP2, h5py, matplotlib, netcdf4, NetworkX, NumPy, pandas, Phonopy, pillow, pymatgen, PyYAML, SciPy, seekpath, spglib, sympy. Do not install additional packages or fetch dependencies from the network.

- Run three progressively larger baseline interpolation factors, then compare baseline three with a run changing only `fd_tol`. The first and third factors must differ by at least 2×, and the actual energy-window cutoffs must confirm expansion.
- Compare `overall`, ADP, and IMP × six concentrations × `xx/yy/zz` (54 identities) using `abs(old-new)/abs(new)` and a strict 2% threshold. Zero or non-finite denominators are pending numerical comparisons; non-positive or non-finite native mobility evidence is invalid. Evaluate each axis using its latest valid adjacent comparison. A coupled fitting/grid change does not establish pure integration-grid error, and total transport cannot hide mechanism changes.
- Seal a falsifiable follow-up prediction for the trusted `global_maximum_108` component before its run, regardless of whether it exceeds 2%. Preserve the returned axis and component identity; ties follow the returned `tie_rule` and `tie_count`. A fitting/grid follow-up increases the factor by at least 1.5× and every actual grid dimension; a window follow-up keeps factor and grid fixed and reduces `fd_tol`.
- Register the interpretation rule for the independent control through the `private-control` action before its configuration is disclosed. Compare it with `window-match-3` when available, otherwise with `followup-5`, using the same parent for transport and energy cutoffs.
- Preserve every attempt's native HDF, actual settings, logs, run identity, and independent transport reconstruction. Summaries alone do not prove execution. Conclusions apply only to tested settings and budget; do not claim asymptotic convergence or absolute accuracy.

The complete task session is limited to 1800 seconds. Within it, each native run is limited to 180 seconds, each trusted rebuild to 300 seconds, and each supervised process tree to 12 GiB peak RSS. A sealed follow-up budget can only reduce the native `followup-5` limits. Report incomplete work honestly.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/inputs/` | Native silicon transport inputs. |

Inputs:

```text
/app/environment/assets/inputs/
```

RPC interface and public output contract:

```text
/app/environment/case06_rpc.py
/app/environment/assets/public/output-contract.md
```

Submit these three scientific reports:

```text
/app/final/
├── report.json
├── private-control-response.json
└── report.md
```

Execution evidence is preserved automatically by the environment; no manual copying is needed. Before calling terminal `finalize`, make sure the report and response objects match the files you will submit.
