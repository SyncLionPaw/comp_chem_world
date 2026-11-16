#!/usr/bin/env python3
# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""case-07 open-research structural and registered-numeric verification (single-file entry point)."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, re, stat, sys, zipfile, xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REFS = json.loads((Path(__file__).resolve().parent / "refs.json").read_text(encoding="utf-8"))
_SEL = _REFS["numeric_selectors"]
_LIM = _SEL["limits"]
FIGURE3A_SELECTORS = {k: tuple(v) for k, v in _SEL["figure3a"].items()}
MAX_XLSX = int(_LIM["xlsx_byte_limit"])
MAX_ZIP_ENTRIES = int(_LIM["zip_entries"])
MAX_UNCOMPRESSED = int(_LIM["uncompressed_bytes"])
SHEET1_ROWS = range(int(_LIM["sheet1_first_row"]), int(_LIM["sheet1_last_row"]) + 1)
MIN_POINTS = int(_LIM["min_points"])
MIN_DISTINCT_X = int(_LIM["min_distinct_x"])
OUTCAR_BYTE_LIMIT = int(_LIM["outcar_byte_limit"])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def read_sheet1(path: Path) -> dict[str, str]:
    if path.stat().st_size > MAX_XLSX:
        raise ValueError("xlsx byte limit exceeded")
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
            raise ValueError("xlsx expansion limit exceeded")
        if any(i.file_size > MAX_UNCOMPRESSED for i in infos):
            raise ValueError("xlsx member limit exceeded")
        strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            doc = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                       for si in doc.findall("m:si", NS)]
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        cells = {}
        for cell in sheet.findall(".//m:sheetData/m:row/m:c", NS):
            value = cell.find("m:v", NS)
            text = "" if value is None else value.text or ""
            if cell.attrib.get("t") == "s" and text:
                text = strings[int(text)]
            cells[cell.attrib["r"]] = text
        return cells


def finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric value must be a JSON number, not bool/string")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("numeric value must be finite")
    return result


def ols(points: list[tuple[float, float]]) -> dict[str, float | int]:
    if len(points) < 3:
        raise ValueError("OLS requires at least three observed points")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    xx = sum((x - xm) ** 2 for x in xs)
    if xx == 0:
        raise ValueError("OLS pressure values are not distinct")
    slope = sum((x - xm) * (y - ym) for x, y in points) / xx
    intercept = ym - slope * xm
    stderr = math.sqrt(sum((y - intercept - slope * x) ** 2 for x, y in points)
                       / (len(points) - 2) / xx)
    return {"n": len(points), "slope": slope, "intercept": intercept,
            "ols_slope_standard_error": stderr}


def registered_figure3a(path: Path, series: str, low: float, high: float) -> dict:
    selectors = FIGURE3A_SELECTORS
    if series not in selectors:
        raise LookupError("series not registered; NOT_CHECKED")
    if not math.isfinite(low) or not math.isfinite(high) or low > high:
        raise ValueError("pressure interval must be finite and ordered")
    cells = read_sheet1(path)
    xcol, ycol = selectors[series]
    points = []
    for row in SHEET1_ROWS:
        try:
            x, y = float(cells[f"{xcol}{row}"]), float(cells[f"{ycol}{row}"])
        except (KeyError, ValueError):
            continue
        if low <= x <= high:
            points.append((x, y))
    if len(points) < MIN_POINTS or len({point[0] for point in points}) < MIN_DISTINCT_X:
        raise LookupError("registered OLS standard-error check is inapplicable to this interval; NOT_CHECKED")
    result = ols(points)
    result["pressure_min_GPa"] = low
    result["pressure_max_GPa"] = high
    return result


def dft_signed_modes(path: Path) -> list[float]:
    if path.stat().st_size > OUTCAR_BYTE_LIMIT:
        raise ValueError("OUTCAR byte limit exceeded")
    data = path.read_text(encoding="utf-8", errors="replace")
    values = []
    pattern = re.compile(r"\b([fFiI](?:/i)?)\s*=\s*[+-]?[0-9.]+\s+THz\s+[+-]?[0-9.]+\s+2PiTHz\s+([+-]?[0-9.]+)\s+cm-1")
    for line in data.splitlines():
        match = pattern.search(line)
        if match:
            value = abs(float(match.group(2)))
            values.append(-value if match.group(1).lower() == "f/i" else value)
    return values


from datetime import date

MAX_FILES = 300
MAX_FILE_BYTES = 20_000_000
MAX_TREE_BYTES = 50_000_000
MAX_JSON_BYTES = 2_000_000
REGISTRY = Path(__file__).parent / "private/source-registry.json"


class ContractError(ValueError):
    pass


class InfrastructureError(RuntimeError):
    pass


def validate_private_assets():
    try:
        if REGISTRY.is_symlink() or not REGISTRY.is_file():
            raise InfrastructureError("private source registry is unavailable")
        registry = strict_json(REGISTRY)
        if registry.get("schema") != "case07-source-registry/1":
            raise InfrastructureError("private source registry schema is invalid")
        files = [("Figure3a.xlsx", registry["figure3a"]),
                 ("Figure4b.xlsx", registry["figure4b"])]
        files.extend((f"OUTCAR-{item['pressure_GPa']}GPa", item)
                     for item in registry["dft_bulk_outcars"])
        seen = set()
        for name, expected in files:
            path = REGISTRY.parent / "reference" / name
            if (name in seen or path.is_symlink() or not path.is_file()
                    or path.stat().st_size != expected.get("bytes")
                    or sha256(path) != expected.get("sha256")):
                raise InfrastructureError(f"pinned private verifier reference is damaged: {name}")
            seen.add(name)
    except InfrastructureError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        raise InfrastructureError(f"private verifier registry/reference validation failed: {exc}") from exc


def _bad_constant(token):
    raise ContractError(f"non-finite JSON constant: {token}")


def _finite_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise ContractError(f"overflow/non-finite JSON number: {token}")
    return value


def _bounded_int(token):
    if len(token.lstrip("-")) > 128:
        raise ContractError("JSON integer digit limit exceeded")
    return int(token)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _check_json_numbers(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("non-finite JSON number")
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            if not math.isfinite(float(value)):
                raise ContractError("overflow JSON integer")
        except OverflowError as exc:
            raise ContractError("overflow JSON integer") from exc
    if isinstance(value, dict):
        for child in value.values(): _check_json_numbers(child)
    elif isinstance(value, list):
        for child in value: _check_json_numbers(child)


def strict_json(path: Path):
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ContractError(f"JSON exceeds size limit: {path.name}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_bad_constant, parse_float=_finite_float, parse_int=_bounded_int)
        _check_json_numbers(parsed)
        return parsed
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractError(f"invalid strict JSON {path.name}: {exc}") from exc


def safe_tree(root: Path):
    if root.is_symlink() or not root.is_dir():
        raise ContractError("final must be a real directory")
    absolute = root.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ContractError(f"symlink in final path: {current}")
    count = total = dirs_seen = 0
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        if depth > 32:
            raise ContractError("final tree depth limit exceeded")
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    st = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(st.st_mode):
                        raise ContractError(f"symlink forbidden: {path.relative_to(root)}")
                    if stat.S_ISDIR(st.st_mode):
                        dirs_seen += 1
                        if dirs_seen > MAX_FILES:
                            raise ContractError("final tree directory-count limit exceeded")
                        pending.append((path, depth + 1))
                    elif stat.S_ISREG(st.st_mode):
                        count += 1
                        total += st.st_size
                        if st.st_nlink != 1:
                            raise ContractError(f"hardlink forbidden: {path.relative_to(root)}")
                        if st.st_size > MAX_FILE_BYTES:
                            raise ContractError(f"file too large: {path.relative_to(root)}")
                        if count > MAX_FILES or total > MAX_TREE_BYTES:
                            raise ContractError("final tree exceeds file-count or total-size limit")
                    else:
                        raise ContractError(f"special file forbidden: {path.relative_to(root)}")
        except OSError as exc:
            raise ContractError(f"cannot safely scan final tree: {exc}") from exc
    return count, total


def safe_rel(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractError("manifest path must be a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.as_posix() != value or path.is_absolute() or any(p in ("", ".", "..") for p in path.parts):
        raise ContractError(f"unsafe manifest path: {value!r}")
    return path.as_posix()


def run(final: Path) -> dict:
    validate_private_assets()
    file_count, total_bytes = safe_tree(final)
    report = final / "report.md"
    prov_path = final / "provenance.json"
    if not report.is_file() or report.stat().st_size == 0:
        raise ContractError("final/report.md must be present and nonempty")
    prov = strict_json(prov_path)
    if not isinstance(prov, dict) or prov.get("schema") != "case07-provenance/2":
        raise ContractError("provenance schema must be case07-provenance/2")
    for key in ("sources", "claims", "reproduction_manifest"):
        if key not in prov:
            raise ContractError(f"provenance missing {key}")
    prov.setdefault("numeric_evidence", [])
    if not isinstance(prov["sources"], list) or not prov["sources"]:
        raise ContractError("sources must be a nonempty list")
    for source in prov["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not source["title"].strip():
            raise ContractError("each source requires a nonempty title")
        if not any(isinstance(source.get(key), str) and source[key].strip() for key in ("url", "doi")):
            raise ContractError("each source requires a DOI or stable URL")
        if not isinstance(source.get("version_or_publication"), str) or not source["version_or_publication"].strip():
            raise ContractError("each source requires version_or_publication")
        if not isinstance(source.get("access_date"), str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", source["access_date"]):
            raise ContractError("each source requires access_date as YYYY-MM-DD")
        try:
            date.fromisoformat(source["access_date"])
        except ValueError as exc:
            raise ContractError("source access_date is not a calendar date") from exc
        if not isinstance(source.get("files"), list):
            raise ContractError("each source requires a files array")
        for item in source["files"]:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ContractError("source file entries require a path")
            file_rel = safe_rel(item["path"])
            if "bytes" in item and (type(item["bytes"]) is not int or item["bytes"] < 0):
                raise ContractError("source file bytes must be a nonnegative integer")
            if "sha256" in item and (not isinstance(item["sha256"], str) or len(item["sha256"]) != 64
                                      or any(ch not in "0123456789abcdef" for ch in item["sha256"])):
                raise ContractError("source file sha256 must be lowercase hexadecimal")
    if not isinstance(prov["claims"], list) or not prov["claims"] or not isinstance(prov["numeric_evidence"], list):
        raise ContractError("claims must be nonempty and numeric_evidence must be an array")
    for claim in prov["claims"]:
        if (not isinstance(claim, dict) or not isinstance(claim.get("id"), str) or not claim["id"].strip()
                or not isinstance(claim.get("text"), str) or not claim["text"].strip()
                or not isinstance(claim.get("evidence"), list) or not claim["evidence"]):
            raise ContractError("each claim requires id, text, and evidence paths")
        for ref in claim["evidence"]:
            rel = safe_rel(ref)
            if not (final / rel).is_file():
                raise ContractError(f"claim evidence path is missing: {rel}")
    if not isinstance(prov["reproduction_manifest"], list) or not prov["reproduction_manifest"]:
        raise ContractError("reproduction_manifest must be a nonempty list")
    actual = {}
    for item in prov["reproduction_manifest"]:
        if not isinstance(item, dict):
            raise ContractError("manifest entry must be an object")
        rel = safe_rel(item.get("path"))
        # The manifest accepts either a final-root path (reproduction/...) or
        # a path relative to reproduction/. Normalize both forms before
        # duplicate detection and byte verification; never infer from existence.
        canonical = rel if rel.startswith("reproduction/") else f"reproduction/{rel}"
        if canonical in actual:
            raise ContractError(f"duplicate manifest path: {canonical}")
        path = final / canonical
        # Lexical safe path and no-symlink tree validation precede use.
        if not path.is_file():
            raise ContractError(f"manifest file missing: {rel}")
        digest, size = sha256(path), path.stat().st_size
        if item.get("sha256") != digest or type(item.get("bytes")) is not int or item["bytes"] != size:
            raise ContractError(f"manifest bytes/hash mismatch: {rel}")
        actual[canonical] = (digest, size)
    for source in prov["sources"]:
        for item in source["files"]:
            rel = safe_rel(item["path"])
            if rel.startswith("reproduction/"):
                bound = actual.get(rel)
                if bound is None or ("bytes" in item and item["bytes"] != bound[1]) or ("sha256" in item and item["sha256"] != bound[0]):
                    raise ContractError(f"source file provenance differs from output bytes: {rel}")
    if not any(rel.startswith("reproduction/") for rel in actual):
        raise ContractError("manifest must bind reproduction material")
    tree_reproduction = {str(path.relative_to(final)) for path in (final / "reproduction").rglob("*")
                         if path.is_file()}
    if tree_reproduction != {rel for rel in actual if rel.startswith("reproduction/")}:
        raise ContractError("manifest must bind every reproduction file and no missing path")

    registry = strict_json(REGISTRY)
    numeric = []
    for item in prov["numeric_evidence"]:
        if (not isinstance(item, dict) or not isinstance(item.get("source_id"), str)
                or not item["source_id"].strip()):
            raise ContractError("numeric evidence entries require a nonempty source_id")
        source_id = item["source_id"]
        selector = item.get("selector")
        units = item.get("units")
        selector_ok = isinstance(selector, dict) or (isinstance(selector, str) and selector.strip())
        units_ok = isinstance(units, dict) or (isinstance(units, str) and units.strip())
        if not isinstance(item.get("method"), str) or not item["method"].strip() or not selector_ok or not units_ok:
            raise ContractError("numeric evidence requires a nonempty method and selector/units string or object")
        if source_id in {"official_supplement.figure3a.ols", "official_supplement.figure3a.ols_0_8"}:
            if item.get("method") != "OLS":
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                                "reason": "method is outside the registered calculation"})
                continue
            if item.get("series") not in registry["figure3a"]["ols"]:
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                                "reason": "series is outside the registered selector table"})
                continue
            slope_unit = units if isinstance(units, str) else units.get("slope")
            if slope_unit != "cm-1/GPa":
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                                "reason": "reported slope unit is outside registered unit"})
                continue
            rel = safe_rel(item.get("evidence_path"))
            path = final / rel
            expected = registry["figure3a"]
            if (rel not in actual or actual[rel][0] != expected["sha256"] or actual[rel][1] != expected["bytes"]
                    or sha256(Path(__file__).parent / "private/reference/Figure3a.xlsx") != expected["sha256"]):
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                                "reason": "candidate bytes do not match the registered workbook"})
                continue
            series = item.get("series")
            try:
                low = finite_number(item.get("pressure_min_GPa"))
                high = finite_number(item.get("pressure_max_GPa"))
                result = registered_figure3a(path, series, low, high)
            except LookupError as exc:
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED", "reason": str(exc),
                                "pressure_min_GPa": item.get("pressure_min_GPa"),
                                "pressure_max_GPa": item.get("pressure_max_GPa")})
                continue
            for key in ("n", "slope", "intercept", "ols_slope_standard_error"):
                if key in item:
                    reported = item[key]
                    if key == "n":
                        if type(reported) is not int:
                            raise ContractError("numeric evidence n must be an integer, not bool")
                        observed = result[key]
                        ok = reported == observed
                    else:
                        reported = finite_number(reported)
                        observed = result[key]
                        ok = math.isclose(reported, observed, rel_tol=2e-6, abs_tol=2e-7)
                    numeric.append({"source_id": source_id, "series": series,
                                    "pressure_min_GPa": low, "pressure_max_GPa": high,
                                    "field": key, "status": "CONSISTENT" if ok else "CONTRADICTED",
                                    "observed": observed, "reported": reported})
        elif source_id == "official_supplement.figure4b.shared_thickness":
            rel = safe_rel(item.get("evidence_path"))
            expected = registry["figure4b"]
            ref = Path(__file__).parent / "private/reference/Figure4b.xlsx"
            if (rel not in actual or actual[rel] != (expected["sha256"], expected["bytes"])
                    or sha256(ref) != expected["sha256"]):
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                                "reason": "candidate bytes do not match the registered workbook"})
            else:
                numeric.append({"source_id": source_id, "status": "SOURCE_MATCHED_REVIEW_REQUIRED",
                                "reason": "registered source matched; derived relation remains for scientific review"})
        elif source_id == "official_supplement.bulk_dft.signed_modes":
            rel = safe_rel(item.get("evidence_path"))
            dft = next((d for d in registry["dft_bulk_outcars"] if item.get("pressure_GPa") == d["pressure_GPa"]), None)
            ref = Path(__file__).parent / "private/reference" / f"OUTCAR-{item.get('pressure_GPa')}GPa"
            if dft and rel in actual and actual[rel] == (dft["sha256"], dft["bytes"]) and sha256(ref) == dft["sha256"]:
                numeric.append({"source_id": source_id, "status": "SOURCE_MATCHED_REVIEW_REQUIRED",
                                "reason": "registered raw OUTCAR matched; scientific interpretation remains for review"})
            else:
                numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                                "reason": "candidate bytes do not match registered raw OUTCAR"})
        else:
            numeric.append({"source_id": source_id, "status": "NOT_CHECKED",
                            "reason": "source/method is outside bounded private registry"})
    contradicted = any(entry.get("status") == "CONTRADICTED" for entry in numeric)
    return {"schema": "case07-structural-evidence/1", "status": "REVIEW_REQUIRED",
            "reward": None, "file_count": file_count, "tree_bytes": total_bytes,
            "reproduction_files_bound": len(actual), "numeric_checks": numeric,
            "automatic_contradiction": contradicted,
            "science_decision": "CONTRADICTED_REGISTERED_CLAIM" if contradicted else "NOT_MADE_BY_AUTOMATION"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default="/app/final")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--evidence-out", default="/logs/verifier/research-evidence.json")
    args = parser.parse_args()
    try:
        evidence = run(Path(args.output_dir))
        Path(args.evidence_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence_out).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2) if args.json else "REVIEW_REQUIRED: structural checks complete; no science decision or reward")
        return 0
    except (ContractError, OSError, ValueError, KeyError, TypeError, OverflowError, zipfile.BadZipFile) as exc:
        evidence = {
            "schema": "case07-structural-evidence/1",
            "status": "CASE07_INVALID",
            "reward": None,
            "science_decision": "NOT_MADE_BY_AUTOMATION",
            "error": str(exc),
        }
        try:
            Path(args.evidence_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.evidence_out).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
        print(f"CASE07_INVALID: {exc}", file=sys.stderr)
        return 2
    except InfrastructureError as exc:
        evidence = {
            "schema": "case07-structural-evidence/1",
            "status": "ENV_INVALID",
            "reward": None,
            "science_decision": "NOT_MADE_BY_AUTOMATION",
            "error": str(exc),
        }
        try:
            Path(args.evidence_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.evidence_out).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
        print(f"CASE07_INFRA_ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
