# 任务：归档链期望与 Metropolis 转移

## 背景

检查点定义了一个固定的六角度周期模型，能量单位为 kJ/mol。目标与均匀 flat-probe 系综是模型空间的数学分布；有限归档链不能证明平衡、物理 Ala4 自由能或新采样。

## 任务

实现 `/app/submission.py`，计算网络及参数梯度、目标/均匀 Metropolis 转移，并从归档链估计系综均值、梯度差及分块 MCSE。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

六角按 `(phi1,psi1,phi2,psi2,phi3,psi3)` 排列，单位弧度，折回 `[-π,π)`；输入编码为全部六个正弦再接全部六个余弦。网络为 `12→96→48→24→1`，隐藏层 ReLU，零点导数取零，使用 float64 计算。检查点为八个已解码数组，依次为 `fc1.weight,fc1.bias,fc2.weight,fc2.bias,fc3.weight,fc3.bias,out.weight,out.bias`，形状为 `(96,12),(96,),(48,96),(48,),(24,48),(24,),(1,24),(1,)`。

提供以下函数：

- `forward_and_grad(angles, checkpoint) -> (energy, gradient)`：反向求导；按上述数组顺序及数组内部 C 序展开全部 7,105 个参数导数。
- `set_checkpoint(checkpoint)`：保存供 `transition` 使用的检查点。
- `transition(state, proposal, u, ensemble, beta, gamma) -> (accepted, next_state)`：proposal 是绝对角度，两个状态均折回周期域。`target` 在 `log(u) < min(0, beta*(V(proposal)−V(state))/(gamma−1))` 时接受；`flat_probe` 总是接受。拒绝时返回折回后的原状态。使用传入的 beta/gamma；归档参考采用 gamma=10、beta=1/(0.00831446261815324×300) mol/kJ。
- `analyze(chains, checkpoint, blocksize)`：每个系综有两条分别给定的链。计算能量和参数梯度均值、目标减均匀的梯度差，以及逐分量 `sqrt(var(target block means,ddof=1)/Ntarget + var(flat block means,ddof=1)/Nflat)`。先在各链内分块，再汇总块均值。

对非有限或形状错误的输入、未知系综、u 不在 `(0,1)`、非有限 beta、gamma≤1、非正或非整数块长、不能整除任一链长度或每系综汇总后不足两个块的情况，抛出 `ValueError`。输出均有限。forward/gradient 的 atol/rtol 为 `2e-9/2e-8`，analysis 为 `2e-8/2e-8`，后继角度为 `2e-12/0`；接受标志须为真正的布尔值。不生成新 Monte Carlo 或 MD 样本，不宣称收敛、置信覆盖或物理 FES。

### 输入与产物细则

输入为 `/app/environment/assets/` 下的 `model_checkpoint.pt`、`retained-chains.json`。仅提交 `/app/submission.py`，使用所给 Python/NumPy 环境。

`analyze` 返回字典，恰含 `target_energy_mean`、`flat_energy_mean`、`target_gradient_mean`、`flat_gradient_mean`、`contrast`、`mcse`；或按此顺序返回六元素序列。前两项为 kJ/mol 标量均值，后四项形状为 `(7105,)`，参数顺序同上。contrast 为目标减均匀，MCSE 非负。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 给定输入与资源目录。 |

提交 `/app/submission.py`。调用方式和输出约定见上文。
