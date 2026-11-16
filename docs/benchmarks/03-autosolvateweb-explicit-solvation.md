# AutoSolvateWeb Explicit Solvation

## Overview

This benchmark is based on the study "**Chatbot-assisted quantum chemistry for explicitly solvated molecules**" by Rohit S. K. Gadde et al., published in *Chemical Science* (2025).

The study investigates chatbot-assisted quantum chemistry in explicit solvent environments. Its workflow connects molecular specification, charge fitting, force-field preparation, molecular dynamics, and solvent-cluster extraction. The central question is whether these stages can be automated while preserving chemically consistent inputs and scientifically meaningful calculations.

**Reference:** Rohit S. K. Gadde et al., *Chemical Science*, 2025. DOI: [10.1039/d4sc08677e](https://doi.org/10.1039/d4sc08677e).

## Tasks

| Task | Description |
| --- | --- |
| Task 14 | Fit RESP charges for a naphthalene radical cation from supplied geometry and ESP grids. |
| Task 15 | Construct a consistent periodic solvent model using the supplied six-site acetonitrile parameters. |
| Task 16 | Diagnose equilibration and statistical reliability in native molecular-dynamics trajectories. |
| Task 17 | Extract solvent clusters while preserving molecules and periodic-boundary geometry. |
| Task 18 | Analyse continuum and local-solvent effects for Reichardt's dye. |
| Task 19 | Validate chemical requests and charge-model choices within the workflow's supported scope. |
| Task 20 | Diagnose and recover a failed propagation without changing the underlying physical model. |

## Environment preparation and reruns

Tasks 015 and 020 use pinned Conda packages to supply the scientific tools; their instructions do not require Conda as a package manager. Both ARM64 and x86_64 archives are included in the task caches and shared stores. The dependency build step runs without network access and verifies archive hashes before installing. Keep these validated versions when repairing infrastructure failures; changing the scientific runtime requires another oracle check.

On the evaluation machine, install and start Docker, then run from the repository root:

```bash
uv run init
uv run harbor run -p tasks/015-task015 -a oracle -y
uv run harbor run -p tasks/020-task020 -a oracle -y
```

Each oracle trial must finish without an exception and produce a numeric reward of 1 before running a model. If an offline dependency is missing, check that the repository's shared stores are complete. If restored inputs were removed after initialization, run `uv run reset` and `uv run init` to restore them. Hash mismatches must be repaired from the matching original archive; do not edit a shared blob or bypass verification.

After both oracle checks pass, rerun these tasks with the model configuration below. Fill `.env` with a valid API key and sufficient balance first.

```bash
uv run harbor run -c configs/autosolvate-rerun.yaml --env-file .env -y
```

The new run uses a separate job name so that the original failed trials remain available. `RUN --network=none` applies to the dependency installation step; initial setup may still need network access for Harbor and base images.
