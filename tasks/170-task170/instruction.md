# Task: Plan a QE 7.2 electron–phonon input chain

## Background

This is static input design; no Quantum ESPRESSO run is requested. The comparison protocol used denser grids
(192×192×1 k, 96×96×1 q). Read `assets/computational-brief.md` and use
`assets/W2N3-monolayer.poscar` as the fixed starting geometry (five-atom W₂N₃, a=2.9131 Å, P-6m2).

## Task

Create a coherent native QE 7.2 interpolation chain, an auditable cost plan, and a helper that
derives irreducible q weights from the actual PH lambda-file q headers. Provide both μ*
post-processing inputs. Plan estimates are not measured performance.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use a 64×64×1 **unshifted** dense SCF fit with `la2F=.true.`, 16×16×1 coarse SCF, and unshifted 4×4×1 q mesh. SCF decks share prefix, outdir, cell, and ordered coordinates; both use `ATOMIC_POSITIONS (crystal)` and are periodically equivalent to the supplied POSCAR within 0.001 Å per atom and 0.001 Å per cell vector. Keep symmetry enabled in the coarse SCF. Set `ecutwfc≥60 Ry`, smearing occupations, and `degauss=0.005–0.02 Ry`; geometry has vacuum≥15 Å and c≥20 Å. Use QE 7.2 `electron_phonon='interpolated'`; `ph.in` declares `fildvscf` and `fildyn`. `q2r.in` enables `la2F`, reads the same `fildyn` declared by PH, and writes `flfrc`; `matdyn.in` enables `la2F` and DOS, declares `fldos`, uses positive integer `nk1`, `nk2`, `nk3`, and reads the same `flfrc`. Run two lambda.x postprocessings. `make-lambda-input.py` derives full-grid spglib orbit multiplicities and maps actual PH lambda-file headers from QE `tpiba` (Cartesian 2π/alat) to reciprocal crystal coordinates; it fails closed on missing/duplicate points or total weight ≠16, then writes standard stdin files for μ*=0.16/0.10. `run.sh` order: dense SCF fit → coarse SCF → ph.x → q2r.x → matdyn.x → mapping helper → lambda.x twice. Only after PH files exist may the helper write lambda inputs. Do not claim QE execution, measured feasibility, realized error, convergence, or error direction without evidence. Discuss dense-k, coarse-k, q interpolation, and smearing uncertainty as unresolved; do not assert an error direction or no added error. Plan total≤300 core-hours and DFPT≤40; estimates are planning values, each component positive and finite, summing to total.

### Input and deliverable details

Deliver under `/app/final/`: `scf.in`, `coarse_scf.in`, `ph.in`, `q2r.in`, `matdyn.in`,
`make-lambda-input.py`, `run.sh`, `plan.json`. Use one complete **compact** `plan.json` format
(expanded layout remains accepted): `route`=`qe_native`; `qe_target`=`QE 7.2`; ordered
`execution_order` array `dense_scf_fit, coarse_scf, ph, q2r, matdyn_a2f, lambda_postprocess`;
`structure` object with numeric `n_atoms` and `cell_height_z_A`; `cutoffs.ecutwfc_ry` number;
`smearing` with `occupations` string and `degauss_ry` number; `grids` with integer arrays
`dense_scf_k`, `coarse_scf_k`, `q`; `estimated_core_hours` object with positive finite numbers
`dense_scf`, `coarse_scf`, `ph`, `post`, `total` (total equals components within 1e-6); string
`estimate_basis` that says these are planning estimates, not benchmarked; `justifications` object
with text for `dense_scf_k`, `coarse_scf_k`, `q`, `degauss`, explaining tradeoffs and uncertainty
without an asserted error direction. Include cutoff/smearing choices, execution/data flow and
budget/accuracy caveats. The deliverables are judged statically; placeholder pseudopotentials
require licensed compatible files before production.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `assets/computational-brief.md` | Supplied data, parameters or method documentation; see the task requirements. |
| `assets/W2N3-monolayer.poscar` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
