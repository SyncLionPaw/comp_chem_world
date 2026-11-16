# First-Principles Carrier Scattering

## Overview

This benchmark is based on the study "**Efficient calculation of carrier scattering rates from first principles**" by Alex M. Ganose et al., published in *Nature Communications* (2021).

The study introduces an efficient first-principles treatment of charge-carrier scattering in semiconductors and insulators. AMSET combines electronic structure with material response parameters to predict scattering rates and transport coefficients. The central question is how physical scattering models and numerical approximations determine the reliability of mobility and thermoelectric predictions.

**Reference:** Alex M. Ganose et al., *Nature Communications*, 2021. DOI: [10.1038/s41467-021-22440-5](https://doi.org/10.1038/s41467-021-22440-5).

## Tasks

| Task | Description | Execution location / 计算位置 |
| --- | --- | --- |
| Task 55 | Compare angularly weighted scattering rates and resolve forward-scattering integration. | local（本地容器） |
| Task 56 | Analyse directional mobilities and the limits of harmonic mechanism-combination estimates. | local（本地容器） |
| Task 57 | Compare constant and temperature-scaled relaxation-time approximations. | local（本地容器） |
| Task 58 | Check Seebeck, conductivity, carrier-sign, and mobility consistency. | local（本地容器） |
| Task 59 | Generate and validate GaAs first-principles inputs for carrier-scattering calculations. | remote（远程计算） |
| Task 60 | Assess silicon transport convergence across meshes, energy windows, mechanisms, and concentrations. | local（本地容器） |
| Task 61 | Conduct open-ended research on reliable first-principles semiconductor transport. | local（本地容器） |

Execution location / 计算位置：`local` = 在任务容器内计算，无需远程/HPC；`remote` = 使用远程计算。此列描述科学计算位置，不是模型 API 或评分器的位置；不新增访问权限，也不代表运行已验收。本地 Oracle 回放不等于完成远程计算。原题的预算、方法、执行接口及证据要求仍然适用。

## Environment repair note (2026-11)

Task 061 retains the hashed scientific dependency lock and uses uv with longer download timeouts, retries and a BuildKit cache. It has no reference solution; the environment preflight checks imports before a model trial. See [environment repairs](environment-repairs.md).
