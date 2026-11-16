# 弹性碰撞算符与前向散射数值验证

## 背景

弹性、保速散射中，寿命率与动量弛豫率对角度的权重不同；前向尖峰会影响数值积分的稳定性。

## 任务

根据给定的屏蔽参数和核函数，自行设计角度积分与网格加密方法，比较 SERTA 与 MRTA 速率，并判断前向散射趋势。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 覆盖输入中的五个 `a` 值，分别提交 `results.json` 和 `quadratures.json`。
- 对每个 `a`，提供至少两档递增且不同的求积网格。节点至少 8 个、位于 `[-1,1]`，权重严格为正且总和为 2；每档最多 200000 个节点。
- 每级网格的节点不得重复，一阶、二阶矩误差各不超过 `1e-3`；最后两档中两种速率的相对变化各不超过 `1e-3`。
- 最终速率须由所提交的求积值复算一致（`rtol=1e-10`），并与闭式速率一致（相对误差不超过 `3e-4`）。所有值有限；`rate_ratio=mrta_rate/serta_rate`。
- 按 `environment/assets/public/output-contract.md` 的字段提交。积分结果应由本题给定核和输入产生；不要用外部数值或伪造的运行记录替代计算。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/author/inputs/elastic-angular.json` | 散射核、参数和速率定义 |
| `/app/environment/assets/public/output-contract.md` | 公开提交规范 |

工作目录为 `/app`。输入位于 `environment/assets/author/inputs/elastic-angular.json`，输出写入 `/app/final/`。本题采用等速、弹性散射和 `u=cos(theta)`；参数、核函数与速率定义见输入文件。

**交付物**

| 路径 | 内容 |
| --- | --- |
| `/app/final/results.json` | 散射速率及比值 |
| `/app/final/quadratures.json` | 数值积分结果 |
