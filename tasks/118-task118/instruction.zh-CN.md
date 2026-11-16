# 任务：同组分堆垛结构的稳定性比较

## 背景

`environment/assets/configurations.yaml` 列出六份沉积的 GGA 弛豫输出——每份含 `POSCAR`、`CONTCAR`、`INCAR`、`KPOINTS`、`OUTCAR`、`OSZICAR`——覆盖三个同组成的 P-3m1 / R-3m 堆叠对：TiS2、LiTiS2、NaTiS2。

## 任务

由沉积的末态能量比较每个堆叠对的 P 与 R 堆叠，并说明该比较的证据边界。

## 要求

在本地容器内解析原生日志；不得启动 VASP 或重跑 DFT。按 Ti 原子数归一，一个 Ti 对应一个 TiS2 化学式单位。主能量取末态 OUTCAR 自由能 `TOTEN`；OUTCAR 的 `energy(sigma->0)` 与末态 OSZICAR `E0` 作为交叉校验，须与之在 1e-5 eV 内一致。报告 `E_stack = TOTEN / n_Ti`（eV per Ti）与 `delta_R_minus_P = E_R − E_P`；delta 为正表示该沉积数据中 P 更低。仅当 `|delta|` 超过 1e-3 eV/Ti 时才给出确定排序，否则记为 `within_dead_zone`。比较容差 1e-5 eV/Ti 只对应打印精度，不是 DFT 物理不确定度。

逐份核对采样条件（KPOINTS 与晶胞记录）、末态电子收敛（把末态 OSZICAR 电子迭代的 `dE` 与 `d eps` 与该文件的 `EDIFF` 比较）、离子弛豫是否完成、VASP 是否正常结束，以及是否触及早期 NELM 上限。比较范围仅限这三个堆叠对：带符号的能量差不建立凸包或全局多晶型稳定性，33 相凸包不属于本任务。

### 输入与产物细则

写入 `/app/final/stacking.json`，内容包括：

- `configurations`：覆盖六个公开配置 ID `TiS2-P`、`TiS2-R`、`LiTiS2-P`、`LiTiS2-R`、`NaTiS2-P`、`NaTiS2-R`，各含整数 `n_atoms`、`n_Ti`、`n_formula_units`，数值 `final_TOTEN_eV`、`energy_per_formula_unit_eV`，以及布尔 `final_electronic_converged`、`ionic_relaxation_complete`、`normal_end`、`early_scf_limit_hit`。
- `pairs`：恰为 `TiS2`、`LiTiS2`、`NaTiS2`，各含数值 `P_eV_per_Ti`、`R_eV_per_Ti`、`delta_R_minus_P_eV_per_Ti`，字符串 `ordering`（`P_lower`、`R_lower` 或 `within_dead_zone`），以及 R 堆叠的布尔 `early_scf_limit_hit`。
- `all_electronic_steps_converged`（布尔）与 `hull_or_global_stability_claim`（固定为 `false`）。
- `methods` 与 `limitations`，使用下列固定值且不得改动。

布尔值不能替代数值。

`methods` 必须恰好包含：`energy_source` = `final OUTCAR free energy TOTEN, cross-checked against energy(sigma->0) and final OSZICAR E0`；`normalization` = `one Ti atom equals one TiS2 formula unit; divide by N_Ti`；`delta_definition` = `E_R_per_Ti - E_P_per_Ti`；`energy_tolerance_eV_per_Ti` = 1e-5；`delta_tolerance_eV_per_Ti` = 1e-5；`ordering_dead_zone_eV_per_Ti` = 1e-3；`tolerance_meaning` = `printed-value comparison precision only; not a physical DFT uncertainty`。

`limitations` 必须恰好包含下列六条，不得改动：

- `Only the three available same-composition P/R pairs are compared.`
- `The deposited KPOINTS files carry the same 4×4×4 grid label, while the cells have different sizes; k-point density convergence is not established.`
- `No Mg or Na0.5TiS2 pair is included.`
- `No formation energies, convex hull, or global stability result is calculated.`
- `Final ionic relaxation completion is checked separately from electronic convergence of every SCF step. NaTiS2-R has an early SCF step that reached NELM=100 without meeting EDIFF; later ionic steps converged.`
- `Therefore this result does not claim that every electronic step converged, nor that either stacking is a global ground state.`

用公开渲染器由 `/app/final/stacking.json` 生成 `/app/final/report.md`，两者内容保持一致：

```text
python environment/assets/render_report.py /app/final/stacking.json /app/final/report.md
```

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `environment/assets/configurations.yaml` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/stacking.json` | 提交结果；内容与格式按上文要求。 |
| `/app/final/report.md` | 提交结果；内容与格式按上文要求。 |
