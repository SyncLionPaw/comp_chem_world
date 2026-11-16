"""Minimal, self-contained public-geometry helpers for Case07 preparation.

The routines below are adapted from runtimes/hpc/case07/reference_campaign.py
at SHA-256 5ce15f16265bb2cd4e5add04d9b52d3823f9982befe86c9b3a21c67d6334aef2.
Only public CSV mapping, alignment and interpolation math is included; no
campaign controller, broker, runner, archive, or private reference is loaded.
See reference-plan.json for the source functions and frozen input pins.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

ATOM_ORDER = ("C", "C", "C", "C", "C", "C", "H", "H", "H", "H", "O", "O", "O", "O", "H", "O", "C", "H", "H", "H", "H")
SOURCE_INDEX = {
    "bpr": list(range(1, 22)),
    "C1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 20, 12, 13, 21, 14, 16, 17, 18, 19, 15],
    "C2": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 11, 12, 13, 21, 14, 15, 16, 17, 18, 19],
}
SCREEN_LAMBDAS = (0.15, 0.30, 0.50)
RETAINED_BONDS = ((0, 10), (1, 11), (3, 12), (5, 13), (12, 15),
                  (1, 6), (2, 7), (3, 8), (4, 9), (16, 17), (16, 18),
                  (16, 19), (0, 20))
EXPECTED_SHA256 = "504e3f981b84b5f46e9bbc41a15c4e57ce9bb0d1384baa75df5a8ec8ca0ca3c3"


def distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def align_quaternion(coords: list[list[float]], target: list[list[float]]) -> list[list[float]]:
    """Align heavy atoms with the same quaternion power iteration as source."""
    heavy = [i for i, e in enumerate(ATOM_ORDER) if e != "H"]
    ca = [sum(coords[i][k] for i in heavy) / len(heavy) for k in range(3)]
    cb = [sum(target[i][k] for i in heavy) / len(heavy) for k in range(3)]
    aa = [[v-ca[k] for k, v in enumerate(p)] for p in coords]
    bb = [[v-cb[k] for k, v in enumerate(p)] for p in target]
    s = [[sum(aa[i][j]*bb[i][k] for i in heavy) for k in range(3)] for j in range(3)]
    xx, xy, xz = s[0]; yx, yy, yz = s[1]; zx, zy, zz = s[2]
    n = [[xx+yy+zz, yz-zy, zx-xz, xy-yx],
         [yz-zy, xx-yy-zz, xy+yx, zx+xz],
         [zx-xz, xy+yx, -xx+yy-zz, yz+zy],
         [xy-yx, zx+xz, yz+zy, -xx-yy+zz]]
    shift = sum(abs(v) for row in n for v in row) + 1.0
    q = [1.0, 0.1, 0.2, 0.3]
    for _ in range(2000):
        v = [sum(n[i][j]*q[j] for j in range(4)) + shift*q[i] for i in range(4)]
        norm = math.sqrt(sum(x*x for x in v))
        if norm == 0 or not math.isfinite(norm):
            raise ValueError("public endpoint alignment failed")
        p = [x/norm for x in v]
        if sum((x-y)**2 for x, y in zip(q, p)) < 1e-26:
            q = p
            break
        q = p
    w, x, y, z = q
    r = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    out = [[sum(r[k][j]*p[j] for j in range(3))+cb[k] for k in range(3)] for p in aa]
    before = sum(distance(coords[i], target[i])**2 for i in heavy)
    after = sum(distance(out[i], target[i])**2 for i in heavy)
    if after > before + 1e-6:
        raise ValueError("public endpoint alignment increased heavy-atom RMSD")
    return out


def load_public_geometries(assets: Path) -> dict[str, dict[str, object]]:
    path = assets / "bpr_skeleton_geometries.csv"
    if path.is_symlink() or not path.is_file():
        raise ValueError("canonical public geometry asset is missing or unsafe")
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise ValueError("public geometry asset SHA-256 differs from pinned input")
    groups: dict[str, list[dict[str, str]]] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["sheet", "species_role", "atom_index", "element", "x", "y", "z"]:
            raise ValueError("public geometry asset has an unexpected schema")
        for row in reader:
            groups.setdefault(row["species_role"], []).append(row)
    names = {"bpr": "bicyclic_peroxy_radical", "C1": "ring_opened_product_C1",
             "C2": "ring_opened_product_C2"}
    result: dict[str, dict[str, object]] = {}
    for name, role in names.items():
        rows = sorted(groups.get(role, []), key=lambda r: int(r["atom_index"]))
        if len(rows) != 21 or [int(r["atom_index"]) for r in rows] != list(range(1, 22)):
            raise ValueError(f"public geometry rows are incomplete for {role}")
        source_e = [r["element"] for r in rows]
        source_xyz = [[float(r[a]) for a in ("x", "y", "z")] for r in rows]
        indices = SOURCE_INDEX[name]
        elements = [source_e[i-1] for i in indices]
        coords = [source_xyz[i-1] for i in indices]
        if tuple(elements) != ATOM_ORDER or any(not math.isfinite(v) for row in coords for v in row):
            raise ValueError(f"public geometry mapping is invalid for {role}")
        result[name] = {"elements": elements, "coordinates": coords}
    for channel in ("C1", "C2"):
        result[channel]["coordinates"] = align_quaternion(
            result[channel]["coordinates"], result["bpr"]["coordinates"])
    return result


def screen_geometry(bpr: list[list[float]], product: list[list[float]], lam: float) -> list[list[float]]:
    seed = [[(1-lam)*a + lam*b for a, b in zip(x, y)] for x, y in zip(bpr, product)]
    for center, atom in RETAINED_BONDS:
        vector = [seed[atom][k]-seed[center][k] for k in range(3)]
        length = math.sqrt(sum(v*v for v in vector))
        if not math.isfinite(length) or length <= 1e-5:
            raise ValueError("public interpolation collapsed a retained bond")
        desired = ((1-lam)*distance(bpr[center], bpr[atom])
                   + lam*distance(product[center], product[atom]))
        seed[atom] = [seed[center][k] + vector[k]*desired/length for k in range(3)]
    if min(distance(seed[i], seed[j]) for i in range(21) for j in range(i)) <= 0.55:
        raise ValueError("public interpolation contains an implausibly short atom pair")
    return seed


def typed_geometry(coords: list[list[float]]) -> list[dict[str, object]]:
    return [{"element": element, "xyz": [float(value) for value in row]}
            for element, row in zip(ATOM_ORDER, coords)]
