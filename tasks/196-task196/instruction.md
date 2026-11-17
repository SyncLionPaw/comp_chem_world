# NNP atomic and cell optimization calculations for eight silica frameworks

## Background

Atomic and cell relaxation can change the energies and periodic connectivity of silica frameworks. Eight initial periodic frameworks and the SiAlOH1 neural-network potential are supplied for a comparison at zero external pressure.

## Task

Calculate the atomic and cell relaxation of all eight supplied frameworks at zero external pressure. Continue each optimization with tightened stopping conditions, reconstruct periodic topology for both results, and compare structural properties under a common potential-energy gauge. Preserve the calculated residuals and numerical changes needed to assess each result.

## Requirements

- Execute the required scientific calculations locally in the task environment. Preserve the actual commands, inputs, native outputs and reproducible execution records.
- Use the designated SiAlOH1 model and 6 Å neighborhood, preserve source isotope masses and target zero external pressure. State energy, force and ASE Voigt stress units.
- Choose the optimizer and atomic/cell freedoms. Declare positive force and stress stopping thresholds per framework, then continue with both thresholds strictly tightened. Preserve native logs, raw forces/stresses, final structures, restarts and failures.
- Check independent energy-force/stress derivatives, step-size checks and numerical changes. Report the performed stopping checks without claiming that a selected resolution is sufficient.
- Verify periodic image-edge topology for both final and tightened structures. Explicit atom permutations, integer lattice basis changes and wrapping maps are permitted; do not force connectivity using an arbitrary cutoff.
- Recompute per-Si energy relative to quartz aq, Si density, periodic-edge mean bond length and lattice lengths. Do not claim SCAN/experimental accuracy, global ground states, full-BZ phonons or a strict local minimum.
- Preserve complete native execution records to support independent verification.

- Submit native trajectories, optimization histories, model settings and derivative samples to record the calculations.
- Submit the required results and evidence under `/app/` according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Framework structures and the designated neural-network potential. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.yaml` | Required outputs and submission format. |
