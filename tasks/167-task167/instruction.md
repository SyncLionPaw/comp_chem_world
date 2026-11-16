# Task: Construct and validate monolayer W₂N₃

## Background

Monolayer W₂N₃ is a candidate phonon-mediated superconductor. Build a crystallographic model from `assets/structure-brief.md`; distinguish
reported claims from values recomputed from your structure.

## Task

Create a three-dimensionally periodic five-atom W₂N₃ primitive cell with space group P-6m2 (No.
187), hexagonal in-plane `a=2.85–2.95 Å` (justify the choice), and clear interlayer vacuum ≥15 Å.
Choose internal z coordinates consistent with symmetry, bonds, and the brief; assess the stated
Wyckoff labels, coordination, and any incompatibility between the supplied source’s central-N claim and the
constructed structure. Independently validate symmetry, Wyckoff occupation, and site symmetry with
spglib or pymatgen. No DFT is needed.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use minimum-image periodic distances. Report the clear gap from the top atomic plane to the next
periodic image (not `c`), outer-N-to-outer-N layer thickness, W coordination at 2.45 Å, and the
count of outer N bonded to exactly three W within 2.15 Å. Keep stated claims separate from computed coordination.
Explain all discrepancies in a nonempty explanation. Lengths are in Å.

### Input and deliverable details

Read `assets/structure-brief.md`. Write `/app/final/W2N3-monolayer.poscar` (VASP POSCAR, scale 1.0,
Cartesian lattice in Å, Direct fractional positions) and `/app/final/structure-report.json`.

`structure-report.json` exact fields and types: `stoichiometry` string; `n_atoms`,
`space_group_number` integers; `space_group_symbol` string; `inplane_lattice_a_A`, `vacuum_A`,
`layer_thickness_A` finite numbers; `coordination` object with `cutoff_A` number, `W_counts`
two-integer array, `N_three_coordination_count` integer, `N_center_count` integer;
`paper_coordination_claims` object of integers `W`, `N_outer`, `N_center` (source values 6, 3, 5);
`discrepancy_note` nonempty string. `W_counts` are W–N counts at the declared cutoff and must
be consistent at 2.45 Å; outer-N count must match the 2.15 Å check. Space group must match
independent recomputation. Extra fields are allowed.

Include `computed_wyckoff_sites`, with one record per atom containing zero-based `atom_index` in POSCAR order, `species`, `wyckoff_letter` and `site_symmetry`. Use the submitted cell and a symmetry tolerance of 0.001 Å.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `assets/structure-brief.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final/W2N3-monolayer.poscar` | Required result; use the contents and format specified above. |
| `/app/final/structure-report.json` | Required result; use the contents and format specified above. |
