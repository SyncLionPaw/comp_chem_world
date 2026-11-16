#!/bin/sh
set -eu
python3 - --assets "${APP:-/app}/assets" --output "${APP:-/app}/final" <<'__P04_SCIENTIFIC_SOLUTION__'
#!/usr/bin/env python3
"""Reconstruct the toluene ipso-BPR profile directly from public native assets."""
import argparse
import csv
import json
import re
from pathlib import Path

FACTOR = 627.509
SPECIES = {
    "BPR": ("Toluene-iBPR-DFT.log", "Toluene-iBPR-F12.out"),
    "C1": ("Toluene-iBPR-TS-C1-DFT.log", "Toluene-iBPR-TS-C1-F12.out"),
    "C2": ("Toluene-iBPR-TS-C2-DFT.log", "Toluene-iBPR-TS-C2-F12.out"),
    "P-C1": ("P-C1-DFT.log", "P-C1-F12.out"),
    "P-C2": ("P-C2-DFT.log", "P-C2-F12.out"),
}
LABELS = {
    "zpe_au": "Zero-point correction=",
    "e_zero_point_au": "Sum of electronic and zero-point Energies=",
    "e_f12_au": "RCCSD(T)-F12A/cc-pVDZ-F12 energy=",
}


def extract(path, label):
    lines = path.read_text(errors="replace").splitlines()
    matches = [(i + 1, line) for i, line in enumerate(lines) if label in line]
    if not matches: raise ValueError(f"missing label {label} in {path}")
    line_no, line = matches[-1]
    value = float(re.search(re.escape(label) + r"\s*([-+\d.eEdD]+)", line).group(1).replace("D", "E"))
    return line_no, line.strip(), value


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    root = a.assets / "Toluene-iBPR-rearrangment"
    values, records = {}, []
    for sp, (dft_name, f12_name) in SPECIES.items():
        dft, f12 = root / dft_name, root / f12_name
        zline, zlabel, zpe = extract(dft, LABELS["zpe_au"])
        sline, slabel, sumzpe = extract(dft, LABELS["e_zero_point_au"])
        fline, flabel, f12e = extract(f12, LABELS["e_f12_au"])
        values[sp] = {"zpe": zpe, "sumzpe": sumzpe, "elec": sumzpe-zpe, "f12": f12e,
                      "file_dft": dft_name, "file_f12": f12_name}
        for q, path, line, label, value in (("zpe_au", dft, zline, zlabel, zpe),
                                             ("e_zero_point_au", dft, sline, slabel, sumzpe),
                                             ("e_f12_au", f12, fline, flabel, f12e)):
            records.append({"species": sp, "quantity": q,
                            "source_file": "assets/Toluene-iBPR-rearrangment/" + path.name,
                            "label": label, "line_number": line, "value_au": value})
    pub = {"C1": 18.8, "C2": 17.9, "P-C1": -51.7, "P-C2": -49.4}
    adopted, alternatives = {}, {}
    schemes = {"dft_zero_point": "zpe", "dft_electronic": "elec", "dft_gibbs": None, "f12_only": "f12"}
    gibbs = {}
    for sp, (dft_name, _) in SPECIES.items():
        lines = (root / dft_name).read_text(errors="replace").splitlines()
        found = [float(re.search(r"Sum of electronic and thermal Free Energies=\s*([-+\d.]+)", line).group(1))
                 for line in lines if "Sum of electronic and thermal Free Energies=" in line]
        gibbs[sp] = found[-1]
    for sp in ("C1", "C2", "P-C1", "P-C2"):
        v = values[sp]
        adopted[sp] = ((v["f12"]-values["BPR"]["f12"]) + (v["zpe"]-values["BPR"]["zpe"])) * FACTOR
        alternatives["dft_zero_point"] = alternatives.get("dft_zero_point", {})
        alternatives["dft_zero_point"][sp] = (v["sumzpe"]-values["BPR"]["sumzpe"]) * FACTOR
        alternatives["dft_electronic"] = alternatives.get("dft_electronic", {})
        alternatives["dft_electronic"][sp] = (v["elec"]-values["BPR"]["elec"]) * FACTOR
        alternatives["dft_gibbs"] = alternatives.get("dft_gibbs", {})
        alternatives["dft_gibbs"][sp] = (gibbs[sp]-gibbs["BPR"]) * FACTOR
        alternatives["f12_only"] = alternatives.get("f12_only", {})
        alternatives["f12_only"][sp] = (v["f12"]-values["BPR"]["f12"]) * FACTOR
    a.output.mkdir(parents=True, exist_ok=True)
    with (a.output / "bpr_profile.csv").open("w", newline="", encoding="utf-8") as f:
        cols = ["species", "file_dft", "file_f12", "e_electronic_au", "zpe_au", "e_zero_point_au", "e_f12_au", "derived_kcal_per_mol"]
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for sp, v in values.items():
            w.writerow({"species": sp, "file_dft": "assets/Toluene-iBPR-rearrangment/"+v["file_dft"],
                        "file_f12": "assets/Toluene-iBPR-rearrangment/"+v["file_f12"],
                        "e_electronic_au": v["elec"], "zpe_au": v["zpe"], "e_zero_point_au": v["sumzpe"],
                        "e_f12_au": v["f12"], "derived_kcal_per_mol": 0 if sp == "BPR" else adopted[sp]})
    output = {"rule": {"electronic_source": "f12", "correction_source": "dft_zpe", "reference_species": "BPR",
                       "unit": "kcal/mol", "hartree_to_kcal": FACTOR,
                       "rejected_alternatives": [{"scheme": k, "values_kcal_per_mol": v} for k, v in alternatives.items()]},
              "derived_values_kcal_per_mol": adopted, "published_values_kcal_per_mol": pub}
    (a.output / "bpr_profile.json").write_text(json.dumps(output, indent=2)+"\n")
    with (a.output / "energy_rule.md").open("w") as f:
        f.write("# Composite energy rule\n\nUse the Molpro F12 electronic difference plus the Gaussian DFT zero-point difference, each relative to BPR. This rule gives " + ", ".join(f"{adopted[x]:.3f}" for x in ("C1","C2","P-C1","P-C2")) + " kcal/mol.\n\n")
        for k, vals in alternatives.items():
            f.write(f"## Rejected {k.replace('_',' ')}\n\n")
            f.write("C1, C2, P-C1, P-C2: " + ", ".join(f"{vals[x]:.3f}" for x in ("C1","C2","P-C1","P-C2")) + " kcal/mol.\n\n")
            f.write("Absolute deviations from the published profile in that order: " + ", ".join(f"{abs(vals[x]-pub[x]):.3f}" for x in ("C1","C2","P-C1","P-C2")) + " kcal/mol.\n\n")
    (a.output / "native_parse_manifest.json").write_text(json.dumps({"records": records}, indent=2)+"\n")


if __name__ == "__main__": main()
__P04_SCIENTIFIC_SOLUTION__
