# 任务：高压 SiO₂ 状态方程与相稳定性

## 背景

现有 `low_quartz`、`coesite`、`stishovite`、`pbo2`、`rosiaite`、`pyrite` 六种 SiO₂ 相的 ACE 和 DFT 能量-体积数据。比较其状态方程和高压相稳定性，并分析两种模型的一致之处、差异及适用范围。

## 任务

分析两种模型中的全部六种相，并将数值结果、摘要和图表提交至 `outputs/`。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

比较 ACE 和 DFT 中的全部六种相。依据给定的化学式单元数和参考能量，将晶胞数据归一化到化学式单元。拟合窗口须覆盖源曲线至少 80% 的点；`parameters_json` 须包含配对的 `curve_volume_A3_per_fu` 和 `curve_energy_eV_per_fu` 数组，且至少有 20 个按体积排序的样本。每条曲线从 0 GPa 起至少报告 20 个焓样本，间隔不超过 0.5 GPa；相对焓以 stishovite 为基准，且仅在共同有效区间内填写。对两种模型列出共同支持区间内的全部相对，记录交点或无交点，并注明结论是条件性的还是覆盖全部六相。

量化留一残差、拟合窗口敏感性和方法敏感性。敏感性分析将全数据 PCHIP 分别与两端各删一个点的 PCHIP、全数据 CubicSpline 比较；在共同支持区间取 201 个等距压力，逐点最小化 E(V)+PV，并报告最大绝对焓差。所有结果须一致。CSV 使用带表头的 UTF-8 格式，JSON 须有效，数值须有限。

只报告有效拟合窗口。各相和模型的曲线 RMSE 上限为保形留一误差与全数据 BM3 残差中较大者的 1.25 倍，再加 0.03 meV/原子。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `inputs/high_pressure/energy_volume/` | 目录内 `README.txt` 说明数据列顺序、化学式单元数和 DFT 参考能量。 |

| 路径 | 内容 |
| --- | --- |
| `outputs/normalized_eos.csv` | `phase,model,n_formula_units,V_A3_per_fu,E_eV_per_fu` |
| `outputs/eos_parameters.csv` | `phase,model,eos_form,parameters_json,n_points,fit_rmse_meV_per_atom,fit_window_Vmin_A3_per_fu,fit_window_Vmax_A3_per_fu,fit_valid`；`parameters_json` 还须含上述配对曲线数组。 |
| `outputs/enthalpy.csv` | `phase,model,P_GPa,V_A3_per_fu,H_eV_per_fu,relative_H_meV_per_fu,fit_valid,relative_valid,reason` |
| `outputs/crossings.csv` | `model,phase_a,phase_b,status,P_low_GPa,P_high_GPa,deltaH_uncertainty_meV_per_fu,domain_basis,reason`；`status` 为 `crossing` 或 `no_crossing_in_common_supported_domain`。 |
| `outputs/summary.json` | 包含 `units`（volume=`A^3/FU`、energy=`eV/FU`、pressure=`GPa`）、`method`、`valid_domain`（逐 phase/model 记录 `Pmin_GPa`、`Pmax_GPa`）、`phase_results`（全部 12 个组合的条件性结论及 `relative_H_at_0_meV_per_fu`、`relative_H_min_meV_per_fu`、`relative_H_max_meV_per_fu`）和 `uncertainty`。量化 `max_loo_residual_meV_per_atom`、`max_fit_window_sensitivity_meV_per_atom`、`max_method_sensitivity_meV_per_atom`；`fit_window_scan` 及 `method_scan` 各含 12 条记录，字段分别为 `phase,model,trim_each_end_points,retained_fraction,Vmin_A3_per_fu,Vmax_A3_per_fu,common_pressure_max_GPa,max_abs_H_change_meV_per_atom` 和 `phase,model,reference_method,comparison_method,common_pressure_max_GPa,max_abs_H_change_meV_per_atom`。 |
| `outputs/figures/` | 12 张 `eos_<phase>_<model>.png`，以及 `enthalpy_ace.png`、`enthalpy_dft.png`、`deltaH_ace.png`、`deltaH_dft.png`；共 16 张非空、可检查的 PNG。 |
