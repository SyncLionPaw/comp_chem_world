# PaiNN/SHARC 短程动力学诊断

## 背景

给定丁烯 PaiNN 检查点由 30 分钟探索训练中的验证结果选出，尚未完成生产动力学校准。40 个 S1 初始条件来自经过速度和动能一致性筛选的公开 SHNITSEL A03 数据，并非 Wigner 样本或新生成轨迹。低能隙覆盖、相位连续性及分布外风险仍待评估。

## 任务

预先登记并执行一次有界诊断，最多选择两个不同的给定初始条件。依据原生轨迹评估接口和已采样模型风险，说明后续研究是否有证据支持。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、h5py、matplotlib、NetworkX、NumPy、pillow、PyTorch、PyYAML、SciPy、sympy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 执行前记录固定模型、条件、资源、风险假设、漂移阈值和决策／停止规则。每个条件运行 5–10 fs，核时间步长 0.5 fs，单次尝试的墙钟时间不超过 300 秒。使用给定 CPU 目标，记录实际软件与资源，不提交远程作业。
- 使用固定 state dict、导出推理模型、源码、适配器及初始条件池，不加载替代 pickle。检查接口和数据来源，报告能量、力、平滑 NAC 的形状和单位，解释相位处理、低能隙及 OOD 风险；平滑 NAC 不等同于导数耦合。公开网格仅用于诊断，不得用于训练或调参。
- 登记计划只执行一次，不重试、不替换失败或截断条件、不增加作业，也不改变模型、时长或阈值。保留启动前被停止规则排除的条件及触发条件索引，以及输入、原生轨迹、终止状态与资源证据。
- 独立检查完整的 0…T 时间网格、初始 S1 单态布居、有限且归一化的布居、`Etot=Ekin+Epot`、漂移与完成／截断状态。未到计划终点的前缀不能称为完成。
- 区分接口错误、数值不稳、能量漂移、近简并耦合／相位问题、表面跳跃稳定性、OOD／数据覆盖和外部执行失败。漂移阈值仅作诊断，未经独立校准不得声称可靠或将继续执行视为已验证结论。一两条 5–10 fs 前缀不能识别 100 fs 的 S1 寿命、置信区间或生存分布；寿命应保持未估计。若报告 S1 占据面积，须注明实际时间窗口和轨迹数。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 数据库、预试模型检查点、运行资料及输出约定。 |

输入位于 `/app/inputs/`：13,000 条记录的 `databases/03_3Sing_C4H8.db`、诊断网格 `databases/06_3Sing_C4H8_grid.db`、`pilot-baseline/weights/painn_state_dict.pt`、`pilot-baseline/initial_conditions/a03_equiv_s1_40.json` 和 `sharc-v3.0.0.zip`。

执行接口及结果格式见 `/app/inputs/output-contract.md`。提交 `/app/outputs/probe-plan.json`、`probe-result.json` 和 `decision.json`，回收证据保留在 `/app/bench25-artifacts/`。决策中 `s1_100fs_lifetime_fs` 为 null，`lifetime_identifiability` 表明短前缀下不可辨识；观测面积使用 `observed_prefix_s1_occupancy_integral_fs`。无法执行或缺少证据时如实说明，不虚构结果。
