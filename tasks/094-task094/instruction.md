# Task: Recover the longitudinal dielectric response from the supplied SPC/E trajectory

## Background

The supplied sample contains 200 authentic configurations at 100 ps intervals from the completed 20 ns NVT production of corrected job 9136 (9033 SPC/E waters, cubic cell). The full source is documented in `source_manifest.json`; the public sample is `trajectory_sample.npz`. Analyze the supplied trajectory locally — do not run or submit molecular dynamics. This is a project-generated trajectory, not an source-published dataset or a full isotropic reproduction of the supplied documentation.

## Task

Compute the charge structure factor directly from the coordinates,

`S(k) = mean_frames(|sum_j q_j exp(-i k.r_j)|^2)`,

and the longitudinal susceptibility `chi_parallel(k) = e^2 S(k) / (epsilon0 kB T V k^2)` with SI prefactors (`k` in m⁻¹, `V` in m³), `T=300 K`, and the supplied charges. Average the three Cartesian vectors `(n,0,0)`, `(0,n,0)`, `(0,0,n)` for each shell `n=1..62`, with `k=2*pi*n/L` from the measured box. Estimate the static dielectric constant from the molecular dipole fluctuation formula, `epsilon_w = 1 + e^2 <|M-Mbar|^2> / (3 epsilon0 V kB T)`, building each water dipole from the two minimum-image H–O vectors; compute one global mean dipole over the full trajectory and use fluctuations about it.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- Statistics: 20 contiguous 1 ns blocks (ten 100 ps frames each) for the pointwise block standard error of every `chi_parallel(k)`; an independent 2 ns reblocking check (ten blocks) on the same sample. Uncertainties for `k_min`, `chi_min`, `k_max`, `delta_k` come from a bootstrap over the 1 ns blocks with `numpy.random.default_rng(20261008)`, 2000 replicates drawing block indices with replacement (`rng.integers(0, nblocks, size=nblocks)`, same draw order for the four features), plus the finite reciprocal-grid resolution floors `h/sqrt(12)` (wavenumbers) and `h/sqrt(6)` (widths), `h=2*pi/L`.
- Numerical conventions: For each 1 ns or 2 ns block-mean curve, use the sample standard deviation (`ddof=1`) divided by the square root of the number of blocks for the pointwise standard error. For each feature's raw bootstrap spread, use the sample standard deviation (`ddof=1`) over its finite, resolved replicate values; retain the existing 80% resolution/null rule and finite-grid floors. Preserve the supplied fixed box lengths in calculations; use a recorded fixed-box value or sufficiently precise accumulation (for example, float64) so averaging identical float32 box entries does not change the box used for phases, k, and volume.

- Numerical comparisons use `abs(submitted-reference) <= atol + rtol*abs(reference)` componentwise: `chi_k.csv` k, chi and both block-error columns use `(rtol,atol)=(4e-6,2e-9)`; volume uses `(2e-7,1e-5)`; epsilon values and jackknife standard errors, including the 2 ns check, use `(2e-7,1e-8)`; resolved feature values (including the 2 ns check), feature standard errors and raw bootstrap spreads use `(2e-5,1e-8)`; box lengths use `(0,0.002)` Å; finite-grid-floor metadata use `(1e-5,1e-8)`. The saved time interval has absolute tolerance `1e-8` ps. Discrete counts, hashes, required schema/units and resolved/null status must match their stated contracts exactly.

- Features: search the low-k trough in `[0.15,1.20] Å⁻¹` (deepest interior local minimum, chosen by smallest `chi`), the overscreening peak in `[2.0,4.5] Å⁻¹` (first index of the maximum), and `delta_k` as the interpolated full width at half maximum of that peak. An interior local minimum at index `i` means `chi[i] < chi[i-1]` and `chi[i] <= chi[i+1]`. With `left` one grid point below the window's lowest index and `right` one grid point above its highest index, the prominence is `min(max chi[left..i-1], max chi[i+1..right]) - chi[i]` and the noise is `sqrt(SE[i]² + max(max SE[left..i], max SE[i..right])²)`; the trough counts as resolved only when the prominence exceeds twice that noise. The half-maximum level of the peak is half of the parabola-refined peak height, and its two crossings are linearly interpolated between the adjacent grid points bracketing that level, taking the last crossing below the peak and the first one above. Refine interior extrema with a parabola through the three adjacent points, keeping the grid point when the fit is not a same-type extremum. Report an unresolved feature rather than forcing a value: its `value`, `standard_error` and `bootstrap_standard_error` are all `null`, with a non-empty `reason`. Set `valid_bootstrap_replicates` to the number of the 2000 fixed-seed replicate draws in which the feature resolved to a finite value (`k_min` and `chi_min` share the trough count); a feature is unresolved when fewer than 80% of those draws resolve it.
- `final/analyze.py`: a self-contained program (no submitted helper files) run as `python3 /app/final/analyze.py --input /app/assets/trajectory_sample.npz --out /app/final`, optionally accepting `--vectors CSV` (header `nx,ny,nz`) to recompute with alternate integer reciprocal vectors. It must order frames by their supplied times before forming blocks, so reversing the input array leaves the results unchanged, and must process frames and modes in bounded chunks.
- `final/chi_k.csv`: header `n_index,k_Ainv,chi_parallel,se_1ns,se_2ns,n_directions`, exactly 62 rows.
- `final/observables.json`: top-level keys exactly `schema` (`ihf008-observables/v1`), `temperature_K`, `selected_frames`, `selected_source_frame_indices`, `saved_interval_ps`, `block_length_ps`, `blocks_1ns`, `blocks_2ns`, `box_A`, `volume_A3`, `reciprocal_sampling`, `uncertainty`, `observables`. The `observables` object contains exactly `eps_w`, `k_min_Ainv`, `chi_min`, `k_max_Ainv`, `delta_k_Ainv`; each is an object with `value`, `standard_error`, `units`, `status`, `reason`, the 2 ns independent check, and the bootstrap details (`valid_bootstrap_replicates`, `bootstrap_standard_error`); wavenumber features also carry `finite_k_resolution_floor`. `reciprocal_sampling` reports `n_min=1`, `n_max=62`, `directions_per_shell` (62 counts), and `mode_vectors_sha256` (content checksum over the integer mode-vector triples in supplied order, row-major little-endian int16). `uncertainty` is an object holding numeric `blocks_1ns` and a `feature_bootstrap` object with numeric `resamples` (2000), `seed` (20261008), `resolution_floor_k_Ainv` (`h/sqrt(12)`) and `resolution_floor_delta_k_Ainv` (`h/sqrt(6)`); these exact names are required, matching `analysis_contract.json`.
  `selected_source_frame_indices` is the two-element `[min, max]` of the selected input frame indices, not the full index list, `eps_w` also carries `independent_2ns_standard_error`, and every observable records `units` exactly as `analysis_contract.json` specifies.
- `final/analysis.log`: the input hash, data window, frame/time/block metadata, box, mode-vector hash, elapsed time, and the completion line `status=complete`, written as one `key=value` line per field (the exact token list is in `analysis_contract.json`).

The submission is replayed under transformed inputs (reversed frame order, subsampled frames, translated coordinates, alternate reciprocal vectors) and compared against an independently computed reference; fabricated uncertainty, order-dependent blocking, and forged input hashes are rejected.

### Input and deliverable details

- Input: `/app/assets/trajectory_sample.npz` (also `analysis_contract.json`, `source_manifest.json` for provenance)
- Outputs: `final/analyze.py`, `final/chi_k.csv`, `final/observables.json`, `final/analysis.log`

The program may be up to 2,000,000 bytes. Each of the other three files may be up to 100,000 bytes.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/trajectory_sample.npz` | Supplied scientific input or resource; see the task requirements for format and units. |

| Path | Contents |
| --- | --- |
| `/app/final/analyze.py` | Use the fields, units and contents specified above. |
| `/app/final/chi_k.csv` | header `n_index,k_Ainv,chi_parallel,se_1ns,se_2ns,n_directions`, exactly 62 rows. |
| `/app/final/observables.json` | Use the fields, units and contents specified above. |
| `/app/final/analysis.log` | Use the fields, units and contents specified above. |
