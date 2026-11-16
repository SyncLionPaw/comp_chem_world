# Task: Crack-tip hydrogen occupation and fracture free energy

## Background

The inputs combine published absorption parameters, elastic constants, digitized fracture energies and a registered FCC crack-column geometry. The absorption formula and caption admit different width interpretations. The fracture-energy anchor temperature is unspecified; separating its energetic and entropic contributions therefore requires a conditional reference.

## Task

Predict stress-driven crack-tip hydrogen occupation and conditional fracture free energy, distinguishing cleavage and dislocation-emission coverages and assessing nanoscale diffusion, entropy and temperature effects.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Solve bulk chemical-potential closure and site occupations in the registered 12-column model. Use Hill-isotropic Poisson ratio, tensile driving pressure, ΔV=2.8 Å³ and consistent pressure-energy units. Use C_cleave=mean(c_1…c_9), C_emit=mean(c_10…c_12), and the registered saturated nanoscale-diffusion model C_S=min(1,1.5*C_cleave).
- Retain both printed-scale and caption-standard-deviation interpretations. Analyze all six alloys at 5800 appm/300 K, and SS304 at 2600 appm/300 K and 4000 appm/300 and 400 K; use Kapp=0…1.2 MPa√m in 0.1 steps.
- Infer the conditional energetic reference from the 5800 appm fracture anchors at assumed Tref=300 K, subtracting configurational entropy, then interpolate linearly between coverage anchors. Hold this energy family fixed when comparing other conditions. Restore entropy consistently, including 0 ln 0 endpoints, and propagate the ±0.05 J/m² image interval.
- Check zero-stress bulk closure, common-reference-shift invariance and occupation bounds. Compare source observations without fitting away disagreement. At SS304, Kapp=0.6/0.8 and both widths, assess Voigt/Reuss elastic closures, ΔV=2.7/2.9 Å³ and origin offsets ±0.1 column spacing against baseline.
- Report numerical refinement separately from source/model uncertainty. The inferred energetic term is dependent on the fracture anchors, not independent surface-energy evidence; do not claim absolute chemical potential or a fully validated macroscopic prediction.
- For origin-offset sensitivities, either interpret the signed parameter as an origin displacement or as a relative-coordinate shift; describe and use one sign convention consistently across the complete sensitivity set.
- Compare the calculated site occupations point-by-point with Fig. 1(b) reading intervals and interpret the SS304 temperature comparison.

- With n(x)=exp(−x²)/sqrt(pi), eta=mu−Ebar−EZP and f(y)=1/(1+exp(y/(kB*T))), use the same energy distribution in Cb=integral n(x)f(sigma*x−eta)dx and c_i=integral n(x)f(sigma*x−p_i*DeltaV−eta)dx; thus c_i=Cb at zero stress. Define C_cleave=mean(c1…c9), C_emit=mean(c10…c12), C_S=min(1,1.5*C_cleave).

### Input and deliverable details

Use the parameter, coordinate and source-comparison tables under `/app/assets/`. Create `/app/final/` and submit the following scientific outputs, executable `calculation_source.py` and `run_metadata.json`.

- `occupation.csv` (2808 rows) and `fracture_free_energy.csv` (234 rows) share the keys `condition,alloy,Cb_fraction,T_K,Kapp_MPa_sqrt_m,width_interpretation` and quantities `eta_eV_mu_minus_Ebar_minus_EZP,C_cleave,C_emit,C_S`. The occupation table adds `site_column,c_i`. The free-energy table adds `Cb_recomputed,nu_hill,DeltaV_A3,A0_A2,gamma_E_J_m2,gamma_E_low_J_m2,gamma_E_high_J_m2,gamma_S_J_m2,gamma_F_J_m2,gamma_F_low_J_m2,gamma_F_high_J_m2`. Use width IDs `printed_formula_scale,caption_standard_deviation` and any four consistent condition labels.
- `thermodynamic_model.json` records `width_interpretations` (the two named multipliers 1 and sqrt(2)), `DeltaV_A3`, `gamma_E_condition`, `conditional_assumptions` and `sensitivity_summary`. Use a reference object `{status:"conditional",reference_temperature_status:"assumed",reference_Cb_fraction:0.0058,reference_temperature_K:300,image_half_width_J_m2:0.05}`. Explain at least three conditional assumptions, the density/pressure model and elastic closure in your own words; no fixed prose formula or source-label wording is required.
- Place the 28 sensitivity records in `sensitivity_summary.one_at_a_time_model_sensitivity`: each has `width,Kapp,variant,parameters={DeltaV_A3,origin_delta_over_dx},coverages={C_cleave,C_emit,C_S}`. Variant IDs are `baseline,nu_Voigt,nu_Reuss,DeltaV_2.7,DeltaV_2.9,origin_-0.1,origin_0.1`.
- `limiting_checks.json` records `maximum_bulk_concentration_residual,maximum_common_reference_shift_eta_residual_eV,site_occupancy_bounds` (minimum/maximum pair) and `gamma_S_endpoint_checks` (per-alloy `gamma_S_cs0_J_m2,gamma_S_cs1_J_m2`). `mechanism.md` interprets the occupations, source comparisons, temperature response and limitations.

Use UTF-8 tables and JSON arrays for interval cells. The run record uses `schema="compchemworld-calculation-run/v1"`, `calculation_sources=[{name,sha256}]`, `inputs={asset_basename:hash}`, `outputs={relative_output_path:hash}`, `python` and `execution_context`; list every input and every final file except the record itself. Hashes identify actual file bytes; bare hex or `sha256:` prefixes are accepted for the run record.

`python` may be a nonempty version string or `{version:...}`; `execution_context` may be a nonempty description or object.

Use absolute comparison tolerance 2e−7 for ordinary numerical values. The bulk residual must not exceed 2e−10 and the reference-shift residual must not exceed 1e−9.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
