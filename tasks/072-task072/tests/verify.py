# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Analyse residue-correlation and distance matrices with consistent residue numbering.
from __future__ import annotations

import argparse
import base64
import ctypes
import csv
import hashlib
import io
import json
import math
import os
import re
import resource
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np


from typing import Any


class CandidateFail(ValueError):
    pass


class EnvironmentInvalid(RuntimeError):
    pass


INPUT_SHA256 = {
    "README_residue_numbering": "a1488c55ef353c6ae82a2f9d77c35a6dfc9929ac70a65081f098acb4156ea230",
    "corrmat_c0_WT.dat": "be3202d7235606d7e212b6baac5a26bc26a38c2c9a809a359f054bac28cf7bb0",
    "distmat_c0_WT.dat": "63d6042457f7fcc811fd24fb0cb2a2ac18185cc85bfdb28ed3831b42e6be2686",
    "corrmat_c0_V72I.dat": "881b191e61b3807565c83125ddcbb9d03840a855885582d3a732318128c3cd05",
    "distmat_c0_V72I.dat": "3f0f76ec7bb044b55783151835833341b2ca3d418cb1d9e388862cffc62a8b65",
}
REFERENCE_SHA256 = "ebca88b5264fda929e1e2fb3e6fa589698c02b51851c1b3735079ab8ddc114e2"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scientific_reference() -> dict[str, Any]:
    path = Path(__file__).with_name("refs.json")
    if path.is_symlink() or not path.is_file() or sha256_file(path) != REFERENCE_SHA256:
        raise EnvironmentInvalid("frozen evaluator scientific-reference basis is missing, redirected, or changed")
    try:
        basis = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"frozen evaluator scientific-reference basis cannot be parsed: {exc}") from exc
    if not isinstance(basis, dict) or basis.get("schema_version") != "spm-allostery-reference/v1":
        raise EnvironmentInvalid("frozen evaluator scientific-reference basis has an unsupported schema")
    if basis.get("public_input_sha256") != INPUT_SHA256:
        raise EnvironmentInvalid("frozen evaluator basis is pinned to different public input bytes")
    numbering = basis.get("numbering", {})
    if numbering.get("matrix_index_origin") != 0 or numbering.get("mature_residue_equals_matrix_index") is not True:
        raise EnvironmentInvalid("frozen evaluator basis does not establish the corrected zero-based numbering")
    if basis.get("author_output_basis", {}).get("wt_display_edges") != 32 or basis["author_output_basis"].get("v72i_display_edges") != 25:
        raise EnvironmentInvalid("frozen author SPM basis is incomplete or inconsistent")
    challenge = basis.get("calibrated_input_challenge", {})
    if challenge.get("manifest_sha256") != "cec9564acbe23c59ff424fb32c6cf5348cfceeb4bf74317ea364b743d2459779" or challenge.get("changed_file_sha256") != "6d1bd9056a29e659d5195edcb501e76920b9c8a9d7aa5ebd468898652278a0f9":
        raise EnvironmentInvalid("frozen evaluator input-challenge basis is incomplete or inconsistent")
    return basis


def public_root(path: str, expected: dict[str, str]) -> dict[str, Path]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise EnvironmentInvalid("public input root is absent or redirected")
    result: dict[str, Path] = {}
    for name, digest in expected.items():
        file = root / name
        if file.is_symlink() or not file.is_file():
            raise EnvironmentInvalid(f"required public input is absent or redirected: {name}")
        if sha256_file(file) != digest:
            raise EnvironmentInvalid(f"public input SHA-256 mismatch: {name}")
        result[name] = file
    return result


def real_output_dir(app: str) -> Path:
    root = Path(app)
    final = root / "final"
    if root.is_symlink() or not root.is_dir() or final.is_symlink() or not final.is_dir():
        raise CandidateFail("APP/final must be a real directory")
    return final


def require_files(final: Path, names: tuple[str, ...]) -> dict[str, Path]:
    result = {}
    for name in names:
        path = final / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise CandidateFail(f"required final deliverable is missing, empty, or redirected: {name}")
        result[name] = path
    return result


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
                raise CandidateFail(f"{path.name} is missing required columns: {sorted(required)}")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not rows:
        raise CandidateFail(f"{path.name} has no data rows")
    return rows


def finite_number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateFail(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise CandidateFail(f"{label} must be finite")
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateFail(f"{path.name} must contain a JSON object")
    return value


def emit(logs: str, case_id: str, status: str, message: str, details: dict[str, Any] | None = None) -> int:
    root = Path(logs)
    root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"case_id": case_id, "status": status, "message": message}
    if details:
        report["details"] = details
    if status in {"PASS", "FAIL"}:
        report["reward"] = 1.0 if status == "PASS" else 0.0
        (root / "reward.txt").write_text(f"{report['reward']:g}\n", encoding="ascii")
    else:
        (root / "reward.txt").unlink(missing_ok=True)
    (root / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return {"PASS": 0, "REVIEW_REQUIRED": 0, "FAIL": 1, "ENV_INVALID": 2}.get(status, 2)



def _validate_beta13_interpretation(value, wt_count: int, mut_count: int) -> None:
    """Check that a submitted category matches independently counted edges."""
    if not isinstance(value, str):
        raise CandidateFail("β13 interpretation must be a string category")
    expected = ("display_usage_decreased" if mut_count < wt_count else
                "display_usage_increased" if mut_count > wt_count else
                "display_usage_unchanged")
    # Preserve the legacy reference label only where its meaning is accurate.
    if value == "wt_display_branch_lost_or_weakened_in_v72i":
        if mut_count < wt_count:
            return
        raise CandidateFail("legacy β13 interpretation does not match the independently counted edge usage")
    if value not in {"display_usage_decreased", "display_usage_increased", "display_usage_unchanged"}:
        raise CandidateFail("β13 interpretation must use a supported display-usage category")
    if value != expected:
        raise CandidateFail("β13 interpretation does not match the independently counted edge usage")

"""Independent reference graph and weighted all-pairs edge usage for case 03."""

import heapq

import networkx as nx


def graph_from_matrices(corr: np.ndarray, dist: np.ndarray, cutoff: float, floor: float):
    n = corr.shape[0]
    adjacency = [[] for _ in range(n)]
    edges = {}
    for i in range(n):
        for j in range(i + 1, n):
            if dist[i, j] <= cutoff:
                length = -math.log(max(abs(float(corr[i, j])), floor))
                if not math.isfinite(length) or length <= 0:
                    raise ValueError("reference graph contains a non-positive or non-finite edge length")
                adjacency[i].append((j, length))
                adjacency[j].append((i, length))
                edges[(i, j)] = length
    return adjacency, edges


def all_pairs_edge_usage(adjacency):
    """Weighted Brandes edge betweenness, equal-splitting all shortest path ties."""
    usage = {}
    n = len(adjacency)
    for source in range(n):
        stack = []
        pred = [[] for _ in range(n)]
        sigma = [0.0] * n
        sigma[source] = 1.0
        distance = [math.inf] * n
        distance[source] = 0.0
        queue = [(0.0, source)]
        while queue:
            dv, v = heapq.heappop(queue)
            if dv > distance[v] + 1e-12:
                continue
            stack.append(v)
            for w, length in adjacency[v]:
                candidate = dv + length
                if candidate < distance[w] - 1e-12:
                    distance[w] = candidate
                    heapq.heappush(queue, (candidate, w))
                    sigma[w] = sigma[v]
                    pred[w] = [v]
                elif abs(candidate - distance[w]) <= 1e-12:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        dependency = [0.0] * n
        while stack:
            w = stack.pop()
            if sigma[w]:
                for v in pred[w]:
                    contribution = (sigma[v] / sigma[w]) * (1.0 + dependency[w])
                    pair = (v, w) if v < w else (w, v)
                    usage[pair] = usage.get(pair, 0.0) + contribution
                    dependency[v] += contribution
    # Every undirected edge/path is counted from both endpoint orientations.
    return {edge: value / 2.0 for edge, value in usage.items()}


def normalized_edge_usage(adjacency):
    graph = nx.Graph()
    graph.add_nodes_from(range(len(adjacency)))
    for i, neighbors in enumerate(adjacency):
        for j, length in neighbors:
            if i < j:
                graph.add_edge(i, j, length=length)
    # Rebuild edge usage from the independently assembled full matrix graph.
    raw_nx = nx.edge_betweenness_centrality(graph, normalized=False, weight="length")
    raw = {tuple(sorted(edge)): float(value) for edge, value in raw_nx.items()}
    maximum = max(raw.values(), default=0.0)
    if maximum <= 0:
        raise ValueError("reference graph has no positive edge usage")
    return {edge: value / maximum for edge, value in raw.items()}


def shortest_path_to_apical(adjacency, source=517):
    """Return one deterministic shortest path from source to matrix index 189..373."""
    n = len(adjacency)
    distance = [math.inf] * n
    previous = [-1] * n
    distance[source] = 0.0
    queue = [(0.0, source)]
    targets = set(range(189, 374))
    while queue:
        dv, v = heapq.heappop(queue)
        if dv > distance[v] + 1e-12:
            continue
        if v in targets:
            path = [v]
            while path[-1] != source:
                path.append(previous[path[-1]])
            return list(reversed(path)), dv
        for w, length in adjacency[v]:
            candidate = dv + length
            if candidate < distance[w] - 1e-12:
                distance[w] = candidate
                previous[w] = v
                heapq.heappush(queue, (candidate, w))
    raise ValueError("mature residue 517 cannot reach the apical region in the full contact graph")


CASE = "case-03-spm-allostery"
REPLAY_TIMEOUT_SECONDS = 30
REPLAY_CPU_SECONDS = 30
REPLAY_MAX_FILE_BYTES = 64 * 1024 * 1024
REPLAY_MAX_PROCESSES = 16
REPLAY_MAX_ADDRESS_SPACE = 3 * 1024 * 1024 * 1024
REPLAY_TMPFS_MAX_BYTES = 512 * 1024 * 1024
REPLAY_STREAM_CHARS = 4000
REPLAY_STREAM_MAX_BYTES = 1024 * 1024


def _json_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CandidateFail(f"{label} must be a finite JSON number")
    return float(value)



def run(app: str, assets: str, logs: str, challenge_manifest: str | None = None, baseline_assets: str | None = None) -> int:
    try:
        reference = scientific_reference()
        challenge_path = None
        if challenge_manifest is None:
            inputs = public_root(assets, INPUT_SHA256)
        else:
            if baseline_assets is None:
                raise EnvironmentInvalid("input-challenge mode requires the evaluator's original baseline inputs")
            baseline = public_root(baseline_assets, INPUT_SHA256)
            inputs, challenge_path = _challenge_inputs(assets, challenge_manifest, baseline, reference)
        matrices: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for tag in ("WT", "V72I"):
            corr = np.loadtxt(inputs[f"corrmat_c0_{tag}.dat"])
            dist = np.loadtxt(inputs[f"distmat_c0_{tag}.dat"])
            if corr.shape != (526, 526) or dist.shape != (526, 526) or not np.isfinite(corr).all() or not np.isfinite(dist).all():
                raise EnvironmentInvalid(f"{tag} public matrices do not match the pinned finite 526x526 contract")
            if not np.allclose(corr, corr.T, atol=1e-8) or not np.allclose(dist, dist.T, atol=1e-8):
                raise EnvironmentInvalid(f"{tag} public matrices are not symmetric within the frozen tolerance")
            matrices[tag] = (corr, dist)

        final = real_output_dir(app)
        out = require_files(final, ("spm_WT.csv", "spm_V72I.csv", "analysis.py", "report.md", "findings.json"))
        try:
            report = out["report.md"].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CandidateFail(f"report.md must be valid UTF-8 text: {exc}") from exc
        if not report.strip():
            raise CandidateFail("report.md must explain the network construction and path comparison")
        findings = _read_findings(out["findings.json"])
        method = findings["method"]
        cutoff = method["contact_cutoff_angstrom"]
        # Prose has no fixed template. Check a numeric declaration if the
        # report explicitly uses this recognizable scientific method label.
        for match in re.finditer(r"contact[_ ]cutoff[_ ]angstrom\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", report, re.I):
            if float(match.group(1)) != cutoff:
                raise CandidateFail("report.md contact cutoff disagrees with structured findings.json")
        if cutoff not in (6.0,):
            raise CandidateFail("this independently calibrated reference supports contact_cutoff_angstrom 6.0 only")
        if method["correlation_to_length"] != "negative_log_abs_floor" or method["correlation_floor"] != 1e-12:
            raise CandidateFail("this independently calibrated reference supports -log(max(abs(correlation), 1e-12)) only")
        if method["graph"] != "undirected" or method["shortest_path_policy"] != "equal_split_all_pairs" or method["usage_normalization"] != "maximum_edge_usage":
            raise CandidateFail("unsupported graph, shortest-path tie, or normalization method")
        threshold = method["display_threshold"]
        if threshold not in (0.30, 0.35):
            raise CandidateFail("display_threshold must be one of the calibrated values 0.30 or 0.35")
        checked = {}
        submitted = {}
        for tag, filename in (("WT", "spm_WT.csv"), ("V72I", "spm_V72I.csv")):
            submitted[tag] = _read_graph(out[filename], tag, matrices[tag][1], cutoff)
            checked[tag] = len(submitted[tag])
        expected = {}
        path_evidence = {}
        independent_compute_wall = {}
        for tag in ("WT", "V72I"):
            science_started = time.monotonic()
            corr, dist = matrices[tag]
            try:
                adjacency, _ = graph_from_matrices(corr, dist, cutoff, method["correlation_floor"])
                usage = normalized_edge_usage(adjacency)
                expected[tag] = {edge: value for edge, value in usage.items() if value > threshold - 1e-12}
                path_evidence[tag] = shortest_path_to_apical(adjacency, 517)
                independent_compute_wall[tag] = round(time.monotonic() - science_started, 3)
            except (ValueError, OverflowError) as exc:
                raise EnvironmentInvalid(f"independent {tag} graph calculation failed: {exc}") from exc
            if expected[tag].keys() != submitted[tag].keys():
                raise CandidateFail(f"{tag} selected SPM edge set is incomplete or contains an unsupported edge")
            for edge, value in expected[tag].items():
                if abs(value - submitted[tag][edge]) > 1e-7:
                    raise CandidateFail(f"{tag} normalized all-pairs edge usage is incorrect for mature pair {edge}")
        _validate_findings_science(findings, expected, path_evidence, matrices, reference)
        replay = _replay_analysis(out["analysis.py"], inputs, challenge_path, threshold)
        for tag in ("WT", "V72I"):
            name = f"spm_{tag}.csv"
            regenerated = _read_graph_data(replay["outputs"][name], name, matrices[tag][1], cutoff)
            if submitted[tag].keys() != regenerated.keys():
                raise CandidateFail(f"analysis.py replay changed the {tag} edge set")
            for pair, value in submitted[tag].items():
                if abs(value - regenerated[pair]) > 1e-10:
                    raise CandidateFail(f"analysis.py replay changed the {tag} weight for matrix pair {pair}")
        challenge_replay = None
        if challenge_path is None:
            with tempfile.TemporaryDirectory(prefix="ccb-case03-input-challenge-") as temp_name:
                challenge_inputs, authorized_manifest = _build_automatic_challenge(inputs, reference, Path(temp_name))
                challenge_replay = _score_challenge_replay(out["analysis.py"], challenge_inputs, authorized_manifest,
                                                           cutoff, method["correlation_floor"], threshold)
            if challenge_replay["status"] == "REVIEW_REQUIRED":
                return emit(logs, CASE, "REVIEW_REQUIRED",
                            "baseline graph is correct, but the candidate analysis does not establish input dependence under the evaluator-authorized contact challenge",
                            {"candidate_replay": replay["receipt"], "challenge_replay": challenge_replay,
                             "input_challenge": "unsupported; no reward"})
        else:
            # An explicitly requested evaluator challenge was already independently scored above.
            challenge_replay = {"input_challenge": True, "challenge_manifest_sha256": sha256_file(challenge_path),
                                "independent_replay": "explicit challenge outputs checked against its input matrices"}
        return emit(logs, CASE, "PASS",
                    "independent full-contact-graph Brandes calculation, structured scientific claims, baseline replay, and authorized input challenge all agree",
                    {"edge_rows": checked, "matrix_index_mapping": "matrix_index = mature_residue", "contact_cutoff_angstrom": cutoff,
                     "display_threshold": threshold, "beta13_display_edges": {tag: sum(375 <= a <= 380 and 375 <= b <= 380 for a, b in expected[tag]) for tag in expected},
                     "candidate_analysis_executed": True, "input_challenge": "PASS",
                     "explicit_input_challenge": challenge_path is not None,
                     "independent_grader_wall_seconds_by_variant": independent_compute_wall,
                     "candidate_replay": replay["receipt"], "challenge_replay": challenge_replay})
    except EnvironmentInvalid as exc:
        return emit(logs, CASE, "ENV_INVALID", str(exc))
    except CandidateFail as exc:
        return emit(logs, CASE, "FAIL", str(exc))
    except Exception as exc:
        return emit(logs, CASE, "ENV_INVALID", f"verifier could not establish a safe complete result: {type(exc).__name__}: {exc}")


def _challenge_inputs(assets: str, manifest_name: str, baseline: dict[str, Path], reference: dict) -> tuple[dict[str, Path], Path]:
    manifest = Path(manifest_name)
    challenge_basis = reference["calibrated_input_challenge"]
    if manifest.is_symlink() or not manifest.is_file() or sha256_file(manifest) != challenge_basis["manifest_sha256"]:
        raise EnvironmentInvalid("input challenge manifest is absent, changed, or not evaluator-authorized")
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"input challenge manifest cannot be parsed: {exc}") from exc
    if not isinstance(record, dict) or set(record) != {"schema_version", "base_input_sha256", "challenge_input_sha256", "mutation"}:
        raise EnvironmentInvalid("input challenge manifest has an unsupported schema")
    if record["schema_version"] != "spm-input-challenge/v1" or record["base_input_sha256"] != INPUT_SHA256:
        raise EnvironmentInvalid("input challenge does not name the pinned baseline data")
    root = Path(assets)
    if root.is_symlink() or not root.is_dir():
        raise EnvironmentInvalid("challenge input root is absent or redirected")
    inputs = {}
    for name, digest in record["challenge_input_sha256"].items():
        if name not in INPUT_SHA256 or not isinstance(digest, str):
            raise EnvironmentInvalid("challenge manifest names an unknown public input")
    if set(record["challenge_input_sha256"]) != set(INPUT_SHA256):
        raise EnvironmentInvalid("challenge manifest does not cover the complete input set")
    for name in INPUT_SHA256:
        path = root / name
        if path.is_symlink() or not path.is_file() or sha256_file(path) != record["challenge_input_sha256"][name]:
            raise EnvironmentInvalid(f"challenge input is missing, redirected, or has an unauthorized SHA-256: {name}")
        inputs[name] = path
    if record["challenge_input_sha256"].get(challenge_basis["changed_file"]) != challenge_basis["changed_file_sha256"]:
        raise EnvironmentInvalid("challenge input SHA differs from the frozen evaluator challenge")
    for name in INPUT_SHA256:
        if name != challenge_basis["changed_file"] and record["challenge_input_sha256"][name] != INPUT_SHA256[name]:
            raise EnvironmentInvalid("challenge may change only its one declared contact-distance input")
    mutation = record["mutation"]
    if not isinstance(mutation, dict) or set(mutation) != {"matrix", "removed_contact_edge", "old_distance_angstrom", "new_distance_angstrom"}:
        raise EnvironmentInvalid("challenge mutation declaration is malformed")
    if mutation["matrix"] != challenge_basis["changed_file"] or mutation["removed_contact_edge"] != challenge_basis["removed_contact_edge_matrix_indices"]:
        raise EnvironmentInvalid("challenge mutation differs from the frozen evaluator challenge")
    i, j = mutation["removed_contact_edge"]
    original = np.loadtxt(baseline[challenge_basis["changed_file"]])
    changed = np.loadtxt(inputs[challenge_basis["changed_file"]])
    original_value = float(original[i, j])
    if (not math.isclose(original_value, float(mutation["old_distance_angstrom"]), abs_tol=1e-12)
            or not math.isclose(float(mutation["new_distance_angstrom"]), float(challenge_basis["replacement_distance_angstrom"]), abs_tol=1e-12)
            or original[i, j] > 6.0 or changed[i, j] <= 6.0 or changed[j, i] <= 6.0):
        raise EnvironmentInvalid("challenge does not symmetrically remove its declared original contact")
    original[i, j] = original[j, i] = changed[i, j]
    if not np.array_equal(original, changed):
        raise EnvironmentInvalid("challenge changed data outside the single declared undirected contact edge")
    return inputs, manifest


def _build_automatic_challenge(baseline: dict[str, Path], reference: dict, root: Path) -> tuple[dict[str, Path], Path]:
    basis = reference["calibrated_input_challenge"]
    encoded_manifest = basis.get("manifest_base64")
    if not isinstance(encoded_manifest, str):
        raise EnvironmentInvalid("evaluator-authorized input challenge manifest is not embedded")
    manifest = root / "scientific-challenge-manifest.json"
    try:
        manifest.write_bytes(base64.b64decode(encoded_manifest, validate=True))
    except (OSError, TypeError, ValueError) as exc:
        raise EnvironmentInvalid("evaluator-authorized input challenge manifest is invalid") from exc
    if sha256_file(manifest) != basis["manifest_sha256"]:
        raise EnvironmentInvalid("evaluator-authorized input challenge manifest is damaged")
    for name, source in baseline.items():
        shutil.copyfile(source, root / name)
    matrix_name = basis["changed_file"]
    dist = np.loadtxt(root / matrix_name)
    i, j = basis["removed_contact_edge_matrix_indices"]
    dist[i, j] = dist[j, i] = basis["replacement_distance_angstrom"]
    np.savetxt(root / matrix_name, dist, fmt="%.10g")
    try:
        record = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EnvironmentInvalid(f"evaluator-authorized input challenge manifest cannot be parsed: {exc}") from exc
    inputs = {name: root / name for name in INPUT_SHA256}
    actual_sha = {name: sha256_file(path) for name, path in inputs.items()}
    if actual_sha != record.get("challenge_input_sha256"):
        raise EnvironmentInvalid("derived challenge input bytes disagree with their frozen SHA manifest")
    return inputs, manifest


def _score_challenge_replay(script: Path, inputs: dict[str, Path], manifest: Path, cutoff: float,
                            floor: float, threshold: float) -> dict:
    challenge_matrices = {}
    expected = {}
    independent_seconds = {}
    for tag in ("WT", "V72I"):
        started = time.monotonic()
        corr = np.loadtxt(inputs[f"corrmat_c0_{tag}.dat"])
        dist = np.loadtxt(inputs[f"distmat_c0_{tag}.dat"])
        try:
            adjacency, _ = graph_from_matrices(corr, dist, cutoff, floor)
            normalized = normalized_edge_usage(adjacency)
        except (ValueError, OverflowError) as exc:
            raise EnvironmentInvalid(f"independent challenge {tag} graph calculation failed: {exc}") from exc
        expected[tag] = {edge: value for edge, value in normalized.items() if value > threshold - 1e-12}
        challenge_matrices[tag] = (corr, dist)
        independent_seconds[tag] = round(time.monotonic() - started, 3)
    try:
        replay = _replay_analysis(script, inputs, manifest, threshold)
    except CandidateFail as exc:
        # This cannot silently become a scientific PASS: an old submission may
        # be retained for review but receives no reward without input-challenge support.
        return {"status": "REVIEW_REQUIRED", "reason": str(exc), "candidate_supports_input_manifest": False,
                "independent_grader_wall_seconds_by_variant": independent_seconds}
    row_counts = {}
    for tag in ("WT", "V72I"):
        name = f"spm_{tag}.csv"
        regenerated = _read_graph_data(replay["outputs"][name], name, challenge_matrices[tag][1], cutoff)
        if expected[tag].keys() != regenerated.keys():
            raise CandidateFail(f"analysis.py input-manifest challenge did not recompute the {tag} edge set")
        for edge, value in expected[tag].items():
            if abs(value - regenerated[edge]) > 1e-7:
                raise CandidateFail(f"analysis.py input-manifest challenge has incorrect {tag} edge usage for {edge}")
        row_counts[tag] = len(regenerated)
    return {"status": "PASS", "candidate_supports_input_manifest": True,
            "manifest_sha256": sha256_file(manifest), "selected_edge_rows": row_counts,
            "independent_grader_wall_seconds_by_variant": independent_seconds,
            "candidate_replay": replay["receipt"]}


def _read_findings(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateFail(f"findings.json cannot be parsed: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "method", "beta13", "regional_coverage", "full_graph_path"}:
        raise CandidateFail("findings.json must use exactly schema_version, method, beta13, regional_coverage, and full_graph_path")
    if value["schema_version"] != "spm-allostery/v1":
        raise CandidateFail("findings.json schema_version must be spm-allostery/v1")
    method = value["method"]
    required_method = {"contact_cutoff_angstrom", "correlation_to_length", "correlation_floor", "graph",
                       "shortest_path_policy", "usage_normalization", "display_threshold"}
    if not isinstance(method, dict) or set(method) != required_method:
        raise CandidateFail("findings.json method fields are incomplete or contain undeclared fields")
    for field in ("contact_cutoff_angstrom", "correlation_floor", "display_threshold"):
        if isinstance(method[field], bool) or not isinstance(method[field], (int, float)) or not math.isfinite(method[field]):
            raise CandidateFail(f"findings.json method.{field} must be a finite JSON number")
    if method["contact_cutoff_angstrom"] != 6.0 or method["correlation_floor"] != 1e-12:
        raise CandidateFail("findings.json declares a method outside the independently calibrated numeric parameters")
    return value


def _validate_findings_science(findings: dict, expected: dict, path_evidence: dict, matrices: dict, reference: dict) -> None:
    author = reference["author_output_basis"]
    if author.get("wt_beta13_internal_display_edges") != 5 or author.get("v72i_beta13_internal_display_edges") != 0:
        raise EnvironmentInvalid("pinned author evidence does not support the frozen β13 display comparison")
    if findings["method"]["display_threshold"] == 0.30:
        for tag, field in (("WT", "wt_display_edges"), ("V72I", "v72i_display_edges")):
            if len(expected[tag]) != author[field]:
                raise EnvironmentInvalid(f"independent baseline graph no longer reproduces the pinned author {tag} edge-count reference")
    beta = findings["beta13"]
    if not isinstance(beta, dict) or set(beta) != {"wt_internal_display_edges", "v72i_internal_display_edges", "interpretation"}:
        raise CandidateFail("findings.json beta13 must declare both numeric edge counts and an interpretation")
    wt_count = sum(375 <= a <= 380 and 375 <= b <= 380 for a, b in expected["WT"])
    mut_count = sum(375 <= a <= 380 and 375 <= b <= 380 for a, b in expected["V72I"])
    if type(beta["wt_internal_display_edges"]) is not int or beta["wt_internal_display_edges"] != wt_count:
        raise CandidateFail(f"β13 WT display-edge count must equal the independently computed {wt_count}")
    if type(beta["v72i_internal_display_edges"]) is not int or beta["v72i_internal_display_edges"] != mut_count:
        raise CandidateFail(f"β13 V72I display-edge count must equal the independently computed {mut_count}")
    _validate_beta13_interpretation(beta["interpretation"], wt_count, mut_count)
    coverage = findings["regional_coverage"]
    required_coverage = {"c_terminal_equatorial_to_intermediate", "intermediate_to_apical",
                         "beta13_to_apical", "atp_lid_region_390_409"}
    # Accept either a list of the four branch names or an object keyed by them (a submission may
    # also record per-branch evidence counts as the values).
    if isinstance(coverage, dict):
        coverage_names, coverage_ok = set(coverage), all(isinstance(k, str) for k in coverage)
    elif isinstance(coverage, list) and all(isinstance(item, str) for item in coverage):
        coverage_names, coverage_ok = set(coverage), len(coverage) == len(set(coverage))
    else:
        coverage_names, coverage_ok = None, False
    if not coverage_ok or coverage_names != required_coverage:
        raise CandidateFail("regional_coverage must list the four evidence-backed WT structural branches")
    wt_edges = set(expected["WT"])

    def has_edge(predicate):
        return any(predicate(a, b) or predicate(b, a) for a, b in wt_edges)

    is_equatorial = lambda node: 0 <= node <= 133 or 410 <= node <= 525
    is_intermediate = lambda node: 134 <= node <= 188 or 374 <= node <= 409
    is_apical = lambda node: 189 <= node <= 373
    observed = {
        "c_terminal_equatorial_to_intermediate": has_edge(lambda a, b: is_equatorial(a) and a >= 410 and is_intermediate(b)),
        "intermediate_to_apical": has_edge(lambda a, b: is_intermediate(a) and is_apical(b)),
        "beta13_to_apical": has_edge(lambda a, b: 375 <= a <= 380 and is_apical(b)),
        "atp_lid_region_390_409": has_edge(lambda a, b: 390 <= a <= 409 and 390 <= b <= 409),
    }
    if not all(observed.values()):
        missing = sorted(key for key, value in observed.items() if not value)
        raise CandidateFail(f"WT selected graph does not cover required author/paper-supported branches: {missing}")
    paths = findings["full_graph_path"]
    if not isinstance(paths, dict) or set(paths) != {"WT", "V72I"}:
        raise CandidateFail("findings.json full_graph_path must include WT and V72I evidence")
    for tag in ("WT", "V72I"):
        row = paths[tag]
        if not isinstance(row, dict) or set(row) != {"source_mature", "target_mature", "path_mature", "shortest_distance"}:
            raise CandidateFail(f"findings.json full_graph_path.{tag} has an invalid schema")
        if type(row["source_mature"]) is not int or row["source_mature"] != 517:
            raise CandidateFail(f"{tag} full-graph path source must be mature residue 517")
        path, distance = path_evidence[tag]
        submitted_path = row["path_mature"]
        if not isinstance(submitted_path, list) or len(submitted_path) < 2 or any(type(node) is not int for node in submitted_path):
            raise CandidateFail(f"{tag} full_graph_path.path_mature must be an integer node sequence")
        if (submitted_path[0] != 517 or not (189 <= submitted_path[-1] <= 373)
                or type(row["target_mature"]) is not int or row["target_mature"] != submitted_path[-1]):
            raise CandidateFail(f"{tag} full-graph path must run from mature 517 to a mature apical residue")
        # A path can differ from the deterministic independent example when equal-cost ties exist.
        corr, dist = matrices[tag]
        total = 0.0
        for a, b in zip(submitted_path, submitted_path[1:]):
            if not (0 <= a < 526 and 0 <= b < 526) or dist[a, b] > 6.0:
                raise CandidateFail(f"{tag} claimed full-graph route includes a missing contact edge")
            total += -math.log(max(abs(float(corr[a, b])), 1e-12))
        claimed = _json_number(row["shortest_distance"], f"{tag} shortest_distance")
        if abs(total - claimed) > 1e-8 or abs(total - distance) > 1e-8:
            raise CandidateFail(f"{tag} route is not a minimum-cost full-contact-graph path")


def _read_graph(path: Path, tag: str, distances: np.ndarray, cutoff: float) -> dict[tuple[int, int], float]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"source", "target", "normalized_weight"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise CandidateFail(f"{path.name} must contain source,target,normalized_weight")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CandidateFail(f"cannot parse {path.name}: {exc}") from exc
    return _read_graph_rows(rows, path.name, distances, cutoff)


def _read_graph_data(data: bytes, filename: str, distances: np.ndarray, cutoff: float) -> dict[tuple[int, int], float]:
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
        required = {"source", "target", "normalized_weight"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise CandidateFail(f"{filename} must contain source,target,normalized_weight")
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise CandidateFail(f"cannot parse replayed {filename}: {exc}") from exc
    return _read_graph_rows(rows, filename, distances, cutoff)


def _read_graph_rows(rows: list[dict[str, str]], filename: str, distances: np.ndarray,
                     cutoff: float) -> dict[tuple[int, int], float]:
    if not rows:
        raise CandidateFail(f"{filename} has no graph edges")
    parsed: dict[tuple[int, int], float] = {}
    for number, row in enumerate(rows, 2):
        try:
            mature_source, mature_target = int(row["source"]), int(row["target"])
        except (TypeError, ValueError) as exc:
            raise CandidateFail(f"{filename}:{number}: source and target must be integer mature residue numbers") from exc
        # Mature numbering equals the zero-based matrix index. The separate
        # author/PDB residue labels are one-based and are not CSV indices.
        i, j = mature_source, mature_target
        if not (0 <= i < 526 and 0 <= j < 526) or i == j:
            raise CandidateFail(f"{filename}:{number}: mature residue does not map to a valid distinct matrix pair")
        pair = (i, j)
        if pair in parsed:
            raise CandidateFail(f"{filename}:{number}: duplicate directed graph edge")
        weight = finite_number(row["normalized_weight"], f"{filename}:{number} normalized_weight")
        if not 0 <= weight <= 1:
            raise CandidateFail(f"{filename}:{number}: normalized_weight must be in [0,1]")
        if distances[i, j] > cutoff + 1e-9:
            raise CandidateFail(f"{filename}:{number}: edge violates the report's declared contact cutoff")
        parsed[pair] = weight
    return parsed


def _candidate_preexec(rootfs: Path, work: Path) -> None:
    os.chroot(rootfs)
    os.chdir(str(work))
    resource.setrlimit(resource.RLIMIT_CPU, (REPLAY_CPU_SECONDS, REPLAY_CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (REPLAY_MAX_FILE_BYTES, REPLAY_MAX_FILE_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (REPLAY_MAX_PROCESSES, REPLAY_MAX_PROCESSES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (REPLAY_MAX_ADDRESS_SPACE, REPLAY_MAX_ADDRESS_SPACE))
    os.umask(0o077)
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), "prctl(PR_SET_NO_NEW_PRIVS)")


def _require_chroot_capabilities() -> None:
    if os.geteuid() != 0:
        raise EnvironmentInvalid("isolated analysis replay requires a root verifier")
    try:
        line = next(line for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines()
                    if line.startswith("CapEff:"))
        effective = int(line.split()[1], 16)
    except (OSError, StopIteration, ValueError, IndexError) as exc:
        raise EnvironmentInvalid(f"cannot verify verifier capabilities for chroot replay: {exc}") from exc
    required = (1 << 18) | (1 << 6) | (1 << 7)  # SYS_CHROOT, SETGID, SETUID
    if effective & required != required:
        raise EnvironmentInvalid("verifier lacks SYS_CHROOT, SETGID, or SETUID; refusing weaker candidate execution")


def _bounded_replay_tmpfs() -> Path:
    mount_size = None
    try:
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) < 10 or fields[4].replace("\\040", " ") != "/dev/shm":
                continue
            separator = fields.index("-")
            if fields[separator + 1] != "tmpfs":
                continue
            options = fields[5].split(",")
            super_options = fields[separator + 3].split(",")
            size_option = next((item for item in super_options if item.startswith("size=")), None)
            if size_option is None or "ro" in options or "noexec" in options:
                break
            raw = size_option[5:]
            multiplier = 1
            for suffix, value in (("k", 1024), ("m", 1024**2), ("g", 1024**3)):
                if raw.lower().endswith(suffix):
                    raw, multiplier = raw[:-1], value
                    break
            mount_size = int(raw) * multiplier
            break
    except (OSError, ValueError, IndexError) as exc:
        raise EnvironmentInvalid(f"cannot verify executable bounded replay tmpfs: {exc}") from exc
    if mount_size is None or mount_size <= 0 or mount_size > REPLAY_TMPFS_MAX_BYTES:
        raise EnvironmentInvalid("candidate replay requires executable /dev/shm tmpfs capped at 512 MiB or less")
    if Path("/dev/shm").is_symlink() or not Path("/dev/shm").is_dir():
        raise EnvironmentInvalid("candidate replay /dev/shm is missing or unsafe")
    return Path("/dev/shm")


def _tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            total += path.stat().st_size
    return total


def _stream_tail(data: bytearray) -> bytes:
    return bytes(data[-REPLAY_STREAM_CHARS:])


def _stream_text(data: bytearray) -> str:
    return _stream_tail(data).decode("utf-8", errors="replace")


def _collect_candidate_streams(proc: subprocess.Popen) -> tuple[str, str]:
    """Drain candidate pipes with a combined byte cap and wall deadline."""
    if proc.stdout is None or proc.stderr is None:
        raise EnvironmentInvalid("candidate replay pipes were not created")
    streams = {proc.stdout.fileno(): bytearray(), proc.stderr.fileno(): bytearray()}
    selector = selectors.DefaultSelector()
    started = time.monotonic()
    try:
        for pipe in (proc.stdout, proc.stderr):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map() or proc.poll() is None:
            remaining = REPLAY_TIMEOUT_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise CandidateFail(
                    f"analysis.py exceeded {REPLAY_TIMEOUT_SECONDS}s; "
                    f"stdout={_stream_text(streams[proc.stdout.fileno()])!r}; "
                    f"stderr={_stream_text(streams[proc.stderr.fileno()])!r}"
                )
            if not selector.get_map():
                time.sleep(min(remaining, 0.1))
                continue
            for key, _ in selector.select(min(remaining, 0.25)):
                fd = key.fd
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if sum(map(len, streams.values())) + len(chunk) > REPLAY_STREAM_MAX_BYTES:
                    raise CandidateFail(
                        f"analysis.py exceeded combined stdout/stderr limit "
                        f"of {REPLAY_STREAM_MAX_BYTES} bytes; "
                        f"stdout={_stream_text(streams[proc.stdout.fileno()])!r}; "
                        f"stderr={_stream_text(streams[proc.stderr.fileno()])!r}"
                    )
                streams[fd].extend(chunk)
        return (_stream_text(streams[proc.stdout.fileno()]),
                _stream_text(streams[proc.stderr.fileno()]))
    finally:
        selector.close()


def _kill_and_reap_candidate(proc: subprocess.Popen) -> None:
    """Stop the candidate process group and always reap its leader."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait()
    except OSError:
        pass


def _replay_analysis(script: Path, inputs: dict[str, Path], challenge_manifest: Path | None = None,
                     threshold: float = 0.30) -> dict:
    replay_started = time.monotonic()
    _require_chroot_capabilities()
    configured = os.environ.get("CCB_PYTHON_ROOTFS")
    if not configured:
        raise EnvironmentInvalid("Python 3.12 candidate chroot is not configured")
    source_root = Path(configured)
    if source_root.is_symlink() or not source_root.is_dir():
        raise EnvironmentInvalid("candidate chroot path is missing or redirected")
    rootfs_source = source_root.resolve(strict=True)
    for forbidden in ("tests", "refs", "references", "root/.ssh", "root/.claude", "proc", "dev"):
        if (rootfs_source / forbidden).exists():
            raise EnvironmentInvalid(f"candidate chroot unexpectedly includes a forbidden path: {forbidden}")
    if not (rootfs_source / "usr/bin/python3").is_file():
        raise EnvironmentInvalid("candidate chroot lacks its Python interpreter")
    temp_root = _bounded_replay_tmpfs()
    required = _tree_bytes(rootfs_source) + sum(path.stat().st_size for path in inputs.values()) + 8 * 1024 * 1024
    if shutil.disk_usage(temp_root).free < required:
        raise EnvironmentInvalid("bounded replay tmpfs lacks space for a fresh candidate chroot")
    with tempfile.TemporaryDirectory(prefix="ccb-case03-replay-", dir=temp_root) as temp_name:
        rootfs = Path(temp_name) / "rootfs"
        try:
            shutil.copytree(rootfs_source, rootfs, symlinks=True)
            (rootfs / "tmp").chmod(0o555)
            assets = rootfs / "assets"
            assets.mkdir(mode=0o755)
            for name, source in inputs.items():
                destination = assets / name
                shutil.copyfile(source, destination)
                destination.chmod(0o444)
            assets.chmod(0o555)
            if challenge_manifest is not None:
                challenge = rootfs / "challenge"
                challenge.mkdir(mode=0o555)
                shutil.copyfile(challenge_manifest, challenge / "manifest.json")
                (challenge / "manifest.json").chmod(0o444)
        except OSError as exc:
            raise EnvironmentInvalid(f"cannot stage a fresh private candidate chroot: {exc}") from exc
        work_root = rootfs / "work"
        if work_root.is_symlink() or not work_root.is_dir():
            raise EnvironmentInvalid("candidate chroot work directory is missing or unsafe")
        attempt = work_root / uuid.uuid4().hex
        source_dir, output_dir = attempt / "source", attempt / "out"
        source_dir.mkdir(parents=True, mode=0o755)
        output_dir.mkdir(mode=0o777)
        output_dir.chmod(0o777)
        candidate_script = source_dir / "analysis.py"
        try:
            shutil.copyfile(script, candidate_script)
            candidate_script.chmod(0o444)
            source_dir.chmod(0o555)
            attempt.chmod(0o755)
        except OSError as exc:
            raise CandidateFail(f"cannot stage analysis.py for isolated replay: {exc}") from exc
        child_work = Path("/work") / attempt.name / "out"
        proc = None
        try:
            command = ["/opt/ccb-runtime/bin/python", "-I", str(Path("/work") / attempt.name / "source/analysis.py"),
                       "--assets", "/assets", "--output", str(child_work), "--threshold", str(threshold)]
            if challenge_manifest is not None:
                command.extend(("--input-manifest", "/challenge/manifest.json"))
            proc = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, env={
                    "HOME": str(child_work), "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin",
                    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                    "MPLCONFIGDIR": str(child_work / ".mplconfig"), "TMPDIR": str(child_work),
                }, close_fds=True, start_new_session=True,
                preexec_fn=lambda: _candidate_preexec(rootfs, child_work),
            )
            stdout, stderr = _collect_candidate_streams(proc)
            proc.wait()
        except CandidateFail:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise EnvironmentInvalid(f"could not start isolated candidate chroot: {exc}") from exc
        finally:
            if proc is not None:
                _kill_and_reap_candidate(proc)
                for pipe in (proc.stdout, proc.stderr):
                    if pipe is not None:
                        pipe.close()
        if proc.returncode != 0:
            raise CandidateFail(f"analysis.py exited {proc.returncode}; stdout={stdout!r}; stderr={stderr!r}")
        outputs: dict[str, bytes] = {}
        for filename in ("spm_WT.csv", "spm_V72I.csv"):
            path = output_dir / filename
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                raise CandidateFail(f"analysis.py replay did not produce {filename}")
            outputs[filename] = path.read_bytes()
        receipt = {
            "isolation": "network-none outer container + fresh Python/science chroot + uid/gid 65534 + no_new_privileges + rlimits",
            "uid_gid": 65534, "wall_timeout_seconds": REPLAY_TIMEOUT_SECONDS,
            "elapsed_wall_seconds": round(time.monotonic() - replay_started, 3),
            "cpu_limit_seconds": [REPLAY_CPU_SECONDS, REPLAY_CPU_SECONDS + 1],
            "address_space_limit_bytes": REPLAY_MAX_ADDRESS_SPACE,
            "file_size_limit_bytes": REPLAY_MAX_FILE_BYTES, "process_limit": REPLAY_MAX_PROCESSES,
            "private_tests_in_chroot": False, "ssh_credentials_in_chroot": False,
            "read_only_public_inputs": True, "candidate_writable_path": str(child_work),
            "public_input_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()},
            "challenge_manifest_sha256": hashlib.sha256(challenge_manifest.read_bytes()).hexdigest() if challenge_manifest else None,
            "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "replayed_output_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
            "returncode": proc.returncode, "stdout": stdout, "stderr": stderr,
        }
        return {"outputs": outputs, "receipt": receipt}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app")
    parser.add_argument("--assets", required=True)
    parser.add_argument("--logs", required=True)
    parser.add_argument("--input-manifest")
    parser.add_argument("--baseline-assets")
    args = parser.parse_args()
    raise SystemExit(run(args.app, args.assets, args.logs, args.input_manifest, args.baseline_assets))
