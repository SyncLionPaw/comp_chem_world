#!/usr/bin/env python3
"""Build an evaluator-side, source-pinned Case08 reference package.

The only newly executed chemistry here is an analytic/RK4 preformed-iBPR/NO
screen. MESMER grain-size runs are copied with their original ARM64 receipts
and remain historical/local comparison evidence.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
FREEZE = HERE / "reference-manifest.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def put(src: Path, root: Path, rel: str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    return target


def conditional_r1b_share(test_file: Path, at_s: float = 1.0) -> float:
    """Read the R1a/R1b populations at a printed MESMER time point."""
    in_profile = False
    for line in test_file.read_text(errors="replace").splitlines():
        if line.startswith("Print time dependent species and product profiles"):
            in_profile = True
            continue
        if not in_profile:
            continue
        fields = line.split()
        if len(fields) < 6:
            continue
        try:
            t, r1a, r1b = float(fields[0]), float(fields[4]), float(fields[5])
        except ValueError:
            continue
        if abs(t - at_s) < 1e-10 and r1a + r1b > 0:
            return r1b / (r1a + r1b)
    raise ValueError(f"no usable MESMER population point at {at_s:g} s in {test_file}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: solve.sh OUTPUT_DIR")
    app = Path(sys.argv[1]).expanduser().resolve()
    frozen = json.loads(FREEZE.read_text())
    if frozen.get("schema") != "case08-reference-solution-manifest/v1":
        raise SystemExit("unsupported or missing frozen solution manifest")
    listed = {}
    for item in frozen.get("files", []):
        rel = Path(item["path"])
        src = HERE / rel
        if rel.is_absolute() or ".." in rel.parts or src.is_symlink() or not src.is_file():
            raise SystemExit(f"unsafe or missing frozen solution asset: {rel}")
        if src.stat().st_size != item["bytes"] or sha(src) != item["sha256"]:
            raise SystemExit(f"frozen solution asset hash mismatch: {rel}")
        listed[rel.as_posix()] = item["sha256"]
    actual = {p.relative_to(HERE).as_posix() for p in HERE.rglob("*")
              if p.is_file() and p != FREEZE and not p.is_symlink()}
    if actual != set(listed):
        raise SystemExit("solution source set differs from frozen reference manifest")
    final = app / "final"
    if final.exists() and any(final.iterdir()):
        raise SystemExit(f"refusing to overwrite nonempty output directory: {final}")
    app.mkdir(parents=True, exist_ok=True)
    final.mkdir(parents=True, exist_ok=True)
    native = final / "native_evidence"
    native.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()

    # Preserve the minimum source bytes needed to recheck the rates and the
    # correction-aware channel interpretation, with acquisition provenance.
    source_manifest = json.loads((HERE / "sources/source-manifest.json").read_text())
    acquisition = json.loads((HERE / "sources/acquisition-manifest.json").read_text())
    acquired_at = {x["file"]: x.get("response_received_at_utc", x.get("retrieved_at_utc_from_file_mtime", ""))
                   for x in acquisition["sources"]}
    acquired = {}
    for name in ("article.xml", "correction.pdf", "41467_2023_40675_MOESM1_ESM.docx",
                 "Toluene-ipso-HR-300-mesmer_out.xml", "acquisition-manifest.json", "source-manifest.json"):
        src = HERE / "sources" / name
        dst = put(src, native, f"sources/{name}")
        acquired[name] = {"path": dst.relative_to(final).as_posix(), "sha256": sha(dst),
                          "accessed_at": acquired_at.get(name, "2026-10-07T15:38:00.856983+00:00"),
                          "locator": "public article/SI and source archive; see sources/acquisition-manifest.json"}

    # Run the source-checked analytical model in this invocation, rather than
    # copying its earlier output from /tmp.
    rate_input = put(HERE / "data/rate_evidence.csv", native, "data/rate_evidence.csv")
    model_input = put(HERE / "model/kinetic_screen.py", native, "model/kinetic_screen.py")
    reference_check = put(HERE / "verify_reference.py", native, "model/verify_reference.py")
    frozen_input = put(FREEZE, native, "inputs/reference-manifest.json")
    for name in ("downstream_network_evidence.csv",):
        put(HERE / "data" / name, native, f"inputs/{name}")
    output_dir = native / "kinetic_screen"
    env = dict(os.environ, CASE08_OUTPUT_DIR=str(output_dir))
    proc = subprocess.run([sys.executable, str(model_input)], env=env, capture_output=True,
                          text=True, timeout=30)
    if proc.returncode:
        raise SystemExit(f"kinetic screen failed (rc={proc.returncode}): {proc.stderr[-2000:]}")
    result = json.loads((output_dir / "validation.json").read_text())
    if not result["checks"]["accepted_grid_pass"]:
        raise SystemExit("analytic/RK4 verification failed")
    finished = datetime.now(timezone.utc).isoformat()
    run_receipt = {
        "schema": "case08-local-reference-execution/v1",
        "command": [sys.executable, "model/kinetic_screen.py"],
        "started_at_utc": started, "finished_at_utc": finished,
        "status": "completed_local_analysis_only", "returncode": proc.returncode,
        "python": sys.version, "platform": sys.platform,
        "input_sha256": {"rate_evidence.csv": sha(rate_input), "kinetic_screen.py": sha(model_input)},
        "output_sha256": {p.name: sha(p) for p in sorted(output_dir.iterdir()) if p.is_file()},
        "scheduler_job_id": None, "allocated_cpu_hours": 0,
        "receipt_note": "This is a local analytical calculation; it is not an HPC receipt or independent execution authentication."
    }
    receipt_path = native / "kinetic_screen/local-run-receipt.json"
    receipt_path.write_text(json.dumps(run_receipt, indent=2) + "\n")

    # Include two actual, bounded ARM64 MESMER grain-size controls. These are
    # existing executions, not newly run chemistry and not the cluster smoke.
    historic = []
    for name in ("g50-qd", "g200-qd"):
        source_dir = HERE / "reference_runs" / ("control-g50qd" if name == "g50-qd" else "control-g200qd")
        dest_dir = native / "historical_local_mesmer" / name
        dest_dir.mkdir(parents=True)
        copied = {}
        for filename in ("Toluene-mech-S2-R1.xml", "Toluene-mech-S2-R1.test",
                         "mesmer_out.xml", "run-receipt.json"):
            source_file = source_dir / filename
            if source_file.exists():
                target = dest_dir / filename
                shutil.copyfile(source_file, target)
                copied[filename] = target
        required = {"Toluene-mech-S2-R1.xml", "Toluene-mech-S2-R1.test", "mesmer_out.xml", "run-receipt.json"}
        if set(copied) != required:
            raise SystemExit(f"historical reference files incomplete for {name}")
        historic.append((name, copied))

    # Compact, generated comparison table from pinned old receipts and the
    # current analytic model; no claim is made that this is an aerosol yield.
    at15 = {}
    with (output_dir / "early_competition.csv").open() as stream:
        for row in csv.DictReader(stream):
            if float(row["time_s"]) == 1.5:
                at15[float(row["no_ppbv"])] = row
    summary = {
        "schema": "case08-reference-solution-summary/v1",
        "scope": "preformed toluene i-BPR ring-opening channels with a lumped SI-based NO sink; no downstream O2/HO2 kinetics or aerosol yield",
        "source_rates": {"C1_s-1": 0.164121, "C2_s-1": 0.585048,
                         "NO_cm3_molecule-1_s-1": 9.15e-12,
                         "conditions": "300 K, 1 atm; NO ideal-gas conversion; NO rate temperature dependence unspecified"},
        "new_local_calculation_at_1.5s": {str(n): {k: float(v) for k, v in at15[n].items()
             if k in ("P-C1", "P-C2", "NO_lumped_sink", "mass_closure", "C1_fraction_of_opened", "C2_fraction_of_opened")}
             for n in (0.0, 1.0, 10.0, 200.0)},
        "validation": result["checks"],
        "historical_mesmer_controls": [],
        "limitations": ["NO is modeled as a lumped loss, with no product branching.",
                        "The calculation starts from preformed i-BPR; it does not model i-BPR formation.",
                        "Post-open O2/HO2 kinetics and time-dependent precursor flux are unsupported by acquired species-specific rates.",
                        "No aerosol mass yield is calculated.",
                        "Historical MESMER controls were executed locally on ARM64 and are not current HPC evidence."]
    }
    for name, files in historic:
        rr = json.loads(files["run-receipt.json"].read_text())
        summary["historical_mesmer_controls"].append({"name": name, "architecture": rr["architecture"],
             "wall_s": rr["wall_s"], "peak_process_tree_rss_bytes": rr["peak_process_tree_rss_bytes"],
             "population_sum_max_abs_error": rr["population_sum_max_abs_error"],
             "conditional_R1b_share_at_1s": conditional_r1b_share(files["Toluene-mech-S2-R1.test"]),
             "status": "historical_local_arm64_execution"})
    summary_path = native / "reference-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    checked = subprocess.run([sys.executable, str(reference_check), str(final)],
                             capture_output=True, text=True, timeout=10)
    if checked.returncode:
        raise SystemExit(f"reference validation failed (rc={checked.returncode}): {checked.stderr or checked.stdout}")

    evidence = []
    by_path = {}
    def ev(eid: str, role: str, path: Path, source=None):
        rel = path.relative_to(final).as_posix()
        item = {"id": eid, "role": role, "path": rel, "sha256": "sha256:" + sha(path)}
        if source:
            item["source"] = {"locator": source["locator"], "accessed_at": source["accessed_at"]}
        evidence.append(item); by_path[rel] = eid
        return eid

    # Acquired-source bytes.
    source_ids = {}
    for name, rec in acquired.items():
        source_ids[name] = ev("src_" + name.replace(".", "_").replace("-", "_"), "acquired_source",
                              final / rec["path"], rec)
    rate_id = ev("input_rate_evidence", "native_input", rate_input)
    model_id = ev("input_kinetic_screen", "native_input", model_input)
    downstream_id = ev("input_downstream_route_evidence", "native_input",
                        native / "inputs/downstream_network_evidence.csv")
    frozen_id = ev("input_frozen_solution_manifest", "native_input", frozen_input)
    native_article = ev("input_article_xml", "native_input", final / acquired["article.xml"]["path"])
    native_si = ev("input_si_docx", "native_input", final / acquired["41467_2023_40675_MOESM1_ESM.docx"]["path"])
    native_mesmer_source = ev("input_archived_mesmer_rates", "native_input",
                              final / acquired["Toluene-ipso-HR-300-mesmer_out.xml"]["path"])
    native_source_manifest = ev("input_source_manifest", "native_input",
                                final / acquired["source-manifest.json"]["path"])
    output_ids = [ev("output_early_competition", "native_output", output_dir / "early_competition.csv"),
                  ev("output_stress_sensitivity", "native_output", output_dir / "stress_sensitivity.csv"),
                  ev("output_validation", "native_output", output_dir / "validation.json"),
                  ev("output_summary", "native_output", summary_path)]
    receipt_id = ev("receipt_local_execution", "execution_receipt", receipt_path)

    executions = [{"id": "run_analytic_no_competition", "kind": "new_computation", "status": "completed",
        "started_at": started, "finished_at": finished, "tool": "Python analytic solution + independent RK4", "version": sys.version.split()[0],
        "input_evidence_ids": [rate_id, model_id, native_article, native_si, native_mesmer_source, native_source_manifest, frozen_id,
                               ev("input_reference_checker", "native_input", reference_check)],
        "output_evidence_ids": output_ids, "receipt_evidence_ids": [receipt_id],
        "resources": {"allocated_cpu_hours": 0},
        "decisions": ["The NO sink is lumped and is not resolved to products.", "No O2/HO2 post-open kinetics or aerosol yield is asserted."]}]

    # Historical executions have their actual receipts and remain analysis-only.
    for idx, (name, files) in enumerate(historic):
        input_ev = ev(f"{name}_input", "native_input", files["Toluene-mech-S2-R1.xml"])
        test_ev = ev(f"{name}_test", "native_input", files["Toluene-mech-S2-R1.test"])
        out_ev = ev(f"{name}_output", "native_output", files["mesmer_out.xml"])
        rr_ev = ev(f"{name}_receipt", "execution_receipt", files["run-receipt.json"])
        rr = json.loads(files["run-receipt.json"].read_text())
        executions.append({"id": f"historical_{name}", "kind": "analysis", "status": "completed",
            "started_at": "2026-10-07T00:00:00+00:00", "finished_at": "2026-10-07T23:59:59+00:00",
            "tool": "MESMER 7.1 local ARM64", "version": "7.1",
            "input_evidence_ids": [input_ev, test_ev], "output_evidence_ids": [out_ev],
            "receipt_evidence_ids": [rr_ev], "decisions": [f"Historical local control; recorded architecture={rr['architecture']}."]})

    provenance = {"schema_version": "compchemworld.case08.provenance/v1",
      "case_id": "case-08-end-to-end-rearrangement-claim", "evidence": evidence, "executions": executions,
      "decisions": [
        {"id": "scope", "choice": "Preformed-iBPR early competition with a qualitative precursor route map", "rationale": "The acquired sources support channel rates, a lumped i-BPR+NO coefficient, and qualitative R1+O2 / RO2 / O9 route connectivity. Species-specific post-open rates were not located, so no downstream flux is calculated.", "evidence_ids": [source_ids["article.xml"], source_ids["41467_2023_40675_MOESM1_ESM.docx"], source_ids["Toluene-ipso-HR-300-mesmer_out.xml"], downstream_id]},
        {"id": "method", "choice": "Closed-form kinetics checked against RK4", "rationale": "Mass closure, nonnegativity, and step-size comparison are computed from the same pinned rates.", "evidence_ids": output_ids}],
      "claims": [
        {"id": "new_no_competition", "statement": "For a preformed i-BPR population at 300 K and 1 atm, the stated lumped NO-loss scenario changes the modeled early branch populations; this is conditional kinetic screening, not aerosol yield or a complete oxidation mechanism.", "evidence_ids": [*output_ids, receipt_id],
         "quantities": [{"id": "p_c1_1ppbv_1p5s", "value": float(at15[1.0]["P-C1"]), "unit": "initial-population fraction", "system": "toluene-derived i-BPR", "population": "preformed i-BPR, unit initial population", "origin": "new_computation", "evidence_ids": [by_path[(output_dir / "early_competition.csv").relative_to(final).as_posix()]], "execution_ids": ["run_analytic_no_competition"], "conditions": {"temperature": {"value": 300, "unit": "K"}, "pressure": {"value": 1, "unit": "atm"}}, "reference_definition": "Analytic solution of two unimolecular ring-opening channels competing with lumped i-BPR+NO loss at 1 ppbv NO, t=1.5 s."}]},
        {"id": "precursor_route_scope", "statement": "The acquired paper/SI and archived R1+O2 model support a qualitative oxygenation/autoxidation route toward oxidized precursor species, including an O9-RO2 endpoint; this package does not calculate downstream route flux or aerosol mass yield.", "evidence_ids": [source_ids["article.xml"], source_ids["41467_2023_40675_MOESM1_ESM.docx"], source_ids["Toluene-ipso-HR-300-mesmer_out.xml"], downstream_id]},
        {"id": "historical_grain_controls", "statement": "Existing local ARM64 QD grain-size controls show an empirical comparison for the early R1a/R1b route; they do not constitute an HPC run or a rigorous uncertainty bound.", "evidence_ids": [by_path[(native / "reference-summary.json").relative_to(final).as_posix()], *[x["id"] for x in evidence if x["id"].endswith("_receipt")]]}]
    }
    (final / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n")
    (final / "claim.md").write_text(
        "# Conditional reference analysis\n\n"
        "This reference combines acquired public kinetic parameters, existing MESMER controls, and a newly run local analytic/RK4 competition screen. "
        "It is intentionally limited to a preformed toluene-derived i-BPR population at 300 K and 1 atm. The ring-opening rates are 0.164121 and 0.585048 s⁻¹ from the archived MESMER output; the article reports rounded values. The correction reverses the P-C1/P-C2 structures in the original Fig. 1a, so this reference preserves channel labels rather than assigning the corrected structures from the old figure.\n\n"
        "The new local screen compares those two unimolecular channels against the SI's 9.15×10⁻¹² cm³ molecule⁻¹ s⁻¹ lumped i-BPR+NO loss under ideal-gas ppbv conversion. It includes analytic populations, an independent RK4 check, and order-of-magnitude parameter stress tests. The NO coefficient's unit is inferred from reaction dimensionality and its temperature dependence is unspecified. Stress tests are scenarios, not confidence intervals.\n\n"
        "The copied g50/g200 MESMER runs are historical local ARM64 executions with their original input, output, and receipts. Their conditional R1b comparison is empirical, not a convergence proof; the associated g100 result and source model are retained only where referenced by the summary. No result here is a current HPC execution.\n\n"
        "The acquired paper/SI and archived R1+O₂ PES support qualitative R1b-RO₂→O₂/autoxidation connectivity toward O9-RO₂ and other oxidized precursors. Species-specific rates needed to quantify that downstream branch were not found, so no downstream flux or aerosol yield is calculated. The initial paper pathway fractions use a P-C2-derived excited population; they are distinct from this reference's preformed-iBPR + NO population. Accordingly this package is a traceable, bounded reference solution and requires independent scientific review; it does not claim a six-criterion PASS.\n", encoding="utf-8")
    print(json.dumps({"final": str(final), "new_execution": "local analytic/RK4 only",
                      "historical_controls": [x[0] for x in historic],
                      "outputs": [p.relative_to(final).as_posix() for p in output_dir.iterdir()]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
