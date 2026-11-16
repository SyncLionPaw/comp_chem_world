# Task: Organonitrate energy reconciliation

## Background

SI Table 9 labels benzene and four toluene OH-addition sites. Deposited Gaussian/Molpro files contain energies, sometimes with free NO2.

## Task

Recompute SI energies from native files. Check the meta-alkoxy identities, use SI lifetimes to verify labeled columns, and report unresolved energy, rate or saddle assignments.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

- Recompute 20 selected energy cells and all 30 candidates relative to each column's B-RONO2 anchor; include free-NO2 F12 energy and Gaussian zero-point correction where required.
- Report DFT-only (DFT electronic energy + ZPE) and composite (F12 electronic energy + DFT ZPE) values, SI energies and deviations. Preserve the four native paths `source_dft_file,source_f12_file,anchor_dft_file,anchor_f12_file` for every row; CSV `includes_no2` states whether the reported energy includes the separate free-NO2 contribution.
- Verify both meta-alkoxy pairs by hashes, embedded F12 source-log identity and NO2-corrected energy; distinguish SI lifetime/rate evidence from native kinetic evidence and flag unsupported rates.
- List all saddle candidates and deviations by site. Mark ambiguity when multiple candidates are within 0.10 kcal/mol; assess identifiability without assuming a unique channel.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Source records and reaction data for the analysis. |

Inputs are `/app/assets/41467_2023_40675_MOESM1_ESM.docx` and `/app/assets/RONO2/`; no new calculation is needed. In `column_assignment.json`, `assigned_column` accepts canonical keys or matching SI display names (`Benzene`, `Toluene (site)`). Write under `/app/final/`:
- `rono2_energies.csv`: 20 selected cells with `species_column,quantity,file_stem,source_dft_file,source_f12_file,anchor_dft_file,anchor_f12_file,includes_no2,dft_zero_point_kcal_per_mol,composite_kcal_per_mol,published_kcal_per_mol,deviation`.
- `rono2_candidates.csv`: all 30 candidates with the same columns.
- `column_assignment.json`: top-level `columns` (five `{species_column,assigned_column}` records), `lifetime_evidence` (three `{species_column,published_rate_per_s,lifetime_minutes,assigned_column}` records), `rate_witness_scope` (`SI_only` or `native_supported`), and `channel_selection` (five `{species_column,candidates,selected_file_stem,ambiguous}` records). Each saddle candidate has `{file_stem,composite_kcal_per_mol,published_kcal_per_mol,abs_deviation}`. Optional `comparison_rule` may state `comparison_tolerance_kcal_per_mol:0.10`.
- `identity_conflict.json`: two `advertised_species` records (B-RO and RB-C1-RO) with `{label,dft_file,f12_file,dft_sha256,f12_sha256,f12_source_log_name,f12_energy_au,computed_with_free_no2_kcal_per_mol,published_kcal_per_mol,abs_deviation_kcal_per_mol,status}`. `status` describes whether native file content supports its advertised label, independently of SI-cell assignment. `resolved` requires geometry and source evidence. Mark selected energy cells or rates without native support in `unverified_rows.json`; keep candidate identity findings here.
- `unverified_rows.json`: `rows` for selected energy cells or SI rates lacking native support, each with `{species_column,quantity,status,reason}`. Use `unverified_input_identity_conflict` when a selected energy-cell assignment lacks a native witness because its identity is unresolved, and `unsupported_no_native_witness` for unsupported rates; rate rows also include `published_rate_per_s`. Keep candidate-level identity questions in `identity_conflict.json`.
- `discrepancies.md`: explain the source-identity and recoverability findings, native rate-evidence limits, and saddle identifiability.

Use species columns `benzene,toluene-ipso,toluene-ortho,toluene-meta,toluene-para`; quantities `x-B-RO + NO2,TSrearrangement,x-RB-RONO2,x-RB-RO + NO2` (`x-` optional), and rates `kx-B-RONO2 => x-B-RO + NO2`,`kx-B-RONO2 => x-RB-RO + NO2` (or `k_B-RO`,`k_RB-RO`). Paths may be asset-relative, start with `assets/`, or use `/app/assets/`. Tolerances: DFT-only 0.01, composite/deviation 0.002, SI transcription 0.001 kcal/mol; report composite/deviation to at least three decimals. Candidate ambiguity threshold: 0.10 kcal/mol. Lifetimes may be rate-derived or approximate SI values with source stated. Missing-witness explanations may be in English or Chinese.
