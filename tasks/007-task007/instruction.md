# Hydrogen site preference and magnetic sensitivity in CoCrFeNi

## Background

The input is one fixed-geometry, equiatomic CoCrFeNi periodic cell with 32 metal atoms. Local chemistry and magnetic initialization can affect H interstitial electronic energies; this cell is not a random-alloy ensemble.

## Task

Before examining results, choose two octahedral sites with different first-shell compositions. Run three matched A/B pairs—baseline, numerical sensitivity and alternate magnetic initialization—to test for a conditional electronic-energy preference.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `ikkem-slurm` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

- Reconstruct the cell and complete octahedral-site inventory; verify periodic multiplicity, six-neighbor distances and element counts. Record chosen sites, coordinates and rationale before results.
- Complete exactly six fixed-geometry, collinear spin-polarized PBE/PAW static VASP calculations with the same potentials. Within each A/B pair, physical inputs match; baseline and numerical-sensitivity starts also match magnetically. No hybrid, +U, SOC or meta-GGA.
- Use native VASP inputs/outputs, execution records and local moments to establish electronic convergence before the SCF limit, normal termination, consistent OUTCAR/OSZICAR/XML energies, finite sigma-to-zero energies and highest-band occupation <1e-3. Forces are diagnostic; incomplete/invalid pairs do not support the complete study.
- For all three pairs calculate Δ=E_A−E_B. A conditional direction requires all three Δ to have the same nonzero sign and strictly `min(|Δ|)>|Δ_numerical−Δ_baseline|+0.0082 eV`; otherwise report the preference as unresolved. The added scale is exploratory, not an error bar or confidence interval. If an alternate start also changes solver/physical input, interpret it as a joint response. Do not infer magnetic ground state, thermodynamic occupancy, relaxed absorption enthalpy, fracture behavior or random-alloy representativeness.
- Follow the attempt deadline and distinguish fresh runs from authenticated historical records. Preserve software and PAW dataset identities and use licensed datasets in accordance with their terms.
- Stay within: ENCUT 350–800 eV; NBANDS 256–512; EDIFF 1e-8–1e-3 eV; SIGMA 0.01–0.3 eV; NELM 80–400; AMIX 0.01–0.8; AMIX_MAG 0.01–1; BMIX/BMIX_MAG 1e-5–0.1; ISMEAR −5/0/1; PREC Normal/Accurate; ALGO Normal/All/Fast; optional MAXMIX 4–20; each k-grid axis 2–12 and `NBANDS×kx×ky×kz≤100000`. These bounds do not prescribe energy differences or site choice.
- Follow the public submission schema linked below and retain native calculation and execution evidence.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Alloy data, source records and task conventions. |

Read `/app/assets/task07-scientific-claims.schema.json` for the submission format and `/run/compchembench/task7-facts.json` for the attempt deadline.

| Path | Contents |
| --- | --- |
| `/app/final/` | Two hydrogen structures, the full site inventory, three paired calculation records and the pre-result site choice, scientific claims, native inputs and outputs, execution records, receipts and the evidence index. |
