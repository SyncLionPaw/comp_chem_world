# 任务：TNEP 极化率与 QM7B 盲验证

## 背景

使用所给原始模型和构型，验证给定资料 Table 2 中的分子极化率以及 QM7B 偶极和极化率。

## 任务

选择相应模型、识别不同体系的物理口径，组织并实现推理。不得获取外部验证标签。

公开材料位于 `environment/assets/inputs/`（当前运行布局亦可通过 `/app/inputs/` 访问），包括预训练模型和下列构型：

| system_id | 构型文件 | 帧数 |
|---|---|---|
| alpha_h2o | test-positions-alpha-h2o.xyz | 500 |
| alpha_h2o_dimer | test-positions-alpha-h2o-dimer.xyz | 500 |
| alpha_h5o2plus | test-positions-alpha-h5o2plus.xyz | 500 |
| qm7b_dipole | test-positions-qm7b-dipole.xyz | 1443 |
| qm7b_polarizability | test-positions-qm7b-polarizability.xyz | 1443 |

本题不包含液态水极化率；不得自行替换被测体系或减少帧数。工具、精度、批处理和物理约定的实现由你决定，题目不提供引擎路线或处理配方。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

### 精度与数值条件

将分子体系和 QM7B 的各项误差与发表值比较，须满足 `|log10(recomputed / published)| <= 0.5`。九分量张量须对称：双精度逐对容差为 `atol=1e-6 bohr³, rtol=1e-6`；单精度为 `atol=1e-4, rtol=1e-4`。数值须有限。请选择并记录可复现的模型推理路线；题目未规定修正步骤。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/inputs/` | 本题的来源材料与科学输入。 |

写入 `/app/final/`：`results.json`、五体系预测 NPZ、非空 `build.log` 和 `run.log`。

- `engine`：`name`、`version`、`build_command`、`log_sha256`（两个日志的文件校验值）。单精度设置 `precision: float32`，双精度设置 `precision: float64`。省略时按双精度比较。
- `predictions`：system_id 到相对 NPZ 路径的映射。
- 分子和 QM7B 极化率数组键为 `polarizability`，形状 `(n_frames, 9)`，行优先 `xx,xy,xz,yx,yy,yz,zx,zy,zz`，单位 bohr³；QM7B 偶极键为 `dipole`，形状 `(n_frames, 3)`，单位 e·bohr。预测保存逐构型的模型物理量。将 QM7B 结果与发表误差比较时，按给定资料所述口径归一化。
- `conventions` 必须含 `molecular_polarizability`、`offdiag`、`qm7b`，分别解释你的物理口径判断和实现。说明各物理口径判断的依据。`qm7b` 使用 `per-cell`、`per-molecule` 或 `per-atom` 声明所存物理量的口径，并说明给定资料误差指标如何归一化；存储口径和指标归一化可以不同。按给定资料的指标口径，将 QM7B 结果与发表误差比较。词表不替你决定正确的存储口径。
