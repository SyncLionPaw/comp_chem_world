# Spatial transport at prescribed electrode flux

## Background

The inputs provide initial and conditioned meshes, flux conditions and solve settings, and transport, species and boundary parameters.

## Task

Solve the seven-species GMPNP model over the full 80 µm domain for zero and prescribed 1 mA/cm² flux controls.

## Requirements

See the listed output convention for output fields, numerical rules and scientific criteria.

- Actually solve the seven-species GMPNP model at both conditions: zero and prescribed 1 mA/cm² CO-flux controls over the full 80 µm domain. These are spatial solves at imposed flux, not postprocessing or predictions of kinetic electrode current.
- Preserve rounded bulk values, K-only packing/common steric activities, Robin electrostatics, all homogeneous reactions and Dirichlet bulk values/potential. Electrode fluxes are CO2=−f, CO=+f, OH=2f and zero otherwise; K/CO have no homogeneous source and CO is neutral with zero bulk concentration. Zero electrode flux does not imply chemical equilibrium.
- Choose a valid solver and at least four nested full-domain grids resolving both boundary layers and 10 nm. Audit all seven original equations and Robin/Poisson; report full fields and RP/10 nm/bulk observables. Repeat finest solves from perturbed primary guesses at higher arithmetic precision.
- Retain every attempt, coordinates and unrounded primary fields. No clipping, log(0), positive replacement of zero flux or shortened domain. Independently integrate continuous sources/charge and check bulk endpoint gradients; discrete balances include the bulk half-cell and reconstructed reservoir flux, not just the last internal face. Report zero-source identities separately.
- Compare concentration/activity, pH, packing and electrostatic response with the stated reservoir/carbonate limits; empirical mesh stability does not prove continuum uniqueness or physical-model uncertainty.

- `/app/code/solve.py` must accept `--inputs PATH --output PATH` for independent isolated recomputation.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Meshes, model parameters and solver controls. |
| `/opt/co2-public/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
