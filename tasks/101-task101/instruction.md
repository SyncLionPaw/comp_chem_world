# Task: Pressure-dependent Γ-point phonons in MoS₂

## Background

Reproduce the signed Γ-point phonons of fixed MoS₂ structures at 0, 3, 6 and 9 GPa, and track the Raman-active E₂g², E₂g¹ and A₁g branches. The route is VASP 6.4.1, PAW-PBE, PBE+D3 (`IVDW=11`), 500 eV, Γ-centered 12×12×1, `EDIFF≤1e−10 eV`, `IBRION=6`, `ISIF=3`, `POTIM=0.015 Å`, `NFREE=2`, and `KPAR=4`; set `PSTRESS=0/30/60/90 kbar`, respectively. Keep supplied geometries fixed.

## Task

Calculate all 18 signed Γ modes at each pressure, track the Raman branches, fit their four-point pressure coefficients, quantify initial pressure/force state and one single-variable convergence control, and provide native calculation/execution evidence.

## Requirements

If using HPC, follow the `ikkem-slurm` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

Use pressure-matched structures and input mapping in `/app/assets`; do not relax structures. Run at least one 0-GPa single-variable cutoff or `kz` control. Every finite-displacement electronic step must reach its declared EDIFF without reaching NELM. Follow `/app/verification.md` for branch tracking, pressure residuals, fields, tolerances and evidence.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Pressure-matched structures, VASP inputs and potential provenance. |
| `/app/verification.md` | Methods and output specification. |

Inputs: `/app/assets/POSCAR_*`, `/app/assets/INCAR_*`, `/app/assets/KPOINTS_*`, `/app/assets/pressure_deck_map.md`, and `/app/assets/pseudos/README.md`. Submit `/app/final/phonons.json`, `raman_modes.json`, `pressure_state.md`, `convergence.md` and `engine_io/` under the public contract. Do not submit POTCAR bytes.
