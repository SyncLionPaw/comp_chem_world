# Compare constant and temperature-scaled relaxation-time approximations

## Background

Constant relaxation time (CRT) and temperature-scaled relaxation time (SRT) may give different mobility errors and temperature slopes. What relationship emerges when these two types of metrics are compared?

## Task

Using the AMSET, CRT, and SRT mobility arrays for GaAs, GaN, and SnSe, compare model errors and temperature slopes at matching conditions, and determine which observed metrics SRT improves or worsens.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Compare CRT at fixed `10 fs` with SRT at `10 fs × (300 K/T)`. Match only concentrations, temperatures, and `xx/yy/zz` directions actually present in each data file; do not invent missing temperature points.
- Submit `results.json` for all matching conditions, covering every metric by material, concentration, and direction: `log_rmse=sqrt(mean(log10(mu_model/mu_amset)^2))`; slope is `(ln(mu_maxT)-ln(mu_minT))/(ln(maxT)-ln(minT))`.
- Assess SRT using the actual errors and slopes; AMSET is the reference within this task's arrays, not experimental truth. Do not transfer error or correlation statistics for the complete source dataset into this task.
- Submit a reproducible `analysis.py`, run record `run.log`, and scientific summary `report.md`. The script must read the public arrays and generate results using `python analysis.py --inputs environment/assets --output final`; the record format is specified in the public output contract.
- Write all four required files—`results.json`, `analysis.py`, `run.log`, and `report.md`—to `/app/final/`. Record `run.log` as the JSON object specified in the public output contract.
- Report fields, coverage requirements, and format are specified in `environment/assets/public/output-contract.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/raw_data/unpacked/` | Transport data for the materials and methods listed above |
| `/app/environment/assets/public/output-contract.md` | Public submission contract |

The working directory is `/app`. Inputs are under `environment/assets/raw_data/unpacked/` in the `mobility/` material directories; use each of GaAs, GaN, and SnSe's `AMSET_transport.json`, `CRT_transport.json`, and `SRT_transport.json`. Write results to `/app/final/`.

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/results.json` | Quantitative results |
| `/app/final/analysis.py` | Reproducible analysis code |
| `/app/final/run.log` | JSON execution record |
| `/app/final/report.md` | Scientific report |
