## Background

**Task: Wolfe–Quapp static variational-bias optimization**

The supplied inputs define the rotated two-dimensional, fourth-order Wolfe–Quapp potential in natural units (T=1, friction=10) on x,y∈[-3,3]. This is static optimization; do not run molecular dynamics.


## Task

For beta=1 and well-tempered gamma=10, compute a bias for p_target(x,y) ∝ exp[-U(x,y)/gamma] on [-3,3]^2, minimizing Omega[V]=E_target[V]+log ∫ exp[-(U+V)] dx dy. Biases differing by an additive constant are equivalent. Use either an analytic certificate or numerical optimization.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

- Write the six artifacts directly under /app/: bias-grid.csv, bias_model.py, optimization-trace.csv, report.md, method-evidence.json, and solve.py. The grid has exactly one row per point of the closed, uniform 61×61 grid and columns x,y,bias_kBT. bias_model.py exports evaluate(x,y)->scalar_kBT and gradient(x,y)->(dV/dx,dV/dy); the numeric route also exports evaluate_theta(x,y,theta) and parameter_gradient(x,y,theta) for its monomial basis.
- method-evidence.json must include the required scientific members route, physics, representation, integration, and stop, plus a route-specific certificate (analytic) or solver (numeric). Descriptive top-level metadata may be included, but does not replace or change these required scientific members. Require physics={beta:1,gamma:10,domain:[[-3,3],[-3,3]]}; representation={basis:monomial,parameter_order:1–64 unique integer exponent pairs in [0,8]²,scales:[3,3]}, with phi_ij=(x/3)^i(y/3)^j; integration={rule:tensor_trapezoid,resolution:61–181,refinement_resolution:larger and ≤241}; and stop with criterion gradient_norm or relative_objective_change, positive finite tolerance ≤1e-5, and a nonempty scientific explanation in reason.
- Analytic route: certificate.coefficients is keyed by strings "i,j" and covers all 25 c_ij for i,j∈{0,…,4} in the unscaled polynomial V=Σc_ij x^i y^j; gauge_constant=c_00. Establish stationarity and global minimality of Omega. Do not include a numeric solver.
- Numeric route: solver declares entrypoint=solve.py, uint32 seed, initial_theta, config (method/options, optional polish method/options), and challenge.scale∈[0.02,0.2]. Every maxiter is an integer in [1,1500]. solve.py exports optimize(objective_gradient,initial_theta,config)->states, where objective_gradient returns (objective,gradient). Return 2–2000 numeric states, starting at initial_theta, with consecutive zero-based iteration and bias_version and adjacent Euclidean parameter_step_norm (first is zero). Run independent replays from initial_theta and a nearby challenge-perturbed value; both terminal gradient norms must be ≤max(1e-5,10*tolerance). The trace must also meet the selected stop: gradient_norm≤tolerance, or abs(ΔOmega)/max(1,abs(Omega_previous),abs(Omega_current))≤1.01*tolerance and final gradient_norm≤max(1e-5,10*tolerance). Exhausting maxiter is not convergence. For SciPy L-BFGS-B/BFGS, gtol is positive and ≤gradient tolerance; with relative-objective stopping, ftol=tolerance.
- Trace columns are iteration,objective,gradient_norm,parameter_step_norm,bias_version,theta_json. Analytic route has one stationarity row with iteration, bias_version, gradient_norm, and parameter_step_norm all zero, theta_json=analytic_stationarity; its objective uses the same functional. Its solve.py is a nonempty UTF-8 note and is not run. Numeric route records actual states. report.md is a nonempty UTF-8 scientific summary of method, objective, representation, quadrature, and limitations; no fixed template.
- Numerical accuracy limits: bias RMSE≤0.05 kBT, target-distribution total variation≤0.02, maximum off-grid bias error≤0.05 kBT, and objective quadrature-refinement difference≤2e-4. Additive constants do not affect distribution checks.

The input coefficients are already in the task coordinate frame. Apply no further rotation.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/md_potential` | Potential coefficients |
| `/app/environment/assets/md_input` | Simulation settings and units |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/bias-grid.csv` | Bias grid |
| `/app/optimization-trace.csv` | Optimization trace |
| `/app/bias_model.py` | Bias model |
| `/app/report.md` | Scientific summary |
| `/app/method-evidence.json` | Method evidence |
| `/app/solve.py` | Solver or analytic-route note |
