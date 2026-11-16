# Task: Static mechanics of an archived silicon snapshot

## Background

The inputs contain a periodic 216-atom silicon snapshot and two frozen neural-network biases. Determine their static mechanics. Native execution records are unavailable as inputs, so conclusions are limited to the supplied models and snapshot; they cannot establish new dynamics, equilibrium sampling, phase change, or agreement with unseen records.

## Task

Implement `/app/final/evaluate.py --snapshot PATH --models PATH --output PATH` and generate `/app/final/result.json`. Compute from the received files, retaining atom identities when snapshot rows are reordered and responding to changed model parameters. Do not launch LAMMPS, PLUMED, simulations, or scheduler jobs.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

For each model, use `V(q)=b2+Σi w2[i] tanh(w1[i]*(q−input_center)/input_scale+b1[i])` with eight hidden units. Coordinates and cell are in Å; energy/virial in eV and forces in eV/Å.

For each atom i use minimum-image `r_ij=x_j−x_i`, excluding self. Set sigma=0.4 Å, lambda=100, a=5.431 Å/4, R0=0.5 and rc=max_t|t|+3sigma. Templates are `T1={(a,a,a),(−a,−a,a),(a,−a,−a),(−a,a,−a)}` and `T2={(a,−a,a),(−a,a,a),(a,a,−a),(−a,−a,−a)}`. For neighbors inside rc, compute `k_im=(1/4)Σj,t exp(−|r_ij−t|²/(4sigma²))`, `s_i=log(Σm exp(lambda*k_im))/lambda` without subtracting log 2, and `Q=Σi (s_i/R0)^12/[1+(s_i/R0)^12]`. Q is dimensionless. Compute gain dV/dQ and force `F=−(dV/dQ)∂Q/∂x`.

Report the full, unsymmetrized affine virial `W_ab=−dV/d(epsilon_ab)`: transform row-vector coordinates and the cell by `x'=xF^T`, keeping templates fixed in the laboratory frame. Check coordinate and strain derivatives with h=1e-4. Q/energy/gain tolerances are atol=rtol=1e-11; forces, virial and finite-difference diagnostics use atol=2e-9. Report the summed net force; every component must have magnitude ≤2e-8 eV/Å.

### Input and deliverable details

Inputs are `/app/environment/assets/snapshot.data` and `models.json`. Deliver the program and generated JSON under `/app/final/`.

The result contains `atoms` (integer count), `cell_A` (3×3), and `models` in the input model order. Each model record uses exactly these calculated fields: `model_id`, `Q`, `bias_energy_eV`, `dVdQ_eV_per_Q`, `force_eV_per_A_atom_id_order` (216×3, IDs 1–216), `virial_eV_row_a_column_b` (3×3), and `diagnostics`. Optional metadata can be omitted; additional descriptive fields belong only at the JSON root.

`diagnostics` contains `net_force_eV_per_A` (three components), `coordinate_probes` for atom IDs 1,54,109 and each axis 0,1,2, and `strain_probes` for all nine ordered axis pairs. Coordinate records use `{atom_id,axis,analytic_force_eV_per_A,finite_difference_eV_per_A}`; strain records use `{a,b,analytic_W_eV,finite_difference_W_eV}`. Indices are integers and calculated values are finite numbers, not booleans.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/snapshot.data` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
