# 传播给定的激子网络

## 背景

`inputs/benchmark.json` 定义三态动力学网络（S1、T1、T2）、初始布居、速率常数和观测时刻。S0 为剩余布居。

## 任务

根据给定速率构造列向量布居方程 dP/dt=KP，K 的行列顺序为 S1、T1、T2：K=[[-(isc1+isc2+f+nrS),risc1,risc2],[isc1,-(risc1+ic12+ph1+nr1),ic21],[isc2,ic12,-(risc2+ic21+ph2+nr2)]]。采用稳定方法传播初始布居至各指定时刻；S0 为守恒剩余。由态布居无穷时积分计算通道概率：荧光=f∫S1，T1 磷光=ph1∫T1，T2 磷光=ph2∫T2，非辐射损失=nrS∫S1+nr1∫T1+nr2∫T2。不得硬编码给定轨迹。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 h5py、NumPy、PySCF、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

在 `result.json` 中报告输入顺序的 `times_s`、N×4 `populations`（列顺序 S1、T1、T2、S0），以及恰好五个有限无量纲产率：`fluorescence`、`phosphorescence_T1`、`phosphorescence_T2`、`nonradiative`、`total_PLQY`。S0 由守恒计算；每行布居之和为 1。`total_PLQY` 为三个发光通道产率之和；非辐射产率单独报告。轨迹和全部产率相对于独立计算的绝对差不得超过 2e−7 + 2e−7 × 参考值的绝对值。

写入 `final/solver.py`、`final/result.json` 和 `final/convergence.json`。执行两次真实收敛计算，并用 `runs` 记录，恰好两项；每项含 `method` 和实际 Python `command`（argv 列表或命令字符串）。第一项运行 `solver.py`；第二项运行 `solver.py` 或 `convergence_solver.py`。两次须使用不同方法，或使用同一方法且均报告正的 `rtol`、`atol`，第二次两个容差均不得放宽且至少一个严格收紧。不得同时重复基准源文件和命令。两组轨迹最大绝对差须不超过 2e−7。检查概率守恒、零 ISC 解析极限、全部速率乘 10 且时间除 10 时的人口与产率不变性；区分有限时刻剩余激发态布居与无穷时产率。

重放命令从应用根目录运行，读取 `inputs/benchmark.json`；`result.json` 可写在工作目录或脚本旁的 `final/`，若两处都有文件，内容必须一致。无 shell 命令字符串或 argv 应使用 Python 及 `/app/final/solver.py` 等应用路径。资源限制：2 CPU、2 GiB、15 分钟；不得联网或使用凭据。

`convergence.json` 含非空字符串 `solver`、`solver_version` 和 `runs`。每项 run 含非空 `method` 及实际执行的 `command`；若方法相同，每项还须记录正的 `rtol` 和 `atol`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/benchmark.json` | 基准参数与计算条件。 |

输入：`/app/inputs/benchmark.json`。必需输出：`/app/final/solver.py`、`/app/final/result.json`、`/app/final/convergence.json`。仅当第二次运行使用独立源文件时，还需 `/app/final/convergence_solver.py`。
