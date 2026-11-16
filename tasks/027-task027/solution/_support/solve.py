#!/usr/bin/env python3
"""Run only the explicitly staged current Case07 reference bundle.

Normal execution checks only an explicitly staged current raw bundle and never
submits work. The historical scalar/archive diagnostic is opt-in and is not a
fresh task solution.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HARTREE_TO_KCAL = 627.5094740631
PINS = {
    "41467_2023_40675_MOESM1_ESM.docx": "52c8854e125cac6ea714c61a4e711fea66565cef62d0f176511e819e59fd568a",
    "Figure4/Toluene/Toluene-iBPR-DFT.log": "d2d7720643c371c07c3e34ea673ac6e70f7e4d610577241e7a7a87e368d168f1",
    "bpr_skeleton_geometries.csv": "504e3f981b84b5f46e9bbc41a15c4e57ce9bb0d1384baa75df5a8ec8ca0ca3c3",
    "ipso_energy_reference.csv": "a9224bde49cfc8fee17944238392af351fbc645dc98ed077b498b23dcb3d209b",
    "ipso_energy_reference_provenance.json": "8d7ae2cde6a0b1685159961fbc66ddb3ce00b663269377943e093ca7e4312ceb",
}
ARCHIVE_REL = Path("prepared_jobs/case07_followup_audit_3887398")
ARCHIVE_PINS = {
    "results/3887398/C1_ts_freq/job.out": "c2ceb4f865131287a9988566bcc67076133141bf81237d07abfd9ffd624281a8",
    "results/3887398/C1_ts_freq/job.hess": "6b7b6d30e8077fce71a1a937126948c6f2bf966c31e6c8157f37286eb2c28163",
    "results/3887398/C1_ts_freq/job.inp": "62094968eb0be92844a38e82edb3f56521bf9b119c8f88faccaaff3014e99f31",
    "results/3887398/C1_ts_freq/receipt.json": "83dd584180d00ec90e044027566a5db63c115864d8bf762b919d64fbeec5d3ca",
    "production_3892162/native/minus_frequency/job.out": "a03c6317c4dfde18d33d73a34ee094a0fe0bcea668c5eaeea6281aee9ecbcd2f",
    "production_3892162/native/minus_frequency/job.hess": "7496a64ad9374c3256ebb59dd80f2f52a8431449e931805e1e6f9b804c052f03",
    "production_3892162/native/minus_frequency/job.inp": "ff41c413a6a012e7c6e12075bf2011e5c015f2604e5e066b25eca70d571ea5bc",
    "production_3892162/native/minus_frequency/receipt.json": "69810402c9163abbde70c8e0228791ba67a614bd859161f5c72c7ca133407cde",
    "final_3892162_runtime_3893417/plus_frequency/job.out": "c5a648a4c2dacb68895ae6f7b3434d3132c465927b63e31d189ec1627e619483",
    "final_3892162_runtime_3893417/plus_frequency/job.hess": "05d35a370fdd9fa6fd6965fedec6519908ebc1e6ca3e68ef534697c33c7ad19a",
    "final_3892162_runtime_3893417/plus_frequency/job.inp": "ff41c413a6a012e7c6e12075bf2011e5c015f2604e5e066b25eca70d571ea5bc",
    "final_3892162_runtime_3893417/plus_frequency/receipt.json": "217a7d2e003f56356ea548b889edb36913de692a0a5b48c0bcd8f1aa98e80644",
    "final_3892162_runtime_3893417/science_report.json": "5f1a768d48e5494535850b42be04ad814511d4bee7629e9c5f989f187dbd15b4",
}


def sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe public input: {path.name}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def reject_symlink_path(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"symlink path is not allowed: {path}")


def reject_symlink_relative(root: Path, relative: str) -> None:
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink public input component is not allowed: {relative}")


def finite_last(pattern: str, text: str, label: str) -> float:
    values = re.findall(pattern, text, flags=re.IGNORECASE)
    if not values:
        raise ValueError(f"native Gaussian log has no {label}")
    value = float(values[-1])
    if not math.isfinite(value):
        raise ValueError(f"native Gaussian {label} is non-finite")
    return value


def parse_gaussian_minimum(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="strict")
    if "Normal termination of Gaussian" not in text:
        raise ValueError("deposited Gaussian log lacks normal termination")
    charge_mult = re.findall(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text)
    if not charge_mult or charge_mult[-1] != ("0", "2"):
        raise ValueError("deposited Gaussian log is not a neutral doublet")
    atom_counts = re.findall(r"NAtoms=\s*(\d+)", text)
    if not atom_counts or int(atom_counts[-1]) != 21:
        raise ValueError("deposited Gaussian log does not contain 21 atoms")
    # Only the final harmonic-analysis block is relevant to the final BPR
    # minimum; this log contains preceding optimization-cycle information.
    frequency_header = text.rfind("Harmonic frequencies")
    if frequency_header < 0:
        raise ValueError("deposited Gaussian log lacks a harmonic frequency block")
    freq_matches = list(re.finditer(r"Frequencies --([^\n]+)", text[frequency_header:]))
    frequencies = [float(token) for match in freq_matches
                   for token in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?", match.group(1))]
    if len(frequencies) != 57 or any(not math.isfinite(x) for x in frequencies):
        raise ValueError(f"expected 57 finite vibrational frequencies; found {len(frequencies)}")
    electronic = finite_last(r"SCF Done:\s+E\([^)]*\)\s*=\s*([-+0-9.Ee]+)", text, "SCF energy")
    zpe = finite_last(r"Zero-point correction=\s*([-+0-9.Ee]+)", text, "ZPE")
    return {
        "engine": "Gaussian 16 RevC.02 (deposited public output)",
        "charge": 0,
        "multiplicity": 2,
        "atom_count": 21,
        "electronic_energy_hartree": electronic,
        "zpe_hartree": zpe,
        "frequency_count": len(frequencies),
        "imaginary_frequency_count": sum(x < 0 for x in frequencies),
        "minimum_frequency_cm-1": min(frequencies),
        "normal_termination": True,
        "source_sha256": sha256(path),
    }


def _import_native_parser(repository_root: Path):
    runtime_dir = repository_root / "runtimes" / "hpc" / "case07"
    parser_path = runtime_dir / "native_parser.py"
    expected = "48a0bbbab4f1ccc8ad3fd265d0b513d32d87dcefaf7029fa917f05c285718940"
    if sha256(parser_path) != expected:
        raise ValueError("frozen Case07 native parser source hash mismatch")
    if str(runtime_dir) not in sys.path:
        sys.path.insert(0, str(runtime_dir))
    sys.dont_write_bytecode = True
    import native_parser
    return native_parser, expected


def audit_archived_c1(repository_root: Path) -> dict:
    """Parse a pinned historical C1 TS and signed-mode endpoint frequency set."""
    archive = repository_root / ARCHIVE_REL
    if not archive.is_dir():
        return {"status": "NOT_AVAILABLE_IN_RUNTIME_MOUNT",
                "scope": "historical author archive is not part of public runtime assets"}
    paths = {}
    for rel, expected in ARCHIVE_PINS.items():
        path = archive / rel
        if sha256(path) != expected:
            raise ValueError(f"historical C1 archive pin mismatch: {rel}")
        paths[rel] = path
    parser, parser_sha = _import_native_parser(repository_root)
    stages = [
        ("C1_TS", "3887398", "results/3887398/C1_ts_freq", "6b7b6d30e8077fce71a1a937126948c6f2bf966c31e6c8157f37286eb2c28163", 1),
        ("BPR_SIDE_ENDPOINT", "3892162", "production_3892162/native/minus_frequency", "7496a64ad9374c3256ebb59dd80f2f52a8431449e931805e1e6f9b804c052f03", 0),
        ("C1_PRODUCT_ENDPOINT", "3893417", "final_3892162_runtime_3893417/plus_frequency", "05d35a370fdd9fa6fd6965fedec6519908ebc1e6ca3e68ef534697c33c7ad19a", 0),
    ]
    results = {}
    for name, job_id, relroot, expected_hess, expected_imaginary in stages:
        rel = f"{relroot}/job.out"
        out_path = paths[rel]
        hess_path = paths[f"{relroot}/job.hess"]
        inp_path = paths[f"{relroot}/job.inp"]
        receipt_path = paths[f"{relroot}/receipt.json"]
        output_text = out_path.read_text(encoding="utf-8", errors="strict")
        if "ORCA TERMINATED NORMALLY" not in output_text:
            raise ValueError(f"historical {name} output lacks ORCA normal-termination marker")
        if not re.search(r"SCF CONVERGED AFTER\s+\d+\s+CYCLES", output_text):
            raise ValueError(f"historical {name} output lacks a converged SCF marker")
        if "UKS r2SCAN-3c" not in output_text or not re.search(r"Total Charge\s+Charge\s+\.{3,}\s+0", output_text):
            raise ValueError(f"historical {name} method/charge differs from the frozen reference")
        if not re.search(r"Multiplicity\s+Mult\s+\.{3,}\s+2", output_text):
            raise ValueError(f"historical {name} is not a doublet calculation")
        energy = finite_last(r"FINAL SINGLE POINT ENERGY\s+([-+0-9.Ee]+)", output_text, "ORCA energy")
        zpe = finite_last(r"Zero point energy\s+\.{3,}\s+([-+0-9.Ee]+)\s+Eh", output_text, "ORCA ZPE")
        hess = parser.parse_hess(hess_path)
        imaginary = hess["physical_imaginary"]
        if len(imaginary) != expected_imaginary:
            raise ValueError(f"historical {name} has {len(imaginary)} physical imaginary modes")
        freq_by_index = hess["frequencies"]
        frequencies = [freq_by_index[index] for index in range(6, 63)]
        if len(frequencies) != 57 or any(not math.isfinite(value) for value in frequencies):
            raise ValueError(f"historical {name} does not have 57 finite physical modes")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (receipt.get("status") != "normal" or receipt.get("returncode") != 0
                or receipt.get("output_sha256") != sha256(out_path)
                or receipt.get("input_sha256") != sha256(inp_path)
                or abs(float(receipt.get("energy_au", math.nan)) - energy) > 1e-7
                or abs(float(receipt.get("zpe_au", math.nan)) - zpe) > 1e-8):
            raise ValueError(f"historical {name} native output/receipt mismatch")
        if sha256(hess_path) != expected_hess:
            raise ValueError(f"historical {name} Hessian/source-report digest mismatch")
        results[name] = {
            "historical_job_id": job_id,
            "archive_relative_stage": relroot,
            "output_sha256": sha256(out_path), "input_sha256": sha256(inp_path),
            "hessian_sha256": sha256(hess_path), "receipt_sha256": sha256(receipt_path),
            "electronic_energy_hartree": energy, "zpe_hartree": zpe,
            "physical_mode_count": len(frequencies), "physical_imaginary_count": len(imaginary),
            "physical_imaginary_frequencies_cm-1": [freq_by_index[index] for index in imaginary],
            "receipt_status": receipt["status"], "receipt_returncode": receipt["returncode"],
        }
    report_path = paths["final_3892162_runtime_3893417/science_report.json"]
    author_report = json.loads(report_path.read_text(encoding="utf-8"))
    if (author_report.get("scope_status") != "C1_connection_completed_prior_strict_budgets_failed"
            or author_report.get("original_strict_8h_budget_pass") is not False
            or author_report.get("canonical_screening_scope_revalidated") is not False):
        raise ValueError("historical author report scope/status does not match the pinned expected-fail reference")
    if (author_report["ts_source"]["frequency_summary"]["imaginary_count"] != 1
            or author_report["minus_endpoint"]["spectrum"]["imaginary_count"] != 0
            or author_report["plus_endpoint"]["spectrum"]["imaginary_count"] != 0):
        raise ValueError("historical science summary disagrees with native frequency classifications")
    expected_reports = {
        "C1_TS": author_report["ts_source"],
        "BPR_SIDE_ENDPOINT": author_report["minus_endpoint"],
        "C1_PRODUCT_ENDPOINT": author_report["plus_endpoint"],
    }
    for name, facts in results.items():
        source = expected_reports[name]
        expected_e = source.get("ts_frequency_energy_au", source.get("energy_au"))
        expected_zpe = source.get("ts_frequency_zpe_au", source.get("zpe_au"))
        if (abs(facts["electronic_energy_hartree"] - expected_e) > 1e-8
                or abs(facts["zpe_hartree"] - expected_zpe) > 1e-8):
            raise ValueError(f"historical {name} native output differs from the pinned science report")
    return {
        "status": "PARSED_PINNED_HISTORICAL_AUTHOR_EVIDENCE",
        "archive_mode": "reused historical run; not a fresh-agent-positive",
        "native_parser_sha256": parser_sha,
        "stages": results,
        "author_report_sha256": sha256(report_path),
        "author_claim_scope": author_report["scope_status"],
        "old_strict_8h_budget_pass": False,
        "canonical_screening_scope_revalidated": False,
        "C2_status": "UNRESOLVED",
        "connection_basis": "prior signed imaginary-mode endpoint evidence reported by the pinned author summary; this reparse verifies frequency/output/receipt consistency, not a new connection",
    }


def composite_barrier(row: dict[str, str], bpr: dict[str, str]) -> tuple[float, float, float]:
    """Recompute author F12-electronic + DFT-ZPE composite and check 0.1 rounding."""
    value = ((float(row["e_f12_au"]) - float(bpr["e_f12_au"]))
             + (float(row["zpe_au"]) - float(bpr["zpe_au"]))) * HARTREE_TO_KCAL
    published = float(row["published_channel_barrier_kcal_per_mol"])
    difference = value - published
    # The public value is reported to one decimal place; half a unit in that
    # last place is the comparison bound, not a scientific uncertainty band.
    if abs(difference) > 0.05 + 1e-12:
        raise ValueError("recomputed public composite barrier differs beyond published one-decimal rounding")
    return value, published, difference


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path,
                        help="optional author workspace root for rechecking the pinned historical C1 archive")
    parser.add_argument("--archive-diagnostic", action="store_true",
                        help="explicitly run the bounded historical/public-reference diagnostic; never a fresh task solution")
    parser.add_argument("--fresh-bundle", type=Path,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.archive_diagnostic:
        bundle = args.fresh_bundle or (Path(__file__).resolve().parent / "current-reference-run")
        if not bundle.exists():
            args.output.mkdir(parents=True, exist_ok=True)
            target = args.output / "case07-solution-status.json"
            target.write_text(json.dumps({"schema": "case07-solution-status/v1", "status": "NOT_RUN",
                "reason": "No current raw bundle is staged at /solution/current-reference-run; no scheduler, remote service, historical archive or derived result was used."},
                indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"NOT_RUN: no current fresh-reference bundle; wrote {target}", file=sys.stderr)
            return 2
        try:
            if str(Path(__file__).resolve().parent) not in sys.path:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
            import current_reference
            result = current_reference.finalize_preflight(bundle, args.output, args.assets)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            args.output.mkdir(parents=True, exist_ok=True)
            result = {"schema": "case07-solution-status/v1", "status": "INVALID_BUNDLE",
                      "reason": str(exc), "oracle_pass": False}
            (args.output / "case07-solution-status.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if result.get("final_artifacts_assembled") is True:
            print("CANDIDATE_ARTIFACTS_ASSEMBLED: no Oracle reward or science-completion claim")
            return 0
        print(f"{result.get('status', 'INVALID_BUNDLE')}: no Oracle pass", file=sys.stderr)
        return 2 if result.get("status") == "NOT_RUN" else 1
    reject_symlink_path(args.assets)
    reject_symlink_path(args.output)
    assets = args.assets.resolve(strict=True)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    hashes = {}
    for rel, expected in PINS.items():
        reject_symlink_relative(assets, rel)
        path = assets / rel
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"public input hash mismatch: {rel}")
        hashes[rel] = actual

    gaussian = parse_gaussian_minimum(assets / "Figure4/Toluene/Toluene-iBPR-DFT.log")
    with (assets / "ipso_energy_reference.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = {row["species"]: row for row in csv.DictReader(stream)}
    if set(rows) != {"BPR", "C1", "C2"}:
        raise ValueError("public scalar reference must contain exactly BPR, C1 and C2")
    bpr = rows["BPR"]
    ref_e, ref_zpe = float(bpr["e_dft_au"]), float(bpr["zpe_au"])
    delta_e_kcal = abs(gaussian["electronic_energy_hartree"] - ref_e) * HARTREE_TO_KCAL
    delta_zpe_kcal = abs(gaussian["zpe_hartree"] - ref_zpe) * HARTREE_TO_KCAL
    if gaussian["frequency_count"] != 57 or gaussian["imaginary_frequency_count"] != 0:
        raise ValueError("deposited BPR stationary-point classification is inconsistent")
    if delta_e_kcal > 0.01 or delta_zpe_kcal > 0.01:
        raise ValueError("deposited BPR native output does not match its public scalar row")

    barriers = {}
    for channel in ("C1", "C2"):
        row = rows[channel]
        composite, published, difference = composite_barrier(row, bpr)
        barriers[channel] = {
            "recomputed_composite_barrier_kcal_per_mol": composite,
            "published_barrier_kcal_per_mol": published,
            "difference_kcal_per_mol": difference,
            "comparison_basis": "published one-decimal-place rounding only",
            "interpretation": "recalculation of deposited author scalars; not a new barrier",
        }

    report = {
        "schema": "case07-reference-validation/v1",
        "status": "REUSED_ARCHIVE_REFERENCE",
        "grade": "NOT_FRESH_AGENT_GRADE_POSITIVE",
        "execution_performed": False,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "validator_sha256": sha256(Path(__file__).resolve()),
        "scope": "public deposited BPR native minimum plus author scalar barrier arithmetic",
        "source_hashes": hashes,
        "native_bpr_check": {
            **gaussian,
            "reference_electronic_energy_hartree": ref_e,
            "reference_zpe_hartree": ref_zpe,
            "absolute_energy_difference_kcal_per_mol": delta_e_kcal,
            "absolute_zpe_difference_kcal_per_mol": delta_zpe_kcal,
            "assessment": "MATCHES_PUBLIC_REFERENCE",
        },
        "historical_native_c1_audit": audit_archived_c1(
            args.archive_root.resolve(strict=True) if args.archive_root else Path(__file__).resolve().parents[3]),
        "author_scalar_barriers": barriers,
        "not_established": [
            "no new calculation was run",
            "no C1 or C2 multi-point screening was performed",
            "no transition state was newly optimized or frequency-verified",
            "no reaction connection was newly established",
            "no fresh resource or execution provenance was measured",
            "historical C1 evidence is reused and does not establish original eight-hour budget compliance",
            "deposited saddle geometries and protected grading material were not read",
        ],
    }
    target = output / "case07-reference-validation.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(f"{report['status']}: wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
