# Lambda distributions and protonation populations

## Background

Near pKa, lambda distributions should resolve both protonation endpoints. The supplied tripeptide systems support comparison with theoretical protonation populations.

Inputs include tripeptide systems, force fields, calibration parameters and theoretical comparisons.

## Task

Plan and execute the three fixed-pH tripeptide simulations, reconstruct lambda probability distributions, identify endpoint peaks, and compare the measured mean deprotonation coordinate with the Henderson–Hasselbalch prediction. Choose the software setup and job organization within the cluster requirements below, while preserving the supplied scientific model and calculation requirements.

## Requirements

- See `/app/AGENTS.md` and use SSH alias `hpc` to inspect the configured cluster and execute all prescribed production simulations in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Prepare the GROMACS CpHMD fork required by the supplied lambda-dynamics model and verify startup before production. A startup check does not replace the required production sampling.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Use pH 4.0 for Asp, 4.5 for Glu and 6.5 for His. Complete one 20 ns production run per system.
- Use the CpHMD fork and preserve the supplied constraints and output interval. Explain equilibration treatment.
- Use state two for Asp/Glu and the neutral-state sum for His. Derive every distribution from actual samples and retain all analysed values.
- Declare bins and mass/density normalization. Convert using bin widths correctly. Require two endpoint peaks separated by more than 0.5, peak-height ratio 0.2–5 and a lower central region. Also check shape using 50 equal bins on [-0.2,1.2].
- The measured mean must differ from HH by at most 0.08. Report finite values and retain logs establishing full production and active lambda dynamics.
- Preserve the actual simulation inputs, launch and analysis commands, native outputs, and available scheduler receipts, including failed or stopped attempts. Report results from the completed production records; retain the effective parameters and analysis windows needed for independent numerical verification.

- Submit the required artifacts and run evidence according to the listed output contract. Keep linked evidence inside the submission directory.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Simulation systems, force fields and run parameters. |
| `/app/output-contract.md` | Required outputs and submission format. |
| `/app/final/` | Submitted results and required execution evidence. |
