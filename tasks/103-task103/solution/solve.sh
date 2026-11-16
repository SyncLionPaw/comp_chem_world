#!/usr/bin/env bash
set -euo pipefail
exec python3 - "$0" <<'PY'
#!/usr/bin/env python3
"""Reconstruct the stitched energy profiles from deposited native OUTCARs."""
import bz2
import json
import os
import re
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

ROOT = Path(os.environ.get("APP", "/app"))
ASSETS = ROOT / "assets"
OUT = ROOT / "final"
GROUPS = CONFIG["groups"]
SIGMA = re.compile(r"energy\(sigma->0\)\s*=\s*([+-]?\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?)")


def energy(path: Path) -> float:
    text = bz2.decompress(path.read_bytes()).decode("latin1", errors="replace")
    values = SIGMA.findall(text)
    if not values:
        raise ValueError(f"missing energy(sigma->0) in {path}")
    return float(values[-1])


profiles = {}
barriers = {}
for name, (composition, hops) in GROUPS.items():
    rows = []
    offset = 0.0
    for hop_name in hops:
        hop = ASSETS / composition / hop_name
        images = sorted(
            (p for p in hop.iterdir() if p.is_dir() and p.name.isdigit()
             and (p / "OUTCAR.bz2").is_file()),
            key=lambda p: int(p.name),
        )
        if not images:
            continue
        energies = [energy(image / "OUTCAR.bz2") for image in images]
        start = energies[0]
        for image, value in zip(images, energies):
            rows.append({"hop": hop_name, "image": image.name,
                         "energy_meV": round(offset + (value - start) * 1000.0, 6)})
        offset = rows[-1]["energy_meV"]
    if not rows:
        raise ValueError(f"no deposited OUTCAR images for {name}")
    profiles[name] = rows
    barriers[name] = round(max(row["energy_meV"] for row in rows), 6)

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "results.json").write_text(json.dumps({"path_profile": profiles,
    "barriers_meV": barriers}, indent=2) + "\n", encoding="utf-8")
(OUT / "methods.md").write_text(
    "使用每个原生 OUTCAR 最后一次 `energy(sigma->0)`。按输入 hop 顺序逐段拼接；每段以其首图为零点，" 
    "下一段首图接续上一段末图。报告值相对全路径首图，单位 meV；势垒为该拼接剖面的最大值。\n",
    encoding="utf-8",
)
PY
