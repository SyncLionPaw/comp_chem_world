# Generate and validate GaAs first-principles inputs for carrier-scattering calculations

## Background

First-principles scattering calculations require electronic, elastic, dielectric, polar-optical-phonon, and deformation-potential parameters derived from crystal structures. The supplied GaAs structure and methodological context are for this task; the context material is not a numerical answer and does not prescribe a unique computational route.

## Task

Using the supplied GaAs input, produce parameters for carrier-scattering research, convergence comparisons, and verifiable native computational evidence. Use the task's fresh VASP/PBE workflow and explain the approximations and their scope.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, NetworkX, NumPy, pandas, pymatgen, SciPy, spglib, sympy. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `hpc` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

- Report the fundamental and direct band gaps, elastic stiffnesses, clamped-ion (electronic) and ion-inclusive dielectric tensors, long-wavelength effective POP frequencies, and deformation responses of conduction-band electrons and valence-band holes. State units, structure, energy reference, strain convention, and sources.
- Compare each reported quantity across at least two comparable settings and give the differences. State the unscissored band gap and occupations used for response calculations; do not use the HSE06 gap to conceal metallic PBE response. For degenerate hole states, provide the complete subspace response or an equivalent symmetry invariant.
- Preserve actual inputs, structures, native outputs, and execution provenance so they can be independently checked. Do not fabricate logs or substitute published values for this run. Do not include credentials or pseudopotential text restricted by license in submitted materials.
- Use VASP/PBE with compatible PAW metadata for the native evidence. This is the route supported by the current verifier.
- Use only inputs declared for this task and resources authorized by the host execution profile. Public inputs are in `/app/assets/`; `methods-context.md` is background only. Follow that profile for compute limits.
- Choose an authorized site and suitable resources. The optional helper at `/app/assets/public/prepare_hpc_route.py` can discover available routes and inspect VASP and POTCAR metadata.
- Use only authorized software and potential files. A remote job may temporarily stage POTCAR files for VASP, but do not display or download their licensed text locally or include it, credentials, or identity details in submitted materials; record allowed metadata and hashes, and report if no authorized setup is available.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Public calculation inputs and method context |
| `/app/assets/public/output-contract.md` | Public submission contract |

The public contract defines fields, units, and native evidence formats.Submit only the four items listed below.

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/parameters.json` | Calculation parameters |
| `/app/final/native/` | Native calculation evidence |
| `/app/final/convergence.json` | Convergence analysis |
| `/app/final/report.md` | Scientific report |
