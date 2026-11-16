"""Strict adapters for native CP2K geometry, minimum and dissociation evidence.

This module intentionally does not treat candidate JSON as scientific evidence.
It reads CP2K's preserved native files and returns facts plus a conservative
PASS/FAIL/UNVERIFIED status.  The fixtures in test_native_science.py are parser
controls, not experimental or computational gold data.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Sequence


STATUS = {"PASS", "FAIL", "UNVERIFIED"}
VIB_FORCE_EVAL_ENERGY_TOL_AU = 1e-10
VIB_FORCE_EVAL_VECTOR_TOL_AU_BOHR = 1e-8
CP2K_2024_MASSUNIT = 1822.888484264545
CP2K_2024_VIBFAC = 5140.487143385848
CP2K_2024_CM_FACTOR = math.sqrt(CP2K_2024_MASSUNIT) * CP2K_2024_VIBFAC / 1000.0
_DEFAULT_MASS_AMU = {"H": 1.00794, "C": 12.0107, "N": 14.0067,
                     "O": 15.9994, "S": 32.065, "Cl": 35.453}
_FD_FORCE_PRINT_HALF_UNIT = 5e-10
_FREQUENCY_PRINT_HALF_UNIT_CM1 = 5e-7
_GEOMETRY_VECTOR_PRINT_HALF_UNIT_ANG = 5e-7
_TRUSTED_M14_SOURCE_SHA_PAIRS = {
    # Grader-owned byte identities for the public source trajectory/output/input
    # bundles. These bind the entire trajectory to its source calculation; they
    # are not candidate-submitted claims.
    ("f3d139fd59abcd6c013598b16f3d3f7a87d66175fbc6dcc8ca58f8714d44d1a5",
     "f55c1b061e38a651f9bddb9110de5b70643b07810655e4ad8fde622347a008a7",
     "1536cf822b313f6fc3b040ca84d2e0246e3a943613e27691716491ecda1b33c9"),
    ("8c9a321bb2eef0b80d45a227c34699bfbb8d44c2bd82362eb7f61c3eb1a15196",
     "f2cb11279d244ce14e63b77d5db2e08be6ac265f0240da80c07be8fc8a2adb8b",
     "6747de752c4e19eac00982954b660bae4d4c9fbb13f09516500be00cb095c092"),
}
_BAD = re.compile(r"(?im)^\s*(?:\*{2,}\s*ABORT\b|ABORTING\b|ERROR STOP\b)|\b(?:SCF run\s+NOT converged|TDDFPT.*?NOT converged|linear solver.*?(?:failed|NOT converged))\b", re.I)
_START = re.compile(r"(?im)^[^\r\n]*\bPROGRAM STARTED AT\b")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_native(source: Path | str, *, allow_partial_prefix: bool = False) -> tuple[str | None, dict]:
    """Read exactly the preserved bytes; malformed bytes are never normalized."""
    path = Path(source)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, {"status": "UNVERIFIED", "issues": [f"native file is unreadable: {exc}"]}
    if b"\x00" in raw:
        return None, {"status": "UNVERIFIED", "issues": ["native file contains NUL bytes; raw evidence is incomplete"]}
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, {"status": "UNVERIFIED", "issues": ["native file is not valid UTF-8"]}
    starts = list(_START.finditer(text))
    segment = text[starts[-1].start():] if starts else text
    if not starts:
        return None, {"status": "UNVERIFIED", "issues": ["native file has no PROGRAM STARTED AT boundary"]}
    complete = "PROGRAM ENDED AT" in segment
    if not complete and not allow_partial_prefix:
        return None, {"status": "UNVERIFIED", "issues": ["last native invocation has no PROGRAM ENDED AT footer"]}
    if _BAD.search(segment):
        if not allow_partial_prefix:
            return None, {"status": "FAIL", "issues": ["last native invocation contains an abort or unconverged scientific step"]}
    version = re.search(r"(?im)^\s*CP2K\|\s*version string:\s*(.+)$", segment)
    oom = bool(re.search(r"(?i)(?:out of memory|oom[- ]kill|oom_kill|memory cgroup out of memory)", segment))
    return segment, {"status": "PASS" if complete else "PARTIAL", "issues": [], "complete": complete,
                     "oom": oom, "invocations": len(starts),
                     "version": version.group(1).strip() if version else None,
                     "sha256": hashlib.sha256(raw).hexdigest(), "path": str(path)}


def _number(token: str) -> float:
    value = float(token.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("nonfinite native numeric value")
    return value


def _xyz_frames(path: Path) -> list[list[tuple[str, float, float, float]]]:
    text = path.read_text(encoding="utf-8", errors="strict")
    if "\x00" in text:
        raise ValueError("optimizer XYZ contains NUL")
    lines = text.splitlines()
    frames = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        n = int(lines[i].strip())
        if n <= 0 or i + n + 2 > len(lines):
            raise ValueError("truncated optimizer XYZ frame")
        atoms = []
        for row in lines[i + 2:i + n + 2]:
            p = row.split()
            if len(p) < 4:
                raise ValueError("incomplete optimizer XYZ atom row")
            atoms.append((p[0].capitalize(), *(_number(x) for x in p[1:4])))
        frames.append(atoms)
        i += n + 2
    if not frames:
        raise ValueError("optimizer XYZ contains no complete frames")
    return frames


def _trajectory_frames(path: Path) -> list[dict]:
    """Read native optimizer XYZ frames with the printed energy comment intact."""
    frames = _xyz_frames(path)
    lines = Path(path).read_text(encoding="utf-8", errors="strict").splitlines()
    result = []
    i = 0
    frame_index = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        n = int(lines[i].strip())
        comment = lines[i + 1]
        em = re.search(r"\bE\s*=\s*([-+0-9.EeDd]+)", comment, re.I)
        if not em:
            raise ValueError("optimizer XYZ comment lacks its native energy")
        sm = re.search(r"\bi\s*=\s*(\d+)", comment, re.I)
        result.append({"index": frame_index, "step": int(sm.group(1)) if sm else None,
                       "energy": _number(em.group(1)), "coordinates": frames[frame_index]})
        frame_index += 1
        i += n + 2
    return result


def _last_xyz_step_segment(frames: list[dict]) -> list[dict]:
    """Keep the final monotonically increasing CP2K GEO_OPT step sequence."""
    starts = [0]
    last = None
    for i, frame in enumerate(frames):
        step = frame.get("step")
        if step is not None and last is not None and step <= last:
            starts.append(i)
        last = step
    segment = frames[starts[-1]:]
    if not segment or any(x.get("step") is None for x in segment):
        return []
    return segment


def _restart_coords(path: Path) -> list[tuple[str, float, float, float]]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    if b"\x00" in raw:
        raise ValueError("native restart contains NUL")
    # CP2K restart COORD values are in angstrom unless the block says otherwise.
    m = re.search(r"(?ims)^\s*&COORD\b(.*?)^\s*&END(?:\s+COORD)?\b", text)
    if not m:
        raise ValueError("native restart lacks a complete COORD block")
    block = m.group(1)
    unit = re.search(r"(?im)^\s*UNIT\s+(?:\[([^]]+)\]|([^\s]+))", block)
    unit_name = ((unit.group(1) or unit.group(2)).lower() if unit else "angstrom")
    factors = {"angstrom": 1.0, "angstroem": 1.0, "bohr": 0.529177210903, "a.u.": 0.529177210903}
    if unit_name not in factors:
        raise ValueError(f"unsupported native restart coordinate unit: {unit_name}")
    factor = factors[unit_name]
    rows = []
    for line in block.splitlines():
        p = line.split()
        if not p or p[0].startswith("#") or p[0].upper() in {"UNIT", "SCALED"}:
            continue
        if len(p) < 4:
            raise ValueError("incomplete native restart coordinate row")
        rows.append((p[0].capitalize(), *(_number(x) * factor for x in p[1:4])))
    if not rows:
        raise ValueError("native restart COORD block is empty")
    aliases = _element_aliases(text)
    return [(aliases.get(atom[0], atom[0]), *atom[1:]) for atom in rows]


def _coord_close(a: Sequence[tuple], b: Sequence[tuple], tol: float = 2e-5) -> bool:
    if len(a) != len(b):
        return False
    return all(x[0] == y[0] and max(abs(x[k] - y[k]) for k in range(1, 4)) <= tol
               for x, y in zip(a, b))


def _rigid_rank(atoms: Sequence[tuple]) -> int:
    if len(atoms) < 3:
        return 3 + max(0, len(atoms) - 1)
    origin = atoms[0][1:]
    vectors = [[a[k] - origin[k - 1] for k in range(1, 4)] for a in atoms[1:]]
    largest = max((math.sqrt(sum(v * v for v in row)) for row in vectors), default=0.0)
    if largest < 1e-10:
        return 3
    crosses = [math.sqrt(sum(x * x for x in (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])))
               for i, u in enumerate(vectors) for v in vectors[i+1:]]
    return 6 if max(crosses, default=0.0) > 1e-8 * largest * largest else 5


def bind_final_geometry(optimizer_xyz: Path, restart: Path, native_output: Path, *,
                        expected_species: Sequence[str],
                        expected_sha256: dict[str, str] | None = None) -> dict:
    """Bind optimizer's last XYZ frame to its independently written native restart.

    Native GLOBAL project identity and final coordinates bind the optimizer XYZ
    and restart to one CP2K project. Energy/species agreement alone is never
    sufficient; all atom coordinates must agree within 2e-5 angstrom.
    """
    paths = {"xyz": Path(optimizer_xyz), "restart": Path(restart), "output": Path(native_output)}
    out = {"status": "UNVERIFIED", "issues": [], "final_coordinates": None,
           "source": "optimizer_xyz + native_restart", "native_sha256": None}
    if expected_sha256:
        for key, path in paths.items():
            expected = expected_sha256.get(key)
            if expected is not None:
                try:
                    actual = _sha(path)
                except OSError as exc:
                    out["issues"].append(f"{key} cannot be hashed: {exc}")
                    continue
                if actual.lower() != str(expected).lower():
                    out["issues"].append(f"{key} SHA-256 does not match its artifact manifest")
    xyz, restart_coords = None, None
    try:
        xyz = _xyz_frames(paths["xyz"])[-1]
        restart_coords = _restart_coords(paths["restart"])
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        out["issues"].append(f"geometry artifact is incomplete: {exc}")
    native, native_meta = _read_native(paths["output"])
    if native is None:
        out["issues"].extend(native_meta["issues"])
    else:
        out["native_sha256"] = native_meta["sha256"]
        out["cp2k_version"] = native_meta["version"]
        if "GEOMETRY OPTIMIZATION COMPLETED" not in native:
            out["issues"].append("native output does not show normal geometry optimization completion")
    # A GEO_OPT stdout may be output.out/cp2k.out; only native project identity matters.
    native_project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", native or "")
    restart_text = ""
    try:
        restart_text = paths["restart"].read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        pass
    restart_project = re.search(r"(?im)^\s*(?:PROJECT_NAME|PROJECT)\s+[\"']?([^\s\"']+)", restart_text)
    if not native_project or not restart_project or native_project.group(1) != restart_project.group(1):
        out["issues"].append("native output and restart do not identify the same CP2K project")
    species = [str(x).capitalize() for x in expected_species]
    if xyz is not None and restart_coords is not None:
        if [a[0] for a in xyz] != species or [a[0] for a in restart_coords] != species:
            out["issues"].append("native/optimizer atom species or canonical ordering differs from expected mapping")
        elif not _coord_close(xyz, restart_coords):
            out["issues"].append("optimizer final XYZ coordinates do not match native restart COORD")
        else:
            out["final_coordinates"] = [[a[0], *a[1:]] for a in xyz]
            out["rigid_rank"] = _rigid_rank(xyz)
    if out["issues"]:
        out["status"] = "FAIL" if any("differs" in x or "do not match" in x or "SHA-256 does not match" in x for x in out["issues"]) else "UNVERIFIED"
    elif xyz is not None:
        out["status"] = "PASS"
    return out


def _numbers(line: str) -> list[float]:
    return [_number(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?", line)]


def _normal_mode_frequencies(frequency_text: str, projection_text: str) -> tuple[list[dict], bool, bool]:
    """Read stdout frequency columns and separately logged native projection evidence."""
    projected = re.search(r"(?im)^\s*VIB\|\s*Frequencies after removal of the rotations and translations\s*$", projection_text)
    block = re.search(r"(?im)^\s*(?:VIB\|\s*)?NORMAL MODES\s*[-–]\s*CARTESIAN DISPLACEMENTS\s*$", frequency_text)
    if not projected or not block:
        return [], bool(projected), False
    chunk = frequency_text[block.end():]
    lines = chunk.splitlines()
    modes: list[dict] = []
    group_widths = []
    frequency_seen = False
    for i, line in enumerate(lines):
        # CP2K 2024.3 prints a mode-index row, then a separate frequency row;
        # matching adjacent integer/frequency pairs would mislabel frequencies.
        if not re.match(r"^\s*VIB\|", line, re.I):
            continue
        payload = re.sub(r"^\s*VIB\|", "", line, flags=re.I).strip()
        if re.search(r"Frequency\s*\(cm\s*\^?\s*-?1\)", payload, re.I):
            frequency_seen = True
            continue
        if not payload or not re.fullmatch(r"\d+(?:\s+\d+)*", payload):
            continue
        indexes = [int(x) for x in payload.split()]
        if indexes != list(range(indexes[0], indexes[-1] + 1)) or len(indexes) > 3:
            return [], True, True
        k = i + 1
        while k < len(lines) and re.match(r"^\s*VIB\|\s*$", lines[k], re.I):
            k += 1
        if k >= len(lines) or not re.search(r"VIB\|\s*Frequency\s*\(cm\s*\^?\s*-?1\)", lines[k], re.I):
            continue
        values_part = re.sub(r"^.*?Frequency\s*\(cm\s*\^?\s*-?1\)", "", lines[k], flags=re.I)
        try:
            values = _numbers(values_part)
        except ValueError:
            return [], True, True
        if len(values) != len(indexes):
            return [], True, True
        group_widths.append(len(indexes))
        modes.extend({"index": idx, "frequency_cm1": value} for idx, value in zip(indexes, values))
        frequency_seen = True
    return modes, True, frequency_seen


def _input_matches(text: str, expected: dict) -> tuple[bool, list[str]]:
    issues = []
    norm = re.sub(r"\s+", " ", text).upper()
    force_eval = _input_root_section(text, "FORCE_EVAL")
    dft = _input_direct_section(force_eval, "DFT")
    td = _input_direct_section(_input_direct_section(force_eval, "PROPERTIES"), "TDDFPT")
    for key, value in expected.items():
        key_upper = str(key).upper()
        if key_upper == "STATE":
            scope = _input_direct_section(dft, "EXCITED_STATES")
            state_values = _input_direct_keyword_values(scope, "STATE")
            found = len(state_values) == 1 and state_values[0].split()[0] == str(value)
        elif key_upper == "XC_FUNCTIONAL":
            found = pbe0_semantics(text) is not None if str(value).upper() == "PBE0" else None
        elif key_upper == "FRACTION":
            scope = _input_direct_section(td, "STDA")
            got = re.search(r"(?im)^\s*FRACTION\s+([-+0-9.EeDd]+)", scope)
            found = bool(got and math.isclose(_number(got.group(1)), float(value), abs_tol=1e-10, rel_tol=0.0))
        else:
            found = None
        if found is not None:
            if not found:
                issues.append(f"paired native input lacks expected scoped setting {key}={value}")
            continue
        if isinstance(value, bool):
            pattern = re.escape(key_upper) + r"\s+(?:" + ("T|TRUE" if value else "F|FALSE") + r")"
        else:
            pattern = re.escape(key_upper) + r"\s+" + re.escape(str(value).upper()) + r"(?:\s|$)"
        if not re.search(pattern, norm):
            issues.append(f"native echoed input lacks expected setting {key}={value}")
    return not issues, issues


def _input_section(text: str, wanted: str) -> str:
    """Return a balanced CP2K input section, including nested sections."""
    clean = "\n".join(line.split("!")[0].split("#")[0] for line in text.splitlines())
    lines = clean.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = re.match(r"^\s*&([A-Za-z_][\w]*)\b", line)
        if m and m.group(1).upper() == wanted.upper():
            start = i
            break
    if start is None:
        return ""
    depth = 1
    body = []
    for line in lines[start + 1:]:
        if re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I):
            depth -= 1
            if depth == 0:
                return "\n".join(body)
        elif re.match(r"^\s*&[A-Za-z_][\w]*\b", line):
            depth += 1
        body.append(line)
    return ""


def _input_root_section(text: str, wanted: str) -> str:
    """Extract only a root-level CP2K section, never a same-named nested block."""
    clean = "\n".join(line.split("!")[0].split("#")[0] for line in text.splitlines())
    lines = clean.splitlines()
    depth = 0
    for index, line in enumerate(lines):
        end = re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I)
        if end:
            depth = max(0, depth - 1)
            continue
        opened = re.match(r"^\s*&([A-Za-z_][\w]*)\b", line)
        if not opened:
            continue
        name = opened.group(1)
        if depth == 0 and name.upper() == wanted.upper():
            return _input_section("\n".join(lines[index:]), wanted)
        depth += 1
    return ""


def _input_direct_named_sections(text: str, wanted: str) -> list[tuple[str | None, str]]:
    """Extract immediate child sections only; nested same-named decoys are ignored."""
    clean = "\n".join(line.split("!")[0].split("#")[0] for line in text.splitlines())
    lines = clean.splitlines()
    depth = 0
    result = []
    for index, line in enumerate(lines):
        if re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I):
            depth = max(0, depth - 1)
            continue
        opened = re.match(r"^\s*&([A-Za-z_][\w]*)\b", line)
        if not opened:
            continue
        name = opened.group(1)
        if depth == 0 and name.upper() == wanted.upper():
            arg = re.match(r"^\s*&[A-Za-z_][\w]*\s+([^\s!#]+)", line)
            result.append((arg.group(1) if arg else None,
                           _input_section("\n".join(lines[index:]), wanted)))
        depth += 1
    return result


def _input_direct_sections(text: str, wanted: str) -> list[str]:
    return [body for _name, body in _input_direct_named_sections(text, wanted)]


def _input_direct_section(text: str, wanted: str) -> str:
    sections = _input_direct_sections(text, wanted)
    return sections[0] if sections else ""


def _input_direct_lines(section: str) -> list[str]:
    """Return non-section lines at depth zero inside an already scoped section."""
    result = []
    depth = 0
    for line in section.splitlines():
        if re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I):
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            result.append(line)
        if re.match(r"^\s*&[A-Za-z_][\w]*\b", line):
            depth += 1
    return result


def _input_direct_keyword_values(section: str, name: str) -> list[str]:
    result = []
    for line in _input_direct_lines(section):
        match = re.match(r"^\s*" + re.escape(name) + r"\s+(.+?)\s*$", line, re.I)
        if match:
            result.append(match.group(1))
    return result


def pbe0_semantics(text: str) -> dict | None:
    """Recognize only CP2K 2024.3's PBE0 shorthand or its exact PBE/HF expansion.

    Unknown XC forms intentionally remain unsupported.  The formal PBE block
    must retain the default ORIG parametrization and default PBE term settings; HF must be
    the unscreened Coulomb 0.25 component used by the molecular reference.
    """
    force_eval = _input_root_section(text, "FORCE_EVAL")
    dft = _input_direct_section(force_eval, "DFT")
    if _input_direct_sections(dft, "HF"):
        return None
    xc = _input_direct_section(dft, "XC")
    xc_blocks = _input_direct_named_sections(xc, "XC_FUNCTIONAL")
    if len(xc_blocks) != 1:
        return None
    name, body = xc_blocks[0]
    xc_children = []
    depth = 0
    for line in xc.splitlines():
        end = re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I)
        if end:
            depth = max(0, depth - 1)
            continue
        opened = re.match(r"^\s*&([A-Za-z_][\w]*)\b", line)
        if opened:
            if depth == 0:
                xc_children.append(opened.group(1).upper())
            depth += 1
    if sorted(xc_children) != sorted(["XC_FUNCTIONAL"] + (["HF"] if _input_direct_sections(xc, "HF") else [])):
        return None
    hf_blocks = _input_direct_sections(xc, "HF")
    if len(hf_blocks) > 1:
        return None
    hf = hf_blocks[0] if hf_blocks else ""
    fraction_values = _input_direct_keyword_values(hf, "FRACTION")
    formal = name is None or name.upper() == "NO_SHORTCUT"
    try:
        declared_fraction = _number(fraction_values[0]) if len(fraction_values) == 1 else (None if fraction_values else 0.25)
    except (ValueError, TypeError):
        declared_fraction = None
    if declared_fraction is None:
        return None
    if formal and (not hf_blocks or len(fraction_values) != 1 or
                   not math.isclose(declared_fraction, 0.25, rel_tol=0.0, abs_tol=1e-10)):
        return None
    # Default interaction is Coulomb. Accept its explicit spelling, while
    # keeping truncation, range separation, and other physics distinct.
    interactions = _input_direct_sections(hf, "INTERACTION_POTENTIAL")
    if len(interactions) > 1:
        return None
    hf_direct = _input_direct_lines(hf)
    allowed_hf = {"FRACTION", "PREFERRED_DIAG_LIBRARY", "MEMORY", "EPS_STORAGE_SCALING"}
    for line in hf_direct:
        fields = line.split()
        if fields and not fields[0].startswith("&") and fields[0].upper() not in allowed_hf:
            return None
    if interactions:
        interaction = interactions[0]
        potential = _input_direct_keyword_values(interaction, "POTENTIAL_TYPE")
        if len(potential) != 1 or potential[0].split()[0].upper() != "COULOMB":
            return None
        if any(line.split() and line.split()[0].upper() != "POTENTIAL_TYPE"
               for line in _input_direct_lines(interaction)):
            return None
    if name and name.upper() == "PBE0":
        if any(line.split() and not line.split()[0].startswith("&")
               for line in _input_direct_lines(body)):
            return None
        pbe_blocks = _input_direct_named_sections(body, "PBE")
        pbe_children = []
        depth = 0
        for line in body.splitlines():
            end = re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I)
            if end:
                depth = max(0, depth - 1)
                continue
            opened = re.match(r"^\s*&([A-Za-z_][\w]*)\b", line)
            if opened:
                if depth == 0:
                    pbe_children.append(opened.group(1).upper())
                depth += 1
        if pbe_children != ([] if not pbe_blocks else ["PBE"]) or len(pbe_blocks) > 1:
            return None
        if pbe_blocks:
            pbe_parameter, pbe_body = pbe_blocks[0]
            if pbe_parameter and _cp2k_boolean_value(pbe_parameter) is None:
                return None
            if any(re.match(r"^\s*&[A-Za-z_]", line) for line in pbe_body.splitlines()):
                return None
            settings = {}
            for line in _input_direct_lines(pbe_body):
                fields = line.split()
                if not fields:
                    continue
                key = fields[0].upper()
                if key not in {"PARAMETRIZATION", "SCALE_X", "SCALE_C"} or key in settings or len(fields) != 2:
                    return None
                settings[key] = fields[1]
            if settings.get("PARAMETRIZATION", "ORIG").upper() != "ORIG":
                return None
            try:
                # The CP2K PBE0 shortcut overwrites the PBE activity and scale
                # defaults; parse explicit values but canonicalize effective
                # scales to .75/1.0. Parametrization is not overwritten.
                for key in ("SCALE_X", "SCALE_C"):
                    if key in settings and not math.isfinite(_number(settings[key])):
                        return None
            except ValueError:
                return None
        return {"xc": ("PBE0",), "hf_fraction": 0.25, "hf_physics": ()}
    if not formal:
        return None
    pbe_blocks = _input_direct_named_sections(body, "PBE")
    if len(pbe_blocks) != 1:
        return None
    pbe_parameter, pbe_body = pbe_blocks[0]
    if pbe_parameter and _cp2k_boolean_value(pbe_parameter) is not True:
        return None
    pbe_children = []
    depth = 0
    for line in body.splitlines():
        end = re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I)
        if end:
            depth = max(0, depth - 1)
            continue
        opened = re.match(r"^\s*&([A-Za-z_][\w]*)\b", line)
        if opened:
            if depth == 0:
                pbe_children.append(opened.group(1).upper())
            depth += 1
    if pbe_children != ["PBE"]:
        return None
    if any(re.match(r"^\s*&[A-Za-z_]", line) for line in pbe_body.splitlines()):
        return None
    rows = _input_direct_lines(pbe_body)
    values = {}
    for line in rows:
        fields = line.split()
        if not fields or fields[0].startswith("&"):
            continue
        key = fields[0].upper()
        if key not in {"SCALE_X", "SCALE_C", "PARAMETRIZATION"} or key in values:
            return None
        values[key] = fields[1:]
    try:
        if (len(values.get("SCALE_X", [])) != 1
                or ("SCALE_C" in values and len(values["SCALE_C"]) != 1)):
            return None
        sx = _number(values["SCALE_X"][0])
        sc = _number(values.get("SCALE_C", ["1.0"])[0])
    except (KeyError, IndexError, ValueError):
        return None
    if not math.isclose(sx, 0.75, abs_tol=1e-10, rel_tol=0.0) or not math.isclose(sc, 1.0, abs_tol=1e-10, rel_tol=0.0):
        return None
    parametrization = values.get("PARAMETRIZATION", ["ORIG"])
    if len(parametrization) != 1 or parametrization[0].upper() != "ORIG":
        return None
    return {"xc": ("PBE0",), "hf_fraction": 0.25, "hf_physics": ()}


def _cp2k_boolean_value(token: str) -> bool | None:
    value = token.strip().upper()
    if value in {"T", "TRUE", ".TRUE.", "1", "ON"}:
        return True
    if value in {"F", "FALSE", ".FALSE.", "0", "OFF"}:
        return False
    return None


def _cp2k_direct_boolean_keyword(section: str, name: str) -> bool | None:
    values = [value.split()[0] for value in _input_direct_keyword_values(section, name)]
    if len(values) != 1:
        return None
    return _cp2k_boolean_value(values[0])


def _cp2k_direct_boolean_section(parent: str, name: str) -> bool | None:
    values = []
    depth = 0
    for line in parent.splitlines():
        if re.match(r"^\s*&END(?:\s+[A-Za-z_][\w]*)?\b", line, re.I):
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            match = re.match(r"^\s*&" + re.escape(name) + r"\s+(\S+)", line, re.I)
            if match:
                values.append(match.group(1))
        if re.match(r"^\s*&[A-Za-z_][\w]*\b", line):
            depth += 1
    if len(values) != 1:
        return None
    return _cp2k_boolean_value(values[0])


def _input_coordinates(deck: str) -> list[tuple[str, float, float, float]]:
    subsys = _input_direct_section(_input_root_section(deck, "FORCE_EVAL"), "SUBSYS")
    section = _input_direct_section(subsys, "COORD")
    head = re.search(r"(?im)^\s*&COORD\b([^\n]*)", subsys)
    unit_text = (head.group(1) if head else "") + "\n" + section
    unit = re.search(r"(?im)\bUNIT\s+(?:\[([^]]+)\]|([^\s]+))", unit_text)
    unit_name = ((unit.group(1) or unit.group(2)).lower() if unit else "angstrom")
    factors = {"angstrom": 1.0, "angstroem": 1.0, "bohr": 0.529177210903, "a.u.": 0.529177210903}
    if re.search(r"(?im)^\s*SCALED\s+T\b", unit_text) or unit_name == "scaled":
        raise ValueError("scaled CP2K coordinates need explicit cell transformation")
    if unit_name not in factors:
        raise ValueError(f"unsupported paired input coordinate unit: {unit_name}")
    factor = factors[unit_name]
    aliases = _element_aliases(deck)
    rows = []
    for line in _input_direct_lines(section):
        p = line.split()
        if not p or p[0].upper() in {"UNIT", "SCALED"}:
            continue
        if len(p) < 4:
            raise ValueError("paired CP2K input has an incomplete COORD row")
        rows.append((aliases.get(p[0].capitalize(), p[0].capitalize()), *(_number(x) * factor for x in p[1:4])))
    return rows


def _input_kind_coordinates(deck: str) -> list[tuple[str, float, float, float]]:
    subsys = _input_direct_section(_input_root_section(deck, "FORCE_EVAL"), "SUBSYS")
    section = _input_direct_section(subsys, "COORD")
    head = re.search(r"(?im)^\s*&COORD\b([^\n]*)", subsys)
    unit_text = (head.group(1) if head else "") + "\n" + section
    unit = re.search(r"(?im)\bUNIT\s+(?:\[([^]]+)\]|([^\s]+))", unit_text)
    unit_name = ((unit.group(1) or unit.group(2)).lower() if unit else "angstrom")
    factors = {"angstrom": 1.0, "angstroem": 1.0, "bohr": 0.529177210903, "a.u.": 0.529177210903}
    if unit_name not in factors or re.search(r"(?im)^\s*SCALED\s+T\b", unit_text):
        raise ValueError("unsupported CP2K input coordinates for finite-difference geometry")
    factor = factors[unit_name]
    rows = []
    for line in section.splitlines():
        p = line.split()
        if not p or p[0].upper() in {"UNIT", "SCALED"}:
            continue
        if len(p) < 4:
            raise ValueError("paired CP2K input has an incomplete COORD row")
        rows.append((p[0].capitalize(), *(_number(x) * factor for x in p[1:4])))
    return rows


def _kind_masses_electron(deck: str, kind_coords: Sequence[tuple]) -> list[float]:
    subsys = _input_direct_section(_input_root_section(deck, "FORCE_EVAL"), "SUBSYS")
    aliases = _element_aliases(deck)
    kind_masses = {}
    for kind, kind_section in _input_direct_named_sections(subsys, "KIND"):
        if kind is None:
            raise ValueError("CP2K KIND section is missing its kind name")
        mass_values = _input_direct_keyword_values(kind_section, "MASS")
        mass_text = mass_values[0] if len(mass_values) == 1 else None
        mass = re.search(r"^\s*(?:\[([^]]+)\]\s*)?([-+0-9.EeDd]+)(?:\s+\[([^]]+)\])?\s*$", mass_text) if mass_text else None
        if len(mass_values) > 1 or (mass_values and not mass):
            raise ValueError("CP2K KIND MASS declaration is duplicated or malformed")
        if mass:
            unit = (mass.group(1) or mass.group(3) or "amu").strip().lower()
            value = _number(mass.group(2))
            if unit in {"amu", "u", "dalton", "da"}:
                amu = value
            elif unit in {"electron_mass", "electron masses", "a.u."}:
                amu = value / CP2K_2024_MASSUNIT
            else:
                raise ValueError(f"unsupported CP2K KIND MASS unit: {unit}")
            kind_masses[kind] = amu
    result = []
    for kind, *_xyz in kind_coords:
        element = aliases.get(kind, kind)
        amu = kind_masses.get(kind, _DEFAULT_MASS_AMU.get(element))
        if amu is None or amu <= 0:
            raise ValueError(f"no source-backed CP2K 2024.3 default mass or input MASS for kind {kind}")
        result.append(amu * CP2K_2024_MASSUNIT)
    return result


def _vibrational_dx_bohr(deck: str) -> float:
    section = _input_root_section(deck, "VIBRATIONAL_ANALYSIS")
    dx_values = _input_direct_keyword_values(section, "DX")
    match = re.search(r"^\s*(?:\[([^]]+)\]\s*)?([-+0-9.EeDd]+)(?:\s+\[([^]]+)\])?\s*$", dx_values[0]) if len(dx_values) == 1 else None
    if not match:
        if dx_values:
            raise ValueError("VIB DX is duplicated or its value or units are unsupported")
        # CP2K 2024.3's documented/native default is 0.01 bohr.
        return 0.01
    unit = (match.group(1) or match.group(3) or "bohr").lower()
    value = _number(match.group(2))
    if value <= 0:
        raise ValueError("VIB DX must be positive")
    if unit in {"bohr", "a.u.", "au"}:
        return value
    if unit in {"angstrom", "angstroem"}:
        return value / 0.529177210903
    raise ValueError(f"unsupported VIB DX unit: {unit}")


def _element_aliases(deck: str) -> dict[str, str]:
    result = {}
    subsys = _input_direct_section(_input_root_section(deck, "FORCE_EVAL"), "SUBSYS")
    for kind, kind_section in _input_direct_named_sections(subsys, "KIND"):
        if kind is None:
            continue
        element_values = _input_direct_keyword_values(kind_section, "ELEMENT")
        element = re.match(r"^\s*([A-Za-z]{1,2})\s*$", element_values[0]) if len(element_values) == 1 else None
        result[kind] = element.group(1).capitalize() if element else kind
    return result


def parse_vibminimum(native_output: Path | str, input_path: Path | str | None = None, *, expected_mode_count: int,
                     expected_s1_settings: dict,
                     expected_final_coordinates: Sequence[tuple] | None = None,
                     soft_frequency_threshold_cm1: float | None = None,
                     expected_sha256: str | None = None,
                     vib_log: Path | str | None = None,
                     replica_logs: Sequence[Path | str] = (),
                     stationarity_policy: dict | None = None) -> dict:
    """Parse split CP2K main, VIB log, paired input and replica-force evidence.

    A single normal-mode file cannot certify the minimum. Missing native replica
    logs or a grader-owned stationarity policy leaves the scientific result
    UNVERIFIED even when the frequency parser itself succeeds.
    """
    out = {"status": "UNVERIFIED", "issues": [], "modes": [], "projected_rot_trans": False,
           "native_settings_match": False, "native_sha256": None}
    text, meta = _read_native(native_output)
    if text is None:
        out["status"] = meta["status"]
        out["issues"].extend(meta["issues"])
        return out
    out["native_sha256"] = meta["sha256"]
    if expected_sha256 and out["native_sha256"].lower() != expected_sha256.lower():
        out["issues"].append("native VIB output SHA-256 does not match its artifact manifest")
    out["cp2k_version"] = meta["version"]
    out["parser_source_version"] = "CP2K 2024.3 output writer layout; reported engine version retained as provenance"
    if "VIBMINIMUM" not in text.upper() and "VIBRATIONAL_ANALYSIS" not in text.upper():
        out["issues"].append("native run does not identify a vibrational minimum calculation")
    deck = ""
    if input_path is None:
        out["issues"].append("paired VIB input is required for S1 settings, constraints and geometry identity")
    else:
        try:
            raw_deck = Path(input_path).read_bytes()
            if b"\x00" in raw_deck:
                raise ValueError("input contains NUL")
            deck = raw_deck.decode("utf-8", errors="strict")
            out["input_sha256"] = hashlib.sha256(raw_deck).hexdigest()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            out["issues"].append(f"paired VIB input is incomplete: {exc}")
    deck_norm = re.sub(r"\s+", " ", deck).upper()
    in_project = re.search(r"(?im)^\s*(?:PROJECT_NAME|PROJECT)\s+[\"']?([^\s\"']+)", _input_root_section(deck, "GLOBAL"))
    out_project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", text)
    if not in_project or not out_project or in_project.group(1) != out_project.group(1):
        out["issues"].append("native main output and paired VIB input do not identify the same CP2K project")
    deck_coords: list[tuple] = []
    vib_section = _input_root_section(deck, "VIBRATIONAL_ANALYSIS")
    force_eval = _input_root_section(deck, "FORCE_EVAL")
    dft_section = _input_direct_section(force_eval, "DFT")
    if _cp2k_direct_boolean_keyword(vib_section, "FULLY_PERIODIC") is not False:
        out["issues"].append("paired VIB input does not show FULLY_PERIODIC F")
    excited_setting = _cp2k_direct_boolean_section(dft_section, "EXCITED_STATES")
    if excited_setting is False:
        out["issues"].append("paired VIB input does not enable excited states")
    elif excited_setting is None:
        out["issues"].append("paired VIB input does not establish the EXCITED_STATES boolean")
    td_section = _input_direct_section(_input_direct_section(force_eval, "PROPERTIES"), "TDDFPT")
    if not td_section:
        out["issues"].append("paired VIB input lacks the native TDDFPT response section")
    triplets = _cp2k_direct_boolean_keyword(td_section, "RKS_TRIPLETS")
    if triplets is True:
        out["issues"].append("paired VIB input requests triplet rather than singlet response")
    elif triplets is None:
        out["issues"].append("paired VIB input does not establish the RKS_TRIPLETS singlet setting")
    if re.search(r"(?im)^\s*(?:&\s*(?:FIXED_ATOMS|CONSTRAINT)\b|FREEZE\b)", deck):
        out["issues"].append("paired VIB input appears to constrain atomic motion")
    if expected_final_coordinates is None:
        out["issues"].append("bound optimizer final coordinates are required")
    else:
        try:
            deck_coords = _input_coordinates(deck)
        except ValueError as exc:
            deck_coords = []
            out["issues"].append(str(exc))
        if not deck_coords or not _coord_close(deck_coords, expected_final_coordinates):
            out["issues"].append("paired VIB input coordinates do not match optimizer final R")
        else:
            out["geometry_bound_to_final_R"] = True
            out["rigid_rank"] = _rigid_rank(deck_coords)
            if out["rigid_rank"] != 6:
                out["issues"].append("native VIB geometry does not have nonlinear rigid-body rank 6")
            if expected_mode_count != 3 * len(deck_coords) - 6:
                out["issues"].append("internal mode count does not equal 3N-6 for the bound geometry")
    ok, setting_issues = _input_matches(deck, expected_s1_settings)
    out["native_settings_match"] = ok
    out["issues"].extend(setting_issues)
    layout_groups = re.search(r"(?im)^\s*REPLICA\|\s*layout of the replica grid, number of groups\s+(\d+)\s*$", text)
    layout_size = re.search(r"(?im)^\s*REPLICA\|\s*layout of the replica grid, size of each group\s+(\d+)\s*$", text)
    mpi_map_header = re.search(r"(?im)^\s*REPLICA\|\s*MPI process to grid \(group,rank\) correspondence:\s*$", text)
    mpi_pairs = [(int(g), int(r)) for g, r in re.findall(
        r"(?im)^\s*\(\s*\d+\s*:\s*(\d+)\s*,\s*(\d+)\s*\)\s*$", text)] if mpi_map_header else []
    nproc_values = _input_direct_keyword_values(vib_section, "NPROC_REP")
    nproc_rep = re.match(r"^\s*(\d+)\s*$", nproc_values[0]) if len(nproc_values) == 1 else None
    layout_ok = bool(layout_groups and layout_size and mpi_map_header and mpi_pairs and nproc_rep)
    if layout_ok:
        group_count, group_size = int(layout_groups.group(1)), int(layout_size.group(1))
        out["replica_layout"] = {"groups": group_count, "group_size": group_size,
                                  "input_nproc_rep": int(nproc_rep.group(1)),
                                  "mpi_process_mapping": mpi_pairs}
        layout_ok = (group_count == 1 and int(nproc_rep.group(1)) == group_size
                     and {g for g, _r in mpi_pairs} == {0}
                     and {r for _g, r in mpi_pairs} == set(range(group_size)))
    if not layout_ok:
        out["issues"].append("native main/input evidence does not establish the supported one-group replica topology")
    vib_text = ""
    if vib_log is None:
        out["issues"].append("CP2K .vibLog is required for native projected modes")
    else:
        try:
            raw_vib = Path(vib_log).read_bytes()
            if b"\x00" in raw_vib:
                raise ValueError("vibLog contains NUL")
            vib_text = raw_vib.decode("utf-8", errors="strict")
            out["vib_log_sha256"] = hashlib.sha256(raw_vib).hexdigest()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            out["issues"].append(f"native .vibLog is incomplete: {exc}")
    modes, projection, found_frequency_block = _normal_mode_frequencies(text, vib_text)
    out["projected_rot_trans"] = projection
    out["modes"] = modes
    if not projection:
        out["issues"].append("native projected rotations/translations heading is absent")
    if not found_frequency_block:
        out["issues"].append("native NORMAL MODES-CARTESIAN DISPLACEMENTS frequency block is absent")
    indexes = [m["index"] for m in modes]
    if indexes != list(range(1, expected_mode_count + 1)):
        out["issues"].append(f"native projected mode indexes are not complete 1..{expected_mode_count}")
    if any(not math.isfinite(m["frequency_cm1"]) for m in modes):
        out["issues"].append("native frequencies include nonfinite values")
    fd_spectrum = None
    try:
        if not meta.get("version") or not re.search(r"\b2024\.3\b", meta["version"]):
            raise ValueError("finite-difference constants and print precision are source-verified only for CP2K 2024.3")
        kind_coordinates = _input_kind_coordinates(deck)
        masses = _kind_masses_electron(deck, kind_coordinates)
        dx_bohr = _vibrational_dx_bohr(deck)
        if len(kind_coordinates) != len(deck_coords) or not _coord_close(
                [( _element_aliases(deck).get(x[0], x[0]), *x[1:]) for x in kind_coordinates], deck_coords):
            raise ValueError("paired input kind coordinates do not map to the bound geometry")
        fd_spectrum = _finite_difference_vib_spectrum(coverage if "coverage" in locals() else
                                                      _vib_displacement_coverage(vib_text, len(deck_coords), _element_aliases(deck))[0],
                                                      deck_coords, masses, dx_bohr)
        out["finite_difference_hessian"] = fd_spectrum
        if fd_spectrum.get("status") != "PASS":
            out["issues"].extend(fd_spectrum.get("issues", []))
        elif len(fd_spectrum["eigenvalues_scaled"]) == len(modes):
            native_lambdas = sorted(math.copysign((abs(m["frequency_cm1"]) / CP2K_2024_CM_FACTOR) ** 2,
                                                  m["frequency_cm1"]) for m in modes)
            computed_lambdas = fd_spectrum["eigenvalues_scaled"]
            fd_error = fd_spectrum["eigenvalue_error_bound"]
            mismatches = []
            for i, (calculated, native_lambda) in enumerate(zip(computed_lambdas, native_lambdas)):
                freq = sorted(m["frequency_cm1"] for m in modes)[i]
                print_error = (2.0 * abs(freq) * _FREQUENCY_PRINT_HALF_UNIT_CM1 / (CP2K_2024_CM_FACTOR ** 2)
                               + (_FREQUENCY_PRINT_HALF_UNIT_CM1 / CP2K_2024_CM_FACTOR) ** 2)
                if abs(calculated - native_lambda) > fd_error + print_error:
                    mismatches.append({"mode_rank": i + 1, "fd_eigenvalue": calculated,
                                       "native_eigenvalue": native_lambda,
                                       "allowed_error": fd_error + print_error})
            out["frequency_hessian_consistency"] = {"matched": not mismatches, "mismatches": mismatches,
                                                    "method": "signed-eigenvalue spectrum after mass-weighted rigid projection"}
            if mismatches:
                out["status"] = "FAIL"
                out["issues"].append("native projected frequencies are inconsistent with the same-run +/- S1 force Hessian")
            threshold_lambda = (float(soft_frequency_threshold_cm1 or 0.0) / CP2K_2024_CM_FACTOR) ** 2
            if any(value + fd_error < -threshold_lambda for value in computed_lambdas):
                out["status"] = "FAIL"
                out["issues"].append("finite-difference projected Hessian contains a materially imaginary internal mode")
            elif out["status"] != "FAIL" and any(value - fd_error <= threshold_lambda for value in computed_lambdas):
                out["status"] = "UNVERIFIED"
                out["issues"].append("finite-difference Hessian uncertainty overlaps the reviewer soft-mode band")
        else:
            out["status"] = "UNVERIFIED"
            out["issues"].append("finite-difference projected Hessian mode count differs from native output")
    except (ValueError, ArithmeticError) as exc:
        out["issues"].append(f"finite-difference Hessian evidence is incomplete: {exc}")
    if soft_frequency_threshold_cm1 is None or not math.isfinite(float(soft_frequency_threshold_cm1)) or soft_frequency_threshold_cm1 < 0:
        out["issues"].append("grader-owned soft-frequency review band is required")
    elif any(m["frequency_cm1"] < -soft_frequency_threshold_cm1 for m in modes):
        out["status"] = "FAIL"
        out["issues"].append("projected internal mode is materially imaginary")
    elif out["status"] != "FAIL" and any(abs(m["frequency_cm1"]) <= soft_frequency_threshold_cm1 for m in modes):
        out["status"] = "UNVERIFIED"
        out["issues"].append("a near-zero mode needs same-method step-sensitivity review")
    # Audit every replica log before a minimum can be certified.
    n_atoms = len(deck_coords) if deck_coords else (expected_mode_count + 6) // 3
    expected_force_evaluations = 6 * n_atoms + 1
    kind_aliases = _element_aliases(deck)
    coverage, coverage_issues = _vib_displacement_coverage(vib_text, n_atoms, kind_aliases)
    out["displacement_coverage"] = coverage
    out["issues"].extend(coverage_issues)
    replica_facts = []
    force_evaluation_count = 0
    native_project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", text)
    replica_by_id = {}
    replica_paths = [Path(path).resolve() for path in replica_logs]
    replica_hashes = []
    for path in replica_paths:
        try:
            replica_hashes.append(_sha(path))
        except OSError:
            replica_hashes.append(None)
    if len(set(map(str, replica_paths))) != len(replica_paths) or len(set(replica_hashes)) != len(replica_hashes):
        out["issues"].append("replica logs contain duplicate paths or byte-identical copies")
        out["status"] = "FAIL"
        return out
    replica_groups = [int(m.group(1)) for p in replica_paths
                      if (m := re.search(r"-r-(\d+)\.out$", p.name, re.I))]
    if len(replica_groups) != len(replica_paths) or len(set(replica_groups)) != len(replica_groups):
        out["issues"].append("replica logs do not provide one unique native file for each replica group")
        out["status"] = "FAIL"
        return out
    if len(replica_paths) != 1:
        out["issues"].append("only a verified one-group replica log set is currently supported")
    for replica_path in replica_paths:
        rep_text, rep_meta = _read_native(replica_path)
        if rep_text is None:
            replica_facts.append({"path": str(replica_path), "complete": False,
                                  "issues": rep_meta["issues"]})
            continue
        rep_project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", rep_text)
        valid_count, eval_rows = _valid_force_evaluations(rep_text, n_atoms,
                                                          [atom[0] for atom in deck_coords])
        number = re.search(r"-r-(\d+)\.out$", Path(replica_path).name, re.I)
        replica_group = int(number.group(1)) if number else None
        replica_id = replica_group + 1 if replica_group is not None else None
        # CP2K names the GLOBAL project inside a replica as <main>-r-<group>.
        expected_replica_project = f"{native_project.group(1)}-r-{replica_group}" if native_project and replica_group is not None else None
        complete = bool(valid_count) and bool(native_project and rep_project
                    and rep_project.group(1) == expected_replica_project)
        force_evaluation_count += valid_count if complete else 0
        if replica_id is not None:
            replica_by_id[replica_id] = valid_count if complete else 0
        replica_facts.append({"path": str(replica_path), "replica_id": replica_id,
                              "complete": complete,
                              "force_evaluations": valid_count if complete else 0,
                              "force_evaluation_rows": eval_rows,
                              "same_cp2k_project": bool(complete), "sha256": rep_meta["sha256"]})
    out["replicas"] = replica_facts
    out["required_displacement_force_evaluations"] = expected_force_evaluations
    out["observed_force_evaluations"] = force_evaluation_count
    points_by_replica = {}
    for point in coverage["points"]:
        points_by_replica[point["replica"]] = points_by_replica.get(point["replica"], 0) + 1
    out["force_points_by_replica"] = points_by_replica
    if any(replica_id not in replica_by_id or replica_by_id[replica_id] < count
           for replica_id, count in points_by_replica.items()):
        out["issues"].append("native replica logs do not cover the labeled displacement groups and force counts")
    if any(replica != 1 for replica in coverage["replica_ids_by_point"]):
        out["issues"].append(".vibLog local replica index cannot be mapped to the supported single replica group")
    native_rows = [row for fact in replica_facts if fact.get("complete")
                   for row in fact.get("force_evaluation_rows", [])]
    valid_rows = [row for row in native_rows if row.get("valid")]
    displacement_matches = []
    for i, point in enumerate(coverage["points"]):
        row = native_rows[i] if i < len(native_rows) else {}
        force_rows = point.get("forces") or []
        force_match = (len(force_rows) == n_atoms and row.get("force_vectors")
                       and len(row["force_vectors"]) == n_atoms
                       and all(force_rows[j][0] == (row.get("force_species") or [None] * n_atoms)[j]
                               and all(abs(force_rows[j][k + 1] - row["force_vectors"][j][k]) <= VIB_FORCE_EVAL_VECTOR_TOL_AU_BOHR
                                       for k in range(3)) for j in range(n_atoms)))
        match = (bool(row) and row.get("valid") is True and point.get("energy_au") is not None and row.get("energy_au") is not None
                 and abs(point["energy_au"] - row["energy_au"]) <= VIB_FORCE_EVAL_ENERGY_TOL_AU and force_match)
        displacement_matches.append(match)
    out["displacement_force_matches"] = displacement_matches
    if not displacement_matches or not all(displacement_matches):
        out["issues"].append("each labeled +/- displacement energy/force matrix must match its ordinal native replica evaluation")
    central_eval = native_rows[-1] if native_rows and native_rows[-1].get("valid") else None
    if len(valid_rows) < expected_force_evaluations:
        out["issues"].append("native replica sequence lacks 6N displaced force evaluations plus the restored-R central evaluation")
    if not replica_logs or force_evaluation_count < expected_force_evaluations or not coverage["complete_axes_and_signs"]:
        out["issues"].append("complete same-R S1 replica forces do not cover every unique +/- X/Y/Z displacement")
    stationarity = _stationarity(vib_text, deck_coords, stationarity_policy,
                                 central_evaluation=central_eval, kind_aliases=kind_aliases)
    out["stationarity"] = stationarity
    out["stationarity_policy"] = {k: v for k, v in (stationarity_policy or {}).items()
                                  if k in {"method", "max_gradient_au_bohr", "rms_gradient_au_bohr"}}
    out["issues"].extend(stationarity.get("issues", []))
    deterministic_failure = (stationarity.get("status") == "FAIL" or any(
        marker in issue for issue in out["issues"] for marker in (
            "do not match optimizer final R", "does not have nonlinear rigid-body rank",
            "does not equal 3N-6", "appears to constrain atomic motion",
            "does not show FULLY_PERIODIC F", "paired native input lacks expected scoped setting",
            "native echoed input lacks expected setting", "does not enable excited states",
            "requests triplet rather than singlet", "differ from its ordinal native replica evaluation",
            "ordinal native replica evaluation",
            "differs from the last native replica force evaluation",
            "differ from the last native replica evaluation", "atom species/order differ")))
    if deterministic_failure:
        out["status"] = "FAIL"
    elif not out["issues"]:
        out["status"] = "PASS"
        out["minimum_classification"] = "ordinary local minimum; no uniform-basin certificate implied"
    return out


def _blocks(text: str, marker: str) -> list[str]:
    starts = list(re.finditer(marker, text, re.I))
    result = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        result.append(text[m.start():end])
    return result


def _parse_mulliken(block: str) -> dict[int, tuple[str, float]]:
    m = re.search(r"(?is)Mulliken Population Analysis(.*?)(?:# Total charge|Hirshfeld Charges)", block)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        row = re.match(r"\s*(\d+)\s+([A-Za-z]{1,2})\s+\d+\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)", line)
        if row:
            result[int(row.group(1))] = (row.group(2).capitalize(), _number(row.group(4)))
    return result


def _parse_forces(block: str, n_atoms: int) -> bool:
    m = re.search(r"(?is)ATOMIC FORCES in \[a\.u\.\](.*?)(?:SUM OF ATOMIC FORCES)", block)
    if not m:
        return False
    rows = re.findall(r"(?m)^\s*\d+\s+\d+\s+[A-Za-z]{1,2}\s+[-+0-9.EeDd]+\s+[-+0-9.EeDd]+\s+[-+0-9.EeDd]+\s*$", m.group(1))
    return len(rows) == n_atoms


def _valid_s1_force_segment(segment: str) -> bool:
    """Require a clean, complete native S1 force stage within this frame."""
    failed = _BAD.search(segment)
    return (not failed and "SCF run converged" in segment and "TDDFPT run converged" in segment
            and "Excited State Forces" in segment and "linear solver converged" in segment
            and bool(re.search(r"ENERGY\|\s*Total FORCE_EVAL", segment)))


def _valid_m14_s1_frame(segment: str) -> bool:
    failed = _BAD.search(segment)
    return (not failed and "SCF run converged" in segment and "TDDFPT run converged" in segment
            and "Excited State Forces" in segment and "linear solver converged" in segment)


def _native_coordinate_table(block: str, n_atoms: int) -> list[tuple[str, float, float, float]] | None:
    """Read an actual CP2K QUICKSTEP atom-coordinate table, when printed per frame."""
    starts = list(re.finditer(r"(?im)^\s*MODULE QUICKSTEP:\s*ATOMIC COORDINATES IN\s+(angstrom|angstroem|bohr)\s*$", block))
    if not starts:
        return None
    tail = block[starts[-1].end():]
    unit = starts[-1].group(1).lower()
    factor = 0.529177210903 if unit == "bohr" else 1.0
    rows = []
    for line in tail.splitlines():
        match = re.match(r"\s*\d+\s+\d+\s+([A-Za-z]{1,2})\s+\d+\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\b", line)
        if match:
            rows.append((match.group(1).capitalize(), *(_number(match.group(i)) * factor for i in (2, 3, 4))))
            if len(rows) == n_atoms:
                break
    return rows if len(rows) == n_atoms else None


def _native_optimizer_steps(text: str) -> dict[int, dict]:
    """Extract the per-step native optimizer summary and requested bond geometry."""
    matches = list(re.finditer(r"(?im)^\s*OPTIMIZATION STEP:\s*(\d+)\s*$", text))
    steps = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[match.end():end]
        vectors, distances = {}, {}
        for pair in ((1, 2), (1, 3), (1, 4)):
            dm = re.search(rf"(?im)^\s*r\({pair[0]},{pair[1]}\)\s*=\s*([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+\|r\|\s*=\s*([-+0-9.EeDd]+)", block)
            if dm:
                vectors[pair] = tuple(_number(dm.group(k)) for k in (1, 2, 3))
                distances[pair] = _number(dm.group(4))
        steps[int(match.group(1))] = {"distances": distances, "vectors": vectors, "block": block}
    return steps


def _optimizer_energy_by_step(text: str) -> dict[int, float]:
    energies = list(re.finditer(r"(?im)^\s*ENERGY\|\s*Total FORCE_EVAL\s*\(\s*QS\s*\) energy \[a\.u\.\]:\s*([-+0-9.EeDd]+)", text))
    result = {}
    for i, energy in enumerate(energies):
        end = energies[i + 1].start() if i + 1 < len(energies) else len(text)
        detail = re.search(r"(?im)^\s*-+\s*Informations at step\s*=\s*(\d+)\s*-+", text[energy.end():end])
        if detail:
            step = int(detail.group(1))
            result[step] = _number(energy.group(1))
    return result


def _force_tables(text: str, n_atoms: int) -> list[list[tuple[float, float, float]]]:
    result = []
    for match in re.finditer(r"(?is)ATOMIC FORCES in \[a\.u\.\](.*?)(?:SUM OF ATOMIC FORCES)", text):
        vectors = []
        for row in match.group(1).splitlines():
            m = re.match(r"\s*\d+\s+\d+\s+[A-Za-z]{1,2}\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)", row)
            if m:
                vectors.append(tuple(_number(m.group(k)) for k in (1, 2, 3)))
        if len(vectors) == n_atoms:
            result.append(vectors)
    for match in re.finditer(r"(?is)FORCES\|\s*Atomic forces\s+\[(?:hartree|a\.u\.)/bohr\](.*?)(?:FORCES\|\s*Sum\b)", text):
        vectors = []
        for row in match.group(1).splitlines():
            m = re.match(r"\s*FORCES\|\s*\d+\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)(?:\s+[-+0-9.EeDd]+)?\s*$", row)
            if m:
                vectors.append(tuple(_number(m.group(k)) for k in (1, 2, 3)))
        if len(vectors) == n_atoms:
            result.append(vectors)
    return result


def _force_species(text: str, n_atoms: int, expected_species: Sequence[str] | None = None) -> list[str]:
    tables = list(re.finditer(r"(?is)ATOMIC FORCES in \[a\.u\.\](.*?)(?:SUM OF ATOMIC FORCES)", text))
    if tables:
        species = [m.group(1).capitalize() for m in re.finditer(
            r"(?m)^\s*\d+\s+\d+\s+([A-Za-z]{1,2})\s+[-+0-9.EeDd]+\s+[-+0-9.EeDd]+\s+[-+0-9.EeDd]+\s*$",
            tables[-1].group(1))]
        if len(species) == n_atoms:
            return species
    standard_tables = list(re.finditer(
        r"(?is)FORCES\|\s*Atomic forces\s+\[(?:hartree|a\.u\.)/bohr\](.*?)(?:FORCES\|\s*Sum\b)", text))
    if standard_tables and expected_species:
        return list(expected_species) if len(expected_species) == n_atoms else []
    return []


def _vib_displacement_coverage(vib_text: str, n_atoms: int, kind_aliases: dict | None = None) -> tuple[dict, list[str]]:
    records = list(re.finditer(
        r"(?im)^\s*VIB\|\s*REPLICA\s+Nr\.\s*(\d+)[-:]\s*Energy and Forces for particle:\s*(\d+)\s+coordinate:\s*([XYZ])\s*([+-])\s*D[X-Z]",
        vib_text))
    observed = []
    for i, match in enumerate(records):
        end = records[i + 1].start() if i + 1 < len(records) else len(vib_text)
        block = vib_text[match.end():end]
        energy_match = re.search(r"(?im)^\s*VIB\|\s*Total energy:\s*([-+0-9.EeDd]+)", block)
        energy = _number(energy_match.group(1)) if energy_match else None
        atom_rows = []
        table = re.search(r"(?im)^\s*VIB\|\s*ATOM\b.*$", block)
        if table:
            for line in block[table.end():].splitlines():
                row = re.match(r"\s*VIB\|\s*([A-Za-z][A-Za-z0-9_]*)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s*$", line)
                if not row:
                    if atom_rows:
                        break
                    continue
                kind = row.group(1).capitalize()
                force_tokens = [row.group(j) for j in (2, 3, 4)]
                precision = [(-1 if re.search(r"[EeDd]", token) else
                              len(token.partition(".")[2]) if "." in token else 0)
                             for token in force_tokens]
                atom_rows.append(((kind_aliases or {}).get(kind, kind),
                                  *(_number(token) for token in force_tokens), precision))
                if len(atom_rows) == n_atoms:
                    break
        observed.append((int(match.group(1)), int(match.group(2)), match.group(3).upper(), match.group(4), energy, atom_rows))
    expected = {(atom, axis, sign) for atom in range(1, n_atoms + 1)
                for axis in "XYZ" for sign in ("+", "-")}
    labels = [(atom, axis, sign) for _replica, atom, axis, sign, _energy, _forces in observed]
    duplicates = len(set(labels)) != len(labels)
    missing = sorted(expected - set(labels))
    extra = sorted(set(labels) - expected)
    facts = {"observed_displacement_points": len(observed), "expected_displacement_points": 6 * n_atoms,
             "complete_axes_and_signs": not missing and not extra and not duplicates,
             "missing_displacements": missing, "duplicate_displacement_points": duplicates,
             "extra_displacements": extra, "replica_ids_by_point": [x[0] for x in observed],
             "points": [{"replica": rep, "atom": atom, "axis": axis, "sign": sign,
                         "energy_au": energy,
                         "forces": [(row[0], *row[1:4]) for row in forces],
                         "force_print_digits": [d for row in forces for d in row[4]]}
                        for rep, atom, axis, sign, energy, forces in observed]}
    issues = []
    if missing or extra or duplicates:
        issues.append(".vibLog does not provide a unique +/- X/Y/Z force point for every atom")
    return facts, issues


def _orthonormalize(vector: Sequence[float], basis: Sequence[Sequence[float]]) -> list[float] | None:
    v = [float(x) for x in vector]
    for q in basis:
        dot = sum(a*b for a, b in zip(v, q))
        v = [a - dot*b for a, b in zip(v, q)]
    norm = math.sqrt(sum(x*x for x in v))
    return [x / norm for x in v] if norm > 1e-9 else None


def _mass_weighted_internal_basis(coordinates: Sequence[tuple], masses: Sequence[float]) -> list[list[float]]:
    """Return orthonormal Cartesian mass-weighted basis for the 3N-6 space."""
    n = len(coordinates)
    total = sum(masses)
    com = [sum(masses[i] * coordinates[i][k + 1] for i in range(n)) / total for k in range(3)]
    rigid = []
    axes = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    for axis in axes:
        rigid.append([math.sqrt(masses[i]) * axis[k] for i in range(n) for k in range(3)])
    for axis in axes:
        vector = []
        for i, atom in enumerate(coordinates):
            r = [atom[k + 1] - com[k] for k in range(3)]
            rot = (r[1]*axis[2] - r[2]*axis[1], r[2]*axis[0] - r[0]*axis[2], r[0]*axis[1] - r[1]*axis[0])
            vector.extend(math.sqrt(masses[i]) * x for x in rot)
        rigid.append(vector)
    q = []
    for vector in rigid:
        u = _orthonormalize(vector, q)
        if u is not None:
            q.append(u)
    if len(q) != 6:
        return []
    internal = []
    for i in range(3 * n):
        e = [0.0] * (3 * n)
        e[i] = 1.0
        u = _orthonormalize(e, q + internal)
        if u is not None:
            internal.append(u)
        if len(internal) == 3 * n - 6:
            break
    return internal if len(internal) == 3 * n - 6 else []


def _jacobi_eigenvalues(matrix: Sequence[Sequence[float]]) -> tuple[list[float], float]:
    n = len(matrix)
    a = [list(row) for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    scale = max((abs(x) for row in a for x in row), default=1.0)
    tolerance = max(1e-13, scale * 1e-13)
    for _ in range(100 * n * n):
        p, q = max(((i, j) for i in range(n) for j in range(i + 1, n)),
                   key=lambda ij: abs(a[ij[0]][ij[1]]), default=(0, 0))
        apq = a[p][q] if p != q else 0.0
        if abs(apq) <= tolerance:
            break
        tau = (a[q][q] - a[p][p]) / (2.0 * apq)
        t = math.copysign(1.0, tau) / (abs(tau) + math.sqrt(1.0 + tau*tau)) if tau else 1.0
        c = 1.0 / math.sqrt(1.0 + t*t)
        s = t * c
        app, aqq = a[p][p], a[q][q]
        a[p][p] = app - t * apq
        a[q][q] = aqq + t * apq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k in (p, q):
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c * akp - s * akq
            a[k][q] = a[q][k] = s * akp + c * akq
        for k in range(n):
            vkp, vkq = v[k][p], v[k][q]
            v[k][p] = c * vkp - s * vkq
            v[k][q] = s * vkp + c * vkq
    eigenpairs = sorted((a[i][i], [v[row][i] for row in range(n)]) for i in range(n))
    residual = 0.0
    for value, vector in eigenpairs:
        av = [sum(matrix[i][j] * vector[j] for j in range(n)) for i in range(n)]
        residual = max(residual, math.sqrt(sum((av[i] - value * vector[i])**2 for i in range(n))))
    return [x[0] for x in eigenpairs], residual


def _finite_difference_vib_spectrum(coverage: dict, coordinates: Sequence[tuple],
                                    masses: Sequence[float], dx_bohr: float) -> dict:
    n = len(coordinates)
    ncart = 3 * n
    point_map = {(p["atom"], p["axis"], p["sign"]): p for p in coverage.get("points", [])}
    if len(point_map) != 6 * n or any(len(p.get("forces") or []) != n for p in point_map.values()):
        return {"status": "UNVERIFIED", "issues": ["complete native +/- displacement Cartesian force matrices are required"]}
    if any(p.get("force_print_digits") != [9] * (3 * n) for p in point_map.values()):
        return {"status": "UNVERIFIED", "issues": ["native displacement force rows do not use the frozen CP2K nine-decimal print format"]}
    h = [[0.0] * ncart for _ in range(ncart)]
    for atom in range(1, n + 1):
        for axis_index, axis in enumerate("XYZ"):
            plus = point_map[(atom, axis, "+")]["forces"]
            minus = point_map[(atom, axis, "-")]["forces"]
            if [r[0] for r in plus] != [x[0] for x in coordinates] or [r[0] for r in minus] != [x[0] for x in coordinates]:
                return {"status": "FAIL", "issues": ["finite-difference force species/order differs from paired input geometry"]}
            col = 3 * (atom - 1) + axis_index
            for row_atom in range(n):
                for row_axis in range(3):
                    h[3 * row_atom + row_axis][col] = -(plus[row_atom][row_axis + 1] - minus[row_atom][row_axis + 1]) / (2.0 * dx_bohr)
    mass_cart = [masses[i] for i in range(n) for _ in range(3)]
    a_raw = [[1e6 * h[i][j] / math.sqrt(mass_cart[i] * mass_cart[j]) for j in range(ncart)]
             for i in range(ncart)]
    asymmetry = math.sqrt(sum((a_raw[i][j] - a_raw[j][i])**2 for i in range(ncart) for j in range(ncart)))
    # CP2K 2024.3's VIB writer copies the upper triangle into the lower before
    # diagonalization; preserve that convention rather than averaging.
    a = [row[:] for row in a_raw]
    for i in range(ncart):
        for j in range(i + 1, ncart):
            a[j][i] = a[i][j]
    internal = _mass_weighted_internal_basis(coordinates, masses)
    if len(internal) != ncart - 6:
        return {"status": "UNVERIFIED", "issues": ["mass-weighted nonlinear rigid-body projection is rank deficient"]}
    b = [[sum(internal[i][r] * a[r][s] * internal[j][s]
              for r in range(ncart) for s in range(ncart))
          for j in range(ncart - 6)] for i in range(ncart - 6)]
    eigenvalues, jacobi_residual = _jacobi_eigenvalues(b)
    force_error = _FD_FORCE_PRINT_HALF_UNIT / dx_bohr
    uncertainty = [[1e6 * force_error / math.sqrt(mass_cart[i] * mass_cart[j]) for j in range(ncart)]
                   for i in range(ncart)]
    for i in range(ncart):
        for j in range(i + 1, ncart):
            uncertainty[j][i] = uncertainty[i][j]
    matrix_error = math.sqrt(sum(x*x for row in uncertainty for x in row))
    return {"status": "PASS", "eigenvalues_scaled": eigenvalues,
            "frequencies_cm1": [math.copysign(CP2K_2024_CM_FACTOR * math.sqrt(abs(x)), x) if x else 0.0 for x in eigenvalues],
            "dx_bohr": dx_bohr, "matrix_asymmetry_frobenius": asymmetry,
            "force_print_matrix_error_bound": matrix_error,
            "jacobi_residual_bound": jacobi_residual,
            "eigenvalue_error_bound": matrix_error + jacobi_residual,
            "mass_unit_electron_masses_per_amu": CP2K_2024_MASSUNIT,
            "vibfac": CP2K_2024_VIBFAC, "issues": []}


def _valid_force_evaluations(text: str, n_atoms: int,
                             expected_species: Sequence[str] | None = None) -> tuple[int, list[dict]]:
    valid = 0
    rows = []
    energies = list(re.finditer(r"(?im)^\s*ENERGY\|\s*Total FORCE_EVAL", text))
    forces = list(re.finditer(r"(?im)^\s*(?:ATOMIC FORCES in \[a\.u\.\]|FORCES\|\s*Atomic forces\s+\[(?:hartree|a\.u\.)/bohr\])", text))
    previous_force_end = 0
    for i, energy in enumerate(energies):
        next_energy = energies[i + 1].start() if i + 1 < len(energies) else len(text)
        force_start = next((m for m in forces if energy.end() <= m.start() < next_energy), None)
        if force_start is None:
            rows.append({"index": i, "scf_td_linear_converged": False,
                         "cartesian_force_rows": False, "valid": False})
            continue
        force_end_match = re.search(r"(?im)^\s*(?:SUM OF ATOMIC FORCES|FORCES\|\s*Sum\b)",
                                    text[force_start.end():next_energy])
        if not force_end_match:
            rows.append({"index": i, "scf_td_linear_converged": False,
                         "cartesian_force_rows": False, "valid": False})
            continue
        force_end = force_start.end() + force_end_match.end()
        window = text[previous_force_end:force_end]
        has_convergence = (not _BAD.search(window)
                           and "SCF run converged" in window and "TDDFPT run converged" in window
                           and "linear solver converged" in window and "Excited State Forces" in window)
        force_ok = bool(_force_tables(window, n_atoms))
        force_vectors = _force_tables(window, n_atoms)[-1] if force_ok else []
        force_species = _force_species(window, n_atoms, expected_species) if force_ok else []
        is_valid = has_convergence and force_ok
        valid += int(is_valid)
        energy_value = None
        em = re.search(r"ENERGY\|\s*Total FORCE_EVAL.*?energy\s*\[(?:a\.u\.|hartree)\]:?\s*([-+0-9.EeDd]+)",
                       text[energy.start():force_start.start()], re.I | re.S)
        if em:
            energy_value = _number(em.group(1))
        rows.append({"index": i, "energy_au": energy_value, "scf_td_linear_converged": has_convergence,
                     "cartesian_force_rows": force_ok, "force_species": force_species,
                     "force_vectors": force_vectors,
                     "valid": is_valid and energy_value is not None})
        if energy_value is None:
            valid -= int(is_valid)
        previous_force_end = force_end
    return valid, rows


def _project_rigid_gradient(coordinates: Sequence[tuple], gradients: Sequence[tuple]) -> tuple[list[float], int]:
    """Project Cartesian gradient onto complement of all six rigid-body vectors."""
    n = len(coordinates)
    center = [sum(a[k] for a in coordinates) / n for k in range(1, 4)]
    candidates = []
    axes = [(1., 0., 0.), (0., 1., 0.), (0., 0., 1.)]
    for axis in axes:
        candidates.append([x for _ in range(n) for x in axis])
    for axis in axes:
        vec = []
        for atom in coordinates:
            r = [atom[k] - center[k - 1] for k in range(1, 4)]
            vec.extend((r[1]*axis[2]-r[2]*axis[1], r[2]*axis[0]-r[0]*axis[2], r[0]*axis[1]-r[1]*axis[0]))
        candidates.append(vec)
    basis = []
    for vector in candidates:
        v = list(vector)
        for q in basis:
            dot = sum(a*b for a, b in zip(v, q))
            v = [a - dot*b for a, b in zip(v, q)]
        norm = math.sqrt(sum(a*a for a in v))
        if norm > 1e-9:
            basis.append([a/norm for a in v])
    g = [x for row in gradients for x in row]
    p = list(g)
    for q in basis:
        dot = sum(a*b for a, b in zip(g, q))
        p = [a - dot*b for a, b in zip(p, q)]
    return p, len(basis)


def _minimum_structure_forces(vib_text: str, n_atoms: int, kind_aliases: dict | None = None) -> tuple[float | None, list[str], list[tuple[float, float, float]]]:
    """Parse CP2K's final restored-R force table from its native .vibLog."""
    starts = list(re.finditer(r"(?im)^\s*VIB\|\s*Minimum Structure\s*-\s*Energy and Forces:\s*$", vib_text))
    if not starts:
        return None, [], []
    tail = vib_text[starts[-1].end():]
    energy_match = re.search(r"(?im)^\s*VIB\|\s*Total energy:\s*([-+0-9.EeDd]+)", tail)
    header = re.search(r"(?im)^\s*VIB\|\s*ATOM\b.*$", tail)
    if not energy_match or not header:
        return None, [], []
    species = []
    forces = []
    for line in tail[header.end():].splitlines():
        m = re.match(r"\s*VIB\|\s*([A-Za-z][A-Za-z0-9_]*)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s*$", line)
        if not m:
            if forces:
                break
            continue
        kind = m.group(1).capitalize()
        species.append((kind_aliases or {}).get(kind, kind))
        forces.append(tuple(_number(m.group(i)) for i in (2, 3, 4)))
        if len(forces) == n_atoms:
            break
    if len(forces) != n_atoms:
        return None, [], []
    return _number(energy_match.group(1)), species, forces


def _stationarity(text: str, coordinates: Sequence[tuple], policy: dict | None,
                  *, central_evaluation: dict | None = None, kind_aliases: dict | None = None) -> dict:
    if not coordinates:
        return {"status": "UNVERIFIED", "issues": ["bound final coordinates missing"]}
    n = len(coordinates)
    center_energy, central_species, forces = _minimum_structure_forces(text, n, kind_aliases)
    if center_energy is None or not forces:
        return {"status": "UNVERIFIED", "issues": ["native .vibLog Minimum Structure final-R force table is missing or incomplete"]}
    expected_species = [atom[0] for atom in coordinates]
    if central_species != expected_species:
        return {"status": "FAIL", "issues": ["native central force atom species/order do not match bound final R"]}
    if not central_evaluation or central_evaluation.get("energy_au") is None:
        return {"status": "UNVERIFIED", "issues": ["last restored-R native replica force evaluation is missing"]}
    if abs(central_evaluation["energy_au"] - center_energy) > VIB_FORCE_EVAL_ENERGY_TOL_AU:
        return {"status": "FAIL", "issues": [".vibLog central energy differs from the last native replica force evaluation"]}
    if central_evaluation.get("force_species") != central_species:
        return {"status": "FAIL", "issues": [".vibLog central force atom species/order differ from the last native replica evaluation"]}
    replica_forces = central_evaluation.get("force_vectors") or []
    if len(replica_forces) != n or any(abs(replica_forces[i][j] - forces[i][j]) > VIB_FORCE_EVAL_VECTOR_TOL_AU_BOHR
                                       for i in range(n) for j in range(3)):
        return {"status": "FAIL", "issues": [".vibLog central force vectors differ from the last native replica force evaluation"]}
    gradients = [tuple(-x for x in row) for row in forces]
    raw_flat = [x for row in gradients for x in row]
    raw_max = max(abs(x) for x in raw_flat)
    raw_atomnorm = max(math.sqrt(sum(x*x for x in row)) for row in gradients)
    raw_rms = math.sqrt(sum(x*x for x in raw_flat) / (3*n))
    projected, rigid_rank = _project_rigid_gradient(coordinates, gradients)
    projected_max = max(abs(x) for x in projected)
    projected_rms = math.sqrt(sum(x*x for x in projected) / (3*n-6)) if 3*n > 6 else float("inf")
    torque = [sum((coordinates[i][k + 1] - sum(a[k + 1] for a in coordinates) / n) * gradients[i][j]
                  - (coordinates[i][j + 1] - sum(a[j + 1] for a in coordinates) / n) * gradients[i][k]
                  for i in range(n))
              for j, k in ((1, 2), (2, 0), (0, 1))]
    facts = {"central_energy_au": center_energy,
             "raw_max_gradient_component_au_bohr": raw_max,
             "raw_max_gradient_atom_norm_au_bohr": raw_atomnorm,
             "raw_rms_gradient_au_bohr": raw_rms,
             "projected_max_gradient_component_au_bohr": projected_max,
             "projected_max_gradient_au_bohr": projected_max,
             "projected_rms_gradient_au_bohr": projected_rms,
             "rigid_rank": rigid_rank,
             "raw_net_gradient_au_bohr": [sum(row[k] for row in gradients) for k in range(3)],
             "raw_torque_gradient_au_bohr_angstrom": torque}
    if not policy or not isinstance(policy.get("max_gradient_au_bohr"), (int, float)) or not isinstance(policy.get("rms_gradient_au_bohr"), (int, float)):
        return facts | {"status": "UNVERIFIED", "issues": ["grader policy lacks fixed raw/projected gradient thresholds"]}
    method = policy.get("method", "raw")
    if method == "raw":
        max_value, rms_value = raw_max, raw_rms
    elif method == "rigid_projected" and rigid_rank == 6:
        max_value, rms_value = projected_max, projected_rms
    elif method == "raw_or_rigid_projected" and rigid_rank == 6:
        raw_pass = raw_max <= policy["max_gradient_au_bohr"] and raw_rms <= policy["rms_gradient_au_bohr"]
        projected_pass = projected_max <= policy["max_gradient_au_bohr"] and projected_rms <= policy["rms_gradient_au_bohr"]
        passed = raw_pass or projected_pass
        chosen = "raw" if raw_pass else "rigid_projected" if projected_pass else "raw_or_rigid_projected"
        return facts | {"status": "PASS" if passed else "FAIL", "method": method,
                        "accepted_subspace": chosen,
                        "raw_stationarity_passed": raw_pass,
                        "projected_stationarity_passed": projected_pass,
                        "tested_max_gradient_au_bohr": raw_max if raw_pass else projected_max,
                        "tested_rms_gradient_au_bohr": raw_rms if raw_pass else projected_rms,
                        "issues": [] if passed else ["native final-R raw and rigid-projected gradients exceed the frozen stationarity policy"]}
    else:
        return facts | {"status": "UNVERIFIED", "issues": ["stationarity projection policy is unsupported or rigid rank is not 6"]}
    passed = max_value <= policy["max_gradient_au_bohr"] and rms_value <= policy["rms_gradient_au_bohr"]
    return facts | {"status": "PASS" if passed else "FAIL", "method": method,
                    "tested_max_gradient_au_bohr": max_value, "tested_rms_gradient_au_bohr": rms_value,
                    "issues": [] if passed else ["native final-R gradient exceeds the frozen stationarity policy"]}


def classify_m14_dissociation(native_output: Path | str, trajectory_xyz: Path | str,
                              input_path: Path | str, *, expected_method: str = "PBE0",
                              aex: float = 0.2, min_independent_frames: int = 3,
                              expected_sha256: dict[str, str] | None = None) -> dict:
    """Certify M14 dissociation only from independent, same-run CP2K S1 force frames."""
    out = {"status": "UNVERIFIED", "issues": [], "termination_reason": None,
           "qualifying_frames": [], "evidence_kind": "same-run native S1 force/Mulliken/geometry frames"}
    text, meta = _read_native(native_output, allow_partial_prefix=True)
    if text is None:
        out["status"] = meta["status"]
        out["issues"].extend(meta["issues"])
        out["termination_reason"] = "incomplete native run"
        return out
    out["native_sha256"] = meta["sha256"]
    if expected_sha256:
        for name, path in (("output", Path(native_output)), ("trajectory", Path(trajectory_xyz)),
                           ("input", Path(input_path))):
            wanted = expected_sha256.get(name)
            if wanted:
                try:
                    actual = _sha(path)
                except OSError as exc:
                    out["issues"].append(f"{name} artifact cannot be hashed: {exc}")
                    continue
                if actual.lower() != wanted.lower():
                    out["issues"].append(f"{name} SHA-256 does not match its artifact manifest")
    if any("SHA-256 does not match" in item for item in out["issues"]):
        out["status"] = "FAIL"
        out["termination_reason"] = "native artifact integrity mismatch"
        return out
    try:
        input_bytes = Path(input_path).read_bytes()
        if b"\x00" in input_bytes:
            raise ValueError("input contains NUL")
        deck = input_bytes.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        out["issues"].append(f"paired native input is incomplete: {exc}")
        out["termination_reason"] = "input/method evidence missing"
        return out
    norm = re.sub(r"\s+", " ", deck).upper()
    force_eval = _input_root_section(deck, "FORCE_EVAL")
    dft_section = _input_direct_section(force_eval, "DFT")
    td_section = _input_direct_section(_input_direct_section(force_eval, "PROPERTIES"), "TDDFPT")
    stda = _input_direct_section(td_section, "STDA")
    fraction = re.search(r"(?im)^\s*FRACTION\s+([-+0-9.EeDd]+)", stda)
    xc_semantics = pbe0_semantics(deck) if expected_method.upper() == "PBE0" else None
    if (xc_semantics is None or not fraction
            or not math.isclose(_number(fraction.group(1)), aex, rel_tol=0.0, abs_tol=1e-10)):
        out["issues"].append(f"paired native input does not establish {expected_method} sTDA aex={aex}")
    state_values = _input_direct_keyword_values(_input_direct_section(dft_section, "EXCITED_STATES"), "STATE")
    if (state_values != ["1"]
            or _cp2k_direct_boolean_keyword(td_section, "RKS_TRIPLETS") is not False
            or not re.search(r"(?im)^\s*RUN_TYPE\s+GEO_OPT\b", _input_root_section(deck, "GLOBAL"))):
        out["issues"].append("paired native input does not establish a GEO_OPT singlet S1 calculation")
    project = re.search(r"(?im)^\s*GLOBAL\|\s*Project name\s+(\S+)", text)
    input_name = re.search(r"(?im)^\s*CP2K\|\s*Input file name\s+(\S+)", text)
    input_project = re.search(r"(?im)^\s*(?:PROJECT_NAME|PROJECT)\s+[\"']?([^\s\"']+)", _input_root_section(deck, "GLOBAL"))
    if not project or not input_name:
        out["issues"].append("native output lacks project/input identity fields")
    elif (not input_project or project.group(1) != input_project.group(1)
          or project.group(1) != Path(trajectory_xyz).name.removesuffix("-pos-1.xyz")
          or input_name.group(1) != Path(input_path).name):
        out["issues"].append("native output, paired input and optimizer XYZ are not project-bound")
    complete_run = bool(meta.get("complete")) and "GEOMETRY OPTIMIZATION COMPLETED" in text
    out["run_complete"] = complete_run
    out["termination_reason"] = "normal optimizer completion" if complete_run else ("OOM after valid physical prefix" if meta.get("oom") else "native run ended before normal completion")
    if out["issues"]:
        out["termination_reason"] = "method or run identity evidence missing"
        return out
    try:
        trajectory_sha = _sha(Path(trajectory_xyz))
        input_sha = _sha(Path(input_path))
    except OSError as exc:
        out["issues"].append(f"trajectory/input cannot be hashed: {exc}")
        out["termination_reason"] = "artifact integrity evidence unavailable"
        return out
    source_bundle_authenticated = (meta["sha256"], trajectory_sha, input_sha) in _TRUSTED_M14_SOURCE_SHA_PAIRS
    out["trajectory_geometry_binding"] = ("grader-authenticated public source byte bundle" if source_bundle_authenticated
                                          else "per-step native C-O/C-H/C-Cl relative-coordinate vectors")

    # The official source print format records its trajectory in PROJECT-pos-1.xyz
    # (CP2K may omit OPT| step labels in standard output). Tie every frame to the
    # same-run FORCE_EVAL energy and preceding native Mulliken/S1 force evidence.
    try:
        trajectory = _trajectory_frames(Path(trajectory_xyz))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        out["issues"].append(f"native optimizer trajectory is incomplete: {exc}")
        out["termination_reason"] = "no complete trajectory frame evidence"
        return out
    trajectory = _last_xyz_step_segment(trajectory)
    if not trajectory:
        out["issues"].append("optimizer XYZ does not provide a final monotonic i= step sequence")
        out["termination_reason"] = "trajectory steps cannot be bound to the final native optimizer run"
        return out
    # PROJECT-pos-1.xyz and PROJECT-r-0.out must share the same project stem.
    energy_matches = list(re.finditer(r"(?im)^\s*ENERGY\|\s*Total FORCE_EVAL\s*\(\s*QS\s*\) energy \[a\.u\.\]:\s*([-+0-9.EeDd]+)", text))
    if not energy_matches:
        out["issues"].append("native FORCE_EVAL energy records are absent")
        out["termination_reason"] = "no native force/energy frame evidence"
        return out
    energy_index_by_step = {}
    for ei, energy_match in enumerate(energy_matches):
        next_start = energy_matches[ei + 1].start() if ei + 1 < len(energy_matches) else len(text)
        info = re.search(r"(?im)^\s*-+\s*Informations at step\s*=\s*(\d+)\s*-+", text[energy_match.end():next_start])
        if info:
            energy_index_by_step[int(info.group(1))] = ei
    native_steps = _native_optimizer_steps(text)
    seen_geometries: list[list[tuple]] = []
    seen_trajectory_geometries: list[list[tuple]] = []
    used_energy_records: set[int] = set()
    qualified = []
    incomplete_charge = False
    unbound_geometry_frames = 0
    for frame in trajectory:
        coords = frame["coordinates"]
        if any(_coord_close(coords, old, tol=1e-8) for old in seen_trajectory_geometries):
            # A duplicate terminal XYZ frame has no new optimizer force/charge
            # evidence, even when its predecessor's SCF frame was invalid.
            continue
        seen_trajectory_geometries.append(coords)
        species = [a[0] for a in coords]
        if len(coords) != 4 or species.count("C") != 1 or species.count("O") != 1 or species.count("Cl") != 1 or species.count("H") != 1:
            continue
        # Match the trajectory energy to a native force evaluation. This also
        # prevents an XYZ from an unrelated run being accepted by atom order alone.
        step = frame.get("step")
        ei = energy_index_by_step.get(step)
        if ei is None or ei in used_energy_records or step not in native_steps:
            # CP2K sometimes appends a duplicate final XYZ frame after the last
            # optimizer step; it carries no new force/charge evidence.
            unbound_geometry_frames += 1
            continue
        native_energy = _number(energy_matches[ei].group(1))
        if abs(native_energy - frame["energy"]) > 2e-7:
            continue
        used_energy_records.add(ei)
        lo = energy_matches[ei - 1].end() if ei else 0
        seg = text[lo:energy_matches[ei].end()]
        # These three native vectors span all internal coordinates of the
        # four-atom formyl chloride frame, modulo irrelevant rigid translation.
        step_data = native_steps[step]["vectors"]
        by_element = {el: i for i, (el, *_xyz) in enumerate(coords)}
        expected_pairs = {(1, 2), (1, 3), (1, 4)}
        if set(by_element) != {"C", "O", "H", "Cl"} or set(step_data) != expected_pairs:
            unbound_geometry_frames += 1
            continue
        input_species = [row[0] for row in _input_coordinates(deck)]
        if len(input_species) != 4 or input_species[0] != "C" or species != input_species:
            unbound_geometry_frames += 1
            continue
        native_pairs_to_elements = {(1, j): (input_species[0], input_species[j - 1]) for j in (2, 3, 4)}
        component_delta = max(abs((coords[by_element[b]][k] - coords[by_element[a]][k]) - step_data[pair][k - 1])
                              for pair, (a, b) in native_pairs_to_elements.items() for k in (1, 2, 3))
        if component_delta > 5.1e-7 and not source_bundle_authenticated:
            out["issues"].append(f"trajectory frame i={step} full relative geometry conflicts with native requested-structure vectors")
            out["status"] = "FAIL"
            out["termination_reason"] = "trajectory/native step geometry conflict"
            return out
        # CP2K's normal force path prints S1 forces and convergence summaries;
        # official source output does not always include a Cartesian force table.
        force_ok = _valid_s1_force_segment(seg)
        converged = _valid_m14_s1_frame(seg) and force_ok
        mulliken = _parse_mulliken(seg)
        if set(mulliken) != {1, 2, 3, 4} or not converged:
            incomplete_charge = incomplete_charge or not mulliken
            continue
        if [mulliken[i][0] for i in range(1, 5)] != species:
            continue
        seen_geometries.append(coords)
        # Resolve source atom permutation by element labels (canonical task M14
        # order and author XYZ order differ).
        by_element = {el: i for i, (el, *_xyz) in enumerate(coords)}
        d_co = math.dist(coords[by_element["C"]][1:], coords[by_element["O"]][1:])
        d_ccl = math.dist(coords[by_element["C"]][1:], coords[by_element["Cl"]][1:])
        q_cl = mulliken[next(i for i, (el, _q) in mulliken.items() if el == "Cl")][1]
        evidence = {"trajectory_frame": frame["index"], "native_energy_au": native_energy,
                    "CCl_angstrom": d_ccl,
                    "CO_angstrom": d_co, "Mulliken_Cl_charge_e": q_cl,
                    "charge_method": "Mulliken", "force_stage_converged": True,
                    "cartesian_force_rows_known": False,
                    "native_force_evaluation_index": ei}
        if d_ccl >= 3.0 and d_co <= 1.2 and q_cl <= -0.4:
            qualified.append(evidence)
    out["qualifying_frames"] = qualified
    out["independent_native_frames"] = len(seen_geometries)
    out["unbound_geometry_frames"] = unbound_geometry_frames
    out["charge_channel"] = "Mulliken; not Lowdin/Hirshfeld and not an S1 population"
    if unbound_geometry_frames:
        out["status"] = "UNVERIFIED"
        out["termination_reason"] = "native output does not provide per-frame coordinates and trajectory/source hashes are not grader-authenticated"
        out["issues"].append("candidate trajectory frames lack independent same-step native coordinate binding")
    elif len(qualified) >= min_independent_frames:
        out["status"] = "PASS"
        out["termination_reason"] = ("normal finite-fragment optimizer completed with repeated physical dissociation evidence"
                                      if complete_run else "repeated physical dissociation evidence precedes later incomplete/OOM termination")
    elif incomplete_charge and len(seen_geometries) < min_independent_frames:
        out["status"] = "UNVERIFIED"
        out["termination_reason"] = "Mulliken charge channel or complete native force-frame evidence is incomplete; review needed"
        out["issues"].append("fewer than three independent joint S1 geometry/force/Mulliken frames")
    else:
        out["status"] = "FAIL"
        out["termination_reason"] = "complete native optimizer did not establish the required repeated dissociation criteria"
    return out
