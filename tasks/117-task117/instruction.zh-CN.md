# 任务：差分电荷密度与极化分析

## 背景

`environment/assets/Li/` 与 `environment/assets/Mg/` 各含三份总电荷密度：`host_ion`（宿主加嵌入离子）、`host`（去掉该离子的 TiS2 宿主）、`ion`（孤立的 Li 或 Mg），各带一个 `CONTCAR`。仅使用这些 Li 与 Mg 输入，不需要新的 DFT 计算。

## 任务

计算 Li 与 Mg 的第一段总电荷密度差分，核对每种离子三个文件的兼容性，并判断所定义的观测量——积分、峰值与阈值体积分数——是否能建立 Li/Mg 价电子极化排序。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

只读取每个 CHGCAR 的第一段总电荷密度网格，在 PAW 增强占据之前停止，并排除后续的磁化网格。文件截断、缺值或非有限值都应报错，绝不能用零补齐。设存储值 D、晶胞体积 V、网格点数 N，则密度 `rho = D/V`，差分为 `delta_rho = rho(host_ion) − rho(host) − rho(ion)`；积分为 `delta_N = sum(delta_rho) * V / N`，当三个晶胞一致时 `sum(delta_D)/N` 必须给出同一结果。报告 `cell_volume_A3`（Å³）、`integral_delta_e`（e）、`max_abs_delta_e_per_A3` = `max|delta_rho|`，以及 `volume_fraction_abs_gt_0.004` 为 `|delta_rho|` 超过 0.004 e Å⁻³ 的网格占比。

同一种离子的三个文件必须具有相同的网格形状与晶格矢量（1e-4 Å）。几何核对时，先在 `host_ion` 中识别嵌入离子，将其余原子按元素与 `host` 一一匹配，再把嵌入离子与 `ion` 匹配；使用最小镜像距离、0.01 Å 容差，且每个目标原子只能匹配一次；坐标可以是 Direct 或 Cartesian。

解释字段记录：这些积分、峰值与阈值体积分数不能建立 Li/Mg 价电子极化排序。该边界只针对这些观测量，不排除其他 CHGCAR 价电子分析。

### 输入与产物细则

读取 `environment/assets/Li/` 与 `environment/assets/Mg/` 下的 CHGCAR 与 CONTCAR。

写入 `polarization.json`：`schema_version` 为 2；`Li` 与 `Mg` 两个对象，各含三个整数的 `grid`、`cell_volume_A3`、`integral_delta_e`、`max_abs_delta_e_per_A3`、`volume_fraction_abs_gt_0.004`；`checks` 含 `cells_and_grids_compatible`、`geometry_matches`、`electron_count_closed`（仅当两种离子的 `|integral_delta_e|` 都低于 0.001 e 时为 true）；`interpretation` 含 `observable` = `first_grid_total_density_difference`、`valence_order_status` = `insufficient_evidence`、`reason` = `no_defined_valence_polarization_metric`。

用公开渲染器由该 JSON 生成 `report.md`，两者内容保持一致：

```text
python environment/assets/render_report.py polarization.json report.md
```

积分、体积和体积分数的绝对容差分别为 1e-4 个电子、1e-4 Å³ 和 0.002。峰值容差按所声明单位取 max(1e-6, 0.001 × |参考峰值|)。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `environment/assets/Li/` | 给定输入与资源目录。 |
| `environment/assets/Mg/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/polarization.json` | 提交结果；内容与格式按上文要求。 |
| `/app/report.md` | 提交结果；内容与格式按上文要求。 |
