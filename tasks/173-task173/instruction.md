# Task: Compare cell composition and SANS length scale

## Background

`environment/assets/frame_late.xyz` is a periodic cubic LiTFSI–water cell; its comment gives the edge in Å. `experimental_sans.txt` gives the SANS peak window and uses `2π/q` for its real-space repeat.

## Task

Determine the cell composition and molality, convert the SANS window to repeat lengths, and compare them with the cell edge.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Molality is moles of LiTFSI per kilogram of water; `n_H2O_per_Li` is the water-to-lithium number ratio. Report `sans_repeat_A` as `[2π/q_max, 2π/q_min]`. `correlation_lengths_along_edge` is the edge divided by the repeat at the q-window midpoint. `cell_spans_multiple_repeats` is true when the edge exceeds that repeat; `charge_neutral` is true when Li and TFSI counts are equal.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Simulation cell and scattering reference data. |

Write `/app/final/composition.json` with integer counts, numeric measurements in the stated units, and JSON booleans:

`n_atoms`, `n_Li`, `n_TFSI`, `n_H2O`, `molality_mol_kg`, `n_H2O_per_Li`, `box_length_A`, `sans_repeat_A`, `correlation_lengths_along_edge`, `cell_spans_multiple_repeats`, `charge_neutral`.
