# Task: Generate and rank an aspirin conformer ensemble

## Background

The thermally accessible gas-phase conformers of aspirin depend on sampling, symmetry-aware identification of repeated minima and consistent statistical weighting.

## Task

Using `MACE-OFF23-small`, generate and relax a diverse ensemble for the molecule in `/app/inputs/molecule.smi`, identify distinct relaxed basins and estimate their Boltzmann populations at 298.15 K.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, MACE, NumPy, RDKit. Do not install additional packages or fetch dependencies from the network.

Relax every generated candidate on the supplied model’s energy scale. Remove structures that are symmetry-equivalent after relaxation so each retained structure represents a distinct basin. Rank retained minima by increasing energy; compute relative energies from the global minimum and normalized Boltzmann populations at 298.15 K. Report the ensemble actually found: its accessible population split depends on deduplication granularity and is not prescribed. Do not use a task-specific external solution.

The operational acceptance range is 2–5 distinct conformers. The first excited conformer must be within 0.05 eV of the minimum, the minimum within 0.1 eV of the reference, and the first two SDF conformers separated by a best-fit RMSD of at least 0.10 Å.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/molecule.smi` | Input molecular structure in SMILES format. |

**Inputs**

- `/app/inputs/molecule.smi`.

**Deliverables**

Write `/app/final/result.json` using the structure below. Include one entry per retained conformer, with consecutive ranks starting at 1.

```text
{
  "n_unique_conformers": <integer>,
  "global_minimum_energy_eV": <number>,
  "conformers": [
    {"rank": <integer>, "relative_energy_eV": <number>, "boltzmann_population": <number>}
  ]
}
```

- `/app/final/conformers.sdf`: include the same relaxed structures in the same order, one record per conformer.

Time budget: 3,600 s.
