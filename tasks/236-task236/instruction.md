# Extensive and intensive SOAP-KRR learning curves

## Background

The Rad-6 dataset permits controlled study of molecular and reaction-space learning.

The inputs include DFT structures and atomization labels, official extensive and intensive FPS orders, and `source/SOAP-PROTOCOL.md` and source conventions. The author UFF500 calibration inputs do not represent the full DFT learning curves.

## Task

Fit extensive and intensive SOAP-KRR models for N=500,1000,2000,4000, quantify molecular atomization-energy errors and distinguish kernel scaling from sampling and target effects.

## Requirements

- Fit all eight extensive/intensive runs at N=500,1000,2000,4000 using the respective official FPS sequences. Reserve the preceding 100 and final 1030 IDs for validation/test. Choose a strictly increasing sigma grid spanning [1e-5,1e-1] with at least two candidates; select by validation RMSE and report complete prefix spectra/condition evidence.
- Use original nonperiodic DFT coordinates, H/C/O, n_max=l_max=8, cutoff/atom_sigma 2.0/0.3 and 4.0/0.6 Å, and squared atomic SOAP dot products. Normalize intensive kernels separately by cutoff before averaging. Extensive targets use AE; intensive targets use AE/N, training-mean correction and molecular-N restoration.
- Preserve ordered splits, complete kernel blocks, fitted coefficients and sigma-grid evidence for independent reconstruction; do not substitute source labels for predictions. Author UFF500 calibration is separate from the DFT learning curves.
- Distinguish kernel scaling from FPS/target effects; the N=4000 comparison alone is not a causal kernel claim.
- See `/app/AGENTS.md` and use SSH alias `hpc` to inspect the configured cluster and execute descriptor and kernel construction, all prescribed fits or model predictions, and the full scientific comparisons in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.

Submit the results according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Molecular structures, labels and training orders. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/inputs/source/SOAP-PROTOCOL.md` | Calculation methods and result-submission requirements. |
