# Verification protocol — case-01（评价方专用，Agent 不可见）

## 验证分层

- **Candidate-output check**：两个必需交付物缺失、POSCAR/JSON 不可解析或报告字段缺失/类型错误，均属于候选答案不完整，判 FAIL/reward 0/exit 1。评分参考、公开输入或依赖缺失/损坏才属于 ENV_INVALID、无 reward、exit 2。
- **L1（完备性）**：`structure-report.json` 具备契约全部必需字段且类型正确；
  POSCAR 可解析（Direct 坐标、5 原子、2 W + 3 N）。
- **L2（科学执行有效性）**：验证器独立复算结构几何：
  - 六方度量：|a₁|=|a₂|（相对差 <1e-3）、γ=120°±0.5°、a₃⊥面内（|cos|<0.01）；
  - a ∈ [2.85, 2.95] Å；
  - 真空 = c − layer_thickness ≥ 15 Å；层厚 ∈ [3.5, 7.0] Å；
  - 最小原子间距 ≥ 1.5 Å（PBC 最小像）；
  - spglib（symprec 1e-3）独立判定的空间群编号 == 187；
  - 配位（PBC 最小像）：每个 W 的 N 配位数（≤2.45 Å）∈ [5,7] 且 ≥1.9 Å 最近键；
    恰好 2 个 N 与 ≤3 个 W（≤2.15 Å）成键；中心 N 与 ≤2.5 Å 的 W 数 ≥4；
  - 报告字段与复算一致：a（±0.02 Å）、vacuum（±0.5 Å）、thickness（±0.5 Å）、
    W_counts、N_center_count、N_three_coordination_count（与复算完全一致）、
    space_group_number==187 且 space_group_symbol 等于真实 spglib 符号 P-6m2。
  `paper_coordination_claims` 必须原样报告正文 Section B 的 W=6、外层 N=3、中心 N=5；
  验证器会将源文声称与 POSCAR 的实际中心 N=6 明确分开核验。
- **L3（科学判据）**：
  1. 结构满足论文全部冻结约束（计量比、No.187、a 窗口、真空、三明治配位形貌）——
     basis: paper_result（正文 Section B 数值）。
  2. `discrepancy_note` 非空且 `N_center_count` 如实报告复算值（6），即
     agent 必须发现并如实报告“论文称中心 N 为五配位，但 P-6m2 位点对称性（-6m2）
     下中心 N 只能取 3+3=6 个等距 W 邻居”这一不一致——
     basis: scientific_constraint（No.187 一重位点 -6m2 的 3 重等价轨道约束；
     参考结构 Materials Cloud 9q9yd-8kg16 W2N3-4c3b093a 中该距离为 2.233 Å）。

全部 L1+L2+L3 通过 ⇒ overall PASS（reward 1）；任一必要判据失败 ⇒ FAIL（reward 0）；
交付物缺失/不可解析 ⇒ 候选答案 FAIL（exit 1，reward 0）；绑定的评分参考、公开输入或依赖缺失/损坏 ⇒ ENV_INVALID（exit 2，无 reward）。

## 判据来源与出处

- 论文：docs/Campi 等 - 2021 ... W2N3.pdf，Section B（空间群、5 原子、a=2.912/2.898/2.890 Å、
  40 Å 真空、配位声称）。
- 参考结构（验证器内部对照，不发给 Agent）：
  tests/reference-monolayer.poscar（SHA-256 见 tests/refs.json），来源 Mounet et al. 2018，
  Materials Cloud 9q9yd-8kg16（DOI 10.24435/materialscloud:2017.0008/v1），
  文件 structures/W2N3-4c3b093a.xsf，PBE 弛豫，a=2.9131 Å，W@2i、N_outer@2h、N_center@1d。
- 注意：论文配位描述中“中心 N 五配位”与对称性矛盾；参考结构中心 N–W 距离 2.233 Å（×6）、
  外层 N–W 2.017 Å（×3）、外层 N···N 2.582 Å（不作为键）。

## 实现说明

`tests/verify.py <final_dir>`：只依赖 Python 标准库 + NumPy + spglib（requirements 已声明）。
spglib 缺失时输出结构化环境错误并 exit 2。评分边界：PASS↔reward 1↔exit 0；
FAIL↔reward 0↔exit 1；环境错误↔无 reward↔exit 2。

## 未覆盖范围

- 不验证 DFT 松弛后的键长精度（本任务不要求运行 DFT）；
- 不验证 agent 使用何种软件构建结构（方法中性）。
