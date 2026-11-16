# 任务：COF 效率论断与跨表一致性审计

## 背景

共价有机框架的高效激发态计算需要一致地评估精度与计算成本。耗时、优化工作量及导出的光学能量应当支持同一比较。

## 任务

自主定位正文的组件耗时、优化及光学能量结果和 SI 的原子数、基函数数，审计效率与 COF 精度论断。需要时从印刷表格数据独立推导结果。只在图中展示的谱形比较属于定性信息，不能作数值审计。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pandas、pillow。不要自行安装额外软件包，也不要通过网络获取依赖。

- 组件耗时：由印刷时间推导组件时间占比和加速比。光谱及优化耗时：推导优化循环数、比较每步加速比，并把 sTDA 最大谱时间从秒换算为分钟。光学能量：对同一 COF/方法计算 Stokes 位移 `Evert − Efl`；四项 MAE（Evert/Ead/Efl/Stokes）均按六个 COF 的 `|sTDA−ADMM|` 平均值重算。
- 将正文的原子数、基函数数与对应 SI 数据对照。时间单位用秒，能量用 eV；数量与比值沿用表中单位。
- 如实报告推导值与印刷值之间的每项差异，不要强行匹配或省略。图示谱形比较仅作定性说明，不作为数值证据。

### 输入与产物细则

使用 `/app/inputs/` 中提供的正文与补充信息 PDF，自主查找所需数据。输出放入 `/app/final/`：

- `audit.csv`：列 `claim_id,recomputed,printed,verdict,source`。`verdict` 为 `confirmed`、`rounding-consistent`、`documented-discrepancy` 或 `not-derivable`。单纯转录行的 `recomputed` 与 `printed` 均填印刷值。派生量的 `printed` 填正文讨论中对应的论断；逐体系循环数没有直接印刷对照，两列均填推导后四舍五入到整数的循环数。在适用容差内一致用 `confirmed`；Stokes 差异可由印刷舍入解释用 `rounding-consistent`，超出该界用 `documented-discrepancy`。逐行注明自主找到的来源表标识。
- `claim_id` 模式：组件耗时全列 `timing_<GS_SCF|ES_energy_gradient|ERI|DERI|Total>_<PBE0|ADMM-PBE0|sTDA@ADMM-PBE0>`，另含 `timing_ERI_share_PBE0`、`timing_DERI_share_PBE0`、`timing_speedup_ADMM`、`timing_speedup_sTDA`、`timing_speedup_DERI`；光谱/优化耗时列 `workflow_<abs_admm|abs_stda|opt_admm|opt_admm_step|opt_stda|opt_stda_step>_<COF>`、循环数 `workflow_cycles_<COF>_<ADMM|sTDA>`、汇总 `workflow_more_stda_cycles_count`（`source` 注明逐 COF 循环比较得到的例外 COF ID）、`workflow_perstep_speedup_min`、`workflow_perstep_speedup_max`、`workflow_abs_stda_max_min`；光学能量 `energy_stokes_<COF>_<ADMM|sTDA>` 和 `energy_MAE_<Evert|Ead|Efl|stokes>`；结构计数 `structure_<atoms|basis>_<COF>`。
- COF 为 05000N2、05001N2、15100N2、15101N2、20610N2、20611N2。组件耗时比较针对 4608 核的 COF 05000N2，覆盖三种方法各自的五项时间；工作流比较含两种核的谱时间和优化时间；光学能量比较含 Evert/Ead/Efl 与 Stokes 值。
- `report.md`：根据审计行总结定量比较与差异，并说明谱形论断仅为定性。`provenance.json`：记录审计规则。

占比按组件/PBE0 总时间×100%；总时间加速比按 PBE0 总时间/另一方法总时间；DERI 加速比按 PBE0 DERI/ADMM-PBE0 DERI；循环数按优化总时间/每步时间；每步加速比按 ADMM/sTDA。转录保留印刷精度，比较派生值时考虑舍入。近似对照容差：组件耗时转录 0.5 秒、占比 1 个百分点、加速比（总时间 0.3、DERI 1.5）、正文论断比较 0.5；工作流耗时转录 0.001 秒、循环数 1.5、每步加速比 0.05/0.1、谱时间最大值 0.5 分钟；光学能量 Stokes 推导容差 0.005 eV、印刷 Stokes 转录须精确、MAE 0.02 eV、印刷 MAE 0.005 eV；结构计数 0.001。记录自主定位到的来源标识；报告中的文件引用应能在 `final/` 中解析。

`workflow_more_stda_cycles_count` 的 `recomputed` 和 `printed` 两列均填推导出的计数。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/inputs/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/audit.csv` | 完整字段、单位和内容按上文要求。 |
| `/app/final/report.md` | 根据审计行总结定量比较与差异，并说明谱形论断仅为定性。`provenance.json`：记录审计规则。 |
