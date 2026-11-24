# 任务：MoS₂ 压力依赖 Γ 点声子

## 背景

复现固定 MoS₂ 结构在 0、3、6、9 GPa 下的带符号 Γ 点声子，并跟踪 Raman 活性 E₂g²、E₂g¹、A₁g 分支。目标路线为 VASP 6.4.1、PAW-PBE、PBE+D3（`IVDW=11`）、500 eV、Γ 中心 12×12×1、`EDIFF≤1e−10 eV`、`IBRION=6`、`ISIF=3`、`POTIM=0.015 Å`、`NFREE=2`、`KPAR=4`；对应 `PSTRESS` 为 0/30/60/90 kbar。保持给定结构不变。

## 任务

计算并报告每个压力下全部 18 个带符号 Γ 模态，跟踪 Raman 分支并拟合四点压力系数；量化初始压力/力状态及一个单变量收敛对照。提交原生计算和执行证据。

## 要求

使用 HPC 时，按 `hpc` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。

使用 `/app/assets` 中压力匹配的结构与输入映射，不得弛豫结构。至少进行一个 0 GPa 单变量截断能或 `kz` 对照。所有有限位移电子步都须达到声明的 EDIFF，且不得耗尽 NELM。分支跟踪、压力残差、字段、容差和证据按 `/app/verification.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 压力匹配结构、VASP 输入及赝势来源。 |
| `/app/verification.md` | 方法与输出规范。 |

输入：`/app/assets/POSCAR_*`、`/app/assets/INCAR_*`、`/app/assets/KPOINTS_*`、`/app/assets/pressure_deck_map.md` 和 `/app/assets/pseudos/README.md`。按公开契约提交 `/app/final/phonons.json`、`raman_modes.json`、`pressure_state.md`、`convergence.md` 与 `engine_io/`。不得提交 POTCAR 文件内容。
