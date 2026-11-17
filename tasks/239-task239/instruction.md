# BEP barrier scaling: paired grouped validation and transfer limits

## Background

The supplied BH76 reference barriers support descriptive BEP validation; this is an external extension, not a reproduction of the Rad-6 paper kinetics.

The inputs include BH76 barrier records and GMTKN55 context and usage notes.

## Task

Fit all 38 forward pairs with intercept OLS and evaluate 34 TS LOGO folds and 38 pair LOPO folds, quantifying reference coupling and transfer limits.

## Requirements

- Treat the BH76 `.res` as text, never executable code. Preserve physical line numbers, source order/case, stoichiometric coefficients and negative barriers. Consecutive records are forward/reverse pairs, first fixed forward; convert with C=0.043364104241800934 eV/(kcal/mol), Eaf=first*C, Ear=second*C and deltaE=Eaf−Ear.
- Fit all 38 forward pairs by equal-weight intercept OLS; evaluate 34 TS-group LOGO and 38 pair LOPO folds. Keep forward/reverse partners together; LOGO has zero TS overlap, and LOPO overlap must be reported. Include held-out MAE, baseline, maximum error and extrapolation counts.
- Reconstruct reference-species/repeated-TS counts, population identity cov(deltaE,Eaf)=var(Eaf)−cov(Eaf,Ear), and repeated-TS common-mode perturbation effects on covariance and OLS coefficients.
- Match folds by unique fold_id and predictions/sensitivity records by pair_id; retain source order where meaningful, with no missing/duplicate IDs, JSON keys or leakage. Numeric tolerance is 1e-8 absolute/relative; counts and booleans are exact.
- Explain reference coupling and transfer limits without claiming causal BEP behavior, universal/prospective accuracy, kinetic rates or controls not executed. This external descriptive extension does not reproduce Rad-6 kinetics; no DFT, TS search or microkinetics.
- Use supplied data locally without network.

- Submit the required results and evidence under `/app/` according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Barrier data and analysis parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/OUTPUT-CONTRACT.yaml` | Required outputs and submission format. |
