# 任务：ADMM 绝热激发能与荧光能误差重算

## 背景

辅助基组近似会通过电子能和弛豫几何的变化影响绝热激发能与荧光能。评估时需要区分这些能量，并采用一致的参考定义。

## 任务

自主定位逐分子绝热激发能和荧光能，重算 ADMM 误差统计，并与对应的发表统计比较。另行转录已发表的核级统计，区分参考方法。用重算结果评估正文对三 ζ 辅助基组能量 MAE 区间的论断。逐分子垂直激发能未发表，不在本题范围。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow。不要自行安装额外软件包，也不要通过网络获取依赖。

- 逐分子 Ead/Efl 误差按同主基组的 ADMM 减常规 PBE0 计算。对每个基组组合的 35 个分子值重算 eV 单位的 ME、MAE、带符号 MAX 和总体标准差 STD（`ddof=0`）；原始分子能量有舍入，应在推导中考虑。
- 核统计 Ead 参考 EOM-CCSD；Efl 参考 PBE0/def2-QZVPP/Turbomole。由于相应逐分子参考能未发表，这些行只能转录核验；不得混淆参考系或声称重新计算。
- 自主查找并引用该能量 MAE 区间的两个界限，并用重算的三重 ζ MAE 评估论断；说明逐分子垂直激发能未刊且不在本题范围内。

### 输入与产物细则

使用 `/app/inputs/` 中提供的正文与补充信息 PDF，自主查找所需数据。输出放入 `/app/final/`：

- `statistics.csv`：列 `row_type,quantity,pbs,abs,method,me,mae,max,std,source_table,reference`。含 18 行 `recomputed-from-raw`：EAD、EFL 分别覆盖九组 `(dzp,DZVP)`、`(dzp,TZVP)`、`(dzp,TZV2P)`、`(dzp,cc-GRB-D)`、`(tzp,TZVP)`、`(tzp,TZV2P)`、`(tzp,cc-GRB-T)`、`(tz2p,TZV2P)`、`(tz2p,cc-GRB-Q)`；`source_table` 填自主找到的对应发表聚合统计所印的表标识，reference 为“ADMM − 常规 PBE0（同主基组）”。另含已发表 SI 核级汇总中的 7 行 EAD 与 11 行 EFL，标记 `verified-against-SI`，转录 ME、MAE、MAX 和 STD。EAD 包含 PBE0/DZVP、TZVP、TZV2P；ADMM-PBE0/TZVP+tzp、TZV2P+tzp；sTDA@PBE0/TZVP；sTDA@ADMM-PBE0/TZVP+tzp（reference：EOM-CCSD）。EFL 含 3 个 PBE0、6 个 ADMM-PBE0、2 个 sTDA 条目（reference：Turbomole）。核验行用 `method` 和 `abs` 中完整基组名识别（如 `method=ADMM-PBE0`、基组 `TZVP+tzp`）；`pbs` 可留空。
- `provenance.json`：`samples` 键为 `EAD|<abs>|<pbs>` 或 `EFL|<abs>|<pbs>`；逐组注明原始数据来源，每条重算行包含 35 个 `{ "mol": 分子编号, "err": ADMM−PBE0 带符号误差 }`。核验行不提供逐分子样本。
- `report.md`：总结三重 ζ MAE 比较并说明垂直能范围。

自主找到与重算结果匹配的发表聚合统计作为对照；逐分子误差容差为 ±0.006 eV，聚合比较容差为 ±0.02 eV；核验行非 sTDA 转录容差 ±0.001 eV，sTDA 为 ±0.005 eV。报告记录自主找到的来源标识；文件引用应能在 `final/` 中解析。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/statistics.csv` | 完整字段、单位和内容按上文要求。 |
| `/app/final/provenance.json` | `samples` 键为 `EAD\|<abs>\|<pbs>` 或 `EFL\|<abs>\|<pbs>` |
| `/app/final/report.md` | 总结三重 ζ MAE 比较并说明垂直能范围。 |
