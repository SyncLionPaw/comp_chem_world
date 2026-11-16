# Output contract — case-01

## `/app/final/W2N3-monolayer.poscar`

VASP POSCAR（Direct 坐标）。第 1 行任意注释；缩放因子 1.0；晶格为笛卡尔矢量（Å）。

## `/app/final/structure-report.json`

JSON 对象，字段（键名必须一致；数值单位见括号）：

```json
{
  "stoichiometry": "W2N3",
  "n_atoms": 5,
  "space_group_number": 187,
  "space_group_symbol": "P-6m2",
  "inplane_lattice_a_A": 2.912,
  "vacuum_A": 25.0,
  "layer_thickness_A": 5.16,
  "coordination": {
    "cutoff_A": 2.5,
    "W_counts": [6, 6],
    "N_three_coordination_count": 2,
    "N_center_count": 6
  },
  "paper_coordination_claims": {"W": 6, "N_outer": 3, "N_center": 5},
  "discrepancy_note": "（非空文本）"
}
```

字段语义：

- `inplane_lattice_a_A`：你结构中实际的六方面内晶格常数。
- `vacuum_A`：原子层顶面到相邻镜像层底面的净空隙（非 c 长度本身）。
- `layer_thickness_A`：最外原子平面之间的厚度（外层 N–外层 N）。
- `coordination.cutoff_A`：你使用的配位判定截断半径；`W_counts` 为两个 W 各自的
  N 配位数（在 2.45 Å 内计数也须与之一致性由验证器复核）；`N_three_coordination_count`
  为与 ≤3 个 W 成键的外层 N 个数（应为 2）；`N_center_count` 为中心 N 的 W 配位数
  （你结构中的真实值，验证器会复算）。
- `space_group_symbol` 与 `space_group_number` 必须都匹配验证器从 POSCAR 重新计算的 spglib
  结果（P-6m2, No.187）；`coordination.N_three_coordination_count` 必须匹配两个外层 N
  在 ≤2.15 Å 下的重算计数。`paper_coordination_claims` 是论文 Section B 的原文数值
  `{W:6, N_outer:3, N_center:5}`，不能把中心 N 的源文声称改成几何实际值 6。
- `discrepancy_note`：论文声称与你的结构之间全部不一致点及原因；无不一致时也须说明
  核对结论。

验证器以结构文件为准独立复算全部几何量；报告与结构不一致、或关键物理量超出
允许窗口时判 FAIL。允许额外字段。
