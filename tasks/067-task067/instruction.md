# Task: Compare TIP3P and TIP4P/Ew Binding-Free-Energy Errors

## Background

The six-ligand OAMe table provides experimental, TIP3P and TIP4P/Ew binding-free-energy means in kcal mol⁻¹ with reported simulation σ. `environment/assets/method-basis.md` fixes the comparison.

## Task

Separate each water model's absolute error, common offset and ligand ranking, then explain the per-ligand TIP4P/Ew−TIP3P shifts and the limits of the comparison.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Use equal weights to calculate RMSE, mean prediction-minus-experiment offset, offset-corrected RMSE, squared Pearson correlation, OLS slope of prediction on experiment, and Kendall tau-a. Report all six paired ligand shifts and distinguish ranking from absolute accuracy.

The reported σ values describe simulation estimates; they are neither force-field uncertainty nor weights in this protocol. Do not claim a new MD run, model training or causal force-field diagnosis. Keep conclusions limited to these six ligands and discuss sampling and model-form limits.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/submission/metrics.json` | Comparison metrics |
| `/app/submission/per_ligand_effects.csv` | Effects by ligand |
| `/app/submission/interpretation.json` | Interpretation |
| `/app/submission/comparison-report.md` | Comparison report |
| `/app/submission/provenance.json` | Data provenance |
