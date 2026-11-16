# Task: Calculate 3C-SiC lattice thermal conductivity

## Background

Phonon–phonon scattering limits lattice thermal conductivity. Computing it requires harmonic and anharmonic interatomic force constants and converged reciprocal-space integration; a machine-learned potential supplies the force evaluations.

## Task

Using `MACE-MATPES-PBE-0`, calculate isotropic lattice thermal conductivity for cubic 3C-SiC at 100 K and 300 K, starting from the conventional bulk structure in `/app/inputs/sic_bulk.cif`.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, MACE, NumPy, Phonopy, pymatgen, SciPy. Do not install additional packages or fetch dependencies from the network.

Reduce to the primitive cell, then relax both cell and atomic positions to a force tolerance of 0.01 eV/Å. Use float64 for finite-difference force constants. Calculate second- and third-order force constants using a 2×2×2 primitive-cell supercell, integrate on a 5×5×5 Brillouin-zone mesh, and report the conductivity averaged isotropically over the tensor in W m⁻¹ K⁻¹ at both temperatures. Do not use task-specific external solutions.

The conductivity comparison uses 5% relative tolerance at both temperatures.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/sic_bulk.cif` | Conventional bulk SiC structure. |

**Inputs**

- `/app/inputs/sic_bulk.cif`: conventional bulk structure.

**Deliverables**

Write `/app/final/thermal_conductivity_results.json` with the following structure (both values are numbers in W m⁻¹ K⁻¹):

```text
{
  "thermal_conductivity_summary": {
    "temp_100K": <number>,
    "temp_300K": <number>
  }
}
```

Time budget: 3,600 s.
