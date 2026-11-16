# Output contract — case-02

## `/app/final/eliashberg-results.json`

```json
{
  "lambda": 0.0,
  "omega_log_cm1": 0.0,
  "omega_log_K": 0.0,
  "tc_mu016_K": 0.0,
  "tc_mu01_K": 0.0,
  "mu_star_sensitivity": {
    "ratio_tc_mu01_over_mu016": 0.0,
    "ad_surrogate_le_10pct_supported": false,
    "sensitivity_note": "（非空文本）"
  },
  "decomposition": {
    "lambda_0_200_cm1": 0.0,
    "lambda_200_300_cm1": 0.0,
    "lambda_300_360_cm1": 0.0,
    "lambda_360_450_cm1": 0.0,
    "lambda_above_450_cm1": 0.0
  }
}
```

字段语义：

- 所有 λ/频段量为无量纲积分量；ω_log、Tc 的单位由键名标注（cm⁻¹、K）。
- `ratio_tc_mu01_over_mu016` 必须与 `tc_mu01_K / tc_mu016_K` 自洽（±2%）。
- `ad_surrogate_le_10pct_supported`：仅当你在本数据上算出的比值 ≤ 1.10 时为 true。
- 频段边界为左开右闭区间，以 cm⁻¹ 计；频段 λ 之和与 λ 之差应 < 2%。

允许额外字段；必需字段缺失、类型错误或数值超出验证器容差判 FAIL。
