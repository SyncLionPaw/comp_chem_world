#!/usr/bin/env bash
set -euo pipefail
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/task73-solution.XXXXXX")"
# Keep extracted sources available until execution and any HPC staging/collection finish.
trap 'rm -rf -- "$work_dir"' EXIT
cat > "$work_dir/solve.py" <<'TASK_SOURCE_SOLVE_PY'
#!/usr/bin/env python3
"""Reference analysis using NetworkX weighted edge betweenness."""
from __future__ import annotations

import argparse
import csv
import hashlib
import time
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np

INPUT_SHA256 = {
    "README_residue_numbering": "a1488c55ef353c6ae82a2f9d77c35a6dfc9929ac70a65081f098acb4156ea230",
    "corrmat_c0_WT.dat": "be3202d7235606d7e212b6baac5a26bc26a38c2c9a809a359f054bac28cf7bb0",
    "distmat_c0_WT.dat": "63d6042457f7fcc811fd24fb0cb2a2ac18185cc85bfdb28ed3831b42e6be2686",
    "corrmat_c0_V72I.dat": "881b191e61b3807565c83125ddcbb9d03840a855885582d3a732318128c3cd05",
    "distmat_c0_V72I.dat": "3f0f76ec7bb044b55783151835833341b2ca3d418cb1d9e388862cffc62a8b65",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_challenge(assets: Path, manifest_path: Path | None) -> None:
    if manifest_path is None:
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "base_input_sha256", "challenge_input_sha256", "mutation"}:
        raise ValueError("challenge SHA manifest has an unsupported schema")
    if manifest["schema_version"] != "spm-input-challenge/v1" or manifest["base_input_sha256"] != INPUT_SHA256:
        raise ValueError("challenge SHA manifest does not authorize this baseline")
    actual = {name: sha256(assets / name) for name in INPUT_SHA256}
    if actual != manifest["challenge_input_sha256"]:
        raise ValueError("challenge assets do not match the explicitly authorized SHA manifest")
    mutation = manifest["mutation"]
    if not isinstance(mutation, dict) or set(mutation) != {"removed_contact_edge", "matrix", "old_distance_angstrom", "new_distance_angstrom"}:
        raise ValueError("challenge manifest mutation declaration is invalid")


def graph(corr: np.ndarray, dist: np.ndarray) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(range(526))
    i, j = np.where(np.triu(dist <= 6.0, k=1))
    lengths = -np.log(np.maximum(np.abs(corr[i, j]), 1e-12))
    g.add_edges_from((int(a), int(b), {"length": float(cost)}) for a, b, cost in zip(i, j, lengths))
    return g


def path_to_apical(g: nx.Graph) -> tuple[list[int], float]:
    distances, paths = nx.single_source_dijkstra(g, 517, weight="length")
    target = min((n for n in range(189, 374) if n in distances), key=lambda n: (distances[n], n))
    return paths[target], float(distances[target])


def analyze(assets: Path, output: Path, threshold: float) -> None:
    wall_started = time.monotonic()
    cpu_started = time.process_time()
    output.mkdir(parents=True, exist_ok=True)
    expected = {}
    path_claims = {}
    for tag in ("WT", "V72I"):
        corr = np.loadtxt(assets / f"corrmat_c0_{tag}.dat")
        dist = np.loadtxt(assets / f"distmat_c0_{tag}.dat")
        g = graph(corr, dist)
        raw = nx.edge_betweenness_centrality(g, normalized=False, weight="length")
        maximum = max(raw.values())
        normalized = {tuple(sorted(edge)): float(value / maximum) for edge, value in raw.items()}
        expected[tag] = {edge: value for edge, value in normalized.items() if value > threshold}
        with (output / f"spm_{tag}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("source", "target", "normalized_weight"))
            for (a, b), value in sorted(expected[tag].items()):
                writer.writerow((a, b, f"{value:.17g}"))
        path, cost = path_to_apical(g)
        path_claims[tag] = {"source_mature": 517, "target_mature": path[-1],
                            "path_mature": path, "shortest_distance": cost}
    beta_counts = {
        tag: sum(375 <= a <= 380 and 375 <= b <= 380 for a, b in expected[tag])
        for tag in ("WT", "V72I")
    }
    findings = {
        "schema_version": "spm-allostery/v1",
        "method": {
            "contact_cutoff_angstrom": 6.0,
            "correlation_to_length": "negative_log_abs_floor",
            "correlation_floor": 1e-12,
            "graph": "undirected",
            "shortest_path_policy": "equal_split_all_pairs",
            "usage_normalization": "maximum_edge_usage",
            "display_threshold": threshold,
        },
        "beta13": {
            "wt_internal_display_edges": beta_counts["WT"],
            "v72i_internal_display_edges": beta_counts["V72I"],
            "interpretation": "wt_display_branch_lost_or_weakened_in_v72i",
        },
        "regional_coverage": ["c_terminal_equatorial_to_intermediate", "intermediate_to_apical",
                              "beta13_to_apical", "atp_lid_region_390_409"],
        "full_graph_path": path_claims,
    }
    (output / "findings.json").write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
    (output / "analysis.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (output / "report.md").write_text(
        """# WT 与 V72I SPM 比较

contact_cutoff_angstrom: 6.0
edge_length_definition: -log(max(abs(correlation), 1e-12))

以零基矩阵索引作为成熟 Hsp60 编号。每个变体使用无向全接触图；在全图上计算所有节点对的加权最短路边使用量，最短路等权分摊，随后以全图最大边使用量归一化。表格保留归一化使用量严格高于声明阈值的完整边集。`findings.json` 声明当前阈值并列出全图而非显示子图的路径证据。

WT 的显示图在 C 端赤道区与中间域、铰链/中间域与顶端域，以及 β13 至 apical 区分支均有边；Asp397 附近 390–409 区间有高使用量边。WT 成熟 375–380 的五条内部边都超过当前显示阈值。V72I 中相同五条结构接触仍在 6 Å 接触图中，但没有一条内部边超过当前阈值，因此解释为 β13 变构分支使用量减弱并从阈值图消失，不能解释为残基或接触结构消失。V72I 边界 380–381 与 381–382 仍保留于 0.30 阈值图；较高阈值的显示边须按其实际 CSV 判断。

WT 成熟 517–516 是局部显示边。WT 在当前阈值图中没有从 517 连至 apical 的连续路线；517 至 apical 的真实最短路证据取自未阈值化的全接触图，避免将显示子图误作连续通路。论文第 4 页和作者输出支持 C 端、ATP-lid 附近与 apical 区的区域关系；区域覆盖不等同于把 517 与 Asp397 强制连成一条唯一显示路径。
        """, encoding="utf-8")
    print(json.dumps({"analysis_wall_seconds": round(time.monotonic() - wall_started, 3),
                      "analysis_cpu_seconds": round(time.process_time() - cpu_started, 3),
                      "graphs": 2, "contact_cutoff_angstrom": 6.0, "display_threshold": threshold}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, default=Path("/app/assets"))
    parser.add_argument("--output", type=Path, default=Path("/app/final"))
    parser.add_argument("--threshold", type=float, choices=(0.30, 0.35), default=0.30)
    parser.add_argument("--input-manifest", type=Path)
    args = parser.parse_args()
    validate_challenge(args.assets, args.input_manifest)
    analyze(args.assets, args.output, args.threshold)


if __name__ == "__main__":
    main()
TASK_SOURCE_SOLVE_PY

python3 "$work_dir/solve.py" "$@"
