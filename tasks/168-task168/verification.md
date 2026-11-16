# Verification protocol — case-02（评价方专用，Agent 不可见）

## 验证分层

- **Candidate-output check**：`/app/final/eliashberg-results.json` 缺失、不可解析、必需字段缺失或字段类型无效，均属于候选答案错误/不完整，判 FAIL/reward 0/exit 1。绑定谱文件、评分参考或依赖缺失/损坏才属于 ENV_INVALID、无 reward、exit 2。
- **L1（完备性）**：契约必需字段齐全且为数值/布尔/文本类型。
- **L2（科学执行有效性）**：验证器从包内绑定的
  `environment/assets/a2f-unstrained.csv`（SHA-256 校验）用独立实现复算：
  λ、ω_log（cm⁻¹、K）、Tc(μ*=0.16/0.10)、五个频段 λ；与 agent 结果逐项比较。
- **L3（科学判据）**：
  1. λ = 1.90 ± 2%、ω_log = 112.8 cm⁻¹ ± 2%（= 162.3 K ± 2%）、
     Tc(μ*=0.16) = 19.36 K ± 0.6 K、Tc(μ*=0.10) = 22.52 K ± 0.6 K——
     basis: derived_reference（合成谱按论文锚点 λ=1.9、AD Tc=19.4 K 标定；
     复算锚点由 verify.py 从绑定数据独立积分得到）。
  2. 频段分解与复算一致（每段 max(±8%, ±0.01)），且两个最大贡献频段必须是
     `lambda_0_200_cm1`（声学模，复算值 ≈1.248）与 `lambda_300_360_cm1`
     （330 cm⁻¹ 光学模，复算值 ≈0.378）——basis: paper_result（正文 Section C：
     耦合由 BZ 中部 LA/SH 声学模与 Γ 点 330/400 cm⁻¹ 光学模主导；330 线宽最大）。
  3. 敏感性：ratio 与自洽检查一致且 ∈ [1.13, 1.19]（复算 1.163）；
     `ad_surrogate_le_10pct_supported` 必须为 false——本合成标量谱与 Allen–Dynes 代理上
     Allen-Dynes 的 μ* 敏感性约为 16%，与论文"≤10%"陈述不一致（该陈述针对
     论文自身的各向同性 ME 结果/数据，口径不同）。agent 必须报告计算结论而非
     复述论文——basis: independent_calculation + scientific_constraint
     （Allen-Dynes 公式中 Tc 比值仅依赖 λ 与 μ*，λ=1.9 时解析可算）。
     `sensitivity_note` 为非空文本。

## 判据来源与出处

- 论文：docs/Campi 等 - 2021 ... W2N3.pdf Section C（λ=1.9、Tc(AD, μ*=0.16)=19.4 K、
  μ* 敏感性陈述）；SI Fig.3（网格收敛）。
- 输入数据：author/inputs/a2f-unstrained.csv（合成重构，标定依据与免责声明见文件头；
  SHA-256 与 tests/refs.json 一致）。
- 复算容差依据：0.5 cm⁻¹ 网格上任意一致求积的积分差异 <0.5%，故主量取 ±2%、
  频段取 ±8%（Gap 区段绝对量小，叠加 ±0.01 绝对容差）。

## 评分边界

PASS ↔ reward 1 ↔ exit 0；任一必要判据失败 ↔ FAIL/reward 0/exit 1；
候选交付物缺失、不可解析或科学判据失败 ↔ FAIL/reward 0/exit 1；绑定资产或评分参考校验失败 ↔ ENV_INVALID，无 reward，exit 2。

## 未覆盖范围

- 不要求各向同性/各向异性 Migdar-Eliashberg 求解（case-03 覆盖其等价物）；
- 不验证 agent 的积分代码实现细节（方法中性，只验证数值结果与自洽性）。
