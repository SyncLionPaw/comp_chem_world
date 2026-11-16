# Task: Characterize Li–Li RDF features and comparison curves

## Background

The supplied Li–Li RDF is `environment/assets/li_li_rdf_this_work.csv`; comparison curves are supplied under `environment/assets/`. Their distance units and temperature are given in `units.txt`.

## Task

Report the primary contact peak, the two principal environment minima, and the contact-to-saddle free-energy barrier. Identify qualifying comparison peaks, test whether any matches the primary peak, and compare the barrier with thermal energy.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Convert the source RDF distance from pm to Å. The contact peak is the maximum g(r) for `2.2 < r < 2.8 Å`. Report the deepest sampled minimum in each of `2.7 < r < 3.3 Å` and `3.6 < r < 4.5 Å`. These measured minima need not equal the supplied region cutoffs of 3.0 and 4.15 Å. Use `F(r) = −k_B T ln g(r)`; the barrier in kcal/mol is max F over `2.7 < r < 3.3 Å` minus min F over `2.2 < r < 2.7 Å`, using samples with `g(r) > 10⁻⁸`.

For each comparison curve, convert distances to Å using `units.txt`, sort by distance, and average values at duplicate distances. A local maximum is strictly above the preceding sample and at least as high as the following sample. A qualifying peak has `r < 3 Å` and `g(r) ≥ 0.6`. It matches the primary contact peak when its position is within `0.1 Å` and its height differs by at most 20% of the primary peak height. Classify the barrier as comparable to `kBT` when `0.5 ≤ barrier/(kBT) ≤ 2`; these are operational comparison criteria.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Li–Li radial distribution functions and published comparison curves. |

Write `/app/final/environments.json`; report distances in Å, barrier in kcal/mol, filenames in the curve list, and flags as JSON booleans. Include:

`r_first_maximum_A`, `g_first_maximum`, `r_boundary_I_II_A`, `r_boundary_II_III_A`, `barrier_I_II_kcal_mol`, `barrier_comparable_to_kT`, `curves_with_maximum_below_3A_and_g_at_least_0.6`, `any_comparison_curve_matches_contact_peak`.
