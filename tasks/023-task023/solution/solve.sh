#!/bin/sh
set -eu
python3 - --assets "${APP:-/app}/assets" --output "${APP:-/app}/final" <<'__P04_SCIENTIFIC_SOLUTION__'
#!/usr/bin/env python3
"""Extract MESMER rates from native XML and fit modified Arrhenius curves."""
import argparse
import csv
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

NS = {"me": "http://www.chem.leeds.ac.uk/mesmer"}
R = 0.00198720425864


def extract(path):
    root = ET.parse(path).getroot()
    pt = root.find(".//me:PTpair", NS)
    rate = root.find(".//me:analysis/me:rateList", NS)
    if pt is None or rate is None: raise ValueError(f"missing PTpair/rateList in {path}")
    r = {e.attrib["toRef"]: e for e in rate.findall("me:firstOrderRate", NS)}
    c1, c2 = r["ringopen-prod1"], r["ringopen-prod2"]
    return {"temperature_K": float(pt.attrib["T"]), "pressure_Torr": float(pt.attrib["P"]),
            "bath_gas": pt.attrib["bathGas"], "k_C1_per_s": float(c1.text), "k_C2_per_s": float(c2.text),
            "k_total_per_s": float(c1.text)+float(c2.text), "C1_fromRef": c1.attrib["fromRef"],
            "C1_toRef": c1.attrib["toRef"], "C2_fromRef": c2.attrib["fromRef"], "C2_toRef": c2.attrib["toRef"]}


def fit(temps, rates, name):
    t = np.asarray(temps, dtype=float); y = np.log(np.asarray(rates, dtype=float)); tref = 300.0
    X = np.column_stack((np.ones_like(t), np.log(t/tref), 1/t))
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ b
    return {"quantity": name, "A_per_s": math.exp(float(b[0])), "n_T_exponent": float(b[1]),
            "Ea_kcal_per_mol": float(-b[2]*R), "T_ref_K": tref, "fit_min_K": 200,
            "fit_max_K": 500, "n_points": len(t), "max_ln_k_deviation": float(np.max(np.abs(pred-y))),
            "formula": "k(T)=A*(T/T_ref_K)^n*exp(-Ea_kcal_per_mol/(R*T))"}


def main():
    p = argparse.ArgumentParser(); p.add_argument("--assets", type=Path, required=True); p.add_argument("--output", type=Path, required=True); a=p.parse_args()
    files = sorted(a.assets.rglob("Toluene-ipso-HR-*-mesmer_out.xml"), key=lambda p: extract(p)["temperature_K"])
    values=[]
    for path in files:
        rec=extract(path); rec["source_file"]="assets/"+path.relative_to(a.assets).as_posix(); values.append(rec)
    a.output.mkdir(parents=True, exist_ok=True)
    cols=["source_file","temperature_K","pressure_Torr","bath_gas","k_C1_per_s","k_C2_per_s","k_total_per_s","C1_fromRef","C1_toRef","C2_fromRef","C2_toRef"]
    with (a.output/"rates_by_temperature.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(values)
    branches=[{"temperature_K":r["temperature_K"],"branching_C1_percent":100*r["k_C1_per_s"]/r["k_total_per_s"]} for r in values]
    with (a.output/"branching_curve.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["temperature_K","branching_C1_percent"]);w.writeheader();w.writerows(branches)
    temps=[r["temperature_K"] for r in values]
    fits={"C1":fit(temps,[r["k_C1_per_s"] for r in values],"k_C1_full_range"),
          "C2":fit(temps,[r["k_C2_per_s"] for r in values],"k_C2_full_range"),
          "total":fit(temps,[r["k_total_per_s"] for r in values],"k_total_full_range")}
    (a.output/"arrhenius_fit.json").write_text(json.dumps(fits,indent=2)+"\n")
    (a.output/"derivation_notes.md").write_text(
        "# Rate reconstruction\n\nRates were read from the `<me:analysis>/<me:rateList>` first-order reactions, before comparing the published split. The C1 branching fraction is temperature-dependent: 12.863% at 200 K, 21.907% at 300 K, and 31.030% at 500 K. The 21.907% value therefore applies to 300 K. All 23 calculations use 760 Torr N2; a single pressure cannot establish pressure dependence.\n")


if __name__ == "__main__": main()
__P04_SCIENTIFIC_SOLUTION__
