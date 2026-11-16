# Check Seebeck, conductivity, carrier-sign, and mobility consistency

## Background

The relationships among the diffusion Seebeck coefficient, carrier sign, mobility, and conductivity depend on the model and unit conversions; transport-data coverage can also differ among materials.

## Task

Using the AMSET and CRT arrays for GaAs, p-GaAs, SnSe, Si, and CdS, compare Seebeck coefficients, check conductivity–mobility unit consistency, and analyze how the scattering model affects the conclusions.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- Cover every material, concentration, temperature, and `xx/yy/zz` direction in the public data. Report `S` in microvolts per kelvin and calculate `delta_S=S_amset-S_crt`.
- From AMSET conductivity and overall mobility, calculate `sigma_from_mu_S_m=abs(n_cm3)×1e6×e_C×mu_cm2_Vs×1e-4` and report `(sigma_from_mu_S_m-sigma_S_m)/sigma_S_m`; do not force to zero the difference between nominal doping and carrier normalization used in the data.
- Report carrier polarity, directional differences in SnSe, and model differences. Use energy dependence and transport moments to assess whether the relaxation-time factor cancels, and state the scope of applicability of the data to the diffusion term and phonon drag.
- When identifying `diffusive_only_materials`, distinguish the supplied source’s experimental comparison scope from the physical contributions included in the AMSET/CRT arrays; consult the attached documentation and supporting data.
- Submit a reproducible `analysis.py`, run record `run.log`, and scientific summary `report.md`. The script must read the public arrays and generate results using `python analysis.py --inputs environment/assets --output final`; the record format is specified in the public output contract. Do not substitute external external results for array analysis.
- Write all four required files—`results.json`, `analysis.py`, `run.log`, and `report.md`—to `/app/final/`. Record `run.log` as the JSON object specified in the public output contract.
- Report fields, coverage requirements, and format are specified in `environment/assets/public/output-contract.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/raw_data/unpacked/` | Transport data for the materials and methods listed above |
| `/app/environment/assets/public/output-contract.md` | Public submission contract |

The working directory is `/app`. Inputs are under `environment/assets/raw_data/unpacked/` in the `seebeck/` material directories; use each of GaAs, p-GaAs, SnSe, Si, and CdS's `AMSET_transport.json` and `CRT_transport.json`. Supporting PDF documents are supplied under `environment/assets/`. Write results to `/app/final/`.

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/final/results.json` | Quantitative results |
| `/app/final/analysis.py` | Reproducible analysis code |
| `/app/final/run.log` | JSON execution record |
| `/app/final/report.md` | Scientific report |
