# 任务：XAlkeneDB 激发态数据库审计与性质提取

## 背景

本题使用等变消息传递网络 SPaiNN 拟合激发态性质并驱动非绝热动力学。正确理解公开参考数据库 XAlkeneDB（Zenodo 10736050）是其训练与分析的前提。所提供数据库包含按 SA(3)-CASSCF(2,2)/cc-pVDZ 计算的 Wigner 采样参考数据。

## 任务

审计三个 Wigner 采样数据库的格式与性质，并验证数据库中包含的一致性约束。从数据中推导 data 字典的语义，包括键名、数组形状和耦合轴顺序，并提供证据，例如通过不同性质之间的数学关系进行交叉验证。

各分子的相对能量统一以该分子的 S0 最小值为基准。标准差使用总体标准差（`ddof=0`）；报告均值、标准差和极值，并覆盖输出契约要求的全部行。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、matplotlib、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

数据库由 SHARC 管线生成，因此坐标和性质的单位与 ASE 默认约定不同。利用数据中的物理约束（例如键长和能量量级）推断并说明单位与换算。

结论应写明单位、证据链和任何不确定处。不要断言数据无法支持的内容。对每个分子和耦合对，`n_points`应报告跨所有记录和原子接受检验的标量耦合分量总数；每个原子的三个笛卡尔分量均计入（等价于对各记录求和 `n_atoms × 3`）。

### 输入与产物细则

- `inputs/databases/01_3Sing_C2H4.db`、`02_3Sing_C3H6.db` 和 `03_3Sing_C4H8.db`：ASE SQLite 数据库，可由 `ase.db.connect` 读取；每行的 `row.data` 字典包含多态性质。分子分别为乙烯（6 个原子）、丙烯（9 个原子）和丁烯（12 个原子）。
- `inputs/README.md`：上述输入的背景说明。
- `inputs/output-contract.md`：要求在 `outputs/` 下交付四个文件。
- 请独立检查证据，并在提交中解释分析。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `inputs/databases/01_3Sing_C2H4.db` | 给定科学输入或资源；格式和单位见任务要求。 |
| `inputs/README.md` | 上述输入的背景说明。 |
| `inputs/output-contract.md` | 要求在 `outputs/` 下交付四个文件。 |

按公开的 `inputs/output-contract.md` 将四个文件写入 `/app/outputs/`。
