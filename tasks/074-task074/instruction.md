# Task: Hsp60 Catalytic Dyad Geometry and Apical Conformation

## Background

`/app/assets/Fig_6b.dat` and `Fig_8b.dat` provide per-frame data at 300 K for the double-ring D and football F assemblies, respectively; `data_dictionary.md` defines panels, columns, units, and protonation states. Analyze δ (Asp50–Asp397 Cγ–Cγ distance, Å) and γ (apical opening angle, degrees) for WT/V72I and AspAsp/AshAsp/AspAsh in oligomer panels: 12 groups per observable. The monomer M column is optional background only and is not part of these 12 groups.

## Task

Use the supplied data to assess associations of V72I and protonation state with dyad geometry and apical opening. Determine effect directions, correlation directions, and whether a shoulder is present from the data; do not assume outcomes.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, NumPy, pandas, SciPy. Do not install additional packages or fetch dependencies from the network.

- For each of the 12 δ groups and 12 γ groups, report finite `n`, mean, sample standard deviation (`ddof=1`), median, Q1, and Q3. At minimum, provide matched WT→V72I δ/γ comparisons for each group, and δ comparisons of AshAsp and AspAsh against AspAsp for each assembly and variant. For every comparison, state whether the mean or median was used, reference and target values, the signed target-minus-reference effect, units, and the direction determined by the values.
- Report empirical contact proportions and counts for raw δ≤4.35 Å, including within-group mutation comparisons and contact-proportion differences for each singly protonated state versus AspAsp. Report apical context directly from γ: for F, the median and proportion with γ>120°; for D, the median and proportion with γ≥100°.
- For each of the 12 groups, calculate the Pearson correlation of frame-paired δ and γ, the paired count, and direction. Frames are pooled monomer observations; there are no independent-replicate labels or time axis. Standard deviations, quartiles, proportions, and correlations are descriptive, not confidence intervals or independent-sample inference; make no causal or significance claims.
- Submit complete, continuous histograms for δ in all 12 groups. In `findings.json`, `rdf_normalization` may be `raw_count`, `frequency`, `probability_density`, or `radius_weighted_probability_density`; `density` must strictly match the declared definition: count, count/N, count/(N·bin_width), or bin_center·count/(N·bin_width), respectively.
- For AspAsp in D/F × WT/V72I, report eight shape probes using σ=0.10 and 0.15 Å. Use one consistent algorithm: a probability-density histogram p(r) over 0–16 Å at 0.01 Å spacing; radial shape p(r)/r²; smoothing with `gaussian_filter1d` (`sigma_angstrom/0.01`, `mode='nearest'`, `truncate=4.0`); slope from `numpy.gradient(smoothed,0.01)`; and minima found with `find_peaks(-slope)`. Report every slope minimum and its position/slope in the closed D window 4.6–5.0 Å or F window 4.1–4.7 Å. `primary_mode_angstrom` is the location of the maximum of the unsmoothed radial shape among centers r strictly greater than the window lower bound (choose the smallest center in a tie). `primary_mode_above_feature` is true only if at least one in-window minimum is below that mode and the mode is above the first such minimum. `raw_mass_feature_window` is the proportion of raw δ values in the closed window. `shoulder_present` is true if and only if there is an in-window slope minimum. Pair `feature_positions_angstrom` and `feature_slope_values` in ascending center order; `feature_type` is fixed as `local_minimum_of_radial_shape_slope`. Slope minima, secondary peaks, and raw probability mass in the window are distinct quantities; do not substitute one for another or assume a shoulder is present.
- Compute all effects and statistics from full-precision data; numeric fields must be finite. Reproduction tolerances are `max(2e-6, 2e-6×max(|actual|,|expected|))` for ordinary fields, `max(2e-8, 2e-6×max(|actual|,|expected|))` for RDF density, and an absolute 0.0200001 Å for shape positions. RDF edges must be contiguous and equally spaced, with error no greater than 1e-9 Å. These are acceptance tolerances, not rounding precision.

### Input and deliverable details

Submit `distributions.csv`, `rdf.csv`, `findings.json`, and `report.md` in `final/`. CSV columns are:

- `distributions.csv`: `assembly,variant,protonation,observable,n,mean,std,median,q25,q75`; exactly 24 combinations of D/F × WT/V72I × three protonation states × δ/γ.
- `rdf.csv`: `assembly,variant,protonation,bin_left,bin_right,count,density`; cover the complete δ range for all 12 groups.
- `findings.json`: required top-level keys are `schema` (fixed to `assembly-dyad/v1`), `rdf_normalization`, `statistical_methods` (non-empty string array), `inference_status` (fixed to `descriptive_only`), `limitations` (non-empty array of explanatory strings), `uncertainty_provenance`, and the seven result arrays below. All JSON numbers must be finite and counts must be integers.
  - `mutation_effects`: 12 rows, one per assembly × protonation × observable; match on `assembly,protonation,observable`. Include applicable string fields `statistic,reference_variant,target_variant,reference_protonation,target_protonation,observable,units,conclusion` and finite numeric `reference_value,target_value,effect`. `statistic` is `mean` or `median`; the variant contrast is WT→V72I.
  - `protonation_effects`: 8 rows, one per assembly × variant × singly protonated target; match on `assembly,variant,target_protonation`. Include applicable string fields `statistic,reference_variant,target_variant,reference_protonation,observable,units,conclusion` and finite numeric `reference_value,target_value,effect`. `statistic` is `mean` or `median`; reference AspAsp, target AshAsp or AspAsh, observable δ. `conclusion` is `higher`, `lower`, or `equal`; effect is target minus reference, with `equal` when |effect|≤1e-12.
  - `local_contact_state`: 12 rows with string fields `assembly,variant,protonation`, integer `n`, and finite numeric `threshold_angstrom,probability_delta_le_threshold`.
  - `local_contact_differences`: 14 rows with string fields `contrast,assembly,variant,protonation,reference,target,conclusion` and finite numeric `effect`. `contrast` is `mutation` or `protonation`; direction is `higher`, `lower`, or `equal` (`equal` when |effect|≤1e-12). Include six WT→V72I and eight singly protonated-state versus AspAsp differences. Mutation rows use an empty string for `variant` and `reference=WT,target=V72I`; protonation rows use `variant=WT` or `V72I`, `reference=AspAsp,target=AshAsp` or `AspAsh`. Every difference is target minus reference contact proportion.
  - `apical_context`: 12 rows with string fields `assembly,variant,protonation,cutoff_operator`, integer `n`, and finite numeric `gamma_location_median_degree,cutoff_degree`; also include finite `fraction_gamma_ge_100_degree` for D or `fraction_gamma_gt_120_degree` for F.
  - `delta_gamma_dependence`: 12 rows with string fields `assembly,variant,protonation,method,interpretation`, integer `n_paired`, and finite numeric `coefficient`. `method` is `Pearson`; direction is `positive_association`, `negative_association`, or `zero_association`.
  - `shape_features`: 8 rows with keys `assembly,variant,sigma_angstrom,feature_window_low_angstrom,feature_window_high_angstrom,feature_type,feature_positions_angstrom,feature_slope_values,shoulder_present,primary_mode_above_feature,primary_mode_angstrom,raw_mass_feature_window`. `feature_type` is `local_minimum_of_radial_shape_slope`; position and slope arrays must be paired and list every in-window minimum; they may be empty.
- All four Boolean fields in `uncertainty_provenance` must be `false`: `independent_replicates_available`, `time_axis_available`, `pooled_frame_spread_is_confidence_interval`, and `frames_treated_as_independent_samples`.
- In concise prose, `report.md` must explain the statistics, matched comparisons, RDF normalization, direct γ metrics, shape probes, and descriptive uncertainty limitations. Its values must agree with `findings.json` and both CSV files.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/Fig_6b.dat` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final/distributions.csv` | Summary statistics for δ and γ |
| `/app/final/rdf.csv` | Radial distributions |
| `/app/final/findings.json` | Structured comparisons |
| `/app/final/report.md` | Scientific interpretation |
