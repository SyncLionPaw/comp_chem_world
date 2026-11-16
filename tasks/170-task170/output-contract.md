# Output contract — case-04

Deliver a static, internally consistent QE 7.2 native interpolation chain in `/app/final/`:

- `scf.in`: dense unshifted SCF fit with `&SYSTEM la2F=.true.`.
- `coarse_scf.in`: regular coarse SCF used by `ph.x`, same prefix, outdir, cell and coordinates.
- `ph.in`: `&INPUTPH`, `electron_phonon='interpolated'`, `fildvscf`, and an automatic unshifted 4×4×1 q mesh.
- `q2r.in`: consumes the matching `fildyn` output, writes the force constants, and enables `la2F`.
- `matdyn.in`: consumes those force constants, enables `la2F`, and may request phonon DOS using `fldos` (phonon DOS only).
- `make-lambda-input.py`: after PH, compute full-mesh orbit multiplicities from the SCF structure using spglib, read each actual PH lambda file in `elph_dir` and its q header in QE Cartesian 2π/alat (`tpiba`) units, convert to reciprocal crystal coordinates, identify the full-grid point, map that point through the spglib orbit table, and fail closed on missing/duplicate points or a weight sum other than 16. It then writes standard `lambda.x` stdin files for μ*=0.16 and 0.10.
- `run.sh`: calls `pw.x` dense fit, `pw.x` coarse SCF, `ph.x`, `q2r.x`, `matdyn.x`, the q-map helper, then `lambda.x` twice; preserve both μ* outputs.
- `plan.json`: route and QE target version, structure, cutoffs, smearing, dense/coarse k and q grids, execution order, dynamic q/file mapping method, positive finite core-hour estimates whose total equals the sum of stages, and rationale for the mesh/budget choices.

Use identical prefix and outdir for the dense and coarse SCF datasets as in the QE 7.2 `PHonon/examples/example03/run_example` interpolation workflow. Use consistent cell and ordered atomic positions in both decks. `CELL_PARAMETERS alat` is accepted only when its scale is explicitly computed from `celldm(1)`; this implementation template uses angstrom.

The two decks must also use `ATOMIC_POSITIONS (crystal)`, contain exactly W₂N₃ (two W and three N), and be periodically equivalent to the hash-checked `assets/W2N3-monolayer.poscar`: lattice vectors within 1e-3 Å and atom positions within 1e-3 Å after periodic wrapping and same-species matching. Changing both decks consistently to another unit, species, coordinates or cell does not satisfy the structure contract.

This case does not run Quantum ESPRESSO. Its estimated costs are planning estimates with no measured benchmark, and a static PASS does not show the 300/40 core-hour budget is achievable on a specific machine. The selected pseudopotential names are placeholders and must be replaced with licensed, compatible files before a production run.

## Typed `plan.json` format

The verifier accepts either layout below. Fields shown as required are typed and must be present; additional evidence is allowed. The expanded layout is accepted because earlier versions of this task described the same plan with these names. Do not assert an error direction, convergence, or performance without measurements.

### Compact layout

```json
{
  "route": "qe_native",
  "qe_target": "QE 7.2",
  "execution_order": ["dense_scf_fit", "coarse_scf", "ph", "q2r", "matdyn_a2f", "lambda_postprocess"],
  "structure": {"n_atoms": 5, "cell_height_z_A": 25.15},
  "cutoffs": {"ecutwfc_ry": 80.0},
  "smearing": {"occupations": "smearing", "degauss_ry": 0.01},
  "grids": {"dense_scf_k": [64, 64, 1], "coarse_scf_k": [16, 16, 1], "q": [4, 4, 1]},
  "estimated_core_hours": {"dense_scf": 24.0, "coarse_scf": 2.0, "ph": 36.0, "post": 6.0, "total": 68.0},
  "estimate_basis": "Planning estimate only; not benchmarked.",
  "justifications": {
    "dense_scf_k": "...",
    "coarse_scf_k": "...",
    "q": "...",
    "degauss": "..."
  }
}
```

### Expanded layout

```json
{
  "case": "case-04",
  "material": "W2N3 monolayer",
  "qe_target_version": "7.2",
  "route": {"name": "QE native interpolation", "electron_phonon": "interpolated", "stages_in_order": ["dense_scf_fit", "coarse_scf", "ph_dfpt", "q2r", "matdyn", "qmap_helper", "lambda_mu016", "lambda_mu010"]},
  "structure": {"formula": "W2N3", "nat": 5, "ntyp": 2, "source": "assets/W2N3-monolayer.poscar", "units": "angstrom", "c_angstrom": 25.15},
  "cutoffs": {"ecutwfc_ry": 80.0, "ecutrho_ry": 320.0},
  "smearing": {"occupations": "smearing", "degauss_ry": 0.01},
  "k_mesh": {"dense": {"grid": [64, 64, 1], "shift": [0, 0, 0]}, "coarse": {"grid": [16, 16, 1], "shift": [0, 0, 0]}},
  "q_mesh": {"grid": [4, 4, 1], "shift": [0, 0, 0]},
  "data_flow": [{"stage": "dense_scf_fit", "program": "pw.x", "input": "scf.in", "reads": "...", "writes": ["..."], "note": "..."}],
  "q_file_mapping": {"method": "dynamic q-header mapping", "units_in_ph_header": "tpiba", "fail_closed_conditions": ["..."], "on_failure": "..."},
  "cost_estimate_core_hours": {"stages": {"dense_scf_fit": 140.0, "coarse_scf": 10.0, "ph_dfpt": 32.0, "q2r": 0.5, "matdyn": 1.5, "lambda_mu016": 1.0, "lambda_mu010": 1.0, "qmap_helper": 0.1}, "total": 186.1, "phonon_dfpt_core_hours": 32.0, "phonon_dfpt_plus_postproc_core_hours": 36.1, "budget_core_hours": 300.0, "phonon_budget_core_hours": 40.0, "basis": "Planning estimates only; no benchmark was run."},
  "precision_vs_paper": {"paper": {}, "this_work": {}, "tradeoff": "...", "error_direction": "...", "cutoff_smearing": "..."},
  "assumptions_and_caveats": ["..."],
  "deliverables": ["scf.in", "coarse_scf.in", "ph.in", "q2r.in", "matdyn.in", "make-lambda-input.py", "run.sh", "plan.json"]
}
```

For either layout, keep QE target at 7.2, grids at the task values, and the correct units in field names. The estimate entries must be positive finite numbers, sum exactly to `total` within 1e-6 core-hours, and stay within total 300 and DFPT 40 core-hours. Cost text must say the values are planning estimates, not measured benchmarks.

State uncertainty in the rationale for dense k, coarse k, q interpolation and smearing. Use ordinary English or Chinese wording; do not copy a required sentence. Existing expanded-layout prose remains an accepted representation; a typed `uncertainty` object is optional and can use `dense_k_status`/`dense_k_note`, `coarse_q_status`/`coarse_q_note`, `interpolation_status`/`interpolation_note`, and `smearing_status`/`smearing_note`. If present, each status must be a recognized unknown/unresolved value and each note must explain an unmeasured limitation. Do not use a typed status to contradict the prose. Unknown status or wording does not excuse a definite directional or no-added-error assertion in the same note or another rationale field; qualify the assertion itself (for example, “it is not established that the mesh underestimates lambda”). A directional error claim or claim of no added error needs actual validation evidence; otherwise leave it unresolved.
