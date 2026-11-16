# 计算发光体跃迁速率

## 背景

给定案例覆盖辐射跃迁、系间窜越（ISC）、反向系间窜越（RISC）和内转换（IC），包括带符号能隙与零极限。

## 任务

实现可复用的 Python 速率内核，读取 `inputs/benchmark.json`，计算其中每条记录及数组组合对应的速率。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 h5py、NumPy、PySCF、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 SI 换算 `E=gap_eV·e`、`μ=dipole_au·e·a0`、`V=soc_cm1·h·c·100`、`Γ=gamma_cm1·h·c·100`。计算 `kF=E³μ²/[3π ε0 ħ⁴c³]·n_ref(n_ref²+2)²/9`、`L=2V²Γ/[ħ(E²+Γ²)]` 和 `q=exp[−|E|/(kB·T_K)]`。带符号能隙≥0（含零）时，`kISC=L`、`kRISC=Lq/3`；能隙<0 时，`kISC=Lq`、`kRISC=L/3`。每条 IC 记录计算 `kIC_up=down_s1·exp[−gap_eV·e/(kB·T_K)]`。带符号分支和因子 1/3 是任务约定。

所有速率须为有限、非负的 s⁻¹ 数值，并在相对误差 1e−7、绝对误差 1e−12 内符合上述公式。拒绝非有限输入、T≤0、gamma≤0、SOC<0、负的辐射或 IC 能隙、n_ref≤0 和 down_s1≤0；拒绝时返回非零退出码且不留下结果。确认零 SOC 的速率为零、ISC 按 SOC² 缩放，并且正速率行满足带符号能隙的详细平衡 `RISC/ISC=exp[−gap_eV·e/(kB·T_K)]/3`。

写入 `final/kernel.py` 和 `final/result.json`。结果对象含 `radiative_s1`（每条辐射输入一个速率，保持输入顺序）、`spin_rows`（按温度、有符号能隙、SOC、展宽的顺序遍历笛卡尔积；每行含 `T_K`、`gap_eV`、`soc_cm1`、`gamma_cm1`、`isc_s1`、`risc_s1`）及 `ic_up_s1`（每条 IC 输入一个速率，保持输入顺序）。输入须相对应用工作目录读取，脚本须能在应用形目录中原样运行。可选以 `final/validation.json` 的 `checks` 记录检查结果：`zero_soc_max_abs_s-1`、`soc_squared_ratio_min`、`soc_squared_ratio_max`、`detailed_balance_max_relative_error`，分别为零 SOC 速率绝对值上限、匹配条件下最大/最小正 SOC 的 ISC 比值范围及详细平衡最大相对误差。资源限制：2 CPU、2 GiB、15 分钟；不得联网。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/benchmark.json` | 基准参数与计算条件。 |

输入：`/app/inputs/benchmark.json`。必需输出：`/app/final/kernel.py` 和 `/app/final/result.json`。
