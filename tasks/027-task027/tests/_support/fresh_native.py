"""Fresh-run native scientific evidence checks for Case07.

This module is independent of the archive-specific verifier. Parsing primitives
are injected from verify.py so the archive path can remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping

FROZEN_ELEMENTS = ["C"]*6 + ["H"]*4 + ["O"]*4 + ["H"] + ["O", "C"] + ["H"]*4
HARTREE_TO_KCAL = 627.5094740631


def verifier_api(verify_module: Any) -> dict[str, Any]:
    """Adapt the existing verifier's parsers without importing its archive path."""
    return {"confined": verify_module.confined, "sha": verify_module.sha,
            "safe_json": verify_module.safe_json, "parse_xyz": verify_module.parse_xyz,
            "parse_hess": verify_module.parse_hess, "stage_facts": verify_module.stage_facts,
            "aligned_max_difference": verify_module.aligned_max_difference,
            "bond_graph": verify_module.bond_graph,
            "UnsupportedEvidence": verify_module.UnsupportedEvidence}


class FreshCriterionFailure(ValueError):
    def __init__(self, criterion: str, message: str, paths: tuple[str, ...] = ()):
        super().__init__(message)
        self.criterion = criterion
        self.paths = tuple(paths)


@dataclass(frozen=True)
class FreshNativeAudit:
    native_status: str
    connection_status: str
    reason: str
    facts: Mapping[str, Any]


def _stage(api: Mapping[str, Any], final: Path, path: Any, *, opt: bool = False,
           imaginary: int | None = None, registry: Mapping[str, Any] | None = None) -> dict:
    try:
        return api["stage_facts"](final, path, require_opt=opt,
                                  expected_imaginary=imaginary, registry=registry)
    except api["UnsupportedEvidence"]:
        raise
    except ValueError as exc:
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    f"native stage {path} failed raw-output consistency checks: {exc}",
                                    (str(path),)) from exc


def _bond_graph(elements: list[str], coords: list[list[float]]) -> set[tuple[int, int]]:
    radii = {"C": 0.76, "H": 0.31, "O": 0.66}
    return {(i, j) for i in range(len(elements)) for j in range(i+1, len(elements))
            if math.dist(coords[i], coords[j]) < 1.20 * (radii[elements[i]] + radii[elements[j]])}


def _safe(path: Any, api: Mapping[str, Any], final: Path) -> Path:
    return api["confined"](final, path)


def _load_xyz(api: Mapping[str, Any], path: Path) -> tuple[list[str], list[list[float]]]:
    return api["parse_xyz"](path)


def _method_fingerprint(stage_facts: Mapping[str, Any]) -> str:
    return str(stage_facts.get("method_fingerprint", "")).strip().lower()


def _normalize_level(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _level_tokens(value: Any) -> frozenset[str]:
    """Compare method directives without making token order significant."""
    return frozenset(re.findall(r"def2/j|[a-z0-9-]+", _normalize_level(value)))


def _parse_engrad(path: Path) -> dict[str, Any]:
    """Parse the native ORCA 6 .engrad layout: scalar/gradient blocks and
    21 atomic-number plus 3-coordinate rows, with no gradient count line.
    """
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    def section(marker: str) -> list[str]:
        hits = [i for i, line in enumerate(lines) if line.strip() == marker]
        if len(hits) != 1:
            raise ValueError(f"ORCA engrad must contain exactly one {marker} section")
        out = []
        for line in lines[hits[0]+1:]:
            stripped = line.strip()
            if stripped.startswith("#"):
                if out:
                    break
                continue
            if stripped:
                out.extend(stripped.split())
        return out
    atom_count_tokens = section("# Number of atoms")
    if atom_count_tokens != ["21"]:
        raise ValueError("screening engrad must contain 21 atoms")
    energy_tokens = section("# The current total energy in Eh")
    if len(energy_tokens) != 1:
        raise ValueError("ORCA engrad energy section is malformed")
    energy = float(energy_tokens[0])
    gradient_tokens = section("# The current gradient in Eh/bohr")
    if len(gradient_tokens) != 63:
        raise ValueError("ORCA engrad gradient must contain exactly 63 components")
    gradient = [float(x) for x in gradient_tokens]
    atom_rows = section("# The atomic numbers and current coordinates in Bohr")
    if len(atom_rows) != 84:
        raise ValueError("ORCA engrad coordinate block must contain 21 atomic-number/coordinate rows")
    expected_numbers = [6]*6 + [1]*4 + [8]*4 + [1, 8, 6] + [1]*4
    numbers, bohr = [], []
    for i in range(21):
        numbers.append(int(atom_rows[4*i]))
        bohr.extend(float(x) for x in atom_rows[4*i+1:4*i+4])
    if numbers != expected_numbers:
        raise ValueError("screening engrad atom order differs from frozen mapping")
    coords = [[bohr[3*i+k]*0.529177210903 for k in range(3)] for i in range(21)]
    if not math.isfinite(energy) or any(not math.isfinite(x) for x in gradient + [v for row in coords for v in row]):
        raise ValueError("ORCA engrad contains non-finite scientific values")
    return {"energy_au": energy, "gradient": gradient, "coordinates": coords}


def _parse_singlepoint(out: Path, engrad: Path | None, api: Mapping[str, Any], *, gradient: bool):
    text = out.read_text(encoding="utf-8", errors="strict")
    if "ORCA" not in text.upper():
        raise api["UnsupportedEvidence"]("native singlepoint output is not ORCA")
    if "ORCA TERMINATED NORMALLY" not in text:
        raise ValueError("native singlepoint did not terminate normally")
    if not re.search(r"SCF CONVERGED AFTER\s+\d+\s+CYCLES", text):
        raise ValueError("native singlepoint lacks a converged SCF marker")
    energies = re.findall(r"FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)", text)
    if not energies or not math.isfinite(float(energies[-1])):
        raise ValueError("native singlepoint has no finite energy")
    result = {"energy_au": float(energies[-1]), "output_text": text}
    if gradient:
        if engrad is None or engrad.is_symlink() or not engrad.is_file():
            raise ValueError("screening evaluation lacks a native ORCA engrad")
        parsed = _parse_engrad(engrad)
        if abs(parsed["energy_au"] - result["energy_au"]) > 1e-7:
            raise ValueError("native engrad energy differs from ORCA output energy")
        result.update(parsed)
    return result


def _xyz_digest(elements: list[str], coords: list[list[float]]) -> str:
    payload = "\n".join(" ".join([element] + [format(x, ".12f") for x in row])
                        for element, row in zip(elements, coords)) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def _verify_singlepoint_input(input_path: Path, output_text: str, api: Mapping[str, Any],
                             geometry_path: Path | None = None, *, action: str = "SP") -> None:
    text = input_path.read_text(encoding="utf-8", errors="strict")
    geometry_match = re.search(r"(?m)^\*\s+xyzfile\s+0\s+2\s+(\S+)\s*$", text)
    if not geometry_match:
        raise ValueError("singlepoint input must declare neutral doublet xyzfile geometry")
    if geometry_path is not None and (input_path.parent / geometry_match.group(1)).resolve() != geometry_path.resolve():
        raise ValueError("singlepoint input geometry path differs from the reported native geometry")
    lines = re.findall(r"(?im)^\s*!\s*(.+)$", text)
    if len(lines) != 1:
        raise ValueError("singlepoint input must contain one method directive")
    method_line = lines[0].lower().split()
    if "uks" not in method_line or not any(method in method_line for method in ("pbe", "r2scan-3c")):
        raise api["UnsupportedEvidence"]("singlepoint uses a valid but uncalibrated open-shell method family")
    if action == "SP" and not ({"sp", "engrad"} & set(method_line)):
        raise ValueError("pilot job is not an explicit native SP or EnGrad calculation")
    if action == "EnGrad" and "engrad" not in method_line:
        raise ValueError("screening job is not an explicit native EnGrad evaluation")
    echo = re.search(r"(?ms)^\s*INPUT FILE\s*\n[-=]+\s*\n(.*?)^\s*\|\s*\d+>\s+\*{4}END OF INPUT\*{4}", output_text)
    if not echo:
        raise ValueError("ORCA output lacks echoed singlepoint input")
    echoed = [re.sub(r"^\s*\|\s*\d+>\s?", "", x).strip() for x in echo.group(1).splitlines()]
    actual = [x.strip() for x in text.splitlines()]
    while echoed and not echoed[-1]: echoed.pop()
    while actual and not actual[-1]: actual.pop()
    if echoed and re.fullmatch(r"NAME\s*=\s*job\.inp", echoed[0], re.I): echoed.pop(0)
    if echoed != actual:
        raise ValueError("ORCA echoed singlepoint input differs from submitted input")


def _audit_pilots(final: Path, report: Mapping[str, Any], api: Mapping[str, Any]) -> list[dict]:
    pilots = report.get("short_pilots")
    if not isinstance(pilots, list) or not pilots:
        raise FreshCriterionFailure("budgeted_scientific_decisions", "no actual short pilot evidence is reported")
    facts = []
    for pilot in pilots:
        if not isinstance(pilot, Mapping):
            raise ValueError("short pilot record is malformed")
        inp, out = (_safe(pilot.get(k), api, final) for k in ("native_input", "native_output"))
        geometry = _safe(pilot.get("geometry_path"), api, final)
        receipt_path = _safe(pilot.get("receipt_path"), api, final)
        receipt = api["safe_json"](receipt_path)
        if receipt.get("input_sha256") != api["sha"](inp) or receipt.get("output_sha256") != api["sha"](out):
            raise ValueError("pilot receipt does not bind input/output bytes")
        elapsed = float(receipt.get("elapsed_seconds", pilot.get("elapsed_seconds")))
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError("pilot lacks a valid measured elapsed time")
        if receipt.get("status") != "normal" or receipt.get("returncode") != 0:
            facts.append({"status": receipt.get("status"), "elapsed_seconds": elapsed,
                          "method": pilot.get("method")})
            continue
        engrad_path = _safe(pilot.get("native_engrad"), api, final) if pilot.get("native_engrad") else None
        if engrad_path is not None:
            if receipt.get("engrad_sha256") != api["sha"](engrad_path):
                raise ValueError("pilot receipt does not bind its native EnGrad")
            point = _parse_singlepoint(out, engrad_path, api, gradient=True)
            if api["aligned_max_difference"](point["coordinates"], _load_xyz(api, geometry)[1]) > 1e-5:
                raise ValueError("pilot EnGrad geometry differs from its bound input geometry")
        else:
            point = _parse_singlepoint(out, None, api, gradient=False)
        _verify_singlepoint_input(inp, point["output_text"], api, geometry, action="SP")
        elements, _ = _load_xyz(api, geometry)
        if elements != FROZEN_ELEMENTS:
            raise ValueError("pilot geometry atom map differs from the frozen mapping")
        facts.append({"status": "normal", "energy_au": point["energy_au"],
                      "elapsed_seconds": elapsed, "method": pilot.get("method"),
                      "gradient_component_count": len(point["gradient"]) if engrad_path is not None else None})
    if not any(item.get("status") == "normal" for item in facts):
        raise FreshCriterionFailure("budgeted_scientific_decisions", "no short pilot completed a real SCF energy")
    return facts


def _screening(final: Path, report: Mapping[str, Any], api: Mapping[str, Any]) -> dict:
    results = {}
    channels = report.get("channels")
    if not isinstance(channels, Mapping) or set(channels) != {"C1", "C2"}:
        raise ValueError("fresh report must contain exactly C1 and C2 channels")
    for channel in ("C1", "C2"):
        entries = channels[channel].get("screening")
        if not isinstance(entries, list):
            raise ValueError(f"{channel} screening records are malformed")
        successful = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError(f"{channel} screening record is malformed")
            inp, out = (_safe(entry.get(k), api, final) for k in ("native_input", "native_output"))
            geom_path = _safe(entry.get("geometry_path"), api, final)
            receipt_path = _safe(entry.get("receipt_path"), api, final)
            elements, coords = _load_xyz(api, geom_path)
            if elements != FROZEN_ELEMENTS:
                raise ValueError(f"{channel} screening geometry atom map differs")
            receipt = api["safe_json"](receipt_path)
            if (receipt.get("input_sha256") != api["sha"](inp)
                    or receipt.get("output_sha256") != api["sha"](out)):
                raise ValueError(f"{channel} screening receipt does not bind input/output")
            if receipt.get("status") not in {"normal", "timeout", "failed"}:
                raise ValueError(f"{channel} screening receipt status is unsupported")
            if receipt.get("status") != "normal":
                continue
            if receipt.get("returncode") != 0:
                raise ValueError(f"{channel} normal screening receipt has a nonzero return code")
            engrad = _safe(entry.get("native_engrad"), api, final)
            if receipt.get("engrad_sha256") != api["sha"](engrad):
                raise ValueError(f"{channel} screening receipt does not bind engrad")
            point = _parse_singlepoint(out, engrad, api, gradient=True)
            _verify_singlepoint_input(inp, point["output_text"], api, geom_path, action="EnGrad")
            if api["aligned_max_difference"](coords, point["coordinates"]) > 1e-5:
                raise ValueError(f"{channel} engrad coordinates differ from reported screening geometry")
            digest = _xyz_digest(elements, point["coordinates"])
            if entry.get("geometry_sha256") != digest:
                raise ValueError(f"{channel} screening geometry hash differs from actual engrad coordinates")
            try:
                receipt_energy = float(receipt.get("energy_au"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{channel} screening receipt energy is malformed") from exc
            if not math.isfinite(receipt_energy) or abs(receipt_energy - point["energy_au"]) > 1e-7:
                raise ValueError(f"{channel} screening receipt energy differs from native output")
            successful.append({"energy_au": point["energy_au"], "geometry_sha256": digest,
                               "gradient_components": len(point["gradient"]),
                               "output_sha256": api["sha"](out), "engrad_sha256": api["sha"](engrad)})
        unique = {r["geometry_sha256"] for r in successful}
        if len(successful) < 3 or len(unique) < 3:
            raise FreshCriterionFailure("budgeted_scientific_decisions",
                                        f"{channel} has fewer than three distinct successful raw SCF/energy/63-gradient points")
        results[channel] = {"successful_evaluations": len(successful),
                            "distinct_geometries": len(unique), "points": successful}
    return results

def _check_stage_geometry(api: Mapping[str, Any], final: Path, opt_path: Any,
                          freq_path: Any, optfacts: Mapping[str, Any], freqfacts: Mapping[str, Any],
                          label: str) -> list[list[float]]:
    optdir = _safe(opt_path, api, final)
    freqdir = _safe(freq_path, api, final)
    try:
        _, optimized = _load_xyz(api, optdir / "job.xyz")
        _, freq_start = _load_xyz(api, freqdir / "start.xyz")
    except (ValueError, OSError) as exc:
        raise FreshCriterionFailure("native_outputs_internally_consistent", f"{label} optimization/frequency geometry is invalid: {exc}") from exc
    if api["aligned_max_difference"](optimized, freq_start) > 1e-5:
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    f"{label} frequency geometry differs from its converged optimization")
    hess = freqfacts.get("hessian")
    if not isinstance(hess, Mapping) or hess.get("elements") != FROZEN_ELEMENTS:
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    f"{label} frequency Hessian has the wrong atom mapping")
    if api["aligned_max_difference"](optimized, hess["coordinates"]) > 1e-5:
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    f"{label} frequency Hessian geometry differs from optimization")
    return hess["coordinates"]


def _trajectory_frames(path: Path) -> tuple[list[list[str]], list[list[list[float]]], list[float], list[bytes]]:
    """Read complete native XYZ frames, preserving each frame's exact source bytes."""
    raw_lines = path.read_bytes().splitlines(keepends=True)
    lines = [line.decode("utf-8", errors="strict").rstrip("\r\n") for line in raw_lines]
    elements_by_frame, coords_by_frame, energies, raw_frames = [], [], [], []
    cursor = 0
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        try:
            count = int(lines[cursor].strip())
        except ValueError as exc:
            raise ValueError("optimization trajectory contains a malformed frame count") from exc
        if count != len(FROZEN_ELEMENTS) or cursor + count + 1 >= len(lines):
            raise ValueError("optimization trajectory contains an incomplete/non-21-atom frame")
        comment = lines[cursor + 1].strip()
        match = re.search(r"(?:^|\s)E\s+([-+0-9.Ee]+)(?:\s|$)", comment)
        if not match:
            raise ValueError("trajectory frame lacks a native energy comment")
        energy = float(match.group(1))
        if not math.isfinite(energy):
            raise ValueError("trajectory frame energy is non-finite")
        elements, coords = [], []
        for line in lines[cursor + 2:cursor + 2 + count]:
            fields = line.split()
            if len(fields) != 4:
                raise ValueError("trajectory coordinate row is malformed")
            elements.append(fields[0])
            row = [float(value) for value in fields[1:]]
            if not all(math.isfinite(value) for value in row):
                raise ValueError("trajectory contains non-finite coordinates")
            coords.append(row)
        if elements != FROZEN_ELEMENTS:
            raise ValueError("trajectory atom order differs from the frozen mapping")
        elements_by_frame.append(elements)
        coords_by_frame.append(coords)
        energies.append(energy)
        raw_frames.append(b"".join(raw_lines[cursor:cursor + count + 2]))
        cursor += count + 2
    if not energies:
        raise ValueError("optimization trajectory contains no complete frames")
    return elements_by_frame, coords_by_frame, energies, raw_frames


def _chain_geometry_matches(left: list[list[float]], right: list[list[float]], tolerance: float = 1e-5) -> bool:
    return (len(left) == len(right)
            and all(len(a) == len(b) == 3
                    and all(math.isfinite(x) and math.isfinite(y) and abs(x-y) <= tolerance
                            for x, y in zip(a, b))
                    for a, b in zip(left, right)))


def _checked_chain_file(api: Mapping[str, Any], final: Path, relative: Any) -> Path:
    path = _safe(relative, api, final)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"opt-chain evidence is missing or not a regular file: {relative}")
    return path


def _normalized_chain_state(value: Any) -> str:
    """Normalize common sacct state decorations without broadening eligibility."""
    return re.split(r"[+\s]", str(value or "").strip(), maxsplit=1)[0].upper()


def _validate_chain_opt_input(text: str, final_method_fingerprint: str) -> None:
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    method_lines = [line.strip()[1:].strip() for line in lines if re.match(r"^\s*!", line)]
    if len(method_lines) != 1:
        raise ValueError("endpoint opt_chain input must contain one ordinary method directive")
    if re.search(r"(?im)^\s*%basis\b|^\s*%method\s+.*\b(?:functional|method|exchange|correlation|basis)\b", text):
        raise ValueError("endpoint opt_chain input overrides the calibrated method/level")
    tokens = _level_tokens(method_lines[0])
    actions = {token.lower() for token in tokens} & {"opt", "optts", "anfreq", "freq", "sp", "engrad", "irc"}
    if "opt" not in actions or "optts" in actions or len(actions) != 1:
        raise ValueError("endpoint opt_chain segment must be a normal Opt, not OptTS or another action")
    ignored = {"opt", "optts", "anfreq", "freq", "sp", "engrad", "irc", "tightopt",
               "tightscf", "verytightscf", "moread"}
    core = frozenset(token for token in tokens if token not in ignored)
    if core != _level_tokens(final_method_fingerprint):
        raise ValueError("endpoint opt_chain segment method/level differs from final endpoint Opt")


def _validate_opt_chain(api: Mapping[str, Any], final: Path, chain: Any, *,
                        case_id: str, attempt_id: str, signed_seed: list[list[float]],
                        final_opt_path: Any, final_method_fingerprint: str) -> list[dict[str, Any]]:
    """Validate resource-only failed optimization history leading to an endpoint Opt.

    This proves only the provenance link between the signed seed, each terminal
    non-success native attempt, and its successor geometry. Failed segments
    never receive scientific-stage or execution-order credit.
    """
    if (not isinstance(chain, Mapping) or chain.get("schema") != "case07-endpoint-opt-chain/v1"
            or not isinstance(chain.get("segments"), list) or not chain["segments"]):
        raise ValueError("endpoint opt_chain schema/segments are malformed")
    previous_coords = signed_seed
    seen_jobs: set[str] = set()
    checked = []
    for segment in chain["segments"]:
        if not isinstance(segment, Mapping):
            raise ValueError("endpoint opt_chain segment is malformed")
        stage_dir = _safe(segment.get("stage_path"), api, final)
        if stage_dir.is_symlink() or not stage_dir.is_dir():
            raise ValueError("endpoint opt_chain stage directory is missing")
        record_path = _checked_chain_file(api, final, segment.get("scheduler_record_path"))
        inventory_path = _checked_chain_file(api, final, segment.get("inventory_path"))
        trajectory_path = _checked_chain_file(api, final, segment.get("trajectory_path"))
        frame_path = _checked_chain_file(api, final, segment.get("frame_xyz_path"))
        if api["sha"](record_path) != segment.get("scheduler_record_sha256"):
            raise ValueError("endpoint opt_chain scheduler-record hash mismatch")
        if api["sha"](inventory_path) != segment.get("inventory_sha256"):
            raise ValueError("endpoint opt_chain inventory hash mismatch")
        if api["sha"](trajectory_path) != segment.get("trajectory_sha256"):
            raise ValueError("endpoint opt_chain trajectory hash mismatch")
        if api["sha"](frame_path) != segment.get("frame_xyz_sha256"):
            raise ValueError("endpoint opt_chain selected-frame hash mismatch")
        for evidence_path in (record_path, inventory_path, trajectory_path):
            try:
                evidence_path.resolve().relative_to(stage_dir.resolve())
            except ValueError as exc:
                raise ValueError("endpoint opt_chain source evidence escapes its allocation directory") from exc
        record = api["safe_json"](record_path)
        inventory = api["safe_json"](inventory_path)
        scheduler = record.get("scheduler") if isinstance(record, Mapping) else None
        allocated = record.get("allocated") if isinstance(record, Mapping) else None
        if not isinstance(record, Mapping) or not isinstance(inventory, Mapping):
            raise ValueError("endpoint opt_chain record/inventory is malformed")
        if (record.get("schema") != "compchemworld.p04-scheduler-record/v1"
                or record.get("case_id") != case_id or record.get("attempt_id") != attempt_id
                or record.get("state") not in {"TIMEOUT", "CANCELLED"}
                or not isinstance(scheduler, Mapping)
                or record.get("job_id") != str(scheduler.get("allocation_id", ""))
                or record.get("job_id") in seen_jobs):
            raise ValueError("endpoint opt_chain scheduler identity/state is inconsistent")
        seen_jobs.add(record["job_id"])
        if not isinstance(allocated, Mapping):
            raise ValueError("endpoint opt_chain allocation measurements are malformed")
        elapsed = allocated.get("elapsed_seconds")
        raw_sacct = record.get("raw_sacct")
        if (type(elapsed) is not int or elapsed <= 0 or not isinstance(raw_sacct, Mapping)
                or _normalized_chain_state(raw_sacct.get("State")) != record.get("state")
                or record.get("state") not in {"TIMEOUT", "CANCELLED"}
                or str(raw_sacct.get("ElapsedRaw")) != str(elapsed)
                or str(raw_sacct.get("AllocCPUS")) != str(allocated.get("cpus"))):
            raise ValueError("endpoint opt_chain failed allocation scheduler/resource facts are inconsistent")
        start = record.get("started_at_utc")
        end = record.get("ended_at_utc")
        try:
            from datetime import datetime, timedelta, timezone
            start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            offset_minutes = record.get("scheduler_timezone_offset_minutes")
            if type(offset_minutes) is not int:
                raise ValueError("missing scheduler timezone offset")
            raw_start = datetime.fromisoformat(str(raw_sacct.get("Start"))).replace(
                tzinfo=timezone(timedelta(minutes=offset_minutes))).astimezone(timezone.utc)
            raw_end = datetime.fromisoformat(str(raw_sacct.get("End"))).replace(
                tzinfo=timezone(timedelta(minutes=offset_minutes))).astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise ValueError("endpoint opt_chain scheduler interval is malformed") from exc
        if (start_dt.tzinfo is None or end_dt.tzinfo is None
                or start_dt.astimezone(timezone.utc) != raw_start or end_dt.astimezone(timezone.utc) != raw_end
                or (end_dt - start_dt).total_seconds() <= 0
                or abs((end_dt - start_dt).total_seconds() - elapsed) > 1.1):
            raise ValueError("endpoint opt_chain scheduler interval differs from raw scheduler facts")
        declaration = record.get("candidate_stage_declaration")
        if (not isinstance(declaration, Mapping) or declaration.get("stage_id") != record.get("stage_id")
                or segment.get("provider_stage_id") != record.get("stage_id")
                or not isinstance(record.get("stage_id"), str)):
            raise ValueError("endpoint opt_chain provider stage identity is inconsistent")
        if (inventory.get("attempt_id") != attempt_id or inventory.get("job_id") != record.get("job_id")
                or inventory.get("stage_id") != record.get("stage_id")):
            raise ValueError("endpoint opt_chain sealed inventory identity mismatch")
        local_rows = inventory.get("locally_downloaded_files")
        remote_rows = inventory.get("full_remote_inventory")
        if not isinstance(local_rows, list) or not isinstance(remote_rows, list):
            raise ValueError("endpoint opt_chain inventory lacks complete/downloaded file descriptors")
        remote_by_path = {row.get("path"): row for row in remote_rows if isinstance(row, Mapping)}
        if len(remote_by_path) != len(remote_rows):
            raise ValueError("endpoint opt_chain sealed inventory repeats or malforms a remote path")
        local_by_path = {}
        for row in local_rows:
            if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
                raise ValueError("endpoint opt_chain inventory row is malformed")
            rel = row["path"]
            if rel in local_by_path:
                raise ValueError("endpoint opt_chain inventory repeats a path")
            source_path = _checked_chain_file(api, final, f"{segment['stage_path']}/{rel}")
            remote = remote_by_path.get(rel)
            if (source_path.stat().st_size != row.get("bytes") or api["sha"](source_path) != row.get("sha256")
                    or remote is None or remote.get("bytes") != row.get("bytes")
                    or remote.get("sha256") != row.get("sha256")):
                raise ValueError(f"endpoint opt_chain inventory bytes/hash mismatch: {rel}")
            local_by_path[rel] = row
        expected_rows = record.get("expected_outputs")
        if not isinstance(expected_rows, list):
            raise ValueError("endpoint opt_chain scheduler record lacks expected-output facts")
        expected = {row.get("path"): row for row in expected_rows if isinstance(row, Mapping)}
        if len(expected) != len(expected_rows):
            raise ValueError("endpoint opt_chain scheduler record repeats/malforms expected outputs")
        required_present = {"job.sbatch", "slurm-" + record["job_id"] + ".out",
                            "slurm-" + record["job_id"] + ".err", "orca.stdout", "orca.stderr"}
        if set(expected) != required_present | {"native.exitcode", "native-stage-receipt.json"}:
            raise ValueError("endpoint opt_chain scheduler output set differs from the sealed P04 contract")
        for rel in required_present:
            row = expected.get(rel)
            local = local_by_path.get(rel)
            if (not isinstance(row, Mapping) or row.get("present") is not True or local is None
                    or row.get("sha256") != local.get("sha256") or row.get("bytes") != local.get("bytes")):
                raise ValueError(f"endpoint opt_chain lacks hash-bound failed-stage output {rel}")
        for rel in ("native.exitcode", "native-stage-receipt.json"):
            row = expected.get(rel)
            if (not isinstance(row, Mapping) or row.get("present") is not False
                    or row.get("absence_reason") != "not_observed_in_terminal_job_directory"):
                raise ValueError("endpoint opt_chain failed segment must explicitly lack native completion evidence")
        for rel in ("start.xyz", "job.inp", "job_trj.xyz", "orca.stdout"):
            if rel not in local_by_path:
                raise ValueError(f"endpoint opt_chain is missing downloaded native evidence {rel}")
        stage_start_path = _checked_chain_file(api, final, f"{segment['stage_path']}/start.xyz")
        start_elements, stage_start = _load_xyz(api, stage_start_path)
        if start_elements != FROZEN_ELEMENTS or not _chain_geometry_matches(stage_start, previous_coords):
            raise ValueError("endpoint opt_chain stage does not start at its signed/preceding linked geometry")
        inp = _checked_chain_file(api, final, f"{segment['stage_path']}/job.inp").read_text(encoding="utf-8", errors="strict")
        if not re.search(r"(?im)^\s*\*\s+xyzfile\s+0\s+2\s+start\.xyz\s*$", inp):
            raise ValueError("endpoint opt_chain input does not use its hash-bound start.xyz")
        _validate_chain_opt_input(inp, final_method_fingerprint)
        elements, frames, energies, raw_frames = _trajectory_frames(trajectory_path)
        frame_index = segment.get("last_complete_frame_index")
        if type(frame_index) is not int or frame_index != len(frames) - 1:
            raise ValueError("endpoint opt_chain does not select the last complete evaluated trajectory frame")
        try:
            declared_energy = float(segment.get("energy_au"))
            frame_elements, frame_coords = _load_xyz(api, frame_path)
        except (TypeError, ValueError, OSError) as exc:
            raise ValueError("endpoint opt_chain selected frame metadata is malformed") from exc
        if (not math.isfinite(declared_energy) or abs(declared_energy - energies[frame_index]) > 1e-7
                or frame_path.read_bytes() != raw_frames[frame_index]
                or frame_elements != elements[frame_index]
                or not _chain_geometry_matches(frame_coords, frames[frame_index], 1e-8)):
            raise ValueError("endpoint opt_chain frame geometry/energy differs from native trajectory")
        stdout_path = _checked_chain_file(api, final, f"{segment['stage_path']}/orca.stdout")
        output_text = stdout_path.read_text(encoding="utf-8", errors="strict")
        matches = list(re.finditer(r"FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)", output_text))
        coordinate_blocks = []
        for coord_match in re.finditer(r"CARTESIAN COORDINATES \(ANGSTROEM\)", output_text):
            rows = []
            for line in output_text[coord_match.end():].splitlines():
                fields = line.split()
                if len(fields) == 4 and fields[0] in {"C", "H", "O"}:
                    try:
                        values = [float(value) for value in fields[1:]]
                    except ValueError:
                        if rows:
                            break
                        continue
                    rows.append((fields[0], values))
                    if len(rows) == len(FROZEN_ELEMENTS):
                        break
                elif rows:
                    break
            if len(rows) == len(FROZEN_ELEMENTS):
                coordinate_blocks.append((coord_match.start(), rows))
        if (len(matches) != len(energies)
                or len(coordinate_blocks) not in {len(matches), len(matches) + 1}):
            raise ValueError("endpoint opt_chain trajectory and native energy/geometry evaluation counts differ")
        for index, match in enumerate(matches):
            native_energy = float(match.group(1))
            if not math.isfinite(native_energy) or abs(native_energy - energies[index]) > 1e-7:
                raise ValueError("endpoint opt_chain trajectory energy differs from native ORCA output")
            preceding_coordinates = [(position, rows) for position, rows in coordinate_blocks
                                     if position < match.start()]
            if len(preceding_coordinates) != index + 1:
                raise ValueError("endpoint opt_chain evaluated geometry sequence is incomplete/inconsistent")
            log_elements = [row[0] for row in preceding_coordinates[-1][1]]
            log_coords = [row[1] for row in preceding_coordinates[-1][1]]
            if (log_elements != FROZEN_ELEMENTS
                    or not _chain_geometry_matches(log_coords, frames[index])):
                raise ValueError("endpoint opt_chain trajectory geometry differs from its native energy evaluation")
            block_end = matches[index + 1].start() if index + 1 < len(matches) else len(output_text)
            block = output_text[match.end():block_end]
            grad_start = block.find("CARTESIAN GRADIENT")
            grad_end = block.find("Difference to translation invariance:", grad_start)
            if grad_start < 0 or grad_end < 0:
                raise ValueError("endpoint opt_chain evaluated frame lacks a complete Cartesian-gradient block")
            rows = []
            for line in block[grad_start:grad_end].splitlines():
                parsed = re.match(r"^\s*\d+\s+([A-Za-z]+)\s*:\s*(\S+)\s+(\S+)\s+(\S+)\s*$", line)
                if parsed:
                    try:
                        rows.append((parsed.group(1), [float(parsed.group(i)) for i in (2, 3, 4)]))
                    except ValueError as exc:
                        raise ValueError("endpoint opt_chain Cartesian gradient is malformed") from exc
            if (len(rows) != len(FROZEN_ELEMENTS)
                    or [row[0] for row in rows] != FROZEN_ELEMENTS
                    or any(not math.isfinite(value) for _, vector in rows for value in vector)):
                raise ValueError("endpoint opt_chain Cartesian gradient atom mapping/components are invalid")
        previous_coords = frames[frame_index]
        checked.append({"job_id": record["job_id"], "stage_id": record["stage_id"],
                        "state": record["state"], "elapsed_seconds": elapsed,
                        "last_complete_frame_index": frame_index, "energy_au": energies[frame_index],
                        "allocated_cpu_seconds": allocated["allocated_cpu_seconds"],
                        "allocated_cpus": allocated["cpus"],
                        "allocated_memory_mib": allocated["memory_mib"],
                        "scientific_stage_credit": False, "execution_order_credit": False})
    endpoint_start_path = _checked_chain_file(api, final, f"{final_opt_path}/start.xyz")
    endpoint_elements, endpoint_start = _load_xyz(api, endpoint_start_path)
    if (endpoint_elements != FROZEN_ELEMENTS
            or not _chain_geometry_matches(endpoint_start, previous_coords)):
        raise ValueError("endpoint optimization does not start at the final linked trajectory frame")
    return checked

def audit_fresh_native(final: Path, report: Mapping[str, Any], api: Mapping[str, Any],
                       reference_geometries: Mapping[str, Mapping[str, Any]],
                       registry: Mapping[str, Any] | None = None) -> FreshNativeAudit:
    """Audit fresh screenings and six selected-channel stationary stages.

    Expected report keys: `selected_channel`; each channel has `screening`,
    `status`, and `validation` with `ts_opt`, `ts_freq`, `seed_minus`,
    `seed_plus`, `displacement`, `endpoint_minus.{opt,freq}`, and
    `endpoint_plus.{opt,freq}`.
    `reference_geometries` is evaluator-pinned BPR/C1/C2 geometry data.
    """
    try:
        pilot_facts = _audit_pilots(final, report, api)
        screen_facts = _screening(final, report, api)
    except api["UnsupportedEvidence"]:
        raise
    except FreshCriterionFailure:
        raise
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise FreshCriterionFailure("budgeted_scientific_decisions",
                                    f"pilot or screening raw evidence is incomplete/inconsistent: {exc}") from exc
    selected = report.get("selected_channel")
    if selected not in {"C1", "C2"}:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "fresh report selected_channel must be C1 or C2")
    channel = report["channels"][selected]
    if channel.get("status") != "validated":
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair",
                                    "selected channel is not declared validated")
    validation = channel.get("validation")
    if not isinstance(validation, Mapping):
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "selected channel validation record is malformed")
    endpoints = {"minus": validation.get("endpoint_minus"),
                 "plus": validation.get("endpoint_plus")}
    if any(not isinstance(v, Mapping)
           or set(v) not in ({"opt", "freq"}, {"opt", "freq", "opt_chain"})
           for v in endpoints.values()):
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "selected channel must provide endpoint Opt/Freq and an optional linked opt_chain")
    if selected not in {"C1", "C2"} or not isinstance(reference_geometries, Mapping):
        raise ValueError("evaluator reference geometry map is missing")
    for role in ("bpr", selected):
        if role not in reference_geometries:
            raise FreshCriterionFailure("saddle_connects_the_claimed_pair", f"evaluator-pinned {role} graph reference is missing")

    stages = {}
    stages["ts_opt"] = _stage(api, final, validation.get("ts_opt"), opt=True, registry=registry)
    stages["ts_freq"] = _stage(api, final, validation.get("ts_freq"), imaginary=1, registry=registry)
    for side in ("minus", "plus"):
        endpoint = endpoints[side]
        stages[f"endpoint_{side}_opt"] = _stage(api, final, endpoint["opt"], opt=True, registry=registry)
        stages[f"endpoint_{side}_freq"] = _stage(api, final, endpoint["freq"], imaginary=0, registry=registry)
    fingerprints = {_method_fingerprint(v) for v in stages.values()}
    if "" in fingerprints or len(fingerprints) != 1:
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    "six selected-channel production stages do not share one parsed method/level")
    # Unknown legal method strings are REVIEW_REQUIRED through the injected stage parser.
    level = next(iter(fingerprints))
    engine_versions = set()
    for item in stages.values():
        output = item.get("output", "")
        version = re.search(r"(?im)Program Version\s+([0-9]+\.[0-9]+\.[0-9]+)", output)
        if not version:
            raise api["UnsupportedEvidence"]("native output lacks a calibrated ORCA version marker")
        engine_versions.add("ORCA " + version.group(1))
    if len(engine_versions) != 1:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "production stages use different ORCA versions")
    declared_engine = str(report.get("engine", "")).strip()
    declared_version = re.search(r"(?i)ORCA\s+([0-9]+\.[0-9]+\.[0-9]+)", declared_engine)
    if not declared_version or ("ORCA " + declared_version.group(1)).lower() not in {x.lower() for x in engine_versions}:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "declared engine version differs from native outputs")
    if level not in {"uks r2scan-3c defgrid3",
                     "uks pbe d3bj def2-svp def2/j ri defgrid3"}:
        raise api["UnsupportedEvidence"]("native method has no calibrated Case07 final-level parser")
    scf_by_stage = {(name.removeprefix("endpoint_") if name.startswith("endpoint_") else name):
                    _normalize_level(item.get("scf_convergence", "unspecified"))
                    for name, item in stages.items()}
    scf_levels = set(scf_by_stage.values())
    scf_review_required = len(scf_levels) != 1 or "unspecified" in scf_levels
    declared_scf = _normalize_level(report.get("scf_convergence"))
    scf_report_inconsistent = (not scf_review_required and declared_scf != next(iter(scf_levels)))
    if scf_review_required:
        declared_by_stage = report.get("scf_convergence_by_stage")
        if isinstance(declared_by_stage, Mapping):
            normalized_declared = {str(key): _normalize_level(value)
                                   for key, value in declared_by_stage.items()}
            if normalized_declared != scf_by_stage:
                scf_report_inconsistent = True
    ts_hess = stages["ts_freq"].get("hessian")
    if not isinstance(ts_hess, Mapping) or ts_hess.get("elements") != FROZEN_ELEMENTS:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "TS Hessian atom mapping is invalid")
    ts_opt_dir = _safe(validation["ts_opt"], api, final)
    ts_freq_dir = _safe(validation["ts_freq"], api, final)
    try:
        ts_opt_input = (ts_opt_dir / "job.inp").read_text(encoding="utf-8", errors="strict")
        ts_freq_input = (ts_freq_dir / "job.inp").read_text(encoding="utf-8", errors="strict")
    except (ValueError, OSError) as exc:
        raise FreshCriterionFailure("native_outputs_internally_consistent", f"TS input is unreadable: {exc}") from exc
    if not re.search(r"(?im)^\s*!.*\bOptTS\b", ts_opt_input):
        raise FreshCriterionFailure("native_outputs_internally_consistent", "fresh transition-state stage is not an OptTS job")
    if not re.search(r"(?im)^\s*!.*\b(?:AnFreq|Freq)\b", ts_freq_input):
        raise FreshCriterionFailure("native_outputs_internally_consistent", "fresh TS frequency stage lacks a frequency action")
    try:
        _, ts_final = _load_xyz(api, ts_opt_dir / "job.xyz")
        _, ts_start = _load_xyz(api, ts_freq_dir / "start.xyz")
    except (ValueError, OSError) as exc:
        raise FreshCriterionFailure("native_outputs_internally_consistent", f"TS optimization/frequency geometry is invalid: {exc}") from exc
    if api["aligned_max_difference"](ts_final, ts_start) > 1e-5:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "TS frequency geometry differs from TS optimization")
    if api["aligned_max_difference"](ts_final, ts_hess["coordinates"]) > 1e-5:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "TS Hessian geometry differs from TS optimization")

    # Reconstruct the two submitted seeds from the current run's actual imaginary mode.
    mode_id = ts_hess["physical_imaginary"][0]
    try:
        displacement = api["safe_json"](_safe(validation.get("displacement"), api, final))
    except (ValueError, KeyError, OSError) as exc:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", f"signed-mode metadata is unreadable: {exc}") from exc
    hess_path = ts_freq_dir / "job.hess"
    try:
        amplitude = float(displacement.get("amplitude_angstrom"))
        frequency = float(displacement.get("frequency_cm1"))
    except (TypeError, ValueError) as exc:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "signed-mode amplitude/frequency metadata is malformed") from exc
    if (displacement.get("mode_index") != mode_id
            or displacement.get("hess_sha256") != api["sha"](hess_path)
            or not math.isfinite(frequency)
            or not math.isclose(frequency, ts_hess["frequencies"][mode_id], abs_tol=0.02)):
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "signed-mode metadata is not bound to the current TS Hessian",
                                    (str(validation.get("displacement")), str(validation.get("ts_freq"))))
    normalization = displacement.get("normalization")
    if not math.isfinite(amplitude) or amplitude <= 0:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "signed-mode displacement amplitude is invalid")
    if displacement.get("mode_vector_convention") != "raw_hess_modes":
        raise api["UnsupportedEvidence"]("signed-mode vector convention is not calibrated for raw ORCA Hessian columns")
    if normalization not in {"max_atom_cartesian", "cartesian_l2"}:
        raise api["UnsupportedEvidence"]("signed-mode normalization convention is unsupported")
    signs = (displacement.get("seed_minus_sign"), displacement.get("seed_plus_sign"))
    if (any(type(sign) is not int for sign in signs)
            or signs not in {(-1, 1), (1, -1)}
            or displacement.get("phase_source") != "eigenvector-as-written"):
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "signed-mode phase metadata is incomplete")
    vector = [[ts_hess["modes"][3*i+k][mode_id] for k in range(3)] for i in range(21)]
    norm = (max(math.sqrt(sum(x*x for x in row)) for row in vector)
            if normalization == "max_atom_cartesian"
            else math.sqrt(sum(x*x for row in vector for x in row)))
    if not math.isfinite(norm) or norm <= 0:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "TS imaginary mode has zero displacement")
    expected_seeds = {sign: [[xyz[k] + sign*amplitude*vec[k]/norm for k in range(3)]
                              for xyz, vec in zip(ts_hess["coordinates"], vector)] for sign in signs}
    seed_coords = []
    for key, sign in (("seed_minus", signs[0]), ("seed_plus", signs[1])):
        try:
            elems, coords = _load_xyz(api, _safe(validation.get(key), api, final))
        except (ValueError, OSError) as exc:
            raise FreshCriterionFailure("saddle_connects_the_claimed_pair", f"{key} geometry is unreadable: {exc}") from exc
        if elems != FROZEN_ELEMENTS:
            raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "signed seed atom ordering differs from frozen map")
        if api["aligned_max_difference"](coords, expected_seeds[sign]) > 1e-5:
            raise FreshCriterionFailure("saddle_connects_the_claimed_pair", f"{key} is not reconstructed from the actual TS mode",
                                        (str(validation.get(key)), str(validation.get("displacement"))))
        seed_coords.append(coords)
    if api["aligned_max_difference"](seed_coords[0], seed_coords[1]) < 1e-4:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair", "signed normal-mode seeds are duplicated")

    endpoint_coords = {}
    opt_chain_facts = {}
    for side in ("minus", "plus"):
        endpoint = endpoints[side]
        endpoint_coords[side] = _check_stage_geometry(
            api, final, endpoint["opt"], endpoint["freq"], stages[f"endpoint_{side}_opt"],
            stages[f"endpoint_{side}_freq"], side)
        optdir = _safe(endpoint["opt"], api, final)
        freqdir = _safe(endpoint["freq"], api, final)
        try:
            opt_input = (optdir / "job.inp").read_text(encoding="utf-8", errors="strict")
            freq_input = (freqdir / "job.inp").read_text(encoding="utf-8", errors="strict")
        except (ValueError, OSError) as exc:
            raise FreshCriterionFailure("native_outputs_internally_consistent", f"{side} endpoint input is unreadable: {exc}") from exc
        if not re.search(r"(?im)^\s*!.*\bOpt\b", opt_input) or re.search(r"(?im)^\s*!.*\bOptTS\b", opt_input):
            raise FreshCriterionFailure("native_outputs_internally_consistent", f"{side} endpoint is not an ordinary Opt job")
        if not re.search(r"(?im)^\s*!.*\b(?:AnFreq|Freq)\b", freq_input):
            raise FreshCriterionFailure("native_outputs_internally_consistent", f"{side} endpoint lacks a frequency calculation")
        try:
            _, opt_start = _load_xyz(api, optdir / "start.xyz")
        except (ValueError, OSError) as exc:
            raise FreshCriterionFailure("saddle_connects_the_claimed_pair", f"{side} endpoint seed input is unreadable: {exc}") from exc
        if "opt_chain" in endpoint:
            try:
                report_attempt = report.get("attempt_id")
                report_case = report.get("case_id")
                if (not isinstance(report_attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", report_attempt)
                        or not isinstance(report_case, str) or not report_case):
                    raise ValueError("opt_chain requires the exact candidate case_id and attempt_id")
                opt_chain_facts[side] = _validate_opt_chain(
                    api, final, endpoint["opt_chain"], case_id=report_case, attempt_id=report_attempt,
                    signed_seed=seed_coords[0 if side == "minus" else 1], final_opt_path=endpoint["opt"],
                    final_method_fingerprint=_method_fingerprint(stages[f"endpoint_{side}_opt"]))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise FreshCriterionFailure("native_outputs_internally_consistent",
                                            f"endpoint {side} opt_chain provenance is invalid: {exc}") from exc
        elif api["aligned_max_difference"](opt_start, seed_coords[0 if side == "minus" else 1]) > 1e-5:
            raise FreshCriterionFailure("saddle_connects_the_claimed_pair",
                                        f"endpoint {side} optimization does not start from its actual signed-mode seed")

    def graph(reference: Mapping[str, Any]) -> set[tuple[int, int]]:
        elems, coords = reference.get("elements"), reference.get("coordinates")
        if elems != FROZEN_ELEMENTS or not isinstance(coords, list) or len(coords) != 21:
            raise ValueError("pinned reaction graph reference does not use the frozen 21-atom mapping")
        return graph_fn(elems, coords)

    graph_fn = api.get("bond_graph", _bond_graph)
    actual_graphs = {side: graph_fn(FROZEN_ELEMENTS, coords) for side, coords in endpoint_coords.items()}
    expected_bpr = graph(reference_geometries["bpr"])
    expected_product = graph(reference_geometries[selected])
    role_by_side = {}
    for side, edges in actual_graphs.items():
        if edges == expected_bpr:
            role_by_side[side] = "bpr"
        elif edges == expected_product:
            role_by_side[side] = "product"
    if set(role_by_side.values()) != {"bpr", "product"}:
        raise FreshCriterionFailure("saddle_connects_the_claimed_pair",
                                    "the two actual signed-mode endpoints do not match BPR and selected-product full graphs")
    bpr_side = next(side for side, role in role_by_side.items() if role == "bpr")
    product_side = next(side for side, role in role_by_side.items() if role == "product")
    energies = {"reactant": stages[f"endpoint_{bpr_side}_freq"]["energy_au"],
                "ts": stages["ts_freq"]["energy_au"],
                "zpe_reactant": stages[f"endpoint_{bpr_side}_freq"]["zpe_au"],
                "zpe_ts": stages["ts_freq"]["zpe_au"]}
    if any(v is None or not math.isfinite(float(v)) for v in energies.values()):
        raise FreshCriterionFailure("native_outputs_internally_consistent", "fresh BPR/TS frequency energies or ZPE are missing")
    barrier = ((float(energies["ts"]) + float(energies["zpe_ts"]))
               - (float(energies["reactant"]) + float(energies["zpe_reactant"]))) * HARTREE_TO_KCAL
    import csv
    barrier_path = _safe("barriers.csv", api, final)
    with barrier_path.open(newline="", encoding="utf-8") as stream:
        barrier_rows = list(csv.DictReader(stream))
    selected_rows = [row for row in barrier_rows if row.get("channel") == selected]
    if len(selected_rows) != 1 or selected_rows[0].get("status") != "validated":
        raise FreshCriterionFailure("native_outputs_internally_consistent", "selected channel barrier row is missing/invalid")
    bpr_freq_path = f"{endpoints[bpr_side]['freq']}/job.out"
    ts_freq_path = f"{validation['ts_freq']}/job.out"
    if selected_rows[0].get("reactant_output") != bpr_freq_path or selected_rows[0].get("ts_output") != ts_freq_path:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "barrier paths do not point to current selected-channel native frequency outputs")
    if _level_tokens(selected_rows[0].get("level")) != _level_tokens(level):
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    "selected-channel barrier level differs from the actual native method fingerprint")
    for field, key in (("e_reactant_au", "reactant"), ("e_ts_au", "ts"),
                       ("zpe_reactant_au", "zpe_reactant"), ("zpe_ts_au", "zpe_ts")):
        try:
            value = float(selected_rows[0][field])
        except (ValueError, TypeError) as exc:
            raise FreshCriterionFailure("native_outputs_internally_consistent", f"barrier {field} is missing/malformed") from exc
        if not math.isfinite(value) or abs(value - float(energies[key])) > 1e-6:
            raise FreshCriterionFailure("native_outputs_internally_consistent", f"barrier {field} differs from fresh native outputs")
    try:
        declared_barrier = float(selected_rows[0]["dft_zpe_barrier_kcal_per_mol"])
    except (ValueError, TypeError) as exc:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "selected-channel barrier is malformed") from exc
    if not math.isfinite(declared_barrier) or abs(declared_barrier - barrier) > 0.05:
        raise FreshCriterionFailure("native_outputs_internally_consistent", "selected-channel barrier does not reproduce from fresh outputs")
    if _level_tokens(report.get("final_level")) != _level_tokens(level):
        raise FreshCriterionFailure("native_outputs_internally_consistent", "declared final level differs from native stages")
    facts = {"selected_channel": selected, "pilots": pilot_facts, "screening": screen_facts,
             "method_fingerprint": level, "stages": stages, "endpoint_graphs": actual_graphs,
             "endpoint_roles": role_by_side, "reactant_side": bpr_side, "product_side": product_side,
             "dft_zpe_barrier_kcal_mol": barrier,
             "resource_only_opt_chains": opt_chain_facts}
    if scf_report_inconsistent:
        raise FreshCriterionFailure("native_outputs_internally_consistent",
                                    "per-stage SCF labels differ from actual native inputs")
    if scf_review_required:
        raise api["UnsupportedEvidence"](
            "SCF settings are mixed or unspecified across otherwise parsed stages; independent review is required")
    return FreshNativeAudit("PASS", "PASS", "fresh screening, stationary points, modes, endpoints, and graph roles are consistent", facts)
