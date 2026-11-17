# Multi-Target Pose Reranking and Paired Statistics

## Background

Molecular docking algorithms often produce multiple decoy poses alongside near-native conformations. Evaluating whether enhanced sampling simulations successfully improve pose identification requires testing across diverse targets and conducting formal statistical hypothesis testing against docking baselines.

The inputs include OpenBPMD+grand scores and pose RMSDs for 210 poses across 42 systems, together with IFD scores and source pose numbers from the original MAE records.

## Task

Evaluate the full dataset of 42 diverse protein-ligand systems (210 candidate docked poses) tabulated in Supplementary Table S1 from OpenBPMD simulations with grand equilibration. Complete the following:
1. Rerank poses strictly by their metadynamics `CompScore` (in ascending order; lower score = higher stability).
2. Select the Top-1 predicted pose for each system and calculate overall benchmark success rates under the 2.0 Å and 3.0 Å heavy-atom RMSD cutoffs.
3. Derive the IFD Top-1 pose from the minimum original `r_psp_IFDScore` in the supplied ACS SI extraction, using the explicit pose number and exact pose ID. Join both methods' pose IDs to Table S1 and run a two-sided paired Wilcoxon signed-rank test on the per-system Top-1 RMSDs (`IFD RMSD`, `OpenBPMD RMSD`) with `zero_method=wilcox`, `correction=False`, `method=auto`. Report nominal p and the decision at prespecified alpha 0.05; do not force significance or tune the pairing to the paper's rounded statistic.
4. Identify and report the specific kinase system outlier under standard 0.3 kcal/mol hills.

## Requirements

- Rank all 210 poses in 42 systems by ascending CompScore, never RMSD. For exact ties choose the lexicographically smallest pose ID and report all ties; both `tie_break` and `score_tie_policy` use `lexicographically_smallest_pose_id`.
- Compute Top-1 success at 2.0/3.0 Å. Derive IFD Top-1 from minimum original `r_psp_IFDScore`, joining explicit pose numbers and exact pose IDs to Table S1.
- Test paired per-system Top-1 RMSDs (not binary success/ranks) with two-sided Wilcoxon, `zero_method=wilcox`, `correction=False`, `method=auto`. Report actual nominal p and the alpha 0.05 decision without forcing significance or claiming causal/general superiority.
- Report the CDK2 2b52 outlier under 0.3 kcal/mol hills without changing scores. Compare recomputed statistics to the OpenBPMD 2022 SI Figure S1 (S=98.5, p=0.00197), retain both pairs and the discrepancy flag; do not tune rounded-source calculations to match the published summary or attribute it to Clark2016.
- `paired_variable` and `p_value_interpretation` are nonempty free text; counts are JSON integers excluding booleans, and scores/rates/statistics finite numbers. Median-difference tolerance: 1e-9 Å.

The output contract listed below defines the input index, output fields, units and numerical protocols. Keep linked run evidence within the declared submission directory.

JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.

The paired effect may use either declared subtraction direction, with the median signed accordingly; improved always denotes lower OpenBPMD RMSD.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Pose scores, RMSDs and method-comparison data. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/output-contract.md` | Required outputs and submission format. |
