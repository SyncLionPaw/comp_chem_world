## 背景

苯甲酮具有低能羰基 n–π* 态。本任务考察在固定几何和数值设置时，交换-相关泛函如何影响这些态的能量与特征。

## 任务

独立优化中性苯甲酮（C13H10O，24 个原子；`O=C(c1ccccc1)c1ccccc1`），并确认其为极小值。在该几何下，使用两种确实不同的 TDDFT 泛函，计算最低三个单重态和三个三重态根，比较能量和态特征。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 h5py、NumPy、PySCF、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，按 `ikkem-slurm` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。

在本题运行预算内使用任务配置的远程执行环境。不得从任务答案几何开始。

两种泛函比较时固定优化几何、基组、响应近似、DFT 网格和密度拟合设置。两个泛函标签必须对应不同的 PySCF/libxc 泛函；同一泛函的别名不能算作一对。逐根报告激发能（Hartree）、振子强度（三重态必须恰为零）、主 NTO 对权重，以及按 AO 重叠度量得到的 24 原子 Mulliken 空穴/粒子总布居。每个布居向量之和须为一；这些是总布居，不是概率。结合布居向量与 NTO 重叠比较氧空穴和羰基粒子特征。使用主空穴/粒子 NTO 重叠和 3×3 配对相似度矩阵，报告使矩阵元素总和最大的对应一对一根映射；根编号本身不能确定态身份。根据匹配根的能量和 NTO 证据比较泛函敏感性。这些量不能确定自旋轨道耦合（SOC）或绝对系间窜越（ISC）速率。可在可选的 `decision.md` 中补充文字解释。

接受的优化器评估和最终几何的独立梯度复核，其笛卡尔分量最大绝对值都必须 ≤ `1e-4 Eh/bohr`。计算全部 66 个谐振频率且必须均为正值。保留原始笛卡尔 Hessian。相对于对称化 Hessian 的最大元素及 Frobenius 反对称比都必须 ≤ `1e-4`；原始与对称化谱均须稳定，逐模差异不超过 `0.1 cm-1`。根据所交 Hessian 独立重建时，每个频率须在 `0.01 cm-1` 内复现；无量纲 C=O 投影数组须符合 `rtol=2e-7, atol=2e-9`。频率、振动模式和投影须来自一致几何；优化器坐标与 `structure.xyz` 的差异须在 `1e-9 Å` 内。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/benchmark.json` | 基准参数与计算条件。 |

`final/result.json` 为精简结果，结构如下：一个 `response_approximation`（`full TDDFT` 或 `TDA`）；可选的 `functional_pair_rationale`；仅当原生日志未给出版本时才提供一个 `engine_version`；`methods` 恰有两个 `{functional, singlet, triplet}` 对象，每个自旋数组含三个按能量排序的根；`comparison` 含 `singlet` 和 `triplet` 对象，每个包含 `nto_similarity_3x3` 和你给出的 `root_mapping`（字符串键 `"1"`–`"3"`，整数值 `1`–`3`）。泛函标识符也用于原生文件名，仅使用英文字母、数字、下划线或连字符。

矩阵元素 `(i,j)` 为 AO 重叠度量下主空穴和粒子 NTO 重叠的绝对值乘积。每个根对象包含科学结果：`excitation_energy_hartree`、`oscillator_strength`、`leading_nto_pair_weight`、`hole_atom_mulliken`（24 个值）、`particle_atom_mulliken`（24 个值）。结果中的换算值 `excitation_energy_eV` 可省略。输入背景见 `/app/inputs/benchmark.json`。精简格式只接受以上键，不得与旧版 `schema`/元数据字段混用。

可在 `final/decision.md` 中补充科学说明。可选字段 `functional_pair_rationale` 可记录泛函选择理由。

所有交付物放入 `/app/final/`：

| 产物 | 必需证据 |
|---|---|
| `structure.xyz` | 优化后的 24 原子几何，原子顺序固定。 |
| `native/optimization_summary.json` | `accepted_attempt`、`gtol_hartree_per_bohr`、`grid_level`、`functional`、`basis`、`scf_converged`、`max_abs_gradient_hartree_per_bohr`、`rms_gradient_hartree_per_bohr`、`final_energy_hartree`、`frequency_recheck_max_abs_gradient_hartree_per_bohr`、`frequency_recheck_rms_gradient_hartree_per_bohr`、`frequency_recheck_energy_hartree`。 |
| `native/<accepted_attempt>/evaluation_*.npz` | `coordinates_angstrom` `(24,3)`、`gradient_hartree_per_bohr` `(24,3)`、标量 `energy_hartree`；保留优化器评估。 |
| `native/final_gradient.npz`、`native/final_frequency_gradient.npz` | 相同的三个键与形状；第二个数组是最终几何处独立计算的梯度。 |
| `native/final_frequency_gradient.log`、`native/frequency.log`、`native/optimized_geometry.xyz` | 独立梯度日志（含收敛 SCF 和梯度输出）及收敛 RKS/频率原生记录；优化 XYZ 与 `structure.xyz` 须在 `1e-10 Å` 内匹配。 |
| `native/cartesian_hessian_hartree_per_bohr2.npy` | 有限值原始笛卡尔 Hessian `(24,24,3,3)`，单位 `hartree/bohr^2`。 |
| `native/normal_modes.npz` | `frequencies_cm1` `(66,)`、`mass_weighted_modes` `(66,24,3)`、无量纲 `co_stretch_overlap_squared` `(66,)`；重建容差见上文。 |
| `native/<functional-lower>_tddft.log` | 保留每种方法的完整原生日志，含收敛 SCF、泛函、基组、网格、输入几何和密度拟合证据。恰含六条 `NATIVE_QC_ROOT ` 记录，每条 JSON 具有 `method`、`spin`、`root`、`excitation_energy_hartree`、`excitation_energy_eV`、`oscillator_strength`。其 `[INPUT]` 原子列表须与 `structure.xyz` 的顺序、坐标相同；启用密度拟合时须展示 `auxbasis`。 |
| `native/<functional-lower>_<singlet|triplet>_root<1..3>_nto.npz` | 每种方法六个根文件。必需数组：`coefficients` 与 AO `overlap` `(nao,nao)`、`weights` `(nocc,)`、`mo_coeff` `(nao,nmo)`、`mo_occ` `(nmo,)`、`td_x` 和 `td_y` `(nocc,nvir)`、标量 `excitation_energy_hartree`、标量 `oscillator_strength`。`coefficients[:,0]` 为主空穴 NTO，`coefficients[:,nocc]` 为主粒子 NTO。 |
| `decision.md` | 可选的科学说明。 |

原生记录必须证明实际计算及其设置。
