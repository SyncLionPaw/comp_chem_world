# Reaction-network topology, hub chemistry and mechanistic limits

## Background

The Rad-6 reaction network supports analysis of hub chemistry and the limits of topology-based mechanistic inference.

The inputs include reaction connectivity and energies, species identities and composition, and original structures.

## Task

Reconstruct all 32,515 reactions and 10,081 species using 10,712 molecular records; quantify hub chemistry, graph projections and mechanistic non-identifiability with constructive controls.

## Requirements

- Reconstruct all 32515 reactions and 10081 species from the 10712 molecular records. Treat -1 as the rearrangement sentinel; use the simple undirected educt–product projection with duplicate edges collapsed, while participation retains repeated products. Preserve all-source energy closure within 1e-6 eV.
- Use exact normalized Brandes, fixed 4×16-source batches (seed 20261016), or declared independent uniform-source batches (2–32, at least one source each, at most 2048 total; seed in [0,2^63)). Report method and uncertainty.
- Use the supported KS-selected discrete-tail approximation or declare a source-chosen cutoff in `power_law_parameters={xmin}` with integer xmin, retaining at least two nodes. For tail d≥xmin: alpha=1+n/sum(log(d/(xmin−0.5))); KS is the maximum observed-support difference between empirical CDF and 1−((k+0.5)/(xmin−0.5))^(1−alpha). Report tail population and matching alpha; additional estimators do not replace this executable primary method.
- Cover each of the ten degree hubs once in `hub_chemical_assessment`: source-exact identity, integer participation counts, nonempty assertion and at least two distinct relevant reaction rows. Preserve row/product order and multiplicity; cover all occurring roles and at least two educts when multiple educts produce the hub. Each row has `csv_line`, `educt_id`, `product_ids`, `reaction_type`, `reaction_energy_eV`.
- Construct duplicate-enumeration (factor 2–10), kinetic (200–1000 K; baseline barrier 0.05–2 eV; extra barrier 0.05–5 eV) and path/star-extension controls (edge count above original maximum degree, at most 20000). Kinetic responses must differ by >0.1 log unit. These are hypothetical controls, not measured fluxes/barriers.
- Do not infer actual spin, barriers, flux, abundance or a universal power law from degree. Support chemical assertions numerically, and use `/app/environment/assets/CERTIFICATE-FIELD-TYPES.json` for certificate fields.
- Use only supplied data, without network.

Submit the results according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/environment/assets/` | Reaction network, species information and reference energies. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/environment/assets/CERTIFICATE-FIELD-TYPES.json` | Output fields and submission format. |
