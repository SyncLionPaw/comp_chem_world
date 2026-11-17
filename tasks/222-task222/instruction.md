# HH fitting from supplied trajectories

## Background

Synthetic lambda time series for Asp, Glu and His cover nine pH values and three replicas per residue, supporting population estimation and HH fitting.

The inputs include synthetic lambda trajectories, their index and an experimental pKa reference.

## Task

Analyse the supplied trajectories, compute populations and replica SEM, and fit HH pKa values with statistical intervals.

## Requirements

- Perform local analysis only. Analyse every supplied 50 ns trajectory in full at its 1 ps sampling interval; do not run new dynamics.
- Classify lambda<0.2 as protonated and lambda>0.8 as deprotonated. Both boundary values and the region between them are intermediate. Endpoint population is deprotonated count divided by the sum of endpoint counts.
- Calculate each replica population before the three-replica mean and sample standard deviation divided by sqrt(3). Sum the three regime counts per residue/pH point.
- Fit S=1/(1+10^(pKa-pH)) from the measured populations. Cover all 27 unique points, use finite values and nonnegative SEM. Standard CSV quoting and arbitrary row order are allowed.
- pKa recovery tolerance is 0.10. Intervals must be ordered, contain the reported pKa and be at most 0.5 wide. State the statistical method. Correlated synthetic trajectories do not establish MD-frame independence or validated interval coverage.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Supplied trajectories and reference data. |
| `/app/inputs/output-contract.md` | Required outputs and submission format. |
| `/app/final/` | Submitted results and required execution evidence. |
