# 任务：速度振动谱与机理解释的独立审计

## 背景

由速度计算的振动密度谱可描述有限分子动力学轨迹中的涨落，但不直接给出绝对红外/拉曼强度，也未必能唯一识别反应路径。随任务提供的 `spectrum.py` 是需审阅的原始脚本；依据代码和轨迹独立诊断它对结构选择、速度处理和频谱解释的影响。

## 任务

从四条 Au/水界面轨迹重建 CO₂ 速度谱，分析弯曲和两类伸缩振动，并用键方向投影与分块稳定性检查模式指派。另作可复核的原始脚本实现诊断，区分结构/电荷态的有限样本指纹与内球/外球路径结论。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 只读 `/app/environment/assets/` 中的四条轨迹和原始脚本，使用 Python 3.12。帧间隔为 1 fs；保留 C、O、H 源质量，不作同位素质量缩放。各体系独立识别 CO₂，仅用三个原子的九个笛卡尔速度分量。
- 选取半开帧区间 `[start_frame, end_frame_exclusive)`，起点为 0–3000，长度至少 6500 且不超轨迹长度。记录逐体系原子索引、质量和帧范围；氢质量可用全列表或去重升序列表。
- `metadata.estimator` 记录 `kind`、`window`、`detrend`、`nfft`、`block_count`；Welch 还记录请求值 `nperseg`、`noverlap`。可用 periodogram、Welch 或 VACF/FFT 周期图路线 `vacf_fft`；采用其他科学合理的估计方法时，说明等价性、计算方法和模式指派依据。使用其他估计方法时，须经独立科学复核后才能给出评分。窗口为 Hann、boxcar 或 blackmanharris，去趋势为 constant、linear 或 false。`nfft` 可为 null 或所选序列长度至其四倍；补零不提高真实频率分辨率。分成 3–6 个连续块，每块至少 1024 帧。Welch 请求 `nperseg≥1024`，`0≤noverlap<nperseg`；实际段长和重叠按可用序列截取并报告。完整序列 PSD 不得以块谱平均替代，分块只用于峰位稳定性检查。
- `spectra.csv` 列为 `system,wavenumber_cm-1,power_arb`。频轴递增，从零开始并覆盖至少 3000 cm⁻¹，至少 100 点；可输出完整频轴或连续前缀，所有体系使用同一任意正强度比例。说明单位换算、Nyquist 频率和时间来源。频轴容差为 `1e-5 cm⁻¹`；归一化 PSD 容差 `atol=2e-5, rtol=2e-4`。
- 对每帧将相对速度投影到瞬时 C–O 键方向。两键投影 `dr1`、`dr2` 的和/差（除以 `sqrt(2)`）分别给对称/反对称伸缩；弯曲用两键的六个横向相对速度分量。分别在弯曲 `400–950 cm⁻¹`、对称伸缩 `900–1500 cm⁻¹` 搜索主峰；反对称伸缩在中性态 `2000–2700 cm⁻¹`、阴离子态 `1300–1950 cm⁻¹` 搜索。不得直接抄给定资料图峰位。
- `peaks.json` 为四体系的 bending/symmetric/asymmetric 峰提供 `wavenumber_cm-1`、`block_peaks_cm-1`、`stability_range_cm-1`、`status` 和非空 `rationale`。分块用 `numpy.array_split`，稳定范围为块峰 min/max，不是置信区间。可选 `range_kind=block_minmax` 与 `mode_source`（弯曲 `bond_transverse`、对称 `bond_rate_sum`、反对称 `bond_rate_difference`）若提供须正确。状态为 `resolved` 或 `unresolved`；未分辨需有非空理由。可选 `unresolved_reason` 为 `weak_in_total_PSD`（模式频带 PSD 峰低于总峰的 8%）、`block_drift`（块峰跨度至少 40 cm⁻¹）或 `mode_overlap`（与另一投影峰相距不超过 100 cm⁻¹）；须与实际诊断相符。已分辨峰须有总 CO₂ PSD 局部峰落在指派峰 `max(25 cm⁻¹, 2×频轴间距)` 内；这些是操作性筛查，不是普适物理标准。峰位和块峰容差为 `0.001 cm⁻¹`。
- `metadata.json` 记录逐体系 `selection`，每项含 `atom_indices`、`mass_u`、`hydrogen_masses_u`、`start_frame`、`end_frame_exclusive`，以及 `dt_fs`、`speed_of_light_cm_per_fs`、`Nyquist_cm-1`、`time_source`、估计器、`absolute_IR_or_Raman_intensity=false`、`mass_rescaled=false`、`provided_ensembles`、`missing_IS_comparison` 和 `script_diagnostics`。`provided_ensembles` 使用 `OS_neutral`、`OS_anion` 标签，可为四体系映射或两个态标签列表。脚本诊断记录 `loop_components`、`required_interface_components`、`example_system`、`atom_scope`、`VACF_transform`、`frequency_offset_cm-1`、`full_convolution_alignment` 及足够复核的说明；示例为 `water_CO2`；`required_interface_components` 表示完整界面速度数组的分量数；若同时报告 CO₂ 观测量的分量数，应使用独立字段，例如 `required_whole_interface_components` 和 `required_co2_components`。计数用整数或明确数字字符串表示，并从脚本/结构独立核对。类别为 `whole_interface|CO2_only`、`squared_again|linear_transform`、`not_corrected|centered_same`。
- `peaks.json` 顶层含四体系 `systems` 映射和 `claims`；claims 含固定键 `absolute_IR_Raman_intensity`、`charge_state_structural_fingerprint`、`unique_IS_or_OS_assignment`、`block_range_is_confidence_interval`。每项必须有 `verdict`（`supported`、`conditional`、`not_established`）、JSON Pointer `evidence` 和非空 `rationale`；可选 `scope` 为非空文本或单文本列表。证据应覆盖实际的强度/质量、四体系模式表、OS-only 与缺失 IS 对照、时间块等依据；指针前缀为 `metadata:/...` 或 `peaks:/...`，分别指向 metadata 对象或 peaks 的 systems。例如，`peaks:/<system>/<mode>` 与 `peaks:/systems/<system>/<mode>` 是指向同一体系模式的等价路径。

### 输入与产物细则

- `/app/environment/assets/water_CO2/10ps.traj`
- `/app/environment/assets/water_CO2anion/10ps.traj`
- `/app/environment/assets/2K_CO2/10ps.traj`
- `/app/environment/assets/2K_CO2anion/10ps.traj`
- `/app/environment/assets/spectrum.py`
- 将 `spectra.csv`、`peaks.json`、`metadata.json`、可执行 `analysis.py` 和 `report.md` 写入 `/app/final/`。`python analysis.py ASSET_DIR OUTPUT_DIR` 从公开资产重算谱和结构化数据并可重复。报告解释原始脚本诊断、估计器、投影依据、块间相关性，以及速度谱不能支持的强度或路径推断。

上述 `ASSET_DIR` 为 `/app/environment/assets/`，`OUTPUT_DIR` 为 `/app/final/`。`analysis.py` 是需要编写的提交产物，并非预置分析脚本。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 给定输入与资源目录。 |
| `/app/environment/assets/water_CO2/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/water_CO2anion/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/2K_CO2/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/2K_CO2anion/10ps.traj` | 给定科学输入或资源；格式和单位见任务要求。 |
| `/app/environment/assets/spectrum.py` | 给定的计算或辅助工具。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |

输出格式摘要见 `/app/environment/assets/output-contract.json`。科学定义和数值约定以上文为准。
