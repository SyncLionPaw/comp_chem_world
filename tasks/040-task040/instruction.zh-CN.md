# 任务：稀疏静态 DFT 证据下的局部响应与科学决策

## 背景

本任务重分析已完成的固定水/2K 环境静态 DFT 数据，研究 CO₂ 沿 Au–C 方向的局部响应、数值一致性和有限初态敏感性。公开原生归档包含 13 个静态力计算点及 VASP XML、OUTCAR、输入、点位映射和预算记录。历史构造预算上限为 24 次离子力评估。

## 任务

对 water 与 2K 环境中 C–Au 距离 2.6 Å、3.0 Å 的四个中心，固定 Au 和其余环境，沿 Au→C 单位向量刚性平移 CO₂，位移 −0.02、0、+0.02 Å。另一个 2K、2.6 Å 中心具有不同弯曲/水合/配位初态，不属于三点组。以 VASP `e_fr_energy` 计算每组相对中心的局部能量，并从原生 XML 重算 CO₂ 三原子力之和沿 Au→C 的负投影；比较力梯度与中心差分。阈值为 `0.05 eV/Å + 5% × max(|力梯度|, |差分梯度|)`，超阈值也须解释，不得删点或换点。

分别量化 2.6 Å、3.0 Å 下 water/2K 的局部响应差异，以及 2K 同名义距离不同初态的响应差异。检查路径是否等价；多个结构因素同时改变时，不将差异归因于单一配位作用。至少选择一个公开但未测量的种子几何与实测中心比较，说明信息增益和机会成本。回顾性比较固定环境局部响应、初态/路径混杂、数值估计误差三种解释，并依证据提出至少两个可执行的后续方案，说明优先顺序、成本、机会成本、触发/停止条件及可能结果分支。建议不构成授权。

结论限于已计算的固定环境局部响应和有限初态敏感性。扫描点不是平衡态、端点或过渡态。不得据此建立平衡平均力、平衡自由能、过渡态/能垒、全局吸附稳定性、恒电势 K 效应或单变量配位因果作用；`equilibrium_deltaA_eV` 和 `equilibrium_CI` 为 `null`。本轮实际新增科学调用为 0，不提交 DFT/MD 计算或作业。既有公开结果属于事后分析，不得称为预注册。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

复核原生来源、固定环境、原子映射、坐标扰动、收敛、符号/单位、局部能量零点和历史预算。比较至少两个后续方案，并解释不同可能结果将如何影响后续判断。POTCAR 未分发，只能说明已提供的版本/哈希来源。`analysis.py` 须从原生证据重算并可确定性重放交付结果。

### 输入与产物细则

输入均在 `/app/environment/assets/` 下：`water_CO2/POSCAR`、`2K_CO2/POSCAR`、`methods.json`、`IS_seed_panel.extxyz`、`IS_seed_provenance.json`、`IS_budget.json`、`IS_native.tar.gz` 和 `IS_native_manifest.json`。产物结构、字段、预算与重放要求以同目录的 `output-contract.json` 为准。不提供 POTCAR。

在 `/app/final/` 提交 `selection.json`、`hypotheses.json`、`response.csv`、`path_audit.json`、`decision_log.json`、`next_calculation.json`、`native/manifest.json`、`analysis.py` 和 `report.md`。提交的 `native/` 下只要求 manifest，无需复制整份原生归档。`analysis.py` 是需要编写的提交产物，接口为 `python analysis.py ASSET_DIR OUTPUT_DIR`，两个目录参数分别为 `/app/environment/assets/` 和 `/app/final/`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
