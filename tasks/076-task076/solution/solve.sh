#!/usr/bin/env bash
set -euo pipefail
SOURCE="${SOURCE:-/app/inputs}"
OUTPUT="${1:-/app/final}"
exec python3 - --source "$SOURCE" --output "$OUTPUT" <<'PY'
#!/usr/bin/env python3
"""Recompute case 01 statistics from geometry rows printed in the public SI PDF."""
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


def val(token: str) -> float:
    return float(token.lower().rstrip("abcdefghijklmnopqrstuvwxyz").replace("−", "-").replace(" ", ""))


def parse_rows(pdf: Path, first_page: int, last_page: int, ncols: int):
    rows = []
    mol = state = None
    reader = pdfium.PdfDocument(str(pdf))
    for page_idx in range(first_page - 1, last_page):
        text = reader[page_idx].get_textpage().get_text_range() or ""
        for line in text.splitlines():
            sm = START.match(line)
            if sm:
                mol, state = int(sm.group(1)), sm.group(2).upper()
                prefix = line[sm.end():]
            else:
                prefix = line
            hits = list(NUM.finditer(prefix))
            if len(hits) < ncols:
                continue
            hits = hits[-ncols:]
            label = prefix[:hits[0].start()].strip()
            label = re.sub(r"^\s*\d+\.\s*(?:GS|ES)\s*", "", label, flags=re.I)
            is_dihedral = "η" in label or "\\eta" in label
            kind = "angle" if "∠" in prefix[:hits[0].start()] else ("dihedral" if is_dihedral else "bond_length")
            label = label.replace("∠", "").replace("η", "").replace("\\eta", "")
            label = " ".join(label.lower().split())
            label = re.sub(r"\bh\s+ald\b", "hald", label)
            # The published η row has no atom label; the case contract represents it as an empty label.
            if mol is None or state not in ("GS", "ES") or (not label and not is_dihedral):
                continue
            nums = [val(m.group(0)) for m in hits]
            rows.append({"mol": mol, "variant": state, "label": label, "kind": kind, "nums": nums})
    return rows


def moments(samples):
    xs = [x["err"] for x in samples]
    if not xs:
        raise ValueError("empty sample group")
    mean = sum(xs) / len(xs)
    return mean, sum(abs(x) for x in xs) / len(xs), max(xs, key=abs), math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="/app/inputs")
    ap.add_argument("--output", default="/app/final")
    args = ap.parse_args()
    source, out = Path(args.source), Path(args.output)
    si = source / "ct2c00144_si_001.pdf"
    main_pdf = source / "hehn2022_main.pdf"
    if not si.is_file() or not main_pdf.is_file():
        raise SystemExit("both public input PDFs are required")
    # Tables 3 and 4: MOLOPT and ccGRB geometries, respectively.
    data = parse_rows(si, 10, 22, 12)
    data += parse_rows(si, 24, 37, 9)
    if len(data) < 500:
        raise SystemExit(f"SI extraction incomplete: only {len(data)} geometry rows parsed")
    combinations = [
        ("dzp", "DZVP", 3, 6), ("dzp", "TZVP", 4, 7), ("dzp", "TZV2P", 5, 9),
        ("tzp", "TZVP", 4, 8), ("tzp", "TZV2P", 5, 10),
        ("tz2p", "TZV2P", 5, 11),
    ]
    # ccGRB basis columns are PBE0 D/T/Q then ADMM D/T/Q.
    combinations += [("dzp", "cc-GRB-D", 3, 6), ("tzp", "cc-GRB-T", 4, 7), ("tz2p", "cc-GRB-Q", 5, 8)]
    samples_by = defaultdict(list)
    for r in data:
        is_ccgrb = len(r["nums"]) == 9
        for abs_, pbs, pbe0col, admmcol in combinations:
            if is_ccgrb != pbs.startswith("cc-"):
                continue
            if r["kind"] == "dihedral" and r["variant"] != "ES":
                continue
            key = f'{r["kind"]}|{abs_}|{pbs}|{r["variant"]}'
            samples_by[key].append({"mol": r["mol"], "label": r["label"], "err": round(r["nums"][admmcol] - r["nums"][pbe0col], 8)})
    expected = 45
    if len(samples_by) != expected:
        raise SystemExit(f"expected {expected} statistic groups, parsed {len(samples_by)}; sample counts=" + str({k: len(v) for k,v in samples_by.items()}))
    out.mkdir(parents=True, exist_ok=True)
    with (out / "statistics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["quantity", "variant", "pbs", "abs", "me", "mae", "max", "std"])
        for key in sorted(samples_by):
            quantity, abs_, pbs, variant = key.split("|")
            vals = moments(samples_by[key])
            w.writerow([quantity, variant, pbs, abs_, *(f"{x:.8f}" for x in vals)])
    with (out / "provenance.json").open("w", encoding="utf-8") as f:
        json.dump({"inputs": {si.name: sha(si), main_pdf.name: sha(main_pdf)}, "samples": dict(samples_by),
                   "sample_sources": {key: ("SI Table 4" if key.split("|")[2].startswith("cc-") else "SI Table 3") for key in samples_by},
                   "derivation": "ADMM-PBE0 minus conventional PBE0 using same primary basis; per-molecule rows extracted from SI Tables 3 and 4; population standard deviation (ddof=0)."}, f, indent=2)
    dzp = [moments(samples_by[f"bond_length|dzp|{pbs}|ES"])[1] for pbs in ("DZVP", "TZVP", "TZV2P")]
    tzp = [moments(samples_by[f"bond_length|tzp|{pbs}|ES"])[1] for pbs in ("TZVP", "TZV2P")]
    tz2p = moments(samples_by["bond_length|tz2p|TZV2P|ES"])[1]
    dzp_mean = sum(dzp) / len(dzp)
    higher_mean = (sum(tzp) + tz2p) / (len(tzp) + 1)
    if higher_mean < dzp_mean:
        trend = "lower"
        verdict = "support a reduction in excited-state bond-length error with the larger auxiliary bases"
    elif higher_mean > dzp_mean:
        trend = "higher"
        verdict = "do not show a reduction in excited-state bond-length error with the larger auxiliary bases"
    else:
        trend = "equal"
        verdict = "show no average change in excited-state bond-length error with the larger auxiliary bases"
    (out / "report.md").write_text(
        "# ADMM auxiliary-basis convergence (recomputed from SI)\n\n"
        f"Parsed {len(data)} per-molecule geometry rows from SI Tables 3 and 4; the 45 groups are calculated from ADMM-PBE0 minus conventional PBE0 at the same primary basis. The signed maximum retains the sign of the largest-absolute sample, and STD is population standard deviation (ddof=0). Input SHA-256 is recorded in `provenance.json`.\n\n"
        f"For excited-state bond lengths, dzp MAEs across DZVP/TZVP/TZV2P are {', '.join(f'{x:.3f}' for x in dzp)} pm; tzp MAEs at TZVP/TZV2P are {', '.join(f'{x:.3f}' for x in tzp)} pm; tz2p/TZV2P is {tz2p:.3f} pm. The mean of the tzp/tz2p MAEs is {higher_mean:.3f} pm, {trend} than the dzp mean of {dzp_mean:.3f} pm; these results {verdict}.\n\n"
        "M8/M35 eclipsed transition-state conformations are not separate entries in the SI benchmark data; M10 and M30 use the stated C2v-constrained references, with M30 B1. Dihedral definitions follow SI Table 1.\n", encoding="utf-8")


if __name__ == "__main__":
    main()

PY
