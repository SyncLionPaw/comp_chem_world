# Audit historical CP2K, prediction, and execution records without launching new calculations

## Background

This retrospective audit uses supplied CP2K records, archived predictions, selected frames, and public event-ledger projections. A projection is not a complete source ledger. Native validity, engine exit, process completion, and scheduler state are separate; a missing terminal scheduler record is unknown. Do not run CP2K, MD, training, or network services, or claim prospective compliance or pool-wide accuracy.

## Task

Reconstruct input and attempt evidence, compare the declared reference pairs, quantify force errors on selected frames, reconcile the two budget views, and decide whether the evidence supports reference sufficiency. Submit `audit.json` and a concise, evidence-linked `decision.md`.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Check every input against `inputs/public-input-manifest.json`. Keep original-intent `L01`–`L20` separate from retrospective `L02`–`L20` plus `D1`. Bind each attempt to its input, ordered geometry, selected frame, native validity, engine exit, process status, and scheduler evidence. Keep these states distinct and report absent terminal scheduler evidence as unknown.
- Compare exactly `D1/L01`, `D1/R01`, and `B01/S01` in that order. Parse method, functional, dispersion/reference, cutoffs, SCF settings, cell vectors, periodicity, and geometry identity. Report absolute energy difference per atom, Cartesian force-component RMSE, and maximum atom-vector force difference using the contract conversions and gates: `1e-4 eV/atom`, `0.01 eV/Å`, and `0.05 eV/Å`. A pair is eligible only if both native records and processes are verified and settings differ.
- For all 20 selected frames, report each of four models and their arithmetic ensemble: force-component RMSE and maximum atom-vector error, with selection/frame/temperature/trajectory/category and evidence binding. For each population, report random and risk results in all four temperature/trajectory strata (eight cells), including every selected item. Compute stratum error summaries only from native-valid, process-verified records; keep all selected records in the missingness denominator. Count a hit only with verified native and process evidence and ensemble RMSE ≥0.15 eV/Å; for `n` selected items, `h` verified hits, and `m` selected items without verified process evidence, report `[h/n,(h+m)/n]` and compare random/risk within trajectory using one consistently identified population, as defined in the output contract.
- At the selected `L01` frame, compare `D1` and `R01` to the ensemble; report error and hit changes, but keep the archived disagreement-based risk rank fixed. Do not infer pool-wide accuracy or independent sampling.
- Reconcile the original 28 quantum-label-intent cap and later 54 operator-attempt cap on separate accounting axes, including starts, finishes, exits, recoveries, operator events, prestart failures, and charged/unknown jobs. Disclose that ledgers are field projections.
- Follow `inputs/output-contract.json` for audit structure and numerical rules. Give three distinct, ranked next-evidence actions in `audit.json`, each with gap, reason, stop condition, evidence basis, and one budget axis (`analysis_only`, `existing_evidence_only`, or `separate_authorization_required`). `decision.md` may use any clear prose form; its scientific priorities must agree with the audit.
- Do not claim prospective budget compliance, production or pool-wide accuracy, or independent sampling.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Native records, candidate pool and decision policy. |
| `/app/inputs/output-contract.json` | Output and evidence conventions. |

Work under `/app/`; input and output paths below are relative to that directory.

Use `inputs/public-input-manifest.json`, `inputs/native/`, `inputs/pool/`, `inputs/ledgers/`, `inputs/policy/`, and `inputs/output-contract.json`. Submit `audit.json` and `decision.md`; the contract defines the schemas, pair order, thresholds, calculations, and decision policy.
