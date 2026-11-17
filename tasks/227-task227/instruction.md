# MM-GBSA Association, Ranking and Failure Attribution

## Background

Molecular Mechanics Generalized Born Surface Area (MM-GBSA) is widely used in structure-based drug design to estimate binding free energies. However, evaluating candidate docking poses using endpoint MM-GBSA on short unbiased MD simulations frequently yields poor results.

The authors benchmarked MM-GBSA against OpenBPMD using 10 ns unbiased trajectories scored with AmberTools20 `MMPBSA.py`. Compute the association and ranking performance directly from the supplied paired per-pose data. The SI energy file covers 200 poses in 40 systems; two DPP4 systems are absent because the reported MMPBSA.py calculations failed. Do not impute those data or compare rates using different denominators.

Table S1 supplies pose identifiers, RMSDs and OpenBPMD scores for 42 systems. The SI energy data cover 200 poses in 40 systems; the provenance records the source and exclusions.

## Task

Compute the statistical association between MM-GBSA scores and pose RMSD and compare ranking performance on the matched population. Evaluate solvent, entropy and finite-sampling explanations against scientifically plausible alternatives. Distinguish observations, hypotheses and causal conclusions; a justified finding that the mechanism is not identifiable can satisfy the task.

## Requirements

- Join the energy data by `pose_id` and verify `pose_rmsd_A` against Table S1.

- Derive coefficients, variable direction and ranking performance from the supplied matched data. Do not treat a fixed sign or arbitrary coefficient threshold as a universal rule. Pooled p-values are nominal because poses cluster within systems; association and ranking differences do not by themselves identify causality or establish universal method superiority.
- These formal countermodels address missing causal information. They are not measured affinity, measured entropy, a recovered MMGBSA energy-component decomposition or a demonstrated fix.
- In the report, connect each correction to an actual matched control: change solvent representation while retaining poses, force field and sampling; change entropy estimator at fixed trajectory/solvent; extend independent sampling at fixed Hamiltonian/estimator.
- Distinct intervention predictions show what data would discriminate the explanations.
- RMSD is a pose observable, not a known binding free energy.
- Preserve contrary evidence and transfer limits.
- Countermodel tolerance=max(1e-7,1e-7*abs(expected)); cluster-statistic tolerance=max(1e-8,1e-7*abs(expected)). All values must be finite typed JSON numbers. Units: x is MM-GBSA binding energy dG in kJ/mol (kJ mol^-1 or kJ mol⁻¹); y is pose RMSD in Angstrom or Å; n=200. kcal/mol and nm are different units. `excluded_systems` is a unique ID set. Tie bounds require finite min/max and integer n.

The output contract listed below defines the input index, output fields, units and numerical protocols. Keep linked run evidence within the declared submission directory.

JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Paired energies, poses and reference data. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/output-contract.md` | Required outputs and submission format. |
