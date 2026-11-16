#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including results.json).
# L2 Execution: Bind native run evidence to the trusted runner context and capture proof.
# L3 Science: Assess a five-image Li5+x ordinary-NEB path.
from __future__ import annotations
import json, os, sys
from pathlib import Path

REFS = json.loads(Path(__file__).with_name("refs.json").read_text(encoding="utf-8"))

"""Verify Case 04 claims by rebuilding them from host-bound native outputs."""

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys

RUNNER_CONTEXT_PATH = Path("/app/.bench16-trusted/runner-context.json")
CAPTURE_PROOF_PATH = Path("/app/.bench16-trusted/capture-proof.json")

def _trusted_context_bytes(path):
    path=Path(path)
    runner_path=os.environ.get('CCB_RUN_CONTEXT_PATH')
    expected=os.environ.get('CCB_RUN_CONTEXT_SHA256')
    if path.is_symlink() or not path.is_file(): raise ContextError('trusted runner context is not a regular file')
    raw=path.read_bytes()
    if runner_path is not None or expected is not None:
        if not runner_path or not expected or str(path)!=runner_path or not re.fullmatch(r'[0-9a-f]{64}',str(expected)):
            raise ContextError('runner context pin is malformed')
        if hashlib.sha256(raw).hexdigest()!=expected: raise ContextError('trusted runner context digest mismatch')
        return raw
    if path != RUNNER_CONTEXT_PATH:
        raise ContextError('runner did not provide a pinned protected context')
    proof_path=CAPTURE_PROOF_PATH
    if proof_path.is_symlink() or not proof_path.is_file():
        raise ContextError('protected capture proof is missing')
    try:
        proof=json.loads(proof_path.read_text(encoding='utf-8'))
        context=json.loads(raw.decode('utf-8'))
    except Exception as exc:
        raise ContextError('protected context or capture proof is malformed') from exc
    if (not isinstance(proof,dict) or proof.get('schema')!='compchembench.bench16-capture-proof/v1'
            or proof.get('context_sha256')!=hashlib.sha256(raw).hexdigest()
            or proof.get('attempt_id')!=context.get('attempt_id')
            or proof.get('task')!=context.get('task')
            or proof.get('case_id')!=context.get('case_id')
            or proof.get('execution_mode')!=context.get('execution_mode')):
        raise ContextError('protected capture proof does not bind this context')
    return raw



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


def parse_image_outcar(path: Path, natoms: int = REFS["atom_count"]) -> dict:
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
    force_ulp = REFS["printed_force_ulp"]
    tau_ulp = REFS["printed_tangent_ulp"]
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
            5.0 * (block["distance_next"] - block["distance_prev"])) <= REFS["spring_distance_tolerance"],
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
    here = Path(__file__).resolve().parent
    candidates = (here, here.parent / "environment" / "assets", Path("/app/assets"))
    for candidate in candidates:
        if (candidate / "neb" / "INCAR").is_file():
            return candidate
    raise ScienceError("frozen public asset root is unavailable")


def build_result(evidence: Path, paw_identity: dict | None = None) -> dict:
    root = Path(evidence)
    neb = root / "neb"
    positions = {image: parse_poscar(neb / image / "POSCAR") for image in ("00", "01", "02", "03", "04")}
    expected_counts = REFS["composition"]
    expected_symbols = ["Li"] * 41 + ["Ti"] * 40 + ["O"] * 96
    expected_paw_titles = REFS["paw_titles"]
    for image, structure in positions.items():
        if structure["counts"] != expected_counts or structure["symbols"] != expected_symbols:
            raise ScienceError(f"image {image}: wrong authored species/count/order")
    images = {image: parse_image_outcar(neb / image / "OUTCAR") for image in ("01", "02", "03")}
    for image, parsed in images.items():
        if parsed["paw_titles"] != expected_paw_titles:
            raise ScienceError(f"active image {image} does not identify the authored standard Li/Ti/O PAWs")
    common_available = sorted(set.intersection(*(set(images[i]["blocks"]) for i in images)))
    common = common_available
    if len(common) < REFS["minimum_common_steps"]:
        raise ScienceError(f"only {len(common)} common complete SCF/force steps; need four")
    assets = _asset_root()
    method = audit_author_method(neb / "INCAR", assets / "neb" / "INCAR", assets / "neb" / "KPOINTS")
    native_methods = {image: audit_native_method(parsed["text"], method["native_method_without_nsw"] |
                       {"NSW": str(method["native_nsw"])}) for image, parsed in images.items()}
    provenance = json.loads((assets / "input-manifest.json").read_text(encoding="utf-8"))
    if (provenance.get("combined_standard_paw_sha256") !=
            REFS["combined_standard_paw_sha256"]
            or provenance.get("standard_ti_paw_sha256") !=
            REFS["standard_ti_paw_sha256"]):
        raise ScienceError("author archive standard-Ti PAW identity pin mismatch")
    input_incar = (neb / "INCAR").read_text(errors="replace")
    native_nsw = method["native_nsw"]
    if native_nsw == REFS["fresh_nsw"]:
        common = common[:REFS["fresh_nsw"]]
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
    result = {
        "schema": "case04-author-neb-v3-results/v1", "case_id": REFS["case_id"],
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
            "bounded_experiment_complete": len(common) >= REFS["minimum_common_steps"],
            "last_common_step_force_metrics": {i: {
                "recomputed_neb_max_atom_eV_A": last["images"][i]["audit"]["native_neb_max_recomputed_eV_A"],
                "authored_ediffg_threshold_eV_A": REFS["force_threshold_eV_A"],
                "below_threshold": last["images"][i]["audit"]["native_neb_max_recomputed_eV_A"] <= REFS["force_threshold_eV_A"],
                "optimizer_force_converged_marker": images[i]["blocks"][common[-1]]["optimizer_marker"]}
                for i in ("01", "02", "03")},
            "current_neb_force_converged": all(
                last["images"][i]["audit"]["native_neb_max_recomputed_eV_A"] <= REFS["force_threshold_eV_A"] and
                images[i]["blocks"][common[-1]]["optimizer_marker"] for i in ("01", "02", "03")),
            "per_image_cell_max_delta_from_00_A": per_image_cell_delta,
            "method_and_cell_scope": "Ordinary NEB with the authors' five unmodified POSCAR cells; this output describes a finite sampled path. The geometric tangent comparison maps each structure through its own fractional cell into the current image cell; it is a stated review metric, not a claim that VTST used this variable-cell mapping."},
    }
    if paw_identity is not None:
        display = {k: paw_identity[k] for k in ("policy", "source_id", "titles", "combined_sha256",
                                                "compressed_sha256", "archive_sha256", "archive_member")
                   if k in paw_identity}
        if isinstance(paw_identity.get("components"), list):
            display["components"] = [{k: row[k] for k in ("element", "title", "sha256", "source_path", "component_index") if k in row}
                                     for row in paw_identity["components"]]
        result["input_audit"]["paw_identity"]["active_run_source"] = display
        result["input_audit"]["paw_identity"]["historical_endpoints_source"] = {
            "role": "HISTORICAL_RELAXED_ENDPOINT_UPSTREAM",
            "source_id": REFS["archive_source_id"],
            "archive_sha256": REFS["archive_sha256"],
            "combined_standard_paw_sha256": REFS["combined_standard_paw_sha256"],
            "native_titels": {i: endpoints[i]["paw_titles"] for i in endpoints},
            "native_versions": {i: endpoints[i]["native_version"] for i in endpoints}}
        if paw_identity.get("policy") == REFS["qualified_hpc_paw"]["policy"]:
            analysis = result["analysis"]
            analysis.update({
                "profile_comparability": "INCOMPARABLE/NOT_ESTABLISHED",
                "mixed_source_profile_claimed": False,
                "same_source_sigma0_profile_eV": {i: last["images"][i]["sigma0_eV"] for i in ("01", "02", "03")},
                "same_source_toten_profile_eV": {i: last["images"][i]["toten_eV"] for i in ("01", "02", "03")},
                "historical_endpoint_delta_sigma0_eV": endpoints["04"]["sigma0_eV"] - endpoints["00"]["sigma0_eV"],
                "same_step_sigma0_profile_eV": None,
                "same_step_toten_profile_eV": None,
                "highest_sampled_image": None,
                "finite_profile_peak_eV_above_endpoint00": None,
                "endpoint_directional_delta_eV": None,
                "barrier_established": False})
    return result


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
    if nsw not in REFS["allowed_nsw"] or baseline != str(REFS["fresh_nsw"]):
        raise ScienceError("only the reviewed fresh NSW=4 and historical NSW=200 modes are allowed")
    required = REFS["required_method"]
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

class ContextError(ValueError):
    pass


class CandidateError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(context: dict) -> dict[str, tuple[str, int]]:
    manifest = context.get("native_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ContextError("protected native manifest is missing")
    result = {}
    for row in manifest:
        if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                or not isinstance(row.get("sha256"), str)
                or type(row.get("bytes")) is not int or row["bytes"] < 0):
            raise ContextError("malformed protected native manifest row")
        if row["path"] in result:
            raise ContextError("duplicate protected native path")
        result[row["path"]] = (row["sha256"], row["bytes"])
    return result


def _mode_source_path(context: dict, relative: str) -> str:
    mode = context["execution_mode"]
    if mode == "HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY":
        return f"case04-author/{relative}"
    job = context.get("source_job_id")
    if not isinstance(job, str) or not job or "/" in job or job in (".", ".."):
        raise ContextError("invalid fresh source job id")
    return f"case04-author/{job}/{relative}"


def _bind_native_evidence(context: dict, evidence: Path) -> None:
    rows = _rows(context)
    required = ["neb/INCAR", "neb/KPOINTS"]
    required += [f"neb/{image}/POSCAR" for image in ("00", "01", "02", "03", "04")]
    required += [f"neb/{image}/OUTCAR" for image in ("01", "02", "03")]
    # Historical archive endpoint witnesses are protected native files. In a
    # fresh run endpoints remain the supplied public upstream records.
    mode = context["execution_mode"]
    if mode == "HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY":
        required += [f"upstream/{image}/{name}" for image in ("00", "04")
                     for name in ("CONTCAR", "OUTCAR.bz2")]
    for relative in required:
        path = evidence / relative
        if not path.is_file():
            raise CandidateError(f"missing native evidence {relative}")
        source = _mode_source_path(context, relative)
        record = rows.get(source)
        if record is None:
            raise CandidateError(f"native file is not in protected manifest: {source}")
        actual = (_sha(path), path.stat().st_size)
        if actual != record:
            raise CandidateError(f"native bytes differ from host manifest: {source}")

    # Optional fetched native rows are also bound, so an unexamined altered
    # CONTCAR or scheduler artifact cannot be passed off as host output.
    for relative in ("neb/00/CONTCAR", "neb/04/CONTCAR", "neb/01/CONTCAR",
                     "neb/02/CONTCAR", "neb/03/CONTCAR",
                     "neb/01/OSZICAR", "neb/02/OSZICAR", "neb/03/OSZICAR"):
        path = evidence / relative
        if path.is_file():
            source = _mode_source_path(context, relative)
            record = rows.get(source)
            if record != (_sha(path), path.stat().st_size):
                raise CandidateError(f"optional native bytes differ from host manifest: {source}")


_FREE_TEXT_FIELDS = set(REFS["free_text_fields"])
_GEOMETRY_METRICS = set(REFS["geometry_metrics"])


def _compare(actual, expected, where="$", tolerance=REFS["comparison_tolerance"]):
    if isinstance(expected, bool):
        if type(actual) is not bool or actual is not expected:
            raise CandidateError(f"{where}: boolean differs from native reconstruction")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                or not math.isfinite(float(actual))
                or abs(float(actual) - float(expected)) > tolerance):
            raise CandidateError(f"{where}: numeric value differs from native reconstruction")
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or not set(expected).issubset(actual):
            raise CandidateError(f"{where}: required object fields differ from native reconstruction")
        for key in expected:
            _compare(actual[key], expected[key], f"{where}.{key}", tolerance)
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise CandidateError(f"{where}: list differs from native reconstruction")
        for index, (a, e) in enumerate(zip(actual, expected)):
            _compare(a, e, f"{where}[{index}]", tolerance)
    elif isinstance(expected, str) and where.rsplit(".", 1)[-1] in _FREE_TEXT_FIELDS:
        if not isinstance(actual, str) or not actual.strip():
            raise CandidateError(f"{where}: explanatory text must be non-empty")
    elif isinstance(expected, str) and where.rsplit(".", 1)[-1] == "metric_id":
        if actual not in _GEOMETRY_METRICS:
            raise CandidateError(f"{where}: unsupported geometric comparison convention")
    elif actual != expected:
        raise CandidateError(f"{where}: value differs from native reconstruction")


def _validate_fresh_resources(context: dict) -> None:
    if context.get("resource_budget_ok") is not True:
        raise CandidateError("fresh allocation did not satisfy protected resource budget")
    if (not isinstance(context.get("source_terminal_state"), str)
            or not context["source_terminal_state"]
            or not isinstance(context.get("source_job_id"), str)
            or not context["source_job_id"]):
        raise ContextError("fresh source job or terminal state is missing")
    plan = context.get("accepted_plan")
    if not isinstance(plan, dict):
        raise ContextError("fresh accepted plan is missing")
    if not isinstance(context.get("accepted_plan_sha256"), str):
        raise ContextError("fresh accepted-plan hash is missing")
    required = {"ntasks", "memory_gib", "walltime_seconds", "neb_ranks", "vasp_path", "mpi_path"}
    if set(plan) != required:
        raise ContextError("fresh accepted plan has unexpected fields")
    plan_sha = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    if context["accepted_plan_sha256"] != plan_sha:
        raise ContextError("fresh accepted-plan hash does not match the protected plan")
    for key, low, high in (("ntasks", 1, REFS["resource_limits"]["max_cpus"]),
                           ("memory_gib", 1, REFS["resource_limits"]["max_memory_gib"]),
                           ("walltime_seconds", 1, REFS["resource_limits"]["max_walltime_seconds"]),
                           ("neb_ranks", REFS["neb_ranks_multiple"], REFS["resource_limits"]["max_cpus"])):
        value = plan[key]
        if type(value) is not int or not low <= value <= high:
            raise CandidateError(f"accepted plan violates {key} bounds")
    if plan["neb_ranks"] % REFS["neb_ranks_multiple"] or plan["neb_ranks"] > plan["ntasks"]:
        raise CandidateError("accepted NEB rank count is incompatible with NPAR=4 and IMAGES=3")
    if not isinstance(plan["vasp_path"], str) or not isinstance(plan["mpi_path"], str):
        raise CandidateError("accepted executable paths are malformed")
    inventory = context.get("software_inventory")
    qualified = next((row for row in inventory if isinstance(row, dict) and row.get("qualified") is True
                      and row.get("vasp_path") == plan["vasp_path"] and row.get("mpi_path") == plan["mpi_path"]), None) if isinstance(inventory, list) else None
    if qualified is None:
        raise CandidateError("accepted VASP/MPI pair is not host-observed as qualified")
    paw = qualified.get("paw_identity")
    if not isinstance(paw, dict) or paw.get("host_source_verified") is not True or paw.get("private_payload") is not True or paw.get("titles") != REFS["paw_titles"]:
        raise CandidateError("accepted VASP/MPI pair has no host-qualified standard PAW identity")
    policy = paw.get("policy", "exact_author_archive")
    if policy == "exact_author_archive":
        if (paw.get("source_id") != REFS["archive_source_id"]
                or paw.get("combined_sha256") != REFS["combined_standard_paw_sha256"]
                or paw.get("standard_ti_paw_sha256") != REFS["standard_ti_paw_sha256"]):
            raise CandidateError("fresh exact-author PAW identity differs from pinned archive provenance")
    elif policy == REFS.get("qualified_hpc_paw", {}).get("policy"):
        expected = REFS["qualified_hpc_paw"]
        components = paw.get("components")
        if (paw.get("source_id") != expected["source_id"] or paw.get("combined_sha256") != expected["combined_sha256"]
                or not isinstance(components, list) or len(components) != 3):
            raise CandidateError("fresh installed PAW identity differs from the reviewed HPC source")
        paw_root = PurePosixPath(plan["vasp_path"]).parent.parent / "testsuite" / "POTCARS"
        for got, want in zip(components, expected["components"]):
            want = {**want, "source_path": str(paw_root / PurePosixPath(want["source_path"]).name)}
            if not isinstance(got, dict) or any(got.get(k) != want.get(k) for k in ("element", "title", "sha256", "source_path", "component_index")):
                raise CandidateError("fresh installed PAW component identity or order is invalid")
        run_pots = paw.get("run_potcar_observations")
        expected_run = [{"title": row["title"], "sha256": row["sha256"]} for row in expected["components"]]
        if (not isinstance(run_pots, list) or {x.get("path") for x in run_pots if isinstance(x, dict)} != {"neb/POTCAR"}
                or any(x.get("sha256") != expected["combined_sha256"] or x.get("titles") != REFS["paw_titles"]
                       or x.get("components") != expected_run for x in run_pots)):
            raise CandidateError("fresh NEB POTCAR is not bound to the qualified ordered source components")
    else:
        raise CandidateError("fresh PAW policy is unsupported")
    facts = context.get("execution_facts")
    if (not isinstance(facts, dict) or facts.get("executable_path") != plan["vasp_path"]
            or facts.get("mpi_path") != plan["mpi_path"]
            or not isinstance(facts.get("executable_sha256"), str)
            or not isinstance(facts.get("mpi_sha256"), str)
            or not isinstance(facts.get("script_sha256"), str)):
        raise CandidateError("fresh execution facts do not bind the accepted executable pair")
    accounting = context.get("resource_accounting")
    if not isinstance(accounting, dict):
        accounting = context.get("actual_accounting")
    if not isinstance(accounting, dict):
        raise ContextError("fresh scheduler accounting is missing")
    rows = accounting.get("scheduler_rows")
    job = context.get("source_job_id")
    parent = next((row for row in rows or [] if isinstance(row, dict)
                   and str(row.get("JobIDRaw", "")) == str(job)), None)
    if parent is None:
        raise ContextError("fresh parent scheduler row is missing")
    cpus = int(parent.get("AllocCPUS", 0))
    if cpus != plan["ntasks"]:
        raise CandidateError("actual AllocCPUS differs from accepted plan")
    elapsed_text = str(parent.get("ElapsedRaw", ""))
    if elapsed_text:
        elapsed = int(elapsed_text)
    else:
        elapsed = _slurm_seconds(parent.get("Elapsed"))
    if elapsed < 0 or elapsed > REFS["resource_limits"]["max_walltime_seconds"]:
        raise CandidateError("actual elapsed allocation exceeds the hard walltime cap")
    charged = accounting.get("allocated_core_hours_charged",
                             accounting.get("allocated_core_hours"))
    expected_charge = cpus * elapsed / 3600.0
    if not isinstance(charged, (int, float)) or isinstance(charged, bool) or not math.isclose(
            float(charged), expected_charge, rel_tol=0, abs_tol=1e-6):
        raise CandidateError("actual allocated core-hours do not match CPU and elapsed accounting")
    if expected_charge > REFS["resource_limits"]["max_core_hours"]:
        raise CandidateError("actual allocation exceeds the Case 04 core-hour budget")
    if accounting.get("allocated_cpus") is not None and accounting["allocated_cpus"] != cpus:
        raise CandidateError("resource ledger CPU count differs from parent scheduler row")
    if accounting.get("elapsed_raw_seconds") is not None and accounting["elapsed_raw_seconds"] != elapsed:
        raise CandidateError("resource ledger elapsed seconds differ from parent scheduler row")
    if accounting.get("allocated_core_hours") is not None and not math.isclose(
            float(accounting["allocated_core_hours"]), expected_charge, rel_tol=0, abs_tol=1e-6):
        raise CandidateError("resource ledger core-hour charge differs from actual CPU and elapsed")
    memory = str(parent.get("ReqMem", ""))
    match = re.fullmatch(r"(\d+)Gn?", memory)
    if not match or int(match.group(1)) != plan["memory_gib"]:
        raise CandidateError("actual requested memory differs from accepted plan")
    requested_memory = accounting.get("requested_memory")
    if requested_memory is not None and str(requested_memory) != memory:
        raise CandidateError("resource ledger memory differs from parent scheduler row")
    time_limit = _slurm_seconds(parent.get("Timelimit"))
    if time_limit != plan["walltime_seconds"]:
        raise CandidateError("actual Slurm time limit differs from accepted plan")
    if accounting.get("time_limit") is not None and _slurm_seconds(str(accounting["time_limit"])) != time_limit:
        raise CandidateError("resource ledger time limit differs from parent scheduler row")
    if parent.get("WorkDir") != context.get("workdir"):
        raise CandidateError("actual work directory differs from host context")
    if accounting.get("workdir") is not None and accounting["workdir"] != parent.get("WorkDir"):
        raise CandidateError("resource ledger work directory differs from parent scheduler row")
    for scheduler_key, ledger_key in (("Account", "account"), ("Partition", "partition")):
        if accounting.get(ledger_key) is not None and parent.get(scheduler_key) != accounting[ledger_key]:
            raise CandidateError(f"actual scheduler {scheduler_key} differs from resource ledger")
    site = context.get("site_profile")
    attempt = context.get("attempt_id")
    if (not isinstance(site, dict) or set(site) != {"account", "partition", "job_root", "vasp_path", "mpi_path"}
            or not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt)):
        raise ContextError("fresh operator site profile is missing or malformed")
    site_sha = hashlib.sha256(json.dumps(site, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    root = site.get("job_root")
    posix_root = PurePosixPath(root) if isinstance(root, str) else PurePosixPath(".")
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+", str(site.get("account", "")))
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(site.get("partition", "")))
            or not posix_root.is_absolute() or root in {"/", "//"} or root.startswith("//")
            or ".." in posix_root.parts or root != posix_root.as_posix()
            or context.get("site_profile_sha256") != site_sha):
        raise ContextError("fresh operator site profile is not normalized or hash bound")
    expected_workdir = f"{root.rstrip('/')}/bench16/case04-author/runs/{attempt}"
    if (context.get("workdir") != expected_workdir or parent.get("Account") != site["account"]
            or parent.get("Partition") != site["partition"]):
        raise CandidateError("actual Slurm workdir or account differs from operator site config")
    if (plan["vasp_path"] != site["vasp_path"] or plan["mpi_path"] != site["mpi_path"]
            or facts.get("executable_sha256") != REFS["vasp_sha256"]
            or facts.get("mpi_sha256") != REFS["mpi_sha256"]):
        raise CandidateError("accepted executable location or scientific identity differs from the reviewed pair")


def _slurm_seconds(value) -> int:
    if not isinstance(value, str) or not value:
        raise ContextError("scheduler time value is missing")
    days = 0
    if "-" in value:
        day, value = value.split("-", 1)
        days = int(day)
    fields = [int(part) for part in value.split(":")]
    if len(fields) == 2:
        hours, minutes = fields
        seconds = 0
    elif len(fields) == 3:
        hours, minutes, seconds = fields
    else:
        raise ContextError("malformed Slurm time value")
    return days * 86400 + hours * 3600 + minutes * 60 + seconds



def _readonly_security_context_valid(audit: dict | None) -> bool:
    if not isinstance(audit, dict) or audit.get("passed") is not True or audit.get("agent_uid") in (None, 0):
        return False
    if audit.get("ssh_auth_socket_env_empty") is not True:
        return False
    protected = audit.get("protected_paths")
    if not isinstance(protected, dict):
        return False
    if protected.get("/root/.ssh", {}).get("read") is not False:
        return False
    if protected.get("/run/bench16/profile.json", {}).get("write") is not False:
        return False
    if protected.get("/run/bench16/ikkem.toml", {}).get("read") is not False:
        return False
    if protected.get("/app/assets/bench16_runtime.py", {}).get("write") is not False:
        return False
    clients = audit.get("remote_clients")
    expected = {"ssh", "scp", "sftp", "dbclient", "plink"}
    if not isinstance(clients, dict) or set(clients) != expected:
        return False
    if any(not isinstance(rows, list) or any(not isinstance(row, dict)
           or row.get("nonroot_execution_denied") is not True for row in rows) for rows in clients.values()):
        return False
    helpers = audit.get("setuid_helpers_present")
    if not isinstance(helpers, dict) or any(helpers.values()):
        return False
    if audit.get("setuid_files_remaining") != 0:
        return False
    return True


def _candidate_evidence_absent_valid(context: dict, final_dir: Path) -> bool:
    tasks = {"case-03-author-relax-v4": "task 106", "case-04-author-neb-v3": "task 107"}
    attempt = context.get("attempt_id")
    case = context.get("case_id")
    site = context.get("site_profile")
    if not isinstance(site, dict): raise ContextError("operator Slurm site profile is missing")
    lane = "case03-author-v4" if case == "case-03-author-relax-v4" else "case04-author"
    root = site.get("job_root", "").rstrip("/") + "/bench16/" + lane + "/runs"
    site_sha = hashlib.sha256(json.dumps(site, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if (context.get("schema") != "compchembench.bench16-task-root-context/v1"
            or context.get("task") != tasks.get(case)
            or context.get("execution_mode") != "NORMAL"
            or context.get("authority") != "task_root_observed"
            or context.get("candidate_evidence_status") != "NOT_DEMONSTRATED"
            or context.get("science_status") != "NOT_DEMONSTRATED"
            or context.get("source_is_historical") is not False
            or case not in tasks
            or not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt)
            or context.get("run_id") != attempt
            or context.get("workdir") != root + "/" + str(attempt)
            or context.get("site_profile_sha256") != site_sha
            or context.get("jobs") != [] or context.get("remote_files_created") != []
            or any(key in context for key in ("accepted_plan", "native_manifest", "source_job_id", "job_ids", "actual_accounting"))):
        raise ContextError("candidate-absence context identity or claim set is invalid")
    for field in ("task_input_manifest_sha256", "runtime_sha256", "snapshot_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(context.get(field, ""))):
            raise ContextError(f"candidate-absence context {field} is invalid")
    snapshot = context.get("snapshot")
    if (not isinstance(snapshot, dict) or snapshot.get("status") != "OBSERVED"
            or snapshot.get("software_matches_reviewed_identity") is not True
            or snapshot.get("paw_matches_reviewed_identity") is not True
            or context.get("startup_probe_sha256") != hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            ).hexdigest()):
        raise ContextError("candidate-absence startup snapshot binding is invalid")
    observation = context.get("candidate_evidence_observation")
    if not isinstance(observation, dict) or set(observation) != {"sacct", "squeue", "attempt_workdir"}:
        raise ContextError("candidate-absence source observations are missing")
    empty_sha = hashlib.sha256(b"").hexdigest()
    absent_sha = hashlib.sha256(b"absent").hexdigest()
    sacct, squeue, workdir = observation["sacct"], observation["squeue"], observation["attempt_workdir"]
    if (not isinstance(sacct, dict) or set(sacct) != {"query_return_code", "query_name", "query_workdir", "matching_parent_rows", "stdout_sha256"}
            or type(sacct.get("query_return_code")) is not int or sacct["query_return_code"] != 0
            or sacct.get("query_name") != attempt or sacct.get("query_workdir") != context["workdir"]
            or type(sacct.get("matching_parent_rows")) is not int or sacct["matching_parent_rows"] != 0
            or sacct.get("stdout_sha256") != empty_sha):
        raise ContextError("candidate-absence accounting observation is invalid")
    if (not isinstance(squeue, dict) or set(squeue) != {"query_return_code", "query_name", "matching_jobs", "stdout_sha256"}
            or type(squeue.get("query_return_code")) is not int or squeue["query_return_code"] != 0
            or squeue.get("query_name") != attempt
            or type(squeue.get("matching_jobs")) is not int or squeue["matching_jobs"] != 0
            or squeue.get("stdout_sha256") != empty_sha):
        raise ContextError("candidate-absence queue observation is invalid")
    if (not isinstance(workdir, dict) or set(workdir) != {"query_return_code", "path", "exists", "stdout_sha256"}
            or type(workdir.get("query_return_code")) is not int or workdir["query_return_code"] != 0
            or workdir.get("path") != context["workdir"] or workdir.get("exists") is not False
            or workdir.get("stdout_sha256") != absent_sha):
        raise ContextError("candidate-absence workdir observation is invalid")
    result_path = final_dir / "results.json"
    if result_path.is_symlink() or result_path.exists():
        raise ContextError("candidate results exist despite the absent-evidence claim")
    evidence = final_dir / "evidence"
    if evidence.is_symlink() or (evidence.exists() and any(path.is_file() for path in evidence.rglob("*"))):
        raise ContextError("candidate evidence files exist despite the absent-evidence claim")
    return True

def verify(final_dir: Path, context_path: Path | None = None, asset_root: Path | None = None) -> dict:
    final_dir = Path(final_dir)
    asset_root = Path(asset_root or os.environ.get("APP", "/app") + "/assets")
    context_path = Path(context_path or os.environ.get("CCB_RUN_CONTEXT_PATH", "/app/.bench16-trusted/runner-context.json"))
    try:
        context = json.loads(_trusted_context_bytes(context_path).decode("utf-8"))
        mode = context.get("execution_mode")
        if mode == 'NO_HPC_JOB':
            if (context.get('schema') != 'compchembench.bench16-task-root-context/v1'
                    or context.get('authority') != 'task_root_observed'
                    or context.get('case_id') != REFS["case_id"]):
                raise ContextError('invalid trusted scheduler selection record')
            return {'schema':'compchembench.verification/v1','status':'FAIL','score':0,
                    'execution_mode':mode,'science_status':'NOT_DEMONSTRATED',
                    'checked_claims':['no qualifying HPC job was available for trusted collection']}

        if context.get("candidate_evidence_status") == "NOT_DEMONSTRATED":
            _candidate_evidence_absent_valid(context, final_dir)
            return {"schema": "compchembench.verification/v1", "status": "FAIL", "score": 0,
                    "execution_mode": "NORMAL", "science_status": "NOT_DEMONSTRATED",
                    "checked_claims": ["source returned successful empty Slurm accounting and queue observations for this exact protected attempt",
                                       "the protected attempt workdir is absent; no qualifying completed candidate evidence is demonstrated"]}
        if mode == "READONLY_MVP":
            if (context.get("authority") != "task_root_observed"
                    or context.get("case_id") != REFS["case_id"]
                    or context.get("science_status") != "NOT_RUN"
                    or context.get("jobs") != []
                    or context.get("remote_files_created") != []
                    or context.get("submission_disabled") is not True
                    or context.get("remote_mutation_disabled") is not True
                    or not _readonly_security_context_valid(context.get("security_audit"))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(context.get("runtime_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(context.get("snapshot_sha256", "")))):
                raise ContextError("read-only MVP trusted context is malformed")
            return {"schema": "compchembench.verification/v1", "status": "FAIL", "score": 0,
                    "execution_mode": "READONLY_MVP", "science_status": "NOT_RUN",
                    "checked_claims": ["read-only profile recorded by task-root collector",
                                       "zero submitted jobs and zero remote files created",
                                       "scientific analysis was not run"]}
        actual = json.loads((final_dir / "results.json").read_text(encoding="utf-8"))
        if context.get("case_id") != REFS["case_id"]:
            raise ContextError("protected task context identity is invalid")
        if mode == "FRESH_HPC":
            if context.get("authority") not in {"runner_host_observed", "task_root_observed"}:
                raise ContextError("fresh task-root context authority is invalid")
        elif context.get("authority") != "runner_host_observed":
            raise ContextError("historical archive context authority is invalid")
        if mode == "HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY":
            if (context.get("source_is_historical") is not True or context.get("source_job_id") is not None
                    or context.get("archive_source_id") != REFS["archive_source_id"]
                    or context.get("archive_sha256") != REFS["archive_sha256"]):
                raise ContextError("unapproved historical archive source")
        elif mode == "FRESH_HPC":
            if context.get("source_is_historical") is not False:
                raise ContextError("fresh context is marked historical")
            _validate_fresh_resources(context)
        else:
            raise ContextError("unsupported host execution mode")
    except ContextError as exc:
        return {"schema": "compchembench.verification/v1", "status": "ERROR",
                "score": None, "error": str(exc), "checked_claims": []}
    except Exception as exc:
        return {"schema": "compchembench.verification/v1", "status": "ERROR",
                "score": None, "error": f"protected input unavailable: {exc}", "checked_claims": []}

    try:
        if actual.get("schema") != "case04-author-neb-v3-results/v1" or actual.get("case_id") != context["case_id"]:
            raise CandidateError("result schema or case identity mismatch")
        evidence = final_dir / "evidence"
        _bind_native_evidence(context, evidence)
        for image in ("00", "01", "02", "03", "04"):
            source = asset_root / "neb" / image / "POSCAR"
            candidate = evidence / "neb" / image / "POSCAR"
            if not source.is_file() or _sha(source) != _sha(candidate):
                raise CandidateError(f"image {image} POSCAR differs from the original authored input")
        if _sha(asset_root / "neb" / "KPOINTS") != _sha(evidence / "neb" / "KPOINTS"):
            raise CandidateError("NEB KPOINTS differs from the authored Gamma mesh")
        for image in ("00", "04"):
            for filename in ("CONTCAR", "OUTCAR.bz2"):
                source = asset_root / "upstream" / image / filename
                target = evidence / "upstream" / image / filename
                if not source.is_file():
                    raise ContextError(f"frozen endpoint reference is unavailable: {source}")
                if mode == "FRESH_HPC":
                    if not target.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(source.read_bytes())
                    elif _sha(target) != _sha(source):
                        raise CandidateError(f"fresh run replaced frozen historical endpoint {image}/{filename}")
                elif not target.is_file() or _sha(target) != _sha(source):
                    raise CandidateError(f"historical endpoint {image}/{filename} differs from frozen source")
        paw_identity = None
        if mode == "FRESH_HPC":
            pair = context["accepted_plan"]
            qualified = next(row for row in context["software_inventory"]
                             if row.get("qualified") is True and row.get("vasp_path") == pair["vasp_path"]
                             and row.get("mpi_path") == pair["mpi_path"])
            paw_identity = qualified["paw_identity"]
        expected = build_result(evidence, paw_identity)
        source = actual.get("source")
        if not isinstance(source, dict):
            raise CandidateError("source provenance is missing")
        expected_source = {
            "job_id": context.get("source_job_id"),
            "historical": mode != "FRESH_HPC",
            "execution_mode": mode,
        }
        if mode == "HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY":
            expected_source.update({"archive_source_id": context["archive_source_id"],
                                    "archive_sha256": context["archive_sha256"]})
        else:
            expected_source.update({"terminal_state": context.get("source_terminal_state"),
                                    "resource_budget_ok": context.get("resource_budget_ok"),
                                    "accepted_plan": context.get("accepted_plan"),
                                    "accepted_plan_sha256": context.get("accepted_plan_sha256")})
            expected_source.update({"paw_policy": paw_identity.get("policy", "exact_author_archive"),
                                    "paw_source_id": paw_identity.get("source_id")})
        for key, value in expected_source.items():
            if source.get(key) != value:
                raise CandidateError(f"source provenance mismatch for {key}")
        expected["source"].update(expected_source)
        if paw_identity is not None and paw_identity.get("policy") == REFS["qualified_hpc_paw"]["policy"]:
            analysis = actual.get("analysis", {})
            for claim in ("barrier", "activation_barrier", "migration_barrier", "activation_energy", "path_barrier"):
                if claim in analysis and analysis[claim] not in (None, False, "INCOMPARABLE/NOT_ESTABLISHED"):
                    raise CandidateError("alternate PAW route cannot claim a mixed-source endpoint-relative barrier")
        _compare(actual, expected)
        return {"schema": "compchembench.verification/v1", "status": "PASS", "score": 1,
                "execution_mode": mode,
                "checked_claims": ["all native evidence is bound to the host manifest",
                                   "all reported native energies, positions, forces, tangents and method are independently rebuilt",
                                   "ordinary-NEB force, projection, spring and sampled-profile audit"]}
    except ContextError as exc:
        return {"schema": "compchembench.verification/v1", "status": "ERROR",
                "score": None, "error": str(exc), "checked_claims": []}
    except Exception as exc:
        return {"schema": "compchembench.verification/v1", "status": "FAIL",
                "score": 0, "error": str(exc), "checked_claims": []}


def main() -> int:
    report = verify(Path(os.environ.get("APP", "/app")) / "final")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "ERROR" else 1



def test_output_main():
    
    
    final = Path(os.environ.get("APP", "/app")) / "final"
    context = Path(os.environ.get("CCB_RUN_CONTEXT_PATH", "/app/.bench16-trusted/runner-context.json"))
    asset_root = Path("/app/assets")
    if not asset_root.is_dir():
        asset_root = Path(__file__).resolve().parents[1] / "environment" / "assets"
    report = verify(final, context, asset_root)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "ERROR" else 1

if __name__ == "__main__":
    raise SystemExit(test_output_main() if "--test-output" in sys.argv[1:] else main())
