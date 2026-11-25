# Constant-pH performance comparison

## Background

The performance overhead of charge-interpolation dynamics must be measured under matched conditions. Four supplied systems span tripeptides, Cardiotoxin V, HEWL and GLIC.

The inputs include the four benchmark systems, run templates, force fields and calibration parameters.

## Task

Plan and execute paired normal-MD and constant-pH MD measurements for the four supplied systems, quantify performance overhead, and fit its dependence on the number of titratable sites. Choose the software setup and job organization within the cluster requirements below, while preserving the supplied scientific model and calculation requirements.

## Requirements

- See `/app/AGENTS.md` and use SSH alias `hpc` to inspect the configured cluster and execute all prescribed production simulations in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Prepare the GROMACS CpHMD fork required by the supplied lambda-dynamics model and verify startup before production. A startup check does not replace the required production sampling.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Run all four systems in normal-MD and CpHMD modes for 10 ns each (eight production runs), at pH 7 for CpHMD, without re-equilibrating the supplied systems.
- Keep hardware, resources and paired settings comparable except for required CpHMD machinery. Record CPU/GPU, core allocation and effective parameters.
- Derive timing and ns/day from completed native runs, treating preparation/nonproduction work consistently. Define relative performance and overhead consistently; require overhead ≤50% for the three smaller systems and ≤60% for GLIC.
- Fit against 1, 4, 10 and 185 titratable sites; report slope, intercept and R² with absolute slope<0.002 and R²>0.5.
- Preserve inputs, commands, complete native outputs, analysis windows and available scheduler receipts, including failed/stopped attempts. All linked artifacts must resolve within `/app/final/` and support independent numerical verification.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Simulation systems, force fields and run parameters. |
| `/app/inputs/output-contract.md` | Required outputs and submission format. |
| `/app/final/` | Submitted results and required execution evidence. |
