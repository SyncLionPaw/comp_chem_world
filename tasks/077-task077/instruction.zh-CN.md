# 任务：四种响应核相对 EOM-CCSD 的精度比较

## 背景

不同响应核在计算成本、几何精度和能量精度之间具有不同的权衡。有效比较需要采用一致的参考方法，并明确区分不同物理量。

## 任务

比较 PBE0/TZVP、ADMM-PBE0/TZVP+tzp、sTDA@PBE0/TZVP、sTDA@ADMM-PBE0/TZVP+tzp 四种核。根据逐分子 SI 数据重算相对 EOM-CCSD 的键长、键角和二面角误差，并与已发表的统计值对照。根据 SI 来源核验能量统计，并将 Evert 与正文的核能量汇总比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow。不要自行安装额外软件包，也不要通过网络获取依赖。

- 几何误差按核几何减 EOM-CCSD 计算；重算 ME、MAE、带符号 MAX（绝对值最大的误差）和总体标准差 STD（`ddof=0`）。键长单位为 pm，键角和二面角为度。保留分子标签，并说明四种核二面角误差的方向和幅度。
- 区分参考系：自主确认各能量量的参考方法、几何及态选择。Evert 比较针对对应优化几何上的首态，不得以多态聚合统计替代。能量行是印刷值核验，因为没有逐分子参考能；不得虚构逐分子能量。
- 自主查找并解读 M14 的参数例外；讨论几何是否为正常最低点时，须区分默认 aEX=0.2 与 aEX=0.25 的参数例外。

### 输入与产物细则

使用 `/app/inputs/` 中提供的正文与补充信息 PDF，自主查找所需数据。输出放入 `/app/final/`：

- `statistics.csv`：列 `row_type,kernel,basis,quantity,me,mae,max,std,source_table`。含 12 行几何数据：四种核 × `bond`、`angle`、`dihedral`，`row_type=recomputed-from-raw`，并注明自主找到的原始数据来源和参考系；另含 18 行能量数据，`row_type=verified-against-SI`：六种方法/基组（PBE0/DZVP、PBE0/TZVP、PBE0/TZV2P、ADMM-PBE0/TZVP+tzp、sTDA@PBE0/TZVP、sTDA@ADMM-PBE0/TZVP+tzp）× Evert/Ead/Efl。转录 ME/MAE/STD，`max` 可留空。
- `provenance.json`：`samples` 按 `<kernel>|<basis>|<quantity>` 编键；每条几何行含全部 `{ "mol": 分子编号, "label": 原子标签, "err": 带符号误差 }`；SI 原子标签用小写，无标记二面角行的 `label` 填空字符串。同名标签的重复条目须分别保留。能量行不提供逐分子样本。
- `report.md`：比较四种核；依据所提交的行列出各核的二面角 ME 并量化差异，并解释 M14 的参数例外。

四种 TZVP 几何比较均使用自主找到的 MOLOPT/TZVP 数据及对应聚合统计。`source_table` 中，几何行标识原始数据来源，能量行标识 SI 聚合统计来源，填写自主找到的来源表标识。逐项几何容差 ±0.006（对应单位），聚合值为 ±0.02；能量转录为 ±0.005 eV。记录自主找到的来源标识；报告中的文件引用应能在 `final/` 中解析。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/statistics.csv` | 完整字段、单位和内容按上文要求。 |
| `/app/final/provenance.json` | `samples` 按 `<kernel>\|<basis>\|<quantity>` 编键 |
| `/app/final/report.md` | 比较四种核 |

原子标签的大小写、空白和键连接符统一处理（`C-H`、`c–h` 与 `c h` 等价），但原子顺序、下标及重复样本必须保留。分子编号须为正整数；`M` 前缀和前导零仅作格式表示，整数值数字形式等价。方法/基组名称忽略大小写及空白，`sTDA@ADMM` 与 `sTDA@ADMM-PBE0` 等价。来源标识可使用 Table、T 或“表”等表格标记，可在表号前加 S，也可单独填写表号；句末标点不影响识别。报告分别给出四种核的二面角 ME，同一次数字出现不能同时代表多个方法。
