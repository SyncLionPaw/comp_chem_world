# Task: Archived Ala2 NN-VES checkpoint reconstruction

## Background

Reconstruct the archived static NN-VES checkpoint and evaluate its mathematical outputs on the finite historical record. The checkpoint was forcibly frozen at the recorded endpoint; this is not evidence of intrinsic convergence. Do not claim new sampling, retraining, FES accuracy, or general method advantage.

## Task

Implement `/app/submission.py` with `forward_and_grad(angles, checkpoint)`, `frame_force(coords_nm, box_nm, checkpoint)`, and `analyze(train, ves, control, contract)`. Compute each result from its arguments, including altered checkpoints, frames, and analysis parameters; do not replay memorized outputs.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- The network input is `[sin(phi),sin(psi),cos(phi),cos(psi)]` (radians); layers are 4→48→24→12→1, ReLU after the first three, scalar bias in kJ/mol. The checkpoint has exactly `layers`, an ordered list of four `{weight,bias}` entries; source tensors are little-endian float32 arrays in order `fc1.weight`, `fc1.bias`, `fc2.weight`, `fc2.bias`, `fc3.weight`, `fc3.bias`, `out.weight`, `out.bias`, with shapes `(48,4),(48,),(24,48),(24,),(12,24),(12,),(1,12),(1,)`. ReLU derivative at zero is zero. Parse Torch ZIP tensor payloads safely; never execute arbitrary pickle code.
- Each frame has 22 atoms; coordinates and orthorhombic box lengths are nm, forces kJ mol⁻¹ nm⁻¹. Compute phi from 1-based atoms `[5,7,9,15]`, psi from `[7,9,15,17]`, applying minimum-image displacement to each consecutive torsion bond. For archived step zero, original TRR float32 coordinates are canonical; CSV coordinate sidecars give rounded decimal intervals for checking them.
- All three APIs return Python dictionaries (JSON objects) at the top level, not tuples or lists. `forward_and_grad` accepts two finite angles and the checkpoint. Wrap angles to `[-π,π)`. Return exactly finite `bias_kj_mol`, `dV_dphi_kj_mol_rad`, `dV_dpsi_kj_mol_rad`. `frame_force` accepts finite 22×3 coordinates and three positive box lengths; return exactly `phi_rad`, `psi_rad`, `bias_kj_mol`, `force_kj_mol_nm` (22×3), where force is the negative Cartesian derivative through both torsions. `analyze` returns the specified nested-dictionary analysis tree.
- `analyze` receives ordered row lists for `train`, `ves`, `control`; each row has integer `step`, finite `time_ps`, `phi_rad`, `psi_rad`, and, when available, `bias_kj_mol`. `contract` supplies `dt_ps`, `stride_steps`, `required_rows_per_arm`, `core_radius_rad`, `minimum_consecutive_samples`, `cores_rad`, `checkpoint_iteration`, `forced_freeze_step`, `forced_freeze_time_ps`, `static_window_start_step`, and `static_window_end_step` (inclusive), `temperature_K`, `gas_constant_kj_mol_k_K`, `native_terminal_status/native_science_pass` read from the archived terminal record. Use supplied values, not instance constants. Historical cadence is 0.002 ps/step and 0.04 ps/sample (20 steps); each arm has 37,501 ordered rows spanning 750,000 steps.
- Locked periodic core centers (radians): `b1=(-1.3823,1.0053)`, `b2=(-2.5133,2.7646)`, `b3=(-1.508,2.2619)`, `b4=(1.131,-0.754)`. A sample is inside a core when the periodic-coordinate distance `hypot(wrap(Δphi),wrap(Δpsi))` is ≤ `core_radius_rad`. Count a visit after `minimum_consecutive_samples` consecutive rows in one core; leaving or switching cores resets the streak. Count a transition only when a newly qualified core differs from the previous qualified core; use the completing row's step and preserve input order.
- Reweight only static VES rows: `logw=+beta*V`, `beta=1/(R*T)` from supplied constants, globally normalized with stable log-sum-exp. Exclude training rows because their model changed. Compute raw Kish ESS on the inclusive static window; it is an importance-support diagnostic, not time-corrected ESS or an FES. Read terminal status and science flag from the terminal record.
- Return exactly this analysis tree; `?` marks optional descriptive strings:

```text
{
 freeze:{checkpoint_iteration:int,forced_freeze_step:int,forced_freeze_time_ps:number,convergence_claim:false},
 static_window:{arm:"ves",first_step:int,last_step:int,rows:int,checkpoint_iteration:int},
 arms:{train|ves|control:{rows:int,first_step:int,last_step:int,core_visits:{b1:int,b2:int,b3:int,b4:int},qualified_intercore_transitions:[{from:string,to:string,step:int}]}},
 static_ves_reweighting:{temperature_K:number,gas_constant_kJ_mol_K:number,beta_mol_per_kJ:number,log_weight_convention?:string,log_normalizer:number,normalized_weight_sum:number,core_mass:{b1:number,b2:number,b3:number,b4:number},raw_kish_ess_by_core:{b1:number,b2:number,b3:number,b4:number},raw_kish_ess_global:number,qualification?:string,limitations?:string},
 common_support:{cores_with_positive_weighted_ves_mass_and_control_visits:[string],qualification?:string},
 evidence_limits:{native_terminal_status:string,native_science_pass:boolean,fes_status?:string,time_corrected_ess_status?:string,scope?:string}
}
```

  The seven optional strings are descriptive metadata. Copy the terminal record's status and Boolean science flag; the latter is not an independent scientific pass. Other keys, values, shapes, and numeric/Boolean types are required exactly; numeric fields must be finite JSON numbers, never booleans.
- Raise `ValueError` for malformed shapes, nonfinite values, invalid row cadence/order, or an empty/reversed static window. Compare using absolute tolerances only (`rtol=0`): energy 1e-8 kJ/mol, angular derivatives 2e-7 kJ mol⁻¹ rad⁻¹, Cartesian forces 2e-7 kJ mol⁻¹ nm⁻¹, wrapped frame angles 1e-10 rad, and analysis numeric fields 2e-8. Use Python standard library and NumPy 2.2.6.

### Input and deliverable details

Checkpoint, TRR frames, trajectories, and public source code are under `environment/assets/`. The only required artifact is `/app/submission.py`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `environment/assets/` | Directory of supplied inputs and resources. |

Submit `/app/submission.py`. Use the interface and output conventions above.
