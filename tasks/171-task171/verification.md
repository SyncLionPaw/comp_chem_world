# Verification protocol — case-05（评价方专用，Agent 不可见）

## 验证分层

- **Candidate-output check**：`diagnosis.json` 缺失、不可解析或候选字段缺失，判 FAIL/reward 0/exit 1。包内 tar.gz 或 refs.json 缺失/损坏才属于 ENV_INVALID、无 reward、exit 2；候选 JSON 不应被归为环境错误。
- **Bound-input integrity**：包内 tar.gz 必须与 refs.json 中 SHA-256 一致。
- **L1（完备性）**：runs 恰好四键；selected_chain 与 extracted 字段齐全。
- **L2（科学执行有效性）**：验证器解包绑定的 `epc-campaign.tar.gz`，独立解析：
  - `runA_lambda_summary.txt`（λ=1.9000、ω_log=112.8410 cm⁻¹、Tc(0.16)=19.40、
    Tc(0.10)=22.56）作为提取参考；
  - `runA_a2f.dat` 独立梯形积分 λ_ref（eV 单位）；
  - `runA_linewidths.dat` 最大 γ 模（4.80 meV @ 329.9 cm⁻¹）。合成文件第 3 列为频率 cm⁻¹，第 4 列为 γ meV；40.9 meV 对应约 329.9 cm⁻¹（1 meV ≈ 8.0655 cm⁻¹），不是 40.9 cm⁻¹。
- **L3（科学判据）**：
  1. 提取正确：lambda ∈ 1.90±0.05（与摘要一致）；omega_log_cm1 ∈ [110.8, 114.8]；
     tc_mu016_K ∈ [18.9, 19.9]（论文锚点 19.4 K）；lambda_from_a2f_dat 与
     验证器积分值一致（±5%）且与 lambda 一致（±5%）——basis: derived_reference
     （合成数据按论文锚点标定）+ paper_result（λ=1.9、Tc 19.4 K）。
  2. 线宽物理判读：gamma_max_meV ∈ [4.5, 5.1] 且
      gamma_max_mode_omega_cm1 ∈ [326, 334] cm⁻¹——最大线宽模是 330 cm⁻¹ 光学模
     ——basis: paper_result（正文：330 与 400 cm⁻¹ 光学模线宽最大、330 最大）。
  3. 诊断精确集合（受控词表）：run-A: ∅；run-B: {unconverged_scf}；
     run-C: {insufficient_vacuum}（Γ 点幽灵声学支 −2.3/4.8/5.1 cm⁻¹ 为症状，
     根因是 10 Å cell 高度导致镜像层耦合）；run-D:
     {insufficient_k_mesh, insufficient_q_mesh, excessive_smearing}
     （24×24/12×12 对照 192×192/96×96；sk=0.5 eV 对照 0.05 eV）——
     basis: paper_result（论文协议数值）+ scientific_constraint
     （Γ 声学支必须为零频、2D 计算需要充分真空、线性响应线宽的
     k/q 收敛与展宽敏感性）。
  4. selected_chain == "run-A" 且每个 run 的 evidence 为非空文本。

## 判据来源与出处

- 论文：docs/Campi 等 - 2021 ... W2N3.pdf Section B/C（协议与结果数值）。
- 输入：author/inputs/epc-campaign.tar.gz（合成重构包；settings.json 给出全部
  运行参数；README 与文件头声明非作者原始数据）。
- 病理-证据对应：runB 输出含 "convergence NOT achieved"；runC settings
  cell_height_z_A=10.0 且 runC_phonons_gamma.dat Γ 行含负频；runD settings
  k_mesh_epw=[24,24]、q_mesh_epw=[12,12]、sk_ev=0.5，且其 Tc=28.9 K 与
  可信链 19.4 K 明显背离（过收敛差异）。

## 评分边界

PASS ↔ reward 1 ↔ exit 0；任一必要判据失败或候选交付物缺失/不可解析 ↔ FAIL/reward 0/exit 1；
包完整性、绑定参考或依赖失败 ↔ ENV_INVALID，无 reward，exit 2。

## 未覆盖范围

- 不要求复现 run-D 的"正确"收敛 Tc（收敛性外推属 case-06/远程范围）；
- evidence 为自由文本，验证器只检查非空；内容质量由 verification.md
  所列对应关系约束并在下游审查中复核。
