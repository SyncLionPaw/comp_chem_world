# 任务：修复会丢失振荡的水合求解器

## 背景

只读输入 `/app/assets/defective_solver.py` 与 `/app/assets/defective_force_model.py` 实现了一个故意注入缺陷的六阶水合压力求解器；运行前者并指定输出目录即可查看其力曲线。物理约定沿用底层案例：自然边界条件 `P1''=0`，变分压力 `Pi = -dU/dL_A/epsilon0`。

## 任务

诊断并最小化修复注入的缺陷，恢复振荡的尖锐压力。提交物必须真正执行求解——报告固定数值不算完成。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、MDAnalysis、NumPy、pillow、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 写出 `final/fixed_solver.py`、`final/force_model.py`、`final/diagnosis.md`、`final/force_fixed.csv`、`final/recovery.json`。
- 提交的求解器须接受工作目录作为第一个位置参数，从环境读取 `CASE007_P0` 与 `CASE007_ALPHA`，并在该工作目录下写出 `final/force_fixed.csv`。
- `recovery.json` 须记录 `natural_boundary` 为 `P1''=0`、`pressure_definition` 为 `-dU/dL_A/epsilon0`；`diagnosis.md` 须同时指出被错误替换的一阶导条件与修正后的二阶导条件。
- 公开参数下完整的 2–20 Å 压力曲线与独立计算的参考比较，且提交程序会在若干未事先公开的 `P0`/`alpha` 取值上重跑。每次重跑都必须由请求参数真实重算——忽略参数、复用公开参数曲线或复现原缺陷的输出都不能通过。

### 输入与产物细则

- 输入：`/app/assets/defective_solver.py`、`/app/assets/defective_force_model.py`（只读）
- 输出：`final/fixed_solver.py`、`final/force_model.py`、`final/diagnosis.md`、`final/force_fixed.csv`、`final/recovery.json`

保留 2 至 20 Å、步长 0.1 Å 的 181 点距离网格。距离容差为 1e-9 Å；压力比较采用相对容差 2e-5、绝对容差 1e-3 Pa。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/defective_solver.py` | 给定的计算或辅助工具。 |
| `/app/assets/defective_force_model.py` | 给定的计算或辅助工具。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
