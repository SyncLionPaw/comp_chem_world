#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Reconstruct Li migration energy profiles from VASP outputs.
"""Score stitched Li migration barriers from deposited NEB OUTCARs.

L2 requires a complete per-image energy profile. Keyword text in methods.md
is not a substitute. Barriers are the maximum of that stitched profile.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bz2
import json
import math
import os
import re
from pathlib import Path

SIGMA = re.compile(r"energy\(sigma->0\)\s*=\s*([+-]?\d+\.\d+)")
NOENT = re.compile(r"energy\s+without entropy=\s*([+-]?\d+\.\d+)")
CONFIG = json.loads(Path(__file__).with_name("refs.json").read_text(encoding="utf-8"))
TOL_MEV = CONFIG["tolerance_meV"]
PAIR_CUTOFF_A = CONFIG["pair_cutoff_A"]
CARRIERS = tuple(CONFIG["carriers"])
REFERENCE_BARRIERS = CONFIG["reference_barriers_meV"]


def assets_root() -> Path:
    override = os.environ.get("CASE_ASSETS")
    if override:
        return Path(override)
    mounted = Path("/app/assets")
    if mounted.is_dir():
        return mounted
    return Path(__file__).resolve().parents[1] / "environment" / "assets"


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


def last_energies(outcar_bz2: Path) -> tuple[float, float]:
    text = bz2.decompress(outcar_bz2.read_bytes()).decode("latin1", errors="replace")
    sigma = SIGMA.findall(text)
    noent = NOENT.findall(text)
    if not sigma or not noent:
        raise ValueError(f"missing energy tags in {outcar_bz2}")
    return float(sigma[-1]), float(noent[-1])


def hop_label(image: Path) -> str:
    parent = image.parent.name
    return parent if parent.startswith("neb_hop_") or parent == "NEB_Li7-x" else parent


def record_id(image: Path) -> str:
    return f"{hop_label(image)}/{image.name}"


def energy_records(name: str) -> list[dict]:
    rows = []
    offset_sigma = 0.0
    offset_noent = 0.0
    for hop in hop_dirs(name):
        hop_rows = []
        for image in image_dirs(hop, require_outcar=True):
            sigma, noent = last_energies(image / "OUTCAR.bz2")
            hop_rows.append({"hop": hop_label(image), "image": image.name, "path": image, "sigma": sigma, "noent": noent})
        if not hop_rows:
            continue
        first_sigma = hop_rows[0]["sigma"]
        first_noent = hop_rows[0]["noent"]
        for row in hop_rows:
            row["sigma_meV"] = offset_sigma + (row["sigma"] - first_sigma) * 1000.0
            row["noent_meV"] = offset_noent + (row["noent"] - first_noent) * 1000.0
        offset_sigma = hop_rows[-1]["sigma_meV"]
        offset_noent = hop_rows[-1]["noent_meV"]
        rows.extend(hop_rows)
    if len(rows) < 2:
        raise ValueError(f"no energy profile for {name}")
    return rows


def barrier_refs(name: str) -> dict[str, float]:
    rows = energy_records(name)
    return {
        "sigma_meV": max(row["sigma_meV"] for row in rows),
        "noent_meV": max(row["noent_meV"] for row in rows),
    }


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


def submitted_rows(block) -> list[dict] | None:
    if not isinstance(block, list) or not block:
        return None
    rows = []
    for item in block:
        if not isinstance(item, dict):
            return None
        hop = str(item.get("hop") or "").strip()
        image = str(item.get("image") or "").strip()
        if not hop or not image:
            return None
        rows.append({"hop": hop, "image": image, "raw": item})
    return rows


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def match_energy_profile(submitted, reference: list[dict]) -> tuple[bool, str]:
    rows = submitted_rows(submitted)
    if rows is None:
        return False, "path_profile must be a list of {hop, image, energy_meV}"
    by_id = {(row["hop"], row["image"]): row for row in rows}
    if len(by_id) != len(rows):
        return False, "path_profile has duplicate hop/image keys"
    missing = [(row["hop"], row["image"]) for row in reference if (row["hop"], row["image"]) not in by_id]
    extra = [key for key in by_id if key not in {(row["hop"], row["image"]) for row in reference}]
    if missing or extra:
        return False, f"image set mismatch: missing={missing[:6]} extra={extra[:6]}"
    worst_by_convention = {"sigma": 0.0, "noent": 0.0}
    for ref in reference:
        energy = finite(by_id[(ref["hop"], ref["image"])]["raw"].get("energy_meV"))
        if energy is None:
            return False, f"non-finite energy_meV at {ref['hop']}/{ref['image']}"
        deltas = {name: abs(energy - ref[f"{name}_meV"]) for name in worst_by_convention}
        if min(deltas.values()) > TOL_MEV:
            return False, f"{ref['hop']}/{ref['image']} is {min(deltas.values()):.3f} meV from both OUTCAR tags"
        for name, delta in deltas.items():
            worst_by_convention[name] = max(worst_by_convention[name], delta)
    convention = min(worst_by_convention, key=worst_by_convention.__getitem__)
    worst = worst_by_convention[convention]
    if worst > TOL_MEV:
        return False, "profile mixes sigma-zero and without-entropy energy conventions"
    return True, f"all {len(reference)} images use {convention} energies within {TOL_MEV} meV; worst {worst:.3f} meV"


def match_contact_series(submitted, reference: list[dict]) -> tuple[bool, str]:
    rows = submitted_rows(submitted)
    if rows is None:
        return False, "contact_series must be a list of {hop, image, n_pairs}"
    by_id = {(row["hop"], row["image"]): row for row in rows}
    if len(by_id) != len(rows):
        return False, "contact_series has duplicate hop/image keys"
    missing = [(row["hop"], row["image"]) for row in reference if (row["hop"], row["image"]) not in by_id]
    extra = [key for key in by_id if key not in {(row["hop"], row["image"]) for row in reference}]
    if missing or extra:
        return False, f"image set mismatch: missing={missing[:6]} extra={extra[:6]}"
    wrong = []
    for ref in reference:
        reported = by_id[(ref["hop"], ref["image"])]["raw"].get("n_pairs")
        try:
            value = int(reported)
        except (TypeError, ValueError):
            return False, f"n_pairs is not an integer at {ref['hop']}/{ref['image']}"
        if value != ref["n_pairs"]:
            wrong.append((ref["hop"], ref["image"], value, ref["n_pairs"]))
    if wrong:
        return False, f"pair-count mismatches: {wrong[:6]}"
    return True, f"all {len(reference)} images match"


def find_results(base: Path) -> Path | None:
    for cand in (base / "final" / "results.json", base / "results.json"):
        if cand.is_file():
            return cand
    hits = list(base.rglob("results.json"))
    return hits[0] if hits else None


def find_methods(base: Path) -> Path | None:
    for cand in (base / "final" / "methods.md", base / "methods.md"):
        if cand.is_file():
            return cand
    hits = list(base.rglob("methods.md"))
    return hits[0] if hits else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default="/app/final")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--print-reference", action="store_true")
    args = parser.parse_args()
    if args.print_reference:
        payload = {
            name: [
                {"hop": row["hop"], "image": row["image"], "sigma_meV": round(row["sigma_meV"], 3), "noent_meV": round(row["noent_meV"], 3)}
                for row in energy_records(name)
            ]
            for name in CARRIERS
        }
        print(json.dumps({"profiles": payload, "barriers_meV": REFERENCE_BARRIERS}, indent=2))
        return 0

    checks = []

    def add(name: str, level: str, passed: bool, detail: str) -> None:
        checks.append({"criterion": name, "level": level, "pass": bool(passed), "detail": detail})

    base = Path(args.output_dir)
    results_path = find_results(base)
    methods_path = find_methods(base)
    data = None
    if results_path is None:
        add("deliverables_complete", "L1", False, "final/results.json not found")
    else:
        try:
            data = json.loads(results_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            add("deliverables_complete", "L1", False, f"results.json unparsable: {exc}")
    profile = data.get("path_profile") if isinstance(data, dict) else None
    barriers = data.get("barriers_meV") if isinstance(data, dict) else None
    ok = (
        isinstance(profile, dict)
        and isinstance(barriers, dict)
        and all(key in profile and key in barriers for key in CARRIERS)
        and methods_path is not None
        and methods_path.stat().st_size > 0
    )
    add("deliverables_complete", "L1", ok, "results.json keys and methods.md" if ok else "missing path_profile, barriers_meV, or methods.md")

    profile_ok = True
    profile_details = {}
    if isinstance(profile, dict):
        for name in CARRIERS:
            passed, detail = match_energy_profile(profile.get(name), energy_records(name))
            profile_details[name] = {"pass": passed, "detail": detail}
            profile_ok = profile_ok and passed
    else:
        profile_ok = False
        profile_details = {"error": "path_profile missing"}
    add("hop_chain_profile", "L2", profile_ok, json.dumps(profile_details, ensure_ascii=False))

    reported = {}
    refs = {key: barrier_refs(key) for key in CARRIERS}
    if isinstance(barriers, dict):
        reported = {key: finite(barriers.get(key)) for key in CARRIERS}
    barrier_ok = profile_ok
    barrier_details = {}
    if not profile_ok:
        barrier_details["error"] = "barrier is scored only after a complete energy profile"
    for key in CARRIERS:
        value = reported.get(key)
        sigma = refs[key]["sigma_meV"]
        noent = refs[key]["noent_meV"]
        ok = value is not None and min(abs(value - sigma), abs(value - noent)) <= TOL_MEV
        if isinstance(profile, dict) and isinstance(profile.get(key), list):
            submitted_max = [finite(item.get("energy_meV")) for item in profile[key] if isinstance(item, dict)]
            submitted_max = [item for item in submitted_max if item is not None]
            if submitted_max and value is not None and abs(value - max(submitted_max)) > TOL_MEV:
                ok = False
        barrier_ok = barrier_ok and ok
        barrier_details[key] = {"reported": value, "matches_stitched_profile_max": ok}
    add("stitched_barrier", "L3", barrier_ok, json.dumps(barrier_details))

    passed = all(row["pass"] for row in checks)
    payload = {"case_id": "case-01", "pass": passed, "checks": checks}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for row in checks:
            print(f"{row['level']} {row['criterion']}: {'PASS' if row['pass'] else 'FAIL'} {row['detail']}")
        print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
