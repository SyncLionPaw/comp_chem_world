# Contact Dynamics and Composite Scoring

## Background

In Open Binding Pose Metadynamics (OpenBPMD), the resistance of a ligand to a biasing potential deposited along its RMSD collective variable reflects its pose stability. To evaluate this stability beyond hydrogen bonds (which fails for hydrophobic or pi-stacking ligands), OpenBPMD introduces `ContactScore` and the composite `CompScore = PoseScore - 5 * ContactScore`.

The inputs provide an equilibrated, centered protein-ligand reference structure and an OpenBPMD trajectory with 99 production frames.

## Task

Analyze an enhanced sampling trajectory of a protein-ligand complex, compute the time series of ligand heavy-atom displacement (`PoseScore`) and nonbonded heavy-atom contact persistence (`ContactScore`), and calculate the final composite stability score over the final 2 ns of the simulation.

## Requirements

- Use frame 0 of `solute.dcd` as the reference, excluding it from the 99 production rows. Fit each production frame's protein `backbone` to frame 0 before calculating ligand RMSD in Å.
- Keep the distinct selections: PoseScore uses `resname UNK and not name H*`; contacts use ligand `resname UNK and not name *H*` and the frame-0 protein neighborhood `protein and not name H* and around 5 resname UNK`. Numeric-prefix hydrogen names can survive the first selection; do not reuse it for contacts.
- Native contacts are ligand/protein pairs at frame-0 distance <3.5 Å. For each production frame, Q is the fraction with distance no greater than its own reference distance. Normalize by the first nine production Q values' mean and clip at 1.0. Include all such noncovalent contacts, not only hydrogen bonds.
- Average PoseScore and ContactScore over the final 20 of 99 production frames (approximately 2 ns at 100 ps spacing), using unrounded values. Do not substitute snapshots or whole-trajectory means.
- Require `CompScore = PoseScore - 5 * ContactScore` within 1e-4. The independent reference uses unrounded tail means; PoseScore/ContactScore may be reported to three decimals, with CompScore computed from the reported values. More digits are accepted; no pre-rounding convention is imposed.
- All CSV scores and JSON summary scores must be finite; JSON booleans are not scores.

JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.

Submit a JSON object with finite non-boolean numbers `PoseScore` (Å), normalized `ContactScore`, and `CompScore = PoseScore - 5 * ContactScore`. Submit a CSV with 99 rows and unique headers including integer `frame` and finite numeric `PoseScore`, `ContactScore`, and `CompScore`; additional unique columns are allowed.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Reference structure and trajectory. |
| `/app/scores.json` | Pose-stability metrics. |
| `/app/timeseries.csv` | Framewise pose and contact metrics. |
