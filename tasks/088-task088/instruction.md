# Task: Compute the bulk SPC/E water response from a fresh MD production run

## Background

The public inputs are `/app/public/protocol.json` and `/app/public/output-contract.json`. The scientific target is a fresh 20 ns NVT production trajectory of 9033 SPC/E waters following the published equilibration protocol, and the longitudinal dielectric response over roughly 0–6 Å⁻¹ derived from it, with five observables and their statistical uncertainties.

## Task

Implement the prescribed GROMACS workflow, prepare the compute environment, submit the remote job, collect the native outputs, and analyze the trajectory. Document the choices the supplied documentation leaves open. A pre-existing trajectory or private source result cannot replace the required fresh production, and a successful scheduler exit does not by itself validate the science.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

If using HPC, see `/app/AGENTS.md`: use SSH alias `hpc`, keep remote work under a unique `~/submit-jobs/<task>-<utc>-<rand>/` directory, and validate the scientific result.

- Follow the host-provided execution profile and use its supported software environment.
- Document constraint, PME, and neighbor-list settings; system construction and equilibration checks; output frequency; the reciprocal-space estimator; and the uncertainty method. Stream the trajectory rather than allocating a frame-by-atom-by-wavevector array. Discuss finite-size resolution and estimator aliasing, whether the low-k minimum is statistically resolved, and the baseline used for `delta_k`. Report static dielectric fluctuations separately from the finite-k estimates. Record measured software versions and resources, not estimates.
- Preserve the equilibration evidence you generate: the solvated starting structure and runtime topology, and the EM/NVT/NPT TPR/log/GRO files plus the EM energy. These establish that the production continued from your own equilibration.
- Provide machine-readable execution evidence under `final/` (for example, `final/provenance.json`). Bind the scheduler/accounting record, job and allocation, resources, timezone-qualified start/end times, the submitted batch or workflow source, stdout/stderr, stage order (EM → NVT → NPT → production), and each native artifact to its relative path and content checksum. Include the actual evidence files; a status-only summary is insufficient. Follow the host execution profile; no particular scheduler command, remote directory layout, or receipt schema is prescribed.

### Input and deliverable details

- Inputs: `/app/public/protocol.json`, `/app/public/output-contract.json`, `/app/public/runtime-instructions.md`
- Outputs under `final/`: everything required by `/app/public/output-contract.json`, plus the machine-readable execution evidence and referenced files
- Native artifacts at `/app/`: `production.tpr/xtc/edr/log`, `em.tpr/log/gro/edr`, `nvt.tpr/log/gro`, `npt.tpr/log/gro`, `solvated.gro`, `topol.runtime.top`, and the workflow script you executed

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/public/protocol.json` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/public/output-contract.json` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
| `/app/production.tpr` | Required result; use the contents and format specified above. |
| `/app/production.xtc` | Required result; use the contents and format specified above. |
| `/app/production.edr` | Required result; use the contents and format specified above. |
| `/app/production.log` | Required result; use the contents and format specified above. |
| `/app/npt.gro` | Required result; use the contents and format specified above. |
| `/app/nvt.log` | Required result; use the contents and format specified above. |
| `/app/npt.log` | Required result; use the contents and format specified above. |
| `/app/nvt.tpr` | Required result; use the contents and format specified above. |
| `/app/nvt.edr` | Required result; use the contents and format specified above. |
| `/app/nvt.gro` | Required result; use the contents and format specified above. |
| `/app/nvt.cpt` | Required result; use the contents and format specified above. |
| `/app/npt.tpr` | Required result; use the contents and format specified above. |
| `/app/production.mdp` | Required result; use the contents and format specified above. |
| `/app/nvt.mdp` | Required result; use the contents and format specified above. |
| `/app/npt.mdp` | Required result; use the contents and format specified above. |
| `/app/em.mdp` | Required result; use the contents and format specified above. |
| `/app/em.tpr` | Required result; use the contents and format specified above. |
| `/app/em.log` | Required result; use the contents and format specified above. |
| `/app/em.gro` | Required result; use the contents and format specified above. |
| `/app/em.edr` | Required result; use the contents and format specified above. |
| `/app/solvated.gro` | Required result; use the contents and format specified above. |
| `/app/topol.runtime.top` | Required result; use the contents and format specified above. |
| `/app/run_case01.sh` | Required result; use the contents and format specified above. |
