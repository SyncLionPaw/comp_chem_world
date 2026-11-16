# Martini constant-pH validation

## Background

Martini coarse-grained tripeptides support a test of charge-interpolation constant-pH dynamics against all-atom and experimental comparisons.

Inputs include Asp/Glu coarse-grained systems and force field, and all-atom and experimental comparisons.

## Task

Design and execute the Asp/Glu coarse-grained titration sampling within the requirements below, fit pKa values, and compare the coarse-grained, all-atom and experimental results. Choose the software setup and job organization within the cluster requirements below, while preserving the supplied scientific model and calculation requirements.

## Requirements

- Use `ikkem-slurm` to inspect the configured cluster and execute all prescribed production simulations in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Prepare the GROMACS CpHMD fork required by the supplied lambda-dynamics model and verify startup before production. A startup check does not replace the required production sampling.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Preserve the supplied single-lambda representation, buffers, reaction-field electrostatics, relative dielectric 2.5, infinite external dielectric and 20 fs timestep. Do not substitute PME or an all-atom timestep.
- Use the CpHMD fork. Choose and justify a converged pH grid, replica count and duration, with at least three distinct pH values per residue covering the titration midpoint.
- Use lambda<0.2 and lambda>0.8 for endpoint populations, excluding intermediate samples. Explain equilibration and derive HH fits and uncertainty from actual runs.
- Require Asp pKa in [3.5,3.9], Glu in [4.1,4.5], CG–AA difference<=0.10 and CG–experiment difference<=0.15. Intervals must contain the reported pKa; use a consistent deviation convention.
- Retain the actual production artifacts.
- Preserve the actual simulation inputs, launch and analysis commands, native outputs, and available scheduler receipts, including failed or stopped attempts. Report results from the completed production records; retain the effective parameters and analysis windows needed for independent numerical verification.

- Submit the required artifacts and run evidence according to the listed output contract. Keep linked evidence inside the submission directory.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Simulation systems, force fields and run parameters. |
| `/app/output-contract.md` | Required outputs and submission format. |
| `/app/final/` | Submitted results and required execution evidence. |
