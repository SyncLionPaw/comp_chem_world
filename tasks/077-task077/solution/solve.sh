#!/usr/bin/env bash
set -euo pipefail
SOURCE="${SOURCE:-/app/inputs}"
OUTPUT="${1:-/app/final}"
exec python3 - --source "$SOURCE" --output "$OUTPUT" <<'PY'
#!/usr/bin/env python3
"""Recompute case 02 geometry statistics from public SI tables and verify energies."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import pypdfium2 as pdfium

NUM = re.compile(r"(?<![A-Za-z])[-−]?\d+\s*\.\s*\d+[a-z]?(?!\w)")
START = re.compile(r"^\s*(\d+)\.\s*(GS|ES)(?:[a-z])?\b", re.I)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def num(token: str) -> float:
    return float(token.lower().rstrip("abcdefghijklmnopqrstuvwxyz").replace("−", "-").replace(" ", ""))


def geometry_rows(pdf: Path, first_page: int, last_page: int, ncols: int, *, es_only: bool = True):
    """Read complete printed geometry rows, tracking molecule/state across page breaks."""
    rows, mol, state = [], None, None
    reader = pdfium.PdfDocument(str(pdf))
    for page_idx in range(first_page - 1, last_page):
        text = reader[page_idx].get_textpage().get_text_range() or ""
        for line in text.splitlines():
            start = START.match(line)
            prefix = line[start.end():] if start else line
            if start:
                mol, state = int(start.group(1)), start.group(2).upper()
            hits = list(NUM.finditer(prefix))
            if len(hits) < ncols:
                continue
            hits = hits[-ncols:]
            before = prefix[:hits[0].start()].strip()
            is_eta = "η" in before or "\\eta" in before
            kind = "angle" if "∠" in before else ("dihedral" if is_eta else "bond")
            label = " ".join(before.replace("∠", "").replace("η", "").replace("\\eta", "").lower().split())
            label = re.sub(r"\bh\s+ald\b", "hald", label)
            if mol is None or state not in (("ES",) if es_only else ("GS", "ES")):
                continue
            if not label and kind != "dihedral":
                continue
            rows.append((mol, state, kind, label, [num(x.group(0)) for x in hits]))
    return rows


def moments(samples):
    xs = [it["err"] for it in samples]
    if not xs:
        raise ValueError("empty geometry sample group")
    mean = sum(xs) / len(xs)
    return mean, sum(abs(x) for x in xs) / len(xs), max(xs, key=abs), math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def article_energy_rows(main_pdf: Path):
    reader = pdfium.PdfDocument(str(main_pdf))
    text = "\n".join(reader[i].get_textpage().get_text_range() or "" for i in range(len(reader)))
    idx = text.find("Table 2.")
    if idx < 0:
        raise SystemExit("article Table 2 not found")
    block = text[idx:]
    energy_marker = block.find("Evert (eV)")
    if energy_marker < 0:
        raise SystemExit("article Table 2 energy subtable not found")
    entries = {}
    pattern = re.compile(r"^\s*(PBE0|ADMM-PBE0|sTDA@PBE0|sTDA@ADMM-PBE0)\s+(DZVP|TZVP|TZV2P|TZVP\+tzp)\s+(.+?)\s*$", re.I)
    for line in block[energy_marker:].splitlines():
        match = pattern.match(line)
        if not match:
            continue
        kernel, basis = match.group(1), match.group(2)
        values = [num(x) for x in NUM.findall(match.group(3))]
        if len(values) == 9:
            entries[(kernel, basis)] = {"Evert": values[0:3], "Ead": values[3:6], "Efl": values[6:9]}
    needed = [("PBE0", "DZVP"), ("PBE0", "TZVP"), ("PBE0", "TZV2P"),
              ("ADMM-PBE0", "TZVP+tzp"), ("sTDA@PBE0", "TZVP"),
              ("sTDA@ADMM-PBE0", "TZVP+tzp")]
    if any(key not in entries for key in needed):
        raise SystemExit(f"article Table 2 energy rows incomplete: {sorted(entries)}")
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="/app/inputs")
    ap.add_argument("--output", default="/app/final")
    args = ap.parse_args()
    source, out = Path(args.source), Path(args.output)
    si, mainpdf = source / "ct2c00144_si_001.pdf", source / "hehn2022_main.pdf"
    if not si.is_file() or not mainpdf.is_file():
        raise SystemExit("both public input PDFs are required")

    # SI Table 3 columns: CCSD=0, PBE0/TZVP=4, ADMM-PBE0/TZVP+tzp=8.
    table3 = geometry_rows(si, 10, 22, 12)
    # SI Table 14 columns: CCSD=0, sTDA@PBE0/TZVP=3, sTDA@ADMM/TZVP+tzp=4.
    table14 = geometry_rows(si, 50, 55, 5)
    if len(table3) < 150 or len(table14) < 150:
        raise SystemExit(f"incomplete PDF geometry extraction: Table3={len(table3)}, Table14={len(table14)}")

    samples = defaultdict(list)
    for mol, state, quantity, label, cols in table3:
        for kernel, basis, idx in (("PBE0", "TZVP", 4), ("ADMM-PBE0", "TZVP+tzp", 8)):
            key = f"{kernel}|{basis}|{quantity}"
            samples[key].append({"mol": mol, "label": label, "err": round(cols[idx] - cols[0], 8)})
    for mol, state, quantity, label, cols in table14:
        for kernel, basis, idx in (("sTDA@PBE0", "TZVP", 3), ("sTDA@ADMM-PBE0", "TZVP+tzp", 4)):
            key = f"{kernel}|{basis}|{quantity}"
            samples[key].append({"mol": mol, "label": label, "err": round(cols[idx] - cols[0], 8)})

    expected_geometry = {f"{kernel}|{basis}|{quantity}" for kernel,basis in (
        ("PBE0","TZVP"),("ADMM-PBE0","TZVP+tzp"),("sTDA@PBE0","TZVP"),("sTDA@ADMM-PBE0","TZVP+tzp")) for quantity in ("bond","angle","dihedral")}
    if set(samples) != expected_geometry:
        raise SystemExit(f"incomplete geometry groups: got {sorted(samples)}")
    energy = article_energy_rows(mainpdf)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "statistics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["row_type", "kernel", "basis", "quantity", "me", "mae", "max", "std", "evidence_status", "source_table"])
        sources = {"PBE0": "SI Table 3", "ADMM-PBE0": "SI Table 3", "sTDA@PBE0": "SI Table 14", "sTDA@ADMM-PBE0": "SI Table 14"}
        for kernel,basis in (("PBE0","TZVP"),("ADMM-PBE0","TZVP+tzp"),("sTDA@PBE0","TZVP"),("sTDA@ADMM-PBE0","TZVP+tzp")):
            for quantity in ("bond","angle","dihedral"):
                key=f"{kernel}|{basis}|{quantity}"
                stats=moments(samples[key])
                writer.writerow(["recomputed-from-raw",kernel,basis,quantity,*(f"{x:.8f}" for x in stats),"recomputed-from-raw",sources[kernel]])
        energy_source = {"Evert": 27, "Ead": 46, "Efl": 51}
        for kernel,basis in (("PBE0","DZVP"),("PBE0","TZVP"),("PBE0","TZV2P"),("ADMM-PBE0","TZVP+tzp"),("sTDA@PBE0","TZVP"),("sTDA@ADMM-PBE0","TZVP+tzp")):
            for quantity in ("Evert","Ead","Efl"):
                vals=energy[(kernel,basis)][quantity]
                writer.writerow(["verified-against-SI",kernel,basis,quantity,f"{vals[0]:.2f}",f"{vals[1]:.2f}","",f"{vals[2]:.2f}","verified-against-SI",f"SI Table {energy_source[quantity]}"])

    with (out / "provenance.json").open("w", encoding="utf-8") as f:
        json.dump({"inputs": {si.name: sha(si), mainpdf.name: sha(mainpdf)}, "samples": dict(samples),
                   "derivations": {"PBE0/TZVP and ADMM-PBE0/TZVP+tzp": "SI Table 3; per-molecule DFT minus EOM-CCSD.",
                                   "sTDA@PBE0/TZVP and sTDA@ADMM-PBE0/TZVP+tzp": "SI Table 14; per-molecule sTDA minus EOM-CCSD. M14 footnote-c printed geometry retained.",
                                   "energy rows": "Verify-only values transcribed from article Table 2; Evert -> SI Table 27 (Turbomole reference), Ead -> SI Table 46 (EOM-CCSD reference), Efl -> SI Table 51 (Turbomole reference)."}}, f, indent=2)

    dihedral = {kernel: moments(samples[f"{kernel}|{basis}|dihedral"]) for kernel,basis in (
        ("PBE0","TZVP"),("ADMM-PBE0","TZVP+tzp"),("sTDA@PBE0","TZVP"),("sTDA@ADMM-PBE0","TZVP+tzp"))}
    ordered = [("PBE0/TZVP",dihedral["PBE0"][0],dihedral["PBE0"][1]),
               ("ADMM-PBE0/TZVP+tzp",dihedral["ADMM-PBE0"][0],dihedral["ADMM-PBE0"][1]),
               ("sTDA@PBE0/TZVP",dihedral["sTDA@PBE0"][0],dihedral["sTDA@PBE0"][1]),
               ("sTDA@ADMM-PBE0/TZVP+tzp",dihedral["sTDA@ADMM-PBE0"][0],dihedral["sTDA@ADMM-PBE0"][1])]
    diffs = "; ".join(f"{name}: ME {me:.2f}°, MAE {mae:.2f}°" for name,me,mae in ordered)
    smean = (dihedral["sTDA@PBE0"][0]+dihedral["sTDA@ADMM-PBE0"][0])/2
    dmean = (dihedral["PBE0"][0]+dihedral["ADMM-PBE0"][0])/2
    if smean > 0:
        bias_direction = "positive"
    elif smean < 0:
        bias_direction = "negative"
    else:
        bias_direction = "zero-net"
    if smean > dmean:
        relative_direction = "higher"
    elif smean < dmean:
        relative_direction = "lower"
    else:
        relative_direction = "equal"
    (out / "report.md").write_text(
        "# Response-kernel geometry and energy comparison\n\n"
        "All four geometry kernels were recomputed per molecule against the EOM-CCSD column: PBE0 and ADMM-PBE0 from SI Table 3, and both sTDA variants from SI Table 14. Samples preserve each printed bond/angle label; the η rows use an empty label. Statistics use the signed DFT-minus-CCSD differences and population STD (ddof=0). Energy statistics are verify-only transcriptions from article Table 2; provenance records the corresponding SI tables and reference methods.\n\n"
        f"Dihedral results from the submitted per-molecule samples are {diffs}. The two sTDA means average {smean:.2f}°, versus {dmean:.2f}° for PBE0 and ADMM-PBE0; the combined signed sTDA error is {bias_direction}, and its mean is {relative_direction} than the PBE0/ADMM-PBE0 mean relative to EOM-CCSD.\n\n"
        "M14 footnote c: the default aEX=0.2 calculation dissociates; aEX >= 0.25 can recover a geometry. That recovered geometry is not a normal minimum at the default parameter.\n", encoding="utf-8")


if __name__ == "__main__":
    main()

PY
