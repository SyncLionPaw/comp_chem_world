# Task: Assess potential alignment, barrier comparisons, and conditional pathway ordering

## Background

Supplied Fermi levels, reaction barriers, and conditional perturbations can be used to examine constant-potential approximations and pathway rankings under specified assumptions. They are not equivalent to experimental rates, statistical errors, or measurements of the inner electrode potential.

## Task

Use the public `kinetics.json` to calculate changes in neutral/anion mean Fermi levels, nominal barrier rate ratios for two pairs, and worst-case barrier differences under independent perturbations. Explain the assumptions behind the calculations and how missing evidence limits the conclusions.

## Requirements

- Read only `/app/environment/assets/kinetics.json`; use Python 3.12. Use `T=300 K`, `kB=8.617333262145e-5 eV/K`, and the same Eyring prefactor. Calculate the log ratios using logarithmic expressions: `K_vs_water_OS_log10_rate=log10(k_KOS/k_waterOS)` and `K_IS_vs_OS_log10_rate=log10(k_KIS/k_KOS)`.
- `water_fermi_shift_eV` and `K_fermi_shift_eV` are the anion mean minus the neutral-state mean for the same system. Do not describe a Fermi-level shift as a change in inner electrode potential.
- Apply the input positive/negative perturbations independently to each relevant pathway and calculate the worst-case lower bounds `OS_barrier_gap_lower_eV` and `K_pathway_gap_lower_eV`; calculate rate ratios from nominal barriers. Explain the common-prefactor assumption and the minimum positive barrier difference.
- `robustness.json` provides the six finite values above and `claims`; rate ratios are dimensionless and all other values are in eV. `uncertainty_semantics` is optional; if provided, it must be `conditional_bounds_not_Fermi_spread_CI`. The absolute error relative to the input and formulas must not exceed `1e-6`.
- The claims cover `K_slower_OS_than_water`, `K_IS_faster_than_K_OS`, `fermi_spread_is_SEM`, `strict_constant_electrode_potential`, `barrier_bounds_are_measured_uncertainty`, `experimental_TOF_determined`, and `short_range_causality_proven`. Each item contains a `verdict` (`supported`, `conditional`, or `not_established`), `evidence` (a list of JSON Pointer strings), and a nonempty natural-language `rationale`. `scope` is optional; if provided, it must be nonempty text or a list containing one text item. Evidence uses `input:/...` to point to inputs and `result:/...` to point to this task's results; it may point to a field or an appropriate parent node. As applicable, evidence should cover: pathway rankings with lower barrier bounds and prefactor/perturbation assumptions; the Fermi spread and missing effective sample size for the SEM judgment; Fermi shifts and the missing inner-potential measurement for the constant-potential judgment; perturbation assumptions and missing capacitance/path-specific constant-potential corrections for the uncertainty judgment; nominal barriers and model prefactors for the TOF judgment; and missing inner-potential and pathway-specific corrections for the causality judgment. Base conclusions on the evidence; do not prespecify verdicts or scope.

### Input and deliverable details

- `/app/environment/assets/kinetics.json`
- Write `robustness.json`, an executable `analysis.py`, and `report.md` to `/app/final/`. `python analysis.py ASSET_DIR OUTPUT_DIR` must recompute and reproducibly generate the data files. The report must explain calculation assumptions, the distinction between Fermi spread and the standard error of the mean, missing evidence, and the scope of conditional inferences. The claims JSON block is optional; if present, it must agree with the claims in `robustness.json`. This discussion does not establish experimental rates, statistical confidence intervals, or short-range causality.

Here `ASSET_DIR` is `/app/environment/assets/` and `OUTPUT_DIR` is `/app/final/`. Create `analysis.py` as part of your submission; no analysis script is supplied for this task.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/kinetics.json` | Supplied data, parameters or method documentation; see the task requirements. |
| `/app/environment/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |

The existing output-format summary is available at `/app/environment/assets/output-contract.json`. Use the scientific definitions and numerical conventions above.
