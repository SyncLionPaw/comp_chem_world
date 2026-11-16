# Task: Compare lithium contacts and oxygen bridges in two frames

## Background

`frame_early.xyz` is the 0 ps classical-MD endpoint and `frame_late.xyz` the 70 ps ab initio restart; each comment gives the cubic edge in Å. Both are the same LiTFSI–water cell.

## Task

Compare Li–Li contacts, oxygen bridges, and contact-graph components between the frames. Report the defined statistics and assess chain evidence and ensemble populations.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Choose and report one Li–Li cutoff in `[2.7, 3.2] Å` and one Li–O cutoff in `[2.4, 3.0] Å`, applying each unchanged to both frames. Use periodic minimum-image distances and inclusive cutoffs. An oxygen bridges a Li pair when it is within the Li–O cutoff of both ions. Classify it as water oxygen if any H is less than `1.25 Å` away; otherwise it is TFSI oxygen. Include every Li in the contact graph and add an edge for each Li–Li contact, whether bridged or not. A chain is a connected component of at least three Li; this does not imply linear geometry.

For each frame report `n_contact_pairs`, `fraction_oxygen_bridged` (contacts sharing at least one oxygen; zero if there are no contacts), `max_component_size`, and `fraction_Li_in_components_ge_3`. `contacts_share_water` indicates a late-frame contact sharing water oxygen; `anion_can_co_bridge` indicates a late-frame contact sharing both water and TFSI oxygen. `chains_present_in_late_frame` is true when the late-frame largest component has at least three Li; `extended_chains_present_at_classical_start` is true when the early-frame largest component has at least four Li. Assess whether two configurations establish an ensemble population.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Structures for the lithium-network analysis. |

Inputs are under `environment/assets/`. Write `/app/final/topology.json`. Fractions are numeric, counts and sizes are integers, and flags are JSON booleans. Include `li_li_cutoff_A`, `li_o_cutoff_A`, `late` and `early` (each with the four statistics above), `contacts_share_water`, `anion_can_co_bridge`, `chains_present_in_late_frame`, `extended_chains_present_at_classical_start`, and `ensemble_population_established`.
