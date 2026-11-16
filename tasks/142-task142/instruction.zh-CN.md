# 任务：鞍点搜索对受控初猜扰动的稳健性

## 背景

在冻结的 NewtonNet 势能上使用给定的两个过渡态代理几何（ID `001` 和 `162`）。源工作流的原始起始猜测不可得，因此结论仅适用于这两个几何和指定的扰动设计。

## 任务

运行冻结的十个 full-Hessian 鞍点搜索，评估搜索满足一阶鞍点成功判据的频率。解释收敛与计算代价，并讨论相对各自 baseline 的末态能量和重原子几何变化。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、JAX、matplotlib、NetworkX、NumPy、pandas、pillow、PyTorch、PyYAML、scikit-learn、SciPy、sympy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 严格遵循 `/app/assets/protocol.json`：每个 ID 一条 baseline；RMS 扰动幅度为 0.05 和 0.12 angstrom，种子为 17 和 31，共十个 trial。使用协议规定的 PCG64 抽样、刚体运动投影与缩放。
- 使用冻结的 Sella 2.5.0 exact-Hessian callback 协议，每个 trial 最多接受 16 个优化步。
- 科学成功要求优化器收敛、独立重放得到的最大单原子力向量欧氏范数 <= 0.04 eV/angstrom，且投影内部本征值中恰有一个低于 -1/23.06055 eV/angstrom^2。
- 保留全部 trial 的原始真实证据：冻结起始几何与扰动清单、事件 sidecar、事件记录、原生轨迹、优化器日志、协议快照与 envelope。不得合成或重建运行证据。
- 遵守冻结预算：180 次 Hessian 调用、640 次能量/力评估、2700 秒。
- 在 `failure_analysis.md` 中解释十个 trial 的观察结果、收敛与代价，以及相对 baseline 的能量和重原子几何响应。结论限于这两个代理几何与固定的幅度/种子。能量和 RMSD 不能认证过渡态身份。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 初始几何、模型检查点、规格及协议。 |
| `/app/assets/output-contract.json` | 原生运行目录及提交格式。 |

将 `failure_analysis.md` 和 `/app/assets/output-contract.json` 所述完整 `runner_output` 树写入 `/app/final`。从完整原始 `runner_output` 记录得出试验结果和数值诊断；在 `failure_analysis.md` 中解释结果并保留全部原生证据。
