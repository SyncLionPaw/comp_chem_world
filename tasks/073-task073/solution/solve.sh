#!/usr/bin/env bash
set -euo pipefail
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/task74-solution.XXXXXX")"
# Keep extracted sources available until execution and any HPC staging/collection finish.
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'TASK_SOURCE_SOLVE_PY'
#!/usr/bin/env python3
"""Summarize the public Fig. 9a measurements and describe post-hydrolysis shifts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

PANELS = {
    ("S", "WT"): (0, 1),
    ("D-AspAsh", "WT"): (2, 3),
    ("D-ADP-Pi", "WT"): (4, 5),
    ("S", "V72I"): (6, 7),
    ("D-AspAsh", "V72I"): (8, 9),
    # The data dictionary reverses the final panel: column 11 is gamma.
    ("D-ADP-Pi", "V72I"): (11, 10),
}


def summarize(values: np.ndarray) -> dict[str, int | float]:
    clean = values[np.isfinite(values)]
    return {
        "n": int(clean.size),
        "mean": float(np.mean(clean)),
        "std": float(np.std(clean, ddof=1)),
        "median": float(np.median(clean)),
        "q25": float(np.quantile(clean, 0.25)),
        "q75": float(np.quantile(clean, 0.75)),
    }


def build(data_path: Path, statistic: str) -> dict:
    frame = pd.read_csv(data_path, sep=r"\s+", header=0, na_values=["NaN"], engine="c")
    if frame.shape != (560000, 12):
        raise ValueError(f"Fig_9a.dat has unexpected shape {frame.shape}")

    summaries: dict[tuple[str, str, str], dict] = {}
    rows = []
    for (condition, variant), (delta_col, gamma_col) in PANELS.items():
        for observable, col in (("delta", delta_col), ("gamma", gamma_col)):
            summary = summarize(frame.iloc[:, col].to_numpy(dtype=float))
            summaries[(condition, variant, observable)] = summary
            rows.append({"condition": condition, "variant": variant, "observable": observable, **summary})

    comparisons = []
    for variant in ("WT", "V72I"):
        for observable in ("delta", "gamma"):
            base = summaries[("D-AspAsh", variant, observable)][statistic]
            target = summaries[("D-ADP-Pi", variant, observable)][statistic]
            effect = target - base
            conclusion = "increased" if effect > 2e-6 else "decreased" if effect < -2e-6 else "inconclusive"
            comparisons.append({
                "variant": variant,
                "observable": observable,
                "baseline": "D-AspAsh",
                "target": "D-ADP-Pi",
                "location_statistic": statistic,
                "effect": float(effect),
                "units": "angstrom" if observable == "delta" else "degree",
                "conclusion": conclusion,
            })

    return_toward_s = []
    for variant in ("WT", "V72I"):
        s = summaries[("S", variant, "delta")][statistic]
        before = abs(summaries[("D-AspAsh", variant, "delta")][statistic] - s)
        after = abs(summaries[("D-ADP-Pi", variant, "delta")][statistic] - s)
        return_toward_s.append({
            "variant": variant,
            "location_statistic": statistic,
            "baseline_condition": "D-AspAsh",
            "target_condition": "D-ADP-Pi",
            "reference_condition": "S",
            "before_distance": float(before),
            "after_distance": float(after),
            "units": "angstrom",
            "closer_to_S": bool(after < before),
        })

    spread = [
        {"condition": row["condition"], "variant": row["variant"], "observable": row["observable"],
         "q25": row["q25"], "q75": row["q75"]}
        for row in rows
    ]
    return {
        "schema_version": "post-hydrolysis/v1",
        "summary_statistics": rows,
        "statistical_methods": [
            "Empirical summaries: mean, sample standard deviation, median, and linearly interpolated 25th/75th percentiles.",
            "Post-hydrolysis effects are target minus baseline central tendency using descriptive summaries.",
        ],
        "comparisons": comparisons,
        "return_toward_S": return_toward_s,
        "uncertainty": {
            "approach": "descriptive",
            "independent_sampling_claim": False,
            "series_spread": spread,
            "applicability": "pooled_empirical_data",
            "limitations": ["no_replica_labels", "no_time_axis"],
        },
    }


def make_report(findings: dict) -> str:
    comparisons = findings["comparisons"]
    returning = findings["return_toward_S"]
    lines = [
        "# ATP 水解后的口袋打开与顶端回落",
        "",
        "比较 D-ADP-Pi 与 D-AspAsh 的同一中心统计量，效应定义为目标减基线。δ 使用 Å，γ 使用度；方向来自逐帧经验分布的摘要统计。",
        "",
        "| 变体 | 观测量 | 统计量 | 效应 | 方向 |",
        "|---|---|---:|---:|---|",
    ]
    for row in comparisons:
        units = "Å" if row["observable"] == "delta" else "度"
        label = "口袋距离 δ" if row["observable"] == "delta" else "顶端角 γ"
        lines.append(f"| {row['variant']} | {label} | {row['location_statistic']} | {row['effect']:.6f} {units} | {row['conclusion']} |")
    lines.extend(["", "## 向单环 S 的距离", "", "| 变体 | 统计量 | AspAsh 到 S | ADP-Pi 到 S | 是否更接近 S |", "|---|---|---:|---:|---|"])
    for row in returning:
        lines.append(f"| {row['variant']} | {row['location_statistic']} | {row['before_distance']:.6f} Å | {row['after_distance']:.6f} Å | {'是' if row['closer_to_S'] else '否'} |")
    lines.extend([
        "",
        "不确定度按 pooled empirical data 的四分位距描述；数据没有 replica labels 或 time axis，因此这些逐帧样本不被视为独立重复，不报告置信区间或显著性检验。δ 向 S 靠近表示中心位置距离缩短，不表示完全恢复。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, default=Path("/app/assets"))
    parser.add_argument("--output", type=Path, default=Path("/app/final"))
    parser.add_argument("--statistic", choices=("mean", "median"), default="mean")
    args = parser.parse_args()
    findings = build(args.assets / "Fig_9a.dat", args.statistic)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "findings.json").write_text(json.dumps(findings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "report.md").write_text(make_report(findings), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
TASK_SOURCE_SOLVE_PY

python3 "$work_dir/solve.py" "$@"
