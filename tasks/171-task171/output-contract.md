# Output contract — case-05

## `/app/final/diagnosis.json`

```json
{
  "runs": {
    "run-A": {"trustworthy": true, "pathologies": [], "evidence": "（非空证据说明）"},
    "run-B": {"trustworthy": false, "pathologies": ["unconverged_scf"], "evidence": "（非空证据说明）"},
    "run-C": {"trustworthy": false, "pathologies": ["insufficient_vacuum"], "evidence": "（非空证据说明）"},
    "run-D": {"trustworthy": false, "pathologies": ["insufficient_k_mesh"], "evidence": "（非空证据说明）"}
  },
  "selected_chain": "run-A",
  "extracted": {
    "lambda": 0.0,
    "omega_log_cm1": 0.0,
    "tc_mu016_K": 0.0,
    "lambda_from_a2f_dat": 0.0,
    "gamma_max_meV": 0.0,
    "gamma_max_mode_omega_cm1": 0.0
  }
}
```

硬性约定：

- `runs` 必须恰好包含 run-A、run-B、run-C、run-D 四键。
- `pathologies` 取值限于受控词表：`unconverged_scf`、`insufficient_vacuum`、
  `insufficient_k_mesh`、`insufficient_q_mesh`、`excessive_smearing`。
  可信运行必须为空数组；每个不可信运行的每个病理都必须真实成立
  （以设置与合成资产植入标签为判据，验证器按精确集合比对；不得将因果标签泛化到真实数据）。
- `selected_chain` = 唯一 trustworthy 的运行 id。
- `extracted` 数值取自可信链输出；`lambda_from_a2f_dat` 为你对 a2F 数据文件
  独立积分的结果（应与 `lambda` 一致，±5%）；`gamma_max_meV` /
  `gamma_max_mode_omega_cm1` 为最大 γ 模的线宽（meV）与频率（cm⁻¹）。该合成资产中
  线宽文件第三列全为 cm⁻¹，第四列 γ 为 meV。

允许额外字段；缺键、超差或病理集合不符判 FAIL。
