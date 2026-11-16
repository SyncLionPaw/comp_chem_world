# Task: Analyse local Au–C force responses and numerical consistency in fixed water/potassium environments

## Background

This task reanalyzes completed static DFT data in fixed water and 2K environments to study local CO₂ response along the Au–C direction, numerical consistency, and sensitivity to a finite set of initial structures. The public native archive contains 13 static force-evaluation points and VASP XML, OUTCAR, inputs, point mappings, and budget records. The historical construction budget was at most 24 ionic-force evaluations.

## Task

For water and 2K environments, use the four centers at C–Au distances of 2.6 Å and 3.0 Å. Hold Au and the rest of the environment fixed, and rigidly translate CO₂ along the Au→C unit vector by −0.02, 0, and +0.02 Å. A second 2K center at 2.6 Å has a different bending, hydration, and coordination initial structure; it is not part of a three-point set. Use VASP `e_fr_energy` for energies relative to each set’s center. From the native XML, recompute the negative projection of the summed force on the three CO₂ atoms along Au→C, and compare the force gradient with the central finite difference. Use the threshold `0.05 eV/Å + 5% × max(|force gradient|, |finite-difference gradient|)`; explain any exceedance and do not omit or replace points.

Quantify local-response differences between water and 2K at 2.6 Å and 3.0 Å, and between the two 2K initial structures at the same nominal distance. Check whether the paths are equivalent. When multiple structural factors change together, do not attribute a difference to a single coordination effect. Compare at least one public but unmeasured seed geometry with the measured centers, and explain its information gain and opportunity cost. Retrospectively compare three explanations: a fixed-environment local response, initial-structure/pathway confounding, and numerical-estimation error. Propose at least two executable follow-up options, explaining their priority, cost, opportunity cost, trigger/stop conditions, and possible outcome branches. Recommendations do not authorize those calculations.

Conclusions are limited to the computed fixed-environment local response and sensitivity to the finite set of initial structures. Scan points are not equilibrium states, endpoints, or transition states. Do not use them to establish an equilibrium mean force, equilibrium free energy, transition state/barrier, global adsorption stability, constant-potential K effect, or single-variable coordination causality; set `equilibrium_deltaA_eV` and `equilibrium_CI` to `null`. This round performs zero new scientific calls and submits no DFT/MD calculation or job. The public results are retrospective analyses and must not be described as preregistered.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, matplotlib, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

Audit native provenance, the fixed environment, atom mapping, coordinate perturbations, convergence, signs/units, local energy zero, and historical budget. Compare at least two follow-up options and explain how their possible outcomes would affect subsequent decisions. POTCAR was not distributed; report only the version/hash provenance that is provided. `analysis.py` must recompute the deliverables from native evidence and replay them deterministically.

### Input and deliverable details

Inputs are provided under `/app/environment/assets/`: `water_CO2/POSCAR`, `2K_CO2/POSCAR`, `methods.json`, `IS_seed_panel.extxyz`, `IS_seed_provenance.json`, `IS_budget.json`, `IS_native.tar.gz`, and `IS_native_manifest.json`. The output structure, fields, budget, and replay requirements are defined in `output-contract.json` in the same directory. POTCAR is not provided.

Write `selection.json`, `hypotheses.json`, `response.csv`, `path_audit.json`, `decision_log.json`, `next_calculation.json`, `native/manifest.json`, `analysis.py`, and `report.md` to `/app/final/`. Only the manifest is required under the submitted `native/`; do not copy the whole native archive there. Create `analysis.py` as part of your submission; its interface is `python analysis.py ASSET_DIR OUTPUT_DIR`, with `/app/environment/assets/` and `/app/final/` as the respective directories.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
