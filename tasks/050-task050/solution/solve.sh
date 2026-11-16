#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${OUTPUT_DIR:-/app}"
SOLUTION_DIR="$APP_DIR/solution"
ASSET_DIR="$APP_DIR/environment/assets"
mkdir -p "$SOLUTION_DIR"
WORK="$(mktemp -d)"
cleanup() { status=$?; trap - EXIT; rm -rf "$WORK"; exit "$status"; }
trap cleanup EXIT
cat > "$WORK/analyze.py" <<'CCW_TASK50_ANALYZE_PY_EOF'
#!/usr/bin/env python3
"""Recompute an archived case-02 analysis from its three public inputs."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
ASSETS = HERE / "environment" / "assets"
sys.path.insert(0, str(ASSETS))
import statistics_builder as sb  # noqa: E402

SCHEMA = "case02-archived-online-analysis/v1"
TRAJECTORY_COLUMNS = ["step", "time", "x", "y", "U", "bias_x", "kl", "learning_rate", "bias_version", "replica"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(required).issubset(reader.fieldnames):
            raise ValueError(f"{path.name} has missing required columns")
        return list(reader)


def audit_history(rows: list[dict[str, str]], protocol: dict) -> dict:
    centers = protocol["bias"]["centers"]
    parsed = []
    groups: dict[tuple[int, int], list[int]] = {}
    for line, row in enumerate(rows, 2):
        try:
            stepf, versionf, indexf = float(row["step"]), float(row["bias_version"]), float(row["parameter_index"])
            theta = float(row["theta"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"bias-history.csv:{line} contains invalid values") from exc
        if not all(math.isfinite(v) for v in (stepf, versionf, indexf, theta)):
            raise ValueError(f"bias-history.csv:{line} contains non-finite values")
        if any(v != int(v) for v in (stepf, versionf, indexf)):
            raise ValueError(f"bias-history.csv:{line} integer field is fractional")
        step, version, index = int(stepf), int(versionf), int(indexf)
        if step < 0 or version < 0 or not 0 <= index < len(centers):
            raise ValueError(f"bias-history.csv:{line} index is outside protocol")
        groups.setdefault((step, version), []).append(index)
        parsed.append((step, version, index))
    versions: dict[int, int] = {}
    for (step, version), indices in groups.items():
        if len(indices) != len(centers) or len(set(indices)) != len(centers) or set(indices) != set(range(len(centers))):
            raise ValueError(f"bias history update {version} at step {step} is incomplete or duplicated")
        if version in versions:
            raise ValueError("one bias version appears at more than one update step")
        versions[version] = step
    ordered = sorted(versions.items())
    if not ordered or ordered[0][0] != 0 or [v for v, _ in ordered] != list(range(ordered[0][0], ordered[-1][0] + 1)):
        raise ValueError("bias versions must be a contiguous history starting at version zero")
    if any(ordered[i][1] >= ordered[i + 1][1] for i in range(len(ordered) - 1)):
        raise ValueError("bias update steps are not strictly increasing")
    freeze_version, freeze_step = ordered[-1]
    interval = protocol["optimizer"].get("update_interval")
    if not isinstance(interval, int) or interval < 1 or any(step != version * interval for version, step in ordered):
        raise ValueError("recorded update steps do not match the declared optimizer interval and version sequence")
    initial = protocol["bias"].get("initial_theta")
    initial_rows = [r for r in rows if r["bias_version"] == 0]
    if not isinstance(initial, list) or len(initial) != len(centers):
        raise ValueError("protocol initial coefficients do not match the basis")
    initial_map = {int(r["parameter_index"]): float(r["theta"]) for r in initial_rows}
    if set(initial_map) != set(range(len(centers))) or any(not math.isclose(initial_map[i], float(initial[i]), rel_tol=0, abs_tol=1e-10) for i in range(len(centers))):
        raise ValueError("version-zero history does not match protocol initial coefficients")
    return {"complete_updates": len(ordered), "parameter_count": len(centers),
            "versions": [v for v, _ in ordered], "update_steps": [s for _, s in ordered],
            "last_complete_update": {"bias_version": freeze_version, "step": freeze_step},
            "cutoff_rule": "last complete recorded bias-history update; not a first-eligible-freeze claim"}


def validate_trajectory_history(matrix: np.ndarray, history: list[dict], protocol: dict) -> None:
    """Bind each saved frame to the complete recorded bias version used for it."""
    centers = np.asarray(protocol["bias"]["centers"], dtype=np.float64)
    sigma = float(protocol["bias"]["sigma"])
    gauge = float(protocol["bias"].get("gauge_offset", 0.0))
    grouped: dict[int, dict[int, float]] = {}
    steps_by_version: dict[int, int] = {}
    for row in history:
        version, step, index = int(row["bias_version"]), int(row["step"]), int(row["parameter_index"])
        if version in steps_by_version and steps_by_version[version] != step:
            raise ValueError("one bias version maps to inconsistent update steps")
        steps_by_version[version] = step
        if index in grouped.setdefault(version, {}):
            raise ValueError("bias history repeats a parameter index")
        grouped[version][index] = float(row["theta"])
    if not steps_by_version:
        raise ValueError("bias history is empty")
    ordered = sorted((step, version) for version, step in steps_by_version.items())
    next_step = {version: ordered[i + 1][0] if i + 1 < len(ordered) else math.inf
                 for i, (_, version) in enumerate(ordered)}
    coeff = {}
    for version, by_index in grouped.items():
        if set(by_index) != set(range(len(centers))):
            raise ValueError(f"bias version {version} is incomplete")
        coeff[version] = np.asarray([by_index[i] for i in range(len(centers))], dtype=np.float64)
    version_steps = {version: step for version, step in steps_by_version.items()}
    for version in sorted(set(int(v) for v in matrix[:, 8])):
        if version not in coeff:
            raise ValueError(f"trajectory references unrecorded bias version {version}")
        mask = matrix[:, 8] == version
        rows = matrix[mask]
        low = version_steps[version]
        high = next_step[version]
        if np.any(rows[:, 0] <= low) or np.any(rows[:, 0] > high):
            raise ValueError(f"trajectory step is inconsistent with bias version {version}")
        theta = coeff[version]
        for start in range(0, len(rows), 8192):
            chunk = rows[start:start + 8192]
            basis = np.exp(-0.5 * ((chunk[:, 2, None] - centers[None, :]) / sigma) ** 2)
            expected = gauge + np.sum(basis * theta[None, :], axis=1)
            if not np.allclose(chunk[:, 5], expected, rtol=1e-10, atol=1e-8):
                raise ValueError(f"trajectory bias_x disagrees with recorded coefficients for version {version}")


def rename_analysis_windows(value):
    names = {"pre_freeze": "pre_analysis_cutoff", "post_freeze": "post_analysis_cutoff",
             "late_post": "late_post_analysis_cutoff"}
    if isinstance(value, dict):
        return {names.get(k, k): rename_analysis_windows(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rename_analysis_windows(v) for v in value]
    return value


def analyze(data_dir: Path, analysis_cutoff: int | None = None) -> dict:
    data_dir = data_dir.resolve()
    protocol_path = data_dir / "run-protocol.json"
    trajectory_path = data_dir / "trajectory.csv"
    history_path = data_dir / "bias-history.csv"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    history_rows = read_csv(history_path, ["step", "bias_version", "parameter_index", "theta"])
    history = []
    for row in history_rows:
        item = dict(row)
        for key in ("step", "bias_version", "parameter_index"):
            item[key] = int(item[key])
        for key in ("theta", "gradient", "adam_m", "adam_v", "learning_rate"):
            if key in item:
                item[key] = float(item[key])
        history.append(item)
    history_audit = audit_history(history, protocol)
    recorded_update = history_audit["last_complete_update"]
    if analysis_cutoff is None:
        cutoff_step = recorded_update["step"]
    else:
        if isinstance(analysis_cutoff, bool) or not isinstance(analysis_cutoff, int):
            raise ValueError("analysis cutoff must be an integer saved-step value")
        if analysis_cutoff < recorded_update["step"]:
            raise ValueError("analysis cutoff precedes the last complete recorded update and is not a static window")
        cutoff_step = analysis_cutoff
    freeze = {"step": cutoff_step, "bias_version": recorded_update["bias_version"]}
    matrix = sb._read_csv_matrix(trajectory_path, TRAJECTORY_COLUMNS)
    sample_ids = sorted(set(int(x) for x in matrix[:, 9]))
    expected_ids = list(range(1, len(protocol["dynamics"]["replica_seeds"]) + 1))
    if sample_ids != expected_ids:
        raise ValueError("trajectory replica IDs must match the protocol's complete replica set")
    if analysis_cutoff is not None:
        for rid in expected_ids:
            if not np.any((matrix[:, 9] == rid) & (matrix[:, 0] == cutoff_step)):
                raise ValueError("explicit analysis cutoff must be a saved frame for every replica")
    per_replica = {}
    exposure_shapes = set()
    for rid in sample_ids:
        part = matrix[matrix[:, 9] == rid]
        steps = part[:, 0]
        shape = (len(part), int(np.min(steps)), int(np.max(steps)))
        exposure_shapes.add(shape)
        per_replica[str(rid)] = {"rows": int(len(part)), "first_step": int(np.min(steps)),
                                 "last_step": int(np.max(steps)),
                                 "strict_post_cutoff_rows": int(np.count_nonzero(steps > freeze["step"]))}
    if len(exposure_shapes) != 1:
        raise ValueError("replicas must have matching saved-frame exposure for this analysis contract")
    validate_trajectory_history(matrix, history, protocol)
    result = sb.compute(matrix, freeze["step"], protocol, reference=None, bias_history=history)
    diag = result["derived_diagnostics"]
    adequate = (diag["conservative"]["coverage"] >= 0.90
                and diag["conservative"]["rmse_kBT"] is not None and diag["conservative"]["rmse_kBT"] <= 1.0
                and diag["conservative"]["absolute_error_p95_kBT"] is not None
                and diag["conservative"]["absolute_error_p95_kBT"] <= 2.0)
    return {"schema": SCHEMA,
            "input_sha256": {"trajectory.csv": sha256(trajectory_path),
                             "run-protocol.json": sha256(protocol_path),
                             "bias-history.csv": sha256(history_path)},
            "recorded_update_cutoff": recorded_update,
            "cutoff": {"step": freeze["step"], "bias_version": freeze["bias_version"],
                       "rule": "chosen analysis cutoff must be at or after the last complete recorded update; strict static rows satisfy step > chosen cutoff"},
            "history_audit": history_audit,
            "sample_audit": {"trajectory_rows": int(len(matrix)), "replica_ids": sample_ids,
                             "per_replica": per_replica,
                             "optimizer_sample_interval_steps": protocol["optimizer"]["sample_stride"],
                             "optimizer_update_interval": protocol["optimizer"]["update_interval"],
                             "saved_trajectory_stride": protocol["dynamics"]["sample_stride"],
                             "strict_post_cutoff_rows": diag["settings"]["postfreeze_rows"]},
            "fes_bins": result["reweighted_fes"],
            "legacy": diag["legacy"], "conservative": diag["conservative"],
            "support": diag["support"], "window_boundary": "analysis_cutoff",
            "windows": rename_analysis_windows(diag["windows"]),
            "sensitivity": rename_analysis_windows(diag["sensitivity"]),
            "instance_adequacy": {"thresholds_met": adequate,
                "criteria": {"coverage_min": 0.90, "supported_bin_ess_min": 20.0,
                              "weighted_rmse_max_kBT": 1.0, "absolute_error_p95_max_kBT": 2.0},
                "legacy_thresholds_met": bool(diag["legacy"]["all_thresholds_pass"]),
                "original_l3_thresholds_met": adequate,
                "additional_conservative_checks_met": bool(diag["conservative"]["all_thresholds_pass"])},
            "interpretation_limits": {"fresh_run": False,
                "optimizer_internal_batches_independently_verified": False,
                "first_eligible_freeze_established": False,
                "causal_cv_sufficiency_established": False,
                "production_convergence_established": False,
                "saved_trajectory_stride_is_distinct_from_optimizer_stride": True}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ASSETS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analysis-cutoff", type=int, default=None,
                        help="optional saved-step analysis cutoff; must be no earlier than the last complete bias-history update")
    args = parser.parse_args()
    output = analyze(args.data_dir, args.analysis_cutoff)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_name(args.output.name + ".tmp")
    tmp.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    print(json.dumps({"output": str(args.output), "schema": SCHEMA,
                      "cutoff_step": output["cutoff"]["step"],
                      "thresholds_met": output["instance_adequacy"]["thresholds_met"]}))


if __name__ == "__main__":
    main()
CCW_TASK50_ANALYZE_PY_EOF
chmod 0755 "$WORK/analyze.py"
cp "$WORK/analyze.py" "$SOLUTION_DIR/analyze.py"
python3 "$SOLUTION_DIR/analyze.py" \
  --data-dir "$ASSET_DIR" \
  --output "$APP_DIR/result.json"
