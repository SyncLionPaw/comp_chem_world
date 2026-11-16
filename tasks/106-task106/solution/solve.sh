#!/usr/bin/env bash
set -euo pipefail
: "${APP:=/app}"
REF="${BENCH16_REFERENCE_ROOT:-/run/compchembench/reference}/case04-author"
CTX="${CCB_RUN_CONTEXT_PATH:-/app/.bench16-trusted/runner-context.json}"
SOL_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 - "$REF" "$CTX" "$APP/final" "$SOL_DIR" <<'PY'
from __future__ import annotations
import json, shutil, sys
from pathlib import Path

ref, ctx_path, out = map(Path, sys.argv[1:4])
"""Minimal native-block parser and ordinary-NEB arithmetic kernel."""
import math
import re

KERNEL_NUM = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
KERNEL_IONIC = re.compile(r"(?m)^-+\s*Iteration\s+\d+\(\s*1\s*\)\s*-+")
KERNEL_TABLE = re.compile(r"POSITION\s+TOTAL-FORCE \(eV/Angst\)(.*?)(?=\n\s*NEB:|\n\s*total drift:|\n\s*FORCES:)", re.S)


class KernelEvidenceError(ValueError):
    pass


def _finite(values):
    return all(math.isfinite(x) for x in values)


def _rows3(text):
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3:
            try:
                row = [float(x) for x in fields]
            except ValueError:
                continue
            if _finite(row):
                rows.append(row)
    return rows


def parse_final_neb_block(text: str, natoms: int) -> dict:
    starts = list(KERNEL_IONIC.finditer(text))
    if not starts:
        raise KernelEvidenceError("no ionic block")
    final = text[starts[-1].start():]
    tables = KERNEL_TABLE.findall(final)
    if len(tables) != 1:
        raise KernelEvidenceError("missing or ambiguous force table")
    force_rows = []
    for line in tables[0].splitlines():
        fields = line.split()
        if len(fields) == 6:
            try:
                row = [float(x) for x in fields]
            except ValueError:
                continue
            if _finite(row):
                force_rows.append(row)
    if len(force_rows) != natoms:
        raise KernelEvidenceError("force table atom count mismatch")

    def one(pattern, label, count):
        found = re.findall(pattern, final, re.I)
        if len(found) != 1:
            raise KernelEvidenceError(f"missing or ambiguous {label}")
        values = [float(x) for x in found[0][:count]]
        if not _finite(values):
            raise KernelEvidenceError(f"non-finite {label}")
        return values

    projections = one(r"NEB:\s*projections on to tangent \(spring, REAL\)\s*" + KERNEL_NUM + r"\s+" + KERNEL_NUM, "projection", 2)
    summary = one(r"FORCES:\s*max atom, RMS\s*" + KERNEL_NUM + r"\s+" + KERNEL_NUM, "force summary", 2)
    neb = one(r"NEB:\s*forces:\s*par spring, perp REAL, dneb\s*" + KERNEL_NUM + r"\s+" + KERNEL_NUM + r"\s+" + KERNEL_NUM, "NEB summary", 3)
    distances = one(r"NEB:\s*distance to prev, next image, angle between\s*" + KERNEL_NUM + r"\s+" + KERNEL_NUM + r"\s+" + KERNEL_NUM, "distance", 3)
    tangent_match = re.search(r"NEB:\s*Tangent\s*\n\s*-+\s*\n(.*?)(?=\n\s*NEB:\s*forces:)", final, re.S)
    if tangent_match is None:
        raise KernelEvidenceError("missing tangent")
    tangents = _rows3(tangent_match.group(1))
    if len(tangents) != natoms:
        raise KernelEvidenceError("tangent atom count mismatch")
    toten = re.findall(r"free\s+energy\s+TOTEN\s*=\s*" + KERNEL_NUM, final, re.I)
    sigma = re.findall(r"energy\(sigma->0\)\s*=\s*" + KERNEL_NUM, final, re.I)
    if not toten or not sigma:
        raise KernelEvidenceError("missing energy convention")
    prev = re.findall(r"NEB:\s*the previous image is higher in energy:\s*([TF])", final)
    nxt = re.findall(r"NEB:\s*the next image is higher in energy\s*:\s*([TF])", final)
    if len(prev) != 1 or len(nxt) != 1:
        raise KernelEvidenceError("missing neighbor energy flags")
    first = re.findall(r"NEB:\s*EFIRST\s+" + KERNEL_NUM, text)
    last = re.findall(r"NEB:\s*ELAST\s+" + KERNEL_NUM, text)
    if len(first) != 1 or len(last) != 1:
        raise KernelEvidenceError("missing or ambiguous native endpoint energy policy")
    return {"positions": [r[:3] for r in force_rows], "forces": [r[3:] for r in force_rows],
            "tangent": tangents, "spring_projection": projections[0],
            "real_projection": projections[1], "par_spring": neb[0],
            "perp_real": neb[1], "dneb": neb[2], "distance_prev": distances[0],
            "distance_next": distances[1], "angle_deg": distances[2],
            "summary_max": summary[0], "summary_rms": summary[1],
            "toten": float(toten[-1]), "sigma0": float(sigma[-1]),
            "efirst": float(first[0]), "elast": float(last[0]),
            "higher_prev": prev[0] == "T", "higher_next": nxt[0] == "T",
            "optimizer_marker": "OPT: skip step - force has converged" in final}


def force_metrics(block: dict, tangent, climbing=False) -> dict:
    flat_tau = [float(x) for row in block["tangent"] for x in row]
    flat_f = [float(x) for row in block["forces"] for x in row]
    norm_tau = math.sqrt(sum(x*x for x in flat_tau))
    if len(flat_tau) != len(flat_f) or norm_tau <= 1e-14 or not _finite(flat_tau + flat_f):
        raise KernelEvidenceError("force/tangent shape or finite-value error")
    tau = [x / norm_tau for x in flat_tau]
    q = sum(f*t for f,t in zip(flat_f,tau))
    spring = 0.0 if climbing else float(block["spring_projection"])
    neb = [f-q*t+spring*t for f,t in zip(flat_f,tau)]
    atoms = [math.sqrt(sum(x*x for x in neb[i:i+3])) for i in range(0,len(neb),3)]
    physical = [math.sqrt(sum(x*x for x in flat_f[i:i+3])) for i in range(0,len(flat_f),3)]
    perp = math.sqrt(sum((f-q*t)**2 for f,t in zip(flat_f,tau)))
    return {"q": q, "native_projection_delta": q-float(block["real_projection"]),
            "perp_norm": perp, "neb_forces": [neb[i:i+3] for i in range(0,len(neb),3)],
            "max_atom": max(atoms), "rms_atom": math.sqrt(sum(x*x for x in atoms)/len(atoms)),
            "atomic_true_max": max(physical)}


"""Author-method ordinary-NEB parser and same-block consistency audit.

This parser deliberately treats the five image cells independently.  It checks
printed native tangent/force arithmetic and reports cell-aware geometry facts;
it does not label a finite ordinary-NEB profile a converged saddle.
"""

import bz2
import hashlib
import json
import math
import re
from pathlib import Path


NUM = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
IONIC = re.compile(r"(?m)^-+\s*Iteration\s+(\d+)\(\s*1\s*\)\s*-+")
NORMAL = "General timing and accounting informations for this job:"


class ScienceError(ValueError):
    pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outcar_text(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix == ".bz2":
        raw = bz2.decompress(raw)
    return raw.decode("latin1", "replace")


def parse_poscar(path: Path) -> dict:
    rows = Path(path).read_text(errors="replace").splitlines()
    if len(rows) < 8:
        raise ScienceError(f"truncated POSCAR: {path}")
    scale = float(rows[1].split()[0])
    cell = [[scale * float(x) for x in rows[i].split()[:3]] for i in (2, 3, 4)]
    species, counts = rows[5].split(), [int(v) for v in rows[6].split()]
    if len(species) != len(counts):
        raise ScienceError("POSCAR species/count mismatch")
    idx = 7
    if rows[idx].strip().lower().startswith("s"):
        idx += 1
    direct = rows[idx].strip().lower().startswith("d")
    idx += 1
    coords, symbols = [], []
    for symbol, count in zip(species, counts):
        for row in rows[idx:idx + count]:
            coords.append([float(x) for x in row.split()[:3]])
            symbols.append(symbol)
        idx += count
    if len(coords) != sum(counts):
        raise ScienceError("truncated POSCAR coordinate table")
    if direct:
        coords = [[sum(v[j] * cell[j][k] for j in range(3)) for k in range(3)]
                  for v in coords]
    return {"cell_A": cell, "positions_cartesian_A": coords,
            "symbols": symbols, "counts": dict(zip(species, counts))}


def parse_image_outcar(path: Path, natoms: int = 177) -> dict:
    text = _outcar_text(path)
    markers = list(IONIC.finditer(text))
    blocks = {}
    for idx, marker in enumerate(markers):
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        chunk = text[marker.start():end]
        try:
            block = parse_final_neb_block(
                "NEB: EFIRST 0.000000\nNEB: ELAST 0.000000\n" + chunk, natoms)
        except KernelEvidenceError:
            continue
        # EDIFF is a per-electronic-block terminal, not inferred from NSW or tail.
        if "aborting loop because EDIFF is reached" not in chunk:
            continue
        e0 = re.findall(r"energy\(sigma->0\)\s*=\s*" + NUM, chunk, re.I)
        if not e0:
            continue
        block.update(step=int(marker.group(1)), sigma0_eV=float(e0[-1]),
                     scf_converged=True,
                     source_block_sha256=hashlib.sha256(chunk.encode("latin1")).hexdigest())
        blocks[block["step"]] = block
    if not markers:
        raise ScienceError(f"no ionic steps in {path}")
    return {"blocks": blocks, "ionic_steps": [int(m.group(1)) for m in markers],
            "normal_termination": NORMAL in text,
            "native_version": _version(text), "paw_titles": _paw_titles(text), "sha256": sha(path),
            "raw_bytes": path.stat().st_size, "text": text}


def audit_native_method(text: str, expected: dict[str, str]) -> dict:
    """Check method settings echoed by VASP/VTST against the authored INCAR."""
    def number(pattern: str, label: str) -> float:
        match = re.search(pattern, text, re.I | re.M)
        if not match:
            raise ScienceError(f"native OUTCAR does not report {label}")
        return float(match.group(1).replace("D", "E").replace("d", "e"))

    values = {
        "ENCUT": number(r"^\s*ENCUT\s*=\s*(" + NUM + r")\s+eV\b", "ENCUT"),
        "EDIFF": number(r"^\s*EDIFF\s*=\s*(" + NUM + r")\b", "EDIFF"),
        "EDIFFG": number(r"^\s*EDIFFG\s*=\s*(" + NUM + r")\b", "EDIFFG"),
        "NSW": number(r"^\s*NSW\s*=\s*(\d+)\b", "NSW"),
        "IBRION": number(r"^\s*IBRION\s*=\s*(\d+)\b", "IBRION"),
        "ISIF": number(r"^\s*ISIF\s*=\s*(\d+)\b", "ISIF"),
        "ISPIN": number(r"^\s*ISPIN\s*=\s*(\d+)\b", "ISPIN"),
        "ISMEAR": number(r"^\s*ISMEAR\s*=\s*(-?\d+)\b", "ISMEAR"),
        "SIGMA": number(r"^\s*ISMEAR\s*=.*?SIGMA\s*=\s*(" + NUM + r")\b", "SIGMA"),
        "POTIM": number(r"^\s*POTIM\s*=\s*(" + NUM + r")\b", "POTIM"),
        "SPRING": number(r"^\s*NEB:\s*SPRING\s+(" + NUM + r")\b", "VTST SPRING"),
        "IMAGES": number(r"^\s*OPT:\s*\w+,\s*IMAGES\s+(\d+)\b", "VTST IMAGES"),
    }
    if not re.search(r"^\s*PREC\s*=\s*accura\w*\b", text, re.I | re.M):
        raise ScienceError("native OUTCAR does not report authored PREC=Accurate")
    if not re.search(r"^\s*LEXCH\s*=\s*PE\b", text, re.I | re.M):
        raise ScienceError("native OUTCAR does not identify the authored PBE exchange functional")
    if not re.search(r"^\s*NEB:\s*LCLIMB\s+F\b", text, re.I | re.M):
        raise ScienceError("native OUTCAR does not report ordinary NEB LCLIMB=False")
    if not re.search(r"^\s*OPT:\s*Using\s+LBFGS\s+optimizer\b", text, re.I | re.M):
        raise ScienceError("native OUTCAR does not report the authored IOPT=1 LBFGS optimizer")
    expected_values = {
        "ENCUT": float(expected["ENCUT"]), "EDIFF": float(expected["EDIFF"]),
        "EDIFFG": float(expected["EDIFFG"]), "NSW": float(expected["NSW"]),
        "IBRION": float(expected["IBRION"]), "ISIF": float(expected["ISIF"]),
        "ISPIN": float(expected["ISPIN"]), "ISMEAR": float(expected["ISMEAR"]),
        "SIGMA": float(expected["SIGMA"]), "POTIM": float(expected["POTIM"]),
        "SPRING": float(expected["SPRING"]), "IMAGES": float(expected["IMAGES"]),
    }
    for key, value in expected_values.items():
        if not math.isclose(values[key], value, rel_tol=0, abs_tol=1e-8):
            raise ScienceError(f"native OUTCAR {key}={values[key]} differs from authored {value}")
    return {"echoed_settings": values, "prec": "Accurate", "lexch": "PE",
            "iopt": 1, "lclimb": False}


def _version(text: str) -> str | None:
    match = re.search(r"vasp\.([0-9][^\s]*)", text)
    return match.group(1) if match else None


def _paw_titles(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", match).strip()
            for match in re.findall(r"(?im)^\s*TITEL\s*=\s*(.+?)\s*$", text)]


def _flatten(rows):
    return [v for row in rows for v in row]


def _norm(values):
    return math.sqrt(sum(float(x) ** 2 for x in values))


def audit_block(block: dict) -> dict:
    tau = _flatten(block["tangent"])
    norm_tau = _norm(tau)
    if not math.isfinite(norm_tau) or norm_tau <= 1e-14:
        raise ScienceError("native tangent is degenerate")
    metrics = force_metrics(block, tau, climbing=False)
    # Tolerances follow the printed precision of native fields; they are not
    # physical DFT uncertainty allowances.
    n3 = 3 * len(block["forces"])
    force_ulp = 0.5e-6
    tau_ulp = 0.5e-5
    df = math.sqrt(n3) * force_ulp
    dt = math.sqrt(n3) * tau_ulp
    qtol = _norm(_flatten(block["forces"])) * dt + df + df * dt + force_ulp
    perp_tol = df + abs(metrics["q"]) * dt + qtol + force_ulp
    summary_tol = math.sqrt(3) * force_ulp + abs(metrics["q"]) * math.sqrt(3) * tau_ulp + qtol + force_ulp
    tangent_unit_delta = norm_tau - 1.0
    checks = {
        "native_tangent_l2": norm_tau,
        "native_tangent_unit_delta": tangent_unit_delta,
        "native_projection_recomputed_eV_A": metrics["q"],
        "native_projection_printed_eV_A": block["real_projection"],
        "native_projection_delta_eV_A": metrics["native_projection_delta"],
        "native_perp_norm_recomputed_eV_A": metrics["perp_norm"],
        "native_perp_norm_printed_eV_A": block["perp_real"],
        "native_neb_max_recomputed_eV_A": metrics["max_atom"],
        "native_neb_max_printed_eV_A": block["summary_max"],
        "physical_force_max_eV_A": metrics["atomic_true_max"],
        "precision_bounds": {"projection_eV_A": qtol, "perp_eV_A": perp_tol,
                             "summary_eV_A": summary_tol},
        "projection_consistent": abs(metrics["native_projection_delta"]) <= qtol,
        "perp_consistent": abs(metrics["perp_norm"] - block["perp_real"]) <= perp_tol,
        "summary_consistent": abs(metrics["max_atom"] - block["summary_max"]) <= summary_tol,
        "tangent_normalized": abs(tangent_unit_delta) <= math.sqrt(n3) * tau_ulp + 1e-6,
        "ordinary_neb": True,
        "spring_projection_recomputed_eV_A": 5.0 * (block["distance_next"] - block["distance_prev"]),
        "spring_distance_delta_eV_A": block["spring_projection"] -
            5.0 * (block["distance_next"] - block["distance_prev"]),
        "spring_consistent": abs(block["spring_projection"] -
            5.0 * (block["distance_next"] - block["distance_prev"])) <= 6e-6,
    }
    checks["same_block_arithmetic_consistent"] = all(checks[k] for k in (
        "projection_consistent", "perp_consistent", "summary_consistent", "tangent_normalized",
        "spring_consistent"))
    return checks


def parse_endpoint(path: Path, poscar: Path) -> dict:
    text = _outcar_text(path)
    e0 = re.findall(r"energy\(sigma->0\)\s*=\s*" + NUM, text, re.I)
    toten = re.findall(r"free\s+energy\s+TOTEN\s*=\s*" + NUM, text, re.I)
    if not e0 or not toten:
        raise ScienceError(f"endpoint lacks both energy conventions: {path}")
    struct = parse_poscar(poscar)
    return {"role": "HISTORICAL_RELAXED_ENDPOINT_UPSTREAM",
            "sigma0_eV": float(e0[-1]), "toten_eV": float(toten[-1]),
            "native_version": _version(text), "paw_titles": _paw_titles(text),
            "normal_termination": NORMAL in text,
            "poscar_sha256": sha(poscar), "outcar_sha256": sha(path),
            "cell_A": struct["cell_A"], "counts": struct["counts"]}


def _cell_delta(a, b):
    return max(abs(x - y) for ra, rb in zip(a, b) for x, y in zip(ra, rb))


def _inverse(cell):
    a, b, c = cell
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    if abs(det) < 1e-12:
        raise ScienceError("singular image cell")
    return [[(b[1]*c[2]-b[2]*c[1])/det, (a[2]*c[1]-a[1]*c[2])/det, (a[1]*b[2]-a[2]*b[1])/det],
            [(b[2]*c[0]-b[0]*c[2])/det, (a[0]*c[2]-a[2]*c[0])/det, (a[2]*b[0]-a[0]*b[2])/det],
            [(b[0]*c[1]-b[1]*c[0])/det, (a[1]*c[0]-a[0]*c[1])/det, (a[0]*b[1]-a[1]*b[0])/det]]


def _mic_delta(a, b, cell):
    delta = [b[k] - a[k] for k in range(3)]
    center = [round(x) for x in delta]
    best, best2 = None, math.inf
    for i in range(center[0] - 1, center[0] + 2):
        for j in range(center[1] - 1, center[1] + 2):
            for k in range(center[2] - 1, center[2] + 2):
                frac = [delta[0] - i, delta[1] - j, delta[2] - k]
                cart = [sum(frac[m] * cell[m][n] for m in range(3)) for n in range(3)]
                norm2 = sum(x * x for x in cart)
                if norm2 < best2:
                    best, best2 = cart, norm2
    return best


def _geometry_tangent_comparison(previous, previous_cell, current, current_cell,
                                 following, following_cell, previous_energy,
                                 current_energy, following_energy, higher_prev,
                                 higher_next, cell):
    """Compare native tangent with one explicit per-image-cell geometry metric.

    Each image is converted from its own Cartesian coordinates to fractional
    coordinates in its own cell. Neighbor fractional coordinates are then
    mapped into the current image's cell before MIC displacements are formed.
    This is a stated comparison convention, not a claim about VTST internals.
    """
    def fractional(points, own_cell):
        inverse = _inverse(own_cell)
        return [[sum(float(p[j]) * inverse[j][k] for j in range(3)) for k in range(3)]
                for p in points]
    prev_frac = fractional(previous, previous_cell)
    curr_frac = fractional(current, current_cell)
    next_frac = fractional(following, following_cell)
    forward = [_mic_delta(a, b, cell) for a, b in zip(curr_frac, next_frac)]
    backward = [_mic_delta(a, b, cell) for a, b in zip(prev_frac, curr_frac)]
    if higher_next and not higher_prev:
        vector = [x for row in forward for x in row]
    elif higher_prev and not higher_next:
        vector = [x for row in backward for x in row]
    else:
        dp, dm = following_energy - current_energy, previous_energy - current_energy
        high, low = max(abs(dp), abs(dm)), min(abs(dp), abs(dm))
        wp = high if following_energy > previous_energy else low
        wm = low if following_energy > previous_energy else high
        vector = [wp * f + wm * b for fr, br in zip(forward, backward) for f, b in zip(fr, br)]
    norm = _norm(vector)
    if norm <= 1e-14:
        raise ScienceError("degenerate per-image-cell geometric tangent")
    return [x / norm for x in vector]


def _asset_root() -> Path:
    here = Path(sys.argv[4]).resolve()
    candidates = (here, here.parent / "environment" / "assets", Path("/app/assets"))
    for candidate in candidates:
        if (candidate / "neb" / "INCAR").is_file():
            return candidate
    raise ScienceError("frozen public asset root is unavailable")


def build_result(evidence: Path) -> dict:
    root = Path(evidence)
    neb = root / "neb"
    positions = {image: parse_poscar(neb / image / "POSCAR") for image in ("00", "01", "02", "03", "04")}
    expected_counts = {"Li": 41, "Ti": 40, "O": 96}
    expected_symbols = ["Li"] * 41 + ["Ti"] * 40 + ["O"] * 96
    expected_paw_titles = ["PAW_PBE Li 17Jan2003", "PAW_PBE Ti 08Apr2002", "PAW_PBE O 08Apr2002"]
    for image, structure in positions.items():
        if structure["counts"] != expected_counts or structure["symbols"] != expected_symbols:
            raise ScienceError(f"image {image}: wrong authored species/count/order")
    images = {image: parse_image_outcar(neb / image / "OUTCAR") for image in ("01", "02", "03")}
    for image, parsed in images.items():
        if parsed["paw_titles"] != expected_paw_titles:
            raise ScienceError(f"active image {image} does not identify the authored standard Li/Ti/O PAWs")
    common_available = sorted(set.intersection(*(set(images[i]["blocks"]) for i in images)))
    common = common_available
    if len(common) < 4:
        raise ScienceError(f"only {len(common)} common complete SCF/force steps; need four")
    assets = _asset_root()
    method = audit_author_method(neb / "INCAR", assets / "neb" / "INCAR", assets / "neb" / "KPOINTS")
    native_methods = {image: audit_native_method(parsed["text"], method["native_method_without_nsw"] |
                       {"NSW": str(method["native_nsw"])}) for image, parsed in images.items()}
    provenance = json.loads((assets / "input-manifest.json").read_text(encoding="utf-8"))
    if (provenance.get("combined_standard_paw_sha256") !=
            "5fc9d862e89819d167ba022ff08c36bfb15a0fb7e01ba74935952a4b6cd490f2"
            or provenance.get("standard_ti_paw_sha256") !=
            "9f765a064614b02ad1ea9b6ae5fc727c54698bfd03536120e34f939afcefc05e"):
        raise ScienceError("author archive standard-Ti PAW identity pin mismatch")
    input_incar = (neb / "INCAR").read_text(errors="replace")
    native_nsw = method["native_nsw"]
    if native_nsw == 4:
        common = common[:4]
    endpoints = {image: parse_endpoint(root / "upstream" / image / "OUTCAR.bz2",
                                        root / "upstream" / image / "CONTCAR")
                 for image in ("00", "04")}
    for image, parsed in endpoints.items():
        if parsed["paw_titles"] != expected_paw_titles:
            raise ScienceError(f"upstream endpoint {image} does not identify the authored standard Li/Ti/O PAWs")
    records = []
    for step in common:
        row = {"step": step, "images": {}}
        for image in ("01", "02", "03"):
            block = images[image]["blocks"][step]
            previous_image, next_image = f"{int(image) - 1:02d}", f"{int(image) + 1:02d}"
            previous_block = images.get(previous_image, {}).get("blocks", {}).get(step)
            next_block = images.get(next_image, {}).get("blocks", {}).get(step)
            previous_positions = previous_block["positions"] if previous_block else positions[previous_image]["positions_cartesian_A"]
            next_positions = next_block["positions"] if next_block else positions[next_image]["positions_cartesian_A"]
            previous_energy = previous_block["toten"] if previous_block else block["efirst"]
            next_energy = next_block["toten"] if next_block else block["elast"]
            geometry_tau = _geometry_tangent_comparison(
                previous_positions, positions[previous_image]["cell_A"],
                block["positions"], positions[image]["cell_A"],
                next_positions, positions[next_image]["cell_A"],
                previous_energy, block["toten"], next_energy,
                block["higher_prev"], block["higher_next"], positions[image]["cell_A"])
            native_tau = _flatten(block["tangent"])
            cosine = sum(a * b for a, b in zip(geometry_tau, native_tau)) / _norm(native_tau)
            row["images"][image] = {
                "toten_eV": block["toten"], "sigma0_eV": block["sigma0_eV"],
                "positions_cartesian_A": block["positions"],
                "physical_forces_eV_A": block["forces"],
                "native_tangent_cartesian_3N": block["tangent"],
                "native_spring_projection_eV_A": block["spring_projection"],
                "native_real_projection_eV_A": block["real_projection"],
                "native_perp_real_eV_A": block["perp_real"],
                "native_neb_max_atom_eV_A": block["summary_max"],
                "native_neb_rms_atom_eV_A": block["summary_rms"],
                "geometry_tangent_metric_comparison": {
                    "metric_id": "own-fractional-cells-mapped-to-current-cell-mic-v1",
                    "coordinate_convention": "each image Cartesian structure to its own fractional cell, then map neighbor fractions into current-image cell and apply MIC",
                    "cosine_to_native_tangent": cosine,
                    "angle_to_native_tangent_deg": math.degrees(math.acos(max(-1.0, min(1.0, cosine)))),
                    "directional_cosine": cosine,
                },
                "audit": audit_block(block),
                "native_block_sha256": block["source_block_sha256"],
            }
        row["same_block_arithmetic_consistent"] = all(
            row["images"][i]["audit"]["same_block_arithmetic_consistent"] for i in ("01", "02", "03"))
        records.append(row)
    last = records[-1]
    profile = {"00": endpoints["00"]["sigma0_eV"], **{
        i: last["images"][i]["sigma0_eV"] for i in ("01", "02", "03")},
        "04": endpoints["04"]["sigma0_eV"]}
    toten_profile = {"00": endpoints["00"]["toten_eV"], **{
        i: last["images"][i]["toten_eV"] for i in ("01", "02", "03")},
        "04": endpoints["04"]["toten_eV"]}
    highest = max(profile, key=profile.get)
    cells = {image: positions[image]["cell_A"] for image in positions}
    per_image_cell_delta = {i: _cell_delta(cells[i], cells["00"]) for i in ("01", "02", "03", "04")}
    for image in ("00", "04"):
        if not endpoints[image]["normal_termination"]:
            raise ScienceError(f"historical endpoint {image} did not terminate normally")
    if any(not images[i]["normal_termination"] for i in images):
        raise ScienceError("one or more historical active images lack normal termination")
    return {
        "schema": "case04-author-neb-v3-results/v1", "case_id": "case-04-author-neb-v3",
        "source": {"native_nsw": native_nsw,
                   "active_native_versions": {
                       i: images[i]["native_version"] for i in images}},
        "endpoint_upstream": endpoints,
        "input_audit": {"native_method": method, "active_native_method_audit": native_methods,
            "paw_identity": {"combined_standard_paw_sha256": provenance["combined_standard_paw_sha256"],
                             "standard_ti_paw_sha256": provenance["standard_ti_paw_sha256"],
                             "native_titels": {"active_images": {i: images[i]["paw_titles"] for i in images},
                                                "upstream_endpoints": {i: endpoints[i]["paw_titles"] for i in endpoints}},
                             "identity_source": "native OUTCAR TITEL and pinned author archive provenance; PAW bytes are not staged"},
            "lclimb_false": True, "preserved_original_cells": True,
            "cell_max_delta_from_00_A": per_image_cell_delta,
            "common_cells": all(value <= 1e-8 for value in per_image_cell_delta.values())},
        "common_complete_steps": common, "all_common_complete_steps_available": common_available,
        "additional_common_complete_steps_not_in_fresh_prefix": common_available[len(common):],
        "incomplete_later_ionic_steps": {i: sorted(set(images[i]["ionic_steps"]) - set(images[i]["blocks"]))
                                           for i in images},
        "common_step_records": records,
        "analysis": {"energy_convention": "sigma0_eV; TOTEN retained separately per image",
            "energy_fields": {"primary": "sigma0_eV", "secondary": "toten_eV"},
            "scope_flags": {"finite_sampled_path_only": True,
                             "cross_version_uncertainty_bound_asserted": False,
                             "geometric_metric_claims_native_vtst_tangent": False},
            "version_scope": {"active_images": {i: images[i]["native_version"] for i in images},
                              "upstream_endpoints": {i: endpoints[i]["native_version"] for i in endpoints},
                              "cross_version_energy_comparison": "reported as supplied; no cross-version numerical uncertainty tolerance is asserted"},
            "same_step_sigma0_profile_eV": profile, "same_step_toten_profile_eV": toten_profile,
            "highest_sampled_image": highest,
            "finite_profile_peak_eV_above_endpoint00": profile[highest] - profile["00"],
            "endpoint_directional_delta_eV": profile["04"] - profile["00"],
            "all_native_same_block_force_audits_consistent": all(r["same_block_arithmetic_consistent"] for r in records),
            "ordinary_neb_not_climbing_image": True,
            "bounded_experiment_complete": len(common) >= 4,
            "last_common_step_force_metrics": {i: {
                "recomputed_neb_max_atom_eV_A": last["images"][i]["audit"]["native_neb_max_recomputed_eV_A"],
                "authored_ediffg_threshold_eV_A": 0.05,
                "below_threshold": last["images"][i]["audit"]["native_neb_max_recomputed_eV_A"] <= 0.05,
                "optimizer_force_converged_marker": images[i]["blocks"][common[-1]]["optimizer_marker"]}
                for i in ("01", "02", "03")},
            "current_neb_force_converged": all(
                last["images"][i]["audit"]["native_neb_max_recomputed_eV_A"] <= 0.05 and
                images[i]["blocks"][common[-1]]["optimizer_marker"] for i in ("01", "02", "03")),
            "per_image_cell_max_delta_from_00_A": per_image_cell_delta,
            "method_and_cell_scope": "Ordinary NEB with the authors' five unmodified POSCAR cells; this output describes a finite sampled path. The geometric tangent comparison maps each structure through its own fractional cell into the current image cell; it is a stated review metric, not a claim that VTST used this variable-cell mapping."},
    }


def _int_setting(text: str, key: str) -> int:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(\d+)\b", text)
    if not match:
        raise ScienceError(f"missing integer method setting {key}")
    return int(match.group(1))


def parse_incar(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        body = line.split("!")[0].split("#")[0].strip()
        if not body or "=" not in body:
            continue
        key, value = body.split("=", 1)
        key, value = key.strip().upper(), value.strip().upper()
        if key in values:
            raise ScienceError(f"duplicate INCAR setting {key}")
        values[key] = value
    return values


def audit_author_method(native_incar: Path, frozen_incar: Path, frozen_kpoints: Path) -> dict:
    native = parse_incar(Path(native_incar).read_text(errors="replace"))
    frozen = parse_incar(Path(frozen_incar).read_text(errors="replace"))
    nsw = native.pop("NSW", None)
    baseline = frozen.pop("NSW", None)
    if native != frozen:
        raise ScienceError("native method differs from the frozen authored method beyond NSW")
    if nsw not in {"4", "200"} or baseline != "4":
        raise ScienceError("only the reviewed fresh NSW=4 and historical NSW=200 modes are allowed")
    required = {"IMAGES": 3, "IBRION": 3, "IOPT": 1, "SPRING": -5,
                "POTIM": 0, "ISIF": 2, "ENCUT": 520, "EDIFF": 1e-5,
                "EDIFFG": -0.05, "ISPIN": 2, "ISMEAR": 0, "SIGMA": 0.05,
                "NPAR": 4}
    for key, value in required.items():
        actual = native.get(key)
        try:
            matches = actual is not None and math.isclose(float(actual), float(value), rel_tol=0, abs_tol=1e-12)
        except ValueError:
            matches = False
        if not matches:
            raise ScienceError(f"authored NEB method identity mismatch for {key}: {actual}")
    if native.get("LCLIMB", "").strip(".") not in {"FALSE", "F"}:
        raise ScienceError("authored ordinary NEB requires LCLIMB=False")
    if native.get("KPAR", "1") != "1":
        raise ScienceError("parallel layout differs from the frozen KPAR=1 default")
    kp = Path(frozen_kpoints).read_text(errors="replace").splitlines()
    compact = " ".join(line.strip() for line in kp if line.strip())
    if not re.search(r"Gamma\s+1\s+1\s+1", compact, re.I):
        raise ScienceError("frozen KPOINTS are not the authored Gamma 1x1x1 mesh")
    return {"native_nsw": int(nsw), "authored_method_matches": True,
            "native_method_without_nsw": native,
            "fresh_method_nsw": int(baseline), "kpoints_gamma_1x1x1": True}


ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
if (ctx.get("authority") != "runner_host_observed"
        or ctx.get("case_id") != "case-04-author-neb-v3"
        or ctx.get("execution_mode") != "HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY"
        or ctx.get("source_is_historical") is not True
        or ctx.get("source_job_id") is not None
        or ctx.get("archive_source_id") != "author-neb-hop1-archive"
        or ctx.get("archive_sha256") != "7bdcd8aa4e6e12d388af5193ac8b24ddaedf49e33c8e5f9eb49ca9e1ca6ae404"):
    raise SystemExit("Oracle requires the host-protected author-archive replay context")

evidence = out / "evidence"
neb = evidence / "neb"
neb.mkdir(parents=True, exist_ok=True)
for name in ("INCAR", "KPOINTS"):
    source = ref / "neb" / name
    if not source.is_file():
        raise SystemExit(f"missing protected author input {source}")
    shutil.copyfile(source, neb / name)
for image in ("00", "01", "02", "03", "04"):
    source = ref / "neb" / image
    dest = neb / image
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("POSCAR", "CONTCAR", "OUTCAR"):
        candidate = source / name
        if candidate.is_file():
            shutil.copyfile(candidate, dest / name)
    if not (dest / "POSCAR").is_file():
        raise SystemExit(f"missing original authored image POSCAR {image}")
for image in ("00", "04"):
    source = ref / "upstream" / image
    dest = evidence / "upstream" / image
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("CONTCAR", "OUTCAR.bz2"):
        candidate = source / name
        if not candidate.is_file():
            raise SystemExit(f"missing upstream endpoint evidence {image}/{name}")
        shutil.copyfile(candidate, dest / name)

result = build_result(evidence)
result["source"].update({"job_id": None, "historical": True,
                         "archive_source_id": ctx["archive_source_id"],
                         "archive_sha256": ctx["archive_sha256"],
                         "execution_mode": ctx["execution_mode"]})
out.mkdir(parents=True, exist_ok=True)
(out / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
PY
