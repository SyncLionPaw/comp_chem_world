# Analyse directional mobilities and the limits of harmonic mechanism-combination estimates

## Background

A material's mobility tensor varies with carrier concentration, temperature, and direction. How do mechanism-specific mobilities relate to overall mobility? Under what conditions is a harmonic estimate constructed from macroscopic mobility applicable?

## Task

Using the supplied transport arrays for GaAs, GaN, Si, and SnSe, compare overall mobility with each mechanism mobility at matching material, concentration, temperature, and direction, and assess the bias of the harmonic estimate.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Following the public output contract, submit `results.json` for every input concentration, temperature, and `xx/yy/zz` direction of each material. Compute `harmonic_proxy=1/sum(1/mu_mechanism)` and `(harmonic_proxy-overall)/overall` for each condition.
- Report mechanism-limiting trends for each material, directional differences in SnSe, and use actual results to explain the applicability limits of the macroscopic harmonic estimate. See the public output contract for evidence-coverage requirements.
- Submit a reproducible `analysis.py`, run record `run.log`, and scientific summary `report.md`. The script must read the public arrays and generate results using `python analysis.py --inputs environment/assets --output final`; the record format is specified in the public output contract. Do not substitute values transcribed from papers for analysis of the arrays.
- Write all four required files—`results.json`, `analysis.py`, `run.log`, and `report.md`—to `/app/final/`. Record `run.log` as the JSON object specified in the public output contract.
- The format and fields for `report.md` are specified in `environment/assets/public/output-contract.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/raw_data/unpacked/` | Transport data for the materials and methods listed above |
| `/app/environment/assets/public/output-contract.md` | Public submission contract |

The working directory is `/app`. Inputs are under `environment/assets/raw_data/unpacked/` in the `mobility/` material directories; use each of GaAs, GaN, Si, and SnSe's `AMSET_transport.json`. Write results to `/app/final/`.

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/results.json` | Quantitative results |
| `/app/final/analysis.py` | Reproducible analysis code |
| `/app/final/run.log` | JSON execution record |
| `/app/final/report.md` | Scientific report |
