# Electronic reference library: spin constraints and method comparability

## Background

The supplied Rad-6 molecular library supports an audit of spin constraints and electronic-method comparability.

The inputs include the original structures, coordinates and energies, the Rad-6 README on format, units, molecule classes and electronic initialization, plus the article and Supplementary Note 1 on electronic-structure methods and limitations.

## Task

Audit all 10,712 molecular records and 123,914 atom rows, reconstruct the signed atomization ledger and neutral spin constraints, and assess electronic-method comparability.

## Requirements

- Audit all 10712 records and 123914 atom rows locally. Preserve original IDs/order, DFT/UFF coordinates (Å) and signed eV energies. Locate H/C/O isolated-atom references in the source; reconstruct atomization and raw/per-atom/atom-referenced method differences with full denominators. Coordinate tolerance: 1e-8 Å; derived energy: 1e-7 eV.
- Use neutral charge 0 to derive electron parity and allowed total-spin families, not actual multiplicities. Distinguish source radical counts, declared initialization/exceptions, observed differences and inferred conclusions. Do not identify ground states, biradical character or actual symmetry breaking from parity, missing diagnostics or column names; UFF coordinates are not a separately optimized BS geometry.
- Cite the supplied README, article Methods p.9/license p.11 and SI pp.2–3; retain attribution. Explain method/geometry confounding, normalization limits and concrete matched controls that would distinguish stronger claims. No fixed ground-state conclusion is imposed; justified non-identifiability is allowed.
- Construct at least six source examples including H/C/O/O2 and both parity sectors. For each molecular example supply two protocol countermodels reproducing the source delta, with matched spin lowering in [-5,0] eV and predictions separated by at least 0.1 eV. Include the required allowed finite-electron representations and matched initialization/geometry controls.
- Construct two normalized six-determinant two-electron states embedded in an even-electron example, with onsite interaction in [0.1,10] eV. Reconstruct all observables: both states have zero Ms, S² and spin density, but leading natural occupations differ by >0.5 and interaction responses by >0.05 eV. These are active-space counterexamples, not wavefunctions assigned to the source molecule.
- Write the source-cited report in English or Chinese; distinguish hypothetical controls from observations.
- No new DFT, SCF searches, scheduler jobs or network.

- Submit the required results and evidence under `/app/` according to the listed output convention.

The source-summary contract defines the even-radical intersection bounds from the source radical and neutral-parity marginal counts.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Molecular structures, energies and source material. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/CERTIFICATE-OUTPUT-CONTRACT.md` | Required outputs and submission format. |
