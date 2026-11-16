# Extract solvent clusters while preserving molecules and periodic-boundary geometry

## Background
The supplied topology/trajectory describe a periodic aqueous system; extracted clusters must preserve whole molecules across PBC.

## Task
Extract local solvent clusters at ten frames and state sampling limits.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use frames 0,10,…,90 and the first 18-atom residue as solute. Include a whole solvent residue if any atom is within 4.0 Å of any solute atom by orthorhombic minimum image. Reconstruct molecules along topology bonds using minimum-image vectors. Compute the unwrapped solute arithmetic centroid; place each solvent molecule’s first atom in the nearest image to it; subtract centroid once from all coordinates and do not recenter. Preserve solute-first/native solvent-residue and atom order; derive elements from atomic numbers. Record frame times, zero-based indices, and source/selected scalar max-minus-min spans in ps. This is geometric extraction, not independent equilibrium evidence. Read supplied topology/trajectory; submit selection.json, extract.py, analysis.md and selected frame XYZs under /app/final/. Public output contract defines record fields. CLI regenerates clusters from inputs in a clean directory.

Comparison tolerances are 0.001 Å for coordinates, 1e−6 ps for frame times, and 1e−7 ps for the time span.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Topology and trajectory. |
| `/app/output-contract.yaml` | Output format and evidence requirements. |

/app/inputs/: topology/trajectory; /app/output-contract.yaml: contract; /app/final/: selection/clusters/code/analysis.
