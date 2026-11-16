# Finite-cohort electrostatic adsorption-heat effects

## Background

Independent insertion moments describe finite-cohort electrostatic adsorption-heat effects at 298 K.

Public inputs provide the cohort, source moments, model context and thermodynamic conventions.

## Task

Reconstruct DDEC3-minus-NO_Q effects for every included group and H2S-effect-minus-CO2-effect for paired structures.

## Requirements

- Retain the acquired 11-group universe and fixed 10-group cohort (six CO2, four H2S); exclude GAZLAW_clean/CO2 by provenance, never by effect sign. Only four paired structures enter gas contrasts. Reconstruct Qst=RT-cE from primary/audit moments, within/between-replica variance, rounding and deterministic energy bounds, using the full formulas in the listed output contract. Source admissibility remains total halfwidth <=0.5 kJ/mol and numerical <=0.05. Use Fieller/Cauchy–Schwarz denominator correction; per-group difference uses two 97.5% enclosures (t=0.9875 quantile), gas contrasts four 98.75% enclosures (t=0.99375). Require both primary/audit intervals to support a sign, else unidentified. Choose CO2, H2S or paired_gas_difference focus without dropping results. Serialize to six decimals (5.1e-7 bound); unbounded endpoints are empty cells. Nominal Student/asymptotic coverage is per comparison, with no population or experimental claim.
- Use only this case’s public inputs; retain required statuses, failures, units and reproducible evidence.

- Complete the finite-cohort analysis from the supplied sufficient statistics in the local container. Do not generate new trajectories, invoke remote scientific engines, or infer effects for structures or gases absent from the supplied observations. Put all deliverables under `/app/outputs/`; the submitted code must support the fixed replay command in the public output contract.

- Submit analysis.py and its dependencies in outputs/code/; it must regenerate the scientific results in an empty directory.

- During controlled replay, `/submission` and `/inputs` are read-only; `/out`, `/tmp` and a private `/dev/shm` are writable. The public runtime and `/dev/null` and `/dev/urandom` are available; `/proc`, grading data, and host-specific paths are not. Use the provided command-line paths rather than assuming the host filesystem layout.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/opt/qeq-public/` | Public data, models and calculation parameters. |
| `/opt/qeq-public/output-contract.yaml` | Required outputs and submission format. |
| `/app/outputs/` | Submitted results and required execution evidence. |
