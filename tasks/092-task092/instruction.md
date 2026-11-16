# Task: Analyze differential capacitance and Parsons–Zobel concentration trends

## Background

The supplied `reference_sweeps.csv`, `curve_refinement.csv`, and `analysis_contract.json` are the complete public data contract for source-generated Poisson–Fermi double-layer sweeps. The model uses T=300 K, alpha=0.5, cell length 0.8 nm, and the published kernel coefficients in the manifest. Concentration is in mM (numerically mol/m³ for number density), `Pbar_C_m2` and `sigma0_C_m2` in C/m², `phi0_V` in V.

Each branch is a fixed-concentration, fixed-`Pbar` profile family: 20 public branches (concentrations 1, 2, 3, 5, 10 mM × `Pbar` 0, 0.01, 0.02, 0.03 C/m²). The source solved `sigma0=0` first, then continued the positive and negative arms independently. Preserve branch identity — never combine rows from different concentrations or `Pbar` values — and never sort a branch by `phi0`.

## Task

Build a reusable, branch-aware analysis program that computes the differential-capacitance curves and Parsons–Zobel (PZ) concentration diagnostics from the sweeps. This task is about numerical analysis and regression on supplied data; the double-layer BVP itself is not re-solved.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- `final/analyze.py`, runnable as

  `python3 /app/final/analyze.py --input /app/assets/reference_sweeps.csv --refinement /app/assets/curve_refinement.csv --manifest /app/assets/analysis_contract.json --out /app/final`

  conforming exactly to the output keys, CSV columns, units, enums, and log schema in `analysis_contract.json`.
- Reference capacitance: the Gouy–Chapman `C_GC` uses the supplied kernel's zero-wavenumber value, `eps_b = 1 + 1/K11 + 1/K21` (≈70.998) — it is part of the fixed model input, not a free physical choice, so the water value 78.3 is not used. Report `eps_b` in `analysis.json` accordingly.
- Physical capacitance curve: for each branch, `curve_refinement.csv` supplies real BVP potentials at offsets -2h, -h, 0, +h, +2h for three five-point derivative levels (h = 5e-4, 2.5e-4, 1.25e-4 C/m²). Report the signed `d_sigma0/d_phi0` (reciprocal of the five-point `d_phi0/d_sigma0`) and its absolute value C at every level, the successive capacitance and derivative changes, a sign-consistency flag, and the coarse-grid estimate's relative bias against the finest level. Label each point `unresolved` if signs disagree across levels or the numerical interval `[d3-2|d3-d2|, d3+2|d3-d2|]` contains zero, `ill_conditioned` if `|C_h3-C_h2|/C_h3 > 0.01`, otherwise `resolved`. These are reported numerical diagnostics, not proofs of convergence or stability.
- PZ analysis: for each fixed `Pbar`, the unweighted least-squares line over the five declared concentrations with `x=1/C_GC(phi0=0)`, `y=1/C_model(sigma0=0)`; plus the diagnostic fit using `x=1/C_GC(phi_pzc_model)`, five leave-one-concentration-out fits, and the two adjacent four-concentration windows declared in the manifest. The supplied source’s printed Figure 8 slopes provide provenance; calculate and report the fits from the supplied data and declared manifest windows.
- Validate the input (complete, finite, correct units, no mixed branches) rather than silently filling or reordering it.
- Write `final/capacitance_curves.csv` (one row per branch and coarse center), `final/parsons_zobel.csv` (all concentration points and fit summaries), `final/analysis.json` (complete branch/fit diagnostics), and `final/solver.log` (a compact successful-analysis record).

Validate the declared inputs before analysis. The submitted public-data results and the program’s results on valid off-grid sweeps are compared with an independent implementation.

### Input and deliverable details

- Inputs: `/app/assets/reference_sweeps.csv`, `/app/assets/curve_refinement.csv`, `/app/assets/analysis_contract.json`
- Outputs: `final/analyze.py`, `final/capacitance_curves.csv`, `final/parsons_zobel.csv`, `final/analysis.json`, `final/solver.log`

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/reference_sweeps.csv` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/assets/curve_refinement.csv` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/assets/analysis_contract.json` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
