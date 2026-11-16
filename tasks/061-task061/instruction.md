# Conduct open-ended research on reliable first-principles semiconductor transport

## Background

First-principles scattering models can predict semiconductor transport, but conclusions depend on the system studied, approximations, numerical error, and comparable evidence.

## Task

Propose a well-scoped, evidence-testable research question about the conditions under which first-principles physical scattering models can reliably predict semiconductor transport, and answer it using auditable data. You choose the system, structure, method, comparisons, and stopping criteria; no structure, dataset or numerical target is prescribed.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include AMSET, ASE, BoltzTraP2, h5py, matplotlib, netcdf4, NetworkX, NumPy, pandas, Phonopy, pillow, pymatgen, PyYAML, SciPy, seekpath, spglib, sympy. Do not install additional packages or fetch dependencies from the network.

Perform calculations and analysis locally in the task container using its permitted local interface. Public-source retrieval remains subject to the existing access rules; do not submit remote/HPC jobs.

- Describe the research system and its sources; methods and software; inputs and execution; result units and conditions; fairness of comparisons; error and convergence; uncertainty; resource cost; and limits of the conclusions. Distinguish new runs in this task from historical data and public sources; explain failed or incomplete branches. Conclusions may be positive, negative, limited, or uncertain, but must be proportionate to the evidence.
- You may use data with a clearly public source or generate inputs and run calculations; provide source versions and reproduction information. Link reported numbers to the corresponding run or clearly identify their published source. Label estimated costs as estimates.
- The work record must be sufficient to audit execution and cost; a submitted plan alone is not execution or numerical evidence.
- Use the public-data reanalysis interface described in `/task/reanalysis-plan-format.md`, or another independently checkable local method. Analyze public data or perform calculations within the local execution profile.
- Retain completed local calculations' native outputs and execution provenance in the submitted evidence. Identify historical scheduler records as historical evidence, not as jobs executed in this attempt; status alone does not establish a completed calculation.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/task/output-contract.md` | Evidence and submission conventions for the open analysis. |
| `/task/reanalysis-plan-format.md` | Optional public-data analysis format. |
| `/task/compute-budget.yaml` | Local resource limits. |

The runtime provides `/task/output-contract.md`, optional `/task/reanalysis-plan-format.md`, and public resource limits in `/task/compute-budget.yaml`. Submit `report.md`, `evidence-index.json`, and the raw or tabular data supporting the conclusions under `/app/final/`; the index must record sources, quantitative claims, comparisons, execution, costs, and reasoning. If submitting native cluster results, also submit their source manifest.
