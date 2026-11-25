# Defect clusters

## Background

Residual defects and clusters must be distinguished from registration and periodic-mapping artifacts in large cascade configurations.

The supplied initial and final configurations each contain 16 million atoms and support periodic reference construction and defect mapping, respectively. `request.json` specifies the scientific scope, units and controls.

## Task

Analyze the original 16-million-atom MoTaVW initial/final configurations with periodic Wigner-Seitz mapping. Preserve registration, occupancy conservation, 2NN/3NN clustering at reference site centers, over-occupancy weights, periodic translations, chemical relabeling and known-defect controls. Do not simulate a new cascade or infer general radiation superiority from one final state.

## Requirements

- See `/app/AGENTS.md` and use SSH alias `hpc` to inspect the configured cluster and execute full configuration parsing and reference construction, complete Wigner–Seitz mapping and registration variants, clustering and prescribed controls in Slurm allocations on compute nodes. Local execution is limited to preparation, transfer, monitoring, lightweight inspection and final artifact assembly. Do not replace the required cluster calculations with local production work after a connection or scheduling failure.
- Honor the configured connection waiting periods when probing the cluster. If connectivity or scheduling cannot be restored, preserve the failure and report the blocked execution; do not fabricate success or cancel production after startup and count it as complete.
- Retain submission scripts, scientific commands and input identities, job IDs, original scheduler receipts, compute-node native logs, and the correspondence between jobs and final outputs. Collect these execution records under `/logs/agent/hpc-evidence/` and return the scientific outputs to their existing declared paths. A successful scheduler exit alone does not establish scientific correctness.
- Analyze both complete 16-million-atom MoTaVW configurations: the initial state and the 140 ps final state of the supplied 100 keV cascade. Construct the complete periodic reference from the initial structure and map every final-state atom; do not run a new cascade or infer general radiation superiority from one state.
- Preserve exact occupancy conservation, reference-site identities and complete atom-to-site mappings. Cluster vacancies with the specified 2NN convention and interstitials with the 3NN convention at reference-site centers. Vacancy weights are 1; interstitial weights are occupancy−1, and cluster sizes are their sums. This does not identify a unique dumbbell atom as the interstitial position.
- Compute at least two full-map registration translations and at least two cutoff variants for each defect type. Retain known-defect, periodic-boundary, translation, chemical-relabeling, registration and cutoff controls. Count boundary-crossing clusters once and state the periodic centroid convention.
- Choose spatial indexing and the implementation while retaining the listed output convention. Preserve parsing, registration, mapping and clustering code, inputs, native outputs and failed or stopped attempts. MD execution logs are not required. No reference answer is supplied.

- Submit the required results and evidence under `/app/results/` according to the listed output convention. Declare defect element and ID conventions in `metadata.json` and retain extra-atom and mapping indices for overoccupied sites.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Initial and final structures and analysis parameters. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/assets/output-contract.json` | Required outputs and submission format. |
