# FPS sampling and reaction-energy error propagation

## Background

The Rad-6 dataset permits controlled study of molecular and reaction-space learning.

The inputs include DFT structures and atomization labels, official extensive and intensive FPS orders, coefficients for the eight source models, the full reaction network and reference energies. The inputs also include `source/SOAP-PROTOCOL.md` and the source conventions.

## Task

Reconstruct all eight source models combining two kernels, two FPS orders and N=500/4000; compare coverage and propagation from molecular atomization errors to the complete reaction network.

## Requirements

- Use all 10712 species and all 32515 reactions, preserving source row order and the -1 rearrangement sentinel. Preserve original source coefficients and the full 2×2 kernel/FPS design. Compute complete source predictions, coverage, signed error propagation and the prescribed balanced contrasts.
- Do not treat this training-exposed network as a blind generalization test; zero AE MAE requires an undefined ratio represented by null.
- Use the original nonperiodic DFT coordinates, H/C/O species, n_max=l_max=8, cutoff/atom_sigma pairs 2.0/0.3 and 4.0/0.6 Angstrom, and squared atomic SOAP dot products.
- Normalize intensive kernels separately per cutoff before averaging; extensive targets are AE, intensive targets AE/N with training-mean correction and molecular-N restoration.
- Use `hpc` to inspect the configured cluster and execute descriptor and kernel construction, all prescribed fits or model predictions, and the full scientific comparisons in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Keep source inputs unchanged and use the supplied scientific data. All numerical results are assessed by independent source reconstruction and protocol checks.

- Use one fixed coverage convention for all eight models: a small molecule has at most four atoms and participates in at least one source reaction. Count each species once per reaction row for reaction incidence, even when it occurs in multiple roles. Rank all source species by decreasing incidence, breaking ties by increasing numeric species ID; use the first twenty as hubs. Coverage uses the selected FPS training prefix.

- Submit the required results and evidence under `/app/`.

See the listed output convention for the complete input index, field structure, units and fixed numerical protocols. Keep linked run evidence within the declared submission directory.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Molecular data, model coefficients and reaction network. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/output-contract.md` | Required outputs and submission format. |
