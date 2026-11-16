# Calculate emitter transition rates

## Background

The supplied inputs cover radiative emission, intersystem crossing (ISC), reverse ISC (RISC), and upward internal conversion (IC), including signed gaps and zero limits.

## Task

Implement a reusable Python kernel that reads `inputs/benchmark.json` and computes rates for every supplied record and array combination.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include h5py, NumPy, PySCF, SciPy. Do not install additional packages or fetch dependencies from the network.

Use SI conversions `E=gap_eV·e`, `μ=dipole_au·e·a0`, `V=soc_cm1·h·c·100`, and `Γ=gamma_cm1·h·c·100`. Compute `kF=E³μ²/[3π ε0 ħ⁴c³]·n_ref(n_ref²+2)²/9`, `L=2V²Γ/[ħ(E²+Γ²)]`, and `q=exp[−|E|/(kB·T_K)]`. For signed gap ≥0, including zero, set `kISC=L` and `kRISC=Lq/3`; for signed gap <0, set `kISC=Lq` and `kRISC=L/3`. For each IC record compute `kIC_up=down_s1·exp[−gap_eV·e/(kB·T_K)]`. The signed branches and factor 1/3 are task conventions.

All rates must be finite, nonnegative, in s⁻¹, and agree with these equations to relative 1e−7 and absolute 1e−12. Reject nonfinite inputs, T≤0, gamma≤0, SOC<0, negative radiative or IC gaps, n_ref≤0, and down_s1≤0; a rejected run exits nonzero without leaving a result. Confirm zero-SOC rates are zero, ISC scales as SOC², and positive-rate rows satisfy signed-gap detailed balance `RISC/ISC=exp[−gap_eV·e/(kB·T_K)]/3`.

Write `final/kernel.py` and `final/result.json`. The result object contains `radiative_s1` (one rate per radiative input, input order), `spin_rows` (the Cartesian product in temperature, signed gap, SOC, broadening order, with `T_K`, `gap_eV`, `soc_cm1`, `gamma_cm1`, `isc_s1`, `risc_s1` in each row), and `ic_up_s1` (one rate per IC input, input order). Read input relative to the application working directory and run unchanged in an application-shaped directory. If providing `final/validation.json`, use its `checks` object for `zero_soc_max_abs_s-1`, `soc_squared_ratio_min`, `soc_squared_ratio_max`, and `detailed_balance_max_relative_error`: the zero-SOC magnitude, high/low positive-SOC ISC ratio range under matched conditions, and maximum relative detailed-balance error. Runtime: 2 CPUs, 2 GiB, 15 minutes; no network access.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/benchmark.json` | Benchmark parameters and calculation conditions. |

Input: `/app/inputs/benchmark.json`. Required outputs: `/app/final/kernel.py` and `/app/final/result.json`.
