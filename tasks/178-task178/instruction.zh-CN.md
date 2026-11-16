# 任务：评估结构与动力学主张

## 背景

数据包括早期经典模拟和 70 ps 从头算构型、Li–Li RDF、配位与角度直方图、群体序列、总 X 射线曲线、MSD 与非高斯参数轨迹，以及 distinct Li–Li van Hove 矩阵。文件单位和定义见 给定的 `units.txt`、`scattering_units.txt`、`dynamics_units.txt`；`experimental_sans.txt` 仅提供长度尺度背景。

## 任务

评估短接触锂链和氧桥的证据、其群体与交换、接触到鞍点的自由能尺度、X 射线的结构判别能力、物种相对迁移能力与非高斯行为，以及小间距 distinct Li–Li van Hove 强度的变化。说明证据范围与局限。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

RDF 距离从 pm 换算为 Å，在 298.15 K 使用 `F(r) = −kBT ln g(r)`。接触峰为 `2.2 < r < 2.8 Å` 内 g(r) 最大值；势垒为 `2.7 < r < 3.3 Å` 内 F 最大值减去 `2.2 < r < 2.7 Å` 内 F 最小值，仅用 `g(r) > 10⁻⁸` 的采样点。若 `0.5 ≤ 势垒/(kBT) ≤ 2`，按操作性判据视为与 kBT 相当。

群体序列第1列是帧索引，不是时间。图3第5组数据及图例将 `pop_b` 标为 chain（区域I）、`pop_c` 标为 intermediate chain（II）、`pop_a` 标为 no chain（III）。保留原始分类，分别报告原百分比，不重新归一化；这些数据未定义为互斥分区。接触比例为所选序列各百分比的算术平均，多数指超过50%。`contact_cn_higher_than_isolated` 比较 I/chain 与给定标记的 III/no-chain 分布；这不代表 III 中每个 Li 均无接触。图4将 `window_blue` 对应 I、`window_red` 对应 III、`window_all` 对应无条件平均；比较 I 与 III 的总 Li–O 配位众数，而非均值或无条件直方图。图2区域边界为 3.0 和 4.15 Å，未规定端点归属。

在 `frame_late.xyz` 中分析拓扑时，使用最小镜像周期边界、Li–Li 距离≤3.0 Å、Li–O 距离≤2.6 Å；以相同边界下 O–H 距离<1.25 Å 判定水氧。这些是本题分析截断。至少含三个 Li 的连通分量为链状分量，不表示线性几何或宏观网络。根据所给构型和序列评估系综群体占比证据。

X 射线计算 q 单位为 nm⁻¹（除以10），实验 q 单位为 Å⁻¹且未作垂直对齐。曲线按 q 排序并对重复 q 取均值后插值。在含端点的 0.5–8.0 Å⁻¹ 范围内取300个等距 q 点，用线性插值并以最小二乘拟合一个垂直偏移；偏移后无量纲 RMSE≤0.10 为操作性吻合判据。

MSD 时间单位 ps、数值单位 pm²（除以10,000换算为 Å²）；报告各物种末值，并据此排序。非高斯时间为第1列除以1000。使用共同的 0.1–30 ps 区间（21点）及峰值 α₂。峰值>0.10 是描述性信号，不是显著性检验；仅当 Li>0.10 且水氧、阴离子氮各≤0.10 时，称为 Li 特异信号。轨迹代表选定原子，不是质心运动。

Distinct van Hove 矩阵按行表示时间、按列表示距离。分别对时间<5 ps 和>20 ps、距离分箱中心<0.5 Å 的所有元素求均值。若后期均值更高，则支持不同 Li 离子占据先前位置的交换相容运动；这不测量驻留时间或交换速率。评估现有动力学数据是否呈现稳定的长时扩散区间，并说明定量扩散估计所依据的证据、采样与不确定性。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 用于核验科学主张的公开证据。 |

输入位于 `environment/assets/`。将结果写入 `/app/final/claim.json`，含布尔字段 `nanochains_with_short_contacts`、`contact_population_is_majority`、`barrier_comparable_to_kT`、`transient_exchange`、`contacts_share_water`、`contact_cn_higher_than_isolated`、`xray_s_agrees`、`xray_s_proves_short_chains`、`diffusion_coefficients_quantitatively_reportable`、`dynamic_heterogeneity_specific_to_lithium`；数值字段 `contact_distance_A`、`contact_fraction_percent`、`vhcf_small_r_mean_before_5ps`、`vhcf_small_r_mean_after_20ps`；`contact_series`（`pop_a`、`pop_b` 或 `pop_c`）；含数值 `Li`、`H2O`、`TFSI` 的 `msd_final_A2` 对象；以及按迁移能力从高到低排列这些物种的 `apparent_mobility_order`。`limits` 数组至少包含两个不同标识：`trajectory_about_70ps`、`single_density_functional`、`finite_cell`、`single_concentration`（分别表示采样时长、泛函选择、盒尺寸及浓度覆盖范围）。
