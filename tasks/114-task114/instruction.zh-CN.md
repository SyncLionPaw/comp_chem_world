# 任务：比较已提供结构中的 TiS₂ 层间距

## 背景

工作目录提供了 TiS₂、LiTiS₂ 和 NaTiS₂ 的七个 PBE+D3 弛豫 CONTCAR，涉及 O1/P-3m1、O3/R-3m 和 R3m 堆垛。`TiS2_R-3m` 是 O3 结构。本题无需新做 DFT。

## 任务

测量各晶胞的晶格矢量长度和按规则定义的层间距；评估 O1 中 Li/Na 插入是否扩层、Na 扩层是否大于 Li、数据集中是否有 MgTiS₂，以及所给 R3m TiS₂ 晶胞是否为原胞单层。

## 要求

保留 CONTCAR 比例因子，长度单位为 Å。仅当 `|a-b|≤0.01 Å`、`a<4.5 Å` 且 `n_Ti` 为 1 或 3 时定义层间距 `c/n_Ti`，否则为 `null`。比较 O1 TiS₂ 与 O1 LiTiS₂、NaTiS₂：扩层须增加 >0.05 Å；Na 的增加量须比 Li 再大 0.05 Å。仅使用提供的七个结构。

在 `/app/lattice.json` 中写 schema version 2，`structures` 覆盖七个结构 ID，并包含 `a_A`、`b_A`、`c_A`、整数 `n_Ti`、`interlayer_A`；`methods.interlayer_rule`=`c_over_nTi_if_a_b_hexagonal_and_nTi_1_or_3`；并提供布尔结论 `O1_lithiation_expands_interlayer`、`O1_sodiation_expands_interlayer_more_than_lithiation`、`deposited_GGA_set_contains_MgTiS2`、`R3m_TiS2_is_primitive_monolayer_cell`。使用 `/app/environment/assets/render_report.py` 从 JSON 生成 `/app/report.md`。

长度比较的绝对容差为 0.001 Å。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 七个组成与物相的弛豫结构。 |

读取 `/app/environment/assets/<structure_id>/CONTCAR`，结构为 `TiS2_P-3m1`、`TiS2_R-3m`、`TiS2_R3m`、`LiTiS2_P-3m1`、`LiTiS2_R-3m`、`NaTiS2_P-3m1`、`NaTiS2_R-3m`。提交 `/app/lattice.json` 和 `/app/report.md`。
