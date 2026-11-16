# 任务：full-Hessian 与 quasi-Newton 鞍点搜索比较

## 背景

在冻结的 NewtonNet 势能上比较两种过渡态搜索策略，反应 ID 为 `001`（10 原子）和 `079`（11 原子）：一种在每个优化步使用解析 Hessian，另一种使用原生 quasi-Newton 曲率。两种策略均从给定初猜出发并遵循冻结协议。

## 任务

运行四个配对 trial，判断各运行是否满足协议的一阶鞍点成功标准，并比较两种方法的收敛与计算代价。结论仅针对这两个体系和每种方法的一次重复。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、JAX、matplotlib、NetworkX、NumPy、pandas、pillow、PyTorch、PyYAML、scikit-learn、SciPy、sympy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 严格遵循 `/app/assets/protocol.json`，包括每个 trial 最多 24 步；全部四个 trial 均计入分母。
- 科学成功要求优化器收敛、独立重放得到的最大单原子力向量欧氏范数 ≤ 0.04 eV/angstrom，且投影内部本征值中恰有一个低于 −1/23.06055 eV/angstrom²。
- 记录每个已接受优化步选用的曲率，以便独立核查两种搜索策略。
- 保留四个 trial 的原生运行证据与实际设置。不得合成或重建运行证据。
- 总预算为每 trial 24 个优化步、120 次 Hessian 调用及 500 次能量/力评估。
- 提交简洁的 `report.md`，解释观察到的配对成功结果、收敛/代价权衡及推断边界。在报告中说明科学方法与参数选择；不得根据两个 ID 和一次重复作宽泛结论。

依据原始运行记录汇总成功结果、各方法步数、模型调用总数、活跃耗时和配对试验结果。在 `report.md` 中解释观察到的收敛情况与计算代价；结论限于四个已记录试验，并保留其原生证据。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 初始几何、模型检查点、规格及协议。 |
| `/app/assets/output-contract.json` | 原生运行目录及提交格式。 |

输入位于 `/app/assets`：初猜、checkpoint、模型规格、冻结的 `protocol.json` 及本 `output-contract.json`。将 `/app/final/report.md` 和契约 `runner_output.required_tree` 所述完整原生运行树写入 `/app/final`。原生目录必须包含 envelope、协议快照、四个 trial 记录、评估事件流、原生轨迹和优化器日志。报告必须准确解释这些原始记录。
