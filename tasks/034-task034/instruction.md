# How Does the A2 Intervention Affect Condensate Structure?

## Background

The public model is the N130–rpL5 coarse-grained system defined by `AllSys.in.init`, `N130_WT.in.settings`, `WT.data`, and `methods.yaml`. `WT.data` is a 466-bead construction unit, not an equilibrated condensate. A2 is the specified intervention: the specified acidic-region charge neutralization together with the corresponding self-Lennard-Jones changes.

## Task

Assess whether A2 changes PD spatial structure and A2–rpL5 association in the condensed phase. Evidence may support, refute, or leave an effect unresolved. Choose and justify system preparation, integration, sampling, independent repeats, uncertainty, and analyses; no optimizer, timestep, run length, seed, replicate count, metric, or response direction is prescribed.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

If using HPC computing resources, see `/app/AGENTS.md` and use SSH alias `hpc`.

Follow the remote execution interface in `/app/environment/RPC-PROTOCOL.md` and the host's access and scheduler policies. Record actual resource use, job IDs, submission scripts, status, exit codes and collected artifact hashes. Establish a condensate rather than treating the 466-bead construction unit as one. Preserve force-field and intervention identity: A2 includes both the charge and Lennard-Jones changes, so charge-only neutralization is not the A2 intervention. Distinguish new execution evidence from published results. Report equilibration and sampling evidence, uncertainty, limitations, and interpretation. A conclusion may be supported, refuted, or evidence-based inconclusive.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/simulation/` | Public simulation inputs. |

Runtime directory `/app`; public inputs `/app/environment/assets`; deliverables `/app/final/`. Preserve replayable analysis code, generated model inputs, logs, trajectories, analysis data, and their provenance.

- `report.md`: question, method, findings, uncertainty, limitations, interpretation.
- `run_manifest.json`: nonempty `model_identity`, `intervention_identity`, `protocol_rationale`, an `environment` object, a `provenance` array binding the four public input basenames to content checksum, and `analysis_replay`. The replay declares `argv` beginning `python3 analysis.py` (no shell), nonempty final-relative `inputs` and `outputs` lists with every input present under `final/`, a nonempty `dependencies` object, and a nonempty `resources` object.
- `native-artifacts.json`: nonempty `artifacts` with unique final-relative `path`, `role`, `size_bytes`, and `sha256`, covering `model_input`, `simulation_log`, `trajectory`, and `analysis_data`. List and hash every replay output.
- `analysis.py`: readable, reproducible analysis entry point.
- `diagnostics.json`: numerical validity, equilibration, sampling, and uncertainty evidence.
- `scientific-answer.json`: nonempty `overall_assessment`; nonempty `outcomes` addressing both `PD_spatial_structure` and `A2_rpL5_association`. Each outcome declares `metric`, `unit`, `method`, `uncertainty_method`, `interval_type`, `interval_coverage`, `decision_rule`, `interpretation`, finite `wt_estimate`, `a2_estimate`, `difference_a2_minus_wt` (A2 minus WT), an ordered two-value `difference_interval`, and `evidence_direction` in `supports_effect`, `no_resolved_effect`, or `inconclusive`.

No physical threshold or particular response direction is prescribed.
