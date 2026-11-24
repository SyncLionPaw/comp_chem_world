# Task: Compare eight same-composition relaxation candidates

## Background

The supplied package contains eight Li41Ti40O96 starting structures, common spin-polarized relaxation inputs, an output schema and evidence routes for an authorized archive replay or separately authorized HPC calculation. Archived settings are observations and do not establish the requested optimizer.

## Task

Compare the candidates using native final-relaxation evidence: energy, physical forces, structure, convergence and all pairwise differences. State what this finite same-composition set supports and the limits of that comparison.

## Requirements

For fresh calculations, use `hpc` to probe authorized resources. Choose MPI ranks, memory, wall time, and concurrency within the task budget. Submit, wait for a terminal state, collect native outputs, and validate the scientific results.

Preserve each starting structure and use the common method. A fresh calculation is a spin-polarized variable-cell relaxation with `IBRION=1`, `NPAR=2` and standard PAW_PBE Li 17Jan2003, Ti 08Apr2002 and O 08Apr2002, subject to the authorized host resources and sealed PAW policy. Do not combine candidates or start one from another’s relaxed structure. Report archived observed settings separately from the requested fresh method. Keep the selected PAW policy and host-sealed source/run observations in `method.paw_policy` and `method.paw_identity`; do not publish POTCAR contents. The alternate `hpc_standard_native_v1` source is host-qualified but is not asserted byte-identical or numerically equivalent to the archived source.

For every candidate, analyze the final ionic step, `TOTEN`, `energy(sigma->0)`, physical forces, final structure and electronic/structural termination evidence. Require normal termination, electronic convergence, structural stopping evidence and maximum force ≤0.02 eV/Å. Report all 28 signed pairwise energy differences under both energy conventions and compare structures using the species-preserving periodic metric in `/app/assets/output-schema.json`. Discuss rankings, energy-convention sensitivity and uncertainty not quantified by these records. Limit conclusions to these eight candidates; do not infer cross-stoichiometry stability or a global ground state.

Read `/app/hpc-attempt.json` before any run. Submit HPC work only when host execution is available and authorized; do not bypass disabled submission, transfer or shell access. Use supported existing records and report missing evidence rather than inventing it. Preserve native records and provenance. Write `/app/final/results.json` according to `/app/assets/output-schema.json`.

Read the authorized aliases, job name `attempt_id`, and `workdir_template` from `/app/hpc-attempt.json`. Probe and choose a host and partition with `hpc`, then use that job name and directory for submission. Write the chosen SSH alias alone to `/app/final/hpc-host.txt` for native evidence collection. Run the Slurm commands from a writable working directory and link `/app/submit-job.json` there as `submit-job.json`.

For a fresh run, stage `accepted-plan.json` in the job directory with `ntasks`, `memory_gib`, `walltime_seconds`, `concurrent_runs`, `ranks_per_run`, `vasp_path`, and `mpi_path`. Include `# CCB_ACCEPTED_PLAN_SHA256=<digest>` on its own line in the submitted batch script. Hash the plan as UTF-8 JSON with sorted keys, compact separators, and no final newline.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Candidate structures, calculation settings and output schema. |
| `/app/assets/output-schema.json` | Submission format and structural comparison conventions |
| `/app/hpc-attempt.json` | Host execution status and authorized resources |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/results.json` | Scientific results in the supplied format. |
| `/app/final/hpc-host.txt` | Selected SSH alias for a fresh run. |
