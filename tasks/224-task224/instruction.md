# Metadynamics Protocol and Gaussian Hill-Height Decision

## Background

Binding pose metadynamics accelerates the exploration of metastable ligand states by depositing history-dependent Gaussian bias potentials along a collective variable (CV). In OpenBPMD, the CV is the root-mean-square deviation (RMSD) of the ligand's heavy atoms relative to reference coordinates, aligned against protein secondary structure Cα "anchor" atoms to decouple internal ligand motion from global protein tumbling.

The solvated system is supplied as an Amber topology and restart. The inputs also provide source condition comparisons and their provenance.

## Task

Gaussian hill height changes finite-time driven perturbation and ranking. Compare the specified 0.30 and 0.05 settings without inferring measured throughput or free-energy resolution from the amplitude. Assess conditional benefits/risks using the source data, counterevidence and distinguishing predictions.

Orchestrate the simulation protocol specification for OpenMM metadynamics on the solvated system and formulate a physical rationale for the Gaussian hill height decision.

## Requirements

- Compare 0.30 and 0.05 hill heights under the same 10×10 ns intended budget, using source statistics, counterevidence and distinguishing predictions. Do not infer measured throughput/free-energy resolution or universal benefit/harm from hill amplitude; the source reports some poses escaping too quickly, not universal escape.
- Derive ordered DSSP H/G/I/E/B Cα anchors within 10 Å of ligand heavy atoms, excluding loops/termini. This benchmark rule and anchor-only-fit/ligand-only-measure CV differ from the author's COM-neighborhood backbone selection and joint ligand-plus-anchor RMSDForce; disclose both distinctions.
- Keep the specified 100 ps deposition interval and disclose the Methods 100 ps/code 1 ps discrepancy. Represent the author's empty flat-bottom workaround as `k_kj_mol: 0.0`, `upper_wall_nm: 10.0`; it exerts no force and does not fix RMSD image handling.
- Retain the supplied Amber topology and specify intended NVT, 300 K, Langevin friction 1 ps^-1, 4 fs, HMR 4 Da applied/checked at system construction, PME/1 nm, HBonds and PBC. Distinguish these unexecuted source-derived production intentions from uniform-mass geometric smoke tests. The paper reports ff14SB/GAFF2/AM1-BCC/TIP3P, but Amber files alone do not establish complete provenance.
- Include `parameter_rationales` for every required bias/CV/PBC/budget field, `intended_production_protocol` and `source_cv_distinction`. Support reasons with source evidence and quantitative controls. Prose alone is not semantically certified.
- Use directly acquired OpenBPMD pp6213–6214 for O3 and the conditional small-hill recommendation. Do not treat unverified Clark2016 rerun/escape details as observations. Numerical countermodels are hypothetical, not measured probabilities, trajectories or causal conclusions.
- Use finite JSON numbers, excluding booleans; response/evidence tolerance is max(1e-8,1e-7*abs(reference)).

JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.

Use zero-based Amber atom and residue indices; a descriptive residue ID may follow the source representation. Native validation is checked through its scientific behavior rather than an exact platform or integrator class name.

Calculate and submit both separate reproducible controls in the output field map: the nonzero-force periodic/nonperiodic energy diagnostic and the deposited-hill CV control (`reference_control`). These are required numerical outputs, distinct from the zero-k workaround and your main smoke simulation. Report the actual settings and results of the main smoke, whose valid platform, Langevin integrator and duration are not prescribed by these controls. The map specifies each control's inputs, output fields and numerical tolerance.

Submit the results according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Solvated system and source data. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/inputs/output-field-map.json` | Output fields and submission format. |
