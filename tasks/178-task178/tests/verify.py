#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Assess structural and dynamical claims.
"""Score the integrated nanochain claim against author observables."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

def thermal_energy() -> float:
    return load_refs()["criteria"]["temperature_K"] * 8.314462618 / 1000.0 / 4.184


def emit(status: str, checks: list[dict], code: int) -> int:
    print(json.dumps({"overall": status, "checks": checks}, ensure_ascii=False, indent=2))
    return code


def num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def asset_directory() -> Path:
    app_assets = Path(os.environ.get("APP", "/app")) / "environment" / "assets"
    if app_assets.is_dir():
        return app_assets
    return Path(__file__).resolve().parents[1] / "environment" / "assets"


def mean_percent(path: Path) -> float:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        values.append(float(line.split()[1]))
    return float(np.mean(values))


def mode_cn(path: Path, column: int = 1) -> int:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            rows.append([float(part) for part in line.split()])
    table = np.asarray(rows)
    return int(table[np.argmax(table[:, column]), 0])


def final_msd(path: Path) -> float:
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        last = line
    return float(last.split(";")[1]) / 10000.0


def vhcf_means(path: Path) -> tuple[float, float]:
    criteria = load_refs()["criteria"]
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append([float(part) for part in line.replace(";", " ").split()])
    matrix = np.asarray(rows)
    r = (np.arange(matrix.shape[1]) * criteria["vhcf_radius_step_pm"] + criteria["vhcf_radius_offset_pm"]) / 100.0
    t = np.arange(matrix.shape[0]) * criteria["vhcf_time_step_ps"] + criteria["vhcf_time_offset_ps"]
    small = r < criteria["vhcf_small_r_A"]
    early = float(matrix[t < criteria["vhcf_early_before_ps"]][:, small].mean())
    late = float(matrix[t > criteria["vhcf_late_after_ps"]][:, small].mean())
    return early, late


def non_gaussian_peak(path: Path) -> float:
    criteria = load_refs()["criteria"]
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            values.append([float(part) for part in line.replace(";", " ").split()])
    table = np.asarray(values)
    time_ps = table[:, 0] / 1000.0
    return float(np.max(table[(time_ps >= criteria["nongaussian_time_range_ps"][0]) & (time_ps <= criteria["nongaussian_time_range_ps"][1]), 1]))


def graph_claims(path: Path, li_cut: float | None = None, o_cut: float | None = None) -> tuple[bool, bool]:
    """Rebuild the final-frame PBC Li graph and classify shared oxygen bridges."""
    criteria = load_refs()["criteria"]
    li_cut = criteria["li_li_cutoff_A"] if li_cut is None else li_cut
    o_cut = criteria["li_o_cutoff_A"] if o_cut is None else o_cut
    lines = path.read_text(encoding="utf-8").splitlines()
    elems, coords = [], []
    for line in lines[2:]:
        parts = line.split()
        if len(parts) >= 4:
            elems.append(parts[0])
            coords.append([float(value) for value in parts[1:4]])
    elems, xyz = np.asarray(elems), np.asarray(coords)
    box = np.asarray([float(value) for value in lines[1].split()[2:5]])
    li = np.where(elems == "Li")[0]
    oxygen = np.where(elems == "O")[0]
    hydrogen = np.where(elems == "H")[0]

    def pbc(delta: np.ndarray) -> np.ndarray:
        return delta - box * np.round(delta / box)

    water = set()
    for oi in oxygen:
        if np.any(np.linalg.norm(pbc(xyz[hydrogen] - xyz[oi]), axis=1) < criteria["water_OH_cutoff_A"]):
            water.add(int(oi))
    shell_o = []
    for li_i in li:
        distances = np.linalg.norm(pbc(xyz[oxygen] - xyz[li_i]), axis=1)
        shell_o.append(set(int(oxygen[j]) for j in np.where(distances <= o_cut)[0]))

    adjacency = [set() for _ in li]
    shared_water = False
    for i in range(len(li)):
        distances = np.linalg.norm(pbc(xyz[li[i + 1:]] - xyz[li[i]]), axis=1)
        for offset in np.where(distances <= li_cut)[0]:
            j = i + 1 + int(offset)
            adjacency[i].add(j)
            adjacency[j].add(i)
            shared_water |= bool((shell_o[i] & shell_o[j]) & water)

    seen, largest = set(), 0
    for i in range(len(li)):
        if i in seen:
            continue
        stack, size = [i], 0
        seen.add(i)
        while stack:
            node = stack.pop()
            size += 1
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        largest = max(largest, size)
    return largest >= criteria["chain_component_min"], shared_water


def barrier(path: Path) -> float:
    criteria = load_refs()["criteria"]
    r, g = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        a, b = line.split(";")[:2]
        r.append(float(a) / 100.0)
        g.append(float(b))
    r, g = np.asarray(r), np.asarray(g)
    ok = g > criteria["positive_g_min"]
    free = np.full_like(g, np.nan)
    free[ok] = -np.log(g[ok]) * thermal_energy()
    well = (r > criteria["well_window_A"][0]) & (r < criteria["well_window_A"][1]) & ok
    saddle = (r > criteria["saddle_window_A"][0]) & (r < criteria["saddle_window_A"][1]) & ok
    return float(np.nanmax(free[saddle]) - np.nanmin(free[well]))


def contact_peak(path: Path) -> float:
    criteria = load_refs()["criteria"]
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        distance, value = line.replace(";", " ").split()[:2]
        rows.append([float(distance) / 100.0, float(value)])
    values = np.asarray(rows)
    selected = (values[:, 0] > criteria["peak_window_A"][0]) & (values[:, 0] < criteria["peak_window_A"][1])
    return float(values[np.where(selected)[0][np.argmax(values[selected, 1])], 0])



def valid_limits(value) -> bool:
    criteria = load_refs()["criteria"]
    return (
        isinstance(value, list)
        and len(value) >= criteria["minimum_limits"]
        and all(isinstance(item, str) and item in criteria["limits"] for item in value)
        and len(set(value)) >= criteria["minimum_limits"]
    )


def xray_agrees(assets: Path) -> bool:
    criteria = load_refs()["criteria"]
    def read(path: Path, scale: float) -> np.ndarray:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.replace(";", " ").split()
            rows.append([float(parts[0]) * scale, float(parts[1])])
        values = np.asarray(rows)
        order = np.argsort(values[:, 0], kind="stable")
        values = values[order]
        unique_q, inverse = np.unique(values[:, 0], return_inverse=True)
        mean_y = np.bincount(inverse, weights=values[:, 1]) / np.bincount(inverse)
        return np.column_stack((unique_q, mean_y))

    experiment = read(assets / "saxs_experiment.dat", criteria["xray_experiment_q_scale"])
    calculation = read(assets / "sfac_xray_calc.csv", criteria["xray_calculation_q_scale"])
    q = np.linspace(*criteria["xray_q_range_Ainv"], int(criteria["xray_grid_samples"]))
    exp_y = np.interp(q, experiment[:, 0], experiment[:, 1])
    calc_y = np.interp(q, calculation[:, 0], calculation[:, 1])
    best_shift = float(np.mean(calc_y - exp_y))
    residual = float(np.sqrt(np.mean((exp_y + best_shift - calc_y) ** 2)))
    return residual <= criteria["xray_agreement_rmse"]


def mobility_ok(order, expected_order: list[str]) -> bool:
    if not isinstance(order, list) or len(order) != 3:
        return False
    aliases = {"h2o": "H2O", "water": "H2O", "w": "H2O", "li": "Li", "lithium": "Li",
               "tfsi": "TFSI", "anion": "TFSI", "c2f6no4s2": "TFSI"}
    normalized = [aliases.get(str(item).strip().lower()) for item in order]
    return normalized == expected_order


def lithium_specific_heterogeneity(species_peaks: dict[str, float]) -> bool:
    criteria = load_refs()["criteria"]
    return species_peaks["Li"] > criteria["heterogeneity_peak"] and all(
        species_peaks[key] <= criteria["heterogeneity_peak"] for key in ("H2O", "TFSI")
    )


def load_refs() -> dict:
    """Require the private references and every pinned scientific input."""
    import hashlib
    import math
    import re
    from pathlib import PurePosixPath

    tests = Path(os.environ.get("TESTS", Path(__file__).resolve().parent)).resolve()
    path = tests / "refs.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("refs.json missing or unsafe")
    refs = json.loads(path.read_text(encoding="utf-8"))
    schema = {'output': 'str', 'assets': [{'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}, {'path': 'str', 'sha256': 'str'}], 'gold': {'nanochains_with_short_contacts': 'bool', 'contact_distance_A': 'number', 'contact_series': 'str', 'contact_fraction_percent': 'number', 'contact_population_is_majority': 'bool', 'barrier_comparable_to_kT': 'bool', 'transient_exchange': 'bool', 'contacts_share_water': 'bool', 'contact_cn_higher_than_isolated': 'bool', 'xray_s_agrees': 'bool', 'xray_s_proves_short_chains': 'bool', 'msd_final_A2': {'Li': 'number', 'H2O': 'number', 'TFSI': 'number'}, 'diffusion_coefficients_quantitatively_reportable': 'bool', 'apparent_mobility_order': ['str', 'str', 'str'], 'dynamic_heterogeneity_specific_to_lithium': 'bool', 'vhcf_small_r_mean_before_5ps': 'number', 'vhcf_small_r_mean_after_20ps': 'number', 'limits': ['str', 'str']}, 'tolerances': {'msd_relative': 'number', 'contact_distance_A': 'number', 'contact_percent': 'number', 'vhcf_early': 'number', 'vhcf_late': 'number'}, 'criteria': {'temperature_K': 'number', 'vhcf_radius_step_pm': 'number', 'vhcf_radius_offset_pm': 'number', 'vhcf_time_step_ps': 'number', 'vhcf_time_offset_ps': 'number', 'vhcf_small_r_A': 'number', 'vhcf_early_before_ps': 'number', 'vhcf_late_after_ps': 'number', 'nongaussian_time_range_ps': ['number', 'number'], 'li_li_cutoff_A': 'number', 'li_o_cutoff_A': 'number', 'water_OH_cutoff_A': 'number', 'chain_component_min': 'number', 'positive_g_min': 'number', 'well_window_A': ['number', 'number'], 'saddle_window_A': ['number', 'number'], 'peak_window_A': ['number', 'number'], 'limits': ['str', 'str', 'str', 'str'], 'minimum_limits': 'number', 'xray_q_range_Ainv': ['number', 'number'], 'xray_grid_samples': 'number', 'xray_calculation_q_scale': 'number', 'xray_experiment_q_scale': 'number', 'xray_agreement_rmse': 'number', 'heterogeneity_peak': 'number', 'contact_series': 'str', 'barrier_kT_range': ['number', 'number'], 'majority_percent': 'number'}}

    def validate(value, expected):
        if isinstance(expected, dict):
            if not isinstance(value, dict) or set(value) != set(expected):
                raise ValueError("refs.json keys are missing or malformed")
            for key in expected:
                validate(value[key], expected[key])
        elif isinstance(expected, list):
            if not isinstance(value, list) or len(value) != len(expected):
                raise ValueError("refs.json array is malformed")
            for item, entry in zip(value, expected):
                validate(item, entry)
        elif expected == "number":
            if not num(value) or not math.isfinite(value):
                raise ValueError("refs.json number is invalid")
        elif expected == "bool":
            if not isinstance(value, bool):
                raise ValueError("refs.json boolean is invalid")
        elif not isinstance(value, str) or not value:
            raise ValueError("refs.json string is invalid")

    validate(refs, schema)

    def validate_bounds(value):
        if isinstance(value, dict):
            for item in value.values():
                validate_bounds(item)
        elif isinstance(value, list):
            if len(value) == 2 and all(num(item) for item in value) and value[0] > value[1]:
                raise ValueError("reference bounds are reversed")
            for item in value:
                validate_bounds(item)
        elif num(value) and value < 0:
            raise ValueError("negative reference tolerance or criterion")

    validate_bounds(refs["tolerances"])
    validate_bounds(refs["criteria"])
    output = PurePosixPath(refs["output"])
    if len(output.parts) != 1 or output.name in (".", ".."):
        raise ValueError("unsafe output name")
    app = asset_directory().parents[1]
    seen = set()
    for item in refs["assets"]:
        rel, expected = item["path"], item["sha256"]
        path = PurePosixPath(rel)
        if (path.is_absolute() or ".." in path.parts
                or path.parts[:2] != ("environment", "assets")
                or rel in seen or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
            raise ValueError("invalid asset reference")
        seen.add(rel)
        target = app.joinpath(*path.parts)
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"asset missing or unsafe: {rel}")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f"asset hash mismatch: {rel}")
    return refs


def main(argv: list[str]) -> int:
    try:
        refs = load_refs()
    except Exception as exc:
        return emit("ENV_INVALID", [{"criterion": "references", "passed": False, "detail": str(exc)}], 2)
    gold, tol, criteria = refs["gold"], refs["tolerances"], refs["criteria"]
    final = Path(argv[1]).resolve() if len(argv) > 1 else Path("/app/final")
    assets = asset_directory()
    required = [
        "populations/pop_a.dat", "populations/pop_b.dat", "populations/pop_c.dat",
        "li_li_rdf_this_work.csv", "window_blue.dat", "window_red.dat",
        "frame_late.xyz", "msd_Li_#2.csv",
        "msd_H2O_#2.csv", "msd_C2F6NO4S2_#2.csv", "vhcf_li_li.csv",
        "nongaussian_Li.dat", "nongaussian_Ow.dat", "nongaussian_N_ani.dat",
        "saxs_experiment.dat", "sfac_xray_calc.csv",
    ]
    if any(not (assets / rel).is_file() for rel in required):
        return emit("ENVIRONMENT_ERROR", [{"criterion": "assets", "passed": False, "detail": "claim assets missing"}], 2)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"criterion": name, "passed": ok, "detail": detail})

    path = final / refs["output"]
    if not path.is_file():
        add("claim_file_present", False, "missing claim.json")
        return emit("FAIL", checks, 1)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        add("claim_file_present", False, str(exc))
        return emit("FAIL", checks, 1)
    add("claim_file_present", True, "parsed")

    population_means = {
        key: mean_percent(assets / "populations" / f"{key}.dat")
        for key in ("pop_a", "pop_b", "pop_c")
    }
    contact_mean = population_means["pop_b"]
    main_contact_peak = contact_peak(assets / "li_li_rdf_this_work.csv")
    msd = {
        "Li": final_msd(assets / "msd_Li_#2.csv"),
        "H2O": final_msd(assets / "msd_H2O_#2.csv"),
        "TFSI": final_msd(assets / "msd_C2F6NO4S2_#2.csv"),
    }
    early_g, late_g = vhcf_means(assets / "vhcf_li_li.csv")
    species_peaks = {
        "Li": non_gaussian_peak(assets / "nongaussian_Li.dat"),
        "H2O": non_gaussian_peak(assets / "nongaussian_Ow.dat"),
        "TFSI": non_gaussian_peak(assets / "nongaussian_N_ani.dat"),
    }
    order = sorted(msd, key=msd.get, reverse=True)
    contact_graph, water_bridge = graph_claims(assets / "frame_late.xyz")
    contact_mode = mode_cn(assets / "window_blue.dat")
    isolated_mode = mode_cn(assets / "window_red.dat")
    reported_msd = doc.get("msd_final_A2")
    msd_ok = isinstance(reported_msd, dict) and all(
        num(reported_msd.get(key)) and abs(float(reported_msd[key]) - value) / value <= tol["msd_relative"]
        for key, value in msd.items()
    )
    consistent = (
        num(doc.get("contact_distance_A")) and abs(float(doc["contact_distance_A"]) - main_contact_peak) <= tol["contact_distance_A"]
        and doc.get("contact_series") == criteria["contact_series"]
        and num(doc.get("contact_fraction_percent"))
        and abs(float(doc["contact_fraction_percent"]) - contact_mean) <= tol["contact_percent"]
        and msd_ok
        and num(doc.get("vhcf_small_r_mean_before_5ps"))
        and abs(float(doc["vhcf_small_r_mean_before_5ps"]) - early_g) <= tol["vhcf_early"]
        and num(doc.get("vhcf_small_r_mean_after_20ps"))
        and abs(float(doc["vhcf_small_r_mean_after_20ps"]) - late_g) <= tol["vhcf_late"]
    )
    add("cross_observable_consistency", consistent,
        f"contact mean {contact_mean:.2f}%, MSD {msd}, van Hove {early_g:.3f} -> {late_g:.3f}")

    height = barrier(assets / "li_li_rdf_this_work.csv")
    limits = doc.get("limits")
    barrier_comparable = criteria["barrier_kT_range"][0] <= height / thermal_energy() <= criteria["barrier_kT_range"][1]
    heterogeneity_specific = lithium_specific_heterogeneity(species_peaks)
    claim_ok = (
        consistent
        and doc.get("nanochains_with_short_contacts") is contact_graph
        and doc.get("contact_population_is_majority") is (contact_mean > criteria["majority_percent"])
        and doc.get("barrier_comparable_to_kT") is barrier_comparable
        and doc.get("transient_exchange") is (late_g > early_g)
        and doc.get("contacts_share_water") is water_bridge
        and doc.get("contact_cn_higher_than_isolated") is (contact_mode > isolated_mode)
        and doc.get("xray_s_agrees") is xray_agrees(assets)
        and doc.get("xray_s_proves_short_chains") is False
        and doc.get("diffusion_coefficients_quantitatively_reportable") is False
        and mobility_ok(doc.get("apparent_mobility_order"), order)
        and doc.get("dynamic_heterogeneity_specific_to_lithium") is heterogeneity_specific
        and valid_limits(limits)
    )
    add("nanochain_claim_and_limits", claim_ok,
        f"I-II barrier {height:.3f} kcal/mol ({height / thermal_energy():.2f} kT); "
        f"late-frame max Li component {contact_graph}; shared water bridge {water_bridge}; "
        f"contact/isolated CN modes {contact_mode}/{isolated_mode}; alpha2 peaks {species_peaks}")
    add("population_matches_author_window", consistent and doc.get("contact_population_is_majority") is (contact_mean > criteria["majority_percent"]),
        f"Figure 3 series 5 means a/b/c = {population_means['pop_a']:.2f}/{contact_mean:.2f}/{population_means['pop_c']:.2f}% "
        f"(sum {sum(population_means.values()):.4f}%; reported separately without normalization)")
    passed = all(item["passed"] for item in checks)
    return emit("PASS" if passed else "FAIL", checks, 0 if passed else 1)



def harbor_main() -> int:
    """Validate mounted inputs and translate the scientific verifier into Harbor reward protocol."""
    import json
    import os
    import subprocess
    from pathlib import Path

    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", Path(__file__).resolve().parent)).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    report_path = logs / "verification.json"
    reward_path = logs / "reward.txt"

    def report(status: str, **extra: object) -> int:
        report_path.write_text(
            json.dumps({"status": status, **extra}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"status": status, **extra}, ensure_ascii=False))
        return 2

    try:
        load_refs()

        verifier = Path(__file__).resolve()
        result = subprocess.run(
            [sys.executable, str(verifier), str(app / "final")],
            capture_output=True, text=True, check=False,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return report("ENV_INVALID", error=f"verifier emitted invalid JSON (rc={result.returncode})")
        status = payload.get("overall") if isinstance(payload, dict) else None
        checks = payload.get("checks") if isinstance(payload, dict) else None
        if (not isinstance(checks, list) or not checks
                or any(not isinstance(check, dict) or not isinstance(check.get("passed"), bool)
                       for check in checks)):
            return report("ENV_INVALID", error="verifier output has no valid checks array")
        checks_passed = all(check["passed"] for check in checks)
        if status == "ENVIRONMENT_ERROR" or result.returncode == 2:
            return report("ENV_INVALID", checks=checks, error="scientific verifier reported unavailable/broken evaluation inputs")
        if status == "PASS" and result.returncode == 0 and checks_passed:
            reward = 1
        elif status == "FAIL" and result.returncode == 1 and not checks_passed:
            reward = 0
        else:
            return report("ENV_INVALID", checks=checks, error=f"verifier status/exit mismatch: {status!r}/{result.returncode}")
        reward_path.write_text(f"{reward}\n", encoding="utf-8")
        report_path.write_text(
            json.dumps({"status": status, "reward": reward, "checks": checks},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        return report("ENV_INVALID", error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--harbor"]:
        raise SystemExit(harbor_main())
    sys.exit(main(sys.argv))
