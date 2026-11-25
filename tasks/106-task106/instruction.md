# Task: Assess a five-image Li5+x ordinary-NEB path

## Background

The supplied five-image hop-1 path has a separate cell for each image, frozen NEB inputs, historical relaxed endpoint evidence and an output schema. The endpoints are upstream relaxations, not new static calculations.

## Task

Assess the finite ordinary-NEB evidence by reconstructing the sampled profile and checking native forces, tangents, spring contributions and reported arithmetic. State what it supports about force convergence and saddle evidence; a short finite path does not establish a converged saddle.

## Requirements

For fresh calculations, see `/app/AGENTS.md` and use SSH alias `hpc` to probe authorized resources. Choose MPI ranks, memory, wall time, and concurrency within the task budget. Submit, wait for a terminal state, collect native outputs, and validate the scientific results.

Use the frozen five images, ordinary NEB with `LCLIMB=.FALSE.`, three active images, `NPAR=4`, and the specified standard PAW_PBE Li 17Jan2003, Ti 08Apr2002, O 08Apr2002. A fresh run is limited to the authorized four-step resource plan. Do not alter inputs, substitute PAW identities or climbing-image NEB, or replace historical endpoint evidence with new static calculations. Keep physical atomic forces distinct from projected NEB forces; preserve each image’s cell; report both energy conventions, with sigma-zero primary. Provide at least four common complete ionic steps for active images 01–03, host-verifiable native provenance and observed-method comparison. Do not present the geometric tangent check as VTST’s internal tangent or the finite path as a converged saddle. Do not publish POTCAR contents.

For a fresh run, read `/app/hpc-attempt.json` first. Follow the host’s sealed PAW policy and authorization. The `hpc_standard_native_v1` source is qualified by installed paths, titles, component hashes/order and combined hash, but is not claimed byte-identical or numerically equivalent to the archived source. Keep frozen endpoints as separate historical evidence. Under this alternate policy report active-image same-step energies separately, identify historical endpoint-only comparisons and mark the full endpoint-to-active profile `INCOMPARABLE/NOT_ESTABLISHED`; do not report a mixed-source barrier. Never bypass disabled host submission, transfer or shell access; report missing evidence.

Use inputs and `/app/assets/output-schema.json`; write `/app/final/results.json` to that schema, preserving native records and provenance.

Read the authorized aliases, job name `attempt_id`, and `workdir_template` from `/app/hpc-attempt.json`. Probe and choose a host and partition with `hpc`, then use that job name and directory for submission. Write the chosen SSH alias alone to `/app/final/hpc-host.txt` for native evidence collection. Run the Slurm commands from a writable working directory and link `/app/submit-job.json` there as `submit-job.json`.

For a fresh run, stage `accepted-plan.json` in the job directory with `ntasks`, `memory_gib`, `walltime_seconds`, `neb_ranks`, `vasp_path`, and `mpi_path`. Include `# CCB_ACCEPTED_PLAN_SHA256=<digest>` on its own line in the submitted batch script. Hash the plan as UTF-8 JSON with sorted keys, compact separators, and no final newline.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | NEB inputs, upstream records and output schema. |
| `/app/assets/output-schema.json` | Submission format |
| `/app/hpc-attempt.json` | Host execution status and authorized resources |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/results.json` | Scientific results in the supplied format. |
| `/app/final/hpc-host.txt` | Selected SSH alias for a fresh run. |
