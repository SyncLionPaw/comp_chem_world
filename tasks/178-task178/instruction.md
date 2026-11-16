# Task: Assess structural and dynamical claims

## Background

The supplied data include early classical and 70 ps ab initio frames, Li–Li RDF, coordination and angle histograms, population series, total X-ray curves, MSD and non-Gaussian traces, and a distinct Li–Li van Hove matrix. File units and definitions are in the supplied `units.txt`, `scattering_units.txt`, and `dynamics_units.txt`; `experimental_sans.txt` provides length-scale context.

## Task

Assess the evidence for short-contact lithium chains and oxygen bridges, their population and exchange, the contact-to-saddle free-energy scale, X-ray structural specificity, relative species mobility and non-Gaussian behavior, and changes in small-separation distinct Li–Li van Hove intensity. State the evidence scope and limitations.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

For RDF analysis, convert distances from pm to Å and use `F(r) = −kBT ln g(r)` at 298.15 K. The contact peak is the maximum g(r) for `2.2 < r < 2.8 Å`; the barrier is max F over `2.7 < r < 3.3 Å` minus min F over `2.2 < r < 2.7 Å`, using samples with `g(r) > 10⁻⁸`. Call it comparable to kBT when `0.5 ≤ barrier/(kBT) ≤ 2` (operational criterion).

For population series, column 1 is a frame index, not time. Figure 3's fifth data set and legend identify `pop_b` as chain (region I), `pop_c` as intermediate chain (II), and `pop_a` as no chain (III). Preserve these supplied categories and report their supplied percentages without renormalizing; they are not specified as a mutually exclusive partition. The contact fraction is the selected series' arithmetic mean; majority means above 50%. Interpret `contact_cn_higher_than_isolated` by comparing I/chain with the source-labeled III/no-chain distribution; this does not imply every Li in III lacks contacts. Figure 4 maps `window_blue` to I, `window_red` to III, and `window_all` to the unconditional average. Compare the I and III total Li–O coordination modes, not means or the unconditional histogram. Figure 2 boundaries are 3.0 and 4.15 Å; endpoint inclusion is unspecified.

For topology in `frame_late.xyz`, use minimum-image periodic boundaries, Li–Li distance ≤3.0 Å and Li–O distance ≤2.6 Å. Classify water oxygen by O–H distance <1.25 Å using the same boundaries. These are task analysis cutoffs. A connected Li component of at least three ions is chain-like, without implying linear geometry or a macroscopic network. Assess ensemble-population evidence from the supplied configurations and series.

For X-ray comparison, calculated q is in nm⁻¹ (divide by 10), while experimental q is in Å⁻¹ and the trace is not vertically aligned. Sort each curve and average duplicate q values before interpolation. Fit one vertical offset by least squares over 300 equally spaced q points, including endpoints, from 0.5 to 8.0 Å⁻¹, using linear interpolation. Shifted dimensionless RMSE ≤0.10 is the operational agreement criterion.

For MSD, times are in ps and values in pm² (divide by 10,000 for Å²); report each species' last value and order species by those values. Non-Gaussian time is column 1 divided by 1000. Use the common 0.1–30 ps interval (21 points) and its peak α₂ value. A peak >0.10 is a descriptive signal, not a significance test; call it Li-specific only if Li exceeds 0.10 while water oxygen and anion nitrogen are each ≤0.10. These traces are for selected atoms, not center-of-mass motion.

For the distinct van Hove matrix, row is time and column is distance. In each window, average all elements with distance-bin centers <0.5 Å and time respectively <5 ps or >20 ps. A higher late-window mean supports exchange-compatible motion between Li ions occupying former positions; it does not measure residence times or an exchange rate. Assess whether the supplied dynamics show a stable long-time diffusive regime and characterize the evidence, uncertainty, and sampling supporting any quantitative diffusion estimate.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public evidence for evaluating the claims. |

Inputs are under `environment/assets/`. Write `/app/final/claim.json` with boolean fields `nanochains_with_short_contacts`, `contact_population_is_majority`, `barrier_comparable_to_kT`, `transient_exchange`, `contacts_share_water`, `contact_cn_higher_than_isolated`, `xray_s_agrees`, `xray_s_proves_short_chains`, `diffusion_coefficients_quantitatively_reportable`, and `dynamic_heterogeneity_specific_to_lithium`; numeric fields `contact_distance_A`, `contact_fraction_percent`, `vhcf_small_r_mean_before_5ps`, and `vhcf_small_r_mean_after_20ps`; `contact_series` (`pop_a`, `pop_b`, or `pop_c`); `msd_final_A2` with numeric `Li`, `H2O`, and `TFSI`; and `apparent_mobility_order`, listing those species from fastest to slowest. `limits` must be a list containing at least two distinct identifiers from `trajectory_about_70ps`, `single_density_functional`, `finite_cell`, and `single_concentration` (sampling duration, functional choice, cell size, and concentration coverage).
