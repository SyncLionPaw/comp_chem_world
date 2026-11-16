# 任务：TNEP 张量模型的旋转等变性核验

## 背景

以所给 200 帧水单体构型和原始模型为起点，独立设计并执行秩-1 偶极和秩-2 极化率的旋转等变性实验。

## 任务

自行确定张量应如何变换、旋转如何构造、参考中心如何选择，以及数值误差如何分析。题目不提供张量变换公式、旋转生成算法或样例种子。

公开材料位于 `environment/assets/inputs/`（当前运行布局亦可通过 `/app/inputs/` 访问）；构型文件为 `test-positions-h2o-200.xyz`。原始与旋转后的几何都必须真实运行模型。不得只用未旋转结果生成变换后的预测，不得获取外部标签。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

### 坐标与数据编码约定

以下约定用于消除矩阵方向或文件格式的歧义，不规定你的研究方案：

- `R` 使用列向量约定；在坐标文件中表示 `x' = R(x-c)+c`。中心可声明 `origin` 或 `com`；后者使用 O=15.999、H=1.008。
- 200 个 R 均须属于 SO(3)，正交和行列式误差各不超过 `1e-10`，每帧转角至少 `0.2 rad`；旋转坐标须与所声明变换一致（最大偏差 `2e-5 Å`）。旋转设计、可复现种子和分布由你选择。
- 偶极单位 e·bohr，极化率单位 bohr³；九分量张量行优先排列。

### 数值精度与可复现性

双精度下，双精度下，最大偶极绝对残差不得超过 `1e-6 e·bohr`，最大极化率相对残差不得超过 `1e-6`；单精度下两者均不得超过 `1e-4`。数据须有限。根据提交数组中的残差核对四项摘要，容差为 `rtol=1e-3`、`atol=1e-12`。未旋转预测的 RMSE 须满足给定资料锚点窗口（log10 比值绝对值不超过 `0.75`）。

须对原始和旋转几何均实际运行原始模型。按下文记录真实引擎、精度、输入、预测和哈希，以便复现分析。

保留原生执行记录。数值检查比较所提交的数组和记录，不重跑推理引擎。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/inputs/` | 本题的来源材料与科学输入。 |

在 `/app/final/` 提交：

1. `equivariance.json`，含：
   - `engine`：`name`、`version`、`precision`（float32/single 或 float64/double）、`log_sha256`。
   - `rotation_protocol`：整数 `seed`、非空 `distribution`、`n_rotations=200`、`center`。
   - `frames`：按输入顺序编号 0–199；每帧提供 `frame`、`R`（3×3）、`mu_unrotated`/`mu_rotated`（3）、`alpha_unrotated`/`alpha_rotated`（9）。
   - `residual_summary`：`max_abs_mu`、`rms_mu`、`max_rel_alpha`、`rms_alpha`。令 `expected` 表示按相应张量秩的变换规律得到的参考张量，`actual` 为旋转后几何的预测。偶极逐元素残差为 `abs(expected-actual)`，极化率逐元素残差为 `abs(expected-actual)/(abs(expected)+1e-12)`。`max_abs_mu`/`rms_mu` 和 `max_rel_alpha`/`rms_alpha` 分别为对应残差在全部帧、全部分量上的最大值与均方根。对应秩的参考变换应自行推导。
2. `rotated-positions.xyz`：旋转几何。
3. `inference-unrotated.xyz`、`inference-rotated.xyz`：各 200 帧，几何分别绑定原构型和旋转构型；注释提供与 JSON 一致的 `dipole` 和 `polarizability` 数组。数值可以是带引号的 JSON 数字列表或带引号的空白分隔数字项；括号完整的 JSON 数字列表也可以不加引号。未加引号的空白分隔数列存在歧义，不接受。
4. `inference.log`：非空，含 `run=unrotated`、`run=rotated`，以及 `input_sha256`、`rotated_xyz_sha256`、`inference_unrotated_sha256`、`inference_rotated_sha256` 四项 `key=SHA-256`。`engine.log_sha256` 为此日志的哈希。
