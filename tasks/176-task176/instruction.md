# Task: Compare coordination and angle distributions

## Background

`window_blue.dat`, `window_green.dat`, and `window_red.dat` are Li–O coordination histograms for three Li–Li distance windows; `window_all.dat` is unconditional. Columns give coordination number, total-oxygen percent, anion-oxygen percent, and water-oxygen percent. The Figure 4 scripts map blue/green/red to regions I/II/III and `window_all` to Ave; Figure 2 gives region boundaries at 3.0 and 4.15 Å without specifying endpoint inclusion. Angle files contain trajectory Li–Ow–Li and experimental bulk-water O–O–O histograms.

## Task

Identify the window associated with short Li–Li contacts. Report its total- and anion-oxygen coordination modes and compare its total mode with the unconditional mode. Find the largest-histogram-value angle in `0° < θ < 90°` (acute) and `90° < θ < 180°` (obtuse), report each within 2° of its sampled mode, and compare the acute mode with the experimental bulk-water mode.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

A mode is the coordination number or angle at the largest value in the relevant histogram; the unconditional mode is not a mean. Compare peak angles, not widths, and calculate the bulk-water mode from its histogram. Determine the comparison direction from the data. The 2° tolerance is reporting precision, not sampling uncertainty. Use the source window mapping above and compare modes, not means.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Coordination-number and bond-angle histograms. |

Inputs are under `environment/assets/`. Write `/app/final/solvation.json` with `short_contact_window` (`blue`, `green`, or `red`), integer `short_contact_mode_total_cn`, `average_mode_total_cn` (unconditional mode), boolean `short_contact_cn_higher_than_average`, integer `short_contact_modal_anion_cn`, two-number `angle_modes_deg` ordered acute then obtuse, and boolean `acute_mode_tighter_than_bulk_water` (true when the acute angle is smaller than the bulk-water mode).
