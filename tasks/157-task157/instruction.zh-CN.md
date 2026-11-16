# 任务：α-quartz 表面能与厚度效应

## 背景

现有五种表面取向（`001`、`011`、`100_alpha`、`100_beta`、`101`）的 DFT 弛豫 α-quartz slab，以及已发表的解理表面能。评估弛豫表面能、取向排序、厚度收敛性，并与解理值比较。

## 任务

审查所有 slab，拟合厚度依赖关系，估算表面能，并在 `outputs/` 中报告取向及弛豫前后比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

审查五种取向的全部 35 个 slab，检查组成和几何。每个取向拟合连续末尾 3 个和 4 个 slab 的窗口（每个拟合至少 3 个 slab），根据前两个晶胞矢量计算 `A=|a×b|`，并使用 `γ=(E_slab−Nμ)/(2A)`；`μ` 来自与弛豫表面能相同的 E(N) 拟合。按 `1 eV/Å² = 16.02176634 J/m²` 换算，并与给定解理能比较。`reconstruction` 使用 `cleaved_published_input` 或 `relaxed_from_slab`；解理参考的 `converged` 为 `not_applicable`，弛豫结果为布尔值。依据结果和不确定性推导 `near_degenerate` 或 `rank_N`，不得预设排序。未提供解理几何，因此能量比较不能确定逐原子的重构路径。

CSV 使用带表头的 UTF-8 格式，JSON 须有效，数值须有限。

有效拟合窗口的 RMSE 不超过 0.004 eV。弛豫结果仅在拟合有效且各有效厚层窗口的结果跨度不超过 0.002 eV/Å² 时可填 `converged=true`。弛豫不确定度须至少覆盖该跨度且不超过 0.002 eV/Å²，解理值舍入不确定度为 [0.0005, 0.001] eV/Å²。`surface_energy.<orientation>` 含 `gamma_relaxed_eV_per_A2`、`gamma_cleaved_eV_per_A2`、`relaxation_energy_drop_eV_per_A2`。`ranking` 含 `cleaved_low_to_high`、`relaxed_low_to_high`、`cleaved_near_degenerate`、`relaxed_near_degenerate`、`rank_change_near_degenerate`、`rank_change_robust`。近简并取向用 `near_degenerate`，其余用 `rank_<名次>`。

记录 `method.conversion_eV_per_A2_to_J_per_m2`。每个取向的 `orientation_audit` 含 `n_slabs`、`N_atoms`、`stoichiometry`、`area_A2`；`reconstruction_effect` 含 `drop_eV_per_A2`、`drop_J_per_m2` 及布尔值 `significant`。同时记录 `uncertainty.relaxed_surface_energy_eV_per_A2.<orientation>`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `inputs/` | 包含 slab 文件、已发表的解理表面能和方法说明。 |

| 路径 | 内容 |
| --- | --- |
| `outputs/orientation_audit.csv` | `orientation,slab_file,N_atoms,N_Si,N_O,area_A2,atomic_span_A,cell_vectors_A,stoichiometry,geometry_note` |
| `outputs/slab_fit.csv` | `orientation,reconstruction,window_files,window_N_min,window_N_max,slope_eV_per_atom,intercept_eV,residual_RMSE_eV,n_points,fit_assumptions` |
| `outputs/surface_energy.csv` | `orientation,reconstruction,area_A2,gamma_eV_per_A2,gamma_J_per_m2,uncertainty_eV_per_A2,uncertainty_J_per_m2,bulk_reference,converged,decision,reason` |
| `outputs/summary.json` | 包含 `method`、`orientation_audit`、`bulk_reference`、`surface_energy`、`reconstruction_effect`、`ranking`、`uncertainty`、`limitations`、`figure_panels`。记录换算因子、逐取向审计与 `mu_eV_per_atom`、弛豫/解理能及差值、能量降低及显著性、不确定度、两种排序、近简并集合和排序稳健性。`figure_panels` 包含 `orientation_specific_E_N_fits` 和 `cleaved_vs_relaxed_surface_energy`。 |
| `outputs/figures/thickness_fit.png` | 在清晰可读的 PNG 中展示两项科学比较，排版不限。 |
