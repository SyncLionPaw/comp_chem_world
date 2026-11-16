"""Regression checks for the two documented block weight scales."""
from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path

import pytest


TASK = Path(__file__).resolve().parents[1]
SCIENCE = TASK / "tests" / "science"
VERIFY_SPEC = importlib.util.spec_from_file_location("task64_verify", SCIENCE / "verify.py")
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)
VERIFY.configure_trusted_paths(
    ref_path=SCIENCE / "refs.json",
    source_path=TASK / "environment" / "assets" / "g4-thermodynamic-records.npz",
)
DATA = VERIFY.load_source()


def write_candidate(
    path: Path,
    scale: str = "global",
    time_representation: str = "interval_edges",
    population: str = "histogram",
    data: dict = DATA,
) -> tuple[dict, list[dict]]:
    result = VERIFY.reweight(
        data,
        edge="floor",
        block_weight_scope=population,
        block_origin="burn_time",
    )
    path.mkdir(parents=True, exist_ok=True)
    with (path / "FES.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["z_nm", "probability", "F_kJ_mol", "F_kcal_mol"])
        for z, probability, free_energy in zip(
            result["centers"], result["probabilities"], result["F_kJ"]
        ):
            writer.writerow([
                repr(float(z)),
                repr(float(probability)),
                repr(float(free_energy)) if math.isfinite(free_energy) else "",
                repr(float(free_energy / VERIFY.KCAL)) if math.isfinite(free_energy) else "",
            ])

    maximum = max(block["max_log_weight"] for block in result["blocks"])
    blocks = []
    for block in result["blocks"]:
        scaled_sum = block["weight_sum_scaled"]
        if scale == "global":
            scaled_sum *= math.exp(block["max_log_weight"] - maximum)
        elif scale != "local":
            raise ValueError(f"unknown scale: {scale}")
        if time_representation == "interval_edges":
            time_start, time_end = block["time_start_ps"], block["time_end_ps"]
        elif time_representation == "observed_eligible":
            time_start = block["_observed_time_start_ps"]
            time_end = block["_observed_time_end_ps"]
        else:
            raise ValueError(f"unknown time representation: {time_representation}")
        blocks.append({
            "block": block["block"] + 1,
            "time_start_ps": time_start,
            "time_end_ps": time_end,
            "eligible_rows": block["eligible_rows"],
            "weight_sum_scaled": scaled_sum,
            "max_log_weight": block["max_log_weight"],
            "deltaG_kJ_mol": block["deltaG_kJ_mol"],
            "deltaG_kcal_mol": block["deltaG_kcal_mol"],
        })
    with (path / "blocks.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(blocks[0]))
        writer.writeheader()
        writer.writerows(blocks)

    (path / "thermodynamics.json").write_text(json.dumps({"thermodynamics": {
        "deltaG_kcal_mol": result["deltaG_kcal"],
        "deltaG_kJ_mol": result["deltaG_kJ"],
        "weighted_block_mean_kcal_mol": result["block_mean_kcal"],
        "weighted_block_mean_kJ_mol": result["block_mean_kcal"] * VERIFY.KCAL,
        "weighted_block_sd_kcal_mol": result["block_sd_kcal"],
        "weighted_block_formal_se_kcal_mol": result["block_formal_se_kcal"],
        "frame_effective_sample_size": result["frame_ess"],
        "block_effective_sample_size": result["block_ess"],
    }}, indent=2) + "\n", encoding="utf-8")
    return result, blocks


def edit_csv(path: Path, filename: str, row_index: int, field: str, delta: float) -> None:
    csv_path = path / filename
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    fields = list(rows[0])
    rows[row_index][field] = repr(float(rows[row_index][field]) + delta)
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def reject(path: Path, field: str) -> None:
    with pytest.raises(VERIFY.CandidateFail, match=field):
        VERIFY.try_matching_modes(DATA, path)


@pytest.mark.parametrize("scale", ["local", "global"])
def test_uniform_local_and_global_scales_replay(tmp_path: Path, scale: str) -> None:
    candidate = tmp_path / scale
    write_candidate(candidate, scale)
    matches = VERIFY.try_matching_modes(DATA, candidate)
    assert len(matches) == 1
    assert matches[0]["method"] == {
        "bin_edge_assignment": "floor",
        "block_weight_population": "histogram",
        "block_time_origin": "burn_time",
    }


@pytest.mark.parametrize("time_representation", ["interval_edges", "observed_eligible"])
def test_uniform_time_representations_replay(tmp_path: Path, time_representation: str) -> None:
    candidate = tmp_path / time_representation
    write_candidate(candidate, "global", time_representation)
    VERIFY.try_matching_modes(DATA, candidate)


def test_mixed_time_representations_are_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "mixed-times"
    write_candidate(candidate, "global", "interval_edges")
    result = VERIFY.reweight(DATA, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    rows = list(csv.DictReader((candidate / "blocks.csv").open(newline="", encoding="utf-8")))
    fields = list(rows[0])
    rows[0]["time_start_ps"] = repr(result["blocks"][0]["_observed_time_start_ps"])
    with (candidate / "blocks.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    reject(candidate, "time_start_ps")


def test_in_range_but_nonobserved_endpoint_is_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "fake-endpoint"
    write_candidate(candidate, "global", "observed_eligible")
    result = VERIFY.reweight(DATA, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    rows = list(csv.DictReader((candidate / "blocks.csv").open(newline="", encoding="utf-8")))
    fields = list(rows[0])
    start = result["blocks"][0]["_observed_time_start_ps"]
    rows[0]["time_start_ps"] = repr(start + 0.1)
    with (candidate / "blocks.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    reject(candidate, "time_start_ps")


def test_endpoint_from_wrong_population_is_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "wrong-population-time"
    altered = {key: values.copy() for key, values in DATA.items()}
    # Make the first wall-eligible source row fall outside the z histogram range.
    first_wall = next(i for i, (time, wall_value) in enumerate(zip(altered["time_ps"], altered["funnelwall_bias_kJ_mol"]))
                      if time >= 20000.0 and wall_value <= 10.0)
    altered["cyl_z_nm"][first_wall] = 1.9
    write_candidate(candidate, "global", "observed_eligible", "histogram", altered)
    histogram = VERIFY.reweight(altered, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    wall = VERIFY.reweight(altered, edge="floor", block_weight_scope="wall", block_origin="burn_time")
    differing = next(
        i for i, (h, w) in enumerate(zip(histogram["blocks"], wall["blocks"]))
        if h["_observed_time_start_ps"] != w["_observed_time_start_ps"]
        or h["_observed_time_end_ps"] != w["_observed_time_end_ps"]
    )
    rows = list(csv.DictReader((candidate / "blocks.csv").open(newline="", encoding="utf-8")))
    fields = list(rows[0])
    rows[differing]["time_start_ps"] = repr(wall["blocks"][differing]["_observed_time_start_ps"])
    rows[differing]["time_end_ps"] = repr(wall["blocks"][differing]["_observed_time_end_ps"])
    with (candidate / "blocks.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(VERIFY.CandidateFail, match="time_start_ps|time_end_ps"):
        VERIFY.try_matching_modes(altered, candidate)


def test_mixed_scale_is_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "mixed"
    result, blocks = write_candidate(candidate, "global")
    maximum = max(block["max_log_weight"] for block in result["blocks"])
    edit_csv(candidate, "blocks.csv", 0, "weight_sum_scaled",
             blocks[0]["weight_sum_scaled"] * math.exp(maximum - blocks[0]["max_log_weight"]) - blocks[0]["weight_sum_scaled"])
    reject(candidate, "weight_sum_scaled")


@pytest.mark.parametrize("field,delta", [
    ("weight_sum_scaled", 2.0),
    ("max_log_weight", 0.01),
])
def test_block_field_tampering_is_rejected(tmp_path: Path, field: str, delta: float) -> None:
    candidate = tmp_path / field
    write_candidate(candidate, "global")
    edit_csv(candidate, "blocks.csv", 0, field, delta)
    reject(candidate, field)


def test_weighted_block_sd_tampering_is_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "sd"
    result, _ = write_candidate(candidate, "global")
    therm_path = candidate / "thermodynamics.json"
    therm = json.loads(therm_path.read_text(encoding="utf-8"))
    therm["thermodynamics"]["weighted_block_sd_kcal_mol"] = result["block_sd_kcal"] + 0.01
    therm_path.write_text(json.dumps(therm) + "\n", encoding="utf-8")
    reject(candidate, "weighted_block_sd_kcal_mol")


@pytest.mark.parametrize("field,within,outside", [
    ("weight_sum_scaled", 0.5e-6, 1.5e-6),
    ("max_log_weight", 0.5e-8, 1.5e-8),
])
def test_block_tolerances_are_preserved(tmp_path: Path, field: str, within: float, outside: float) -> None:
    accepted = tmp_path / f"{field}-within"
    write_candidate(accepted, "global")
    edit_csv(accepted, "blocks.csv", 0, field, within)
    VERIFY.try_matching_modes(DATA, accepted)

    rejected = tmp_path / f"{field}-outside"
    write_candidate(rejected, "global")
    edit_csv(rejected, "blocks.csv", 0, field, outside)
    reject(rejected, field)


@pytest.mark.parametrize("delta,should_pass", [(0.5e-6, True), (1.5e-6, False)])
def test_weighted_block_sd_tolerance_is_preserved(tmp_path: Path, delta: float, should_pass: bool) -> None:
    candidate = tmp_path / str(should_pass)
    result, _ = write_candidate(candidate, "global")
    therm_path = candidate / "thermodynamics.json"
    therm = json.loads(therm_path.read_text(encoding="utf-8"))
    therm["thermodynamics"]["weighted_block_sd_kcal_mol"] += delta
    therm_path.write_text(json.dumps(therm) + "\n", encoding="utf-8")
    if should_pass:
        VERIFY.try_matching_modes(DATA, candidate)
    else:
        reject(candidate, "weighted_block_sd_kcal_mol")


def sensitivity_row(result: dict, *, variant: str, changed_choice: str, unit: str, value: float) -> dict:
    return {
        "variant": variant,
        "changed_choice": changed_choice,
        "parameter_unit": unit,
        "parameter_value": repr(value),
        "deltaG_kcal_mol": repr(result["deltaG_kcal"]),
        "block_sd_kcal_mol": repr(result["block_sd_kcal"]),
        "block_formal_se_kcal_mol": repr(result["block_formal_se_kcal"]),
        "frame_ess": repr(result["frame_ess"]),
        "block_ess": repr(result["block_ess"]),
    }


def test_baseline_reference_row_is_replayed_but_not_counted_as_alternative() -> None:
    baseline = VERIFY.reweight(DATA, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    alternative = VERIFY.reweight(DATA, 10000.0, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    reference_row = sensitivity_row(baseline, variant="baseline", changed_choice="reference: no changed choice", unit="ps", value=20000)
    reference_row["window_start_ps"] = "20000"
    reference_row["window_end_ps"] = repr(float(DATA["time_ps"][-1]))
    alternative_row = sensitivity_row(alternative, variant="burnin_10ns", changed_choice="burn-in", unit="ps", value=10000)

    checked = VERIFY.replay_sensitivities(DATA, [reference_row, alternative_row], baseline["method"])
    assert checked[0]["status"] == "baseline_reference"
    assert checked[1]["status"] == "supported"


def test_baseline_reference_numeric_tampering_is_rejected() -> None:
    baseline = VERIFY.reweight(DATA, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    alternative = VERIFY.reweight(DATA, 10000.0, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    reference_row = sensitivity_row(baseline, variant="baseline", changed_choice="reference", unit="ps", value=20000)
    reference_row["deltaG_kcal_mol"] = repr(baseline["deltaG_kcal"] + 0.01)
    alternative_row = sensitivity_row(alternative, variant="burnin_10ns", changed_choice="burn-in", unit="ps", value=10000)

    with pytest.raises(VERIFY.CandidateFail, match="sensitivity deltaG_kcal_mol"):
        VERIFY.replay_sensitivities(DATA, [reference_row, alternative_row], baseline["method"])


@pytest.mark.parametrize("unit,value", [("ps", 10000), ("bins", 36)])
def test_baseline_marker_with_changed_parameter_is_rejected(unit: str, value: float) -> None:
    baseline = VERIFY.reweight(DATA, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    alternative = VERIFY.reweight(DATA, 10000.0, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    reference_row = sensitivity_row(baseline, variant="baseline", changed_choice="burn-in", unit=unit, value=value)
    alternative_row = sensitivity_row(alternative, variant="burnin_10ns", changed_choice="burn-in", unit="ps", value=10000)

    with pytest.raises(VERIFY.CandidateFail, match="baseline"):
        VERIFY.replay_sensitivities(DATA, [reference_row, alternative_row], baseline["method"])


def test_reference_rows_do_not_satisfy_distinct_sensitivity_requirement() -> None:
    baseline = VERIFY.reweight(DATA, edge="floor", block_weight_scope="histogram", block_origin="burn_time")
    reference = sensitivity_row(baseline, variant="baseline", changed_choice="reference", unit="bins", value=72)

    with pytest.raises(VERIFY.CandidateFail, match="no distinct sensitivity alternative"):
        VERIFY.replay_sensitivities(DATA, [reference], baseline["method"])
