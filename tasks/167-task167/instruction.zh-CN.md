# 任务：—构建并验证单层 W₂N₃ 结构

## 背景

单层 W₂N₃ 是候选声子介导超导体。
请根据 `assets/structure-brief.md` 构建晶体学模型，并区分给定资料陈述与结构重算结果。

## 任务

构建三维周期、五原子 W₂N₃ 原胞，空间群 P-6m2（No. 187），六方平面晶格常数 `a=2.85–2.95 Å`（在报告中说明选择），层间净真空≥15 Å。
根据对称性、键长和 brief 选择合理 z 坐标；
检查给定资料 Wyckoff 标记、配位描述及给定资料中心 N 配位声明与所建结构是否相容。
用 spglib 或 pymatgen 独立验证空间群、Wyckoff 占位和位点对称性。
不需要 DFT。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

使用最小镜像周期距离。
报告顶层原子平面到下一周期像底层原子平面的净真空（不是 `c`）、外侧 N 平面间层厚度、2.45 Å 截止下 W 配位，以及在 2.15 Å 内恰与 3 个 W 成键的外侧 N 数量。
给定资料配位声明必须与结构重算值分开。
解释所有差异。
长度单位为 Å。

### 输入与产物细则

读取 `assets/structure-brief.md`。
写入 `/app/final/W2N3-monolayer.poscar`（VASP POSCAR，缩放因子 1.0，笛卡尔晶格矢量单位 Å，Direct 分数坐标）和 `/app/final/structure-report.json`。

`structure-report.json` 必需字段与类型：`stoichiometry` 字符串；
`n_atoms`、`space_group_number` 整数；
`space_group_symbol` 字符串；
`inplane_lattice_a_A`、`vacuum_A`、`layer_thickness_A` 有限数值；
`coordination` 对象含数值 `cutoff_A`、两个整数组成的 `W_counts` 数组、整数 `N_three_coordination_count`、整数 `N_center_count`；
`paper_coordination_claims` 对象含整数 `W`、`N_outer`、`N_center`（给定资料来源值 6、3、5）；
`discrepancy_note` 非空字符串。
`W_counts` 是声明截止下 W–N 配位，并须与 2.45 Å 检查一致；
外侧 N 数须与 2.15 Å 检查一致。
空间群须与独立重算相符。
允许额外字段。

提交 `computed_wyckoff_sites`，每个原子一条记录，包含按 POSCAR 顺序从 0 起算的 `atom_index`、`species`、`wyckoff_letter` 和 `site_symmetry`。使用提交的晶胞，对称性容差为 0.001 Å。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `assets/structure-brief.md` | 给定数据、参数或方法说明；用途见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/W2N3-monolayer.poscar` | 提交结果；内容与格式按上文要求。 |
| `/app/final/structure-report.json` | 提交结果；内容与格式按上文要求。 |
