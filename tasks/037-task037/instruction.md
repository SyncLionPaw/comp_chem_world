# Task: Audit velocity-derived vibrational spectra and their mechanistic interpretation

## Background

Vibrational density spectra calculated from velocities can describe fluctuations in finite molecular dynamics trajectories, but do not directly provide absolute infrared/Raman intensities and may not uniquely identify a reaction pathway. The supplied `spectrum.py` is a supplied script to be reviewed; independently diagnose, using the code and trajectories, how it handles structure selection and velocity processing, and how it interprets spectra.

## Task

Reconstruct CO₂ velocity spectra from the four Au/water interface trajectories, analyze bending and both stretching modes, and use bond-direction projections and block stability to check mode assignments. Also provide a reproducible implementation-level diagnosis of the supplied script, distinguishing finite-sample fingerprints of structure/charge state from conclusions about inner-sphere/outer-sphere pathways.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, matplotlib, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- Read only the four trajectories and supplied script in `/app/environment/assets/`; use Python 3.12. The frame interval is 1 fs. Preserve the source masses of C, O, and H; do not apply isotope mass scaling. Identify CO₂ independently in each system and use only the nine Cartesian velocity components of its three atoms.
- Select a half-open frame interval `[start_frame, end_frame_exclusive)`, with a start frame from 0–3000, a length of at least 6500 frames, and an end no later than the trajectory length. Record each system's atom indices, masses, and frame range. Hydrogen masses may be reported as a full list or as a deduplicated ascending list.
- In `metadata.estimator`, record `kind`, `window`, `detrend`, `nfft`, and `block_count`; for Welch, also record the requested values of `nperseg` and `noverlap`. You may use a periodogram, Welch, or a VACF/FFT periodogram route `vacf_fft`. If you use another scientifically reasonable estimator, explain its equivalence, calculation method, and mode-assignment basis. An alternative estimator requires independent scientific review before a score can be assigned. The window must be Hann, boxcar, or blackmanharris; detrending must be constant, linear, or false. `nfft` may be null or from the selected sequence length through four times that length; zero-padding does not improve true frequency resolution. Divide the sequence into 3–6 contiguous blocks, each at least 1024 frames. For Welch, request `nperseg≥1024` and `0≤noverlap<nperseg`; truncate the actual segment length and overlap to the available sequence and report them. Do not replace the full-sequence PSD with an average of block spectra; use blocks only to assess peak-location stability.
- `spectra.csv` has columns `system,wavenumber_cm-1,power_arb`. The frequency axis must increase from zero, cover at least 3000 cm⁻¹, and contain at least 100 points; you may output the full axis or a continuous prefix. Use the same arbitrary positive intensity scaling for all systems. Explain unit conversion, the Nyquist frequency, and the time source. The frequency-axis tolerance is `1e-5 cm⁻¹`; the normalized PSD tolerance is `atol=2e-5, rtol=2e-4`.
- For every frame, project relative velocities onto the instantaneous C–O bond directions. The sum and difference of the two bond projections `dr1` and `dr2`, each divided by `sqrt(2)`, give the symmetric and antisymmetric stretches, respectively. Use the six transverse relative-velocity components of the two bonds for bending. Search for the main peak in `400–950 cm⁻¹` for bending and `900–1500 cm⁻¹` for the symmetric stretch. Search for the antisymmetric stretch in `2000–2700 cm⁻¹` for neutral states and `1300–1950 cm⁻¹` for anion states. Do not copy peak positions directly from a source figure.
- In `peaks.json`, provide `wavenumber_cm-1`, `block_peaks_cm-1`, `stability_range_cm-1`, `status`, and a nonempty `rationale` for the bending, symmetric, and asymmetric peaks in all four systems. Use `numpy.array_split` for blocks; the stability range is the block-peak minimum and maximum, not a confidence interval. Optional `range_kind=block_minmax` and `mode_source` (bending `bond_transverse`, symmetric `bond_rate_sum`, antisymmetric `bond_rate_difference`) must be correct if provided. status is `resolved` or `unresolved`; unresolved peaks need a nonempty reason. Optional `unresolved_reason` may be `weak_in_total_PSD` (the PSD peak in the mode band is below 8% of the total peak), `block_drift` (the block-peak span is at least 40 cm⁻¹), or `mode_overlap` (within 100 cm⁻¹ of another projected peak); it must agree with the actual diagnostic. A resolved peak must have a local peak in the total CO₂ PSD within `max(25 cm⁻¹, 2×frequency spacing)` of the assigned peak. These are operational screening criteria, not universal physical standards. The tolerances for peak and block-peak positions are `0.001 cm⁻¹`.
- In `metadata.json`, record a per-system `selection`; each entry contains `atom_indices`, `mass_u`, `hydrogen_masses_u`, `start_frame`, and `end_frame_exclusive`. Also record `dt_fs`, `speed_of_light_cm_per_fs`, `Nyquist_cm-1`, `time_source`, the estimator, `absolute_IR_or_Raman_intensity=false`, `mass_rescaled=false`, `provided_ensembles`, `missing_IS_comparison`, and `script_diagnostics`. `provided_ensembles` uses the `OS_neutral` and `OS_anion` labels; it may be a mapping for the four systems or a list of the two state labels. Script diagnostics record `loop_components`, `required_interface_components`, `example_system`, `atom_scope`, `VACF_transform`, `frequency_offset_cm-1`, `full_convolution_alignment`, and enough explanation to reproduce the diagnosis. `required_interface_components` is the component count for the full-interface velocity array; if you also report the CO₂-only observable's count, use distinct fields such as `required_whole_interface_components` and `required_co2_components`. The example is `water_CO2`. Counts must be integers or unambiguous numeric strings, independently checked against the script/structure. Categories are `whole_interface|CO2_only`, `squared_again|linear_transform`, and `not_corrected|centered_same`.
- `peaks.json` has a top-level `systems` mapping for the four systems and `claims`. claims contains the fixed keys `absolute_IR_Raman_intensity`, `charge_state_structural_fingerprint`, `unique_IS_or_OS_assignment`, and `block_range_is_confidence_interval`. Each item must have a `verdict` (`supported`, `conditional`, or `not_established`), JSON Pointer `evidence`, and a nonempty `rationale`; optional `scope` may be nonempty text or a list containing one text item. Evidence should cover the actual intensity/mass, four-system mode table, OS-only data and missing IS comparison, and time blocks, as applicable. Evidence prefixes are `metadata:/...` or `peaks:/...`, pointing to the metadata object or to the systems mapping in peaks, respectively. For example, `peaks:/<system>/<mode>` and `peaks:/systems/<system>/<mode>` are equivalent pointers to a system mode.

### Input and deliverable details

- `/app/environment/assets/water_CO2/10ps.traj`
- `/app/environment/assets/water_CO2anion/10ps.traj`
- `/app/environment/assets/2K_CO2/10ps.traj`
- `/app/environment/assets/2K_CO2anion/10ps.traj`
- `/app/environment/assets/spectrum.py`
- Write `spectra.csv`, `peaks.json`, `metadata.json`, an executable `analysis.py`, and `report.md` to `/app/final/`. `python analysis.py ASSET_DIR OUTPUT_DIR` must recompute spectra and structured data from the public assets and be reproducible. The report must explain the supplied-script diagnosis, estimator, projection basis, block correlation, and what velocity spectra cannot establish about intensity or pathway.

Here `ASSET_DIR` is `/app/environment/assets/` and `OUTPUT_DIR` is `/app/final/`. Create `analysis.py` as part of your submission; no analysis script is supplied for this task.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Directory of supplied inputs and resources. |
| `/app/environment/assets/water_CO2/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/water_CO2anion/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/2K_CO2/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/2K_CO2anion/10ps.traj` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/environment/assets/spectrum.py` | Supplied calculation or helper tool. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |

The existing output-format summary is available at `/app/environment/assets/output-contract.json`. Use the scientific definitions and numerical conventions above.
