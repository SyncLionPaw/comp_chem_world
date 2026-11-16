# Task: Intrinsic cleavage–emission competition in six alloys

## Background

Published elastic, fracture-energy and unstable stacking-fault anchors permit an intrinsic cleavage–emission comparison. At fixed bulk fraction 0.0058 and task temperature 300 K, surface and unstable-fault coverages are independent variables; this is not a crack-tip or macroscopic embrittlement map.

## Task

Construct continuous two-dimensional competition maps for six alloys and quantify exact boundaries, classification areas and robustness to digitization uncertainty and nucleation area.

## Requirements

- Interpolate linearly only between coverage anchors 0/0.5/1 on each independent axis. Evaluate the full 101×101 coverage grid at nucleation areas 30/50/70 Å²; do not collapse to equal coverages or extrapolate.
- Calculate cleavage/emission critical intensities and the lower, central and upper competition functions with consistent J/m² versus mJ/m² conversion. Propagate the fracture-energy ±0.05 J/m² interval and scale physical USF spread from 108 Å² to each nucleation area.
- Determine all boundary edge intersections in every anchor rectangle, omitting nonexistent segments. Compute exact cleavage-robust, emission-robust and uncertain areas, which must partition the unit square.
- Support no-boundary and whole-domain robustness conclusions with extrema and their locations over the nine anchor combinations. Use any mathematically equivalent method that establishes the same complete boundary and area information.
- Keep source provenance and physical assumptions explicit. Do not reapply entropy or the random-50% correction, infer Ni parameters, or import crack-tip enrichment and external loads into this intrinsic model.
- With all energies converted to J/m², use `D_center=alpha*gamma_F_mean−beta*mu_usf`, `D_low=alpha*gamma_F_low−beta*mu_usf`, and `D_high=alpha*gamma_F_high−beta*(mu_usf−sigma_A)`, with `sigma_A=sigma_108*sqrt(108/A)`. Critical intensities obey `KIc=sqrt(alpha_GPa*gamma_F_Jm2/1000)` and the corresponding beta/USF expression.

### Input and deliverable details

Use the elastic, fracture-energy and unstable-fault tables under `/app/assets/`, together with their source records. Create `/app/final/` and submit four outputs.

- `phase_map.csv` (183618 rows): keys `alloy,A_nucleation_A2,C_surface,C_usf`, fixed `Cb_fixed,temperature_K`, the three `gamma_F_{mean,low,high}_J_m2` values, `gamma_usf_sigma_scaled_mJ_m2`, `D_{low,center,high}_GPa_J_m2`, `KIc_{low,mean,high}_MPa_sqrt_m`, `KIe_{low,mean}_MPa_sqrt_m`, and `classification` (`cleavage_first_robust,emission_first_robust,competition_uncertain`). Braced alternatives denote separate columns.
- `analytic_boundaries.json`: an array of `{alloy,A_nucleation_A2,boundary,C_surface_cell,C_usf_cell,endpoints_C_surface_C_usf}`; use `D_low,D_center,D_high` for boundary families and numeric coordinate pairs.
- `region_areas.csv` (18 rows): `alloy,A_nucleation_A2,cleavage_first_robust,emission_first_robust,competition_uncertain,area_sum`.
- `extrema_certificates.json` (18 objects): `alloy,A_nucleation_A2,vertices_checked,min_D_low,max_D_low,min_D_high,max_D_high,whole_domain_certificate`. Each extremum gives `C_surface,C_usf,D_low_GPa_J_m2,D_high_GPa_J_m2`. Conclusions use `cleavage_first_robust_entire_domain`, `emission_first_robust_entire_domain` or `local_competition_or_uncertainty_present` as supported by the computed extrema.

Use UTF-8 CSV with headers and JSON numeric arrays for coordinate pairs. Units are carried by the scientific column names; repeated source-label or unit-string columns are optional.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final/analytic_boundaries.json` | an array of `{alloy,A_nucleation_A2,boundary,C_surface_cell,C_usf_cell,endpoints_C_surface_C_usf}` |
