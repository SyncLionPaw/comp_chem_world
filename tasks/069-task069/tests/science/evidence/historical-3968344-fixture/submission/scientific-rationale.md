# Independent post-processed scientific rationale

This analysis was run after collection for Slurm job 3968344; it is versioned separately from the original job-time case08_tools.py (SHA-256 9e1b1bd0911e78902f1ae8767a0a5ad147ee2f73df70e0dd3456444315e4e1c2). The post-processing script SHA-256 is c72667e9be50094e6e8a93f441b8ab7b9119066f4cf7dc72c33974b0b1fa8379. Original job-time reports are retained with the `job-` prefix.

The four paired NVT trajectories each reached 50 ps. Missing GROMACS energy terms were independently re-extracted from the unchanged native EDR files with GROMACS 2022.6; their hashes and source EDR bindings are recorded in energy-extraction.json. The ranges below are measured from native sampled GRO frames and these re-extracted EDR series. Explicit warning counts use whole-word event matching, so the parameter name `lincs-warnangle` is not counted as an event.

For B, full-window mean temperature was 299.459 K at 1 fs and 300.462 K at 2 fs (2 fs minus 1 fs: +1.003 K); this is a finite-sample contrast, not a universal stability threshold.
For B, mean constraint RMSD was 5.716e-06 at 1 fs and 2.2482e-05 at 2 fs; Conserved En. changed by +13.758 and -40.672 kJ/mol, respectively. These are diagnostics in thermostatted NVT, not pass/fail cutoffs or a requirement that total energy be conserved.
For U, full-window mean temperature was 299.914 K at 1 fs and 299.824 K at 2 fs (2 fs minus 1 fs: -0.090 K); this is a finite-sample contrast, not a universal stability threshold.
For U, mean constraint RMSD was 5.324e-06 at 1 fs and 2.1198e-05 at 2 fs; Conserved En. changed by +3.141 and -56.773 kJ/mol, respectively. These are diagnostics in thermostatted NVT, not pass/fail cutoffs or a requirement that total energy be conserved.
In both starting states, 2 fs produced a larger mean constraint RMSD and a larger absolute conserved-energy change than 1 fs in this 50 ps sample; this supports prioritizing 1 fs in the next bounded numerical check, not declaring 2 fs universally unsafe. NVT total energy is not required to be conserved.

The observation-based recommendation is `needs_check`. Even a warning-free result supports only a bounded numerical follow-up: these short trajectories do not demonstrate equilibration, free energy, kinetics, or production suitability.
