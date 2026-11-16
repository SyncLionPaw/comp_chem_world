# Compare transport observables and finite-size-corrected diffusion across six temperatures

## Background

The supplied reline data give box lengths, viscosities, ionic diffusion coefficients, and Green–Kubo conductivity at six temperatures. Diffusion coefficients already include a finite-size correction; the system specification gives composition and molecular charges.

## Task

Recompute Nernst–Einstein conductivity, `gamma=sigma_GK/sigma_NE`, and the Yeh–Hummer diffusion increment. Explain what the ratios imply about charge-current correlations and molecular association, and what evidence is still needed.

## Requirements

- Derive ionic number density and charge contributions from the system specification. Convert the rounded table to SI, use cubic volume `L³`, and account for the existing diffusion correction. Report the Yeh–Hummer increment separately; do not apply the correction again when computing conductivity.
- Use `e=1.602176634×10⁻¹⁹ C`, `k_B=1.380649×10⁻²³ J/K`, and cubic-cell constant 2.837297. Report conductivity in S/m and diffusion increment in m²/s at each supplied temperature.
- Identify temperatures with gamma above/below one. Explain its physical meaning, admissible range, interspecies correlations, whether an ion-pair interpretation is supported, and uncertainty needed to assess significance. Base conclusions on the calculations rather than preset classifications.
- Provide a Python 3 standard-library program that reads the CSV via `--input` and regenerates outputs with `python calculations.py --input INPUT.csv --output DIR`. It must work when lengths, viscosities, diffusivities, or conductivities change.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Conductivity audit table and system definition. |
| `/app/output-contract.json` | Output and evidence conventions. |

Read `/app/inputs/conductivity-audit.csv` and `/app/inputs/system-spec.json`. Write `/app/results.csv`, `/app/analysis.json`, and `/app/calculations.py`; use `/app/output-contract.json` for field definitions. Record correction treatment, temperature classification, SI units, and scientific interpretation.
