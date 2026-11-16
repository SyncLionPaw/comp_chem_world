# Verification protocol — case-03（评价方专用，Agent 不可见）

## 验证分层

- **Preflight**：`/app/final/tuning-report.json` 存在且为合法 JSON。
- **L1（完备性）**：members 覆盖全部 11 个 series_id 且各含必需字段；trends 与
  extreme_coupling 字段齐全。
- **L2（科学执行有效性）**：验证器从绑定的 `a2f-tuning-series.csv`（SHA-256 校验）
  独立复算 λ、ω_log、两个 μ* 的形式 Tc 与软模权重，并逐项比较；缺少软模占比或
  非有限数值属于答案不完整/错误。
- **L3（科学判据）**：
  1. 数值锚点（复算 vs agent，容差 λ ±3%、ω_log ±3%、Tc ±1.0 K）：
     strain_0p0pct：λ=1.90、Tc(0.16)=19.36 K（论文锚点 19.4 K）；
     strain_-2p0pct：λ=1.00、Tc=12.01 K（论文锚点 12 K）；
     strain_+1p0pct：λ=3.50（论文锚点 3.5）；
     electron_1p0e：Tc(0.16)=0.78 K ∈ 论文区间 0.4–1.6 K、Tc(0.10)=2.45 K ∈
     论文区间 2–4.4 K——basis: paper_result（正文 Section C/D 数值）+
     derived_reference（合成谱标定依据，见数据文件头与 author/derived-reference.json）。
  2. 软模风险筛查：soft_mode_risk/proxy_safe 必须与低频 λ 占比 >0.30 一致；risk 成员
     的 Tc 为 null。正频合成 α²F 没有声子本征值或色散，故判据仅支持风险筛查，不支持
     真实动力学稳定性结论。空穴区间必须是相邻采样成员 [0.15, 0.20]，不要求从合成谱
     复现论文 >0.175 h/u.c. 的真实结构失稳结果。basis: provided_data + scientific_constraint。
  3. 趋势布尔量与数据真值一致（由复算 λ/ω_log 序列直接判定）：
     compression_reduces_lambda=true、compression_raises_omega_log=true、
     hole_doping_raises_lambda=true、expansion_1pct_lambda=3.50±3%——
     basis: paper_result（Fig.7/10 的趋势描述：压缩 λ 降、ω_log 升；+1% λ=3.5；
     空穴掺杂提高 λ）。
  4. 极端耦合判断：lambda_value 命中合成输入锚点 3.50±3%，并报告其超过论文所述已知
     λ≈2.6；`quantitative_tc_reliable=false` 的理由限定为“合成标量谱不足以确证真实材料
     的定量 Tc”，结合缺失的声子稳定性/收敛证据及模型适用范围。不能仅凭 λ=3.5 断言
     Migdal 理论失效；rationale 非空检查只确认说明存在，不代替科学评审。basis: paper_result
     + provided_data + scientific_constraint。

## 判据来源与出处

- 论文：docs/Campi 等 - 2021 ... W2N3.pdf Section C/D、Fig.7、Fig.8、Fig.9、Fig.10；
  SI Fig.9–29。
- 输入数据：author/inputs/a2f-tuning-series.csv（合成重构；锚点成员与插值成员的
  区分及免责声明见文件头）。
- 容差依据：0.5 cm⁻¹ 网格复算的积分量一致求积差异 <0.5%；Tc 对 λ 的敏感传播
  在 λ≈3.5 处最大约 ±0.4 K，取 ±1.0 K。

## 评分边界

PASS ↔ reward 1 ↔ exit 0；答案缺失/不可解析/科学判据失败 ↔ FAIL/reward 0/exit 1；
绑定输入、评分参考文件或依赖损坏 ↔ ENV_INVALID，无 reward，exit 2。

## 未覆盖范围

- 不要求各向异性 Migdar-Eliashberg 求解与 Δ_k 各向异性谱（论文 Fig.5–6 内容，
  留给 runtime 阶段的远程 EPW 链路）；
- 不验证真实声子谱、虚频、力常数收敛、各向异性 Eliashberg 求解或集群执行；这些结论不由本合成谱评分。
