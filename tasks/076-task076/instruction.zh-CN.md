# 任务：ADMM 辅助基组收敛性判定（激发态几何）

## 背景

激发态几何的准确性可能受到 ADMM 辅助基组选择的影响。评估这种影响，需要在不同基组组合之间一致地比较键长、键角和二面角。

## 任务

自主定位资料中的逐分子几何数据，独立重算 ADMM 与同主基组常规 PBE0 的几何误差，并与对应的已发表聚合统计对照。分析基态与激发态键长、键角以及激发态二面角；二面角定义由你自主定位和确认。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow。不要自行安装额外软件包，也不要通过网络获取依赖。

- 对每个分子样本集合重算 ME、MAE、带符号 MAX（绝对值最大的误差）和总体标准差 STD（`ddof=0`）。键长误差单位为 pm；键角和二面角为度。正键长 ME 表示 ADMM 键更长，负键角 ME 表示角度更窄。
- 排除 M8、M35 的 eclipsed 激发态构型；M10、M30 使用 C2v 对称约束参考，其中 M30 取 B1 态。
- 使用共同主基组定量比较 dzp、tzp、tz2p 的激发态键长 MAE，并据提交数据讨论收敛性。
- 保留公开资料中的每个分子、标签和误差；若印刷舍入导致并列极值的符号不明确，应说明该歧义而非改变误差定义。报告 SI 聚合值与逐分子数据之间的差异。

### 输入与产物细则

使用 `/app/inputs/` 中提供的正文与补充信息 PDF，自主查找所需数据。输出放入 `/app/final/`：

- `statistics.csv`：列 `quantity,variant,pbs,abs,me,mae,max,std`，共 45 个组合。`quantity` 为 `bond_length`、`angle`、`dihedral`；前两者各含 GS、ES，后者含 ES。基组对：`(dzp,DZVP)`、`(dzp,TZVP)`、`(dzp,TZV2P)`、`(dzp,cc-GRB-D)`、`(tzp,TZVP)`、`(tzp,TZV2P)`、`(tzp,cc-GRB-T)`、`(tz2p,TZV2P)`、`(tz2p,cc-GRB-Q)`。
- `report.md`：收敛性比较（列出共同主基组 TZV2P 下 dzp/tzp/tz2p 的 ES 键长 MAE）及聚合值与来源逐项差异的说明。
- `provenance.json`：`samples` 以 `<quantity>|<abs>|<pbs>|<variant>` 为键；每项含 `{ "mol": 分子编号, "label": 小写 SI 原子标签, "err": 带符号误差 }`。标签去掉 ∠/η 前缀，例如 `c br`、`br c br`、`s c s c br`。无原子标签的二面角行使用空标签；同名标签的重复条目须分别保留。逐组注明自主找到的原始数据来源并保留全部逐分子样本；逐项比较容差为 ±0.006（对应单位），聚合比较容差为 ±0.03。

报告应记录自主找到的来源标识，无固定页码格式要求；报告中的文件引用应能在 `final/` 中解析。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/statistics.csv` | 列 `quantity,variant,pbs,abs,me,mae,max,std`，共 45 个组合。`quantity` 为 `bond_length`、`angle`、`dihedral` |
| `/app/final/report.md` | 收敛性比较（列出共同主基组 TZV2P 下 dzp/tzp/tz2p 的 ES 键长 MAE）及聚合值与来源逐项差异的说明。 |
| `/app/final/provenance.json` | `samples` 以 `<quantity>\|<abs>\|<pbs>\|<variant>` 为键 |
