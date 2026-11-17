# Finite Gas Reweighting and Identifiability

## Background

Finite gas-phase records can support reweighting diagnostics without establishing equilibrium or a complete thermodynamic cycle. The fixed six-particle Hamiltonian, two recorded coordinate sets and eight-state protocol are supplied.

## Task

Recompute all eight state energies for both 320-frame replicas, solve their finite-data MBAR equations, and compare frame-common and state-specific energy-gauge transformations.

## Requirements

- Use the supplied Hamiltonian, coordinates and state schedule; each state contributes 40 frames per replica. Preserve replica and coordinate identity, including any allowed bijective column reordering.
- Convert kJ/mol energies with the prescribed R and T, fix f[0]=0, and report all free energies, overlap matrices and weight-based Neff.
- Recompute both prescribed gauge transformations and check weight normalization and solver convergence. Do not add pV or standard-state terms.
- Generate no new dynamics, substitute no observations, and infer no hydration free energy, equilibrium or time independence from these records. Include a nonempty bounded interpretation.
- Use installed local tools without networking.

- Submit the required results and evidence under `/app/` according to the listed output convention. The reproducible analysis entry point is `/app/analysis.py`.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular systems, force fields and calculation parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/output-contract.json` | Required outputs and submission format. |
