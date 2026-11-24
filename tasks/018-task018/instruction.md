# Analyse continuum and local-solvent effects for Reichardt's dye

## Background
The supplied Reichardt dye is a neutral-singlet C41H29NO zwitterion (72 atoms). Short trajectories are diagnostic, not equilibrium populations.

## Task
Prepare periodic methanol/acetonitrile systems, run short dynamics and compare five fixed-geometry electronic calculations for local-solvent effects.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, QC-IOdata, SciPy. Do not install additional packages or fetch dependencies from the network.

Follow public compute-budget.yaml and output-contract.yaml. Use AM1-BCC/GAFF dye, Amber 20 MEOHBOX/frcmod.meoh methanol, supplied ACN model. Each box ≤3,000 atoms; minimize ≤200 cycles; run 100 warm-start +100 NVT diagnostic steps per solvent at 2 fs/298 K, saving every ASCII mdcrd frame; each 0.2 ps segment is not equilibration. Select from actual trajectories with periodic reconstruction. A/B share selected MeOH dye geometry with CPCM MeOH/ACN; C adds sampled MeOH; D rotates only donor H, heavy atoms fixed; E is distinct ACN MD, not matched. Contact: H···O≤2.5 Å and O–H···O≥130°; if absent, nearest candidate and inconclusive, never force contact. Preserve frame/time/topology/trajectory provenance. Run five sequential remote neutral-singlet ORCA 6.0.1 BP86/def2-SVP def2/J RI-J TightSCF CPCM single points within budget; fixed geometry, no optimization/TDDFT. Retain native MD/selector/QM/scheduler artifacts. From native ORCA and corrected Molden compute signed overlap Mulliken qμ=cμ(Sc)μ; all occupied/virtual normalization and orthogonality errors≤1e-4, no renormalization. Dye atoms 1–72, solvent 73–78; report A−B/C−D total/HOMO/LUMO differences in hartree and participation. Discuss orbital localization and method limits; no optical/equilibrium mechanism claims. Public contracts define records/files/classification/tolerances; use supplied stages and templates. If using HPC computing resources, consult `hpc`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Public calculation inputs, helper scripts and resource limits. |

/app/assets/: public inputs/scripts/budget; /app/final/: linked records/calculations/analysis.
