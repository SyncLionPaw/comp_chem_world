# Task: Count Li–Li contacts along migration paths

## Background

Supplied POSCARs and some CONTCARs sample Li4+x, Li5+x and Li7−x migration paths, with hop-level INCAR/KPOINTS. Energies and mechanistic interpretation are not supplied, so only local path geometry can be assessed.

## Task

Count short Li–Li contacts in every image and describe their variation along each sampled path. Separately assess whether these per-hop geometries establish a bulk fully mixed solid solution, distinguishing lack of evidence from thermodynamic impossibility.

## Requirements

Use CONTCAR when present and POSCAR otherwise. With periodic minimum-image distances, count each Li–Li pair once if its distance is strictly less than 2.60 Å. Include all endpoints and interior images and derive path-specific statements from the complete contact series. For the bulk-solid-solution assessment, state what structural and thermodynamic evidence would be needed and whether these hop geometries provide it; explain evidence and limits in `methods.md`. Do not infer energies, activation barriers or bulk thermodynamic stability from these geometries.

Write `/app/final/results.json` with `contact_series` for `Li4_plus_delta`, `Li5_plus_delta` and `Li7_minus_delta`; each row has `hop`, `image` and `n_pairs`. In `kinetic_conclusion`, include booleans `li7_short_contacts_absent_at_endpoints`, `li7_short_contacts_present_on_interior_images`, `li4_and_li5_start_already_have_short_contacts` and `bulk_solid_solution_required`. For Li7−x use hop name `NEB_Li7-x`; otherwise use each image’s parent directory. Also write `/app/final/methods.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Image geometries and hop-level VASP settings. |

Read geometries under `/app/assets/`, together with hop-level INCAR/KPOINTS. Submit `/app/final/results.json` and `/app/final/methods.md`.
