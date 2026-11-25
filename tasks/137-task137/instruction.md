# Tensor properties and vibrational spectra

## Background

Neuroevolution potentials (NEPs) model atomistic properties. This study asks whether NEPs can represent rank-1 molecular dipoles and rank-2 polarizability tensors, how accurate and efficient those predictions are, and whether the resulting models support infrared (IR) and Raman spectroscopy. No scientific data, models, or reference results are supplied.

## Task

Choose a physical system and reproducible research design. Address all six targets: `rank1_dipole`, `rank2_polarizability`, `accuracy`, `efficiency`, `infrared_spectroscopy`, and `raman_spectroscopy`. Use suitable reference data to evaluate model properties. Distinguish previously reported data from your own calculations, and explain units, methods, scope, uncertainty and limitations. Mark unsupported targets `insufficient`; do not present an unperformed calculation as a result.

## Requirements

If using HPC computing resources, see `/app/AGENTS.md` and use SSH alias `hpc`.

Use only resources you are authorized to access. Choose resources according to the scientific requirements; do not assume a GPU is available or guess host/account details. Use a new job directory and keep the research independent of benchmark reference or historical run materials. Record the methods, data, resource use, execution outcomes and evidence needed to reproduce reported results. If a service is unavailable, report it as a limitation, not scientific disproof.

## Files

Public input files:

| File path | Description |
| --- | --- |
| — | No predefined research data are supplied. |

Submit `/app/final/research.json` with all referenced evidence files. Use globally unique IDs. Paths are submission-relative, contained in the submission and do not traverse symlinks. JSON numbers must be finite.

| Record | Required fields and conventions |
|---|---|
| Top level | `question`; arrays `claims`, `sources`, `artifacts`, `evaluations`, `executions`, and `target_coverage`. |
| `claims` | `id`, `statement`, `conclusion` (`supports`, `contradicts`, `insufficient`), `scope`, `evidence_ids`, `limitations`. |
| `sources` | `id`, public `url`, `local_artifact` ID, `sha256` of local source bytes, and `acquisition_note`. |
| `artifacts` | `id`, relative `path`, `sha256`, and `role`. |
| `evaluations` | `id`, `kind` (`numeric`, `qualitative`, or `scientific_constraint`), `evidence_ids`. Qualitative: `description`. Numeric: `metric`, `calculation`, `artifact_id`, `value`, `unit`; add relevant input keys below. |
| `executions` | `id`, `role` (`selected_result`, `retry`, `postprocess`, `other`), `status` (`completed`, `failed`, `cancelled`), `resource_mode` (`declared_local_only`, `slurm_accounted`), `command`, `input_artifact_ids`, `output_artifact_ids`, `evidence_ids`, `exit_code`, `elapsed_seconds`, and `cpu_cores`, `memory_gib`, `gpu_count`, `gpu_memory_gb`, `allocated_gpu_hours`. Preserve and account for failed, retry and postprocessing runs where applicable. If no computation was run, `executions` may be empty and the report must say so; a `selected_result` is completed with exit code 0. A local CPU run needs a GNU `/usr/bin/time -v` artifact; set `timing_artifact_id` and ensure its command, elapsed time, exit status match the execution record, with logged peak memory no greater than declared `memory_gib`. |
| `target_coverage` | `id`: exactly one row per target above; `status` (`supports`, `contradicts`, `insufficient`), nonempty `claim_ids`, `evaluation_ids`, and `artifact_ids`. Each claim must cite an evaluation; each evaluation must cite relevant source or artifact evidence. |

For numeric evaluations, supported metrics are `rmse`, `mae`, `r2`, `mean`, `std`, `l2_norm`, and `relative_difference`. Paired arrays use `reference_key` and `prediction_key`; array summaries use `values_key`; `relative_difference` also uses `reference_value`. Use matching arrays with at least two entries for paired metrics and a nonconstant reference for `r2`; `std` uses ddof=0 and `relative_difference=abs(mean(values)-reference_value)/abs(reference_value)`. Recomputed values use atol=1e-8 and rtol=1e-7. Other metrics may be documented for independent review. Choose appropriate efficiency measures and report their units, hardware, workload and measurement method with supporting evidence.

An optional tensor-covariance evaluation can support `rank1_dipole` or `rank2_polarizability`. Use `constraint: "tensor_rotation_covariance"`, `target_id`, `artifact_id`, and `unit`, and name `original_key`, `rotated_key`, `rotation_key`, `original_positions_key`, and `rotated_positions_key`. Store the five arrays together in one NPZ artifact: dipoles `(3,)`, polarizabilities `(3,3)`, proper rotation `(3,3)`, and atom positions `(N,3)` in the same order. Under rotation R, positions transform as r′=rRᵀ, dipoles as μ′=Rμ, and polarizabilities as α′=RαRᵀ. The normalized maximum absolute residual must be no greater than `1e-7`; normalize tensor and coordinate residuals by their respective original maximum absolute components. Choose a nontrivial rotation; an unchanged geometry or tensor does not distinguish covariance from an invariant output. This tests covariance, not predictive accuracy.

Place the submission at `/app/final/`. It must contain `research.json` and every source, data, model, script, report and execution artifact referenced by that index.
