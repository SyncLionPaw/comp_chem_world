# Task: Analyse differential Li/Mg charge densities using consistent cells and references

## Background

`environment/assets/Li/` and `environment/assets/Mg/` each hold three total charge densities: `host_ion` (host plus the inserted ion), `host` (the TiS2 host with that ion removed), and `ion` (isolated Li or Mg), each with its `CONTCAR`. Only these Li and Mg inputs are used, and no new DFT is required.

## Task

Compute the Li and Mg first-grid total-density differences, check the compatibility of the three files of each ion, and decide whether the defined observables — the integral, the peak, and the threshold volume fraction — establish a Li/Mg valence-electron polarization ordering.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Read only the first total charge-density grid of each CHGCAR, stopping before the PAW augmentation occupancies and excluding later magnetization grids. Truncated, missing, or non-finite grid values are an error and must never be padded with zeros. With stored value D, cell volume V, and N grid points, the density is `rho = D/V` and the difference is `delta_rho = rho(host_ion) − rho(host) − rho(ion)`; the integral is `delta_N = sum(delta_rho) * V / N`, and when the three cells agree, `sum(delta_D)/N` must reproduce it. Report `cell_volume_A3` in Å³, `integral_delta_e` in e, `max_abs_delta_e_per_A3` as `max|delta_rho|`, and `volume_fraction_abs_gt_0.004` as the grid fraction with `|delta_rho|` above 0.004 e Å⁻³.

The three files of an ion must share grid shape and lattice vectors (1e-4 Å). For the geometry check, identify the inserted ion in `host_ion`, match every remaining atom one-to-one by element against `host`, and match the inserted ion against `ion`, using minimum-image distances with a 0.01 Å tolerance and never reusing a target atom; coordinates may be Direct or Cartesian.

The interpretation fields record that these integrals, peaks, and threshold volume fractions do not establish a Li/Mg valence-electron polarization ordering. That boundary concerns only these observables; it does not rule out other CHGCAR valence analyses.

### Input and deliverable details

Read the CHGCAR and CONTCAR files under `environment/assets/Li/` and `environment/assets/Mg/`.

Write `polarization.json` with `schema_version` 2; a `Li` and an `Mg` object, each with `grid` as three integers, `cell_volume_A3`, `integral_delta_e`, `max_abs_delta_e_per_A3`, and `volume_fraction_abs_gt_0.004`; a `checks` object with `cells_and_grids_compatible`, `geometry_matches`, and `electron_count_closed` (true only when `|integral_delta_e|` is below 0.001 e for both ions); and an `interpretation` object with `observable` = `first_grid_total_density_difference`, `valence_order_status` = `insufficient_evidence`, and `reason` = `no_defined_valence_polarization_metric`.

Generate `report.md` from that JSON with the provided renderer so the two agree:

```text
python environment/assets/render_report.py polarization.json report.md
```

Absolute comparison tolerances are 1e-4 electrons for integrals, 1e-4 Å³ for volumes, and 0.002 for volume fractions. The peak tolerance is max(1e-6, 0.001 × |reference peak|) in its declared units.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `environment/assets/Li/` | Directory of supplied inputs and resources. |
| `environment/assets/Mg/` | Directory of supplied inputs and resources. |

| Path | Contents |
| --- | --- |
| `/app/polarization.json` | Required result; use the contents and format specified above. |
| `/app/report.md` | Required result; use the contents and format specified above. |
