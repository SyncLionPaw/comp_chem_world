# 任务：从给定的 SPC/E 轨迹恢复纵向介电响应

## 背景

给定样本包含 200 个真实构型，间隔 100 ps，取自更正后作业 9136 完成的 20 ns NVT 生产（9033 个 SPC/E 水分子、立方元胞）。完整来源记录在 `source_manifest.json`；公开样本为 `trajectory_sample.npz`。请在本地分析该轨迹——不要运行或提交分子动力学。这是项目生成的轨迹，不是原始发表的数据集，也不是对给定资料的完整各向同性复现。

## 任务

直接从坐标计算电荷结构因子

`S(k) = mean_frames(|sum_j q_j exp(-i k.r_j)|^2)`，

以及纵向电极化率 `chi_parallel(k) = e^2 S(k) / (epsilon0 kB T V k^2)`，前因子用 SI 单位（`k` 用 m⁻¹、`V` 用 m³），`T=300 K`，电荷取自给定数组。对每个壳层 `n=1..62` 平均三个笛卡尔矢量 `(n,0,0)`、`(0,n,0)`、`(0,0,n)`，`k=2*pi*n/L` 由实测盒长给出。由分子偶极涨落公式估计静态介电常数 `epsilon_w = 1 + e^2 <|M-Mbar|^2> / (3 epsilon0 V kB T)`，每个水分子偶极用两个最小镜像 H–O 矢量构造；对整条轨迹只计算一个全局平均偶极，用其涨落。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 统计：用 20 个连续的 1 ns 区块（每块十个 100 ps 帧）给出各 `chi_parallel(k)` 点的区块标准误；另用十个 2 ns 区块在同一批样本上做独立重分块检查。`k_min`、`chi_min`、`k_max`、`delta_k` 的不确定度来自 1 ns 区块自助法，使用 `numpy.random.default_rng(20261008)`、2000 次重抽样、按 `rng.integers(0, nblocks, size=nblocks)` 有放回抽取区块索引（四个特征共用同一抽取顺序），并报告有限倒格分辨率下限 `h/sqrt(12)`（波数）与 `h/sqrt(6)`（峰宽），`h=2*pi/L`。
- 数值约定：对 1 ns 与 2 ns 块均值曲线，逐点标准误差取块均值的样本标准差（`ddof=1`）除以块数的平方根。各特征的原始 bootstrap 散布取该特征有限且已解析重复值的样本标准差（`ddof=1`）；沿用已有 80% 解析率/null 规则与有限网格下限。计算中保留输入固定盒长的数值；可读取记录的固定盒长，或用足够精度累加（例如 float64），避免对相同 float32 盒长求均值时的舍入改变用于相位、k 和体积的盒长。

- 数值比较逐分量使用 `abs(提交值-参考值) <= atol + rtol*abs(参考值)`：`chi_k.csv` 的 k、chi 及两列块标准误差使用 `(rtol,atol)=(4e-6,2e-9)`；体积使用 `(2e-7,1e-5)`；epsilon 值与 jackknife 标准误差（含 2 ns 检查）使用 `(2e-7,1e-8)`；已解析特征值（含 2 ns 检查）、特征标准误差及原始 bootstrap 散布使用 `(2e-5,1e-8)`；盒长使用 `(0,0.002)` Å；有限网格下限元数据使用 `(1e-5,1e-8)`。保存时间间隔的绝对容差为 `1e-8` ps。离散计数、哈希、规定的 schema/单位及解析/null 状态必须与已说明的合同完全一致。

- 特征：在 `[0.15,1.20] Å⁻¹` 搜索低 k 谷（取 `chi` 最小的内部极小），在 `[2.0,4.5] Å⁻¹` 搜索过屏蔽峰（取最大值的首个索引），`delta_k` 为该峰半高处的插值全宽。索引 `i` 处的内部极小指 `chi[i] < chi[i-1]` 且 `chi[i] <= chi[i+1]`。取 `left` 为窗口最低索引下方一个格点、`right` 为窗口最高索引上方一个格点，则显著度为 `min(max chi[left..i-1], max chi[i+1..right]) - chi[i]`，噪声为 `sqrt(SE[i]² + max(max SE[left..i], max SE[i..right])²)`；仅当显著度超过该噪声的两倍时该谷才算分辨。峰的半高水平取抛物线细化后峰高的一半，两个交点由夹住该水平的相邻格点线性插值得到，取峰左侧最后一个交点与峰右侧第一个交点。内部极值用相邻三点抛物线细化，若拟合不是同类型极值则保留网格点。未分辨特征不要强行取值：`value`、`standard_error`、`bootstrap_standard_error` 全部为 `null`，并给出非空 `reason`。同时把 `valid_bootstrap_replicates` 写成 2000 次固定种子重抽样中该特征解出有限值的次数（`k_min` 与 `chi_min` 共用谷的计数）；当解出比例低于 80% 时该特征为未分辨。
- `final/analyze.py`：自包含程序（不依赖额外提交的辅助文件），按 `python3 /app/final/analyze.py --input /app/assets/trajectory_sample.npz --out /app/final` 运行，并可选接受 `--vectors CSV`（表头 `nx,ny,nz`）以用其他整数倒格矢量重算。它必须按给定时间排序帧后再分块，使输入数组逆序不影响结果，并以有界分块处理帧与模式。
- `final/chi_k.csv`：表头 `n_index,k_Ainv,chi_parallel,se_1ns,se_2ns,n_directions`，恰好 62 行。
- `final/observables.json`：顶层键恰为 `schema`(`ihf008-observables/v1`)、`temperature_K`、`selected_frames`、`selected_source_frame_indices`、`saved_interval_ps`、`block_length_ps`、`blocks_1ns`、`blocks_2ns`、`box_A`、`volume_A3`、`reciprocal_sampling`、`uncertainty`、`observables`。`observables` 恰含 `eps_w`、`k_min_Ainv`、`chi_min`、`k_max_Ainv`、`delta_k_Ainv`；每项含 `value`、`standard_error`、`units`、`status`、`reason`、2 ns 独立检查，以及自助法细节（`valid_bootstrap_replicates`、`bootstrap_standard_error`）；波数类特征另含 `finite_k_resolution_floor`。`reciprocal_sampling` 报告 `n_min=1`、`n_max=62`、`directions_per_shell`（62 个计数）与 `mode_vectors_sha256`（对按给定顺序的整数模式矢量三元组、按行主序小端 int16 序列化后取 文件校验值）。`uncertainty` 为对象，含数值 `blocks_1ns` 与 `feature_bootstrap` 对象，后者含数值 `resamples`(2000)、`seed`(20261008)、`resolution_floor_k_Ainv`(`h/sqrt(12)`) 与 `resolution_floor_delta_k_Ainv`(`h/sqrt(6)`)；这些键名必须与 `analysis_contract.json` 完全一致。
  `selected_source_frame_indices` 是所选输入帧索引的两元素 `[最小值, 最大值]`，不是完整索引列表；`eps_w` 另需给出 `independent_2ns_standard_error`；每项 `units` 必须与 `analysis_contract.json` 给出的字符串完全一致。
- `final/analysis.log`：输入哈希、数据窗口、帧/时间/区块元数据、盒子、模式矢量哈希、耗时，以及完成行 `status=complete`，每个字段写成一行 `key=value`（确切标记列表见 `analysis_contract.json`）。

提交物会在变换后的输入下重放（帧序反转、帧抽样、坐标平移、替代倒格矢量）并与独立计算的参考比较；伪造不确定度、依赖顺序的分块与伪造的输入哈希都会被拒绝。

### 输入与产物细则

- 输入：`/app/assets/trajectory_sample.npz`（另有 `analysis_contract.json`、`source_manifest.json` 供溯源）
- 输出：`final/analyze.py`、`final/chi_k.csv`、`final/observables.json`、`final/analysis.log`

程序不得超过 2,000,000 字节，其余三个文件各不得超过 100,000 字节。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/trajectory_sample.npz` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/analyze.py` | 完整字段、单位和内容按上文要求。 |
| `/app/final/chi_k.csv` | 表头 `n_index,k_Ainv,chi_parallel,se_1ns,se_2ns,n_directions`，恰好 62 行。 |
| `/app/final/observables.json` | 完整字段、单位和内容按上文要求。 |
| `/app/final/analysis.log` | 输入哈希、数据窗口、帧/时间/区块元数据、盒子、模式矢量哈希、耗时，以及完成行 `status=complete`，每个字段写成一行 `key=value`（确切标记列表见 `analysis_contract.json`）。 |
