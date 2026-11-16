# Molecular Contact Networks from a Real Trajectory

## Background

The supplied 11-frame example trajectory contains 1,728 molecules: N130 pentamers and rpL5 peptides. The supplied `selections.json` identifies the acidic bead types for A0/A1/A2 and the basic rpL5 bead types. A short trajectory samples one local region and its frames are correlated, so it cannot establish ensemble-wide bimodality or percolation.

## Task

Build unweighted, undirected molecule-level contact networks between each acidic tract (A0/A1/A2) and rpL5. Derive each contact cutoff from the first local minimum of the supplied mean RDF, distinguish it from the supplied historical operational cutoffs, and report species-specific and overall degree distributions including isolated molecules.

## Requirements

Use periodic minimum-image distances with the DCD frame box and strict \(d<\text{cutoff}\). Map beads to molecules with the type lists in `selections.json` (`N130_acidic_types`, `rpL5_basic_types`), count each molecule pair once, remove self-loops, and retain every molecule, including zero-degree nodes. The historical source cutoffs are A0 = 13.0, A1 = 13.0, A2 = 12.5 Å; derive the data minima independently. Choose cutoffs within A0 [12.75,14.0], A1 [12.5,13.25] and A2 [12.0,12.75] Å, justify them, and test sensitivity to a one-bin (0.5 Å) perturbation. Sensitivity is not statistical uncertainty. Limit conclusions to what 11 correlated frames support.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Simulation setup, selections, trajectories and RDF data. |

Inputs are in `/app/environment/assets/` (`rpL5_init.data`, `selections.json`, `rpL5_example_traj.dcd`, `RDFs_rpL5_charged_A{0,1,2}Pep.txt`). Write these deliverables under `/app/final/`:

- `graphs.npz`: exactly `A0`, `A1`, `A2`; each a `uint8` adjacency array of shape `[11,1728,1728]`, in DCD frame order and sorted LAMMPS residue/molecule ID order, symmetric, with zero diagonal and isolated nodes retained.
- `degrees.npz`: exactly `A0`, `A1`, `A2`; integer arrays of shape `[11,1728]` equal to the adjacency row sums.
- `cutoffs.json`: exactly `A0`, `A1`, `A2`; each a finite cutoff in Å, equal to the value actually used for that graph.
- `report.md`: bead-to-molecule mapping, distance and contact definitions, RDF-minimum derivation, cutoff rationale, sensitivity, species-specific and overall degree distributions with isolated nodes, and the short-trajectory limitations.
- `analysis.py`: deterministic, reproducible analysis. It must accept `--input-dir` and `--output-dir`, read the six public input files from the input directory, write the other outputs, and use the stated contact conventions.

`analysis.py` must run under the container's provided Python using only its preinstalled packages (NumPy, SciPy, matplotlib, MDAnalysis). The analysis must be self-contained and require no additional packages, network access, or alternative interpreter.

Avoid NaN/Infinity and place only these five files in `/app/final/`.
