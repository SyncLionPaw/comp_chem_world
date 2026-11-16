"""Grader-only authority for the native S050 SI table and derived targets.

Authority bytes are protected; the candidate must independently acquire and
include its own native material under /app/final. Source matching verifies
published SI correspondence, not the underlying experiments' truth.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SOURCE_ADAPTER = "published-s050-cp1252/v1"
RAW_ZIP_SHA256 = "ce339248e5d4db6c3939624d08e5a7fdf8a83bcff8f3ddb0543721638641aa8e"
METADATA_SHA256 = "51f8896566477ade439a1da613e76fc76c1049ab604ea47c77154cb387c67eec"
RAW_ZIP_BYTES = 72_358_128
ZIP_MEMBER = "SC-012-D0SC04896H-s050.csv"
CSV_COLUMNS = (
    "Entry", "Exp_Rate_Constant k1 (M-1s-1)", "Substrate SMILES",
    "Nucleophile SMILES", "Product SMILES", "Reaction SMILES", "Temp (K)",
    "Activation Free Energy (kcalmol-1)", "Reference", "Year", "Title",
    "Authors", "DOI", "Book_Page", "Table", "Nucleophile", "Leaving Group",
    "Solvent", "logk", "Entry IDs of Duplicates", "Model_Flag",
)
MAX_ZIP_BYTES = 100_000_000
MAX_MEMBER_BYTES = 16_000_000
MAX_COMPRESSION_RATIO = 200
R_GAS_J_MOL_K = 8.31446261815324
PLANCK_J_S = 6.62607015e-34
BOLTZMANN_J_K = 1.380649e-23
JOULES_PER_KCAL = 4184.0
AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "protected" / "source-authority-v1"
NATIVE_SI_SHA256 = "ec3744548892430c8c32c6c520eb06e6820638bdf4c6ea33c686e6f8cf3b6a43"
NATIVE_SI_BYTES = 1_656_384
PUBLIC_CSV_SHA256 = "590153f74fd27a1414cf6d1cdae3758e68cc9e137da81bd58fa84cc5c9750107"
PUBLIC_CSV_BYTES = 281_470
NATIVE_STANDARD_STATE = "1 mol L^-1 (1 M), explicitly stated in SI Equation S11"
NATIVE_EYRING_EQUATION = "DeltaG‡ = -R*T*ln(k*h/(kB*T)); k_eff=k2*C_standard"
TABULATED_PROFILE = "native-tabulated-apparent-activation-free-energy/v1"
RECOMPUTED_PROFILE = "registered-eyring-recomputed-apparent-activation-free-energy/v1"


class SourceAdapterError(ValueError):
    """The protected public source is missing, malformed, or outside scope."""


@dataclass(frozen=True)
class TargetSpec:
    schema: str = "case06-target-spec/v1"
    rate_order: int = 2
    rate_unit: str = "M^-1 s^-1"
    concentration_value: float = 1.0
    concentration_unit: str = "mol L^-1"
    transmission_coefficient: float = 1.0
    standard_state: str = "1 mol L^-1"
    target_name: str = "apparent activation Gibbs free energy from reported rate and temperature"
    target_unit: str = "kcal/mol"


def _s050_rate_target(rate_molar: float, target_spec: TargetSpec) -> tuple[float, float]:
    """Convert the CSV's declared M^-1 s^-1 value into the typed target units."""
    if (type(target_spec.rate_order) is not int or target_spec.rate_order != 2
            or isinstance(target_spec.transmission_coefficient, bool)
            or target_spec.transmission_coefficient != 1.0
            or target_spec.standard_state != "1 mol L^-1" or target_spec.target_unit != "kcal/mol"):
        raise SourceAdapterError("unsupported S050 target dimensions or standard state")
    if target_spec.rate_unit == "M^-1 s^-1" and target_spec.concentration_unit == "mol L^-1":
        if isinstance(target_spec.concentration_value, bool) or target_spec.concentration_value != 1.0:
            raise SourceAdapterError("molar S050 target requires typed C0=1 mol L^-1")
        rate_in_target_units = rate_molar
    elif target_spec.rate_unit == "m^3 mol^-1 s^-1" and target_spec.concentration_unit == "mol m^-3":
        if isinstance(target_spec.concentration_value, bool) or target_spec.concentration_value != 1000.0:
            raise SourceAdapterError("SI S050 target requires typed C0=1000 mol m^-3")
        rate_in_target_units = rate_molar / 1000.0
    else:
        raise SourceAdapterError("S050 source rate and target dimensions are not a registered unit pair")
    effective = rate_to_first_order(
        rate_in_target_units, rate_order=target_spec.rate_order,
        rate_unit=target_spec.rate_unit, concentration_value=target_spec.concentration_value,
        concentration_unit=target_spec.concentration_unit)
    return rate_in_target_units, effective


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_doi(value: str) -> str:
    doi = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.rstrip("/")


def rate_to_first_order(rate: float, *, rate_order: int, rate_unit: str,
                        concentration_value: float, concentration_unit: str) -> float:
    """Convert a declared second-order rate and standard concentration to s^-1."""
    if type(rate_order) is not int or rate_order != 2:
        raise SourceAdapterError("registered S050 adapter requires a second-order rate")
    if isinstance(rate, bool) or type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
        raise SourceAdapterError("rate constant must be positive and finite")
    if (isinstance(concentration_value, bool) or type(concentration_value) not in (int, float)
            or not math.isfinite(concentration_value) or concentration_value <= 0):
        raise SourceAdapterError("standard concentration must be positive and finite")
    if rate_unit == "M^-1 s^-1" and concentration_unit == "mol L^-1":
        return rate * concentration_value
    if rate_unit == "m^3 mol^-1 s^-1" and concentration_unit == "mol m^-3":
        return rate * concentration_value
    raise SourceAdapterError("rate/concentration units are not a registered dimensionally consistent pair")


def eyring_barrier(rate_s_inv: float, temperature_k: float, *,
                   transmission_coefficient: float = 1.0) -> float:
    if isinstance(rate_s_inv, bool) or type(rate_s_inv) not in (int, float) or rate_s_inv <= 0:
        raise SourceAdapterError("effective first-order rate must be positive and finite")
    if not math.isfinite(temperature_k) or temperature_k <= 0:
        raise SourceAdapterError("temperature must be positive and finite")
    if not math.isfinite(transmission_coefficient) or transmission_coefficient <= 0:
        raise SourceAdapterError("transmission coefficient must be positive and finite")
    argument = rate_s_inv * PLANCK_J_S / (transmission_coefficient * BOLTZMANN_J_K * temperature_k)
    if not math.isfinite(argument) or argument <= 0:
        raise SourceAdapterError("Eyring logarithm argument must be positive and finite")
    return -R_GAS_J_MOL_K * temperature_k * math.log(argument) / JOULES_PER_KCAL


def _union_find(size: int):
    parent = list(range(size))
    rank = [0] * size

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    return find, union


def curate_s050_csv(raw: bytes, *, target_spec: TargetSpec = TargetSpec(),
                    require_canonical_shape: bool = True) -> dict[str, Any]:
    if len(raw) > MAX_MEMBER_BYTES or not raw:
        raise SourceAdapterError("S050 CSV is empty or exceeds the member size limit")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("cp1252"), newline=""))
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise SourceAdapterError("S050 column schema does not match the registered adapter")
        source_rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise SourceAdapterError("S050 CSV cannot be decoded or parsed") from exc
    if require_canonical_shape and len(source_rows) != 518:
        raise SourceAdapterError("registered S050 source must contain 518 data rows")

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for pos, row in enumerate(source_rows, start=1):
        errors = []
        try:
            entry = str(int(row["Entry"].strip()))
        except (AttributeError, ValueError):
            entry = ""
            errors.append("entry_invalid")
        try:
            rate = float(row["Exp_Rate_Constant k1 (M-1s-1)"].strip())
        except (AttributeError, ValueError):
            rate = math.nan
        try:
            temperature = float(row["Temp (K)"].strip())
        except (AttributeError, ValueError):
            temperature = math.nan
        if not math.isfinite(rate) or rate <= 0:
            errors.append("rate_not_positive_finite")
        if not math.isfinite(temperature) or temperature <= 0:
            errors.append("temperature_not_positive_finite")
        doi_raw = row["DOI"].strip()
        if not normalize_doi(doi_raw):
            errors.append("doi_missing")
        for col in ("Substrate SMILES", "Nucleophile SMILES", "Reaction SMILES", "Solvent"):
            if not row[col].strip():
                errors.append(f"{col.lower().replace(' ', '_')}_missing")
        sample_id = f"entry-{entry}-row-{pos:04d}" if entry else f"source-row-{pos:04d}"
        if errors:
            excluded.append({"source_row": pos, "sample_id": sample_id, "reasons": errors})
            continue
        rate_in_target_units, effective_rate = _s050_rate_target(rate, target_spec)
        measured = eyring_barrier(effective_rate, temperature,
                                  transmission_coefficient=target_spec.transmission_coefficient)
        try:
            reported_token = row["Activation Free Energy (kcalmol-1)"].strip()
            reported = float(reported_token)
            if not math.isfinite(reported):
                reported = None
        except (ValueError, AttributeError):
            reported_token = ""
            reported = None
        included.append({
            "id": sample_id, "source_row": pos, "entry": entry,
            "reaction_smiles_raw": row["Reaction SMILES"],
            "doi_raw": doi_raw, "doi_normalized": normalize_doi(doi_raw),
            "substrate_smiles": row["Substrate SMILES"],
            "nucleophile_smiles": row["Nucleophile SMILES"],
            "product_smiles": row["Product SMILES"],
            "leaving_group": row["Leaving Group"],
            "year_metadata": row["Year"],
            "reference_metadata": row["Reference"],
            "solvent": row["Solvent"], "temperature_k": temperature,
            "rate_value": rate, "rate_unit": "M^-1 s^-1",
            "rate_value_in_target_units": rate_in_target_units,
            "target_rate_unit": target_spec.rate_unit,
            "standard_concentration_value": target_spec.concentration_value,
            "standard_concentration_unit": target_spec.concentration_unit,
            "effective_rate_s_inv": effective_rate,
            "measurement_kcal_mol": measured,
            "native_tabulated_kcal_mol": reported,
            "reported_barrier_audit_only_kcal_mol": reported,
            "reported_barrier_token": reported_token,
            "reported_barrier_decimal_places": (len(reported_token.partition(".")[2]) if "." in reported_token else 0),
            "duplicate_entry_ids_raw": row["Entry IDs of Duplicates"],
        })

    if require_canonical_shape and (len(included) != 495 or len(excluded) != 23):
        raise SourceAdapterError("S050 curation does not reproduce the registered 495/23 row boundary")
    ids = [row["entry"] for row in included]
    if len(ids) != len(set(ids)):
        raise SourceAdapterError("included S050 entry identifiers are not unique")

    find, union = _union_find(len(included))
    by_entry: dict[str, int] = {row["entry"]: i for i, row in enumerate(included)}
    seen: dict[tuple[str, str], int] = {}
    for i, row in enumerate(included):
        for key in (("doi", row["doi_normalized"]), ("reaction", row["reaction_smiles_raw"].strip())):
            if key in seen:
                union(i, seen[key])
            else:
                seen[key] = i
        for duplicate in re.findall(r"\d+", row["duplicate_entry_ids_raw"]):
            if duplicate in by_entry:
                union(i, by_entry[duplicate])
    components: dict[int, list[int]] = {}
    for i in range(len(included)):
        components.setdefault(find(i), []).append(i)
    ordered = sorted(components.values(), key=lambda ix: min(included[i]["source_row"] for i in ix))
    for number, indices in enumerate(ordered, start=1):
        gid = f"group-{number:03d}"
        for i in indices:
            included[i]["group_id"] = gid
    if require_canonical_shape and len(ordered) != 27:
        raise SourceAdapterError("S050 connected reaction/DOI grouping does not reproduce 27 groups")
    return {"adapter": SOURCE_ADAPTER, "target_spec": target_spec.__dict__,
            "included": included, "excluded": excluded,
            "row_count": len(source_rows), "included_count": len(included),
            "excluded_count": len(excluded), "group_count": len(ordered),
            "source_csv_sha256": sha256_bytes(raw)}


def load_registered_s050(archive_path: Path, metadata_path: Path) -> dict[str, Any]:
    for path, expected, byte_count, label in (
        (archive_path, RAW_ZIP_SHA256, RAW_ZIP_BYTES, "raw archive"),
        (metadata_path, METADATA_SHA256, 2_422, "article metadata"),
    ):
        if path.is_symlink() or not path.is_file():
            raise SourceAdapterError(f"registered {label} is missing or unsafe")
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size != byte_count or sha256_bytes(path.read_bytes()) != expected:
            raise SourceAdapterError(f"registered {label} custody hash/size mismatch")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("doi", "").casefold() != "10.1039/d0sc04896h" or metadata.get("is_retracted") is True:
        raise SourceAdapterError("article metadata is not the registered non-retracted DOI")
    raw = archive_path.read_bytes()
    if len(raw) > MAX_ZIP_BYTES:
        raise SourceAdapterError("raw archive exceeds the registered byte cap")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise SourceAdapterError("archive has duplicate member names")
            for info in infos:
                member = PurePosixPath(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if (member.is_absolute() or ".." in member.parts or "\\" in info.filename
                        or info.file_size > MAX_MEMBER_BYTES or info.file_size < 0
                        or (info.file_size and (info.compress_size == 0
                            or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO))
                        or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG))):
                    raise SourceAdapterError("archive member violates path, size, ratio, or file-type limits")
            matches = [i for i in infos if i.filename == ZIP_MEMBER]
            if len(matches) != 1:
                raise SourceAdapterError("archive must contain exactly one registered S050 member")
            csv_raw = archive.read(matches[0])
            if len(csv_raw) != matches[0].file_size:
                raise SourceAdapterError("S050 member size differs from its directory record")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SourceAdapterError("registered source archive is unreadable") from exc
    parsed = curate_s050_csv(csv_raw)
    parsed["raw_archive_sha256"] = RAW_ZIP_SHA256
    parsed["metadata_sha256"] = METADATA_SHA256
    return parsed


class ProtectedSourceError(RuntimeError):
    """The grader's pinned source authority is damaged or unavailable."""


def load_protected_s050() -> dict[str, Any]:
    """Verify private SI/archive bytes, then derive target rows from native CSV."""
    si_path = AUTHORITY_DIR / "SC-012-D0SC04896H-s001.pdf"
    zip_path = AUTHORITY_DIR / "SC-012-D0SC04896H-s002.zip"
    try:
        si_raw, archive_raw = si_path.read_bytes(), zip_path.read_bytes()
    except OSError as exc:
        raise ProtectedSourceError("registered native source authority is missing") from exc
    if (len(si_raw) != NATIVE_SI_BYTES or sha256_bytes(si_raw) != NATIVE_SI_SHA256
            or len(archive_raw) != RAW_ZIP_BYTES or sha256_bytes(archive_raw) != RAW_ZIP_SHA256):
        raise ProtectedSourceError("registered native source authority bytes/hash do not match")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_raw), "r") as archive:
            matches = [item for item in archive.infolist() if item.filename == ZIP_MEMBER]
            if len(matches) != 1:
                raise ProtectedSourceError("registered SI archive member is absent or duplicated")
            csv_raw = archive.read(matches[0])
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ProtectedSourceError("registered SI archive cannot be read") from exc
    try:
        parsed = curate_s050_csv(csv_raw, require_canonical_shape=True)
    except SourceAdapterError as exc:
        raise ProtectedSourceError("registered native SI member fails its source adapter") from exc
    return {**parsed, "native_si_sha256": NATIVE_SI_SHA256,
            "raw_archive_sha256": RAW_ZIP_SHA256,
            "source_csv_sha256": PUBLIC_CSV_SHA256,
            "standard_state": NATIVE_STANDARD_STATE,
            "equation": NATIVE_EYRING_EQUATION}


def match_candidate_source(final: Path, source_spec: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
    """Require candidate-acquired original S050 CSV bytes to match private SI."""
    if normalize_doi(source_spec.get("doi", "")) != "10.1039/d0sc04896h":
        raise SourceAdapterError("source is outside the registered S050 authority")
    rel = source_spec.get("path")
    if not isinstance(rel, str):
        raise SourceAdapterError("registered source must include its acquired native CSV")
    relative = PurePosixPath(rel)
    if relative.is_absolute() or not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise SourceAdapterError("candidate native source path is unsafe")
    if relative.parts[0] != "native_evidence" or len(relative.parts) < 2:
        raise SourceAdapterError("registered source path must remain under native_evidence")
    path = final.joinpath(*relative.parts)
    current = final
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SourceAdapterError("candidate native source path contains a symlink")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SourceAdapterError("candidate native source bytes are missing") from exc
    if (len(raw) != PUBLIC_CSV_BYTES or sha256_bytes(raw) != PUBLIC_CSV_SHA256
            or source_spec.get("sha256") != PUBLIC_CSV_SHA256):
        raise SourceAdapterError("candidate S050 source bytes do not match the registered native SI member")
    candidate = curate_s050_csv(raw, require_canonical_shape=True)
    if candidate["included_count"] != authority["included_count"]:
        raise SourceAdapterError("candidate source differs from protected source row authority")
    return candidate


def deterministic_group_split(rows: list[dict[str, Any]], *, seed: int,
                              train_fraction: float = 0.60,
                              calibration_fraction: float = 0.20) -> dict[str, Any]:
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise SourceAdapterError("split seed must be an explicit bounded integer")
    groups = sorted({row["group_id"] for row in rows})
    if len(groups) < 10 or not (0 < train_fraction < 1 and 0 < calibration_fraction < 1
                                and train_fraction + calibration_fraction < 1):
        raise SourceAdapterError("registered group split cannot form three independent partitions")
    ranked = sorted(groups, key=lambda group: hashlib.sha256(f"{seed}:{group}".encode()).hexdigest())
    n_train = math.floor(len(ranked) * train_fraction)
    n_cal = math.floor(len(ranked) * calibration_fraction)
    partitions = {"train": ranked[:n_train], "calibration": ranked[n_train:n_train+n_cal],
                  "test": ranked[n_train+n_cal:]}
    groups_for = {name: set(values) for name, values in partitions.items()}
    if any(groups_for[a] & groups_for[b] for a in groups_for for b in groups_for if a < b):
        raise SourceAdapterError("connected groups overlap across partitions")
    rows_by_partition = {name: [row["id"] for row in rows if row["group_id"] in group_ids]
                         for name, group_ids in groups_for.items()}
    return {"schema": "case06-group-split/v1", "seed": seed, "allocation": "60/20/20 group count",
            "groups": partitions, "rows": rows_by_partition,
            "target_values_used_for_split": False,
            "labels_public_and_exposed": True}
