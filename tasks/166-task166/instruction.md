# Multistate CASSCF properties at two ethylene geometries

## Background

Two fixed ethylene geometries are supplied: A is planar (C=C 2.0500 Bohr, dihedral 0°); B is twisted and stretched (C=C 2.5000 Bohr, dihedral 90°). File coordinates are in Å. The specified method is equal-weight SA(3)-CASSCF(2,2)/cc-pVDZ; historical orbital choices and state-tracking records are unavailable.

## Task

Calculate and cross-check the three lowest singlet-state properties at both geometries, including state gradients and the S0/S1 nonadiabatic coupling. Assess convergence, active-orbital choices, root tracking and unit conventions.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include h5py, NumPy, PySCF, SciPy. Do not install additional packages or fetch dependencies from the network.

- Keep both geometries fixed and use neutral singlet SA(3)-CASSCF(2,2)/cc-pVDZ with weights 1/3 per root, seven inactive orbitals and a C=C π/π* active space. Select and verify the actual active orbitals rather than inferring them from expected results.
- Calculate C01 (S0/S1) and its Frobenius norm, which is invariant to arbitrary coupling phase. Do not confuse it with C12 (S1/S2); C12 is not required.
- Use the supplied CPU PySCF execution target; record the interpreter, software version and actual resource configuration. Before calculation, register the runtime request and submit the A/B operation using the supplied interface within the 1,200 s task budget. Do not submit remote jobs.
- Declare SCF/CASSCF convergence criteria, retain iteration histories and failure diagnostics, and check for root flipping. Report unresolved calculations honestly; summary statements do not establish convergence. Preserve the inputs, execution script, native outputs and exit status needed to reproduce and verify both calculations.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Two fixed ethene geometries, reference calculation specification and output contract. |

Inputs are `/app/inputs/geometries/ethene_grid_A.xyz`, `ethene_grid_B.xyz`, `/app/inputs/casscf_reference_spec.md` and `/app/inputs/output-contract.md`. The last two files define scientific conventions, execution interface, units, numerical tolerances and result formats.

Write `/app/outputs/runtime-request.json` before execution. Submit all three roots' results at both points, C01 norms and convergence analysis in the specified files under `/app/outputs/`, including `summary.json` linking to nonempty raw outputs. Preserve collected execution evidence under `/app/bench25-artifacts/`.
