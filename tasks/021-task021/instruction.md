# Task: Reconstructing the bicyclic peroxy radical ring-opening profile

## Background

The deposited Gaussian DFT and Molpro F12 outputs and workbook define the toluene ipso-BPR ring-opening profile. Reconstruct it and determine the supported energy combination.

## Task

Derive both barriers and product energies relative to ipso-BPR. Trace native quantities and blocks, resolve repeated Gaussian blocks, and compare the supported rule with two alternatives.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

- Use the supplied Gaussian and Molpro outputs and workbook; a transcription of published values alone is insufficient.
- For all five stationary points, report the source files and identify the native energy quantities and calculation blocks. Explain the selected blocks, the energy-combination rule, zero-point correction, Hartree-to-kcal/mol conversion, and BPR reference.
- Verify species and electronic state from the native calculations: 21 atoms and 57 vibrational modes per species, multiplicity 2 throughout, exactly one imaginary frequency for each transition state and none for BPR or either product. Limit conclusions to this deposited cluster and reported profile.
- The adopted profile must reproduce the four non-reference workbook values within 0.10 kcal/mol. Compare at least two rejected rules in `energy_rule.md`; give all four predictions and their position-matched signed or absolute deviations in C1, C2, P-C1, P-C2 order, each within 0.02 kcal/mol of the computed values.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Source records and reaction data for the analysis. |

Write four files under `/app/final/`:

- `bpr_profile.csv`: five rows for `BPR`, `C1`, `C2`, `P-C1`, `P-C2`; columns `species,file_dft,file_f12,e_electronic_au,zpe_au,e_zero_point_au,e_f12_au,derived_kcal_per_mol`. BPR's derived energy is zero.
- `bpr_profile.json`: `rule.rejected_alternatives[].scheme` may use `dft_zero_point`, `dft_electronic`, `dft_gibbs`, or `f12_only`. `rule` fields `electronic_source`, `correction_source`, `reference_species`, `unit`, and numeric `hartree_to_kcal` (within 0.001 of 627.509); root fields `derived_values_kcal_per_mol` and `published_values_kcal_per_mol` keyed by the four non-reference species; and `rule.rejected_alternatives`, with at least two distinct `{scheme, values_kcal_per_mol}` records containing all four species. Use chemical-method names or native-source identifiers for the electronic and correction quantities; identify the BPR reference and report energies in kcal/mol. Determine and justify the supported combination from the evidence. JSON derived values agree with CSV within 0.01 kcal/mol and published values with the workbook within 0.01 kcal/mol. Use finite numbers.
- `energy_rule.md`: rationale, unit/reference convention, at least two named alternatives, and each alternative's four predictions and four matching deviations in the order above. Use table rows labelled with the JSON scheme identifier for predictions and deviations, with the four species in the stated order. State the rule as a formula.
- `native_parse_manifest.json`: `records` entries `{species, quantity, source_file, value_au}` for `zpe_au`, `e_zero_point_au`, and `e_f12_au` for every species. Each value must match the named species's native output. `label` and `line_number` may be included as locators; when supplied, they must identify the actual latest matching source line. Paths may include `assets/` or use unique basenames; if basenames are used, set `source_directory` to `Toluene-iBPR-rearrangment`. Optional `e_dft_gibbs_au` or `e_gibbs_au` must match that species' latest Gaussian Gibbs line. Each species/quantity may occur once; use one Gibbs alias.

No quantum-chemistry engine is needed.

Inputs are under `/app/assets/`: `41467_2023_40675_MOESM1_ESM.docx` (SI methods and T1 diagnostics), `41467_2023_40675_MOESM3_ESM.xlsx` (published Source Data), and the Gaussian `.log` / Molpro `.out` pairs in `Toluene-iBPR-rearrangment/` for BPR, TS-C1, TS-C2, P-C1, and P-C2.
