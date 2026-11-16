# Initial Ni–Ni3Al phase regions and static Mo partitioning

## Background

Study chemical-order phase boundaries and static Mo partitioning in the supplied initial state.

The inputs include the author’s Ni/Al/Mo initial configuration, lattice and interface-width parameters, and a ledger of static exchange energies and temperature.

## Task

Analyze the supplied author 108000-atom Ni/Al/Mo initial configuration. Infer the ordered Ni3Al slab using Al occupation on the FCC corner sublattice, independently of Mo. Identify the slab axis by the restricted set of Al-bearing half-lattice layers (fcc_a_A/2 grid); infer each interface halfway to its adjacent Al-free corner layer. Wrap coordinates with the periodic cubic cell. Interior is gamma_prime, exterior gamma. Exclude interface distances <= width+1e-9 A. Compute the requested interface-width sensitivity of the STATIC initial Mo ratio K_snapshot = c_Mo(gamma_prime)/c_Mo(gamma). These are not equilibrium partition coefficients.

## Requirements

Compute phase populations, Mo concentrations and static partition ratios for each requested interface width, and output phase labels in source-row order at the requested width. Analyze each static energy ledger entry to calculate forward and reverse energy differences and theoretical Metropolis–Hastings probabilities and log probabilities under symmetric proposals. Each row starts from S0 and reverses back to S0; pairs were chosen deterministically and no accept/reject experiment was recorded. Temperature changes reweight the same static energies and do not create thermal trajectories. Do not calculate new NEP energies or run MCMD.

Explain chemical-order boundaries, width sensitivity, and why the initial state and three swaps cannot establish equilibrium mixing or a confidence interval. Use only the supplied records; the executable accepts `--inputs DIR --output DIR`, writes directly to the output directory, and recomputes for each input including temperature changes. Use bundled Python dependencies without network access. Submit results and evidence according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Interface structures, exchange energies and calculation parameters. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.json` | Required outputs and submission format. |
