# Output contract — case-03

## `/app/final/tuning-report.json`

```json
{
  "members": [
    {
      "series_id": "strain_-2p0pct",
      "lambda": 0.0,
      "omega_log_cm1": 0.0,
      "soft_mode_risk": false,
      "proxy_safe": true,
      "tc_mu016_K": 0.0,
      "tc_mu01_K": 0.0,
      "soft_lambda_fraction_below_12cm1": 0.0
    }
  ],
  "trends": {
    "compression_reduces_lambda": true,
    "compression_raises_omega_log": true,
    "expansion_1pct_lambda": 0.0,
    "hole_doping_raises_lambda": true,
    "hole_soft_mode_risk_bracket": [0.15, 0.2],
    "electron_1p0e_tc_mu016_K": 0.0,
    "electron_doping_tc_in_paper_range": true
  },
  "extreme_coupling": {
    "series_id": "strain_+1p0pct",
    "lambda_value": 0.0,
    "exceeds_known_materials": true,
    "quantitative_tc_reliable": false,
    "rationale": "（非空文本）"
  },
  "notes": "（可选文本）"
}
```

字段语义与硬性约定：

- `members` 必须覆盖全部 11 个 series_id（文件中出现的每个 id 恰好一条）：
  strain_-2p0pct, strain_-1p0pct, strain_-0p5pct, strain_0p0pct, strain_+0p5pct,
  strain_+1p0pct, hole_0p10h, hole_0p15h, hole_0p20h, electron_0p5e, electron_1p0e。
- `soft_lambda_fraction_below_12cm1` = λ(ω<12 cm⁻¹)/λ_total；占比 >0.30 时
  `soft_mode_risk=true`、`proxy_safe=false` 且两个 Tc 字段必须为 null；否则 `false/true`
  且 Tc 字段为数值。这些字段只代表正频 α²F 的低频权重筛查结果，不是动力学稳定性结论。
- `hole_soft_mode_risk_bracket` 是输入采样中最高 proxy-safe 与最低 risk 的空穴掺杂值。
  它必须来自实际相邻输入成员；不能内插成单点，也不能表述为真实结构失稳阈值。
  论文的 >0.175 h/u.c. 结论来自其结构/声子计算，不能仅凭此合成谱代理重现。
- `electron_1p0e_tc_mu016_K`：electron_1p0e 成员的 Tc(μ*=0.16)，须与 members 中
  对应条目一致；`electron_doping_tc_in_paper_range`：该值是否落入论文报告区间
  0.4–1.6 K（允许 ±0.1 K 边界余量）。
- `extreme_coupling.lambda_value` 须与 strain_+1p0pct 成员的 λ 一致；
  `exceeds_known_materials` 按论文（已知最高 λ≈2.6）判断；
  `quantitative_tc_reliable` 表达该合成标量谱是否足以确证真实材料的定量 Tc；须说明
  数据合成、声子稳定性证据与各向异性求解缺口。文本非空检查不构成论证质量证明。

允许额外字段；必需字段缺失、成员缺失或数值超容差判 FAIL。
