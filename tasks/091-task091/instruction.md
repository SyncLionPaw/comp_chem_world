# Task: Solve the coupled Poisson–Fermi double layer

## Background

The public request `/app/assets/edl_request.json` fixes the model: kernel constants `K11=0.140125`, `K12=-0.207118 Å²`, `K13=0.011290 Å⁴`, `K21=0.015908`, `K22=2.003940 Å²`; `T=300 K`, `alpha=0.5`, `a=0.8 nm`, `sigma0=0.1 C/m²`; and eight conditions spanning `c={1,10} mM` × `Pbar={-0.05,0,0.05,0.1} C/m²`. Work in SI with `z` in metres for the equations; profile coordinates are in Å.

With `psi=q phi/(kB T)`, use the lattice-gas closure

```
n+ = nb exp(-psi) / [1 + 2 nb a^3 (cosh(psi)-1)]
n- = nb exp(+psi) / [1 + 2 nb a^3 (cosh(psi)-1)]
```

and solve the coupled equations

```
eps0 phi'' - P1' - P2' + q(n+ - n-) = 0
K11 P1 - K12 P1'' + K13 P1'''' + eps0 phi' = 0
K21 P2 - K22 P2'' + eps0 phi' = 0
```

At the wall impose `P1=(1-alpha)Pbar`, `P2=alpha Pbar`, the natural variational condition `P1''=0`, and `eps0 phi'=Pbar-sigma0`; at the far boundary `phi=P1=P1'=P2=0`. `P1'(0)` is a solved output, never a boundary input. Report `rho1_wall=-P1'(0)` and `rho_total_wall=-(P1'+P2')(0)` in C/m³ — polarization-gradient observables, not surface charge densities.

## Task

Implement a reusable solver and reproduce the requested sharp and roughness-averaged profiles.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- Submit `final/solver.py` (optionally with regular `.py` helpers beside it in `final/`). It must expose `Parameters`, `DoubleLayer(parameters)`, `DoubleLayer.solve(tol=...)`, `DoubleLayer.profile(z_A=...)`, and accept

  `python3 /app/final/solver.py --input /app/request/edl_request.json --output-dir /app/final`

- Off-grid requests must be recomputed from the actual `sigma0`, concentration, and `Pbar` values — never selected from a stored table by `run_id`. Probe ranges are `c=1–10 mM`, `Pbar=-0.05–0.1 C/m²`, `sigma0=0.08–0.12 C/m²`, with T, alpha, a, K fixed. Continue each solution branch from the zero-field baseline; do not switch branches at a fold — refine the step or mesh instead.
- Export both profile tables on the exact grid the request defines: `z` from zero through 12 GC lengths rounded up to a multiple of 10 Å, one row per `z_i=i*0.05 Å`. Internal meshes may be finer. Preserve all input parameters and unit labels in the output metadata.
- Roughness reconstruction: convolve each sharp field independently over `ell>=0` with the normalized Eq. 19 distribution `exp(-((ell-mean)/delta)^2)`, `mean=2.5 Å`, `delta=1.5 Å` (standard deviation `delta/sqrt(2)`). Average `n+` and `n-` separately — the closure is nonlinear, so never recompute them from averaged `phi` — and average derivative columns as averages of the sharp derivatives. Rough densities and occupancy must be nonnegative within roundoff, and occupancy cannot exceed the local liquid fraction.
- Write `final/dl_profiles_sharp.csv`, `final/dl_profiles_smeared.csv` (exact column order and rows per the request's `output_contract`), `final/analysis.json` (required-key schema: BVP convergence, boundaries, integrated charge, occupancy, energy and quadrature convergence, stationarity diagnostics), and `final/solver.log`. Report finite values; do not present a finite perturbation test as proof of a global minimum.

All eight public conditions and every profile point are compared against independently converged references using the request's tolerances, and four off-grid parameter requests are run against the submitted executable; closure, boundaries, charge balance, and occupancy are independently recomputed from the submitted rows.

Budget your time: solving has a 3600 s wall-clock limit. Stage complete deliverables in `final/` as you go because its contents are frozen when the limit expires.

### Input and deliverable details

- Input: `/app/assets/edl_request.json`
- Outputs: `final/solver.py` (plus any helpers), `final/dl_profiles_sharp.csv`, `final/dl_profiles_smeared.csv`, `final/analysis.json`, `final/solver.log`

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/edl_request.json` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
