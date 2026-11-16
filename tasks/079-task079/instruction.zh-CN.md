# 任务：垂直激发统计映射与基组限制分析

## 背景

垂直激发统计依赖于参考方法、分子几何、态的选择和基组。在将差异归因于响应核之前，需要区分这些条件。

## 任务

自主定位正文中辅助基组及响应核的 Evert 汇总，确定对应 SI 来源及其方法、参考、态数和几何变体。调和印刷 ME/MAE，并评估双 ζ 基组局限、ADMM 差异与依赖参考条件的 sTDA 结果。区分 CP2K 和 Turbomole 参考层；逐分子垂直激发能未发表。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow。不要自行安装额外软件包，也不要通过网络获取依赖。

- 根据表格中的方法、参考系、态数和几何变体，逐项建立正文到 SI 的映射；不得混淆不同参考层。
- 定量分析双 ζ 限制和参考条件下 sTDA@ADMM 的差异，并说明比较所用的方法及几何/态变体。
- 解释已发表数值对基组大小与 sTDA 参考系依赖性的支持，不得虚构逐分子激发能。

### 输入与产物细则

使用 `/app/inputs/` 中提供的正文与补充信息 PDF，自主查找所需数据。输出放入 `/app/final/`：

- `reconciliation.csv`：列 `entry,printed_me,printed_mae,si_table,si_me,si_mae,match`，共 12 行。六个 ID 为 `admm|<abs>/<pbs>`：dzp/DZVP、dzp/TZVP、dzp/TZV2P、tzp/TZVP、tzp/TZV2P、tz2p/TZV2P；六个 ID 为 `kernel|<method>/<basis>`：PBE0/DZVP、PBE0/TZVP、PBE0/TZV2P、ADMM-PBE0/TZVP+tzp、sTDA@PBE0/TZVP、sTDA@ADMM-PBE0/TZVP+tzp。记录正文与 SI 的印刷 ME/MAE、自主找到的来源表所印标识（填在 `si_table`）及舍入一致性。
- `provenance.json`：说明映射规则。`report.md` 逐行给出正文条目所对应的 SI 表、方法、参考系、态数和几何变体。
- `report.md`：定量讨论所提交的调和结果及双 ζ/sTDA 参考条件比较；逐项报告前十个单重态下 PBE0/DZVP 与 sTDA@ADMM-PBE0/TZVP+tzp 的 ME，覆盖参考方法（PBE0/TZV2P/CP2K 或 PBE0/def2-QZVPP/Turbomole）与几何（EOM-CCSD 优化或各被评估方法自身优化）的四种组合。自主定位这些分组，不得以仅首态的统计替代。

SI 转录容差为 ±0.005 eV；根据印刷舍入以 ±0.011 eV 评估正文/SI 一致性。`match` 使用 `consistent` 或 `rounding-consistent`。报告记录自主定位到的来源标识；文件引用应能在 `final/` 中解析。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/reconciliation.csv` | 完整字段、单位和内容按上文要求。 |
| `/app/final/provenance.json` | 说明映射规则。`report.md` 逐行给出正文条目所对应的 SI 表、方法、参考系、态数和几何变体。 |
| `/app/final/report.md` | 定量讨论所提交的调和结果及双 ζ/sTDA 参考条件比较 |
