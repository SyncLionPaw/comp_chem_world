# Tripeptide pKa prediction

## Background

Charge-interpolation constant-pH dynamics uses lambda coordinates to represent protonation changes. The supplied equilibrated Asp/Glu/His systems support titration and comparison with experiment.

Inputs include equilibrated Asp/Glu/His systems, force fields, calibration parameters and experimental comparisons.

## Task

Plan and execute the prescribed tripeptide titration grid, calculate populations from the resulting trajectories, and fit Henderson–Hasselbalch pKa values with uncertainty. Choose the software setup and job organization within the cluster requirements below, while preserving the supplied scientific model and calculation requirements.

## Requirements

- Use `hpc` to inspect the configured cluster and execute all prescribed production simulations in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Prepare the GROMACS CpHMD fork required by the supplied lambda-dynamics model and verify startup before production. A startup check does not replace the required production sampling.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Use Asp pH 2.0, 3.0, 3.5, 4.0, 5.0; Glu 2.5, 3.5, 4.0, 4.5, 5.5; His 5.0, 6.0, 6.5, 7.0, 8.0. Run two independent replicas per point, each for 10 ns: 30 production runs.
- Use the GROMACS CpHMD fork. Preserve the supplied force field, constraints and lambda update settings; set pH, production steps and independent seeds correctly.
- Derive chemical deprotonation coordinates from the multistate channels: state two for Asp/Glu, the sum of neutral states for His. Classify lambda<0.2 as protonated and lambda>0.8 as deprotonated; exclude intermediate values.
- Justify equilibration removal. Compute replica populations before their mean and SEM. Fit S=1/(1+10^(pKa-pH)); derive uncertainty statistically. Intervals must contain the reported pKa and be at most 0.5 wide.
- Deviations from experiment must not exceed 0.15 for Asp/Glu or 0.20 for His. Retain actual run artifacts; do not substitute reference numbers for computed results.
- Preserve the actual simulation inputs, launch and analysis commands, native outputs, and available scheduler receipts, including failed or stopped attempts. Report results from the completed production records; retain the effective parameters and analysis windows needed for independent numerical verification.

- Submit the required artifacts and run evidence according to the listed output contract. Keep linked evidence inside the submission directory.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Simulation systems, force fields and run parameters. |
| `/app/output-contract.md` | Required outputs and submission format. |
| `/app/final/` | Submitted results and required execution evidence. |
