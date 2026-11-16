# Task: Cross-source consistency of aromatic BPR rates

## Background

The deposit contains 15 single-temperature MESMER outputs for bicyclic peroxy radicals from seven aromatic precursors. A workbook reports a 16-cell rate grid without row labels; native files may have two product channels and differing temperatures.

## Task

Map each published cell to a molecule and addition site using the supplied evidence, compare it with defensible native-rate definitions, report irreconcilable cells, and assess whether temperature differences permit a substituent trend.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

- Read both native first-order channels for every XML output and record molecule, site, file and conditions. Reconcile all 16 published cells against channel1, channel2, faster or sum; missing native witnesses stay blank for unavailable fields.
- For every conflict, report all candidate definitions, values and relative deviations. Do not force a universal definition or hide unexplained cells.
- Compare at recorded temperatures (298, 298.15 and 300 K). Give a limited toluene-ipso 298-to-300 K sensitivity for the activation term alone and including the temperature exponent; assess whether the available temperature evidence permits normalization of close cross-molecule rankings.
- Assess whether a single definition explains all cells and whether the evidence resolves close cross-molecule orderings. Limit any substituent trend to the conditions and uncertainty supported by the data.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Source records and reaction data for the analysis. |

The XMLs are in `/app/assets/Figure4/`; workbook and SI DOCX are under `/app/assets/`. Use the chemical aliases ethylbenzene/E-Benzene and isopropylbenzene/I-Benzene. Benzene's single site may be `ipso` or `unique`/equivalent; this site alias applies only to benzene. No MESMER run is needed. Submit under `/app/final/`:
- `bpr_rate_matrix.csv`: 15 rows, columns `molecule,oh_addition_site,source_file,temperature_K,pressure_Torr,bath_gas,k_channel1_per_s,k_channel2_per_s,k_dominant_per_s`.
- `cell_reconciliation.csv`: 16 rows, columns `molecule,oh_addition_site,published_value_per_s,source_file,temperature_K,matched_definition,matched_value_per_s,relative_deviation,reconciled`. Definitions: `channel1,channel2,faster,sum,missing_native`. Native-backed rows report a native value; a match is within 5%. Missing-native source/temperature/match/deviation fields are blank.
- `anomalies.json`: `unreconciled` array of `{molecule,site,source_file,temperature_K,published_value_per_s,candidates,reason}`. Each candidate has `definition,value_per_s,relative_deviation`; native-backed conflicts list all four definitions, while a missing-native cell has no candidates.
- `trend_evidence.json`: Boolean `single_definition_claim`; `temperature_scope` has `recorded_temperatures_K,normalisation_status,toluene_ipso_298_to_300_activation_percent_range,with_n_percent,close_orderings_indeterminate`, with optional `activation_basis`. Use the 270–310 K local modified-Arrhenius fit by default (`local_modified_arrhenius_fit` or `local_modified_arrhenius_fit_270_310K`); alternatively use TS1/TS2 native static barriers (`native_static_barriers`) from the pinned toluene-ipso XML, explaining the basis and `n_eff` split in `trend_analysis.md`. `with_n_percent` is the observed 298-to-300 K channel-rate change: a two-element range, or a scalar for the dominant channel with both channel endpoints stated in `trend_analysis.md`. Limit ranges and trend claims to the evidence; justify `indeterminate` or `established` normalization.
- `trend_analysis.md`: explain mapping, conflicts, temperatures, sensitivity example, and limits on universal normalization.

Use `d=(native-published)/published` (signed or absolute); reconcile at `abs(d)<=0.05`. Paths may be asset-relative, prefixed by `assets/`, or unique basenames. Booleans may use true/false, yes/no, 1/0, or reconciled/unreconciled. Missing-native explanations may be in English or Chinese.
