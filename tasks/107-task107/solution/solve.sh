#!/usr/bin/env bash
set -euo pipefail
exec python3 - "$0" <<'PY'
#!/usr/bin/env python3
"""Count short Li-Li contacts from every deposited migration geometry."""
import json
import os
import sys
from pathlib import Path

HERE = Path(sys.argv[1]).resolve().parent
REFS_PATH = HERE.parent / "tests" / "refs.json"
# The isolated oracle container receives only /solution, without /tests.
CONFIG = json.loads(REFS_PATH.read_text(encoding="utf-8")) if REFS_PATH.is_file() else json.loads(r'''{
  "carriers": [
    "Li4_plus_delta",
    "Li5_plus_delta",
    "Li7_minus_delta"
  ],
  "groups": {
    "Li4_plus_delta": [
      "NEB_Li4+x",
      [
        "neb_hop_1",
        "neb_hop_2",
        "neb_hop_3",
        "neb_hop_4",
        "neb_hop_5"
      ]
    ],
    "Li5_plus_delta": [
      "NEB_Li5+x",
      [
        "neb_hop_1",
        "neb_hop_2",
        "neb_hop_3",
        "neb_hop_4",
        "neb_hop_5",
        "neb_hop_6",
        "neb_hop_7"
      ]
    ],
    "Li7_minus_delta": [
      "",
      [
        "NEB_Li7-x"
      ]
    ]
  },
  "tolerance_meV": 8.0,
  "pair_cutoff_A": 2.6,
  "reference_barriers_meV": {
    "Li4_plus_delta": 343.343,
    "Li5_plus_delta": 199.369,
    "Li7_minus_delta": 455.574
  }
}''')

import math

PAIR_CUTOFF_A = CONFIG["pair_cutoff_A"]
CARRIERS = tuple(CONFIG["carriers"])


def assets_root() -> Path:
    override = os.environ.get("CASE_ASSETS")
    if override:
        return Path(override)
    mounted = Path("/app/assets")
    if mounted.is_dir():
        return mounted
    return HERE.parent / "environment" / "assets"


def hop_dirs(name: str) -> list[Path]:
    base = assets_root()
    composition, hops = CONFIG["groups"][name]
    return [base / composition / hop for hop in hops]


def image_dirs(hop: Path, require_outcar: bool) -> list[Path]:
    found = []
    for child in hop.iterdir():
        if not (child.is_dir() and child.name.isdigit()):
            continue
        has_out = (child / "OUTCAR.bz2").is_file()
        has_geo = (child / "POSCAR").is_file() or (child / "CONTCAR").is_file()
        if require_outcar and not has_out:
            continue
        if not require_outcar and not has_geo:
            continue
        found.append(child)
    return sorted(found, key=lambda p: int(p.name))


def hop_label(image: Path) -> str:
    parent = image.parent.name
    return parent if parent.startswith("neb_hop_") or parent == "NEB_Li7-x" else parent


def read_poscar(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    scale = float(lines[1].split()[0])
    lattice = [[float(x) * scale for x in lines[i].split()[:3]] for i in range(2, 5)]
    names = lines[5].split()
    counts = [int(x) for x in lines[6].split()]
    cursor = 7
    if lines[cursor].strip().lower().startswith("s"):
        cursor += 1
    mode = lines[cursor].strip().lower()
    cursor += 1
    n = sum(counts)
    coords = [[float(x) for x in lines[cursor + i].split()[:3]] for i in range(n)]
    species = []
    for name, count in zip(names, counts):
        species.extend([name] * count)
    if mode.startswith("d"):
        cart = []
        for frac in coords:
            cart.append([
                frac[0] * lattice[0][0] + frac[1] * lattice[1][0] + frac[2] * lattice[2][0],
                frac[0] * lattice[0][1] + frac[1] * lattice[1][1] + frac[2] * lattice[2][1],
                frac[0] * lattice[0][2] + frac[1] * lattice[1][2] + frac[2] * lattice[2][2],
            ])
    else:
        cart = [[c * scale for c in row] for row in coords]
    return lattice, species, cart


def structure_path(image: Path) -> Path:
    contcar = image / "CONTCAR"
    if contcar.is_file() and contcar.stat().st_size > 200:
        return contcar
    return image / "POSCAR"


def li_li_pairs(image: Path, cutoff: float = PAIR_CUTOFF_A) -> int:
    lattice, species, cart = read_poscar(structure_path(image))
    a, b, c = lattice

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    volume = a[0] * cross(b, c)[0] + a[1] * cross(b, c)[1] + a[2] * cross(b, c)[2]
    inv_cols = [cross(b, c), cross(c, a), cross(a, b)]
    inv = [[inv_cols[col][row] / volume for col in range(3)] for row in range(3)]
    li = [cart[i] for i, sp in enumerate(species) if sp == "Li"]
    count = 0
    for i in range(len(li)):
        for j in range(i + 1, len(li)):
            delta = [li[j][k] - li[i][k] for k in range(3)]
            frac = [sum(delta[c] * inv[c][r] for c in range(3)) for r in range(3)]
            frac = [f - round(f) for f in frac]
            cart_d = [sum(frac[r] * lattice[r][c] for r in range(3)) for c in range(3)]
            dist = math.sqrt(sum(x * x for x in cart_d))
            if dist < cutoff:
                count += 1
    return count


def contact_records(name: str) -> list[dict]:
    rows = []
    for hop in hop_dirs(name):
        for image in image_dirs(hop, require_outcar=False):
            rows.append({
                "hop": hop_label(image),
                "image": image.name,
                "n_pairs": li_li_pairs(image),
            })
    if not rows:
        raise ValueError(f"no geometry profile for {name}")
    return rows

ROOT = Path(os.environ.get("APP", "/app"))
OUT = ROOT / "final"
series = {name: [
    {"hop": row["hop"], "image": row["image"], "n_pairs": row["n_pairs"]}
    for row in contact_records(name)
] for name in CARRIERS}
li7 = series["Li7_minus_delta"]
li4 = series["Li4_plus_delta"]
li5 = series["Li5_plus_delta"]
conclusion = {
    "li7_short_contacts_absent_at_endpoints": li7[0]["n_pairs"] == 0 and li7[-1]["n_pairs"] == 0,
    "li7_short_contacts_present_on_interior_images": any(row["n_pairs"] > 0 for row in li7[1:-1]),
    "li4_and_li5_start_already_have_short_contacts": li4[0]["n_pairs"] > 0 and li5[0]["n_pairs"] > 0,
    "bulk_solid_solution_required": False,
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "results.json").write_text(json.dumps({"contact_series": series,
    "kinetic_conclusion": conclusion}, indent=2) + "\n", encoding="utf-8")
(OUT / "methods.md").write_text(
    "对每张图像使用 CONTCAR（若无则 POSCAR），在周期边界条件下对所有 Li–Li 对计算最小镜像距离；" 
    "严格小于 2.60 Å 计为短接触。前三项结论由完整图像序列的端点、内部图像和 Li4/Li5 起点计数直接得到。"
    "`bulk_solid_solution_required` 不同：这些分 hop 几何只覆盖有限迁移路径的局部构型，"
    "既不包含体相混合的热力学与熵信息，也未采样除迁移路径以外的构型，因此不足以确立体相完全混合固溶体；"
    "该判断表示所给证据不充分，而不是已证明固溶体在热力学上不可能。\n",
    encoding="utf-8",
)
PY
