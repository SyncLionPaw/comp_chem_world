# Task: Run three fresh periodic-water CP2K labels

## Background

The task supplies three periodic water geometries, each with 192 atoms, its own cell, and a CP2K input template.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Run a fresh CP2K ENERGY_FORCE calculation for each geometry. Use BLYP-D3, TZV2P-GTH, GTH-BLYP, a 500 Ry cutoff, and a 60 Ry relative cutoff. Preserve each geometry, cell, and atom order; in its template replace only @PROJECT_NAME@ with the specified job name.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `ikkem-slurm` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

Each native output must show one finite total energy in Hartree, one complete 192-row force block in Hartree/Bohr, positive SCF convergence, normal termination, and geometry and cell echoes consistent with the input. Preserve input row order in the forces.

Write final/native-labels.json as UTF-8 JSON with finite numbers. Its top level is:

    {
      "schema": "task180-native-labels/v2",
      "unit_conversion": {
        "hartree_to_ev": 27.211386245988,
        "hartree_per_bohr_to_ev_per_angstrom": 51.422067476325886
      },
      "records": []
    }

Include exactly three records in job order 0, 10, 19. Each record must report label_job_ordinal, exit_status (copied from its exit-status.json), input_sha256, geometry_sha256, native_output_sha256, atom_count, composition, cell_angstrom (the ordered 3×3 input cell vectors), scf, normal_end, method, energy_hartree, energy_eV, forces_hartree_per_bohr, and forces_eV_per_angstrom. The three content checksum values are lowercase hashes of the exact rendered input, geometry include, and native output bytes. Use atom_count 192, composition {"O":64,"H":128}, scf CONVERGED, normal_end true, and method BLYP-D3 / TZV2P-GTH / GTH-BLYP / 500 Ry / REL_CUTOFF 60. Store forces as finite 192×3 arrays in input order. Convert the parsed binary64 native values with the constants above and retain enough digits for round-trip; conversion values may differ by at most 4 ULP. Compare each same-geometry result with the pinned native reference using the frozen numeric bands regardless of the candidate's build/runtime profile: PASS requires |ΔE| ≤ 0.01 eV, force-component RMS ≤ 0.001 eV/Å, and maximum force-component difference ≤ 0.005 eV/Å; GRAY uses the wider limits in refs.json, and values beyond those limits fail. Build/runtime profile fields (including compiler, CPU, dates, and data-directory text) are diagnostic only. All three PASS bands score 1; any GRAY with no FAIL scores 0.5; an UNQUALIFIED or incomplete band set scores 0; a numeric FAIL rejects the submission. Candidate-reported execution metadata does not authenticate where or how the calculation ran.

**Execution setup.** Follow the host execution profile and use its supported software environment.

### Input and deliverable details

Inputs are in environment/assets/v2/native-labels/label/cp2k-inc-{0000,0010,0019}/, each with coord_n_cell.inc and cp2k.inp. Use the corresponding task180_label_0000, task180_label_0010, or task180_label_0019 project name. For each job, save the rendered input, unchanged geometry include, native output, and process exit status in exit-status.json as {"exit_code":0} on success under runs/cp2k-label-v2/label-{0000,0010,0019}/{cp2k.inp,coord_n_cell.inc,output,exit-status.json}. Also submit final/native-labels.json.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/v2/` | Three starting water geometries and CP2K input template. |

| Path | Contents |
| --- | --- |
| `/app/final/native-labels.json` | Required result; use the contents and format specified above. |
| `/app/runs/cp2k-label-v2` | Required result; use the contents and format specified above. |
