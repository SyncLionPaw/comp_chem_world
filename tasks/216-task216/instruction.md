# Multi-Scale Mechanistic Synthesis and Inactivity Diagnosis

## Background

The supplied evidence concerns turnover differences and Chimera 1 inactivity.

The supplied dataset contains kinetics, EVB, sequence and MSM evidence.

## Task

Assess mechanistic evidence for turnover differences and Chimera 1 inactivity, and calculate and interpret the quantities specified below and in the public contract.

## Requirements

- Compare WT and Chimeras 7/4/3 quantitatively, preserve signed six-residue electrostatic comparisons and independently counted motifs.
- Keep the three unavailable Chimera 1 MSM quantities and experimental activation barrier as source-bound nulls.
- Provide source-bound quantities and derived operations, report, attribution matrix and constructive mechanism certificate.
- Construct two opposing serial waiting-time allocations (chemical fractions ≤0.1 and ≥0.9) per system, two C1 zero-turnover boundary models and observationally equivalent E-loop models.
- Do not identify MSM opening with productive access, residual barriers with gating, or observational countermodels with measured interventions.
- Use R=0.00198720425864083 kcal mol⁻¹ K⁻¹, T=298.15 K and tolerance max(1e-6,1e-6*abs(expected)).
- Retain conditional prefactor uncertainty and evidence-linked candidate mechanisms, counterevidence and distinguishing measurements.
- Do not fetch external scientific data.

- In the attribution matrix, source paths use slash-separated keys relative to the dataset JSON root, without a filename prefix or leading slash; for example `kinetics_25C/WT_PTP1B/kcat_s_inv`.
- JSON submissions must use unique object member names and finite numbers. Artifact paths may resolve to files inside `/app`.
- For the E-loop countermodel sum use only K120_E_loop, E115_E_loop, K116_E_loop and R112_E_loop; report all six residues separately in the attribution matrix.
- A derived quantity's `operation` is a bare enum from the output contract, such as `ratio`, `difference` or `eyring_rate_ratio`; put explanatory prose in the designated rationale fields, not in the enum value. The four-residue E-loop sum is signed, with neither absolute values nor the additional N111 and L110 terms.
- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Structures, calculation records and reference data. |
| `/app/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
