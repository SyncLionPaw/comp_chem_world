## 背景

激发能导数是对角量，不能给出态间非对角矩阵元。本任务沿一个 C=O 主导正常模式测量态导数，并另行计算范围受限的 S0–S1 核吸引导数算符投影。

## 任务

独立优化中性苯甲酮（C13H10O，24 个原子）并计算笛卡尔 Hessian，选择 C=O 伸缩投影最大的模式。在优化几何及沿该模式正负位移的三个逐次减半步长处，使用同一种固定响应近似（full TDDFT 或 TDA）计算最低三个单重态和三重态根。通过最大化跃迁密度重叠代理量绝对值之和，将位移态与参考态一对一匹配；根编号可以改变。对每个自旋、参考根和步长报告 `[E_n(+Q)-E_n(-Q)]/(2Q)`。另行计算范围受限的 S0–S1 算符投影，复用已保存的参考单重态 root-1 数组和未修改参考日志，不得为该参考态另跑 SCF/TD。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 h5py、NumPy、PySCF、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，见 `/app/AGENTS.md`：用 SSH 别名 `hpc`，远程工作目录使用唯一的 `~/submit-jobs/<task>-<utc>-<rand>/`，再核验科学结果。

在本题运行预算内使用任务配置的远程执行环境。几何、Hessian、模式、参考/位移根和算符须使用一致的电子结构及模式方案。原子质量使用 PySCF 同位素平均值（`atom_mass_list(isotope_avg=True)`）。固定模式相位，使归一化质量加权本征向量与归一化 C=O 伸缩向量的点积非负：沿 C→O 单位轴，C、O 原子分量分别为 `-axis/sqrt(m_C)`、`+axis/sqrt(m_O)`，其余分量为零，随后归一化。固定 S1 电子态相位，使 AO 跃迁密度绝对值最大的分量非负。自行选择三个正 Q 步长（严格逐次减半）及一对一根映射。对原子 A 和笛卡尔方向 k，计算 `O_Ak=-Z_A*(int1e_iprinv+transpose)`，与单重态跃迁密度 `2*(X+Y)` 收缩，并用 `mode_Ak/sqrt(m_A)` 投影；不得重复乘核电荷。以 Hartree/(bohr·sqrt(amu)) 报告带符号投影。使用三个逐次减半的 Bohr 步长，对逆距离原点有限差分验证。最小步长的分量及投影误差须在现有 Richardson O(h²) 截断包络与 `64*eps*nao²` 浮点下限之内。

优化器接受点和最终频率独立复核的最大绝对梯度均须 ≤ `1e-4 Eh/bohr`。原始 Hessian 相对其对称部分的最大元素和 Frobenius 反对称比均须 ≤ `1e-4`。独立重建的原始/对称谱须稳定，逐模差异 ≤ `0.1 cm⁻¹`；66 个模式均须为正。完整谱和所选频率须在 `0.01 cm⁻¹` 内复现；结构、最终梯度和所选模式须对应同一几何（坐标差 ≤ `1e-9 Å`）。明确说明算符范围：它是单参考线性响应单电子跃迁密度近似，不是 Gaussian-16 波函数或多参考结果，也不推广至三重态，不代表自旋轨道耦合或绝对 ISC 速率。不得将对角导数称作非对角算符。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/benchmark.json` | 基准参数与计算条件。 |

写入 `/app/final/`，提交 `structure.xyz`、`mode.json`、`state_tracking.csv`、`derivatives.csv` 和 `s0_s1_offdiag_operator.json`。可在 `diagnosis.md` 中补充可选说明。精简格式中，`mode.json` 的 `selected_mode_index_zero_based` 填写从计算所得振动谱选出的模式索引，从零计数。

若 `native/optimization_summary.json` 没有 `pyscf_version`，须在 `mode.json` 报告 `engine_version`；二者都存在时必须一致，不能猜测版本。

`state_tracking.csv` 恰有 36 行，列为 `step_index,step_Q_Angstrom_sqrt_amu,multiplicity,sign,reference_root,selected_displaced_root`。`derivatives.csv` 恰有 18 行，列为 `step_index,step_Q_Angstrom_sqrt_amu,multiplicity,reference_root,central_derivative_eV_per_Angstrom_sqrt_amu`。step 为 1–3；multiplicity 为 `singlet` 或 `triplet`；sign 为 `minus`/`plus`；根为 1–3。

算符 JSON 须含 `analytic_projection_hartree_per_bohr_sqrt_amu`、三个值的 `origin_steps_bohr`、三个值的 `projection_hartree_per_bohr_sqrt_amu` 和 `scientific_scope`。换算值 `analytic_projection_eV_per_angstrom_sqrt_amu` 可省略。输入背景见 `/app/inputs/benchmark.json`。

保留以下实际执行证据；仅提供相符数值不能证明计算真实执行。

| 原生证据 | 必需内容 |
|---|---|
| `optimization_summary.json`、`<accepted_attempt>/evaluation_*.npz`、`final_gradient.npz`、`final_frequency_gradient.npz`、`final_frequency_gradient.log`、`optimized_geometry.xyz`、`frequency.log`、`independent_cartesian_hessian_hartree_per_bohr2.npy` | summary 含 `scf_converged`、`functional`、`basis`、可选 `pyscf_version`（若缺失，compact `mode.json` 提供 `engine_version`）、`grid_level`、启用时形如 `{enabled, auxbasis}` 的 `density_fitting`（辅助基组须与日志一致）、`accepted_attempt`、`gtol_hartree_per_bohr`、`final_energy_hartree`、`max_abs_gradient_hartree_per_bohr`、`rms_gradient_hartree_per_bohr`、`frequency_recheck_max_abs_gradient_hartree_per_bohr`、`frequency_recheck_rms_gradient_hartree_per_bohr`、`frequency_recheck_energy_hartree`。每个 evaluation/梯度 NPZ 含 `coordinates_angstrom (24,3)`、`gradient_hartree_per_bohr (72)`、标量 `energy_hartree`。Hessian 为 `(24,24,3,3)` Hartree/bohr²。频率日志须含 `converged SCF energy` 和 `RKS`；梯度日志须含 `converged SCF energy` 和 `Gradients`。 |
| `mode_evidence.npz` | `mass_weighted_modes (66,24,3)`、`frequencies_cm1 (66)`、`co_stretch_overlap_squared (66)`。 |
| `reference_tddft.log`、六个 `q<1..3>_<minus|plus>_tddft.log`、42 个对应根 NPZ、六个 `q<step>_<sign>.xyz` | 保留每份完整原生日志。七份日志各含六条 `NATIVE_QC_ROOT` JSON 记录（`method`、`spin`、`root`、`excitation_energy_hartree`、`excitation_energy_eV`、`oscillator_strength`、`response_approximation`）以及原生文本标记 `converged SCF energy`、`XC functionals = <functional>`、`basis = <basis>`、`grids dens level: <integer>`（启用密度拟合时还需 `auxbasis = <basis>`）。每个根 NPZ 含 `td_x`、`td_y`、`mo_coeff`、`mo_occ`、`excitation_energy_hartree`、`oscillator_strength`、`response_approximation`。保留六个 `reference_tddft_<singlet|triplet>_root<1..3>.npz` 和相应的 `q<step>_<sign>_tddft_<singlet|triplet>_root<1..3>.npz`。 |
| `s0_s1_offdiag_operator_evidence.npz`、`s0_s1_offdiag_operator.log` | 精确数组：`coordinates_bohr (24,3)`、`atom_charges (24)`、`masses_amu (24)`、`mass_weighted_mode (24,3)`、`contribution_factor (24,3)`、`raw_td_x`、`raw_td_y`、`phase_aligned_td_x`、`phase_aligned_td_y`、`mo_coeff`、`mo_occ`、`ao_transition_density`、标量 `excitation_energy_hartree`、`oscillator_strength`、`analytic_transition_moments_hartree_per_bohr (24,3)`、`finite_difference_transition_moments_hartree_per_bohr (3,24,3)`、`finite_difference_moment_absolute_errors_hartree_per_bohr (3,24,3)`、`finite_difference_projection_absolute_errors_hartree_per_bohr_sqrt_amu (3)`、`finite_difference_moment_error_envelope_hartree_per_bohr (24,3)`、`finite_difference_projection_error_envelope_hartree_per_bohr_sqrt_amu (1)`、`finite_difference_analytic_agreement (1)`、标量 `analytic_projection_hartree_per_bohr_sqrt_amu`、`finite_difference_projection_hartree_per_bohr_sqrt_amu (3)`、`fd_steps_bohr (3)`、标量 `state_phase_sign`、`mode_phase_sign`。矩/投影单位为 Hartree/bohr 和 Hartree/(bohr·sqrt(amu))；步长为 bohr。reader 检查 `NATIVE_OFFDIAG_OP <JSON>` 中的 `analytic_projection_hartree_per_bohr_sqrt_amu` 和 `finite_difference_projection_hartree_per_bohr_sqrt_amu`，以及 `NATIVE_OFFDIAG_OP_SOURCE <JSON>` 中的 `source_kind`、`reference_root_file`、`reference_log_file`、`mode_file`、`derivatives_file`、`response_approximation`、`functional`、`basis`、`grid_level`、`density_fitting`。 |

优化轨迹目录取摘要中 `accepted_attempt` 的值。原生来源记录的 `source_kind` 填 `reused_exact_saved_task_reference_singlet_root1`。原生文件路径相对于 `/app/final/native/`；报告与结构化产物直接位于 `/app/final/`。精简格式只在原生 `NATIVE_OFFDIAG_OP_SOURCE` 记录中将 `derivatives_file` 设为 `derivatives.csv`，不要在精简算符 JSON 中添加此键。旧详细格式的两处记录均使用 `derivatives.json`。可选说明可讨论根匹配对中心差分的影响、随步长减半趋于稳定的导数，以及单独的 S0–S1 算符投影能够说明什么。
