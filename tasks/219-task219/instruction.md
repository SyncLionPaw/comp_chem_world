# Protein multisite pKa prediction

## Background

Cardiotoxin V contains four titratable sites: His4, Glu17, Asp42 and Asp59. The supplied protein system and experimental references support a site-specific titration assessment.

Inputs include Cardiotoxin V structures, topology, indices and run parameters, plus force fields, calibration parameters and experimental references.

## Task

Plan and execute the prescribed protein titration campaign, calculate site-specific curves and pKa intervals, and compare the fitted values with experiment. Choose the software setup and job organization within the cluster requirements below, while preserving the supplied scientific model and calculation requirements.

## Requirements

- See `/app/AGENTS.md` and use SSH alias `hpc` to inspect the configured cluster and execute all prescribed production simulations in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Prepare the GROMACS CpHMD fork required by the supplied lambda-dynamics model and verify startup before production. A startup check does not replace the required production sampling.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Use pH 1.0–8.0 in steps of 0.5, five independent replicas per pH, 50 ns per replica: 75 simulations. Preserve 300 K, 1 bar and the supplied 20 buffer particles.
- Use the CpHMD fork, map index groups and atom collections to the correct sites, and extend the short template to production duration.
- Explain equilibration, endpoint classification and replica aggregation. Use lambda<0.2 and lambda>0.8 for the two basins; exclude the middle region. His deprotonation is the neutral-state sum.
- Cover every site with finite curves in [0,1] and intervals containing the fitted pKa. Treat Asp59 pKa<2 as an upper bound; document exclusion, an upper-bound approximation or another justified censored-data policy.
- Report Pearson r, MSE, RMSE, residuals and included sites. Require r>=0.90, MSE<=0.5 and RMSE<=0.8.
- Preserve the actual simulation inputs, launch and analysis commands, native outputs, and available scheduler receipts, including failed or stopped attempts. Report results from the completed production records; retain the effective parameters and analysis windows needed for independent numerical verification.

- Submit the required artifacts and run evidence according to the listed output contract. Keep linked evidence inside the submission directory.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Simulation systems, force fields and run parameters. |
| `/app/output-contract.md` | Required outputs and submission format. |
| `/app/final/` | Submitted results and required execution evidence. |
