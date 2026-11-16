# Multi-Replica Ensemble Statistics and Trace Diagnostics

## Background

Because metadynamics is a non-equilibrium enhanced sampling simulation that stochastically traverses energy barriers, a single 10 ns simulation trajectory is statistically noisy and prone to sampling hysteresis. To establish reproducible pose ranking, OpenBPMD executes 10 independent simulation replicas for every candidate binding pose.

Each of the ten replica directories contains `bpm_results.csv` with 99 rows of CompScore, PoseScore (Å) and ContactScore. The inputs include the resampling protocol and complete bootstrap index table.

## Task

Ingest the results from 10 independent OpenBPMD simulation repeats, calculate the ensemble mean and standard deviation across all repeats, extract the final 2 ns tail window across the ensemble, and synthesize the 6 official benchmark stability metrics.

## Requirements

- Analyze all ten replicas and all 99 frames. Compute the six summary metrics from the pooled 200 final-window values (10 replicas × final 20 frames), using population SD; do not substitute the SD of replica means.
- Compute framewise population SD, whole/tail autocorrelation and ESS, paired replica drift, and both whole-window and within-tail variance changes. Preserve source frame order and exactly the unique replica IDs 0..9.
- Use the supplied resampling protocol and complete bootstrap index table: 4000 whole-replica draws of ten slots, retaining duplicates and degenerate draws. Use binary64 in the declared order, divisor 9 for bootstrap sample variances, and sorted zero-based endpoints 100/3900 without interpolation (tolerance 1e-9).
- Use the specified fields, ACF stopping/constant-trace rules, frozen t coefficient 2.262 and diagnostic status tokens. Summary scores may have three decimals and framewise SD six; this does not relax bootstrap tolerance.
- Limit conclusions to finite-trace diagnostics. Without a trusted practical-equivalence margin, stability remains unresolved and `convergence_status` is `INCONCLUSIVE`; neither detected nor undetected change certifies free-energy or thermodynamic convergence. Ten-cluster bootstrap and df=9 t intervals are approximate.
- This analyzes supplied traces; no additional simulations are required.

JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Replica score series and resampling parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/output-contract.md` | Required outputs and submission format. |
