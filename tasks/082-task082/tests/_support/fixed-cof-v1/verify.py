#!/usr/bin/env python3
"""Offline case-07 verifier with deterministic checks and external science review."""
from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import sysconfig
from typing import Any

CASE_ID = "case-07-cof-excited-state-screening"
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
PDF_PINS = {
    "hehn2022_main.pdf": "255c5b1f0a6ea6500a8afadf2252c0200994eaca5e1c9df6e0d7c5f492a0cc27",
    "ct2c00144_si_001.pdf": "6ea0e0c5787b9ba0b3723b06a2752594980a958a5580cf71d9fc761dcb7ef1aa",
}
HELPER_PINS = {
    "parse_workflow.py": "39fc577ff8789f09980b729949c23e4fdaf06e4962d9de7f16e832370403b128",
    "inspect_full_scf.py": "b5acaf86c42a5b46c84d94684ea32744123f6794c39dbb1dce010368c30b146d",
    "inspect_gs_energy.py": "34aff4880c7dce5dfc74b36f1c6d81baf0f62ecd842ddb4d9fc685a86b0a217d",
    "inspect_spectrum_energy.py": "2af956739cd06ba9348b47992df41ddbb7358279aa1ece4ee734d3deb8626064",
    "inspect_s1_energy.py": "c08b33bdecac1a0fbca1aefbc4a33b286b3f19988813245157f524838a8226c5",
    "inspect_geo_opt.py": "498d684a6afcfb888fc2c80def77a9b6226f497469cb50f79cfb5464957314df",
}
SUPPORT_HELPER_PINS = {'science_checks.py': 'ea20b038b4e6549ca4a5598ff1bc5ebdfa12b199a105c3e30c2e8c5347bfe6ac', 'review_protocol.py': '2a0c295104a0bed7462206859dd3674f476e31336ff40b79f48dd354b5be69f2'}
REFS_SHA256 = "849b5db4e89239c31a1ac366e42894a4a3b098660ba80d08690900adfdcb550e"
STAGES = {
    "gs_optimization": ("geo", "GS"),
    "full_spectrum": ("spectrum", "FULL"),
    "stda_spectrum": ("spectrum", "STDA"),
    "full_s1_optimization": ("geo", "S1"),
    "stda_s1_optimization": ("geo", "S1"),
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_SCHEMA = "bench12.case07.provenance/v1"
STAGE_IDS = tuple(STAGES)
REPORT_HEADER = [
    "kernel", "Evert_eV", "Ead_electronic_eV", "Efl_eV", "Stokes_eV",
    "Ead_0-0_eV", "paper_Evert_eV", "paper_Ead_paper_definition_eV",
    "paper_Efl_eV", "paper_Stokes_eV",
]
PAPER_VALUES: dict[str, tuple[str, str, str, str]] = {}
TARGET_COMPOSITION = Counter({"B": 12, "O": 24, "C": 108, "H": 48})


class VerifierError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _load_local_helper(name: str) -> tuple[Any, bytes]:
    """Load a fixed grader helper from the trusted TESTS directory under -I."""
    tests_dir = Path(__file__).resolve(strict=True).parent
    if tests_dir.is_symlink() or not tests_dir.is_dir():
        raise VerifierError("ENV_INVALID", "trusted TESTS directory is unavailable")
    helper_dir = tests_dir / "_support"
    if helper_dir.is_symlink() or not helper_dir.is_dir():
        raise VerifierError("ENV_INVALID", "trusted TESTS directory is unavailable")
    path = helper_dir / f"{name}.py"
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise VerifierError("ENV_INVALID", f"trusted grader helper is not a regular file: {name}")
        data = path.read_bytes()
        expected = SUPPORT_HELPER_PINS.get(name + ".py")
        if expected is None or hashlib.sha256(data).hexdigest() != expected:
            raise VerifierError("ENV_INVALID", f"trusted grader helper hash mismatch: {name}")
    except OSError:
        raise VerifierError("ENV_INVALID", f"trusted grader helper is unavailable: {name}") from None
    module_name = f"_case07_trusted_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise VerifierError("ENV_INVALID", f"trusted grader helper cannot be loaded: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        exec(compile(data, str(path), "exec"), module.__dict__)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise VerifierError("ENV_INVALID", f"trusted grader helper import failed: {type(exc).__name__}") from None
    return module, data


def _base(status: str = "REVIEW_REQUIRED") -> dict[str, Any]:
    result = {
        "case_id": CASE_ID,
        "verifier": "case07-partial-offline/v1",
        "criteria_version": "case07-definition-2026-10-07",
        "status": status,
        "science_validated": False,
        "authenticity_unverified": True,
        "gold_eligible": False,
        "checks": [],
        "problems": [],
        "review_reasons": [],
        "stage_diagnostics": {},
        "scope": "Legacy schema receives diagnostics only; case07 provenance v1 requires deterministic gates and a pinned independent science review.",
    }
    if status == "FAIL":
        result["reward"] = 0
    return result


def _regular_nosymlink(path: Path, *, status: str, label: str) -> None:
    if path.is_symlink():
        raise VerifierError(status, f"{label} is a symlink")
    if not path.exists() or not path.is_file():
        raise VerifierError(status, f"{label} is missing or not a regular file")


def _read_bounded(path: Path, limit: int, *, status: str, label: str) -> bytes:
    _regular_nosymlink(path, status=status, label=label)
    size = path.stat().st_size
    if size <= 0:
        raise VerifierError(status, f"{label} is empty")
    if size > limit:
        # Artifact-size bounds are a format limitation, not a scientific failure.
        bounded_status = "REVIEW_REQUIRED" if status == "FAIL" else status
        raise VerifierError(bounded_status, f"{label} exceeds the supported read bound ({limit} bytes)")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) != size or len(data) > limit:
        raise VerifierError(status, f"{label} changed while being read or exceeds size limit")
    return data


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _check_public_inputs(package_root: Path) -> None:
    override = os.environ.get("CASE07_PUBLIC_INPUTS")
    mounted = Path("/public-inputs")
    root = Path(override) if override else (mounted if mounted.is_dir() else package_root / "inputs")
    if not root.is_absolute():
        raise VerifierError("ENV_INVALID", "CASE07_PUBLIC_INPUTS must be an absolute trusted path")
    if root.is_symlink() or not root.is_dir():
        raise VerifierError("ENV_INVALID", "trusted public-input directory is unavailable or symlinked")
    for name, expected in PDF_PINS.items():
        data = _read_bounded(root / name, 100 * 1024 * 1024, status="ENV_INVALID", label=f"trusted input {name}")
        if _sha(data) != expected:
            raise VerifierError("ENV_INVALID", f"trusted input hash mismatch: {name}")


def _load_helpers(tool_dir: Path) -> dict[str, Any]:
    if not tool_dir.is_absolute() or tool_dir.is_symlink() or not tool_dir.is_dir():
        raise VerifierError("ENV_INVALID", "CASE07_AUTHOR_TOOLS must name an absolute trusted helper directory")
    snapshots: dict[str, bytes] = {}
    for name, expected in HELPER_PINS.items():
        data = _read_bounded(tool_dir / name, MAX_ARTIFACT_BYTES, status="ENV_INVALID", label=f"trusted helper {name}")
        if _sha(data) != expected:
            raise VerifierError("ENV_INVALID", f"trusted helper hash mismatch: {name}")
        snapshots[name] = data
    # Keep candidate APP and the verifier's own tests directory out of import resolution.
    old_path = list(sys.path)
    sys.dont_write_bytecode = True
    stdlib = sysconfig.get_paths()
    safe_stdlib = [stdlib.get("stdlib"), stdlib.get("platstdlib"), sysconfig.get_config_var("DESTSHARED")]
    with tempfile.TemporaryDirectory(prefix="case07-trusted-helpers-") as snapshot_dir:
        for name, data in snapshots.items():
            Path(snapshot_dir, name).write_bytes(data)
        module_names = tuple(Path(name).stem for name in HELPER_PINS)
        prior_modules = {name: sys.modules.pop(name) for name in module_names if name in sys.modules}
        try:
            sys.path[:] = [snapshot_dir] + [p for p in safe_stdlib if p]
            names = ("inspect_geo_opt", "inspect_spectrum_energy")
            modules = {name: importlib.import_module(name) for name in names}
        except Exception as exc:
            raise VerifierError("ENV_INVALID", f"trusted author-helper import failed: {type(exc).__name__}") from None
        finally:
            sys.path[:] = old_path
            for name in module_names:
                sys.modules.pop(name, None)
            sys.modules.update(prior_modules)
    return modules


def _resolve_ref(final: Path, value: Any, where: str) -> tuple[Path, str | None]:
    if isinstance(value, str):
        rel, expected = value, None
    elif isinstance(value, dict) and set(value).issubset({"path", "sha256"}) and isinstance(value.get("path"), str):
        rel, expected = value["path"], value.get("sha256")
    else:
        raise VerifierError("REVIEW_REQUIRED", f"unsupported provenance reference shape at {where}")
    ref = Path(rel)
    if ref.is_absolute() or not rel or any(part in ("..", "") for part in rel.split("/")) or "\\" in rel:
        raise VerifierError("FAIL", f"unsafe provenance path at {where}")
    current = final
    for part in ref.parts:
        current = current / part
        if current.is_symlink():
            raise VerifierError("FAIL", f"symlink in provenance path at {where}")
    try:
        current.resolve(strict=True).relative_to(final.resolve(strict=True))
    except (ValueError, FileNotFoundError, OSError):
        if not current.exists():
            raise VerifierError("FAIL", f"referenced artifact is missing at {where}") from None
        raise VerifierError("FAIL", f"provenance path escapes final at {where}") from None
    _regular_nosymlink(current, status="FAIL", label=f"referenced artifact {where}")
    if expected is not None and (not isinstance(expected, str) or not SHA_RE.fullmatch(expected)):
        raise VerifierError("REVIEW_REQUIRED", f"unsupported sha256 declaration at {where}")
    return current, expected


def _read_candidate_ref(final: Path, ref: Any, where: str) -> tuple[str | None, dict[str, Any]]:
    path, expected = _resolve_ref(final, ref, where)
    data = _read_bounded(path, MAX_ARTIFACT_BYTES, status="FAIL", label=where)
    actual = _sha(data)
    meta = {"path": str(path.relative_to(final)), "sha256": actual, "size_bytes": len(data)}
    if expected is None:
        meta["declared_sha256"] = None
    else:
        meta["declared_sha256"] = expected
        if expected != actual:
            raise VerifierError("FAIL", f"sha256 mismatch at {where}")
    try:
        return data.decode("utf-8"), meta
    except UnicodeDecodeError:
        return None, meta


def _snapshot_final(final: Path) -> tuple[dict[str, dict[str, Any]], str]:
    """Hash every final-tree member and reject links/special files."""
    final_real = final.resolve(strict=True)
    index: dict[str, dict[str, Any]] = {}
    manifest_rows = []
    total_bytes = 0
    for base, dirs, names in os.walk(final, followlinks=False):
        base_path = Path(base)
        for dirname in list(dirs):
            p = base_path / dirname
            mode = p.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise VerifierError("FAIL", f"final contains a symlink or special directory: {p.relative_to(final)}")
        for name in names:
            path = base_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise VerifierError("FAIL", f"final contains a symlink or special file: {path.relative_to(final)}")
            try:
                path.resolve(strict=True).relative_to(final_real)
            except (ValueError, OSError):
                raise VerifierError("FAIL", f"final artifact escapes final tree: {path.relative_to(final)}") from None
            rel = path.relative_to(final).as_posix()
            if not rel or "\\" in rel or any(part in ("", ".", "..") for part in rel.split("/")) or rel in index:
                raise VerifierError("FAIL", "final artifact path is noncanonical or duplicated")
            size = path.stat().st_size
            total_bytes += size
            if total_bytes > 8 * 1024 * 1024 * 1024:
                raise VerifierError("REVIEW_REQUIRED", "final artifact tree exceeds the 8 GiB automatic snapshot bound")
            digest = hashlib.sha256()
            blocks = [] if size <= 16 * 1024 * 1024 else None
            newline_count = 0
            last_byte = b""
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    newline_count += block.count(b"\n")
                    if block:
                        last_byte = block[-1:]
                    if blocks is not None:
                        blocks.append(block)
            sha = digest.hexdigest()
            data = b"".join(blocks) if blocks is not None else None
            line_count = newline_count + (1 if size and last_byte != b"\n" else 0)
            if data is not None:
                try:
                    text_value = data.decode("utf-8")
                    line_count = len(text_value.splitlines())
                except UnicodeDecodeError:
                    line_count = 0
            item = {"path": rel, "bytes": size, "sha256": sha, "line_count": line_count}
            if "sacct" in name.lower() and data is not None:
                item["bytes_data"] = data
            index[rel] = item
            manifest_rows.append({"path": rel, "bytes": size, "sha256": sha})
    if not index:
        raise VerifierError("FAIL", "final artifact tree is empty")
    manifest_rows.sort(key=lambda row: row["path"])
    manifest_sha = hashlib.sha256(json.dumps(manifest_rows, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return index, manifest_sha


def _native_build_digest(local_sources: dict[str, bytes]) -> str:
    # Include the wrapper, all package-local scientific/review logic, the test
    # entry point and each external author parser pin in the review binding.
    rows = {name: hashlib.sha256(data).hexdigest() for name, data in local_sources.items()}
    rows.update({f"author:{name}": digest for name, digest in HELPER_PINS.items()})
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _v1_ref(final: Path, index: dict[str, dict[str, Any]], ref: Any,
            where: str, science: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise VerifierError("FAIL", f"case07 provenance v1 requires path+sha256 at {where}")
    text, meta = _read_candidate_ref(final, ref, where)
    if meta.get("declared_sha256") is None:
        raise VerifierError("FAIL", f"case07 provenance v1 lacks a declared hash at {where}")
    indexed = index.get(meta["path"])
    if indexed is None or indexed["sha256"] != meta["sha256"]:
        raise VerifierError("FAIL", f"case07 provenance v1 ref is outside the artifact snapshot at {where}")
    if text is None:
        raise science.UnsupportedFormat(f"{where} is not a supported UTF-8 text artifact")
    return text, meta


def _safe_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise VerifierError("FAIL", "case07 provenance contains unsupported or nonfinite JSON values") from None


def _reject_nonfinite_numbers(value: Any) -> None:
    if isinstance(value, float) and not __import__("math").isfinite(value):
        raise VerifierError("FAIL", "case07 provenance contains a nonfinite JSON number")
    if isinstance(value, dict):
        for child in value.values():
            _reject_nonfinite_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _reject_nonfinite_numbers(child)


def _decimal_from_report(token: str, label: str, science: Any) -> Decimal:
    try:
        return science.decimal_token(token, label)
    except science.ScienceCheckError as exc:
        raise VerifierError("FAIL", str(exc)) from None


def _validate_case07_v1(final: Path, package_root: Path, provenance: dict[str, Any],
                        artifact_index: dict[str, dict[str, Any]], artifact_manifest_sha: str,
                        author_helpers: dict[str, Any], science: Any, review_protocol: Any,
                        local_sources: dict[str, bytes]) -> dict[str, Any]:
    """Run deterministic v1 checks, then apply the runner-pinned review gate."""
    top_keys = {"schema", "case_id", "criteria_version", "structure", "runtime", "stages"}
    if set(provenance) != top_keys or provenance.get("schema") != PROVENANCE_SCHEMA:
        raise VerifierError("FAIL", "case07 provenance v1 root fields are invalid")
    if provenance.get("case_id") != CASE_ID or provenance.get("criteria_version") != "case07-definition-2026-10-07":
        raise VerifierError("FAIL", "case07 provenance case_id or criteria_version is unsupported")
    checks: list[dict[str, Any]] = []
    problems: list[str] = []
    review_reasons: list[str] = []
    stage_refs: dict[str, dict[str, dict[str, Any]]] = {}
    stage_texts: dict[str, dict[str, str]] = {}
    stage_diagnostics: dict[str, Any] = {}

    structure = provenance.get("structure")
    if not isinstance(structure, dict) or set(structure) != {
            "source_structure", "atom_count", "basis_function_count", "cell_policy", "gs_geometry"}:
        raise VerifierError("FAIL", "case07 provenance structure fields are invalid")
    if type(structure["atom_count"]) is not int or structure["atom_count"] != 192:
        raise VerifierError("FAIL", "case07 structure must declare 192 atoms")
    if type(structure["basis_function_count"]) is not int or structure["basis_function_count"] != 4848:
        raise VerifierError("FAIL", "case07 structure must declare 4848 native basis functions")
    if structure["cell_policy"] != "fixed_database_cell":
        raise VerifierError("FAIL", "case07 structure must identify the fixed database cell policy")
    _, source_meta = _v1_ref(final, artifact_index, structure["source_structure"], "structure.source_structure", science)
    gs_geometry_text, gs_geometry_meta = _v1_ref(final, artifact_index, structure["gs_geometry"], "structure.gs_geometry", science)
    try:
        gs_geometry_frames = science.parse_xyz_frames(gs_geometry_text, "structure.gs_geometry")
    except science.UnsupportedFormat as exc:
        gs_geometry_frames = None
        review_reasons.append(str(exc))
    if gs_geometry_frames is not None and len(gs_geometry_frames) != 1:
        raise VerifierError("FAIL", "structure.gs_geometry must be one endpoint XYZ frame")
    def check_target_composition(frames: list[dict[str, Any]], label: str) -> None:
        for frame in frames:
            composition = Counter(atom["element"] for atom in frame["atoms"])
            if composition != TARGET_COMPOSITION:
                raise VerifierError("FAIL", f"{label} does not have the frozen B12O24C108H48 05001N2 composition")
    if gs_geometry_frames is not None:
        check_target_composition(gs_geometry_frames, "structure.gs_geometry")
    try:
        source_structure_text, _ = _v1_ref(final, artifact_index, structure["source_structure"],
                                           "structure.source_structure", science)
        source_frames = science.parse_xyz_frames(source_structure_text, "structure.source_structure")
        check_target_composition(source_frames, "structure.source_structure")
    except science.UnsupportedFormat:
        review_reasons.append("source structure format requires independent composition and identity review")
    checks.append({"id": "structure_counts_and_references", "status": "PASS",
                   "source_structure": source_meta, "gs_geometry": gs_geometry_meta,
                   "atom_count": 192, "basis_function_count": 4848})

    runtime = provenance.get("runtime")
    if not isinstance(runtime, dict) or set(runtime) != {"cp2k_version", "binary_sha256", "data_sha256", "runtime_evidence"}:
        raise VerifierError("FAIL", "case07 provenance runtime fields are invalid")
    if not isinstance(runtime["cp2k_version"], str) or not runtime["cp2k_version"].strip():
        raise VerifierError("FAIL", "case07 runtime version declaration is malformed")
    def supported_cp2k_unit_version(version: str) -> bool:
        return re.search(r"(?<!\d)(?:9\.1|2024\.3)(?!\d)", version) is not None
    runtime_unit_profile = supported_cp2k_unit_version(runtime["cp2k_version"])
    native_versions: dict[str, list[str]] = {}
    if not runtime_unit_profile:
        review_reasons.append("CP2K version is outside the independently source-checked automatic CODATA unit profile")
    if not isinstance(runtime["binary_sha256"], str) or not SHA_RE.fullmatch(runtime["binary_sha256"]):
        raise VerifierError("FAIL", "case07 runtime binary SHA-256 is malformed")
    data_hashes = runtime["data_sha256"]
    required_data_names = {"BASIS_ccGRB_UZH", "BASIS_ADMM_UZH", "POTENTIAL_UZH", "t_c_g.dat"}
    if not isinstance(data_hashes, dict) or set(data_hashes) != required_data_names or any(
            not isinstance(x, str) or not SHA_RE.fullmatch(x) for x in data_hashes.values()):
        raise VerifierError("FAIL", "case07 CP2K data SHA-256 declarations are incomplete")
    _, runtime_meta = _v1_ref(final, artifact_index, runtime["runtime_evidence"], "runtime.runtime_evidence", science)
    stage_version_mismatch = False

    stages = provenance.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise VerifierError("FAIL", "case07 provenance must declare all five frozen stages exactly once")
    for stage_name, (kind, mode) in STAGES.items():
        entry = stages[stage_name]
        expected_fields = {"input", "native", "geometry"} | ({"trajectory"} if kind == "geo" else set())
        if not isinstance(entry, dict) or set(entry) != expected_fields:
            raise VerifierError("FAIL", f"case07 provenance stage fields are invalid: {stage_name}")
        refs, texts = {}, {}
        for field in expected_fields:
            text_value, meta = _v1_ref(final, artifact_index, entry[field], f"{stage_name}.{field}", science)
            refs[field], texts[field] = meta, text_value
        stage_refs[stage_name], stage_texts[stage_name] = refs, texts
        geometry_text, geometry_meta = _v1_ref(final, artifact_index, entry["geometry"], f"{stage_name}.geometry", science)
        try:
            frames = science.parse_xyz_frames(geometry_text, f"{stage_name}.geometry")
        except science.UnsupportedFormat as exc:
            frames = None
            review_reasons.append(str(exc))
        if frames is not None and len(frames) != 1:
            raise VerifierError("FAIL", f"{stage_name}.geometry must contain exactly one endpoint XYZ frame")
        if frames is not None:
            check_target_composition(frames, f"{stage_name}.geometry")
        if stage_name == "gs_optimization" and gs_geometry_frames is not None and frames is not None:
            try:
                science.compare_xyz_frames(gs_geometry_frames[0], frames[0], "structure and GS final geometry")
            except science.UnsupportedFormat as exc:
                review_reasons.append(str(exc))
        if stage_name == "gs_optimization" and (gs_geometry_frames is None or frames is None):
            review_reasons.append("GS final geometry identity requires review because a geometry format is outside the automatic profile")
        if stage_name in ("full_spectrum", "stda_spectrum") and gs_geometry_frames is not None and frames is not None:
            try:
                science.compare_xyz_frames(gs_geometry_frames[0], frames[0], f"{stage_name} GS geometry")
            except science.UnsupportedFormat as exc:
                review_reasons.append(str(exc))
        elif stage_name in ("full_spectrum", "stda_spectrum"):
            review_reasons.append(f"{stage_name} geometry identity requires review because a geometry format is outside the automatic profile")
        if stage_name.endswith("_s1_optimization"):
            try:
                traj_frames = science.parse_xyz_frames(texts["trajectory"], f"{stage_name}.trajectory")
                check_target_composition(traj_frames, f"{stage_name}.trajectory")
                if frames is not None:
                    try:
                        science.compare_xyz_frames(traj_frames[-1], frames[0], f"{stage_name} trajectory endpoint")
                    except science.UnsupportedFormat as exc:
                        review_reasons.append(str(exc))
                else:
                    review_reasons.append(f"{stage_name} trajectory endpoint identity requires review because geometry format is unsupported")
            except science.UnsupportedFormat as exc:
                review_reasons.append(str(exc))
        elif stage_name == "gs_optimization":
            try:
                traj_frames = science.parse_xyz_frames(texts["trajectory"], f"{stage_name}.trajectory")
                check_target_composition(traj_frames, f"{stage_name}.trajectory")
            except science.UnsupportedFormat as exc:
                review_reasons.append(str(exc))
        try:
            version_matches = re.findall(r"^\s*CP2K\s+version\s+(\S+)", texts["native"], re.IGNORECASE | re.MULTILINE)
            native_versions[stage_name] = version_matches
            if version_matches and any(runtime["cp2k_version"].split()[-1] != v for v in version_matches):
                stage_version_mismatch = True
            if kind == "geo":
                parsed = author_helpers["inspect_geo_opt"].inspect_text(
                    texts["input"], texts["native"], texts["trajectory"], expected_atoms=192, mode=mode)
            else:
                parsed = author_helpers["inspect_spectrum_energy"].inspect_text(
                    texts["input"], texts["native"], expected_atoms=192)
            stage_diagnostics[stage_name] = {"strict_syntax_complete": parsed.get("strict_syntax_complete") is True,
                                             "failed_checks": parsed.get("failed_checks", []),
                                             "native_contract": parsed.get("native_contract", {}),
                                             "input_contract": parsed.get("input_contract", {}),
                                             "artifact_refs": refs}
            if parsed.get("strict_syntax_complete") is not True:
                review_reasons.append(f"author parser profile requires independent review for {stage_name}")
        except Exception as exc:
            stage_diagnostics[stage_name] = {"parser_status": "unsupported_or_exception",
                                             "parser_error": type(exc).__name__, "artifact_refs": refs}
            review_reasons.append(f"native format or parser profile requires independent review for {stage_name}")
    if stage_version_mismatch:
        raise VerifierError("FAIL", "native CP2K version contradicts the submitted runtime declaration")
    unit_profile_supported = runtime_unit_profile and all(
        native_versions.get(stage) and all(supported_cp2k_unit_version(v) for v in native_versions[stage])
        for stage in STAGE_IDS)
    if not unit_profile_supported:
        review_reasons.append("native CP2K version evidence is incomplete or outside the source-checked Hartree/eV profile; converted Ead requires independent unit review")
    checks.append({"id": "five_stage_references_and_geometry_bindings", "status": "PASS",
                   "stages": {name: stage_refs[name] for name in STAGE_IDS}})
    checks.append({"id": "native_energy_unit_profile", "status": "PASS" if unit_profile_supported else "REVIEW_REQUIRED",
                   "supported": unit_profile_supported,
                   "conversion_constant_Ha_to_eV": "27.2113838565563" if unit_profile_supported else None,
                   "source_profiles": ["CP2K 9.1", "CP2K 2024.3"]})

    try:
        gs_auto = science.validate_gs_optimization(stage_texts["gs_optimization"]["native"], label="gs_optimization")
        review_reasons.extend(gs_auto["convergence_review_reasons"])
    except science.UnsupportedFormat as exc:
        gs_auto = None
        review_reasons.append(str(exc))
    # Validate every stage independently. Unsupported GS syntax must not mask
    # a deterministic defect in an otherwise recognizable spectrum/S1 output.
    spectrum_data = {}
    for name, kernel in (("full_spectrum", "FULL"), ("stda_spectrum", "STDA")):
        try:
            spectrum_data[name] = science.validate_spectrum(stage_texts[name]["native"], kernel=kernel, label=name)
            review_reasons.extend(spectrum_data[name]["convergence_review_reasons"])
        except science.UnsupportedFormat as exc:
            review_reasons.append(str(exc))
    s1_data = {}
    for name, kernel in (("full_s1_optimization", "FULL"), ("stda_s1_optimization", "STDA")):
        try:
            s1_data[name] = science.validate_s1_trajectory(stage_texts[name]["native"], kernel=kernel, label=name)
            review_reasons.extend(s1_data[name]["convergence_review_reasons"])
            if s1_data[name]["same_evaluation_identity_review_required"]:
                review_reasons.append(f"{name} native S1-total/E0/omega differences exceed printed-token rounding and require an error-budget review")
        except science.UnsupportedFormat as exc:
            review_reasons.append(str(exc))
    native_state_diagnostics = {
        "spectra": {
                   name: {"kernel": value["kernel"], "state_count": value["state_count"],
                   "convergence_review_reasons": value["convergence_review_reasons"],
                   "states": [{"state": row["state"], "energy_eV": str(row["energy_eV"]),
                               "energy_token": row["energy_token"],
                               "oscillator_strength": str(row["oscillator_strength"]),
                               "oscillator_strength_token": row["oscillator_strength_token"],
                               "line": row["line"]} for row in value["state_rows"]]}
            for name, value in spectrum_data.items()},
        "s1_optimizations": {
            name: {"kernel": value["kernel"], "evaluation_count": value["evaluation_count"],
                   "same_evaluation_identity_review_required": value["same_evaluation_identity_review_required"],
                   "convergence_review_reasons": value["convergence_review_reasons"],
                   "evaluations": [{"line_start": ev["line_start"], "line_end": ev["line_end"],
                                    "total_Ha_token": ev["total_Ha_token"],
                                    "e0_Ha_token": ev["e0_Ha_token"], "e0_line": ev["e0_line"],
                                    "same_evaluation_energy_identity": ev["same_evaluation_energy_identity"],
                                    "states": [{"state": row["state"], "energy_token": row["energy_token"],
                                                "oscillator_strength_token": row["oscillator_strength_token"],
                                                "line": row["line"]} for row in ev["state_rows"]]}
                                   for ev in value["evaluations"]]}
            for name, value in s1_data.items()},
        "gs_endpoint": gs_auto,
    }

    table_bytes = _read_bounded(final / "table5.csv", MAX_REPORT_BYTES, status="FAIL", label="final/table5.csv")
    try:
        table_rows = list(csv.DictReader(io.StringIO(table_bytes.decode("utf-8"), newline=""), strict=True))
        header = next(csv.reader(io.StringIO(table_bytes.decode("utf-8"), newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error, StopIteration):
        raise VerifierError("FAIL", "case07 table5.csv is not valid UTF-8 CSV") from None
    if header != REPORT_HEADER or len(table_rows) != 2 or [row.get("kernel") for row in table_rows] != ["FULL", "STDA"]:
        raise VerifierError("FAIL", "case07 table5.csv does not match the frozen two-kernel schema")
    reported = {row["kernel"]: row for row in table_rows}
    paper_checks = {}
    for kernel, expected_values in PAPER_VALUES.items():
        row = reported[kernel]
        for field, expected_value in zip(REPORT_HEADER[6:10], expected_values):
            value = _decimal_from_report(row[field], f"{kernel}.{field}", science)
            expected = Decimal(expected_value)
            if abs(value - expected) > Decimal("0.005"):
                raise VerifierError("FAIL", f"case07 paper Table 5 value is mis-transcribed: {kernel}.{field}")
        paper_checks[kernel] = {field: row[field] for field in REPORT_HEADER[6:10]}
        if row["Ead_0-0_eV"].strip():
            _decimal_from_report(row["Ead_0-0_eV"], f"{kernel}.Ead_0-0_eV", science)
            review_reasons.append(f"{kernel} reports a 0-0 Ead and requires a same-model ZPE evidence review")
    derived = {}
    table_arithmetic_checks = {}
    if gs_auto and len(spectrum_data) == 2 and len(s1_data) == 2:
        gs_e0_token = gs_auto["endpoint_E0_Ha_token"]
        for kernel, spectrum_name, s1_name in (("FULL", "full_spectrum", "full_s1_optimization"),
                                                ("STDA", "stda_spectrum", "stda_s1_optimization")):
            spectrum = spectrum_data[spectrum_name]
            s1 = s1_data[s1_name]["endpoint"]
            formulas = science.energy_summary(gs_e0_token,
                                              spectrum["state_rows"][0]["energy_token"],
                                              s1["total_Ha_token"], s1["e0_Ha_token"],
                                              s1["state_rows"][0]["energy_token"])
            report_tokens = {field: reported[kernel][field] for field in
                             ("Evert_eV", "Ead_electronic_eV", "Efl_eV", "Stokes_eV")}
            native_envelopes = {
                "Evert_eV": str(science.half_ulp(spectrum["state_rows"][0]["energy_token"], "Evert native token")),
                "Efl_eV": str(science.half_ulp(s1["state_rows"][0]["energy_token"], "Efl native token")),
                "Ead_electronic_eV": str((science.half_ulp(s1["total_Ha_token"], "S1 total") +
                                           science.half_ulp(gs_e0_token, "GS E0")) * science.EV_PER_HA_CODATA_2006),
                "Stokes_eV": str(science.half_ulp(spectrum["state_rows"][0]["energy_token"], "Evert") +
                                 science.half_ulp(s1["state_rows"][0]["energy_token"], "Efl")),
            }
            reported_rounded = {}
            field_checks = {}
            for field, formula in (("Evert_eV", formulas["Evert_eV"]),
                                   ("Ead_electronic_eV", formulas["Ead_electronic_eV"]),
                                   ("Efl_eV", formulas["Efl_eV"]),
                                   ("Stokes_eV", formulas["Stokes_eV"])):
                token = report_tokens[field]
                value = _decimal_from_report(token, f"{kernel}.{field}", science)
                expected_value = Decimal(formula)
                if field == "Ead_electronic_eV" and not unit_profile_supported:
                    field_checks[field] = {"reported_token": token, "native_derived_diagnostic": str(expected_value),
                                           "conversion_profile": "unsupported; no automatic converted comparison",
                                           "passed": None}
                    continue
                native_envelope = Decimal(native_envelopes[field])
                report_envelope = science.half_ulp(token, f"{kernel}.{field}")
                # This is a precision-review trigger, not a scientific
                # acceptance tolerance. A very coarse printed table must not
                # obtain an arbitrarily wide arithmetic allowance silently.
                if report_envelope > Decimal("0.005"):
                    review_reasons.append(
                        f"{kernel}.{field} table precision exceeds the 0.005 eV review trigger; independent review must assess whether rounding can alter interpretation")
                if abs(value - expected_value) > native_envelope + report_envelope:
                    raise VerifierError("FAIL", f"{kernel} reported {field} disagrees with native-token arithmetic")
                field_checks[field] = {"reported_token": token, "native_derived": str(expected_value),
                                       "native_rounding_envelope": str(native_envelope),
                                       "table_rounding_envelope": str(report_envelope), "passed": True}
                reported_rounded[field] = str(value)
            if abs(Decimal(formulas["Evert_eV"]) - Decimal(formulas["Efl_eV"]) - Decimal(formulas["Stokes_eV"])) > (
                    Decimal(native_envelopes["Stokes_eV"]) + science.half_ulp(report_tokens["Evert_eV"], "Evert") +
                    science.half_ulp(report_tokens["Efl_eV"], "Efl") + science.half_ulp(report_tokens["Stokes_eV"], "Stokes")):
                raise VerifierError("FAIL", f"{kernel} Stokes identity fails its printed-token rounding envelope")
            derived[kernel] = formulas
            table_arithmetic_checks[kernel] = field_checks
    else:
        review_reasons.append("complete raw native energy/state parsing is outside the automatic profile")
    checks.append({"id": "native_500_8_state_and_electronic_table_arithmetic",
                   "status": "PASS" if table_arithmetic_checks else "REVIEW_REQUIRED",
                   "table_checks": table_arithmetic_checks, "paper_reference_transcription": paper_checks})

    # Trusted scheduler accounting is separate from candidate provenance.
    runner_path = os.environ.get("CASE07_RUN_MANIFEST")
    runner_sha = os.environ.get("CASE07_RUN_MANIFEST_SHA256")
    try:
        runner_manifest = review_protocol.load_runner_manifest(
            app_root=final.parent, path_text=runner_path,
            expected_sha=runner_sha, artifact_index=artifact_index,
            artifact_manifest_sha256=artifact_manifest_sha,
            criteria_version=provenance["criteria_version"],
            production_native_refs={name: {key: stage_refs[name]["native"][key]
                                           for key in ("path", "sha256")} for name in STAGE_IDS})
    except review_protocol.ReviewStaleError as exc:
        runner_manifest = None
        review_reasons.append(str(exc))
    if runner_manifest is None:
        review_reasons.append("trusted runner manifest is unavailable or stale; measured cost authenticity remains under review")

    build_sha = _native_build_digest(local_sources)
    core = {
        "schema": "bench12.case07.automatic-core/v1",
        "case_id": CASE_ID,
        "criteria_version": provenance["criteria_version"],
        "provenance_schema": PROVENANCE_SCHEMA,
        "verifier_build_sha256": build_sha,
        "artifact_manifest_sha256": artifact_manifest_sha,
        "checks": checks,
        "problems": problems,
        "review_reasons": review_reasons,
        "stage_diagnostics": stage_diagnostics,
        "native_state_diagnostics": native_state_diagnostics,
        "native_derived_values": derived,
        "runner_costs": None if runner_manifest is None else {
            "runner_manifest_sha256": runner_manifest["sha256"],
            "run_id": runner_manifest["run_id"],
            "costs_by_stage_cpu_seconds": runner_manifest["costs_by_stage_cpu_seconds"],
            "production_cost_by_stage_cpu_seconds": runner_manifest["production_cost_by_stage_cpu_seconds"],
            "total_allocated_cpu_seconds": runner_manifest["total_allocated_cpu_seconds"],
            "total_allocated_cpu_hours": runner_manifest["total_allocated_cpu_hours"],
            "attempts": runner_manifest["attempts"]},
    }
    core_sha = science.canonical_json_sha256(core)
    if problems:
        return {"status": "FAIL", "reward": 0, "science_validated": False,
                "automatic_core": core, "automatic_core_sha256": core_sha,
                "review": None, "problems": problems, "review_reasons": review_reasons,
                "stage_diagnostics": stage_diagnostics}
    try:
        review = review_protocol.evaluate_review(
            app_root=final.parent,
            review_path=os.environ.get("CASE07_REVIEW_FILE"),
            review_sha256=os.environ.get("CASE07_REVIEW_SHA256"),
            criteria_version=provenance["criteria_version"], verifier_sha256=build_sha,
            automatic_core_sha256=core_sha, artifact_manifest_sha256=artifact_manifest_sha,
            runner_manifest_sha256=None if runner_manifest is None else runner_manifest["sha256"],
            run_id=None if runner_manifest is None else runner_manifest["run_id"],
            artifact_index=artifact_index, runner_manifest=runner_manifest)
    except review_protocol.ReviewStaleError as exc:
        review = {"status": "REVIEW_REQUIRED", "reason": str(exc)}
    if review["status"] == "PASS":
        has_zero_zero_value = any(reported[kernel]["Ead_0-0_eV"].strip() for kernel in ("FULL", "STDA"))
        zero_zero_disposition = review["criteria"]["native_screening_consistency_and_paper_comparison"]["findings"]["zero_zero_disposition"]
        if has_zero_zero_value and zero_zero_disposition != "supported":
            raise review_protocol.ReviewEnvironmentError(
                "trusted review PASS contradicts a reported 0-0 energy without a supported same-model ZPE disposition")
        if not has_zero_zero_value and zero_zero_disposition == "supported":
            raise review_protocol.ReviewEnvironmentError(
                "trusted review PASS claims a supported 0-0 energy that is absent from the candidate table")
    status = review["status"]
    result = {"status": status, "science_validated": status == "PASS",
              "authenticity_unverified": status != "PASS", "gold_eligible": False,
              "automatic_core": core, "automatic_core_sha256": core_sha,
              "review": review, "problems": problems, "review_reasons": review_reasons,
              "stage_diagnostics": stage_diagnostics}
    if status == "PASS":
        result["reward"] = 1
    elif status == "FAIL":
        result["reward"] = 0
    return result


def _validate_l1(final: Path, report: dict[str, Any]) -> dict[str, Any] | None:
    missing = []
    for dirname in ("geometries", "spectra"):
        p = final / dirname
        if p.is_symlink() or not p.is_dir():
            missing.append(f"final/{dirname}/")
        else:
            # At least one regular, non-symlink file is required in each deliverable collection.
            if not any(f.is_file() and not f.is_symlink() for f in p.rglob("*")):
                missing.append(f"final/{dirname}/ (no regular deliverable files)")
    for name in ("table5.csv", "report.md", "provenance.json"):
        p = final / name
        if p.is_symlink() or not p.is_file():
            missing.append(f"final/{name}")
    if missing:
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("missing required L1 deliverables: " + ", ".join(missing))
        return None
    report_data = _read_bounded(final / "report.md", MAX_REPORT_BYTES, status="FAIL", label="final/report.md")
    table_data = _read_bounded(final / "table5.csv", MAX_REPORT_BYTES, status="FAIL", label="final/table5.csv")
    prov_data = _read_bounded(final / "provenance.json", MAX_JSON_BYTES, status="FAIL", label="final/provenance.json")
    if not report_data.strip() or not table_data.strip():
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("required report/table deliverable is empty")
        return None
    try:
        rows = list(csv.reader(io.StringIO(table_data.decode("utf-8")), strict=True))
    except (UnicodeDecodeError, csv.Error):
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("final/table5.csv is not readable UTF-8 CSV")
        return None
    if len(rows) < 2 or not rows[0] or any(not cell.strip() for cell in rows[0]):
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("final/table5.csv lacks a header or data row")
        return None
    header = [cell.strip() for cell in rows[0]]
    if len({cell.casefold() for cell in header}) != len(header):
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("final/table5.csv has duplicate column names")
        return None
    if any(len(row) != len(header) for row in rows[1:]):
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("final/table5.csv has inconsistent row widths")
        return None
    # If the candidate exposes a recognizable Evert/Efl/Stokes triplet, enforce
    # the printed-token arithmetic envelope. Unknown table layouts remain review.
    normalized = [re.sub(r"[^a-z0-9]+", "", cell.casefold()) for cell in header]
    units_by_column: dict[int, str | None] = {}

    def find_energy_column(bases: tuple[str, ...], *, optional_zero_zero: bool = False) -> int | None:
        matches: list[tuple[int, str | None]] = []
        for i, name in enumerate(normalized):
            if optional_zero_zero and re.search(r"(?:00|zerozero|zeropoint|zpe)", name):
                continue
            unit = None
            base = name
            for suffix, suffix_unit in (("hartree", "ha"), ("ev", "ev"), ("ha", "ha")):
                if name.endswith(suffix) and name[:-len(suffix)] in bases:
                    base, unit = name[:-len(suffix)], suffix_unit
                    break
            if (base in bases) and (name == base or unit is not None):
                matches.append((i, unit))
        if len(matches) != 1:
            return None
        units_by_column[matches[0][0]] = matches[0][1]
        return matches[0][0]

    evert_i = find_energy_column(("evert", "verticalexcitation"))
    efl_i = find_energy_column(("efl", "emissionenergy", "fluorescenceenergy"))
    stokes_i = find_energy_column(("stokes",))
    ead_i = find_energy_column(("ead", "eadelectronic", "adiabaticelectronic"), optional_zero_zero=True)
    required_numeric = {i for i in (evert_i, efl_i, stokes_i, ead_i) if i is not None}
    nonfinite_tokens = {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
    for row_no, row in enumerate(rows[1:], 2):
        if not any(value.strip() for value in row):
            report["status"] = "FAIL"
            report["reward"] = 0
            report["problems"].append(f"final/table5.csv has an empty data row {row_no}")
            return None
        for col_i, value in enumerate(row):
            token = value.strip()
            if not token or token.casefold() in nonfinite_tokens:
                if col_i in required_numeric:
                    report["status"] = "FAIL"
                    report["reward"] = 0
                    report["problems"].append(f"required electronic energy field is empty/non-finite at row {row_no}, column {header[col_i]}")
                    return None
                report["review_reasons"].append(f"optional or unclassified table field needs review: row {row_no}, column {header[col_i]}")
                continue
            if col_i in required_numeric:
                try:
                    value_decimal = Decimal(token)
                except InvalidOperation:
                    report["status"] = "FAIL"
                    report["reward"] = 0
                    report["problems"].append(f"recognized electronic energy field is not numeric at row {row_no}, column {header[col_i]}")
                    return None
                if not value_decimal.is_finite():
                    report["status"] = "FAIL"
                    report["reward"] = 0
                    report["problems"].append(f"recognized electronic energy field is non-finite at row {row_no}, column {header[col_i]}")
                    return None
    if evert_i is not None and efl_i is not None and stokes_i is not None:
        units = [units_by_column.get(i) for i in (evert_i, efl_i, stokes_i)]
        if len(set(units)) == 1 and units[0] is not None:
            for row_no, row in enumerate(rows[1:], 2):
                try:
                    ev, efl, st = (Decimal(row[i].strip()) for i in (evert_i, efl_i, stokes_i))
                except InvalidOperation:
                    report["status"] = "FAIL"
                    report["reward"] = 0
                    report["problems"].append(f"recognized Stokes fields are not numeric at row {row_no}")
                    return None
                if not (ev.is_finite() and efl.is_finite() and st.is_finite()):
                    report["status"] = "FAIL"
                    report["reward"] = 0
                    report["problems"].append(f"recognized Stokes fields are non-finite at row {row_no}")
                    return None
                delta = ev - efl
                uncertainty = sum((Decimal(1).scaleb(x.as_tuple().exponent) / 2 for x in (ev, efl, st)), Decimal(0))
                if abs(delta - st) > uncertainty:
                    report["status"] = "FAIL"
                    report["reward"] = 0
                    report["problems"].append(f"Stokes arithmetic exceeds printed-token rounding envelope at row {row_no}")
                    return None
            report["checks"].append("recognizable Stokes arithmetic is consistent within printed-token rounding")
        else:
            report["review_reasons"].append("Stokes columns were recognized but units are missing or inconsistent")
    else:
        report["review_reasons"].append("table5 layout is readable but scientific column mapping needs manual review")
    try:
        provenance = json.loads(
            prov_data,
            object_pairs_hook=_unique_object_pairs,
            parse_float=lambda token: _finite_json_float(token),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("final/provenance.json is invalid JSON")
        return None
    if not isinstance(provenance, dict) or not provenance:
        report["status"] = "FAIL"
        report["reward"] = 0
        report["problems"].append("final/provenance.json must be a nonempty object")
        return None
    report["checks"].append("required L1 deliverables exist and have basic readable structure")
    return provenance


def _finite_json_float(token: str) -> float:
    value = float(token)
    if not __import__("math").isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _stage_diagnostics(final: Path, provenance: dict[str, Any], report: dict[str, Any], modules: dict[str, Any]) -> None:
    stages = provenance.get("stages")
    if not isinstance(stages, dict) or not stages:
        report["review_reasons"].append("stage mapping is absent or does not use the unfinalized supported schema")
        return
    unknown = sorted(set(stages) - set(STAGES))
    if unknown:
        report["review_reasons"].append("stage mapping contains unsupported stage identifiers")
        return
    if set(stages) != set(STAGES):
        report["review_reasons"].append("one or more expected stage identifiers are absent; schema compatibility remains under review")
    for stage_name, entry in stages.items():
        if not isinstance(entry, dict):
            report["review_reasons"].append(f"unsupported stage record shape: {stage_name}")
            continue
        refs_required = ("input", "native", "trajectory") if stage_name.endswith("optimization") else ("input", "native")
        if any(key not in entry for key in refs_required):
            report["review_reasons"].append(f"incomplete references for stage {stage_name}")
            continue
        texts: dict[str, str | None] = {}
        metas: dict[str, dict[str, Any]] = {}
        for role in refs_required:
            text, meta = _read_candidate_ref(final, entry[role], f"{stage_name}.{role}")
            texts[role], metas[role] = text, meta
        if any(v is None for v in texts.values()):
            report["review_reasons"].append(f"non-UTF-8 stage artifact requires manual format review: {stage_name}")
            continue
        parser_kind, mode = STAGES[stage_name]
        try:
            if parser_kind == "geo":
                result = modules["inspect_geo_opt"].inspect_text(
                    texts["input"], texts["native"], texts["trajectory"], expected_atoms=192, mode=mode
                )
            else:
                result = modules["inspect_spectrum_energy"].inspect_text(
                    texts["input"], texts["native"], expected_atoms=192
                )
            expected_kernel = "STDA" if stage_name.startswith("stda_") else "FULL"
            if stage_name == "gs_optimization":
                stage_kernel_matches = None
            else:
                kernel = (result.get("input_contract", {}).get("kernel")
                          or result.get("input_contract", {}).get("input_s1_kernel"))
                stage_kernel_matches = str(kernel).upper() == expected_kernel
            strict = result.get("strict_syntax_complete") is True and stage_kernel_matches is not False
            report["stage_diagnostics"][stage_name] = {
                "parser": "trusted pinned syntax parser",
                "strict_syntax_complete": strict,
                "stage_kernel_matches_stage_id": stage_kernel_matches,
                "failed_checks": result.get("failed_checks", []),
                "checks": result.get("checks", {}),
                "artifacts": metas,
                "science_validated": False,
                "gold_eligible": False,
            }
            if any(meta.get("declared_sha256") is None for meta in metas.values()):
                report["review_reasons"].append(f"one or more stage artifacts lack a declared SHA-256: {stage_name}")
            if not strict:
                report["review_reasons"].append(f"author parser did not validate stage syntax: {stage_name}")
        except Exception as exc:
            report["stage_diagnostics"][stage_name] = {"parser_error": type(exc).__name__, "artifacts": metas,
                                                        "science_validated": False}
            report["review_reasons"].append(f"stage format or parser behavior needs manual review: {stage_name}")


def run(app: Path, package_root: Path, tool_dir: Path) -> dict[str, Any]:
    report = _base()
    science = None
    review_protocol = None
    try:
        if app.is_symlink() or not app.is_dir():
            raise VerifierError("ENV_INVALID", "APP must be an existing non-symlink directory")
        _check_public_inputs(package_root)
        refs_path = Path(__file__).resolve(strict=True).parent / "refs.json"
        if refs_path.is_symlink() or not refs_path.is_file():
            raise VerifierError("ENV_INVALID", "trusted refs.json is unavailable or symlinked")
        refs_raw = refs_path.read_bytes()
        if hashlib.sha256(refs_raw).hexdigest() != REFS_SHA256:
            raise VerifierError("ENV_INVALID", "trusted refs.json hash mismatch")
        refs = json.loads(refs_raw)
        if refs.get("author_helper_sha256") != HELPER_PINS or refs.get("grader_helper_sha256") != SUPPORT_HELPER_PINS:
            raise VerifierError("ENV_INVALID", "refs.json trusted helper pins disagree with the verifier")
        literature = refs.get("literature_table5", {}).get("values")
        if not isinstance(literature, dict) or set(literature) != {"FULL", "STDA"}:
            raise VerifierError("ENV_INVALID", "refs.json literature table inventory is malformed")
        if any(not isinstance(values, list) or len(values) != 4 or any(not isinstance(v, str) for v in values)
               for values in literature.values()):
            raise VerifierError("ENV_INVALID", "refs.json literature values are malformed")
        global PAPER_VALUES
        PAPER_VALUES = {kernel: tuple(values) for kernel, values in literature.items()}
        modules = _load_helpers(tool_dir)
        final = app / "final"
        if final.is_symlink() or not final.is_dir():
            report["status"] = "FAIL"
            report["reward"] = 0
            report["problems"].append("final/ is missing or is a symlink")
            return report
        provenance = _validate_l1(final, report)
        if provenance is None:
            return report
        if provenance.get("schema") == PROVENANCE_SCHEMA:
            artifact_index, artifact_manifest_sha = _snapshot_final(final)
            science, science_bytes = _load_local_helper("science_checks")
            review_protocol, review_bytes = _load_local_helper("review_protocol")
            wrapper_path = Path(__file__).resolve(strict=True)
            wrapper_bytes = wrapper_path.read_bytes()
            test_sh_path = wrapper_path.with_name("test.sh")
            test_sh_bytes = test_sh_path.read_bytes()
            local_sources = {"verify.py": wrapper_bytes, "science_checks.py": science_bytes,
                             "review_protocol.py": review_bytes, "test.sh": test_sh_bytes}
            v1_result = _validate_case07_v1(final, package_root, provenance, artifact_index,
                                            artifact_manifest_sha, modules, science, review_protocol,
                                            local_sources)
            report.update(v1_result)
            report["verifier"] = "case07-science-review-protocol/v1"
            report["scope"] = "Automatic necessary scientific checks plus an external, digest-bound independent review; not a Gold claim or runtime-bound reviewer identity."
            report["checks"] = v1_result.get("automatic_core", {}).get("checks", [])
            report["review_reasons"] = v1_result.get("review_reasons", [])
            report["problems"] = v1_result.get("problems", [])
            return report
        _stage_diagnostics(final, provenance, report, modules)
        report["review_reasons"].append("scientific thresholds, error budget, state continuity, conclusions, and runner authenticity require independent review")
        # Candidate claims are deliberately non-authoritative.
        report["candidate_science_claim_ignored"] = "present_but_not_authoritative" if "science_pass" in provenance else "not_present"
        report["status"] = "REVIEW_REQUIRED"
        report.pop("reward", None)
        return report
    except VerifierError as exc:
        report["status"] = exc.status
        report.pop("reward", None)
        if exc.status == "FAIL":
            report["reward"] = 0
        report["problems"].append(str(exc))
        return report
    except Exception as exc:
        # Scientific candidate defects and unsupported native profiles have
        # explicit outcomes; unexpected grader failures are environment errors.
        try:
            if review_protocol is None:
                review_protocol, _ = _load_local_helper("review_protocol")
            if science is None:
                science, _ = _load_local_helper("science_checks")
            if isinstance(exc, science.ScienceCheckError):
                report["status"] = "FAIL"
                report["reward"] = 0
            elif isinstance(exc, science.UnsupportedFormat):
                report["status"] = "REVIEW_REQUIRED"
                report.pop("reward", None)
            elif isinstance(exc, review_protocol.ReviewEnvironmentError):
                report["status"] = "ENV_INVALID"
                report.pop("reward", None)
            elif isinstance(exc, review_protocol.ReviewStaleError):
                report["status"] = "REVIEW_REQUIRED"
                report.pop("reward", None)
            else:
                report["status"] = "ENV_INVALID"
                report.pop("reward", None)
        except Exception:
            report["status"] = "ENV_INVALID"
            report.pop("reward", None)
        report["problems"].append(f"verifier exception: {type(exc).__name__}: {exc}")
        return report


def main() -> int:
    app = Path(os.environ.get("APP", "/app"))
    logs = Path(os.environ.get("LOGS", "/logs/verifier"))
    package_root = Path(os.environ.get("CASE07_PACKAGE_ROOT", str(Path(__file__).resolve().parents[1])))
    tool_text = os.environ.get("CASE07_AUTHOR_TOOLS")
    report_path = logs / "verification.json"
    try:
        if not logs.is_absolute() or logs.is_symlink():
            raise VerifierError("ENV_INVALID", "LOGS must be an absolute non-symlink directory")
        logs.mkdir(parents=True, exist_ok=True)
        if report_path.is_symlink():
            raise VerifierError("ENV_INVALID", "verification report path is symlinked")
        if not tool_text:
            report = _base("ENV_INVALID")
            report["problems"].append("CASE07_AUTHOR_TOOLS is not configured by the trusted runner")
            code = 2
        else:
            report = run(app, package_root, Path(tool_text))
            code = {"PASS": 0, "FAIL": 1, "REVIEW_REQUIRED": 0, "ENV_INVALID": 2}.get(report["status"], 2)
        encoded = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        fd, tmpname = tempfile.mkstemp(prefix=".verification.", dir=logs)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
        os.replace(tmpname, report_path)
        print(json.dumps({"status": report["status"], "report": str(report_path)}, ensure_ascii=False))
        return code
    except VerifierError as exc:
        # Best-effort structured infra report. Never try to write into APP.
        report = _base(exc.status)
        report["problems"].append(str(exc))
        try:
            logs.mkdir(parents=True, exist_ok=True)
            if not report_path.is_symlink():
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        except OSError:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
